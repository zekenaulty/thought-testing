import copy
import json
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from thoughtlab.gemini_generate_content import (
    GenerateContentHttpResult,
    decode_generate_content_bytes,
)
from thoughtlab.raw_call_store import RawCallStore as CallStore
from thoughtlab.reasoningEngineering import modernization_pilot as pilot
from thoughtlab.reasoningEngineering import modernization_protocol as protocol


REPO_ROOT = Path(__file__).resolve().parents[1]


def http_result(*, payload: dict, status: int = 200) -> GenerateContentHttpResult:
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return GenerateContentHttpResult(
        http_status=status,
        payload=payload,
        raw_body=raw.decode("utf-8"),
        transport_error="",
        response_parse_error="",
        elapsed_ms=1,
        raw_body_bytes=raw,
        response_headers={"x-request-id": "fixture"},
    )


def planning_result(
    *,
    text: str | None = "READY",
    signature: str | None = "secret",
    include_candidates: bool = True,
    finish_reason: str | None = "STOP",
) -> GenerateContentHttpResult:
    payload: dict = {
        "modelVersion": protocol.MODEL,
        "usageMetadata": {
            "totalTokenCount": 64,
            "candidatesTokenCount": len(text or ""),
            "thoughtsTokenCount": 60,
        },
    }
    if include_candidates:
        part: dict = {"text": text or ""}
        if signature is not None:
            part["thoughtSignature"] = signature
        candidate: dict = {
            "content": {"role": "model", "parts": [part]},
        }
        if finish_reason is not None:
            candidate["finishReason"] = finish_reason
        payload["candidates"] = [candidate]
    return http_result(payload=payload)


class ScriptedTransport:
    def __init__(self, results: list[GenerateContentHttpResult]) -> None:
        self.results = list(results)
        self.bodies: list[dict] = []

    def __call__(self, **kwargs) -> GenerateContentHttpResult:
        self.bodies.append(copy.deepcopy(kwargs["body"]))
        if not self.results:
            raise AssertionError("scripted transport was exhausted")
        return self.results.pop(0)


def make_store(path: Path, transport: ScriptedTransport) -> CallStore:
    return CallStore(
        run_dir=path,
        api_key="not-written",
        timeout=1,
        delay_seconds=0,
        transport=transport,
        max_attempts=3,
        retry_backoff_seconds=protocol.RETRY_BACKOFF_SECONDS,
        request_target=pilot._canonical_request_target(),
        sleeper=lambda _seconds: None,
    )


def test_cli_byte_digest_uses_exact_file_bytes(capsys) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        artifact = Path(temporary) / "seal.json"
        artifact.write_bytes(b'{"spacing":  true}\r\n')

        pilot._print_file_byte_digest(artifact)

        assert capsys.readouterr().out.strip() == (
            "sha256_bytes=" + protocol.sha256_bytes(artifact.read_bytes())
        )


@pytest.mark.parametrize(
    "argv",
    [
        [
            "seal-intervention",
            "--intervention-dir",
            "intervention",
            "--phase-one-seal",
            "phase_one_seal.json",
        ],
        [
            "close-no-target",
            "--phase-one-seal",
            "phase_one_seal.json",
            "--note",
            "note.md",
        ],
        [
            "verify-no-target",
            "--phase-one-seal",
            "phase_one_seal.json",
        ],
    ],
)
def test_human_terminal_cli_requires_reviewed_freeze_binding(
    argv: list[str],
) -> None:
    with pytest.raises(SystemExit):
        pilot._parser().parse_args(argv)


def build_valid_phase_one_archive(
    root: Path, *, freeze_id: str = "a" * 64
) -> tuple[pilot.PlanningPhaseRuntime, dict]:
    claim_id = "ID_0123456789ABCDEFGHJKMNPQRS"
    claim_path = root / pilot.PHASE_ONE_CLAIM_FILE
    pilot.write_json(
        claim_path,
        {
            "schema_version": "modernization_phase_one_consumption_claim_v1",
            "freeze_id": freeze_id,
            "claim_id": claim_id,
            "claimed_at": pilot.utc_now(),
            "status": "CLAIMED",
        },
    )
    transport = ScriptedTransport(
        [
            planning_result(
                text="READY", signature="BASELINE_PRIVATE_SIGNATURE"
            ),
            planning_result(
                text="The plan has stabilized around a bounded staged course.",
                signature="OBSERVATION_PRIVATE_SIGNATURE",
            ),
        ]
    )
    store = make_store(root, transport)
    runtime = pilot.run_planning_phase(
        phase="baseline",
        first_body=protocol.initial_planning_body(task_text="TASK"),
        max_turns=1,
        store=store,
        run_dir=root,
    )
    rows, observation_seal = pilot.run_inspections(
        runtime=runtime,
        store=store,
        run_dir=root,
    )
    planning_private = root / "baseline_planning.private.json"
    observation_private = root / "baseline_observations.private.json"
    review_path = root / "PHASE_ONE_REVIEW.md"
    pilot.write_text(
        review_path,
        pilot._phase_review_markdown(runtime=runtime, observations=rows),
    )
    for name, template_text in pilot.INTERVENTION_TEMPLATE_TEXT.items():
        pilot.write_text(root / "intervention" / name, template_text)
    call_records = pilot._validate_call_index(root)
    seal = {
        "schema_version": "modernization_phase_one_seal_v1",
        "freeze_id": freeze_id,
        "created_at": pilot.utc_now(),
        "planning_summary_sha256": protocol.sha256_json(runtime.public_summary),
        "observation_seal_sha256": protocol.sha256_json(observation_seal),
        "baseline_planning_private_bytes_sha256": protocol.sha256_bytes(
            planning_private.read_bytes()
        ),
        "baseline_observations_private_bytes_sha256": protocol.sha256_bytes(
            observation_private.read_bytes()
        ),
        "ready_checkpoint_id": runtime.ready_checkpoint.checkpoint_id,
        "phase_two_requires_sealed_intervention": True,
        "phase_one_claim_id": claim_id,
        "phase_one_claim_bytes_sha256": protocol.sha256_bytes(
            claim_path.read_bytes()
        ),
        "phase_one_terminal": "READY_OBSERVATION_ELIGIBLE",
        "ready_observation_eligible": True,
        "intervention_authorized": True,
        "phase_one_call_index_prefix_sha256": protocol.sha256_json(
            call_records
        ),
        "phase_one_call_index_bytes_sha256": protocol.sha256_bytes(
            (root / "raw" / "call_index.json").read_bytes()
        ),
        "phase_one_physical_call_count": len(call_records),
        "phase_one_raw_inventory": pilot._raw_inventory(root),
        "phase_one_artifact_inventory": pilot._artifact_inventory(
            run_dir=root, relative_paths=pilot.PHASE_ONE_ARTIFACT_PATHS
        ),
        "phase_one_review_bytes_sha256": protocol.sha256_bytes(
            review_path.read_bytes()
        ),
        "baseline_task_sha256": protocol.sha256_text("TASK"),
    }
    seal_path = root / "phase_one_seal.json"
    pilot.write_json(seal_path, seal)
    pilot.write_json(
        root / pilot.PHASE_ONE_TERMINAL_FILE,
        {
            "schema_version": "modernization_phase_one_consumption_terminal_v1",
            "freeze_id": freeze_id,
            "claim_id": claim_id,
            "claim_bytes_sha256": protocol.sha256_bytes(claim_path.read_bytes()),
            "status": "COMPLETED",
            "terminal_at": pilot.utc_now(),
            "error_type": None,
            "phase_one_seal_sha256": protocol.sha256_bytes(
                seal_path.read_bytes()
            ),
        },
    )
    return runtime, seal


def rebind_phase_one_claim(root: Path) -> None:
    terminal_path = root / pilot.PHASE_ONE_TERMINAL_FILE
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    terminal["phase_one_seal_sha256"] = protocol.sha256_bytes(
        (root / "phase_one_seal.json").read_bytes()
    )
    pilot.write_json(terminal_path, terminal)


def create_sealed_intervention(
    root: Path, *, freeze_id: str = "a" * 64
) -> Path:
    intervention_dir = root / "intervention"
    intervention_dir.mkdir(exist_ok=True)
    (intervention_dir / "diagnosis.md").write_text(
        "The plan relies too heavily on an unbounded authority interpretation.",
        encoding="utf-8",
    )
    (intervention_dir / "prediction.md").write_text(
        "Governance sequencing should change while integrity controls remain.",
        encoding="utf-8",
    )
    (intervention_dir / "intervention.txt").write_text(
        "Re-examine the scope and enforceability of the authority relied upon. "
        "Preserve conclusions that remain justified.",
        encoding="utf-8",
    )
    pilot.seal_intervention_package(
        intervention_dir=intervention_dir,
        phase_one_seal_path=root / "phase_one_seal.json",
        expected_freeze_id=freeze_id,
        expected_task_text="TASK",
        expected_run_dir=root,
    )
    return intervention_dir


def build_completed_phase_two_archive(
    repo_root: Path,
    *,
    freeze_id: str,
    monkeypatch: pytest.MonkeyPatch,
    first_execution_finish_reason: str | None = None,
) -> Path:
    run_dir = repo_root / "results" / "reasoning_engineering" / freeze_id
    run_dir.mkdir(parents=True)
    build_valid_phase_one_archive(run_dir, freeze_id=freeze_id)
    intervention_dir = create_sealed_intervention(run_dir, freeze_id=freeze_id)
    results = [
        planning_result(text="READY", signature="ADJUSTED_READY_SIGNATURE"),
        planning_result(
            text="Adjusted integrated decision observation",
            signature="ADJUSTED_OBSERVATION_SIGNATURE",
        ),
    ]
    results.extend(
        planning_result(
            text=f"Executive recovery memorandum {index}",
            signature=f"EXECUTION_SIGNATURE_{index}",
            finish_reason=(first_execution_finish_reason if index == 0 else None),
        )
        for index in range(protocol.EXECUTION_REPLICATES_PER_CHECKPOINT * 2)
    )
    monkeypatch.setattr(
        pilot,
        "_load_verified_definition",
        lambda **_kwargs: {"dossier": {"assembled_task_text": "TASK"}},
    )
    monkeypatch.setattr(
        pilot,
        "_assert_private_output_root",
        lambda **_kwargs: None,
    )
    pilot.execute_phase_two(
        repo_root=repo_root,
        freeze_dir=repo_root,
        freeze_id=freeze_id,
        intervention_dir=intervention_dir,
        api_key="unused",
        transport=ScriptedTransport(results),
    )
    return run_dir


def rebind_phase_two_nonraw_inventory(run_dir: Path) -> None:
    phase_two_seal_path = run_dir / pilot.PHASE_TWO_SEAL_FILE
    phase_two_seal = json.loads(phase_two_seal_path.read_text(encoding="utf-8"))
    phase_two_seal["artifact_inventory"] = pilot._nonraw_inventory(
        run_dir=run_dir,
        excluded={pilot.PHASE_TWO_SEAL_FILE, pilot.PHASE_TWO_TERMINAL_FILE},
    )
    pilot.write_json(phase_two_seal_path, phase_two_seal)
    terminal_path = run_dir / pilot.PHASE_TWO_TERMINAL_FILE
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    terminal["phase_two_seal_sha256"] = protocol.sha256_bytes(
        phase_two_seal_path.read_bytes()
    )
    pilot.write_json(terminal_path, terminal)


