import OpenAI from "openai";
import { env, isLlmEnabled } from "@/lib/env";

interface GenerateArgs<T> {
  system: string;
  user: string;
  schemaName: string;
  /** JSON-schema-like description embedded into the prompt as guidance */
  schema: unknown;
  /** returned verbatim if LLM is disabled or anything fails */
  fallback: T;
}

const log = (...args: unknown[]) => {
  if (typeof window === "undefined") console.log("[evidentia:llm]", ...args);
};

/**
 * Ask the configured LLM to return a strict JSON object matching a schema.
 * Returns `fallback` whenever the LLM is disabled, the call errors, or the
 * response cannot be parsed. Never throws.
 *
 * Note: OpenAI JSON mode requires a top-level JSON object, so array outputs
 * should be wrapped, e.g. `{ steps: [...] }`.
 */
export async function generateStructuredObject<T>({
  system,
  user,
  schemaName,
  schema,
  fallback,
}: GenerateArgs<T>): Promise<T> {
  if (!isLlmEnabled() || env.provider !== "openai" || !env.openaiApiKey) {
    return fallback;
  }

  try {
    const client = new OpenAI({ apiKey: env.openaiApiKey });
    const schemaText = JSON.stringify(schema, null, 2);
    const systemPrompt =
      `${system}\n\n` +
      `Return ONLY a valid JSON object named "${schemaName}" that conforms to this schema. ` +
      `Do not include markdown, code fences, or any prose outside the JSON.\n` +
      `Schema:\n${schemaText}`;

    const completion = await client.chat.completions.create({
      model: env.model,
      messages: [
        { role: "system", content: systemPrompt },
        { role: "user", content: user },
      ],
      response_format: { type: "json_object" },
    });

    const content = completion.choices?.[0]?.message?.content;
    if (!content) {
      log("empty completion; using fallback");
      return fallback;
    }

    const parsed = JSON.parse(content) as unknown;
    if (parsed === null || typeof parsed !== "object") {
      log("parsed non-object; using fallback");
      return fallback;
    }
    return parsed as T;
  } catch (error) {
    log(`generateStructuredObject(${schemaName}) failed:`, error instanceof Error ? error.message : error);
    return fallback;
  }
}
