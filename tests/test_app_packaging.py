"""Check standalone archive rejection without requiring a Windows freezer."""
from io import BytesIO
import importlib.util
import json
import marshal
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import verify_app
import build_app
import build
sys.path.insert(0, str(ROOT / 'client'))
from ootrr_triforce import app_runtime


class APWorldContainerTests(unittest.TestCase):
    """AP0.6.8 installs one package directory, unlike generic Python zipimport.

    Primary contract: ArchipelagoMW/Archipelago,0.6.8,
    worlds/LauncherComponents.py::_install_apworld.
    """
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.root = Path(cls.folder.name)
        cls.cli = cls.root / 'cli/ootrr_remake.apworld'
        build.archive(cls.cli, build.world_entries())
        cls.bundle = cls.root / 'application'
        node = cls.bundle / 'runtime/node/node.exe'
        node.parent.mkdir(parents=True)
        node.write_bytes(b'isolated-test-node')
        license = node.with_name('LICENSE')
        license.write_text('test runtime license', encoding='utf8')
        with patch.object(build_app, 'licenses', return_value={}):
            files, _ = build_app.payload(cls.bundle, '0.12-test', node, license)
        cls.bundled_world = files['ootrr_remake.apworld']

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_cli_and_executable_payload_have_identical_installable_worlds(self):
        self.assertEqual(self.cli.read_bytes(), self.bundled_world.read_bytes())
        for path in (self.cli, self.bundled_world):
            metadata = verify_app.inspect_apworld(path.read_bytes(), set(), path.name)
            self.assertEqual(metadata['game'], 'Ocarina of Time Remake')
            with ZipFile(path) as archive:
                self.assertEqual({name.split('/')[0] for name in archive.namelist()}, {'ootrr_remake'})
                self.assertIn('ootrr_remake/archipelago.json', archive.namelist())
                self.assertNotIn('ootrr_full/__init__.py', archive.namelist())

    def test_old_two_package_layout_is_rejected_by_both_preflights(self):
        raw = BytesIO()
        with ZipFile(raw, 'w') as archive:
            archive.writestr('ootrr_remake/__init__.py', '# world')
            archive.writestr('ootrr_full/__init__.py', '# separate top-level engine')
        with self.assertRaisesRegex(ValueError, 'single directory'):
            app_runtime.validate_apworld_archive(BytesIO(raw.getvalue()))
        with self.assertRaisesRegex(ValueError, 'single directory'):
            verify_app.inspect_apworld(raw.getvalue(), set(), 'ootrr_remake.apworld')

    def test_install_from_the_application_keeps_the_real_container_format(self):
        archipelago, base = self.root / 'private-ap', self.root / 'private-user'
        archipelago.mkdir()
        (archipelago / 'ArchipelagoGenerate.exe').touch()
        with patch.object(app_runtime, 'resource_root', return_value=self.bundle), \
             patch.object(app_runtime, 'NODE_SHA256', app_runtime._sha(self.bundle / 'runtime/node/node.exe')):
            installed = app_runtime.install_apworld(archipelago, base=base)
        self.assertEqual(installed.read_bytes(), self.cli.read_bytes())
        verify_app.inspect_apworld(installed.read_bytes(), set(), installed.name)

    def test_zip_and_extracted_world_import_their_own_engine_without_the_repo(self):
        extracted = self.root / 'extracted'
        with ZipFile(self.cli) as archive:
            archive.extractall(extracted)
        script = r'''
import importlib,importlib.util,json,pathlib,sys,zipimport
source=pathlib.Path(sys.argv[1]).resolve()
if source.is_file():
    spec=zipimport.zipimporter(str(source)).find_spec('ootrr_remake')
else:
    spec=importlib.util.spec_from_file_location('ootrr_remake',source/'ootrr_remake/__init__.py',submodule_search_locations=[str(source/'ootrr_remake')])
package=importlib.util.module_from_spec(spec)
sys.modules['ootrr_remake']=package
full=importlib.import_module('ootrr_remake.full_ap')
world=full.new_world(full.full_defaults(),'isolated-apworld-container')
import ootrr_full
engine=ootrr_full.__file__.replace('\\','/')
assert '/ootrr_remake/_vendor/ootrr_full/' in engine,engine
assert len(world.names)==1106,len(world.names)
print(json.dumps({'checks':len(world.names),'engine':engine}))
'''
        for source in (self.cli, extracted):
            result = subprocess.run([sys.executable, '-I', '-c', script, str(source)], cwd=self.root,
                                    capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['checks'], 1106)


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


if __name__ == "__main__":
    unittest.main()
