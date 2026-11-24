"""Native clients preserve the Player brain's original command-result contract."""
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client'))
from ootrr_triforce import upgrade_readiness as gate
from ootrr_triforce import native_player_brain as candidate


@unittest.skipUnless(os.environ.get('OOT_NUP'), 'OOT_NUP not set; native resources remain private')
class NativePlayerBrainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import zstandard as zstd
        from ootrr_full.formats.inspect_nup import Nup
        from ootrr_full.formats.inspect_resources import dictionaries, decompress, sarc
        from ootrr_full.game.world_maps import effective_members
        from ootrr_full.formats import byml_codec
        cls.nup = Nup(os.environ['OOT_NUP'])
        cls.members, cls.dictionary = effective_members(cls.nup), dictionaries(cls.nup)
        cls.sarc, cls.build_sarc = staticmethod(sarc), staticmethod(byml_codec.build_sarc)
        dictionary = cls.dictionary
        class TestCompression:
            def decode(self, frame):
                return decompress(frame, dictionary)
            def encode(self, raw, frame):
                ident = zstd.get_frame_parameters(frame).dict_id
                compression = {zstd.ZstdCompressionDict(value).dict_id(): zstd.ZstdCompressionDict(value)
                               for value in dictionary.values()}
                return zstd.ZstdCompressor(dict_data=compression.get(ident), level=3).compress(raw)
        cls.codec = TestCompression()
        cls.token = 'b' * 64
        cls.originals = {path: cls.nup.read(cls.members[path]) for path in gate.PLAYER_PACKS}
        global_files = cls.sarc(cls.read(gate.GLOBAL_PACK))
        cls.templates = gate.native_templates(global_files, cls.sarc(cls.read(gate.NAVI_PACK)))
        cls.old_query = gate._template(global_files, 'QueryPlayerGetCurrentActionVerb')

    @classmethod
    def tearDownClass(cls):
        cls.nup.stream.close()

    @classmethod
    def read(cls, path):
        raw = cls.nup.read(cls.members[path])
        return cls.codec.decode(raw) if path.endswith('.zs') else raw

    def ready_packs(self, *, legacy=False):
        from ootrr_full.patching.ap_mailbox import ainb_to_binary
        result = {}
        for path, original in self.originals.items():
            files = dict(self.sarc(self.codec.decode(original)))
            raw = gate.patch_player_brain(files[gate.BRAIN], gate.readiness_name(self.token), self.templates)
            if legacy:
                doc = candidate._document(raw)
                old = copy.deepcopy(self.old_query)
                old.update({'Node Index': 1, 'GUID': gate._guid(gate.readiness_name(self.token), 1), 'Plugs': {}, 'Queries': []})
                old['Parameters']['Inputs']['Int'][0] = gate._default('ActionSlot', 0)
                doc['Nodes'][1] = old
                raw = ainb_to_binary(doc)
            files[gate.BRAIN] = raw
            files['TestSentinel.preserved'] = b'other Player pack changes'
            result[path] = self.codec.encode(self.build_sarc(files), original)
        return result

    def stage(self, packs, token=None):
        return candidate.stage_player_packs(packs, self.originals, token or self.token,
            self.templates, self.old_query, self.codec)

    def test_exact_v1_and_v2_restoration_preserves_every_other_pack_member(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                packs = self.ready_packs(legacy=legacy)
                staged, metadata, states = self.stage(packs)
                self.assertEqual(set(staged), set(gate.PLAYER_PACKS))
                self.assertEqual(set(states.values()), {'v1' if legacy else 'v2'})
                for path, frame in staged.items():
                    before = dict(self.sarc(self.codec.decode(packs[path])))
                    after = dict(self.sarc(self.codec.decode(frame)))
                    original = self.sarc(self.codec.decode(self.originals[path]))
                    self.assertEqual(after.pop(gate.BRAIN), original[gate.BRAIN])
                    before.pop(gate.BRAIN)
                    self.assertEqual(after, before)
                second, repeated, states = self.stage(staged)
                self.assertEqual(second, {})
                self.assertEqual(repeated, metadata)
                self.assertEqual(set(states.values()), {'native'})

    def test_absent_overrides_remain_absent(self):
        staged, _, states = self.stage({})
        self.assertEqual(staged, {})
        self.assertEqual(set(states.values()), {'native'})

    def test_another_room_cannot_be_restored(self):
        with self.assertRaisesRegex(ValueError, 'different-room'):
            self.stage(self.ready_packs(), 'e' * 64)

    def test_an_unknown_brain_cannot_be_overwritten(self):
        from ootrr_full.patching.ap_mailbox import ainb_to_binary
        packs = self.ready_packs()
        path = gate.PLAYER_PACKS[-1]
        files = dict(self.sarc(self.codec.decode(packs[path])))
        doc = candidate._document(files[gate.BRAIN])
        doc['Nodes'][10]['Parameters']['Inputs']['Bool'][0]['Default Value'] = False
        files[gate.BRAIN] = ainb_to_binary(doc)
        packs[path] = self.codec.encode(self.build_sarc(files), packs[path])
        with self.assertRaisesRegex(ValueError, 'unknown'):
            self.stage(packs)

    def _prepare(self, artifact):
        with patch('ootrr_triforce.mod_codec.Codec', return_value=self.codec):
            return candidate.prepare_native_player_brains(artifact / 'base', artifact,
                self.token, game_source=os.environ['OOT_NUP'])

    def _write_fixture(self, artifact, packs):
        dictionary = artifact / 'base/Pack/ZsDic.pack.zs'
        dictionary.parent.mkdir(parents=True)
        dictionary.write_bytes(self.nup.read(self.members['Pack/ZsDic.pack.zs']))
        for path, frame in packs.items():
            target = artifact / 'romfs' / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(frame)

    def test_repeated_prepare_does_not_rewrite_packs(self):
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary)
            self._write_fixture(artifact, self.ready_packs())
            metadata, _, changed = self._prepare(artifact)
            self.assertEqual(set(changed), set(gate.PLAYER_PACKS))
            before = {p: (artifact / 'romfs' / p).stat().st_mtime_ns for p in gate.PLAYER_PACKS}
            repeated, _, changed = self._prepare(artifact)
            self.assertEqual(changed, ())
            self.assertEqual(repeated, metadata)
            self.assertEqual(before, {p: (artifact / 'romfs' / p).stat().st_mtime_ns for p in gate.PLAYER_PACKS})

    def test_unknown_last_pack_leaves_first_two_completely_unchanged(self):
        from ootrr_full.patching.ap_mailbox import ainb_to_binary
        packs = self.ready_packs()
        path = gate.PLAYER_PACKS[-1]
        files = dict(self.sarc(self.codec.decode(packs[path])))
        doc = candidate._document(files[gate.BRAIN])
        doc['Nodes'][1]['Parameters']['Inputs']['Int'][0]['Default Value'] = 100
        files[gate.BRAIN] = ainb_to_binary(doc)
        packs[path] = self.codec.encode(self.build_sarc(files), packs[path])
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary)
            self._write_fixture(artifact, packs)
            with self.assertRaisesRegex(ValueError, 'unknown'):
                self._prepare(artifact)
            self.assertEqual(packs, {p: (artifact / 'romfs' / p).read_bytes() for p in gate.PLAYER_PACKS})


if __name__ == '__main__':
    unittest.main(verbosity=2)
