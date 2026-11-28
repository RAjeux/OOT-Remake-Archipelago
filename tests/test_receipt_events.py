"""Execute generated receipt graphs over a small authored native pouch flow."""
import io
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from evfl import EventFlow
from evfl.actor import Actor
from evfl.common import ActorIdentifier, Argument
from evfl.entry_point import EntryPoint
from evfl.event import ActionEvent, SubFlowEvent, SwitchEvent
from evfl.flowchart import Flowchart
from evfl.util import make_index
from oot_rando.patching.progressive import FlowEditor, link
from oot_rando.patching.soul_adapter import murmur3
from ootrr_triforce.catalog import ITEM_DATA, ITEM_IDS
from ootrr_triforce.receipt_events import CURES, CURSOR_PREFIX, OWNERS, SILENT_ENTRY, build_receipt_flow, event_name
from ootrr_triforce.native_presentations import AMMO_BAGS, STARTER_KITS

TOKEN = "a" * 64
CURSOR = CURSOR_PREFIX + TOKEN


def native_flow():
    flow = EventFlow()
    flow.name = "GetPouchContent"
    flow.flowchart = Flowchart()
    flow.flowchart.name = flow.name
    for name in ("GameSystemActor", "UISystemActor", "SoundSystemActor"):
        actor = Actor()
        actor.identifier = ActorIdentifier(name)
        flow.flowchart.actors.append(actor)
    stream = io.BytesIO()
    assert flow.write(stream)
    editor = FlowEditor(stream.getvalue(), "synthetic native pouch flow")
    prepare = editor.action("Prepare", "PouchSystemActor", "EventTriggerSetForGetWindow",
                            {"Actor": Argument("ActorName")})
    popup = editor.subflow("Popup", "", "OpenGetWindow", None)
    rupee_ui = editor.subflow("RupeeUI", "", "OpenRupeeUIIfNeed", None)
    grant = editor.action("NativeGrant", "PouchSystemActor", "EventTriggerAddOrRemovePouchContent",
                          {"Num": 1, "Actor": Argument("ActorName"),
                           "IsGetEvent": Argument("IsGetInEvent"), "IsEquipDIrect": False})
    hook = editor.action("NativeBagHook", "GameDataActor", "EventTriggerSetGameDataBool",
                         {"GameDataName": "Fixture.NativeBagHook", "Value": True, "Index": -1})
    close_ui = editor.subflow("CloseUI", "", "CloseRupeeUIIfNeed", None)
    optional = editor.switch("OptionalNativeHook", "GameDataActor", "EventQueryIsGameDataBool",
                             {"GameDataName": "Fixture.NativeHookEnabled", "Index": -1}, hook, close_ui)
    save = editor.action("NativeAutoSave", "GameSystemActor", "EventTriggerRequestAutoSave", None)
    played = editor.action("NativeHavePlayed", "PouchSystemActor", "EventTriggerSetHavePlayedGetEvent", None)
    caption_save = editor.action("NativeCaptionSave", "GameSystemActor", "EventTriggerRequestAutoSave", None)
    link(played, caption_save)
    popup_end = EntryPoint("OpenGetWindow_End")
    popup_end.main_event = make_index(played)
    editor.chart.entry_points.append(popup_end)
    autosave = editor.switch("NativeSaveChoice", "PouchSystemActor", "EventQueryIsAutoSavePouchContent",
                            {"ActorName": Argument("ActorName")}, save, None)
    for current, following in [(prepare, popup), (popup, rupee_ui), (rupee_ui, grant),
                               (grant, optional), (hook, close_ui), (close_ui, autosave)]:
        link(current, following)
    entry = EntryPoint("GetPouchContent")
    entry.main_event = make_index(prepare)
    editor.chart.entry_points.append(entry)
    return editor.write("Synthetic receipt input")[0]


