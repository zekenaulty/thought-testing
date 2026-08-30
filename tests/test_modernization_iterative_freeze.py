import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from thoughtlab.reasoningEngineering import modernization_iterative_freeze as freeze
from thoughtlab.reasoningEngineering import modernization_iterative_protocol as protocol


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_object(freeze_dir: Path, name: str) -> dict[str, object]:
    value = freeze.strict_json_loads(
        (freeze_dir / name).read_text(encoding="utf-8")
    )
    assert isinstance(value, dict)
    return value


def _rewrite_bound_freeze(
    freeze_dir: Path, *, manifest: dict[str, object]
) -> dict[str, object]:
    definition = _load_object(freeze_dir, freeze.DEFINITION_NAME)
    payload_values = {
        freeze.DEFINITION_NAME: definition,
        freeze.MANIFEST_NAME: manifest,
        freeze.PREREGISTRATION_NAME: freeze.build_preregistration(
            definition, manifest
        ),
        freeze.VALIDATION_REPORT_NAME: freeze.build_validation_report(
            definition, manifest, REPO_ROOT
        ),
    }
    payload_bytes = {
        name: freeze._json_bytes(value) for name, value in payload_values.items()
    }
    for name, data in payload_bytes.items():
        (freeze_dir / name).write_bytes(data)
    lock = freeze._lock_for_payload_bytes(payload_bytes)
    (freeze_dir / freeze.LOCK_NAME).write_bytes(freeze._json_bytes(lock))
    return lock


def test_prepare_is_deterministic_transport_free_and_exactly_five_files() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        first_dir = root / "first"
        second_dir = root / "second"
        with patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("freeze preparation attempted transport"),
        ):
            first = freeze.prepare_freeze(
                repo_root=REPO_ROOT, freeze_dir=first_dir
            )
            second = freeze.prepare_freeze(
                repo_root=REPO_ROOT, freeze_dir=second_dir
            )

        assert first == second
        assert sorted(path.name for path in first_dir.iterdir()) == sorted(
            freeze.SAFE_FREEZE_FILES
        )
        assert len(freeze.SAFE_FREEZE_FILES) == 5
        result = freeze.verify_freeze(
            freeze_dir=first_dir,
            repo_root=REPO_ROOT,
            expected_freeze_id=first["freeze_id"],
        )
        assert result["valid"] is True
        assert result["errors"] == []

        validation = _load_object(first_dir, freeze.VALIDATION_REPORT_NAME)
        assert validation["preparation_transport_path_present"] is False
        assert validation["preparation_credential_access_path_present"] is False
        assert validation["raw_provider_artifacts_present"] is False
        assert validation[
            "final_human_O3_assessment_gates_execution_without_X4_or_I4"
        ] is True


def test_source_closure_binds_iterative_and_shared_occurrence_code() -> None:
    required = {
        "thoughtlab/gemini_generate_content.py",
        "thoughtlab/opaque_ids.py",
        "thoughtlab/raw_call_store.py",
        (
            "thoughtlab/reasoningEngineering/"
            "MODERNIZATION_ITERATIVE_REASONING_ENGINEERING_DESIGN.md"
        ),
        "thoughtlab/reasoningEngineering/modernization_protocol.py",
        "thoughtlab/reasoningEngineering/modernization_iterative_protocol.py",
        "thoughtlab/reasoningEngineering/modernization_iterative_pilot.py",
        "thoughtlab/reasoningEngineering/modernization_iterative_freeze.py",
        "tests/test_modernization_iterative_protocol.py",
        "tests/test_modernization_iterative_pilot.py",
        "tests/test_modernization_iterative_freeze.py",
    }
    dossier = {
        f"{protocol.base.DOSSIER_DIRECTORY}/{name}"
        for name in protocol.base.DOSSIER_FILES
    }

    assert required <= set(freeze.SOURCE_FILES)
    assert dossier <= set(freeze.SOURCE_FILES)
    assert len(freeze.SOURCE_FILES) == len(set(freeze.SOURCE_FILES))


