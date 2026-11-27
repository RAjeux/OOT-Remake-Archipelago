"""Internal source prototype: pinning, isolation, exact native request contract."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce import hookshot_setup, longshot_setup as setup

SOURCE = Path(os.environ.get("LONGSHOT_TEST_SOURCE", ROOT / "build/longshot-prototype-source-20261127"))


class LongshotTests(unittest.TestCase):
    def test_unknown_source_fails_before_creating_a_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            with self.assertRaises(setup.LongshotError):
                setup.stage_source(base / "missing", base / "output")
            self.assertFalse((base / "output").exists())
        for patch in setup.PATCHES.values():
            with self.assertRaises(setup.LongshotError):
                patch(b"not the audited source")

    def test_shared_bridge_stays_read_only_and_longshot_uses_native_events_only(self):
        path = ROOT / "native/ootrr_archipelago.inc"
        original = path.read_bytes()
        changed = setup.isolated_bridge(original)
        self.assertIn(b"hosts\\\\longshot", changed)
        self.assertIn(b"OOTRR_AP_BASE", changed)
        self.assertIn(b'#include "ootrr_ap_longshot_event.inc"', changed)
        self.assertIn(b"if (!ap_event_mode16 || !ap_cursor16", changed)
        self.assertIn(b"hos_save_dir_chosen()", changed)
        self.assertIn(b"_stricmp(ap_chosen_saves,ap_expected_saves)", changed)
        self.assertNotIn(b"const Ctx saved", changed)
        self.assertNotIn(b"a64_lookup(", changed)
        self.assertEqual(path.read_bytes(), original)

    def test_private_launch_overrides_inherited_host_profile_without_changing_the_input(self):
        previous = {"LONGSHOT_PROFILE": "another profile", "HOS_MODS": "another mod"}
        token = "b" * 64
        env = setup.launch_environment(ROOT / "build/profiles-test", token, ROOT / "build/mods-test", environment=previous)
        self.assertEqual(previous["LONGSHOT_PROFILE"], "another profile")
        self.assertEqual(env["LONGSHOT_PROFILE"], str((ROOT / "build/profiles-test" / token / "user").resolve()))
        self.assertEqual(env["OOTRR_AP_BASE"], str((ROOT / "build/profiles-test").resolve()))
        for invalid in ("../user", "A" * 64, "", "b" * 65):
            with self.assertRaises(setup.LongshotError):
                setup.launch_environment(ROOT, invalid, ROOT, environment={})

    @unittest.skipUnless((SOURCE / "host/hos_main.c").is_file(), "Pinned Longshot source needed")
    def test_actual_clean_source_and_idempotent_menu_game_boot_language_patches(self):
        setup.validate_source(SOURCE)
        for name, patch in setup.PATCHES.items():
            original = (SOURCE / name).read_bytes()
            for raw in (original, original.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")):
                changed = patch(raw)
                self.assertNotEqual(changed, raw, name)
                self.assertEqual(patch(changed), changed, name)
            self.assertEqual((SOURCE / name).read_bytes(), original)
        menu = setup.patch_renderer((SOURCE / "gpu/vk/vk_menu.cpp").read_bytes())
        self.assertIn(b"TextField masked=", menu)
        self.assertIn(b"memset(edit_kept,0,sizeof edit_kept)", menu)
        self.assertNotIn(b'{TAB_GAMEPLAY, "AP ', menu)
        rows = (ROOT / "native/ootrr_ap_longshot_menu.inc").read_bytes()
        self.assertIn(b"MENU_MODULE(archipelago)", rows)
        self.assertEqual(rows.count(b".unsaved=true"), 6)

    def test_actual_native_request_uses_scheduler_calls_and_cleans_constructed_arguments(self):
        tools = Path(hookshot_setup.discover().get("native_tools") or ".")
        known = tools / "llvm-mingw/bin/x86_64-w64-mingw32-clang.exe"
        compiler = os.environ.get("CC") or (str(known) if known.is_file() else None) or shutil.which("cc")
        if not compiler:
            self.skipTest("C compiler required for the actual adapter")
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / ("events.exe" if os.name == "nt" else "events")
            args = [compiler, "-std=c11", "-Wall", "-Werror", "-I", str(ROOT / "native"),
                    str(ROOT / "tests/fixtures/longshot-event-model.c"), "-o", str(binary)]
            built = subprocess.run(args, capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
