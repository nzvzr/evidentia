import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function backend(): string | undefined {
  return process.env.EVIDENTIA_BACKEND_URL?.replace(/\/$/, "");
}

const READ_TIMEOUT_MS = Number(process.env.EVIDENTIA_BACKEND_READ_TIMEOUT_MS) || 8000;

async function fetchWithTimeout(url: string, init: RequestInit = {}, ms = READ_TIMEOUT_MS) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), ms);
  try {
    return await fetch(url, { ...init, cache: "no-store", signal: controller.signal });
  } finally {
    clearTimeout(timeout);
  }
}

/** GET /api/reports/[id] — proxy one report; 404 if backend unset/missing. */
export async function GET(_request: Request, { params }: { params: { id: string } }) {
  const b = backend();
  if (!b) return NextResponse.json({ error: "not found" }, { status: 404 });
  try {
    const res = await fetchWithTimeout(`${b}/api/reports/${encodeURIComponent(params.id)}`);
    if (!res.ok) return NextResponse.json({ error: "not found" }, { status: res.status });
    return NextResponse.json(await res.json());
  } catch {
    return NextResponse.json({ error: "backend unreachable" }, { status: 502 });
  }
}

/** DELETE /api/reports/[id] — proxy deletion. */
export async function DELETE(_request: Request, { params }: { params: { id: string } }) {
  const b = backend();
  if (!b) return NextResponse.json({ error: "persistence unavailable" }, { status: 503 });
  try {
    const res = await fetchWithTimeout(`${b}/api/reports/${encodeURIComponent(params.id)}`, {
      method: "DELETE",
    });
    return NextResponse.json(await res.json().catch(() => ({})), { status: res.status });
  } catch {
    return NextResponse.json({ error: "backend unreachable" }, { status: 502 });
  }
}
