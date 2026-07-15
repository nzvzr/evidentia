import { NextResponse } from "next/server";
import {
  backendFetch,
  backendUrl,
  clearSessionCookies,
  forwardedForHeader,
  readJsonWithLimit,
} from "@/lib/auth/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * POST /api/auth/password-reset
 *   { email }            → request a reset link (always 202, no enumeration)
 *   { token, password }  → set a new password
 *
 * A successful reset revokes every session backend-side, so the local cookies
 * are cleared too.
 */
export async function POST(request: Request) {
  if (!backendUrl()) {
    return NextResponse.json({ error: "Password reset unavailable" }, { status: 503 });
  }

  const parsed = await readJsonWithLimit(request);
  if (!parsed.ok) return parsed.response;
  const body = (parsed.body ?? {}) as Record<string, any>;
  const isConfirm = Boolean(body?.token);
  const path = isConfirm ? "/api/auth/password-reset/confirm" : "/api/auth/password-reset/request";
  const payload = isConfirm ? { token: body.token, password: body.password } : { email: body?.email };

  try {
    const res = await backendFetch(path, {
      method: "POST",
      body: JSON.stringify(payload),
      headers: forwardedForHeader(request),
    });
    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      return NextResponse.json({ error: resetError(data) }, { status: res.status });
    }

    const out = NextResponse.json({ ok: true }, { status: res.status });
    return isConfirm ? clearSessionCookies(out) : out;
  } catch {
    return NextResponse.json({ error: "Password reset service unreachable" }, { status: 502 });
  }
}

function resetError(data: unknown): string {
  const detail = (data as { detail?: unknown })?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string };
    if (typeof first?.msg === "string") return first.msg.replace(/^Value error,\s*/, "");
  }
  return "Password reset failed";
}
