"""Shop tokens must keep seed prices, unique purchase identities and all slots."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.ap_shops import prepare_shops, selected_shops, shop_records
from ootrr_triforce.catalog import ITEM_DATA, ITEM_IDS, LEGACY_SHOP_CHECKS, SHOP_CHECKS


class ShopRecordTests(unittest.TestCase):
    def setUp(self):
        self.roster = {name: {"item": "Same reward", "player": "Ami", "owner": 1, "item_id": 100,
                              "local": False} for name in sorted(LEGACY_SHOP_CHECKS)}
        self.settings = {"kokiri_shop_checks": True,
                         "shop_prices": {name: 5 + i for i, name in enumerate(sorted(LEGACY_SHOP_CHECKS))}}

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

    def test_local_rewards_keep_a_unique_presentation_and_native_recipe(self):
        names = sorted(LEGACY_SHOP_CHECKS)
        for name in names:
            self.roster[name].update(item="Bow", player="Link", item_id=ITEM_IDS["Bow"], local=True)
        records = shop_records(self.roster, self.settings)
        self.assertEqual(len({row["actor"] for row in records}), 8)
        for row in records:
            self.assertEqual(row["local_item"], "Bow")
            self.assertEqual(row["native_actor"], ITEM_DATA["Bow"]["actor"])
            self.assertTrue(row["actor"].startswith("Item_AP_"))
        self.settings["foreign_only_shops"] = True
        with self.assertRaisesRegex(ValueError, "test room reserves"):
            shop_records(self.roster, self.settings)

    def test_missing_unknown_local_and_invalid_price_fail_before_writing(self):
        first = sorted(LEGACY_SHOP_CHECKS)[0]
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
                 patch("ootrr_triforce.shop_layout.prepare_shop_layout"), \
                 patch("ootrr_triforce.shop_events.prepare_shop_events", return_value={"ok": True}):
                self.assertEqual(prepare_shops(romfs, mod, self.roster, self.settings), {"ok": True})
            self.assertEqual(engine.call_args.args[0], "shops")
            self.assertEqual(engine.call_args.args[1]["messages"],
                             ["Mals/EUfr.Product.110.sarc.zs", "Mals/USen.Product.110.sarc.zs"])
            self.assertEqual(len(engine.call_args.args[1]["shops"]), 8)
            self.assertEqual((romfs / "Mals/ignore.txt").read_bytes(), b"untouched")

    def test_personal_dungeon_shelf_labels_are_named_after_the_native_factory(self):
        first = sorted(self.roster)[0]
        self.roster[first].update(item="Boss Key (Forest Temple)", player="Link", local=True,
                                  item_id=ITEM_IDS["Boss Key (Forest Temple)"])
        record = next(row for row in shop_records(self.roster, self.settings) if row["name"] == first)
        order = []
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            romfs, mod = root / "game", root / "load/Archipelago/romfs"
            (mod / "Mals").mkdir(parents=True)
            (mod / "Mals/EUfr.Product.110.sarc.zs").write_bytes(b"fixture")
            with patch("ootrr_triforce.ap_shops.run_engine", side_effect=lambda *_: order.append("factory") or ""), \
                    patch("ootrr_triforce.dungeon_messages.prepare_messages", side_effect=lambda *_, **__: order.append("names")) as names, \
                    patch("ootrr_triforce.shop_identity.prepare_shop_identities"), \
                    patch("ootrr_triforce.shop_poses.prepare_shop_poses"), \
                    patch("ootrr_triforce.shop_layout.prepare_shop_layout"), \
                    patch("ootrr_triforce.shop_events.prepare_shop_events"):
                prepare_shops(romfs, mod, self.roster, self.settings)
            self.assertEqual(order, ["factory", "names"])
            names.assert_called_once_with(romfs, mod,
                aliases={record["actor"]: ITEM_DATA["Boss Key (Forest Temple)"]})


class SpecialDealRecordTests(unittest.TestCase):
    def setUp(self):
        self.names = [next(name for name, row in SHOP_CHECKS.items() if row["shop"] == shop)
                      for shop in dict.fromkeys(row["shop"] for row in SHOP_CHECKS.values())]
        self.roster = {name: {"item": "Bow" if index % 2 == 0 else "Friend reward", "player": "Link" if index % 2 == 0 else "Ami",
                              "local": index % 2 == 0, "item_id": ITEM_IDS["Bow"] if index % 2 == 0 else 123}
                       for index, name in enumerate(self.names)}
        self.settings = dict(shop_check_mode="special_deals", shop_checks=list(self.names),
                             kokiri_shop_checks=False,
                             shop_prices={name: 10 + index for index, name in enumerate(self.names)})

    def test_only_selected_deals_across_all_shops_become_ap_shelves(self):
        from ootrr_triforce.shop_events import _records
        records = _records(shop_records(self.roster, self.settings))
        self.assertEqual(len(records), 8)
        self.assertEqual({record["name"] for record in records}, set(self.names))
        self.assertEqual({record["shop"] for record in records}, {row["shop"] for row in SHOP_CHECKS.values()})
        self.assertEqual({len(record["counters"]) for record in records}, {1, 2, 3})
        self.assertEqual(sum("local_item" in record for record in records), 4)
        self.assertEqual(len({record["actor"] for record in records}), 8)
        self.assertTrue(all(record["counters"] == SHOP_CHECKS[record["name"]]["counters"] for record in records))

    def test_empty_deal_selection_does_not_read_or_patch_the_game(self):
        settings = dict(self.settings, shop_checks=[], shop_prices={})
        with patch("ootrr_triforce.ap_shops.run_engine") as engine, \
                patch("ootrr_triforce.shop_events.prepare_shop_events") as events:
            self.assertEqual(prepare_shops(Path("absent-game"), Path("absent-mod"), {}, settings), {})
        engine.assert_not_called()
        events.assert_not_called()

    def test_mismatch_duplicate_unknown_or_missing_selection_is_rejected(self):
        for selected in (self.names[:-1], self.names + [self.names[0]], ["Unknown shop"], None, self.names[0]):
            with self.subTest(selection=selected), self.assertRaises(ValueError):
                shop_records(self.roster, dict(self.settings, shop_checks=selected))
        with self.assertRaises(ValueError):
            shop_records(self.roster, dict(self.settings, shop_check_mode="all_shelves"))
        with self.assertRaises(ValueError):
            shop_records(self.roster, {"kokiri_shop_checks": True})
        with self.assertRaises(ValueError):
            shop_records(self.roster, {})

    def test_local_deals_work_without_another_player(self):
        roster = {name: dict(item="Bow", item_id=ITEM_IDS["Bow"], player="Link", local=True) for name in self.names}
        records = shop_records(roster, self.settings)
        self.assertTrue(all(row["local_item"] == "Bow" for row in records))

    def test_new_deal_price_uses_the_seed_limits(self):
        for price in (None, 0, -1, 1000, True):
            prices = dict(self.settings["shop_prices"], **{self.names[0]: price})
            with self.subTest(price=price), self.assertRaises(ValueError):
                shop_records(self.roster, dict(self.settings, shop_prices=prices))


if __name__ == "__main__":
    unittest.main()
