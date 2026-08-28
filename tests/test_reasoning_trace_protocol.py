import copy
import json
from pathlib import Path

import pytest

from thoughtlab.reasoningTraces import reasoning_trace_protocol as protocol


def thought_step(signature: str = "signed-state") -> dict:
    return {"type": "thought", "signature": signature, "summary": []}


def model_output(text: str = "READY") -> dict:
    return {"type": "model_output", "content": [{"type": "text", "text": text}]}


def test_definition_is_deterministic_valid_and_35_to_39_calls() -> None:
    first = protocol.build_experiment_definition()
    second = protocol.build_experiment_definition()

    assert first == second
    assert protocol.validate_experiment_definition(first) == []
    assert len(first["schedule"]["readouts"]) == 31
    assert first["planned_calls"]["logical_minimum_when_both_sources_eligible"] == 35
    assert first["planned_calls"]["logical_maximum_when_both_sources_eligible"] == 39
    assert first["planned_calls"]["physical_maximum"] == 117


def test_readout_schedule_starts_with_two_blunt_carriers_then_is_complete() -> None:
    schedule = protocol.build_readout_schedule()

    assert schedule[:2] == [
        {"arm": "signature_only", "source": "source_A", "probe": "blunt"},
        {"arm": "signature_only", "source": "source_B", "probe": "blunt"},
    ]
    signature_rows = [row for row in schedule if row["arm"] == "signature_only"]
    assert len(signature_rows) == 26
    assert {row["probe"] for row in signature_rows} == {
        "blunt",
        *(label for label, _ in protocol.TARGETED_PROBES),
    }
    assert sorted(row["arm"] for row in schedule if row["arm"] != "signature_only") == [
        "full_prefix",
        "full_prefix",
        "probe_only",
        "task_only",
        "visible_ready_only",
    ]


def test_prompt_split_is_exact_and_rejects_ambiguous_envelopes() -> None:
    assert protocol.split_bookforge_prompt("SYSTEM:\nsys\nUSER:\nuser") == (
        "sys",
        "user",
    )
    with pytest.raises(ValueError):
        protocol.split_bookforge_prompt("sys\nUSER:\nuser")
    with pytest.raises(ValueError):
        protocol.split_bookforge_prompt("SYSTEM:\ns\nUSER:\nu\nUSER:\nx")


def test_selected_task_hashes_and_excludes_historical_artifacts() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    capsule_path = repo_root / protocol.CAPSULE_RELATIVE_PATH
    if not capsule_path.exists():
        pytest.skip("private historical corpus is not present")

    task = protocol.verify_selected_task(repo_root)
    capsule = json.loads(capsule_path.read_text(encoding="utf-8"))
    body = protocol.source_initial_body(
        system_text=task["system_text"],
        user_text=task["user_text"],
        source="source_A",
    )
    encoded = protocol.canonical_json_bytes(body).decode("utf-8")
    historical_visible = str(capsule["visible_output"])
    historical_signature = str(capsule["signed_part"]["thoughtSignature"])

    assert historical_visible not in encoded
    assert historical_signature not in encoded
    assert protocol.PLANNING_CONTROLLER in body["input"][0]["content"][0]["text"]
    assert body["system_instruction"] == task["system_text"]


def test_source_requests_use_same_task_but_distinct_frozen_seeds() -> None:
    a = protocol.source_initial_body(
        system_text="system", user_text="task", source="source_A"
    )
    b = protocol.source_initial_body(
        system_text="system", user_text="task", source="source_B"
    )

    assert a["input"] == b["input"]
    assert a["system_instruction"] == b["system_instruction"] == "system"
    assert a["generation_config"]["seed"] != b["generation_config"]["seed"]


def test_not_ready_followup_preserves_every_prior_step_exactly() -> None:
    history = [protocol.user_step("task"), thought_step(), model_output("NOT_READY")]
    snapshot = copy.deepcopy(history)

    body = protocol.source_followup_body(
        system_text="system",
        full_history=history,
        source="source_A",
        round_number=2,
    )

    assert history == snapshot
    assert body["input"][:-1] == history
    assert body["input"][-1] == protocol.user_step(protocol.CONTINUE_PLANNING_PROMPT)


