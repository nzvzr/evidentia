import { NextResponse } from "next/server";
import {
  applySession,
  authedBackendFetch,
  backendUrl,
  forwardedForHeader,
  type SessionTokens,
} from "@/lib/auth/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Tenant-scoped M5a audit; deliberately separate from report compatibility JSON. */
export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!backendUrl()) return NextResponse.json({ error: "not found" }, { status: 404 });
  let rotated: SessionTokens | undefined;
  try {
    const result = await authedBackendFetch(
      `/api/reports/${encodeURIComponent(id)}/claims`,
      {},
      undefined,
      forwardedForHeader(request),
    );
    const { res } = result;
    rotated = result.rotated;
    if (!res.ok) {
      return applySession(
        NextResponse.json({ error: "not found" }, { status: res.status }),
        rotated,
      );
    }
    return applySession(NextResponse.json(await res.json()), rotated);
  } catch {
    return applySession(
      NextResponse.json({ error: "backend unreachable" }, { status: 502 }),
      rotated,
    );
  }
}
