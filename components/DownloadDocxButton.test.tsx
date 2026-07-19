// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DownloadDocxButton from "./DownloadDocxButton";

function docxResponse(filename: string): Response {
  return new Response(new Blob([new Uint8Array([1, 2, 3])]), {
    status: 200,
    headers: {
      "content-type":
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "content-disposition": `attachment; filename="${filename}"; filename*=UTF-8''${filename}`,
    },
  });
}

let clickedDownload: string | null = null;

beforeEach(() => {
  clickedDownload = null;
  // jsdom implements neither of these; the component only needs them to exist.
  URL.createObjectURL = vi.fn(() => "blob:mock-url");
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    clickedDownload = this.download;
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("DownloadDocxButton", () => {
  it("shows the download control", () => {
    vi.stubGlobal("fetch", vi.fn());
    render(<DownloadDocxButton reportId="report-1" />);
    expect(screen.getByRole("button", { name: /download docx/i })).toBeTruthy();
  });

  it("calls the correct BFF export endpoint and saves the returned blob", async () => {
    const fetchMock = vi.fn().mockResolvedValue(docxResponse("evidentia-support-emea-abc.docx"));
    vi.stubGlobal("fetch", fetchMock);

    render(<DownloadDocxButton reportId="report-42" />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /download docx/i }));
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/reports/report-42/export/docx");
    // Filename comes from the server's Content-Disposition, honored on the anchor.
    await waitFor(() => expect(clickedDownload).toBe("evidentia-support-emea-abc.docx"));
    expect(URL.createObjectURL).toHaveBeenCalled();
    expect(URL.revokeObjectURL).toHaveBeenCalled();
  });

  it("prevents duplicate requests while one is in flight", async () => {
    let resolveFetch: (r: Response) => void = () => {};
    const pending = new Promise<Response>((resolve) => {
      resolveFetch = resolve;
    });
    const fetchMock = vi.fn().mockReturnValue(pending);
    vi.stubGlobal("fetch", fetchMock);

    render(<DownloadDocxButton reportId="report-1" />);
    const button = screen.getByRole("button", { name: /download docx|preparing/i });

    await act(async () => {
      fireEvent.click(button);
      fireEvent.click(button); // second click while the first is pending
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveFetch(docxResponse("evidentia-report.docx"));
      await pending;
    });
  });

  it("surfaces a clear error on failure and never falls back", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ code: "not_found" }), {
        status: 404,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<DownloadDocxButton reportId="missing" />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /download docx/i }));
    });

    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.getByRole("alert").textContent).toMatch(/no longer available/i);
    // No object URL was created — nothing was downloaded.
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    // The control invites a retry rather than silently succeeding.
    expect(screen.getByRole("button", { name: /retry download/i })).toBeTruthy();
  });
});
