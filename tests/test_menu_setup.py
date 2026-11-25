"""The renderer adapter patches known hooks atomically and preserves user input."""
import hashlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.menu_setup import MARK, _edits, _edits_080, patch_renderer


def fixture(newline="\n"):
    source = (ROOT / "tests/fixtures/triforce-menu-source.cpp").read_text(encoding="utf-8")
    return source.replace("\n", newline).encode("utf-8")


def newer_fixture(newline="\n"):
    # The two changed dispatch excerpts in Triforce v0.7.0, renderer SHA256
    # 906be96311660308285ea8456d360fec1a44e73e1e9b9486975dd78b3db7a5e6.
    # The surrounding fixture is synthetic; no full host renderer is supplied.
    source = fixture().decode("utf-8")
    source = source.replace(
        "    else if (page == kModsPage) draw_mods(k);\n    else draw_options(k);",
        "    else if (page == kModsPage) draw_mods(k);\n"
        "    else if (page == kAchPage) draw_achievements(k);   // ((Triforce) the System tab's Achievements)\n"
        "    else draw_options(k);")
    source = source.replace(
        "        mods_tick(press, tab_left, tab_right, mouse, moved, ptr, mx, my, changed);",
        "        if (mods_screen.ready(prof_now())) mods_tick(press, tab_left, tab_right, mouse, moved, ptr, mx, my, changed);")
    return source.replace("\n", newline).encode("utf-8")


