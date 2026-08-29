#!/usr/bin/env python3
"""Run the staged modernization reasoning-engineering experiment.

This is the only network-capable module in this package.  It persists exact
provider wire artifacts under the ignored ``results/`` tree, keeps isolated
observations off the live history, and never uses a structured response format
for the planning boundary.
"""

from __future__ import annotations

import argparse
import copy
import functools
import json
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from thoughtlab.gemini_generate_content import (
    GenerateContentHttpResult,
    canonical_json_bytes as generate_content_wire_bytes,
    decode_generate_content_bytes,
    generate_content_url,
    post_generate_content,
    response_contents,
    thought_signature_metadata,
)
from thoughtlab.opaque_ids import generate_opaque_id, is_opaque_id
from thoughtlab.raw_call_store import (
    RawCallStore as CallStore,
    bounded_storage_label as _bounded_storage_label,
    write_json,
    write_text,
)
from thoughtlab.reasoningEngineering import modernization_protocol as protocol


SCHEMA_VERSION = "modernization_reasoning_engineering_execution_v1"
INTER_REQUEST_DELAY_SECONDS = 1.0

ACTION_FREEZE_READY = "FREEZE_READY"
ACTION_CONTINUE = "CONTINUE"
ACTION_TERMINATE_TECHNICAL = "TERMINATE_TECHNICAL"

OUTPUT_BUDGET_FINISH_REASONS = frozenset(
    protocol.OUTPUT_BUDGET_FINISH_REASONS
)
COMPLETED_FINISH_REASONS = frozenset(protocol.COMPLETED_FINISH_REASONS)

INTERVENTION_RECORD_FILES = (
    "diagnosis.md",
    "prediction.md",
    "intervention.txt",
)
INTERVENTION_TEMPLATE_TEXT = {
    "diagnosis.md": (
        "REPLACE_BEFORE_SEALING\n\nDescribe the material reasoning weakness "
        "observed in the isolated READY-checkpoint observation.\n"
    ),
    "prediction.md": (
        "REPLACE_BEFORE_SEALING\n\nRecord the targeted reasoning relationship, "
        "predicted downstream changes, and commitments expected to remain stable "
        "before phase two.\n"
    ),
    "intervention.txt": (
        "REPLACE_BEFORE_SEALING\n\nWrite one diagnostic, non-answer-supplying "
        "reasoning intervention.\n"
    ),
}
INTERVENTION_LOCK_FILE = "intervention.lock.json"
PHASE_ONE_CLAIM_FILE = "phase_one_consumption_claim.json"
PHASE_ONE_TERMINAL_FILE = "phase_one_consumption_terminal.json"
PHASE_TWO_CLAIM_FILE = "phase_two_consumption_claim.json"
PHASE_TWO_TERMINAL_FILE = "phase_two_consumption_terminal.json"
PHASE_TWO_SEAL_FILE = "phase_two_seal.json"
PHASE_TWO_DISPOSITION_FILE = "phase_two_disposition.json"
NO_INTERVENTION_TARGET_FILE = "no_valid_intervention_target.json"
NO_INTERVENTION_NOTE_FILE = "no_target_note.md"
PHASE_ONE_ARTIFACT_PATHS = [
    PHASE_ONE_CLAIM_FILE,
    "baseline_planning.private.json",
    "baseline_planning_attempts.json",
    "baseline_planning_summary.json",
    "baseline_observations.private.json",
    "baseline_observations.json",
    "baseline_observation_seal.json",
    "PHASE_ONE_REVIEW.md",
]

PHASE_ONE_SEAL_KEYS = {
    "schema_version",
    "freeze_id",
    "created_at",
    "planning_summary_sha256",
    "observation_seal_sha256",
    "baseline_planning_private_bytes_sha256",
    "baseline_observations_private_bytes_sha256",
    "ready_checkpoint_id",
    "phase_two_requires_sealed_intervention",
    "phase_one_claim_id",
    "phase_one_claim_bytes_sha256",
    "phase_one_terminal",
    "ready_observation_eligible",
    "intervention_authorized",
    "phase_one_call_index_prefix_sha256",
    "phase_one_call_index_bytes_sha256",
    "phase_one_physical_call_count",
    "phase_one_raw_inventory",
    "phase_one_artifact_inventory",
    "phase_one_review_bytes_sha256",
    "baseline_task_sha256",
}
INTERVENTION_LOCK_KEYS = {
    "schema_version",
    "created_at",
    "phase_one_seal_sha256",
    "disposition_claim_bytes_sha256",
    "records",
    "sealed_before_phase_two",
}
PHASE_TWO_DISPOSITION_KEYS = {
    "schema_version",
    "freeze_id",
    "disposition_id",
    "phase_one_seal_bytes_sha256",
    "decision_payload_sha256",
    "selected_at",
    "disposition",
}
PHASE_TWO_CLAIM_KEYS = {
    "schema_version",
    "freeze_id",
    "claim_id",
    "ready_checkpoint_id",
    "intervention_lock_sha256",
    "claimed_at",
    "status",
}
PHASE_TWO_SEAL_KEYS = {
    "schema_version",
    "freeze_id",
    "created_at",
    "phase_one_seal_bytes_sha256",
    "intervention_lock_bytes_sha256",
    "phase_two_claim_id",
    "phase_two_claim_bytes_sha256",
    "baseline_ready_checkpoint_id",
    "adjusted_ready_checkpoint_id",
    "adjusted_ready_observation_eligible",
    "evidence_chain_complete",
    "phase_two_terminal",
    "artifact_inventory",
    "final_call_index_sha256",
    "final_call_index_bytes_sha256",
    "final_physical_call_count",
    "raw_inventory",
}
PHASE_TWO_SUMMARY_KEYS = {
    "schema_version",
    "freeze_id",
    "intervention_lock_sha256",
    "diagnosis_sha256",
    "prediction_sha256",
    "intervention_sha256",
    "adjusted_terminal",
    "adjusted_ready_checkpoint_id",
    "adjusted_observations",
    "adjusted_ready_observation_eligible",
    "execution_rows",
    "evidence_chain_complete",
    "phase_two_terminal",
}


@dataclass
class PlanningTurnEvaluation:
    provider_status: str
    explicit_finish_reasons: list[str]
    readiness_observation: str | None
    controller_action: str
    carrier_replayable: bool
    reasons: list[str]
    steps: list[dict[str, Any]]
    visible_text: str
    normalized_visible_text: str
    safe_metadata: dict[str, Any]


@dataclass
class CheckpointRuntime:
    checkpoint_id: str
    phase: str
    turn_number: int
    readiness_observation: str
    provider_status: str
    full_history: list[dict[str, Any]]
    response_steps: list[dict[str, Any]]
    summary: dict[str, Any]


@dataclass
class PlanningPhaseRuntime:
    phase: str
    checkpoints: list[CheckpointRuntime]
    ready_checkpoint: CheckpointRuntime | None
    terminal: str
    last_turn_classification: str | None
    public_summary: dict[str, Any]


