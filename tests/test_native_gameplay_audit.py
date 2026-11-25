"""Independent native-flow audit; real assets are opt-in and read-only.

Set OOTRR_ROMFS, OOTRR_AUDIT_MOD and OOTRR_CODEC_RESOURCES to audit a prepared
private mod. The dependency delta additionally uses OOTRR_AUDIT_BASE, the
generated base before room preparation. This is not a visual playthrough.
"""
from functools import lru_cache
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))


def successors(event):
    data = event.data
    result = []
    if hasattr(data, "nxt") and data.nxt.v is not None:
        result.append(data.nxt.v)
    result.extend(case.v for case in getattr(data, "cases", {}).values() if case.v is not None)
    result.extend(case.v for case in getattr(data, "forks", []) if case.v is not None)
    if hasattr(data, "join") and data.join.v is not None:
        result.append(data.join.v)
    return result


class CallGraph:
    """Analyze entry calls without using the production dependency updater."""
    def __init__(self, reader):
        self.reader = reader
        self.missing = set()

    @lru_cache(None)
    def chart(self, flow):
        from oot_rando.patching.event_patch import _flow
        raw = self.reader(flow)
        return _flow(raw).flowchart if raw is not None else None

    @lru_cache(None)
    def direct(self, flow, entry):
        from evfl.event import ActionEvent, SubFlowEvent
        chart = self.chart(flow)
        points = {point.name: point for point in chart.entry_points} if chart else {}
        if not entry and points:
            entry = flow if flow in points else "EntryPoint0" if "EntryPoint0" in points else next(iter(points))
        if entry not in points:
            self.missing.add((flow, entry))
            return frozenset(), frozenset(), frozenset()
        stack, visited, calls, children, dynamic = [points[entry].main_event.v], set(), set(), set(), set()
        while stack:
            event = stack.pop()
            if event is None or event in visited:
                continue
            visited.add(event)
            data = event.data
            if isinstance(data, SubFlowEvent):
                calls.add((data.res_flowchart_name or flow, data.entry_point_name))
            elif type(data).__name__ == "SubFlowSwitchEvent":
                if not data.res_flowchart_name and data.entry_point_name in points:
                    calls.add((flow, data.entry_point_name))
                else:
                    dynamic.add((flow, event.name))
            elif isinstance(data, ActionEvent) and data.actor_action.v.v == "EventTransition":
                name = data.params.data.get("EventName") if data.params else None
                if isinstance(name, str) and name:
                    children.add(str(name))
            stack.extend(successors(event))
        return frozenset(calls), frozenset(children), frozenset(dynamic)

    @lru_cache(None)
    def closure(self, flow, entry):
        pending, seen, flows, children, dynamic = [(flow, entry)], set(), set(), set(), set()
        while pending:
            call = pending.pop()
            if call in seen:
                continue
            seen.add(call)
            flows.add(call[0])
            calls, transitions, unknown = self.direct(*call)
            pending.extend(calls - seen)
            children.update(transitions)
            dynamic.update(unknown)
        return frozenset(flows), frozenset(children), frozenset(dynamic)


