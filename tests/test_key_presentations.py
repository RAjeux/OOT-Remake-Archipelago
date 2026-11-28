"""Dungeon receipts name their destination while retaining native effects."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from evfl.actor import Actor
from evfl.common import ActorIdentifier, Argument
from evfl.entry_point import EntryPoint
from evfl.event import SubFlowEvent
from evfl.util import make_index, make_rindex
from oot_rando.patching.progressive import FlowEditor, link
from ootrr_triforce.catalog import ITEM_DATA, ITEM_IDS
from ootrr_triforce.dungeon_messages import message_id
from ootrr_triforce.native_presentations import (PRESENTER_NAME, PRESENTER_ENTRY, CAMERA_FACING_FLOW,
                                                CAMERA_FACING_ENTRY, SMALL_KEY_MODEL, append_local_chests,
                                                append_recipe, copy_receipt_presenter)
from ootrr_triforce.receipt_events import DUNGEONS, build_presented_receipts, event_name
from ootrr_triforce.presentation_models import SHOW_ACTOR_ARGUMENT, model_actor
from test_presented_receipts import native_presenter, native_facing_animation, SceneRun, TOKEN, CURSOR
from test_receipt_events import native_flow
from test_network_flows import editor as empty_editor

DUNGEON_ITEMS = tuple(name for name, metadata in ITEM_DATA.items()
                      if metadata["mode"] == "generic" and metadata.get("dungeon"))


def real_model_presenter():
    from evfl.common import Argument
    from evfl.container import Container
    source = FlowEditor(native_presenter(), "Native model command")
    model = next(event for event in source.chart.events if event.name == "NativeModel")
    model.data.actor_action = make_rindex(source._holder(model.data.actor.v.actions,
                                                        "EventCreateShowItemFromActorFileName"))
    model.data.params = Container()
    model.data.params.data = {"Actor": Argument("ActorName"), "IsWaitEnd": True}
    source.expected[model.name] = dict(model.data.params.data)
    return source.write("Native model command")[0]


def chest_presenter():
    source = empty_editor("Dm_SY_TreasureboxSmall")
    for name in ("TreasureBox_EventStarter", "Fixture"):
        actor = Actor()
        actor.identifier = ActorIdentifier(name)
        source.chart.actors.append(actor)
    model = source.action("NativeModel", "Fixture", "FixtureNativeModel", {"ActorName": Argument("ContentName")})
    sound = source.action("NativeSound", "Fixture", "FixtureNativeSound", {"Sound": "native-chest"})
    get = source.subflow("NativeGet", "GetPouchContent", "GetPouchContentByActorNameForTreasureBox",
                        {"ActorName": Argument("ContentName")})
    cleanup = source.action("NativeCleanup", "Fixture", "FixtureCleanup", None)
    link(model, sound)
    link(sound, get)
    link(get, cleanup)
    entry = EntryPoint("Success_")
    entry.main_event = make_index(model)
    source.chart.entry_points.append(entry)
    return source


class KeyPresentationTests(unittest.TestCase):
    def test_only_small_key_model_and_rotation_use_the_native_minigame_actor(self):
        names = ("Small Key (Forest Temple)", "Small Key (Thieves Hideout)",
                 "Boss Key (Fire Temple)", "Map (Water Temple)")
        pouch, presented, _ = build_presented_receipts(native_flow(), real_model_presenter(), TOKEN, names)
        charts = {name: FlowEditor(raw, name).chart for name, raw in (
            ("GetPouchContent", pouch), (PRESENTER_NAME, presented), (CAMERA_FACING_FLOW, native_facing_animation()))}
        for name in names:
            with self.subTest(item=name):
                small = ITEM_DATA[name]["kind"] in {"SmallKey", "HideoutSmallKey"}
                run = SceneRun(charts)
                run.run("GetPouchContent", event_name(ITEM_IDS[name]))
                models = [params["Actor"] for action, params in run.trace
                          if action == "EventCreateShowItemFromActorFileName"]
                self.assertEqual(models, [SMALL_KEY_MODEL if small else ITEM_DATA[name]["actor"]])
                rotations = [params["ContentName"] for flow, entry, params in run.calls
                             if flow == CAMERA_FACING_FLOW and entry == CAMERA_FACING_ENTRY]
                self.assertEqual(rotations, [ITEM_DATA[name]["actor"]])
                windows = [params["ActorName"] for action, params in run.trace if action == "FixtureItemWindow"]
                self.assertFalse(windows)
                self.assertEqual([params["MessageId"] for action, params in run.trace if action == "EventTalk"],
                                 [message_id(ITEM_DATA[name])])
                credits = [params["GameDataName"] for action, params in run.trace
                           if action in {"EventTriggerSetGameDataBool", "EventTriggerAddOrSubGameDataInt"}]
                self.assertNotIn("MiniGame_SmallKeyNum", credits)
                if small:
                    dungeon = "ForestTemple" if "Forest" in name else "GerudoFortress"
                    self.assertIn("DungeonInfo." + dungeon + ".SmallKeyNum", credits)
                    self.assertIn("DungeonInfo." + dungeon + ".SmallKeyTotalNum", credits)
                self.assertEqual(credits.count(CURSOR), 1)

    def assert_named_window_and_credit(self, run, name, *, received):
        metadata = ITEM_DATA[name]
        dialogs = [(actor, params) for actor, action, params in run.actions if action == "EventTalk"]
        self.assertEqual([actor for actor, _ in dialogs], ["SystemTextNPC"])
        params = dialogs[0][1]
        self.assertEqual(params["MessageId"], message_id(metadata))
        self.assertEqual(params["OverrideStyle"], 4)
        self.assertTrue(params["IsWaitEnd"])
        self.assertTrue(params["IsCloseDialog"])
        self.assertFalse(any(action == "FixtureItemWindow" for action, _ in run.trace))
        self.assertEqual(sum(action == "FixtureNativeModel" for action, _ in run.trace), 1)
        self.assertEqual(sum(action == "FixtureNativeSound" for action, _ in run.trace), 1)
        self.assertFalse(any(action.startswith("EventGetDungeon") for action, _ in run.trace))
        self.assertFalse(any(action == "EventTriggerAddOrRemovePouchContent" for action, _ in run.trace))
        credits = [(action, params["GameDataName"], params["Value"]) for action, params in run.trace
                   if action in {"EventTriggerSetGameDataBool", "EventTriggerAddOrSubGameDataInt"}]
        prefix = "DungeonInfo." + DUNGEONS[metadata["dungeon"]] + "."
        if metadata["kind"] in {"SmallKey", "HideoutSmallKey"}:
            expected = [("EventTriggerAddOrSubGameDataInt", prefix + "SmallKeyNum", 1),
                        ("EventTriggerAddOrSubGameDataInt", prefix + "SmallKeyTotalNum", 1),
                        ("EventTriggerSetGameDataBool", prefix + "IsGetSmallKeyOnce", True)]
        else:
            member = {"BossKey": "IsGetBossKey", "GanonBossKey": "IsGetBossKey",
                      "Map": "IsGetMap", "Compass": "IsGetCompass"}[metadata["kind"]]
            expected = [("EventTriggerSetGameDataBool", prefix + member, True)]
        if received:
            expected.append(("EventTriggerAddOrSubGameDataInt", CURSOR, 1))
        self.assertEqual(credits, expected)

    def test_every_dungeon_item_receipt_has_one_named_window_and_only_its_original_effect(self):
        pouch, shown, entries = build_presented_receipts(native_flow(), native_presenter(), TOKEN, DUNGEON_ITEMS)
        charts = {"GetPouchContent": FlowEditor(pouch, "key receipts").chart,
                  PRESENTER_NAME: FlowEditor(shown, "key presenter").chart,
                  CAMERA_FACING_FLOW: FlowEditor(native_facing_animation(), "key camera").chart}
        self.assertEqual(len({message_id(ITEM_DATA[name]) for name in DUNGEON_ITEMS}), len(DUNGEON_ITEMS))
        for name in DUNGEON_ITEMS:
            with self.subTest(item=name):
                run = SceneRun(charts)
                run.run("GetPouchContent", entries[ITEM_IDS[name]])
                self.assert_named_window_and_credit(run, name, received=True)
                self.assertEqual(run.trace[-1][0], "EventTriggerRequestAutoSave")

    def test_every_dungeon_item_local_chest_opens_once_without_received_cursor(self):
        source = chest_presenter()
        entries = append_local_chests(source, native_flow(), DUNGEON_ITEMS)
        raw = source.write("Named dungeon chest rewards")[0]
        charts = {"Dm_SY_TreasureboxSmall": FlowEditor(raw, "named chests").chart}
        for name in DUNGEON_ITEMS:
            with self.subTest(item=name):
                run = SceneRun(charts)
                run.run("Dm_SY_TreasureboxSmall", entries[name])
                self.assert_named_window_and_credit(run, name, received=False)
                self.assertEqual(sum(action == "EventTriggerTreasureBoxOpened" for action, _ in run.trace), 1)
                self.assertEqual(run.trace[-1][0], "FixtureCleanup")

    def test_minigame_key_and_regular_item_keep_their_generic_native_window(self):
        names = ("Small Key (Treasure Chest Game)", "Rupees (5)")
        pouch, shown, entries = build_presented_receipts(native_flow(), native_presenter(), TOKEN, names)
        charts = {"GetPouchContent": FlowEditor(pouch, "ordinary receipts").chart,
                  PRESENTER_NAME: FlowEditor(shown, "ordinary presenter").chart,
                  CAMERA_FACING_FLOW: FlowEditor(native_facing_animation(), "ordinary camera").chart}
        for name in names:
            with self.subTest(item=name):
                self.assertIsNone(message_id(ITEM_DATA[name]))
                run = SceneRun(charts)
                run.run("GetPouchContent", entries[ITEM_IDS[name]])
                self.assertEqual([p["ActorName"] for a, p in run.trace if a == "FixtureItemWindow"],
                                 [ITEM_DATA[name]["actor"]])
                self.assertFalse(any(action == "EventTalk" for action, _ in run.trace))

    def test_quiet_dungeon_recipes_never_open_a_dialogue(self):
        for name in DUNGEON_ITEMS:
            with self.subTest(item=name):
                editor = empty_editor("GetPouchContent")
                for identifier in ("GameDataActor", "GameSystemActor"):
                    actor = Actor()
                    actor.identifier = ActorIdentifier(identifier)
                    editor.chart.actors.append(actor)
                commit = editor.action("FixtureCommit", "GameSystemActor", "EventTriggerRequestAutoSave", None)
                root = append_recipe(editor, ITEM_DATA[name], "QuietDungeon", "unused", commit, pickup=True)
                entry = EntryPoint("Quiet")
                entry.main_event = make_index(root)
                editor.chart.entry_points.append(entry)
                raw = editor.write("Quiet dungeon recipe")[0]
                run = SceneRun({"GetPouchContent": FlowEditor(raw, "quiet dungeon").chart})
                run.run("GetPouchContent", "Quiet")
                self.assertFalse(any(action in {"EventTalk", "FixtureItemWindow"} for action, _ in run.trace))
                self.assertEqual(run.trace[-1][0], "EventTriggerRequestAutoSave")


@unittest.skipUnless(os.environ.get("OOTRR_ROMFS"), "requires native v1.1.1 presentation assets")
class NativeKeyPresentationTests(unittest.TestCase):
    def test_all_named_receipts_roundtrip_real_native_pouch_presenter_and_camera(self):
        from ootrr_triforce import app_runtime
        from ootrr_triforce.mod_codec import Codec
        from oot_rando.formats import byml_codec
        from evfl.event import ActionEvent
        game = Path(os.environ["OOTRR_ROMFS"])
        with patch.object(app_runtime, "_resource_override", Path(os.environ["OOTRR_CODEC_RESOURCES"])):
            codec = Codec((game / "Pack/ZsDic.pack.zs").read_bytes())
            def read(relative):
                return codec.decode((game / relative).read_bytes())
            info = {row["__RowId"]: row for row in byml_codec.load(
                read("RSDB/PouchActorInfo.Product.111.rstbl.byml.zs"))["root"]}
            pouch, presented, entries = build_presented_receipts(
                read("Event/EventFlow/GetPouchContent.bfevfl.zs"),
                read("Event/EventFlow/Dm_SY_GetInEvent.bfevfl.zs"), TOKEN, DUNGEON_ITEMS,
                native_info=info, ground_raw=read("Event/EventFlow/Dm_SY_Get.bfevfl.zs"))
        chart = FlowEditor(pouch, "Real native named dungeon receipts").chart
        windows = {event.name: event for event in chart.events if event.name.endswith("_Pouch_Window")}
        self.assertEqual(len(windows), len(DUNGEON_ITEMS))
        self.assertEqual(len(entries), len(DUNGEON_ITEMS))
        FlowEditor(presented, "Real native named dungeon presentation")
        for name in DUNGEON_ITEMS:
            with self.subTest(item=name):
                window = windows[event_name(ITEM_IDS[name]) + "_Pouch_Window"]
                self.assertIsInstance(window.data, ActionEvent)
                self.assertEqual(str(window.data.actor.v.identifier), "SystemTextNPC")
                self.assertEqual(window.data.actor_action.v.v, "EventTalk")
                self.assertEqual(window.data.params.data["MessageId"], message_id(ITEM_DATA[name]))
                self.assertEqual(window.data.params.data["OverrideStyle"], 4)

    def test_real_native_model_rotation_and_window_arguments_remain_separate(self):
        from ootrr_triforce import app_runtime
        from ootrr_triforce.mod_codec import Codec
        from oot_rando.formats import byml_codec
        from oot_rando.formats.inspect_resources import sarc
        game = Path(os.environ["OOTRR_ROMFS"])
        with patch.object(app_runtime, "_resource_override", Path(os.environ["OOTRR_CODEC_RESOURCES"])):
            codec = Codec((game / "Pack/ZsDic.pack.zs").read_bytes())
            raw = codec.decode((game / "Event/EventFlow/Dm_SY_GetInEvent.bfevfl.zs").read_bytes())
            model_pack = sarc(codec.decode((game / "Pack/Actor/Obj_MiniGame_SmallKey.pack.zs").read_bytes()))
            animation = codec.decode((game / "AS/Obj_Dungeon_SmallKey.root.asb.zs").read_bytes())
            info = byml_codec.load(codec.decode((game / "RSDB/PouchActorInfo.Product.111.rstbl.byml.zs").read_bytes()))
        actor = byml_codec.load(model_pack["Actor/Obj_MiniGame_SmallKey.engine__actor__ActorParam.bgyml"])["root"]
        self.assertIn("Obj_MiniGame_SmallKey", actor["Components"]["ASInfoRef"])
        self.assertIn(b"Rotate_GetDemo", animation)
        self.assertIn("Item_Dungeon_SmallKey", {row["__RowId"] for row in info["root"]})
        for name in ("Small Key (Forest Temple)", "Small Key (Thieves Hideout)"):
            with self.subTest(item=name):
                target = FlowEditor(raw, PRESENTER_NAME)
                prefix = "AP_Key_" + str(ITEM_IDS[name])
                copy_receipt_presenter(target, ITEM_DATA[name], ITEM_IDS[name], "AP_KeyEffect", prefix=prefix)
                _, checked = target.write("Native key presentation")
                events = [event for event in checked.flowchart.events if event.name.startswith(prefix)]
                model_events = [event for event in events
                          if getattr(getattr(event.data, "actor_action", None), "v", None) is not None
                          and event.data.actor_action.v.v == "EventCreateShowItemFromActorFileName"]
                models = [event.data.params.data["Actor"] for event in model_events]
                self.assertEqual([str(value) for value in models], [SHOW_ACTOR_ARGUMENT])
                self.assertTrue(all(set(event.data.params.data) == {"Actor", "IsWaitEnd"}
                                    for event in model_events))
                rotations = [event.data.params.data["ContentName"] for event in events
                             if isinstance(event.data, SubFlowEvent) and event.data.res_flowchart_name == CAMERA_FACING_FLOW]
                self.assertEqual([str(value) for value in rotations], ["ActorName"])
                effects = [event for event in events if isinstance(event.data, SubFlowEvent)
                           and event.data.res_flowchart_name == "GetPouchContent"
                           and event.data.entry_point_name == "AP_KeyEffect"]
                self.assertEqual(len(effects), 1)
                self.assertEqual(str(effects[0].data.params.data["ActorName"]), "ActorName")


if __name__ == "__main__":
    unittest.main()