def test_preregistration_binds_adaptive_trajectory_tomography_and_bounds() -> None:
    definition = protocol.build_experiment_definition(REPO_ROOT)
    manifest = freeze.build_manifest(REPO_ROOT)
    preregistration = freeze.build_preregistration(definition, manifest)
    errors = freeze._iterative_semantics_errors(definition)

    assert errors == []
    assert preregistration["primary_trajectory"]["ordered_chain"] == [
        "C0",
        "O0",
        "X1",
        "I1",
        "C1",
        "O1",
        "X2",
        "I2",
        "C2",
        "O2",
        "X3",
        "I3",
        "C3",
        "O3",
    ]
    tomography = preregistration["tomography"]
    assert tomography["status"] == "experiment_protocol_defined_primary_operator"
    assert tomography["distinct_from_unmodified_live_continuation"] is True
    assert tomography["every_replayable_planning_checkpoint_is_inspected"] is True
    interventions = preregistration["adaptive_human_interventions"]
    assert interventions["exact_treatment_text_is_not_preloaded"] is True
    assert interventions["I1"]["selection_after"] == "eligible O0 and recorded X1"
    assert interventions["I2"]["selection_after"] == "eligible O1 and recorded X2"
    assert interventions["I2"]["must_record_prior_delta_disposition"] is True
    assert interventions["I3"]["selection_after"] == "eligible O2 and recorded X3"
    assert interventions["I3"]["must_reintegrate_the_cumulative_trajectory"] is True
    assert interventions["review_streams"]["B"]["model"] == "gpt-5.6-sol"
    assert interventions["reconciliation"][
        "only_reconciled_intervention_text_is_model_facing"
    ] is True
    assert preregistration["gemini_logical_call_minimum"] == 20
    assert preregistration["gemini_logical_call_maximum"] == 60
    assert preregistration["gemini_physical_call_maximum"] == 180
    assert preregistration["external_examiner_turns_exact"] == 3
    assert definition["planned_calls"]["inspection_maximum"] == 24
    assert preregistration["matched_execution"]["execution_calls"] == 12
    assert preregistration["private_measurement_material"][
        "semantic_rubric_dimensions"
    ] == 6
    assert preregistration["private_measurement_material"][
        "diagnostic_states"
    ][-1] == "RATIONALIZED"
    assessments = preregistration["observation_assessments"]
    assert assessments["observations_scored"] == ["O0", "O1", "O2", "O3"]
    assert len(assessments["same_rubric_dimensions"]) == 6
    assert assessments["target_diagnostic_states"]["O3"] == ["I1", "I2", "I3"]
    final_O3 = assessments["final_O3_assessment"]
    assert final_O3["human_only_non_examiner"] is True
    assert final_O3["record_keys"] == sorted(
        protocol.RUNTIME_FINAL_O3_ASSESSMENT_KEYS
    )
    assert final_O3["creates_no_X4_or_I4_or_examiner_turn"] is True
    assert final_O3["must_be_sealed_before_execution_gate_opens"] is True
    assert preregistration["matched_execution"][
        "requires_eligible_O3_and_final_human_assessment_seal"
    ] is True


def test_semantic_validation_rejects_bypassing_final_O3_human_gate() -> None:
    definition = protocol.build_experiment_definition(REPO_ROOT)
    definition["state_machine"][
        "execution_gate_requires_eligible_O3_and_final_human_assessment"
    ] = False
    definition["execution"][
        "begins_only_after_O3_is_eligible_and_final_assessment_is_sealed"
    ] = False

    errors = freeze._iterative_semantics_errors(definition)

    assert any("final human assessment" in error for error in errors)
    assert any("final O3 assessment" in error for error in errors)


def test_strict_json_rejects_duplicates_and_all_nonfinite_forms() -> None:
    with pytest.raises(freeze.DuplicateJsonKey):
        freeze.strict_json_loads('{"a":1,"a":2}')
    for text in ('{"a":NaN}', '{"a":Infinity}', '{"a":-Infinity}', '{"a":1e9999}'):
        with pytest.raises(ValueError, match="non-finite"):
            freeze.strict_json_loads(text)


def test_verification_fails_closed_on_payload_tamper() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        freeze_dir = Path(temporary) / "freeze"
        lock = freeze.prepare_freeze(repo_root=REPO_ROOT, freeze_dir=freeze_dir)
        path = freeze_dir / freeze.DEFINITION_NAME
        value = json.loads(path.read_text(encoding="utf-8"))
        value["model"] = "different-model"
        path.write_text(json.dumps(value), encoding="utf-8")

        result = freeze.verify_freeze(
            freeze_dir=freeze_dir,
            repo_root=REPO_ROOT,
            expected_freeze_id=lock["freeze_id"],
        )

    assert result["valid"] is False
    assert any("lock" in error or "definition" in error for error in result["errors"])


def test_verification_rejects_extra_and_missing_entries() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        extra_dir = root / "extra"
        freeze.prepare_freeze(repo_root=REPO_ROOT, freeze_dir=extra_dir)
        (extra_dir / "unexpected.json").write_text("{}", encoding="utf-8")
        extra = freeze.verify_freeze(freeze_dir=extra_dir, repo_root=REPO_ROOT)

        missing_dir = root / "missing"
        freeze.prepare_freeze(repo_root=REPO_ROOT, freeze_dir=missing_dir)
        (missing_dir / freeze.PREREGISTRATION_NAME).unlink()
        missing = freeze.verify_freeze(freeze_dir=missing_dir, repo_root=REPO_ROOT)

    assert extra["valid"] is False
    assert any("allowlist" in error for error in extra["errors"])
    assert missing["valid"] is False
    assert any(
        "missing" in error or "allowlist" in error for error in missing["errors"]
    )


