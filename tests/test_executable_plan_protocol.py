from __future__ import annotations

import copy
import random
import unittest

from thoughtlab.executablePlans import executable_plan_protocol as protocol
from thoughtlab.executablePlans.executable_plan_protocol import (
    APPLY_TOOL,
    ATOMIC_READOUT_REPEATS,
    MAX_POST_OBSERVATION_DECISIONS,
    MODEL,
    NO_FUNCTION_CALLS_TOOL_CHOICE,
    OBSERVATION_ROLES,
    OPERATION_ROLES,
    PROSPECTIVE_REPEATS,
    SOURCE_LABELS,
    STRUCTURED_POLICY_REPEATS,
    SYSTEM_INSTRUCTION,
    TASK_ONLY_REPEATS,
    TOOL_DECLARATIONS,
    VERIFY_TOKEN,
    VERIFY_TOOL,
    apply_simulator_action,
    atomic_prediction_prompt,
    build_executable_interaction_body,
    canonical_action_token,
    canonical_json_bytes,
    create_execution_manifest,
    create_experiment_definition,
    expected_topology,
    initial_simulator_state,
    is_complete_success_sequence,
    open_readout_prompt,
    sha256_json,
    strict_json_loads,
    structured_policy_prompt,
    task_only_prediction_prompt,
    validate_execution_manifest,
    validate_experiment_definition,
    valid_success_sequences,
)
from thoughtlab.opaque_ids import generate_opaque_id, is_opaque_id


