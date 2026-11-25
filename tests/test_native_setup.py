"""Native DLL updates must invalidate the generated mod cache and compiled game."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.native_setup import BUILD_MARK, MENU_BUILD_MARK, MENU_FILES, compiled_game, runtime_cache_name
from ootrr_triforce import native_setup


class CompiledGameTests(unittest.TestCase):
    def test_current_bundle_is_required(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            romfs = root / "game/romfs"
            romfs.mkdir(parents=True)
            native = root / "release/native"
            native.mkdir(parents=True)
            dll = native / "archipelago.dll"
            executable = romfs.parent / "Triforce.exe"
            renderer = romfs.parent / "triforce_vk.dll"
            expected = hashlib.sha256(b"current DLL").digest()
            old = hashlib.sha256(b"previous DLL").digest()
            with patch.object(sys, "argv", [str(root / "release/Client-OOT-Remake.pyz")]):
                executable.write_bytes(BUILD_MARK + expected)
                self.assertFalse(compiled_game(romfs), "A missing bundle cannot certify a build.")
                dll.write_bytes(b"current DLL")
                for binary in (b"", BUILD_MARK, BUILD_MARK + old, expected):
                    executable.write_bytes(binary)
                    self.assertFalse(compiled_game(romfs))
                executable.write_bytes(BUILD_MARK + b"\0" * 32 + expected)
                self.assertFalse(compiled_game(romfs), "The Options menu renderer must be rebuilt too.")
                renderer.write_bytes(b"old renderer")
                self.assertFalse(compiled_game(romfs))
                renderer.write_bytes(MENU_BUILD_MARK)
                self.assertTrue(compiled_game(romfs))
                tools = root / "tools"
                host = tools / "host"
                host.mkdir(parents=True)
                menu = tools / "gpu/vk"
                menu.mkdir(parents=True)
                for name in ("ootrr_archipelago.inc", "ootrr_ap_items.inc", "ootrr_ap_digest.h"):
                    helper = host / name
                    helper.write_bytes(b"installed host adapter")
                    os.utime(helper, ns=(1_000_000_000, 1_000_000_000))
                for name in (*MENU_FILES, "vk_menu.cpp"):
                    helper = menu / name
                    helper.write_bytes(b"installed menu adapter")
                    os.utime(helper, ns=(1_000_000_000, 1_000_000_000))
                os.utime(executable, ns=(2_000_000_000, 2_000_000_000))
                os.utime(renderer, ns=(2_000_000_000, 2_000_000_000))
                self.assertTrue(compiled_game(romfs,tools))
                os.utime(menu / MENU_FILES[0], ns=(3_000_000_000, 3_000_000_000))
                self.assertFalse(compiled_game(romfs,tools), "A menu update requires a rebuilt renderer.")
                os.utime(renderer, ns=(4_000_000_000, 4_000_000_000))
                self.assertTrue(compiled_game(romfs,tools))
                os.utime(host / "ootrr_archipelago.inc", ns=(3_000_000_000, 3_000_000_000))
                self.assertFalse(compiled_game(romfs,tools), "An adapter update requires recompilation too.")
                dll.write_bytes(b"another release")
                self.assertFalse(compiled_game(romfs), "A replacement DLL requires recompilation.")

    def test_native_cache_changes_with_dll_and_baseline(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            native = root / "release/native"
            native.mkdir(parents=True)
            dll = native / "archipelago.dll"
            cache = root / "cache"
            previous = cache / "jeu-016-mod-0/mods/Archipelago/archipelago.dll"
            previous.parent.mkdir(parents=True)
            previous.write_bytes(b"legacy DLL")
            with patch.object(sys, "argv", [str(root / "release/Client-OOT-Remake.pyz")]):
                dll.write_bytes(b"current DLL")
                first = cache / runtime_cache_name(0)
                first.mkdir()
                (first / "archipelago.dll").write_bytes(dll.read_bytes())
                self.assertEqual(cache / runtime_cache_name(0), first)
                self.assertNotEqual(cache / runtime_cache_name(1), first)
                dll.write_bytes(b"updated DLL")
                updated = cache / runtime_cache_name(0)
                self.assertNotEqual(updated, first)
                self.assertFalse(updated.exists(), "The updated DLL must not reuse the old mod.")
                self.assertEqual(previous.read_bytes(), b"legacy DLL")
                self.assertEqual((first / "archipelago.dll").read_bytes(), b"current DLL")
                from importlib import resources
                original_resources = resources.files
                changed_sources = root / "changed-sources"
                changed_sources.mkdir()
                for source in original_resources("ootrr_triforce").iterdir():
                    if source.is_file() and source.name.endswith((".py", ".cjs", ".wasm", ".json")):
                        (changed_sources / source.name).write_bytes(source.read_bytes())
                with patch.object(resources,"files",return_value=changed_sources):
                    baseline = cache / runtime_cache_name(0)
                    self.assertEqual(baseline, updated, "An exact source copy must keep the cache key.")
                    receipt = changed_sources / "receipt_events.py"
                    original_receipt = receipt.read_bytes()
                    receipt.write_bytes(original_receipt + b"\n# receipt update\n")
                    self.assertNotEqual(cache / runtime_cache_name(0), baseline,
                                        "Receipt updates must also invalidate the generated native mod.")
                    receipt.write_bytes(original_receipt)
                    catalogue = changed_sources / "network_sources.json"
                    catalogue.write_bytes(catalogue.read_bytes() + b"\n")
                    self.assertNotEqual(cache / runtime_cache_name(0), baseline,
                                        "The source catalogue must participate in mod cache invalidation.")


class TradeReplaySessionTests(unittest.TestCase):
    def inputs(self):
        from ootrr_triforce.catalog import GAME, ITEM_IDS, TRADE_CHECKS
        from test_trade_receipts import TOKEN
        data = dict(room="room", slot="Zelda", token=TOKEN, player=2, game=GAME,
                    reward_mode="all_locations", local_items=True, adult_trade_shuffle=True,
                    checks=list(TRADE_CHECKS))
        roster = {name:dict(item="Rupees (5)", item_id=ITEM_IDS["Rupees (5)"], owner=2,
                           player="Zelda", local=True, game=GAME) for name in data["checks"]}
        config = dict(server="ws://127.0.0.1:38281", protected="", baseline=0)
        return data, roster, config

    def test_validated_trade_capability_is_exported_only_for_full_recovery_rooms(self):
        from ootrr_triforce.catalog import LOCATION_IDS
        from ootrr_triforce import trade_receipts
        from test_trade_receipts import PreparedTradeReplayTests
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); prepared=PreparedTradeReplayTests().finalize(root / "resources")
            (root / "profile").mkdir()
            data,roster,config=self.inputs()
            recovery=[LOCATION_IDS[name] for name in data["checks"]]
            with patch("ootrr_triforce.restoration.prepared_locations", return_value=recovery), patch.object(native_setup,"detect_language",return_value="en"):
                native_setup.save_session(root / "profile",config,data,roster,prepared=prepared)
                saved=root / "profile/native-session.json"
                session=json.loads(saved.read_bytes())
                self.assertEqual(session["TradeReplayReceipts"], {str(key):value for key,value in trade_receipts.replay_receipts().items()})
                before=saved.read_bytes()
                for mode in (dict(local_items=False),dict(reward_mode="legacy_gear")):
                    with self.subTest(mode=mode), self.assertRaises(ValueError):
                        native_setup.save_session(root / "profile",config,data|mode,roster,prepared=prepared)
                    self.assertEqual(saved.read_bytes(),before)
                with patch("ootrr_triforce.restoration.prepared_locations",return_value=recovery[:-1]), self.assertRaises(ValueError):
                    native_setup.save_session(root / "profile",config,data,roster,prepared=prepared)
                self.assertEqual(saved.read_bytes(),before)

    def test_existing_rooms_without_prepared_capability_keep_the_original_protocol(self):
        from ootrr_triforce.catalog import LOCATION_IDS
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); prepared=root / "empty-romfs"; prepared.mkdir()
            (root / "profile").mkdir()
            data,roster,config=self.inputs()
            recovery=[LOCATION_IDS[name] for name in data["checks"]]
            with patch("ootrr_triforce.restoration.prepared_locations",return_value=recovery), patch.object(native_setup,"detect_language",return_value="en"):
                native_setup.save_session(root / "profile",config,data,roster,prepared=prepared)
                self.assertNotIn("TradeReplayReceipts",json.loads((root / "profile/native-session.json").read_bytes()))
                native_setup.save_session(root / "profile",config,data|dict(adult_trade_shuffle=False),roster,prepared=prepared)
                self.assertNotIn("TradeReplayReceipts",json.loads((root / "profile/native-session.json").read_bytes()))


if __name__ == "__main__":
    unittest.main()
