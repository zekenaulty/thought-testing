from __future__ import annotations

import copy
import json
from pathlib import Path
from unittest import mock

import pytest

from thoughtlab.gemini_generate_content import GenerateContentHttpResult
from thoughtlab.raw_call_store import write_text
from thoughtlab.reasoningEngineering import modernization_iterative_pilot as pilot
from thoughtlab.reasoningEngineering import modernization_iterative_protocol as protocol


FREEZE_ID = "7" * 64


class FakeGenerateContent:
    def __init__(self) -> None:
        self.bodies: list[dict] = []
        self.planning_count = 0
        self.observation_count = 0
        self.execution_count = 0

    def __call__(self, *, api_key, body, timeout, encoded_body):
        del api_key, timeout
        assert encoded_body == pilot.canonical_json_bytes(body)
        self.bodies.append(copy.deepcopy(body))
        last_text = body["contents"][-1]["parts"][0]["text"]
        if last_text == protocol.PRIMARY_INSPECTION_PROMPT:
            self.observation_count += 1
            visible = f"OBSERVATION::{self.observation_count}"
            parts = [{"text": visible}]
        elif last_text == protocol.EXECUTION_PROMPT:
            self.execution_count += 1
            visible = f"EXECUTION::{self.execution_count}"
            parts = [{"text": visible}]
        else:
            self.planning_count += 1
            visible = "READY"
            parts = [
                {"thoughtSignature": f"native-signature-{self.planning_count}"},
                {"text": visible},
            ]
        payload = {
            "modelVersion": protocol.MODEL,
            "candidates": [{
                "finishReason": "STOP",
                "content": {"role": "model", "parts": parts},
            }],
            "usageMetadata": {
                "promptTokenCount": 10, "candidatesTokenCount": 2,
                "thoughtsTokenCount": 20, "totalTokenCount": 32,
            },
        }
        raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        return GenerateContentHttpResult(
            http_status=200, payload=payload, raw_body=raw,
            transport_error="", response_parse_error="", elapsed_ms=1,
            raw_body_bytes=raw.encode("utf-8"), response_headers={},
        )


class TruncateThenReady(FakeGenerateContent):
    def __init__(self) -> None:
        super().__init__()
        self.first_planning_content: dict | None = None

    def __call__(self, *, api_key, body, timeout, encoded_body):
        last_text = body["contents"][-1]["parts"][0]["text"]
        is_planning = last_text not in {protocol.PRIMARY_INSPECTION_PROMPT, protocol.EXECUTION_PROMPT}
        if is_planning and self.planning_count == 0:
            self.bodies.append(copy.deepcopy(body))
            self.planning_count = 1
            content = {
                "role": "model",
                "parts": [{"thoughtSignature": "truncated-signed-state"}, {"text": "REA"}],
            }
            self.first_planning_content = copy.deepcopy(content)
            payload = {
                "modelVersion": protocol.MODEL,
                "candidates": [{"finishReason": "MAX_TOKENS", "content": content}],
            }
            raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
            return GenerateContentHttpResult(
                http_status=200, payload=payload, raw_body=raw,
                transport_error="", response_parse_error="", elapsed_ms=1,
                raw_body_bytes=raw.encode("utf-8"), response_headers={},
            )
        return super().__call__(
            api_key=api_key, body=body, timeout=timeout, encoded_body=encoded_body,
        )


def definition() -> dict:
    task = "FROZEN DOSSIER TASK"
    return {
        "model": protocol.MODEL,
        "api": protocol.API,
        "dossier": {
            "assembled_task_text": task,
            "assembled_task_sha256": protocol.base.sha256_text(task),
        },
        "execution": {"schedule": protocol.build_execution_schedule()},
    }


def _completed_review(title: str) -> str:
    return (
        f"# {title}\n\n"
        "## Diagnosis\n\nA material local dependency is inadequately bounded.\n\n"
        "## Observation evidence\n\n- The observation makes an unsupported joint commitment.\n\n"
        "## Targeted reasoning relationship\n\nThe commitment-to-evidence relationship.\n\n"
        "## Predicted observation changes\n\nThe next observation should bound the dependency.\n\n"
        "## Predicted execution changes\n\nThe execution should state a trigger and fallback.\n\n"
        "## Proposed intervention text\n\nRe-examine the cited dependency and bound its effects without changing unrelated commitments.\n"
    )


