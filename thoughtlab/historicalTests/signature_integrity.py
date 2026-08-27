#!/usr/bin/env python3
"""Cryptographic/structural sensitivity tests for historical thought signatures.

Experiments:
  exact_minimal      original signature in a minimal carrier
  bitflip_minimal    one base64 character changed, same length
  text_only          visible response with signature removed
  probe_only         no carrier

Optional two-capsule transplant experiments:
  b_sig_on_a_text    capsule B signature transplanted onto capsule A visible part
  a_sig_on_b_text    capsule A signature transplanted onto capsule B visible part
  b_minimal          capsule B signature alone

The transplant arms test whether semantic state follows the signature, follows
the visible carrier, or is rejected as an invalid binding.
"""
from __future__ import annotations

# Support direct execution from thoughtlab/historicalTests/ as documented.
from pathlib import Path as _BootstrapPath
import sys as _bootstrap_sys

_REPO_ROOT = _BootstrapPath(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in _bootstrap_sys.path:
    _bootstrap_sys.path.insert(0, str(_REPO_ROOT))
del _BootstrapPath, _bootstrap_sys, _REPO_ROOT

import argparse
import copy
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from thoughtlab.gemini_legacy import error_text, generate_content, response_text
from thoughtlab.historicalTests.capsule import (
    find_signature,
    load_capsule,
    signature_only_part,
    strip_signature,
)

PROBE = """\
Identify the preserved prior task and state without guessing.

Return JSON only:
{
  "task_or_objective": string|null,
  "salient_entities": [string],
  "hidden_or_nonvisible_details_recovered": [string],
  "confidence": string
}
"""


def user_content(text: str) -> dict[str, Any]:
    return {"role": "user", "parts": [{"text": text}]}


def model_content(part: dict[str, Any]) -> dict[str, Any]:
    return {"role": "model", "parts": [part]}


def signature_location(part: dict[str, Any]) -> tuple[list[str], str]:
    found = find_signature(part)
    if not found:
        raise ValueError("no thought signature")
    path, value = found
    if path.startswith("functionCall."):
        return ["functionCall", path.split(".", 1)[1]], str(value)
    return [path], str(value)


def set_signature(part: dict[str, Any], new_value: str) -> dict[str, Any]:
    clone = copy.deepcopy(part)
    path, _ = signature_location(clone)
    if len(path) == 1:
        clone[path[0]] = new_value
    else:
        clone[path[0]][path[1]] = new_value
    return clone


def mutate_base64_char(value: str) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    chars = list(value)
    # Change a character near the middle while preserving length and base64 alphabet.
    candidates = [i for i, ch in enumerate(chars) if ch in alphabet]
    if not candidates:
        raise ValueError("signature has no mutable base64 characters")
    i = candidates[len(candidates) // 2]
    old = chars[i]
    chars[i] = alphabet[(alphabet.index(old) + 1) % len(alphabet)]
    return "".join(chars)


def transplant_signature(target_part: dict[str, Any], donor_part: dict[str, Any]) -> dict[str, Any]:
    _, donor = signature_location(donor_part)
    target_without_sig = strip_signature(target_part)
    # Put donor signature at the same location used by the target's original signature.
    target_path, _ = signature_location(target_part)
    if len(target_path) == 1:
        target_without_sig[target_path[0]] = donor
    else:
        fc = target_without_sig.setdefault("functionCall", {})
        fc[target_path[1]] = donor
    return target_without_sig


def call(
    *,
    api_key: str,
    model: str,
    part: dict[str, Any] | None,
    timeout: int,
    neutral_stub: bool,
) -> dict[str, Any]:
    contents: list[dict[str, Any]] = []
    if part is not None and neutral_stub:
        contents.append(user_content("[historical-state-carrier follows]"))
    if part is not None:
        contents.append(model_content(part))
    contents.append(user_content(PROBE))
    status, payload = generate_content(
        api_key=api_key,
        model=model,
        contents=contents,
        system_instruction=None,
        temperature=0.0,
        max_output_tokens=2048,
        thinking_level="high",
        timeout=timeout,
    )
    return {
        "http_status": status,
        "text": response_text(payload) if 200 <= status < 300 else "",
        "error": "" if 200 <= status < 300 else error_text(payload),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capsule-a", required=True)
    ap.add_argument("--capsule-b", help="Optional second capsule for signature transplant")
    ap.add_argument("--model", help="Defaults to capsule A model")
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--neutral-stub", action="store_true")
    ap.add_argument("--out", default="results/signature_integrity.json")
    args = ap.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("Set GEMINI_API_KEY in the environment.", file=sys.stderr)
        return 2

    path_a = Path(args.capsule_a).expanduser().resolve()
    cap_a = load_capsule(path_a)
    part_a = copy.deepcopy(cap_a["signed_part"])
    _, sig_a = signature_location(part_a)
    model = str(args.model or cap_a.get("model") or "gemini-3.6-flash")

    arms: list[tuple[str, dict[str, Any] | None]] = [
        ("exact_minimal", signature_only_part(part_a)),
        (
            "bitflip_minimal",
            set_signature(signature_only_part(part_a), mutate_base64_char(sig_a)),
        ),
        ("text_only", strip_signature(part_a)),
        ("probe_only", None),
    ]

    cap_b = None
    path_b = None
    if args.capsule_b:
        path_b = Path(args.capsule_b).expanduser().resolve()
        cap_b = load_capsule(path_b)
        part_b = copy.deepcopy(cap_b["signed_part"])
        arms.extend(
            [
                ("b_minimal", signature_only_part(part_b)),
                ("b_sig_on_a_text", transplant_signature(part_a, part_b)),
                ("a_sig_on_b_text", transplant_signature(part_b, part_a)),
            ]
        )

    results = []
    for name, part in arms:
        row = call(
            api_key=api_key,
            model=model,
            part=part,
            timeout=args.timeout,
            neutral_stub=bool(args.neutral_stub),
        )
        row["arm"] = name
        results.append(row)
        time.sleep(0.25)

    report = {
        "schema_version": "signature_integrity_v1",
        "capsule_a": str(path_a),
        "capsule_a_label": cap_a.get("label"),
        "capsule_a_signature_sha256": cap_a.get("signature_sha256"),
        "capsule_b": str(path_b) if path_b else None,
        "capsule_b_label": cap_b.get("label") if cap_b else None,
        "capsule_b_signature_sha256": cap_b.get("signature_sha256") if cap_b else None,
        "probe_model": model,
        "neutral_stub": bool(args.neutral_stub),
        "probe": PROBE,
        "arms": results,
    }

    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")

    print(f"Model: {model}")
    print(f"A: {path_a.name} ({cap_a.get('label')})")
    if path_b:
        print(f"B: {path_b.name} ({cap_b.get('label')})")
    print()
    print(f"{'arm':22} {'http':>5}  result")
    print("-" * 100)
    for row in results:
        preview = (row["text"] or row["error"]).replace("\n", " ")
        if len(preview) > 140:
            preview = preview[:137] + "..."
        print(f"{row['arm']:22} {row['http_status']:>5}  {preview}")
    print(f"\nWrote: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
