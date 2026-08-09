#!/usr/bin/env python3
"""Query the same historical reasoning carrier from multiple semantic angles.

Run this only after historical_probe.py shows that the historical signature is
accepted and that signed_part differs meaningfully from text_only/probe_only.

Each question is run in a fresh stateless request, so no tomography answer can
contaminate a later question.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from thoughtlab.gemini_legacy import error_text, generate_content, response_text
from thoughtlab.historicalTests.capsule import load_capsule, strip_signature
from thoughtlab.historicalTests.probes import TOMOGRAPHY_PROBES


def user_content(text: str) -> dict[str, Any]:
    return {"role": "user", "parts": [{"text": text}]}


def model_content(part: dict[str, Any]) -> dict[str, Any]:
    return {"role": "model", "parts": [part]}


def call(
    *,
    api_key: str,
    model: str,
    part: dict[str, Any] | None,
    prompt: str,
    timeout: int,
    neutral_stub: bool,
) -> dict[str, Any]:
    contents: list[dict[str, Any]] = []
    if part is not None and neutral_stub:
        contents.append(user_content("[historical-state-carrier follows]"))
    if part is not None:
        contents.append(model_content(part))
    contents.append(user_content(prompt))
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
    ap.add_argument("--capsule", required=True)
    ap.add_argument("--model", help="Probe model; defaults to capsule model")
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--out", default="results/tomography.json")
    ap.add_argument("--neutral-stub", action="store_true")
    ap.add_argument(
        "--controls",
        action="store_true",
        help="Also run text-only and probe-only controls for every semantic slice.",
    )
    args = ap.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("Set GEMINI_API_KEY in the environment.", file=sys.stderr)
        return 2

    path = Path(args.capsule).expanduser().resolve()
    capsule = load_capsule(path)
    signed = copy.deepcopy(capsule["signed_part"])
    text_only = strip_signature(signed)
    model = str(args.model or capsule.get("model") or "gemini-3-flash-preview")

    results: dict[str, Any] = {}
    for probe_id, prompt in TOMOGRAPHY_PROBES.items():
        row: dict[str, Any] = {
            "signed_part": call(
                api_key=api_key,
                model=model,
                part=signed,
                prompt=prompt,
                timeout=args.timeout,
                neutral_stub=bool(args.neutral_stub),
            )
        }
        if args.controls:
            row["text_only"] = call(
                api_key=api_key,
                model=model,
                part=text_only,
                prompt=prompt,
                timeout=args.timeout,
                neutral_stub=bool(args.neutral_stub),
            )
            row["probe_only"] = call(
                api_key=api_key,
                model=model,
                part=None,
                prompt=prompt,
                timeout=args.timeout,
                neutral_stub=False,
            )
        results[probe_id] = row
        time.sleep(0.25)

    report = {
        "schema_version": "historical_tomography_v1",
        "capsule_path": str(path),
        "source_ref": capsule.get("source_ref"),
        "source_path": capsule.get("source_path"),
        "source_model": capsule.get("model"),
        "probe_model": model,
        "signature_sha256": capsule.get("signature_sha256"),
        "signature_chars": capsule.get("signature_chars"),
        "neutral_stub": bool(args.neutral_stub),
        "controls": bool(args.controls),
        "results": results,
    }

    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")

    for probe_id, row in results.items():
        result = row["signed_part"]
        text = result["text"] or result["error"]
        preview = text.replace("\n", " ")
        if len(preview) > 150:
            preview = preview[:147] + "..."
        print(f"{probe_id:15} HTTP {result['http_status']}: {preview}")
    print(f"\nWrote: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
