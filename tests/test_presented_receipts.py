"""Native V2 item scenes keep their model/sound branch and commit one effect."""
from collections import Counter
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
from ootrr_triforce.catalog import ITEM_DATA, ITEM_IDS
from ootrr_triforce.native_presentations import PRESENTER_ENTRY, PRESENTER_NAME, is_cure
from ootrr_triforce.receipt_events import CURSOR_PREFIX, OWNERS, build_presented_receipts, event_name
from test_receipt_events import native_flow

TOKEN = "b" * 64
CURSOR = CURSOR_PREFIX + TOKEN


def native_presenter():
    flow = EventFlow()
    flow.name = PRESENTER_NAME
    flow.flowchart = Flowchart()
    flow.flowchart.name = flow.name
    for name in ("GameSystemActor", "SoundSystemActor", "EventCamera"):
        actor = Actor()
        actor.identifier = ActorIdentifier(name)
        flow.flowchart.actors.append(actor)
    stream = io.BytesIO()
    assert flow.write(stream)
    editor = FlowEditor(stream.getvalue(), "authored native presenter")
    saved = editor.action("NativeCameraSave", "EventCamera", "EventTriggerCameraSavePoint", None)
    snap = editor.action("NativeNpcSnap", "EventCamera", "EventMoveToTargetPosCamera", {"MoveTime": 0, "IsWaitEnd": True})
    model = editor.action("NativeModel", "GameSystemActor", "FixtureNativeModel",
                          {"ActorName": Argument("ActorName")})
    major = editor.action("ImportantFanfare", "SoundSystemActor", "FixtureNativeSound", {"Sound": "native-important"})
    minor = editor.action("MinorFanfare", "SoundSystemActor", "FixtureNativeSound", {"Sound": "native-minor"})
    choose = editor.switch("NativeImportance", "PouchSystemActor", "FixtureIsImportant",
                           {"ActorName": Argument("ActorName")}, major, minor)
    give = editor.subflow("NativeCallback", "GetPouchContent", "GetPouchContentByActorName_ForGetInEvent",
                         {"ActorName": Argument("ActorName")})
    heart = editor.subflow("NativeHeart", "Dm_SY_Get", "CheckHeart", {"ActorName": Argument("ActorName")})
    clean = editor.action("NativeCleanup", "GameSystemActor", "FixtureCleanup", None)
    snap_back = editor.action("NativeNpcSnapBack", "EventCamera", "EventMoveCameraToSavePoint", {"MoveFrame": 0, "IsWaitEnd": True})
    for current, following in ((saved, snap), (snap, model), (model, choose), (major, give), (minor, give),
                               (give, heart), (heart, snap_back), (snap_back, clean)):
        link(current, following)
    entry = EntryPoint(PRESENTER_ENTRY)
    entry.main_event = make_index(saved)
    editor.chart.entry_points.append(entry)
    return editor.write("authored native presenter")[0]


def native_ground_camera():
    """Authored camera path with the parameters observed in native Dm_SY_Get."""
    flow = EventFlow()
    flow.name = "Dm_SY_Get"
    flow.flowchart = Flowchart()
    flow.flowchart.name = flow.name
    for name in ("EventCamera", "PlayerCamera", "GameSystemActor"):
        actor = Actor()
        actor.identifier = ActorIdentifier(name)
        flow.flowchart.actors.append(actor)
    stream = io.BytesIO()
    assert flow.write(stream)
    editor = FlowEditor(stream.getvalue(), "authored native ground camera")
    move = editor.action("GroundCameraMove", "EventCamera", "EventBasedOnLookAtCamera",
                         {"MoveTime": 15, "IsWaitEnd": True})
    keep = editor.action("GroundCameraKeep", "PlayerCamera", "EventTriggerSendKeepStateMessageToPlayerCamera",
                         {"AfterKeepEndInterpolateCountScale": 1.0, "ChangeToManualModeAfterEvent": False,
                          "KeepManualModeFrame": 120.0, "IsKeepWithRelativePos": True})
    for name, node in (("Dm_SY_Get_Camera", move), ("GroundCameraCleanup", keep)):
        entry = EntryPoint(name)
        entry.main_event = make_index(node)
        editor.chart.entry_points.append(entry)
    return editor.write("authored native ground camera")[0]


