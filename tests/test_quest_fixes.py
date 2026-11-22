"""Native-local gift availability and monotonic Fire/Spirit quest progress."""
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_story_fixes import editor, entry
from evfl.event import ActionEvent, SubFlowEvent, SwitchEvent
from oot_rando.patching.event_patch import _flow, _snapshot
from oot_rando.patching.progressive import link
from ootrr_triforce import quest_fixes as quest


def fixture(name):
    out = editor(name)
    # The native Spirit flow already has this actor. Do not invent its params.
    event_actor = out.chart.actors[2]
    from evfl.actor import Actor
    from evfl.common import ActorIdentifier
    from evfl.container import Container
    actor = Actor()
    actor.identifier = ActorIdentifier("EventSystemActor")
    actor.params = Container()
    actor.params.data = dict(event_actor.params.data)
    out.chart.actors.append(actor)
    fallback = out.action("NativeFallback", "Player_Event", "EventTriggerFallback", None)
    for record in quest.LATE:
        if record[0] == name:
            for point in record[1]:
                entry(out.chart, point, fallback)
    for flow, challenge, step in quest.ORDER:
        if flow != name:
            continue
        after = out.action("NativeAfter" + step, "Player_Event", "EventTriggerAfterStep", None)
        request = out.action("NativeStep" + step, "ChallengeSystemActor", "EventExecuteProgressChallengeStep",
                             {"ChallengeName": challenge, "StepName": step, "IsWaitEnd": True})
        link(request, after)
        entry(out.chart, "StepEntry" + step, request)
    if name == quest.GENERATE_FLOW:
        entry(out.chart, quest.GENERATE_ENTRY, fallback)
        entry(out.chart, "OtherExit", fallback)
    return out.write("quest fixture")[0]


class Run:
    def __init__(self, raw, **flags):
        self.chart = _flow(raw).flowchart
        self.flags = flags
        self.calls, self.steps, self.fallback, self.after = [], [], 0, 0

    def run(self, name):
        event = next(point.main_event.v for point in self.chart.entry_points if point.name == name)
        limit = 0
        while event:
            limit += 1
            assert limit < 100, "quest repair introduced a cycle"
            data = event.data
            params = data.params.data if data.params else {}
            if isinstance(data, SwitchEvent):
                yes = bool(self.flags.get(params["GameDataName"], False))
                target = data.cases.get(0 if yes else 1)
                event = target.v if target else None
            elif isinstance(data, SubFlowEvent):
                self.calls.append((data.res_flowchart_name, data.entry_point_name))
                event = data.nxt.v
            elif isinstance(data, ActionEvent):
                action = data.actor_action.v.v
                if action == "EventTriggerSetGameDataBool":
                    self.flags[params["GameDataName"]] = params["Value"]
                elif action == "EventExecuteProgressChallengeStep":
                    self.steps.append((params["ChallengeName"], params["StepName"]))
                elif action == "EventTransition":
                    self.calls.append(("scene", params["EventName"]))
                elif action == "EventTriggerFallback":
                    self.fallback += 1
                elif action == "EventTriggerAfterStep":
                    self.after += 1
                else:
                    raise AssertionError(action)
                event = data.nxt.v
            else:
                raise AssertionError(type(data))
        return self


