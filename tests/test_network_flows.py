"""Native reward copies retain entry-scoped NPC arguments and presentations."""
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
from evfl.container import Container
from evfl.entry_point import EntryPoint
from evfl.flowchart import Flowchart
from evfl.util import make_index
from oot_rando.patching.progressive import FlowEditor, link
from ootrr_triforce.native_presentations import copy_entry


def editor(name, *, scopes=()):
    flow = EventFlow()
    flow.name = name
    flow.flowchart = Flowchart()
    flow.flowchart.name = name
    for entry_name, argument in scopes:
        point = EntryPoint(entry_name)
        flow.flowchart.entry_points.append(point)
        actor = Actor()
        actor.identifier = ActorIdentifier("Npc_EventStarter", entry_name + "(" + argument + ")")
        actor.argument_name = argument
        actor.argument_entry_point = make_index(point)
        actor.concurrent_clips = 1
        actor.params = Container()
        actor.params.data = {"NativeActorParameter": True, "NativeTurnSpeed": 2.5}
        flow.flowchart.actors.append(actor)
    stream = io.BytesIO()
    assert flow.write(stream)
    return FlowEditor(stream.getvalue(), name)


def argument_fixture():
    source = editor("NpcCommon", scopes=(("Give", "NpcActor"), ("Handover", "HelperActor")))
    actors = {actor.argument_name: actor for actor in source.chart.actors}
    helper = source.action("NativeHandover", str(actors["HelperActor"].identifier), "EventNativeHandover",
                           {"Speaker": copy.deepcopy(actors["HelperActor"].identifier), "Wait": True})
    source.chart.entry_points[1].main_event = make_index(helper)
    handover = source.subflow("CallHandover", "", "Handover",
                             {"HelperActor": copy.deepcopy(actors["NpcActor"].identifier),
                              "ActorName": Argument("ActorName")})
    give = source.action("NativeGive", str(actors["NpcActor"].identifier), "EventNativeGive",
                         {"Speaker": copy.deepcopy(actors["NpcActor"].identifier),
                          "ExternalNpc": ActorIdentifier("Npc_Hylia_External"),
                          "ActorName": Argument("ActorName")})
    link(give, handover)
    source.chart.entry_points[0].main_event = make_index(give)
    return FlowEditor(source.write("Native scoped fixture")[0], "Scoped source")


def scoped_snapshot(chart):
    return [(str(actor.identifier), actor.argument_name,
             actor.argument_entry_point.v.name if actor.argument_entry_point.v else None,
             copy.deepcopy(actor.params.data) if actor.params else None)
            for actor in chart.actors]


class NativeArgumentCopyTests(unittest.TestCase):
    def test_opt_in_rebinds_scopes_and_forwarded_actor_identifiers(self):
        source, target = argument_fixture(), editor("Destination")
        original_actors = scoped_snapshot(source.chart)
        entry = copy_entry(source.chart, target, "Give", "AP_7311000", local_closure=True, bind_arguments=True)
        self.assertEqual(entry, "AP_7311000_Give")
        raw, checked = target.write("Scoped native copy")
        actors = {actor.argument_name: actor for actor in checked.flowchart.actors}
        for argument, scope in (("NpcActor", "Give"), ("HelperActor", "Handover")):
            actor = actors[argument]
            self.assertEqual(actor.identifier.sub_name, "AP_7311000_" + scope + "(" + argument + ")")
            self.assertEqual(actor.argument_entry_point.v.name, "AP_7311000_" + scope)
            self.assertEqual(actor.params.data, {"NativeActorParameter": True, "NativeTurnSpeed": 2.5})
        events = {event.name: event for event in checked.flowchart.events}
        give = events["AP_7311000_NativeGive"].data
        self.assertEqual(give.params.data["Speaker"], actors["NpcActor"].identifier)
        self.assertEqual(give.params.data["ExternalNpc"], ActorIdentifier("Npc_Hylia_External"))
        self.assertIsInstance(give.params.data["ActorName"], Argument)
        call = events["AP_7311000_CallHandover"].data
        self.assertEqual(call.entry_point_name, "AP_7311000_Handover")
        self.assertEqual(call.params.data["HelperActor"], actors["NpcActor"].identifier)
        self.assertEqual(events["AP_7311000_NativeHandover"].data.params.data["Speaker"], actors["HelperActor"].identifier)
        self.assertEqual(scoped_snapshot(source.chart), original_actors)
        self.assertEqual(FlowEditor(raw, "Roundtrip").write("Roundtrip")[0], raw)

    def test_default_stays_strict_and_other_actor_scopes_are_not_silently_dropped(self):
        with self.assertRaisesRegex(ValueError, "another entry"):
            copy_entry(argument_fixture().chart, editor("Destination"), "Give", "AP_Default", local_closure=True)
        source = argument_fixture()
        source.chart.actors[0].argument_entry_point = make_index(source.chart.entry_points[1])
        with self.assertRaisesRegex(ValueError, "another entry"):
            copy_entry(source.chart, editor("Destination"), "Give", "AP_Bad", local_closure=True, bind_arguments=True)

    def test_distinct_source_copies_never_share_argument_actors(self):
        source, target = argument_fixture(), editor("Destination")
        for prefix in ("AP_1", "AP_2"):
            copy_entry(source.chart, target, "Give", prefix, local_closure=True, bind_arguments=True)
        _, checked = target.write("Independent native argument scopes")
        actors = [actor for actor in checked.flowchart.actors if actor.argument_entry_point.v is not None]
        self.assertEqual(len(actors), 4)
        self.assertEqual(len({str(actor.identifier) for actor in actors}), 4)
        self.assertEqual({actor.argument_entry_point.v.name for actor in actors},
                         {"AP_1_Give", "AP_1_Handover", "AP_2_Give", "AP_2_Handover"})

    def test_shared_native_entry_alias_retains_the_argument_owners_real_scope(self):
        source, target = argument_fixture(), editor("Destination")
        # Native presentations share nodes between entry points. A selected
        # alias can use an actor owned by an entry it never explicitly calls.
        source.chart.entry_points[0].main_event = source.chart.entry_points[1].main_event
        copy_entry(source.chart, target, "Give", "AP_Alias", local_closure=True, bind_arguments=True)
        _, checked = target.write("Shared native argument entry")
        points = {point.name: point for point in checked.flowchart.entry_points}
        self.assertEqual(set(points), {"AP_Alias_Give", "AP_Alias_Handover"})
        self.assertIs(points["AP_Alias_Give"].main_event.v, points["AP_Alias_Handover"].main_event.v)
        owner = points["AP_Alias_Give"].main_event.v.data.actor.v
        self.assertEqual(owner.argument_entry_point.v.name, "AP_Alias_Handover")
        self.assertEqual(owner.identifier.sub_name, "AP_Alias_Handover(HelperActor)")


