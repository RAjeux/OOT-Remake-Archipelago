"""Old saves recover journaled AP checks without resending or duplicating items."""
from collections import Counter
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from evfl.common import Argument
from evfl.entry_point import EntryPoint
from evfl.event import ActionEvent, SubFlowEvent, SwitchEvent
from evfl.util import make_index
from oot_rando.formats import byml_codec as by
from oot_rando.game import resource_allocations
from oot_rando.patching import chest_flags
from oot_rando.patching.progressive import FlowEditor
from oot_rando.patching.soul_adapter import murmur3
from ootrr_triforce import ap_skulls, native_setup, restoration as restore
from ootrr_triforce.catalog import AP_SKULL_CHECKS, CHESTS, ITEM_DATA, ITEM_IDS, LOCATION_IDS, SHOP_CHECKS, TRADE_CHECKS
from ootrr_triforce.cursor_resource import append_transient_index
from ootrr_triforce.receipt_events import CURSOR_PREFIX, OWNERS
from test_receipt_events import native_flow
from test_receipt_registration import IdentityCodec

CHEST = next(iter(CHESTS))
MULTI = next(name for name, refs in CHESTS.items() if len(refs) > 1)
SHOP = next(iter(SHOP_CHECKS))
SKULL = sorted(AP_SKULL_CHECKS)[0]


def reward(item="Rupees (5)", local=True):
    return dict(item=item, item_id=ITEM_IDS[item] if local else 123456,
                player="Zelda" if local else "Friend", owner=2 if local else 1,
                local=local, game="Ocarina of Time Remake" if local else "Another Game")


def pouch():
    editor = FlowEditor(native_flow(), "native recovery fixture")
    for name in ("OpenGetWindow", "OpenRupeeUIIfNeed", "CloseRupeeUIIfNeed"):
        point = EntryPoint(name)
        point.main_event = make_index(None)
        editor.chart.entry_points.append(point)
    return editor.write("native recovery fixture")[0]


def document(root, endian="<"):
    return by.dump(dict(root=root, endian=endian, version=7))


def game_data(endian="<"):
    return document(dict(Data=dict(Int=[
        dict(Hash=by.U32(1), DefaultValue=0, SaveFileIndex=-1, ResetTypeValue=8),
        dict(Hash=by.U32(2), DefaultValue=7, SaveFileIndex=0, ResetTypeValue=8)],
        Bool=[dict(Hash=by.U32(3), DefaultValue=True, SaveFileIndex=0, ResetTypeValue=8)],
        Native64=[by.U64(0x9876543210123456)]),
        MetaData=dict(SaveDataSize=[100, 56], SaveDataOffsetPos=[100, 56],
                      AllDataSaveSize=130, AllDataSaveOffset=145)), endian)


