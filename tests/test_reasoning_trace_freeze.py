import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from thoughtlab.reasoningTraces import reasoning_trace_freeze as freeze_module
from thoughtlab.reasoningTraces import reasoning_trace_protocol as protocol


class GuardedEnvironment(dict):
    """Permit benign launch variables and fail if preparation enumerates env."""

    def __iter__(self):  # pragma: no cover - called only on regression
        raise AssertionError("freeze preparation must not enumerate the environment")

    def items(self):  # pragma: no cover - called only on regression
        raise AssertionError("freeze preparation must not enumerate the environment")

    def keys(self):  # pragma: no cover - called only on regression
        raise AssertionError("freeze preparation must not enumerate the environment")

    def get(self, key, default=None):
        allowed = {
            "PATH",
            "SystemRoot",
            "WINDIR",
            "COMSPEC",
            "PATHEXT",
            "TEMP",
            "TMP",
            "LANG",
            "LC_ALL",
        }
        if key not in allowed:
            raise AssertionError(f"unexpected environment access: {key}")
        return super().get(key, default)


def make_repo(root: Path) -> None:
    for relative in freeze_module.SOURCE_FILES:
        path = root.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"fixture source: {relative}\n".encode("utf-8"))

    actual_root = Path(protocol.__file__).resolve().parents[2]
    capsule_bytes = (actual_root / protocol.CAPSULE_RELATIVE_PATH).read_bytes()
    capsule_path = root.joinpath(*protocol.CAPSULE_RELATIVE_PATH.split("/"))
    capsule_path.parent.mkdir(parents=True, exist_ok=True)
    capsule_path.write_bytes(capsule_bytes)


def prepare(root: Path, name: str = "freeze") -> dict:
    return freeze_module.prepare_freeze(
        repo_root=root,
        freeze_dir=root / name,
        master_seed=protocol.MASTER_SEED,
    )


def test_call_store_import_closure_and_eventual_executor_are_source_bound() -> None:
    required = {
        "thoughtlab/gemini_interactions.py",
        "thoughtlab/stateTransitions/fork_pilot.py",
        "thoughtlab/stateTransitions/probes.py",
        "thoughtlab/stateTransitions/score_ground_truth.py",
        "thoughtlab/reasoningTraces/reasoning_trace_protocol.py",
        "thoughtlab/reasoningTraces/reasoning_trace_freeze.py",
        "thoughtlab/reasoningTraces/reasoning_trace_pilot.py",
    }
    assert required.issubset(set(freeze_module.SOURCE_FILES))
    assert protocol.CAPSULE_RELATIVE_PATH not in freeze_module.SOURCE_FILES


def test_prepare_is_deterministic_allowlisted_external_hash_only_and_self_verifying() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        make_repo(root)
        first = prepare(root, "freeze_a")
        second = prepare(root, "freeze_b")

        assert first["freeze_id"] == second["freeze_id"]
        freeze_dir = Path(first["freeze_dir"])
        assert sorted(path.name for path in freeze_dir.iterdir()) == sorted(
            freeze_module.SAFE_FREEZE_FILES
        )
        assert first["freeze_id"] == freeze_module.sha256_bytes(
            (freeze_dir / freeze_module.FREEZE_LOCK_NAME).read_bytes()
        )
        verification = freeze_module.verify_freeze(
            repo_root=root,
            freeze_dir=freeze_dir,
            expected_freeze_id=first["freeze_id"],
            verify_source=True,
        )
        assert verification["valid"], verification["errors"]
        assert verification["external_capsule_verified"] is True

        definition = freeze_module.load_frozen_object(
            freeze_dir, freeze_module.DEFINITION_NAME
        )
        manifest = freeze_module.load_frozen_object(
            freeze_dir, freeze_module.MANIFEST_NAME
        )
        preregistration = freeze_module.load_frozen_object(
            freeze_dir, freeze_module.PREREGISTRATION_NAME
        )
        assert manifest == freeze_module.create_manifest(definition)
        assert set(preregistration["source_file_bytes_sha256"]) == set(
            freeze_module.SOURCE_FILES
        )
        binding = preregistration["selected_capsule_external_binding"]
        assert binding["capsule_file_sha256"] == protocol.CAPSULE_FILE_SHA256
        assert binding["raw_signature_copied_into_freeze"] is False

        capsule = json.loads(
            (root / protocol.CAPSULE_RELATIVE_PATH).read_text(encoding="utf-8")
        )
        raw_signature = str(capsule["signed_part"]["thoughtSignature"])
        frozen_bytes = b"\n".join(path.read_bytes() for path in freeze_dir.iterdir())
        assert raw_signature.encode("utf-8") not in frozen_bytes
        assert str(capsule["prompt_text"]).encode("utf-8") not in frozen_bytes


