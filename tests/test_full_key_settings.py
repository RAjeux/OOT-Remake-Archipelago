"""Individual AP key settings retain historical rooms and real key capacity."""
from collections import Counter
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client'))
from ootrr_triforce.full_ap import full_defaults, new_world, translate_legacy_options
from ootrr_full.logic import rando_options
from ootrr_full.patching.key_adapter import RING_DUNGEONS, small_key_item
from ootrr_full.game.native_key_limits import NATIVE_SMALL_KEYS, THRESHOLDS, enabled as native_limits
from ootrr_full.logic.rules import Logic
from ootrr_full.logic.world import World


class IndividualKeySettingsTests(unittest.TestCase):
    def test_new_rooms_enable_individual_keys_but_missing_historical_value_is_false(self):
        self.assertTrue(full_defaults()['full_individual_smallkeys'])
        self.assertFalse(rando_options.stored_value({}, 'individual_smallkeys'))
        self.assertNotIn('individual_smallkeys', rando_options.recorded({'individual_smallkeys': False}))
        self.assertEqual(rando_options.recorded({'individual_smallkeys': True}), {'individual_smallkeys': True})

    def test_each_supported_scope_has_native_safe_capacity_and_victory(self):
        for mode in ('dungeon', 'any_dungeon', 'overworld', 'regional', 'keysanity'):
            world = new_world(dict(full_defaults(), full_key_rings='off', full_shuffle_smallkeys=mode), 'ap-individual-keys')
            pool = Counter(world.pool)
            self.assertEqual({small_key_item(folder): pool[small_key_item(folder)] for folder in RING_DUNGEONS},
                             {small_key_item(folder): count for folder, count in NATIVE_SMALL_KEYS.items()})
            self.assertEqual(len(world.pool), len(world.names))
            self.assertTrue(world.reach(pool)[1], mode)
            self.assertTrue(set(world.c.individual_keys) <= world.progression)

    def test_keysanity_has_no_own_world_quota_and_accepts_overworld_handovers(self):
        world = new_world(dict(full_defaults(), full_key_rings='off', full_shuffle_smallkeys='keysanity'), 'global-individual-keys')
        for item in world.c.individual_keys:
            self.assertNotIn(item, world.local_only)
            self.assertTrue(world.can_hold('npc#Market Lost Dog', item), item)

    def test_selected_ring_dungeons_and_individual_dungeons_do_not_duplicate_keys(self):
        world = new_world(dict(full_defaults(), full_key_rings='choose', full_key_rings_list=['Forest Temple']), 'mixed-ring-keys')
        pool = Counter(world.pool)
        self.assertEqual(pool['Small Key Ring (Forest Temple)'], 1)
        self.assertEqual(pool['Small Key (Forest Temple)'], 0)
        self.assertEqual(pool['Small Key (Water Temple)'], 4)
        self.assertTrue(world.reach(pool)[1])

    def test_native_and_removed_modes_do_not_add_individual_key_items(self):
        for mode in ('vanilla', 'remove'):
            world = new_world(dict(full_defaults(), full_key_rings='off', full_shuffle_smallkeys=mode), 'native-key-settings')
            self.assertFalse(world.c.individual_keys)
            self.assertFalse(any(item.startswith('Small Key (') for item in world.pool))
            self.assertTrue(world.reach(Counter(world.pool))[1])

    def test_legacy_key_scope_does_not_overwrite_explicit_individual_ring_choice(self):
        values = dict(full_defaults(), full_key_rings='off')
        result = translate_legacy_options({'shuffle_smallkeys': 'keysanity'}, values)
        self.assertEqual(result['full_key_rings'], 'off')
        self.assertTrue(result['full_individual_smallkeys'])

    def test_full_native_key_set_resolves_only_imported_thresholds_above_its_total(self):
        for item, total in THRESHOLDS.items():
            for active in (False, True):
                logic = Logic(World(), {'native_key_limits': active})
                for required in (1, total, total + 1, total + 2):
                    rule = logic.compile(f'({item!r}, {required})')
                    threshold = min(total, required) if active else required
                    state = logic.new_state({item: threshold})
                    self.assertTrue(rule(state, state.counts, 'adult'))
                    state = logic.new_state({item: threshold - 1})
                    self.assertFalse(rule(state, state.counts, 'adult'))

    def test_loose_key_checks_follow_key_shuffle_and_chest_toggle(self):
        from ootrr_full.game.loose_keys import entries
        for field, value in (('full_shuffle_chests', False), ('full_shuffle_smallkeys', 'vanilla')):
            values = dict(full_defaults(), full_key_rings='off', **{field: value})
            world = new_world(values, 'native-loose-key-toggle')
            self.assertFalse(set(entries({'individual_smallkeys': True})) & set(world.names))

    def test_unshuffled_chests_retain_native_grouped_keys_and_fire_route(self):
        for selected in ([], ['Forest Temple', 'Water Temple', 'Shadow Temple', 'Gerudo Training Ground']):
            values = dict(full_defaults(), full_shuffle_chests=False,
                          full_shuffle_ganon_bosskey='vanilla', full_shuffle_smallkeys='dungeon',
                          full_key_rings='choose' if selected else 'off', full_key_rings_list=selected)
            world = new_world(values, 'native-fire-keys-with-shuffled-surroundings')
            self.assertFalse(world.c.individual_keys)
            self.assertEqual(world.c.starting['Small Key (Fire Temple)'], 1)
            self.assertEqual(world.c.base['Fire Temple Near Boss Chest'], 'Small Key (Fire Temple)')
            reached, victory = world.reach(Counter(world.pool))
            self.assertTrue(victory)
            self.assertEqual([name for gid, name in world.names.items() if world.vnames[gid] not in reached], [])

    def test_native_key_limits_remain_active_for_all_unshuffled_key_layouts(self):
        for field, value in (('shuffle_chests', False), ('shuffle_smallkeys', 'vanilla'),
                             ('chest_scope', 'overworld')):
            self.assertTrue(native_limits({'individual_smallkeys': True, field: value}))
            self.assertTrue(native_limits({'individual_smallkeys': False, field: value}))
        world = new_world(dict(full_defaults(), full_shuffle_chests=False,
                              full_shuffle_ganon_bosskey='vanilla', full_shuffle_smallkeys='vanilla',
                              full_key_rings='off', full_shuffle_enemy_spawns='regional'),
                          'native-water-four-key-completion')
        self.assertTrue(world.c.settings['native_key_limits'])
        reached, victory = world.reach(Counter(world.pool))
        self.assertTrue(victory)
        self.assertEqual([name for gid, name in world.names.items() if world.vnames[gid] not in reached], [])


if __name__ == '__main__':
    unittest.main()
