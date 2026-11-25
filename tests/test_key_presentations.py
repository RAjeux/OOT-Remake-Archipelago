"""Dungeon keys use the native spinning model without changing their effect."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from evfl.event import SubFlowEvent
from evfl.util import make_rindex
from oot_rando.patching.progressive import FlowEditor
from ootrr_triforce.catalog import ITEM_DATA, ITEM_IDS
from ootrr_triforce.native_presentations import (PRESENTER_NAME, PRESENTER_ENTRY, CAMERA_FACING_FLOW,
                                                CAMERA_FACING_ENTRY, SMALL_KEY_MODEL, copy_receipt_presenter)
from ootrr_triforce.receipt_events import build_presented_receipts, event_name
from ootrr_triforce.presentation_models import SHOW_ACTOR_ARGUMENT, model_actor
from test_presented_receipts import native_presenter, native_facing_animation, SceneRun, TOKEN, CURSOR
from test_receipt_events import native_flow


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
                self.assertEqual(windows, [ITEM_DATA[name]["actor"]])
                credits = [params["GameDataName"] for action, params in run.trace
                           if action in {"EventTriggerSetGameDataBool", "EventTriggerAddOrSubGameDataInt"}]
                self.assertNotIn("MiniGame_SmallKeyNum", credits)
                if small:
                    dungeon = "ForestTemple" if "Forest" in name else "GerudoFortress"
                    self.assertIn("DungeonInfo." + dungeon + ".SmallKeyNum", credits)
                    self.assertIn("DungeonInfo." + dungeon + ".SmallKeyTotalNum", credits)
                self.assertEqual(credits.count(CURSOR), 1)


@unittest.skipUnless(os.environ.get("OOTRR_ROMFS"), "requires native v1.1.1 presentation assets")
class NativeKeyPresentationTests(unittest.TestCase):
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
