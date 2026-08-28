import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from thoughtlab.reasoningEngineering import modernization_freeze as freeze
from thoughtlab.reasoningEngineering import modernization_protocol as protocol


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_freeze_object(freeze_dir: Path, name: str) -> dict[str, object]:
    value = freeze.strict_json_loads(
        (freeze_dir / name).read_text(encoding="utf-8")
    )
    assert isinstance(value, dict)
    return value


def _rewrite_bound_freeze(
    freeze_dir: Path, *, manifest: dict[str, object]
) -> dict[str, object]:
    definition = _load_freeze_object(freeze_dir, freeze.DEFINITION_NAME)
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


def test_prepare_is_transport_free_deterministic_and_verifiable() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        first_dir = root / "first"
        second_dir = root / "second"
        with patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("freeze preparation attempted network access"),
        ):
            first = freeze.prepare_freeze(
                repo_root=REPO_ROOT,
                freeze_dir=first_dir,
            )
            second = freeze.prepare_freeze(
                repo_root=REPO_ROOT,
                freeze_dir=second_dir,
            )

        assert first == second
        assert sorted(path.name for path in first_dir.iterdir()) == sorted(
            freeze.SAFE_FREEZE_FILES
        )
        verification = freeze.verify_freeze(
            freeze_dir=first_dir,
            repo_root=REPO_ROOT,
            expected_freeze_id=first["freeze_id"],
        )
        assert verification["valid"] is True
        assert verification["errors"] == []

        definition = freeze.strict_json_loads(
            (first_dir / freeze.DEFINITION_NAME).read_text(encoding="utf-8")
        )
        validation = freeze.strict_json_loads(
            (first_dir / freeze.VALIDATION_REPORT_NAME).read_text(
                encoding="utf-8"
            )
        )
        assert definition["status"] == "prepared_unexecuted"
        assert definition["planning"]["visible_channel"] == (
            "raw_text_no_schema_no_json_envelope"
        )
        assert validation["model_facing_json_readiness_envelope_present"] is False
        assert validation["preparation_transport_path_present"] is False
        assert validation["preparation_credential_access_path_present"] is False


def test_freeze_verification_fails_closed_on_payload_tamper() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        freeze_dir = Path(temporary) / "freeze"
        lock = freeze.prepare_freeze(repo_root=REPO_ROOT, freeze_dir=freeze_dir)
        path = freeze_dir / freeze.DEFINITION_NAME
        value = json.loads(path.read_text(encoding="utf-8"))
        value["model"] = "different-model"
        path.write_text(json.dumps(value), encoding="utf-8")

        verification = freeze.verify_freeze(
            freeze_dir=freeze_dir,
            repo_root=REPO_ROOT,
            expected_freeze_id=lock["freeze_id"],
        )

    assert verification["valid"] is False
    assert any("lock" in error or "definition" in error for error in verification["errors"])


def test_freeze_verification_rejects_extra_or_missing_entries() -> None:
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
    assert any("missing" in error or "allowlist" in error for error in missing["errors"])


def test_strict_json_rejects_duplicate_keys_and_nonfinite_numbers() -> None:
    with pytest.raises(freeze.DuplicateJsonKey):
        freeze.strict_json_loads('{"a":1,"a":2}')
    with pytest.raises(ValueError, match="non-finite"):
        freeze.strict_json_loads('{"a":NaN}')
    with pytest.raises(ValueError, match="non-finite"):
        freeze.strict_json_loads('{"a":1e9999}')


def test_prepare_refuses_to_overwrite_nonempty_directory() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        freeze_dir = Path(temporary) / "freeze"
        freeze_dir.mkdir()
        (freeze_dir / "owned.txt").write_text("do not overwrite", encoding="utf-8")

        with pytest.raises(FileExistsError, match="nonempty"):
            freeze.prepare_freeze(repo_root=REPO_ROOT, freeze_dir=freeze_dir)

        assert (freeze_dir / "owned.txt").read_text(encoding="utf-8") == (
            "do not overwrite"
        )


def test_freezer_source_has_no_transport_or_credential_lookup() -> None:
    source = (REPO_ROOT / "thoughtlab/reasoningEngineering/modernization_freeze.py").read_text(
        encoding="utf-8"
    )

    assert "post_interaction" not in source
    assert "GEMINI_API_KEY" not in source
    assert "from thoughtlab.gemini_interactions" not in source
    assert "import thoughtlab.gemini_interactions" not in source
    assert protocol.EXPERIMENT_ID in freeze.build_manifest(REPO_ROOT)[
        "experiment_id"
    ]


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
def test_manifest_schema_and_bindings_remain_invalid_after_rebinding_lock(
    mutation: str,
) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        freeze_dir = Path(temporary) / "freeze"
        freeze.prepare_freeze(repo_root=REPO_ROOT, freeze_dir=freeze_dir)
        manifest = _load_freeze_object(freeze_dir, freeze.MANIFEST_NAME)

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
            manifest["source_closure_sha256"] = protocol.sha256_json(records)
        elif mutation == "source_closure":
            manifest["source_closure_sha256"] = "0" * 64
        else:  # pragma: no cover - parameter exhaustiveness guard
            raise AssertionError(mutation)

        lock = _rewrite_bound_freeze(freeze_dir, manifest=manifest)
        verification = freeze.verify_freeze(
            freeze_dir=freeze_dir,
            repo_root=REPO_ROOT,
            expected_freeze_id=lock["freeze_id"],
        )

    assert verification["valid"] is False
    assert any("manifest" in error for error in verification["errors"])


def test_verification_fails_closed_when_freeze_directory_is_unreadable() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        freeze_dir = Path(temporary) / "freeze"
        freeze.prepare_freeze(repo_root=REPO_ROOT, freeze_dir=freeze_dir)
        original_iterdir = Path.iterdir

        def unreadable_iterdir(path: Path):
            if path == freeze_dir:
                raise PermissionError("simulated directory denial")
            return original_iterdir(path)

        with patch.object(Path, "iterdir", new=unreadable_iterdir):
            verification = freeze.verify_freeze(
                freeze_dir=freeze_dir,
                repo_root=REPO_ROOT,
            )

    assert verification["valid"] is False
    assert any("failed safely" in error for error in verification["errors"])


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
            verification = freeze.verify_freeze(
                freeze_dir=freeze_dir,
                repo_root=REPO_ROOT,
            )

    assert changed is True
    assert verification["valid"] is False
    assert any(
        "unstable" in error or "changed while being read" in error
        for error in verification["errors"]
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
                    repo_root=REPO_ROOT,
                    freeze_dir=freeze_dir,
                )
