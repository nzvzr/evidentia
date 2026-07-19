// Focused tests for the authenticated DOCX export BFF route
// (`app/api/reports/[id]/export/docx/route.ts`).
//
// These drive the REAL route handler against the REAL session module: only the
// two true boundaries are faked — the httpOnly cookie store (`next/headers`) and
// the network (`fetch`). Nothing about `authedBackendFetch`, the single-flight
// refresh, or `applySession` is stubbed, so genuine session behavior (reading the
// session cookie, attaching the Bearer, rotating an expired token and persisting
// the rotation) is exercised, not bypassed.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const DOCX_CONTENT_TYPE =
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const DISPOSITION =
  `attachment; filename="evidentia-support-emea-abc.docx"; ` +
  `filename*=UTF-8''evidentia-support-emea-abc.docx`;
const BACKEND = "http://backend.test";
const TEST_MAX_BYTES = 32;
const ROTATED = { accessToken: "at-new", refreshToken: "rt-new" };

// The mocked httpOnly cookie jar the real `readTokens()` reads from.
const state = vi.hoisted(() => ({ cookieStore: {} as Record<string, string> }));

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => {
      const value = state.cookieStore[name];
      return value === undefined ? undefined : { name, value };
    },
  }),
}));

import { GET } from "./route";

/** Invoke the route as Next would, with a real Request and resolved params. */
function call(id: string, page?: string) {
  const suffix = page ? `?page=${page}` : "";
  const request = new Request(
    `http://localhost:3000/api/reports/${id}/export/docx${suffix}`,
  );
  return GET(request, { params: Promise.resolve({ id }) });
}

/** A tiny binary body with the ZIP/DOCX magic bytes, to prove byte fidelity. */
const BYTES = new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0, 1, 2, 253, 254, 255]);

function docxResponse(body: Uint8Array = BYTES, extraHeaders: Record<string, string> = {}) {
  return new Response(body, {
    status: 200,
    headers: {
      "content-type": DOCX_CONTENT_TYPE,
      "content-disposition": DISPOSITION,
      "x-evidentia-renderer": "docx-renderer",
      "x-evidentia-renderer-version": "docx-renderer-v1",
      "x-evidentia-content-hash": "hash-abc",
      "x-evidentia-semantic-digest": "digest-abc",
      ...extraHeaders,
    },
  });
}

function refreshThen(finalResponse: () => Response) {
  return vi.fn(async (url: string, init: { headers?: Record<string, string> }) => {
    if (String(url).endsWith("/api/auth/refresh")) {
      return new Response(JSON.stringify(ROTATED), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    if (init?.headers?.Authorization === "Bearer at-old") return new Response(null, { status: 401 });
    if (init?.headers?.Authorization === `Bearer ${ROTATED.accessToken}`) return finalResponse();
    return new Response(null, { status: 500 });
  });
}

function expectRotatedSession(res: Awaited<ReturnType<typeof call>>) {
  expect(res.cookies.get("evidentia_at")?.value).toBe(ROTATED.accessToken);
  expect(res.cookies.get("evidentia_rt")?.value).toBe(ROTATED.refreshToken);
  const setCookies =
    typeof res.headers.getSetCookie === "function"
      ? res.headers.getSetCookie()
      : [res.headers.get("set-cookie") ?? ""];
  expect(setCookies.join("\n").toLowerCase()).toContain("httponly");
}

function expectNoOrdinaryHeaderTokenLeak(res: Response) {
  for (const [name, value] of res.headers.entries()) {
    // Next's test runtime mirrors cookie serialization through both Set-Cookie
    // and its internal x-middleware-set-cookie transport. Those are the intended
    // httpOnly cookie channel, not an ordinary browser-readable response header.
    if (name.toLowerCase().includes("set-cookie")) continue;
    expect(value).not.toContain(ROTATED.accessToken);
    expect(value).not.toContain(ROTATED.refreshToken);
  }
}

function chunkedResponse(
  chunks: Uint8Array[],
  extraHeaders: Record<string, string> = {},
) {
  const state = { sent: 0, cancelled: false };
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (state.sent >= chunks.length) {
        controller.close();
        return;
      }
      controller.enqueue(chunks[state.sent]);
      state.sent += 1;
    },
    cancel() {
      state.cancelled = true;
    },
  });
  return {
    response: new Response(body, {
      status: 200,
      headers: { "content-type": DOCX_CONTENT_TYPE, ...extraHeaders },
    }),
    state,
  };
}

