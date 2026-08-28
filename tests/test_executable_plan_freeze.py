import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from thoughtlab.executablePlans import executable_plan_freeze as freeze_module
from thoughtlab.executablePlans import executable_plan_protocol as protocol


class GuardedEnvironment(dict):
    """Permit only explicitly benign launch variables and forbid enumeration."""

    def __iter__(self):  # pragma: no cover - called only on a regression
        raise AssertionError("freeze preparation must not enumerate the environment")

    def items(self):  # pragma: no cover - called only on a regression
        raise AssertionError("freeze preparation must not enumerate the environment")

    def keys(self):  # pragma: no cover - called only on a regression
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


class ExecutablePlanFreezeTests(unittest.TestCase):
    def make_repo(self, root: Path) -> None:
        for relative in freeze_module.SOURCE_FILES:
            path = root.joinpath(*relative.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"fixture source: {relative}\n".encode("utf-8"))

    def prepare(self, root: Path, name: str = "freeze", seed: int = 916_331):
        return freeze_module.prepare_freeze(
            repo_root=root,
            freeze_dir=root / name,
            master_seed=seed,
        )

    def test_shared_call_store_import_closure_is_source_bound(self):
        required = {
            "thoughtlab/__init__.py",
            "thoughtlab/gemini_interactions.py",
            "thoughtlab/opaque_ids.py",
            "thoughtlab/stateTransitions/__init__.py",
            "thoughtlab/stateTransitions/fork_pilot.py",
            "thoughtlab/stateTransitions/probes.py",
            "thoughtlab/stateTransitions/score_ground_truth.py",
        }
        self.assertTrue(required.issubset(set(freeze_module.SOURCE_FILES)))

    def test_prepare_is_deterministic_allowlisted_and_self_verifying(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_repo(root)
            first = self.prepare(root, "freeze_a")
            second = self.prepare(root, "freeze_b")

            self.assertEqual(first["freeze_id"], second["freeze_id"])
            freeze_dir = Path(first["freeze_dir"])
            self.assertEqual(
                sorted(path.name for path in freeze_dir.iterdir()),
                sorted(freeze_module.SAFE_FREEZE_FILES),
            )
            self.assertEqual(
                first["freeze_id"],
                freeze_module.sha256_bytes(
                    (freeze_dir / freeze_module.FREEZE_LOCK_NAME).read_bytes()
                ),
            )
            verification = freeze_module.verify_freeze(
                repo_root=root,
                freeze_dir=freeze_dir,
                expected_freeze_id=first["freeze_id"],
                verify_source=True,
            )
            self.assertTrue(verification["valid"], verification["errors"])

            definition = protocol.strict_json_loads(
                (freeze_dir / "experiment_definition.json").read_text("utf-8")
            )
            manifest = protocol.strict_json_loads(
                (freeze_dir / "manifest.json").read_text("utf-8")
            )
            self.assertEqual(manifest, protocol.create_execution_manifest(definition))
            preregistration = protocol.strict_json_loads(
                (freeze_dir / "preregistration.json").read_text("utf-8")
            )
            self.assertEqual(
                set(preregistration["source_file_bytes_sha256"]),
                set(freeze_module.SOURCE_FILES),
            )

    def test_prepare_refuses_wrong_model_and_nonempty_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_repo(root)
            with self.assertRaisesRegex(ValueError, "requires model"):
                freeze_module.prepare_freeze(
                    repo_root=root,
                    freeze_dir=root / "wrong_model",
                    master_seed=7,
                    model="another-model",
                )
            occupied = root / "occupied"
            occupied.mkdir()
            (occupied / "keep.txt").write_text("do not overwrite", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
                freeze_module.prepare_freeze(
                    repo_root=root,
                    freeze_dir=occupied,
                    master_seed=7,
                )
            self.assertEqual(
                (occupied / "keep.txt").read_text(encoding="utf-8"),
                "do not overwrite",
            )

    def test_payload_tampering_and_reviewed_id_mismatch_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_repo(root)
            prepared = self.prepare(root)
            freeze_dir = Path(prepared["freeze_dir"])
            manifest_path = freeze_dir / "manifest.json"
            manifest_path.write_bytes(manifest_path.read_bytes() + b" \n")

            verification = freeze_module.verify_freeze(
                repo_root=root,
                freeze_dir=freeze_dir,
                expected_freeze_id=prepared["freeze_id"],
            )
            self.assertFalse(verification["valid"])
            self.assertTrue(
                any("manifest.json: exact file-byte hash mismatch" in error for error in verification["errors"]),
                verification["errors"],
            )

            wrong_id = "0" * 64
            verification = freeze_module.verify_freeze(
                repo_root=root,
                freeze_dir=freeze_dir,
                expected_freeze_id=wrong_id,
                verify_source=False,
            )
            self.assertFalse(verification["valid"])
            self.assertIn(
                "freeze ID does not match the reviewed expected value",
                verification["errors"],
            )

    def test_extra_and_runtime_entries_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_repo(root)
            prepared = self.prepare(root)
            freeze_dir = Path(prepared["freeze_dir"])
            raw_dir = freeze_dir / "raw"
            raw_dir.mkdir()
            (raw_dir / "provider-response.bin").write_bytes(b"private")

            verification = freeze_module.verify_freeze(
                repo_root=root,
                freeze_dir=freeze_dir,
                verify_source=False,
            )
            self.assertFalse(verification["valid"])
            self.assertTrue(
                any("safe allowlist" in error for error in verification["errors"]),
                verification["errors"],
            )
            self.assertTrue(
                any("forbidden runtime entries" in error for error in verification["errors"]),
                verification["errors"],
            )

    def test_source_byte_drift_is_detected_but_can_be_explicitly_skipped(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_repo(root)
            prepared = self.prepare(root)
            freeze_dir = Path(prepared["freeze_dir"])
            source_path = root.joinpath(*freeze_module.SOURCE_FILES[1].split("/"))
            source_path.write_bytes(source_path.read_bytes() + b"changed\n")

            checked = freeze_module.verify_freeze(
                repo_root=root,
                freeze_dir=freeze_dir,
                verify_source=True,
            )
            self.assertFalse(checked["valid"])
            self.assertIn(
                "current executable source bytes differ from the freeze",
                checked["errors"],
            )
            unchecked = freeze_module.verify_freeze(
                repo_root=root,
                freeze_dir=freeze_dir,
                verify_source=False,
            )
            self.assertTrue(unchecked["valid"], unchecked["errors"])

    def test_links_or_reparse_points_are_rejected_for_payloads_and_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_repo(root)
            prepared = self.prepare(root)
            freeze_dir = Path(prepared["freeze_dir"])
            real_detector = freeze_module._is_link_or_reparse_point

            def payload_link(path: Path) -> bool:
                return path.name == "manifest.json" or real_detector(path)

            with patch.object(
                freeze_module,
                "_is_link_or_reparse_point",
                side_effect=payload_link,
            ):
                verification = freeze_module.verify_freeze(
                    repo_root=root,
                    freeze_dir=freeze_dir,
                    verify_source=False,
                )
            self.assertFalse(verification["valid"])
            self.assertTrue(
                any("links and reparse points are forbidden" in error for error in verification["errors"]),
                verification["errors"],
            )

            def source_link(path: Path) -> bool:
                return path.name == "opaque_ids.py" or real_detector(path)

            with patch.object(
                freeze_module,
                "_is_link_or_reparse_point",
                side_effect=source_link,
            ):
                with self.assertRaisesRegex(ValueError, "link/reparse point"):
                    freeze_module.prepare_freeze(
                        repo_root=root,
                        freeze_dir=root / "source_link_freeze",
                        master_seed=19,
                    )

    def test_malformed_or_incomplete_lock_never_raises_from_verify(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_repo(root)
            prepared = self.prepare(root)
            freeze_dir = Path(prepared["freeze_dir"])
            lock_path = freeze_dir / freeze_module.FREEZE_LOCK_NAME
            lock_path.write_bytes(b'{"files":')

            malformed = freeze_module.verify_freeze(
                repo_root=root,
                freeze_dir=freeze_dir,
                verify_source=False,
            )
            self.assertFalse(malformed["valid"])
            self.assertTrue(malformed["errors"])

            missing = freeze_module.verify_freeze(
                repo_root=root,
                freeze_dir=root / "does-not-exist",
                verify_source=False,
            )
            self.assertFalse(missing["valid"])
            self.assertTrue(missing["errors"])

    def test_strict_json_rejects_duplicate_keys_and_nonfinite_values(self):
        for name, malformed_bytes, expected_fragment in (
            (
                "duplicate",
                b'{"schema_version":"one","schema_version":"two"}\n',
                "duplicate JSON key",
            ),
            ("nonfinite", b'{"value":NaN}\n', "non-finite JSON number"),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.make_repo(root)
                prepared = self.prepare(root)
                freeze_dir = Path(prepared["freeze_dir"])
                manifest_path = freeze_dir / "manifest.json"
                manifest_path.write_bytes(malformed_bytes)
                lock_path = freeze_dir / freeze_module.FREEZE_LOCK_NAME
                lock = protocol.strict_json_loads(lock_path.read_text("utf-8"))
                lock["files"]["manifest.json"] = freeze_module.sha256_bytes(
                    malformed_bytes
                )
                freeze_module._write_json(lock_path, lock)

                verification = freeze_module.verify_freeze(
                    repo_root=root,
                    freeze_dir=freeze_dir,
                    verify_source=False,
                )
                self.assertFalse(verification["valid"])
                self.assertTrue(
                    any(expected_fragment in error for error in verification["errors"]),
                    verification["errors"],
                )

    def test_prepare_does_not_enumerate_credentials_or_call_transport(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_repo(root)
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
                    master_seed=41,
                )
            self.assertTrue(prepared["valid"])

        module_source = Path(freeze_module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("post_interaction", module_source)
        self.assertNotIn("GEMINI_API_KEY", module_source)


if __name__ == "__main__":
    unittest.main()
