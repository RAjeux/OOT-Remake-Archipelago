"""Read-only directory indexing matches resource paths and rejects changed links."""
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client'))
from ootrr_full.formats.inspect_nup import Nup


class DirectorySourceTests(unittest.TestCase):
    def test_nested_unicode_files_keep_exact_member_names_and_contents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected = {'Pack/Actor/Cow.pack.zs': b'cow', 'Event/épreuve.bfevfl.zs': b'flow'}
            for name, data in expected.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            nup = Nup(root)
            self.assertEqual(set(nup.entries), {'0/romfs/' + name for name in expected})
            for name, data in expected.items():
                self.assertEqual(nup.read(nup.latest('romfs/' + name)), data)
            self.assertEqual({name: (root / name).read_bytes() for name in expected}, expected)

    def symlink(self, target, link, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except OSError as error:
            if directory and os.name == 'nt':
                # Directory junctions need no Windows developer/admin privilege.
                environment = dict(os.environ, OOTRR_TEST_LINK=str(link), OOTRR_TEST_TARGET=str(target))
                result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                                         'New-Item -ItemType Junction -Path $env:OOTRR_TEST_LINK '
                                         '-Target $env:OOTRR_TEST_TARGET -ErrorAction Stop | Out-Null'],
                                        capture_output=True, env=environment,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if result.returncode == 0:
                    return
            self.skipTest('Creating links is unavailable: ' + str(error))

    def test_external_directory_links_are_rejected(self):
        for directory in (True,):
            with tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                root, outside = base / 'game', base / 'outside'
                root.mkdir(); outside.mkdir()
                (outside / 'item').write_bytes(b'outside')
                self.symlink(outside if directory else outside / 'item', root / 'linked', directory)
                with self.assertRaisesRegex(ValueError, 'external link'):
                    Nup(root)

    def test_link_swapped_after_indexing_is_checked_again_on_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / 'game'; root.mkdir()
            folder, outside = root / 'folder', base / 'outside'
            folder.mkdir(); outside.mkdir()
            (folder / 'item').write_bytes(b'original'); (outside / 'item').write_bytes(b'outside')
            nup = Nup(root)
            folder.rename(root / 'old')
            self.symlink(outside, folder, True)
            with self.assertRaisesRegex(ValueError, 'changed during generation'):
                nup.read('0/romfs/folder/item')

    def test_internal_alias_is_supported_and_directory_cycles_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / 'original'; original.mkdir()
            (original / 'item').write_bytes(b'inside')
            self.symlink(original, root / 'alias', True)
            nup = Nup(root)
            self.assertEqual(nup.read('0/romfs/alias/item'), b'inside')
            self.symlink(root, original / 'loop', True)
            with self.assertRaisesRegex(ValueError, 'cycle'):
                Nup(root)


if __name__ == '__main__':
    unittest.main()