@pytest.mark.parametrize(
    ("text", "expected_observation", "expected_action"),
    [
        ("READY", protocol.READY, pilot.ACTION_FREEZE_READY),
        (" \r\nREADY\t", protocol.READY, pilot.ACTION_FREEZE_READY),
        ("NOT_READY", protocol.SELF_DECLARED_NOT_READY, pilot.ACTION_CONTINUE),
        ('{"status":"READY"}', protocol.INVALID_STATUS, pilot.ACTION_CONTINUE),
        ("```READY```", protocol.INVALID_STATUS, pilot.ACTION_CONTINUE),
        ("READY.", protocol.INVALID_STATUS, pilot.ACTION_CONTINUE),
        ("ready", protocol.INVALID_STATUS, pilot.ACTION_CONTINUE),
        ("", protocol.INVALID_STATUS, pilot.ACTION_CONTINUE),
    ],
)
def test_completed_raw_ready_is_the_only_ready_observation(
    text: str, expected_observation: str, expected_action: str
) -> None:
    evaluated = pilot.evaluate_planning_turn(planning_result(text=text))

    assert evaluated.readiness_observation == expected_observation
    assert evaluated.controller_action == expected_action
    assert evaluated.carrier_replayable is True


@pytest.mark.parametrize(
    "parts",
    [
        [
            {"text": "REA", "thoughtSignature": "secret"},
            {"text": "DY"},
        ],
        [
            {"text": "NOT_", "thoughtSignature": "secret"},
            {"text": "READY"},
        ],
    ],
)
def test_completed_boundary_requires_exactly_one_visible_text_part(
    parts: list[dict],
) -> None:
    evaluated = pilot.evaluate_planning_turn(
        http_result(
            payload={
                "modelVersion": protocol.MODEL,
                "candidates": [
                    {
                        "content": {"role": "model", "parts": parts},
                        "finishReason": "STOP",
                    }
                ],
            }
        )
    )

    assert evaluated.normalized_visible_text in {"READY", "NOT_READY"}
    assert evaluated.readiness_observation == protocol.INVALID_STATUS
    assert evaluated.controller_action == pilot.ACTION_CONTINUE
    assert evaluated.carrier_replayable is True
    assert any("exactly one" in reason for reason in evaluated.reasons)


@pytest.mark.parametrize("partial", ["READY", "NOT_READY", "Here", "", None])
def test_incomplete_overrides_partial_visible_status_or_noise(
    partial: str | None,
) -> None:
    evaluated = pilot.evaluate_planning_turn(
        planning_result(
            text=partial,
            signature="truncated-secret",
            finish_reason="MAX_TOKENS",
        )
    )

    assert evaluated.readiness_observation == protocol.UNOBSERVED_TRUNCATED
    assert evaluated.controller_action == pilot.ACTION_CONTINUE
    assert evaluated.carrier_replayable is True
    assert evaluated.explicit_finish_reasons == ["MAX_TOKENS"]


def test_output_budget_finish_reason_continues() -> None:
    evaluated = pilot.evaluate_planning_turn(
        planning_result(
            text="READY",
            signature="truncated-secret",
            finish_reason="MAX_TOKENS",
        )
    )

    assert evaluated.readiness_observation == protocol.UNOBSERVED_TRUNCATED
    assert evaluated.controller_action == pilot.ACTION_CONTINUE
    assert evaluated.carrier_replayable is True


def test_missing_finish_reason_terminates_technically() -> None:
    evaluated = pilot.evaluate_planning_turn(
        planning_result(
            text="READY",
            signature="signed-but-finish-unobserved",
            finish_reason=None,
        )
    )

    assert evaluated.readiness_observation is None
    assert evaluated.controller_action == pilot.ACTION_TERMINATE_TECHNICAL
    assert evaluated.carrier_replayable is True
    assert any("missing or unsupported" in reason for reason in evaluated.reasons)


@pytest.mark.parametrize("finish_reason", ["SAFETY", "CONTENT_FILTER"])
def test_explicit_non_token_finish_reason_terminates_technically(
    finish_reason: str,
) -> None:
    evaluated = pilot.evaluate_planning_turn(
        planning_result(
            text="READY",
            signature="signed-but-not-token-truncated",
            finish_reason=finish_reason,
        )
    )

    assert evaluated.readiness_observation is None
    assert evaluated.controller_action == pilot.ACTION_TERMINATE_TECHNICAL
    assert evaluated.carrier_replayable is True
    assert any("missing or unsupported" in reason for reason in evaluated.reasons)


@pytest.mark.parametrize(
    ("finish_reason", "expected_observation", "expected_action"),
    [
        ("MAX_TOKENS", protocol.UNOBSERVED_TRUNCATED, pilot.ACTION_CONTINUE),
        ("SAFETY", None, pilot.ACTION_TERMINATE_TECHNICAL),
        ("CONTENT_FILTER", None, pilot.ACTION_TERMINATE_TECHNICAL),
    ],
)
def test_non_stop_finish_reason_never_promotes_visible_ready(
    finish_reason: str,
    expected_observation: str | None,
    expected_action: str,
) -> None:
    evaluated = pilot.evaluate_planning_turn(
        planning_result(
            text="READY",
            signature="non-stop-signed-carrier",
            finish_reason=finish_reason,
        )
    )

    assert evaluated.readiness_observation == expected_observation
    assert evaluated.controller_action == expected_action
    assert evaluated.carrier_replayable is True


def test_completed_stop_with_exact_ready_remains_ready() -> None:
    evaluated = pilot.evaluate_planning_turn(
        planning_result(
            text="READY",
            signature="ordinary-stop",
            finish_reason="STOP",
        )
    )

    assert evaluated.readiness_observation == protocol.READY
    assert evaluated.controller_action == pilot.ACTION_FREEZE_READY


@pytest.mark.parametrize(
    "parts",
    [
        [
            {
                "text": "readable thought summary",
                "thought": True,
                "thoughtSignature": "secret",
            },
            {"text": "READY"},
        ],
        [
            {
                "text": "READY",
                "thoughtSignature": "secret",
                "readable_metadata": "ordinary task context",
            },
        ],
    ],
)
def test_unexpected_readable_carrier_fields_terminate_technically(
    parts: list[dict],
) -> None:
    evaluated = pilot.evaluate_planning_turn(
        http_result(
            payload={
                "modelVersion": protocol.MODEL,
                "candidates": [
                    {
                        "content": {"role": "model", "parts": parts},
                        "finishReason": "STOP",
                    }
                ],
            }
        )
    )

    assert evaluated.controller_action == pilot.ACTION_TERMINATE_TECHNICAL
    assert evaluated.carrier_replayable is False
    assert any("safely isolatable" in reason for reason in evaluated.reasons)


def test_max_tokens_without_replayable_signed_content_terminates_technically() -> None:
    evaluated = pilot.evaluate_planning_turn(
        planning_result(
            text="partial",
            signature=None,
            finish_reason="MAX_TOKENS",
        )
    )

    assert evaluated.readiness_observation == protocol.UNOBSERVED_TRUNCATED
    assert evaluated.carrier_replayable is False
    assert evaluated.controller_action == pilot.ACTION_TERMINATE_TECHNICAL
    assert any("no signed Part carrier" in reason for reason in evaluated.reasons)


def test_truncated_then_ready_replays_exact_signed_checkpoint_and_promotes_later() -> None:
    transport = ScriptedTransport(
        [
            planning_result(
                text="Here",
                signature="PRIVATE_TRUNCATED_SIGNATURE",
                finish_reason="MAX_TOKENS",
            ),
            planning_result(text="READY", signature="PRIVATE_READY_SIGNATURE"),
        ]
    )
    with tempfile.TemporaryDirectory() as temporary:
        run_dir = Path(temporary)
        runtime = pilot.run_planning_phase(
            phase="baseline",
            first_body=protocol.initial_planning_body(task_text="TASK"),
            max_turns=2,
            store=make_store(run_dir, transport),
            run_dir=run_dir,
        )

        assert runtime.terminal == "COMPLETED_READY_CHECKPOINT"
        assert runtime.ready_checkpoint is runtime.checkpoints[1]
        assert runtime.checkpoints[0].readiness_observation == (
            protocol.UNOBSERVED_TRUNCATED
        )
        assert runtime.checkpoints[1].readiness_observation == protocol.READY
        assert transport.bodies[1]["contents"][:-1] == (
            runtime.checkpoints[0].full_history
        )
        assert transport.bodies[1]["contents"][-1] == protocol.user_step(
            protocol.CONTINUE_PLANNING_PROMPT
        )
        assert any(
            part.get("thoughtSignature") == "PRIVATE_TRUNCATED_SIGNATURE"
            for content in transport.bodies[1]["contents"]
            for part in content.get("parts", [])
        )
        public = (run_dir / "baseline_planning_summary.json").read_text(
            encoding="utf-8"
        )
        assert "PRIVATE_TRUNCATED_SIGNATURE" not in public
        assert "PRIVATE_READY_SIGNATURE" not in public


@pytest.mark.parametrize(
    ("result", "classification"),
    [
        (
            planning_result(text="NOT_READY", signature="self-not-ready"),
            protocol.SELF_DECLARED_NOT_READY,
        ),
        (
            planning_result(
                text="READY",
                signature="truncated",
                finish_reason="MAX_TOKENS",
            ),
            protocol.UNOBSERVED_TRUNCATED,
        ),
        (
            planning_result(text="READY.", signature="invalid"),
            protocol.INVALID_STATUS,
        ),
    ],
)
def test_threshold_reached_preserves_last_turn_classification(
    result: GenerateContentHttpResult, classification: str
) -> None:
    transport = ScriptedTransport([result])
    with tempfile.TemporaryDirectory() as temporary:
        run_dir = Path(temporary)
        runtime = pilot.run_planning_phase(
            phase="baseline",
            first_body=protocol.initial_planning_body(task_text="TASK"),
            max_turns=1,
            store=make_store(run_dir, transport),
            run_dir=run_dir,
        )

    assert runtime.terminal == protocol.PLANNING_THRESHOLD_REACHED
    assert runtime.last_turn_classification == classification
    assert runtime.ready_checkpoint is None


def test_2xx_incomplete_is_not_retried_or_synthetically_repaired() -> None:
    transport = ScriptedTransport(
        [
            planning_result(
                text="Here",
                signature="incomplete-once",
                finish_reason="MAX_TOKENS",
            )
        ]
    )
    with tempfile.TemporaryDirectory() as temporary:
        store = make_store(Path(temporary), transport)
        result, record = store.invoke_logical(
            label="incomplete",
            body=protocol.initial_planning_body(task_text="TASK"),
        )

    assert result.payload["candidates"][0]["finishReason"] == "MAX_TOKENS"
    assert record["attempt_count"] == 1
    assert len(transport.bodies) == 1


