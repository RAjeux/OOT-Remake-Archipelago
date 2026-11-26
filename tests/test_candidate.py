"""Contributions may change code while immutable release references stay fixed."""
import hashlib
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import verify_candidate as check


class CandidateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        files = {"VERSION": b"1.2.3", "LICENSE": b"license", "NOTICE": b"notices",
                 "apworld/ootrr_remake/__init__.py": b"# synthetic world",
                 "client/__main__.py": b"# source client", "client/ootrr_triforce/settings.py": b"before",
                 "moteur/engine.rs": b"// source", "distribution/Guide.txt": b"guide",
                 "native/bridge.inc": b"/* bridge */", "prebuilt/windows-x64/archipelago.dll": b"synthetic dll",
                 "tests/reference-1.2.3.json": b"published immutable reference"}
        raw = files["prebuilt/windows-x64/archipelago.dll"]
        files["native/ootrr_ap_digest.h"] = ("static const unsigned char ap_dll_sha16[32] = {" +
            ",".join(map(str, hashlib.sha256(raw).digest())) + "};\n").encode()
        for name, raw in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        self.archive = self.root / "dist/Archipelago-OOT-Remake-1.2.3.zip"
        for name, value in (("WORLD_FILES", ("settings.py",)), ("HOST_FILES", ("bridge.inc", "ootrr_ap_digest.h"))):
            context = patch.object(check.build, name, value)
            context.start()
            self.addCleanup(context.stop)
        self.package()

    def package(self):
        # Build synthetic containers independently of the verifier's mappings.
        rows = {"Guide.txt": b"guide", "LICENSE": b"license", "NOTICE": b"notices", "VERSION": b"1.2.3",
                "native/archipelago.dll": (self.root / "prebuilt/windows-x64/archipelago.dll").read_bytes()}
        for path in (self.root / "native").iterdir():
            rows["native/" + path.name] = path.read_bytes()
            rows["sources/native/" + path.name] = path.read_bytes()
        for container, folder in zip(check.CONTAINERS, ("apworld", "client", "moteur")):
            raw = BytesIO()
            with ZipFile(raw, "w") as archive:
                for path in (self.root / folder).rglob("*"):
                    if path.is_file():
                        archive.writestr(path.relative_to(self.root / folder).as_posix(), path.read_bytes())
                if folder == "apworld":
                    archive.writestr("ootrr_remake/settings.py", (self.root / "client/ootrr_triforce/settings.py").read_bytes())
            rows[container] = raw.getvalue()
        self.archive.parent.mkdir(exist_ok=True)
        with ZipFile(self.archive, "w") as archive:
            for name, raw in rows.items():
                archive.writestr(name, raw)

    def test_changed_and_rebuilt_contribution_does_not_need_a_new_version_or_reference(self):
        reference = self.root / "tests/reference-1.2.3.json"
        before = reference.read_bytes()
        self.assertEqual(check.verify(self.root), "1.2.3")
        (self.root / "client/ootrr_triforce/settings.py").write_bytes(b"legitimate contribution")
        self.package()
        self.assertEqual(check.verify(self.root), "1.2.3")
        self.assertEqual(reference.read_bytes(), before)

    def test_stale_package_is_rejected_after_source_changes(self):
        (self.root / "client/ootrr_triforce/settings.py").write_bytes(b"new source")
        with self.assertRaisesRegex(ValueError, "stale or changed content"):
            check.verify(self.root)

    def test_unexpected_members_and_duplicate_entries_are_rejected(self):
        with ZipFile(self.archive, "a") as archive:
            archive.writestr("../outside", b"bad")
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            check.verify(self.root)
        self.package()
        with warnings.catch_warnings(), ZipFile(self.archive, "a") as archive:
            warnings.simplefilter("ignore", UserWarning)
            archive.writestr("VERSION", b"tampered")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            check.verify(self.root)

    def test_dll_digest_mismatch_cannot_be_blessed_as_a_candidate(self):
        (self.root / "prebuilt/windows-x64/archipelago.dll").write_bytes(b"replaced dll")
        with self.assertRaisesRegex(ValueError, "DLL"):
            check.verify(self.root)


if __name__ == "__main__":
    unittest.main()