beforeEach(() => {
  process.env.EVIDENTIA_BACKEND_URL = BACKEND;
  process.env.EVIDENTIA_EXPORT_MAX_BYTES = String(TEST_MAX_BYTES);
  delete process.env.EVIDENTIA_BFF_SECRET;
  delete process.env.EVIDENTIA_TRUSTED_PROXY_COUNT;
  state.cookieStore = {};
});

afterEach(() => {
  delete process.env.EVIDENTIA_EXPORT_MAX_BYTES;
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("GET /api/reports/[id]/export/docx (BFF)", () => {
  it("proxies the backend as the authenticated user, preserving MIME, disposition and bytes", async () => {
    state.cookieStore = { evidentia_at: "access-abc" };
    const fetchMock = vi.fn(
      async (_url: string, _init: { headers: Record<string, string> }): Promise<Response> => docxResponse(),
    );
    vi.stubGlobal("fetch", fetchMock);

    const res = await call("report-42");

    expect(res.status).toBe(200);
    // Proxied to the exact backend export endpoint, as the user (Bearer from cookie).
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BACKEND}/api/reports/report-42/export/docx`);
    expect(init.headers.Authorization).toBe("Bearer access-abc");

    // MIME type + Content-Disposition are preserved exactly.
    expect(res.headers.get("content-type")).toBe(DOCX_CONTENT_TYPE);
    expect(res.headers.get("content-disposition")).toBe(DISPOSITION);
    expect(res.headers.get("cache-control")).toBe("no-store");
    expect(res.headers.get("x-evidentia-renderer")).toBe("docx-renderer");
    expect(res.headers.get("x-evidentia-renderer-version")).toBe("docx-renderer-v1");
    expect(res.headers.get("x-evidentia-content-hash")).toBe("hash-abc");
    expect(res.headers.get("x-evidentia-semantic-digest")).toBe("digest-abc");

    // Binary bytes are returned unchanged.
    const out = new Uint8Array(await res.arrayBuffer());
    expect(Array.from(out)).toEqual(Array.from(BYTES));

    // The demo pipeline is never touched by an authenticated export.
    for (const [u] of fetchMock.mock.calls) {
      expect(String(u)).not.toContain("/api/demo/generate-workflow");
    }
  });

  it("falls back to a safe default Content-Disposition when the backend omits it", async () => {
    state.cookieStore = { evidentia_at: "a" };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(BYTES, { status: 200, headers: { "content-type": DOCX_CONTENT_TYPE } })),
    );

    const res = await call("r1");
    expect(res.headers.get("content-disposition")).toBe('attachment; filename="evidentia-report.docx"');
  });

  it("refreshes an expired access token and persists the rotation as httpOnly cookies", async () => {
    state.cookieStore = { evidentia_at: "at-old", evidentia_rt: "rt-old" };
    const fetchMock = refreshThen(() => docxResponse());
    vi.stubGlobal("fetch", fetchMock);

    const res = await call("r1");

    expect(res.status).toBe(200);
    // The rotation actually went through the refresh endpoint...
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/api/auth/refresh"))).toBe(true);
    // ...and the new tokens are written back onto the response.
    expectRotatedSession(res);
  });

  it("never leaks a backend token to the browser on the happy path", async () => {
    state.cookieStore = {
      evidentia_at: "super-secret-access-token",
      evidentia_rt: "super-secret-refresh-token",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init: { headers?: Record<string, string> }) =>
        init?.headers?.Authorization === "Bearer super-secret-access-token"
          ? docxResponse()
          : new Response(null, { status: 500 }),
      ),
    );

    const res = await call("r1");
    expect(res.status).toBe(200);
    // No token echoed in any browser-readable surface.
    expect(res.headers.get("authorization")).toBeNull();
    const setCookie = res.headers.get("set-cookie") ?? "";
    expect(setCookie).not.toContain("super-secret-access-token");
    expect(setCookie).not.toContain("super-secret-refresh-token");
    const body = new TextDecoder().decode(await res.arrayBuffer());
    expect(body).not.toContain("super-secret-access-token");
    expect(body).not.toContain("super-secret-refresh-token");
  });

  it.each([
    [401, 401, "not_authenticated"],
    [404, 404, "not_found"],
    [413, 413, "too_large"],
    [500, 502, "export_failed"],
  ])(
    "surfaces backend %i as an honest typed failure (never a document)",
    async (backendStatus, expectedStatus, code) => {
      // Only an access token (no refresh token), so a backend 401 is surfaced,
      // not swallowed by a refresh attempt.
      state.cookieStore = { evidentia_at: "a" };
      vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: backendStatus })));

      const res = await call("r1");
      expect(res.status).toBe(expectedStatus);
      expect(res.headers.get("content-type")).toContain("application/json");
      expect(await res.json()).toMatchObject({ code });
      expect(res.cookies.get("evidentia_at")).toBeUndefined();
      expect(res.cookies.get("evidentia_rt")).toBeUndefined();
    },
  );

  it.each([
    [401, 401, "not_authenticated"],
    [404, 404, "not_found"],
    [413, 413, "too_large"],
    [500, 502, "export_failed"],
  ])(
    "persists a successful refresh when the retried backend returns %i",
    async (backendStatus, expectedStatus, code) => {
      state.cookieStore = { evidentia_at: "at-old", evidentia_rt: "rt-old" };
      vi.stubGlobal("fetch", refreshThen(() => new Response(null, { status: backendStatus })));

      const res = await call("r1");
      expect(res.status).toBe(expectedStatus);
      expectRotatedSession(res);
      expectNoOrdinaryHeaderTokenLeak(res);
      const body = await res.text();
      expect(body).toContain(code);
      expect(body).not.toContain(ROTATED.accessToken);
      expect(body).not.toContain(ROTATED.refreshToken);
    },
  );

  it("persists a successful refresh on 429 while preserving Retry-After", async () => {
    state.cookieStore = { evidentia_at: "at-old", evidentia_rt: "rt-old" };
    vi.stubGlobal(
      "fetch",
      refreshThen(() => new Response(null, { status: 429, headers: { "retry-after": "37" } })),
    );

    const res = await call("r1");
    expect(res.status).toBe(429);
    expect(res.headers.get("retry-after")).toBe("37");
    expectRotatedSession(res);
    expectNoOrdinaryHeaderTokenLeak(res);
    const body = await res.text();
    expect(body).not.toContain(ROTATED.accessToken);
    expect(body).not.toContain(ROTATED.refreshToken);
  });

  it("preserves a 429 with its Retry-After header", async () => {
    state.cookieStore = { evidentia_at: "a" };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(null, { status: 429, headers: { "retry-after": "37" } })),
    );

    const res = await call("r1");
    expect(res.status).toBe(429);
    expect(res.headers.get("retry-after")).toBe("37");
    expect(await res.json()).toMatchObject({ code: "rate_limited" });
  });

  it("returns the typed backend_unavailable response when the backend URL is unset", async () => {
    delete process.env.EVIDENTIA_BACKEND_URL;
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const res = await call("r1");
    expect(res.status).toBe(503);
    expect(await res.json()).toMatchObject({ code: "backend_unavailable" });
    // No document was produced and the backend was never even called.
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns the typed backend_unavailable response when the backend call throws", async () => {
    state.cookieStore = { evidentia_at: "a" };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("ECONNREFUSED");
      }),
    );

    const res = await call("r1");
    expect(res.status).toBe(503);
    expect(await res.json()).toMatchObject({ code: "backend_unavailable" });
    expect(res.cookies.get("evidentia_at")).toBeUndefined();
    expect(res.cookies.get("evidentia_rt")).toBeUndefined();
  });

  it("rejects an oversized Content-Length before accessing the body", async () => {
    state.cookieStore = { evidentia_at: "a" };
    const upstream = docxResponse(BYTES, { "content-length": String(TEST_MAX_BYTES + 1) });
    let bodyAccessed = false;
    Object.defineProperty(upstream, "body", {
      get() {
        bodyAccessed = true;
        throw new Error("body must not be read");
      },
    });
    vi.stubGlobal("fetch", vi.fn(async () => upstream));

    const res = await call("r1");
    expect(res.status).toBe(413);
    expect(await res.json()).toMatchObject({ code: "too_large" });
    expect(bodyAccessed).toBe(false);
  });

  it.each(["-1", "12.5", "not-a-number"])(
    "rejects malformed Content-Length %s before accessing the body",
    async (declared) => {
      state.cookieStore = { evidentia_at: "a" };
      const upstream = docxResponse(BYTES, { "content-length": declared });
      let bodyAccessed = false;
      Object.defineProperty(upstream, "body", {
        get() {
          bodyAccessed = true;
          throw new Error("body must not be read");
        },
      });
      vi.stubGlobal("fetch", vi.fn(async () => upstream));

      const res = await call("r1");
      expect(res.status).toBe(413);
      expect(bodyAccessed).toBe(false);
    },
  );

  it("cancels an oversized chunked body without consuming all chunks", async () => {
    state.cookieStore = { evidentia_at: "a" };
    const upstream = chunkedResponse(Array.from({ length: 10 }, () => new Uint8Array(8)));
    vi.stubGlobal("fetch", vi.fn(async () => upstream.response));

    const res = await call("r1");
    expect(res.status).toBe(413);
    expect(await res.json()).toMatchObject({ code: "too_large" });
    expect(upstream.state.cancelled).toBe(true);
    expect(upstream.state.sent).toBeLessThan(10);
  });

  it("accepts a chunked body exactly at the maximum with identical bytes", async () => {
    state.cookieStore = { evidentia_at: "a" };
    const expected = new Uint8Array(TEST_MAX_BYTES);
    for (let index = 0; index < expected.length; index += 1) expected[index] = index;
    const upstream = chunkedResponse([expected.slice(0, 11), expected.slice(11, 23), expected.slice(23)]);
    vi.stubGlobal("fetch", vi.fn(async () => upstream.response));

    const res = await call("r1");
    expect(res.status).toBe(200);
    expect(Array.from(new Uint8Array(await res.arrayBuffer()))).toEqual(Array.from(expected));
    expect(upstream.state.cancelled).toBe(false);
  });

  it("rejects actual bytes above the maximum even when Content-Length declares less", async () => {
    state.cookieStore = { evidentia_at: "a" };
    const upstream = chunkedResponse(
      [new Uint8Array(20), new Uint8Array(20), new Uint8Array(20)],
      { "content-length": "4" },
    );
    vi.stubGlobal("fetch", vi.fn(async () => upstream.response));

    const res = await call("r1");
    expect(res.status).toBe(413);
    expect(upstream.state.cancelled).toBe(true);
  });

  it("persists rotated cookies when a chunked response overflows", async () => {
    state.cookieStore = { evidentia_at: "at-old", evidentia_rt: "rt-old" };
    const upstream = chunkedResponse(Array.from({ length: 10 }, () => new Uint8Array(8)));
    vi.stubGlobal("fetch", refreshThen(() => upstream.response));

    const res = await call("r1");
    expect(res.status).toBe(413);
    expectRotatedSession(res);
    expectNoOrdinaryHeaderTokenLeak(res);
    expect(upstream.state.cancelled).toBe(true);
  });

  it("returns a typed failure instead of an empty DOCX when the upstream body is missing", async () => {
    state.cookieStore = { evidentia_at: "a" };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(null, { status: 200, headers: { "content-type": DOCX_CONTENT_TYPE } })),
    );

    const res = await call("r1");
    expect(res.status).toBe(502);
    expect(await res.json()).toMatchObject({ code: "export_failed" });
  });

  it("persists rotation when the authenticated response body fails while reading", async () => {
    state.cookieStore = { evidentia_at: "at-old", evidentia_rt: "rt-old" };
    const broken = new Response(
      new ReadableStream<Uint8Array>({
        pull(controller) {
          controller.error(new Error("upstream body failed"));
        },
      }),
      { status: 200, headers: { "content-type": DOCX_CONTENT_TYPE } },
    );
    vi.stubGlobal("fetch", refreshThen(() => broken));

    const res = await call("r1");
    expect(res.status).toBe(503);
    expectRotatedSession(res);
  });
});
