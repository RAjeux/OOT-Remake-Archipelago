"""Flow analysis caches live for one preparation and never change dependency results."""
from concurrent.futures import ThreadPoolExecutor
import copy
import gc
import io
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
import weakref

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from evfl import EventFlow
from evfl.entry_point import EntryPoint
from evfl.enums import Version
from evfl.event import SubFlowEvent
from evfl.flowchart import Flowchart
from evfl.util import make_index
from oot_rando.patching import event_info, event_patch
from oot_rando.patching.progressive import FlowEditor
from oot_rando.formats import byml_codec
from ootrr_triforce import ap_skulls, restoration
from ootrr_triforce.catalog import AP_SKULL_CHECKS, LOCATION_IDS
from test_restoration import reward, pouch
from test_skull_events import native_flow, ground_flow


def fixture(child="Child_A", entries=2, version=Version.V3):
    flow = EventFlow()
    flow.name = "Owner"
    flow.version = version
    flow.flowchart = Flowchart()
    flow.flowchart.name = flow.name
    stream = io.BytesIO()
    assert flow.write(stream)
    editor = FlowEditor(stream.getvalue(), "Dependency fixture")
    call = editor.subflow("Call", child, "Main", None)
    transition = editor.action("Transition", "GameDataActor", "EventTransition", {"EventName": "ChildEvent"})
    call.data.nxt = make_index(transition)
    for number in range(entries):
        point = EntryPoint("Entry" + str(number))
        point.main_event = make_index(call)
        editor.chart.entry_points.append(point)
    return editor.write("Dependency fixture")[0]


