"""Spent trade-token replay acknowledges once without a misleading item scene."""
import io
import copy
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
from evfl.event import ActionEvent, SwitchEvent, SubFlowEvent
from evfl.flowchart import Flowchart
from evfl.util import make_index
from oot_rando.patching.event_patch import _flow, _snapshot
from oot_rando.patching.progressive import FlowEditor, link
from ootrr_triforce.catalog import ITEM_DATA, ITEM_IDS, TRADE_CHECKS
from ootrr_triforce.receipt_events import CURSOR_PREFIX, event_name
from ootrr_triforce.trade_catalog import TRADE_ITEMS
from ootrr_triforce.trade_receipts import patch_trade_receipt_guard, PREFIX
from ootrr_triforce import trade_receipts as replay

TOKEN = "abcdef0123456789" * 4
CURSOR = CURSOR_PREFIX + TOKEN


def receipt_fixture(*, cursor=CURSOR, local_helper=False):
    flow = EventFlow()
    flow.name = "GetPouchContent"
    flow.flowchart = Flowchart()
    flow.flowchart.name = flow.name
    for name in ("GameSystemActor", "EventSystemActor"):
        actor = Actor()
        actor.identifier = ActorIdentifier(name)
        flow.flowchart.actors.append(actor)
    stream = io.BytesIO()
    assert flow.write(stream)
    editor = FlowEditor(stream.getvalue(), "room-bound trade receipt fixture")
    for name in sorted(TRADE_ITEMS | {"Rupees (5)"}):
        stem = "Native" + str(ITEM_IDS[name])
        save = editor.action(stem + "Save", "GameSystemActor", "EventTriggerRequestAutoSave", None)
        wait = editor.action(stem + "Wait", "EventSystemActor", "EventWait", {"Frames": 1, "IsWaitEnd": True})
        link(wait, save)
        ack = editor.action(stem + "Ack", "GameDataActor", "EventTriggerAddOrSubGameDataInt",
                            {"GameDataName": cursor, "Index": -1, "Value": 1})
        link(ack, wait)
        give = editor.action(stem + "Give", "PouchSystemActor", "EventTriggerAddOrRemovePouchContent",
                             {"Actor": ITEM_DATA[name]["actor"], "Num": 1})
        link(give, ack)
        window = editor.action(stem + "Window", "PouchSystemActor", "EventTriggerSetForGetWindow",
                               {"Actor": ITEM_DATA[name]["actor"]})
        link(window, give)
        point = EntryPoint(event_name(ITEM_IDS[name]))
        if local_helper:
            helper = EntryPoint(stem + "Helper")
            helper.main_event = make_index(window)
            editor.chart.entry_points.append(helper)
            call = editor.subflow(stem + "Call", "", helper.name, None)
            point.main_event = make_index(call)
            point._sub_flow_event_indices = [editor.chart.events.index(call)]
        else:
            point.main_event = make_index(window)
        editor.chart.entry_points.append(point)
    return editor.write("original receipt fixture")[0]


def major_fixture():
    pouch = FlowEditor(receipt_fixture(), "major receipt pouch fixture")
    flow = EventFlow()
    flow.name = "Dm_SY_GetInEvent"
    flow.flowchart = Flowchart()
    flow.flowchart.name = flow.name
    stream = io.BytesIO()
    assert flow.write(stream)
    presenter = FlowEditor(stream.getvalue(), "major receipt presentation fixture")
    points = {point.name: point for point in pouch.chart.entry_points}
    for name in TRADE_ITEMS:
        item = ITEM_IDS[name]
        point = points[event_name(item)]
        core = EntryPoint(event_name(item) + "_Pouch")
        core.main_event = make_index(point.main_event.v)
        pouch.chart.entry_points.append(core)
        root = pouch.subflow("Show" + str(item), "Dm_SY_GetInEvent", "Show" + str(item), None)
        point.main_event = make_index(root)
        point._sub_flow_event_indices.append(pouch.chart.events.index(root))
        body = presenter.subflow("Core" + str(item), "GetPouchContent", core.name, None)
        show = EntryPoint("Show" + str(item))
        show.main_event = make_index(body)
        show._sub_flow_event_indices = [presenter.chart.events.index(body)]
        presenter.chart.entry_points.append(show)
    return pouch.write("major receipt pouch")[0], presenter.write("major receipt presenter")[0]