def test_raw_binder_reconstructs_retry_span_and_selected_response() -> None:
    first_payload = planning_result(
        text="retryable", signature="RETRY_SIGNATURE"
    ).payload
    first = http_result(payload=first_payload, status=503)
    transport = ScriptedTransport(
        [first, planning_result(text="READY", signature="SELECTED_SIGNATURE")]
    )
    with tempfile.TemporaryDirectory() as temporary:
        run_dir = Path(temporary)
        store = make_store(run_dir, transport)
        body = protocol.initial_planning_body(task_text="TASK")
        _result, logical = store.invoke_logical(
            label="baseline_planning_turn_1", body=body
        )
        cursor = pilot.PhysicalCallCursor(
            records=pilot._validate_call_index(run_dir),
            next_call_number=1,
            logical_paths_used=set(),
        )
        rebound = pilot._bound_generate_content_result(
            run_dir=run_dir,
            call_summary=pilot._safe_call_summary(logical),
            expected_label="baseline_planning_turn_1",
            expected_body=body,
            call_cursor=cursor,
        )

        assert (
            rebound.payload["candidates"][0]["content"]["parts"][0]["text"]
            == "READY"
        )
        assert cursor.next_call_number == 3
        assert logical["selection_reason"] == "first_nonretryable_after_retry"

        logical_path = run_dir / "raw" / "logical_baseline_planning_turn_1.metadata.json"
        tampered = json.loads(logical_path.read_text(encoding="utf-8"))
        tampered["selected_response_wire_sha256"] = "f" * 64
        pilot.write_json(logical_path, tampered)
        with pytest.raises(ValueError, match="selection or timing"):
            pilot._bound_generate_content_result(
                run_dir=run_dir,
                call_summary=pilot._safe_call_summary(tampered),
                expected_label="baseline_planning_turn_1",
                expected_body=body,
                call_cursor=pilot.PhysicalCallCursor(
                    records=pilot._validate_call_index(run_dir),
                    next_call_number=1,
                    logical_paths_used=set(),
                ),
            )


@pytest.mark.parametrize(
    ("http_status", "partial_bytes"),
    [(None, b""), (200, b'{"partial"')],
)
def test_raw_binder_reconstructs_exhausted_transport_errors(
    http_status: int | None, partial_bytes: bytes
) -> None:
    def transport_error_result() -> GenerateContentHttpResult:
        return GenerateContentHttpResult(
            http_status=http_status,
            payload=None,
            raw_body=partial_bytes.decode("utf-8"),
            transport_error="IncompleteRead: partial response body",
            response_parse_error="",
            elapsed_ms=1,
            raw_body_bytes=partial_bytes,
            response_headers={},
        )

    transport = ScriptedTransport(
        [transport_error_result() for _index in range(3)]
    )
    with tempfile.TemporaryDirectory() as temporary:
        run_dir = Path(temporary)
        store = make_store(run_dir, transport)
        body = protocol.initial_planning_body(task_text="TASK")
        _result, logical = store.invoke_logical(
            label="baseline_planning_turn_1", body=body
        )
        cursor = pilot.PhysicalCallCursor(
            records=pilot._validate_call_index(run_dir),
            next_call_number=1,
            logical_paths_used=set(),
        )
        rebound = pilot._bound_generate_content_result(
            run_dir=run_dir,
            call_summary=pilot._safe_call_summary(logical),
            expected_label="baseline_planning_turn_1",
            expected_body=body,
            call_cursor=cursor,
        )

        assert rebound.payload is None
        assert rebound.transport_error.startswith("IncompleteRead")
        assert logical["selection_reason"] == "retry_budget_exhausted"
        assert cursor.next_call_number == 4


def test_truncated_checkpoint_is_inspection_eligible_but_not_execution_parent() -> None:
    checkpoint = pilot.CheckpointRuntime(
        checkpoint_id="ID_0123456789ABCDEFGHJKMNPQRS",
        phase="baseline",
        turn_number=1,
        readiness_observation=protocol.UNOBSERVED_TRUNCATED,
        provider_status="incomplete",
        full_history=[
            protocol.user_step("TASK"),
            {
                "role": "model",
                "parts": [
                    {"text": "Here", "thoughtSignature": "SECRET"}
                ],
            },
        ],
        response_steps=[
            {
                "role": "model",
                "parts": [
                    {"text": "Here", "thoughtSignature": "SECRET"}
                ],
            },
        ],
        summary={},
    )
    runtime = pilot.PlanningPhaseRuntime(
        phase="baseline",
        checkpoints=[checkpoint],
        ready_checkpoint=None,
        terminal=protocol.PLANNING_THRESHOLD_REACHED,
        last_turn_classification=protocol.UNOBSERVED_TRUNCATED,
        public_summary={},
    )
    transport = ScriptedTransport(
        [planning_result(text="Recovered integrated decision state", signature="readout")]
    )
    with tempfile.TemporaryDirectory() as temporary:
        run_dir = Path(temporary)
        rows, _seal = pilot.run_inspections(
            runtime=runtime,
            store=make_store(run_dir, transport),
            run_dir=run_dir,
        )

        assert rows[0]["eligible_observation"] is True
        inspection_body = transport.bodies[0]
        assert "TASK" not in str(inspection_body)
        carrier = inspection_body["contents"][:-1]
        assert "Here" not in str(carrier)
        assert [content["role"] for content in carrier] == ["user", "model"]
        assert carrier[1]["parts"] == [
            {"text": "", "thoughtSignature": "SECRET"}
        ]
        assert carrier[0]["parts"][0]["text"] == protocol.NEUTRAL_CARRIER_STUB
        assert inspection_body["contents"][-1]["parts"][0]["text"] == (
            protocol.PRIMARY_INSPECTION_PROMPT
        )
        assert checkpoint.full_history[0] == protocol.user_step("TASK")

        with pytest.raises(ValueError, match="not a completed READY"):
            pilot.run_executions(
                baseline=checkpoint,
                adjusted=checkpoint,
                store=make_store(run_dir, ScriptedTransport([])),
                run_dir=run_dir,
            )


def test_inspection_side_branch_cannot_mutate_live_history() -> None:
    result = planning_result(text="READY", signature="LIVE_SECRET")
    evaluated = pilot.evaluate_planning_turn(result)
    history = [protocol.user_step("TASK"), *copy.deepcopy(evaluated.steps)]
    checkpoint = pilot.CheckpointRuntime(
        checkpoint_id="ID_0123456789ABCDEFGHJKMNPQRS",
        phase="baseline",
        turn_number=1,
        readiness_observation=protocol.READY,
        provider_status="completed",
        full_history=copy.deepcopy(history),
        response_steps=copy.deepcopy(evaluated.steps),
        summary={},
    )
    before = copy.deepcopy(checkpoint.full_history)
    runtime = pilot.PlanningPhaseRuntime(
        phase="baseline",
        checkpoints=[checkpoint],
        ready_checkpoint=checkpoint,
        terminal="COMPLETED_READY_CHECKPOINT",
        last_turn_classification=protocol.READY,
        public_summary={},
    )
    transport = ScriptedTransport(
        [planning_result(text="holistic observation", signature="READOUT_SECRET")]
    )
    with tempfile.TemporaryDirectory() as temporary:
        pilot.run_inspections(
            runtime=runtime,
            store=make_store(Path(temporary), transport),
            run_dir=Path(temporary),
        )

    assert checkpoint.full_history == before
    assert "holistic observation" not in str(checkpoint.full_history)


def test_execution_uses_frozen_interleaved_schedule_and_paired_seeds() -> None:
    def ready_checkpoint(*, phase: str, checkpoint_id: str) -> pilot.CheckpointRuntime:
        response = [
            {
                "role": "model",
                "parts": [
                    {
                        "text": "READY",
                        "thoughtSignature": f"{phase.upper()}_PRIVATE_SIGNATURE",
                    }
                ],
            },
        ]
        return pilot.CheckpointRuntime(
            checkpoint_id=checkpoint_id,
            phase=phase,
            turn_number=1,
            readiness_observation=protocol.READY,
            provider_status="completed",
            full_history=[protocol.user_step(f"{phase} task"), *response],
            response_steps=response,
            summary={},
        )

    baseline = ready_checkpoint(
        phase="baseline", checkpoint_id="ID_0123456789ABCDEFGHJKMNPQRS"
    )
    adjusted = ready_checkpoint(
        phase="adjusted", checkpoint_id="ID_11111111111111111111111111"
    )
    schedule = protocol.build_execution_schedule()
    transport = ScriptedTransport(
        [
            planning_result(text=f"Memorandum {index}", signature=f"EXEC_{index}")
            for index in range(1, len(schedule) + 1)
        ]
    )
    with tempfile.TemporaryDirectory() as temporary:
        rows, _seal = pilot.run_executions(
            baseline=baseline,
            adjusted=adjusted,
            store=make_store(Path(temporary), transport),
            run_dir=Path(temporary),
        )

    assert [
        {
            "order": row["schedule_order"],
            "branch": row["branch"],
            "replicate": row["replicate"],
        }
        for row in rows
    ] == schedule
    for replicate in range(1, protocol.EXECUTION_REPLICATES_PER_CHECKPOINT + 1):
        pair = [
            body["generationConfig"]
            for body, row in zip(transport.bodies, rows, strict=True)
            if row["replicate"] == replicate
        ]
        assert len(pair) == 2
        assert pair[0] == pair[1]


@pytest.mark.parametrize(
    ("error_field", "error_value"),
    [
        ("error", {"message": "provider refused the inspection"}),
        ("errors", [{"message": "provider refused the inspection"}]),
        ("error", {}),
        ("errors", []),
    ],
)
def test_observation_top_level_errors_are_ineligible_but_partial_text_is_retained(
    error_field: str,
    error_value: object,
) -> None:
    result = planning_result(
        text="Partial diagnostic text worth retaining",
        signature="inspection-signature",
    )
    assert result.payload is not None
    result.payload[error_field] = error_value

    eligible, visible, _steps, _safe, reasons = (
        pilot._evaluate_observation_response(result)
    )

    assert eligible is False
    assert visible == "Partial diagnostic text worth retaining"
    assert "inspection response contained a top-level error" in reasons


@pytest.mark.parametrize("finish_reason", ["MAX_TOKENS", "SAFETY", "CONTENT_FILTER"])
def test_completed_observation_with_non_stop_finish_reason_is_ineligible(
    finish_reason: str,
) -> None:
    result = planning_result(
        text="Partial diagnostic text retained for audit",
        signature="inspection-signature",
        finish_reason=finish_reason,
    )

    eligible, visible, _steps, safe, reasons = (
        pilot._evaluate_observation_response(result)
    )

    assert eligible is False
    assert visible == "Partial diagnostic text retained for audit"
    assert safe["explicit_finish_reasons"] == [finish_reason]
    assert any("finishReason was not STOP" in reason for reason in reasons)


