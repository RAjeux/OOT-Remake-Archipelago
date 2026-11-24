"""External setup isolates profiles, installs atomically and never edits saves."""
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce import external_setup as setup


TOKEN = "e" * 64
DATA = {"token": TOKEN, "slot": "External Link", "room": "external-test-room", "player": 2,
        "generation_mode": "full_network", "checks": ["One check"]}


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "game resources"
        for name in setup.RESOURCE_FILES:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"original game resource fixture")
        self.player = self.root / "Player.apootrr"
        self.player.write_text(json.dumps(DATA), encoding="utf-8")
        self.exe = self.root / "emulator.exe"
        self.exe.write_bytes(b"not executed")
        self.save = self.root / "account/slot_00/progress.sav"
        self.save.parent.mkdir(parents=True)
        self.save.write_bytes(b"original save fixture")
        self.mods = self.root / "emulator user/load/title"
        self.mods.mkdir(parents=True)
        (self.mods / "unrelated-mod").mkdir()
        (self.mods / "unrelated-mod/keep").write_bytes(b"unrelated mod preserved")
        self.base = self.root / "application data"
        native_save = self.base / TOKEN / "user/progress.sav"
        native_save.parent.mkdir(parents=True)
        native_save.write_bytes(b"native room save preserved")
        self.request = setup.ExternalSetupRequest(self.player, self.source, self.mods, self.exe,
                            self.save, "ws://127.0.0.1:12345", base=self.base)
        self.builds = 0
        def build(root, settings, data):
            self.builds += 1
            target = Path(root) / "mods/Archipelago"
            (target / "romfs").mkdir(parents=True)
            (target / "romfs/resource").write_bytes(b"prepared mod")
            (target / "manifest.json").write_text(json.dumps({"archipelago": {"token": TOKEN},
                "external_readiness": {"flag": "Archipelago.Ready." + TOKEN}}), encoding="utf-8")
        def artifact(directory, token):
            setup._no_native(directory)
            value = json.loads((Path(directory) / "manifest.json").read_text())
            if value["archipelago"]["token"] != token:
                raise ValueError("fixture token mismatch")
            return value
        for patcher in (patch.object(setup, "validate_manifest", lambda d: d),
                        patch.object(setup, "_running", lambda _: False),
                        patch.object(setup, "_artifact", artifact),
                        patch("ootrr_triforce.full_mod.build", build),
                        patch("ootrr_triforce.full_mod.code_fingerprint", lambda: "fixed-test-code")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def assert_preserved(self):
        self.assertEqual(self.save.read_bytes(), b"original save fixture")
        self.assertEqual((self.base / TOKEN / "user/progress.sav").read_bytes(), b"native room save preserved")
        self.assertEqual((self.mods / "unrelated-mod/keep").read_bytes(), b"unrelated mod preserved")
        for name in setup.RESOURCE_FILES:
            self.assertEqual((self.source / name).read_bytes(), b"original game resource fixture")

    def test_prepare_installs_external_only_and_preserves_original_data(self):
        result = setup.configure(self.request)
        self.assertTrue(result["ready"])
        self.assertEqual(result["host"], "external")
        self.assertIn("hosts/external/profiles", Path(result["profile"]).as_posix())
        self.assertFalse((self.mods / "Archipelago/romfs/Archipelago/room-v1.txt").exists())
        self.assertNotIn("protected_password", result)
        self.assertEqual(setup.list_profiles(self.base)[0]["token"], TOKEN)
        self.assert_preserved()

    def test_reprepare_reuses_cache_and_keeps_previous_mod_outside_active_mods(self):
        first = setup.configure(self.request)
        (self.mods / "Archipelago/previous-resource").write_bytes(b"old managed mod")
        second = setup.configure(self.request)
        self.assertEqual(self.builds, 1)
        backup = Path(second["backup"])
        self.assertNotIn(self.mods, backup.parents)
        self.assertEqual((backup / "previous-resource").read_bytes(), b"old managed mod")
        self.assertEqual(first["token"], second["token"])
        self.assert_preserved()

    def test_failure_after_backup_restores_the_original_mod_and_profile(self):
        first = setup.configure(self.request)
        old_session = (Path(first["profile"]) / setup.SESSION).read_bytes()
        (self.mods / "Archipelago/previous-resource").write_bytes(b"old managed mod")
        rename = Path.rename
        def fail_install(path, destination):
            if path.parent.name == ".ootrr-ap-staging" and Path(destination).name == "Archipelago":
                raise PermissionError("fixture target locked")
            return rename(path, destination)
        with patch.object(Path, "rename", fail_install):
            with self.assertRaises(PermissionError):
                setup.configure(self.request)
        self.assertEqual((self.mods / "Archipelago/previous-resource").read_bytes(), b"old managed mod")
        self.assertEqual((Path(first["profile"]) / setup.SESSION).read_bytes(), old_session)
        self.assertFalse((setup.namespace(self.base) / "install-transaction.json").exists())
        self.assert_preserved()

    def test_unmanaged_or_native_mod_cannot_be_overwritten(self):
        target = self.mods / "Archipelago"
        target.mkdir()
        (target / "important").write_bytes(b"keep")
        with self.assertRaisesRegex(ValueError, "unmanaged"):
            setup.configure(self.request)
        (target / "archipelago.dll").write_bytes(b"native integration")
        with self.assertRaisesRegex(ValueError, "native connection"):
            setup.configure(self.request)
        self.assertEqual((target / "important").read_bytes(), b"keep")
        self.assert_preserved()

    def test_running_selected_game_stops_before_build(self):
        with patch.object(setup, "_running", return_value=True):
            with self.assertRaisesRegex(ValueError, "Close the selected game"):
                setup.configure(self.request)
        self.assertEqual(self.builds, 0)
        self.assert_preserved()

    def test_launch_passes_game_as_separate_argument_and_no_input_override(self):
        result = setup.configure(self.request)
        with patch.object(setup.subprocess, "Popen") as popen, patch.dict(os.environ, {"HOS_INPUT_EXCLUSIVE": "1"}):
            setup.launch(result["profile"])
        arguments = popen.call_args
        self.assertEqual(arguments.args[0], [str(self.exe)])
        self.assertFalse(any(key.startswith("HOS_INPUT_") for key in arguments.kwargs["env"]))
        self.assertNotIn("--user", arguments.args[0])
        self.assert_preserved()

    def test_preferences_change_while_game_runs_without_reinstall_or_save_write(self):
        result = setup.configure(self.request)
        build_count = self.builds
        with patch.object(setup, "_running", return_value=True):
            updated = setup.update_preferences(result["profile"], save_path="", server="archipelago.gg:12345",
                                                auto_connect=False)
        self.assertEqual(updated["save_path"], "")
        self.assertEqual(updated["server"], "archipelago.gg:12345")
        self.assertFalse(updated["auto_connect"])
        self.assertEqual(self.builds, build_count)
        self.assert_preserved()

    def test_external_connection_cannot_duplicate_an_active_native_slot(self):
        result = setup.configure(self.request)
        native = self.base / TOKEN
        (native / "native-session.json").write_text("{}")
        with patch("ootrr_triforce.connection_control.Controller") as controller:
            controller.return_value.info.return_value = {"running": True}
            with self.assertRaisesRegex(ValueError, "native client"):
                setup.connect(result["profile"])

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_unicode_password_is_protected_retained_and_not_returned(self):
        password = "private-external-password-é"
        result = setup.configure(replace(self.request, password=password))
        path = Path(result["profile"]) / setup.SESSION
        self.assertNotIn(password, path.read_text())
        self.assertNotIn("protected_password", result)
        protected = json.loads(path.read_text())["protected_password"]
        self.assertEqual(setup._unprotect_password(protected), password)
        result = setup.configure(self.request)
        self.assertTrue(result["has_password"])
        self.assertEqual(json.loads(path.read_text())["protected_password"], protected)
        result = setup.configure(replace(self.request, clear_password=True))
        self.assertFalse(result["has_password"])
        self.assert_preserved()


@unittest.skipUnless(os.environ.get("OOT_NUP"), "OOT_NUP not set")
class NativeResourceCacheTests(unittest.TestCase):
    def test_only_required_readonly_resources_are_extracted(self):
        from ootrr_full.formats.inspect_nup import Nup
        from ootrr_full.game.world_maps import effective_members
        source = Path(os.environ["OOT_NUP"])
        before = (source.stat().st_size, source.stat().st_mtime_ns)
        with tempfile.TemporaryDirectory() as temporary:
            root = setup.resource_cache(source, temporary)
            files = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
            self.assertEqual(files, set(setup.RESOURCE_FILES))
            nup = Nup(source)
            try:
                members = effective_members(nup)
                for name in setup.RESOURCE_FILES:
                    self.assertEqual((root / name).read_bytes(), nup.read(members[name]))
            finally:
                nup.stream.close()
            self.assertEqual(setup.resource_cache(source, temporary), root)
        self.assertEqual((source.stat().st_size, source.stat().st_mtime_ns), before)


if __name__ == "__main__":
    unittest.main()