def _completed_reconciliation(intervention_id: str, *, no_target: bool = False) -> str:
    prior = protocol.NO_PRIOR_INTERVENTION if intervention_id == "I1" else "Preserve the prior localized repair."
    rubric = "\n".join(
        f"{item['dimension']}: 2" for item in protocol.SEMANTIC_HUMAN_RUBRIC
    )
    observation_id = str(protocol.INTERVENTION_SPECS[intervention_id]["source_observation"])
    target_fields = "\n\n".join(
        (
            f"## {target} diagnostic state\n\nBOUNDED\n\n"
            f"## {target} diagnostic evidence\n\nThe observation bounds this target and preserves its revision trigger.\n\n"
            f"## {target} hard contradiction present\n\nNO"
        )
        for target in protocol.OBSERVATION_ASSESSMENT_TARGETS[observation_id]
    )
    no_target_basis = (
        "Both independent streams found no material target satisfying the frozen charter."
        if no_target else "NOT_APPLICABLE"
    )
    return (
        "# Human-approved reconciliation\n\n"
        "Approved by: human_researcher\n"
        "Reviewer A disposition: accepted with localized synthesis\n"
        "Reviewer B disposition: accepted with localized synthesis\n\n"
        "## Basis\n\nThe two streams independently identified the same load-bearing relationship.\n\n"
        "## Final diagnosis\n\nA material local dependency is inadequately bounded.\n\n"
        "## Final observation evidence\n\n- The current observation makes an unsupported joint commitment.\n\n"
        "## Final targeted reasoning relationship\n\nThe commitment-to-evidence relationship.\n\n"
        "## Final predicted observation changes\n\nThe next observation should bound the dependency.\n\n"
        "## Final predicted execution changes\n\nThe execution should state a trigger and fallback.\n\n"
        f"## Prior delta: persist\n\n{prior}\n\n"
        f"## Prior delta: reverse\n\n{prior}\n\n"
        f"## Prior delta: remain unaffected\n\n{prior}\n\n"
        "## Final intervention text\n\nRe-examine the cited dependency and bound its effects without changing unrelated commitments.\n\n"
        f"## Semantic rubric\n\n{rubric}\n\n"
        f"{target_fields}\n\n"
        f"## No-valid-target basis\n\n{no_target_basis}\n"
    )


def complete_gate_files(run_dir: Path, intervention_id: str, *, no_target: bool = False) -> None:
    gate = run_dir / intervention_id.lower()
    write_text(gate / "examiner_review.md", _completed_review("Independent Sol 5.6 xhigh examination"))
    write_text(gate / "researcher_review.md", _completed_review("Human researcher review"))
    write_text(gate / "reconciliation.md", _completed_reconciliation(intervention_id, no_target=no_target))


def complete_o3_assessment(run_dir: Path) -> None:
    rubric = "\n".join(
        f"{item['dimension']}: 2" for item in protocol.SEMANTIC_HUMAN_RUBRIC
    )
    target_fields = "\n\n".join(
        (
            f"## {intervention_id} final diagnostic state\n\nRESOLVED\n\n"
            f"## {intervention_id} final diagnostic evidence\n\nO3 preserves the repaired target and its revision rule.\n\n"
            f"## {intervention_id} hard contradiction present\n\nNO"
        )
        for intervention_id in protocol.INTERVENTIONS
    )
    write_text(
        run_dir / "o3_assessment.md",
        "# Human-only O3 assessment\n\n"
        "Assessed by: human_researcher\n\n"
        "## Assessment basis\n\nO3 propagates and bounds all three sealed targets.\n\n"
        f"## Semantic rubric\n\n{rubric}\n\n{target_fields}\n",
    )