def test_semantic_output_accepts_multiple_ordered_visible_text_parts() -> None:
    result = planning_result(text="unused", signature="inspection-signature")
    assert result.payload is not None
    result.payload["candidates"][0]["content"]["parts"] = [
        {"text": "Integrated "},
        {"text": "decision structure", "thoughtSignature": "signed-readout"},
    ]

    eligible, visible, _steps, _safe, reasons = (
        pilot._evaluate_observation_response(result)
    )

    assert eligible is True
    assert visible == "Integrated decision structure"
    assert reasons == []


def test_semantic_output_rejects_whitespace_only_text() -> None:
    result = planning_result(text=" \r\n\t", signature="inspection-signature")

    eligible, visible, _steps, _safe, reasons = (
        pilot._evaluate_observation_response(result)
    )

    assert eligible is False
    assert visible == " \r\n\t"
    assert "inspection visible output was empty" in reasons


def test_generate_content_bytes_reject_invalid_utf8_without_replay_payload() -> None:
    raw_body, payload, parse_error = decode_generate_content_bytes(
        b'{"candidates":[{"content":{"parts":[{"thoughtSignature":"\xff"}]}}]}'
    )

    assert "\ufffd" in raw_body
    assert payload is None
    assert parse_error.startswith("UnicodeDecodeError:")


def test_execution_response_uses_execution_context_for_transport_failures() -> None:
    payload = planning_result(
        text="Partial execution memorandum", signature="execution-signature"
    ).payload
    result = http_result(payload=payload, status=503)

    eligible, _visible, _safe, _steps, reasons = pilot._execution_response(result)

    assert eligible is False
    assert "execution was not HTTP 2xx" in reasons
    assert all(not reason.startswith("inspection ") for reason in reasons)


@pytest.mark.parametrize(("error_field", "error_value"), [("error", {}), ("errors", [])])
def test_planning_rejects_present_but_falsy_top_level_error_fields(
    error_field: str, error_value: object
) -> None:
    result = planning_result(text="READY", signature="SIGNED_READY")
    assert result.payload is not None
    result.payload[error_field] = error_value

    evaluated = pilot.evaluate_planning_turn(result)

    assert evaluated.controller_action == pilot.ACTION_TERMINATE_TECHNICAL
    assert evaluated.carrier_replayable is False
    assert "response contained a top-level error" in evaluated.reasons


def test_phase_review_labels_eligibility_reasons_and_ineligible_partial_text() -> None:
    runtime = pilot.PlanningPhaseRuntime(
        phase="baseline",
        checkpoints=[],
        ready_checkpoint=None,
        terminal=protocol.PLANNING_THRESHOLD_REACHED,
        last_turn_classification=protocol.INVALID_STATUS,
        public_summary={},
    )
    observations = [
        {
            "turn_number": 1,
            "checkpoint_id": "ID_0123456789ABCDEFGHJKMNPQRS",
            "checkpoint_readiness_observation": protocol.READY,
            "eligible_observation": True,
            "reasons": [],
            "observation": "Eligible integrated observation",
        },
        {
            "turn_number": 2,
            "checkpoint_id": "ID_11111111111111111111111111",
            "checkpoint_readiness_observation": protocol.INVALID_STATUS,
            "eligible_observation": False,
            "reasons": [
                "inspection response contained a top-level error",
                "inspection generateContent finishReason was not STOP",
            ],
            "observation": "Partial ineligible text retained for audit",
        },
    ]

    review = pilot._phase_review_markdown(
        runtime=runtime,
        observations=observations,
    )

    assert "Observation eligibility: `ELIGIBLE`" in review
    assert "Observation eligibility: `INELIGIBLE`" in review
    assert "Observation eligibility reasons:\n\n- NONE" in review
    assert "- inspection response contained a top-level error" in review
    assert "- inspection generateContent finishReason was not STOP" in review
    assert "Observation text (retained even when ineligible):" in review
    assert "Partial ineligible text retained for audit" in review


def test_intervention_package_must_replace_templates_and_is_hash_sealed() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_valid_phase_one_archive(root)
        intervention_dir = root / "intervention"
        phase_one_seal = root / "phase_one_seal.json"
        for name in pilot.INTERVENTION_RECORD_FILES:
            (intervention_dir / name).write_text(
                "REPLACE_BEFORE_SEALING", encoding="utf-8"
            )

        with pytest.raises(ValueError, match="template marker"):
            pilot.seal_intervention_package(
                intervention_dir=intervention_dir,
                phase_one_seal_path=phase_one_seal,
                expected_freeze_id="a" * 64,
                expected_task_text="TASK",
                expected_run_dir=root,
            )

        (intervention_dir / "diagnosis.md").write_text(
            "The plan depends materially on a broad reading of emergency authority.",
            encoding="utf-8",
        )
        (intervention_dir / "prediction.md").write_text(
            "Governance and sequencing should change; integrity controls should remain.",
            encoding="utf-8",
        )
        (intervention_dir / "intervention.txt").write_text(
            "Re-examine the extent and enforceability of emergency authority and its "
            "consequences. Preserve conclusions that remain justified.",
            encoding="utf-8",
        )
        lock = pilot.seal_intervention_package(
            intervention_dir=intervention_dir,
            phase_one_seal_path=phase_one_seal,
            expected_freeze_id="a" * 64,
            expected_task_text="TASK",
            expected_run_dir=root,
        )
        verified, texts = pilot.verify_intervention_package(
            intervention_dir=intervention_dir,
            phase_one_seal_path=phase_one_seal,
        )

        assert verified == lock
        assert texts["intervention.txt"].startswith("Re-examine")
        (intervention_dir / "prediction.md").write_text(
            "post-seal mutation", encoding="utf-8"
        )
        with pytest.raises(ValueError, match="changed"):
            pilot.verify_intervention_package(
                intervention_dir=intervention_dir,
                phase_one_seal_path=phase_one_seal,
            )


def test_intervention_seal_requires_complete_authorized_phase_one_lineage() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_valid_phase_one_archive(root)
        intervention_dir = root / "intervention"
        for name in pilot.INTERVENTION_RECORD_FILES:
            (intervention_dir / name).write_text(
                "A complete diagnostic record with no template marker.",
                encoding="utf-8",
            )
        (root / pilot.PHASE_ONE_TERMINAL_FILE).unlink()

        with pytest.raises(ValueError, match="required JSON artifact"):
            pilot.seal_intervention_package(
                intervention_dir=intervention_dir,
                phase_one_seal_path=root / "phase_one_seal.json",
                expected_freeze_id="a" * 64,
                expected_task_text="TASK",
                expected_run_dir=root,
            )

        assert not (root / pilot.PHASE_TWO_DISPOSITION_FILE).exists()
        assert not (intervention_dir / pilot.INTERVENTION_LOCK_FILE).exists()


@pytest.mark.parametrize("disposition", ["intervention", "no_target"])
@pytest.mark.parametrize(
    ("expected_freeze_id", "expected_task_text"),
    [("b" * 64, "TASK"), ("a" * 64, "WRONG TASK")],
)
def test_disposition_rejects_independently_supplied_freeze_or_task_mismatch(
    disposition: str,
    expected_freeze_id: str,
    expected_task_text: str,
) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_valid_phase_one_archive(root)
        if disposition == "intervention":
            intervention_dir = root / "intervention"
            for name in pilot.INTERVENTION_RECORD_FILES:
                (intervention_dir / name).write_text(
                    "A complete human disposition record.", encoding="utf-8"
                )
            with pytest.raises(ValueError):
                pilot.seal_intervention_package(
                    intervention_dir=intervention_dir,
                    phase_one_seal_path=root / "phase_one_seal.json",
                    expected_freeze_id=expected_freeze_id,
                    expected_task_text=expected_task_text,
                    expected_run_dir=root,
                )
            assert not (intervention_dir / pilot.INTERVENTION_LOCK_FILE).exists()
        else:
            note_path = root / pilot.NO_INTERVENTION_NOTE_FILE
            note_path.write_text(
                "The isolated observation exposes no valid local intervention target.",
                encoding="utf-8",
            )
            with pytest.raises(ValueError):
                pilot.record_no_valid_intervention_target(
                    phase_one_seal_path=root / "phase_one_seal.json",
                    note_path=note_path,
                    expected_freeze_id=expected_freeze_id,
                    expected_task_text=expected_task_text,
                    expected_run_dir=root,
                )
            assert not (root / pilot.NO_INTERVENTION_TARGET_FILE).exists()

        assert not (root / pilot.PHASE_TWO_DISPOSITION_FILE).exists()


def test_intervention_seal_rejects_extra_root_artifact_before_disposition() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_valid_phase_one_archive(root)
        intervention_dir = root / "intervention"
        for name in pilot.INTERVENTION_RECORD_FILES:
            (intervention_dir / name).write_text(
                "A complete human disposition record.", encoding="utf-8"
            )
        (root / "unexpected_review_artifact.txt").write_text(
            "not part of the frozen review family", encoding="utf-8"
        )

        with pytest.raises(ValueError):
            pilot.seal_intervention_package(
                intervention_dir=intervention_dir,
                phase_one_seal_path=root / "phase_one_seal.json",
                expected_freeze_id="a" * 64,
                expected_task_text="TASK",
                expected_run_dir=root,
            )

        assert not (root / pilot.PHASE_TWO_DISPOSITION_FILE).exists()
        assert not (intervention_dir / pilot.INTERVENTION_LOCK_FILE).exists()


@pytest.mark.parametrize("disposition", ["intervention", "no_target"])
def test_disposition_mutation_rejects_a_copied_run_occurrence(
    disposition: str,
) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_valid_phase_one_archive(root)
        copied_occurrence = root / "not-the-authorized-run"
        if disposition == "intervention":
            intervention_dir = root / "intervention"
            for name in pilot.INTERVENTION_RECORD_FILES:
                (intervention_dir / name).write_text(
                    "A complete human disposition record.", encoding="utf-8"
                )
            with pytest.raises(ValueError, match="authorized freeze run"):
                pilot.seal_intervention_package(
                    intervention_dir=intervention_dir,
                    phase_one_seal_path=root / "phase_one_seal.json",
                    expected_freeze_id="a" * 64,
                    expected_task_text="TASK",
                    expected_run_dir=copied_occurrence,
                )
        else:
            note_path = root / pilot.NO_INTERVENTION_NOTE_FILE
            note_path.write_text(
                "The isolated observation exposes no valid local target.",
                encoding="utf-8",
            )
            with pytest.raises(ValueError, match="authorized freeze run"):
                pilot.record_no_valid_intervention_target(
                    phase_one_seal_path=root / "phase_one_seal.json",
                    note_path=note_path,
                    expected_freeze_id="a" * 64,
                    expected_task_text="TASK",
                    expected_run_dir=copied_occurrence,
                )

        assert not (root / pilot.PHASE_TWO_DISPOSITION_FILE).exists()


