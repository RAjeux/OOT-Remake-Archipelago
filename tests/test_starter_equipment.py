"""First AP weapons receive their native equipment before queued ownership."""
import copy
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from oot_rando.patching.progressive import FlowEditor, link
from oot_rando.patching.event_info import reachable
from ootrr_triforce import ap_skulls, network_rewards, receipt_events, restoration
from ootrr_triforce.catalog import ITEM_IDS, LOCATION_IDS
from ootrr_triforce.native_presentations import STARTER_KITS
from test_network_rewards import QueuedSourceRun, names, settings
from test_restoration import reward
from test_skull_events import native_flow


def staged_fixture():
    """The native OOTRRBag post-grant ownership check, including both kits."""
    editor = FlowEditor(native_flow(), "Staged equipment fixture")
    grant = next(event for event in editor.chart.events if event.name == "NativeGive")
    then = grant.data.nxt.v
    for number, (actor, (bags, ammo, amount)) in enumerate(reversed(list(STARTER_KITS.items()))):
        stem = "OOTRRBag_" + str(number)
        refill = editor.action(stem + "Ammo", "PouchSystemActor", "EventTriggerAddOrRemovePouchContent",
                               {"Actor": ammo, "Num": amount})
        link(refill, then)
        small = editor.action(stem + "Small", "PouchSystemActor", "EventTriggerAddOrRemovePouchContent",
                              {"Actor": bags[0], "Num": 1})
        link(small, refill)
        root = small
        for index, bag in enumerate(bags):
            root = editor.switch(stem + "Bag" + str(index), "GameDataActor", "EventQueryCheckIsGet",
                                 {"ActorName": bag}, then, root)
        owner = receipt_events.OWNERS.get(actor, actor)
        then = editor.switch(stem + "Weapon", "GameDataActor", "EventQueryCheckIsGet",
                             {"ActorName": owner}, root, then)
    link(grant, then)
    return editor.write("Staged equipment fixture")[0]


def physical(raw, items, *, foreign=False):
    locations = names("container", len(items))
    roster = {name: reward(item, local=not foreign) for name, item in zip(locations, items)}
    records = network_rewards.source_records(roster, settings(roster))
    return ap_skulls.patch_skull_flow(raw, records), records, roster


def pouch_actions(trace):
    return [(params["Actor"], params["Num"]) for action, params in trace
            if action == "EventTriggerAddOrRemovePouchContent"]