@pytest.fixture
def harness(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_dir = tmp_path / "r"
    fake = FakeGenerateContent()
    with (
        mock.patch.object(pilot, "_load_definition", return_value=definition()),
        mock.patch.object(pilot, "_assert_private_root"),
        mock.patch.object(pilot, "execution_output_dir", return_value=run_dir),
    ):
        yield repo, tmp_path / "freeze", fake


def _checkpoint(repo: Path, freeze: Path, fake: FakeGenerateContent, checkpoint: str):
    return pilot.execute_checkpoint(
        repo_root=repo, freeze_dir=freeze, freeze_id=FREEZE_ID,
        checkpoint=checkpoint, api_key="test", transport=fake,
    )


def _seal(repo: Path, freeze: Path, intervention_id: str):
    return pilot.seal_intervention(
        repo_root=repo, freeze_dir=freeze, freeze_id=FREEZE_ID,
        intervention_id=intervention_id,
    )


def test_exact_c0_i1_c1_i2_c2_i3_c3_and_twelve_executions(harness):
    repo, freeze, fake = harness
    run_dir, _ = _checkpoint(repo, freeze, fake, "C0")
    for checkpoint, intervention in (("C1", "I1"), ("C2", "I2"), ("C3", "I3")):
        complete_gate_files(run_dir, intervention)
        _seal(repo, freeze, intervention)
        _checkpoint(repo, freeze, fake, checkpoint)

    complete_o3_assessment(run_dir)
    pilot.seal_o3_assessment(
        repo_root=repo, freeze_dir=freeze, freeze_id=FREEZE_ID,
    )

    pilot.run_primary_executions(
        repo_root=repo, freeze_dir=freeze, freeze_id=FREEZE_ID,
        api_key="test", transport=fake,
    )
    verified = pilot.verify_archive(
        repo_root=repo, freeze_dir=freeze, freeze_id=FREEZE_ID,
        through="final",
    )

    assert verified == {"valid": True, "through": "final", "physical_call_count": 20}
    assert fake.planning_count == 4
    assert fake.observation_count == 4
    assert fake.execution_count == 12
    assert len(protocol.build_execution_schedule()) == 12

    # O outputs are measurements, never live planning or execution history.
    model_facing_noninspection = [
        body for body in fake.bodies
        if body["contents"][-1]["parts"][0]["text"] != protocol.PRIMARY_INSPECTION_PROMPT
    ]
    assert all("OBSERVATION::" not in json.dumps(body) for body in model_facing_noninspection)

    # X2 and X3 receive cumulative *safe* traces, never native carriers.
    x2 = (run_dir / "i2/examiner_packet.md").read_text(encoding="utf-8")
    x3 = (run_dir / "i3/examiner_packet.md").read_text(encoding="utf-8")
    assert "OBSERVATION::1" in x2 and "OBSERVATION::2" in x2
    assert "OBSERVATION::1" in x3 and "OBSERVATION::3" in x3
    assert "native-signature" not in x2 + x3
    assert "thoughtSignature" not in x2 + x3


def test_max_tokens_is_replayable_unobserved_and_continues():
    payload = {
        "modelVersion": protocol.MODEL,
        "candidates": [{
            "finishReason": "MAX_TOKENS",
            "content": {"role": "model", "parts": [
                {"thoughtSignature": "signed-state"}, {"text": "READY"},
            ]},
        }],
    }
    result = GenerateContentHttpResult(
        http_status=200, payload=payload, raw_body=json.dumps(payload),
        transport_error="", response_parse_error="", elapsed_ms=1,
    )
    evaluated = pilot.evaluate_planning_turn(result)
    assert evaluated.carrier_replayable is True
    assert evaluated.readiness_observation == protocol.UNOBSERVED_TRUNCATED
    assert evaluated.controller_action == pilot.ACTION_CONTINUE


def test_hard_contradiction_cannot_be_resolved(tmp_path: Path):
    path = tmp_path / "reconciliation.md"
    text = _completed_reconciliation("I2").replace(
        "## I1 diagnostic state\n\nBOUNDED", "## I1 diagnostic state\n\nRESOLVED"
    ).replace("## I1 hard contradiction present\n\nNO", "## I1 hard contradiction present\n\nYES")
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="contradicted target RESOLVED"):
        pilot._parse_reconciliation(path, intervention_id="I2")


def test_no_target_is_terminal_and_cannot_reach_c1(harness):
    repo, freeze, fake = harness
    run_dir, _ = _checkpoint(repo, freeze, fake, "C0")
    complete_gate_files(run_dir, "I1", no_target=True)
    pilot.close_no_target(
        repo_root=repo, freeze_dir=freeze, freeze_id=FREEZE_ID,
        intervention_id="I1",
    )
    assert pilot.verify_archive(
        repo_root=repo, freeze_dir=freeze, freeze_id=FREEZE_ID, through="i1"
    )["terminal"] == "NO_VALID_TARGET"
    with pytest.raises(ValueError, match="no-target"):
        _checkpoint(repo, freeze, fake, "C1")


def test_examiner_review_provenance_is_external_sol_not_codex(tmp_path: Path):
    packet_hash = "a" * 64
    path = tmp_path / "examiner_review.md"
    path.write_text(_completed_review("Independent Sol 5.6 xhigh examination"), encoding="utf-8")
    stream = pilot._parse_review(path, reviewer="reviewer_B", packet_hash=packet_hash)
    assert stream["provenance"] == {
        **protocol.REVIEWER_PROVENANCE_REQUIREMENTS["reviewer_B"],
        "input_sha256": packet_hash,
    }
    assert stream["provenance"]["identity"] == "independent_sol_chatgpt_reviewer_channel"


