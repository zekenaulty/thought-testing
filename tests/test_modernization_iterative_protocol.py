import copy
import json
from pathlib import Path

import pytest

from thoughtlab.reasoningEngineering import (
    modernization_iterative_protocol as protocol,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_definition_is_normalized_json_round_trip_stable() -> None:
    definition = protocol.build_experiment_definition(REPO_ROOT)

    assert json.loads(json.dumps(definition, ensure_ascii=True)) == definition


EXAMINER_INPUT_HASH = "b" * 64
EXAMINER_OUTPUT_HASH = "c" * 64


def model_content(text: str = "READY", signature: str = "secret") -> dict:
    return {
        "role": "model",
        "parts": [{"text": text, "thoughtSignature": signature}],
    }


def review_stream(reviewer: str, intervention_id: str) -> dict:
    spec = protocol.INTERVENTION_SPECS[intervention_id]
    provenance = copy.deepcopy(
        protocol.REVIEWER_PROVENANCE_REQUIREMENTS[reviewer]
    )
    provenance["input_sha256"] = (
        "a" * 64 if reviewer == "reviewer_A" else EXAMINER_INPUT_HASH
    )
    return {
        "provenance": provenance,
        "diagnosis": f"{reviewer} finds a material local relationship to test.",
        "observation_evidence": [
            f"Evidence in {spec['source_observation']} supports the local diagnosis."
        ],
        "targeted_reasoning_relationship": "A locally observed dependency and its consequences.",
        "predicted_observation_changes": "The relationship should be bounded or justifiably preserved.",
        "predicted_execution_changes": "Matched executions should reflect any decision change.",
        "proposed_intervention_text": (
            "Re-examine the evidenced dependency, propagate justified consequences, "
            "and preserve unrelated conclusions."
        ),
    }


def observation_assessment(observation_id: str) -> dict:
    return {
        "observation_id": observation_id,
        "assessed_by": "human_researcher",
        "assessment_basis": (
            f"Semantic review of eligible {observation_id} against the common rubric."
        ),
        "rubric_scores": {
            dimension: 1 for dimension in protocol.RUBRIC_DIMENSIONS
        },
        "target_diagnostic_states": {
            intervention_id: {
                "state": "BOUNDED",
                "evidence": (
                    f"{observation_id} bounds the target selected for "
                    f"{intervention_id}."
                ),
                "hard_contradiction_present": False,
            }
            for intervention_id in protocol.OBSERVATION_ASSESSMENT_TARGETS[
                observation_id
            ]
        },
    }


def human_draft(intervention_id: str) -> dict:
    spec = protocol.INTERVENTION_SPECS[intervention_id]
    if intervention_id == "I1":
        disposition = {
            key: protocol.NO_PRIOR_INTERVENTION
            for key in protocol.PRIOR_DELTA_DISPOSITION_KEYS
        }
    else:
        disposition = {
            "persist": "Keep the justified local improvement observed from O0 to O1.",
            "reverse": "Reverse no prior change unless O1 evidence undermines it.",
            "remain_unaffected": "Keep unrelated commitments outside the current target stable.",
        }
    return {
        "reviewer_A": review_stream("reviewer_A", intervention_id),
        "reviewer_B": review_stream("reviewer_B", intervention_id),
        "reconciliation": {
            "approved_by": "human_researcher",
            "basis": "The human reconciled both independently recorded reviews.",
            "reviewer_A_disposition": "Adopt the evidence-grounded local target.",
            "reviewer_B_disposition": "Retain the independent caution in prediction.",
        },
        "diagnosis": "The target relationship remains materially unresolved.",
        "observation_evidence": [
            f"The eligible {spec['source_observation']} contains direct evidence."
        ],
        "targeted_reasoning_relationship": "The selected local dependency and its downstream decision effects.",
        "predicted_observation_changes": "The next observation should revise, bound, or justify the relationship.",
        "predicted_execution_changes": "The matched execution family should instantiate the predicted decision delta.",
        "prior_delta_disposition": disposition,
        "expected_stable_commitments": list(
            protocol.STABLE_SEMANTIC_COMMITMENTS
        ),
        "source_observation_assessment": observation_assessment(
            spec["source_observation"]
        ),
        "intervention_text": (
            "Re-examine the evidenced relationship, propagate any justified "
            "consequences, and preserve unrelated conclusions."
        ),
    }


def sealed_record(intervention_id: str, observation_hash: str) -> dict:
    return protocol.seal_human_intervention_record(
        human_draft(intervention_id),
        intervention_id=intervention_id,
        source_observation_sha256=observation_hash,
        examiner_input_sha256=EXAMINER_INPUT_HASH,
        examiner_output_sha256=EXAMINER_OUTPUT_HASH,
        sealed_at="2026-08-29T12:00:00Z",
    )


def test_live_planning_is_raw_status_and_uses_fresh_c0_seed() -> None:
    task = protocol.base.assemble_task_text(protocol.base.load_dossier(REPO_ROOT))
    body = protocol.initial_planning_body(task_text=task)

    assert body["contents"] == [protocol.base.user_step(task)]
    assert "raw ASCII token" in body["systemInstruction"]["parts"][0]["text"]
    assert '"status"' not in str(body)
    assert "responseSchema" not in str(body)
    assert body["generationConfig"] == protocol.generation_config(
        kind="planning", seed_label="iterative:c0:turn:1"
    )
    assert protocol.READY == "READY"
    assert protocol.NOT_READY == "NOT_READY"


def test_continuation_intervention_and_execution_replay_live_history_exactly() -> None:
    history = [protocol.base.user_step("TASK"), model_content()]
    before = copy.deepcopy(history)
    observation_hash = "a" * 64
    record = sealed_record("I1", observation_hash)

    continuation = protocol.planning_continuation_body(
        full_history=history,
        checkpoint="C0",
        turn_number=2,
    )
    intervention = protocol.intervention_body(
        parent_ready_history=history,
        intervention_id="I1",
        sealed_record=record,
        source_observation_sha256=observation_hash,
    )
    execution = protocol.execution_body(
        full_history=history,
        checkpoint="C0",
        replicate=1,
    )

    assert history == before
    assert continuation["contents"][:-1] == history
    assert intervention["contents"][:-1] == history
    assert execution["contents"][:-1] == history
    assert continuation["contents"][-1] == protocol.base.user_step(
        protocol.CONTINUE_PLANNING_PROMPT
    )
    assert record["intervention_text"] in str(intervention["contents"][-1])
    assert "joint feasibility across cost ranges" not in str(
        intervention["contents"][-1]
    )
    assert execution["contents"][-1] == protocol.base.user_step(
        protocol.EXECUTION_PROMPT
    )
    assert history[1]["parts"][0]["thoughtSignature"] == "secret"


def test_human_records_are_observation_bound_and_stage_specific() -> None:
    o0_hash = "0" * 64
    i1 = sealed_record("I1", o0_hash)
    validated = protocol.validate_human_intervention_record(
        i1,
        intervention_id="I1",
        expected_observation_sha256=o0_hash,
    )

    assert validated == i1
    assert validated is not i1
    assert validated["seal_status"] == "SEALED_AFTER_O0"
    assert validated["source_observation_assessment"]["observation_id"] == "O0"
    assert set(
        validated["source_observation_assessment"]["target_diagnostic_states"]
    ) == {"I1"}

    with pytest.raises(ValueError, match="source_observation_sha256"):
        protocol.validate_human_intervention_record(
            i1,
            intervention_id="I1",
            expected_observation_sha256="1" * 64,
        )

    with pytest.raises(ValueError, match="intervention_id"):
        protocol.validate_human_intervention_record(
            i1,
            intervention_id="I2",
            expected_observation_sha256=o0_hash,
        )

    i2 = sealed_record("I2", "2" * 64)
    assert i2["source_observation"] == "O1"
    assert i2["seal_status"] == "SEALED_AFTER_O1"
    assert i2["target_checkpoint"] == "C2"
    assert i2["prior_delta_disposition"]["persist"].startswith("Keep")
    assert i2["examination_id"] == "X2"
    assert set(i2["source_observation_assessment"]["target_diagnostic_states"]) == {
        "I1",
        "I2",
    }

    i3 = sealed_record("I3", "3" * 64)
    assert i3["source_observation"] == "O2"
    assert i3["seal_status"] == "SEALED_AFTER_O2"
    assert i3["target_checkpoint"] == "C3"
    assert i3["examination_id"] == "X3"
    assert set(i3["source_observation_assessment"]["target_diagnostic_states"]) == {
        "I1",
        "I2",
        "I3",
    }


def test_every_observation_uses_exactly_the_same_six_dimension_rubric() -> None:
    for intervention_id in protocol.INTERVENTIONS:
        draft = human_draft(intervention_id)
        assessment = draft["source_observation_assessment"]
        assert set(assessment["rubric_scores"]) == set(protocol.RUBRIC_DIMENSIONS)
        protocol.validate_human_intervention_draft(
            draft, intervention_id=intervention_id
        )

    o3 = observation_assessment("O3")
    assert set(o3["rubric_scores"]) == set(protocol.RUBRIC_DIMENSIONS)
    assert set(o3["target_diagnostic_states"]) == {"I1", "I2", "I3"}


def test_final_o3_human_assessment_is_hash_bound_and_fail_closed() -> None:
    o3_hash = "f" * 64
    assessment = observation_assessment("O3")
    record = protocol.seal_final_o3_assessment(
        assessment,
        source_observation_sha256=o3_hash,
        sealed_at="2026-08-29T12:30:00Z",
    )

    assert protocol.validate_final_o3_assessment_record(
        record, expected_observation_sha256=o3_hash
    ) == record
    assert record["assessment_id"] == protocol.FINAL_O3_ASSESSMENT_ID
    assert record["seal_status"] == "SEALED_BEFORE_MATCHED_EXECUTIONS"
    assert record["source_checkpoint"] == "C3"
    assert record["source_observation"] == "O3"
    assert "examiner_input_sha256" not in record
    assert "examiner_output_sha256" not in record

    examiner_contaminated = copy.deepcopy(record)
    examiner_contaminated["examiner_output_sha256"] = EXAMINER_OUTPUT_HASH
    with pytest.raises(ValueError, match="unexpected fields"):
        protocol.validate_final_o3_assessment_record(
            examiner_contaminated, expected_observation_sha256=o3_hash
        )

    with pytest.raises(ValueError, match="source_observation_sha256"):
        protocol.validate_final_o3_assessment_record(
            record, expected_observation_sha256="e" * 64
        )

    missing_target = observation_assessment("O3")
    del missing_target["target_diagnostic_states"]["I2"]
    with pytest.raises(ValueError, match="target_diagnostic_states"):
        protocol.seal_final_o3_assessment(
            missing_target,
            source_observation_sha256=o3_hash,
            sealed_at="2026-08-29T12:30:00Z",
        )

    invalid_score = observation_assessment("O3")
    invalid_score["rubric_scores"]["resolution"] = 3
    with pytest.raises(ValueError, match="rubric_scores"):
        protocol.seal_final_o3_assessment(
            invalid_score,
            source_observation_sha256=o3_hash,
            sealed_at="2026-08-29T12:30:00Z",
        )

    with pytest.raises(ValueError, match="UTC timestamp"):
        protocol.seal_final_o3_assessment(
            assessment,
            source_observation_sha256=o3_hash,
            sealed_at="2026-08-29T12:30:00+01:00",
        )


def test_hard_contradiction_cannot_be_scored_or_labeled_as_repaired() -> None:
    assessment = observation_assessment("O3")
    assessment["target_diagnostic_states"]["I1"] = {
        "state": "RESOLVED",
        "evidence": "The contradiction is still present in O3.",
        "hard_contradiction_present": True,
    }
    with pytest.raises(ValueError, match="cannot mark.*RESOLVED"):
        protocol.seal_final_o3_assessment(
            assessment,
            source_observation_sha256="f" * 64,
            sealed_at="2026-08-29T12:30:00Z",
        )

    assessment = observation_assessment("O3")
    assessment["target_diagnostic_states"]["I1"][
        "hard_contradiction_present"
    ] = True
    assessment["rubric_scores"]["joint_coherence"] = 2
    with pytest.raises(ValueError, match="scores conflict"):
        protocol.seal_final_o3_assessment(
            assessment,
            source_observation_sha256="f" * 64,
            sealed_at="2026-08-29T12:30:00Z",
        )


def test_runtime_owns_source_binding_and_utc_seal_metadata() -> None:
    draft = human_draft("I1")
    assert "sealed_at" not in draft
    assert "source_observation_sha256" not in draft

    with pytest.raises(ValueError, match="UTC timestamp"):
        protocol.seal_human_intervention_record(
            draft,
            intervention_id="I1",
            source_observation_sha256="a" * 64,
            examiner_input_sha256=EXAMINER_INPUT_HASH,
            examiner_output_sha256=EXAMINER_OUTPUT_HASH,
            sealed_at="2026-08-29T12:00:00+01:00",
        )

    with pytest.raises(ValueError, match="source observation hash"):
        protocol.seal_human_intervention_record(
            draft,
            intervention_id="I1",
            source_observation_sha256="not-a-hash",
            examiner_input_sha256=EXAMINER_INPUT_HASH,
            examiner_output_sha256=EXAMINER_OUTPUT_HASH,
            sealed_at="2026-08-29T12:00:00Z",
        )

    with pytest.raises(ValueError, match="examiner input hash conflicts"):
        protocol.seal_human_intervention_record(
            draft,
            intervention_id="I1",
            source_observation_sha256="a" * 64,
            examiner_input_sha256="d" * 64,
            examiner_output_sha256=EXAMINER_OUTPUT_HASH,
            sealed_at="2026-08-29T12:00:00Z",
        )


def test_human_record_cannot_change_stability_scope_or_trigger_execution() -> None:
    observation_hash = "b" * 64
    changed = sealed_record("I1", observation_hash)
    changed["expected_stable_commitments"] = ["a convenient replacement"]

    with pytest.raises(ValueError, match="changed stable commitments"):
        protocol.validate_human_intervention_record(
            changed,
            intervention_id="I1",
            expected_observation_sha256=observation_hash,
        )

    executable = sealed_record("I1", observation_hash)
    executable["intervention_text"] = protocol.EXECUTION_TRIGGER
    with pytest.raises(ValueError, match="execution trigger"):
        protocol.intervention_body(
            parent_ready_history=[protocol.base.user_step("TASK"), model_content()],
            intervention_id="I1",
            sealed_record=executable,
            source_observation_sha256=observation_hash,
        )


def test_review_streams_have_distinct_provenance_and_human_reconciliation() -> None:
    draft = human_draft("I2")

    assert draft["reviewer_A"]["provenance"]["identity"] == "human_researcher"
    assert draft["reviewer_B"]["provenance"]["identity"] == (
        "independent_sol_chatgpt_reviewer_channel"
    )
    assert draft["reviewer_B"]["provenance"]["model"] == "gpt-5.6-sol"
    assert draft["reviewer_B"]["provenance"]["reasoning_effort"] == "xhigh"
    assert len(draft["reviewer_B"]["provenance"]["input_sha256"]) == 64
    assert draft["reconciliation"]["approved_by"] == "human_researcher"
    protocol.validate_human_intervention_draft(draft, intervention_id="I2")

    invalid = copy.deepcopy(draft)
    invalid["reviewer_B"]["provenance"]["identity"] = "second_human"
    with pytest.raises(ValueError, match="reviewer_B.*provenance"):
        protocol.validate_human_intervention_draft(invalid, intervention_id="I2")


def test_isolation_is_a_core_blank_text_signed_part_operator() -> None:
    response_steps = [
        {
            "role": "model",
            "parts": [
                {"text": "REA"},
                {"text": "DY", "thoughtSignature": "opaque-signature"},
            ],
        }
    ]
    before = copy.deepcopy(response_steps)

    carrier = protocol.isolate_checkpoint_carrier(response_steps)
    o0 = protocol.inspection_body(response_steps=response_steps, checkpoint="C0")
    o2 = protocol.inspection_body(response_steps=response_steps, checkpoint="C2")

    assert response_steps == before
    assert carrier == [
        protocol.base.user_step(protocol.NEUTRAL_CARRIER_STUB),
        {
            "role": "model",
            "parts": [
                {"text": ""},
                {"text": "", "thoughtSignature": "opaque-signature"},
            ],
        },
    ]
    assert "READY" not in str(carrier)
    assert "systemInstruction" not in o0
    assert o0["contents"][-1] == protocol.base.user_step(
        protocol.PRIMARY_INSPECTION_PROMPT
    )
    assert o0["generationConfig"] == o2["generationConfig"]


def test_stage_machine_requires_three_examinations_seals_and_four_observations() -> None:
    status = protocol.PREPARED_UNEXECUTED
    events = (
        "AUTHORIZE_C0",
        "READY_C0",
        "O0_ELIGIBLE",
        "RECORD_X1",
        "SEAL_I1",
        "BEGIN_C1",
        "READY_C1",
        "O1_ELIGIBLE",
        "RECORD_X2",
        "SEAL_I2",
        "BEGIN_C2",
        "READY_C2",
        "O2_ELIGIBLE",
        "RECORD_X3",
        "SEAL_I3",
        "BEGIN_C3",
        "READY_C3",
        "O3_ELIGIBLE",
        "SEAL_FINAL_O3_ASSESSMENT",
        "BEGIN_MATCHED_EXECUTIONS",
        "COMPLETE_MATCHED_EXECUTIONS",
    )
    for event in events:
        status = protocol.advance_stage(status, event)

    assert status == protocol.COMPLETED_EVIDENCE_CHAIN

    with pytest.raises(ValueError, match="invalid"):
        protocol.advance_stage(protocol.AWAITING_I1_HUMAN_SEAL, "BEGIN_C1")
    with pytest.raises(ValueError, match="invalid"):
        protocol.advance_stage(protocol.X2_EXAMINATION_PENDING, "SEAL_I2")
    with pytest.raises(ValueError, match="invalid"):
        protocol.advance_stage(
            protocol.C2_READY_AWAITING_O2, "BEGIN_MATCHED_EXECUTIONS"
        )
    with pytest.raises(ValueError, match="invalid"):
        protocol.advance_stage(
            protocol.FINAL_O3_ASSESSMENT_PENDING,
            "BEGIN_MATCHED_EXECUTIONS",
        )
    with pytest.raises(ValueError, match="invalid"):
        protocol.advance_stage(protocol.EXECUTION_GATE_OPEN, "RECORD_X4")


def test_execution_schedule_is_three_matched_randomized_quartets() -> None:
    schedule = protocol.build_execution_schedule()

    assert len(schedule) == 12
    assert [row["order"] for row in schedule] == list(range(1, 13))
    for replicate in range(1, 4):
        quartet = [row for row in schedule if row["replicate"] == replicate]
        assert len(quartet) == 4
        assert {row["checkpoint"] for row in quartet} == {
            "C0",
            "C1",
            "C2",
            "C3",
        }

        bodies = [
            protocol.execution_body(
                full_history=[
                    protocol.base.user_step("TASK"),
                    model_content(signature=f"signature-{checkpoint}"),
                ],
                checkpoint=checkpoint,
                replicate=replicate,
            )
            for checkpoint in protocol.CHECKPOINTS
        ]
        assert len(
            {body["generationConfig"]["seed"] for body in bodies}
        ) == 1

    first = protocol.execution_body(
        full_history=[protocol.base.user_step("TASK"), model_content()],
        checkpoint="C0",
        replicate=1,
    )
    second = protocol.execution_body(
        full_history=[protocol.base.user_step("TASK"), model_content()],
        checkpoint="C0",
        replicate=2,
    )
    assert first["generationConfig"]["seed"] != second["generationConfig"]["seed"]


def test_definition_freezes_iterative_semantics_without_exact_output_scoring() -> None:
    first = protocol.build_experiment_definition(REPO_ROOT)
    second = protocol.build_experiment_definition(REPO_ROOT)

    assert first == second
    assert protocol.validate_experiment_definition(first, REPO_ROOT) == []
    assert first["status"] == "prepared_unexecuted"
    assert first["trajectory"]["ordered_chain"] == [
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
    assert first["trajectory"]["X4_exists"] is False
    assert first["trajectory"]["O3_is_followed_by_human_assessment_not_X4"] is True
    assert first["planning"]["visible_channel"] == (
        "raw_text_no_schema_no_json_envelope"
    )
    assert first["planning"]["max_tokens_is_unobserved_truncation"] is True
    assert first["isolation"]["operator_status"] == (
        "protocol_defined_core_operator"
    )
    assert "off-protocol" not in str(first).lower()
    assert first["interventions"]["I1_may_be_sealed_only_after"] == "eligible O0"
    assert first["interventions"]["I2_may_be_sealed_only_after"] == "eligible O1"
    assert first["interventions"]["I3_may_be_sealed_only_after"] == "eligible O2"
    assert first["interventions"][
        "runtime_supplies_and_validates_source_observation_hash"
    ] is True
    assert first["interventions"][
        "runtime_supplies_and_validates_sealed_at_UTC"
    ] is True
    assert first["interventions"][
        "runtime_supplies_and_validates_examiner_input_output_hashes"
    ] is True
    assessments = first["observation_assessments"]
    assert assessments["observations_scored"] == ["O0", "O1", "O2", "O3"]
    assert assessments["rubric_dimensions"] == list(protocol.RUBRIC_DIMENSIONS)
    assert assessments["same_six_dimension_rubric_for_every_observation"] is True
    assert assessments["target_diagnostic_states"]["O3"] == ["I1", "I2", "I3"]
    assert assessments["final_O3_assessment"]["human_only_non_examiner"] is True
    assert assessments["final_O3_assessment"][
        "must_be_sealed_before_execution_gate_opens"
    ] is True
    assert first["state_machine"][
        "execution_gate_requires_eligible_O3_and_final_human_assessment"
    ] is True
    assert first["execution"][
        "begins_only_after_O3_is_eligible_and_final_assessment_is_sealed"
    ] is True
    assert first["isolation"][
        "every_replayable_planning_checkpoint_is_inspected"
    ] is True
    assert first["planned_calls"]["inspection_minimum_on_complete_path"] == 4
    assert first["planned_calls"]["inspection_maximum"] == 24
    assert first["planned_calls"]["execution_count_on_complete_path"] == 12
    assert first["planned_calls"]["whole_experiment_maximum"] == 60
    assert first["planned_calls"]["whole_experiment_physical_maximum"] == 180
    assert first["planned_calls"][
        "transport_retry_physical_maximum_multiplier"
    ] == 3
    assert first["planned_calls"]["completed_evidence_path_minimum"] == 20
    assert first["planned_calls"]["external_examiner_turns_exact"] == 3
    assert first["adjudication"]["labels"] == list(
        protocol.ADJUDICATION_LABELS
    )
    assert first["adjudication"]["no_keyword_counting"] is True
    assert first["adjudication"]["no_exact_output_matching"] is True
    assert first["adjudication"]["mode"] == "semantic_relational_human_review"
    assert first["adjudication"]["review_streams"]["reviewer_A"][
        "provenance_requirements"
    ]["identity"] == "human_researcher"
    assert first["adjudication"]["review_streams"]["reviewer_B"][
        "provenance_requirements"
    ]["identity"] == "independent_sol_chatgpt_reviewer_channel"
    assert first["adjudication"]["review_streams"]["reviewer_B"][
        "provenance_requirements"
    ]["model"] == "gpt-5.6-sol"
    assert first["adjudication"]["review_streams"]["reviewer_B"][
        "provenance_requirements"
    ]["reasoning_effort"] == "xhigh"
    assert first["adjudication"]["human_researcher_is_final_adjudicator"] is True
    assert first["adjudication"][
        "every_O_i_is_scored_on_the_same_six_dimensions"
    ] is True
    assert first["adjudication"][
        "final_O3_scores_are_human_sealed_before_execution"
    ] is True
    assert first["participant_topology"]["participant_roles"] == 3
    assert first["participant_topology"]["model_agents"] == 2
    assert first["participant_topology"]["planner"]["model"] == "gemini-3.7-flash"
    assert first["participant_topology"]["examiner"]["model"] == "gpt-5.6-sol"
    assert first["participant_topology"]["examiner"]["reasoning_effort"] == "xhigh"


def test_fixed_examination_charters_allow_adaptive_nonanswer_targets() -> None:
    i1_rule = protocol.INTERVENTION_SELECTION_RULES["I1"]
    i2_rule = protocol.INTERVENTION_SELECTION_RULES["I2"]
    i3_rule = protocol.INTERVENTION_SELECTION_RULES["I3"]

    assert protocol.EXAMINATIONS == ("X1", "X2", "X3")
    assert "epistemic-hinge charter" in i1_rule
    assert "adversarial-alternative/falsification charter" in i2_rule
    assert "global-reintegration/joint-feasibility charter" in i3_rule
    assert "adaptively select" in i2_rule
    assert "adaptively select" in i3_rule
    assert "prescribing a replacement answer" in i1_rule
    assert "prescribe a replacement answer" in i2_rule
    assert "prescribe a replacement answer" in i3_rule
    assert "X4" not in protocol.EXAMINATION_CHARTERS


def test_private_generic_fault_atlas_and_human_rubric_are_frozen() -> None:
    definition = protocol.build_experiment_definition(REPO_ROOT)
    atlas_ids = {row["fault_id"] for row in protocol.PRIVATE_FAULT_ATLAS}
    required_faults = {
        "EVIDENCE_INFERENCE_CONFLATION",
        "PROVENANCE_WEIGHTING_FAILURE",
        "UNSUPPORTED_COMMITMENT",
        "FAVORABLE_BOUND_SELECTION",
        "RESOURCE_COLLISION",
        "CALENDAR_COLLISION",
        "AUTHORITY_MISMATCH",
        "DEPENDENCY_CYCLE",
        "UNBOUNDED_CRITICAL_UNCERTAINTY",
        "FALLBACK_WITHOUT_TRIGGER",
        "TRIGGER_WITHOUT_ACTIONABLE_FALLBACK",
        "ALTERNATIVE_PREMATURELY_DISCARDED",
        "LOCAL_GLOBAL_INCONSISTENCY",
    }

    assert required_faults <= atlas_ids
    serialized_atlas = str(protocol.PRIVATE_FAULT_ATLAS)
    for dossier_term in ("North River", "Eastbank", "Tern", "RRPS"):
        assert dossier_term not in serialized_atlas

    dimensions = [row["dimension"] for row in protocol.SEMANTIC_HUMAN_RUBRIC]
    assert dimensions == [
        "defect_recognition",
        "resolution",
        "dependency_propagation",
        "locality",
        "evidentiary_discipline",
        "joint_coherence",
    ]
    rubric = {row["dimension"]: row["anchors"] for row in protocol.SEMANTIC_HUMAN_RUBRIC}
    assert rubric["resolution"] == {
        "0": "unresolved or rationalized",
        "1": "bounded",
        "2": "resolved",
    }
    assert rubric["locality"] == {
        "0": "wholesale re-solve",
        "1": "mixed local repair and collateral movement",
        "2": "stable unrelated commitments",
    }
    assert rubric["joint_coherence"] == {
        "0": "contradiction remains",
        "1": "joint feasibility remains uncertain",
        "2": "jointly feasible",
    }
    assert protocol.DIAGNOSTIC_STATES == (
        "UNRECOGNIZED",
        "RECOGNIZED",
        "BOUNDED",
        "RESOLVED",
        "RATIONALIZED",
    )
    private = definition["private_measurement_material"]
    assert private["invisible_to_gemini_planner"] is True
    assert private["generic_and_contains_no_dossier_specific_answer"] is True
    assert definition["adjudication"][
        "rubric_scores_are_descriptive_not_a_sole_stop_rule"
    ] is True
    assert definition["adjudication"]["hard_contradictions_gate_repair"] is True
    assert definition["adjudication"][
        "matched_executions_are_separate_behavioral_evidence"
    ] is True
    assert definition["adjudication"][
        "diagnostic_state_is_recorded_per_target_across_available_later_observations"
    ] is True
