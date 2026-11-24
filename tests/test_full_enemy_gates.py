"""Every native difficulty gate has conservative, age-specific AP combat rules."""
from collections import Counter
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client'))
from ootrr_full.game.enemy_gates import PASSAGES, requirement, forest_souls, FOREST_GUARDS
from ootrr_full.logic.rules import Logic
from ootrr_full.logic.world import World
from ootrr_triforce.full_ap import full_defaults, new_world


class FullEnemyGateTests(unittest.TestCase):
    def test_every_enabled_native_gate_has_one_ap_contract(self):
        raw = (ROOT / 'moteur/ootrr-ap/randomizer/core/src/difficulty/gates.rs').read_text(encoding='utf-8')
        block = raw.split('pub const GATES:', 1)[1].split('];', 1)[0]
        native = {int(number): name for number, name in re.findall(r'Gate \{ id: (\d+),.*?map: "([^"]+)"', block)}
        self.assertEqual({row[0]: row[1] for row in PASSAGES},
                         {number: name for number, name in native.items() if number != 7})
        regions = {row['region_name'] for row in World().regions}
        self.assertTrue(all(target in regions for row in PASSAGES for target in row[2]))

    def test_native_child_and_adult_fights_require_melee_only_at_their_actual_age(self):
        settings = {'enemy_gates': True, 'shuffle_master_sword': True, 'open_forest': 'closed'}
        logic = Logic(World(), settings)
        for _, _, regions, age, shield in PASSAGES:
            rule = logic.compile(requirement('Source', regions[0], settings))
            empty = logic.new_state({})
            self.assertFalse(rule(empty, empty.counts, age), regions[0])
            other = 'child' if age == 'adult' else 'adult'
            self.assertTrue(rule(empty, empty.counts, other), regions[0])
            owned = {'Kokiri Sword': 1, 'Master Sword': 1, 'Buy Deku Shield': 1}
            state = logic.new_state(owned)
            self.assertTrue(rule(state, state.counts, age), (regions[0], shield))

    def test_closed_forest_gate_is_absent_when_the_native_adapter_suppresses_it(self):
        for settings in ({'enemy_gates': False}, {'enemy_gates': True, 'open_forest': 'closed_deku'},
                         {'enemy_gates': True, 'open_forest': 'closed', 'open_kakariko': 'open'}):
            self.assertIsNone(requirement('Kokiri Forest', 'KF Outside Deku Tree', settings))

    def test_closed_forest_requires_souls_of_its_actual_bound_native_guards(self):
        from ootrr_triforce.full_ap import load_catalog
        from ootrr_full.patching.soul_adapter import plan_souls
        catalogue = load_catalog()
        world = World()
        for mode in ('off', 'bosses', 'all', 'regional'):
            plan = plan_souls(mode, catalogue['enemies'], world.regions)
            required = forest_souls(plan)
            self.assertEqual(bool(required), mode in ('all', 'regional'))
            settings = {'enemy_gates': True, 'open_forest': 'closed', 'enemy_gate_souls': required}
            logic = Logic(world, settings)
            rule = logic.compile(requirement('Kokiri Forest', 'KF Outside Deku Tree', settings))
            state = logic.new_state({'Kokiri Sword': 1})
            self.assertEqual(rule(state, state.counts, 'child'), not required)
            state = logic.new_state({'Kokiri Sword': 1, **dict.fromkeys(required, 1)})
            self.assertTrue(rule(state, state.counts, 'child'))
        actual = {str(row['hash']) for row in catalogue['enemies'] if row['actor'] == 'Enemy_Dekubaba_Withered'}
        self.assertTrue(FOREST_GUARDS <= actual)

    def test_full_maximum_inventory_wins_with_and_without_coupled_dungeons(self):
        for entrances in ('off', 'dungeons'):
            world = new_world(dict(full_defaults(), full_enemy_gates=True,
                                   full_shuffle_entrances=entrances), 'native-enemy-gates')
            self.assertTrue(world.reach(Counter(world.pool))[1])
            self.assertTrue({'Deku Shield', 'Hylian Shield'} <= world.progression)


if __name__ == '__main__':
    unittest.main()
