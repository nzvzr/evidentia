// @vitest-environment jsdom

import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PENDING_RUN_KEY } from "@/lib/pendingRun";
import { resetGenerationFlightsForTests } from "@/lib/workflowGeneration";
import RunningPage from "./page";

const mocks = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
}));

vi.mock("@/components/AppShell", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

const REPORT_ID = "78e741d7-46b9-4bd8-bc91-8968fd58630a";

function response(status: number, body: object = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

function storeRun() {
  window.localStorage.setItem(
    PENDING_RUN_KEY,
    JSON.stringify({
      id: "tenant-run-1",
      input: {
        market: "EMEA",
        persona: "Solutions Architect",
        customPersona: "",
        selectedDocumentIds: ["tenant-doc-42"],
      },
    }),
  );
}

function renderPage() {
  return render(
    <StrictMode>
      <RunningPage />
    </StrictMode>,
  );
}

describe("RunningPage authenticated generation", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.useFakeTimers();
    window.localStorage.clear();
    mocks.push.mockReset();
    storeRun();
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    resetGenerationFlightsForTests();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("shares one authenticated POST in Strict Mode and opens the persisted report", async () => {
    fetchMock.mockResolvedValue(response(200, { id: REPORT_ID }));

    renderPage();
    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/generate-workflow",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/api/demo/"))).toBe(false);
    expect(mocks.push).toHaveBeenCalledWith(`/reports/${REPORT_ID}`);
  });

  it("uses an honest indeterminate state with no fictional agent completion UI", async () => {
    fetchMock.mockReturnValue(new Promise<Response>(() => undefined));

    renderPage();
    await flush();

    expect(screen.getByLabelText("Generation in progress")).toBeTruthy();
    expect(screen.getByText(/Progress details are unavailable until it completes/)).toBeTruthy();
    expect(screen.queryByText(/Document Reader|Risk Analyzer|Citation Binder|Queued|Complete/)).toBeNull();
  });

  it.each([
    [503, {}, "Generation unavailable"],
    [429, {}, "Generation limit reached"],
    [500, {}, "Generation failed"],
    [409, { code: "tenant_corpus_empty" }, "No Citation-ready documents selected"],
    [403, { code: "tenant_generation_disabled" }, "Tenant generation disabled"],
  ])("maps HTTP %s to %s", async (status, body, headline) => {
    fetchMock.mockResolvedValue(response(status, body));

    renderPage();
    await flush();

    expect(screen.getByText(headline)).toBeTruthy();
    expect(screen.getByText("No report was saved for this attempt.")).toBeTruthy();
  });

  it("surfaces the request timeout as unavailable", async () => {
    fetchMock.mockImplementation((_: string, init: RequestInit) =>
      new Promise<Response>((_, reject) => {
        init.signal?.addEventListener("abort", () => reject(new DOMException("Timed out", "AbortError")));
      }),
    );

    renderPage();
    await act(async () => {
      vi.advanceTimersByTime(60_000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText("Generation unavailable")).toBeTruthy();
  });

  it("retries with one fresh authenticated request", async () => {
    fetchMock
      .mockResolvedValueOnce(response(500))
      .mockResolvedValueOnce(response(200, { id: REPORT_ID }));

    renderPage();
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.every(([url]) => url === "/api/generate-workflow")).toBe(true);
    expect(mocks.push).toHaveBeenCalledWith(`/reports/${REPORT_ID}`);
  });

  it("ignores stale pending data from the hybrid frontend", async () => {
    window.localStorage.clear();
    window.localStorage.setItem(
      "evidentia:pending-run",
      JSON.stringify({
        market: "EMEA",
        persona: "Solutions Architect",
        selectedDocumentIds: ["security-compliance-whitepaper"],
      }),
    );

    renderPage();
    await flush();

    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByText("No Citation-ready documents selected")).toBeTruthy();
  });

  it("never stores authenticated report content in localStorage", async () => {
    fetchMock.mockResolvedValue(response(200, { id: REPORT_ID, summary: "private report text" }));

    renderPage();
    await flush();

    expect(Object.values(window.localStorage).join(" ")).not.toContain("private report text");
  });
});
