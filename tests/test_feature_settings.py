"""New-room options are explicit and cannot leak into historical seed strings."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))

from ootrr_triforce.feature_settings import (COLOR_PARTS, FEATURE_KEYS, LEGACY_DIFFICULTY_KEYS,
                                           LEGACY_DIFFICULTY_DEFAULTS, feature_config, read_features)
from ootrr_triforce.settings import SPEC_BY_ID, default_options, engine_settings, validate_options, yaml_options
from ootrr_triforce.settings_labels import active_reason, normalize_inactive


class FeatureSettingsTests(unittest.TestCase):
    def test_absent_features_remain_distinct_from_new_room_with_default_features(self):
        self.assertIsNone(read_features(None))
        self.assertEqual(feature_config(default_options()), {"schema": 1, "settings": {}})
        native = engine_settings({})
        self.assertFalse((FEATURE_KEYS - LEGACY_DIFFICULTY_KEYS).intersection(native))
        self.assertEqual(engine_settings({"free_scarecrow": True}), native)

    def test_explicit_new_room_roundtrips_without_mutating_options(self):
        values = validate_options({"free_scarecrow": True, "nocturne_trigger": "classic",
                                   "dungeon_key_tracker": True})
        envelope = feature_config(values)
        self.assertEqual(read_features(json.loads(json.dumps(envelope))), envelope)
        envelope["settings"]["free_scarecrow"] = False
        self.assertTrue(values["free_scarecrow"])
        self.assertEqual(feature_config(values)["settings"]["nocturne_trigger"], "classic")

    def test_untrusted_features_are_rejected_before_resource_edits(self):
        for payload in (True, {}, {"schema": True, "settings": {}}, {"schema": 2, "settings": {}},
                        {"schema": 1, "settings": [], "extra": True},
                        {"schema": 1, "settings": {"nocturne_trigger": "open"}},
                        {"schema": 1, "settings": {"free_scarecrow": 1}},
                        {"schema": 1, "settings": {"bridge_medallions": True}},
                        {"schema": 1, "settings": {"bridge_medallions": 7}},
                        {"schema": 1, "settings": {"unknown": False}}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                read_features(payload)

    def test_medallion_counts_stay_separate_from_combined_reward_goals(self):
        values = validate_options({"bridge": "medallions", "bridge_medallions": 4,
                                   "shuffle_ganon_bosskey": "lacs_medallions",
                                   "lacs_medallions": 5, "shuffle_rewards": "supported"})
        envelope = read_features(feature_config(values))
        self.assertEqual(envelope["settings"]["bridge_medallions"], 4)
        self.assertEqual(envelope["settings"]["lacs_medallions"], 5)
        native = engine_settings(values)
        self.assertEqual(native["bridge"], "dungeons")
        self.assertEqual(native["shuffle_ganon_bosskey"], "lacs_dungeons")
        with self.assertRaises(ValueError):
            validate_options(dict(values, bridge_rewards=4))

    def test_inactive_counts_and_daytime_skull_requirement_reset_without_affecting_active_options(self):
        values = default_options()
        values.update(bridge_medallions=3, lacs_medallions=2, skulls_by_day=True,
                      night_skulls_suns_song=True, fishing_any_fish=True)
        effective = validate_options(normalize_inactive(values))
        self.assertEqual(effective["bridge_medallions"], 6)
        self.assertEqual(effective["lacs_medallions"], 6)
        self.assertFalse(effective["night_skulls_suns_song"])
        self.assertTrue(effective["fishing_any_fish"])
        self.assertTrue(values["night_skulls_suns_song"])
        self.assertTrue(active_reason("bridge_medallions", values, "fr"))

    def test_bilingual_yaml_explains_song_trigger_semantics(self):
        for language, phrase in (("en", "holding their three Medallions"),
                                 ("fr", "posséder leurs trois médaillons")):
            rendered = yaml_options(language=language)
            self.assertIn(phrase, rendered)
            self.assertIn('  nocturne_trigger: "vanilla"', rendered)
            self.assertIn('  dungeon_key_tracker: false', rendered)

    def test_colour_and_plan_mappings_use_known_ids_and_survive_json_export(self):
        values = validate_options({"cosmetic_color_mode": "custom",
                                   "cosmetic_colors": {"kokiri": "#abcdef", "navi": "random"},
                                   "item_plando": {"KF Midos Top Left Chest": "Progressive Hookshot"}})
        self.assertEqual(values["cosmetic_colors"]["kokiri"], "#ABCDEF")
        envelope = feature_config(values)
        self.assertEqual(read_features(json.loads(json.dumps(envelope))), envelope)
        self.assertFalse((FEATURE_KEYS - LEGACY_DIFFICULTY_KEYS).intersection(engine_settings(values)))
        self.assertEqual(len(COLOR_PARTS), 27)
        for changed in ({"cosmetic_colors": {"kokiri": "blue"}},
                        {"cosmetic_colors": {"../../Game": "#ABCDEF"}},
                        {"cosmetic_colors": {"kokiri": {"rgb": [1, 2, 3]}}},
                        {"item_plando": {"KF Midos Top Left Chest": "Not An Item"}},
                        {"item_plando": {"Not A Check": "Progressive Hookshot"}}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                validate_options(changed)

    def test_inactive_custom_colours_reset_without_erasing_the_draft(self):
        values = default_options()
        values.update(cosmetic_color_mode="random", cosmetic_colors={"kokiri": "#FFFFFF"})
        effective = validate_options(normalize_inactive(values))
        self.assertEqual(effective["cosmetic_colors"], {})
        self.assertEqual(values["cosmetic_colors"], {"kokiri": "#FFFFFF"})

    def test_colour_picker_ids_match_the_compiled_engine_catalogue(self):
        import re
        source = (ROOT / "moteur/ootrr-ap/randomizer/cosmetics/src/colors.rs").read_text(encoding="utf-8")
        declaration = source.split("pub const ITEMS:", 1)[1].split("pub const SHADES:", 1)[0]
        native_ids = set(re.findall(r'(?:part\(\s*|\bid:\s*)"([a-z_]+)"', declaration))
        self.assertEqual(set(COLOR_PARTS), native_ids)

    def test_modern_difficulty_never_applies_scaling_twice_through_old_builder(self):
        values = validate_options({"enemy_health": 200, "enemy_damage": 150,
                                   "enemy_backup": True, "no_ammo_drops": True,
                                   "damage_taken": "quadruple"})
        native = engine_settings(values)
        for name, baseline in LEGACY_DIFFICULTY_DEFAULTS.items():
            self.assertEqual(native[name], baseline, name)
        features = read_features(feature_config(values))["settings"]
        self.assertEqual(features["enemy_health"], 200)
        self.assertEqual(features["enemy_damage"], 150)
        self.assertIs(features["enemy_backup"], True)
        self.assertIs(features["no_ammo_drops"], True)
        self.assertEqual(features["damage_taken"], "quadruple")
        with self.assertRaises(ValueError):
            read_features({"schema": 1, "settings": {"enemy_health": 101}})

    def test_known_broken_upstream_switches_are_absent_and_rejected_at_both_boundaries(self):
        for name, selected, baseline in (("volvagia_roams", True, False),
                                         ("enemy_sizes", "mild", "off"),
                                         ("enemy_sizes_health", True, False)):
            with self.subTest(name=name):
                self.assertNotIn(name, SPEC_BY_ID)
                self.assertNotIn("  " + name + ":", yaml_options())
                with self.assertRaisesRegex(ValueError, "Unavailable setting"):
                    validate_options({name: selected})
                with self.assertRaisesRegex(ValueError, "Unavailable setting"):
                    read_features({"schema": 1, "settings": {name: selected}})
                self.assertNotIn(name, validate_options({name: baseline}))
                self.assertEqual(read_features({"schema": 1, "settings": {name: baseline}}),
                                 {"schema": 1, "settings": {}})


if __name__ == "__main__":
    unittest.main()
