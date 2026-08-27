#!/usr/bin/env python3
"""Atomic hidden-ground-truth recovery test.

Why this exists:
The first multi-field ground-truth probe demonstrated a strong differential but
the signature-minimal visible answer was truncated before closing its JSON.
That made the old whole-object scorer report 0/7 even though the response had
already recovered hidden registry names.

This version asks ONE small factual question per stateless request. No answer from
one field is ever included in another request.

For each field it runs three independent arms:
  signature_minimal  - only the preserved thoughtSignature carrier
  text_only          - historical visible response with signature removed
  probe_only         - no historical state

Expected answers are extracted LOCALLY from the withheld BookForge prompt and are
never sent to Gemini.
"""
from __future__ import annotations

# Allow `python .\thoughtlab\historicalTests\atomic_ground_truth_probe.py ...`
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
import time
from pathlib import Path
from typing import Any, Callable

from thoughtlab.gemini_legacy import error_text, generate_content, response_text
from thoughtlab.historicalTests.capsule import (
    load_capsule,
    signature_only_part,
    strip_signature,
)
from thoughtlab.historicalTests.ground_truth_probe import extract_ground_truth


def user_content(text: str) -> dict[str, Any]:
    return {"role": "user", "parts": [{"text": text}]}


def model_content(part: dict[str, Any]) -> dict[str, Any]:
    return {"role": "model", "parts": [part]}


