"""Desktop setup keeps save history and rolls back incomplete native updates."""
import asyncio
from contextlib import ExitStack
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce import app_runtime, install_mod, install_service as service, player
from ootrr_triforce.catalog import GAME, ITEM_IDS, LOCATION_IDS, PROTOCOL


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def fixture(folder):
    with ZipFile(ROOT / "tests/fixtures/neutre/salle-test.zip") as archive:
        name = next(name for name in archive.namelist() if name.endswith(".apootrr"))
        path = folder / Path(name).name
        path.write_bytes(archive.read(name))
    return path, player.read_manifest(path)


class FakeSocket:
    def __init__(self, batches):
        self.batches = list(batches)
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def send(self, text):
        self.sent.extend(json.loads(text))

    async def recv(self):
        if self.batches:
            return json.dumps(self.batches.pop(0))
        await asyncio.sleep(20)


class ReadOnlyScoutTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        _, self.data = fixture(Path(self.temporary.name))
        self.data = copy.deepcopy(self.data)
        self.data["checks"] = self.data["checks"][:1]

    def run_socket(self, batches, data=None, cancel=None):
        socket = FakeSocket(batches)
        with patch("websockets.legacy.client.connect", return_value=socket):
            result = asyncio.run(service.fetch_roster(data or self.data, "ws://127.0.0.1:1", "not-logged", cancel, timeout=1))
        return socket, result

    def connected(self):
        return dict(cmd="Connected", slot=self.data["player"], checked_locations=[], team=0,
                    slot_data=dict(protocol=PROTOCOL, token=self.data["token"],
                                   checks=[LOCATION_IDS[name] for name in self.data["checks"]]),
                    slot_info={str(self.data["player"]): dict(name=self.data["slot"], game=GAME),
                               "9": dict(name="Ami", game="Fixture Game")})

    def test_scout_resolves_foreign_names_without_sending_checks_or_grants(self):
        location = LOCATION_IDS[self.data["checks"][0]]
        socket, result = self.run_socket([
            [dict(cmd="RoomInfo", seed_name=self.data["room"])],
            [self.connected()],
            [dict(cmd="LocationInfo", locations=[dict(item=123456, location=location, player=9)])],
            [dict(cmd="DataPackage", data=dict(games={"Fixture Game": dict(item_name_to_id={"Friend Sword": 123456},
                                                                                 location_name_to_id={})}))],
        ])
        self.assertEqual(result, {self.data["checks"][0]: ("Friend Sword", "Ami")})
        self.assertEqual({packet["cmd"] for packet in socket.sent}, {"Connect", "LocationScouts", "GetDataPackage"})
        scouts = next(packet for packet in socket.sent if packet["cmd"] == "LocationScouts")
        self.assertEqual(scouts["create_as_hint"], 0)

    def test_wrong_room_is_rejected_before_authentication(self):
        with self.assertRaises(service.InstallError) as error:
            self.run_socket([[dict(cmd="RoomInfo", seed_name="another-room")]])
        self.assertNotIn("not-logged", error.exception.public_message)

    def test_mismatched_slot_identity_is_rejected(self):
        connected = self.connected()
        connected["slot_data"]["token"] = "0" * 64
        with self.assertRaises(service.InstallError):
            self.run_socket([[dict(cmd="RoomInfo", seed_name=self.data["room"])], [connected]])

    def test_wrong_password_has_a_fixed_public_error(self):
        with self.assertRaises(service.InstallError) as error:
            self.run_socket([[dict(cmd="ConnectionRefused", errors=["InvalidPassword"])]] )
        self.assertIn("password", error.exception.public_message.lower())
        self.assertNotIn("not-logged", error.exception.public_message)

    def test_cancelled_scout_does_not_open_a_socket(self):
        event = threading.Event()
        event.set()
        with patch("websockets.legacy.client.connect") as connect:
            with self.assertRaises(service.InstallCancelled):
                asyncio.run(service.fetch_roster(self.data, "ws://127.0.0.1:1", "", event))
        connect.assert_not_called()


class InstallationTransactionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manifest, self.data = fixture(self.root)
        self.base = self.root / "application"
        self.profile = self.base / self.data["token"]
        self.game = self.root / "game"
        self.tools = self.root / "tools"
        self.mods = self.game / "mods"
        self.source = self.root / "prepared"
        self.old_files = {}
        for path, raw in (
            (self.game / "Triforce.exe", b"old game"),
            (self.game / "triforce_vk.dll", b"old renderer"),
            (self.game / "image.bin", b"original image"),
            (self.game / "romfs/Pack/ZsDic.pack.zs", b"native dictionary"),
            (self.tools / "host/hos_main.c", b"old host"),
            (self.tools / "nx2/build.py", b"native build entry"),
            (self.game / "user/save/slot_00/progress.sav", b"original game save"),
            (self.profile / "user/save/slot_00/progress.sav", b"room save"),
            (self.profile / "native-checks.json", b'{"checked":[1,2,3]}'),
            (self.mods / "Costumes/romfs/untouched", b"unrelated mod"),
            (self.mods / "Archipelago/romfs/old", b"old AP mod"),
            (self.mods / "My Seed/romfs" / install_mod.REST, b"old randomizer"),
        ):
            put(path, raw)
            self.old_files[path] = raw
        write_session = dict(Token=self.data["token"], Room=self.data["room"], Player=self.data["player"],
                             Slot=self.data["slot"], Baseline=3, UUID="preserved-uuid", AutoConnect=False)
        put(self.profile / "native-session.json", json.dumps(write_session).encode())
        self.old_files[self.profile / "native-session.json"] = (self.profile / "native-session.json").read_bytes()
        put(self.mods / "Archipelago" / install_mod.MARK, json.dumps(dict(owner=install_mod.OWNER, room="old-room")).encode())
        self.old_files[self.mods / "Archipelago" / install_mod.MARK] = (self.mods / "Archipelago" / install_mod.MARK).read_bytes()
        put(self.source / "Archipelago/romfs/Archipelago/room-v1.txt", self.data["token"].encode())
        put(self.source / "Archipelago/romfs/new", b"new randomized resources")
        put(self.source / "Archipelago/archipelago.dll", b"new native module")
        put(self.base / "outils.json", json.dumps(dict(keep="setting", ports={"hookshot": dict(keep="other port")})).encode())
        self.old_files[self.base / "outils.json"] = (self.base / "outils.json").read_bytes()
        self.request = dict(base=str(self.base), manifest=str(self.manifest), server="127.0.0.1:1", password="test-secret",
                            game=str(self.game), romfs=str(self.game / "romfs"), tools=str(self.tools), mods=str(self.mods),
                            node=str(self.root / "node.exe"), rebuild=True)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(service, "_running_game", return_value=False))
        self.stack.enter_context(patch.object(service, "fetch_roster", new=AsyncMock(return_value={})))
        self.stack.enter_context(patch.object(app_runtime, "ensure_builder", return_value=self.root / "ootrr.exe"))
        self.stack.enter_context(patch.object(service.native_setup, "runtime_cache_name", return_value="fixture-runtime"))
        self.stack.enter_context(patch.object(service.native_setup, "protect_password", return_value="protected"))
        self.stack.enter_context(patch.object(service.player, "build"))
        self.prepare = self.stack.enter_context(patch.object(service.player, "prepare", return_value=self.source))
        def install_tools(base, chooser, configured):
            put(self.tools / "host/hos_main.c", b"new host")
            for name in service.native_setup.RT_FILES:
                put(self.tools / "host" / name, b"new helper")
            return self.tools
        self.tools_install = self.stack.enter_context(patch.object(service.native_setup, "install_tools", side_effect=install_tools))
        def save_session(root, runtime, data, roster, prepared):
            previous = json.loads((root / "native-session.json").read_bytes())
            previous.update(Server=runtime["server"], ProtectedPassword=runtime["protected"], Baseline=runtime["baseline"])
            put(root / "native-session.json", json.dumps(previous).encode())
        self.session_save = self.stack.enter_context(patch.object(service.native_setup, "save_session", side_effect=save_session))
        self.compatible = self.stack.enter_context(patch.object(service.native_setup, "compiled_game", return_value=True))
        self.executable = self.stack.enter_context(patch.object(service.native_setup, "compiled_executable", return_value=self.game / "Triforce.exe"))

    def assert_saves_unchanged(self):
        for path, raw in self.old_files.items():
            if path.suffix == ".sav" or path.name == "native-checks.json":
                self.assertEqual(path.read_bytes(), raw)

    def test_success_preserves_history_uuid_and_other_mods_and_moves_old_seed(self):
        progress = []
        result = service.install(self.request, lambda percent, message: progress.append(percent))
        self.assertTrue(result["ready"])
        self.assertFalse(result["build_required"])
        self.assertEqual((self.mods / "Archipelago/romfs/new").read_bytes(), b"new randomized resources")
        self.assertEqual((self.mods / "Costumes/romfs/untouched").read_bytes(), b"unrelated mod")
        self.assertFalse((self.mods / "My Seed").exists())
        self.assertEqual(len(list(install_mod.state_dir(self.mods).glob("previous-randomizer-*"))), 1)
        current = json.loads((self.profile / "native-session.json").read_bytes())
        self.assertEqual(current["UUID"], "preserved-uuid")
        self.assertEqual(current["Baseline"], 3)
        self.assertTrue(current["AutoConnect"])
        config = json.loads((self.base / "outils.json").read_bytes())
        self.assertEqual(config["keep"], "setting")
        self.assertEqual(config["ports"]["hookshot"], dict(keep="other port"))
        self.assertNotIn("node", config)
        self.assertNotIn("password", config)
        self.assertEqual(progress[-1], 100)
        self.assert_saves_unchanged()

    def test_failed_build_restores_mod_native_sources_settings_and_executable(self):
        self.compatible.return_value = False
        def fail(*args):
            (self.game / "Triforce.exe").write_bytes(b"partial build")
            raise service.InstallError("Fixture build failed")
        with patch.object(service, "_build_game", side_effect=fail):
            with self.assertRaises(service.InstallError):
                service.install(self.request)
        for path, raw in self.old_files.items():
            self.assertEqual(path.read_bytes(), raw, str(path))
        self.assertFalse((self.mods / "Archipelago/romfs/new").exists())
        self.assertTrue((self.mods / "My Seed").is_dir())

    def test_cancel_after_preparation_leaves_active_installation_untouched(self):
        event = threading.Event()
        def prepared(*args):
            event.set()
            return self.source
        self.prepare.side_effect = prepared
        with self.assertRaises(service.InstallCancelled):
            service.install(self.request, cancel=event)
        self.tools_install.assert_not_called()
        self.session_save.assert_not_called()
        for path, raw in self.old_files.items():
            self.assertEqual(path.read_bytes(), raw, str(path))

    def test_existing_client_lock_prevents_even_an_ap_connection(self):
        lock = self.profile / "client.lock"
        put(lock, b"")
        with service.exclusive(lock):
            with self.assertRaises(service.InstallError):
                service.install(self.request)
        service.fetch_roster.assert_not_called()
        self.tools_install.assert_not_called()

    def test_a_different_game_romfs_is_rejected_before_connecting(self):
        other = self.root / "different-game/romfs"
        put(other / "Pack/ZsDic.pack.zs", b"another dictionary")
        request = dict(self.request, romfs=str(other))
        with self.assertRaises(service.InstallError):
            service.install(request)
        service.fetch_roster.assert_not_called()

    def test_a_romfs_junction_still_checks_the_selected_game_host(self):
        external = self.root / "external-romfs"
        put(external / "Pack/ZsDic.pack.zs", b"external dictionary")
        original_resolve = Path.resolve
        lexical_romfs = self.game / "romfs"
        def resolve(path, *args, **kwargs):
            return external if path == lexical_romfs else original_resolve(path, *args, **kwargs)
        with patch.object(Path, "resolve", resolve):
            result = service.install(dict(self.request, romfs=str(external)))
            discovered = service.discover(self.base)
        self.assertTrue(result["ready"])
        self.assertEqual(discovered["game"], str(self.game))
        self.assertEqual(discovered["romfs"], str(external))
        self.assertTrue(all(call.args[0] == lexical_romfs for call in self.compatible.call_args_list))

    def test_discovery_uses_triforce_registered_nonstandard_game_folder(self):
        with patch.object(service, "_registered_game", return_value=self.game):
            value = service.discover(self.root / "no-application-settings")
        self.assertEqual(value["game"], str(self.game))
        self.assertFalse((self.root / "no-application-settings").exists())

    def test_unexpected_error_cannot_expose_password_in_public_message_or_log(self):
        self.prepare.side_effect = RuntimeError("failing test-secret request")
        with self.assertRaises(service.InstallError) as error:
            service.install(self.request)
        self.assertNotIn("test-secret", error.exception.public_message)
        self.assertNotIn("test-secret", Path(error.exception.diagnostic_log).read_text())
        self.assertIn("[redacted]", Path(error.exception.diagnostic_log).read_text())
        self.tools_install.assert_not_called()

    def test_normal_launch_does_not_enable_scripted_or_live_input(self):
        put(self.mods / "Archipelago/romfs/Archipelago/room-v1.txt", self.data["token"].encode())
        result = dict(profile=str(self.profile), game=str(self.game), tools=str(self.tools), mods=str(self.mods))
        with patch.dict(os.environ, {"HOS_INPUT_LIVE": "inherited-test-path", "HOS_INPUT_SCRIPT_BACKGROUND": "1"}), \
                patch.object(app_runtime, "spawn_process") as spawn:
            service.launch(result)
        args, options = spawn.call_args
        self.assertEqual(args[0][:2], [str(self.game / "Triforce.exe"), str(self.game / "image.bin")])
        self.assertFalse(any(key.startswith("HOS_INPUT_") for key in options["env"]))
        self.assertEqual(options["env"]["HOS_MODS"], str(self.mods))
        self.assertEqual(options["env"]["HOS_SAVE_LOCK"], "1")

    def test_bin_layout_launches_the_certified_game_instead_of_the_setup_launcher(self):
        put(self.mods / "Archipelago/romfs/Archipelago/room-v1.txt", self.data["token"].encode())
        binary = self.game / "bin/Triforce.exe"
        put(binary, b"certified native game")
        self.executable.return_value = binary
        (self.game / "Triforce.exe").write_bytes(b"setup launcher")
        result = dict(profile=str(self.profile), game=str(self.game), tools=str(self.tools), mods=str(self.mods))
        with patch.object(app_runtime, "spawn_process") as spawn:
            service.launch(result)
        args, options = spawn.call_args
        self.assertEqual(args[0][0], str(binary))
        self.assertEqual(args[0][1], str(self.game / "image.bin"))
        self.assertEqual(options["cwd"], binary.parent)
        self.assertIn(str(self.profile / "user"), args[0])


class ExistingRendererEnvironmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.tools = self.root / "setup/tools"
        self.game = self.root / "game"

    def wgpu(self, root):
        for relative in ("include/webgpu/webgpu.h", "lib/wgpu_native.dll", "lib/wgpu_native.dll.lib"):
            put(root / relative, b"existing Triforce renderer")

    def ngx(self, root):
        for relative in ("include/nvsdk_ngx.h", "lib/nvsdk_ngx_s.lib"):
            put(root / relative, b"already installed SDK")

    def test_bundled_webgpu_and_an_already_used_ngx_sdk_are_reused(self):
        self.wgpu(self.tools / "wgpu-native")
        self.ngx(self.tools.parent / "ngx-sdk")
        (self.game / "ngx").mkdir(parents=True)
        with patch.dict(os.environ, {"WGPU_NATIVE": "missing", "HOOKSHOT_NGX_SDK": "missing"}):
            result = service._build_environment(self.game, self.tools, self.game / "mods")
        self.assertEqual(result["WGPU_NATIVE"], str(self.tools / "wgpu-native"))
        self.assertEqual(result["HOOKSHOT_NGX_SDK"], str(self.tools.parent / "ngx-sdk"))

    def test_valid_explicit_sdk_choices_are_preserved(self):
        self.wgpu(self.tools / "wgpu-native")
        self.wgpu(self.root / "chosen-wgpu")
        self.ngx(self.tools.parent / "ngx-sdk")
        self.ngx(self.root / "chosen-ngx")
        (self.game / "ngx").mkdir(parents=True)
        selected = dict(WGPU_NATIVE=str(self.root / "chosen-wgpu"), HOOKSHOT_NGX_SDK=str(self.root / "chosen-ngx"))
        with patch.dict(os.environ, selected):
            result = service._build_environment(self.game, self.tools, self.game / "mods")
        self.assertEqual({key: result[key] for key in selected}, selected)

    def test_sdk_presence_does_not_enable_a_new_licensed_feature(self):
        self.ngx(self.tools.parent / "ngx-sdk")
        with patch.dict(os.environ, {}, clear=True):
            result = service._build_environment(self.game, self.tools, self.game / "mods")
        self.assertNotIn("HOOKSHOT_NGX_SDK", result)


if __name__ == "__main__":
    unittest.main()
