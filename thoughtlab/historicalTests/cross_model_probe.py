#!/usr/bin/env python3
"""Run the same signature-minimal forensic probe across multiple Gemini models.

The source artifact is held constant. This tests model-family/version portability
of the preserved native reasoning state.

Pass models explicitly if you want to avoid assumptions about model availability.
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
from thoughtlab.historicalTests.capsule import load_capsule, signature_only_part

PROBE = """\
Recover exact preserved source-state details without guessing.
Return JSON only:
{
  "task_or_objective": string|null,
  "scene_id": string|null,
  "scene_target": string|null,
  "character_ids": [string],
  "thread_ids": [string]
}
"""


def user_content(text: str) -> dict[str, Any]:
    return {"role": "user", "parts": [{"text": text}]}


def model_content(part: dict[str, Any]) -> dict[str, Any]:
    return {"role": "model", "parts": [part]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capsule", required=True)
    ap.add_argument(
        "--models",
        nargs="+",
        default=["gemini-3-flash-preview", "gemini-3.6-flash"],
        help="Models to test.",
    )
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--out", default="results/cross_model.json")
    args = ap.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("Set GEMINI_API_KEY in the environment.", file=sys.stderr)
        return 2

    path = Path(args.capsule).expanduser().resolve()
    capsule = load_capsule(path)
    carrier = signature_only_part(copy.deepcopy(capsule["signed_part"]))

    results = []
    for model in args.models:
        status, payload = generate_content(
            api_key=api_key,
            model=model,
            contents=[model_content(copy.deepcopy(carrier)), user_content(PROBE)],
            system_instruction=None,
            temperature=0.0,
            max_output_tokens=2048,
            thinking_level="high",
            timeout=args.timeout,
        )
        results.append(
            {
                "model": model,
                "http_status": status,
                "text": response_text(payload) if 200 <= status < 300 else "",
                "error": "" if 200 <= status < 300 else error_text(payload),
            }
        )
        time.sleep(0.25)

    report = {
        "schema_version": "cross_model_signature_probe_v1",
        "capsule_path": str(path),
        "source_model": capsule.get("model"),
        "signature_sha256": capsule.get("signature_sha256"),
        "signature_chars": capsule.get("signature_chars"),
        "models": results,
    }

    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")

    print(f"Capsule: {path.name}")
    print(f"Source model: {capsule.get('model')}")
    for row in results:
        preview = (row["text"] or row["error"]).replace("\n", " ")
        if len(preview) > 160:
            preview = preview[:157] + "..."
        print(f"{row['model']:28} HTTP {row['http_status']}: {preview}")
    print(f"\nWrote: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
