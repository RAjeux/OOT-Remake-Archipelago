"""Adult start retains the native first-draw rewards and quest initialization."""
from collections import Counter
import importlib.util
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client'))
from ootrr_full.patching import adult_start
from ootrr_triforce.full_ap import full_defaults, new_world


class AdultLogicTests(unittest.TestCase):
    def test_adult_start_needs_no_free_sword_to_reach_both_ages_or_complete_its_pool(self):
        values = full_defaults()
        values['full_starting_age'] = 'adult'
        world = new_world(values, 'adult-native-prologue')
        self.assertEqual(world.pool.count('Master Sword'), 1)
        self.assertEqual(adult_start.starting_actors(world.options), ())
        self.assertTrue(world.options['open_door_of_time'])
        state, _, _ = world.c.sweep({}, Counter())
        self.assertFalse(state.has('Master Sword'))
        self.assertTrue(state.has('Time Travel'))
        self.assertTrue(all('Beyond Door of Time' in state.reached[age] for age in ('child', 'adult')))
        inventory = Counter(world.pool)
        self.assertTrue(world.reach(inventory)[1])
        self.assertTrue(all(world.reachable(gid, inventory) for gid in world.names))

    @unittest.skipUnless(importlib.util.find_spec('zstandard'), 'native build codec not installed')
    def test_initial_pouch_does_not_duplicate_the_prologue_weapon(self):
        from ootrr_full.randomizer.randomizer_core import starting_pouch_items
        for shuffle in (False, True):
            self.assertEqual(starting_pouch_items({'options': {'starting_age': 'adult',
                                                               'shuffle_master_sword': shuffle}}), ['Pouch_Amiibo'])


