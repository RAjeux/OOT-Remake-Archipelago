"""Repair prepared native caches without changing their room or saved progress."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client'))
from ootrr_triforce import full_mod, upgrade_readiness as gate


class ExternalCacheTests(unittest.TestCase):
    def test_external_client_never_reads_or_rewrites_native_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary) / 'not-created'
            with patch('ootrr_triforce.native_player_brain.prepare_native_player_brains',
                       side_effect=AssertionError('External clients must keep their readiness graph')):
                self.assertEqual(full_mod.refresh_native_player_brains(artifact,
                    {'native': False}, {}), ())
            self.assertFalse(artifact.exists())


@unittest.skipUnless(os.environ.get('OOT_NUP'), 'OOT_NUP not set; native resources remain private')
class NativeBrainCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import zstandard as zstd
        from ootrr_full.formats.inspect_nup import Nup
        from ootrr_full.formats.inspect_resources import dictionaries, decompress, sarc
        from ootrr_full.game.world_maps import effective_members
        from ootrr_full.formats import byml_codec
        cls.nup = Nup(os.environ['OOT_NUP'])
        cls.members, dictionary = effective_members(cls.nup), dictionaries(cls.nup)
        cls.sarc, cls.build_sarc = staticmethod(sarc), staticmethod(byml_codec.build_sarc)
        class TestCompression:
            def decode(self, frame):
                return decompress(frame, dictionary)
            def encode(self, raw, frame):
                ident = zstd.get_frame_parameters(frame).dict_id
                compression = {zstd.ZstdCompressionDict(value).dict_id(): zstd.ZstdCompressionDict(value)
                               for value in dictionary.values()}
                return zstd.ZstdCompressor(dict_data=compression.get(ident), level=3).compress(raw)
        cls.codec = TestCompression()
        cls.originals = {path: cls.nup.read(cls.members[path]) for path in gate.PLAYER_PACKS}
        global_files = sarc(cls.read(gate.GLOBAL_PACK))
        cls.templates = gate.native_templates(global_files, sarc(cls.read(gate.NAVI_PACK)))

    @classmethod
    def tearDownClass(cls):
        cls.nup.stream.close()

    @classmethod
    def read(cls, path):
        frame = cls.nup.read(cls.members[path])
        return cls.codec.decode(frame) if path.endswith('.zs') else frame

    def fixture(self, root, *, ready=True):
        token = 'd' * 64
        artifact, romfs = root / 'Archipelago', root / 'base'
        dictionary = romfs / 'Pack/ZsDic.pack.zs'
        dictionary.parent.mkdir(parents=True)
        dictionary.write_bytes(self.nup.read(self.members['Pack/ZsDic.pack.zs']))
        for path, frame in self.originals.items():
            files = dict(self.sarc(self.codec.decode(frame)))
            if ready:
                files[gate.BRAIN] = gate.patch_player_brain(files[gate.BRAIN],
                    gate.readiness_name(token), self.templates)
            files['CacheTest.keep'] = b'Other native Player settings'
            target = artifact / 'romfs' / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.codec.encode(self.build_sarc(files), frame))
        data = {'token': token, 'catalog_scan': 'unchanged-catalog', 'death_link': True,
                'full_patch': {'placements': {
                    'own-source': {'item': 'Bow', 'own': True, 'player': 'Player'},
                    'foreign-source': {'item': 'Foreign Sword', 'own': False, 'player': 'Friend'}},
                    'remote': [{'item': 'Hookshot', 'player': 'Friend'}]}}
        manifest = {'seed_id': 'stable-room-seed',
                    'archipelago': {'token': token, 'generation_mode': 'full_network'},
                    'tracking': {'sha256': 'old-tracking-hash'},
                    'files': {'obsolete': {'size': 0, 'sha256': 'old-file-hash'}},
                    'external_readiness': {'version': 2, 'flag': gate.readiness_name(token)},
                    'resource_allocations': {'version': 1, 'resources': 17, 'changed': []}}
        (artifact / 'manifest.json').write_text(json.dumps(manifest), encoding='utf8')
        (artifact / 'full-player.json').write_text(json.dumps(data), encoding='utf8')
        (artifact / 'tracking.json').write_text(json.dumps({'seed_marker': 12345,
            'checks': {'own-source': {'item': 'Bow'}, 'foreign-source': {'item': 'Foreign Sword'}}}), encoding='utf8')
        (artifact / 'spoiler.json').write_text(json.dumps(data['full_patch']), encoding='utf8')
        bridge = artifact / 'romfs' / full_mod.NATIVE_METADATA
        bridge.parent.mkdir(parents=True)
        bridge.write_text(json.dumps({'token': token, 'version': 1, 'records': ['saved receipts']}), encoding='utf8')
        # A save inside this disposable fixture must never be opened by repair.
        save = artifact / 'save/progress.sav'
        save.parent.mkdir()
        save.write_bytes(b'existing player inventory and received-item cursor')
        return artifact, {'native': True, 'romfs': str(romfs), 'game_source': os.environ['OOT_NUP']}, data

    def snapshot(self, artifact):
        return {p.relative_to(artifact).as_posix(): p.read_bytes()
                for p in artifact.rglob('*') if p.is_file()}

    def run_refresh(self, artifact, settings, data, *, allocations=None):
        # Budget reconciliation has its own real-resource tests. These tests
        # exercise actual Player-pack restoration and manifest hashing, while
        # replacing only that expensive whole-game resource scan.
        if allocations is None:
            allocations = {'version': 1, 'resources': 17, 'changed': []}
        with patch('ootrr_triforce.mod_codec.Codec', return_value=self.codec), \
             patch('ootrr_triforce.full_allocations.prepare_allocations', return_value=allocations) as budget:
            result = full_mod.refresh_native_player_brains(artifact, settings, data)
        return result, budget

    def test_old_native_cache_repairs_marker_and_hashes_preserving_room_and_progress(self):
        with tempfile.TemporaryDirectory() as temporary:
            artifact, settings, data = self.fixture(Path(temporary))
            before = self.snapshot(artifact)
            changed, budget = self.run_refresh(artifact, settings, data)
            self.assertEqual(set(changed), set(gate.PLAYER_PACKS))
            budget.assert_called_once_with(Path(settings['romfs']), artifact,
                                           game_source=settings['game_source'])
            after = self.snapshot(artifact)
            modified = {path for path in before if before[path] != after[path]}
            self.assertEqual(modified, {'manifest.json', *('romfs/' + p for p in gate.PLAYER_PACKS)})
            document = json.loads(after['manifest.json'])
            self.assertEqual(document['seed_id'], 'stable-room-seed')
            self.assertEqual(document['archipelago']['token'], data['token'])
            self.assertEqual(document['native_player_brain']['version'], 1)
            self.assertNotIn('external_readiness', document)
            self.assertEqual(document['tracking']['sha256'], hashlib.sha256(after['tracking.json']).hexdigest())
            expected = {path.removeprefix('romfs/'): {'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                        for path, raw in after.items() if path.startswith('romfs/')}
            self.assertEqual(document['files'], expected)
            for path in gate.PLAYER_PACKS:
                files = self.sarc(self.codec.decode(after['romfs/' + path]))
                original = self.sarc(self.codec.decode(self.originals[path]))
                self.assertEqual(files[gate.BRAIN], original[gate.BRAIN])
                self.assertEqual(files['CacheTest.keep'], b'Other native Player settings')
            self.assertEqual(json.loads(after['full-player.json'])['full_patch'], data['full_patch'])

    def test_repeated_cache_refresh_does_not_write_manifest_packs_or_any_saved_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            artifact, settings, data = self.fixture(Path(temporary))
            self.run_refresh(artifact, settings, data)
            before = self.snapshot(artifact)
            times = {p: (artifact / p).stat().st_mtime_ns for p in before}
            changed, budget = self.run_refresh(artifact, settings, data)
            self.assertEqual(changed, ())
            budget.assert_not_called()
            self.assertEqual(before, self.snapshot(artifact))
            self.assertEqual(times, {p: (artifact / p).stat().st_mtime_ns for p in before})

    def test_native_brains_still_gain_missing_capability_without_budget_rewrites(self):
        with tempfile.TemporaryDirectory() as temporary:
            artifact, settings, data = self.fixture(Path(temporary), ready=False)
            before = self.snapshot(artifact)
            changed, budget = self.run_refresh(artifact, settings, data)
            self.assertEqual(changed, ())
            budget.assert_not_called()
            after = self.snapshot(artifact)
            self.assertEqual({p for p in before if before[p] != after[p]}, {'manifest.json'})
            document = json.loads(after['manifest.json'])
            self.assertEqual(document['native_player_brain']['version'], 1)
            self.assertNotIn('external_readiness', document)
            self.assertEqual(document['resource_allocations'], {'version': 1, 'resources': 17, 'changed': []})

    def test_marker_cannot_mask_a_still_replaced_player_brain(self):
        with tempfile.TemporaryDirectory() as temporary:
            artifact, settings, data = self.fixture(Path(temporary))
            path = artifact / 'manifest.json'
            document = json.loads(path.read_bytes())
            document['native_player_brain'] = {'version': 1}
            document.pop('external_readiness')
            path.write_text(json.dumps(document), encoding='utf8')
            changed, budget = self.run_refresh(artifact, settings, data)
            self.assertEqual(set(changed), set(gate.PLAYER_PACKS))
            budget.assert_called_once()


if __name__ == '__main__':
    unittest.main()
