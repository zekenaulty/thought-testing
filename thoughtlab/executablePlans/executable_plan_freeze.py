#!/usr/bin/env python3
"""Prepare and verify an immutable executable-plan experiment freeze.

This module is deliberately transport-free.  It may construct protocol data,
hash local source files, and inspect the local Git worktree, but it has no model
client, network, or credential-access path.  Execution belongs to the separate
executable-plan pilot module and must consume a reviewed freeze ID.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Final

from thoughtlab.executablePlans import executable_plan_protocol as protocol


SAFE_PAYLOAD_FILES: Final[tuple[str, ...]] = (
    "experiment_definition.json",
    "manifest.json",
    "preregistration.json",
    "validation_report.json",
)
FREEZE_LOCK_NAME: Final[str] = "freeze.lock.json"
SAFE_FREEZE_FILES: Final[tuple[str, ...]] = (*SAFE_PAYLOAD_FILES, FREEZE_LOCK_NAME)
FORBIDDEN_RUNTIME_NAMES: Final[tuple[str, ...]] = (
    "raw",
    "call_index.json",
    "checkpoint_summaries.json",
    "checkpoint_summaries.partial.json",
    "prospective_results.json",
    "prospective_results.partial.json",
    "readout_results.json",
    "readout_results.partial.json",
    "summary.json",
    "review.md",
    "execution_ledger.json",
    "consumption_claim.json",
)

# This fixed inventory intentionally leaves the archived Review 02 source list
# untouched.  New executable-plan freezes bind the exact bytes of their own
# design, protocol, executor, tests, and the unchanged shared helpers they use.
SOURCE_FILES: Final[tuple[str, ...]] = (
    ".gitignore",
    "thoughtlab/__init__.py",
    "thoughtlab/gemini_interactions.py",
    "thoughtlab/opaque_ids.py",
    "thoughtlab/stateTransitions/__init__.py",
    "thoughtlab/stateTransitions/fork_pilot.py",
    "thoughtlab/stateTransitions/probes.py",
    "thoughtlab/stateTransitions/score_ground_truth.py",
    "thoughtlab/executablePlans/EXECUTABLE_PLAN_FEASIBILITY_DESIGN.md",
    "thoughtlab/executablePlans/__init__.py",
    "thoughtlab/executablePlans/executable_plan_protocol.py",
    "thoughtlab/executablePlans/executable_plan_freeze.py",
    "thoughtlab/executablePlans/executable_plan_pilot.py",
    "tests/test_executable_plan_protocol.py",
    "tests/test_executable_plan_freeze.py",
    "tests/test_executable_plan_pilot.py",
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
        "system_instruction_sha256",
        "tool_declarations_canonical_json_sha256",
        "planned_calls",
        "repeat_counts",
        "schedule_canonical_json_sha256",
        "transport_policy",
        "all_sources_generated_before_measurement",
        "no_replacement_source_generation",
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
        "forbidden_runtime_entries",
        "safe_file_allowlist",
        "source_file_allowlist",
        "no_call_claim",
    }
)

def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def sha256_json(value: Any) -> str:
    return sha256_bytes(protocol.canonical_json_bytes(value))


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
    return (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    _atomic_write(path, _pretty_json_bytes(value))


def _safe_source_path(repo_root: Path, relative_path: str) -> Path:
    pure = PurePosixPath(relative_path)
    if (
        not relative_path
        or pure.is_absolute()
        or ".." in pure.parts
        or "\\" in relative_path
    ):
        raise ValueError(f"unsafe source inventory path: {relative_path!r}")
    root = repo_root.resolve()
    path = root.joinpath(*pure.parts)
    current = path
    while current != root:
        if current.exists() and _is_link_or_reparse_point(current):
            raise ValueError(
                f"source inventory path contains a link/reparse point: {relative_path}"
            )
        parent = current.parent
        if parent == current:
            raise ValueError(f"source inventory path escapes repository: {relative_path}")
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
    hashes: dict[str, str] = {}
    for relative_path in SOURCE_FILES:
        path = _safe_source_path(repo_root, relative_path)
        hashes[relative_path] = sha256_bytes(
            _read_stable_regular_file(path, label=relative_path)
        )
    return hashes


def _minimal_git_environment() -> dict[str, str]:
    """Return only OS launch variables; never enumerate credential-bearing env."""
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
    """Compatibility wrapper around the protocol-owned manifest builder."""
    return protocol.create_execution_manifest(definition)


def validate_manifest(
    manifest: Any,
    definition: dict[str, Any] | None = None,
) -> list[str]:
    """Compatibility wrapper around the protocol-owned manifest validator."""
    if not isinstance(manifest, dict):
        return ["manifest is not an object"]
    if not isinstance(definition, dict):
        return ["experiment definition is unavailable for manifest validation"]
    return protocol.validate_execution_manifest(manifest, definition)


def prepare_freeze(
    *,
    repo_root: Path,
    freeze_dir: Path,
    master_seed: int,
    model: str = protocol.MODEL,
) -> dict[str, Any]:
    """Create a deterministic reviewed package without transport or credentials."""
    if model != protocol.MODEL:
        raise ValueError(f"executable-plan protocol requires model {protocol.MODEL}")
    unsafe_component = first_link_or_reparse_component(freeze_dir)
    if unsafe_component is not None:
        raise ValueError(
            f"freeze path contains a link/reparse point: {unsafe_component}"
        )
    freeze_dir = freeze_dir.resolve()
    if freeze_dir.exists() and any(freeze_dir.iterdir()):
        raise FileExistsError(f"refusing to overwrite nonempty freeze directory: {freeze_dir}")
    freeze_dir.mkdir(parents=True, exist_ok=True)

    definition = protocol.create_experiment_definition(master_seed=master_seed)
    definition_errors = protocol.validate_experiment_definition(definition)
    if definition_errors:
        raise ValueError(
            "experiment definition validation failed: " + "; ".join(definition_errors)
        )
    if definition.get("model") != model:
        raise ValueError("experiment definition returned a different model")
    manifest = create_manifest(definition)
    manifest_errors = validate_manifest(manifest, definition)
    if manifest_errors:
        raise ValueError("manifest validation failed: " + "; ".join(manifest_errors))

    definition_path = freeze_dir / "experiment_definition.json"
    manifest_path = freeze_dir / "manifest.json"
    _write_json(definition_path, definition)
    _write_json(manifest_path, manifest)

    source_hashes = _source_hashes(repo_root)
    preregistration = {
        "schema_version": "executable_plan_preregistration_v1",
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
        "system_instruction_sha256": sha256_text(definition["system_instruction"]),
        "tool_declarations_canonical_json_sha256": sha256_json(definition["tools"]),
        "planned_calls": copy.deepcopy(definition["planned_calls"]),
        "repeat_counts": copy.deepcopy(definition["repeat_counts"]),
        "schedule_canonical_json_sha256": sha256_json(definition["schedule"]),
        "transport_policy": copy.deepcopy(definition["transport_policy"]),
        "all_sources_generated_before_measurement": True,
        "no_replacement_source_generation": True,
        "raw_provider_artifacts_private": True,
        "execution_must_consume_this_exact_freeze": True,
    }
    preregistration_path = freeze_dir / "preregistration.json"
    _write_json(preregistration_path, preregistration)

    validation_report = {
        "schema_version": "executable_plan_freeze_validation_v1",
        "validated": True,
        "definition_errors": [],
        "manifest_errors": [],
        "planned_calls": copy.deepcopy(definition["planned_calls"]),
        "evidence_kind": "static_architectural_attestation_plus_hashed_regression_source",
        "preparation_transport_path_present": False,
        "preparation_credential_access_path_present": False,
        "raw_provider_artifacts_present": False,
        "forbidden_runtime_entries": [],
        "safe_file_allowlist": list(SAFE_FREEZE_FILES),
        "source_file_allowlist": list(SOURCE_FILES),
        "no_call_claim": (
            "freeze preparation imports only the pure protocol module and contains no "
            "model transport or credential access path; exact source-byte hashes are "
            "authoritative"
        ),
    }
    validation_path = freeze_dir / "validation_report.json"
    _write_json(validation_path, validation_report)

    lock = {
        "schema_version": "executable_plan_freeze_lock_v1",
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
            "new executable-plan freeze failed verification: "
            + "; ".join(verification["errors"])
        )
    return {
        "freeze_dir": str(freeze_dir),
        "freeze_id": freeze_id,
        "experiment_definition_canonical_json_sha256": sha256_json(definition),
        "manifest_canonical_json_sha256": sha256_json(manifest),
        "manifest_file_bytes_sha256": sha256_bytes(manifest_path.read_bytes()),
        "valid": True,
    }


def _load_object(path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        text = _read_stable_regular_file(path, label=path.name).decode("utf-8")
        value = protocol.strict_json_loads(text)
    except (OSError, UnicodeError, TypeError, ValueError, RecursionError) as exc:
        errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{path.name}: top-level JSON is not an object")
        return None
    return value


def _file_sha256(path: Path, errors: list[str]) -> str | None:
    try:
        return sha256_bytes(_read_stable_regular_file(path, label=path.name))
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        errors.append(f"{path.name}: exact file-byte hash failed: {type(exc).__name__}: {exc}")
        return None


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
        if lock.get("schema_version") != "executable_plan_freeze_lock_v1":
            errors.append("freeze lock schema version mismatch")
        if lock.get("hash_algorithm") != "sha256":
            errors.append("freeze lock hash algorithm mismatch")
        if lock.get("file_hash_semantics") != "exact_file_bytes":
            errors.append("freeze lock hash semantics mismatch")
        recorded_files = lock.get("files")
        if isinstance(recorded_files, dict):
            lock_files = recorded_files
    if lock_files is None or set(lock_files) != set(SAFE_PAYLOAD_FILES):
        errors.append("freeze lock file inventory is incomplete")
    else:
        for name in SAFE_PAYLOAD_FILES:
            expected_hash = lock_files.get(name)
            if (
                not isinstance(expected_hash, str)
                or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None
            ):
                errors.append(f"{name}: freeze lock hash is not a lowercase SHA-256 digest")
                continue
            if _file_sha256(freeze_dir / name, errors) != expected_hash:
                errors.append(f"{name}: exact file-byte hash mismatch")

    definition = _load_object(freeze_dir / "experiment_definition.json", errors)
    manifest = _load_object(freeze_dir / "manifest.json", errors)
    preregistration = _load_object(freeze_dir / "preregistration.json", errors)
    validation = _load_object(freeze_dir / "validation_report.json", errors)

    if definition is not None:
        try:
            errors.extend(protocol.validate_experiment_definition(definition))
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
        if validation.get("schema_version") != "executable_plan_freeze_validation_v1":
            errors.append("validation report schema version mismatch")
        if validation.get("validated") is not True:
            errors.append("validation report is not marked valid")
        if validation.get("preparation_transport_path_present") is not False:
            errors.append("validation report does not attest a transport-free prepare path")
        if validation.get("preparation_credential_access_path_present") is not False:
            errors.append("validation report does not attest a credential-free prepare path")
        if validation.get("raw_provider_artifacts_present") is not False:
            errors.append("validation report indicates provider artifacts in freeze")
        if validation.get("safe_file_allowlist") != list(SAFE_FREEZE_FILES):
            errors.append("validation report safe-file allowlist mismatch")
        if validation.get("source_file_allowlist") != list(SOURCE_FILES):
            errors.append("validation report source-file allowlist mismatch")

    if preregistration is not None and definition is not None and manifest is not None:
        if set(preregistration) != PREREGISTRATION_KEYS:
            errors.append("preregistration keys differ from the exact schema")
        if preregistration.get("schema_version") != "executable_plan_preregistration_v1":
            errors.append("preregistration schema version mismatch")
        definition_hashes = preregistration.get("experiment_definition")
        definition_hashes = definition_hashes if isinstance(definition_hashes, dict) else {}
        manifest_hashes = preregistration.get("manifest")
        manifest_hashes = manifest_hashes if isinstance(manifest_hashes, dict) else {}
        if preregistration.get("experiment_id") != definition.get("experiment_id"):
            errors.append("preregistration experiment ID mismatch")
        if preregistration.get("protocol_revision") != definition.get("protocol_revision"):
            errors.append("preregistration protocol revision mismatch")
        if preregistration.get("model") != protocol.MODEL:
            errors.append("preregistration model mismatch")
        if definition_hashes.get("canonical_json_sha256") != sha256_json(definition):
            errors.append("experiment definition canonical JSON hash mismatch")
        if definition_hashes.get("file_bytes_sha256") != _file_sha256(
            freeze_dir / "experiment_definition.json", errors
        ):
            errors.append("experiment definition recorded file-byte hash mismatch")
        if manifest_hashes.get("canonical_json_sha256") != sha256_json(manifest):
            errors.append("manifest canonical JSON hash mismatch")
        if manifest_hashes.get("file_bytes_sha256") != _file_sha256(
            freeze_dir / "manifest.json", errors
        ):
            errors.append("manifest recorded file-byte hash mismatch")
        if preregistration.get("system_instruction_sha256") != sha256_text(
            definition["system_instruction"]
        ):
            errors.append("system instruction hash mismatch")
        if preregistration.get("tool_declarations_canonical_json_sha256") != sha256_json(
            definition["tools"]
        ):
            errors.append("tool declaration hash mismatch")
        if preregistration.get("planned_calls") != definition.get("planned_calls"):
            errors.append("preregistration planned-call policy mismatch")
        if preregistration.get("repeat_counts") != definition.get("repeat_counts"):
            errors.append("preregistration repeat-count policy mismatch")
        if preregistration.get("schedule_canonical_json_sha256") != sha256_json(
            definition["schedule"]
        ):
            errors.append("schedule hash mismatch")
        if preregistration.get("transport_policy") != definition.get("transport_policy"):
            errors.append("preregistration transport policy mismatch")
        recorded_source_hashes = preregistration.get("source_file_bytes_sha256")
        if not isinstance(recorded_source_hashes, dict) or set(
            recorded_source_hashes
        ) != set(SOURCE_FILES):
            errors.append("preregistration source-file inventory mismatch")
        elif any(
            not isinstance(value, str)
            or re.fullmatch(r"[0-9a-f]{64}", value) is None
            for value in recorded_source_hashes.values()
        ):
            errors.append("preregistration contains an invalid source-file hash")
        for key in (
            "all_sources_generated_before_measurement",
            "no_replacement_source_generation",
            "raw_provider_artifacts_private",
            "execution_must_consume_this_exact_freeze",
        ):
            if preregistration.get(key) is not True:
                errors.append(f"preregistration required assertion is not true: {key}")

        if verify_source:
            try:
                current_source_hashes = _source_hashes(repo_root)
            except (OSError, UnicodeError, TypeError, ValueError) as exc:
                errors.append(f"source inventory failed: {type(exc).__name__}: {exc}")
            else:
                if preregistration.get("source_file_bytes_sha256") != current_source_hashes:
                    errors.append("current executable source bytes differ from the freeze")

    return {
        "schema_version": "executable_plan_freeze_verification_v1",
        "valid": not errors,
        "freeze_dir": str(freeze_dir),
        "freeze_id": freeze_id,
        "expected_freeze_id": expected_freeze_id,
        "source_verified": verify_source,
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
            "schema_version": "executable_plan_freeze_verification_v1",
            "valid": False,
            "freeze_dir": freeze_dir_text,
            "freeze_id": None,
            "expected_freeze_id": expected_freeze_id,
            "source_verified": verify_source,
            "errors": [f"freeze verification failed safely: {type(exc).__name__}: {exc}"],
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--seed", type=int, required=True)
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
            print(f"Prepared executable-plan review freeze: {result['freeze_dir']}")
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
