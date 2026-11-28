"""Native pickup dispatch banks preserve selection, arguments and return paths."""
import io
import struct
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from evfl.actor import Actor
from evfl.common import ActorIdentifier, Argument, StringHolder
from evfl.entry_point import EntryPoint, VariableDef
from evfl.event import ActionEvent, SubFlowEvent, SwitchEvent
from evfl.util import make_index, make_rindex
from oot_rando.game.resource_allocations import allocation
from oot_rando.patching.progressive import FlowEditor
from ootrr_triforce import dispatch_banks as banks
from test_receipt_events import native_flow
from test_receipt_registration import IdentityCodec
from test_resource_allocations import table


def fixture(count, name="GetPouchContent", *, args=True):
    editor = FlowEditor(native_flow(), "dispatcher fixture")
    editor.chart.name = editor.flow.name = name
    editor.chart.events.clear()
    editor.chart.entry_points.clear()
    editor.expected.clear()
    fallback = editor.action("NativeFallback", "GameDataActor", "FixtureFallback", (
        {key: Argument(key) for key in ("ActorName", "IsGetInEvent", "IsShowNumDisplay", "IsTreasureBox")}
        if args else None))
    dispatch = fallback
    for index in reversed(range(count)):
        reward = editor.action("Reward" + str(index), "GameDataActor", "FixtureReward", {"Number": index})
        dispatch = editor.switch("OOTRR_APSkull_" + str(index + 1) + "_Match0", "GameDataActor",
            "EventQueryIsGameDataString64", {"GameDataName": "Archipelago.SelectedPickup", "Index": -1,
                                           "Value": "Item_AP_Identity" + str(index)}, reward, dispatch)
    point = EntryPoint(name)
    point.main_event = make_index(dispatch)
    editor.chart.entry_points.append(point)
    return editor.write("dispatcher fixture")[0]


def serialize(editor):
    stream = io.BytesIO()
    editor.flow.write(stream)
    return stream.getvalue()


def outcome(raw, identity, arguments=None):
    chart = FlowEditor(raw, "selector execution model").chart
    points = {point.name: point.main_event.v for point in chart.entry_points}
    node = points[chart.name]
    arguments = arguments or {}
    stack, steps = [], 0
    while node is not None or stack:
        if node is None:
            node, arguments = stack.pop()
            continue
        steps += 1
        assert steps < 10000
        data = node.data
        params = {key: arguments[value] if isinstance(value, Argument) else value
                  for key, value in (data.params.data.items() if data.params else ())}
        if isinstance(data, SwitchEvent):
            node = data.cases[0 if params["Value"] == identity else 1].v
        elif isinstance(data, SubFlowEvent):
            assert not data.res_flowchart_name
            stack.append((data.nxt.v, arguments))
            node, arguments = points[data.entry_point_name], params
        elif isinstance(data, ActionEvent):
            return node.name, params
        else:
            raise AssertionError(type(data))
    return None


