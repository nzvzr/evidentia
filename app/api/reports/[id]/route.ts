import { NextResponse } from "next/server";
import {
  applySession,
  authedBackendFetch,
  backendUrl,
  forwardedForHeader,
} from "@/lib/auth/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * GET /api/reports/[id] — one report from the caller's tenant.
 *
 * Tenant scoping is enforced backend-side: a report id belonging to another
 * organization returns 404 here, exactly as if it did not exist.
 */
export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!backendUrl()) return NextResponse.json({ error: "not found" }, { status: 404 });

  try {
    const { res, rotated } = await authedBackendFetch(
      `/api/reports/${encodeURIComponent(id)}`,
      {},
      undefined,
      forwardedForHeader(request),
    );
    if (!res.ok) {
      return NextResponse.json({ error: "not found" }, { status: res.status });
    }
    return applySession(NextResponse.json(await res.json()), rotated);
  } catch {
    return NextResponse.json({ error: "backend unreachable" }, { status: 502 });
  }
}

/** DELETE /api/reports/[id] — admin/owner only, enforced by the backend. */
export async function DELETE(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!backendUrl()) {
    return NextResponse.json({ error: "persistence unavailable" }, { status: 503 });
  }

  try {
    const { res, rotated } = await authedBackendFetch(
      `/api/reports/${encodeURIComponent(id)}`,
      { method: "DELETE" },
      undefined,
      forwardedForHeader(request),
    );
    return applySession(
      NextResponse.json(await res.json().catch(() => ({})), { status: res.status }),
      rotated,
    );
  } catch {
    return NextResponse.json({ error: "backend unreachable" }, { status: 502 });
  }
}
