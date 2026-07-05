"""LLM service.

Reads the API key from backend/.env (via config). When EVIDENTIA_USE_LLM=true
and a key exists, calls OpenAI and returns a parsed JSON object; otherwise (or on
any error) returns the provided fallback. Never crashes; never exposes keys.
"""

from __future__ import annotations

import json
import logging
from typing import Any, TypeVar

from app.core.config import get_settings

logger = logging.getLogger("evidentia.llm")

T = TypeVar("T")


def generate_structured_object(
    *,
    system: str,
    user: str,
    schema_name: str,
    schema: Any,
    fallback: T,
) -> T:
    settings = get_settings()
    if not settings.is_llm_enabled() or settings.evidentia_llm_provider != "openai":
        return fallback

    try:
        # Imported lazily so the backend runs without the SDK when LLM is off.
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        schema_text = json.dumps(schema, indent=2)
        system_prompt = (
            f"{system}\n\n"
            f'Return ONLY a valid JSON object named "{schema_name}" that conforms to this schema. '
            "Do not include markdown, code fences, or any prose outside the JSON.\n"
            f"Schema:\n{schema_text}"
        )
        completion = client.chat.completions.create(
            model=settings.evidentia_llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
        )
        content = completion.choices[0].message.content
        if not content:
            return fallback
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            return fallback
        return parsed  # type: ignore[return-value]
    except Exception as exc:  # noqa: BLE001 - never crash the request
        logger.warning("generate_structured_object(%s) failed: %s", schema_name, exc)
        return fallback
