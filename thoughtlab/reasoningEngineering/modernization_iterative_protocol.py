"""Pure protocol for an iterative modernization reasoning-engineering study.

The protocol defines a fresh C0/O0 -> X1/I1 -> C1/O1 -> X2/I2 -> C2/O2 ->
X3/I3 -> C3/O3 trajectory.  It has no transport, credential, or
filesystem-write path.  Live planning replays native history without mutation
and exposes only raw READY/NOT_READY judgments.  Detached checkpoint
observation uses an explicitly protocol-defined carrier isolation operator;
that mutation is part of the experiment, not an exception to it.
"""

from __future__ import annotations

import copy
import hashlib
import random
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from thoughtlab.reasoningEngineering import modernization_protocol as base


SCHEMA_VERSION = "modernization_reasoning_engineering_iterative_protocol_v1"
PROTOCOL_REVISION = "modernization_reasoning_engineering_iterative_review_01"
EXPERIMENT_ID = "modernization_reasoning_engineering_iterative_01"
MODEL = base.MODEL
API = base.API
MASTER_SEED = 1182749365

CHECKPOINTS = ("C0", "C1", "C2", "C3")
OBSERVATIONS = ("O0", "O1", "O2", "O3")
EXAMINATIONS = ("X1", "X2", "X3")
INTERVENTIONS = ("I1", "I2", "I3")
CHECKPOINT_TO_OBSERVATION = dict(zip(CHECKPOINTS, OBSERVATIONS, strict=True))
CHECKPOINT_TO_PHASE = {
    "C0": "baseline",
    "C1": "after_i1",
    "C2": "after_i2",
    "C3": "after_i3",
}

MAX_PLANNING_TURNS_PER_CHECKPOINT = 6
EXECUTION_REPLICATES_PER_CHECKPOINT = 3
PRIMARY_INSPECTION_SEED_LABEL = "iterative:inspection:matched"
EXECUTION_SCHEDULE_SEED_LABEL = "iterative:execution:schedule"

READY = base.READY
NOT_READY = base.NOT_READY
SELF_DECLARED_NOT_READY = base.SELF_DECLARED_NOT_READY
UNOBSERVED_TRUNCATED = base.UNOBSERVED_TRUNCATED
INVALID_STATUS = base.INVALID_STATUS
PLANNING_THRESHOLD_REACHED = base.PLANNING_THRESHOLD_REACHED
OUTPUT_BUDGET_FINISH_REASONS = base.OUTPUT_BUDGET_FINISH_REASONS
COMPLETED_FINISH_REASONS = base.COMPLETED_FINISH_REASONS

PLANNING_SYSTEM_INSTRUCTION = base.PLANNING_SYSTEM_INSTRUCTION
CONTINUE_PLANNING_PROMPT = base.CONTINUE_PLANNING_PROMPT
PRIMARY_INSPECTION_PROMPT = base.PRIMARY_INSPECTION_PROMPT
EXECUTION_PROMPT = base.EXECUTION_PROMPT
INTERVENTION_PREFIX = base.INTERVENTION_PREFIX
INTERVENTION_SUFFIX = base.INTERVENTION_SUFFIX
EXECUTION_TRIGGER = base.EXECUTION_TRIGGER
NEUTRAL_CARRIER_STUB = base.NEUTRAL_CARRIER_STUB


STABLE_SEMANTIC_COMMITMENTS = (
    "institutional and cross-boundary root-cause diagnosis",
    "immediate containment of unsafe retry and identity-loss paths",
    "stable occurrence, correction, reversal, authorization, and settlement semantics",
    "benefit continuity and Treasury settlement finality",
    "gateway decoupling and phased, gated migration rather than blind rollback",
)

EXAMINATION_CHARTERS = {
    "X1": {
        "charter_id": "epistemic_hinge_audit_v1",
        "title": "epistemic hinge audit",
        "instruction": (
            "Identify one load-bearing interpretation, inference, source "
            "assessment, or assumption in O0. Test whether its evidential basis, "
            "provenance, uncertainty, and downstream commitments justify the "
            "weight placed on it. Select the most material evidenced hinge "
            "without supplying a replacement answer."
        ),
    },
    "X2": {
        "charter_id": "adversarial_alternative_falsification_audit_v1",
        "title": "adversarial alternative/falsification audit",
        "instruction": (
            "Using O1 and the recorded O0-to-O1 delta, identify the strongest "
            "materially plausible alternative, counterexample, or falsifying "
            "condition that the current preferred course has not adequately "
            "answered. Select a local challenge that could reopen or revise the "
            "decision without prescribing a replacement answer."
        ),
    },
    "X3": {
        "charter_id": "global_reintegration_joint_feasibility_audit_v1",
        "title": "global reintegration/joint-feasibility audit",
        "instruction": (
            "Reintegrate the whole O2 decision state after the first two local "
            "changes. Audit whether commitments, dependencies, resources, timing, "
            "authority, evidence requirements, contingencies, and fallbacks can "
            "hold together jointly. Select the most material remaining coupling, "
            "regression, or unsupported closure without prescribing an answer."
        ),
    },
}

INTERVENTION_SELECTION_RULES = {
    "I1": (
        "After X1 examines eligible O0 under the epistemic-hinge charter, select "
        "one material local relationship actually evidenced there. Challenge "
        "its basis without prescribing a replacement answer; predict localized "
        "observation and execution consequences; and identify unrelated "
        "commitments expected to remain stable."
    ),
    "I2": (
        "After X2 examines eligible O1 and the O0-to-O1 delta under the "
        "adversarial-alternative/falsification charter, adaptively select one "
        "material local target actually evidenced there. State which prior "
        "changes should persist, reverse, or remain unaffected; do not prescribe "
        "a replacement answer; and predict observation and execution effects."
    ),
    "I3": (
        "After X3 examines eligible O2 and the cumulative trajectory under the "
        "global-reintegration/joint-feasibility charter, adaptively select one "
        "material remaining coupling, regression, or unsupported closure. State "
        "which prior changes should persist, reverse, or remain unaffected; do "
        "not prescribe a replacement answer; and predict final observation and "
        "execution effects."
    ),
}

