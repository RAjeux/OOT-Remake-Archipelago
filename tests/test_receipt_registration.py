"""Receipt registration loads only each generated route and its real callees."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from evfl import EventFlow
from evfl.actor import Actor
from evfl.common import ActorIdentifier
from evfl.entry_point import EntryPoint
from evfl.enums import Version
from evfl.event import SubFlowSwitchEvent
from evfl.flowchart import Flowchart
from evfl.util import make_index
from oot_rando.formats import byml_codec
from oot_rando.game import resource_allocations
from oot_rando.patching import chest_flags, event_info
from oot_rando.patching.progressive import FlowEditor
from ootrr_triforce import receipt_events, presentation_models
from ootrr_triforce.catalog import ITEM_IDS
from ootrr_triforce.native_presentations import PRESENTER_PATH, CAMERA_FACING_FLOW
from test_presented_receipts import native_flow, native_ground_camera, native_presenter, native_facing_animation

PICKUP_SOUND = ("Work/Event/GameEventSoundSetting/IgnoreDuckingOnFlowchart."
                "game__event__GameEventSoundSetting.gyml")
MAJOR_SOUND = ("Work/Event/GameEventSoundSetting/PauseOneShotSEOnFlowchart."
               "game__event__GameEventSoundSetting.gyml")


class IdentityCodec:
    """Keep this test portable: fixture resources are already decoded."""
    def __init__(self, dictionary):
        pass

    def decode(self, data):
        return data

    def encode(self, data, original):
        return data


def byml(root):
    return byml_codec.dump({"root": root, "endian": "<", "version": 7})


def child_flow(name, child_name):
    flow = EventFlow()
    flow.name = name
    flow.flowchart = Flowchart()
    flow.flowchart.name = flow.name
    actor = Actor()
    actor.identifier = ActorIdentifier("GameSystemActor")
    flow.flowchart.actors.append(actor)
    stream = io.BytesIO()
    assert flow.write(stream)
    editor = FlowEditor(stream.getvalue(), "health registration fixture")
    child = editor.action("StartChild", "GameSystemActor", "EventTransition", {"EventName": child_name})
    entry = EntryPoint("Check")
    entry.main_event = make_index(child)
    editor.chart.entry_points.append(entry)
    return editor.write("health registration fixture")[0]


class ReceiptRegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        romfs, mod = Path(cls.temp.name) / "game", Path(cls.temp.name) / "mod"
        info = json.loads((ROOT / "tests/fixtures/pouch-presentation-info.json").read_bytes())["actors"]
        ground = FlowEditor(native_ground_camera(), "ground registration fixture")
        ground.flow.version = Version.V4
        # Native Dm_SY_Get_Camera asks local return-valued subflows such as
        # JudgeCamera/IsCameraHit. Their query graphs also have dependencies.
        camera_entry = next(entry for entry in ground.chart.entry_points if entry.name == "Dm_SY_Get_Camera")
        choose_data = SubFlowSwitchEvent()
        choose_data.entry_point_name = "NativeCameraQuery"
        choose_data.cases = {0: make_index(camera_entry.main_event.v), 1: make_index(None)}
        choose = ground._event("NativeCameraChoice", choose_data, None)
        camera_entry.main_event = make_index(choose)
        camera_query = ground.subflow("NativeCameraQueryCall", "ReceiptCameraFixture", "Check", None)
        entry = EntryPoint("NativeCameraQuery")
        entry.main_event = make_index(camera_query)
        ground.chart.entry_points.append(entry)
        check = ground.subflow("NativeHealth", "ReceiptHealthFixture", "Check", None)
        entry = EntryPoint("CheckHeart")
        entry.main_event = make_index(check)
        ground.chart.entry_points.append(entry)
        cls.camera = {"FixtureNativeCamera": "preserved"}
        resources = {
            "Pack/ZsDic.pack.zs": b"dictionary",
            receipt_events.FLOW_PATH: native_flow(),
            PRESENTER_PATH: native_presenter(),
            event_info.flow_path(CAMERA_FACING_FLOW): native_facing_animation(),
            event_info.flow_path("Dm_SY_Get"): ground.write("ground registration fixture")[0],
            event_info.flow_path("ReceiptHealthFixture"): child_flow("ReceiptHealthFixture", "FixtureChild"),
            event_info.flow_path("ReceiptCameraFixture"): child_flow("ReceiptCameraFixture", "FixtureCameraChild"),
            "RSDB/PouchActorInfo.Product.111.rstbl.byml.zs": byml([
                {"__RowId": actor, **row} for actor, row in info.items()]),
            chest_flags.EVENT_SETTINGS: byml([{
                "__RowId": "Dm_SY_Get", "EntryPointName": "Dm_SY_Get",
                "FlowchartFileName": "Work/Event/EventFlow/Dm_SY_Get.evfc",
                "EventSoundSetting": MAJOR_SOUND,
                "EventSettingComponentList": "FixtureWindmillForcedParticipants"}]),
            chest_flags.ANALYZED: byml([{
                "__RowId": "Dm_SY_Get", "IsPlayerWarpFirstFrame": True,
                "IsPlayerEventStartWithClimb": True, "IsPlayerEventStartWithDrawn": False,
                "RecordedCameraInfo": cls.camera, "SubFlowList": ["FixtureUnrelated"]},
                {"__RowId": "FixtureChild", "ChildEventList": ["FixtureGrandchild"]}]),
            receipt_events.REST: b"resource sizes",
        }
        for relative, raw in resources.items():
            target = romfs / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        names = ["Rupees (5)", "Bombs (5)", "Recovery Heart", "Piece of Heart", "Mirror Shield"]
        build = receipt_events.build_presented_receipts

        def selected(pouch, presenter, token, **kwargs):
            kwargs.pop("names", None)
            return build(pouch, presenter, token, names, **kwargs)

        with patch.object(receipt_events, "Codec", IdentityCodec), \
                patch("ootrr_triforce.mod_codec.Codec", IdentityCodec), \
                patch.object(presentation_models, "prepare_presentation_models") as models, \
                patch.object(receipt_events, "build_presented_receipts", side_effect=selected), \
                patch.object(resource_allocations, "grow_resources", return_value=(b"grown sizes", {})):
            receipt_events.prepare_receipts(romfs, mod, {"token": "c" * 64, "local_items": True})
            models.assert_called_once_with(romfs, mod)
        cls.settings = {row["__RowId"]: row for row in byml_codec.load(
            (mod / chest_flags.EVENT_SETTINGS).read_bytes())["root"]}
        cls.analyzed = {row["__RowId"]: row for row in byml_codec.load(
            (mod / chest_flags.ANALYZED).read_bytes())["root"]}
        cls.ground_raw = resources[event_info.flow_path("Dm_SY_Get")]

    def rows(self, item):
        name = receipt_events.event_name(ITEM_IDS[item])
        settings, analyzed = self.settings[name], self.analyzed[name]
        self.assertEqual(settings["EntryPointName"], name)
        self.assertEqual(settings["FlowchartFileName"], "Work/Event/EventFlow/GetPouchContent.evfc")
        self.assertIs(analyzed["IsPlayerWarpFirstFrame"], False)
        self.assertIs(analyzed["IsPlayerEventStartWithClimb"], True)
        self.assertIs(analyzed["IsPlayerEventStartWithDrawn"], False)
        self.assertNotIn("Windmill", settings["EventSettingComponentList"])
        return settings, analyzed

    def test_pickups_register_only_pouch_without_recorded_camera_or_warp(self):
        for item in ("Rupees (5)", "Bombs (5)", "Recovery Heart"):
            with self.subTest(item=item):
                settings, analyzed = self.rows(item)
                self.assertEqual(analyzed["SubFlowList"], ["GetPouchContent"])
                self.assertNotIn("RecordedCameraInfo", analyzed)
                self.assertNotIn("ChildEventList", analyzed)
                self.assertEqual(settings["EventSoundSetting"], PICKUP_SOUND)
                self.assertIn("FellingInGameFlowchartEvent.", settings["EventSettingComponentList"])

    def test_medium_heart_effect_stays_local_without_unused_camera_or_children(self):
        settings, analyzed = self.rows("Piece of Heart")
        self.assertEqual(set(analyzed["SubFlowList"]), {
            "GetPouchContent", "Dm_SY_GetInEvent"})
        self.assertNotIn("ChildEventList", analyzed)
        self.assertNotIn("RecordedCameraInfo", analyzed)
        self.assertEqual(settings["EventSoundSetting"], PICKUP_SOUND)
        self.assertIn("FellingInGameFlowchartEvent.", settings["EventSettingComponentList"])

    def test_major_loads_authored_facing_helper_without_unused_camera_branches(self):
        settings, analyzed = self.rows("Mirror Shield")
        self.assertEqual(set(analyzed["SubFlowList"]), {
            "GetPouchContent", "Dm_SY_GetInEvent", "Dm_SY_Get", "ReceiptHealthFixture", CAMERA_FACING_FLOW})
        self.assertEqual(set(analyzed["ChildEventList"]), {"FixtureChild", "FixtureGrandchild"})
        self.assertEqual(analyzed["RecordedCameraInfo"], self.camera)
        self.assertEqual(settings["EventSoundSetting"], MAJOR_SOUND)
        self.assertIn("FellingInGameFlowchartWithIgnoreDissentPlay.", settings["EventSettingComponentList"])

    def test_unknown_external_subflow_switch_remains_refused(self):
        editor = FlowEditor(self.ground_raw, "unknown message switch fixture")
        switch = next(event for event in editor.chart.events if isinstance(event.data, SubFlowSwitchEvent))
        switch.data.res_flowchart_name = "EventFlowMsg/Unknown"
        raw = editor.write("unknown message switch fixture")[0]
        calls = event_info.entry_calls(raw, "Dm_SY_Get_Camera")
        self.assertIn(event_info.SWITCH_CALL, calls)
        with self.assertRaisesRegex(ValueError, "message sub-flow switch"):
            event_info.add_subflow_dependencies(byml([]), [], {("Owner", "Main"): calls}, lambda name: raw)


if __name__ == "__main__":
    unittest.main()
