import copy
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import thoughtlab.stateTransitions.planning_transition_freeze as freeze_module
import thoughtlab.stateTransitions.planning_transition_pilot as pilot_module
import thoughtlab.stateTransitions.fork_pilot as fork_pilot_module
import thoughtlab.gemini_interactions as interactions_module
from thoughtlab.gemini_interactions import InteractionHttpResult, post_interaction
from thoughtlab.stateTransitions.fork_pilot import CallStore
from thoughtlab.stateTransitions.planning_transition_freeze import (
    SAFE_FREEZE_FILES,
    prepare_freeze,
    verify_freeze,
)
from thoughtlab.stateTransitions.planning_transition_pilot import (
    ProbeObservation,
    _checkpoint_eligibility,
    _parse_probe_result,
    _timeline_diagnostics,
    arm_steps,
    derive_delta_rows,
    execution_output_dir,
    execute_reviewed_freeze,
    generate_trial,
    generation_status,
    summarize_results,
)
from thoughtlab.stateTransitions.planning_transition_probes import (
    ACK_RESPONSE_FORMAT,
    PROBES,
)
from thoughtlab.stateTransitions.planning_transition_protocol import (
    ARMS,
    CHECKPOINTS,
    CONTROL_ARMS,
    DELTA_ARMS,
    FIELDS,
    MODEL,
    PROMPT_FIREWALL_TERMS,
    create_manifest,
    load_and_validate_experiment_definition,
    validate_manifest,
)
from thoughtlab.stateTransitions.planning_transition_score import (
    derive_delta,
    empty_shape,
    expected_normalized,
    score_planning_answer,
    validate_planning_answer,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


class CanonicalExecutionCleanup:
    def __init__(self, path):
        self.path = Path(path)

    def cleanup(self):
        private_root = (
            REPO_ROOT / "results" / "planning_transition" / "executions"
        ).resolve()
        resolved = self.path.resolve()
        if (
            resolved.parent != private_root
            or re.fullmatch(r"[0-9a-f]{64}", resolved.name) is None
        ):
            raise AssertionError(f"refusing unsafe test cleanup: {resolved}")
        if resolved.exists():
            shutil.rmtree(resolved)


def interaction_response(text, index, *, model=MODEL, status="completed"):
    payload = {
        "status": status,
        "model": model,
        "steps": [
            {
                "type": "thought",
                "signature": f"private-signature-{index}",
                "summary": [],
            },
            {
                "type": "model_output",
                "content": [{"type": "text", "text": text}],
            },
        ],
    }
    return InteractionHttpResult(
        http_status=200,
        payload=payload,
        raw_body=json.dumps(payload),
        raw_body_bytes=json.dumps(payload).encode("utf-8"),
        transport_error="",
        response_parse_error="",
        elapsed_ms=1,
    )


def ack_response(index):
    return interaction_response('{"ack":true}', index)


def pretty_ack_response(index):
    return interaction_response('{\n  "ack": true\n}', index)


def unknown_answer(field):
    kind = PROBES[field]["kind"]
    if kind == "viability":
        return {
            "knowledge": "unknown",
            "viable_ids": [],
            "nonviable_ids": [],
        }
    key = "ids_high_to_low" if kind == "ranking" else "ids"
    return {"knowledge": "unknown", key: []}


class FakeHttpResponse:
    def __init__(self, raw_body, *, status=200, read_error=None):
        self.raw_body = raw_body
        self.status = status
        self.headers = {}
        self.read_error = read_error

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        if self.read_error is not None:
            raise self.read_error
        return self.raw_body


def perfect_responses(run_attempt, *, first_probe_text=None, start_index=0):
    responses = []
    index = start_index
    for _trial_name in run_attempt["generation_trial_order"]:
        for _checkpoint in CHECKPOINTS:
            responses.append(ack_response(index))
            index += 1
    target = run_attempt["trials"]["target"]
    donor = run_attempt["trials"]["donor"]
    for probe_index, task in enumerate(run_attempt["probe_tasks"]):
        if probe_index == 0 and first_probe_text is not None:
            text = first_probe_text
        elif task["arm"] in CONTROL_ARMS:
            text = json.dumps(unknown_answer(task["field"]), separators=(",", ":"))
        else:
            source = donor if task["arm"] in {"wrong_trial_latest", "donor_full_prefix"} else target
            answer = source["truth"][task["checkpoint"]][task["field"]]
            text = json.dumps(answer, separators=(",", ":"))
        responses.append(interaction_response(text, index))
        index += 1
    return responses


class ProtocolManifestTests(unittest.TestCase):
    def test_definition_and_manifest_are_exact_and_deterministic(self):
        definition = load_and_validate_experiment_definition(REPO_ROOT)
        self.assertEqual(definition["model"], MODEL)
        left = create_manifest(master_seed=77231)
        right = create_manifest(master_seed=77231)
        self.assertEqual(left, right)
        self.assertEqual(validate_manifest(left), [])
        self.assertEqual(len(left["planned_run_attempts"]), 2)

    def test_truth_ids_matrix_and_budgets_match_the_protocol(self):
        manifest = create_manifest(master_seed=99119)
        all_ids = []
        expected_truth_aliases = {
            "S0": (set(), [], set(), set(), set()),
            "S1": ({"A", "B", "C"}, ["A", "B", "C"], {"A", "B", "C"}, set(), set()),
            "S2": ({"A", "B", "C"}, ["B", "A", "C"], {"A", "B", "C"}, set(), set()),
            "S3": ({"A", "B"}, ["B", "A"], {"A", "B"}, set(), set()),
            "S4": ({"A", "B", "D"}, ["B", "A", "D"], {"A", "B", "D"}, set(), set()),
            "S5": ({"A", "B", "D"}, ["B", "A", "D"], {"A", "D"}, {"B"}, set()),
            "S6": ({"A", "B", "D"}, ["B", "A", "D"], {"A", "D"}, {"B"}, {"A"}),
        }
        for run in manifest["planned_run_attempts"]:
            self.assertEqual(len(run["probe_tasks"]), 196)
            self.assertEqual(len(run["generation_tasks"]), 14)
            self.assertEqual(
                len({(task["checkpoint"], task["field"], task["arm"]) for task in run["probe_tasks"]}),
                196,
            )
            self.assertEqual(
                {task["request_order"] for task in run["probe_tasks"]},
                set(range(1, 197)),
            )
            for trial in run["trials"].values():
                aliases = trial["report_aliases"]
                reverse = {identifier: alias for alias, identifier in aliases.items()}
                all_ids.extend(trial["id_universe"])
                for identifier in trial["id_universe"]:
                    self.assertRegex(identifier, r"^ID_[0-9A-HJKMNP-TV-Z]{26}$")
                    self.assertNotRegex(identifier, r"PLAN|CANDIDATE|CONDITION")
                for checkpoint, expected in expected_truth_aliases.items():
                    truth = trial["truth"][checkpoint]
                    registry = {reverse[value] for value in truth["candidate_registry"]["ids"]}
                    ranking = [reverse[value] for value in truth["utility_ranking"]["ids_high_to_low"]]
                    viable = {reverse[value] for value in truth["viability_partition"]["viable_ids"]}
                    nonviable = {reverse[value] for value in truth["viability_partition"]["nonviable_ids"]}
                    selected = {reverse[value] for value in truth["selected_candidate"]["ids"]}
                    self.assertEqual((registry, ranking, viable, nonviable, selected), expected)
            target = run["trials"]["target"]
            donor = run["trials"]["donor"]
            discriminating = sum(
                target["truth"][checkpoint][field] != donor["truth"][checkpoint][field]
                for checkpoint in CHECKPOINTS
                for field in FIELDS
            )
            self.assertEqual(discriminating, 19)
        self.assertEqual(len(all_ids), len(set(all_ids)))
        self.assertEqual(manifest["planned_calls"]["per_complete_run"]["logical_total"], 210)
        self.assertEqual(manifest["planned_calls"]["two_run_stopping_ceiling"]["logical_total"], 224)

    def test_prompts_are_native_delta_only_and_role_neutral(self):
        manifest = create_manifest(master_seed=4201)
        for run in manifest["planned_run_attempts"]:
            for trial in run["trials"].values():
                prompts = trial["prompts"]
                combined = "\n".join(prompts.values())
                for phrase in PROMPT_FIREWALL_TERMS:
                    self.assertNotIn(phrase.lower(), combined.lower())
                self.assertIsNone(re.search(r"(?<![A-Za-z0-9_])[ABCD](?![A-Za-z0-9_])", combined))
                aliases = trial["report_aliases"]
                self.assertIn(aliases["B"], prompts["S2"])
                self.assertNotIn(aliases["A"], prompts["S2"])
                self.assertNotIn(aliases["C"], prompts["S2"])
                self.assertIn(aliases["C"], prompts["S3"])
                self.assertIn(aliases["D"], prompts["S4"])
                self.assertIn(aliases["K"], prompts["S5"])
                self.assertIn(aliases["B"], prompts["S5"])
                self.assertNotIn(aliases["A"], prompts["S6"])
                self.assertNotIn(aliases["B"], prompts["S6"])
                self.assertNotIn(aliases["D"], prompts["S6"])
        probe_text = "\n".join(spec["prompt"] for spec in PROBES.values())
        for phrase in PROMPT_FIREWALL_TERMS:
            self.assertNotIn(phrase.lower(), probe_text.lower())

    def test_manifest_validation_rejects_truth_and_matrix_corruption(self):
        manifest = create_manifest(master_seed=1234)
        manifest["planned_run_attempts"][0]["probe_tasks"].pop()
        errors = validate_manifest(manifest)
        self.assertTrue(any("tomography" in error for error in errors))
        self.assertTrue(any("deterministic" in error for error in errors))


class TransportDecodeTests(unittest.TestCase):
    def call(self):
        return post_interaction(
            api_key="not-persisted",
            body={"x": 1},
            timeout=1,
        )

    def test_oversized_integer_2xx_preserves_raw_response_bytes(self):
        raw_body = b'{"n":' + (b"9" * 5000) + b"}"
        with patch.object(
            interactions_module.urllib.request,
            "urlopen",
            return_value=FakeHttpResponse(raw_body),
        ):
            result = self.call()
        self.assertEqual(result.http_status, 200)
        self.assertIsNone(result.payload)
        self.assertTrue(result.response_parse_error)
        self.assertEqual(result.raw_body_bytes, raw_body)
        self.assertEqual(result.raw_body, raw_body.decode("utf-8"))
        self.assertFalse(result.transport_error)

    def test_recursive_http_error_preserves_raw_response_bytes(self):
        raw_body = (b"[" * 2000) + b"0" + (b"]" * 2000)
        error = urllib.error.HTTPError(
            "https://example.invalid",
            500,
            "synthetic",
            {},
            io.BytesIO(raw_body),
        )
        with patch.object(
            interactions_module.urllib.request,
            "urlopen",
            side_effect=error,
        ):
            result = self.call()
        self.assertEqual(result.http_status, 500)
        self.assertIsNone(result.payload)
        self.assertTrue(result.response_parse_error)
        self.assertEqual(result.raw_body_bytes, raw_body)
        self.assertEqual(result.raw_body, raw_body.decode("utf-8"))
        self.assertFalse(result.transport_error)

    def test_incomplete_2xx_read_preserves_partial_bytes_as_retryable(self):
        partial = b'{"status":"completed"'
        incomplete = interactions_module.http.client.IncompleteRead(
            partial,
            100,
        )
        response = FakeHttpResponse(
            b"",
            read_error=incomplete,
        )
        with patch.object(
            interactions_module.urllib.request,
            "urlopen",
            return_value=response,
        ):
            result = self.call()
        self.assertEqual(result.http_status, 200)
        self.assertIsNone(result.payload)
        self.assertEqual(result.raw_body_bytes, partial)
        self.assertEqual(result.raw_body, partial.decode("utf-8"))
        self.assertIn("IncompleteRead", result.transport_error)
        self.assertFalse(result.response_parse_error)

    def test_incomplete_http_error_read_preserves_partial_bytes_as_retryable(self):
        partial = b'{"error":{"message":"partial"}'
        error = urllib.error.HTTPError(
            "https://example.invalid",
            503,
            "synthetic",
            {},
            io.BytesIO(b"unused"),
        )

        def incomplete_read():
            raise interactions_module.http.client.IncompleteRead(partial, 100)

        error.read = incomplete_read
        with patch.object(
            interactions_module.urllib.request,
            "urlopen",
            side_effect=error,
        ):
            result = self.call()
        self.assertEqual(result.http_status, 503)
        self.assertIsNone(result.payload)
        self.assertEqual(result.raw_body_bytes, partial)
        self.assertEqual(result.raw_body, partial.decode("utf-8"))
        self.assertIn("IncompleteRead", result.transport_error)
        self.assertFalse(result.response_parse_error)


class FreezeContractTests(unittest.TestCase):
    def test_prepare_is_deterministic_allowlisted_and_transport_free(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            with patch("urllib.request.urlopen") as urlopen:
                left = prepare_freeze(
                    repo_root=REPO_ROOT,
                    freeze_dir=Path(first),
                    master_seed=818181,
                )
                right = prepare_freeze(
                    repo_root=REPO_ROOT,
                    freeze_dir=Path(second),
                    master_seed=818181,
                )
            urlopen.assert_not_called()
            self.assertEqual(left["freeze_id"], right["freeze_id"])
            self.assertEqual(
                sorted(path.name for path in Path(first).iterdir()),
                sorted(SAFE_FREEZE_FILES),
            )
            for name in SAFE_FREEZE_FILES:
                self.assertEqual((Path(first) / name).read_bytes(), (Path(second) / name).read_bytes())
            validation = json.loads((Path(first) / "validation_report.json").read_text())
            self.assertFalse(validation["preparation_transport_path_present"])
            self.assertFalse(validation["preparation_credential_access_path_present"])
            self.assertEqual(
                validation["hashed_no_call_regression_source"],
                "tests/test_planning_transition_pilot.py",
            )
            self.assertFalse((Path(first) / "raw").exists())

    def test_git_attestation_never_enumerates_or_reads_credential_environment(self):
        allowed_values = {
            key: os.environ.get(key)
            for key in (
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
        }

        class GuardedEnvironment:
            def get(self, key, default=None):
                if any(
                    marker in key.upper()
                    for marker in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
                ):
                    raise AssertionError(f"credential variable read: {key}")
                return allowed_values.get(key, default)

            def items(self):
                raise AssertionError("environment enumeration is forbidden")

        completed = [
            SimpleNamespace(stdout="deadbeef\n"),
            SimpleNamespace(stdout=""),
        ]
        with patch.object(freeze_module.os, "environ", GuardedEnvironment()), patch.object(
            freeze_module.subprocess,
            "run",
            side_effect=completed,
        ) as run:
            snapshot = freeze_module._git_snapshot(REPO_ROOT)
        self.assertEqual(snapshot["commit"], "deadbeef")
        self.assertEqual(run.call_count, 2)

    def test_verify_detects_exact_file_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            prepared = prepare_freeze(
                repo_root=REPO_ROOT,
                freeze_dir=Path(temporary),
                master_seed=919191,
            )
            manifest_path = Path(temporary) / "manifest.json"
            manifest_path.write_bytes(manifest_path.read_bytes() + b" ")
            verification = verify_freeze(
                repo_root=REPO_ROOT,
                freeze_dir=Path(temporary),
                expected_freeze_id=prepared["freeze_id"],
            )
            self.assertFalse(verification["valid"])
            self.assertTrue(any("file-byte hash" in error for error in verification["errors"]))

    def test_prepare_refuses_nonempty_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            Path(temporary, "existing.txt").write_text("occupied", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                prepare_freeze(
                    repo_root=REPO_ROOT,
                    freeze_dir=Path(temporary),
                    master_seed=1,
                )

    def test_verify_rejects_null_trial_without_crashing(self):
        with tempfile.TemporaryDirectory() as temporary:
            prepared = prepare_freeze(
                repo_root=REPO_ROOT,
                freeze_dir=Path(temporary),
                master_seed=333,
            )
            manifest_path = Path(temporary) / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["planned_run_attempts"][0]["trials"]["target"] = None
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            verification = verify_freeze(
                repo_root=REPO_ROOT,
                freeze_dir=Path(temporary),
                expected_freeze_id=prepared["freeze_id"],
            )
            self.assertFalse(verification["valid"])
            self.assertTrue(verification["errors"])


class PlanningScoreTests(unittest.TestCase):
    def setUp(self):
        self.trial = create_manifest(master_seed=55)["planned_run_attempts"][0]["trials"]["target"]

    def score(self, field, checkpoint, answer):
        normalized = validate_planning_answer(PROBES[field]["kind"], answer)
        return normalized, score_planning_answer(
            kind=PROBES[field]["kind"],
            normalized=normalized,
            expected=self.trial["truth"][checkpoint][field],
            candidate_universe=set(self.trial["truth"][checkpoint]["candidate_registry"]["ids"]),
            source_id_universe=set(self.trial["id_universe"]),
            condition_id=self.trial["condition_id"],
        )

    def test_known_empty_is_exact_and_unknown_empty_is_not(self):
        expected = self.trial["truth"]["S0"]["selected_candidate"]
        normalized, score = self.score("selected_candidate", "S0", expected)
        self.assertTrue(score["exact"])
        self.assertFalse(empty_shape("id_set", normalized))
        unknown = validate_planning_answer("id_set", {"knowledge": "unknown", "ids": []})
        unknown_score = score_planning_answer(
            kind="id_set",
            normalized=unknown,
            expected=expected,
            candidate_universe=set(),
            source_id_universe=set(self.trial["id_universe"]),
            condition_id=self.trial["condition_id"],
        )
        self.assertFalse(unknown_score["exact"])
        self.assertTrue(empty_shape("id_set", unknown))

    def test_viability_requires_duplicate_free_disjoint_exact_union(self):
        truth = self.trial["truth"]["S5"]["viability_partition"]
        normalized, score = self.score("viability_partition", "S5", truth)
        self.assertTrue(normalized["schema_valid"])
        self.assertTrue(score["exact"])
        candidate = truth["viable_ids"][0]
        broken = copy.deepcopy(truth)
        broken["nonviable_ids"].append(candidate)
        _, broken_score = self.score("viability_partition", "S5", broken)
        self.assertFalse(broken_score["exact"])
        self.assertIn("viability arrays overlap", broken_score["truth_shape_errors"])

    def test_condition_noncanonical_duplicates_and_null_never_score(self):
        condition = self.trial["condition_id"]
        answer = {"knowledge": "known", "ids": [condition, condition, "SECRET_SENTINEL"]}
        _, score = self.score("candidate_registry", "S5", answer)
        self.assertFalse(score["exact"])
        self.assertEqual(score["role_inappropriate_ids"], [condition])
        self.assertTrue(score["duplicate_canonical_ids"])
        self.assertTrue(score["noncanonical_value_sha256"])
        self.assertNotIn("SECRET_SENTINEL", json.dumps(score))
        for value in (None, [], "null", {"knowledge": "known", "ids": None}):
            with self.subTest(value=value):
                normalized = validate_planning_answer("id_set", value)
                result = score_planning_answer(
                    kind="id_set",
                    normalized=normalized,
                    expected=self.trial["truth"]["S0"]["candidate_registry"],
                    candidate_universe=set(),
                    source_id_universe=set(self.trial["id_universe"]),
                    condition_id=condition,
                )
                self.assertFalse(result["exact"])

    def test_unknown_canonical_ids_are_hashed_and_never_emitted(self):
        unknown_id = "ID_" + "7" * 26
        answer = {
            "knowledge": "known",
            "ids": [unknown_id, unknown_id],
        }
        _, score = self.score("candidate_registry", "S1", answer)
        serialized_score = json.dumps(score)
        expected_hash = hashlib.sha256(unknown_id.encode("utf-8")).hexdigest()
        self.assertNotIn(unknown_id, serialized_score)
        self.assertIn(expected_hash, score["unknown_canonical_value_sha256"])
        self.assertIn(
            expected_hash,
            score["duplicate_unknown_canonical_value_sha256"],
        )

        observation = _parse_probe_result(
            result=interaction_response(json.dumps(answer), 1),
            kind="id_set",
            prescribed_ids=set(),
        )
        serialized_metadata = json.dumps(observation.safe_metadata)
        self.assertNotIn(unknown_id, serialized_metadata)
        self.assertIn(expected_hash, serialized_metadata)

    def test_unicode_escaped_prescribed_id_is_recovered_from_parsed_json(self):
        candidate = self.trial["report_aliases"]["A"]
        escaped = candidate.replace("I", r"\u0049", 1)
        text = f'{{"knowledge":"known","ids":["{escaped}"]}}'
        observation = _parse_probe_result(
            result=interaction_response(text, 1),
            kind="id_set",
            prescribed_ids={candidate},
        )
        self.assertEqual(
            observation.safe_metadata["raw_prescribed_id_tokens"],
            [candidate],
        )
        self.assertEqual(
            observation.safe_metadata["parsed_prescribed_id_tokens"],
            [candidate],
        )

    def _summary_for_observation(self, observation, *, checkpoint="S3"):
        row = {
            "checkpoint": checkpoint,
            "field": "candidate_registry",
            "arm": "target_latest_thought",
            "carrier_source_trial": "target",
            "score_source": None,
            "timeline": None,
            **observation.safe_metadata,
        }
        return summarize_results(
            run_attempt=create_manifest(master_seed=55)["planned_run_attempts"][0],
            generation={"eligible": False},
            checkpoint_summaries=[],
            rows=[row],
            observations={},
            delta_rows=[],
        )

    def test_invalid_json_unicode_escape_still_gates_premature_id(self):
        future = self.trial["report_aliases"]["D"]
        escaped = future.replace("I", r"\u0049", 1)
        observation = _parse_probe_result(
            result=interaction_response(f'not-json "{escaped}"', 1),
            kind="id_set",
            prescribed_ids=set(self.trial["id_universe"]),
        )
        self.assertEqual(observation.safe_metadata["outcome"], "invalid_json")
        self.assertIn(
            future,
            observation.safe_metadata["response_wire_prescribed_id_tokens"],
        )
        summary = self._summary_for_observation(observation)
        self.assertGreater(summary["premature_ids"], 0)
        self.assertFalse(summary["latest_positive_exploratory_observation"])

    def test_malformed_steps_container_cannot_hide_wire_premature_id(self):
        future = self.trial["report_aliases"]["D"]
        payload = {
            "status": "completed",
            "model": MODEL,
            "steps": {"malformed_future_id": future},
        }
        raw_body = json.dumps(payload, separators=(",", ":"))
        observation = _parse_probe_result(
            result=InteractionHttpResult(
                http_status=200,
                payload=payload,
                raw_body=raw_body,
                raw_body_bytes=raw_body.encode("utf-8"),
                transport_error="",
                response_parse_error="",
                elapsed_ms=1,
            ),
            kind="id_set",
            prescribed_ids=set(self.trial["id_universe"]),
        )
        self.assertEqual(
            observation.safe_metadata["outcome"],
            "response_shape_error",
        )
        self.assertIn(
            future,
            observation.safe_metadata["response_wire_prescribed_id_tokens"],
        )
        summary = self._summary_for_observation(observation)
        self.assertGreater(summary["premature_ids"], 0)
        self.assertFalse(summary["latest_positive_exploratory_observation"])

    def test_duplicate_key_unicode_escape_still_gates_premature_id(self):
        future = self.trial["report_aliases"]["D"]
        escaped = future.replace("I", r"\u0049", 1)
        text = (
            '{"knowledge":"known","ids":[],"ids":["'
            + escaped
            + '"]}'
        )
        observation = _parse_probe_result(
            result=interaction_response(text, 1),
            kind="id_set",
            prescribed_ids=set(self.trial["id_universe"]),
        )
        self.assertEqual(
            observation.safe_metadata["outcome"],
            "duplicate_json_key",
        )
        self.assertIn(
            future,
            observation.safe_metadata["parsed_prescribed_id_tokens"],
        )
        summary = self._summary_for_observation(observation)
        self.assertGreater(summary["premature_ids"], 0)
        self.assertFalse(summary["latest_positive_exploratory_observation"])

    def test_nonobject_step_cannot_hide_premature_id_in_valid_output_step(self):
        future = self.trial["report_aliases"]["D"]
        text = json.dumps({"knowledge": "known", "ids": [future]})
        payload = {
            "status": "completed",
            "model": MODEL,
            "steps": [
                None,
                {
                    "type": "model_output",
                    "content": [{"type": "text", "text": text}],
                },
            ],
        }
        observation = _parse_probe_result(
            result=InteractionHttpResult(
                http_status=200,
                payload=payload,
                raw_body=json.dumps(payload),
                raw_body_bytes=json.dumps(payload).encode("utf-8"),
                transport_error="",
                response_parse_error="",
                elapsed_ms=1,
            ),
            kind="id_set",
            prescribed_ids=set(self.trial["id_universe"]),
        )
        self.assertEqual(
            observation.safe_metadata["outcome"],
            "response_shape_error",
        )
        self.assertIn(
            future,
            observation.safe_metadata["raw_prescribed_id_tokens"],
        )
        summary = self._summary_for_observation(observation)
        self.assertGreater(summary["premature_ids"], 0)
        self.assertFalse(summary["latest_positive_exploratory_observation"])

    def test_outer_response_parse_error_cannot_hide_premature_id(self):
        future = self.trial["report_aliases"]["D"]
        escaped = future.replace("I", r"\u0049", 1)
        raw_body = f'outer-json-failure "{escaped}"'
        observation = _parse_probe_result(
            result=InteractionHttpResult(
                http_status=200,
                payload=None,
                raw_body=raw_body,
                raw_body_bytes=raw_body.encode("utf-8"),
                transport_error="",
                response_parse_error="JSONDecodeError",
                elapsed_ms=1,
            ),
            kind="id_set",
            prescribed_ids=set(self.trial["id_universe"]),
        )
        self.assertEqual(
            observation.safe_metadata["outcome"],
            "response_parse_error",
        )
        self.assertIn(
            future,
            observation.safe_metadata["response_wire_prescribed_id_tokens"],
        )
        summary = self._summary_for_observation(observation)
        self.assertGreater(summary["premature_ids"], 0)
        self.assertFalse(summary["latest_positive_exploratory_observation"])

    def test_schema_invalid_noncanonical_collection_enters_anomaly_gate(self):
        sentinel = "NOT_AN_OPAQUE_ID"
        observation = _parse_probe_result(
            result=interaction_response(
                json.dumps(
                    {"knowledge": "known", "ids": [sentinel, 5]},
                    separators=(",", ":"),
                ),
                1,
            ),
            kind="id_set",
            prescribed_ids=set(self.trial["id_universe"]),
        )
        self.assertEqual(observation.safe_metadata["outcome"], "schema_invalid")
        self.assertNotIn(sentinel, json.dumps(observation.safe_metadata))
        self.assertIn(
            hashlib.sha256(sentinel.encode("utf-8")).hexdigest(),
            observation.safe_metadata[
                "parsed_collection_noncanonical_value_sha256"
            ],
        )
        summary = self._summary_for_observation(observation, checkpoint="S1")
        self.assertGreater(summary["source_anomalies"]["noncanonical_values"], 0)
        self.assertFalse(summary["latest_positive_exploratory_observation"])

    def test_oversized_integer_probe_answer_is_invalid_not_an_exception(self):
        future = self.trial["report_aliases"]["D"]
        text = (
            '{"knowledge":"known","ids":["'
            + future
            + '"],"oversized":'
            + ("9" * 5000)
            + "}"
        )
        observation = _parse_probe_result(
            result=interaction_response(text, 1),
            kind="id_set",
            prescribed_ids=set(self.trial["id_universe"]),
        )
        self.assertEqual(observation.safe_metadata["outcome"], "invalid_json")
        self.assertIn(
            future,
            observation.safe_metadata["raw_prescribed_id_tokens"],
        )
        summary = self._summary_for_observation(observation)
        self.assertGreater(summary["premature_ids"], 0)
        self.assertFalse(summary["latest_positive_exploratory_observation"])

    def test_oversized_integer_ack_marks_generation_ineligible(self):
        visible = '{"ack":true,"oversized":' + ("9" * 5000) + "}"
        result = interaction_response(visible, 1)
        reasons, details = _checkpoint_eligibility(
            result=result,
            payload=result.payload,
            steps=result.payload["steps"],
            request_body={
                "store": False,
                "stream": False,
                "background": False,
            },
            trial=self.trial,
        )
        self.assertIn(
            "visible output did not canonically match the required acknowledgement object",
            reasons,
        )
        self.assertFalse(details["visible_ack_json_parse_valid"])
        self.assertFalse(details["visible_ack_canonical_match"])

    def test_ack_eligibility_compares_canonical_json_both_ways(self):
        request_body = {
            "store": False,
            "stream": False,
            "background": False,
        }
        pretty = interaction_response('{\n  "ack": true\n}', 1)
        reasons, details = _checkpoint_eligibility(
            result=pretty,
            payload=pretty.payload,
            steps=pretty.payload["steps"],
            request_body=request_body,
            trial=self.trial,
        )
        self.assertEqual(reasons, [])
        self.assertTrue(details["visible_ack_json_parse_valid"])
        self.assertTrue(details["visible_ack_canonical_match"])
        self.assertFalse(
            details["visible_ack_post_extraction_text_exact"]
        )
        self.assertEqual(
            details["visible_ack_canonical_sha256"],
            details["expected_ack_canonical_sha256"],
        )

        escaped_key = interaction_response(r'{"\u0061ck":true}', 2)
        escaped_reasons, escaped_details = _checkpoint_eligibility(
            result=escaped_key,
            payload=escaped_key.payload,
            steps=escaped_key.payload["steps"],
            request_body=request_body,
            trial=self.trial,
        )
        self.assertEqual(escaped_reasons, [])
        self.assertTrue(escaped_details["visible_ack_canonical_match"])
        self.assertFalse(
            escaped_details["visible_ack_post_extraction_text_exact"]
        )

        for text in (
            '{"ack":1}',
            '{"ack":false}',
            '{"ack":true,"extra":null}',
            '{"ack":true,"ack":true}',
            "null",
            '{"ack":NaN}',
            '{"ack":1e999}',
            '{"ack":-1e999}',
        ):
            with self.subTest(text=text):
                result = interaction_response(text, 2)
                invalid_reasons, invalid_details = _checkpoint_eligibility(
                    result=result,
                    payload=result.payload,
                    steps=result.payload["steps"],
                    request_body=request_body,
                    trial=self.trial,
                )
                self.assertIn(
                    "visible output did not canonically match the required acknowledgement object",
                    invalid_reasons,
                )
                self.assertFalse(invalid_details["visible_ack_canonical_match"])

    def test_delta_derivation_distinguishes_changed_and_stable(self):
        before = expected_normalized("ranking", self.trial["truth"]["S1"]["utility_ranking"])
        after = expected_normalized("ranking", self.trial["truth"]["S2"]["utility_ranking"])
        changed = derive_delta("ranking", before, after)
        self.assertFalse(changed["stable"])
        self.assertEqual(len(changed["pairwise_reversals"]), 1)
        stable = derive_delta("ranking", after, after)
        self.assertTrue(stable["stable"])

    def test_timeline_future_and_premature_diagnostics_are_narrow(self):
        donor = create_manifest(master_seed=55)["planned_run_attempts"][0]["trials"]["donor"]
        future = self.trial["truth"]["S4"]["candidate_registry"]
        normalized = validate_planning_answer("id_set", future)
        diagnostics = _timeline_diagnostics(
            field="candidate_registry",
            checkpoint="S3",
            normalized=normalized,
            trial=self.trial,
            other_trial=donor,
            current_exact=False,
        )
        self.assertIn("S4", diagnostics["future_exact_hits"])
        self.assertEqual(diagnostics["premature_ids"], [self.trial["report_aliases"]["D"]])
        current = validate_planning_answer(
            "id_set", self.trial["truth"]["S3"]["candidate_registry"]
        )
        current_diag = _timeline_diagnostics(
            field="candidate_registry",
            checkpoint="S3",
            normalized=current,
            trial=self.trial,
            other_trial=donor,
            current_exact=True,
        )
        self.assertEqual(current_diag["future_exact_hits"], [])


class GenerationAndPrivacyTests(unittest.TestCase):
    def test_atomic_replace_retries_transient_windows_permission_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "artifact.bin"
            original_replace = fork_pilot_module.os.replace
            attempts = 0

            def flaky_replace(source, destination):
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    raise PermissionError("synthetic transient file lock")
                return original_replace(source, destination)

            with patch.object(
                fork_pilot_module.os,
                "replace",
                side_effect=flaky_replace,
            ), patch.object(fork_pilot_module.time, "sleep") as sleep:
                fork_pilot_module.write_bytes(target, b"durable")
            self.assertEqual(target.read_bytes(), b"durable")
            self.assertEqual(attempts, 3)
            self.assertEqual(sleep.call_count, 2)

    def test_linear_history_preserves_all_steps_and_carriers_are_isolated(self):
        run = create_manifest(master_seed=984112)["planned_run_attempts"][0]
        trial = run["trials"]["target"]
        responses = [ack_response(index) for index in range(7)]
        pending = list(responses)

        def transport(**_kwargs):
            return pending.pop(0)

        with tempfile.TemporaryDirectory() as temporary:
            store = CallStore(
                run_dir=Path(temporary),
                api_key="not-written",
                timeout=1,
                delay_seconds=0,
                transport=transport,
                sleeper=lambda _seconds: None,
            )
            runtimes, summaries = generate_trial(
                run_id=run["run_id"],
                trial=trial,
                generation_tasks=run["generation_tasks"],
                store=store,
            )
            self.assertEqual(len(summaries), 7)
            self.assertTrue(all(row["eligible"] for row in summaries))
            self.assertEqual(
                [step["type"] for step in runtimes["S6"].full_history],
                ["user_input", "thought", "model_output"] * 7,
            )
            latest = arm_steps(
                arm="target_latest_thought",
                checkpoint="S6",
                target_runtimes=runtimes,
                donor_runtimes=runtimes,
            )
            original = copy.deepcopy(runtimes["S6"].latest_thoughts)
            latest[0]["signature"] = "mutated"
            self.assertEqual(runtimes["S6"].latest_thoughts, original)
            self.assertEqual(runtimes["S0"].latest_thoughts, runtimes["S0"].cumulative_thoughts)
            compact = json.dumps(summaries)
            self.assertNotIn("private-signature-0", compact)
            self.assertIn("signature_sha256", compact)

    def test_all_fourteen_pretty_acknowledgements_pass_generation(self):
        run = create_manifest(master_seed=984113)["planned_run_attempts"][0]
        pending = [pretty_ack_response(index) for index in range(14)]

        with tempfile.TemporaryDirectory() as temporary:
            store = CallStore(
                run_dir=Path(temporary),
                api_key="not-written",
                timeout=1,
                delay_seconds=0,
                transport=lambda **_kwargs: pending.pop(0),
                sleeper=lambda _seconds: None,
            )
            runtimes = {}
            summaries = []
            for trial_name in run["generation_trial_order"]:
                trial_runtimes, trial_summaries = generate_trial(
                    run_id=run["run_id"],
                    trial=run["trials"][trial_name],
                    generation_tasks=run["generation_tasks"],
                    store=store,
                )
                runtimes[trial_name] = trial_runtimes
                summaries.extend(trial_summaries)

            self.assertFalse(pending)
            self.assertTrue(
                generation_status(
                    checkpoint_summaries=summaries,
                    runtimes=runtimes,
                )["eligible"]
            )
            self.assertTrue(
                all(row["visible_ack_canonical_match"] for row in summaries)
            )
            self.assertTrue(
                all(
                    not row["visible_ack_post_extraction_text_exact"]
                    for row in summaries
                )
            )

    def test_generation_failure_drops_provider_controlled_free_text(self):
        run = create_manifest(master_seed=10101)["planned_run_attempts"][0]
        trial = run["trials"]["target"]
        sentinel = "SECRET_PROVIDER_SENTINEL"
        bad = interaction_response(
            json.dumps({"ack": True, "echo": sentinel}, separators=(",", ":")),
            0,
        )
        with tempfile.TemporaryDirectory() as temporary:
            store = CallStore(
                run_dir=Path(temporary),
                api_key="unused",
                timeout=1,
                delay_seconds=0,
                transport=lambda **_kwargs: bad,
                sleeper=lambda _seconds: None,
            )
            _, summaries = generate_trial(
                run_id=run["run_id"],
                trial=trial,
                generation_tasks=run["generation_tasks"],
                store=store,
            )
            self.assertFalse(summaries[0]["eligible"])
            self.assertNotIn(sentinel, json.dumps(summaries))
            raw = b"".join(path.read_bytes() for path in (Path(temporary) / "raw").glob("*.response.bin"))
            self.assertIn(sentinel.encode(), raw)

    def test_probe_failure_hashes_noncanonical_provider_text(self):
        sentinel = "SECRET_PROVIDER_SENTINEL"
        result = interaction_response(
            json.dumps({"knowledge": "known", "ids": [sentinel]}),
            1,
        )
        observation = _parse_probe_result(
            result=result,
            kind="id_set",
            prescribed_ids=set(),
        )
        self.assertTrue(observation.safe_metadata["evaluable"])
        self.assertNotIn(sentinel, json.dumps(observation.safe_metadata))
        self.assertTrue(
            observation.safe_metadata["normalized"]["noncanonical_value_sha256"]
        )

    def test_provider_transport_text_is_confined_to_raw_call_index(self):
        sentinel = "ID_" + "7" * 26
        transport_failure = InteractionHttpResult(
            http_status=None,
            payload=None,
            raw_body="",
            raw_body_bytes=b"",
            transport_error=f"synthetic transport error {sentinel}",
            response_parse_error="",
            elapsed_ms=1,
        )
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            store = CallStore(
                run_dir=run_dir,
                api_key="unused",
                timeout=1,
                delay_seconds=0,
                transport=lambda **_kwargs: transport_failure,
                max_attempts=1,
                sleeper=lambda _seconds: None,
            )
            store.invoke_logical(label="logical_provider_error", body={"x": 1})
            self.assertFalse((run_dir / "call_index.json").exists())
            self.assertIn(
                sentinel,
                (run_dir / "raw" / "call_index.json").read_text(
                    encoding="utf-8"
                ),
            )


class FrozenExecutionTests(unittest.TestCase):
    def prepare(self, seed):
        temporary = tempfile.TemporaryDirectory()
        prepared = prepare_freeze(
            repo_root=REPO_ROOT,
            freeze_dir=Path(temporary.name),
            master_seed=seed,
        )
        return temporary, prepared

    def execute_with_responses(self, prepared, responses):
        pending = list(responses)
        calls = []

        def transport(**kwargs):
            calls.append(kwargs["encoded_body"])
            return pending.pop(0)

        output = execution_output_dir(
            repo_root=REPO_ROOT,
            freeze_id=prepared["freeze_id"],
        )
        parent = CanonicalExecutionCleanup(output)
        if output.exists():
            raise FileExistsError(f"stale canonical test output exists: {output}")
        try:
            ledger = execute_reviewed_freeze(
                repo_root=REPO_ROOT,
                freeze_dir=Path(prepared["freeze_dir"]),
                expected_freeze_id=prepared["freeze_id"],
                api_key="sentinel-not-persisted",
                transport=transport,
                sleeper=lambda _seconds: None,
            )
        except Exception:
            parent.cleanup()
            raise
        return parent, output, ledger, calls, pending

    def test_source_mutation_after_verification_is_refused_before_transport(self):
        freeze_temp, prepared = self.prepare(6000)
        output = execution_output_dir(
            repo_root=REPO_ROOT,
            freeze_id=prepared["freeze_id"],
        )
        manifest_path = Path(prepared["freeze_dir"]) / "manifest.json"
        original_verify = pilot_module.verify_freeze
        transport_calls = []

        def verify_then_mutate(**kwargs):
            result = original_verify(**kwargs)
            manifest_path.write_bytes(manifest_path.read_bytes() + b" ")
            return result

        try:
            with patch.object(
                pilot_module,
                "verify_freeze",
                side_effect=verify_then_mutate,
            ), self.assertRaises(ValueError):
                execute_reviewed_freeze(
                    repo_root=REPO_ROOT,
                    freeze_dir=Path(prepared["freeze_dir"]),
                    expected_freeze_id=prepared["freeze_id"],
                    api_key="unused",
                    transport=lambda **kwargs: transport_calls.append(kwargs),
                    sleeper=lambda _seconds: None,
                )
            self.assertFalse(transport_calls)
            self.assertFalse(output.exists())
        finally:
            freeze_temp.cleanup()

    def test_postclaim_setup_exception_persists_terminal_ledger(self):
        freeze_temp, prepared = self.prepare(6007)
        output = execution_output_dir(
            repo_root=REPO_ROOT,
            freeze_id=prepared["freeze_id"],
        )
        cleanup = CanonicalExecutionCleanup(output)
        transport_calls = []
        try:
            with patch.object(
                pilot_module,
                "_copy_freeze",
                side_effect=KeyboardInterrupt("synthetic setup interruption"),
            ), self.assertRaises(KeyboardInterrupt):
                execute_reviewed_freeze(
                    repo_root=REPO_ROOT,
                    freeze_dir=Path(prepared["freeze_dir"]),
                    expected_freeze_id=prepared["freeze_id"],
                    api_key="unused",
                    transport=lambda **kwargs: transport_calls.append(kwargs),
                    sleeper=lambda _seconds: None,
                )
            self.assertFalse(transport_calls)
            ledger = json.loads(
                (output / "execution_ledger.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                ledger["final_status"],
                "execution_interrupted_postclaim_setup",
            )
            self.assertEqual(ledger["logical_requests_total"], 0)
            self.assertEqual(ledger["physical_attempts_total"], 0)
            interruption = json.loads(
                (output / "execution_interrupted.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(interruption["phase"], "postclaim_setup")
            self.assertTrue(interruption["terminal_for_this_consumed_freeze"])
        finally:
            cleanup.cleanup()
            freeze_temp.cleanup()

    def test_outer_guard_terminalizes_an_unhandled_between_phase_interrupt(self):
        freeze_temp, prepared = self.prepare(6011)
        output = execution_output_dir(
            repo_root=REPO_ROOT,
            freeze_id=prepared["freeze_id"],
        )
        cleanup = CanonicalExecutionCleanup(output)

        def synthetic_claimed_inner(**kwargs):
            guard_state = kwargs["guard_state"]
            output.parent.mkdir(parents=True, exist_ok=True)
            output.mkdir(exist_ok=False)
            ledger = {
                "schema_version": "native_planning_transition_execution_ledger_v1",
                "freeze_id": prepared["freeze_id"],
                "attempts": [],
                "tomography_started_run": None,
                "final_run": None,
            }
            guard_state.update(
                {
                    "claim_created": True,
                    "output_dir": output,
                    "execution_ledger": ledger,
                    "current_run_id": "run_01",
                    "phase": "between_phase_guards",
                }
            )
            raise KeyboardInterrupt("synthetic unhandled phase gap")

        try:
            with patch.object(
                pilot_module,
                "_execute_reviewed_freeze_inner",
                side_effect=synthetic_claimed_inner,
            ), self.assertRaises(KeyboardInterrupt):
                execute_reviewed_freeze(
                    repo_root=REPO_ROOT,
                    freeze_dir=Path(prepared["freeze_dir"]),
                    expected_freeze_id=prepared["freeze_id"],
                    api_key="unused",
                    transport=lambda **_kwargs: self.fail(
                        "transport must not run"
                    ),
                    sleeper=lambda _seconds: None,
                )
            ledger = json.loads(
                (output / "execution_ledger.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                ledger["final_status"],
                "execution_interrupted_between_phase_guards",
            )
            self.assertEqual(ledger["logical_requests_total"], 0)
            self.assertEqual(ledger["physical_attempts_total"], 0)
            interruption = json.loads(
                (output / "execution_interrupted.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(interruption["phase"], "between_phase_guards")
        finally:
            cleanup.cleanup()
            freeze_temp.cleanup()

    def test_generation_postprocessing_exception_is_terminal_and_counted(self):
        freeze_temp, prepared = self.prepare(6008)
        output = execution_output_dir(
            repo_root=REPO_ROOT,
            freeze_id=prepared["freeze_id"],
        )
        cleanup = CanonicalExecutionCleanup(output)
        pending = [ack_response(index) for index in range(14)]
        try:
            with patch.object(
                pilot_module,
                "generation_status",
                side_effect=KeyboardInterrupt(
                    "synthetic generation postprocessing interruption"
                ),
            ), self.assertRaises(KeyboardInterrupt):
                execute_reviewed_freeze(
                    repo_root=REPO_ROOT,
                    freeze_dir=Path(prepared["freeze_dir"]),
                    expected_freeze_id=prepared["freeze_id"],
                    api_key="unused",
                    transport=lambda **_kwargs: pending.pop(0),
                    sleeper=lambda _seconds: None,
                )
            self.assertFalse(pending)
            ledger = json.loads(
                (output / "execution_ledger.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                ledger["final_status"],
                "execution_interrupted_after_generation_before_tomography_calls",
            )
            self.assertEqual(ledger["logical_requests_total"], 14)
            self.assertEqual(ledger["physical_attempts_total"], 14)
            self.assertFalse((output / "run_01" / "tomography_started.json").exists())
            self.assertFalse((output / "run_02").exists())
            interruption = json.loads(
                (output / "execution_interrupted.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                interruption["phase"],
                "after_generation_before_tomography_calls",
            )
        finally:
            cleanup.cleanup()
            freeze_temp.cleanup()

    def test_perfect_reviewed_freeze_executes_run_one_only(self):
        freeze_temp, prepared = self.prepare(6001)
        try:
            manifest = json.loads((Path(prepared["freeze_dir"]) / "manifest.json").read_text())
            run = manifest["planned_run_attempts"][0]
            responses = perfect_responses(run)
            parent, output, ledger, calls, pending = self.execute_with_responses(prepared, responses)
            try:
                self.assertEqual(ledger["final_run"], "run_01")
                self.assertEqual(ledger["final_status"], "tomography_complete")
                self.assertEqual(ledger["logical_requests_total"], 210)
                self.assertEqual(len(calls), 210)
                self.assertFalse(pending)
                summary = json.loads((output / "run_01" / "summary.json").read_text())
                self.assertTrue(summary["probe_matrix_complete"])
                self.assertEqual(summary["latest_component_counts"]["joint_latest"], {"exact": 28, "total": 28})
                self.assertEqual(summary["delta_counts_by_arm"]["target_latest_thought"]["exact"], 24)
                self.assertEqual(summary["wrong_trial"]["discriminating_total"], 19)
                self.assertTrue(summary["latest_positive_exploratory_observation"])
                self.assertFalse((output / "run_02").exists())
                expected_labels = {
                    task["logical_label"]
                    for task in (
                        run["generation_tasks"] + run["probe_tasks"]
                    )
                }
                logical_metadata_paths = list(
                    (output / "run_01" / "raw").glob(
                        "logical_*.metadata.json"
                    )
                )
                observed_labels = {
                    json.loads(path.read_text(encoding="utf-8"))[
                        "logical_label"
                    ]
                    for path in logical_metadata_paths
                }
                self.assertEqual(observed_labels, expected_labels)
                self.assertEqual(len(logical_metadata_paths), 210)
                self.assertTrue(
                    all(len(str(path.resolve())) < 260 for path in logical_metadata_paths)
                )
                copied = output / "frozen_protocol" / "freeze.lock.json"
                self.assertEqual(copied.read_bytes(), (Path(prepared["freeze_dir"]) / "freeze.lock.json").read_bytes())
                attempt = ledger["attempts"][0]
                summary_bytes = (output / "run_01" / "summary.json").read_bytes()
                self.assertEqual(
                    attempt["summary_file_bytes_sha256"],
                    hashlib.sha256(summary_bytes).hexdigest(),
                )
                self.assertNotEqual(
                    attempt["summary_canonical_json_sha256"],
                    attempt["summary_file_bytes_sha256"],
                )
                all_bytes = b"".join(
                    path.read_bytes() for path in output.rglob("*") if path.is_file()
                )
                self.assertNotIn(b"sentinel-not-persisted", all_bytes)
                with self.assertRaises(FileExistsError):
                    execute_reviewed_freeze(
                        repo_root=REPO_ROOT,
                        freeze_dir=Path(prepared["freeze_dir"]),
                        expected_freeze_id=prepared["freeze_id"],
                        api_key="unused",
                        transport=lambda **_kwargs: self.fail(
                            "transport must not run for a consumed freeze"
                        ),
                        sleeper=lambda _seconds: None,
                    )
            finally:
                parent.cleanup()
        finally:
            freeze_temp.cleanup()

    def test_generation_failure_allows_only_frozen_replacement(self):
        freeze_temp, prepared = self.prepare(6002)
        try:
            manifest = json.loads((Path(prepared["freeze_dir"]) / "manifest.json").read_text())
            bad = interaction_response('{"ack":false}', 0)
            responses = [bad, *perfect_responses(manifest["planned_run_attempts"][1], start_index=1)]
            parent, output, ledger, calls, pending = self.execute_with_responses(prepared, responses)
            try:
                self.assertEqual(ledger["final_run"], "run_02")
                self.assertEqual(ledger["logical_requests_total"], 211)
                self.assertEqual(len(calls), 211)
                self.assertFalse(pending)
                self.assertFalse((output / "run_01" / "tomography_started.json").exists())
                self.assertTrue((output / "run_02" / "tomography_started.json").exists())
            finally:
                parent.cleanup()
        finally:
            freeze_temp.cleanup()

    def test_unknown_provider_id_is_hashed_in_every_compact_execution_artifact(self):
        freeze_temp, prepared = self.prepare(6005)
        try:
            manifest = json.loads(
                (Path(prepared["freeze_dir"]) / "manifest.json").read_text()
            )
            run = manifest["planned_run_attempts"][0]
            responses = perfect_responses(run)
            probe_index = next(
                index
                for index, task in enumerate(run["probe_tasks"])
                if task["field"] == "candidate_registry"
                and task["arm"] == "target_latest_thought"
            )
            unknown_id = "ID_" + "7" * 26
            responses[14 + probe_index] = interaction_response(
                json.dumps({"knowledge": "known", "ids": [unknown_id]}),
                14 + probe_index,
            )
            parent, output, _ledger, _calls, pending = self.execute_with_responses(
                prepared,
                responses,
            )
            try:
                self.assertFalse(pending)
                compact_files = [
                    path
                    for path in output.rglob("*")
                    if path.is_file() and "raw" not in path.parts
                ]
                compact_bytes = b"".join(path.read_bytes() for path in compact_files)
                expected_hash = hashlib.sha256(unknown_id.encode("utf-8")).hexdigest()
                self.assertNotIn(unknown_id.encode("utf-8"), compact_bytes)
                self.assertIn(expected_hash.encode("ascii"), compact_bytes)
                raw_bytes = b"".join(
                    path.read_bytes()
                    for path in (output / "run_01" / "raw").glob("*.response.bin")
                )
                self.assertIn(unknown_id.encode("utf-8"), raw_bytes)
            finally:
                parent.cleanup()
        finally:
            freeze_temp.cleanup()

    def test_tomography_failure_is_final_and_never_triggers_run_two(self):
        freeze_temp, prepared = self.prepare(6003)
        try:
            manifest = json.loads((Path(prepared["freeze_dir"]) / "manifest.json").read_text())
            run = manifest["planned_run_attempts"][0]
            responses = perfect_responses(run)
            bad_probe_index = next(
                index
                for index, task in enumerate(run["probe_tasks"])
                if task["arm"] == "target_latest_thought"
                and task["checkpoint"] == "S3"
                and task["field"] == "candidate_registry"
            )
            future_id = run["trials"]["target"]["report_aliases"]["D"]
            responses[14 + bad_probe_index] = interaction_response(
                f'not-json "{future_id}"', 14 + bad_probe_index
            )
            parent, output, ledger, calls, pending = self.execute_with_responses(prepared, responses)
            try:
                self.assertEqual(ledger["final_run"], "run_01")
                self.assertEqual(ledger["logical_requests_total"], 210)
                self.assertEqual(len(calls), 210)
                self.assertFalse(pending)
                self.assertFalse((output / "run_02").exists())
                summary = json.loads((output / "run_01" / "summary.json").read_text())
                self.assertTrue(summary["probe_matrix_complete"])
                self.assertGreater(summary["premature_ids"], 0)
                self.assertFalse(summary["causal_specificity_gate"])
                self.assertFalse(summary["latest_positive_exploratory_observation"])
            finally:
                parent.cleanup()
        finally:
            freeze_temp.cleanup()

    def test_tomography_exception_is_terminal_and_freeze_cannot_be_reused(self):
        freeze_temp, prepared = self.prepare(6004)
        output = execution_output_dir(
            repo_root=REPO_ROOT,
            freeze_id=prepared["freeze_id"],
        )
        cleanup = CanonicalExecutionCleanup(output)
        try:
            manifest = json.loads(
                (Path(prepared["freeze_dir"]) / "manifest.json").read_text()
            )
            pending = [ack_response(index) for index in range(14)]

            def transport(**_kwargs):
                if pending:
                    return pending.pop(0)
                raise RuntimeError("synthetic transport interruption")

            with self.assertRaises(RuntimeError):
                execute_reviewed_freeze(
                    repo_root=REPO_ROOT,
                    freeze_dir=Path(prepared["freeze_dir"]),
                    expected_freeze_id=prepared["freeze_id"],
                    api_key="unused",
                    transport=transport,
                    sleeper=lambda _seconds: None,
                )
            self.assertFalse(pending)
            ledger = json.loads((output / "execution_ledger.json").read_text())
            self.assertEqual(ledger["final_run"], manifest["planned_run_attempts"][0]["run_id"])
            self.assertEqual(ledger["final_status"], "tomography_interrupted_final")
            self.assertEqual(ledger["logical_requests_total"], 15)
            self.assertEqual(ledger["physical_attempts_total"], 15)
            self.assertTrue((output / "run_01" / "tomography_interrupted.json").exists())
            interruption = json.loads(
                (output / "run_01" / "tomography_interrupted.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(interruption["probe_logical_requests_attempted"], 1)
            self.assertEqual(interruption["probe_physical_attempts_started"], 1)
            self.assertFalse((output / "run_02").exists())
            with self.assertRaises(FileExistsError):
                execute_reviewed_freeze(
                    repo_root=REPO_ROOT,
                    freeze_dir=Path(prepared["freeze_dir"]),
                    expected_freeze_id=prepared["freeze_id"],
                    api_key="unused",
                    transport=transport,
                    sleeper=lambda _seconds: None,
                )
        finally:
            cleanup.cleanup()
            freeze_temp.cleanup()

    def test_generation_exception_is_terminal_and_counts_inflight_attempt(self):
        freeze_temp, prepared = self.prepare(6006)
        output = execution_output_dir(
            repo_root=REPO_ROOT,
            freeze_id=prepared["freeze_id"],
        )
        cleanup = CanonicalExecutionCleanup(output)
        unknown_id = "ID_" + "7" * 26
        call_count = 0

        def transport(**_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ack_response(0)
            raise KeyboardInterrupt(f"synthetic interruption {unknown_id}")

        try:
            with self.assertRaises(KeyboardInterrupt):
                execute_reviewed_freeze(
                    repo_root=REPO_ROOT,
                    freeze_dir=Path(prepared["freeze_dir"]),
                    expected_freeze_id=prepared["freeze_id"],
                    api_key="unused",
                    transport=transport,
                    sleeper=lambda _seconds: None,
                )
            ledger = json.loads(
                (output / "execution_ledger.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                ledger["final_status"],
                "execution_interrupted_before_tomography",
            )
            self.assertEqual(ledger["logical_requests_total"], 2)
            self.assertEqual(ledger["physical_attempts_total"], 2)
            self.assertEqual(call_count, 2)
            self.assertTrue((output / "execution_interrupted.json").exists())
            self.assertFalse((output / "run_01" / "tomography_started.json").exists())
            self.assertFalse((output / "run_02").exists())
            raw_index = json.loads(
                (output / "run_01" / "raw" / "call_index.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(len(raw_index), 2)
            self.assertEqual(
                raw_index[-1]["attempt_state"],
                "transport_interrupted_outcome_unknown",
            )
            self.assertFalse((output / "run_01" / "call_index.json").exists())
            compact_bytes = b"".join(
                path.read_bytes()
                for path in output.rglob("*")
                if path.is_file() and "raw" not in path.parts
            )
            self.assertNotIn(unknown_id.encode("ascii"), compact_bytes)
            with self.assertRaises(FileExistsError):
                execute_reviewed_freeze(
                    repo_root=REPO_ROOT,
                    freeze_dir=Path(prepared["freeze_dir"]),
                    expected_freeze_id=prepared["freeze_id"],
                    api_key="unused",
                    transport=lambda **_kwargs: self.fail(
                        "transport must not run for a consumed freeze"
                    ),
                    sleeper=lambda _seconds: None,
                )
        finally:
            cleanup.cleanup()
            freeze_temp.cleanup()

    def test_summary_hash_exception_is_terminal_tomography_interruption(self):
        freeze_temp, prepared = self.prepare(6009)
        output = execution_output_dir(
            repo_root=REPO_ROOT,
            freeze_id=prepared["freeze_id"],
        )
        cleanup = CanonicalExecutionCleanup(output)
        manifest = json.loads(
            (Path(prepared["freeze_dir"]) / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        pending = perfect_responses(manifest["planned_run_attempts"][0])
        original_sha256_json = pilot_module.sha256_json

        def interrupt_summary_hash(value):
            if (
                isinstance(value, dict)
                and value.get("schema_version")
                == "native_planning_transition_summary_v1"
            ):
                raise KeyboardInterrupt("synthetic summary hash interruption")
            return original_sha256_json(value)

        try:
            with patch.object(
                pilot_module,
                "sha256_json",
                side_effect=interrupt_summary_hash,
            ), self.assertRaises(KeyboardInterrupt):
                execute_reviewed_freeze(
                    repo_root=REPO_ROOT,
                    freeze_dir=Path(prepared["freeze_dir"]),
                    expected_freeze_id=prepared["freeze_id"],
                    api_key="unused",
                    transport=lambda **_kwargs: pending.pop(0),
                    sleeper=lambda _seconds: None,
                )
            self.assertFalse(pending)
            ledger = json.loads(
                (output / "execution_ledger.json").read_text(encoding="utf-8")
            )
            self.assertEqual(ledger["final_status"], "tomography_interrupted_final")
            self.assertEqual(ledger["logical_requests_total"], 210)
            self.assertEqual(ledger["physical_attempts_total"], 210)
            self.assertTrue(
                (output / "run_01" / "tomography_interrupted.json").exists()
            )
            self.assertFalse((output / "run_02").exists())
        finally:
            cleanup.cleanup()
            freeze_temp.cleanup()

    def test_terminal_ledger_write_exception_gets_root_interruption_record(self):
        freeze_temp, prepared = self.prepare(6010)
        output = execution_output_dir(
            repo_root=REPO_ROOT,
            freeze_id=prepared["freeze_id"],
        )
        cleanup = CanonicalExecutionCleanup(output)
        manifest = json.loads(
            (Path(prepared["freeze_dir"]) / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        pending = perfect_responses(manifest["planned_run_attempts"][0])
        original_write_json = pilot_module.write_json
        interrupted = False

        def interrupt_final_ledger(path, value):
            nonlocal interrupted
            if (
                not interrupted
                and Path(path).name == "execution_ledger.json"
                and isinstance(value, dict)
                and value.get("final_status") == "tomography_complete"
            ):
                interrupted = True
                raise KeyboardInterrupt("synthetic final ledger interruption")
            return original_write_json(path, value)

        try:
            with patch.object(
                pilot_module,
                "write_json",
                side_effect=interrupt_final_ledger,
            ), self.assertRaises(KeyboardInterrupt):
                execute_reviewed_freeze(
                    repo_root=REPO_ROOT,
                    freeze_dir=Path(prepared["freeze_dir"]),
                    expected_freeze_id=prepared["freeze_id"],
                    api_key="unused",
                    transport=lambda **_kwargs: pending.pop(0),
                    sleeper=lambda _seconds: None,
                )
            self.assertTrue(interrupted)
            self.assertFalse(pending)
            ledger = json.loads(
                (output / "execution_ledger.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                ledger["final_status"],
                "execution_interrupted_during_terminal_persistence",
            )
            self.assertEqual(ledger["logical_requests_total"], 210)
            self.assertEqual(ledger["physical_attempts_total"], 210)
            interruption = json.loads(
                (output / "execution_interrupted.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                interruption["previous_final_status"],
                "tomography_complete",
            )
            self.assertEqual(
                interruption["phase"],
                "during_terminal_persistence",
            )
        finally:
            cleanup.cleanup()
            freeze_temp.cleanup()

    def test_summary_is_missing_safe(self):
        run = create_manifest(master_seed=777)["planned_run_attempts"][0]
        summary = summarize_results(
            run_attempt=run,
            generation={"eligible": False},
            checkpoint_summaries=[],
            rows=[
                None,
                {"checkpoint": "S0"},
                {
                    "checkpoint": "S0",
                    "field": "candidate_registry",
                    "arm": "target_latest_thought",
                    "score_source": {"exact": True},
                },
            ],
            observations={},
            delta_rows=[None],
        )
        self.assertFalse(summary["probe_matrix_complete"])
        self.assertFalse(summary["delta_matrix"]["complete"])
        self.assertEqual(summary["first_attempt_sensitivity"]["latest_exact"], 0)
        self.assertFalse(summary["latest_positive_exploratory_observation"])

    def test_summary_rejects_nonmechanical_delta_flags(self):
        run = create_manifest(master_seed=778)["planned_run_attempts"][0]
        delta_rows = derive_delta_rows(
            run_attempt=run,
            rows=[],
            observations={},
        )
        delta_rows[0]["changed_expected"] = not delta_rows[0]["changed_expected"]
        summary = summarize_results(
            run_attempt=run,
            generation={"eligible": False},
            checkpoint_summaries=[],
            rows=[],
            observations={},
            delta_rows=delta_rows,
        )
        self.assertFalse(summary["delta_matrix"]["complete"])
        self.assertEqual(summary["delta_matrix"]["nonmechanical_rows"], 1)


if __name__ == "__main__":
    unittest.main()