class ExecutablePlanDefinitionTests(unittest.TestCase):
    def test_definition_is_deterministic_valid_and_fixed_to_37_flash(self) -> None:
        left = create_experiment_definition(master_seed=8675309)
        right = create_experiment_definition(master_seed=8675309)

        self.assertEqual(left, right)
        self.assertEqual(validate_experiment_definition(left), [])
        self.assertEqual(left["model"], "gemini-3.7-flash")
        self.assertEqual(left["model"], MODEL)
        self.assertEqual(left["system_instruction"], SYSTEM_INSTRUCTION)
        self.assertEqual(left["tools"], TOOL_DECLARATIONS)
        self.assertEqual(
            left["readouts"]["task_only_tool_choice"],
            NO_FUNCTION_CALLS_TOOL_CHOICE,
        )
        self.assertIs(left["api"]["store"], False)
        self.assertIsNone(left["api"]["previous_interaction_id"])

    def test_source_a_and_b_requests_are_byte_identical(self) -> None:
        definition = create_experiment_definition(master_seed=4201)
        source = definition["source_generation"]
        a = source["requests"][SOURCE_LABELS[0]]
        b = source["requests"][SOURCE_LABELS[1]]

        self.assertEqual(canonical_json_bytes(a), canonical_json_bytes(b))
        self.assertEqual(sha256_json(a), source["request_sha256"])
        self.assertEqual(sha256_json(b), source["request_sha256"])
        self.assertNotIn("source_A", canonical_json_bytes(a).decode("utf-8"))
        self.assertNotIn("source_B", canonical_json_bytes(a).decode("utf-8"))
        self.assertEqual(a["system_instruction"], SYSTEM_INSTRUCTION)
        self.assertEqual(a["tools"], TOOL_DECLARATIONS)
        self.assertNotIn("response_format", a)

    def test_local_request_builder_deep_copies_all_mutable_inputs(self) -> None:
        steps = [{"type": "user_input", "content": [{"type": "text", "text": "x"}]}]
        config = {"seed": 7}
        response_format = {"type": "text"}
        tools = copy.deepcopy(TOOL_DECLARATIONS)
        body = build_executable_interaction_body(
            model=MODEL,
            input_steps=steps,
            generation_config_value=config,
            response_format=response_format,
            system_instruction=SYSTEM_INSTRUCTION,
            tools=tools,
        )

        steps[0]["content"][0]["text"] = "changed"
        config["seed"] = 8
        response_format["type"] = "changed"
        tools[0]["name"] = "changed"
        self.assertEqual(body["input"][0]["content"][0]["text"], "x")
        self.assertEqual(body["generation_config"]["seed"], 7)
        self.assertEqual(body["response_format"]["type"], "text")
        self.assertEqual(body["tools"][0]["name"], "inspect_environment")

    def test_ids_are_unique_type_neutral_and_task_has_no_serialized_plan(self) -> None:
        task = create_experiment_definition(master_seed=13579)["task"]
        aliases = task["report_aliases"]
        ids = list(aliases.values())

        self.assertEqual(set(aliases), {*OBSERVATION_ROLES, *OPERATION_ROLES})
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(is_opaque_id(value) for value in ids))
        self.assertTrue(all(value.startswith("ID_") for value in ids))
        for value in ids:
            self.assertEqual(task["task_text"].count(value), 1)
        lowered = task["task_text"].casefold()
        for forbidden in (
            "source_a",
            "source_b",
            "thought signature",
            "serialized plan",
            "step 1",
            "step 2",
            "->",
        ):
            self.assertNotIn(forbidden, lowered)

    def test_task_has_three_distinct_topologies_and_real_alternatives(self) -> None:
        task = create_experiment_definition(master_seed=2468)["task"]
        aliases = task["report_aliases"]

        one = valid_success_sequences(task, aliases["one_operation"])
        two = valid_success_sequences(task, aliases["two_ordered_operations"])
        none = valid_success_sequences(task, aliases["no_operation"])
        self.assertEqual(len(one), 2)
        self.assertEqual(len(two), 2)
        self.assertEqual(none, [[VERIFY_TOKEN]])
        self.assertNotEqual(one[0][0], one[1][0])
        self.assertNotEqual(two[0][0], two[1][0])
        self.assertNotEqual(two[0][1], two[1][1])
        self.assertEqual(
            expected_topology(task, aliases["one_operation"]),
            (APPLY_TOOL, VERIFY_TOOL),
        )
        self.assertEqual(
            expected_topology(task, aliases["two_ordered_operations"]),
            (APPLY_TOOL, APPLY_TOOL, VERIFY_TOOL),
        )
        self.assertEqual(
            expected_topology(task, aliases["no_operation"]), (VERIFY_TOOL,)
        )
        self.assertTrue(all(len(path) <= MAX_POST_OBSERVATION_DECISIONS for path in one + two + none))

    def test_repeated_schedule_and_task_derived_call_accounting(self) -> None:
        definition = create_experiment_definition(master_seed=99991)
        schedule = definition["schedule"]

        self.assertEqual(PROSPECTIVE_REPEATS, 3)
        self.assertEqual(ATOMIC_READOUT_REPEATS, 2)
        self.assertEqual(STRUCTURED_POLICY_REPEATS, 2)
        self.assertEqual(TASK_ONLY_REPEATS, 3)
        self.assertEqual(
            schedule["phase_order"],
            ["source_generation", "prospective", "readout_execution"],
        )
        self.assertIn("automatic", schedule["phase_transition"])
        self.assertEqual(len(schedule["source_generation"]), 2)
        self.assertEqual(len(schedule["prospective"]), 18)
        self.assertEqual(len(schedule["readout_execution"]), 35)
        arms = [row["arm"] for row in schedule["readout_execution"]]
        self.assertEqual(arms.count("atomic"), 12)
        self.assertEqual(arms.count("structured"), 4)
        self.assertEqual(arms.count("task_only"), 9)
        full_task_rows = [
            row
            for row in schedule["readout_execution"]
            if row["arm"] == "full_task_semantic"
        ]
        self.assertEqual([row["repeat"] for row in sorted(full_task_rows, key=lambda row: row["repeat"])], [1, 2])
        self.assertTrue(all("source" not in row for row in full_task_rows))
        planned = definition["planned_calls"]
        self.assertIsNone(planned["global_arbitrary_call_ceiling"])
        self.assertEqual(planned["prospective_branch_decision_limit"], 3)
        self.assertEqual(
            planned["eligible_execution_logical_range"],
            {
                "minimum": 55,
                "expected_when_all_trajectories_are_valid": 73,
                "maximum_from_frozen_schedule_and_task_topology": 73,
            },
        )

    def test_schedule_validation_rejects_count_preserving_duplicate_cells(self) -> None:
        definition = create_experiment_definition(master_seed=99_992)
        duplicate = copy.deepcopy(definition)
        prospective = duplicate["schedule"]["prospective"]
        prospective[1]["source"] = prospective[0]["source"]
        prospective[1]["observation"] = prospective[0]["observation"]
        prospective[1]["repeat"] = prospective[0]["repeat"]

        errors = protocol._validate_definition_structure(duplicate)

        self.assertIn("prospective Cartesian coverage mismatch", errors)

    def test_prompts_separate_retention_from_task_only_resolving(self) -> None:
        task = create_experiment_definition(master_seed=777)["task"]
        observation = task["observation_order"][0]
        atomic = atomic_prediction_prompt(observation)
        task_only = task_only_prediction_prompt(observation)
        structured = structured_policy_prompt(task["observation_order"])
        opened = open_readout_prompt()

        self.assertIn("already been\nprepared", atomic)
        self.assertIn("Do not solve a new task", atomic)
        self.assertIn("Solve the task now", task_only)
        self.assertNotIn("already been prepared", task_only)
        self.assertIn("exactly one policy entry", structured)
        self.assertIn(VERIFY_TOKEN, structured)
        self.assertNotIn(task["operation_universe"][0], structured)
        self.assertIn("course of action", opened)
        for other in task["observation_order"][1:]:
            self.assertNotIn(other, atomic)

    def test_manifest_is_exactly_derived_and_detects_corruption(self) -> None:
        definition = create_experiment_definition(master_seed=123456)
        manifest = create_execution_manifest(definition)

        self.assertEqual(validate_execution_manifest(manifest, definition), [])
        self.assertTrue(manifest["source_request_bytes_identical"])
        self.assertEqual(manifest["definition_sha256"], sha256_json(definition))
        corrupted = copy.deepcopy(manifest)
        corrupted["repeat_counts"]["prospective"] = 1
        self.assertNotEqual(validate_execution_manifest(corrupted, definition), [])

    def test_validation_rejects_semantic_and_schedule_corruption(self) -> None:
        definition = create_experiment_definition(master_seed=314159)
        corrupted = copy.deepcopy(definition)
        corrupted["model"] = "gemini-3-flash-preview"
        self.assertTrue(any("model" in error for error in validate_experiment_definition(corrupted)))

        corrupted = copy.deepcopy(definition)
        corrupted["source_generation"]["requests"]["source_B"]["input"][0]["content"][0]["text"] += " changed"
        self.assertTrue(any("request bytes differ" in error for error in validate_experiment_definition(corrupted)))

        corrupted = copy.deepcopy(definition)
        corrupted["schedule"]["prospective"].pop()
        self.assertTrue(any("prospective" in error for error in validate_experiment_definition(corrupted)))


class ExecutablePlanSimulatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.task = create_experiment_definition(master_seed=112233)["task"]

    def test_every_frozen_valid_sequence_reaches_terminal_success(self) -> None:
        for observation in self.task["observation_order"]:
            for sequence in valid_success_sequences(self.task, observation):
                state = initial_simulator_state(self.task, observation)
                original = copy.deepcopy(state)
                for token in sequence:
                    if token == VERIFY_TOKEN:
                        result = apply_simulator_action(self.task, state, VERIFY_TOOL, {})
                    else:
                        result = apply_simulator_action(
                            self.task, state, APPLY_TOOL, {"operation_id": token}
                        )
                    state = result["state"]
                self.assertEqual(original["decisions"], 0)
                self.assertTrue(result["valid"])
                self.assertTrue(result["terminal"])
                self.assertTrue(result["success"])
                self.assertEqual(state["decisions"], len(sequence))
                self.assertTrue(
                    is_complete_success_sequence(self.task, observation, sequence)
                )

    def test_mismatched_second_stage_operation_is_invalid(self) -> None:
        aliases = self.task["report_aliases"]
        observation = aliases["two_ordered_operations"]
        state = initial_simulator_state(self.task, observation)
        first = apply_simulator_action(
            self.task,
            state,
            APPLY_TOOL,
            {"operation_id": aliases["open_gate_primary"]},
        )
        mismatch = apply_simulator_action(
            self.task,
            first["state"],
            APPLY_TOOL,
            {"operation_id": aliases["bind_config_alternative"]},
        )

        self.assertFalse(mismatch["valid"])
        self.assertTrue(mismatch["terminal"])
        self.assertEqual(mismatch["error"], "operation_precondition_false")

    def test_unsafe_verify_repeated_inspect_and_foreign_operation_stop(self) -> None:
        aliases = self.task["report_aliases"]
        observation = aliases["one_operation"]
        state = initial_simulator_state(self.task, observation)
        early_verify = apply_simulator_action(self.task, state, VERIFY_TOOL, {})
        self.assertEqual(early_verify["error"], "verification_before_ready")

        repeated_inspect = apply_simulator_action(
            self.task, state, "inspect_environment", {}
        )
        self.assertEqual(repeated_inspect["error"], "repeated_inspection")

        foreign = generate_opaque_id(rng=random.Random(9191))
        self.assertNotIn(foreign, self.task["operation_universe"])
        foreign_result = apply_simulator_action(
            self.task, state, APPLY_TOOL, {"operation_id": foreign}
        )
        self.assertEqual(foreign_result["error"], "foreign_operation_id")

    def test_action_normalization_and_decision_limit_are_strict(self) -> None:
        operation = self.task["operation_universe"][0]
        self.assertEqual(
            canonical_action_token(APPLY_TOOL, {"operation_id": operation}), operation
        )
        self.assertEqual(canonical_action_token(VERIFY_TOOL, {}), VERIFY_TOKEN)
        with self.assertRaises(ValueError):
            canonical_action_token(APPLY_TOOL, {"operation_id": operation, "extra": 1})

        aliases = self.task["report_aliases"]
        state = initial_simulator_state(self.task, aliases["no_operation"])
        state["decisions"] = MAX_POST_OBSERVATION_DECISIONS
        over = apply_simulator_action(self.task, state, VERIFY_TOOL, {})
        self.assertEqual(over["error"], "post_observation_decision_limit")

    def test_strict_json_normalizes_whitespace_and_rejects_noise(self) -> None:
        left = strict_json_loads('{"next": "VERIFY", "status": "known"}')
        right = strict_json_loads('{\n"status":"known","next":"VERIFY"\n}')
        self.assertEqual(canonical_json_bytes(left), canonical_json_bytes(right))
        with self.assertRaises(ValueError):
            strict_json_loads('{"status":"known","status":"unknown"}')
        with self.assertRaises(ValueError):
            strict_json_loads('{"value": NaN}')


if __name__ == "__main__":
    unittest.main()
