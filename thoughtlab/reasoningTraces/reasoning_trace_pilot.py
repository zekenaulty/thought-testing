#!/usr/bin/env python3
"""Execute one reviewed READY-boundary reasoning-trace freeze.

This is the only network-capable module in the reasoning-trace experiment.  It
uses stateless Gemini Interactions requests, retains exact wire artifacts under
the ignored ``results/`` tree, and keeps diagnostic readouts separate from the
untouched full-history continuations.

No request built or submitted here contains tools, function calls, tool-choice
configuration, or a structured response format.
"""

from __future__ import annotations

import argparse
import copy
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
    post_interaction,
    response_steps,
    thought_signature_metadata,
)
from thoughtlab.reasoningTraces import reasoning_trace_protocol as protocol
from thoughtlab.stateTransitions.fork_pilot import (
    CallStore,
    write_bytes,
    write_json,
    write_text,
)


SCHEMA_VERSION = "bookforge_ready_trace_execution_v1"
INTER_REQUEST_DELAY_SECONDS = 1.0


class DuplicateJsonKey(ValueError):
    """Raised when a supposedly immutable JSON artifact has duplicate keys."""


@dataclass
class ParsedResponse:
    eligible: bool
    outcome: str
    reasons: list[str]
    steps: list[dict[str, Any]]
    thought_steps: list[dict[str, Any]]
    model_output_steps: list[dict[str, Any]]
    visible_text: str
    boundary_token: str | None
    signatures: list[str]
    safe_metadata: dict[str, Any]


@dataclass
class SourceRuntime:
    label: str
    eligible: bool
    full_history: list[dict[str, Any]]
    final_response_steps: list[dict[str, Any]]
    cumulative_thought_steps: list[dict[str, Any]]
    final_thought_steps: list[dict[str, Any]]
    final_model_output_steps: list[dict[str, Any]]
    signatures: list[str]
    summary: dict[str, Any]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def strict_json_loads(text: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DuplicateJsonKey(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=reject_duplicates)


def execution_output_dir(*, repo_root: Path, freeze_id: str) -> Path:
    if re.fullmatch(r"[0-9a-f]{64}", freeze_id) is None:
        raise ValueError("freeze ID must be a lowercase SHA-256 digest")
    return (
        repo_root.resolve()
        / "results"
        / "reasoning_trace_native"
        / freeze_id
    )


def _freeze_api() -> Any:
    # Kept lazy so the transport-free protocol and focused runner tests do not
    # depend on import order while the separately owned freezer is developed.
    from thoughtlab.reasoningTraces import reasoning_trace_freeze

    return reasoning_trace_freeze


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
            raise ValueError(
                f"execution path contains a link/reparse point: {current}"
            )
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
        output_dir / "semantic_readouts.private.json",
        output_dir / "continuations.private.json",
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
    freeze = _freeze_api()
    unsafe_component = freeze.first_link_or_reparse_component(freeze_dir)
    if unsafe_component is not None:
        raise ValueError(
            f"freeze path contains a link/reparse point: {unsafe_component}"
        )
    source = freeze_dir.resolve()
    if not source.is_dir():
        raise ValueError("freeze directory does not exist")
    entries = sorted(path.name for path in source.iterdir())
    if entries != sorted(freeze.SAFE_FREEZE_FILES):
        raise ValueError("freeze snapshot entries differ from the safe allowlist")

    snapshot: dict[str, bytes] = {}
    for name in freeze.SAFE_FREEZE_FILES:
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

    if protocol.sha256_bytes(snapshot[freeze.FREEZE_LOCK_NAME]) != expected_freeze_id:
        raise ValueError("freeze snapshot ID differs from the reviewed freeze ID")
    lock = strict_json_loads(snapshot[freeze.FREEZE_LOCK_NAME].decode("utf-8"))
    if not isinstance(lock, dict) or not isinstance(lock.get("files"), dict):
        raise ValueError("freeze lock is not an object with a file inventory")
    if set(lock["files"]) != set(freeze.SAFE_PAYLOAD_FILES):
        raise ValueError("freeze lock file inventory is incomplete")
    for name in freeze.SAFE_PAYLOAD_FILES:
        if protocol.sha256_bytes(snapshot[name]) != lock["files"].get(name):
            raise ValueError(f"freeze snapshot byte hash mismatch: {name}")

    definition = strict_json_loads(
        snapshot["experiment_definition.json"].decode("utf-8")
    )
    if not isinstance(definition, dict):
        raise ValueError("frozen experiment definition is not an object")
    errors = protocol.validate_experiment_definition(definition)
    if errors:
        raise ValueError(
            "frozen experiment definition is invalid: " + "; ".join(errors)
        )
    return snapshot, definition


def _copy_freeze(snapshot: dict[str, bytes], output_dir: Path) -> None:
    freeze = _freeze_api()
    target = output_dir / "frozen_protocol"
    target.mkdir(parents=True, exist_ok=False)
    for name in freeze.SAFE_FREEZE_FILES:
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
                    "transport_error_present": bool(
                        attempt.get("transport_error")
                    ),
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
        "selected_physical_call_number": call.get(
            "selected_physical_call_number"
        ),
        "selected_response_wire_sha256": call.get(
            "selected_response_wire_sha256"
        ),
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
        "returned_model_matches": payload.get("model") == protocol.MODEL,
        "returned_model_value_sha256": (
            protocol.sha256_text(str(payload.get("model")))
            if payload.get("model") is not None
            else None
        ),
        "usage_sha256": (
            protocol.sha256_json(usage) if usage is not None else None
        ),
        "provider_error_present": bool(provider_error),
        "provider_error_sha256": (
            protocol.sha256_text(provider_error) if provider_error else None
        ),
    }


