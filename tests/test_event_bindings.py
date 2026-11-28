"""Native local actor arguments retain every forwarded action/query binding."""
import copy
import io
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from evfl import EventFlow
from evfl.actor import Actor
from evfl.common import ActorIdentifier, Argument
from evfl.container import Container
from evfl.entry_point import EntryPoint
from evfl.enums import Version
from evfl.event import SubFlowSwitchEvent
from evfl.flowchart import Flowchart
from evfl.util import make_index
from oot_rando.patching.event_bindings import complete_forwarded_actor_bindings
from oot_rando.patching.progressive import FlowEditor, link


def fixture():
    flow = EventFlow()
    flow.name = "ForwardedActor"
    flow.flowchart = Flowchart()
    flow.flowchart.name = flow.name
    for name in ("Main", "Outer", "Middle", "Leaf"):
        flow.flowchart.entry_points.append(EntryPoint(name))
    for name, entry, argument in (("Npc_Talon", None, ""), ("Npc_EventStarter", "Outer", "NpcActor"),
                                   ("Npc_EventStarter", "Leaf", "Npc")):
        actor = Actor()
        actor.identifier = ActorIdentifier(name, entry + "(" + argument + ")" if entry else "")
        actor.argument_name = argument
        actor.argument_entry_point = make_index(next((p for p in flow.flowchart.entry_points if p.name == entry), None))
        actor.concurrent_clips = 1
        actor.params = Container()
        actor.params.data = {"NativeParameter": True}
        flow.flowchart.actors.append(actor)
    stream = io.BytesIO()
    assert flow.write(stream)
    editor = FlowEditor(stream.getvalue(), flow.name)
    points = {p.name:p for p in editor.chart.entry_points}
    concrete, outer, leaf = editor.chart.actors
    action = editor.action("LeafDoNothing", str(leaf.identifier), "EventDoNothing", {"IsWaitEnd": True})
    query = editor.switch("LeafQuery", str(leaf.identifier), "EventQueryNative", None, action, None)
    points["Leaf"].main_event = make_index(query)
    middle = editor.subflow("MiddleToLeaf", "", "Leaf", {"Npc": Argument("ForwardedNpc")})
    points["Middle"].main_event = make_index(middle)
    outer_action = editor.action("OuterEmotion", str(outer.identifier), "EventTriggerChangeEmotion", {"Native": True})
    child = editor.subflow("OuterToMiddle", "", "Middle", {"ForwardedNpc": copy.deepcopy(outer.identifier)})
    link(outer_action, child)
    points["Outer"].main_event = make_index(outer_action)
    start = editor.subflow("MainToOuter", "", "Outer", {"NpcActor": copy.deepcopy(concrete.identifier)})
    points["Main"].main_event = make_index(start)
    return editor


def methods(actor):
    return ([holder.v for holder in actor.actions], [holder.v for holder in actor.queries])


def structure(editor):
    return ([(event.name, type(event.data), copy.deepcopy(event.data.params.data) if getattr(event.data,"params",None) else None)
             for event in editor.chart.events],
            [(str(a.identifier), a.argument_name, a.argument_entry_point.v.name if a.argument_entry_point.v else None,
              copy.deepcopy(a.params.data) if a.params else None) for a in editor.chart.actors],
            [(e.name, e.main_event.v, tuple(e._sub_flow_event_indices)) for e in editor.chart.entry_points])


