"""Check standalone metadata and archive safety without running a freezer."""
import ast
from io import BytesIO
import json
import marshal
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import verify_app
import build_app


class WindowsVersionInfoTests(unittest.TestCase):
    def read_resource(self, resource):
        tree = ast.parse(Path(resource).read_text(encoding="utf-8"))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
        fixed = next(node for node in calls if node.func.id == "FixedFileInfo")
        fields = {keyword.arg: ast.literal_eval(keyword.value) for keyword in fixed.keywords}
        strings = {ast.literal_eval(node.args[0]): ast.literal_eval(node.args[1])
                   for node in calls if node.func.id == "StringStruct"}
        table = next(node for node in calls if node.func.id == "StringTable")
        translation = next(node for node in calls if node.func.id == "VarStruct")
        self.assertEqual(ast.literal_eval(table.args[0]), "040904B0")
        self.assertEqual([ast.literal_eval(value) for value in translation.args], ["Translation", [0x0409, 1200]])
        self.assertEqual(set(strings), {"FileDescription", "FileVersion", "InternalName", "OriginalFilename",
                                        "ProductName", "ProductVersion"})
        return fields, strings

    def test_release_and_prerelease_resources_keep_exact_semver_and_versioned_filename(self):
        cases = (("1.2.3", (1, 2, 3, 0), 0),
                 ("0.10.1-alpha.3", (0, 10, 1, 3), 2),
                 ("1.2.3-rc.12+build.004", (1, 2, 3, 12), 2),
                 ("1.2.3-alpha", (1, 2, 3, 0), 2))
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            for version, expected, flags in cases:
                with self.subTest(version=version):
                    name = "OOT-Remake-Archipelago-" + version
                    resource = build_app.write_version_info(work, version, name)
                    self.assertEqual(resource.parent.resolve(), work.resolve())
                    fixed, strings = self.read_resource(resource)
                    self.assertEqual(fixed["filevers"], expected)
                    self.assertEqual(fixed["prodvers"], expected)
                    self.assertEqual(fixed["flags"], flags)
                    self.assertEqual(fixed["mask"], 0x3f)
                    self.assertEqual(fixed["fileType"], 1)
                    self.assertEqual(strings, {
                        "FileDescription": "OOT Remake Archipelago", "FileVersion": version,
                        "InternalName": name, "OriginalFilename": name + ".exe",
                        "ProductName": "OOT Remake Archipelago", "ProductVersion": version})
                    self.assertNotIn(b"\r\n", resource.read_bytes())

    def test_invalid_semver_and_windows_field_overflow_are_rejected(self):
        for version in ("1.2", "01.2.3", "1.2.03", "1.2.3-", "1.2.3-alpha.01", "1.2.3+",
                        "1.2.3.4", "1.2.3\nInjected", "65536.2.3", "1.65536.3", "1.2.65536",
                        "1.2.3-alpha.65536"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                build_app.windows_version(version)
        self.assertEqual(build_app.windows_version("65535.65535.65535-rc.65535"), ((65535,) * 4, 2))

    def test_main_passes_workspaces_generated_version_resource_to_pyinstaller(self):
        for use_path_alias in (False, True):
            with self.subTest(equivalent_path_alias=use_path_alias):
                self.check_main_version_resource(use_path_alias)

    def check_main_version_resource(self, use_path_alias):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            if use_path_alias:
                # Exercise canonicalization everywhere, even on machines whose
                # TEMP path has no Windows short-name alias such as RUNNER~1.
                (root / "alias").mkdir()
                root = root / "alias" / ".."
                self.assertNotEqual(root, root.resolve())
            version = "0.10.1-alpha.3"
            name = "OOT-Remake-Archipelago-" + version
            (root / "VERSION").write_text(version + "\n", encoding="utf-8")
            module = root / "client/ootrr_triforce"
            module.mkdir(parents=True)
            for path in ("app_window.py", "app_runtime.py", "install_service.py"):
                (module / path).touch()
            node, node_license = root / "node.exe", root / "NODE-LICENSE.txt"
            node.write_bytes(b"test runtime")
            node_license.write_text("test license", encoding="utf-8")
            work, output = root / "build/custom-work", root / "dist"
            calls = []

            def freeze(command, **kwargs):
                calls.append(command)
                self.assertEqual(command[command.index("--name") + 1], name)
                resource = Path(command[command.index("--version-file") + 1])
                self.assertEqual(resource.resolve(), (work / "windows-version-info.txt").resolve())
                self.assertEqual(self.read_resource(resource)[1]["ProductVersion"], version)
                self.assertEqual(Path(kwargs["cwd"]).resolve(), root.resolve())
                output.mkdir()
                (output / (name + ".exe")).write_bytes(b"fake freezer output")

            fake_image = MagicMock()
            fake_pil = SimpleNamespace(Image=SimpleNamespace(open=MagicMock(return_value=fake_image)))
            with patch.object(build_app, "ROOT", root), \
                    patch.object(build_app.sys, "argv", ["build_app.py", "--work", str(work), "--output", str(output)]), \
                    patch.object(build_app.sys, "platform", "win32"), \
                    patch.object(build_app.sysconfig, "get_platform", return_value="win-amd64"), \
                    patch.object(build_app.importlib.metadata, "version", return_value=build_app.PYINSTALLER_VERSION), \
                    patch.object(build_app, "pinned_node", return_value=(node, node_license)), \
                    patch.object(build_app, "payload", return_value=({}, {"payload": {}})), \
                    patch.object(build_app.subprocess, "run", side_effect=freeze), \
                    patch.dict(sys.modules, {"PIL": fake_pil}), patch("builtins.print"):
                build_app.main()
            self.assertEqual(len(calls), 1)
            report = json.loads((work / "build-result.json").read_text(encoding="utf-8"))
            self.assertEqual(report["artifact"], name + ".exe")


class FrozenArchiveSafetyTests(unittest.TestCase):
    def test_game_sessions_and_unrelated_executables_are_rejected(self):
        for name in ("../secret", "C:/Users/private/secret", "romfs/Pack/ZsDic.pack.zs",
                     "user/progress.sav", "ootrr.exe", "native/Triforce.exe",
                     "native-session.json", "saves/room.apsave", "player.apootrr"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                verify_app.safe_name(name)
        for name in ("native/archipelago.dll", "runtime/node/node.exe", "ootrr_remake.apworld",
                     "licenses/Python-LICENSE.txt", "ootrr_triforce/engine.wasm"):
            self.assertEqual(verify_app.safe_name(name), name)

    def test_compressed_bytecode_cannot_hide_private_source_paths(self):
        raw = BytesIO()
        code = compile("value = 42", "C:/private-workspace/client/module.py", "exec")
        with ZipFile(raw, "w") as archive:
            archive.writestr("module.pyc", bytes(16) + marshal.dumps(code))
        with self.assertRaisesRegex(ValueError, "Absolute Python"):
            verify_app.inspect_zip(raw.getvalue(), set(), "library")

    def test_private_markers_are_found_in_utf8_and_utf16(self):
        markers = verify_app.markers(["test-private-marker"])
        for data in (b"TEST-PRIVATE-MARKER", "test-private-marker".encode("utf-16-le")):
            with self.assertRaisesRegex(ValueError, "Private build path"):
                verify_app.private_data(data, markers, "payload")

    def test_relative_source_paths_are_accepted(self):
        code = compile("def value():\n    return 42\n", "ootrr_triforce/module.py", "exec")
        verify_app.code_paths(code, "module")


class TkLicenseTests(unittest.TestCase):
    def test_yaml_parser_license_is_included_from_the_installed_distribution(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(build_app, "_tk_license_text", return_value="Vendor Tk terms"):
                files = build_app.licenses(Path(temporary), Path(temporary)/"node-license")
            license_file = files["licenses/PyYAML-LICENSE"]
            self.assertIn("Permission is hereby granted", license_file.read_text(encoding="utf-8"))

    def interpreter(self, folder):
        class Tcl8:
            def call(self, command, argument):
                return "8.6.14" if argument == "patchlevel" else str(folder)
            def eval(self, command):
                return str(folder)
        return Tcl8()

    def test_existing_vendor_license_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "license.terms").write_text("Dedicated vendor terms.\n", encoding="utf-8")
            for language in ("Tcl", "Tk"):
                self.assertEqual(build_app._tk_license_text(self.interpreter(folder), language), "Dedicated vendor terms.\n")

    def test_consolidated_notices_are_copied_in_full_when_separate_files_are_absent(self):
        notice = ("This software is copyrighted by the Regents of the University of California, Sun Microsystems, Inc., Scriptics Corporation\n"
                  "The authors hereby grant permission to use, copy, modify, distribute,\n"
                  "IN NO EVENT SHALL THE AUTHORS OR DISTRIBUTORS BE LIABLE\n"
                  "permission to use and distribute the software in accordance with the terms specified in this license.\n")
        combined = "Python distribution notices.\n" + notice + notice + "Other notices are retained too.\n"
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "LICENSE.txt").write_text(combined, encoding="utf-8")
            with patch.object(build_app.sys, "base_prefix", str(folder)):
                for language in ("Tcl", "Tk"):
                    self.assertEqual(build_app._tk_license_text(self.interpreter(folder), language), combined)

    def test_psf_only_license_cannot_replace_missing_tcl_and_tk_notices(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "LICENSE.txt").write_text("Python Software Foundation license only.\n", encoding="utf-8")
            with patch.object(build_app.sys, "base_prefix", str(folder)):
                for language in ("Tcl", "Tk"):
                    with self.assertRaisesRegex(ValueError, "Tcl and Tk license terms"):
                        build_app._tk_license_text(self.interpreter(folder), language)


class CorrespondingSourceTests(unittest.TestCase):
    def test_a_candidate_can_link_to_its_exact_commit_before_a_release_tag_exists(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            revision = "1234567890abcdef" * 2 + "12345678"
            text = build_app.source_notice(folder, "0.10.4-alpha.1", revision).read_text(encoding="utf-8")
            self.assertIn("/tree/" + revision, text)
            self.assertIn("/archive/" + revision + ".zip", text)
            self.assertNotIn("/refs/tags/", text)
            default = build_app.source_notice(folder, "1.2.3").read_text(encoding="utf-8")
            self.assertIn("/archive/refs/tags/v1.2.3.zip", default)
            with self.assertRaises(ValueError):
                build_app.source_notice(folder, "1.2.3", "HEAD")


if __name__ == "__main__":
    unittest.main()
