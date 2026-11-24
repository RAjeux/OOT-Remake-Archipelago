"""Check standalone archive rejection without requiring a Windows freezer."""
from io import BytesIO
import marshal
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import verify_app
import build_app


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
