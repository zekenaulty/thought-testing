#!/usr/bin/env python3
"""Prepare and verify a reviewable, transport-free S0-S6 protocol freeze."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

from thoughtlab.stateTransitions.planning_transition_probes import PROBES
from thoughtlab.stateTransitions.planning_transition_protocol import (
    CARRIER_CONTRACT,
    GENERATION_ELIGIBILITY_CONTRACT,
    MODEL,
    SCORING_POLICY,
    STOPPING_POLICY,
    TRANSPORT_POLICY,
    DuplicateJsonKey,
    canonical_json_bytes,
    create_manifest,
    load_and_validate_experiment_definition,
    sha256_bytes,
    sha256_json,
    strict_json_loads,
    validate_manifest,
)


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
    "probe_results.json",
    "probe_results.partial.json",
    "summary.json",
    "review.md",
)
SOURCE_FILES: Final[tuple[str, ...]] = (
    ".gitignore",
    "thoughtlab/__init__.py",
    "thoughtlab/gemini_interactions.py",
    "thoughtlab/opaque_ids.py",
    "thoughtlab/stateTransitions/__init__.py",
    "thoughtlab/stateTransitions/fork_pilot.py",
    "thoughtlab/stateTransitions/probes.py",
    "thoughtlab/stateTransitions/score_ground_truth.py",
    "thoughtlab/stateTransitions/planning_transition_probes.py",
    "thoughtlab/stateTransitions/planning_transition_score.py",
    "thoughtlab/stateTransitions/planning_transition_protocol.py",
    "thoughtlab/stateTransitions/planning_transition_freeze.py",
    "thoughtlab/stateTransitions/planning_transition_pilot.py",
    "thoughtlab/stateTransitions/experiments/planning_transition_pilot_v1.json",
    "thoughtlab/stateTransitions/PLANNING_SLICE_TEST_PLAN.md",
    "tests/test_planning_transition_pilot.py",
)


def _is_link_or_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    file_attributes = getattr(metadata, "st_file_attributes", 0)
    return path.is_symlink() or bool(file_attributes & reparse_flag)


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
            temporary.unlink()


def _pretty_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    _atomic_write(path, _pretty_json_bytes(value))


def _source_hashes(repo_root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for relative_path in SOURCE_FILES:
        path = repo_root / relative_path
        if not path.is_file():
            raise FileNotFoundError(f"required source file is missing: {relative_path}")
        if _is_link_or_reparse_point(path):
            raise ValueError(f"required source file is a link/reparse point: {relative_path}")
        hashes[relative_path] = sha256_bytes(path.read_bytes())
    return hashes


def _git_snapshot(repo_root: Path) -> dict[str, Any]:
    allowed_environment_keys = (
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
    safe_environment = {
        key: value
        for key in allowed_environment_keys
        if isinstance((value := os.environ.get(key)), str)
    }
    safe_environment.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_ATTR_NOSYSTEM": "1",
        }
    )
    git_prefix = [
        "git",
        "-c",
        f"safe.directory={repo_root.resolve()}",
        "-c",
        "core.fsmonitor=false",
        "-c",
        f"core.hooksPath={os.devnull}",
    ]
    try:
        commit = subprocess.run(
            [*git_prefix, "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            env=safe_environment,
        ).stdout.strip()
        status = subprocess.run(
            [*git_prefix, "status", "--short", "--", *SOURCE_FILES],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            env=safe_environment,
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


def prepare_freeze(
    *,
    repo_root: Path,
    freeze_dir: Path,
    master_seed: int,
    model: str = MODEL,
) -> dict[str, Any]:
    """Create a deterministic safe package without importing or invoking transport."""
    unsafe_component = first_link_or_reparse_component(freeze_dir)
    if unsafe_component is not None:
        raise ValueError(
            f"freeze path contains a link/reparse point: {unsafe_component}"
        )
    freeze_dir = freeze_dir.resolve()
    if freeze_dir.exists() and any(freeze_dir.iterdir()):
        raise FileExistsError(f"refusing to overwrite nonempty freeze directory: {freeze_dir}")
    freeze_dir.mkdir(parents=True, exist_ok=True)

    definition = load_and_validate_experiment_definition(repo_root)
    manifest = create_manifest(master_seed=master_seed, model=model)
    manifest_errors = validate_manifest(manifest)
    if manifest_errors:
        raise ValueError("manifest validation failed: " + "; ".join(manifest_errors))

    definition_path = freeze_dir / "experiment_definition.json"
    manifest_path = freeze_dir / "manifest.json"
    _write_json(definition_path, definition)
    _write_json(manifest_path, manifest)

    policy_bundle = {
        "transport_policy": TRANSPORT_POLICY,
        "stopping_policy": STOPPING_POLICY,
        "generation_eligibility_contract": GENERATION_ELIGIBILITY_CONTRACT,
        "carrier_contract": CARRIER_CONTRACT,
        "scoring_policy": SCORING_POLICY,
    }
    preregistration = {
        "schema_version": "native_planning_transition_preregistration_v1",
        "experiment_id": manifest["experiment_id"],
        "protocol_revision": manifest["protocol_revision"],
        "manifest": {
            "canonical_json_sha256": sha256_json(manifest),
            "file_bytes_sha256": sha256_bytes(manifest_path.read_bytes()),
        },
        "experiment_definition": {
            "canonical_json_sha256": sha256_json(definition),
            "file_bytes_sha256": sha256_bytes(definition_path.read_bytes()),
        },
        "probe_definitions_canonical_json_sha256": sha256_json(PROBES),
        "policy_bundle": policy_bundle,
        "policy_bundle_canonical_json_sha256": sha256_json(policy_bundle),
        "source_file_bytes_sha256": _source_hashes(repo_root),
        "source_binding": _git_snapshot(repo_root),
        "planned_calls": manifest["planned_calls"],
        "both_replacement_runs_frozen_before_execution": True,
        "tomography_requires_complete_generation_eligibility": True,
        "raw_provider_artifacts_private": True,
        "execution_must_consume_this_exact_freeze": True,
    }
    preregistration_path = freeze_dir / "preregistration.json"
    _write_json(preregistration_path, preregistration)

    validation_report = {
        "schema_version": "native_planning_transition_freeze_validation_v1",
        "validated": True,
        "manifest_errors": [],
        "planned_run_attempts": 2,
        "tomography_keys_per_run": 196,
        "generation_keys_per_complete_run": 14,
        "complete_run_logical_requests": 210,
        "complete_run_max_physical_attempts": 630,
        "two_run_logical_ceiling": 224,
        "two_run_max_physical_attempts": 672,
        "evidence_kind": "static_architectural_attestation_plus_hashed_regression_source",
        "preparation_transport_path_present": False,
        "preparation_credential_access_path_present": False,
        "hashed_no_call_regression_source": "tests/test_planning_transition_pilot.py",
        "forbidden_runtime_entries": [],
        "no_call_claim": (
            "the freeze-preparation module contains no model transport or credential "
            "access path; the hashed regression source blocks the HTTP entry point "
            "during preparation. This is a scoped static/test attestation, not a "
            "claim about unrelated processes or all operating-system egress"
        ),
        "safe_file_allowlist": list(SAFE_FREEZE_FILES),
    }
    validation_path = freeze_dir / "validation_report.json"
    _write_json(validation_path, validation_report)

    lock = {
        "schema_version": "native_planning_transition_freeze_lock_v1",
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
        raise ValueError("new freeze failed verification: " + "; ".join(verification["errors"]))
    return {
        "freeze_dir": str(freeze_dir),
        "freeze_id": freeze_id,
        "manifest_canonical_json_sha256": preregistration["manifest"][
            "canonical_json_sha256"
        ],
        "manifest_file_bytes_sha256": preregistration["manifest"][
            "file_bytes_sha256"
        ],
        "valid": True,
    }


def _load_object(path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        value = strict_json_loads(path.read_text(encoding="utf-8"))
    except (
        OSError,
        UnicodeError,
        TypeError,
        ValueError,
        RecursionError,
        DuplicateJsonKey,
    ) as exc:
        errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{path.name}: top-level JSON is not an object")
        return None
    return value


def _file_sha256(path: Path, errors: list[str]) -> str | None:
    """Hash a regular file, recording an invalid-verification error on read failure."""
    try:
        if not path.is_file():
            return None
        return sha256_bytes(path.read_bytes())
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        errors.append(
            f"{path.name}: exact file-byte hash failed: {type(exc).__name__}: {exc}"
        )
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
        errors.append(
            f"freeze path contains a link/reparse point: {unsafe_component}"
        )
    freeze_dir = freeze_dir.resolve()
    entries = _freeze_entries(freeze_dir)
    if entries != sorted(SAFE_FREEZE_FILES):
        errors.append(
            f"freeze entries differ from safe allowlist: found {entries!r}"
        )
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
        recorded_lock_files = lock.get("files")
        if isinstance(recorded_lock_files, dict):
            lock_files = recorded_lock_files
    if lock is not None and (
        lock_files is None or set(lock_files) != set(SAFE_PAYLOAD_FILES)
    ):
        errors.append("freeze lock file inventory is incomplete")
    elif lock_files is not None:
        for name, expected_hash in lock_files.items():
            path = freeze_dir / name
            actual_hash = _file_sha256(path, errors)
            if actual_hash != expected_hash:
                errors.append(f"{name}: exact file-byte hash mismatch")

    definition = _load_object(freeze_dir / "experiment_definition.json", errors)
    manifest = _load_object(freeze_dir / "manifest.json", errors)
    preregistration = _load_object(freeze_dir / "preregistration.json", errors)
    validation = _load_object(freeze_dir / "validation_report.json", errors)
    if manifest is not None:
        try:
            errors.extend(validate_manifest(manifest))
        except Exception as exc:
            errors.append(
                f"manifest validation failed safely: {type(exc).__name__}: {exc}"
            )
    if validation is not None:
        if validation.get("validated") is not True:
            errors.append("validation report is not marked valid")
        if validation.get("preparation_transport_path_present") is not False:
            errors.append("validation report does not attest a transport-free prepare path")
        if validation.get("preparation_credential_access_path_present") is not False:
            errors.append("validation report does not attest a credential-free prepare path")

    if preregistration is not None and manifest is not None and definition is not None:
        recorded_manifest_hashes = preregistration.get("manifest")
        manifest_hashes = (
            recorded_manifest_hashes
            if isinstance(recorded_manifest_hashes, dict)
            else {}
        )
        recorded_definition_hashes = preregistration.get("experiment_definition")
        definition_hashes = (
            recorded_definition_hashes
            if isinstance(recorded_definition_hashes, dict)
            else {}
        )
        if manifest_hashes.get("canonical_json_sha256") != sha256_json(manifest):
            errors.append("manifest canonical JSON hash mismatch")
        if manifest_hashes.get("file_bytes_sha256") != _file_sha256(
            freeze_dir / "manifest.json", errors
        ):
            errors.append("manifest recorded file-byte hash mismatch")
        if definition_hashes.get("canonical_json_sha256") != sha256_json(definition):
            errors.append("experiment definition canonical JSON hash mismatch")
        if definition_hashes.get("file_bytes_sha256") != _file_sha256(
            freeze_dir / "experiment_definition.json", errors
        ):
            errors.append("experiment definition recorded file-byte hash mismatch")
        if preregistration.get("probe_definitions_canonical_json_sha256") != sha256_json(
            PROBES
        ):
            errors.append("probe definition hash mismatch")
        policy_bundle = {
            "transport_policy": TRANSPORT_POLICY,
            "stopping_policy": STOPPING_POLICY,
            "generation_eligibility_contract": GENERATION_ELIGIBILITY_CONTRACT,
            "carrier_contract": CARRIER_CONTRACT,
            "scoring_policy": SCORING_POLICY,
        }
        if preregistration.get("policy_bundle") != policy_bundle:
            errors.append("embedded policy bundle mismatch")
        if preregistration.get("policy_bundle_canonical_json_sha256") != sha256_json(
            policy_bundle
        ):
            errors.append("policy bundle hash mismatch")
        if verify_source:
            try:
                current_source_hashes = _source_hashes(repo_root)
            except (OSError, UnicodeError, TypeError, ValueError) as exc:
                errors.append(
                    f"source inventory failed: {type(exc).__name__}: {exc}"
                )
            else:
                if preregistration.get("source_file_bytes_sha256") != current_source_hashes:
                    errors.append("current executable source bytes differ from the freeze")

    return {
        "schema_version": "native_planning_transition_freeze_verification_v1",
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
    """Verify a freeze fail-closed, including when untrusted inputs are malformed."""
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
            "schema_version": "native_planning_transition_freeze_verification_v1",
            "valid": False,
            "freeze_dir": freeze_dir_text,
            "freeze_id": None,
            "expected_freeze_id": expected_freeze_id,
            "source_verified": verify_source,
            "errors": [
                f"freeze verification failed safely: {type(exc).__name__}: {exc}"
            ],
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--seed", type=int, required=True)
    prepare.add_argument("--out", required=True)
    prepare.add_argument("--model", default=MODEL)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--freeze-dir", required=True)
    verify.add_argument("--freeze-id")
    verify.add_argument("--skip-source-check", action="store_true")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    try:
        if args.command == "prepare":
            if args.model != MODEL:
                raise ValueError(f"frozen protocol requires model {MODEL}")
            result = prepare_freeze(
                repo_root=repo_root,
                freeze_dir=Path(args.out),
                master_seed=args.seed,
                model=args.model,
            )
            print(f"Prepared review freeze: {result['freeze_dir']}")
            print(f"Freeze ID (freeze.lock.json exact bytes): {result['freeze_id']}")
            print(
                "Manifest canonical JSON SHA-256: "
                f"{result['manifest_canonical_json_sha256']}"
            )
            print(
                "Manifest file-bytes SHA-256: "
                f"{result['manifest_file_bytes_sha256']}"
            )
            print("Dry preparation complete; this module has no model transport path.")
            return 0
        result = verify_freeze(
            repo_root=repo_root,
            freeze_dir=Path(args.freeze_dir),
            expected_freeze_id=args.freeze_id,
            verify_source=not args.skip_source_check,
        )
    except (OSError, ValueError, json.JSONDecodeError, DuplicateJsonKey) as exc:
        print(f"Freeze operation failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
