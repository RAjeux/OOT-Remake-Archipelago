"""Real controls export one typed schema, without touching a game or parsing YAML."""
import json
from pathlib import Path
import re
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.app_window import yaml_content
from ootrr_triforce.settings import AP_ONLY, OPTION_SPECS, SPEC_BY_ID, default_options, engine_settings
from ootrr_triforce.settings_labels import (LABELS, choice_label, description, normalize_inactive,
                                           choice_description, selection_summary, setting_label)
from ootrr_triforce.settings_window import SettingsWindow, search_text, window_size


def parsed_values(text):
    return {name: json.loads(value) for name, value in re.findall(r"^  ([a-z_]+): (.+)$", text, re.M)}


class SettingsExportTests(unittest.TestCase):
    def test_search_and_window_sizes_work_on_small_displays(self):
        self.assertEqual(search_text("ÉPÉE, cœur shuffle_skulltulas"), "epee, coeur shuffle skulltulas")
        for width, height in ((1366, 768), (1024, 600), (1920, 1080)):
            actual_width, actual_height = window_size(width, height)
            self.assertLessEqual(actual_width, width - 60)
            self.assertLessEqual(actual_height, height - 100)
    def test_all_controls_have_bilingual_labels_and_help(self):
        self.assertEqual(set(LABELS), set(SPEC_BY_ID))
        for name in SPEC_BY_ID:
            for language in ("en", "fr"):
                self.assertTrue(setting_label(name, language).strip(), name)
                self.assertTrue(description(name, language).strip(), name)
        self.assertIn("Mido", description("open_forest", "en"))
        self.assertIn("Mido", description("open_forest", "fr"))
        self.assertIn("Off and Pieces", description("shuffle_freestanding_items", "en"))
        self.assertIn("Off et Pieces", description("shuffle_freestanding_items", "fr"))

    def test_selected_values_and_language_reach_yaml_without_reinterpreting_game_rules(self):
        values = default_options()
        values.update(death_link=True, shops_always_open=True, starting_hearts=5, open_forest="open",
                      shuffle_shops="random", starting_items=["bow"], skip_cutscenes="story")
        for language in ("en", "fr"):
            rendered = yaml_content('Link "AP"', values, language)
            selected = parsed_values(rendered)
            expected = dict(values, shuffle_shops="random_deals")
            self.assertEqual(selected, expected)
            self.assertEqual(rendered.count("  death_link:"), 1)
            self.assertIn(description("shops_always_open", language).split(".")[0], rendered)
        self.assertIn("Génère une salle", yaml_content("Link", values, "fr"))
        self.assertEqual(default_options()["open_forest"], "closed")
        self.assertEqual(default_options()["skip_cutscenes"], "off")
        self.assertNotIn("shops_always_open", engine_settings(values))
        self.assertIn("shops_always_open", AP_ONLY)

    def test_inactive_children_reset_before_validation_but_leave_active_choices(self):
        values = default_options()
        values.update(shuffle_rewards="off", shuffle_scrubs_a=True, scrub_prices="fixed",
                      scrub_price_fixed=75, shuffle_dungeon_rewards="anywhere", merchant_prices="cheap",
                      shuffle_merchants="all", song_harp_colors=False)
        normalized = normalize_inactive(values)
        for name in ("shuffle_scrubs_a", "scrub_prices", "scrub_price_fixed", "shuffle_dungeon_rewards",
                     "merchant_prices", "shuffle_merchants", "song_harp_colors"):
            self.assertEqual(normalized[name], default_options()[name], name)
        self.assertIs(values["shuffle_scrubs_a"], True, "caller values must stay independent")
        values.update(shuffle_rewards="supported", plant_beans=True, shuffle_songs="anywhere")
        normalized = normalize_inactive(values)
        self.assertEqual(normalized["scrub_price_fixed"], 75)
        self.assertFalse(normalized["song_harp_colors"])


class SettingsWindowTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.editor = None

    def tearDown(self):
        if self.editor and not self.editor.closed:
            self.editor.close()
        self.root.destroy()

    def open(self, **kwargs):
        self.editor = SettingsWindow(self.root, **kwargs)
        self.root.update()
        return self.editor

    def set_choice(self, name, value):
        self.editor.variables[name].set(choice_label(name, value, self.editor.language))

    def test_actual_controls_apply_typed_values_and_disable_dependent_fields(self):
        result = []
        editor = self.open(language="fr", on_apply=result.append)
        self.assertEqual(set(editor.controls), {spec["id"] for spec in OPTION_SPECS})
        self.assertEqual(str(editor.controls["bridge_rewards"].cget("state")), "disabled")
        self.assertIn("Nécessite", editor.reasons["bridge_rewards"].cget("text"))
        self.set_choice("bridge", "dungeons")
        self.assertEqual(str(editor.controls["bridge_rewards"].cget("state")), "normal")
        editor.variables["bridge_rewards"].set("5")
        editor.variables["shops_always_open"].set(True)
        editor.variables["death_link"].set(True)
        self.set_choice("open_forest", "open")
        self.set_choice("skip_cutscenes", "story")
        self.set_choice("shuffle_rewards", "supported")
        editor.variables["shuffle_scrubs_a"].set(True)
        self.set_choice("scrub_prices", "fixed")
        editor.variables["scrub_price_fixed"].set("75")
        self.set_choice("shuffle_rewards", "off")
        self.assertEqual(str(editor.controls["scrub_price_fixed"].cget("state")), "disabled")
        editor.apply_button.invoke()
        self.assertTrue(editor.closed)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["bridge_rewards"], 5)
        self.assertIs(result[0]["death_link"], True)
        self.assertIs(result[0]["shops_always_open"], True)
        self.assertEqual(result[0]["scrub_prices"], "vanilla")
        self.assertEqual(parsed_values(yaml_content("Link", result[0], "fr")), result[0])

    def test_invalid_range_cannot_apply_and_cancel_does_not_modify_caller(self):
        original = default_options()
        result = []
        editor = self.open(values=original, on_apply=result.append)
        editor.variables["enemy_health"].set("101")
        with patch("ootrr_triforce.settings_window.messagebox.showerror") as error:
            editor.apply()
        error.assert_called_once()
        self.assertFalse(editor.closed)
        self.assertEqual(result, [])
        editor.close()
        self.assertEqual(original, default_options())

    def test_starting_equipment_multiple_selection_and_existing_dependencies(self):
        result = []
        editor = self.open(on_apply=result.append)
        items = SPEC_BY_ID["starting_items"]["choices"]
        editor.controls["starting_items"].selection_set(items.index("bombchus"))
        with patch("ootrr_triforce.settings_window.messagebox.showerror") as error:
            editor.apply()
        error.assert_called_once()
        self.assertFalse(result)
        editor.controls["starting_items"].selection_set(items.index("bomb_bag"))
        editor.apply()
        self.assertEqual(result[0]["starting_items"], ["bomb_bag", "bombchus"])

    def test_search_finds_both_languages_ids_and_inactive_advanced_options_without_changing_values(self):
        for language in ("en", "fr"):
            with self.subTest(language=language):
                editor = self.open(language=language)
                original = editor._read_values()
                self.assertNotIn("enemy_health", editor.filtered_names)
                for query, expected in (("gold skulltulas", "shuffle_skulltulas"),
                                        ("médaillons", "bridge"), ("enemy_health", "enemy_health"),
                                        ("bridge_rewards", "bridge_rewards")):
                    editor.search_var.set(query)
                    self.assertIn(expected, editor.visible_names)
                    self.assertIsNone(editor.current_group)
                    self.assertEqual(str(editor.advanced_button.cget("state")), "disabled")
                self.assertEqual(str(editor.controls["bridge_rewards"].cget("state")), "disabled")
                editor.search_var.set("zzzz_no_settings_match_zzzz")
                self.assertEqual(editor.visible_names, [])
                self.assertTrue(editor.empty.grid_info())
                editor._escape()
                self.assertFalse(editor.closed)
                self.assertEqual(editor.current_group, "Shuffle")
                self.assertEqual(editor._read_values(), original)
                editor.close()

    def test_filters_preserve_customized_and_inactive_choices_and_reactivation_restores_them(self):
        original = default_options()
        original["enemy_health"] = 200
        editor = self.open(values=original, language="fr")
        self.assertIn("1 choix personnalisés", editor.filter_note.cget("text"))
        editor.show_advanced.set(True)
        self.assertIn("enemy_health", editor.filtered_names)
        editor.show_advanced.set(False)
        self.assertEqual(editor.selected_values()["enemy_health"], 200)
        self.set_choice("shuffle_rewards", "supported")
        editor.variables["shuffle_scrubs_a"].set(True)
        self.set_choice("scrub_prices", "fixed")
        editor.variables["scrub_price_fixed"].set("75")
        self.set_choice("shuffle_rewards", "off")
        self.assertEqual(editor.variables["scrub_price_fixed"].get(), "75")
        self.assertEqual(editor.selected_values()["scrub_price_fixed"], default_options()["scrub_price_fixed"])
        self.assertNotIn("scrub_price_fixed", editor.filtered_names)
        editor.hide_inactive.set(False)
        self.assertEqual(editor.variables["scrub_price_fixed"].get(), "75")
        self.set_choice("shuffle_rewards", "supported")
        self.assertEqual(editor.selected_values()["scrub_price_fixed"], 75)
        self.assertEqual(str(editor.controls["scrub_price_fixed"].cget("state")), "normal")
        editor.close()
        self.assertEqual(original["enemy_health"], 200)
        self.assertEqual(original["scrub_price_fixed"], default_options()["scrub_price_fixed"])

    def test_empty_filtered_category_explains_how_to_reveal_options(self):
        editor = self.open(language="fr")
        editor._select_group(editor.group_ids.index("Economy"))
        self.assertEqual(editor.visible_names, [])
        self.assertTrue(editor.empty.grid_info())
        self.assertIn("options avancées", editor.empty.cget("text"))
        before = editor.selected_values()
        editor.show_advanced.set(True)
        self.assertTrue(editor.visible_names)
        self.assertFalse(editor.empty.grid_info())
        self.assertEqual(editor.selected_values(), before)

    def test_current_choice_explanation_and_summary_follow_the_actual_draft_in_both_languages(self):
        for language in ("en", "fr"):
            with self.subTest(language=language):
                editor = self.open(language=language)
                before = editor.rows["shuffle_skulltulas"][1].cget("text")
                self.set_choice("shuffle_skulltulas", "matched")
                current = editor.rows["shuffle_skulltulas"][1].cget("text")
                self.assertNotEqual(before, current)
                self.assertEqual(current, choice_description("shuffle_skulltulas", "matched", language))
                self.assertIn("100", current)
                self.assertEqual(editor.summary.cget("text"), "\n".join(selection_summary(editor._read_values(), language)))
                self.assertIn("DeathLink", "\n".join(selection_summary(dict(editor._read_values(), death_link=True), language)))
                editor.close()

    def test_invalid_hidden_active_number_is_revealed_and_inactive_invalid_draft_is_not_exported(self):
        applied = []
        editor = self.open(on_apply=applied.append)
        editor.variables["enemy_health"].set("101")
        with patch("ootrr_triforce.settings_window.messagebox.showerror") as error:
            editor.apply()
        error.assert_called_once()
        self.assertIn("enemy_health", editor.visible_names)
        self.assertTrue(editor.show_advanced.get())
        self.assertFalse(applied)
        editor.variables["enemy_health"].set("200")
        editor.variables["scrub_price_fixed"].set("unfinished number")
        self.assertEqual(editor.selected_values()["scrub_price_fixed"], default_options()["scrub_price_fixed"])
        self.assertEqual(editor.variables["scrub_price_fixed"].get(), "unfinished number")
        editor.variables["enemy_health"].set("101")
        with patch("ootrr_triforce.settings_window.messagebox.showerror"):
            editor.apply()
        self.assertIn("enemy_health", editor.visible_names, "an ignored draft must not steal focus from the actual error")
        editor.variables["enemy_health"].set("200")
        editor.apply()
        self.assertEqual(len(applied), 1)
        self.assertEqual(len(applied[0]), len(OPTION_SPECS))

    def test_combination_errors_reveal_the_named_fix_even_when_the_id_is_inside_the_message(self):
        editor = self.open(language="fr")
        items = SPEC_BY_ID["starting_items"]["choices"]
        editor.controls["starting_items"].selection_set(items.index("bombchus"))
        with patch("ootrr_triforce.settings_window.messagebox.showerror"):
            editor.apply()
        self.assertEqual(editor.current_group, SPEC_BY_ID["starting_items"]["group"])
        self.assertIn("starting_items", editor.visible_names)
        editor.controls["starting_items"].selection_clear(0, tk.END)
        self.set_choice("shuffle_rewards", "supported")
        self.set_choice("shuffle_merchants", "beans")
        with patch("ootrr_triforce.settings_window.messagebox.showerror"):
            editor.apply()
        self.assertEqual(editor.current_group, SPEC_BY_ID["plant_beans"]["group"])
        self.assertIn("plant_beans", editor.visible_names)
        self.assertFalse(editor.closed)

    def test_small_visible_window_keeps_summary_buttons_and_native_mousewheel_behavior(self):
        self.root.deiconify()
        self.root.geometry("1x1+0+0")
        self.root.update()
        with patch("ootrr_triforce.settings_window.window_size", return_value=(964, 500)):
            editor = self.open(language="en")
        editor.window.transient("")
        editor.window.deiconify()
        self.root.update()
        for widget in (editor.summary, editor.apply_button):
            self.assertTrue(widget.winfo_ismapped())
            self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                                 editor.window.winfo_rooty() + editor.window.winfo_height())
        self.assertGreater(editor.canvas.winfo_height(), 60)
        before = editor.selected_values()
        editor.canvas.yview_moveto(0)
        self.root.update()
        editor.controls["shuffle_chests"].event_generate("<MouseWheel>", delta=-120)
        self.root.update()
        self.assertGreater(editor.canvas.yview()[0], 0)
        self.assertEqual(editor.selected_values(), before, "wheel over a closed combo must scroll without editing it")
        editor._select_group(editor.group_ids.index("Starting inventory"))
        self.root.update()
        field = editor.controls["starting_items"]
        field.yview_moveto(0)
        canvas_position = editor.canvas.yview()
        field.event_generate("<MouseWheel>", delta=-120)
        self.root.update()
        self.assertGreater(field.yview()[0], 0)
        self.assertEqual(editor.canvas.yview(), canvas_position)
        self.assertEqual(editor.selected_values(), before)


if __name__ == "__main__":
    unittest.main()