class ParameterCallGraph(CallGraph):
    """Bounded string dataflow, sufficient for the native/AP dispatcher split.

    Native actor constants share one abstract value: equalities with AP actor
    identities are false, while comparisons with other native values remain
    unknown. Calls invalidate scratch on return because their side effects are
    not summarized. Both choices retain unproved paths instead of hiding them.
    """
    NATIVE = "<native-non-AP-actor>"

    def __init__(self, reader, native_actors):
        super().__init__(reader)
        self.native_actors = frozenset(native_actors)
        self.budget_hits = set()
        self.context_count = 0

    def literal(self, value, arguments):
        from evfl.common import Argument
        if isinstance(value, Argument):
            return arguments.get(str(value))
        if type(value) not in (str, bool, int, float):
            return None
        return self.NATIVE if value in self.native_actors else value

    @lru_cache(maxsize=50000)
    def direct_context(self, flow, entry, bindings):
        from evfl.common import Argument
        from evfl.event import ActionEvent, SubFlowEvent, SwitchEvent
        self.context_count += 1
        if self.context_count > 50000:
            self.budget_hits.add((flow, entry))
            return frozenset(), frozenset(), frozenset()
        chart = self.chart(flow)
        points = {p.name: p for p in chart.entry_points} if chart else {}
        if not entry and points:
            entry = flow if flow in points else "EntryPoint0" if "EntryPoint0" in points else next(iter(points))
        if entry not in points:
            self.missing.add((flow, entry))
            return frozenset(), frozenset(), frozenset()
        arguments = dict(bindings)
        initial = {key[4:]: value for key, value in bindings if key.startswith("$gd:")}
        pending, seen = [(points[entry].main_event.v, tuple(sorted(initial.items())))], set()
        calls, children, dynamic = set(), set(), set()
        while pending:
            event, frozen = pending.pop()
            if event is None or (event, frozen) in seen:
                continue
            seen.add((event, frozen))
            if len(seen) > 100000:
                self.budget_hits.add((flow, entry))
                break
            values, data = dict(frozen), event.data
            params = data.params.data if getattr(data, "params", None) else {}
            if isinstance(data, ActionEvent):
                if data.actor_action.v.v == "EventTriggerSetGameDataString64":
                    key = self.literal(params.get("GameDataName"), arguments)
                    value = self.literal(params.get("Value"), arguments)
                    if key is not None:
                        if value is None:
                            values.pop(key, None)
                        else:
                            values[key] = value
                elif data.actor_action.v.v == "EventTransition":
                    value = self.literal(params.get("EventName"), arguments)
                    if value is not None:
                        children.add(value)
            elif isinstance(data, SubFlowEvent):
                target = data.res_flowchart_name or flow
                if data.res_flowchart_name or data.entry_point_name in points:
                    bound = {key: self.literal(value, arguments) for key, value in params.items()}
                    bound = {key: value for key, value in bound.items() if value is not None}
                    bound.update({"$gd:" + key: value for key, value in values.items()})
                    calls.add((target, data.entry_point_name, tuple(sorted(bound.items()))))
                values.clear()
            elif isinstance(data, SwitchEvent) and data.actor_query.v.v == "EventQueryIsGameDataString64":
                key = self.literal(params.get("GameDataName"), arguments)
                expected = self.literal(params.get("Value"), arguments)
                actual = values.get(key)
                choice = None
                if actual is not None and expected is not None:
                    if self.NATIVE not in (actual, expected):
                        choice = 0 if actual == expected else 1
                    elif any(type(value) is str and value.startswith(("Item_AP_", "Obj_AP_"))
                             for value in (actual, expected)):
                        choice = 1
                if choice is not None:
                    target = data.cases.get(choice)
                    if target and target.v is not None:
                        pending.append((target.v, tuple(sorted(values.items()))))
                    continue
            elif type(data).__name__ == "SubFlowSwitchEvent":
                if not data.res_flowchart_name and data.entry_point_name in points:
                    calls.add((flow, data.entry_point_name, bindings))
                else:
                    dynamic.add((flow, event.name))
            frozen = tuple(sorted(values.items()))
            pending.extend((target, frozen) for target in successors(event))
        return frozenset(calls), frozenset(children), frozenset(dynamic)

    @lru_cache(maxsize=20000)
    def closure(self, flow, entry):
        pending, seen, flows, children, dynamic = [(flow, entry, ())], set(), set(), set(), set()
        while pending:
            call = pending.pop()
            if call in seen:
                continue
            seen.add(call)
            flows.add(call[0])
            calls, transitions, unknown = self.direct_context(*call)
            pending.extend(calls - seen)
            children.update(transitions)
            dynamic.update(unknown)
        return frozenset(flows), frozenset(children), frozenset(dynamic)


def audit_dependencies(native, current, settings, analyzed, modified):
    """Only new requirements are asserted; old native imperfections stay visible."""
    now, before = CallGraph(current), CallGraph(native)
    by_flow = {}
    for name in sorted(modified):
        chart = now.chart(name)
        flows, children = set(), set()
        for point in chart.entry_points:
            a, ac, _ = now.closure(name, point.name)
            b, bc, _ = before.closure(name, point.name)
            flows.update(a - b)
            children.update(ac - bc)
        by_flow[name] = flows, children
    failures, checked = [], 0
    rows = {row["__RowId"]: row for row in analyzed}
    for row in settings:
        filename = row.get("FlowchartFileName", "")
        name = filename.rsplit("/", 1)[-1].removesuffix(".evfc")
        info = rows.get(row["__RowId"], {})
        listed = set(info.get("SubFlowList", ()))
        if name not in modified and not listed.intersection(modified):
            continue
        checked += 1
        entry = row.get("EntryPointName", "")
        a, ac, _ = now.closure(name, entry)
        b, bc, _ = before.closure(name, entry)
        needed, child_needed = set(a - b), set(ac - bc)
        # Self entries register their exact quiet route. They must not inherit
        # the unrelated receipt/camera entries that happen to share a chart.
        for referenced in listed.intersection(by_flow) - {name}:
            extra, extra_children = by_flow[referenced]
            needed.update(extra)
            child_needed.update(extra_children)
        missing = needed - listed - {name}
        missing_children = child_needed - set(info.get("ChildEventList", ())) - {row["__RowId"]}
        if missing or missing_children:
            failures.append(dict(event=row["__RowId"], subflows=sorted(missing), children=sorted(missing_children)))
    return dict(modified_flows=len(modified), checked_events=checked, failures=failures,
                new_missing_entries=sorted(now.missing - before.missing),
                native_missing_entries=len(before.missing))


