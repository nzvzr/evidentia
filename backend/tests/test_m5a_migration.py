"""M5a data-bearing migration cycle on SQLite and optional PostgreSQL 16."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import event, inspect, text
from sqlalchemy.exc import IntegrityError

from tests.test_m3_migration import _NOW, mig
from tests.test_m4_migration import M4, _seed_tenant_source

M5A = "f5a6c7d8e9b0"
M5A_TABLES = {
    "claim_pattern_versions", "report_claim_candidates", "report_claim_decisions",
    "report_claim_evidence", "pattern_metrics", "report_feedback", "item_feedback",
    "citation_feedback", "retrieval_misses",
}


def _id() -> str:
    return str(uuid.uuid4())


def _seed_report(conn, source: dict[str, str], label: str) -> tuple[str, str]:
    report_id, source_id, binding_id = _id(), _id(), _id()
    conn.execute(text(
        "INSERT INTO reports (id,company_id,title,report_json,corpus_mode,generation_status,"
        "source_version_count,evidence_section_count,created_at,updated_at) "
        "VALUES (:id,:company,:title,'{}','tenant','completed',1,1,:now,:now)"
    ), {"id": report_id, "company": source["company"], "title": label, "now": _NOW})
    conn.execute(text(
        "INSERT INTO report_source_versions (id,report_id,company_id,document_id,document_version_id,"
        "version_no,manifest_sha256,finalization_target_digest,position) VALUES "
        "(:id,:report,:company,:document,:version,1,:manifest,:target,0)"
    ), {"id": source_id, "report": report_id, "company": source["company"],
        "document": source["document"], "version": source["version"], "manifest": "a" * 64,
        "target": "cft1:" + "b" * 64})
    conn.execute(text(
        "INSERT INTO report_evidence_bindings (id,report_id,company_id,report_source_version_id,"
        "document_id,document_version_id,section_id,anchor_id,citation_id,section_ordinal,"
        "section_signature,retrieval_rank,retrieval_score,evidence_excerpt,document_title,section_title) "
        "VALUES (:id,:report,:company,:source,:document,:version,:section,:anchor,:citation,0,"
        ":signature,1,10.0,'Bounded','Policy','Policy')"
    ), {"id": binding_id, "report": report_id, "company": source["company"], "source": source_id,
        "document": source["document"], "version": source["version"], "section": source["section"],
        "anchor": f"anc-{label}", "citation": f"{label}-001", "signature": "c" * 64})
    return report_id, binding_id


def test_m5a_data_cycle_exact_m4_downgrade_and_hostile_tenant_references(mig):
    mig.upgrade(M4)
    eng = mig.engine()
    if eng.dialect.name == "sqlite":
        @event.listens_for(eng, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    try:
        with eng.begin() as conn:
            tenant_a = _seed_tenant_source(conn, "M5A")
            tenant_b = _seed_tenant_source(conn, "M5B")
            report_a, binding_a = _seed_report(conn, tenant_a, "M5A")
            report_a_other, binding_a_other = _seed_report(conn, tenant_a, "M5A-OTHER")
            report_b, binding_b = _seed_report(conn, tenant_b, "M5B")
        with eng.connect() as conn:
            before_tables = set(inspect(conn).get_table_names())
            before_binding_uniques = {
                item["name"] for item in inspect(conn).get_unique_constraints("report_evidence_bindings")
            }

        mig.upgrade(M5A)
        pattern_id, candidate_id, candidate_row_id, user_id = _id(), "d" * 64, _id(), _id()
        with eng.begin() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM report_claim_candidates")).scalar_one() == 0
            conn.execute(text(
                "INSERT INTO users (id,email,is_active,token_version,created_at,updated_at) "
                "VALUES (:id,:email,:active,0,:now,:now)"
            ), {"id": user_id, "email": f"m5a-{user_id}@example.test", "active": True, "now": _NOW})
            conn.execute(text(
                "INSERT INTO claim_pattern_versions (id,claim_pack_id,claim_pack_version,module_id,module_version,claim_spec_id,pattern_version,"
                "schema_version,release_version,release_digest,pattern_digest,definition_json,imported_at) "
                "VALUES (:id,'compliance.claim-patterns','1.0.0','compliance','1.0.0','mfa','1.0.0','claim-patterns-v1','1.0.0',:digest,:digest,'{}',:now)"
            ), {"id": pattern_id, "digest": "e" * 64, "now": _NOW})
            conn.execute(text(
                "INSERT INTO report_claim_candidates (id,report_id,company_id,claim_pattern_version_id,"
                "candidate_id,claim_spec_id,pattern_version,candidate_source,proposed_statement,"
                "source_snapshot_digest,matcher_observations,deterministic_features,status_before_gate,"
                "appeared_in_final,created_at) VALUES (:id,:report,:company,:pattern,:candidate,'mfa',"
                "'1.0.0','deterministic_pattern','MFA is required',:snapshot,'[]','{}','proposed',:appeared,:now)"
            ), {"id": candidate_row_id, "report": report_a, "company": tenant_a["company"],
                "pattern": pattern_id, "candidate": candidate_id, "snapshot": "tcs1:" + "f" * 64,
                "appeared": True, "now": _NOW})
            conn.execute(text(
                "INSERT INTO report_claim_decisions (id,report_claim_candidate_id,report_id,company_id,"
                "decision,support_score,threshold,reason_codes,matched_requirements,missing_requirements,"
                "conflicting_evidence,accepted_binding_ids,gate_policy_id,gate_policy_version,"
                "gate_engine_version,deterministic_features,created_at) VALUES (:id,:candidate,:report,"
                ":company,'accepted',1.0,0.8,'[\"accepted\"]','[\"mfa\"]','[]','[]','[\"M5A-001\"]',"
                "'default','1.0.0','deterministic-support-gate-v1','{}',:now)"
            ), {"id": _id(), "candidate": candidate_row_id, "report": report_a,
                "company": tenant_a["company"], "now": _NOW})
            conn.execute(text(
                "INSERT INTO report_claim_evidence (id,report_claim_candidate_id,report_evidence_binding_id,"
                "report_id,company_id,proposed,accepted) VALUES (:id,:candidate,:binding,:report,:company,:proposed,:accepted)"
            ), {"id": _id(), "candidate": candidate_row_id, "binding": binding_a,
                "report": report_a, "company": tenant_a["company"], "proposed": True, "accepted": True})
            conn.execute(text(
                "INSERT INTO report_feedback (id,report_id,company_id,user_id,verdict,created_at,updated_at) "
                "VALUES (:id,:report,:company,:user,'correct_useful',:now,:now)"
            ), {"id": _id(), "report": report_a, "company": tenant_a["company"],
                "user": user_id, "now": _NOW})

        with pytest.raises(IntegrityError):
            with eng.begin() as conn:
                conn.execute(text(
                    "INSERT INTO report_claim_candidates (id,report_id,company_id,candidate_id,claim_spec_id,"
                    "pattern_version,candidate_source,proposed_statement,source_snapshot_digest,"
                    "matcher_observations,deterministic_features,status_before_gate,appeared_in_final,created_at) "
                    "VALUES (:id,:report,:foreign_company,:candidate,'mfa','1.0.0','deterministic_pattern',"
                    "'hostile',:snapshot,'[]','{}','proposed',:appeared,:now)"
                ), {"id": _id(), "report": report_a, "foreign_company": tenant_b["company"],
                    "candidate": "a" * 64, "snapshot": "tcs1:" + "b" * 64,
                    "appeared": False, "now": _NOW})
        with pytest.raises(IntegrityError):
            with eng.begin() as conn:
                conn.execute(text(
                    "INSERT INTO report_claim_evidence (id,report_claim_candidate_id,report_evidence_binding_id,"
                    "report_id,company_id,proposed,accepted) VALUES (:id,:candidate,:foreign_binding,:report,:company,:proposed,:accepted)"
                ), {"id": _id(), "candidate": candidate_row_id, "foreign_binding": binding_b,
                    "report": report_a, "company": tenant_a["company"], "proposed": True, "accepted": True})
        with pytest.raises(IntegrityError):
            with eng.begin() as conn:
                conn.execute(text(
                    "INSERT INTO report_feedback (id,report_id,company_id,user_id,verdict,created_at,updated_at) "
                    "VALUES (:id,:report,:foreign_company,:user,'incorrect',:now,:now)"
                ), {"id": _id(), "report": report_a, "foreign_company": tenant_b["company"],
                    "user": user_id, "now": _NOW})
        for hostile_binding in (binding_a_other, binding_b):
            with pytest.raises(IntegrityError):
                with eng.begin() as conn:
                    conn.execute(text(
                        "INSERT INTO citation_feedback (id,report_id,company_id,user_id,"
                        "report_evidence_binding_id,item_path,citation_id,verdict,"
                        "corrected_report_evidence_binding_id,created_at,updated_at) VALUES "
                        "(:id,:report,:company,:user,:binding,'/citations/0','M5A-001',"
                        "'incorrect_source',:hostile,:now,:now)"
                    ), {"id": _id(), "report": report_a, "company": tenant_a["company"],
                        "user": user_id, "binding": binding_a, "hostile": hostile_binding,
                        "now": _NOW})
        with pytest.raises(IntegrityError):
            with eng.begin() as conn:
                conn.execute(text(
                    "INSERT INTO citation_feedback (id,report_id,company_id,user_id,"
                    "report_evidence_binding_id,item_path,citation_id,verdict,created_at,updated_at) "
                    "VALUES (:id,:report,:company,:user,:binding,'/citations/0','M5A-001',"
                    "'incorrect_source',:now,:now)"
                ), {"id": _id(), "report": report_a, "company": tenant_a["company"],
                    "user": user_id, "binding": binding_a, "now": _NOW})

        mig.downgrade(M4)
        with eng.connect() as conn:
            assert set(inspect(conn).get_table_names()) == before_tables
            assert {item["name"] for item in inspect(conn).get_unique_constraints(
                "report_evidence_bindings"
            )} == before_binding_uniques
            assert conn.execute(text("SELECT COUNT(*) FROM reports")).scalar_one() == 3
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == M4

        mig.upgrade(M5A)
        with eng.connect() as conn:
            assert M5A_TABLES <= set(inspect(conn).get_table_names())
            assert conn.execute(text("SELECT COUNT(*) FROM reports")).scalar_one() == 3
            assert conn.execute(text("SELECT COUNT(*) FROM report_claim_candidates")).scalar_one() == 0
            assert conn.execute(text("SELECT COUNT(*) FROM report_feedback")).scalar_one() == 0
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == M5A
    finally:
        eng.dispose()
