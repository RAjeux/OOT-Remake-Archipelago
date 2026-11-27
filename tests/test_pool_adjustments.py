"""New room pool changes are explicit, conservative and independently auditable."""
from collections import Counter
from pathlib import Path
import random
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.catalog import FILLER
from ootrr_triforce.pool_adjustments import eligible_filler, prepare, from_manifest
from test_access_logic import fixture


class PoolAdjustmentTests(unittest.TestCase):
    def example(self):
        moved = {"A": "Bow", "B": "Rupees (20)", "C": "Bunny Hood", "D": "Rupees (5)"}
        options = dict(starting_bunny_hood=True, shuffle_ice_traps=True, ice_trap_count=2)
        pool = prepare(moved, options, {"Bow", "Bunny Hood"}, random.Random(4))
        return dict(moved=moved, features=dict(schema=1, settings=options), access_logic=fixture(),
                    pool_substitutions={n: item for n, item in pool.items() if item != moved[n]}), pool

    def test_exact_adjusted_pool_survives_manifest_without_rewriting_donor_items(self):
        data, pool = self.example()
        self.assertEqual(from_manifest(data), pool)
        self.assertEqual(data["moved"]["A"], "Bow")
        self.assertEqual(data["moved"]["C"], "Bunny Hood")
        self.assertEqual(Counter(pool.values())["Ice Trap"], 2)
        self.assertEqual(len(pool), len(data["moved"]))

    def test_legacy_manifest_keeps_exact_original_pool(self):
        data = dict(moved={"A": "Bow", "B": FILLER})
        self.assertEqual(from_manifest(data), data["moved"])
        data["pool_substitutions"] = {"A": FILLER}
        with self.assertRaises(ValueError):
            from_manifest(data)

    def test_traps_cannot_replace_a_key_map_token_or_logical_consumable(self):
        for item in ("Small Key (Forest Temple)", "Map (Forest Temple)", "Gold Skulltula Token", "Bombs (5)"):
            with self.subTest(item=item):
                self.assertFalse(eligible_filler(item, {"Bombs (5)"}))

    def test_starting_hood_removes_one_copy_in_canonical_order_only(self):
        moved = {"B": "Bunny Hood", "A": "Bunny Hood", "C": FILLER}
        pool = prepare(moved, {"starting_bunny_hood": True}, {"Bunny Hood"}, random.Random(1))
        self.assertEqual(pool, {"B": "Bunny Hood", "A": FILLER, "C": FILLER})
        data = dict(moved=moved, features=dict(settings={"starting_bunny_hood": True}),
                    pool_substitutions={"A": FILLER, "B": FILLER})
        with self.assertRaises(ValueError):
            from_manifest(data)

    def test_pool_audit_rejects_progression_loss_wrong_count_unknown_source_and_extra_reward(self):
        mutations = [lambda d: d["pool_substitutions"].update(A="Ice Trap"),
                     lambda d: d["features"]["settings"].update(ice_trap_count=1),
                     lambda d: d["pool_substitutions"].update(Unknown="Ice Trap"),
                     lambda d: d["pool_substitutions"].update(B="Hookshot")]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                data, _ = self.example()
                mutate(data)
                with self.assertRaises(ValueError):
                    from_manifest(data)


if __name__ == "__main__":
    unittest.main()
