"""Generic AP source callbacks keep effects, completion and replay consistent."""
from collections import Counter
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from evfl.common import Argument
from evfl.event import ActionEvent, SubFlowEvent, SwitchEvent
from oot_rando.patching.progressive import FlowEditor
from ootrr_triforce import ap_skulls, network_rewards, restoration
from ootrr_triforce.catalog import (AP_SKULL_CHECKS, CHESTS, CHECK_FLAGS, ITEM_DATA,
                                   ITEM_IDS, LOCATION_IDS, SHOP_CHECKS, TRADE_CHECKS)
from ootrr_triforce.master_sword import LOCATION as MASTER_SWORD, FLAG_NAME as MASTER_SWORD_FLAG
from ootrr_triforce.native_presentations import AMMO_BAGS, is_cure
from ootrr_triforce.network_catalog import SOURCES, flag_name, source_flags
from ootrr_triforce.receipt_events import CURSOR_PREFIX, DUNGEONS, OWNERS
from test_restoration import SaveRun, reward
from test_skull_events import Pickup, ground_flow, native_flow


def names(kind, count=1):
    selected = [name for name, row in SOURCES.items() if row["kind"] == kind
                and name not in TRADE_CHECKS and (kind != "skull" or name not in AP_SKULL_CHECKS)]
    if len(selected) < count and kind == "skull":
        selected = [name for name, row in SOURCES.items() if row["kind"] == kind]
    return selected[:count]


def settings(roster, **extra):
    return {"network_sources_schema": 1,
            "network_sources": {name: SOURCES[name] for name in roster if name in SOURCES}, **extra}


def callbacks(roster, configuration=None):
    configuration = settings(roster) if configuration is None else configuration
    records = network_rewards.source_records(roster, configuration)
    raw, effects = ap_skulls.patch_skull_flow(native_flow(), records, return_entries=True)
    return raw, records, effects


def grants(trace):
    # Companion equipment for a first Bow/Slingshot is tested separately; these
    # assertions count the assigned AP reward, including one native bundle.
    companions = {"Item_Quiver_Small", "Item_BulletBag_Small"}
    return [params for action, params in trace if action == "EventTriggerAddOrRemovePouchContent"
            and params["Actor"] not in companions
            and not (params["Actor"] in {"Item_Arrow_Normal", "Item_DekuSeed"} and params["Num"] == 30)]


def assert_no_receipt_cursor(test, trace):
    test.assertFalse(any(str(params.get("GameDataName", "")).startswith(CURSOR_PREFIX) for _, params in trace))


class QueuedSourceRun:
    """Queue writes and defer requested saves to the native frame boundary."""
    def __init__(self, raw):
        self.entries = {point.name: point.main_event.v for point in FlowEditor(raw, "AP source queue").chart.entry_points}
        self.values, self.inventory, self.pending, self.trace, self.saves = {}, Counter(), [], [], []
        self.save_requested = False
        self.steps = 0

    def flush(self):
        for kind, key, value in self.pending:
            if kind == "set":
                self.values[key] = value
            elif kind == "increment":
                self.values[key] = self.values.get(key, 0) + value
            else:
                self.inventory[key] += value
        self.pending.clear()
        # The native action requests a save; serialization occurs after the
        # frame's queued GameData/pouch writes, rather than at the request node.
        if self.save_requested:
            self.saves.append((copy.deepcopy(self.values), self.inventory.copy()))
            self.save_requested = False

    def run(self, entry, arguments=None):
        node, arguments = self.entries[entry], arguments or {}
        while node is not None:
            self.steps += 1
            assert self.steps < 10000, "AP source callback loop"
            data = node.data
            params = {key: arguments[value] if isinstance(value, Argument) else value
                      for key, value in (data.params.data.items() if data.params else ())}
            if isinstance(data, ActionEvent):
                action = data.actor_action.v.v
                self.trace.append((action, params))
                if action in {"EventTriggerSetGameDataBool", "EventTriggerSetGameDataInt", "EventTriggerSetGameDataString64"}:
                    self.pending.append(("set", params["GameDataName"], params["Value"]))
                elif action == "EventTriggerAddOrSubGameDataInt":
                    self.pending.append(("increment", params["GameDataName"], params["Value"]))
                elif action == "EventTriggerAddOrRemovePouchContent":
                    self.pending.append(("stock", OWNERS.get(params["Actor"], params["Actor"]), params["Num"]))
                elif action == "EventTriggerRecoverByCureItem":
                    self.pending.append(("stock", params["ActorName"], 1))
                elif action == "EventWait":
                    assert params == {"Frames": 1, "IsWaitEnd": True}
                    self.flush()
                elif action == "EventTriggerRequestAutoSave":
                    self.save_requested = True
                elif action not in {"EventTriggerSetForGetWindow", "EventTriggerSetHavePlayedGetEvent", "EventCloseMessageDialog"}:
                    raise AssertionError(action)
                node = data.nxt.v
            elif isinstance(data, SwitchEvent):
                query = data.actor_query.v.v
                if query == "EventQueryIsGameDataString64":
                    yes = self.values.get(params["GameDataName"]) == params["Value"]
                elif query == "EventQueryIsGameDataBool":
                    yes = bool(self.values.get(params["GameDataName"]))
                elif query in {"EventQueryCheckIsGet", "EventQueryIsExistInPouch"}:
                    actor = params.get("ActorName", params.get("Actor"))
                    yes = self.inventory[OWNERS.get(actor, actor)] >= params.get("Num", 1)
                elif query == "EventQueryIsAutoSavePouchContent":
                    yes = True
                else:
                    raise AssertionError(query)
                target = data.cases.get(0 if yes else 1)
                node = target.v if target else None
            elif isinstance(data, SubFlowEvent):
                if not (data.res_flowchart_name == "Dm_SY_Get" and data.entry_point_name == "CheckHeart"):
                    assert data.res_flowchart_name == ""
                    self.run(data.entry_point_name, params)
                node = data.nxt.v
            else:
                raise AssertionError(type(data).__name__)
        return self

    def collect(self, record, alias="actor"):
        return self.run("GetPouchContent", {"ActorName": record[alias], "IsGetInEvent": False,
                                            "IsShowNumDisplay": True, "IsTreasureBox": False})


