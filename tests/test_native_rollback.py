"""Compose the shipped DLL, a cloned local AP server and generated restore flows.

Inventory/flags are an explicit event-graph model, not a running Zelda game.
The real native scheduler and the real game player gate have separate C tests.
Only a temporary profile, copied DLL and a fresh local room are used.
"""
import argparse
import asyncio
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
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from oot_rando.patching import chest_flags
from oot_rando.patching.soul_adapter import murmur3
from ootrr_triforce import native_setup, player, restoration
from ootrr_triforce.catalog import GAME, ITEM_DATA, ITEM_IDS, LOCATION_IDS
from support import server_command
from test_local_items import Peer, until
from test_receipt_registration import IdentityCodec
from test_restoration import SaveRun, document, game_data, pouch
from websockets.legacy.client import connect
from websockets.legacy.server import serve
from websockets.exceptions import ConnectionClosed


def worker(profile, token, library):
    dll = C.CDLL(str(library))
    dll.AP_Start.argtypes = [C.c_char_p, C.c_char_p]
    dll.AP_Start.restype = C.c_int
    dll.AP_ConnectionInfo.argtypes = [C.c_void_p, C.c_int]
    dll.AP_ConnectionInfo.restype = C.c_int
    dll.AP_Flags.argtypes = [C.POINTER(C.c_uint32), C.c_int]
    dll.AP_Flags.restype = C.c_int
    dll.AP_Opened.argtypes = [C.POINTER(C.c_uint32), C.c_int, C.c_int]
    dll.AP_Next.argtypes = [C.c_int]
    dll.AP_Next.restype = C.c_int
    dll.AP_Applied.argtypes = [C.c_int]
    dll.AP_Cursor.restype = C.c_uint32
    dll.AP_SeedMarker.restype = C.c_uint32
    dll.AP_DeathLink.argtypes = [C.c_int]
    dll.AP_DeathLink.restype = C.c_int
    dll.AP_Restore.argtypes = [C.POINTER(C.c_uint8), C.c_int]
    dll.AP_Restore.restype = C.c_int
    assert dll.AP_Start(str(profile).encode("utf-8"), token.encode("ascii")) == 1
    flags = (C.c_uint32 * 4096)()
    count = dll.AP_Flags(flags, len(flags))
    assert 0 < count <= 4096

    def snapshot():
        buffer = C.create_string_buffer(8192)
        assert dll.AP_ConnectionInfo(buffer, len(buffer)) > 0
        history = []
        for index in range(20000):
            item = dll.AP_Next(index)
            if not item:
                break
            history.append(item)
        else:
            raise AssertionError("Native history did not terminate")
        return dict(info=json.loads(buffer.value), history=history,
                    flags=list(flags[:count]), cursor_hash=dll.AP_Cursor(), seed_marker=dll.AP_SeedMarker())

    print(json.dumps(snapshot()), flush=True)
    for line in sys.stdin:
        request = json.loads(line)
        result = {}
        if "opened" in request:
            opened = request["opened"]
            values = (C.c_uint32 * max(1, len(opened)))(*opened)
            dll.AP_Opened(values, len(opened), 0)
        if "states" in request:
            values = request["states"]
            array = (C.c_uint8 * max(1, len(values)))(*values)
            result["restore"] = dll.AP_Restore(array, len(values))
        if "applied" in request:
            dll.AP_Applied(request["applied"])
        if 'death' in request:
            result['death'] = dll.AP_DeathLink(request['death'])
        print(json.dumps({**snapshot(), **result}), flush=True)
        if request.get("stop"):
            os._exit(0)  # The real Go client owns process-lifetime workers/locks.


class Worker:
    def __init__(self, profile, token, library, errors):
        self.profile, self.token, self.library, self.errors = profile, token, library, errors
        self.process = None

    async def start(self):
        self.process = await asyncio.create_subprocess_exec(sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve()),
            "--worker", str(self.profile), self.token, str(self.library), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=self.errors)
        return await self.read()

    async def read(self):
        line = await asyncio.wait_for(self.process.stdout.readline(), 20)
        assert line, "Native worker stopped; inspect its private log"
        return json.loads(line)

    async def request(self, **data):
        self.process.stdin.write((json.dumps(data) + "\n").encode("utf-8"))
        await self.process.stdin.drain()
        return await self.read()

    async def ready(self, expected=None):
        for _ in range(200):
            value = await self.request()
            if value["info"]["state"] == "connected" and (expected is None or value["history"] == expected):
                return value
            await asyncio.sleep(0.025)
        raise AssertionError("Native room never synchronized")

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


def build_registry(root, roster):
    game, mod = root / "game", root / "stage/Archipelago/romfs"
    resources = {
        "Pack/ZsDic.pack.zs": b"dictionary", restoration.FLOW_PATH: pouch(),
        restoration.GAME_DATA: game_data(), restoration.REST: b"native sizes",
        chest_flags.EVENT_SETTINGS: document([dict(__RowId="Dm_SY_Get", EntryPointName="Dm_SY_Get",
            FlowchartFileName="Work/Event/EventFlow/Dm_SY_Get.evfc")]),
        chest_flags.ANALYZED: document([dict(__RowId="Dm_SY_Get", IsPlayerWarpFirstFrame=True)])}
    for relative, raw in resources.items():
        path = game / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    with patch.object(restoration, "Codec", IdentityCodec), \
            patch("oot_rando.game.resource_allocations.grow_resources", return_value=(b"grown sizes", {})):
        restoration.prepare_restoration(game, mod, roster)
    return mod


