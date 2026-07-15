import { NextResponse } from "next/server";
import { backendFetch, backendUrl, forwardedForHeader, readJsonWithLimit } from "@/lib/auth/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * POST /api/auth/verify-email
 *   { token }  → confirm an address
 *   { email }  → request a fresh verification link
 */
export async function POST(request: Request) {
  if (!backendUrl()) {
    return NextResponse.json({ error: "Verification unavailable" }, { status: 503 });
  }

  const parsed = await readJsonWithLimit(request);
  if (!parsed.ok) return parsed.response;
  const body = (parsed.body ?? {}) as Record<string, any>;
  const path = body?.token ? "/api/auth/verify-email/confirm" : "/api/auth/verify-email/request";
  const payload = body?.token ? { token: body.token } : { email: body?.email };

  try {
    const res = await backendFetch(path, {
      method: "POST",
      body: JSON.stringify(payload),
      headers: forwardedForHeader(request),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = typeof data?.detail === "string" ? data.detail : "Verification failed";
      return NextResponse.json({ error: detail }, { status: res.status });
    }
    return NextResponse.json({ ok: true }, { status: res.status });
  } catch {
    return NextResponse.json({ error: "Verification service unreachable" }, { status: 502 });
  }
}
