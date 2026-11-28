"""Dungeon pickup text follows the AP reward, including guest-performer gets."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))

from evfl.event import SubFlowEvent
from oot_rando.patching.progressive import FlowEditor
from ootrr_triforce.ap_skulls import (NATIVE_SCRATCH, PICKUP_FLOWS, SCRATCH,
                                    patch_pickup_presentation, patch_skull_flow, skull_records)
from ootrr_triforce.catalog import ITEM_DATA
from ootrr_triforce.dungeon_messages import message_id
from ootrr_triforce.receipt_events import DUNGEONS
from test_skull_events import Pickup, ground_flow, native_flow, roster


def talks(run):
    return [values for command, values in run.trace if command == "EventTalk"]


def assert_credit(test, run, record):
    metadata = ITEM_DATA[record["local_item"]]
    prefix = "DungeonInfo." + DUNGEONS[metadata["dungeon"]] + "."
    expected = ({prefix + "SmallKeyNum": 1, prefix + "SmallKeyTotalNum": 1,
                 prefix + "IsGetSmallKeyOnce": True}
                if metadata["kind"] in {"SmallKey", "HideoutSmallKey"} else
                {prefix + {"BossKey": "IsGetBossKey", "GanonBossKey": "IsGetBossKey",
                           "Map": "IsGetMap", "Compass": "IsGetCompass"}[metadata["kind"]]: True})
    test.assertEqual({key: value for key, value in run.values.items() if key.startswith("DungeonInfo.")}, expected)
    test.assertTrue(run.values[record["flag_name"]])
    test.assertFalse(any(command == "EventTriggerAddOrRemovePouchContent" for command, _values in run.trace))
    test.assertFalse(any(str(values.get("GameDataName", "")).startswith("Archipelago.ReceivedIndex.")
                         for _command, values in run.trace))


class DungeonPickupMessageTests(unittest.TestCase):
    def test_every_dungeon_pickup_shows_one_specific_message_and_credits_only_its_dungeon(self):
        names = [name for name, metadata in ITEM_DATA.items() if message_id(metadata)]
        self.assertTrue(any(name.startswith("Small Key") for name in names))
        self.assertTrue(any(name.startswith("Boss Key") for name in names))
        for start in range(0, len(names), 8):
            records = skull_records(roster(names[start:start + 8]))
            patched = patch_skull_flow(native_flow(), records)
            for record in records:
                for alias in ("actor", "pickup"):
                    with self.subTest(item=record["local_item"], alias=alias):
                        run = Pickup(patched)
                        run.run(record[alias])
                        self.assertEqual([values["MessageId"] for values in talks(run)],
                                         [message_id(ITEM_DATA[record["local_item"]])])
                        self.assertEqual(sum(command == "call:OpenGetWindow" for command, _values in run.trace), 0)
                        assert_credit(self, run, record)
                        before = len(talks(run))
                        run.run(record[alias])
                        self.assertEqual(len(talks(run)), before, "completed pickups do not repeat their dialogue")
                        assert_credit(self, run, record)

    def test_guest_pickups_keep_one_window_before_one_effect_and_native_cleanup(self):
        names = ("Small Key (Forest Temple)", "Small Key (Fire Temple)",
                 "Boss Key (Forest Temple)", "Boss Key (Water Temple)",
                 "Map (Spirit Temple)", "Compass (Fire Temple)")
        records = skull_records(roster(names))
        pouch, effects = patch_skull_flow(native_flow(), records, return_entries=True)
        for flow_name in PICKUP_FLOWS:
            patched = patch_pickup_presentation(ground_flow(flow_name), records, effects, flow_name)
            entry = "PouchAddItem" if flow_name == "Dm_SY_Get" else flow_name
            for record in records:
                for alias in ("actor", "pickup"):
                    with self.subTest(flow=flow_name, item=record["local_item"], alias=alias):
                        run = Pickup({"GetPouchContent": pouch, flow_name: patched})
                        run.call(entry, {"ActorName": record[alias]}, flow_name)
                        self.assertEqual([values["MessageId"] for values in talks(run)],
                                         [message_id(ITEM_DATA[record["local_item"]])])
                        self.assertFalse(any(command == "call:OpenGetWindow" for command, _values in run.trace))
                        self.assertFalse(any(command == "EventTriggerAddOwnToPouch" for command, _values in run.trace))
                        assert_credit(self, run, record)
                        displayed = next(index for index, (command, _values) in enumerate(run.trace)
                                         if command == "EventTalk")
                        credit = next(index for index, (_command, values) in enumerate(run.trace)
                                      if str(values.get("GameDataName", "")).startswith("DungeonInfo."))
                        committed = next(index for index, (_command, values) in enumerate(run.trace)
                                         if values.get("GameDataName") == record["flag_name"])
                        self.assertLess(displayed, credit)
                        self.assertLess(credit, committed)
                        self.assertEqual([values["ActorName"] for command, values in run.trace
                                          if command == "EventTriggerRequestOpenPickUpWindow"],
                                         [record["native_actor"]])

    def test_quiet_effect_callbacks_never_open_a_dungeon_message(self):
        records = skull_records(roster(("Small Key (Forest Temple)", "Boss Key (Fire Temple)")))
        pouch, effects = patch_skull_flow(native_flow(), records, return_entries=True)
        for record in records:
            with self.subTest(item=record["local_item"]):
                run = Pickup(pouch)
                run.call(effects[record["actor"]], {})
                self.assertEqual(talks(run), [])
                self.assertFalse(any(command == "call:OpenGetWindow" for command, _values in run.trace))
                assert_credit(self, run, record)

    def test_foreign_and_ordinary_gets_keep_their_native_message_even_after_a_key(self):
        local = skull_records(roster(("Small Key (Forest Temple)",)))[0]
        # Same foreign item name cannot accidentally select a local key recipe.
        # Distinct physical locations retain distinct actor and persistence IDs.
        foreign_source = next(name for name in roster(("Bow", "Bow")) if name != local["name"])
        foreign = skull_records({foreign_source: dict(item="Boss Key (Fire Temple)", player="Ami", local=False)})[0]
        records = [local, foreign]
        pouch, effects = patch_skull_flow(native_flow(), records, return_entries=True)
        for flow_name in PICKUP_FLOWS:
            patched = patch_pickup_presentation(ground_flow(flow_name), records, effects, flow_name)
            entry = "PouchAddItem" if flow_name == "Dm_SY_Get" else flow_name
            for actor in (foreign["actor"], foreign["pickup"], "Item_Token_Gold"):
                with self.subTest(flow=flow_name, actor=actor):
                    run = Pickup({"GetPouchContent": pouch, flow_name: patched})
                    run.values[SCRATCH] = local["actor"]
                    run.values[NATIVE_SCRATCH] = local["native_actor"]
                    run.call(entry, {"ActorName": actor}, flow_name)
                    self.assertEqual(talks(run), [])
                    self.assertEqual(sum(command == "call:OpenGetWindow" for command, _values in run.trace), 1)
                    self.assertFalse(any(str(values.get("GameDataName", "")).startswith("DungeonInfo.")
                                         for _command, values in run.trace))

    def test_missing_native_window_is_rejected_before_an_incomplete_patch_is_returned(self):
        records = skull_records(roster(("Small Key (Forest Temple)",)))
        _pouch, effects = patch_skull_flow(native_flow(), records, return_entries=True)
        for flow_name in PICKUP_FLOWS:
            editor = FlowEditor(ground_flow(flow_name), flow_name)
            for event in editor.chart.events:
                if isinstance(event.data, SubFlowEvent) and event.data.entry_point_name == "OpenGetWindow":
                    event.data.entry_point_name = "UnknownWindow"
            changed = editor.write("unknown native pickup window")[0]
            with self.assertRaises(ValueError):
                patch_pickup_presentation(changed, records, effects, flow_name)


if __name__ == "__main__":
    unittest.main()
