"""External old-save recovery uses real checks and native item transactions."""
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client'))
from ootrr_triforce import upgrade_recovery as recovery
from ootrr_full.archipelago.client import ArchipelagoClient
from ootrr_full.patching.ap_mailbox import record_key, DISPATCH


class RecoveryIdentityTests(unittest.TestCase):
    def test_nonced_sync_get_fence_completes_even_when_received_items_is_empty(self):
        delivery = SimpleNamespace(records=[{'key': 'owned', 'restore_location_id': 101}])
        client = ArchipelagoClient({'archipelago': {'slot_name': 'Link', 'location_ids': {'own': 101}}},
                                   'ws://127.0.0.1:1', delivery=delivery)
        sent = []
        client._send = lambda socket, *packets: sent.extend(packets)
        client._handle(None, {'cmd': 'Connected', 'slot': 1, 'team': 0, 'checked_locations': [101]})
        self.assertEqual([packet['cmd'] for packet in sent], ['Sync', 'Get'])
        nonce = sent[1]['keys'][0]
        self.assertFalse(client._history_synced)
        self.assertEqual(client.received_keys(), [])
        client._handle(None, {'cmd': 'ReceivedItems', 'index': 0, 'items': []})
        client._handle(None, {'cmd': 'Retrieved', 'keys': {'another-nonce': None}})
        self.assertFalse(client._history_synced)
        client._handle(None, {'cmd': 'Retrieved', 'keys': {nonce: None}})
        self.assertTrue(client._history_synced)
        self.assertEqual(client.received_keys(), ['owned'])
        client._request_history(None)
        client._handle(None, {'cmd': 'Retrieved', 'keys': {nonce: None}})
        self.assertFalse(client._history_synced, 'a previous connection/sync nonce is never a fence')

    def test_real_collection_flags_are_the_receipts_and_foreign_checks_never_get_an_item(self):
        data = {'player': 2, 'slot': 'Link', 'full_patch': {'placements': {
            'own': {'own': True, 'item': 'Bow'}, 'foreign': {'own': False, 'item': 'Foreign item'}}}}
        actual = [{'name': 'Owned chest', 'id': 101, 'flags': ['RealOwn', 'ChestOpen'], 'counters': [],
                   'local': True, 'item': 'Bow', 'progressive_token': {
                       'actor': 'Item_Prog_Bow_1', 'applied': 'RandoProg.Item_Prog_Bow_1'}},
                  {'name': 'Friend chest', 'id': 102, 'flags': ['RealForeign'], 'counters': ['ShopSold'],
                   'local': False, 'item': None}]
        with patch('ootrr_triforce.full_ap.load_catalog', return_value={
                    'locations': {'own': 'Owned chest', 'foreign': 'Friend chest'}}), \
                patch('ootrr_triforce.full_mod.collection_records', return_value=actual):
            rows = recovery.recovery_records(data, Path('staged-only'), {})
        self.assertEqual(rows[0]['got'], 'RealOwn')
        self.assertEqual(rows[0]['key'], record_key('Link', 'Owned chest'))
        self.assertEqual(rows[0]['also_set'], ['ChestOpen'])
        self.assertEqual(rows[0]['progressive_token'], actual[0]['progressive_token'])
        self.assertNotIn('RandoProg.Item_Prog_Bow_1', rows[0]['also_set'])
        self.assertFalse(rows[0]['restore_only'])
        self.assertEqual(rows[1]['got'], 'RealForeign')
        self.assertTrue(rows[1]['restore_only'])
        self.assertEqual(rows[1]['counters'], ['ShopSold'])
        self.assertEqual(rows[1]['restore_location_id'], 102)

    def test_only_authenticated_server_checks_supply_additional_recovery_keys(self):
        client = ArchipelagoClient.__new__(ArchipelagoClient)
        client._lock = threading.RLock()
        client.received = [{'item': 1, 'player': 2, 'location': 200}]
        client.slot, client.connected = 1, True
        client._history_synced = True
        client.names = {'Other': {'location': {200: 'Remote chest'}}}
        client.slot_info = {2: {'name': 'Friend', 'game': 'Other'}}
        client.reporter = SimpleNamespace(server_checked={101, 102})
        client.delivery = SimpleNamespace(records=[
            {'key': 'confirmed-own', 'restore_location_id': 101},
            {'key': 'confirmed-foreign', 'restore_location_id': 102, 'restore_only': True},
            {'key': 'unconfirmed', 'restore_location_id': 103},
        ])
        original = list(client.received)
        self.assertEqual(client.received_keys(), [record_key('Friend', 'Remote chest'),
                                                  'confirmed-own', 'confirmed-foreign'])
        self.assertEqual(client.received, original, 'recovery must not fabricate ReceivedItems')
        client._history_synced = False
        self.assertEqual(client.received_keys(), ['confirmed-foreign'])
        client._history_synced = True
        client.names = {}
        self.assertEqual(client.received_keys(), [], 'wait for all names before restoring/reordering history')
        client.names = {'Other': {'location': {200: 'Remote chest'}}}
        client.connected = False
        self.assertEqual(client.received_keys(), [record_key('Friend', 'Remote chest')])

    def test_trade_guard_uses_actual_consuming_location_and_preserves_its_separate_reward(self):
        rows = [{'item': 'Pocket Cucco'}, {'item': '(checked location)', 'restore_only': True}]
        recovery.bind_spent_trades(rows, {'adult_trade_shuffle': True, 'token': 'a' * 64,
            'location_ids': {'Kak Anju Trade Pocket Cucco': 999}})
        self.assertEqual(rows[0]['consumed_by_location_id'], 999)
        self.assertEqual(rows[0]['spent_actor'], 'Item_PocketCucco')
        self.assertNotIn('spent', rows[1])


