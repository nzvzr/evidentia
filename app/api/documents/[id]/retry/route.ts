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
 * POST /api/documents/[id]/retry — re-enqueue a failed ingestion for the
 * document's latest version. The backend enforces tenancy, the failed-only
 * precondition (409 version_not_failed) and rate limits.
 */
export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!backendUrl()) {
    return NextResponse.json({ code: "backend_unavailable" }, { status: 503 });
  }
  try {
    const { res, rotated } = await authedBackendFetch(
      `/api/documents/${encodeURIComponent(id)}/retry`,
      { method: "POST" },
      undefined,
      forwardedForHeader(request),
    );
    if (res.status === 401) {
      return NextResponse.json({ code: "not_authenticated" }, { status: 401 });
    }
    return applySession(
      NextResponse.json(await res.json().catch(() => ({})), { status: res.status }),
      rotated,
    );
  } catch {
    return NextResponse.json({ code: "backend_unavailable" }, { status: 503 });
  }
}
