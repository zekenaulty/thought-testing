from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

SIGNATURE_KEYS = ("thoughtSignature", "thought_signature", "thoughtsignature")


def load_capsule(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("capsule must be a JSON object")
    part = payload.get("signed_part")
    if not isinstance(part, dict):
        raise ValueError("capsule is missing signed_part")
    if find_signature(part) is None:
        raise ValueError("capsule signed_part does not contain a thought signature")
    return payload


def find_signature(part: dict[str, Any]) -> tuple[str, Any] | None:
    for key in SIGNATURE_KEYS:
        if part.get(key):
            return key, part[key]
    fc = part.get("functionCall")
    if isinstance(fc, dict):
        for key in SIGNATURE_KEYS:
            if fc.get(key):
                return f"functionCall.{key}", fc[key]
    return None


def strip_signature(part: dict[str, Any]) -> dict[str, Any]:
    clone = copy.deepcopy(part)
    for key in SIGNATURE_KEYS:
        clone.pop(key, None)
    fc = clone.get("functionCall")
    if isinstance(fc, dict):
        for key in SIGNATURE_KEYS:
            fc.pop(key, None)
    return clone


def erase_visible_payload_keep_signature(part: dict[str, Any]) -> dict[str, Any]:
    """Keep the signed carrier shape, but remove human-readable payload where possible."""
    clone = copy.deepcopy(part)
    if "text" in clone:
        clone["text"] = ""
    # Function-call arguments are visible semantic payload too. Preserve the function name
    # for structural validity but blank arguments.
    fc = clone.get("functionCall")
    if isinstance(fc, dict):
        if "args" in fc:
            fc["args"] = {}
        if "arguments" in fc:
            fc["arguments"] = {}
    return clone


def signature_only_part(part: dict[str, Any]) -> dict[str, Any]:
    found = find_signature(part)
    if not found:
        return {}
    path, value = found
    if path.startswith("functionCall."):
        key = path.split(".", 1)[1]
        return {"functionCall": {key: value}}
    return {path: value}


def visible_payload(part: dict[str, Any]) -> str:
    if isinstance(part.get("text"), str):
        return str(part.get("text") or "")
    fc = part.get("functionCall")
    if isinstance(fc, dict):
        return json.dumps(fc, ensure_ascii=True, sort_keys=True)
    return ""
