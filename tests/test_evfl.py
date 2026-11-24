"""Terminal switch branches emitted by OOTRR must survive EVFL editing."""
import io
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client"))

from evfl import EventFlow
from evfl.actor import Actor
from evfl.common import ActorIdentifier, StringHolder
from evfl.entry_point import EntryPoint
from evfl.enums import Version
from evfl.event import Event, ForkEvent, JoinEvent, SubFlowEvent, SubFlowSwitchEvent, SwitchEvent
from evfl.flowchart import Flowchart
from evfl.repr_util import generate_flowchart_graph
from evfl.util import make_index, make_rindex


def switch_flow(kind, fork=False):
    flow = EventFlow()
    flow.version = Version.V4
    flow.name = "TerminalSwitch"
    flow.flowchart = chart = Flowchart()
    chart.name = flow.name
    actor = Actor()
    actor.identifier = ActorIdentifier("GameDataActor")
    actor.queries = [StringHolder("EventQueryIsGameDataBool")]
    chart.actors = [actor]
    branch = Event()
    branch.name = "Branch"
    branch.data = kind()
    if kind is SwitchEvent:
        branch.data.actor = make_rindex(actor)
        branch.data.actor_query = make_rindex(actor.queries[0])
    else:
        branch.data.res_flowchart_name = "External"
        branch.data.entry_point_name = "Choose"
    reward = Event()
    reward.name = "Reward"
    reward.data = SubFlowEvent()
    reward.data.res_flowchart_name = "External"
    reward.data.entry_point_name = "Give"
    branch.data.cases = {0: make_index(None), 1: make_index(reward)}
    chart.events = [branch, reward]
    entry = EntryPoint("Main")
    entry.main_event = make_index(branch)
    chart.entry_points = [entry]
    if fork:
        head, join = Event(), Event()
        head.name, head.data = "Fork", ForkEvent()
        join.name, join.data = "Join", JoinEvent()
        head.data.forks = [make_rindex(branch)]
        head.data.join = make_rindex(join)
        chart.events.extend([head, join])
        entry.main_event = make_index(head)
    return flow


def encode(flow):
    output = io.BytesIO()
    assert flow.write(output)
    return output.getvalue()


def decode(raw):
    flow = EventFlow()
    flow.read(raw)
    return flow


class LargeDispatcherTests(unittest.TestCase):
    def test_thousands_of_switches_preserve_subflow_order_without_python_recursion(self):
        for kind in (SwitchEvent, SubFlowSwitchEvent):
            with self.subTest(kind=kind.__name__):
                flow = switch_flow(kind)
                chart = flow.flowchart
                first, reward = chart.events
                branches = [first]
                for index in range(1, 2500):
                    branch = Event()
                    branch.name, branch.data = 'Branch' + str(index), kind()
                    if kind is SwitchEvent:
                        branch.data.actor = make_rindex(chart.actors[0])
                        branch.data.actor_query = make_rindex(chart.actors[0].queries[0])
                    else:
                        branch.data.res_flowchart_name = 'External'
                        branch.data.entry_point_name = 'Choose'
                    branches.append(branch)
                for index, branch in enumerate(branches):
                    branch.data.cases = {0: make_index(reward),
                                         1: make_index(branches[index + 1] if index + 1 < len(branches) else None)}
                chart.events = [*branches, reward]
                raw = encode(flow)
                restored = decode(raw)
                expected = [2500] if kind is SwitchEvent else [0, 2500, *range(1, 2500)]
                self.assertEqual(restored.flowchart.entry_points[0]._sub_flow_event_indices, expected)
                self.assertEqual(encode(restored), raw)


class TerminalSwitchTests(unittest.TestCase):
    def test_read_write_keeps_terminal_and_other_case(self):
        for kind in (SwitchEvent, SubFlowSwitchEvent):
            with self.subTest(kind=kind.__name__):
                raw = encode(switch_flow(kind))
                for _ in range(2):
                    restored = decode(raw)
                    chart = restored.flowchart
                    cases = chart.events[0].data.cases
                    self.assertIsNone(cases[0].v)
                    self.assertEqual(cases[0]._idx, 0xFFFF)
                    self.assertIs(cases[1].v, chart.events[1])
                    self.assertEqual(cases[1]._idx, 1)
                    expected = [1] if kind is SwitchEvent else [0, 1]
                    self.assertEqual(chart.entry_points[0]._sub_flow_event_indices, expected)
                    raw = encode(restored)

    def test_terminal_graph_has_no_invalid_edge(self):
        for kind in (SwitchEvent, SubFlowSwitchEvent):
            for fork in (False, True):
                with self.subTest(kind=kind.__name__, fork=fork):
                    graph = generate_flowchart_graph(switch_flow(kind, fork))
                    edges = [row for row in graph if row["type"] == "edge"]
                    self.assertIn({"type": "edge", "source": 0, "target": 1,
                                   "data": {"value": 1}}, edges)
                    terminal = [edge for edge in edges
                                if edge["source"] == 0 and edge["data"].get("value") == 0]
                    expected = ([{"type": "edge", "source": 0, "target": 3,
                                  "data": {"value": 0, "virtual": True}}] if fork else [])
                    self.assertEqual(terminal, expected)

    def test_other_invalid_case_index_is_rejected(self):
        raw = encode(switch_flow(SwitchEvent))
        # Locate the first switch's case table using the documented EVFL pointers.
        import struct
        charts = struct.unpack_from("<Q", raw, 0x28)[0]
        chart = struct.unpack_from("<Q", raw, charts)[0]
        events = struct.unpack_from("<Q", raw, chart + 0x30)[0]
        cases = struct.unpack_from("<Q", raw, events + 0x18)[0]
        broken = bytearray(raw)
        struct.pack_into("<H", broken, cases + 4, 2)
        with self.assertRaises(IndexError):
            decode(broken)


if __name__ == "__main__":
    unittest.main()
