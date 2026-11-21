"""Run purchase hooks through authored shop paths and optionally a real staged flow."""
import copy
import hashlib
import io
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from evfl import EventFlow
from evfl.actor import Actor
from evfl.common import ActorIdentifier
from evfl.container import Container
from evfl.entry_point import EntryPoint
from evfl.event import ActionEvent, SubFlowEvent, SwitchEvent
from evfl.flowchart import Flowchart
from evfl.util import make_index
from oot_rando.patching.event_patch import _flow
from oot_rando.patching.event_info import reachable
from oot_rando.patching.progressive import FlowEditor, link
from ootrr_triforce.shop_events import ENTRY, FLOW_PATH, PREFIX, SELECTED, patch_shop_flow, prepare_shop_events


def records():
    return [{"actor": "Item_AP_test" + str(slot), "flag_name": "Archipelago.Shop.KF." + str(slot),
             "counters": [f"Shop_SoldNum.Kokiri.{age}.{slot}" for age in ("Child", "Short", "Adult")],
             "name": "KF Shop Item " + str(slot + 1), "price": 10 + 5 * slot} for slot in (0, 7)]


def native_shop():
    flow = EventFlow(); flow.name = "DisplayShop"
    flow.flowchart = Flowchart(); flow.flowchart.name = flow.name
    for name in ("Npc_EventStarter", "GameSystemActor"):
        actor = Actor(); actor.identifier = ActorIdentifier(name)
        actor.params = Container(); actor.params.data = {"EventMemberCreateMethod": 0}
        flow.flowchart.actors.append(actor)
    stream = io.BytesIO(); assert flow.write(stream)
    editor = FlowEditor(stream.getvalue(), "fixture DisplayShop")
    for index in range(548):
        if index in (6, 170):
            editor.switch("Event77" if index == 6 else "Event303", "PouchSystemActor",
                          "EventQueryCanAddToPorchByGameData", {"GameDataForActorName": SELECTED}, None, None)
        elif index in (156, 461):
            editor.action("Event281" if index == 156 else "Event543", "Npc_EventStarter",
                          "EventTriggerGetItemAtShop", {"IsGetEvent": False})
        else:
            editor.action("Fixture" + str(index), "GameSystemActor", "EventWait", {"Frames": 0})
    events = editor.chart.events
    for gate_index, money_index, pay_index, sold_index, grant_index, call_index, finish_index in (
            (6, 20, 21, 22, 156, 157, 158), (170, 25, 26, 27, 461, 462, 463)):
        money = editor.switch("Money" + str(gate_index), "Npc_EventStarter", "EventQueryHasRuppe", None, events[pay_index], events[finish_index])
        pay = editor.action("Pay" + str(gate_index), "Npc_EventStarter", "EventTriggerPayItemPriceAtShop", None)
        sold = editor.action("NativeSold" + str(gate_index), "Npc_EventStarter", "EventTriggerAddShopItemSoldNum", None)
        call = editor.subflow("ShelfGive" + str(gate_index), "", "OOTRR_ShelfGive", None)
        events[gate_index].data.cases = {0: make_index(money), 1: make_index(events[finish_index]), 2: make_index(events[finish_index])}
        link(events[pay_index], pay); link(pay, sold); link(sold, events[grant_index])
        link(events[grant_index], call); link(call, events[finish_index])
        entry = EntryPoint("FirstBuy" if gate_index == 6 else "RepeatBuy")
        entry.main_event = make_index(events[gate_index])
        entry._sub_flow_event_indices = [editor.chart.events.index(call)]
        editor.chart.entry_points.append(entry)
    shelf = editor.action("ShelfEffect", "GameDataActor", "EventTriggerSetGameDataBool",
                          {"GameDataName": "Fixture.ShelfGive", "Index": -1, "Value": True})
    entry = EntryPoint("OOTRR_ShelfGive"); entry.main_event = make_index(shelf)
    editor.chart.entry_points.append(entry)
    return editor.write("Synthetic DisplayShop")[0]


