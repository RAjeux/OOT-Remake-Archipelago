"""Publish text localization transactionally, including old base-cache reuse."""
import asyncio
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce import ap_shops, install_mod, medallions, player, restoration, shop_tracking
from ootrr_triforce.catalog import LEGACY_SHOP_CHECKS


def put(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


class LocalizationPipelineTests(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory)
        game = root / "game/romfs"
        cache = root / "cache"
        base = cache / "mods/Archipelago/romfs"
        put(game / "Mals/EUfr.Product.110.sarc.zs", b"French native text")
        put(game / "Mals/USen.Product.110.sarc.zs", b"English native text")
        put(base / "Mals/EUfr.Product.110.sarc.zs", b"OOTRR French labels")
        put(base / "Event/reward-flow", b"native inventory recipe")
        settings = {"romfs": str(game), "reward_mode": "all_locations", "local_items": True,
                    "kokiri_shop_checks": True, "_seed_settings": "OOTRR1-canonical-seed-settings"}
        return root, game, cache, base, settings

    def test_localization_runs_once_after_receipts_and_shops_and_invalidates_old_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root, game, cache, base, settings = self.fixture(directory)
            roster = {"synthetic chest": ("Bow", "Ami")}
            effective = sorted((p.relative_to(cache / "mods").as_posix(), p.stat().st_size, p.stat().st_mtime_ns)
                               for p in (cache / "mods").rglob("*") if p.is_file())
            old_payload = json.dumps([4, True, True, True, {}, roster, effective], ensure_ascii=False, sort_keys=True)
            old = cache / "v14" / hashlib.sha256(old_payload.encode()).hexdigest()[:16] / "mods/Archipelago/romfs"
            put(old / "old-cache-marker", b"previous published cache")
            actions = []

            def patch_rewards(_game, mod, *_args, **_kwargs):
                actions.append("rewards")
                put(mod / "Event/reward-flow", b"AP receipt recipe")

            def patch_shops(_game, mod, *_args):
                actions.append("shops")
                put(mod / "Event/shop-flow", b"AP purchase recipe")

            def patch_restoration(_game, mod, *_args, **kwargs):
                self.assertEqual(kwargs["settings"], settings)
                actions.append("restoration")
                put(mod / "Event/restore-flow", b"AP restoration recipe")

            def patch_tracking(_game, mod, *_args):
                actions.append("tracking")
                put(mod / "Event/tracking-flow", b"AP quiet stock reconciliation")

            def localize(command, request, original, mod):
                actions.append(command)
                self.assertEqual(command, "localize")
                self.assertEqual(request["settings"], settings["_seed_settings"])
                self.assertEqual(request["messages"], ["Mals/EUfr.Product.110.sarc.zs", "Mals/USen.Product.110.sarc.zs"])
                self.assertEqual(original, game)
                self.assertEqual((mod / "Event/reward-flow").read_bytes(), b"AP receipt recipe")
                self.assertEqual((mod / "Event/shop-flow").read_bytes(), b"AP purchase recipe")
                self.assertEqual((mod / "Event/restore-flow").read_bytes(), b"AP restoration recipe")
                self.assertEqual((mod / "Event/tracking-flow").read_bytes(), b"AP quiet stock reconciliation")
                self.assertEqual((mod / "Mals/EUfr.Product.110.sarc.zs").read_bytes(), b"OOTRR French labels")
                put(mod / "Mals/USen.Product.110.sarc.zs", b"localized English labels")
                return ""

            with patch.object(medallions, "patch_mod", patch_rewards), patch.object(ap_shops, "prepare_shops", patch_shops), \
                    patch.object(restoration, "prepare_restoration", patch_restoration), \
                    patch.object(shop_tracking, "prepare_shop_tracking", patch_tracking), \
                    patch.object(medallions, "run_engine", localize), contextlib.redirect_stdout(io.StringIO()):
                result = medallions.prepare(cache, settings, roster, {})
                self.assertEqual(medallions.prepare(cache, settings, roster, {}), result)
            self.assertEqual(actions, ["rewards", "shops", "restoration", "tracking", "localize"])
            self.assertNotEqual(result / "Archipelago/romfs", old)
            self.assertEqual((old / "old-cache-marker").read_bytes(), b"previous published cache")
            self.assertEqual((base / "Event/reward-flow").read_bytes(), b"native inventory recipe")
            self.assertFalse((base / "Mals/USen.Product.110.sarc.zs").exists())
            self.assertEqual((game / "Mals/USen.Product.110.sarc.zs").read_bytes(), b"English native text")

    def test_empty_roster_and_settings_change_are_supported_without_guessing_legacy_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, cache, base, settings = self.fixture(directory)
            with patch.object(medallions, "patch_mod") as rewards, patch.object(ap_shops, "prepare_shops") as shops, \
                    patch.object(medallions, "run_engine", return_value="") as engine, contextlib.redirect_stdout(io.StringIO()):
                first = medallions.prepare(cache, settings, {}, {})
                second = medallions.prepare(cache, {**settings, "_seed_settings": {"navi_return": "off"}}, {}, {})
                self.assertNotEqual(first, second)
                self.assertEqual(engine.call_count, 2)
                rewards.assert_not_called()
                shops.assert_not_called()
                legacy = {key: value for key, value in settings.items() if key != "_seed_settings"}
                self.assertEqual(medallions.prepare(cache, legacy, {}, {}), cache / "mods")
                self.assertEqual(engine.call_count, 2)

    def test_special_deal_mode_does_not_reuse_a_legacy_shop_visual_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, cache, _, settings = self.fixture(directory)
            roster = {name: ("Foreign reward", "Ami") for name in sorted(LEGACY_SHOP_CHECKS)}
            settings["shop_prices"] = {name: 10 for name in roster}
            new_settings = dict(settings, kokiri_shop_checks=False, shop_check_mode="special_deals",
                                shop_checks=sorted(roster))
            with patch.object(medallions, "patch_mod"), patch.object(ap_shops, "prepare_shops") as shops, \
                    patch.object(restoration, "prepare_restoration"), \
                    patch.object(medallions, "run_engine", return_value=""), contextlib.redirect_stdout(io.StringIO()):
                legacy = medallions.prepare(cache, settings, roster, {})
                selected = medallions.prepare(cache, new_settings, roster, {})
                cached = medallions.prepare(cache, new_settings, roster, {})
            self.assertNotEqual(legacy, selected)
            self.assertEqual(selected, cached)
            self.assertEqual(shops.call_count, 2)

    def test_failed_localization_never_publishes_or_changes_the_base(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, cache, base, settings = self.fixture(directory)
            def failed(_command, _request, _game, mod):
                put(mod / "Mals/EUfr.Product.110.sarc.zs", b"partial output")
                raise RuntimeError("localizer failed")
            with patch.object(medallions, "run_engine", failed), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, "localizer failed"):
                    medallions.prepare(cache, settings, {}, {})
            self.assertEqual((base / "Mals/EUfr.Product.110.sarc.zs").read_bytes(), b"OOTRR French labels")
            self.assertEqual(list((cache / "v14").iterdir()), [])

    def test_connected_preparation_uses_the_manifest_settings_and_leaves_config_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = {"player": 2, "checks": [], "moved": {}, "seed_file": {"settings": "canonical seed settings"}}
            session = player.Session(root, "auto", data)
            session.visual.roster = lambda: {}
            config = {"assets": root / "cache", "_seed_settings": "stale configuration settings",
                      "shops_always_open": True}
            source = root / "prepared/mods"
            async def run():
                await session.ready_mod(config)
                await session.visual.build_task
                self.assertTrue(await session.ready_mod(config))
            with patch.object(player, "prepare", return_value=source) as prepare:
                asyncio.run(run())
            self.assertEqual(prepare.call_count, 1)
            self.assertEqual(prepare.call_args.args[1]["_seed_settings"], "canonical seed settings")
            self.assertIs(prepare.call_args.args[1]["shops_always_open"], False)
            self.assertEqual(config["_seed_settings"], "stale configuration settings")
            self.assertEqual(player.preparation_settings(config, {"seed_file": {}}),
                             {"assets": root / "cache", "shops_always_open": False})

    def test_build_only_upgrades_the_same_room_after_preparing_localized_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = ROOT / "tests/fixtures/neutre/salle-test.zip"
            with ZipFile(archive) as source:
                name = next(name for name in source.namelist() if name.endswith(".apootrr"))
                manifest = root / "Zelda.apootrr"
                manifest.write_bytes(source.read(name))
            data = player.read_manifest(manifest)
            game, mods = root / "game/romfs", root / "port/mods"
            game.mkdir(parents=True)
            mods.mkdir(parents=True)
            tool = root / "ootrr.exe"
            tool.write_bytes(b"unused test executable")
            previous, localized = root / "old/mods", root / "localized/mods"
            put(previous / "Archipelago/romfs/text", b"old English-only OOTRR text")
            install_mod.install(previous, mods, data["token"])
            put(localized / "Archipelago/romfs/text", b"localized text")
            def build(cache, _settings, _data):
                put(cache / "mods/Archipelago/romfs/text", b"unlocalized base")
            argv = ["Client.pyz", str(manifest), "--build-only", "--mods", str(mods),
                    "--ootrr", str(tool), "--romfs", str(game)]
            with patch.object(sys, "argv", argv), patch.dict(os.environ, {"LOCALAPPDATA": str(root / "local")}, clear=True), \
                    patch.object(player, "build", build), patch.object(player, "prepare", return_value=localized) as prepare, \
                    contextlib.redirect_stdout(io.StringIO()):
                player.main()
            self.assertEqual(prepare.call_count, 1)
            self.assertEqual(prepare.call_args.args[1]["_seed_settings"], data["seed_file"]["settings"])
            self.assertEqual((mods / "Archipelago/romfs/text").read_bytes(), b"localized text")
            self.assertEqual(install_mod.marker(mods / "Archipelago")["room"], data["token"])
            self.assertEqual((previous / "Archipelago/romfs/text").read_bytes(), b"old English-only OOTRR text")


if __name__ == "__main__":
    unittest.main()
