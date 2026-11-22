"""Preserve shuffled story rewards while repairing native progression order."""
import io
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from evfl import EventFlow
from evfl.actor import Actor
from evfl.common import ActorIdentifier
from evfl.container import Container
from evfl.entry_point import EntryPoint
from evfl.event import ActionEvent, SubFlowEvent
from evfl.flowchart import Flowchart
from evfl.util import make_index
from oot_rando.patching.event_info import reachable
from oot_rando.patching.event_patch import _flow, _snapshot, GAMEDATA_ACTOR_PARAMS
from oot_rando.patching.progressive import FlowEditor, link
from ootrr_triforce import story_fixes as story


def editor(name):
    flow = EventFlow()
    flow.name = name
    flow.flowchart = Flowchart()
    flow.flowchart.name = name
    for name in ("GameDataActor", "PouchSystemActor", "UISystemActor", "Player_Event",
                 "ChallengeSystemActor", "GameSystemActor"):
        actor = Actor()
        actor.identifier = ActorIdentifier(name)
        actor.params = Container()
        actor.params.data = dict(GAMEDATA_ACTOR_PARAMS)
        flow.flowchart.actors.append(actor)
    stream = io.BytesIO()
    assert flow.write(stream)
    return FlowEditor(stream.getvalue(), name)


def entry(chart, name, event):
    point = EntryPoint(name)
    point.main_event = make_index(event)
    chart.entry_points.append(point)
    return point


def give(builder, name, actor, then=None):
    event = builder.subflow(name, "Dm_SY_GetInEvent", "GetInEvent_NotTurn_NotNpc", {"ActorName": actor})
    link(event, then)
    return event


def door():
    out = editor(story.DOOR)
    for name in ("Event12", "OOTRRDoorFix4"):
        action = out.action(name, "ChallengeSystemActor", "EventExecuteProgressChallengeStep",
                            {"ChallengeName": story.DOOR, "StepName": "Step04", "IsWaitEnd": True})
        entry(out.chart, name + "Entry", action)
    return out.write("escape fixture")[0]


def windmill(serial=55):
    out = editor(story.WINDMILL)
    final = out.action("NativeAfterSong", "GameDataActor", "EventTriggerSetGameDataBool",
                       {"GameDataName": "WindmillWasSlowed", "Value": True, "Index": -1})
    entry(out.chart, "After_GetStormSong", final)
    reward = give(out, "ShuffledReward", "Item_OddMushroom")
    speed = out.action("OOTRRSongDm_MelodyGet_Storm_" + str(serial) + "_Write", "GameDataActor", "EventTriggerSetGameDataBool",
                       {"GameDataName": "KakarikoVillage_Windmill_IsHighSpeed", "Value": True, "Index": -1})
    played = out.action("OOTRRSong" + str(serial), "GameDataActor", "EventTriggerSetGameDataBool",
                        {"GameDataName": "HavePlayedEvent.Dm_MelodyGet_Storm", "Value": True, "Index": -1})
    link(played, speed)
    link(speed, reward)
    entry(out.chart, "Talk", played)
    entry(out.chart, "PlayStormSong_Adult", played)
    return out.write("windmill fixture")[0]


def nocturne(serial=308):
    out = editor(story.ARRIVAL)
    continuation = out.action("Event280", "Player_Event", "EventTriggerNativeContinuation", None)
    played = out.action("OOTRRSong" + str(serial), "GameDataActor", "EventTriggerSetGameDataBool",
                        {"GameDataName": "HavePlayedEvent.Dm_MelodyGet_Shadow", "Value": True, "Index": -1})
    credit = out.action("ShuffledRewardCredit", "GameDataActor", "EventTriggerSetGameDataBool",
                        {"GameDataName": "OwnShuffledRewardCredit", "Value": True, "Index": -1})
    link(credit, continuation)
    first = give(out, "ShuffledRewardFirstTier", "Item_BombBag_Small", credit)
    second = give(out, "ShuffledRewardSecondTier", "Item_BombBag_Medium", credit)
    choice = out.switch("ShuffledTierChoice", "PouchSystemActor", "EventQueryIsExistInPouch",
                        {"Actor": "Item_BombBag_Small", "Num": 1}, second, first)
    link(played, choice)
    boot = out.action("Event406", "Player_Event", "EventTriggerParticipateEvent", None)
    link(boot, played)
    ending = out.action("Event460", "Player_Event", "EventTriggerNativeArrivalEnding", None)
    change = out.action("Event329", "GameSystemActor", "EventReserveBancChange",
                        {"NextBanc": "KakarikoVillage_Adult_Alternative",
                         "BootEventName": "KakarikoVillage_MelodyGet_Shadow", "IsWaitEnd": True})
    link(change, ending)
    before = out.action("Event496", "Player_Event", "EventPlayerUnequip", {"IsWaitEnd": True})
    link(before, change)
    entry(out.chart, "KakarikoVillage_MelodyGet_Shadow", boot)
    entry(out.chart, "KakarikoVillage_Arrive", before)
    return out.write("nocturne fixture")[0]


