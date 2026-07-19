"""API + security tests for the tenant-scoped DOCX export endpoint (Phase 10).

Every test drives the real FastAPI app through the shared harness. The export
endpoint reuses the report authorization path, so the tenant-isolation shape is
the same as the rest of the report API: Alice (Acme) owns a report; Bob (Globex)
is authenticated but must never export it, even naming Alice's company id.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from xml.dom import minidom

from app.core.config import get_settings
from app.models.db_models import Report
from tests.conftest import GEN_INPUT, seed_finalized_document

DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)

# Distinct per-tenant markers embedded in each corpus, so a cross-tenant leak is
# detectable in the rendered bytes.
ACME_POLICY = b"""# Acme Access Control Policy

## Administrative access

Administrative access requires multi-factor authentication. Unique marker: ACMEMARK-111-A.

## Incident escalation

Severity one incidents require immediate on-call escalation and a review.
"""

GLOBEX_POLICY = b"""# Globex Access Control Policy

## Administrative access

Administrative access requires hardware keys. Unique marker: GLOBEXMARK-222-B.

## Incident escalation

Severity one incidents require immediate on-call escalation and a review.
"""


def _generate(account, session_factory, monkeypatch, body=ACME_POLICY) -> str:
    seed_finalized_document(account, session_factory, monkeypatch, body=body)
    res = account.post("/api/generate-workflow", json=GEN_INPUT)
    assert res.status_code == 200, res.text
    return res.json()["id"]


def _export(account, report_id, **kw):
    return account.get(f"/api/reports/{report_id}/export/docx", **kw)


# --- happy path -----------------------------------------------------------


def test_export_returns_a_valid_docx(client, alice, session_factory, monkeypatch):
    report_id = _generate(alice, session_factory, monkeypatch)
    res = _export(alice, report_id)
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == DOCX_CONTENT_TYPE

    disposition = res.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "evidentia-" in disposition and ".docx" in disposition

    # Valid ZIP + parseable Word XML.
    zf = zipfile.ZipFile(io.BytesIO(res.content))
    assert "word/document.xml" in zf.namelist()
    minidom.parseString(zf.read("word/document.xml"))


def test_export_headers_carry_renderer_metadata(client, alice, session_factory, monkeypatch):
    report_id = _generate(alice, session_factory, monkeypatch)
    res = _export(alice, report_id)
    assert res.headers["x-evidentia-renderer"] == "docx-renderer"
    assert res.headers["x-evidentia-renderer-version"] == "docx-renderer-v1"
    # The advertised content hash must match the delivered bytes exactly.
    assert res.headers["x-evidentia-content-hash"] == hashlib.sha256(res.content).hexdigest()
    assert len(res.headers["x-evidentia-semantic-digest"]) == 64


def test_export_is_byte_deterministic(client, alice, session_factory, monkeypatch):
    report_id = _generate(alice, session_factory, monkeypatch)
    first = _export(alice, report_id)
    second = _export(alice, report_id)
    assert first.status_code == 200 and second.status_code == 200
    assert first.content == second.content
    assert (
        first.headers["x-evidentia-content-hash"]
        == second.headers["x-evidentia-content-hash"]
    )


def test_letter_page_size_option_still_renders(client, alice, session_factory, monkeypatch):
    report_id = _generate(alice, session_factory, monkeypatch)
    res = _export(alice, report_id, params={"page": "Letter"})
    assert res.status_code == 200
    minidom.parseString(zipfile.ZipFile(io.BytesIO(res.content)).read("word/document.xml"))


def test_exported_docx_contains_tenant_citation_and_audit(
    client, alice, session_factory, monkeypatch
):
    report_id = _generate(alice, session_factory, monkeypatch)
    res = _export(alice, report_id)
    text = zipfile.ZipFile(io.BytesIO(res.content)).read("word/document.xml").decode("utf-8")
    # The tenant's own corpus and audit are present.
    assert "Audit appendix" in text
    assert "tenant" in text.lower()


# --- tenant isolation -----------------------------------------------------


def test_bob_cannot_export_alices_report(client, alice, bob, session_factory, monkeypatch):
    report_id = _generate(alice, session_factory, monkeypatch)
    assert _export(alice, report_id).status_code == 200
    res = _export(bob, report_id)
    assert res.status_code == 404, "cross-tenant export must 404"
    assert "ACMEMARK" not in res.text


def test_forged_company_id_cannot_export(client, alice, bob, session_factory, monkeypatch):
    report_id = _generate(alice, session_factory, monkeypatch)
    res = bob.get(
        f"/api/reports/{report_id}/export/docx",
        headers={"X-Company-Id": alice.company_id},
    )
    assert res.status_code == 404


def test_no_other_tenant_marker_appears_in_export(
    client, alice, bob, session_factory, monkeypatch
):
    # Both tenants finalize corpora with distinct unique markers.
    globex_report = _generate(bob, session_factory, monkeypatch, body=GLOBEX_POLICY)
    acme_report = _generate(alice, session_factory, monkeypatch, body=ACME_POLICY)

    acme_bytes = _export(alice, acme_report).content
    acme_text = zipfile.ZipFile(io.BytesIO(acme_bytes)).read("word/document.xml").decode("utf-8")
    # Alice's document must never contain Globex's marker.
    assert "GLOBEXMARK-222-B" not in acme_text
    # And Bob still cannot reach Alice's report at all.
    assert _export(bob, acme_report).status_code == 404
    assert _export(alice, globex_report).status_code == 404


# --- unauthenticated / not-exportable -------------------------------------


def test_unauthenticated_export_is_rejected(client, alice, session_factory, monkeypatch):
    report_id = _generate(alice, session_factory, monkeypatch)
    # No Authorization header.
    res = client.get(f"/api/reports/{report_id}/export/docx")
    assert res.status_code == 401


def test_unknown_report_is_404(client, alice):
    assert _export(alice, "does-not-exist").status_code == 404


def test_failed_report_is_not_exportable(client, alice, db_session, session_factory, monkeypatch):
    """A non-completed (failed/running) report must not export — enumeration-safe 404."""
    seed_finalized_document(alice, session_factory, monkeypatch)
    failed = Report(
        company_id=alice.company_id,
        user_id=alice.user_id,
        title="failed",
        report_json={},
        generation_status="failed",
        corpus_mode="tenant",
    )
    db_session.add(failed)
    db_session.commit()
    res = _export(alice, failed.id)
    assert res.status_code == 404


# --- rate limiting --------------------------------------------------------


def test_export_is_rate_limited(client, alice, session_factory, monkeypatch):
    report_id = _generate(alice, session_factory, monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "rl_export_ip_limit", 2)
    monkeypatch.setattr(settings, "rl_export_user_limit", 2)
    monkeypatch.setattr(settings, "rl_export_tenant_limit", 2)

    assert _export(alice, report_id).status_code == 200
    assert _export(alice, report_id).status_code == 200
    throttled = _export(alice, report_id)
    assert throttled.status_code == 429
    assert throttled.json()["code"] == "rate_limited"
