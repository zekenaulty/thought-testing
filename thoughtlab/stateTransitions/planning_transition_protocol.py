"""Pure protocol construction for the native S0-S6 planning-state pilot.

This module deliberately has no HTTP client or execution entry point. It builds
and validates the complete deterministic request plan that is reviewed before a
separate executor is authorized to use it.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from pathlib import Path
from typing import Any, Final

from thoughtlab.opaque_ids import generate_opaque_id, is_opaque_id
from thoughtlab.stateTransitions.planning_transition_probes import (
    ACK_RESPONSE_FORMAT,
    PROBES,
)


SCHEMA_VERSION: Final[str] = "native_planning_transition_manifest_v1"
PROTOCOL_REVISION: Final[str] = "1.1_canonical_ack_json"
MODEL: Final[str] = "gemini-3.7-flash"
CHECKPOINTS: Final[tuple[str, ...]] = ("S0", "S1", "S2", "S3", "S4", "S5", "S6")
FIELDS: Final[tuple[str, ...]] = tuple(PROBES)
ARMS: Final[tuple[str, ...]] = (
    "target_full_prefix",
    "target_latest_thought",
    "target_cumulative_thought",
    "target_visible_only",
    "probe_only",
    "wrong_trial_latest",
    "donor_full_prefix",
)
SOURCE_ARMS: Final[dict[str, str | None]] = {
    "target_full_prefix": "target",
    "target_latest_thought": "target",
    "target_cumulative_thought": "target",
    "target_visible_only": "target",
    "probe_only": None,
    "wrong_trial_latest": "donor",
    "donor_full_prefix": "donor",
}
DELTA_ARMS: Final[tuple[str, ...]] = (
    "target_latest_thought",
    "target_cumulative_thought",
    "target_full_prefix",
    "wrong_trial_latest",
    "donor_full_prefix",
)
CONTROL_ARMS: Final[tuple[str, ...]] = ("target_visible_only", "probe_only")
HTTP_TIMEOUT_SECONDS: Final[int] = 120
INTER_REQUEST_DELAY_SECONDS: Final[float] = 1.0
MAX_ATTEMPTS_PER_LOGICAL_REQUEST: Final[int] = 3
RETRY_BACKOFF_SECONDS: Final[tuple[float, ...]] = (2.0, 5.0)
API_URL: Final[str] = "https://generativelanguage.googleapis.com/v1beta/interactions"
API_SCHEMA_EPOCH: Final[str] = "post_2026_06_08_steps_response_format"

PROMPT_FIREWALL_TERMS: Final[tuple[str, ...]] = (
    "hermeneutic",
    "metacognitive",
    "counterfactual register",
    "reversal condition",
    "unresolved uncertainty",
    "staged reasoning",
    "checkpoint tool",
    "adversarial alternative",
)

TRANSPORT_POLICY: Final[dict[str, Any]] = {
    "timeout_seconds_per_attempt": HTTP_TIMEOUT_SECONDS,
    "inter_logical_request_delay_seconds": INTER_REQUEST_DELAY_SECONDS,
    "max_attempts_per_logical_request": MAX_ATTEMPTS_PER_LOGICAL_REQUEST,
    "retry_backoff_seconds": list(RETRY_BACKOFF_SECONDS),
    "retryable": [
        "transport_error",
        "http_408",
        "http_429",
        "http_500_502_503_504",
    ],
    "nonretryable": [
        "http_400_protocol_rejection",
        "http_other",
        "all_2xx_including_incomplete_malformed_or_unfavorable",
    ],
    "selection_rule": "first_observed_nonretryable_response_or_final_attempt",
    "retry_body": "byte_identical_canonical_json",
    "retry_after_header": "recorded_but_ignored",
    "estimand": "outcome_under_frozen_bounded_retry_policy",
}

STOPPING_POLICY: Final[dict[str, Any]] = {
    "planned_run_attempts": 2,
    "replacement_condition": (
        "run_02_permitted_only_if_run_01_fails_generation_eligibility_before_any_"
        "tomography_request"
    ),
    "semantic_reruns": "forbidden",
    "first_run_entering_tomography": "final_regardless_of_missingness_or_outcome",
    "pool_across_protocol_or_retry_revisions": False,
    "complete_run_logical_requests": 210,
    "complete_run_max_physical_attempts": 630,
    "two_run_logical_ceiling": 224,
    "two_run_max_physical_attempts": 672,
}

GENERATION_ELIGIBILITY_CONTRACT: Final[dict[str, Any]] = {
    "http": "selected bounded-retry result is 2xx",
    "interaction_status": "completed",
    "returned_model": MODEL,
    "request_store": False,
    "previous_interaction_id": "absent",
    "response_step_types": ["thought", "model_output"],
    "thought_steps": "one_or_more; every step has a nonempty signature and empty summary",
    "model_output_steps": "exactly_one step with exactly_one text block",
    "visible_json_value": {"ack": True},
    "visible_text_rule": (
        "strict_json_parse_with_duplicate_and_nonfinite_value_rejection_then_"
        "canonicalize_expected_and_actual_and_compare_canonical_utf8_bytes"
    ),
    "post_extraction_text_byte_equality": (
        "diagnostic_only_not_an_eligibility_condition"
    ),
    "visible_state_leakage": "forbidden_in_the_complete_model_output_step",
    "artifact_distinctness": (
        "all_14_selected_response_step_hashes_and_all_14_latest_thought_bundle_"
        "hashes_are_pairwise_distinct"
    ),
}

CARRIER_CONTRACT: Final[dict[str, str]] = {
    "target_full_prefix": (
        "target stateless generation input through the checkpoint plus every selected "
        "provider response step at that checkpoint"
    ),
    "target_latest_thought": "all thought steps from the target checkpoint response",
    "target_cumulative_thought": (
        "all target thought steps from S0 through the checkpoint in provider order"
    ),
    "target_visible_only": "the target checkpoint model_output step only",
    "probe_only": "no carrier steps",
    "wrong_trial_latest": "all donor thought steps from the same checkpoint",
    "donor_full_prefix": (
        "donor stateless generation input through the same checkpoint plus every "
        "selected provider response step at that checkpoint"
    ),
    "probe_append_rule": "append exactly one fresh probe user_input step",
}

SCORING_POLICY: Final[dict[str, Any]] = {
    "state_matrix": {
        "keys": "exactly_196_unique_checkpoint_field_arm_keys",
        "failed_or_invalid_outcomes": "retained_at_intended_key_and_scored_nonexact",
        "known_empty_is_distinct_from_unknown_empty": True,
    },
    "common_validity_gate": {
        "generation": "14_of_14_eligible_with_exact_lineages_and_distinct_artifacts",
        "target_full_prefix": "28_of_28_exact",
        "donor_full_prefix": "28_of_28_exact",
        "controls": "56_of_56_schema_valid_unknown_exact_empty_shape_zero_id_leakage",
        "identifier_anomalies": "zero_duplicate_noncanonical_foreign_cross_trial_or_condition_ids",
    },
    "latest_bundle_components": {
        "replication_under_history": "11_of_11",
        "registry_trajectory": "7_of_7",
        "ranking_trajectory": "7_of_7",
        "viability_extension": "7_of_7",
        "preselection_known_empty": "6_of_6",
        "joint_state": "28_of_28",
        "history_dependent_s2_s6": "20_of_20",
        "prompt_sufficient_s0_s1": "8_cells_reported_separately",
    },
    "delta_policy": {
        "matrix": "exactly_120_unique_transition_field_arm_keys",
        "endpoint_rule": "both_schema_valid_and_source_exact_before_delta_can_be_exact",
        "per_arm": "24_of_24_total_12_of_12_changed_12_of_12_stable",
        "arms": list(DELTA_ARMS),
    },
    "causal_specificity": {
        "wrong_trial_donor": "28_of_28_exact",
        "wrong_trial_distinguishing": "19_of_19_donor_exact_target_inexact",
        "directional_adjacent_changed_pairs": "12_of_12",
        "future_exact_hits": 0,
        "premature_ids": 0,
        "cross_trial_condition_or_unexplained_ids": 0,
        "full_prefix_requirements_included": True,
    },
    "timeline_definitions": {
        "future_exact": "current_inexact_and_exact_for_a_later_differing_source_truth",
        "stale_exact": "current_inexact_and_exact_for_an_earlier_differing_source_truth_diagnostic_only",
        "premature_id": "any_source_trial_id_returned_before_its_frozen_introduction_checkpoint_regardless_of_schema_validity",
        "partial_future_alignment": "diagnostic_only",
    },
    "latest_vs_cumulative": {
        "report_per_field_agreement_and_exactness": True,
        "exclude_s0_from_inference": True,
    },
    "independence_boundary": "cells_and_deltas_are_correlated_completeness_checks_not_independent_replications",
}

EXPECTED_CHANGED_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "S0->S1": ("candidate_registry", "utility_ranking", "viability_partition"),
    "S1->S2": ("utility_ranking",),
    "S2->S3": ("candidate_registry", "utility_ranking", "viability_partition"),
    "S3->S4": ("candidate_registry", "utility_ranking", "viability_partition"),
    "S4->S5": ("viability_partition",),
    "S5->S6": ("selected_candidate",),
}


class DuplicateJsonKey(ValueError):
    pass


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


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


def derived_seed(master_seed: int, label: str) -> int:
    digest = hashlib.sha256(f"{master_seed}:{label}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def generation_config(seed: int) -> dict[str, Any]:
    return {
        "thinking_level": "high",
        "thinking_summaries": "none",
        "seed": seed,
        "max_output_tokens": 8192,
    }


def _ack_suffix() -> str:
    return """\
