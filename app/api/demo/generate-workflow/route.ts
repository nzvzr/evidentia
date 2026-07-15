import { NextResponse } from "next/server";
import { runEvidentiaAgentsV2 } from "@/lib/agents/llmOrchestrator";
import { clientIp, rateLimit } from "@/lib/rateLimit";
import type { AgentInput } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * POST /api/demo/generate-workflow — the **explicitly public** sample pipeline.
 *
 * This is the only place the TypeScript pipeline is still reachable, and it is
 * deliberately not an authenticated route:
 *
 *   - it never reads the session cookies, so it cannot be mistaken for an
 *     authenticated request and cannot act on behalf of an account;
 *   - it runs only over the bundled public demo corpus;
 *   - it **persists nothing** — no tenant, no user, no database write;
 *   - it is IP-rate-limited in-process, because it can spend LLM budget without
 *     ever reaching the backend.
 *
 * The response carries `X-Evidentia-Demo: true`. The report body itself is an
 * unmodified `EvidentiaReport` — the public schema is not extended to mark it.
 */

const DEMO_LIMIT = Number(process.env.EVIDENTIA_DEMO_RATE_LIMIT) || 5;
const DEMO_WINDOW_SECONDS = Number(process.env.EVIDENTIA_DEMO_RATE_WINDOW) || 3600;

// The demo is a fixed showcase: callers do not get to steer the pipeline (and so
// cannot use it as a free, unauthenticated LLM endpoint with arbitrary input).
const DEMO_INPUT: AgentInput = {
  market: "EMEA",
  persona: "Support Agent",
  customPersona: "",
  selectedDocumentIds: [],
};

export async function POST(request: Request) {
  const ip = clientIp(request);
  const { allowed, retryAfter } = rateLimit(`demo:${ip}`, DEMO_LIMIT, DEMO_WINDOW_SECONDS);

  if (!allowed) {
    return NextResponse.json(
      { code: "rate_limited", error: "Demo limit reached. Please try again later." },
      { status: 429, headers: { "Retry-After": String(retryAfter) } },
    );
  }

  try {
    const report = await runEvidentiaAgentsV2(DEMO_INPUT, {
      generatedAt: new Date().toISOString(),
    });
    return NextResponse.json(report, {
      status: 200,
      headers: { "X-Evidentia-Demo": "true", "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json(
      { code: "demo_failed", error: "Could not generate the demo report." },
      { status: 500 },
    );
  }
}

export function GET() {
  return NextResponse.json(
    { message: "POST to generate a public sample report. Not persisted." },
    { status: 405 },
  );
}
