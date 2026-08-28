#!/usr/bin/env python3
"""Execute and score one already-reviewed executable-policy freeze.

The protocol constructor and freezer are deliberately transport-free.  This
module is the only network-capable part of the executable-policy pilot.  It
claims one ignored output directory before the first request, retains every
wire request/response, and terminalizes that consumed freeze on every outcome.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from thoughtlab.gemini_interactions import (
    InteractionHttpResult,
    error_text,
    output_text,
    post_interaction,
    response_steps,
)
from thoughtlab.stateTransitions.fork_pilot import (
    CallStore,
    write_bytes,
    write_json,
    write_text,
)
from thoughtlab.executablePlans.executable_plan_freeze import (
    FREEZE_LOCK_NAME,
    SAFE_FREEZE_FILES,
    SAFE_PAYLOAD_FILES,
    first_link_or_reparse_component,
    verify_freeze,
)
from thoughtlab.executablePlans.executable_plan_protocol import (
    APPLY_TOOL,
    HTTP_TIMEOUT_SECONDS,
    INSPECT_TOOL,
    MAX_ATTEMPTS_PER_LOGICAL_REQUEST,
    MAX_POST_OBSERVATION_DECISIONS,
    MODEL,
    NO_FUNCTION_CALLS_TOOL_CHOICE,
    RETRY_BACKOFF_SECONDS,
    SOURCE_LABELS,
    SYSTEM_INSTRUCTION,
    TOOL_DECLARATIONS,
    UNKNOWN_TOKEN,
    VERIFY_TOKEN,
    VERIFY_TOOL,
    DuplicateJsonKey,
    apply_simulator_action,
    build_executable_interaction_body,
    canonical_json_bytes,
    generation_config,
    initial_simulator_state,
    is_complete_success_sequence,
    sha256_bytes,
    sha256_json,
    strict_json_loads,
    user_step,
    valid_success_sequences,
    validate_experiment_definition,
)


SCHEMA_VERSION = "native_executable_policy_execution_v1"
INTER_REQUEST_DELAY_SECONDS = 1.0
INVALID_READOUT = "INVALID_READOUT"
INVALID_TRAJECTORY = "INVALID_TRAJECTORY"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


@dataclass
class SourceRuntime:
    label: str
    request_body: dict[str, Any]
    initial_input: list[dict[str, Any]]
    response_steps: list[dict[str, Any]]
    thought_step: dict[str, Any] | None
    function_call: dict[str, Any] | None
    signature: str | None
    summary: dict[str, Any]


def execution_output_dir(*, repo_root: Path, freeze_id: str) -> Path:
    """Return the sole allowed private execution location for a freeze."""

    if re.fullmatch(r"[0-9a-f]{64}", freeze_id) is None:
        raise ValueError("freeze ID must be a lowercase SHA-256 digest")
    return repo_root.resolve() / "results" / "executable_plan_native" / freeze_id


def _is_link_or_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0) & reparse_flag
    )


def _assert_path_has_no_link_ancestor(*, repo_root: Path, path: Path) -> None:
    root = repo_root.resolve()
    candidate = path.absolute()
    if candidate != root and not candidate.is_relative_to(root):
        raise ValueError("execution path escapes the repository")
    current = candidate
    while current != root:
        if current.exists() and _is_link_or_reparse_point(current):
            raise ValueError(f"execution path contains a link/reparse point: {current}")
        current = current.parent


def _minimal_git_environment() -> dict[str, str]:
    allowed = (
        "PATH",
        "SystemRoot",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
    )
    environment = {
        key: value
        for key in allowed
        if isinstance((value := os.environ.get(key)), str)
    }
    environment.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_ATTR_NOSYSTEM": "1",
        }
    )
    return environment


def _assert_execution_paths_are_ignored(*, repo_root: Path, output_dir: Path) -> None:
    root = repo_root.resolve()
    candidates = (
        output_dir,
        output_dir / "execution_ledger.json",
        output_dir / "raw" / "0001.request.json",
        output_dir / "raw" / "0001.response.bin",
        output_dir / "source_artifacts.private.json",
    )
    git_prefix = [
        "git",
        "-c",
        f"safe.directory={root}",
        "-c",
        "core.fsmonitor=false",
        "-c",
        f"core.hooksPath={os.devnull}",
    ]
    for candidate in candidates:
        try:
            relative = candidate.absolute().relative_to(root)
        except ValueError as exc:
            raise ValueError("execution output escapes the repository") from exc
        completed = subprocess.run(
            [*git_prefix, "check-ignore", "-q", "--", str(relative)],
            cwd=root,
            check=False,
            capture_output=True,
            env=_minimal_git_environment(),
        )
        if completed.returncode == 1:
            raise ValueError(f"private execution path is not Git-ignored: {relative}")
        if completed.returncode != 0:
            raise RuntimeError("could not verify Git-ignore protection")


def _read_verified_freeze_snapshot(
    *, freeze_dir: Path, expected_freeze_id: str
) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Read one immutable snapshot and parse its deterministic definition."""

    unsafe_component = first_link_or_reparse_component(freeze_dir)
    if unsafe_component is not None:
        raise ValueError(
            f"freeze path contains a link/reparse point: {unsafe_component}"
        )
    source = freeze_dir.resolve()
    if not source.is_dir():
        raise ValueError("freeze directory does not exist")
    entries = sorted(path.name for path in source.iterdir())
    if entries != sorted(SAFE_FREEZE_FILES):
        raise ValueError("freeze snapshot entries differ from the safe allowlist")

    snapshot: dict[str, bytes] = {}
    for name in SAFE_FREEZE_FILES:
        path = source / name
        if not path.is_file() or _is_link_or_reparse_point(path):
            raise ValueError(f"unsafe freeze payload path: {name}")
        before = path.stat()
        data = path.read_bytes()
        after = path.stat()
        before_fingerprint = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        )
        after_fingerprint = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        )
        if before_fingerprint != after_fingerprint or _is_link_or_reparse_point(path):
            raise ValueError(f"freeze payload changed while being read: {name}")
        snapshot[name] = data

    if sha256_bytes(snapshot[FREEZE_LOCK_NAME]) != expected_freeze_id:
        raise ValueError("freeze snapshot ID differs from the reviewed freeze ID")
    lock = strict_json_loads(snapshot[FREEZE_LOCK_NAME].decode("utf-8"))
    if not isinstance(lock, dict) or not isinstance(lock.get("files"), dict):
        raise ValueError("freeze lock is not an object with a file inventory")
    if set(lock["files"]) != set(SAFE_PAYLOAD_FILES):
        raise ValueError("freeze lock file inventory is incomplete")
    for name in SAFE_PAYLOAD_FILES:
        if sha256_bytes(snapshot[name]) != lock["files"].get(name):
            raise ValueError(f"freeze snapshot byte hash mismatch: {name}")

    definition = strict_json_loads(
        snapshot["experiment_definition.json"].decode("utf-8")
    )
    if not isinstance(definition, dict):
        raise ValueError("frozen experiment definition is not an object")
    definition_errors = validate_experiment_definition(definition)
    if definition_errors:
        raise ValueError(
            "frozen experiment definition is invalid: "
            + "; ".join(definition_errors)
        )
    return snapshot, definition


def _copy_freeze(snapshot: dict[str, bytes], output_dir: Path) -> None:
    target = output_dir / "frozen_protocol"
    target.mkdir(parents=True, exist_ok=False)
    for name in SAFE_FREEZE_FILES:
        write_bytes(target / name, snapshot[name])


def _safe_call_summary(call: dict[str, Any]) -> dict[str, Any]:
    attempts = call.get("attempts") if isinstance(call, dict) else None
    safe_attempts: list[dict[str, Any]] = []
    if isinstance(attempts, list):
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            safe_attempts.append(
                {
                    "attempt_index": attempt.get("attempt_index"),
                    "call_number": attempt.get("call_number"),
                    "http_status": attempt.get("http_status"),
                    "transport_error_present": bool(attempt.get("transport_error")),
                    "response_parse_error_present": bool(
                        attempt.get("response_parse_error")
                    ),
                    "request_wire_sha256": attempt.get("request_wire_sha256"),
                    "request_wire_bytes": attempt.get("request_wire_bytes"),
                    "response_wire_sha256": attempt.get("response_wire_sha256"),
                    "response_wire_bytes": attempt.get("response_wire_bytes"),
                    "retryable_reason": attempt.get("retryable_reason"),
                }
            )
    return {
        "logical_request_id": call.get("logical_request_id"),
        "attempt_count": call.get("attempt_count"),
        "selected_physical_call_number": call.get("selected_physical_call_number"),
        "selected_response_wire_sha256": call.get("selected_response_wire_sha256"),
        "selection_reason": call.get("selection_reason"),
        "retried": bool(call.get("retried")),
        "request_wire_sha256": call.get("request_wire_sha256"),
        "request_wire_bytes": call.get("request_wire_bytes"),
        "attempts": safe_attempts,
    }