def v080_fixture(newline="\n"):
    # Synthetic excerpts for v0.8.0, renderer SHA256
    # 8adb02daac6d2cb520dff73b3a1997c4e00b89e202611045c069e1e14cc80b53.
    source = newer_fixture().decode("utf-8")
    source = source.replace("int scrolled_to[TAB_MOTION + 2] = {-1, -1, -1, -1, -1, -1, -1, -1};",
                            "int scrolled_to[TAB_SIM_TURF + 1] = {-1, -1, -1, -1, -1, -1, -1, -1, -1, -1};")
    source = source.replace('static_assert(TAB_MOTION + 2 == 8, "scrolled_to:',
                            'static_assert(TAB_SIM_TURF + 1 == 10, "scrolled_to:')
    source = source.replace(
        '{"Display", "Graphics", "Audio", "Controls", "System", "Debug"}',
        'static const char* const ours[TAB_COUNT] = {"Display", "Graphics", "Audio", "Controls", "System", "Debug"};\n'
        'static const char* const names[TAB_COUNT] = {"Display", "Graphics", "Audio", "Controls", "System", "Debug"};')
    source = source.replace(
        "int menu_text_wanted() { return mods_text_wanted.load(std::memory_order_relaxed) ? 1 : 0; }",
        "int menu_text_wanted() {   // ((Triforce) the Mods screen's search; the Output width and height rows' digits)\n"
        "    return mods_text_wanted.load(std::memory_order_relaxed) || size_text_wanted.load(std::memory_order_relaxed) ? 1 : 0;\n}")
    source = source.replace(
        "        std::lock_guard<std::mutex> g(mods_typed_mu);\n        mods_typed.clear();",
        "        std::lock_guard<std::mutex> g(mods_typed_mu);\n"
        "        // ((Triforce) but the Output width and height rows' digits, while one of them is selected: size_edit)\n"
        "        if (size_text_wanted.load(std::memory_order_relaxed) && size_typed.size() < 64)\n"
        "            size_typed.insert(size_typed.end(), mods_typed.begin(), mods_typed.end());\n"
        "        mods_typed.clear();")
    source += "\n" + "\n".join((
        "TAB_MOTION = TAB_COUNT,", "TAB_PAGE = TAB_MOTION + 1,", "TAB_N64 = TAB_PAGE + 1,",
        "TAB_SIM_TURF = TAB_N64 + 1,", "TAB_HIDDEN = TAB_SIM_TURF + 1,",
        "int tab_selected[TAB_SIM_TURF + 1] = {};", "float scroll_at[TAB_SIM_TURF + 1];",
        "int wheel_rows[TAB_SIM_TURF + 1];", "float scroll_want[TAB_SIM_TURF + 1];",
        'static const char* const tabs[] = {"display", "graphics", "audio", "controls", "system", "debug", "motion", "controls",\n'
        '                                       "graphics", "graphics", "hidden"};',
        "const bool tuning = tune_mode && page == 0 && !embed_open && !row;",
        "else if (tuning) draw_tune_bar(k);",
        "if (press[5] && cur_tab == TAB_N64) cur_tab = TAB_GRAPHICS;",
        "if (press[5] && cur_tab == TAB_SIM_TURF) cur_tab = TAB_GRAPHICS;",
        "size_text_wanted.store(size_row, std::memory_order_relaxed);")) + "\n"
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

    def test_published_v1_renderer_patch_remains_byte_identical(self):
        # Generated by the published 0.9.0-alpha.1 adapter, before the fix.
        changed = patch_renderer(fixture())
        self.assertEqual(hashlib.sha256(changed).hexdigest(),
                         "c0427733e23df0566f3279bcad3093bbae5f0c7edb2713cb5b6c978ac7eb4194")
        self.assertEqual(patch_renderer(changed), changed)

    def test_new_host_pages_and_mods_input_transition_are_preserved(self):
        for newline in ("\n", "\r\n"):
            original = newer_fixture(newline)
            with self.subTest(newline=repr(newline)):
                changed = patch_renderer(original)
                self.assertEqual(patch_renderer(changed), changed)
                text = changed.decode("utf-8").replace("\r\n", "\n")
                self.assertIn("else if (page == kAchPage) draw_achievements(k);", text)
                self.assertLess(text.index("else if (page == kAchPage)"),
                                text.index("else if (cur_tab == TAB_ARCHIPELAGO)"))
                self.assertIn("if (mods_screen.ready(prof_now())) mods_tick(press", text)
                # Removing exactly our declared additions must recover every
                # original byte, including native transition conditions.
                restored = text
                for before, after in reversed(_edits()):
                    self.assertEqual(restored.count(after), 1)
                    restored = restored.replace(after, before, 1)
                self.assertEqual(restored.replace("\n", newline).encode("utf-8"), original)

    def test_new_renderer_still_rejects_ambiguous_or_missing_insertion_points(self):
        original = newer_fixture()
        for hook in (b"    else draw_options(k);", b"    } else if (open_now.load()) {"):
            with self.subTest(hook=hook), self.assertRaises(ValueError):
                patch_renderer(original + b"\n" + hook)
            with self.subTest(missing=hook), self.assertRaises(ValueError):
                patch_renderer(original.replace(hook, b"/* changed upstream */", 1))

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

    def test_v080_preserves_extra_pages_size_input_and_tuning_bar(self):
        for newline in ("\n", "\r\n"):
            with self.subTest(newline=repr(newline)):
                original = v080_fixture(newline)
                changed = patch_renderer(original)
                self.assertEqual(patch_renderer(changed), changed)
                text = changed.decode("utf-8").replace("\r\n", "\n")
                self.assertEqual(text.count(MARK), 1)
                self.assertEqual(text.count('"System", "Archipelago", "Debug"'), 2)
                self.assertIn('TAB_SIM_TURF + 1 == 11', text)
                self.assertIn('"system", "archipelago", "debug", "motion", "controls"', text)
                self.assertIn("size_text_wanted.store(size_row, std::memory_order_relaxed);", text)
                self.assertIn("else if (tuning) draw_tune_bar(k);", text)
                self.assertIn("!row && cur_tab != TAB_ARCHIPELAGO;", text)
                self.assertIn("if (press[5] && cur_tab == TAB_SIM_TURF) cur_tab = TAB_GRAPHICS;", text)
                self.assertIn("if (mods_screen.ready(prof_now())) mods_tick(press", text)
                self.assertLess(text.index("else if (page == kAchPage)"),
                                text.index("else if (cur_tab == TAB_ARCHIPELAGO)"))
                restored = text
                for before, after in reversed(_edits_080()):
                    self.assertEqual(restored.count(after), 1)
                    restored = restored.replace(after, before, 1)
                self.assertEqual(restored.replace("\n", newline).encode("utf-8"), original)
                if newline == "\r\n":
                    self.assertNotIn(b"\n", changed.replace(b"\r\n", b""))

    def test_v080_rejects_each_missing_ambiguous_or_tampered_hook(self):
        original = v080_fixture()
        patched = patch_renderer(original)
        for before, after in _edits_080():
            with self.subTest(hook=before[:65]):
                with self.assertRaises(ValueError):
                    patch_renderer(original.replace(before.encode(), b"/* changed upstream */", 1))
                with self.assertRaises(ValueError):
                    patch_renderer(original + before.encode())
                with self.assertRaises(ValueError):
                    patch_renderer(patched.replace(after.encode(), b"/* damaged AP hook */", 1))


if __name__ == "__main__":
    unittest.main()