class Receipt:
    def __init__(self, raw, presenter_raw=None):
        chart = _flow(raw).flowchart
        self.entries = {point.name: point.main_event.v for point in chart.entry_points}
        self.charts = {chart.name: self.entries}
        if presenter_raw is not None:
            presenter = _flow(presenter_raw).flowchart
            self.charts[presenter.name] = {point.name: point.main_event.v for point in presenter.entry_points}
        self.values = {CURSOR: 7}
        self.pending, self.stock, self.trace, self.saves = {}, {}, [], []

    def run(self, entry, flow="GetPouchContent"):
        node = self.charts[flow][entry]
        while node is not None:
            data = node.data
            params = data.params.data if getattr(data, "params", None) else {}
            if isinstance(data, ActionEvent):
                command = data.actor_action.v.v
                self.trace.append(command)
                if command == "EventTriggerAddOrSubGameDataInt":
                    name = params["GameDataName"]
                    self.pending[name] = self.values.get(name, 0) + params["Value"]
                elif command == "EventWait":
                    self.values.update(self.pending)
                    self.pending.clear()
                elif command == "EventTriggerRequestAutoSave":
                    assert not self.pending, "The cursor must be visible before save"
                    self.saves.append(dict(self.values))
                elif command == "EventTriggerAddOrRemovePouchContent":
                    self.stock[params["Actor"]] = self.stock.get(params["Actor"], 0) + params["Num"]
                elif command != "EventTriggerSetForGetWindow":
                    raise AssertionError(command)
                node = data.nxt.v
            elif isinstance(data, SwitchEvent):
                assert data.actor_query.v.v == "EventQueryIsGameDataBool"
                node = data.cases[0 if self.values.get(params["GameDataName"]) else 1].v
            elif isinstance(data, SubFlowEvent):
                target = data.res_flowchart_name or flow
                assert target in self.charts
                self.run(data.entry_point_name, target)
                node = data.nxt.v
            else:
                raise AssertionError(type(data))


class TradeReplayTests(unittest.TestCase):
    def test_host_selected_replay_acknowledges_without_local_flags_presentation_or_reward(self):
        raw = patch_trade_receipt_guard(receipt_fixture(), TOKEN)
        for item, location in replay.replay_receipts().items():
            with self.subTest(item=item):
                run = Receipt(raw)
                run.run(replay.replay_event(item))
                self.assertFalse(run.stock)
                self.assertEqual(run.values, {CURSOR: 8})
                self.assertEqual(run.trace, ["EventTriggerAddOrSubGameDataInt", "EventWait", "EventTriggerRequestAutoSave"])
                self.assertEqual(run.saves, [{CURSOR: 8}])
                self.assertNotIn(location, run.values)

    def test_major_receipts_find_their_ack_across_the_real_two_chart_shape(self):
        pouch, presenter = major_fixture()
        with self.assertRaisesRegex(ValueError, "no room-bound acknowledgement"):
            patch_trade_receipt_guard(pouch, TOKEN)
        raw = patch_trade_receipt_guard(pouch, TOKEN, presenter_raw=presenter)
        name = "Prescription"
        spent = Receipt(raw, presenter)
        spent.values[TRADE_CHECKS["ZD Trade Prescription"]["flag_name"]] = True
        spent.run(event_name(ITEM_IDS[name]))
        self.assertEqual(spent.values[CURSOR], 8)
        self.assertFalse(spent.stock)
        self.assertNotIn("EventTriggerSetForGetWindow", spent.trace)
        fresh = Receipt(raw, presenter)
        fresh.run(event_name(ITEM_IDS[name]))
        self.assertEqual(fresh.values[CURSOR], 8)
        self.assertEqual(fresh.stock, {"Item_Prescription": 1})

    def test_every_spent_token_advances_the_bound_cursor_without_effect_or_presentation(self):
        raw = patch_trade_receipt_guard(receipt_fixture(), TOKEN)
        consumers = {row["required_actor"]: row for row in TRADE_CHECKS.values() if row["required_actor"]}
        for name in TRADE_ITEMS:
            with self.subTest(item=name):
                run = Receipt(raw)
                run.values[consumers[ITEM_DATA[name]["actor"]]["flag_name"]] = True
                run.run(event_name(ITEM_IDS[name]))
                self.assertFalse(run.stock)
                self.assertNotIn("EventTriggerSetForGetWindow", run.trace)
                self.assertEqual(run.trace, ["EventTriggerAddOrSubGameDataInt", "EventWait", "EventTriggerRequestAutoSave"])
                self.assertEqual(run.values[CURSOR], 8)
                self.assertEqual(run.saves[-1][CURSOR], 8)

    def test_unspent_tokens_keep_their_native_receipt(self):
        raw = patch_trade_receipt_guard(receipt_fixture(local_helper=True), TOKEN)
        for name in TRADE_ITEMS:
            with self.subTest(item=name):
                run = Receipt(raw)
                run.run(event_name(ITEM_IDS[name]))
                self.assertEqual(run.stock, {ITEM_DATA[name]["actor"]: 1})
                self.assertIn("EventTriggerSetForGetWindow", run.trace)
                self.assertEqual(run.values[CURSOR], 8)

    def test_only_the_matching_token_consumption_flag_suppresses_it(self):
        raw = patch_trade_receipt_guard(receipt_fixture(), TOKEN)
        run = Receipt(raw)
        run.values[TRADE_CHECKS["Kak Anju Trade Pocket Cucco"]["flag_name"]] = True
        run.run(event_name(ITEM_IDS["Cojiro"]))
        self.assertEqual(run.stock, {"Item_CojiroCucco": 1})

    def test_original_actions_and_non_trade_entry_are_preserved(self):
        before = receipt_fixture()
        after = patch_trade_receipt_guard(before, TOKEN)
        original = _flow(before)
        changed = _flow(after)
        snapshots = _snapshot(changed)
        self.assertTrue(all(snapshots[name] == params for name, params in _snapshot(original).items()))
        old = {point.name: point.main_event.v.name for point in original.flowchart.entry_points}
        now = {point.name: point.main_event.v.name for point in changed.flowchart.entry_points}
        self.assertEqual(old[event_name(ITEM_IDS["Rupees (5)"])], now[event_name(ITEM_IDS["Rupees (5)"])])
        run = Receipt(after)
        run.run(event_name(ITEM_IDS["Rupees (5)"]))
        self.assertEqual(run.values[CURSOR], 8)
        self.assertTrue(run.stock)

    def test_wrong_room_missing_ack_and_repatch_are_rejected(self):
        for token in (None, True, "abc", "A" * 64, "g" * 64):
            with self.subTest(token=token), self.assertRaises(ValueError):
                patch_trade_receipt_guard(receipt_fixture(), token)
        with self.assertRaisesRegex(ValueError, "different room"):
            patch_trade_receipt_guard(receipt_fixture(cursor=CURSOR_PREFIX + "0" * 64), TOKEN)
        raw = patch_trade_receipt_guard(receipt_fixture(), TOKEN)
        with self.assertRaises(ValueError):
            patch_trade_receipt_guard(raw, TOKEN)