class SaveRun:
    """Model the native write queue and pouch operations, with explicit saves."""
    def __init__(self, raw):
        self.entries = {point.name: point.main_event.v for point in FlowEditor(raw, "recovery model").chart.entry_points}
        self.values = {"Fixture.NativeHookEnabled": True}
        self.inventory, self.trace, self.saves = Counter(), [], []
        self.empty_bottle = False
        self.steps = 0

    def run(self, entry, arguments=None):
        node = self.entries[entry]
        arguments = arguments or {}
        while node is not None:
            self.steps += 1
            assert self.steps < 5000, "Restoration loop"
            data = node.data
            params = {key: arguments[value] if isinstance(value, Argument) else value
                      for key, value in (data.params.data.items() if data.params else ())}
            if isinstance(data, ActionEvent):
                action = data.actor_action.v.v
                self.trace.append((action, params))
                if action in {"EventTriggerSetGameDataBool", "EventTriggerSetGameDataInt", "EventTriggerSetGameDataString64"}:
                    self.values[params["GameDataName"]] = params["Value"]
                elif action == "EventTriggerAddOrSubGameDataInt":
                    key = params["GameDataName"]
                    self.values[key] = self.values.get(key, 0) + params["Value"]
                elif action == "EventTriggerAddOrRemovePouchContent":
                    self.inventory[OWNERS.get(params["Actor"], params["Actor"])] += params["Num"]
                elif action == "EventTriggerPushToEmptyBottle":
                    assert self.empty_bottle, "No bottle may be consumed after a failed preflight"
                    self.inventory["Bottle:" + str(params["Item"])] += 1
                    self.empty_bottle = False
                elif action == "EventTriggerRecoverByCureItem":
                    self.inventory[params["ActorName"]] += 1
                elif action == "EventTriggerRequestAutoSave":
                    self.saves.append((copy.deepcopy(self.values), self.inventory.copy()))
                elif action == "EventWait":
                    assert params == {"Frames": 1, "IsWaitEnd": True}
                else:
                    raise AssertionError("Unexpected presentation or action: " + action)
                node = data.nxt.v
            elif isinstance(data, SwitchEvent):
                query = data.actor_query.v.v
                if query == "EventQueryIsGameDataBool":
                    result = bool(self.values.get(params["GameDataName"]))
                elif query == "EventQueryCheckIsGet":
                    result = self.inventory[params["ActorName"]] > 0
                elif query == "EventQueryIsAnyBottleEmpty":
                    result = self.empty_bottle
                elif query == "EventQueryIsExistInPouch":
                    result = self.inventory[OWNERS.get(params["Actor"], params["Actor"])] >= params["Num"]
                else:
                    raise AssertionError("Unexpected restoration query: " + query)
                # A missing branch is a normal terminal return in native EVFL.
                branch = data.cases.get(0 if result else 1)
                node = branch.v if branch is not None else None
            elif isinstance(data, SubFlowEvent):
                assert data.res_flowchart_name == "", "Quiet restoration must not call UI/camera events"
                assert params.get("IsShowNumDisplay", False) is False
                self.run(data.entry_point_name, params)
                node = data.nxt.v
            else:
                raise AssertionError("Unknown recovery step")
        return self

    def restore(self, name):
        return self.run(restore.event_name(LOCATION_IDS[name]))