@unittest.skipUnless(os.environ.get('OOT_NUP'), 'OOT_NUP not set')
class NativeRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ootrr_full.formats.inspect_nup import Nup
        from ootrr_full.game.world_maps import effective_members
        from ootrr_full.formats.inspect_resources import dictionaries, decompress
        from ootrr_full.formats import byml_codec
        from ootrr_full.patching.ammo_quantities import build_files
        from ootrr_triforce.full_mod import receipt_catalog
        from ootrr_triforce.catalog import ITEM_IDS
        cls.nup = Nup(os.environ['OOT_NUP'])
        cls.members, cls.dictionary = effective_members(cls.nup), dictionaries(cls.nup)
        cls.decompress, cls.cache = staticmethod(decompress), {}
        cls.names = ('Arrows (30)', 'Deku Seeds (30)', 'Deku Nuts (5)', 'Bombs (20)',
                     'Progressive Hookshot', 'Bow', 'Slingshot', 'Ocarina', 'Recovery Heart', 'Forest Medallion',
                     'Pocket Cucco')
        cls.recipes = receipt_catalog({'full_patch': {'placements': {}, 'remote': [{'item': n} for n in cls.names]}})
        modified, _ = build_files(cls.read, cls.names)
        info = byml_codec.load(modified[recovery.POUCH_INFO])['root']
        cls.identifiers = {name: ITEM_IDS[name] for name in cls.names}
        cls.pouch, cls.presenter, cls.entries = recovery.build_presentations(
            cls.read(recovery.POUCH), cls.read(recovery.PRESENTER), cls.read(recovery.GROUND),
            cls.recipes, cls.identifiers, {row['__RowId']: row for row in info})

    @classmethod
    def tearDownClass(cls):
        cls.nup.stream.close()

    @classmethod
    def read(cls, path):
        if path not in cls.cache:
            raw = cls.nup.read(cls.members[path])
            cls.cache[path] = cls.decompress(raw, cls.dictionary) if path.endswith('.zs') else raw
        return cls.cache[path]

    def record(self, name='Arrows (30)', *, check_only=False):
        return {'key': 'native-recovery', 'item': name, 'event': 'RandoAP_native_recovery',
                'recv': 'External.Recv', 'got': 'Real.Collection', 'also_set': ['Native.Chest.Open'],
                'counters': ['Native.Sold'], 'restore_only': check_only}

    def simulate(self, record, held=(), bools=None):
        from ootrr_full.patching.progressive import FlowEditor
        raw = recovery.bind_records(self.presenter, [record], self.entries)
        charts = {'GetPouchContent': FlowEditor(self.pouch, 'test').chart,
                  'Dm_SY_GetInEvent': FlowEditor(raw, 'test').chart}
        state = {'bools': dict(bools or {'External.Recv': True}), 'ammo': 0, 'popups': 0, 'saves': 0,
                 'counters': {}, 'owned': set(held), 'removed_trade': 0}
        def call(flow, entry):
            point = next(p for p in charts[flow].entry_points if p.name == entry)
            execute(flow, point.main_event.v)
        def execute(flow, event):
            budget = 100
            while event is not None:
                budget -= 1
                self.assertGreater(budget, 0)
                data, kind = event.data, type(event.data).__name__
                params = dict(data.params.data) if data.params is not None else {}
                if kind == 'SwitchEvent':
                    query = data.actor_query.v.v
                    if query == 'EventQueryIsGameDataBool':
                        answer = state['bools'].get(params['GameDataName'], False)
                    elif query == 'EventQueryCheckIsGet':
                        answer = params['ActorName'] in state['owned']
                    else:
                        self.assertEqual(query, 'EventQueryIsExistInPouch')
                        answer = params['Actor'] in state['owned']
                    case = data.cases.get(0 if answer else 1)
                    event = case.v if case else None
                    continue
                if kind == 'SubFlowEvent':
                    call(data.res_flowchart_name or flow, data.entry_point_name)
                else:
                    self.assertEqual(kind, 'ActionEvent')
                    action = data.actor_action.v.v
                    if action == 'EventTriggerAddOrRemovePouchContent':
                        if params['Actor'] == 'Item_PocketCucco':
                            self.assertEqual(params['Num'], -1)
                            state['owned'].remove(params['Actor'])
                            state['removed_trade'] += 1
                        else:
                            self.assertEqual(params['Actor'], 'Item_Arrow_Normal')
                            self.assertEqual(params['Num'], 30)
                            state['ammo'] += params['Num']
                    elif action == 'EventTriggerSetGameDataBool':
                        state['bools'][params['GameDataName']] = params['Value']
                    elif action == 'EventTriggerSetGameDataInt':
                        state['counters'][params['GameDataName']] = params['Value']
                    elif action == 'EventTriggerRequestOpenPickUpWindow':
                        self.assertEqual(params['ActorName'], 'Item_FullAmmo_Arrow30')
                        state['popups'] += 1
                    elif action == 'EventWait':
                        self.assertEqual(params['Frames'], 1)
                    else:
                        self.assertEqual(action, 'EventTriggerRequestAutoSave')
                        state['saves'] += 1
                event = data.nxt.v
        call('Dm_SY_GetInEvent', DISPATCH)
        return state

    def test_old_save_gets_one_native_effect_then_real_collection_and_chest_flags(self):
        result = self.simulate(self.record(), ('Item_Quiver_Medium',))
        self.assertEqual(result['ammo'], 30)
        self.assertEqual(result['popups'], 1)
        self.assertTrue(result['bools']['Real.Collection'])
        self.assertTrue(result['bools']['Native.Chest.Open'])
        self.assertEqual(result['counters']['Native.Sold'], 1)
        self.assertEqual(result['saves'], 1)

    def test_no_equipment_consumes_receipt_with_no_ammo_or_substitute_or_display(self):
        result = self.simulate(self.record())
        self.assertEqual((result['ammo'], result['popups']), (0, 0))
        self.assertTrue(result['bools']['Real.Collection'])

    def test_already_collected_physical_check_never_receives_again(self):
        result = self.simulate(self.record(), ('Item_Quiver_Medium',),
                               {'External.Recv': True, 'Real.Collection': True})
        self.assertEqual((result['ammo'], result['popups'], result['saves']), (0, 0, 0))
        self.assertFalse(result['bools']['External.Recv'])

    def test_friend_check_restores_only_native_state(self):
        result = self.simulate(self.record(check_only=True))
        self.assertEqual((result['ammo'], result['popups']), (0, 0))
        self.assertTrue(result['bools']['Real.Collection'])
        self.assertEqual(result['counters']['Native.Sold'], 1)

    def test_server_spent_trade_on_older_save_never_refunds_and_clears_stale_token_quietly(self):
        record = dict(self.record('Pocket Cucco'), spent='Server.Spent',
                      consumed_by_location_id=999, consumed_by_flag='Consuming.Point', spent_actor='Item_PocketCucco')
        for owned in ((), ('Item_PocketCucco',)):
            result = self.simulate(record, owned, {'External.Recv': True, 'Server.Spent': True,
                                                   'Consuming.Point': False})
            self.assertEqual((result['ammo'], result['popups']), (0, 0))
            self.assertTrue(result['bools']['Real.Collection'])
            self.assertFalse(result['bools']['Consuming.Point'], 'its own missing AP reward must remain recoverable')
            self.assertEqual(result['removed_trade'], int(bool(owned)))

    def test_stale_source_progressive_token_is_reconciled_after_effect_and_flags(self):
        from ootrr_full.patching.progressive import FlowEditor
        record = dict(self.record('Progressive Hookshot'), restore_location_id=101, location='Fixture source',
                      progressive_token={'actor': 'Item_Prog_Hookshot_1',
                                         'applied': 'RandoProg.Item_Prog_Hookshot_1'})
        raw = recovery.bind_records(self.presenter, [record], self.entries)
        chart = FlowEditor(raw, 'Native progressive restoration').chart
        point = next(p for p in chart.entry_points if p.name == record['event'])
        event = point.main_event.v
        self.assertEqual(type(event.data).__name__, 'SubFlowEvent')
        for expected in (record['got'], *record['also_set']):
            event = event.data.nxt.v
            self.assertEqual(event.data.params.data['GameDataName'], expected)
        event = event.data.nxt.v  # the source's saved counter
        self.assertEqual(event.data.params.data['GameDataName'], 'Native.Sold')
        event = event.data.nxt.v
        self.assertEqual(event.data.params.data['GameDataName'], record['progressive_token']['applied'])
        owned = event.data.nxt.v
        self.assertEqual(owned.data.actor_query.v.v, 'EventQueryIsExistInPouch')
        take = owned.data.cases[0].v
        self.assertEqual(take.data.params.data['Actor'], record['progressive_token']['actor'])
        self.assertEqual(take.data.params.data['Num'], -1)

    def test_major_presentation_keeps_native_camera_facing_helper(self):
        from ootrr_full.patching.progressive import FlowEditor
        flow = FlowEditor(self.presenter, 'test')
        calls = [event for event in flow.chart.events
                 if event.name.startswith(recovery.PREFIX) and type(event.data).__name__ == 'SubFlowEvent'
                 and event.data.res_flowchart_name == 'Dm_SY_TreasureboxSmall'
                 and event.data.entry_point_name == 'GetAnimationAction']
        self.assertTrue(calls)

    def test_real_weapon_recipe_initializes_only_missing_capacity_before_one_ack(self):
        from evfl.common import Argument
        from ootrr_full.patching.progressive import FlowEditor
        from ootrr_triforce.native_presentations import append_recipe
        for family in ('Bow', 'Slingshot'):
            recipe = self.recipes[family]
            small, medium, large = recipe['ensure_capacity']
            weapon = recipe['tiers'][0]
            cases = ((weapon, (), [weapon, small]),
                     (medium, (weapon, small), [medium]),
                     (large, (weapon, medium), [large]),
                     (large, (weapon, large), [large]),
                     (weapon, (weapon, medium), [weapon]))
            for given, initial, expected in cases:
                with self.subTest(family=family, given=given, initial=initial):
                    editor = FlowEditor(self.read(recovery.POUCH), 'Weapon recipe verification')
                    ack = editor.action('FixtureAck', 'GameDataActor', 'EventTriggerSetGameDataBool',
                                         {'GameDataName': 'Fixture.Committed', 'Index': -1, 'Value': True})
                    root = append_recipe(editor, recipe, 'FixtureWeapon', 'UnusedSilentGrant', ack)
                    editor.write('Weapon recipe verification')
                    owned, pending, grants, acknowledgements = set(initial), set(), [], 0
                    event = root
                    while event is not None:
                        data = event.data
                        params = {key: given if isinstance(value, Argument) else value
                                  for key, value in data.params.data.items()}
                        if type(data).__name__ == 'SwitchEvent':
                            self.assertEqual(data.actor_query.v.v, 'EventQueryCheckIsGet')
                            case = data.cases.get(0 if params['ActorName'] in owned else 1)
                            event = case.v if case else None
                            continue
                        self.assertEqual(type(data).__name__, 'ActionEvent', 'no hidden early-ACK silent subflow')
                        action = data.actor_action.v.v
                        if action == 'EventTriggerAddOrRemovePouchContent':
                            self.assertEqual(params['Num'], 1)
                            grants.append(params['Actor'])
                            pending.add(params['Actor'])
                        elif action == 'EventWait':
                            self.assertEqual(params['Frames'], 1)
                            owned.update(pending)
                            pending.clear()
                        else:
                            self.assertEqual(action, 'EventTriggerSetGameDataBool')
                            self.assertEqual(grants, expected, 'ACK must follow all native effects')
                            acknowledgements += 1
                        event = data.nxt.v
                    self.assertEqual(grants, expected)
                    self.assertEqual(acknowledgements, 1)


if __name__ == '__main__':
    unittest.main()
