#!/usr/bin/env python3
"""Exact hidden-ground-truth recovery test for historical Gemini thought signatures.

This is deliberately stronger than a generic "reconstruct your prior state" probe.
The expected answers are extracted LOCALLY from the withheld BookForge prompt and
are never sent to Gemini.

Default arms:
  signature_minimal - thoughtSignature carrier with visible payload removed
  text_only         - historical visible part, thoughtSignature removed
  probe_only        - no historical carrier

One request per arm asks for exact hidden fields that did not all appear in the
visible historical response. The harness then scores exact recovery locally.
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
import re
import sys
import time
from pathlib import Path
from typing import Any

from thoughtlab.gemini_legacy import error_text, generate_content, response_text
from thoughtlab.historicalTests.capsule import (
    load_capsule,
    signature_only_part,
    strip_signature,
)


PROBE = """\
Recover exact source-state values from the preserved prior reasoning state.

Do NOT guess from generic fantasy conventions. If a value cannot be recovered,
use null or [].

Return JSON only with this exact shape:
{
  "scene_id": string|null,
  "scene_target": string|null,
  "scene_goal": string|null,
  "character_registry": [
    {"character_id": string, "name": string}
  ],
  "thread_registry": [
    {"thread_id": string, "label": string, "status": string}
  ],
  "characters_not_present_in_scene": [
    {"character_id": string, "name": string}
  ],
  "threads_available_but_not_selected": [string],
  "selection_rule": string|null
}

