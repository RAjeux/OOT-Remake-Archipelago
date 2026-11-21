"""Check release verification against tampering and unsafe reference updates."""
from contextlib import redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import verify_release as verify


class ReleaseVerificationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        (self.root / "VERSION").write_text("1.2.3", encoding="utf-8")
        (self.root / "dist").mkdir()
        (self.root / "tests").mkdir()
        self.archive = self.root / "dist/Archipelago-OOT-Remake-1.2.3.zip"
        self.write_release()
        self.addCleanup(patch.stopall)
        patch.object(verify, "ROOT", self.root).start()
        self.run_verify("--record-reference")

    def write_release(self, nested=b"original", guide=b"guide"):
        with ZipFile(self.archive, "w") as outer:
            outer.writestr("Guide.txt", guide)
            for name in verify.CONTAINERS:
                stream = BytesIO()
                with ZipFile(stream, "w") as child:
                    child.writestr("member.py", nested)
                outer.writestr(name, stream.getvalue())

    def run_verify(self, *args):
        with patch.object(sys, "argv", ["verify_release.py", *args]), redirect_stdout(StringIO()):
            verify.main()

    def test_original_and_nested_tampering(self):
        self.run_verify()
        self.write_release(nested=b"tampered")
        with self.assertRaisesRegex(SystemExit, "member.py.*content"):
            self.run_verify()

    def test_external_tampering(self):
        self.write_release(guide=b"tampered")
        with self.assertRaisesRegex(SystemExit, "Guide.txt.*content"):
            self.run_verify()

    def test_reference_cannot_be_overwritten(self):
        original = (self.root / "tests/reference-1.2.3.json").read_bytes()
        self.write_release(nested=b"tampered")
        with self.assertRaises(FileExistsError):
            self.run_verify("--record-reference")
        self.assertEqual(original, (self.root / "tests/reference-1.2.3.json").read_bytes())

    def test_duplicate_zip_entries_are_refused(self):
        with warnings.catch_warnings(), ZipFile(self.archive, "a") as archive:
            warnings.simplefilter("ignore", UserWarning)
            archive.writestr("Guide.txt", b"duplicate")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.run_verify()


if __name__ == "__main__":
    unittest.main()
