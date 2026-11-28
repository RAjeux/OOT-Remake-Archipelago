"""Old native local purchases gain AP tracking without replaying their rewards."""
import copy
import io
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
from evfl.event import ActionEvent, SwitchEvent
from evfl.flowchart import Flowchart
from evfl.util import make_index
from oot_rando.formats import byml_codec as by
from oot_rando.patching import chest_flags
from oot_rando.patching.progressive import FlowEditor
from oot_rando.patching.soul_adapter import murmur3
from ootrr_triforce import shop_tracking as tracking
from ootrr_triforce.catalog import ITEM_DATA, SHOP_CHECKS


def document(root):
    return by.dump(dict(root=root, version=7, endian="<"))


def records():
    names = list(SHOP_CHECKS)[:3]
    result = []
    for n, name in enumerate(names):
        row = dict(SHOP_CHECKS[name])
        row.update(name=name, actor="Item_AP_TrackingFixture" + str(n), price=20)
        if n != 2:
            item = "Rupees (20)" if n == 0 else "Progressive Hookshot"
            row.update(local_item=item, native_actor=ITEM_DATA[item]["actor"])
        result.append(row)
    return result


def native_flow():
    flow = EventFlow()
    flow.name = "GetPouchContent"
    flow.flowchart = Flowchart()
    flow.flowchart.name = flow.name
    actor = Actor()
    actor.identifier = ActorIdentifier("GameSystemActor")
    flow.flowchart.actors.append(actor)
    stream = io.BytesIO()
    assert flow.write(stream)
    editor = FlowEditor(stream.getvalue(), "native tracking fixture")
    from ootrr_triforce.ap_skulls import _after_writes
    targets = [_after_writes(editor, "Native" + str(n), None) for n in range(3)]
    query = editor.switch("Event10", "GameDataActor", tracking.INT_QUERY,
                          dict(GameDataName="Market_MiniGame_ChoiceTreasure_NumOfHit", Index=-1, Value=4), None, None)
    query.data.cases = {n: make_index(target) for n, target in enumerate(targets)}
    point = EntryPoint("Native")
    point.main_event = make_index(query)
    editor.chart.entry_points.append(point)
    return editor.write("native tracking fixture")[0]


def game_data(rows):
    fields = dict(Int=[dict(Hash=by.U32(1234), DefaultValue=0, SaveFileIndex=-1, ResetTypeValue=8)], Bool=[])
    for record in rows:
        fields["Bool"].append(dict(Hash=by.U32(murmur3(record["flag_name"])), DefaultValue=False,
                                   SaveFileIndex=0, ResetTypeValue=8))
        fields["Int"].extend(dict(Hash=by.U32(murmur3(name)), DefaultValue=0, SaveFileIndex=0, ResetTypeValue=8)
                             for name in record["counters"])
    return document(dict(Data=fields, MetaData=dict(SaveDataSize=[100, 56], SaveDataOffsetPos=[100, 56],
                                                   AllDataSaveSize=130, AllDataSaveOffset=145)))


