"""Check standalone archive rejection without requiring a Windows freezer."""
from io import BytesIO
import marshal
from pathlib import Path
import sys
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import verify_app


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


if __name__ == "__main__":
    unittest.main()
