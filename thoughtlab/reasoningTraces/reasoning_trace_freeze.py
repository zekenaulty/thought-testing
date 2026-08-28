#!/usr/bin/env python3
"""Prepare and verify the immutable BookForge READY-trace experiment freeze.

This module is deliberately transport-free.  It constructs only deterministic
protocol metadata, validates the externally selected BookForge capsule by its
already frozen hashes, binds executable source bytes, and writes an allowlisted
review package.  It has no model client, credential lookup, or network path.
Execution belongs to :mod:`reasoning_trace_pilot` and must consume a reviewed
freeze ID.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import secrets
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Final

from thoughtlab.reasoningTraces import reasoning_trace_protocol as protocol


DEFINITION_NAME: Final[str] = "experiment_definition.json"
MANIFEST_NAME: Final[str] = "manifest.json"
PREREGISTRATION_NAME: Final[str] = "preregistration.json"
VALIDATION_REPORT_NAME: Final[str] = "validation_report.json"
SAFE_PAYLOAD_FILES: Final[tuple[str, ...]] = (
    DEFINITION_NAME,
    MANIFEST_NAME,
    PREREGISTRATION_NAME,
    VALIDATION_REPORT_NAME,
)
FREEZE_LOCK_NAME: Final[str] = "freeze.lock.json"
SAFE_FREEZE_FILES: Final[tuple[str, ...]] = (*SAFE_PAYLOAD_FILES, FREEZE_LOCK_NAME)

FORBIDDEN_RUNTIME_NAMES: Final[tuple[str, ...]] = (
    "raw",
    "call_index.json",
    "source_results.json",
    "source_results.partial.json",
    "readout_results.json",
    "readout_results.partial.json",
    "continuation_results.json",
    "continuation_results.partial.json",
    "summary.json",
    "review.md",
    "execution_ledger.json",
    "consumption_claim.json",
)

# Fixed source-byte closure for this experiment.  The selected BookForge
# capsule is intentionally *not* copied into this inventory or into the freeze:
# it is an external research input bound separately by the frozen byte hashes.
SOURCE_FILES: Final[tuple[str, ...]] = (
    ".gitignore",
    "thoughtlab/__init__.py",
    "thoughtlab/gemini_interactions.py",
    "thoughtlab/opaque_ids.py",
    "thoughtlab/stateTransitions/__init__.py",
    "thoughtlab/stateTransitions/fork_pilot.py",
    "thoughtlab/stateTransitions/probes.py",
    "thoughtlab/stateTransitions/score_ground_truth.py",
    "thoughtlab/reasoningTraces/REASONING_TRACE_READY_DESIGN.md",
    "thoughtlab/reasoningTraces/__init__.py",
    "thoughtlab/reasoningTraces/reasoning_trace_protocol.py",
    "thoughtlab/reasoningTraces/reasoning_trace_freeze.py",
    "thoughtlab/reasoningTraces/reasoning_trace_pilot.py",
    "tests/test_reasoning_trace_protocol.py",
    "tests/test_reasoning_trace_freeze.py",
    "tests/test_reasoning_trace_pilot.py",
)

MANIFEST_SCHEMA_VERSION: Final[str] = "bookforge_ready_trace_manifest_v1"
PREREGISTRATION_SCHEMA_VERSION: Final[str] = "bookforge_ready_trace_preregistration_v1"
VALIDATION_SCHEMA_VERSION: Final[str] = "bookforge_ready_trace_freeze_validation_v1"
LOCK_SCHEMA_VERSION: Final[str] = "bookforge_ready_trace_freeze_lock_v1"
VERIFICATION_SCHEMA_VERSION: Final[str] = "bookforge_ready_trace_freeze_verification_v1"
EVIDENCE_KIND: Final[str] = (
    "static_architectural_attestation_plus_hashed_regression_source"
)
NO_CALL_CLAIM: Final[str] = (
    "freeze preparation imports only the pure protocol module and contains "
    "no model transport or credential-access path; exact source and external "
    "capsule hashes are authoritative"
)

PREREGISTRATION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "experiment_id",
        "protocol_revision",
        "model",
        "experiment_definition",
        "manifest",
        "source_file_bytes_sha256",
        "source_binding",
        "selected_capsule_external_binding",
        "schedule_canonical_json_sha256",
        "planned_calls",
        "transport_policy",
        "all_readouts_sealed_before_continuation",
        "no_replacement_source_generation",
        "text_only_no_function_or_tool_structure",
        "historical_signature_or_response_sent",
        "raw_provider_artifacts_private",
        "execution_must_consume_this_exact_freeze",
    }
)
VALIDATION_REPORT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "validated",
        "definition_errors",
        "manifest_errors",
        "planned_calls",
        "evidence_kind",
        "preparation_transport_path_present",
        "preparation_credential_access_path_present",
        "raw_provider_artifacts_present",
        "selected_capsule_copied_into_freeze",
        "historical_signature_copied_into_freeze",
        "forbidden_runtime_entries",
        "safe_file_allowlist",
        "source_file_allowlist",
        "external_capsule_binding",
        "no_call_claim",
    }
)


class DuplicateJsonKey(ValueError):
    """Raised when strict freeze JSON contains a duplicate object key."""


def strict_json_loads(text: str) -> Any:
    """Load normalized JSON while rejecting ambiguity and non-finite numbers."""

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DuplicateJsonKey(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> Any:
        raise ValueError(f"non-finite JSON number: {value}")

    def parse_finite_float(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError(f"non-finite JSON number: {value}")
        return parsed

    return json.loads(
        text,
        object_pairs_hook=reject_duplicates,
        parse_constant=reject_nonfinite,
        parse_float=parse_finite_float,
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def sha256_json(value: Any) -> str:
    return sha256_bytes(protocol.canonical_json_bytes(value))


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _is_link_or_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0) & reparse_flag
    )


def first_link_or_reparse_component(path: Path) -> Path | None:
    current = path.absolute()
    while True:
        if _is_link_or_reparse_point(current):
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


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
            try:
                temporary.unlink()
            except OSError:
                pass


def _pretty_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, allow_nan=False, ensure_ascii=True, indent=2) + "\n"
    ).encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    _atomic_write(path, _pretty_json_bytes(value))


def _safe_repo_path(repo_root: Path, relative_path: str) -> Path:
    pure = PurePosixPath(relative_path)
    if (
        not relative_path
        or pure.is_absolute()
        or ".." in pure.parts
        or "\\" in relative_path
    ):
        raise ValueError(f"unsafe repository-relative path: {relative_path!r}")
    root = repo_root.resolve()
    path = root.joinpath(*pure.parts)
    current = path
    while current != root:
        if current.exists() and _is_link_or_reparse_point(current):
            raise ValueError(
                f"repository path contains a link/reparse point: {relative_path}"
            )
        parent = current.parent
        if parent == current:
            raise ValueError(f"repository path escapes root: {relative_path}")
        current = parent
    return path


def _read_stable_regular_file(path: Path, *, label: str) -> bytes:
    if not path.is_file() or _is_link_or_reparse_point(path):
        raise ValueError(f"required regular file is missing or unsafe: {label}")
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
        raise ValueError(f"file changed while being read: {label}")
    return data


def _source_hashes(repo_root: Path) -> dict[str, str]:
    if len(SOURCE_FILES) != len(set(SOURCE_FILES)):
        raise ValueError("source inventory contains duplicate paths")
    return {
        relative: sha256_bytes(
            _read_stable_regular_file(
                _safe_repo_path(repo_root, relative), label=relative
            )
        )
        for relative in SOURCE_FILES
    }


def _expected_capsule_binding() -> dict[str, Any]:
    """Return the sole hash-only description allowed in a reviewed freeze."""

    return {
        "binding_semantics": "external_exact_hashes_only_not_copied_into_freeze",
        "relative_path": protocol.CAPSULE_RELATIVE_PATH,
        "capsule_file_sha256": protocol.CAPSULE_FILE_SHA256,
        "prompt_sha256": protocol.CAPSULE_PROMPT_SHA256,
        "original_system_sha256": protocol.ORIGINAL_SYSTEM_SHA256,
        "original_user_sha256": protocol.ORIGINAL_USER_SHA256,
        "historical_visible_sha256": protocol.HISTORICAL_VISIBLE_SHA256,
        "corpus_source_commit": protocol.CORPUS_SOURCE_COMMIT,
        "raw_signature_copied_into_freeze": False,
    }


def _selected_capsule_binding(repo_root: Path) -> dict[str, Any]:
    """Verify the external capsule and return hashes only, never its contents."""

    expected_path = _safe_repo_path(repo_root, protocol.CAPSULE_RELATIVE_PATH)
    task = protocol.verify_selected_task(repo_root)
    actual_path = Path(task["path"]).resolve()
    if actual_path != expected_path.resolve():
        raise ValueError("selected capsule resolved to an unexpected path")
    return _expected_capsule_binding()


def _minimal_git_environment() -> dict[str, str]:
    """Return only benign launch variables; never enumerate the environment."""

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


def _git_snapshot(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    prefix = [
        "git",
        "-c",
        f"safe.directory={root}",
        "-c",
        "core.fsmonitor=false",
        "-c",
        f"core.hooksPath={os.devnull}",
    ]
    try:
        commit = subprocess.run(
            [*prefix, "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            env=_minimal_git_environment(),
        ).stdout.strip()
        status = subprocess.run(
            [*prefix, "status", "--short", "--", *SOURCE_FILES],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            env=_minimal_git_environment(),
        ).stdout.splitlines()
        return {
            "commit": commit,
            "relevant_tree_clean": not status,
            "relevant_status": status,
            "binding_rule": "source_file_byte_hashes_are_authoritative",
        }
    except (OSError, subprocess.CalledProcessError) as exc:
        return {
            "commit": None,
            "relevant_tree_clean": None,
            "relevant_status": [],
            "snapshot_error": f"{type(exc).__name__}: {exc}",
            "binding_rule": "source_file_byte_hashes_are_authoritative",
        }


def _freeze_entries(freeze_dir: Path) -> list[str]:
    if not freeze_dir.exists():
        return []
    return sorted(
        str(path.relative_to(freeze_dir)).replace("\\", "/")
        for path in freeze_dir.rglob("*")
    )


def _forbidden_entries(freeze_dir: Path) -> list[str]:
    return sorted(
        entry
        for entry in _freeze_entries(freeze_dir)
        if Path(entry).name in FORBIDDEN_RUNTIME_NAMES
        or entry.startswith("raw/")
        or "/raw/" in entry
    )


def create_manifest(definition: dict[str, Any]) -> dict[str, Any]:
    """Derive the sole execution manifest from a validated definition."""

    errors = protocol.validate_experiment_definition(definition)
    if errors:
        raise ValueError("invalid experiment definition: " + "; ".join(errors))
    source_task = definition["source_task"]
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "experiment_id": definition["experiment_id"],
        "protocol_revision": definition["protocol_revision"],
        "model": definition["model"],
        "api": definition["api"],
        "master_seed": definition["master_seed"],
        "definition_sha256": sha256_json(definition),
        "selected_capsule_external_hashes": {
            "capsule_file_sha256": source_task["capsule_file_sha256"],
            "prompt_sha256": source_task["prompt_sha256"],
            "original_system_sha256": source_task["original_system_sha256"],
            "original_user_sha256": source_task["original_user_sha256"],
        },
        "reasoning_boundary_sha256": sha256_json(definition["reasoning_boundary"]),
        "interrogation_sha256": sha256_json(definition["interrogation"]),
        "validation_sha256": sha256_json(definition["validation"]),
        "schedule": copy.deepcopy(definition["schedule"]),
        "planned_calls": copy.deepcopy(definition["planned_calls"]),
        "transport_policy": copy.deepcopy(definition["transport_policy"]),
    }


def validate_manifest(
    manifest: Any,
    definition: dict[str, Any] | None = None,
) -> list[str]:
    if not isinstance(manifest, dict):
        return ["manifest is not an object"]
    if not isinstance(definition, dict):
        return ["experiment definition is unavailable for manifest validation"]
    try:
        expected = create_manifest(definition)
    except (KeyError, TypeError, ValueError) as exc:
        return [f"cannot derive execution manifest: {exc}"]
    return [] if manifest == expected else [
        "manifest differs from deterministic definition-derived reconstruction"
    ]


def prepare_freeze(
    *,
    repo_root: Path,
    freeze_dir: Path,
    master_seed: int = protocol.MASTER_SEED,
    model: str = protocol.MODEL,
) -> dict[str, Any]:
    """Create a deterministic, reviewed package without transport or credentials."""

    if model != protocol.MODEL:
        raise ValueError(f"reasoning-trace protocol requires model {protocol.MODEL}")
    if master_seed != protocol.MASTER_SEED:
        raise ValueError(
            f"reasoning-trace protocol requires master seed {protocol.MASTER_SEED}"
        )
    unsafe_component = first_link_or_reparse_component(freeze_dir)
    if unsafe_component is not None:
        raise ValueError(
            f"freeze path contains a link/reparse point: {unsafe_component}"
        )
    freeze_dir = freeze_dir.resolve()
    if freeze_dir.exists() and any(freeze_dir.iterdir()):
        raise FileExistsError(
            f"refusing to overwrite nonempty freeze directory: {freeze_dir}"
        )
    freeze_dir.mkdir(parents=True, exist_ok=True)

    external_binding = _selected_capsule_binding(repo_root)
    definition = protocol.build_experiment_definition()
    definition_errors = protocol.validate_experiment_definition(definition)
    if definition_errors:
        raise ValueError(
            "experiment definition validation failed: " + "; ".join(definition_errors)
        )
    if definition.get("model") != model or definition.get("master_seed") != master_seed:
        raise ValueError("experiment definition returned different frozen parameters")
    manifest = create_manifest(definition)
    manifest_errors = validate_manifest(manifest, definition)
    if manifest_errors:
        raise ValueError("manifest validation failed: " + "; ".join(manifest_errors))

    definition_path = freeze_dir / DEFINITION_NAME
    manifest_path = freeze_dir / MANIFEST_NAME
    _write_json(definition_path, definition)
    _write_json(manifest_path, manifest)

    source_hashes = _source_hashes(repo_root)
    preregistration = {
        "schema_version": PREREGISTRATION_SCHEMA_VERSION,
        "experiment_id": definition["experiment_id"],
        "protocol_revision": definition["protocol_revision"],
        "model": model,
        "experiment_definition": {
            "canonical_json_sha256": sha256_json(definition),
            "file_bytes_sha256": sha256_bytes(definition_path.read_bytes()),
        },
        "manifest": {
            "canonical_json_sha256": sha256_json(manifest),
            "file_bytes_sha256": sha256_bytes(manifest_path.read_bytes()),
        },
        "source_file_bytes_sha256": source_hashes,
        "source_binding": _git_snapshot(repo_root),
        "selected_capsule_external_binding": external_binding,
        "schedule_canonical_json_sha256": sha256_json(definition["schedule"]),
        "planned_calls": copy.deepcopy(definition["planned_calls"]),
        "transport_policy": copy.deepcopy(definition["transport_policy"]),
        "all_readouts_sealed_before_continuation": True,
        "no_replacement_source_generation": True,
        "text_only_no_function_or_tool_structure": True,
        "historical_signature_or_response_sent": False,
        "raw_provider_artifacts_private": True,
        "execution_must_consume_this_exact_freeze": True,
    }
    preregistration_path = freeze_dir / PREREGISTRATION_NAME
    _write_json(preregistration_path, preregistration)

    validation_report = {
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "validated": True,
        "definition_errors": [],
        "manifest_errors": [],
        "planned_calls": copy.deepcopy(definition["planned_calls"]),
        "evidence_kind": EVIDENCE_KIND,
        "preparation_transport_path_present": False,
        "preparation_credential_access_path_present": False,
        "raw_provider_artifacts_present": False,
        "selected_capsule_copied_into_freeze": False,
        "historical_signature_copied_into_freeze": False,
        "forbidden_runtime_entries": [],
        "safe_file_allowlist": list(SAFE_FREEZE_FILES),
        "source_file_allowlist": list(SOURCE_FILES),
        "external_capsule_binding": copy.deepcopy(external_binding),
        "no_call_claim": NO_CALL_CLAIM,
    }
    validation_path = freeze_dir / VALIDATION_REPORT_NAME
    _write_json(validation_path, validation_report)

    lock = {
        "schema_version": LOCK_SCHEMA_VERSION,
        "hash_algorithm": "sha256",
        "file_hash_semantics": "exact_file_bytes",
        "files": {
            name: sha256_bytes((freeze_dir / name).read_bytes())
            for name in SAFE_PAYLOAD_FILES
        },
    }
    lock_path = freeze_dir / FREEZE_LOCK_NAME
    _write_json(lock_path, lock)
    freeze_id = sha256_bytes(lock_path.read_bytes())
    verification = verify_freeze(
        repo_root=repo_root,
        freeze_dir=freeze_dir,
        expected_freeze_id=freeze_id,
        verify_source=True,
    )
    if not verification["valid"]:
        raise ValueError(
            "new reasoning-trace freeze failed verification: "
            + "; ".join(verification["errors"])
        )
    return {
        "freeze_dir": str(freeze_dir),
        "freeze_id": freeze_id,
        "experiment_definition_canonical_json_sha256": sha256_json(definition),
        "manifest_canonical_json_sha256": sha256_json(manifest),
        "manifest_file_bytes_sha256": sha256_bytes(manifest_path.read_bytes()),
        "external_capsule_file_sha256": external_binding["capsule_file_sha256"],
        "valid": True,
    }


def _load_object(path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        text = _read_stable_regular_file(path, label=path.name).decode("utf-8")
        value = strict_json_loads(text)
    except (OSError, UnicodeError, TypeError, ValueError, RecursionError) as exc:
        errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{path.name}: top-level JSON is not an object")
        return None
    return value


def load_frozen_object(freeze_dir: Path, name: str) -> dict[str, Any]:
    """Load one allowlisted freeze object strictly for a verified executor."""

    if name not in SAFE_FREEZE_FILES:
        raise ValueError(f"freeze filename is not allowlisted: {name}")
    errors: list[str] = []
    value = _load_object(freeze_dir / name, errors)
    if value is None:
        raise ValueError("; ".join(errors))
    return value


def _file_sha256(path: Path, errors: list[str]) -> str | None:
    try:
        return sha256_bytes(_read_stable_regular_file(path, label=path.name))
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        errors.append(
            f"{path.name}: exact file-byte hash failed: {type(exc).__name__}: {exc}"
        )
        return None


def _verify_external_binding(repo_root: Path, recorded: Any) -> list[str]:
    if not isinstance(recorded, dict):
        return ["selected capsule external binding is not an object"]
    try:
        current = _selected_capsule_binding(repo_root)
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        return [f"selected external capsule verification failed: {type(exc).__name__}: {exc}"]
    return [] if recorded == current else ["selected external capsule binding differs from freeze"]


def _verify_freeze(
    *,
    repo_root: Path,
    freeze_dir: Path,
    expected_freeze_id: str | None = None,
    verify_source: bool = True,
) -> dict[str, Any]:
    errors: list[str] = []
    unsafe_component = first_link_or_reparse_component(freeze_dir)
    if unsafe_component is not None:
        errors.append(f"freeze path contains a link/reparse point: {unsafe_component}")
    freeze_dir = freeze_dir.resolve()
    entries = _freeze_entries(freeze_dir)
    if entries != sorted(SAFE_FREEZE_FILES):
        errors.append(f"freeze entries differ from safe allowlist: found {entries!r}")
    forbidden = _forbidden_entries(freeze_dir)
    if forbidden:
        errors.append(f"forbidden runtime entries present: {forbidden!r}")
    for name in SAFE_FREEZE_FILES:
        path = freeze_dir / name
        if path.exists() and _is_link_or_reparse_point(path):
            errors.append(f"{name}: links and reparse points are forbidden")

    lock_path = freeze_dir / FREEZE_LOCK_NAME
    freeze_id = _file_sha256(lock_path, errors)
    if expected_freeze_id is not None and freeze_id != expected_freeze_id:
        errors.append("freeze ID does not match the reviewed expected value")
    lock = _load_object(lock_path, errors) if lock_path.is_file() else None
    lock_files: dict[str, Any] | None = None
    if lock is None:
        errors.append("freeze lock is missing or invalid")
    else:
        if set(lock) != {
            "schema_version",
            "hash_algorithm",
            "file_hash_semantics",
            "files",
        }:
            errors.append("freeze lock keys differ from the exact schema")
        if lock.get("schema_version") != LOCK_SCHEMA_VERSION:
            errors.append("freeze lock schema version mismatch")
        if lock.get("hash_algorithm") != "sha256":
            errors.append("freeze lock hash algorithm mismatch")
        if lock.get("file_hash_semantics") != "exact_file_bytes":
            errors.append("freeze lock hash semantics mismatch")
        if isinstance(lock.get("files"), dict):
            lock_files = lock["files"]
    if lock_files is None or set(lock_files) != set(SAFE_PAYLOAD_FILES):
        errors.append("freeze lock file inventory is incomplete")
    else:
        for name in SAFE_PAYLOAD_FILES:
            expected_hash = lock_files.get(name)
            if not _is_sha256(expected_hash):
                errors.append(f"{name}: freeze lock hash is not a lowercase SHA-256 digest")
                continue
            if _file_sha256(freeze_dir / name, errors) != expected_hash:
                errors.append(f"{name}: exact file-byte hash mismatch")

    definition = _load_object(freeze_dir / DEFINITION_NAME, errors)
    manifest = _load_object(freeze_dir / MANIFEST_NAME, errors)
    preregistration = _load_object(freeze_dir / PREREGISTRATION_NAME, errors)
    validation = _load_object(freeze_dir / VALIDATION_REPORT_NAME, errors)

    if definition is not None:
        try:
            errors.extend(protocol.validate_experiment_definition(definition))
            protocol.assert_no_function_or_tool_structure(definition)
        except Exception as exc:
            errors.append(
                f"experiment definition validation failed safely: {type(exc).__name__}: {exc}"
            )
    if manifest is not None:
        try:
            errors.extend(validate_manifest(manifest, definition))
        except Exception as exc:
            errors.append(f"manifest validation failed safely: {type(exc).__name__}: {exc}")

    if validation is not None:
        if set(validation) != VALIDATION_REPORT_KEYS:
            errors.append("validation report keys differ from the exact schema")
        if validation.get("schema_version") != VALIDATION_SCHEMA_VERSION:
            errors.append("validation report schema version mismatch")
        if validation.get("validated") is not True:
            errors.append("validation report is not marked valid")
        if validation.get("definition_errors") != []:
            errors.append("validation report contains definition errors")
        if validation.get("manifest_errors") != []:
            errors.append("validation report contains manifest errors")
        if definition is not None and validation.get("planned_calls") != definition.get(
            "planned_calls"
        ):
            errors.append("validation report planned-call policy mismatch")
        if validation.get("evidence_kind") != EVIDENCE_KIND:
            errors.append("validation report evidence kind mismatch")
        for key in (
            "preparation_transport_path_present",
            "preparation_credential_access_path_present",
            "raw_provider_artifacts_present",
            "selected_capsule_copied_into_freeze",
            "historical_signature_copied_into_freeze",
        ):
            if validation.get(key) is not False:
                errors.append(f"validation report false assertion mismatch: {key}")
        if validation.get("safe_file_allowlist") != list(SAFE_FREEZE_FILES):
            errors.append("validation report safe-file allowlist mismatch")
        if validation.get("source_file_allowlist") != list(SOURCE_FILES):
            errors.append("validation report source-file allowlist mismatch")
        if validation.get("forbidden_runtime_entries") != []:
            errors.append("validation report records forbidden runtime entries")
        if validation.get("no_call_claim") != NO_CALL_CLAIM:
            errors.append("validation report no-call claim mismatch")

    if preregistration is not None and definition is not None and manifest is not None:
        if set(preregistration) != PREREGISTRATION_KEYS:
            errors.append("preregistration keys differ from the exact schema")
        if preregistration.get("schema_version") != PREREGISTRATION_SCHEMA_VERSION:
            errors.append("preregistration schema version mismatch")
        definition_hashes = preregistration.get("experiment_definition")
        definition_hashes = definition_hashes if isinstance(definition_hashes, dict) else {}
        manifest_hashes = preregistration.get("manifest")
        manifest_hashes = manifest_hashes if isinstance(manifest_hashes, dict) else {}
        if set(definition_hashes) != {
            "canonical_json_sha256",
            "file_bytes_sha256",
        }:
            errors.append("experiment definition hash record keys differ from exact schema")
        if set(manifest_hashes) != {
            "canonical_json_sha256",
            "file_bytes_sha256",
        }:
            errors.append("manifest hash record keys differ from exact schema")
        if preregistration.get("experiment_id") != definition.get("experiment_id"):
            errors.append("preregistration experiment ID mismatch")
        if preregistration.get("protocol_revision") != definition.get("protocol_revision"):
            errors.append("preregistration protocol revision mismatch")
        if preregistration.get("model") != protocol.MODEL:
            errors.append("preregistration model mismatch")
        if definition_hashes.get("canonical_json_sha256") != sha256_json(definition):
            errors.append("experiment definition canonical JSON hash mismatch")
        if definition_hashes.get("file_bytes_sha256") != _file_sha256(
            freeze_dir / DEFINITION_NAME, errors
        ):
            errors.append("experiment definition recorded file-byte hash mismatch")
        if manifest_hashes.get("canonical_json_sha256") != sha256_json(manifest):
            errors.append("manifest canonical JSON hash mismatch")
        if manifest_hashes.get("file_bytes_sha256") != _file_sha256(
            freeze_dir / MANIFEST_NAME, errors
        ):
            errors.append("manifest recorded file-byte hash mismatch")
        if preregistration.get("schedule_canonical_json_sha256") != sha256_json(
            definition["schedule"]
        ):
            errors.append("schedule hash mismatch")
        if preregistration.get("planned_calls") != definition.get("planned_calls"):
            errors.append("preregistration planned-call policy mismatch")
        if preregistration.get("transport_policy") != definition.get("transport_policy"):
            errors.append("preregistration transport policy mismatch")
        for key, expected in (
            ("all_readouts_sealed_before_continuation", True),
            ("no_replacement_source_generation", True),
            ("text_only_no_function_or_tool_structure", True),
            ("historical_signature_or_response_sent", False),
            ("raw_provider_artifacts_private", True),
            ("execution_must_consume_this_exact_freeze", True),
        ):
            if preregistration.get(key) is not expected:
                errors.append(f"preregistration assertion mismatch: {key}")

        recorded_source_hashes = preregistration.get("source_file_bytes_sha256")
        if not isinstance(recorded_source_hashes, dict) or set(recorded_source_hashes) != set(SOURCE_FILES):
            errors.append("preregistration source-file inventory mismatch")
        elif any(not _is_sha256(value) for value in recorded_source_hashes.values()):
            errors.append("preregistration contains an invalid source-file hash")

        external_binding = preregistration.get("selected_capsule_external_binding")
        if validation is not None and validation.get("external_capsule_binding") != external_binding:
            errors.append("validation report external capsule binding mismatch")
        if external_binding != _expected_capsule_binding():
            errors.append("selected capsule external binding differs from exact frozen hashes")

        if verify_source:
            try:
                current_source_hashes = _source_hashes(repo_root)
            except (OSError, UnicodeError, TypeError, ValueError) as exc:
                errors.append(f"source inventory failed: {type(exc).__name__}: {exc}")
            else:
                if recorded_source_hashes != current_source_hashes:
                    errors.append("current executable source bytes differ from the freeze")
            errors.extend(_verify_external_binding(repo_root, external_binding))

    return {
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "valid": not errors,
        "freeze_dir": str(freeze_dir),
        "freeze_id": freeze_id,
        "expected_freeze_id": expected_freeze_id,
        "source_verified": verify_source,
        "external_capsule_verified": verify_source,
        "errors": errors,
    }


def verify_freeze(
    *,
    repo_root: Path,
    freeze_dir: Path,
    expected_freeze_id: str | None = None,
    verify_source: bool = True,
) -> dict[str, Any]:
    """Verify a freeze fail-closed, including for malformed untrusted inputs."""

    try:
        return _verify_freeze(
            repo_root=repo_root,
            freeze_dir=freeze_dir,
            expected_freeze_id=expected_freeze_id,
            verify_source=verify_source,
        )
    except Exception as exc:
        try:
            freeze_dir_text = str(freeze_dir)
        except Exception:
            freeze_dir_text = "<unprintable freeze directory>"
        return {
            "schema_version": VERIFICATION_SCHEMA_VERSION,
            "valid": False,
            "freeze_dir": freeze_dir_text,
            "freeze_id": None,
            "expected_freeze_id": expected_freeze_id,
            "source_verified": verify_source,
            "external_capsule_verified": verify_source,
            "errors": [f"freeze verification failed safely: {type(exc).__name__}: {exc}"],
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--seed", type=int, default=protocol.MASTER_SEED)
    prepare.add_argument("--out", required=True)
    prepare.add_argument("--model", default=protocol.MODEL)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--freeze-dir", required=True)
    verify.add_argument("--freeze-id")
    verify.add_argument("--skip-source-check", action="store_true")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    try:
        if args.command == "prepare":
            result = prepare_freeze(
                repo_root=repo_root,
                freeze_dir=Path(args.out),
                master_seed=args.seed,
                model=args.model,
            )
            print(f"Prepared reasoning-trace freeze: {result['freeze_dir']}")
            print(f"Freeze ID (freeze.lock.json exact bytes): {result['freeze_id']}")
            print(
                "Manifest canonical JSON SHA-256: "
                f"{result['manifest_canonical_json_sha256']}"
            )
            print("Dry preparation complete; no model transport or credential path exists here.")
            return 0
        result = verify_freeze(
            repo_root=repo_root,
            freeze_dir=Path(args.freeze_dir),
            expected_freeze_id=args.freeze_id,
            verify_source=not args.skip_source_check,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Freeze operation failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
