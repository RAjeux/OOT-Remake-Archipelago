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


CHANGED = {"kokiri_shop_checks": True, "open_forest": "open", "open_kakariko": "open",
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
            if name != "kokiri_shop_checks":
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


if __name__ == "__main__":
    unittest.main()