PRIVATE_FAULT_ATLAS = (
    {
        "fault_id": "EVIDENCE_INFERENCE_CONFLATION",
        "description": "A source claim, observation, or correlation is treated as an inference or conclusion without preserving the distinction.",
    },
    {
        "fault_id": "PROVENANCE_WEIGHTING_FAILURE",
        "description": "Source authority, incentives, scope, reliability, disagreement, or missing visibility is weighted inappropriately.",
    },
    {
        "fault_id": "UNSUPPORTED_COMMITMENT",
        "description": "A major commitment lacks an adequate evidential or inferential basis.",
    },
    {
        "fault_id": "FAVORABLE_BOUND_SELECTION",
        "description": "A plan assumes favorable points within separate ranges will occur together without bounding that conjunction.",
    },
    {
        "fault_id": "RESOURCE_COLLISION",
        "description": "Multiple commitments consume the same non-fungible funding, capacity, or specialist resource at the same time.",
    },
    {
        "fault_id": "CALENDAR_COLLISION",
        "description": "Durations, readiness conditions, freezes, evidence windows, or dated commitments cannot coexist as represented.",
    },
    {
        "fault_id": "AUTHORITY_MISMATCH",
        "description": "A decision, obligation, or fallback is assigned to an actor without the authority needed to perform it.",
    },
    {
        "fault_id": "DEPENDENCY_CYCLE",
        "description": "Commitments or prerequisites form a circular path with no independently supportable entry condition.",
    },
    {
        "fault_id": "UNBOUNDED_CRITICAL_UNCERTAINTY",
        "description": "An unresolved uncertainty could materially change the decision but lacks an evidence plan, bound, or revision rule.",
    },
    {
        "fault_id": "FALLBACK_WITHOUT_TRIGGER",
        "description": "A fallback is named without a condition that determines when it becomes operative.",
    },
    {
        "fault_id": "TRIGGER_WITHOUT_ACTIONABLE_FALLBACK",
        "description": "A failure condition is specified but its consequence is unactionable, unfunded, unauthorized, or undefined.",
    },
    {
        "fault_id": "ALTERNATIVE_PREMATURELY_DISCARDED",
        "description": "A materially plausible alternative is rejected before its strongest evidence and tradeoffs are tested.",
    },
    {
        "fault_id": "LOCAL_GLOBAL_INCONSISTENCY",
        "description": "Individual components appear coherent while the integrated architecture remains jointly inconsistent.",
    },
    {
        "fault_id": "COLLATERAL_DRIFT",
        "description": "A local challenge moves unrelated commitments without a justified dependency.",
    },
    {
        "fault_id": "SOPHISTICATED_RATIONALIZATION",
        "description": "A polished explanation renames or surrounds a contradiction without repairing it.",
    },
)

SEMANTIC_HUMAN_RUBRIC = (
    {
        "dimension": "defect_recognition",
        "anchors": {"0": "defect missed, denied, or misunderstood", "1": "defect partly or verbally recognized", "2": "defect and its decision role accurately recognized"},
    },
    {
        "dimension": "resolution",
        "anchors": {"0": "unresolved or rationalized", "1": "bounded", "2": "resolved"},
    },
    {
        "dimension": "dependency_propagation",
        "anchors": {"0": "material consequences ignored", "1": "consequences partly propagated", "2": "material dependencies, consequences, and revision conditions propagated"},
    },
    {
        "dimension": "locality",
        "anchors": {"0": "wholesale re-solve", "1": "mixed local repair and collateral movement", "2": "stable unrelated commitments"},
    },
    {
        "dimension": "evidentiary_discipline",
        "anchors": {"0": "evidence, inference, or provenance conflated", "1": "mixed evidentiary discipline", "2": "evidence, inference, provenance, and uncertainty appropriately distinguished"},
    },
    {
        "dimension": "joint_coherence",
        "anchors": {"0": "contradiction remains", "1": "joint feasibility remains uncertain", "2": "jointly feasible"},
    },
)
RUBRIC_DIMENSIONS = tuple(row["dimension"] for row in SEMANTIC_HUMAN_RUBRIC)

DIAGNOSTIC_STATES = (
    "UNRECOGNIZED",
    "RECOGNIZED",
    "BOUNDED",
    "RESOLVED",
    "RATIONALIZED",
)
DIAGNOSTIC_STATE_DEFINITIONS = {
    "UNRECOGNIZED": "The targeted fault is absent, denied, or materially misunderstood.",
    "RECOGNIZED": "The fault is named accurately but remains live and materially unbounded.",
    "BOUNDED": "The fault remains uncertain but its decision effects and revision conditions are constrained.",
    "RESOLVED": "The contradiction or dependency is coherently repaired and propagated.",
    "RATIONALIZED": "The account appears coherent while the contradiction persists or is replaced by an unsupported assumption.",
}
HARD_CONTRADICTION_GATE = (
    "A live hard contradiction in the targeted relationship prevents RESOLVED "
    "and full-repair adjudication regardless of descriptive rubric scores."
)

OBSERVATION_ASSESSMENT_TARGETS = {
    "O0": ("I1",),
    "O1": ("I1", "I2"),
    "O2": ("I1", "I2", "I3"),
    "O3": ("I1", "I2", "I3"),
}
OBSERVATION_ASSESSMENT_KEYS = frozenset(
    {
        "observation_id",
        "assessed_by",
        "assessment_basis",
        "rubric_scores",
        "target_diagnostic_states",
    }
)
TARGET_DIAGNOSTIC_STATE_KEYS = frozenset(
    {"state", "evidence", "hard_contradiction_present"}
)
FINAL_O3_ASSESSMENT_SCHEMA_VERSION = "iterative_final_o3_assessment_seal_v1"
FINAL_O3_ASSESSMENT_ID = "FINAL_O3_PRE_EXECUTION_HUMAN_ASSESSMENT"
RUNTIME_FINAL_O3_ASSESSMENT_KEYS = frozenset(
    {
        "schema_version",
        "assessment_id",
        "source_checkpoint",
        "source_observation",
        "source_observation_sha256",
        "seal_status",
        "sealed_at",
        "assessment",
    }
)

INTERVENTION_SPECS: dict[str, dict[str, Any]] = {
    "I1": {
        "examination_id": "X1",
        "examination_charter_id": EXAMINATION_CHARTERS["X1"]["charter_id"],
        "selection_rule_id": "adaptive_epistemic_hinge_after_o0_v1",
        "selection_rule": INTERVENTION_SELECTION_RULES["I1"],
        "source_checkpoint": "C0",
        "source_observation": "O0",
        "target_checkpoint": "C1",
        "human_seal_status": "SEALED_AFTER_O0",
    },
    "I2": {
        "examination_id": "X2",
        "examination_charter_id": EXAMINATION_CHARTERS["X2"]["charter_id"],
        "selection_rule_id": "adaptive_falsification_after_o1_v1",
        "selection_rule": INTERVENTION_SELECTION_RULES["I2"],
        "source_checkpoint": "C1",
        "source_observation": "O1",
        "target_checkpoint": "C2",
        "human_seal_status": "SEALED_AFTER_O1",
    },
    "I3": {
        "examination_id": "X3",
        "examination_charter_id": EXAMINATION_CHARTERS["X3"]["charter_id"],
        "selection_rule_id": "adaptive_joint_feasibility_after_o2_v1",
        "selection_rule": INTERVENTION_SELECTION_RULES["I3"],
        "source_checkpoint": "C2",
        "source_observation": "O2",
        "target_checkpoint": "C3",
        "human_seal_status": "SEALED_AFTER_O2",
    },
}

