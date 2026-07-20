import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const BACKEND = "http://backend.test";
const ROTATED = { accessToken: "rotated-access", refreshToken: "rotated-refresh" };

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

function call(id = "report-1") {
  return GET(new Request(`http://localhost:3000/api/reports/${id}/claims`), {
    params: Promise.resolve({ id }),
  });
}

function rotatingFetch(finalStatus: number, payload: unknown = {}) {
  let reportCalls = 0;
  return vi.fn(async (url: string) => {
    if (url.endsWith("/api/auth/refresh")) {
      return Response.json(ROTATED);
    }
    reportCalls += 1;
    if (reportCalls === 1) return new Response(null, { status: 401 });
    return Response.json(payload, { status: finalStatus });
  });
}

function expectRotatedCookies(res: Awaited<ReturnType<typeof call>>) {
  expect(res.cookies.get("evidentia_at")).toBeDefined();
  expect(res.cookies.get("evidentia_rt")).toBeDefined();
}

beforeEach(() => {
  process.env.EVIDENTIA_BACKEND_URL = BACKEND;
  delete process.env.EVIDENTIA_BFF_SECRET;
  delete process.env.EVIDENTIA_TRUSTED_PROXY_COUNT;
  state.cookieStore = {};
});

afterEach(() => {
  delete process.env.EVIDENTIA_BACKEND_URL;
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("GET /api/reports/[id]/claims (BFF)", () => {
  it("returns 401 when the session has no access or refresh token", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const res = await call();

    expect(res.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns the successful backend claim-audit payload", async () => {
    state.cookieStore = { evidentia_at: "session-access" };
    const payload = {
      claimEngineEnabled: true,
      candidates: [{ candidateId: "claim-1", decision: { status: "accepted" } }],
    };
    vi.stubGlobal("fetch", vi.fn(async () => Response.json(payload)));

    const res = await call();

    expect(res.status).toBe(200);
    expect(await res.json()).toEqual(payload);
  });

  it("URL-encodes the report ID before calling the tenant claims endpoint", async () => {
    state.cookieStore = { evidentia_at: "session-access" };
    const fetchMock = vi.fn(async (_url: string) => Response.json({ candidates: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await call("tenant/report ?");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe(
      `${BACKEND}/api/reports/tenant%2Freport%20%3F/claims`,
    );
  });

  it("applies rotated session cookies on success", async () => {
    state.cookieStore = { evidentia_at: "expired-access", evidentia_rt: "refresh-session" };
    vi.stubGlobal("fetch", rotatingFetch(200, { candidates: [] }));

    const res = await call();

    expect(res.status).toBe(200);
    expectRotatedCookies(res);
  });

  it.each([404, 403])(
    "applies rotated session cookies when the retried backend returns %i",
    async (status) => {
      state.cookieStore = { evidentia_at: "expired-access", evidentia_rt: "refresh-session" };
      vi.stubGlobal("fetch", rotatingFetch(status));

      const res = await call();

      expect(res.status).toBe(status);
      expectRotatedCookies(res);
    },
  );

  it.each([404, 429, 503])("preserves backend status %i", async (status) => {
    state.cookieStore = { evidentia_at: "session-access" };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status })));

    const res = await call();

    expect(res.status).toBe(status);
    expect(await res.json()).toEqual({ error: "not found" });
  });

  it("preserves the existing enumeration-safe error when backend configuration is unavailable", async () => {
    delete process.env.EVIDENTIA_BACKEND_URL;
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const res = await call();

    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ error: "not found" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns the existing gateway error when the backend request fails", async () => {
    state.cookieStore = { evidentia_at: "session-access" };
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("ECONNREFUSED"); }));

    const res = await call();

    expect(res.status).toBe(502);
    expect(await res.json()).toEqual({ error: "backend unreachable" });
  });

  it("never substitutes demo or locally generated claim data for a backend miss", async () => {
    state.cookieStore = { evidentia_at: "session-access" };
    const fetchMock = vi.fn(async (_url: string) => new Response(null, { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);

    const res = await call("missing-report");

    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ error: "not found" });
    expect(fetchMock.mock.calls.every(([url]) => String(url).startsWith(BACKEND))).toBe(true);
    expect(fetchMock.mock.calls.every(([url]) => !String(url).includes("/api/demo/"))).toBe(true);
  });
});
