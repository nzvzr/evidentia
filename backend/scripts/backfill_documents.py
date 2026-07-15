#!/usr/bin/env python
"""Backfill existing content_text documents into the ingestion schema (M1).

Synthesizes a `document_versions` row (version 1) + original bytes in the blob
store + a queued ingestion job for every tenant document that still holds its
content only in the deprecated `documents.content_text` column. Idempotent:
documents that already have a version are skipped, so the command is always
safe to re-run. See `app/services/document_backfill.py` for the semantics and
the crash-safe write order.

Run the M1 Alembic migration first (`alembic upgrade head`).

Usage:
    python scripts/backfill_documents.py                 # all tenants
    python scripts/backfill_documents.py --company-id ID # one tenant
    python scripts/backfill_documents.py --dry-run       # report only
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal  # noqa: E402
from app.services.document_backfill import backfill_content_text_documents  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company-id", default=None, help="restrict to one tenant")
    parser.add_argument("--dry-run", action="store_true", help="report what would be done; write nothing")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = backfill_content_text_documents(
            db, company_id=args.company_id, dry_run=args.dry_run
        )
    finally:
        db.close()

    verb = "would backfill" if args.dry_run else "backfilled"
    print(
        f"{verb} {len(result.backfilled)} document(s); "
        f"skipped {len(result.skipped_has_version)} already-versioned, "
        f"{len(result.skipped_no_content)} without content "
        f"({result.total_examined} examined)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