class ForwardedActorTests(unittest.TestCase):
    def test_earlier_argument_provider_receives_later_native_callbacks(self):
        editor = fixture()
        concrete = editor.chart.actors[0]
        editor.action("LaterNativeCleanup", str(concrete.identifier), "EventGoOffstageForUser", {"IsWaitEnd": False})
        earlier = EntryPoint("EarlierInitTalk")
        editor.chart.entry_points.append(earlier)
        alias = copy.deepcopy(editor.chart.actors[2])
        alias.identifier = ActorIdentifier("Npc_EventStarter", "EarlierInitTalk(Arg_Actor)")
        alias.argument_name = "Arg_Actor"
        alias.argument_entry_point = make_index(earlier)
        alias.actions, alias.queries = [], []
        editor.chart.actors.append(alias)
        earlier.main_event = make_index(editor.action("EarlierGreeting", str(alias.identifier), "EventTalk", None))
        before_call = editor.subflow("MainInitTalk", "", "EarlierInitTalk",
                                     {"Arg_Actor": copy.deepcopy(concrete.identifier)})
        after_call = next(e for e in editor.chart.events if e.name == "MainToOuter")
        link(before_call, after_call)
        next(p for p in editor.chart.entry_points if p.name == "Main").main_event = make_index(before_call)
        before = structure(editor)
        self.assertNotIn("EventGoOffstageForUser", methods(alias)[0])
        result = complete_forwarded_actor_bindings(editor.chart)
        self.assertIn("EventGoOffstageForUser", methods(alias)[0])
        self.assertIn("EventDoNothing", methods(alias)[0])
        self.assertIn("EventQueryNative", methods(alias)[1])
        self.assertGreater(result["reverse_provider_edges"], 0)
        self.assertEqual(structure(editor), before)
        editor.write("Earlier native argument provider")
        self.assertEqual(complete_forwarded_actor_bindings(editor.chart)["actors"], [])

    def test_shared_callee_does_not_cross_transfer_different_providers_methods(self):
        editor = fixture()
        concrete = editor.chart.actors[0]
        other = copy.deepcopy(concrete)
        other.identifier = ActorIdentifier("Npc_Different")
        editor.chart.actors.append(other)
        editor.action("NativeA", str(concrete.identifier), "EventOnlyA", {"Native": 1})
        editor.action("NativeB", str(other.identifier), "EventOnlyB", {"Native": 2})
        root = EntryPoint("OtherRoot")
        editor.chart.entry_points.append(root)
        root.main_event = make_index(editor.subflow("OtherToOuter", "", "Outer",
                                                    {"NpcActor": copy.deepcopy(other.identifier)}))
        before = structure(editor)
        complete_forwarded_actor_bindings(editor.chart)
        self.assertNotIn("EventOnlyB", methods(concrete)[0])
        self.assertNotIn("EventOnlyA", methods(other)[0])
        for provider in (concrete, other):
            self.assertIn("EventDoNothing", methods(provider)[0])
            self.assertIn("EventQueryNative", methods(provider)[1])
        for alias in (editor.chart.actors[1], editor.chart.actors[2]):
            self.assertNotIn("EventOnlyA", methods(alias)[0])
            self.assertNotIn("EventOnlyB", methods(alias)[0])
        self.assertEqual(structure(editor), before)
        editor.write("Shared native callee provider isolation")

    def test_unknown_provider_alternative_cannot_look_uniquely_concrete(self):
        for unknown in (ActorIdentifier("UndeclaredNativeWorldActor"), Argument("ExternalNpc")):
            with self.subTest(unknown=unknown):
                editor = fixture()
                concrete = editor.chart.actors[0]
                editor.action("ConcreteOnly", str(concrete.identifier), "EventOnlyConcrete", None)
                root = EntryPoint("ExternalRoot")
                editor.chart.entry_points.append(root)
                root.main_event = make_index(editor.subflow("ExternalToOuter", "", "Outer", {"NpcActor": unknown}))
                before = structure(editor)
                result = complete_forwarded_actor_bindings(editor.chart)
                self.assertGreater(result["ambiguous_provider_edges"], 0)
                self.assertNotIn("EventOnlyConcrete", methods(editor.chart.actors[1])[0])
                self.assertEqual(structure(editor), before)
                self.assertEqual(complete_forwarded_actor_bindings(editor.chart)["actors"], [])

    def test_three_level_argument_forwarding_binds_alias_and_concrete_actor(self):
        editor = fixture()
        before = structure(editor)
        concrete, outer, leaf = editor.chart.actors
        self.assertNotIn("EventDoNothing", methods(concrete)[0])
        self.assertNotIn("EventDoNothing", methods(outer)[0])
        result = complete_forwarded_actor_bindings(editor.chart)
        for actor in (concrete,outer,leaf):
            self.assertIn("EventDoNothing", methods(actor)[0])
            self.assertIn("EventQueryNative", methods(actor)[1])
        self.assertIn("EventTriggerChangeEmotion", methods(concrete)[0])
        self.assertEqual(structure(editor), before)
        self.assertGreater(result["actions"], 0)
        raw, checked = editor.write("Native forwarded actor binding")
        self.assertIn("EventDoNothing", methods(checked.flowchart.actors[0])[0])
        self.assertTrue(raw)
        after = [methods(actor) for actor in editor.chart.actors]
        repeated = complete_forwarded_actor_bindings(editor.chart)
        self.assertEqual(repeated["actors"], [])
        self.assertEqual(after, [methods(actor) for actor in editor.chart.actors])

    def test_external_call_does_not_modify_local_caller_requirements(self):
        editor = fixture()
        call = next(e for e in editor.chart.events if e.name == "MainToOuter")
        call.data.res_flowchart_name = "NativeExternalFlow"
        concrete = editor.chart.actors[0]
        before = methods(concrete)
        complete_forwarded_actor_bindings(editor.chart)
        self.assertEqual(methods(concrete), before)

    def test_disjoint_entry_scopes_do_not_transfer_unrelated_native_methods(self):
        editor = fixture()
        independent, other_main = EntryPoint("Independent"), EntryPoint("OtherMain")
        editor.chart.entry_points.extend([independent, other_main])
        concrete = copy.deepcopy(editor.chart.actors[0])
        concrete.identifier = ActorIdentifier("Npc_Unrelated")
        scoped = copy.deepcopy(editor.chart.actors[2])
        scoped.identifier = ActorIdentifier("Npc_EventStarter", "Independent(Npc)")
        scoped.argument_entry_point = make_index(independent)
        scoped.actions, scoped.queries = [], []
        editor.chart.actors.extend([concrete, scoped])
        action = editor.action("IndependentAnim", str(scoped.identifier), "EventOnlyIndependent", {"Native": True})
        independent.main_event = make_index(action)
        call = editor.subflow("OtherToIndependent", "", "Independent", {"Npc": copy.deepcopy(concrete.identifier)})
        other_main.main_event = make_index(call)
        before = structure(editor)
        complete_forwarded_actor_bindings(editor.chart)
        self.assertIn("EventOnlyIndependent", methods(concrete)[0])
        self.assertNotIn("EventOnlyIndependent", methods(editor.chart.actors[0])[0])
        self.assertNotIn("EventDoNothing", methods(concrete)[0])
        self.assertNotIn("EventQueryNative", methods(concrete)[1])
        self.assertEqual(structure(editor), before)
        editor.write("Independent native scopes")

    def test_local_return_value_subflow_also_forwards_native_methods(self):
        editor = fixture()
        editor.flow.version = Version.V4
        call = next(e for e in editor.chart.events if e.name == "MainToOuter")
        original = call.data
        data = SubFlowSwitchEvent()
        data.res_flowchart_name = ""
        data.entry_point_name = original.entry_point_name
        data.params, data.cases = original.params, {}
        call.data = data
        before = structure(editor)
        complete_forwarded_actor_bindings(editor.chart)
        self.assertIn("EventDoNothing", methods(editor.chart.actors[0])[0])
        self.assertIn("EventQueryNative", methods(editor.chart.actors[0])[1])
        self.assertEqual(structure(editor), before)
        self.assertEqual(complete_forwarded_actor_bindings(editor.chart)["actors"], [])
        editor.write("Native local return value")

    def test_native_shared_body_resolves_requirements_in_active_entry_argument(self):
        editor = fixture()
        leaf = editor.chart.actors[2]
        alternate = EntryPoint("AlternateLeafScope")
        point = next(p for p in editor.chart.entry_points if p.name == "Leaf")
        alternate.main_event = make_index(point.main_event.v)
        editor.chart.entry_points.append(alternate)
        # Exactly the native GetInEvent_NotTurn/Fado shape: the called entry
        # shares nodes with another entry that owns the actor declaration.
        leaf.argument_entry_point = make_index(alternate)
        leaf.identifier = ActorIdentifier("Npc_EventStarter", "AlternateLeafScope(Npc)")
        before = structure(editor)
        complete_forwarded_actor_bindings(editor.chart)
        for actor in editor.chart.actors:
            self.assertIn("EventDoNothing", methods(actor)[0])
            self.assertIn("EventQueryNative", methods(actor)[1])
        self.assertEqual(structure(editor), before)
        self.assertEqual(complete_forwarded_actor_bindings(editor.chart)["actors"], [])

    def test_duplicate_argument_aliases_union_requirements_without_merging_identities(self):
        editor = fixture()
        leaf = editor.chart.actors[2]
        sibling = copy.deepcopy(leaf)
        sibling.identifier = ActorIdentifier("Npc_OtherAlias", leaf.identifier.sub_name)
        sibling.argument_entry_point = make_index(leaf.argument_entry_point.v)
        sibling.actions = [editor._holder([], "EventOtherNative")]
        sibling.queries = []
        editor.chart.actors.append(sibling)
        before = [str(a.identifier) for a in editor.chart.actors]
        complete_forwarded_actor_bindings(editor.chart)
        self.assertEqual([str(a.identifier) for a in editor.chart.actors], before)
        for actor in editor.chart.actors:
            self.assertIn("EventOtherNative", methods(actor)[0])

    def test_cycles_are_finite_and_second_pass_is_empty(self):
        editor = fixture()
        leaf_point = next(p for p in editor.chart.entry_points if p.name == "Leaf")
        action = next(e for e in editor.chart.events if e.name == "LeafDoNothing")
        cycle = editor.subflow("LeafToOuter", "", "Outer", {"NpcActor": Argument("Npc")})
        link(action,cycle)
        first = complete_forwarded_actor_bindings(editor.chart)
        second = complete_forwarded_actor_bindings(editor.chart)
        self.assertGreater(first["actions"], 0)
        self.assertEqual(second["actions"], 0)
        self.assertEqual(second["queries"], 0)
        self.assertIsNotNone(leaf_point.main_event.v)

    def test_unbound_actor_argument_cycle_remains_opaque_and_finite(self):
        editor = fixture()
        next(p for p in editor.chart.entry_points if p.name == "Main").main_event = make_index(None)
        # Remove the detached caller as well: no concrete participant supplies
        # this closed native argument cycle from any local invocation.
        editor.chart.events = [e for e in editor.chart.events if e.name != "MainToOuter"]
        action = next(e for e in editor.chart.events if e.name == "LeafDoNothing")
        cycle = editor.subflow("LeafToOuter", "", "Outer", {"NpcActor": Argument("Npc")})
        link(action, cycle)
        concrete = editor.chart.actors[0]
        editor.action("ConcreteNotPassed", str(concrete.identifier), "EventOnlyUnusedConcrete", None)
        before = structure(editor)
        result = complete_forwarded_actor_bindings(editor.chart)
        self.assertGreater(result["ambiguous_provider_edges"], 0)
        for actor in editor.chart.actors[1:]:
            self.assertNotIn("EventOnlyUnusedConcrete", methods(actor)[0])
        self.assertEqual(structure(editor), before)
        self.assertEqual(complete_forwarded_actor_bindings(editor.chart)["actors"], [])

    def test_ambiguous_concrete_participant_is_rejected_before_mutation(self):
        editor = fixture()
        editor.chart.actors.append(copy.deepcopy(editor.chart.actors[0]))
        before = [methods(a) for a in editor.chart.actors]
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            complete_forwarded_actor_bindings(editor.chart)
        self.assertEqual(before,[methods(a) for a in editor.chart.actors])

    def test_undeclared_world_literal_remains_native_and_is_reported(self):
        editor = fixture()
        call = next(e for e in editor.chart.events if e.name == "MainToOuter")
        call.data.params.data["NpcActor"] = ActorIdentifier("NativeWorldActor")
        concrete = editor.chart.actors[0]
        before = methods(concrete)
        result = complete_forwarded_actor_bindings(editor.chart)
        self.assertEqual(methods(concrete), before)
        self.assertEqual(result["world_actor_literals"], ["NativeWorldActor"])


if __name__ == "__main__":
    unittest.main()
