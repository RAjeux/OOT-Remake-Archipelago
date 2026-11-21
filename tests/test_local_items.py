"""Verify AP handling=5 against a real isolated server, including Sync/reconnect.

The source room is copied without its save. Only temporary test checks change.
No DLL or game is rebuilt or loaded by this protocol contract test.
"""
import argparse
import asyncio
import contextlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from zipfile import ZipFile

from support import server_command

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dist/Client-OOT-Remake.pyz"))
from websockets.legacy.client import connect
from ootrr_triforce import player


def network_item(item):
    if isinstance(item, dict):
        return item["item"], item["location"], item["player"]
    return tuple(item[:3])


async def until(probe, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if probe():
            return
        await asyncio.sleep(0.025)
    raise AssertionError("Protocol test timed out")


class Peer:
    def __init__(self, uri, name, game, handling):
        self.uri, self.name, self.game, self.handling = uri, name, game, handling
        self.info = self.connected = None
        self.history, self.scouts, self.retrieved = [], {}, set()
        self.ws = self.reader = None

    async def send(self, *packets):
        await self.ws.send(json.dumps(packets))

    async def wait(self, predicate):
        def check():
            if self.reader.done():
                self.reader.result()
                raise AssertionError("Peer disconnected")
            return predicate()
        await until(check)

    async def start(self):
        self.ws = await connect(self.uri, max_size=32 * 1024 * 1024)

        async def reading():
            async for frame in self.ws:
                for packet in json.loads(frame):
                    command = packet["cmd"]
                    if command == "RoomInfo":
                        self.info = packet
                    elif command == "ConnectionRefused":
                        raise AssertionError(packet["errors"])
                    elif command == "Connected":
                        self.connected = packet
                    elif command == "LocationInfo":
                        for item in packet["locations"]:
                            identifier, location, owner = network_item(item)
                            self.scouts[location] = (identifier, owner)
                    elif command == "ReceivedItems":
                        index = packet["index"]
                        assert 0 <= index <= len(self.history), "Filtered stream contains an index hole"
                        items = [network_item(item) for item in packet["items"]]
                        if index == 0:
                            self.history = items
                        else:
                            self.history[index:] = items
                    elif command == "Retrieved":
                        self.retrieved.update(packet["keys"])

        self.reader = asyncio.create_task(reading())
        await self.wait(lambda: self.info)
        await self.send({"cmd": "Connect", "name": self.name, "game": self.game,
                         "password": "", "uuid": str(uuid.uuid4()),
                         "items_handling": self.handling, "slot_data": True, "tags": ["AP"],
                         "version": {"major": 0, "minor": 6, "build": 7, "class": "Version"}})
        await self.wait(lambda: self.connected)
        await self.fence()
        return self

    async def fence(self):
        key = "ootrr-local-items-test-" + uuid.uuid4().hex
        await self.send({"cmd": "Get", "keys": [key]})
        await self.wait(lambda: key in self.retrieved)

    async def scout(self):
        locations = self.connected["missing_locations"]
        for start in range(0, len(locations), 200):
            await self.send({"cmd": "LocationScouts", "locations": locations[start:start + 200], "create_as_hint": 0})
        await self.wait(lambda: all(location in self.scouts for location in locations))

    async def close(self):
        if self.ws:
            await self.ws.close()
        if self.reader:
            self.reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.reader


async def exercise(root, source):
    with ZipFile(next(source.glob("*.zip"))) as archive:
        for name in archive.namelist():
            if name.endswith((".apootrr", ".archipelago")):
                archive.extract(name, root)
    data = player.read_manifest(next(root.glob("*.apootrr")))
    with socket.socket() as address:
        address.bind(("127.0.0.1", 0))
        port = address.getsockname()[1]
    peers = []
    logfile = root / "server.log"
    with logfile.open("wb") as out:
        server = subprocess.Popen([*server_command(), str(next(root.glob("*.archipelago"))),
                                   "--host", "127.0.0.1", "--port", str(port), "--disable_save"],
                                  cwd=root, stdin=subprocess.PIPE, stdout=out, stderr=out)
    try:
        def listening():
            assert server.poll() is None, "Local server stopped"
            return "server listening on" in logfile.read_text(encoding="utf-8", errors="replace")
        await until(listening)
        uri = f"ws://127.0.0.1:{port}"

        async def boot(handling):
            instance = Peer(uri, data["slot"], data.get("game", "Ocarina of Time Remake (Triforce)"), handling)
            peers.append(instance)
            return await instance.start()

        local = await boot(5)
        remote = await boot(7)
        ami = Peer(uri, "Ami", "Dark Souls III", 7)
        peers.append(ami)
        await ami.start()
        await local.scout()
        await ami.scout()
        zelda = local.connected["slot"]
        own_location, own = next((location, reward) for location, reward in local.scouts.items() if reward[1] == zelda)
        foreign_location, foreign = next((location, reward) for location, reward in ami.scouts.items() if reward[1] == zelda)
        baseline_local, baseline_remote = list(local.history), list(remote.history)
        await local.send({"cmd": "LocationChecks", "locations": [own_location]})
        await local.fence()
        await remote.fence()
        assert local.history == baseline_local, "Own-world self reward was delivered a second time by mode 5"
        assert remote.history == baseline_remote + [(own[0], own_location, zelda)], "Legacy mode 7 lost the own reward"
        await ami.send({"cmd": "LocationChecks", "locations": [foreign_location]})
        await ami.fence()
        await local.fence()
        await remote.fence()
        expected = baseline_local + [(foreign[0], foreign_location, ami.connected["slot"])]
        assert local.history == expected, "Remote reward was filtered or shifted by a local check"
        await local.send({"cmd": "LocationChecks", "locations": [own_location]}, {"cmd": "Sync"})
        await local.fence()
        assert local.history == expected, "Sync reintroduced a physically granted reward"
        await local.close()
        reopened = await boot(5)
        assert reopened.history == expected, "A complete connection restart reintroduced a physically granted reward"
        await reopened.send({"cmd": "Sync"})
        await reopened.fence()
        assert reopened.history == expected, "Restarted client Sync duplicated the own reward"
        return {"result": "PASS", "items_handling": 5, "legacy_items_handling": 7,
                "own_world_self_excluded": True, "remote_received": True,
                "sync_preserved_filtered_indices": True, "restart_preserved_filtered_indices": True,
                "source_room_modified": False, "source_save_loaded": False}
    finally:
        for peer in peers:
            await peer.close()
        if server.poll() is None:
            server.terminate()
            await asyncio.to_thread(server.wait, 10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--room", type=Path, default=ROOT / "tests/fixtures/neutre")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ootrr-local-items-") as temporary:
        result = asyncio.run(exercise(Path(temporary), args.room.resolve()))
    document = json.dumps(result, indent=2) + "\n"
    if args.report:
        args.report.write_text(document, encoding="utf-8")
    print(document, end="")


if __name__ == "__main__":
    main()