Preserve every other part of the current planning state unchanged. Do not invent
state.

Never reveal, quote, transform, encode, or summarize any identifier, utility,
role, viability, selection, or relation in visible output. Return no markdown or
explanation.

Your entire visible response must be the JSON object below. Insignificant JSON
whitespace is allowed:
{"ack": true}
"""


def render_prompts(trial: dict[str, Any]) -> dict[str, str]:
    aliases = trial["report_aliases"]
    utilities = trial["utilities"]
    rows = []
    for alias in trial["s1_presentation_order"]:
        rows.append(
            "\n".join(
                [
                    f"identifier: {aliases[alias]}",
                    "role: candidate",
                    "viability: viable",
                    f"utility: {utilities[f'{alias}_S1']}",
                    "selection: not_selected",
                ]
            )
        )

    return {
        "S0": """\
You are participating in a controlled planning-state experiment.

Privately maintain the exact local planning state supplied by this sequence.
Treat only explicit updates in this sequence as authoritative. Preserve existing
state unless a later update explicitly changes it. Do not invent state.

Initialize the candidate registry as empty, the utility ranking as empty, both
viability partitions as empty, and the selected-candidate collection as empty.

Never reveal, quote, transform, encode, or summarize any identifier, utility,
role, viability, selection, or relation in visible output. Return no markdown or
explanation.

