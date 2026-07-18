#!/usr/bin/env python
"""Regenerate the golden expected outputs for the M3 identity surfaces.

The golden corpus (`tests/golden/`) pins the frozen anchor algorithm,
inheritance decisions, internal citation ids, deterministic classification
and final manifests. Tests compare exact equality and NEVER regenerate —
running this command is an explicit, reviewed act: every diff it produces is
an identity change that must be explained (a new algorithm/module version,
never silent tuning).

Usage:
    python scripts/regenerate_golden_fixtures.py            # all fixtures
    python scripts/regenerate_golden_fixtures.py base split # named fixtures
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.golden_harness import (  # noqa: E402
    FIXTURE_PLAN,
    compute_fixture,
    expected_path,
    write_expected,
)


def main() -> int:
    names = sys.argv[1:] or sorted(FIXTURE_PLAN)
    unknown = [n for n in names if n not in FIXTURE_PLAN]
    if unknown:
        print(f"unknown fixture(s): {', '.join(unknown)}")
        return 1
    for name in names:
        payload = compute_fixture(name)
        write_expected(name, payload)
        print(f"wrote {expected_path(name)} ({len(payload['sections'])} sections)")
    print(
        "\nReview the diff: every change to these files is a permanent identity"
        " change and must be explained in the commit."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
