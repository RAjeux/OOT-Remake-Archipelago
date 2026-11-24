"""Trade rewards replace the quest gift and commit one native item/check."""
from collections import Counter
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from evfl.common import Argument
from evfl.entry_point import EntryPoint
from evfl.event import ActionEvent, SubFlowEvent, SwitchEvent
from evfl.util import make_index
from oot_rando.patching.event_info import reachable
from oot_rando.patching.progressive import FlowEditor, link
from ootrr_triforce import ap_trade
from ootrr_triforce.catalog import ITEM_DATA, ITEM_IDS
from ootrr_triforce.native_presentations import AMMO_BAGS, CAMERA_FACING_FLOW, PRESENTER_NAME, is_cure
from ootrr_triforce.receipt_events import CURSOR_PREFIX, OWNERS
from ootrr_triforce.trade_catalog import TALON_AWAKE, TRADE_CHECKS, event_name
from test_receipt_events import native_flow
from test_presented_receipts import native_presenter, native_facing_animation

ANJU, CUCCO, COJIRO = list(TRADE_CHECKS)[:3]
INFO = json.loads((ROOT / "tests/fixtures/pouch-presentation-info.json").read_bytes())["actors"]


def reward(item="Rupees (5)", local=True):
    return dict(item=item, item_id=ITEM_IDS[item] if local else 456789,
                local=local, player="Zelda" if local else "Friend", owner=2 if local else 1)


def pouch_fixture():
    editor = FlowEditor(native_flow(), "Trade transaction pouch fixture")
    # A native display ending in a caption save is deliberately dangerous for
    # a transaction that has consumed its input before the final item grant.
    for name in ("OpenGetWindow", "OpenRupeeUIIfNeed", "CloseRupeeUIIfNeed"):
        point = EntryPoint(name)
        point.main_event = make_index(None)
        editor.chart.entry_points.append(point)
    target = editor.action("NativeDisplayTarget", "PouchSystemActor", "EventTriggerSetForGetWindow",
                           {"Actor": Argument("ActorName")})
    caption = editor.subflow("NativeDisplayCaption", "", "OpenGetWindow_End", None)
    link(target, caption)
    point = EntryPoint("DisplayGetByActorName")
    point.main_event = make_index(target)
    editor.chart.entry_points.append(point)
    return editor.write("Trade native display fixture")[0]


def presenter_fixture():
    editor = FlowEditor(native_presenter(), "Trade presenter fixture")
    callback = next(node for node in editor.chart.events if node.name == "NativeCallback")
    # A second caption-like request in the presenter must also be bypassed.
    unsafe = editor.action("NativePrematureSave", "GameSystemActor", "EventTriggerRequestAutoSave", None)
    link(unsafe, callback)
    for node in list(editor.chart.events):
        if node is unsafe:
            continue
        from ootrr_triforce.shop_events import _retarget
        _retarget(node, callback, unsafe)
    return editor.write("Trade native presenter save fixture")[0]


class Interrupted(Exception):
    pass


