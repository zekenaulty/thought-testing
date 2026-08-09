#!/usr/bin/env python3
"""Ablation probe for historical BookForge Gemini thought-signature carriers.

The original BookForge prompt remains withheld from Gemini. It is kept only as
local ground truth. Each arm is a separate HTTP request.

Arms:
  signed_part         exact historical model part including thoughtSignature
  text_only           same visible carrier with signature removed
  signature_blank     same signed carrier with visible payload erased
  signature_minimal   signature metadata with almost all carrier payload removed
  probe_only          no historical carrier

For legacy generateContent, some carrier mutilations may receive HTTP 4xx.
That is experimental evidence, not necessarily a harness failure.
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
from thoughtlab.historicalTests.capsule import (
    erase_visible_payload_keep_signature,
    load_capsule,
    signature_only_part,
    strip_signature,
)
from thoughtlab.historicalTests.probes import BASELINE_PROBE


def user_content(text: str) -> dict[str, Any]:
    return {"role": "user", "parts": [{"text": text}]}


def model_content(part: dict[str, Any]) -> dict[str, Any]:
    return {"role": "model", "parts": [part]}


def run_arm(
    *,
    api_key: str,
    model: str,
    name: str,
    historical_part: dict[str, Any] | None,
    probe: str,
    timeout: int,
    neutral_stub: bool,
) -> dict[str, Any]:
    contents: list[dict[str, Any]] = []
    # Some legacy Gemini endpoints are stricter about history beginning with a
    # model role. --neutral-stub lets us satisfy alternation without reintroducing
    # the original BookForge prompt.
    if historical_part is not None and neutral_stub:
        contents.append(user_content("[historical-state-carrier follows]"))
    if historical_part is not None:
        contents.append(model_content(historical_part))
    contents.append(user_content(probe))

    status, payload = generate_content(
        api_key=api_key,
        model=model,
        contents=contents,
        system_instruction=None,  # minimize new semantic contamination
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
    ap.add_argument("--model", help="Probe model; defaults to capsule model")
    ap.add_argument("--probe", help="Override forensic probe text")
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--out", default="results/historical_probe.json")
    ap.add_argument(
        "--neutral-stub",
        action="store_true",
        help="Prepend a content-free user stub before the historical model part.",
    )
    args = ap.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("Set GEMINI_API_KEY in the environment.", file=sys.stderr)
        return 2

    capsule_path = Path(args.capsule).expanduser().resolve()
    capsule = load_capsule(capsule_path)
    signed = copy.deepcopy(capsule["signed_part"])
    model = str(args.model or capsule.get("model") or "gemini-3-flash-preview")
    probe = str(args.probe or BASELINE_PROBE)

    arms_spec = [
        ("signed_part", signed),
        ("text_only", strip_signature(signed)),
        ("signature_blank", erase_visible_payload_keep_signature(signed)),
        ("signature_minimal", signature_only_part(signed)),
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
                neutral_stub=bool(args.neutral_stub),
            )
        )
        time.sleep(0.25)

    prompt = str(capsule.get("prompt_text") or "")
    visible = str(capsule.get("visible_output") or "")
    report = {
        "schema_version": "historical_probe_v2",
        "capsule_path": str(capsule_path),
        "source_ref": capsule.get("source_ref"),
        "source_path": capsule.get("source_path"),
        "source_label": capsule.get("label"),
        "source_model": capsule.get("model"),
        "probe_model": model,
        "signature_sha256": capsule.get("signature_sha256"),
        "signature_chars": capsule.get("signature_chars"),
        "neutral_stub": bool(args.neutral_stub),
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
    print(f"Neutral stub: {bool(args.neutral_stub)}")
    print()
    print(f"{'arm':20} {'http':>5}  result")
    print("-" * 96)
    for arm in arms:
        text = arm["text"] or arm["error"]
        preview = text.replace("\n", " ")
        if len(preview) > 130:
            preview = preview[:127] + "..."
        print(f"{arm['arm']:20} {arm['http_status']:>5}  {preview}")
    print(f"\nWrote: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