class SceneRun:
    def __init__(self, charts, *, important=True, owned=None, native_info=None):
        self.entries = {name: {entry.name: entry.main_event.v for entry in chart.entry_points}
                        for name, chart in charts.items()}
        self.important = important
        self.owned = owned if owned is not None else set()
        self.trace = []
        self.calls = []
        self.actions = []
        self.native_info = native_info or {}

    def run(self, flow, entry, args=None):
        node, args = self.entries[flow][entry], args or {}
        steps = 0
        while node is not None:
            steps += 1
            assert steps < 1000, "Native receipt scene loops"
            data = node.data
            params = {key: args[value] if isinstance(value, Argument) else value
                      for key, value in (data.params.data.items() if data.params else ())}
            if isinstance(data, ActionEvent):
                command = data.actor_action.v.v
                self.actions.append((str(data.actor.v.identifier), command, params))
                self.trace.append((command, params))
                if command == "EventTriggerAddOrRemovePouchContent":
                    assert params["Num"] == 1
                    self.owned.add(OWNERS.get(params["Actor"], params["Actor"]))
                node = data.nxt.v
            elif isinstance(data, SwitchEvent):
                query = data.actor_query.v.v
                if query == "FixtureIsImportant":
                    result = self.important
                elif query == "EventQueryCheckIsGet":
                    result = params["ActorName"] in self.owned
                elif query == "EventQueryIsGameDataBool":
                    assert params["GameDataName"] == "Fixture.NativeHookEnabled"
                    result = True
                else:
                    raise AssertionError("Unexpected native receipt query: " + query)
                branch = data.cases.get(0 if result else 1)
                node = branch.v if branch else None
            elif isinstance(data, SubFlowEvent):
                target = data.res_flowchart_name or flow
                name = data.entry_point_name
                self.calls.append((target, name, params))
                if target == "GetPouchContent" and name == "DisplayGetByActorName":
                    self.trace.append(("FixtureItemWindow", params))
                elif target == "Dm_SY_Get" and name == "CheckHeart":
                    self.trace.append(("FixtureCheckHeart", params))
                elif target == "GetPouchContent" and name in ("OpenRupeeUIIfNeed", "CloseRupeeUIIfNeed"):
                    self.assert_rupee_ui(name, params)
                else:
                    self.run(target, name, params)
                node = data.nxt.v
            else:
                raise AssertionError("Unexpected native receipt node: " + type(data).__name__)
        return self.trace

    def assert_rupee_ui(self, entry, params):
        if params.get("IsShowNumDisplay") and self.native_info.get(params.get("ActorName"), {}).get("PouchCategory") == "Rupee":
            self.trace.append(("FixtureRupeeOpen" if entry.startswith("Open") else "FixtureRupeeClose", params))


class PresentedReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pouch = native_flow()
        cls.presenter = native_presenter()
        pouch, presenter, cls.receipts = build_presented_receipts(cls.pouch, cls.presenter, TOKEN)
        cls.charts = {}
        for name, raw in (("GetPouchContent", pouch), (PRESENTER_NAME, presenter)):
            flow = EventFlow()
            flow.read(raw)
            cls.charts[name] = flow.flowchart

    def check_scene(self, name, important=True, owned=None):
        run = SceneRun(self.charts, important=important, owned=owned)
        trace = run.run("GetPouchContent", event_name(ITEM_IDS[name]))
        self.assertFalse(any(entry in {"OpenRupeeUIIfNeed", "CloseRupeeUIIfNeed"}
                             for flow, entry, params in run.calls))
        commands = Counter(command for command, params in trace)
        ack = [index for index, (command, params) in enumerate(trace)
               if command == "EventTriggerAddOrSubGameDataInt" and params["GameDataName"] == CURSOR]
        self.assertEqual(len(ack), 1)
        self.assertEqual(trace[ack[0]][1]["Value"], 1)
        self.assertEqual(commands["FixtureNativeModel"], 1)
        self.assertEqual(commands["FixtureNativeSound"], 1)
        self.assertEqual(commands["FixtureItemWindow"], 1)
        sound = next(params["Sound"] for command, params in trace if command == "FixtureNativeSound")
        self.assertEqual(sound, "native-important" if important else "native-minor")
        self.assertEqual(commands["FixtureCheckHeart"], int(not is_cure(ITEM_DATA[name])))
        effects = {"EventTriggerAddOrRemovePouchContent", "EventTriggerRecoverByCureItem",
                   "EventTriggerPushToEmptyBottle", "EventGetDungeonSmallKey", "EventGetDungeonBossKey",
                   "EventGetDungeonCompass", "EventGetDungeonMap"}
        self.assertTrue(all(index < ack[0] for index, (command, params) in enumerate(trace) if command in effects))
        self.assertTrue(all(index > ack[0] for index, (command, params) in enumerate(trace)
                            if command in {"FixtureCheckHeart", "FixtureCleanup", "EventTriggerRequestAutoSave"}))
        self.assertEqual(trace[-1][0], "EventTriggerRequestAutoSave")
        return trace

    def test_every_receipt_keeps_native_model_and_both_sound_branches(self):
        self.assertEqual(set(self.receipts), set(ITEM_IDS.values()))
        for name in ITEM_DATA:
            for important in (False, True):
                with self.subTest(item=name, important=important):
                    self.check_scene(name, important)

    def test_cures_and_bottle_refills_are_one_effect_with_typed_parameters(self):
        for name, metadata in ITEM_DATA.items():
            if is_cure(metadata):
                trace = self.check_scene(name)
                self.assertEqual(sum(command == "EventTriggerRecoverByCureItem" for command, params in trace), 1)
                self.assertFalse(any(command == "EventTriggerAddOrRemovePouchContent" for command, params in trace))
            elif metadata.get("bottle_item") and metadata.get("pouch_special") == "NotPushToPouch":
                trace = self.check_scene(name)
                refills = [params for command, params in trace if command == "EventTriggerPushToEmptyBottle"]
                self.assertEqual(len(refills), 1)
                self.assertIs(type(refills[0]["Item"]), int)
                self.assertFalse(refills[0]["IsPushToSelectedBottle"])
                self.assertFalse(any(command == "EventTriggerAddOrRemovePouchContent" for command, params in trace))

    def test_progressive_scene_model_follows_the_next_owned_tier(self):
        for name, metadata in ITEM_DATA.items():
            if metadata["mode"] != "tiers":
                continue
            for index, tier in enumerate(metadata["tiers"]):
                trace = self.check_scene(name, owned={OWNERS.get(tier, tier)})
                expected = metadata["tiers"][min(index + 1, len(metadata["tiers"]) - 1)]
                shown = [params["ActorName"] for command, params in trace if command == "FixtureNativeModel"]
                grants = [params["Actor"] for command, params in trace if command == "EventTriggerAddOrRemovePouchContent"]
                self.assertEqual(shown, [expected])
                self.assertEqual(grants, shown)


class GroundStyleReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native_info = json.loads((ROOT / "tests/fixtures/pouch-presentation-info.json").read_bytes())["actors"]
        cls.names = list(ITEM_DATA)
        cls.ground_raw = native_ground_camera()
        pouch, presenter, cls.receipts = build_presented_receipts(
            native_flow(), native_presenter(), TOKEN, cls.names,
            native_info=cls.native_info, ground_raw=cls.ground_raw)
        cls.charts = {}
        for name, raw in (("GetPouchContent", pouch), (PRESENTER_NAME, presenter), ("Dm_SY_Get", cls.ground_raw)):
            flow = EventFlow()
            flow.read(raw)
            cls.charts[name] = flow.flowchart

    def execute(self, name, *, important=True):
        run = SceneRun(self.charts, native_info=self.native_info, important=important)
        run.run("GetPouchContent", event_name(ITEM_IDS[name]))
        ack = [index for index, (command, params) in enumerate(run.trace)
               if command == "EventTriggerAddOrSubGameDataInt" and params["GameDataName"] == CURSOR]
        self.assertEqual(len(ack), 1)
        self.assertFalse(any(entry in {"OpenRupeeUIIfNeed", "CloseRupeeUIIfNeed"}
                             for flow, entry, params in run.calls))
        self.assertFalse(any(command in {"EventOpenRupeeDisplay", "EventCloseRupeeDisplay"}
                             for command, params in run.trace))
        return run, ack[0]

    def test_all_rupees_keep_only_centered_pickup_without_get_scene_or_camera(self):
        for name in ("Rupee (1)", "Rupees (5)", "Rupees (20)", "Rupees (50)", "Rupees (200)"):
            with self.subTest(item=name):
                row = self.native_info[ITEM_DATA[name]["actor"]]
                # Gold's native Medium pose is intentionally overridden by the
                # user's request for a centered pickup counter for every rupee.
                self.assertEqual((row["PouchGetType"], row["PouchCategory"]),
                                 ("Medium" if name == "Rupees (200)" else "Small", "Rupee"))
                run, ack = self.execute(name)
                commands = [command for command, params in run.trace]
                self.assertFalse(any(flow == PRESENTER_NAME for flow, entry, params in run.calls))
                self.assertFalse(any("Camera" in command or command == "FixtureNativeModel" for command in commands))
                self.assertNotIn("FixtureItemWindow", commands)
                grants = [(index, params) for index, (command, params) in enumerate(run.trace)
                          if command == "EventTriggerAddOrRemovePouchContent"]
                self.assertEqual(len(grants), 1)
                self.assertEqual(grants[0][1]["Actor"], ITEM_DATA[name]["actor"])
                self.assertEqual(grants[0][1]["Num"], 1)
                self.assertIs(grants[0][1]["IsGetEvent"], False)
                self.assertLess(grants[0][0], ack)
                self.assertFalse(any("Wait" in command or "Camera" in command
                                     for command, params in run.trace[grants[0][0] + 1:ack]))
                pickup = [index for index, (command, params) in enumerate(run.trace)
                          if command == "EventTriggerRequestOpenPickUpWindow"]
                self.assertEqual(len(pickup), 1)
                self.assertGreater(pickup[0], ack)
                pickup_args = [params for flow, entry, params in run.calls if "IsGetInEvent" in params]
                self.assertTrue(any(params["IsGetInEvent"] is False and params.get("IsShowNumDisplay") is True
                                    for params in pickup_args))
                self.assert_pickup_ui_only(run, ack)
                # Native UI_PickUp_00 owns the centered pickup/counting SLink
                # sounds; a second shop counter or fanfare would duplicate it.
                self.assertFalse(any(actor == "SoundSystemActor" for actor, command, params in run.actions))

    def assert_pickup_ui_only(self, run, ack):
        self.assertFalse(any(entry in {"OpenRupeeUIIfNeed", "CloseRupeeUIIfNeed"}
                             for flow, entry, params in run.calls))
        commands = [command for command, params in run.trace]
        self.assertFalse(set(commands) & {"FixtureRupeeOpen", "FixtureRupeeClose",
                                         "EventOpenRupeeDisplay", "EventCloseRupeeDisplay"})
        self.assertFalse(any("HUD" in command.upper() for command in commands))
        self.assertFalse(any("ModeShop" in str(value)
                             for actor, command, params in run.actions for value in params.values()))
        ui = [command for actor, command, params in run.actions if actor == "UISystemActor"]
        self.assertTrue(all(command == "EventTriggerRequestOpenPickUpWindow" for command in ui))
        save = [index for index, (command, params) in enumerate(run.trace)
                if command == "EventTriggerRequestAutoSave"]
        self.assertEqual(len(save), 1)
        self.assertGreater(save[0], ack)
        for index, (command, params) in enumerate(run.trace):
            if command == "EventTriggerRequestOpenPickUpWindow":
                self.assertGreater(index, ack)
                self.assertLess(index, save[0])

    def test_small_ammunition_and_cure_avoid_important_item_presentation(self):
        for name in ("Bombs (5)", "Recovery Heart"):
            run, ack = self.execute(name)
            self.assertFalse(any(flow == PRESENTER_NAME for flow, entry, params in run.calls))
            self.assertFalse(any("Camera" in command or command == "FixtureNativeModel" for command, params in run.trace))
            expected = "EventTriggerRecoverByCureItem" if name == "Recovery Heart" else "EventTriggerAddOrRemovePouchContent"
            self.assertEqual(sum(command == expected for command, params in run.trace), 1)
            self.assert_pickup_ui_only(run, ack)
            if name == "Bombs (5)":
                self.assertEqual(sum(command == "EventTriggerRequestOpenPickUpWindow" for command, params in run.trace), 1)
            else:
                self.assertIs(self.native_info[ITEM_DATA[name]["actor"]]["IsNotOpenStockNumDisplay"], True)
                self.assertFalse(any(command == "EventTriggerRequestOpenPickUpWindow" for command, params in run.trace))
            self.assertFalse(any(actor == "SoundSystemActor" for actor, command, params in run.actions))

    def test_major_item_uses_native_ground_camera_and_cleanup_without_snap(self):
        for name in ("Mirror Shield", "Progressive Hookshot"):
            with self.subTest(item=name):
                run, ack = self.execute(name)
                commands = [command for command, params in run.trace]
                self.assertIn("FixtureNativeModel", commands)
                self.assertIn("FixtureNativeSound", commands)
                self.assertNotIn("EventMoveToTargetPosCamera", commands)
                self.assertNotIn("EventMoveCameraToSavePoint", commands)
                movements = [params for command, params in run.trace if command == "EventBasedOnLookAtCamera"]
                self.assertEqual(movements, [{"MoveTime": 15, "IsWaitEnd": True}])
                keep = [params for command, params in run.trace if command == "EventTriggerSendKeepStateMessageToPlayerCamera"]
                self.assertEqual(keep, [{"AfterKeepEndInterpolateCountScale": 1.0, "ChangeToManualModeAfterEvent": False,
                                         "KeepManualModeFrame": 120.0, "IsKeepWithRelativePos": True}])
                self.assertLess(commands.index("EventBasedOnLookAtCamera"), commands.index("FixtureNativeModel"))
                self.assertGreater(commands.index("EventTriggerSendKeepStateMessageToPlayerCamera"), ack)

    def test_all_routes_avoid_shop_counter_and_native_key_specials_keep_presentation(self):
        for name in ITEM_DATA:
            with self.subTest(no_shop_counter=name):
                self.execute(name)
        for name in ("Ocarina", "Sarias Song", "Piece of Heart", "Gold Skulltula Token"):
            with self.subTest(item=name):
                run, ack = self.execute(name)
                self.assertTrue(any(flow == PRESENTER_NAME for flow, entry, params in run.calls))
                self.assertEqual(sum(command == "FixtureNativeModel" for command, params in run.trace), 1)

    def test_medium_ground_items_keep_the_short_pose_without_camera(self):
        for name in ("Piece of Heart", "Gold Skulltula Token", "Bombchus (5)"):
            with self.subTest(item=name):
                run, ack = self.execute(name, important=False)
                self.assertTrue(any(flow == PRESENTER_NAME for flow, entry, params in run.calls))
                self.assertEqual(sum(command == "FixtureNativeModel" for command, params in run.trace), 1)
                self.assertFalse(any("Camera" in command for command, params in run.trace))
                sounds = [params["Sound"] for command, params in run.trace if command == "FixtureNativeSound"]
                self.assertEqual(sounds, ["native-minor"])


if __name__ == "__main__":
    unittest.main()
