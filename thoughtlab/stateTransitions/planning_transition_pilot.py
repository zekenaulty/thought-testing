#!/usr/bin/env python3
"""Executor and scorer for an already reviewed native S0-S6 freeze.

This module never creates or alters a protocol manifest. Execution requires the
exact freeze directory and its externally reviewed freeze ID.
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from thoughtlab.gemini_interactions import (
    InteractionHttpResult,
    build_interaction_body,
    error_text,
    output_text,
    post_interaction,
    response_steps,
    select_steps,
    thought_signature_metadata,
    user_step,
)
from thoughtlab.opaque_ids import is_opaque_id
from thoughtlab.stateTransitions.fork_pilot import (
    CallStore,
    CheckpointRuntime,
    write_bytes,
    write_json,
    write_text,
)
from thoughtlab.stateTransitions.planning_transition_freeze import (
    FREEZE_LOCK_NAME,
    SAFE_FREEZE_FILES,
    SAFE_PAYLOAD_FILES,
    first_link_or_reparse_component,
    verify_freeze,
)
from thoughtlab.stateTransitions.planning_transition_probes import (
    ACK_RESPONSE_FORMAT,
    PROBES,
)
from thoughtlab.stateTransitions.planning_transition_protocol import (
    ARMS,
    CHECKPOINTS,
    CONTROL_ARMS,
    DELTA_ARMS,
    EXPECTED_CHANGED_FIELDS,
    FIELDS,
    HTTP_TIMEOUT_SECONDS,
    INTER_REQUEST_DELAY_SECONDS,
    MAX_ATTEMPTS_PER_LOGICAL_REQUEST,
    MODEL,
    RETRY_BACKOFF_SECONDS,
    SOURCE_ARMS,
    DuplicateJsonKey,
    canonical_json_bytes,
    generation_config,
    sha256_bytes,
    sha256_json,
    sha256_text,
    strict_json_loads,
    validate_manifest,
)
from thoughtlab.stateTransitions.planning_transition_score import (
    COLLECTION_KEYS,
    derive_delta,
    empty_shape,
    expected_normalized,
    normalized_state,
    score_planning_answer,
    validate_planning_answer,
)


@dataclass
class ProbeObservation:
    normalized: dict[str, Any] | None
    safe_metadata: dict[str, Any]


def _is_link_or_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0) & reparse_flag
    )


def _minimal_git_environment() -> dict[str, str]:
    """Return only OS-launch variables; never enumerate credential-bearing env."""
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


def execution_output_dir(*, repo_root: Path, freeze_id: str) -> Path:
    if re.fullmatch(r"[0-9a-f]{64}", freeze_id) is None:
        raise ValueError("freeze ID must be a lowercase SHA-256 digest")
    return (
        repo_root.resolve()
        / "results"
        / "planning_transition"
        / "executions"
        / freeze_id
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


def _assert_execution_paths_are_ignored(*, repo_root: Path, output_dir: Path) -> None:
    root = repo_root.resolve()
    candidates = (
        output_dir,
        output_dir / "execution_ledger.json",
        output_dir / "run_01" / "raw" / "0001.request.json",
        output_dir / "run_01" / "raw" / "0001.response.bin",
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
            raise RuntimeError(
                "could not verify Git-ignore protection for private execution path"
            )


def _read_verified_freeze_snapshot(
    *, freeze_dir: Path, expected_freeze_id: str
) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Read once, cryptographically verify, and parse the exact bytes to execute."""
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
        fingerprint_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        )
        fingerprint_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        )
        if fingerprint_before != fingerprint_after or _is_link_or_reparse_point(path):
            raise ValueError(f"freeze payload changed while being read: {name}")
        snapshot[name] = data

    lock_bytes = snapshot[FREEZE_LOCK_NAME]
    if sha256_bytes(lock_bytes) != expected_freeze_id:
        raise ValueError("freeze snapshot ID differs from the reviewed freeze ID")
    try:
        lock = strict_json_loads(lock_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, DuplicateJsonKey) as exc:
        raise ValueError("freeze lock is not strict UTF-8 JSON") from exc
    if not isinstance(lock, dict) or not isinstance(lock.get("files"), dict):
        raise ValueError("freeze lock is not an object with a file inventory")
    if set(lock["files"]) != set(SAFE_PAYLOAD_FILES):
        raise ValueError("freeze lock file inventory is incomplete")
    for name in SAFE_PAYLOAD_FILES:
        expected_hash = lock["files"].get(name)
        if not isinstance(expected_hash, str) or sha256_bytes(snapshot[name]) != expected_hash:
            raise ValueError(f"freeze snapshot byte hash mismatch: {name}")

    try:
        manifest = strict_json_loads(snapshot["manifest.json"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, DuplicateJsonKey) as exc:
        raise ValueError("frozen manifest is not strict UTF-8 JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError("frozen manifest is not an object")
    manifest_errors = validate_manifest(manifest)
    if manifest_errors:
        raise ValueError("frozen manifest is invalid: " + "; ".join(manifest_errors))
    return snapshot, manifest


def _safe_call_summary(call: dict[str, Any]) -> dict[str, Any]:
    attempts = call.get("attempts") if isinstance(call, dict) else None
    safe_attempts = []
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
                    "selected_for_logical_result": bool(
                        attempt.get("selected_for_logical_result")
                    ),
                }
            )
    return {
        "logical_request_id": call.get("logical_request_id"),
        "attempt_count": call.get("attempt_count"),
        "selected_attempt": call.get("selected_attempt"),
        "selected_physical_call_number": call.get(
            "selected_physical_call_number"
        ),
        "selected_response_wire_sha256": call.get(
            "selected_response_wire_sha256"
        ),
        "selection_reason": call.get("selection_reason"),
        "retried": bool(call.get("retried")),
        "actual_backoff_seconds": list(call.get("actual_backoff_seconds") or []),
        "request_wire_sha256": call.get("request_wire_sha256"),
        "request_wire_bytes": call.get("request_wire_bytes"),
        "attempts": safe_attempts,
    }