class StarterEquipmentTests(unittest.TestCase):
    def test_terminal_native_give_wait_remains_the_exact_cleanup(self):
        from evfl.actor import Actor
        from evfl.common import ActorIdentifier
        editor = FlowEditor(staged_fixture(), "Terminal native companion fixture")
        actor = Actor()
        actor.identifier = ActorIdentifier("EventSystemActor")
        editor.chart.actors.append(actor)
        wait = editor.action("OOTRRGiveBag999", "EventSystemActor", "EventWait",
                             {"Frames": 1, "IsWaitEnd": True})
        add = editor.action("OOTRRGiveBag998", "PouchSystemActor", "EventTriggerAddOrRemovePouchContent",
                            {"Actor": "Item_Quiver_Small", "Num": 1})
        link(add, wait)
        self.assertIs(receipt_events.native_starter_exit(add), wait)
        self.assertIs(receipt_events.native_starter_exit(wait), wait)
        grant = next(event for event in editor.chart.events if event.name == "NativeGive")
        link(grant, add)
        receipt_events._silent_grant(editor, None)
        entry = next(point for point in editor.chart.entry_points if point.name == receipt_events.SILENT_ENTRY)
        commands = [(receipt_events._action(event), event.data.params.data if event.data.params else None)
                    for event in reachable(entry.main_event.v)]
        self.assertIn(("EventWait", {"Frames": 1, "IsWaitEnd": True}), commands)
        self.assertFalse(any(params and params.get("Actor") == "Item_Quiver_Small" for _, params in commands))
        for invalid in ({"Frames": 2, "IsWaitEnd": True}, {"Frames": 1, "IsWaitEnd": False}):
            wait.data.params.data = invalid
            with self.assertRaises(ValueError):
                receipt_events.native_starter_exit(add)

    def test_kits_match_native_start_items_table(self):
        self.assertEqual(STARTER_KITS, {
            "Item_Range_Bow": (("Item_Quiver_Small", "Item_Quiver_Medium", "Item_Quiver_Large"), "Item_Arrow_Normal", 30),
            "Item_Range_SlingShot": (("Item_BulletBag_Small", "Item_BulletBag_Medium", "Item_BulletBag_Large"), "Item_DekuSeed", 30)})

    def test_first_weapon_small_bag_and_thirty_ammo_are_one_queued_transaction(self):
        for family, actor in (("Bow", "Item_Range_Bow"), ("Slingshot", "Item_Range_SlingShot")):
            with self.subTest(family=family):
                raw, records, _ = physical(staged_fixture(), [family, family, family])
                run = QueuedSourceRun(raw)
                bags, ammo, amount = STARTER_KITS[actor]
                run.collect(records[0])
                self.assertEqual(pouch_actions(run.trace), [(bags[0], 1), (ammo, amount), (actor, 1)])
                self.assertFalse(run.saves)
                self.assertFalse(run.inventory)
                run.flush()
                self.assertEqual(run.inventory[receipt_events.OWNERS[actor]], 1)
                self.assertEqual(run.inventory[bags[0]], 1)
                self.assertEqual(run.inventory[ammo], 30)
                self.assertTrue(run.saves[-1][0][records[0]["flag_name"]])
                self.assertEqual(run.saves[-1][1][ammo], 30)
                for record in records[1:]:
                    run.collect(record).flush()
                self.assertEqual(pouch_actions(run.trace),
                                 [(bags[0], 1), (ammo, amount), (actor, 1), (bags[1], 1), (bags[2], 1)])
                for record in records:
                    run.collect(record, "pickup").flush()
                self.assertEqual(run.inventory[ammo], 30)
                self.assertEqual(run.inventory[bags[0]], 1)

    def test_larger_bag_existing_weapon_foreign_and_ammo_never_receive_a_free_small_kit(self):
        for family, actor, refill in (("Bow", "Item_Range_Bow", "Arrows (30)"),
                                      ("Slingshot", "Item_Range_SlingShot", "Deku Seeds (30)")):
            bags, ammo, _ = STARTER_KITS[actor]
            for owned in (receipt_events.OWNERS[actor], bags[1], bags[2]):
                with self.subTest(family=family, owned=owned):
                    raw, records, _ = physical(staged_fixture(), [family])
                    run = QueuedSourceRun(raw)
                    run.inventory[owned] = 1
                    run.collect(records[0]).flush()
                    self.assertEqual(run.inventory[bags[0]], 0)
                    self.assertEqual(run.inventory[ammo], 0)
            raw, records, _ = physical(staged_fixture(), [family], foreign=True)
            run = QueuedSourceRun(raw)
            run.inventory[receipt_events.OWNERS[actor]] = 1
            run.collect(records[0]).flush()
            self.assertEqual(pouch_actions(run.trace), [(records[0]["actor"], 1)])
            raw, records, _ = physical(staged_fixture(), [refill])
            run = QueuedSourceRun(raw)
            run.inventory[receipt_events.OWNERS[actor]] = 1
            run.collect(records[0]).flush()
            self.assertFalse(pouch_actions(run.trace))

    def test_restoration_and_legacy_receipts_get_the_same_first_equipment_without_extra_ack(self):
        for family, actor in (("Bow", "Item_Range_Bow"), ("Slingshot", "Item_Range_SlingShot")):
            bags, ammo, amount = STARTER_KITS[actor]
            source, records, roster = physical(staged_fixture(), [family])
            recovered, _ = restoration.build_restoration_flow(source, roster, settings(roster))
            run = QueuedSourceRun(recovered).run(restoration.event_name(LOCATION_IDS[records[0]["name"]]))
            run.flush()
            self.assertEqual(pouch_actions(run.trace), [(bags[0], 1), (ammo, amount), (actor, 1)])
            self.assertTrue(run.values[records[0]["flag_name"]])
            legacy, _ = receipt_events.build_receipt_flow(staged_fixture(), "b" * 64, [family])
            run = QueuedSourceRun(legacy).run(receipt_events.event_name(ITEM_IDS[family]))
            run.flush()
            self.assertEqual(pouch_actions(run.trace), [(bags[0], 1), (ammo, amount), (actor, 1)])
            self.assertEqual(run.values[receipt_events.CURSOR_PREFIX + "b" * 64], 1)

    def test_only_ap_copy_bypasses_the_native_global_repair_hook(self):
        original = staged_fixture()
        editor = FlowEditor(original, "Original native fallback")
        before = {event.name: (copy.deepcopy(event.data.params.data) if event.data.params else None,
                              event.data.nxt.v.name if hasattr(event.data, "nxt") and event.data.nxt.v else None)
                  for event in editor.chart.events}
        receipt_events._silent_grant(editor, None)
        raw, checked = editor.write("AP silent equipment copy")
        for event in checked.flowchart.events:
            if event.name in before:
                self.assertEqual((event.data.params.data if event.data.params else None,
                                  event.data.nxt.v.name if hasattr(event.data, "nxt") and event.data.nxt.v else None), before[event.name])
        point = next(point for point in checked.flowchart.entry_points if point.name == receipt_events.SILENT_ENTRY)
        self.assertFalse(any("OOTRRBag" in event.name for event in reachable(point.main_event.v)))
        self.assertTrue(any(event.name.startswith("OOTRRBag") for event in checked.flowchart.events))


