"""Shop tokens must keep seed prices, unique purchase identities and all slots."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.ap_shops import prepare_shops, shop_records
from ootrr_triforce.catalog import SHOP_CHECKS


class ShopRecordTests(unittest.TestCase):
    def setUp(self):
        self.roster = {name: {"item": "Same reward", "player": "Ami", "owner": 1, "item_id": 100,
                              "local": False} for name in SHOP_CHECKS}
        self.settings = {"kokiri_shop_checks": True,
                         "shop_prices": {name: 5 + i for i, name in enumerate(SHOP_CHECKS)}}

    def test_same_reward_has_distinct_shelf_tokens_and_seed_price(self):
        records = shop_records(self.roster, self.settings)
        self.assertEqual({r["slot"] for r in records}, set(range(8)))
        self.assertEqual(len({r["actor"] for r in records}), 8)
        self.assertEqual(len({r["flag_name"] for r in records}), 8)
        self.assertTrue(all(len(r["counters"]) == 3 for r in records))
        for record in records:
            self.assertEqual(record["price"], self.settings["shop_prices"][record["name"]])

    def test_all_real_catalogue_slots_pass_purchase_hook_validation(self):
        from ootrr_triforce.shop_events import _records
        records = shop_records(self.roster, self.settings)
        validated = _records(records)
        self.assertEqual({row["flag_name"] for row in validated},
                         {"Archipelago.Shop.KF." + str(slot) for slot in range(8)})

    def test_missing_self_owned_and_invalid_price_fail_before_writing(self):
        first = next(iter(SHOP_CHECKS))
        with self.assertRaises(ValueError):
            shop_records({name: row for name, row in self.roster.items() if name != first}, self.settings)
        self.roster[first]["local"] = True
        with self.assertRaises(ValueError):
            shop_records(self.roster, self.settings)
        self.roster[first]["local"] = False
        for price in (None, 0, 1000, True):
            self.settings["shop_prices"][first] = price
            with self.assertRaises(ValueError):
                shop_records(self.roster, self.settings)

    def test_message_archive_names_are_sent_without_wasi_directory_listing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            romfs, mod = root / "game", root / "load/Archipelago/romfs"
            for home in (romfs, mod):
                (home / "Mals").mkdir(parents=True)
                (home / "Mals/EUfr.Product.110.sarc.zs").write_bytes(b"fixture")
            (mod / "Mals/USen.Product.110.sarc.zs").write_bytes(b"fixture")
            (romfs / "Mals/ignore.txt").write_bytes(b"untouched")
            with patch("ootrr_triforce.ap_shops.run_engine", return_value="prepared") as engine, \
                 patch("ootrr_triforce.shop_events.prepare_shop_events", return_value={"ok": True}):
                self.assertEqual(prepare_shops(romfs, mod, self.roster, self.settings), {"ok": True})
            self.assertEqual(engine.call_args.args[0], "shops")
            self.assertEqual(engine.call_args.args[1]["messages"],
                             ["Mals/EUfr.Product.110.sarc.zs", "Mals/USen.Product.110.sarc.zs"])
            self.assertEqual(len(engine.call_args.args[1]["shops"]), 8)
            self.assertEqual((romfs / "Mals/ignore.txt").read_bytes(), b"untouched")


if __name__ == "__main__":
    unittest.main()
