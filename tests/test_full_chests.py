"""Full chest rooms must neither omit local prizes nor hide self-owned AP rewards."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dist/Client-OOT-Remake.pyz"))
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.catalog import CHESTS, CHECK_FLAGS, GAME, GEAR, ITEM_IDS, LOCATION_IDS, LEGACY_SHOP_CHECKS, SHOP_CHECKS, SKULL_CHECKS, AP_SKULL_CHECKS
from ootrr_triforce.shop_pool import SHOP_CHECK_MODE
from ootrr_triforce.native_setup import save_session
from ootrr_triforce.player import patch_request, read_manifest
from ootrr_triforce.presentation import Presentation
from ootrr_triforce.room_view import RoomView


def fixture(kind):
    with ZipFile(ROOT / f"tests/fixtures/{kind}/salle-test.zip") as archive:
        return json.loads(archive.read(next(n for n in archive.namelist() if n.endswith(".apootrr"))))


class FullChestTests(unittest.TestCase):
    def read(self, data):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "player.apootrr"
            path.write_text(json.dumps(data), encoding="utf-8")
            return read_manifest(path)

    def test_skull_manifest_preserves_native_only_rewards_and_uses_pickup_flags(self):
        data = fixture("complet-v2")
        name = sorted(AP_SKULL_CHECKS)[0]
        bean = "ZR GS Near Raised Grottos"
        data["shuffle_skulltulas"] = "matched"
        data["local_skulltulas"] = {bean: "Native-only: bean access is not proved."}
        for skull in SKULL_CHECKS:
            data["seed_file"]["placements"].pop(skull, None)
        data["seed_file"]["placements"].update({name: "Gold Skulltula Token", bean: "Rupees (5)"})
        data["checks"].append(name)
        data["moved"][name] = "Gold Skulltula Token"
        validated = self.read(data)
        self.assertIn(name, validated["checks"])
        self.assertNotIn(bean, validated["checks"])
        # The chest neutralizer must never turn the enemy's actor into a chest.
        requests = patch_request(validated)
        self.assertFalse(any(row["actor"] == SKULL_CHECKS[name]["actor"]
                             for rows in requests["files"].values() for row in rows))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save_session(root, dict(server="ws://127.0.0.1:38281", protected="", baseline=0),
                         validated, {name: dict(item="Gold Skulltula Token", player="Zelda", local=True)})
            session = json.loads((root / "native-session.json").read_bytes())
            self.assertEqual(session["Checks"][str(LOCATION_IDS[name])]["Flags"], [SKULL_CHECKS[name]["flag"]])

    def test_unknown_unproved_or_omitted_skull_checks_are_rejected(self):
        data = fixture("complet-v2")
        name = sorted(AP_SKULL_CHECKS)[0]
        data["shuffle_skulltulas"] = "matched"
        for skull in SKULL_CHECKS:
            data["seed_file"]["placements"].pop(skull, None)
        data["seed_file"]["placements"][name] = "Gold Skulltula Token"
        # A reason string cannot silently exclude any ordinary supported check.
        data["local_skulltulas"] = {name: "Skip this location"}
        with self.assertRaises(ValueError):
            self.read(data)
        unknown = sorted(set(SKULL_CHECKS) - AP_SKULL_CHECKS)[0]
        data["checks"].append(unknown)
        data["moved"][unknown] = "Gold Skulltula Token"
        data["seed_file"]["placements"][unknown] = "Gold Skulltula Token"
        with self.assertRaises(ValueError):
            self.read(data)

    def test_manifests_and_every_physical_drop(self):
        legacy = self.read(fixture("neutre"))
        self.assertTrue(all(reward in GEAR for reward in legacy["moved"].values()))
        full = self.read(fixture("complet"))
        self.assertEqual(set(full["checks"]), set(full["moved"]))
        self.assertTrue(any("Small Key" in n for n in full["moved"].values()))
        self.assertTrue(any("Progressive" in n for n in full["moved"].values()))
        requests = patch_request(full)["files"]
        expected_actors = {(path, ref["actor"]) for name in full["checks"]
                           for ref in CHESTS[name] for path in ref["files"]}
        actual_actors = {(path, request["actor"]) for path, rows in requests.items() for request in rows}
        self.assertEqual(actual_actors, expected_actors)
        self.assertTrue(all(r["drop"] == "TBox_Rupee_Green" and r["expected"]
                            for rows in requests.values() for r in rows))
        for mutation in ("missing", "wrong_prize", "unknown_mode"):
            invalid = copy.deepcopy(full)
            if mutation == "missing":
                invalid["checks"].pop()
            elif mutation == "wrong_prize":
                invalid["moved"][invalid["checks"][0]] = "Blue Rupee (5)"
            else:
                invalid["reward_mode"] = "unsupported"
            with self.assertRaises(ValueError):
                self.read(invalid)

    def test_self_owned_chest_is_also_replaced(self):
        data = fixture("complet")
        first, second = data["checks"][:2]
        data["checks"] = [first, second]
        room = RoomView(data["player"])
        room.games[3] = "Other game"
        room.names["Other game"] = {"item_id": {900: "Other reward"}}
        own_item = ITEM_IDS[data["moved"][first]]
        with tempfile.TemporaryDirectory() as folder:
            view = Presentation(Path(folder), data, room)
            view.stable_names = {data["player"]: data["slot"], 3: "Ami"}
            view.scouts = {LOCATION_IDS[first]: (own_item, data["player"]),
                           LOCATION_IDS[second]: (900, 3)}
            self.assertEqual(set(view.roster()), {first, second})
            view.full_chests = False
            self.assertEqual(set(view.roster()), {second})
            config = {"server": "ws://127.0.0.1:38281", "protected": "", "baseline": 0}
            save_session(Path(folder), config, data, {})
            session = json.loads((Path(folder) / "native-session.json").read_bytes())
            self.assertEqual(session["RewardMode"], "all_chest_rewards")

    def v2(self):
        data = fixture("complet")
        data.update(reward_mode="all_locations", local_items=True, kokiri_shop_checks=True)
        for index, name in enumerate(sorted(LEGACY_SHOP_CHECKS)):
            item = list(ITEM_IDS)[index]
            data["seed_file"].setdefault("shops", {})[name] = {"item": item, "price": 40}
            data["checks"].append(name)
            data["moved"][name] = item
        return data

    def test_v2_manifest_keeps_all_eight_legacy_shops_without_chest_actor_requests(self):
        data = self.read(self.v2())
        self.assertEqual(len(data["checks"]), 136)
        requests = patch_request(data)["files"]
        actual = {(path, row["actor"]) for path, rows in requests.items() for row in rows}
        expected = {(path, ref["actor"]) for name in data["checks"] if name in CHESTS
                    for ref in CHESTS[name] for path in ref["files"]}
        self.assertEqual(actual, expected)
        for mutation in ("local_mode", "missing_shop", "disabled_shops"):
            invalid = copy.deepcopy(data)
            if mutation == "local_mode":
                invalid["local_items"] = False
            elif mutation == "missing_shop":
                invalid["checks"].remove(next(iter(SHOP_CHECKS)))
            else:
                invalid["kokiri_shop_checks"] = False
            with self.assertRaises(ValueError):
                self.read(invalid)

    def test_v2_roster_and_session_keep_owner_identity_and_shop_flags(self):
        data = self.v2()
        chest, shop = data["checks"][0], next(iter(SHOP_CHECKS))
        data["checks"] = [chest, shop]
        room = RoomView(data["player"])
        room.games[3] = "Other game"
        room.names["Other game"] = {"item_id": {900: "Other reward"}}
        own = ITEM_IDS[data["moved"][chest]]
        with tempfile.TemporaryDirectory() as folder:
            view = Presentation(Path(folder), data, room)
            view.stable_names = {data["player"]: data["slot"], 3: "Ami"}
            view.scouts = {LOCATION_IDS[chest]: (own, data["player"]), LOCATION_IDS[shop]: (900, 3)}
            roster = view.roster()
            self.assertTrue(roster[chest]["local"])
            self.assertEqual(roster[chest]["item_id"], own)
            self.assertFalse(roster[shop]["local"])
            self.assertEqual(roster[shop]["player"], "Ami")
            save_session(Path(folder), {"server": "ws://127.0.0.1:38281", "protected": "", "baseline": 0}, data, roster)
            session = json.loads((Path(folder) / "native-session.json").read_bytes())
            self.assertTrue(session["LocalItems"])
            self.assertEqual(session["RewardMode"], "all_locations")
            self.assertEqual(session["Checks"][str(LOCATION_IDS[shop])]["Flags"], list(CHECK_FLAGS[shop]))

    def global_shops(self, selected=None):
        data = fixture("complet")
        if selected is None:
            selected = {next(name for name, row in SHOP_CHECKS.items() if row["shop"] == shop)
                        for shop in dict.fromkeys(row["shop"] for row in SHOP_CHECKS.values())}
        data.update(reward_mode="all_locations", local_items=True, kokiri_shop_checks=False,
                    foreign_only_shops=False, shop_check_mode=SHOP_CHECK_MODE, shop_checks=sorted(selected))
        data["seed_file"]["shops"] = {
            name: dict(item="Bow" if name in selected else row["item"], price=40,
                       deal=name in selected) for name, row in SHOP_CHECKS.items()}
        for name in sorted(selected):
            data["checks"].append(name)
            data["moved"][name] = "Bow"
        return data

    def test_new_manifest_tracks_native_deals_across_all_shops_and_no_ordinary_stock(self):
        data = self.read(self.global_shops())
        selected = set(data["shop_checks"])
        self.assertEqual(len(data["seed_file"]["shops"]), 64)
        self.assertEqual(len(selected), 8)
        self.assertEqual(len(selected & LEGACY_SHOP_CHECKS), 1)
        self.assertEqual(set(data["checks"]) & set(SHOP_CHECKS), selected)
        requests = patch_request(data)["files"]
        actual = {(path, row["actor"]) for path, rows in requests.items() for row in rows}
        expected = {(path, ref["actor"]) for name in data["checks"] if name in CHESTS
                    for ref in CHESTS[name] for path in ref["files"]}
        self.assertEqual(actual, expected)
        for mutation in ("missing_deal", "ordinary_check", "changed_seed_deal", "legacy_mode"):
            invalid = copy.deepcopy(data)
            if mutation == "missing_deal":
                invalid["checks"].remove(sorted(selected)[0])
            elif mutation == "ordinary_check":
                ordinary = sorted(set(SHOP_CHECKS) - selected)[0]
                invalid["checks"].append(ordinary)
                invalid["moved"][ordinary] = invalid["seed_file"]["shops"][ordinary]["item"]
            elif mutation == "changed_seed_deal":
                invalid["seed_file"]["shops"][sorted(selected)[0]]["deal"] = False
            else:
                invalid["kokiri_shop_checks"] = True
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.read(invalid)

    def test_new_ordinary_shuffle_has_no_ap_shop_checks_and_preserves_old_player_files(self):
        data = self.read(self.global_shops(set()))
        self.assertEqual(data["shop_checks"], [])
        self.assertFalse(set(data["checks"]) & set(SHOP_CHECKS))
        self.assertEqual(len(data["seed_file"]["shops"]), 64)
        for name in ("neutre", "complet", "complet-v2"):
            with self.subTest(old_room=name):
                old = fixture(name)
                old_checks = list(old["checks"])
                validated = self.read(old)
                self.assertEqual(validated["checks"], old_checks)
                self.assertNotIn("shop_check_mode", validated)

    def test_new_sessions_keep_global_shop_ids_and_saved_flags(self):
        data = self.read(self.global_shops())
        roster = {name: dict(item="Bow", player="Zelda", local=index % 2 == 0)
                  for index, name in enumerate(data["shop_checks"])}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            save_session(root, {"server": "ws://127.0.0.1:38281", "protected": "", "baseline": 0}, data, roster)
            session = json.loads((root / "native-session.json").read_bytes())
        self.assertEqual(set(session["Checks"]), {str(LOCATION_IDS[name]) for name in data["checks"]})
        for name in data["shop_checks"]:
            self.assertEqual(session["Checks"][str(LOCATION_IDS[name])]["Flags"], CHECK_FLAGS[name])


if __name__ == "__main__":
    unittest.main()
