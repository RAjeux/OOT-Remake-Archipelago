"""Check downloaded-tool transactions and frozen external-process isolation."""
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client'))
from ootrr_triforce import app_runtime as runtime


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def tool_archive(extra=None):
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        for name in ('LICENSE', 'NOTICE', 'ootrr.exe', 'portable.txt', 'README.md'):
            archive.writestr(runtime.BUILDER_FOLDER + '/' + name, b'new builder' if name == 'ootrr.exe' else b'notice')
        if extra:
            archive.writestr(extra, b'escape')
    return output.getvalue()


class AppRuntimeTests(unittest.TestCase):
    def test_failed_download_never_replaces_an_existing_tool(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = base / 'tools' / runtime.BUILDER_FOLDER
            target.mkdir(parents=True)
            (target / 'ootrr.exe').write_bytes(b'old builder')
            (target / 'user-note.txt').write_bytes(b'keep me')
            with patch.object(runtime.urllib.request, 'urlopen', return_value=BytesIO(b'invalid archive')):
                with self.assertRaises(ValueError):
                    runtime.ensure_builder(base)
            self.assertEqual((target / 'ootrr.exe').read_bytes(), b'old builder')
            self.assertEqual((target / 'user-note.txt').read_bytes(), b'keep me')

    def test_successful_download_keeps_old_tool_and_reuses_cache_offline(self):
        raw = tool_archive()
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = base / 'tools' / runtime.BUILDER_FOLDER
            target.mkdir(parents=True)
            (target / 'ootrr.exe').write_bytes(b'old builder')
            with patch.object(runtime, 'BUILDER_ZIP_SHA256', digest(raw)), \
                 patch.object(runtime, 'BUILDER_SHA256', digest(b'new builder')), \
                 patch('ootrr_triforce.builder.validate_builder') as validate, \
                 patch.object(runtime.urllib.request, 'urlopen', return_value=BytesIO(raw)) as download:
                tool = runtime.ensure_builder(base)
                self.assertEqual(tool.read_bytes(), b'new builder')
                old, = target.parent.glob(runtime.BUILDER_FOLDER + '-before-*')
                self.assertEqual((old / 'ootrr.exe').read_bytes(), b'old builder')
                download.side_effect = AssertionError('Cache reuse must be offline')
                self.assertEqual(runtime.ensure_builder(base), tool)
                self.assertEqual(download.call_count, 1)
                self.assertEqual(validate.call_count, 2)

    def test_cancelled_download_preserves_original(self):
        cancel = threading.Event()
        class Response(BytesIO):
            def read(self, *args):
                cancel.set()
                return super().read(*args)
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = base / 'tools' / runtime.BUILDER_FOLDER
            target.mkdir(parents=True)
            (target / 'ootrr.exe').write_bytes(b'old')
            with patch.object(runtime.urllib.request, 'urlopen', return_value=Response(b'download')):
                with self.assertRaises(InterruptedError):
                    runtime.ensure_builder(base, cancel=cancel)
            self.assertEqual((target / 'ootrr.exe').read_bytes(), b'old')

    def test_tool_archive_cannot_write_outside_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage = root / 'stage'
            stage.mkdir()
            raw = tool_archive(runtime.BUILDER_FOLDER + '/../../escaped')
            with self.assertRaises(ValueError):
                runtime._extract_builder(BytesIO(raw), stage)
            self.assertFalse((root / 'escaped').exists())

    def test_real_child_does_not_inherit_frozen_python_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory)
            environment = dict(os.environ, PYTHONHOME=str(bundle / 'wrong-python'),
                               PYTHONPATH=str(bundle / 'wrong-modules'), TCL_LIBRARY=str(bundle / 'tcl'),
                               PATH=str(bundle) + os.pathsep + os.environ.get('PATH', ''))
            with patch.object(sys, 'frozen', True, create=True), patch.object(sys, '_MEIPASS', str(bundle), create=True):
                result = runtime.run_process([sys.executable, '-c',
                    "import json,os;print(json.dumps({k:os.environ.get(k) for k in ['PYTHONHOME','PYTHONPATH','TCL_LIBRARY','PATH']}))"],
                    env=environment, capture_output=True, text=True, check=True)
            state = json.loads(result.stdout)
            self.assertIsNone(state['PYTHONHOME'])
            self.assertIsNone(state['PYTHONPATH'])
            self.assertIsNone(state['TCL_LIBRARY'])
            self.assertNotIn(str(bundle), state['PATH'].split(os.pathsep))

    def test_frozen_process_timeout_and_failure_are_reported(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(sys, 'frozen', True, create=True), \
             patch.object(sys, '_MEIPASS', directory, create=True):
            with self.assertRaises(subprocess.CalledProcessError) as failure:
                runtime.run_process([sys.executable, '-c', 'raise SystemExit(4)'], capture_output=True, check=True)
            self.assertEqual(failure.exception.returncode, 4)
            with self.assertRaises(subprocess.TimeoutExpired):
                runtime.run_process([sys.executable, '-c', 'import time;time.sleep(5)'], capture_output=True, timeout=.1)

    def test_install_world_keeps_previous_and_persists_its_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle, base, archipelago = root / 'bundle', root / 'user', root / 'archipelago'
            node = bundle / 'runtime/node'
            node.mkdir(parents=True)
            (node / 'node.exe').write_bytes(b'node-runtime')
            (node / 'LICENSE').write_bytes(b'node-license')
            with ZipFile(bundle / 'ootrr_remake.apworld', 'w') as archive:
                archive.writestr('ootrr_remake/__init__.py', '# world')
            (archipelago / 'custom_worlds').mkdir(parents=True)
            (archipelago / 'ArchipelagoGenerate.exe').touch()
            previous = archipelago / 'custom_worlds/ootrr_remake.apworld'
            previous.write_bytes(b'previous-world')
            with patch.object(runtime, 'resource_root', return_value=bundle), \
                 patch.object(runtime, 'NODE_SHA256', digest(b'node-runtime')):
                installed = runtime.install_apworld(archipelago, base=base)
            self.assertEqual(installed.read_bytes(), (bundle / 'ootrr_remake.apworld').read_bytes())
            backup, = (base / 'backups/apworld').glob('*.apworld')
            self.assertEqual(backup.read_bytes(), b'previous-world')
            with patch.object(runtime, 'resource_root', return_value=root / 'closed-app'), patch.dict(os.environ):
                # This case exercises the persistent fallback, independently
                # of a developer's intentionally higher-priority Node override.
                os.environ.pop('OOTRR_NODE', None)
                persistent = Path(runtime.bundled_node(base=base))
                self.assertEqual(persistent.read_bytes(), b'node-runtime')
                self.assertEqual((persistent.parent / 'LICENSE').read_bytes(), b'node-license')


if __name__ == '__main__':
    unittest.main()
