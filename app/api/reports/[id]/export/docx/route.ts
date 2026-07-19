import { NextResponse } from "next/server";
import {
  applySession,
  authedBackendFetch,
  backendUrl,
  forwardedForHeader,
  type SessionTokens,
} from "@/lib/auth/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const DOCX_CONTENT_TYPE =
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

/**
 * Defensive ceiling on the DOCX body this BFF will buffer, mirroring the backend's
 * own `EVIDENTIA_EXPORT_MAX_BYTES` cap (12 MiB). The backend already refuses to
 * emit anything larger, so this is a second, independent bound — an over-large
 * body is rejected by its declared `Content-Length` *before* buffering, so a
 * mis-sized upstream response cannot pin memory in the Next process.
 */
const DEFAULT_MAX_EXPORT_BYTES = 12 * 1024 * 1024;
const RENDERER_HEADERS = [
  "x-evidentia-renderer",
  "x-evidentia-renderer-version",
  "x-evidentia-content-hash",
  "x-evidentia-semantic-digest",
] as const;

type BoundedBodyResult =
  | { ok: true; bytes: Uint8Array }
  | { ok: false; reason: "too_large" | "missing_body" };

function maxExportBytes(): number {
  const configured = Number(process.env.EVIDENTIA_EXPORT_MAX_BYTES);
  return Number.isSafeInteger(configured) && configured > 0
    ? configured
    : DEFAULT_MAX_EXPORT_BYTES;
}

/** Read an upstream body without ever retaining more than `maxBytes`. */
async function readBoundedBody(res: Response, maxBytes: number): Promise<BoundedBodyResult> {
  const declared = res.headers.get("content-length");
  if (declared !== null) {
    // Content-Length is decimal digits only. Reject ambiguous, negative, unsafe,
    // or oversized declarations before touching the body stream.
    if (!/^\d+$/.test(declared)) return { ok: false, reason: "too_large" };
    const declaredBytes = Number(declared);
    if (!Number.isSafeInteger(declaredBytes) || declaredBytes > maxBytes) {
      return { ok: false, reason: "too_large" };
    }
  }

  if (!res.body) return { ok: false, reason: "missing_body" };

  const reader = res.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    if (!value || value.byteLength === 0) continue;

    total += value.byteLength;
    if (total > maxBytes) {
      await reader.cancel().catch(() => {});
      return { ok: false, reason: "too_large" };
    }
    chunks.push(value);
  }

  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return { ok: true, bytes };
}

/**
 * GET /api/reports/[id]/export/docx — authenticated DOCX export proxy.
 *
 * The browser never holds a token: this BFF route reads the httpOnly session,
 * calls the Python backend as the user (transparently refreshing an expired
 * access token, and persisting the rotation onto the response), and streams the
 * rendered DOCX bytes back with the backend's content type and filename intact.
 *
 * There is **no demo fallback**: an authenticated export belongs to a real
 * tenant, so if the backend cannot validate the session or find the report, this
 * returns the backend's status verbatim — never a locally produced document.
 * Cross-tenant / unknown / non-completed reports surface as 404, exactly as they
 * do on the report read route.
 */
export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  if (!backendUrl()) {
    return NextResponse.json({ code: "backend_unavailable" }, { status: 503 });
  }

  const page = new URL(request.url).searchParams.get("page");
  const query = page === "Letter" ? "?page=Letter" : "";
  let rotatedSession: SessionTokens | undefined;
  const finalize = (response: NextResponse) => applySession(response, rotatedSession);

  try {
    const { res, rotated } = await authedBackendFetch(
      `/api/reports/${encodeURIComponent(id)}/export/docx${query}`,
      {},
      Number(process.env.EVIDENTIA_BACKEND_TIMEOUT_MS) || 45_000,
      forwardedForHeader(request),
    );
    rotatedSession = rotated;

    if (res.status === 401) {
      return finalize(
        NextResponse.json(
          { code: "not_authenticated", error: "Your session has expired. Please sign in again." },
          { status: 401 },
        ),
      );
    }
    if (res.status === 429) {
      const retryAfter = res.headers.get("retry-after");
      return finalize(
        NextResponse.json(
          { code: "rate_limited", error: "Too many exports. Please try again shortly." },
          { status: 429, headers: retryAfter ? { "Retry-After": retryAfter } : undefined },
        ),
      );
    }
    if (!res.ok) {
      // 404 (unknown / cross-tenant / not completed), 413 (too large), 5xx.
      const status = res.status === 404 || res.status === 413 ? res.status : 502;
      return finalize(
        NextResponse.json(
          { code: status === 404 ? "not_found" : status === 413 ? "too_large" : "export_failed" },
          { status },
        ),
      );
    }

    // Independent size bound: strict declared-length validation plus incremental
    // counting means neither a false Content-Length nor a chunked response can
    // make the BFF retain more than the configured maximum.
    const bounded = await readBoundedBody(res, maxExportBytes());
    if (!bounded.ok) {
      const response =
        bounded.reason === "too_large"
          ? NextResponse.json({ code: "too_large" }, { status: 413 })
          : NextResponse.json({ code: "export_failed" }, { status: 502 });
      return finalize(response);
    }

    const headers = new Headers({
      "Content-Type": res.headers.get("content-type") || DOCX_CONTENT_TYPE,
      "Content-Disposition":
        res.headers.get("content-disposition") || 'attachment; filename="evidentia-report.docx"',
      "Content-Length": String(bounded.bytes.byteLength),
      "Cache-Control": "no-store",
    });
    for (const name of RENDERER_HEADERS) {
      const value = res.headers.get(name);
      if (value !== null) headers.set(name, value);
    }

    const download = new NextResponse(bounded.bytes, {
      status: 200,
      headers,
    });
    return finalize(download);
  } catch {
    // Network error / timeout: we cannot validate the session, so we must not
    // produce a document. Never fall back.
    return finalize(NextResponse.json({ code: "backend_unavailable" }, { status: 503 }));
  }
}