def test_no_target_preflight_rejects_reserved_empty_directory_before_claim() -> None:
    with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as note_temp:
        root = Path(temporary)
        build_valid_phase_one_archive(root)
        (root / pilot.NO_INTERVENTION_NOTE_FILE).mkdir()
        external_note = Path(note_temp) / "note.md"
        external_note.write_text(
            "The isolated observation exposes no valid local target.",
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="unexpected directory"):
            pilot.record_no_valid_intervention_target(
                phase_one_seal_path=root / "phase_one_seal.json",
                note_path=external_note,
                expected_freeze_id="a" * 64,
                expected_task_text="TASK",
                expected_run_dir=root,
            )

        assert not (root / pilot.PHASE_TWO_DISPOSITION_FILE).exists()


def test_phase_one_archive_verifier_binds_ready_lineage_and_observations() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        runtime, seal = build_valid_phase_one_archive(root)

        verified, loaded = pilot._verify_phase_one_archive(
            run_dir=root, expected_freeze_id="a" * 64
        )

        assert verified == seal
        assert loaded.ready_checkpoint.checkpoint_id == (
            runtime.ready_checkpoint.checkpoint_id
        )

        (root / "intervention" / "diagnosis.md").unlink()
        with pytest.raises(ValueError, match="template family is incomplete"):
            pilot._verify_phase_one_archive(
                run_dir=root, expected_freeze_id="a" * 64
            )


def test_phase_one_archive_rejects_cross_freeze_and_wrong_ready_id() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        runtime, seal = build_valid_phase_one_archive(root)

        with pytest.raises(ValueError, match="different freeze"):
            pilot._verify_phase_one_archive(
                run_dir=root, expected_freeze_id="b" * 64
            )

        seal["ready_checkpoint_id"] = "ID_11111111111111111111111111"
        pilot.write_json(root / "phase_one_seal.json", seal)
        rebind_phase_one_claim(root)
        with pytest.raises(ValueError, match="terminal state is inconsistent"):
            pilot._verify_phase_one_archive(
                run_dir=root, expected_freeze_id="a" * 64
            )
        assert runtime.ready_checkpoint is not None


@pytest.mark.parametrize(
    "bad_created_at", ["not-a-timestamp", "2000-01-01T00:00:00Z"]
)
def test_phase_one_rejects_invalid_or_out_of_order_observation_seal_time(
    bad_created_at: str,
) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        _runtime, phase_one_seal = build_valid_phase_one_archive(root)
        observation_seal_path = root / "baseline_observation_seal.json"
        observation_seal = json.loads(
            observation_seal_path.read_text(encoding="utf-8")
        )
        observation_seal["created_at"] = bad_created_at
        pilot.write_json(observation_seal_path, observation_seal)
        phase_one_seal["observation_seal_sha256"] = protocol.sha256_json(
            observation_seal
        )
        phase_one_seal["phase_one_artifact_inventory"] = pilot._artifact_inventory(
            run_dir=root, relative_paths=pilot.PHASE_ONE_ARTIFACT_PATHS
        )
        pilot.write_json(root / "phase_one_seal.json", phase_one_seal)
        rebind_phase_one_claim(root)

        with pytest.raises(ValueError):
            pilot._verify_phase_one_archive(
                run_dir=root,
                expected_freeze_id="a" * 64,
                expected_task_text="TASK",
            )


def test_phase_one_archive_rejects_rehashed_public_summary_tampering() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        _runtime, seal = build_valid_phase_one_archive(root)
        summary_path = root / "baseline_planning_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["terminal"] = protocol.PLANNING_THRESHOLD_REACHED
        pilot.write_json(summary_path, summary)
        seal["planning_summary_sha256"] = protocol.sha256_json(summary)
        pilot.write_json(root / "phase_one_seal.json", seal)
        rebind_phase_one_claim(root)

        with pytest.raises(ValueError, match="conflicts with raw lineage"):
            pilot._verify_phase_one_archive(
                run_dir=root, expected_freeze_id="a" * 64
            )


def test_phase_one_archive_rejects_rehashed_fabricated_review() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        _runtime, seal = build_valid_phase_one_archive(root)
        review_path = root / "PHASE_ONE_REVIEW.md"
        review_path.write_text(
            "FABRICATED REVIEW BASELINE_PRIVATE_SIGNATURE", encoding="utf-8"
        )
        seal["phase_one_review_bytes_sha256"] = protocol.sha256_bytes(
            review_path.read_bytes()
        )
        seal["phase_one_artifact_inventory"] = pilot._artifact_inventory(
            run_dir=root, relative_paths=pilot.PHASE_ONE_ARTIFACT_PATHS
        )
        pilot.write_json(root / "phase_one_seal.json", seal)
        rebind_phase_one_claim(root)

        with pytest.raises(ValueError, match="review changed"):
            pilot._verify_phase_one_archive(
                run_dir=root, expected_freeze_id="a" * 64
            )


def test_phase_one_archive_rejects_byte_only_claim_and_call_index_mutation() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_valid_phase_one_archive(root)
        claim_path = root / pilot.PHASE_ONE_CLAIM_FILE
        original_claim = claim_path.read_bytes()
        claim_path.write_bytes(original_claim + b" ")
        with pytest.raises(ValueError, match="complete or authentic"):
            pilot._verify_phase_one_archive(
                run_dir=root, expected_freeze_id="a" * 64
            )

        claim_path.write_bytes(original_claim)
        call_index_path = root / "raw" / "call_index.json"
        original_call_index = call_index_path.read_bytes()
        call_index_path.write_bytes(original_call_index + b" ")
        with pytest.raises(ValueError, match="raw call index"):
            pilot._verify_phase_one_archive(
                run_dir=root, expected_freeze_id="a" * 64
            )


def test_phase_one_archive_rejects_unsealed_extra_nonraw_artifact() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_valid_phase_one_archive(root)
        (root / "UNSEALED_MISLEADING_REVIEW.md").write_text(
            "unsealed", encoding="utf-8"
        )

        with pytest.raises(ValueError, match="non-raw run-tree closure"):
            pilot._verify_phase_one_archive(
                run_dir=root, expected_freeze_id="a" * 64
            )


def test_phase_one_archive_rejects_unexpected_raw_directory() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_valid_phase_one_archive(root)
        (root / "raw" / "reserved_future_artifact.request.json").mkdir()

        with pytest.raises(ValueError, match="raw call inventory.*unexpected directory"):
            pilot._verify_phase_one_archive(
                run_dir=root, expected_freeze_id="a" * 64
            )


def test_phase_two_consumption_claim_is_atomic_under_concurrency() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        barrier = threading.Barrier(2)

        def compete() -> str:
            barrier.wait()
            try:
                pilot._claim_phase_two_consumption(
                    run_dir=root,
                    freeze_id="a" * 64,
                    ready_checkpoint_id="ID_0123456789ABCDEFGHJKMNPQRS",
                    intervention_lock_sha256="b" * 64,
                )
            except FileExistsError:
                return "rejected"
            return "claimed"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _index: compete(), range(2)))

        assert sorted(outcomes) == ["claimed", "rejected"]


def test_first_turn_technical_termination_seals_empty_observation_set() -> None:
    transport = ScriptedTransport(
        [
            planning_result(
                text=None,
                signature=None,
                include_candidates=False,
            )
        ]
    )
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        runtime = pilot.run_planning_phase(
            phase="baseline",
            first_body=protocol.initial_planning_body(task_text="TASK"),
            max_turns=2,
            store=make_store(root, transport),
            run_dir=root,
        )
        rows, seal = pilot.run_inspections(
            runtime=runtime,
            store=make_store(root, ScriptedTransport([])),
            run_dir=root,
        )

        assert runtime.terminal == "TECHNICAL_TERMINATION_NO_REPLAYABLE_CHECKPOINT"
        assert rows == []
        assert seal["checkpoint_count"] == 0
        assert seal["observation_count"] == 0
        assert json.loads(
            (root / "baseline_observations.private.json").read_text(
                encoding="utf-8"
            )
        ) == []


def test_zero_checkpoint_phase_one_archive_is_still_bound_to_frozen_task(
    monkeypatch,
) -> None:
    freeze_id = "7" * 64
    transport = ScriptedTransport(
        [
            planning_result(
                text=None,
                signature=None,
                include_candidates=False,
            )
        ]
    )
    with tempfile.TemporaryDirectory() as temporary:
        repo_root = Path(temporary)
        monkeypatch.setattr(
            pilot,
            "_load_verified_definition",
            lambda **_kwargs: {"dossier": {"assembled_task_text": "TASK"}},
        )
        monkeypatch.setattr(
            pilot,
            "_assert_private_output_root",
            lambda **_kwargs: None,
        )

        run_dir, runtime, observations = pilot.execute_phase_one(
            repo_root=repo_root,
            freeze_dir=repo_root,
            freeze_id=freeze_id,
            api_key="unused",
            transport=transport,
        )

        assert runtime.checkpoints == []
        assert observations == []
        pilot._verify_phase_one_archive(
            run_dir=run_dir,
            expected_freeze_id=freeze_id,
            expected_task_text="TASK",
        )
        with pytest.raises(ValueError, match="frozen dossier"):
            pilot._verify_phase_one_archive(
                run_dir=run_dir,
                expected_freeze_id=freeze_id,
                expected_task_text="WRONG TASK",
            )


def test_execute_phase_one_does_not_return_before_reverse_verification(
    monkeypatch,
) -> None:
    freeze_id = "6" * 64
    transport = ScriptedTransport(
        [
            planning_result(text="READY", signature="READY_SIGNATURE"),
            planning_result(
                text="Integrated isolated observation",
                signature="OBSERVATION_SIGNATURE",
            ),
        ]
    )
    with tempfile.TemporaryDirectory() as temporary:
        repo_root = Path(temporary)
        monkeypatch.setattr(
            pilot,
            "_load_verified_definition",
            lambda **_kwargs: {"dossier": {"assembled_task_text": "TASK"}},
        )
        monkeypatch.setattr(
            pilot,
            "_assert_private_output_root",
            lambda **_kwargs: None,
        )

        def reject_reverse_verification(**_kwargs):
            raise ValueError("forced phase-one reverse-verification failure")

        monkeypatch.setattr(
            pilot, "_verify_phase_one_archive", reject_reverse_verification
        )
        with pytest.raises(ValueError, match="forced phase-one"):
            pilot.execute_phase_one(
                repo_root=repo_root,
                freeze_dir=repo_root,
                freeze_id=freeze_id,
                api_key="unused",
                transport=transport,
            )

        run_dir = pilot.execution_output_dir(
            repo_root=repo_root, freeze_id=freeze_id
        )
        terminal = json.loads(
            (run_dir / pilot.PHASE_ONE_TERMINAL_FILE).read_text(encoding="utf-8")
        )
        assert terminal["status"] == "COMPLETED"


