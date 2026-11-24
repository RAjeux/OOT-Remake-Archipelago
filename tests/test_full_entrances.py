"""Paired dungeon entrances keep native return ages, AP routes and reward edits."""
import copy
from collections import Counter
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client'))
from ootrr_full.game.dungeon_entrances import (catalogue, normalize, age_errors,
                                              region_targets, choose, moves, apply)
from ootrr_full.logic.world import World
from ootrr_full.logic import rando_options
from ootrr_full.randomizer.full_randomizer import ap_settings
from ootrr_triforce.full_ap import full_defaults, new_world


class FullDungeonEntranceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.names = [row['name'] for row in catalogue()['connections']]
        cls.native = dict(zip(cls.names, cls.names))

    def test_catalogue_has_every_unique_supported_door_and_no_boss_or_castle_guess(self):
        self.assertEqual(len(self.names), 11)
        self.assertNotIn('Ganons Castle', self.names)
        ids = [number for row in catalogue()['connections'] for number in [*row['doors'], row['back']]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {row['hash'] for row in catalogue()['doors']})

    def test_native_layout_does_not_edit_any_door(self):
        self.assertEqual(moves(self.native), [])
        self.assertEqual(age_errors(self.native), [])

    def test_ordinary_returns_follow_the_new_entrance_in_the_same_permutation(self):
        layout = dict(self.native, **{'Deku Tree': 'Jabu Jabus Belly', 'Jabu Jabus Belly': 'Deku Tree'})
        targets = region_targets(layout)
        self.assertEqual(targets['KF Outside Deku Tree', 'Deku Tree Lobby'], 'Jabu Jabus Belly Beginning')
        self.assertEqual(targets['Jabu Jabus Belly Beginning', 'Zoras Fountain'], 'KF Outside Deku Tree')
        self.assertEqual(len(moves(layout)), 5)

    def test_an_adult_dungeon_cannot_return_through_child_only_jabu_arrival(self):
        layout = dict(self.native, **{'Ice Cavern': 'Jabu Jabus Belly', 'Jabu Jabus Belly': 'Ice Cavern'})
        self.assertTrue(any('adult' in reason for reason in age_errors(layout)))

    def test_duplicate_or_missing_dungeons_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'exactly once'):
            normalize(dict(self.native, **{'Deku Tree': 'Fire Temple'}))
        with self.assertRaisesRegex(ValueError, 'exactly once'):
            normalize({'Deku Tree': 'Deku Tree'})

    def test_actual_ap_world_uses_the_layout_and_reaches_every_enabled_source(self):
        world = new_world(dict(full_defaults(), full_shuffle_entrances='dungeons'), 'coupled-native-routes-test')
        self.assertNotEqual(world.c.entrances, self.native)
        self.assertEqual(age_errors(world.c.entrances), [])
        inventory = Counter(world.pool)
        self.assertTrue(world.reach(inventory)[1])
        self.assertEqual([name for gid, name in world.names.items() if not world.reachable(gid, inventory)], [])
        targets = region_targets(world.c.entrances)
        for row in catalogue()['connections']:
            target = targets[tuple(row['entry'])]
            actual = [name for name, _ in world.c.logic.regions[row['entry'][0]]['exits']]
            self.assertIn(target, actual)

    def test_selection_is_deterministic_and_does_not_mutate_the_frozen_world_resources(self):
        data = World()
        fingerprint = data.fingerprint()
        original = copy.deepcopy(data.regions)
        settings = ap_settings(rando_options.defaults(), True)
        first = choose(data, settings, 'same-native-entrance-test')
        self.assertEqual(choose(data, settings, 'same-native-entrance-test'), first)
        self.assertEqual(data.regions, original)
        self.assertEqual(data.fingerprint(), fingerprint)

    def test_unshuffled_ocarina_cannot_be_locked_behind_its_own_well_entrance(self):
        unsafe = dict(self.native, **{'Deku Tree': 'Bottom of the Well',
                                    'Bottom of the Well': 'Deku Tree'})
        safe = dict(self.native, **{'Forest Temple': 'Ice Cavern', 'Ice Cavern': 'Forest Temple'})
        values = dict(full_defaults(), full_shuffle_entrances='dungeons',
                      full_shuffle_quest_rewards=False, full_shuffle_boss_rewards=False)
        with patch('ootrr_full.game.dungeon_entrances.layout_candidates', return_value=iter((unsafe, safe))):
            world = new_world(values, 'unshuffled-native-ocarina-cycle')
        self.assertEqual(world.c.entrances, safe)
        self.assertTrue(world.reach(Counter(world.pool))[1])


ROMFS = os.environ.get('OOT_ROMFS') or os.environ.get('OOTRR_ROMFS')


@unittest.skipUnless(ROMFS, 'Set OOT_ROMFS for native 1.1.1 dungeon destination validation.')
class NativeDungeonEntranceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ootrr_triforce import app_runtime
        app_runtime._resource_override = ROOT / 'dist'
        from ootrr_triforce.mod_codec import Codec
        cls.romfs = Path(ROMFS)
        cls.codec = Codec((cls.romfs / 'Pack/ZsDic.pack.zs').read_bytes())

    def test_native_destination_only_edits_preserve_every_other_map_field(self):
        from ootrr_full.formats import byml_codec
        names = [row['name'] for row in catalogue()['connections']]
        layout = dict(zip(names, names))
        layout.update({'Deku Tree': 'Jabu Jabus Belly', 'Jabu Jabus Belly': 'Deku Tree'})
        modified = {}
        def read(path):
            raw = self.codec.decode((self.romfs / path).read_bytes())
            document = byml_codec.load(raw)
            # Stand in for an already applied AP item placement. Entrance edits
            # must preserve this unrelated native map field verbatim.
            for actor in document['root']['Actors']:
                if actor.get('Gyaml', '').startswith('Obj_TBox'):
                    actor.setdefault('Dynamic', {})['Drop__DropActor'] = 'TBox_Rupee_Purple'
                    break
            return byml_codec.dump(document)
        report = apply(layout, read, lambda path, raw: modified.__setitem__(path, raw))
        self.assertEqual(report['actors'], 5)
        self.assertTrue(modified)
        for path, raw in modified.items():
            self.assertEqual(byml_codec.load(byml_codec.dump(byml_codec.load(raw))), byml_codec.load(raw))

    def test_every_supported_door_and_start_position_matches_the_actual_game_maps(self):
        from ootrr_full.formats import byml_codec
        known = {}
        for row in catalogue()['doors']:
            if row['file'] not in known:
                document = byml_codec.load(self.codec.decode((self.romfs / row['file']).read_bytes()))
                known[row['file']] = {str(actor['Hash']): actor for actor in document['root']['Actors']}
            actor = known[row['file']][row['hash']]
            self.assertEqual(actor['Gyaml'], 'FieldAndDungeonEntranceEventRequestActor')
            self.assertEqual(actor['Dynamic'].get('NextStartPosName', ''), row['start'])
            for age, key in (('adult', 'NextBancParamNameAdult'), ('child', 'NextBancParamNameChild')):
                self.assertEqual(actor['Dynamic'].get(key, ''), row[age])


if __name__ == '__main__':
    unittest.main()
