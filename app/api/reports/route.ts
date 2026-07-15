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
 * GET /api/reports — the authenticated user's tenant reports.
 *
 * Unauthenticated callers get 401 (previously: the shared demo company's data).
 * The tenant is derived from the session on the backend; this route never sends
 * a company id.
 */
export async function GET(request: Request) {
  if (!backendUrl()) return NextResponse.json({ reports: [] });

  try {
    const { res, rotated } = await authedBackendFetch(
      "/api/reports",
      {},
      undefined,
      forwardedForHeader(request),
    );
    if (res.status === 401) {
      return NextResponse.json({ error: "Not authenticated", reports: [] }, { status: 401 });
    }
    if (!res.ok) return NextResponse.json({ reports: [] }, { status: res.status });
    return applySession(NextResponse.json(await res.json()), rotated);
  } catch {
    return NextResponse.json({ reports: [] });
  }
}

/** POST /api/reports — save a report into the caller's tenant. */
export async function POST(request: Request) {
  if (!backendUrl()) {
    return NextResponse.json({ error: "persistence unavailable" }, { status: 503 });
  }

  const parsed = await readJsonWithLimit(request);
  if (!parsed.ok) return parsed.response;
  const body = (parsed.body ?? {}) as Record<string, any>;

  try {
    // Only the report and persona are forwarded: ownership (company/user) is
    // taken from the session by the backend and cannot be set by the client.
    const { res, rotated } = await authedBackendFetch(
      "/api/reports",
      {
        method: "POST",
        body: JSON.stringify({ report: body?.report ?? body, personaId: body?.personaId }),
      },
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
