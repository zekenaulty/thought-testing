from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from thoughtlab.gemini_interactions import InteractionHttpResult
from thoughtlab.reasoningTraces import reasoning_trace_pilot as pilot
from thoughtlab.reasoningTraces import reasoning_trace_protocol as protocol
from thoughtlab.reasoningTraces import reasoning_trace_freeze as freeze
from thoughtlab.stateTransitions.fork_pilot import CallStore


def http_result(
    *,
    status: int = 200,
    payload: dict | None = None,
) -> InteractionHttpResult:
    value = payload if payload is not None else {}
    raw = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return InteractionHttpResult(
        http_status=status,
        payload=value,
        raw_body=raw.decode("utf-8"),
        transport_error="",
        response_parse_error="",
        elapsed_ms=1,
        raw_body_bytes=raw,
        response_headers={"x-request-id": "fixture"},
    )


def completed_text(*, signature: str, text: str) -> InteractionHttpResult:
    return http_result(
        payload={
            "status": "completed",
            "model": protocol.MODEL,
            "steps": [
                {"type": "thought", "signature": signature, "summary": []},
                {
                    "type": "model_output",
                    "content": [{"type": "text", "text": text}],
                },
            ],
            "usage": {"total_tokens": 17},
        }
    )


class ScriptedTransport:
    def __init__(
        self,
        *,
        source_a_tokens: tuple[str, ...] = ("NOT_READY", "READY"),
        source_b_tokens: tuple[str, ...] = ("READY",),
        reject_controls: bool = False,
    ) -> None:
        self.source_tokens = {
            "source_A": list(source_a_tokens),
            "source_B": list(source_b_tokens),
        }
        self.source_calls = {"source_A": 0, "source_B": 0}
        self.reject_controls = reject_controls
        self.bodies: list[dict] = []
        self.source_bodies: list[dict] = []
        self.readout_bodies: list[dict] = []
        self.execution_bodies: list[dict] = []
        self.readout_counter = 0

    @staticmethod
    def _last_user_text(body: dict) -> str:
        step = body["input"][-1]
        if step.get("type") != "user_input":
            return ""
        return "".join(
            str(block.get("text") or "")
            for block in step.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        )

    @staticmethod
    def _source_from_seed(body: dict) -> str | None:
        seed = body.get("generation_config", {}).get("seed")
        for source in protocol.SOURCE_LABELS:
            for round_number in range(1, protocol.MAX_PLANNING_ROUNDS + 1):
                if seed == protocol.derived_seed(f"{source}:round:{round_number}"):
                    return source
        return None

    @staticmethod
    def _is_control(body: dict) -> bool:
        inputs = body.get("input", [])
        if not inputs:
            return False
        last_text = ScriptedTransport._last_user_text(body)
        if last_text != protocol.BLUNT_PROBE:
            return last_text.startswith(protocol.FRESH_TASK_ANALYSIS_PROMPT)
        # A signature-only blunt readout has one or more thought steps followed
        # by the probe. Every other blunt request is one of the five controls.
        return not inputs[:-1] or any(
            step.get("type") != "thought" for step in inputs[:-1]
        )

    def __call__(self, **kwargs) -> InteractionHttpResult:
        body = copy.deepcopy(kwargs["body"])
        self.bodies.append(body)
        last_text = self._last_user_text(body)
        source = self._source_from_seed(body)
        is_source = source is not None and (
            protocol.PLANNING_CONTROLLER in last_text
            or last_text == protocol.CONTINUE_PLANNING_PROMPT
        )
        if is_source:
            self.source_bodies.append(body)
            index = self.source_calls[source]
            self.source_calls[source] += 1
            tokens = self.source_tokens[source]
            token = tokens[index] if index < len(tokens) else tokens[-1]
            return completed_text(
                signature=f"PRIVATE_{source}_ROUND_{index + 1}",
                text=token,
            )

        if last_text == protocol.EXECUTE_PROMPT:
            self.execution_bodies.append(body)
            execution_source = (
                "source_A"
                if any(
                    step.get("signature") == "PRIVATE_source_A_ROUND_2"
                    for step in body["input"]
                )
                else "source_B"
            )
            return completed_text(
                signature=f"PRIVATE_EXECUTION_{execution_source}",
                text=f"repaired artifact from {execution_source}",
            )

        self.readout_bodies.append(body)
        self.readout_counter += 1
        if self.reject_controls and self._is_control(body):
            return http_result(
                status=400,
                payload={
                    "error": {
                        "message": "synthetic request topology rejection"
                    }
                },
            )
        return completed_text(
            signature=f"PRIVATE_READOUT_{self.readout_counter}",
            text=f"semantic readout {self.readout_counter}",
        )