def _safe_payload_metadata(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "interaction_status": None,
            "returned_model_matches": False,
            "usage_sha256": None,
            "provider_error_present": False,
        }
    provider_error = error_text(payload)
    usage = payload.get("usage")
    return {
        "interaction_status": payload.get("status"),
        "returned_model_matches": payload.get("model") == MODEL,
        "returned_model_value_sha256": sha256_text(str(payload.get("model")))
        if payload.get("model") is not None
        else None,
        "usage_sha256": sha256_json(usage) if usage is not None else None,
        "provider_error_present": bool(provider_error),
        "provider_error_sha256": sha256_text(provider_error)
        if provider_error
        else None,
    }


def _invoke(
    *, store: CallStore, label: str, body: dict[str, Any]
) -> tuple[InteractionHttpResult, dict[str, Any]]:
    result, call = store.invoke_logical(label=label, body=body)
    return result, _safe_call_summary(call)


def _base_http_reasons(
    *, result: InteractionHttpResult, expected_status: str
) -> list[str]:
    reasons: list[str] = []
    if result.http_status is None or not 200 <= result.http_status < 300:
        reasons.append("request was not HTTP 2xx")
    if result.transport_error:
        reasons.append("transport error")
    if result.response_parse_error:
        reasons.append("response body was not a JSON object")
    payload = result.payload
    if not isinstance(payload, dict):
        reasons.append("missing response payload")
        return reasons
    if payload.get("status") != expected_status:
        reasons.append(f"interaction status was not {expected_status}")
    if payload.get("model") != MODEL:
        reasons.append("returned model did not match the frozen model")
    if payload.get("error") or payload.get("errors"):
        reasons.append("response contained a top-level error")
    return reasons


def _parse_steps(result: InteractionHttpResult) -> tuple[list[dict[str, Any]], str | None]:
    if not isinstance(result.payload, dict):
        return [], "missing response payload"
    try:
        return response_steps(result.payload), None
    except ValueError as exc:
        return [], f"invalid response steps: {exc}"


def _source_runtime(
    *,
    label: str,
    body: dict[str, Any],
    result: InteractionHttpResult,
    call: dict[str, Any],
) -> SourceRuntime:
    reasons = _base_http_reasons(result=result, expected_status="requires_action")
    steps, step_error = _parse_steps(result)
    if step_error:
        reasons.append(step_error)
    thought: dict[str, Any] | None = None
    function_call: dict[str, Any] | None = None
    signature: str | None = None
    if len(steps) != 2 or [step.get("type") for step in steps] != [
        "thought",
        "function_call",
    ]:
        reasons.append("steps were not exactly [thought, function_call]")
    else:
        thought = copy.deepcopy(steps[0])
        function_call = copy.deepcopy(steps[1])
        candidate_signature = thought.get("signature")
        if not isinstance(candidate_signature, str) or not candidate_signature:
            reasons.append("source thought lacked a nonempty signature")
        else:
            signature = candidate_signature
        if thought.get("summary") not in (None, "", []):
            reasons.append("source thought contained a visible summary")
        if function_call.get("name") != INSPECT_TOOL:
            reasons.append("first function call was not inspect_environment")
        if function_call.get("arguments") != {}:
            reasons.append("inspect_environment arguments were not empty")
        if not isinstance(function_call.get("id"), str) or not function_call.get("id"):
            reasons.append("source function call lacked a nonempty ID")
    if output_text(result.payload or {}):
        reasons.append("source response contained visible model output")
    if any(step.get("type") == "model_output" for step in steps):
        reasons.append("source response contained a model_output step")
    initial_input = copy.deepcopy(body.get("input") or [])
    summary = {
        "schema_version": "native_executable_policy_source_summary_v1",
        "source": label,
        "eligible": not reasons,
        "ineligibility_reasons": reasons,
        "request_sha256": sha256_json(body),
        "request_input_sha256": sha256_json(initial_input),
        "response_steps_sha256": sha256_json(steps),
        "thought_step_count": sum(step.get("type") == "thought" for step in steps),
        "function_call_step_count": sum(
            step.get("type") == "function_call" for step in steps
        ),
        "model_output_step_count": sum(
            step.get("type") == "model_output" for step in steps
        ),
        "signature_sha256": sha256_text(signature) if signature else None,
        "signature_chars": len(signature) if signature else 0,
        "function_call_id_sha256": sha256_text(str(function_call.get("id")))
        if function_call and function_call.get("id")
        else None,
        "call": call,
        **_safe_payload_metadata(result.payload),
    }
    return SourceRuntime(
        label=label,
        request_body=copy.deepcopy(body),
        initial_input=initial_input,
        response_steps=copy.deepcopy(steps),
        thought_step=thought,
        function_call=function_call,
        signature=signature,
        summary=summary,
    )


def generate_sources(
    *,
    definition: dict[str, Any],
    store: CallStore,
    run_dir: Path,
) -> tuple[dict[str, SourceRuntime], dict[str, Any]]:
    runtimes: dict[str, SourceRuntime] = {}
    private_rows: dict[str, Any] = {}
    schedule = definition["schedule"]["source_generation"]
    requests = definition["source_generation"]["requests"]
    for row in schedule:
        label = row["source"]
        body = copy.deepcopy(requests[label])
        result, call = _invoke(store=store, label=row["logical_label"], body=body)
        runtime = _source_runtime(
            label=label,
            body=body,
            result=result,
            call=call,
        )
        runtimes[label] = runtime
        private_rows[label] = {
            "request": body,
            "response_steps": runtime.response_steps,
        }
        write_json(run_dir / "source_artifacts.private.json", private_rows)
        write_json(
            run_dir / "source_summaries.partial.json",
            [runtimes[name].summary for name in SOURCE_LABELS if name in runtimes],
        )

        # Scientific failures are not repaired.  If the first source is already
        # unusable, the frozen 1--2 source-call stopping rule ends generation
        # without spending a second call that cannot make the pair eligible.
        if not runtime.summary["eligible"]:
            break

    complete_pair = set(runtimes) == set(SOURCE_LABELS)
    request_bytes = [
        canonical_json_bytes(runtimes[name].request_body)
        for name in SOURCE_LABELS
        if name in runtimes
    ]
    requests_identical = complete_pair and request_bytes[0] == request_bytes[1]
    if complete_pair and not requests_identical:
        for runtime in runtimes.values():
            runtime.summary["eligible"] = False
            runtime.summary["ineligibility_reasons"].append(
                "source generation requests were not byte-identical"
            )
    signatures = [
        runtimes[name].signature for name in SOURCE_LABELS if name in runtimes
    ]
    signatures_distinct = (
        complete_pair
        and None not in signatures
        and signatures[0] != signatures[1]
    )
    if complete_pair and None not in signatures and signatures[0] == signatures[1]:
        for runtime in runtimes.values():
            runtime.summary["eligible"] = False
            runtime.summary["ineligibility_reasons"].append(
                "source thought signatures were not distinct"
            )
    generation = {
        "schema_version": "native_executable_policy_generation_v1",
        "eligible": complete_pair
        and all(runtimes[name].summary["eligible"] for name in SOURCE_LABELS),
        "source_calls_completed": len(runtimes),
        "source_pair_complete": complete_pair,
        "source_request_bytes_identical": requests_identical,
        "source_request_sha256": sha256_bytes(request_bytes[0])
        if request_bytes
        else None,
        "source_signatures_distinct": signatures_distinct,
        "sources": [
            runtimes[name].summary for name in SOURCE_LABELS if name in runtimes
        ],
        "replacement_generation_permitted": False,
    }
    write_json(run_dir / "source_summaries.json", generation)
    return runtimes, generation


