"""Room selection changes only the active mod; each host keeps its own saves."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce import install_mod
from ootrr_triforce.room_library import LibraryError, RoomLibrary, room_progress


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.base = self.root / "app"
        self.library = RoomLibrary(self.base)
        self.game = self.root / "game"
        self.mods = self.game / "mods"
        self.mods.mkdir(parents=True)
        (self.game / "romfs").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def create_room(self, letter, host="nx2navi"):
        token = letter * 64
        namespace = self.library.host_base(host)
        profile = namespace / token
        profile.mkdir(parents=True)
        session = {"Token": token, "Room": "Room " + letter, "Slot": "Link", "Player": 1,
                   "Server": "ws://localhost:38281", "ProtectedPassword": "secret-must-not-escape",
                   "Checks": {"100": {"Name": "Kokiri chest", "Item": "Do not reveal this item"},
                              "101": {"Name": "Forest chest", "Item": "Do not reveal this either"}}}
        (profile / "native-session.json").write_text(json.dumps(session), encoding="utf-8")
        save = profile / "user/save/account/slot_00/progress.sav"
        save.parent.mkdir(parents=True)
        save.write_bytes(b"save-" + letter.encode())
        source = namespace / "prepared" / token
        marker = source / "Archipelago/romfs/Archipelago/room-v1.txt"
        marker.parent.mkdir(parents=True)
        marker.write_text(token)
        (marker.parent / "resources.bin").write_bytes(b"mod-" + letter.encode())
        result = dict(host=host, token=token, profile=str(profile), room=session["Room"], slot="Link",
                      game=str(self.game), romfs=str(self.game / "romfs"), tools=str(self.root / "tools"),
                      mods=str(self.mods), prepared_source=str(source))
        return result, save

    def test_register_rename_and_discovery_never_expose_credentials(self):
        result, save = self.create_room("a")
        self.library.register(result)
        key = "nx2navi:" + result["token"]
        self.library.rename(key, "My adventure")
        rows = self.library.rooms()
        self.assertEqual(rows[0]["name"], "My adventure")
        index = (self.base / "room-library.json").read_text(encoding="utf-8")
        self.assertNotIn("secret-must-not-escape", index)
        self.assertNotIn("ProtectedPassword", json.dumps(rows))
        self.assertEqual(save.read_bytes(), b"save-a")

    def test_switching_cached_rooms_preserves_both_saves_and_unknown_mods(self):
        first, save_a = self.create_room("a")
        second, save_b = self.create_room("b")
        self.library.register(first)
        self.library.register(second)
        unrelated = self.mods / "Unrelated/romfs/original.bin"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_bytes(b"untouched")
        before = {save_a: save_a.read_bytes(), save_b: save_b.read_bytes(), unrelated: unrelated.read_bytes()}
        with patch("ootrr_triforce.install_service._running_game", return_value=False), \
             patch("ootrr_triforce.install_service._compiled_game", return_value=True):
            for room in (first, second, first):
                active = self.library.select("nx2navi:" + room["token"])
                self.assertTrue(active["ready"])
                self.assertEqual((self.mods / "Archipelago/romfs/Archipelago/room-v1.txt").read_text(), room["token"])
                self.assertEqual(json.loads((self.base / "last-profile.json").read_text())["root"], room["profile"])
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_running_game_prevents_mod_and_marker_changes(self):
        room, save = self.create_room("a")
        self.library.register(room)
        before = save.read_bytes()
        with patch("ootrr_triforce.install_service._running_game", return_value=True):
            with self.assertRaises(LibraryError):
                self.library.select("nx2navi:" + room["token"])
        self.assertFalse((self.mods / "Archipelago").exists())
        self.assertFalse((self.base / "last-profile.json").exists())
        self.assertEqual(save.read_bytes(), before)

    def test_host_namespaces_and_tokens_cannot_be_substituted(self):
        room, _save = self.create_room("a", "hookshot")
        self.library.register(room)
        row = self.library.rooms()[0]
        self.assertEqual(row["host"], "hookshot")
        forged = dict(room, host="nx2navi")
        with self.assertRaises(LibraryError):
            self.library.register(forged)
        with self.assertRaises(LibraryError):
            self.library._profile("../../other", room["token"])
        with self.assertRaises(LibraryError):
            self.library._profile("nx2navi", "../other")

    def test_backup_has_verified_save_and_check_history_without_passwords(self):
        room, save = self.create_room("a")
        self.library.register(room)
        profile = Path(room["profile"])
        (profile / "native-checks.json").write_text('{"Locations":[100],"Won":false}')
        backup = self.library.snapshot("nx2navi:" + room["token"])
        self.assertEqual((backup / save.relative_to(profile)).read_bytes(), save.read_bytes())
        self.assertEqual((backup / "native-checks.json").read_bytes(), (profile / "native-checks.json").read_bytes())
        self.assertFalse((backup / "native-session.json").exists())
        self.assertNotIn("secret-must-not-escape", (backup / "room.json").read_text())

    def test_progress_is_passive_and_does_not_reveal_uncollected_items(self):
        room, _save = self.create_room("a")
        profile = Path(room["profile"])
        (profile / "native-checks.json").write_text('{"Locations":[100,999],"Won":true}')
        progress = room_progress(profile)
        self.assertEqual((progress["checked"], progress["total"]), (1, 2))
        self.assertTrue(progress["won"])
        self.assertNotIn("Do not reveal", json.dumps(progress))

    def test_tampered_cached_room_is_not_activated(self):
        room, _save = self.create_room("a")
        self.library.register(room)
        (Path(room["prepared_source"]) / "Archipelago/romfs/Archipelago/room-v1.txt").write_text("b" * 64)
        selected = self.library.select("nx2navi:" + room["token"])
        self.assertFalse(selected["ready"])
        self.assertFalse((self.mods / "Archipelago").exists())

    def test_failed_activation_restores_previous_mod_and_profile_markers(self):
        from ootrr_triforce import room_library
        first, save_a = self.create_room("a")
        second, save_b = self.create_room("b")
        self.library.register(first)
        self.library.register(second)
        with patch("ootrr_triforce.install_service._running_game", return_value=False), \
             patch("ootrr_triforce.install_service._compiled_game", return_value=True):
            self.library.select("nx2navi:" + first["token"])
            before = {name: (self.base / name).read_bytes() for name in ("outils.json", "last-profile.json", "desktop-host.json")}
            write = room_library._write
            def fail_late(path, value):
                if path.name == "desktop-host.json":
                    raise OSError("simulated write failure")
                return write(path, value)
            with patch.object(room_library, "_write", side_effect=fail_late), self.assertRaises(OSError):
                self.library.select("nx2navi:" + second["token"])
        self.assertEqual((self.mods / "Archipelago/romfs/Archipelago/room-v1.txt").read_text(), first["token"])
        self.assertEqual({name: (self.base / name).read_bytes() for name in before}, before)
        self.assertEqual(save_a.read_bytes(), b"save-a")
        self.assertEqual(save_b.read_bytes(), b"save-b")

    def test_external_rooms_share_names_but_never_use_native_activation_or_copy_original_save(self):
        token = "c" * 64
        profile = self.library.host_base("external") / token
        profile.mkdir(parents=True)
        original = self.root / "emulator/nand/progress.sav"
        original.parent.mkdir(parents=True)
        original.write_bytes(b"external-save")
        data = {"version": 1, "backend": "external", "token": token, "room": "External room", "slot": "Link", "player": 1,
                "server": "localhost:38281", "save_path": str(original), "executable": str(self.root / "emulator.exe"),
                "protected_password": "keep-this-private"}
        (profile / "external-session.json").write_text(json.dumps(data), encoding="utf-8")
        result = dict(data, profile=str(profile), host="external")
        self.library.register(result)
        key = "external:" + token
        self.library.rename(key, "My emulator room")
        row = self.library.select(key)
        self.assertTrue(row["external"])
        self.assertEqual(row["name"], "My emulator room")
        self.assertFalse((self.base / "last-profile.json").exists())
        self.assertNotIn("keep-this-private", json.dumps(self.library.rooms()))
        with patch("ootrr_triforce.external_setup._closed"):
            backup = self.library.snapshot(key)
        self.assertEqual((backup / "progress.sav").read_bytes(), b"external-save")
        self.assertEqual(original.read_bytes(), b"external-save")


if __name__ == "__main__":
    unittest.main()
