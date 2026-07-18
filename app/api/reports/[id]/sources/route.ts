import { NextResponse } from "next/server";
import {
  applySession,
  authedBackendFetch,
  backendUrl,
  forwardedForHeader,
} from "@/lib/auth/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Tenant-scoped audit metadata; it is deliberately separate from report JSON. */
export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!backendUrl()) return NextResponse.json({ error: "not found" }, { status: 404 });
  try {
    const { res, rotated } = await authedBackendFetch(
      `/api/reports/${encodeURIComponent(id)}/sources`,
      {},
      undefined,
      forwardedForHeader(request),
    );
    if (!res.ok) return NextResponse.json({ error: "not found" }, { status: res.status });
    return applySession(NextResponse.json(await res.json()), rotated);
  } catch {
    return NextResponse.json({ error: "backend unreachable" }, { status: 502 });
  }
}

