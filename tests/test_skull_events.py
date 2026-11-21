"""Gold Skulltula callbacks grant and commit only the collected AP pickup."""
import copy
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from evfl import EventFlow
from evfl.actor import Actor
from evfl.common import ActorIdentifier, Argument
from evfl.entry_point import EntryPoint
from evfl.event import ActionEvent, SubFlowEvent, SwitchEvent
from evfl.flowchart import Flowchart
from evfl.util import make_index
from oot_rando.patching.event_patch import _flow
from oot_rando.patching.progressive import FlowEditor, link
from ootrr_triforce.ap_skulls import PREFIX, SCRATCH, NATIVE_SCRATCH, patch_skull_flow, patch_pickup_presentation, skull_records
from ootrr_triforce.catalog import AP_SKULL_CHECKS, ITEM_DATA, ITEM_IDS
from ootrr_triforce.native_presentations import is_cure
from ootrr_triforce.receipt_events import DUNGEONS, OWNERS


def native_flow():
    flow = EventFlow()
    flow.name = "GetPouchContent"
    flow.flowchart = Flowchart()
    flow.flowchart.name = flow.name
    for name in ("GameDataActor", "PouchSystemActor", "GameSystemActor"):
        actor = Actor()
        actor.identifier = ActorIdentifier(name)
        flow.flowchart.actors.append(actor)
    stream = io.BytesIO()
    assert flow.write(stream)
    editor = FlowEditor(stream.getvalue(), "native pickup fixture")
    def entry(name, root):
        point = EntryPoint(name)
        point.main_event = make_index(root)
        editor.chart.entry_points.append(point)
    save = editor.action("NativeSave", "GameSystemActor", "EventTriggerRequestAutoSave", None)
    save_if = editor.switch("NativeSaveIf", "PouchSystemActor", "EventQueryIsAutoSavePouchContent",
                            {"ActorName": Argument("ActorName")}, save, None)
    close = editor.subflow("NativeClose", "", "CloseRupeeUIIfNeed", None)
    link(close, save_if)
    give = editor.action("NativeGive", "PouchSystemActor", "EventTriggerAddOrRemovePouchContent",
                         {"Actor": Argument("ActorName"), "Num": 1, "IsEquipDIrect": False,
                          "IsSetMessageTargetActorName": True, "IsGetEvent": Argument("IsGetInEvent")})
    link(give, close)
    counter = editor.subflow("NativeCounter", "", "OpenRupeeUIIfNeed", None)
    link(counter, give)
    window = editor.subflow("NativeWindow", "", "OpenGetWindow", None)
    link(window, counter)
    target = editor.action("NativeTarget", "PouchSystemActor", "EventTriggerSetForGetWindow",
                           {"Actor": Argument("ActorName")})
    link(target, window)
    entry("GetPouchContent", target)
    for name in ("OpenGetWindow", "OpenRupeeUIIfNeed", "CloseRupeeUIIfNeed"):
        entry(name, None)
    return editor.write("native pickup fixture")[0]


def ground_flow(name):
    """The authored message/window/grant boundaries of the two real charts."""
    flow = EventFlow()
    flow.name = name
    flow.flowchart = Flowchart()
    flow.flowchart.name = name
    for actor_name in ("PouchContentGuestPerformer", "UISystemActor"):
        actor = Actor()
        actor.identifier = ActorIdentifier(actor_name)
        flow.flowchart.actors.append(actor)
    stream = io.BytesIO()
    assert flow.write(stream)
    editor = FlowEditor(stream.getvalue(), name)
    grant_name, message_name = ("Event35", "Event38") if name == "Dm_SY_Get" else ("Event0", "Event2")
    notify = editor.action("NativeNotify", "UISystemActor", "EventTriggerRequestOpenPickUpWindow",
                           {"ActorName": Argument("ActorName")})
    grant = editor.action(grant_name, "PouchContentGuestPerformer", "EventTriggerAddOwnToPouch", None)
    link(grant, notify)
    window = editor.subflow("NativeWindow", "GetPouchContent", "OpenGetWindow", None)
    link(window, grant)
    message = editor.action(message_name, "PouchContentGuestPerformer", "EventTriggerSetOwnNameToMessage", None)
    link(message, window)
    entry = EntryPoint("PouchAddItem" if name == "Dm_SY_Get" else name)
    entry.main_event = make_index(message)
    editor.chart.entry_points.append(entry)
    return editor.write(name)[0]


