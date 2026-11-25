"""Append-only identities and exact native selection survive packaged manifests."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.catalog import CHECK_FLAGS, CHESTS, GAME, ITEM_IDS, LOCATION_IDS, SHOP_CHECKS, SKULL_CHECKS
from ootrr_triforce.engine import run_engine
from ootrr_triforce.master_sword import token_material
from ootrr_triforce.network_catalog import (APPENDED_IDS, SOURCES, check_flags, enabled, extend_ids,
                                           flag_name, murmur3, validate_sources)
from ootrr_triforce.native_setup import save_session
from ootrr_triforce.player import read_manifest
from oot_rando.patching.soul_adapter import murmur3 as native_murmur


def manifest():
    names = [next(iter(CHESTS)), "Song from Impa", "KF House of Twins Pot 1", "KF GS Bean Patch"]
    placements = dict.fromkeys(names, "Rupees (20)")
    shops = {name: dict(item="Buy Heart", price=row["price"]) for name, row in SHOP_CHECKS.items()}
    sources = {name: dict(copy.deepcopy(SOURCES[name]), generated_item=item) for name, item in placements.items()}
    for name, row in shops.items():
        sources[name] = dict(copy.deepcopy(SOURCES[name]), generated_item=row["item"], price=row["price"], deal=False)
    seed = dict(format="ootrr-seed", generator="ootrr-core 0.8.1", checksum="manifest-fixture",
                placements=placements, shops=shops)
    moved = dict(placements, **{name: row["item"] for name, row in shops.items()})
    room = "native-network-manifest-test"
    return dict(game=GAME, protocol=1, room=room, player=1, slot="Player",
                token=hashlib.sha256(token_material(room, 1, seed["checksum"], False).encode()).hexdigest(),
                seed_file=seed, checks=sorted(moved), moved=moved, reward_mode="all_locations", local_items=True,
                network_sources_schema=1, network_sources=sources, shop_check_mode="randomized_stock",
                shop_checks=sorted(shops), foreign_only_shops=False, kokiri_shop_checks=False,
                adult_trade_shuffle=False, shuffle_master_sword=False, shops_always_open=False)


class NetworkCatalogueTests(unittest.TestCase):
    def test_all_released_identities_and_flags_remain_frozen(self):
        frozen = json.loads((ROOT / "tests/fixtures/protocol-v0.10.json").read_text(encoding="utf-8"))
        self.assertEqual(len(frozen["items"]), 205)
        self.assertEqual(len(frozen["locations"]), 304)
        for name, value in frozen["items"].items():
            self.assertEqual(ITEM_IDS[name], value, name)
        for name, value in frozen["locations"].items():
            self.assertEqual(LOCATION_IDS[name], value, name)
            self.assertEqual(CHECK_FLAGS[name], frozen["flags"][name], name)
        self.assertEqual(set(APPENDED_IDS), SOURCES.keys() - frozen["locations"].keys())
        self.assertTrue(set(APPENDED_IDS.values()).isdisjoint(frozen["locations"].values()))
        self.assertEqual(len(LOCATION_IDS), len(set(LOCATION_IDS.values())))

    def test_missing_identity_cannot_silently_renumber_the_new_catalogue(self):
        frozen = json.loads((ROOT / "tests/fixtures/protocol-v0.10.json").read_text(encoding="utf-8"))
        restored = dict(frozen["locations"])
        extend_ids(restored)
        self.assertEqual(restored, LOCATION_IDS)
        del restored[next(iter(APPENDED_IDS))]
        with self.assertRaises(ValueError):
            extend_ids(restored)

    def test_unsafe_native_sources_remain_visible_but_are_explicitly_junk_only(self):
        protected = {name for name, row in SOURCES.items() if row["placement"]["junk_only"]}
        self.assertEqual(len(protected), 35)
        self.assertEqual(sum(SOURCES[name]["kind"] == "skull" for name in protected), 23)
        self.assertTrue(protected <= LOCATION_IDS.keys())

    def test_completion_hashes_are_native_and_new_skulls_do_not_reuse_legacy_flags(self):
        flags = [murmur3(flag_name(name)) for name in SOURCES]
        self.assertEqual(len(flags), len(set(flags)))
        for name in SOURCES:
            self.assertEqual(murmur3(flag_name(name)), native_murmur(flag_name(name)))
        name = "KF GS Bean Patch"
        self.assertEqual(check_flags(name), CHECK_FLAGS[name])
        self.assertNotEqual(check_flags(name, network=True), CHECK_FLAGS[name])
        self.assertEqual(check_flags(name, network=True), [native_murmur(flag_name(name))])

    def test_every_selected_reward_and_ordinary_shop_is_required_exactly_once(self):
        data = manifest()
        self.assertEqual(set(validate_sources(data)), set(data["moved"]))
        self.assertTrue(set(SHOP_CHECKS) <= validate_sources(data).keys())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "room.apootrr"
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(read_manifest(path), data)
            data["checks"].remove("Song from Impa")
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                read_manifest(path)

    def test_descriptor_reward_price_and_schema_tampering_are_rejected(self):
        for change in (lambda d: d["network_sources"].pop("Song from Impa"),
                       lambda d: d["network_sources"]["Song from Impa"].update(generated_item="Bow"),
                       lambda d: d["network_sources"]["Song from Impa"]["placement"].update(junk_only=True),
                       lambda d: d["network_sources"]["KF Shop Item 1"].update(price=999),
                       lambda d: d.update(network_sources_schema=True)):
            data = manifest()
            change(data)
            with self.assertRaises(ValueError):
                validate_sources(data)
        self.assertFalse(enabled({}))
        with self.assertRaises(ValueError):
            enabled(dict(network_sources={}))

    def test_native_session_uses_room_versioned_flags_for_all_new_families(self):
        data = manifest()
        roster = {name: dict(item=item, player="Player", owner=1, local=True, game=GAME,
                            item_id=ITEM_IDS[item]) for name, item in data["moved"].items()}
        with tempfile.TemporaryDirectory() as directory:
            save_session(Path(directory), dict(server="ws://127.0.0.1:38281", protected="", baseline=0), data, roster)
            session = json.loads((Path(directory) / "native-session.json").read_text(encoding="utf-8"))
        for name in data["checks"]:
            self.assertEqual(session["Checks"][str(LOCATION_IDS[name])]["Flags"], check_flags(name, network=True))

    def test_packaged_catalogue_matches_the_actual_wasm_export(self):
        actual = json.loads(run_engine("catalog", {}))
        self.assertEqual(actual, dict(schema=1, sources=SOURCES))


if __name__ == "__main__":
    unittest.main()
