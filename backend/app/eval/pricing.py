"""Rough LLM cost estimation (USD per 1M tokens).

These are approximate list prices for estimation only; adjust as needed.
"""

from __future__ import annotations

from typing import Optional

# (input_per_1m, output_per_1m) in USD
_PRICING = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
}
_DEFAULT = (0.15, 0.60)


def estimate_cost(model: Optional[str], input_tokens: int, output_tokens: int) -> float:
    if not model:
        return 0.0
    in_rate, out_rate = _PRICING.get(model, _DEFAULT)
    cost = (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate
    return round(cost, 6)