def audit_parameter_dependencies(native, current, settings, analyzed, modified, native_actors):
    now, before = ParameterCallGraph(current, native_actors), ParameterCallGraph(native, native_actors)
    infos = {row["__RowId"]: row for row in analyzed}
    candidates, checked = [], 0
    for row in settings:
        flow = row.get("FlowchartFileName", "").rsplit("/", 1)[-1].removesuffix(".evfc")
        info = infos.get(row["__RowId"], {})
        listed = set(info.get("SubFlowList", ()))
        if flow not in modified and not listed.intersection(modified):
            continue
        checked += 1
        a, ac, _ = now.closure(flow, row.get("EntryPointName", ""))
        b, bc, _ = before.closure(flow, row.get("EntryPointName", ""))
        missing = a - b - listed - {flow}
        children = ac - bc - set(info.get("ChildEventList", ())) - {row["__RowId"]}
        if missing or children:
            candidates.append(dict(event=row["__RowId"], flow=flow, subflows=sorted(missing), children=sorted(children)))
    return dict(checked_events=checked, candidates=candidates,
                current_contexts=now.context_count, base_contexts=before.context_count,
                context_budget_hits=sorted(now.budget_hits | before.budget_hits),
                new_missing_entries=sorted(now.missing - before.missing))


class CallGraphTests(unittest.TestCase):
    def fixture(self, name, *, call=None, transition=None, params=None):
        from evfl import EventFlow
        from evfl.actor import Actor
        from evfl.common import ActorIdentifier
        from evfl.entry_point import EntryPoint
        from evfl.flowchart import Flowchart
        from evfl.util import make_index
        from oot_rando.patching.progressive import FlowEditor
        flow = EventFlow()
        flow.name = name
        flow.flowchart = Flowchart()
        flow.flowchart.name = name
        for actor_name in ("EventSystemActor", "GameSystemActor"):
            actor = Actor()
            actor.identifier = ActorIdentifier(actor_name)
            actor.concurrent_clips = 1
            flow.flowchart.actors.append(actor)
        stream = io.BytesIO()
        self.assertTrue(flow.write(stream))
        editor = FlowEditor(stream.getvalue(), name)
        if call:
            node = editor.subflow("Call", *call, params)
        elif transition:
            node = editor.action("Transition", "GameSystemActor", "EventTransition", {"EventName": transition})
        else:
            node = editor.action("End", "EventSystemActor", "EventWait", {"Frames": 1})
        point = EntryPoint(name)
        point.main_event = make_index(node)
        editor.chart.entry_points.append(point)
        return editor.write("Dependency audit fixture")[0]

    def test_indirect_load_and_child_event_requirements_are_both_detected(self):
        old = {"Main": self.fixture("Main"), "Guide": self.fixture("Guide", transition="Lesson")}
        new = dict(old, Main=self.fixture("Main", call=("Guide", "Guide")))
        settings = [{"__RowId": "MainEvent", "FlowchartFileName": "Work/Event/EventFlow/Main.evfc", "EntryPointName": "Main"}]
        report = audit_dependencies(old.get, new.get, settings, [{"__RowId": "MainEvent"}], {"Main"})
        self.assertEqual(report["failures"], [{"event": "MainEvent", "subflows": ["Guide"], "children": ["Lesson"]}])
        registered = [{"__RowId": "MainEvent", "SubFlowList": ["Guide"], "ChildEventList": ["Lesson"]}]
        self.assertFalse(audit_dependencies(old.get, new.get, settings, registered, {"Main"})["failures"])

    def test_missing_new_entry_is_reported_separately_from_old_native_gaps(self):
        old = {"Main": self.fixture("Main"), "Guide": self.fixture("Guide")}
        new = dict(old, Main=self.fixture("Main", call=("Guide", "Missing")))
        graph = CallGraph(new.get)
        graph.closure("Main", "Main")
        self.assertEqual(graph.missing, {("Guide", "Missing")})

    def test_native_actor_binding_excludes_ap_branch_but_unknown_actor_keeps_it(self):
        from evfl.common import Argument
        from oot_rando.patching.progressive import FlowEditor, link
        source = FlowEditor(self.fixture("Pouch"), "Pouch")
        end = source.chart.entry_points[0].main_event.v
        forbidden = source.subflow("OnlyAP", "ForeignOnly", "ForeignOnly", None)
        branch = source.switch("MatchAP", "GameDataActor", "EventQueryIsGameDataString64",
                               {"GameDataName": "Archipelago.SelectedPickup", "Index": -1,
                                "Value": "Item_AP_123"}, forbidden, end)
        capture = source.action("Capture", "GameDataActor", "EventTriggerSetGameDataString64",
                                {"GameDataName": "Archipelago.SelectedPickup", "Index": -1,
                                 "Value": Argument("ActorName")})
        link(capture, branch)
        from evfl.util import make_index
        source.chart.entry_points[0].main_event = make_index(capture)
        files = {"Pouch": source.write("Parametric dispatcher fixture")[0],
                 "ForeignOnly": self.fixture("ForeignOnly"),
                 "Native": self.fixture("Native", call=("Pouch", "Pouch"), params={"ActorName": "Item_FishingRod"}),
                 "Unknown": self.fixture("Unknown", call=("Pouch", "Pouch"))}
        graph = ParameterCallGraph(files.get, {"Item_FishingRod"})
        self.assertNotIn("ForeignOnly", graph.closure("Native", "Native")[0])
        self.assertIn("ForeignOnly", graph.closure("Unknown", "Unknown")[0])


