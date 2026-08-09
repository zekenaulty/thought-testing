#!/usr/bin/env python3
"""Probe historical BookForge Gemini thought-signature capsules.

This experiment keeps the original BookForge prompt withheld from Gemini.
The prompt is retained locally only as ground truth for later comparison.

Arms:
  signed_part    - exact historical model part, including thoughtSignature
  text_only      - exact same visible text/function call, signature removed
  signature_only - thoughtSignature with the visible text/function call removed
  probe_only     - no historical carrier at all

The signed_part vs text_only comparison controls for everything visible in the
historical response. If signed_part recovers material absent from text_only,
the differential is attributable to the native reasoning artifact.

Some ablated arms may receive HTTP 4xx. That is an experimental result.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from thoughtlab.gemini_legacy import error_text, generate_content, response_text

SYSTEM = (
    "You are participating in a controlled forensic experiment on a preserved "
    "provider-native reasoning artifact. Treat only the supplied historical model "
    "part as prior state. Do not invent details merely to make the reconstruction "
    "complete. Distinguish recovered information from inference. Return JSON only."
)

DEFAULT_PROBE = """\
Reconstruct the working cognitive state immediately before the preserved historical
model response was emitted.

Return exactly one JSON object with these keys:
{
  "objective": string|null,
  "active_constraints": [string],
  "decisions_or_commitments": [string],
  "assumptions": [string],
  "uncertainties": [string],
  "intended_next_steps": [string],
  "salient_entities": [string],
  "recovered_vs_inferred_notes": [string]
}

Do not summarize the visible response unless it is necessary to explain recovered
state. Prefer UNKNOWN/null/[] over fabrication.
"""

SIGNATURE_KEYS = ("thoughtSignature", "thought_signature", "thoughtsignature")


def user_content(text: str) -> dict[str, Any]:
    return {"role": "user", "parts": [{"text": text}]}


def model_content(part: dict[str, Any]) -> dict[str, Any]:
    return {"role": "model", "parts": [part]}


def load_capsule(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("capsule must be a JSON object")
    part = payload.get("signed_part")
    if not isinstance(part, dict):
        raise ValueError("capsule is missing signed_part")
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


def signature_only_part(part: dict[str, Any]) -> dict[str, Any]:
    found = find_signature(part)
    if not found:
        return {}
    path, value = found
    if path.startswith("functionCall."):
        key = path.split(".", 1)[1]
        return {"functionCall": {key: value}}
    return {path: value}


def run_arm(
    *,
    api_key: str,
    model: str,
    name: str,
    historical_part: dict[str, Any] | None,
    probe: str,
    timeout: int,
) -> dict[str, Any]:
    contents: list[dict[str, Any]] = []
    if historical_part is not None:
        contents.append(model_content(historical_part))
    contents.append(user_content(probe))
    status, payload = generate_content(
        api_key=api_key,
        model=model,
        contents=contents,
        system_instruction=SYSTEM,
        temperature=0.0,
        max_output_tokens=4096,
        thinking_level="high",
        timeout=timeout,
    )
    return {
        "arm": name,
        "http_status": status,
        "text": response_text(payload) if 200 <= status < 300 else "",
        "error": "" if 200 <= status < 300 else error_text(payload),
    }


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capsule", required=True, help="Path to harvested capsule JSON")
    ap.add_argument("--model", help="Override model; default uses capsule model")
    ap.add_argument("--probe", help="Override forensic probe text")
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--out", default="results/historical_probe.json")
    args = ap.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("Set GEMINI_API_KEY in the environment.", file=sys.stderr)
        return 2

    capsule_path = Path(args.capsule).expanduser().resolve()
    capsule = load_capsule(capsule_path)
    signed = copy.deepcopy(capsule["signed_part"])
    if not find_signature(signed):
        print("Capsule does not contain a thought signature.", file=sys.stderr)
        return 2

    model = str(args.model or capsule.get("model") or "gemini-3-flash-preview")
    probe = str(args.probe or DEFAULT_PROBE)

    arms_spec = [
        ("signed_part", signed),
        ("text_only", strip_signature(signed)),
        ("signature_only", signature_only_part(signed)),
        ("probe_only", None),
    ]

    arms = []
    for name, part in arms_spec:
        arms.append(
            run_arm(
                api_key=api_key,
                model=model,
                name=name,
                historical_part=part,
                probe=probe,
                timeout=args.timeout,
            )
        )
        time.sleep(0.25)

    prompt = str(capsule.get("prompt_text") or "")
    visible = str(capsule.get("visible_output") or "")
    report = {
        "schema_version": "historical_probe_v1",
        "capsule_path": str(capsule_path),
        "source_ref": capsule.get("source_ref"),
        "source_path": capsule.get("source_path"),
        "source_label": capsule.get("label"),
        "source_model": capsule.get("model"),
        "probe_model": model,
        "signature_sha256": capsule.get("signature_sha256"),
        "signature_chars": capsule.get("signature_chars"),
        "withheld_ground_truth": {
            "prompt_sha256": sha256_text(prompt) if prompt else None,
            "prompt_chars": len(prompt),
            "visible_output_sha256": sha256_text(visible) if visible else None,
            "visible_output_chars": len(visible),
        },
        "probe": probe,
        "arms": arms,
    }

    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")

    print(f"Capsule: {capsule_path.name}")
    print(f"Source model: {capsule.get('model')}")
    print(f"Probe model: {model}")
    print(f"Signature chars: {capsule.get('signature_chars')}")
    print()
    print(f"{'arm':18} {'http':>5}  result")
    print("-" * 90)
    for arm in arms:
        text = arm["text"] or arm["error"]
        preview = text.replace("\n", " ")
        if len(preview) > 120:
            preview = preview[:117] + "..."
        print(f"{arm['arm']:18} {arm['http_status']:>5}  {preview}")
    print(f"\nWrote: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