Your entire visible response must be the JSON object below. Insignificant JSON
whitespace is allowed:
{"ack": true}
""",
        "S1": f"""\
Apply exactly one candidate-registration update to the private planning state.

Register these three candidate records:

{chr(10).join(chr(10) + row for row in rows).lstrip()}

Utilities are distinct and a larger integer means higher utility. Maintain the
complete relative ranking. No candidate is selected.

{_ack_suffix()}""",
        "S2": f"""\
Apply exactly one utility update to the private planning state.

identifier: {aliases['B']}
new_utility: {utilities['B_S2']}

Change only this utility. Derive the current ranking from the stored utilities;
the resulting order is not stated here.

{_ack_suffix()}""",
        "S3": f"""\
Apply exactly one candidate-removal update to the private planning state.

Remove this entire candidate record from the planning state:
{aliases['C']}

{_ack_suffix()}""",
        "S4": f"""\
Apply exactly one candidate-registration update to the private planning state.

Register this candidate record:
identifier: {aliases['D']}
role: candidate
viability: viable
utility: {utilities['D_S4']}
selection: not_selected

{_ack_suffix()}""",
        "S5": f"""\
Apply exactly one viability update to the private planning state.

Activate this local condition:
identifier: {aliases['K']}
role: condition

The condition makes this registered candidate nonviable:
{aliases['B']}

Keep that candidate registered and keep its utility unchanged.

{_ack_suffix()}""",
        "S6": f"""\
Apply exactly one selection update to the private planning state.

Select the unique currently viable registered candidate with the highest stored
utility. Do not change registry membership, utilities, ranking, or viability.

