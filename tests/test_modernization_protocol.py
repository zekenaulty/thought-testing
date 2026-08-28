import copy
from pathlib import Path

import pytest

from thoughtlab.reasoningEngineering import modernization_protocol as protocol


REPO_ROOT = Path(__file__).resolve().parents[1]


def thought(signature: str = "secret") -> dict:
    return {"type": "thought", "signature": signature, "summary": []}


def model_output(text: str = "READY") -> dict:
    return {
        "type": "model_output",
        "content": [{"type": "text", "text": text}],
    }


def test_semantic_state_contract_is_not_a_numbered_thinking_script() -> None:
    prompt = protocol.PLANNING_SYSTEM_INSTRUCTION
    normalized = " ".join(prompt.split())

    assert "Use your private reasoning in whatever order" in prompt
    assert "preserves the basis for why options are selected" in prompt
    assert "source provenance, incentives, reliability, scope" in prompt
    assert "Do not organize reasoning merely to demonstrate compliance" in normalized
    assert "READY means\ndecision-ready, not certain" in prompt
    assert "1. COMPREHEND" not in prompt
    assert "Step 1" not in prompt


def test_planning_channel_is_raw_text_without_json_schema_or_deprecated_sampling() -> None:
    task = protocol.assemble_task_text(protocol.load_dossier(REPO_ROOT))
    body = protocol.initial_planning_body(task_text=task)
    serialized = str(body)

    assert "response_format" not in body
    assert "response_schema" not in body
    assert "tools" not in body
    assert "temperature" not in body["generation_config"]
    assert "top_p" not in body["generation_config"]
    assert "top_k" not in body["generation_config"]
    assert "raw ASCII token" in body["system_instruction"]
    assert '{"status"' not in serialized
    protocol.assert_no_function_tool_or_schema_structure(body)


def test_readiness_normalization_repairs_only_transport_whitespace() -> None:
    assert protocol.normalize_readiness_text(" \r\nREADY\t") == "READY"
    assert protocol.normalize_readiness_text("NOT_READY\n") == "NOT_READY"
    assert protocol.normalize_readiness_text("READY.") == "READY."
    assert protocol.normalize_readiness_text("```READY```") == "```READY```"
    assert protocol.normalize_readiness_text('{"status":"READY"}') == (
        '{"status":"READY"}'
    )


def test_isolation_preserves_thought_exactly_and_blanks_only_visible_text() -> None:
    source = [
        thought("opaque-signature"),
        model_output("READY"),
    ]
    before = copy.deepcopy(source)

    carrier = protocol.isolate_response_steps(source)

    assert source == before
    assert carrier[0] == protocol.user_step(protocol.NEUTRAL_CARRIER_STUB)
    assert carrier[1] == source[0]
    assert carrier[1] is not source[0]
    assert carrier[2]["content"][0]["text"] == ""
    assert "READY" not in str(carrier)
    assert "North River" not in str(carrier)


def test_thought_only_truncated_checkpoint_can_be_isolated_without_synthetic_output() -> None:
    source = [thought("truncated-signature")]

    carrier = protocol.isolate_response_steps(source)

    assert carrier == [
        protocol.user_step(protocol.NEUTRAL_CARRIER_STUB),
        thought("truncated-signature"),
    ]
    assert all(step.get("type") != "model_output" for step in carrier)


@pytest.mark.parametrize(
    "source",
    [
        [
            {
                "type": "thought",
                "signature": "secret",
                "summary": [],
                "content": [{"type": "text", "text": "readable thought"}],
            }
        ],
        [
            thought(),
            {
                "type": "model_output",
                "content": [{"type": "text", "text": "READY"}],
                "readable_metadata": "READY",
            },
        ],
        [
            thought(),
            {
                "type": "model_output",
                "content": [
                    {
                        "type": "text",
                        "text": "READY",
                        "annotation": "ordinary task context",
                    }
                ],
            },
        ],
    ],
)
def test_isolation_rejects_every_unexpected_readable_field(
    source: list[dict],
) -> None:
    before = copy.deepcopy(source)

    with pytest.raises(ValueError, match="unexpected fields"):
        protocol.isolate_response_steps(source)

    assert source == before


def test_isolation_blanks_every_allowed_visible_text_block() -> None:
    source = [
        thought("opaque"),
        {
            "type": "model_output",
            "content": [
                {"type": "text", "text": "REA"},
                {"type": "text", "text": "DY"},
            ],
        },
    ]

    carrier = protocol.isolate_response_steps(source)

    assert carrier[2]["content"] == [
        {"type": "text", "text": ""},
        {"type": "text", "text": ""},
    ]
    assert "READY" not in str(carrier)


def test_inspection_is_detached_holistic_and_has_no_ordinary_context() -> None:
    source = [thought(), model_output("NOT_READY")]
    body = protocol.inspection_body(
        response_steps=source,
        checkpoint_id="ID_0123456789ABCDEFGHJKMNPQRS",
    )
    sibling = protocol.inspection_body(
        response_steps=source,
        checkpoint_id="ID_11111111111111111111111111",
    )

    assert "system_instruction" not in body
    assert body["input"][-1] == protocol.user_step(
        protocol.PRIMARY_INSPECTION_PROMPT
    )
    assert "integrated decision structure" in protocol.PRIMARY_INSPECTION_PROMPT
    assert "option, evidence, assumption" not in protocol.PRIMARY_INSPECTION_PROMPT
    assert "NOT_READY" not in str(body["input"][:-1])
    assert "North River" not in str(body)
    assert body["generation_config"] == sibling["generation_config"]
    assert body["generation_config"] == protocol.generation_config(
        kind="inspection",
        seed_label=protocol.PRIMARY_INSPECTION_SEED_LABEL,
    )


