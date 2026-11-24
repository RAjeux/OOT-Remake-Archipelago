"""Release updates authenticate before staging and preserve files on failure."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce import update_service as updates
from ootrr_full import ed25519


def release_entry(version="0.11.0", *, signed=True, prerelease=False):
    tag = "v" + version
    names = [f"OOT-Remake-Archipelago-{version}.exe", updates.CHECKSUMS]
    if signed:
        names.append(updates.SIGNATURE)
    return {"tag_name": tag, "draft": False, "prerelease": prerelease,
            "body": "Release notes", "assets": [
                {"name": name, "browser_download_url": updates._asset_url(tag, name)} for name in names]}


def signed_release():
    entry = release_entry()
    return updates.check_for_update("0.10.0-alpha.1", platform="win32",
                                    fetch=lambda *_: json.dumps([entry]).encode())


class DiscoveryTests(unittest.TestCase):
    def test_version_order_and_prerelease_selection(self):
        entries = [release_entry("0.11.0-beta.10", prerelease=True),
                   release_entry("0.11.0-beta.2", prerelease=True), release_entry("0.10.1")]
        fetch = lambda *_: json.dumps(entries).encode()
        self.assertEqual(updates.check_for_update("0.10.0", platform="win32", fetch=fetch).version, "0.10.1")
        self.assertEqual(updates.check_for_update("0.10.0", True, platform="win32", fetch=fetch).version,
                         "0.11.0-beta.10")
        self.assertGreater(updates.version_key("0.11.0"), updates.version_key("0.11.0-rc.12"))
        self.assertIsNone(updates.check_for_update("0.12.0", True, platform="win32", fetch=fetch))

    def test_missing_signature_is_manual_download_only(self):
        release = updates.check_for_update("0.10.0", platform="win32",
                fetch=lambda *_: json.dumps([release_entry(signed=False)]).encode())
        self.assertFalse(release.signed)
        self.assertTrue(release.page.startswith(updates.PAGES))
        with self.assertRaisesRegex(updates.UpdateError, "no signed checksums"):
            updates.prepare_update(release, Path("unused"), public_key=b"p" * 32)

    def test_missing_trust_anchor_cannot_enable_automatic_updates(self):
        self.assertEqual(len(updates.TRUSTED_PUBLIC_KEY), 32)
        with patch.object(updates, "TRUSTED_PUBLIC_KEY", None):
            with self.assertRaisesRegex(updates.UpdateError, "no trusted publisher key"):
                updates.prepare_update(signed_release(), Path("unused"))

    def test_api_asset_cannot_redirect_to_other_repository(self):
        entry = release_entry()
        entry["assets"][0]["browser_download_url"] = "https://github.com/attacker/repo/releases/download/v1/run.exe"
        with self.assertRaisesRegex(updates.UpdateError, "unexpected download address"):
            updates.check_for_update("0.10.0", platform="win32", fetch=lambda *_: json.dumps([entry]).encode())

    def test_metadata_shape_and_unsupported_platform(self):
        with self.assertRaises(updates.UpdateError):
            updates.check_for_update("0.10.0", fetch=lambda *_: b'{"message":"rate limit"}')
        self.assertIsNone(updates.check_for_update("0.10.0", platform="darwin", fetch=lambda *_: b"[]"))


class StagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.release = signed_release()
        self.payload = b"MZ verified application fixture"
        self.digest = hashlib.sha256(self.payload).hexdigest()
        self.manifest = f"{self.digest}  {self.release.asset_name}\n".encode()
        self.responses = {self.release.checksum_url: self.manifest,
                          self.release.signature_url: b"s" * 64,
                          self.release.asset_url: self.payload}

    def fetch(self, url, _limit):
        return self.responses[url]

    def prepare(self, **kwargs):
        return updates.prepare_update(self.release, self.root / "staged", public_key=b"p" * 32,
                fetch=self.fetch, verifier=kwargs.pop("verifier", lambda *_: True), **kwargs)

    def test_invalid_signature_downloads_no_executable_and_writes_nothing(self):
        requested = []
        def fetch(url, limit):
            requested.append(url)
            return self.fetch(url, limit)
        with self.assertRaisesRegex(updates.UpdateError, "signature could not be verified"):
            updates.prepare_update(self.release, self.root / "staged", public_key=b"p" * 32,
                                   fetch=fetch, verifier=lambda *_: False)
        self.assertNotIn(self.release.asset_url, requested)
        self.assertFalse((self.root / "staged").exists())

    def test_corrupted_executable_rejected(self):
        self.responses[self.release.asset_url] = self.payload + b"changed"
        with self.assertRaisesRegex(updates.UpdateError, "signed checksum"):
            self.prepare()
        self.assertFalse((self.root / "staged").exists())

    def test_signed_duplicate_or_path_manifest_rejected(self):
        for bad in (self.manifest + self.manifest,
                    self.manifest + b"a" * 64 + b"  ../save.dat\n"):
            with self.subTest(manifest=bad):
                self.responses[self.release.checksum_url] = bad
                with self.assertRaises(updates.UpdateError):
                    self.prepare()

    def test_stage_and_install_preserve_adjacent_data_and_old_executable(self):
        prepared = self.prepare()
        self.assertEqual(prepared.path.read_bytes(), self.payload)
        executable = self.root / "OOT Remake.exe"
        executable.write_bytes(b"old application")
        save = self.root / "profile" / "progress.sav"
        save.parent.mkdir()
        save.write_bytes(b"unchanged save")
        backup = updates.install_prepared(prepared, executable)
        self.assertEqual(executable.read_bytes(), self.payload)
        self.assertEqual(backup.read_bytes(), b"old application")
        self.assertEqual(save.read_bytes(), b"unchanged save")

    def test_failed_replacement_rolls_back_old_application(self):
        prepared = self.prepare()
        executable = self.root / "OOT Remake.exe"
        executable.write_bytes(b"old application")
        replace = updates.os.replace
        calls = []
        def fail_second(source, target):
            calls.append((source, target))
            if len(calls) == 2:
                raise PermissionError("locked destination fixture")
            return replace(source, target)
        with patch.object(updates.os, "replace", fail_second):
            with self.assertRaises(PermissionError):
                updates.install_prepared(prepared, executable)
        self.assertEqual(executable.read_bytes(), b"old application")
        self.assertFalse(executable.with_name(executable.name + ".updating").exists())

    def test_staged_modification_is_rejected_before_any_rename(self):
        prepared = self.prepare()
        prepared.path.write_bytes(b"changed")
        executable = self.root / "OOT Remake.exe"
        executable.write_bytes(b"old application")
        with self.assertRaisesRegex(updates.UpdateError, "changed after verification"):
            updates.install_prepared(prepared, executable)
        self.assertEqual(executable.read_bytes(), b"old application")


class SignatureTests(unittest.TestCase):
    def test_rfc8032_empty_message_vector_and_corruption(self):
        public = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
        signature = bytes.fromhex("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555f"
                                  "b8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
        self.assertTrue(ed25519.verify(public, b"", signature))
        self.assertFalse(ed25519.verify(public, b"changed", signature))
        self.assertFalse(ed25519.verify(public, b"", signature[:-1]))

    def test_small_order_identity_is_not_a_trusted_signing_key(self):
        identity = b"\x01" + b"\x00" * 31
        self.assertFalse(ed25519.verify(identity, b"arbitrary manifest", identity + b"\x00" * 32))


if __name__ == "__main__":
    unittest.main()