def test_execute_phase_two_does_not_return_before_reverse_verification(
    monkeypatch,
) -> None:
    freeze_id = "5" * 64
    with tempfile.TemporaryDirectory() as temporary:
        repo_root = Path(temporary)
        run_dir = repo_root / "results" / "reasoning_engineering" / freeze_id
        run_dir.mkdir(parents=True)
        build_valid_phase_one_archive(run_dir, freeze_id=freeze_id)
        intervention_dir = create_sealed_intervention(run_dir, freeze_id=freeze_id)
        observation_payload = copy.deepcopy(
            planning_result(
                text="Partial adjusted observation",
                signature="INELIGIBLE_OBSERVATION",
            ).payload
        )
        observation_payload["error"] = {"message": "inspection refused"}
        transport = ScriptedTransport(
            [
                planning_result(text="READY", signature="ADJUSTED_READY"),
                http_result(payload=observation_payload),
            ]
        )
        monkeypatch.setattr(
            pilot,
            "_load_verified_definition",
            lambda **_kwargs: {"dossier": {"assembled_task_text": "TASK"}},
        )
        monkeypatch.setattr(
            pilot,
            "_assert_private_output_root",
            lambda **_kwargs: None,
        )

        def reject_reverse_verification(**_kwargs):
            raise ValueError("forced phase-two reverse-verification failure")

        monkeypatch.setattr(
            pilot, "verify_phase_two_archive", reject_reverse_verification
        )
        with pytest.raises(ValueError, match="forced phase-two"):
            pilot.execute_phase_two(
                repo_root=repo_root,
                freeze_dir=repo_root,
                freeze_id=freeze_id,
                intervention_dir=intervention_dir,
                api_key="unused",
                transport=transport,
            )

        terminal = json.loads(
            (run_dir / pilot.PHASE_TWO_TERMINAL_FILE).read_text(encoding="utf-8")
        )
        assert terminal["status"] == "COMPLETED"


def test_signed_safety_termination_is_not_checkpointed_or_continued() -> None:
    transport = ScriptedTransport(
        [
            planning_result(
                text="READY",
                signature="SIGNED_SAFETY_CARRIER",
                finish_reason="SAFETY",
            )
        ]
    )
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        runtime = pilot.run_planning_phase(
            phase="baseline",
            first_body=protocol.initial_planning_body(task_text="TASK"),
            max_turns=2,
            store=make_store(root, transport),
            run_dir=root,
        )

        assert runtime.terminal == "TECHNICAL_TERMINATION_NONCONTINUABLE_RESPONSE"
        assert runtime.checkpoints == []
        assert runtime.ready_checkpoint is None
        assert len(transport.bodies) == 1
        attempts = json.loads(
            (root / "baseline_planning_attempts.json").read_text(encoding="utf-8")
        )
        assert attempts[0]["carrier_replayable"] is True
        assert attempts[0]["controller_action"] == pilot.ACTION_TERMINATE_TECHNICAL


def test_invalid_freeze_stops_phase_one_before_transport(monkeypatch) -> None:
    transport = ScriptedTransport([])

    def reject_freeze(**_kwargs):
        raise ValueError("invalid reviewed freeze")

    monkeypatch.setattr(pilot, "_load_verified_definition", reject_freeze)
    with pytest.raises(ValueError, match="invalid reviewed freeze"):
        pilot.execute_phase_one(
            repo_root=Path.cwd(),
            freeze_dir=Path.cwd(),
            freeze_id="a" * 64,
            api_key="unused",
            transport=transport,
        )

    assert transport.bodies == []


def test_private_output_guard_accepts_only_the_ignored_results_tree() -> None:
    output = pilot.execution_output_dir(
        repo_root=REPO_ROOT, freeze_id="f" * 64
    )

    pilot._assert_private_output_root(repo_root=REPO_ROOT, output_dir=output)

    with pytest.raises(ValueError, match="private results tree"):
        pilot._assert_private_output_root(
            repo_root=REPO_ROOT,
            output_dir=REPO_ROOT / "shareable" / ("f" * 64),
        )


def test_no_target_terminal_is_bound_and_blocks_reuse() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        runtime, _seal = build_valid_phase_one_archive(root)
        note = root / "no_target_note.md"
        note.write_text(
            "The isolated observation contains no material local weakness that can "
            "be challenged without supplying an answer.",
            encoding="utf-8",
        )

        marker = pilot.record_no_valid_intervention_target(
            phase_one_seal_path=root / "phase_one_seal.json",
            note_path=note,
            expected_freeze_id="a" * 64,
            expected_task_text="TASK",
            expected_run_dir=root,
        )

        assert marker["terminal"] == "NO_VALID_INTERVENTION_TARGET"
        assert marker["ready_checkpoint_id"] == (
            runtime.ready_checkpoint.checkpoint_id
        )
        assert marker["phase_two_model_calls"] == 0
        assert pilot.verify_no_valid_intervention_target(
            phase_one_seal_path=root / "phase_one_seal.json",
            expected_freeze_id="a" * 64,
            expected_task_text="TASK",
        ) == marker
        original_note = note.read_bytes()
        note.write_text("post-terminal mutation", encoding="utf-8")
        with pytest.raises(ValueError, match="invalid or conflicting"):
            pilot.verify_no_valid_intervention_target(
                phase_one_seal_path=root / "phase_one_seal.json",
                expected_freeze_id="a" * 64,
                expected_task_text="TASK",
            )
        note.write_bytes(original_note)
        with pytest.raises(FileExistsError, match="already recorded"):
            pilot.record_no_valid_intervention_target(
                phase_one_seal_path=root / "phase_one_seal.json",
                note_path=note,
                expected_freeze_id="a" * 64,
                expected_task_text="TASK",
                expected_run_dir=root,
            )

        intervention_dir = root / "intervention"
        intervention_dir.mkdir(exist_ok=True)
        for name in pilot.INTERVENTION_RECORD_FILES:
            (intervention_dir / name).write_text(
                "A complete diagnostic record that does not contain a template marker.",
                encoding="utf-8",
            )
        with pytest.raises(ValueError, match="preflight run-tree closure"):
            pilot.seal_intervention_package(
                intervention_dir=intervention_dir,
                phase_one_seal_path=root / "phase_one_seal.json",
                expected_freeze_id="a" * 64,
                expected_task_text="TASK",
                expected_run_dir=root,
            )


@pytest.mark.parametrize("tamper", ["extra_nonraw", "changed_template"])
def test_no_target_rejects_nonraw_tampering_before_disposition(tamper: str) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_valid_phase_one_archive(root)
        note_path = root / pilot.NO_INTERVENTION_NOTE_FILE
        note_path.write_text(
            "The isolated observation exposes no valid local intervention target.",
            encoding="utf-8",
        )
        if tamper == "extra_nonraw":
            (root / "unexpected_review_artifact.txt").write_text(
                "not part of the frozen review family", encoding="utf-8"
            )
        else:
            (root / "intervention" / "diagnosis.md").write_text(
                "changed canonical template", encoding="utf-8"
            )

        with pytest.raises(ValueError):
            pilot.record_no_valid_intervention_target(
                phase_one_seal_path=root / "phase_one_seal.json",
                note_path=note_path,
                expected_freeze_id="a" * 64,
                expected_task_text="TASK",
                expected_run_dir=root,
            )

        assert not (root / pilot.PHASE_TWO_DISPOSITION_FILE).exists()
        assert not (root / pilot.NO_INTERVENTION_TARGET_FILE).exists()


def test_no_target_verifier_rejects_independent_freeze_or_task_mismatch() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_valid_phase_one_archive(root)
        note_path = root / pilot.NO_INTERVENTION_NOTE_FILE
        note_path.write_text(
            "The isolated observation exposes no valid local intervention target.",
            encoding="utf-8",
        )
        pilot.record_no_valid_intervention_target(
            phase_one_seal_path=root / "phase_one_seal.json",
            note_path=note_path,
            expected_freeze_id="a" * 64,
            expected_task_text="TASK",
            expected_run_dir=root,
        )

        for expected_freeze_id, expected_task_text in (
            ("b" * 64, "TASK"),
            ("a" * 64, "WRONG TASK"),
        ):
            with pytest.raises(ValueError):
                pilot.verify_no_valid_intervention_target(
                    phase_one_seal_path=root / "phase_one_seal.json",
                    expected_freeze_id=expected_freeze_id,
                    expected_task_text=expected_task_text,
                )


def test_phase_two_disposition_choice_is_atomic_under_concurrency() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        barrier = threading.Barrier(2)

        def compete(disposition: str) -> str:
            barrier.wait()
            try:
                pilot._claim_phase_two_disposition(
                    run_dir=root,
                    freeze_id="a" * 64,
                    phase_one_seal_bytes=b"phase-one-seal",
                    decision_payload_sha256="b" * 64,
                    disposition=disposition,
                )
            except FileExistsError:
                return "rejected"
            return "claimed"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(
                executor.map(
                    compete,
                    ["SEALED_INTERVENTION", "NO_VALID_INTERVENTION_TARGET"],
                )
            )

        assert sorted(outcomes) == ["claimed", "rejected"]


def test_adjusted_threshold_performs_no_execution_calls_and_consumes_once(
    monkeypatch,
) -> None:
    freeze_id = "a" * 64
    with tempfile.TemporaryDirectory() as temporary:
        repo_root = Path(temporary)
        run_dir = (
            repo_root
            / "results"
            / "reasoning_engineering"
            / freeze_id
        )
        run_dir.mkdir(parents=True)
        build_valid_phase_one_archive(run_dir, freeze_id=freeze_id)
        intervention_dir = run_dir / "intervention"
        intervention_dir.mkdir(exist_ok=True)
        (intervention_dir / "diagnosis.md").write_text(
            "The plan relies too heavily on an unbounded authority interpretation.",
            encoding="utf-8",
        )
        (intervention_dir / "prediction.md").write_text(
            "Governance sequencing should change while integrity controls remain.",
            encoding="utf-8",
        )
        (intervention_dir / "intervention.txt").write_text(
            "Re-examine the scope and enforceability of the authority relied upon. "
            "Preserve conclusions that remain justified.",
            encoding="utf-8",
        )
        pilot.seal_intervention_package(
            intervention_dir=intervention_dir,
            phase_one_seal_path=run_dir / "phase_one_seal.json",
            expected_freeze_id=freeze_id,
            expected_task_text="TASK",
            expected_run_dir=run_dir,
        )
        results = [
            planning_result(text="NOT_READY", signature=f"ADJUSTED_{index}")
            for index in range(protocol.MAX_ADJUSTED_PLANNING_TURNS)
        ]
        results.extend(
            planning_result(
                text=f"Observation {index}", signature=f"READOUT_{index}"
            )
            for index in range(protocol.MAX_ADJUSTED_PLANNING_TURNS)
        )
        transport = ScriptedTransport(results)
        monkeypatch.setattr(
            pilot,
            "_load_verified_definition",
            lambda **_kwargs: {"dossier": {"assembled_task_text": "TASK"}},
        )
        monkeypatch.setattr(
            pilot,
            "_assert_private_output_root",
            lambda **_kwargs: None,
        )

        adjusted, observations, executions = pilot.execute_phase_two(
            repo_root=repo_root,
            freeze_dir=repo_root,
            freeze_id=freeze_id,
            intervention_dir=intervention_dir,
            api_key="unused",
            transport=transport,
        )

        assert adjusted.terminal == protocol.PLANNING_THRESHOLD_REACHED
        assert len(observations) == protocol.MAX_ADJUSTED_PLANNING_TURNS
        assert executions == []
        assert len(transport.bodies) == protocol.MAX_ADJUSTED_PLANNING_TURNS * 2
        assert all(
            body["contents"][-1] != protocol.user_step(protocol.EXECUTION_PROMPT)
            for body in transport.bodies
        )
        claim = json.loads(
            (run_dir / pilot.PHASE_TWO_CLAIM_FILE).read_text(encoding="utf-8")
        )
        assert claim["status"] == "CLAIMED"
        terminal = json.loads(
            (run_dir / pilot.PHASE_TWO_TERMINAL_FILE).read_text(encoding="utf-8")
        )
        assert terminal["status"] == "COMPLETED"
        assert terminal["phase_two_seal_sha256"]
        with pytest.raises(FileExistsError, match="already started"):
            pilot.execute_phase_two(
                repo_root=repo_root,
                freeze_dir=repo_root,
                freeze_id=freeze_id,
                intervention_dir=intervention_dir,
                api_key="unused",
                transport=ScriptedTransport([]),
            )


