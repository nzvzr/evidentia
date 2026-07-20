"use client";

/**
 * Browser-storage hygiene for the tenant-only product.
 *
 * Report and document content always lives in the backend. Browser storage is
 * limited to transient UI choices, and all Evidentia keys are cleared when the
 * authenticated session changes.
 */

const LEGACY_KEYS = [
  "evidentia:reports",
  "evidentia:uploaded-documents",
  "evidentia:user",
  "evidentia:workspace",
  "evidentia:workspace-selection",
  "evidentia:pending-run",
];

function remove(keys: string[]): void {
  for (const key of keys) {
    try {
      window.localStorage.removeItem(key);
    } catch {
      /* browser storage unavailable */
    }
  }
}

/** One-time migration for keys written by tenant/demo hybrid builds. */
export function purgeLegacyAuthenticatedData(): void {
  if (typeof window === "undefined") return;
  try {
    remove(LEGACY_KEYS);
    const obsolete: string[] = [];
    for (let index = 0; index < window.localStorage.length; index += 1) {
      const key = window.localStorage.key(index);
      if (key?.startsWith("evidentia:public-demo:")) obsolete.push(key);
    }
    remove(obsolete);
  } catch {
    /* browser storage unavailable */
  }
}

/** Clear all product state whenever the authenticated session changes. */
export function purgeAuthenticatedCache(): void {
  if (typeof window === "undefined") return;
  try {
    const keys: string[] = [];
    for (let index = 0; index < window.localStorage.length; index += 1) {
      const key = window.localStorage.key(index);
      if (key?.startsWith("evidentia:")) keys.push(key);
    }
    remove(keys);
  } catch {
    /* browser storage unavailable */
  }
}
