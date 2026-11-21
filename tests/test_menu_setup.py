"""The renderer adapter patches known hooks atomically and preserves user input."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.menu_setup import MARK, _edits, patch_renderer


def fixture(newline="\n"):
    source = (ROOT / "tests/fixtures/triforce-menu-source.cpp").read_text(encoding="utf-8")
    return source.replace("\n", newline).encode("utf-8")


class MenuSetupTests(unittest.TestCase):
    def test_complete_patch_is_idempotent_with_both_line_endings(self):
        for newline in ("\n", "\r\n"):
            with self.subTest(newline=repr(newline)):
                changed = patch_renderer(fixture(newline))
                self.assertEqual(patch_renderer(changed), changed)
                text = changed.decode().replace("\r\n", "\n")
                self.assertEqual(text.count(MARK), 1)
                self.assertIn('TAB_ARCHIPELAGO = 5', text)
                self.assertIn('ap_menu_tick(press', text)
                self.assertIn('if (!ap_menu_editing())', text)
                self.assertIn('ap_menu_editing() || (open_now.load()', text)
                if newline == "\r\n":
                    self.assertNotIn(b"\n", changed.replace(b"\r\n", b""))

    def test_each_missing_or_duplicated_hook_is_rejected(self):
        source = fixture()
        for before, after in _edits():
            with self.subTest(hook=before[:55]):
                marker = before.encode()
                with self.assertRaises(ValueError):
                    patch_renderer(source.replace(marker, b"/* upstream changed */", 1))
                with self.assertRaises(ValueError):
                    patch_renderer(source + marker)
                self.assertEqual(source, fixture())

    def test_partial_or_tampered_previous_patch_is_rejected(self):
        patched = patch_renderer(fixture())
        with self.assertRaises(ValueError):
            patch_renderer(patched.replace(b"ap_menu_tick(press", b"changed_tick(press", 1))
        with self.assertRaises(ValueError):
            patch_renderer(fixture() + MARK.encode())


if __name__ == "__main__":
    unittest.main()
