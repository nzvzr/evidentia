import "server-only";

import { cookies } from "next/headers";
import { NextResponse } from "next/server";

/**
 * Server-side session for the Next.js BFF.
 *
 * The browser never holds a token. The access + refresh tokens live in
 * httpOnly, sameSite=lax cookies that only the Next server can read; it attaches
 * the access token as a Bearer header when it calls the Python backend. This
 * means an XSS bug cannot exfiltrate a session, and the backend never has to
 * accept credentials from a browser origin.
 */

export const ACCESS_COOKIE = "evidentia_at";
export const REFRESH_COOKIE = "evidentia_rt";

export interface SessionTokens {
  accessToken: string;
  refreshToken: string;
}

const isProd = process.env.NODE_ENV === "production";

function cookieOptions(maxAgeSeconds: number) {
  return {
    httpOnly: true,
    secure: isProd,
    sameSite: "lax" as const,
    path: "/",
    maxAge: maxAgeSeconds,
  };
}

/** Access-cookie lifetime is generous; the backend's `exp` is the real check. */
const ACCESS_MAX_AGE = 60 * 60;
const REFRESH_MAX_AGE = 60 * 60 * 24 * 30;

export function setSessionCookies(res: NextResponse, tokens: SessionTokens): NextResponse {
  res.cookies.set(ACCESS_COOKIE, tokens.accessToken, cookieOptions(ACCESS_MAX_AGE));
  res.cookies.set(REFRESH_COOKIE, tokens.refreshToken, cookieOptions(REFRESH_MAX_AGE));
  return res;
}

export function clearSessionCookies(res: NextResponse): NextResponse {
  res.cookies.set(ACCESS_COOKIE, "", { ...cookieOptions(0), maxAge: 0 });
  res.cookies.set(REFRESH_COOKIE, "", { ...cookieOptions(0), maxAge: 0 });
  return res;
}

/** Next 16: the cookie store is async. */
export async function readTokens(): Promise<{ accessToken?: string; refreshToken?: string }> {
  const jar = await cookies();
  return {
    accessToken: jar.get(ACCESS_COOKIE)?.value,
    refreshToken: jar.get(REFRESH_COOKIE)?.value,
  };
}

export function backendUrl(): string | undefined {
  return process.env.EVIDENTIA_BACKEND_URL?.replace(/\/$/, "");
}

const IPV4 = /^(\d{1,3}\.){3}\d{1,3}$/;
const IPV6 = /^[0-9a-fA-F:]+$/;

function isIp(value: string): boolean {
  if (IPV4.test(value)) return value.split(".").every((o) => Number(o) <= 255);
  return value.includes(":") && IPV6.test(value);
}

/**
 * The end user's IP, for the backend's per-IP rate limits.
 *
 * The backend only ever sees the BFF's address, so without this every user would
 * share one IP budget. We forward a *single* value (never the client's own
 * chain), so a caller cannot inject extra hops.
 *
 * `X-Real-IP` is **never** trusted. It was previously used as a fallback at zero
 * trusted hops, which meant any client could set it and freely rotate their own
 * rate-limit identity — completely defeating the per-IP budget. It is a
 * client-writable header like any other and there is no hop count that makes it
 * verifiable.
 *
 * At `EVIDENTIA_TRUSTED_PROXY_COUNT=0` we forward **nothing** and let the backend
 * fall back to the TCP peer. With N hops, only the Nth-from-the-right entry of
 * `X-Forwarded-For` (written by the innermost trusted proxy) is believed, and it
 * must parse as an IP.
 */
export function forwardedForHeader(request: Request): Record<string, string> {
  const hops = Number(process.env.EVIDENTIA_TRUSTED_PROXY_COUNT) || 0;
  if (hops <= 0) return {};

  const chain = (request.headers.get("x-forwarded-for") ?? "")
    .split(",")
    .map((p) => p.trim())
    .filter(Boolean);
  if (chain.length < hops) return {};

  const candidate = chain[chain.length - hops];
  return isIp(candidate) ? { "X-Forwarded-For": candidate } : {};
}

/**
 * Authenticates this BFF to the backend.
 *
 * A backend configured with `EVIDENTIA_TRUSTED_PROXY_COUNT>0` believes the
 * `X-Forwarded-For` it is sent. If that backend is also reachable directly from
 * the internet, anyone can bypass the BFF and forge the header. This shared
 * secret lets the backend refuse any request that did not come through the BFF,
 * so trusting the header stays sound even if the port is exposed.
 */
export function bffAuthHeader(): Record<string, string> {
  const secret = process.env.EVIDENTIA_BFF_SECRET;
  return secret ? { "X-Evidentia-BFF": secret } : {};
}

/** Hard cap on a request body the BFF will buffer. Mirrors the backend's cap. */
export const MAX_BFF_BODY_BYTES =
  Number(process.env.EVIDENTIA_MAX_BODY_BYTES) || 512 * 1024;

export type ParsedBody =
  | { ok: true; body: unknown }
  | { ok: false; response: NextResponse };

/**
 * Read and parse a JSON body, refusing anything oversized **before** buffering it.
 *
 * `await request.json()` buffers the entire body into memory with no limit, so a
 * multi-megabyte POST to any BFF route was an unauthenticated memory-pressure
 * vector in the Next process — the backend's 512 KiB cap never got a say, because
 * the BFF had already read the whole thing.
 *
 * We check the declared `Content-Length` first, then count bytes as they stream
 * (so a chunked body with no declared length cannot slip past).
 */