class QuietRun:
    """Queued native GameData writes, flush barriers, and observed saves."""
    def __init__(self, raw, values):
        self.chart = FlowEditor(raw, "tracking execution").chart
        self.values = dict(values)
        self.queue = []
        self.writes = []
        self.saves = []
        self.inventory = dict(rupees=83, hookshot=1, receipt_cursor=7)

    def flush(self):
        for key, value in self.queue:
            self.values[key] = value
        self.queue.clear()

    def run(self):
        before = dict(self.inventory)
        node = next(e.main_event.v for e in self.chart.entry_points if e.name == tracking.ENTRY)
        count = 0
        while node is not None:
            count += 1
            assert count < 10000, "Tracking graph loops"
            data = node.data
            params = data.params.data if data.params else {}
            if isinstance(data, ActionEvent):
                command = data.actor_action.v.v
                if command in ("EventTriggerSetGameDataBool", "EventTriggerSetGameDataInt"):
                    self.queue.append((params["GameDataName"], params["Value"]))
                    self.writes.append((command, dict(params)))
                elif command == "EventWait":
                    assert params == {"Frames": 1, "IsWaitEnd": True}
                    assert str(data.actor.v.identifier) == "EventSystemActor"
                    self.flush()
                elif command == "EventTriggerRequestAutoSave":
                    assert not self.queue, "Persistent writes must settle before save"
                    self.saves.append(dict(self.values))
                else:
                    raise AssertionError("Non-quiet operation: " + command)
                node = data.nxt.v
            elif isinstance(data, SwitchEvent):
                query = data.actor_query.v.v
                value = self.values.get(params["GameDataName"], 0)
                if query == "EventQueryIsGameDataBool":
                    case = 0 if value else 1
                else:
                    assert query == tracking.INT_QUERY
                    case = 0 if value < params["Value"] else 1 if value == params["Value"] else 2
                node = data.cases[case].v
            else:
                raise AssertionError("Tracking called a purchase or receipt flow")
        self.flush()
        assert self.inventory == before
        assert self.values[tracking.RESULT] == 1
        return self

    @property
    def persistent_writes(self):
        return [(command, values) for command, values in self.writes if values["GameDataName"] != tracking.RESULT]


class IdentityCodec:
    def __init__(self, dictionary):
        pass

    def decode(self, raw):
        return raw

    def encode(self, raw, original):
        return raw


