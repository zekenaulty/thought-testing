"""Exact REST transport helpers for Gemini Developer API generateContent."""

from __future__ import annotations

import copy
import hashlib
import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable


API_BASE = "https://generativelanguage.googleapis.com/v1beta"


@dataclass(frozen=True)
class GenerateContentHttpResult:
    http_status: int | None
    payload: dict[str, Any] | None
    raw_body: str
    transport_error: str
    response_parse_error: str
    elapsed_ms: int
    raw_body_bytes: bytes = b""
    response_headers: dict[str, str] | None = None


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


def generate_content_url(*, model: str, api_base: str = API_BASE) -> str:
    """Return the exact Developer API generateContent request target."""

    model_name = urllib.parse.quote(model, safe="-._/")
    return f"{api_base.rstrip('/')}/models/{model_name}:generateContent"


def _audit_headers(headers: Any) -> dict[str, str]:
    allowed = {"date", "retry-after", "x-request-id", "x-goog-request-id"}
    if headers is None:
        return {}
    return {
        str(key).lower(): str(value)
        for key, value in headers.items()
        if str(key).lower() in allowed
    }


def decode_generate_content_payload(
    raw_body: str,
) -> tuple[dict[str, Any] | None, str]:
    try:
        value = json.loads(raw_body)
    except (ValueError, RecursionError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if not isinstance(value, dict):
        return None, "response JSON was not an object"
    return value, ""


def decode_generate_content_bytes(
    raw_body_bytes: bytes,
) -> tuple[str, dict[str, Any] | None, str]:
    """Strictly decode provider JSON while retaining displayable audit text."""

    try:
        raw_body = raw_body_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        return (
            raw_body_bytes.decode("utf-8", errors="replace"),
            None,
            f"{type(exc).__name__}: {exc}",
        )
    payload, parse_error = decode_generate_content_payload(raw_body)
    return raw_body, payload, parse_error


def _incomplete_read_result(
    *,
    exc: http.client.IncompleteRead,
    http_status: int,
    headers: Any,
    started: float,
) -> GenerateContentHttpResult:
    partial = exc.partial
    raw_body_bytes = (
        partial
        if isinstance(partial, bytes)
        else bytes(partial)
        if isinstance(partial, bytearray)
        else b""
    )
    return GenerateContentHttpResult(
        http_status=http_status,
        payload=None,
        raw_body=raw_body_bytes.decode("utf-8", errors="replace"),
        transport_error="IncompleteRead: partial response body",
        response_parse_error="",
        elapsed_ms=round((time.perf_counter() - started) * 1000),
        raw_body_bytes=raw_body_bytes,
        response_headers=_audit_headers(headers),
    )


def post_generate_content(
    *,
    api_key: str,
    model: str,
    body: dict[str, Any],
    timeout: int,
    api_base: str = API_BASE,
    encoded_body: bytes | None = None,
) -> GenerateContentHttpResult:
    """POST generateContent while retaining exact success/failure bytes."""

    url = generate_content_url(model=model, api_base=api_base)
    request = urllib.request.Request(
        url,
        data=(
            encoded_body
            if encoded_body is not None
            else canonical_json_bytes(body)
        ),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
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
            raw_body, payload, parse_error = decode_generate_content_bytes(
                raw_body_bytes
            )
            return GenerateContentHttpResult(
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
        raw_body, payload, parse_error = decode_generate_content_bytes(
            raw_body_bytes
        )
        return GenerateContentHttpResult(
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
        return GenerateContentHttpResult(
            http_status=None,
            payload=None,
            raw_body="",
            transport_error=f"{type(exc).__name__}: {exc}",
            response_parse_error="",
            elapsed_ms=round((time.perf_counter() - started) * 1000),
        )


def response_contents(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the first candidate's native model content without mutation."""

    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise ValueError(
            "generateContent response does not contain exactly one candidate"
        )
    if any(not isinstance(candidate, dict) for candidate in candidates):
        raise ValueError("generateContent response contains a non-object candidate")
    content = candidates[0].get("content")
    if not isinstance(content, dict):
        raise ValueError("generateContent candidate has no content object")
    if content.get("role") != "model":
        raise ValueError("generateContent candidate content is not model role")
    parts = content.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ValueError("generateContent candidate has no content parts")
    if any(not isinstance(part, dict) for part in parts):
        raise ValueError("generateContent candidate contains a non-object part")
    return [copy.deepcopy(content)]


def visible_text_from_contents(contents: Iterable[dict[str, Any]]) -> str:
    pieces: list[str] = []
    for content in contents:
        if content.get("role") != "model":
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict) or part.get("thought") is True:
                continue
            text = part.get("text")
            if isinstance(text, str):
                pieces.append(text)
    return "".join(pieces)


def thought_signature_metadata(
    contents: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    metadata: list[dict[str, Any]] = []
    for content_index, content in enumerate(contents):
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        for part_index, part in enumerate(parts):
            if not isinstance(part, dict):
                continue
            signature = part.get("thoughtSignature")
            if not isinstance(signature, str) or not signature:
                continue
            metadata.append(
                {
                    "content_index": content_index,
                    "part_index": part_index,
                    "signature_sha256": sha256_text(signature),
                    "signature_chars": len(signature),
                }
            )
    return metadata
