import { NextResponse } from "next/server";
import { runEvidentiaAgentsV2 } from "@/lib/agents/llmOrchestrator";
import type { AgentInput } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface RequestBody {
  market?: unknown;
  persona?: unknown;
  customPersona?: unknown;
  selectedDocumentIds?: unknown;
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((v): v is string => typeof v === "string");
}

/**
 * POST /api/generate-workflow
 *
 * If EVIDENTIA_BACKEND_URL is set, proxies the request to the Python FastAPI
 * backend and returns its EvidentiaReport. If the backend is unset, offline, or
 * errors, it falls back to the built-in TypeScript pipeline (deterministic, with
 * optional LLM refinement). Never exposes API keys or backend internals.
 */
export async function POST(request: Request) {
  let body: RequestBody = {};
  try {
    body = (await request.json()) as RequestBody;
  } catch {
    // Empty / invalid JSON → fall back to defaults below.
    body = {};
  }

  const input: AgentInput = {
    market: asString(body.market) || "EMEA",
    persona: asString(body.persona) || "Support Agent",
    customPersona: asString(body.customPersona),
    selectedDocumentIds: asStringArray(body.selectedDocumentIds),
  };

  // 1. Proxy to the Python backend when configured. The backend owns the API
  //    keys; the frontend never sees them. On any failure we fall through to
  //    the deterministic TypeScript pipeline below.
  const backendUrl = process.env.EVIDENTIA_BACKEND_URL;
  if (backendUrl) {
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 20000);
      const res = await fetch(`${backendUrl.replace(/\/$/, "")}/api/generate-workflow`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(input),
        signal: controller.signal,
        cache: "no-store",
      });
      clearTimeout(timeout);
      if (res.ok) {
        const report = await res.json();
        return NextResponse.json(report, { status: 200 });
      }
      // Non-2xx: log status only (no secrets) and fall back.
      console.warn(`[evidentia] backend returned ${res.status}; using TypeScript fallback`);
    } catch {
      // Network error / backend offline — never surface backend internals.
      console.warn("[evidentia] backend unreachable; using TypeScript fallback");
    }
  }

  // 2. Deterministic (optionally LLM-assisted) TypeScript pipeline fallback.
  try {
    const report = await runEvidentiaAgentsV2(input, {
      generatedAt: new Date().toISOString(),
    });
    // generationMode / llmProvider / llmModel are embedded in the report.
    // API keys are never included in the response.
    return NextResponse.json(report, { status: 200 });
  } catch {
    return NextResponse.json(
      { error: "Failed to generate workflow" },
      { status: 500 },
    );
  }
}

export function GET() {
  return NextResponse.json(
    { message: "POST an AgentInput to generate an Evidentia report." },
    { status: 405 },
  );
}