def event_map(raw):
    return {event.name: event for event in _flow(raw).flowchart.events}


class PreparedStoryTests(unittest.TestCase):
    def test_generated_song_numbers_do_not_change_story_repairs(self):
        # Reward serialization can allocate different generated node numbers
        # in each seed. Only the native boot/flag/action contract is stable.
        for serial in (308, 957):
            with self.subTest(nocturne_serial=serial):
                raw = story.patch_nocturne(nocturne(serial))
                nodes = event_map(raw)
                self.assertIs(nodes["OOTRRSong" + str(serial)].data.nxt.v,
                              nodes[story.PREFIX + "NocturneLoading"])
                self.assertIs(nodes["Event496"].data.nxt.v, nodes["ShuffledTierChoice"])
                self.assertEqual(story.patch_nocturne(raw), raw)
        for serial in (55, 199):
            with self.subTest(windmill_serial=serial):
                raw = story.patch_windmill(windmill(serial))
                nodes = event_map(raw)
                self.assertIs(nodes["OOTRRSongDm_MelodyGet_Storm_" + str(serial) + "_Write"].data.nxt.v,
                              nodes[story.PREFIX + "StormAfter"])
                self.assertEqual(story.patch_windmill(raw), raw)

    def test_complete_upstream_repairs_are_kept_without_duplicate_events(self):
        for fixture, transform in ((windmill(199), story.patch_windmill), (nocturne(957), story.patch_nocturne)):
            with self.subTest(flow=transform.__name__):
                fixed = transform(fixture)
                altered = FlowEditor(fixed, _flow(fixed).flowchart.name)
                for event in altered.chart.events:
                    if event.name.startswith(story.PREFIX):
                        old_name = event.name
                        event.name = "OOTRRSongGenerated_" + old_name[len(story.PREFIX):]
                        altered.expected[event.name] = altered.expected.pop(old_name)
                upstream = altered.write("already repaired upstream fixture")[0]
                self.assertEqual(transform(upstream), upstream)
                self.assertEqual(transform(transform(upstream)), upstream)

    def test_partial_upstream_nocturne_repair_is_rejected(self):
        fixed = story.patch_nocturne(nocturne(957))
        for variant in ("missing_reward", "wrong_fade"):
            with self.subTest(variant=variant):
                altered = FlowEditor(fixed, story.ARRIVAL)
                for event in altered.chart.events:
                    if event.name.startswith(story.PREFIX):
                        old_name = event.name
                        event.name = "Upstream_" + old_name[len(story.PREFIX):]
                        altered.expected[event.name] = altered.expected.pop(old_name)
                nodes = {event.name: event for event in altered.chart.events}
                if variant == "missing_reward":
                    link(nodes["Event496"], nodes["Event329"])
                else:
                    fade = nodes["Upstream_NocturneFade"]
                    fade.data.params.data["Length"] = 0
                    altered.expected[fade.name]["Length"] = 0
                with self.assertRaises(ValueError):
                    story.patch_nocturne(altered.write("partial upstream layout")[0])

    def test_played_anchor_requires_unique_true_write_reachable_from_native_entry(self):
        altered = FlowEditor(nocturne(957), story.ARRIVAL)
        altered.action("UnreachableSameFlag", "GameDataActor", "EventTriggerSetGameDataBool",
                       {"GameDataName": "HavePlayedEvent.Dm_MelodyGet_Shadow", "Value": True, "Index": -1})
        raw = altered.write("unreachable matching flag")[0]
        self.assertEqual(story.patch_nocturne(story.patch_nocturne(raw)), story.patch_nocturne(raw))
        for ambiguous in (False, True):
            with self.subTest(ambiguous=ambiguous):
                altered = FlowEditor(nocturne(957), story.ARRIVAL)
                played = next(event for event in altered.chart.events if event.name == "OOTRRSong957")
                if ambiguous:
                    duplicate = altered.action("SecondReachablePlayedWrite", "GameDataActor", "EventTriggerSetGameDataBool",
                        {"GameDataName": "HavePlayedEvent.Dm_MelodyGet_Shadow", "Value": True, "Index": -1})
                    link(duplicate, played.data.nxt.v)
                    link(played, duplicate)
                else:
                    played.data.params.data["Value"] = False
                    altered.expected[played.name]["Value"] = False
                with self.assertRaises(ValueError):
                    story.patch_nocturne(altered.write("invalid played anchor")[0])

    def test_escape_moves_both_step_requests_without_changing_other_parameters(self):
        before = door()
        after = story.patch_escape_flow(before)
        original, actual = _snapshot(_flow(before)), _snapshot(_flow(after))
        for name in ("Event12", "OOTRRDoorFix4"):
            original[name]["StepName"] = "Step05"
        self.assertEqual(actual, original)
        self.assertEqual(story.patch_escape_flow(after), after)

    def test_escape_rejects_an_unrelated_challenge_or_new_game_layout(self):
        raw = door()
        altered = FlowEditor(raw, story.DOOR)
        event = next(e for e in altered.chart.events if e.name == "Event12")
        event.data.params.data["ChallengeName"] = "OtherQuest"
        altered.expected[event.name]["ChallengeName"] = "OtherQuest"
        with self.assertRaises(ValueError):
            story.patch_escape_flow(altered.write("unrelated quest fixture")[0])

    def test_windmill_runs_native_post_lesson_before_exact_shuffled_reward(self):
        before = windmill()
        after = story.patch_windmill(before)
        nodes = event_map(after)
        call = nodes[story.PREFIX + "StormAfter"]
        self.assertIsInstance(call.data, SubFlowEvent)
        self.assertEqual((call.data.res_flowchart_name, call.data.entry_point_name), ("", "After_GetStormSong"))
        self.assertIs(nodes["OOTRRSongDm_MelodyGet_Storm_55_Write"].data.nxt.v, call)
        self.assertIs(call.data.nxt.v, nodes["ShuffledReward"])
        self.assertEqual(nodes["ShuffledReward"].data.params.data, {"ActorName": "Item_OddMushroom"})
        self.assertEqual(story.patch_windmill(after), after)
        chart = _flow(after).flowchart
        point = next(p for p in chart.entry_points if p.name == "Talk")
        self.assertIn(chart.events.index(next(e for e in chart.events if e.name == call.name)), point._sub_flow_event_indices)

    def test_nocturne_moves_entire_reward_and_credit_before_scene_change(self):
        before = nocturne()
        after = story.patch_nocturne(before)
        nodes = event_map(after)
        # Preserve both upgrade branches, their credit and their native actors.
        self.assertIs(nodes["Event496"].data.nxt.v, nodes["ShuffledTierChoice"])
        for name in ("ShuffledRewardFirstTier", "ShuffledRewardSecondTier"):
            self.assertIs(nodes[name].data.nxt.v, nodes["ShuffledRewardCredit"])
        self.assertIs(nodes["ShuffledRewardCredit"].data.nxt.v, nodes["Event329"])
        previous = _snapshot(_flow(before))
        current = _snapshot(_flow(after))
        self.assertEqual({name: current[name] for name in previous}, previous)
        self.assertEqual(story.patch_nocturne(after), after)

    def test_nocturne_boot_waits_for_loading_then_fades_without_another_reward(self):
        chart = _flow(story.patch_nocturne(nocturne())).flowchart
        point = next(p for p in chart.entry_points if p.name == "KakarikoVillage_MelodyGet_Shadow")
        chain, current = [], point.main_event.v
        while current:
            chain.append(current)
            current = current.data.nxt.v
        commands = [story._action(event) for event in chain]
        self.assertLess(commands.index(("UISystemActor", "EventWaitCloseLoadingFade")),
                        commands.index(("UISystemActor", "EventEventFadeIn")))
        self.assertFalse(any(isinstance(event.data, SubFlowEvent) for event in chain))
        arrive = next(p for p in chart.entry_points if p.name == "KakarikoVillage_Arrive")
        calls = [event for event in reachable(arrive.main_event.v) if isinstance(event.data, SubFlowEvent)]
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(chart.events.index(event) in arrive._sub_flow_event_indices for event in calls))

    def test_nocturne_refuses_unknown_scene_routing_before_rewriting_rewards(self):
        raw = nocturne()
        altered = FlowEditor(raw, story.ARRIVAL)
        change = next(e for e in altered.chart.events if e.name == "Event329")
        change.data.params.data["BootEventName"] = "OtherScene"
        altered.expected[change.name]["BootEventName"] = "OtherScene"
        with self.assertRaises(ValueError):
            story.patch_nocturne(altered.write("unknown scene fixture")[0])

    def test_partial_story_markers_and_cyclic_write_chain_fail_closed(self):
        altered = FlowEditor(windmill(), story.WINDMILL)
        write = next(e for e in altered.chart.events if e.name == "OOTRRSongDm_MelodyGet_Storm_55_Write")
        link(write, write)
        with self.assertRaises(ValueError):
            story.patch_windmill(altered.write("cyclic story fixture")[0])
        altered = FlowEditor(story.patch_nocturne(nocturne()), story.ARRIVAL)
        wait = next(e for e in altered.chart.events if e.name == story.PREFIX + "NocturneLoading")
        wait.data.params.data["IsWaitEnd"] = False
        altered.expected[wait.name]["IsWaitEnd"] = False
        with self.assertRaises(ValueError):
            story.patch_nocturne(altered.write("partial story marker fixture")[0])