def test_prepare_refuses_to_overwrite_nonempty_directory() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        freeze_dir = Path(temporary) / "freeze"
        freeze_dir.mkdir()
        owned = freeze_dir / "owned.txt"
        owned.write_text("do not overwrite", encoding="utf-8")

        with pytest.raises(FileExistsError, match="nonempty"):
            freeze.prepare_freeze(repo_root=REPO_ROOT, freeze_dir=freeze_dir)

        assert owned.read_text(encoding="utf-8") == "do not overwrite"


def test_freezer_source_has_no_live_transport_or_secret_lookup() -> None:
    source = (
        REPO_ROOT
        / "thoughtlab/reasoningEngineering/modernization_iterative_freeze.py"
    ).read_text(encoding="utf-8")
    forbidden_fragments = (
        "urlopen(",
        "generate_content_request(",
        "post_interaction",
        "gemini_interactions",
        "API" + "_KEY",
    )

    assert all(fragment not in source for fragment in forbidden_fragments)
    assert freeze.build_manifest(REPO_ROOT)["experiment_id"] == (
        protocol.EXPERIMENT_ID
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "extra_manifest_key",
        "experiment_id",
        "protocol_revision",
        "source_file_count",
        "source_record_keys",
        "source_closure",
    ),
)
def test_manifest_schema_stays_invalid_after_attacker_rebinds_lock(
    mutation: str,
) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        freeze_dir = Path(temporary) / "freeze"
        freeze.prepare_freeze(repo_root=REPO_ROOT, freeze_dir=freeze_dir)
        manifest = _load_object(freeze_dir, freeze.MANIFEST_NAME)

        if mutation == "extra_manifest_key":
            manifest["unexpected"] = True
        elif mutation == "experiment_id":
            manifest["experiment_id"] = "different_experiment"
        elif mutation == "protocol_revision":
            manifest["protocol_revision"] = "different_revision"
        elif mutation == "source_file_count":
            manifest["source_file_count"] = len(freeze.SOURCE_FILES) - 1
        elif mutation == "source_record_keys":
            records = manifest["source_files"]
            assert isinstance(records, dict)
            first_record = records[freeze.SOURCE_FILES[0]]
            assert isinstance(first_record, dict)
            first_record["unexpected"] = True
            manifest["source_closure_sha256"] = freeze._canonical_sha256(records)
        elif mutation == "source_closure":
            manifest["source_closure_sha256"] = "0" * 64
        else:  # pragma: no cover
            raise AssertionError(mutation)

        lock = _rewrite_bound_freeze(freeze_dir, manifest=manifest)
        result = freeze.verify_freeze(
            freeze_dir=freeze_dir,
            repo_root=REPO_ROOT,
            expected_freeze_id=lock["freeze_id"],
        )

    assert result["valid"] is False
    assert any("manifest" in error for error in result["errors"])


def test_verification_fails_closed_for_unreadable_directory() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        freeze_dir = Path(temporary) / "freeze"
        freeze.prepare_freeze(repo_root=REPO_ROOT, freeze_dir=freeze_dir)
        original_iterdir = Path.iterdir

        def unreadable_iterdir(path: Path):
            if path == freeze_dir:
                raise PermissionError("simulated directory denial")
            return original_iterdir(path)

        with patch.object(Path, "iterdir", new=unreadable_iterdir):
            result = freeze.verify_freeze(
                freeze_dir=freeze_dir, repo_root=REPO_ROOT
            )

    assert result["valid"] is False
    assert any("failed safely" in error for error in result["errors"])


def test_verification_detects_file_change_during_read() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        freeze_dir = Path(temporary) / "freeze"
        freeze.prepare_freeze(repo_root=REPO_ROOT, freeze_dir=freeze_dir)
        target = freeze_dir / freeze.MANIFEST_NAME
        original_read_bytes = Path.read_bytes
        changed = False

        def racing_read_bytes(path: Path) -> bytes:
            nonlocal changed
            data = original_read_bytes(path)
            if path == target and not changed:
                changed = True
                path.write_bytes(data + b"\n")
            return data

        with patch.object(Path, "read_bytes", new=racing_read_bytes):
            result = freeze.verify_freeze(
                freeze_dir=freeze_dir, repo_root=REPO_ROOT
            )

    assert changed is True
    assert result["valid"] is False
    assert any(
        "unstable" in error or "changed while being read" in error
        for error in result["errors"]
    )


def test_prepare_refuses_success_when_self_verification_fails() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        freeze_dir = Path(temporary) / "freeze"
        failed = {
            "schema_version": freeze.VERIFICATION_SCHEMA,
            "valid": False,
            "freeze_id": None,
            "errors": ["simulated verification failure"],
            "safe_file_count": 0,
        }
        with patch.object(freeze, "verify_freeze", return_value=failed):
            with pytest.raises(ValueError, match="failed self-verification"):
                freeze.prepare_freeze(
                    repo_root=REPO_ROOT, freeze_dir=freeze_dir
                )
