"""Native trade stock replay preserves concurrent items and consumes only spent ones."""
from collections import Counter
import io
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from evfl import EventFlow
from evfl.actor import Actor
from evfl.common import ActorIdentifier, Argument
from evfl.entry_point import EntryPoint
from evfl.event import ActionEvent, SwitchEvent
from evfl.flowchart import Flowchart
from evfl.util import make_index
from oot_rando.patching.progressive import FlowEditor, link
from ootrr_triforce.catalog import TRADE_CHECKS
from ootrr_triforce.trade_state import append_reconcile, patch_native_grant


def native():
    flow = EventFlow()
    flow.name = "GetPouchContent"
    flow.flowchart = Flowchart()
    flow.flowchart.name = flow.name
    for name in ("PouchSystemActor", "GameDataActor", "GameSystemActor"):
        actor = Actor()
        actor.identifier = ActorIdentifier(name)
        flow.flowchart.actors.append(actor)
    stream = io.BytesIO()
    assert flow.write(stream)
    editor = FlowEditor(stream.getvalue(), "Native trade stock fixture")
    save = editor.action("Save", "GameSystemActor", "EventTriggerRequestAutoSave", None)
    grant = editor.action("Event0", "PouchSystemActor", "EventTriggerAddOrRemovePouchContent",
                          {"Actor": Argument("ActorName"), "Num": 1})
    link(grant, save)
    entry = EntryPoint("GetPouchContent")
    entry.main_event = make_index(grant)
    editor.chart.entry_points.append(entry)
    return editor.write("Native fixture")[0]


class NativeRun:
    def __init__(self, raw):
        self.chart = FlowEditor(raw, "Trade stock simulation").chart
        self.stock, self.flags = Counter(), {}
        self.pending, self.saves = [], []

    def run(self, actor=None, entry="GetPouchContent"):
        node = next(point.main_event.v for point in self.chart.entry_points if point.name == entry)
        steps = 0
        while node is not None:
            steps += 1
            assert steps < 500
            data = node.data
            params = {key: actor if isinstance(value, Argument) else value
                      for key, value in (data.params.data if data.params else {}).items()}
            if isinstance(data, ActionEvent):
                action = data.actor_action.v.v
                if action == "EventTriggerAddOrRemovePouchContent":
                    self.pending.append(("stock", params["Actor"], params["Num"]))
                elif action == "EventTriggerSetGameDataBool":
                    self.pending.append(("bool", params["GameDataName"], params["Value"]))
                elif action == "EventWait":
                    self.assert_wait(params)
                    for kind, key, value in self.pending:
                        if kind == "stock":
                            self.stock[key] += value
                            assert self.stock[key] >= 0, "A spent token must never be removed twice"
                        else:
                            self.flags[key] = value
                    self.pending.clear()
                elif action == "EventTriggerRequestAutoSave":
                    assert not self.pending, "Inventory and check writes must settle before saving"
                    self.saves.append((self.stock.copy(), dict(self.flags)))
                else:
                    raise AssertionError(action)
                node = data.nxt.v
            elif isinstance(data, SwitchEvent):
                query = data.actor_query.v.v
                if query == "EventQueryIsExistInPouch":
                    yes = self.stock[params["Actor"]] >= params["Num"]
                elif query == "EventQueryIsGameDataBool":
                    yes = bool(self.flags.get(params["GameDataName"]))
                else:
                    raise AssertionError(query)
                node = data.cases[0 if yes else 1].v
            else:
                raise AssertionError(type(data))
        return self

    @staticmethod
    def assert_wait(params):
        assert params == {"Frames": 1, "IsWaitEnd": True}


class TradeStockTests(unittest.TestCase):
    def test_distinct_native_stocks_coexist_and_given_item_is_not_consumption(self):
        run = NativeRun(patch_native_grant(native()))
        run.flags[TRADE_CHECKS["Kak Anju as Adult"]["flag_name"]] = True
        for actor in ("Item_PocketCucco", "Item_CojiroCucco", "Item_Prescription", "Item_PoacherSaw"):
            run.run(actor)
        self.assertTrue(all(run.stock[actor] == 1 for actor in
                            ("Item_PocketCucco", "Item_CojiroCucco", "Item_Prescription", "Item_PoacherSaw")))
        self.assertEqual(len(run.saves), 4)

    def test_later_source_restoration_discards_only_a_previously_spent_token(self):
        run = NativeRun(patch_native_grant(native()))
        run.flags[TRADE_CHECKS["LW Trade Cojiro"]["flag_name"]] = True
        run.stock["Item_Prescription"] = 1
        run.run("Item_CojiroCucco").run("Item_DekuStick")
        self.assertEqual(run.stock["Item_CojiroCucco"], 0)
        self.assertEqual(run.stock["Item_Prescription"], 1)
        self.assertEqual(run.stock["Item_DekuStick"], 1)
        self.assertEqual(run.saves[0][0]["Item_CojiroCucco"], 0)

    def test_queued_completion_removes_owned_token_before_commit_without_repeat(self):
        editor = FlowEditor(native(), "Queued completion")
        save = next(event for event in editor.chart.events if event.name == "Save")
        record = TRADE_CHECKS["ZD Trade Prescription"]
        check = editor.action("Complete", "GameDataActor", "EventTriggerSetGameDataBool",
                              {"GameDataName": record["flag_name"], "Index": -1, "Value": True})
        link(check, append_reconcile(editor, "Settle", save))
        point = EntryPoint("Complete")
        point.main_event = make_index(check)
        editor.chart.entry_points.append(point)
        run = NativeRun(editor.write("Queued completion")[0])
        run.stock["Item_Prescription"] = run.stock["Item_CojiroCucco"] = 1
        run.run(entry="Complete").run(entry="Complete")
        self.assertEqual(run.stock["Item_Prescription"], 0)
        self.assertEqual(run.stock["Item_CojiroCucco"], 1)
        self.assertTrue(all(state[1][record["flag_name"]] for state in run.saves))


if __name__ == "__main__":
    unittest.main()
