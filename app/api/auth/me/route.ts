import { NextResponse } from "next/server";
import {
  applySession,
  authedBackendFetch,
  backendUrl,
  clearSessionCookies,
  forwardedForHeader,
} from "@/lib/auth/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * GET /api/auth/me — the current session, or 401.
 *
 * This is the only way the browser learns who it is: the token itself is never
 * readable from JavaScript.
 */
export async function GET(request: Request) {
  if (!backendUrl()) {
    return NextResponse.json({ user: null, error: "no-backend" }, { status: 401 });
  }

  try {
    // /me can trigger a silent refresh, which is rate-limited per IP — forward
    // the real client so one busy BFF does not exhaust everyone's refresh budget.
    const { res, rotated } = await authedBackendFetch(
      "/api/auth/me",
      {},
      undefined,
      forwardedForHeader(request),
    );
    if (!res.ok) {
      // Session is gone — clear the stale cookies so the client stops retrying.
      return clearSessionCookies(NextResponse.json({ user: null }, { status: 401 }));
    }
    const data = await res.json();
    return applySession(
      NextResponse.json({ user: data.user, companies: data.companies ?? [] }),
      rotated,
    );
  } catch {
    return NextResponse.json({ user: null, error: "unreachable" }, { status: 502 });
  }
}
