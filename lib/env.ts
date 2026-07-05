/**
 * Server-side environment configuration.
 *
 * IMPORTANT: This module reads secret keys from process.env and must only be
 * imported from server code (API routes / server modules). Never use
 * NEXT_PUBLIC_* for secrets, and never import this into a client component.
 * On the client, process.env has no access to these values, so the keys read
 * as empty strings — the app then uses the deterministic pipeline.
 */

export type LlmProvider = "openai" | "anthropic";

export const env = {
  openaiApiKey: process.env.OPENAI_API_KEY ?? "",
  anthropicApiKey: process.env.ANTHROPIC_API_KEY ?? "",
  provider: (process.env.EVIDENTIA_LLM_PROVIDER ?? "openai") as LlmProvider,
  model: process.env.EVIDENTIA_LLM_MODEL ?? "gpt-5.5",
  useLlm: process.env.EVIDENTIA_USE_LLM === "true",
};

/** True only when LLM usage is explicitly enabled AND a matching key exists. */
export function isLlmEnabled(): boolean {
  if (!env.useLlm) return false;
  if (env.provider === "openai") return env.openaiApiKey.length > 0;
  if (env.provider === "anthropic") return env.anthropicApiKey.length > 0;
  return false;
}

/** The provider actually in use, or "none" when falling back to deterministic. */
export function activeProvider(): LlmProvider | "none" {
  return isLlmEnabled() ? env.provider : "none";
}

/** The model in use, or undefined for deterministic mode. */
export function activeModel(): string | undefined {
  return isLlmEnabled() ? env.model : undefined;
}