def test_truncated_signed_checkpoint_is_replayed_exactly_then_ready(harness):
    repo, freeze, _unused = harness
    fake = TruncateThenReady()
    run_dir, runtime = _checkpoint(repo, freeze, fake, "C0")
    assert runtime.ready_checkpoint is not None
    assert len(runtime.checkpoints) == 2
    assert runtime.checkpoints[0].readiness_observation == protocol.UNOBSERVED_TRUNCATED
    assert fake.first_planning_content is not None
    second_planning = fake.bodies[1]
    assert second_planning["contents"][1] == fake.first_planning_content
    assert second_planning["contents"][:-1] == runtime.checkpoints[0].full_history
    assert pilot.verify_archive(
        repo_root=repo, freeze_dir=freeze, freeze_id=FREEZE_ID, through="c0"
    )["physical_call_count"] == 4
    private = json.loads((run_dir / "c0_planning.private.json").read_text(encoding="utf-8"))
    assert private["checkpoints"][0]["response_steps"][0] == fake.first_planning_content


def test_examiner_packet_tamper_is_rejected_by_reverse_derivation(harness):
    repo, freeze, fake = harness
    run_dir, _ = _checkpoint(repo, freeze, fake, "C0")
    packet = run_dir / "i1/examiner_packet.md"
    packet.write_text(packet.read_text(encoding="utf-8") + "\ncontamination\n", encoding="utf-8")
    with pytest.raises(ValueError, match="examiner packet"):
        pilot.verify_archive(
            repo_root=repo, freeze_dir=freeze, freeze_id=FREEZE_ID, through="c0"
        )


