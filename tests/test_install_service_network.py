"""Scout two copied regression rooms using a real, isolated AP server."""
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce import install_service, player
from support import server_command


@unittest.skipUnless(os.environ.get("AP_SERVER") or os.environ.get("AP_SOURCE"), "requires an isolated Archipelago server")
class NativeInstallerScoutTests(unittest.TestCase):
    async def scenario(self, name):
        from websockets.legacy.client import connect
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with ZipFile(ROOT / "tests/fixtures" / name / "salle-test.zip") as archive:
                for member in archive.namelist():
                    if member.endswith((".archipelago", ".apootrr")):
                        (root / Path(member).name).write_bytes(archive.read(member))
            data = player.read_manifest(next(root.glob("*.apootrr")))
            with socket.socket() as socket_:
                socket_.bind(("127.0.0.1", 0))
                port = socket_.getsockname()[1]
            uri = f"ws://127.0.0.1:{port}"
            log_path = root / "server.log"
            with log_path.open("wb") as log:
                process = subprocess.Popen([*server_command(), str(next(root.glob("*.archipelago"))),
                                            "--host", "127.0.0.1", "--port", str(port), "--disable_save"],
                                           stdout=log, stderr=log, stdin=subprocess.PIPE)
            try:
                for _ in range(200):
                    if "server listening on" in log_path.read_text(errors="replace"):
                        break
                    if process.poll() is not None:
                        self.fail("The isolated fixture server stopped before setup.")
                    await asyncio.sleep(.1)
                else:
                    self.fail("The isolated fixture server did not become ready.")
                roster = await install_service.fetch_roster(data, uri, "", timeout=20)
                self.assertTrue(roster)
                if data.get("local_items"):
                    self.assertEqual(set(roster), set(data["checks"]))
                    self.assertTrue(any(row["local"] for row in roster.values()))
                    self.assertTrue(any(not row["local"] for row in roster.values()))
                else:
                    self.assertTrue(all(owner != data["slot"] for _, owner in roster.values()))
                # A second read-only connection verifies setup never checked a
                # location while retrieving the full placement roster.
                async with connect(uri, open_timeout=10) as ws:
                    while True:
                        messages = json.loads(await asyncio.wait_for(ws.recv(), 10))
                        for message in messages:
                            if message["cmd"] == "RoomInfo":
                                await ws.send(json.dumps([dict(cmd="Connect", name=data["slot"], game=data["game"],
                                                               uuid="fixture-read-only-check", password=None,
                                                               items_handling=0, tags=["AP"], slot_data=True,
                                                               version=dict(major=0, minor=6, build=7, **{"class": "Version"}))]))
                            elif message["cmd"] == "Connected":
                                self.assertEqual(message["checked_locations"], [])
                                return
            finally:
                if process.poll() is None:
                    process.stdin.write(b"exit\n")
                    process.stdin.flush()
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        process.wait(timeout=5)
                process.stdin.close()

    def test_legacy_foreign_chests_only(self):
        asyncio.run(self.scenario("neutre"))

    def test_full_local_and_remote_rewards(self):
        asyncio.run(self.scenario("complet-v2"))


if __name__ == "__main__":
    unittest.main()
