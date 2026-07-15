"""Deterministic fixed-window rate limiting.

Design
------
* **Fixed window, not token bucket.** A request is counted into the window
  `floor(now / window_seconds)`. Given the same clock and the same keys, the
  decision is fully reproducible — which is what makes the limits testable
  (`FakeClock` below) rather than timing-dependent.

* **Storage is in-process memory.** `MemoryRateLimitStore` is a plain dict keyed
  by `(rule, identity, window_index)`, with expired windows swept lazily. This is
  correct for a single backend process and is the documented deployment shape
  (one FastAPI process behind the Next.js BFF). It is **per-process**: running N
  replicas multiplies every effective limit by N. `RateLimitStore` is a Protocol
  so a shared Redis store can be dropped in without touching call sites — see
  docs/ai/PROJECT_STATE.md for the deployment caveat.

* **No internal state is exposed.** A throttled response carries `Retry-After`
  and a stable error code, and nothing else: no limit, no remaining count, no
  window boundary. An attacker cannot map the policy by probing it.
"""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Protocol, Tuple

# The single machine-readable code every throttled response carries.
RATE_LIMITED_CODE = "rate_limited"


@dataclass(frozen=True)
class RateLimitRule:
    """`limit` requests per `window_seconds`, counted under `name`."""

    name: str
    limit: int
    window_seconds: int

    def window_index(self, now: float) -> int:
        return int(now // self.window_seconds)

    def window_reset(self, now: float) -> float:
        return (self.window_index(now) + 1) * self.window_seconds


class RateLimitExceeded(Exception):
    """Raised when a rule is exceeded. Carries only `retry_after` — the handler
    must not surface which rule tripped, or how close the caller was to it."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("rate limit exceeded")
        self.retry_after = max(1, retry_after)


class RateLimitStore(Protocol):
    """The seam a shared (Redis) store implements for multi-instance deployment.

    A Redis implementation is `INCR` + `EXPIRE` on the same key and needs no
    changes to any call site.
    """

    def hit(self, key: str, rule: RateLimitRule, now: float) -> int:  # pragma: no cover
        """Count one request against `key` and return the new window count."""
        ...

    def size(self) -> int:  # pragma: no cover
        ...

    def reset(self) -> None:  # pragma: no cover
        ...


DEFAULT_MAX_KEYS = 100_000


class MemoryRateLimitStore:
    """Thread-safe, **bounded**, amortized-O(1) in-process counters.

    Two properties matter, and the naive version had neither:

    * **No full-map sweep per request.** The old store scanned every key on every
      write, so cost grew linearly with the number of tracked identities — an
      attacker could make each request more expensive than the last. Expiry is now
      lazy (checked on read) plus an amortized incremental sweep of a small fixed
      slice, so a hit is O(1) amortized.

    * **Bounded cardinality.** Every unique email/token used to mint a permanent
      entry, so a flood of unique identities grew memory without limit — a trivial
      memory-exhaustion DoS. The map is now capped at `max_keys` with LRU eviction
      (an `OrderedDict` in insertion/refresh order). Eviction is safe for a
      *limiter*: the worst case of dropping a counter is that an attacker regains
      budget, which is strictly better than exhausting the host's memory. The
      per-IP budget is checked first (see `RateLimiter.check_all`), so the keys an
      attacker can cheaply create are exactly the ones that stop being created once
      their IP is already blocked.
    """

    _SWEEP_SLICE = 8  # entries examined per write; keeps the amortized cost flat

    def __init__(self, max_keys: int = DEFAULT_MAX_KEYS, clock: Callable[[], float] = time.time) -> None:
        self._buckets: "OrderedDict[Tuple[str, int], Tuple[int, float]]" = OrderedDict()
        self._max_keys = max_keys
        self._clock = clock
        self._lock = threading.Lock()

    def hit(self, key: str, rule: RateLimitRule, now: float) -> int:
        bucket = (key, rule.window_index(now))
        with self._lock:
            self._sweep_slice(now)

            entry = self._buckets.get(bucket)
            if entry is not None and entry[1] > now:
                count = entry[0] + 1
            else:
                count = 1  # new bucket, or a stale one from an expired window

            self._buckets[bucket] = (count, rule.window_reset(now))
            self._buckets.move_to_end(bucket)

            # Bounded: evict least-recently-touched buckets past the cap.
            while len(self._buckets) > self._max_keys:
                self._buckets.popitem(last=False)

            return count

    def _sweep_slice(self, now: float) -> None:
        """Examine a fixed number of the oldest entries and drop expired ones.

        Fixed slice ⇒ constant work per request, regardless of map size.
        """
        for _ in range(self._SWEEP_SLICE):
            if not self._buckets:
                return
            oldest_key = next(iter(self._buckets))
            _count, expires_at = self._buckets[oldest_key]
            if expires_at > now:
                return  # oldest is still live; nothing further to reclaim cheaply
            self._buckets.popitem(last=False)

    def size(self) -> int:
        with self._lock:
            return len(self._buckets)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


class RateLimiter:
    def __init__(
        self,
        store: RateLimitStore | None = None,
        clock: Callable[[], float] = time.time,
        enabled: bool = True,
    ) -> None:
        self._store = store or MemoryRateLimitStore()
        self._clock = clock
        self.enabled = enabled

    def check(self, rule: RateLimitRule, identity: str) -> None:
        """Count one request. Raises RateLimitExceeded when over the limit.

        `identity` is the thing being limited (an IP, a normalized email, a user
        id, a company id, a token digest). It is namespaced by rule name, so the
        same IP hitting login and refresh consumes two independent budgets.
        """
        if not self.enabled or rule.limit <= 0:
            return
        now = self._clock()
        count = self._store.hit(f"{rule.name}:{identity}", rule, now)
        if count > rule.limit:
            raise RateLimitExceeded(math.ceil(rule.window_reset(now) - now))

    def check_all(self, checks: list[tuple[RateLimitRule, str]]) -> None:
        """Enforce several rules, **primary (bounded-cardinality) rule first**.

        Ordering is a memory-safety property, not a style choice. `checks[0]` must
        be the rule whose identity space an attacker cannot inflate — the client
        IP. If that budget is already exhausted we raise *immediately*, without
        counting the remaining rules, so a flood of unique emails or tokens from a
        blocked IP cannot keep minting new buckets in the store.

        Rules after the first are still all counted (not short-circuited among
        themselves) so that tripping one cannot be used to dodge another.
        """
        if not checks:
            return

        primary_rule, primary_identity = checks[0]
        if primary_identity:
            # Raises before any attacker-controlled key is created.
            self.check(primary_rule, primary_identity)

        breach: RateLimitExceeded | None = None
        for rule, identity in checks[1:]:
            if not identity:
                continue
            try:
                self.check(rule, identity)
            except RateLimitExceeded as exc:
                # Keep the longest wait, and keep counting the remaining rules.
                if breach is None or exc.retry_after > breach.retry_after:
                    breach = exc
        if breach is not None:
            raise breach

    def size(self) -> int:
        return self._store.size()

    def reset(self) -> None:
        self._store.reset()


class FakeClock:
    """Deterministic clock for tests: time only moves when you move it."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@lru_cache
def get_rate_limiter() -> RateLimiter:
    from app.core.config import get_settings

    settings = get_settings()
    return RateLimiter(
        store=MemoryRateLimitStore(max_keys=settings.evidentia_rate_limit_max_keys),
        enabled=settings.evidentia_rate_limit_enabled,
    )
