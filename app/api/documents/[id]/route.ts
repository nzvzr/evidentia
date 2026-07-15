import { NextResponse } from "next/server";
import {
  applySession,
  authedBackendFetch,
  backendUrl,
  forwardedForHeader,
} from "@/lib/auth/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** DELETE /api/documents/[id] — tenant-scoped; another tenant's id is a 404. */
export async function DELETE(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!backendUrl()) {
    return NextResponse.json({ code: "backend_unavailable" }, { status: 503 });
  }
  try {
    const { res, rotated } = await authedBackendFetch(
      `/api/documents/${encodeURIComponent(id)}`,
      { method: "DELETE" },
      undefined,
      forwardedForHeader(request),
    );
    return applySession(
      NextResponse.json(await res.json().catch(() => ({})), { status: res.status }),
      rotated,
    );
  } catch {
    return NextResponse.json({ code: "backend_unavailable" }, { status: 503 });
  }
}
