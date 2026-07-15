import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  RATE_LIMIT_MAX_KEYS,
  rateLimit,
  rateLimitReset,
  rateLimitSize,
} from "./rateLimit";

/**
 * Adversarial tests for the public demo limiter.
 *
 * The demo route is anonymous, so its key space is entirely attacker-controlled:
 * these tests are the ones that matter.
 */

describe("demo rate limiter", () => {
  beforeEach(() => {
    rateLimitReset();
    vi.useRealTimers();
  });

  it("allows up to the limit, then blocks with a Retry-After", () => {
    for (let i = 0; i < 5; i++) {
      expect(rateLimit("ip-1", 5, 3600).allowed).toBe(true);
    }
    const blocked = rateLimit("ip-1", 5, 3600);
    expect(blocked.allowed).toBe(false);
    expect(blocked.retryAfter).toBeGreaterThan(0);
  });

  it("keeps separate budgets per identity", () => {
    expect(rateLimit("a", 1, 3600).allowed).toBe(true);
    expect(rateLimit("a", 1, 3600).allowed).toBe(false);
    expect(rateLimit("b", 1, 3600).allowed).toBe(true);
  });

  it("restores budget after the window expires", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));

    expect(rateLimit("k", 1, 60).allowed).toBe(true);
    expect(rateLimit("k", 1, 60).allowed).toBe(false);

    vi.advanceTimersByTime(61_000);
    expect(rateLimit("k", 1, 60).allowed).toBe(true);
  });

  it("BOUNDS cardinality under a flood of unique IPs", () => {
    // The DoS: every unique source address used to mint a permanent entry.
    for (let i = 0; i < 200_000; i++) {
      rateLimit(`demo:203.0.113.${i}`, 5, 3600);
    }
    expect(rateLimitSize()).toBeLessThanOrEqual(RATE_LIMIT_MAX_KEYS);
  });

  it("still enforces the limit for an active identity during a flood", () => {
    // Exhaust one identity, then spray far fewer unique keys than the cap so the
    // active bucket cannot have been evicted — it must still be blocked.
    for (let i = 0; i < 5; i++) rateLimit("victim", 5, 3600);
    expect(rateLimit("victim", 5, 3600).allowed).toBe(false);

    for (let i = 0; i < 100; i++) rateLimit(`noise-${i}`, 5, 3600);

    expect(rateLimit("victim", 5, 3600).allowed).toBe(false);
  });

  it("does not scan the whole map on every request", () => {
    // A regression guard on cost: with a large live map, a fixed number of
    // additional requests must not take time proportional to the map size.
    for (let i = 0; i < 20_000; i++) rateLimit(`fill-${i}`, 100, 3600);

    const start = performance.now();
    for (let i = 0; i < 1_000; i++) rateLimit("hot-key", 100_000, 3600);
    const elapsed = performance.now() - start;

    // 1000 hits against a warm map should be milliseconds, not seconds. The old
    // full-map sweep made this O(n) per request.
    expect(elapsed).toBeLessThan(500);
  });
});
