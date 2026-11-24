"""Player edits preserve AP options and cannot silently change generation modes."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.catalog import GAME
from ootrr_triforce.settings_editor import ConfigurationError, PlayerConfiguration, specs_for


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_legacy_import_edit_export_preserves_weighted_and_common_options(self):
        source = self.root / "original.yaml"
        import yaml
        data = {
            "name": 'Link: "test"', "game": GAME, "description": "Keep this description", "requires": {"version": "0.6.8"},
            GAME: {"shuffle_shops": {"off": 1, "random_deals": 4}, "death_link": True,
                   "start_inventory": {"Bow": 1}, "local_items": ["Kokiri Sword"]}}
        source.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        original = source.read_bytes()
        document = PlayerConfiguration.read(source)
        self.assertEqual(document.mode, "legacy")
        document.apply({"starting_hearts": 5})
        target = self.root / "edited.yaml"
        document.write(target)
        exported = yaml.safe_load(target.read_text(encoding="utf-8"))
        self.assertEqual(exported["name"], data["name"])
        self.assertEqual(exported["description"], data["description"])
        self.assertEqual(exported["requires"], data["requires"])
        self.assertEqual(exported[GAME]["shuffle_shops"], data[GAME]["shuffle_shops"])
        self.assertEqual(exported[GAME]["start_inventory"], {"Bow": 1})
        self.assertEqual(exported[GAME]["local_items"], ["Kokiri Sword"])
        self.assertEqual(exported[GAME]["starting_hearts"], 5)
        self.assertEqual(exported[GAME]["generation_mode"], "legacy")
        self.assertEqual(source.read_bytes(), original)

    def test_new_full_configuration_uses_supported_schema_and_round_trips(self):
        document = PlayerConfiguration.new("full_network", "Link")
        document.validate()
        self.assertGreater(len(specs_for(document.mode)), 40)
        self.assertEqual(document.values["full_tokensanity"], "all")
        self.assertEqual(document.values["full_shopsanity"], "all")
        for suffix in (".yaml", ".json"):
            target = self.root / ("player" + suffix)
            document.write(target)
            result = PlayerConfiguration.read(target)
            self.assertEqual(result.as_mapping(), document.as_mapping())

    def test_presets_do_not_drop_common_advanced_options(self):
        for mode in ("legacy", "full_network"):
            for preset in ("standard", "maximum_ap", "quick_start"):
                document = PlayerConfiguration.new(mode)
                document.values["accessibility"] = "items"
                document.values["start_inventory"] = {"Bow": 1}
                document.common["description"] = "My room"
                document.preset(preset)
                self.assertEqual(document.values["accessibility"], "items")
                self.assertEqual(document.values["start_inventory"], {"Bow": 1})
                self.assertEqual(document.common["description"], "My room")

    def test_import_rejects_duplicate_keys_recursive_alias_and_other_game(self):
        documents = [
            'name: Link\nname: Other\ngame: ' + GAME + '\n',
            'name: Link\ngame: ' + GAME + '\n"' + GAME + '": &loop\n  loop: *loop\n',
            'name: Link\ngame: Another game\nAnother game: {}\n',
            '!!python/object/apply:os.system ["do-not-run"]',
        ]
        for index, text in enumerate(documents):
            with self.subTest(index=index):
                path = self.root / "invalid.yaml"
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(ConfigurationError):
                    PlayerConfiguration.read(path)

    def test_invalid_edit_is_atomic_and_concrete_dependencies_are_checked(self):
        document = PlayerConfiguration.new("legacy")
        before = document.as_mapping()
        for update in ({"starting_hearts": 21}, {"enemy_speed": 76}, {"death_link": "true"},
                       {"open_kakariko": "open", "open_forest": "closed"}):
            with self.subTest(update=update), self.assertRaises(ConfigurationError):
                document.apply(update)
            self.assertEqual(document.as_mapping(), before)

    def test_weighted_values_must_be_supported_and_have_positive_integer_weights(self):
        document = PlayerConfiguration.new("legacy")
        for value in ({"off": 0}, {"off": -1, "all": 1}, {"wrong": 1}, {"off": "yes"}):
            with self.subTest(value=value), self.assertRaises(ConfigurationError):
                document.apply({"shuffle_chests": value})
        document.apply({"shuffle_chests": {"off": 1, "all": 5}, "starting_hearts": "random-low"})
        self.assertEqual(document.values["shuffle_chests"], {"off": 1, "all": 5})

    def test_unknown_mode_and_duplicate_json_are_rejected(self):
        for text in ('{"name":"Link","name":"Other"}', json.dumps({"name": "Link", "game": GAME,
                      GAME: {"generation_mode": "unknown"}})):
            path = self.root / "invalid.json"
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(ConfigurationError):
                PlayerConfiguration.read(path)

    def test_yaml_merge_defaults_are_supported_without_losing_explicit_overrides(self):
        source = self.root / "merged.yaml"
        source.write_text('name: Link\ngame: "' + GAME + '"\ndefaults: &base\n  starting_hearts: 3\n'
                          '  death_link: false\n' + json.dumps(GAME) + ':\n  <<: *base\n  starting_hearts: 5\n', encoding="utf-8")
        document = PlayerConfiguration.read(source)
        self.assertEqual(document.values["starting_hearts"], 5)
        self.assertFalse(document.values["death_link"])

    def test_shared_alias_expansion_has_a_total_work_bound(self):
        source = self.root / "aliases.yaml"
        lines = ['name: Link', 'game: ' + json.dumps(GAME), json.dumps(GAME) + ': {}', 'a: &a [0]']
        for index, letter in enumerate('bcdefg'):
            previous = chr(ord(letter) - 1)
            lines.append(letter + ': &' + letter + ' [' + ','.join('*' + previous for _ in range(10)) + ']')
        source.write_text('\n'.join(lines), encoding="utf-8")
        with self.assertRaises(ConfigurationError):
            PlayerConfiguration.read(source)

    def test_excessive_merge_aliases_are_rejected_before_safe_loader_constructs_mappings(self):
        import yaml
        source = self.root / "merge-aliases.yaml"
        lines = ['name: Link', 'game: ' + json.dumps(GAME), json.dumps(GAME) + ': {}',
                 'layer0: &layer0 {value: 1}']
        for index in range(1, 19):
            previous = '*layer' + str(index - 1)
            lines.append('layer' + str(index) + ': &layer' + str(index) + ' {<<: [' + previous + ',' + previous + ']}')
        source.write_text('\n'.join(lines), encoding='utf-8')
        with patch.object(yaml.SafeLoader, 'construct_document', side_effect=AssertionError('Construction must not begin')) as construct:
            with self.assertRaisesRegex(ConfigurationError, 'too many|too deeply'):
                PlayerConfiguration.read(source)
            construct.assert_not_called()

    def test_all_full_option_metadata_has_french_display_text(self):
        from ootrr_triforce.full_ap import full_option_specs
        catalogue = json.loads((ROOT / "client/ootrr_triforce/i18n_fr.json").read_text(encoding="utf-8"))
        for spec in full_option_specs():
            for key in ("label", "description", "group"):
                self.assertTrue(spec[key] in catalogue, spec["id"] + ": " + key)


if __name__ == "__main__":
    unittest.main()
