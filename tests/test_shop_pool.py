"""Keep native shop selection, AP ownership and legacy player files separate."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client"))
from ootrr_triforce.catalog import LEGACY_SHOP_CHECKS, SHOP_CHECKS
from ootrr_triforce.shop_pool import SHOP_CHECK_MODE, manifest_shop_checks, shop_checks


def native_seed(deals=()):
    return {"shops": {name: {"item": row["item"], "price": row["price"], "deal": name in deals}
                       for name, row in SHOP_CHECKS.items()}}


class ShopPoolTests(unittest.TestCase):
    def test_only_actual_deals_enter_the_pool_across_all_eight_shops(self):
        selected = {next(name for name, row in SHOP_CHECKS.items() if row["shop"] == shop)
                    for shop in {row["shop"] for row in SHOP_CHECKS.values()}}
        self.assertEqual(shop_checks(native_seed(selected)), selected)
        self.assertEqual(shop_checks(native_seed()), set())
        self.assertEqual(shop_checks({}), set())

    def test_kokiri_can_have_no_deal_while_another_shop_has_one(self):
        selected = {next(name for name in SHOP_CHECKS if name not in LEGACY_SHOP_CHECKS)}
        self.assertEqual(shop_checks(native_seed(selected)), selected)

    def test_original_kokiri_rooms_keep_all_eight_purchases(self):
        seed = native_seed()
        seed["shops"] = {name: seed["shops"][name] for name in LEGACY_SHOP_CHECKS}
        self.assertEqual(manifest_shop_checks({"seed_file": seed, "kokiri_shop_checks": True}), LEGACY_SHOP_CHECKS)
        self.assertEqual(manifest_shop_checks({"seed_file": seed}), set())
        seed["shops"].pop(next(iter(LEGACY_SHOP_CHECKS)))
        with self.assertRaisesRegex(ValueError, "eight Kokiri"):
            shop_checks(seed, mode=None, legacy=True)

    def test_manifest_cannot_add_ordinary_goods_remove_deals_or_force_foreign_rewards(self):
        selected = [next(iter(SHOP_CHECKS))]
        valid = {"seed_file": native_seed(selected), "shop_check_mode": SHOP_CHECK_MODE,
                 "shop_checks": selected, "kokiri_shop_checks": False, "foreign_only_shops": False}
        self.assertEqual(manifest_shop_checks(valid), set(selected))
        ordinary = next(name for name in SHOP_CHECKS if name not in selected)
        for changes in ({"shop_checks": []}, {"shop_checks": selected * 2},
                        {"shop_checks": selected + [ordinary]}, {"shop_checks": "unknown"},
                        {"foreign_only_shops": True}, {"kokiri_shop_checks": True},
                        {"shop_check_mode": "unknown"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                manifest_shop_checks({**valid, **changes})

    def test_native_metadata_is_checked_before_it_can_select_a_network_location(self):
        name = next(iter(SHOP_CHECKS))
        for changes in ({"deal": 1}, {"item": ""}, {"price": True}, {"price": 0}, {"price": 1000}):
            seed = native_seed([name])
            seed["shops"][name].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                shop_checks(seed)
        seed = native_seed()
        seed["shops"].pop(name)
        with self.assertRaisesRegex(ValueError, "catalogue is incomplete"):
            shop_checks(seed)
        seed = native_seed()
        seed["shops"]["Unknown shop"] = deepcopy(seed["shops"][name])
        with self.assertRaises(ValueError):
            shop_checks(seed)


if __name__ == "__main__":
    unittest.main()
