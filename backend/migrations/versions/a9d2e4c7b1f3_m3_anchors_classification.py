"""M3: stable anchors, citation identities, deterministic classification

Additive for every pre-M3 row — no data is rewritten and every pre-M3 row
remains valid and readable. Design: docs/ai/PLATFORM_ARCHITECTURE.md §7
(versioned anchor algorithm, the M3 gate in §12) and
docs/ai/DOCUMENT_INGESTION_ARCHITECTURE.md §4/§6. The binding M2→M3
lifecycle contract (DECISIONS.md 2026-07-16) is honored by shape:
finalization creates a NEW document_versions row and never mutates a
`pre-m3-transitional` version, its sections, or its manifest.

Adds:
  * document_versions.{source_version_id, finalization_engine,
    engine_versions, classification_signature}
    - source_version_id: which transitional version a successor was
      re-ingested from. DB-ENFORCED tenancy/document integrity: the composite
      self-referential FK (source_version_id, document_id, company_id) ->
      (id, document_id, company_id) makes a cross-document or cross-tenant
      source unrepresentable, and (NO ACTION semantics) blocks deleting a
      referenced source alone while still permitting whole-document/tenant
      CASCADEs that remove source + successor together. Explicit chain rule:
      a successor references ONLY the blob-owning transitional upload version
      (never another successor) — service-enforced direction, DB-enforced
      ownership.
    - finalization_engine: the COMPLETE finalization target digest
      ("cft1:<sha256>" over parser/normalizer/sectionizer/anchor algorithm/
      inheritance/classifier/section-signature/module id+version+digest+
      signatureVersion/manifest/thresholds/weights), width 80.
    - unique (source_version_id, finalization_engine): at most ONE successor
      per source version and COMPLETE target, DB-enforced against concurrent
      finalization triggers. NULLs distinct => upload versions unaffected.
    - unique (id, document_id, company_id): the composite parent key the
      self-reference requires.
  * document_sections.{anchor_provenance, matched_rules,
    classification_signature} — inheritance provenance + deterministic rule
    ids + per-section classification signature.
  * ingestion_jobs.operation — explicit typed discriminator
    ("ingest" default = M2 semantics; "finalize" = M3 successor processing).
    server_default keeps every existing row meaning what it meant.
  * documents.citation_prefix widened 8 -> 12 chars: a 5-char base plus a
    numeric collision suffix minted through the configured tenant document
    quota (default 500) must always fit.

Downgrade (data-preserving, PREFLIGHT-FIRST):
  SQLite/Alembic DDL cannot be assumed to roll back atomically (batch table
  recreation is a DROP+RENAME sequence). An intentional safe refusal must
  therefore leave the COMPLETE M3 schema untouched, so the downgrade runs in
  three strictly ordered phases and no schema operation executes before every
  refusal condition has been checked:

  * PHASE 1 — preflight (no schema mutation, no insert): every refusal
    condition is evaluated up front against live data, for EVERY successor
    with a non-null source_version_id — including successors that already own
    a document_blobs row. (a) citation_prefix: refuse if any stored value
    exceeds the M2 width of 8 (identity values are never truncated).
    (b) successor blob resolvability: the source version must exist, belong to
    the SAME document and tenant, and own exactly one valid document_blobs
    binding — DB-backed data, size and content hash consistent with the bytes,
    correct tenancy. ZERO source blobs refuses (removing source_version_id
    would strand the successor without resolvable bytes); multiple or
    metadata-inconsistent source blobs refuse as ambiguous. (c) a successor
    that ALREADY owns a blob row is accepted only when that blob is an exact
    safe equivalent of the source binding (same bytes, same size, valid
    ownership) — then it counts as already materialized (idempotent re-run);
    any divergence refuses without overwriting or deleting anything.
    (d) planned insertions must be free of uniqueness conflicts. The whole
    plan is built globally before any row is written: a refusal for ANY
    successor means NO successor blob is inserted.
  * PHASE 2 — materialize (data only, lineage still present): give each
    successor its OWN document_blobs row from the deterministic plan, reusing
    the source's content-addressed bytes (no physical duplication), while
    source_version_id and every M3 lineage column still exist.
  * PHASE 3 — schema downgrade (DDL): only now narrow citation_prefix, drop
    ingestion_jobs.operation, the M3 section columns, and the source/
    finalization columns/indexes/constraints, in dependency order, to arrive
    at exactly the committed M2 schema.

  downgrade() is deliberately nothing but the three phase calls in that order
  (preflight -> materialize -> apply DDL) so the ordering invariant is
  reviewable at a glance and regression-tested by calling downgrade() itself.

Revision ID: a9d2e4c7b1f3
Revises: f7c3a1b9e2d4
"""