class Purchase:
    def __init__(self, raw, selected, money=100, capacity=2):
        self.chart = _flow(raw).flowchart
        self.entries = {entry.name: entry.main_event.v for entry in self.chart.entry_points}
        self.selected, self.money, self.capacity = selected, money, capacity
        self.values, self.trace = {}, []

    def run(self, entry):
        node = self.entries[entry]
        steps = 0
        while node is not None:
            steps += 1; assert steps < 2000, "Purchase hook loop"
            data = node.data
            params = data.params.data if getattr(data, "params", None) else {}
            if isinstance(data, SubFlowEvent):
                assert data.res_flowchart_name == "", "Unexpected external preload dependency"
                self.run(data.entry_point_name)
                node = data.nxt.v
            elif isinstance(data, SwitchEvent):
                command = data.actor_query.v.v
                self.trace.append((command, dict(params)))
                if command == "EventQueryIsGameDataString64":
                    self.assert_selected(params); answer = 0 if self.selected == params["Value"] else 1
                elif command == "EventQueryCanAddToPorchByGameData":
                    answer = self.capacity
                elif command == "EventQueryHasRuppe":
                    answer = 0 if self.money >= self.price else 1
                else:
                    raise AssertionError(command)
                reference = data.cases.get(answer)
                node = reference.v if reference else None
            elif isinstance(data, ActionEvent):
                command = data.actor_action.v.v
                self.trace.append((command, dict(params)))
                if command == "EventTriggerPayItemPriceAtShop":
                    self.money -= self.price
                elif command in ("EventTriggerSetGameDataBool", "EventTriggerSetGameDataInt"):
                    self.values[params["GameDataName"]] = params["Value"]
                node = data.nxt.v
            else:
                raise AssertionError(type(data).__name__)

    @property
    def price(self):
        return next((record["price"] for record in records() if record["actor"] == self.selected), 15)

    @staticmethod
    def assert_selected(params):
        assert params["GameDataName"] == SELECTED and params["Index"] == -1


class ShopEventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = native_shop()
        cls.after = patch_shop_flow(cls.before, records())

    def test_both_success_paths_mark_only_the_selected_purchase_after_native_grant(self):
        for entry in ("FirstBuy", "RepeatBuy"):
            for selected in records():
                run = Purchase(self.after, selected["actor"], capacity=2)
                run.run(entry)
                self.assertEqual(run.money, 100 - selected["price"])
                self.assertTrue(run.values["Fixture.ShelfGive"], "Existing OOTRR continuation disappeared")
                self.assertTrue(run.values[selected["flag_name"]])
                self.assertTrue(all(run.values[counter] == 1 for counter in selected["counters"]))
                self.assertEqual(sum(command == "EventTriggerGetItemAtShop" for command, _ in run.trace), 1)
                self.assertFalse(any(command == "EventQueryCanAddToPorchByGameData" for command, _ in run.trace))
                grant = next(i for i, (command, _) in enumerate(run.trace) if command == "EventTriggerGetItemAtShop")
                mark = next(i for i, (_, params) in enumerate(run.trace) if params.get("GameDataName") == selected["flag_name"])
                self.assertLess(grant, mark)
                self.assertFalse(any(key.startswith("Archipelago.ReceivedIndex.") for key in run.values))
                self.assertFalse(any(command == "EventTriggerAddOrRemovePouchContent" for command, _ in run.trace))
                other = next(record for record in records() if record is not selected and record["actor"] != selected["actor"])
                self.assertNotIn(other["flag_name"], run.values)

    def test_money_and_non_ap_capacity_checks_are_preserved(self):
        for entry in ("FirstBuy", "RepeatBuy"):
            poor = Purchase(self.after, records()[0]["actor"], money=0, capacity=2)
            poor.run(entry)
            self.assertEqual(poor.money, 0); self.assertFalse(poor.values)
            self.assertFalse(any(command == "EventTriggerGetItemAtShop" for command, _ in poor.trace))
            full = Purchase(self.after, "Item_BombBundle_Small", capacity=1)
            full.run(entry)
            self.assertEqual(full.money, 100); self.assertFalse(full.values)
            self.assertTrue(any(command == "EventQueryCanAddToPorchByGameData" for command, _ in full.trace))
            normal = Purchase(self.after, "Item_BombBundle_Small", capacity=0)
            normal.run(entry)
            self.assertEqual(normal.money, 85)
            self.assertEqual(normal.values, {"Fixture.ShelfGive": True})

    def test_preloads_original_parameters_and_duplicate_rejection(self):
        before, after = _flow(self.before).flowchart, _flow(self.after).flowchart
        originals = {event.name: event for event in before.events}
        for event in after.events:
            if event.name in originals:
                old = originals[event.name]
                self.assertEqual(type(event.data), type(old.data))
                self.assertEqual(getattr(event.data, "params", None).data if getattr(event.data, "params", None) else None,
                                 getattr(old.data, "params", None).data if getattr(old.data, "params", None) else None)
        for point in after.entry_points:
            for event in reachable(point.main_event.v):
                if event.name.startswith(PREFIX) and isinstance(event.data, SubFlowEvent):
                    self.assertIn(after.events.index(event), point._sub_flow_event_indices)
        with self.assertRaises(ValueError): patch_shop_flow(self.after, records())
        invalid = records(); invalid[1]["actor"] = invalid[0]["actor"]
        with self.assertRaises(ValueError): patch_shop_flow(self.before, invalid)
        self.assertEqual(patch_shop_flow(self.before, []), self.before)

    def test_unknown_native_layout_and_shared_sale_identity_are_rejected(self):
        for target in ("grant", "capacity"):
            flow = _flow(self.before)
            if target == "grant":
                flow.flowchart.events[461].data.params.data["IsGetEvent"] = True
            else:
                flow.flowchart.events[6].data.params.data["GameDataForActorName"] = "UnexpectedItem"
            stream = io.BytesIO(); self.assertTrue(flow.write(stream))
            with self.assertRaises(ValueError): patch_shop_flow(stream.getvalue(), records())
        invalid = records(); invalid[1]["counters"][0] = invalid[0]["counters"][0]
        with self.assertRaises(ValueError): patch_shop_flow(self.before, invalid)
        invalid = records(); invalid[0]["flag_name"] = "Archipelago.Shop.KF.8"
        with self.assertRaises(ValueError): patch_shop_flow(self.before, invalid)

    def test_all_eight_real_catalog_flags_can_be_hooked(self):
        from ootrr_triforce.catalog import SHOP_CHECKS
        native_records = [dict(record, name=name, actor="Item_AP_catalog" + str(index), price=15)
                          for index, (name, record) in enumerate(SHOP_CHECKS.items())]
        patched = _flow(patch_shop_flow(self.before, native_records)).flowchart
        flags = {event.data.params.data.get("GameDataName") for event in patched.events
                 if event.name.startswith(PREFIX + "Collected")}
        self.assertEqual(flags, {record["flag_name"] for record in SHOP_CHECKS.values()})

    def test_real_resources_only_write_flow_and_rest_in_temporary_stage(self):
        game = Path(os.environ.get("OOTRR_ROMFS", ""))
        if not (game / "Pack/ZsDic.pack.zs").is_file(): self.skipTest("Set OOTRR_ROMFS for the read-only resource check")
        before = {path: hashlib.sha256((game/path).read_bytes()).digest() for path in (FLOW_PATH, "Pack/ZsDic.pack.zs")}
        effective = Path(os.environ.get("OOTRR_MOD_ROMFS", ""))
        from ootrr_triforce.medallions import REST
        originals = {effective / relative: hashlib.sha256((effective / relative).read_bytes()).digest()
                     for relative in (FLOW_PATH, REST) if (effective / relative).is_file()}
        argv0 = sys.argv[0]
        try:
            sys.argv[0] = str(ROOT / "dist/Client-OOT-Remake.pyz")
            with tempfile.TemporaryDirectory() as temporary:
                for path in originals:
                    target = Path(temporary) / path.relative_to(effective)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
                result = prepare_shop_events(game, Path(temporary), records())
                self.assertEqual(result["purchases"], 2)
                written = {path.relative_to(temporary).as_posix() for path in Path(temporary).rglob("*") if path.is_file()}
                self.assertEqual(written, {FLOW_PATH, REST})
        finally:
            sys.argv[0] = argv0
        self.assertEqual(before, {path: hashlib.sha256((game/path).read_bytes()).digest() for path in before})
        self.assertEqual(originals, {path: hashlib.sha256(path.read_bytes()).digest() for path in originals})


if __name__ == "__main__":
    unittest.main()