class ShopTrackingTests(unittest.TestCase):
    def setUp(self):
        self.records = records()
        self.locals = tracking._local_records(self.records)
        self.native = native_flow()
        self.flow, changed = tracking.build_tracking_flow(self.native, self.records)
        self.assertTrue(changed)

    def state(self):
        return {key: value for record in self.records
                for key, value in [(record["flag_name"], False)] + [(name, 0) for name in record["counters"]]}

    def test_original_native_graph_unchanged_and_program_idempotent(self):
        original = FlowEditor(self.native, "before").chart
        final = FlowEditor(self.flow, "after").chart
        self.assertEqual([tracking._signature(e) for e in original.events],
                         [tracking._signature(e) for e in final.events[:len(original.events)]])
        self.assertEqual(tracking.build_tracking_flow(self.flow, self.records), (self.flow, False))
        self.assertEqual(tracking.build_tracking_flow(self.native, [self.records[2]]), (self.native, False))

    def test_legacy_local_purchase_tracks_once_without_inventory_effect(self):
        state = self.state()
        for record in self.locals:
            state[record["counters"][-1]] = 1
        # A foreign old shelf remains outside this local-inventory repair.
        state[self.records[2]["counters"][0]] = 1
        run = QuietRun(self.flow, state).run()
        self.assertEqual(len(run.saves), 1)
        for record in self.locals:
            self.assertIs(run.values[record["flag_name"]], True)
            self.assertTrue(all(run.values[name] == 1 for name in record["counters"]))
        self.assertFalse(run.values[self.records[2]["flag_name"]])
        self.assertEqual(run.saves[0][tracking.RESULT], -1)
        again = QuietRun(self.flow, run.values).run()
        self.assertEqual(again.persistent_writes, [])
        self.assertEqual(again.saves, [])

    def test_missing_age_stock_is_repaired_only_when_check_is_owned(self):
        for stock in (0, -1):
            with self.subTest(stock=stock):
                state = self.state()
                record = self.locals[0]
                state[record["flag_name"]] = True
                state[record["counters"][0]] = stock
                run = QuietRun(self.flow, state).run()
                self.assertEqual(len(run.saves), 1)
                self.assertTrue(all(run.values[name] == 1 for name in record["counters"]))

    def test_clean_room_and_complete_purchases_do_not_save_or_write_stock(self):
        for purchased in (False, True):
            with self.subTest(purchased=purchased):
                state = self.state()
                for record in self.locals:
                    state[record["flag_name"]] = purchased
                    for counter in record["counters"]:
                        state[counter] = 3 if purchased else -1
                run = QuietRun(self.flow, state).run()
                self.assertEqual(run.persistent_writes, [])
                self.assertEqual(run.saves, [])

    def test_all_64_native_shelves_share_one_quiet_save(self):
        rows = []
        for index, (name, native) in enumerate(SHOP_CHECKS.items()):
            rows.append(dict(native, name=name, actor="Item_AP_AllTracking" + str(index), price=10,
                             local_item="Rupees (20)", native_actor=ITEM_DATA["Rupees (20)"]["actor"]))
        raw, changed = tracking.build_tracking_flow(self.native, rows)
        self.assertTrue(changed)
        values = {name: 0 for row in rows for name in row["counters"]}
        for row in rows:
            values[row["flag_name"]] = False
            values[row["counters"][-1]] = 1
        run = QuietRun(raw, values).run()
        self.assertEqual(len(run.saves), 1)
        self.assertTrue(all(run.values[row["flag_name"]] for row in rows))
        self.assertTrue(all(run.values[name] == 1 for row in rows for name in row["counters"]))
        again = QuietRun(raw, run.values).run()
        self.assertEqual(again.persistent_writes, [])
        self.assertEqual(again.saves, [])

    def test_registered_fields_are_typed_persistent_and_collision_free(self):
        self.assertEqual(murmur3(tracking.RESULT), 0x7F2414C7)
        raw = game_data(self.locals)
        self.assertFalse(tracking.validate_fields(raw, self.locals))
        from ootrr_triforce.cursor_resource import append_transient_index
        status = append_transient_index(raw, murmur3(tracking.RESULT))
        self.assertTrue(tracking.validate_fields(status, self.locals))
        doc = by.load(raw)
        for field, value in (("ResetTypeValue", 2), ("SaveFileIndex", -1), ("DefaultValue", False)):
            bad = copy.deepcopy(doc)
            bad["root"]["Data"]["Int"][1][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                tracking.validate_fields(by.dump(bad), self.locals)
        for mode in ("missing", "duplicate", "wrongkind"):
            bad = copy.deepcopy(doc)
            row = bad["root"]["Data"]["Int"][1]
            if mode == "missing":
                bad["root"]["Data"]["Int"].remove(row)
            elif mode == "duplicate":
                bad["root"]["Data"]["Int"].append(copy.deepcopy(row))
            else:
                bad["root"]["Data"].setdefault("UInt", []).append(copy.deepcopy(row))
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                tracking.validate_fields(by.dump(bad), self.locals)
        with patch("oot_rando.patching.soul_adapter.murmur3", return_value=1), self.assertRaises(ValueError):
            tracking.validate_fields(raw, self.locals)

    def test_unknown_query_and_tampered_owned_program_fail_closed(self):
        tracking.validate_native_query(self.native)
        editor = FlowEditor(self.native, "bad ABI")
        next(e for e in editor.chart.events if e.name == "Event10").data.params.data["Value"] = 3
        with self.assertRaises(ValueError):
            tracking.validate_native_query(editor.write("bad ABI")[0])
        editor = FlowEditor(self.flow, "bad tracking")
        node = next(e for e in editor.chart.events if e.name.endswith("_MarkDirty"))
        node.data.params.data["Value"] = 0
        with self.assertRaises(ValueError):
            tracking.build_tracking_flow(editor.write("bad tracking")[0], self.records)

    def test_native_fifo_binding_is_preserved_and_unknown_binding_rejected(self):
        from oot_rando.patching.event_patch import GAMEDATA_ACTOR_PARAMS
        old = FlowEditor(self.native, "old wait").chart
        new = FlowEditor(self.flow, "new wait").chart
        original = next(a for a in old.actors if str(a.identifier) == "EventSystemActor")
        resulting = next(a for a in new.actors if str(a.identifier) == "EventSystemActor")
        self.assertEqual(original.params.data, GAMEDATA_ACTOR_PARAMS)
        self.assertEqual(resulting.params.data, original.params.data)
        self.assertEqual(resulting.concurrent_clips, original.concurrent_clips)
        for native in (False, True):
            editor = FlowEditor(self.native if native else self.flow, "bad wait actor")
            actor = next(a for a in editor.chart.actors if str(a.identifier) == "EventSystemActor")
            actor.params.data["IsArgumentActor"] = True
            with self.subTest(native=native), self.assertRaises(ValueError):
                tracking.build_tracking_flow(editor.write("bad wait actor")[0], self.records)
        editor = FlowEditor(self.flow, "bad wait parameters")
        wait = next(e for e in editor.chart.events if e.name == tracking.PREFIX + "Flush0")
        wait.data.params.data["IsWaitEnd"] = False
        with self.assertRaises(ValueError):
            tracking.build_tracking_flow(editor.write("bad wait parameters")[0], self.records)

    def test_resource_registration_preserves_native_metadata_and_is_idempotent(self):
        from ootrr_triforce.medallions import REST
        with tempfile.TemporaryDirectory() as temp:
            romfs, mod = Path(temp) / "game", Path(temp) / "mods/Archipelago/romfs"
            resources = {
                "Pack/ZsDic.pack.zs": b"dictionary",
                tracking.FLOW_PATH: self.native,
                tracking.GAME_DATA: game_data(self.locals),
                chest_flags.EVENT_SETTINGS: document([dict(__RowId="Dm_SY_Get", EntryPointName="Dm_SY_Get", FixtureNative=True)]),
                chest_flags.ANALYZED: document([dict(__RowId="Dm_SY_Get", SubFlowList=["KeepNative"], IsPlayerEventStartWithClimb=True)]),
                REST: b"sizes",
            }
            for path, raw in resources.items():
                target = romfs / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            mod.mkdir(parents=True)
            with patch.object(tracking, "Codec", IdentityCodec), patch("ootrr_triforce.ap_shops.shop_records", return_value=self.records), \
                    patch("oot_rando.game.resource_allocations.grow_resources", side_effect=lambda raw, sizes: (raw, len(sizes))):
                result = tracking.prepare_shop_tracking(romfs, mod, {}, {})
                self.assertEqual((result["shops"], result["changed"]), (2, True))
                setting = by.load((mod / chest_flags.EVENT_SETTINGS).read_bytes())["root"]
                analysis = by.load((mod / chest_flags.ANALYZED).read_bytes())["root"]
                self.assertEqual(next(r for r in setting if r["__RowId"] == "Dm_SY_Get"),
                                 by.load(resources[chest_flags.EVENT_SETTINGS])["root"][0])
                quiet = next(r for r in analysis if r["__RowId"] == tracking.ENTRY)
                self.assertEqual(quiet["SubFlowList"], ["GetPouchContent"])
                self.assertNotIn("ChildEventList", quiet)
                before = {p.relative_to(mod).as_posix(): p.read_bytes() for p in mod.rglob("*") if p.is_file()}
                self.assertEqual(tracking.prepare_shop_tracking(romfs, mod, {}, {}), dict(shops=2, changed=False))
                self.assertEqual(before, {p.relative_to(mod).as_posix(): p.read_bytes() for p in mod.rglob("*") if p.is_file()})
                self.assertEqual(by.load(resources[tracking.GAME_DATA])["root"]["MetaData"],
                                 by.load((mod / tracking.GAME_DATA).read_bytes())["root"]["MetaData"])
                # Corrupted persisted capability fails before touching any resource.
                bad = by.load((mod / tracking.GAME_DATA).read_bytes())
                next(r for r in bad["root"]["Data"]["Int"] if r["Hash"] == murmur3(tracking.RESULT))["SaveFileIndex"] = 0
                (mod / tracking.GAME_DATA).write_bytes(by.dump(bad))
                snapshot = {p: p.read_bytes() for p in mod.rglob("*") if p.is_file()}
                with self.assertRaises(ValueError):
                    tracking.prepare_shop_tracking(romfs, mod, {}, {})
                self.assertEqual(snapshot, {p: p.read_bytes() for p in mod.rglob("*") if p.is_file()})


if __name__ == "__main__":
    unittest.main()
