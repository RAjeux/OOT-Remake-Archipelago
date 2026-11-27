"""Shared pickup hooks keep ordinary chest, shop and NPC event preloads complete."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from evfl.entry_point import EntryPoint
from evfl.enums import Version
from evfl.event import SubFlowSwitchEvent
from evfl.util import make_index
from oot_rando.formats import byml_codec
from oot_rando.game.resource_allocations import allocation
from oot_rando.patching import event_info
from oot_rando.patching.progressive import FlowEditor
from ootrr_triforce import ap_skulls
from ootrr_triforce.catalog import AP_SKULL_CHECKS
from test_receipt_registration import IdentityCodec, byml
from test_resource_allocations import table
from test_restoration import reward
from test_skull_events import native_flow, ground_flow


def pouch():
    editor = FlowEditor(native_flow(), "native shared pickup dependencies")
    editor.flow.version = Version.V4
    get = next(point for point in editor.chart.entry_points if point.name == "GetPouchContent")
    native = get.main_event.v
    dynamic = SubFlowSwitchEvent()
    dynamic.res_flowchart_name = "EventFlowMsg/NativeMessage"
    dynamic.entry_point_name = "MessageChoice"
    dynamic.cases = {0: make_index(native)}
    unknown = editor._event("NativeMessageDispatch", dynamic, None)
    choose = editor.switch("NativeCondition", "GameDataActor", "EventQueryIsGameDataBool",
                           {"GameDataName": "NativeMessage", "Index": -1}, native, unknown)
    chest = editor.subflow("NativeChestGet", "", "GetPouchContent", None)
    choose.data.cases[0] = make_index(chest)
    point = EntryPoint("GetPouchContentByActorNameForTreasureBox")
    point.main_event = make_index(choose)
    editor.chart.entry_points.append(point)
    return editor.write("native shared pickup dependencies")[0]


def trap():
    editor = FlowEditor(native_flow(), "native trap")
    editor.chart.name = editor.flow.name = "Dm_SY_GetInEvent"
    editor.chart.entry_points.clear()
    action = editor.action("Freeze", "GameSystemActor", "FixtureIceTrap", None)
    point = EntryPoint("AP_IceTrap")
    point.main_event = make_index(action)
    editor.chart.entry_points.append(point)
    return editor.write("native trap")[0]


class PickupDependencyTests(unittest.TestCase):
    def prepare(self, item="Ice Trap", missing_trap=False):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        romfs, mod = Path(directory.name) / "game", Path(directory.name) / "mod"
        settings, info = [], []
        for name in ("ForeignChest", "NativeChest", "Shop", "Npc", "Pickup"):
            settings.append(dict(__RowId=name, FlowchartFileName="Work/Event/EventFlow/" + name + ".evfc",
                                 EntryPointName="Main"))
            info.append(dict(__RowId=name, SubFlowList=["GetPouchContent", "NativeMessage"],
                             ChildEventList=["NativeChild"], NativeMetadata={"preserved": True}))
        settings.append(dict(__RowId="SharedGet", FlowchartFileName="Work/Event/EventFlow/GetPouchContent.evfc",
                             EntryPointName="GetPouchContentByActorNameForTreasureBox"))
        info.append(dict(__RowId="SharedGet", SubFlowList=["NativeMessage"]))
        settings.append(dict(__RowId="SharedQuiet", FlowchartFileName="Work/Event/EventFlow/GetPouchContent.evfc",
                             EntryPointName="OpenGetWindow"))
        info.append(dict(__RowId="SharedQuiet", SubFlowList=["GetPouchContent"]))
        info.append(dict(__RowId="Unrelated", SubFlowList=["NativeMessage"]))
        baseline = copy.deepcopy(info)
        resources = {"Pack/ZsDic.pack.zs": b"dictionary", ap_skulls.FLOW_PATH: pouch(),
                     ap_skulls.SETTINGS: byml(settings), ap_skulls.ANALYZED: byml(info)}
        resources.update({event_info.flow_path(name): ground_flow(name) for name in ap_skulls.PICKUP_FLOWS})
        if not missing_trap:
            resources[event_info.flow_path("Dm_SY_GetInEvent")] = trap()
        resources[ap_skulls.REST] = table([(path.removesuffix(".zs"), len(raw) + 4096)
                                         for path, raw in resources.items() if path.endswith(".zs")])
        for path, raw in resources.items():
            target = romfs / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        records = ap_skulls.skull_records({sorted(AP_SKULL_CHECKS)[0]: reward(item)})
        with patch.object(ap_skulls, "Codec", IdentityCodec):
            if missing_trap:
                with self.assertRaises(FileNotFoundError):
                    ap_skulls.prepare_pickup_callbacks(romfs, mod, records)
                self.assertFalse(mod.exists(), "an incomplete event graph must not be installed")
                return
            report = ap_skulls.prepare_pickup_callbacks(romfs, mod, records)
        return romfs, mod, baseline, report, resources

    def test_trap_branch_preloads_for_all_existing_callers_without_changing_native_metadata(self):
        romfs, mod, baseline, report, resources = self.prepare()
        rows = byml_codec.load((mod / ap_skulls.ANALYZED).read_bytes())["root"]
        self.assertEqual(report["preloads"], 6)
        self.assertEqual(report["child_events"], 0)
        for before, after in zip(baseline, rows):
            expected = copy.deepcopy(before)
            if before["__RowId"] not in {"Unrelated", "SharedQuiet"}:
                expected["SubFlowList"] = sorted(before["SubFlowList"] + ["Dm_SY_GetInEvent"], key=str.lower)
            self.assertEqual(after, expected)
        raw = (mod / ap_skulls.FLOW_PATH).read_bytes()
        self.assertIn(event_info.SWITCH_CALL, event_info.entry_calls(raw, "GetPouchContentByActorNameForTreasureBox"))
        self.assertIn(("Dm_SY_GetInEvent", "AP_IceTrap"), event_info.entry_calls(raw, "GetPouchContent"))
        self.assertEqual((romfs / ap_skulls.ANALYZED).read_bytes(), resources[ap_skulls.ANALYZED])
        rst = (mod / ap_skulls.REST).read_bytes()
        self.assertGreaterEqual(allocation(rst, ap_skulls.ANALYZED.removesuffix(".zs")),
                                allocation(resources[ap_skulls.REST], ap_skulls.ANALYZED.removesuffix(".zs")))
        # Applying the same metadata completion again must preserve exact bytes.
        flows = {event_info.flow_name(path): (mod / path).read_bytes()
                 for path in [ap_skulls.FLOW_PATH, *map(event_info.flow_path, ap_skulls.PICKUP_FLOWS)]}
        original = lambda name: resources[event_info.flow_path(name)]
        current = lambda name: flows[name] if name in flows else original(name)
        result = event_info.add_subflow_dependencies((mod / ap_skulls.ANALYZED).read_bytes(),
            byml_codec.load(resources[ap_skulls.SETTINGS])["root"], event_info.new_subflows(flows, original), current)
        self.assertEqual(result, ((mod / ap_skulls.ANALYZED).read_bytes(), {}))

    def test_ordinary_reward_does_not_add_unused_trap_preloads(self):
        _, mod, _, report, resources = self.prepare("Rupees (5)")
        self.assertEqual(report["preloads"], 0)
        self.assertFalse((mod / ap_skulls.ANALYZED).exists())
        self.assertNotIn(("Dm_SY_GetInEvent", "AP_IceTrap"), event_info.entry_calls(
            (mod / ap_skulls.FLOW_PATH).read_bytes(), "GetPouchContent"))

    def test_missing_new_dependency_fails_before_any_resources_are_written(self):
        self.prepare(missing_trap=True)

    def test_new_children_use_exact_owner_entry_but_propagate_to_external_callers(self):
        settings = [dict(__RowId=name, FlowchartFileName="Work/Event/EventFlow/GetPouchContent.evfc",
                         EntryPointName=entry) for name, entry in
                    (("Get", "GetPouchContent"), ("Quiet", "OpenGetWindow"))]
        rows = [dict(__RowId=name, SubFlowList=["GetPouchContent"]) for name in ("Get", "Quiet", "External")]
        rows.append(dict(__RowId="NewChild", ChildEventList=[]))
        raw, report = event_info.add_child_events(byml(rows), settings,
            {("GetPouchContent", "GetPouchContent"): {"NewChild"}}, lambda name: pouch())
        result = {row["__RowId"]: row for row in byml_codec.load(raw)["root"]}
        self.assertEqual(set(report), {"Get", "External"})
        self.assertEqual(result["Quiet"], rows[1])
        self.assertEqual(result["Get"]["ChildEventList"], ["NewChild"])
        self.assertEqual(result["External"]["ChildEventList"], ["NewChild"])


if __name__ == "__main__":
    unittest.main()