class NetworkRewardTests(unittest.TestCase):
    def test_new_sources_use_location_flags_and_legacy_adapters_keep_their_identities(self):
        generic = [names(kind)[0] for kind in ("container", "pickup", "skull", "flow")]
        chest, shop, trade = next(iter(CHESTS)), next(iter(SHOP_CHECKS)), "LW Trade Cojiro"
        roster = {name: reward() for name in [*generic, chest, shop, trade]}
        config = settings(roster, adult_trade_shuffle=True)
        records = network_rewards.source_records(roster, config)
        self.assertEqual({record["name"] for record in records}, set(generic))
        for record in records:
            self.assertEqual(record["metadata"], SOURCES[record["name"]])
            self.assertEqual(record["flag_name"], flag_name(record["name"]))
            self.assertEqual(record["flag_hash"], source_flags(record["name"])[0])
        self.assertEqual(network_rewards.source_records(roster, {}), [])
        old = ap_skulls.skull_records({sorted(AP_SKULL_CHECKS)[0]: reward("Bomb Bag")})[0]
        self.assertNotIn("network_source", old)
        self.assertNotEqual(old["flag_name"], flag_name(old["name"]))
        legacy = restoration.restoration_records({old["name"]: reward()})[0]
        self.assertEqual(legacy["flags"], [old["flag_name"]])
        self.assertEqual(legacy["id"], LOCATION_IDS[old["name"]])
        self.assertNotEqual(source_flags(old["name"]), CHECK_FLAGS[old["name"]])

    def test_small_major_cure_and_dungeon_rewards_have_one_effect_then_their_own_flag(self):
        for item in ("Rupees (20)", "Deku Nuts (5)", "Bow", "Bomb Bag", "Bottle", "Recovery Heart",
                     "Magic Meter", "Small Key (Forest Temple)", "Boss Key (Fire Temple)", "Map (Water Temple)"):
            roster = {names(kind)[0]: reward(item) for kind in ("container", "pickup", "skull", "flow")}
            raw, records, _ = callbacks(roster)
            for record in records:
                with self.subTest(item=item, kind=record["metadata"]["kind"]):
                    run = Pickup(raw)
                    run.run(record["pickup"])
                    self.assertEqual({row["flag_name"] for row in records if run.values.get(row["flag_name"])},
                                     {record["flag_name"]})
                    metadata = ITEM_DATA[item]
                    effects = grants(run.trace)
                    if metadata["mode"] == "generic":
                        self.assertFalse(effects)
                        prefix = "DungeonInfo." + DUNGEONS[metadata["dungeon"]] + "."
                        field = {"SmallKey": "SmallKeyNum", "BossKey": "IsGetBossKey", "Map": "IsGetMap"}[metadata["kind"]]
                        self.assertEqual(run.values[prefix + field], 1)
                    elif is_cure(metadata):
                        self.assertFalse(effects)
                        self.assertEqual([args["ActorName"] for action, args in run.trace
                                          if action == "EventTriggerRecoverByCureItem"], [metadata["actor"]])
                    else:
                        self.assertEqual([effect["Actor"] for effect in effects], [metadata.get("tiers", [metadata["actor"]])[0]])
                        self.assertTrue(all(effect["Num"] == 1 for effect in effects), "Do not multiply the native bundle yield")
                    last_effect = max(index for index, (action, params) in enumerate(run.trace)
                                      if action in {"EventTriggerAddOrRemovePouchContent", "EventTriggerRecoverByCureItem",
                                                    "EventTriggerAddOrSubGameDataInt", "EventTriggerSetGameDataBool"}
                                      and params.get("GameDataName") != record["flag_name"])
                    commit = next(index for index, (_, params) in enumerate(run.trace)
                                  if params.get("GameDataName") == record["flag_name"])
                    self.assertLess(last_effect, commit)
                    before = list(run.trace)
                    run.run(record["actor"])
                    self.assertEqual(grants(run.trace), grants(before))
                    assert_no_receipt_cursor(self, run.trace)

    def test_second_and_third_bomb_bags_preview_and_grant_real_upgrades_without_phantom_items(self):
        sources = names("container", 3)
        raw, records, _ = callbacks({name: reward("Bomb Bag") for name in sources})
        run = Pickup(raw)
        for index, record in enumerate(records):
            before = len(run.trace)
            run.run(record["pickup"])
            expected = ITEM_DATA["Bomb Bag"]["tiers"][index]
            self.assertEqual([effect["Actor"] for effect in grants(run.trace[before:])], [expected])
            self.assertEqual([params["Actor"] for action, params in run.trace[before:]
                              if action == "EventTriggerSetForGetWindow"], [expected])
            self.assertIn(expected, run.held)
            self.assertTrue(run.values[record["flag_name"]])
        self.assertEqual([effect["Actor"] for effect in grants(run.trace)], ITEM_DATA["Bomb Bag"]["tiers"])
        for record in reversed(records):
            run.run(record["actor"])
        self.assertEqual(len(grants(run.trace)), 3)

    def test_unsupported_ammo_gives_nothing_and_replaying_after_getting_bag_still_gives_nothing(self):
        locations = names("container", 2)
        for ammo, family in (("Bombs (20)", "Bomb Bag"), ("Arrows (30)", "Bow"), ("Deku Seeds (30)", "Slingshot")):
            with self.subTest(ammo=ammo):
                roster = {locations[0]: reward(ammo), locations[1]: reward(family)}
                raw, records, _ = callbacks(roster)
                by_name = {record["name"]: record for record in records}
                run = Pickup(raw)
                run.run(by_name[locations[0]]["actor"])
                self.assertFalse(grants(run.trace))
                self.assertFalse(run.windows)
                self.assertTrue(run.values[by_name[locations[0]]["flag_name"]])
                run.run(by_name[locations[1]]["pickup"])
                run.run(by_name[locations[0]]["pickup"])
                self.assertEqual([effect["Actor"] for effect in grants(run.trace)], [ITEM_DATA[family]["tiers"][0]])
                self.assertNotIn("TBox_Rupee_Green", run.held)
                for bag in AMMO_BAGS[ITEM_DATA[ammo]["actor"]]:
                    owned = Pickup(raw)
                    owned.held.add(bag)
                    owned.run(by_name[locations[0]]["pickup"])
                    self.assertEqual([effect["Actor"] for effect in grants(owned.trace)], [ITEM_DATA[ammo]["actor"]])
                    self.assertEqual(grants(owned.trace)[0]["Num"], 1)

    def test_all_progressive_families_restore_the_next_level_and_saturate(self):
        for family, metadata in ITEM_DATA.items():
            if metadata["mode"] != "tiers":
                continue
            locations = names("container", len(metadata["tiers"]) + 1)
            roster = {name: reward(family) for name in locations}
            raw, records, _ = callbacks(roster)
            run = Pickup(raw)
            for record in records:
                run.run(record["actor"])
            expected = [*metadata["tiers"], metadata["tiers"][-1]]
            with self.subTest(family=family):
                self.assertEqual([effect["Actor"] for effect in grants(run.trace)], expected)
                restored, _ = restoration.build_restoration_flow(raw, roster, settings(roster))
                older = SaveRun(restored)
                for record in records:
                    older.restore(record["name"])
                self.assertEqual([effect["Actor"] for effect in grants(older.trace)], expected)
                for record in records:
                    older.restore(record["name"])
                self.assertEqual([effect["Actor"] for effect in grants(older.trace)], expected)

    def test_foreign_item_uses_one_token_and_does_not_give_its_zelda_namesake(self):
        roster = {names(kind)[0]: reward("Bomb Bag", local=False) for kind in ("container", "pickup", "skull", "flow")}
        raw, records, _ = callbacks(roster)
        for record in records:
            with self.subTest(kind=record["metadata"]["kind"]):
                run = Pickup(raw)
                run.run(record["actor"])
                self.assertEqual([effect["Actor"] for effect in grants(run.trace)], [record["actor"]])
                self.assertTrue(run.values[record["flag_name"]])
                self.assertTrue(set(ITEM_DATA["Bomb Bag"]["tiers"]).isdisjoint(run.held))
                run.run(record["pickup"])
                self.assertEqual(len(grants(run.trace)), 1)
                assert_no_receipt_cursor(self, run.trace)

    def test_authored_ground_preview_and_effect_are_one_gain_for_important_and_small_items(self):
        locations = names("pickup", 3)
        roster = dict(zip(locations, (reward("Bomb Bag"), reward("Rupees (20)"), reward("Bow", local=False))))
        pouch, records, effects = callbacks(roster)
        for name in ap_skulls.PICKUP_FLOWS:
            ground = ap_skulls.patch_pickup_presentation(ground_flow(name), records, effects, name)
            for record in records:
                with self.subTest(flow=name, item=record.get("local_item")):
                    run = Pickup({"GetPouchContent": pouch, name: ground})
                    entry = "PouchAddItem" if name == "Dm_SY_Get" else name
                    run.call(entry, {"ActorName": record["pickup"]}, name)
                    self.assertEqual(len(run.windows), 1)
                    self.assertFalse(run.windows[0][1].get(record["flag_name"]))
                    self.assertTrue(run.values[record["flag_name"]])
                    count = len(grants(run.trace)) + sum(action == "EventTriggerAddOwnToPouch" for action, _ in run.trace)
                    self.assertEqual(count, 1)
                    self.assertTrue(all(effect["Num"] == 1 for effect in grants(run.trace)))
                    run.call(entry, {"ActorName": record["actor"]}, name)
                    self.assertEqual(len(grants(run.trace)) + sum(action == "EventTriggerAddOwnToPouch" for action, _ in run.trace), 1)

    def test_older_save_restores_personal_items_once_and_foreign_checks_without_a_second_send(self):
        locations = [names(kind)[0] for kind in ("container", "pickup", "skull", "flow")]
        roster = dict(zip(locations, (reward("Bomb Bag"), reward("Rupees (20)"),
                                      reward("Small Key (Forest Temple)"), reward("Bow", local=False))))
        configuration = settings(roster)
        source, records, _ = callbacks(roster)
        raw, entries = restoration.build_restoration_flow(source, roster, configuration)
        self.assertEqual(set(entries), {LOCATION_IDS[name] for name in roster})
        older = SaveRun(raw)
        for record in records:
            older.restore(record["name"])
            self.assertTrue(older.values[record["flag_name"]])
            self.assertEqual(older.values[restoration.RESULT], LOCATION_IDS[record["name"]])
        self.assertEqual(older.inventory, Counter({"Item_BombBag_Small": 1, "TBox_Rupee_Red": 1}))
        self.assertEqual(older.values["DungeonInfo.ForestTemple.SmallKeyNum"], 1)
        previous = older.inventory.copy(), dict(older.values)
        for record in records:
            older.restore(record["name"])
        self.assertEqual(older.inventory, previous[0])
        replay = Pickup(raw)
        replay.values = dict(older.values)
        replay.held.update(actor for actor, count in older.inventory.items() if count > 0)
        for record in records:
            replay.run(record["pickup"])
        self.assertFalse(grants(replay.trace))
        self.assertEqual(replay.values["DungeonInfo.ForestTemple.SmallKeyNum"], 1)
        self.assertFalse(any(record["actor"] in older.inventory for record in records))
        assert_no_receipt_cursor(self, older.trace + replay.trace)

    def test_network_restoration_preserves_mastered_trade_consumption_and_master_sword_flags(self):
        source = names("container")[0]
        trade = "LW Trade Cojiro"
        roster = {source: reward("Cojiro"), trade: reward(local=False), MASTER_SWORD: reward(local=False)}
        config = settings(roster, adult_trade_shuffle=True)
        raw, _ = restoration.build_restoration_flow(native_flow(), roster, config)
        run = SaveRun(raw)
        run.inventory["Item_CojiroCucco"] = run.inventory["Item_Prescription"] = 1
        run.restore(trade).restore(source).restore(trade).restore(source).restore(MASTER_SWORD)
        self.assertEqual(run.inventory["Item_CojiroCucco"], 0)
        self.assertEqual(run.inventory["Item_Prescription"], 1)
        self.assertTrue(run.values[TRADE_CHECKS[trade]["flag_name"]])
        self.assertTrue(run.values[MASTER_SWORD_FLAG])
        self.assertTrue(run.values[flag_name(source)])
        legacy = restoration.restoration_records({trade: reward(local=False)})[0]
        self.assertEqual(legacy["flags"], [TRADE_CHECKS[trade]["flag_name"]])

    def test_saved_source_identity_is_not_inferred_from_native_inventory_or_another_check(self):
        locations = names("container", 2)
        roster = {name: reward("Bomb Bag") for name in locations}
        raw, records, _ = callbacks(roster)
        run = Pickup(raw)
        run.held.update(ITEM_DATA["Bomb Bag"]["tiers"])
        run.run("Item_Token_Gold")
        self.assertFalse(any(run.values.get(record["flag_name"]) for record in records))
        run.values[records[0]["flag_name"]] = True
        run.run(records[1]["pickup"])
        self.assertTrue(run.values[records[1]["flag_name"]])
        self.assertEqual(grants(run.trace)[-1]["Actor"], "Item_BombBag_Large")

    def test_stale_source_flags_metadata_hashes_and_unsafe_refills_are_rejected(self):
        name = names("container")[0]
        _, records, _ = callbacks({name: reward("Bomb Bag")})
        for field, value in (("flag_name", "Archipelago.Source.0"), ("flag_hash", 1),
                             ("hash", "1"), ("files", []), ("metadata", {}),
                             ("native_actor", "Item_BombBag_Large")):
            with self.subTest(field=field):
                malformed = copy.deepcopy(records)
                malformed[0][field] = value
                with self.assertRaises(ValueError):
                    ap_skulls.patch_skull_flow(native_flow(), malformed)
        for kind in ("container", "pickup", "skull", "flow"):
            name = names(kind)[0]
            with self.subTest(kind=kind):
                with self.assertRaises(ValueError):
                    network_rewards.source_records({name: reward("Buy Fish")}, settings({name: reward("Buy Fish")}))

    def test_queued_callback_commits_inventory_and_flag_before_autosave(self):
        name = names("container")[0]
        raw, records, _ = callbacks({name: reward("Bomb Bag")})
        run = QueuedSourceRun(raw).collect(records[0])
        self.assertFalse(run.saves)
        self.assertIn(("stock", "Item_BombBag_Small", 1), run.pending)
        self.assertIn(("set", records[0]["flag_name"], True), run.pending)
        run.flush()  # End of the native frame, including the requested save.
        self.assertEqual(run.inventory["Item_BombBag_Small"], 1)
        self.assertTrue(run.values[records[0]["flag_name"]])
        self.assertTrue(run.saves[-1][0][records[0]["flag_name"]])
        self.assertEqual(run.saves[-1][1]["Item_BombBag_Small"], 1)
        run.collect(records[0], "pickup")
        run.flush()
        self.assertEqual(run.inventory["Item_BombBag_Small"], 1)

    def test_queued_old_save_recovery_commits_inventory_and_flag_before_autosave(self):
        name = names("pickup")[0]
        roster = {name: reward("Bomb Bag")}
        raw, _ = restoration.build_restoration_flow(native_flow(), roster, settings(roster))
        run = QueuedSourceRun(raw).run(restoration.event_name(LOCATION_IDS[name]))
        self.assertFalse(run.saves)
        self.assertIn(("stock", "Item_BombBag_Small", 1), run.pending)
        self.assertIn(("set", flag_name(name), True), run.pending)
        run.flush()
        self.assertEqual(run.inventory["Item_BombBag_Small"], 1)
        self.assertTrue(run.values[flag_name(name)])
        self.assertTrue(run.saves[-1][0][flag_name(name)])
        self.assertEqual(run.saves[-1][1]["Item_BombBag_Small"], 1)
        run.run(restoration.event_name(LOCATION_IDS[name]))
        run.flush()
        self.assertEqual(run.inventory["Item_BombBag_Small"], 1)


if __name__ == "__main__":
    unittest.main()
