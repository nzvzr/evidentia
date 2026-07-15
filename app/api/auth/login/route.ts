import { NextResponse } from "next/server";
import {
  backendFetch,
  backendUrl,
  forwardedForHeader,
  setSessionCookies,
  readJsonWithLimit,
} from "@/lib/auth/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * POST /api/auth/login — exchange credentials for an httpOnly session.
 *
 * The tokens returned by the backend are written to cookies and never sent to
 * the browser in the response body.
 */
export async function POST(request: Request) {
  if (!backendUrl()) {
    return NextResponse.json(
      { error: "Authentication is unavailable: no backend configured." },
      { status: 503 },
    );
  }

  const parsed = await readJsonWithLimit(request);
  if (!parsed.ok) return parsed.response;
  const body = (parsed.body ?? {}) as Record<string, any>;

  try {
    const res = await backendFetch("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email: body.email, password: body.password }),
      // Attribute the attempt to the real client so brute-force limits bite.
      headers: forwardedForHeader(request),
    });
    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      return NextResponse.json(
        { error: typeof data?.detail === "string" ? data.detail : "Invalid email or password" },
        { status: res.status },
      );
    }

    const out = NextResponse.json({ user: data.user, companies: data.companies ?? [] });
    return setSessionCookies(out, {
      accessToken: data.accessToken,
      refreshToken: data.refreshToken,
    });
  } catch {
    return NextResponse.json({ error: "Authentication service unreachable" }, { status: 502 });
  }
}