class TradeRun:
    """Separate queued GameData writes from saved current inventory state."""
    def __init__(self, pouch, presenter):
        self.charts = {FLOW: FlowEditor(raw, FLOW).chart for FLOW, raw in (
            (ap_trade.FLOW_NAME, pouch), (PRESENTER_NAME, presenter),
            (CAMERA_FACING_FLOW, native_facing_animation()))}
        self.values = {"Fixture.NativeHookEnabled": True, TALON_AWAKE: True}
        self.pending, self.inventory, self.trace, self.saves = {}, Counter(), [], []
        self.historical = set()
        self.empty_bottle = True
        self.stop_after = None
        self.steps = 0

    def run(self, entry, arguments=None, flow=ap_trade.FLOW_NAME):
        chart = self.charts[flow]
        point = next(point for point in chart.entry_points if point.name == entry)
        node, arguments = point.main_event.v, arguments or {}
        while node is not None:
            self.steps += 1
            assert self.steps < 20000
            data = node.data
            params = {key: arguments[value] if isinstance(value, Argument) else value
                      for key, value in (data.params.data.items() if data.params else ())}
            if isinstance(data, ActionEvent):
                if self.stop_after is not None and len(self.trace) == self.stop_after:
                    raise Interrupted()
                action = data.actor_action.v.v
                self.trace.append((action, params))
                if action in {"EventTriggerSetGameDataBool", "EventTriggerSetGameDataInt", "EventTriggerSetGameDataString64"}:
                    self.pending[params["GameDataName"]] = params["Value"]
                elif action == "EventTriggerAddOrSubGameDataInt":
                    key = params["GameDataName"]
                    self.pending[key] = self.pending.get(key, self.values.get(key, 0)) + params["Value"]
                elif action == "EventWait":
                    assert params == {"Frames": 1, "IsWaitEnd": True}
                    self.values.update(self.pending)
                    self.pending.clear()
                elif action == "EventTriggerAddOrRemovePouchContent":
                    actor = OWNERS.get(params["Actor"], params["Actor"])
                    self.inventory[actor] = max(0, self.inventory[actor] + params["Num"])
                    if params["Num"] > 0:
                        self.historical.add(actor)
                elif action == "EventTriggerPushToEmptyBottle":
                    assert self.empty_bottle
                    self.empty_bottle = False
                    self.inventory["Bottle:" + str(params["Item"])] += 1
                elif action == "EventTriggerRecoverByCureItem":
                    self.inventory[params["ActorName"]] += 1
                elif action == "EventTriggerRequestAutoSave":
                    self.saves.append((dict(self.values), self.inventory.copy()))
                node = data.nxt.v
            elif isinstance(data, SwitchEvent):
                query = data.actor_query.v.v
                if query == "EventQueryIsGameDataBool":
                    yes = bool(self.values.get(params["GameDataName"]))
                elif query == "EventQueryIsExistInPouch":
                    yes = self.inventory[params["Actor"]] >= params["Num"]
                elif query == "EventQueryCheckIsGet":
                    yes = params["ActorName"] in self.historical or self.inventory[params["ActorName"]] > 0
                elif query == "EventQueryIsAnyBottleEmpty":
                    yes = self.empty_bottle
                elif query == "FixtureIsImportant":
                    yes = True
                elif query == "EventQueryPouchContentGetType":
                    node = data.cases[1].v
                    continue
                else:
                    raise AssertionError(query)
                branch = data.cases.get(0 if yes else 1)
                node = branch.v if branch else None
            elif isinstance(data, SubFlowEvent):
                target = data.res_flowchart_name or flow
                if not (target == "Dm_SY_Get" and data.entry_point_name == "CheckHeart"):
                    self.run(data.entry_point_name, params, target)
                node = data.nxt.v
            else:
                raise AssertionError(type(data))
        return self

    def trade(self, name):
        return self.run(event_name(TRADE_CHECKS[name]["id"]))