export async function readJsonWithLimit(
  request: Request,
  maxBytes: number = MAX_BFF_BODY_BYTES,
): Promise<ParsedBody> {
  const tooLarge = () => ({
    ok: false as const,
    response: NextResponse.json(
      { code: "payload_too_large", error: "Request body too large." },
      { status: 413 },
    ),
  });

  const declared = request.headers.get("content-length");
  if (declared && Number(declared) > maxBytes) return tooLarge();

  const reader = request.body?.getReader();
  if (!reader) return { ok: true, body: {} };

  const chunks: Uint8Array[] = [];
  let total = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    if (value) {
      total += value.byteLength;
      if (total > maxBytes) {
        await reader.cancel().catch(() => {});
        return tooLarge();
      }
      chunks.push(value);
    }
  }

  const merged = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.byteLength;
  }

  try {
    const text = new TextDecoder().decode(merged);
    return { ok: true, body: text ? JSON.parse(text) : {} };
  } catch {
    return {
      ok: false,
      response: NextResponse.json(
        { code: "invalid_request", error: "Malformed JSON body." },
        { status: 400 },
      ),
    };
  }
}

const TIMEOUT_MS = Number(process.env.EVIDENTIA_BACKEND_READ_TIMEOUT_MS) || 8000;

export async function backendFetch(
  path: string,
  init: RequestInit = {},
  timeoutMs = TIMEOUT_MS,
): Promise<Response> {
  const base = backendUrl();
  if (!base) throw new Error("EVIDENTIA_BACKEND_URL is not configured");

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(`${base}${path}`, {
      ...init,
      cache: "no-store",
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        // Proves to the backend that this request came through the BFF.
        ...bffAuthHeader(),
        ...(init.headers ?? {}),
      },
    });
  } finally {
    clearTimeout(timer);
  }
}

export interface AuthedResult {
  res: Response;
  /** Set when the access token was silently refreshed mid-request; the caller
   *  must write these back as cookies so the rotation is not lost. */
  rotated?: SessionTokens;
}

/**
 * In-flight refreshes, keyed by the refresh token being spent.
 *
 * Refresh tokens rotate, and re-presenting a spent one is (correctly) treated as
 * theft and burns the whole family. But a single page load fires several parallel
 * BFF requests, and if the access token has just expired they would *all* try to
 * refresh with the same parent token — the first succeeds, the rest present a
 * now-spent token, and the user is force-logged-out for simply loading a page.
 *
 * Single-flight collapses concurrent refreshes of the same parent onto one
 * backend call, so exactly one rotation happens and every waiter gets its result.
 * This is a legitimacy fix, not a weakening: a genuine *reuse* (a second use after
 * the first has completed and the promise has been evicted) still burns the family.
 */
const inFlightRefreshes = new Map<string, Promise<SessionTokens | null>>();

async function singleFlightRefresh(
  refreshToken: string,
  forwarded: Record<string, string>,
): Promise<SessionTokens | null> {
  const existing = inFlightRefreshes.get(refreshToken);
  if (existing) return existing;

  const attempt = (async (): Promise<SessionTokens | null> => {
    try {
      const refreshed = await backendFetch("/api/auth/refresh", {
        method: "POST",
        body: JSON.stringify({ refreshToken }),
        headers: forwarded,
      });
      if (!refreshed.ok) return null;
      const body = (await refreshed.json()) as SessionTokens;
      return { accessToken: body.accessToken, refreshToken: body.refreshToken };
    } catch {
      return null;
    } finally {
      // Evict on the next tick so callers that joined this flight all read it,
      // but a later, genuinely separate reuse is not served from the cache.
      setTimeout(() => inFlightRefreshes.delete(refreshToken), 0);
    }
  })();

  inFlightRefreshes.set(refreshToken, attempt);
  return attempt;
}

/**
 * Call the backend as the current user, transparently refreshing an expired
 * access token once.
 *
 * Because refresh tokens rotate, a refresh here produces a *new* refresh token.
 * The caller MUST persist `rotated` onto its response (see `applySession`), or
 * the next request will present a spent token and trip reuse detection.
 */
export async function authedBackendFetch(
  path: string,
  init: RequestInit = {},
  timeoutMs = TIMEOUT_MS,
  /** Client-attribution headers (X-Forwarded-For) — pass `forwardedForHeader(request)`
   *  so the backend's per-IP limits key on the real caller, not on this server. */
  forwarded: Record<string, string> = {},
): Promise<AuthedResult> {
  const { accessToken, refreshToken } = await readTokens();

  const call = (token?: string) =>
    backendFetch(
      path,
      {
        ...init,
        headers: {
          ...forwarded,
          ...(init.headers ?? {}),
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      },
      timeoutMs,
    );

  let res = accessToken ? await call(accessToken) : undefined;

  if ((!res || res.status === 401) && refreshToken) {
    const refreshed = await singleFlightRefresh(refreshToken, forwarded);
    if (refreshed) {
      const retry = await call(refreshed.accessToken);
      return { res: retry, rotated: refreshed };
    }
    // Refresh failed (expired / revoked / reuse-detected): the session is over.
    return {
      res: new Response(JSON.stringify({ error: "Not authenticated" }), { status: 401 }),
    };
  }

  if (!res) {
    return { res: new Response(JSON.stringify({ error: "Not authenticated" }), { status: 401 }) };
  }
  return { res };
}

/** Persist a mid-request token rotation onto the outgoing response. */
export function applySession(res: NextResponse, rotated?: SessionTokens): NextResponse {
  return rotated ? setSessionCookies(res, rotated) : res;
}
