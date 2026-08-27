import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from thoughtlab.gemini_interactions import (
    InteractionHttpResult,
    canonical_json_bytes,
    sha256_json,
    user_step,
)
from thoughtlab.stateTransitions import fork_pilot
from thoughtlab.stateTransitions.fork_pilot import (
    ARMS,
    CallStore,
    arm_steps,
    create_manifest,
    generate_trial,
    is_private_run_directory,
    load_and_validate_experiment_definition,
    resolve_run_directory,
    render_review,
    summarize_results,
    validate_manifest,
)
from thoughtlab.stateTransitions.probes import PROBES
from thoughtlab.stateTransitions.score_ground_truth import (
    score_probe_answer,
    validate_probe_answer,
)


def completed_response(index: int, *, model: str = "gemini-3.7-flash"):
    payload = {
        "status": "completed",
        "model": model,
        "steps": [
            {
                "type": "thought",
                "signature": f"private-signature-{index}",
                "summary": [],
            },
            {
                "type": "model_output",
                "content": [{"type": "text", "text": '{"ack":true}'}],
            },
        ],
    }
    return InteractionHttpResult(
        http_status=200,
        payload=payload,
        raw_body=json.dumps(payload),
        transport_error="",
        response_parse_error="",
        elapsed_ms=1,
    )


class ManifestTests(unittest.TestCase):
    def test_frozen_definition_matches_executable_protocol(self):
        repo_root = Path(__file__).resolve().parents[1]
        definition = load_and_validate_experiment_definition(repo_root)
        self.assertEqual(definition["model"], "gemini-3.7-flash")

    def test_manifest_is_deterministic_except_timestamps(self):
        left = create_manifest(master_seed=77231, model="gemini-3.7-flash")
        right = create_manifest(master_seed=77231, model="gemini-3.7-flash")
        left.pop("created_at")
        right.pop("created_at")
        self.assertEqual(left, right)
        self.assertEqual(validate_manifest(left), [])

    def test_manifest_has_disjoint_type_neutral_ids_and_complete_matrix(self):
        manifest = create_manifest(master_seed=99119, model="gemini-3.7-flash")
        target = manifest["trials"]["target"]
        donor = manifest["trials"]["donor"]
        self.assertTrue(set(target["id_universe"]).isdisjoint(donor["id_universe"]))
        for identifier in target["id_universe"] + donor["id_universe"]:
            self.assertRegex(identifier, r"^ID_[0-9A-HJKMNP-TV-Z]{26}$")
            self.assertNotRegex(identifier, r"PLAN|FACT|GOAL|CONSTRAINT")
        self.assertNotEqual(
            target["truth"]["S5A"]["selected_plan"],
            target["truth"]["S5B"]["selected_plan"],
        )
        self.assertEqual(
            target["truth"]["S5A"]["utility_ranking"],
            target["truth"]["S5B"]["utility_ranking"],
        )
        self.assertEqual(len(manifest["probe_tasks"]), 2 * len(PROBES) * len(ARMS))
        self.assertEqual(
            {task["request_order"] for task in manifest["probe_tasks"]},
            set(range(1, len(manifest["probe_tasks"]) + 1)),
        )
        self.assertNotIn(
            "temperature",
            manifest["request_templates"]["generation_config_generation"],
        )
        self.assertEqual(
            manifest["request_templates"]["generation_config_generation"][
                "max_output_tokens"
            ],
            8192,
        )
        self.assertIsNone(manifest["api"]["api_revision_header"])

    def test_execute_paths_must_resolve_under_private_results(self):
        repo_root = Path(__file__).resolve().parents[1]
        safe = (repo_root / "results" / "fork_pilot" / "run").resolve()
        unsafe = (repo_root / "thoughtlab" / "stateTransitions" / "leak").resolve()
        self.assertTrue(
            is_private_run_directory(repo_root=repo_root, run_dir=safe)
        )
        self.assertFalse(
            is_private_run_directory(repo_root=repo_root, run_dir=unsafe)
        )
        default = resolve_run_directory(
            repo_root=repo_root,
            requested_out=None,
            run_tag="tag",
            seed=123,
        )
        self.assertEqual(default, (repo_root / "results/fork_pilot/tag_123").resolve())

    def test_branch_prompts_and_seeds_differ_only_as_prespecified(self):
        trial = create_manifest(
            master_seed=42, model="gemini-3.7-flash"
        )["trials"]["target"]
        self.assertEqual(
            trial["generation_seeds"]["S5A"], trial["generation_seeds"]["S5B"]
        )
        a = trial["prompts"]["S5A"].replace("MAXIMUM", "EXTREME")
        b = trial["prompts"]["S5B"].replace("MINIMUM", "EXTREME")
        self.assertEqual(a, b)

    def test_manifest_validation_rejects_corrupted_truth(self):
        manifest = create_manifest(master_seed=734, model="gemini-3.7-flash")
        manifest["trials"]["target"]["truth"]["S5A"]["selected_plan"] = [
            manifest["trials"]["donor"]["id_universe"][0]
        ]
        errors = validate_manifest(manifest)
        self.assertTrue(any("truth" in error for error in errors))


