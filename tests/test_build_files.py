"""Repeat packaging without rewriting an identical runtime DLL in use."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_build_files', ROOT / 'tools/build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class CopyFilesTests(unittest.TestCase):
    def test_identical_runtime_is_not_reopened_for_writing_when_another_process_uses_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / 'bundled.dll', root / 'runtime.dll'
            source.write_bytes(b'identical runtime')
            destination.write_bytes(source.read_bytes())
            with patch.object(build.shutil, 'copyfile', side_effect=PermissionError('DLL is loaded')) as copy:
                build.copy_file(source, destination)
                copy.assert_not_called()
            self.assertEqual(destination.read_bytes(), source.read_bytes())

    def test_different_locked_runtime_still_fails_without_hiding_the_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / 'bundled.dll', root / 'runtime.dll'
            source.write_bytes(b'new runtime')
            destination.write_bytes(b'previous runtime')
            with patch.object(build.shutil, 'copyfile', side_effect=PermissionError('DLL is loaded')):
                with self.assertRaises(PermissionError):
                    build.copy_file(source, destination)
            self.assertEqual(destination.read_bytes(), b'previous runtime')


if __name__ == '__main__':
    unittest.main()
