#!/usr/bin/env python3
"""Prepare and verify the transport-free iterative reasoning-engineering freeze.

The freezer is deliberately a local, deterministic packaging tool.  It hashes
the complete source closure used by the occurrence, writes exactly five safe
JSON files, and never imports or invokes the live transport or raw archive.
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
from pathlib import Path, PurePosixPath
from typing import Any, Final

from thoughtlab.reasoningEngineering import (
    modernization_iterative_protocol as protocol,
)


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
    "modernization_iterative_reasoning_engineering_review_01_occurrence_01"
)

# This is an exact, deliberately closed inventory.  The iterative protocol
# imports the prior pure protocol for shared prompt and dossier construction,
# so that module is part of the closure even though the previous runner and
# freezer are not.  Live transport modules are hashed, never imported here.
SOURCE_FILES: Final[tuple[str, ...]] = (
    ".gitignore",
    "thoughtlab/__init__.py",
    "thoughtlab/gemini_generate_content.py",
    "thoughtlab/opaque_ids.py",
    "thoughtlab/raw_call_store.py",
    "thoughtlab/reasoningEngineering/__init__.py",
    (
        "thoughtlab/reasoningEngineering/"
        "MODERNIZATION_ITERATIVE_REASONING_ENGINEERING_DESIGN.md"
    ),
    "thoughtlab/reasoningEngineering/DOSSIER_CONSTRUCTION_NOTES.md",
    "thoughtlab/reasoningEngineering/modernization_protocol.py",
    "thoughtlab/reasoningEngineering/modernization_iterative_protocol.py",
    "thoughtlab/reasoningEngineering/modernization_iterative_pilot.py",
    "thoughtlab/reasoningEngineering/modernization_iterative_freeze.py",
    *(
        f"{protocol.base.DOSSIER_DIRECTORY}/{name}"
        for name in protocol.base.DOSSIER_FILES
    ),
    "tests/test_modernization_iterative_protocol.py",
    "tests/test_modernization_iterative_pilot.py",
    "tests/test_modernization_iterative_freeze.py",
)

MANIFEST_SCHEMA = "modernization_iterative_reasoning_engineering_manifest_v1"
PREREGISTRATION_SCHEMA = (
    "modernization_iterative_reasoning_engineering_preregistration_v1"
)
VALIDATION_SCHEMA = "modernization_iterative_reasoning_engineering_validation_v1"
LOCK_SCHEMA = "modernization_iterative_reasoning_engineering_freeze_lock_v1"
VERIFICATION_SCHEMA = (
    "modernization_iterative_reasoning_engineering_freeze_verification_v1"
)

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

EXPECTED_CHAIN: Final[list[str]] = [
    "C0",
    "O0",
    "X1",
    "I1",
    "C1",
    "O1",
    "X2",
    "I2",
    "C2",
    "O2",
    "X3",
    "I3",
    "C3",
    "O3",
]
EXPECTED_CALL_BOUNDS: Final[dict[str, int]] = {
    "completed_evidence_path_minimum": 20,
    "whole_experiment_maximum": 60,
    "whole_experiment_physical_maximum": 180,
}


class DuplicateJsonKey(ValueError):
    """Raised when strict immutable JSON contains duplicate object keys."""


def strict_json_loads(text: str) -> Any:
    """Load standards-compliant finite JSON while rejecting duplicate keys."""

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
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return _sha256_bytes(encoded)


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
                "source inventory path contains a link/reparse point: "
                f"{relative}"
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
        records[relative] = {"bytes": len(data), "sha256": _sha256_bytes(data)}
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
            expected_closure = _canonical_sha256(source_files)
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
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "experiment_id": protocol.EXPERIMENT_ID,
        "protocol_revision": protocol.PROTOCOL_REVISION,
        "source_files": files,
        "source_file_count": len(files),
        "source_closure_sha256": _canonical_sha256(files),
        "git": _git_record(root),
    }
    errors = _manifest_structure_errors(manifest)
    if errors:
        raise ValueError("generated manifest is invalid: " + "; ".join(errors))
    return manifest


def _iterative_semantics_errors(definition: Any) -> list[str]:
    """Check the high-level causal commitments the freeze must preserve."""

    if not isinstance(definition, dict):
        return ["experiment definition is not an object"]
    errors: list[str] = []
    trajectory = definition.get("trajectory")
    participant_topology = definition.get("participant_topology")
    planning = definition.get("planning")
    isolation = definition.get("isolation")
    examinations = definition.get("examinations")
    measurement = definition.get("private_measurement_material")
    observation_assessments = definition.get("observation_assessments")
    interventions = definition.get("interventions")
    state_machine = definition.get("state_machine")
    execution = definition.get("execution")
    adjudication = definition.get("adjudication")
    planned_calls = definition.get("planned_calls")

    if not isinstance(participant_topology, dict):
        errors.append("participant topology is missing")
    else:
        examiner = participant_topology.get("examiner")
        planner = participant_topology.get("planner")
        adjudicator = participant_topology.get("final_adjudicator")
        if participant_topology.get("participant_roles") != 3:
            errors.append("participant-role count differs")
        if participant_topology.get("model_agents") != 2:
            errors.append("model-agent count differs")
        if not isinstance(planner, dict) or planner.get("model") != "gemini-3.7-flash":
            errors.append("Gemini planner role differs")
        if not isinstance(examiner, dict) or (
            examiner.get("model"),
            examiner.get("reasoning_effort"),
            examiner.get("harness"),
        ) != ("gpt-5.6-sol", "xhigh", "chatgpt"):
            errors.append("Sol/ChatGPT examiner role differs")
        if not isinstance(adjudicator, dict) or adjudicator.get("role") != (
            "human_researcher"
        ):
            errors.append("human final-adjudicator role differs")

    if not isinstance(trajectory, dict) or trajectory.get("ordered_chain") != EXPECTED_CHAIN:
        errors.append("trajectory is not the frozen four-checkpoint chain")
    elif (
        trajectory.get("exactly_three_examinations") is not True
        or trajectory.get("X4_exists") is not False
    ):
        errors.append("trajectory does not stop after exactly three examinations")
    if not isinstance(planning, dict):
        errors.append("planning definition is missing")
    else:
        if planning.get("visible_channel") != "raw_text_no_schema_no_json_envelope":
            errors.append("planning readiness is not raw text")
        if planning.get("live_candidate_content_is_replayed_without_mutation") is not True:
            errors.append("exact unmodified live Content replay is not frozen")
        if planning.get("max_tokens_signed_content_is_replayed_exactly") is not True:
            errors.append("MAX_TOKENS signed Content continuation is not frozen")

    if not isinstance(isolation, dict):
        errors.append("isolation definition is missing")
    else:
        if isolation.get("operator_status") != "protocol_defined_core_operator":
            errors.append("tomography is not a protocol-defined core operator")
        if isolation.get("operator_name") != (
            "detached_blank_text_signed_part_isolation"
        ):
            errors.append("tomography operator identity differs")
        if isolation.get("visible_part_text_is_replaced_with_empty_text") is not True:
            errors.append("blank-text detached carrier mutation is not frozen")
        if isolation.get("part_order_and_thought_signatures_are_preserved_exactly") is not True:
            errors.append("isolated Part order and signatures are not preserved")
        if isolation.get("every_replayable_planning_checkpoint_is_inspected") is not True:
            errors.append("every replayable planning checkpoint is not inspected")
        if isolation.get("eligible_observation_required_before_next_human_seal") is not True:
            errors.append("eligible observation does not gate the next human seal")

    if not isinstance(examinations, dict):
        errors.append("external examination definition is missing")
    else:
        if examinations.get("ids") != ["X1", "X2", "X3"]:
            errors.append("external examination IDs differ")
        if examinations.get("exact_external_examiner_turns") != 3:
            errors.append("external examiner does not have exactly three turns")
        expected_charters = [
            "epistemic_hinge_audit_v1",
            "adversarial_alternative_falsification_audit_v1",
            "global_reintegration_joint_feasibility_audit_v1",
        ]
        if examinations.get("fixed_charter_order") != expected_charters:
            errors.append("examination charter order differs")
        if examinations.get("adaptive_target_selection_within_each_charter") is not True:
            errors.append("examiner target selection is not adaptive")
        if examinations.get("examiner_output_is_never_replayed_to_planner") is not True:
            errors.append("examiner output could be replayed directly to planner")
        if examinations.get("no_fourth_examination") is not True:
            errors.append("a fourth examination is not excluded")

    if not isinstance(measurement, dict):
        errors.append("private measurement material is missing")
    else:
        rubric = measurement.get("semantic_human_rubric")
        diagnostic_states = measurement.get("diagnostic_states")
        if not isinstance(measurement.get("fault_atlas"), (list, tuple)) or len(
            measurement["fault_atlas"]
        ) < 1:
            errors.append("private generic fault atlas is missing")
        if not isinstance(rubric, (list, tuple)) or len(rubric) != 6:
            errors.append("semantic rubric is not six-dimensional")
        elif any(set(item.get("anchors", {})) != {"0", "1", "2"} for item in rubric):
            errors.append("semantic rubric does not use exact 0-2 anchors")
        if diagnostic_states != [
            "UNRECOGNIZED",
            "RECOGNIZED",
            "BOUNDED",
            "RESOLVED",
            "RATIONALIZED",
        ]:
            errors.append("diagnostic-state vocabulary differs")
        if measurement.get("generic_and_contains_no_dossier_specific_answer") is not True:
            errors.append("private fault atlas is not generic")
        if measurement.get("invisible_to_gemini_planner") is not True:
            errors.append("private measurement material could reach the planner")
        if measurement.get("not_in_planning_intervention_or_execution_requests") is not True:
            errors.append("private measurement material could enter Gemini requests")

    if not isinstance(observation_assessments, dict):
        errors.append("observation-assessment contract is missing")
    else:
        if observation_assessments.get("observations_scored") != [
            "O0",
            "O1",
            "O2",
            "O3",
        ]:
            errors.append("observation-assessment coverage differs")
        if observation_assessments.get(
            "same_six_dimension_rubric_for_every_observation"
        ) is not True:
            errors.append("observations do not share the same six-dimension rubric")
        dimensions = observation_assessments.get("rubric_dimensions")
        if not isinstance(dimensions, list) or len(dimensions) != 6:
            errors.append("observation-assessment rubric dimensions differ")
        if observation_assessments.get("score_range") != [0, 2]:
            errors.append("observation-assessment score range differs")
        if observation_assessments.get("assessor") != "human_researcher":
            errors.append("observation assessor is not the human researcher")
        if observation_assessments.get("scores_are_descriptive_not_a_stop_rule") is not True:
            errors.append("observation rubric scores became a sole stop rule")
        if observation_assessments.get("target_diagnostic_states") != {
            "O0": ["I1"],
            "O1": ["I1", "I2"],
            "O2": ["I1", "I2", "I3"],
            "O3": ["I1", "I2", "I3"],
        }:
            errors.append("observation diagnostic-target coverage differs")
        if observation_assessments.get(
            "available_later_observations_reassess_prior_targets"
        ) is not True:
            errors.append("later observations do not reassess prior targets")
        if observation_assessments.get("O0_O1_O2_assessments_are_bound_in") != {
            "O0": "I1 human seal",
            "O1": "I2 human seal",
            "O2": "I3 human seal",
        }:
            errors.append("O0-O2 assessments are not bound into intervention seals")
        final_assessment = observation_assessments.get("final_O3_assessment")
        if not isinstance(final_assessment, dict):
            errors.append("final O3 human assessment contract is missing")
        else:
            if final_assessment.get("schema_version") != (
                protocol.FINAL_O3_ASSESSMENT_SCHEMA_VERSION
            ):
                errors.append("final O3 assessment schema differs")
            if final_assessment.get("assessment_id") != protocol.FINAL_O3_ASSESSMENT_ID:
                errors.append("final O3 assessment identity differs")
            if final_assessment.get("record_keys") != sorted(
                protocol.RUNTIME_FINAL_O3_ASSESSMENT_KEYS
            ):
                errors.append("final O3 assessment record schema differs")
            if final_assessment.get("required_target_states") != ["I1", "I2", "I3"]:
                errors.append("final O3 assessment target coverage differs")
            if final_assessment.get("human_only_non_examiner") is not True:
                errors.append("final O3 assessment is not human-only")
            if final_assessment.get("creates_no_X4_or_I4") is not True:
                errors.append("final O3 assessment could create X4 or I4")
            if final_assessment.get(
                "must_be_sealed_before_execution_gate_opens"
            ) is not True:
                errors.append("final O3 assessment does not gate execution")
        if observation_assessments.get(
            "hard_contradiction_precludes_resolved_target_or_full_repair_scores"
        ) is not True:
            errors.append("hard contradiction does not constrain O0-O3 assessments")

    if not isinstance(interventions, dict):
        errors.append("intervention definition is missing")
    else:
        # The specs contain only adaptive selection rules and causal edges.  No
        # exact treatment wording or target is chosen until the source
        # observation and two independent review streams exist.
        specs = interventions.get("specs")
        selection_rules = interventions.get("selection_rules")
        if not isinstance(specs, dict) or set(specs) != {"I1", "I2", "I3"}:
            errors.append("adaptive intervention specifications differ")
        elif any("template" in spec for spec in specs.values()):
            errors.append("exact preloaded intervention treatment remains present")
        if not isinstance(selection_rules, dict) or set(selection_rules) != {
            "I1",
            "I2",
            "I3",
        }:
            errors.append("adaptive intervention selection rules differ")
        if interventions.get(
            "actual_diagnosis_target_prediction_and_text_are_authored_after_observation"
        ) is not True:
            errors.append(
                "adaptive diagnosis, target, prediction, and text are not "
                "authored after observation"
            )
        if interventions.get(
            "runtime_supplies_and_validates_source_observation_hash"
        ) is not True:
            errors.append("interventions are not bound to their source observations")
        if interventions.get(
            "runtime_supplies_and_validates_examiner_input_output_hashes"
        ) is not True:
            errors.append("interventions are not bound to examiner input/output")
        authored_keys = interventions.get("human_authored_record_keys")
        if not isinstance(authored_keys, list) or (
            "source_observation_assessment" not in authored_keys
        ):
            errors.append("intervention seals do not bind source assessments")
        if interventions.get(
            "model_facing_intervention_contains_only_reconciled_intervention_text"
        ) is not True:
            errors.append("unreconciled review material could become model-facing")
        provenance = interventions.get("reviewer_provenance_requirements")
        if not isinstance(provenance, dict) or set(provenance) != {
            "reviewer_A",
            "reviewer_B",
        }:
            errors.append("independent review-stream provenance differs")
        else:
            reviewer_b = provenance.get("reviewer_B")
            if not isinstance(reviewer_b, dict) or reviewer_b != {
                "reviewer_type": "model",
                "identity": "independent_sol_chatgpt_reviewer_channel",
                "model": "gpt-5.6-sol",
                "reasoning_effort": "xhigh",
                "harness": "chatgpt",
            }:
                errors.append("independent model review provenance differs")
        if interventions.get("human_researcher_is_final_adjudicator") is not True:
            errors.append("human-approved reconciliation is not frozen")

    if not isinstance(state_machine, dict):
        errors.append("state machine is missing")
    else:
        if state_machine.get("human_seal_gates_cannot_be_bypassed") is not True:
            errors.append("human intervention seals can be bypassed")
        if state_machine.get(
            "execution_gate_requires_eligible_O3_and_final_human_assessment"
        ) is not True:
            errors.append("eligible O3 and its final human assessment do not gate execution")
        if state_machine.get("no_X4_or_I4_transition") is not True:
            errors.append("state machine does not terminate examination at X3/I3")

    if not isinstance(execution, dict):
        errors.append("execution definition is missing")
    else:
        if execution.get("checkpoints") != ["C0", "C1", "C2", "C3"]:
            errors.append("matched execution checkpoints differ")
        if execution.get("replicates_per_checkpoint") != 3:
            errors.append("matched execution replicate count differs")
        if execution.get("same_seed_within_matched_checkpoint_quartet") is not True:
            errors.append("execution seeds are not matched within quartets")
        if execution.get(
            "begins_only_after_O3_is_eligible_and_final_assessment_is_sealed"
        ) is not True:
            errors.append("matched execution can precede the final O3 assessment seal")

    if not isinstance(adjudication, dict):
        errors.append("adjudication definition is missing")
    else:
        if adjudication.get("mode") != "semantic_relational_human_review":
            errors.append("adjudication is not semantic and relational")
        if adjudication.get("no_keyword_counting") is not True:
            errors.append("keyword-count adjudication has not been excluded")
        if adjudication.get("rubric_dimensions") != 6:
            errors.append("adjudication rubric dimension count differs")
        if adjudication.get("rubric_anchor_range") != [0, 2]:
            errors.append("adjudication rubric range differs")
        if adjudication.get("diagnostic_states") != [
            "UNRECOGNIZED",
            "RECOGNIZED",
            "BOUNDED",
            "RESOLVED",
            "RATIONALIZED",
        ]:
            errors.append("adjudication diagnostic states differ")
        if adjudication.get("hard_contradictions_gate_repair") is not True:
            errors.append("hard contradiction does not gate repair claims")

    if not isinstance(planned_calls, dict):
        errors.append("planned call bounds are missing")
    else:
        for key, expected in EXPECTED_CALL_BOUNDS.items():
            if planned_calls.get(key) != expected:
                errors.append(f"planned call bound differs: {key}")

    if "off-protocol" in json.dumps(definition, ensure_ascii=True).lower():
        errors.append("tomography is mislabeled as outside the experiment protocol")
    return errors


def build_preregistration(
    definition: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, Any]:
    """Bind the design, causal gates, and adaptive selection rules."""

    return {
        "schema_version": PREREGISTRATION_SCHEMA,
        "experiment_id": protocol.EXPERIMENT_ID,
        "protocol_revision": protocol.PROTOCOL_REVISION,
        "model": protocol.MODEL,
        "api": protocol.API,
        "status": "prepared_unexecuted",
        "definition_canonical_sha256": _canonical_sha256(definition),
        "manifest_canonical_sha256": _canonical_sha256(manifest),
        "source_closure_sha256": manifest["source_closure_sha256"],
        "dossier_assembled_sha256": definition["dossier"][
            "assembled_task_sha256"
        ],
        "participant_topology": {
            "planner": {
                "model": "gemini-3.7-flash",
                "api": protocol.API,
                "role": "private planning state and matched execution",
            },
            "examiner": {
                "model": "gpt-5.6-sol",
                "reasoning_effort": "xhigh",
                "harness": "chatgpt",
                "role": "three external semantic examinations",
                "exact_turns": 3,
            },
            "final_adjudicator": "human researcher",
            "participant_roles": 3,
            "model_agents": 2,
        },
        "primary_trajectory": {
            "ordered_chain": copy.deepcopy(EXPECTED_CHAIN),
            "state_transitions": [
                "C0--X1/I1-->C1",
                "C1--X2/I2-->C2",
                "C2--X3/I3-->C3",
            ],
            "observations": ["O0", "O1", "O2", "O3"],
            "examinations": ["X1", "X2", "X3"],
            "observation_is_not_replayed_into_live_planning": True,
            "examiner_output_is_not_replayed_into_live_planning": True,
            "exact_native_parent_history_replay": True,
            "primary_completion_is_not_gated_by_optional_controls": True,
            "no_X4_or_I4": True,
            "post_O3_gate": (
                "human-only final O3 rubric and diagnostic assessment seal, "
                "then execution"
            ),
        },
        "planning": {
            "visible_channel": "raw_text_no_schema_no_json_envelope",
            "finish_reason_precedes_visible_parse": True,
            "max_tokens_has_no_observed_readiness_judgment": True,
            "max_tokens_signed_native_content_continues_exactly": True,
            "threshold_is_experimental_termination_not_model_judgment": True,
        },
        "tomography": {
            "status": "experiment_protocol_defined_primary_operator",
            "operator": "detached_blank_text_signed_part_isolation",
            "distinct_from_unmodified_live_continuation": True,
            "every_replayable_planning_checkpoint_is_inspected": True,
            "observation_is_query_conditioned_semantic_projection": True,
            "observability_does_not_entail_state_modification": True,
            "state_modification_does_not_entail_successful_repair": True,
        },
        "external_examinations": {
            "X1": "epistemic_hinge_audit_v1",
            "X2": "adversarial_alternative_falsification_audit_v1",
            "X3": "global_reintegration_joint_feasibility_audit_v1",
            "fixed_charter_order_adaptive_target_selection": True,
            "exactly_three_recorded_Sol_ChatGPT_turns": True,
            "inputs_and_outputs_are_runtime_hash_bound": True,
            "no_fourth_examination": True,
        },
        "private_measurement_material": {
            "generic_fault_atlas": True,
            "contains_no_dossier_specific_answer": True,
            "invisible_to_gemini_planner": True,
            "excluded_from_planning_intervention_and_execution_requests": True,
            "semantic_rubric_dimensions": 6,
            "rubric_anchor_range": [0, 2],
            "diagnostic_states": [
                "UNRECOGNIZED",
                "RECOGNIZED",
                "BOUNDED",
                "RESOLVED",
                "RATIONALIZED",
            ],
            "hard_contradiction_gates_full_repair": True,
        },
        "observation_assessments": {
            "assessor": "human researcher",
            "observations_scored": ["O0", "O1", "O2", "O3"],
            "same_rubric_dimensions": list(protocol.RUBRIC_DIMENSIONS),
            "score_range": [0, 2],
            "scores_are_descriptive_not_a_stop_rule": True,
            "target_diagnostic_states": {
                "O0": ["I1"],
                "O1": ["I1", "I2"],
                "O2": ["I1", "I2", "I3"],
                "O3": ["I1", "I2", "I3"],
            },
            "O0_O1_O2_assessments_are_bound_into": {
                "O0": "I1 human seal",
                "O1": "I2 human seal",
                "O2": "I3 human seal",
            },
            "final_O3_assessment": {
                "schema_version": protocol.FINAL_O3_ASSESSMENT_SCHEMA_VERSION,
                "assessment_id": protocol.FINAL_O3_ASSESSMENT_ID,
                "record_keys": sorted(protocol.RUNTIME_FINAL_O3_ASSESSMENT_KEYS),
                "source_observation_hash_bound": True,
                "human_only_non_examiner": True,
                "creates_no_X4_or_I4_or_examiner_turn": True,
                "must_be_sealed_before_execution_gate_opens": True,
            },
            "hard_contradiction_precludes_resolved_or_full_repair": True,
        },
        "adaptive_human_interventions": {
            "I1": {
                "selection_after": "eligible O0 and recorded X1",
                "source_observation_hash_bound": True,
                "select_one_material_reasoning_relationship": True,
                "record_diagnosis_and_predicted_downstream_changes": True,
                "seal_before_any_C1_call": True,
            },
            "I2": {
                "selection_after": "eligible O1 and recorded X2",
                "source_observation_hash_bound": True,
                "must_cite_target_evidence_in_O1": True,
                "must_record_prior_delta_disposition": True,
                "record_predicted_downstream_and_execution_changes": True,
                "seal_before_any_C2_call": True,
            },
            "I3": {
                "selection_after": "eligible O2 and recorded X3",
                "source_observation_hash_bound": True,
                "must_reintegrate_the_cumulative_trajectory": True,
                "must_record_prior_delta_disposition": True,
                "record_predicted_final_observation_and_execution_changes": True,
                "seal_before_any_C3_call": True,
            },
            "exact_treatment_text_is_not_preloaded": True,
            "selection_rules_are_bound_not_treatment_wording": True,
            "seal_chronology_is_runtime_archive_verifiable": True,
            "each_seal_binds": [
                "source checkpoint and observation",
                "source observation SHA-256",
                "examination ID and charter ID",
                "examiner input SHA-256",
                "examiner output SHA-256",
                "UTC seal time",
            ],
            "review_streams": {
                "A": {
                    "type": "human researcher",
                    "independently_recorded": True,
                    "exact_bytes_and_input_artifact_hashes_archived": True,
                },
                "B": {
                    "type": "independent Sol/ChatGPT reviewer channel",
                    "model": "gpt-5.6-sol",
                    "reasoning_effort": "xhigh",
                    "harness": "chatgpt",
                    "independently_recorded": True,
                    "exact_bytes_and_input_artifact_hashes_archived": True,
                },
                "mutually_unseen_before_reconciliation": True,
                "neither_receives_raw_carrier_or_thought_signatures": True,
            },
            "reconciliation": {
                "exact_bytes_reference_both_review_hashes": True,
                "human_approval_identity_and_time_archived": True,
                "lock_after_examination_reviews_and_before_first_child_call": True,
                "only_reconciled_intervention_text_is_model_facing": True,
            },
        },
        "matched_execution": {
            "checkpoints": ["C0", "C1", "C2", "C3"],
            "replicates_per_checkpoint": 3,
            "execution_calls": 12,
            "shared_seed_within_replicate_quartet": True,
            "interleaved_frozen_schedule": True,
            "requires_eligible_O3_and_final_human_assessment_seal": True,
        },
        "adjudication": {
            "mode": "semantic_relational_human_review",
            "two_independent_review_streams_then_human_reconciliation": True,
            "private_raw_artifacts": True,
            "distinguishes_convergence_from_sophisticated_rationalization": True,
        },
        "gemini_logical_call_minimum": 20,
        "gemini_logical_call_maximum": 60,
        "gemini_physical_call_maximum": 180,
        "external_examiner_turns_exact": 3,
        "external_examiner_turns_excluded_from_gemini_call_bounds": True,
        "planned_calls": copy.deepcopy(definition["planned_calls"]),
        "execution_requires_exact_reviewed_freeze_id": True,
    }


def build_validation_report(
    definition: dict[str, Any], manifest: dict[str, Any], repo_root: Path
) -> dict[str, Any]:
    definition_errors: list[str] = []
    try:
        definition_errors.extend(
            protocol.validate_experiment_definition(definition, repo_root)
        )
    except Exception as exc:
        definition_errors.append(
            "protocol validation failed safely: "
            f"{type(exc).__name__}: {exc}"
        )
    definition_errors.extend(_iterative_semantics_errors(definition))
    definition_errors = list(dict.fromkeys(definition_errors))
    return {
        "schema_version": VALIDATION_SCHEMA,
        "validated": not definition_errors,
        "definition_errors": definition_errors,
        "source_file_count": manifest["source_file_count"],
        "source_closure_sha256": manifest["source_closure_sha256"],
        "dossier_document_count": definition["dossier"]["document_count"],
        "withheld_notes_sent_to_model": definition["dossier"][
            "withheld_notes_sent_to_model"
        ],
        "safe_file_allowlist": list(SAFE_FREEZE_FILES),
        "model_facing_json_readiness_envelope_present": False,
        "response_format_or_schema_present": False,
        "function_or_tool_structure_present": False,
        "preparation_transport_path_present": False,
        "preparation_credential_access_path_present": False,
        "raw_provider_artifacts_present": False,
        "exact_unmodified_live_continuation_frozen": (
            definition["planning"].get(
                "live_candidate_content_is_replayed_without_mutation"
            )
            is True
        ),
        "tomography_is_protocol_defined_primary_operator": (
            definition["isolation"].get("operator_status")
            == "protocol_defined_core_operator"
        ),
        "tomography_is_distinct_from_live_continuation": True,
        "adaptive_intervention_seals_gate_C1_C2_and_C3": (
            definition["state_machine"].get("human_seal_gates_cannot_be_bypassed")
            is True
        ),
        "final_human_O3_assessment_gates_execution_without_X4_or_I4": (
            definition["state_machine"].get(
                "execution_gate_requires_eligible_O3_and_final_human_assessment"
            )
            is True
            and definition["state_machine"].get("no_X4_or_I4_transition") is True
            and definition["observation_assessments"]["final_O3_assessment"].get(
                "human_only_non_examiner"
            )
            is True
        ),
        "gemini_logical_call_bounds": {"minimum": 20, "maximum": 60},
        "gemini_physical_call_maximum": 180,
        "external_examiner_turns_exact": 3,
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
    return {
        "schema_version": LOCK_SCHEMA,
        "freeze_id": _canonical_sha256(hashes),
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
    payload_bytes = {
        name: _json_bytes(value) for name, value in payload_values.items()
    }
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
    if not isinstance(expected_files, dict) or set(expected_files) != set(SOURCE_FILES):
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


def _invalid_verification(*errors: str) -> dict[str, Any]:
    return {
        "schema_version": VERIFICATION_SCHEMA,
        "valid": False,
        "freeze_id": None,
        "errors": list(errors),
        "safe_file_count": 0,
    }


def _verify_freeze(
    *, freeze_dir: Path, repo_root: Path, expected_freeze_id: str | None = None
) -> dict[str, Any]:
    errors: list[str] = []
    directory = freeze_dir.absolute()
    unsafe = first_link_or_reparse_component(directory)
    if unsafe is not None:
        return _invalid_verification(
            f"freeze path contains a link or reparse point: {unsafe}"
        )
    try:
        directory_metadata = directory.lstat()
    except FileNotFoundError:
        return _invalid_verification("freeze directory does not exist")
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if not stat.S_ISDIR(directory_metadata.st_mode) or bool(
        getattr(directory_metadata, "st_file_attributes", 0) & reparse_flag
    ):
        return _invalid_verification("freeze path is not a safe directory")
    if expected_freeze_id is not None and not _is_sha256(expected_freeze_id):
        errors.append("reviewed freeze ID is malformed")

    entries = _freeze_entry_names(directory)
    if entries != sorted(SAFE_FREEZE_FILES):
        errors.append("freeze entries differ from the exact safe allowlist")
    values: dict[str, Any] = {}
    raw: dict[str, bytes] = {}
    for name in SAFE_FREEZE_FILES:
        try:
            data = _read_stable_regular_file(directory / name, label=name)
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
            errors.extend(
                protocol.validate_experiment_definition(definition, repo_root)
            )
            errors.extend(_iterative_semantics_errors(definition))
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
        try:
            manifest_hash = _canonical_sha256(manifest)
        except (TypeError, ValueError, RecursionError) as exc:
            errors.append(f"manifest hash could not be derived safely: {exc}")
        else:
            if preregistration.get("manifest_canonical_sha256") != manifest_hash:
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
    """Verify untrusted freeze state without letting malformed input escape."""

    try:
        return _verify_freeze(
            freeze_dir=freeze_dir,
            repo_root=repo_root,
            expected_freeze_id=expected_freeze_id,
        )
    except Exception as exc:
        return _invalid_verification(
            "freeze verification failed safely: "
            f"{type(exc).__name__}: {exc}"
        )


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
