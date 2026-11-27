"""Exercise the real structured controls, including cancel and draft retention."""
from pathlib import Path
import sys
import tkinter as tk
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))

from ootrr_triforce.settings_labels import choice_label
from ootrr_triforce.settings_window import SettingsWindow


class StructuredSettingsWindowTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.editor = SettingsWindow(self.root, language="fr")
        self.root.update()

    def tearDown(self):
        if hasattr(self, "editor"):
            self.editor.close()
        if hasattr(self, "root"):
            self.root.destroy()

    def test_colour_table_applies_known_parts_and_keeps_inactive_draft(self):
        editor = self.editor
        self.assertEqual(str(editor.controls["cosmetic_colors"].cget("state")), "disabled")
        editor.variables["cosmetic_color_mode"].set(choice_label("cosmetic_color_mode", "custom", "fr"))
        self.assertEqual(str(editor.controls["cosmetic_colors"].cget("state")), "normal")
        dialog = editor._edit_mapping("cosmetic_colors")
        dialog.key_var.set("Tunique Kokiri")
        dialog.value_var.set("#abcdef")
        dialog.add()
        dialog.apply()
        self.assertEqual(editor.selected_values()["cosmetic_colors"], {"kokiri": "#ABCDEF"})
        editor.variables["cosmetic_color_mode"].set(choice_label("cosmetic_color_mode", "random", "fr"))
        self.assertEqual(editor.selected_values()["cosmetic_colors"], {})
        editor.variables["cosmetic_color_mode"].set(choice_label("cosmetic_color_mode", "custom", "fr"))
        self.assertEqual(editor.selected_values()["cosmetic_colors"], {"kokiri": "#ABCDEF"})

    def test_plando_table_rejects_unknown_entries_and_cancel_keeps_parent_unchanged(self):
        editor = self.editor
        dialog = editor._edit_mapping("item_plando")
        dialog.key_var.set("KF Midos Top Left Chest")
        dialog.value_var.set("Unknown Item")
        dialog.add()
        self.assertFalse(dialog.values)
        dialog.value_var.set("Progressive Hookshot")
        dialog.add()
        self.assertEqual(len(dialog.tree.get_children()), 1)
        dialog.close()
        self.assertEqual(editor.selected_values()["item_plando"], {})
        dialog = editor._edit_mapping("item_plando")
        dialog.key_var.set("KF Midos Top Left Chest")
        dialog.value_var.set("Progressive Hookshot")
        dialog.add()
        dialog.apply()
        self.assertEqual(editor.selected_values()["item_plando"], {"KF Midos Top Left Chest": "Progressive Hookshot"})

    def test_medallion_mode_activates_only_its_count(self):
        editor = self.editor
        editor.variables["bridge"].set(choice_label("bridge", "medallions", "fr"))
        self.assertEqual(str(editor.controls["bridge_rewards"].cget("state")), "disabled")
        self.assertEqual(str(editor.controls["bridge_medallions"].cget("state")), "normal")
        editor.variables["bridge_medallions"].set("4")
        self.assertEqual(editor.selected_values()["bridge_medallions"], 4)


if __name__ == "__main__":
    unittest.main()