import hashlib
import uuid
from datetime import datetime
from typing import List, NamedTuple, Optional, Sequence, Union

import sqlalchemy as sa
from alembic import op

# Deterministic namespace for materialized-blob identities: the same successor
# version always maps to the same blob id/storage_key, so a re-run is idempotent.
_MATERIALIZE_NS = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")

revision: str = "a9d2e4c7b1f3"
down_revision: Union[str, None] = "f7c3a1b9e2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("document_versions") as batch:
        batch.add_column(sa.Column("source_version_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("finalization_engine", sa.String(80), nullable=True))
        batch.add_column(sa.Column("engine_versions", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("classification_signature", sa.String(64), nullable=True))
        batch.create_unique_constraint(
            "uq_document_versions_id_doc_company", ["id", "document_id", "company_id"]
        )
        batch.create_foreign_key(
            "fk_document_versions_source_same_doc",
            "document_versions",
            ["source_version_id", "document_id", "company_id"],
            ["id", "document_id", "company_id"],
        )
    op.create_index(
        "uq_document_versions_source_engine",
        "document_versions",
        ["source_version_id", "finalization_engine"],
        unique=True,
    )

    with op.batch_alter_table("document_sections") as batch:
        batch.add_column(sa.Column("anchor_provenance", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("matched_rules", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("classification_signature", sa.String(64), nullable=True))

    with op.batch_alter_table("ingestion_jobs") as batch:
        batch.add_column(
            sa.Column("operation", sa.String(20), nullable=False, server_default="ingest")
        )

    with op.batch_alter_table("documents") as batch:
        batch.alter_column(
            "citation_prefix", existing_type=sa.String(8), type_=sa.String(12)
        )


class _BlobMaterialization(NamedTuple):
    """One planned document_blobs row for a successor version, decided entirely
    during preflight so PHASE 2 performs no further validation."""

    blob_id: str
    version_id: str
    company_id: str
    storage_key: str
    byte_size: int
    data: bytes


class _DowngradePlan(NamedTuple):
    """The complete, globally validated downgrade work plan. Produced by
    _preflight_downgrade before any row is inserted and before any DDL runs;
    consumed verbatim by _materialize_successor_blobs."""

    blob_materializations: List[_BlobMaterialization]


def _validated_blob_bytes(
    blob_row,
    *,
    role: str,
    successor_id: str,
    expected_company_id: str,
    expected_sha256: Optional[str],
) -> bytes:
    """Validate one document_blobs row against the frozen M2 schema contract
    (correct tenancy, non-empty storage key, DB-backed data, size and content
    hash consistent with the actual bytes) and return those bytes. Any gap is
    a preflight refusal: an unprovable blob must never be trusted silently."""
    if blob_row.company_id != expected_company_id:
        raise RuntimeError(
            "downgrade refused: the "
            f"{role} blob for successor version {successor_id} belongs to a "
            "different tenant; refusing to cross ownership lineage."
        )
    if not blob_row.storage_key:
        raise RuntimeError(
            "downgrade refused: the "
            f"{role} blob for successor version {successor_id} has no storage "
            "key; its metadata is incomplete."
        )
    if blob_row.data is None:
        raise RuntimeError(
            "downgrade refused: the "
            f"{role} blob for successor version {successor_id} is not "
            "DB-backed (data is NULL) and cannot be materialized. Migrate the "
            "blob storage first or delete the successor versions explicitly."
        )
    raw = bytes(blob_row.data)
    if blob_row.byte_size is None or blob_row.byte_size != len(raw):
        raise RuntimeError(
            "downgrade refused: the "
            f"{role} blob for successor version {successor_id} has a byte_size "
            "that does not match its stored bytes; its metadata is invalid."
        )
    if expected_sha256 is not None and hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise RuntimeError(
            "downgrade refused: the "
            f"{role} blob for successor version {successor_id} does not match "
            "the recorded content hash; its metadata is invalid."
        )
    return raw


def _preflight_citation_prefix_width(bind) -> None:
    """Refuse (before ANY DDL) if narrowing citation_prefix to the M2 width
    would truncate a stored identity value."""
    too_long = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM documents "
            "WHERE citation_prefix IS NOT NULL AND LENGTH(citation_prefix) > 8"
        )
    ).scalar()
    if too_long:
        raise RuntimeError(
            "downgrade refused: documents.citation_prefix values longer than 8 "
            "characters exist; they would be truncated by the M2 column width."
        )


def _plan_successor_materialization(bind) -> List[_BlobMaterialization]:
    """PREFLIGHT: validate that EVERY successor's bytes remain safely resolvable
    once source_version_id is dropped, and return the deterministic insertion
    plan. Performs NO schema mutation and NO insert; raises RuntimeError (safe
    refusal) if ANY successor cannot be proven safe. Callers MUST run this
    before any DDL so a refusal leaves the schema untouched.

    Every successor with a non-null source_version_id is preflighted — a
    successor that already owns a document_blobs row is NOT skipped: its
    existing blob must prove exact equivalence to the source binding (same
    bytes, same size, valid ownership) to count as already materialized;
    any divergence refuses without overwriting or deleting anything. The plan
    is built globally: a refusal for any successor means no blob is inserted
    for any successor.
    """
    successors = bind.execute(
        sa.text(
            "SELECT v.id, v.company_id, v.document_id, v.source_version_id, "
            "v.content_sha256 "
            "FROM document_versions v "
            "WHERE v.source_version_id IS NOT NULL "
            "ORDER BY v.id"
        )
    ).fetchall()

    plan: List[_BlobMaterialization] = []
    planned_keys: set = set()
    for version_id, company_id, document_id, source_version_id, successor_sha in successors:
        source = bind.execute(
            sa.text(
                "SELECT id, document_id, company_id, content_sha256 "
                "FROM document_versions WHERE id = :sid"
            ),
            {"sid": source_version_id},
        ).fetchone()
        if source is None:
            raise RuntimeError(
                "downgrade refused: successor version "
                f"{version_id} references source version {source_version_id}, "
                "which does not exist."
            )
        if source.document_id != document_id or source.company_id != company_id:
            raise RuntimeError(
                "downgrade refused: successor version "
                f"{version_id} references a source version in a different "
                "document or tenant; refusing to materialize an ambiguous blob."
            )

        source_blobs = bind.execute(
            sa.text(
                "SELECT id, company_id, storage_key, byte_size, data "
                "FROM document_blobs WHERE version_id = :sid"
            ),
            {"sid": source_version_id},
        ).fetchall()
        if len(source_blobs) == 0:
            raise RuntimeError(
                "downgrade refused: successor version "
                f"{version_id} resolves its bytes through source version "
                f"{source_version_id}, which has no document_blobs row. "
                "Removing source_version_id would leave the successor unable "
                "to resolve its bytes; restore the source blob or delete the "
                "successor versions explicitly."
            )
        if len(source_blobs) > 1:
            raise RuntimeError(
                "downgrade refused: source version "
                f"{source_version_id} has multiple blob bindings; refusing to "
                "materialize an ambiguous successor blob."
            )
        source_bytes = _validated_blob_bytes(
            source_blobs[0],
            role="source",
            successor_id=version_id,
            expected_company_id=company_id,
            expected_sha256=source.content_sha256,
        )
        if (
            successor_sha is not None
            and hashlib.sha256(source_bytes).hexdigest() != successor_sha
        ):
            raise RuntimeError(
                "downgrade refused: successor version "
                f"{version_id} records a content hash that does not match its "
                "source version's bytes; refusing to materialize a blob that "
                "would contradict the successor's own metadata."
            )

        existing_blobs = bind.execute(
            sa.text(
                "SELECT id, company_id, storage_key, byte_size, data "
                "FROM document_blobs WHERE version_id = :vid"
            ),
            {"vid": version_id},
        ).fetchall()
        if len(existing_blobs) > 1:
            raise RuntimeError(
                "downgrade refused: successor version "
                f"{version_id} has multiple document_blobs rows; refusing to "
                "validate an ambiguous existing binding."
            )
        if len(existing_blobs) == 1:
            existing_bytes = _validated_blob_bytes(
                existing_blobs[0],
                role="pre-existing successor",
                successor_id=version_id,
                expected_company_id=company_id,
                expected_sha256=source.content_sha256,
            )
            if (
                existing_bytes != source_bytes
                or existing_blobs[0].byte_size != len(source_bytes)
            ):
                raise RuntimeError(
                    "downgrade refused: successor version "
                    f"{version_id} already owns a document_blobs row whose "
                    "content differs from its source version's bytes; refusing "
                    "to silently retain, overwrite or delete it."
                )
            # Exact safe equivalent of the source binding: the successor is
            # already materialized. Idempotent — nothing to plan, nothing to
            # touch.
        else:
            # Deterministic identity (idempotent across re-runs). The content
            # bytes, size and tenancy are reused verbatim — no physical
            # duplication of the object-store identity.
            blob_id = str(uuid.uuid5(_MATERIALIZE_NS, version_id))
            storage_key = f"db:{blob_id}"
            # Materialization feasibility: the target blob row must be
            # insertable without a uniqueness conflict.
            conflict = bind.execute(
                sa.text("SELECT 1 FROM document_blobs WHERE storage_key = :key"),
                {"key": storage_key},
            ).fetchone()
            if conflict is not None or storage_key in planned_keys:
                raise RuntimeError(
                    "downgrade refused: materializing a blob for successor "
                    f"version {version_id} would conflict with an existing "
                    "document_blobs row."
                )
            planned_keys.add(storage_key)
            plan.append(
                _BlobMaterialization(
                    blob_id=blob_id,
                    version_id=version_id,
                    company_id=company_id,
                    storage_key=storage_key,
                    byte_size=len(source_bytes),
                    data=source_bytes,
                )
            )
    return plan


def _preflight_downgrade(bind) -> _DowngradePlan:
    """PHASE 1: evaluate EVERY refusal condition and build the complete work
    plan. Pure reads — no schema mutation, no insert — so a refusal here
    leaves the COMPLETE M3 schema and all data untouched."""
    _preflight_citation_prefix_width(bind)
    return _DowngradePlan(
        blob_materializations=_plan_successor_materialization(bind)
    )


def _materialize_successor_blobs(bind, plan: _DowngradePlan) -> None:
    """PHASE 2: insert the planned document_blobs rows. Runs only after a
    successful preflight, while source_version_id and every M3 lineage column
    still exist. No validation happens here — the plan is already safe."""
    for row in plan.blob_materializations:
        bind.execute(
            sa.text(
                "INSERT INTO document_blobs "
                "(id, version_id, company_id, storage_key, byte_size, data, created_at) "
                "VALUES (:id, :vid, :cid, :key, :size, :data, :now)"
            ),
            {
                "id": row.blob_id,
                "vid": row.version_id,
                "cid": row.company_id,
                "key": row.storage_key,
                "size": row.byte_size,
                "data": row.data,
                "now": datetime.utcnow(),
            },
        )


def _apply_m2_schema_downgrade() -> None:
    """PHASE 3: DDL down to exactly the committed M2 shape. Must run strictly
    after _preflight_downgrade and _materialize_successor_blobs — the first
    statement here is the first schema mutation of the whole downgrade."""
    with op.batch_alter_table("documents") as batch:
        batch.alter_column(
            "citation_prefix", existing_type=sa.String(12), type_=sa.String(8)
        )

    with op.batch_alter_table("ingestion_jobs") as batch:
        batch.drop_column("operation")

    with op.batch_alter_table("document_sections") as batch:
        batch.drop_column("classification_signature")
        batch.drop_column("matched_rules")
        batch.drop_column("anchor_provenance")

    op.drop_index("uq_document_versions_source_engine", table_name="document_versions")
    with op.batch_alter_table("document_versions") as batch:
        batch.drop_constraint("fk_document_versions_source_same_doc", type_="foreignkey")
        batch.drop_constraint("uq_document_versions_id_doc_company", type_="unique")
        batch.drop_column("classification_signature")
        batch.drop_column("engine_versions")
        batch.drop_column("finalization_engine")
        batch.drop_column("source_version_id")


def downgrade() -> None:
    bind = op.get_bind()
    plan = _preflight_downgrade(bind)
    _materialize_successor_blobs(bind, plan)
    _apply_m2_schema_downgrade()
