"""Real concurrency tests.

Rules for every test in this file:

* **Each worker thread gets its own SQLAlchemy Session.** A Session is not
  thread-safe; sharing one across threads produces both false passes (the race
  can't happen inside a single transaction) and flaky failures.
* **Worker exceptions are never swallowed.** Each worker appends to an `errors`
  list which is asserted empty, and `pytest.ini` promotes
  `PytestUnhandledThreadExceptionWarning` to an error, so a thread that dies
  cannot leave a green test.
* **A queued test must prove it queued.** Two threads that merely start together
  are not evidence of a critical section; where the property under test is "the
  second writer waits", the test asserts the second writer finished *after* the
  first one released the lock.

What this file does and does not prove
--------------------------------------
By default these run on file-backed SQLite, whose concurrency model is a
whole-database write lock, NOT PostgreSQL's per-row `SELECT ... FOR UPDATE`.
They therefore prove that the *application* takes its locks before it makes a
decision, and that its invariants hold when two writers genuinely contend.

They do **not** verify PostgreSQL's row-lock semantics. Production runs on
managed PostgreSQL. To exercise that path, run the suite against a real server:

    EVIDENTIA_TEST_DATABASE_URL=postgresql+psycopg2://user:pass@localhost/evidentia_test \
        python -m pytest tests/test_concurrency.py

The PostgreSQL-specific tests below skip (loudly) when that is unset.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Callable, List

import pytest

from sqlalchemy import select

from app.core import security
from app.core.config import get_settings
from app.models.db_models import (
    JOB_STATE_QUEUED,
    JOB_STATE_RUNNING,
    Company,
    CompanyMember,
    Document,
    DocumentBlob,
    DocumentVersion,
    IngestionJob,
    RefreshToken,
    User,
)
from app.repositories import memberships as memberships_repo
from app.services.job_queue import DatabaseJobQueue
from tests.conftest import VALID_PASSWORD, register

NEW_PASSWORD = "an-entirely-different-password"

POSTGRES_URL = os.getenv("EVIDENTIA_TEST_DATABASE_URL", "").strip()

requires_postgres = pytest.mark.skipif(
    not POSTGRES_URL.startswith("postgresql"),
    reason=(
        "PostgreSQL row-lock semantics are NOT verified locally. Set "
        "EVIDENTIA_TEST_DATABASE_URL=postgresql+psycopg2://... to run against the "
        "engine production actually uses."
    ),
)


def run_concurrently(fns: List[Callable[[], None]]) -> List[BaseException]:
    """Run each callable in its own thread; return every exception raised."""
    errors: List[BaseException] = []
    lock = threading.Lock()
    barrier = threading.Barrier(len(fns))

    def wrap(fn: Callable[[], None]) -> Callable[[], None]:
        def inner() -> None:
            try:
                barrier.wait(timeout=10)  # maximise the overlap
                fn()
            except BaseException as exc:  # noqa: BLE001 - surfaced, never swallowed
                with lock:
                    errors.append(exc)

        return inner

    threads = [threading.Thread(target=wrap(fn)) for fn in fns]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    for t in threads:
        assert not t.is_alive(), "a worker thread hung"
    return errors


def _live_refresh_tokens(session_factory, email: str) -> int:
    inspect = session_factory()
    try:
        user = inspect.query(User).filter(User.email == email).one()
        return (
            inspect.query(RefreshToken)
            .filter(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .count()
        )
    finally:
        inspect.close()


# ==========================================================================
# H1 — the password decision and the session issuance are ONE critical section
# ==========================================================================


def test_login_with_the_old_password_cannot_survive_a_concurrent_reset(
    client, session_factory, outbox, monkeypatch
):
    """A login that approved the OLD password must never yield a usable session
    once a concurrent password reset has committed.

    The original bug: the password was verified *before* the user lock was taken.
    A login could approve the old password, pause, let the reset change the
    password and revoke every session, then resume under the lock, re-read the
    user, and mint a fresh session carrying the NEW token_version — a fully live
    credential produced by a password that had just been reset away.

    `verify_password` is instrumented to hold the window open. With the fix the
    lock is already held when it runs, so the reset cannot interleave there at all.
    """
    acct = register(client, "login-vs-reset@acme.co")

    outbox.clear()
    client.post("/api/auth/password-reset/request", json={"email": acct.email})
    reset_token = outbox[0].body.split("token=")[1].split()[0]

    verify_started = threading.Event()
    reset_done = threading.Event()
    real_verify = security.verify_password

    def slow_verify(plain: str, hashed: str) -> bool:
        verify_started.set()
        reset_done.wait(timeout=3.0)
        return real_verify(plain, hashed)

    monkeypatch.setattr(security, "verify_password", slow_verify)
    out: dict = {}

    def do_login() -> None:
        res = client.post(
            "/api/auth/login", json={"email": acct.email, "password": VALID_PASSWORD}
        )
        out["login_status"] = res.status_code
        out["login_body"] = res.json() if res.status_code == 200 else None

    def do_reset() -> None:
        verify_started.wait(timeout=10.0)
        out["reset_status"] = client.post(
            "/api/auth/password-reset/confirm",
            json={"token": reset_token, "password": NEW_PASSWORD},
        ).status_code
        reset_done.set()

    errors = run_concurrently([do_login, do_reset])
    reset_done.set()
    assert errors == [], f"worker raised: {errors}"
    assert out["reset_status"] == 200, "the password reset must have won"

    # Whichever order they committed in, nothing minted from the OLD password may
    # still be exchangeable for access.
    body = out.get("login_body")
    if body:
        assert (
            client.get(
                "/api/reports", headers={"Authorization": f"Bearer {body['accessToken']}"}
            ).status_code
            == 401
        ), "an access token issued from the OLD password survived the reset"
        assert (
            client.post(
                "/api/auth/refresh", json={"refreshToken": body["refreshToken"]}
            ).status_code
            == 401
        ), "a refresh token issued from the OLD password survived the reset"

    assert _live_refresh_tokens(session_factory, acct.email) == 0, (
        "a refresh token survived the password reset"
    )

    monkeypatch.setattr(security, "verify_password", real_verify)
    assert (
        client.post(
            "/api/auth/login", json={"email": acct.email, "password": VALID_PASSWORD}
        ).status_code
        == 401
    ), "the old password still authenticates after the reset"
    assert (
        client.post(
            "/api/auth/login", json={"email": acct.email, "password": NEW_PASSWORD}
        ).status_code
        == 200
    ), "the new password does not authenticate after the reset"


def test_login_racing_logout_all_leaves_no_session_behind(client, session_factory, monkeypatch):
    """Logout-all must serialize against session *issuance*, not just revocation.

    A login whose password check ran before the lock could commit a brand-new
    refresh token after the revocation sweep had already passed over the user.
    """
    acct = register(client, "login-vs-logoutall@acme.co")

    verify_started = threading.Event()
    logout_done = threading.Event()
    real_verify = security.verify_password

    def slow_verify(plain: str, hashed: str) -> bool:
        verify_started.set()
        logout_done.wait(timeout=3.0)
        return real_verify(plain, hashed)

    monkeypatch.setattr(security, "verify_password", slow_verify)
    out: dict = {}

    def do_login() -> None:
        res = client.post(
            "/api/auth/login", json={"email": acct.email, "password": VALID_PASSWORD}
        )
        out["login"] = res.status_code
        out["body"] = res.json() if res.status_code == 200 else None

    def do_logout_all() -> None:
        verify_started.wait(timeout=10.0)
        out["logout_all"] = acct.post("/api/auth/logout-all").status_code
        logout_done.set()

    errors = run_concurrently([do_login, do_logout_all])
    logout_done.set()
    assert errors == [], f"worker raised: {errors}"
    assert out["logout_all"] == 200

    # The login is allowed to win the lock and issue a session — but then it must
    # have committed BEFORE the sweep, so the sweep must have revoked it.
    body = out.get("body")
    if body:
        assert (
            client.post(
                "/api/auth/refresh", json={"refreshToken": body["refreshToken"]}
            ).status_code
            == 401
        ), "a session issued during logout-all outlived it"
    assert _live_refresh_tokens(session_factory, acct.email) == 0


def test_refresh_racing_logout_all_cannot_survive(client, session_factory):
    """A refresh token minted concurrently with logout-all must not outlive it.

    The race: refresh rotates the parent and issues a child; logout-all revokes
    "all" tokens and bumps token_version. If they interleave without a lock, the
    child can be written *after* the revocation sweep and survive — a fully valid
    session that outlives the user's own "sign out everywhere".
    """
    acct = register(client, "race-logout@acme.co")
    parent = acct.refresh

    def do_refresh() -> None:
        client.post("/api/auth/refresh", json={"refreshToken": parent})

    def do_logout_all() -> None:
        acct.post("/api/auth/logout-all")

    errors = run_concurrently([do_refresh, do_logout_all])
    assert errors == [], f"worker raised: {errors}"

    assert _live_refresh_tokens(session_factory, acct.email) == 0, (
        "a refresh token survived logout-all"
    )
    assert acct.get("/api/reports").status_code == 401, "the old access token survived"


def test_refresh_racing_password_reset_cannot_survive(client, session_factory, outbox):
    acct = register(client, "race-reset@acme.co")
    parent = acct.refresh

    outbox.clear()
    client.post("/api/auth/password-reset/request", json={"email": acct.email})
    token = outbox[0].body.split("token=")[1].split()[0]

    def do_refresh() -> None:
        client.post("/api/auth/refresh", json={"refreshToken": parent})

    def do_reset() -> None:
        client.post(
            "/api/auth/password-reset/confirm",
            json={"token": token, "password": NEW_PASSWORD},
        )

    errors = run_concurrently([do_refresh, do_reset])
    assert errors == [], f"worker raised: {errors}"

    assert _live_refresh_tokens(session_factory, acct.email) == 0, (
        "a refresh token survived the password reset"
    )

    inspect = session_factory()
    try:
        version = inspect.query(User).filter(User.email == acct.email).one().token_version
    finally:
        inspect.close()
    # Exactly one reset committed, so exactly one bump. ">= 1" would also pass with
    # a lost update, which is the bug the atomic UPDATE exists to prevent.
    assert version == 1, f"expected exactly 1 token_version bump, got {version}"


def test_concurrent_logout_all_bumps_token_version_once_per_accepted_call(
    client, session_factory
):
    """token_version must be an atomic UPDATE, not an ORM read/modify/write.

    Read/modify/write means two concurrent bumps both read N and both write N+1 —
    a lost update. The version still moves, so the bug is invisible unless you
    count. Each *accepted* (200) logout-all must move the counter by exactly one;
    the calls whose access token was already stranded (401) must not move it at all.
    """
    acct = register(client, "bump@acme.co")

    inspect = session_factory()
    try:
        before = inspect.query(User).filter(User.email == acct.email).one().token_version
    finally:
        inspect.close()

    logins = [
        client.post(
            "/api/auth/login", json={"email": acct.email, "password": VALID_PASSWORD}
        ).json()
        for _ in range(4)
    ]

    codes: List[int] = []
    lock = threading.Lock()

    def logout_all(payload) -> None:
        res = client.post(
            "/api/auth/logout-all",
            headers={"Authorization": f"Bearer {payload['accessToken']}"},
        )
        assert res.status_code in (200, 401), res.text
        with lock:
            codes.append(res.status_code)

    errors = run_concurrently([lambda p=p: logout_all(p) for p in logins])
    assert errors == [], f"worker raised: {errors}"

    inspect = session_factory()
    try:
        after = inspect.query(User).filter(User.email == acct.email).one().token_version
    finally:
        inspect.close()

    accepted = codes.count(200)
    assert accepted >= 1, "every logout-all was rejected; the test proved nothing"
    assert after - before == accepted, (
        f"lost update: {accepted} logout-all calls were accepted but the counter "
        f"moved by {after - before}"
    )


def test_token_version_bump_is_atomic_not_read_modify_write(session_factory):
    """Directly exercise the primitive with N independent sessions.

    An ORM read/modify/write (`user.token_version = user.token_version + 1`) loses
    updates under concurrency: several workers read the same N and all write N+1.
    Only an atomic `UPDATE ... SET token_version = token_version + 1` is safe.
    """
    from app.repositories import users as users_repo

    setup = session_factory()
    try:
        user = users_repo.create_user(
            setup, email="atomic@acme.co", hashed_password=security.hash_password("x" * 14)
        )
        setup.commit()
        user_id = user.id
    finally:
        setup.close()

    workers = 12

    def bump() -> None:
        session = session_factory()
        try:
            users_repo.bump_token_version_by_id(session, user_id)
            session.commit()
        finally:
            session.close()

    errors = run_concurrently([bump for _ in range(workers)])
    assert errors == [], f"worker raised: {errors}"

    check = session_factory()
    try:
        final = check.get(User, user_id).token_version
    finally:
        check.close()

    assert final == workers, f"lost update: expected {workers} bumps, counter is at {final}"


def test_concurrent_refresh_of_one_parent_mints_at_most_one_child(client):
    acct = register(client, "one-child@acme.co")
    parent = acct.refresh
    codes: List[int] = []
    lock = threading.Lock()

    def rotate() -> None:
        res = client.post("/api/auth/refresh", json={"refreshToken": parent})
        with lock:
            codes.append(res.status_code)

    errors = run_concurrently([rotate for _ in range(8)])
    assert errors == [], f"worker raised: {errors}"

    assert codes.count(200) <= 1, f"token double-spent: {codes.count(200)} rotations succeeded"


# ==========================================================================
# H2 — authorization must be re-read from the DB *under* the lock
# ==========================================================================


def _hold_company_lock(monkeypatch, slow_target_id: str, hold_seconds: float = 0.8):
    """Make the role change that targets `slow_target_id` hold the company lock.

    The wrapper returns *inside* the still-open transaction, so the lock is held
    for `hold_seconds` — long enough for a second request to arrive and genuinely
    queue behind it. `lock_held` fires while the lock is held; `released_at` records
    when it was let go, so a queued caller can prove it waited.
    """
    original = memberships_repo.change_role
    lock_held = threading.Event()
    released_at: dict = {}

    def slow_change_role(db, company_id, actor_id, target_user_id, new_role, **kw):
        result = original(
            db,
            company_id=company_id,
            actor_id=actor_id,
            target_user_id=target_user_id,
            new_role=new_role,
            **kw,
        )
        if target_user_id == slow_target_id:
            lock_held.set()
            time.sleep(hold_seconds)
            # perf_counter, not monotonic: on Windows time.monotonic() ticks in
            # ~15.6 ms steps, and PostgreSQL hands a released row lock to the
            # queued waiter fast enough that "released" and "finished" land in
            # the same tick — making the strict > queue-proof fail on equality.
            released_at["t"] = time.perf_counter()
        return result

    monkeypatch.setattr(memberships_repo, "change_role", slow_change_role)
    return lock_held, released_at


def test_queued_role_change_with_stale_authority_is_rejected(client, alice, monkeypatch):
    """An admin's PATCH, *queued on the company lock* while the owner demotes them,
    must be refused — it has to re-read its own authority inside the lock.

    Note this is not merely "the role is stale in the identity map". SQLAlchemy's
    identity map holds weak references, so the preloaded membership is often
    collected before the gate re-reads it, and the stale value surfaces only
    sometimes. Authorization that is correct only when the garbage collector
    happens to have run is not correct; `reload_membership` makes the fresh read
    unconditional.
    """
    admin = register(client, "stale-admin@acme.co", company="Stale Personal")
    victim = register(client, "stale-victim@acme.co", company="Victim Personal")
    alice.post("/api/companies/members", json={"email": admin.email, "role": "admin"})
    alice.post("/api/companies/members", json={"email": victim.email, "role": "member"})

    admin_headers = {**admin.headers, "X-Company-Id": alice.company_id}
    lock_held, released_at = _hold_company_lock(monkeypatch, admin.user_id)
    out: dict = {}

    def owner_demotes_the_admin() -> None:
        out["demote"] = alice.patch(
            f"/api/companies/members/{admin.user_id}", json={"role": "member"}
        ).status_code

    def admin_mutates_while_queued() -> None:
        assert lock_held.wait(timeout=15.0), "the demotion never took the lock"
        res = client.patch(
            f"/api/companies/members/{victim.user_id}",
            headers=admin_headers,
            json={"role": "admin"},
        )
        out["mutation"] = res.status_code
        out["mutation_finished"] = time.perf_counter()

    errors = run_concurrently([owner_demotes_the_admin, admin_mutates_while_queued])
    assert errors == [], f"worker raised: {errors}"

    assert out["demote"] == 200, "the owner's demotion must succeed"
    # Prove the mutation really queued: it cannot have completed before the
    # demotion released the lock. Without this, two threads merely overlapping
    # would masquerade as a serialized test.
    assert out["mutation_finished"] > released_at["t"], (
        "the mutation did not queue behind the lock; this test proves nothing"
    )
    assert out["mutation"] == 403, "acted with authority captured before the lock"

    # And the victim was not actually promoted.
    members = alice.get("/api/companies/members").json()["members"]
    victim_role = next(m["role"] for m in members if m["userId"] == victim.user_id)
    assert victim_role == "member"


def test_queued_member_creation_with_stale_authority_is_rejected(client, alice, monkeypatch):
    """Member creation is a role grant, so it must use the same transactional gate.

    It previously authorized from `ctx.role` — captured before any lock — and took
    no lock at all, so an admin whose demotion had already committed still created
    members with the authority they no longer held.
    """
    admin = register(client, "stale-admin2@acme.co", company="Stale2 Personal")
    outsider = register(client, "outsider@acme.co", company="Outsider Personal")
    alice.post("/api/companies/members", json={"email": admin.email, "role": "admin"})

    admin_headers = {**admin.headers, "X-Company-Id": alice.company_id}
    lock_held, released_at = _hold_company_lock(monkeypatch, admin.user_id)
    out: dict = {}

    def owner_demotes_the_admin() -> None:
        out["demote"] = alice.patch(
            f"/api/companies/members/{admin.user_id}", json={"role": "member"}
        ).status_code

    def admin_invites_while_queued() -> None:
        assert lock_held.wait(timeout=15.0), "the demotion never took the lock"
        res = client.post(
            "/api/companies/members",
            headers=admin_headers,
            json={"email": outsider.email, "role": "member"},
        )
        out["invite"] = res.status_code
        out["invite_finished"] = time.perf_counter()

    errors = run_concurrently([owner_demotes_the_admin, admin_invites_while_queued])
    assert errors == [], f"worker raised: {errors}"

    assert out["demote"] == 200
    assert out["invite_finished"] > released_at["t"], (
        "the invite did not queue behind the lock; this test proves nothing"
    )
    assert out["invite"] == 403, "a demoted admin created a member with stale authority"

    members = alice.get("/api/companies/members").json()["members"]
    assert outsider.user_id not in {m["userId"] for m in members}


def test_concurrent_transfer_and_demotion_keeps_the_owner_pointer_valid(
    client, alice, session_factory, monkeypatch
):
    """`company.owner_id` must always name an active owner.

    The bug: the reassignment decision was made from `db.get(Company, ...)`, which
    returns the instance the request dependency already loaded (`ctx.company` holds
    a strong reference to it, so it is reliably stale, not occasionally stale).
    When a transfer had already moved `owner_id` to `second`, a queued demotion of
    `second` compared against the STALE pointer, concluded "not the designated
    owner", skipped the reassignment — and left the company designating a demoted
    admin as its owner.
    """
    second = register(client, "ptr-second@acme.co", company="S Personal")
    third = register(client, "ptr-third@acme.co", company="T Personal")
    alice.post("/api/companies/members", json={"email": second.email, "role": "owner"})
    alice.post("/api/companies/members", json={"email": third.email, "role": "owner"})

    third_headers = {**third.headers, "X-Company-Id": alice.company_id}
    # alice->admin is the LAST write of transfer_ownership: by then the lock is
    # held and owner_id has already been moved to `second`.
    lock_held, released_at = _hold_company_lock(monkeypatch, alice.user_id, hold_seconds=1.0)
    out: dict = {}

    def transfer_to_second() -> None:
        out["transfer"] = alice.post(
            "/api/companies/transfer-ownership", json={"userId": second.user_id}
        ).status_code

    def third_demotes_second() -> None:
        assert lock_held.wait(timeout=15.0), "the transfer never took the lock"
        out["demote"] = client.patch(
            f"/api/companies/members/{second.user_id}",
            headers=third_headers,
            json={"role": "admin"},
        ).status_code
        out["demote_finished"] = time.perf_counter()

    errors = run_concurrently([transfer_to_second, third_demotes_second])
    assert errors == [], f"worker raised: {errors}"

    assert out["transfer"] == 200
    assert out["demote_finished"] > released_at["t"], (
        "the demotion did not queue behind the transfer; this test proves nothing"
    )

    inspect = session_factory()
    try:
        company = inspect.get(Company, alice.company_id)
        designated = (
            inspect.query(CompanyMember)
            .filter(
                CompanyMember.company_id == alice.company_id,
                CompanyMember.user_id == company.owner_id,
            )
            .one_or_none()
        )
        owners = (
            inspect.query(CompanyMember)
            .filter(
                CompanyMember.company_id == alice.company_id,
                CompanyMember.role == "owner",
            )
            .count()
        )
    finally:
        inspect.close()

    assert owners >= 1, "the company lost its last owner"
    assert designated is not None, "company.owner_id names a non-member"
    assert designated.role == "owner", (
        f"company.owner_id names a {designated.role}, not an owner"
    )


def test_concurrent_demotion_of_two_owners_keeps_one(client, alice, session_factory):
    second = register(client, "co-owner@acme.co", company="Co Personal")
    alice.post("/api/companies/members", json={"email": second.email, "role": "owner"})

    def demote(target_id: str) -> None:
        res = alice.patch(f"/api/companies/members/{target_id}", json={"role": "admin"})
        assert res.status_code in (200, 409, 403), res.text

    errors = run_concurrently([
        lambda: demote(alice.user_id),
        lambda: demote(second.user_id),
    ])
    assert errors == [], f"worker raised: {errors}"

    inspect = session_factory()
    try:
        owners = (
            inspect.query(CompanyMember)
            .filter(
                CompanyMember.company_id == alice.company_id,
                CompanyMember.role == "owner",
            )
            .count()
        )
        company = inspect.get(Company, alice.company_id)
        designated = inspect.query(CompanyMember).filter(
            CompanyMember.company_id == alice.company_id,
            CompanyMember.user_id == company.owner_id,
        ).one_or_none()
    finally:
        inspect.close()

    assert owners >= 1, "concurrent demotions removed the last owner"
    assert designated is not None and designated.role == "owner", (
        "company.owner_id does not name an active owner membership"
    )


def test_concurrent_removal_of_two_owners_keeps_one(client, alice, session_factory):
    second = register(client, "co-owner2@acme.co", company="Co2 Personal")
    alice.post("/api/companies/members", json={"email": second.email, "role": "owner"})

    def remove(target_id: str) -> None:
        res = alice.delete(f"/api/companies/members/{target_id}")
        assert res.status_code in (200, 409, 403, 404), res.text

    errors = run_concurrently([
        lambda: remove(alice.user_id),
        lambda: remove(second.user_id),
    ])
    assert errors == [], f"worker raised: {errors}"

    inspect = session_factory()
    try:
        owners = (
            inspect.query(CompanyMember)
            .filter(
                CompanyMember.company_id == alice.company_id,
                CompanyMember.role == "owner",
            )
            .count()
        )
        company = inspect.get(Company, alice.company_id)
        designated = inspect.query(CompanyMember).filter(
            CompanyMember.company_id == alice.company_id,
            CompanyMember.user_id == company.owner_id,
        ).one_or_none()
    finally:
        inspect.close()

    assert owners >= 1, "concurrent removals removed the last owner"
    assert designated is not None and designated.role == "owner"


# ==========================================================================
# Identity-map staleness — the root cause of H2, isolated from any race
# ==========================================================================


def test_reload_membership_bypasses_the_identity_map(client, alice, session_factory):
    """A plain `select()` re-read returns the CACHED object, not the current row.

    This is the whole of H2 in one test, with the concurrency removed: hold a
    strong reference to a preloaded membership (as a request's CompanyContext does
    for its company), commit a change from another session, and re-read. The ORM
    hands back the stale instance. Only `populate_existing` actually re-reads.
    """
    admin = register(client, "map-admin@acme.co", company="Map Personal")
    alice.post("/api/companies/members", json={"email": admin.email, "role": "admin"})

    session = session_factory()
    try:
        # Preload, exactly as authenticating the request does. The strong reference
        # is what keeps it in the weak identity map.
        preloaded = memberships_repo.get_membership(session, alice.company_id, admin.user_id)
        preloaded_company = session.get(Company, alice.company_id)
        assert preloaded.role == "admin"

        other = session_factory()
        try:
            other.execute(
                CompanyMember.__table__.update()
                .where(
                    CompanyMember.company_id == alice.company_id,
                    CompanyMember.user_id == admin.user_id,
                )
                .values(role="member")
            )
            other.execute(
                Company.__table__.update()
                .where(Company.id == alice.company_id)
                .values(owner_id=admin.user_id)
            )
            other.commit()
        finally:
            other.close()

        # The unqualified re-read is stale — this is what the authorization gate
        # used to trust.
        assert (
            memberships_repo.get_membership(session, alice.company_id, admin.user_id).role
            == "admin"
        ), "the identity map is expected to serve the stale role here"
        assert session.get(Company, alice.company_id).owner_id == preloaded_company.owner_id

        # The gate's reader sees the truth.
        assert (
            memberships_repo.reload_membership(session, alice.company_id, admin.user_id).role
            == "member"
        ), "reload_membership returned a stale role"
        assert (
            memberships_repo.reload_company(session, alice.company_id).owner_id
            == admin.user_id
        ), "reload_company returned a stale owner_id"
    finally:
        session.close()


# ==========================================================================
# PostgreSQL row-lock semantics (skipped unless a real server is configured)
# ==========================================================================


@requires_postgres
def test_the_suite_is_running_against_postgres(engine):
    """Guards the profile itself: if this runs at all, the tests above just
    exercised real `SELECT ... FOR UPDATE` row locks rather than SQLite's
    whole-database write lock."""
    assert engine.dialect.name == "postgresql"


@requires_postgres
def test_user_row_lock_serializes_session_issuance_on_postgres(client, session_factory):
    """The SQLite path fakes a row lock with a no-op UPDATE. On PostgreSQL the lock
    is a genuine `FOR UPDATE`, and this asserts the same invariant holds there."""
    acct = register(client, "pg-lock@acme.co")
    parent = acct.refresh

    def do_refresh() -> None:
        client.post("/api/auth/refresh", json={"refreshToken": parent})

    def do_logout_all() -> None:
        acct.post("/api/auth/logout-all")

    errors = run_concurrently([do_refresh, do_logout_all])
    assert errors == [], f"worker raised: {errors}"
    assert _live_refresh_tokens(session_factory, acct.email) == 0


@requires_postgres
def test_concurrent_enqueue_leaves_exactly_one_live_job_on_postgres(session_factory):
    """The enqueue race the partial unique index exists for, on the engine
    production actually uses.

    Two sessions both pass the 'no live job' pre-select, both INSERT. On
    PostgreSQL the second INSERT blocks on the unique index entry until the
    first commits, then raises; the loser's savepoint rollback must discard
    only its insert, and the loser must re-select and adopt the winner's job.
    SQLite cannot demonstrate this faithfully (a writer holding a stale
    snapshot fails with SQLITE_BUSY, not a unique violation), so the
    deterministic simulation lives in test_ingestion_schema_and_seams.py and
    the genuine race is proven here.
    """
    setup = session_factory()
    try:
        company = Company(name="Enqueue Race Co", slug="enqueue-race-co")
        setup.add(company)
        setup.flush()
        doc = Document(company_id=company.id, title="Racy", slug="racy")
        setup.add(doc)
        setup.flush()
        version = DocumentVersion(document_id=doc.id, company_id=company.id, version_no=1)
        setup.add(version)
        setup.commit()
        company_id, document_id, version_id = company.id, doc.id, version.id
    finally:
        setup.close()

    resolved_ids: List[str] = []
    resolved_lock = threading.Lock()

    def enqueue_worker() -> None:
        session = session_factory()
        try:
            job = DatabaseJobQueue().enqueue(
                session, company_id=company_id, document_id=document_id, version_id=version_id
            )
            session.commit()
            with resolved_lock:
                resolved_ids.append(job.id)
        finally:
            session.close()

    errors = run_concurrently([enqueue_worker, enqueue_worker])
    assert errors == [], f"worker raised: {errors}"

    # Both callers resolved, and to the SAME surviving job.
    assert len(resolved_ids) == 2
    assert len(set(resolved_ids)) == 1

    check = session_factory()
    try:
        live = (
            check.execute(
                select(IngestionJob).where(
                    IngestionJob.version_id == version_id,
                    IngestionJob.state.in_((JOB_STATE_QUEUED, JOB_STATE_RUNNING)),
                )
            )
            .scalars()
            .all()
        )
        assert [job.id for job in live] == [resolved_ids[0]]
    finally:
        check.close()


# ==========================================================================
# Flag-on JSON create quota boundaries under real row locks (review fix).
# The JSON path shares the multipart path's company-row lock, so two creates
# racing for the last quota slot must serialize: exactly one wins, the loser
# gets the typed quota code, and nothing the loser touched persists.
# ==========================================================================


def _race_two_json_creates(alice) -> List[tuple]:
    """Fire two concurrent flag-on JSON creates as the same tenant; return
    [(status_code, body), ...] in completion order."""
    results: List[tuple] = []
    lock = threading.Lock()

    def create(n: int) -> None:
        res = alice.post(
            "/api/documents",
            json={
                "title": f"Racer {n}",
                "type": "MD",
                "contentText": f"## R{n}\n" + "x" * 34,  # 40 UTF-8 bytes exactly
            },
        )
        with lock:
            results.append((res.status_code, res.json()))

    errors = run_concurrently([lambda: create(1), lambda: create(2)])
    assert errors == [], f"worker raised: {errors}"
    assert len(results) == 2
    return results


def _tenant_ingestion_rows(session_factory, company_id: str) -> dict:
    check = session_factory()
    try:
        return {
            "documents": len(
                check.execute(
                    select(Document).where(Document.company_id == company_id)
                ).scalars().all()
            ),
            "versions": len(
                check.execute(
                    select(DocumentVersion).where(DocumentVersion.company_id == company_id)
                ).scalars().all()
            ),
            "blobs": len(
                check.execute(
                    select(DocumentBlob).where(DocumentBlob.company_id == company_id)
                ).scalars().all()
            ),
            "jobs": len(
                check.execute(
                    select(IngestionJob).where(IngestionJob.company_id == company_id)
                ).scalars().all()
            ),
            "stored_bytes": sum(
                blob.byte_size
                for blob in check.execute(
                    select(DocumentBlob).where(DocumentBlob.company_id == company_id)
                ).scalars().all()
            ),
        }
    finally:
        check.close()


@requires_postgres
def test_concurrent_json_creates_respect_the_count_quota_on_postgres(
    client, alice, session_factory, monkeypatch
):
    """One document-count slot remains; two flag-on JSON creates race for it."""
    monkeypatch.setattr(get_settings(), "evidentia_tenant_corpus_enabled", True)
    monkeypatch.setattr(get_settings(), "evidentia_tenant_max_documents", 1)

    results = _race_two_json_creates(alice)

    codes = sorted(code for code, _ in results)
    assert codes == [201, 403], f"expected exactly one winner, got {codes}"
    loser = next(body for code, body in results if code == 403)
    assert loser["code"] == "document_quota_exceeded"

    rows = _tenant_ingestion_rows(session_factory, alice.company_id)
    assert rows["documents"] == 1, "the persisted count exceeded the quota"
    assert rows["versions"] == 1 and rows["blobs"] == 1 and rows["jobs"] == 1, (
        "the losing create left rows behind"
    )


@requires_postgres
def test_concurrent_json_creates_respect_the_byte_quota_on_postgres(
    client, alice, session_factory, monkeypatch
):
    """Storage allows exactly one 40-byte payload; two flag-on JSON creates race."""
    monkeypatch.setattr(get_settings(), "evidentia_tenant_corpus_enabled", True)
    monkeypatch.setattr(get_settings(), "evidentia_tenant_max_documents", 100)
    monkeypatch.setattr(get_settings(), "evidentia_tenant_max_total_bytes", 60)

    results = _race_two_json_creates(alice)  # each payload is 40 bytes

    codes = sorted(code for code, _ in results)
    assert codes == [201, 403], f"expected exactly one winner, got {codes}"
    loser = next(body for code, body in results if code == 403)
    assert loser["code"] == "storage_quota_exceeded"

    rows = _tenant_ingestion_rows(session_factory, alice.company_id)
    assert rows["stored_bytes"] <= 60, "persisted bytes exceeded the storage quota"
    assert rows["documents"] == 1 and rows["versions"] == 1 and rows["blobs"] == 1, (
        "the losing create left rows behind"
    )