class RestorationFlowTests(unittest.TestCase):
    def graph(self, roster, source=None):
        raw, entries = restore.build_restoration_flow(source or pouch(), roster)
        self.assertEqual(set(entries), {LOCATION_IDS[name] for name in roster})
        chart = FlowEditor(raw, "recovery result").chart
        for event in chart.events:
            params = getattr(event.data, "params", None)
            if event.name.startswith(restore.PREFIX) and params:
                self.assertFalse(str(params.data.get("GameDataName", "")).startswith(CURSOR_PREFIX))
        return SaveRun(raw)

    def test_older_save_recovers_once_and_preserves_original_native_bag_hook(self):
        run = self.graph({CHEST: reward("Bombs (5)")})
        run.restore(CHEST)
        actor = "TBox_Rupee_Green"
        self.assertFalse(run.inventory, "Missing equipment must not grant ammo, a bag or a replacement")
        self.assertEqual(run.inventory["Item_BombBundle_Small"], 0)
        self.assertEqual(run.inventory["Item_BombBag_Small"], 0)
        self.assertFalse(run.values.get("Fixture.NativeBagHook", False))
        self.assertEqual(run.values[restore.RESULT], LOCATION_IDS[CHEST])
        self.assertEqual(run.trace[-2][0], "EventTriggerRequestAutoSave")
        self.assertEqual(run.trace[-1][1]["GameDataName"], restore.RESULT)
        record = restore.restoration_records({CHEST: reward()})[0]
        self.assertTrue(all(run.saves[-1][0][flag] for flag in record["flags"]))
        run.restore(CHEST)
        self.assertFalse(any(run.inventory.values()))
        # A separate earlier save has no effect or flag; its recovery is needed.
        older = self.graph({CHEST: reward("Bombs (5)")})
        older.inventory["Item_BombBag_Small"] = 1
        older.restore(CHEST)
        self.assertEqual(older.inventory["Item_BombBundle_Small"], 1)
        self.assertEqual(older.inventory[actor], 0)

    def test_one_existing_reference_prevents_a_second_grant_and_completes_all_flags(self):
        run = self.graph({MULTI: reward("Rupees (20)")})
        flags = restore.restoration_records({MULTI: reward()})[0]["flags"]
        run.values[flags[-1]] = True
        run.restore(MULTI)
        self.assertFalse(run.inventory)
        self.assertTrue(all(run.values[flag] for flag in flags))

    def test_foreign_shop_restores_sold_state_without_payment_or_remote_send(self):
        run = self.graph({SHOP: reward(local=False), SKULL: reward(local=False)})
        run.restore(SHOP).restore(SKULL)
        self.assertFalse(run.inventory)
        self.assertTrue(run.values[SHOP_CHECKS[SHOP]["flag_name"]])
        self.assertTrue(all(run.values[name] == 1 for name in SHOP_CHECKS[SHOP]["counters"]))
        self.assertEqual(len(run.saves), 2)

    def test_each_shop_recovers_only_selected_purchases_and_shared_age_stock_once(self):
        names = [next(name for name, row in SHOP_CHECKS.items() if row["shop"] == shop)
                 for shop in dict.fromkeys(row["shop"] for row in SHOP_CHECKS.values())]
        roster = {name: reward("Bow", local=index % 2 == 0) for index, name in enumerate(names)}
        run = self.graph(roster)
        for name in names:
            run.restore(name)
            row = SHOP_CHECKS[name]
            self.assertTrue(run.values[row["flag_name"]])
            self.assertTrue(all(run.values[counter] == 1 for counter in row["counters"]))
        inventory = run.inventory.copy()
        for name in names:
            for counter in SHOP_CHECKS[name]["counters"]:
                run.values[counter] = 0
            run.restore(name)
            self.assertTrue(all(run.values[counter] == 1 for counter in SHOP_CHECKS[name]["counters"]))
        self.assertEqual(run.inventory, inventory)
        self.assertEqual(sum(inventory.values()), 4)
        self.assertEqual(len(run.saves), 16)
        for name in set(SHOP_CHECKS).difference(names):
            self.assertNotIn(SHOP_CHECKS[name]["flag_name"], run.values)
            self.assertTrue(set(SHOP_CHECKS[name]["counters"]).isdisjoint(run.values))

    def test_progressive_rewards_select_current_native_tier_and_do_not_duplicate(self):
        run = self.graph({CHEST: reward("Bomb Bag"), MULTI: reward("Bomb Bag")})
        tiers = ITEM_DATA["Bomb Bag"]["tiers"]
        run.restore(CHEST).restore(MULTI).restore(CHEST)
        self.assertEqual(run.inventory, Counter({tiers[0]: 1, tiers[1]: 1}))

    def test_existing_highest_capacity_never_restores_a_lower_tier_or_repeats_a_check(self):
        names = list(CHESTS)[:4]
        for family in ("Bomb Bag", "Bow", "Progressive Wallet"):
            with self.subTest(family=family):
                run = self.graph({name: reward(family) for name in names})
                highest = ITEM_DATA[family]["tiers"][-1]
                run.inventory[OWNERS.get(highest, highest)] = 1
                for name in [*names, names[0], names[-1]]:
                    run.restore(name)
                grants = [params["Actor"] for action, params in run.trace
                          if action == "EventTriggerAddOrRemovePouchContent"]
                self.assertEqual(grants, [highest] * len(names))

    def test_blocked_refill_defers_without_flags_save_or_effect_then_commits_once(self):
        run = self.graph({CHEST: reward("Buy Fish"), MULTI: reward("Rupees (5)")})
        run.restore(CHEST)
        self.assertEqual(run.values[restore.RESULT], -LOCATION_IDS[CHEST])
        self.assertFalse(run.saves)
        self.assertFalse(run.inventory)
        self.assertFalse(any(run.values.get(flag) for flag in restore.restoration_records({CHEST: reward()})[0]["flags"]))
        run.restore(MULTI)
        self.assertTrue(run.inventory)
        run.empty_bottle = True
        run.restore(CHEST).restore(CHEST)
        self.assertEqual(sum(amount for name, amount in run.inventory.items() if name.startswith("Bottle:")), 1)
        self.assertFalse(run.empty_bottle)
        self.assertEqual(run.values[restore.RESULT], LOCATION_IDS[CHEST])

    def test_restoration_uses_native_fallback_after_skull_dispatch_not_ap_ack(self):
        source = ap_skulls.patch_skull_flow(pouch(), ap_skulls.skull_records({SKULL: reward("Bombs (5)")}))
        run = self.graph({SKULL: reward("Bombs (5)")}, source)
        run.inventory["Item_BombBag_Small"] = 1
        run.restore(SKULL)
        self.assertEqual(run.inventory["Item_BombBundle_Small"], 1)
        self.assertNotIn(ap_skulls.SCRATCH, run.values)

    def test_trade_rollback_consumes_exact_input_and_late_source_cannot_restore_spent_token(self):
        name = "LW Trade Cojiro"
        run = self.graph({name: reward(local=False), CHEST: reward("Cojiro")})
        run.inventory["Item_CojiroCucco"] = run.inventory["Item_Prescription"] = 1
        run.restore(name)
        self.assertEqual(run.inventory["Item_CojiroCucco"], 0)
        self.assertEqual(run.inventory["Item_Prescription"], 1)
        run.restore(CHEST).restore(name).restore(CHEST)
        self.assertEqual(run.inventory["Item_CojiroCucco"], 0)
        self.assertEqual(run.inventory["Item_Prescription"], 1)

    def test_restoring_completed_cucco_trade_also_preserves_its_talon_prerequisite(self):
        from ootrr_triforce.trade_catalog import TALON_AWAKE
        name = "Kak Anju Trade Pocket Cucco"
        run = self.graph({name: reward("Rupees (5)")})
        run.inventory["Item_PocketCucco"] = 1
        run.restore(name)
        self.assertTrue(run.values[TALON_AWAKE])
        self.assertEqual(run.inventory["Item_PocketCucco"], 0)

    def test_native_fallback_accepts_only_the_authored_skull_commit_barrier(self):
        source = ap_skulls.patch_skull_flow(pouch(), ap_skulls.skull_records({SKULL: reward("Bombs (5)")}))
        editor = FlowEditor(source, "tampered skull barrier")
        barrier = next(event for event in editor.chart.events if event.name == ap_skulls.PREFIX + "SelectReady")
        barrier.data.params.data["Frames"] = 0
        editor.expected[barrier.name] = dict(barrier.data.params.data)
        with self.assertRaises(ValueError):
            restore.build_restoration_flow(editor.write("tampered skull barrier")[0], {SKULL: reward("Bombs (5)")})

    def test_all_exported_locations_have_verifiable_native_flags(self):
        roster = {name: reward(local=False) for name in (*CHESTS, *SHOP_CHECKS, *AP_SKULL_CHECKS)}
        self.assertEqual(len(restore.restoration_records(roster)), len(CHESTS) + len(SHOP_CHECKS) + len(AP_SKULL_CHECKS))
        self.graph(roster)
        with self.assertRaises(ValueError):
            restore.restoration_records({"Unknown check": reward()})
        with self.assertRaises(ValueError):
            restore.restoration_records({CHEST: reward("Bombs (5)") | {"item_id": ITEM_IDS["Bow"]}})