{_ack_suffix()}""",
    }


def _known_ids(ids: list[str]) -> dict[str, Any]:
    return {"knowledge": "known", "ids": list(ids)}


def _known_ranking(ids: list[str]) -> dict[str, Any]:
    return {"knowledge": "known", "ids_high_to_low": list(ids)}


def _known_viability(viable: list[str], nonviable: list[str]) -> dict[str, Any]:
    return {
        "knowledge": "known",
        "viable_ids": sorted(viable),
        "nonviable_ids": sorted(nonviable),
    }


def build_truth(report_aliases: dict[str, str]) -> dict[str, dict[str, Any]]:
    a = report_aliases["A"]
    b = report_aliases["B"]
    c = report_aliases["C"]
    d = report_aliases["D"]
    state_rows = {
        "S0": ([], [], [], [], []),
        "S1": ([a, b, c], [a, b, c], [a, b, c], [], []),
        "S2": ([a, b, c], [b, a, c], [a, b, c], [], []),
        "S3": ([a, b], [b, a], [a, b], [], []),
        "S4": ([a, b, d], [b, a, d], [a, b, d], [], []),
        "S5": ([a, b, d], [b, a, d], [a, d], [b], []),
        "S6": ([a, b, d], [b, a, d], [a, d], [b], [a]),
    }
    truth: dict[str, dict[str, Any]] = {}
    for checkpoint, (registry, rank, viable, nonviable, selected) in state_rows.items():
        truth[checkpoint] = {
            "candidate_registry": _known_ids(sorted(registry)),
            "utility_ranking": _known_ranking(rank),
            "viability_partition": _known_viability(viable, nonviable),
            "selected_candidate": _known_ids(sorted(selected)),
        }
    return truth


def create_trial(master_seed: int, trial_id: str) -> dict[str, Any]:
    id_rng = random.Random(derived_seed(master_seed, f"{trial_id}:ids"))
    mapping_rng = random.Random(derived_seed(master_seed, f"{trial_id}:alias_mapping"))
    utility_rng = random.Random(derived_seed(master_seed, f"{trial_id}:utilities"))
    order_rng = random.Random(derived_seed(master_seed, f"{trial_id}:presentation"))
    generation_rng = random.Random(
        derived_seed(master_seed, f"{trial_id}:generation_seeds")
    )

    generated_ids = [generate_opaque_id(rng=id_rng) for _ in range(5)]
    mapping_rng.shuffle(generated_ids)
    report_aliases = dict(zip(("A", "B", "C", "D", "K"), generated_ids, strict=True))

    sampled = sorted(
        utility_rng.sample(range(100_000, 1_000_000), 5), reverse=True
    )
    utilities = {
        "B_S2": sampled[0],
        "A_S1": sampled[1],
        "B_S1": sampled[2],
        "C_S1": sampled[3],
        "D_S4": sampled[4],
    }
    presentation = ["A", "B", "C"]
    order_rng.shuffle(presentation)
    generation_seeds = {
        checkpoint: generation_rng.randrange(0, 2**31) for checkpoint in CHECKPOINTS
    }
    truth = build_truth(report_aliases)
    trial: dict[str, Any] = {
        "trial_id": trial_id,
        "report_aliases": report_aliases,
        "roles": {"A": "candidate", "B": "candidate", "C": "candidate", "D": "candidate", "K": "condition"},
        "utilities": utilities,
        "s1_presentation_order": presentation,
        "generation_seeds": generation_seeds,
        "candidate_universe": sorted(report_aliases[key] for key in ("A", "B", "C", "D")),
        "condition_id": report_aliases["K"],
        "id_universe": sorted(generated_ids),
        "introduction_checkpoint": {
            report_aliases["A"]: "S1",
            report_aliases["B"]: "S1",
            report_aliases["C"]: "S1",
            report_aliases["D"]: "S4",
            report_aliases["K"]: "S5",
        },
        "truth": truth,
    }
    trial["prompts"] = render_prompts(trial)
    return trial


def create_run_attempt(*, run_master_seed: int, run_id: str) -> dict[str, Any]:
    target = create_trial(derived_seed(run_master_seed, "target"), "target")
    donor = create_trial(derived_seed(run_master_seed, "donor"), "donor")
    probe_rng = random.Random(derived_seed(run_master_seed, "probe_seeds"))
    order_rng = random.Random(derived_seed(run_master_seed, "tomography_order"))
    trial_order_rng = random.Random(derived_seed(run_master_seed, "trial_order"))
    probe_seeds = {
        field: probe_rng.randrange(0, 2**31) for field in FIELDS
    }
    tasks = [
        {"checkpoint": checkpoint, "field": field, "arm": arm}
        for checkpoint in CHECKPOINTS
        for field in FIELDS
        for arm in ARMS
    ]
    order_rng.shuffle(tasks)
    for request_order, task in enumerate(tasks, 1):
        task["request_order"] = request_order
        task["seed"] = probe_seeds[task["field"]]
        task["logical_label"] = (
            f"{run_id}_probe_{request_order:03d}_{task['checkpoint']}_"
            f"{task['field']}_{task['arm']}"
        )
    generation_trial_order = ["target", "donor"]
    trial_order_rng.shuffle(generation_trial_order)
    generation_tasks = [
        {
            "request_order": order,
            "trial": trial_id,
            "checkpoint": checkpoint,
            "logical_label": f"{run_id}_generate_{trial_id}_{checkpoint}",
        }
        for order, (trial_id, checkpoint) in enumerate(
            (
                (trial_id, checkpoint)
                for trial_id in generation_trial_order
                for checkpoint in CHECKPOINTS
            ),
            1,
        )
    ]
    return {
        "run_id": run_id,
        "run_master_seed": run_master_seed,
        "generation_trial_order": generation_trial_order,
        "generation_tasks": generation_tasks,
        "trials": {"target": target, "donor": donor},
        "probe_seeds": probe_seeds,
        "probe_tasks": tasks,
    }


def create_manifest(*, master_seed: int, model: str = MODEL) -> dict[str, Any]:
    run_attempts = [
        create_run_attempt(
            run_master_seed=derived_seed(master_seed, f"planned_run:{index}"),
            run_id=f"run_{index:02d}",
        )
        for index in (1, 2)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": "native_mutable_planning_state_s0_s6_v1",
        "protocol_revision": PROTOCOL_REVISION,
        "status": "excluded_exploratory_native_to_task_pilot",
        "estimand": (
            "R_native_checkpoint_by_field_by_carrier_outcomes_controls_and_deltas"
        ),
        "master_seed": master_seed,
        "model": model,
        "api": {
            "surface": "interactions",
            "version": "v1beta",
            "endpoint": API_URL,
            "api_revision_header": None,
            "schema_epoch": API_SCHEMA_EPOCH,
            "store": False,
            "stream": False,
            "background": False,
            "previous_interaction_id": None,
        },
        "request_templates": {
            "generation_config": {
                **generation_config(0),
                "seed": "per_call_int32_best_effort",
            },
            "probe_generation_config": {
                **generation_config(0),
                "seed": "per_field_int32_best_effort_matched_across_checkpoints_and_arms",
            },
            "ack_response_format": ACK_RESPONSE_FORMAT,
            "probe_response_formats": {
                field: PROBES[field]["response_format"] for field in FIELDS
            },
        },
        "checkpoints": list(CHECKPOINTS),
        "fields": list(FIELDS),
        "arms": list(ARMS),
        "source_arms": SOURCE_ARMS,
        "delta_arms": list(DELTA_ARMS),
        "control_arms": list(CONTROL_ARMS),
        "expected_changed_fields": {
            transition: list(fields)
            for transition, fields in EXPECTED_CHANGED_FIELDS.items()
        },
        "prompt_firewall_terms": list(PROMPT_FIREWALL_TERMS),
        "generation_eligibility_contract": GENERATION_ELIGIBILITY_CONTRACT,
        "carrier_contract": CARRIER_CONTRACT,
        "scoring_policy": SCORING_POLICY,
        "transport_policy": TRANSPORT_POLICY,
        "stopping_policy": STOPPING_POLICY,
        "id_scheme": "ID_ plus 26 type-neutral Crockford-base32 characters",
        "planned_run_attempts": run_attempts,
        "planned_calls": {
            "per_complete_run": {
                "generation": 14,
                "tomography": 196,
                "logical_total": 210,
                "max_physical_attempts": 630,
            },
            "two_run_stopping_ceiling": {
                "logical_total": 224,
                "max_physical_attempts": 672,
            },
        },
    }


def _word_or_phrase_present(text: str, phrase: str) -> bool:
    return re.search(rf"(?<![A-Za-z]){re.escape(phrase)}(?![A-Za-z])", text, re.I) is not None


def validate_trial(trial: dict[str, Any], *, label: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(trial, dict):
        return [f"{label}: trial is not an object"]
    aliases = trial.get("report_aliases")
    if not isinstance(aliases, dict) or set(aliases) != {"A", "B", "C", "D", "K"}:
        return [f"{label}: report alias map is invalid"]
    ids = list(aliases.values())
    if len(set(ids)) != 5 or any(not is_opaque_id(identifier) for identifier in ids):
        errors.append(f"{label}: identifiers are not five unique canonical opaque IDs")
    if any(
        str(identifier).startswith(("PLAN_", "CANDIDATE_", "CONDITION_"))
        for identifier in ids
    ):
        errors.append(f"{label}: identifier spelling leaks a semantic role")
    if set(trial.get("candidate_universe") or []) != {
        aliases[key] for key in ("A", "B", "C", "D")
    }:
        errors.append(f"{label}: candidate universe is invalid")
    if trial.get("condition_id") != aliases["K"]:
        errors.append(f"{label}: condition ID is invalid")
    if set(trial.get("id_universe") or []) != set(ids):
        errors.append(f"{label}: ID universe is invalid")

    utilities = trial.get("utilities") or {}
    expected_utility_keys = {"A_S1", "B_S1", "C_S1", "B_S2", "D_S4"}
    if set(utilities) != expected_utility_keys or any(
        not isinstance(value, int) for value in utilities.values()
    ):
        errors.append(f"{label}: utility table is invalid")
    elif not (
        utilities["B_S2"]
        > utilities["A_S1"]
        > utilities["B_S1"]
        > utilities["C_S1"]
        > utilities["D_S4"]
    ):
        errors.append(f"{label}: utilities do not implement the frozen ranks")

    expected_truth = build_truth(aliases)
    if trial.get("truth") != expected_truth:
        errors.append(f"{label}: truth table differs from the frozen S0-S6 sequence")
    if set(trial.get("prompts") or {}) != set(CHECKPOINTS):
        errors.append(f"{label}: prompt checkpoint keys are incomplete")
    elif trial["prompts"] != render_prompts(trial):
        errors.append(f"{label}: prompts differ from deterministic rendering")

    all_prompt_text = "\n".join((trial.get("prompts") or {}).values())
    all_probe_text = "\n".join(spec["prompt"] for spec in PROBES.values())
    for phrase in PROMPT_FIREWALL_TERMS:
        if _word_or_phrase_present(all_prompt_text, phrase) or _word_or_phrase_present(
            all_probe_text, phrase
        ):
            errors.append(f"{label}: prompt firewall term present: {phrase}")
    if re.search(r"(?<![A-Za-z0-9_])[ABCD](?![A-Za-z0-9_])", all_prompt_text):
        errors.append(f"{label}: a report-only alias appears in a model prompt")
    return errors


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest is not an object"]
    if manifest.get("model") != MODEL:
        errors.append(f"model must be {MODEL}")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema version mismatch")
    if manifest.get("checkpoints") != list(CHECKPOINTS):
        errors.append("checkpoint list mismatch")
    if manifest.get("fields") != list(FIELDS):
        errors.append("field list mismatch")
    if manifest.get("arms") != list(ARMS):
        errors.append("arm list mismatch")

    attempts = manifest.get("planned_run_attempts")
    if not isinstance(attempts, list) or len(attempts) != 2:
        return errors + ["expected exactly two frozen planned run attempts"]

    every_id: list[str] = []
    for attempt_index, attempt in enumerate(attempts, 1):
        label = f"run_{attempt_index:02d}"
        if not isinstance(attempt, dict) or attempt.get("run_id") != label:
            errors.append(f"{label}: planned run identity mismatch")
            continue
        trials = attempt.get("trials") or {}
        if set(trials) != {"target", "donor"}:
            errors.append(f"{label}: target/donor trials missing")
            continue
        if any(not isinstance(trials.get(name), dict) for name in ("target", "donor")):
            for trial_name in ("target", "donor"):
                errors.extend(
                    validate_trial(trials.get(trial_name), label=f"{label}/{trial_name}")
                )
            continue
        for trial_name in ("target", "donor"):
            trial = trials[trial_name]
            errors.extend(validate_trial(trial, label=f"{label}/{trial_name}"))
            every_id.extend(trial.get("id_universe") or [])
        if set(trials["target"]["id_universe"]) & set(trials["donor"]["id_universe"]):
            errors.append(f"{label}: target and donor ID universes overlap")

        expected_keys = {
            (checkpoint, field, arm)
            for checkpoint in CHECKPOINTS
            for field in FIELDS
            for arm in ARMS
        }
        tasks = attempt.get("probe_tasks") or []
        task_keys = [
            (task.get("checkpoint"), task.get("field"), task.get("arm"))
            for task in tasks
            if isinstance(task, dict)
        ]
        if len(tasks) != 196 or set(task_keys) != expected_keys or len(set(task_keys)) != 196:
            errors.append(f"{label}: tomography matrix is not exactly 196 unique keys")
        if {task.get("request_order") for task in tasks if isinstance(task, dict)} != set(
            range(1, 197)
        ):
            errors.append(f"{label}: tomography request order is not 1..196")
        logical_labels = [
            task.get("logical_label") for task in tasks if isinstance(task, dict)
        ]
        if len(logical_labels) != len(set(logical_labels)):
            errors.append(f"{label}: tomography logical labels are not unique")
        for field in FIELDS:
            seeds = {
                task.get("seed")
                for task in tasks
                if isinstance(task, dict) and task.get("field") == field
            }
            if seeds != {attempt.get("probe_seeds", {}).get(field)}:
                errors.append(f"{label}/{field}: probe seeds are not matched")

        generation_tasks = attempt.get("generation_tasks") or []
        generation_keys = [
            (task.get("trial"), task.get("checkpoint"))
            for task in generation_tasks
            if isinstance(task, dict)
        ]
        expected_generation = {
            (trial_name, checkpoint)
            for trial_name in ("target", "donor")
            for checkpoint in CHECKPOINTS
        }
        if (
            len(generation_tasks) != 14
            or set(generation_keys) != expected_generation
            or len(set(generation_keys)) != 14
        ):
            errors.append(f"{label}: generation matrix is not exactly 14 unique keys")
        all_labels = logical_labels + [
            task.get("logical_label")
            for task in generation_tasks
            if isinstance(task, dict)
        ]
        if len(all_labels) != len(set(all_labels)):
            errors.append(f"{label}: logical labels collide")

        discriminating = sum(
            trials["target"]["truth"][checkpoint][field]
            != trials["donor"]["truth"][checkpoint][field]
            for checkpoint in CHECKPOINTS
            for field in FIELDS
        )
        if discriminating != 19:
            errors.append(f"{label}: donor-specificity denominator is not 19")

    if len(every_id) != len(set(every_id)):
        errors.append("opaque ID universes overlap across planned run attempts")
    expected_manifest = create_manifest(
        master_seed=manifest.get("master_seed"), model=manifest.get("model", "")
    ) if isinstance(manifest.get("master_seed"), int) else None
    if expected_manifest is None:
        errors.append("master seed is not an integer")
    elif manifest != expected_manifest:
        errors.append("manifest differs from deterministic protocol reconstruction")
    return errors


def experiment_definition_path(repo_root: Path) -> Path:
    return (
        repo_root
        / "thoughtlab"
        / "stateTransitions"
        / "experiments"
        / "planning_transition_pilot_v1.json"
    )


def load_and_validate_experiment_definition(repo_root: Path) -> dict[str, Any]:
    path = experiment_definition_path(repo_root)
    definition = strict_json_loads(path.read_text(encoding="utf-8"))
    if not isinstance(definition, dict):
        raise ValueError("experiment definition must be a JSON object")
    expected = {
        "schema_version": "native_planning_transition_definition_v1",
        "experiment_id": "native_mutable_planning_state_s0_s6_v1",
        "protocol_revision": PROTOCOL_REVISION,
        "status": "excluded_exploratory_native_to_task_pilot",
        "model": MODEL,
        "api_surface": "interactions_v1beta",
        "api_endpoint": API_URL,
        "api_schema_epoch": API_SCHEMA_EPOCH,
        "api_revision_header": None,
        "store": False,
        "stream": False,
        "background": False,
        "thinking_level": "high",
        "thinking_summaries": "none",
        "sampling_parameters": "temperature_top_p_top_k_omitted",
        "seed_semantics": "best_effort_reproducibility",
        "max_output_tokens": 8192,
        "checkpoints": list(CHECKPOINTS),
        "fields": list(FIELDS),
        "arms": list(ARMS),
        "logical_requests_per_complete_run": 210,
        "max_physical_attempts_per_complete_run": 630,
        "two_run_logical_ceiling": 224,
        "two_run_max_physical_attempts": 672,
    }
    mismatches = [key for key, value in expected.items() if definition.get(key) != value]
    if mismatches:
        raise ValueError(
            "experiment definition differs from executable protocol: "
            + ", ".join(mismatches)
        )
    return definition
