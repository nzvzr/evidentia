"use client";

/**
 * Browser storage hygiene.
 *
 * Authenticated data (reports, uploaded document excerpts, the user record) used
 * to sit in *global* localStorage keys that were never cleared. On a shared or
 * multi-account browser that meant one tenant's report content stayed readable
 * after logout, and was still served to whoever signed in next — the client-side
 * mirror of a tenant-isolation bug.
 *
 * The rules now:
 *   - authenticated reports and documents are NEVER cached in localStorage; the
 *     backend is the only source of truth (see lib/reportsApi.ts);
 *   - the only thing allowed in localStorage is explicitly public demo data,
 *     under the `evidentia:public-demo:` prefix;
 *   - every legacy authenticated key is purged on login, logout, session change,
 *     and once at boot (migration for browsers that already hold them).
 */

/**
 * Keys that held actual tenant *content* (report bodies, document excerpts, the
 * user record). These are the leak, and they are removed unconditionally — at
 * boot as a migration, and on every session change.
 */
const LEGACY_DATA_KEYS = [
  "evidentia:reports",
  "evidentia:uploaded-documents",
  "evidentia:user",
];

/**
 * Transient UI state (which persona/market is selected, the run being started).
 * Not tenant content, but still session-scoped, so it is cleared when the session
 * changes — NOT at boot, because a page load mid-flow legitimately reads it.
 */
const SESSION_SCOPED_KEYS = [
  "evidentia:pending-run",
  "evidentia:workspace-selection",
];

/** The only namespace allowed to survive a session change. Public sample data. */
export const PUBLIC_DEMO_PREFIX = "evidentia:public-demo:";

function remove(keys: string[]): void {
  for (const key of keys) {
    try {
      window.localStorage.removeItem(key);
    } catch {
      /* ignore */
    }
  }
}

/**
 * Migration, run once at boot.
 *
 * Deletes tenant content that older builds cached globally. Deliberately narrow:
 * it must not touch in-flight UI state, because it runs on every page load —
 * including the run page, which reads the pending run it is about to execute.
 */
export function purgeLegacyAuthenticatedData(): void {
  if (typeof window === "undefined") return;
  remove(LEGACY_DATA_KEYS);
}

/**
 * Full purge, run on every session change (login, logout, session loss).
 *
 * Removes tenant content, session-scoped UI state, and anything else in our
 * namespace that is not explicitly public demo data — including keys written by
 * builds we no longer know about. This is what guarantees one account's residue
 * cannot bleed into the next account to use this browser.
 */
export function purgeAuthenticatedCache(): void {
  if (typeof window === "undefined") return;
  try {
    remove(LEGACY_DATA_KEYS);
    remove(SESSION_SCOPED_KEYS);

    const doomed: string[] = [];
    for (let i = 0; i < window.localStorage.length; i++) {
      const key = window.localStorage.key(i);
      if (!key) continue;
      if (key.startsWith("evidentia:") && !key.startsWith(PUBLIC_DEMO_PREFIX)) {
        doomed.push(key);
      }
    }
    remove(doomed);
  } catch {
    /* storage disabled / quota — nothing to do */
  }
}

/** Drop the public demo data too (used by "reset demo"). */
export function purgePublicDemoCache(): void {
  if (typeof window === "undefined") return;
  try {
    const doomed: string[] = [];
    for (let i = 0; i < window.localStorage.length; i++) {
      const key = window.localStorage.key(i);
      if (key?.startsWith(PUBLIC_DEMO_PREFIX)) doomed.push(key);
    }
    for (const key of doomed) window.localStorage.removeItem(key);
  } catch {
    /* ignore */
  }
}