class ReplacedRewardTests(unittest.TestCase):
    """The native prize's companion effects never survive an AP replacement."""
    def source(self, name):
        source = editor(name)
        for name in ("EventSystemActor", "SystemTextNPC"):
            actor = Actor()
            actor.identifier = ActorIdentifier(name)
            source.chart.actors.append(actor)
        return source

    def bind(self, source, first, generated_item):
        from ootrr_triforce.catalog import LOCATION_IDS
        from ootrr_triforce.network_catalog import SOURCES, flag_name
        from ootrr_triforce.network_flows import patch_reward
        name = next(name for name, metadata in SOURCES.items() if metadata["kind"] == "flow")
        self.assertIn(name, LOCATION_IDS)
        entry = EntryPoint("Gift")
        entry.main_event = make_index(first)
        source.chart.entry_points.append(entry)
        record = {"name": name, "actor": "AP_TestForeignReward", "flag_name": flag_name(name),
                  "generated_item": generated_item}
        patch_reward(source, first, "ActorName", record, "AP_Effect", lambda _: self.fail("Unexpected presenter"), 0)
        checked = FlowEditor(source.write("Replaced native reward")[0], "Replaced native reward")
        from oot_rando.patching.event_info import reachable
        return list(reachable(next(p for p in checked.chart.entry_points if p.name == "Gift").main_event.v))

    def test_ocarina_and_song_original_compensation_is_removed_but_cleanup_remains(self):
        from ootrr_triforce.catalog import ITEM_DATA
        from evfl.event import SubFlowEvent
        for item, actor, equip in (("Ocarina", "Item_Ocarina_Time", True),
                                   ("Bolero of Fire", ITEM_DATA["Bolero of Fire"]["actor"], False)):
            with self.subTest(item=item):
                source = self.source("Npc_Gift")
                cleanup = source.action("NativeCleanup", "EventSystemActor", "EventWait", {"Frames": 60})
                after = cleanup
                if equip:
                    after = source.action("OOTRRHeldAdd12", "GameDataActor", "EventTriggerSetGameDataString64",
                                          {"GameDataName": "PlayerStatus.EquipOcarina", "Index": -1, "Value": actor})
                    link(after, cleanup)
                add = source.action("OOTRRHeldAdd13", "PouchSystemActor", "EventTriggerAddOrRemovePouchContent",
                                    {"Actor": actor, "Num": 1, "IsGetEvent": False})
                link(add, after)
                give = source.subflow("OriginalGift", "GetPouchContent", "DisplayGetByActorName",
                                      {"ActorName": "Obj_OriginalPickup"})
                link(give, add)
                events = self.bind(source, give, item)
                self.assertIn("NativeCleanup", [node.name for node in events])
                self.assertFalse(any(node.name.startswith("OOTRRHeldAdd") for node in events))
                grants = [node.data for node in events if isinstance(node.data, SubFlowEvent)]
                self.assertEqual(len(grants), 1)
                self.assertEqual(grants[0].entry_point_name, "GetPouchContentByActorName")
                self.assertEqual(grants[0].params.data["ActorName"], "AP_TestForeignReward")

    def test_unexpected_held_compensation_fails_instead_of_discarding_quest_state(self):
        from ootrr_triforce.network_flows import _native_continuation
        source = editor("Npc_Gift")
        for actor, amount in (("Item_BombBag_Large", 1), ("Item_Ocarina_Time", 2)):
            with self.subTest(actor=actor, amount=amount):
                event = source.action("OOTRRHeldAdd" + actor + str(amount), "PouchSystemActor",
                                      "EventTriggerAddOrRemovePouchContent", {"Actor": actor, "Num": amount})
                with self.assertRaisesRegex(ValueError, "Unknown native held-item compensation"):
                    _native_continuation(event, "Ocarina")

    def test_native_map_credit_is_removed_with_its_message_but_not_boss_cleanup(self):
        source = self.source("BossReward")
        cleanup = source.action("NativeCleanup", "EventSystemActor", "EventWait", {"Frames": 60})
        message = source.action("Key13", "SystemTextNPC", "EventTalk",
                                {"MessageId": "EventFlowMsg/Dm_SY_Get:OOTRR_Map_ForestTemple"})
        credit = source.action("Key12", "GameDataActor", "EventTriggerSetGameDataBool",
                               {"GameDataName": "DungeonInfo.ForestTemple.IsGetMap", "Index": -1, "Value": True})
        give = source.subflow("OriginalGift", "GetPouchContent", "DisplayGetByActorName",
                              {"ActorName": "Item_Dungeon_Map"})
        link(give, credit)
        link(credit, message)
        link(message, cleanup)
        events = self.bind(source, give, "Map (Forest Temple)")
        self.assertIn("NativeCleanup", [node.name for node in events])
        self.assertFalse(any(node.name in {"Key12", "Key13"} for node in events))

    def test_unrelated_native_quest_flag_is_preserved(self):
        from ootrr_triforce.network_flows import _native_continuation
        source = editor("Quest")
        flag = source.action("CompleteQuest", "GameDataActor", "EventTriggerSetGameDataBool",
                             {"GameDataName": "Native.QuestComplete", "Index": -1, "Value": True})
        self.assertIs(_native_continuation(flag, "Ocarina"), flag)