def make_store(path: Path, transport: ScriptedTransport) -> CallStore:
    return CallStore(
        run_dir=path,
        api_key="not-written",
        timeout=1,
        delay_seconds=0,
        transport=transport,
        max_attempts=3,
        retry_backoff_seconds=(0.0, 0.0),
        sleeper=lambda _seconds: None,
    )


def generate_fixture_sources(
    path: Path,
    transport: ScriptedTransport,
) -> tuple[CallStore, dict[str, pilot.SourceRuntime], dict]:
    store = make_store(path, transport)
    definition = protocol.build_experiment_definition()
    runtimes, generation, _signatures = pilot.generate_sources(
        definition=definition,
        system_text="SYSTEM",
        user_text="TASK",
        store=store,
        run_dir=path,
    )
    return store, runtimes, generation


def test_ready_loop_preserves_exact_history_and_cumulative_thought_carrier() -> None:
    transport = ScriptedTransport()
    with tempfile.TemporaryDirectory() as temporary:
        run_dir = Path(temporary)
        _store, runtimes, generation = generate_fixture_sources(
            run_dir, transport
        )

        assert generation["both_sources_eligible"] is True
        assert generation["source_task_inputs_identical"] is True
        assert generation["initial_requests_differ_only_by_seed"] is True
        source_a = runtimes["source_A"]
        assert source_a.summary["ready_round"] == 2
        assert [step["type"] for step in source_a.full_history] == [
            "user_input",
            "thought",
            "model_output",
            "user_input",
            "thought",
            "model_output",
        ]
        assert source_a.final_thought_steps == [
            {
                "type": "thought",
                "signature": "PRIVATE_source_A_ROUND_2",
                "summary": [],
            }
        ]
        assert source_a.cumulative_thought_steps == [
            {
                "type": "thought",
                "signature": "PRIVATE_source_A_ROUND_1",
                "summary": [],
            },
            {
                "type": "thought",
                "signature": "PRIVATE_source_A_ROUND_2",
                "summary": [],
            },
        ]
        assert source_a.summary["cumulative_thought_step_count"] == 2
        assert source_a.final_model_output_steps[0]["content"][0]["text"] == "READY"

        first_response = [
            {
                "type": "thought",
                "signature": "PRIVATE_source_A_ROUND_1",
                "summary": [],
            },
            {
                "type": "model_output",
                "content": [{"type": "text", "text": "NOT_READY"}],
            },
        ]
        expected_prefix = [
            *copy.deepcopy(transport.source_bodies[0]["input"]),
            *first_response,
        ]
        assert transport.source_bodies[1]["input"][:-1] == expected_prefix
        assert transport.source_bodies[1]["input"][-1] == protocol.user_step(
            protocol.CONTINUE_PLANNING_PROMPT
        )

        sanitized = json.dumps(generation, sort_keys=True)
        assert "PRIVATE_source_A_ROUND_1" not in sanitized
        assert "PRIVATE_source_A_ROUND_2" not in sanitized
        assert (run_dir / "source_artifacts.private.json").is_file()