class ForkHistoryTests(unittest.TestCase):
    def test_generation_rejects_hidden_state_in_non_text_output_block(self):
        trial = create_manifest(
            master_seed=6871, model="gemini-3.7-flash"
        )["trials"]["target"]
        leaked_id = trial["id_universe"][0]
        payload = {
            "status": "completed",
            "model": "gemini-3.7-flash",
            "steps": [
                {"type": "thought", "signature": "signed", "summary": []},
                {
                    "type": "model_output",
                    "content": [
                        {"type": "text", "text": '{"ack":true}'},
                        {"type": "metadata", "value": leaked_id},
                    ],
                },
            ],
        }
        result = InteractionHttpResult(
            http_status=200,
            payload=payload,
            raw_body=json.dumps(payload),
            transport_error="",
            response_parse_error="",
            elapsed_ms=1,
        )
        body = fork_pilot.build_interaction_body(
            model="gemini-3.7-flash",
            input_steps=[user_step(trial["prompts"]["S0"])],
            generation_config=fork_pilot.generation_config(1, probe=False),
            response_format=fork_pilot.ACK_RESPONSE_FORMAT,
        )
        reasons, details = fork_pilot._checkpoint_eligibility(
            result=result,
            payload=payload,
            steps=payload["steps"],
            request_body=body,
            trial=trial,
            model="gemini-3.7-flash",
        )
        self.assertIn("visible output leaked prescribed state", reasons)
        self.assertTrue(details["model_output_structure_issues"])

    def test_generation_preserves_all_steps_and_forks_exact_p4(self):
        trial = create_manifest(
            master_seed=984112, model="gemini-3.7-flash"
        )["trials"]["target"]
        responses = [completed_response(index) for index in range(7)]

        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            store = CallStore(
                run_dir=run_dir,
                api_key="not-written",
                timeout=1,
                delay_seconds=0,
            )
            with patch.object(
                fork_pilot, "post_interaction", side_effect=responses
            ) as mocked_post:
                runtimes, summaries = generate_trial(
                    trial=trial,
                    model="gemini-3.7-flash",
                    store=store,
                )

            self.assertEqual(len(mocked_post.call_args_list), 7)
            self.assertEqual(len(summaries), 7)
            self.assertTrue(all(row["eligible"] for row in summaries))

            branch_calls = {}
            for call in mocked_post.call_args_list:
                body = call.kwargs["body"]
                final_prompt = body["input"][-1]["content"][0]["text"]
                if final_prompt == trial["prompts"]["S5A"]:
                    branch_calls["S5A"] = body
                elif final_prompt == trial["prompts"]["S5B"]:
                    branch_calls["S5B"] = body

            self.assertEqual(set(branch_calls), {"S5A", "S5B"})
            prefix_a = branch_calls["S5A"]["input"][:-1]
            prefix_b = branch_calls["S5B"]["input"][:-1]
            self.assertEqual(prefix_a, prefix_b)
            self.assertEqual(prefix_a, runtimes["S4"].full_history)
            self.assertEqual(sha256_json(prefix_a), sha256_json(prefix_b))
            self.assertEqual(
                branch_calls["S5A"]["generation_config"]["seed"],
                branch_calls["S5B"]["generation_config"]["seed"],
            )

            # P4 has five user turns and preserves both returned steps per turn.
            self.assertEqual(len(prefix_a), 15)
            self.assertEqual(
                [step["type"] for step in prefix_a],
                ["user_input", "thought", "model_output"] * 5,
            )

            raw_response = b"\n".join(
                path.read_bytes()
                for path in (run_dir / "raw").glob("*.response.bin")
            )
            self.assertIn(b"private-signature-0", raw_response)
            compact = json.dumps(summaries)
            self.assertNotIn("private-signature-0", compact)
            self.assertIn("signature_sha256", compact)
            first_body = mocked_post.call_args_list[0].kwargs["body"]
            first_request = next((run_dir / "raw").glob("*.request.json"))
            self.assertEqual(first_request.read_bytes(), canonical_json_bytes(first_body))
            self.assertNotIn(b"not-written", first_request.read_bytes())

    def test_artifact_arms_are_isolated_copies(self):
        trial = create_manifest(
            master_seed=55, model="gemini-3.7-flash"
        )["trials"]["target"]
        responses = [completed_response(index) for index in range(7)]
        with tempfile.TemporaryDirectory() as temporary:
            store = CallStore(
                run_dir=Path(temporary),
                api_key="unused",
                timeout=1,
                delay_seconds=0,
            )
            with patch.object(fork_pilot, "post_interaction", side_effect=responses):
                runtimes, _ = generate_trial(
                    trial=trial, model="gemini-3.7-flash", store=store
                )

            latest = arm_steps(
                arm="latest_thought",
                target=runtimes["S5A"],
                donor=runtimes["S5B"],
            )
            original = copy.deepcopy(runtimes["S5A"].latest_thoughts)
            latest[0]["signature"] = "mutated"
            self.assertEqual(runtimes["S5A"].latest_thoughts, original)
            self.assertEqual(
                arm_steps(
                    arm="probe_only",
                    target=runtimes["S5A"],
                    donor=runtimes["S5B"],
                ),
                [],
            )


