#!/usr/bin/env python
"""Bulk M3 finalization of existing pre-m3-transitional documents.

Discovers documents whose CURRENT version is a ready `pre-m3-transitional`
version and ensures each has exactly one immutable finalization successor +
one live finalize job (the worker does the processing). Idempotent and
resumable: re-running is a no-op for completed or live targets, and an
interrupted run picks up where it left off. Old versions and their sections
are never touched; a failure never moves `documents.current_version_id`.

Run the M3 Alembic migration first (`alembic upgrade head`).

Usage:
    python scripts/finalize_documents.py                     # all tenants
    python scripts/finalize_documents.py --company-id ID     # one tenant
    python scripts/finalize_documents.py --document-id ID    # one document
    python scripts/finalize_documents.py --limit 25          # bounded batch
    python scripts/finalize_documents.py --dry-run           # report only
    python scripts/finalize_documents.py --process           # also run the
                                                             # queued jobs
                                                             # inline

Logs contain ids and counts only — never document text.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import get_settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.document_finalize import run_finalization_backfill  # noqa: E402


MAX_LIMIT = 1000


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company-id", default=None, help="restrict to one tenant")
    parser.add_argument("--document-id", default=None, help="restrict to one document")
    parser.add_argument(
        "--limit", type=int, default=None, help=f"bounded batch size (1..{MAX_LIMIT})"
    )
    parser.add_argument("--dry-run", action="store_true", help="report what would be done; write nothing")
    parser.add_argument(
        "--process",
        action="store_true",
        help="process THIS run's finalize jobs inline (when no worker is "
        "running); never drains unrelated queued work",
    )
    args = parser.parse_args()

    if args.limit is not None and not 1 <= args.limit <= MAX_LIMIT:
        parser.error(f"--limit must be between 1 and {MAX_LIMIT}")

    if not get_settings().evidentia_tenant_corpus_enabled:
        print("EVIDENTIA_TENANT_CORPUS_ENABLED is false: finalization is disabled.")
        return 1

    db = SessionLocal()
    try:
        summary = run_finalization_backfill(
            db,
            company_id=args.company_id,
            document_id=args.document_id,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    finally:
        db.close()

    verb = "would finalize" if args.dry_run else "finalization targets"
    counts = summary.counts
    print(
        f"{verb}: examined={counts['examined']} enqueued={counts['enqueued']} "
        f"adopted={counts['adopted']} retried={counts['retried']} "
        f"alreadyFinal={counts['alreadyFinal']} skipped={counts['skippedIneligible']}"
    )

    if args.process and not args.dry_run:
        from app.ingestion.worker import IngestionWorker

        # Bounded inline processing: ONLY the successors this invocation
        # enqueued/adopted/retried — a backfill run must never drain other
        # tenants' (or a live worker's) unrelated queue jobs.
        scoped = summary.successor_version_ids
        processed = 0
        if scoped:
            worker = IngestionWorker(SessionLocal)
            while worker.process_one(version_ids=scoped):
                processed += 1
        print(f"processed {processed} job(s) inline (scoped to this run)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