class Pickup:
    def __init__(self, raw, *, ignored_entries=()):
        raw = raw if isinstance(raw, dict) else {"GetPouchContent": raw}
        self.charts = {name: _flow(content).flowchart for name, content in raw.items()}
        self.chart = self.charts["GetPouchContent"]
        self.entries = {entry.name: entry.main_event.v for entry in self.chart.entry_points}
        self.values, self.trace, self.held = {}, [], set()
        self.ignored_entries = set(ignored_entries)
        self.windows = []
        self.message_target = None

    def run(self, actor):
        self.call("GetPouchContent", {"ActorName": actor, "IsGetInEvent": False,
                                      "IsShowNumDisplay": True, "IsTreasureBox": False})

    def call(self, entry, args, flow_name="GetPouchContent"):
        if (flow_name, entry) in self.ignored_entries:
            return
        chart = self.charts[flow_name]
        event = next(point.main_event.v for point in chart.entry_points if point.name == entry)
        steps = 0
        def params(data):
            values = data.params.data if getattr(data, "params", None) else {}
            return {key: args.get(str(value), str(value)) if isinstance(value, Argument) else value
                    for key, value in values.items()}
        while event is not None:
            steps += 1
            assert steps < 1000
            data = event.data
            values = params(data)
            if isinstance(data, ActionEvent):
                command = data.actor_action.v.v
                self.trace.append((command, values))
                key = values.get("GameDataName")
                if command in {"EventTriggerSetGameDataBool", "EventTriggerSetGameDataString64", "EventTriggerSetGameDataInt"}:
                    self.values[key] = values["Value"]
                elif command == "EventTriggerAddOrSubGameDataInt":
                    self.values[key] = self.values.get(key, 0) + values["Value"]
                elif command == "EventTriggerSetForGetWindow":
                    self.message_target = values["Actor"]
                elif command == "EventTriggerSetOwnNameToMessage":
                    self.message_target = args["ActorName"]
                elif command == "EventTriggerAddOrRemovePouchContent":
                    self.held.add(OWNERS.get(values["Actor"], values["Actor"]))
                event = data.nxt.v
            elif isinstance(data, SwitchEvent):
                command = data.actor_query.v.v
                if command == "EventQueryIsGameDataString64":
                    yes = self.values.get(values["GameDataName"]) == values["Value"]
                elif command == "EventQueryIsGameDataBool":
                    yes = bool(self.values.get(values["GameDataName"]))
                elif command == "EventQueryIsExistInPouch":
                    yes = values["Actor"] in self.held
                elif command == "EventQueryCheckIsGet":
                    yes = values["ActorName"] in self.held
                elif command == "EventQueryIsAutoSavePouchContent":
                    yes = True
                elif command == "EventQueryCheckTagOnPouchActor":
                    # Ordinary AP identities have no bottle/fire/heart tag.
                    target = data.cases[2]
                    event = target.v
                    continue
                else:
                    raise AssertionError(command)
                target = data.cases.get(0 if yes else 1)
                event = target.v if target else None
            elif isinstance(data, SubFlowEvent):
                self.trace.append(("call:" + data.entry_point_name, values))
                target_flow = data.res_flowchart_name or flow_name
                if data.entry_point_name == "OpenGetWindow":
                    self.windows.append((self.message_target, dict(self.values)))
                self.call(data.entry_point_name, {**args, **values}, target_flow)
                event = data.nxt.v
            else:
                raise AssertionError(type(data))


def roster(names, foreign=False):
    return {location: dict(item=name, player="Ami" if foreign else "Link", item_id=ITEM_IDS[name],
                           local=not foreign)
            for location, name in zip(AP_SKULL_CHECKS, names)}


