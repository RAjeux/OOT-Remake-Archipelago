"""Every AP shelf maps to one native stock unit without renumbering old rooms."""
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from oot_rando.patching.soul_adapter import murmur3
from ootrr_triforce.catalog import (CHECK_FLAGS, CHESTS, LEGACY_CHESTS, LEGACY_SHOP_CHECKS,
                                    LOCATION_IDS, SHOP_CHECKS, SKULL_CHECKS,
                                    TRADE_CHECKS)
from ootrr_triforce.shop_catalog import ADDITIONAL_SHOP_CHECKS, SHOP_FIRST_ID


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class ShopCatalogueTests(unittest.TestCase):
    def test_all_preexisting_ids_and_kokiri_metadata_are_unchanged(self):
        old_names = {*LEGACY_CHESTS, *LEGACY_SHOP_CHECKS, *SKULL_CHECKS, *TRADE_CHECKS}
        old_ids = {name: LOCATION_IDS[name] for name in old_names}
        self.assertEqual(len(old_ids), 247)
        self.assertEqual(digest(old_ids), "86de26d2549fc0ead84e555d2eedd9e073294d9521a86992c2e909baf5f9072b")
        self.assertEqual(LEGACY_SHOP_CHECKS, {"KF Shop Item " + str(i) for i in range(1, 9)})
        self.assertEqual(digest({name: SHOP_CHECKS[name] for name in LEGACY_SHOP_CHECKS}),
                         "dde8d9c52b099a483aebd280f7af31e443be2923ce0c9aa1d2904efad3880118")
        self.assertEqual(len(set(LOCATION_IDS.values())), len(LOCATION_IDS))
        self.assertEqual(set(ADDITIONAL_SHOP_CHECKS), set(SHOP_CHECKS) - LEGACY_SHOP_CHECKS)
        self.assertEqual({LOCATION_IDS[name] for name in ADDITIONAL_SHOP_CHECKS},
                         set(range(SHOP_FIRST_ID, SHOP_FIRST_ID + 56)))
        self.assertFalse(set(old_ids.values()) & {LOCATION_IDS[name] for name in ADDITIONAL_SHOP_CHECKS})

    def test_all_eight_shops_follow_the_native_slot_and_placement_table(self):
        native = json.loads((ROOT / "moteur/ootrr-ap/data/shops.json").read_text(encoding="utf-8"))
        definitions = {shop["shop"]: shop for shop in native["shops"]}
        self.assertEqual(set(SHOP_CHECKS), {row["name"] for row in native["slots"]})
        self.assertEqual(len(SHOP_CHECKS), 64)
        self.assertEqual(len(definitions), 8)
        for slot in native["slots"]:
            with self.subTest(location=slot["name"]):
                record = SHOP_CHECKS[slot["name"]]
                for key in ("shop", "slot", "actor", "item", "price", "counters", "target"):
                    self.assertEqual(record[key], slot[key])
                for key in ("files", "keepers", "bancs"):
                    self.assertEqual(record[key], definitions[slot["shop"]][key])
                self.assertEqual(CHECK_FLAGS[slot["name"]], [murmur3(record["flag_name"])])
                self.assertEqual(record["flag"], murmur3(record["flag_name"]))
                self.assertEqual({counter.rsplit(".", 1)[0].removeprefix("Shop_SoldNum.")
                                  for counter in record["counters"]}, set(record["keepers"]))
        for shop in definitions:
            self.assertEqual({record["slot"] for record in SHOP_CHECKS.values() if record["shop"] == shop},
                             set(range(8)))

    def test_single_purchase_cannot_match_two_locations_or_ages(self):
        units = [(tuple(record["files"]), record["slot"]) for record in SHOP_CHECKS.values()]
        counters = [counter for record in SHOP_CHECKS.values() for counter in record["counters"]]
        self.assertEqual(len(set(units)), 64)
        self.assertEqual(len(counters), 96)
        self.assertEqual(len(set(counters)), 96)
        self.assertEqual(len({record["target"] for record in SHOP_CHECKS.values()}), 64)
        self.assertEqual(len({record["flag"] for record in SHOP_CHECKS.values()}), 64)
        expected = {"KF Shop": 3, "GC Shop": 2, "ZD Shop": 2}
        for record in SHOP_CHECKS.values():
            self.assertEqual(len(record["counters"]), expected.get(record["shop"], 1))
            self.assertTrue(record["flag_name"].startswith("Archipelago.Shop."))
            self.assertTrue(record["target"].startswith("shop:"))
            self.assertTrue(all(counter.endswith("." + str(record["slot"])) for counter in record["counters"]))

    def test_global_flags_do_not_collide_with_other_checks_or_native_flags(self):
        new_flags = {record["flag"] for record in ADDITIONAL_SHOP_CHECKS.values()}
        old_flags = {flag for name, flags in CHECK_FLAGS.items() if name not in ADDITIONAL_SHOP_CHECKS
                     for flag in flags}
        native = json.loads((ROOT / "moteur/ootrr-ap/data/flags.json").read_text(encoding="utf-8"))
        native_flags = {int(record["hash"], 16) for record in native["flags"]}
        self.assertFalse(new_flags & old_flags)
        self.assertFalse(new_flags & native_flags)

    @unittest.skipUnless(os.environ.get("OOTRR_ROMFS"), "Set OOTRR_ROMFS for the read-only native shelf check")
    def test_real_native_keeper_links_cover_every_slot_without_touching_romfs(self):
        from oot_rando.formats.inspect_resources import Byml
        from ootrr_triforce.mod_codec import Codec
        game = Path(os.environ["OOTRR_ROMFS"])
        paths = {path for record in SHOP_CHECKS.values() for path in record["bancs"]}
        originals = {path: (game / path).read_bytes() for path in paths | {"Pack/ZsDic.pack.zs"}}
        argv0 = sys.argv[0]
        try:
            sys.argv[0] = str(ROOT / "dist/Client-OOT-Remake.pyz")
            codec = Codec(originals["Pack/ZsDic.pack.zs"])
            maps = {path: Byml(codec.decode(originals[path])).root for path in paths}
            physical = 0
            for name, record in SHOP_CHECKS.items():
                matches = []
                for path in record["bancs"]:
                    actors = maps[path].get("Actors", [])
                    by_hash = {actor.get("Hash"): actor for actor in actors}
                    for keeper in actors:
                        if keeper.get("Gyaml") not in record["keepers"]:
                            continue
                        for link in keeper.get("Links", []):
                            actor = by_hash.get(link.get("Dst"), {})
                            if (link.get("Name") == "ForSale" and actor.get("Gyaml", "").startswith("Shop_")
                                    and actor.get("Dynamic", {}).get("ShopItemIndex", 0) == record["slot"]):
                                matches.append(actor["Gyaml"])
                with self.subTest(location=name):
                    self.assertTrue(matches, "No native shelf belongs to this keeper and slot")
                    self.assertEqual(set(matches), {record["actor"]})
                physical += len(matches)
            self.assertEqual(len(maps), 10)
            self.assertEqual(physical, 120)
        finally:
            sys.argv[0] = argv0
            self.assertEqual(originals, {path: (game / path).read_bytes() for path in originals})


if __name__ == "__main__":
    unittest.main()