class PreparedTradeReplayTests(unittest.TestCase):
    def resources(self):
        from oot_rando.formats import byml_codec as by
        doc = lambda rows: by.dump(dict(root=rows, endian="<", version=7))
        resources = {replay.FLOW_PATH: patch_trade_receipt_guard(receipt_fixture(), TOKEN)}
        resources.update(replay._register_quiet_events(doc([dict(__RowId="Dm_SY_Get")]), doc([])))
        return resources

    def finalize(self, folder):
        root = Path(folder)
        game, prepared = root / "game", root / "Archipelago/romfs"
        (game / "Pack").mkdir(parents=True)
        (game / "Pack/ZsDic.pack.zs").write_bytes(b"private dictionary fixture")
        resources = self.resources()
        for path, data in resources.items():
            target = prepared / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        class IdentityCodec:
            def __init__(self, pack): pass
            def decode(self, frame): return frame
        with patch.object(replay, "Codec", IdentityCodec):
            self.assertEqual(replay.finalize_trade_receipts(game, prepared, TOKEN), replay.replay_receipts())
        return prepared

    def test_registrations_require_only_the_quiet_pouch_event(self):
        resources = self.resources()
        replay._validate_quiet_resources(resources, TOKEN)
        with self.assertRaises(ValueError):
            replay._validate_quiet_resources(resources, "0" * 64)
        for path in (replay.SETTINGS, replay.ANALYZED):
            from oot_rando.formats import byml_codec as by
            broken = copy.deepcopy(resources)
            rows = by.load(broken[path])
            rows["root"] = [row for row in rows["root"] if row.get("__RowId") != replay.replay_event(ITEM_IDS["Cojiro"])]
            broken[path] = by.dump(rows)
            with self.subTest(resource=path), self.assertRaises(ValueError):
                replay._validate_quiet_resources(broken, TOKEN)
        broken = copy.deepcopy(resources)
        editor = FlowEditor(broken[replay.FLOW_PATH], "malformed quiet entry")
        point = next(point for point in editor.chart.entry_points if point.name == replay.replay_event(ITEM_IDS["Cojiro"]))
        point.main_event = make_index(next(point for point in editor.chart.entry_points if point.name == event_name(ITEM_IDS["Cojiro"])).main_event.v)
        broken[replay.FLOW_PATH] = editor.write("malformed quiet entry")[0]
        with self.assertRaises(ValueError):
            replay._validate_quiet_resources(broken, TOKEN)

    def test_final_marker_binds_room_exact_mapping_and_unchanged_resources(self):
        with tempfile.TemporaryDirectory() as folder:
            prepared = self.finalize(folder)
            self.assertEqual(replay.prepared_trade_receipts(prepared, TOKEN), replay.replay_receipts())
            with self.assertRaises(ValueError):
                replay.prepared_trade_receipts(prepared, "0" * 64)
            path = prepared / replay.FLOW_PATH
            path.write_bytes(path.read_bytes() + b"changed")
            with self.assertRaises(ValueError):
                replay.prepared_trade_receipts(prepared, TOKEN)

    def test_absent_legacy_marker_is_optional_but_wrong_pairs_and_malformed_marker_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(replay.prepared_trade_receipts(folder, TOKEN), {})
            prepared = self.finalize(folder)
            path = prepared / replay.MARKER
            original = json.loads(path.read_bytes())
            bad = copy.deepcopy(original)
            keys = list(bad["receipts"])
            bad["receipts"][keys[0]], bad["receipts"][keys[1]] = bad["receipts"][keys[1]], bad["receipts"][keys[0]]
            for data in (bad, [], {**original, "schema": True}, {**original, "resources": []}):
                with self.subTest(data_type=type(data).__name__):
                    path.write_text(json.dumps(data), encoding="utf-8")
                    with self.assertRaises(ValueError): replay.prepared_trade_receipts(prepared, TOKEN)


if __name__ == "__main__":
    unittest.main()