def test_all_31_readouts_are_sealed_before_exact_history_continuations() -> None:
    transport = ScriptedTransport()
    with tempfile.TemporaryDirectory() as temporary:
        run_dir = Path(temporary)
        store, runtimes, _generation = generate_fixture_sources(
            run_dir, transport
        )
        definition = protocol.build_experiment_definition()
        rows, seal, _signatures = pilot.run_readouts(
            definition=definition,
            runtimes=runtimes,
            system_text="SYSTEM",
            user_text="TASK",
            store=store,
            run_dir=run_dir,
        )

        assert len(rows) == 31
        assert len(transport.readout_bodies) == 31
        assert seal["scheduled_rows"] == 31
        assert seal["attempted_rows"] == 31
        assert seal["eligible_rows"] == 31
        assert not transport.execution_bodies

        schedule = definition["schedule"]["readouts"]
        for schedule_row, body in zip(
            schedule, transport.readout_bodies, strict=True
        ):
            protocol.assert_no_function_or_tool_structure(body)
            assert "tools" not in body
            assert "tool_choice" not in body.get("generation_config", {})
            arm = schedule_row["arm"]
            source = schedule_row.get("source")
            if arm == "signature_only":
                assert body["input"][:-1] == runtimes[source].cumulative_thought_steps
                assert all(
                    step["type"] == "thought" for step in body["input"][:-1]
                )
                assert body["input"][-1]["type"] == "user_input"
                assert "system_instruction" not in body
                assert "TASK" not in json.dumps(body)
                assert "READY" not in json.dumps(body["input"][:-1])
            elif arm == "full_prefix":
                assert body["input"][:-1] == runtimes[source].full_history
                assert body["system_instruction"] == "SYSTEM"
            elif arm == "visible_ready_only":
                assert body["input"][:-1] == runtimes[source].final_model_output_steps
                assert [step["type"] for step in body["input"]] == [
                    "model_output",
                    "user_input",
                ]
            elif arm == "probe_only":
                assert len(body["input"]) == 1
            elif arm == "task_only":
                assert len(body["input"]) == 1
                assert "TASK" in json.dumps(body)

        calls_at_seal = len(store.records)
        continuations, _ = pilot.run_continuations(
            definition=definition,
            runtimes=runtimes,
            system_text="SYSTEM",
            readout_rows=rows,
            readout_seal=seal,
            store=store,
            run_dir=run_dir,
        )
        assert len(continuations) == 2
        assert all(row["eligible"] for row in continuations)
        assert len(transport.execution_bodies) == 2
        assert len(store.records) == calls_at_seal + 2
        for body in transport.execution_bodies:
            source = next(
                label
                for label, runtime in runtimes.items()
                if body["input"][:-1] == runtime.full_history
            )
            assert body["input"][:-1] == runtimes[source].full_history
            assert body["input"][-1] == protocol.user_step(protocol.EXECUTE_PROMPT)
            assert body["system_instruction"] == "SYSTEM"
            assert "semantic readout" not in json.dumps(body)
            protocol.assert_no_function_or_tool_structure(body)


def test_invalid_controls_are_unavailable_and_never_scored_as_zero() -> None:
    transport = ScriptedTransport(reject_controls=True)
    with tempfile.TemporaryDirectory() as temporary:
        run_dir = Path(temporary)
        store, runtimes, generation = generate_fixture_sources(run_dir, transport)
        definition = protocol.build_experiment_definition()
        rows, seal, _ = pilot.run_readouts(
            definition=definition,
            runtimes=runtimes,
            system_text="SYSTEM",
            user_text="TASK",
            store=store,
            run_dir=run_dir,
        )
        controls = [row for row in rows if row["arm"] != "signature_only"]
        primary = [row for row in rows if row["arm"] == "signature_only"]

        assert len(primary) == 26
        assert all(row["eligible"] for row in primary)
        assert len(controls) == 5
        assert all(row["outcome"] == "http_400_protocol_rejected" for row in controls)
        assert all(row["unavailable"] for row in controls)
        assert all(row["scientific_score"] is None for row in controls)
        assert all(row["call"]["attempt_count"] == 1 for row in controls)

        continuations, _ = pilot.run_continuations(
            definition=definition,
            runtimes=runtimes,
            system_text="SYSTEM",
            readout_rows=rows,
            readout_seal=seal,
            store=store,
            run_dir=run_dir,
        )
        summary = pilot.build_summary(
            freeze_id="a" * 64,
            generation=generation,
            readouts=rows,
            continuations=continuations,
            readout_seal=seal,
            store=store,
        )
        assert summary["readouts"]["unavailable"] == 5
        assert summary["semantic_adjudication"][
            "invalid_or_unavailable_cells_excluded_not_scored_zero"
        ] is True
        for cell in summary["readouts"]["controls_by_arm"].values():
            assert cell["score"] is None
        assert '"score": 0' not in json.dumps(summary)