def test_detached_readout_contains_only_exact_thoughts_and_one_probe() -> None:
    thoughts = [thought_step("one"), thought_step("two")]
    body = protocol.signature_readout_body(
        thought_steps=thoughts,
        source="source_A",
        probe_label="plan",
    )

    assert body["input"][:-1] == thoughts
    assert body["input"][-1]["type"] == "user_input"
    assert "What plan had you formed?" in str(body["input"][-1])
    assert "visible planning-phase responses does not apply" in str(body["input"][-1])
    assert "READY" not in str(body["input"])
    assert "BookForge" not in str(body["input"])
    assert "system_instruction" not in body


def test_detached_carrier_rejects_readable_payload_and_bad_source_label() -> None:
    assert protocol.validate_detached_thought_steps([thought_step()]) == []
    assert protocol.validate_detached_thought_steps(
        [{"type": "thought", "signature": "s", "summary": ""}]
    ) == []
    assert protocol.validate_detached_thought_steps([])
    assert protocol.validate_detached_thought_steps(
        [{"type": "thought", "signature": "s", "content": [{"text": "leak"}]}]
    )
    assert protocol.validate_detached_thought_steps(
        [{"type": "thought", "signature": "s", "summary": ["leak"]}]
    )
    with pytest.raises(ValueError, match="unknown source label"):
        protocol.signature_readout_body(
            thought_steps=[thought_step()], source="source_Z", probe_label="blunt"
        )


def test_controls_and_execution_have_the_frozen_information_surfaces() -> None:
    thoughts = [thought_step()]
    ready = [model_output()]
    history = [protocol.user_step("task"), *thoughts, *ready]

    full = protocol.full_prefix_control_body(
        system_text="sys", full_history=history, source="source_A"
    )
    visible = protocol.visible_ready_control_body(model_output_steps=ready)
    probe = protocol.probe_only_control_body()
    task = protocol.task_only_control_body(system_text="sys", user_text="task")
    execute = protocol.execution_body(system_text="sys", full_history=history)

    assert full["input"][:-1] == history
    assert full["system_instruction"] == "sys"
    assert visible["input"][:-1] == ready
    assert len(probe["input"]) == 1
    assert "signed-state" not in str(task)
    assert "fresh-analysis control" in str(task)
    assert execute["input"][:-1] == history
    assert execute["input"][-1] == protocol.user_step(protocol.EXECUTE_PROMPT)
    assert execute["system_instruction"] == "sys"
    blunt = protocol.signature_readout_body(
        thought_steps=thoughts, source="source_A", probe_label="blunt"
    )
    assert {
        protocol.sha256_json(body["generation_config"])
        for body in (full, visible, probe, task, blunt)
    } == {protocol.sha256_json(blunt["generation_config"])}


def test_every_constructed_request_is_free_of_tool_and_function_structure() -> None:
    requests = [
        protocol.source_initial_body(
            system_text="system", user_text="task", source="source_A"
        ),
        protocol.signature_readout_body(
            thought_steps=[thought_step()], source="source_A", probe_label="blunt"
        ),
        protocol.visible_ready_control_body(model_output_steps=[model_output()]),
        protocol.probe_only_control_body(),
        protocol.task_only_control_body(system_text="system", user_text="task"),
        protocol.execution_body(
            system_text="system",
            full_history=[protocol.user_step("task"), thought_step(), model_output()],
        ),
    ]

    for request in requests:
        protocol.assert_no_function_or_tool_structure(request)
        encoded = protocol.canonical_json_bytes(request)
        assert b'"tools"' not in encoded
        assert b'"tool_choice"' not in encoded
        assert b'"function_call"' not in encoded
        assert b'"function_result"' not in encoded
        assert b'"response_format"' not in encoded

    for forbidden_key in (
        "functions",
        "response_schema",
        "function_call",
        "tool_call",
    ):
        with pytest.raises(ValueError, match="forbidden request key"):
            protocol.assert_no_function_or_tool_structure(
                {"type": "model_output", forbidden_key: {"unexpected": True}}
            )


def test_boundary_normalization_tolerates_only_unicode_and_outer_whitespace() -> None:
    assert protocol.normalize_boundary_token(" \r\nREADY\t") == "READY"
    assert protocol.normalize_boundary_token("NOT_READY\n") == "NOT_READY"
    assert protocol.normalize_boundary_token("ready") == "ready"
    assert protocol.normalize_boundary_token("READY.") == "READY."
