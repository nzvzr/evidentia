import { NextResponse } from "next/server";
import {
  applySession,
  authedBackendFetch,
  backendUrl,
  forwardedForHeader,
  readJsonWithLimit,
} from "@/lib/auth/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function proxy(request: Request, id: string, method: "GET" | "PUT") {
  if (!backendUrl()) return NextResponse.json({ error: "backend unavailable" }, { status: 503 });
  let body: string | undefined;
  if (method === "PUT") {
    const parsed = await readJsonWithLimit(request);
    if (!parsed.ok) return parsed.response;
    body = JSON.stringify(parsed.body);
  }
  try {
    const { res, rotated } = await authedBackendFetch(
      `/api/reports/${encodeURIComponent(id)}/feedback`,
      { method, ...(body ? { body } : {}) },
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

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  return proxy(request, (await params).id, "GET");
}

export async function PUT(request: Request, { params }: { params: Promise<{ id: string }> }) {
  return proxy(request, (await params).id, "PUT");
}
