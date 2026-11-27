"""Native graph alternatives, counts, fixed rewards and safe AP integration."""
from collections import Counter
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.access_logic import AccessLogic, validate, arith, key_caps


def fixture():
    items = [dict(name=n, adv=True, event=(n == "Bridge"))
             for n in ("Bow", "Hookshot", "Small Key (Forest Temple)", "Progressive Wallet", "Bridge")]
    locs = [dict(name="Choice", region=0, rule=["or", [["h", 0, 1], ["h", 1, 1]]], event=None),
            dict(name="Two Keys", region=0, rule=["h", 2, 2], event=None),
            dict(name="Shop", region=0, rule=["h", 3, 2], event=None),
            dict(name="Native", region=0, rule=True, event=None),
            dict(name="Bridge Event", region=0, rule=["h", 0, 1], event=4),
            dict(name="Adult", region=1, rule=["ageis", "adult"], event=None),
            dict(name="Day", region=1, rule=["tod", 1, False], event=None),
            dict(name="Master Sword Pedestal", region=0, rule=["ageis", "child"], event=None)]
    world = dict(items=items, regions=[dict(name="Root", time=1, exits=[0], locs=[0, 1, 2, 3, 4, 7]),
                                     dict(name="Across", time=0, exits=[], locs=[5, 6])],
                 exits=[dict(**{"from": 0}, to=1, rule=["h", 4, 1])], locs=locs,
                 goal=["h", 4, 1], root=0, real=[0, 1, 2, 3, 5, 6, 7], start=[])
    return dict(schema=1, world=world, fixed=[[3, 2]],
                sources={n: [i] for n, i in (("Choice", 0), ("Two Keys", 1), ("Shop", 2), ("Adult", 5), ("Day", 6))},
                master_sword=7)


