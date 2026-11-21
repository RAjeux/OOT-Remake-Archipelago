"""Public YAML settings stay typed and inside the implemented AP coverage."""
import ast
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.settings import (AP_ONLY, FIXED_SETTINGS, OPTION_SPECS, SPEC_BY_ID,
                                     STARTING_ITEMS, STARTING_SONGS, default_options,
                                     engine_settings, validate_options, yaml_options)
from ootrr_triforce.catalog import GAME


class DirectSettingsTests(unittest.TestCase):
    def test_player_yaml_export_asks_only_name_quotes_it_and_never_overwrites(self):
        from ootrr_triforce.i18n import tr
        tree = ast.parse((ROOT / "client/ootrr_triforce/player.py").read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "export_yaml")
        name = 'Zelda "E": test'
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            original = folder / ("Player-" + re.sub(r"[^\w -]", "_", name) + ".yaml")
            original.write_bytes(b"previous player file\n")
            ask, choose = Mock(return_value=name), Mock(return_value=folder)
            namespace = dict(input=ask, choose=choose, GAME=GAME, json=json, re=re, yaml_options=yaml_options, tr=tr)
            exec(compile(ast.Module(body=[function], type_ignores=[]), "player.py", "exec"), namespace)
            with redirect_stdout(io.StringIO()):
                namespace["export_yaml"]()
                namespace["export_yaml"]()
            self.assertEqual(ask.call_count, 2)
            self.assertEqual(choose.call_count, 2)
            self.assertTrue(all(call.kwargs == {"folder": True} for call in choose.call_args_list))
            self.assertEqual(original.read_bytes(), b"previous player file\n")
            created = sorted(path for path in folder.glob("*.yaml") if path != original)
            self.assertEqual(len(created), 2)
            for path in created:
                text = path.read_text(encoding="utf-8")
                self.assertIn("name: " + json.dumps(name, ensure_ascii=False) + "\n", text)
                self.assertIn("game: " + json.dumps(GAME) + "\n", text)
                options = {key: json.loads(value) for key, value in
                           re.findall(r"^  ([a-z_]+): (.+)$", text, flags=re.M)}
                self.assertEqual(options, default_options())
                self.assertIs(options["death_link"], False)
                self.assertIs(options["kokiri_shop_checks"], False)
                self.assertNotIn("OOTRR1-", text)

    def test_only_covered_shuffles_are_public_and_native_rewards_stay_local(self):
        shuffles = {name for name in SPEC_BY_ID if name.startswith("shuffle_")}
        self.assertEqual(shuffles, {"shuffle_chests", "shuffle_smallkeys", "shuffle_bosskeys",
                                    "shuffle_ganon_bosskey", "shuffle_mapcompass"})
        native = engine_settings({})
        self.assertEqual(native["shuffle_dungeon_rewards"], "vanilla")
        for name in ("shuffle_boss_hearts", "shuffle_ocarinas", "shuffle_kokiri_sword", "shuffle_cows",
                     "shuffle_trade_checks", "shuffle_silver_rupees", "shuffle_beehives"):
            self.assertIs(native[name], False, name)
        for name in ("shuffle_rewards", "shuffle_pots", "shuffle_crates", "shuffle_freestanding_items",
                     "shuffle_skulltulas", "shuffle_songs", "shuffle_entrances"):
            self.assertEqual(native[name], "off", name)
        self.assertIs(native["bombchus_in_logic"], False)
        self.assertIs(native["gossip_hints"], False)
        self.assertEqual(native["misc_hints"], [])
        self.assertIs(native["chests_match_contents"], False)
        self.assertEqual(native["logic_rules"], "glitchless")
        self.assertEqual(native["starting_age"], "child")
        self.assertIs(native["triforce_hunt"], False)
        self.assertFalse(set(AP_ONLY).intersection(native))

    def test_yaml_lists_every_public_native_option_with_independent_defaults(self):
        self.assertEqual(len(OPTION_SPECS), len(SPEC_BY_ID))
        rendered = yaml_options()
        names = re.findall(r"^  ([a-z_]+):", rendered, flags=re.M)
        self.assertEqual(set(names), set(SPEC_BY_ID).difference(AP_ONLY))
        self.assertEqual(len(names), len(set(names)))
        self.assertNotIn("ootrr_settings:", rendered)
        self.assertNotIn("OOTRR1-", rendered)
        self.assertNotIn("shuffle_dungeon_rewards:", rendered)
        first, second = default_options(), default_options()
        first["starting_items"].append("bow")
        first["starting_songs"].append("eponas_song")
        self.assertEqual(second["starting_items"], [])
        self.assertEqual(second["starting_songs"], [])

    def test_native_key_choices_are_the_implemented_subsets(self):
        self.assertEqual(set(SPEC_BY_ID["zora_fountain"]["choices"]), {"closed", "open"})
        self.assertEqual(set(SPEC_BY_ID["shuffle_smallkeys"]["choices"]),
                         {"vanilla", "dungeon", "any_dungeon", "keysanity"})
        boss = {"remove", "vanilla", "dungeon", "regional", "overworld", "any_dungeon", "keysanity"}
        self.assertEqual(set(SPEC_BY_ID["shuffle_bosskeys"]["choices"]), boss)
        self.assertEqual(set(SPEC_BY_ID["shuffle_ganon_bosskey"]["choices"]), boss)
        self.assertEqual(set(SPEC_BY_ID["shuffle_mapcompass"]["choices"]),
                         {"remove", "startwith", "vanilla", "dungeon", "regional", "any_dungeon", "keysanity"})
        self.assertEqual(set(SPEC_BY_ID["bridge"]["choices"]), {"vanilla", "dungeons"})
        for name in ("shuffle_smallkeys", "shuffle_bosskeys", "shuffle_ganon_bosskey", "shuffle_mapcompass"):
            with self.subTest(option=name):
                with self.assertRaises(ValueError):
                    engine_settings({"shuffle_chests": "overworld", name: "keysanity"})
                self.assertEqual(engine_settings({"shuffle_chests": "dungeons", name: "keysanity"})[name], "keysanity")
        with self.assertRaises(ValueError):
            engine_settings({"shuffle_chests": "dungeons", "shuffle_bosskeys": "overworld"})

    def test_known_values_reach_the_native_json_with_kokiri_goods_only(self):
        given = {"open_forest": "open", "open_kakariko": "open", "door_of_time_condition": "open",
                 "starting_hearts": 6, "faster_blocks": True, "trials": 3, "enemy_health": 125,
                 "starting_items": ["bombchus", "big_bomb_bag", "deku_shield"],
                 "starting_songs": ["eponas_song"], "death_link": True, "kokiri_shop_checks": True}
        native = engine_settings(given)
        for name, value in given.items():
            if name not in AP_ONLY:
                self.assertEqual(native[name], value if not isinstance(value, list) else
                                 [item for item in SPEC_BY_ID[name]["choices"] if item in value])
        self.assertEqual(native["shuffle_shops"], "shuffle")
        self.assertEqual(engine_settings({"kokiri_shop_checks": False})["shuffle_shops"], "off")
        self.assertEqual({name: native[name] for name in FIXED_SETTINGS}, FIXED_SETTINGS)

    def test_invalid_types_ranges_and_untracked_options_are_rejected(self):
        for values in ({"shuffle_chests": "off"}, {"shuffle_smallkeys": "overworld"},
                       {"shuffle_mapcompass": "overworld"}, {"shuffle_ganon_bosskey": "lacs_dungeons"},
                       {"bridge": "tokens"}, {"zora_fountain": "adult"}, {"starting_hearts": 0}, {"starting_hearts": True},
                       {"starting_hearts": "6"}, {"enemy_speed": 201}, {"more_enemies": 99}, {"enemy_health": 101},
                       {"death_link": "false"}, {"faster_blocks": 2}, {"starting_items": "bow"},
                       {"starting_items": ["zeldas_letter"]}, {"starting_songs": ["unknown_song"]},
                       {"shuffle_dungeon_rewards": "anywhere"}, {"shuffle_boss_hearts": True},
                       {"ootrr_settings": "OOTRR1-AAAA"}, {"unknown_setting": True}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                engine_settings(values)
        # Public difficulty controls deliberately use the native menu's steps.
        self.assertEqual(engine_settings({"enemy_health": 125})["enemy_health"], 125)

    def test_forest_time_and_starting_inventory_conflicts_are_rejected(self):
        self.assertNotIn("zeldas_letter", STARTING_ITEMS)
        self.assertEqual(len(STARTING_SONGS), 12)
        for values in ({"open_kakariko": "open"},
                       {"open_forest": "open", "open_kakariko": "open", "starting_songs": ["zeldas_lullaby"]},
                       {"early_beds": True, "time_always_passes": False},
                       {"starting_items": ["bombchus"]}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                engine_settings(values)
        for bag in ("bomb_bag", "big_bomb_bag", "biggest_bomb_bag"):
            self.assertIn("bombchus", engine_settings({"starting_items": [bag, "bombchus"]})["starting_items"])
        values = validate_options({"starting_items": ["bow", "bow", "bomb_bag"]})
        self.assertEqual(values["starting_items"].count("bow"), 1)


if __name__ == "__main__":
    unittest.main()
