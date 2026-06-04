"""OpenAI Responses API client helpers for future agent upgrades."""

from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv

DEFAULT_MODEL = "gpt-5.2"


def _api_key() -> str:
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is missing. Add it to your environment or .env file."
        )
    return api_key


def _model() -> str:
    load_dotenv()
    return os.getenv("OPENAI_MODEL", DEFAULT_MODEL)


def _client() -> Any:
    _api_key()
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "The official OpenAI SDK is not installed. Run `pip install openai`."
        ) from exc

    return OpenAI()


def _extract_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return str(output_text).strip()

    output = getattr(response, "output", None)
    if output:
        chunks: list[str] = []
        for item in output:
            for content in getattr(item, "content", []) or []:
                text = getattr(content, "text", None)
                if text:
                    chunks.append(str(text))
        if chunks:
            return "\n".join(chunks).strip()

    raise RuntimeError("OpenAI response did not contain text output.")


def ask_llm(system_prompt: str, user_prompt: str) -> str:
    """Ask an OpenAI model for a text response."""
    client = _client()
    response = client.responses.create(
        model=_model(),
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return _extract_text(response)


def ask_llm_json(system_prompt: str, user_prompt: str) -> dict[str, Any]:
    """Ask an OpenAI model for a JSON object response."""
    json_system_prompt = (
        f"{system_prompt}\n\n"
        "Return only one valid JSON object. Do not include markdown fences."
    )
    text = ask_llm(json_system_prompt, user_prompt)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("OpenAI response was not valid JSON.") from exc

    if not isinstance(parsed, dict):
        raise ValueError("OpenAI JSON response must be an object.")

    return parsed