def test_ineligible_ready_observation_blocks_intervention_authorization(
    monkeypatch,
) -> None:
    freeze_id = "a" * 64
    bad_observation_payload = copy.deepcopy(
        planning_result(
            text="Partial observation retained for audit",
            signature="INELIGIBLE_OBSERVATION_SIGNATURE",
        ).payload
    )
    bad_observation_payload["error"] = {"message": "inspection refused"}
    transport = ScriptedTransport(
        [
            planning_result(text="READY", signature="READY_PRIVATE_SIGNATURE"),
            http_result(payload=bad_observation_payload),
        ]
    )
    with tempfile.TemporaryDirectory() as temporary:
        repo_root = Path(temporary)
        monkeypatch.setattr(
            pilot,
            "_load_verified_definition",
            lambda **_kwargs: {"dossier": {"assembled_task_text": "TASK"}},
        )
        monkeypatch.setattr(
            pilot,
            "_assert_private_output_root",
            lambda **_kwargs: None,
        )

        run_dir, runtime, observations = pilot.execute_phase_one(
            repo_root=repo_root,
            freeze_dir=repo_root,
            freeze_id=freeze_id,
            api_key="unused",
            transport=transport,
        )

        seal = json.loads(
            (run_dir / "phase_one_seal.json").read_text(encoding="utf-8")
        )
        assert runtime.ready_checkpoint is not None
        assert observations[-1]["eligible_observation"] is False
        assert seal["phase_one_terminal"] == "READY_PRIMARY_OBSERVATION_INVALID"
        assert seal["ready_observation_eligible"] is False
        assert seal["intervention_authorized"] is False
        assert not (run_dir / "intervention").exists()
        verified_seal, _verified_runtime = pilot._verify_phase_one_archive(
            run_dir=run_dir, expected_freeze_id=freeze_id
        )
        assert verified_seal["intervention_authorized"] is False
        with pytest.raises(ValueError, match="does not authorize"):
            pilot._verify_phase_one_archive(
                run_dir=run_dir,
                expected_freeze_id=freeze_id,
                require_intervention_authorized=True,
            )


def test_max_tokens_threshold_archive_is_verifiable_but_not_authorized(
    monkeypatch,
) -> None:
    freeze_id = "9" * 64
    results = [
        planning_result(
            text=f"partial {turn}",
            signature=f"TRUNCATED_{turn}",
            finish_reason="MAX_TOKENS",
        )
        for turn in range(1, protocol.MAX_BASELINE_PLANNING_TURNS + 1)
    ]
    results.extend(
        planning_result(
            text=f"Isolated threshold observation {turn}",
            signature=f"OBSERVED_{turn}",
        )
        for turn in range(1, protocol.MAX_BASELINE_PLANNING_TURNS + 1)
    )
    with tempfile.TemporaryDirectory() as temporary:
        repo_root = Path(temporary)
        monkeypatch.setattr(
            pilot,
            "_load_verified_definition",
            lambda **_kwargs: {"dossier": {"assembled_task_text": "TASK"}},
        )
        monkeypatch.setattr(
            pilot,
            "_assert_private_output_root",
            lambda **_kwargs: None,
        )

        run_dir, runtime, observations = pilot.execute_phase_one(
            repo_root=repo_root,
            freeze_dir=repo_root,
            freeze_id=freeze_id,
            api_key="unused",
            transport=ScriptedTransport(results),
        )

        assert runtime.terminal == protocol.PLANNING_THRESHOLD_REACHED
        assert runtime.last_turn_classification == protocol.UNOBSERVED_TRUNCATED
        assert len(observations) == protocol.MAX_BASELINE_PLANNING_TURNS
        verified, _loaded = pilot._verify_phase_one_archive(
            run_dir=run_dir,
            expected_freeze_id=freeze_id,
            expected_task_text="TASK",
        )
        assert verified["phase_one_terminal"] == protocol.PLANNING_THRESHOLD_REACHED
        assert verified["intervention_authorized"] is False
        with pytest.raises(ValueError, match="does not authorize"):
            pilot._verify_phase_one_archive(
                run_dir=run_dir,
                expected_freeze_id=freeze_id,
                expected_task_text="TASK",
                require_intervention_authorized=True,
            )
        for name, template_text in pilot.INTERVENTION_TEMPLATE_TEXT.items():
            pilot.write_text(run_dir / "intervention" / name, template_text)
        with pytest.raises(ValueError, match="unauthorized.*intervention templates"):
            pilot._verify_phase_one_archive(
                run_dir=run_dir,
                expected_freeze_id=freeze_id,
                expected_task_text="TASK",
            )


def test_phase_one_interruption_terminalizes_consumption_claim(monkeypatch) -> None:
    freeze_id = "b" * 64
    transport = ScriptedTransport([])
    with tempfile.TemporaryDirectory() as temporary:
        repo_root = Path(temporary)
        monkeypatch.setattr(
            pilot,
            "_load_verified_definition",
            lambda **_kwargs: {"dossier": {"assembled_task_text": "TASK"}},
        )
        monkeypatch.setattr(
            pilot,
            "_assert_private_output_root",
            lambda **_kwargs: None,
        )

        with pytest.raises(AssertionError, match="exhausted"):
            pilot.execute_phase_one(
                repo_root=repo_root,
                freeze_dir=repo_root,
                freeze_id=freeze_id,
                api_key="unused",
                transport=transport,
            )

        run_dir = pilot.execution_output_dir(
            repo_root=repo_root, freeze_id=freeze_id
        )
        claim = json.loads(
            (run_dir / pilot.PHASE_ONE_CLAIM_FILE).read_text(encoding="utf-8")
        )
        assert claim["status"] == "CLAIMED"
        terminal = json.loads(
            (run_dir / pilot.PHASE_ONE_TERMINAL_FILE).read_text(encoding="utf-8")
        )
        assert terminal["status"] == "TERMINATED_ERROR"
        assert terminal["error_type"] == "AssertionError"
        assert terminal["phase_one_seal_sha256"] is None
        assert not (run_dir / "phase_one_seal.json").exists()


def test_missing_or_tampered_call_index_invalidates_phase_one_lineage() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_valid_phase_one_archive(root)
        call_index_path = root / "raw" / "call_index.json"
        original_index = call_index_path.read_bytes()
        call_index_path.unlink()
        with pytest.raises(ValueError, match="safe regular file"):
            pilot._verify_phase_one_archive(
                run_dir=root, expected_freeze_id="a" * 64
            )

        call_index_path.write_bytes(original_index)
        records = json.loads(original_index.decode("utf-8"))
        request_path = root / records[0]["raw_request_path"]
        request_path.write_bytes(request_path.read_bytes() + b" ")
        with pytest.raises(ValueError, match="wire artifact"):
            pilot._verify_phase_one_archive(
                run_dir=root, expected_freeze_id="a" * 64
            )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("http_status", 200.5, "field types"),
        ("call_number", True, "call numbers"),
        ("elapsed_ms", -1, "field types"),
        ("transport_error", 0, "field types"),
        ("response_decoded_chars", 999999, "wire artifact"),
    ],
)
def test_call_index_rejects_malformed_controller_metadata(
    field: str, value: object, message: str
) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_valid_phase_one_archive(root)
        call_index_path = root / "raw" / "call_index.json"
        records = json.loads(call_index_path.read_text(encoding="utf-8"))
        records[0][field] = value
        request_path = root / records[0]["raw_request_path"]
        stem = request_path.name[: -len(".request.json")]
        metadata_path = request_path.with_name(f"{stem}.metadata.json")
        pilot.write_json(metadata_path, records[0])
        pilot.write_json(call_index_path, records)

        with pytest.raises(ValueError, match=message):
            pilot._validate_call_index(root)


def test_call_index_rejects_nonmonotonic_physical_call_chronology() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        build_valid_phase_one_archive(root)
        call_index_path = root / "raw" / "call_index.json"
        records = json.loads(call_index_path.read_text(encoding="utf-8"))
        records[1]["started_at"] = "2000-01-01T00:00:00Z"
        records[1]["completed_at"] = "2000-01-01T00:00:01Z"
        request_path = root / records[1]["raw_request_path"]
        stem = request_path.name[: -len(".request.json")]
        pilot.write_json(
            request_path.with_name(f"{stem}.metadata.json"), records[1]
        )
        pilot.write_json(call_index_path, records)

        with pytest.raises(ValueError, match="timestamps"):
            pilot._validate_call_index(root)


def test_missing_phase_one_call_index_blocks_phase_two_before_transport(
    monkeypatch,
) -> None:
    freeze_id = "e" * 64
    with tempfile.TemporaryDirectory() as temporary:
        repo_root = Path(temporary)
        run_dir = repo_root / "results" / "reasoning_engineering" / freeze_id
        run_dir.mkdir(parents=True)
        build_valid_phase_one_archive(run_dir, freeze_id=freeze_id)
        intervention_dir = create_sealed_intervention(run_dir, freeze_id=freeze_id)
        (run_dir / "raw" / "call_index.json").unlink()
        transport = ScriptedTransport([])
        monkeypatch.setattr(
            pilot,
            "_load_verified_definition",
            lambda **_kwargs: {"dossier": {"assembled_task_text": "TASK"}},
        )
        monkeypatch.setattr(
            pilot,
            "_assert_private_output_root",
            lambda **_kwargs: None,
        )

        with pytest.raises(ValueError, match="safe regular file"):
            pilot.execute_phase_two(
                repo_root=repo_root,
                freeze_dir=repo_root,
                freeze_id=freeze_id,
                intervention_dir=intervention_dir,
                api_key="unused",
                transport=transport,
            )

        assert transport.bodies == []
        assert not (run_dir / pilot.PHASE_TWO_CLAIM_FILE).exists()