class GraphRun:
    def __init__(self, chart, owned=None, hook=True):
        self.entries = {entry.name: entry.main_event.v for entry in chart.entry_points}
        self.owned = owned if owned is not None else set()
        self.hook = hook
        self.trace = []

    def run(self, entry, arguments=None):
        node = self.entries[entry]
        arguments = arguments or {}
        steps = 0
        while node is not None:
            steps += 1
            assert steps < 1000, "Receipt graph loops"
            data = node.data
            params = {key: arguments[value] if isinstance(value, Argument) else value
                      for key, value in (data.params.data.items() if data.params else ())}
            if isinstance(data, ActionEvent):
                command = data.actor_action.v.v
                self.trace.append((command, params))
                if command == "EventTriggerAddOrRemovePouchContent":
                    actor = params["Actor"]
                    assert params["Num"] == 1 or (params["Actor"], params["Num"]) in {
                        (ammo, amount) for _, ammo, amount in STARTER_KITS.values()
                    }, "Only a first-weapon kit gives native single ammunition in quantity"
                    self.owned.add(OWNERS.get(actor, actor))
                if command == "EventTriggerRequestAutoSave":
                    assert any(command == "EventTriggerAddOrSubGameDataInt" and values["GameDataName"] == CURSOR
                               for command, values in self.trace), "Save before the receipt cursor"
                node = data.nxt.v
            elif isinstance(data, SwitchEvent):
                query = data.actor_query.v.v
                if query == "EventQueryCheckIsGet":
                    result = params["ActorName"] in self.owned
                elif query == "EventQueryIsGameDataBool":
                    assert params["GameDataName"] == "Fixture.NativeHookEnabled"
                    result = self.hook
                else:
                    raise AssertionError("Unexpected or unremoved UI query: " + query)
                node = data.cases.get(0 if result else 1)
                node = node.v if node is not None else None
            elif isinstance(data, SubFlowEvent):
                assert data.entry_point_name not in {"OpenGetWindow", "OpenRupeeUIIfNeed", "CloseRupeeUIIfNeed"}
                if data.res_flowchart_name == "":
                    assert data.entry_point_name == SILENT_ENTRY
                    self.run(data.entry_point_name, params)
                else:
                    if (data.res_flowchart_name, data.entry_point_name) == ("Dm_SY_GetInEvent", "AP_IceTrap"):
                        self.trace.append(("FixtureNativeIceTrap", {}))
                    else:
                        assert (data.res_flowchart_name, data.entry_point_name) == ("Dm_SY_Get", "CheckHeart")
                        assert not any(command == "EventTriggerAddOrSubGameDataInt" and values["GameDataName"] == CURSOR
                                       for command, values in self.trace), "Receipt cursor committed before its native health effect"
                        self.trace.append(("FixtureNativeCheckHeart", params))
                node = data.nxt.v
            else:
                raise AssertionError("Blocking or unsupported receipt node: " + type(data).__name__)
        return self.trace


class ReceiptFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = native_flow()
        raw, cls.events = build_receipt_flow(cls.original, TOKEN)
        cls.flow = EventFlow()
        cls.flow.read(raw)
        # Many real saved variables have hashes but no recovered name in this
        # catalogue. Compare hashes so unnamed dungeon counters stay covered.
        cls.saved_flags = {int(flag["hash"], 16) for flag in json.loads(
            (ROOT / "moteur/ootrr-ap/data/flags.json").read_bytes())["flags"]}

    def assert_receipt(self, trace):
        acknowledgements = [i for i, (command, values) in enumerate(trace)
                            if command == "EventTriggerAddOrSubGameDataInt" and values["GameDataName"] == CURSOR]
        self.assertEqual(len(acknowledgements), 1)
        ack = acknowledgements[0]
        self.assertEqual(trace[ack][1]["Value"], 1)
        self.assertEqual(trace[-1][0], "EventTriggerRequestAutoSave")
        self.assertLess(ack, len(trace) - 1)
        self.assertTrue(all(command not in {"EventTriggerAddOrRemovePouchContent", "EventTriggerSetGameDataBool",
                                           "EventTriggerRecoverByCureItem", "EventTriggerSetHavePlayedGetEvent"}
                            for command, values in trace[ack + 1:]))

    def test_every_item_has_one_effect_and_one_cursor_ack(self):
        self.assertEqual(set(self.events), set(ITEM_IDS.values()))
        for name, metadata in ITEM_DATA.items():
            for hook in (False, True):
                with self.subTest(item=name, native_hook=hook):
                    trace = GraphRun(self.flow.flowchart, hook=hook).run(event_name(ITEM_IDS[name]))
                    self.assert_receipt(trace)
                    grants = [params for command, params in trace if command == "EventTriggerAddOrRemovePouchContent"]
                    if metadata["mode"] == "trap":
                        self.assertFalse(grants)
                        self.assertEqual(sum(command == "FixtureNativeIceTrap" for command, _ in trace), 1)
                        self.assertEqual(trace[0][0], "FixtureNativeIceTrap")
                    elif metadata["mode"] == "generic" or metadata["kind"] == "TCGSmallKey":
                        self.assertFalse(grants)
                        for command, params in trace:
                            key = params.get("GameDataName")
                            if key and key != CURSOR:
                                self.assertTrue(murmur3(key) in self.saved_flags, "Unknown saved flag: " + key)
                    elif metadata["actor"] in CURES:
                        self.assertFalse(grants)
                        cures = [params["ActorName"] for command, params in trace
                                 if command == "EventTriggerRecoverByCureItem"]
                        self.assertEqual(cures, [metadata["actor"]])
                    elif metadata["actor"] in AMMO_BAGS:
                        self.assertEqual(trace, [("EventTriggerAddOrSubGameDataInt",
                                                 {"GameDataName": CURSOR, "Index": -1, "Value": 1}),
                                                ("EventTriggerRequestAutoSave", {})])
                        self.assertFalse(grants)
                    else:
                        kit = STARTER_KITS.get(metadata["actor"])
                        expected = ([(kit[0][0], 1), (kit[1], kit[2])] if kit else []) + [(metadata["actor"], 1)]
                        self.assertEqual([(grant["Actor"], grant["Num"]) for grant in grants], expected)
                        played = [index for index, (command, values) in enumerate(trace)
                                  if command == "EventTriggerSetHavePlayedGetEvent"]
                        grant_index = next(index for index, (command, values) in enumerate(trace)
                                           if command == "EventTriggerAddOrRemovePouchContent" and values["Actor"] == metadata["actor"])
                        self.assertEqual(len(played), 1)
                        self.assertLess(played[0], grant_index)
                        hooks = [params for command, params in trace if params.get("GameDataName") == "Fixture.NativeBagHook"]
                        self.assertEqual(len(hooks), int(hook))

    def test_ammunition_requires_its_bag_without_blocking_later_progression(self):
        for name, bags in (("Bombs (20)", ("Item_BombBag_Small", "Item_BombBag_Medium", "Item_BombBag_Large")),
                           ("Arrows (30)", ("Item_Quiver_Small", "Item_Quiver_Medium", "Item_Quiver_Large")),
                           ("Deku Seeds (30)", ("Item_BulletBag_Small", "Item_BulletBag_Medium", "Item_BulletBag_Large"))):
            for owned in (set(), {"Item_Hookshot"}, *({bag} for bag in bags)):
                with self.subTest(item=name, owned=owned):
                    trace = GraphRun(self.flow.flowchart, set(owned)).run(event_name(ITEM_IDS[name]))
                    self.assert_receipt(trace)
                    grants = [values["Actor"] for command, values in trace
                              if command == "EventTriggerAddOrRemovePouchContent"]
                    self.assertEqual(grants, [ITEM_DATA[name]["actor"]] if owned.intersection(bags) else [])
        held = set()
        for name, expected in (("Bombs (20)", None), ("Bomb Bag", "Item_BombBag_Small"),
                               ("Bombs (20)", ITEM_DATA["Bombs (20)"]["actor"])):
            trace = GraphRun(self.flow.flowchart, held).run(event_name(ITEM_IDS[name]))
            self.assert_receipt(trace)
            self.assertEqual([values["Actor"] for command, values in trace
                              if command == "EventTriggerAddOrRemovePouchContent"], [expected] if expected else [])

    def test_progressive_levels_advance_and_saturate(self):
        for name, metadata in ITEM_DATA.items():
            if metadata["mode"] != "tiers":
                continue
            owned = set()
            actual = []
            for _ in range(len(metadata["tiers"]) + 2):
                trace = GraphRun(self.flow.flowchart, owned).run(event_name(ITEM_IDS[name]))
                self.assert_receipt(trace)
                actual.extend(values["Actor"] for command, values in trace
                              if command == "EventTriggerAddOrRemovePouchContent")
            kit = STARTER_KITS.get(metadata["actor"])
            self.assertEqual(actual, ([kit[0][0], kit[1]] if kit else []) +
                             [*metadata["tiers"], metadata["tiers"][-1], metadata["tiers"][-1]])
            for index, tier in enumerate(metadata["tiers"]):
                trace = GraphRun(self.flow.flowchart, {OWNERS.get(tier, tier)}).run(event_name(ITEM_IDS[name]))
                grants = [values["Actor"] for command, values in trace
                          if command == "EventTriggerAddOrRemovePouchContent"]
                self.assertEqual(grants, [metadata["tiers"][min(index + 1, len(metadata["tiers"]) - 1)]])

    def test_dungeon_key_keeps_its_own_dungeon(self):
        trace = GraphRun(self.flow.flowchart).run(event_name(ITEM_IDS["Small Key (Gerudo Training Ground)"]))
        keys = [params["GameDataName"] for command, params in trace
                if "GameDataName" in params and params["GameDataName"] != CURSOR]
        self.assertEqual(keys, ["DungeonInfo.GerudoTrainingGround.SmallKeyNum",
                                "DungeonInfo.GerudoTrainingGround.SmallKeyTotalNum",
                                "DungeonInfo.GerudoTrainingGround.IsGetSmallKeyOnce"])

    def test_treasure_chest_game_key_has_native_counter(self):
        trace = GraphRun(self.flow.flowchart).run(event_name(ITEM_IDS["Small Key (Treasure Chest Game)"]))
        self.assert_receipt(trace)
        keys = [params["GameDataName"] for command, params in trace
                if "GameDataName" in params and params["GameDataName"] != CURSOR]
        self.assertEqual(keys, ["MiniGame_SmallKeyNum", "UI_MiniGameGetSmallKeyOnce"])

    def test_reprocessing_and_unknown_rewards_are_rejected(self):
        with self.assertRaises(ValueError):
            build_receipt_flow(self.original, "invalid-token")
        with self.assertRaises(ValueError):
            build_receipt_flow(self.original, TOKEN, ["Unsupported reward"])
        raw, _ = build_receipt_flow(self.original, TOKEN)
        with self.assertRaises(ValueError):
            build_receipt_flow(raw, TOKEN)


if __name__ == "__main__":
    unittest.main()
