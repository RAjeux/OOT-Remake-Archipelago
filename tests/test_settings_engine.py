"""Prove that typed AP settings reach the actual vendored OOTRR WASM."""
import json
import os
from pathlib import Path
import shutil
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.catalog import DEFAULT_SETTINGS, SHOP_CHECKS
from ootrr_triforce.engine import run_engine
from ootrr_triforce.settings import FIXED_SETTINGS, engine_settings


CHANGED = {"shuffle_shops": "shuffle", "open_forest": "open", "open_kakariko": "open",
           "door_of_time_condition": "open", "door_of_time_escape": "moat",
           "starting_hearts": 6, "starting_items": ["deku_shield", "big_bomb_bag"],
           "starting_songs": ["eponas_song"], "faster_blocks": True, "trials": 3, "enemy_health": 125}


@unittest.skipUnless(os.environ.get("OOTRR_NODE") or shutil.which("node"), "Node.js needed for real WASM checks")
class NativeSettingsTests(unittest.TestCase):
    def inspect(self, settings):
        return json.loads(run_engine("settings", {"settings": settings}))

    def assert_applied(self, settings):
        expected = engine_settings(CHANGED)
        for name in CHANGED:
            self.assertEqual(settings[name], expected[name], name)
        self.assertEqual(settings["shuffle_shops"], "shuffle")
        for name, value in FIXED_SETTINGS.items():
            self.assertEqual(settings[name], value, name)

    def test_json_options_and_canonical_string_have_identical_native_values(self):
        result = self.inspect(engine_settings(CHANGED))
        self.assert_applied(result["settings"])
        restored = self.inspect(result["settings_string"])
        self.assertEqual(restored, result)

    def test_old_strings_remain_readable_and_unknown_or_invalid_native_fields_fail(self):
        result = self.inspect(DEFAULT_SETTINGS)
        self.assertTrue(result["settings_string"].startswith("OOTRR1-"))
        for settings in ({"unknown_setting": True}, {"starting_hearts": 0},
                         {"shuffle_smallkeys": "not_a_choice"}):
            with self.subTest(settings=settings), self.assertRaises(RuntimeError):
                self.inspect(settings)

    def test_generated_seed_records_the_requested_native_settings(self):
        generated = json.loads(run_engine("generate", {"settings": engine_settings(CHANGED),
                                                        "seed": "AP-YAML-DIRECT-VALIDATION"}))
        self.assert_applied(self.inspect(generated["seed_file"]["settings"])["settings"])
        self.assertTrue(generated["seed_file"]["placements"])
        reached = {name for wave in generated["waves"] for name in wave}
        self.assertIn("Ganon", reached)
        self.assertTrue(set(SHOP_CHECKS).issubset(reached))
        self.assertTrue(set(SHOP_CHECKS).issubset(generated["seed_file"]["shops"]))

    def test_broad_native_local_profile_preserves_ap_projection_and_supported_items(self):
        from ootrr_triforce.catalog import CHESTS, ITEM_IDS, AP_SKULL_CHECKS
        changes = dict(shuffle_rewards="supported", shuffle_rewards_extra=True,
                       shuffle_songs="anywhere", shuffle_dungeon_rewards="anywhere",
                       shuffle_trade_checks=True, shuffle_cows=True, shuffle_frog_songs=True,
                       shuffle_frog_bug_heart=True, shuffle_potion_shop=True, shuffle_ocarinas=True,
                       shuffle_kokiri_sword=True, shuffle_scrubs_a=True, shuffle_scrubs_b=True,
                       shuffle_merchants="all", plant_beans=True, shuffle_boss_hearts=True,
                       shuffle_treasure_reward=True, shuffle_freestanding_items="all",
                       shuffle_pots="all", shuffle_crates="all", shuffle_rocks="all",
                       shuffle_grass="all", shuffle_beehives=True, shuffle_entrances="dungeons",
                       shuffle_shops="deals_4", shopsanity_prices="giant",
                       shuffle_skulltulas="matched", shuffle_ganon_bosskey="lacs_dungeons",
                       lacs_rewards=3, fairy_prices="cheap", scrub_prices="fixed",
                       scrub_price_fixed=10, scrub_hint_text=True, merchant_prices="cheap")
        generated = json.loads(run_engine("generate", {"settings": engine_settings(changes),
                                                        "seed": "AP-HYBRID-SKULLS-VALIDATION"}))
        seed = generated["seed_file"]
        reached = {name for wave in generated["waves"] for name in wave}
        self.assertIn("Ganon", reached)
        network = {name: item for name, item in seed["placements"].items()
                   if name in CHESTS or name in AP_SKULL_CHECKS}
        self.assertTrue(network)
        self.assertTrue(set(network) <= reached)
        self.assertTrue(set(network.values()) <= ITEM_IDS.keys())
        self.assertTrue(any(name in AP_SKULL_CHECKS for name in network))
        self.assertTrue(any(name not in network and name not in SHOP_CHECKS for name in seed["placements"]))
        self.assertTrue(set(SHOP_CHECKS) <= reached)
        self.assertEqual(self.inspect(seed["settings"])["settings"]["shuffle_skulltulas"], "matched")


if __name__ == "__main__":
    unittest.main()