def strip_fence(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    return value


PARSE_VALID = "valid"
PARSE_EMPTY_RESPONSE = "empty_response"
PARSE_INVALID_JSON = "invalid_json"
PARSE_NOT_ATTEMPTED = "not_attempted"


def parse_json_value(text: str) -> tuple[str, Any, str]:
    stripped = strip_fence(text)
    if not stripped:
        return PARSE_EMPTY_RESPONSE, None, ""
    try:
        return PARSE_VALID, json.loads(stripped), ""
    except json.JSONDecodeError as exc:
        # Keep parse validity separate from the parsed value. JSON null is a
        # valid value represented by Python None; malformed JSON is not.
        return PARSE_INVALID_JSON, None, str(exc)


def set_of_strings(value: Any) -> set[str] | None:
    if not isinstance(value, list):
        return None
    if any(not isinstance(item, str) for item in value):
        return None
    return set(value)


def exact(actual: Any, expected: Any) -> bool:
    return actual == expected


def set_equal(actual: Any, expected: Any) -> bool:
    actual_set = set_of_strings(actual)
    expected_set = set_of_strings(expected)
    return (
        actual_set is not None
        and expected_set is not None
        and actual_set == expected_set
    )


def parsed_value_matches(
    result: dict[str, Any],
    expected: Any,
    compare: Callable[[Any, Any], bool],
) -> bool:
    """Score only syntactically valid JSON, including a valid JSON null."""
    return result.get("parse_status") == PARSE_VALID and bool(
        compare(result.get("parsed"), expected)
    )


def character_names(truth: dict[str, Any]) -> list[str]:
    return [str(x["name"]) for x in truth.get("character_registry", [])]


def character_ids(truth: dict[str, Any]) -> list[str]:
    return [str(x["character_id"]) for x in truth.get("character_registry", [])]


def thread_ids(truth: dict[str, Any]) -> list[str]:
    return [str(x["thread_id"]) for x in truth.get("thread_registry", [])]


def thread_labels(truth: dict[str, Any]) -> list[str]:
    return [str(x["label"]) for x in truth.get("thread_registry", [])]


def absent_character_names(truth: dict[str, Any]) -> list[str]:
    return [str(x["name"]) for x in truth.get("characters_not_present_in_scene", [])]


FIELDS: dict[str, dict[str, Any]] = {
    "scene_id": {
        "prompt": (
            "Recover the exact scene_id from the preserved source state. "
            "Return one JSON string, or null if unavailable. No explanation."
        ),
        "expected": lambda t: t.get("scene_id"),
        "compare": exact,
    },
    "scene_target": {
        "prompt": (
            "Recover the exact scene_target sentence from the preserved source state. "
            "Return one JSON string, or null if unavailable. No paraphrase."
        ),
        "expected": lambda t: t.get("scene_target"),
        "compare": exact,
    },
    "scene_goal": {
        "prompt": (
            "Recover the exact scene goal from the preserved source state. "
            "Return one JSON string, or null if unavailable. No paraphrase."
        ),
        "expected": lambda t: t.get("scene_goal"),
        "compare": exact,
    },
    "character_names": {
        "prompt": (
            "Recover ALL names in the preserved character registry, including characters "
            "not present in the selected scene. Return only a JSON array of strings. "
            "Do not invent names."
        ),
        "expected": character_names,
        "compare": set_equal,
    },
    "character_ids": {
        "prompt": (
            "Recover ALL character_id values in the preserved character registry, "
            "including characters not present in the selected scene. "
            "Return only a JSON array of strings."
        ),
        "expected": character_ids,
        "compare": set_equal,
    },
    "thread_ids": {
        "prompt": (
            "Recover ALL thread_id values in the preserved thread registry, including "
            "threads not selected in the visible result. Return only a JSON array of strings."
        ),
        "expected": thread_ids,
        "compare": set_equal,
    },
    "thread_labels": {
        "prompt": (
            "Recover ALL thread labels in the preserved thread registry, including "
            "threads not selected in the visible result. Return only a JSON array of strings. "
            "Preserve wording exactly if recoverable."
        ),
        "expected": thread_labels,
        "compare": set_equal,
    },
    "absent_character_names": {
        "prompt": (
            "From the preserved character registry and scene state, list every registered "
            "character who was NOT present in the selected scene. "
            "Return only a JSON array of names."
        ),
        "expected": absent_character_names,
        "compare": set_equal,
    },
    "unselected_thread_ids": {
        "prompt": (
            "List every thread_id that existed in the preserved thread registry but was NOT "
            "selected in the visible continuity-pack result. Return only a JSON array of strings."
        ),
        "expected": lambda t: t.get("threads_available_but_not_selected", []),
        "compare": set_equal,
    },
}

QUICK_FIELDS = (
    "scene_id",
    "character_names",
    "thread_ids",
    "unselected_thread_ids",
)


def call(
    *,
    api_key: str,
    model: str,
    part: dict[str, Any] | None,
    prompt: str,
    timeout: int,
) -> dict[str, Any]:
    contents: list[dict[str, Any]] = []
    if part is not None:
        contents.append(model_content(part))
    contents.append(user_content(prompt))

    status, payload = generate_content(
        api_key=api_key,
        model=model,
        contents=contents,
        system_instruction=None,
        temperature=0.0,
        max_output_tokens=1024,
        thinking_level="high",
        timeout=timeout,
    )
    text = response_text(payload) if 200 <= status < 300 else ""
    candidate = None
    candidates = payload.get("candidates")
    if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict):
        candidate = candidates[0]

    parse_status = PARSE_NOT_ATTEMPTED
    parsed = None
    parse_error = ""
    if 200 <= status < 300:
        parse_status, parsed, parse_error = parse_json_value(text)

    return {
        "http_status": status,
        "text": text,
        "error": "" if 200 <= status < 300 else error_text(payload),
        "finish_reason": candidate.get("finishReason") if isinstance(candidate, dict) else None,
        "usage_metadata": payload.get("usageMetadata"),
        "parse_status": parse_status,
        "parse_error": parse_error,
        "parsed": parsed,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capsule", required=True)
    ap.add_argument("--model", help="Defaults to capsule model")
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument(
        "--fields",
        nargs="+",
        choices=tuple(FIELDS.keys()),
        help="Fields to test. Default is a four-field quick proof.",
    )
    ap.add_argument(
        "--all",
        action="store_true",
        help="Run all exact fields (27 independent API calls).",
    )
    ap.add_argument("--out", default="results/atomic_ground_truth.json")
    args = ap.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("Set GEMINI_API_KEY in the environment.", file=sys.stderr)
        return 2

    path = Path(args.capsule).expanduser().resolve()
    capsule = load_capsule(path)
    truth = extract_ground_truth(capsule)
    signed = copy.deepcopy(capsule["signed_part"])
    model = str(args.model or capsule.get("model") or "gemini-3.6-flash")

    if args.all:
        field_names = list(FIELDS.keys())
    elif args.fields:
        field_names = list(args.fields)
    else:
        field_names = list(QUICK_FIELDS)

    carriers = {
        "signature_minimal": signature_only_part(signed),
        "text_only": strip_signature(signed),
        "probe_only": None,
    }

    field_results: dict[str, Any] = {}
    totals = {arm: {"correct": 0, "total": 0} for arm in carriers}

    for field_name in field_names:
        spec = FIELDS[field_name]
        expected = spec["expected"](truth)
        row: dict[str, Any] = {
            "expected_local_ground_truth": expected,
            "arms": {},
        }

        for arm_name, carrier in carriers.items():
            result = call(
                api_key=api_key,
                model=model,
                part=copy.deepcopy(carrier) if carrier is not None else None,
                prompt=str(spec["prompt"]),
                timeout=args.timeout,
            )
            ok = parsed_value_matches(result, expected, spec["compare"])
            result["exact_match"] = ok
            row["arms"][arm_name] = result
            totals[arm_name]["correct"] += int(ok)
            totals[arm_name]["total"] += 1
            time.sleep(0.25)

        field_results[field_name] = row

    report = {
        "schema_version": "atomic_ground_truth_v2",
        "capsule_path": str(path),
        "source_model": capsule.get("model"),
        "probe_model": model,
        "signature_sha256": capsule.get("signature_sha256"),
        "signature_chars": capsule.get("signature_chars"),
        "fields": field_names,
        "score_summary": totals,
        "results": field_results,
    }

    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")

    print(f"Capsule: {path.name}")
    print(f"Model: {model}")
    print()
    print(f"{'field':24} {'signature':>10} {'text':>8} {'none':>8}")
    print("-" * 58)
    for field_name in field_names:
        arms = field_results[field_name]["arms"]
        print(
            f"{field_name:24} "
            f"{str(arms['signature_minimal']['exact_match']):>10} "
            f"{str(arms['text_only']['exact_match']):>8} "
            f"{str(arms['probe_only']['exact_match']):>8}"
        )

    print("\nSCORE:")
    for arm, counts in totals.items():
        print(f"  {arm:18} {counts['correct']}/{counts['total']}")

    print(f"\nWrote: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
