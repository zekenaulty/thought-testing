"""Small REST helpers for controlled Gemini Interactions experiments."""

from __future__ import annotations

import copy
import hashlib
import http.client
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable

API_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
DEFAULT_API_REVISION: str | None = None


@dataclass(frozen=True)
class InteractionHttpResult:
    http_status: int | None
    payload: dict[str, Any] | None
    raw_body: str
    transport_error: str
    response_parse_error: str
    elapsed_ms: int
    raw_body_bytes: bytes = b""
    response_headers: dict[str, str] | None = None


def _audit_headers(headers: Any) -> dict[str, str]:
    allowed = {"date", "retry-after", "x-request-id", "x-goog-request-id"}
    if headers is None:
        return {}
    return {
        str(key).lower(): str(value)
        for key, value in headers.items()
        if str(key).lower() in allowed
    }


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def user_step(text: str) -> dict[str, Any]:
    return {
        "type": "user_input",
        "content": [{"type": "text", "text": text}],
    }


def build_interaction_body(
    *,
    model: str,
    input_steps: list[dict[str, Any]],
    generation_config: dict[str, Any],
    response_format: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "store": False,
        "stream": False,
        "background": False,
        "input": copy.deepcopy(input_steps),
        "generation_config": copy.deepcopy(generation_config),
    }
    if response_format is not None:
        body["response_format"] = copy.deepcopy(response_format)
    return body


def _decode_payload(raw_body: str) -> tuple[dict[str, Any] | None, str]:
    try:
        value = json.loads(raw_body)
    except (ValueError, RecursionError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if not isinstance(value, dict):
        return None, "response JSON was not an object"
    return value, ""


def _incomplete_read_result(
    *,
    exc: http.client.IncompleteRead,
    http_status: int,
    headers: Any,
    started: float,
) -> InteractionHttpResult:
    partial = exc.partial
    raw_body_bytes = (
        partial
        if isinstance(partial, bytes)
        else bytes(partial)
        if isinstance(partial, bytearray)
        else b""
    )
    return InteractionHttpResult(
        http_status=http_status,
        payload=None,
        raw_body=raw_body_bytes.decode("utf-8", errors="replace"),
        transport_error="IncompleteRead: partial response body",
        response_parse_error="",
        elapsed_ms=round((time.perf_counter() - started) * 1000),
        raw_body_bytes=raw_body_bytes,
        response_headers=_audit_headers(headers),
    )


def post_interaction(
    *,
    api_key: str,
    body: dict[str, Any],
    timeout: int,
    api_url: str = API_URL,
    api_revision: str | None = DEFAULT_API_REVISION,
    encoded_body: bytes | None = None,
) -> InteractionHttpResult:
    """POST an Interactions request while retaining HTTP failures as data."""
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }
    if api_revision:
        headers["Api-Revision"] = api_revision
    request = urllib.request.Request(
        api_url,
        data=encoded_body if encoded_body is not None else canonical_json_bytes(body),
        method="POST",
        headers=headers,
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            try:
                raw_body_bytes = response.read()
            except http.client.IncompleteRead as exc:
                return _incomplete_read_result(
                    exc=exc,
                    http_status=int(response.status),
                    headers=response.headers,
                    started=started,
                )
            raw_body = raw_body_bytes.decode("utf-8", errors="replace")
            payload, parse_error = _decode_payload(raw_body)
            return InteractionHttpResult(
                http_status=int(response.status),
                payload=payload,
                raw_body=raw_body,
                transport_error="",
                response_parse_error=parse_error,
                elapsed_ms=round((time.perf_counter() - started) * 1000),
                raw_body_bytes=raw_body_bytes,
                response_headers=_audit_headers(response.headers),
            )
    except urllib.error.HTTPError as exc:
        try:
            raw_body_bytes = exc.read()
        except http.client.IncompleteRead as incomplete:
            return _incomplete_read_result(
                exc=incomplete,
                http_status=int(exc.code),
                headers=exc.headers,
                started=started,
            )
        raw_body = raw_body_bytes.decode("utf-8", errors="replace")
        payload, parse_error = _decode_payload(raw_body)
        return InteractionHttpResult(
            http_status=int(exc.code),
            payload=payload,
            raw_body=raw_body,
            transport_error="",
            response_parse_error=parse_error,
            elapsed_ms=round((time.perf_counter() - started) * 1000),
            raw_body_bytes=raw_body_bytes,
            response_headers=_audit_headers(exc.headers),
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return InteractionHttpResult(
            http_status=None,
            payload=None,
            raw_body="",
            transport_error=f"{type(exc).__name__}: {exc}",
            response_parse_error="",
            elapsed_ms=round((time.perf_counter() - started) * 1000),
        )


def response_steps(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return every response step unchanged and in provider order."""
    steps = payload.get("steps")
    if not isinstance(steps, list):
        raise ValueError("interaction response is missing a steps array")
    if any(not isinstance(step, dict) for step in steps):
        raise ValueError("interaction response contains a non-object step")
    return copy.deepcopy(steps)


def select_steps(
    steps: Iterable[dict[str, Any]],
    allowed_types: set[str],
) -> list[dict[str, Any]]:
    """Filter steps without changing their relative order."""
    return [
        copy.deepcopy(step)
        for step in steps
        if str(step.get("type") or "") in allowed_types
    ]


def output_text(payload: dict[str, Any]) -> str:
    pieces: list[str] = []
    for step in payload.get("steps", []) or []:
        if not isinstance(step, dict) or step.get("type") != "model_output":
            continue
        content = step.get("content", []) or []
        if isinstance(content, str):
            pieces.append(content)
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                pieces.append(str(block.get("text") or ""))
    return "".join(pieces).strip()


def error_text(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    return ""


def thought_signature_metadata(
    steps: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    metadata: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        if step.get("type") != "thought":
            continue
        signature = step.get("signature")
        if not isinstance(signature, str) or not signature:
            continue
        metadata.append(
            {
                "step_index": index,
                "signature_sha256": sha256_text(signature),
                "signature_chars": len(signature),
            }
        )
    return metadata
