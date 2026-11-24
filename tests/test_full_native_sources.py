"""Compose full-engine and additional native reward patches on real source flows."""
from collections import defaultdict
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client'))
from ootrr_triforce.full_ap import new_world, full_defaults
from ootrr_full.game.native_extras import entries
from ootrr_full.patching.native_extras import _operations, apply
from ootrr_full.patching.event_patch import _flow, patch_event_params


def extra_plan():
    matches = entries()
    return {'matches': matches, 'placements': [{'id': gid, 'after': 'Item_AP_Extra_' + str(index)}
                                              for index, gid in enumerate(matches)]}


class SourceIdentityTests(unittest.TestCase):
    def test_structural_reward_adapter_leaves_loose_key_pickups_to_their_own_adapter(self):
        from ootrr_full.game.loose_keys import entries as loose_keys
        plan = extra_plan()
        expected = _operations(plan)
        for gid, row in loose_keys({'individual_smallkeys': True}).items():
            plan['matches'][gid] = row
            plan['placements'].append({'id': gid, 'after': 'Item_AP_ForeignKeyPickup'})
        self.assertEqual(_operations(plan), expected)

    def test_physical_handover_targets_are_unique_except_the_explicit_ten_case_bean_dispatcher(self):
        world = new_world(full_defaults(), 'physical-source-identity')
        targets = defaultdict(set)
        for gid, entry in world.c.shuffled.items():
            for variant in entry['variants']:
                if 'event' in variant:
                    targets[(variant['resource'], variant['event'], variant['param'])].add(gid)
        duplicates = {key: values for key, values in targets.items() if len(values) > 1}
        self.assertEqual(len(duplicates), 1)
        key, gids = next(iter(duplicates.items()))
        self.assertEqual(key, ('Event/EventFlow/SimpleShop.bfevfl.zs', 'Event182', 'ReveiveItem'))
        self.assertEqual(len(gids), 10)
        self.assertTrue(all('bean_index' in world.c.shuffled[gid] for gid in gids))
        # Structural edits must not replace an already shuffled upstream reward.
        upstream = {(variant['resource'], variant['event']) for entry in world.c.shuffled.values()
                    if entry['source'] not in {'native_extra', 'adult_trade', 'native_cow'}
                    for variant in entry['variants'] if 'event' in variant}
        edits = {(path, operation['event']) for path, operations in _operations(extra_plan()).items()
                 for operation in operations if 'event' in operation}
        self.assertFalse(upstream & edits)


@unittest.skipUnless(os.environ.get('OOT_NUP'), 'OOT_NUP not set')
class NativeCompositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ootrr_full.formats.inspect_nup import Nup
        from ootrr_full.formats.inspect_resources import dictionaries, decompress
        cls.nup = Nup(os.environ['OOT_NUP'])
        cls.dictionary = dictionaries(cls.nup)
        cls.decompress = staticmethod(decompress)
        cls.cache = {}

    @classmethod
    def tearDownClass(cls):
        cls.nup.stream.close()

    @classmethod
    def read(cls, path):
        if path not in cls.cache:
            cls.cache[path] = cls.decompress(cls.nup.read(cls.nup.latest('romfs/' + path)), cls.dictionary)
        return cls.cache[path]

    def test_storm_song_heart_and_first_bug_win_remain_distinct_after_composition(self):
        path = 'Event/EventFlow/MiniGame_FrogTenors.bfevfl.zs'
        storm_actor = 'Item_AP_StormSongReward'
        original = self.read(path)
        composed = {path: patch_event_params(original, [('Event384', 'ActorName', 'Obj_Heart_Piece', storm_actor)])}
        plan = extra_plan()
        apply(plan, composed, self.read)
        chart = _flow(composed[path]).flowchart
        events = {event.name: event for event in chart.events}
        self.assertEqual(events['Event384'].data.params.data['ActorName'], storm_actor)
        bug_gid = 'native_extra#ZR Frogs Bug Game'
        bug_actor = next(row['after'] for row in plan['placements'] if row['id'] == bug_gid)
        for name in ('Event161', 'Event75'):
            self.assertEqual(events[name].data.params.data['ActorName'], bug_actor)
        # Ordinary repeat wins keep their native blue-rupee reward.
        old = {event.name: event for event in _flow(original).flowchart.events}
        for event in chart.events:
            if event.name in old and getattr(event.data, 'entry_point_name', '') == 'MushiToriGame':
                if event.name not in {'Event161', 'Event75'}:
                    self.assertEqual(event.data.params.data, old[event.name].data.params.data)
        # Follow local sub-calls as well as event edges: bug game never grants the Storm reward.
        from ootrr_full.patching.event_info import reachable
        roots = {point.name: point.main_event.v for point in chart.entry_points}
        pending, visited = [roots['MushiToriGame']], set()
        while pending:
            for event in reachable(pending.pop()):
                if event.name in visited:
                    continue
                visited.add(event.name)
                call = event.data
                if getattr(call, 'res_flowchart_name', None) == '' and call.entry_point_name in roots:
                    pending.append(roots[call.entry_point_name])
        self.assertNotIn('Event384', visited)

    def test_all_extra_sources_patch_together_and_register_exactly_ten_new_purchase_flags(self):
        from ootrr_full.formats import byml_codec
        from ootrr_full.patching.soul_adapter import murmur3
        from ootrr_full.game.tracking_metadata import GAMEDATA
        current, plan = {}, extra_plan()
        operations = apply(plan, current, self.read)
        self.assertEqual(set(operations), {
            'Event/EventFlow/MiniGame_FrogTenors.bfevfl.zs',
            'Event/EventFlow/Npc_Hylia_020_Shop_Child.bfevfl.zs',
            'Event/EventFlow/Npc_Goron_Medigoron_Adult.bfevfl.zs',
            'Event/EventFlow/SimpleShop.bfevfl.zs',
            'Event/EventFlow/Npc_Hylia_047_Child.bfevfl.zs'})
        schema = byml_codec.load(current[GAMEDATA])['root']['Data']['Bool']
        saved = {int(row['Hash']) for row in schema if row.get('SaveFileIndex') == 0}
        for row in entries().values():
            self.assertIn(murmur3(row['native_flag']), saved)
        chart = _flow(current['Event/EventFlow/SimpleShop.bfevfl.zs']).flowchart
        selector = next(event for event in chart.events if event.name == 'FullBeanSelectPurchase')
        self.assertEqual(set(selector.data.cases), set(range(10)))
        self.assertEqual(len({case.v.name for case in selector.data.cases.values()}), 10)
        gifts = [event for event in chart.events if event.name.startswith('FullBeanPurchase_')]
        self.assertEqual(len(gifts), 10)
        self.assertEqual(len({event.data.params.data['ReveiveItem'] for event in gifts}), 10)


if __name__ == '__main__':
    unittest.main()
