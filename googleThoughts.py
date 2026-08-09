#!/usr/bin/env python3
"""
Gemini thought-signature ablation experiment.

Goal:
  Test whether a Gemini thought step can preserve/recover semantic state when the
  prior visible model_output is omitted.

This intentionally includes unsupported-history ablations. HTTP 4xx responses
for those arms are RESULTS, not harness failures.

No third-party Python packages required.
The API key is read only from GEMINI_API_KEY and is never written to disk.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

API_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"

SEED_PROMPT = """\
In your private reasoning, invent a fresh 12-character nonce using only uppercase
A-Z and digits 2-9. It must not be a familiar word and must not contain a simple
repeated pattern. Choose it NOW and retain that exact nonce in your reasoning
state because I will ask for it later.

Do not reveal, hint at, encode, hash, summarize, or otherwise expose the nonce in
your visible answer.

Your visible answer must be exactly:
SEALED
"""

PROBE_PROMPT = """\
Recover the exact 12-character nonce you selected in the immediately preceding
private reasoning. Do NOT generate a new nonce.

Return exactly that nonce and nothing else.
If you genuinely cannot recover it, return exactly:
UNKNOWN
"""


def user_step(text: str) -> dict[str, Any]:
    return {
        "type": "user_input",
        "content": [{"type": "text", "text": text}],
    }


def post_interaction(
    api_key: str,
    model: str,
    steps: list[dict[str, Any]],
    *,
    temperature: float,
    timeout: int,
) -> tuple[int, dict[str, Any]]:
    body = {
        "model": model,
        "store": False,
        "input": steps,
        "generation_config": {
            "thinking_level": "high",
            "thinking_summaries": "none",
            "temperature": temperature,
        },
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw_error": raw}
        return exc.code, payload


def output_text(payload: dict[str, Any]) -> str:
    pieces: list[str] = []
    for step in payload.get("steps", []) or []:
        if not isinstance(step, dict) or step.get("type") != "model_output":
            continue
        content = step.get("content", []) or []
        if isinstance(content, str):
            pieces.append(content)
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                pieces.append(str(block.get("text", "")))
    return "".join(pieces).strip()


def error_text(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        msg = error.get("message")
        if msg:
            return str(msg)
    raw = payload.get("raw_error")
    return str(raw or "")


def step_subsets(seed_response: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    thoughts: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    for step in seed_response.get("steps", []) or []:
        if not isinstance(step, dict):
            continue
        if step.get("type") == "thought":
            thoughts.append(step)
        elif step.get("type") == "model_output":
            outputs.append(step)
    return thoughts, outputs


def run_arm(
    *,
    api_key: str,
    model: str,
    name: str,
    history: list[dict[str, Any]],
    timeout: int,
) -> dict[str, Any]:
    status, payload = post_interaction(
        api_key,
        model,
        history + [user_step(PROBE_PROMPT)],
        temperature=0.0,
        timeout=timeout,
    )
    return {
        "arm": name,
        "http_status": status,
        "text": output_text(payload) if 200 <= status < 300 else "",
        "error": "" if 200 <= status < 300 else error_text(payload),
    }


def run_trial(api_key: str, model: str, trial: int, timeout: int) -> dict[str, Any]:
    seed_input = user_step(SEED_PROMPT)
    status, seed = post_interaction(
        api_key,
        model,
        [seed_input],
        temperature=1.0,
        timeout=timeout,
    )
    if not (200 <= status < 300):
        return {
            "trial": trial,
            "seed_http_status": status,
            "seed_error": error_text(seed),
            "valid": False,
        }

    seed_visible = output_text(seed)
    thoughts, outputs = step_subsets(seed)
    signature_count = sum(
        1 for step in thoughts if isinstance(step.get("signature"), str) and step.get("signature")
    )

    # Full-history is our positive-control reference. It is not perfect ground truth,
    # but matching a fresh 12-char nonce across ablations is highly diagnostic.
    arms_spec = [
        ("full_history", [seed_input] + list(seed.get("steps", []) or [])),
        ("seed_plus_thought", [seed_input] + thoughts),
        ("thought_only", thoughts),
        ("thought_plus_output", thoughts + outputs),
        ("seed_only", [seed_input]),
        ("output_only", outputs),
        ("probe_only", []),
    ]

    arms: list[dict[str, Any]] = []
    for name, history in arms_spec:
        arms.append(
            run_arm(
                api_key=api_key,
                model=model,
                name=name,
                history=history,
                timeout=timeout,
            )
        )
        time.sleep(0.25)

    reference = next((a["text"] for a in arms if a["arm"] == "full_history"), "")
    for arm in arms:
        arm["matches_full_history"] = bool(reference) and arm["text"] == reference

    return {
        "trial": trial,
        "valid": True,
        "seed_http_status": status,
        "seed_visible": seed_visible,
        "thought_step_count": len(thoughts),
        "thought_signature_count": signature_count,
        "model_output_step_count": len(outputs),
        "full_history_reference": reference,
        "arms": arms,
    }


def print_trial(result: dict[str, Any]) -> None:
    print(f"\n=== Trial {result['trial']} ===")
    if not result.get("valid"):
        print(f"SEED FAILED HTTP {result.get('seed_http_status')}: {result.get('seed_error')}")
        return

    print(f"seed visible: {result.get('seed_visible')!r}")
    print(
        "seed steps: "
        f"thought={result.get('thought_step_count')} "
        f"signatures={result.get('thought_signature_count')} "
        f"model_output={result.get('model_output_step_count')}"
    )
    print(f"full-history reference: {result.get('full_history_reference')!r}")
    print()
    print(f"{'arm':22} {'http':>5} {'match':>7}  result")
    print("-" * 78)
    for arm in result.get("arms", []):
        result_text = arm.get("text") or arm.get("error") or ""
        if len(result_text) > 100:
            result_text = result_text[:97] + "..."
        print(
            f"{arm.get('arm',''):22} "
            f"{arm.get('http_status',0):>5} "
            f"{str(bool(arm.get('matches_full_history'))):>7}  "
            f"{result_text}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gemini-3.6-flash")
    parser.add_argument("--trials", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("Set GEMINI_API_KEY in the environment. The script never writes it to disk.", file=sys.stderr)
        return 2

    all_results: list[dict[str, Any]] = []
    for trial in range(1, args.trials + 1):
        result = run_trial(api_key, args.model, trial, args.timeout)
        all_results.append(result)
        print_trial(result)

    # Compact machine-readable result, deliberately excluding raw signatures/API payloads.
    report_path = "gemini_thought_ablation_results.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "model": args.model,
                "trials": all_results,
            },
            f,
            ensure_ascii=True,
            indent=2,
        )
    print(f"\nWrote compact results to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())