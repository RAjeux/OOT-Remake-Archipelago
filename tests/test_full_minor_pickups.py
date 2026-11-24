"""Physical checks commit after native pickup and preserve short consumable gets."""
import copy
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client'))
from ootrr_full.formats import byml_codec
from ootrr_full.patching import repeatable_adapter as r
from ootrr_full.patching import bomb_refills


class MinorPolicyTests(unittest.TestCase):
    def test_ap_metadata_generation_needs_no_resource_decoder_or_event_libraries(self):
        code = """import sys, importlib.abc
sys.path.insert(0, 'client')
class NoResourceLibraries(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, path=None, target=None):
  if fullname in ('zstandard', 'ainb', 'evfl'):
   raise AssertionError('AP item generation imported ' + fullname)
sys.meta_path.insert(0, NoResourceLibraries())
from ootrr_full.patching.ap_mailbox import records
item = records([{'item': 'Arrows (30)', 'player': 'Friend', 'location': 'Check'}])[0]
assert item['grant_actor'] == 'Item_Arrow_Normal' and item['grant_amount'] == 30
assert len(item['capacity']) == 3
"""
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_native_short_get_repeats_callback_without_held_pose(self):
        for actor in ('TBox_Rupee_Green', 'TBox_DekuNutBundle', 'TBox_DekuSeedBundle',
                      'Item_BombBundle_Small', 'TBox_ArrowBundle_Large', 'Obj_Heart'):
            with self.subTest(actor=actor):
                settings = r.pickup_pouch_settings(actor, {'PouchGetType': 'Large'})
                self.assertEqual(settings['GetType'], r.SMALL_GET_TYPE)
                self.assertTrue(settings['PlayGetEventManyTimes'])
        self.assertEqual(r.get_type('Item_Hammer', {'PouchGetType': 'Large'}), r.LARGE_GET_TYPE)

    def test_exact_quantities_require_native_ammunition_and_valid_item(self):
        for canonical, item, expected in (
            ('TBox_ArrowBundle_Large', 'Arrows (30)', ('Item_Arrow_Normal', 30)),
            ('TBox_DekuSeedBundle', 'Deku Seeds (30)', ('Item_DekuSeed', 30)),
            ('TBox_DekuNutBundle', 'Deku Nuts (5)', ('Item_DekuNut', 5)),
            ('Item_BombBundle_Small', 'Bombs (20)', ('Item_Bomb', 20)),
        ):
            self.assertEqual(r.exact_ammunition_grant(canonical, item), expected)
        self.assertIsNone(r.exact_ammunition_grant('Item_AP_Friend', 'Bombs (20)'))
        self.assertIsNone(r.exact_ammunition_grant('Item_AP_Friend', 'Bombs (20) (Friend)'))
        self.assertIsNone(r.exact_ammunition_grant('TBox_Rupee_Green', 'Rupees (5)'))
        for item in ('Arrows (0)', 'Arrows (-5)', 'Arrows (1000)'):
            with self.assertRaisesRegex(ValueError, 'quantity'):
                r.exact_ammunition_grant('TBox_ArrowBundle_Large', item)


