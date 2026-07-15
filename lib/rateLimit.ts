import "server-only";

/**
 * Bounded fixed-window limiter for the Next.js edge of the app.
 *
 * The authoritative limits live in the Python backend (core/ratelimit.py). This
 * exists only for routes the backend never sees — i.e. the public demo pipeline,
 * which runs in this process and can spend LLM budget without ever calling the
 * backend.
 *
 * Two properties the naive `Map` version lacked, and why they matter here:
 *
 *  * **Bounded cardinality.** The demo route is *anonymous*, so its key space is
 *    attacker-controlled: every fresh IP minted a permanent entry that was only
 *    ever deleted by a sweep. A spray from many source addresses grew the map
 *    without limit — a memory-exhaustion DoS against the Next process. Entries are
 *    now capped (`MAX_KEYS`) with LRU eviction. Evicting a counter can hand back
 *    budget to an attacker; exhausting the host's memory is strictly worse.
 *
 *  * **No full-map scan per request.** The old `sweep()` walked every key on every
 *    new window, so each request got more expensive as the attack widened. Expiry
 *    is now lazy plus a fixed-size slice of the oldest entries, which is O(1)
 *    amortized regardless of how many identities are being tracked.
 *
 * Still per-process: N Next instances multiply the effective demo limit by N.
 * Global enforcement needs a shared store (Redis) or a trusted edge/gateway rule.
 */

interface Bucket {
  count: number;
  resetAt: number;
}

/** Insertion-ordered, so the first entries are the least recently touched. */
const buckets = new Map<string, Bucket>();

const MAX_KEYS = Number(process.env.EVIDENTIA_DEMO_RATE_MAX_KEYS) || 10_000;
const SWEEP_SLICE = 8;

export interface RateLimitResult {
  allowed: boolean;
  /** Seconds until the window resets. Only meaningful when `allowed` is false. */
  retryAfter: number;
}

/** Drop at most SWEEP_SLICE expired entries from the oldest end. Constant work. */
function sweepSlice(now: number): void {
  let examined = 0;
  for (const [key, bucket] of buckets) {
    if (examined >= SWEEP_SLICE) return;
    if (bucket.resetAt > now) return; // oldest is still live — nothing cheap to reclaim
    buckets.delete(key);
    examined += 1;
  }
}

/** Evict least-recently-touched entries until we are back under the cap. */
function evictToCap(): void {
  while (buckets.size > MAX_KEYS) {
    const oldest = buckets.keys().next();
    if (oldest.done) return;
    buckets.delete(oldest.value);
  }
}

export function rateLimit(key: string, limit: number, windowSeconds: number): RateLimitResult {
  const now = Date.now();
  sweepSlice(now);

  const existing = buckets.get(key);

  if (!existing || existing.resetAt <= now) {
    buckets.delete(key); // re-insert so Map order reflects recency
    buckets.set(key, { count: 1, resetAt: now + windowSeconds * 1000 });
    evictToCap();
    return { allowed: true, retryAfter: 0 };
  }

  existing.count += 1;
  // Refresh recency so an active identity is not evicted before an idle one.
  buckets.delete(key);
  buckets.set(key, existing);

  if (existing.count > limit) {
    return {
      allowed: false,
      retryAfter: Math.max(1, Math.ceil((existing.resetAt - now) / 1000)),
    };
  }
  return { allowed: true, retryAfter: 0 };
}

/** Test/introspection helpers. */
export function rateLimitSize(): number {
  return buckets.size;
}

export function rateLimitReset(): void {
  buckets.clear();
}

export const RATE_LIMIT_MAX_KEYS = MAX_KEYS;

/**
 * The caller's IP, trusting `X-Forwarded-For` only when we are told we sit behind
 * a proxy. Mirrors the backend's rule: with N trusted hops the only entry we can
 * vouch for is the Nth from the right; everything left of it may be client-injected.
 * `X-Real-IP` is never consulted.
 */
export function clientIp(request: Request): string {
  const hops = Number(process.env.EVIDENTIA_TRUSTED_PROXY_COUNT) || 0;
  if (hops <= 0) return "peer";

  const forwarded = request.headers.get("x-forwarded-for");
  if (!forwarded) return "peer";

  const parts = forwarded
    .split(",")
    .map((p) => p.trim())
    .filter(Boolean);
  if (parts.length < hops) return "peer";

  return parts[parts.length - hops] || "peer";
}
