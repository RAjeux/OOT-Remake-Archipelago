"""Hookshot patches fail closed and keep host/profile/cache identities separate."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce import hookshot_setup as setup

REAL = Path(os.environ.get("HOOKSHOT_TOOLS") or setup.discover().get("native_tools") or ".")


class HookshotTests(unittest.TestCase):
    def test_profile_override_and_manual_start_fallback_never_use_triforce_profiles(self):
        original = (ROOT / "native/ootrr_archipelago.inc").read_bytes()
        changed = setup.isolated_bridge(original)
        self.assertIn(b'OOTRR_AP_BASE', changed)
        self.assertIn(b'OOTRR-Archipelago\\\\hosts\\\\hookshot', changed)
        self.assertNotEqual(changed, original)
        self.assertEqual((ROOT / "native/ootrr_archipelago.inc").read_bytes(), original)
        with self.assertRaises(setup.HookshotError):
            setup.isolated_bridge(original.replace(b'LOCALAPPDATA', b'unknown'))

    def test_unknown_sources_are_rejected_before_any_output_is_created(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "untouched"
            with self.assertRaises(setup.HookshotError):
                setup.install_tools(base, configured=Path(temporary) / "unknown")
            self.assertFalse(base.exists())
        for function in (setup.patch_source, setup.patch_renderer):
            with self.assertRaises(setup.HookshotError):
                function(b"unrecognized host sources")

    def test_patch_algorithm_revision_gets_a_new_private_cache_without_overwriting_the_old_one(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, base = Path(temporary) / "source", Path(temporary) / "profiles"
            (source / "host").mkdir(parents=True)
            (source / "gpu/vk").mkdir(parents=True)
            host, menu = b"original host", b"original renderer"
            (source / "host/hos_main.c").write_bytes(host)
            (source / "gpu/vk/vk_menu.cpp").write_bytes(menu)
            (source / "gpu/vk/vk_menu_i18n.cpp").write_bytes(b"original translations")
            (source / "version.txt").write_text("v3.0.1")
            with patch.object(setup,"HOST_SHA",hashlib.sha256(host).hexdigest()), \
                 patch.object(setup,"MENU_SHA",hashlib.sha256(menu).hexdigest()), \
                 patch.object(setup,"_bundle",return_value=ROOT/"native"), \
                 patch.object(setup,"patch_source",return_value=b"patched revision one") as modify, \
                 patch.object(setup,"patch_renderer",return_value=b"patched renderer"), \
                 patch.object(setup,"patch_i18n",return_value=b"patched translations"):
                first = setup.install_tools(base, configured=source)
                self.assertEqual(setup.install_tools(base, configured=source), first)
                modify.return_value = b"patched revision two"
                second = setup.install_tools(base, configured=source)
                relocated = Path(temporary) / "moved-source"
                shutil.copytree(source,relocated)
                third = setup.install_tools(base,configured=relocated)
                self.assertNotEqual(third,second)
                self.assertEqual(json.loads((third/setup.METADATA).read_bytes())["source"],str(relocated))
            self.assertNotEqual(first, second)
            self.assertEqual((first / "host/hos_main.c").read_bytes(), b"patched revision one")
            self.assertEqual((second / "host/hos_main.c").read_bytes(), b"patched revision two")
            self.assertEqual((source / "host/hos_main.c").read_bytes(), host)

    @unittest.skipUnless((REAL / "host/hos_main.c").is_file(), "Hookshot 3.0.1 source tools needed")
    def test_actual_source_patches_are_idempotent_and_password_field_is_masked(self):
        for relative, function in (("host/hos_main.c",setup.patch_source),("gpu/vk/vk_menu.cpp",setup.patch_renderer)):
            original = (REAL / relative).read_bytes()
            changed = function(original)
            self.assertNotEqual(changed, original)
            self.assertEqual(function(changed), changed)
            self.assertEqual((REAL / relative).read_bytes(), original)
        changed = setup.patch_renderer((REAL / "gpu/vk/vk_menu.cpp").read_bytes())
        self.assertIn(b"TextField masked=", changed)
        self.assertIn(b"memset(edit_kept,0,sizeof edit_kept)", changed)
        self.assertIn(b"hookshot_ap::dirty=true", changed)
        self.assertIn(b"sizeof TextField::text", changed)
        for line in changed.decode().splitlines():
            if '{TAB_GAMEPLAY, "AP ' in line:
                self.assertTrue(line.endswith('nullptr, false, true},'),line)

    def test_actual_native_menu_include_handles_desktop_refresh_edit_errors_and_password_erasure(self):
        compiler = (os.environ.get("CXX") or shutil.which("clang++") or shutil.which("g++"))
        local = REAL / "llvm-mingw/bin/x86_64-w64-mingw32-clang++.exe"
        if not compiler and local.is_file():
            compiler = str(local)
        if not compiler:
            self.skipTest("A C++ compiler is needed for the actual menu-state helper")
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / ("menu.exe" if os.name == "nt" else "menu")
            command = [compiler,"-std=c++17",*( ["-static"] if os.name == "nt" else []),"-I",str(ROOT/"native"),
                       str(ROOT/"tests/fixtures/hookshot-menu-model.cpp"),"-o",str(executable)]
            result = subprocess.run(command,capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            result = subprocess.run([str(executable)],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__ == "__main__":
    unittest.main()
