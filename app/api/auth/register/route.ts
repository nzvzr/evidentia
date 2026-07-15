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

/** POST /api/auth/register — create the account + organization, then sign in. */
export async function POST(request: Request) {
  if (!backendUrl()) {
    return NextResponse.json(
      { error: "Registration is unavailable: no backend configured." },
      { status: 503 },
    );
  }

  const parsed = await readJsonWithLimit(request);
  if (!parsed.ok) return parsed.response;
  const body = (parsed.body ?? {}) as Record<string, any>;

  try {
    const res = await backendFetch("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({
        email: body.email,
        password: body.password,
        name: body.name || undefined,
        company: body.company || undefined,
      }),
      headers: forwardedForHeader(request),
    });
    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      return NextResponse.json({ error: registrationError(res.status, data) }, { status: res.status });
    }

    const out = NextResponse.json({ user: data.user, companies: data.companies ?? [] }, { status: 201 });
    return setSessionCookies(out, {
      accessToken: data.accessToken,
      refreshToken: data.refreshToken,
    });
  } catch {
    return NextResponse.json({ error: "Registration service unreachable" }, { status: 502 });
  }
}

/** Surface validation problems (weak password, bad email) in a readable form. */
function registrationError(status: number, data: unknown): string {
  const detail = (data as { detail?: unknown })?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string };
    if (typeof first?.msg === "string") return first.msg.replace(/^Value error,\s*/, "");
  }
  return status === 409 ? "That email is already registered" : "Registration failed";
}