class QuestOrderTests(unittest.TestCase):
    def test_thawed_king_zora_uses_existing_gift_once_even_without_tunic(self):
        raw = quest.patch_quest_flow(fixture("Npc_Zora_KingZora_adult"), "Npc_Zora_KingZora_adult")
        record = quest.LATE[0]
        state = Run(raw, **{record[2]: True})
        state.run("Talk")
        self.assertEqual(state.calls, [("SageOfWater", "Safety_Entry")])
        state.flags[record[3]] = True
        state.run("Talk")
        self.assertEqual(len(state.calls), 1)
        self.assertEqual(state.fallback, 1)
        for flags in ({quest.CHILD: True, record[2]: True}, {record[2]: False}):
            state = Run(raw, **flags).run("Talk")
            self.assertEqual(state.calls, [])
            self.assertEqual(state.fallback, 1)

    def test_all_late_goron_talk_entries_reuse_the_native_randomized_gift(self):
        record = quest.LATE[1]
        raw = quest.patch_quest_flow(fixture(record[0]), record[0])
        for point in record[1]:
            state = Run(raw).run(point)
            self.assertEqual(state.calls, [("SageOfFire", "Step02_Npc_Goron_DaruniaJr_Adult_Talk")])
            state.flags[record[3]] = True
            state.run(point)
            self.assertEqual(len(state.calls), 1)
            self.assertEqual(state.fallback, 1)

    def test_unplayed_card_scene_is_offered_without_duplicating_a_finished_scene(self):
        record = quest.LATE[2]
        raw = quest.patch_quest_flow(fixture(record[0]), record[0])
        self.assertEqual(Run(raw).run(record[1][0]).calls, [("scene", "Dm_Gerudo_0025")])
        state = Run(raw, **{record[3]: True}).run(record[1][0])
        self.assertFalse(state.calls)
        self.assertEqual(state.fallback, 1)

    def test_earlier_fire_and_spirit_requests_never_roll_a_later_quest_back(self):
        for flow, challenge, step in quest.ORDER:
            with self.subTest(flow=flow, step=step):
                raw = quest.patch_quest_flow(fixture(flow), flow)
                comparison = quest.STORY_AFTER_STEP01 if (challenge, step) == ("SageOfSpirit", "Step01") else challenge + "_IsAfter_" + step + "_Exp"
                late = Run(raw, **{comparison: True}).run("StepEntry" + step)
                self.assertEqual(late.steps, [])
                self.assertEqual(late.after, 1)
                early = Run(raw).run("StepEntry" + step)
                self.assertEqual(early.steps, [(challenge, step)])
                self.assertEqual(early.after, 1)

    def test_spirit_story_guard_uses_actual_stage_when_fortress_clearance_uses_card(self):
        name = "Npc_Hylia_012_Adult"
        raw = quest.patch_quest_flow(fixture(name), name)
        late_without_card = Run(raw, **{quest.STORY_AFTER_STEP01: True,
            "SageOfSpirit_IsAfter_Step01_Exp": False}).run("StepEntryStep01")
        self.assertEqual(late_without_card.steps, [])
        early_with_card = Run(raw, **{quest.STORY_AFTER_STEP01: False,
            "SageOfSpirit_IsAfter_Step01_Exp": True}).run("StepEntryStep01")
        self.assertEqual(early_with_card.steps, [("SageOfSpirit", "Step01")])

    def test_rescue_mark_commits_even_when_spirit_step_request_is_skipped(self):
        raw = quest.patch_quest_flow(fixture("SageOfSpirit"), "SageOfSpirit")
        for late in (False, True):
            state = Run(raw, SageOfSpirit_IsAfter_Step02_Exp=late).run("StepEntryStep02")
            self.assertIs(state.flags[quest.RESCUED], True)

    def test_crater_exit_creates_the_adult_goron_without_changing_other_exits(self):
        raw = quest.patch_quest_flow(fixture(quest.GENERATE_FLOW), quest.GENERATE_FLOW)
        adult = Run(raw).run(quest.GENERATE_ENTRY)
        self.assertIs(adult.flags[quest.GENERATE_FLAG], True)
        self.assertEqual(adult.fallback, 1)
        for entry_name, flags in ((quest.GENERATE_ENTRY, {quest.CHILD: True}), ("OtherExit", {})):
            state = Run(raw, **flags).run(entry_name)
            self.assertNotIn(quest.GENERATE_FLAG, state.flags)
            self.assertEqual(state.fallback, 1)

    def test_source_actions_and_gifts_are_unchanged_and_preparation_is_idempotent(self):
        flows = {record[0] for record in quest.LATE} | {record[0] for record in quest.ORDER} | {quest.GENERATE_FLOW}
        for name in flows:
            with self.subTest(flow=name):
                before = fixture(name)
                after = quest.patch_quest_flow(before, name)
                original, actual = _snapshot(_flow(before)), _snapshot(_flow(after))
                self.assertEqual({key: actual[key] for key in original}, original)
                self.assertEqual(quest.patch_quest_flow(after, name), after)


@unittest.skipUnless(os.environ.get("OOTRR_ROMFS"), "requires a private native RomFS")
class RealQuestOrderTests(unittest.TestCase):
    def test_all_native_entries_and_request_windows_match_and_zora_trade_is_retained(self):
        from unittest.mock import patch
        from ootrr_triforce.mod_codec import Codec
        romfs = Path(os.environ["OOTRR_ROMFS"])
        codec_app = os.environ.get("OOTRR_CODEC_APP", str(ROOT / "dist/Client-OOT-Remake.pyz"))
        with patch.object(sys, "argv", [codec_app]):
            codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
        flows = {record[0] for record in quest.LATE} | {record[0] for record in quest.ORDER} | {quest.GENERATE_FLOW}
        for name in sorted(flows):
            before = codec.decode((romfs / ("Event/EventFlow/" + name + ".bfevfl.zs")).read_bytes())
            after = quest.patch_quest_flow(before, name)
            original, actual = _snapshot(_flow(before)), _snapshot(_flow(after))
            self.assertEqual({key: actual[key] for key in original}, original)
            if name == "Npc_Zora_KingZora_adult":
                self.assertIn("Event131", actual)
                self.assertEqual(actual["Event131"], original["Event131"])
            self.assertEqual(quest.patch_quest_flow(after, name), after)


if __name__ == "__main__":
    unittest.main()