class DispatchBankTests(unittest.TestCase):
    def test_long_chain_preserves_every_reward_and_native_fallback_arguments(self):
        before = fixture(321)
        after, report = banks.bank_dispatch_flow(before, "GetPouchContent")
        self.assertTrue(report["changed"])
        self.assertEqual(report["banks"], 5)
        self.assertEqual(report["max_switches_per_bank"], 64)
        args = dict(ActorName="Original", IsGetInEvent=True, IsShowNumDisplay=False, IsTreasureBox=True)
        for index in range(321):
            identity = "Item_AP_Identity" + str(index)
            self.assertEqual(outcome(before, identity, args), outcome(after, identity, args))
        self.assertEqual(outcome(before, "NativeActor", args), outcome(after, "NativeActor", args))
        self.assertEqual(outcome(after, "NativeActor", args), ("NativeFallback", args))
        self.assertLessEqual(report["max_direct_subflows"], 1)

    def test_limit_boundary_and_noop_native_charts(self):
        for count, expected in ((0, 0), (64, 0), (65, 1), (128, 1), (129, 2)):
            raw = fixture(count)
            changed, report = banks.bank_dispatch_flow(raw, "GetPouchContent")
            self.assertEqual(report["banks"], expected)
            self.assertEqual(changed == raw, expected == 0)
        raw = native_flow()
        self.assertEqual(banks.bank_dispatch_flow(raw, "GetPouchContent")[0], raw)
        with self.assertRaises(ValueError):
            banks.bank_dispatch_flow(raw, "Unknown")

    def test_complete_repeat_is_byte_identical_and_does_not_add_nodes(self):
        raw, first = banks.bank_dispatch_flow(fixture(513), "GetPouchContent")
        result, repeat = banks.bank_dispatch_flow(raw, "GetPouchContent")
        self.assertEqual(result, raw)
        self.assertFalse(repeat["changed"])
        self.assertTrue(repeat["validated_existing"])
        self.assertEqual(repeat["banks"], first["banks"])

    def test_tampered_plain_string_argument_partial_bank_and_continuation_are_rejected(self):
        raw, _ = banks.bank_dispatch_flow(fixture(130), "GetPouchContent")
        for mode in ("string", "missing", "entry", "return", "extra"):
            editor = FlowEditor(raw, "tamper")
            call = next(event for event in editor.chart.events if event.name.startswith(banks.PREFIX))
            if mode == "string":
                call.data.params.data["ActorName"] = "ActorName"
            elif mode == "missing":
                del call.data.params.data["ActorName"]
            elif mode == "entry":
                editor.chart.entry_points = [p for p in editor.chart.entry_points if p.name != call.data.entry_point_name]
            elif mode == "return":
                call.data.nxt = make_index(editor.chart.events[0])
            else:
                call.data.params.data["Unrelated"] = Argument("Unrelated")
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                banks.bank_dispatch_flow(serialize(editor), "GetPouchContent")

    def test_unrecognized_query_and_invented_identity_are_rejected(self):
        for field, value in (("GameDataName", "OtherScratch"), ("Index", True), ("Value", "NativeActor")):
            editor = FlowEditor(fixture(70), "bad signature")
            event = next(event for event in editor.chart.events if isinstance(event.data, SwitchEvent))
            event.data.params.data[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                banks.bank_dispatch_flow(serialize(editor), "GetPouchContent")

    def test_bank_variable_defaults_and_raw_subflow_index_tampering_are_rejected(self):
        raw, _ = banks.bank_dispatch_flow(fixture(130), "GetPouchContent")
        editor = FlowEditor(raw, "variable tamper")
        point = next(point for point in editor.chart.entry_points if point.name.startswith(banks.PREFIX))
        point.variable_defs["ActorName"] = VariableDef.from_value(1)
        with self.assertRaises(ValueError):
            banks.bank_dispatch_flow(serialize(editor), "GetPouchContent")
        # The normal writer repairs this table automatically, so corrupt its
        # raw index while keeping every pointer and count structurally valid.
        raw = bytearray(raw)
        array = struct.unpack_from("<Q", raw, 0x28)[0]
        chart = struct.unpack_from("<Q", raw, array)[0]
        points = struct.unpack_from("<Q", raw, chart + 0x40)[0]
        index = next(i for i, point in enumerate(FlowEditor(bytes(raw), "raw tamper").chart.entry_points)
                     if point.name.startswith(banks.PREFIX) and point._sub_flow_event_indices)
        indices = struct.unpack_from("<Q", raw, points + index * 32)[0]
        struct.pack_into("<H", raw, indices, 0)
        with self.assertRaises(ValueError):
            banks.bank_dispatch_flow(bytes(raw), "GetPouchContent")

    def test_unrelated_nodes_actor_methods_entry_targets_and_true_edges_are_unchanged(self):
        before = fixture(1940)
        after, report = banks.bank_dispatch_flow(before, "GetPouchContent")
        a = FlowEditor(before, "before").chart
        b = FlowEditor(after, "after").chart
        self.assertEqual([(str(x.identifier), [h.v for h in x.actions], [h.v for h in x.queries]) for x in a.actors],
                         [(str(x.identifier), [h.v for h in x.actions], [h.v for h in x.queries]) for x in b.actors])
        self.assertEqual(a.entry_points[0].main_event.v.name, b.entry_points[0].main_event.v.name)
        targets = {event.name: event for event in b.events}
        for event in a.events:
            other = targets[event.name]
            self.assertIs(type(other.data), type(event.data))
            if isinstance(event.data, SwitchEvent):
                self.assertEqual(other.data.cases[0].v.name, event.data.cases[0].v.name)
        self.assertEqual(report["banks"], 30)

    def test_entry_scoped_native_participant_is_forwarded_without_rebinding_its_scope(self):
        editor = FlowEditor(fixture(130, "Dm_SY_Get"), "native actor argument")
        owner = Actor()
        owner.identifier = ActorIdentifier("NativeGuest", "CanonicalEntry(Actor)")
        owner.argument_name = "Actor"
        owner.argument_entry_point = make_index(editor.chart.entry_points[0])
        owner.actions = [StringHolder("FixtureFallback")]
        editor.chart.actors.append(owner)
        fallback = next(event for event in editor.chart.events if event.name == "NativeFallback")
        fallback.data.actor = make_rindex(owner)
        fallback.data.actor_action = make_rindex(owner.actions[0])
        before = serialize(editor)
        after, _ = banks.bank_dispatch_flow(before, "Dm_SY_Get")
        chart = FlowEditor(after, "native actor argument").chart
        actual = next(actor for actor in chart.actors if actor.identifier == owner.identifier)
        self.assertEqual(actual.argument_name, "Actor")
        self.assertEqual(actual.argument_entry_point.v.name, "Dm_SY_Get")
        self.assertEqual([holder.v for holder in actual.actions], ["FixtureFallback"])
        calls = [event for event in chart.events if event.name.startswith(banks.PREFIX)]
        self.assertTrue(calls)
        for call in calls:
            self.assertIsInstance(call.data.params.data["Actor"], Argument)
        args = dict(Actor=ActorIdentifier("ActualNpc"), ActorName="Other", IsGetInEvent=False,
                    IsShowNumDisplay=True, IsTreasureBox=False)
        self.assertEqual(outcome(before, "NativeActor", args), outcome(after, "NativeActor", args))

    def test_staging_grows_only_owned_flow_allocations_and_repeat_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            game, mod = Path(tmp) / "game", Path(tmp) / "mods/Archipelago/romfs"
            path = "Event/EventFlow/GetPouchContent.bfevfl.zs"
            raw = fixture(321)
            resources = {"Pack/ZsDic.pack.zs": b"dictionary", path: raw,
                         banks.REST: table([(path.removesuffix(".zs"), len(raw) + 4096), ("Unrelated", 777)])}
            for name, data in resources.items():
                target = game / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            (mod / path).parent.mkdir(parents=True)
            (mod / path).write_bytes(raw)
            with patch("ootrr_triforce.mod_codec.Codec", IdentityCodec):
                report = banks.prepare_dispatch_banks(game, mod)
                self.assertTrue(report["flows"])
                rst = (mod / banks.REST).read_bytes()
                self.assertGreaterEqual(allocation(rst, path.removesuffix(".zs")), len(raw) + 4096)
                self.assertEqual(allocation(rst, "Unrelated"), 777)
                snapshot = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in mod.rglob("*") if p.is_file()}
                self.assertEqual(banks.prepare_dispatch_banks(game, mod), {})
                self.assertEqual({p: (p.read_bytes(), p.stat().st_mtime_ns) for p in snapshot}, snapshot)
            self.assertEqual((game / path).read_bytes(), raw)

    def test_invalid_later_chart_fails_before_any_staged_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            game, mod = Path(tmp) / "game", Path(tmp) / "mods/Archipelago/romfs"
            (game / "Pack").mkdir(parents=True)
            (game / "Pack/ZsDic.pack.zs").write_bytes(b"dictionary")
            (mod / "Event/EventFlow").mkdir(parents=True)
            good = mod / "Event/EventFlow/GetPouchContent.bfevfl.zs"
            bad = mod / "Event/EventFlow/Dm_SY_Get.bfevfl.zs"
            good.write_bytes(fixture(100))
            bad.write_bytes(fixture(100, "OtherChart"))
            snapshot = {p: p.read_bytes() for p in (good, bad)}
            with patch("ootrr_triforce.mod_codec.Codec", IdentityCodec), self.assertRaises(ValueError):
                banks.prepare_dispatch_banks(game, mod)
            self.assertEqual({p: p.read_bytes() for p in snapshot}, snapshot)


if __name__ == "__main__":
    unittest.main()
