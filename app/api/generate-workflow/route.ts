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
 * Runs the deterministic multi-agent pipeline and returns an EvidentiaReport.
 * Requires no external APIs; validates input and applies safe defaults.
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

  try {
    const report = await runEvidentiaAgentsV2(input, {
      generatedAt: new Date().toISOString(),
    });
    // generationMode / llmProvider / llmModel are embedded in the report.
    // API keys are never included in the response.
    return NextResponse.json(report, { status: 200 });
  } catch (error) {
    return NextResponse.json(
      { error: "Failed to generate workflow", detail: String(error) },
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
