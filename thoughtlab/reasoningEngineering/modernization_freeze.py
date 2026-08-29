#!/usr/bin/env python3
"""Prepare and verify the transport-free modernization experiment freeze."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import secrets
import stat
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Final

from thoughtlab.reasoningEngineering import modernization_protocol as protocol


DEFINITION_NAME: Final[str] = "experiment_definition.json"
MANIFEST_NAME: Final[str] = "manifest.json"
PREREGISTRATION_NAME: Final[str] = "preregistration.json"
VALIDATION_REPORT_NAME: Final[str] = "validation_report.json"
LOCK_NAME: Final[str] = "freeze.lock.json"
SAFE_PAYLOAD_FILES: Final[tuple[str, ...]] = (
    DEFINITION_NAME,
    MANIFEST_NAME,
    PREREGISTRATION_NAME,
    VALIDATION_REPORT_NAME,
)
SAFE_FREEZE_FILES: Final[tuple[str, ...]] = (*SAFE_PAYLOAD_FILES, LOCK_NAME)
DEFAULT_FREEZE_RELATIVE_PATH: Final[str] = (
    "thoughtlab/reasoningEngineering/freezes/"
    "modernization_reasoning_engineering_generate_content_review_01_occurrence_04"
)

SOURCE_FILES: Final[tuple[str, ...]] = (
    ".gitignore",
    "README.md",
    "thoughtlab/__init__.py",
    "thoughtlab/gemini_generate_content.py",
    "thoughtlab/opaque_ids.py",
    "thoughtlab/raw_call_store.py",
    "thoughtlab/reasoningEngineering/__init__.py",
    "thoughtlab/reasoningEngineering/MODERNIZATION_REASONING_ENGINEERING_DESIGN.md",
    "thoughtlab/reasoningEngineering/DOSSIER_CONSTRUCTION_NOTES.md",
    "thoughtlab/reasoningEngineering/modernization_protocol.py",
    "thoughtlab/reasoningEngineering/modernization_pilot.py",
    "thoughtlab/reasoningEngineering/modernization_freeze.py",
    *(f"{protocol.DOSSIER_DIRECTORY}/{name}" for name in protocol.DOSSIER_FILES),
    "tests/test_modernization_dossier.py",
    "tests/test_modernization_protocol.py",
    "tests/test_modernization_pilot.py",
    "tests/test_modernization_freeze.py",
)

MANIFEST_SCHEMA = "modernization_reasoning_engineering_manifest_v1"
PREREGISTRATION_SCHEMA = "modernization_reasoning_engineering_preregistration_v1"
VALIDATION_SCHEMA = "modernization_reasoning_engineering_validation_v1"
LOCK_SCHEMA = "modernization_reasoning_engineering_freeze_lock_v1"
VERIFICATION_SCHEMA = "modernization_reasoning_engineering_freeze_verification_v1"

MANIFEST_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "experiment_id",
        "protocol_revision",
        "source_files",
        "source_file_count",
        "source_closure_sha256",
        "git",
    }
)
MANIFEST_SOURCE_RECORD_KEYS: Final[frozenset[str]] = frozenset(
    {"bytes", "sha256"}
)
MANIFEST_GIT_KEYS: Final[frozenset[str]] = frozenset(
    {"head", "head_error", "status_short", "status_error"}
)


class DuplicateJsonKey(ValueError):
    """Raised when strict immutable JSON contains duplicate object keys."""


def strict_json_loads(text: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DuplicateJsonKey(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> Any:
        raise ValueError(f"non-finite JSON number: {value}")

    def finite_float(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError(f"non-finite JSON number: {value}")
        return parsed

    return json.loads(
        text,
        object_pairs_hook=reject_duplicates,
        parse_constant=reject_nonfinite,
        parse_float=finite_float,
    )


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{64}", value) is not None
    )


def _is_link_or_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & reparse_flag
    )


def first_link_or_reparse_component(path: Path) -> Path | None:
    current = path.absolute()
    while True:
        if _is_link_or_reparse(current):
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _safe_source_path(repo_root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if (
        not relative
        or pure.is_absolute()
        or ".." in pure.parts
        or "\\" in relative
    ):
        raise ValueError(f"unsafe source inventory path: {relative!r}")
    root = repo_root.resolve()
    path = root.joinpath(*pure.parts)
    current = path
    while current != root:
        if _is_link_or_reparse(current):
            raise ValueError(
                f"source inventory path contains a link/reparse point: {relative}"
            )
        parent = current.parent
        if parent == current:
            raise ValueError(f"source inventory path escapes repository: {relative}")
        current = parent
    return path


def _stat_fingerprint(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _read_stable_regular_file(path: Path, *, label: str) -> bytes:
    before = path.lstat()
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if not stat.S_ISREG(before.st_mode) or bool(
        getattr(before, "st_file_attributes", 0) & reparse_flag
    ):
        raise ValueError(f"required regular file is missing or unsafe: {label}")
    data = path.read_bytes()
    after = path.lstat()
    if (
        _stat_fingerprint(before) != _stat_fingerprint(after)
        or not stat.S_ISREG(after.st_mode)
        or bool(getattr(after, "st_file_attributes", 0) & reparse_flag)
    ):
        raise ValueError(f"file changed while being read: {label}")
    return data


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    )
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


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


def _git_record(repo_root: Path) -> dict[str, Any]:
    prefix = [
        "git",
        "-c",
        f"safe.directory={repo_root.resolve()}",
        "-c",
        "core.fsmonitor=false",
        "-c",
        f"core.hooksPath={os.devnull}",
    ]

    def run(*arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*prefix, *arguments],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            env=_minimal_git_environment(),
        )

    head = run("rev-parse", "HEAD")
    status = run("status", "--short", "--untracked-files=all")
    return {
        "head": head.stdout.strip() if head.returncode == 0 else None,
        "head_error": head.stderr.strip() if head.returncode != 0 else None,
        "status_short": status.stdout.splitlines() if status.returncode == 0 else [],
        "status_error": status.stderr.strip() if status.returncode != 0 else None,
    }


def _source_file_records(repo_root: Path) -> dict[str, dict[str, Any]]:
    if len(SOURCE_FILES) != len(set(SOURCE_FILES)):
        raise ValueError("source inventory contains duplicate paths")
    records: dict[str, dict[str, Any]] = {}
    for relative in SOURCE_FILES:
        data = _read_stable_regular_file(
            _safe_source_path(repo_root, relative), label=relative
        )
        records[relative] = {
            "bytes": len(data),
            "sha256": _sha256_bytes(data),
        }
    return records


def _manifest_structure_errors(manifest: Any) -> list[str]:
    if not isinstance(manifest, dict):
        return ["manifest is not an object"]

    errors: list[str] = []
    if set(manifest) != MANIFEST_KEYS:
        errors.append("manifest keys differ from the exact schema")
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        errors.append("manifest schema differs")
    if manifest.get("experiment_id") != protocol.EXPERIMENT_ID:
        errors.append("manifest experiment ID differs")
    if manifest.get("protocol_revision") != protocol.PROTOCOL_REVISION:
        errors.append("manifest protocol revision differs")

    source_files = manifest.get("source_files")
    if not isinstance(source_files, dict):
        errors.append("manifest source_files is not an object")
    else:
        if set(source_files) != set(SOURCE_FILES):
            errors.append("manifest source-file inventory differs from allowlist")
        for relative, record in source_files.items():
            if not isinstance(record, dict):
                errors.append(f"manifest source record is not an object: {relative}")
                continue
            if set(record) != MANIFEST_SOURCE_RECORD_KEYS:
                errors.append(
                    f"manifest source record keys differ from schema: {relative}"
                )
            byte_count = record.get("bytes")
            if type(byte_count) is not int or byte_count < 0:
                errors.append(f"manifest source byte count is invalid: {relative}")
            if not _is_sha256(record.get("sha256")):
                errors.append(f"manifest source hash is invalid: {relative}")
        try:
            expected_closure = protocol.sha256_json(source_files)
        except (TypeError, ValueError, RecursionError) as exc:
            errors.append(f"manifest source closure cannot be derived: {exc}")
        else:
            if manifest.get("source_closure_sha256") != expected_closure:
                errors.append("manifest source closure hash is invalid")

    source_count = manifest.get("source_file_count")
    if type(source_count) is not int or source_count != len(SOURCE_FILES):
        errors.append("manifest source-file count differs from frozen inventory")
    if isinstance(source_files, dict) and source_count != len(source_files):
        errors.append("manifest source-file count does not match its inventory")
    if not _is_sha256(manifest.get("source_closure_sha256")):
        errors.append("manifest source closure is not a lowercase SHA-256 digest")

    git_record = manifest.get("git")
    if not isinstance(git_record, dict):
        errors.append("manifest git binding is not an object")
    else:
        if set(git_record) != MANIFEST_GIT_KEYS:
            errors.append("manifest git binding keys differ from the exact schema")
        head = git_record.get("head")
        head_error = git_record.get("head_error")
        if head is not None and (
            not isinstance(head, str)
            or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head) is None
        ):
            errors.append("manifest git head is malformed")
        if head_error is not None and not isinstance(head_error, str):
            errors.append("manifest git head error is malformed")
        if head is None and not isinstance(head_error, str):
            errors.append("manifest git binding lacks a head or head error")
        if head is not None and head_error is not None:
            errors.append("manifest git binding has both a head and head error")
        status_short = git_record.get("status_short")
        status_error = git_record.get("status_error")
        if not isinstance(status_short, list) or any(
            not isinstance(line, str) for line in status_short
        ):
            errors.append("manifest git status is malformed")
        if status_error is not None and not isinstance(status_error, str):
            errors.append("manifest git status error is malformed")
        if status_error is not None and status_short:
            errors.append("manifest git binding has status output and a status error")

    return list(dict.fromkeys(errors))


def build_manifest(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    files = _source_file_records(root)
    closure = protocol.sha256_json(files)
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "experiment_id": protocol.EXPERIMENT_ID,
        "protocol_revision": protocol.PROTOCOL_REVISION,
        "source_files": files,
        "source_file_count": len(files),
        "source_closure_sha256": closure,
        "git": _git_record(root),
    }
    errors = _manifest_structure_errors(manifest)
    if errors:
        raise ValueError("generated manifest is invalid: " + "; ".join(errors))
    return manifest


def build_preregistration(
    definition: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": PREREGISTRATION_SCHEMA,
        "experiment_id": protocol.EXPERIMENT_ID,
        "protocol_revision": protocol.PROTOCOL_REVISION,
        "model": protocol.MODEL,
        "api": protocol.API,
        "status": "prepared_unexecuted",
        "definition_canonical_sha256": protocol.sha256_json(definition),
        "manifest_canonical_sha256": protocol.sha256_json(manifest),
        "source_closure_sha256": manifest["source_closure_sha256"],
        "dossier_assembled_sha256": definition["dossier"][
            "assembled_task_sha256"
        ],
        "planning_visible_channel": "raw_text_no_schema_no_json_envelope",
        "exactly_one_candidate_required": True,
        "candidate_finish_reason_precedes_visible_parse": True,
        "stop_is_the_only_completed_finish_reason": True,
        "max_tokens_with_signed_native_content_continues_exactly": True,
        "missing_or_non_budget_finish_reason_terminates_technically": True,
        "missing_signed_native_content_terminates_technically": True,
        "live_candidate_content_is_replayed_without_mutation": True,
        "threshold_terminal": protocol.PLANNING_THRESHOLD_REACHED,
        "primary_observation_surface": (
            "isolated blank-text thoughtSignature native Content carrier"
        ),
        "isolation_mutation_status": (
            "intentional off-protocol semantic tomography"
        ),
        "phase_one_stops_before_human_intervention": True,
        "phase_two_requires_sealed_human_intervention": True,
        "all_completed_phase_one_terminals_are_integrity_verifiable": True,
        "human_disposition_is_atomically_exclusive": True,
        "baseline_and_adjusted_execution_replicates": (
            protocol.EXECUTION_REPLICATES_PER_CHECKPOINT
        ),
        "planned_calls": definition["planned_calls"],
        "raw_provider_artifacts_private": True,
        "execution_requires_exact_reviewed_freeze_id": True,
    }


def build_validation_report(
    definition: dict[str, Any], manifest: dict[str, Any], repo_root: Path
) -> dict[str, Any]:
    definition_errors = protocol.validate_experiment_definition(definition, repo_root)
    prompt_text = "\n".join(protocol.iter_all_frozen_prompt_texts(repo_root))
    return {
        "schema_version": VALIDATION_SCHEMA,
        "validated": not definition_errors,
        "definition_errors": definition_errors,
        "source_file_count": manifest["source_file_count"],
        "dossier_document_count": definition["dossier"]["document_count"],
        "withheld_notes_sent_to_model": definition["dossier"][
            "withheld_notes_sent_to_model"
        ],
        "model_facing_json_readiness_envelope_present": False,
        "response_format_or_schema_present": False,
        "function_or_tool_structure_present": False,
        "planning_status_tokens_present": all(
            token in prompt_text for token in (protocol.READY, protocol.NOT_READY)
        ),
        "neutral_continuation_exact": (
            definition["planning"]["continuation_prompt"]
            == protocol.CONTINUE_PLANNING_PROMPT
        ),
        "one_candidate_finish_reason_policy_present": (
            definition["planning"].get(
                "provider_finish_reason_precedes_visible_parse"
            )
            is True
            and definition["planning"].get(
                "missing_or_non_budget_finish_reason_is_technical"
            )
            is True
            and definition["isolation"].get("source")
            == "sole target checkpoint candidate.content only"
        ),
        "exact_native_content_replay_frozen": definition["planning"].get(
            "live_candidate_content_is_replayed_without_mutation"
        )
        is True,
        "blank_text_signature_isolation_is_off_protocol": (
            definition["isolation"].get("mutation_status")
            == "intentional off-protocol semantic tomography"
            and "blank every allowed Part text"
            in str(definition["isolation"].get("detached_carrier_mutation", ""))
        ),
        "isolation_is_primary": definition["isolation"][
            "primary_observation_surface"
        ],
        "preparation_transport_path_present": False,
        "preparation_credential_access_path_present": False,
        "raw_provider_artifacts_present": False,
        "safe_file_allowlist": list(SAFE_FREEZE_FILES),
        "source_closure_sha256": manifest["source_closure_sha256"],
    }


def _payloads(repo_root: Path) -> dict[str, Any]:
    definition = protocol.build_experiment_definition(repo_root)
    manifest = build_manifest(repo_root)
    preregistration = build_preregistration(definition, manifest)
    validation = build_validation_report(definition, manifest, repo_root)
    if not validation["validated"]:
        raise ValueError(
            "experiment definition is invalid: "
            + "; ".join(validation["definition_errors"])
        )
    return {
        DEFINITION_NAME: definition,
        MANIFEST_NAME: manifest,
        PREREGISTRATION_NAME: preregistration,
        VALIDATION_REPORT_NAME: validation,
    }


def _lock_for_payload_bytes(payload_bytes: dict[str, bytes]) -> dict[str, Any]:
    hashes = {
        name: {"bytes": len(data), "sha256": _sha256_bytes(data)}
        for name, data in sorted(payload_bytes.items())
    }
    freeze_id = protocol.sha256_json(hashes)
    return {
        "schema_version": LOCK_SCHEMA,
        "freeze_id": freeze_id,
        "safe_payload_files": list(SAFE_PAYLOAD_FILES),
        "payloads": hashes,
        "prepared_unexecuted": True,
    }


def prepare_freeze(*, repo_root: Path, freeze_dir: Path) -> dict[str, Any]:
    target = freeze_dir.absolute()
    if first_link_or_reparse_component(target) is not None:
        raise ValueError("freeze path contains a link or reparse point")
    if target.exists() and any(target.iterdir()):
        raise FileExistsError("refusing to overwrite a nonempty freeze directory")
    target.mkdir(parents=True, exist_ok=True)
    payload_values = _payloads(repo_root)
    payload_bytes = {name: _json_bytes(value) for name, value in payload_values.items()}
    lock = _lock_for_payload_bytes(payload_bytes)
    for name in SAFE_PAYLOAD_FILES:
        _atomic_write(target / name, payload_bytes[name])
    _atomic_write(target / LOCK_NAME, _json_bytes(lock))
    verification = verify_freeze(
        freeze_dir=target,
        repo_root=repo_root,
        expected_freeze_id=lock["freeze_id"],
    )
    if not verification["valid"]:
        raise ValueError(
            "new freeze failed self-verification: "
            + "; ".join(verification["errors"])
        )
    return lock


def _verify_source_manifest(
    manifest: dict[str, Any], repo_root: Path, errors: list[str]
) -> None:
    errors.extend(_manifest_structure_errors(manifest))
    expected_files = manifest.get("source_files")
    if not isinstance(expected_files, dict):
        return
    if set(expected_files) != set(SOURCE_FILES):
        return
    for relative in SOURCE_FILES:
        try:
            data = _read_stable_regular_file(
                _safe_source_path(repo_root, relative), label=relative
            )
        except (OSError, TypeError, ValueError) as exc:
            errors.append(
                f"source file unreadable or unstable: {relative}: "
                f"{type(exc).__name__}: {exc}"
            )
            continue
        record = expected_files.get(relative, {})
        if not isinstance(record, dict) or (
            record.get("bytes") != len(data)
            or record.get("sha256") != _sha256_bytes(data)
        ):
            errors.append(f"source file changed: {relative}")
    try:
        final_records = _source_file_records(repo_root)
    except (OSError, TypeError, ValueError) as exc:
        errors.append(
            "source inventory could not be re-read safely: "
            f"{type(exc).__name__}: {exc}"
        )
    else:
        if final_records != expected_files:
            errors.append("source inventory changed during verification")


def _freeze_entry_names(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.iterdir())


def _verify_freeze(
    *, freeze_dir: Path, repo_root: Path, expected_freeze_id: str | None = None
) -> dict[str, Any]:
    errors: list[str] = []
    directory = freeze_dir.absolute()
    unsafe = first_link_or_reparse_component(directory)
    if unsafe is not None:
        return {
            "schema_version": VERIFICATION_SCHEMA,
            "valid": False,
            "freeze_id": None,
            "errors": [
                f"freeze path contains a link or reparse point: {unsafe}"
            ],
            "safe_file_count": 0,
        }
    try:
        directory_metadata = directory.lstat()
    except FileNotFoundError:
        errors.append("freeze directory does not exist")
        return {
            "schema_version": VERIFICATION_SCHEMA,
            "valid": False,
            "freeze_id": None,
            "errors": errors,
            "safe_file_count": 0,
        }
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if not stat.S_ISDIR(directory_metadata.st_mode) or bool(
        getattr(directory_metadata, "st_file_attributes", 0) & reparse_flag
    ):
        errors.append("freeze path is not a safe directory")
        return {
            "schema_version": VERIFICATION_SCHEMA,
            "valid": False,
            "freeze_id": None,
            "errors": errors,
            "safe_file_count": 0,
        }
    if expected_freeze_id is not None and not _is_sha256(expected_freeze_id):
        errors.append("reviewed freeze ID is malformed")

    entries = _freeze_entry_names(directory)
    if entries != sorted(SAFE_FREEZE_FILES):
        errors.append("freeze entries differ from the exact safe allowlist")
    values: dict[str, Any] = {}
    raw: dict[str, bytes] = {}
    for name in SAFE_FREEZE_FILES:
        path = directory / name
        try:
            data = _read_stable_regular_file(path, label=name)
        except (OSError, TypeError, ValueError) as exc:
            errors.append(
                f"missing, unreadable, unsafe, or unstable freeze file: {name}: "
                f"{type(exc).__name__}: {exc}"
            )
            continue
        raw[name] = data
        try:
            values[name] = strict_json_loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            errors.append(f"invalid strict JSON in {name}: {exc}")
    lock = values.get(LOCK_NAME)
    freeze_id: str | None = None
    if isinstance(lock, dict):
        freeze_id = lock.get("freeze_id")
        if not _is_sha256(freeze_id):
            errors.append("freeze ID is malformed")
            freeze_id = None
        payload_raw = {
            name: raw[name] for name in SAFE_PAYLOAD_FILES if name in raw
        }
        if len(payload_raw) == len(SAFE_PAYLOAD_FILES):
            expected_lock = _lock_for_payload_bytes(payload_raw)
            if lock != expected_lock:
                errors.append("freeze lock does not match payload bytes")
    else:
        errors.append("freeze lock is not an object")
    if expected_freeze_id is not None and freeze_id != expected_freeze_id:
        errors.append("freeze ID does not match the reviewed ID")

    definition = values.get(DEFINITION_NAME)
    if isinstance(definition, dict):
        try:
            errors.extend(protocol.validate_experiment_definition(definition, repo_root))
        except Exception as exc:
            errors.append(
                "experiment definition validation failed safely: "
                f"{type(exc).__name__}: {exc}"
            )
    else:
        errors.append("experiment definition is not an object")
    manifest = values.get(MANIFEST_NAME)
    if isinstance(manifest, dict):
        _verify_source_manifest(manifest, repo_root, errors)
        if isinstance(definition, dict):
            if manifest.get("experiment_id") != definition.get("experiment_id"):
                errors.append("manifest experiment ID is not bound to definition")
            if manifest.get("protocol_revision") != definition.get(
                "protocol_revision"
            ):
                errors.append("manifest protocol revision is not bound to definition")
    else:
        errors.append("manifest is not an object")
    preregistration = values.get(PREREGISTRATION_NAME)
    if not isinstance(preregistration, dict) or preregistration.get(
        "schema_version"
    ) != PREREGISTRATION_SCHEMA:
        errors.append("preregistration schema differs")
    elif isinstance(definition, dict) and isinstance(manifest, dict):
        try:
            expected_preregistration = build_preregistration(definition, manifest)
        except Exception as exc:
            errors.append(
                "preregistration binding could not be derived safely: "
                f"{type(exc).__name__}: {exc}"
            )
        else:
            if preregistration != expected_preregistration:
                errors.append(
                    "preregistration differs from its bound definition and manifest"
                )
    validation = values.get(VALIDATION_REPORT_NAME)
    if not isinstance(validation, dict) or validation.get(
        "schema_version"
    ) != VALIDATION_SCHEMA:
        errors.append("validation-report schema differs")
    elif not validation.get("validated"):
        errors.append("frozen validation report is not validated")
    elif isinstance(definition, dict) and isinstance(manifest, dict):
        try:
            expected_validation = build_validation_report(
                definition, manifest, repo_root
            )
        except Exception as exc:
            errors.append(
                "validation-report binding could not be derived safely: "
                f"{type(exc).__name__}: {exc}"
            )
        else:
            if validation != expected_validation:
                errors.append("validation report differs from deterministic validation")

    if isinstance(manifest, dict) and isinstance(preregistration, dict):
        if preregistration.get("experiment_id") != manifest.get("experiment_id"):
            errors.append("preregistration experiment ID is not bound to manifest")
        if preregistration.get("protocol_revision") != manifest.get(
            "protocol_revision"
        ):
            errors.append("preregistration protocol revision is not bound to manifest")
        if preregistration.get("source_closure_sha256") != manifest.get(
            "source_closure_sha256"
        ):
            errors.append("preregistration source closure is not bound to manifest")
        if preregistration.get("manifest_canonical_sha256") != protocol.sha256_json(
            manifest
        ):
            errors.append("preregistration manifest hash binding is invalid")
    if isinstance(manifest, dict) and isinstance(validation, dict):
        if validation.get("source_file_count") != manifest.get("source_file_count"):
            errors.append("validation source count is not bound to manifest")
        if validation.get("source_closure_sha256") != manifest.get(
            "source_closure_sha256"
        ):
            errors.append("validation source closure is not bound to manifest")

    final_entries = _freeze_entry_names(directory)
    if final_entries != entries:
        errors.append("freeze directory changed during verification")
    final_directory_metadata = directory.lstat()
    if _stat_fingerprint(final_directory_metadata) != _stat_fingerprint(
        directory_metadata
    ):
        errors.append("freeze directory metadata changed during verification")
    if first_link_or_reparse_component(directory) is not None:
        errors.append("freeze path became a link or reparse point during verification")
    for name, initial_data in raw.items():
        try:
            final_data = _read_stable_regular_file(directory / name, label=name)
        except (OSError, TypeError, ValueError) as exc:
            errors.append(
                f"freeze file could not be re-read safely: {name}: "
                f"{type(exc).__name__}: {exc}"
            )
        else:
            if final_data != initial_data:
                errors.append(f"freeze file changed during verification: {name}")

    errors = list(dict.fromkeys(errors))
    return {
        "schema_version": VERIFICATION_SCHEMA,
        "valid": not errors,
        "freeze_id": freeze_id,
        "errors": errors,
        "safe_file_count": len(raw),
    }


def verify_freeze(
    *, freeze_dir: Path, repo_root: Path, expected_freeze_id: str | None = None
) -> dict[str, Any]:
    """Verify untrusted freeze state without allowing malformed input to escape."""

    try:
        return _verify_freeze(
            freeze_dir=freeze_dir,
            repo_root=repo_root,
            expected_freeze_id=expected_freeze_id,
        )
    except Exception as exc:
        return {
            "schema_version": VERIFICATION_SCHEMA,
            "valid": False,
            "freeze_id": None,
            "errors": [
                "freeze verification failed safely: "
                f"{type(exc).__name__}: {exc}"
            ],
            "safe_file_count": 0,
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--freeze-dir", type=Path)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--freeze-dir", type=Path)
    verify.add_argument("--freeze-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    freeze_dir = args.freeze_dir or repo_root / DEFAULT_FREEZE_RELATIVE_PATH
    if args.command == "prepare":
        lock = prepare_freeze(repo_root=repo_root, freeze_dir=freeze_dir)
        print(lock["freeze_id"])
        return 0
    verification = verify_freeze(
        freeze_dir=freeze_dir,
        repo_root=repo_root,
        expected_freeze_id=args.freeze_id,
    )
    print(json.dumps(verification, ensure_ascii=True, sort_keys=True, indent=2))
    return 0 if verification["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
