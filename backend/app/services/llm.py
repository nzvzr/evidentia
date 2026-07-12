"""LLM service.

Reads the API key from backend/.env (via config). When the LLM is enabled and a
key exists, calls OpenAI and returns a parsed JSON object; otherwise (or on any
error) returns the provided fallback. Never crashes; never exposes keys.

Returns an LLMCallResult so the orchestrator can count calls and log context
size without inspecting internals.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger("evidentia.llm")


@dataclass
class LLMCallResult:
    value: Any
    called: bool
    input_chars: int
    input_tokens: int = 0
    output_tokens: int = 0


def generate_structured_object(
    *,
    system: str,
    user: str,
    schema_name: str,
    schema: Any,
    fallback: Any,
    max_output_tokens: int = 700,
) -> LLMCallResult:
    settings = get_settings()
    # The orchestrator gates *which* agents call the LLM per resolved mode; here
    # we only require that an LLM is actually configured and available.
    if not settings.is_llm_enabled() or settings.evidentia_llm_provider != "openai":
        return LLMCallResult(fallback, False, 0)

    schema_text = json.dumps(schema, indent=2)
    system_prompt = (
        f"{system}\n\n"
        f'Return ONLY a valid JSON object named "{schema_name}" that conforms to this schema. '
        "Do not include markdown, code fences, or any prose outside the JSON.\n"
        f"Schema:\n{schema_text}"
    )
    input_chars = len(system_prompt) + len(user)

    try:
        from openai import OpenAI  # lazy import so the backend runs without the SDK when off

        client = OpenAI(api_key=settings.openai_api_key)
        completion = client.chat.completions.create(
            model=settings.evidentia_llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            max_tokens=max_output_tokens,
        )
        usage = getattr(completion, "usage", None)
        in_tok = int(getattr(usage, "prompt_tokens", 0) or 0)
        out_tok = int(getattr(usage, "completion_tokens", 0) or 0)
        content = completion.choices[0].message.content
        if not content:
            return LLMCallResult(fallback, True, input_chars, in_tok, out_tok)
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            return LLMCallResult(fallback, True, input_chars, in_tok, out_tok)
        return LLMCallResult(parsed, True, input_chars, in_tok, out_tok)
    except Exception as exc:  # noqa: BLE001 - never crash the request
        logger.warning("generate_structured_object(%s) failed: %s", schema_name, exc)
        return LLMCallResult(fallback, True, input_chars)