NO_PRIOR_INTERVENTION = "NO_PRIOR_INTERVENTION"
PRIOR_DELTA_DISPOSITION_KEYS = frozenset(
    {"persist", "reverse", "remain_unaffected"}
)
HUMAN_AUTHORED_INTERVENTION_KEYS = frozenset(
    {
        "reviewer_A",
        "reviewer_B",
        "reconciliation",
        "diagnosis",
        "observation_evidence",
        "targeted_reasoning_relationship",
        "predicted_observation_changes",
        "predicted_execution_changes",
        "prior_delta_disposition",
        "expected_stable_commitments",
        "source_observation_assessment",
        "intervention_text",
    }
)
REVIEW_STREAM_KEYS = frozenset(
    {
        "provenance",
        "diagnosis",
        "observation_evidence",
        "targeted_reasoning_relationship",
        "predicted_observation_changes",
        "predicted_execution_changes",
        "proposed_intervention_text",
    }
)
REVIEWER_PROVENANCE_REQUIREMENTS = {
    "reviewer_A": {
        "reviewer_type": "human",
        "identity": "human_researcher",
        "model": "none",
        "reasoning_effort": "human",
        "harness": "human_review",
    },
    "reviewer_B": {
        "reviewer_type": "model",
        "identity": "independent_sol_chatgpt_reviewer_channel",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "xhigh",
        "harness": "chatgpt",
    },
}
REVIEWER_PROVENANCE_KEYS = frozenset(
    {"reviewer_type", "identity", "model", "reasoning_effort", "harness", "input_sha256"}
)
RECONCILIATION_KEYS = frozenset(
    {
        "approved_by",
        "basis",
        "reviewer_A_disposition",
        "reviewer_B_disposition",
    }
)
RUNTIME_INTERVENTION_SEAL_KEYS = frozenset(
    {
        "schema_version",
        "intervention_id",
        "examination_id",
        "examination_charter_id",
        "examiner_input_sha256",
        "examiner_output_sha256",
        "selection_rule_id",
        "source_checkpoint",
        "source_observation",
        "source_observation_sha256",
        "target_checkpoint",
        "seal_status",
        "sealed_at",
    }
)
SEALED_INTERVENTION_RECORD_KEYS = (
    HUMAN_AUTHORED_INTERVENTION_KEYS | RUNTIME_INTERVENTION_SEAL_KEYS
)
HUMAN_INTERVENTION_SCHEMA_VERSION = "iterative_human_intervention_seal_v1"

ADJUDICATION_LABELS = (
    "SUPPORTED",
    "PARTIALLY_SUPPORTED",
    "NOT_SUPPORTED",
    "INDETERMINATE_TECHNICAL",
)


PREPARED_UNEXECUTED = "PREPARED_UNEXECUTED"
C0_PLANNING = "C0_PLANNING"
C0_READY_AWAITING_O0 = "C0_READY_AWAITING_O0"
X1_EXAMINATION_PENDING = "X1_EXAMINATION_PENDING"
AWAITING_I1_HUMAN_SEAL = "AWAITING_I1_HUMAN_SEAL"
I1_SEALED = "I1_SEALED"
C1_PLANNING = "C1_PLANNING"
C1_READY_AWAITING_O1 = "C1_READY_AWAITING_O1"
X2_EXAMINATION_PENDING = "X2_EXAMINATION_PENDING"
AWAITING_I2_HUMAN_SEAL = "AWAITING_I2_HUMAN_SEAL"
I2_SEALED = "I2_SEALED"
C2_PLANNING = "C2_PLANNING"
C2_READY_AWAITING_O2 = "C2_READY_AWAITING_O2"
X3_EXAMINATION_PENDING = "X3_EXAMINATION_PENDING"
AWAITING_I3_HUMAN_SEAL = "AWAITING_I3_HUMAN_SEAL"
I3_SEALED = "I3_SEALED"
C3_PLANNING = "C3_PLANNING"
C3_READY_AWAITING_O3 = "C3_READY_AWAITING_O3"
FINAL_O3_ASSESSMENT_PENDING = "FINAL_O3_ASSESSMENT_PENDING"
EXECUTION_GATE_OPEN = "EXECUTION_GATE_OPEN"
EXECUTIONS_RUNNING = "EXECUTIONS_RUNNING"
COMPLETED_EVIDENCE_CHAIN = "COMPLETED_EVIDENCE_CHAIN"

TRANSITION_ROWS: tuple[dict[str, str], ...] = (
    {
        "from": PREPARED_UNEXECUTED,
        "event": "AUTHORIZE_C0",
        "to": C0_PLANNING,
    },
    {"from": C0_PLANNING, "event": "CONTINUE_PLANNING", "to": C0_PLANNING},
    {"from": C0_PLANNING, "event": "READY_C0", "to": C0_READY_AWAITING_O0},
    {
        "from": C0_READY_AWAITING_O0,
        "event": "O0_ELIGIBLE",
        "to": X1_EXAMINATION_PENDING,
    },
    {
        "from": X1_EXAMINATION_PENDING,
        "event": "RECORD_X1",
        "to": AWAITING_I1_HUMAN_SEAL,
    },
    {
        "from": AWAITING_I1_HUMAN_SEAL,
        "event": "SEAL_I1",
        "to": I1_SEALED,
    },
    {"from": I1_SEALED, "event": "BEGIN_C1", "to": C1_PLANNING},
    {"from": C1_PLANNING, "event": "CONTINUE_PLANNING", "to": C1_PLANNING},
    {"from": C1_PLANNING, "event": "READY_C1", "to": C1_READY_AWAITING_O1},
    {
        "from": C1_READY_AWAITING_O1,
        "event": "O1_ELIGIBLE",
        "to": X2_EXAMINATION_PENDING,
    },
    {
        "from": X2_EXAMINATION_PENDING,
        "event": "RECORD_X2",
        "to": AWAITING_I2_HUMAN_SEAL,
    },
    {
        "from": AWAITING_I2_HUMAN_SEAL,
        "event": "SEAL_I2",
        "to": I2_SEALED,
    },
    {"from": I2_SEALED, "event": "BEGIN_C2", "to": C2_PLANNING},
    {"from": C2_PLANNING, "event": "CONTINUE_PLANNING", "to": C2_PLANNING},
    {"from": C2_PLANNING, "event": "READY_C2", "to": C2_READY_AWAITING_O2},
    {
        "from": C2_READY_AWAITING_O2,
        "event": "O2_ELIGIBLE",
        "to": X3_EXAMINATION_PENDING,
    },
    {
        "from": X3_EXAMINATION_PENDING,
        "event": "RECORD_X3",
        "to": AWAITING_I3_HUMAN_SEAL,
    },
    {
        "from": AWAITING_I3_HUMAN_SEAL,
        "event": "SEAL_I3",
        "to": I3_SEALED,
    },
    {"from": I3_SEALED, "event": "BEGIN_C3", "to": C3_PLANNING},
    {"from": C3_PLANNING, "event": "CONTINUE_PLANNING", "to": C3_PLANNING},
    {"from": C3_PLANNING, "event": "READY_C3", "to": C3_READY_AWAITING_O3},
    {
        "from": C3_READY_AWAITING_O3,
        "event": "O3_ELIGIBLE",
        "to": FINAL_O3_ASSESSMENT_PENDING,
    },
    {
        "from": FINAL_O3_ASSESSMENT_PENDING,
        "event": "SEAL_FINAL_O3_ASSESSMENT",
        "to": EXECUTION_GATE_OPEN,
    },
    {
        "from": EXECUTION_GATE_OPEN,
        "event": "BEGIN_MATCHED_EXECUTIONS",
        "to": EXECUTIONS_RUNNING,
    },
    {
        "from": EXECUTIONS_RUNNING,
        "event": "COMPLETE_MATCHED_EXECUTIONS",
        "to": COMPLETED_EVIDENCE_CHAIN,
    },
)

