import { proxyMultipartUpload } from "@/lib/uploadProxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * POST /api/documents/[id]/versions — explicit new version for an existing
 * tenant document. Identical bytes are an explicit no-op (200); changed bytes
 * create immutable version N+1 (202). Cross-tenant ids are 404 at the backend.
 */
export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return proxyMultipartUpload(request, `/api/documents/${encodeURIComponent(id)}/versions`);
}