@unittest.skipUnless(os.environ.get('OOT_NUP'), 'OOT_NUP not set')
class NativeAdultPrologueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ootrr_full.formats.inspect_nup import Nup
        from ootrr_full.formats.inspect_resources import dictionaries, decompress
        cls.nup = Nup(os.environ['OOT_NUP'])
        cls.dictionaries = dictionaries(cls.nup)
        cls.decompress = staticmethod(decompress)
        cls.cache = {}

    @classmethod
    def tearDownClass(cls):
        cls.nup.stream.close()

    @classmethod
    def read(cls, path):
        if path not in cls.cache:
            frame = cls.nup.read(cls.nup.latest('romfs/' + path))
            cls.cache[path] = cls.decompress(frame, cls.dictionaries) if path.endswith('.zs') else frame
        return cls.cache[path]

    def chart(self, name):
        from ootrr_full.patching.event_patch import _flow
        return _flow(self.read('Event/EventFlow/' + name + '.bfevfl.zs')).flowchart

    def events(self, name, entry):
        from ootrr_full.patching.event_info import reachable
        chart = self.chart(name)
        root = next(point for point in chart.entry_points if point.name == entry)
        return reachable(root.main_event.v)

    def test_new_anchor_uses_the_native_pedestal_transform_without_changing_any_original_actor(self):
        from ootrr_full.formats import byml_codec
        raw = self.read(adult_start.SPAWN_MAP)
        before = byml_codec.load(raw)['root']
        after = byml_codec.load(adult_start.add_start_marker(raw))['root']
        self.assertEqual(after['Actors'][:-1], before['Actors'])
        marker = after['Actors'][-1]
        sword = next(row for row in before['Actors'] if row.get('Gyaml') == 'Obj_TimeTemple_MasterSword_A_01')
        self.assertEqual(marker['Gyaml'], 'StartPos')
        self.assertEqual(marker['Name'], adult_start.WARP_PARAMS['EventStarterName'])
        for field in ('Translate', 'Rotate', 'SRTHash'):
            self.assertEqual(marker[field], sword[field])
        self.assertNotIn(int(marker['Hash']), {int(row['Hash']) for row in before['Actors']})

    def test_opening_starts_the_original_first_draw_in_its_native_child_scene(self):
        from ootrr_full.patching.event_patch import _flow
        raw, report = adult_start.patch_opening(self.read('Event/EventFlow/OpeningEvent.bfevfl.zs'))
        events = {event.name: event for event in _flow(raw).flowchart.events}
        self.assertEqual(events[adult_start.ANCHOR].data.nxt.v.name, adult_start.ERA_EVENT)
        self.assertEqual(events[adult_start.ERA_EVENT].data.params.data['Value'], True)
        self.assertEqual(events[adult_start.WARP_EVENT].data.params.data, adult_start.WARP_PARAMS)
        self.assertEqual(report['banc'], 'Market_Child')
        from ootrr_full.formats import byml_codec
        rows = byml_codec.load(self.read('RSDB/EventSetting.Product.111.rstbl.byml.zs'))['root']
        boot = next(row for row in rows if row['__RowId'] == adult_start.WARP_PARAMS['BootEventName'])
        self.assertEqual(boot['EntryPointName'], 'DoorOfTime_Draw')
        self.assertTrue(boot['EventBaseSetting'].endswith('/StarterPos.game__event__GameEventBaseSetting.gyml'))

    def test_native_chain_changes_age_runs_rauru_then_initializes_both_quests(self):
        # These are unchanged native continuations, not newly invented grants or quest counters.
        draw = self.events('DoorOfTime', 'DoorOfTime_Draw')
        self.assertTrue(any(getattr(event.data, 'params', None)
                            and event.data.params.data.get('BootEventName') == 'SageRoom_MeetGanondorf' for event in draw))
        ganondorf = self.events('DoorOfTime', 'SageRoom_MeetGanondorf')
        self.assertTrue(any(getattr(event.data, 'params', None)
                            and event.data.params.data.get('GameDataName') == adult_start.ERA_FLAG
                            and event.data.params.data.get('Value') is False for event in ganondorf))
        self.assertTrue(any(getattr(event.data, 'params', None)
                            and event.data.params.data.get('BootEventName') == 'SageRoom_MeetRauru' for event in ganondorf))
        self.assertTrue(any(getattr(event.data, 'params', None)
                            and event.data.params.data.get('EventName') == 'Dm_TimeTemple_0040' for event in ganondorf))
        rauru = self.events('DoorOfTime', 'SageRoom_MeetRauru')
        params = [event.data.params.data for event in rauru if getattr(event.data, 'params', None)]
        self.assertTrue(any(row.get('EventName') == 'Dm_SageRoom_0005' for row in params))
        self.assertTrue(any(row.get('BootEventName') == 'Market_Adult_AllSage_Start' for row in params))
        self.assertTrue(any(row.get('ChallengeName') == 'DoorOfTime' and row.get('StepName') == 'Complete' for row in params))
        arrival = self.events('AllSage', 'Market_Adult_AllSage_Start')
        params = [event.data.params.data for event in arrival if getattr(event.data, 'params', None)]
        self.assertTrue(any(row.get('ChallengeName') == 'AllSage' and row.get('StepName') == 'Step01' for row in params))
        self.assertTrue(any(row.get('EventName') == 'Dm_TimeTemple_0050' for row in params))
        self.assertTrue(any(row.get('ChallengeName') == 'SageOfLight' and row.get('StepName') == 'Complete' for row in params))

    def test_two_original_reward_hooks_preserve_their_native_collection_flags(self):
        from ootrr_full.patching.event_patch import patch_event_params, add_collection_markers, _flow
        from ootrr_full.patching.special_item_shuffle import patch_flow
        for name, event, param, before in (('DoorOfTime', 'Event115', 'Actor', 'Weapon_Sword_Master'),
                                           ('Dm_SageRoom_0005', 'Event48', 'ActorName', 'Item_Medal_Light')):
            raw = patch_event_params(self.read('Event/EventFlow/' + name + '.bfevfl.zs'),
                                     [(event, param, before, 'Item_AP_PrologueReward')])
            flag = 'RandoCheck.AdultPrologue.' + event
            raw, markers = add_collection_markers(raw, {event: flag})
            if name == 'DoorOfTime':
                raw, _ = patch_flow('Event/EventFlow/DoorOfTime.bfevfl.zs', raw)
            events = {row.name: row for row in _flow(raw).flowchart.events}
            self.assertEqual(events[event].data.params.data[param], 'Item_AP_PrologueReward')
            marker = events[event].data.nxt.v
            self.assertEqual(marker.data.params.data['GameDataName'], flag)
            self.assertEqual(marker.data.params.data['Value'], True)
            if name == 'DoorOfTime':
                self.assertIs(events[event].data.params.data['IsEquipDIrect'], False)
            from ootrr_triforce.full_events import guard_gifts
            guarded = {row.name: row for row in _flow(guard_gifts(raw, markers)).flowchart.events}
            once = guarded['OOTRR_APOnce_' + event]
            self.assertEqual(once.data.params.data['GameDataName'], flag)
            self.assertEqual(once.data.cases[1].v.name, event)
            self.assertEqual(once.data.cases[0].v.name, marker.data.nxt.v.name)
            # Execute the isolated handover transaction twice, then an older
            # save whose receipt flag was restored. Only the first can grant.
            collected, grants = False, 0
            for _ in range(2):
                node = once.data.cases[0 if collected else 1].v
                while node.name != marker.data.nxt.v.name:
                    if node.name == event:
                        grants += 1
                    elif node.name == marker.name:
                        collected = True
                    else:
                        self.fail('Unexpected prologue transaction node: ' + node.name)
                    node = node.data.nxt.v
            self.assertEqual(grants, 1)
            self.assertEqual(once.data.cases[0].v.name, marker.data.nxt.v.name)

    def test_native_swordless_return_prompt_and_arrival_equipment_guards_are_active(self):
        from ootrr_full.patching.master_sword_item import (pedestal_put_in_without_sword, PEDESTAL_PACK,
                                                          PUT_IN_CLIENT, PULL_OUT)
        from ootrr_full.formats.inspect_resources import sarc
        from ootrr_full.formats import byml_codec
        from ootrr_full.patching.special_item_shuffle import patch_flow
        from ootrr_full.patching.event_patch import _flow
        files = sarc(pedestal_put_in_without_sword(self.read(PEDESTAL_PACK)))
        self.assertEqual(byml_codec.load(files[PUT_IN_CLIENT])['root']['ActionType'], PULL_OUT)
        for name, target in (('Dm_TimeTemple_0085', 'Event9'), ('Dm_SY_BancChangeArrive', 'Event37')):
            raw, _ = patch_flow('Event/EventFlow/' + name + '.bfevfl.zs',
                                 self.read('Event/EventFlow/' + name + '.bfevfl.zs'))
            chart = _flow(raw).flowchart
            guard = next(event for event in chart.events if event.name.startswith('RandoMasterSwordOwned_')
                         and event.data.cases[0].v.name == target)
            self.assertEqual(guard.data.params.data, {'Actor': 'Weapon_Sword_Master', 'Num': 1})
            self.assertNotEqual(getattr(guard.data.cases.get(1), 'v', None), guard.data.cases[0].v)


if __name__ == '__main__':
    unittest.main()
