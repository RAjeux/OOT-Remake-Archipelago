"""The native two-key child route never becomes a general shuffled-key shortcut."""
from collections import Counter
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'client'))
from ootrr_full.game.spirit_layout import CHILD_ROUTE,native_keys
from ootrr_full.logic.rules import Logic
from ootrr_full.logic.world import World
from ootrr_triforce.full_ap import full_defaults,new_world


class SpiritKeys(unittest.TestCase):
    def test_only_native_key_layouts_use_the_observed_shortcut(self):
        self.assertFalse(native_keys(dict(individual_smallkeys=True,shuffle_smallkeys='keysanity',shuffle_chests=True)))
        for values in ({},{'shuffle_smallkeys':'vanilla'}, {'shuffle_chests':False},{'chest_scope':'overworld'}):
            self.assertTrue(native_keys(dict(individual_smallkeys=True,**values)) if values else native_keys({}))

    def test_observed_child_route_requires_both_keys_and_all_proven_equipment(self):
        logic=Logic(World(),{'native_spirit_keys':True,'shuffle_master_sword':True})
        rule=logic.compile(CHILD_ROUTE)
        gear={'Kokiri Sword':1,'Slingshot':1,'Bomb Bag':1,'Dins Fire':1,'Magic Meter':1,
              'Ocarina':1,'Zeldas Lullaby':1,'Small Key (Spirit Temple)':2}
        state=logic.new_state(gear)
        self.assertTrue(rule(state,state.counts,'child'))
        self.assertFalse(rule(state,state.counts,'adult'))
        for item in gear:
            without=dict(gear);without[item]-=1
            state=logic.new_state(without)
            self.assertFalse(rule(state,state.counts,'child'),item)

    def test_native_vanilla_keys_no_longer_deadlock_strength_behind_five_keys(self):
        world=new_world(dict(full_defaults(),full_shuffle_chests=False,full_shuffle_boss_rewards=False,
                             full_shuffle_smallkeys='vanilla',full_key_rings='off'),'native-child-spirit-keys')
        reached,victory=world.reach(Counter(world.pool))
        self.assertTrue(victory)
        self.assertIn('Spirit Temple Silver Gauntlets Chest',world.c.sweep({},Counter(world.pool))[1])


if __name__=='__main__':unittest.main()
