"""Review rich release text and small-screen actions without update I/O."""
from pathlib import Path
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.ui_theme import COLORS
from ootrr_triforce.update_window import UpdateWindow


class UpdateWindowPresentationTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        self.window = None
        self.release = dict(current_version="0.10.2-alpha.1", latest_version="0.10.2-alpha.2",
                            release_url="https://github.com/RAjeux/OOT-Remake-Archipelago/releases", can_install=True,
                            notes="Native item fixes.\n\nRead more: https://example.com/release\n")

    def tearDown(self):
        if self.window and not self.window.closed:
            self.window.close()
        elif not self.window:
            self.root.destroy()

    def test_release_notes_are_readonly_selectable_and_links_do_not_open_automatically(self):
        with patch("ootrr_triforce.update_window.webbrowser.open") as open_page:
            self.window = UpdateWindow(self.root, self.release)
            self.root.update_idletasks()
            notes = self.window.notes
            self.assertEqual(notes.get("1.0", "end-1c"), self.release["notes"].strip())
            self.assertEqual(str(notes.cget("state")), "disabled")
            self.assertEqual(notes.cget("background"), COLORS["elevated"])
            self.assertEqual(notes.cget("selectbackground"), COLORS["gold"])
            notes.tag_add("sel", "1.0", "1.6")
            self.assertEqual(notes.get("sel.first", "sel.last"), "Native")
            self.assertTrue(notes.tag_ranges("link"))
            self.assertTrue(notes.tk.call(notes._w, "tag", "bind", "url_0", "<Button-1>"))
            open_page.assert_not_called()
            self.assertFalse(self.window.want_world.get())

    def test_small_french_window_keeps_update_actions_visible_with_long_release_notes(self):
        self.release["notes"] *= 20
        self.window = UpdateWindow(self.root, self.release, language="fr")
        self.root.geometry("620x560")
        # Mapped geometry is required for actual clipping checks; stay invisible.
        self.root.attributes("-alpha", 0)
        self.root.deiconify()
        self.root.update()
        right = self.root.winfo_rootx() + self.root.winfo_width()
        bottom = self.root.winfo_rooty() + self.root.winfo_height()
        for button in (self.window.release_button, self.window.close_button, self.window.primary):
            self.assertLessEqual(button.winfo_rootx() + button.winfo_width(), right)
            self.assertLessEqual(button.winfo_rooty() + button.winfo_height(), bottom)
        self.assertGreater(self.window.canvas.bbox("all")[3], self.window.canvas.winfo_height())
        self.window.folder.event_generate("<FocusIn>")
        self.root.update()
        viewport_top = self.window.canvas.winfo_rooty()
        viewport_bottom = viewport_top + self.window.canvas.winfo_height()
        self.assertGreaterEqual(self.window.folder.winfo_rooty(), viewport_top)
        self.assertLessEqual(self.window.folder.winfo_rooty() + self.window.folder.winfo_height(), viewport_bottom)
        self.assertFalse(self.window.want_world.get())


if __name__ == "__main__":
    unittest.main()