def test_prepare_refuses_wrong_model_seed_and_nonempty_destination() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        make_repo(root)
        with pytest.raises(ValueError, match="requires model"):
            freeze_module.prepare_freeze(
                repo_root=root,
                freeze_dir=root / "wrong_model",
                model="another-model",
            )
        with pytest.raises(ValueError, match="requires master seed"):
            freeze_module.prepare_freeze(
                repo_root=root,
                freeze_dir=root / "wrong_seed",
                master_seed=protocol.MASTER_SEED + 1,
            )

        occupied = root / "occupied"
        occupied.mkdir()
        (occupied / "keep.txt").write_text("do not overwrite", encoding="utf-8")
        with pytest.raises(FileExistsError, match="refusing to overwrite"):
            prepare(root, "occupied")
        assert (occupied / "keep.txt").read_text(encoding="utf-8") == "do not overwrite"


def test_payload_tampering_and_reviewed_id_mismatch_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        make_repo(root)
        prepared = prepare(root)
        freeze_dir = Path(prepared["freeze_dir"])
        manifest_path = freeze_dir / freeze_module.MANIFEST_NAME
        manifest_path.write_bytes(manifest_path.read_bytes() + b" \n")

        verification = freeze_module.verify_freeze(
            repo_root=root,
            freeze_dir=freeze_dir,
            expected_freeze_id=prepared["freeze_id"],
        )
        assert not verification["valid"]
        assert any(
            "manifest.json: exact file-byte hash mismatch" in error
            for error in verification["errors"]
        )

        wrong_id = "0" * 64
        verification = freeze_module.verify_freeze(
            repo_root=root,
            freeze_dir=freeze_dir,
            expected_freeze_id=wrong_id,
            verify_source=False,
        )
        assert not verification["valid"]
        assert "freeze ID does not match the reviewed expected value" in verification["errors"]


def test_manifest_unknown_or_missing_keys_are_rejected_even_with_rehashed_lock() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        make_repo(root)
        prepared = prepare(root)
        freeze_dir = Path(prepared["freeze_dir"])
        manifest_path = freeze_dir / freeze_module.MANIFEST_NAME
        manifest = freeze_module.load_frozen_object(freeze_dir, freeze_module.MANIFEST_NAME)
        manifest["unknown"] = "not frozen"
        freeze_module._write_json(manifest_path, manifest)

        preregistration_path = freeze_dir / freeze_module.PREREGISTRATION_NAME
        preregistration = freeze_module.load_frozen_object(
            freeze_dir, freeze_module.PREREGISTRATION_NAME
        )
        preregistration["manifest"] = {
            "canonical_json_sha256": freeze_module.sha256_json(manifest),
            "file_bytes_sha256": freeze_module.sha256_bytes(manifest_path.read_bytes()),
        }
        freeze_module._write_json(preregistration_path, preregistration)

        lock_path = freeze_dir / freeze_module.FREEZE_LOCK_NAME
        lock = freeze_module.load_frozen_object(freeze_dir, freeze_module.FREEZE_LOCK_NAME)
        for name in freeze_module.SAFE_PAYLOAD_FILES:
            lock["files"][name] = freeze_module.sha256_bytes(
                (freeze_dir / name).read_bytes()
            )
        freeze_module._write_json(lock_path, lock)

        verification = freeze_module.verify_freeze(
            repo_root=root,
            freeze_dir=freeze_dir,
            verify_source=False,
        )
        assert not verification["valid"]
        assert any("manifest differs" in error for error in verification["errors"])


def test_external_capsule_hash_tampering_is_rejected_without_reading_external_file() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        make_repo(root)
        prepared = prepare(root)
        freeze_dir = Path(prepared["freeze_dir"])

        preregistration_path = freeze_dir / freeze_module.PREREGISTRATION_NAME
        preregistration = freeze_module.load_frozen_object(
            freeze_dir, freeze_module.PREREGISTRATION_NAME
        )
        preregistration["selected_capsule_external_binding"]["prompt_sha256"] = "0" * 64
        freeze_module._write_json(preregistration_path, preregistration)

        validation_path = freeze_dir / freeze_module.VALIDATION_REPORT_NAME
        validation = freeze_module.load_frozen_object(
            freeze_dir, freeze_module.VALIDATION_REPORT_NAME
        )
        validation["external_capsule_binding"]["prompt_sha256"] = "0" * 64
        freeze_module._write_json(validation_path, validation)

        lock_path = freeze_dir / freeze_module.FREEZE_LOCK_NAME
        lock = freeze_module.load_frozen_object(freeze_dir, freeze_module.FREEZE_LOCK_NAME)
        for name in freeze_module.SAFE_PAYLOAD_FILES:
            lock["files"][name] = freeze_module.sha256_bytes(
                (freeze_dir / name).read_bytes()
            )
        freeze_module._write_json(lock_path, lock)

        verification = freeze_module.verify_freeze(
            repo_root=root,
            freeze_dir=freeze_dir,
            verify_source=False,
        )
        assert not verification["valid"]
        assert any(
            "external binding differs from exact frozen hashes" in error
            for error in verification["errors"]
        )


def test_extra_and_runtime_entries_are_rejected() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        make_repo(root)
        prepared = prepare(root)
        freeze_dir = Path(prepared["freeze_dir"])
        raw_dir = freeze_dir / "raw"
        raw_dir.mkdir()
        (raw_dir / "provider-response.bin").write_bytes(b"private")

        verification = freeze_module.verify_freeze(
            repo_root=root,
            freeze_dir=freeze_dir,
            verify_source=False,
        )
        assert not verification["valid"]
        assert any("safe allowlist" in error for error in verification["errors"])
        assert any("forbidden runtime entries" in error for error in verification["errors"])


