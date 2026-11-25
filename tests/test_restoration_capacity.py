"""Large rooms retain native FIFO cleanup without duplicating its event body."""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from evfl.event import SubFlowEvent
from oot_rando.patching.progressive import FlowEditor
from ootrr_triforce import ap_skulls, network_rewards, restoration
from ootrr_triforce.catalog import ITEM_DATA, ITEM_IDS, LOCATION_IDS, TRADE_CHECKS
from ootrr_triforce.network_catalog import check_flags
from test_network_rewards import QueuedSourceRun, names, settings
from test_restoration import pouch, reward


class SharedRestorationCleanupTests(unittest.TestCase):
    def test_shared_trade_body_keeps_both_fifo_barriers_and_each_own_save_result(self):
        location = names("container", 1)[0]
        trade = "LW Trade Cojiro"
        roster = {trade: reward(local=False), location: reward("Cojiro")}
        raw, entries = restoration.build_restoration_flow(pouch(), roster, settings(roster))
        chart = FlowEditor(raw, "Shared restore cleanup").chart
        self.assertEqual(sum(point.name == restoration.TRADE_RECONCILE for point in chart.entry_points), 1)
        calls = [event for event in chart.events if isinstance(event.data, SubFlowEvent)
                 and event.data.entry_point_name == restoration.TRADE_RECONCILE]
        self.assertEqual(len(calls), len(roster))
        for event in calls:
            self.assertEqual(event.data.nxt.v.name, event.name.removesuffix("_TradeSettle") + "_Save")
        shared = [event for event in chart.events if event.name.startswith(restoration.PREFIX + "SharedTradeState")]
        waits = [event for event in shared if getattr(getattr(event.data, "actor_action", None), "v", None)
                 and event.data.actor_action.v.v == "EventWait"]
        self.assertEqual([dict(event.data.params.data) for event in waits],
                         [{"Frames": 1, "IsWaitEnd": True}] * 2)
        self.assertEqual(sum(event.name.startswith(restoration.PREFIX + "SharedTradeState_Remove") for event in shared),
                         sum(row["required_actor"] is not None for row in TRADE_CHECKS.values()))
        run = QueuedSourceRun(raw)
        run.inventory["Item_CojiroCucco"] = run.inventory["Item_Prescription"] = 1
        for name in (trade, location):
            before = len(run.trace)
            run.run(entries[LOCATION_IDS[name]]).flush()
            trace = run.trace[before:]
            wait_at = [index for index, (action, _) in enumerate(trace) if action == "EventWait"]
            remove_at = next(index for index, (action, params) in enumerate(trace)
                             if action == "EventTriggerAddOrRemovePouchContent" and params.get("Num") == -1)
            save_at = next(index for index, (action, _) in enumerate(trace) if action == "EventTriggerRequestAutoSave")
            self.assertEqual(len(wait_at), 2)
            self.assertLess(wait_at[0], remove_at)
            self.assertLess(remove_at, wait_at[1])
            self.assertLess(wait_at[1], save_at)
            self.assertEqual(run.values[restoration.RESULT], LOCATION_IDS[name])
            self.assertEqual(run.inventory["Item_CojiroCucco"], 0)
            self.assertEqual(run.inventory["Item_Prescription"], 1)
            self.assertEqual(run.saves[-1][1]["Item_CojiroCucco"], 0)
        self.assertFalse(any(key.startswith("Archipelago.ReceivedIndex.") for key in run.values))


@unittest.skipUnless(os.environ.get("OOTRR_ROMFS") and os.environ.get("OOTRR_CAPACITY_PROOF"),
                     "requires a private MAX native generation proof")
class NativeMaximumCapacityTests(unittest.TestCase):
    def test_all_own_normal_pool_callbacks_restoration_and_all_remote_receipts_fit_u16_with_margin(self):
        from ootrr_triforce import app_runtime
        from ootrr_triforce.mod_codec import Codec
        proof = Path(os.environ["OOTRR_CAPACITY_PROOF"])
        data = json.loads((proof / "BuildTest.apootrr").read_bytes())
        roster = json.loads((proof / "roster.json").read_bytes())
        # The pool comes from the actual native generation, including its many
        # ordinary collectibles. Do not manufacture thousands of progressives.
        self.assertEqual(len(roster), 1212)
        self.assertTrue(all(row["local"] for row in roster.values()))
        self.assertEqual({name: row["item"] for name, row in roster.items()}, data["moved"])
        game = Path(os.environ["OOTRR_ROMFS"])
        with patch.object(app_runtime, "_resource_override", Path(os.environ["OOTRR_CODEC_RESOURCES"])):
            codec = Codec((game / "Pack/ZsDic.pack.zs").read_bytes())
            base = codec.decode((proof / "room/mods/Archipelago/romfs" / restoration.FLOW_PATH).read_bytes())
        base_chart = FlowEditor(base, "Native MAX plus remote receipts").chart
        remote = [entry for entry in base_chart.entry_points if entry.name.startswith("OOTRR_APReceive_")
                  and entry.name.removeprefix("OOTRR_APReceive_").isdigit()]
        self.assertEqual(len(remote), len(ITEM_DATA))
        records = network_rewards.source_records(roster, data)
        callbacks = ap_skulls.patch_skull_flow(base, records)
        complete, locations = restoration.build_restoration_flow(callbacks, roster, data)
        chart = FlowEditor(complete, "All-own MAX native callbacks").chart
        self.assertEqual(len(locations), 1212)
        self.assertLess(len(chart.events), 65535 - 10000)
        self.assertLess(len(chart.entry_points), 65535 - 10000)
        flags = {flag for name in data["checks"] for flag in check_flags(name, network=True)}
        self.assertLessEqual(len(data["checks"]), 2000)
        self.assertLessEqual(len(flags), 4096)
        # The final room preparation also adds mastered trade/sword adapters;
        # this ten-thousand-event margin exceeds their combined native budget.
        result = dict(checks=len(locations), flags=len(flags), source_callbacks=len(records),
                      remote_receipts=len(remote), events=len(chart.events), entries=len(chart.entry_points),
                      event_limit=65535, spare_events=65535 - len(chart.events),
                      complete_room=False, scope="base native + all remote receipts + all-own source callbacks + restoration")
        (ROOT / "build/restoration-capacity-audit.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    unittest.main()
