import { proxyMultipartUpload } from "@/lib/uploadProxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * POST /api/documents/upload — authenticated multipart MD/TXT upload.
 *
 * Bounded passthrough to the backend, which owns validation, dedupe, quotas
 * and rate limits. 202 = new ingestion job; 200 = explicit duplicate/no-op;
 * 403 tenant_corpus_disabled when the feature flag is off.
 */
export async function POST(request: Request) {
  return proxyMultipartUpload(request, "/api/documents/upload");
}