def test_source_round_limit_exhaustion_is_retained_without_replacement() -> None:
    transport = ScriptedTransport(
        source_a_tokens=("NOT_READY",),
        source_b_tokens=("NOT_READY",),
    )
    with tempfile.TemporaryDirectory() as temporary:
        _store, runtimes, generation = generate_fixture_sources(
            Path(temporary), transport
        )

        assert generation["eligible_sources"] == 0
        assert len(transport.source_bodies) == 6
        assert all(not runtime.eligible for runtime in runtimes.values())
        assert all(runtime.summary["rounds_attempted"] == 3 for runtime in runtimes.values())
        assert all(
            runtime.summary["ineligibility_reasons"]
            == ["planning_round_limit_exhausted_without_READY"]
            for runtime in runtimes.values()
        )


def test_boundary_normalization_is_whitespace_only_and_not_json_or_markdown() -> None:
    accepted = pilot.evaluate_response(
        result=completed_text(signature="secret", text=" \r\nREADY\t"),
        require_source_boundary=True,
    )
    fenced = pilot.evaluate_response(
        result=completed_text(signature="secret", text="```READY```"),
        require_source_boundary=True,
    )
    json_value = pilot.evaluate_response(
        result=completed_text(signature="secret", text='{"status":"READY"}'),
        require_source_boundary=True,
    )

    assert accepted.eligible is True
    assert accepted.boundary_token == "READY"
    assert fenced.eligible is False
    assert json_value.eligible is False


def test_source_rejects_missing_signature_and_function_step() -> None:
    missing_signature = http_result(
        payload={
            "status": "completed",
            "model": protocol.MODEL,
            "steps": [
                {"type": "thought", "summary": []},
                {
                    "type": "model_output",
                    "content": [{"type": "text", "text": "READY"}],
                },
            ],
        }
    )
    forbidden = http_result(
        payload={
            "status": "completed",
            "model": protocol.MODEL,
            "steps": [
                {"type": "thought", "signature": "secret", "summary": []},
                {"type": "function_call", "name": "do_not_call"},
                {
                    "type": "model_output",
                    "content": [{"type": "text", "text": "READY"}],
                },
            ],
        }
    )

    first = pilot.evaluate_response(
        result=missing_signature,
        require_source_boundary=True,
    )
    second = pilot.evaluate_response(
        result=forbidden,
        require_source_boundary=True,
    )
    assert first.eligible is False
    assert any("no nonempty signature" in reason for reason in first.reasons)
    assert second.eligible is False
    assert any("function_call" in reason for reason in second.reasons)


def test_readout_seal_tampering_blocks_continuation_before_transport() -> None:
    transport = ScriptedTransport()
    with tempfile.TemporaryDirectory() as temporary:
        run_dir = Path(temporary)
        store, runtimes, _generation = generate_fixture_sources(run_dir, transport)
        definition = protocol.build_experiment_definition()
        rows, seal, _ = pilot.run_readouts(
            definition=definition,
            runtimes=runtimes,
            system_text="SYSTEM",
            user_text="TASK",
            store=store,
            run_dir=run_dir,
        )
        calls_before = len(store.records)
        tampered = copy.deepcopy(seal)
        tampered["private_file_bytes_sha256"] = "0" * 64

        with pytest.raises(RuntimeError, match="seal verification failed"):
            pilot.run_continuations(
                definition=definition,
                runtimes=runtimes,
                system_text="SYSTEM",
                readout_rows=rows,
                readout_seal=tampered,
                store=store,
                run_dir=run_dir,
            )
        assert len(store.records) == calls_before
        assert not transport.execution_bodies


def test_full_history_drift_blocks_continuation_before_transport() -> None:
    transport = ScriptedTransport()
    with tempfile.TemporaryDirectory() as temporary:
        run_dir = Path(temporary)
        store, runtimes, _generation = generate_fixture_sources(run_dir, transport)
        definition = protocol.build_experiment_definition()
        rows, seal, _ = pilot.run_readouts(
            definition=definition,
            runtimes=runtimes,
            system_text="SYSTEM",
            user_text="TASK",
            store=store,
            run_dir=run_dir,
        )
        calls_before = len(store.records)
        runtimes["source_A"].full_history[0]["content"][0]["text"] = "DRIFTED"

        with pytest.raises(RuntimeError, match="history changed before continuation"):
            pilot.run_continuations(
                definition=definition,
                runtimes=runtimes,
                system_text="SYSTEM",
                readout_rows=rows,
                readout_seal=seal,
                store=store,
                run_dir=run_dir,
            )
        assert len(store.records) == calls_before
        assert not transport.execution_bodies