def test_source_and_external_capsule_drift_are_detected_but_skip_is_explicit() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        make_repo(root)
        prepared = prepare(root)
        freeze_dir = Path(prepared["freeze_dir"])

        source_path = root.joinpath(*freeze_module.SOURCE_FILES[1].split("/"))
        source_path.write_bytes(source_path.read_bytes() + b"changed\n")
        capsule_path = root / protocol.CAPSULE_RELATIVE_PATH
        capsule_path.write_bytes(capsule_path.read_bytes() + b"changed\n")

        checked = freeze_module.verify_freeze(
            repo_root=root,
            freeze_dir=freeze_dir,
            verify_source=True,
        )
        assert not checked["valid"]
        assert "current executable source bytes differ from the freeze" in checked["errors"]
        assert any("external capsule" in error for error in checked["errors"])

        unchecked = freeze_module.verify_freeze(
            repo_root=root,
            freeze_dir=freeze_dir,
            verify_source=False,
        )
        assert unchecked["valid"], unchecked["errors"]
        assert unchecked["external_capsule_verified"] is False


def test_links_or_reparse_points_are_rejected_for_payloads_and_sources() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        make_repo(root)
        prepared = prepare(root)
        freeze_dir = Path(prepared["freeze_dir"])
        real_detector = freeze_module._is_link_or_reparse_point

        def payload_link(path: Path) -> bool:
            return path.name == freeze_module.MANIFEST_NAME or real_detector(path)

        with patch.object(
            freeze_module, "_is_link_or_reparse_point", side_effect=payload_link
        ):
            verification = freeze_module.verify_freeze(
                repo_root=root,
                freeze_dir=freeze_dir,
                verify_source=False,
            )
        assert not verification["valid"]
        assert any("links and reparse points" in error for error in verification["errors"])

        def source_link(path: Path) -> bool:
            return path.name == "gemini_interactions.py" or real_detector(path)

        with patch.object(
            freeze_module, "_is_link_or_reparse_point", side_effect=source_link
        ):
            with pytest.raises(ValueError, match="link/reparse point"):
                freeze_module.prepare_freeze(
                    repo_root=root,
                    freeze_dir=root / "source_link_freeze",
                )


def test_malformed_or_incomplete_lock_never_raises_from_verify() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        make_repo(root)
        prepared = prepare(root)
        freeze_dir = Path(prepared["freeze_dir"])
        (freeze_dir / freeze_module.FREEZE_LOCK_NAME).write_bytes(b'{"files":')

        malformed = freeze_module.verify_freeze(
            repo_root=root,
            freeze_dir=freeze_dir,
            verify_source=False,
        )
        assert not malformed["valid"]
        assert malformed["errors"]

        missing = freeze_module.verify_freeze(
            repo_root=root,
            freeze_dir=root / "does-not-exist",
            verify_source=False,
        )
        assert not missing["valid"]
        assert missing["errors"]


@pytest.mark.parametrize(
    ("malformed_bytes", "expected_fragment"),
    [
        (b'{"schema_version":"one","schema_version":"two"}\n', "duplicate JSON key"),
        (b'{"value":NaN}\n', "non-finite JSON number"),
    ],
)
def test_strict_json_rejects_duplicate_keys_and_nonfinite_values(
    malformed_bytes: bytes, expected_fragment: str
) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        make_repo(root)
        prepared = prepare(root)
        freeze_dir = Path(prepared["freeze_dir"])
        manifest_path = freeze_dir / freeze_module.MANIFEST_NAME
        manifest_path.write_bytes(malformed_bytes)
        lock_path = freeze_dir / freeze_module.FREEZE_LOCK_NAME
        lock = freeze_module.load_frozen_object(freeze_dir, freeze_module.FREEZE_LOCK_NAME)
        lock["files"][freeze_module.MANIFEST_NAME] = freeze_module.sha256_bytes(
            malformed_bytes
        )
        freeze_module._write_json(lock_path, lock)

        verification = freeze_module.verify_freeze(
            repo_root=root,
            freeze_dir=freeze_dir,
            verify_source=False,
        )
        assert not verification["valid"]
        assert any(expected_fragment in error for error in verification["errors"])


def test_prepare_does_not_enumerate_credentials_or_call_transport() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        make_repo(root)
        fake_process = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        guarded = GuardedEnvironment({"PATH": "fixture-path"})
        with patch.object(freeze_module.os, "environ", guarded), patch.object(
            freeze_module.subprocess,
            "run",
            return_value=fake_process,
        ), patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("transport must not run during freeze preparation"),
        ):
            prepared = freeze_module.prepare_freeze(
                repo_root=root,
                freeze_dir=root / "no_transport",
            )
        assert prepared["valid"]

    module_source = Path(freeze_module.__file__).read_text(encoding="utf-8")
    assert "post_interaction" not in module_source
    assert "GEMINI_API_KEY" not in module_source
