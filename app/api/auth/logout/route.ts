import { NextResponse } from "next/server";
import { backendFetch, backendUrl, clearSessionCookies, readTokens } from "@/lib/auth/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * POST /api/auth/logout — revoke the refresh token server-side and clear the
 * cookies. The cookies are cleared even if the backend call fails, so a user can
 * always end their local session.
 */
export async function POST() {
  const { refreshToken } = await readTokens();

  if (refreshToken && backendUrl()) {
    try {
      await backendFetch("/api/auth/logout", {
        method: "POST",
        body: JSON.stringify({ refreshToken }),
      });
    } catch {
      // Revocation is best-effort; the cookie clear below is not.
    }
  }

  return clearSessionCookies(NextResponse.json({ ok: true }));
}
