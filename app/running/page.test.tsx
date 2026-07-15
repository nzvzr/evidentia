// @vitest-environment jsdom

import { StrictMode } from "react";
import { renderToString } from "react-dom/server";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PENDING_RUN_KEY } from "@/lib/pendingRun";
import { resetGenerationFlightsForTests } from "@/lib/workflowGeneration";
import RunningPage from "./page";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/components/AppShell", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

const REPORT_ID = "78e741d7-46b9-4bd8-bc91-8968fd58630a";
const STAGES_COMPLETE_MS = 780 * 6;

function response(status: number, body: object = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function advance(ms: number): Promise<void> {
  await act(async () => {
    vi.advanceTimersByTime(ms);
    await Promise.resolve();
  });
}

function renderStrict() {
  return render(
    <StrictMode>
      <RunningPage />
    </StrictMode>,
  );
}

describe("RunningPage generation lifecycle", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  let consoleError: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.useFakeTimers();
    push.mockReset();
    window.localStorage.clear();
    window.localStorage.setItem(
      PENDING_RUN_KEY,
      JSON.stringify({
        id: "logical-run-1",
        input: {
          market: "EMEA",
          persona: "Solutions Architect",
          customPersona: "",
          selectedDocumentIds: ["platform-api-reference"],
        },
      }),
    );
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  afterEach(() => {
    cleanup();
    resetGenerationFlightsForTests();
    consoleError.mockRestore();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("shares one POST in Strict Mode, waits for animation, and navigates exactly once", async () => {
    fetchMock.mockResolvedValue(response(200, { id: REPORT_ID }));

    renderStrict();
    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/generate-workflow",
      expect.objectContaining({ method: "POST" }),
    );
    expect(push).not.toHaveBeenCalled();
    expect(screen.queryByText("Generation unavailable")).toBeNull();

    await advance(STAGES_COMPLETE_MS);

    expect(push).toHaveBeenCalledTimes(1);
    expect(push).toHaveBeenCalledWith(`/reports/${REPORT_ID}`);
    expect(consoleError.mock.calls.flat().join(" ")).not.toContain(
      "Cannot update a component",
    );

    await advance(22_000);
    expect(push).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/taking longer than usual/i)).toBeNull();
  });

  it("shows finalizing when animation wins and waits for the report response", async () => {
    const request = deferred<Response>();
    fetchMock.mockReturnValue(request.promise);

    renderStrict();
    await advance(STAGES_COMPLETE_MS);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/Agents complete .* compiling the grounded playbook/i)).toBeTruthy();
    expect(push).not.toHaveBeenCalled();

    request.resolve(response(200, { id: REPORT_ID }));
    await flush();

    expect(push).toHaveBeenCalledTimes(1);
    expect(push).toHaveBeenCalledWith(`/reports/${REPORT_ID}`);
  });

  it.each([
    [503, "Generation unavailable"],
    [429, "Generation limit reached"],
    [500, "Generation failed"],
  ])("maps HTTP %s to its honest failure state", async (status, headline) => {
    fetchMock.mockResolvedValue(response(status));

    renderStrict();
    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByText(headline)).toBeTruthy();
    expect(push).not.toHaveBeenCalled();
  });

  it("maps a real network rejection to unavailable", async () => {
    fetchMock.mockRejectedValue(new TypeError("network down"));

    renderStrict();
    await flush();

    expect(screen.getByText("Generation unavailable")).toBeTruthy();
    expect(push).not.toHaveBeenCalled();
  });

  it("maps the active request timeout to unavailable", async () => {
    fetchMock.mockImplementation((_: string, init: RequestInit) =>
      new Promise<Response>((_, reject) => {
        init.signal?.addEventListener("abort", () =>
          reject(new DOMException("Timed out", "AbortError")),
        );
      }),
    );

    renderStrict();
    await advance(60_000);
    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Generation unavailable")).toBeTruthy();
    expect(push).not.toHaveBeenCalled();
  });

  it("redirects a 401 to login once", async () => {
    fetchMock.mockResolvedValue(response(401));

    renderStrict();
    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(push).toHaveBeenCalledTimes(1);
    expect(push).toHaveBeenCalledWith("/login?next=/workspace");
  });

  it("ignores cleanup cancellation and never navigates after unmount", async () => {
    const request = deferred<Response>();
    fetchMock.mockReturnValue(request.promise);
    const view = renderStrict();

    view.unmount();
    await advance(0);
    request.resolve(response(200, { id: REPORT_ID }));
    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(push).not.toHaveBeenCalled();
    expect(consoleError.mock.calls.flat().join(" ")).not.toMatch(/unmounted|state update/i);
  });

  it.each([
    ["success", response(200, { id: "stale-report-id" })],
    ["failure", response(503)],
  ])("ignores a stale %s completion after a newer run succeeds", async (_, staleResponse) => {
    const staleRequest = deferred<Response>();
    const activeRequest = deferred<Response>();
    fetchMock
      .mockReturnValueOnce(staleRequest.promise)
      .mockReturnValueOnce(activeRequest.promise);

    const staleView = renderStrict();
    staleView.unmount();
    await advance(0);

    window.localStorage.setItem(
      PENDING_RUN_KEY,
      JSON.stringify({
        id: "logical-run-2",
        input: {
          market: "US",
          persona: "Support Agent",
          customPersona: "",
          selectedDocumentIds: ["incident-response-runbook"],
        },
      }),
    );
    renderStrict();
    activeRequest.resolve(response(200, { id: REPORT_ID }));
    staleRequest.resolve(staleResponse);
    await flush();
    await advance(STAGES_COMPLETE_MS);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("Generation unavailable")).toBeNull();
    expect(push).toHaveBeenCalledTimes(1);
    expect(push).toHaveBeenCalledWith(`/reports/${REPORT_ID}`);
  });

  it("aborts the shared request and clears its timers after a real unmount", async () => {
    fetchMock.mockImplementation((_: string, init: RequestInit) =>
      new Promise<Response>((_, reject) => {
        init.signal?.addEventListener("abort", () =>
          reject(new DOMException("Unmounted", "AbortError")),
        );
      }),
    );
    const view = renderStrict();

    view.unmount();
    await advance(0);
    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(push).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("starts exactly one fresh request on retry and can then succeed", async () => {
    fetchMock
      .mockResolvedValueOnce(response(503))
      .mockResolvedValueOnce(response(200, { id: REPORT_ID }));

    renderStrict();
    await flush();
    expect(screen.getByText("Generation unavailable")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("Generation unavailable")).toBeNull();

    await advance(STAGES_COMPLETE_MS);
    expect(push).toHaveBeenCalledTimes(1);
    expect(push).toHaveBeenCalledWith(`/reports/${REPORT_ID}`);
  });

  it.each([
    ["an empty object body", () => response(200, {})],
    [
      "an unparseable body",
      () =>
        new Response("not-json{", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    ],
    ["a missing id", () => response(200, { summary: "report without id" })],
    ["id=null", () => response(200, { id: null })],
    ["an empty id", () => response(200, { id: "" })],
    ["a non-string id", () => response(200, { id: 1234 })],
  ])("fails a 200 response with %s instead of finalizing forever", async (_, makeResponse) => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    fetchMock.mockResolvedValue(makeResponse());

    renderStrict();
    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Generation failed")).toBeTruthy();
    expect(screen.queryByText("Generation unavailable")).toBeNull();

    await advance(STAGES_COMPLETE_MS + 60_000);

    expect(screen.getByText("Generation failed")).toBeTruthy();
    expect(screen.queryByText(/compiling the grounded playbook/i)).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(push).not.toHaveBeenCalled();
    expect(setItem).not.toHaveBeenCalled();
    setItem.mockRestore();
  });

  it("never writes authenticated report content to localStorage", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    fetchMock.mockResolvedValue(response(200, { id: REPORT_ID, summary: "tenant secret" }));

    renderStrict();
    await flush();
    await advance(STAGES_COMPLETE_MS);

    const writes = setItem.mock.calls.map(([, value]) => value).join("\n");
    expect(writes).not.toContain(REPORT_ID);
    expect(writes).not.toContain("tenant secret");
    setItem.mockRestore();
  });

  describe("hydration-safe header labels", () => {
    const nonDefaultRun = {
      id: "logical-run-hydration",
      input: {
        market: "US",
        persona: "Support Agent",
        customPersona: "",
        selectedDocumentIds: ["incident-response-runbook"],
      },
    };

    it("renders default labels before mount even when a non-default run is stored", () => {
      window.localStorage.setItem(PENDING_RUN_KEY, JSON.stringify(nonDefaultRun));

      // renderToString runs no effects, so this is the pre-mount render the
      // server HTML must agree with (dynamic text is separated by comments).
      const html = renderToString(<RunningPage />).replace(/<!--.*?-->/g, "");

      expect(html).toContain("Solutions Architect · EMEA");
      expect(html).not.toContain("Support Agent");
      expect(html).not.toContain("· US");
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it("shows the stored labels after mount while generating from the stored input", async () => {
      window.localStorage.setItem(PENDING_RUN_KEY, JSON.stringify(nonDefaultRun));
      fetchMock.mockResolvedValue(response(200, { id: REPORT_ID }));

      const view = renderStrict();
      await flush();

      expect(view.container.textContent).toContain("Support Agent · US");
      expect(view.container.textContent).not.toContain("Solutions Architect · EMEA");

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const requestInit = fetchMock.mock.calls[0][1] as RequestInit;
      expect(JSON.parse(String(requestInit.body))).toMatchObject({
        market: "US",
        persona: "Support Agent",
      });

      await advance(STAGES_COMPLETE_MS);
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(push).toHaveBeenCalledTimes(1);
      expect(push).toHaveBeenCalledWith(`/reports/${REPORT_ID}`);
    });
  });
});
