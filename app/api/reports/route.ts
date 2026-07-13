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

/** GET /api/reports — proxy to the Python backend; empty list if unavailable. */
export async function GET() {
  const b = backend();
  if (!b) return NextResponse.json({ reports: [] });
  try {
    const res = await fetchWithTimeout(`${b}/api/reports`);
    if (!res.ok) return NextResponse.json({ reports: [] });
    return NextResponse.json(await res.json());
  } catch {
    return NextResponse.json({ reports: [] });
  }
}

/** POST /api/reports — proxy a report save to the backend. */
export async function POST(request: Request) {
  const b = backend();
  const body = await request.json().catch(() => ({}));
  if (!b) return NextResponse.json({ error: "persistence unavailable" }, { status: 503 });
  try {
    const res = await fetchWithTimeout(`${b}/api/reports`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return NextResponse.json(await res.json(), { status: res.status });
  } catch {
    return NextResponse.json({ error: "backend unreachable" }, { status: 502 });
  }
}