class RetryPolicyTests(unittest.TestCase):
    @staticmethod
    def _http_result(
        status,
        *,
        transport_error="",
        parse_error="",
        payload=None,
    ):
        raw = json.dumps(payload) if payload is not None else ""
        return InteractionHttpResult(
            http_status=status,
            payload=payload,
            raw_body=raw,
            transport_error=transport_error,
            response_parse_error=parse_error,
            elapsed_ms=1,
        )

    def test_frozen_retry_sequences_and_selection(self):
        completed = self._http_result(
            200,
            payload={"status": "completed", "model": "gemini-3.7-flash"},
        )
        cases = [
            ("success", [completed], 1, [], "first_attempt_nonretryable"),
            (
                "protocol_rejection",
                [self._http_result(400, payload={"error": {}})],
                1,
                [],
                "first_attempt_nonretryable",
            ),
            (
                "invalid_json_200",
                [self._http_result(200, parse_error="invalid")],
                1,
                [],
                "first_attempt_nonretryable",
            ),
            (
                "incomplete_200",
                [self._http_result(200, payload={"status": "incomplete"})],
                1,
                [],
                "first_attempt_nonretryable",
            ),
            (
                "503_then_200",
                [self._http_result(503, payload={"error": {}}), completed],
                2,
                [2.0],
                "first_nonretryable_after_retry",
            ),
            (
                "transport_then_400",
                [
                    self._http_result(None, transport_error="reset"),
                    self._http_result(400, payload={"error": {}}),
                ],
                2,
                [2.0],
                "first_nonretryable_after_retry",
            ),
            (
                "retry_budget_exhausted",
                [
                    self._http_result(429, payload={"error": {}}),
                    self._http_result(503, payload={"error": {}}),
                    self._http_result(429, payload={"error": {}}),
                ],
                3,
                [2.0, 5.0],
                "retry_budget_exhausted",
            ),
            (
                "408_then_schema_invalid_200",
                [
                    self._http_result(408, payload={"error": {}}),
                    self._http_result(200, payload={"status": "completed"}),
                ],
                2,
                [2.0],
                "first_nonretryable_after_retry",
            ),
        ]
        for name, sequence, expected_attempts, expected_sleeps, reason in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                pending = list(sequence)
                wire_bodies = []
                sleeps = []

                def transport(**kwargs):
                    wire_bodies.append(kwargs["encoded_body"])
                    return pending.pop(0)

                store = CallStore(
                    run_dir=Path(temporary),
                    api_key="never-persisted",
                    timeout=120,
                    delay_seconds=0,
                    transport=transport,
                    sleeper=sleeps.append,
                )
                _, logical = store.invoke_logical(
                    label=f"case_{name}",
                    body={"model": "gemini-3.7-flash", "store": False},
                )
                self.assertEqual(logical["attempt_count"], expected_attempts)
                self.assertEqual(logical["selection_reason"], reason)
                self.assertEqual(sleeps, expected_sleeps)
                self.assertEqual(len(set(wire_bodies)), 1)
                self.assertEqual(len(store.records), expected_attempts)
                self.assertTrue(logical["attempts"][-1]["selected_for_logical_result"])
                self.assertTrue(
                    all(
                        not attempt["selected_for_logical_result"]
                        for attempt in logical["attempts"][:-1]
                    )
                )
                self.assertTrue(
                    list((Path(temporary) / "raw").glob("logical_*.metadata.json"))
                )

    def test_only_selected_generation_attempt_enters_history(self):
        trial = create_manifest(
            master_seed=9124, model="gemini-3.7-flash"
        )["trials"]["target"]
        excluded_payload = {
            "status": "completed",
            "model": "gemini-3.7-flash",
            "steps": [
                {"type": "thought", "signature": "excluded-signature"},
                {
                    "type": "model_output",
                    "content": [{"type": "text", "text": '{"ack":true}'}],
                },
            ],
        }
        responses = [
            self._http_result(503, payload=excluded_payload),
            *[completed_response(index) for index in range(7)],
        ]
        with tempfile.TemporaryDirectory() as temporary:
            pending = list(responses)

            def transport(**_kwargs):
                return pending.pop(0)

            store = CallStore(
                run_dir=Path(temporary),
                api_key="unused",
                timeout=120,
                delay_seconds=0,
                transport=transport,
                sleeper=lambda _seconds: None,
            )
            runtimes, summaries = generate_trial(
                trial=trial,
                model="gemini-3.7-flash",
                store=store,
            )
        serialized_history = json.dumps(runtimes["S5A"].full_history)
        self.assertNotIn("excluded-signature", serialized_history)
        self.assertEqual(summaries[0]["call"]["selected_attempt"], 2)
        self.assertEqual(len(store.records), 8)


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.trial = create_manifest(
            master_seed=76543, model="gemini-3.7-flash"
        )["trials"]["target"]
        self.universe = set(self.trial["id_universe"])

    def test_exact_id_set_scores_and_unknown_does_not(self):
        expected = self.trial["truth"]["S5A"]["rejected_plans"]
        normalized = validate_probe_answer(
            "id_set", {"knowledge": "known", "ids": list(reversed(expected))}
        )
        score = score_probe_answer(
            kind="id_set",
            normalized=normalized,
            expected=expected,
            truth_universe=self.universe,
        )
        self.assertTrue(score["exact"])

        unknown = validate_probe_answer(
            "id_set", {"knowledge": "unknown", "ids": []}
        )
        score_unknown = score_probe_answer(
            kind="id_set",
            normalized=unknown,
            expected=expected,
            truth_universe=self.universe,
        )
        self.assertFalse(score_unknown["exact"])
        self.assertEqual(score_unknown["outcome"], "unknown_for_known")

    def test_duplicates_foreign_ids_and_wrong_rank_fail_exactness(self):
        ranking = self.trial["truth"]["S5A"]["utility_ranking"]
        duplicate = validate_probe_answer(
            "ranking",
            {"knowledge": "known", "ids_high_to_low": ranking + [ranking[-1]]},
        )
        duplicate_score = score_probe_answer(
            kind="ranking",
            normalized=duplicate,
            expected=ranking,
            truth_universe=self.universe,
        )
        self.assertFalse(duplicate_score["exact"])
        self.assertEqual(duplicate_score["duplicate_ids"], [ranking[-1]])

        reversed_rank = validate_probe_answer(
            "ranking",
            {"knowledge": "known", "ids_high_to_low": list(reversed(ranking))},
        )
        reversed_score = score_probe_answer(
            kind="ranking",
            normalized=reversed_rank,
            expected=ranking,
            truth_universe=self.universe,
        )
        self.assertFalse(reversed_score["exact"])
        self.assertEqual(reversed_score["pairwise_order"]["correct"], 0)

    def test_null_and_malformed_values_cannot_score(self):
        expected = self.trial["truth"]["S5A"]["selected_plan"]
        for value in (None, {"knowledge": "known", "ids": None}, []):
            normalized = validate_probe_answer("id_set", value)
            score = score_probe_answer(
                kind="id_set",
                normalized=normalized,
                expected=expected,
                truth_universe=self.universe,
            )
            self.assertFalse(score["scored"])
            self.assertEqual(score["outcome"], "schema_invalid")

    def test_foreign_truth_universe_can_never_score_exact(self):
        expected = self.trial["truth"]["S5A"]["selected_plan"]
        normalized = validate_probe_answer(
            "id_set", {"knowledge": "known", "ids": expected}
        )
        score = score_probe_answer(
            kind="id_set",
            normalized=normalized,
            expected=expected,
            truth_universe=set(),
        )
        self.assertFalse(score["exact"])
        self.assertEqual(score["foreign_ids"], expected)
        self.assertEqual(score["expected_foreign_ids"], expected)


