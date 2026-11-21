"""Exercise the desktop transport with the real DLL and isolated AP server.

Reuse the menu's reconnect/offline-item/DeathLink scenarios through the local
control service. Gameplay callbacks remain test models; no game is modified.
"""
import asyncio
import json
import os
from pathlib import Path
import tempfile

import test_connection_menu as menu
from ootrr_triforce.connection_control import Controller


class CompanionWorker(menu.NativeWorker):
    async def start(self):
        snapshot = await super().start()
        self.controller = Controller(self.root)

        async def available():
            info = await asyncio.to_thread(self.controller.info)
            return info if info.get("live") else None

        info = await menu.until(available, "desktop control service startup")
        assert info["slot"] == snapshot["snapshot"]["slot"]
        assert info["room"] == snapshot["snapshot"]["room"]
        assert info["state"] == snapshot["snapshot"]["state"]
        # An existing in-game control command remains visible in the companion.
        assert (await super().request(action="disconnect"))["result"] == 1
        assert (await asyncio.to_thread(self.controller.info))["state"] == "disconnected"
        return snapshot

    async def request(self, **packet):
        action = packet.pop("action", None)
        if action == "connect":
            result = await asyncio.to_thread(
                self.controller.apply, packet.pop("server"), packet.pop("password", ""),
                packet.pop("mode", 0), bool(packet.pop("automatic", 0)))
        elif action == "disconnect":
            result = await asyncio.to_thread(self.controller.disconnect)
        else:
            assert action is None
            return await super().request(**packet)
        snapshot = await super().request(**packet)
        snapshot["result"] = result["result"]
        if result["result"] < 0:
            snapshot["control_error"] = result["error_code"]
        return snapshot


def main():
    menu.NativeWorker = CompanionWorker
    root = Path(__file__).resolve().parents[1]
    library = root / ("dist/native/archipelago.dll" if os.name == "nt" else "build/archipelago.so")
    with tempfile.TemporaryDirectory(prefix="ootrr-connection-companion-") as temporary:
        result = asyncio.run(menu.exercise(Path(temporary), root / "tests/fixtures/complet-v2", library))
    result["scope"] = "desktop controller, real native DLL, isolated local AP server"
    result["shared_in_game_client"] = True
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
