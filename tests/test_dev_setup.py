"""Source development stages private resources and preserves external app data."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import dev


def put(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


class DevelopmentSetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="source setup é ")
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        self.root = self.home / "checkout with spaces"
        self.workspace = self.root / "build/source GUI"
        put(self.root / "apworld/ootrr_remake/__init__.py", b"# synthetic APWorld\n")
        for name in dev.build.WORLD_FILES:
            put(self.root / "client/ootrr_triforce" / name, b"synthetic " + name.encode())
        for name in dev.build.HOST_FILES:
            put(self.root / "native" / name, b"synthetic host")
        library = b"synthetic DLL"
        put(self.root / "prebuilt/windows-x64/archipelago.dll", library)
        header = "static const unsigned char ap_dll_sha16[32] = {" + ",".join(map(str, hashlib.sha256(library).digest())) + "};\n"
        put(self.root / "native/ootrr_ap_digest.h", header.encode())
        for name in ("LICENSE", "NOTICE", "assets/icon.png", "distribution/runtime/libzstd.dll", "distribution/runtime/LICENSE.txt"):
            put(self.root / name, b"synthetic resource")
        put(self.root / "VERSION", b"1.2.3-alpha.1\n")
        self.node, self.license = self.home / "provided node.exe", self.home / "NODE-LICENSE.txt"
        put(self.node, b"synthetic Node runtime")
        put(self.license, b"synthetic Node license")
        self.runtime = Mock(return_value=(self.node, self.license))
        self.original = self.home / "original application/OOTRR-Archipelago/profiles/room/user/save/progress.sav"
        put(self.original, b"original save must stay unchanged")

    def prepare(self, **kwargs):
        return dev.prepare_resources(self.workspace, root=self.root, runtime_provider=self.runtime, **kwargs)

    def test_first_preparation_and_repeated_source_launch_preserve_inputs_and_cached_resources(self):
        original = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        with patch.object(dev.subprocess, "run", side_effect=AssertionError("Preparation must never execute")):
            first = self.prepare()
            stamps = {path: path.stat().st_mtime_ns for path in self.workspace.rglob("*") if path.is_file()}
            second = self.prepare()
        self.assertTrue(first["world_rebuilt"])
        self.assertFalse(second["world_rebuilt"])
        self.assertEqual(second["resources_copied"], 0)
        self.assertEqual(stamps, {path: path.stat().st_mtime_ns for path in self.workspace.rglob("*") if path.is_file()})
        for path, raw in original.items():
            self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(self.original.read_bytes(), b"original save must stay unchanged")
        resources = Path(first["resources"])
        self.assertEqual((resources / "runtime/node/node.exe").read_bytes(), self.node.read_bytes())
        with ZipFile(resources / "ootrr_remake.apworld") as archive:
            self.assertEqual(archive.read("ootrr_remake/settings.py"), b"synthetic settings.py")
        self.assertTrue(all(Path(first[name]).is_relative_to(self.workspace) for name in ("resources", "local_appdata", "appdata")))

    def test_world_cache_tracks_source_changes_and_rejects_a_damaged_archive(self):
        first = self.prepare()
        world = Path(first["resources"]) / "ootrr_remake.apworld"
        put(self.root / "client/ootrr_triforce/settings.py", b"changed setting implementation")
        self.assertTrue(self.prepare()["world_rebuilt"])
        with ZipFile(world) as archive:
            self.assertEqual(archive.read("ootrr_remake/settings.py"), b"changed setting implementation")
        world.write_bytes(b"damaged private cache")
        self.assertTrue(self.prepare()["world_rebuilt"])
        with ZipFile(world) as archive:
            self.assertIn("ootrr_remake/__init__.py", archive.namelist())
        put(self.root / "client/ootrr_triforce/app_window.py", b"changed live source UI")
        self.assertFalse(self.prepare()["world_rebuilt"], "GUI source edits must not require repackaging the world")

    def test_workspace_cannot_be_the_build_root_or_an_external_application_folder(self):
        for path in (self.root / "build", self.home / "original application", self.root / "build/../../outside"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                dev.prepare_resources(path, root=self.root, runtime_provider=self.runtime)
        self.runtime.assert_not_called()
        self.assertEqual(self.original.read_bytes(), b"original save must stay unchanged")

    def test_redirected_resource_destination_cannot_overwrite_an_external_file(self):
        self.workspace.mkdir(parents=True)
        external = self.home / "outside resources"
        external.mkdir()
        sentinel = external / "ootrr_remake.apworld"
        sentinel.write_bytes(b"external world")
        try:
            (self.workspace / "resources").symlink_to(external, target_is_directory=True)
        except OSError:
            self.skipTest("Directory symlinks are not available on this host")
        with self.assertRaises(ValueError):
            self.prepare()
        self.runtime.assert_not_called()
        self.assertEqual(sentinel.read_bytes(), b"external world")

    def test_mismatched_native_digest_stops_before_download_or_staging(self):
        put(self.root / "native/ootrr_ap_digest.h", b"mismatched header")
        with self.assertRaisesRegex(ValueError, "DLL and digest"):
            self.prepare()
        self.runtime.assert_not_called()
        self.assertFalse(self.workspace.exists())

    def test_default_runtime_cache_file_links_cannot_redirect_downloads_outside_the_cache(self):
        cache = self.root / "build/app-dependencies"
        cache.mkdir(parents=True)
        for filename in ("node.exe", "NODE-LICENSE.txt"):
            for existing in (False, True):
                outside = self.home / ("external " + str(existing) + " " + filename)
                if existing:
                    outside.write_bytes(b"external content must stay unchanged")
                link = cache / filename
                try:
                    link.symlink_to(outside)
                except OSError:
                    self.skipTest("File symlinks are not available on this host")
                with self.subTest(filename=filename, existing=existing):
                    try:
                        with self.assertRaises(ValueError):
                            self.prepare()
                        self.runtime.assert_not_called()
                        if existing:
                            self.assertEqual(outside.read_bytes(), b"external content must stay unchanged")
                        else:
                            self.assertFalse(outside.exists(), "A dangling cache link must not create its external target")
                    finally:
                        link.unlink()

    def test_supplied_node_is_read_only_and_requires_its_existing_license(self):
        for arguments in (dict(node=self.node), dict(node_license=self.license),
                          dict(node=self.node, node_license=self.home / "absent license")):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                self.prepare(**arguments)
        self.runtime.assert_not_called()
        self.prepare(node=self.node, node_license=self.license)
        self.runtime.assert_called_once_with(self.node, self.license)
        self.assertEqual(self.node.read_bytes(), b"synthetic Node runtime")
        self.assertEqual(self.license.read_bytes(), b"synthetic Node license")

    def test_subprocess_isolation_preserves_normal_temporary_paths_and_the_parent_environment(self):
        prepared = self.prepare()
        original = dict(LOCALAPPDATA=str(self.original.parents[5]), APPDATA="original roaming", TEMP="C:/short temp",
                        TMP="C:/other temp", OOTRR_NODE="original node", PATH="untouched PATH")
        environment = dev.child_environment(prepared, original)
        self.assertEqual(environment["TEMP"], original["TEMP"])
        self.assertEqual(environment["TMP"], original["TMP"])
        self.assertEqual(environment["PATH"], original["PATH"])
        self.assertNotEqual(environment["LOCALAPPDATA"], original["LOCALAPPDATA"])
        self.assertEqual(original["OOTRR_NODE"], "original node")
        for name in ("LOCALAPPDATA", "APPDATA", "PYTHONPYCACHEPREFIX", "OOTRR_NODE"):
            self.assertTrue(Path(environment[name]).is_relative_to(self.workspace))

    def test_actual_child_bootstrap_uses_live_source_and_private_resources_with_spaces(self):
        prepared = self.prepare()
        package = self.root / "client/ootrr_triforce"
        put(package / "__init__.py", b"")
        put(package / "app_runtime.py", b"_resource_override = None\n")
        put(self.root / "client/app.py", b"from ootrr_triforce import app_runtime\nimport json, os, sys\nfrom pathlib import Path\nPath(sys.argv[1]).write_text(json.dumps(dict(resources=str(app_runtime._resource_override), local=os.environ['LOCALAPPDATA'], arguments=sys.argv[2:])))\n")
        report = self.workspace / "child result.json"
        command = dev.launch_command(prepared, root=self.root, arguments=(report, "one value & $with spaces"))
        result = subprocess.run(command, env=dev.child_environment(prepared), capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        value = json.loads(report.read_bytes())
        self.assertEqual(value["resources"], prepared["resources"])
        self.assertEqual(value["local"], prepared["local_appdata"])
        self.assertEqual(value["arguments"], ["one value & $with spaces"])

    def test_prepare_only_cli_never_launches_the_application(self):
        prepared = self.prepare()
        with patch.object(dev, "check_environment") as check, patch.object(dev, "prepare_resources", return_value=prepared), \
             patch.object(dev.subprocess, "run") as launch, redirect_stdout(StringIO()) as output:
            self.assertEqual(dev.main(["--prepare-only"]), 0)
        check.assert_called_once_with(dependencies=False)
        launch.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["workspace"], str(self.workspace))

    def test_native_arm64_python_is_rejected_before_preparation_but_x64_python_is_accepted(self):
        with patch.object(dev.sys, "platform", "win32"), patch.object(dev.sys, "maxsize", 2**63 - 1), \
             patch.object(dev.sys, "version_info", (3, 13, 0)):
            with patch.object(dev.sysconfig, "get_platform", return_value="win-arm64"), \
                 patch.object(dev, "prepare_resources") as prepare, redirect_stderr(StringIO()) as error:
                with self.assertRaises(SystemExit) as failed:
                    dev.main(["--prepare-only"])
            self.assertEqual(failed.exception.code, 1)
            self.assertIn("Windows x64 Python", error.getvalue())
            prepare.assert_not_called()
            # Python's ABI is decisive, including x64 Python emulated on ARM.
            with patch.object(dev.sysconfig, "get_platform", return_value="win-amd64"):
                dev.check_environment(dependencies=False)


if __name__ == "__main__":
    unittest.main()