class RestorationPreparationTests(unittest.TestCase):
    def prepare(self, folder, roster):
        romfs, mod = folder / "game", folder / "stage/Archipelago/romfs"
        resources = {
            "Pack/ZsDic.pack.zs": b"dictionary", restore.FLOW_PATH: pouch(),
            restore.GAME_DATA: game_data(), restore.REST: b"native sizes",
            chest_flags.EVENT_SETTINGS: document([dict(__RowId="Dm_SY_Get", EntryPointName="Dm_SY_Get",
                FlowchartFileName="Work/Event/EventFlow/Dm_SY_Get.evfc", EventSettingComponentList="NativeParticipants")]),
            chest_flags.ANALYZED: document([dict(__RowId="Dm_SY_Get", IsPlayerWarpFirstFrame=True,
                RecordedCameraInfo={"NativeCamera": "preserved"}, SubFlowList=["UnrelatedCamera"])])}
        for path, raw in resources.items():
            target = romfs / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        with patch.object(restore, "Codec", IdentityCodec), \
                patch.object(resource_allocations, "grow_resources", return_value=(b"grown sizes", {})):
            result = restore.prepare_restoration(romfs, mod, roster)
        self.assertEqual(result["locations"], sorted(LOCATION_IDS[name] for name in roster))
        for path, raw in resources.items():
            self.assertEqual((romfs / path).read_bytes(), raw)
        return romfs, mod

    def test_unsaved_status_preserves_save_layout_and_existing_64_bit_values(self):
        for endian in ("<", ">"):
            raw = game_data(endian)
            before = by.load(raw)["root"]
            result = append_transient_index(raw, murmur3(restore.RESULT))
            after = by.load(result)["root"]
            self.assertEqual(after["MetaData"], before["MetaData"])
            self.assertEqual(after["Data"]["Native64"], before["Data"]["Native64"])
            self.assertEqual([row for row in after["Data"]["Int"] if row["Hash"] != murmur3(restore.RESULT)], before["Data"]["Int"])
            self.assertTrue(restore._status_field(result))
            with self.assertRaises(ValueError):
                append_transient_index(result, murmur3(restore.RESULT))

    def test_registry_proof_enables_only_exact_present_routes_and_rejects_stale_metadata(self):
        roster = {CHEST: reward(), SHOP: reward(local=False)}
        with tempfile.TemporaryDirectory() as temp, patch.object(restore, "Codec", IdentityCodec):
            folder = Path(temp)
            _, mod = self.prepare(folder, roster)
            self.assertEqual(restore.prepared_locations(mod, roster), sorted(LOCATION_IDS[name] for name in roster))
            analyzed = by.load((mod / chest_flags.ANALYZED).read_bytes())
            for row in analyzed["root"]:
                if row["__RowId"].startswith(restore.PREFIX):
                    self.assertEqual(row["SubFlowList"], ["GetPouchContent"])
                    self.assertIs(row["IsPlayerWarpFirstFrame"], False)
                    self.assertNotIn("RecordedCameraInfo", row)
            old = (mod / chest_flags.ANALYZED).read_bytes()
            analyzed["root"] = [row for row in analyzed["root"] if row["__RowId"] != restore.event_name(LOCATION_IDS[CHEST])]
            (mod / chest_flags.ANALYZED).write_bytes(by.dump(analyzed))
            with self.assertRaises(ValueError):
                restore.prepared_locations(mod, roster)
            (mod / chest_flags.ANALYZED).write_bytes(old)
            with self.assertRaises(ValueError):
                restore.prepared_locations(mod, [CHEST])
            (mod / restore.MARKER).unlink()
            self.assertEqual(restore.prepared_locations(mod, roster), [])

    def test_session_remains_disabled_for_old_mods_and_binds_numeric_owner_after_proof(self):
        roster = {CHEST: reward(), SHOP: reward(local=False)}
        with tempfile.TemporaryDirectory() as temp, patch.object(restore, "Codec", IdentityCodec), \
                patch.object(native_setup, "detect_language", return_value="en"):
            root = Path(temp)
            _, mod = self.prepare(root, roster)
            data = dict(checks=list(roster), room="test room", slot="Zelda", token="a" * 64, player=2,
                        local_items=True, reward_mode="all_locations")
            config = dict(server="ws://localhost:38281", protected="", baseline=0)
            native_setup.save_session(root, config, data, roster)
            self.assertEqual(json.loads((root / "native-session.json").read_bytes())["RecoveryLocations"], [])
            native_setup.save_session(root, config, data, roster, prepared=mod)
            session = json.loads((root / "native-session.json").read_bytes())
            self.assertEqual(session["RecoveryLocations"], sorted(LOCATION_IDS[name] for name in roster))
            row = session["Checks"][str(LOCATION_IDS[SHOP])]
            self.assertEqual((row["ItemID"], row["Recipient"], row["Owner"]), (123456, 1, "Friend"))
            with self.assertRaises(ValueError):
                native_setup.save_session(root, config, data, roster | {CHEST: reward() | {"owner": 1}}, prepared=mod)


if __name__ == "__main__":
    unittest.main()
