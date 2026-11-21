"""Real AP server + DS3 checks + restarted native workers; no game assets required.

This validates native ABI history and simulated life transitions. It does not
assert that a real Triforce inventory changed or that Link died on screen.
"""
import argparse
import asyncio
from collections import Counter, defaultdict
import contextlib
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
# Use the packaged WebSocket implementation with the current source installer.
sys.path.insert(0, str(ROOT / "dist/Client-OOT-Remake.pyz"))
from websockets.legacy.client import connect
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce import native_setup, player
from ootrr_triforce.catalog import ITEM_IDS
from support import server_command


def worker(root, token, library):
    """One DLL lifetime per process, like closing and reopening Triforce."""
    dll = C.CDLL(str(library))
    dll.AP_Start.argtypes = [C.c_char_p, C.c_char_p]
    dll.AP_Start.restype = C.c_int
    dll.AP_Next.argtypes = [C.c_int]
    dll.AP_Next.restype = C.c_int
    dll.AP_DeathLink.argtypes = [C.c_int]
    dll.AP_DeathLink.restype = C.c_int
    if dll.AP_Start(os.fsencode(root), token.encode("ascii")) != 1:
        raise RuntimeError("AP_Start refused the isolated test profile")
    lock = threading.Lock()
    state = {"life": -1, "remote_kills": 0, "paused": False, "error": None}

    def tick():
        if dll.AP_DeathLink(state["life"]):
            state["remote_kills"] += 1
            state["life"] = 1
            # Simulate the actual game accepting the kill and reporting death.
            assert dll.AP_DeathLink(1) == 0

    def ticking():
        try:
            while True:
                with lock:
                    if not state["paused"]:
                        tick()
                time.sleep(0.025)
        except BaseException as exc:
            state["error"] = f"{type(exc).__name__}: {exc}"

    def snapshot():
        history = []
        for index in range(20000):
            item = dll.AP_Next(index)
            if not item:
                break
            history.append(item)
        else:
            raise AssertionError("Native history did not terminate")
        logfile = root / "archipelago-jeu.log"
        log = logfile.read_text(encoding="utf-8", errors="replace") if logfile.exists() else ""
        return {**state, "history": history, "next_item": dll.AP_Next(len(history)),
                "connected_count": log.count("Archipelago connecté"), "pid": os.getpid()}

    threading.Thread(target=ticking, daemon=True).start()
    print(json.dumps({"started": True, "pid": os.getpid()}), flush=True)
    for line in sys.stdin:
        request = json.loads(line)
        with lock:
            if "life" in request:
                assert request["life"] in (-1, 0, 1)
                state["life"] = request["life"]
                if not state["paused"]:
                    tick()
            if "paused" in request:
                state["paused"] = bool(request["paused"])
            response = snapshot()
        print(json.dumps(response), flush=True)
        if request.get("stop"):
            # Native Go goroutines intentionally live until the host exits.
            os._exit(0)


