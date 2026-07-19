import { NextResponse } from "next/server";
import { applySession, authedBackendFetch, backendUrl, forwardedForHeader, readJsonWithLimit } from "@/lib/auth/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function PUT(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!backendUrl()) return NextResponse.json({ error: "backend unavailable" }, { status: 503 });
  const parsed = await readJsonWithLimit(request);
  if (!parsed.ok) return parsed.response;
  try {
    const { res, rotated } = await authedBackendFetch(
      `/api/reports/${encodeURIComponent(id)}/retrieval-misses`,
      { method: "PUT", body: JSON.stringify(parsed.body) }, undefined, forwardedForHeader(request),
    );
    return applySession(NextResponse.json(await res.json().catch(() => ({})), { status: res.status }), rotated);
  } catch {
    return NextResponse.json({ error: "backend unreachable" }, { status: 502 });
  }
}
