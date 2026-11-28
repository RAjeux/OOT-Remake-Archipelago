"""Player YAML edits preserve unrolled options and use the shared settings schema."""
import ast
import copy
from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.catalog import GAME
from ootrr_triforce.settings import SPEC_BY_ID, default_options, yaml_options
from ootrr_triforce.yaml_import import (MAX_BYTES, YamlImportError, _ap_inactive,
                                        load_yaml, parse_yaml, render_imported_yaml)


def document(options=None, **top):
    return yaml.safe_dump(dict(name="Link", game=GAME, **{GAME: options or {}}, **top), sort_keys=False)


def rendered(imported, values=None, *, changed=None, name=None):
    return yaml.safe_load(render_imported_yaml(imported, name or imported.name,
        imported.values if values is None else values, changed_keys=changed))


class PlayerYamlImportTests(unittest.TestCase):
    def test_real_direct_fixture_loads_player_and_common_options_without_writes(self):
        source = ROOT / "tests/fixtures/yaml-direct/Zelda.yaml"
        original = source.read_bytes()
        imported = load_yaml(source)
        self.assertEqual(imported.name, "ZeldaTest")
        self.assertEqual(imported.values["starting_hearts"], 6)
        self.assertEqual(imported.values["shuffle_smallkeys"], "keysanity")
        self.assertTrue(imported.values["death_link"])
        out = rendered(imported, {"death_link": False})
        expected = yaml.safe_load(original)
        expected[GAME]["death_link"] = False
        self.assertEqual(out, expected)
        self.assertEqual(source.read_bytes(), original)

    def test_current_complete_writer_roundtrips_every_option(self):
        text = 'name: Link\ngame: "'+GAME+'"\n"'+GAME+'":\n'+yaml_options()+"  death_link: true\n"
        imported = parse_yaml(text)
        self.assertEqual(imported.values, dict(default_options(), death_link=True))
        self.assertFalse(imported.invalid_options)
        self.assertEqual(rendered(imported), yaml.safe_load(text))

    def test_weights_random_and_aliases_are_not_rolled_or_replaced(self):
        raw = {"shuffle_shops": {"off": "10", "shuffle": 90.9},
               "starting_hearts": "random-range-low-3-8", "death_link": "random",
               "cosmetic_color_mode": "random", "progression_balancing": 65,
               "accessibility": "full", "start_inventory": {"Bottle": 1}}
        imported = parse_yaml(document(raw))
        self.assertTrue(set(raw)-{"progression_balancing", "accessibility", "start_inventory"} <= set(imported.preserved_options))
        self.assertFalse(imported.invalid_options)
        self.assertEqual(rendered(imported)[GAME], raw)
        explicit = parse_yaml(document({"shuffle_shops": "random_deals", "cosmetic_color_mode": "random_colors"}))
        self.assertEqual(explicit.values["shuffle_shops"], "random")
        self.assertEqual(explicit.values["cosmetic_color_mode"], "random")
        self.assertEqual(rendered(explicit)[GAME], {"shuffle_shops": "random_deals", "cosmetic_color_mode": "random_colors"})

    def test_explicit_edit_equal_to_projection_default_replaces_a_weight(self):
        imported = parse_yaml(document({"starting_hearts": {3: 50, 8: 50}}))
        self.assertEqual(imported.values["starting_hearts"], 3)
        self.assertEqual(rendered(imported, {"starting_hearts": 3})[GAME]["starting_hearts"], {3: 50, 8: 50})
        self.assertEqual(rendered(imported, {"starting_hearts": 3}, changed={"starting_hearts"})[GAME]["starting_hearts"], 3)

    def test_only_edited_keys_are_added_and_metadata_stays_semantically_identical(self):
        text = "name: Link\ngame: "+GAME+"\ndescription: old file\nmetadata:\n  enabled: on\n  disabled: off\n  date: 2026-11-28\n"+GAME+":\n  death_link: false\n  future_option: {nested: [on, off, null]}\n"
        imported = parse_yaml(text)
        out = rendered(imported, {"death_link": True}, name="New Link")
        expected = yaml.safe_load(text)
        expected["name"] = "New Link"
        expected[GAME]["death_link"] = True
        self.assertEqual(out, expected)
        self.assertEqual(out["metadata"]["date"], date(2026, 11, 28))
        self.assertEqual(set(out[GAME]), {"death_link", "future_option"})
        self.assertIn("future_option", imported.preserved_options)

    def test_yaml_bool_choice_aliases_and_unquoted_off_follow_ap_semantics(self):
        text = "name: Link\ngame: "+GAME+"\n"+GAME+":\n  shuffle_shops: off\n  shuffle_chests: {off: 50, all: 50}\n"
        imported = parse_yaml(text)
        self.assertEqual(imported.values["shuffle_shops"], "off")
        self.assertFalse(imported.invalid_options)
        out = rendered(imported)
        self.assertIs(out[GAME]["shuffle_shops"], False)
        self.assertEqual(out[GAME]["shuffle_chests"], {False: 50, "all": 50})
        invalid = parse_yaml(document({"shuffle_chests": True}))
        self.assertIn("shuffle_chests", invalid.invalid_options, "No option_on exists; True is not choice index 1")

    def test_unquoted_choice_off_keeps_trigger_comparison_semantics(self):
        text = ("name: Link\ngame: "+GAME+"\n"+GAME+":\n  shuffle_shops: off\n"
                "  triggers:\n  - option_name: shuffle_shops\n    option_result: false\n"
                "    options:\n      "+GAME+":\n        death_link: true\n")
        imported = parse_yaml(text)
        out = rendered(imported, {"starting_hearts": 6})
        self.assertEqual(out[GAME]["shuffle_shops"], out[GAME]["triggers"][0]["option_result"])
        expected = yaml.safe_load(text)
        expected[GAME]["starting_hearts"] = 6
        self.assertEqual(out, expected)

    def test_native_sets_dicts_and_ap_scalar_aliases_are_projected_without_loss(self):
        raw = {"starting_items": "bow, bottle", "death_link": "disabled", "starting_hearts": "high",
               "cosmetic_color_mode": "custom", "cosmetic_colors": {"hair": "#aabbcc"}}
        imported = parse_yaml(document(raw))
        self.assertEqual(imported.values["starting_items"], ["bow", "bottle"])
        self.assertFalse(imported.values["death_link"])
        self.assertEqual(imported.values["starting_hearts"], 20)
        self.assertEqual(imported.values["cosmetic_colors"], {"hair": "#AABBCC"})
        self.assertEqual(rendered(imported)[GAME], raw)
        mapping = parse_yaml(document({"starting_items": {"bow": None, "bottle": None}}))
        self.assertEqual(mapping.values["starting_items"], ["bow", "bottle"])
        self.assertFalse(mapping.invalid_options)

    def test_random_option_sets_and_empty_weight_mappings_are_preserved(self):
        for choice in ("random", "random-low", "random-high", "random-middle", "random-range-low-1-3"):
            with self.subTest(choice=choice):
                imported = parse_yaml(document({"starting_items": choice, "shuffle_shops": {}}))
                self.assertFalse(imported.invalid_options)
                self.assertEqual(imported.values["shuffle_shops"], "off")
                self.assertEqual(rendered(imported)[GAME], {"starting_items": choice, "shuffle_shops": {}})

    def test_explicit_invalid_known_values_are_reported_and_require_a_replacement(self):
        imported = parse_yaml(document({"starting_hearts": 100}))
        self.assertIn("starting_hearts", imported.invalid_options)
        with self.assertRaises(YamlImportError) as error:
            rendered(imported, {"death_link": True})
        self.assertEqual(error.exception.code, "settings")
        self.assertEqual(rendered(imported, {"starting_hearts": 3}, changed={"starting_hearts"})[GAME]["starting_hearts"], 3)

    def test_unknown_options_and_common_game_options_are_preserved(self):
        raw = {"newer_option": {"variant": ["x", "y"]}, "local_items": ["Bottle"],
               "exclude_locations": ["KF Kokiri Sword Chest"], "priority_locations": [],
               "item_links": [{"name": "Link", "item_pool": ["Rupees (5)"]}]}
        imported = parse_yaml(document(raw, requires={"version": "0.6.8"}))
        self.assertEqual(rendered(imported)[GAME], raw)
        self.assertEqual([n.key for n in imported.warnings if n.code == "unknown"], ["newer_option"])

    def test_inactive_raw_values_survive_and_take_effect_when_the_parent_is_edited(self):
        imported = parse_yaml(document({"bridge": "vanilla", "bridge_rewards": 4}))
        self.assertEqual(imported.values["bridge_rewards"], 9)
        self.assertEqual(imported.preserved_options["bridge_rewards"], 4)
        self.assertEqual(rendered(imported)[GAME]["bridge_rewards"], 4)
        out = rendered(imported, {"bridge": "dungeons"}, changed={"bridge"})
        self.assertEqual(out[GAME], {"bridge": "dungeons", "bridge_rewards": 4})

    def test_invalid_active_combinations_are_not_hidden_by_gui_normalization(self):
        imported = parse_yaml(document({"open_forest": "closed", "open_kakariko": "open"}))
        self.assertIn("open_kakariko", imported.preserved_options)
        with self.assertRaises(YamlImportError) as error:
            rendered(imported)
        self.assertIn("open_kakariko", error.exception.detail)
        repaired = rendered(imported, {"open_forest": "open"}, changed={"open_forest"})
        self.assertEqual(repaired[GAME], {"open_forest": "open", "open_kakariko": "open"})

    def test_removed_test_options_are_reported_instead_of_being_sent_to_generator(self):
        imported = parse_yaml(document({"kokiri_shop_checks": True, "shuffle_trade_checks": False,
                                        "volvagia_roams": True, "death_link": True}))
        self.assertEqual(set(imported.removed_options), {"kokiri_shop_checks", "shuffle_trade_checks", "volvagia_roams"})
        self.assertEqual(rendered(imported)[GAME], {"death_link": True})
        self.assertEqual(sum(n.code == "removed" for n in imported.warnings), 3)
        self.assertTrue(imported.requires_review)

    def test_only_active_removed_or_unsupported_legacy_settings_require_review(self):
        inactive = parse_yaml(document({"kokiri_shop_checks": False, "shuffle_trade_checks": "off"}))
        self.assertFalse(inactive.requires_review)
        exact = parse_yaml(document({"ootrr_settings": "OOTRR1-EXAMPLE"}),
                           decoder=Mock(return_value={"starting_hearts": 6}))
        self.assertFalse(exact.requires_review)
        unsupported = parse_yaml(document({"ootrr_settings": "OOTRR1-EXAMPLE"}),
                                 decoder=Mock(return_value={"starting_age": "adult"}))
        self.assertTrue(unsupported.requires_review)

    def test_legacy_string_is_decoded_exactly_with_explicit_options_taking_precedence(self):
        decoder = Mock(return_value={"open_forest": "open", "open_kakariko": "open",
            "starting_hearts": 8, "shuffle_shops": "random", "starting_age": "adult",
            "logic_rules": "glitchless"})
        imported = parse_yaml(document({"ootrr_settings": "OOTRR1-EXAMPLE", "starting_hearts": 7,
                                         "accessibility": "full"}), decoder=decoder)
        decoder.assert_called_once_with("OOTRR1-EXAMPLE")
        self.assertEqual(imported.values["starting_hearts"], 7)
        self.assertEqual(imported.values["shuffle_shops"], "random")
        out = rendered(imported)
        self.assertNotIn("ootrr_settings", out[GAME])
        self.assertNotIn("starting_age", out[GAME])
        self.assertEqual(out[GAME]["shuffle_shops"], "random_deals")
        self.assertTrue(any(n.code == "legacy_unsupported" and n.key == "starting_age" for n in imported.warnings))
        self.assertIn("OOTRR1-EXAMPLE", render_imported_yaml(imported, "Link", imported.values))

    def test_invalid_legacy_string_or_failed_decoder_never_returns_a_partial_import(self):
        for raw, decoder in (("not a code", Mock()), ("OOTRR1-X", Mock(side_effect=RuntimeError("invalid code")))):
            with self.subTest(raw=raw), self.assertRaises(YamlImportError) as error:
                parse_yaml(document({"ootrr_settings": raw}), decoder=decoder)
            self.assertEqual(error.exception.code, "legacy")

    def test_shared_yaml_alias_does_not_make_a_game_edit_change_other_metadata(self):
        text = "name: Link\ngame: "+GAME+"\ndefaults: &defaults\n  death_link: false\n"+GAME+": *defaults\n"
        imported = parse_yaml(text)
        original = copy.deepcopy(imported.document)
        out = rendered(imported, {"death_link": True})
        self.assertEqual(out["defaults"], {"death_link": False})
        self.assertEqual(out[GAME], {"death_link": True})
        self.assertEqual(imported.document, original)

    def test_wrong_game_multiple_documents_or_non_player_shapes_are_rejected(self):
        for text in ("name: Link\ngame: Ocarina of Time\n", "[]", "name: Link\n---\nname: Ami\n",
                     "name: Link\ngame: [x,y]\n",
                     "name: Link\ngame: "+GAME+"\n"+GAME+": []\n"):
            with self.subTest(text=text), self.assertRaises(YamlImportError):
                parse_yaml(text)

    def test_duplicate_keys_bool_numeric_collisions_and_ap_plus_collisions_are_rejected(self):
        for body in ("death_link: true\n  death_link: false", "future: {false: x, 0: y}",
                     "death_link: true\n  +death_link: false"):
            text = "name: Link\ngame: "+GAME+"\n"+GAME+":\n  "+body+"\n"
            with self.subTest(body=body), self.assertRaises(YamlImportError) as error:
                parse_yaml(text)
            self.assertEqual(error.exception.code, "duplicate_key")

    def test_unsafe_tags_cycles_expansion_size_and_depth_are_bounded(self):
        with patch("os.system") as system:
            with self.assertRaises(YamlImportError):
                parse_yaml("!!python/object/apply:os.system ['arbitrary command']")
            system.assert_not_called()
        for text in ("a: &a [*a]", "["*50+"0"+"]"*50,
                     "a: &a [0,0]\n"+"\n".join(f"x{i}: ["+",".join("*a" for _ in range(1000))+"]" for i in range(31))):
            with self.subTest(text=text[:30]), self.assertRaises(YamlImportError):
                parse_yaml(text)
        with self.assertRaises(YamlImportError) as error:
            parse_yaml("#"*(MAX_BYTES+1))
        self.assertEqual(error.exception.code, "too_large")

    def test_load_supports_bom_and_does_not_read_unbounded_files(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)/"player.yaml"
            p.write_bytes(b"\xef\xbb\xbf"+document({"death_link": True}).encode())
            imported = load_yaml(p)
            self.assertTrue(imported.values["death_link"])
            self.assertEqual(imported.source, p)
            p.write_bytes(b"#"*(MAX_BYTES+1))
            with self.assertRaises(YamlImportError): load_yaml(p)

    def test_generator_inactive_normalization_parity(self):
        tree = ast.parse((ROOT/"apworld/ootrr_remake/options.py").read_text(encoding="utf-8"))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_normalize_inactive_options")
        namespace = dict(default_options=default_options)
        exec(compile(ast.Module(body=[function], type_ignores=[]), "authoritative-options.py", "exec"), namespace)
        oracle = namespace[function.name]
        cases = [default_options(), dict(default_options(), bridge="open", bridge_rewards=4,
            open_forest="closed", open_kakariko="open", shuffle_rewards="off", shuffle_potion_shop=True)]
        for name, spec in SPEC_BY_ID.items():
            variants = spec.get("choices", ()) if spec["kind"] == "choice" else (
                (False, True) if spec["kind"] == "toggle" else (spec["min"], spec["max"]) if spec["kind"] == "range" else ())
            cases.extend(dict(default_options(), **{name: value}) for value in variants)
        for values in cases:
            with self.subTest(values=values):
                self.assertEqual(_ap_inactive(values), oracle(copy.deepcopy(values)))


if __name__ == "__main__":
    unittest.main()
