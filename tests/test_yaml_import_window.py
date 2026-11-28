"""Real launcher import/edit/save workflows using only temporary player files."""
import copy
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_app_window as fixtures
from ootrr_triforce.catalog import GAME
from ootrr_triforce.settings import default_options
from ootrr_triforce.settings_labels import setting_label
from ootrr_triforce.yaml_import import load_yaml


class YamlImportWindowTests(unittest.TestCase):
    def setUp(self):
        # Compose the existing isolated app fixture without collecting its tests
        # a second time through inheritance or an imported TestCase alias.
        self.fixture = fixtures.AppWindowTests("test_cancelled_save_dialog_writes_nothing")
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.window = self.fixture.open()
        self.window.show_page("yaml")

    def player(self, options=None, **metadata):
        document = {
            "name": "Old adventure",
            "game": GAME,
            "description": "A configuration kept for the next adventure.",
            "requires": {"version": "0.6.7"},
            GAME: {
                "death_link": False,
                "progression_balancing": 35,
                "accessibility": "full",
                "local_items": ["Ice Trap"],
                "non_local_items": ["Progressive Bomb Bag"],
                "start_inventory": {"Deku Shield": 1},
            },
        }
        document[GAME].update(options or {})
        document.update(metadata)
        return document

    def write_player(self, document, name="old-player.yaml"):
        source = self.fixture.base / name
        # JSON is valid YAML and leaves no YAML 1.1 Boolean ambiguity in the
        # fixture's expected structure.
        source.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        return source

    def import_player(self, document, name="old-player.yaml"):
        source = self.write_player(document, name)
        self.fixture.dialogs.open = str(source)
        self.window.import_yaml_button.invoke()
        self.fixture.pump(lambda: not self.window.busy)
        self.assertEqual(self.window.status_key, "yaml_imported")
        return source

    def snapshot(self):
        return (self.window.yaml_imported, self.window.yaml_source,
                copy.deepcopy(self.window.yaml_values), set(self.window.yaml_changed_keys),
                self.window.player_name.get())

    def save_copy(self, name="modified-player.yaml"):
        target = self.fixture.base / name
        self.fixture.dialogs.save = str(target)
        self.window.save_yaml_button.invoke()
        self.fixture.pump(lambda: not self.window.busy)
        self.assertEqual(self.window.status_key, "yaml_saved")
        return target, yaml.safe_load(target.read_text(encoding="utf-8"))

    def test_import_loads_typed_settings_name_and_metadata_then_saves_a_copy(self):
        document = self.player({
            "death_link": True, "starting_items": ["bow"], "bridge": "dungeons", "bridge_rewards": 4,
            "cosmetic_color_mode": "custom", "cosmetic_colors": {"kokiri": "#123456"},
        })
        source = self.import_player(document)
        original = source.read_bytes()
        self.assertEqual(self.window.player_name.get(), document["name"])
        self.assertEqual(self.window.yaml_source, source)
        self.assertEqual(self.window.yaml_imported.document, document)
        self.assertEqual(self.window.yaml_changed_keys, set())
        for name in ("death_link", "starting_items", "bridge", "bridge_rewards", "cosmetic_colors"):
            self.assertEqual(self.window.yaml_values[name], document[GAME][name])
        self.assertIn(source.name, self.window.yaml_import_note.cget("text"))
        self.assertTrue(self.window.yaml_details_button.grid_info())
        target, saved = self.save_copy()
        self.assertEqual(saved, document)
        self.assertEqual(source.read_bytes(), original)
        self.assertNotEqual(source, target)
        dialog = self.fixture.dialogs.calls[-1][1]
        self.assertEqual(dialog["initialdir"], str(source.parent))
        self.assertEqual(dialog["initialfile"], source.stem + "-modified.yaml")
        self.assertFalse(self.fixture.service.calls, "editing YAML must not install or launch a game")

    def test_editing_deathlink_preserves_weights_unknowns_and_all_other_imported_options(self):
        document = self.player({
            "shuffle_shops": "random",
            "enemy_health": {"100": 3, "200": 1},
            "bridge": {"vanilla": 2, "dungeons": 1},
            "starting_items": ["bow"],
            "future_community_setting": {"normal": 3, "hard": 1},
        })
        source = self.import_player(document)
        original = source.read_bytes()
        self.window.settings_button.invoke()
        editor = self.window.settings_window
        self.assertTrue(editor.preserve_unchanged)
        self.assertTrue({"shuffle_shops", "enemy_health", "bridge"}.issubset(editor.preserved_options))
        self.assertNotIn("future_community_setting", editor.controls)
        editor.variables["death_link"].set(True)
        editor.apply_button.invoke()
        self.assertEqual(self.window.yaml_changed_keys, {"death_link"})
        self.window.open_settings()
        reopened = self.window.settings_window
        self.assertTrue(reopened.variables["death_link"].get())
        self.assertIn("shuffle_shops", reopened.preserved_options)
        reopened.apply()
        self.assertEqual(self.window.yaml_changed_keys, {"death_link"})
        target, saved = self.save_copy()
        expected = copy.deepcopy(document)
        expected[GAME]["death_link"] = True
        self.assertEqual(saved, expected)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(target.parent, source.parent)

    def test_replace_opaque_choice_at_default_is_saved_and_not_protected_again(self):
        document = self.player({"shuffle_shops": "random"})
        source = self.import_player(document)
        original = source.read_bytes()
        self.window.open_settings()
        editor = self.window.settings_window
        editor.replace_buttons["shuffle_shops"].invoke()
        editor.apply()
        self.assertEqual(self.window.yaml_values["shuffle_shops"], default_options()["shuffle_shops"])
        self.assertEqual(self.window.yaml_changed_keys, {"shuffle_shops"})
        self.window.open_settings()
        self.assertNotIn("shuffle_shops", self.window.settings_window.preserved_options)
        self.window.settings_window.close()
        _target, saved = self.save_copy()
        expected = copy.deepcopy(document)
        expected[GAME]["shuffle_shops"] = "off"
        self.assertEqual(saved, expected)
        self.assertEqual(source.read_bytes(), original)

    def test_cancelled_dialog_and_failed_import_keep_the_current_draft(self):
        self.import_player(self.player({"enemy_health": 200}))
        self.window.player_name.set("My next game")
        self.window.yaml_values["death_link"] = True
        self.window.yaml_changed_keys.add("death_link")
        before = self.snapshot()
        self.fixture.dialogs.open = ""
        self.window.import_yaml()
        self.assertFalse(self.window.busy)
        self.assertEqual(self.snapshot(), before)
        broken = self.fixture.base / "broken.yaml"
        broken.write_text("game: [secret malformed input", encoding="utf-8")
        self.fixture.dialogs.open = str(broken)
        self.window.import_yaml_button.invoke()
        self.fixture.pump(lambda: not self.window.busy)
        self.assertEqual(self.window.status_key, "yaml_import_failed")
        self.assertEqual(self.snapshot(), before)
        self.assertNotIn("secret", self.window.status.cget("text"))
        self.assertEqual(self.window.progress_text, self.window._text("yaml_error_syntax"))

    def test_cancelled_background_import_does_not_replace_the_draft(self):
        self.import_player(self.player({"enemy_health": 200}))
        before = self.snapshot()
        source = self.write_player(self.player({"death_link": True}, name="Other player"), "other.yaml")
        imported = load_yaml(source)
        started, release = threading.Event(), threading.Event()

        def slow_load(_source):
            started.set()
            release.wait(3)
            return imported

        self.fixture.dialogs.open = str(source)
        with patch("ootrr_triforce.yaml_import.load_yaml", side_effect=slow_load):
            try:
                self.window.import_yaml()
                self.fixture.pump(started.is_set)
                self.window.cancel()
            finally:
                release.set()
            self.fixture.pump(lambda: not self.window.busy)
        self.assertEqual(self.window.status_key, "cancelled")
        self.assertEqual(self.snapshot(), before)

    def test_declining_older_setting_conversion_preserves_existing_settings_and_editor(self):
        self.import_player(self.player({"enemy_health": 200}))
        self.window.open_settings()
        editor = self.window.settings_window
        before = self.snapshot()
        source = self.write_player(self.player({"kokiri_shop_checks": True}), "older.yaml")
        self.fixture.dialogs.open = str(source)
        with patch("ootrr_triforce.app_window.messagebox.askyesno", return_value=False) as confirm:
            self.window.import_yaml()
            self.fixture.pump(lambda: not self.window.busy)
        confirm.assert_called_once()
        self.assertEqual(self.window.status_key, "cancelled")
        self.assertEqual(self.snapshot(), before)
        self.assertIs(self.window.settings_window, editor)
        self.assertFalse(editor.closed)

    def test_new_configuration_clears_import_state_and_closes_the_previous_editor(self):
        source = self.import_player(self.player({"shuffle_shops": "random", "death_link": True}))
        original = source.read_bytes()
        self.window.open_settings()
        editor = self.window.settings_window
        editor.variables["shops_always_open"].set(True)
        self.window.new_yaml_button.invoke()
        self.assertTrue(editor.closed)
        self.assertIsNone(self.window.yaml_imported)
        self.assertIsNone(self.window.yaml_source)
        self.assertEqual(self.window.yaml_values, default_options())
        self.assertEqual(self.window.yaml_changed_keys, set())
        self.assertEqual(self.window.player_name.get(), "Link")
        self.assertFalse(self.window.yaml_details_button.grid_info())
        self.assertEqual(self.window.status_key, "yaml_new")
        self.window.open_settings()
        self.assertIsNot(self.window.settings_window, editor)
        self.assertFalse(self.window.settings_window.preserve_unchanged)
        self.window.settings_window.close()
        self.assertEqual(source.read_bytes(), original)

    def test_invalid_imported_value_blocks_save_without_misreporting_a_player_name_error(self):
        source = self.import_player(self.player({"shuffle_skulltulas": "nonsense"}))
        original = source.read_bytes()
        self.assertIn("shuffle_skulltulas", self.window.yaml_imported.invalid_options)
        with patch("ootrr_triforce.app_window.messagebox.showinfo") as details:
            self.window.yaml_details_button.invoke()
        marked = self.window._text("yaml_notice_invalid", settings=setting_label("shuffle_skulltulas", self.window.language))
        self.assertIn(marked, details.call_args.args[1])
        target = self.fixture.base / "must-not-be-created.yaml"
        self.fixture.dialogs.save = str(target)
        dialog_count = len(self.fixture.dialogs.calls)
        self.window.save_yaml_button.invoke()
        self.assertFalse(self.window.busy)
        self.assertEqual(self.window.status_key, "yaml_import_failed")
        self.assertNotEqual(self.window.status_key, "yaml_name_error")
        self.assertEqual(self.window.progress_text, self.window._text("yaml_error_settings"))
        self.assertEqual(len(self.fixture.dialogs.calls), dialog_count, "invalid settings must be reviewed before choosing an output file")
        self.assertFalse(target.exists())
        self.assertEqual(source.read_bytes(), original)

    def test_successful_second_import_closes_the_previous_editor_and_discards_its_pending_choices(self):
        first = self.import_player(self.player({"enemy_health": 200}))
        first_bytes = first.read_bytes()
        self.window.yaml_values["death_link"] = True
        self.window.yaml_changed_keys.add("death_link")
        self.window.open_settings()
        previous = self.window.settings_window
        previous.variables["starting_hearts"].set("7")
        second_document = self.player({"shops_always_open": True}, name="Second save")
        second = self.import_player(second_document, "second-player.yaml")
        self.assertTrue(previous.closed)
        self.assertEqual(self.window.yaml_source, second)
        self.assertEqual(self.window.player_name.get(), "Second save")
        self.assertEqual(self.window.yaml_changed_keys, set())
        self.assertEqual(self.window.yaml_values["starting_hearts"], default_options()["starting_hearts"])
        self.assertFalse(self.window.yaml_values["death_link"])
        self.assertTrue(self.window.yaml_values["shops_always_open"])
        self.window.open_settings()
        current = self.window.settings_window
        self.assertIsNot(current, previous)
        current.apply_button.invoke()
        self.assertEqual(self.window.yaml_changed_keys, set())
        self.assertEqual(self.window.yaml_imported.document, second_document)
        self.assertEqual(first.read_bytes(), first_bytes)

    def test_import_controls_status_details_and_editor_follow_both_interface_languages(self):
        document = self.player({"shuffle_shops": "random", "future_community_setting": 1})
        labels = []
        for language in ("en", "fr"):
            with self.subTest(language=language):
                self.window.language = language
                self.window._render()
                self.assertEqual(self.window.import_yaml_button.cget("text"), self.window._text("import_yaml"))
                self.assertEqual(self.window.new_yaml_button.cget("text"), self.window._text("new_yaml"))
                labels.append(self.window.import_yaml_button.cget("text"))
                self.import_player(document)
                self.assertEqual(self.window.status.cget("text"), self.window._text("yaml_imported"))
                self.assertEqual(self.window.yaml_preview.cget("text"), self.window._text("yaml_preserved_preview"))
                with patch("ootrr_triforce.app_window.messagebox.showinfo") as details:
                    self.window.yaml_details_button.invoke()
                details.assert_called_once()
                self.assertEqual(details.call_args.args[0], self.window._text("yaml_import_details"))
                self.assertIn(self.window._text("yaml_details_original"), details.call_args.args[1])
                self.window.open_settings()
                editor = self.window.settings_window
                self.assertEqual(editor.language, language)
                self.assertEqual(editor.replace_buttons["shuffle_shops"].cget("text"),
                                 "Modifier" if language == "fr" else "Replace")
                editor.close()
        self.assertNotEqual(labels[0], labels[1])


if __name__ == "__main__":
    unittest.main()