class TradeRewardTests(unittest.TestCase):
    def graphs(self, roster, *, native_info=INFO):
        pouch, presenter, entries = ap_trade.build_trade_rewards(
            pouch_fixture(), presenter_fixture(), roster, native_info=native_info)
        self.assertEqual(set(entries), {TRADE_CHECKS[name]["id"] for name in roster})
        for raw in (pouch, presenter):
            chart = FlowEditor(raw, "Trade resulting graph").chart
            for point in chart.entry_points:
                if not point.name.startswith(ap_trade.PREFIX):
                    continue
                for node in reachable(point.main_event.v):
                    params = getattr(node.data, "params", None)
                    if params:
                        self.assertFalse(str(params.data.get("GameDataName", "")).startswith(CURSOR_PREFIX))
        return pouch, presenter

    def runner(self, roster):
        return TradeRun(*self.graphs(roster))

    def test_legacy_room_is_inert_and_new_metadata_is_strict(self):
        raw, presented = pouch_fixture(), presenter_fixture()
        self.assertEqual(ap_trade.build_trade_rewards(raw, presented, {}), (raw, presented, {}))
        self.assertEqual(ap_trade.prepare_trade_rewards("missing", "also-missing", {}, {}), {})
        with self.assertRaises(ValueError):
            ap_trade.trade_records({ANJU: reward()}, require_all=True)
        with self.assertRaises(ValueError):
            ap_trade.trade_records({ANJU: dict(reward("Bow"), item_id=123)})

    def test_missing_ammo_equipment_consumes_only_the_trade_input_without_item_scene(self):
        for item, bag in (("Bombs (20)", "Item_BombBag_Medium"),
                          ("Arrows (30)", "Item_Quiver_Large"),
                          ("Deku Seeds (30)", "Item_BulletBag_Small")):
            for owns_bag in (False, True):
                with self.subTest(item=item, owns_bag=owns_bag):
                    run = self.runner({COJIRO: reward(item)})
                    run.inventory["Item_CojiroCucco"] = 1
                    if owns_bag:
                        run.inventory[bag] = 1
                    run.trade(COJIRO)
                    self.assertEqual(run.inventory["Item_CojiroCucco"], 0)
                    metadata = ITEM_DATA[item]
                    actor = metadata.get('grant_actor', metadata['actor'])
                    actor = OWNERS.get(actor, actor)
                    expected = {'Bombs (20)': 20, 'Arrows (30)': 30, 'Deku Seeds (30)': 30}[item]
                    self.assertEqual(run.inventory[actor], expected if owns_bag else 0)
                    self.assertEqual(run.inventory["TBox_Rupee_Green"], 0)
                    self.assertTrue(run.values[TRADE_CHECKS[COJIRO]["flag_name"]])
                    self.assertEqual(len(run.saves), 1)
                    if not owns_bag:
                        self.assertFalse(any(cmd in {"FixtureNativeModel", "FixtureNativeSound", "EventTriggerSetForGetWindow",
                                                     "EventTriggerRequestOpenPickUpWindow"} for cmd, _ in run.trace))
                    before = run.inventory.copy()
                    run.trade(COJIRO)
                    self.assertEqual(run.inventory, before)

    def test_full_quantity_alias_consumes_input_even_without_a_bag(self):
        from ootrr_full.patching.ammo_quantities import quantity_actor
        name = 'Bombs (20)'
        recipes = dict(ITEM_DATA)
        recipes[name] = dict(ITEM_DATA[name], actor=quantity_actor(name))
        info = dict(INFO)
        info[quantity_actor(name)] = dict(INFO[ITEM_DATA[name]['actor']])
        pouch, presenter, _ = ap_trade.build_trade_rewards(
            pouch_fixture(), presenter_fixture(), {COJIRO: reward(name)}, native_info=info,
            item_data=recipes, reconcile=False)
        run = TradeRun(pouch, presenter)
        run.inventory['Item_CojiroCucco'] = 1
        run.trade(COJIRO)
        self.assertEqual(run.inventory['Item_CojiroCucco'], 0)
        self.assertEqual(run.inventory['Item_Bomb'], 0)
        self.assertTrue(run.values[TRADE_CHECKS[COJIRO]['flag_name']])
        self.assertEqual(len(run.saves), 1)
        self.assertFalse(any(command in {'FixtureNativeModel', 'FixtureNativeSound',
                                        'EventTriggerRequestOpenPickUpWindow'} for command, _ in run.trace))

    def test_own_reward_replaces_quest_grant_consumes_only_its_input_once(self):
        run = self.runner({COJIRO: reward("Bomb Bag")})
        run.inventory.update(Item_CojiroCucco=1, Item_Prescription=1, Item_PoacherSaw=1)
        run.trade(COJIRO)
        flag = TRADE_CHECKS[COJIRO]["flag_name"]
        self.assertEqual(run.inventory["Item_CojiroCucco"], 0)
        self.assertEqual(run.inventory["Item_Prescription"], 1)
        self.assertEqual(run.inventory["Item_PoacherSaw"], 1)
        self.assertEqual(run.inventory[ITEM_DATA["Bomb Bag"]["tiers"][0]], 1)
        self.assertEqual(run.inventory["Item_OddMushroom"], 0, "No vanilla quest item accompanies the reward")
        self.assertTrue(run.values[flag])
        self.assertEqual(len(run.saves), 1)
        before = (run.inventory.copy(), list(run.trace), list(run.saves))
        run.trade(COJIRO)
        self.assertEqual((run.inventory, run.trace, run.saves), before)

    def test_is_get_history_does_not_replace_owned_stock_or_talon_precondition(self):
        run = self.runner({CUCCO: reward("Rupees (5)")})
        run.historical.add("Item_PocketCucco")
        run.trade(CUCCO)
        self.assertFalse(run.trace)
        run.inventory["Item_PocketCucco"] = 1
        run.values[TALON_AWAKE] = False
        run.trade(CUCCO)
        self.assertFalse(run.trace)
        run.values[TALON_AWAKE] = True
        run.trade(CUCCO)
        self.assertEqual(run.inventory["Item_PocketCucco"], 0)
        self.assertTrue(run.values[TRADE_CHECKS[CUCCO]["flag_name"]])

    def test_foreign_reward_shows_ap_identity_without_giving_native_or_virtual_item(self):
        run = self.runner({COJIRO: reward("Foreign Sword", local=False)})
        run.inventory["Item_CojiroCucco"] = 1
        run.trade(COJIRO)
        adds = [params for action, params in run.trace if action == "EventTriggerAddOrRemovePouchContent"]
        self.assertEqual(adds, [dict(Actor="Item_CojiroCucco", Num=-1, IsEquipDIrect=False,
                                     IsSetMessageTargetActorName=False, IsGetEvent=False)])
        record = ap_trade.trade_records({COJIRO: reward("Foreign Sword", local=False)})[0]
        models = [params["ActorName"] for action, params in run.trace if action == "FixtureNativeModel"]
        self.assertEqual(models, [record["actor"]])
        self.assertTrue(run.values[record["flag_name"]])

    def test_full_bottle_defers_before_any_presentation_consumption_or_check(self):
        run = self.runner({COJIRO: reward("Buy Fish")})
        run.inventory["Item_CojiroCucco"] = 1
        run.empty_bottle = False
        run.trade(COJIRO)
        self.assertFalse(run.trace)
        self.assertEqual(run.inventory["Item_CojiroCucco"], 1)
        run.empty_bottle = True
        run.trade(COJIRO)
        self.assertEqual(run.inventory["Item_CojiroCucco"], 0)
        self.assertEqual(sum(value for key, value in run.inventory.items() if key.startswith("Bottle:")), 1)
        self.assertEqual(len(run.saves), 1)

    def test_effect_callback_rechecks_input_and_bottle_before_consuming(self):
        run = self.runner({COJIRO: reward("Buy Fish")})
        run.inventory["Item_CojiroCucco"] = 1
        run.empty_bottle = False
        run.run(event_name(TRADE_CHECKS[COJIRO]["id"]) + "_Pouch",
                {"ActorName": ITEM_DATA["Buy Fish"]["actor"]})
        self.assertEqual(run.inventory["Item_CojiroCucco"], 1)
        self.assertFalse(run.saves)
        run.empty_bottle = True
        run.inventory["Item_CojiroCucco"] = 0
        run.historical.add("Item_CojiroCucco")
        run.run(event_name(TRADE_CHECKS[COJIRO]["id"]) + "_Pouch",
                {"ActorName": ITEM_DATA["Buy Fish"]["actor"]})
        self.assertFalse(run.saves)
        self.assertFalse(any(action == "EventTriggerAddOrRemovePouchContent" for action, _ in run.trace))

    def test_existing_remote_receipt_is_unchanged_and_trade_does_not_ack_it(self):
        from ootrr_triforce.receipt_events import build_presented_receipts, event_name as receipt_name
        token = "a" * 64
        raw, shown, _ = build_presented_receipts(pouch_fixture(), presenter_fixture(), token,
                                                names=["Deku Stick (1)"])
        baseline = TradeRun(raw, shown).run(receipt_name(ITEM_IDS["Deku Stick (1)"]))
        pouch, presenter, _ = ap_trade.build_trade_rewards(raw, shown, {COJIRO: reward("Bomb Bag")}, native_info=INFO)
        updated = TradeRun(pouch, presenter).run(receipt_name(ITEM_IDS["Deku Stick (1)"]))
        self.assertEqual(updated.trace, baseline.trace)
        self.assertEqual(updated.inventory, baseline.inventory)
        updated.inventory["Item_CojiroCucco"] = 1
        start = len(updated.trace)
        updated.trade(COJIRO)
        self.assertFalse(any(str(params.get("GameDataName", "")).startswith(CURSOR_PREFIX)
                             for _, params in updated.trace[start:]))

    def test_no_save_at_any_interruption_point_can_commit_only_consumed_input(self):
        roster = {COJIRO: reward("Bow")}
        pouch, presenter = self.graphs(roster)
        complete = TradeRun(pouch, presenter)
        complete.inventory["Item_CojiroCucco"] = 1
        complete.trade(COJIRO)
        for stop in range(len(complete.trace) + 1):
            with self.subTest(stop=stop):
                run = TradeRun(pouch, presenter)
                run.inventory["Item_CojiroCucco"] = 1
                run.stop_after = stop
                try:
                    run.trade(COJIRO)
                except Interrupted:
                    pass
                for values, inventory in run.saves:
                    self.assertTrue(values[TRADE_CHECKS[COJIRO]["flag_name"]])
                    self.assertEqual(inventory["Item_CojiroCucco"], 0)
                    self.assertEqual(inventory["Weapon_Range_Bow"], 1)

    def test_every_catalogue_recipe_uses_its_native_effect_without_remote_ack(self):
        names = list(ITEM_DATA)
        locations = list(TRADE_CHECKS)
        for start in range(0, len(names), len(locations)):
            roster = dict(zip(locations, map(reward, names[start:start + len(locations)])))
            pouch, presenter = self.graphs(roster)
            for location, row in roster.items():
                with self.subTest(item=row["item"]):
                    run = TradeRun(pouch, presenter)
                    required = TRADE_CHECKS[location]["required_actor"]
                    if required:
                        run.inventory[required] = 1
                    run.trade(location)
                    self.assertTrue(run.values[TRADE_CHECKS[location]["flag_name"]])
                    self.assertEqual(len(run.saves), 1)
                    metadata = ITEM_DATA[row["item"]]
                    positive = [params for action, params in run.trace
                                if action == "EventTriggerAddOrRemovePouchContent" and params["Num"] > 0]
                    special = (metadata["actor"] in AMMO_BAGS or metadata["mode"] == "generic" or metadata["kind"] == "TCGSmallKey" or is_cure(metadata)
                               or (metadata.get("bottle_item") and metadata.get("pouch_special") == "NotPushToPouch"))
                    self.assertEqual(len(positive), 0 if special else 1)
                    self.assertFalse(any(str(params.get("GameDataName", "")).startswith(CURSOR_PREFIX)
                                         for _, params in run.trace))


if __name__ == "__main__":
    unittest.main()