@unittest.skipUnless(os.environ.get("OOTRR_ROMFS") and os.environ.get("OOTRR_AUDIT_MOD"),
                     "requires a prepared private native mod and original read-only assets")
class NativeGameplayAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ootrr_triforce import app_runtime
        from ootrr_triforce.mod_codec import Codec
        cls.game = Path(os.environ["OOTRR_ROMFS"])
        cls.mod = Path(os.environ["OOTRR_AUDIT_MOD"])
        cls.override = patch.object(app_runtime, "_resource_override", Path(os.environ["OOTRR_CODEC_RESOURCES"]))
        cls.override.start()
        cls.codec = Codec((cls.game / "Pack/ZsDic.pack.zs").read_bytes())
        cls.report = {"scope": "Read-only resource and event contracts; no game launched."}

    @classmethod
    def tearDownClass(cls):
        cls.override.stop()
        if os.environ.get("OOTRR_AUDIT_REPORT"):
            Path(os.environ["OOTRR_AUDIT_REPORT"]).write_text(json.dumps(cls.report, indent=2), encoding="utf-8")

    @classmethod
    def read(cls, path, *, native=False):
        staged = cls.mod / path
        return cls.codec.decode((cls.game / path if native or not staged.is_file() else staged).read_bytes())

    def test_player_brain_contract_remains_native_for_rental_rod_and_input(self):
        from oot_rando.formats.inspect_resources import sarc
        count = 0
        for actor in ("Player_Base", "Player_Child", "Player_Adult"):
            file = "Pack/Actor/" + actor + ".pack.zs"
            native, prepared = sarc(self.read(file, native=True)), sarc(self.read(file))
            brain = "AI/Player.brain.root.ainb"
            self.assertIn(brain, native)
            self.assertEqual(prepared[brain], native[brain], actor)
            count += 1
        self.report["unchanged_native_player_brains"] = count

    def test_fishing_and_bowling_keep_authored_player_equipment_commands(self):
        from oot_rando.patching.event_patch import _flow
        checked = {}
        for flow in ("MiniGame_Fishing", "MiniGame_BombchuBowling"):
            path = "Event/EventFlow/" + flow + ".bfevfl.zs"
            old = _flow(self.read(path, native=True)).flowchart
            new = _flow(self.read(path)).flowchart
            by_name = {event.name: event for event in new.events}
            commands = []
            for event in old.events:
                action = getattr(event.data, "actor_action", None)
                if action is None or not action.v.v.startswith("EventPlayer"):
                    continue
                after = by_name[event.name].data
                self.assertEqual(after.actor_action.v.v, action.v.v, (flow, event.name))
                params = event.data.params.data if event.data.params else None
                self.assertEqual(after.params.data if after.params else None, params, (flow, event.name))
                commands.append([event.name, action.v.v])
            self.assertTrue(commands, flow)
            checked[flow] = commands
        self.report["preserved_native_minigame_commands"] = checked

    def test_native_non_ap_pouch_contents_cannot_enter_an_ap_source_callback(self):
        from evfl.event import ActionEvent, SwitchEvent
        from oot_rando.formats import byml_codec
        from oot_rando.patching.event_patch import _flow
        path = "Event/EventFlow/GetPouchContent.bfevfl.zs"
        original = _flow(self.read(path, native=True)).flowchart
        prepared = _flow(self.read(path)).flowchart
        root_of = lambda chart: next(p.main_event.v for p in chart.entry_points if p.name == "GetPouchContent")
        actor_names = {row["__RowId"] for row in byml_codec.load(self.read("RSDB/PouchActorInfo.Product.111.rstbl.byml.zs", native=True))["root"]}
        node, seen, identities = root_of(prepared), set(), set()
        while node.name.startswith("OOTRR_APSkull_"):
            self.assertNotIn(node.name, seen)
            seen.add(node.name)
            data = node.data
            if isinstance(data, ActionEvent):
                self.assertIn(data.actor_action.v.v, {"EventTriggerSetGameDataString64", "EventWait"})
                node = data.nxt.v
            else:
                self.assertIsInstance(data, SwitchEvent)
                self.assertEqual(data.actor_query.v.v, "EventQueryIsGameDataString64")
                identities.add(data.params.data["Value"])
                node = data.cases[1].v
            self.assertIsNotNone(node)
        self.assertFalse(identities.intersection(actor_names))
        self.assertEqual(node.name, root_of(original).name)
        self.report["native_pouch_fallback"] = dict(native_contents=len(actor_names), ap_identities=len(identities),
                                                     native_root=node.name, fishing_rod="Item_FishingRod" in actor_names)

    def test_new_call_targets_and_exact_quiet_restoration_dependencies_are_registered(self):
        from oot_rando.formats import byml_codec
        from oot_rando.patching import chest_flags
        if not os.environ.get("OOTRR_AUDIT_BASE"):
            self.skipTest("requires the generated base before AP room preparation")
        base = Path(os.environ["OOTRR_AUDIT_BASE"])
        modified = {path.name.removesuffix(".bfevfl.zs") for path in (self.mod / "Event/EventFlow").glob("*.bfevfl.zs")}
        def reader(name, native=False):
            path = "Event/EventFlow/" + name + ".bfevfl.zs"
            if not (self.game / path).is_file() and (native or not (self.mod / path).is_file()):
                return None
            return self.read(path, native=native)
        def baseline(name):
            path = "Event/EventFlow/" + name + ".bfevfl.zs"
            source = base / path
            return self.codec.decode(source.read_bytes()) if source.is_file() else reader(name, True)
        report = audit_dependencies(baseline, reader,
                    byml_codec.load(self.read(chest_flags.EVENT_SETTINGS))["root"],
                    byml_codec.load(self.read(chest_flags.ANALYZED))["root"], modified)
        # Broad static traversal cannot infer literal ActorName bindings across
        # calls. In particular it may enter AP dispatch cases for a native item
        # that the preceding fallback test proves cannot enter those cases.
        # Quiet restoration entries do not have this ambiguity. Retain other
        # findings as review candidates, never as a claimed gameplay defect.
        candidates = report.pop("failures")
        report["failures"] = [row for row in candidates if row["event"].startswith("OOTRR_APRestore_")]
        report["conservative_candidates"] = [row for row in candidates if not row["event"].startswith("OOTRR_APRestore_")]
        report["analysis_limit"] = "No cross-call parameter propagation; non-restoration candidates require contextual review."
        self.report["dependencies"] = report
        self.assertFalse(report["failures"], json.dumps(report["failures"][:10], indent=2))
        self.assertFalse(report["new_missing_entries"], report["new_missing_entries"][:10])
        native_actors = {row["__RowId"] for row in byml_codec.load(
            self.read("RSDB/PouchActorInfo.Product.111.rstbl.byml.zs", native=True))["root"]}
        parameter_report = audit_parameter_dependencies(baseline, reader,
                    byml_codec.load(self.read(chest_flags.EVENT_SETTINGS))["root"],
                    byml_codec.load(self.read(chest_flags.ANALYZED))["root"], modified, native_actors)
        self.report["parameter_dependencies"] = parameter_report
        self.assertFalse(parameter_report["new_missing_entries"], parameter_report["new_missing_entries"][:10])


if __name__ == "__main__":
    unittest.main(verbosity=2)