class ProbeParsingTests(unittest.TestCase):
    @staticmethod
    def _result(status, payload):
        raw = json.dumps(payload) if payload is not None else ""
        return InteractionHttpResult(
            http_status=status,
            payload=payload,
            raw_body=raw,
            transport_error="",
            response_parse_error="",
            elapsed_ms=1,
        )

    def test_http_outcomes_preserve_protocol_vs_missing_data(self):
        for status, outcome in (
            (400, "protocol_rejected"),
            (429, "rate_limited"),
            (503, "provider_error"),
        ):
            with self.subTest(status=status):
                parsed = fork_pilot._parse_probe_result(
                    result=self._result(status, {"error": {"message": "x"}}),
                    model="gemini-3.7-flash",
                    kind="id_set",
                )
                self.assertFalse(parsed["evaluable"])
                self.assertEqual(parsed["outcome"], outcome)

    def test_success_with_missing_steps_or_extra_output_is_unevaluable(self):
        missing = {
            "status": "completed",
            "model": "gemini-3.7-flash",
        }
        parsed_missing = fork_pilot._parse_probe_result(
            result=self._result(200, missing),
            model="gemini-3.7-flash",
            kind="id_set",
        )
        self.assertEqual(parsed_missing["outcome"], "response_shape_error")

        extra = {
            "status": "completed",
            "model": "gemini-3.7-flash",
            "steps": [
                {
                    "type": "model_output",
                    "content": [
                        {
                            "type": "text",
                            "text": '{"knowledge":"unknown","ids":[]}',
                        },
                        {"type": "metadata", "value": "hidden"},
                    ],
                }
            ],
        }
        parsed_extra = fork_pilot._parse_probe_result(
            result=self._result(200, extra),
            model="gemini-3.7-flash",
            kind="id_set",
        )
        self.assertFalse(parsed_extra["evaluable"])
        self.assertEqual(parsed_extra["outcome"], "response_shape_error")