def test_signature_containment_guard_and_interruption_terminalization() -> None:
    with pytest.raises(RuntimeError, match="raw thought signature"):
        pilot._assert_no_raw_signatures(
            {"accidental": "PRIVATE_SIGNATURE"}, ["PRIVATE_SIGNATURE"]
        )

    with tempfile.TemporaryDirectory() as temporary:
        output_dir = Path(temporary)
        ledger = {"freeze_id": "b" * 64}
        assert pilot._terminalize(
            output_dir=output_dir,
            ledger=ledger,
            phase="readouts",
            exc=RuntimeError("sensitive details are not persisted"),
            store=None,
        ) is True
        stored = json.loads((output_dir / "execution_ledger.json").read_text())
        interruption = json.loads(
            (output_dir / "execution_interrupted.json").read_text()
        )
        assert stored["terminal_for_consumed_freeze"] is True
        assert stored["replacement_generation_permitted"] is False
        assert interruption["replacement_permitted"] is False
        assert "sensitive details" not in json.dumps(interruption)


def test_invalid_reviewed_freeze_fails_before_task_read_or_output_claim() -> None:
    fake_freeze = SimpleNamespace(
        verify_freeze=lambda **_kwargs: {
            "valid": False,
            "errors": ["synthetic invalid freeze"],
        }
    )
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        freeze_dir = root / "freeze"
        freeze_dir.mkdir()
        with patch.object(pilot, "_freeze_api", return_value=fake_freeze), patch.object(
            protocol,
            "verify_selected_task",
            side_effect=AssertionError("task must not be read"),
        ):
            with pytest.raises(ValueError, match="synthetic invalid freeze"):
                pilot.execute_reviewed_freeze(
                    repo_root=root,
                    freeze_dir=freeze_dir,
                    expected_freeze_id="c" * 64,
                    api_key="unused",
                    transport=lambda **_kwargs: (_ for _ in ()).throw(
                        AssertionError("transport must not run")
                    ),
                )
        assert not (root / "results").exists()


def test_reviewed_freeze_is_consumed_once_and_terminalizes_complete_run() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    private_results = repo_root / "results"
    private_results.mkdir(exist_ok=True)
    transport = ScriptedTransport()
    with tempfile.TemporaryDirectory(dir=private_results) as temporary:
        temporary_root = Path(temporary)
        freeze_dir = temporary_root / "freeze"
        prepared = freeze.prepare_freeze(
            repo_root=repo_root,
            freeze_dir=freeze_dir,
        )
        output_dir = temporary_root / "consumed"
        with patch.object(
            pilot,
            "execution_output_dir",
            return_value=output_dir,
        ):
            ledger = pilot.execute_reviewed_freeze(
                repo_root=repo_root,
                freeze_dir=freeze_dir,
                expected_freeze_id=prepared["freeze_id"],
                api_key="not-written",
                transport=transport,
                sleeper=lambda _seconds: None,
            )
            calls_after_completion = len(transport.bodies)
            with pytest.raises(FileExistsError):
                pilot.execute_reviewed_freeze(
                    repo_root=repo_root,
                    freeze_dir=freeze_dir,
                    expected_freeze_id=prepared["freeze_id"],
                    api_key="not-written",
                    transport=transport,
                    sleeper=lambda _seconds: None,
                )

        assert ledger["final_status"] == "evidence_collection_complete"
        assert ledger["terminal_for_consumed_freeze"] is True
        assert ledger["all_readouts_sealed_before_continuation"] is True
        assert ledger["logical_requests"] == 36
        assert len(transport.bodies) == calls_after_completion
        assert (output_dir / "frozen_protocol" / freeze.FREEZE_LOCK_NAME).is_file()
        assert (output_dir / "raw" / "call_index.json").is_file()
        assert (output_dir / "readout_seal.json").is_file()
        summary_text = (output_dir / "summary.json").read_text(encoding="utf-8")
        assert "PRIVATE_source_A_ROUND_2" not in summary_text
        assert "semantic readout 1" not in summary_text
