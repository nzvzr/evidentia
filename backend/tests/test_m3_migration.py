"""M3 — data-bearing Alembic migration regressions.

The M3 downgrade is PREFLIGHT-FIRST: every refusal condition is evaluated
before any row insertion and before any schema mutation, so an intentional
safe refusal leaves the COMPLETE M3 schema and all data untouched even where
DDL is not transactional. These tests prove:

* a successor whose source version has ZERO document_blobs rows refuses the
  downgrade (removing source_version_id would leave the successor unable to
  resolve its bytes) — as do multiple/ambiguous source blobs, incomplete or
  hash-inconsistent source blob metadata, and NULL (not DB-backed) source
  blob data;
* successors that ALREADY own a document_blobs row are preflighted too: an
  exact safe equivalent of the source binding is accepted idempotently, while
  divergent content, multiple rows, or incomplete metadata refuse without
  overwriting or deleting anything;
* the materialization plan is built globally before any insert: a refusal for
  a later successor means no blob is inserted for an earlier valid one;
* a safely materializable successor round-trips M2 -> M3 -> M2 -> M3 with
  every successor's source bytes preserved exactly;
* downgrade() itself — not just its helpers — is structured as strictly
  ordered phases (_preflight_downgrade -> _materialize_successor_blobs ->
  _apply_m2_schema_downgrade): calling the real downgrade() under an Alembic
  migration context while recording every executed statement proves that no
  mutating SQL runs before the preflight completes, and that a refusal
  executes no mutating SQL at all.

Runs on file-backed SQLite always. When ``EVIDENTIA_TEST_DATABASE_URL`` names a
PostgreSQL server (the CI/dev PostgreSQL 16 container), the same cases also run
against a throwaway database created on that server.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import os
import uuid
from datetime import datetime
from pathlib import Path
from unittest import mock

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.core.config import get_settings

# Migration chain endpoints: committed M2 head and corrected M3.
M2_HEAD = "f7c3a1b9e2d4"
M3 = "a9d2e4c7b1f3"

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ALEMBIC_INI = _BACKEND_DIR / "alembic.ini"
_MIGRATIONS_DIR = _BACKEND_DIR / "migrations"
_M3_MIGRATION_FILE = _MIGRATIONS_DIR / "versions" / "a9d2e4c7b1f3_m3_anchors_classification.py"

_PG_URL = os.getenv("EVIDENTIA_TEST_DATABASE_URL", "").strip()
_BACKENDS = ["sqlite"] + (["postgres"] if _PG_URL.startswith("postgresql") else [])


def _load_migration_module():
    """Import the M3 migration module directly (a fresh module object per call,
    so per-test instrumentation cannot leak) to drive its downgrade() and
    preflight helpers against a raw connection."""
    spec = importlib.util.spec_from_file_location("_m3_mig", _M3_MIGRATION_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# backend harness
# --------------------------------------------------------------------------- #


class _Mig:
    def __init__(self, url: str, cfg: Config):
        self.url = url
        self.cfg = cfg
        self.is_sqlite = url.startswith("sqlite")

    def upgrade(self, rev: str) -> None:
        command.upgrade(self.cfg, rev)

    def downgrade(self, rev: str) -> None:
        command.downgrade(self.cfg, rev)

    def engine(self):
        return create_engine(self.url, future=True)


def _create_pg_temp_db(base_url: str):
    name = "evidentia_mig_" + uuid.uuid4().hex[:12]
    eng = create_engine(base_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with eng.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        eng.dispose()
    # NB: str(URL) masks the password as '***' in SQLAlchemy 2.0 — render it out
    # explicitly or the migration would connect with a literal '***' password.
    temp = sa.engine.make_url(base_url).set(database=name)
    return temp.render_as_string(hide_password=False), name


def _drop_pg_temp_db(base_url: str, name: str) -> None:
    eng = create_engine(base_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with eng.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :n AND pid <> pg_backend_pid()"
                ),
                {"n": name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    finally:
        eng.dispose()


@pytest.fixture(params=_BACKENDS)
def mig(request, tmp_path, monkeypatch):
    """A migration harness bound to a throwaway database (SQLite file or a
    freshly created PostgreSQL database). Alembic's env.py reads the database
    URL from settings, so we point settings at the throwaway DB for the test."""
    pg_name = None
    if request.param == "postgres":
        url, pg_name = _create_pg_temp_db(_PG_URL)
    else:
        url = f"sqlite:///{tmp_path / 'mig.db'}"

    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    try:
        yield _Mig(url, cfg)
    finally:
        get_settings.cache_clear()
        if pg_name is not None:
            _drop_pg_temp_db(_PG_URL, pg_name)


# --------------------------------------------------------------------------- #
# seeding + introspection
# --------------------------------------------------------------------------- #

_NOW = datetime(2026, 7, 18, 12, 0, 0)


def _seed_company_document(conn, *, citation_prefix="PLC"):
    cid, did = str(uuid.uuid4()), str(uuid.uuid4())
    conn.execute(
        text(
            "INSERT INTO companies (id,name,slug,created_at,updated_at) "
            "VALUES (:i,:n,:s,:c,:u)"
        ),
        {"i": cid, "n": "Acme", "s": f"acme-{cid[:8]}", "c": _NOW, "u": _NOW},
    )
    conn.execute(
        text(
            "INSERT INTO documents (id,company_id,title,slug,citation_prefix,"
            "source_type,status,created_at,updated_at) "
            "VALUES (:i,:c,:t,:s,:p,'api','ready',:ca,:ua)"
        ),
        {"i": did, "c": cid, "t": "Policy", "s": f"policy-{did[:8]}",
         "p": citation_prefix, "ca": _NOW, "ua": _NOW},
    )
    return cid, did


def _seed_blob(conn, *, vid, cid, data, byte_size=None, storage_key=None):
    """One document_blobs row. byte_size/storage_key are overridable so tests
    can seed deliberately corrupt metadata."""
    blob = str(uuid.uuid4())
    if byte_size is None:
        byte_size = len(data) if data is not None else 0
    if storage_key is None:
        storage_key = f"seed:{blob}"
    conn.execute(
        text(
            "INSERT INTO document_blobs (id,version_id,company_id,storage_key,"
            "byte_size,data,created_at) VALUES (:i,:v,:c,:k,:sz,:data,:ca)"
        ),
        {"i": blob, "v": vid, "c": cid, "k": storage_key,
         "sz": byte_size, "data": data, "ca": _NOW},
    )
    return blob


def _seed_source_version(
    conn, *, cid, did, data,
    with_blob=True, byte_size=None, storage_key=None, content_sha256=None,
):
    """A transitional source version, by default with a well-formed blob."""
    src = str(uuid.uuid4())
    conn.execute(
        text(
            "INSERT INTO document_versions (id,document_id,company_id,version_no,"
            "status,anchor_algo_version,content_sha256,created_at) "
            "VALUES (:i,:d,:c,1,'ready','pre-m3-transitional',:sha,:ca)"
        ),
        {"i": src, "d": did, "c": cid, "sha": content_sha256, "ca": _NOW},
    )
    if with_blob:
        _seed_blob(conn, vid=src, cid=cid, data=data,
                   byte_size=byte_size, storage_key=storage_key)
    return src


def _seed_successor(conn, *, cid, did, src, vid=None, content_sha256=None):
    succ = vid if vid is not None else str(uuid.uuid4())
    conn.execute(
        text(
            "INSERT INTO document_versions (id,document_id,company_id,version_no,"
            "status,anchor_algo_version,content_sha256,source_version_id,"
            "finalization_engine,created_at) "
            "VALUES (:i,:d,:c,2,'ready','heading-path-v1',:sha,:src,:eng,:ca)"
        ),
        {"i": succ, "d": did, "c": cid, "sha": content_sha256, "src": src,
         "eng": "cft1:" + "0" * 64, "ca": _NOW},
    )
    return succ


def _drop_blob_version_unique(eng) -> None:
    """The M2 schema DB-enforces the 1-1 version<->blob binding
    (uq_document_blobs_version). To exercise the preflight's defense against
    an already-corrupted multi-blob state, remove the constraint on the
    throwaway database first (batch mode recreates the table on SQLite)."""
    with eng.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx) as ops:
            with ops.batch_alter_table("document_blobs") as batch:
                batch.drop_constraint("uq_document_blobs_version", type_="unique")
        conn.commit()


def _m3_schema(engine) -> dict:
    """A dialect-robust structural fingerprint of the complete M3 schema plus
    the Alembic revision. Two reflections are equal iff the schema is unchanged."""
    with engine.connect() as conn:
        insp = inspect(conn)
        dv_cols = {c["name"] for c in insp.get_columns("document_versions")}
        ds_cols = {c["name"] for c in insp.get_columns("document_sections")}
        ij_cols = {c["name"] for c in insp.get_columns("ingestion_jobs")}
        doc_cols = {c["name"]: str(c["type"]) for c in insp.get_columns("documents")}
        dv_uniques = sorted(
            tuple(u["column_names"]) for u in insp.get_unique_constraints("document_versions")
        )
        dv_fks = sorted(
            tuple(sorted(f["constrained_columns"]))
            for f in insp.get_foreign_keys("document_versions")
        )
        dv_indexes = sorted(
            (tuple(i["column_names"]), bool(i["unique"]))
            for i in insp.get_indexes("document_versions")
        )
        revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    return {
        "citation_prefix_type": doc_cols["citation_prefix"],
        "dv_cols": tuple(sorted(dv_cols)),
        "ds_cols": tuple(sorted(ds_cols)),
        "ij_cols": tuple(sorted(ij_cols)),
        "dv_uniques": tuple(dv_uniques),
        "dv_fks": tuple(dv_fks),
        "dv_indexes": tuple(dv_indexes),
        "revision": revision,
    }


def _blob_count(engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM document_blobs")).scalar()


def _assert_refused_state(
    eng, before, *, blobs_before, successor=None, source=None
):
    """Everything a safe refusal guarantees: the complete M3 schema, the
    Alembic revision, the M3 columns/widths, the successor's lineage and the
    blob table are all exactly as they were."""
    after = _m3_schema(eng)
    assert after == before, "the complete M3 schema must be unchanged after a refusal"
    assert after["revision"] == M3
    assert "12" in after["citation_prefix_type"]
    assert "source_version_id" in after["dv_cols"]
    assert "operation" in after["ij_cols"]
    assert {"anchor_provenance", "matched_rules", "classification_signature"} <= set(
        after["ds_cols"]
    )
    assert _blob_count(eng) == blobs_before, "no partial materialization row"
    if successor is not None:
        with eng.connect() as conn:
            row = conn.execute(
                text("SELECT source_version_id FROM document_versions WHERE id = :i"),
                {"i": successor},
            ).fetchone()
        assert row is not None and row.source_version_id == source, (
            "successor lineage (source_version_id) must remain intact after a refusal"
        )


# --------------------------------------------------------------------------- #
# BLOCKER 1 — a byte-unresolvable successor refuses the downgrade
# --------------------------------------------------------------------------- #


def test_downgrade_refuses_when_source_has_zero_blob_rows(mig):
    """A successor whose source version has NO document_blobs row would become
    byte-unresolvable once source_version_id is dropped: the downgrade must
    refuse during preflight, never skip the successor."""
    mig.upgrade(M2_HEAD)
    mig.upgrade(M3)
    eng = mig.engine()
    try:
        with eng.begin() as conn:
            cid, did = _seed_company_document(conn)
            src = _seed_source_version(conn, cid=cid, did=did, data=None, with_blob=False)
            succ = _seed_successor(conn, cid=cid, did=did, src=src)

        before = _m3_schema(eng)
        assert before["revision"] == M3
        blobs_before = _blob_count(eng)

        with pytest.raises(RuntimeError, match="downgrade refused"):
            mig.downgrade(M2_HEAD)

        _assert_refused_state(
            eng, before, blobs_before=blobs_before, successor=succ, source=src
        )
    finally:
        eng.dispose()


def test_downgrade_refuses_null_source_blob_and_leaves_m3_schema_intact(mig):
    mig.upgrade(M2_HEAD)
    mig.upgrade(M3)
    eng = mig.engine()
    try:
        with eng.begin() as conn:
            cid, did = _seed_company_document(conn)
            src = _seed_source_version(conn, cid=cid, did=did, data=None)  # NULL blob
            succ = _seed_successor(conn, cid=cid, did=did, src=src)

        before = _m3_schema(eng)
        blobs_before = _blob_count(eng)

        with pytest.raises(RuntimeError, match="downgrade refused"):
            mig.downgrade(M2_HEAD)

        _assert_refused_state(
            eng, before, blobs_before=blobs_before, successor=succ, source=src
        )
    finally:
        eng.dispose()


def test_downgrade_refuses_multiple_ambiguous_source_blobs(mig):
    """Two blob rows for one source version (a corrupted state the M2 unique
    constraint normally forbids) are ambiguous: refuse, never pick one."""
    mig.upgrade(M2_HEAD)
    mig.upgrade(M3)
    eng = mig.engine()
    try:
        _drop_blob_version_unique(eng)
        with eng.begin() as conn:
            cid, did = _seed_company_document(conn)
            src = _seed_source_version(conn, cid=cid, did=did, data=b"variant-one")
            _seed_blob(conn, vid=src, cid=cid, data=b"variant-two")
            succ = _seed_successor(conn, cid=cid, did=did, src=src)

        before = _m3_schema(eng)
        blobs_before = _blob_count(eng)

        with pytest.raises(RuntimeError, match="downgrade refused"):
            mig.downgrade(M2_HEAD)

        _assert_refused_state(
            eng, before, blobs_before=blobs_before, successor=succ, source=src
        )
    finally:
        eng.dispose()


@pytest.mark.parametrize(
    "corruption", ["size_mismatch", "empty_storage_key", "source_hash_mismatch",
                   "successor_hash_mismatch"]
)
def test_downgrade_refuses_invalid_source_blob_metadata(mig, corruption):
    """Source blob metadata that cannot be proven valid (wrong size, missing
    storage key, content hash contradicting the bytes) refuses the downgrade."""
    data = b"the actual source bytes"
    wrong_sha = hashlib.sha256(b"different bytes entirely").hexdigest()
    mig.upgrade(M2_HEAD)
    mig.upgrade(M3)
    eng = mig.engine()
    try:
        with eng.begin() as conn:
            cid, did = _seed_company_document(conn)
            if corruption == "size_mismatch":
                src = _seed_source_version(
                    conn, cid=cid, did=did, data=data, byte_size=len(data) + 7
                )
                succ = _seed_successor(conn, cid=cid, did=did, src=src)
            elif corruption == "empty_storage_key":
                src = _seed_source_version(
                    conn, cid=cid, did=did, data=data, storage_key=""
                )
                succ = _seed_successor(conn, cid=cid, did=did, src=src)
            elif corruption == "source_hash_mismatch":
                src = _seed_source_version(
                    conn, cid=cid, did=did, data=data, content_sha256=wrong_sha
                )
                succ = _seed_successor(conn, cid=cid, did=did, src=src)
            else:  # successor_hash_mismatch
                src = _seed_source_version(conn, cid=cid, did=did, data=data)
                succ = _seed_successor(
                    conn, cid=cid, did=did, src=src, content_sha256=wrong_sha
                )

        before = _m3_schema(eng)
        blobs_before = _blob_count(eng)

        with pytest.raises(RuntimeError, match="downgrade refused"):
            mig.downgrade(M2_HEAD)

        _assert_refused_state(
            eng, before, blobs_before=blobs_before, successor=succ, source=src
        )
    finally:
        eng.dispose()


def test_downgrade_refuses_overlong_citation_prefix_and_leaves_m3_schema_intact(mig):
    mig.upgrade(M2_HEAD)
    mig.upgrade(M3)
    eng = mig.engine()
    try:
        with eng.begin() as conn:
            _seed_company_document(conn, citation_prefix="ABCDEFGHIJKL")  # 12 > 8

        before = _m3_schema(eng)
        blobs_before = _blob_count(eng)
        with pytest.raises(RuntimeError, match="downgrade refused"):
            mig.downgrade(M2_HEAD)
        _assert_refused_state(eng, before, blobs_before=blobs_before)
    finally:
        eng.dispose()


# --------------------------------------------------------------------------- #
# BLOCKER 2 — successors that already own a blob are validated, not skipped
# --------------------------------------------------------------------------- #


def test_downgrade_refuses_divergent_preexisting_successor_blob(mig):
    """Source resolves to bytes A but the successor already owns bytes B: the
    downgrade must refuse — never silently retain B, never overwrite it."""
    source_bytes = b"bytes A - the source content"
    divergent_bytes = b"bytes B - something else entirely"
    mig.upgrade(M2_HEAD)
    mig.upgrade(M3)
    eng = mig.engine()
    try:
        with eng.begin() as conn:
            cid, did = _seed_company_document(conn)
            src = _seed_source_version(conn, cid=cid, did=did, data=source_bytes)
            succ = _seed_successor(conn, cid=cid, did=did, src=src)
            divergent_blob = _seed_blob(conn, vid=succ, cid=cid, data=divergent_bytes)

        before = _m3_schema(eng)
        blobs_before = _blob_count(eng)

        with pytest.raises(RuntimeError, match="downgrade refused"):
            mig.downgrade(M2_HEAD)

        _assert_refused_state(
            eng, before, blobs_before=blobs_before, successor=succ, source=src
        )
        # The conflicting blob was neither overwritten nor deleted.
        with eng.connect() as conn:
            row = conn.execute(
                text("SELECT id, data FROM document_blobs WHERE version_id = :v"),
                {"v": succ},
            ).fetchone()
        assert row.id == divergent_blob
        assert bytes(row.data) == divergent_bytes
    finally:
        eng.dispose()


def test_downgrade_accepts_equivalent_preexisting_successor_blob_idempotently(mig):
    """A successor blob that is an exact safe equivalent of the source binding
    (same bytes, same size, same tenant) counts as already materialized: the
    downgrade succeeds and leaves that row untouched — no duplicate insert."""
    source_bytes = b"identical bytes on both versions"
    mig.upgrade(M2_HEAD)
    mig.upgrade(M3)
    eng = mig.engine()
    try:
        with eng.begin() as conn:
            cid, did = _seed_company_document(conn)
            src = _seed_source_version(conn, cid=cid, did=did, data=source_bytes)
            succ = _seed_successor(conn, cid=cid, did=did, src=src)
            existing_blob = _seed_blob(conn, vid=succ, cid=cid, data=source_bytes)

        assert _blob_count(eng) == 2
        mig.downgrade(M2_HEAD)

        with eng.connect() as conn:
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            rows = conn.execute(
                text("SELECT id, byte_size, data FROM document_blobs WHERE version_id = :v"),
                {"v": succ},
            ).fetchall()
            src_data = conn.execute(
                text("SELECT data FROM document_blobs WHERE version_id = :v"), {"v": src}
            ).scalar()
        assert revision == M2_HEAD
        assert len(rows) == 1, "no duplicate blob may be inserted for the successor"
        assert rows[0].id == existing_blob, "the pre-existing equivalent row is kept"
        assert bytes(rows[0].data) == source_bytes
        assert rows[0].byte_size == len(source_bytes)
        assert bytes(src_data) == source_bytes
        assert _blob_count(eng) == 2
    finally:
        eng.dispose()


def test_downgrade_refuses_multiple_preexisting_successor_blobs(mig):
    """Two blob rows already bound to one successor (corrupted state) are
    ambiguous: refuse during preflight."""
    source_bytes = b"the source bytes"
    mig.upgrade(M2_HEAD)
    mig.upgrade(M3)
    eng = mig.engine()
    try:
        _drop_blob_version_unique(eng)
        with eng.begin() as conn:
            cid, did = _seed_company_document(conn)
            src = _seed_source_version(conn, cid=cid, did=did, data=source_bytes)
            succ = _seed_successor(conn, cid=cid, did=did, src=src)
            _seed_blob(conn, vid=succ, cid=cid, data=source_bytes)
            _seed_blob(conn, vid=succ, cid=cid, data=source_bytes)

        before = _m3_schema(eng)
        blobs_before = _blob_count(eng)

        with pytest.raises(RuntimeError, match="downgrade refused"):
            mig.downgrade(M2_HEAD)

        _assert_refused_state(
            eng, before, blobs_before=blobs_before, successor=succ, source=src
        )
    finally:
        eng.dispose()


def test_downgrade_refuses_incomplete_preexisting_successor_blob(mig):
    """A successor blob whose data is NULL cannot prove equivalence to the
    source binding: refuse rather than trust it."""
    mig.upgrade(M2_HEAD)
    mig.upgrade(M3)
    eng = mig.engine()
    try:
        with eng.begin() as conn:
            cid, did = _seed_company_document(conn)
            src = _seed_source_version(conn, cid=cid, did=did, data=b"real bytes")
            succ = _seed_successor(conn, cid=cid, did=did, src=src)
            _seed_blob(conn, vid=succ, cid=cid, data=None)

        before = _m3_schema(eng)
        blobs_before = _blob_count(eng)

        with pytest.raises(RuntimeError, match="downgrade refused"):
            mig.downgrade(M2_HEAD)

        _assert_refused_state(
            eng, before, blobs_before=blobs_before, successor=succ, source=src
        )
    finally:
        eng.dispose()


def test_refusal_plans_globally_and_inserts_nothing_for_valid_successors(mig):
    """One early, perfectly valid successor plus one later conflicting one:
    the whole downgrade refuses and the early successor gains NO blob — the
    plan is completed globally before any materialization row is written."""
    early_bytes = b"early successor source bytes"
    mig.upgrade(M2_HEAD)
    mig.upgrade(M3)
    eng = mig.engine()
    try:
        with eng.begin() as conn:
            cid1, did1 = _seed_company_document(conn)
            src1 = _seed_source_version(conn, cid=cid1, did=did1, data=early_bytes)
            # Preflight iterates successors ORDER BY id: this one is planned first.
            early = _seed_successor(
                conn, cid=cid1, did=did1, src=src1,
                vid="00000000-0000-4000-8000-0000000000aa",
            )
            cid2, did2 = _seed_company_document(conn)
            src2 = _seed_source_version(conn, cid=cid2, did=did2, data=b"source A")
            later = _seed_successor(
                conn, cid=cid2, did=did2, src=src2,
                vid="ffffffff-ffff-4fff-bfff-ffffffffffff",
            )
            _seed_blob(conn, vid=later, cid=cid2, data=b"conflicting B")

        before = _m3_schema(eng)
        blobs_before = _blob_count(eng)

        with pytest.raises(RuntimeError, match="downgrade refused"):
            mig.downgrade(M2_HEAD)

        _assert_refused_state(
            eng, before, blobs_before=blobs_before, successor=early, source=src1
        )
        with eng.connect() as conn:
            early_blob = conn.execute(
                text("SELECT 1 FROM document_blobs WHERE version_id = :v"),
                {"v": early},
            ).fetchone()
        assert early_blob is None, (
            "no blob may be inserted for the early valid successor when a later "
            "successor refuses — planning must complete before materialization"
        )
    finally:
        eng.dispose()


# --------------------------------------------------------------------------- #
# successful downgrade + full round trip
# --------------------------------------------------------------------------- #


def test_successful_downgrade_materializes_successor_blob_and_round_trips(mig):
    source_bytes = b"# Policy\n\nThe retained source document bytes.\n"
    other_bytes = b"# Handbook\n\nA second tenant's source bytes.\n"
    mig.upgrade(M2_HEAD)
    mig.upgrade(M3)
    eng = mig.engine()
    try:
        with eng.begin() as conn:
            cid, did = _seed_company_document(conn)
            src = _seed_source_version(conn, cid=cid, did=did, data=source_bytes)
            succ = _seed_successor(conn, cid=cid, did=did, src=src)
            cid2, did2 = _seed_company_document(conn)
            src2 = _seed_source_version(conn, cid=cid2, did=did2, data=other_bytes)
            succ2 = _seed_successor(conn, cid=cid2, did=did2, src=src2)

        mig.downgrade(M2_HEAD)

        # M3 columns are gone and citation_prefix fits the M2 width.
        with eng.connect() as conn:
            insp = inspect(conn)
            dv_cols = {c["name"] for c in insp.get_columns("document_versions")}
            ds_cols = {c["name"] for c in insp.get_columns("document_sections")}
            ij_cols = {c["name"] for c in insp.get_columns("ingestion_jobs")}
            prefix_type = next(
                str(c["type"]) for c in insp.get_columns("documents")
                if c["name"] == "citation_prefix"
            )
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert "source_version_id" not in dv_cols
        assert "finalization_engine" not in dv_cols
        assert "engine_versions" not in dv_cols
        assert not ({"anchor_provenance", "matched_rules"} & ds_cols)
        assert "operation" not in ij_cols
        assert "8" in prefix_type and "12" not in prefix_type
        assert revision == M2_HEAD

        # EVERY successor now owns its own content-addressed blob (same bytes,
        # no physical duplication of identity), and the source bytes remain
        # resolvable. No dangling blob references.
        with eng.connect() as conn:
            for version_id, expected in ((succ, source_bytes), (succ2, other_bytes)):
                succ_blob = conn.execute(
                    text("SELECT byte_size, data FROM document_blobs WHERE version_id = :v"),
                    {"v": version_id},
                ).fetchone()
                assert succ_blob is not None, "successor must have its own materialized blob"
                assert bytes(succ_blob.data) == expected
                assert succ_blob.byte_size == len(expected)

            for version_id, expected in ((src, source_bytes), (src2, other_bytes)):
                src_blob = conn.execute(
                    text("SELECT data FROM document_blobs WHERE version_id = :v"),
                    {"v": version_id},
                ).fetchone()
                assert bytes(src_blob.data) == expected  # source still resolvable

            dangling = conn.execute(
                text(
                    "SELECT COUNT(*) FROM document_blobs b "
                    "WHERE NOT EXISTS (SELECT 1 FROM document_versions v WHERE v.id = b.version_id)"
                )
            ).scalar()
            assert dangling == 0

        # Re-upgrade to corrected M3 succeeds; all persisted bytes/rows survive.
        mig.upgrade(M3)
        with eng.connect() as conn:
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            versions = conn.execute(
                text("SELECT COUNT(*) FROM document_versions WHERE document_id = :d"),
                {"d": did},
            ).scalar()
            src_data = conn.execute(
                text("SELECT data FROM document_blobs WHERE version_id = :v"), {"v": src}
            ).scalar()
        assert revision == M3
        assert versions == 2
        assert bytes(src_data) == source_bytes
    finally:
        eng.dispose()


# --------------------------------------------------------------------------- #
# BLOCKER 3 — downgrade() itself is preflight-first (SQL-level proof)
# --------------------------------------------------------------------------- #

_MUTATING_PREFIXES = (
    "insert", "update", "delete", "alter", "create", "drop", "replace", "truncate"
)


def _is_mutating_sql(stmt: str) -> bool:
    return stmt.lstrip().lower().startswith(_MUTATING_PREFIXES)


def _record_sql(eng, timeline) -> None:
    """Append every statement the engine executes to the shared timeline."""

    def _listener(conn, cursor, statement, parameters, context, executemany):
        timeline.append(("sql", statement))

    sa.event.listen(eng, "before_cursor_execute", _listener)


def _wrap_phase(m3, name, timeline) -> None:
    """Record start/end of a downgrade phase in the shared timeline while
    delegating to the real implementation."""
    real = getattr(m3, name)

    def wrapper(*args, **kwargs):
        timeline.append(("phase", f"{name}:start"))
        result = real(*args, **kwargs)
        timeline.append(("phase", f"{name}:end"))
        return result

    setattr(m3, name, wrapper)


def test_downgrade_call_executes_no_mutating_sql_before_refusing(mig):
    """Calling the REAL downgrade() (not its helpers) with a refusal condition
    seeded: every statement executed on the connection is recorded, and not a
    single mutating statement (INSERT/ALTER/CREATE/DROP/...) may run. This
    fails if any future edit moves DDL or blob insertion ahead of preflight,
    independent of whether the platform would roll DDL back."""
    m3 = _load_migration_module()
    mig.upgrade(M2_HEAD)
    mig.upgrade(M3)
    eng = mig.engine()
    try:
        with eng.begin() as conn:
            cid, did = _seed_company_document(conn)
            src = _seed_source_version(conn, cid=cid, did=did, data=None, with_blob=False)
            succ = _seed_successor(conn, cid=cid, did=did, src=src)

        before = _m3_schema(eng)
        blobs_before = _blob_count(eng)

        timeline = []
        _record_sql(eng, timeline)
        with eng.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                with pytest.raises(RuntimeError, match="downgrade refused"):
                    m3.downgrade()

        mutating = [s for kind, s in timeline if kind == "sql" and _is_mutating_sql(s)]
        assert mutating == [], (
            "a refused downgrade must not execute ANY mutating statement; got: "
            f"{mutating}"
        )
        _assert_refused_state(
            eng, before, blobs_before=blobs_before, successor=succ, source=src
        )
    finally:
        eng.dispose()


def test_downgrade_call_runs_phases_in_order_and_mutates_only_after_preflight(mig):
    """Calling the REAL downgrade() on a safely materializable successor proves
    the phase ordering end to end: preflight completes first with zero mutating
    SQL, blob materialization happens strictly inside phase 2, and the first
    DDL appears only inside phase 3."""
    source_bytes = b"phase-ordering source bytes"
    m3 = _load_migration_module()
    mig.upgrade(M2_HEAD)
    mig.upgrade(M3)
    eng = mig.engine()
    try:
        with eng.begin() as conn:
            cid, did = _seed_company_document(conn)
            src = _seed_source_version(conn, cid=cid, did=did, data=source_bytes)
            succ = _seed_successor(conn, cid=cid, did=did, src=src)

        timeline = []
        for phase in (
            "_preflight_downgrade",
            "_materialize_successor_blobs",
            "_apply_m2_schema_downgrade",
        ):
            _wrap_phase(m3, phase, timeline)
        _record_sql(eng, timeline)

        with eng.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                m3.downgrade()
            conn.commit()

        phases = [entry for entry in timeline if entry[0] == "phase"]
        assert phases == [
            ("phase", "_preflight_downgrade:start"),
            ("phase", "_preflight_downgrade:end"),
            ("phase", "_materialize_successor_blobs:start"),
            ("phase", "_materialize_successor_blobs:end"),
            ("phase", "_apply_m2_schema_downgrade:start"),
            ("phase", "_apply_m2_schema_downgrade:end"),
        ], "downgrade() must run exactly preflight -> materialize -> apply DDL"

        preflight_end = timeline.index(("phase", "_preflight_downgrade:end"))
        materialize_end = timeline.index(("phase", "_materialize_successor_blobs:end"))
        early_mutations = [
            s for kind, s in timeline[:preflight_end]
            if kind == "sql" and _is_mutating_sql(s)
        ]
        assert early_mutations == [], (
            "no mutating statement may execute before the preflight completes; "
            f"got: {early_mutations}"
        )
        blob_inserts = [
            i for i, (kind, s) in enumerate(timeline)
            if kind == "sql" and s.lstrip().lower().startswith("insert")
            and "document_blobs" in s.lower()
        ]
        assert blob_inserts, "the successor blob must be materialized"
        assert all(preflight_end < i < materialize_end for i in blob_inserts), (
            "blob materialization must happen strictly inside phase 2"
        )

        # The downgrade really completed: M3 columns are gone and the successor
        # owns the exact source bytes.
        with eng.connect() as conn:
            insp = inspect(conn)
            dv_cols = {c["name"] for c in insp.get_columns("document_versions")}
            row = conn.execute(
                text("SELECT byte_size, data FROM document_blobs WHERE version_id = :v"),
                {"v": succ},
            ).fetchone()
        assert "source_version_id" not in dv_cols
        assert row is not None
        assert bytes(row.data) == source_bytes
        assert row.byte_size == len(source_bytes)
    finally:
        eng.dispose()


class _PreflightSentinel(Exception):
    """Raised by the instrumented preflight: proves downgrade() aborts with the
    exact exception and touches NOTHING when preflight fails."""


# Every op-level mutation entry point the M2 downgrade could conceivably use.
_OP_MUTATION_ENTRY_POINTS = (
    "batch_alter_table",
    "alter_column",
    "add_column",
    "drop_column",
    "drop_constraint",
    "drop_index",
    "create_index",
    "create_table",
    "drop_table",
    "create_unique_constraint",
    "create_foreign_key",
    "execute",
    "bulk_insert",
)


def test_downgrade_with_failing_preflight_calls_no_mutation_entry_point(
    mig, monkeypatch
):
    """Sentinel interception: _preflight_downgrade raises a sentinel while
    EVERY mutation path — the materialization phase, the schema phase, every
    op.* mutation entry point, and every mutating statement on the real
    connection — is intercepted. downgrade() must call preflight, call nothing
    else, execute no mutating SQL, and surface exactly the sentinel. A future
    edit that adds any mutation before preflight fails this test."""
    m3 = _load_migration_module()
    mig.upgrade(M2_HEAD)
    mig.upgrade(M3)
    eng = mig.engine()
    try:
        calls = []

        def sentinel_preflight(bind):
            calls.append("preflight")
            raise _PreflightSentinel()

        monkeypatch.setattr(m3, "_preflight_downgrade", sentinel_preflight)
        materialize = mock.MagicMock(name="_materialize_successor_blobs")
        apply_ddl = mock.MagicMock(name="_apply_m2_schema_downgrade")
        monkeypatch.setattr(m3, "_materialize_successor_blobs", materialize)
        monkeypatch.setattr(m3, "_apply_m2_schema_downgrade", apply_ddl)

        # Intercept the op-level mutation entry points on the (shared) alembic
        # op proxy; monkeypatch restores them after the test.
        op_mocks = {}
        for name in _OP_MUTATION_ENTRY_POINTS:
            if hasattr(m3.op, name):
                op_mocks[name] = mock.MagicMock(name=f"op.{name}")
                monkeypatch.setattr(m3.op, name, op_mocks[name])

        statements = []
        _record_sql(eng, statements)
        with eng.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                with pytest.raises(_PreflightSentinel):
                    m3.downgrade()

        assert calls == ["preflight"], "preflight must be called exactly once"
        assert not materialize.called, "no materialization phase may be called"
        assert not apply_ddl.called, "no schema phase may be called"
        for name, op_mock in op_mocks.items():
            assert not op_mock.called, f"mutation entry point op.{name} was called"
        mutating = [s for kind, s in statements if kind == "sql" and _is_mutating_sql(s)]
        assert mutating == [], f"mutating SQL executed despite failing preflight: {mutating}"
    finally:
        eng.dispose()


def test_downgrade_source_order_is_exactly_the_three_phases():
    """AST supplement (never a substitute for the runtime interception tests
    above): downgrade()'s body is EXACTLY get_bind -> _preflight_downgrade ->
    _materialize_successor_blobs -> _apply_m2_schema_downgrade, in that order,
    with no other calls — so any added statement is a reviewable diff here."""
    tree = ast.parse(_M3_MIGRATION_FILE.read_text(encoding="utf-8"))
    fn = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "downgrade"
    )
    called = []
    for stmt in fn.body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call):
                func = node.func
                called.append(
                    func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "?")
                )
    assert called == [
        "get_bind",
        "_preflight_downgrade",
        "_materialize_successor_blobs",
        "_apply_m2_schema_downgrade",
    ]


# --------------------------------------------------------------------------- #
# preflight plan determinism (white-box)
# --------------------------------------------------------------------------- #


def test_preflight_plan_is_deterministic_and_safe_for_db_backed_source(mig):
    """A DB-backed source yields a deterministic, conflict-free materialization
    plan (idempotent identity) without touching the schema."""
    m3 = _load_migration_module()
    mig.upgrade(M2_HEAD)
    mig.upgrade(M3)
    eng = mig.engine()
    try:
        with eng.begin() as conn:
            cid, did = _seed_company_document(conn)
            src = _seed_source_version(conn, cid=cid, did=did, data=b"bytes-here")
            succ = _seed_successor(conn, cid=cid, did=did, src=src)

        with eng.connect() as conn:
            plan_a = m3._plan_successor_materialization(conn)
            plan_b = m3._plan_successor_materialization(conn)
        assert len(plan_a) == 1
        assert plan_a[0].version_id == succ
        assert plan_a[0].data == b"bytes-here"
        # deterministic identity across runs (idempotent re-run)
        assert plan_a[0].blob_id == plan_b[0].blob_id
        assert plan_a[0].storage_key == plan_b[0].storage_key
    finally:
        eng.dispose()
