import copy
from pathlib import Path

import pytest

from thoughtlab.reasoningEngineering import modernization_protocol as protocol


REPO_ROOT = Path(__file__).resolve().parents[1]


def model_content(text: str = "READY", signature: str = "secret") -> dict:
    return {
        "role": "model",
        "parts": [{"text": text, "thoughtSignature": signature}],
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
    assert body["generationConfig"]["temperature"] == 0.0
    assert "topP" not in body["generationConfig"]
    assert "topK" not in body["generationConfig"]
    assert "raw ASCII token" in body["systemInstruction"]["parts"][0]["text"]
    assert body["contents"][0]["role"] == "user"
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


def test_isolation_preserves_signature_and_blanks_only_detached_text() -> None:
    source = [model_content("READY", "opaque-signature")]
    before = copy.deepcopy(source)

    carrier = protocol.isolate_response_steps(source)

    assert source == before
    assert carrier[0] == protocol.user_step(protocol.NEUTRAL_CARRIER_STUB)
    assert carrier[1] == {
        "role": "model",
        "parts": [{"text": "", "thoughtSignature": "opaque-signature"}],
    }
    assert carrier[1] is not source[0]
    assert "READY" not in str(carrier)
    assert "North River" not in str(carrier)


def test_thought_only_truncated_checkpoint_can_be_isolated_without_synthetic_output() -> None:
    source = [model_content("partial", "truncated-signature")]

    carrier = protocol.isolate_response_steps(source)

    assert carrier == [
        protocol.user_step(protocol.NEUTRAL_CARRIER_STUB),
        {
            "role": "model",
            "parts": [{"text": "", "thoughtSignature": "truncated-signature"}],
        },
    ]
    assert source[0]["parts"][0]["text"] == "partial"


@pytest.mark.parametrize(
    "source",
    [
        [
            {
                "role": "model",
                "parts": [
                    {
                        "text": "READY",
                        "thoughtSignature": "secret",
                        "readable_metadata": "bad",
                    }
                ],
            }
        ],
        [
            {
                "role": "assistant",
                "parts": [{"text": "READY", "thoughtSignature": "secret"}],
                "readable_metadata": "READY",
            },
        ],
        [
            {
                "role": "model",
                "parts": [
                    {
                        "text": "READY",
                        "thoughtSignature": "secret",
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


def test_isolation_validates_then_removes_every_visible_text_block() -> None:
    source = [
        {
            "role": "model",
            "parts": [
                {"text": "REA"},
                {"text": "DY", "thoughtSignature": "opaque"},
            ],
        },
    ]

    carrier = protocol.isolate_response_steps(source)

    assert carrier == [
        protocol.user_step(protocol.NEUTRAL_CARRIER_STUB),
        {
            "role": "model",
            "parts": [
                {"text": ""},
                {"text": "", "thoughtSignature": "opaque"},
            ],
        },
    ]
    assert "READY" not in str(carrier)


def test_inspection_is_detached_holistic_and_has_no_ordinary_context() -> None:
    source = [model_content("NOT_READY")]
    body = protocol.inspection_body(
        response_steps=source,
        checkpoint_id="ID_0123456789ABCDEFGHJKMNPQRS",
    )
    sibling = protocol.inspection_body(
        response_steps=source,
        checkpoint_id="ID_11111111111111111111111111",
    )

    assert "systemInstruction" not in body
    assert body["contents"][-1] == protocol.user_step(
        protocol.PRIMARY_INSPECTION_PROMPT
    )
    assert "integrated decision structure" in protocol.PRIMARY_INSPECTION_PROMPT
    assert "option, evidence, assumption" not in protocol.PRIMARY_INSPECTION_PROMPT
    assert "NOT_READY" not in str(body["contents"][:-1])
    assert body["contents"][1]["parts"][0]["text"] == ""
    assert body["contents"][1]["parts"][0]["thoughtSignature"] == "secret"
    assert "North River" not in str(body)
    assert body["generationConfig"] == sibling["generationConfig"]
    assert body["generationConfig"] == protocol.generation_config(
        kind="inspection",
        seed_label=protocol.PRIMARY_INSPECTION_SEED_LABEL,
    )


def test_neutral_continuation_and_execution_preserve_exact_parent_history() -> None:
    history = [protocol.user_step("task"), model_content("READY")]
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

    assert continuation["contents"][:-1] == history
    assert continuation["contents"][-1] == protocol.user_step(
        protocol.CONTINUE_PLANNING_PROMPT
    )
    assert "whatever reasoning remains necessary" in protocol.CONTINUE_PLANNING_PROMPT
    assert "what still prevents" not in protocol.CONTINUE_PLANNING_PROMPT
    assert execution["contents"][:-1] == history
    assert execution["contents"][-1] == protocol.user_step(protocol.EXECUTION_PROMPT)
    assert execution["generationConfig"] == adjusted_execution["generationConfig"]
    assert execution["generationConfig"]["seed"] != second_replicate[
        "generationConfig"
    ]["seed"]


def test_intervention_is_diagnostic_branch_and_cannot_trigger_execution() -> None:
    history = [protocol.user_step("task"), model_content("READY")]
    body = protocol.intervention_body(
        baseline_ready_history=history,
        intervention_text=(
            "Re-examine the assumed scope of emergency authority and its "
            "consequences. Preserve conclusions that remain justified."
        ),
    )

    assert body["contents"][:-1] == history
    assert "Re-examine the assumed scope" in str(body["contents"][-1])
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