class AccessLogicTests(unittest.TestCase):
    def test_alternative_routes_do_not_require_unrelated_donor_sphere_items(self):
        logic = AccessLogic(fixture())
        self.assertNotIn("Choice", logic.sweep({}).reach)
        self.assertIn("Choice", logic.sweep({"Bow": 1}).reach)
        self.assertIn("Choice", logic.sweep({"Hookshot": 1}).reach)
        self.assertNotIn("Adult", logic.sweep({"Hookshot": 1}).reach)

    def test_fixed_native_rewards_counts_and_wallet_are_respected(self):
        logic = AccessLogic(fixture())
        self.assertNotIn("Two Keys", logic.sweep({}).reach)
        self.assertIn("Two Keys", logic.sweep({"Small Key (Forest Temple)": 1}).reach)
        self.assertNotIn("Shop", logic.sweep({"Progressive Wallet": 1}).reach)
        self.assertIn("Shop", logic.sweep({"Progressive Wallet": 2}).reach)

    def test_events_age_and_day_time_propagate_through_reached_regions(self):
        logic = AccessLogic(fixture())
        before = logic.sweep({})
        after = logic.sweep({"Bow": 1})
        self.assertFalse(before.won)
        self.assertTrue(after.won)
        self.assertTrue({"Adult", "Day"} <= after.reach)
        logic.raw["world"]["regions"][0]["time"] = 0
        no_day = AccessLogic(logic.raw).sweep({"Bow": 1})
        self.assertNotIn("Day", no_day.reach)

    def test_starting_inventory_is_not_removed_with_exported_checks(self):
        raw = fixture()
        raw["world"]["start"] = [[0, 1], [3, 2]]
        result = AccessLogic(raw).sweep({})
        self.assertTrue(result.won)
        self.assertIn("Shop", result.reach)

    def test_native_event_can_reuse_an_existing_inventory_item_definition(self):
        raw = fixture()
        # Native Epona/trial events reuse item-table entries created before the
        # event was compiled. Their item.event bit can legitimately stay false.
        raw["world"]["items"][4]["event"] = False
        self.assertTrue(AccessLogic(raw).sweep({"Bow": 1}).won)

    def test_selected_reward_never_grants_its_original_native_item(self):
        raw = fixture()
        raw["fixed"] = []
        self.assertNotIn("Two Keys", AccessLogic(raw).sweep({"Small Key (Forest Temple)": 1}).reach)
        raw["fixed"] = [[0, 0]]
        with self.assertRaises(ValueError):
            AccessLogic(raw)

    def test_old_save_or_removed_item_does_not_reuse_a_later_inventory_cache(self):
        logic = AccessLogic(fixture())
        self.assertTrue(logic.sweep({"Bow": 1}).won)
        self.assertFalse(logic.sweep({}).won)
        self.assertTrue(logic.sweep({"Bow": 1}).won)
        for n in range(300):
            logic.sweep({"Bow": n})
        self.assertLessEqual(len(logic._cache), 256)

    def test_shuffled_master_sword_keeps_child_pedestal_access_but_gates_adult_combat(self):
        logic = AccessLogic(fixture(), master_sword=True)
        before = logic.sweep({"Bow": 1})
        self.assertIn("ToT Master Sword", before.reach)
        self.assertNotIn("Adult", before.reach)
        self.assertFalse(before.won)
        after = logic.sweep({"Bow": 1, "Master Sword": 1})
        self.assertIn("Adult", after.reach)
        self.assertTrue(after.won)

    def test_known_out_of_logic_source_has_only_explicit_late_fallback(self):
        raw = fixture()
        raw["world"]["locs"][0]["rule"] = False
        logic = AccessLogic(raw, optional=("Choice",), required=(("Bow", 1),))
        self.assertNotIn("Choice", logic.sweep({}).reach)
        self.assertIn("Choice", logic.sweep({"Bow": 1}).reach)
        restored = AccessLogic(copy.deepcopy(logic.raw))
        self.assertNotIn("Choice", restored.sweep({}).reach)
        self.assertIn("Choice", restored.sweep({"Bow": 1}).reach)

    def test_validation_rejects_broken_indices_unknown_operations_and_alias_collisions(self):
        mutations = [lambda x: x.update(schema=True),
                     lambda x: x["world"].update(root=-1),
                     lambda x: x["world"]["locs"][0].update(rule=["execute", "file"]),
                     lambda x: x["world"]["locs"][0].update(rule=["h", 10000, 1]),
                     lambda x: x["sources"].update(Other=[0]),
                     lambda x: x["sources"].update(Other=[[0]]),
                     lambda x: x["world"].update(real=[]),
                     lambda x: x["world"]["locs"][0].update(event=0)]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                raw = fixture()
                mutate(raw)
                with self.assertRaises(ValueError):
                    validate(raw)

    def test_integer_arithmetic_keeps_exact_counts_and_floor_semantics(self):
        self.assertEqual(arith("+", 2**54, 1), 2**54 + 1)
        self.assertEqual(arith("//", -3, 2), -2)
        self.assertEqual(arith("%", -3, 2), 1)

    def test_key_totals_include_remote_pool_fixed_and_starts_without_age_duplicates(self):
        raw = fixture()
        raw["world"]["start"] = [[2, 3]]
        raw["world"]["locs"].append(dict(name="Native @ Across", region=1, rule=True, event=None))
        raw["world"]["regions"][1]["locs"].append(8)
        raw["world"]["real"].append(8)
        raw["fixed"].append([8, 2])
        caps = key_caps(raw, ["Small Key (Forest Temple)"] * 2)
        self.assertEqual(caps, [6, 0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(key_caps(raw, []), [4, 0, 0, 0, 0, 0, 0, 0])

    def test_linked_key_totals_use_the_native_signed_counter_domain(self):
        key = "Small Key (Forest Temple)"
        self.assertEqual(key_caps(fixture(), Counter({key: 80}))[0], 81)
        self.assertEqual(key_caps(fixture(), Counter({key: 2**31 - 2}))[0], 2**31 - 1)
        with self.assertRaises(ValueError):
            key_caps(fixture(), Counter({key: 2**31 - 1}))


if __name__ == "__main__":
    unittest.main()
