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

/**
 * Documents for the authenticated tenant. The backend scopes every row to the
 * caller's company; nothing is cached in the browser.
 */
export async function GET(request: Request) {
  if (!backendUrl()) {
    return NextResponse.json({ code: "backend_unavailable", documents: [] }, { status: 503 });
  }
  try {
    const { res, rotated } = await authedBackendFetch(
      "/api/documents",
      {},
      undefined,
      forwardedForHeader(request),
    );
    if (res.status === 401) {
      return NextResponse.json({ code: "not_authenticated", documents: [] }, { status: 401 });
    }
    if (!res.ok) return NextResponse.json({ documents: [] }, { status: res.status });
    return applySession(NextResponse.json(await res.json()), rotated);
  } catch {
    return NextResponse.json({ code: "backend_unavailable", documents: [] }, { status: 503 });
  }
}

/** Upload a document into the caller's tenant. */
export async function POST(request: Request) {
  if (!backendUrl()) {
    return NextResponse.json({ code: "backend_unavailable" }, { status: 503 });
  }

  const parsed = await readJsonWithLimit(request);
  if (!parsed.ok) return parsed.response;

  try {
    const { res, rotated } = await authedBackendFetch(
      "/api/documents",
      { method: "POST", body: JSON.stringify(parsed.body) },
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