TERMINAL_STATUSES = (
    COMPLETED_EVIDENCE_CHAIN,
    "C0_PLANNING_THRESHOLD_REACHED",
    "C1_PLANNING_THRESHOLD_REACHED",
    "C2_PLANNING_THRESHOLD_REACHED",
    "C3_PLANNING_THRESHOLD_REACHED",
    "C0_TECHNICAL_TERMINATION",
    "C1_TECHNICAL_TERMINATION",
    "C2_TECHNICAL_TERMINATION",
    "C3_TECHNICAL_TERMINATION",
    "O0_PRIMARY_OBSERVATION_INVALID",
    "O1_PRIMARY_OBSERVATION_INVALID",
    "O2_PRIMARY_OBSERVATION_INVALID",
    "O3_PRIMARY_OBSERVATION_INVALID",
    "FINAL_O3_ASSESSMENT_INVALID",
    "NO_VALID_I1_TARGET",
    "NO_VALID_I2_TARGET",
    "NO_VALID_I3_TARGET",
    "EXECUTION_MEASUREMENT_INCOMPLETE",
)

_TRANSITION_MAP = {
    (row["from"], row["event"]): row["to"] for row in TRANSITION_ROWS
}


def derived_seed(label: str) -> int:
    digest = hashlib.sha256(f"{MASTER_SEED}:{label}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def generation_config(*, kind: str, seed_label: str) -> dict[str, Any]:
    if kind == "planning":
        maximum = base.PLANNING_MAX_OUTPUT_TOKENS
    elif kind == "inspection":
        maximum = base.INSPECTION_MAX_OUTPUT_TOKENS
    elif kind == "execution":
        maximum = base.EXECUTION_MAX_OUTPUT_TOKENS
    else:
        raise ValueError(f"unknown generation-config kind: {kind}")
    return {
        "temperature": 0.0,
        "thinkingConfig": {"thinkingLevel": "high"},
        "seed": derived_seed(seed_label),
        "maxOutputTokens": maximum,
    }


def execution_seed_label(replicate: int) -> str:
    if not 1 <= replicate <= EXECUTION_REPLICATES_PER_CHECKPOINT:
        raise ValueError("invalid execution replicate")
    return f"iterative:execution:replicate:{replicate}"


def build_execution_schedule() -> list[dict[str, Any]]:
    """Build three matched, randomized four-checkpoint quartets."""

    rng = random.Random(derived_seed(EXECUTION_SCHEDULE_SEED_LABEL))
    schedule: list[dict[str, Any]] = []
    for replicate in range(1, EXECUTION_REPLICATES_PER_CHECKPOINT + 1):
        checkpoints = list(CHECKPOINTS)
        rng.shuffle(checkpoints)
        for checkpoint in checkpoints:
            schedule.append(
                {
                    "order": len(schedule) + 1,
                    "checkpoint": checkpoint,
                    "replicate": replicate,
                }
            )
    return schedule


def _exact_history_copy(full_history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(full_history, list) or not full_history:
        raise ValueError("live history must be a nonempty list")
    source_hash = base.sha256_json(full_history)
    replay = copy.deepcopy(full_history)
    if replay != full_history or base.sha256_json(full_history) != source_hash:
        raise RuntimeError("live-history replay mutated its source")
    return replay


def _planning_seed_label(checkpoint: str, turn_number: int) -> str:
    if checkpoint not in CHECKPOINTS:
        raise ValueError("invalid checkpoint")
    if not 1 <= turn_number <= MAX_PLANNING_TURNS_PER_CHECKPOINT:
        raise ValueError("invalid planning turn number")
    return f"iterative:{checkpoint.lower()}:turn:{turn_number}"


def initial_planning_body(*, task_text: str) -> dict[str, Any]:
    return base.generate_content_body(
        contents=[base.user_step(task_text)],
        system_instruction=PLANNING_SYSTEM_INSTRUCTION,
        config=generation_config(
            kind="planning", seed_label=_planning_seed_label("C0", 1)
        ),
    )


def planning_continuation_body(
    *,
    full_history: list[dict[str, Any]],
    checkpoint: str,
    turn_number: int,
) -> dict[str, Any]:
    if turn_number < 2:
        raise ValueError("continuation turn number must be at least two")
    replay = _exact_history_copy(full_history)
    return base.generate_content_body(
        contents=[*replay, base.user_step(CONTINUE_PLANNING_PROMPT)],
        system_instruction=PLANNING_SYSTEM_INSTRUCTION,
        config=generation_config(
            kind="planning",
            seed_label=_planning_seed_label(checkpoint, turn_number),
        ),
    )


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _required_text(record: Mapping[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"human intervention record has invalid {key}")
    return value.strip()


def _validate_observation_evidence(value: Any, *, label: str) -> None:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise ValueError(f"{label} has invalid observation_evidence")


def _validate_review_stream(
    value: Any, *, reviewer: str
) -> None:
    if not isinstance(value, Mapping) or set(value) != REVIEW_STREAM_KEYS:
        raise ValueError(f"{reviewer} review stream has unexpected fields")
    provenance = value.get("provenance")
    if not isinstance(provenance, Mapping) or set(provenance) != (
        REVIEWER_PROVENANCE_KEYS
    ):
        raise ValueError(f"{reviewer} review stream has invalid provenance")
    required_provenance = REVIEWER_PROVENANCE_REQUIREMENTS[reviewer]
    if any(provenance.get(key) != expected for key, expected in required_provenance.items()):
        raise ValueError(f"{reviewer} review stream has invalid provenance")
    if not _is_sha256(provenance.get("input_sha256")):
        raise ValueError(f"{reviewer} review stream has invalid provenance input hash")
    for key in (
        "diagnosis",
        "targeted_reasoning_relationship",
        "predicted_observation_changes",
        "predicted_execution_changes",
        "proposed_intervention_text",
    ):
        _required_text(value, key)
    _validate_observation_evidence(value.get("observation_evidence"), label=reviewer)
    if EXECUTION_TRIGGER in str(value["proposed_intervention_text"]):
        raise ValueError(f"{reviewer} proposed intervention contains execution trigger")


def _validate_reconciliation(value: Any) -> None:
    if not isinstance(value, Mapping) or set(value) != RECONCILIATION_KEYS:
        raise ValueError("reconciliation has unexpected fields")
    if value.get("approved_by") != "human_researcher":
        raise ValueError("reconciliation is not human-approved")
    for key in (
        "basis",
        "reviewer_A_disposition",
        "reviewer_B_disposition",
    ):
        _required_text(value, key)


def _validated_utc_timestamp(value: Any) -> str:
    if not isinstance(value, str) or not value.endswith("Z") or "T" not in value:
        raise ValueError("runtime seal has invalid sealed_at UTC timestamp")
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError as exc:
        raise ValueError("runtime seal has invalid sealed_at UTC timestamp") from exc
    if parsed.utcoffset() != timedelta(0):
        raise ValueError("runtime seal has invalid sealed_at UTC timestamp")
    return value


def _validate_observation_assessment(
    value: Any, *, observation_id: str
) -> dict[str, Any]:
    """Validate one human semantic readout against the common O0--O3 rubric."""

    if observation_id not in OBSERVATION_ASSESSMENT_TARGETS:
        raise ValueError("invalid observation assessment id")
    if not isinstance(value, Mapping) or set(value) != OBSERVATION_ASSESSMENT_KEYS:
        raise ValueError(f"{observation_id} assessment has unexpected fields")
    if value.get("observation_id") != observation_id:
        raise ValueError(f"{observation_id} assessment has invalid observation_id")
    if value.get("assessed_by") != "human_researcher":
        raise ValueError(f"{observation_id} assessment is not human-authored")
    basis = value.get("assessment_basis")
    if not isinstance(basis, str) or not basis.strip():
        raise ValueError(f"{observation_id} assessment has invalid assessment_basis")

    scores = value.get("rubric_scores")
    if not isinstance(scores, Mapping) or set(scores) != set(RUBRIC_DIMENSIONS):
        raise ValueError(f"{observation_id} assessment has invalid rubric_scores")
    for dimension in RUBRIC_DIMENSIONS:
        score = scores.get(dimension)
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 2:
            raise ValueError(f"{observation_id} assessment has invalid rubric_scores")

    diagnostic_states = value.get("target_diagnostic_states")
    expected_targets = set(OBSERVATION_ASSESSMENT_TARGETS[observation_id])
    if not isinstance(diagnostic_states, Mapping) or set(diagnostic_states) != (
        expected_targets
    ):
        raise ValueError(
            f"{observation_id} assessment has invalid target_diagnostic_states"
        )
    hard_contradiction_present = False
    for intervention_id in OBSERVATION_ASSESSMENT_TARGETS[observation_id]:
        target_state = diagnostic_states.get(intervention_id)
        if not isinstance(target_state, Mapping) or set(target_state) != (
            TARGET_DIAGNOSTIC_STATE_KEYS
        ):
            raise ValueError(
                f"{observation_id} assessment has invalid state for {intervention_id}"
            )
        if target_state.get("state") not in DIAGNOSTIC_STATES:
            raise ValueError(
                f"{observation_id} assessment has invalid state for {intervention_id}"
            )
        evidence = target_state.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError(
                f"{observation_id} assessment has invalid evidence for {intervention_id}"
            )
        contradiction = target_state.get("hard_contradiction_present")
        if not isinstance(contradiction, bool):
            raise ValueError(
                f"{observation_id} assessment has invalid hard contradiction flag "
                f"for {intervention_id}"
            )
        if contradiction and target_state.get("state") == "RESOLVED":
            raise ValueError(
                f"{observation_id} assessment cannot mark a contradicted target RESOLVED"
            )
        hard_contradiction_present = hard_contradiction_present or contradiction
    if hard_contradiction_present and (
        scores["resolution"] == 2 or scores["joint_coherence"] == 2
    ):
        raise ValueError(
            f"{observation_id} assessment scores conflict with a hard contradiction"
        )
    return copy.deepcopy(dict(value))


def seal_final_o3_assessment(
    human_assessment: Mapping[str, Any],
    *,
    source_observation_sha256: str,
    sealed_at: str,
) -> dict[str, Any]:
    """Seal the human-only O3 readout that opens the execution gate."""

    assessment = _validate_observation_assessment(
        human_assessment, observation_id="O3"
    )
    if not _is_sha256(source_observation_sha256):
        raise ValueError("source observation hash is invalid")
    timestamp = _validated_utc_timestamp(sealed_at)
    return {
        "schema_version": FINAL_O3_ASSESSMENT_SCHEMA_VERSION,
        "assessment_id": FINAL_O3_ASSESSMENT_ID,
        "source_checkpoint": "C3",
        "source_observation": "O3",
        "source_observation_sha256": source_observation_sha256,
        "seal_status": "SEALED_BEFORE_MATCHED_EXECUTIONS",
        "sealed_at": timestamp,
        "assessment": assessment,
    }


def validate_final_o3_assessment_record(
    record: Mapping[str, Any], *, expected_observation_sha256: str
) -> dict[str, Any]:
    """Validate the non-examiner O3 assessment before execution begins."""

    if not isinstance(record, Mapping) or set(record) != (
        RUNTIME_FINAL_O3_ASSESSMENT_KEYS
    ):
        raise ValueError("final O3 assessment record has unexpected fields")
    if not _is_sha256(expected_observation_sha256):
        raise ValueError("expected observation hash is invalid")
    exact_values = {
        "schema_version": FINAL_O3_ASSESSMENT_SCHEMA_VERSION,
        "assessment_id": FINAL_O3_ASSESSMENT_ID,
        "source_checkpoint": "C3",
        "source_observation": "O3",
        "source_observation_sha256": expected_observation_sha256,
        "seal_status": "SEALED_BEFORE_MATCHED_EXECUTIONS",
    }
    for key, expected in exact_values.items():
        if record.get(key) != expected:
            raise ValueError(f"final O3 assessment record has invalid {key}")
    _validated_utc_timestamp(record.get("sealed_at"))
    _validate_observation_assessment(record.get("assessment"), observation_id="O3")
    return copy.deepcopy(dict(record))


def validate_human_intervention_draft(
    record: Mapping[str, Any], *, intervention_id: str
) -> dict[str, Any]:
    """Validate only the fields authored after the source observation."""

    if intervention_id not in INTERVENTION_SPECS:
        raise ValueError("invalid intervention id")
    if not isinstance(record, Mapping):
        raise ValueError("human intervention draft is not an object")
    if set(record) != HUMAN_AUTHORED_INTERVENTION_KEYS:
        raise ValueError("human intervention draft has unexpected fields")

    for key in (
        "diagnosis",
        "targeted_reasoning_relationship",
        "predicted_observation_changes",
        "predicted_execution_changes",
        "intervention_text",
    ):
        _required_text(record, key)

    _validate_review_stream(record.get("reviewer_A"), reviewer="reviewer_A")
    _validate_review_stream(record.get("reviewer_B"), reviewer="reviewer_B")
    _validate_reconciliation(record.get("reconciliation"))
    _validate_observation_evidence(
        record.get("observation_evidence"), label="human intervention draft"
    )
    _validate_observation_assessment(
        record.get("source_observation_assessment"),
        observation_id=INTERVENTION_SPECS[intervention_id]["source_observation"],
    )

    disposition = record.get("prior_delta_disposition")
    if not isinstance(disposition, Mapping) or set(disposition) != (
        PRIOR_DELTA_DISPOSITION_KEYS
    ):
        raise ValueError("human intervention draft has invalid prior_delta_disposition")
    for key in PRIOR_DELTA_DISPOSITION_KEYS:
        value = disposition.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                "human intervention draft has invalid prior_delta_disposition"
            )
    if intervention_id == "I1":
        if set(disposition.values()) != {NO_PRIOR_INTERVENTION}:
            raise ValueError("I1 has no prior intervention delta to classify")
    elif all(value == NO_PRIOR_INTERVENTION for value in disposition.values()):
        raise ValueError(f"{intervention_id} must classify the prior delta")

    intervention_text = str(record["intervention_text"]).strip()
    if EXECUTION_TRIGGER in intervention_text:
        raise ValueError("intervention text contains the execution trigger")
    stable = record.get("expected_stable_commitments")
    if stable != list(STABLE_SEMANTIC_COMMITMENTS):
        raise ValueError("human intervention draft changed stable commitments")
    return copy.deepcopy(dict(record))


def seal_human_intervention_record(
    human_record: Mapping[str, Any],
    *,
    intervention_id: str,
    source_observation_sha256: str,
    examiner_input_sha256: str,
    examiner_output_sha256: str,
    sealed_at: str,
) -> dict[str, Any]:
    """Add runtime-owned source binding and UTC seal metadata to a draft."""

    draft = validate_human_intervention_draft(
        human_record, intervention_id=intervention_id
    )
    if not _is_sha256(source_observation_sha256):
        raise ValueError("source observation hash is invalid")
    if not _is_sha256(examiner_input_sha256):
        raise ValueError("examiner input hash is invalid")
    if not _is_sha256(examiner_output_sha256):
        raise ValueError("examiner output hash is invalid")
    reviewer_b_provenance = draft["reviewer_B"]["provenance"]
    if reviewer_b_provenance["input_sha256"] != examiner_input_sha256:
        raise ValueError("examiner input hash conflicts with reviewer_B provenance")
    timestamp = _validated_utc_timestamp(sealed_at)
    spec = INTERVENTION_SPECS[intervention_id]
    runtime_fields = {
        "schema_version": HUMAN_INTERVENTION_SCHEMA_VERSION,
        "intervention_id": intervention_id,
        "examination_id": spec["examination_id"],
        "examination_charter_id": spec["examination_charter_id"],
        "examiner_input_sha256": examiner_input_sha256,
        "examiner_output_sha256": examiner_output_sha256,
        "selection_rule_id": spec["selection_rule_id"],
        "source_checkpoint": spec["source_checkpoint"],
        "source_observation": spec["source_observation"],
        "source_observation_sha256": source_observation_sha256,
        "target_checkpoint": spec["target_checkpoint"],
        "seal_status": spec["human_seal_status"],
        "sealed_at": timestamp,
    }
    return {**runtime_fields, **draft}


def validate_human_intervention_record(
    record: Mapping[str, Any],
    *,
    intervention_id: str,
    expected_observation_sha256: str,
) -> dict[str, Any]:
    """Validate a runtime-sealed record before constructing a model request."""

    if intervention_id not in INTERVENTION_SPECS:
        raise ValueError("invalid intervention id")
    if not isinstance(record, Mapping):
        raise ValueError("human intervention record is not an object")
    if set(record) != SEALED_INTERVENTION_RECORD_KEYS:
        raise ValueError("sealed intervention record has unexpected fields")
    if not _is_sha256(expected_observation_sha256):
        raise ValueError("expected observation hash is invalid")

    spec = INTERVENTION_SPECS[intervention_id]
    exact_values = {
        "schema_version": HUMAN_INTERVENTION_SCHEMA_VERSION,
        "intervention_id": intervention_id,
        "examination_id": spec["examination_id"],
        "examination_charter_id": spec["examination_charter_id"],
        "selection_rule_id": spec["selection_rule_id"],
        "source_checkpoint": spec["source_checkpoint"],
        "source_observation": spec["source_observation"],
        "source_observation_sha256": expected_observation_sha256,
        "target_checkpoint": spec["target_checkpoint"],
        "seal_status": spec["human_seal_status"],
    }
    for key, expected in exact_values.items():
        if record.get(key) != expected:
            raise ValueError(f"sealed intervention record has invalid {key}")
    _validated_utc_timestamp(record.get("sealed_at"))
    for key in ("examiner_input_sha256", "examiner_output_sha256"):
        if not _is_sha256(record.get(key)):
            raise ValueError(f"sealed intervention record has invalid {key}")
    draft = {
        key: record[key] for key in HUMAN_AUTHORED_INTERVENTION_KEYS
    }
    validate_human_intervention_draft(draft, intervention_id=intervention_id)
    if (
        draft["reviewer_B"]["provenance"]["input_sha256"]
        != record["examiner_input_sha256"]
    ):
        raise ValueError("sealed examiner input does not bind reviewer_B provenance")
    return copy.deepcopy(dict(record))


def intervention_body(
    *,
    parent_ready_history: list[dict[str, Any]],
    intervention_id: str,
    sealed_record: Mapping[str, Any],
    source_observation_sha256: str,
) -> dict[str, Any]:
    record = validate_human_intervention_record(
        sealed_record,
        intervention_id=intervention_id,
        expected_observation_sha256=source_observation_sha256,
    )
    replay = _exact_history_copy(parent_ready_history)
    target = str(INTERVENTION_SPECS[intervention_id]["target_checkpoint"])
    prompt = (
        f"{INTERVENTION_PREFIX}{record['intervention_text'].strip()}\n\n"
        f"{INTERVENTION_SUFFIX}"
    )
    return base.generate_content_body(
        contents=[*replay, base.user_step(prompt)],
        system_instruction=PLANNING_SYSTEM_INSTRUCTION,
        config=generation_config(
            kind="planning", seed_label=_planning_seed_label(target, 1)
        ),
    )


def isolate_checkpoint_carrier(
    response_steps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply the core protocol's detached blank-text signed-Part operator."""

    return base.isolate_response_steps(response_steps)


def inspection_body(
    *, response_steps: list[dict[str, Any]], checkpoint: str
) -> dict[str, Any]:
    if checkpoint not in CHECKPOINTS:
        raise ValueError("invalid checkpoint")
    carrier = isolate_checkpoint_carrier(response_steps)
    return base.generate_content_body(
        contents=[*carrier, base.user_step(PRIMARY_INSPECTION_PROMPT)],
        config=generation_config(
            kind="inspection", seed_label=PRIMARY_INSPECTION_SEED_LABEL
        ),
    )


def execution_body(
    *,
    full_history: list[dict[str, Any]],
    checkpoint: str,
    replicate: int,
) -> dict[str, Any]:
    if checkpoint not in CHECKPOINTS:
        raise ValueError("invalid checkpoint")
    replay = _exact_history_copy(full_history)
    return base.generate_content_body(
        contents=[*replay, base.user_step(EXECUTION_PROMPT)],
        system_instruction=PLANNING_SYSTEM_INSTRUCTION,
        config=generation_config(
            kind="execution", seed_label=execution_seed_label(replicate)
        ),
    )


def advance_stage(status: str, event: str) -> str:
    """Advance only through the frozen observation and human-seal gates."""

    try:
        return _TRANSITION_MAP[(status, event)]
    except KeyError as exc:
        raise ValueError(f"event {event!r} is invalid from status {status!r}") from exc


def build_experiment_definition(repo_root: Path) -> dict[str, Any]:
    documents = base.load_dossier(repo_root)
    task_text = base.assemble_task_text(documents)
    planning_configs = {
        checkpoint: [
            generation_config(
                kind="planning",
                seed_label=_planning_seed_label(checkpoint, turn),
            )
            for turn in range(1, MAX_PLANNING_TURNS_PER_CHECKPOINT + 1)
        ]
        for checkpoint in CHECKPOINTS
    }
    execution_configs = {
        checkpoint: [
            generation_config(
                kind="execution", seed_label=execution_seed_label(replicate)
            )
            for replicate in range(1, EXECUTION_REPLICATES_PER_CHECKPOINT + 1)
        ]
        for checkpoint in CHECKPOINTS
    }
    definition = {
        "schema_version": SCHEMA_VERSION,
        "protocol_revision": PROTOCOL_REVISION,
        "experiment_id": EXPERIMENT_ID,
        "status": "prepared_unexecuted",
        "model": MODEL,
        "api": API,
        "master_seed": MASTER_SEED,
        "participant_topology": {
            "participant_roles": 3,
            "model_agents": 2,
            "planner": {
                "role": "private_planning_state_and_checkpoint_execution",
                "model": "gemini-3.7-flash",
                "api": API,
            },
            "examiner": {
                "role": "three_external_semantic_examinations",
                "model": "gpt-5.6-sol",
                "reasoning_effort": "xhigh",
                "harness": "chatgpt",
            },
            "final_adjudicator": {
                "role": "human_researcher",
                "is_model_agent": False,
            },
        },
        "dossier": {
            "directory": base.DOSSIER_DIRECTORY,
            "document_count": len(documents),
            "documents": documents,
            "assembled_task_text": task_text,
            "assembled_task_sha256": base.sha256_text(task_text),
            "withheld_construction_notes": base.WITHHELD_CONSTRUCTION_NOTES,
            "withheld_notes_sent_to_model": False,
            "preferred_solution_exists": False,
        },
        "trajectory": {
            "checkpoints": list(CHECKPOINTS),
            "observations": list(OBSERVATIONS),
            "examinations": list(EXAMINATIONS),
            "interventions": list(INTERVENTIONS),
            "ordered_chain": [
                "C0", "O0", "X1", "I1",
                "C1", "O1", "X2", "I2",
                "C2", "O2", "X3", "I3",
                "C3", "O3",
            ],
            "exactly_three_examinations": True,
            "X4_exists": False,
            "O3_is_followed_by_human_assessment_not_X4": True,
            "observation_is_never_replayed_into_live_planning": True,
            "intervention_is_appended_to_exact_parent_live_history": True,
        },
        "planning": {
            "system_instruction": PLANNING_SYSTEM_INSTRUCTION,
            "continuation_prompt": CONTINUE_PLANNING_PROMPT,
            "visible_channel": "raw_text_no_schema_no_json_envelope",
            "eligible_self_judgments": [READY, NOT_READY],
            "maximum_turns_per_checkpoint": MAX_PLANNING_TURNS_PER_CHECKPOINT,
            "generation_configs": planning_configs,
            "provider_finish_reason_precedes_visible_parse": True,
            "completed_ready_requires_exactly_one_visible_text_part": True,
            "continuation_classifications": [
                SELF_DECLARED_NOT_READY,
                UNOBSERVED_TRUNCATED,
                INVALID_STATUS,
            ],
            "threshold_terminal": PLANNING_THRESHOLD_REACHED,
            "max_tokens_is_unobserved_truncation": True,
            "max_tokens_signed_content_is_replayed_exactly": True,
            "missing_or_non_budget_finish_reason_is_technical": True,
            "live_candidate_content_is_replayed_without_mutation": True,
        },
        "isolation": {
            "operator_status": "protocol_defined_core_operator",
            "operator_name": "detached_blank_text_signed_part_isolation",
            "source": "sole target checkpoint candidate.content only",
            "source_is_deep_copied": True,
            "visible_part_text_is_replaced_with_empty_text": True,
            "part_order_and_thought_signatures_are_preserved_exactly": True,
            "unexpected_readable_fields_are_rejected": True,
            "neutral_stub": NEUTRAL_CARRIER_STUB,
            "task_system_and_ordinary_history_included": False,
            "query": PRIMARY_INSPECTION_PROMPT,
            "every_replayable_planning_checkpoint_is_inspected": True,
            "primary_stage_observations_are_ready_checkpoint_readouts": True,
            "matched_seed_across_checkpoints": True,
            "generation_config": generation_config(
                kind="inspection", seed_label=PRIMARY_INSPECTION_SEED_LABEL
            ),
            "provider_error_or_invalid_readout_is_ineligible": True,
            "eligible_observation_required_before_next_human_seal": True,
        },
        "examinations": {
            "ids": list(EXAMINATIONS),
            "exact_external_examiner_turns": 3,
            "charters": copy.deepcopy(EXAMINATION_CHARTERS),
            "fixed_charter_order": [
                "epistemic_hinge_audit_v1",
                "adversarial_alternative_falsification_audit_v1",
                "global_reintegration_joint_feasibility_audit_v1",
            ],
            "adaptive_target_selection_within_each_charter": True,
            "each_turn_occurs_after_its_source_observation_is_eligible": True,
            "examiner_inputs_and_outputs_are_runtime_hash_bound": True,
            "examiner_output_is_never_replayed_to_planner": True,
            "no_fourth_examination": True,
        },
        "private_measurement_material": {
            "fault_atlas": list(copy.deepcopy(PRIVATE_FAULT_ATLAS)),
            "semantic_human_rubric": list(copy.deepcopy(SEMANTIC_HUMAN_RUBRIC)),
            "diagnostic_states": list(DIAGNOSTIC_STATES),
            "diagnostic_state_definitions": copy.deepcopy(
                DIAGNOSTIC_STATE_DEFINITIONS
            ),
            "hard_contradiction_gate": HARD_CONTRADICTION_GATE,
            "generic_and_contains_no_dossier_specific_answer": True,
            "invisible_to_gemini_planner": True,
            "not_in_planning_intervention_or_execution_requests": True,
        },
        "observation_assessments": {
            "observations_scored": list(OBSERVATIONS),
            "same_six_dimension_rubric_for_every_observation": True,
            "rubric_dimensions": list(RUBRIC_DIMENSIONS),
            "score_range": [0, 2],
            "assessor": "human_researcher",
            "scores_are_descriptive_not_a_stop_rule": True,
            "target_diagnostic_states": {
                observation: list(targets)
                for observation, targets in OBSERVATION_ASSESSMENT_TARGETS.items()
            },
            "available_later_observations_reassess_prior_targets": True,
            "O0_O1_O2_assessments_are_bound_in": {
                "O0": "I1 human seal",
                "O1": "I2 human seal",
                "O2": "I3 human seal",
            },
            "final_O3_assessment": {
                "schema_version": FINAL_O3_ASSESSMENT_SCHEMA_VERSION,
                "assessment_id": FINAL_O3_ASSESSMENT_ID,
                "record_keys": sorted(RUNTIME_FINAL_O3_ASSESSMENT_KEYS),
                "required_target_states": list(
                    OBSERVATION_ASSESSMENT_TARGETS["O3"]
                ),
                "human_only_non_examiner": True,
                "creates_no_X4_or_I4": True,
                "must_be_sealed_before_execution_gate_opens": True,
            },
            "hard_contradiction_precludes_resolved_target_or_full_repair_scores": True,
        },
        "interventions": {
            "specs": copy.deepcopy(INTERVENTION_SPECS),
            "selection_rules": copy.deepcopy(INTERVENTION_SELECTION_RULES),
            "actual_diagnosis_target_prediction_and_text_are_authored_after_observation": True,
            "I1_may_be_sealed_only_after": "eligible O0",
            "I2_may_be_sealed_only_after": "eligible O1",
            "I3_may_be_sealed_only_after": "eligible O2",
            "human_authored_record_keys": sorted(HUMAN_AUTHORED_INTERVENTION_KEYS),
            "runtime_seal_keys": sorted(RUNTIME_INTERVENTION_SEAL_KEYS),
            "sealed_record_keys": sorted(SEALED_INTERVENTION_RECORD_KEYS),
            "review_stream_keys": sorted(REVIEW_STREAM_KEYS),
            "reviewer_provenance_requirements": copy.deepcopy(
                REVIEWER_PROVENANCE_REQUIREMENTS
            ),
            "reviewer_provenance_keys": sorted(REVIEWER_PROVENANCE_KEYS),
            "reconciliation_keys": sorted(RECONCILIATION_KEYS),
            "human_researcher_is_final_adjudicator": True,
            "runtime_supplies_and_validates_source_observation_hash": True,
            "runtime_supplies_and_validates_examiner_input_output_hashes": True,
            "runtime_supplies_and_validates_sealed_at_UTC": True,
            "seal_chronology_must_be_verified_by_runtime_archive": True,
            "stable_semantic_commitments": list(STABLE_SEMANTIC_COMMITMENTS),
            "model_facing_intervention_contains_only_reconciled_intervention_text": True,
            "replacement_answer_must_not_be_planted": True,
        },
        "state_machine": {
            "initial_status": PREPARED_UNEXECUTED,
            "transitions": list(TRANSITION_ROWS),
            "terminal_statuses": list(TERMINAL_STATUSES),
            "human_seal_gates_cannot_be_bypassed": True,
            "execution_gate_requires_eligible_O3_and_final_human_assessment": True,
            "no_X4_or_I4_transition": True,
            "model_judgment_is_distinct_from_experimental_termination": True,
        },
        "execution": {
            "prompt": EXECUTION_PROMPT,
            "checkpoints": list(CHECKPOINTS),
            "replicates_per_checkpoint": EXECUTION_REPLICATES_PER_CHECKPOINT,
            "generation_configs": execution_configs,
            "schedule_seed": derived_seed(EXECUTION_SCHEDULE_SEED_LABEL),
            "schedule": build_execution_schedule(),
            "same_seed_within_matched_checkpoint_quartet": True,
            "interleaved_checkpoint_order": True,
            "begins_only_after_O3_is_eligible_and_final_assessment_is_sealed": True,
            "only_completed_ready_checkpoints_are_eligible": True,
            "truncated_checkpoint_is_never_an_execution_baseline": True,
            "natural_language_no_json": True,
        },
        "adjudication": {
            "labels": list(ADJUDICATION_LABELS),
            "mode": "semantic_relational_human_review",
            "review_streams": {
                "reviewer_A": {
                    "provenance_requirements": copy.deepcopy(
                        REVIEWER_PROVENANCE_REQUIREMENTS["reviewer_A"]
                    ),
                    "independently_recorded": True,
                },
                "reviewer_B": {
                    "provenance_requirements": copy.deepcopy(
                        REVIEWER_PROVENANCE_REQUIREMENTS["reviewer_B"]
                    ),
                    "independently_recorded": True,
                },
            },
            "reconciliation_is_human_approved": True,
            "human_researcher_is_final_adjudicator": True,
            "no_keyword_counting": True,
            "no_exact_output_matching": True,
            "no_aggregate_pseudo_precision": True,
            "stable_commitment_preservation_is_semantic_not_verbatim": True,
            "rubric": list(copy.deepcopy(SEMANTIC_HUMAN_RUBRIC)),
            "rubric_dimensions": 6,
            "rubric_anchor_range": [0, 2],
            "rubric_scores_are_descriptive_not_a_sole_stop_rule": True,
            "every_O_i_is_scored_on_the_same_six_dimensions": True,
            "final_O3_scores_are_human_sealed_before_execution": True,
            "diagnostic_state_is_recorded_per_target_across_available_later_observations": True,
            "matched_executions_are_separate_behavioral_evidence": True,
            "diagnostic_states": list(DIAGNOSTIC_STATES),
            "hard_contradictions_gate_repair": True,
            "hard_contradiction_gate": HARD_CONTRADICTION_GATE,
            "review_questions": [
                "Is the targeted relationship substantively represented rather than merely named?",
                "Was it revised, bounded, or justifiably preserved?",
                "Were material downstream consequences propagated?",
                "Were unrelated stable commitments preserved?",
                "Do matched executions instantiate the checkpoint difference behaviorally?",
            ],
            "full_support_pattern": [
                "all three intervention links show their sealed semantic prediction or justified preservation",
                (
                    "later observations do not regress a previously repaired "
                    "relationship unless the next intervention predicted and "
                    "justified its reversal"
                ),
                "stable commitments remain unless an explicit dependency justifies change",
                "at least two of three matched execution quartets reflect all three ordered state changes",
                "no targeted hard contradiction remains in a claim of full repair",
            ],
            "non_support_pattern": [
                "intervention vocabulary is echoed but the relationship is unchanged",
                "a targeted contradiction remains or is replaced by unsupported favorable assumptions",
                "observed state differences do not produce corresponding execution differences",
            ],
            "technical_indeterminacy_is_not_capability_failure": True,
            "does_not_establish": [
                "verbatim hidden chain of thought",
                "inspection output identical to reasoning state",
                "population reliability from one dossier",
            ],
        },
        "planned_calls": {
            "planning_maximum": 4 * MAX_PLANNING_TURNS_PER_CHECKPOINT,
            "inspection_minimum_on_complete_path": 4,
            "inspection_maximum": 4 * MAX_PLANNING_TURNS_PER_CHECKPOINT,
            "execution_count_on_complete_path": (
                len(CHECKPOINTS) * EXECUTION_REPLICATES_PER_CHECKPOINT
            ),
            "completed_evidence_path_minimum": 20,
            "whole_experiment_maximum": 60,
            "transport_retry_physical_maximum_multiplier": (
                base.MAX_ATTEMPTS_PER_LOGICAL_REQUEST
            ),
            "whole_experiment_physical_maximum": 180,
            "external_examiner_turns_exact": 3,
            "external_examiner_turns_excluded_from_gemini_call_bounds": True,
            "human_review_and_sealing_calls": 0,
        },
    }
    base.assert_no_function_tool_or_schema_structure(definition)
    return definition


def validate_experiment_definition(
    definition: dict[str, Any], repo_root: Path
) -> list[str]:
    errors: list[str] = []
    if not isinstance(definition, dict):
        return ["experiment definition is not an object"]
    if definition != build_experiment_definition(repo_root):
        errors.append("experiment definition differs from deterministic protocol")
    try:
        base.assert_no_function_tool_or_schema_structure(definition)
    except ValueError as exc:
        errors.append(str(exc))
    return errors
