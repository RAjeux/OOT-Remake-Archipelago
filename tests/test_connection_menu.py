"""Exercise the connection-menu ABI against a copied local Archipelago room.

One DLL lifetime runs in each child process, like a game launch. Only temporary
profiles and a copied room are used; life/cursor callbacks are test models, not
an assertion that a real game inventory or Link's animation changed.
"""
import argparse
import asyncio
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

from support import server_command
from test_offline_deathlink import Peer, room_files, until, native_setup
from ootrr_triforce.catalog import CHECK_FLAGS, LOCATION_IDS

ROOT = Path(__file__).resolve().parents[1]
TEST_PASSWORD = "menu-test-pässword"


def worker(root, token, library):
    dll = C.CDLL(str(library))
    dll.AP_SetLanguage.argtypes = [C.c_char_p]
    dll.AP_Start.argtypes = [C.c_char_p, C.c_char_p]
    dll.AP_ConnectionInfo.argtypes = [C.c_void_p, C.c_int]
    dll.AP_Connect.argtypes = [C.c_char_p, C.c_char_p, C.c_int, C.c_int]
    dll.AP_Disconnect.argtypes = []
    dll.AP_Opened.argtypes = [C.POINTER(C.c_uint32), C.c_int, C.c_int]
    dll.AP_Next.argtypes = [C.c_int]
    dll.AP_Applied.argtypes = [C.c_int]
    dll.AP_DeathLink.argtypes = [C.c_int]
    dll.AP_Cursor.restype = C.c_uint32
    dll.AP_SetLanguage(b"fr")
    assert dll.AP_Start(os.fsencode(root), token.encode("ascii")) == 1
    life, kills, cursor = -1, 0, 0

    def snapshot():
        buffer = C.create_string_buffer(8192)
        length = dll.AP_ConnectionInfo(buffer, len(buffer))
        assert length > 0 and length == len(buffer.value)
        history = []
        for index in range(20000):
            item = dll.AP_Next(index)
            if not item:
                break
            history.append(item)
        else:
            raise AssertionError("Native item history did not terminate")
        return {"snapshot": json.loads(buffer.value.decode("utf-8")),
                "history": history, "cursor": cursor, "next_for_cursor": dll.AP_Next(cursor),
                "cursor_hash": dll.AP_Cursor(), "life": life, "remote_kills": kills}

    print(json.dumps(snapshot()), flush=True)
    for line in sys.stdin:
        request = json.loads(line)
        result = None
        if request.get("action") == "connect":
            result = dll.AP_Connect(request["server"].encode("utf-8"),
                                    request.get("password", "").encode("utf-8"),
                                    request.get("mode", 0), request.get("automatic", 0))
        elif request.get("action") == "disconnect":
            result = dll.AP_Disconnect()
        if "opened" in request:
            dll.AP_Opened((C.c_uint32 * 1)(request["opened"]), 1, 0)
        if request.get("advance"):
            assert dll.AP_Next(cursor), "Cannot commit a nonexistent test item"
            dll.AP_Applied(cursor)
            cursor += 1
        if "cursor" in request:
            cursor = request["cursor"]
        if "life" in request:
            life = request["life"]
        if dll.AP_DeathLink(life):
            kills += 1
            life = 1
            assert dll.AP_DeathLink(1) == 0
        print(json.dumps({**snapshot(), "result": result}), flush=True)
        if request.get("stop"):
            os._exit(0)  # The DLL owns process-lifetime background workers/locks.


class NativeWorker:
    def __init__(self, root, token, library, errors):
        self.root, self.token, self.library, self.errors = root, token, library, errors
        self.process = None

    async def start(self):
        self.process = await asyncio.create_subprocess_exec(
            sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--worker",
            str(self.root), self.token, str(self.library), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=self.errors)
        return await self.read()

    async def read(self):
        line = await asyncio.wait_for(self.process.stdout.readline(), 15)
        assert line, "Native menu worker stopped answering"
        return json.loads(line)

    async def request(self, **packet):
        self.process.stdin.write((json.dumps(packet) + "\n").encode("utf-8"))
        await self.process.stdin.drain()
        return await self.read()

    async def close(self):
        if self.process and self.process.returncode is None:
            try:
                await self.request(stop=True)
                await asyncio.wait_for(self.process.wait(), 10)
                assert self.process.returncode == 0
            finally:
                if self.process.returncode is None:
                    self.process.kill()
                    await self.process.wait()