class AnalysisCacheTests(unittest.TestCase):
    def test_same_bytes_parse_once_inside_scope_but_not_across_preparations(self):
        raw = fixture()
        original = event_patch._flow
        with patch.object(event_patch, "_flow", wraps=original) as parser:
            event_info.entry_calls(raw, "Entry0")
            event_info.entry_calls(raw, "Entry1")
            self.assertEqual(parser.call_count, 2)
            with event_info.analysis_scope():
                for _ in range(5):
                    self.assertEqual(event_info.entry_calls(raw, "Entry0"), {("Child_A", "Main")})
                    self.assertEqual(event_info.entry_transitions(raw, "Entry1"), {"ChildEvent"})
                    self.assertEqual(event_info.event_calls(raw, "Call"), {("Child_A", "Main")})
                    self.assertEqual(event_info.entry_names(raw), ["Entry0", "Entry1"])
                self.assertEqual(parser.call_count, 3)
            self.assertIsNone(event_info._analysis_cache.get())
            with event_info.analysis_scope():
                event_info.entry_calls(raw, "Entry0")
            self.assertEqual(parser.call_count, 4)

    def test_content_and_version_changes_and_mutable_buffers_cannot_reuse_stale_graphs(self):
        a, b, v4 = fixture("Child_A"), fixture("Child_B"), fixture("Child_A", version=Version.V4)
        mutable = bytearray(a)
        with patch.object(event_patch, "_flow", wraps=event_patch._flow) as parser, event_info.analysis_scope():
            self.assertEqual(event_info.entry_calls(mutable, "Entry0"), {("Child_A", "Main")})
            mutable[:] = b
            self.assertEqual(event_info.entry_calls(mutable, "Entry0"), {("Child_B", "Main")})
            self.assertEqual(event_info.entry_calls(bytes(bytearray(a)), "Entry1"), {("Child_A", "Main")})
            self.assertEqual(parser.call_count, 2)
            self.assertEqual(event_info.entry_calls(v4, "Entry0"), {("Child_A", "Main")})
            self.assertEqual(parser.call_count, 3)
            result = event_info.entry_calls(a, "Entry0")
            result.clear()
            self.assertEqual(event_info.entry_calls(a, "Entry0"), {("Child_A", "Main")})

    def test_nested_scope_exception_and_context_exit_release_their_graphs(self):
        raw = fixture()
        with event_info.analysis_scope():
            outer = event_info._chart(raw)
            outer_cache = event_info._analysis_cache.get()
            with self.assertRaisesRegex(RuntimeError, "expected"):
                with event_info.analysis_scope():
                    inner = event_info._chart(raw)
                    self.assertIsNot(inner, outer)
                    inner_ref = weakref.ref(inner)
                    inner_cache = event_info._analysis_cache.get()
                    del inner
                    raise RuntimeError("expected")
            self.assertEqual(inner_cache, {})
            gc.collect()
            self.assertIsNone(inner_ref())
            self.assertIs(event_info._analysis_cache.get(), outer_cache)
            self.assertIs(event_info._chart(raw), outer)
        self.assertEqual(outer_cache, {})
        self.assertIsNone(event_info._analysis_cache.get())

    def test_threads_analyze_in_independent_scopes(self):
        raw = fixture()
        barrier = threading.Barrier(2)
        original, parsed_threads, guard = event_patch._flow, [], threading.Lock()
        def counted(data):
            with guard:
                parsed_threads.append(threading.get_ident())
            return original(data)
        def work(_):
            with event_info.analysis_scope():
                for _ in range(4):
                    event_info.entry_calls(raw, "Entry0")
                chart_id = id(event_info._chart(raw))
                barrier.wait(timeout=10)
            self.assertIsNone(event_info._analysis_cache.get())
            return chart_id
        with patch.object(event_patch, "_flow", side_effect=counted), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(work, range(2)))
        self.assertEqual(len(parsed_threads), 2)
        self.assertEqual(len(set(parsed_threads)), 2)
        self.assertNotEqual(results[0], results[1])

    def test_restoration_registration_bytes_and_dependencies_match_uncached_analysis(self):
        roster = {name: reward(local=index % 2 == 0) for index, name in enumerate(list(restoration.CHESTS)[:8])}
        raw, entries = restoration.build_restoration_flow(pouch(), roster)
        def document(rows):
            return byml_codec.dump({"root": rows, "version": 7, "endian": "<"})
        resources = {
            "RSDB/EventSetting.Product.111.rstbl.byml.zs": document([{"__RowId": "Dm_SY_Get", "EntryPointName": "Dm_SY_Get",
                "FlowchartFileName": "Work/Event/EventFlow/Dm_SY_Get.evfc", "NativeMetadata": True}]),
            "RSDB/GameAnalyzedEventInfo.Product.111.rstbl.byml.zs": document([{"__RowId": "Dm_SY_Get", "SubFlowList": []}]),
        }
        cached, reference = {restoration.FLOW_PATH: raw}, {restoration.FLOW_PATH: raw}
        with patch.object(event_patch, "_flow", wraps=event_patch._flow) as parser:
            restoration._register_restorations(cached, entries, resources.__getitem__)
            self.assertEqual(parser.call_count, 1)
        restoration._register_restorations.__wrapped__(reference, entries, resources.__getitem__)
        self.assertEqual(cached, reference)
        self.assertIsNone(event_info._analysis_cache.get())

    def test_optimized_preload_lists_keep_the_original_serialized_order(self):
        location = sorted(AP_SKULL_CHECKS)[0]
        records = ap_skulls.skull_records({location: reward("Bow")})
        source = native_flow()
        patched, effects = ap_skulls.patch_skull_flow(source, records, return_entries=True)
        for raw, original, chart_order in [(patched, source, True),
                *[(ap_skulls.patch_pickup_presentation(ground_flow(name), records, effects, name), ground_flow(name), False)
                  for name in ap_skulls.PICKUP_FLOWS]]:
            editor = FlowEditor(raw, "Preload reference")
            baseline = {point.name: list(point._sub_flow_event_indices)
                        for point in FlowEditor(original, "Native preload reference").chart.entry_points}
            for point in editor.chart.entry_points:
                point._sub_flow_event_indices = baseline.get(point.name, [])
                reached = event_info.reachable(point.main_event.v)
                candidates = editor.chart.events if chart_order else reached
                for event in candidates:
                    if (event.name.startswith(ap_skulls.PREFIX) and isinstance(event.data, SubFlowEvent)
                            and (not chart_order or event in reached)):
                        index = editor.chart.events.index(event)
                        if index not in point._sub_flow_event_indices:
                            point._sub_flow_event_indices.append(index)
            self.assertEqual(editor.write("Original preload algorithm")[0], raw)


@unittest.skipUnless(os.environ.get("OOTRR_ROMFS"), "requires private native v1.1.1 event flows")
class NativeAnalysisCacheTests(unittest.TestCase):
    def test_native_dependency_results_are_identical_and_each_chart_is_parsed_once(self):
        from ootrr_triforce import app_runtime
        from ootrr_triforce.mod_codec import Codec
        game = Path(os.environ["OOTRR_ROMFS"])
        with patch.object(app_runtime, "_resource_override", Path(os.environ["OOTRR_CODEC_RESOURCES"])):
            codec = Codec((game / "Pack/ZsDic.pack.zs").read_bytes())
            raws = [codec.decode((game / event_info.flow_path(name)).read_bytes())
                    for name in ("GetPouchContent", "Dm_SY_GetInEvent", "NpcCommon")]
        expected = [(raw, entry, event_info.entry_calls(raw, entry), event_info.entry_transitions(raw, entry))
                    for raw in raws for entry in event_info.entry_names(raw)[:12]]
        with patch.object(event_patch, "_flow", wraps=event_patch._flow) as parser, event_info.analysis_scope():
            for raw, entry, calls, transitions in expected:
                self.assertEqual(event_info.entry_calls(raw, entry), calls)
                self.assertEqual(event_info.entry_transitions(raw, entry), transitions)
            self.assertEqual(parser.call_count, len(raws))


if __name__ == "__main__":
    unittest.main()