async def exercise(root, room, library):
    with ZipFile(next(room.glob("*.zip"))) as archive:
        for member in archive.namelist():
            if member.endswith((".apootrr", ".archipelago")):
                archive.extract(member, root)
    data = player.read_manifest(next(root.glob("*.apootrr")))
    assert data.get("local_items") and data.get("reward_mode") == "all_locations"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    log = (root / "server.log").open("wb")
    server = subprocess.Popen([*server_command(), str(next(root.glob("*.archipelago"))), "--host", "127.0.0.1",
        "--port", str(port), "--disable_save"], cwd=root, stdin=subprocess.PIPE, stdout=log, stderr=log)
    peers, workers, packets, compression = [], [], [], []
    native_log = (root / "workers.log").open("wb")
    proxy = None
    try:
        def listening():
            assert server.poll() is None, "Private AP server stopped"
            return "server listening on" in (root / "server.log").read_text(encoding="utf-8", errors="replace")
        await until(listening)
        upstream = f"ws://127.0.0.1:{port}"
        zelda = Peer(upstream, data["slot"], data.get("game", GAME), 7)
        ami = Peer(upstream, "Ami", "Dark Souls III", 7)
        for peer in (zelda, ami):
            peers.append(peer)
            await peer.start()
            await peer.scout()

        async def relay(incoming):
            compression.append(bool(incoming.extensions))
            async with connect(upstream, max_size=40 << 20) as outgoing:
                async def forward(source, target, record=False):
                    try:
                        async for frame in source:
                            if record:
                                for packet in json.loads(frame):
                                    packets.append({"cmd": packet["cmd"],
                                                    "locations": packet.get("locations", []),
                                                    "items_handling": packet.get("items_handling")})
                            await target.send(frame)
                    except ConnectionClosed:
                        # A test worker exits with its real process-lifetime Go
                        # DLL; the expected socket EOF isn't a proxy failure.
                        pass
                    finally:
                        await target.close()
                await asyncio.gather(forward(incoming, outgoing, True), forward(outgoing, incoming))
        proxy = await serve(relay, "127.0.0.1", 0, max_size=40 << 20)
        uri = f"ws://127.0.0.1:{proxy.sockets[0].getsockname()[1]}"
        own_slot = zelda.connected["slot"]
        by_id = {identifier: name for name, identifier in ITEM_IDS.items()}
        by_location = {identifier: name for name, identifier in LOCATION_IDS.items()}
        roster = {}
        for location, (item, owner) in zelda.scouts.items():
            metadata = zelda.connected["slot_info"][str(owner)]
            local = owner == own_slot
            roster[by_location[location]] = dict(item=by_id[item] if local else "Foreign item #" + str(item),
                item_id=item, owner=owner, player=metadata["name"], local=local, game=metadata["game"])
        assert set(roster) == set(data["checks"])
        own = next(name for name, reward in roster.items() if reward["local"] and ITEM_DATA[reward["item"]]["mode"] == "tiers")
        foreign = next(name for name, reward in roster.items() if not reward["local"])
        remote_location, (remote_item, _) = next((location, reward) for location, reward in ami.scouts.items() if reward[1] == own_slot)
        mod = build_registry(root, roster)
        profile = root / "profile"
        profile.mkdir()
        config = dict(server=uri, protected="", baseline=0)
        with patch.object(native_setup, "detect_language", return_value="en"):
            native_setup.save_session(profile, config, data, roster)

        async def boot(expected=None):
            instance = Worker(profile, data["token"], library, native_log)
            workers.append(instance)
            await instance.start()
            return instance, await instance.ready(expected)

        instance, initial = await boot()
        baseline_native = list(initial["history"])
        baseline_ami = list(ami.history)
        flags = initial["flags"]
        flow = (mod / restoration.FLOW_PATH).read_bytes()
        earned = SaveRun(flow)
        records = {record["id"]: record for record in restoration.restoration_records(roster)}

        def states(model):
            values = {murmur3(key): value for key, value in model.values.items()}
            return [ord("1") if values.get(flag) else ord("0") for flag in flags]

        def opened(model):
            return [flag for flag, state in zip(flags, states(model)) if state == ord("1")]

        assert (await instance.request(states=states(earned)))["restore"] == 0, "Old profile enabled unregistered recovery"
        earned.restore(own).restore(foreign)  # Explicit model of the first native physical gains.
        await instance.request(opened=opened(earned))
        expected_ami = baseline_ami + [(roster[foreign]["item_id"], LOCATION_IDS[foreign], own_slot)]
        await ami.wait(lambda: ami.history == expected_ami)
        await instance.ready(baseline_native)
        await ami.send({"cmd": "LocationChecks", "locations": [remote_location]})
        expected_native = baseline_native + [remote_item]
        await instance.ready(expected_native)
        await instance.request(applied=len(expected_native) - 1)
        journal_path = profile / "native-checks.json"
        journal = json.loads(journal_path.read_bytes())
        assert {LOCATION_IDS[own], LOCATION_IDS[foreign]} <= set(journal["Locations"])
        await instance.close()
        # Simulate a lost local journal: authenticated server checks must rebuild
        # it before restoration can run. Keep its first committed copy as proof.
        journal_path.rename(profile / "native-checks.before-reconnect.json")
        with patch.object(restoration, "Codec", IdentityCodec), patch.object(native_setup, "detect_language", return_value="en"):
            native_setup.save_session(profile, config, data, roster, prepared=mod)
        checkpoint_packets = [location for packet in packets if packet["cmd"] == "LocationChecks" for location in packet["locations"]]
        assert sorted(checkpoint_packets) == sorted([LOCATION_IDS[own], LOCATION_IDS[foreign]])
        modeled_restores = []
        for restart in range(2):
            instance, snapshot = await boot(expected_native)
            assert snapshot["cursor_hash"] == initial["cursor_hash"]
            assert {LOCATION_IDS[own], LOCATION_IDS[foreign]} <= set(json.loads(journal_path.read_bytes())["Locations"])
            older = SaveRun(flow)  # Independent older save: no flags/effects committed.
            assert (await instance.request(states=states(older)[:-1]))["restore"] == 0
            invalid = states(older)
            invalid[-1] = 255
            assert (await instance.request(states=invalid))["restore"] == 0
            recovered = []
            for _ in range(4):
                reply = await instance.request(states=states(older), opened=opened(older))
                location = reply["restore"]
                if not location:
                    break
                assert location in {LOCATION_IDS[own], LOCATION_IDS[foreign]}
                record = records[location]
                before_inventory = older.inventory.copy()
                older.restore(record["name"])
                assert older.values[restoration.RESULT] == location
                assert all(older.values[flag] for flag in record["flags"])
                if not record["local"]:
                    assert older.inventory == before_inventory, "Foreign recovery granted a Zelda item"
                recovered.append(location)
            assert sorted(recovered) == sorted([LOCATION_IDS[own], LOCATION_IDS[foreign]])
            assert (await instance.request(states=states(older), opened=opened(older)))["restore"] == 0
            assert (await instance.request())["history"] == expected_native, "Rollback or local recovery shifted remote indices"
            modeled_restores.append(recovered)
            # Let the actual native send tick run; a restored flag must not
            # produce another LocationChecks packet or another friend's item.
            await asyncio.sleep(0.65)
            await ami.fence()
            assert ami.history == expected_ami
            await instance.close()
        after_packets = [location for packet in packets if packet["cmd"] == "LocationChecks" for location in packet["locations"]]
        assert after_packets == checkpoint_packets, "Rollback re-emitted an already confirmed location"
        assert all(packet["items_handling"] == 5 for packet in packets if packet["cmd"] == "Connect")
        assert all(compression)
        return dict(result="PASS", dll_sha256=hashlib.sha256(library.read_bytes()).hexdigest(), checks=len(data["checks"]),
            workers=len(workers), own_location=LOCATION_IDS[own], foreign_location=LOCATION_IDS[foreign],
            own_item=roster[own]["item"],
            location_checks=after_packets, restorations=modeled_restores, remote_history=expected_native,
            actual_local_server=True, actual_native_dll=True, native_compression_negotiated=True,
            old_registry_disabled=True, server_rebuilt_journal=True, subsequent_restart_kept_journal=True,
            missing_or_unknown_flags_rejected=True, foreign_reward_not_resent=True, remote_indices_replayable=True,
            rewound_remote_index=0, next_at_rewound_index=expected_native[0],
            inventory_effects="generated event-graph model only", game_started=False, public_room_contacted=False)
    finally:
        for instance in reversed(workers):
            await instance.close()
        for peer in reversed(peers):
            await peer.close()
        if proxy:
            proxy.close()
            await proxy.wait_closed()
        if server.poll() is None:
            server.terminate()
            await asyncio.to_thread(server.wait, 10)
        native_log.close()
        log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--room", type=Path, default=ROOT / "tests/fixtures/complet-v2")
    default_library = ROOT / ("build/archipelago.so" if sys.platform.startswith("linux") else "dist/native/archipelago.dll")
    parser.add_argument("--library", type=Path, default=default_library)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--work", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ootrr-native-rollback-") as temporary:
        if args.work:
            args.work.mkdir(parents=True, exist_ok=True)
            work = Path(tempfile.mkdtemp(prefix="run-", dir=args.work)).resolve()
        else:
            work = Path(temporary)
        copied = work / ("archipelago-test" + args.library.suffix)
        shutil.copyfile(args.library, copied)
        assert hashlib.sha256(copied.read_bytes()).digest() == hashlib.sha256(args.library.read_bytes()).digest()
        result = asyncio.run(exercise(work, args.room.resolve(), copied))
    text = json.dumps(result, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--worker":
        worker(Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]))
    else:
        main()
