"""Exercise APWorld replacement and recovery without an Archipelago install."""
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce import app_runtime as runtime, save_bridge


def world_bytes(package="ootrr_remake", extra=None):
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(package + "/__init__.py", "# private synthetic world")
        if extra:
            archive.writestr(*extra)
    return output.getvalue()


class APWorldInstallationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bundle = self.root / "bundle"
        self.base = self.root / "user"
        self.worlds = self.root / "Archipelago/custom_worlds"
        self.worlds.mkdir(parents=True)
        self.target = self.worlds / "ootrr_remake.apworld"
        node = self.bundle / "runtime/node"
        node.mkdir(parents=True)
        (node / "node.exe").write_bytes(b"private-node")
        (node / "LICENSE").write_bytes(b"notice")
        self.archive = self.bundle / "ootrr_remake.apworld"
        self.archive.write_bytes(world_bytes())
        self.addCleanup(patch.stopall)
        patch.object(runtime, "resource_root", return_value=self.bundle).start()
        patch.object(runtime, "NODE_SHA256", hashlib.sha256(b"private-node").hexdigest()).start()

    def test_install_remembers_target_outside_the_executable_folder(self):
        runtime.install_apworld(self.worlds, base=self.base)
        with patch.dict(os.environ, {}, clear=True), patch.object(runtime, "resource_root", return_value=self.root / "removed"):
            self.assertEqual(runtime.discover_apworld_targets(self.base), [self.worlds.resolve()])
        saved = json.loads((self.base / "apworld-installations.json").read_bytes())
        self.assertEqual(saved["targets"], [str(self.worlds.resolve())])

    def test_invalid_packages_preserve_existing_world_before_runtime_install(self):
        self.target.write_bytes(b"existing")
        invalid = (b"truncated", world_bytes(extra=("VERSION", "wrong root")),
                   world_bytes(extra=("ootrr_remake/../../escape.py", "escape")),
                   world_bytes(extra=("ootrr_remake/__INIT__.py", "duplicate on Windows")))
        for raw in invalid:
            with self.subTest(raw=raw[:16]):
                self.archive.write_bytes(raw)
                with self.assertRaises(ValueError):
                    runtime.install_apworld(self.worlds, base=self.base)
                self.assertEqual(self.target.read_bytes(), b"existing")
                self.assertFalse((self.base / "tools").exists())

    def test_renamed_old_world_is_backed_up_without_touching_other_games(self):
        self.target.write_bytes(b"old canonical")
        old_alias = self.worlds / "ootrr_remake (1).apworld"
        old_raw = world_bytes(extra=("ootrr_remake/old.py", "old"))
        old_alias.write_bytes(old_raw)
        unrelated = self.worlds / "other.apworld"
        unrelated.write_bytes(world_bytes("different_game"))
        broken_other = self.worlds / "unrelated-broken.apworld"
        broken_other.write_bytes(b"not an OOT package")
        before_other = unrelated.read_bytes()
        runtime.install_apworld(self.worlds, base=self.base)
        self.assertFalse(old_alias.exists(), "Two importers for the same package must not remain active.")
        self.assertEqual(self.target.read_bytes(), self.archive.read_bytes())
        self.assertEqual(unrelated.read_bytes(), before_other)
        self.assertEqual(broken_other.read_bytes(), b"not an OOT package")
        backups = [p.read_bytes() for p in (self.base / "backups/apworld").glob("*.apworld")]
        self.assertCountEqual(backups, [b"old canonical", old_raw])

    def test_failed_replacement_restores_renamed_world_and_keeps_original(self):
        self.target.write_bytes(b"existing")
        alias = self.worlds / "older-release.apworld"
        previous = world_bytes(extra=("ootrr_remake/old.py", "old"))
        alias.write_bytes(previous)
        original_atomic = save_bridge.atomic
        def fail_only_world(path, data):
            if Path(path) == self.target:
                raise PermissionError("Synthetic locked target")
            return original_atomic(path, data)
        with patch.object(save_bridge, "atomic", side_effect=fail_only_world):
            with self.assertRaises(PermissionError):
                runtime.install_apworld(self.worlds, base=self.base)
        self.assertEqual(alias.read_bytes(), previous)
        self.assertEqual(self.target.read_bytes(), b"existing")
        self.assertFalse((self.base / "apworld-installations.json").exists())

    def test_current_world_is_reused_without_extra_backup(self):
        self.target.write_bytes(self.archive.read_bytes())
        runtime.install_apworld(self.worlds, base=self.base)
        self.assertFalse((self.base / "backups/apworld").exists())

    def test_discovery_ignores_broken_metadata_and_deduplicates_known_install(self):
        self.target.write_bytes(world_bytes())
        self.base.mkdir()
        metadata = self.base / "apworld-installations.json"
        for invalid in (b"[]", b"bad json", b"{" * (65 << 10)):
            metadata.write_bytes(invalid)
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(runtime.discover_apworld_targets(self.base), [])
            self.assertEqual(metadata.read_bytes(), invalid)
        metadata.write_text(json.dumps({"schema": 1, "targets": [str(self.worlds), str(self.worlds)]}), encoding="utf-8")
        with patch.dict(os.environ, {"ProgramData": str(self.root)}, clear=True):
            self.assertEqual(runtime.discover_apworld_targets(self.base), [self.worlds.resolve()])


if __name__ == "__main__":
    unittest.main()