def test_completed_phase_two_is_integrity_closed_and_verifiable(
    monkeypatch,
) -> None:
    freeze_id = "c" * 64
    with tempfile.TemporaryDirectory() as temporary:
        repo_root = Path(temporary)
        run_dir = repo_root / "results" / "reasoning_engineering" / freeze_id
        run_dir.mkdir(parents=True)
        build_valid_phase_one_archive(run_dir, freeze_id=freeze_id)
        intervention_dir = create_sealed_intervention(run_dir, freeze_id=freeze_id)
        results = [
            planning_result(text="READY", signature="ADJUSTED_READY_SIGNATURE"),
            planning_result(
                text="Adjusted integrated decision observation",
                signature="ADJUSTED_OBSERVATION_SIGNATURE",
            ),
        ]
        results.extend(
            planning_result(
                text=f"Executive recovery memorandum {index}",
                signature=f"EXECUTION_SIGNATURE_{index}",
            )
            for index in range(
                protocol.EXECUTION_REPLICATES_PER_CHECKPOINT * 2
            )
        )
        transport = ScriptedTransport(results)
        monkeypatch.setattr(
            pilot,
            "_load_verified_definition",
            lambda **_kwargs: {"dossier": {"assembled_task_text": "TASK"}},
        )
        monkeypatch.setattr(
            pilot,
            "_assert_private_output_root",
            lambda **_kwargs: None,
        )

        adjusted, observations, executions = pilot.execute_phase_two(
            repo_root=repo_root,
            freeze_dir=repo_root,
            freeze_id=freeze_id,
            intervention_dir=intervention_dir,
            api_key="unused",
            transport=transport,
        )

        assert adjusted.ready_checkpoint is not None
        assert observations[-1]["eligible_observation"] is True
        assert len(executions) == protocol.EXECUTION_REPLICATES_PER_CHECKPOINT * 2
        verified = pilot.verify_phase_two_archive(
            run_dir=run_dir,
            expected_freeze_id=freeze_id,
            expected_task_text="TASK",
        )
        assert verified["evidence_chain_complete"] is True
        claim = json.loads(
            (run_dir / pilot.PHASE_TWO_CLAIM_FILE).read_text(encoding="utf-8")
        )
        assert claim["status"] == "CLAIMED"
        terminal = json.loads(
            (run_dir / pilot.PHASE_TWO_TERMINAL_FILE).read_text(encoding="utf-8")
        )
        assert terminal["status"] == "COMPLETED"
        assert terminal["phase_two_seal_sha256"]

        call_index_path = run_dir / "raw" / "call_index.json"
        original_call_index = call_index_path.read_bytes()
        call_index_path.write_bytes(original_call_index + b" ")
        with pytest.raises(ValueError, match="raw call lineage"):
            pilot.verify_phase_two_archive(
                run_dir=run_dir,
                expected_freeze_id=freeze_id,
                expected_task_text="TASK",
            )
        call_index_path.write_bytes(original_call_index)

        unexpected_path = run_dir / "unexpected_nonraw_artifact.txt"
        unexpected_path.write_text("not sealed", encoding="utf-8")
        with pytest.raises(ValueError, match="run-tree closure"):
            pilot.verify_phase_two_archive(
                run_dir=run_dir,
                expected_freeze_id=freeze_id,
                expected_task_text="TASK",
            )
        unexpected_path.unlink()

        phase_two_claim_path = run_dir / pilot.PHASE_TWO_CLAIM_FILE
        original_phase_two_claim = phase_two_claim_path.read_bytes()
        phase_two_claim_path.write_bytes(original_phase_two_claim + b" ")
        with pytest.raises(ValueError, match="complete or authentic"):
            pilot.verify_phase_two_archive(
                run_dir=run_dir,
                expected_freeze_id=freeze_id,
                expected_task_text="TASK",
            )
        phase_two_claim_path.write_bytes(original_phase_two_claim)

        summary_path = run_dir / "adjusted_planning_summary.json"
        original_summary = summary_path.read_bytes()
        summary_path.write_text("{}", encoding="utf-8")
        with pytest.raises(ValueError, match="conflicts with raw lineage"):
            pilot.verify_phase_two_archive(
                run_dir=run_dir,
                expected_freeze_id=freeze_id,
                expected_task_text="TASK",
            )
        summary_path.write_bytes(original_summary)

        orphan_store = make_store(
            run_dir,
            ScriptedTransport(
                [planning_result(text="orphan", signature="ORPHAN_SIGNATURE")]
            ),
        )
        orphan_store.records = pilot._validate_call_index(run_dir)
        orphan_store.invoke(
            label="orphan_physical_call",
            body=protocol.initial_planning_body(task_text="ORPHAN"),
        )
        resealed_calls = pilot._validate_call_index(run_dir)
        phase_two_seal_path = run_dir / pilot.PHASE_TWO_SEAL_FILE
        phase_two_seal = json.loads(
            phase_two_seal_path.read_text(encoding="utf-8")
        )
        phase_two_seal["final_physical_call_count"] = len(resealed_calls)
        phase_two_seal["created_at"] = pilot.utc_now()
        phase_two_seal["final_call_index_sha256"] = protocol.sha256_json(
            resealed_calls
        )
        phase_two_seal["final_call_index_bytes_sha256"] = protocol.sha256_bytes(
            call_index_path.read_bytes()
        )
        phase_two_seal["raw_inventory"] = pilot._raw_inventory(
            run_dir, include_call_index=True
        )
        pilot.write_json(phase_two_seal_path, phase_two_seal)
        terminal["terminal_at"] = pilot.utc_now()
        terminal["phase_two_seal_sha256"] = protocol.sha256_bytes(
            phase_two_seal_path.read_bytes()
        )
        pilot.write_json(run_dir / pilot.PHASE_TWO_TERMINAL_FILE, terminal)
        with pytest.raises(ValueError, match="orphan or out-of-order call"):
            pilot.verify_phase_two_archive(
                run_dir=run_dir,
                expected_freeze_id=freeze_id,
                expected_task_text="TASK",
            )


@pytest.mark.parametrize("finish_reason", ["MAX_TOKENS", "SAFETY"])
def test_non_stop_execution_finish_reason_prevents_complete_evidence_chain(
    monkeypatch,
    finish_reason: str,
) -> None:
    freeze_id = "1" * 64
    with tempfile.TemporaryDirectory() as temporary:
        repo_root = Path(temporary)
        run_dir = build_completed_phase_two_archive(
            repo_root,
            freeze_id=freeze_id,
            monkeypatch=monkeypatch,
            first_execution_finish_reason=finish_reason,
        )

        rows = json.loads((run_dir / "executions.json").read_text(encoding="utf-8"))
        summary = json.loads(
            (run_dir / "phase_two_summary.json").read_text(encoding="utf-8")
        )
        assert rows[0]["eligible"] is False
        assert rows[0]["explicit_finish_reasons"] == [finish_reason]
        assert any("finishReason was not STOP" in item for item in rows[0]["reasons"])
        assert summary["evidence_chain_complete"] is False
        assert summary["phase_two_terminal"] == "EXECUTION_MEASUREMENT_INCOMPLETE"
        verified = pilot.verify_phase_two_archive(
            run_dir=run_dir,
            expected_freeze_id=freeze_id,
            expected_task_text="TASK",
        )
        assert verified["evidence_chain_complete"] is False


def test_phase_two_rejects_coherently_resealed_unknown_nonraw_artifact(
    monkeypatch,
) -> None:
    freeze_id = "f" * 64
    with tempfile.TemporaryDirectory() as temporary:
        repo_root = Path(temporary)
        run_dir = build_completed_phase_two_archive(
            repo_root,
            freeze_id=freeze_id,
            monkeypatch=monkeypatch,
        )
        (run_dir / "attacker_added_artifact.txt").write_text(
            "coherently added to the claimed inventory", encoding="utf-8"
        )
        rebind_phase_two_nonraw_inventory(run_dir)

        with pytest.raises(ValueError):
            pilot.verify_phase_two_archive(
                run_dir=run_dir,
                expected_freeze_id=freeze_id,
                expected_task_text="TASK",
            )


@pytest.mark.parametrize(
    ("seal_name", "bad_created_at"),
    [
        ("adjusted_observation_seal.json", "not-a-timestamp"),
        ("adjusted_observation_seal.json", "2000-01-01T00:00:00Z"),
        ("execution_seal.json", "not-a-timestamp"),
        ("execution_seal.json", "2000-01-01T00:00:00Z"),
    ],
)
def test_phase_two_rejects_invalid_or_out_of_order_measurement_seal_time(
    monkeypatch,
    seal_name: str,
    bad_created_at: str,
) -> None:
    freeze_id = "f" * 64
    with tempfile.TemporaryDirectory() as temporary:
        repo_root = Path(temporary)
        run_dir = build_completed_phase_two_archive(
            repo_root,
            freeze_id=freeze_id,
            monkeypatch=monkeypatch,
        )
        measurement_seal_path = run_dir / seal_name
        measurement_seal = json.loads(
            measurement_seal_path.read_text(encoding="utf-8")
        )
        measurement_seal["created_at"] = bad_created_at
        pilot.write_json(measurement_seal_path, measurement_seal)
        rebind_phase_two_nonraw_inventory(run_dir)

        with pytest.raises(ValueError):
            pilot.verify_phase_two_archive(
                run_dir=run_dir,
                expected_freeze_id=freeze_id,
                expected_task_text="TASK",
            )


def test_ineligible_adjusted_ready_observation_prevents_execution(
    monkeypatch,
) -> None:
    freeze_id = "d" * 64
    with tempfile.TemporaryDirectory() as temporary:
        repo_root = Path(temporary)
        run_dir = repo_root / "results" / "reasoning_engineering" / freeze_id
        run_dir.mkdir(parents=True)
        build_valid_phase_one_archive(run_dir, freeze_id=freeze_id)
        intervention_dir = create_sealed_intervention(run_dir, freeze_id=freeze_id)
        bad_payload = copy.deepcopy(
            planning_result(
                text="Partial adjusted observation",
                signature="BAD_ADJUSTED_OBSERVATION",
            ).payload
        )
        bad_payload["errors"] = [{"message": "inspection failed"}]
        transport = ScriptedTransport(
            [
                planning_result(text="READY", signature="ADJUSTED_READY"),
                http_result(payload=bad_payload),
            ]
        )
        monkeypatch.setattr(
            pilot,
            "_load_verified_definition",
            lambda **_kwargs: {"dossier": {"assembled_task_text": "TASK"}},
        )
        monkeypatch.setattr(
            pilot,
            "_assert_private_output_root",
            lambda **_kwargs: None,
        )

        _adjusted, observations, executions = pilot.execute_phase_two(
            repo_root=repo_root,
            freeze_dir=repo_root,
            freeze_id=freeze_id,
            intervention_dir=intervention_dir,
            api_key="unused",
            transport=transport,
        )

        assert observations[-1]["eligible_observation"] is False
        assert executions == []
        assert len(transport.bodies) == 2
        summary = json.loads(
            (run_dir / "phase_two_summary.json").read_text(encoding="utf-8")
        )
        assert summary["phase_two_terminal"] == (
            "ADJUSTED_PRIMARY_OBSERVATION_INVALID"
        )
        assert summary["evidence_chain_complete"] is False
        verified = pilot.verify_phase_two_archive(
            run_dir=run_dir,
            expected_freeze_id=freeze_id,
            expected_task_text="TASK",
        )
        assert verified["evidence_chain_complete"] is False