def function_result_step(
    *, function_call: dict[str, Any], result_value: dict[str, Any]
) -> dict[str, Any]:
    """Create Google's documented stateless function-result step."""

    name = function_call.get("name")
    call_id = function_call.get("id")
    if not isinstance(name, str) or not name:
        raise ValueError("function call has no name")
    if not isinstance(call_id, str) or not call_id:
        raise ValueError("function call has no ID")
    return {
        "type": "function_result",
        "name": name,
        "call_id": call_id,
        "result": [
            {
                "type": "text",
                "text": canonical_json_bytes(result_value).decode("ascii"),
            }
        ],
    }


def _tool_decision(
    result: InteractionHttpResult,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[str]]:
    reasons = _base_http_reasons(result=result, expected_status="requires_action")
    steps, step_error = _parse_steps(result)
    if step_error:
        reasons.append(step_error)
    calls = [step for step in steps if step.get("type") == "function_call"]
    outputs = [step for step in steps if step.get("type") == "model_output"]
    unexpected = [
        step for step in steps if step.get("type") not in {"thought", "function_call"}
    ]
    if len(calls) != 1:
        reasons.append("response did not contain exactly one function call")
    if outputs:
        reasons.append("response contained model output")
    if unexpected:
        reasons.append("response contained an unexpected step type")
    call = copy.deepcopy(calls[0]) if len(calls) == 1 else None
    if call is not None:
        if steps[-1] is not calls[0]:
            reasons.append("function call was not the final response step")
        if call.get("name") not in {APPLY_TOOL, VERIFY_TOOL, INSPECT_TOOL}:
            reasons.append("response called an unknown tool")
        if not isinstance(call.get("id"), str) or not call.get("id"):
            reasons.append("function call lacked a nonempty ID")
        if not isinstance(call.get("arguments"), dict):
            reasons.append("function-call arguments were not an object")
    return call if not reasons else None, steps, reasons


def _prospective_request(
    *, source: SourceRuntime, input_steps: list[dict[str, Any]]
) -> dict[str, Any]:
    return build_executable_interaction_body(
        model=MODEL,
        input_steps=input_steps,
        generation_config_value=source.request_body["generation_config"],
        system_instruction=SYSTEM_INSTRUCTION,
        tools=TOOL_DECLARATIONS,
    )


