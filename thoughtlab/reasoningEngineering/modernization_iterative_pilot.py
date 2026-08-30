#!/usr/bin/env python3
"""Run and reverse-verify the staged C0/I1/C1/I2/C2/I3/C3 experiment.

This module is the sole network-capable member of the iterative experiment.
Native Gemini ``Content`` is replayed byte-semantically through protocol request
builders, while tomography is detached and never admitted to live history.
Every consuming command is single-use and terminalizes its claim.
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
from typing import Any, Callable, Mapping

from thoughtlab.gemini_generate_content import (
    GenerateContentHttpResult,
    canonical_json_bytes,
    decode_generate_content_bytes,
    generate_content_url,
    post_generate_content,
    response_contents,
    thought_signature_metadata,
)
from thoughtlab.opaque_ids import generate_opaque_id, is_opaque_id
from thoughtlab.raw_call_store import (
    RawCallStore,
    bounded_storage_label,
    write_json,
    write_text,
)
from thoughtlab.reasoningEngineering import (
    modernization_iterative_protocol as protocol,
)


SCHEMA_VERSION = "modernization_iterative_execution_v1"
RESULTS_PARENT = Path("results/reasoning_engineering_iterative")
INTER_REQUEST_DELAY_SECONDS = 1.0

ACTION_FREEZE_READY = "FREEZE_READY"
ACTION_CONTINUE = "CONTINUE"
ACTION_TERMINATE_TECHNICAL = "TERMINATE_TECHNICAL"

ROUND_TERMINALS = {
    "READY_CHECKPOINT_OBSERVED",
    protocol.PLANNING_THRESHOLD_REACHED,
    "PLANNING_TERMINATED_TECHNICAL",
    "OBSERVATION_MEASUREMENT_INCOMPLETE",
}
OBSERVED = "OBSERVED"
INCOMPLETE = "INCOMPLETE"

CALL_INDEX_KEYS = {
    "call_number", "label", "started_at", "completed_at", "attempt_state",
    "http_status", "elapsed_ms", "request_wire_sha256", "request_wire_bytes",
    "response_wire_sha256", "response_wire_bytes", "response_decoded_chars",
    "transport_error", "response_parse_error", "response_headers",
    "raw_request_path", "raw_response_path", "request_target",
}
LOGICAL_KEYS = {
    "logical_request_id", "logical_label", "started_at", "completed_at",
    "attempt_count", "selected_attempt", "selected_physical_call_number",
    "selected_response_wire_sha256", "selection_reason", "retried",
    "retry_rule", "planned_backoff_seconds", "actual_backoff_seconds",
    "request_wire_sha256", "request_wire_bytes", "first_attempt_http_status",
    "first_attempt_transport_error", "request_target", "attempts",
}
LOGICAL_ATTEMPT_KEYS = CALL_INDEX_KEYS | {
    "attempt_index", "previous_physical_call_number", "retryable_reason",
    "selected_for_logical_result",
}
RETRY_RULE = "transport_or_http_408_429_500_502_503_504_only"

CHECKPOINT_FILES = (
    "claim.json", "planning.private.json", "planning_attempts.json",
    "planning_summary.json", "observations.private.json", "observations.json",
    "observation_seal.json", "review.md", "raw_prefix.json",
    "stage_seal.json", "terminal.json",
)
INTERVENTION_COMMON_FILES = (
    "examiner_packet.md", "participants.json", "examiner_review.md",
    "researcher_review.md", "reconciliation.md",
)
INTERVENTION_SEALED_FILES = (
    "disposition_claim.json", "disposition.json", "intervention.json",
    "semantic_adjudication.json", "review_provenance.json", "lock.json",
    "disposition_terminal.json",
)
INTERVENTION_NO_TARGET_FILES = (
    "disposition_claim.json", "disposition.json", "no_target_record.json",
    "semantic_adjudication.json", "review_provenance.json",
    "no_target_note.md", "disposition_terminal.json",
)
EXECUTION_FILES = (
    "execution_claim.json", "executions.private.json", "executions.json",
    "execution_raw_prefix.json", "trajectory_seal.json",
    "execution_terminal.json",
)
O3_ASSESSMENT_PRESEAL_FILES = (
    "o3_assessment_packet.md", "o3_assessment.md",
)
O3_ASSESSMENT_SEALED_FILES = (
    "o3_assessment_claim.json", "o3_assessment.json",
    "o3_assessment.lock.json", "o3_assessment_terminal.json",
)


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
    checkpoint: str
    turn_number: int
    readiness_observation: str
    provider_status: str
    full_history: list[dict[str, Any]]
    response_steps: list[dict[str, Any]]
    summary: dict[str, Any]


@dataclass
class RoundRuntime:
    checkpoint: str
    checkpoints: list[CheckpointRuntime]
    ready_checkpoint: CheckpointRuntime | None
    terminal: str
    last_turn_classification: str | None
    public_summary: dict[str, Any]


@dataclass
class CallCursor:
    records: list[dict[str, Any]]
    next_call_number: int = 1
    logical_paths_used: set[str] | None = None

    def __post_init__(self) -> None:
        if self.logical_paths_used is None:
            self.logical_paths_used = set()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{label} is not a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{label} is not a UTC timestamp") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"{label} is not a UTC timestamp")
    return parsed


def _sha_bytes(value: bytes) -> str:
    return protocol.base.sha256_bytes(value)


def _sha_text(value: str) -> str:
    return protocol.base.sha256_text(value)


def _sha_json(value: Any) -> str:
    return protocol.base.sha256_json(value)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, indent=2).encode("utf-8")


def _exclusive_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _exclusive_json(path: Path, value: Any) -> None:
    _exclusive_bytes(path, _json_bytes(value))


def _exclusive_text(path: Path, value: str) -> None:
    _exclusive_bytes(path, value.encode("utf-8"))


def _strict_value(path: Path) -> Any:
    from thoughtlab.reasoningEngineering import modernization_iterative_freeze

    if not path.is_file() or _is_link(path):
        raise ValueError(f"required artifact is not a safe regular file: {path}")
    try:
        return modernization_iterative_freeze.strict_json_loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise ValueError(f"invalid strict JSON artifact: {path.name}") from exc


def _strict_object(path: Path) -> dict[str, Any]:
    value = _strict_value(path)
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact is not an object: {path.name}")
    return value


def _strict_list(path: Path) -> list[Any]:
    value = _strict_value(path)
    if not isinstance(value, list):
        raise ValueError(f"JSON artifact is not a list: {path.name}")
    return value


def _is_link(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0) & flag
    )


def _assert_no_link_ancestor(*, root: Path, path: Path) -> None:
    root = root.absolute()
    target = path.absolute()
    if not target.is_relative_to(root):
        raise ValueError("path escapes its trusted root")
    cursor = root
    if _is_link(cursor):
        raise ValueError("trusted root is a link or reparse point")
    for part in target.relative_to(root).parts:
        cursor = cursor / part
        if cursor.exists() and _is_link(cursor):
            raise ValueError(f"path contains a link or reparse point: {cursor}")


def _minimal_git_environment() -> dict[str, str]:
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP"}
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def execution_output_dir(*, repo_root: Path, freeze_id: str) -> Path:
    if not _is_sha256(freeze_id):
        raise ValueError("freeze ID is malformed")
    return repo_root.resolve() / RESULTS_PARENT / freeze_id


def _assert_private_root(*, repo_root: Path, run_dir: Path) -> None:
    root = repo_root.resolve()
    expected = root / RESULTS_PARENT
    if run_dir.parent != expected:
        raise ValueError("run directory is outside the iterative private results tree")
    _assert_no_link_ancestor(root=root, path=run_dir)
    relative = run_dir.relative_to(root)
    completed = subprocess.run(
        ["git", "check-ignore", "-q", "--", str(relative)], cwd=root,
        check=False, capture_output=True, env=_minimal_git_environment(),
    )
    if completed.returncode != 0:
        raise ValueError("private run directory is not Git-ignored")


def _assert_run_tree_has_no_links(run_dir: Path) -> None:
    if not run_dir.is_dir() or _is_link(run_dir):
        raise ValueError("run archive is unavailable or link-backed")
    for path in run_dir.rglob("*"):
        if _is_link(path):
            raise ValueError(f"run archive contains a link or reparse point: {path}")


def _request_target() -> dict[str, str]:
    return {
        "api": protocol.API,
        "method": "POST",
        "endpoint": generate_content_url(model=protocol.MODEL),
        "model": protocol.MODEL,
    }


def _file_record(path: Path) -> dict[str, Any]:
    if not path.is_file() or _is_link(path):
        raise ValueError(f"artifact is not a safe regular file: {path}")
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": _sha_bytes(data)}


def _artifact_inventory(run_dir: Path, paths: list[str] | tuple[str, ...]) -> dict[str, Any]:
    inventory: dict[str, Any] = {}
    for relative in paths:
        fragment = Path(relative)
        if fragment.is_absolute() or ".." in fragment.parts:
            raise ValueError("unsafe artifact inventory path")
        inventory[fragment.as_posix()] = _file_record(run_dir / fragment)
    return inventory


def _verify_inventory(run_dir: Path, inventory: Any) -> None:
    if not isinstance(inventory, dict) or not inventory:
        raise ValueError("sealed artifact inventory is invalid")
    if _artifact_inventory(run_dir, list(inventory)) != inventory:
        raise ValueError("sealed artifact inventory changed")


def _raw_inventory(run_dir: Path, *, include_index: bool = False) -> dict[str, Any]:
    raw = run_dir / "raw"
    if not raw.is_dir() or _is_link(raw):
        raise ValueError("raw archive is unavailable or unsafe")
    result: dict[str, Any] = {}
    for path in sorted(raw.rglob("*"), key=lambda item: item.as_posix()):
        if _is_link(path) or not path.is_file():
            raise ValueError("raw archive contains a link, directory, or non-file")
        relative = path.relative_to(run_dir).as_posix()
        if relative == "raw/call_index.json" and not include_index:
            continue
        result[relative] = _file_record(path)
    return result


def _raw_signatures(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower().replace("_", "") in {"signature", "thoughtsignature"} and isinstance(item, str) and item:
                found.append(item)
            found.extend(_raw_signatures(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_raw_signatures(item))
    return list(dict.fromkeys(found))


def _assert_no_raw_signatures(value: Any, signatures: list[str]) -> None:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True)
    if any(signature and signature in encoded for signature in signatures):
        raise RuntimeError("a raw thought signature entered a shareable artifact")


def _safe_usage(payload: dict[str, Any] | None) -> dict[str, int | None]:
    source = payload.get("usageMetadata") if isinstance(payload, dict) else None
    source = source if isinstance(source, dict) else {}
    keys = {
        "total_tokens": "totalTokenCount", "total_input_tokens": "promptTokenCount",
        "total_cached_tokens": "cachedContentTokenCount",
        "total_output_tokens": "candidatesTokenCount",
        "total_thought_tokens": "thoughtsTokenCount",
        "total_tool_use_tokens": "toolUsePromptTokenCount",
    }
    return {
        target: value if type((value := source.get(provider))) is int else None
        for target, provider in keys.items()
    }


def _finish_reasons(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1 or not isinstance(candidates[0], dict):
        return []
    value = candidates[0].get("finishReason")
    return [value] if isinstance(value, str) and value else []


def _normalized_finish(value: str) -> str:
    return value.strip().upper().replace("-", "_").replace(" ", "_")


def _visible_text(steps: list[dict[str, Any]], *, readiness: bool) -> tuple[str, list[str]]:
    issues: list[str] = []
    pieces: list[str] = []
    if len(steps) != 1:
        issues.append("response did not contain exactly one model Content")
    for index, content in enumerate(steps):
        try:
            protocol.base._validate_model_content(content, index)
        except (TypeError, ValueError) as exc:
            issues.append(str(exc))
            continue
        parts = [
            part for part in content["parts"]
            if part.get("thought") is not True and isinstance(part.get("text"), str)
        ]
        if readiness and len(parts) != 1:
            issues.append("model Content did not contain exactly one visible text Part")
        if not readiness and not parts:
            issues.append("model Content contained no visible text Part")
        pieces.extend(str(part["text"]) for part in parts)
    return "".join(pieces), issues


def _carrier_errors(steps: list[dict[str, Any]]) -> list[str]:
    if not steps:
        return ["response has no replayable Content"]
    try:
        protocol.isolate_checkpoint_carrier(steps)
    except (RuntimeError, TypeError, ValueError) as exc:
        return [f"response carrier was not safely isolatable: {exc}"]
    return []


def evaluate_planning_turn(result: GenerateContentHttpResult) -> PlanningTurnEvaluation:
    reasons: list[str] = []
    usable = (
        result.http_status is not None and 200 <= result.http_status < 300
        and not result.transport_error and not result.response_parse_error
        and isinstance(result.payload, dict)
        and result.payload.get("modelVersion") == protocol.MODEL
        and "error" not in result.payload and "errors" not in result.payload
    )
    if not usable:
        reasons.append("transport or provider envelope was not usable")
    steps: list[dict[str, Any]] = []
    if isinstance(result.payload, dict):
        try:
            steps = response_contents(result.payload)
        except ValueError as exc:
            reasons.append(f"response Content shape was invalid: {exc}")
    visible, visible_issues = _visible_text(steps, readiness=True)
    carrier_issues = _carrier_errors(steps)
    reasons.extend(visible_issues)
    reasons.extend(carrier_issues)
    finish = _finish_reasons(result.payload)
    normalized_finish = {_normalized_finish(item) for item in finish}
    if normalized_finish == set(protocol.COMPLETED_FINISH_REASONS):
        provider_status = "completed"
    elif normalized_finish and normalized_finish.issubset(set(protocol.OUTPUT_BUDGET_FINISH_REASONS)):
        provider_status = "incomplete"
    else:
        provider_status = ""
        reasons.append("missing or unsupported generateContent finishReason")
    normalized_text = protocol.base.normalize_readiness_text(visible)
    if provider_status == "incomplete":
        readiness = protocol.UNOBSERVED_TRUNCATED
    elif provider_status == "completed" and not visible_issues and normalized_text == protocol.READY:
        readiness = protocol.READY
    elif provider_status == "completed" and not visible_issues and normalized_text == protocol.NOT_READY:
        readiness = protocol.SELF_DECLARED_NOT_READY
    elif provider_status == "completed":
        readiness = protocol.INVALID_STATUS
    else:
        readiness = None
    replayable = usable and not carrier_issues
    if not replayable or readiness is None:
        action = ACTION_TERMINATE_TECHNICAL
    elif readiness == protocol.READY:
        action = ACTION_FREEZE_READY
    else:
        action = ACTION_CONTINUE
    safe = {
        "http_status": result.http_status,
        "provider_status": provider_status,
        "explicit_finish_reasons": finish,
        "transport_error_present": bool(result.transport_error),
        "response_parse_error_present": bool(result.response_parse_error),
        "response_content_count": len(steps),
        "response_part_count": sum(len(item.get("parts", [])) for item in steps),
        "signature_metadata": thought_signature_metadata(steps),
        "visible_text_sha256": _sha_text(visible),
        "visible_text_chars": len(visible),
        "usage": _safe_usage(result.payload),
    }
    return PlanningTurnEvaluation(
        provider_status, finish, readiness, action, replayable,
        list(dict.fromkeys(reasons)), copy.deepcopy(steps), visible,
        normalized_text, safe,
    )


def _evaluate_prose_result(result: GenerateContentHttpResult) -> dict[str, Any]:
    reasons: list[str] = []
    usable = (
        result.http_status is not None and 200 <= result.http_status < 300
        and not result.transport_error and not result.response_parse_error
        and isinstance(result.payload, dict)
        and result.payload.get("modelVersion") == protocol.MODEL
        and "error" not in result.payload and "errors" not in result.payload
    )
    if not usable:
        reasons.append("transport or provider envelope was not usable")
    steps: list[dict[str, Any]] = []
    if isinstance(result.payload, dict):
        try:
            steps = response_contents(result.payload)
        except ValueError as exc:
            reasons.append(f"response Content shape was invalid: {exc}")
    text, shape = _visible_text(steps, readiness=False)
    reasons.extend(shape)
    finish = _finish_reasons(result.payload)
    completed = {_normalized_finish(item) for item in finish} == set(protocol.COMPLETED_FINISH_REASONS)
    if not completed:
        reasons.append("response did not finish with the frozen completed reason")
    status = OBSERVED if usable and not shape and completed and bool(text.strip()) else INCOMPLETE
    return {
        "status": status,
        "text": text,
        "steps": copy.deepcopy(steps),
        "reasons": list(dict.fromkeys(reasons)),
        "safe_metadata": {
            "http_status": result.http_status,
            "explicit_finish_reasons": finish,
            "provider_status": "completed" if completed else "incomplete",
            "transport_error_present": bool(result.transport_error),
            "response_parse_error_present": bool(result.response_parse_error),
            "response_content_count": len(steps),
            "response_part_count": sum(len(item.get("parts", [])) for item in steps),
            "text_sha256": _sha_text(text), "text_chars": len(text),
            "usage": _safe_usage(result.payload),
        },
    }


def _safe_call(call: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "logical_request_id", "attempt_count", "selected_physical_call_number",
        "selected_response_wire_sha256", "selection_reason", "request_wire_sha256",
    )
    return {key: call.get(key) for key in keys}


def _invoke(store: RawCallStore, *, label: str, body: dict[str, Any]) -> tuple[GenerateContentHttpResult, dict[str, Any]]:
    protocol.base.assert_no_function_tool_or_schema_structure(body)
    result, call = store.invoke_logical(label=label, body=body)
    if not isinstance(result, GenerateContentHttpResult):
        # Test doubles may satisfy the same dataclass contract by construction.
        required = ("http_status", "payload", "raw_body", "transport_error", "response_parse_error", "elapsed_ms")
        if any(not hasattr(result, key) for key in required):
            raise TypeError("transport returned an incompatible result")
    return result, _safe_call(call)


def _make_store(
    *, run_dir: Path, api_key: str,
    transport: Callable[..., GenerateContentHttpResult] | None = None,
) -> RawCallStore:
    selected = transport or functools.partial(post_generate_content, model=protocol.MODEL)
    store = RawCallStore(
        run_dir=run_dir, api_key=api_key,
        timeout=protocol.base.HTTP_TIMEOUT_SECONDS,
        delay_seconds=INTER_REQUEST_DELAY_SECONDS if transport is None else 0,
        transport=selected,
        max_attempts=protocol.base.MAX_ATTEMPTS_PER_LOGICAL_REQUEST,
        retry_backoff_seconds=protocol.base.RETRY_BACKOFF_SECONDS,
        request_target=_request_target(),
    )
    index = run_dir / "raw/call_index.json"
    if index.exists():
        store.records = _validate_call_index(run_dir)
    return store


def _load_definition(*, repo_root: Path, freeze_dir: Path, freeze_id: str) -> dict[str, Any]:
    from thoughtlab.reasoningEngineering import modernization_iterative_freeze

    verification = modernization_iterative_freeze.verify_freeze(
        freeze_dir=freeze_dir, repo_root=repo_root,
        expected_freeze_id=freeze_id,
    )
    if not verification.get("valid"):
        raise ValueError("freeze verification failed: " + "; ".join(map(str, verification.get("errors", []))))
    value = modernization_iterative_freeze.strict_json_loads(
        (freeze_dir / modernization_iterative_freeze.DEFINITION_NAME).read_text(encoding="utf-8")
    )
    if not isinstance(value, dict):
        raise ValueError("frozen experiment definition is not an object")
    if value.get("model") != protocol.MODEL or value.get("api") != protocol.API:
        raise ValueError("frozen transport identity differs")
    return value


def _claim(path: Path, *, schema: str, freeze_id: str, kind: str, bindings: Mapping[str, Any] | None = None) -> dict[str, Any]:
    value = {
        "schema_version": schema, "freeze_id": freeze_id,
        "claim_id": generate_opaque_id(), "kind": kind,
        "claimed_at": utc_now(), "status": "CLAIMED",
        "bindings": copy.deepcopy(dict(bindings or {})),
    }
    _exclusive_json(path, value)
    return value


def _terminal(
    path: Path, *, schema: str, claim_path: Path, claim: Mapping[str, Any],
    status: str, sealed_path: Path | None = None, error_type: str | None = None,
) -> dict[str, Any]:
    value = {
        "schema_version": schema, "freeze_id": claim["freeze_id"],
        "claim_id": claim["claim_id"],
        "claim_bytes_sha256": _sha_bytes(claim_path.read_bytes()),
        "status": status, "terminal_at": utc_now(), "error_type": error_type,
        "sealed_path": sealed_path.relative_to(
            path.parent.parent
            if path.parent.name in {"i1", "i2", "i3"}
            else path.parent
        ).as_posix() if sealed_path else None,
        "sealed_bytes_sha256": _sha_bytes(sealed_path.read_bytes()) if sealed_path else None,
    }
    _exclusive_json(path, value)
    return value


def _checkpoint_private(item: CheckpointRuntime) -> dict[str, Any]:
    return {
        "checkpoint_id": item.checkpoint_id, "checkpoint": item.checkpoint,
        "turn_number": item.turn_number,
        "readiness_observation": item.readiness_observation,
        "provider_status": item.provider_status,
        "full_history": copy.deepcopy(item.full_history),
        "response_steps": copy.deepcopy(item.response_steps),
        "summary": copy.deepcopy(item.summary),
    }


def run_checkpoint_round(
    *, checkpoint: str, first_body: dict[str, Any], store: RawCallStore,
    run_dir: Path, expected_parent_history: list[dict[str, Any]] | None,
) -> tuple[RoundRuntime, list[dict[str, Any]], list[dict[str, Any]]]:
    if checkpoint not in protocol.CHECKPOINTS:
        raise ValueError("invalid checkpoint")
    if expected_parent_history is None:
        history: list[dict[str, Any]] = []
    else:
        history = copy.deepcopy(expected_parent_history)
        if first_body.get("contents", [])[:-1] != expected_parent_history:
            raise ValueError("intervention request changed exact parent history")
    checkpoints: list[CheckpointRuntime] = []
    ready: CheckpointRuntime | None = None
    attempts: list[dict[str, Any]] = []
    terminal = ""
    last: str | None = None
    for turn in range(1, protocol.MAX_PLANNING_TURNS_PER_CHECKPOINT + 1):
        if turn == 1:
            body = copy.deepcopy(first_body)
        else:
            body = protocol.planning_continuation_body(
                full_history=history, checkpoint=checkpoint, turn_number=turn,
            )
            if body["contents"][:-1] != history:
                raise RuntimeError("continuation changed exact prior history")
        result, call = _invoke(store, label=f"{checkpoint.lower()}_planning_turn_{turn}", body=body)
        evaluated = evaluate_planning_turn(result)
        last = evaluated.readiness_observation
        summary = {
            "turn_number": turn, "provider_status": evaluated.provider_status,
            "explicit_finish_reasons": evaluated.explicit_finish_reasons,
            "readiness_observation": evaluated.readiness_observation,
            "controller_action": evaluated.controller_action,
            "carrier_replayable": evaluated.carrier_replayable,
            "reasons": evaluated.reasons, "safe_metadata": evaluated.safe_metadata,
            "call": call, "request_contents_sha256": _sha_json(body["contents"]),
        }
        attempts.append(copy.deepcopy(summary))
        if evaluated.controller_action == ACTION_TERMINATE_TECHNICAL:
            terminal = "PLANNING_TERMINATED_TECHNICAL"
            break
        history = [*copy.deepcopy(body["contents"]), *copy.deepcopy(evaluated.steps)]
        opaque = generate_opaque_id()
        item = CheckpointRuntime(
            opaque, checkpoint, turn, str(evaluated.readiness_observation),
            evaluated.provider_status, copy.deepcopy(history),
            copy.deepcopy(evaluated.steps), copy.deepcopy(summary),
        )
        checkpoints.append(item)
        if evaluated.controller_action == ACTION_FREEZE_READY:
            ready = item
            terminal = "READY_CHECKPOINT_OBSERVED"
            break
    if not terminal:
        terminal = protocol.PLANNING_THRESHOLD_REACHED
    public_summary = {
        "schema_version": "modernization_iterative_planning_summary_v1",
        "checkpoint": checkpoint, "terminal": terminal,
        "last_turn_classification": last,
        "turns_attempted": len(attempts),
        "checkpoint_count": len(checkpoints),
        "ready_checkpoint_id": ready.checkpoint_id if ready else None,
        "checkpoint_rows": [
            {
                "checkpoint_id": item.checkpoint_id,
                "turn_number": item.turn_number,
                "readiness_observation": item.readiness_observation,
                "provider_status": item.provider_status,
                "full_history_sha256": _sha_json(item.full_history),
                "response_steps_sha256": _sha_json(item.response_steps),
            }
            for item in checkpoints
        ],
    }
    runtime = RoundRuntime(checkpoint, checkpoints, ready, terminal, last, public_summary)
    prefix = checkpoint.lower()
    _exclusive_json(run_dir / f"{prefix}_planning.private.json", {
        "schema_version": "modernization_iterative_planning_private_v1",
        "checkpoint": checkpoint, "terminal": terminal,
        "last_turn_classification": last,
        "ready_checkpoint_id": ready.checkpoint_id if ready else None,
        "checkpoints": [_checkpoint_private(item) for item in checkpoints],
    })
    _exclusive_json(run_dir / f"{prefix}_planning_attempts.json", attempts)
    _exclusive_json(run_dir / f"{prefix}_planning_summary.json", public_summary)

    private_observations: list[dict[str, Any]] = []
    public_observations: list[dict[str, Any]] = []
    for item in checkpoints:
        body = protocol.inspection_body(response_steps=item.response_steps, checkpoint=checkpoint)
        # The detached inspection request must contain only the isolated response
        # carrier and inspection query; no planning-history or prior O output.
        if body["contents"][:-1] != protocol.isolate_checkpoint_carrier(item.response_steps):
            raise RuntimeError("inspection topology differs from the frozen isolation operator")
        label = f"{checkpoint.lower()}_inspection_turn_{item.turn_number}_{item.checkpoint_id}"
        result, call = _invoke(store, label=label, body=body)
        measured = _evaluate_prose_result(result)
        private_row = {
            "checkpoint_id": item.checkpoint_id, "turn_number": item.turn_number,
            "readiness_observation": item.readiness_observation,
            "status": measured["status"], "text": measured["text"],
            "steps": measured["steps"], "reasons": measured["reasons"],
            "safe_metadata": measured["safe_metadata"], "call": call,
            "request_contents_sha256": _sha_json(body["contents"]),
        }
        public_row = {key: value for key, value in private_row.items() if key != "steps"}
        private_observations.append(private_row)
        public_observations.append(public_row)
    _exclusive_json(run_dir / f"{prefix}_observations.private.json", {
        "schema_version": "modernization_iterative_observations_private_v1",
        "checkpoint": checkpoint, "rows": private_observations,
    })
    public_bundle = {
        "schema_version": "modernization_iterative_observations_v1",
        "checkpoint": checkpoint,
        "observation": protocol.CHECKPOINT_TO_OBSERVATION[checkpoint],
        "rows": public_observations,
    }
    all_signatures = _raw_signatures([_checkpoint_private(item) for item in checkpoints]) + _raw_signatures(private_observations)
    _assert_no_raw_signatures(public_summary, all_signatures)
    _assert_no_raw_signatures(public_bundle, all_signatures)
    _exclusive_json(run_dir / f"{prefix}_observations.json", public_bundle)
    primary = next(
        (row for row in public_observations if ready and row["checkpoint_id"] == ready.checkpoint_id),
        None,
    )
    eligible = bool(primary and primary["status"] == OBSERVED)
    observation_seal = {
        "schema_version": "modernization_iterative_observation_seal_v1",
        "checkpoint": checkpoint,
        "observation": protocol.CHECKPOINT_TO_OBSERVATION[checkpoint],
        "ready_checkpoint_id": ready.checkpoint_id if ready else None,
        "eligible": eligible,
        "primary_observation_sha256": _sha_json(primary) if primary else None,
        "observations_bytes_sha256": _sha_bytes((run_dir / f"{prefix}_observations.json").read_bytes()),
        "sealed_at": utc_now(),
    }
    _exclusive_json(run_dir / f"{prefix}_observation_seal.json", observation_seal)
    if ready and not eligible:
        runtime.terminal = "OBSERVATION_MEASUREMENT_INCOMPLETE"
        runtime.public_summary["terminal"] = runtime.terminal
        # Persisted planning summary remains a planning-only observation. The
        # stage terminal and stage seal carry the combined round disposition.
    review = _review_text(runtime, public_observations, observation_seal)
    _exclusive_text(run_dir / f"{prefix}_review.md", review)
    return runtime, private_observations, public_observations


def _review_text(runtime: RoundRuntime, rows: list[dict[str, Any]], seal: dict[str, Any]) -> str:
    lines = [
        f"# {runtime.checkpoint} isolated checkpoint tomography", "",
        f"Planning terminal: `{runtime.terminal}`", "",
        f"Ready checkpoint: `{seal['ready_checkpoint_id']}`", "",
        f"Primary observation eligible: `{seal['eligible']}`", "",
    ]
    for row in rows:
        lines.extend([
            f"## {row['checkpoint_id']} (turn {row['turn_number']})", "",
            f"Readiness classification: `{row['readiness_observation']}`", "",
            f"Observation status: `{row['status']}`", "", row["text"], "",
        ])
    return "\n".join(lines)


def _examiner_packet_text(
    *, run_dir: Path, definition: dict[str, Any], checkpoint: str,
    public_rows: list[dict[str, Any]], observation_seal: dict[str, Any],
    intervention_id: str,
) -> str:
    ready_id = observation_seal.get("ready_checkpoint_id")
    primary = next((row for row in public_rows if row.get("checkpoint_id") == ready_id), None)
    if not observation_seal.get("eligible") or primary is None:
        raise ValueError("eligible source observation is unavailable")
    spec = protocol.INTERVENTION_SPECS[intervention_id]
    examination = str(spec["examination_id"])
    charter = protocol.EXAMINATION_CHARTERS[examination]
    dossier = str(definition["dossier"]["assembled_task_text"])
    fault_lines = "\n".join(
        f"- `{item['fault_id']}` — {item['description']}"
        for item in protocol.PRIVATE_FAULT_ATLAS
    )
    rubric_lines = "\n".join(
        f"- `{item['dimension']}`: "
        + "; ".join(f"{score}={anchor}" for score, anchor in item["anchors"].items())
        for item in protocol.SEMANTIC_HUMAN_RUBRIC
    )
    source_index = protocol.CHECKPOINTS.index(checkpoint)
    trace_parts: list[str] = []
    for index in range(source_index + 1):
        trace_checkpoint = protocol.CHECKPOINTS[index]
        bundle = _strict_object(run_dir / f"{trace_checkpoint.lower()}_observations.json")
        seal = _strict_object(run_dir / f"{trace_checkpoint.lower()}_observation_seal.json")
        rows = bundle.get("rows")
        if not isinstance(rows, list):
            raise ValueError("cumulative examiner trace has invalid observation rows")
        row = next((item for item in rows if isinstance(item, dict) and item.get("checkpoint_id") == seal.get("ready_checkpoint_id")), None)
        if row is None or row.get("status") != OBSERVED:
            raise ValueError("cumulative examiner trace lacks an eligible observation")
        trace_parts.append(
            f"### {protocol.CHECKPOINT_TO_OBSERVATION[trace_checkpoint]}\n\n{row['text']}"
        )
        if index < source_index:
            prior_intervention = protocol.INTERVENTIONS[index]
            record = _strict_object(run_dir / f"{prior_intervention.lower()}/intervention.json")
            safe_record = {
                "diagnosis": record["diagnosis"],
                "observation_evidence": record["observation_evidence"],
                "targeted_reasoning_relationship": record["targeted_reasoning_relationship"],
                "predicted_observation_changes": record["predicted_observation_changes"],
                "predicted_execution_changes": record["predicted_execution_changes"],
                "prior_delta_disposition": record["prior_delta_disposition"],
                "expected_stable_commitments": record["expected_stable_commitments"],
                "intervention_text": record["intervention_text"],
            }
            trace_parts.append(
                f"### Sealed {prior_intervention}\n\n"
                + json.dumps(safe_record, ensure_ascii=True, indent=2)
            )
    cumulative_trace = "\n\n".join(trace_parts)
    return (
        f"# {examination} external examiner packet\n\n"
        "Participant: independent Sol 5.6 xhigh reviewer in ChatGPT. This packet "
        "is not a request for Codex to review its own work.\n\n"
        "## No-answer rule\n\nIdentify and test the most material evidenced "
        "reasoning fault under the charter. Do not prescribe the dossier's answer, "
        "write the recovery memorandum, or execute the plan. Propose only a local "
        "diagnostic intervention if a valid target exists.\n\n"
        f"## Stage charter: {charter['title']}\n\n{charter['instruction']}\n\n"
        f"## Frozen selection rule\n\n{spec['selection_rule']}\n\n"
        f"## Generic fault atlas\n\n{fault_lines}\n\n"
        f"## Semantic adjudication rubric\n\n{rubric_lines}\n\n"
        f"## Diagnostic states\n\n"
        + "\n".join(
            f"- `{state}` — {protocol.DIAGNOSTIC_STATE_DEFINITIONS[state]}"
            for state in protocol.DIAGNOSTIC_STATES
        )
        + f"\n\nHard-contradiction gate: {protocol.HARD_CONTRADICTION_GATE}\n\n"
        f"## Original modernization dossier\n\n{dossier}\n\n"
        "## Cumulative safe observation/intervention trace\n\n"
        f"{cumulative_trace}\n\n"
        "## Required Markdown response fields\n\n"
        "Use the exact headings in `examiner_review.md`. Give ordinary Markdown, "
        "not JSON. Evidence lines under Observation evidence must be bullets.\n"
    )


def _review_template(title: str) -> str:
    return (
        f"# {title}\n\n"
        "## Diagnosis\n\nREPLACE_BEFORE_SEALING\n\n"
        "## Observation evidence\n\n- REPLACE_BEFORE_SEALING\n\n"
        "## Targeted reasoning relationship\n\nREPLACE_BEFORE_SEALING\n\n"
        "## Predicted observation changes\n\nREPLACE_BEFORE_SEALING\n\n"
        "## Predicted execution changes\n\nREPLACE_BEFORE_SEALING\n\n"
        "## Proposed intervention text\n\nREPLACE_BEFORE_SEALING\n"
    )


def _reconciliation_template(intervention_id: str) -> str:
    prior = protocol.NO_PRIOR_INTERVENTION if intervention_id == "I1" else "REPLACE_BEFORE_SEALING"
    rubric = "\n".join(
        f"{item['dimension']}: REPLACE_WITH_0_1_OR_2"
        for item in protocol.SEMANTIC_HUMAN_RUBRIC
    )
    observation_id = str(protocol.INTERVENTION_SPECS[intervention_id]["source_observation"])
    target_fields = "\n\n".join(
        (
            f"## {target} diagnostic state\n\nREPLACE_WITH_DIAGNOSTIC_STATE\n\n"
            f"## {target} diagnostic evidence\n\nREPLACE_BEFORE_SEALING\n\n"
            f"## {target} hard contradiction present\n\nREPLACE_WITH_YES_OR_NO"
        )
        for target in protocol.OBSERVATION_ASSESSMENT_TARGETS[observation_id]
    )
    return (
        "# Human-approved reconciliation\n\n"
        "Approved by: human_researcher\n"
        "Reviewer A disposition: REPLACE_BEFORE_SEALING\n"
        "Reviewer B disposition: REPLACE_BEFORE_SEALING\n\n"
        "## Basis\n\nREPLACE_BEFORE_SEALING\n\n"
        "## Final diagnosis\n\nREPLACE_BEFORE_SEALING\n\n"
        "## Final observation evidence\n\n- REPLACE_BEFORE_SEALING\n\n"
        "## Final targeted reasoning relationship\n\nREPLACE_BEFORE_SEALING\n\n"
        "## Final predicted observation changes\n\nREPLACE_BEFORE_SEALING\n\n"
        "## Final predicted execution changes\n\nREPLACE_BEFORE_SEALING\n\n"
        f"## Prior delta: persist\n\n{prior}\n\n"
        f"## Prior delta: reverse\n\n{prior}\n\n"
        f"## Prior delta: remain unaffected\n\n{prior}\n\n"
        "## Final intervention text\n\nREPLACE_BEFORE_SEALING\n\n"
        f"## Semantic rubric\n\n{rubric}\n\n"
        f"{target_fields}\n\n"
        "## No-valid-target basis\n\nNOT_APPLICABLE\n"
    )


def _create_gate_templates(
    *, run_dir: Path, definition: dict[str, Any], checkpoint: str,
    public_rows: list[dict[str, Any]], observation_seal: dict[str, Any],
    intervention_id: str,
) -> None:
    gate = run_dir / intervention_id.lower()
    gate.mkdir(parents=False, exist_ok=False)
    packet = _examiner_packet_text(
        run_dir=run_dir, definition=definition, checkpoint=checkpoint,
        public_rows=public_rows, observation_seal=observation_seal,
        intervention_id=intervention_id,
    )
    private_signatures: list[str] = []
    for prior_checkpoint in protocol.CHECKPOINTS[: protocol.CHECKPOINTS.index(checkpoint) + 1]:
        private_signatures.extend(
            _raw_signatures(_strict_object(run_dir / f"{prior_checkpoint.lower()}_planning.private.json"))
        )
        private_signatures.extend(
            _raw_signatures(_strict_object(run_dir / f"{prior_checkpoint.lower()}_observations.private.json"))
        )
    _assert_no_raw_signatures(packet, private_signatures)
    _exclusive_text(gate / "examiner_packet.md", packet)
    packet_hash = _sha_bytes((gate / "examiner_packet.md").read_bytes())
    participants = {
        "schema_version": "modernization_iterative_review_participants_v1",
        "intervention_id": intervention_id,
        "examiner_packet_bytes_sha256": packet_hash,
        "reviewer_A": protocol.REVIEWER_PROVENANCE_REQUIREMENTS["reviewer_A"],
        "reviewer_B": protocol.REVIEWER_PROVENANCE_REQUIREMENTS["reviewer_B"],
        "codex_is_not_an_examiner": True,
    }
    _exclusive_json(gate / "participants.json", participants)
    _exclusive_text(gate / "examiner_review.md", _review_template("Independent Sol 5.6 xhigh examination"))
    _exclusive_text(gate / "researcher_review.md", _review_template("Human researcher review"))
    _exclusive_text(gate / "reconciliation.md", _reconciliation_template(intervention_id))


def _o3_assessment_packet_text(
    *, run_dir: Path, public_rows: list[dict[str, Any]],
    observation_seal: dict[str, Any],
) -> str:
    ready_id = observation_seal.get("ready_checkpoint_id")
    primary = next((row for row in public_rows if row.get("checkpoint_id") == ready_id), None)
    if not observation_seal.get("eligible") or primary is None:
        raise ValueError("eligible O3 is unavailable for final human assessment")
    targets: list[str] = []
    for intervention_id in protocol.INTERVENTIONS:
        record = _strict_object(run_dir / f"{intervention_id.lower()}/intervention.json")
        targets.append(
            f"### {intervention_id} target\n\n"
            f"Diagnosis: {record['diagnosis']}\n\n"
            f"Targeted relationship: {record['targeted_reasoning_relationship']}\n\n"
            f"Sealed intervention: {record['intervention_text']}"
        )
    rubric = "\n".join(
        f"- `{item['dimension']}`: "
        + "; ".join(f"{score}={anchor}" for score, anchor in item["anchors"].items())
        for item in protocol.SEMANTIC_HUMAN_RUBRIC
    )
    states = "\n".join(
        f"- `{state}` — {protocol.DIAGNOSTIC_STATE_DEFINITIONS[state]}"
        for state in protocol.DIAGNOSTIC_STATES
    )
    return (
        "# Human-only O3 assessment packet\n\n"
        "This is the final semantic measurement of eligible O3. It creates no "
        "X4, I4, model call, intervention, or planning continuation.\n\n"
        "## Previously sealed targets\n\n" + "\n\n".join(targets) + "\n\n"
        "## Eligible O3 primary observation\n\n" + str(primary["text"]) + "\n\n"
        "## Six-dimension semantic rubric\n\n" + rubric + "\n\n"
        "## Diagnostic states\n\n" + states + "\n\n"
        f"Hard-contradiction gate: {protocol.HARD_CONTRADICTION_GATE}\n"
    )


def _o3_assessment_template() -> str:
    rubric = "\n".join(
        f"{item['dimension']}: REPLACE_WITH_0_1_OR_2"
        for item in protocol.SEMANTIC_HUMAN_RUBRIC
    )
    target_fields = "\n\n".join(
        (
            f"## {intervention_id} final diagnostic state\n\n"
            "REPLACE_WITH_DIAGNOSTIC_STATE\n\n"
            f"## {intervention_id} final diagnostic evidence\n\n"
            "REPLACE_BEFORE_SEALING\n\n"
            f"## {intervention_id} hard contradiction present\n\n"
            "REPLACE_WITH_YES_OR_NO"
        )
        for intervention_id in protocol.INTERVENTIONS
    )
    return (
        "# Human-only O3 assessment\n\n"
        "Assessed by: human_researcher\n\n"
        "## Assessment basis\n\nREPLACE_BEFORE_SEALING\n\n"
        f"## Semantic rubric\n\n{rubric}\n\n"
        f"{target_fields}\n"
    )


def _create_o3_assessment_templates(
    *, run_dir: Path, public_rows: list[dict[str, Any]],
    observation_seal: dict[str, Any],
) -> None:
    packet = _o3_assessment_packet_text(
        run_dir=run_dir, public_rows=public_rows,
        observation_seal=observation_seal,
    )
    private_signatures = _raw_signatures(_strict_object(run_dir / "c3_planning.private.json"))
    private_signatures.extend(_raw_signatures(_strict_object(run_dir / "c3_observations.private.json")))
    _assert_no_raw_signatures(packet, private_signatures)
    _exclusive_text(run_dir / "o3_assessment_packet.md", packet)
    _exclusive_text(run_dir / "o3_assessment.md", _o3_assessment_template())


def _raw_prefix_record(store: RawCallStore) -> list[dict[str, Any]]:
    return copy.deepcopy(store.records)


def _stage_artifact_paths(checkpoint: str) -> list[str]:
    prefix = checkpoint.lower()
    paths = [
        f"{prefix}_claim.json", f"{prefix}_planning.private.json",
        f"{prefix}_planning_attempts.json", f"{prefix}_planning_summary.json",
        f"{prefix}_observations.private.json", f"{prefix}_observations.json",
        f"{prefix}_observation_seal.json", f"{prefix}_review.md",
        f"{prefix}_raw_prefix.json",
    ]
    gate = {"C0": "i1", "C1": "i2", "C2": "i3"}.get(checkpoint)
    if gate:
        paths.extend([f"{gate}/examiner_packet.md", f"{gate}/participants.json"])
    if checkpoint == "C3":
        paths.append("o3_assessment_packet.md")
    return paths


def _write_stage_seal(
    *, run_dir: Path, freeze_id: str, definition: dict[str, Any],
    checkpoint: str, runtime: RoundRuntime, claim_path: Path, claim: dict[str, Any],
    store: RawCallStore, parent_checkpoint: CheckpointRuntime | None,
    intervention_lock: Path | None,
) -> Path:
    prefix = checkpoint.lower()
    prefix_path = run_dir / f"{prefix}_raw_prefix.json"
    _exclusive_json(prefix_path, _raw_prefix_record(store))
    observation_seal = _strict_object(run_dir / f"{prefix}_observation_seal.json")
    prior_index = protocol.CHECKPOINTS.index(checkpoint) - 1
    previous_seal = run_dir / f"{protocol.CHECKPOINTS[prior_index].lower()}_stage_seal.json" if prior_index >= 0 else None
    seal = {
        "schema_version": "modernization_iterative_stage_seal_v1",
        "freeze_id": freeze_id, "checkpoint": checkpoint,
        "created_at": utc_now(),
        "task_sha256": definition["dossier"]["assembled_task_sha256"],
        "claim_id": claim["claim_id"],
        "claim_bytes_sha256": _sha_bytes(claim_path.read_bytes()),
        "previous_stage_seal_bytes_sha256": _sha_bytes(previous_seal.read_bytes()) if previous_seal else None,
        "intervention_lock_bytes_sha256": _sha_bytes(intervention_lock.read_bytes()) if intervention_lock else None,
        "parent_checkpoint_id": parent_checkpoint.checkpoint_id if parent_checkpoint else None,
        "parent_full_history_sha256": _sha_json(parent_checkpoint.full_history) if parent_checkpoint else None,
        "round_terminal": runtime.terminal,
        "ready_checkpoint_id": runtime.ready_checkpoint.checkpoint_id if runtime.ready_checkpoint else None,
        "ready_full_history_sha256": _sha_json(runtime.ready_checkpoint.full_history) if runtime.ready_checkpoint else None,
        "ready_observation_eligible": observation_seal["eligible"],
        "observation_seal_bytes_sha256": _sha_bytes((run_dir / f"{prefix}_observation_seal.json").read_bytes()),
        "raw_call_count": len(store.records),
        "raw_prefix_sha256": _sha_json(store.records),
        "raw_prefix_bytes_sha256": _sha_bytes(prefix_path.read_bytes()),
        "raw_inventory": _raw_inventory(run_dir),
        "artifact_inventory": _artifact_inventory(run_dir, _stage_artifact_paths(checkpoint)),
        "next_gate": (
            {"C0": "I1", "C1": "I2", "C2": "I3", "C3": "O3_ASSESSMENT"}[checkpoint]
            if observation_seal["eligible"] else None
        ),
    }
    path = run_dir / f"{prefix}_stage_seal.json"
    _exclusive_json(path, seal)
    return path


def execute_checkpoint(
    *, repo_root: Path, freeze_dir: Path, freeze_id: str, checkpoint: str,
    api_key: str, transport: Callable[..., GenerateContentHttpResult] | None = None,
) -> tuple[Path, RoundRuntime]:
    if checkpoint not in protocol.CHECKPOINTS:
        raise ValueError("invalid checkpoint")
    definition = _load_definition(repo_root=repo_root, freeze_dir=freeze_dir, freeze_id=freeze_id)
    run_dir = execution_output_dir(repo_root=repo_root, freeze_id=freeze_id)
    _assert_private_root(repo_root=repo_root, run_dir=run_dir)
    if checkpoint == "C0":
        run_dir.mkdir(parents=True, exist_ok=False)
    elif not run_dir.is_dir():
        raise ValueError("prior trajectory archive does not exist")
    prefix = checkpoint.lower()
    claim_path = run_dir / f"{prefix}_claim.json"
    parent: CheckpointRuntime | None = None
    lock_path: Path | None = None
    if checkpoint == "C0":
        if any(run_dir.iterdir()):
            raise ValueError("fresh C0 directory is not empty")
        first = protocol.initial_planning_body(task_text=definition["dossier"]["assembled_task_text"])
        parent_history = None
        bindings = {"task_sha256": definition["dossier"]["assembled_task_sha256"]}
    else:
        previous = protocol.CHECKPOINTS[protocol.CHECKPOINTS.index(checkpoint) - 1]
        intervention_id = protocol.INTERVENTIONS[protocol.CHECKPOINTS.index(checkpoint) - 1]
        gate_verification = verify_archive(
            repo_root=repo_root, freeze_dir=freeze_dir, freeze_id=freeze_id,
            through=intervention_id.lower(),
        )
        if gate_verification.get("terminal") == "NO_VALID_TARGET":
            raise ValueError(f"trajectory cannot continue after {intervention_id} no-target terminal")
        parent = _load_round_runtime(run_dir, previous).ready_checkpoint
        if parent is None:
            raise ValueError("prior stage has no READY checkpoint")
        lock_path = run_dir / f"{intervention_id.lower()}/lock.json"
        lock = _strict_object(lock_path)
        record = _strict_object(run_dir / f"{intervention_id.lower()}/intervention.json")
        observation_path = run_dir / f"{previous.lower()}_observations.json"
        source_hash = _sha_bytes(observation_path.read_bytes())
        if lock.get("source_observations_bytes_sha256") != source_hash:
            raise ValueError("intervention lock is not bound to source observations")
        first = protocol.intervention_body(
            parent_ready_history=parent.full_history, intervention_id=intervention_id,
            sealed_record=record, source_observation_sha256=source_hash,
        )
        parent_history = parent.full_history
        bindings = {
            "parent_checkpoint_id": parent.checkpoint_id,
            "parent_full_history_sha256": _sha_json(parent.full_history),
            "intervention_lock_bytes_sha256": _sha_bytes(lock_path.read_bytes()),
        }
    claim = _claim(
        claim_path, schema="modernization_iterative_round_claim_v1",
        freeze_id=freeze_id, kind=checkpoint, bindings=bindings,
    )
    terminal_path = run_dir / f"{prefix}_terminal.json"
    try:
        store = _make_store(run_dir=run_dir, api_key=api_key, transport=transport)
        runtime, _private, public = run_checkpoint_round(
            checkpoint=checkpoint, first_body=first, store=store, run_dir=run_dir,
            expected_parent_history=parent_history,
        )
        observation_seal = _strict_object(run_dir / f"{prefix}_observation_seal.json")
        if observation_seal["eligible"] and checkpoint in {"C0", "C1", "C2"}:
            intervention_id = {"C0": "I1", "C1": "I2", "C2": "I3"}[checkpoint]
            _create_gate_templates(
                run_dir=run_dir, definition=definition, checkpoint=checkpoint, public_rows=public,
                observation_seal=observation_seal, intervention_id=intervention_id,
            )
        if observation_seal["eligible"] and checkpoint == "C3":
            _create_o3_assessment_templates(
                run_dir=run_dir, public_rows=public,
                observation_seal=observation_seal,
            )
        seal_path = _write_stage_seal(
            run_dir=run_dir, freeze_id=freeze_id, definition=definition,
            checkpoint=checkpoint, runtime=runtime, claim_path=claim_path,
            claim=claim, store=store, parent_checkpoint=parent,
            intervention_lock=lock_path,
        )
        status = "COMPLETED" if observation_seal["eligible"] else runtime.terminal
        _terminal(
            terminal_path, schema="modernization_iterative_round_terminal_v1",
            claim_path=claim_path, claim=claim, status=status,
            sealed_path=seal_path,
        )
        verify_archive(repo_root=repo_root, freeze_dir=freeze_dir, freeze_id=freeze_id, through=checkpoint.lower())
        return run_dir, runtime
    except BaseException as exc:
        if not terminal_path.exists():
            _terminal(
                terminal_path, schema="modernization_iterative_round_terminal_v1",
                claim_path=claim_path, claim=claim, status="FAILED",
                error_type=type(exc).__name__,
            )
        raise


REVIEW_HEADINGS = (
    "Diagnosis", "Observation evidence", "Targeted reasoning relationship",
    "Predicted observation changes", "Predicted execution changes",
    "Proposed intervention text",
)
def _reconciliation_headings(intervention_id: str) -> tuple[str, ...]:
    observation_id = str(protocol.INTERVENTION_SPECS[intervention_id]["source_observation"])
    target_headings = tuple(
        heading
        for target in protocol.OBSERVATION_ASSESSMENT_TARGETS[observation_id]
        for heading in (
            f"{target} diagnostic state",
            f"{target} diagnostic evidence",
            f"{target} hard contradiction present",
        )
    )
    return (
        "Basis", "Final diagnosis", "Final observation evidence",
        "Final targeted reasoning relationship",
        "Final predicted observation changes", "Final predicted execution changes",
        "Prior delta: persist", "Prior delta: reverse",
        "Prior delta: remain unaffected", "Final intervention text",
        "Semantic rubric", *target_headings, "No-valid-target basis",
    )


def _markdown_sections(path: Path, expected: tuple[str, ...]) -> tuple[str, dict[str, str]]:
    if not path.is_file() or _is_link(path):
        raise ValueError(f"review artifact is not a safe file: {path.name}")
    text = path.read_text(encoding="utf-8")
    if "REPLACE_BEFORE" in text or "REPLACE_WITH" in text:
        raise ValueError(f"review artifact still contains template markers: {path.name}")
    matches = list(re.finditer(r"(?m)^## ([^\r\n]+)\r?$", text))
    headings = tuple(match.group(1).strip() for match in matches)
    if headings != expected:
        raise ValueError(f"review headings differ from exact template: {path.name}")
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        value = text[match.end():end].strip()
        if not value:
            raise ValueError(f"review field is empty: {match.group(1)}")
        sections[match.group(1).strip()] = value
    return text, sections


def _evidence_lines(value: str, *, label: str) -> list[str]:
    lines = [line[2:].strip() for line in value.splitlines() if line.startswith("- ")]
    if not lines or any(not line for line in lines):
        raise ValueError(f"{label} must contain one or more Markdown bullets")
    return lines


def _parse_review(path: Path, *, reviewer: str, packet_hash: str) -> dict[str, Any]:
    _text, fields = _markdown_sections(path, REVIEW_HEADINGS)
    stream = {
        "provenance": {
            **protocol.REVIEWER_PROVENANCE_REQUIREMENTS[reviewer],
            "input_sha256": packet_hash,
        },
        "diagnosis": fields["Diagnosis"],
        "observation_evidence": _evidence_lines(fields["Observation evidence"], label=reviewer),
        "targeted_reasoning_relationship": fields["Targeted reasoning relationship"],
        "predicted_observation_changes": fields["Predicted observation changes"],
        "predicted_execution_changes": fields["Predicted execution changes"],
        "proposed_intervention_text": fields["Proposed intervention text"],
    }
    protocol._validate_review_stream(stream, reviewer=reviewer)
    return stream


def _parse_reconciliation(path: Path, *, intervention_id: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    text, fields = _markdown_sections(path, _reconciliation_headings(intervention_id))
    approved = re.findall(r"(?m)^Approved by: ([^\r\n]+)\r?$", text)
    disposition_a = re.findall(r"(?m)^Reviewer A disposition: ([^\r\n]+)\r?$", text)
    disposition_b = re.findall(r"(?m)^Reviewer B disposition: ([^\r\n]+)\r?$", text)
    reconciliation = {
        "approved_by": approved[0].strip() if len(approved) == 1 else "",
        "basis": fields["Basis"],
        "reviewer_A_disposition": disposition_a[0].strip() if len(disposition_a) == 1 else "",
        "reviewer_B_disposition": disposition_b[0].strip() if len(disposition_b) == 1 else "",
    }
    protocol._validate_reconciliation(reconciliation)
    prior = {
        "persist": fields["Prior delta: persist"],
        "reverse": fields["Prior delta: reverse"],
        "remain_unaffected": fields["Prior delta: remain unaffected"],
    }
    if intervention_id == "I1" and set(prior.values()) != {protocol.NO_PRIOR_INTERVENTION}:
        raise ValueError("I1 reconciliation must declare no prior intervention delta")
    if intervention_id != "I1" and set(prior.values()) == {protocol.NO_PRIOR_INTERVENTION}:
        raise ValueError("later reconciliation must classify the prior delta")
    expected_dimensions = [item["dimension"] for item in protocol.SEMANTIC_HUMAN_RUBRIC]
    rubric: dict[str, int] = {}
    for line in fields["Semantic rubric"].splitlines():
        if ":" not in line:
            raise ValueError("semantic rubric line lacks a colon")
        key, raw = (part.strip() for part in line.split(":", 1))
        if key in rubric or raw not in {"0", "1", "2"}:
            raise ValueError("semantic rubric score is invalid")
        rubric[key] = int(raw)
    if list(rubric) != expected_dimensions:
        raise ValueError("semantic rubric dimensions or order differ")
    observation_id = str(protocol.INTERVENTION_SPECS[intervention_id]["source_observation"])
    target_states: dict[str, dict[str, Any]] = {}
    for target in protocol.OBSERVATION_ASSESSMENT_TARGETS[observation_id]:
        state = fields[f"{target} diagnostic state"].strip()
        hard = fields[f"{target} hard contradiction present"].strip().upper()
        if state not in protocol.DIAGNOSTIC_STATES:
            raise ValueError(f"{target} diagnostic state is invalid")
        if hard not in {"YES", "NO"}:
            raise ValueError(f"{target} hard-contradiction field must be YES or NO")
        target_states[target] = {
            "state": state,
            "evidence": fields[f"{target} diagnostic evidence"],
            "hard_contradiction_present": hard == "YES",
        }
    adjudication = {
        "observation_id": observation_id,
        "assessed_by": "human_researcher",
        "assessment_basis": fields["Basis"],
        "rubric_scores": rubric,
        "target_diagnostic_states": target_states,
    }
    protocol._validate_observation_assessment(adjudication, observation_id=observation_id)
    final = {
        "reconciliation": reconciliation,
        "diagnosis": fields["Final diagnosis"],
        "observation_evidence": _evidence_lines(fields["Final observation evidence"], label="reconciliation"),
        "targeted_reasoning_relationship": fields["Final targeted reasoning relationship"],
        "predicted_observation_changes": fields["Final predicted observation changes"],
        "predicted_execution_changes": fields["Final predicted execution changes"],
        "prior_delta_disposition": prior,
        "expected_stable_commitments": list(protocol.STABLE_SEMANTIC_COMMITMENTS),
        "source_observation_assessment": adjudication,
        "intervention_text": fields["Final intervention text"],
        "no_valid_target_basis": fields["No-valid-target basis"],
    }
    return final, adjudication, text


def _review_bundle(gate: Path, *, intervention_id: str, packet_hash: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    reviewer_a = _parse_review(gate / "researcher_review.md", reviewer="reviewer_A", packet_hash=packet_hash)
    reviewer_b = _parse_review(gate / "examiner_review.md", reviewer="reviewer_B", packet_hash=packet_hash)
    final, adjudication, _text = _parse_reconciliation(gate / "reconciliation.md", intervention_id=intervention_id)
    draft = {
        "reviewer_A": reviewer_a, "reviewer_B": reviewer_b,
        **{key: value for key, value in final.items() if key != "no_valid_target_basis"},
    }
    provenance = {
        "schema_version": "modernization_iterative_review_provenance_v1",
        "intervention_id": intervention_id,
        "examiner_packet_bytes_sha256": packet_hash,
        "examiner_output_bytes_sha256": _sha_bytes((gate / "examiner_review.md").read_bytes()),
        "researcher_review_bytes_sha256": _sha_bytes((gate / "researcher_review.md").read_bytes()),
        "reconciliation_bytes_sha256": _sha_bytes((gate / "reconciliation.md").read_bytes()),
        "participants_bytes_sha256": _sha_bytes((gate / "participants.json").read_bytes()),
        "external_examiner": copy.deepcopy(protocol.REVIEWER_PROVENANCE_REQUIREMENTS["reviewer_B"]),
        "human_researcher": copy.deepcopy(protocol.REVIEWER_PROVENANCE_REQUIREMENTS["reviewer_A"]),
        "codex_substitute_used": False,
    }
    return draft, adjudication, {"provenance": provenance, "no_valid_target_basis": final["no_valid_target_basis"]}


def _gate_source_paths(run_dir: Path, intervention_id: str) -> tuple[str, str]:
    spec = protocol.INTERVENTION_SPECS[intervention_id]
    checkpoint = str(spec["source_checkpoint"])
    return checkpoint, f"{checkpoint.lower()}_observations.json"


def _seal_gate(
    *, repo_root: Path, freeze_dir: Path, freeze_id: str,
    intervention_id: str, no_target: bool,
) -> Path:
    if intervention_id not in protocol.INTERVENTIONS:
        raise ValueError("invalid intervention id")
    _load_definition(repo_root=repo_root, freeze_dir=freeze_dir, freeze_id=freeze_id)
    run_dir = execution_output_dir(repo_root=repo_root, freeze_id=freeze_id)
    checkpoint, observation_relative = _gate_source_paths(run_dir, intervention_id)
    verify_archive(repo_root=repo_root, freeze_dir=freeze_dir, freeze_id=freeze_id, through=checkpoint.lower())
    gate = run_dir / intervention_id.lower()
    packet_path = gate / "examiner_packet.md"
    packet_hash = _sha_bytes(packet_path.read_bytes())
    claim_path = gate / "disposition_claim.json"
    kind = "NO_VALID_TARGET" if no_target else "SEALED_INTERVENTION"
    claim = _claim(
        claim_path, schema="modernization_iterative_disposition_claim_v1",
        freeze_id=freeze_id, kind=kind,
        bindings={
            "source_stage_seal_bytes_sha256": _sha_bytes((run_dir / f"{checkpoint.lower()}_stage_seal.json").read_bytes()),
            "examiner_packet_bytes_sha256": packet_hash,
        },
    )
    terminal_path = gate / "disposition_terminal.json"
    try:
        source_observations = run_dir / observation_relative
        source_hash = _sha_bytes(source_observations.read_bytes())
        selected_at = utc_now()
        draft, adjudication, review_meta = _review_bundle(
            gate, intervention_id=intervention_id, packet_hash=packet_hash,
        )
        provenance_path = gate / "review_provenance.json"
        _exclusive_json(provenance_path, review_meta["provenance"])
        adjudication_path = gate / "semantic_adjudication.json"
        _exclusive_json(adjudication_path, adjudication)
        review_bytes_hash = _sha_json({
            "examiner": review_meta["provenance"]["examiner_output_bytes_sha256"],
            "researcher": review_meta["provenance"]["researcher_review_bytes_sha256"],
            "reconciliation": review_meta["provenance"]["reconciliation_bytes_sha256"],
        })
        if no_target:
            basis = str(review_meta["no_valid_target_basis"]).strip()
            if not basis or basis == "NOT_APPLICABLE":
                raise ValueError("no-target closure requires an approved basis")
            record = {
                "schema_version": "modernization_iterative_no_target_record_v1",
                "intervention_id": intervention_id,
                "reviewer_A": draft["reviewer_A"],
                "reviewer_B": draft["reviewer_B"],
                "reconciliation": draft["reconciliation"],
                "no_valid_target_basis": basis,
                "semantic_adjudication_sha256": _sha_bytes(adjudication_path.read_bytes()),
            }
            record_path = gate / "no_target_record.json"
            _exclusive_json(record_path, record)
            note_path = gate / "no_target_note.md"
            _exclusive_text(note_path, basis + "\n")
            lock_path = None
            sealed_hash = _sha_bytes(record_path.read_bytes())
        else:
            if str(review_meta["no_valid_target_basis"]).strip() != "NOT_APPLICABLE":
                raise ValueError("sealed intervention must mark no-target basis NOT_APPLICABLE")
            sealed = protocol.seal_human_intervention_record(
                draft, intervention_id=intervention_id,
                source_observation_sha256=source_hash,
                examiner_input_sha256=packet_hash,
                examiner_output_sha256=review_meta["provenance"]["examiner_output_bytes_sha256"],
                sealed_at=selected_at,
            )
            record_path = gate / "intervention.json"
            _exclusive_json(record_path, sealed)
            lock = {
                "schema_version": "modernization_iterative_intervention_lock_v1",
                "freeze_id": freeze_id, "intervention_id": intervention_id,
                "created_at": utc_now(),
                "source_stage_seal_bytes_sha256": _sha_bytes((run_dir / f"{checkpoint.lower()}_stage_seal.json").read_bytes()),
                "source_observations_bytes_sha256": source_hash,
                "examiner_packet_bytes_sha256": packet_hash,
                "examiner_output_bytes_sha256": review_meta["provenance"]["examiner_output_bytes_sha256"],
                "researcher_review_bytes_sha256": review_meta["provenance"]["researcher_review_bytes_sha256"],
                "reconciliation_bytes_sha256": review_meta["provenance"]["reconciliation_bytes_sha256"],
                "review_bundle_sha256": review_bytes_hash,
                "review_provenance_bytes_sha256": _sha_bytes(provenance_path.read_bytes()),
                "semantic_adjudication_bytes_sha256": _sha_bytes(adjudication_path.read_bytes()),
                "sealed_intervention_bytes_sha256": _sha_bytes(record_path.read_bytes()),
                "sealed_before_target_checkpoint": True,
            }
            lock_path = gate / "lock.json"
            _exclusive_json(lock_path, lock)
            sealed_hash = _sha_bytes(record_path.read_bytes())
        disposition = {
            "schema_version": "modernization_iterative_disposition_v1",
            "freeze_id": freeze_id, "intervention_id": intervention_id,
            "claim_id": claim["claim_id"], "selected_at": selected_at,
            "disposition": kind,
            "source_observations_bytes_sha256": source_hash,
            "examiner_packet_bytes_sha256": packet_hash,
            "examiner_output_bytes_sha256": review_meta["provenance"]["examiner_output_bytes_sha256"],
            "researcher_review_bytes_sha256": review_meta["provenance"]["researcher_review_bytes_sha256"],
            "reconciliation_bytes_sha256": review_meta["provenance"]["reconciliation_bytes_sha256"],
            "review_bundle_sha256": review_bytes_hash,
            "review_provenance_bytes_sha256": _sha_bytes(provenance_path.read_bytes()),
            "semantic_adjudication_bytes_sha256": _sha_bytes(adjudication_path.read_bytes()),
            "record_bytes_sha256": sealed_hash,
            "lock_bytes_sha256": _sha_bytes(lock_path.read_bytes()) if lock_path else None,
        }
        disposition_path = gate / "disposition.json"
        _exclusive_json(disposition_path, disposition)
        _terminal(
            terminal_path, schema="modernization_iterative_disposition_terminal_v1",
            claim_path=claim_path, claim=claim, status="COMPLETED",
            sealed_path=lock_path or record_path,
        )
        verify_archive(
            repo_root=repo_root, freeze_dir=freeze_dir, freeze_id=freeze_id,
            through=intervention_id.lower(),
        )
        return run_dir
    except BaseException as exc:
        if not terminal_path.exists():
            _terminal(
                terminal_path, schema="modernization_iterative_disposition_terminal_v1",
                claim_path=claim_path, claim=claim, status="FAILED",
                error_type=type(exc).__name__,
            )
        raise


def seal_intervention(**kwargs: Any) -> Path:
    return _seal_gate(no_target=False, **kwargs)


def close_no_target(**kwargs: Any) -> Path:
    return _seal_gate(no_target=True, **kwargs)


def _parse_o3_assessment(path: Path, *, packet_hash: str) -> dict[str, Any]:
    if not _is_sha256(packet_hash):
        raise ValueError("O3 assessment packet hash is invalid")
    headings = (
        "Assessment basis", "Semantic rubric",
        *tuple(
            heading
            for intervention_id in protocol.INTERVENTIONS
            for heading in (
                f"{intervention_id} final diagnostic state",
                f"{intervention_id} final diagnostic evidence",
                f"{intervention_id} hard contradiction present",
            )
        ),
    )
    text, fields = _markdown_sections(path, headings)
    assessors = re.findall(r"(?m)^Assessed by: ([^\r\n]+)\r?$", text)
    if assessors != ["human_researcher"]:
        raise ValueError("O3 assessment must name exactly the human researcher")
    expected_dimensions = [item["dimension"] for item in protocol.SEMANTIC_HUMAN_RUBRIC]
    rubric: dict[str, int] = {}
    for line in fields["Semantic rubric"].splitlines():
        if ":" not in line:
            raise ValueError("O3 semantic rubric line lacks a colon")
        key, raw = (part.strip() for part in line.split(":", 1))
        if key in rubric or raw not in {"0", "1", "2"}:
            raise ValueError("O3 semantic rubric score is invalid")
        rubric[key] = int(raw)
    if list(rubric) != expected_dimensions:
        raise ValueError("O3 semantic rubric dimensions or order differ")
    target_states: dict[str, dict[str, Any]] = {}
    for intervention_id in protocol.INTERVENTIONS:
        state = fields[f"{intervention_id} final diagnostic state"].strip()
        hard = fields[f"{intervention_id} hard contradiction present"].strip().upper()
        if state not in protocol.DIAGNOSTIC_STATES:
            raise ValueError(f"O3 {intervention_id} diagnostic state is invalid")
        if hard not in {"YES", "NO"}:
            raise ValueError(f"O3 {intervention_id} hard-contradiction field is invalid")
        if hard == "YES" and state == "RESOLVED":
            raise ValueError(f"a live {intervention_id} hard contradiction prevents RESOLVED")
        target_states[intervention_id] = {
            "state": state,
            "evidence": fields[f"{intervention_id} final diagnostic evidence"],
            "hard_contradiction_present": hard == "YES",
        }
    assessment = {
        "observation_id": "O3", "assessed_by": "human_researcher",
        "assessment_basis": fields["Assessment basis"],
        "rubric_scores": rubric,
        "target_diagnostic_states": target_states,
    }
    protocol._validate_observation_assessment(assessment, observation_id="O3")
    return assessment


def seal_o3_assessment(
    *, repo_root: Path, freeze_dir: Path, freeze_id: str,
) -> Path:
    _load_definition(repo_root=repo_root, freeze_dir=freeze_dir, freeze_id=freeze_id)
    run_dir = execution_output_dir(repo_root=repo_root, freeze_id=freeze_id)
    verify_archive(repo_root=repo_root, freeze_dir=freeze_dir, freeze_id=freeze_id, through="c3")
    observation_seal_path = run_dir / "c3_observation_seal.json"
    observation_seal = _strict_object(observation_seal_path)
    if observation_seal.get("eligible") is not True:
        raise ValueError("O3 assessment requires an eligible O3 observation")
    packet_path = run_dir / "o3_assessment_packet.md"
    assessment_path = run_dir / "o3_assessment.md"
    packet_hash = _sha_bytes(packet_path.read_bytes())
    claim_path = run_dir / "o3_assessment_claim.json"
    claim = _claim(
        claim_path, schema="modernization_iterative_o3_assessment_claim_v1",
        freeze_id=freeze_id, kind="HUMAN_O3_ASSESSMENT",
        bindings={
            "c3_stage_seal_bytes_sha256": _sha_bytes((run_dir / "c3_stage_seal.json").read_bytes()),
            "o3_observations_bytes_sha256": _sha_bytes((run_dir / "c3_observations.json").read_bytes()),
            "o3_observation_seal_bytes_sha256": _sha_bytes(observation_seal_path.read_bytes()),
            "assessment_packet_bytes_sha256": packet_hash,
        },
    )
    terminal_path = run_dir / "o3_assessment_terminal.json"
    try:
        human_assessment = _parse_o3_assessment(assessment_path, packet_hash=packet_hash)
        assessment = protocol.seal_final_o3_assessment(
            human_assessment,
            source_observation_sha256=_sha_bytes((run_dir / "c3_observations.json").read_bytes()),
            sealed_at=utc_now(),
        )
        record_path = run_dir / "o3_assessment.json"
        _exclusive_json(record_path, assessment)
        lock = {
            "schema_version": "modernization_iterative_o3_assessment_lock_v1",
            "freeze_id": freeze_id, "created_at": utc_now(),
            "claim_id": claim["claim_id"],
            "claim_bytes_sha256": _sha_bytes(claim_path.read_bytes()),
            **copy.deepcopy(claim["bindings"]),
            "assessment_source_bytes_sha256": _sha_bytes(assessment_path.read_bytes()),
            "assessment_record_bytes_sha256": _sha_bytes(record_path.read_bytes()),
            "no_X4_or_I4": True, "no_model_call": True,
        }
        lock_path = run_dir / "o3_assessment.lock.json"
        _exclusive_json(lock_path, lock)
        _terminal(
            terminal_path, schema="modernization_iterative_o3_assessment_terminal_v1",
            claim_path=claim_path, claim=claim, status="COMPLETED",
            sealed_path=lock_path,
        )
        verify_archive(
            repo_root=repo_root, freeze_dir=freeze_dir, freeze_id=freeze_id,
            through="o3",
        )
        return run_dir
    except BaseException as exc:
        if not terminal_path.exists():
            _terminal(
                terminal_path, schema="modernization_iterative_o3_assessment_terminal_v1",
                claim_path=claim_path, claim=claim, status="FAILED",
                error_type=type(exc).__name__,
            )
        raise


def run_primary_executions(
    *, repo_root: Path, freeze_dir: Path, freeze_id: str, api_key: str,
    transport: Callable[..., GenerateContentHttpResult] | None = None,
) -> Path:
    definition = _load_definition(repo_root=repo_root, freeze_dir=freeze_dir, freeze_id=freeze_id)
    run_dir = execution_output_dir(repo_root=repo_root, freeze_id=freeze_id)
    verify_archive(repo_root=repo_root, freeze_dir=freeze_dir, freeze_id=freeze_id, through="o3")
    histories: dict[str, CheckpointRuntime] = {}
    for checkpoint in protocol.CHECKPOINTS:
        ready = _load_round_runtime(run_dir, checkpoint).ready_checkpoint
        if ready is None:
            raise ValueError(f"{checkpoint} has no READY execution baseline")
        histories[checkpoint] = ready
    claim_path = run_dir / "execution_claim.json"
    stage_hashes = {
        checkpoint: _sha_bytes((run_dir / f"{checkpoint.lower()}_stage_seal.json").read_bytes())
        for checkpoint in protocol.CHECKPOINTS
    }
    o3_assessment_lock_hash = _sha_bytes((run_dir / "o3_assessment.lock.json").read_bytes())
    claim = _claim(
        claim_path, schema="modernization_iterative_execution_claim_v1",
        freeze_id=freeze_id, kind="PRIMARY_EXECUTIONS",
        bindings={
            "stage_seal_bytes_sha256": stage_hashes,
            "o3_assessment_lock_bytes_sha256": o3_assessment_lock_hash,
        },
    )
    terminal_path = run_dir / "execution_terminal.json"
    try:
        store = _make_store(run_dir=run_dir, api_key=api_key, transport=transport)
        schedule = protocol.build_execution_schedule()
        if schedule != definition["execution"]["schedule"] or len(schedule) != 12:
            raise ValueError("execution schedule differs from frozen twelve-call schedule")
        private_rows: list[dict[str, Any]] = []
        public_rows: list[dict[str, Any]] = []
        for row in schedule:
            checkpoint = str(row["checkpoint"])
            replicate = int(row["replicate"])
            ready = histories[checkpoint]
            body = protocol.execution_body(
                full_history=ready.full_history, checkpoint=checkpoint,
                replicate=replicate,
            )
            if body["contents"][:-1] != ready.full_history:
                raise RuntimeError("execution request changed exact checkpoint history")
            label = f"execution_{row['order']:02d}_{checkpoint.lower()}_replicate_{replicate}"
            result, call = _invoke(store, label=label, body=body)
            measured = _evaluate_prose_result(result)
            private = {
                **copy.deepcopy(row), "checkpoint_id": ready.checkpoint_id,
                "status": measured["status"], "text": measured["text"],
                "steps": measured["steps"], "reasons": measured["reasons"],
                "safe_metadata": measured["safe_metadata"], "call": call,
                "history_sha256": _sha_json(ready.full_history),
                "request_contents_sha256": _sha_json(body["contents"]),
            }
            public = {key: value for key, value in private.items() if key != "steps"}
            private_rows.append(private)
            public_rows.append(public)
        _exclusive_json(run_dir / "executions.private.json", {
            "schema_version": "modernization_iterative_executions_private_v1",
            "schedule": schedule, "rows": private_rows,
        })
        public_bundle = {
            "schema_version": "modernization_iterative_executions_v1",
            "schedule": schedule, "rows": public_rows,
        }
        signatures = _raw_signatures(private_rows)
        _assert_no_raw_signatures(public_bundle, signatures)
        _exclusive_json(run_dir / "executions.json", public_bundle)
        prefix_path = run_dir / "execution_raw_prefix.json"
        _exclusive_json(prefix_path, store.records)
        if any(row["status"] != OBSERVED for row in public_rows):
            terminal_status = "EXECUTION_MEASUREMENT_INCOMPLETE"
        else:
            terminal_status = "COMPLETED"
        seal = {
            "schema_version": "modernization_iterative_trajectory_seal_v1",
            "freeze_id": freeze_id, "created_at": utc_now(),
            "claim_id": claim["claim_id"],
            "claim_bytes_sha256": _sha_bytes(claim_path.read_bytes()),
            "stage_seal_bytes_sha256": stage_hashes,
            "o3_assessment_lock_bytes_sha256": o3_assessment_lock_hash,
            "intervention_lock_bytes_sha256": {
                item: _sha_bytes((run_dir / f"{item.lower()}/lock.json").read_bytes())
                for item in protocol.INTERVENTIONS
            },
            "schedule": schedule, "execution_row_count": len(public_rows),
            "execution_status": terminal_status,
            "final_call_count": len(store.records),
            "final_call_index_sha256": _sha_json(store.records),
            "final_call_index_bytes_sha256": _sha_bytes((run_dir / "raw/call_index.json").read_bytes()),
            "raw_inventory": _raw_inventory(run_dir),
            "artifact_inventory": _artifact_inventory(run_dir, [
                "execution_claim.json", "executions.private.json", "executions.json",
                "execution_raw_prefix.json",
            ]),
            "neutral_lane_present": False,
        }
        seal_path = run_dir / "trajectory_seal.json"
        _exclusive_json(seal_path, seal)
        _terminal(
            terminal_path, schema="modernization_iterative_execution_terminal_v1",
            claim_path=claim_path, claim=claim, status=terminal_status,
            sealed_path=seal_path,
        )
        verify_archive(repo_root=repo_root, freeze_dir=freeze_dir, freeze_id=freeze_id, through="final")
        return run_dir
    except BaseException as exc:
        if not terminal_path.exists():
            _terminal(
                terminal_path, schema="modernization_iterative_execution_terminal_v1",
                claim_path=claim_path, claim=claim, status="FAILED",
                error_type=type(exc).__name__,
            )
        raise


def _retryable(record: Mapping[str, Any]) -> str:
    if record.get("transport_error"):
        return "transport_error"
    status = record.get("http_status")
    return f"http_{status}" if status in {408, 429, 500, 502, 503, 504} else ""


def _validate_call_index(run_dir: Path) -> list[dict[str, Any]]:
    value = _strict_list(run_dir / "raw/call_index.json")
    previous: datetime | None = None
    for number, raw in enumerate(value, start=1):
        if not isinstance(raw, dict) or set(raw) != CALL_INDEX_KEYS:
            raise ValueError("raw call-index record shape is invalid")
        if raw.get("call_number") != number or type(raw.get("call_number")) is not int:
            raise ValueError("raw call numbers are not contiguous")
        if raw.get("attempt_state") != "transport_result_persisted":
            raise ValueError("raw call has no persisted transport result")
        if raw.get("request_target") != _request_target():
            raise ValueError("raw call request target differs")
        http_status = raw.get("http_status")
        response_headers = raw.get("response_headers")
        if (
            (http_status is not None and (type(http_status) is not int or not 100 <= http_status <= 599))
            or type(raw.get("elapsed_ms")) is not int or raw["elapsed_ms"] < 0
            or type(raw.get("request_wire_bytes")) is not int or raw["request_wire_bytes"] < 1
            or type(raw.get("response_wire_bytes")) is not int or raw["response_wire_bytes"] < 0
            or type(raw.get("response_decoded_chars")) is not int or raw["response_decoded_chars"] < 0
            or not isinstance(raw.get("transport_error"), str)
            or not isinstance(raw.get("response_parse_error"), str)
            or not isinstance(response_headers, dict)
            or any(not isinstance(key, str) or not isinstance(item, str) for key, item in response_headers.items())
            or not isinstance(raw.get("label"), str) or not raw["label"]
            or not _is_sha256(raw.get("request_wire_sha256"))
            or (raw.get("response_wire_sha256") is not None and not _is_sha256(raw.get("response_wire_sha256")))
            or not isinstance(raw.get("raw_request_path"), str)
            or not isinstance(raw.get("raw_response_path"), str)
        ):
            raise ValueError("raw call metadata field types are invalid")
        started = _utc(raw.get("started_at"), label="raw call start")
        completed = _utc(raw.get("completed_at"), label="raw call completion")
        if started > completed or (previous and previous > started):
            raise ValueError("raw call timestamp order is invalid")
        previous = completed
        request_fragment = Path(raw["raw_request_path"])
        response_fragment = Path(raw["raw_response_path"])
        if request_fragment.is_absolute() or response_fragment.is_absolute():
            raise ValueError("raw call path is absolute")
        request = run_dir / request_fragment
        response = run_dir / response_fragment
        if not request.absolute().is_relative_to((run_dir / "raw").absolute()) or not response.absolute().is_relative_to((run_dir / "raw").absolute()):
            raise ValueError("raw call path escapes archive")
        _assert_no_link_ancestor(root=run_dir, path=request)
        _assert_no_link_ancestor(root=run_dir, path=response)
        stem = request.name.removesuffix(".request.json")
        metadata = request.with_name(stem + ".metadata.json")
        request_bytes = request.read_bytes()
        response_bytes = response.read_bytes()
        if (
            not request.name.startswith(f"{number:04d}_")
            or response.name != stem + ".response.bin"
            or _strict_object(metadata) != raw
            or raw.get("request_wire_bytes") != len(request_bytes)
            or raw.get("request_wire_sha256") != _sha_bytes(request_bytes)
            or raw.get("response_wire_bytes") != len(response_bytes)
            or raw.get("response_wire_sha256") != (_sha_bytes(response_bytes) if response_bytes else None)
            or raw.get("response_decoded_chars") != len(response_bytes.decode("utf-8", errors="replace"))
        ):
            raise ValueError("raw wire artifact differs from call index")
    if not value:
        raise ValueError("raw call index is empty")
    return copy.deepcopy(value)


def _bound_result(
    *, run_dir: Path, call: Any, label: str, body: dict[str, Any], cursor: CallCursor,
) -> GenerateContentHttpResult:
    if not isinstance(call, dict) or set(call) != {
        "logical_request_id", "attempt_count", "selected_physical_call_number",
        "selected_response_wire_sha256", "selection_reason", "request_wire_sha256",
    }:
        raise ValueError("semantic call summary shape is invalid")
    logical_path = run_dir / "raw" / f"logical_{bounded_storage_label(label)}.metadata.json"
    relative = logical_path.relative_to(run_dir).as_posix()
    assert cursor.logical_paths_used is not None
    if relative in cursor.logical_paths_used:
        raise ValueError("logical call metadata was consumed twice")
    logical = _strict_object(logical_path)
    if set(logical) != LOGICAL_KEYS or logical.get("logical_label") != label:
        raise ValueError("logical call metadata shape or label differs")
    wire = canonical_json_bytes(body)
    wire_hash = _sha_bytes(wire)
    attempts = logical.get("attempts")
    if (
        logical.get("logical_request_id") != _sha_text(f"{label}:{wire_hash}")[:24]
        or logical.get("request_wire_sha256") != wire_hash
        or logical.get("request_wire_bytes") != len(wire)
        or not isinstance(attempts, list)
        or not 1 <= len(attempts) <= protocol.base.MAX_ATTEMPTS_PER_LOGICAL_REQUEST
        or type(logical.get("attempt_count")) is not int
        or logical.get("attempt_count") != len(attempts)
        or type(logical.get("selected_attempt")) is not int
        or logical.get("selected_attempt") != len(attempts)
        or logical.get("retry_rule") != RETRY_RULE
        or logical.get("planned_backoff_seconds") != list(protocol.base.RETRY_BACKOFF_SECONDS)
        or logical.get("actual_backoff_seconds") != list(protocol.base.RETRY_BACKOFF_SECONDS[:len(attempts)-1])
        or logical.get("request_target") != _request_target()
        or logical.get("first_attempt_http_status") != cursor.records[cursor.next_call_number - 1].get("http_status")
        or logical.get("first_attempt_transport_error") != cursor.records[cursor.next_call_number - 1].get("transport_error")
        or _safe_call(logical) != call
    ):
        raise ValueError("logical call is not bound to semantic request")
    numbers = list(range(cursor.next_call_number, cursor.next_call_number + len(attempts)))
    if numbers[-1] > len(cursor.records):
        raise ValueError("logical call span exceeds raw index")
    for position, attempt in enumerate(attempts, start=1):
        raw = cursor.records[numbers[position - 1] - 1]
        if not isinstance(attempt, dict) or set(attempt) != LOGICAL_ATTEMPT_KEYS:
            raise ValueError("logical attempt shape differs")
        if (
            type(attempt.get("call_number")) is not int
            or attempt.get("call_number") != numbers[position - 1]
            or type(attempt.get("attempt_index")) is not int
            or attempt.get("attempt_index") != position
            or attempt.get("previous_physical_call_number") != (numbers[position-2] if position > 1 else None)
            or attempt.get("selected_for_logical_result") is not (position == len(attempts))
            or any(attempt.get(key) != raw.get(key) for key in CALL_INDEX_KEYS)
            or attempt.get("retryable_reason") != (_retryable(raw) or None)
            or raw.get("label") != f"{label}_attempt{position}"
            or (run_dir / str(raw["raw_request_path"])).read_bytes() != wire
        ):
            raise ValueError("logical attempt differs from raw call")
        if position < len(attempts) and not _retryable(raw):
            raise ValueError("nonretryable response was retried")
    selected_number = numbers[-1]
    if logical.get("selected_physical_call_number") != selected_number:
        raise ValueError("logical selection differs from attempt span")
    selected = cursor.records[selected_number - 1]
    final_retry = _retryable(selected)
    reason = "retry_budget_exhausted" if final_retry else ("first_attempt_nonretryable" if len(attempts) == 1 else "first_nonretryable_after_retry")
    if (
        (final_retry and len(attempts) != protocol.base.MAX_ATTEMPTS_PER_LOGICAL_REQUEST)
        or logical.get("selection_reason") != reason
        or logical.get("selected_response_wire_sha256") != selected.get("response_wire_sha256")
        or logical.get("retried") is not (len(attempts) > 1)
    ):
        raise ValueError("logical selection semantics differ")
    logical_start = _utc(logical.get("started_at"), label="logical call start")
    logical_end = _utc(logical.get("completed_at"), label="logical call completion")
    if logical_start > _utc(cursor.records[numbers[0]-1]["started_at"], label="raw start") or _utc(selected["completed_at"], label="raw completion") > logical_end:
        raise ValueError("logical and physical call timestamps differ")
    response_bytes = (run_dir / str(selected["raw_response_path"])).read_bytes()
    transport_error = str(selected.get("transport_error") or "")
    if transport_error:
        raw_body = response_bytes.decode("utf-8", errors="replace")
        payload = None
        if selected.get("response_parse_error"):
            raise ValueError("transport-error parse state is inconsistent")
    else:
        raw_body, payload, parse_error = decode_generate_content_bytes(response_bytes)
        if parse_error != str(selected.get("response_parse_error") or ""):
            raise ValueError("response parse state differs")
    cursor.next_call_number += len(attempts)
    cursor.logical_paths_used.add(relative)
    return GenerateContentHttpResult(
        http_status=selected.get("http_status"), payload=payload,
        raw_body=raw_body, transport_error=transport_error,
        response_parse_error=str(selected.get("response_parse_error") or ""),
        elapsed_ms=int(selected.get("elapsed_ms") or 0), raw_body_bytes=response_bytes,
        response_headers=copy.deepcopy(selected.get("response_headers") or {}),
    )


def _load_round_runtime(run_dir: Path, checkpoint: str) -> RoundRuntime:
    prefix = checkpoint.lower()
    private = _strict_object(run_dir / f"{prefix}_planning.private.json")
    summary = _strict_object(run_dir / f"{prefix}_planning_summary.json")
    if set(private) != {
        "schema_version", "checkpoint", "terminal", "last_turn_classification",
        "ready_checkpoint_id", "checkpoints",
    } or private.get("schema_version") != "modernization_iterative_planning_private_v1":
        raise ValueError("private planning bundle shape differs")
    if private.get("checkpoint") != checkpoint or summary.get("checkpoint") != checkpoint:
        raise ValueError("planning checkpoint identity differs")
    checkpoints: list[CheckpointRuntime] = []
    rows = private.get("checkpoints")
    if not isinstance(rows, list):
        raise ValueError("private checkpoint list is invalid")
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) != {
                "checkpoint_id", "checkpoint", "turn_number",
                "readiness_observation", "provider_status", "full_history",
                "response_steps", "summary",
            }
            or row.get("checkpoint") != checkpoint
            or not is_opaque_id(row.get("checkpoint_id"))
        ):
            raise ValueError("private checkpoint record is invalid")
        checkpoints.append(CheckpointRuntime(
            row["checkpoint_id"], checkpoint, row["turn_number"],
            row["readiness_observation"], row["provider_status"],
            copy.deepcopy(row["full_history"]), copy.deepcopy(row["response_steps"]),
            copy.deepcopy(row["summary"]),
        ))
    ready_id = private.get("ready_checkpoint_id")
    ready = next((item for item in checkpoints if item.checkpoint_id == ready_id), None)
    if (ready_id is None) != (ready is None):
        raise ValueError("READY checkpoint reference differs")
    return RoundRuntime(
        checkpoint, checkpoints, ready, str(private.get("terminal")),
        private.get("last_turn_classification"), summary,
    )


def _verify_round(
    *, run_dir: Path, definition: dict[str, Any], freeze_id: str,
    checkpoint: str, cursor: CallCursor, parent: CheckpointRuntime | None,
    intervention_id: str | None,
) -> RoundRuntime:
    prefix = checkpoint.lower()
    round_start_call = cursor.next_call_number
    claim_path = run_dir / f"{prefix}_claim.json"
    claim = _strict_object(claim_path)
    terminal = _strict_object(run_dir / f"{prefix}_terminal.json")
    seal_path = run_dir / f"{prefix}_stage_seal.json"
    seal = _strict_object(seal_path)
    if set(claim) != {"schema_version", "freeze_id", "claim_id", "kind", "claimed_at", "status", "bindings"}:
        raise ValueError("round claim shape differs")
    if (
        claim.get("schema_version") != "modernization_iterative_round_claim_v1"
        or claim.get("freeze_id") != freeze_id or claim.get("kind") != checkpoint
        or claim.get("status") != "CLAIMED" or not is_opaque_id(claim.get("claim_id"))
        or terminal.get("claim_id") != claim.get("claim_id")
    ):
        raise ValueError("round claim/terminal binding differs")
    if terminal.get("claim_bytes_sha256") != _sha_bytes(claim_path.read_bytes()) or terminal.get("sealed_bytes_sha256") != _sha_bytes(seal_path.read_bytes()):
        raise ValueError("round terminal byte binding differs")
    attempts = _strict_list(run_dir / f"{prefix}_planning_attempts.json")
    runtime = _load_round_runtime(run_dir, checkpoint)
    history = copy.deepcopy(parent.full_history) if parent else []
    if checkpoint == "C0":
        first = protocol.initial_planning_body(task_text=definition["dossier"]["assembled_task_text"])
        expected_claim_bindings = {"task_sha256": definition["dossier"]["assembled_task_sha256"]}
    else:
        if parent is None or intervention_id is None:
            raise ValueError("adjusted round lacks its exact parent")
        record = _strict_object(run_dir / f"{intervention_id.lower()}/intervention.json")
        source_checkpoint = str(protocol.INTERVENTION_SPECS[intervention_id]["source_checkpoint"])
        source_hash = _sha_bytes((run_dir / f"{source_checkpoint.lower()}_observations.json").read_bytes())
        first = protocol.intervention_body(
            parent_ready_history=parent.full_history,
            intervention_id=intervention_id, sealed_record=record,
            source_observation_sha256=source_hash,
        )
        expected_claim_bindings = {
            "parent_checkpoint_id": parent.checkpoint_id,
            "parent_full_history_sha256": _sha_json(parent.full_history),
            "intervention_lock_bytes_sha256": _sha_bytes((run_dir / f"{intervention_id.lower()}/lock.json").read_bytes()),
        }
    if claim.get("bindings") != expected_claim_bindings:
        raise ValueError("round claim prerequisite bindings differ")
    reconstructed: list[CheckpointRuntime] = []
    ready: CheckpointRuntime | None = None
    last_evaluated: PlanningTurnEvaluation | None = None
    for turn, recorded in enumerate(attempts, start=1):
        if not isinstance(recorded, dict):
            raise ValueError("planning attempt is not an object")
        body = first if turn == 1 else protocol.planning_continuation_body(
            full_history=history, checkpoint=checkpoint, turn_number=turn,
        )
        result = _bound_result(
            run_dir=run_dir, call=recorded.get("call"),
            label=f"{prefix}_planning_turn_{turn}", body=body, cursor=cursor,
        )
        evaluated = evaluate_planning_turn(result)
        last_evaluated = evaluated
        expected_summary = {
            "turn_number": turn, "provider_status": evaluated.provider_status,
            "explicit_finish_reasons": evaluated.explicit_finish_reasons,
            "readiness_observation": evaluated.readiness_observation,
            "controller_action": evaluated.controller_action,
            "carrier_replayable": evaluated.carrier_replayable,
            "reasons": evaluated.reasons, "safe_metadata": evaluated.safe_metadata,
            "call": recorded.get("call"),
            "request_contents_sha256": _sha_json(body["contents"]),
        }
        if recorded != expected_summary:
            raise ValueError("planning attempt differs from raw response classification")
        if evaluated.controller_action != ACTION_TERMINATE_TECHNICAL:
            if not evaluated.carrier_replayable:
                raise ValueError("controller continued a nonreplayable carrier")
            history = [*copy.deepcopy(body["contents"]), *copy.deepcopy(evaluated.steps)]
            if len(runtime.checkpoints) <= len(reconstructed):
                raise ValueError("replayable checkpoint is absent from private archive")
            archived = runtime.checkpoints[len(reconstructed)]
            candidate = CheckpointRuntime(
                archived.checkpoint_id, checkpoint, turn,
                str(evaluated.readiness_observation), evaluated.provider_status,
                copy.deepcopy(history), copy.deepcopy(evaluated.steps),
                copy.deepcopy(expected_summary),
            )
            if _checkpoint_private(candidate) != _checkpoint_private(archived):
                raise ValueError("private checkpoint differs from exact raw replay")
            reconstructed.append(candidate)
            if evaluated.controller_action == ACTION_FREEZE_READY:
                ready = candidate
        elif turn != len(attempts):
            raise ValueError("planning continued after a technical terminal")
    if len(reconstructed) != len(runtime.checkpoints):
        raise ValueError("private checkpoint count differs from raw replay")
    if len({item.checkpoint_id for item in reconstructed}) != len(reconstructed):
        raise ValueError("private checkpoint identifiers are not unique")
    if (ready.checkpoint_id if ready else None) != (runtime.ready_checkpoint.checkpoint_id if runtime.ready_checkpoint else None):
        raise ValueError("READY selection differs from raw replay")
    if last_evaluated is None:
        raise ValueError("planning archive contains no attempted turn")
    if ready is not None:
        planning_terminal = "READY_CHECKPOINT_OBSERVED"
    elif last_evaluated.controller_action == ACTION_TERMINATE_TECHNICAL:
        planning_terminal = "PLANNING_TERMINATED_TECHNICAL"
    elif len(attempts) == protocol.MAX_PLANNING_TURNS_PER_CHECKPOINT:
        planning_terminal = protocol.PLANNING_THRESHOLD_REACHED
    else:
        raise ValueError("planning stopped before a registered terminal")
    expected_public_summary = {
        "schema_version": "modernization_iterative_planning_summary_v1",
        "checkpoint": checkpoint, "terminal": planning_terminal,
        "last_turn_classification": last_evaluated.readiness_observation,
        "turns_attempted": len(attempts),
        "checkpoint_count": len(reconstructed),
        "ready_checkpoint_id": ready.checkpoint_id if ready else None,
        "checkpoint_rows": [
            {
                "checkpoint_id": item.checkpoint_id,
                "turn_number": item.turn_number,
                "readiness_observation": item.readiness_observation,
                "provider_status": item.provider_status,
                "full_history_sha256": _sha_json(item.full_history),
                "response_steps_sha256": _sha_json(item.response_steps),
            }
            for item in reconstructed
        ],
    }
    if runtime.terminal != planning_terminal or runtime.last_turn_classification != last_evaluated.readiness_observation or runtime.public_summary != expected_public_summary:
        raise ValueError("planning private/public terminal summary differs from raw replay")
    private_obs = _strict_object(run_dir / f"{prefix}_observations.private.json")
    public_obs = _strict_object(run_dir / f"{prefix}_observations.json")
    private_rows = private_obs.get("rows")
    public_rows = public_obs.get("rows")
    if (
        private_obs.get("schema_version") != "modernization_iterative_observations_private_v1"
        or private_obs.get("checkpoint") != checkpoint
        or public_obs.get("schema_version") != "modernization_iterative_observations_v1"
        or public_obs.get("checkpoint") != checkpoint
        or public_obs.get("observation") != protocol.CHECKPOINT_TO_OBSERVATION[checkpoint]
    ):
        raise ValueError("tomography bundle identity differs")
    if not isinstance(private_rows, list) or not isinstance(public_rows, list) or len(private_rows) != len(reconstructed) or len(public_rows) != len(reconstructed):
        raise ValueError("tomography row count differs")
    for item, private_row, public_row in zip(reconstructed, private_rows, public_rows, strict=True):
        if not isinstance(private_row, dict) or not isinstance(public_row, dict):
            raise ValueError("tomography row is invalid")
        body = protocol.inspection_body(response_steps=item.response_steps, checkpoint=checkpoint)
        label = f"{prefix}_inspection_turn_{item.turn_number}_{item.checkpoint_id}"
        result = _bound_result(
            run_dir=run_dir, call=private_row.get("call"), label=label,
            body=body, cursor=cursor,
        )
        measured = _evaluate_prose_result(result)
        expected = {
            "checkpoint_id": item.checkpoint_id, "turn_number": item.turn_number,
            "readiness_observation": item.readiness_observation,
            "status": measured["status"], "text": measured["text"],
            "steps": measured["steps"], "reasons": measured["reasons"],
            "safe_metadata": measured["safe_metadata"], "call": private_row.get("call"),
            "request_contents_sha256": _sha_json(body["contents"]),
        }
        if private_row != expected or public_row != {key: value for key, value in expected.items() if key != "steps"}:
            raise ValueError("tomography artifact differs from raw response")
    observation_seal = _strict_object(run_dir / f"{prefix}_observation_seal.json")
    primary = next((row for row in public_rows if runtime.ready_checkpoint and row.get("checkpoint_id") == runtime.ready_checkpoint.checkpoint_id), None)
    expected_eligible = bool(primary and primary.get("status") == OBSERVED)
    combined_terminal = "OBSERVATION_MEASUREMENT_INCOMPLETE" if ready and not expected_eligible else planning_terminal
    if (
        set(observation_seal) != {
            "schema_version", "checkpoint", "observation", "ready_checkpoint_id",
            "eligible", "primary_observation_sha256", "observations_bytes_sha256",
            "sealed_at",
        }
        or
        observation_seal.get("schema_version") != "modernization_iterative_observation_seal_v1"
        or
        observation_seal.get("checkpoint") != checkpoint
        or observation_seal.get("observation") != protocol.CHECKPOINT_TO_OBSERVATION[checkpoint]
        or observation_seal.get("ready_checkpoint_id") != (runtime.ready_checkpoint.checkpoint_id if runtime.ready_checkpoint else None)
        or observation_seal.get("eligible") is not expected_eligible
        or observation_seal.get("primary_observation_sha256") != (_sha_json(primary) if primary else None)
        or observation_seal.get("observations_bytes_sha256") != _sha_bytes((run_dir / f"{prefix}_observations.json").read_bytes())
    ):
        raise ValueError("observation seal differs from reconstructed tomography")
    review_runtime = copy.copy(runtime)
    review_runtime.terminal = combined_terminal
    expected_review = _review_text(review_runtime, public_rows, observation_seal)
    if (run_dir / f"{prefix}_review.md").read_text(encoding="utf-8") != expected_review:
        raise ValueError("checkpoint review projection differs from reconstructed tomography")
    gate_id = {"C0": "I1", "C1": "I2", "C2": "I3"}.get(checkpoint)
    if expected_eligible and gate_id:
        expected_packet = _examiner_packet_text(
            run_dir=run_dir, definition=definition, checkpoint=checkpoint,
            public_rows=public_rows, observation_seal=observation_seal,
            intervention_id=gate_id,
        )
        if (run_dir / f"{gate_id.lower()}/examiner_packet.md").read_text(encoding="utf-8") != expected_packet:
            raise ValueError("examiner packet differs from its safe cumulative derivation")
    if expected_eligible and checkpoint == "C3":
        expected_assessment_packet = _o3_assessment_packet_text(
            run_dir=run_dir, public_rows=public_rows,
            observation_seal=observation_seal,
        )
        if (run_dir / "o3_assessment_packet.md").read_text(encoding="utf-8") != expected_assessment_packet:
            raise ValueError("O3 assessment packet differs from its safe derivation")
    expected_seal_keys = {
        "schema_version", "freeze_id", "checkpoint", "created_at", "task_sha256",
        "claim_id", "claim_bytes_sha256", "previous_stage_seal_bytes_sha256",
        "intervention_lock_bytes_sha256", "parent_checkpoint_id",
        "parent_full_history_sha256", "round_terminal", "ready_checkpoint_id",
        "ready_full_history_sha256", "ready_observation_eligible",
        "observation_seal_bytes_sha256", "raw_call_count", "raw_prefix_sha256",
        "raw_prefix_bytes_sha256", "raw_inventory", "artifact_inventory", "next_gate",
    }
    if set(seal) != expected_seal_keys:
        raise ValueError("stage seal shape differs")
    if seal.get("schema_version") != "modernization_iterative_stage_seal_v1" or seal.get("freeze_id") != freeze_id or seal.get("checkpoint") != checkpoint:
        raise ValueError("stage seal identity differs")
    if seal.get("task_sha256") != definition["dossier"]["assembled_task_sha256"]:
        raise ValueError("stage seal task binding differs")
    if seal.get("raw_call_count") != cursor.next_call_number - 1:
        raise ValueError("stage raw prefix count differs")
    prior_index = protocol.CHECKPOINTS.index(checkpoint) - 1
    previous_seal_path = run_dir / f"{protocol.CHECKPOINTS[prior_index].lower()}_stage_seal.json" if prior_index >= 0 else None
    expected_lock_path = run_dir / f"{intervention_id.lower()}/lock.json" if intervention_id else None
    expected_next_gate = (
        (gate_id or "O3_ASSESSMENT") if expected_eligible else None
    )
    if (
        seal.get("claim_id") != claim.get("claim_id")
        or seal.get("claim_bytes_sha256") != _sha_bytes(claim_path.read_bytes())
        or seal.get("previous_stage_seal_bytes_sha256") != (_sha_bytes(previous_seal_path.read_bytes()) if previous_seal_path else None)
        or seal.get("intervention_lock_bytes_sha256") != (_sha_bytes(expected_lock_path.read_bytes()) if expected_lock_path else None)
        or seal.get("parent_checkpoint_id") != (parent.checkpoint_id if parent else None)
        or seal.get("parent_full_history_sha256") != (_sha_json(parent.full_history) if parent else None)
        or seal.get("round_terminal") != combined_terminal
        or seal.get("ready_checkpoint_id") != (ready.checkpoint_id if ready else None)
        or seal.get("ready_full_history_sha256") != (_sha_json(ready.full_history) if ready else None)
        or seal.get("ready_observation_eligible") is not expected_eligible
        or seal.get("observation_seal_bytes_sha256") != _sha_bytes((run_dir / f"{prefix}_observation_seal.json").read_bytes())
        or seal.get("next_gate") != expected_next_gate
    ):
        raise ValueError("stage seal semantic binding differs")
    prefix_records = _strict_list(run_dir / f"{prefix}_raw_prefix.json")
    if prefix_records != cursor.records[:cursor.next_call_number - 1] or seal.get("raw_prefix_sha256") != _sha_json(prefix_records):
        raise ValueError("stage raw prefix differs")
    if seal.get("raw_prefix_bytes_sha256") != _sha_bytes((run_dir / f"{prefix}_raw_prefix.json").read_bytes()):
        raise ValueError("stage raw-prefix byte binding differs")
    _verify_inventory(run_dir, seal.get("artifact_inventory"))
    current_raw = _raw_inventory(run_dir)
    sealed_raw = seal.get("raw_inventory")
    if not isinstance(sealed_raw, dict) or any(current_raw.get(path) != record for path, record in sealed_raw.items()):
        raise ValueError("stage raw inventory changed")
    claim_at = _utc(claim.get("claimed_at"), label="round claim")
    observation_at = _utc(observation_seal.get("sealed_at"), label="observation seal")
    seal_at = _utc(seal.get("created_at"), label="round seal")
    terminal_at = _utc(terminal.get("terminal_at"), label="round terminal")
    first_raw_at = _utc(cursor.records[round_start_call - 1].get("started_at"), label="first round call")
    last_raw_at = _utc(cursor.records[cursor.next_call_number - 2].get("completed_at"), label="last round call")
    if claim_at > first_raw_at or last_raw_at > observation_at or observation_at > seal_at or seal_at > terminal_at:
        raise ValueError("round claim/seal/terminal timestamps are out of order")
    if terminal.get("status") != ("COMPLETED" if expected_eligible else combined_terminal):
        raise ValueError("round terminal status differs")
    if (
        set(terminal) != {
            "schema_version", "freeze_id", "claim_id", "claim_bytes_sha256",
            "status", "terminal_at", "error_type", "sealed_path",
            "sealed_bytes_sha256",
        }
        or terminal.get("schema_version") != "modernization_iterative_round_terminal_v1"
        or terminal.get("freeze_id") != freeze_id
        or terminal.get("error_type") is not None
        or terminal.get("sealed_path") != f"{prefix}_stage_seal.json"
    ):
        raise ValueError("round terminal shape differs")
    if intervention_id:
        prior_gate_terminal = _strict_object(run_dir / f"{intervention_id.lower()}/disposition_terminal.json")
        if _utc(prior_gate_terminal.get("terminal_at"), label="prior gate terminal") > claim_at:
            raise ValueError("round was claimed before its intervention gate closed")
    return runtime


def _verify_gate(run_dir: Path, *, freeze_id: str, intervention_id: str, source_runtime: RoundRuntime) -> str:
    gate = run_dir / intervention_id.lower()
    claim_path = gate / "disposition_claim.json"
    claim = _strict_object(claim_path)
    disposition = _strict_object(gate / "disposition.json")
    terminal = _strict_object(gate / "disposition_terminal.json")
    packet_path = gate / "examiner_packet.md"
    packet_hash = _sha_bytes(packet_path.read_bytes())
    source_stage_path = run_dir / f"{source_runtime.checkpoint.lower()}_stage_seal.json"
    expected_claim_bindings = {
        "source_stage_seal_bytes_sha256": _sha_bytes(source_stage_path.read_bytes()),
        "examiner_packet_bytes_sha256": packet_hash,
    }
    if set(claim) != {"schema_version", "freeze_id", "claim_id", "kind", "claimed_at", "status", "bindings"}:
        raise ValueError("gate claim shape differs")
    if (
        claim.get("schema_version") != "modernization_iterative_disposition_claim_v1"
        or claim.get("freeze_id") != freeze_id
        or claim.get("kind") not in {"SEALED_INTERVENTION", "NO_VALID_TARGET"}
        or claim.get("status") != "CLAIMED" or not is_opaque_id(claim.get("claim_id"))
        or claim.get("bindings") != expected_claim_bindings
        or terminal.get("claim_id") != claim.get("claim_id")
        or disposition.get("claim_id") != claim.get("claim_id")
    ):
        raise ValueError("gate claim/disposition/terminal binding differs")
    if terminal.get("claim_bytes_sha256") != _sha_bytes(claim_path.read_bytes()):
        raise ValueError("gate terminal does not bind claim bytes")
    source_observations = run_dir / f"{source_runtime.checkpoint.lower()}_observations.json"
    source_hash = _sha_bytes(source_observations.read_bytes())
    if disposition.get("source_observations_bytes_sha256") != source_hash or disposition.get("examiner_packet_bytes_sha256") != packet_hash:
        raise ValueError("gate source observation or review packet binding differs")
    participants = _strict_object(gate / "participants.json")
    expected_participants = {
        "schema_version": "modernization_iterative_review_participants_v1",
        "intervention_id": intervention_id,
        "examiner_packet_bytes_sha256": packet_hash,
        "reviewer_A": protocol.REVIEWER_PROVENANCE_REQUIREMENTS["reviewer_A"],
        "reviewer_B": protocol.REVIEWER_PROVENANCE_REQUIREMENTS["reviewer_B"],
        "codex_is_not_an_examiner": True,
    }
    if participants != expected_participants:
        raise ValueError("review participant/provenance declaration differs")
    draft, expected_adjudication, review_meta = _review_bundle(
        gate, intervention_id=intervention_id, packet_hash=packet_hash,
    )
    provenance_path = gate / "review_provenance.json"
    adjudication_path = gate / "semantic_adjudication.json"
    if _strict_object(provenance_path) != review_meta["provenance"]:
        raise ValueError("sealed review provenance differs from source files")
    if _strict_object(adjudication_path) != expected_adjudication:
        raise ValueError("sealed semantic adjudication differs from reconciliation")
    expected_review_bundle_hash = _sha_json({
        "examiner": review_meta["provenance"]["examiner_output_bytes_sha256"],
        "researcher": review_meta["provenance"]["researcher_review_bytes_sha256"],
        "reconciliation": review_meta["provenance"]["reconciliation_bytes_sha256"],
    })
    if (
        disposition.get("examiner_output_bytes_sha256") != review_meta["provenance"]["examiner_output_bytes_sha256"]
        or disposition.get("researcher_review_bytes_sha256") != review_meta["provenance"]["researcher_review_bytes_sha256"]
        or disposition.get("reconciliation_bytes_sha256") != review_meta["provenance"]["reconciliation_bytes_sha256"]
        or disposition.get("review_provenance_bytes_sha256") != _sha_bytes(provenance_path.read_bytes())
        or disposition.get("semantic_adjudication_bytes_sha256") != _sha_bytes(adjudication_path.read_bytes())
        or disposition.get("review_bundle_sha256") != expected_review_bundle_hash
    ):
        raise ValueError("gate review-file byte bindings differ")
    kind = disposition.get("disposition")
    if kind == "SEALED_INTERVENTION":
        record_path = gate / "intervention.json"
        record = protocol.validate_human_intervention_record(
            _strict_object(record_path), intervention_id=intervention_id,
            expected_observation_sha256=source_hash,
        )
        lock_path = gate / "lock.json"
        lock = _strict_object(lock_path)
        expected_lock = {
            "schema_version": "modernization_iterative_intervention_lock_v1",
            "freeze_id": freeze_id, "intervention_id": intervention_id,
            "created_at": lock.get("created_at"),
            "source_stage_seal_bytes_sha256": _sha_bytes(source_stage_path.read_bytes()),
            "source_observations_bytes_sha256": source_hash,
            "examiner_packet_bytes_sha256": packet_hash,
            "examiner_output_bytes_sha256": review_meta["provenance"]["examiner_output_bytes_sha256"],
            "researcher_review_bytes_sha256": review_meta["provenance"]["researcher_review_bytes_sha256"],
            "reconciliation_bytes_sha256": review_meta["provenance"]["reconciliation_bytes_sha256"],
            "review_bundle_sha256": expected_review_bundle_hash,
            "review_provenance_bytes_sha256": _sha_bytes(provenance_path.read_bytes()),
            "semantic_adjudication_bytes_sha256": _sha_bytes(adjudication_path.read_bytes()),
            "sealed_intervention_bytes_sha256": _sha_bytes(record_path.read_bytes()),
            "sealed_before_target_checkpoint": True,
        }
        if (
            lock != expected_lock
            or disposition.get("record_bytes_sha256") != _sha_bytes(record_path.read_bytes())
            or disposition.get("lock_bytes_sha256") != _sha_bytes(lock_path.read_bytes())
            or terminal.get("sealed_bytes_sha256") != _sha_bytes(lock_path.read_bytes())
        ):
            raise ValueError("intervention lock binding differs")
        if {key: record[key] for key in protocol.HUMAN_AUTHORED_INTERVENTION_KEYS} != draft:
            raise ValueError("sealed intervention differs from Markdown reconciliation")
        if record.get("examiner_input_sha256") != packet_hash or record.get("examiner_output_sha256") != review_meta["provenance"]["examiner_output_bytes_sha256"]:
            raise ValueError("sealed intervention examiner binding differs")
        sealed_at = _utc(record.get("sealed_at"), label="intervention seal")
        lock_at = _utc(lock.get("created_at"), label="intervention lock")
        if sealed_at != _utc(disposition.get("selected_at"), label="gate selection") or sealed_at > lock_at:
            raise ValueError("intervention was locked before it was sealed")
    elif kind == "NO_VALID_TARGET":
        record_path = gate / "no_target_record.json"
        record = _strict_object(record_path)
        expected_record = {
            "schema_version": "modernization_iterative_no_target_record_v1",
            "intervention_id": intervention_id,
            "reviewer_A": draft["reviewer_A"], "reviewer_B": draft["reviewer_B"],
            "reconciliation": draft["reconciliation"],
            "no_valid_target_basis": review_meta["no_valid_target_basis"],
            "semantic_adjudication_sha256": _sha_bytes(adjudication_path.read_bytes()),
        }
        if record != expected_record:
            raise ValueError("no-target record differs from reviewed Markdown")
        if disposition.get("record_bytes_sha256") != _sha_bytes(record_path.read_bytes()) or disposition.get("lock_bytes_sha256") is not None:
            raise ValueError("no-target disposition binding differs")
        if terminal.get("sealed_bytes_sha256") != _sha_bytes(record_path.read_bytes()):
            raise ValueError("no-target terminal binding differs")
        expected_note = str(record["no_valid_target_basis"]).strip() + "\n"
        if (gate / "no_target_note.md").read_text(encoding="utf-8") != expected_note:
            raise ValueError("no-target note differs from approved record")
    else:
        raise ValueError("gate disposition is invalid")
    if claim.get("kind") != kind:
        raise ValueError("gate claim kind differs from disposition")
    expected_disposition_keys = {
        "schema_version", "freeze_id", "intervention_id", "claim_id",
        "selected_at", "disposition", "source_observations_bytes_sha256",
        "examiner_packet_bytes_sha256", "examiner_output_bytes_sha256",
        "researcher_review_bytes_sha256", "reconciliation_bytes_sha256",
        "review_bundle_sha256", "review_provenance_bytes_sha256",
        "semantic_adjudication_bytes_sha256", "record_bytes_sha256",
        "lock_bytes_sha256",
    }
    if (
        set(disposition) != expected_disposition_keys
        or disposition.get("schema_version") != "modernization_iterative_disposition_v1"
        or disposition.get("freeze_id") != freeze_id
        or disposition.get("intervention_id") != intervention_id
    ):
        raise ValueError("gate disposition shape or identity differs")
    if (
        set(terminal) != {
            "schema_version", "freeze_id", "claim_id", "claim_bytes_sha256",
            "status", "terminal_at", "error_type", "sealed_path",
            "sealed_bytes_sha256",
        }
        or
        terminal.get("schema_version") != "modernization_iterative_disposition_terminal_v1"
        or terminal.get("freeze_id") != freeze_id
        or terminal.get("status") != "COMPLETED"
        or terminal.get("error_type") is not None
        or terminal.get("sealed_path") != (
            f"{intervention_id.lower()}/lock.json"
            if kind == "SEALED_INTERVENTION"
            else f"{intervention_id.lower()}/no_target_record.json"
        )
    ):
        raise ValueError("gate terminal shape or status differs")
    source_terminal = _strict_object(run_dir / f"{source_runtime.checkpoint.lower()}_terminal.json")
    if (
        _utc(source_terminal.get("terminal_at"), label="source terminal")
        > _utc(claim.get("claimed_at"), label="gate claim")
        or _utc(claim.get("claimed_at"), label="gate claim")
        > _utc(disposition.get("selected_at"), label="gate selection")
        or _utc(disposition.get("selected_at"), label="gate selection")
        > _utc(terminal.get("terminal_at"), label="gate terminal")
    ):
        raise ValueError("gate timestamp order is invalid")
    if kind == "SEALED_INTERVENTION" and lock_at > _utc(
        terminal.get("terminal_at"), label="gate terminal"
    ):
        raise ValueError("gate lock was created after its terminal")
    return str(kind)


def _verify_o3_assessment(run_dir: Path, *, freeze_id: str) -> dict[str, Any]:
    claim_path = run_dir / "o3_assessment_claim.json"
    record_path = run_dir / "o3_assessment.json"
    lock_path = run_dir / "o3_assessment.lock.json"
    terminal_path = run_dir / "o3_assessment_terminal.json"
    packet_path = run_dir / "o3_assessment_packet.md"
    source_path = run_dir / "o3_assessment.md"
    claim = _strict_object(claim_path)
    record = _strict_object(record_path)
    lock = _strict_object(lock_path)
    terminal = _strict_object(terminal_path)
    packet_hash = _sha_bytes(packet_path.read_bytes())
    expected_human_assessment = _parse_o3_assessment(source_path, packet_hash=packet_hash)
    expected_bindings = {
        "c3_stage_seal_bytes_sha256": _sha_bytes((run_dir / "c3_stage_seal.json").read_bytes()),
        "o3_observations_bytes_sha256": _sha_bytes((run_dir / "c3_observations.json").read_bytes()),
        "o3_observation_seal_bytes_sha256": _sha_bytes((run_dir / "c3_observation_seal.json").read_bytes()),
        "assessment_packet_bytes_sha256": packet_hash,
    }
    if (
        set(claim) != {"schema_version", "freeze_id", "claim_id", "kind", "claimed_at", "status", "bindings"}
        or claim.get("schema_version") != "modernization_iterative_o3_assessment_claim_v1"
        or claim.get("freeze_id") != freeze_id
        or claim.get("kind") != "HUMAN_O3_ASSESSMENT"
        or claim.get("status") != "CLAIMED"
        or not is_opaque_id(claim.get("claim_id"))
        or claim.get("bindings") != expected_bindings
    ):
        raise ValueError("O3 assessment claim or record binding differs")
    validated_record = protocol.validate_final_o3_assessment_record(
        record,
        expected_observation_sha256=_sha_bytes((run_dir / "c3_observations.json").read_bytes()),
    )
    if validated_record.get("assessment") != expected_human_assessment:
        raise ValueError("sealed O3 assessment differs from human source artifact")
    expected_lock = {
        "schema_version": "modernization_iterative_o3_assessment_lock_v1",
        "freeze_id": freeze_id, "created_at": lock.get("created_at"),
        "claim_id": claim["claim_id"],
        "claim_bytes_sha256": _sha_bytes(claim_path.read_bytes()),
        **expected_bindings,
        "assessment_source_bytes_sha256": _sha_bytes(source_path.read_bytes()),
        "assessment_record_bytes_sha256": _sha_bytes(record_path.read_bytes()),
        "no_X4_or_I4": True, "no_model_call": True,
    }
    if lock != expected_lock:
        raise ValueError("O3 assessment lock binding differs")
    if (
        terminal.get("schema_version") != "modernization_iterative_o3_assessment_terminal_v1"
        or terminal.get("freeze_id") != freeze_id
        or terminal.get("claim_id") != claim.get("claim_id")
        or terminal.get("claim_bytes_sha256") != _sha_bytes(claim_path.read_bytes())
        or terminal.get("sealed_bytes_sha256") != _sha_bytes(lock_path.read_bytes())
        or terminal.get("status") != "COMPLETED"
        or terminal.get("error_type") is not None
        or terminal.get("sealed_path") != "o3_assessment.lock.json"
    ):
        raise ValueError("O3 assessment terminal binding differs")
    c3_terminal = _strict_object(run_dir / "c3_terminal.json")
    if (
        _utc(c3_terminal.get("terminal_at"), label="C3 terminal")
        > _utc(claim.get("claimed_at"), label="O3 assessment claim")
        or _utc(claim.get("claimed_at"), label="O3 assessment claim")
        > _utc(record.get("sealed_at"), label="sealed O3 assessment")
        or _utc(record.get("sealed_at"), label="sealed O3 assessment")
        > _utc(lock.get("created_at"), label="O3 assessment lock")
        or _utc(lock.get("created_at"), label="O3 assessment lock")
        > _utc(terminal.get("terminal_at"), label="O3 assessment terminal")
    ):
        raise ValueError("O3 assessment timestamp order is invalid")
    if _strict_object(run_dir / "c3_observation_seal.json").get("eligible") is not True:
        raise ValueError("O3 assessment is bound to an ineligible observation")
    return record


def _verify_executions(
    *, run_dir: Path, freeze_id: str, cursor: CallCursor,
    runtimes: dict[str, RoundRuntime], definition: dict[str, Any],
) -> None:
    execution_start_call = cursor.next_call_number
    claim_path = run_dir / "execution_claim.json"
    claim = _strict_object(claim_path)
    private = _strict_object(run_dir / "executions.private.json")
    public = _strict_object(run_dir / "executions.json")
    seal_path = run_dir / "trajectory_seal.json"
    seal = _strict_object(seal_path)
    terminal = _strict_object(run_dir / "execution_terminal.json")
    expected_stage_hashes = {
        checkpoint: _sha_bytes((run_dir / f"{checkpoint.lower()}_stage_seal.json").read_bytes())
        for checkpoint in protocol.CHECKPOINTS
    }
    expected_lock_hashes = {
        intervention: _sha_bytes((run_dir / f"{intervention.lower()}/lock.json").read_bytes())
        for intervention in protocol.INTERVENTIONS
    }
    expected_o3_assessment_hash = _sha_bytes((run_dir / "o3_assessment.lock.json").read_bytes())
    if (
        set(claim) != {"schema_version", "freeze_id", "claim_id", "kind", "claimed_at", "status", "bindings"}
        or claim.get("schema_version") != "modernization_iterative_execution_claim_v1"
        or claim.get("freeze_id") != freeze_id or claim.get("kind") != "PRIMARY_EXECUTIONS"
        or claim.get("status") != "CLAIMED" or not is_opaque_id(claim.get("claim_id"))
        or claim.get("bindings") != {
            "stage_seal_bytes_sha256": expected_stage_hashes,
            "o3_assessment_lock_bytes_sha256": expected_o3_assessment_hash,
        }
    ):
        raise ValueError("execution claim shape or prerequisite binding differs")
    schedule = protocol.build_execution_schedule()
    if (
        set(private) != {"schema_version", "schedule", "rows"}
        or private.get("schema_version") != "modernization_iterative_executions_private_v1"
        or set(public) != {"schema_version", "schedule", "rows"}
        or public.get("schema_version") != "modernization_iterative_executions_v1"
        or schedule != definition["execution"]["schedule"]
        or private.get("schedule") != schedule or public.get("schedule") != schedule
    ):
        raise ValueError("execution schedule differs")
    private_rows = private.get("rows")
    public_rows = public.get("rows")
    if not isinstance(private_rows, list) or not isinstance(public_rows, list) or len(private_rows) != 12 or len(public_rows) != 12:
        raise ValueError("execution row count differs from frozen design")
    for schedule_row, private_row, public_row in zip(schedule, private_rows, public_rows, strict=True):
        checkpoint = str(schedule_row["checkpoint"])
        ready = runtimes[checkpoint].ready_checkpoint
        if ready is None:
            raise ValueError("execution source lacks READY checkpoint")
        body = protocol.execution_body(
            full_history=ready.full_history, checkpoint=checkpoint,
            replicate=int(schedule_row["replicate"]),
        )
        label = f"execution_{schedule_row['order']:02d}_{checkpoint.lower()}_replicate_{schedule_row['replicate']}"
        result = _bound_result(
            run_dir=run_dir, call=private_row.get("call"), label=label,
            body=body, cursor=cursor,
        )
        measured = _evaluate_prose_result(result)
        expected = {
            **schedule_row, "checkpoint_id": ready.checkpoint_id,
            "status": measured["status"], "text": measured["text"],
            "steps": measured["steps"], "reasons": measured["reasons"],
            "safe_metadata": measured["safe_metadata"], "call": private_row.get("call"),
            "history_sha256": _sha_json(ready.full_history),
            "request_contents_sha256": _sha_json(body["contents"]),
        }
        if private_row != expected or public_row != {key: value for key, value in expected.items() if key != "steps"}:
            raise ValueError("execution semantic row differs from raw response")
    expected_status = "COMPLETED" if all(row.get("status") == OBSERVED for row in public_rows) else "EXECUTION_MEASUREMENT_INCOMPLETE"
    expected_seal_keys = {
        "schema_version", "freeze_id", "created_at", "claim_id",
        "claim_bytes_sha256", "stage_seal_bytes_sha256",
        "o3_assessment_lock_bytes_sha256", "intervention_lock_bytes_sha256",
        "schedule", "execution_row_count", "execution_status",
        "final_call_count", "final_call_index_sha256",
        "final_call_index_bytes_sha256", "raw_inventory",
        "artifact_inventory", "neutral_lane_present",
    }
    if set(seal) != expected_seal_keys:
        raise ValueError("trajectory seal shape differs")
    if seal.get("neutral_lane_present") is not False or seal.get("execution_row_count") != 12:
        raise ValueError("trajectory includes an unregistered execution lane")
    if (
        seal.get("schema_version") != "modernization_iterative_trajectory_seal_v1"
        or seal.get("freeze_id") != freeze_id
        or seal.get("claim_id") != claim.get("claim_id")
        or seal.get("claim_bytes_sha256") != _sha_bytes(claim_path.read_bytes())
        or seal.get("stage_seal_bytes_sha256") != expected_stage_hashes
        or seal.get("o3_assessment_lock_bytes_sha256") != expected_o3_assessment_hash
        or seal.get("intervention_lock_bytes_sha256") != expected_lock_hashes
        or seal.get("schedule") != schedule
        or seal.get("execution_status") != expected_status
    ):
        raise ValueError("trajectory seal identity or prerequisite binding differs")
    if seal.get("final_call_count") != len(cursor.records) or seal.get("final_call_index_sha256") != _sha_json(cursor.records):
        raise ValueError("final call-index semantic binding differs")
    if seal.get("final_call_index_bytes_sha256") != _sha_bytes((run_dir / "raw/call_index.json").read_bytes()):
        raise ValueError("final call-index byte binding differs")
    if _strict_list(run_dir / "execution_raw_prefix.json") != cursor.records:
        raise ValueError("execution raw prefix differs")
    if seal.get("raw_inventory") != _raw_inventory(run_dir):
        raise ValueError("final raw inventory differs")
    _verify_inventory(run_dir, seal.get("artifact_inventory"))
    if terminal.get("claim_id") != claim.get("claim_id") or terminal.get("claim_bytes_sha256") != _sha_bytes(claim_path.read_bytes()) or terminal.get("sealed_bytes_sha256") != _sha_bytes(seal_path.read_bytes()):
        raise ValueError("execution claim/terminal binding differs")
    if (
        set(terminal) != {
            "schema_version", "freeze_id", "claim_id", "claim_bytes_sha256",
            "status", "terminal_at", "error_type", "sealed_path",
            "sealed_bytes_sha256",
        }
        or terminal.get("schema_version") != "modernization_iterative_execution_terminal_v1"
        or terminal.get("freeze_id") != freeze_id
        or terminal.get("status") != expected_status
        or terminal.get("error_type") is not None
        or terminal.get("sealed_path") != "trajectory_seal.json"
    ):
        raise ValueError("execution terminal status differs")
    assessment_terminal = _strict_object(run_dir / "o3_assessment_terminal.json")
    claim_at = _utc(claim.get("claimed_at"), label="execution claim")
    seal_at = _utc(seal.get("created_at"), label="trajectory seal")
    terminal_at = _utc(terminal.get("terminal_at"), label="execution terminal")
    first_execution_at = _utc(cursor.records[execution_start_call - 1].get("started_at"), label="first execution call")
    last_execution_at = _utc(cursor.records[cursor.next_call_number - 2].get("completed_at"), label="last execution call")
    if (
        _utc(assessment_terminal.get("terminal_at"), label="O3 assessment terminal")
        > claim_at or claim_at > first_execution_at
        or last_execution_at > seal_at or seal_at > terminal_at
    ):
        raise ValueError("execution timestamp order is invalid")
    logical_count = len(cursor.logical_paths_used or set())
    if not 20 <= logical_count <= 60 or len(cursor.records) > 180:
        raise ValueError("final Gemini call count is outside frozen bounds")


def _expected_nonraw_paths(run_dir: Path) -> set[str]:
    expected: set[str] = set()
    for checkpoint in protocol.CHECKPOINTS:
        prefix = checkpoint.lower()
        if (run_dir / f"{prefix}_claim.json").exists():
            expected.update(f"{prefix}_{name}" for name in CHECKPOINT_FILES)
        intervention = {"C0": "i1", "C1": "i2", "C2": "i3"}.get(checkpoint)
        if intervention and (run_dir / intervention).exists():
            expected.update(f"{intervention}/{name}" for name in INTERVENTION_COMMON_FILES)
            disposition = run_dir / intervention / "disposition.json"
            if disposition.exists():
                kind = _strict_object(disposition).get("disposition")
                family = INTERVENTION_SEALED_FILES if kind == "SEALED_INTERVENTION" else INTERVENTION_NO_TARGET_FILES
                expected.update(f"{intervention}/{name}" for name in family)
    if (run_dir / "o3_assessment_packet.md").exists():
        expected.update(O3_ASSESSMENT_PRESEAL_FILES)
    if (run_dir / "o3_assessment_claim.json").exists():
        expected.update(O3_ASSESSMENT_SEALED_FILES)
    if (run_dir / "execution_claim.json").exists():
        expected.update(EXECUTION_FILES)
    return expected


def _assert_nonraw_closure(run_dir: Path) -> None:
    actual: set[str] = set()
    directories: set[str] = set()
    for path in run_dir.rglob("*"):
        relative = path.relative_to(run_dir).as_posix()
        if relative == "raw" or relative.startswith("raw/"):
            continue
        if _is_link(path):
            raise ValueError("run archive contains a link or reparse point")
        if path.is_dir():
            directories.add(relative)
        elif path.is_file():
            actual.add(relative)
        else:
            raise ValueError("run archive contains a non-file artifact")
    expected = _expected_nonraw_paths(run_dir)
    if actual != expected:
        raise ValueError(f"run archive nonraw closure differs; missing={sorted(expected-actual)} extra={sorted(actual-expected)}")
    allowed_dirs = {"i1", "i2", "i3"} & {path.split("/")[0] for path in expected if "/" in path}
    if directories != allowed_dirs:
        raise ValueError("run archive directory closure differs")


def _assert_raw_closure(run_dir: Path, cursor: CallCursor, *, exact: bool) -> None:
    expected = {"raw/call_index.json"}
    assert cursor.logical_paths_used is not None
    expected.update(cursor.logical_paths_used)
    records = cursor.records if exact else cursor.records[:cursor.next_call_number - 1]
    for raw in records:
        request = str(raw["raw_request_path"]).replace("\\", "/")
        response = str(raw["raw_response_path"]).replace("\\", "/")
        stem = request.removesuffix(".request.json")
        expected.update({request, response, stem + ".metadata.json"})
    actual = set(_raw_inventory(run_dir, include_index=True))
    if exact and actual != expected:
        raise ValueError("raw archive contains an orphan or missing artifact")
    if not expected.issubset(actual):
        raise ValueError("verified raw prefix contains a missing artifact")


THROUGH_ORDER = {
    "c0": 0, "i1": 1, "c1": 2, "i2": 3,
    "c2": 4, "i3": 5, "c3": 6, "o3": 7, "final": 8,
}


def verify_archive(
    *, repo_root: Path, freeze_dir: Path, freeze_id: str, through: str,
) -> dict[str, Any]:
    if through not in THROUGH_ORDER:
        raise ValueError("invalid verification boundary")
    definition = _load_definition(repo_root=repo_root, freeze_dir=freeze_dir, freeze_id=freeze_id)
    run_dir = execution_output_dir(repo_root=repo_root, freeze_id=freeze_id)
    _assert_private_root(repo_root=repo_root, run_dir=run_dir)
    _assert_run_tree_has_no_links(run_dir)
    records = _validate_call_index(run_dir)
    cursor = CallCursor(records)
    runtimes: dict[str, RoundRuntime] = {}
    c0 = _verify_round(
        run_dir=run_dir, definition=definition, freeze_id=freeze_id,
        checkpoint="C0", cursor=cursor, parent=None, intervention_id=None,
    )
    runtimes["C0"] = c0
    if THROUGH_ORDER[through] >= 1:
        kind = _verify_gate(run_dir, freeze_id=freeze_id, intervention_id="I1", source_runtime=c0)
        if kind == "NO_VALID_TARGET":
            if through != "i1":
                raise ValueError("trajectory continued after I1 no-target terminal")
            _assert_nonraw_closure(run_dir)
            _assert_raw_closure(run_dir, cursor, exact=True)
            return {"valid": True, "through": through, "terminal": kind}
    if THROUGH_ORDER[through] >= 2:
        c1 = _verify_round(
            run_dir=run_dir, definition=definition, freeze_id=freeze_id,
            checkpoint="C1", cursor=cursor, parent=c0.ready_checkpoint,
            intervention_id="I1",
        )
        runtimes["C1"] = c1
    if THROUGH_ORDER[through] >= 3:
        kind = _verify_gate(run_dir, freeze_id=freeze_id, intervention_id="I2", source_runtime=runtimes["C1"])
        if kind == "NO_VALID_TARGET":
            if through != "i2":
                raise ValueError("trajectory continued after I2 no-target terminal")
            _assert_nonraw_closure(run_dir)
            _assert_raw_closure(run_dir, cursor, exact=True)
            return {"valid": True, "through": through, "terminal": kind}
    if THROUGH_ORDER[through] >= 4:
        c2 = _verify_round(
            run_dir=run_dir, definition=definition, freeze_id=freeze_id,
            checkpoint="C2", cursor=cursor, parent=runtimes["C1"].ready_checkpoint,
            intervention_id="I2",
        )
        runtimes["C2"] = c2
    if THROUGH_ORDER[through] >= 5:
        kind = _verify_gate(run_dir, freeze_id=freeze_id, intervention_id="I3", source_runtime=runtimes["C2"])
        if kind == "NO_VALID_TARGET":
            if through != "i3":
                raise ValueError("trajectory continued after I3 no-target terminal")
            _assert_nonraw_closure(run_dir)
            _assert_raw_closure(run_dir, cursor, exact=True)
            return {"valid": True, "through": through, "terminal": kind}
    if THROUGH_ORDER[through] >= 6:
        c3 = _verify_round(
            run_dir=run_dir, definition=definition, freeze_id=freeze_id,
            checkpoint="C3", cursor=cursor, parent=runtimes["C2"].ready_checkpoint,
            intervention_id="I3",
        )
        runtimes["C3"] = c3
    if THROUGH_ORDER[through] >= 7:
        _verify_o3_assessment(run_dir, freeze_id=freeze_id)
    if THROUGH_ORDER[through] >= 8:
        _verify_executions(
            run_dir=run_dir, freeze_id=freeze_id, cursor=cursor,
            runtimes=runtimes, definition=definition,
        )
    _assert_nonraw_closure(run_dir)
    # The requested boundary must also be the current terminal boundary. This
    # makes standalone stage verification fail closed against unverified suffixes.
    _assert_raw_closure(run_dir, cursor, exact=True)
    if cursor.next_call_number != len(records) + 1:
        raise ValueError("raw archive contains an unverified suffix")
    logical_actual = {
        path.relative_to(run_dir).as_posix()
        for path in (run_dir / "raw").glob("logical_*.metadata.json")
        if path.is_file()
    }
    if cursor.logical_paths_used != logical_actual:
        raise ValueError("raw archive contains orphan logical-call metadata")
    return {"valid": True, "through": through, "physical_call_count": len(records)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("run-c0", "run-c1", "run-c2", "run-c3", "run-primary-executions"):
        item = sub.add_parser(command)
        item.add_argument("--freeze-dir", type=Path, required=True)
        item.add_argument("--freeze-id", required=True)
    for command in (
        "seal-i1", "seal-i2", "seal-i3", "close-i1-no-target",
        "close-i2-no-target", "close-i3-no-target",
    ):
        item = sub.add_parser(command)
        item.add_argument("--freeze-dir", type=Path, required=True)
        item.add_argument("--freeze-id", required=True)
    assessment = sub.add_parser("seal-o3-assessment")
    assessment.add_argument("--freeze-dir", type=Path, required=True)
    assessment.add_argument("--freeze-id", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--freeze-dir", type=Path, required=True)
    verify.add_argument("--freeze-id", required=True)
    verify.add_argument("--through", choices=tuple(THROUGH_ORDER), required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    common = {"repo_root": repo_root, "freeze_dir": args.freeze_dir.resolve(), "freeze_id": args.freeze_id}
    if args.command == "verify":
        print(json.dumps(verify_archive(**common, through=args.through), sort_keys=True))
        return 0
    if args.command == "seal-o3-assessment":
        seal_o3_assessment(**common)
        return 0
    if args.command.startswith("seal-"):
        seal_intervention(**common, intervention_id=args.command[-2:].upper())
        return 0
    if args.command.startswith("close-"):
        close_no_target(**common, intervention_id=args.command.split("-")[1].upper())
        return 0
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY is required for model commands")
    if args.command == "run-primary-executions":
        run_primary_executions(**common, api_key=api_key)
    else:
        execute_checkpoint(**common, checkpoint=args.command[-2:].upper(), api_key=api_key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
