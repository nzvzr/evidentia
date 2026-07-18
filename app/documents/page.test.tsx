// @vitest-environment jsdom

import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POLL_INTERVAL_MS } from "@/lib/tenantDocuments";
import DocumentsPage from "./page";

vi.mock("@/components/AppShell", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

interface MockDoc {
  id: string;
  companyId?: string;
  title: string;
  type?: string;
  category?: string;
  createdAt?: string;
  metadata?: Record<string, unknown> | null;
  ingestion?: Record<string, unknown> | null;
}

const CORPUS_CONFIG = {
  enabled: true,
  acceptedExtensions: [".md", ".txt"],
  maxFileBytes: 2 * 1024 * 1024,
};

function ingestion(overrides: Record<string, unknown> = {}) {
  return {
    status: "processing",
    stage: "pending",
    stageKind: "ingest",
    identity: null,
    finalized: false,
    versionNo: 1,
    filename: "policy.md",
    detectedFormat: "markdown",
    byteSize: 1536,
    sectionCount: null,
    errorCode: null,
    errorMessage: null,
    updatedAt: "2026-07-16T10:00:00",
    sourceType: "upload",
    ...overrides,
  };
}

function tenantDoc(overrides: Partial<MockDoc> = {}): MockDoc {
  return {
    id: "doc-1",
    companyId: "co-1",
    title: "policy",
    type: "MD",
    category: "Uploaded",
    createdAt: "2026-07-16T10:00:00",
    metadata: null,
    ingestion: ingestion(),
    ...overrides,
  };
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

function mdFile(name = "notes.md", content = "# Hi\n\nBody"): File {
  const file = new File([content], name, { type: "text/markdown" });
  if (typeof file.text !== "function") {
    // jsdom's File lacks the Blob text() method
    Object.defineProperty(file, "text", { value: async () => content });
  }
  return file;
}

function mainFileInput(container: HTMLElement): HTMLInputElement {
  const input = container.querySelector('input[type="file"]');
  if (!input) throw new Error("file input not found");
  return input as HTMLInputElement;
}

function renderStrict() {
  return render(
    <StrictMode>
      <DocumentsPage />
    </StrictMode>,
  );
}

describe("DocumentsPage", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  /** queue of list responses; the last entry repeats for later polls */
  let listResponses: Array<{ documents: MockDoc[]; tenantCorpus?: typeof CORPUS_CONFIG }>;

  const listBody = () =>
    listResponses.length > 1 ? listResponses.shift()! : listResponses[0];

  beforeEach(() => {
    listResponses = [{ documents: [] }];
    fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (typeof url === "string" && url === "/api/documents" && (!init || !init.method)) {
        return json(200, listBody());
      }
      throw new Error(`unmocked fetch: ${init?.method ?? "GET"} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  // ------------------------------------------------------------------ //
  // feature disabled (default)
  // ------------------------------------------------------------------ //

  it("renders the pre-M2 demo experience when the corpus is disabled", async () => {
    renderStrict();
    await flush();

    expect(screen.getByText("DEMO CORPUS")).toBeTruthy();
    expect(screen.getByText(/DEMO MODE/)).toBeTruthy();
    expect(screen.getByText(/Processed locally — never uploaded/)).toBeTruthy();
    expect(screen.queryByText("YOUR DOCUMENTS")).toBeNull();
    expect(screen.queryByText(/SAMPLE CORPUS/)).toBeNull();
  });

  it("uses the legacy JSON path when disabled", async () => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/documents" && (!init || !init.method)) return json(200, { documents: [] });
      if (url === "/api/documents" && init?.method === "POST") {
        expect(init.headers).toMatchObject({ "Content-Type": "application/json" });
        const body = JSON.parse(String(init.body));
        expect(body.contentText).toContain("# Hi");
        return json(201, { id: "new", title: "notes" });
      }
      throw new Error(`unmocked: ${init?.method} ${url}`);
    });

    const { container } = renderStrict();
    await flush();
    fireEvent.change(mainFileInput(container), { target: { files: [mdFile()] } });
    await flush();

    const posts = fetchMock.mock.calls.filter(([, init]) => (init as RequestInit)?.method === "POST");
    expect(posts).toHaveLength(1);
    expect(posts[0][0]).toBe("/api/documents");
  });

  // ------------------------------------------------------------------ //
  // feature enabled
  // ------------------------------------------------------------------ //

  it("shows the upload form with format and size guidance when enabled", async () => {
    listResponses = [{ documents: [], tenantCorpus: CORPUS_CONFIG }];
    renderStrict();
    await flush();

    expect(screen.getByText("Upload a .md or .txt document")).toBeTruthy();
    expect(screen.getByText(/up to 2\.0 MB, one file per upload/)).toBeTruthy();
    expect(screen.getByText("SAMPLE CORPUS (DEMO)")).toBeTruthy();
    expect(
      screen.getByText(/Report generation uses this sample corpus/),
    ).toBeTruthy();
    // sample rows are labelled Sample, never as uploaded tenant content
    expect(screen.getAllByText("Sample").length).toBeGreaterThan(0);
  });

  it("rejects an unsupported selection client-side with guidance", async () => {
    listResponses = [{ documents: [], tenantCorpus: CORPUS_CONFIG }];
    const { container } = renderStrict();
    await flush();

    const bad = new File(["%PDF"], "report.pdf", { type: "application/pdf" });
    fireEvent.change(mainFileInput(container), { target: { files: [bad] } });
    await flush();

    expect(screen.getByText("Only .md and .txt files are supported.")).toBeTruthy();
    const uploads = fetchMock.mock.calls.filter(([url]) => String(url).includes("/upload"));
    expect(uploads).toHaveLength(0);
  });

  it("uploads one markdown file as multipart and reports acceptance", async () => {
    listResponses = [{ documents: [], tenantCorpus: CORPUS_CONFIG }];
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/documents" && (!init || !init.method)) {
        return json(200, { documents: [tenantDoc()], tenantCorpus: CORPUS_CONFIG });
      }
      if (url === "/api/documents/upload" && init?.method === "POST") {
        expect(init.body).toBeInstanceOf(FormData);
        const file = (init.body as FormData).get("file");
        expect((file as File).name).toBe("notes.md");
        return json(202, {
          documentId: "doc-1", versionId: "v-1", versionNo: 1,
          duplicate: false, noop: false, retried: false,
        });
      }
      throw new Error(`unmocked: ${init?.method} ${url}`);
    });

    const { container } = renderStrict();
    await flush();
    fireEvent.change(mainFileInput(container), { target: { files: [mdFile()] } });
    await flush();

    expect(screen.getByText("Upload accepted — processing has started.")).toBeTruthy();
    const uploads = fetchMock.mock.calls.filter(([url]) => url === "/api/documents/upload");
    expect(uploads).toHaveLength(1); // Strict Mode does not duplicate the upload
  });

  it("accepts a valid TXT selection", async () => {
    listResponses = [{ documents: [], tenantCorpus: CORPUS_CONFIG }];
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/documents" && (!init || !init.method)) {
        return json(200, { documents: [], tenantCorpus: CORPUS_CONFIG });
      }
      if (url === "/api/documents/upload" && init?.method === "POST") {
        return json(202, { documentId: "d", versionId: "v", versionNo: 1 });
      }
      throw new Error("unmocked");
    });
    const { container } = renderStrict();
    await flush();
    fireEvent.change(mainFileInput(container), {
      target: { files: [new File(["plain"], "a.txt", { type: "text/plain" })] },
    });
    await flush();
    expect(screen.getByText("Upload accepted — processing has started.")).toBeTruthy();
  });

  it("reports an explicit duplicate", async () => {
    listResponses = [{ documents: [tenantDoc()], tenantCorpus: CORPUS_CONFIG }];
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/documents" && (!init || !init.method)) return json(200, listBody());
      if (url === "/api/documents/upload" && init?.method === "POST") {
        return json(200, { documentId: "doc-1", versionId: "v-1", duplicate: true });
      }
      throw new Error("unmocked");
    });
    const { container } = renderStrict();
    await flush();
    fireEvent.change(mainFileInput(container), { target: { files: [mdFile()] } });
    await flush();
    expect(screen.getByText("Already in your library — nothing new was stored.")).toBeTruthy();
  });

  it("renders a typed backend failure", async () => {
    listResponses = [{ documents: [], tenantCorpus: CORPUS_CONFIG }];
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/documents" && (!init || !init.method)) {
        return json(200, { documents: [], tenantCorpus: CORPUS_CONFIG });
      }
      if (url === "/api/documents/upload" && init?.method === "POST") {
        return json(413, { code: "file_too_large" });
      }
      throw new Error("unmocked");
    });
    const { container } = renderStrict();
    await flush();
    fireEvent.change(mainFileInput(container), { target: { files: [mdFile()] } });
    await flush();
    expect(screen.getByText("That file is too large.")).toBeTruthy();
  });

  // ------------------------------------------------------------------ //
  // real metadata rendering (no fabrication)
  // ------------------------------------------------------------------ //

  it("renders tenant rows from real backend metadata only", async () => {
    listResponses = [
      {
        documents: [
          tenantDoc({
            ingestion: ingestion({
              stage: "ready", status: "ready", sectionCount: 7, identity: "transitional",
            }),
          }),
        ],
        tenantCorpus: CORPUS_CONFIG,
      },
    ];
    renderStrict();
    await flush();

    expect(screen.getByText("YOUR DOCUMENTS")).toBeTruthy();
    expect(screen.getByText("Awaiting finalization")).toBeTruthy();
    const row = screen.getByText("policy").closest("div") as HTMLElement;
    const meta = within(row.parentElement as HTMLElement);
    expect(meta.getByText(/policy\.md · 1\.5 KB · uploaded Jul 16, 2026 · v1 · 7 sections/)).toBeTruthy();
    // no fabricated page counts / risk counts / percentages
    expect(screen.queryByText(/\d+ pages · updated .* · v1/)).toBeNull();
    expect(within(row.parentElement as HTMLElement).queryByText(/%/)).toBeNull();
  });

  it("shows the pre-finalization meaning of a parsed document honestly", async () => {
    listResponses = [
      {
        documents: [
          tenantDoc({
            ingestion: ingestion({
              stage: "ready", status: "ready", sectionCount: 2, identity: "transitional",
            }),
          }),
        ],
        tenantCorpus: CORPUS_CONFIG,
      },
    ];
    renderStrict();
    await flush();
    const badge = screen.getByText("Awaiting finalization");
    expect(badge.getAttribute("title")).toMatch(/Finalize to compute stable citation identities/);
    expect(screen.getByText(/Report generation still uses the sample corpus/)).toBeTruthy();
  });

  it("renders typed ingestion failures with a retry action", async () => {
    listResponses = [
      {
        documents: [
          tenantDoc({
            ingestion: ingestion({
              stage: "failed",
              status: "failed",
              errorCode: "invalid_encoding",
              errorMessage: "The file is not valid UTF-8 text.",
            }),
          }),
        ],
        tenantCorpus: CORPUS_CONFIG,
      },
    ];
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/documents" && (!init || !init.method)) return json(200, listBody());
      if (url === "/api/documents/doc-1/retry" && init?.method === "POST") {
        return json(202, { retried: true });
      }
      throw new Error(`unmocked: ${init?.method} ${url}`);
    });

    renderStrict();
    await flush();
    expect(screen.getByText("Failed")).toBeTruthy();
    expect(screen.getByText("The file is not valid UTF-8 text.")).toBeTruthy();

    fireEvent.click(screen.getByText("Retry"));
    await flush();
    const retries = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/retry"));
    expect(retries).toHaveLength(1);
    expect(screen.getByText("Retry started.")).toBeTruthy();
  });

  it("uploads a new version for an existing document", async () => {
    listResponses = [
      {
        documents: [tenantDoc({ ingestion: ingestion({ stage: "ready", status: "ready", sectionCount: 2 }) })],
        tenantCorpus: CORPUS_CONFIG,
      },
    ];
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/documents" && (!init || !init.method)) return json(200, listBody());
      if (url === "/api/documents/doc-1/versions" && init?.method === "POST") {
        expect(init.body).toBeInstanceOf(FormData);
        return json(202, { documentId: "doc-1", versionId: "v-2", versionNo: 2 });
      }
      throw new Error(`unmocked: ${init?.method} ${url}`);
    });

    renderStrict();
    await flush();
    fireEvent.click(screen.getByText("New version"));
    fireEvent.change(screen.getByLabelText("New version file"), {
      target: { files: [mdFile("policy-v2.md")] },
    });
    await flush();

    expect(screen.getByText("New version accepted — processing has started.")).toBeTruthy();
    const posts = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/versions"));
    expect(posts).toHaveLength(1);
  });

  it("reports an identical new version as an explicit no-op", async () => {
    listResponses = [
      {
        documents: [tenantDoc({ ingestion: ingestion({ stage: "ready", status: "ready" }) })],
        tenantCorpus: CORPUS_CONFIG,
      },
    ];
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/documents" && (!init || !init.method)) return json(200, listBody());
      if (String(url).endsWith("/versions") && init?.method === "POST") {
        return json(200, { documentId: "doc-1", versionId: "v-1", versionNo: 1, noop: true });
      }
      throw new Error("unmocked");
    });
    renderStrict();
    await flush();
    fireEvent.click(screen.getByText("New version"));
    fireEvent.change(screen.getByLabelText("New version file"), {
      target: { files: [mdFile()] },
    });
    await flush();
    expect(
      screen.getByText("Identical to the current version — no new version was created."),
    ).toBeTruthy();
  });

  // ------------------------------------------------------------------ //
  // polling lifecycle
  // ------------------------------------------------------------------ //

  it("polls only while processing, without Strict Mode duplication, and stops on terminal state", async () => {
    vi.useFakeTimers();
    const processing = tenantDoc({ ingestion: ingestion({ stage: "extracting" }) });
    const done = tenantDoc({ ingestion: ingestion({ stage: "ready", status: "ready", sectionCount: 3 }) });
    listResponses = [
      { documents: [processing], tenantCorpus: CORPUS_CONFIG }, // strict-mode mount #1
      { documents: [processing], tenantCorpus: CORPUS_CONFIG }, // strict-mode mount #2
      { documents: [processing], tenantCorpus: CORPUS_CONFIG }, // poll tick 1
      { documents: [done], tenantCorpus: CORPUS_CONFIG }, // poll tick 2 -> terminal
    ];

    renderStrict();
    await flush();
    expect(screen.getByText("Extracting")).toBeTruthy();
    const listCallsAfterMount = fetchMock.mock.calls.length;

    await act(async () => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS);
    });
    await flush();
    // exactly ONE poll fired per interval (no duplicate Strict Mode timers)
    expect(fetchMock.mock.calls.length).toBe(listCallsAfterMount + 1);

    await act(async () => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS);
    });
    await flush();
    expect(screen.getByText("Awaiting finalization")).toBeTruthy();

    // terminal: no further polling
    const settled = fetchMock.mock.calls.length;
    await act(async () => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS * 4);
    });
    await flush();
    expect(fetchMock.mock.calls.length).toBe(settled);
  });

  it("does not poll for terminal documents and cleans up on unmount", async () => {
    vi.useFakeTimers();
    listResponses = [
      {
        documents: [tenantDoc({ ingestion: ingestion({ stage: "ready", status: "ready" }) })],
        tenantCorpus: CORPUS_CONFIG,
      },
    ];
    const view = renderStrict();
    await flush();
    const afterMount = fetchMock.mock.calls.length;

    await act(async () => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS * 4);
    });
    expect(fetchMock.mock.calls.length).toBe(afterMount); // no polling when terminal

    view.unmount();
    await act(async () => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS * 4);
    });
    expect(fetchMock.mock.calls.length).toBe(afterMount); // nothing after unmount
  });

  it("keeps polling cleanup on unmount while active", async () => {
    vi.useFakeTimers();
    listResponses = [
      { documents: [tenantDoc({ ingestion: ingestion({ stage: "sectioning" }) })], tenantCorpus: CORPUS_CONFIG },
    ];
    const view = renderStrict();
    await flush();
    const afterMount = fetchMock.mock.calls.length;
    view.unmount();
    await act(async () => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS * 10);
    });
    expect(fetchMock.mock.calls.length).toBe(afterMount); // interval cleared
  });

  // ------------------------------------------------------------------ //
  // M3 finalization states
  // ------------------------------------------------------------------ //

  it("offers Finalize on a parsed transitional document and reports the start", async () => {
    listResponses = [
      {
        documents: [
          tenantDoc({
            ingestion: ingestion({
              stage: "ready", status: "ready", sectionCount: 3, identity: "transitional",
            }),
          }),
        ],
        tenantCorpus: CORPUS_CONFIG,
      },
    ];
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/documents" && (!init || !init.method)) return json(200, listBody());
      if (url === "/api/documents/doc-1/finalize" && init?.method === "POST") {
        return json(202, { documentId: "doc-1", versionNo: 2, created: true });
      }
      throw new Error(`unmocked: ${init?.method} ${url}`);
    });

    renderStrict();
    await flush();
    fireEvent.click(screen.getByText("Finalize"));
    await flush();

    const posts = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/finalize"));
    expect(posts).toHaveLength(1);
    expect(
      screen.getByText("Finalization started — anchors and classification are being computed."),
    ).toBeTruthy();
  });

  it("labels the M3 stages honestly and keeps polling through them", async () => {
    vi.useFakeTimers();
    const anchoring = tenantDoc({
      ingestion: ingestion({ stage: "anchoring", stageKind: "finalize", identity: "transitional" }),
    });
    const classifying = tenantDoc({
      ingestion: ingestion({ stage: "classifying", stageKind: "finalize", identity: "transitional" }),
    });
    const final = tenantDoc({
      ingestion: ingestion({
        stage: "ready", status: "ready", stageKind: "finalize",
        identity: "final", finalized: true, versionNo: 2, sectionCount: 3,
      }),
    });
    listResponses = [
      { documents: [anchoring], tenantCorpus: CORPUS_CONFIG }, // mount #1
      { documents: [anchoring], tenantCorpus: CORPUS_CONFIG }, // mount #2
      { documents: [classifying], tenantCorpus: CORPUS_CONFIG }, // poll 1
      { documents: [final], tenantCorpus: CORPUS_CONFIG }, // poll 2 -> terminal
    ];

    renderStrict();
    await flush();
    expect(screen.getByText("Anchoring")).toBeTruthy();

    await act(async () => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS);
    });
    await flush();
    expect(screen.getByText("Classifying")).toBeTruthy();

    await act(async () => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS);
    });
    await flush();
    expect(screen.getByText("Citation-ready")).toBeTruthy();

    // terminal: polling stops; no Finalize offered on a final document
    const settled = fetchMock.mock.calls.length;
    await act(async () => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS * 4);
    });
    await flush();
    expect(fetchMock.mock.calls.length).toBe(settled);
    expect(screen.queryByText("Finalize")).toBeNull();
  });

  it("distinguishes a citation-ready document without claiming generation use", async () => {
    listResponses = [
      {
        documents: [
          tenantDoc({
            ingestion: ingestion({
              stage: "ready", status: "ready", stageKind: "finalize",
              identity: "final", finalized: true, versionNo: 2, sectionCount: 3,
            }),
          }),
        ],
        tenantCorpus: CORPUS_CONFIG,
      },
    ];
    renderStrict();
    await flush();
    const badge = screen.getByText("Citation-ready");
    expect(badge.getAttribute("title")).toMatch(/still uses the sample corpus/);
    expect(screen.queryByText("Finalize")).toBeNull();
    // the generation note remains demo-only
    expect(screen.getByText(/Report generation still uses the sample corpus/)).toBeTruthy();
  });

  it("labels a failed finalization distinctly and allows retry", async () => {
    listResponses = [
      {
        documents: [
          tenantDoc({
            ingestion: ingestion({
              stage: "failed", status: "ready", stageKind: "finalize",
              identity: "transitional", versionNo: 2,
              errorCode: "anchoring_failed",
              errorMessage: "Stable section identities could not be assigned.",
            }),
          }),
        ],
        tenantCorpus: CORPUS_CONFIG,
      },
    ];
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/documents" && (!init || !init.method)) return json(200, listBody());
      if (url === "/api/documents/doc-1/retry" && init?.method === "POST") {
        return json(202, { retried: true });
      }
      throw new Error(`unmocked: ${init?.method} ${url}`);
    });

    renderStrict();
    await flush();
    expect(screen.getByText("Finalization failed")).toBeTruthy();
    expect(screen.getByText("Stable section identities could not be assigned.")).toBeTruthy();

    fireEvent.click(screen.getByText("Retry"));
    await flush();
    expect(screen.getByText("Retry started.")).toBeTruthy();
  });

  it("surfaces a typed finalize rejection", async () => {
    listResponses = [
      {
        documents: [
          tenantDoc({
            ingestion: ingestion({
              stage: "ready", status: "ready", identity: "transitional",
            }),
          }),
        ],
        tenantCorpus: CORPUS_CONFIG,
      },
    ];
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/documents" && (!init || !init.method)) return json(200, listBody());
      if (String(url).endsWith("/finalize") && init?.method === "POST") {
        return json(409, { code: "already_final" });
      }
      throw new Error(`unmocked: ${init?.method} ${url}`);
    });

    renderStrict();
    await flush();
    fireEvent.click(screen.getByText("Finalize"));
    await flush();
    expect(screen.getByText("This document is already citation-ready.")).toBeTruthy();
  });

  // ------------------------------------------------------------------ //
  // sample vs tenant separation
  // ------------------------------------------------------------------ //

  it("keeps sample and tenant documents visibly separate", async () => {
    listResponses = [
      {
        documents: [tenantDoc({ title: "my-own-policy", ingestion: ingestion({ stage: "ready", status: "ready" }) })],
        tenantCorpus: CORPUS_CONFIG,
      },
    ];
    renderStrict();
    await flush();

    expect(screen.getByText("SAMPLE CORPUS (DEMO)")).toBeTruthy();
    expect(screen.getByText("YOUR DOCUMENTS")).toBeTruthy();
    expect(screen.getByText(/not your uploaded content/)).toBeTruthy();
    expect(screen.getByText("my-own-policy")).toBeTruthy();
    // demo docs are marked Sample; the tenant doc is not
    const tenantRow = screen.getByText("my-own-policy").closest("div") as HTMLElement;
    expect(within(tenantRow.parentElement as HTMLElement).queryByText("Sample")).toBeNull();
  });
});