@dataclass
class PhysicalCallCursor:
    records: list[dict[str, Any]]
    next_call_number: int
    logical_paths_used: set[str]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_timestamp(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{label} is not a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError as exc:
        raise ValueError(f"{label} is not a UTC timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise ValueError(f"{label} is not a UTC timestamp")
    return parsed


def _exact_visible_text(
    model_contents: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    pieces: list[str] = []
    issues: list[str] = []
    if len(model_contents) != 1:
        issues.append("response did not contain exactly one model Content")
    for content_index, content in enumerate(model_contents):
        try:
            protocol._validate_model_content(content, content_index)
        except ValueError as exc:
            issues.append(str(exc))
            continue
        visible_parts = [
            part
            for part in content["parts"]
            if part.get("thought") is not True
            and isinstance(part.get("text"), str)
        ]
        if len(visible_parts) != 1:
            issues.append(
                f"model content[{content_index}] did not contain exactly one "
                "visible text Part"
            )
        for part in visible_parts:
            text = part.get("text")
            if isinstance(text, str):
                pieces.append(text)
    return "".join(pieces), issues


def _ordinary_visible_text(
    model_contents: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    """Collect ordered prose Parts without imposing the READY token shape."""

    pieces: list[str] = []
    issues: list[str] = []
    if len(model_contents) != 1:
        issues.append("response did not contain exactly one model Content")
    for content_index, content in enumerate(model_contents):
        try:
            protocol._validate_model_content(content, content_index)
        except ValueError as exc:
            issues.append(str(exc))
            continue
        visible_parts = [
            part
            for part in content["parts"]
            if part.get("thought") is not True
            and isinstance(part.get("text"), str)
        ]
        if not visible_parts:
            issues.append(
                f"model content[{content_index}] contained no visible text Part"
            )
        pieces.extend(str(part["text"]) for part in visible_parts)
    return "".join(pieces), issues


def _explicit_finish_reasons(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        return []
    candidate = candidates[0]
    if not isinstance(candidate, dict):
        return []
    reason = candidate.get("finishReason")
    return [reason] if isinstance(reason, str) and reason else []


def _normalized_finish_reason(value: str) -> str:
    return value.strip().upper().replace("-", "_").replace(" ", "_")


def _safe_usage(payload: dict[str, Any] | None) -> dict[str, int | None]:
    usage = payload.get("usageMetadata") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        usage = {}
    mapping = {
        "total_tokens": "totalTokenCount",
        "total_input_tokens": "promptTokenCount",
        "total_cached_tokens": "cachedContentTokenCount",
        "total_output_tokens": "candidatesTokenCount",
        "total_thought_tokens": "thoughtsTokenCount",
        "total_tool_use_tokens": "toolUsePromptTokenCount",
    }
    return {
        target: value if isinstance((value := usage.get(source)), int) else None
        for target, source in mapping.items()
    }


def _carrier_errors(steps: list[dict[str, Any]]) -> list[str]:
    if not steps:
        return ["response has no replayable steps"]
    try:
        # Isolation is the strict carrier validator. It deep-copies the exact
        # model Content and blanks text only in the detached sibling request.
        protocol.isolate_response_steps(steps)
    except (RuntimeError, TypeError, ValueError) as exc:
        return [f"response carrier was not safely isolatable: {exc}"]
    return []


def evaluate_planning_turn(
    result: GenerateContentHttpResult,
) -> PlanningTurnEvaluation:
    """Classify transport, replayability, and readiness without collapsing them."""

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
        payload = {}

    if payload.get("modelVersion") != protocol.MODEL:
        reasons.append("returned model did not match the frozen model")
    if "error" in payload or "errors" in payload:
        reasons.append("response contained a top-level error")

    steps: list[dict[str, Any]] = []
    if isinstance(result.payload, dict):
        try:
            steps = response_contents(result.payload)
        except ValueError as exc:
            reasons.append(f"response Content shape was invalid: {exc}")

    visible_text, output_issues = _exact_visible_text(steps)
    visible_shape_valid = not output_issues
    normalized = protocol.normalize_readiness_text(visible_text)
    carrier_issues = _carrier_errors(steps)
    reasons.extend(output_issues)
    reasons.extend(carrier_issues)

    transport_usable = (
        result.http_status is not None
        and 200 <= result.http_status < 300
        and not result.transport_error
        and not result.response_parse_error
        and isinstance(result.payload, dict)
        and result.payload.get("modelVersion") == protocol.MODEL
        and "error" not in result.payload
        and "errors" not in result.payload
    )
    carrier_replayable = transport_usable and not carrier_issues

    # Readiness is an observation about the provider/model turn.  Carrier
    # replayability is a separate controller property and must not erase that
    # observation when a signed checkpoint is unavailable.
    finish_reasons = _explicit_finish_reasons(result.payload)
    normalized_finish_reasons = {
        _normalized_finish_reason(reason) for reason in finish_reasons
    }
    if normalized_finish_reasons == COMPLETED_FINISH_REASONS:
        provider_status = "completed"
    elif (
        normalized_finish_reasons
        and normalized_finish_reasons.issubset(OUTPUT_BUDGET_FINISH_REASONS)
    ):
        provider_status = "incomplete"
    else:
        provider_status = ""
        reasons.append("missing or unsupported generateContent finishReason")

    readiness: str | None
    if provider_status == "incomplete":
        # MAX_TOKENS outranks any partial visible READY/NOT_READY text.
        readiness = protocol.UNOBSERVED_TRUNCATED
    elif provider_status == "completed":
        if visible_shape_valid and normalized == protocol.READY:
            readiness = protocol.READY
        elif visible_shape_valid and normalized == protocol.NOT_READY:
            readiness = protocol.SELF_DECLARED_NOT_READY
        else:
            readiness = protocol.INVALID_STATUS
    else:
        readiness = None

    if not carrier_replayable:
        action = ACTION_TERMINATE_TECHNICAL
    elif readiness == protocol.READY:
        action = ACTION_FREEZE_READY
    elif readiness in {
        protocol.SELF_DECLARED_NOT_READY,
        protocol.UNOBSERVED_TRUNCATED,
        protocol.INVALID_STATUS,
    }:
        action = ACTION_CONTINUE
    else:
        action = ACTION_TERMINATE_TECHNICAL
        reasons.append(
            f"generateContent finish state was {provider_status!r}"
        )

    reasons = list(dict.fromkeys(reasons))
    return PlanningTurnEvaluation(
        provider_status=provider_status,
        explicit_finish_reasons=finish_reasons,
        readiness_observation=readiness,
        controller_action=action,
        carrier_replayable=carrier_replayable,
        reasons=reasons,
        steps=copy.deepcopy(steps),
        visible_text=visible_text,
        normalized_visible_text=normalized,
        safe_metadata={
            "http_status": result.http_status,
            "provider_status": provider_status,
            "explicit_finish_reasons": finish_reasons,
            "transport_error_present": bool(result.transport_error),
            "response_parse_error_present": bool(result.response_parse_error),
            "response_content_count": len(steps),
            "response_part_count": sum(
                len(content.get("parts", []))
                for content in steps
                if isinstance(content.get("parts"), list)
            ),
            "signature_metadata": thought_signature_metadata(steps),
            "visible_text_sha256": protocol.sha256_text(visible_text),
            "visible_text_chars": len(visible_text),
            "usage": _safe_usage(result.payload),
        },
    )


def _safe_call_summary(call: dict[str, Any]) -> dict[str, Any]:
    return {
        "logical_request_id": call.get("logical_request_id"),
        "attempt_count": call.get("attempt_count"),
        "selected_physical_call_number": call.get("selected_physical_call_number"),
        "selected_response_wire_sha256": call.get("selected_response_wire_sha256"),
        "selection_reason": call.get("selection_reason"),
        "request_wire_sha256": call.get("request_wire_sha256"),
    }


def _invoke(
    *, store: CallStore, label: str, body: dict[str, Any]
) -> tuple[GenerateContentHttpResult, dict[str, Any]]:
    protocol.assert_no_function_tool_or_schema_structure(body)
    result, call = store.invoke_logical(label=label, body=body)
    return result, _safe_call_summary(call)


def _checkpoint_private_record(checkpoint: CheckpointRuntime) -> dict[str, Any]:
    return {
        "checkpoint_id": checkpoint.checkpoint_id,
        "phase": checkpoint.phase,
        "turn_number": checkpoint.turn_number,
        "readiness_observation": checkpoint.readiness_observation,
        "provider_status": checkpoint.provider_status,
        "full_history": copy.deepcopy(checkpoint.full_history),
        "response_steps": copy.deepcopy(checkpoint.response_steps),
        "summary": copy.deepcopy(checkpoint.summary),
    }


def _phase_private_record(runtime: PlanningPhaseRuntime) -> dict[str, Any]:
    return {
        "schema_version": "modernization_planning_phase_private_v1",
        "phase": runtime.phase,
        "terminal": runtime.terminal,
        "last_turn_classification": runtime.last_turn_classification,
        "ready_checkpoint_id": (
            runtime.ready_checkpoint.checkpoint_id
            if runtime.ready_checkpoint is not None
            else None
        ),
        "checkpoints": [
            _checkpoint_private_record(checkpoint)
            for checkpoint in runtime.checkpoints
        ],
    }


def run_planning_phase(
    *,
    phase: str,
    first_body: dict[str, Any],
    max_turns: int,
    store: CallStore,
    run_dir: Path,
    expected_parent_history: list[dict[str, Any]] | None = None,
) -> PlanningPhaseRuntime:
    if phase not in {"baseline", "adjusted"}:
        raise ValueError("invalid planning phase")
    if max_turns <= 0:
        raise ValueError("planning phase must allow at least one turn")
    if expected_parent_history is not None:
        if first_body.get("contents", [])[:-1] != expected_parent_history:
            raise ValueError("first adjusted request changed the baseline parent history")

    checkpoints: list[CheckpointRuntime] = []
    history: list[dict[str, Any]] = []
    if expected_parent_history is not None:
        history = copy.deepcopy(expected_parent_history)
    ready_checkpoint: CheckpointRuntime | None = None
    terminal = ""
    last_classification: str | None = None
    attempt_summaries: list[dict[str, Any]] = []
    private_path = run_dir / f"{phase}_planning.private.json"

    for turn_number in range(1, max_turns + 1):
        if turn_number == 1:
            body = copy.deepcopy(first_body)
        else:
            body = protocol.planning_continuation_body(
                full_history=history,
                phase=phase,
                turn_number=turn_number,
            )
            if body["contents"][:-1] != history:
                raise RuntimeError("planning continuation changed exact prior history")

        result, call = _invoke(
            store=store,
            label=f"{phase}_planning_turn_{turn_number}",
            body=body,
        )
        evaluated = evaluate_planning_turn(result)
        last_classification = evaluated.readiness_observation
        turn_summary: dict[str, Any] = {
            "turn_number": turn_number,
            "provider_status": evaluated.provider_status,
            "readiness_observation": evaluated.readiness_observation,
            "controller_action": evaluated.controller_action,
            "carrier_replayable": evaluated.carrier_replayable,
            "reasons": evaluated.reasons,
            "request_input_sha256": protocol.sha256_json(body["contents"]),
            "response_steps_sha256": protocol.sha256_json(evaluated.steps),
            "call": call,
            **evaluated.safe_metadata,
        }
        attempt_summaries.append(turn_summary)
        write_json(
            run_dir / f"{phase}_planning_attempts.json", attempt_summaries
        )

        if evaluated.controller_action == ACTION_TERMINATE_TECHNICAL:
            terminal = (
                "TECHNICAL_TERMINATION_NO_REPLAYABLE_CHECKPOINT"
                if not evaluated.carrier_replayable
                else "TECHNICAL_TERMINATION_NONCONTINUABLE_RESPONSE"
            )
            provisional = PlanningPhaseRuntime(
                phase=phase,
                checkpoints=checkpoints,
                ready_checkpoint=None,
                terminal=terminal,
                last_turn_classification=last_classification,
                public_summary={},
            )
            write_json(private_path, _phase_private_record(provisional))
            break

        history = [
            *copy.deepcopy(body["contents"]),
            *copy.deepcopy(evaluated.steps),
        ]
        checkpoint = CheckpointRuntime(
            checkpoint_id=generate_opaque_id(),
            phase=phase,
            turn_number=turn_number,
            readiness_observation=str(evaluated.readiness_observation),
            provider_status=evaluated.provider_status,
            full_history=copy.deepcopy(history),
            response_steps=copy.deepcopy(evaluated.steps),
            summary=turn_summary,
        )
        checkpoints.append(checkpoint)
        provisional = PlanningPhaseRuntime(
            phase=phase,
            checkpoints=checkpoints,
            ready_checkpoint=(
                checkpoint
                if evaluated.controller_action == ACTION_FREEZE_READY
                else None
            ),
            terminal="",
            last_turn_classification=last_classification,
            public_summary={},
        )
        write_json(private_path, _phase_private_record(provisional))

        if evaluated.controller_action == ACTION_FREEZE_READY:
            ready_checkpoint = checkpoint
            terminal = "COMPLETED_READY_CHECKPOINT"
            break
        if turn_number == max_turns:
            terminal = protocol.PLANNING_THRESHOLD_REACHED

    if not terminal:
        terminal = protocol.PLANNING_THRESHOLD_REACHED
    public_summary = {
        "schema_version": "modernization_planning_phase_summary_v1",
        "phase": phase,
        "terminal": terminal,
        "last_turn_classification": last_classification,
        "turns_attempted": len(attempt_summaries),
        "replayable_checkpoints": len(checkpoints),
        "ready_checkpoint_id": (
            ready_checkpoint.checkpoint_id if ready_checkpoint else None
        ),
        "ready_turn": ready_checkpoint.turn_number if ready_checkpoint else None,
        "turns": attempt_summaries,
        "checkpoints": [checkpoint.summary for checkpoint in checkpoints],
    }
    runtime = PlanningPhaseRuntime(
        phase=phase,
        checkpoints=checkpoints,
        ready_checkpoint=ready_checkpoint,
        terminal=terminal,
        last_turn_classification=last_classification,
        public_summary=public_summary,
    )
    _assert_no_raw_signatures(
        public_summary,
        _raw_signatures(_phase_private_record(runtime)),
    )
    write_json(private_path, _phase_private_record(runtime))
    write_json(run_dir / f"{phase}_planning_summary.json", public_summary)
    return runtime


def _evaluate_observation_response(
    result: GenerateContentHttpResult,
    *,
    context: str = "inspection",
) -> tuple[bool, str, list[dict[str, Any]], dict[str, Any], list[str]]:
    if context not in {"inspection", "execution"}:
        raise ValueError("observation response context is invalid")
    reasons: list[str] = []
    payload = result.payload
    if result.http_status is None or not 200 <= result.http_status < 300:
        reasons.append(f"{context} was not HTTP 2xx")
    if result.transport_error:
        reasons.append(f"{context} transport error")
    if result.response_parse_error or not isinstance(payload, dict):
        reasons.append(f"{context} response was not a JSON object")
        payload = {}
    if "error" in payload or "errors" in payload:
        reasons.append(f"{context} response contained a top-level error")
    finish_reasons = _explicit_finish_reasons(result.payload)
    normalized_finish_reasons = {
        _normalized_finish_reason(reason) for reason in finish_reasons
    }
    provider_status = (
        "completed"
        if normalized_finish_reasons == COMPLETED_FINISH_REASONS
        else "incomplete"
        if normalized_finish_reasons
        and normalized_finish_reasons.issubset(OUTPUT_BUDGET_FINISH_REASONS)
        else ""
    )
    if provider_status != "completed":
        reasons.append(
            f"{context} generateContent finishReason was not STOP"
        )
    if payload.get("modelVersion") != protocol.MODEL:
        reasons.append(f"{context} returned a different model")
    steps: list[dict[str, Any]] = []
    if isinstance(result.payload, dict):
        try:
            steps = response_contents(result.payload)
        except ValueError as exc:
            reasons.append(f"{context} response Content was invalid: {exc}")
    try:
        protocol.assert_no_function_tool_or_schema_structure(steps)
    except ValueError as exc:
        reasons.append(str(exc))
    visible, output_issues = _ordinary_visible_text(steps)
    reasons.extend(output_issues)
    if not protocol.normalize_readiness_text(visible):
        reasons.append(f"{context} visible output was empty")
    safe = {
        "provider_status": provider_status,
        "explicit_finish_reasons": finish_reasons,
        "response_steps_sha256": protocol.sha256_json(steps),
        "visible_text_sha256": protocol.sha256_text(visible),
        "visible_text_chars": len(visible),
        "usage": _safe_usage(result.payload),
        "signature_metadata": thought_signature_metadata(steps),
    }
    reasons = list(dict.fromkeys(reasons))
    return not reasons, visible, copy.deepcopy(steps), safe, reasons


def run_inspections(
    *,
    runtime: PlanningPhaseRuntime,
    store: CallStore,
    run_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    private_rows: list[dict[str, Any]] = []
    for checkpoint in runtime.checkpoints:
        source_hash = protocol.sha256_json(checkpoint.response_steps)
        body = protocol.inspection_body(
            response_steps=checkpoint.response_steps,
            checkpoint_id=checkpoint.checkpoint_id,
        )
        if protocol.sha256_json(checkpoint.response_steps) != source_hash:
            raise RuntimeError("inspection construction mutated live checkpoint")
        if "systemInstruction" in body:
            raise RuntimeError("isolated inspection included a system instruction")
        result, call = _invoke(
            store=store,
            label=(
                f"{runtime.phase}_inspection_turn_{checkpoint.turn_number}_"
                f"{checkpoint.checkpoint_id}"
            ),
            body=body,
        )
        eligible, visible, steps, safe, reasons = _evaluate_observation_response(
            result
        )
        row = {
            "checkpoint_id": checkpoint.checkpoint_id,
            "phase": runtime.phase,
            "turn_number": checkpoint.turn_number,
            "checkpoint_readiness_observation": checkpoint.readiness_observation,
            "eligible_observation": eligible,
            "reasons": reasons,
            "observation": visible,
            "carrier_sha256": protocol.sha256_json(body["contents"][:-1]),
            "request_input_sha256": protocol.sha256_json(body["contents"]),
            "call": call,
            **safe,
        }
        rows.append(row)
        private_rows.append(
            {
                **copy.deepcopy(row),
                "request_body": body,
                "response_steps": steps,
            }
        )
        captured_signatures = _raw_signatures(
            [
                *[item.response_steps for item in runtime.checkpoints],
                *private_rows,
            ]
        )
        _assert_no_raw_signatures(rows, captured_signatures)
        write_json(
            run_dir / f"{runtime.phase}_observations.private.json", private_rows
        )
        write_json(run_dir / f"{runtime.phase}_observations.json", rows)
    # Preserve an explicit empty measurement result when a phase terminates
    # before producing any replayable checkpoint.
    write_json(run_dir / f"{runtime.phase}_observations.private.json", private_rows)
    write_json(run_dir / f"{runtime.phase}_observations.json", rows)
    seal = {
        "schema_version": "modernization_observation_seal_v1",
        "phase": runtime.phase,
        "created_at": utc_now(),
        "checkpoint_count": len(runtime.checkpoints),
        "observation_count": len(rows),
        "rows_sha256": protocol.sha256_json(rows),
        "live_history_sha256_by_checkpoint": {
            checkpoint.checkpoint_id: protocol.sha256_json(checkpoint.full_history)
            for checkpoint in runtime.checkpoints
        },
    }
    all_signatures = _raw_signatures(
        [
            *[item.response_steps for item in runtime.checkpoints],
            *private_rows,
        ]
    )
    _assert_no_raw_signatures(rows, all_signatures)
    _assert_no_raw_signatures(seal, all_signatures)
    write_json(run_dir / f"{runtime.phase}_observation_seal.json", seal)
    return rows, seal


def _phase_review_markdown(
    *, runtime: PlanningPhaseRuntime, observations: list[dict[str, Any]]
) -> str:
    lines = [
        f"# {runtime.phase.title()} planning and isolated observations",
        "",
        f"- Terminal: `{runtime.terminal}`",
        f"- Last classification: `{runtime.last_turn_classification}`",
        f"- Planning checkpoints: {len(runtime.checkpoints)}",
        f"- Completed READY checkpoint: "
        f"`{runtime.ready_checkpoint.checkpoint_id if runtime.ready_checkpoint else 'NONE'}`",
        "",
    ]
    for row in observations:
        eligible = bool(row.get("eligible_observation"))
        reasons = row.get("reasons")
        reason_lines = (
            [f"- {reason}" for reason in reasons]
            if isinstance(reasons, list) and reasons
            else ["- NONE"]
        )
        lines.extend(
            [
                f"## Turn {row['turn_number']} — {row['checkpoint_id']}",
                "",
                f"Planning classification: `{row['checkpoint_readiness_observation']}`",
                "",
                f"Observation eligibility: `{'ELIGIBLE' if eligible else 'INELIGIBLE'}`",
                "",
                "Observation eligibility reasons:",
                "",
                *reason_lines,
                "",
                "Observation text (retained even when ineligible):",
                "",
                str(row["observation"] or "[observation unavailable]"),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _execution_response(
    result: GenerateContentHttpResult,
) -> tuple[bool, str, dict[str, Any], list[dict[str, Any]], list[str]]:
    eligible, visible, steps, safe, reasons = _evaluate_observation_response(
        result, context="execution"
    )
    return eligible, visible, safe, steps, reasons


def run_executions(
    *,
    baseline: CheckpointRuntime,
    adjusted: CheckpointRuntime,
    store: CallStore,
    run_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if (
        baseline.phase != "baseline"
        or adjusted.phase != "adjusted"
        or baseline.checkpoint_id == adjusted.checkpoint_id
        or baseline.provider_status != "completed"
        or adjusted.provider_status != "completed"
        or baseline.readiness_observation != protocol.READY
        or adjusted.readiness_observation != protocol.READY
    ):
        raise ValueError(
            "execution parent is not a completed READY baseline/adjusted pair"
        )
    rows: list[dict[str, Any]] = []
    private_rows: list[dict[str, Any]] = []
    parents = {"baseline": baseline, "adjusted": adjusted}
    for schedule_row in protocol.build_execution_schedule():
        branch = str(schedule_row["branch"])
        replicate = int(schedule_row["replicate"])
        parent = parents[branch]
        parent_hash = protocol.sha256_json(parent.full_history)
        body = protocol.execution_body(
            full_history=parent.full_history,
            branch=branch,
            replicate=replicate,
        )
        if body["contents"][:-1] != parent.full_history:
            raise RuntimeError("execution request changed its exact parent history")
        if protocol.sha256_json(parent.full_history) != parent_hash:
            raise RuntimeError("execution construction mutated its parent checkpoint")
        result, call = _invoke(
            store=store,
            label=f"execution_{branch}_replicate_{replicate}",
            body=body,
        )
        eligible, visible, safe, steps, reasons = _execution_response(result)
        row = {
            "schedule_order": schedule_row["order"],
            "branch": branch,
            "replicate": replicate,
            "parent_checkpoint_id": parent.checkpoint_id,
            "eligible": eligible,
            "reasons": reasons,
            "memorandum": visible,
            "parent_history_sha256": parent_hash,
            "request_input_sha256": protocol.sha256_json(body["contents"]),
            "call": call,
            **safe,
        }
        rows.append(row)
        private_rows.append(
            {
                **copy.deepcopy(row),
                "request_body": body,
                "response_steps": steps,
            }
        )
        _assert_no_raw_signatures(rows, _raw_signatures(private_rows))
        write_json(run_dir / "executions.private.json", private_rows)
        write_json(run_dir / "executions.json", rows)
    seal = {
        "schema_version": "modernization_execution_seal_v1",
        "created_at": utc_now(),
        "rows": len(rows),
        "rows_sha256": protocol.sha256_json(rows),
        "baseline_checkpoint_id": baseline.checkpoint_id,
        "adjusted_checkpoint_id": adjusted.checkpoint_id,
    }
    _assert_no_raw_signatures(rows, _raw_signatures(private_rows))
    _assert_no_raw_signatures(seal, _raw_signatures(private_rows))
    write_json(run_dir / "execution_seal.json", seal)
    return rows, seal


def execution_output_dir(*, repo_root: Path, freeze_id: str) -> Path:
    if re.fullmatch(r"[0-9a-f]{64}", freeze_id) is None:
        raise ValueError("freeze ID must be a lowercase SHA-256 digest")
    return repo_root.resolve() / "results" / "reasoning_engineering" / freeze_id


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


def _assert_execution_paths_are_ignored(
    *, repo_root: Path, output_dir: Path
) -> None:
    root = repo_root.resolve()
    candidates = (
        output_dir,
        output_dir / "baseline_planning.private.json",
        output_dir / "baseline_observations.private.json",
        output_dir / "adjusted_planning.private.json",
        output_dir / "adjusted_observations.private.json",
        output_dir / "executions.private.json",
        output_dir / "intervention" / "diagnosis.md",
        output_dir / "raw" / "0001.request.json",
        output_dir / "raw" / "0001.response.bin",
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


def _assert_private_output_root(*, repo_root: Path, output_dir: Path) -> None:
    expected_parent = repo_root.resolve() / "results" / "reasoning_engineering"
    if output_dir.parent != expected_parent:
        raise ValueError("execution output is not in the private results tree")
    _assert_path_has_no_link_ancestor(repo_root=repo_root, path=output_dir)
    _assert_execution_paths_are_ignored(repo_root=repo_root, output_dir=output_dir)


def _strict_json_value(path: Path) -> Any:
    from thoughtlab.reasoningEngineering import modernization_freeze

    if not path.is_file() or _is_link_or_reparse_point(path):
        raise ValueError(f"required JSON artifact is not a safe regular file: {path}")
    try:
        return modernization_freeze.strict_json_loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read strict JSON artifact: {path.name}") from exc


def _strict_json_object(path: Path) -> dict[str, Any]:
    value = _strict_json_value(path)
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact is not an object: {path.name}")
    return value


def _assert_exact_keys(
    value: dict[str, Any], *, expected: set[str], label: str
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"invalid {label} keys; missing={missing}; extra={extra}")


def _raw_signatures(value: Any) -> list[str]:
    signatures: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            for key, signature in item.items():
                if (
                    key.lower().replace("_", "")
                    in {"signature", "thoughtsignature"}
                    and isinstance(signature, str)
                    and signature
                ):
                    signatures.append(signature)
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    return list(dict.fromkeys(signatures))


def _assert_no_raw_signatures(value: Any, signatures: list[str]) -> None:
    serialized = json.dumps(value, ensure_ascii=True, sort_keys=True)
    for signature in signatures:
        if signature and signature in serialized:
            raise RuntimeError("a raw thought signature entered a shareable artifact")


CALL_INDEX_RECORD_KEYS = {
    "call_number",
    "label",
    "started_at",
    "completed_at",
    "attempt_state",
    "http_status",
    "elapsed_ms",
    "request_wire_sha256",
    "request_wire_bytes",
    "response_wire_sha256",
    "response_wire_bytes",
    "response_decoded_chars",
    "transport_error",
    "response_parse_error",
    "response_headers",
    "raw_request_path",
    "raw_response_path",
    "request_target",
}
LOGICAL_CALL_RECORD_KEYS = {
    "logical_request_id",
    "logical_label",
    "started_at",
    "completed_at",
    "attempt_count",
    "selected_attempt",
    "selected_physical_call_number",
    "selected_response_wire_sha256",
    "selection_reason",
    "retried",
    "retry_rule",
    "planned_backoff_seconds",
    "actual_backoff_seconds",
    "request_wire_sha256",
    "request_wire_bytes",
    "first_attempt_http_status",
    "first_attempt_transport_error",
    "request_target",
    "attempts",
}
LOGICAL_ATTEMPT_RECORD_KEYS = {
    *CALL_INDEX_RECORD_KEYS,
    "attempt_index",
    "previous_physical_call_number",
    "retryable_reason",
    "selected_for_logical_result",
}
RETRY_RULE = "transport_or_http_408_429_500_502_503_504_only"


def _canonical_request_target() -> dict[str, str]:
    return {
        "api": protocol.API,
        "method": "POST",
        "endpoint": generate_content_url(model=protocol.MODEL),
        "model": protocol.MODEL,
    }


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _raw_retryable_reason(record: dict[str, Any]) -> str:
    if record.get("transport_error"):
        return "transport_error"
    status = record.get("http_status")
    if status == 408:
        return "http_408"
    if status == 429:
        return "http_429"
    if status in {500, 502, 503, 504}:
        return f"http_{status}"
    return ""


def _file_record(path: Path) -> dict[str, Any]:
    if not path.is_file() or _is_link_or_reparse_point(path):
        raise ValueError(f"artifact is not a safe regular file: {path}")
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": protocol.sha256_bytes(data)}


def _raw_inventory(
    run_dir: Path, *, include_call_index: bool = False
) -> dict[str, dict[str, Any]]:
    raw_dir = run_dir / "raw"
    if not raw_dir.is_dir() or _is_link_or_reparse_point(raw_dir):
        raise ValueError("raw call directory is unavailable or unsafe")
    inventory: dict[str, dict[str, Any]] = {}
    for path in sorted(raw_dir.rglob("*"), key=lambda item: item.as_posix()):
        if _is_link_or_reparse_point(path):
            raise ValueError(f"raw call inventory contains a link: {path}")
        if path.is_dir():
            raise ValueError(f"raw call inventory contains an unexpected directory: {path}")
        if not path.is_file():
            raise ValueError(f"raw call inventory contains a non-file: {path}")
        relative = path.relative_to(run_dir).as_posix()
        if relative == "raw/call_index.json" and not include_call_index:
            continue
        inventory[relative] = _file_record(path)
    return inventory


def _nonraw_inventory(
    *, run_dir: Path, excluded: set[str]
) -> dict[str, dict[str, Any]]:
    inventory: dict[str, dict[str, Any]] = {}
    for path in sorted(run_dir.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(run_dir).as_posix()
        if relative == "raw" or relative.startswith("raw/"):
            continue
        if _is_link_or_reparse_point(path):
            raise ValueError(f"run inventory contains a link: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"run inventory contains a non-file: {relative}")
        if relative in excluded:
            continue
        inventory[relative] = _file_record(path)
    return inventory


def _phase_one_base_nonraw_paths() -> set[str]:
    return {
        *PHASE_ONE_ARTIFACT_PATHS,
        PHASE_ONE_TERMINAL_FILE,
        "phase_one_seal.json",
    }


def _intervention_record_paths() -> set[str]:
    return {f"intervention/{name}" for name in INTERVENTION_RECORD_FILES}


def _phase_one_review_nonraw_paths() -> set[str]:
    return _phase_one_base_nonraw_paths() | _intervention_record_paths()


def _phase_two_entry_nonraw_paths() -> set[str]:
    return _phase_one_review_nonraw_paths() | {
        PHASE_TWO_DISPOSITION_FILE,
        f"intervention/{INTERVENTION_LOCK_FILE}",
    }


def _phase_two_seal_inventory_paths(*, execution_required: bool) -> set[str]:
    paths = _phase_two_entry_nonraw_paths() | {
        PHASE_TWO_CLAIM_FILE,
        "adjusted_planning.private.json",
        "adjusted_planning_attempts.json",
        "adjusted_planning_summary.json",
        "adjusted_observations.private.json",
        "adjusted_observations.json",
        "adjusted_observation_seal.json",
        "PHASE_TWO_TRACE_REVIEW.md",
        "phase_two_summary.json",
    }
    if execution_required:
        paths.update(
            {"executions.json", "executions.private.json", "execution_seal.json"}
        )
    return paths


def _assert_nonraw_path_closure(
    *,
    run_dir: Path,
    expected_paths: set[str],
    label: str,
    excluded: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    inventory = _nonraw_inventory(run_dir=run_dir, excluded=excluded or set())
    if set(inventory) != expected_paths:
        raise ValueError(f"{label} run-tree closure is invalid")
    allowed_directories: set[str] = set()
    for relative in expected_paths:
        parent = Path(relative).parent
        while parent != Path("."):
            allowed_directories.add(parent.as_posix())
            parent = parent.parent
    for path in run_dir.rglob("*"):
        relative = path.relative_to(run_dir).as_posix()
        if relative == "raw" or relative.startswith("raw/"):
            continue
        if path.is_dir() and relative not in allowed_directories:
            raise ValueError(f"{label} run-tree closure has an unexpected directory")
    return inventory


def _assert_canonical_intervention_templates(run_dir: Path) -> None:
    for name, expected_text in INTERVENTION_TEMPLATE_TEXT.items():
        path = run_dir / "intervention" / name
        if not path.is_file() or _is_link_or_reparse_point(path):
            raise ValueError("phase-one intervention template family is incomplete")
        try:
            actual_text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ValueError("phase-one intervention template is unreadable") from exc
        if actual_text != expected_text:
            raise ValueError("phase-one intervention template changed before review")


def _assert_phase_two_entry_closure(run_dir: Path) -> None:
    _assert_nonraw_path_closure(
        run_dir=run_dir,
        expected_paths=_phase_two_entry_nonraw_paths(),
        label="phase-two entry",
    )


def _artifact_inventory(
    *, run_dir: Path, relative_paths: list[str]
) -> dict[str, dict[str, Any]]:
    inventory: dict[str, dict[str, Any]] = {}
    for relative in relative_paths:
        fragment = Path(relative)
        if fragment.is_absolute() or ".." in fragment.parts:
            raise ValueError("terminal artifact path is unsafe")
        path = run_dir / fragment
        _assert_path_has_no_link_ancestor(repo_root=run_dir, path=path)
        inventory[fragment.as_posix()] = _file_record(path)
    return inventory


def _verify_artifact_inventory(
    *, run_dir: Path, inventory: Any
) -> None:
    if not isinstance(inventory, dict) or not inventory:
        raise ValueError("terminal artifact inventory is invalid")
    expected_paths = list(inventory)
    actual = _artifact_inventory(run_dir=run_dir, relative_paths=expected_paths)
    if actual != inventory:
        raise ValueError("terminal artifact changed after phase-two sealing")


def _verify_inventory_records(
    *,
    run_dir: Path,
    expected: dict[str, Any],
    require_exact_raw_inventory: bool,
) -> None:
    if not isinstance(expected, dict):
        raise ValueError("sealed raw inventory is not an object")
    actual = _raw_inventory(run_dir)
    if require_exact_raw_inventory and set(actual) != set(expected):
        raise ValueError("raw call inventory changed after phase-one sealing")
    if not set(expected).issubset(actual):
        raise ValueError("sealed phase-one raw artifacts are missing")
    for relative, record in expected.items():
        if (
            not isinstance(relative, str)
            or not isinstance(record, dict)
            or set(record) != {"bytes", "sha256"}
            or actual.get(relative) != record
        ):
            raise ValueError("sealed phase-one raw artifact changed")


def _validate_call_index(run_dir: Path) -> list[dict[str, Any]]:
    index_path = run_dir / "raw" / "call_index.json"
    value = _strict_json_value(index_path)
    if not isinstance(value, list) or not value:
        raise ValueError("raw call index is absent or empty")
    raw_root = (run_dir / "raw").absolute()
    previous_completed_at: datetime | None = None
    for expected_number, record in enumerate(value, start=1):
        if not isinstance(record, dict) or set(record) != CALL_INDEX_RECORD_KEYS:
            raise ValueError("raw call-index record shape is invalid")
        if (
            type(record.get("call_number")) is not int
            or record.get("call_number") != expected_number
        ):
            raise ValueError("raw call numbers are not contiguous")
        if record.get("attempt_state") != "transport_result_persisted":
            raise ValueError("raw call has no persisted transport result")
        http_status = record.get("http_status")
        elapsed_ms = record.get("elapsed_ms")
        request_wire_bytes = record.get("request_wire_bytes")
        response_wire_bytes = record.get("response_wire_bytes")
        response_decoded_chars = record.get("response_decoded_chars")
        response_headers = record.get("response_headers")
        if (
            (http_status is not None and (
                type(http_status) is not int or not 100 <= http_status <= 599
            ))
            or type(elapsed_ms) is not int
            or elapsed_ms < 0
            or type(request_wire_bytes) is not int
            or request_wire_bytes < 1
            or type(response_wire_bytes) is not int
            or response_wire_bytes < 0
            or type(response_decoded_chars) is not int
            or response_decoded_chars < 0
            or not isinstance(record.get("transport_error"), str)
            or not isinstance(record.get("response_parse_error"), str)
            or not isinstance(response_headers, dict)
            or any(
                not isinstance(key, str) or not isinstance(item, str)
                for key, item in response_headers.items()
            )
            or not _is_sha256(record.get("request_wire_sha256"))
            or record.get("request_target") != _canonical_request_target()
        ):
            raise ValueError("raw call metadata field types are invalid")
        try:
            started_at = _utc_timestamp(
                record.get("started_at"), label="raw call start"
            )
            completed_at = _utc_timestamp(
                record.get("completed_at"), label="raw call completion"
            )
        except ValueError as exc:
            raise ValueError("raw call timestamps are invalid") from exc
        if (
            started_at > completed_at
            or (
                previous_completed_at is not None
                and previous_completed_at > started_at
            )
        ):
            raise ValueError("raw call timestamps are invalid")
        previous_completed_at = completed_at
        if not isinstance(record.get("label"), str) or not record.get("label"):
            raise ValueError("raw call label is invalid")
        request_relative = record.get("raw_request_path")
        response_relative = record.get("raw_response_path")
        if not isinstance(request_relative, str) or not isinstance(
            response_relative, str
        ):
            raise ValueError("raw call paths are invalid")
        request_fragment = Path(request_relative)
        response_fragment = Path(response_relative)
        if request_fragment.is_absolute() or response_fragment.is_absolute():
            raise ValueError("raw call path is absolute")
        request_path = (run_dir / request_fragment).absolute()
        response_path = (run_dir / response_fragment).absolute()
        if not request_path.is_relative_to(raw_root) or not response_path.is_relative_to(
            raw_root
        ):
            raise ValueError("raw call path escapes the private raw directory")
        _assert_path_has_no_link_ancestor(repo_root=run_dir, path=request_path)
        _assert_path_has_no_link_ancestor(repo_root=run_dir, path=response_path)
        request_name = request_path.name
        if not request_name.startswith(f"{expected_number:04d}_") or not request_name.endswith(
            ".request.json"
        ):
            raise ValueError("raw request filename is inconsistent with call number")
        stem = request_name[: -len(".request.json")]
        if response_path.name != f"{stem}.response.bin":
            raise ValueError("raw response filename is inconsistent with request")
        metadata_path = request_path.with_name(f"{stem}.metadata.json")
        request_bytes = request_path.read_bytes()
        response_bytes = response_path.read_bytes()
        expected_response_hash = (
            protocol.sha256_bytes(response_bytes) if response_bytes else None
        )
        if (
            record.get("request_wire_bytes") != len(request_bytes)
            or record.get("request_wire_sha256")
            != protocol.sha256_bytes(request_bytes)
            or record.get("response_wire_bytes") != len(response_bytes)
            or record.get("response_wire_sha256") != expected_response_hash
            or (
                expected_response_hash is not None
                and not _is_sha256(record.get("response_wire_sha256"))
            )
            or record.get("response_decoded_chars")
            != len(response_bytes.decode("utf-8", errors="replace"))
            or _strict_json_object(metadata_path) != record
        ):
            raise ValueError("raw call wire artifact does not match its index")
    return copy.deepcopy(value)


def _bound_generate_content_result(
    *,
    run_dir: Path,
    call_summary: Any,
    expected_label: str,
    expected_body: dict[str, Any],
    call_cursor: PhysicalCallCursor,
) -> GenerateContentHttpResult:
    if not isinstance(call_summary, dict) or set(call_summary) != {
        "logical_request_id",
        "attempt_count",
        "selected_physical_call_number",
        "selected_response_wire_sha256",
        "selection_reason",
        "request_wire_sha256",
    }:
        raise ValueError("semantic artifact call summary shape is invalid")
    records = call_cursor.records
    logical_path = (
        run_dir
        / "raw"
        / f"logical_{_bounded_storage_label(expected_label)}.metadata.json"
    )
    logical_relative = logical_path.relative_to(run_dir).as_posix()
    if logical_relative in call_cursor.logical_paths_used:
        raise ValueError("logical call metadata was consumed more than once")
    logical = _strict_json_object(logical_path)
    if set(logical) != LOGICAL_CALL_RECORD_KEYS:
        raise ValueError("logical call metadata shape is invalid")
    attempts = logical.get("attempts")
    selected_number = logical.get("selected_physical_call_number")
    expected_wire = generate_content_wire_bytes(expected_body)
    expected_wire_hash = protocol.sha256_bytes(expected_wire)
    expected_logical_id = protocol.sha256_text(
        f"{expected_label}:{expected_wire_hash}"
    )[:24]
    if (
        logical.get("logical_label") != expected_label
        or logical.get("logical_request_id") != expected_logical_id
        or logical.get("request_wire_sha256") != expected_wire_hash
        or type(logical.get("request_wire_bytes")) is not int
        or logical.get("request_wire_bytes") != len(expected_wire)
        or not isinstance(attempts, list)
        or not 1 <= len(attempts) <= protocol.MAX_ATTEMPTS_PER_LOGICAL_REQUEST
        or type(logical.get("attempt_count")) is not int
        or logical.get("attempt_count") != len(attempts)
        or type(logical.get("selected_attempt")) is not int
        or logical.get("selected_attempt") != len(attempts)
        or type(selected_number) is not int
        or selected_number != attempts[-1].get("call_number")
        or logical.get("retry_rule") != RETRY_RULE
        or logical.get("planned_backoff_seconds")
        != list(protocol.RETRY_BACKOFF_SECONDS)
        or logical.get("actual_backoff_seconds")
        != list(protocol.RETRY_BACKOFF_SECONDS[: len(attempts) - 1])
        or logical.get("retried") is not (len(attempts) > 1)
        or logical.get("request_target") != _canonical_request_target()
        or call_summary != _safe_call_summary(logical)
    ):
        raise ValueError("semantic artifact is not bound to its logical call")
    expected_numbers = list(
        range(
            call_cursor.next_call_number,
            call_cursor.next_call_number + len(attempts),
        )
    )
    if expected_numbers[-1] > len(records):
        raise ValueError("logical attempt span exceeds the raw call index")
    for attempt_index, attempt in enumerate(attempts, start=1):
        call_number = attempt.get("call_number")
        if (
            not isinstance(attempt, dict)
            or set(attempt) != LOGICAL_ATTEMPT_RECORD_KEYS
            or type(call_number) is not int
            or call_number != expected_numbers[attempt_index - 1]
            or type(attempt.get("attempt_index")) is not int
            or attempt.get("attempt_index") != attempt_index
            or attempt.get("previous_physical_call_number")
            != (expected_numbers[attempt_index - 2] if attempt_index > 1 else None)
            or attempt.get("selected_for_logical_result")
            is not (attempt_index == len(attempts))
        ):
            raise ValueError("logical attempt span is invalid")
        record = records[int(call_number) - 1]
        if any(attempt.get(key) != record.get(key) for key in CALL_INDEX_RECORD_KEYS):
            raise ValueError("logical attempt does not match the raw call index")
        retry_reason = _raw_retryable_reason(record)
        if attempt.get("retryable_reason") != (retry_reason or None):
            raise ValueError("logical attempt retry classification is invalid")
        if attempt_index < len(attempts) and not retry_reason:
            raise ValueError("logical call retried a nonretryable response")
        if record.get("label") != f"{expected_label}_attempt{attempt_index}":
            raise ValueError("physical call label is inconsistent")
        request_path = run_dir / str(record["raw_request_path"])
        if request_path.read_bytes() != expected_wire:
            raise ValueError("raw request body differs from the semantic request")
    selected = records[int(selected_number) - 1]
    final_retry_reason = _raw_retryable_reason(selected)
    expected_selection_reason = (
        "retry_budget_exhausted"
        if final_retry_reason
        else (
            "first_attempt_nonretryable"
            if len(attempts) == 1
            else "first_nonretryable_after_retry"
        )
    )
    try:
        logical_started_at = _utc_timestamp(
            logical.get("started_at"), label="logical call start"
        )
        logical_completed_at = _utc_timestamp(
            logical.get("completed_at"), label="logical call completion"
        )
    except ValueError as exc:
        raise ValueError("logical call timestamps are invalid") from exc
    if (
        (final_retry_reason and len(attempts) != protocol.MAX_ATTEMPTS_PER_LOGICAL_REQUEST)
        or logical.get("selection_reason") != expected_selection_reason
        or logical.get("selected_response_wire_sha256")
        != selected.get("response_wire_sha256")
        or logical.get("first_attempt_http_status")
        != records[expected_numbers[0] - 1].get("http_status")
        or logical.get("first_attempt_transport_error")
        != records[expected_numbers[0] - 1].get("transport_error")
        or logical_started_at
        > _utc_timestamp(
            records[expected_numbers[0] - 1].get("started_at"),
            label="first physical call start",
        )
        or _utc_timestamp(
            selected.get("completed_at"), label="selected physical call completion"
        )
        > logical_completed_at
    ):
        raise ValueError("logical call selection or timing is invalid")
    response_bytes = (run_dir / str(selected["raw_response_path"])).read_bytes()
    raw_body = response_bytes.decode("utf-8", errors="replace")
    payload: dict[str, Any] | None = None
    recorded_parse_error = selected.get("response_parse_error")
    transport_error = str(selected.get("transport_error") or "")
    if transport_error:
        if recorded_parse_error:
            raise ValueError("transport-error raw response state is inconsistent")
    else:
        raw_body, payload, recomputed_parse_error = decode_generate_content_bytes(
            response_bytes
        )
        if recomputed_parse_error != str(recorded_parse_error or ""):
            raise ValueError("raw response parse state differs from call metadata")
    call_cursor.next_call_number += len(attempts)
    call_cursor.logical_paths_used.add(logical_relative)
    return GenerateContentHttpResult(
        http_status=selected.get("http_status"),
        payload=payload,
        raw_body=raw_body,
        transport_error=transport_error,
        response_parse_error=str(recorded_parse_error or ""),
        elapsed_ms=int(selected.get("elapsed_ms") or 0),
        raw_body_bytes=response_bytes,
        response_headers=(
            copy.deepcopy(selected.get("response_headers"))
            if isinstance(selected.get("response_headers"), dict)
            else {}
        ),
    )


def _logical_metadata_paths(run_dir: Path) -> set[str]:
    return {
        path.relative_to(run_dir).as_posix()
        for path in (run_dir / "raw").glob("logical_*.metadata.json")
        if path.is_file()
    }


def _phase_logical_metadata_paths(runtime: PlanningPhaseRuntime) -> set[str]:
    turns_attempted = runtime.public_summary.get("turns_attempted")
    if not isinstance(turns_attempted, int) or isinstance(turns_attempted, bool):
        raise ValueError("planning runtime has no validated logical-call count")
    labels = [
        f"{runtime.phase}_planning_turn_{turn_number}"
        for turn_number in range(1, turns_attempted + 1)
    ]
    labels.extend(
        f"{runtime.phase}_inspection_turn_{checkpoint.turn_number}_"
        f"{checkpoint.checkpoint_id}"
        for checkpoint in runtime.checkpoints
    )
    return {
        f"raw/logical_{_bounded_storage_label(label)}.metadata.json"
        for label in labels
    }


def _assert_call_cursor_closed(
    *,
    run_dir: Path,
    call_cursor: PhysicalCallCursor,
    expected_next_call_number: int,
    require_exact_logical_inventory: bool,
) -> None:
    if call_cursor.next_call_number != expected_next_call_number:
        raise ValueError("raw call index contains an orphan or out-of-order call")
    actual_logical_paths = _logical_metadata_paths(run_dir)
    if not call_cursor.logical_paths_used.issubset(actual_logical_paths):
        raise ValueError("a consumed logical call metadata file is missing")
    if (
        require_exact_logical_inventory
        and call_cursor.logical_paths_used != actual_logical_paths
    ):
        raise ValueError("raw inventory contains orphan logical call metadata")


def _expected_raw_paths(
    *,
    records: list[dict[str, Any]],
    logical_paths: set[str],
    include_call_index: bool,
) -> set[str]:
    expected = set(logical_paths)
    if include_call_index:
        expected.add("raw/call_index.json")
    for record in records:
        request_relative = str(record["raw_request_path"]).replace("\\", "/")
        response_relative = str(record["raw_response_path"]).replace("\\", "/")
        request_path = Path(request_relative)
        stem = request_path.name[: -len(".request.json")]
        metadata_relative = (request_path.parent / f"{stem}.metadata.json").as_posix()
        expected.update(
            {request_relative, response_relative, metadata_relative}
        )
    return expected


def _assert_raw_path_closure(
    *,
    run_dir: Path,
    records: list[dict[str, Any]],
    logical_paths: set[str],
    include_call_index: bool,
) -> None:
    actual = _raw_inventory(run_dir, include_call_index=include_call_index)
    expected = _expected_raw_paths(
        records=records,
        logical_paths=logical_paths,
        include_call_index=include_call_index,
    )
    if set(actual) != expected:
        raise ValueError("raw directory contains an orphan or missing artifact")


def _claim_phase_one_consumption(
    *, run_dir: Path, freeze_id: str
) -> tuple[Path, dict[str, Any]]:
    path = run_dir / PHASE_ONE_CLAIM_FILE
    claim = {
        "schema_version": "modernization_phase_one_consumption_claim_v1",
        "freeze_id": freeze_id,
        "claim_id": generate_opaque_id(),
        "claimed_at": utc_now(),
        "status": "CLAIMED",
    }
    encoded = json.dumps(claim, ensure_ascii=True, indent=2).encode("utf-8")
    with path.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    return path, claim


def _terminalize_phase_one_claim(
    *,
    path: Path,
    claim: dict[str, Any],
    status: str,
    error_type: str | None = None,
    phase_one_seal_sha256: str | None = None,
) -> None:
    terminal_path = path.parent / PHASE_ONE_TERMINAL_FILE
    terminal = {
        "schema_version": "modernization_phase_one_consumption_terminal_v1",
        "freeze_id": claim["freeze_id"],
        "claim_id": claim["claim_id"],
        "claim_bytes_sha256": protocol.sha256_bytes(path.read_bytes()),
        "status": status,
        "terminal_at": utc_now(),
        "error_type": error_type,
        "phase_one_seal_sha256": phase_one_seal_sha256,
    }
    encoded = json.dumps(terminal, ensure_ascii=True, indent=2).encode("utf-8")
    with terminal_path.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def _store(
    *,
    run_dir: Path,
    api_key: str,
    transport: Callable[..., GenerateContentHttpResult] | None = None,
) -> CallStore:
    selected_transport = transport or functools.partial(
        post_generate_content,
        model=protocol.MODEL,
    )
    return CallStore(
        run_dir=run_dir,
        api_key=api_key,
        timeout=protocol.HTTP_TIMEOUT_SECONDS,
        delay_seconds=INTER_REQUEST_DELAY_SECONDS if transport is None else 0,
        transport=selected_transport,
        max_attempts=protocol.MAX_ATTEMPTS_PER_LOGICAL_REQUEST,
        retry_backoff_seconds=protocol.RETRY_BACKOFF_SECONDS,
        request_target=_canonical_request_target(),
    )


def _load_verified_definition(
    *, freeze_dir: Path, expected_freeze_id: str, repo_root: Path
) -> dict[str, Any]:
    from thoughtlab.reasoningEngineering import modernization_freeze

    verification = modernization_freeze.verify_freeze(
        freeze_dir=freeze_dir,
        repo_root=repo_root,
        expected_freeze_id=expected_freeze_id,
    )
    if not verification.get("valid"):
        raise ValueError(
            "freeze verification failed: "
            + "; ".join(str(item) for item in verification.get("errors", []))
        )
    definition_path = freeze_dir.resolve() / modernization_freeze.DEFINITION_NAME
    definition = modernization_freeze.strict_json_loads(
        definition_path.read_text(encoding="utf-8")
    )
    if not isinstance(definition, dict):
        raise ValueError("frozen experiment definition is not an object")
    return definition


def execute_phase_one(
    *,
    repo_root: Path,
    freeze_dir: Path,
    freeze_id: str,
    api_key: str,
    transport: Callable[..., GenerateContentHttpResult] | None = None,
) -> tuple[Path, PlanningPhaseRuntime, list[dict[str, Any]]]:
    definition = _load_verified_definition(
        freeze_dir=freeze_dir,
        expected_freeze_id=freeze_id,
        repo_root=repo_root,
    )
    run_dir = execution_output_dir(repo_root=repo_root, freeze_id=freeze_id)
    _assert_private_output_root(repo_root=repo_root, output_dir=run_dir)
    run_dir.mkdir(parents=True, exist_ok=False)
    _assert_private_output_root(repo_root=repo_root, output_dir=run_dir)
    claim_path, claim = _claim_phase_one_consumption(
        run_dir=run_dir, freeze_id=freeze_id
    )
    try:
        store = _store(run_dir=run_dir, api_key=api_key, transport=transport)
        task_text = str(definition["dossier"]["assembled_task_text"])
        first_body = protocol.initial_planning_body(task_text=task_text)
        runtime = run_planning_phase(
            phase="baseline",
            first_body=first_body,
            max_turns=protocol.MAX_BASELINE_PLANNING_TURNS,
            store=store,
            run_dir=run_dir,
        )
        observations, observation_seal = run_inspections(
            runtime=runtime,
            store=store,
            run_dir=run_dir,
        )
        baseline_private_path = run_dir / "baseline_planning.private.json"
        observations_private_path = run_dir / "baseline_observations.private.json"
        signatures = _raw_signatures(
            [
                *[
                    checkpoint.response_steps
                    for checkpoint in runtime.checkpoints
                ],
                _strict_json_value(observations_private_path),
            ]
        )
        ready_observation = None
        if runtime.ready_checkpoint is not None:
            ready_observation = next(
                (
                    row
                    for row in observations
                    if row.get("checkpoint_id")
                    == runtime.ready_checkpoint.checkpoint_id
                ),
                None,
            )
        ready_observation_eligible = bool(
            ready_observation is not None
            and ready_observation.get("eligible_observation") is True
        )
        intervention_authorized = bool(
            runtime.ready_checkpoint is not None and ready_observation_eligible
        )
        if intervention_authorized:
            phase_one_terminal = "READY_OBSERVATION_ELIGIBLE"
        elif runtime.ready_checkpoint is not None:
            phase_one_terminal = "READY_PRIMARY_OBSERVATION_INVALID"
        else:
            phase_one_terminal = runtime.terminal

        phase_one_review = _phase_review_markdown(
            runtime=runtime, observations=observations
        )
        _assert_no_raw_signatures(phase_one_review, signatures)
        review_path = run_dir / "PHASE_ONE_REVIEW.md"
        write_text(review_path, phase_one_review)
        if intervention_authorized:
            intervention_dir = run_dir / "intervention"
            for name, template_text in INTERVENTION_TEMPLATE_TEXT.items():
                write_text(intervention_dir / name, template_text)

        call_records = _validate_call_index(run_dir)
        phase_one_seal = {
            "schema_version": "modernization_phase_one_seal_v1",
            "freeze_id": freeze_id,
            "created_at": utc_now(),
            "planning_summary_sha256": protocol.sha256_json(runtime.public_summary),
            "observation_seal_sha256": protocol.sha256_json(observation_seal),
            "baseline_planning_private_bytes_sha256": protocol.sha256_bytes(
                baseline_private_path.read_bytes()
            ),
            "baseline_observations_private_bytes_sha256": protocol.sha256_bytes(
                observations_private_path.read_bytes()
            ),
            "ready_checkpoint_id": (
                runtime.ready_checkpoint.checkpoint_id
                if runtime.ready_checkpoint is not None
                else None
            ),
            "phase_two_requires_sealed_intervention": True,
            "phase_one_claim_id": claim["claim_id"],
            "phase_one_claim_bytes_sha256": protocol.sha256_bytes(
                claim_path.read_bytes()
            ),
            "phase_one_terminal": phase_one_terminal,
            "ready_observation_eligible": ready_observation_eligible,
            "intervention_authorized": intervention_authorized,
            "phase_one_call_index_prefix_sha256": protocol.sha256_json(
                call_records
            ),
            "phase_one_call_index_bytes_sha256": protocol.sha256_bytes(
                (run_dir / "raw" / "call_index.json").read_bytes()
            ),
            "phase_one_physical_call_count": len(call_records),
            "phase_one_raw_inventory": _raw_inventory(run_dir),
            "phase_one_artifact_inventory": _artifact_inventory(
                run_dir=run_dir, relative_paths=PHASE_ONE_ARTIFACT_PATHS
            ),
            "phase_one_review_bytes_sha256": protocol.sha256_bytes(
                review_path.read_bytes()
            ),
            "baseline_task_sha256": protocol.sha256_text(task_text),
        }
        _assert_no_raw_signatures(phase_one_seal, signatures)
        phase_one_seal_path = run_dir / "phase_one_seal.json"
        write_json(phase_one_seal_path, phase_one_seal)
        seal_sha256 = protocol.sha256_bytes(phase_one_seal_path.read_bytes())
        _terminalize_phase_one_claim(
            path=claim_path,
            claim=claim,
            status="COMPLETED",
            phase_one_seal_sha256=seal_sha256,
        )
        _verify_phase_one_archive(
            run_dir=run_dir,
            expected_freeze_id=freeze_id,
            expected_task_text=task_text,
        )
    except BaseException as exc:
        try:
            _terminalize_phase_one_claim(
                path=claim_path,
                claim=claim,
                status="TERMINATED_ERROR",
                error_type=type(exc).__name__,
            )
        except OSError:
            pass
        raise
    return run_dir, runtime, observations


def _load_private_phase(path: Path) -> PlanningPhaseRuntime:
    value = _strict_json_object(path)
    _assert_exact_keys(
        value,
        expected={
            "schema_version",
            "phase",
            "terminal",
            "last_turn_classification",
            "ready_checkpoint_id",
            "checkpoints",
        },
        label="private planning archive",
    )
    if value.get("schema_version") != "modernization_planning_phase_private_v1":
        raise ValueError("invalid private planning archive schema")
    rows = value.get("checkpoints")
    if not isinstance(rows, list):
        raise ValueError("private planning checkpoints are not an array")
    checkpoints: list[CheckpointRuntime] = []
    seen_ids: set[str] = set()
    expected_row_keys = {
        "checkpoint_id",
        "phase",
        "turn_number",
        "readiness_observation",
        "provider_status",
        "full_history",
        "response_steps",
        "summary",
    }
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("private planning checkpoint is not an object")
        _assert_exact_keys(
            row, expected=expected_row_keys, label="private planning checkpoint"
        )
        checkpoint_id = row.get("checkpoint_id")
        if not is_opaque_id(checkpoint_id) or checkpoint_id in seen_ids:
            raise ValueError("checkpoint ID is invalid or duplicated")
        seen_ids.add(checkpoint_id)
        phase = row.get("phase")
        turn_number = row.get("turn_number")
        readiness = row.get("readiness_observation")
        provider_status = row.get("provider_status")
        full_history = row.get("full_history")
        replay_steps = row.get("response_steps")
        summary = row.get("summary")
        if phase not in {"baseline", "adjusted"}:
            raise ValueError("checkpoint phase is invalid")
        if not isinstance(turn_number, int) or isinstance(turn_number, bool) or turn_number < 1:
            raise ValueError("checkpoint turn number is invalid")
        if readiness not in {
            protocol.READY,
            protocol.SELF_DECLARED_NOT_READY,
            protocol.UNOBSERVED_TRUNCATED,
            protocol.INVALID_STATUS,
        }:
            raise ValueError("checkpoint readiness observation is invalid")
        if provider_status not in {"completed", "incomplete"}:
            raise ValueError("checkpoint provider status is invalid")
        if not isinstance(full_history, list) or not isinstance(replay_steps, list):
            raise ValueError("checkpoint history or response steps are invalid")
        if not replay_steps or full_history[-len(replay_steps) :] != replay_steps:
            raise ValueError("checkpoint history is not bound to its response steps")
        if _carrier_errors(replay_steps):
            raise ValueError("checkpoint response is not a replayable signed carrier")
        if not isinstance(summary, dict):
            raise ValueError("checkpoint summary is not an object")
        if (
            summary.get("turn_number") != turn_number
            or summary.get("provider_status") != provider_status
            or summary.get("readiness_observation") != readiness
            or summary.get("response_steps_sha256")
            != protocol.sha256_json(replay_steps)
        ):
            raise ValueError("checkpoint summary does not match its private carrier")
        checkpoints.append(
            CheckpointRuntime(
                checkpoint_id=checkpoint_id,
                phase=phase,
                turn_number=turn_number,
                readiness_observation=readiness,
                provider_status=provider_status,
                full_history=copy.deepcopy(full_history),
                response_steps=copy.deepcopy(replay_steps),
                summary=copy.deepcopy(summary),
            )
        )
    ready_id = value.get("ready_checkpoint_id")
    ready = next(
        (item for item in checkpoints if item.checkpoint_id == ready_id), None
    )
    if ready_id is not None and ready is None:
        raise ValueError("private planning READY ID has no matching checkpoint")
    return PlanningPhaseRuntime(
        phase=str(value["phase"]),
        checkpoints=checkpoints,
        ready_checkpoint=ready,
        terminal=str(value["terminal"]),
        last_turn_classification=value.get("last_turn_classification"),
        public_summary={},
    )


def _validate_planning_phase_artifacts(
    *,
    runtime: PlanningPhaseRuntime,
    first_body: dict[str, Any],
    max_turns: int,
    run_dir: Path,
    call_cursor: PhysicalCallCursor,
) -> dict[str, Any]:
    phase = runtime.phase
    attempts = _strict_json_value(run_dir / f"{phase}_planning_attempts.json")
    summary = _strict_json_object(run_dir / f"{phase}_planning_summary.json")
    if (
        not isinstance(attempts, list)
        or not 1 <= len(attempts) <= max_turns
        or len({checkpoint.turn_number for checkpoint in runtime.checkpoints})
        != len(runtime.checkpoints)
    ):
        raise ValueError(f"{phase} planning attempt sequence is invalid")
    checkpoints_by_turn = {
        checkpoint.turn_number: checkpoint for checkpoint in runtime.checkpoints
    }
    verified_checkpoints: list[CheckpointRuntime] = []
    history: list[dict[str, Any]] = []
    terminal = ""
    ready: CheckpointRuntime | None = None
    last_classification: str | None = None
    for turn_number, recorded_turn in enumerate(attempts, start=1):
        if not isinstance(recorded_turn, dict):
            raise ValueError(f"{phase} planning attempt is not an object")
        body = (
            copy.deepcopy(first_body)
            if turn_number == 1
            else protocol.planning_continuation_body(
                full_history=history,
                phase=phase,
                turn_number=turn_number,
            )
        )
        result = _bound_generate_content_result(
            run_dir=run_dir,
            call_summary=recorded_turn.get("call"),
            expected_label=f"{phase}_planning_turn_{turn_number}",
            expected_body=body,
            call_cursor=call_cursor,
        )
        evaluated = evaluate_planning_turn(result)
        last_classification = evaluated.readiness_observation
        expected_turn = {
            "turn_number": turn_number,
            "provider_status": evaluated.provider_status,
            "readiness_observation": evaluated.readiness_observation,
            "controller_action": evaluated.controller_action,
            "carrier_replayable": evaluated.carrier_replayable,
            "reasons": evaluated.reasons,
            "request_input_sha256": protocol.sha256_json(body["contents"]),
            "response_steps_sha256": protocol.sha256_json(evaluated.steps),
            "call": copy.deepcopy(recorded_turn.get("call")),
            **evaluated.safe_metadata,
        }
        if recorded_turn != expected_turn:
            raise ValueError(f"{phase} planning attempt differs from raw response")

        if evaluated.controller_action == ACTION_TERMINATE_TECHNICAL:
            if turn_number != len(attempts) or turn_number in checkpoints_by_turn:
                raise ValueError(f"{phase} technical termination lineage is invalid")
            terminal = (
                "TECHNICAL_TERMINATION_NO_REPLAYABLE_CHECKPOINT"
                if not evaluated.carrier_replayable
                else "TECHNICAL_TERMINATION_NONCONTINUABLE_RESPONSE"
            )
            break

        history = [
            *copy.deepcopy(body["contents"]),
            *copy.deepcopy(evaluated.steps),
        ]
        checkpoint = checkpoints_by_turn.get(turn_number)
        if (
            checkpoint is None
            or checkpoint.phase != phase
            or checkpoint.provider_status != evaluated.provider_status
            or checkpoint.readiness_observation
            != str(evaluated.readiness_observation)
            or checkpoint.full_history != history
            or checkpoint.response_steps != evaluated.steps
            or checkpoint.summary != recorded_turn
        ):
            raise ValueError(f"{phase} checkpoint differs from raw planning call")
        verified_checkpoints.append(checkpoint)
        if evaluated.controller_action == ACTION_FREEZE_READY:
            if turn_number != len(attempts):
                raise ValueError(f"{phase} planning continued after completed READY")
            ready = checkpoint
            terminal = "COMPLETED_READY_CHECKPOINT"
            break
        if turn_number == len(attempts):
            if turn_number != max_turns:
                raise ValueError(f"{phase} planning stopped before a terminal state")
            terminal = protocol.PLANNING_THRESHOLD_REACHED

    if [item.checkpoint_id for item in verified_checkpoints] != [
        item.checkpoint_id for item in runtime.checkpoints
    ]:
        raise ValueError(f"{phase} private checkpoint inventory is inconsistent")
    expected_summary = {
        "schema_version": "modernization_planning_phase_summary_v1",
        "phase": phase,
        "terminal": terminal,
        "last_turn_classification": last_classification,
        "turns_attempted": len(attempts),
        "replayable_checkpoints": len(verified_checkpoints),
        "ready_checkpoint_id": ready.checkpoint_id if ready else None,
        "ready_turn": ready.turn_number if ready else None,
        "turns": attempts,
        "checkpoints": [item.summary for item in verified_checkpoints],
    }
    if (
        summary != expected_summary
        or runtime.terminal != terminal
        or runtime.last_turn_classification != last_classification
        or (runtime.ready_checkpoint.checkpoint_id if runtime.ready_checkpoint else None)
        != (ready.checkpoint_id if ready else None)
    ):
        raise ValueError(f"{phase} planning summary conflicts with raw lineage")
    return copy.deepcopy(summary)


def _validate_observation_phase_artifacts(
    *,
    runtime: PlanningPhaseRuntime,
    run_dir: Path,
    call_cursor: PhysicalCallCursor,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    phase = runtime.phase
    public_rows = _strict_json_value(run_dir / f"{phase}_observations.json")
    private_rows = _strict_json_value(
        run_dir / f"{phase}_observations.private.json"
    )
    seal = _strict_json_object(run_dir / f"{phase}_observation_seal.json")
    if (
        not isinstance(public_rows, list)
        or not isinstance(private_rows, list)
        or len(public_rows) != len(runtime.checkpoints)
        or len(private_rows) != len(runtime.checkpoints)
    ):
        raise ValueError(f"{phase} observation archive count is invalid")
    verified_rows: list[dict[str, Any]] = []
    for checkpoint, public_row, private_row in zip(
        runtime.checkpoints, public_rows, private_rows, strict=True
    ):
        if not isinstance(public_row, dict) or not isinstance(private_row, dict):
            raise ValueError(f"{phase} observation row is not an object")
        body = protocol.inspection_body(
            response_steps=checkpoint.response_steps,
            checkpoint_id=checkpoint.checkpoint_id,
        )
        result = _bound_generate_content_result(
            run_dir=run_dir,
            call_summary=public_row.get("call"),
            expected_label=(
                f"{phase}_inspection_turn_{checkpoint.turn_number}_"
                f"{checkpoint.checkpoint_id}"
            ),
            expected_body=body,
            call_cursor=call_cursor,
        )
        eligible, visible, response, safe, reasons = _evaluate_observation_response(
            result
        )
        expected_row = {
            "checkpoint_id": checkpoint.checkpoint_id,
            "phase": phase,
            "turn_number": checkpoint.turn_number,
            "checkpoint_readiness_observation": (
                checkpoint.readiness_observation
            ),
            "eligible_observation": eligible,
            "reasons": reasons,
            "observation": visible,
            "carrier_sha256": protocol.sha256_json(body["contents"][:-1]),
            "request_input_sha256": protocol.sha256_json(body["contents"]),
            "call": copy.deepcopy(public_row.get("call")),
            **safe,
        }
        expected_private = {
            **copy.deepcopy(expected_row),
            "request_body": body,
            "response_steps": response,
        }
        if public_row != expected_row or private_row != expected_private:
            raise ValueError(
                f"{phase} observation differs from raw generateContent response"
            )
        verified_rows.append(copy.deepcopy(expected_row))
    _assert_exact_keys(
        seal,
        expected={
            "schema_version",
            "phase",
            "created_at",
            "checkpoint_count",
            "observation_count",
            "rows_sha256",
            "live_history_sha256_by_checkpoint",
        },
        label=f"{phase} observation seal",
    )
    try:
        observation_seal_time = _utc_timestamp(
            seal.get("created_at"), label=f"{phase} observation seal time"
        )
    except ValueError as exc:
        raise ValueError(f"{phase} observation seal timestamp is invalid") from exc
    last_consumed_record = (
        call_cursor.records[call_cursor.next_call_number - 2]
        if call_cursor.next_call_number > 1
        else None
    )
    if (
        seal.get("schema_version") != "modernization_observation_seal_v1"
        or seal.get("phase") != phase
        or seal.get("checkpoint_count") != len(runtime.checkpoints)
        or seal.get("observation_count") != len(verified_rows)
        or seal.get("rows_sha256") != protocol.sha256_json(verified_rows)
        or seal.get("live_history_sha256_by_checkpoint")
        != {
            checkpoint.checkpoint_id: protocol.sha256_json(
                checkpoint.full_history
            )
            for checkpoint in runtime.checkpoints
        }
        or (
            last_consumed_record is not None
            and _utc_timestamp(
                last_consumed_record.get("completed_at"),
                label=f"last {phase} observation call time",
            )
            > observation_seal_time
        )
    ):
        raise ValueError(f"{phase} observation seal is inconsistent")
    return verified_rows, copy.deepcopy(seal)


def _validate_execution_artifacts(
    *,
    baseline: CheckpointRuntime,
    adjusted: CheckpointRuntime,
    run_dir: Path,
    call_cursor: PhysicalCallCursor,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    public_rows = _strict_json_value(run_dir / "executions.json")
    private_rows = _strict_json_value(run_dir / "executions.private.json")
    seal = _strict_json_object(run_dir / "execution_seal.json")
    schedule = protocol.build_execution_schedule()
    if (
        not isinstance(public_rows, list)
        or not isinstance(private_rows, list)
        or len(public_rows) != len(schedule)
        or len(private_rows) != len(schedule)
    ):
        raise ValueError("execution archive does not match the frozen schedule")
    parents = {"baseline": baseline, "adjusted": adjusted}
    verified_rows: list[dict[str, Any]] = []
    for schedule_row, public_row, private_row in zip(
        schedule, public_rows, private_rows, strict=True
    ):
        if not isinstance(public_row, dict) or not isinstance(private_row, dict):
            raise ValueError("execution row is not an object")
        branch = str(schedule_row["branch"])
        replicate = int(schedule_row["replicate"])
        parent = parents[branch]
        body = protocol.execution_body(
            full_history=parent.full_history,
            branch=branch,
            replicate=replicate,
        )
        result = _bound_generate_content_result(
            run_dir=run_dir,
            call_summary=public_row.get("call"),
            expected_label=f"execution_{branch}_replicate_{replicate}",
            expected_body=body,
            call_cursor=call_cursor,
        )
        eligible, visible, safe, response, reasons = _execution_response(result)
        expected_row = {
            "schedule_order": schedule_row["order"],
            "branch": branch,
            "replicate": replicate,
            "parent_checkpoint_id": parent.checkpoint_id,
            "eligible": eligible,
            "reasons": reasons,
            "memorandum": visible,
            "parent_history_sha256": protocol.sha256_json(parent.full_history),
            "request_input_sha256": protocol.sha256_json(body["contents"]),
            "call": copy.deepcopy(public_row.get("call")),
            **safe,
        }
        expected_private = {
            **copy.deepcopy(expected_row),
            "request_body": body,
            "response_steps": response,
        }
        if public_row != expected_row or private_row != expected_private:
            raise ValueError(
                "execution row differs from its raw generateContent response"
            )
        verified_rows.append(copy.deepcopy(expected_row))
    _assert_exact_keys(
        seal,
        expected={
            "schema_version",
            "created_at",
            "rows",
            "rows_sha256",
            "baseline_checkpoint_id",
            "adjusted_checkpoint_id",
        },
        label="execution seal",
    )
    try:
        execution_seal_time = _utc_timestamp(
            seal.get("created_at"), label="execution seal time"
        )
    except ValueError as exc:
        raise ValueError("execution seal timestamp is invalid") from exc
    last_execution_record = (
        call_cursor.records[call_cursor.next_call_number - 2]
        if call_cursor.next_call_number > 1
        else None
    )
    if (
        seal.get("schema_version") != "modernization_execution_seal_v1"
        or seal.get("rows") != len(verified_rows)
        or seal.get("rows_sha256") != protocol.sha256_json(verified_rows)
        or seal.get("baseline_checkpoint_id") != baseline.checkpoint_id
        or seal.get("adjusted_checkpoint_id") != adjusted.checkpoint_id
        or last_execution_record is None
        or _utc_timestamp(
            last_execution_record.get("completed_at"),
            label="last execution call time",
        )
        > execution_seal_time
    ):
        raise ValueError("execution seal is inconsistent with frozen schedule")
    return verified_rows, copy.deepcopy(seal)


def _verify_phase_one_archive(
    *,
    run_dir: Path,
    expected_freeze_id: str,
    expected_task_text: str | None = None,
    allow_extended_call_index: bool = False,
    allow_additional_raw_files: bool = False,
    allow_additional_nonraw_files: bool = False,
    require_intervention_authorized: bool = False,
) -> tuple[dict[str, Any], PlanningPhaseRuntime]:
    seal_path = run_dir / "phase_one_seal.json"
    seal = _strict_json_object(seal_path)
    _assert_exact_keys(
        seal, expected=PHASE_ONE_SEAL_KEYS, label="phase-one seal"
    )
    if seal.get("schema_version") != "modernization_phase_one_seal_v1":
        raise ValueError("invalid phase-one seal schema")
    if seal.get("freeze_id") != expected_freeze_id:
        raise ValueError("phase-one seal is bound to a different freeze")
    if seal.get("phase_two_requires_sealed_intervention") is not True:
        raise ValueError("phase-one seal does not require a sealed intervention")
    try:
        seal_time = _utc_timestamp(
            seal.get("created_at"), label="phase-one seal time"
        )
    except ValueError as exc:
        raise ValueError("invalid phase-one seal timestamp") from exc
    claim = _strict_json_object(run_dir / PHASE_ONE_CLAIM_FILE)
    _assert_exact_keys(
        claim,
        expected={
            "schema_version",
            "freeze_id",
            "claim_id",
            "claimed_at",
            "status",
        },
        label="phase-one consumption claim",
    )
    terminal = _strict_json_object(run_dir / PHASE_ONE_TERMINAL_FILE)
    _assert_exact_keys(
        terminal,
        expected={
            "schema_version",
            "freeze_id",
            "claim_id",
            "claim_bytes_sha256",
            "status",
            "terminal_at",
            "error_type",
            "phase_one_seal_sha256",
        },
        label="phase-one consumption terminal",
    )
    try:
        claim_time = _utc_timestamp(
            claim.get("claimed_at"), label="phase-one claim time"
        )
        terminal_time = _utc_timestamp(
            terminal.get("terminal_at"), label="phase-one terminal time"
        )
    except ValueError as exc:
        raise ValueError(
            "phase-one consumption claim is not complete or authentic"
        ) from exc
    if (
        claim.get("schema_version")
        != "modernization_phase_one_consumption_claim_v1"
        or claim.get("freeze_id") != expected_freeze_id
        or not is_opaque_id(claim.get("claim_id"))
        or claim.get("claim_id") != seal.get("phase_one_claim_id")
        or claim.get("status") != "CLAIMED"
        or seal.get("phase_one_claim_bytes_sha256")
        != protocol.sha256_bytes((run_dir / PHASE_ONE_CLAIM_FILE).read_bytes())
        or terminal.get("schema_version")
        != "modernization_phase_one_consumption_terminal_v1"
        or terminal.get("freeze_id") != expected_freeze_id
        or terminal.get("claim_id") != claim.get("claim_id")
        or terminal.get("claim_bytes_sha256")
        != seal.get("phase_one_claim_bytes_sha256")
        or terminal.get("status") != "COMPLETED"
        or terminal.get("error_type") is not None
        or terminal.get("phase_one_seal_sha256")
        != protocol.sha256_bytes(seal_path.read_bytes())
        or claim_time > terminal_time
    ):
        raise ValueError("phase-one consumption claim is not complete or authentic")

    private_path = run_dir / "baseline_planning.private.json"
    observations_private_path = run_dir / "baseline_observations.private.json"
    for private_artifact in (private_path, observations_private_path):
        if not private_artifact.is_file() or _is_link_or_reparse_point(
            private_artifact
        ):
            raise ValueError(
                f"phase-one private artifact is unavailable or unsafe: "
                f"{private_artifact.name}"
            )
    if seal.get("baseline_planning_private_bytes_sha256") != protocol.sha256_bytes(
        private_path.read_bytes()
    ):
        raise ValueError("phase-one baseline checkpoint archive changed after sealing")
    if seal.get(
        "baseline_observations_private_bytes_sha256"
    ) != protocol.sha256_bytes(observations_private_path.read_bytes()):
        raise ValueError("phase-one observation archive changed after sealing")

    planning_summary = _strict_json_object(
        run_dir / "baseline_planning_summary.json"
    )
    observation_seal = _strict_json_object(
        run_dir / "baseline_observation_seal.json"
    )
    if seal.get("planning_summary_sha256") != protocol.sha256_json(
        planning_summary
    ):
        raise ValueError("phase-one planning summary does not match its seal")
    if seal.get("observation_seal_sha256") != protocol.sha256_json(
        observation_seal
    ):
        raise ValueError("phase-one observation seal does not match phase one")

    runtime = _load_private_phase(private_path)
    ready = runtime.ready_checkpoint
    sealed_ready_id = seal.get("ready_checkpoint_id")
    if (
        runtime.phase != "baseline"
        or sealed_ready_id != (ready.checkpoint_id if ready else None)
        or (
            ready is not None
            and (
                runtime.terminal != "COMPLETED_READY_CHECKPOINT"
                or runtime.last_turn_classification != protocol.READY
                or ready.phase != "baseline"
                or ready.provider_status != "completed"
                or ready.readiness_observation != protocol.READY
                or ready.summary.get("controller_action") != ACTION_FREEZE_READY
            )
        )
    ):
        raise ValueError("phase-one private terminal state is inconsistent")

    if [checkpoint.turn_number for checkpoint in runtime.checkpoints] != list(
        range(1, len(runtime.checkpoints) + 1)
    ):
        raise ValueError("phase-one checkpoint sequence is not contiguous")
    call_records = _validate_call_index(run_dir)
    prefix_count = seal.get("phase_one_physical_call_count")
    if (
        not isinstance(prefix_count, int)
        or isinstance(prefix_count, bool)
        or prefix_count < 1
        or len(call_records) < prefix_count
    ):
        raise ValueError("raw call index is not bound to the phase-one prefix")
    try:
        first_request_bytes = (
            run_dir / str(call_records[0]["raw_request_path"])
        ).read_bytes()
        first_request = json.loads(first_request_bytes.decode("utf-8"))
        actual_task_text = first_request["contents"][0]["parts"][0]["text"]
    except (OSError, UnicodeError, ValueError, IndexError, KeyError, TypeError) as exc:
        raise ValueError("baseline archive has no canonical task input") from exc
    if (
        not isinstance(actual_task_text, str)
        or first_request != protocol.initial_planning_body(
            task_text=actual_task_text
        )
        or protocol.sha256_text(actual_task_text)
        != seal.get("baseline_task_sha256")
    ):
        raise ValueError("baseline task does not match its phase-one seal")
    if expected_task_text is not None and actual_task_text != expected_task_text:
        raise ValueError("baseline archive is not bound to the frozen dossier")
    call_cursor = PhysicalCallCursor(
        records=call_records,
        next_call_number=1,
        logical_paths_used=set(),
    )
    validated_planning_summary = _validate_planning_phase_artifacts(
        runtime=runtime,
        first_body=protocol.initial_planning_body(task_text=actual_task_text),
        max_turns=protocol.MAX_BASELINE_PLANNING_TURNS,
        run_dir=run_dir,
        call_cursor=call_cursor,
    )
    if validated_planning_summary != planning_summary:
        raise ValueError("phase-one planning summary was not raw-call validated")
    runtime.public_summary = copy.deepcopy(validated_planning_summary)
    for index, checkpoint in enumerate(runtime.checkpoints):
        request_prefix = checkpoint.full_history[: -len(checkpoint.response_steps)]
        if index == 0:
            expected_initial_text = (
                expected_task_text
                if expected_task_text is not None
                else actual_task_text
            )
            if request_prefix != protocol.initial_planning_body(
                task_text=expected_initial_text
            )["contents"]:
                raise ValueError("baseline archive is not bound to the frozen dossier")
        else:
            expected_prefix = [
                *runtime.checkpoints[index - 1].full_history,
                protocol.user_step(protocol.CONTINUE_PLANNING_PROMPT),
            ]
            if request_prefix != expected_prefix:
                raise ValueError("phase-one continuation lineage is not exact")

    _assert_exact_keys(
        observation_seal,
        expected={
            "schema_version",
            "phase",
            "created_at",
            "checkpoint_count",
            "observation_count",
            "rows_sha256",
            "live_history_sha256_by_checkpoint",
        },
        label="baseline observation seal",
    )
    observation_rows = _strict_json_value(run_dir / "baseline_observations.json")
    observation_private_rows = _strict_json_value(
        run_dir / "baseline_observations.private.json"
    )
    if not isinstance(observation_rows, list):
        raise ValueError("baseline observation rows are not an array")
    if not isinstance(observation_private_rows, list):
        raise ValueError("private baseline observation rows are not an array")
    expected_histories = {
        checkpoint.checkpoint_id: protocol.sha256_json(checkpoint.full_history)
        for checkpoint in runtime.checkpoints
    }
    if (
        observation_seal.get("schema_version")
        != "modernization_observation_seal_v1"
        or observation_seal.get("phase") != "baseline"
        or observation_seal.get("checkpoint_count") != len(runtime.checkpoints)
        or observation_seal.get("observation_count") != len(observation_rows)
        or observation_seal.get("observation_count") != len(runtime.checkpoints)
        or observation_seal.get("rows_sha256")
        != protocol.sha256_json(observation_rows)
        or observation_seal.get("live_history_sha256_by_checkpoint")
        != expected_histories
    ):
        raise ValueError("baseline observation seal is inconsistent with phase one")
    if len(observation_private_rows) != len(observation_rows):
        raise ValueError("private and public observation counts differ")
    for checkpoint, public_row, private_row in zip(
        runtime.checkpoints,
        observation_rows,
        observation_private_rows,
        strict=True,
    ):
        if not isinstance(public_row, dict) or not isinstance(private_row, dict):
            raise ValueError("observation row is not an object")
        public_projection = {
            key: value
            for key, value in private_row.items()
            if key not in {"request_body", "response_steps"}
        }
        if public_projection != public_row:
            raise ValueError("private observation does not match its public projection")
        expected_body = protocol.inspection_body(
            response_steps=checkpoint.response_steps,
            checkpoint_id=checkpoint.checkpoint_id,
        )
        if (
            public_row.get("checkpoint_id") != checkpoint.checkpoint_id
            or public_row.get("phase") != "baseline"
            or public_row.get("turn_number") != checkpoint.turn_number
            or public_row.get("checkpoint_readiness_observation")
            != checkpoint.readiness_observation
            or private_row.get("request_body") != expected_body
            or public_row.get("carrier_sha256")
            != protocol.sha256_json(expected_body["contents"][:-1])
            or public_row.get("request_input_sha256")
            != protocol.sha256_json(expected_body["contents"])
            or public_row.get("response_steps_sha256")
            != protocol.sha256_json(private_row.get("response_steps"))
        ):
            raise ValueError("observation row is not bound to its isolated checkpoint")
    validated_observation_rows, validated_observation_seal = (
        _validate_observation_phase_artifacts(
            runtime=runtime,
            run_dir=run_dir,
            call_cursor=call_cursor,
        )
    )
    if (
        validated_observation_rows != observation_rows
        or validated_observation_seal != observation_seal
    ):
        raise ValueError("baseline observations were not raw-call validated")
    baseline_observation_seal_time = _utc_timestamp(
        observation_seal.get("created_at"), label="baseline observation seal time"
    )
    ready_rows = (
        [
            row
            for row in observation_rows
            if isinstance(row, dict)
            and row.get("checkpoint_id") == ready.checkpoint_id
        ]
        if ready is not None
        else []
    )
    ready_observation_eligible = bool(
        len(ready_rows) == 1
        and ready_rows[0].get("eligible_observation") is True
        and ready_rows[0].get("reasons") == []
    )
    intervention_authorized = bool(
        ready is not None and ready_observation_eligible
    )
    expected_phase_one_terminal = (
        "READY_OBSERVATION_ELIGIBLE"
        if intervention_authorized
        else (
            "READY_PRIMARY_OBSERVATION_INVALID"
            if ready is not None
            else runtime.terminal
        )
    )
    if (
        seal.get("phase_one_terminal") != expected_phase_one_terminal
        or seal.get("ready_observation_eligible")
        is not ready_observation_eligible
        or seal.get("intervention_authorized") is not intervention_authorized
    ):
        raise ValueError("phase-one seal conflicts with raw-validated terminal state")
    if require_intervention_authorized and not intervention_authorized:
        raise ValueError("phase-one archive does not authorize an intervention")
    review_path = run_dir / "PHASE_ONE_REVIEW.md"
    try:
        review_text = review_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError("phase-one review is unreadable") from exc
    expected_review = _phase_review_markdown(
        runtime=runtime, observations=observation_rows
    )
    if (
        review_text != expected_review
        or seal.get("phase_one_review_bytes_sha256")
        != protocol.sha256_bytes(review_path.read_bytes())
    ):
        raise ValueError("phase-one review changed after sealing")
    _assert_call_cursor_closed(
        run_dir=run_dir,
        call_cursor=call_cursor,
        expected_next_call_number=prefix_count + 1,
        require_exact_logical_inventory=not allow_extended_call_index,
    )
    prefix_records = (
        call_records[:prefix_count] if isinstance(prefix_count, int) else []
    )
    sealed_prefix_bytes = (
        (run_dir / "raw" / "call_index.json").read_bytes()
        if not allow_extended_call_index
        else json.dumps(
            prefix_records, ensure_ascii=True, indent=2
        ).encode("utf-8")
    )
    if (
        not isinstance(prefix_count, int)
        or isinstance(prefix_count, bool)
        or prefix_count < 1
        or len(call_records) < prefix_count
        or (not allow_extended_call_index and len(call_records) != prefix_count)
        or seal.get("phase_one_call_index_prefix_sha256")
        != protocol.sha256_json(prefix_records)
        or seal.get("phase_one_call_index_bytes_sha256")
        != protocol.sha256_bytes(sealed_prefix_bytes)
        or claim_time
        > _utc_timestamp(
            call_records[0].get("started_at"), label="first phase-one call time"
        )
        or _utc_timestamp(
            prefix_records[-1].get("completed_at"),
            label="last phase-one call time",
        )
        > seal_time
        or baseline_observation_seal_time > seal_time
        or seal_time > terminal_time
    ):
        raise ValueError("raw call index is not bound to the phase-one prefix")
    phase_one_raw_inventory = seal.get("phase_one_raw_inventory")
    expected_phase_one_raw_paths = _expected_raw_paths(
        records=prefix_records,
        logical_paths=call_cursor.logical_paths_used,
        include_call_index=False,
    )
    if (
        not isinstance(phase_one_raw_inventory, dict)
        or set(phase_one_raw_inventory) != expected_phase_one_raw_paths
    ):
        raise ValueError("phase-one raw inventory has an invalid closure")
    _verify_inventory_records(
        run_dir=run_dir,
        expected=phase_one_raw_inventory,
        require_exact_raw_inventory=not allow_additional_raw_files,
    )
    phase_one_artifacts = seal.get("phase_one_artifact_inventory")
    if not isinstance(phase_one_artifacts, dict) or set(
        phase_one_artifacts
    ) != set(PHASE_ONE_ARTIFACT_PATHS):
        raise ValueError("phase-one artifact inventory has an invalid closure")
    _verify_artifact_inventory(run_dir=run_dir, inventory=phase_one_artifacts)
    if not allow_additional_nonraw_files:
        expected_nonraw_paths = _phase_one_base_nonraw_paths()
        expected_template_paths = _intervention_record_paths()
        present_template_paths = {
            f"intervention/{name}"
            for name in INTERVENTION_RECORD_FILES
            if (run_dir / "intervention" / name).is_file()
        }
        if intervention_authorized:
            if present_template_paths != expected_template_paths:
                raise ValueError(
                    "authorized phase-one intervention template family is incomplete"
                )
            _assert_canonical_intervention_templates(run_dir)
            expected_nonraw_paths.update(expected_template_paths)
        elif present_template_paths:
            raise ValueError(
                "unauthorized phase-one archive contains intervention templates"
            )
        _assert_nonraw_path_closure(
            run_dir=run_dir,
            expected_paths=expected_nonraw_paths,
            label="phase-one non-raw",
        )
    _assert_no_raw_signatures(
        [planning_summary, observation_rows, observation_seal, review_text, seal],
        _raw_signatures(
            [
                *[checkpoint.response_steps for checkpoint in runtime.checkpoints],
                observation_private_rows,
            ]
        ),
    )
    return seal, runtime


def _claim_phase_two_disposition(
    *,
    run_dir: Path,
    freeze_id: str,
    phase_one_seal_bytes: bytes,
    decision_payload_sha256: str,
    disposition: str,
) -> tuple[Path, dict[str, Any]]:
    if disposition not in {"SEALED_INTERVENTION", "NO_VALID_INTERVENTION_TARGET"}:
        raise ValueError("invalid phase-two disposition")
    path = run_dir / PHASE_TWO_DISPOSITION_FILE
    record = {
        "schema_version": "modernization_phase_two_disposition_v1",
        "freeze_id": freeze_id,
        "disposition_id": generate_opaque_id(),
        "phase_one_seal_bytes_sha256": protocol.sha256_bytes(
            phase_one_seal_bytes
        ),
        "decision_payload_sha256": decision_payload_sha256,
        "selected_at": utc_now(),
        "disposition": disposition,
    }
    encoded = json.dumps(record, ensure_ascii=True, indent=2).encode("utf-8")
    try:
        with path.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise FileExistsError("phase-two disposition is already selected") from exc
    return path, record


def _verify_phase_two_disposition(
    *,
    run_dir: Path,
    phase_one_seal_bytes: bytes,
    expected_freeze_id: str,
    expected_disposition: str,
    expected_payload_sha256: str,
) -> tuple[Path, dict[str, Any]]:
    path = run_dir / PHASE_TWO_DISPOSITION_FILE
    record = _strict_json_object(path)
    _assert_exact_keys(
        record,
        expected=PHASE_TWO_DISPOSITION_KEYS,
        label="phase-two disposition",
    )
    _utc_timestamp(record.get("selected_at"), label="phase-two disposition time")
    if (
        record.get("schema_version")
        != "modernization_phase_two_disposition_v1"
        or record.get("freeze_id") != expected_freeze_id
        or record.get("phase_one_seal_bytes_sha256")
        != protocol.sha256_bytes(phase_one_seal_bytes)
        or record.get("decision_payload_sha256") != expected_payload_sha256
        or record.get("disposition") != expected_disposition
        or not is_opaque_id(record.get("disposition_id"))
    ):
        raise ValueError("phase-two disposition is invalid or conflicting")
    return path, record


def seal_intervention_package(
    *,
    intervention_dir: Path,
    phase_one_seal_path: Path,
    expected_freeze_id: str,
    expected_task_text: str,
    expected_run_dir: Path,
) -> dict[str, Any]:
    directory = intervention_dir.resolve()
    if directory != intervention_dir.absolute() or _is_link_or_reparse_point(directory):
        raise ValueError("intervention directory must not be a link/reparse point")
    if directory.parent != phase_one_seal_path.parent.resolve():
        raise ValueError("intervention package is not adjacent to its phase-one seal")
    if directory.parent != expected_run_dir.resolve():
        raise ValueError("intervention package is not in the authorized freeze run")
    if phase_one_seal_path.absolute() != directory.parent / "phase_one_seal.json":
        raise ValueError("phase-one seal path is not canonical")
    phase_one_record = _strict_json_object(phase_one_seal_path)
    _assert_exact_keys(
        phase_one_record,
        expected=PHASE_ONE_SEAL_KEYS,
        label="phase-one seal",
    )
    if (
        phase_one_record.get("schema_version")
        != "modernization_phase_one_seal_v1"
        or phase_one_record.get("phase_two_requires_sealed_intervention") is not True
    ):
        raise ValueError("invalid phase-one seal for intervention binding")
    lock_path = directory / INTERVENTION_LOCK_FILE
    if lock_path.exists():
        raise FileExistsError("intervention package is already sealed")
    phase_one_bytes = phase_one_seal_path.read_bytes()
    records: dict[str, Any] = {}
    record_texts: list[str] = []
    for name in INTERVENTION_RECORD_FILES:
        path = directory / name
        if not path.is_file() or _is_link_or_reparse_point(path):
            raise ValueError(f"intervention record is not a safe regular file: {name}")
        data = path.read_bytes()
        try:
            text = data.decode("utf-8").strip()
        except UnicodeError as exc:
            raise ValueError(f"intervention record is not UTF-8: {name}") from exc
        if not text:
            raise ValueError(f"intervention record is empty: {name}")
        if "REPLACE_BEFORE_SEALING" in text:
            raise ValueError(f"intervention record still contains template marker: {name}")
        if name == "intervention.txt" and protocol.EXECUTION_TRIGGER in text:
            raise ValueError("intervention text contains the execution trigger")
        record_texts.append(text)
        records[name] = {
            "bytes": len(data),
            "sha256": protocol.sha256_bytes(data),
        }
    _verified_seal, verified_runtime = _verify_phase_one_archive(
        run_dir=directory.parent,
        expected_freeze_id=expected_freeze_id,
        expected_task_text=expected_task_text,
        allow_additional_nonraw_files=True,
        require_intervention_authorized=True,
    )
    _assert_nonraw_path_closure(
        run_dir=directory.parent,
        expected_paths=_phase_one_review_nonraw_paths(),
        label="intervention sealing preflight",
    )
    _assert_no_raw_signatures(
        record_texts,
        _raw_signatures(
            [
                *[
                    checkpoint.response_steps
                    for checkpoint in verified_runtime.checkpoints
                ],
                _strict_json_value(
                    directory.parent / "baseline_observations.private.json"
                ),
            ]
        ),
    )
    disposition_path, _disposition = _claim_phase_two_disposition(
        run_dir=directory.parent,
        freeze_id=expected_freeze_id,
        phase_one_seal_bytes=phase_one_bytes,
        decision_payload_sha256=protocol.sha256_json(records),
        disposition="SEALED_INTERVENTION",
    )
    lock = {
        "schema_version": "modernization_intervention_lock_v1",
        "created_at": utc_now(),
        "phase_one_seal_sha256": protocol.sha256_bytes(phase_one_bytes),
        "disposition_claim_bytes_sha256": protocol.sha256_bytes(
            disposition_path.read_bytes()
        ),
        "records": records,
        "sealed_before_phase_two": True,
    }
    write_json(lock_path, lock)
    _assert_phase_two_entry_closure(directory.parent)
    verified_lock, _verified_records = verify_intervention_package(
        intervention_dir=directory,
        phase_one_seal_path=phase_one_seal_path,
    )
    if verified_lock != lock:
        raise ValueError("intervention lock failed immediate reverse verification")
    return lock


def verify_intervention_package(
    *, intervention_dir: Path, phase_one_seal_path: Path
) -> tuple[dict[str, Any], dict[str, str]]:
    directory = intervention_dir.resolve()
    if directory != intervention_dir.absolute() or _is_link_or_reparse_point(directory):
        raise ValueError("intervention directory must not be a link/reparse point")
    if directory.parent != phase_one_seal_path.parent.resolve():
        raise ValueError("intervention package is not adjacent to its phase-one seal")
    inventory = {path.name for path in directory.iterdir()}
    expected_inventory = {*INTERVENTION_RECORD_FILES, INTERVENTION_LOCK_FILE}
    if inventory != expected_inventory:
        raise ValueError("intervention directory inventory changed after sealing")
    lock = _strict_json_object(directory / INTERVENTION_LOCK_FILE)
    _assert_exact_keys(
        lock, expected=INTERVENTION_LOCK_KEYS, label="intervention lock"
    )
    if lock.get("schema_version") != "modernization_intervention_lock_v1":
        raise ValueError("invalid intervention lock schema")
    if lock.get("sealed_before_phase_two") is not True:
        raise ValueError("intervention lock was not sealed before phase two")
    records = lock.get("records")
    if not isinstance(records, dict) or set(records) != set(INTERVENTION_RECORD_FILES):
        raise ValueError("intervention lock record inventory is invalid")
    if lock.get("phase_one_seal_sha256") != protocol.sha256_bytes(
        phase_one_seal_path.read_bytes()
    ):
        raise ValueError("intervention lock is bound to a different phase-one seal")
    phase_one_record = _strict_json_object(phase_one_seal_path)
    disposition_path, disposition = _verify_phase_two_disposition(
        run_dir=directory.parent,
        phase_one_seal_bytes=phase_one_seal_path.read_bytes(),
        expected_freeze_id=str(phase_one_record.get("freeze_id")),
        expected_disposition="SEALED_INTERVENTION",
        expected_payload_sha256=protocol.sha256_json(records),
    )
    if lock.get("disposition_claim_bytes_sha256") != protocol.sha256_bytes(
        disposition_path.read_bytes()
    ):
        raise ValueError("intervention lock is bound to a different disposition")
    lock_time = _utc_timestamp(
        lock.get("created_at"), label="intervention lock time"
    )
    disposition_time = _utc_timestamp(
        disposition.get("selected_at"), label="phase-two disposition time"
    )
    if disposition_time > lock_time:
        raise ValueError("intervention lock predates its disposition")
    phase_one_terminal_path = directory.parent / PHASE_ONE_TERMINAL_FILE
    if phase_one_terminal_path.is_file():
        phase_one_terminal = _strict_json_object(phase_one_terminal_path)
        if _utc_timestamp(
            phase_one_terminal.get("terminal_at"),
            label="phase-one terminal time",
        ) > disposition_time:
            raise ValueError("intervention disposition predates phase one")
    texts: dict[str, str] = {}
    for name in INTERVENTION_RECORD_FILES:
        path = directory / name
        if not path.is_file() or _is_link_or_reparse_point(path):
            raise ValueError(f"intervention record is not a safe regular file: {name}")
        data = path.read_bytes()
        expected = records[name]
        if not isinstance(expected, dict) or set(expected) != {"bytes", "sha256"}:
            raise ValueError(f"intervention lock metadata is invalid: {name}")
        if expected.get("bytes") != len(data) or expected.get(
            "sha256"
        ) != protocol.sha256_bytes(data):
            raise ValueError(f"sealed intervention record changed: {name}")
        try:
            text = data.decode("utf-8").strip()
        except UnicodeError as exc:
            raise ValueError(f"intervention record is not UTF-8: {name}") from exc
        if not text or "REPLACE_BEFORE_SEALING" in text:
            raise ValueError(f"sealed intervention record is empty or templated: {name}")
        if name == "intervention.txt" and protocol.EXECUTION_TRIGGER in text:
            raise ValueError("intervention text contains the execution trigger")
        texts[name] = text
    return lock, texts


def _claim_phase_two_consumption(
    *,
    run_dir: Path,
    freeze_id: str,
    ready_checkpoint_id: str,
    intervention_lock_sha256: str,
) -> tuple[Path, dict[str, Any]]:
    path = run_dir / PHASE_TWO_CLAIM_FILE
    claim = {
        "schema_version": "modernization_phase_two_consumption_claim_v1",
        "freeze_id": freeze_id,
        "claim_id": generate_opaque_id(),
        "ready_checkpoint_id": ready_checkpoint_id,
        "intervention_lock_sha256": intervention_lock_sha256,
        "claimed_at": utc_now(),
        "status": "CLAIMED",
    }
    encoded = json.dumps(claim, ensure_ascii=True, indent=2).encode("utf-8")
    try:
        with path.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise FileExistsError(
            "phase two has already been claimed for this freeze run"
        ) from exc
    return path, claim


def _terminalize_phase_two_claim(
    *,
    path: Path,
    claim: dict[str, Any],
    status: str,
    error_type: str | None = None,
    phase_two_seal_sha256: str | None = None,
) -> None:
    terminal_path = path.parent / PHASE_TWO_TERMINAL_FILE
    terminal = {
        "schema_version": "modernization_phase_two_consumption_terminal_v1",
        "freeze_id": claim["freeze_id"],
        "claim_id": claim["claim_id"],
        "claim_bytes_sha256": protocol.sha256_bytes(path.read_bytes()),
        "status": status,
        "terminal_at": utc_now(),
        "error_type": error_type,
        "phase_two_seal_sha256": phase_two_seal_sha256,
    }
    encoded = json.dumps(terminal, ensure_ascii=True, indent=2).encode("utf-8")
    with terminal_path.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def record_no_valid_intervention_target(
    *,
    phase_one_seal_path: Path,
    note_path: Path,
    expected_freeze_id: str,
    expected_task_text: str,
    expected_run_dir: Path,
) -> dict[str, Any]:
    if not phase_one_seal_path.is_file() or _is_link_or_reparse_point(
        phase_one_seal_path
    ):
        raise ValueError("phase-one seal is unavailable or unsafe")
    run_dir = phase_one_seal_path.parent.resolve()
    if phase_one_seal_path.absolute() != run_dir / "phase_one_seal.json":
        raise ValueError("phase-one seal path is not canonical")
    if run_dir != expected_run_dir.resolve():
        raise ValueError("phase-one seal is not in the authorized freeze run")
    marker_path = run_dir / NO_INTERVENTION_TARGET_FILE
    if marker_path.exists():
        raise FileExistsError("no-target terminal is already recorded")
    if (
        (run_dir / PHASE_TWO_CLAIM_FILE).exists()
        or (run_dir / "phase_two_summary.json").exists()
        or (run_dir / INTERVENTION_LOCK_FILE).exists()
        or (run_dir / "intervention" / INTERVENTION_LOCK_FILE).exists()
    ):
        raise FileExistsError("phase two or a sealed intervention already exists")
    if not note_path.is_file() or _is_link_or_reparse_point(note_path):
        raise ValueError("no-target note is not a safe regular file")
    try:
        note_bytes = note_path.read_bytes()
        note = note_bytes.decode("utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise ValueError("no-target note is not readable UTF-8") from exc
    if not note or "REPLACE_BEFORE_SEALING" in note:
        raise ValueError("no-target note is empty or templated")
    canonical_note_path = run_dir / NO_INTERVENTION_NOTE_FILE
    expected_entry_paths = _phase_one_review_nonraw_paths()
    if note_path.absolute() == canonical_note_path.absolute():
        expected_entry_paths.add(NO_INTERVENTION_NOTE_FILE)
    _assert_canonical_intervention_templates(run_dir)
    _assert_nonraw_path_closure(
        run_dir=run_dir,
        expected_paths=expected_entry_paths,
        label="no-target preflight",
    )
    seal, runtime = _verify_phase_one_archive(
        run_dir=run_dir,
        expected_freeze_id=expected_freeze_id,
        expected_task_text=expected_task_text,
        allow_additional_nonraw_files=True,
        require_intervention_authorized=True,
    )
    signatures = _raw_signatures(
        [
            *[checkpoint.response_steps for checkpoint in runtime.checkpoints],
            _strict_json_value(run_dir / "baseline_observations.private.json"),
        ]
    )
    _assert_no_raw_signatures(note, signatures)
    phase_one_seal_bytes = phase_one_seal_path.read_bytes()
    disposition_path, _disposition = _claim_phase_two_disposition(
        run_dir=run_dir,
        freeze_id=expected_freeze_id,
        phase_one_seal_bytes=phase_one_seal_bytes,
        decision_payload_sha256=protocol.sha256_bytes(note_bytes),
        disposition="NO_VALID_INTERVENTION_TARGET",
    )
    if note_path.absolute() != canonical_note_path.absolute():
        try:
            with canonical_note_path.open("xb") as handle:
                handle.write(note_bytes)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise FileExistsError("canonical no-target note already exists") from exc
    no_target_inventory_paths = _phase_one_review_nonraw_paths() | {
        PHASE_TWO_DISPOSITION_FILE,
        NO_INTERVENTION_NOTE_FILE,
    }
    artifact_inventory = _assert_nonraw_path_closure(
        run_dir=run_dir,
        expected_paths=no_target_inventory_paths,
        label="no-target pre-terminal",
    )
    call_records = _validate_call_index(run_dir)
    marker = {
        "schema_version": "modernization_no_intervention_target_v1",
        "freeze_id": expected_freeze_id,
        "created_at": utc_now(),
        "phase_one_seal_bytes_sha256": protocol.sha256_bytes(
            phase_one_seal_bytes
        ),
        "disposition_claim_bytes_sha256": protocol.sha256_bytes(
            disposition_path.read_bytes()
        ),
        "ready_checkpoint_id": runtime.ready_checkpoint.checkpoint_id,
        "note_file": NO_INTERVENTION_NOTE_FILE,
        "note_record": _file_record(canonical_note_path),
        "phase_one_physical_call_count": len(call_records),
        "phase_one_call_index_bytes_sha256": protocol.sha256_bytes(
            (run_dir / "raw" / "call_index.json").read_bytes()
        ),
        "artifact_inventory": artifact_inventory,
        "raw_inventory": _raw_inventory(run_dir, include_call_index=True),
        "terminal": "NO_VALID_INTERVENTION_TARGET",
        "phase_two_model_calls": 0,
    }
    _assert_no_raw_signatures(marker, signatures)
    encoded = json.dumps(marker, ensure_ascii=True, indent=2).encode("utf-8")
    try:
        with marker_path.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise FileExistsError("no-target terminal is already recorded") from exc
    return verify_no_valid_intervention_target(
        phase_one_seal_path=phase_one_seal_path,
        expected_freeze_id=expected_freeze_id,
        expected_task_text=expected_task_text,
    )


def verify_no_valid_intervention_target(
    *,
    phase_one_seal_path: Path,
    expected_freeze_id: str,
    expected_task_text: str,
) -> dict[str, Any]:
    run_dir = phase_one_seal_path.parent.resolve()
    if phase_one_seal_path.absolute() != run_dir / "phase_one_seal.json":
        raise ValueError("phase-one seal path is not canonical")
    seal, runtime = _verify_phase_one_archive(
        run_dir=run_dir,
        expected_freeze_id=expected_freeze_id,
        expected_task_text=expected_task_text,
        allow_additional_nonraw_files=True,
        require_intervention_authorized=True,
    )
    _assert_canonical_intervention_templates(run_dir)
    marker = _strict_json_object(run_dir / NO_INTERVENTION_TARGET_FILE)
    _assert_exact_keys(
        marker,
        expected={
            "schema_version",
            "freeze_id",
            "created_at",
            "phase_one_seal_bytes_sha256",
            "disposition_claim_bytes_sha256",
            "ready_checkpoint_id",
            "note_file",
            "note_record",
            "phase_one_physical_call_count",
            "phase_one_call_index_bytes_sha256",
            "artifact_inventory",
            "raw_inventory",
            "terminal",
            "phase_two_model_calls",
        },
        label="no-target terminal",
    )
    note_path = run_dir / NO_INTERVENTION_NOTE_FILE
    note_record = _file_record(note_path)
    disposition_path, disposition = _verify_phase_two_disposition(
        run_dir=run_dir,
        phase_one_seal_bytes=phase_one_seal_path.read_bytes(),
        expected_freeze_id=expected_freeze_id,
        expected_disposition="NO_VALID_INTERVENTION_TARGET",
        expected_payload_sha256=note_record["sha256"],
    )
    expected_inventory_paths = _phase_one_review_nonraw_paths() | {
        PHASE_TWO_DISPOSITION_FILE,
        NO_INTERVENTION_NOTE_FILE,
    }
    actual_inventory = _assert_nonraw_path_closure(
        run_dir=run_dir,
        expected_paths=expected_inventory_paths,
        label="no-target terminal",
        excluded={NO_INTERVENTION_TARGET_FILE},
    )
    _assert_nonraw_path_closure(
        run_dir=run_dir,
        expected_paths=expected_inventory_paths | {NO_INTERVENTION_TARGET_FILE},
        label="no-target final",
    )
    call_records = _validate_call_index(run_dir)
    marker_time = _utc_timestamp(
        marker.get("created_at"), label="no-target terminal time"
    )
    disposition_time = _utc_timestamp(
        disposition.get("selected_at"), label="phase-two disposition time"
    )
    phase_one_terminal_time = _utc_timestamp(
        _strict_json_object(run_dir / PHASE_ONE_TERMINAL_FILE).get("terminal_at"),
        label="phase-one terminal time",
    )
    if (
        marker.get("schema_version")
        != "modernization_no_intervention_target_v1"
        or marker.get("freeze_id") != expected_freeze_id
        or marker.get("phase_one_seal_bytes_sha256")
        != protocol.sha256_bytes(phase_one_seal_path.read_bytes())
        or marker.get("disposition_claim_bytes_sha256")
        != protocol.sha256_bytes(disposition_path.read_bytes())
        or marker.get("ready_checkpoint_id")
        != runtime.ready_checkpoint.checkpoint_id
        or marker.get("note_file") != NO_INTERVENTION_NOTE_FILE
        or marker.get("note_record") != note_record
        or marker.get("phase_one_physical_call_count")
        != seal.get("phase_one_physical_call_count")
        or marker.get("phase_one_physical_call_count") != len(call_records)
        or marker.get("phase_one_call_index_bytes_sha256")
        != protocol.sha256_bytes(
            (run_dir / "raw" / "call_index.json").read_bytes()
        )
        or marker.get("artifact_inventory") != actual_inventory
        or marker.get("raw_inventory")
        != _raw_inventory(run_dir, include_call_index=True)
        or marker.get("terminal") != "NO_VALID_INTERVENTION_TARGET"
        or marker.get("phase_two_model_calls") != 0
        or phase_one_terminal_time > disposition_time
        or disposition_time > marker_time
    ):
        raise ValueError("no-target terminal closure is invalid")
    for forbidden in (
        PHASE_TWO_CLAIM_FILE,
        PHASE_TWO_TERMINAL_FILE,
        PHASE_TWO_SEAL_FILE,
        "phase_two_summary.json",
        f"intervention/{INTERVENTION_LOCK_FILE}",
    ):
        if (run_dir / forbidden).exists():
            raise ValueError("no-target terminal conflicts with phase-two artifacts")
    return copy.deepcopy(marker)


def execute_phase_two(
    *,
    repo_root: Path,
    freeze_dir: Path,
    freeze_id: str,
    intervention_dir: Path,
    api_key: str,
    transport: Callable[..., GenerateContentHttpResult] | None = None,
) -> tuple[PlanningPhaseRuntime, list[dict[str, Any]], list[dict[str, Any]]]:
    definition = _load_verified_definition(
        freeze_dir=freeze_dir,
        expected_freeze_id=freeze_id,
        repo_root=repo_root,
    )
    task_text = str(definition["dossier"]["assembled_task_text"])
    run_dir = execution_output_dir(repo_root=repo_root, freeze_id=freeze_id)
    _assert_private_output_root(repo_root=repo_root, output_dir=run_dir)
    if not run_dir.is_dir() or _is_link_or_reparse_point(run_dir):
        raise ValueError("phase-one run directory is unavailable or unsafe")
    for prior_artifact in (
        "phase_two_summary.json",
        "adjusted_planning.private.json",
        "executions.private.json",
        NO_INTERVENTION_TARGET_FILE,
    ):
        if (run_dir / prior_artifact).exists():
            raise FileExistsError("phase two has already started for this freeze run")
    phase_one_seal_path = run_dir / "phase_one_seal.json"
    phase_one_seal, baseline_runtime = _verify_phase_one_archive(
        run_dir=run_dir,
        expected_freeze_id=freeze_id,
        expected_task_text=task_text,
        allow_additional_nonraw_files=True,
        require_intervention_authorized=True,
    )
    _lock, intervention = verify_intervention_package(
        intervention_dir=intervention_dir,
        phase_one_seal_path=phase_one_seal_path,
    )
    _assert_phase_two_entry_closure(run_dir)
    baseline = baseline_runtime.ready_checkpoint
    if baseline is None or baseline.readiness_observation != protocol.READY:
        raise ValueError("phase one has no completed READY checkpoint")
    signatures = _raw_signatures(
        [
            *[
                checkpoint.response_steps
                for checkpoint in baseline_runtime.checkpoints
            ],
            _strict_json_value(run_dir / "baseline_observations.private.json"),
        ]
    )
    _assert_no_raw_signatures(intervention, signatures)
    intervention_lock_sha256 = protocol.sha256_json(_lock)
    claim_path, claim = _claim_phase_two_consumption(
        run_dir=run_dir,
        freeze_id=freeze_id,
        ready_checkpoint_id=baseline.checkpoint_id,
        intervention_lock_sha256=intervention_lock_sha256,
    )
    try:
        store = _store(run_dir=run_dir, api_key=api_key, transport=transport)
        # Continue call numbering if phase two is launched in a new process.
        store.records = _validate_call_index(run_dir)
        first_body = protocol.intervention_body(
            baseline_ready_history=baseline.full_history,
            intervention_text=intervention["intervention.txt"],
        )
        adjusted_runtime = run_planning_phase(
            phase="adjusted",
            first_body=first_body,
            max_turns=protocol.MAX_ADJUSTED_PLANNING_TURNS,
            store=store,
            run_dir=run_dir,
            expected_parent_history=baseline.full_history,
        )
        observations, _seal = run_inspections(
            runtime=adjusted_runtime,
            store=store,
            run_dir=run_dir,
        )
        all_signatures = [
            *signatures,
            *_raw_signatures(
                [
                    checkpoint.response_steps
                    for checkpoint in adjusted_runtime.checkpoints
                ]
            ),
            *_raw_signatures(
                _strict_json_value(run_dir / "adjusted_observations.private.json")
            ),
        ]
        trace_review = _phase_review_markdown(
            runtime=adjusted_runtime, observations=observations
        )
        _assert_no_raw_signatures(trace_review, all_signatures)
        write_text(run_dir / "PHASE_TWO_TRACE_REVIEW.md", trace_review)
        executions: list[dict[str, Any]] = []
        adjusted_ready_observation = None
        if adjusted_runtime.ready_checkpoint is not None:
            adjusted_ready_observation = next(
                (
                    row
                    for row in observations
                    if row.get("checkpoint_id")
                    == adjusted_runtime.ready_checkpoint.checkpoint_id
                ),
                None,
            )
        adjusted_ready_observation_eligible = bool(
            adjusted_ready_observation is not None
            and adjusted_ready_observation.get("eligible_observation") is True
        )
        execution_required = bool(
            adjusted_runtime.ready_checkpoint is not None
            and adjusted_ready_observation_eligible
        )
        if execution_required:
            executions, _execution_seal = run_executions(
                baseline=baseline,
                adjusted=adjusted_runtime.ready_checkpoint,
                store=store,
                run_dir=run_dir,
            )
            all_signatures.extend(
                _raw_signatures(
                    _strict_json_value(run_dir / "executions.private.json")
                )
            )
        expected_execution_rows = protocol.EXECUTION_REPLICATES_PER_CHECKPOINT * 2
        executions_eligible = bool(
            len(executions) == expected_execution_rows
            and all(row.get("eligible") is True for row in executions)
        )
        evidence_chain_complete = bool(
            adjusted_ready_observation_eligible and executions_eligible
        )
        if evidence_chain_complete:
            phase_two_terminal = "COMPLETED_EVIDENCE_CHAIN"
        elif adjusted_runtime.ready_checkpoint is None:
            phase_two_terminal = adjusted_runtime.terminal
        elif not adjusted_ready_observation_eligible:
            phase_two_terminal = "ADJUSTED_PRIMARY_OBSERVATION_INVALID"
        else:
            phase_two_terminal = "EXECUTION_MEASUREMENT_INCOMPLETE"
        phase_two_summary = {
            "schema_version": "modernization_phase_two_summary_v1",
            "freeze_id": freeze_id,
            "intervention_lock_sha256": intervention_lock_sha256,
            "diagnosis_sha256": protocol.sha256_text(intervention["diagnosis.md"]),
            "prediction_sha256": protocol.sha256_text(
                intervention["prediction.md"]
            ),
            "intervention_sha256": protocol.sha256_text(
                intervention["intervention.txt"]
            ),
            "adjusted_terminal": adjusted_runtime.terminal,
            "adjusted_ready_checkpoint_id": (
                adjusted_runtime.ready_checkpoint.checkpoint_id
                if adjusted_runtime.ready_checkpoint
                else None
            ),
            "adjusted_observations": len(observations),
            "adjusted_ready_observation_eligible": (
                adjusted_ready_observation_eligible
            ),
            "execution_rows": len(executions),
            "evidence_chain_complete": evidence_chain_complete,
            "phase_two_terminal": phase_two_terminal,
        }
        _assert_no_raw_signatures(phase_two_summary, all_signatures)
        summary_path = run_dir / "phase_two_summary.json"
        write_json(summary_path, phase_two_summary)

        final_call_records = _validate_call_index(run_dir)
        prefix_count = phase_one_seal["phase_one_physical_call_count"]
        if (
            len(final_call_records) <= prefix_count
            or protocol.sha256_json(final_call_records[:prefix_count])
            != phase_one_seal["phase_one_call_index_prefix_sha256"]
        ):
            raise RuntimeError("phase-two call index lost its phase-one prefix")
        final_artifact_inventory = _assert_nonraw_path_closure(
            run_dir=run_dir,
            expected_paths=_phase_two_seal_inventory_paths(
                execution_required=execution_required
            ),
            label="phase-two pre-seal",
        )
        phase_two_seal = {
            "schema_version": "modernization_phase_two_seal_v1",
            "freeze_id": freeze_id,
            "created_at": utc_now(),
            "phase_one_seal_bytes_sha256": protocol.sha256_bytes(
                phase_one_seal_path.read_bytes()
            ),
            "intervention_lock_bytes_sha256": protocol.sha256_bytes(
                (intervention_dir / INTERVENTION_LOCK_FILE).read_bytes()
            ),
            "phase_two_claim_id": claim["claim_id"],
            "phase_two_claim_bytes_sha256": protocol.sha256_bytes(
                claim_path.read_bytes()
            ),
            "baseline_ready_checkpoint_id": baseline.checkpoint_id,
            "adjusted_ready_checkpoint_id": (
                adjusted_runtime.ready_checkpoint.checkpoint_id
                if adjusted_runtime.ready_checkpoint
                else None
            ),
            "adjusted_ready_observation_eligible": (
                adjusted_ready_observation_eligible
            ),
            "evidence_chain_complete": evidence_chain_complete,
            "phase_two_terminal": phase_two_terminal,
            "artifact_inventory": final_artifact_inventory,
            "final_call_index_sha256": protocol.sha256_json(final_call_records),
            "final_call_index_bytes_sha256": protocol.sha256_bytes(
                (run_dir / "raw" / "call_index.json").read_bytes()
            ),
            "final_physical_call_count": len(final_call_records),
            "raw_inventory": _raw_inventory(
                run_dir, include_call_index=True
            ),
        }
        _assert_no_raw_signatures(phase_two_seal, all_signatures)
        phase_two_seal_path = run_dir / PHASE_TWO_SEAL_FILE
        write_json(phase_two_seal_path, phase_two_seal)
        phase_two_seal_sha256 = protocol.sha256_bytes(
            phase_two_seal_path.read_bytes()
        )
    except BaseException as exc:
        try:
            _terminalize_phase_two_claim(
                path=claim_path,
                claim=claim,
                status="TERMINATED_ERROR",
                error_type=type(exc).__name__,
            )
        except OSError:
            pass
        raise
    _terminalize_phase_two_claim(
        path=claim_path,
        claim=claim,
        status="COMPLETED",
        phase_two_seal_sha256=phase_two_seal_sha256,
    )
    verify_phase_two_archive(
        run_dir=run_dir,
        expected_freeze_id=freeze_id,
        expected_task_text=task_text,
    )
    return adjusted_runtime, observations, executions


def verify_phase_two_archive(
    *, run_dir: Path, expected_freeze_id: str, expected_task_text: str
) -> dict[str, Any]:
    phase_two_seal_path = run_dir / PHASE_TWO_SEAL_FILE
    seal = _strict_json_object(phase_two_seal_path)
    _assert_exact_keys(
        seal, expected=PHASE_TWO_SEAL_KEYS, label="phase-two seal"
    )
    if (
        seal.get("schema_version") != "modernization_phase_two_seal_v1"
        or seal.get("freeze_id") != expected_freeze_id
    ):
        raise ValueError("phase-two seal schema or freeze binding is invalid")
    try:
        phase_two_seal_time = _utc_timestamp(
            seal.get("created_at"), label="phase-two seal time"
        )
    except ValueError as exc:
        raise ValueError("phase-two seal timestamp is invalid") from exc

    phase_one_seal, baseline_runtime = _verify_phase_one_archive(
        run_dir=run_dir,
        expected_freeze_id=expected_freeze_id,
        expected_task_text=expected_task_text,
        allow_extended_call_index=True,
        allow_additional_raw_files=True,
        allow_additional_nonraw_files=True,
        require_intervention_authorized=True,
    )
    phase_one_seal_path = run_dir / "phase_one_seal.json"
    if seal.get("phase_one_seal_bytes_sha256") != protocol.sha256_bytes(
        phase_one_seal_path.read_bytes()
    ):
        raise ValueError("phase-two seal is bound to a different phase-one seal")

    intervention_dir = run_dir / "intervention"
    intervention_lock, intervention = verify_intervention_package(
        intervention_dir=intervention_dir,
        phase_one_seal_path=phase_one_seal_path,
    )
    intervention_lock_path = intervention_dir / INTERVENTION_LOCK_FILE
    if seal.get("intervention_lock_bytes_sha256") != protocol.sha256_bytes(
        intervention_lock_path.read_bytes()
    ):
        raise ValueError("phase-two seal is bound to a different intervention")
    intervention_lock_time = _utc_timestamp(
        intervention_lock.get("created_at"), label="intervention lock time"
    )

    claim = _strict_json_object(run_dir / PHASE_TWO_CLAIM_FILE)
    _assert_exact_keys(
        claim, expected=PHASE_TWO_CLAIM_KEYS, label="phase-two consumption claim"
    )
    terminal = _strict_json_object(run_dir / PHASE_TWO_TERMINAL_FILE)
    _assert_exact_keys(
        terminal,
        expected={
            "schema_version",
            "freeze_id",
            "claim_id",
            "claim_bytes_sha256",
            "status",
            "terminal_at",
            "error_type",
            "phase_two_seal_sha256",
        },
        label="phase-two consumption terminal",
    )
    try:
        claim_time = _utc_timestamp(
            claim.get("claimed_at"), label="phase-two claim time"
        )
        terminal_time = _utc_timestamp(
            terminal.get("terminal_at"), label="phase-two terminal time"
        )
    except ValueError as exc:
        raise ValueError(
            "phase-two consumption claim is not complete or authentic"
        ) from exc
    baseline = baseline_runtime.ready_checkpoint
    if (
        claim.get("schema_version")
        != "modernization_phase_two_consumption_claim_v1"
        or claim.get("freeze_id") != expected_freeze_id
        or not is_opaque_id(claim.get("claim_id"))
        or claim.get("claim_id") != seal.get("phase_two_claim_id")
        or claim.get("ready_checkpoint_id") != baseline.checkpoint_id
        or claim.get("intervention_lock_sha256")
        != protocol.sha256_json(intervention_lock)
        or claim.get("status") != "CLAIMED"
        or seal.get("phase_two_claim_bytes_sha256")
        != protocol.sha256_bytes((run_dir / PHASE_TWO_CLAIM_FILE).read_bytes())
        or terminal.get("schema_version")
        != "modernization_phase_two_consumption_terminal_v1"
        or terminal.get("freeze_id") != expected_freeze_id
        or terminal.get("claim_id") != claim.get("claim_id")
        or terminal.get("claim_bytes_sha256")
        != seal.get("phase_two_claim_bytes_sha256")
        or terminal.get("status") != "COMPLETED"
        or terminal.get("error_type") is not None
        or terminal.get("phase_two_seal_sha256")
        != protocol.sha256_bytes(phase_two_seal_path.read_bytes())
        or intervention_lock_time > claim_time
        or claim_time > terminal_time
    ):
        raise ValueError("phase-two consumption claim is not complete or authentic")

    summary = _strict_json_object(run_dir / "phase_two_summary.json")
    _assert_exact_keys(
        summary, expected=PHASE_TWO_SUMMARY_KEYS, label="phase-two summary"
    )
    if (
        summary.get("schema_version") != "modernization_phase_two_summary_v1"
        or summary.get("freeze_id") != expected_freeze_id
        or summary.get("intervention_lock_sha256")
        != protocol.sha256_json(intervention_lock)
        or summary.get("diagnosis_sha256")
        != protocol.sha256_text(intervention["diagnosis.md"])
        or summary.get("prediction_sha256")
        != protocol.sha256_text(intervention["prediction.md"])
        or summary.get("intervention_sha256")
        != protocol.sha256_text(intervention["intervention.txt"])
    ):
        raise ValueError("phase-two summary is not bound to the sealed intervention")
    artifact_inventory = seal.get("artifact_inventory")
    if not isinstance(artifact_inventory, dict):
        raise ValueError("phase-two non-raw artifact inventory is invalid")
    final_calls = _validate_call_index(run_dir)
    prefix_count = phase_one_seal.get("phase_one_physical_call_count")
    if (
        not isinstance(prefix_count, int)
        or isinstance(prefix_count, bool)
        or len(final_calls) <= prefix_count
    ):
        raise ValueError("phase-two call index has no extension of phase one")
    if (
        seal.get("final_physical_call_count") != len(final_calls)
        or seal.get("final_call_index_sha256")
        != protocol.sha256_json(final_calls)
        or seal.get("final_call_index_bytes_sha256")
        != protocol.sha256_bytes(
            (run_dir / "raw" / "call_index.json").read_bytes()
        )
        or protocol.sha256_json(final_calls[:prefix_count])
        != phase_one_seal.get("phase_one_call_index_prefix_sha256")
        or seal.get("raw_inventory")
        != _raw_inventory(run_dir, include_call_index=True)
        or claim_time
        > _utc_timestamp(
            final_calls[prefix_count].get("started_at"),
            label="first phase-two call time",
        )
        or _utc_timestamp(
            final_calls[-1].get("completed_at"),
            label="last phase-two call time",
        )
        > phase_two_seal_time
        or phase_two_seal_time > terminal_time
    ):
        raise ValueError("phase-two raw call lineage changed after sealing")
    call_cursor = PhysicalCallCursor(
        records=final_calls,
        next_call_number=prefix_count + 1,
        logical_paths_used=_phase_logical_metadata_paths(baseline_runtime),
    )

    adjusted_runtime = _load_private_phase(
        run_dir / "adjusted_planning.private.json"
    )
    if adjusted_runtime.phase != "adjusted":
        raise ValueError("phase-two private planning phase is not adjusted")
    adjusted_summary = _validate_planning_phase_artifacts(
        runtime=adjusted_runtime,
        first_body=protocol.intervention_body(
            baseline_ready_history=baseline.full_history,
            intervention_text=intervention["intervention.txt"],
        ),
        max_turns=protocol.MAX_ADJUSTED_PLANNING_TURNS,
        run_dir=run_dir,
        call_cursor=call_cursor,
    )
    adjusted_runtime.public_summary = copy.deepcopy(adjusted_summary)

    adjusted_ready = adjusted_runtime.ready_checkpoint
    adjusted_observations, _adjusted_observation_seal = (
        _validate_observation_phase_artifacts(
            runtime=adjusted_runtime,
            run_dir=run_dir,
            call_cursor=call_cursor,
        )
    )
    adjusted_observation_seal_time = _utc_timestamp(
        _adjusted_observation_seal.get("created_at"),
        label="adjusted observation seal time",
    )
    trace_review_path = run_dir / "PHASE_TWO_TRACE_REVIEW.md"
    try:
        trace_review_text = trace_review_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError("phase-two trace review is unreadable") from exc
    if trace_review_text != _phase_review_markdown(
        runtime=adjusted_runtime, observations=adjusted_observations
    ):
        raise ValueError("phase-two trace review differs from validated state")
    ready_observation_eligible = False
    if adjusted_ready is not None:
        matching = [
            row
            for row in adjusted_observations
            if isinstance(row, dict)
            and row.get("checkpoint_id") == adjusted_ready.checkpoint_id
        ]
        ready_observation_eligible = bool(
            len(matching) == 1
            and matching[0].get("eligible_observation") is True
            and matching[0].get("reasons") == []
        )
    if (
        seal.get("baseline_ready_checkpoint_id") != baseline.checkpoint_id
        or seal.get("adjusted_ready_checkpoint_id")
        != (adjusted_ready.checkpoint_id if adjusted_ready else None)
        or seal.get("adjusted_ready_observation_eligible")
        is not ready_observation_eligible
    ):
        raise ValueError("phase-two seal conflicts with raw-validated adjusted state")

    execution_files = (
        run_dir / "executions.json",
        run_dir / "executions.private.json",
        run_dir / "execution_seal.json",
    )
    execution_seal: dict[str, Any] | None = None
    execution_required = adjusted_ready is not None and ready_observation_eligible
    if execution_required:
        if not all(path.is_file() for path in execution_files):
            raise ValueError("eligible adjusted READY has no complete execution family")
        if call_cursor.next_call_number > len(final_calls):
            raise ValueError("execution family has no remaining raw calls")
        first_execution_record = final_calls[call_cursor.next_call_number - 1]
        first_execution_time = _utc_timestamp(
            first_execution_record.get("started_at"),
            label="first execution call time",
        )
        if adjusted_observation_seal_time > first_execution_time:
            raise ValueError("execution began before adjusted observations were sealed")
        execution_rows, execution_seal = _validate_execution_artifacts(
            baseline=baseline,
            adjusted=adjusted_ready,
            run_dir=run_dir,
            call_cursor=call_cursor,
        )
        execution_seal_time = _utc_timestamp(
            execution_seal.get("created_at"), label="execution seal time"
        )
        if execution_seal_time > phase_two_seal_time:
            raise ValueError("phase-two seal predates the execution seal")
    else:
        if any(path.exists() for path in execution_files):
            raise ValueError(
                "execution artifacts exist without an eligible adjusted READY"
            )
        execution_rows = []
        if adjusted_observation_seal_time > phase_two_seal_time:
            raise ValueError("phase-two seal predates adjusted observation sealing")
    expected_nonraw_paths = _phase_two_seal_inventory_paths(
        execution_required=execution_required
    )
    actual_nonraw = _assert_nonraw_path_closure(
        run_dir=run_dir,
        expected_paths=expected_nonraw_paths,
        label="phase-two sealed artifact",
        excluded={PHASE_TWO_SEAL_FILE, PHASE_TWO_TERMINAL_FILE},
    )
    _assert_nonraw_path_closure(
        run_dir=run_dir,
        expected_paths=expected_nonraw_paths
        | {PHASE_TWO_SEAL_FILE, PHASE_TWO_TERMINAL_FILE},
        label="phase-two final",
    )
    if artifact_inventory != actual_nonraw:
        raise ValueError("phase-two non-raw run-tree closure changed after sealing")
    _assert_call_cursor_closed(
        run_dir=run_dir,
        call_cursor=call_cursor,
        expected_next_call_number=len(final_calls) + 1,
        require_exact_logical_inventory=True,
    )
    _assert_raw_path_closure(
        run_dir=run_dir,
        records=final_calls,
        logical_paths=call_cursor.logical_paths_used,
        include_call_index=True,
    )
    evidence_chain_complete = bool(
        ready_observation_eligible
        and len(execution_rows)
        == protocol.EXECUTION_REPLICATES_PER_CHECKPOINT * 2
        and all(
            isinstance(row, dict) and row.get("eligible") is True
            for row in execution_rows
        )
    )
    if evidence_chain_complete:
        expected_terminal = "COMPLETED_EVIDENCE_CHAIN"
    elif adjusted_ready is None:
        expected_terminal = str(adjusted_summary.get("terminal"))
    elif not ready_observation_eligible:
        expected_terminal = "ADJUSTED_PRIMARY_OBSERVATION_INVALID"
    else:
        expected_terminal = "EXECUTION_MEASUREMENT_INCOMPLETE"
    expected_summary = {
        "schema_version": "modernization_phase_two_summary_v1",
        "freeze_id": expected_freeze_id,
        "intervention_lock_sha256": protocol.sha256_json(intervention_lock),
        "diagnosis_sha256": protocol.sha256_text(intervention["diagnosis.md"]),
        "prediction_sha256": protocol.sha256_text(intervention["prediction.md"]),
        "intervention_sha256": protocol.sha256_text(intervention["intervention.txt"]),
        "adjusted_terminal": adjusted_summary.get("terminal"),
        "adjusted_ready_checkpoint_id": (
            adjusted_ready.checkpoint_id if adjusted_ready else None
        ),
        "adjusted_observations": len(adjusted_observations),
        "adjusted_ready_observation_eligible": ready_observation_eligible,
        "execution_rows": len(execution_rows),
        "evidence_chain_complete": evidence_chain_complete,
        "phase_two_terminal": expected_terminal,
    }
    if (
        summary != expected_summary
        or seal.get("phase_two_terminal") != expected_terminal
        or seal.get("evidence_chain_complete") is not evidence_chain_complete
    ):
        raise ValueError("phase-two execution evidence conflicts with its seal")
    signature_sources: list[Any] = [
        *[checkpoint.response_steps for checkpoint in baseline_runtime.checkpoints],
        *[checkpoint.response_steps for checkpoint in adjusted_runtime.checkpoints],
        _strict_json_value(run_dir / "baseline_observations.private.json"),
        _strict_json_value(run_dir / "adjusted_observations.private.json"),
    ]
    if execution_rows:
        signature_sources.append(
            _strict_json_value(run_dir / "executions.private.json")
        )
    _assert_no_raw_signatures(
        [
            summary,
            adjusted_summary,
            adjusted_observations,
            _adjusted_observation_seal,
            trace_review_text,
            execution_rows,
            execution_seal,
            intervention,
            seal,
        ],
        _raw_signatures(signature_sources),
    )
    return copy.deepcopy(seal)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    phase_one = subparsers.add_parser("phase-one")
    phase_one.add_argument("--freeze-dir", type=Path, required=True)
    phase_one.add_argument("--freeze-id", required=True)
    verify_phase_one = subparsers.add_parser("verify-phase-one")
    verify_phase_one.add_argument("--run-dir", type=Path, required=True)
    verify_phase_one.add_argument("--freeze-dir", type=Path, required=True)
    verify_phase_one.add_argument("--freeze-id", required=True)
    seal = subparsers.add_parser("seal-intervention")
    seal.add_argument("--intervention-dir", type=Path, required=True)
    seal.add_argument("--phase-one-seal", type=Path, required=True)
    seal.add_argument("--freeze-dir", type=Path, required=True)
    seal.add_argument("--freeze-id", required=True)
    no_target = subparsers.add_parser("close-no-target")
    no_target.add_argument("--phase-one-seal", type=Path, required=True)
    no_target.add_argument("--note", type=Path, required=True)
    no_target.add_argument("--freeze-dir", type=Path, required=True)
    no_target.add_argument("--freeze-id", required=True)
    verify_no_target = subparsers.add_parser("verify-no-target")
    verify_no_target.add_argument("--phase-one-seal", type=Path, required=True)
    verify_no_target.add_argument("--freeze-dir", type=Path, required=True)
    verify_no_target.add_argument("--freeze-id", required=True)
    phase_two = subparsers.add_parser("phase-two")
    phase_two.add_argument("--freeze-dir", type=Path, required=True)
    phase_two.add_argument("--freeze-id", required=True)
    phase_two.add_argument("--intervention-dir", type=Path, required=True)
    verify_phase_two = subparsers.add_parser("verify-phase-two")
    verify_phase_two.add_argument("--run-dir", type=Path, required=True)
    verify_phase_two.add_argument("--freeze-dir", type=Path, required=True)
    verify_phase_two.add_argument("--freeze-id", required=True)
    return parser


def _print_file_byte_digest(path: Path) -> None:
    print("sha256_bytes=" + protocol.sha256_bytes(path.read_bytes()))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    if args.command == "seal-intervention":
        definition = _load_verified_definition(
            freeze_dir=args.freeze_dir,
            expected_freeze_id=args.freeze_id,
            repo_root=repo_root,
        )
        seal_intervention_package(
            intervention_dir=args.intervention_dir,
            phase_one_seal_path=args.phase_one_seal,
            expected_freeze_id=args.freeze_id,
            expected_task_text=str(definition["dossier"]["assembled_task_text"]),
            expected_run_dir=execution_output_dir(
                repo_root=repo_root, freeze_id=args.freeze_id
            ),
        )
        _print_file_byte_digest(
            args.intervention_dir / INTERVENTION_LOCK_FILE
        )
        return 0
    if args.command == "close-no-target":
        definition = _load_verified_definition(
            freeze_dir=args.freeze_dir,
            expected_freeze_id=args.freeze_id,
            repo_root=repo_root,
        )
        record_no_valid_intervention_target(
            phase_one_seal_path=args.phase_one_seal,
            note_path=args.note,
            expected_freeze_id=args.freeze_id,
            expected_task_text=str(definition["dossier"]["assembled_task_text"]),
            expected_run_dir=execution_output_dir(
                repo_root=repo_root, freeze_id=args.freeze_id
            ),
        )
        _print_file_byte_digest(
            args.phase_one_seal.parent / NO_INTERVENTION_TARGET_FILE
        )
        return 0
    if args.command == "verify-no-target":
        definition = _load_verified_definition(
            freeze_dir=args.freeze_dir,
            expected_freeze_id=args.freeze_id,
            repo_root=repo_root,
        )
        verify_no_valid_intervention_target(
            phase_one_seal_path=args.phase_one_seal,
            expected_freeze_id=args.freeze_id,
            expected_task_text=str(definition["dossier"]["assembled_task_text"]),
        )
        _print_file_byte_digest(
            args.phase_one_seal.parent / NO_INTERVENTION_TARGET_FILE
        )
        return 0
    if args.command == "verify-phase-one":
        definition = _load_verified_definition(
            freeze_dir=args.freeze_dir,
            expected_freeze_id=args.freeze_id,
            repo_root=repo_root,
        )
        seal, _runtime = _verify_phase_one_archive(
            run_dir=args.run_dir,
            expected_freeze_id=args.freeze_id,
            expected_task_text=str(definition["dossier"]["assembled_task_text"]),
        )
        _print_file_byte_digest(args.run_dir / "phase_one_seal.json")
        return 0
    if args.command == "verify-phase-two":
        definition = _load_verified_definition(
            freeze_dir=args.freeze_dir,
            expected_freeze_id=args.freeze_id,
            repo_root=repo_root,
        )
        seal = verify_phase_two_archive(
            run_dir=args.run_dir,
            expected_freeze_id=args.freeze_id,
            expected_task_text=str(
                definition["dossier"]["assembled_task_text"]
            ),
        )
        _print_file_byte_digest(args.run_dir / PHASE_TWO_SEAL_FILE)
        return 0
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required for model execution")
    if args.command == "phase-one":
        run_dir, runtime, _observations = execute_phase_one(
            repo_root=repo_root,
            freeze_dir=args.freeze_dir,
            freeze_id=args.freeze_id,
            api_key=api_key,
        )
        print(f"{runtime.terminal}: {run_dir}")
        return 0
    adjusted, _observations, executions = execute_phase_two(
        repo_root=repo_root,
        freeze_dir=args.freeze_dir,
        freeze_id=args.freeze_id,
        intervention_dir=args.intervention_dir,
        api_key=api_key,
    )
    print(f"{adjusted.terminal}; execution rows: {len(executions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