@unittest.skipUnless(os.environ.get("OOTRR_ROMFS"), "requires a private native RomFS")
class NativeMoatTests(unittest.TestCase):
    def test_escape_pair_keeps_ocarina_until_collected_independently_of_step(self):
        import ainb
        from unittest.mock import patch
        from ootrr_triforce.mod_codec import Codec
        from oot_rando.formats import byml_codec
        romfs = Path(os.environ["OOTRR_ROMFS"])
        raw = (romfs / story.MOAT_LOGIC).read_bytes()
        original = ainb.AINB.from_binary(raw).as_dict()
        updated = story.patch_moat_logic(raw)
        doc = ainb.AINB.from_binary(updated).as_dict()
        self.assertEqual(doc["Nodes"][1], original["Nodes"][1])
        self.assertEqual(doc["Nodes"][3], original["Nodes"][3])
        self.assertEqual(doc["Nodes"][0]["Name"], "HoldGameDataGetBoolSimple")
        self.assertEqual(doc["Nodes"][0]["Parameters"]["Inputs"]["String"][0]["Default Value"], story.ESCAPED)
        self.assertEqual(story.patch_moat_logic(updated), updated)
        codec_app = os.environ.get("OOTRR_CODEC_APP", str(ROOT / "dist/Client-OOT-Remake.pyz"))
        with patch.object(sys, "argv", [codec_app]):
            codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
        banc = codec.decode((romfs / story.MOAT_BANC).read_bytes())
        changed = story.patch_moat_banc(banc)
        before_doc, after_doc = byml_codec.load(banc), byml_codec.load(changed)
        target = next(actor for actor in before_doc["root"]["Actors"] if actor.get("Hash") == story.MOAT_ACTOR)
        target["Presence"] = {"FlagName": story.PICKED, "IsCheckLazy": False, "IsNegation": True}
        self.assertEqual(after_doc, before_doc)
        self.assertEqual(story.patch_moat_banc(changed), changed)

    def test_existing_escape_not_required_creation_stays_unconditional(self):
        import ainb
        romfs = Path(os.environ["OOTRR_ROMFS"])
        original = ainb.AINB.from_binary((romfs / story.MOAT_LOGIC).read_bytes())
        doc = original.as_dict()
        node = doc["Nodes"][2]
        create = next(value for value in node["Parameters"]["Inputs"]["Bool"] if value["Name"] == "Logic_Create")
        create.update({"Node Index": -1, "Output Index": 0, "Flags": ["Uses Default", "Is Output"]})
        node["Queries"] = [2]
        node["Plugs"]["Generic"] = [value for value in node["Plugs"]["Generic"] if value["Name"] != "Logic_Create"]
        updated = ainb.AINB.from_dict(doc)
        updated.blackboard = original.blackboard
        raw = updated.to_binary()
        self.assertEqual(story.patch_moat_logic(raw), raw)


if __name__ == "__main__":
    unittest.main()
