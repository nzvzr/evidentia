import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * GET /api/health — frontend liveness/readiness probe.
 *
 * Reports whether a Python backend is configured and, if so, whether it is
 * reachable (best-effort, short timeout). Never exposes secrets or backend
 * internals. The app is always usable via the deterministic TypeScript pipeline
 * even when the backend is absent, so this endpoint returns 200 regardless.
 */
export async function GET() {
  const backendUrl = process.env.EVIDENTIA_BACKEND_URL?.replace(/\/$/, "");
  const base = {
    status: "ok" as const,
    service: "evidentia-frontend",
    backendConfigured: Boolean(backendUrl),
    time: new Date().toISOString(),
  };

  if (!backendUrl) {
    return NextResponse.json({ ...base, backendReachable: false, mode: "deterministic-fallback" });
  }

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 4000);
    const res = await fetch(`${backendUrl}/health`, { cache: "no-store", signal: controller.signal });
    clearTimeout(timeout);
    return NextResponse.json({ ...base, backendReachable: res.ok, mode: res.ok ? "backend" : "deterministic-fallback" });
  } catch {
    return NextResponse.json({ ...base, backendReachable: false, mode: "deterministic-fallback" });
  }
}