def test_neutral_continuation_and_execution_preserve_exact_parent_history() -> None:
    history = [protocol.user_step("task"), thought(), model_output("READY")]
    continuation = protocol.planning_continuation_body(
        full_history=history,
        phase="baseline",
        turn_number=2,
    )
    execution = protocol.execution_body(
        full_history=history,
        branch="baseline",
        replicate=1,
    )
    adjusted_execution = protocol.execution_body(
        full_history=history,
        branch="adjusted",
        replicate=1,
    )
    second_replicate = protocol.execution_body(
        full_history=history,
        branch="baseline",
        replicate=2,
    )

    assert continuation["input"][:-1] == history
    assert continuation["input"][-1] == protocol.user_step(
        protocol.CONTINUE_PLANNING_PROMPT
    )
    assert "whatever reasoning remains necessary" in protocol.CONTINUE_PLANNING_PROMPT
    assert "what still prevents" not in protocol.CONTINUE_PLANNING_PROMPT
    assert execution["input"][:-1] == history
    assert execution["input"][-1] == protocol.user_step(protocol.EXECUTION_PROMPT)
    assert execution["generation_config"] == adjusted_execution["generation_config"]
    assert execution["generation_config"]["seed"] != second_replicate[
        "generation_config"
    ]["seed"]


def test_intervention_is_diagnostic_branch_and_cannot_trigger_execution() -> None:
    history = [protocol.user_step("task"), thought(), model_output("READY")]
    body = protocol.intervention_body(
        baseline_ready_history=history,
        intervention_text=(
            "Re-examine the assumed scope of emergency authority and its "
            "consequences. Preserve conclusions that remain justified."
        ),
    )

    assert body["input"][:-1] == history
    assert "Re-examine the assumed scope" in str(body["input"][-1])
    with pytest.raises(ValueError, match="execution trigger"):
        protocol.intervention_body(
            baseline_ready_history=history,
            intervention_text=protocol.EXECUTION_TRIGGER,
        )


def test_definition_is_deterministic_and_freezes_approved_call_bounds() -> None:
    first = protocol.build_experiment_definition(REPO_ROOT)
    second = protocol.build_experiment_definition(REPO_ROOT)

    assert first == second
    assert protocol.validate_experiment_definition(first, REPO_ROOT) == []
    assert first["status"] == "prepared_unexecuted"
    assert first["planned_calls"]["whole_experiment_maximum"] == 30
    assert first["execution"]["replicates_per_checkpoint"] == 3
    assert first["isolation"]["primary_observation_surface"] is True
    assert first["isolation"]["generation_config"] == protocol.generation_config(
        kind="inspection",
        seed_label=protocol.PRIMARY_INSPECTION_SEED_LABEL,
    )
    assert first["execution"]["schedule"] == protocol.build_execution_schedule()
    assert first["isolation"][
        "completed_non_stop_finish_reason_is_ineligible"
    ] is True
    assert first["execution"][
        "completed_non_stop_finish_reason_is_ineligible"
    ] is True
    assert first["isolation"]["explicit_finish_reasons_are_preserved"] is True
    assert first["execution"]["explicit_finish_reasons_are_preserved"] is True
    assert [row["order"] for row in first["execution"]["schedule"]] == list(
        range(1, 2 * protocol.EXECUTION_REPLICATES_PER_CHECKPOINT + 1)
    )
    for replicate in range(1, protocol.EXECUTION_REPLICATES_PER_CHECKPOINT + 1):
        pair = [
            row
            for row in first["execution"]["schedule"]
            if row["replicate"] == replicate
        ]
        assert len(pair) == 2
        assert {row["branch"] for row in pair} == {"baseline", "adjusted"}
        assert (
            first["execution"]["generation_configs"]["baseline"][replicate - 1]
            == first["execution"]["generation_configs"]["adjusted"][replicate - 1]
        )
    assert first["planning"]["visible_channel"] == (
        "raw_text_no_schema_no_json_envelope"
    )
    assert first["state_machine"]["finish_reason_normalization"] == (
        "strip, uppercase, and replace hyphen/space with underscore"
    )
    assert first["state_machine"]["completed_finish_reasons"] == ["STOP"]
    assert first["state_machine"]["immutable_consumption_claim_statuses"] == [
        "CLAIMED"
    ]
    assert first["state_machine"]["consumption_terminal_record_statuses"] == [
        "COMPLETED",
        "TERMINATED_ERROR",
    ]
    assert first["transport"][
        "human_terminal_commands_verify_reviewed_freeze_and_task"
    ] is True
    assert first["transport"][
        "human_review_preflight_has_derived_exact_nonraw_closure"
    ] is True
    assert first["transport"][
        "human_disposition_mutations_are_canonical_run_bound"
    ] is True
    assert first["transport"][
        "derived_closure_rejects_unexpected_directories"
    ] is True
    assert first["transport"][
        "raw_inventory_is_flat_and_rejects_subdirectories"
    ] is True
    assert first["transport"][
        "completed_phase_archives_are_reverse_verified_before_success"
    ] is True
    assert first["transport"][
        "measurement_seal_timestamps_are_chronology_checked"
    ] is True
    assert first["transport"]["verifier_cli_reports_exact_file_byte_hashes"] is True
