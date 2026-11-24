"""Bilingual display names must never alter AP identity or foreign worlds."""
import ast
import json
from pathlib import Path
import re
import sys
from string import Formatter
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.catalog import GAME, LEGACY_GAME, ITEM_IDS
from ootrr_triforce.item_names import item_name, item_names
from ootrr_triforce.settings import AP_ONLY, SPEC_BY_ID, yaml_options
from oot_rando.patching.ap_item import ap_messages


class LocalizationCatalogTests(unittest.TestCase):
    def test_every_static_ui_message_has_a_french_translation(self):
        package = ROOT / "client/ootrr_triforce"
        catalogue = json.loads((package / "i18n_fr.json").read_text(encoding="utf-8"))
        for path in [*package.glob("*.py"), ROOT / "distribution/Observer-Archipelago.py"]:
            for call in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "tr"
                        and call.args and isinstance(call.args[0], ast.Constant)
                        and isinstance(call.args[0].value, str)):
                    with self.subTest(file=path.name, line=call.lineno):
                        self.assertIn(call.args[0].value, catalogue)

    def test_french_templates_preserve_every_english_format_argument(self):
        catalogue = json.loads((ROOT / "client/ootrr_triforce/i18n_fr.json").read_text(encoding="utf-8"))
        formatter = Formatter()
        for english, french in catalogue.items():
            with self.subTest(message=english):
                fields = lambda text: {name for _, name, _, _ in formatter.parse(text) if name is not None}
                self.assertEqual(fields(english), fields(french))

    def test_every_supported_zelda_item_has_two_nonempty_labels(self):
        original = dict(ITEM_IDS)
        labels = item_names()
        self.assertEqual(set(labels), set(ITEM_IDS))
        self.assertEqual(len(labels), 205)
        for canonical, texts in labels.items():
            with self.subTest(item=canonical):
                self.assertEqual(texts["en"], canonical)
                self.assertTrue(texts["fr"].strip())
        self.assertEqual(ITEM_IDS, original)
        labels["Bow"]["fr"] = "changed caller copy"
        self.assertEqual(item_names()["Bow"]["fr"], "Arc")

    def test_game_and_archive_language_codes_select_the_same_french_names(self):
        for language in ("fr", "fr-FR", "fr-CA", "EUfr", "CAfr"):
            with self.subTest(language=language):
                self.assertEqual(item_name("Mirror Shield", language), "Bouclier miroir")
        for language in ("en", "en-US", "USen", "de", "ja", ""):
            self.assertEqual(item_name("Mirror Shield", language), "Mirror Shield")
        self.assertEqual(item_name("Small Key (Water Temple)", "fr"), "Petite clé (Temple de l'Eau)")
        self.assertIn("15", item_name("Buy Bombchu (15)", "fr"))

    def test_unknown_names_and_foreign_namespace_collisions_are_untouched(self):
        for game in ("Dark Souls III", "A Link to the Past", "Unknown World"):
            self.assertEqual(item_name("Bow", "fr", game=game), "Bow")
        self.assertEqual(item_name("Unknown {item} — Ω", "fr", game=GAME), "Unknown {item} — Ω")
        self.assertEqual(item_name("Bow", "fr", game=LEGACY_GAME), "Arc")

    def test_medal_messages_localize_only_the_explicit_owning_game(self):
        owner = "Ami {P1} Ω"
        french = ap_messages("Mirror Shield", owner, "EUfr", GAME)
        self.assertIn("Bouclier miroir", french["GetMessage"])
        self.assertIn(owner, french["GetMessage"])
        english = ap_messages("Mirror Shield", owner, "USen", GAME)
        self.assertIn("You found", english["GetMessage"])
        self.assertIn("Mirror Shield", english["GetMessage"])
        self.assertIn("Bow", ap_messages("Bow", owner, "EUfr", "Dark Souls III")["GetMessage"])
        self.assertIn("Mirror Shield", ap_messages("Mirror Shield", owner, "EUfr")["GetMessage"])
        self.assertIn("You found", ap_messages("Bow", owner, "EUde", GAME)["GetMessage"])

    def test_yaml_language_changes_comments_without_changing_settings(self):
        english, french = yaml_options(), yaml_options(language="fr")
        def values(text):
            return {key: json.loads(value) for key, value in re.findall(r"^  ([a-z_]+): (.+)$", text, re.M)}
        self.assertEqual(values(english), values(french))
        self.assertEqual(set(values(english)), set(SPEC_BY_ID).difference({"death_link"}))
        self.assertIn("Fixed goal: defeat Ganon", english)
        self.assertIn("Objectif fixe", french)
        self.assertIn("Starting inventory", english)
        self.assertIn("Inventaire initial", french)
        catalogue = json.loads((ROOT / "client/ootrr_triforce/settings_fr.json").read_text(encoding="utf-8"))
        self.assertEqual(set(catalogue), set(SPEC_BY_ID))


if __name__ == "__main__":
    unittest.main()
