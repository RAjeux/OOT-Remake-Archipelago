"""Bootstrap real-generator dependencies from synthetic, isolated AP installs."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import prepare_ap_test_env as environments


class ArchipelagoTestEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.repo, self.ap = self.base / "repo", self.base / "Archipelago"
        (self.repo / "build").mkdir(parents=True)
        (self.ap / "lib").mkdir(parents=True)
        (self.ap / "data").mkdir()
        (self.ap / "manifest.json").write_text(json.dumps({"version": [0, 6, 8], "hashes": {}}), encoding="utf-8")
        for name in environments.RUNTIME_FILES[:-1]:
            (self.ap / name).write_bytes(b"MZ-synthetic-runtime")
        with ZipFile(self.ap / "lib/library.zip", "w") as archive:
            for name in ("Generate.pyc", "Main.pyc", "NetUtils.pyc", "Utils.pyc"):
                archive.writestr(name, b"synthetic-test-data-not-executable")
        (self.ap / "lib/helper.dll").write_bytes(b"MZ-synthetic-dependency")
        (self.ap / "data/options.yaml").write_text("{}\n", encoding="utf-8")
        for name in ("custom_worlds/private.apworld", "Players/private.yaml", "output/private.apootrr",
                     "saves/progress.sav", "_persistent_storage.yaml", "host.yaml"):
            path = self.ap / name
            path.parent.mkdir(exist_ok=True)
            path.write_text("private sentinel that must stay here", encoding="utf-8")
        self.output = self.repo / "build/dependencies"
        self.root_patch = patch.object(environments, "ROOT", self.repo)
        self.root_patch.start()

    def tearDown(self):
        self.root_patch.stop()
        self.temporary.cleanup()

    def originals(self):
        return {path.relative_to(self.ap).as_posix(): path.read_bytes()
                for path in self.ap.rglob("*") if path.is_file()}

    def directory_link(self, link, target):
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as error:
            if os.name != "nt":
                self.skipTest(f"Symbolic links unavailable: {error}")
            # Directory junctions do not require the Windows symlink privilege.
            # Exercise a real reparse point rather than mocking its attributes.
            quote = lambda value: "'" + str(value).replace("'", "''") + "'"
            result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                                     "New-Item -ItemType Junction -Path " + quote(link) +
                                     " -Target " + quote(target) + " | Out-Null"],
                                    capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    def test_fresh_snapshot_is_independent_and_excludes_player_data(self):
        before = self.originals()
        result = environments.prepare_environment(self.ap, self.output)
        self.assertEqual(self.originals(), before)
        self.assertEqual(result["ap_version"], [0, 6, 8])
        self.assertTrue(result["original_files_unchanged"])
        self.assertEqual(set(path.name for path in self.output.iterdir()),
                         {*environments.RUNTIME_FILES, *environments.DATA_DIRS, environments.MARKER})
        self.assertEqual(result, environments.validate_snapshot(self.output, self.ap))
        self.assertFalse((self.output / environments.INCOMPLETE).exists())
        self.assertNotIn("private sentinel", (self.output / environments.MARKER).read_text(encoding="utf-8"))
        (self.output / "lib/helper.dll").write_bytes(b"changed private copy")
        self.assertEqual(self.originals(), before)
        with self.assertRaisesRegex(ValueError, "snapshot changed"):
            environments.validate_snapshot(self.output, self.ap)

    def test_existing_destination_is_never_overwritten(self):
        self.output.mkdir()
        sentinel = self.output / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            environments.prepare_environment(self.ap, self.output)
        self.assertEqual(sentinel.read_text(), "keep")

    def test_version_python_layout_and_library_are_required_before_creating_output(self):
        cases = (("manifest.json", json.dumps({"version": [0, 7, 0]}).encode()),
                 ("manifest.json", json.dumps({"version": [0, 6, True]}).encode()),
                 ("python313.dll", b"not a Windows runtime"),
                 ("lib/library.zip", b"not a ZIP"))
        for relative, replacement in cases:
            path = self.ap / relative
            original = path.read_bytes()
            with self.subTest(resource=relative):
                path.write_bytes(replacement)
                try:
                    with self.assertRaises(ValueError):
                        environments.prepare_environment(self.ap, self.output)
                    self.assertFalse(self.output.exists())
                finally:
                    path.write_bytes(original)
        (self.ap / "python313.dll").unlink()
        with self.assertRaises(ValueError):
            environments.prepare_environment(self.ap, self.output)
        self.assertFalse(self.output.exists())

    def test_output_bounds_use_resolved_paths_and_reject_the_installation(self):
        for output in (self.repo / "outside-build", self.repo / "build", self.ap / "private-copy"):
            with self.subTest(output=output.name), self.assertRaises(ValueError):
                environments.prepare_environment(self.ap, output)
        (self.repo / "alias").mkdir()
        aliased = self.repo / "alias/../build/dependencies"
        environments.prepare_environment(self.ap, aliased)
        self.assertEqual(environments.private_destination(aliased), self.output.resolve())
        environments.validate_snapshot(aliased, self.ap)

    def test_build_redirected_outside_checkout_is_rejected_without_touching_source_or_target(self):
        original = self.originals()
        outside = self.base / "outside-checkout"
        outside.mkdir()
        sentinel = outside / "keep.txt"
        sentinel.write_bytes(b"external sentinel")
        (self.repo / "build").rmdir()  # Empty, private fixture directory.
        self.directory_link(self.repo / "build", outside)
        for operation in (environments.prepare_environment, environments.validate_snapshot):
            with self.subTest(operation=operation.__name__):
                with patch.object(environments.shutil, "copy2") as copy:
                    with self.assertRaisesRegex(ValueError, "build folder must stay inside"):
                        if operation is environments.prepare_environment:
                            operation(self.ap, self.output)
                        else:
                            operation(self.output, self.ap)
                    copy.assert_not_called()
        self.assertEqual(self.originals(), original)
        self.assertEqual(list(outside.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_bytes(), b"external sentinel")

    def test_file_count_individual_size_and_total_size_are_bounded(self):
        for name, value, message in (("MAX_FILES", 4, "file-count"),
                                     ("MAX_FILE_BYTES", 64, "file-size"),
                                     ("MAX_TOTAL_BYTES", 64, "total-size")):
            with self.subTest(bound=name), patch.object(environments, name, value):
                with self.assertRaisesRegex(ValueError, message):
                    environments.prepare_environment(self.ap, self.output)
                self.assertFalse(self.output.exists())

    def test_source_links_cannot_copy_external_or_user_data(self):
        link = self.ap / "lib/link.dll"
        try:
            link.symlink_to(self.ap / "custom_worlds/private.apworld")
        except OSError as error:
            if os.name != "nt":
                self.skipTest(f"Symbolic links unavailable: {error}")
            link = self.ap / "lib/linked-worlds"
            self.directory_link(link, self.ap / "custom_worlds")
        with self.assertRaisesRegex(ValueError, "symbolic links or junctions"):
            environments.prepare_environment(self.ap, self.output)
        self.assertFalse(self.output.exists())

    def test_interrupted_or_changed_source_never_becomes_a_valid_snapshot(self):
        count = environments.inspect_installation(self.ap)["file_count"]
        copied, copy = 0, shutil.copy2

        def copy_then_change(source, destination):
            nonlocal copied
            result = copy(source, destination)
            copied += 1
            if copied == count:
                (self.ap / "lib/helper.dll").write_bytes(b"simulated source update")
            return result

        with patch.object(environments.shutil, "copy2", side_effect=copy_then_change):
            with self.assertRaisesRegex(ValueError, "installation changed"):
                environments.prepare_environment(self.ap, self.output)
        self.assertTrue((self.output / environments.INCOMPLETE).is_file())
        self.assertFalse((self.output / environments.MARKER).exists())
        with self.assertRaises(ValueError):
            environments.validate_snapshot(self.output)

    def test_snapshot_rejects_unexpected_root_content(self):
        environments.prepare_environment(self.ap, self.output)
        (self.output / "custom_worlds").mkdir()
        with self.assertRaisesRegex(ValueError, "unexpected root files"):
            environments.validate_snapshot(self.output)


if __name__ == "__main__":
    unittest.main()
