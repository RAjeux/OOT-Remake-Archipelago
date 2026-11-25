"""Large AP dispatchers retain native preorder and do not grow Python's stack."""
from collections import deque
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from evfl.event import ActionEvent, SwitchEvent, ForkEvent, JoinEvent, SubFlowEvent, SubFlowSwitchEvent
from evfl.util import make_index
from oot_rando.patching.progressive import FlowEditor
from test_skull_events import native_flow


def old_order(entry, visited=None, found=None):
    """The original writer's traversal, used only on a small reference graph."""
    visited = set() if visited is None else visited
    found = {} if found is None else found
    queue = deque([entry]) if entry is not None else deque()
    while queue:
        event = queue.popleft()
        if event in visited:
            continue
        visited.add(event)
        data = event.data
        if isinstance(data, (ActionEvent, JoinEvent, SubFlowEvent)):
            if isinstance(data, SubFlowEvent):
                found[event] = None
            if data.nxt.v is not None:
                queue.append(data.nxt.v)
        elif isinstance(data, (SwitchEvent, SubFlowSwitchEvent)):
            if isinstance(data, SubFlowSwitchEvent):
                found[event] = None
            for case in data.cases.values():
                old_order(case.v, visited, found)
        elif isinstance(data, ForkEvent):
            for fork in data.forks:
                old_order(fork.v, visited, found)
            queue.append(data.join.v)
    return [event.name for event in found]


def dispatcher(count):
    editor = FlowEditor(native_flow(), "large dispatcher fixture")
    point = next(point for point in editor.chart.entry_points if point.name == "GetPouchContent")
    root = point.main_event.v
    for index in range(count):
        call = editor.subflow("DeepCall" + str(index), "NativeFixture", "Get", {"ActorName": "Item_Fixture"})
        root = editor.switch("DeepSelect" + str(index), "GameDataActor", "EventQueryIsGameDataBool",
                             {"GameDataName": "Fixture." + str(index), "Index": -1}, call, root)
    point.main_event = make_index(root)
    return editor, point


class EventGraphDepthTests(unittest.TestCase):
    def test_native_preorder_is_unchanged(self):
        editor, point = dispatcher(20)
        expected = old_order(point.main_event.v)
        _, checked = editor.write("reference traversal order")
        point = next(point for point in checked.flowchart.entry_points if point.name == "GetPouchContent")
        actual = [checked.flowchart.events[index].name for index in point._sub_flow_event_indices]
        self.assertEqual(actual, expected)

    def test_thousands_of_source_branches_round_trip_without_global_limit_changes(self):
        limit = sys.getrecursionlimit()
        editor, _ = dispatcher(2500)
        raw, checked = editor.write("large AP dispatcher")
        point = next(point for point in checked.flowchart.entry_points if point.name == "GetPouchContent")
        calls = [checked.flowchart.events[index].name for index in point._sub_flow_event_indices]
        self.assertEqual(calls[:2500], ["DeepCall" + str(index) for index in reversed(range(2500))])
        self.assertEqual(len(calls), len(set(calls)))
        self.assertEqual(sys.getrecursionlimit(), limit)
        again, _ = FlowEditor(raw, "repeated graph write").write("repeated graph write")
        self.assertEqual(raw, again)


if __name__ == "__main__":
    unittest.main()
