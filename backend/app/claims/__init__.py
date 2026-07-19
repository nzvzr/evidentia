"""M5a declarative claim engine.

The package is deliberately domain-independent: all vocabulary, templates and
threshold selections come from versioned module JSON. Code exposes only a
closed set of deterministic matcher primitives and the evidence gate.
"""

from .engine import ClaimRunResult, run_claim_engine
from .patterns import ClaimPatternRelease, PatternValidationError, load_active_claim_patterns

__all__ = [
    "ClaimPatternRelease",
    "ClaimRunResult",
    "PatternValidationError",
    "load_active_claim_patterns",
    "run_claim_engine",
]