@unittest.skipUnless(os.environ.get('OOT_NUP'), 'OOT_NUP not set')
class NativeMinorPickupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ootrr_full.formats.inspect_nup import Nup
        from ootrr_full.game.world_maps import effective_members
        from ootrr_full.formats.inspect_resources import dictionaries, decompress, sarc
        from ootrr_full.patching.soul_adapter import RSDB_FILES
        cls.nup = Nup(os.environ['OOT_NUP'])
        cls.members = effective_members(cls.nup)
        cls.dictionary = dictionaries(cls.nup)
        cls.decompress, cls.sarc = staticmethod(decompress), staticmethod(sarc)
        cls.raw_cache, cls.pack_cache = {}, {}
        cls.files = sarc(cls.read(r.EVENT_PACK))
        cls.tables = {name: byml_codec.load(cls.read(path))['root'] for name, path in RSDB_FILES.items()}

    @classmethod
    def tearDownClass(cls):
        cls.nup.stream.close()

    @classmethod
    def read(cls, path):
        if path not in cls.raw_cache:
            raw = cls.nup.read(cls.members[path])
            cls.raw_cache[path] = cls.decompress(raw, cls.dictionary) if path.endswith('.zs') else raw
        return cls.raw_cache[path]

    @classmethod
    def pack(cls, actor):
        if actor not in cls.pack_cache:
            cls.pack_cache[actor] = cls.sarc(cls.read('Pack/Actor/' + actor + '.pack.zs'))
        return cls.pack_cache[actor]

    def test_accepted_callback_commits_even_when_native_stock_gain_is_zero(self):
        import ainb
        original = ainb.AINB.from_binary(self.files[r.EVENT_MEMBER]).as_dict()
        for canonical, grant in (('TBox_Rupee_Green', None),
                                 ('TBox_ArrowBundle_Large', ('Item_Arrow_Normal', 30))):
            with self.subTest(canonical=canonical):
                flag = 'Rando.Check.NativeAccepted'
                raw = r.instrument_pickup_event(self.files[r.EVENT_MEMBER], flag, 'NativeAccepted',
                                                canonical=canonical, grant=grant)
                document = ainb.AINB.from_binary(raw).as_dict()
                self.assertEqual(document['Commands'], original['Commands'])
                # Eligibility belongs to the native request-get query. Do not add
                # another capacity test after that callback has been accepted.
                self.assertEqual(sum(n['Name'] == 'QueryPouchMgrIsEnablePushToPouch' for n in document['Nodes']),
                                 sum(n['Name'] == 'QueryPouchMgrIsEnablePushToPouch' for n in original['Nodes']))
                state = {'collected': False, 'native_grants': 0}
                nodes = document['Nodes']
                def execute(index):
                    node = nodes[index]
                    if node['Name'] in ('OneShotPouchContentPushToPouchOwnInEvent', 'OneShotAddOrRemovePouchContent'):
                        # Wallet full / ammo without a bag is a real native no-op.
                        state['native_grants'] += 1
                    elif node['Name'] == 'OneShotSetNonStructGameDataBool':
                        state['collected'] = True
                    elif node['Node Type'] == 'Element_BoolSelector':
                        query = nodes[node['Queries'][0]]
                        self.assertEqual(query['Name'], 'QueryGetNonStructGameDataBool')
                        branch = 'True' if state['collected'] else 'False'
                        execute(next(p['Node Index'] for p in node['Plugs']['Child'] if p['Name'] == branch))
                    elif node['Node Type'] == 'Element_Sequential':
                        for plug in node['Plugs']['Child']:
                            execute(plug['Node Index'])
                parent = next(n['Node Index'] for n in nodes if n['GUID'] == r._guid(flag + '/first-only'))
                self.assertIn(parent, [plug['Node Index'] for plug in nodes[58]['Plugs']['Child']])
                execute(parent)
                self.assertTrue(state['collected'])
                self.assertEqual(state['native_grants'], 1)
                execute(parent)
                self.assertEqual(state['native_grants'], 1, 'a second accepted callback cannot grant the check twice')

    def test_real_minor_packs_never_mark_on_spawn_and_grant_exact_native_amount(self):
        import ainb
        samples = (('TBox_Rupee_Green', 'Rupees (1)'),
                   ('TBox_ArrowBundle_Large', 'Arrows (30)'),
                   ('TBox_DekuSeedBundle', 'Deku Seeds (30)'),
                   ('TBox_DekuNutBundle', 'Deku Nuts (5)'),
                   ('Item_BombBundle_Small', 'Bombs (20)'))
        records = [{'id': 'NativeMinor#' + str(i), 'kind': 'placed' if i % 2 else 'pickup',
                    'actor': 'Obj_RandoOnce_NativeMinor' + str(i), 'canonical': actor, 'item': item,
                    'event_filename': 'NativeMinor' + str(i), 'flag': 'Rando.Check.NativeMinor' + str(i),
                    'variants': []} for i, (actor, item) in enumerate(samples)]
        tables = copy.deepcopy(self.tables)
        generated = r.build_repeatable_packs(records, self.pack, self.read, tables)
        rows = {row['__RowId']: row for row in tables['PouchActorInfo']}
        for record in records:
            files = self.sarc(generated['Pack/Actor/' + record['actor'] + '.pack.zs'][0])
            event = ainb.AINB.from_binary(files['AI/' + record['event_filename'] + '.ainb']).as_dict()
            drop = ainb.AINB.from_binary(files['AI/' + record['actor'] + '.root.ainb']).as_dict()
            setters = [n for n in drop['Nodes'] if n['Name'] == 'OneShotSetNonStructGameDataBool']
            self.assertFalse(any(p.get('Default Value') == record['flag'] for n in setters
                                 for p in n['Parameters']['Inputs'].get('String', ())))
            self.assertEqual(rows[record['actor']]['PouchGetType'], 'Small')
            actor = byml_codec.load(files['Actor/' + record['actor'] + '.engine__actor__ActorParam.bgyml'])['root']
            pouch = byml_codec.load(files[actor['Components']['PouchContentRef'][1:]])['root']
            self.assertTrue(pouch['PlayGetEventManyTimes'])
            self.assertEqual(pouch['GetType'], r.SMALL_GET_TYPE)
            grant = r.exact_ammunition_grant(record['canonical'], record['item'])
            push = event['Nodes'][35]
            if grant is None:
                self.assertEqual(push['Name'], 'OneShotPouchContentPushToPouchOwnInEvent')
            else:
                self.assertEqual(push['Name'], 'OneShotAddOrRemovePouchContent')
                inputs = push['Parameters']['Inputs']
                self.assertEqual(inputs['Int'][0]['Default Value'], grant[1])
                self.assertEqual(next(p['Default Value'] for p in inputs['String'] if p['Name'] == 'Actor'),
                                 'Work/Actor/' + grant[0] + '.engine__actor__ActorParam.gyml')
                self.assertFalse(any(p['Default Value'] for p in inputs['Bool']))
                self.assertEqual(rows[record['actor']]['BundleActorNum'], grant[1])
        uncached_tables = copy.deepcopy(self.tables)
        self.assertEqual(generated, r.build_repeatable_packs(records, self.pack, self.read, uncached_tables,
                                                            cache_templates=False))
        self.assertEqual(tables, uncached_tables)

    def test_native_equipment_guard_commits_without_grant_and_accepts_each_real_bag(self):
        import ainb
        for unit, capacities in r.AMMUNITION_CAPACITY.items():
            flag = 'Rando.Check.NoFreeAmmo'
            raw = r.instrument_pickup_event(self.files[r.EVENT_MEMBER], flag, 'NoFreeAmmo',
                                            grant=(unit, 30), capacity=capacities)
            nodes = ainb.AINB.from_binary(raw).as_dict()['Nodes']
            entry = next(n['Node Index'] for n in nodes if n['GUID'] == r._guid(flag + '/first-only'))
            for held in (None, *capacities):
                state = {'grants': 0, 'collected': False}
                def execute(index):
                    node = nodes[index]
                    if node['Name'] == 'OneShotAddOrRemovePouchContent':
                        state['grants'] += 1
                    elif node['Name'] == 'OneShotSetNonStructGameDataBool':
                        state['collected'] = True
                    elif node['Node Type'] == 'Element_Sequential':
                        for plug in node['Plugs']['Child']:
                            execute(plug['Node Index'])
                    elif node['Node Type'] == 'Element_BoolSelector':
                        query = nodes[node['Queries'][0]]
                        if query['Name'] == 'QueryGetNonStructGameDataBool':
                            answer = state['collected']
                        else:
                            self.assertEqual(query['Name'], 'QueryGetGameDataBool')
                            parent = nodes[query['Parameters']['Inputs']['Pointer'][0]['Node Index']]
                            self.assertEqual(parent['Name'], 'QueryGetNonStructGameDataStruct')
                            self.assertEqual(parent['Parameters']['Inputs']['String'][0]['Default Value'], 'IsGet')
                            answer = query['Parameters']['Inputs']['String'][0]['Default Value'] == held
                        execute(next(p['Node Index'] for p in node['Plugs']['Child']
                                     if p['Name'] == ('True' if answer else 'False')))
                execute(entry)
                self.assertTrue(state['collected'])
                self.assertEqual(state['grants'], int(held is not None))
                execute(entry)
                self.assertEqual(state['grants'], int(held is not None), 'no accepted check can be granted twice')

    def test_core_mailbox_uses_exact_units_and_equipment_guard_with_empty_ack(self):
        from ootrr_full.patching import ap_mailbox
        from ootrr_full.patching.progressive import FlowEditor
        names = ('Arrows (30)', 'Deku Seeds (30)', 'Deku Nuts (5)', 'Bombs (20)')
        items = ap_mailbox.records([{'item': name, 'player': 'Friend', 'location': name} for name in names])
        raw = ap_mailbox.add_entries(self.read(ap_mailbox.FLOW_PATH), items, dispatch=True)
        chart = FlowEditor(raw, 'Native exact mailbox').chart
        points = {point.name: point for point in chart.entry_points}
        for row in items:
            event = points[row['event']].main_event.v
            if row.get('capacity'):
                for bag in reversed(row['capacity']):
                    self.assertEqual(event.data.params.data['Actor'], bag)
                    give = event.data.cases[0].v
                    self.assertEqual(give.data.params.data['Actor'], row['grant_actor'])
                    self.assertEqual(give.data.params.data['Num'], row['grant_amount'])
                    event = event.data.cases[1].v
                self.assertEqual(event.name, row['event'] + '_Got')
                self.assertEqual(event.data.params.data['GameDataName'], row['got'])
            else:
                self.assertEqual(event.data.params.data['Actor'], row['grant_actor'])
                self.assertEqual(event.data.params.data['Num'], row['grant_amount'])

    def test_all_embedded_ammunition_capacity_references_are_removed_without_touching_bags(self):
        affected = set()
        for path in self.members:
            if not path.startswith('Pack/Actor/') or not path.endswith('.pack.zs'):
                continue
            raw = self.read(path)
            patched, changed = bomb_refills.patch_pack(raw)
            if changed:
                affected.add(path)
                self.assertIn(path, bomb_refills.NATIVE_PACKS)
                self.assertFalse(bomb_refills.patch_pack(patched)[1])
        self.assertEqual(affected, set(bomb_refills.NATIVE_PACKS))
        existing, generated = {}, {}
        report = bomb_refills.apply(existing, generated, self.read)
        from ootrr_full.patching.soul_adapter import RSDB_FILES
        rows = byml_codec.load(existing[RSDB_FILES['PouchActorInfo']])['root']
        before = {row['__RowId']: row for row in self.tables['PouchActorInfo']}
        for row in rows:
            if row.get('MaxNumGameData') in bomb_refills.BAG_REFERENCES:
                self.assertFalse(row.get('SmallBagActor'))
            else:
                self.assertEqual(row, before[row['__RowId']])
        self.assertTrue(report['RSDB/PouchActorInfo'])


if __name__ == '__main__':
    unittest.main()
