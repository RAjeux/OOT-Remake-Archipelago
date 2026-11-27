"""Bilingual choice explanations stay aligned with the single AP/YAML schema."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.app_window import yaml_content
from ootrr_triforce.settings import OPTION_SPECS, SPEC_BY_ID, ap_choice_key, default_options, engine_settings
from ootrr_triforce.settings_labels import (
    CHOICE_HELP, ESSENTIAL_SETTINGS, GROUP_ORDER, LABELS, TOGGLE_OFF_HELP,
    active_reason, choice_description, choice_label, description, is_advanced,
    normalize_inactive, selection_summary, setting_label,
)


class SettingsHelpTests(unittest.TestCase):
    def test_every_choice_and_both_toggle_states_have_bilingual_explanations(self):
        self.assertEqual(set(LABELS), set(SPEC_BY_ID))
        translated = json.loads((ROOT / "client/ootrr_triforce/settings_fr.json").read_text(encoding="utf-8"))
        self.assertEqual(set(translated), set(SPEC_BY_ID))
        self.assertEqual(set(TOGGLE_OFF_HELP), {spec["id"] for spec in OPTION_SPECS if spec["kind"] == "toggle"})
        for spec in OPTION_SPECS:
            name = spec["id"]
            values = (spec["choices"] if spec["kind"] == "choice" else
                      (False, True) if spec["kind"] == "toggle" else
                      (spec["min"], spec["default"], spec["max"]) if spec["kind"] == "range" else
                      ({}, {"kokiri": "#ABCDEF"}) if spec["kind"] == "dict" else
                      ([], [spec["choices"][0]], list(spec["choices"])))
            for value in values:
                with self.subTest(name=name, value=value):
                    if spec["kind"] == "choice":
                        self.assertIn((name, value), CHOICE_HELP)
                    texts = [choice_description(name, value, language) for language in ("en", "fr")]
                    self.assertTrue(all(len(text.strip()) > 15 for text in texts))
                    self.assertNotEqual(texts[0], texts[1])
                    for text in texts:
                        self.assertNotRegex(text, "\ufffd|[A-Za-z]\\?[A-Za-z]")
            if spec["kind"] == "set":
                for value in spec["choices"]:
                    for language in ("en", "fr"):
                        self.assertIn(choice_label(name, value, language), choice_description(name, value, language))

    def test_display_groups_and_advanced_filter_never_change_the_schema_or_defaults(self):
        snapshot = deepcopy(OPTION_SPECS)
        defaults = default_options()
        self.assertEqual(set(GROUP_ORDER), {spec["group"] for spec in OPTION_SPECS})
        self.assertEqual(len(GROUP_ORDER), len(set(GROUP_ORDER)))
        self.assertTrue(ESSENTIAL_SETTINGS <= set(SPEC_BY_ID))
        for name in SPEC_BY_ID:
            self.assertEqual(is_advanced(name), name not in ESSENTIAL_SETTINGS)
            for language in ("en", "fr"):
                self.assertTrue(setting_label(name, language))
                self.assertTrue(description(name, language))
        self.assertEqual(snapshot, OPTION_SPECS)
        self.assertEqual(defaults, default_options())
        self.assertEqual(SPEC_BY_ID["shuffle_skulltulas"]["choices"], ("off", "pinned", "matched"))
        self.assertEqual(SPEC_BY_ID["shuffle_freestanding_items"]["default"], "off")
        self.assertFalse(defaults["death_link"])
        self.assertEqual(defaults["skip_cutscenes"], "off")

    def test_cheap_price_help_matches_native_random_algorithm_instead_of_fixed_ten(self):
        for name in ("scrub_prices", "merchant_prices", "fairy_prices"):
            for language in ("en", "fr"):
                text = choice_description(name, "cheap", language)
                self.assertIn("95", text)
                self.assertIn("5", text)
                self.assertNotEqual(choice_label(name, "cheap", language), "10 rupees each")
                self.assertIn("0", text)
                self.assertIn("10", text, "Explain that Cheap is not the fixed ten-rupee choice.")
        native = engine_settings({"shuffle_rewards": "supported", "shuffle_scrubs_a": True,
                                  "shuffle_merchants": "no_beans", "scrub_prices": "cheap",
                                  "merchant_prices": "cheap", "fairy_prices": "cheap"})
        for name in ("scrub_prices", "merchant_prices", "fairy_prices"):
            self.assertEqual(native[name], "cheap", "Help must not silently change the native mode.")

    def test_important_aliases_and_distinct_goal_controls_are_explained(self):
        for language in ("en", "fr"):
            self.assertIn("44", choice_description("shuffle_skulltulas", "pinned", language))
            self.assertIn("100", choice_description("shuffle_skulltulas", "matched", language))
            self.assertIn("23", choice_description("shuffle_skulltulas", "matched", language))
            self.assertIn("64", choice_description("shuffle_shops", "random", language))
            self.assertIn("Off", choice_description("shuffle_freestanding_items", "pieces", language))
            self.assertIn("Pieces", choice_description("shuffle_freestanding_items", "off", language))
            self.assertIn("3", description("door_of_time_condition", language)
                          .replace("three", "3").replace("trois", "3"))
        self.assertIn("Light Arrows scene", choice_description("bridge", "vanilla", "en"))
        self.assertIn("Light Arrows", choice_description("shuffle_ganon_bosskey", "lacs_dungeons", "en"))
        self.assertIn("not automatically", choice_description("skip_cutscenes", "story", "en"))
        self.assertIn("ten", description("enemy_gates", "en"))
        self.assertIn("dix", description("enemy_gates", "fr"))
        self.assertIn("sticks and nuts", description("no_ammo_drops", "en"))

    def test_summary_shows_deathlink_keys_and_effective_inactive_choices_without_mutating_draft(self):
        draft = default_options()
        draft.update(death_link=True, shuffle_rewards="off", shuffle_merchants="all",
                     merchant_prices="fixed", merchant_price_fixed=80, bridge="open",
                     shuffle_smallkeys="keysanity")
        original = deepcopy(draft)
        for language in ("en", "fr"):
            summary = selection_summary(draft, language)
            self.assertEqual(len(summary), 6)
            self.assertIn("DeathLink: " + ("Oui" if language == "fr" else "On"), summary[0])
            self.assertIn(choice_label("shuffle_smallkeys", "keysanity", language), summary[3])
            self.assertIn("inactif" if language == "fr" else "inactive", summary[-1])
            self.assertTrue(any("Porte du Temps" in row if language == "fr" else "Door of Time" in row for row in summary))
        self.assertEqual(draft, original)
        normalized = normalize_inactive(draft)
        self.assertEqual(normalized["shuffle_merchants"], "off")
        self.assertEqual(normalized["merchant_price_fixed"], 10)
        self.assertEqual(normalized["bridge_rewards"], 0)

    def test_yaml_and_ap_option_classes_use_the_same_updated_help_and_values(self):
        # Execute the real AP type factory without requiring an installed AP
        # interpreter. Official AP generation is tested separately as well.
        option_source = ast.parse((ROOT / "apworld/ootrr_remake/options.py").read_text(encoding="utf-8"))
        factory = next(node for node in option_source.body if isinstance(node, ast.FunctionDef) and node.name == "_option_type")
        base = type("APBase", (), {})
        namespace = {name: base for name in ("Choice", "Range", "SteppedRange", "OptionSet", "OptionDict", "Toggle")}
        namespace.update(__name__="settings_help_test", setting_label=setting_label, ap_choice_key=ap_choice_key)
        exec(compile(ast.Module(body=[factory], type_ignores=[]), "actual_ap_option_factory", "exec"), namespace)
        before = deepcopy(OPTION_SPECS)
        for spec in OPTION_SPECS:
            option = namespace["_option_type"](spec)
            self.assertEqual(option.__doc__, description(spec["id"], "en"))
            self.assertEqual(option.display_name, setting_label(spec["id"], "en"))
            if spec["kind"] == "choice":
                for index, value in enumerate(spec["choices"]):
                    public = ap_choice_key(spec["id"], value)
                    self.assertEqual(getattr(option, "option_" + public), index)
        values = default_options()
        values.update(shuffle_shops="random", death_link=True, shuffle_skulltulas="matched")
        for language in ("en", "fr"):
            yaml = yaml_content("AuditHelp", values, language)
            decoded = {key: json.loads(value) for key, value in re.findall(r"^  ([a-z_]+): (.+)$", yaml, re.M)}
            self.assertEqual(decoded, dict(values, shuffle_shops="random_deals"))
            comments = " ".join(line.lstrip(" #") for line in yaml.splitlines() if line.lstrip().startswith("#"))
            self.assertIn(description("scrub_prices", language).split(".")[0], comments)
        self.assertEqual(before, OPTION_SPECS)


if __name__ == "__main__":
    unittest.main()
