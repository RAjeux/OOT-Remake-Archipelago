"""Every dungeon key copy has one exact saved effect, independent of Link's map."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'client'), str(ROOT / 'tests')]
from evfl.entry_point import EntryPoint
from evfl.util import make_index
from ootrr_full.patching import key_adapter as keys
from ootrr_full.patching.ap_mailbox import records
from ootrr_full.patching.progressive import FlowEditor
from ootrr_triforce.full_mod import _physical_small_key_tokens, receipt_catalog
from ootrr_triforce.native_presentations import append_recipe
from ootrr_triforce.restoration import build_restoration_flow, event_name
from ootrr_triforce.catalog import ITEM_DATA, LOCATION_IDS
from test_restoration import CHEST, SaveRun, pouch, reward


class KeyCopiesTests(unittest.TestCase):
    def test_tracker_uses_actual_individual_totals_and_saved_ring_membership(self):
        from ootrr_full.game.native_key_limits import NATIVE_SMALL_KEYS
        from ootrr_full.patching.soul_adapter import murmur3
        saved = {'Int': {murmur3(f'DungeonInfo.{folder}.{field}') for folder in keys.RING_DUNGEONS
                         for field in ('SmallKeyNum', 'SmallKeyTotalNum')}, 'Bool': set()}
        options = {'individual_smallkeys': True, 'shuffle_chests': True, 'shuffle_smallkeys': 'keysanity'}
        totals = lambda values: {row['folder']: row['small']['total'] for row in keys.key_tracking(values, saved)}
        self.assertEqual(totals(options), NATIVE_SMALL_KEYS)
        saved['Bool'].add(murmur3(keys.APPLIED_PREFIX + 'WaterTemple'))
        self.assertEqual(totals(options)['WaterTemple'], keys.RING_DUNGEONS['WaterTemple'])
        expected = dict(NATIVE_SMALL_KEYS, WaterTemple=keys.RING_DUNGEONS['WaterTemple'])
        self.assertEqual(totals(dict(options, individual_smallkeys=False)), expected)
        self.assertEqual(totals(dict(options, shuffle_chests=False, shuffle_smallkeys='vanilla')), expected)
        self.assertEqual(totals(dict(options, shuffle_smallkeys='remove')), keys.RING_DUNGEONS)

    def test_all_copies_have_short_dungeon_specific_actors_and_separate_remote_names(self):
        copies = {str(index) + folder: keys.small_key_item(folder)
                  for folder, count in keys.RING_DUNGEONS.items() for index in range(count)}
        placed = keys.individual_key_plan(copies)
        remote = records([{'item': item, 'player': 'Friend', 'location': gid} for gid, item in copies.items()])
        actors = set(placed.values()) | {row['actor'] for row in remote}
        self.assertEqual(len(actors), 2 * sum(keys.RING_DUNGEONS.values()))
        self.assertTrue(all(len(actor) <= 25 for actor in actors))
        for gid, actor in placed.items():
            self.assertEqual(keys.key_actor_item(actor), copies[gid])
        rows = keys.key_records(set(copies.values()), actors)
        self.assertEqual(len(rows), len(actors))
        self.assertEqual(len({row['applied'] for row in rows}), len(actors))
        self.assertTrue(all(row['count'] == 1 for row in rows))

    def test_remote_recipe_reserves_only_its_remote_copies(self):
        name = keys.small_key_item('ForestTemple')
        data = {'full_patch': {'options': {'individual_smallkeys': True},
                              'placements': {'own': {'item': name, 'own': True}},
                              'remote': [{'item': name, 'player': 'Friend', 'location': str(i)} for i in range(2)]}}
        recipe = receipt_catalog(data)[name]
        self.assertEqual(recipe['mode'], 'small_keys')
        self.assertEqual(recipe['small_key_tokens'], [keys.small_key_actor('ForestTemple', i, remote=True)
                                                      for i in (1, 2)])
        self.assertNotIn(keys.small_key_actor('ForestTemple', 1), recipe['small_key_tokens'])

    def test_physical_binding_requires_exact_source_and_saved_flags(self):
        from ootrr_full.patching.soul_adapter import murmur3
        actor = keys.small_key_actor('WaterTemple', 1)
        name = keys.key_actor_item(actor)
        data = {'full_patch': {'options': {'individual_smallkeys': True},
                              'placements': {'own': {'own': True, 'item': name}}}}
        generated = {'skips': {'key_items': {'records': keys.key_records([name], [actor])}}}
        tracking = {'checks': {'own': {'actor': actor, 'item': name}}}
        saved = {murmur3(flag) for flag in (keys.got_flag(actor), keys.small_applied_flag(actor))}
        (ROOT / 'build').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / 'build', prefix='small-key-binding-') as temporary:
            path = Path(temporary)
            (path / 'spoiler.json').write_text(json.dumps({'placements': [{'id': 'own', 'item': name,
                                                                        'actor': actor}]}), encoding='utf-8')
            self.assertEqual(_physical_small_key_tokens(data, path, generated, tracking, saved),
                             {'own': {'actor': actor, 'applied': keys.small_applied_flag(actor)}})
            with self.assertRaisesRegex(ValueError, 'does not match'):
                _physical_small_key_tokens(data, path, generated, tracking, set())


class KeyRecoveryTests(unittest.TestCase):
    def model(self, folder):
        actor = keys.small_key_actor(folder, 1)
        name = keys.key_actor_item(actor)
        record = {'name': CHEST, 'id': LOCATION_IDS[CHEST], 'local': True, 'item': name,
                  'flags': ['Fixture.Source', 'Fixture.Chest'], 'counters': [], 'wake_talon': False,
                  'full_network': True, 'small_key_token': {'actor': actor, 'applied': keys.small_applied_flag(actor)}}
        recipe = dict(ITEM_DATA[name], mode='small_keys', actor=keys.small_key_actor(folder, 1, remote=True),
                      small_key_tokens=[keys.small_key_actor(folder, 1, remote=True)])
        raw, _ = build_restoration_flow(pouch(), {CHEST: reward(name)}, records=[record], item_data={name: recipe})
        return SaveRun(raw), actor

    def test_all_dungeons_restore_one_missing_copy_without_claiming_a_remote_copy(self):
        for folder in keys.RING_DUNGEONS:
            with self.subTest(folder=folder):
                run, actor = self.model(folder)
                run.run(event_name(LOCATION_IDS[CHEST]))
                self.assertEqual(run.values[f'DungeonInfo.{folder}.SmallKeyNum'], 1)
                self.assertEqual(run.values[f'DungeonInfo.{folder}.SmallKeyTotalNum'], 1)
                self.assertTrue(run.values[keys.small_applied_flag(actor)])
                self.assertNotIn(keys.small_applied_flag(keys.small_key_actor(folder, 1, remote=True)), run.values)
                run.run(event_name(LOCATION_IDS[CHEST]))
                self.assertEqual(run.values[f'DungeonInfo.{folder}.SmallKeyNum'], 1)

    def test_saved_applied_copy_never_refunds_a_spent_key_when_collection_flags_are_missing(self):
        for folder in keys.RING_DUNGEONS:
            with self.subTest(folder=folder):
                run, actor = self.model(folder)
                run.values.update({keys.small_applied_flag(actor): True,
                                   f'DungeonInfo.{folder}.SmallKeyNum': 0,
                                   f'DungeonInfo.{folder}.SmallKeyTotalNum': 1})
                run.run(event_name(LOCATION_IDS[CHEST]))
                self.assertEqual(run.values[f'DungeonInfo.{folder}.SmallKeyNum'], 0)
                self.assertEqual(run.values[f'DungeonInfo.{folder}.SmallKeyTotalNum'], 1)
                self.assertTrue(run.saves[-1][0]['Fixture.Source'])

    def test_remote_two_copies_credit_the_exact_dungeon_and_never_restore_spent_stock(self):
        for folder in keys.RING_DUNGEONS:
            with self.subTest(folder=folder):
                editor = FlowEditor(pouch(), 'small-key receipt test')
                ack = editor.action('FixtureAck', 'GameDataActor', 'EventTriggerAddOrSubGameDataInt',
                                    {'GameDataName': 'Fixture.Cursor', 'Index': -1, 'Value': 1})
                actors = [keys.small_key_actor(folder, n, remote=True) for n in (1, 2)]
                metadata = {'actor': actors[0], 'kind': 'FullNetwork', 'mode': 'small_keys', 'small_key_tokens': actors}
                point = EntryPoint('FixtureReceive')
                point.main_event = make_index(append_recipe(editor, metadata, 'FixtureKey', '', ack))
                editor.chart.entry_points.append(point)
                run = SaveRun(editor.write('small-key test')[0])
                run.run('FixtureReceive')
                run.values[f'DungeonInfo.{folder}.SmallKeyNum'] = 0  # spent in a locked door
                run.run('FixtureReceive')
                self.assertEqual(run.values[f'DungeonInfo.{folder}.SmallKeyNum'], 1)
                self.assertEqual(run.values[f'DungeonInfo.{folder}.SmallKeyTotalNum'], 2)
                run.values[f'DungeonInfo.{folder}.SmallKeyNum'] = 0
                run.run('FixtureReceive')  # no reserved copy left: acknowledge without refund
                self.assertEqual(run.values[f'DungeonInfo.{folder}.SmallKeyNum'], 0)
                self.assertEqual(run.values['Fixture.Cursor'], 3)
                self.assertTrue(all(run.values[keys.small_applied_flag(actor)] for actor in actors))


@unittest.skipUnless(os.environ.get('OOT_NUP'), 'OOT_NUP not set')
class RealNativeKeysTests(unittest.TestCase):
    def test_cached_pose_refresh_uses_the_nup_with_only_the_minimal_dictionary_cache(self):
        from ootrr_full.formats.inspect_nup import Nup
        from ootrr_full.formats.inspect_resources import dictionaries, decompress, sarc
        from ootrr_full.formats import byml_codec
        from ootrr_full.patching.soul_adapter import build_item_files, RSDB_FILES
        from ootrr_triforce import app_runtime
        from ootrr_triforce.full_mod import refresh_small_key_poses
        from ootrr_triforce.mod_codec import Codec
        previous = app_runtime._resource_override
        app_runtime._resource_override = ROOT / 'dist'
        self.addCleanup(setattr, app_runtime, '_resource_override', previous)
        nup = Nup(os.environ['OOT_NUP'])
        self.addCleanup(nup.stream.close)
        dictionary = dictionaries(nup)
        frame = lambda path: nup.read(nup.latest('romfs/' + path))
        read = lambda path: decompress(frame(path), dictionary)
        actor = keys.small_key_actor('WaterTemple', 1, remote=True)
        modified, new = build_item_files(read, keys.key_specs([actor]))  # Original unposed cache.
        (ROOT / 'build').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / 'build', prefix='key-pose-nup-') as temporary:
            directory = Path(temporary)
            cache, artifact = directory / 'minimal-romfs', directory / 'Archipelago'
            mod = artifact / 'romfs'
            (cache / 'Pack').mkdir(parents=True)
            (cache / 'Pack/ZsDic.pack.zs').write_bytes(frame('Pack/ZsDic.pack.zs'))
            codec = Codec((cache / 'Pack/ZsDic.pack.zs').read_bytes())
            pack_path = f'Pack/Actor/{actor}.pack.zs'
            resources = {pack_path: (new[pack_path][0], frame(new[pack_path][1])),
                         RSDB_FILES['ActorInfo']: (modified[RSDB_FILES['ActorInfo']], frame(RSDB_FILES['ActorInfo']))}
            rest = 'System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs'
            resources[rest] = (read(rest), frame(rest))
            for path, (raw, template) in resources.items():
                target = mod / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(codec.encode(raw, template))
            (artifact / 'tracking.json').write_text('{}', encoding='utf-8')
            (artifact / 'manifest.json').write_text(json.dumps({'tracking': {}, 'skips': {
                'key_items': {'records': keys.key_records([], [actor])}}}), encoding='utf-8')
            data = {'token': 'a' * 64, 'catalog_scan': 'native-pose-test',
                    'full_patch': {'options': {'individual_smallkeys': True}}}
            settings = {'romfs': str(cache), 'game_source': os.environ['OOT_NUP']}
            self.assertFalse((cache / 'Pack/Actor/Item_Dungeon_SmallKey.pack.zs').exists())
            changed = refresh_small_key_poses(artifact, settings, data)
            self.assertIn(pack_path, changed)
            self.assertEqual(refresh_small_key_poses(artifact, settings, data), [])
            pack = sarc(codec.decode((mod / pack_path).read_bytes()))
            components = byml_codec.load(pack[f'Actor/{actor}.engine__actor__ActorParam.bgyml'])['root']['Components']
            self.assertIn('Item_GetDemo', components['ASInfoRef'])
            self.assertEqual(components['ASRef'], '?AS/Item_Common.root.asb')
            updated = json.loads((artifact / 'manifest.json').read_bytes())
            self.assertIn(pack_path, updated['files'])
            self.assertTrue(updated['resource_allocations']['resources'])

    def test_real_game_accepts_all_actor_packs_saved_flags_counters_and_the_quiet_fallback(self):
        from ootrr_full.formats.inspect_nup import Nup
        from ootrr_full.formats.inspect_resources import dictionaries, decompress
        from ootrr_full.patching.soul_adapter import GAMEDATA, MAX_ACTOR_NAME
        from ootrr_triforce import app_runtime
        previous = app_runtime._resource_override
        app_runtime._resource_override = ROOT / 'dist'
        self.addCleanup(setattr, app_runtime, '_resource_override', previous)
        nup = Nup(os.environ['OOT_NUP'])
        self.addCleanup(nup.stream.close)
        dictionary = dictionaries(nup)
        def read(path):
            return decompress(nup.read(nup.latest('romfs/' + path)), dictionary)
        actors = [keys.small_key_actor(folder, n, remote=remote) for folder in keys.RING_DUNGEONS
                  for n in (1, 2) for remote in (False, True)]
        rows = keys.key_records([], actors)
        keys.check_dungeon_data(read(GAMEDATA), rows)
        modified, new = keys.build_key_files(read, rows, ['Mals/EUen.Product.110.sarc.zs',
                                                       'Mals/EUfr.Product.110.sarc.zs'])
        keys.check_got_flags(modified[GAMEDATA], rows)
        self.assertTrue(all(len(actor) <= MAX_ACTOR_NAME for actor in actors))
        self.assertTrue(all('Pack/Actor/' + actor + '.pack.zs' in new for actor in actors))
        from ootrr_full.formats.inspect_resources import sarc
        from ootrr_full.formats import byml_codec
        from ootrr_full.patching.soul_adapter import RSDB_FILES, TEMPLATE
        native_rows = {row['__RowId']: row for row in byml_codec.load(read(RSDB_FILES['ActorInfo']))['root']}
        native_pack = sarc(read('Pack/Actor/Item_Dungeon_SmallKey.pack.zs'))
        native_offset = byml_codec.load(native_pack[
            'Component/PouchContentParam/KeyItemSmallKey.game__component__PouchContentParam.bgyml'])['root']['GetDemoOffsetPos']
        center = lambda name, axis: (native_rows[name]['ModelAabbMin'][axis] + native_rows[name]['ModelAabbMax'][axis]) / 2
        for actor in actors:
            pack = sarc(new['Pack/Actor/' + actor + '.pack.zs'][0])
            components = byml_codec.load(pack[f'Actor/{actor}.engine__actor__ActorParam.bgyml'])['root']['Components']
            self.assertEqual(components['ASRef'], '?AS/Item_Common.root.asb')
            self.assertIn('Item_GetDemo', components['ASInfoRef'])
            self.assertIn('Obj_Dungeon_SmallKey', components['AnimationRef'])
            self.assertIn('RandoSmallKeyGet', components['PouchContentRef'])
            pouch_param = byml_codec.load(pack[components['PouchContentRef'].lstrip('?')])['root']
            self.assertNotIn('PouchActor', pouch_param, 'A custom key must never redirect its effect to a generic key.')
            for axis in ('X', 'Y', 'Z'):
                self.assertAlmostEqual(pouch_param['GetDemoOffsetPos'][axis] + center(keys.SMALL_KEY_MODEL, axis),
                                       native_offset[axis] + center(TEMPLATE, axis), places=6)
        raw, _ = keys.add_key_hook(read(keys.ACTION_GUIDE_FLOW), rows)
        chart = FlowEditor(raw, 'real dungeon-key converter').chart
        self.assertIn(keys.SMALL_ENTRY, {point.name for point in chart.entry_points})
        # Execute the actual written quiet entry using ordinary native event
        # semantics. Link's current map is deliberately absent from this model.
        values = {}
        def convert():
            node = next(point.main_event.v for point in chart.entry_points if point.name == keys.SMALL_ENTRY)
            for _ in range(1000):
                if node is None:
                    return
                data = node.data
                params = data.params.data
                if type(data).__name__ == 'SwitchEvent':
                    self.assertEqual(data.actor_query.v.v, 'EventQueryIsGameDataBool')
                    branch = data.cases.get(0 if values.get(params['GameDataName']) else 1)
                    node = branch.v if branch is not None else None
                else:
                    action = data.actor_action.v.v
                    if action == 'EventTriggerSetGameDataBool':
                        values[params['GameDataName']] = params['Value']
                    else:
                        self.assertEqual(action, 'EventTriggerAddOrSubGameDataInt')
                        values[params['GameDataName']] = values.get(params['GameDataName'], 0) + params['Value']
                    node = data.nxt.v
            self.fail('Dungeon-key converter loop')
        for folder in keys.RING_DUNGEONS:
            held, found = (f'DungeonInfo.{folder}.{member}' for member in ('SmallKeyNum', 'SmallKeyTotalNum'))
            values[keys.got_flag(keys.small_key_actor(folder, 1))] = True
            convert()
            self.assertEqual((values[held], values[found]), (1, 1))
            values[held] = 0
            values[keys.got_flag(keys.small_key_actor(folder, 1, remote=True))] = True
            convert()
            self.assertEqual((values[held], values[found]), (1, 2))
            convert()
            self.assertEqual((values[held], values[found]), (1, 2))
        from ootrr_full.patching.soul_adapter import murmur3
        saved = {int(row['Hash']) for row in byml_codec.load(modified[GAMEDATA])['root']['Data']['Bool']
                 if row.get('SaveFileIndex') == 0}
        self.assertTrue(all(murmur3(keys.small_applied_flag(actor)) in saved for actor in actors))
        watched = keys.small_key_watch(nup.read(nup.latest('romfs/Sequence/MainUpdate.module.ainb')), actors)
        self.assertTrue(watched)


if __name__ == '__main__':
    unittest.main()
