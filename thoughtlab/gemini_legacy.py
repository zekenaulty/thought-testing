from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


def generate_content(
    *,
    api_key: str,
    model: str,
    contents: list[dict[str, Any]],
    system_instruction: str | None = None,
    temperature: float = 0.0,
    max_output_tokens: int = 4096,
    thinking_level: str | None = None,
    timeout: int = 90,
    api_base: str = DEFAULT_API_BASE,
) -> tuple[int, dict[str, Any]]:
    """Call legacy Gemini generateContent with explicit content history.

    This path is intentional: historical BookForge artifacts stored
    thoughtSignature on response parts produced by generateContent.
    """
    model_name = urllib.parse.quote(model, safe="-._/")
    url = f"{api_base.rstrip('/')}/models/{model_name}:generateContent?key={urllib.parse.quote(api_key)}"

    generation_config: dict[str, Any] = {
        "temperature": temperature,
        "maxOutputTokens": max_output_tokens,
    }
    if thinking_level:
        generation_config["thinkingConfig"] = {"thinkingLevel": thinking_level}

    body: dict[str, Any] = {
        "contents": contents,
        "generationConfig": generation_config,
    }
    if system_instruction:
        body["system_instruction"] = {"parts": [{"text": system_instruction}]}

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status), json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw_error": raw}
        return int(exc.code), payload


def response_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    content = candidates[0].get("content")
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts")
    if not isinstance(parts, list):
        return ""
    return "".join(
        str(part.get("text") or "")
        for part in parts
        if isinstance(part, dict)
    ).strip()


def error_text(payload: dict[str, Any]) -> str:
    err = payload.get("error")
    if isinstance(err, dict) and err.get("message"):
        return str(err["message"])
    return str(payload.get("raw_error") or "")