def test_sealed_examiner_output_tamper_is_rejected(harness):
    repo, freeze, fake = harness
    run_dir, _ = _checkpoint(repo, freeze, fake, "C0")
    complete_gate_files(run_dir, "I1")
    _seal(repo, freeze, "I1")
    examiner = run_dir / "i1/examiner_review.md"
    examiner.write_text(examiner.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
    with pytest.raises(ValueError, match="provenance|binding|Markdown"):
        pilot.verify_archive(
            repo_root=repo, freeze_dir=freeze, freeze_id=FREEZE_ID, through="i1"
        )


def test_cli_exposes_all_frozen_stages_and_no_neutral_lane():
    parser = pilot._parser()
    commands = {
        "run-c0", "run-c1", "run-c2", "run-c3",
        "seal-i1", "seal-i2", "seal-i3",
        "close-i1-no-target", "close-i2-no-target", "close-i3-no-target",
        "seal-o3-assessment", "run-primary-executions", "verify",
    }
    subparser_action = next(action for action in parser._actions if action.dest == "command")
    assert set(subparser_action.choices) == commands
    assert "neutral" not in set(subparser_action.choices)


def test_unfilled_markdown_review_is_rejected(tmp_path: Path):
    path = tmp_path / "examiner_review.md"
    path.write_text(pilot._review_template("Independent Sol 5.6 xhigh examination"), encoding="utf-8")
    with pytest.raises(ValueError, match="template markers"):
        pilot._parse_review(path, reviewer="reviewer_B", packet_hash="a" * 64)


def test_replayable_unsupported_finish_is_technical_not_a_checkpoint(tmp_path: Path):
    payload = {
        "modelVersion": protocol.MODEL,
        "candidates": [{
            "finishReason": "SAFETY",
            "content": {"role": "model", "parts": [
                {"thoughtSignature": "signed-but-unsupported"}, {"text": "READY"},
            ]},
        }],
    }
    raw = json.dumps(payload)
    result = GenerateContentHttpResult(
        http_status=200, payload=payload, raw_body=raw,
        transport_error="", response_parse_error="", elapsed_ms=1,
        raw_body_bytes=raw.encode("utf-8"), response_headers={},
    )

    class OneResultStore:
        def invoke_logical(self, *, label, body):
            del label, body
            return result, {
                "logical_request_id": "call", "attempt_count": 1,
                "selected_physical_call_number": 1,
                "selected_response_wire_sha256": "b" * 64,
                "selection_reason": "first_attempt_nonretryable",
                "request_wire_sha256": "c" * 64,
            }

    evaluated = pilot.evaluate_planning_turn(result)
    assert evaluated.carrier_replayable is True
    assert evaluated.controller_action == pilot.ACTION_TERMINATE_TECHNICAL
    runtime, private_rows, public_rows = pilot.run_checkpoint_round(
        checkpoint="C0",
        first_body=protocol.initial_planning_body(task_text="task"),
        store=OneResultStore(), run_dir=tmp_path, expected_parent_history=None,
    )
    assert runtime.terminal == "PLANNING_TERMINATED_TECHNICAL"
    assert runtime.checkpoints == []
    assert private_rows == public_rows == []


def test_i3_terminal_records_run_relative_seal_path(tmp_path: Path):
    run_dir = tmp_path / "run"
    gate = run_dir / "i3"
    gate.mkdir(parents=True)
    claim_path = gate / "disposition_claim.json"
    claim = {
        "freeze_id": FREEZE_ID, "claim_id": pilot.generate_opaque_id(),
    }
    claim_path.write_text("{}", encoding="utf-8")
    seal_path = gate / "lock.json"
    seal_path.write_text("{}", encoding="utf-8")
    terminal = pilot._terminal(
        gate / "disposition_terminal.json", schema="test",
        claim_path=claim_path, claim=claim, status="COMPLETED",
        sealed_path=seal_path,
    )
    assert terminal["sealed_path"] == "i3/lock.json"


def test_o3_human_assessment_adds_no_model_call_and_gates_execution(harness):
    repo, freeze, fake = harness
    run_dir, _ = _checkpoint(repo, freeze, fake, "C0")
    for checkpoint, intervention in (("C1", "I1"), ("C2", "I2"), ("C3", "I3")):
        complete_gate_files(run_dir, intervention)
        _seal(repo, freeze, intervention)
        _checkpoint(repo, freeze, fake, checkpoint)
    calls_before = len(fake.bodies)
    with pytest.raises(ValueError):
        pilot.run_primary_executions(
            repo_root=repo, freeze_dir=freeze, freeze_id=FREEZE_ID,
            api_key="test", transport=fake,
        )
    assert len(fake.bodies) == calls_before
    complete_o3_assessment(run_dir)
    pilot.seal_o3_assessment(
        repo_root=repo, freeze_dir=freeze, freeze_id=FREEZE_ID,
    )
    assert len(fake.bodies) == calls_before
    record = json.loads((run_dir / "o3_assessment.json").read_text(encoding="utf-8"))
    assert list(record["assessment"]["rubric_scores"]) == [item["dimension"] for item in protocol.SEMANTIC_HUMAN_RUBRIC]
    assert set(record["assessment"]["target_diagnostic_states"]) == {"I1", "I2", "I3"}
    assert record["assessment_id"] == protocol.FINAL_O3_ASSESSMENT_ID
    assert pilot.verify_archive(
        repo_root=repo, freeze_dir=freeze, freeze_id=FREEZE_ID, through="o3"
    )["physical_call_count"] == 8


def test_o3_assessment_sealed_at_must_follow_claim_and_precede_lock(harness):
    repo, freeze, fake = harness
    run_dir, _ = _checkpoint(repo, freeze, fake, "C0")
    for checkpoint, intervention in (("C1", "I1"), ("C2", "I2"), ("C3", "I3")):
        complete_gate_files(run_dir, intervention)
        _seal(repo, freeze, intervention)
        _checkpoint(repo, freeze, fake, checkpoint)
    complete_o3_assessment(run_dir)
    pilot.seal_o3_assessment(
        repo_root=repo, freeze_dir=freeze, freeze_id=FREEZE_ID,
    )

    # Coordinate all direct byte-hash dependants so only chronology exposes the
    # forged pre-claim runtime timestamp.
    record_path = run_dir / "o3_assessment.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["sealed_at"] = "2000-01-01T00:00:00Z"
    pilot.write_json(record_path, record)
    lock_path = run_dir / "o3_assessment.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["assessment_record_bytes_sha256"] = pilot._sha_bytes(record_path.read_bytes())
    pilot.write_json(lock_path, lock)
    terminal_path = run_dir / "o3_assessment_terminal.json"
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    terminal["sealed_bytes_sha256"] = pilot._sha_bytes(lock_path.read_bytes())
    pilot.write_json(terminal_path, terminal)

    with pytest.raises(ValueError, match="O3 assessment timestamp order"):
        pilot.verify_archive(
            repo_root=repo, freeze_dir=freeze, freeze_id=FREEZE_ID, through="o3"
        )