def _safe_payload_metadata(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "interaction_status_class": None,
            "returned_model_matches": False,
            "usage_sha256": None,
            "provider_error_present": False,
            "provider_error_sha256": None,
        }
    status = payload.get("status")
    status_class = status if status in {"completed", "incomplete", "failed"} else "other"
    provider_error = error_text(payload)
    usage = payload.get("usage")
    return {
        "interaction_status_class": status_class,
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


def _model_output_validation(
    steps: list[dict[str, Any]],
) -> tuple[str, list[str], str]:
    output_steps = select_steps(steps, {"model_output"})
    issues: list[str] = []
    if len(output_steps) != 1:
        issues.append("response did not contain exactly one model_output step")
    for index, step in enumerate(output_steps):
        content = step.get("content")
        if not isinstance(content, list):
            issues.append(f"model_output[{index}].content was not an array")
            continue
        if len(content) != 1:
            issues.append(
                f"model_output[{index}].content did not contain exactly one block"
            )
        for block_index, block in enumerate(content):
            if not isinstance(block, dict):
                issues.append(
                    f"model_output[{index}].content[{block_index}] was not an object"
                )
            elif block.get("type") != "text" or not isinstance(
                block.get("text"), str
            ):
                issues.append(
                    f"model_output[{index}].content[{block_index}] was not text"
                )
    serialized = json.dumps(output_steps, ensure_ascii=True, sort_keys=True)
    return output_text({"steps": output_steps}), issues, serialized


def _checkpoint_eligibility(
    *,
    result: InteractionHttpResult,
    payload: dict[str, Any] | None,
    steps: list[dict[str, Any]] | None,
    request_body: dict[str, Any],
    trial: dict[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    reasons: list[str] = []
    visible, output_issues, serialized_outputs = _model_output_validation(steps or [])
    if result.http_status is None or not 200 <= result.http_status < 300:
        reasons.append("generation request was not HTTP 2xx")
    if result.transport_error:
        reasons.append("transport error")
    if result.response_parse_error:
        reasons.append("response body was not a JSON object")
    if not isinstance(payload, dict):
        reasons.append("missing response payload")
    else:
        if payload.get("status") != "completed":
            reasons.append("interaction status was not completed")
        if payload.get("model") != MODEL:
            reasons.append("returned model did not match the frozen model")
        if payload.get("error") or payload.get("errors"):
            reasons.append("response contained a top-level error")
    if request_body.get("store") is not False:
        reasons.append("store was not false")
    if request_body.get("stream") is not False:
        reasons.append("stream was not false")
    if request_body.get("background") is not False:
        reasons.append("background was not false")
    if "previous_interaction_id" in request_body:
        reasons.append("previous_interaction_id was present")

    thought_steps = select_steps(steps or [], {"thought"})
    output_steps = select_steps(steps or [], {"model_output"})
    signature_meta = thought_signature_metadata(steps or [])
    if not thought_steps:
        reasons.append("no thought step")
    if len(signature_meta) != len(thought_steps):
        reasons.append("a thought step lacked a nonempty signature")
    if any(step.get("summary") not in (None, [], "") for step in thought_steps):
        reasons.append("a thought step contained a nonempty summary")
    reasons.extend(output_issues)
    unexpected_types = sorted(
        {
            str(step.get("type") or "")
            for step in (steps or [])
            if step.get("type") not in {"thought", "model_output"}
        }
    )
    if unexpected_types:
        reasons.append("response contained an unexpected step type")

    expected_ack_canonical = canonical_json_bytes({"ack": True})
    visible_json_parse_valid = False
    actual_ack_canonical: bytes | None = None
    try:
        parsed_visible = strict_json_loads(visible)
        visible_json_parse_valid = True
        actual_ack_canonical = canonical_json_bytes(parsed_visible)
    except (TypeError, ValueError, RecursionError):
        pass
    ack_canonical_match = actual_ack_canonical == expected_ack_canonical
    visible_text_exact = visible.encode("utf-8") == expected_ack_canonical
    if not ack_canonical_match:
        reasons.append(
            "visible output did not canonically match the required acknowledgement object"
        )

    leak_markers = [
        *trial["id_universe"],
        *(str(value) for value in trial["utilities"].values()),
        "candidate",
        "condition",
        "viable",
        "nonviable",
        "selected",
        "utility",
        "ranking",
    ]
    leak_count = sum(
        1 for marker in leak_markers if marker.lower() in serialized_outputs.lower()
    )
    if leak_count:
        reasons.append("visible output leaked prescribed state")

    return reasons, {
        "visible_output_sha256": sha256_text(visible),
        "visible_output_chars": len(visible),
        "visible_ack_json_parse_valid": visible_json_parse_valid,
        "visible_ack_canonical_match": ack_canonical_match,
        "visible_ack_canonical_sha256": (
            sha256_bytes(actual_ack_canonical)
            if actual_ack_canonical is not None
            else None
        ),
        "expected_ack_canonical_sha256": sha256_bytes(expected_ack_canonical),
        "visible_ack_post_extraction_text_exact": visible_text_exact,
        "visible_leak_marker_count": leak_count,
        "thought_step_count": len(thought_steps),
        "model_output_step_count": len(output_steps),
        "model_output_structure_issues": output_issues,
        "signature_metadata": signature_meta,
        "unexpected_step_type_count": len(unexpected_types),
    }


def generate_trial(
    *,
    run_id: str,
    trial: dict[str, Any],
    generation_tasks: list[dict[str, Any]],
    store: CallStore,
) -> tuple[dict[str, CheckpointRuntime], list[dict[str, Any]]]:
    runtimes: dict[str, CheckpointRuntime] = {}
    summaries: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
    tasks = {
        task["checkpoint"]: task
        for task in generation_tasks
        if task.get("trial") == trial["trial_id"]
    }
    if set(tasks) != set(CHECKPOINTS):
        raise ValueError(f"{run_id}/{trial['trial_id']}: generation tasks are incomplete")

    for checkpoint_index, checkpoint in enumerate(CHECKPOINTS):
        task = tasks[checkpoint]
        previous_history = copy.deepcopy(history)
        input_steps = previous_history + [user_step(trial["prompts"][checkpoint])]
        if input_steps[:-1] != previous_history:
            raise RuntimeError("generation input did not preserve the exact prior prefix")
        body = build_interaction_body(
            model=MODEL,
            input_steps=input_steps,
            generation_config=generation_config(
                trial["generation_seeds"][checkpoint]
            ),
            response_format=ACK_RESPONSE_FORMAT,
        )
        result, call = store.invoke_logical(
            label=task["logical_label"],
            body=body,
        )
        steps: list[dict[str, Any]] | None = None
        response_shape_error = False
        if isinstance(result.payload, dict):
            try:
                steps = response_steps(result.payload)
            except ValueError:
                response_shape_error = True
        reasons, details = _checkpoint_eligibility(
            result=result,
            payload=result.payload,
            steps=steps,
            request_body=body,
            trial=trial,
        )
        if response_shape_error:
            reasons.append("response steps shape was invalid")
        selected_steps = copy.deepcopy(steps or [])
        full_history = input_steps + selected_steps
        latest_thoughts = select_steps(selected_steps, {"thought"})
        latest_outputs = select_steps(selected_steps, {"model_output"})
        cumulative_thoughts = select_steps(full_history, {"thought"})
        parent_checkpoint = CHECKPOINTS[checkpoint_index - 1] if checkpoint_index else None
        parent_prefix_exact = bool(
            checkpoint_index == 0
            or (
                parent_checkpoint in runtimes
                and previous_history == runtimes[parent_checkpoint].full_history
            )
        )
        if not parent_prefix_exact:
            reasons.append("stateless generation lineage was not exact")
        summary = {
            "schema_version": "native_planning_generation_checkpoint_v1",
            "run_id": run_id,
            "trial_id": trial["trial_id"],
            "checkpoint": checkpoint,
            "parent_checkpoint": parent_checkpoint,
            "parent_prefix_exact": parent_prefix_exact,
            "eligible": not reasons,
            "ineligibility_reasons": reasons,
            "prompt_sha256": sha256_text(trial["prompts"][checkpoint]),
            "request_input_sha256": sha256_json(input_steps),
            "parent_prefix_sha256": sha256_json(previous_history),
            "response_steps_sha256": sha256_json(selected_steps),
            "full_prefix_sha256": sha256_json(full_history),
            "latest_thought_sha256": sha256_json(latest_thoughts),
            "cumulative_thought_sha256": sha256_json(cumulative_thoughts),
            "latest_output_sha256": sha256_json(latest_outputs),
            "http_status": result.http_status,
            "response_parse_error_present": bool(result.response_parse_error),
            "transport_error_present": bool(result.transport_error),
            "call": _safe_call_summary(call),
            **_safe_payload_metadata(result.payload),
            **details,
        }
        summaries.append(summary)
        runtimes[checkpoint] = CheckpointRuntime(
            checkpoint_id=checkpoint,
            full_history=full_history,
            response_steps=selected_steps,
            latest_thoughts=latest_thoughts,
            cumulative_thoughts=cumulative_thoughts,
            latest_outputs=latest_outputs,
            summary=summary,
        )
        if reasons:
            return runtimes, summaries
        history = full_history
    return runtimes, summaries


def generation_status(
    *,
    checkpoint_summaries: list[dict[str, Any]],
    runtimes: dict[str, dict[str, CheckpointRuntime]],
) -> dict[str, Any]:
    expected_keys = {
        (trial, checkpoint)
        for trial in ("target", "donor")
        for checkpoint in CHECKPOINTS
    }
    keys = [
        (row.get("trial_id"), row.get("checkpoint"))
        for row in checkpoint_summaries
        if isinstance(row, dict)
    ]
    matrix_complete = (
        len(keys) == 14 and set(keys) == expected_keys and len(set(keys)) == 14
    )
    response_hashes = [
        row.get("response_steps_sha256")
        for row in checkpoint_summaries
        if isinstance(row, dict)
    ]
    thought_hashes = [
        row.get("latest_thought_sha256")
        for row in checkpoint_summaries
        if isinstance(row, dict)
    ]
    artifacts_distinct = bool(
        matrix_complete
        and all(isinstance(value, str) and value for value in response_hashes)
        and all(isinstance(value, str) and value for value in thought_hashes)
        and len(set(response_hashes)) == 14
        and len(set(thought_hashes)) == 14
    )
    lineages_exact = bool(
        matrix_complete
        and all(row.get("parent_prefix_exact") for row in checkpoint_summaries)
        and all(set(runtimes.get(trial, {})) == set(CHECKPOINTS) for trial in ("target", "donor"))
    )
    checkpoint_eligible = bool(
        matrix_complete and all(row.get("eligible") for row in checkpoint_summaries)
    )
    return {
        "matrix_complete": matrix_complete,
        "checkpoint_eligible": checkpoint_eligible,
        "artifacts_pairwise_distinct": artifacts_distinct,
        "lineages_exact": lineages_exact,
        "eligible": checkpoint_eligible and artifacts_distinct and lineages_exact,
        "checkpoint_count": len(checkpoint_summaries),
    }


def arm_steps(
    *,
    arm: str,
    checkpoint: str,
    target_runtimes: dict[str, CheckpointRuntime],
    donor_runtimes: dict[str, CheckpointRuntime],
) -> list[dict[str, Any]]:
    target = target_runtimes[checkpoint]
    donor = donor_runtimes[checkpoint]
    if arm == "target_full_prefix":
        return copy.deepcopy(target.full_history)
    if arm == "target_latest_thought":
        return copy.deepcopy(target.latest_thoughts)
    if arm == "target_cumulative_thought":
        return copy.deepcopy(target.cumulative_thoughts)
    if arm == "target_visible_only":
        return copy.deepcopy(target.latest_outputs)
    if arm == "probe_only":
        return []
    if arm == "wrong_trial_latest":
        return copy.deepcopy(donor.latest_thoughts)
    if arm == "donor_full_prefix":
        return copy.deepcopy(donor.full_history)
    raise ValueError(f"unknown carrier arm: {arm}")


def _safe_normalized_summary(
    kind: str,
    normalized: dict[str, Any] | None,
    prescribed_ids: set[str],
) -> dict[str, Any] | None:
    if not isinstance(normalized, dict):
        return None
    collections = normalized.get("collections")
    if not isinstance(collections, dict):
        collections = {}
    prescribed_id_values: list[str] = []
    unknown_canonical_hashes: list[str] = []
    noncanonical_hashes: list[str] = []
    collection_lengths: dict[str, int | None] = {}
    for key, values in collections.items():
        if not isinstance(values, list):
            collection_lengths[str(key)] = None
            continue
        collection_lengths[str(key)] = len(values)
        for value in values:
            if not isinstance(value, str):
                continue
            if is_opaque_id(value):
                if value in prescribed_ids:
                    prescribed_id_values.append(value)
                else:
                    unknown_canonical_hashes.append(sha256_text(value))
            else:
                noncanonical_hashes.append(sha256_text(value))
    knowledge = normalized.get("knowledge")
    return {
        "kind": kind,
        "schema_valid": bool(normalized.get("schema_valid")),
        "errors": list(normalized.get("errors") or []),
        "knowledge": knowledge if knowledge in {"known", "unknown"} else None,
        "noncanonical_knowledge_sha256": sha256_text(str(knowledge))
        if knowledge not in {None, "known", "unknown"}
        else None,
        "collection_lengths": collection_lengths,
        "returned_prescribed_ids": prescribed_id_values,
        "unknown_canonical_value_sha256": sorted(unknown_canonical_hashes),
        "duplicate_unknown_canonical_value_sha256": sorted(
            {
                value
                for value in unknown_canonical_hashes
                if unknown_canonical_hashes.count(value) > 1
            }
        ),
        "duplicate_prescribed_ids": sorted(
            {
                value
                for value in prescribed_id_values
                if prescribed_id_values.count(value) > 1
            }
        ),
        "noncanonical_value_sha256": sorted(noncanonical_hashes),
    }


def _normalized_canonical_ids(normalized: dict[str, Any]) -> list[str]:
    collections = normalized.get("collections")
    if not isinstance(collections, dict):
        return []
    return [
        value
        for values in collections.values()
        if isinstance(values, list)
        for value in values
        if isinstance(value, str) and is_opaque_id(value)
    ]


def _safe_raw_id_metadata(text: str, prescribed_ids: set[str]) -> dict[str, Any]:
    escape_normalized = re.sub(
        r"\\u([0-9A-Fa-f]{4})",
        lambda match: chr(int(match.group(1), 16)),
        text,
    )
    canonical_ids = re.findall(
        r"ID_[0-9A-HJKMNP-TV-Z]{26}", escape_normalized
    )
    prescribed_tokens = [value for value in canonical_ids if value in prescribed_ids]
    unknown_hashes = [
        sha256_text(value) for value in canonical_ids if value not in prescribed_ids
    ]
    return {
        "raw_prescribed_id_tokens": prescribed_tokens,
        "raw_unknown_canonical_id_sha256": unknown_hashes,
        "raw_prescribed_id_hits": sorted(set(prescribed_tokens)),
    }


def _safe_response_wire_id_metadata(
    *,
    http_status: int | None,
    text: str,
    prescribed_ids: set[str],
) -> dict[str, Any]:
    """Retain safe ID evidence from a successful wire body across parse failures."""
    eligible_text = (
        text
        if http_status is not None and 200 <= http_status < 300
        else ""
    )
    metadata = _safe_raw_id_metadata(eligible_text, prescribed_ids)
    return {
        "response_wire_prescribed_id_tokens": metadata[
            "raw_prescribed_id_tokens"
        ],
        "response_wire_unknown_canonical_id_sha256": metadata[
            "raw_unknown_canonical_id_sha256"
        ],
        "response_wire_prescribed_id_hits": metadata[
            "raw_prescribed_id_hits"
        ],
    }


def _safe_parsed_id_metadata(value: Any, prescribed_ids: set[str]) -> dict[str, Any]:
    """Find IDs in all parsed JSON strings, including Unicode-escaped spellings."""
    canonical_ids: list[str] = []
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            pending.extend(current.keys())
            pending.extend(current.values())
        elif isinstance(current, (list, tuple)):
            pending.extend(current)
        elif isinstance(current, str):
            canonical_ids.extend(re.findall(r"ID_[0-9A-HJKMNP-TV-Z]{26}", current))
    prescribed_tokens = [item for item in canonical_ids if item in prescribed_ids]
    unknown_hashes = [
        sha256_text(item) for item in canonical_ids if item not in prescribed_ids
    ]
    return {
        "parsed_prescribed_id_tokens": prescribed_tokens,
        "parsed_unknown_canonical_id_sha256": unknown_hashes,
    }


def _safe_parsed_collection_metadata(kind: str, value: Any) -> dict[str, Any]:
    """Hash noncanonical strings supplied in this probe's expected collections."""
    if isinstance(value, dict):
        items = list(value.items())
    elif isinstance(value, list) and all(
        isinstance(item, tuple) and len(item) == 2 for item in value
    ):
        items = value
    else:
        items = []
    expected_keys = set(COLLECTION_KEYS.get(kind, ()))
    noncanonical: list[str] = []
    for key, collection in items:
        if key not in expected_keys:
            continue
        values = collection if isinstance(collection, list) else [collection]
        for item in values:
            if isinstance(item, str) and not is_opaque_id(item):
                noncanonical.append(sha256_text(item))
    return {
        "parsed_collection_noncanonical_value_sha256": noncanonical,
    }


def _permissive_duplicate_json_metadata(
    *, text: str, kind: str, prescribed_ids: set[str]
) -> dict[str, Any]:
    try:
        value = json.loads(text, object_pairs_hook=lambda pairs: pairs)
    except (ValueError, RecursionError):
        return {
            **_safe_parsed_id_metadata(None, prescribed_ids),
            **_safe_parsed_collection_metadata(kind, None),
        }
    return {
        **_safe_parsed_id_metadata(value, prescribed_ids),
        **_safe_parsed_collection_metadata(kind, value),
    }


def _parse_probe_result(
    *,
    result: InteractionHttpResult,
    kind: str,
    prescribed_ids: set[str],
) -> ProbeObservation:
    payload = result.payload
    base: dict[str, Any] = {
        "http_status": result.http_status,
        "transport_error_present": bool(result.transport_error),
        "response_parse_error_present": bool(result.response_parse_error),
        **_safe_raw_id_metadata("", prescribed_ids),
        **_safe_response_wire_id_metadata(
            http_status=result.http_status,
            text=result.raw_body if isinstance(result.raw_body, str) else "",
            prescribed_ids=prescribed_ids,
        ),
        **_safe_parsed_id_metadata(None, prescribed_ids),
        **_safe_parsed_collection_metadata(kind, None),
        **_safe_payload_metadata(payload),
    }
    if result.transport_error:
        return ProbeObservation(None, {**base, "evaluable": False, "outcome": "transport_error"})
    if result.http_status is None or not 200 <= result.http_status < 300:
        if result.http_status == 400:
            outcome = "protocol_rejected"
        elif result.http_status == 429:
            outcome = "rate_limited"
        elif result.http_status is not None and result.http_status >= 500:
            outcome = "provider_error"
        else:
            outcome = "http_error"
        return ProbeObservation(None, {**base, "evaluable": False, "outcome": outcome})
    if result.response_parse_error or not isinstance(payload, dict):
        return ProbeObservation(
            None,
            {**base, "evaluable": False, "outcome": "response_parse_error"},
        )
    raw_steps = payload.get("steps")
    salvage_text = output_text(
        {"steps": raw_steps if isinstance(raw_steps, list) else []}
    )
    salvage_metadata = {
        **_safe_raw_id_metadata(salvage_text, prescribed_ids),
        "response_text_sha256": sha256_text(salvage_text),
        "response_text_chars": len(salvage_text),
    }
    try:
        steps = response_steps(payload)
    except ValueError:
        return ProbeObservation(
            None,
            {
                **base,
                **salvage_metadata,
                "evaluable": False,
                "outcome": "response_shape_error",
            },
        )
    unexpected_types = {
        str(step.get("type") or "")
        for step in steps
        if step.get("type") not in {"thought", "model_output"}
    }
    text, output_issues, _ = _model_output_validation(steps)
    answer_metadata = {
        **_safe_raw_id_metadata(text, prescribed_ids),
        "response_text_sha256": sha256_text(text),
        "response_text_chars": len(text),
        "response_step_count": len(steps),
        "response_signature_metadata": thought_signature_metadata(steps),
    }
    if payload.get("status") != "completed":
        return ProbeObservation(
            None,
            {
                **base,
                **answer_metadata,
                "evaluable": False,
                "outcome": "interaction_incomplete",
            },
        )
    if payload.get("model") != MODEL:
        return ProbeObservation(
            None,
            {
                **base,
                **answer_metadata,
                "evaluable": False,
                "outcome": "model_mismatch",
            },
        )
    if payload.get("error") or payload.get("errors"):
        return ProbeObservation(
            None,
            {
                **base,
                **answer_metadata,
                "evaluable": False,
                "outcome": "response_reported_error",
            },
        )
    if unexpected_types or output_issues:
        return ProbeObservation(
            None,
            {
                **base,
                **answer_metadata,
                "evaluable": False,
                "outcome": "response_shape_error",
                "shape_issue_count": len(unexpected_types) + len(output_issues),
            },
        )
    if not text:
        return ProbeObservation(
            None,
            {
                **base,
                **answer_metadata,
                "evaluable": False,
                "outcome": "empty_response",
            },
        )
    try:
        parsed = strict_json_loads(text)
    except DuplicateJsonKey:
        return ProbeObservation(
            None,
            {
                **base,
                **answer_metadata,
                **_permissive_duplicate_json_metadata(
                    text=text,
                    kind=kind,
                    prescribed_ids=prescribed_ids,
                ),
                "evaluable": False,
                "outcome": "duplicate_json_key",
            },
        )
    except (ValueError, RecursionError):
        return ProbeObservation(
            None,
            {
                **base,
                **answer_metadata,
                "evaluable": False,
                "outcome": "invalid_json",
            },
        )
    normalized = validate_planning_answer(kind, parsed)
    evaluable = bool(normalized.get("schema_valid"))
    metadata = {
        **base,
        **answer_metadata,
        **_safe_parsed_id_metadata(parsed, prescribed_ids),
        **_safe_parsed_collection_metadata(kind, parsed),
        "evaluable": evaluable,
        "outcome": "scored" if evaluable else "schema_invalid",
        "parsed_canonical_json_sha256": sha256_json(parsed),
        "normalized": _safe_normalized_summary(kind, normalized, prescribed_ids),
    }
    return ProbeObservation(normalized, metadata)


def _score_field_for_trial(
    *,
    field: str,
    normalized: dict[str, Any],
    checkpoint: str,
    trial: dict[str, Any],
    other_trial: dict[str, Any],
) -> dict[str, Any]:
    return score_planning_answer(
        kind=PROBES[field]["kind"],
        normalized=normalized,
        expected=trial["truth"][checkpoint][field],
        candidate_universe=set(trial["truth"][checkpoint]["candidate_registry"]["ids"]),
        source_id_universe=set(trial["id_universe"]),
        condition_id=trial["condition_id"],
        other_trial_universe=set(other_trial["id_universe"]),
    )


def _partial_future_alignment(
    *,
    field: str,
    normalized: dict[str, Any],
    current_truth: dict[str, Any],
    future_truth: dict[str, Any],
) -> dict[str, Any]:
    returned = set(_normalized_canonical_ids(normalized))

    def truth_ids(value: dict[str, Any]) -> set[str]:
        return {
            item
            for key, collection in value.items()
            if key != "knowledge" and isinstance(collection, list)
            for item in collection
            if isinstance(item, str)
        }

    current_ids = truth_ids(current_truth)
    future_ids = truth_ids(future_truth)
    result: dict[str, Any] = {
        "future_only_id_hits": sorted(returned & (future_ids - current_ids)),
    }
    collections = normalized.get("collections")
    if not isinstance(collections, dict):
        return result
    if field == "utility_ranking" and isinstance(
        collections.get("ids_high_to_low"), list
    ):
        actual = [
            value
            for value in collections["ids_high_to_low"]
            if isinstance(value, str) and is_opaque_id(value)
        ]
        actual_pos = {value: index for index, value in enumerate(actual)}
        current = list(current_truth["ids_high_to_low"])
        future = list(future_truth["ids_high_to_low"])
        current_pos = {value: index for index, value in enumerate(current)}
        future_pos = {value: index for index, value in enumerate(future)}
        matches = []
        shared = sorted(set(current) & set(future))
        for left_index, left in enumerate(shared):
            for right in shared[left_index + 1 :]:
                current_order = current_pos[left] < current_pos[right]
                future_order = future_pos[left] < future_pos[right]
                if (
                    current_order != future_order
                    and left in actual_pos
                    and right in actual_pos
                    and (actual_pos[left] < actual_pos[right]) == future_order
                ):
                    matches.append([left, right])
        result["future_pairwise_reversal_matches"] = matches
    elif field == "viability_partition":
        matches = []
        actual_viable = set(collections.get("viable_ids") or [])
        actual_nonviable = set(collections.get("nonviable_ids") or [])
        current_viable = set(current_truth["viable_ids"])
        future_viable = set(future_truth["viable_ids"])
        for identifier in sorted(current_ids & future_ids):
            if (identifier in current_viable) == (identifier in future_viable):
                continue
            if (identifier in actual_viable) == (identifier in future_viable) and (
                identifier in actual_viable or identifier in actual_nonviable
            ):
                matches.append(identifier)
        result["future_partition_matches"] = matches
    return result


def _timeline_diagnostics(
    *,
    field: str,
    checkpoint: str,
    normalized: dict[str, Any] | None,
    trial: dict[str, Any],
    other_trial: dict[str, Any],
    current_exact: bool,
) -> dict[str, Any]:
    if not isinstance(normalized, dict) or not normalized.get("schema_valid"):
        return {
            "exact_truth_checkpoints": [],
            "future_exact_hits": [],
            "stale_exact_hits": [],
            "premature_ids": [],
            "partial_future_alignment": {},
        }
    checkpoint_index = CHECKPOINTS.index(checkpoint)
    exact_checkpoints = []
    for candidate_checkpoint in CHECKPOINTS:
        score = _score_field_for_trial(
            field=field,
            normalized=normalized,
            checkpoint=candidate_checkpoint,
            trial=trial,
            other_trial=other_trial,
        )
        if score.get("exact"):
            exact_checkpoints.append(candidate_checkpoint)
    current_truth = trial["truth"][checkpoint][field]
    future_exact_hits = [
        candidate
        for candidate in exact_checkpoints
        if CHECKPOINTS.index(candidate) > checkpoint_index
        and trial["truth"][candidate][field] != current_truth
        and not current_exact
    ]
    stale_exact_hits = [
        candidate
        for candidate in exact_checkpoints
        if CHECKPOINTS.index(candidate) < checkpoint_index
        and trial["truth"][candidate][field] != current_truth
        and not current_exact
    ]
    returned_ids = set(_normalized_canonical_ids(normalized))
    premature_ids = sorted(
        identifier
        for identifier in returned_ids & set(trial["id_universe"])
        if CHECKPOINTS.index(trial["introduction_checkpoint"][identifier])
        > checkpoint_index
    )
    partial: dict[str, Any] = {}
    if not current_exact:
        for future_checkpoint in CHECKPOINTS[checkpoint_index + 1 :]:
            future_truth = trial["truth"][future_checkpoint][field]
            if future_truth == current_truth:
                continue
            alignment = _partial_future_alignment(
                field=field,
                normalized=normalized,
                current_truth=current_truth,
                future_truth=future_truth,
            )
            if any(alignment.values()):
                partial[future_checkpoint] = alignment
    return {
        "exact_truth_checkpoints": exact_checkpoints,
        "future_exact_hits": future_exact_hits,
        "stale_exact_hits": stale_exact_hits,
        "premature_ids": premature_ids,
        "partial_future_alignment": partial,
    }


def run_probes(
    *,
    run_attempt: dict[str, Any],
    target_runtimes: dict[str, CheckpointRuntime],
    donor_runtimes: dict[str, CheckpointRuntime],
    store: CallStore,
) -> tuple[list[dict[str, Any]], dict[tuple[str, str, str], ProbeObservation]]:
    rows: list[dict[str, Any]] = []
    observations: dict[tuple[str, str, str], ProbeObservation] = {}
    target = run_attempt["trials"]["target"]
    donor = run_attempt["trials"]["donor"]
    prescribed_ids = set(target["id_universe"]) | set(donor["id_universe"])

    for task in run_attempt["probe_tasks"]:
        checkpoint = task["checkpoint"]
        field = task["field"]
        arm = task["arm"]
        spec = PROBES[field]
        carrier = arm_steps(
            arm=arm,
            checkpoint=checkpoint,
            target_runtimes=target_runtimes,
            donor_runtimes=donor_runtimes,
        )
        input_steps = carrier + [user_step(spec["prompt"])]
        body = build_interaction_body(
            model=MODEL,
            input_steps=input_steps,
            generation_config=generation_config(task["seed"]),
            response_format=spec["response_format"],
        )
        result, call = store.invoke_logical(
            label=task["logical_label"],
            body=body,
        )
        observation = _parse_probe_result(
            result=result,
            kind=spec["kind"],
            prescribed_ids=prescribed_ids,
        )
        key = (checkpoint, field, arm)
        observations[key] = observation
        score_target = None
        score_donor = None
        if isinstance(observation.normalized, dict):
            score_target = _score_field_for_trial(
                field=field,
                normalized=observation.normalized,
                checkpoint=checkpoint,
                trial=target,
                other_trial=donor,
            )
            score_donor = _score_field_for_trial(
                field=field,
                normalized=observation.normalized,
                checkpoint=checkpoint,
                trial=donor,
                other_trial=target,
            )
        source_trial_name = SOURCE_ARMS[arm]
        source_score = (
            score_target
            if source_trial_name == "target"
            else score_donor
            if source_trial_name == "donor"
            else None
        )
        if arm in CONTROL_ARMS:
            timeline = None
        elif source_trial_name == "target":
            timeline = _timeline_diagnostics(
                field=field,
                checkpoint=checkpoint,
                normalized=observation.normalized,
                trial=target,
                other_trial=donor,
                current_exact=bool(source_score and source_score.get("exact")),
            )
        elif source_trial_name == "donor":
            timeline = _timeline_diagnostics(
                field=field,
                checkpoint=checkpoint,
                normalized=observation.normalized,
                trial=donor,
                other_trial=target,
                current_exact=bool(source_score and source_score.get("exact")),
            )
        else:
            timeline = None
        protocol_class = (
            "documented_valid"
            if arm in {"target_full_prefix", "donor_full_prefix", "probe_only"}
            else "accepted_or_rejected_experimental"
        )
        row = {
            "schema_version": "native_planning_probe_result_v1",
            "request_order": task["request_order"],
            "checkpoint": checkpoint,
            "field": field,
            "probe_kind": spec["kind"],
            "arm": arm,
            "protocol_class": protocol_class,
            "fresh_stateless_request": True,
            "carrier_source_trial": source_trial_name,
            "carrier_source_checkpoint": checkpoint
            if source_trial_name is not None
            else None,
            "carrier_step_count": len(carrier),
            "carrier_sha256": sha256_json(carrier),
            "carrier_signature_metadata": thought_signature_metadata(carrier),
            "call": _safe_call_summary(call),
            **observation.safe_metadata,
            "score_target": score_target,
            "score_donor": score_donor,
            "score_source": source_score,
            "timeline": timeline,
        }
        rows.append(row)
        write_json(store.run_dir / "probe_results.partial.json", rows)
    return rows, observations


def _result_index(
    rows: list[dict[str, Any]],
) -> tuple[
    dict[tuple[str, str, str], dict[str, Any]],
    list[str],
    int,
]:
    index: dict[tuple[str, str, str], dict[str, Any]] = {}
    duplicates: list[str] = []
    malformed = 0
    for row in rows:
        if not isinstance(row, dict) or not all(
            isinstance(row.get(key), str) for key in ("checkpoint", "field", "arm")
        ):
            malformed += 1
            continue
        key = (row["checkpoint"], row["field"], row["arm"])
        if key in index:
            duplicates.append("/".join(key))
            continue
        index[key] = row
    return index, sorted(duplicates), malformed


def _score_exact(row: dict[str, Any] | None, basis: str = "source") -> bool:
    if not isinstance(row, dict):
        return False
    score = row.get(f"score_{basis}")
    return bool(isinstance(score, dict) and score.get("exact"))


def _string_list(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _row_identifier_evidence(row: dict[str, Any]) -> dict[str, set[str]]:
    normalized = row.get("normalized")
    normalized = normalized if isinstance(normalized, dict) else {}
    wire_reviewed = _string_list(
        row.get("response_wire_prescribed_id_tokens")
    )
    raw_reviewed = _string_list(row.get("raw_prescribed_id_tokens"))
    parsed_reviewed = _string_list(row.get("parsed_prescribed_id_tokens"))
    normalized_reviewed = _string_list(normalized.get("returned_prescribed_ids"))
    wire_unknown = _string_list(
        row.get("response_wire_unknown_canonical_id_sha256")
    )
    raw_unknown = _string_list(row.get("raw_unknown_canonical_id_sha256"))
    parsed_unknown = _string_list(row.get("parsed_unknown_canonical_id_sha256"))
    normalized_unknown = _string_list(
        normalized.get("unknown_canonical_value_sha256")
    )
    reviewed_occurrences = (
        wire_reviewed + raw_reviewed + parsed_reviewed + normalized_reviewed
    )
    unknown_occurrences = (
        wire_unknown + raw_unknown + parsed_unknown + normalized_unknown
    )
    return {
        "returned_reviewed_ids": set(reviewed_occurrences),
        "unknown_canonical_sha256": set(unknown_occurrences),
        "duplicate_reviewed_ids": set(
            _string_list(normalized.get("duplicate_prescribed_ids"))
        )
        | {
            value
            for values in (
                wire_reviewed,
                raw_reviewed,
                parsed_reviewed,
                normalized_reviewed,
            )
            for value in values
            if values.count(value) > 1
        },
        "duplicate_unknown_canonical_sha256": set(
            _string_list(normalized.get("duplicate_unknown_canonical_value_sha256"))
        )
        | {
            value
            for values in (
                wire_unknown,
                raw_unknown,
                parsed_unknown,
                normalized_unknown,
            )
            for value in values
            if values.count(value) > 1
        },
        "noncanonical_value_sha256": set(
            _string_list(normalized.get("noncanonical_value_sha256"))
        )
        | set(
            _string_list(row.get("parsed_collection_noncanonical_value_sha256"))
        ),
    }


def _score_cross_truth(
    *,
    field: str,
    normalized: dict[str, Any] | None,
    checkpoint: str,
    trial: dict[str, Any],
    other_trial: dict[str, Any],
) -> bool:
    if not isinstance(normalized, dict):
        return False
    score = _score_field_for_trial(
        field=field,
        normalized=normalized,
        checkpoint=checkpoint,
        trial=trial,
        other_trial=other_trial,
    )
    return bool(score.get("exact"))


def derive_delta_rows(
    *,
    run_attempt: dict[str, Any],
    rows: list[dict[str, Any]],
    observations: dict[tuple[str, str, str], ProbeObservation],
) -> list[dict[str, Any]]:
    index, _, _ = _result_index(rows)
    deltas: list[dict[str, Any]] = []
    target = run_attempt["trials"]["target"]
    donor = run_attempt["trials"]["donor"]
    for arm in DELTA_ARMS:
        source_name = SOURCE_ARMS[arm]
        if source_name not in {"target", "donor"}:
            raise ValueError(f"delta arm {arm} has no truth source")
        source = target if source_name == "target" else donor
        other = donor if source_name == "target" else target
        for transition_index in range(1, len(CHECKPOINTS)):
            before_checkpoint = CHECKPOINTS[transition_index - 1]
            after_checkpoint = CHECKPOINTS[transition_index]
            transition = f"{before_checkpoint}->{after_checkpoint}"
            for field in FIELDS:
                kind = PROBES[field]["kind"]
                before_key = (before_checkpoint, field, arm)
                after_key = (after_checkpoint, field, arm)
                before_row = index.get(before_key)
                after_row = index.get(after_key)
                before_exact = _score_exact(before_row)
                after_exact = _score_exact(after_row)
                before_observation = observations.get(before_key)
                after_observation = observations.get(after_key)
                before_state = (
                    normalized_state(kind, before_observation.normalized)
                    if before_exact
                    and isinstance(before_observation, ProbeObservation)
                    and isinstance(before_observation.normalized, dict)
                    else None
                )
                after_state = (
                    normalized_state(kind, after_observation.normalized)
                    if after_exact
                    and isinstance(after_observation, ProbeObservation)
                    and isinstance(after_observation.normalized, dict)
                    else None
                )
                actual_delta = (
                    derive_delta(kind, before_state, after_state)
                    if before_state is not None and after_state is not None
                    else None
                )
                expected_before = expected_normalized(
                    kind, source["truth"][before_checkpoint][field]
                )
                expected_after = expected_normalized(
                    kind, source["truth"][after_checkpoint][field]
                )
                expected_delta = derive_delta(kind, expected_before, expected_after)
                changed = field in EXPECTED_CHANGED_FIELDS[transition]
                cross_before_to_after = _score_cross_truth(
                    field=field,
                    normalized=before_observation.normalized
                    if isinstance(before_observation, ProbeObservation)
                    else None,
                    checkpoint=after_checkpoint,
                    trial=source,
                    other_trial=other,
                )
                cross_after_to_before = _score_cross_truth(
                    field=field,
                    normalized=after_observation.normalized
                    if isinstance(after_observation, ProbeObservation)
                    else None,
                    checkpoint=before_checkpoint,
                    trial=source,
                    other_trial=other,
                )
                directional_localized = bool(
                    changed
                    and before_exact
                    and after_exact
                    and not cross_before_to_after
                    and not cross_after_to_before
                )
                deltas.append(
                    {
                        "schema_version": "native_planning_delta_result_v1",
                        "arm": arm,
                        "source_trial": source_name,
                        "transition": transition,
                        "before_checkpoint": before_checkpoint,
                        "after_checkpoint": after_checkpoint,
                        "field": field,
                        "changed_expected": changed,
                        "before_source_exact": before_exact,
                        "after_source_exact": after_exact,
                        "actual_delta": actual_delta,
                        "expected_delta": expected_delta,
                        "delta_exact": bool(
                            before_exact
                            and after_exact
                            and actual_delta == expected_delta
                        ),
                        "preceding_artifact_exact_for_new_truth": cross_before_to_after,
                        "new_artifact_exact_for_preceding_truth": cross_after_to_before,
                        "directional_localization_exact": directional_localized,
                    }
                )
    return deltas


def _control_row_clean(
    row: dict[str, Any] | None,
    observation: ProbeObservation | None,
    field: str,
) -> bool:
    evidence = _row_identifier_evidence(row) if isinstance(row, dict) else {}
    return bool(
        isinstance(row, dict)
        and row.get("evaluable")
        and isinstance(observation, ProbeObservation)
        and isinstance(observation.normalized, dict)
        and empty_shape(PROBES[field]["kind"], observation.normalized)
        and not any(evidence.values())
    )


def _agreement(
    *,
    field: str,
    left: ProbeObservation | None,
    right: ProbeObservation | None,
) -> bool:
    if not isinstance(left, ProbeObservation) or not isinstance(right, ProbeObservation):
        return False
    if not isinstance(left.normalized, dict) or not isinstance(right.normalized, dict):
        return False
    kind = PROBES[field]["kind"]

    def state(normalized: dict[str, Any]) -> dict[str, Any] | None:
        if not normalized.get("schema_valid"):
            return None
        collections = normalized.get("collections")
        keys = {
            "id_set": ("ids",),
            "ranking": ("ids_high_to_low",),
            "viability": ("viable_ids", "nonviable_ids"),
        }.get(kind, ())
        if not isinstance(collections, dict) or any(
            not isinstance(collections.get(key), list) for key in keys
        ):
            return None
        values = {
            key: list(collections[key])
            if kind == "ranking"
            else sorted(collections[key])
            for key in keys
        }
        return {"knowledge": normalized.get("knowledge"), **values}

    left_state = state(left.normalized)
    right_state = state(right.normalized)
    return left_state is not None and left_state == right_state


def summarize_results(
    *,
    run_attempt: dict[str, Any],
    generation: dict[str, Any],
    checkpoint_summaries: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    observations: dict[tuple[str, str, str], ProbeObservation],
    delta_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    index, duplicate_keys, malformed_rows = _result_index(rows)
    expected_keys = {
        (checkpoint, field, arm)
        for checkpoint in CHECKPOINTS
        for field in FIELDS
        for arm in ARMS
    }
    matrix_complete = bool(
        not duplicate_keys
        and not malformed_rows
        and len(rows) == 196
        and set(index) == expected_keys
    )

    def exact_count(arm: str, basis: str = "source", checkpoints=CHECKPOINTS, fields=FIELDS) -> int:
        return sum(
            _score_exact(index.get((checkpoint, field, arm)), basis)
            for checkpoint in checkpoints
            for field in fields
        )

    target_full_exact = exact_count("target_full_prefix", "target")
    donor_full_exact = exact_count("donor_full_prefix", "donor")
    controls = {
        arm: {
            "clean": sum(
                _control_row_clean(
                    index.get((checkpoint, field, arm)),
                    observations.get((checkpoint, field, arm)),
                    field,
                )
                for checkpoint in CHECKPOINTS
                for field in FIELDS
            ),
            "total": 28,
        }
        for arm in CONTROL_ARMS
    }
    controls_clean = sum(value["clean"] for value in controls.values())

    latest_arm = "target_latest_thought"
    replication_registry = exact_count(
        latest_arm,
        checkpoints=CHECKPOINTS[2:],
        fields=("candidate_registry",),
    )
    replication_ranking = exact_count(
        latest_arm,
        checkpoints=CHECKPOINTS[2:],
        fields=("utility_ranking",),
    )
    replication_selected = exact_count(
        latest_arm,
        checkpoints=("S6",),
        fields=("selected_candidate",),
    )
    replication_total = (
        replication_registry + replication_ranking + replication_selected
    )
    component_counts = {
        "replication_registry_s2_s6": {"exact": replication_registry, "total": 5},
        "replication_ranking_s2_s6": {"exact": replication_ranking, "total": 5},
        "replication_selected_s6": {"exact": replication_selected, "total": 1},
        "replication_under_history": {"exact": replication_total, "total": 11},
        "registry_trajectory": {
            "exact": exact_count(latest_arm, fields=("candidate_registry",)),
            "total": 7,
        },
        "ranking_trajectory": {
            "exact": exact_count(latest_arm, fields=("utility_ranking",)),
            "total": 7,
        },
        "viability_extension": {
            "exact": exact_count(latest_arm, fields=("viability_partition",)),
            "total": 7,
        },
        "preselection_known_empty": {
            "exact": exact_count(
                latest_arm,
                checkpoints=CHECKPOINTS[:6],
                fields=("selected_candidate",),
            ),
            "total": 6,
        },
        "joint_latest": {"exact": exact_count(latest_arm), "total": 28},
        "history_dependent_s2_s6": {
            "exact": exact_count(latest_arm, checkpoints=CHECKPOINTS[2:]),
            "total": 20,
        },
        "prompt_sufficient_s0_s1": {
            "exact": exact_count(latest_arm, checkpoints=CHECKPOINTS[:2]),
            "total": 8,
        },
    }

    target = run_attempt["trials"]["target"]
    donor = run_attempt["trials"]["donor"]
    discriminating_keys = {
        (checkpoint, field)
        for checkpoint in CHECKPOINTS
        for field in FIELDS
        if target["truth"][checkpoint][field] != donor["truth"][checkpoint][field]
    }
    wrong_donor_exact = exact_count("wrong_trial_latest", "donor")
    wrong_specific = sum(
        _score_exact(index.get((checkpoint, field, "wrong_trial_latest")), "donor")
        and not _score_exact(
            index.get((checkpoint, field, "wrong_trial_latest")), "target"
        )
        for checkpoint, field in discriminating_keys
    )

    source_anomalies = {
        "duplicate_identifier_values": 0,
        "noncanonical_values": 0,
        "foreign_reviewed_ids": 0,
        "unknown_foreign_canonical_values": 0,
        "cross_trial_ids": 0,
        "condition_ids": 0,
    }
    future_exact_hits = 0
    premature_ids = 0
    stale_exact_hits = 0
    for row in rows:
        if not isinstance(row, dict) or row.get("arm") in CONTROL_ARMS:
            continue
        source_name = row.get("carrier_source_trial")
        source_trial = (
            target
            if source_name == "target"
            else donor
            if source_name == "donor"
            else None
        )
        other_trial = (
            donor
            if source_name == "target"
            else target
            if source_name == "donor"
            else None
        )
        evidence = _row_identifier_evidence(row)
        reviewed_ids = evidence["returned_reviewed_ids"]
        source_anomalies["duplicate_identifier_values"] += len(
            evidence["duplicate_reviewed_ids"]
            | evidence["duplicate_unknown_canonical_sha256"]
        )
        source_anomalies["noncanonical_values"] += len(
            evidence["noncanonical_value_sha256"]
        )
        source_anomalies["unknown_foreign_canonical_values"] += len(
            evidence["unknown_canonical_sha256"]
        )
        if isinstance(source_trial, dict):
            source_ids = set(source_trial["id_universe"])
            source_anomalies["foreign_reviewed_ids"] += len(
                reviewed_ids - source_ids
            )
            source_anomalies["condition_ids"] += int(
                source_trial["condition_id"] in reviewed_ids
            )
            checkpoint = row.get("checkpoint")
            if checkpoint in CHECKPOINTS:
                checkpoint_index = CHECKPOINTS.index(checkpoint)
                premature_ids += sum(
                    CHECKPOINTS.index(source_trial["introduction_checkpoint"][identifier])
                    > checkpoint_index
                    for identifier in reviewed_ids & source_ids
                )
        if isinstance(other_trial, dict):
            source_anomalies["cross_trial_ids"] += len(
                reviewed_ids & set(other_trial["id_universe"])
            )
        timeline = row.get("timeline")
        if isinstance(timeline, dict):
            future_exact_hits += len(timeline.get("future_exact_hits") or [])
            stale_exact_hits += len(timeline.get("stale_exact_hits") or [])

    expected_delta_keys = {
        (f"{CHECKPOINTS[index - 1]}->{CHECKPOINTS[index]}", field, arm)
        for arm in DELTA_ARMS
        for index in range(1, len(CHECKPOINTS))
        for field in FIELDS
    }
    mechanically_derived_deltas = derive_delta_rows(
        run_attempt=run_attempt,
        rows=rows,
        observations=observations,
    )
    mechanical_delta_index = {
        (row["transition"], row["field"], row["arm"]): row
        for row in mechanically_derived_deltas
    }
    delta_index: dict[tuple[str, str, str], dict[str, Any]] = {}
    duplicate_delta_keys: list[str] = []
    malformed_delta_rows = 0
    nonmechanical_delta_rows = 0
    for row in delta_rows:
        if not isinstance(row, dict) or not all(
            isinstance(row.get(key), str) for key in ("transition", "field", "arm")
        ):
            malformed_delta_rows += 1
            continue
        key = (row["transition"], row["field"], row["arm"])
        if key not in expected_delta_keys:
            malformed_delta_rows += 1
            continue
        if row != mechanical_delta_index.get(key):
            nonmechanical_delta_rows += 1
            continue
        if key in delta_index:
            duplicate_delta_keys.append("/".join(key))
            continue
        delta_index[key] = row
    delta_matrix_complete = bool(
        not duplicate_delta_keys
        and not malformed_delta_rows
        and not nonmechanical_delta_rows
        and len(delta_rows) == len(expected_delta_keys)
        and set(delta_index) == expected_delta_keys
    )

    deltas_by_arm: dict[str, dict[str, Any]] = {}
    for arm in DELTA_ARMS:
        arm_rows = [row for row in delta_index.values() if row.get("arm") == arm]
        changed = [row for row in arm_rows if row.get("changed_expected")]
        stable = [row for row in arm_rows if not row.get("changed_expected")]
        deltas_by_arm[arm] = {
            "exact": sum(bool(row.get("delta_exact")) for row in arm_rows),
            "total": 24,
            "rows_present": len(arm_rows),
            "changed_exact": sum(bool(row.get("delta_exact")) for row in changed),
            "changed_total": 12,
            "stable_exact": sum(bool(row.get("delta_exact")) for row in stable),
            "stable_total": 12,
            "directional_localization_exact": sum(
                bool(row.get("directional_localization_exact")) for row in changed
            ),
            "directional_localization_total": 12,
        }

    agreement_by_field = {}
    for field in FIELDS:
        agreements = sum(
            _agreement(
                field=field,
                left=observations.get(
                    (checkpoint, field, "target_latest_thought")
                ),
                right=observations.get(
                    (checkpoint, field, "target_cumulative_thought")
                ),
            )
            for checkpoint in CHECKPOINTS[1:]
        )
        latest_exact = exact_count(
            "target_latest_thought", checkpoints=CHECKPOINTS[1:], fields=(field,)
        )
        cumulative_exact = exact_count(
            "target_cumulative_thought", checkpoints=CHECKPOINTS[1:], fields=(field,)
        )
        agreement_by_field[field] = {
            "agreements": agreements,
            "latest_exact": latest_exact,
            "cumulative_exact": cumulative_exact,
            "total": 6,
        }

    anomalies_clear = all(value == 0 for value in source_anomalies.values())
    common_validity = bool(
        generation.get("eligible")
        and matrix_complete
        and target_full_exact == 28
        and donor_full_exact == 28
        and controls_clean == 56
        and anomalies_clear
    )
    primary_delta = deltas_by_arm[latest_arm]
    causal_specificity = bool(
        target_full_exact == 28
        and donor_full_exact == 28
        and anomalies_clear
        and delta_matrix_complete
        and wrong_donor_exact == 28
        and wrong_specific == 19
        and future_exact_hits == 0
        and premature_ids == 0
        and primary_delta["directional_localization_exact"] == 12
    )
    latest_positive = bool(
        common_validity
        and delta_matrix_complete
        and component_counts["joint_latest"]["exact"] == 28
        and primary_delta["exact"] == 24
        and primary_delta["changed_exact"] == 12
        and primary_delta["stable_exact"] == 12
        and causal_specificity
    )

    retry_counts_by_arm = {
        arm: sum(
            isinstance(row.get("call"), dict)
            and (row["call"].get("attempt_count") or 0) > 1
            for row in rows
            if isinstance(row, dict) and row.get("arm") == arm
        )
        for arm in ARMS
    }
    generation_retry_count = sum(
        isinstance(row.get("call"), dict)
        and (row["call"].get("attempt_count") or 0) > 1
        for row in checkpoint_summaries
        if isinstance(row, dict)
    )
    first_attempt_latest_exact = 0
    for checkpoint in CHECKPOINTS:
        for field in FIELDS:
            row = index.get((checkpoint, field, latest_arm))
            call = row.get("call") if isinstance(row, dict) else None
            first_attempt_latest_exact += bool(
                _score_exact(row)
                and isinstance(call, dict)
                and call.get("attempt_count") == 1
            )
    valid_rows = [row for row in rows if isinstance(row, dict)]
    return {
        "schema_version": "native_planning_transition_summary_v1",
        "experiment_id": "native_mutable_planning_state_s0_s6_v1",
        "status": "excluded_exploratory_native_to_task_pilot",
        "estimand": "R_native_matrix_not_scalar_or_direct_latent_state",
        "model": MODEL,
        "generation": generation,
        "checkpoint_count": len(checkpoint_summaries),
        "probe_rows_completed": len(rows),
        "probe_rows_planned": 196,
        "probe_matrix_complete": matrix_complete,
        "duplicate_probe_keys": duplicate_keys,
        "malformed_probe_rows": malformed_rows,
        "probe_outcomes": {
            outcome: sum(row.get("outcome") == outcome for row in valid_rows)
            for outcome in sorted({str(row.get("outcome")) for row in valid_rows})
        },
        "full_prefix_task_adherence": {
            "target_exact": target_full_exact,
            "donor_exact": donor_full_exact,
            "combined_exact": target_full_exact + donor_full_exact,
            "combined_total": 56,
        },
        "controls": {
            "by_arm": controls,
            "clean": controls_clean,
            "total": 56,
            "note": "rows_are_correlated_and_not_independent_controls",
        },
        "latest_component_counts": component_counts,
        "delta_matrix": {
            "complete": delta_matrix_complete,
            "rows_completed": len(delta_rows),
            "rows_planned": len(expected_delta_keys),
            "duplicate_keys": sorted(duplicate_delta_keys),
            "malformed_rows": malformed_delta_rows,
            "nonmechanical_rows": nonmechanical_delta_rows,
        },
        "delta_counts_by_arm": deltas_by_arm,
        "wrong_trial": {
            "donor_exact": wrong_donor_exact,
            "donor_total": 28,
            "discriminating_donor_exact_target_inexact": wrong_specific,
            "discriminating_total": len(discriminating_keys),
        },
        "source_anomalies": source_anomalies,
        "future_exact_hits": future_exact_hits,
        "premature_ids": premature_ids,
        "stale_exact_hits_diagnostic": stale_exact_hits,
        "latest_vs_cumulative_excluding_s0": agreement_by_field,
        "common_validity_gate": common_validity,
        "causal_specificity_gate": causal_specificity,
        "latest_positive_exploratory_observation": latest_positive,
        "retry_counts_by_arm": retry_counts_by_arm,
        "generation_retry_count": generation_retry_count,
        "first_attempt_sensitivity": {
            "latest_exact": first_attempt_latest_exact,
            "latest_total": 28,
            "generation_complete_without_retry": bool(
                generation.get("eligible") and generation_retry_count == 0
            ),
        },
        "denominator_note": (
            "state_cells_and_deltas_are_correlated_completeness_checks_within_one_"
            "target_donor_chain_not_independent_replications"
        ),
    }


def render_review(summary: dict[str, Any]) -> str:
    latest = summary["latest_component_counts"]
    primary_delta = summary["delta_counts_by_arm"]["target_latest_thought"]
    wrong = summary["wrong_trial"]
    full = summary["full_prefix_task_adherence"]
    controls = summary["controls"]
    lines = [
        "# Native S0-S6 planning-transition pilot review",
        "",
        f"- Model: `{MODEL}`",
        "- Status: excluded exploratory native-to-task pilot",
        "- Estimand: the `R_native` outcome/control/delta matrix, not a scalar or direct latent-state readout",
        f"- Generation eligible: `{summary['generation']['eligible']}`",
        f"- Probe matrix complete: `{summary['probe_matrix_complete']}`",
        "- Raw signed artifacts: retained only in the ignored private execution directory",
        "",
        "## Frozen gates",
        "",
        f"- Full prefixes: `{full['combined_exact']}/{full['combined_total']}` exact",
        f"- Visible/probe-only controls: `{controls['clean']}/{controls['total']}` clean unknown-empty",
        f"- Latest replication-under-history: `{latest['replication_under_history']['exact']}/11`",
        f"- Latest joint state: `{latest['joint_latest']['exact']}/28`",
        f"- Latest adjacent deltas: `{primary_delta['exact']}/24` (`{primary_delta['changed_exact']}/12` changed; `{primary_delta['stable_exact']}/12` stable)",
        f"- Wrong-trial donor exact: `{wrong['donor_exact']}/28`",
        f"- Wrong-trial distinguishing cells: `{wrong['discriminating_donor_exact_target_inexact']}/{wrong['discriminating_total']}`",
        f"- Future-exact hits: `{summary['future_exact_hits']}`",
        f"- Premature IDs: `{summary['premature_ids']}`",
        f"- Positive exploratory observation: `{summary['latest_positive_exploratory_observation']}`",
        "",
        "## Interpretation boundary",
        "",
        "This experiment tests model-mediated recovery through whole signed thought-step carriers under one frozen configuration. It does not decode signature bytes, expose chain-of-thought, establish a complete latent state, or test the later retention scaffold.",
        "",
    ]
    return "\n".join(lines)


def _copy_freeze(snapshot: dict[str, bytes], output_dir: Path) -> None:
    target = output_dir / "frozen_protocol"
    target.mkdir(parents=True, exist_ok=False)
    for name in SAFE_FREEZE_FILES:
        write_bytes(target / name, snapshot[name])


def _set_budget_fields(
    ledger: dict[str, Any], *, logical_requests: int, physical_attempts: int
) -> None:
    ledger["logical_requests_total"] = logical_requests
    ledger["physical_attempts_total"] = physical_attempts
    ledger["within_logical_ceiling"] = logical_requests <= 224
    ledger["within_physical_ceiling"] = physical_attempts <= 672


def _logical_requests_attempted(store: CallStore | None) -> int:
    if not isinstance(store, CallStore):
        return 0
    labels = {
        re.sub(r"_attempt[1-9][0-9]*$", "", str(record.get("label") or ""))
        for record in store.records
        if isinstance(record, dict) and record.get("label")
    }
    return len(labels)


def _execution_store_totals(stores: list[CallStore]) -> tuple[int, int]:
    """Recompute counters idempotently from physical attempt-start records."""
    physical = sum(len(store.records) for store in stores)
    logical = sum(_logical_requests_attempted(store) for store in stores)
    return physical, logical


def _terminalize_unhandled_execution(
    *,
    output_dir: Path,
    execution_ledger: dict[str, Any],
    freeze_id: str,
    run_id: str | None,
    phase: str,
    exc: BaseException,
    logical_requests: int,
    physical_attempts: int,
) -> bool:
    """Best-effort terminal record for every failure after one-shot claim."""
    previous_status = execution_ledger.get("final_status")
    execution_ledger["final_run"] = run_id or execution_ledger.get("final_run")
    execution_ledger["final_status"] = f"execution_interrupted_{phase}"
    _set_budget_fields(
        execution_ledger,
        logical_requests=logical_requests,
        physical_attempts=physical_attempts,
    )
    interruption = {
        "schema_version": "native_planning_execution_interruption_v1",
        "run_id": run_id,
        "freeze_id": freeze_id,
        "phase": phase,
        "terminal_for_this_consumed_freeze": True,
        "replacement_permitted": False,
        "previous_final_status": previous_status,
        "exception_type_sha256": sha256_text(
            f"{type(exc).__module__}.{type(exc).__qualname__}"
        ),
        "logical_requests_attempted": logical_requests,
        "physical_attempts_started": physical_attempts,
    }
    try:
        write_json(output_dir / "execution_interrupted.json", interruption)
        write_json(output_dir / "execution_ledger.json", execution_ledger)
    except OSError:
        return False
    return True


def _execute_reviewed_freeze_inner(
    *,
    repo_root: Path,
    freeze_dir: Path,
    expected_freeze_id: str,
    api_key: str,
    transport: Callable[..., InteractionHttpResult] = post_interaction,
    sleeper: Callable[[float], None] | None = None,
    guard_state: dict[str, Any],
) -> dict[str, Any]:
    verification = verify_freeze(
        repo_root=repo_root,
        freeze_dir=freeze_dir,
        expected_freeze_id=expected_freeze_id,
        verify_source=True,
    )
    if not verification["valid"]:
        raise ValueError("reviewed freeze verification failed: " + "; ".join(verification["errors"]))
    snapshot, manifest = _read_verified_freeze_snapshot(
        freeze_dir=freeze_dir,
        expected_freeze_id=expected_freeze_id,
    )
    output_dir = execution_output_dir(
        repo_root=repo_root,
        freeze_id=expected_freeze_id,
    )
    guard_state["output_dir"] = output_dir
    _assert_path_has_no_link_ancestor(repo_root=repo_root, path=output_dir)
    _assert_execution_paths_are_ignored(repo_root=repo_root, output_dir=output_dir)
    if not api_key:
        raise ValueError("an API key is required only for explicit execution")
    execution_ledger: dict[str, Any] = {
        "schema_version": "native_planning_transition_execution_ledger_v1",
        "freeze_id": expected_freeze_id,
        "freeze_source_path_sha256": sha256_text(str(freeze_dir.resolve())),
        "executed_manifest_file_bytes_sha256": sha256_bytes(
            snapshot["manifest.json"]
        ),
        "attempts": [],
        "tomography_started_run": None,
        "final_run": None,
    }
    guard_state["execution_ledger"] = execution_ledger
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    _assert_path_has_no_link_ancestor(repo_root=repo_root, path=output_dir.parent)
    output_dir.mkdir(exist_ok=False)
    guard_state["claim_created"] = True
    guard_state["phase"] = "postclaim_setup"
    total_physical = 0
    total_logical = 0
    try:
        _assert_path_has_no_link_ancestor(repo_root=repo_root, path=output_dir)
        if output_dir.resolve() != output_dir.absolute():
            raise ValueError(
                "canonical execution path changed after its exclusive claim"
            )
        _assert_execution_paths_are_ignored(
            repo_root=repo_root,
            output_dir=output_dir,
        )
        write_json(
            output_dir / "consumption_claim.json",
            {
                "schema_version": "native_planning_transition_consumption_claim_v1",
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
        write_json(output_dir / "execution_ledger.json", execution_ledger)
    except BaseException as exc:
        guard_state["terminalized"] = _terminalize_unhandled_execution(
            output_dir=output_dir,
            execution_ledger=execution_ledger,
            freeze_id=expected_freeze_id,
            run_id=None,
            phase="postclaim_setup",
            exc=exc,
            logical_requests=0,
            physical_attempts=0,
        )
        raise

    for attempt_index, run_attempt in enumerate(manifest["planned_run_attempts"], 1):
        run_id = run_attempt["run_id"]
        guard_state["current_run_id"] = run_id
        guard_state["phase"] = "attempt_setup"
        attempt_dir = output_dir / run_id
        store: CallStore | None = None
        runtimes: dict[str, dict[str, CheckpointRuntime]] = {}
        checkpoint_summaries: list[dict[str, Any]] = []
        generation_failed_early = False
        attempt_record: dict[str, Any] | None = None
        try:
            attempt_dir.mkdir(exist_ok=False)
            store = CallStore(
                run_dir=attempt_dir,
                api_key=api_key,
                timeout=HTTP_TIMEOUT_SECONDS,
                delay_seconds=INTER_REQUEST_DELAY_SECONDS,
                transport=transport,
                max_attempts=MAX_ATTEMPTS_PER_LOGICAL_REQUEST,
                retry_backoff_seconds=RETRY_BACKOFF_SECONDS,
                sleeper=sleeper,
            )
            guard_state["stores"].append(store)
            guard_state["phase"] = "generation"
            for trial_name in run_attempt["generation_trial_order"]:
                trial_runtime, summaries = generate_trial(
                    run_id=run_id,
                    trial=run_attempt["trials"][trial_name],
                    generation_tasks=run_attempt["generation_tasks"],
                    store=store,
                )
                runtimes[trial_name] = trial_runtime
                checkpoint_summaries.extend(summaries)
                write_json(
                    attempt_dir / "checkpoint_summaries.partial.json",
                    checkpoint_summaries,
                )
                if len(summaries) != 7 or not all(
                    row.get("eligible") for row in summaries
                ):
                    generation_failed_early = True
                    break
        except BaseException as exc:
            attempt_physical = len(store.records) if isinstance(store, CallStore) else 0
            attempt_logical = _logical_requests_attempted(store)
            total_physical, total_logical = _execution_store_totals(
                guard_state["stores"]
            )
            attempt_record = {
                "run_id": run_id,
                "attempt_index": attempt_index,
                "generation": {
                    "eligible": False,
                    "interrupted_before_eligibility_decision": True,
                    "checkpoint_summaries_persisted": len(checkpoint_summaries),
                },
                "generation_failed_early": True,
                "tomography_started": False,
                "generation_logical_requests": attempt_logical,
                "generation_physical_attempts": attempt_physical,
                "terminal_status": "execution_interrupted_before_tomography",
            }
            execution_ledger["attempts"].append(attempt_record)
            execution_ledger["final_run"] = run_id
            execution_ledger["final_status"] = "execution_interrupted_before_tomography"
            _set_budget_fields(
                execution_ledger,
                logical_requests=total_logical,
                physical_attempts=total_physical,
            )
            interruption = {
                "schema_version": "native_planning_execution_interruption_v1",
                "run_id": run_id,
                "freeze_id": expected_freeze_id,
                "phase": "generation_before_tomography",
                "terminal_for_this_consumed_freeze": True,
                "replacement_permitted": False,
                "exception_type_sha256": sha256_text(
                    f"{type(exc).__module__}.{type(exc).__qualname__}"
                ),
                "logical_requests_attempted": attempt_logical,
                "physical_attempts_started": attempt_physical,
            }
            terminal_persisted = False
            try:
                write_json(output_dir / "execution_interrupted.json", interruption)
                write_json(output_dir / "execution_ledger.json", execution_ledger)
                terminal_persisted = True
            except OSError:
                pass
            guard_state["terminalized"] = terminal_persisted
            raise
        guard_state["phase"] = "after_generation_before_tomography_calls"
        try:
            if not isinstance(store, CallStore):
                raise RuntimeError("generation completed without a call store")
            generation_physical = len(store.records)
            generation_logical = _logical_requests_attempted(store)
            total_physical, total_logical = _execution_store_totals(
                guard_state["stores"]
            )
            attempt_record = {
                "run_id": run_id,
                "attempt_index": attempt_index,
                "generation": {
                    "eligible": False,
                    "postprocessing_complete": False,
                    "checkpoint_count": len(checkpoint_summaries),
                },
                "generation_failed_early": generation_failed_early,
                "tomography_started": False,
                "generation_logical_requests": generation_logical,
                "generation_physical_attempts": generation_physical,
            }
            execution_ledger["attempts"].append(attempt_record)
            execution_ledger["final_run"] = run_id
            generation = generation_status(
                checkpoint_summaries=checkpoint_summaries,
                runtimes=runtimes,
            )
            attempt_record["generation"] = generation
            write_json(
                attempt_dir / "checkpoint_summaries.json",
                checkpoint_summaries,
            )
            write_json(output_dir / "execution_ledger.json", execution_ledger)

            if not generation["eligible"]:
                write_json(
                    attempt_dir / "summary.json",
                    {
                        "schema_version": "native_planning_generation_failure_v1",
                        "run_id": run_id,
                        "generation": generation,
                        "probe_rows_completed": 0,
                        "replacement_permitted": attempt_index == 1,
                    },
                )
                if attempt_index == 1:
                    continue
                execution_ledger["final_status"] = (
                    "both_planned_runs_generation_ineligible"
                )
                break

            if set(runtimes) != {"target", "donor"}:
                raise RuntimeError(
                    "eligible generation lacks target or donor runtime"
                )
            execution_ledger["tomography_started_run"] = run_id
            attempt_record["tomography_started"] = True
            write_json(
                attempt_dir / "tomography_started.json",
                {
                    "run_id": run_id,
                    "freeze_id": expected_freeze_id,
                    "final_under_stopping_policy": True,
                },
            )
            write_json(output_dir / "execution_ledger.json", execution_ledger)
        except BaseException as exc:
            generation_physical = (
                len(store.records) if isinstance(store, CallStore) else 0
            )
            generation_logical = _logical_requests_attempted(store)
            total_physical, total_logical = _execution_store_totals(
                guard_state["stores"]
            )
            if not isinstance(attempt_record, dict):
                attempt_record = {
                    "run_id": run_id,
                    "attempt_index": attempt_index,
                    "generation": {
                        "eligible": False,
                        "postprocessing_complete": False,
                        "checkpoint_count": len(checkpoint_summaries),
                    },
                    "generation_failed_early": generation_failed_early,
                    "tomography_started": False,
                    "generation_logical_requests": generation_logical,
                    "generation_physical_attempts": generation_physical,
                }
                execution_ledger["attempts"].append(attempt_record)
            attempt_record["terminal_status"] = (
                "execution_interrupted_after_generation_before_tomography_calls"
            )
            guard_state["terminalized"] = _terminalize_unhandled_execution(
                output_dir=output_dir,
                execution_ledger=execution_ledger,
                freeze_id=expected_freeze_id,
                run_id=run_id,
                phase="after_generation_before_tomography_calls",
                exc=exc,
                logical_requests=total_logical,
                physical_attempts=total_physical,
            )
            raise
        guard_state["phase"] = "tomography"
        physical_before_probes = len(store.records)
        try:
            rows, observations = run_probes(
                run_attempt=run_attempt,
                target_runtimes=runtimes["target"],
                donor_runtimes=runtimes["donor"],
                store=store,
            )
            probe_physical = len(store.records) - physical_before_probes
            probe_logical = len(rows)
            total_physical, total_logical = _execution_store_totals(
                guard_state["stores"]
            )
            attempt_record["probe_logical_requests"] = probe_logical
            attempt_record["probe_physical_attempts"] = probe_physical
            write_json(attempt_dir / "probe_results.json", rows)
            delta_rows = derive_delta_rows(
                run_attempt=run_attempt,
                rows=rows,
                observations=observations,
            )
            write_json(attempt_dir / "delta_results.json", delta_rows)
            summary = summarize_results(
                run_attempt=run_attempt,
                generation=generation,
                checkpoint_summaries=checkpoint_summaries,
                rows=rows,
                observations=observations,
                delta_rows=delta_rows,
            )
            summary["logical_requests"] = len(checkpoint_summaries) + len(rows)
            summary["physical_attempts"] = len(store.records)
            summary_path = attempt_dir / "summary.json"
            write_json(summary_path, summary)
            write_text(attempt_dir / "review.md", render_review(summary))
            attempt_record["summary_canonical_json_sha256"] = sha256_json(
                summary
            )
            attempt_record["summary_file_bytes_sha256"] = sha256_bytes(
                summary_path.read_bytes()
            )
            execution_ledger["final_status"] = "tomography_complete"
        except BaseException as exc:
            probe_physical = len(store.records) - physical_before_probes
            attempted_logical = _logical_requests_attempted(store)
            probe_logical = max(
                0,
                attempted_logical
                - int(attempt_record["generation_logical_requests"]),
            )
            total_physical, total_logical = _execution_store_totals(
                guard_state["stores"]
            )
            attempt_record["probe_logical_requests"] = probe_logical
            attempt_record["probe_physical_attempts"] = probe_physical
            attempt_record["terminal_status"] = "tomography_interrupted_final"
            execution_ledger["final_status"] = "tomography_interrupted_final"
            _set_budget_fields(
                execution_ledger,
                logical_requests=total_logical,
                physical_attempts=total_physical,
            )
            interruption = {
                "schema_version": "native_planning_tomography_interruption_v1",
                "run_id": run_id,
                "freeze_id": expected_freeze_id,
                "terminal_under_stopping_policy": True,
                "replacement_permitted": False,
                "exception_type_sha256": sha256_text(
                    f"{type(exc).__module__}.{type(exc).__qualname__}"
                ),
                "probe_logical_requests_attempted": probe_logical,
                "probe_physical_attempts_started": probe_physical,
            }
            terminal_persisted = False
            try:
                write_json(attempt_dir / "tomography_interrupted.json", interruption)
                write_json(output_dir / "execution_ledger.json", execution_ledger)
                terminal_persisted = True
            except OSError:
                pass
            guard_state["terminalized"] = terminal_persisted
            raise
        guard_state["phase"] = "during_terminal_persistence"
        break

    guard_state["phase"] = "during_terminal_persistence"
    budget_exceeded = False
    try:
        total_physical, total_logical = _execution_store_totals(
            guard_state["stores"]
        )
        _set_budget_fields(
            execution_ledger,
            logical_requests=total_logical,
            physical_attempts=total_physical,
        )
        budget_exceeded = bool(
            not execution_ledger["within_logical_ceiling"]
            or not execution_ledger["within_physical_ceiling"]
        )
        if budget_exceeded:
            execution_ledger["final_status"] = (
                "stopping_policy_budget_exceeded"
            )
        write_json(output_dir / "execution_ledger.json", execution_ledger)
        guard_state["terminalized"] = True
    except BaseException as exc:
        guard_state["terminalized"] = _terminalize_unhandled_execution(
            output_dir=output_dir,
            execution_ledger=execution_ledger,
            freeze_id=expected_freeze_id,
            run_id=execution_ledger.get("final_run"),
            phase="during_terminal_persistence",
            exc=exc,
            logical_requests=total_logical,
            physical_attempts=total_physical,
        )
        raise
    if budget_exceeded:
        raise RuntimeError("execution exceeded the frozen stopping-policy budget")
    return execution_ledger


def execute_reviewed_freeze(
    *,
    repo_root: Path,
    freeze_dir: Path,
    expected_freeze_id: str,
    api_key: str,
    transport: Callable[..., InteractionHttpResult] = post_interaction,
    sleeper: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Execute with a true outer guard for every post-claim interruption."""
    guard_state: dict[str, Any] = {
        "claim_created": False,
        "terminalized": False,
        "output_dir": None,
        "execution_ledger": None,
        "current_run_id": None,
        "phase": "preclaim",
        "stores": [],
    }
    try:
        return _execute_reviewed_freeze_inner(
            repo_root=repo_root,
            freeze_dir=freeze_dir,
            expected_freeze_id=expected_freeze_id,
            api_key=api_key,
            transport=transport,
            sleeper=sleeper,
            guard_state=guard_state,
        )
    except BaseException as exc:
        if guard_state.get("claim_created") and not guard_state.get(
            "terminalized"
        ):
            output_dir = guard_state.get("output_dir")
            execution_ledger = guard_state.get("execution_ledger")
            stores = guard_state.get("stores")
            safe_stores = (
                [store for store in stores if isinstance(store, CallStore)]
                if isinstance(stores, list)
                else []
            )
            physical, logical = _execution_store_totals(safe_stores)
            phase = guard_state.get("phase")
            run_id = guard_state.get("current_run_id")
            if isinstance(output_dir, Path) and isinstance(
                execution_ledger, dict
            ):
                guard_state["terminalized"] = (
                    _terminalize_unhandled_execution(
                        output_dir=output_dir,
                        execution_ledger=execution_ledger,
                        freeze_id=expected_freeze_id,
                        run_id=run_id if isinstance(run_id, str) else None,
                        phase=phase if isinstance(phase, str) else "unhandled_postclaim",
                        exc=exc,
                        logical_requests=logical,
                        physical_attempts=physical,
                    )
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
    return 0 if ledger.get("final_status") == "tomography_complete" else 3


if __name__ == "__main__":
    raise SystemExit(main())