class ReportingTests(unittest.TestCase):
    @staticmethod
    def _known_answer(kind, expected):
        if kind == "ancestry":
            return {"knowledge": "known", "items": copy.deepcopy(expected)}
        if kind == "ranking":
            return {
                "knowledge": "known",
                "ids_high_to_low": copy.deepcopy(expected),
            }
        return {"knowledge": "known", "ids": copy.deepcopy(expected)}

    def _clean_result_matrix(self, manifest):
        target = manifest["trials"]["target"]
        donor = manifest["trials"]["donor"]
        target_universe = set(target["id_universe"])
        donor_universe = set(donor["id_universe"])
        rows = []
        for task in manifest["probe_tasks"]:
            branch = task["branch"]
            probe_id = task["probe_id"]
            arm = task["arm"]
            kind = PROBES[probe_id]["kind"]
            if arm in {"visible_only", "probe_only"}:
                parsed = (
                    {"knowledge": "unknown", "items": []}
                    if kind == "ancestry"
                    else {
                        "knowledge": "unknown",
                        "ids_high_to_low": [],
                    }
                    if kind == "ranking"
                    else {"knowledge": "unknown", "ids": []}
                )
            elif arm == "wrong_trial":
                parsed = self._known_answer(kind, donor["truth"][branch][probe_id])
            else:
                parsed = self._known_answer(kind, target["truth"][branch][probe_id])
            normalized = validate_probe_answer(kind, parsed)
            score_current = score_probe_answer(
                kind=kind,
                normalized=normalized,
                expected=target["truth"][branch][probe_id],
                truth_universe=target_universe,
            )
            score_donor = None
            if arm == "wrong_trial":
                score_donor = score_probe_answer(
                    kind=kind,
                    normalized=normalized,
                    expected=donor["truth"][branch][probe_id],
                    truth_universe=donor_universe,
                )
            rows.append(
                {
                    "request_order": task["request_order"],
                    "branch": branch,
                    "probe_id": probe_id,
                    "arm": arm,
                    "evaluable": True,
                    "outcome": "scored",
                    "normalized": normalized,
                    "call": {"attempt_count": 1},
                    "score_current": score_current,
                    "score_donor": score_donor,
                }
            )
        return rows

    @staticmethod
    def _checkpoint_matrix():
        rows = []
        for trial_id in ("target", "donor"):
            for checkpoint_id in ("S0", "S1", "S2", "S3"):
                rows.append(
                    {
                        "trial_id": trial_id,
                        "checkpoint_id": checkpoint_id,
                        "eligible": True,
                        "call": {"attempt_count": 1},
                    }
                )
            parent_hash = f"{trial_id}-p4"
            rows.append(
                {
                    "trial_id": trial_id,
                    "checkpoint_id": "S4",
                    "eligible": True,
                    "full_prefix_sha256": parent_hash,
                    "call": {"attempt_count": 1},
                }
            )
            for branch in ("S5A", "S5B"):
                rows.append(
                    {
                        "trial_id": trial_id,
                        "checkpoint_id": branch,
                        "eligible": True,
                        "call": {"attempt_count": 1},
                        "fork_parent_prefix_sha256": parent_hash,
                        "response_steps_sha256": f"{trial_id}-{branch}-response",
                        "latest_thought_sha256": f"{trial_id}-{branch}-latest",
                        "cumulative_thought_sha256": f"{trial_id}-{branch}-cumulative",
                    }
                )
        return rows

    def test_positive_gate_requires_all_prespecified_components(self):
        manifest = create_manifest(master_seed=1001, model="gemini-3.7-flash")
        rows = self._clean_result_matrix(manifest)
        checkpoints = self._checkpoint_matrix()
        summary = summarize_results(
            manifest=manifest,
            checkpoint_summaries=checkpoints,
            results=rows,
        )
        self.assertTrue(summary["probe_matrix_complete"])
        self.assertTrue(summary["full_prefix_adherence_composite"])
        self.assertTrue(summary["controls_clean_unknown_empty"])
        self.assertTrue(summary["wrong_trial_follows_donor_composite"])
        self.assertTrue(summary["shared_fork_integrity"])
        self.assertTrue(summary["latest_positive_exploratory_observation"])
        self.assertTrue(summary["cumulative_positive_exploratory_observation"])
        self.assertTrue(
            summary["first_attempt_sensitivity"][
                "latest_positive_exploratory_observation"
            ]
        )
        self.assertTrue(
            summary["first_attempt_sensitivity"][
                "cumulative_positive_exploratory_observation"
            ]
        )

        broken = copy.deepcopy(rows)
        control = next(row for row in broken if row["arm"] == "probe_only")
        control["evaluable"] = False
        degraded = summarize_results(
            manifest=manifest,
            checkpoint_summaries=checkpoints,
            results=broken,
        )
        self.assertFalse(degraded["controls_clean_unknown_empty"])
        self.assertFalse(degraded["latest_positive_exploratory_observation"])

        identical = copy.deepcopy(checkpoints)
        target_b = next(
            row
            for row in identical
            if row["trial_id"] == "target" and row["checkpoint_id"] == "S5B"
        )
        target_a = next(
            row
            for row in identical
            if row["trial_id"] == "target" and row["checkpoint_id"] == "S5A"
        )
        target_b["latest_thought_sha256"] = target_a["latest_thought_sha256"]
        identical_summary = summarize_results(
            manifest=manifest,
            checkpoint_summaries=identical,
            results=rows,
        )
        self.assertFalse(
            identical_summary["latest_positive_exploratory_observation"]
        )

    def test_partial_and_malformed_matrices_fail_without_crashing(self):
        manifest = create_manifest(master_seed=202, model="gemini-3.7-flash")
        rows = self._clean_result_matrix(manifest)
        partial = rows[:-1] + [None]
        checkpoints = self._checkpoint_matrix()
        summary = summarize_results(
            manifest=manifest,
            checkpoint_summaries=checkpoints,
            results=partial,
        )
        self.assertFalse(summary["probe_matrix_complete"])
        self.assertEqual(summary["malformed_probe_rows"], 1)
        self.assertFalse(summary["latest_positive_exploratory_observation"])
        with tempfile.TemporaryDirectory() as temporary:
            report = render_review(
                run_dir=Path(temporary),
                manifest=manifest,
                summary=summary,
                results=partial,
            )
        self.assertIn("!missing_result", report)

    def test_unevaluable_rows_render_without_none_dereference(self):
        manifest = create_manifest(master_seed=913, model="gemini-3.7-flash")
        rows = []
        order = 0
        for branch in ("S5A", "S5B"):
            for probe_id in PROBES:
                for arm in ARMS:
                    order += 1
                    rows.append(
                        {
                            "request_order": order,
                            "branch": branch,
                            "probe_id": probe_id,
                            "arm": arm,
                            "evaluable": False,
                            "outcome": "http_error",
                            "score_current": None,
                            "score_donor": None,
                        }
                    )
        summary = summarize_results(
            manifest=manifest, checkpoint_summaries=[], results=rows
        )
        with tempfile.TemporaryDirectory() as temporary:
            report = render_review(
                run_dir=Path(temporary),
                manifest=manifest,
                summary=summary,
                results=rows,
            )
        self.assertIn("!http_error", report)
        self.assertFalse(summary["generation_eligible"])
        self.assertFalse(summary["controls_clean_unknown_empty"])
        self.assertFalse(summary["latest_positive_exploratory_observation"])
        self.assertFalse(summary["cumulative_positive_exploratory_observation"])


if __name__ == "__main__":
    unittest.main()
