import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * GET /api/health — frontend liveness/readiness probe.
 *
 * Evidentia is an authenticated, multi-tenant app: the backend is REQUIRED. There
 * is no "deterministic fallback" mode for authenticated traffic — if the backend
 * is unreachable, product routes return 503 and nothing is generated or saved.
 * (This endpoint used to report `mode: "deterministic-fallback"`, describing an
 * architecture that no longer exists.)
 *
 * Returns 503 when the backend is required but unreachable, so an orchestrator
 * sees an unhealthy instance rather than a green one that cannot serve the product.
 */
export async function GET() {
  const backendUrl = process.env.EVIDENTIA_BACKEND_URL?.replace(/\/$/, "");

  const base = {
    service: "evidentia-frontend",
    backendConfigured: Boolean(backendUrl),
    time: new Date().toISOString(),
  };

  if (!backendUrl) {
    return NextResponse.json(
      {
        ...base,
        status: "unhealthy",
        backendReachable: false,
        mode: "unconfigured",
        detail: "EVIDENTIA_BACKEND_URL is not set: authentication is unavailable.",
      },
      { status: 503 },
    );
  }

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 4000);
    const res = await fetch(`${backendUrl}/health`, {
      cache: "no-store",
      signal: controller.signal,
    });
    clearTimeout(timeout);

    if (!res.ok) {
      return NextResponse.json(
        { ...base, status: "unhealthy", backendReachable: false, mode: "backend-unreachable" },
        { status: 503 },
      );
    }

    return NextResponse.json({
      ...base,
      status: "ok",
      backendReachable: true,
      mode: "backend",
    });
  } catch {
    return NextResponse.json(
      { ...base, status: "unhealthy", backendReachable: false, mode: "backend-unreachable" },
      { status: 503 },
    );
  }
}
