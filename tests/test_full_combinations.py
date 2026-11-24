"""Regression for native rewards used alongside partially shuffled AP sources."""
from collections import Counter
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client'))
from ootrr_triforce.full_ap import full_defaults, new_world


class PartialSourceTests(unittest.TestCase):
    def test_native_and_ap_skulltulas_both_allow_every_native_threshold_reward(self):
        for scope in ('off', 'dungeons', 'overworld', 'all'):
            with self.subTest(scope=scope):
                world = new_world(dict(full_defaults(), full_tokensanity=scope), 'native-token-thresholds')
                inventory = Counter(world.pool)
                self.assertTrue(world.reach(inventory)[1])
                for threshold in (10, 20, 30, 40, 50):
                    gid = world.gids[f'Kak {threshold} Gold Skulltula Reward']
                    self.assertTrue(world.in_logic[gid], 'Unshuffled physical tokens are part of maximum inventory')
                    self.assertTrue(world.reachable(gid, inventory))

    def test_planted_platforms_keep_all_ten_ap_bean_purchases(self):
        from ootrr_full.patching.native_extras import start_values
        for shuffled, counter in ((False, 9), (True, 0)):
            with self.subTest(shuffled=shuffled):
                values = start_values({'plant_beans': True, 'shuffle_bean_merchant': shuffled})
                self.assertEqual(values['Get_MagicBeans'], counter)
                self.assertEqual(sum(name.startswith('IsPlantedMagicBean_SmallFarm.') and value is True
                                     for name, value in values.items()), 10)


if __name__ == '__main__':
    unittest.main()