@unittest.skipUnless(os.environ.get("OOTRR_ROMFS") and os.environ.get("OOTRR_STARTER_MOD"),
                     "requires a private native OOTRR 0.8.1 staged GetPouchContent")
class NativeStarterEquipmentTests(unittest.TestCase):
    def test_public_native_exit_recognizes_both_real_weapon_companion_prefixes(self):
        from ootrr_triforce import app_runtime
        from ootrr_triforce.mod_codec import Codec
        game, mod = Path(os.environ["OOTRR_ROMFS"]), Path(os.environ["OOTRR_STARTER_MOD"])
        prefixes = {"OOTRRBag": 0, "OOTRRGiveBag": 0}
        with patch.object(app_runtime, "_resource_override", Path(os.environ["OOTRR_CODEC_RESOURCES"])):
            codec = Codec((game / "Pack/ZsDic.pack.zs").read_bytes())
            for path in (mod / "Event/EventFlow").glob("*.bfevfl.zs"):
                raw = codec.decode(path.read_bytes())
                if not any(prefix.encode() in raw for prefix in prefixes):
                    continue
                editor = FlowEditor(raw, "Native companion hooks")
                for event in editor.chart.events:
                    for prefix in prefixes:
                        if event.name.startswith(prefix):
                            after = receipt_events.native_starter_exit(event)
                            self.assertTrue(after is None or not after.name.startswith(tuple(prefixes))
                                            or (receipt_events._action(after) == "EventWait"
                                                and after.data.nxt.v is None
                                                and dict(after.data.params.data) == {"Frames": 1, "IsWaitEnd": True}))
                            prefixes[prefix] += 1
                # The helper discovers the cleanup; it changes no native graph.
                editor.write("Native companion hooks unchanged")
        self.assertGreater(prefixes["OOTRRBag"], 0)
        self.assertGreater(prefixes["OOTRRGiveBag"], 0)

    def test_real_staged_pouch_has_exact_equipment_without_deferred_ownership_bug(self):
        from ootrr_triforce import app_runtime
        from ootrr_triforce.mod_codec import Codec
        game, mod = Path(os.environ["OOTRR_ROMFS"]), Path(os.environ["OOTRR_STARTER_MOD"])
        with patch.object(app_runtime, "_resource_override", Path(os.environ["OOTRR_CODEC_RESOURCES"])):
            codec = Codec((game / "Pack/ZsDic.pack.zs").read_bytes())
            source = codec.decode((mod / ap_skulls.FLOW_PATH).read_bytes())
        self.assertTrue(any(event.name.startswith("OOTRRBag") for event in FlowEditor(source, "Staged native").chart.events))
        for family, actor in (("Bow", "Item_Range_Bow"), ("Slingshot", "Item_Range_SlingShot")):
            with self.subTest(family=family):
                raw, records, _ = physical(source, [family, family])
                raw, effects = ap_skulls.patch_skull_flow(source, records, return_entries=True)
                run = QueuedSourceRun(raw)
                for record in records:
                    run.run(effects[record["actor"]], {"ActorName": record["actor"]}).flush()
                bags, ammo, amount = STARTER_KITS[actor]
                self.assertEqual(pouch_actions(run.trace), [(bags[0], 1), (ammo, amount), (actor, 1), (bags[1], 1)])
                self.assertTrue(all(run.values[record["flag_name"]] for record in records))
                legacy, _ = receipt_events.build_receipt_flow(source, "c" * 64, [family])
                run = QueuedSourceRun(legacy).run(receipt_events.event_name(ITEM_IDS[family]))
                run.flush()
                self.assertEqual(pouch_actions(run.trace), [(bags[0], 1), (ammo, amount), (actor, 1)])
                self.assertEqual(run.values[receipt_events.CURSOR_PREFIX + "c" * 64], 1)


if __name__ == "__main__":
    unittest.main()
