"use client";

import type { PendingRun } from "./pendingRun";
import type { EvidentiaReport } from "./types";

const FETCH_ABORT_MS = 60_000;

export type GenerationResult =
  | { kind: "success"; report: EvidentiaReport }
  | { kind: "expired" }
  | { kind: "limited" }
  | { kind: "unavailable" }
  | { kind: "error" }
  | { kind: "cancelled" };

interface Flight {
  controller: AbortController;
  promise: Promise<GenerationResult>;
  subscribers: number;
  idleAbortTimer: ReturnType<typeof setTimeout> | null;
  abortWhenIdle: () => void;
  settled: boolean;
}

/** Only live requests are retained; settled attempts are removed immediately. */
const flights = new Map<string, Flight>();

/**
 * Minimum persistence/navigation contract — deliberately not a full
 * `EvidentiaReport` runtime validator. The page can only navigate to
 * `/reports/{id}`, so a 200 body without a non-empty string `id` can never
 * complete and must surface as a failure instead of waiting in finalizing.
 */
function hasPersistedReportId(body: unknown): body is EvidentiaReport {
  if (typeof body !== "object" || body === null) return false;
  const { id } = body as { id?: unknown };
  return typeof id === "string" && id.length > 0;
}

function flightKey(run: PendingRun): string {
  // The nonce is session-scoped and purged on every session change. Including
  // the actual input also prevents a tampered/reused nonce joining another run.
  return `${run.id}:${JSON.stringify(run.input)}`;
}

function beginFlight(key: string, run: PendingRun): Flight {
  const controller = new AbortController();
  let timedOut = false;
  let cancelledBecauseIdle = false;

  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, FETCH_ABORT_MS);

  const flight: Flight = {
    controller,
    subscribers: 0,
    idleAbortTimer: null,
    settled: false,
    abortWhenIdle: () => {
      if (flight.subscribers !== 0 || controller.signal.aborted) return;
      cancelledBecauseIdle = true;
      controller.abort();
    },
    promise: Promise.resolve({ kind: "cancelled" }),
  };

  flight.promise = (async (): Promise<GenerationResult> => {
    try {
      const res = await fetch("/api/generate-workflow", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(run.input),
        signal: controller.signal,
      });

      if (res.status === 401) return { kind: "expired" };
      if (res.status === 429) return { kind: "limited" };
      if (res.status === 503) return { kind: "unavailable" };
      if (!res.ok) return { kind: "error" };

      let body: unknown;
      try {
        body = await res.json();
      } catch (err) {
        // Body reads also reject on our own abort; rethrow those so the
        // outer catch classifies them. Anything else is a 200 whose body
        // never parsed — a malformed success, not a server outage.
        if (controller.signal.aborted) throw err;
        return { kind: "error" };
      }

      if (!hasPersistedReportId(body)) return { kind: "error" };
      return { kind: "success", report: body };
    } catch {
      if (cancelledBecauseIdle && !timedOut) return { kind: "cancelled" };
      return { kind: "unavailable" };
    } finally {
      clearTimeout(timeout);
      if (flight.idleAbortTimer) clearTimeout(flight.idleAbortTimer);
      flight.idleAbortTimer = null;
      flight.settled = true;
      if (flights.get(key) === flight) flights.delete(key);
    }
  })();

  return flight;
}

export function acquireGeneration(run: PendingRun): {
  promise: Promise<GenerationResult>;
  release: () => void;
} {
  const key = flightKey(run);
  let flight = flights.get(key);
  if (!flight) {
    flight = beginFlight(key, run);
    flights.set(key, flight);
  }

  if (flight.idleAbortTimer) {
    clearTimeout(flight.idleAbortTimer);
    flight.idleAbortTimer = null;
  }
  flight.subscribers += 1;

  let released = false;
  return {
    promise: flight.promise,
    release: () => {
      if (released) return;
      released = true;
      flight.subscribers = Math.max(0, flight.subscribers - 1);
      if (flight.subscribers === 0 && !flight.settled && !flight.controller.signal.aborted) {
        flight.idleAbortTimer = setTimeout(flight.abortWhenIdle, 0);
      }
    },
  };
}

/** Test isolation for module-scoped live requests. */
export function resetGenerationFlightsForTests(): void {
  for (const flight of flights.values()) {
    if (flight.idleAbortTimer) clearTimeout(flight.idleAbortTimer);
    flight.controller.abort();
  }
  flights.clear();
}
