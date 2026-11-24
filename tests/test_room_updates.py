"""Known old resource bugs require same-room preparation, not a new seed."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client'))
from ootrr_triforce.room_updates import requires_reprepare


class RoomUpdateTests(unittest.TestCase):
    def test_legacy_missing_and_current_rooms_are_distinguished_without_writes(self):
        with tempfile.TemporaryDirectory(prefix='ap-room-version-') as temporary:
            root = Path(temporary)
            self.assertFalse(requires_reprepare(root))
            marker = root / 'manifest.json'
            legacy = {'archipelago': {'generation_mode': 'legacy'}}
            marker.write_text(json.dumps(legacy), encoding='utf-8')
            self.assertFalse(requires_reprepare(root, external=True))
            full = {'archipelago': {'generation_mode': 'full_network'}}
            marker.write_text(json.dumps(full), encoding='utf-8')
            before = marker.read_bytes()
            self.assertTrue(requires_reprepare(root))
            self.assertEqual(marker.read_bytes(), before)
            full['resource_allocations'] = {'version': 1}
            marker.write_text(json.dumps(full), encoding='utf-8')
            self.assertTrue(requires_reprepare(root))
            full['native_player_brain'] = {'version': 1}
            marker.write_text(json.dumps(full), encoding='utf-8')
            self.assertFalse(requires_reprepare(root))
            self.assertTrue(requires_reprepare(root, external=True))
            full.update(external_readiness={'version': 2}, external_deathlink={'version': 1, 'enabled': False})
            marker.write_text(json.dumps(full), encoding='utf-8')
            self.assertFalse(requires_reprepare(root, external=True))
            full['external_readiness']['version'] = 1
            marker.write_text(json.dumps(full), encoding='utf-8')
            self.assertTrue(requires_reprepare(root, external=True))

    def test_native_brain_marker_never_substitutes_for_external_runtime_guards(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value = {'archipelago': {'generation_mode': 'full_network'},
                     'resource_allocations': {'version': 1},
                     'native_player_brain': {'version': 1}}
            (root / 'manifest.json').write_text(json.dumps(value), encoding='utf8')
            self.assertFalse(requires_reprepare(root))
            self.assertTrue(requires_reprepare(root, external=True))

    def test_broken_full_marker_is_not_silently_treated_as_legacy(self):
        with tempfile.TemporaryDirectory(prefix='ap-room-version-') as temporary:
            root = Path(temporary)
            (root / 'full-player.json').write_bytes(b'{}')
            self.assertTrue(requires_reprepare(root))
            (root / 'manifest.json').write_bytes(b'{broken')
            self.assertTrue(requires_reprepare(root))


if __name__ == '__main__':
    unittest.main()