class PasswordPeer(Peer):
    def __init__(self, uri, password):
        super().__init__(uri, "Ami", "Dark Souls III")
        self.password = password

    async def send(self, *packets):
        for packet in packets:
            if packet.get("cmd") == "Connect":
                packet["password"] = self.password
        await super().send(*packets)


async def exercise(temporary, source, library):
    source_zip = next(source.glob("*.zip"))
    source_hash = hashlib.sha256(source_zip.read_bytes()).hexdigest()
    multidata, data = room_files(source, temporary, None)
    profile = temporary / data["token"]
    profile.mkdir()
    with socket.socket() as address:
        address.bind(("127.0.0.1", 0))
        port = address.getsockname()[1]
    endpoint, uri = f"127.0.0.1:{port}", f"ws://127.0.0.1:{port}"
    password = TEST_PASSWORD if os.name == "nt" else ""
    native_setup.save_session(profile, {"server": uri, "protected": "", "baseline": 13},
                              {**data, "death_link": True}, {})
    settings_path = profile / "native-session.json"
    settings = json.loads(settings_path.read_bytes())
    settings.update(AutoConnect=False, FutureMenuMetadata={"retain": "unchanged"}, Language="en")
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    server_log = temporary / "server.log"
    workers, peer, server = [], None, None
    with server_log.open("wb") as output, (temporary / "worker-errors.log").open("wb") as errors:
        server = subprocess.Popen([*server_command(), str(multidata), "--host", "127.0.0.1",
                                   "--port", str(port), "--password", password, "--disable_save"],
                                  cwd=temporary, stdin=subprocess.PIPE, stdout=output, stderr=output)
        try:
            async def listening():
                assert server.poll() is None
                return "server listening on" in server_log.read_text(encoding="utf-8", errors="replace")
            await until(listening, "menu test server startup")
            peer = await PasswordPeer(uri, password).start()
            native = NativeWorker(profile, data["token"], library, errors)
            workers.append(native)
            first = await native.start()
            assert first["snapshot"]["state"] == "disconnected"
            assert first["snapshot"]["language"] == "fr" and first["snapshot"]["slot"] == data["slot"]
            assert first["snapshot"]["room"] == data["room"] and not first["snapshot"]["auto_connect"]
            assert set(first["snapshot"]) == {"server", "slot", "room", "state", "error_code",
                                               "has_password", "auto_connect", "language"}
            await asyncio.sleep(0.3)
            assert (await native.request())["snapshot"]["state"] == "disconnected", "AutoConnect=false retried"
            invalid = await native.request(action="connect", server="ws://user:secret@localhost", mode=0)
            assert invalid["result"] == -1 and invalid["snapshot"]["error_code"] == "invalid_server"

            async def status(expected):
                async def probe():
                    state = await native.request()
                    return state if state["snapshot"]["state"] == expected else None
                return await until(probe, "menu status " + expected)

            if os.name == "nt":
                assert (await native.request(action="connect", server=endpoint, password="wrong-test-password", mode=1))["result"] == 1
                refused = await status("retrying")
                assert refused["snapshot"]["error_code"] == "connection_refused"
            assert (await native.request(action="connect", server=endpoint, password=password, mode=1))["result"] == 1
            connected = await status("connected")
            assert connected["snapshot"]["server"] == uri
            baseline, cursor_hash = connected["history"], connected["cursor_hash"]
            assert connected["snapshot"]["has_password"] == bool(password)
            assert connected["cursor_hash"] == native_setup.cursor_hash(data["token"])
            await native.request(cursor=len(baseline), life=2)
            await peer.bounce()
            await asyncio.sleep(0.1)
            assert (await native.request())["remote_kills"] == 0
            assert (await native.request(action="disconnect"))["result"] == 1
            offline = await status("disconnected")
            assert offline["history"] == [] and offline["next_for_cursor"] == 0
            local_name = next(iter(data["checks"]))
            await native.request(opened=CHECK_FLAGS[local_name][0])
            missing = peer.connected["missing_locations"]
            for start in range(0, len(missing), 200):
                await peer.send({"cmd": "LocationScouts", "locations": missing[start:start + 200], "create_as_hint": 0})
            await peer.wait(lambda: all(location in peer.scouts for location in missing), "menu test DS3 scout")
            remote = [(location, item) for location, (item, owner) in peer.scouts.items() if owner == data["player"]][:2]
            assert len(remote) == 2
            for location, _ in remote:
                await peer.send({"cmd": "LocationChecks", "locations": [location]})
                await peer.fence()
            assert (await native.request(life=0))["remote_kills"] == 0
            assert (await native.request(action="connect", server=endpoint, mode=0))["result"] == 1
            recovered = await status("connected")
            expected = baseline + [item for _, item in remote]
            assert recovered["history"] == expected and recovered["next_for_cursor"] == remote[0][1]
            assert recovered["remote_kills"] == 0 and recovered["cursor_hash"] == cursor_hash
            for _ in remote:
                await native.request(advance=True)
            applied = await native.request()
            assert applied["cursor"] == len(expected) and applied["next_for_cursor"] == 0
            async def check_recovered():
                journal = profile / "native-checks.json"
                log = profile / "archipelago-jeu.log"
                return (journal.exists() and LOCATION_IDS[local_name] in json.loads(journal.read_bytes())["Locations"]
                        and "Location checked · " + local_name in log.read_text(encoding="utf-8", errors="replace"))
            await until(check_recovered, "offline check journal")
            await peer.bounce()
            async def live_death():
                state = await native.request()
                return state if state["remote_kills"] == 1 else None
            await until(live_death, "live DeathLink after menu reconnect")
            await native.request(action="disconnect")
            saved = json.loads(settings_path.read_bytes())
            assert saved["Baseline"] == 13 and saved["FutureMenuMetadata"] == {"retain": "unchanged"}
            assert saved["Token"] == settings["Token"] and saved["UUID"] == settings["UUID"]
            assert saved["Slot"] == settings["Slot"] and saved["Room"] == settings["Room"]
            assert saved["AutoConnect"] is False
            assert bool(saved["ProtectedPassword"]) == bool(password)
            if password:
                assert password not in settings_path.read_text(encoding="utf-8")
            await native.close()
            native = NativeWorker(profile, data["token"], library, errors)
            workers.append(native)
            assert (await native.start())["snapshot"]["state"] == "disconnected"
            await native.request(cursor=len(expected), life=0)
            assert (await native.request(action="connect", server=endpoint, mode=0))["result"] == 1
            restarted = await status("connected")
            assert restarted["history"] == expected and restarted["next_for_cursor"] == 0
            assert restarted["remote_kills"] == 0 and restarted["cursor_hash"] == cursor_hash
            log = (profile / "archipelago-jeu.log").read_text(encoding="utf-8", errors="replace")
            assert TEST_PASSWORD not in log and "wrong-test-password" not in log
            assert not peer.from_player(data["slot"]), "remote DeathLink echoed after a menu transition"
            assert hashlib.sha256(source_zip.read_bytes()).hexdigest() == source_hash
            return {"result": "PASS", "scope": "real DLL menu ABI and isolated local AP server",
                    "language": "fr", "autoconnect_false_preserved": True, "manual_connect_disconnect": True,
                    "wrong_password_repaired": os.name == "nt", "dpapi_persistence_restart": os.name == "nt",
                    "offline_remote_items": len(remote), "history_and_caller_cursor_preserved": True,
                    "offline_checks_preserved": True, "deathlink_live_not_replayed": True,
                    "baseline_unknown_fields_and_identity_preserved": True, "source_room_unchanged": True,
                    "source_game_or_save_loaded": False}
        finally:
            for native in workers:
                await native.close()
            if peer:
                await peer.cleanup()
            if server and server.poll() is None:
                server.terminate()
                await asyncio.to_thread(server.wait, 10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", nargs=3, metavar=("ROOT", "TOKEN", "LIBRARY"), help=argparse.SUPPRESS)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.worker:
        root, token, library = args.worker
        worker(Path(root), token, Path(library))
        return
    library = ROOT / ("dist/native/archipelago.dll" if os.name == "nt" else "build/archipelago.so")
    with tempfile.TemporaryDirectory(prefix="ootrr-connection-menu-") as temporary:
        result = asyncio.run(exercise(Path(temporary), ROOT / "tests/fixtures/complet-v2", library))
    document = json.dumps(result, indent=2) + "\n"
    if args.report:
        args.report.write_text(document, encoding="utf-8")
    print(document, end="")


if __name__ == "__main__":
    main()