async def until(probe, description, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = await probe()
        if result:
            return result
        await asyncio.sleep(0.05)
    raise AssertionError("Timeout: " + description)


class Worker:
    def __init__(self, root, token, library, stderr):
        self.root, self.token, self.library, self.stderr = root, token, library, stderr
        self.process = None

    async def start(self):
        self.process = await asyncio.create_subprocess_exec(
            sys.executable, str(Path(__file__).resolve()), "--worker", str(self.root),
            self.token, str(self.library), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=self.stderr,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        greeting = await asyncio.wait_for(self.process.stdout.readline(), 15)
        assert greeting, "Native worker exited before AP_Start completed"
        assert json.loads(greeting)["started"]
        return self

    async def request(self, **request):
        assert self.process is not None and self.process.returncode is None
        self.process.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
        await self.process.stdin.drain()
        response = await asyncio.wait_for(self.process.stdout.readline(), 15)
        assert response, "Native worker stopped answering"
        data = json.loads(response)
        assert data["error"] is None, data["error"]
        return data

    async def stop(self):
        if self.process is not None and self.process.returncode is None:
            await self.request(stop=True)
            await asyncio.wait_for(self.process.wait(), 10)
            assert self.process.returncode == 0

    async def cleanup(self):
        if self.process is not None and self.process.returncode is None:
            self.process.kill()
            await self.process.wait()


def network_item(record):
    return ((record["item"], record["location"], record["player"])
            if isinstance(record, dict) else tuple(record[:3]))


class Peer:
    def __init__(self, uri, name, game):
        self.uri, self.name, self.game = uri, name, game
        self.info = self.connected = None
        self.scouts, self.retrieved = {}, set()
        self.bounces = []
        self.ws = self.reader = None

    async def start(self):
        self.ws = await connect(self.uri, max_size=32 * 1024 * 1024, open_timeout=15)

        async def read():
            async for raw in self.ws:
                for packet in json.loads(raw):
                    command = packet["cmd"]
                    if command == "RoomInfo":
                        self.info = packet
                    elif command == "Connected":
                        self.connected = packet
                    elif command == "ConnectionRefused":
                        raise AssertionError("Peer connection refused: " + repr(packet["errors"]))
                    elif command == "LocationInfo":
                        for record in packet["locations"]:
                            item, location, owner = network_item(record)
                            self.scouts[location] = (item, owner)
                    elif command == "Retrieved":
                        self.retrieved.update(packet["keys"])
                    elif command == "Bounced" and "DeathLink" in packet.get("tags", []):
                        self.bounces.append(packet["data"])

        self.reader = asyncio.create_task(read())
        await self.wait(lambda: self.info, "DS3 RoomInfo")
        await self.send({"cmd": "Connect", "name": self.name, "game": self.game,
                         "password": "", "uuid": str(uuid.uuid4()), "items_handling": 7,
                         "version": {"major": 0, "minor": 6, "build": 7, "class": "Version"},
                         "tags": ["AP", "DeathLink"], "slot_data": True})
        await self.wait(lambda: self.connected, "authenticated DS3 client")
        return self

    async def send(self, *packets):
        await self.ws.send(json.dumps(packets))

    async def wait(self, predicate, description):
        async def probe():
            if self.reader.done():
                self.reader.result()
                raise AssertionError("DS3 connection closed")
            return predicate()
        return await until(probe, description)

    async def fence(self):
        key = "ootrr-integration-" + uuid.uuid4().hex
        await self.send({"cmd": "Get", "keys": [key]})
        await self.wait(lambda: key in self.retrieved, "server processing fence")

    async def bounce(self, timestamp=None):
        data = {"time": timestamp if timestamp is not None else time.time_ns() / 1e9,
                "source": self.name, "cause": "Mort DS3 simulée par le test ABI."}
        await self.send({"cmd": "Bounce", "tags": ["DeathLink"], "data": data})
        await self.fence()
        return data

    def from_player(self, name):
        return [data for data in self.bounces if data.get("source") == name]

    async def cleanup(self):
        if self.ws is not None:
            await self.ws.close()
        if self.reader is not None:
            self.reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.reader


def room_files(source, target, wanted_player):
    """Copy only multidata/manifests, never the source room's persistent save."""
    if source.is_dir():
        inputs = sorted(source.glob("*.archipelago")) + sorted(source.glob("*.apootrr"))
        if not any(path.suffix == ".archipelago" for path in inputs):
            archives = list(source.glob("*.zip"))
            assert len(archives) == 1, "Choose a room ZIP or directory containing one room"
            source = archives[0]
    elif source.suffix in (".apootrr", ".archipelago"):
        inputs = [source] + sorted(source.parent.glob(
            "*.archipelago" if source.suffix == ".apootrr" else "*.apootrr"))
    if source.suffix == ".zip":
        with ZipFile(source) as archive:
            for member in archive.namelist():
                if member.endswith((".apootrr", ".archipelago")):
                    dest = target / Path(member).name
                    assert not dest.exists(), "Duplicate room file name in ZIP"
                    dest.write_bytes(archive.read(member))
    else:
        for path in inputs:
            shutil.copy2(path, target / path.name)
    multidata = list(target.glob("*.archipelago"))
    assert len(multidata) == 1, "Choose exactly one .archipelago room"
    manifests = [player.read_manifest(path) for path in target.glob("*.apootrr")]
    if wanted_player:
        manifests = [data for data in manifests if data["slot"] == wanted_player]
    assert len(manifests) == 1, "Choose one Zelda manifest with --player"
    return multidata[0], manifests[0]


async def history_ready(worker, expected_connections, expected=None):
    async def connected():
        data = await worker.request()
        return data if data["connected_count"] >= expected_connections else None
    await until(connected, "native WebSocket authentication")
    if expected is None:
        # Connected is logged just before the Sync/Get fence. Let this local
        # round-trip finish, then require a stable baseline before closing.
        await asyncio.sleep(0.5)
        previous = (await worker.request())["history"]
        for _ in range(3):
            await asyncio.sleep(0.15)
            current = (await worker.request())["history"]
            assert current == previous, "Initial history did not stabilize"
        return previous

    async def received():
        data = await worker.request()
        return data if data["history"] == expected and data["next_item"] == 0 else None
    return await until(received, "native exact item history after restart")


async def exercise(options, temporary):
    multidata, data = room_files(options.room, temporary, options.player)
    root = temporary / data["token"]
    root.mkdir()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    uri = f"ws://127.0.0.1:{port}"
    # Enable the feature in this isolated native profile, including old fixture rooms.
    native_setup.save_session(root, {"server": uri, "protected": "", "baseline": 0},
                              {**data, "death_link": True}, {})
    assert json.loads((root / "native-session.json").read_text())["DeathLink"] is True
    serverlog = temporary / "server.log"
    workers = []
    peer, server = None, None
    with serverlog.open("wb") as server_out, (temporary / "worker-errors.log").open("wb") as errors:
        server = subprocess.Popen([*server_command(), str(multidata), "--host", "127.0.0.1",
                                   "--port", str(port), "--disable_save"],
                                  cwd=temporary, stdin=subprocess.PIPE,
                                  stdout=server_out, stderr=server_out)
        try:
            async def listening():
                assert server.poll() is None, "AP server stopped before listening"
                return "server listening on" in serverlog.read_text(encoding="utf-8", errors="replace")
            await until(listening, "isolated Archipelago server startup")
            peer = await Peer(uri, options.peer, options.peer_game).start()
            assert peer.connected["slot"] != data["player"]

            async def new_worker():
                instance = Worker(root, data["token"], options.native_lib, errors)
                workers.append(instance)
                return await instance.start()

            native = await new_worker()
            baseline = await history_ready(native, 1)
            await native.stop()
            assert native.process.returncode == 0

            missing = peer.connected["missing_locations"]
            for start in range(0, len(missing), 200):
                await peer.send({"cmd": "LocationScouts", "locations": missing[start:start + 200],
                                 "create_as_hint": 0})
            await peer.wait(lambda: all(location in peer.scouts for location in missing), "DS3 location scouting")
            candidates = [(location, item) for location, (item, owner) in peer.scouts.items()
                          if owner == data["player"] and location in missing]
            assert len(candidates) >= 6, "This room needs six unchecked DS3 items for Zelda"
            groups = defaultdict(list)
            for row in candidates:
                groups[row[1]].append(row)
            repeated = next((rows[:2] for rows in groups.values() if len(rows) >= 2), [])
            selected = repeated[:]
            selected_items = {item for _, item in selected}
            for row in candidates:
                if len(selected) == 6:
                    break
                if row[1] not in selected_items:
                    selected.append(row)
                    selected_items.add(row[1])
            for row in candidates:
                if len(selected) == 6:
                    break
                if row not in selected:
                    selected.append(row)
            expected = baseline + [item for _, item in selected]
            for location, _ in selected:
                await peer.send({"cmd": "LocationChecks", "locations": [location]})
                await peer.fence()
            assert native.process.returncode == 0, "Zelda must remain closed for all DS3 checks"

            native = await new_worker()
            recovered = await history_ready(native, 2, expected)
            assert Counter(recovered["history"][len(baseline):]) == Counter(item for _, item in selected)
            await native.stop()
            native = await new_worker()
            await history_ready(native, 3, expected)

            # Title events, including a later duplicate, never kill the next life.
            title = await peer.bounce()
            await asyncio.sleep(0.5)
            assert (await native.request())["remote_kills"] == 0
            await native.request(life=0)
            await peer.bounce(title["time"])
            await asyncio.sleep(0.5)
            assert (await native.request())["remote_kills"] == 0

            remote = await peer.bounce()
            async def killed_once():
                state = await native.request()
                return state if state["remote_kills"] == 1 and state["life"] == 1 else None
            await until(killed_once, "DS3 DeathLink to native kill request")
            await asyncio.sleep(0.7)
            assert not peer.from_player(data["slot"]), "Remote death echoed back to DS3"
            await native.request(life=0)
            await peer.bounce(remote["time"])
            await asyncio.sleep(0.5)
            assert (await native.request())["remote_kills"] == 1, "Duplicate DeathLink killed a second life"

            await native.request(life=1)
            await peer.wait(lambda: len(peer.from_player(data["slot"])) == 1, "native local death to DS3 Bounce")
            local = peer.from_player(data["slot"])[0]
            assert local["time"] > 0 and isinstance(local.get("cause"), str)
            await asyncio.sleep(0.7)
            assert len(peer.from_player(data["slot"])) == 1, "One local death sent multiple Bounces"

            # A new event arriving while dead cannot leak into the respawn.
            await peer.bounce()
            await asyncio.sleep(0.3)
            await native.request(life=0)
            await asyncio.sleep(0.3)
            assert (await native.request())["remote_kills"] == 1

            # Leave an incoming event unconsumed, close the host, and reopen it.
            await native.request(paused=True)
            await peer.bounce()
            await asyncio.sleep(0.3)
            await native.stop()
            native = await new_worker()
            await history_ready(native, 4, expected)
            await native.request(life=0)
            await asyncio.sleep(0.7)
            final = await native.request()
            assert final["remote_kills"] == 0, "DeathLink replayed after a complete host restart"
            assert final["history"] == expected and final["next_item"] == 0
            assert len(peer.from_player(data["slot"])) == 1
            item_names = {value: name for name, value in ITEM_IDS.items()}
            offline_counts = Counter(item for _, item in selected)
            return {
                "result": "PASS", "scope": "Native ABI history and simulated life transitions",
                "room": data["room"], "zelda_player": data["slot"], "zelda_slot": data["player"],
                "ds3_player": options.peer, "ds3_slot": peer.connected["slot"],
                "baseline_items": len(baseline), "offline_checks": len(selected),
                "offline_item_counts": dict(offline_counts),
                "offline_items": [{"item_id": item, "item_name": item_names[item], "count": count}
                                  for item, count in offline_counts.items()],
                "checked_ds3_locations": [location for location, _ in selected],
                "recovered_history": expected,
                "recovered_items": len(expected), "host_processes": len(workers),
                "host_process_ids": [instance.process.pid for instance in workers],
                "native_library_sha256": hashlib.sha256(options.native_lib.read_bytes()).hexdigest(),
                "offline_worker_fully_closed": True, "history_order_and_prefix_preserved": True,
                "no_extra_history_index": True, "deathlink_both_directions": True,
                "deathlink_duplicate_ignored": True, "deathlink_title_ignored": True,
                "deathlink_dead_ignored": True, "deathlink_remote_death_no_echo": True,
                "deathlink_not_replayed_after_restart": True,
                "source_multidata_modified": False,
                "real_game_inventory_or_death_validated": False,
            }
        finally:
            for instance in workers:
                await instance.cleanup()
            if peer is not None:
                await peer.cleanup()
            if server is not None and server.poll() is None:
                server.terminate()
                await asyncio.to_thread(server.wait, 10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("room", type=Path, nargs="?", default=ROOT / "tests/fixtures/neutre")
    parser.add_argument("--player", help="Zelda slot name if the source contains multiple manifests")
    parser.add_argument("--peer", default="Ami")
    parser.add_argument("--peer-game", default="Dark Souls III")
    parser.add_argument("--native-lib", type=Path,
                        default=ROOT / ("dist/native/archipelago.dll" if os.name == "nt" else "build/archipelago.so"))
    parser.add_argument("--report", type=Path)
    options = parser.parse_args()
    options.room, options.native_lib = options.room.resolve(), options.native_lib.resolve()
    assert options.native_lib.is_file(), "Build a native library exposing AP_DeathLink first"
    try:
        with tempfile.TemporaryDirectory(prefix="ootrr-offline-deathlink-") as tmp:
            report = asyncio.run(exercise(options, Path(tmp)))
    except BaseException as exc:
        if options.report:
            options.report.parent.mkdir(parents=True, exist_ok=True)
            options.report.write_text(json.dumps({"result": "FAIL", "error": f"{type(exc).__name__}: {exc}"},
                                                ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise
    if options.report:
        options.report.parent.mkdir(parents=True, exist_ok=True)
        options.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PASS {report['offline_checks']} real DS3 checks while Zelda was closed; "
          f"{report['recovered_items']} ordered native items, four host lifetimes; "
          "DeathLink bidirectional, no duplicate/title kill/echo/replay. ABI simulation only.")


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--worker":
        worker(Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]))
    else:
        main()