class SkullEventTests(unittest.TestCase):
    def setUp(self):
        self.native = native_flow()

    def test_foreign_pickup_commits_after_native_window_and_never_gives_token_gold(self):
        records = skull_records(roster(["Bow"], foreign=True))
        raw = patch_skull_flow(self.native, records)
        run = Pickup(raw)
        self.assertFalse(run.values)
        run.run(records[0]["actor"])
        self.assertTrue(run.values[records[0]["flag_name"]])
        grant = [args["Actor"] for command, args in run.trace if command == "EventTriggerAddOrRemovePouchContent"]
        self.assertEqual(grant, [records[0]["actor"]])
        self.assertNotIn("Item_Token_Gold", grant)
        self.assertEqual(sum(command == "call:OpenGetWindow" for command, _ in run.trace), 1)
        before = list(run.trace)
        run.run(records[0]["pickup"])
        self.assertEqual(sum(command == "EventTriggerAddOrRemovePouchContent" for command, _ in run.trace),
                         sum(command == "EventTriggerAddOrRemovePouchContent" for command, _ in before))
        self.assertFalse(any(str(args.get("GameDataName", "")).startswith("Archipelago.ReceivedIndex.")
                             for _, args in run.trace))

    def test_local_catalogue_recipes_grant_once_and_preserve_unrelated_native_pickups(self):
        eligible = [name for name, row in ITEM_DATA.items()
                    if not (row.get("bottle_item") and row.get("pouch_special") == "NotPushToPouch")]
        for start in range(0, len(eligible), 8):
            records = skull_records(roster(eligible[start:start + 8]))
            raw = patch_skull_flow(self.native, records)
            for record in records:
                with self.subTest(item=record["local_item"]):
                    run = Pickup(raw)
                    run.run(record["actor"])
                    self.assertTrue(run.values[record["flag_name"]])
                    metadata = ITEM_DATA[record["local_item"]]
                    pouch = [args["Actor"] for command, args in run.trace
                             if command == "EventTriggerAddOrRemovePouchContent"]
                    if metadata["mode"] == "generic" or metadata["kind"] == "TCGSmallKey" or is_cure(metadata):
                        self.assertFalse(pouch)
                    else:
                        self.assertEqual(pouch, [metadata["actor"]])
                        effects = [args for command, args in run.trace
                                   if command == "EventTriggerAddOrRemovePouchContent"]
                        self.assertTrue(all(args["IsGetEvent"] is False for args in effects))
                        calls = [args for command, args in run.trace if command.startswith("call:")
                                 and command.endswith("TemporaryGrant")]
                        self.assertTrue(calls)
                        self.assertTrue(all(call["IsGetInEvent"] is False and call["IsTreasureBox"] is False
                                            and call["IsShowNumDisplay"] is True for call in calls))
                    self.assertNotIn(record["actor"], pouch)
                    self.assertEqual(sum(command == "call:OpenGetWindow" for command, _ in run.trace), 1)
                    committed = list(run.trace)
                    run.run(record["actor"])
                    self.assertEqual(sum(command == "EventTriggerAddOrRemovePouchContent" for command, _ in run.trace),
                                     sum(command == "EventTriggerAddOrRemovePouchContent" for command, _ in committed))
                    self.assertFalse(any(str(args.get("GameDataName", "")).startswith("Archipelago.ReceivedIndex.")
                                         for _, args in run.trace))
            ordinary = Pickup(raw)
            ordinary.run("Item_Token_Gold")
            self.assertEqual([args["Actor"] for command, args in ordinary.trace
                              if command == "EventTriggerAddOrRemovePouchContent"], ["Item_Token_Gold"])
            self.assertFalse(any(ordinary.values.get(row["flag_name"]) for row in records))

    def test_targeted_dungeon_recipe_and_unknown_metadata_fail_closed(self):
        records = skull_records(roster(["Small Key (Forest Temple)"]))
        run = Pickup(patch_skull_flow(self.native, records))
        run.run(records[0]["actor"])
        self.assertEqual(run.values["DungeonInfo." + DUNGEONS["Forest Temple"] + ".SmallKeyNum"], 1)
        self.assertEqual(run.values["DungeonInfo." + DUNGEONS["Forest Temple"] + ".SmallKeyTotalNum"], 1)
        invalid = copy.deepcopy(records)
        invalid[0]["hash"] = "1"
        with self.assertRaises(ValueError):
            patch_skull_flow(self.native, invalid)
        with self.assertRaises(ValueError):
            patch_skull_flow(patch_skull_flow(self.native, records), records)
        refill = next(name for name, metadata in ITEM_DATA.items()
                      if metadata.get("bottle_item") and metadata.get("pouch_special") == "NotPushToPouch")
        with self.assertRaises(ValueError):
            skull_records(roster([refill]))
        self.assertEqual(patch_skull_flow(self.native, []), self.native)

    def test_all_77_identities_complete_only_their_own_pickup(self):
        records = skull_records(roster(["Bow"] * len(AP_SKULL_CHECKS), foreign=True))
        self.assertEqual(len(records), 77)
        raw = patch_skull_flow(self.native, records)
        for index, record in enumerate(records):
            with self.subTest(location=record["name"]):
                run = Pickup(raw)
                run.run(record["pickup"] if index % 2 else record["actor"])
                self.assertEqual({row["flag_name"] for row in records if run.values.get(row["flag_name"])},
                                 {record["flag_name"]})
                grants = [args["Actor"] for command, args in run.trace
                          if command == "EventTriggerAddOrRemovePouchContent"]
                self.assertEqual(grants, [record["actor"]])
                # An unrelated real token is a normal inventory gain; it must
                # never complete another Skulltula location through its count.
                run.run("Item_Token_Gold")
                self.assertEqual({row["flag_name"] for row in records if run.values.get(row["flag_name"])},
                                 {record["flag_name"]})

    def test_progressive_pickup_window_and_grant_use_the_next_native_tier(self):
        for name in ("Bow", "Progressive Hookshot", "Magic Meter"):
            metadata = ITEM_DATA[name]
            record = skull_records(roster([name]))[0]
            raw = patch_skull_flow(self.native, [record])
            for held in range(len(metadata["tiers"]) + 1):
                with self.subTest(item=name, owned_tiers=held):
                    run = Pickup(raw)
                    run.held.update(OWNERS.get(actor, actor) for actor in metadata["tiers"][:held])
                    run.run(record["actor"])
                    expected = metadata["tiers"][min(held, len(metadata["tiers"]) - 1)]
                    self.assertEqual([args["Actor"] for command, args in run.trace
                                      if command == "EventTriggerSetForGetWindow"], [expected])
                    self.assertEqual([args["Actor"] for command, args in run.trace
                                      if command == "EventTriggerAddOrRemovePouchContent"], [expected])
                    self.assertTrue(run.values[record["flag_name"]])

    def test_real_ground_boundaries_preview_then_grant_and_native_notifications(self):
        records = skull_records({name: reward for name, reward in zip(sorted(AP_SKULL_CHECKS), [
            dict(item="Bow", player="Link", local=True),
            dict(item="Rupees (5)", player="Link", local=True),
            dict(item="Small Key (Forest Temple)", player="Link", local=True),
            dict(item="Deku Stick (1)", player="Ami", local=False)])})
        pouch, effects = patch_skull_flow(self.native, records, return_entries=True)
        for name in ("Dm_SY_Get", "Dm_SY_Get_WithoutPlayer"):
            native = ground_flow(name)
            patched = patch_pickup_presentation(native, records, effects, name)
            for record in records:
                for alias in ("actor", "pickup"):
                    with self.subTest(flow=name, item=record.get("local_item"), alias=alias):
                        run = Pickup({"GetPouchContent": pouch, name: patched})
                        run.call("PouchAddItem" if name == "Dm_SY_Get" else name,
                                 {"ActorName": record[alias]}, name)
                        self.assertTrue(run.values[record["flag_name"]])
                        self.assertEqual(len(run.windows), 1)
                        target, snapshot = run.windows[0]
                        self.assertFalse(snapshot.get(record["flag_name"]))
                        notices = [args["ActorName"] for cmd, args in run.trace
                                   if cmd == "EventTriggerRequestOpenPickUpWindow"]
                        guest_grants = [cmd for cmd, args in run.trace if cmd == "EventTriggerAddOwnToPouch"]
                        if "local_item" in record:
                            expected = ITEM_DATA[record["local_item"]].get("tiers", [record["native_actor"]])[0]
                            self.assertEqual(target, expected)
                            self.assertEqual(notices, [expected])
                            self.assertFalse(guest_grants)
                            self.assertEqual(run.values[NATIVE_SCRATCH], expected)
                        else:
                            self.assertEqual(target, record[alias])
                            self.assertEqual(notices, [record[alias]])
                            self.assertEqual(len(guest_grants), 1)
                        before = len([cmd for cmd, _ in run.trace
                                      if cmd in {"EventTriggerAddOwnToPouch", "EventTriggerAddOrRemovePouchContent"}])
                        run.call("PouchAddItem" if name == "Dm_SY_Get" else name,
                                 {"ActorName": record[alias]}, name)
                        self.assertEqual(len([cmd for cmd, _ in run.trace
                                              if cmd in {"EventTriggerAddOwnToPouch", "EventTriggerAddOrRemovePouchContent"}]), before)
            ordinary = Pickup({"GetPouchContent": pouch, name: patched})
            # A previous local preview must not affect the next ordinary pickup.
            ordinary.values[NATIVE_SCRATCH] = "Item_Range_Bow"
            ordinary.call("PouchAddItem" if name == "Dm_SY_Get" else name, {"ActorName": "Item_Token_Gold"}, name)
            self.assertEqual(ordinary.windows[0][0], "Item_Token_Gold")
            self.assertEqual([args["ActorName"] for cmd, args in ordinary.trace
                              if cmd == "EventTriggerRequestOpenPickUpWindow"], ["Item_Token_Gold"])
            self.assertEqual(sum(cmd == "EventTriggerAddOwnToPouch" for cmd, _ in ordinary.trace), 1)
            self.assertFalse(any(ordinary.values.get(row["flag_name"]) for row in records))

    @unittest.skipUnless(os.environ.get("OOTRR_ROMFS"), "requires a private native RomFS")
    def test_authoritative_native_entries_reach_the_pickup_callbacks(self):
        from ootrr_triforce.mod_codec import Codec
        root = Path(os.environ["OOTRR_ROMFS"])
        with patch.object(sys, "argv", [str(ROOT / "dist/Client-OOT-Remake.pyz")]):
            codec = Codec((root / "Pack/ZsDic.pack.zs").read_bytes())
        def raw(name):
            return codec.decode((root / f"Event/EventFlow/{name}.bfevfl.zs").read_bytes())
        ignored = {("GetPouchContent", entry) for entry in ("OpenGetWindow", "OpenRupeeUIIfNeed",
                    "CloseRupeeUIIfNeed", "ActionGuide")}
        ignored.add(("Dm_SY_Get", "MaskNaviReaction"))
        ignored.add(("ActionGuide", "ActionGuide"))
        eligible = [item for item, metadata in ITEM_DATA.items()
                    if not (metadata.get("bottle_item") and metadata.get("pouch_special") == "NotPushToPouch")]
        for start in range(0, len(eligible), 76):
            rewards = roster(eligible[start:start + 76])
            unused = next(location for location in AP_SKULL_CHECKS if location not in rewards)
            rewards[unused] = dict(item="Deku Stick (1)", player="Ami", local=False)
            records = skull_records(rewards)
            pouch, effects = patch_skull_flow(raw("GetPouchContent"), records, return_entries=True)
            for name in ("Dm_SY_Get", "Dm_SY_Get_WithoutPlayer"):
                native = raw(name)
                patched = patch_pickup_presentation(native, records, effects, name)
                charts = {"GetPouchContent": pouch, name: patched}
                before = _flow(native).flowchart
                after = {event.name: event for event in _flow(patched).flowchart.events}
                for event in before.events:
                    if isinstance(event.data, ActionEvent):
                        changed = after[event.name].data
                        self.assertEqual(changed.actor_action.v.v, event.data.actor_action.v.v)
                        self.assertEqual(str(changed.actor.v.identifier), str(event.data.actor.v.identifier))
                        self.assertEqual(repr(changed.params), repr(event.data.params))
                for record in [*records, {"pickup": "Item_DekuStick"}]:
                    with self.subTest(flow=name, item=record.get("local_item", record["pickup"])):
                        run = Pickup(charts, ignored_entries=ignored)
                        run.call("PouchAddItem" if name == "Dm_SY_Get" else name,
                                 {"ActorName": record["pickup"]}, name)
                        if "local_item" in record:
                            expected = ITEM_DATA[record["local_item"]].get("tiers", [record["native_actor"]])[0]
                        else:
                            expected = record["pickup"]
                        self.assertEqual(run.windows[0][0], expected)
                        if "flag_name" in record:
                            self.assertFalse(run.windows[0][1].get(record["flag_name"]))
                            self.assertTrue(run.values[record["flag_name"]])
                        else:
                            self.assertFalse(any(run.values.get(row["flag_name"]) for row in records))
                        self.assertEqual([args["ActorName"] for cmd, args in run.trace
                                          if cmd == "EventTriggerRequestOpenPickUpWindow"], [expected])
                        self.assertEqual(sum(cmd == "EventTriggerAddOwnToPouch" for cmd, _ in run.trace),
                                         int("local_item" not in record))


if __name__ == "__main__":
    unittest.main()
