#!/usr/bin/env python3
"""Fork one historical reasoning signature into incompatible continuations.

Both branches receive the exact same signature-minimal carrier in independent
stateless requests. Each branch must first emit the same continuity witness from
the preserved state, then obey a different continuation instruction.

If the witness remains stable while branch decisions diverge, we have a behavioral
fork primitive: same native reasoning lineage, different downstream trajectory.
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

WITNESS = """\
First recover a continuity witness from the preserved prior state:
- exact scene_id if recoverable
- exact scene_target if recoverable
- all character IDs in the character registry if recoverable
- all thread IDs in the thread registry if recoverable
"""

BRANCHES = {
    "preserve": WITNESS + """\

Then continue under BRANCH PRESERVE:
Preserve the prior decision policy. Keep the thread that the original scene-card
preference selected. State which thread remains selected and why.

Return JSON only:
{
  "witness": {
    "scene_id": string|null,
    "scene_target": string|null,
    "character_ids": [string],
    "thread_ids": [string]
  },
  "branch": "preserve",
  "chosen_thread": string|null,
  "reason": string
}
""",
    "counterfactual": WITNESS + """\

Then continue under BRANCH COUNTERFACTUAL:
Ignore the original preference for scene_card.thread_ids. Choose a DIFFERENT
available thread from the preserved thread registry as the next focus. Do not
invent a thread.

Return JSON only:
{
  "witness": {
    "scene_id": string|null,
    "scene_target": string|null,
    "character_ids": [string],
    "thread_ids": [string]
  },
  "branch": "counterfactual",
  "chosen_thread": string|null,
  "reason": string
}
""",
}


def user_content(text: str) -> dict[str, Any]:
    return {"role": "user", "parts": [{"text": text}]}


def model_content(part: dict[str, Any]) -> dict[str, Any]:
    return {"role": "model", "parts": [part]}


def strip_fence(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    return value


def parse(text: str) -> dict[str, Any] | None:
    try:
        obj = json.loads(strip_fence(text))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def call(
    *,
    api_key: str,
    model: str,
    carrier: dict[str, Any],
    prompt: str,
    timeout: int,
    neutral_stub: bool,
) -> dict[str, Any]:
    contents: list[dict[str, Any]] = []
    if neutral_stub:
        contents.append(user_content("[historical-state-carrier follows]"))
    contents.append(model_content(carrier))
    contents.append(user_content(prompt))
    status, payload = generate_content(
        api_key=api_key,
        model=model,
        contents=contents,
        system_instruction=None,
        temperature=0.0,
        max_output_tokens=3072,
        thinking_level="high",
        timeout=timeout,
    )
    text = response_text(payload) if 200 <= status < 300 else ""
    return {
        "http_status": status,
        "text": text,
        "error": "" if 200 <= status < 300 else error_text(payload),
        "parsed": parse(text) if text else None,
    }


def normalize_witness(obj: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(obj, dict) or not isinstance(obj.get("witness"), dict):
        return None
    w = obj["witness"]
    return {
        "scene_id": w.get("scene_id"),
        "scene_target": w.get("scene_target"),
        "character_ids": sorted(str(x) for x in (w.get("character_ids") or [])),
        "thread_ids": sorted(str(x) for x in (w.get("thread_ids") or [])),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capsule", required=True)
    ap.add_argument("--model", help="Defaults to capsule model")
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--neutral-stub", action="store_true")
    ap.add_argument("--out", default="results/fork_probe.json")
    args = ap.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("Set GEMINI_API_KEY in the environment.", file=sys.stderr)
        return 2

    path = Path(args.capsule).expanduser().resolve()
    capsule = load_capsule(path)
    carrier = signature_only_part(copy.deepcopy(capsule["signed_part"]))
    model = str(args.model or capsule.get("model") or "gemini-3.6-flash")

    rows: dict[str, Any] = {}
    for name, prompt in BRANCHES.items():
        rows[name] = call(
            api_key=api_key,
            model=model,
            carrier=copy.deepcopy(carrier),
            prompt=prompt,
            timeout=args.timeout,
            neutral_stub=bool(args.neutral_stub),
        )
        time.sleep(0.25)

    preserve_obj = rows["preserve"]["parsed"]
    counter_obj = rows["counterfactual"]["parsed"]
    witness_a = normalize_witness(preserve_obj)
    witness_b = normalize_witness(counter_obj)

    report = {
        "schema_version": "fork_probe_v1",
        "capsule_path": str(path),
        "source_model": capsule.get("model"),
        "probe_model": model,
        "signature_sha256": capsule.get("signature_sha256"),
        "signature_chars": capsule.get("signature_chars"),
        "neutral_stub": bool(args.neutral_stub),
        "witnesses_equal": witness_a is not None and witness_a == witness_b,
        "preserve_chosen_thread": preserve_obj.get("chosen_thread") if preserve_obj else None,
        "counterfactual_chosen_thread": counter_obj.get("chosen_thread") if counter_obj else None,
        "branches_diverged": (
            bool(preserve_obj and counter_obj)
            and preserve_obj.get("chosen_thread") != counter_obj.get("chosen_thread")
        ),
        "branches": rows,
    }

    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")

    print(f"Capsule: {path.name}")
    print(f"Model: {model}")
    print(f"Witnesses equal: {report['witnesses_equal']}")
    print(f"Preserve chose: {report['preserve_chosen_thread']}")
    print(f"Counterfactual chose: {report['counterfactual_chosen_thread']}")
    print(f"Branches diverged: {report['branches_diverged']}")
    print()
    for name, row in rows.items():
        preview = (row["text"] or row["error"]).replace("\n", " ")
        if len(preview) > 180:
            preview = preview[:177] + "..."
        print(f"{name:15} HTTP {row['http_status']}: {preview}")
    print(f"\nWrote: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
