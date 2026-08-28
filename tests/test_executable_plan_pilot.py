from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from thoughtlab.executablePlans import executable_plan_freeze as freeze_module
from thoughtlab.executablePlans import executable_plan_pilot as pilot
from thoughtlab.executablePlans.executable_plan_protocol import (
    APPLY_TOOL,
    INSPECT_TOOL,
    MODEL,
    SOURCE_LABELS,
    VERIFY_TOKEN,
    VERIFY_TOOL,
    canonical_json_bytes,
    create_experiment_definition,
)
from thoughtlab.gemini_interactions import InteractionHttpResult


def interaction_result(payload: dict) -> InteractionHttpResult:
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return InteractionHttpResult(
        http_status=200,
        payload=payload,
        raw_body=raw.decode("utf-8"),
        transport_error="",
        response_parse_error="",
        elapsed_ms=1,
        raw_body_bytes=raw,
        response_headers={"x-request-id": "fixture"},
    )


class ScriptedInteractions:
    SOURCE_SIGNATURES = ("RAW_SOURCE_SIGNATURE_A", "RAW_SOURCE_SIGNATURE_B")

    def __init__(
        self,
        definition: dict,
        *,
        first_source_invalid: bool = False,
        premature_two_operation_for_source_a: bool = False,
    ) -> None:
        self.definition = definition
        self.first_source_invalid = first_source_invalid
        self.premature_two_operation_for_source_a = (
            premature_two_operation_for_source_a
        )
        self.bodies: list[dict] = []
        self.phases: list[str] = []
        self.source_calls = 0
        self.call_id = 0

    def _payload(self, *, status: str, steps: list[dict]) -> InteractionHttpResult:
        return interaction_result(
            {"status": status, "model": MODEL, "steps": copy.deepcopy(steps)}
        )

    def _next_call_id(self) -> str:
        self.call_id += 1
        return f"call_{self.call_id:04d}"

    @staticmethod
    def _result_values(body: dict) -> list[tuple[str, dict]]:
        values: list[tuple[str, dict]] = []
        for step in body.get("input", []):
            if step.get("type") != "function_result":
                continue
            text = step["result"][0]["text"]
            values.append((step["name"], json.loads(text)))
        return values

    @staticmethod
    def _prompt_text(body: dict) -> str:
        pieces: list[str] = []
        for step in body.get("input", []):
            if step.get("type") != "user_input":
                continue
            for block in step.get("content", []):
                if block.get("type") == "text":
                    pieces.append(block.get("text", ""))
        return "\n".join(pieces)

    def _source_for_body(self, body: dict) -> str | None:
        signatures = {
            step.get("signature")
            for step in body.get("input", [])
            if step.get("type") == "thought"
        }
        if self.SOURCE_SIGNATURES[0] in signatures:
            return SOURCE_LABELS[0]
        if self.SOURCE_SIGNATURES[1] in signatures:
            return SOURCE_LABELS[1]
        return None

    def _chosen_sequence(self, source: str, observation: str) -> list[str]:
        paths = self.definition["task"]["valid_success_sequences"][observation]
        return list(paths[0] if source == SOURCE_LABELS[0] else paths[-1])

    def _source_response(self) -> InteractionHttpResult:
        source_index = self.source_calls
        self.source_calls += 1
        if source_index == 0 and self.first_source_invalid:
            return self._payload(
                status="completed",
                steps=[
                    {
                        "type": "model_output",
                        "content": [{"type": "text", "text": "cannot inspect"}],
                    }
                ],
            )
        return self._payload(
            status="requires_action",
            steps=[
                {
                    "type": "thought",
                    "signature": self.SOURCE_SIGNATURES[source_index],
                },
                {
                    "type": "function_call",
                    "id": self._next_call_id(),
                    "name": INSPECT_TOOL,
                    "arguments": {},
                },
            ],
        )

    def _prospective_response(self, body: dict) -> InteractionHttpResult:
        self._assert_stateless_tool_history(body)
        results = self._result_values(body)
        observation = next(
            value["observation_id"]
            for name, value in results
            if name == INSPECT_TOOL
        )
        source = self._source_for_body(body)
        assert source is not None
        aliases = self.definition["task"]["report_aliases"]
        if (
            self.premature_two_operation_for_source_a
            and source == SOURCE_LABELS[0]
            and observation == aliases["two_ordered_operations"]
        ):
            name = VERIFY_TOOL
            arguments = {}
        else:
            sequence = self._chosen_sequence(source, observation)
            applied_count = sum(name == APPLY_TOOL for name, _value in results)
            token = sequence[applied_count]
            if token == VERIFY_TOKEN:
                name = VERIFY_TOOL
                arguments = {}
            else:
                name = APPLY_TOOL
                arguments = {"operation_id": token}
        return self._payload(
            status="requires_action",
            steps=[
                {
                    "type": "thought",
                    "signature": f"continuation_{self.call_id + 1}",
                },
                {
                    "type": "function_call",
                    "id": self._next_call_id(),
                    "name": name,
                    "arguments": arguments,
                },
            ],
        )

    def _assert_stateless_tool_history(self, body: dict) -> None:
        self.assert_equal(body.get("system_instruction"), self.definition["system_instruction"])
        self.assert_equal(body.get("tools"), self.definition["tools"])
        steps = body.get("input", [])
        if not steps or steps[0].get("type") != "user_input":
            raise AssertionError("stateless history did not begin with initial user input")
        cursor = 1
        while cursor < len(steps):
            if cursor + 2 >= len(steps):
                raise AssertionError("stateless tool history ended mid-response/result")
            thought, function_call, function_result = steps[cursor : cursor + 3]
            if thought.get("type") != "thought" or not thought.get("signature"):
                raise AssertionError("exact thought step was missing or reordered")
            if function_call.get("type") != "function_call":
                raise AssertionError("exact function call was missing or reordered")
            if function_result.get("type") != "function_result":
                raise AssertionError("matching function result was missing or reordered")
            if function_result.get("call_id") != function_call.get("id"):
                raise AssertionError("function result call_id did not match")
            if function_result.get("name") != function_call.get("name"):
                raise AssertionError("function result name did not match")
            cursor += 3

    @staticmethod
    def assert_equal(left, right) -> None:
        if left != right:
            raise AssertionError(f"values differ: {left!r} != {right!r}")

    def _readout_response(self, body: dict) -> InteractionHttpResult:
        schema = body.get("response_format", {}).get("schema", {})
        prompt = self._prompt_text(body)
        task = self.definition["task"]
        source = self._source_for_body(body)
        if "policies" in schema.get("properties", {}):
            assert source is not None
            answer = {
                "policies": [
                    {
                        "observation": observation,
                        "status": "known",
                        "sequence": self._chosen_sequence(source, observation),
                    }
                    for observation in task["observation_order"]
                ]
            }
            text = canonical_json_bytes(answer).decode("ascii")
        elif "status" in schema.get("properties", {}):
            observation = next(
                observation
                for observation in task["observation_order"]
                if observation in prompt
            )
            if source is not None:
                action = self._chosen_sequence(source, observation)[0]
                answer = {"status": "known", "next": action}
            elif body.get("tools"):
                action = list(task["valid_success_sequences"][observation][0])[0]
                answer = {"status": "known", "next": action}
            else:
                answer = {"status": "unknown", "next": None}
            text = canonical_json_bytes(answer).decode("ascii")
        else:
            text = (
                "Recovered a conditional relay-recovery policy."
                if source is not None
                else "The task requires inspection, recovery, and verification."
            )
        return self._payload(
            status="completed",
            steps=[
                {"type": "thought", "signature": f"readout_{self.call_id + 1}"},
                {
                    "type": "model_output",
                    "content": [{"type": "text", "text": text}],
                },
            ],
        )

    def __call__(
        self,
        *,
        api_key: str,
        body: dict,
        timeout: int,
        encoded_body: bytes,
    ) -> InteractionHttpResult:
        self.bodies.append(copy.deepcopy(body))
        self.assert_wire_body(body, encoded_body)
        has_result = any(
            step.get("type") == "function_result" for step in body.get("input", [])
        )
        if "response_format" not in body and not has_result:
            self.phases.append("source")
            return self._source_response()
        if "response_format" not in body and has_result:
            self.phases.append("prospective")
            return self._prospective_response(body)
        self.phases.append("readout")
        return self._readout_response(body)

    @staticmethod
    def assert_wire_body(body: dict, encoded_body: bytes) -> None:
        if json.loads(encoded_body.decode("utf-8")) != body:
            raise AssertionError("wire body differs from request object")


class ExecutablePlanPilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]

    def prepare(self, root: Path, *, seed: int = 80_827):
        result = freeze_module.prepare_freeze(
            repo_root=self.repo_root,
            freeze_dir=root / "reviewed_freeze",
            master_seed=seed,
        )
        definition = json.loads(
            (Path(result["freeze_dir"]) / "experiment_definition.json").read_text(
                encoding="utf-8"
            )
        )
        return result, definition

    def execute(
        self,
        root: Path,
        freeze: dict,
        transport: ScriptedInteractions,
    ) -> tuple[dict, Path]:
        output = root / "execution"
        with (
            patch.object(pilot, "execution_output_dir", return_value=output),
            patch.object(pilot, "_assert_path_has_no_link_ancestor"),
            patch.object(pilot, "_assert_execution_paths_are_ignored"),
        ):
            ledger = pilot.execute_reviewed_freeze(
                repo_root=self.repo_root,
                freeze_dir=Path(freeze["freeze_dir"]),
                expected_freeze_id=freeze["freeze_id"],
                api_key="fixture-key",
                transport=transport,
                sleeper=lambda _seconds: None,
            )
        return ledger, output

    def test_complete_topology_is_frozen_ordered_and_scored_without_composite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            freeze, definition = self.prepare(root)
            transport = ScriptedInteractions(definition)

            ledger, output = self.execute(root, freeze, transport)

            self.assertEqual(ledger["final_status"], "evidence_collection_complete")
            self.assertEqual(ledger["logical_requests"], 73)
            self.assertEqual(ledger["physical_attempts"], 73)
            self.assertTrue((output / "frozen_protocol" / "freeze.lock.json").is_file())
            self.assertTrue((output / "execution_ledger.json").is_file())

            source_bodies = [
                body for phase, body in zip(transport.phases, transport.bodies) if phase == "source"
            ]
            self.assertEqual(len(source_bodies), 2)
            self.assertEqual(
                canonical_json_bytes(source_bodies[0]),
                canonical_json_bytes(source_bodies[1]),
            )
            first_readout = transport.phases.index("readout")
            self.assertNotIn("prospective", transport.phases[first_readout:])

            task_only_bodies = [
                body
                for body in transport.bodies
                if body.get("generation_config", {}).get("tool_choice")
                == {"allowed_tools": {"mode": "none"}}
            ]
            self.assertEqual(len(task_only_bodies), 9)
            self.assertTrue(all(len(body["input"]) == 1 for body in task_only_bodies))
            # Locate the two semantic-upper requests by their frozen prompt text.
            semantic_prompt = definition["readouts"]["full_task_semantic_prompt"]
            full_task_bodies = [
                body
                for body in transport.bodies
                if semantic_prompt in ScriptedInteractions._prompt_text(body)
            ]
            self.assertEqual(len(full_task_bodies), 2)
            self.assertEqual(
                canonical_json_bytes(full_task_bodies[0]),
                canonical_json_bytes(full_task_bodies[1]),
            )

            summary_text = (output / "summary.json").read_text(encoding="utf-8")
            review_text = (output / "review.md").read_text(encoding="utf-8")
            for signature in ScriptedInteractions.SOURCE_SIGNATURES:
                self.assertNotIn(signature, summary_text)
                self.assertNotIn(signature, review_text)
            private_text = (output / "source_artifacts.private.json").read_text(
                encoding="utf-8"
            )
            self.assertIn(ScriptedInteractions.SOURCE_SIGNATURES[0], private_text)

            summary = json.loads(summary_text)
            self.assertIsNone(summary["scoring"]["composite_pass_gate"])
            layers = summary["scoring"]["evidence_layers"]
            self.assertEqual(
                layers["executable_plan"]["structured_cells_total"], 12
            )
            self.assertEqual(
                layers["executable_plan"]["structured_complete_valid_cells"], 12
            )
            distinguishing = layers["local_commitment"][
                "distinguishing_observations"
            ]
            aliases = definition["task"]["report_aliases"]
            self.assertTrue(distinguishing[aliases["one_operation"]]["distinguishing"])
            self.assertTrue(
                distinguishing[aliases["two_ordered_operations"]]["distinguishing"]
            )
            local_cells = layers["local_commitment"]["cells"]
            source_b_one = next(
                cell
                for cell in local_cells
                if cell["source"] == SOURCE_LABELS[1]
                and cell["observation"] == aliases["one_operation"]
            )
            self.assertEqual(
                source_b_one["own_carrier_vs_own_prospective"]["probability"],
                1.0,
            )
            self.assertEqual(
                source_b_one["donor_carrier_vs_own_prospective"]["probability"],
                0.0,
            )
            self.assertEqual(
                source_b_one["task_only_vs_own_prospective"]["probability"],
                0.0,
            )
            structured = layers["executable_plan"][
                "aggregate_prospective_agreement"
            ]
            self.assertEqual(
                structured["full_sequence"]["own_structured_vs_own"][
                    "probability"
                ],
                1.0,
            )
            self.assertEqual(
                structured["operation_dependency_edges"][
                    "own_structured_vs_own"
                ]["comparisons"],
                12,
            )
            self.assertEqual(
                structured["within_structured_repeat_agreement"],
                {"agreeing_cells": 6, "cells": 6},
            )

            prospective_rows = json.loads(
                (output / "prospective_results.json").read_text(encoding="utf-8")
            )
            readout_rows = json.loads(
                (output / "readout_results.json").read_text(encoding="utf-8")
            )
            # Invalid but globally known operations cannot create a
            # "distinguishing" no-op branch.
            foreign_actions = definition["task"]["operation_universe"][:2]
            no_operation = aliases["no_operation"]
            for row in prospective_rows:
                if row["observation"] == no_operation:
                    row["first_action"] = foreign_actions[
                        SOURCE_LABELS.index(row["source"])
                    ]
            rescored = pilot.score_results(
                definition=definition,
                prospective=prospective_rows,
                readouts=readout_rows,
            )
            self.assertFalse(
                rescored["evidence_layers"]["local_commitment"][
                    "distinguishing_observations"
                ][no_operation]["distinguishing"]
            )

            # One malformed structured all-outcome response contributes three
            # explicit invalid observation cells, never a denominator change.
            one_structured = next(
                row for row in readout_rows if row["arm"] == "structured"
            )
            one_structured["eligible"] = False
            one_structured["normalized"] = None
            rescored = pilot.score_results(
                definition=definition,
                prospective=json.loads(
                    (output / "prospective_results.json").read_text(encoding="utf-8")
                ),
                readouts=readout_rows,
            )
            structured_cells = rescored["evidence_layers"]["conditional_policy"][
                "structured_cells"
            ]
            self.assertEqual(len(structured_cells), 12)
            self.assertEqual(
                sum(cell["semantic_class"] == pilot.INVALID_READOUT for cell in structured_cells),
                3,
            )

    def test_first_source_ineligible_stops_without_replacement_or_measurement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            freeze, definition = self.prepare(root, seed=80_828)
            transport = ScriptedInteractions(definition, first_source_invalid=True)

            ledger, output = self.execute(root, freeze, transport)

            self.assertEqual(ledger["final_status"], "source_generation_ineligible")
            self.assertEqual(ledger["logical_requests"], 1)
            self.assertEqual(transport.phases, ["source"])
            self.assertFalse((output / "prospective_results.json").exists())
            self.assertFalse((output / "readout_results.json").exists())
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["generation"]["source_calls_completed"], 1)
            self.assertFalse(summary["generation"]["replacement_generation_permitted"])

    def test_task_stop_rule_retains_premature_verify_and_still_finishes_readouts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            freeze, definition = self.prepare(root, seed=80_829)
            transport = ScriptedInteractions(
                definition,
                premature_two_operation_for_source_a=True,
            )

            ledger, output = self.execute(root, freeze, transport)

            self.assertEqual(ledger["final_status"], "evidence_collection_complete")
            aliases = definition["task"]["report_aliases"]
            rows = json.loads(
                (output / "prospective_results.json").read_text(encoding="utf-8")
            )
            stopped = [
                row
                for row in rows
                if row["source"] == SOURCE_LABELS[0]
                and row["observation"] == aliases["two_ordered_operations"]
            ]
            self.assertEqual(len(stopped), 3)
            self.assertTrue(all(row["decision_count"] == 1 for row in stopped))
            self.assertTrue(
                all(row["terminal_reason"] == "verification_before_ready" for row in stopped)
            )
            self.assertTrue((output / "readout_results.json").is_file())
            self.assertEqual(len(json.loads((output / "readout_results.json").read_text())), 35)

    def test_normalizers_retain_semantically_wrong_strings_and_reject_noise_safely(self):
        definition = create_experiment_definition(master_seed=9_311)
        task = definition["task"]
        atomic, errors = pilot.normalize_atomic_answer(
            '{"status":"known","next":"FOREIGN_ACTION"}', task
        )
        self.assertEqual(errors, [])
        self.assertEqual(atomic["next"], "FOREIGN_ACTION")
        malformed, errors = pilot.normalize_atomic_answer(
            '{"status":[],"next":{}}', task
        )
        self.assertIsNone(malformed)
        self.assertTrue(errors)
        duplicate, errors = pilot.normalize_atomic_answer(
            '{"status":"unknown","status":"known","next":null}', task
        )
        self.assertIsNone(duplicate)
        self.assertTrue(errors)

        observations = task["observation_order"]
        answer = {
            "policies": [
                {
                    "observation": observations[0],
                    "status": "known",
                    "sequence": ["FOREIGN_ACTION"],
                },
                {
                    "observation": observations[1],
                    "status": "partial",
                    "sequence": ["ALSO_FOREIGN"],
                },
                {
                    "observation": observations[2],
                    "status": "unknown",
                    "sequence": [],
                },
            ]
        }
        normalized, errors = pilot.normalize_structured_answer(
            json.dumps(answer), task
        )
        self.assertEqual(errors, [])
        self.assertIsNotNone(normalized)
        answer["policies"][0]["observation"] = []
        malformed, errors = pilot.normalize_structured_answer(json.dumps(answer), task)
        self.assertIsNone(malformed)
        self.assertTrue(errors)
        answer["policies"][0]["observation"] = observations[0]
        answer["policies"][0]["sequence"] = ["x", "y", "z", "too-many"]
        malformed, errors = pilot.normalize_structured_answer(json.dumps(answer), task)
        self.assertIsNone(malformed)
        self.assertTrue(errors)

    def test_invalid_freeze_is_rejected_before_consumption_or_transport(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            freeze, definition = self.prepare(root, seed=80_830)
            manifest_path = Path(freeze["freeze_dir"]) / "manifest.json"
            manifest_path.write_bytes(manifest_path.read_bytes() + b"\n")
            transport = ScriptedInteractions(definition)
            output = root / "must_not_exist"
            with (
                patch.object(pilot, "execution_output_dir", return_value=output),
                patch.object(pilot, "_assert_path_has_no_link_ancestor"),
                patch.object(pilot, "_assert_execution_paths_are_ignored"),
                self.assertRaises(ValueError),
            ):
                pilot.execute_reviewed_freeze(
                    repo_root=self.repo_root,
                    freeze_dir=Path(freeze["freeze_dir"]),
                    expected_freeze_id=freeze["freeze_id"],
                    api_key="fixture-key",
                    transport=transport,
                    sleeper=lambda _seconds: None,
                )
            self.assertEqual(transport.bodies, [])
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