def _invoke(
    *, store: CallStore, label: str, body: dict[str, Any]
) -> tuple[InteractionHttpResult, dict[str, Any]]:
    protocol.assert_no_function_or_tool_structure(body)
    result, call = store.invoke_logical(label=label, body=body)
    return result, _safe_call_summary(call)


def _exact_visible_text(
    model_output_steps: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    issues: list[str] = []
    if len(model_output_steps) != 1:
        issues.append("response did not contain exactly one model_output step")
        return "", issues
    content = model_output_steps[0].get("content")
    if not isinstance(content, list) or not content:
        issues.append("model_output content was not a nonempty array")
        return "", issues
    pieces: list[str] = []
    for index, block in enumerate(content):
        if (
            not isinstance(block, dict)
            or block.get("type") != "text"
            or not isinstance(block.get("text"), str)
        ):
            issues.append(f"model_output content block {index} was not text")
            continue
        pieces.append(block["text"])
    return "".join(pieces), issues


def _response_outcome(result: InteractionHttpResult, reasons: list[str]) -> str:
    if result.transport_error:
        return "transport_error"
    if result.http_status == 400:
        return "http_400_protocol_rejected"
    if result.http_status is None or not 200 <= result.http_status < 300:
        return "http_error"
    if result.response_parse_error or not isinstance(result.payload, dict):
        return "response_parse_error"
    if reasons:
        return "invalid_2xx_response"
    return "eligible"


def evaluate_response(
    *,
    result: InteractionHttpResult,
    require_source_boundary: bool = False,
    require_nonempty_output: bool = True,
) -> ParsedResponse:
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
    else:
        if payload.get("status") != "completed":
            reasons.append("interaction status was not completed")
        if payload.get("model") != protocol.MODEL:
            reasons.append("returned model did not match the frozen model")
        if payload.get("error") or payload.get("errors"):
            reasons.append("response contained a top-level error")

    steps: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        try:
            steps = response_steps(payload)
        except ValueError as exc:
            reasons.append(f"response steps shape was invalid: {exc}")
    unexpected_types = sorted(
        {
            str(step.get("type") or "")
            for step in steps
            if step.get("type") not in {"thought", "model_output"}
        }
    )
    if unexpected_types:
        reasons.append(f"unexpected response step types: {unexpected_types}")
    try:
        protocol.assert_no_function_or_tool_structure(steps)
    except ValueError as exc:
        reasons.append(str(exc))

    thought_steps = [
        copy.deepcopy(step) for step in steps if step.get("type") == "thought"
    ]
    model_outputs = [
        copy.deepcopy(step)
        for step in steps
        if step.get("type") == "model_output"
    ]
    signature_meta = thought_signature_metadata(thought_steps)
    signatures = [
        str(step["signature"])
        for step in thought_steps
        if isinstance(step.get("signature"), str) and step.get("signature")
    ]
    if require_source_boundary:
        reasons.extend(
            f"source detached carrier invalid: {reason}"
            for reason in protocol.validate_detached_thought_steps(thought_steps)
        )
    elif len(signature_meta) != len(thought_steps):
        reasons.append("a thought step lacked a nonempty signature")
    if any(step.get("summary") not in (None, "", []) for step in thought_steps):
        reasons.append("a thought step contained a nonempty readable summary")

    visible_text, output_issues = _exact_visible_text(model_outputs)
    reasons.extend(output_issues)
    if require_nonempty_output and not visible_text:
        reasons.append("visible model output was empty")

    boundary: str | None = None
    if require_source_boundary:
        boundary = protocol.normalize_boundary_token(visible_text)
        if boundary not in {"READY", "NOT_READY"}:
            reasons.append("visible output was not exactly READY or NOT_READY")

    # Deduplicate without obscuring deterministic reason order.
    reasons = list(dict.fromkeys(reasons))
    outcome = _response_outcome(result, reasons)
    return ParsedResponse(
        eligible=not reasons,
        outcome=outcome,
        reasons=reasons,
        steps=copy.deepcopy(steps),
        thought_steps=thought_steps,
        model_output_steps=model_outputs,
        visible_text=visible_text,
        boundary_token=boundary,
        signatures=signatures,
        safe_metadata={
            "http_status": result.http_status,
            "response_parse_error_present": bool(result.response_parse_error),
            "transport_error_present": bool(result.transport_error),
            "response_step_count": len(steps),
            "thought_step_count": len(thought_steps),
            "model_output_step_count": len(model_outputs),
            "response_signature_metadata": signature_meta,
            "visible_text_sha256": protocol.sha256_text(visible_text),
            "visible_text_chars": len(visible_text),
            "unexpected_step_types": unexpected_types,
            **_safe_payload_metadata(payload),
        },
    )


def _body_without_seed(body: dict[str, Any]) -> dict[str, Any]:
    clone = copy.deepcopy(body)
    config = clone.get("generation_config")
    if isinstance(config, dict):
        config.pop("seed", None)
    return clone


def generate_sources(
    *,
    definition: dict[str, Any],
    system_text: str,
    user_text: str,
    store: CallStore,
    run_dir: Path,
) -> tuple[dict[str, SourceRuntime], dict[str, Any], list[str]]:
    if protocol.validate_experiment_definition(definition):
        raise ValueError("cannot execute an invalid experiment definition")
    runtimes: dict[str, SourceRuntime] = {}
    source_summaries: list[dict[str, Any]] = []
    private_sources: dict[str, Any] = {}
    all_signatures: list[str] = []
    initial_bodies: dict[str, dict[str, Any]] = {}

    for source in protocol.SOURCE_LABELS:
        history: list[dict[str, Any]] = []
        final_response_steps: list[dict[str, Any]] = []
        final_thought_steps: list[dict[str, Any]] = []
        final_outputs: list[dict[str, Any]] = []
        source_signatures: list[str] = []
        round_summaries: list[dict[str, Any]] = []
        private_rounds: list[dict[str, Any]] = []
        ready = False
        terminal_reason: str | None = None

        for round_number in range(1, protocol.MAX_PLANNING_ROUNDS + 1):
            if round_number == 1:
                body = protocol.source_initial_body(
                    system_text=system_text,
                    user_text=user_text,
                    source=source,
                )
                initial_bodies[source] = copy.deepcopy(body)
            else:
                body = protocol.source_followup_body(
                    system_text=system_text,
                    full_history=history,
                    source=source,
                    round_number=round_number,
                )
                if body["input"][:-1] != history:
                    raise RuntimeError("source continuation changed the prior history")

            result, call = _invoke(
                store=store,
                label=f"source_{source}_round_{round_number}",
                body=body,
            )
            parsed = evaluate_response(
                result=result,
                require_source_boundary=True,
                require_nonempty_output=True,
            )
            source_signatures.extend(parsed.signatures)
            all_signatures.extend(parsed.signatures)
            round_summary = {
                "round_number": round_number,
                "eligible_response": parsed.eligible,
                "outcome": parsed.outcome,
                "ineligibility_reasons": parsed.reasons,
                "boundary_token": parsed.boundary_token,
                "request_input_sha256": protocol.sha256_json(body["input"]),
                "response_steps_sha256": protocol.sha256_json(parsed.steps),
                "call": call,
                **parsed.safe_metadata,
            }
            round_summaries.append(round_summary)
            private_rounds.append(
                {
                    "round_number": round_number,
                    "request_body": copy.deepcopy(body),
                    "response_steps": copy.deepcopy(parsed.steps),
                    "visible_text": parsed.visible_text,
                }
            )
            private_sources[source] = {"rounds": copy.deepcopy(private_rounds)}
            write_json(run_dir / "source_artifacts.private.json", private_sources)

            if not parsed.eligible:
                terminal_reason = "invalid_source_response"
                break
            history = [*copy.deepcopy(body["input"]), *copy.deepcopy(parsed.steps)]
            final_response_steps = copy.deepcopy(parsed.steps)
            final_thought_steps = copy.deepcopy(parsed.thought_steps)
            final_outputs = copy.deepcopy(parsed.model_output_steps)
            if parsed.boundary_token == "READY":
                ready = True
                break
            if round_number == protocol.MAX_PLANNING_ROUNDS:
                terminal_reason = "planning_round_limit_exhausted_without_READY"

        source_reasons: list[str] = []
        if not ready:
            source_reasons.append(
                terminal_reason or "source_did_not_reach_READY"
            )
        source_summary = {
            "schema_version": "bookforge_ready_trace_source_summary_v1",
            "source": source,
            "eligible": ready,
            "ineligibility_reasons": source_reasons,
            "rounds_attempted": len(round_summaries),
            "ready_round": (
                len(round_summaries) if ready else None
            ),
            "full_history_sha256": protocol.sha256_json(history),
            "full_history_step_count": len(history),
            "final_response_steps_sha256": protocol.sha256_json(
                final_response_steps
            ),
            "cumulative_thought_steps_sha256": protocol.sha256_json(
                [
                    step
                    for step in history
                    if isinstance(step, dict) and step.get("type") == "thought"
                ]
            ),
            "cumulative_thought_step_count": sum(
                1
                for step in history
                if isinstance(step, dict) and step.get("type") == "thought"
            ),
            "final_thought_steps_sha256": protocol.sha256_json(
                final_thought_steps
            ),
            "final_thought_step_count": len(final_thought_steps),
            "final_model_output_steps_sha256": protocol.sha256_json(
                final_outputs
            ),
            "final_model_output_step_count": len(final_outputs),
            "rounds": round_summaries,
        }
        source_summaries.append(source_summary)
        runtimes[source] = SourceRuntime(
            label=source,
            eligible=ready,
            full_history=copy.deepcopy(history),
            final_response_steps=final_response_steps,
            cumulative_thought_steps=[
                copy.deepcopy(step)
                for step in history
                if isinstance(step, dict) and step.get("type") == "thought"
            ],
            final_thought_steps=final_thought_steps,
            final_model_output_steps=final_outputs,
            signatures=source_signatures,
            summary=source_summary,
        )
        write_json(run_dir / "source_summaries.partial.json", source_summaries)

    input_hashes = {
        source: protocol.sha256_json(initial_bodies[source]["input"])
        for source in protocol.SOURCE_LABELS
        if source in initial_bodies
    }
    bodies_without_seed = {
        source: _body_without_seed(body) for source, body in initial_bodies.items()
    }
    generation = {
        "schema_version": "bookforge_ready_trace_generation_v1",
        "sources_scheduled": len(protocol.SOURCE_LABELS),
        "sources_attempted": len(source_summaries),
        "eligible_sources": sum(row["eligible"] for row in source_summaries),
        "both_sources_eligible": all(row["eligible"] for row in source_summaries),
        "any_source_eligible": any(row["eligible"] for row in source_summaries),
        "source_task_inputs_identical": (
            len(input_hashes) == 2 and len(set(input_hashes.values())) == 1
        ),
        "initial_requests_differ_only_by_seed": (
            len(bodies_without_seed) == 2
            and len(
                {
                    protocol.sha256_json(value)
                    for value in bodies_without_seed.values()
                }
            )
            == 1
        ),
        "sources": source_summaries,
    }
    write_json(run_dir / "source_summaries.json", source_summaries)
    return runtimes, generation, all_signatures


def _readout_protocol_class(arm: str) -> str:
    return {
        "signature_only": "accepted_experimental_primary",
        "full_prefix": "documented_valid_task_visible_upper_bound",
        "task_only": "documented_valid_fresh_analysis_control",
        "visible_ready_only": "accepted_experimental_ablation",
        "probe_only": "documented_valid_control",
    }[arm]


def _readout_body(
    *,
    schedule_row: dict[str, Any],
    runtimes: dict[str, SourceRuntime],
    system_text: str,
    user_text: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str | None]:
    arm = str(schedule_row["arm"])
    source_value = schedule_row.get("source")
    source = str(source_value) if source_value is not None else None
    probe_label = str(schedule_row["probe"])
    runtime = runtimes.get(source) if source is not None else None
    if source is not None and (runtime is None or not runtime.eligible):
        return None, [], "source_unavailable"

    if arm == "signature_only":
        assert runtime is not None and source is not None
        carrier = copy.deepcopy(runtime.cumulative_thought_steps)
        body = protocol.signature_readout_body(
            thought_steps=carrier,
            source=source,
            probe_label=probe_label,
        )
    elif arm == "full_prefix":
        assert runtime is not None and source is not None
        carrier = copy.deepcopy(runtime.full_history)
        body = protocol.full_prefix_control_body(
            system_text=system_text,
            full_history=carrier,
            source=source,
        )
    elif arm == "task_only":
        carrier = []
        body = protocol.task_only_control_body(
            system_text=system_text,
            user_text=user_text,
        )
    elif arm == "visible_ready_only":
        assert runtime is not None
        carrier = copy.deepcopy(runtime.final_model_output_steps)
        body = protocol.visible_ready_control_body(model_output_steps=carrier)
    elif arm == "probe_only":
        carrier = []
        body = protocol.probe_only_control_body()
    else:
        raise ValueError(f"unknown frozen readout arm: {arm}")

    protocol.assert_no_function_or_tool_structure(body)
    if arm in {"signature_only", "full_prefix", "visible_ready_only"}:
        if body["input"][:-1] != carrier:
            raise RuntimeError(f"{arm} request changed its carrier")
    if arm == "signature_only":
        if "system_instruction" in body:
            raise RuntimeError("signature-only request leaked the source system")
        if any(step.get("type") == "model_output" for step in carrier):
            raise RuntimeError("signature-only carrier included visible READY")
    return body, carrier, None


def _unavailable_readout_row(
    *, order: int, schedule_row: dict[str, Any], reason: str
) -> dict[str, Any]:
    return {
        "schema_version": "bookforge_ready_trace_readout_v1",
        "request_order": order,
        "arm": schedule_row.get("arm"),
        "source": schedule_row.get("source"),
        "probe": schedule_row.get("probe"),
        "protocol_class": _readout_protocol_class(str(schedule_row.get("arm"))),
        "fresh_stateless_request": True,
        "attempted": False,
        "eligible": False,
        "outcome": reason,
        "unavailable": True,
        "scientific_score": None,
        "ineligibility_reasons": [reason],
        "carrier_step_count": 0,
        "carrier_sha256": None,
        "carrier_signature_metadata": [],
        "call": None,
    }


def run_readouts(
    *,
    definition: dict[str, Any],
    runtimes: dict[str, SourceRuntime],
    system_text: str,
    user_text: str,
    store: CallStore,
    run_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    schedule = definition.get("schedule", {}).get("readouts")
    if not isinstance(schedule, list) or len(schedule) != 31:
        raise ValueError("frozen readout schedule must contain exactly 31 rows")
    rows: list[dict[str, Any]] = []
    private_rows: list[dict[str, Any]] = []
    all_signatures: list[str] = []

    for order, schedule_row in enumerate(schedule, 1):
        if not isinstance(schedule_row, dict):
            raise ValueError("frozen readout schedule contains a non-object")
        body, carrier, unavailable = _readout_body(
            schedule_row=schedule_row,
            runtimes=runtimes,
            system_text=system_text,
            user_text=user_text,
        )
        if unavailable is not None:
            rows.append(
                _unavailable_readout_row(
                    order=order,
                    schedule_row=schedule_row,
                    reason=unavailable,
                )
            )
            write_json(run_dir / "readout_results.partial.json", rows)
            continue
        assert body is not None
        arm = str(schedule_row["arm"])
        source = schedule_row.get("source")
        probe_label = str(schedule_row["probe"])
        result, call = _invoke(
            store=store,
            label=(
                f"readout_{order:02d}_{arm}_"
                f"{source or 'global'}_{probe_label}"
            ),
            body=body,
        )
        parsed = evaluate_response(
            result=result,
            require_source_boundary=False,
            require_nonempty_output=True,
        )
        all_signatures.extend(parsed.signatures)
        private_rows.append(
            {
                "request_order": order,
                "arm": arm,
                "source": source,
                "probe": probe_label,
                "visible_text": parsed.visible_text,
                "response_steps": copy.deepcopy(parsed.steps),
            }
        )
        write_json(run_dir / "semantic_readouts.private.json", private_rows)
        row = {
            "schema_version": "bookforge_ready_trace_readout_v1",
            "request_order": order,
            "arm": arm,
            "source": source,
            "probe": probe_label,
            "protocol_class": _readout_protocol_class(arm),
            "fresh_stateless_request": True,
            "attempted": True,
            "eligible": parsed.eligible,
            "outcome": parsed.outcome,
            "unavailable": not parsed.eligible,
            "scientific_score": None,
            "ineligibility_reasons": parsed.reasons,
            "carrier_step_count": len(carrier),
            "carrier_sha256": protocol.sha256_json(carrier),
            "carrier_signature_metadata": thought_signature_metadata(carrier),
            "call": call,
            **parsed.safe_metadata,
        }
        rows.append(row)
        write_json(run_dir / "readout_results.partial.json", rows)

    if len(rows) != 31:
        raise RuntimeError("readout schedule was not completely accounted for")
    write_json(run_dir / "readout_results.json", rows)
    private_path = run_dir / "semantic_readouts.private.json"
    if not private_path.exists():
        write_json(private_path, private_rows)
    seal = {
        "schema_version": "bookforge_ready_trace_readout_seal_v1",
        "sealed_at": utc_now(),
        "scheduled_rows": len(rows),
        "attempted_rows": sum(bool(row.get("attempted")) for row in rows),
        "eligible_rows": sum(bool(row.get("eligible")) for row in rows),
        "sanitized_rows_sha256": protocol.sha256_json(rows),
        "sanitized_file_bytes_sha256": protocol.sha256_bytes(
            (run_dir / "readout_results.json").read_bytes()
        ),
        "private_file_bytes_sha256": protocol.sha256_bytes(
            private_path.read_bytes()
        ),
        "physical_calls_completed_before_seal": len(store.records),
        "all_readouts_accounted_before_continuation": True,
    }
    write_json(run_dir / "readout_seal.json", seal)
    return rows, seal, all_signatures


def _verify_readout_seal(
    *, run_dir: Path, rows: list[dict[str, Any]], seal: dict[str, Any]
) -> None:
    sanitized_path = run_dir / "readout_results.json"
    private_path = run_dir / "semantic_readouts.private.json"
    if not sanitized_path.is_file() or not private_path.is_file():
        raise RuntimeError("readout files were not persisted before continuation")
    checks = (
        seal.get("scheduled_rows") == 31,
        seal.get("all_readouts_accounted_before_continuation") is True,
        seal.get("sanitized_rows_sha256") == protocol.sha256_json(rows),
        seal.get("sanitized_file_bytes_sha256")
        == protocol.sha256_bytes(sanitized_path.read_bytes()),
        seal.get("private_file_bytes_sha256")
        == protocol.sha256_bytes(private_path.read_bytes()),
    )
    if not all(checks):
        raise RuntimeError("readout seal verification failed")


def _unavailable_continuation_row(source: str, reason: str) -> dict[str, Any]:
    return {
        "schema_version": "bookforge_ready_trace_continuation_v1",
        "source": source,
        "attempted": False,
        "eligible": False,
        "outcome": reason,
        "unavailable": True,
        "scientific_score": None,
        "ineligibility_reasons": [reason],
        "call": None,
    }


def run_continuations(
    *,
    definition: dict[str, Any],
    runtimes: dict[str, SourceRuntime],
    system_text: str,
    readout_rows: list[dict[str, Any]],
    readout_seal: dict[str, Any],
    store: CallStore,
    run_dir: Path,
) -> tuple[list[dict[str, Any]], list[str]]:
    _verify_readout_seal(
        run_dir=run_dir,
        rows=readout_rows,
        seal=readout_seal,
    )
    order = definition.get("validation", {}).get("continuation_order")
    if not isinstance(order, list) or set(order) != set(protocol.SOURCE_LABELS):
        raise ValueError("frozen continuation order is invalid")
    rows: list[dict[str, Any]] = []
    private_rows: list[dict[str, Any]] = []
    all_signatures: list[str] = []

    for source in order:
        runtime = runtimes.get(source)
        if runtime is None or not runtime.eligible:
            rows.append(_unavailable_continuation_row(source, "source_unavailable"))
            continue
        current_history_hash = protocol.sha256_json(runtime.full_history)
        recorded_history_hash = runtime.summary.get("full_history_sha256")
        if current_history_hash != recorded_history_hash:
            raise RuntimeError(
                f"{source} exact READY history changed before continuation"
            )
        body = protocol.execution_body(
            system_text=system_text,
            full_history=runtime.full_history,
        )
        protocol.assert_no_function_or_tool_structure(body)
        if body["input"][:-1] != runtime.full_history:
            raise RuntimeError("execution request changed the exact READY history")
        if body["input"][-1] != protocol.user_step(protocol.EXECUTE_PROMPT):
            raise RuntimeError("execution request did not append the frozen prompt")
        result, call = _invoke(
            store=store,
            label=f"continuation_{source}",
            body=body,
        )
        parsed = evaluate_response(
            result=result,
            require_source_boundary=False,
            require_nonempty_output=True,
        )
        all_signatures.extend(parsed.signatures)
        private_rows.append(
            {
                "source": source,
                "visible_text": parsed.visible_text,
                "response_steps": copy.deepcopy(parsed.steps),
            }
        )
        write_json(run_dir / "continuations.private.json", private_rows)
        rows.append(
            {
                "schema_version": "bookforge_ready_trace_continuation_v1",
                "source": source,
                "attempted": True,
                "eligible": parsed.eligible,
                "outcome": parsed.outcome,
                "unavailable": not parsed.eligible,
                "scientific_score": None,
                "ineligibility_reasons": parsed.reasons,
                "exact_ready_history_sha256": protocol.sha256_json(
                    runtime.full_history
                ),
                "execution_request_input_sha256": protocol.sha256_json(
                    body["input"]
                ),
                "readout_seal_sha256": protocol.sha256_json(readout_seal),
                "call": call,
                **parsed.safe_metadata,
            }
        )

    if not (run_dir / "continuations.private.json").exists():
        write_json(run_dir / "continuations.private.json", private_rows)
    write_json(run_dir / "continuation_results.json", rows)
    return rows, all_signatures


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


def _outcome_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(
        sorted(
            Counter(str(row.get("outcome") or "unknown") for row in rows).items()
        )
    )


def build_summary(
    *,
    freeze_id: str,
    generation: dict[str, Any],
    readouts: list[dict[str, Any]],
    continuations: list[dict[str, Any]],
    readout_seal: dict[str, Any],
    store: CallStore,
) -> dict[str, Any]:
    controls = [row for row in readouts if row.get("arm") != "signature_only"]
    signature_rows = [
        row for row in readouts if row.get("arm") == "signature_only"
    ]
    controls_by_arm: dict[str, Any] = {}
    for arm in sorted({str(row.get("arm")) for row in controls}):
        arm_rows = [row for row in controls if row.get("arm") == arm]
        controls_by_arm[arm] = {
            "scheduled": len(arm_rows),
            "attempted": sum(bool(row.get("attempted")) for row in arm_rows),
            "eligible": sum(bool(row.get("eligible")) for row in arm_rows),
            "unavailable": sum(bool(row.get("unavailable")) for row in arm_rows),
            "outcomes": _outcome_counts(arm_rows),
            "score": None,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "freeze_id": freeze_id,
        "model": protocol.MODEL,
        "generation": generation,
        "readouts": {
            "scheduled": len(readouts),
            "attempted": sum(bool(row.get("attempted")) for row in readouts),
            "eligible": sum(bool(row.get("eligible")) for row in readouts),
            "unavailable": sum(bool(row.get("unavailable")) for row in readouts),
            "outcomes": _outcome_counts(readouts),
            "signature_only": {
                "scheduled": len(signature_rows),
                "attempted": sum(
                    bool(row.get("attempted")) for row in signature_rows
                ),
                "eligible": sum(
                    bool(row.get("eligible")) for row in signature_rows
                ),
                "outcomes": _outcome_counts(signature_rows),
            },
            "controls_by_arm": controls_by_arm,
            "seal_sha256": protocol.sha256_json(readout_seal),
        },
        "continuations": {
            "scheduled": len(continuations),
            "attempted": sum(
                bool(row.get("attempted")) for row in continuations
            ),
            "eligible": sum(bool(row.get("eligible")) for row in continuations),
            "unavailable": sum(
                bool(row.get("unavailable")) for row in continuations
            ),
            "outcomes": _outcome_counts(continuations),
        },
        "semantic_adjudication": {
            "status": "pending_postrun_claim_level_review",
            "codebook_frozen": True,
            "invalid_or_unavailable_cells_excluded_not_scored_zero": True,
            "composite_pass_gate": None,
        },
        "all_readouts_sealed_before_continuation": True,
        "logical_requests": _logical_requests_attempted(store),
        "physical_attempts": len(store.records),
    }


def _assert_no_raw_signatures(value: Any, signatures: Iterable[str]) -> None:
    serialized = json.dumps(value, ensure_ascii=True, sort_keys=True)
    for signature in signatures:
        if signature and signature in serialized:
            raise RuntimeError("a raw thought signature entered a sanitized artifact")


def render_review(summary: dict[str, Any]) -> str:
    generation = summary["generation"]
    readouts = summary["readouts"]
    continuations = summary["continuations"]
    lines = [
        "# BookForge READY-boundary reasoning trace",
        "",
        f"- Freeze ID: `{summary['freeze_id']}`",
        f"- Model: `{protocol.MODEL}`",
        (
            "- READY sources: "
            f"`{generation['eligible_sources']}/{generation['sources_scheduled']}`"
        ),
        (
            "- Signature-only readouts eligible: "
            f"`{readouts['signature_only']['eligible']}/"
            f"{readouts['signature_only']['scheduled']}`"
        ),
        (
            "- Continuations eligible: "
            f"`{continuations['eligible']}/{continuations['scheduled']}`"
        ),
        f"- Logical requests: `{summary['logical_requests']}`",
        f"- Physical attempts: `{summary['physical_attempts']}`",
        "- Composite pass gate: `none`",
        "",
        "## Interface availability",
        "",
    ]
    for arm, cell in readouts["controls_by_arm"].items():
        lines.append(
            f"- `{arm}`: {cell['eligible']}/{cell['scheduled']} eligible; "
            f"{cell['unavailable']} unavailable. No unavailable cell is scored as zero."
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "All readouts were persisted and sealed before either eligible exact-history continuation began. Semantic claim coding remains pending; this automatic report makes no chain-of-thought, plan-faithfulness, or debugging-usefulness judgment.",
            "",
            "Raw provider responses, signed carriers, and semantic texts remain only in the ignored private execution directory.",
            "",
        ]
    )
    return "\n".join(lines)


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
            "physical_attempts": (
                len(store.records) if isinstance(store, CallStore) else 0
            ),
            "completed_at": utc_now(),
        }
    )
    interruption = {
        "schema_version": "bookforge_ready_trace_interruption_v1",
        "freeze_id": ledger.get("freeze_id"),
        "phase": phase,
        "terminal_for_consumed_freeze": True,
        "replacement_permitted": False,
        "exception_type_sha256": protocol.sha256_text(
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


def _unrun_readouts(
    definition: dict[str, Any], run_dir: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    schedule = definition["schedule"]["readouts"]
    rows = [
        _unavailable_readout_row(
            order=index,
            schedule_row=row,
            reason="no_READY_source",
        )
        for index, row in enumerate(schedule, 1)
    ]
    write_json(run_dir / "readout_results.json", rows)
    write_json(run_dir / "semantic_readouts.private.json", [])
    seal = {
        "schema_version": "bookforge_ready_trace_readout_seal_v1",
        "sealed_at": utc_now(),
        "scheduled_rows": 31,
        "attempted_rows": 0,
        "eligible_rows": 0,
        "sanitized_rows_sha256": protocol.sha256_json(rows),
        "sanitized_file_bytes_sha256": protocol.sha256_bytes(
            (run_dir / "readout_results.json").read_bytes()
        ),
        "private_file_bytes_sha256": protocol.sha256_bytes(
            (run_dir / "semantic_readouts.private.json").read_bytes()
        ),
        "physical_calls_completed_before_seal": 0,
        "all_readouts_accounted_before_continuation": True,
    }
    write_json(run_dir / "readout_seal.json", seal)
    return rows, seal


def execute_reviewed_freeze(
    *,
    repo_root: Path,
    freeze_dir: Path,
    expected_freeze_id: str,
    api_key: str,
    transport: Callable[..., InteractionHttpResult] = post_interaction,
    sleeper: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Consume exactly one verified freeze and terminalize every claimed run."""

    freeze = _freeze_api()
    verification = freeze.verify_freeze(
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
    selected_task = protocol.verify_selected_task(repo_root)
    system_text = str(selected_task["system_text"])
    user_text = str(selected_task["user_text"])
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

    phase = "postclaim_setup"
    store: CallStore | None = None
    ledger: dict[str, Any] = {
        "schema_version": "bookforge_ready_trace_execution_ledger_v1",
        "freeze_id": expected_freeze_id,
        "started_at": utc_now(),
        "final_status": "claimed_not_terminal",
        "terminal_for_consumed_freeze": False,
        "replacement_generation_permitted": False,
        "planned_logical_range_when_both_sources_eligible": [35, 39],
    }
    try:
        write_json(
            output_dir / "consumption_claim.json",
            {
                "schema_version": "bookforge_ready_trace_consumption_claim_v1",
                "freeze_id": expected_freeze_id,
                "claim": "exclusive_canonical_directory_created_before_transport",
                "canonical_output_path_sha256": protocol.sha256_text(
                    str(output_dir)
                ),
            },
        )
        _copy_freeze(snapshot, output_dir)
        copied = freeze.verify_freeze(
            repo_root=repo_root,
            freeze_dir=output_dir / "frozen_protocol",
            expected_freeze_id=expected_freeze_id,
            verify_source=False,
        )
        if not copied["valid"]:
            raise ValueError(
                "copied freeze verification failed: "
                + "; ".join(copied["errors"])
            )
        write_json(output_dir / "execution_ledger.json", ledger)
        store = CallStore(
            run_dir=output_dir,
            api_key=api_key,
            timeout=protocol.HTTP_TIMEOUT_SECONDS,
            delay_seconds=INTER_REQUEST_DELAY_SECONDS,
            transport=transport,
            max_attempts=protocol.MAX_ATTEMPTS_PER_LOGICAL_REQUEST,
            retry_backoff_seconds=protocol.RETRY_BACKOFF_SECONDS,
            sleeper=sleeper,
        )

        phase = "source_generation"
        runtimes, generation, source_signatures = generate_sources(
            definition=definition,
            system_text=system_text,
            user_text=user_text,
            store=store,
            run_dir=output_dir,
        )
        all_signatures = list(source_signatures)

        phase = "readouts"
        if generation["any_source_eligible"]:
            readouts, seal, readout_signatures = run_readouts(
                definition=definition,
                runtimes=runtimes,
                system_text=system_text,
                user_text=user_text,
                store=store,
                run_dir=output_dir,
            )
            all_signatures.extend(readout_signatures)
        else:
            readouts, seal = _unrun_readouts(definition, output_dir)

        phase = "continuations"
        continuations, continuation_signatures = run_continuations(
            definition=definition,
            runtimes=runtimes,
            system_text=system_text,
            readout_rows=readouts,
            readout_seal=seal,
            store=store,
            run_dir=output_dir,
        )
        all_signatures.extend(continuation_signatures)

        phase = "summary"
        summary = build_summary(
            freeze_id=expected_freeze_id,
            generation=generation,
            readouts=readouts,
            continuations=continuations,
            readout_seal=seal,
            store=store,
        )
        _assert_no_raw_signatures(summary, all_signatures)
        review = render_review(summary)
        _assert_no_raw_signatures(review, all_signatures)
        write_json(output_dir / "summary.json", summary)
        write_text(output_dir / "review.md", review)

        ledger.update(
            {
                "final_status": (
                    "evidence_collection_complete"
                    if generation["any_source_eligible"]
                    else "no_READY_source_terminal"
                ),
                "terminal_for_consumed_freeze": True,
                "replacement_generation_permitted": False,
                "all_readouts_sealed_before_continuation": True,
                "logical_requests": _logical_requests_attempted(store),
                "physical_attempts": len(store.records),
                "summary_file_bytes_sha256": protocol.sha256_bytes(
                    (output_dir / "summary.json").read_bytes()
                ),
                "completed_at": utc_now(),
            }
        )
        write_json(output_dir / "execution_ledger.json", ledger)
        return ledger
    except BaseException as exc:
        _terminalize(
            output_dir=output_dir,
            ledger=ledger,
            phase=phase,
            exc=exc,
            store=store,
        )
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    execute = subparsers.add_parser("execute-reviewed-freeze")
    execute.add_argument("--freeze-dir", required=True)
    execute.add_argument("--freeze-id", required=True)
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[2]
    freeze_dir = Path(args.freeze_dir).resolve()
    freeze = _freeze_api()
    verification = freeze.verify_freeze(
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
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"Execution failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(ledger, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