@unittest.skipUnless(os.environ.get("OOTRR_ROMFS"), "requires native v1.1.1 event flows")
class NativeArgumentResourceTests(unittest.TestCase):
    def test_native_handover_and_item_presentations_keep_every_argument_binding(self):
        from ootrr_triforce import app_runtime
        from ootrr_triforce.mod_codec import Codec
        root = Path(os.environ["OOTRR_ROMFS"])
        runtime = os.environ.get("OOTRR_CODEC_RESOURCES")
        override = patch.object(app_runtime, "_resource_override", Path(runtime)) if runtime else \
            patch.object(sys, "argv", [os.environ.get("OOTRR_CODEC_APP", str(ROOT / "dist/Client-OOT-Remake.pyz"))])
        with override:
            codec = Codec((root / "Pack/ZsDic.pack.zs").read_bytes())
            for flow, entry in (("Dm_SY_GetInEvent", "GetInEvent_NotTurn_Fado"),
                                ("Dm_SY_GetInEvent", "GetInEvent_NotTurn_BombBag"),
                                ("Dm_SY_GetInEvent", "GetInEvent_Poeshop"),
                                ("Dm_SY_GetInEvent", "GetInEvent_NotTurn_2DShop"),
                                ("NpcCommon", "NpcCommon_HandOver_NpcToPlayer_NoDisplay")):
                with self.subTest(flow=flow, entry=entry):
                    raw = codec.decode((root / ("Event/EventFlow/" + flow + ".bfevfl.zs")).read_bytes())
                    source, target = FlowEditor(raw, flow), editor("Destination")
                    target.flow.version = source.flow.version
                    actors_before = scoped_snapshot(source.chart)
                    copy_entry(source.chart, target, entry, "AP_Native", local_closure=True, bind_arguments=True)
                    copied, checked = target.write("Copied native argument resource")
                    original_actors = {str(actor.identifier): actor for actor in source.chart.actors}
                    for actor in checked.flowchart.actors:
                        scope = actor.argument_entry_point.v
                        if scope is not None:
                            self.assertTrue(scope.name.startswith("AP_Native_"))
                            self.assertTrue(actor.identifier.sub_name.startswith(scope.name + "("))
                            original_id = ActorIdentifier(actor.identifier.name,
                                                          actor.identifier.sub_name.removeprefix("AP_Native_"))
                            self.assertIn(str(original_id), original_actors)
                            original = original_actors[str(original_id)]
                            self.assertEqual(actor.argument_name, original.argument_name)
                            self.assertEqual(actor.params.data if actor.params else None,
                                             original.params.data if original.params else None)
                    self.assertEqual(FlowEditor(copied, "Native roundtrip").write("Native roundtrip")[0], copied)
                    self.assertEqual(scoped_snapshot(source.chart), actors_before)


if __name__ == "__main__":
    unittest.main()