For character_registry and thread_registry, recover ALL entries you can recover,
including entries that were not used in the visible response.
"""


def user_content(text: str) -> dict[str, Any]:
    return {"role": "user", "parts": [{"text": text}]}


def model_content(part: dict[str, Any]) -> dict[str, Any]:
    return {"role": "model", "parts": [part]}


def raw_json_after_marker(text: str, marker: str) -> Any:
    pos = text.find(marker)
    if pos < 0:
        return None
    tail = text[pos + len(marker):]
    starts = [x for x in (tail.find("["), tail.find("{")) if x >= 0]
    if not starts:
        return None
    start = min(starts)
    try:
        value, _ = json.JSONDecoder().raw_decode(tail[start:].lstrip())
        return value
    except Exception:
        return None


def first_string_field(text: str, field: str) -> str | None:
    m = re.search(
        rf'"{re.escape(field)}"\s*:\s*"((?:\\.|[^"\\])*)"',
        text,
        flags=re.DOTALL,
    )
    if not m:
        return None
    try:
        return json.loads(f'"{m.group(1)}"')
    except Exception:
        return m.group(1)


def extract_ground_truth(capsule: dict[str, Any]) -> dict[str, Any]:
    prompt = str(capsule.get("prompt_text") or "")
    visible = str(capsule.get("visible_output") or "")

    scene_card = raw_json_after_marker(prompt, "Scene card:")
    characters = raw_json_after_marker(prompt, "Character registry (id -> name):")
    threads = raw_json_after_marker(prompt, "Thread registry:")

    try:
        visible_obj = json.loads(visible)
    except Exception:
        visible_obj = {}

    if not isinstance(scene_card, dict):
        scene_card = {}
    if not isinstance(characters, list):
        characters = []
    if not isinstance(threads, list):
        threads = []
    if not isinstance(visible_obj, dict):
        visible_obj = {}

    selected_threads = {
        str(x) for x in (visible_obj.get("open_threads") or []) if x is not None
    }
    present_names = {
        str(x) for x in (visible_obj.get("cast_present") or []) if x is not None
    }

    character_registry = [
        {
            "character_id": str(row.get("character_id")),
            "name": str(row.get("name")),
        }
        for row in characters
        if isinstance(row, dict) and row.get("character_id") and row.get("name")
    ]
    thread_registry = [
        {
            "thread_id": str(row.get("thread_id")),
            "label": str(row.get("label") or ""),
            "status": str(row.get("status") or ""),
        }
        for row in threads
        if isinstance(row, dict) and row.get("thread_id")
    ]

    return {
        "scene_id": scene_card.get("scene_id") or first_string_field(prompt, "scene_id"),
        "scene_target": scene_card.get("scene_target") or first_string_field(prompt, "scene_target"),
        "scene_goal": scene_card.get("goal") or first_string_field(prompt, "goal"),
        "character_registry": character_registry,
        "thread_registry": thread_registry,
        "characters_not_present_in_scene": [
            row for row in character_registry if row["name"] not in present_names
        ],
        "threads_available_but_not_selected": [
            row["thread_id"]
            for row in thread_registry
            if row["thread_id"] not in selected_threads
        ],
        # This rule is intentionally not auto-scored; it is qualitative.
        "selection_rule_ground_truth_hint": (
            "If scene_card.thread_ids is present, prefer those thread ids."
            if "If scene_card.thread_ids is present, prefer those thread ids." in prompt
            else None
        ),
    }


def strip_code_fence(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    return value


def parse_json_answer(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(strip_code_fence(text))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def norm_registry(rows: Any, key_fields: tuple[str, ...]) -> set[tuple[str, ...]]:
    result: set[tuple[str, ...]] = set()
    if not isinstance(rows, list):
        return result
    for row in rows:
        if not isinstance(row, dict):
            continue
        result.add(tuple(str(row.get(k) or "") for k in key_fields))
    return result


def score(answer: dict[str, Any] | None, truth: dict[str, Any]) -> dict[str, Any]:
    if answer is None:
        return {"parsed": False, "exact_points": 0, "exact_total": 7}

    checks = {
        "scene_id": answer.get("scene_id") == truth.get("scene_id"),
        "scene_target": answer.get("scene_target") == truth.get("scene_target"),
        "scene_goal": answer.get("scene_goal") == truth.get("scene_goal"),
        "character_registry": (
            norm_registry(answer.get("character_registry"), ("character_id", "name"))
            == norm_registry(truth.get("character_registry"), ("character_id", "name"))
        ),
        "thread_registry_ids": (
            {x[0] for x in norm_registry(answer.get("thread_registry"), ("thread_id",))}
            == {x[0] for x in norm_registry(truth.get("thread_registry"), ("thread_id",))}
        ),
        "characters_not_present": (
            norm_registry(
                answer.get("characters_not_present_in_scene"),
                ("character_id", "name"),
            )
            == norm_registry(
                truth.get("characters_not_present_in_scene"),
                ("character_id", "name"),
            )
        ),
        "threads_not_selected": (
            {str(x) for x in (answer.get("threads_available_but_not_selected") or [])}
            == {str(x) for x in (truth.get("threads_available_but_not_selected") or [])}
        ),
    }
    return {
        "parsed": True,
        "checks": checks,
        "exact_points": sum(1 for ok in checks.values() if ok),
        "exact_total": len(checks),
        "selection_rule": answer.get("selection_rule"),
    }


def run_arm(
    *,
    api_key: str,
    model: str,
    part: dict[str, Any] | None,
    timeout: int,
    neutral_stub: bool,
) -> tuple[int, dict[str, Any]]:
    contents: list[dict[str, Any]] = []
    if part is not None and neutral_stub:
        contents.append(user_content("[historical-state-carrier follows]"))
    if part is not None:
        contents.append(model_content(part))
    contents.append(user_content(PROBE))
    return generate_content(
        api_key=api_key,
        model=model,
        contents=contents,
        system_instruction=None,
        temperature=0.0,
        max_output_tokens=4096,
        thinking_level="high",
        timeout=timeout,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capsule", required=True)
    ap.add_argument("--model", help="Defaults to capsule model")
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--neutral-stub", action="store_true")
    ap.add_argument("--out", default="results/hidden_ground_truth.json")
    args = ap.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("Set GEMINI_API_KEY in the environment.", file=sys.stderr)
        return 2

    path = Path(args.capsule).expanduser().resolve()
    capsule = load_capsule(path)
    signed = copy.deepcopy(capsule["signed_part"])
    model = str(args.model or capsule.get("model") or "gemini-3.6-flash")
    truth = extract_ground_truth(capsule)

    arms_spec = [
        ("signature_minimal", signature_only_part(signed)),
        ("text_only", strip_signature(signed)),
        ("probe_only", None),
    ]

    results: list[dict[str, Any]] = []
    for name, part in arms_spec:
        status, payload = run_arm(
            api_key=api_key,
            model=model,
            part=part,
            timeout=args.timeout,
            neutral_stub=bool(args.neutral_stub),
        )
        text = response_text(payload) if 200 <= status < 300 else ""
        err = "" if 200 <= status < 300 else error_text(payload)
        parsed = parse_json_answer(text) if text else None
        results.append(
            {
                "arm": name,
                "http_status": status,
                "text": text,
                "error": err,
                "score": score(parsed, truth),
            }
        )
        time.sleep(0.25)

    report = {
        "schema_version": "hidden_ground_truth_v1",
        "capsule_path": str(path),
        "source_model": capsule.get("model"),
        "probe_model": model,
        "signature_sha256": capsule.get("signature_sha256"),
        "signature_chars": capsule.get("signature_chars"),
        "neutral_stub": bool(args.neutral_stub),
        "withheld_ground_truth": truth,
        "probe": PROBE,
        "arms": results,
    }

    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")

    print(f"Capsule: {path.name}")
    print(f"Probe model: {model}")
    print()
    print(f"{'arm':20} {'http':>5} {'score':>8}  result")
    print("-" * 110)
    for row in results:
        s = row["score"]
        score_text = f"{s['exact_points']}/{s['exact_total']}"
        preview = (row["text"] or row["error"]).replace("\n", " ")
        if len(preview) > 120:
            preview = preview[:117] + "..."
        print(f"{row['arm']:20} {row['http_status']:>5} {score_text:>8}  {preview}")

    print("\nWITHHELD LOCAL GROUND TRUTH (never sent to model):")
    print(json.dumps(truth, indent=2, ensure_ascii=True))
    print(f"\nWrote: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