def run_prospective_trajectory(
    *,
    definition: dict[str, Any],
    source: SourceRuntime,
    schedule_row: dict[str, Any],
    store: CallStore,
    partial_writer: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    task = definition["task"]
    observation = schedule_row["observation"]
    if source.function_call is None:
        raise ValueError("prospective execution requires an eligible source call")
    simulator_state = initial_simulator_state(task, observation)
    history = (
        copy.deepcopy(source.initial_input)
        + copy.deepcopy(source.response_steps)
        + [
            function_result_step(
                function_call=source.function_call,
                result_value={"observation_id": observation},
            )
        ]
    )
    branch_limit = len(valid_success_sequences(task, observation)[0])
    decisions: list[dict[str, Any]] = []
    sequence: list[str] = []
    terminal_reason: str | None = None
    first_request_sha256: str | None = None

    for decision_index in range(1, min(branch_limit, MAX_POST_OBSERVATION_DECISIONS) + 1):
        body = _prospective_request(source=source, input_steps=history)
        request_hash = sha256_json(body)
        if first_request_sha256 is None:
            first_request_sha256 = request_hash
        result, call_summary = _invoke(
            store=store,
            label=f"{schedule_row['logical_label']}_decision{decision_index:02d}",
            body=body,
        )
        function_call, exact_steps, response_reasons = _tool_decision(result)
        decision: dict[str, Any] = {
            "decision_index": decision_index,
            "request_sha256": request_hash,
            "response_steps_sha256": sha256_json(exact_steps),
            "response_eligible": not response_reasons,
            "response_ineligibility_reasons": response_reasons,
            "call": call_summary,
            **_safe_payload_metadata(result.payload),
        }
        if function_call is None:
            terminal_reason = "invalid_tool_response"
            decision["simulator"] = {
                "valid": False,
                "terminal": True,
                "success": False,
                "error": terminal_reason,
            }
            decisions.append(decision)
            if partial_writer:
                partial_writer(decision)
            break

        simulator = apply_simulator_action(
            task,
            simulator_state,
            str(function_call.get("name")),
            function_call.get("arguments"),
        )
        simulator_state = simulator["state"]
        action_token = simulator.get("action_token")
        if isinstance(action_token, str):
            sequence.append(action_token)
        decision["function_name"] = function_call.get("name")
        decision["function_call_id_sha256"] = sha256_text(
            str(function_call.get("id"))
        )
        decision["action_token"] = action_token
        decision["simulator"] = {
            "valid": simulator["valid"],
            "terminal": simulator["terminal"],
            "success": simulator["success"],
            "error": simulator["error"],
            "environment_state": simulator_state.get("environment_state"),
        }
        decisions.append(decision)
        if partial_writer:
            partial_writer(decision)
        if simulator["terminal"]:
            terminal_reason = (
                "verified_success" if simulator["success"] else str(simulator["error"])
            )
            break
        if decision_index >= branch_limit:
            simulator_state["terminal"] = True
            simulator_state["success"] = False
            simulator_state["invalid_reason"] = "task_branch_decision_limit"
            terminal_reason = "task_branch_decision_limit"
            break
        history.extend(copy.deepcopy(exact_steps))
        history.append(
            function_result_step(
                function_call=function_call,
                result_value=simulator["tool_result"],
            )
        )

    success = bool(simulator_state.get("success"))
    return {
        "schema_version": "native_executable_policy_trajectory_v1",
        "source": schedule_row["source"],
        "observation": observation,
        "repeat": schedule_row["repeat"],
        "logical_label": schedule_row["logical_label"],
        "first_request_sha256": first_request_sha256,
        "decision_count": len(decisions),
        "branch_decision_limit": branch_limit,
        "first_action": sequence[0] if sequence else None,
        "sequence": sequence,
        "terminal": True,
        "terminal_reason": terminal_reason or "task_branch_decision_limit",
        "success": success,
        "complete_success_sequence": success
        and is_complete_success_sequence(task, observation, sequence),
        "decisions": decisions,
    }


def run_all_prospective(
    *,
    definition: dict[str, Any],
    sources: dict[str, SourceRuntime],
    store: CallStore,
    run_dir: Path,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for schedule_row in definition["schedule"]["prospective"]:
        current: dict[str, Any] = {
            "source": schedule_row["source"],
            "observation": schedule_row["observation"],
            "repeat": schedule_row["repeat"],
            "logical_label": schedule_row["logical_label"],
            "decisions": [],
            "partial": True,
        }

        def persist_decision(decision: dict[str, Any]) -> None:
            current["decisions"].append(copy.deepcopy(decision))
            write_json(run_dir / "prospective_results.partial.json", [*rows, current])

        trajectory = run_prospective_trajectory(
            definition=definition,
            source=sources[schedule_row["source"]],
            schedule_row=schedule_row,
            store=store,
            partial_writer=persist_decision,
        )
        rows.append(trajectory)
        write_json(run_dir / "prospective_results.partial.json", rows)

    expected_count = len(SOURCE_LABELS) * len(definition["task"]["observation_order"]) * 3
    if len(rows) != expected_count or not all(row.get("terminal") for row in rows):
        raise RuntimeError("prospective phase did not terminalize every frozen repeat")
    for source in SOURCE_LABELS:
        for observation in definition["task"]["observation_order"]:
            hashes = {
                row["first_request_sha256"]
                for row in rows
                if row["source"] == source and row["observation"] == observation
            }
            if len(hashes) != 1:
                raise RuntimeError(
                    "prospective first requests were not byte-identical within a cell"
                )
    write_json(run_dir / "prospective_results.json", rows)
    return rows


def normalize_atomic_answer(
    text: str, task: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[str]]:
    reasons: list[str] = []
    try:
        value = strict_json_loads(text)
    except (TypeError, ValueError, RecursionError) as exc:
        return None, [f"strict JSON parse failed: {type(exc).__name__}"]
    if not isinstance(value, dict) or set(value) != {"status", "next"}:
        return None, ["atomic answer did not have exactly status and next"]
    status = value.get("status")
    next_value = value.get("next")
    if not isinstance(status, str) or status not in {"known", "unknown"}:
        reasons.append("atomic status was invalid")
    # A structurally valid but foreign/wrong string is a scientific outcome,
    # not parser failure.  The scorer classifies its semantic relationship to
    # the frozen task separately.
    if status == "known" and not isinstance(next_value, str):
        reasons.append("known atomic answer did not contain a string next action")
    if status == "unknown" and next_value is not None:
        reasons.append("unknown atomic answer did not use null next")
    if reasons:
        return None, reasons
    return {"status": status, "next": next_value}, []


def _is_proper_valid_prefix(
    task: dict[str, Any], observation: str, sequence: list[str]
) -> bool:
    return bool(sequence) and any(
        len(sequence) < len(path) and path[: len(sequence)] == sequence
        for path in valid_success_sequences(task, observation)
    )


def normalize_structured_answer(
    text: str, task: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        value = strict_json_loads(text)
    except (TypeError, ValueError, RecursionError) as exc:
        return None, [f"strict JSON parse failed: {type(exc).__name__}"]
    if not isinstance(value, dict) or set(value) != {"policies"}:
        return None, ["structured answer did not have exactly policies"]
    policies = value.get("policies")
    if not isinstance(policies, list) or len(policies) != 3:
        return None, ["policies was not an array of length three"]
    observation_order = list(task["observation_order"])
    by_observation: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []
    for index, policy in enumerate(policies):
        if not isinstance(policy, dict) or set(policy) != {
            "observation",
            "status",
            "sequence",
        }:
            reasons.append(f"policy {index} did not have exactly the required keys")
            continue
        observation = policy.get("observation")
        status = policy.get("status")
        sequence = policy.get("sequence")
        if (
            not isinstance(observation, str)
            or observation not in observation_order
            or observation in by_observation
        ):
            reasons.append(f"policy {index} had an unknown or duplicate observation")
            continue
        if not isinstance(status, str) or status not in {
            "known",
            "partial",
            "unknown",
        }:
            reasons.append(f"policy {index} had invalid status")
            continue
        if (
            not isinstance(sequence, list)
            or len(sequence) > MAX_POST_OBSERVATION_DECISIONS
            or any(
            not isinstance(token, str) for token in sequence
            )
        ):
            reasons.append(f"policy {index} had an invalid sequence")
            continue
        if status == "unknown" and sequence:
            reasons.append(f"policy {index} unknown status had a nonempty sequence")
        by_observation[observation] = {
            "observation": observation,
            "status": status,
            "sequence": list(sequence),
        }
    if set(by_observation) != set(observation_order):
        reasons.append("structured answer did not cover every observation exactly once")
    if reasons:
        return None, reasons
    return {"policies": [by_observation[obs] for obs in observation_order]}, []


def _readout_text_and_reasons(
    result: InteractionHttpResult,
) -> tuple[str, list[dict[str, Any]], list[str]]:
    reasons = _base_http_reasons(result=result, expected_status="completed")
    steps, step_error = _parse_steps(result)
    if step_error:
        reasons.append(step_error)
    outputs = [step for step in steps if step.get("type") == "model_output"]
    calls = [step for step in steps if step.get("type") == "function_call"]
    unexpected = [
        step
        for step in steps
        if step.get("type") not in {"thought", "model_output"}
    ]
    if len(outputs) != 1:
        reasons.append("readout did not contain exactly one model_output step")
    if calls:
        reasons.append("readout returned a function call")
    if unexpected:
        reasons.append("readout contained an unexpected step type")
    if len(outputs) == 1:
        content = outputs[0].get("content")
        if (
            not isinstance(content, list)
            or len(content) != 1
            or not isinstance(content[0], dict)
            or content[0].get("type") != "text"
            or not isinstance(content[0].get("text"), str)
        ):
            reasons.append("model_output was not exactly one text block")
    return output_text(result.payload or {}), steps, reasons


def _carrier_input(source: SourceRuntime, prompt: str) -> list[dict[str, Any]]:
    if source.thought_step is None:
        raise ValueError("carrier readout requires an eligible source thought")
    return [copy.deepcopy(source.thought_step), user_step(prompt)]


def _readout_request(
    *,
    definition: dict[str, Any],
    schedule_row: dict[str, Any],
    sources: dict[str, SourceRuntime],
) -> tuple[dict[str, Any], str]:
    arm = schedule_row["arm"]
    task = definition["task"]
    readouts = definition["readouts"]
    system_instruction: str | None = None
    tools: list[dict[str, Any]] | None = None
    response_format: dict[str, Any]
    if arm == "atomic":
        observation = schedule_row["observation"]
        source = sources[schedule_row["source"]]
        inputs = _carrier_input(source, readouts["atomic_prompts"][observation])
        seed = readouts["matched_probe_seeds"][observation]
        response_format = readouts["atomic_response_format"]
        cell = f"atomic:{schedule_row['source']}:{observation}"
    elif arm == "structured":
        source = sources[schedule_row["source"]]
        inputs = _carrier_input(source, readouts["structured_prompt"])
        seed = readouts["structured_seed"]
        response_format = readouts["structured_response_format"]
        cell = f"structured:{schedule_row['source']}"
    elif arm == "open":
        source = sources[schedule_row["source"]]
        inputs = _carrier_input(source, readouts["open_prompt"])
        seed = readouts["open_seed"]
        response_format = readouts["open_response_format"]
        cell = f"open:{schedule_row['source']}"
    elif arm == "task_only":
        observation = schedule_row["observation"]
        inputs = [
            user_step(
                task["task_text"].rstrip()
                + "\n\n"
                + readouts["task_only_prompts"][observation]
            ),
        ]
        seed = readouts["matched_probe_seeds"][observation]
        response_format = readouts["atomic_response_format"]
        system_instruction = SYSTEM_INSTRUCTION
        tools = TOOL_DECLARATIONS
        cell = f"task_only:{observation}"
    elif arm == "visible_only":
        observation = schedule_row["observation"]
        source = sources[SOURCE_LABELS[0]]
        if source.function_call is None:
            raise ValueError("visible control requires an eligible source call")
        inputs = [
            copy.deepcopy(source.function_call),
            function_result_step(
                function_call=source.function_call,
                result_value={"observation_id": observation},
            ),
            user_step(readouts["atomic_prompts"][observation]),
        ]
        seed = readouts["matched_probe_seeds"][observation]
        response_format = readouts["atomic_response_format"]
        cell = f"visible_only:{observation}"
    elif arm == "probe_only":
        observation = schedule_row["observation"]
        inputs = [user_step(readouts["atomic_prompts"][observation])]
        seed = readouts["matched_probe_seeds"][observation]
        response_format = readouts["atomic_response_format"]
        cell = f"probe_only:{observation}"
    elif arm == "full_task_semantic":
        inputs = [
            user_step(
                task["task_text"].rstrip()
                + "\n\n"
                + readouts["full_task_semantic_prompt"]
            )
        ]
        seed = readouts["open_seed"]
        response_format = readouts["open_response_format"]
        cell = "full_task_semantic_upper"
    else:
        raise ValueError(f"unknown readout arm: {arm}")
    request_generation_config = generation_config(seed)
    if arm == "task_only":
        # The tool declarations are part of the full-task control context, but
        # this cell measures a normalized report rather than another tool run.
        request_generation_config["tool_choice"] = copy.deepcopy(
            definition["readouts"]["task_only_tool_choice"]
        )
    body = build_executable_interaction_body(
        model=MODEL,
        input_steps=inputs,
        generation_config_value=request_generation_config,
        response_format=response_format,
        system_instruction=system_instruction,
        tools=tools,
    )
    return body, cell


def run_readouts(
    *,
    definition: dict[str, Any],
    sources: dict[str, SourceRuntime],
    store: CallStore,
    run_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    private_text: list[dict[str, Any]] = []
    cell_hashes: dict[str, str] = {}
    task = definition["task"]
    for schedule_row in definition["schedule"]["readout_execution"]:
        body, cell = _readout_request(
            definition=definition,
            schedule_row=schedule_row,
            sources=sources,
        )
        request_hash = sha256_json(body)
        prior_hash = cell_hashes.setdefault(cell, request_hash)
        if prior_hash != request_hash:
            raise RuntimeError(f"readout repeats were not byte-identical for {cell}")
        result, call = _invoke(
            store=store,
            label=schedule_row["logical_label"],
            body=body,
        )
        text, steps, response_reasons = _readout_text_and_reasons(result)
        arm = schedule_row["arm"]
        normalized: dict[str, Any] | None = None
        normalization_reasons: list[str] = []
        if not response_reasons and arm in {
            "atomic",
            "task_only",
            "visible_only",
            "probe_only",
        }:
            normalized, normalization_reasons = normalize_atomic_answer(text, task)
        elif not response_reasons and arm == "structured":
            normalized, normalization_reasons = normalize_structured_answer(text, task)
        elif not response_reasons and arm in {"open", "full_task_semantic"}:
            if not text:
                normalization_reasons = ["open semantic readout was empty"]
            else:
                normalized = {"text_present": True}
        all_reasons = [*response_reasons, *normalization_reasons]
        row = {
            "schema_version": "native_executable_policy_readout_v1",
            **copy.deepcopy(schedule_row),
            "request_cell": cell,
            "request_sha256": request_hash,
            "eligible": not all_reasons,
            "ineligibility_reasons": all_reasons,
            "normalized": normalized,
            "output_sha256": sha256_text(text),
            "output_chars": len(text),
            "response_steps_sha256": sha256_json(steps),
            "call": call,
            **_safe_payload_metadata(result.payload),
        }
        rows.append(row)
        if arm in {"open", "full_task_semantic"}:
            private_text.append(
                {
                    "logical_label": schedule_row["logical_label"],
                    "arm": arm,
                    "source": schedule_row.get("source"),
                    "text": text,
                }
            )
            write_json(run_dir / "semantic_readouts.private.json", private_text)
        write_json(run_dir / "readout_results.partial.json", rows)
    write_json(run_dir / "readout_results.json", rows)
    return rows, private_text


def _distribution(values: Iterable[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _atomic_category(row: dict[str, Any]) -> str:
    normalized = row.get("normalized")
    if not row.get("eligible") or not isinstance(normalized, dict):
        return INVALID_READOUT
    if normalized.get("status") == "unknown":
        return UNKNOWN_TOKEN
    value = normalized.get("next")
    return str(value) if isinstance(value, str) else INVALID_READOUT


def _trajectory_first_category(row: dict[str, Any]) -> str:
    value = row.get("first_action")
    return str(value) if isinstance(value, str) else INVALID_TRAJECTORY


def _pairwise_agreement(
    predictions: list[str], targets: list[str], allowed_actions: set[str]
) -> dict[str, Any]:
    total = len(predictions) * len(targets)
    matches = sum(
        prediction in allowed_actions
        and target in allowed_actions
        and prediction == target
        for prediction in predictions
        for target in targets
    )
    return {
        "matches": matches,
        "comparisons": total,
        "probability": matches / total if total else None,
    }


def _modal_action(values: list[str], allowed_actions: set[str]) -> tuple[str | None, int]:
    counts = Counter(value for value in values if value in allowed_actions)
    if not counts:
        return None, 0
    action, count = counts.most_common(1)[0]
    if list(counts.values()).count(count) > 1:
        return None, count
    return action, count


def _dependency_edge_agreement(
    prediction: list[str], targets: list[list[str]]
) -> dict[str, Any]:
    # Verification is scored separately as stopping behavior.  A dependency
    # edge here is strictly operation -> operation.
    predicted_edges = {
        edge
        for edge in zip(prediction, prediction[1:])
        if VERIFY_TOKEN not in edge
    }
    target_edges = [
        edge
        for target in targets
        for edge in zip(target, target[1:])
        if VERIFY_TOKEN not in edge
    ]
    matches = sum(edge in predicted_edges for edge in target_edges)
    return {
        "matches": matches,
        "comparisons": len(target_edges),
        "probability": matches / len(target_edges) if target_edges else None,
    }


def score_results(
    *,
    definition: dict[str, Any],
    prospective: list[dict[str, Any]],
    readouts: list[dict[str, Any]],
) -> dict[str, Any]:
    task = definition["task"]
    observations = task["observation_order"]
    allowed_actions = {*task["operation_universe"], VERIFY_TOKEN}
    atomic_rows = [row for row in readouts if row["arm"] == "atomic"]
    task_only_rows = [row for row in readouts if row["arm"] == "task_only"]

    local_cells: list[dict[str, Any]] = []
    prospective_by_cell: dict[tuple[str, str], list[str]] = {}
    for source in SOURCE_LABELS:
        for observation in observations:
            prospective_by_cell[(source, observation)] = [
                _trajectory_first_category(row)
                for row in prospective
                if row["source"] == source and row["observation"] == observation
            ]

    distinguishing: dict[str, dict[str, Any]] = {}
    for observation in observations:
        valid_branch_actions = {
            path[0] for path in valid_success_sequences(task, observation) if path
        }
        modes: dict[str, tuple[str | None, int]] = {
            source: _modal_action(
                prospective_by_cell[(source, observation)], valid_branch_actions
            )
            for source in SOURCE_LABELS
        }
        distinguishing[observation] = {
            "source_modes": {
                source: {"action": modes[source][0], "count": modes[source][1]}
                for source in SOURCE_LABELS
            },
            "distinguishing": all(modes[source][1] >= 2 for source in SOURCE_LABELS)
            and modes[SOURCE_LABELS[0]][0] is not None
            and modes[SOURCE_LABELS[1]][0] is not None
            and modes[SOURCE_LABELS[0]][0] != modes[SOURCE_LABELS[1]][0],
        }

    for source_index, source in enumerate(SOURCE_LABELS):
        donor = SOURCE_LABELS[1 - source_index]
        for observation in observations:
            predictions = [
                _atomic_category(row)
                for row in atomic_rows
                if row["source"] == source and row["observation"] == observation
            ]
            donor_predictions = [
                _atomic_category(row)
                for row in atomic_rows
                if row["source"] == donor and row["observation"] == observation
            ]
            own = prospective_by_cell[(source, observation)]
            donor_targets = prospective_by_cell[(donor, observation)]
            task_targets = [
                _atomic_category(row)
                for row in task_only_rows
                if row["observation"] == observation
            ]
            own_agreement = _pairwise_agreement(predictions, own, allowed_actions)
            donor_carrier_against_own = _pairwise_agreement(
                donor_predictions, own, allowed_actions
            )
            task_only_against_own = _pairwise_agreement(
                task_targets, own, allowed_actions
            )
            own_carrier_against_donor = _pairwise_agreement(
                predictions, donor_targets, allowed_actions
            )
            carrier_task_similarity = _pairwise_agreement(
                predictions, task_targets, allowed_actions
            )
            predicted_valid = [value for value in predictions if value in allowed_actions]
            confidently_wrong = sum(
                value not in {UNKNOWN_TOKEN, INVALID_READOUT} and value not in own
                for value in predictions
            )
            local_cells.append(
                {
                    "source": source,
                    "donor_source": donor,
                    "observation": observation,
                    "distinguishing_branch": distinguishing[observation][
                        "distinguishing"
                    ],
                    "atomic_distribution": _distribution(predictions),
                    "own_prospective_distribution": _distribution(own),
                    "donor_atomic_distribution": _distribution(donor_predictions),
                    "donor_prospective_distribution": _distribution(donor_targets),
                    "task_only_distribution": _distribution(task_targets),
                    "own_carrier_vs_own_prospective": own_agreement,
                    "donor_carrier_vs_own_prospective": donor_carrier_against_own,
                    "task_only_vs_own_prospective": task_only_against_own,
                    "own_carrier_vs_donor_prospective_diagnostic": own_carrier_against_donor,
                    "own_carrier_vs_task_only_similarity_diagnostic": carrier_task_similarity,
                    "own_minus_donor_carrier_probability": (
                        own_agreement["probability"]
                        - donor_carrier_against_own["probability"]
                    ),
                    "own_minus_task_only_probability": (
                        own_agreement["probability"]
                        - task_only_against_own["probability"]
                    ),
                    "within_atomic_repeat_agreement": len(predictions) == 2
                    and INVALID_READOUT not in predictions
                    and predictions[0] == predictions[1],
                    "known_action_count": len(predicted_valid),
                    "known_foreign_or_wrong_string_count": sum(
                        value not in {UNKNOWN_TOKEN, INVALID_READOUT}
                        and value not in allowed_actions
                        for value in predictions
                    ),
                    "unknown_count": predictions.count(UNKNOWN_TOKEN),
                    "invalid_readout_count": predictions.count(INVALID_READOUT),
                    "confidently_wrong_count": confidently_wrong,
                }
            )

    structured_rows = [row for row in readouts if row["arm"] == "structured"]
    structured_cells: list[dict[str, Any]] = []
    for row in structured_rows:
        normalized = row.get("normalized")
        if not row.get("eligible") or not isinstance(normalized, dict):
            # A failed all-outcome readout contributes one explicit invalid cell
            # for every frozen observation, keeping the denominator fixed at 12.
            for observation in observations:
                structured_cells.append(
                    {
                        "source": row.get("source"),
                        "repeat": row.get("repeat"),
                        "eligible": False,
                        "observation": observation,
                        "status": INVALID_READOUT,
                        "sequence": [],
                        "first_action_agreement": 0.0,
                        "own_prospective_exact_agreement": 0.0,
                        "donor_prospective_exact_agreement_diagnostic": 0.0,
                        "dependency_edge_agreement": None,
                        "terminal_verify": False,
                        "semantic_class": INVALID_READOUT,
                        "complete_valid_success": False,
                    }
                )
            continue
        source = row["source"]
        donor = SOURCE_LABELS[1 - SOURCE_LABELS.index(source)]
        for policy in normalized["policies"]:
            observation = policy["observation"]
            sequence = list(policy["sequence"])
            own_sequences = [
                list(item["sequence"])
                for item in prospective
                if item["source"] == source and item["observation"] == observation
            ]
            donor_sequences = [
                list(item["sequence"])
                for item in prospective
                if item["source"] == donor and item["observation"] == observation
            ]
            own_first_actions = [target[0] if target else None for target in own_sequences]
            predicted_first = sequence[0] if sequence else None
            complete_valid = policy["status"] == "known" and is_complete_success_sequence(
                task, observation, sequence
            )
            if policy["status"] == "unknown":
                semantic_class = "unknown"
            elif complete_valid:
                semantic_class = "complete_valid_success"
            elif _is_proper_valid_prefix(task, observation, sequence):
                semantic_class = "proper_valid_prefix"
            else:
                semantic_class = "wrong_foreign_or_noncanonical_sequence"
            structured_cells.append(
                {
                    "source": source,
                    "repeat": row["repeat"],
                    "eligible": True,
                    "observation": observation,
                    "status": policy["status"],
                    "sequence": sequence,
                    "first_action_agreement": sum(
                        predicted_first is not None and predicted_first == target
                        for target in own_first_actions
                    )
                    / len(own_first_actions),
                    "own_prospective_exact_agreement": sum(
                        sequence == target for target in own_sequences
                    )
                    / len(own_sequences),
                    "donor_prospective_exact_agreement_diagnostic": sum(
                        sequence == target for target in donor_sequences
                    )
                    / len(donor_sequences),
                    "dependency_edge_agreement": _dependency_edge_agreement(
                        sequence, own_sequences
                    ),
                    "terminal_verify": bool(sequence and sequence[-1] == VERIFY_TOKEN),
                    "semantic_class": semantic_class,
                    "complete_valid_success": complete_valid,
                }
            )

    def exact_sequence_agreement(
        predictions: list[list[str] | None], targets: list[list[str]]
    ) -> dict[str, Any]:
        total = len(predictions) * len(targets)
        matches = sum(
            prediction is not None and prediction == target
            for prediction in predictions
            for target in targets
        )
        return {
            "matches": matches,
            "comparisons": total,
            "probability": matches / total if total else None,
        }

    def first_sequence_agreement(
        predictions: list[list[str] | None], targets: list[list[str]]
    ) -> dict[str, Any]:
        total = len(predictions) * len(targets)
        matches = sum(
            bool(prediction)
            and bool(target)
            and prediction[0] == target[0]
            for prediction in predictions
            for target in targets
        )
        return {
            "matches": matches,
            "comparisons": total,
            "probability": matches / total if total else None,
        }

    def task_implied_sequence(
        observation: str, action: str
    ) -> list[str] | None:
        paths = [
            path
            for path in valid_success_sequences(task, observation)
            if path and path[0] == action
        ]
        return list(paths[0]) if len(paths) == 1 else None

    structured_distribution_cells: list[dict[str, Any]] = []
    for source_index, source in enumerate(SOURCE_LABELS):
        donor = SOURCE_LABELS[1 - source_index]
        for observation_for_implied in observations:
            own_cell_rows = [
                cell
                for cell in structured_cells
                if cell["source"] == source
                and cell["observation"] == observation_for_implied
            ]
            donor_cell_rows = [
                cell
                for cell in structured_cells
                if cell["source"] == donor
                and cell["observation"] == observation_for_implied
            ]
            own_predictions: list[list[str] | None] = [
                list(cell["sequence"]) if cell["eligible"] else None
                for cell in own_cell_rows
            ]
            donor_predictions: list[list[str] | None] = [
                list(cell["sequence"]) if cell["eligible"] else None
                for cell in donor_cell_rows
            ]
            own_targets = [
                list(item["sequence"])
                for item in prospective
                if item["source"] == source
                and item["observation"] == observation_for_implied
            ]
            donor_targets = [
                list(item["sequence"])
                for item in prospective
                if item["source"] == donor
                and item["observation"] == observation_for_implied
            ]
            task_actions = [
                _atomic_category(row)
                for row in task_only_rows
                if row["observation"] == observation_for_implied
            ]
            task_implied_predictions = [
                task_implied_sequence(observation_for_implied, action)
                for action in task_actions
            ]
            own_exact = exact_sequence_agreement(own_predictions, own_targets)
            donor_carrier_exact = exact_sequence_agreement(
                donor_predictions, own_targets
            )
            task_exact = exact_sequence_agreement(
                task_implied_predictions, own_targets
            )
            own_first = first_sequence_agreement(own_predictions, own_targets)
            donor_first = first_sequence_agreement(donor_predictions, own_targets)
            task_first = first_sequence_agreement(
                task_implied_predictions, own_targets
            )
            dependency_rows = [
                _dependency_edge_agreement(prediction or [], own_targets)
                for prediction in own_predictions
            ]
            donor_dependency_rows = [
                _dependency_edge_agreement(prediction or [], own_targets)
                for prediction in donor_predictions
            ]
            task_dependency_rows = [
                _dependency_edge_agreement(prediction or [], own_targets)
                for prediction in task_implied_predictions
            ]

            def aggregate_edges(rows: list[dict[str, Any]]) -> dict[str, Any]:
                matches = sum(row["matches"] for row in rows)
                comparisons = sum(row["comparisons"] for row in rows)
                return {
                    "matches": matches,
                    "comparisons": comparisons,
                    "probability": matches / comparisons if comparisons else None,
                }

            structured_distribution_cells.append(
                {
                    "source": source,
                    "donor_source": donor,
                    "observation": observation_for_implied,
                    "own_structured_vs_own_prospective": own_exact,
                    "donor_structured_vs_own_prospective": donor_carrier_exact,
                    "task_only_implied_vs_own_prospective": task_exact,
                    "own_structured_vs_donor_prospective_diagnostic": exact_sequence_agreement(
                        own_predictions, donor_targets
                    ),
                    "own_minus_donor_carrier_probability": (
                        own_exact["probability"] - donor_carrier_exact["probability"]
                    ),
                    "own_minus_task_only_probability": (
                        own_exact["probability"] - task_exact["probability"]
                    ),
                    "first_action": {
                        "own_structured_vs_own": own_first,
                        "donor_structured_vs_own": donor_first,
                        "task_only_implied_vs_own": task_first,
                    },
                    "operation_dependency_edges": {
                        "own_structured_vs_own": aggregate_edges(dependency_rows),
                        "donor_structured_vs_own": aggregate_edges(
                            donor_dependency_rows
                        ),
                        "task_only_implied_vs_own": aggregate_edges(
                            task_dependency_rows
                        ),
                    },
                    "terminal_verify_rate": {
                        "own_structured": sum(
                            bool(prediction and prediction[-1] == VERIFY_TOKEN)
                            for prediction in own_predictions
                        )
                        / len(own_predictions),
                        "donor_structured": sum(
                            bool(prediction and prediction[-1] == VERIFY_TOKEN)
                            for prediction in donor_predictions
                        )
                        / len(donor_predictions),
                        "task_only_implied": sum(
                            bool(prediction and prediction[-1] == VERIFY_TOKEN)
                            for prediction in task_implied_predictions
                        )
                        / len(task_implied_predictions),
                    },
                    "within_structured_repeat_agreement": len(own_predictions) == 2
                    and all(prediction is not None for prediction in own_predictions)
                    and own_predictions[0] == own_predictions[1],
                    "task_only_implied_sequences": [
                        prediction if prediction is not None else INVALID_TRAJECTORY
                        for prediction in task_implied_predictions
                    ],
                }
            )

    visible = [row for row in readouts if row["arm"] == "visible_only"]
    probe = [row for row in readouts if row["arm"] == "probe_only"]
    carrier_categories = [_atomic_category(row) for row in atomic_rows]
    visible_categories = [_atomic_category(row) for row in visible]
    probe_categories = [_atomic_category(row) for row in probe]
    open_rows = [row for row in readouts if row["arm"] == "open"]
    full_rows = [
        row for row in readouts if row["arm"] == "full_task_semantic"
    ]

    def aggregate_comparisons(
        values: list[dict[str, Any]], key: str
    ) -> dict[str, Any]:
        metrics = [value[key] for value in values]
        matches = sum(metric["matches"] for metric in metrics)
        comparisons = sum(metric["comparisons"] for metric in metrics)
        return {
            "matches": matches,
            "comparisons": comparisons,
            "probability": matches / comparisons if comparisons else None,
        }

    structured_aggregate = {
        "full_sequence": {
            "own_structured_vs_own": aggregate_comparisons(
                structured_distribution_cells,
                "own_structured_vs_own_prospective",
            ),
            "donor_structured_vs_own": aggregate_comparisons(
                structured_distribution_cells,
                "donor_structured_vs_own_prospective",
            ),
            "task_only_implied_vs_own": aggregate_comparisons(
                structured_distribution_cells,
                "task_only_implied_vs_own_prospective",
            ),
        },
        "first_action": {
            baseline: aggregate_comparisons(
                [cell["first_action"] for cell in structured_distribution_cells],
                baseline,
            )
            for baseline in (
                "own_structured_vs_own",
                "donor_structured_vs_own",
                "task_only_implied_vs_own",
            )
        },
        "operation_dependency_edges": {
            baseline: aggregate_comparisons(
                [
                    cell["operation_dependency_edges"]
                    for cell in structured_distribution_cells
                ],
                baseline,
            )
            for baseline in (
                "own_structured_vs_own",
                "donor_structured_vs_own",
                "task_only_implied_vs_own",
            )
        },
        "terminal_verify": {
            baseline: sum(
                cell["terminal_verify_rate"][baseline]
                for cell in structured_distribution_cells
            )
            / len(structured_distribution_cells)
            for baseline in (
                "own_structured",
                "donor_structured",
                "task_only_implied",
            )
        },
        "within_structured_repeat_agreement": {
            "agreeing_cells": sum(
                cell["within_structured_repeat_agreement"]
                for cell in structured_distribution_cells
            ),
            "cells": len(structured_distribution_cells),
        },
    }

    evidence_layers = {
        "context_recovery": {
            "carrier_atomic_distribution": _distribution(carrier_categories),
            "visible_only_distribution": _distribution(visible_categories),
            "probe_only_distribution": _distribution(probe_categories),
            "carrier_open_completed": sum(row["eligible"] for row in open_rows),
            "carrier_open_total": len(open_rows),
            "full_task_semantic_upper_completed": sum(
                row["eligible"] for row in full_rows
            ),
            "full_task_semantic_upper_total": len(full_rows),
            "interpretation": "descriptive context recovery only",
        },
        "local_commitment": {
            "cells": local_cells,
            "distinguishing_observations": distinguishing,
            "interpretation": "descriptive own/donor/task-only comparison",
        },
        "conditional_policy": {
            "structured_cells": structured_cells,
            "distribution_cells": structured_distribution_cells,
            "aggregate_prospective_agreement": structured_aggregate,
            "eligible_structured_readouts": sum(row["eligible"] for row in structured_rows),
            "total_structured_readouts": len(structured_rows),
            "interpretation": "ordered branch policies; open prose excluded",
        },
        "executable_plan": {
            "structured_complete_valid_cells": sum(
                bool(cell["complete_valid_success"]) for cell in structured_cells
            ),
            "structured_cells_total": len(structured_cells),
            "prospective_successful_trajectories": sum(
                bool(row["complete_success_sequence"]) for row in prospective
            ),
            "prospective_trajectories_total": len(prospective),
            "structured_cells": structured_cells,
            "distribution_cells": structured_distribution_cells,
            "aggregate_prospective_agreement": structured_aggregate,
            "interpretation": "complete sequence agreement and stopping behavior",
        },
    }
    return {
        "schema_version": "native_executable_policy_scoring_v1",
        "evidence_layers": evidence_layers,
        "composite_pass_gate": None,
        "inference_level": "descriptive_feasibility_not_inferential",
    }


def _assert_no_raw_signatures(value: Any, signatures: Iterable[str | None]) -> None:
    serialized = json.dumps(value, ensure_ascii=True, sort_keys=True)
    for signature in signatures:
        if isinstance(signature, str) and signature and signature in serialized:
            raise RuntimeError("a raw source signature entered a summary artifact")


def render_review(summary: dict[str, Any]) -> str:
    generation = summary["generation"]
    scoring = summary.get("scoring") or {}
    layers = scoring.get("evidence_layers") or {}
    lines = [
        "# Native executable-policy pilot",
        "",
        f"- Freeze ID: `{summary['freeze_id']}`",
        f"- Model: `{MODEL}`",
        f"- Source generation eligible: `{generation['eligible']}`",
        f"- Logical requests: `{summary['logical_requests']}`",
        f"- Physical attempts: `{summary['physical_attempts']}`",
        "- Composite pass gate: `none`",
        "",
        "## Four evidence layers",
        "",
    ]
    if layers:
        context = layers["context_recovery"]
        executable = layers["executable_plan"]
        conditional = layers["conditional_policy"]
        full_sequence = executable["aggregate_prospective_agreement"][
            "full_sequence"
        ]["own_structured_vs_own"]
        lines.extend(
            [
                f"1. Context recovery: carrier open readouts completed {context['carrier_open_completed']}/{context['carrier_open_total']}; visible and probe-only distributions remain separate controls.",
                f"2. Local commitment: {len(layers['local_commitment']['cells'])} source/observation cells report own, donor, and task-only agreement separately.",
                f"3. Conditional policy: {conditional['eligible_structured_readouts']}/{conditional['total_structured_readouts']} structured readouts were strictly normalizable.",
                f"4. Executable plan: structured readouts matched their own prospective full trajectories in {full_sequence['matches']}/{full_sequence['comparisons']} pairings; {executable['structured_complete_valid_cells']}/{executable['structured_cells_total']} structured branch cells were ground-truth-valid, and {executable['prospective_successful_trajectories']}/{executable['prospective_trajectories_total']} prospective trajectories completed successfully.",
            ]
        )
    else:
        lines.append("Evidence collection did not begin because source eligibility failed.")
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "The layers are descriptive and independent. Open prose is exploratory; it does not support a conditional-policy or executable-plan claim. Raw signed carriers and exact provider payloads remain only in the ignored private execution directory.",
            "",
        ]
    )
    return "\n".join(lines)


def _logical_requests_attempted(store: CallStore | None) -> int:
    if not isinstance(store, CallStore):
        return 0
    return len(
        {
            re.sub(r"_attempt[1-9][0-9]*$", "", str(record.get("label") or ""))
            for record in store.records
            if isinstance(record, dict) and record.get("label")
        }
    )


def _terminalize(
    *,
    output_dir: Path,
    ledger: dict[str, Any],
    phase: str,
    exc: BaseException,
    store: CallStore | None,
) -> bool:
    ledger.update(
        {
            "final_status": f"execution_interrupted_{phase}",
            "terminal_for_consumed_freeze": True,
            "replacement_generation_permitted": False,
            "logical_requests": _logical_requests_attempted(store),
            "physical_attempts": len(store.records) if isinstance(store, CallStore) else 0,
            "completed_at": utc_now(),
        }
    )
    interruption = {
        "schema_version": "native_executable_policy_interruption_v1",
        "freeze_id": ledger.get("freeze_id"),
        "phase": phase,
        "terminal_for_consumed_freeze": True,
        "replacement_permitted": False,
        "exception_type_sha256": sha256_text(
            f"{type(exc).__module__}.{type(exc).__qualname__}"
        ),
        "logical_requests_attempted": ledger["logical_requests"],
        "physical_attempts_started": ledger["physical_attempts"],
    }
    try:
        write_json(output_dir / "execution_interrupted.json", interruption)
        write_json(output_dir / "execution_ledger.json", ledger)
    except OSError:
        return False
    return True


def execute_reviewed_freeze(
    *,
    repo_root: Path,
    freeze_dir: Path,
    expected_freeze_id: str,
    api_key: str,
    transport: Callable[..., InteractionHttpResult] = post_interaction,
    sleeper: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Consume and execute exactly one reviewed freeze, without replacement."""

    verification = verify_freeze(
        repo_root=repo_root,
        freeze_dir=freeze_dir,
        expected_freeze_id=expected_freeze_id,
        verify_source=True,
    )
    if not verification["valid"]:
        raise ValueError(
            "reviewed freeze verification failed: "
            + "; ".join(verification["errors"])
        )
    snapshot, definition = _read_verified_freeze_snapshot(
        freeze_dir=freeze_dir,
        expected_freeze_id=expected_freeze_id,
    )
    if not api_key:
        raise ValueError("an API key is required only for explicit execution")
    output_dir = execution_output_dir(
        repo_root=repo_root,
        freeze_id=expected_freeze_id,
    )
    _assert_path_has_no_link_ancestor(repo_root=repo_root, path=output_dir)
    _assert_execution_paths_are_ignored(repo_root=repo_root, output_dir=output_dir)

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    _assert_path_has_no_link_ancestor(repo_root=repo_root, path=output_dir.parent)
    output_dir.mkdir(exist_ok=False)
    claimed = True
    phase = "postclaim_setup"
    store: CallStore | None = None
    ledger: dict[str, Any] = {
        "schema_version": "native_executable_policy_execution_ledger_v1",
        "freeze_id": expected_freeze_id,
        "started_at": utc_now(),
        "final_status": "claimed_not_terminal",
        "terminal_for_consumed_freeze": False,
        "replacement_generation_permitted": False,
        "planned_logical_range": definition["planned_calls"][
            "eligible_execution_logical_range"
        ],
        "arbitrary_global_call_ceiling": None,
    }
    try:
        write_json(
            output_dir / "consumption_claim.json",
            {
                "schema_version": "native_executable_policy_consumption_claim_v1",
                "freeze_id": expected_freeze_id,
                "claim": "exclusive_canonical_directory_created_before_transport",
                "canonical_output_path_sha256": sha256_text(str(output_dir)),
            },
        )
        _copy_freeze(snapshot, output_dir)
        copied_verification = verify_freeze(
            repo_root=repo_root,
            freeze_dir=output_dir / "frozen_protocol",
            expected_freeze_id=expected_freeze_id,
            verify_source=False,
        )
        if not copied_verification["valid"]:
            raise ValueError(
                "copied freeze verification failed: "
                + "; ".join(copied_verification["errors"])
            )
        write_json(output_dir / "execution_ledger.json", ledger)
        store = CallStore(
            run_dir=output_dir,
            api_key=api_key,
            timeout=HTTP_TIMEOUT_SECONDS,
            delay_seconds=INTER_REQUEST_DELAY_SECONDS,
            transport=transport,
            max_attempts=MAX_ATTEMPTS_PER_LOGICAL_REQUEST,
            retry_backoff_seconds=RETRY_BACKOFF_SECONDS,
            sleeper=sleeper,
        )

        phase = "source_generation"
        sources, generation = generate_sources(
            definition=definition,
            store=store,
            run_dir=output_dir,
        )
        summary: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "freeze_id": expected_freeze_id,
            "model": MODEL,
            "generation": generation,
            "prospective": None,
            "readouts": None,
            "scoring": None,
            "logical_requests": _logical_requests_attempted(store),
            "physical_attempts": len(store.records),
            "composite_pass_gate": None,
        }
        if not generation["eligible"]:
            ledger.update(
                {
                    "final_status": "source_generation_ineligible",
                    "terminal_for_consumed_freeze": True,
                    "logical_requests": _logical_requests_attempted(store),
                    "physical_attempts": len(store.records),
                    "completed_at": utc_now(),
                }
            )
            signatures = [source.signature for source in sources.values()]
            _assert_no_raw_signatures(summary, signatures)
            write_json(output_dir / "summary.json", summary)
            write_text(output_dir / "review.md", render_review(summary))
            write_json(output_dir / "execution_ledger.json", ledger)
            return ledger

        phase = "prospective"
        prospective = run_all_prospective(
            definition=definition,
            sources=sources,
            store=store,
            run_dir=output_dir,
        )
        phase = "readouts"
        readouts, _private_text = run_readouts(
            definition=definition,
            sources=sources,
            store=store,
            run_dir=output_dir,
        )
        phase = "scoring"
        scoring = score_results(
            definition=definition,
            prospective=prospective,
            readouts=readouts,
        )
        summary.update(
            {
                "prospective": {
                    "trajectory_count": len(prospective),
                    "successful_count": sum(row["success"] for row in prospective),
                    "results_sha256": sha256_json(prospective),
                },
                "readouts": {
                    "row_count": len(readouts),
                    "eligible_count": sum(row["eligible"] for row in readouts),
                    "results_sha256": sha256_json(readouts),
                },
                "scoring": scoring,
                "logical_requests": _logical_requests_attempted(store),
                "physical_attempts": len(store.records),
            }
        )
        signatures = [source.signature for source in sources.values()]
        _assert_no_raw_signatures(summary, signatures)
        review = render_review(summary)
        _assert_no_raw_signatures(review, signatures)
        write_json(output_dir / "summary.json", summary)
        write_text(output_dir / "review.md", review)
        ledger.update(
            {
                "final_status": "evidence_collection_complete",
                "terminal_for_consumed_freeze": True,
                "logical_requests": _logical_requests_attempted(store),
                "physical_attempts": len(store.records),
                "summary_file_bytes_sha256": sha256_bytes(
                    (output_dir / "summary.json").read_bytes()
                ),
                "completed_at": utc_now(),
            }
        )
        write_json(output_dir / "execution_ledger.json", ledger)
        return ledger
    except BaseException as exc:
        if claimed:
            _terminalize(
                output_dir=output_dir,
                ledger=ledger,
                phase=phase,
                exc=exc,
                store=store,
            )
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    execute = subparsers.add_parser("execute-reviewed-freeze")
    execute.add_argument("--freeze-dir", required=True)
    execute.add_argument("--freeze-id", required=True)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    freeze_dir = Path(args.freeze_dir).resolve()
    verification = verify_freeze(
        repo_root=repo_root,
        freeze_dir=freeze_dir,
        expected_freeze_id=args.freeze_id,
        verify_source=True,
    )
    if not verification["valid"]:
        print(
            "Refusing execution because the reviewed freeze is invalid: "
            + "; ".join(verification["errors"]),
            file=sys.stderr,
        )
        return 2
    try:
        output_dir = execution_output_dir(
            repo_root=repo_root,
            freeze_id=args.freeze_id,
        )
        _assert_path_has_no_link_ancestor(repo_root=repo_root, path=output_dir)
        _assert_execution_paths_are_ignored(
            repo_root=repo_root,
            output_dir=output_dir,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Execution preflight failed: {exc}", file=sys.stderr)
        return 2
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("Set GEMINI_API_KEY to execute the reviewed freeze.", file=sys.stderr)
        return 2
    try:
        ledger = execute_reviewed_freeze(
            repo_root=repo_root,
            freeze_dir=freeze_dir,
            expected_freeze_id=args.freeze_id,
            api_key=api_key,
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError, DuplicateJsonKey) as exc:
        print(f"Execution failed: {exc}", file=sys.stderr)
        return 2
    print(f"Execution ledger: {output_dir / 'execution_ledger.json'}")
    return 0 if ledger.get("final_status") == "evidence_collection_complete" else 3


if __name__ == "__main__":
    raise SystemExit(main())
