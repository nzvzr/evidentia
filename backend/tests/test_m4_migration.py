"""M4 data-bearing migration cycle on SQLite and optional PostgreSQL 16."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import event, inspect, text
from sqlalchemy.exc import IntegrityError

from tests.test_m3_migration import M3, _NOW, mig

M4 = "e4b7c9d2a610"


def _id() -> str:
    return str(uuid.uuid4())


def _seed_tenant_source(conn, label: str) -> dict[str, str]:
    ids = {key: _id() for key in ("company", "document", "version", "section")}
    conn.execute(
        text(
            "INSERT INTO companies (id,name,slug,created_at,updated_at) "
            "VALUES (:id,:name,:slug,:now,:now)"
        ),
        {"id": ids["company"], "name": label, "slug": f"{label.lower()}-{ids['company'][:8]}", "now": _NOW},
    )
    conn.execute(
        text(
            "INSERT INTO documents (id,company_id,title,slug,citation_prefix,source_type,status,created_at,updated_at) "
            "VALUES (:id,:company,'Policy',:slug,:prefix,'upload','ready',:now,:now)"
        ),
        {
            "id": ids["document"], "company": ids["company"],
            "slug": f"policy-{ids['document'][:8]}", "prefix": label[:3].upper(), "now": _NOW,
        },
    )
    conn.execute(
        text(
            "INSERT INTO document_versions "
            "(id,document_id,company_id,version_no,status,anchor_algo_version,manifest_sha256,"
            "finalization_engine,classification_signature,created_at) "
            "VALUES (:id,:document,:company,1,'ready','heading-path-v1',:sha,:engine,:sha,:now)"
        ),
        {
            "id": ids["version"], "document": ids["document"], "company": ids["company"],
            "sha": "a" * 64, "engine": "cft1:" + "b" * 64, "now": _NOW,
        },
    )
    conn.execute(
        text(
            "INSERT INTO document_sections "
            "(id,company_id,document_id,version_id,anchor_id,citation_id,ordinal,depth,"
            "heading_path,title,text,classification_signature,created_at) "
            "VALUES (:id,:company,:document,:version,:anchor,:citation,0,1,'[\"Policy\"]',"
            "'Policy','Bounded policy text',:signature,:now)"
        ),
        {
            "id": ids["section"], "company": ids["company"], "document": ids["document"],
            "version": ids["version"], "anchor": f"anc-{label}", "citation": f"{label}-001",
            "signature": "c" * 64, "now": _NOW,
        },
    )
    conn.execute(
        text("UPDATE documents SET current_version_id=:version WHERE id=:document"),
        {"version": ids["version"], "document": ids["document"]},
    )
    return ids


def test_m4_data_bearing_cycle_and_tenant_constraints(mig):
    mig.upgrade(M3)
    eng = mig.engine()
    if eng.dialect.name == "sqlite":
        @event.listens_for(eng, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    demo_report = _id()
    try:
        with eng.begin() as conn:
            a = _seed_tenant_source(conn, "AAA")
            b = _seed_tenant_source(conn, "BBB")
            conn.execute(
                text(
                    "INSERT INTO reports (id,company_id,title,report_json,created_at,updated_at) "
                    "VALUES (:id,:company,'Legacy demo','{}',:now,:now)"
                ),
                {"id": demo_report, "company": a["company"], "now": _NOW},
            )

        mig.upgrade(M4)
        report_id, source_id, binding_id = _id(), _id(), _id()
        with eng.begin() as conn:
            legacy = conn.execute(
                text(
                    "SELECT corpus_mode,generation_status,source_version_count,evidence_section_count "
                    "FROM reports WHERE id=:id"
                ),
                {"id": demo_report},
            ).one()
            assert tuple(legacy) == ("demo", "completed", 0, 0)
            conn.execute(
                text(
                    "INSERT INTO reports "
                    "(id,company_id,title,report_json,corpus_mode,generation_status,source_version_count,"
                    "evidence_section_count,created_at,updated_at) "
                    "VALUES (:id,:company,'Tenant report','{}','tenant','completed',1,1,:now,:now)"
                ),
                {"id": report_id, "company": a["company"], "now": _NOW},
            )
            conn.execute(
                text(
                    "INSERT INTO report_source_versions "
                    "(id,report_id,company_id,document_id,document_version_id,version_no,manifest_sha256,"
                    "finalization_target_digest,position) "
                    "VALUES (:id,:report,:company,:document,:version,1,:manifest,:target,0)"
                ),
                {
                    "id": source_id, "report": report_id, "company": a["company"],
                    "document": a["document"], "version": a["version"],
                    "manifest": "a" * 64, "target": "cft1:" + "b" * 64,
                },
            )
            conn.execute(
                text(
                    "INSERT INTO report_evidence_bindings "
                    "(id,report_id,company_id,report_source_version_id,document_id,document_version_id,"
                    "section_id,anchor_id,citation_id,section_ordinal,section_signature,retrieval_rank,"
                    "retrieval_score,evidence_excerpt,document_title,section_title) "
                    "VALUES (:id,:report,:company,:source,:document,:version,:section,:anchor,:citation,"
                    "0,:signature,1,10.0,'Bounded','Policy','Policy')"
                ),
                {
                    "id": binding_id, "report": report_id, "company": a["company"],
                    "source": source_id, "document": a["document"], "version": a["version"],
                    "section": a["section"], "anchor": "anc-AAA", "citation": "AAA-001",
                    "signature": "c" * 64,
                },
            )

        with pytest.raises(IntegrityError):
            with eng.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO report_source_versions "
                        "(id,report_id,company_id,document_id,document_version_id,version_no,manifest_sha256,"
                        "finalization_target_digest,position) VALUES (:id,:report,:company,:document,"
                        ":version,1,:manifest,:target,1)"
                    ),
                    {
                        "id": _id(), "report": report_id, "company": a["company"],
                        "document": b["document"], "version": b["version"],
                        "manifest": "a" * 64, "target": "cft1:" + "b" * 64,
                    },
                )

        mig.downgrade(M3)
        with eng.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM reports")).scalar_one() == 2
            assert conn.execute(text("SELECT COUNT(*) FROM documents")).scalar_one() == 2
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == M3
            tables = set(inspect(conn).get_table_names())
            assert "report_source_versions" not in tables
            assert "report_evidence_bindings" not in tables
            assert "corpus_mode" not in {c["name"] for c in inspect(conn).get_columns("reports")}

        mig.upgrade(M4)
        with eng.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == M4
            assert conn.execute(text("SELECT COUNT(*) FROM reports")).scalar_one() == 2
            assert conn.execute(text("SELECT COUNT(*) FROM documents")).scalar_one() == 2
            assert conn.execute(text("SELECT COUNT(*) FROM report_source_versions")).scalar_one() == 0
            assert conn.execute(text("SELECT COUNT(*) FROM report_evidence_bindings")).scalar_one() == 0
    finally:
        eng.dispose()
