"""Native comfort/challenge adapters retain the full AP placement contract."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client'))
from ootrr_full.game.portable_options import native_values, unrecorded
from ootrr_triforce.full_portable import prepare_portable


class PortableContractTests(unittest.TestCase):
    def test_neutral_historical_patch_does_not_start_a_resource_tool(self):
        with patch('ootrr_triforce.engine.run_engine', side_effect=AssertionError('unexpected tool')):
            report = prepare_portable('.', '.', {'full_patch': {'options': {}}})
        self.assertEqual(report['files'], [])
        self.assertEqual(report['settings'], {})

    def test_resource_request_cannot_inherit_a_second_fill_or_debug_inputs(self):
        values = native_values({'shuffle_chests': True, 'shuffle_entrances': 'dungeons',
                                'enemy_gates': True, 'enemy_spawn_combo': True,
                                'open_forest': False, 'enemy_health': 200})
        self.assertNotIn('shuffle_chests', values)
        self.assertEqual(values['shuffle_entrances'], 'off')
        self.assertTrue(values['enemy_gates'])
        self.assertFalse(values['enemy_spawn_combo'])
        self.assertEqual(values['open_forest'], 'closed')
        self.assertEqual(values['enemy_health'], 200)
        self.assertTrue(set(unrecorded()) <= values.keys())


@unittest.skipUnless(os.environ.get('OOT_NUP') and os.environ.get('OOT_FULL_ARTIFACT'), 'native artifact not selected')
class NativePortableComposition(unittest.TestCase):
    def test_real_native_adapters_preserve_placements_and_exact_starting_status(self):
        from ootrr_triforce import app_runtime
        from ootrr_triforce.full_allocations import prepare_allocations
        from ootrr_full.formats import byml_codec
        from ootrr_triforce.mod_codec import Codec
        from ootrr_full.patching.soul_adapter import murmur3
        import ainb
        previous = app_runtime._resource_override
        app_runtime._resource_override = ROOT / 'dist'
        self.addCleanup(setattr, app_runtime, '_resource_override', previous)
        with tempfile.TemporaryDirectory(prefix='ap-portable-') as temporary:
            artifact = Path(temporary) / 'Archipelago'
            shutil.copytree(os.environ['OOT_FULL_ARTIFACT'], artifact)
            selected = {'faster_blocks': True, 'navi_return': 'everywhere', 'bunny_hood': 'jump',
                        'starting_hearts': 5, 'enemy_health': 150, 'enemy_damage': 125, 'enemy_speed': 120,
                        'jabu_open': True, 'skip_epona_race': True, 'early_beds': True,
                        'skip_mask_quest': True, 'deku_bridge_safe': True, 'skip_first_pickup_text': True}
            data = {'full_patch': {'options': selected, 'open_forest': True}, 'token': 'native-composition-test'}
            before = {path.relative_to(artifact).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in (artifact / 'romfs/Banc').rglob('*') if path.is_file()}
            tracking = (artifact / 'tracking.json').read_bytes()
            spoiler = (artifact / 'spoiler.json').read_bytes()
            report = prepare_portable(os.environ['OOT_ROMFS'], artifact, data, game_source=os.environ['OOT_NUP'])
            self.assertGreater(len(report['files']), 30)
            self.assertEqual((artifact / 'tracking.json').read_bytes(), tracking)
            self.assertEqual((artifact / 'spoiler.json').read_bytes(), spoiler)
            for path, digest in before.items():
                self.assertEqual(hashlib.sha256((artifact / path).read_bytes()).hexdigest(), digest, path)
            graph = ainb.AINB.from_binary((artifact / 'romfs/Sequence/SetPouchAndStatusForGameStart.module.ainb').read_bytes()).as_dict()
            starts = {}
            for node in graph['Nodes']:
                if node['Name'] != 'SeqOneShotSetGameDataInt':
                    continue
                params = node['Parameters']['Inputs']
                name = next((p.get('Default Value') for p in params.get('String', ()) if p['Name'] == 'GameDataName'), None)
                value = next((p.get('Default Value') for p in params.get('Int', ()) if p['Name'] == 'Value'), None)
                starts[name] = value
            self.assertEqual((starts['MaxLife'], starts['Life']), (20, 20))
            codec = Codec((Path(os.environ['OOT_ROMFS']) / 'Pack/ZsDic.pack.zs').read_bytes())
            schema = byml_codec.load(codec.decode((artifact / 'romfs/GameData/GameDataList.Product.110.byml.zs').read_bytes()))['root']['Data']
            first = next(row for row in schema['Bool'] if row['Hash'] == murmur3('HavePlayedGetEvent.Obj_Rupee_Green'))
            self.assertTrue(first['DefaultValue'])
            self.assertTrue((artifact / 'romfs/Event/EventFlow/OOTRREponaOwn.bfevfl.zs').is_file())
            prepare_allocations(os.environ['OOT_ROMFS'], artifact, game_source=os.environ['OOT_NUP'])
            self.assertEqual(prepare_allocations(os.environ['OOT_ROMFS'], artifact, game_source=os.environ['OOT_NUP'])['changed'], [])


if __name__ == '__main__':
    unittest.main()
