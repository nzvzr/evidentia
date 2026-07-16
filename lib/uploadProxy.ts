import "server-only";

import { NextResponse } from "next/server";
import {
  applySession,
  authedBackendFetch,
  backendUrl,
  forwardedForHeader,
} from "@/lib/auth/session";

/**
 * Bounded multipart passthrough for the tenant document upload routes.
 *
 * The browser's multipart body is buffered ONCE with a hard byte cap (checked
 * against the declared Content-Length first, then counted as the stream
 * arrives, so a chunked body cannot slip past) and forwarded verbatim to the
 * backend with its original Content-Type boundary. The backend remains the
 * authority on authentication, file validation, per-file byte caps, quotas
 * and rate limits — this proxy only refuses to buffer the abusive case.
 *
 * There is deliberately NO client-side ingestion fallback: if the backend is
 * unreachable the upload fails with 503, exactly like every authenticated
 * route.
 */

const DEFAULT_MAX_FILE_BYTES = 2 * 1024 * 1024;
const MULTIPART_OVERHEAD = 64 * 1024;

export function uploadBodyLimit(): number {
  const configured = Number(process.env.EVIDENTIA_UPLOAD_MAX_FILE_BYTES);
  const fileCap = Number.isFinite(configured) && configured > 0 ? configured : DEFAULT_MAX_FILE_BYTES;
  return fileCap + MULTIPART_OVERHEAD;
}

async function readBytesWithLimit(
  request: Request,
  maxBytes: number,
): Promise<{ ok: true; body: Uint8Array } | { ok: false; response: NextResponse }> {
  const tooLarge = () => ({
    ok: false as const,
    response: NextResponse.json(
      { code: "payload_too_large", error: "Upload too large." },
      { status: 413 },
    ),
  });

  const declared = request.headers.get("content-length");
  if (declared && Number(declared) > maxBytes) return tooLarge();

  const reader = request.body?.getReader();
  if (!reader) return { ok: true, body: new Uint8Array(0) };

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
  return { ok: true, body: merged };
}

/** Forward a multipart POST to a backend path, preserving status + typed body. */
export async function proxyMultipartUpload(request: Request, backendPath: string) {
  if (!backendUrl()) {
    return NextResponse.json({ code: "backend_unavailable" }, { status: 503 });
  }

  const contentType = request.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().startsWith("multipart/form-data")) {
    return NextResponse.json(
      { code: "invalid_request", error: "Expected a multipart upload." },
      { status: 400 },
    );
  }

  const read = await readBytesWithLimit(request, uploadBodyLimit());
  if (!read.ok) return read.response;

  try {
    const { res, rotated } = await authedBackendFetch(
      backendPath,
      {
        method: "POST",
        // Preserve the multipart boundary; overrides the JSON default.
        headers: { "Content-Type": contentType },
        body: read.body,
      },
      // Ingestion accepts the file and processes in the background, but give
      // the request the same generous budget as generation cold starts.
      Number(process.env.EVIDENTIA_BACKEND_TIMEOUT_MS) || 45_000,
      forwardedForHeader(request),
    );
    if (res.status === 401) {
      return NextResponse.json({ code: "not_authenticated" }, { status: 401 });
    }
    return applySession(
      NextResponse.json(await res.json().catch(() => ({})), { status: res.status }),
      rotated,
    );
  } catch {
    return NextResponse.json({ code: "backend_unavailable" }, { status: 503 });
  }
}
