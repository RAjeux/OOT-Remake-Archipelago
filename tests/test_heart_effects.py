"""Execute heart recipes with queued writes; this model is not native gameplay."""
from collections import Counter
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from evfl.actor import Actor
from evfl.common import ActorIdentifier, Argument
from evfl.entry_point import EntryPoint
from evfl.event import ActionEvent, SubFlowEvent, SwitchEvent
from evfl.util import make_index
from oot_rando.patching.progressive import FlowEditor, link
from ootrr_triforce import restoration, receipt_events
from ootrr_triforce.ap_skulls import patch_skull_flow, patch_pickup_presentation, skull_records
from ootrr_triforce.catalog import ITEM_DATA, ITEM_IDS
from ootrr_triforce.native_presentations import append_local_chests, is_cure, owns_health_refresh
from ootrr_triforce.shop_events import patch_shop_flow, ENTRY as SHOP_ENTRY, SELECTED
from test_network_flows import editor as empty_editor
from test_presented_receipts import native_presenter, native_facing_animation, CAMERA_FACING_FLOW
from test_receipt_events import native_flow
from test_restoration import pouch, reward, CHEST
from test_shop_events import native_shop, records as shop_records
from test_skull_events import native_flow as pickup_native, ground_flow, roster as skull_roster

TOKEN = "e" * 64
CURSOR = receipt_events.CURSOR_PREFIX + TOKEN
HEARTS = ("Heart Container", "Piece of Heart")


class HeartRun:
    """FIFO pouch/GameData effects with an explicit simplified life model.

    Native controls distinguish presented hearts' ownership-only pouch add,
    quiet hearts' automatic effects and the cure action. Effects remain
    queued until a FIFO barrier, so early source/cursor commits fail.
    """
    def __init__(self, charts, *, piece_count=0, max_life=16, selected=None, commits=()):
        self.charts = {name: FlowEditor(raw, name).chart for name, raw in charts.items()}
        self.entries = {name: {p.name: p.main_event.v for p in chart.entry_points}
                        for name, chart in self.charts.items()}
        self.inventory = Counter({"Obj_Heart_Piece": piece_count})
        self.max_life = max_life
        self.values = {"Fixture.NativeHookEnabled": True}
        if selected:
            self.values[SELECTED] = selected
        self.pending = []
        self.trace = []
        self.commits = set(commits)
        self.cures = 0
        self.grants = 0
        self.opened = 0
        self.saved = []

    def flush(self):
        for kind, key, value in self.pending:
            if kind == "pouch":
                count, in_event = value if isinstance(value, tuple) else (value, False)
                # Presented hearts wait for the cure; quiet/physical hearts
                # apply their effects in the native pouch command.
                heart = key in {"Obj_Heart_Container", "Obj_Heart_Piece"}
                if not heart or not in_event:
                    self.inventory[key] += count
                if key == "Obj_Heart_Container" and not in_event:
                    self.max_life = min(80, self.max_life + 4)
                if key == "Obj_Heart_Piece" and self.inventory[key] >= 4:
                    self.inventory[key] -= 4
                    self.max_life = min(80, self.max_life + 4)
            elif kind == "cure":
                if key == "Obj_Heart_Container":
                    self.max_life = min(80, self.max_life + 4)
                elif key == "Obj_Heart_Piece":
                    # Native causal control: applying Cure again after a
                    # settled fourth-piece pouch grant creates an extra piece.
                    self.inventory[key] += 1
                    if self.inventory[key] >= 4:
                        self.inventory[key] -= 4
                        self.max_life = min(80, self.max_life + 4)
            elif kind == "add":
                self.values[key] = self.values.get(key, 0) + value
            else:
                self.values[key] = value
        self.pending.clear()

    def call(self, flow, entry, arguments=None):
        arguments = arguments or {}
        node = self.entries[flow][entry]
        steps = 0
        while node is not None:
            steps += 1
            assert steps < 10000, "Heart route loops"
            data = node.data
            params = {key: arguments[value] if isinstance(value, Argument) else value
                      for key, value in (data.params.data.items() if data.params else ())}
            if isinstance(data, ActionEvent):
                command = data.actor_action.v.v
                self.trace.append((command, dict(params), self.max_life))
                if command == "EventTriggerAddOrRemovePouchContent":
                    self.pending.append(("pouch", params["Actor"], (params["Num"], params.get("IsGetEvent", False))))
                    self.grants += 1
                elif command == "EventTriggerRecoverByCureItem":
                    actor = params["ActorName"]
                    assert actor in {ITEM_DATA[name]["actor"] for name in HEARTS}
                    assert not self.pending, "Cure before native pouch writes settled"
                    self.pending.append(("cure", actor, None))
                    self.cures += 1
                elif command == "EventWait" and str(data.actor.v.identifier) == "EventSystemActor":
                    assert params == {"Frames": 1, "IsWaitEnd": True}
                    self.flush()
                elif command in {"EventTriggerSetGameDataBool", "EventTriggerSetGameDataInt",
                                  "EventTriggerSetGameDataString64", "EventTriggerAddOrSubGameDataInt"}:
                    key = params["GameDataName"]
                    assert not key.startswith("PlayerStatus."), "Life must use the native cure action"
                    if key in self.commits:
                        assert not any(kind in {"pouch", "cure"} for kind, _, _ in self.pending), "Commit before heart effects settled"
                    self.pending.append(("add" if command == "EventTriggerAddOrSubGameDataInt" else "set", key, params["Value"]))
                elif command == "EventTriggerTreasureBoxOpened":
                    assert not self.pending, "Chest committed before its heart effect settled"
                    self.opened += 1
                elif command == "EventTriggerRequestAutoSave":
                    self.flush()
                    self.saved.append((self.max_life, dict(self.inventory), dict(self.values)))
                node = data.nxt.v
            elif isinstance(data, SwitchEvent):
                query = data.actor_query.v.v
                if query == "EventQueryIsGameDataBool":
                    case = 0 if self.values.get(params["GameDataName"], False) else 1
                elif query == "EventQueryIsGameDataString64":
                    case = 0 if self.values.get(params["GameDataName"]) == params["Value"] else 1
                elif query == "EventQueryCheckIsGet":
                    case = 0 if self.inventory.get(params["ActorName"], 0) else 1
                elif query in {"FixtureIsImportant", "EventQueryCanAddToPorchByGameData", "EventQueryIsAnyBottleEmpty",
                               "EventQueryPouchContentGetType"}:
                    case = 0
                elif query == "EventQueryIsAutoSavePouchContent":
                    case = 1
                else:
                    raise AssertionError("Unexpected heart query: " + query)
                target = data.cases.get(case)
                node = target.v if target is not None else None
            elif isinstance(data, SubFlowEvent):
                target = data.res_flowchart_name or flow
                entry = data.entry_point_name
                if target == "Dm_SY_Get" and entry == "CheckHeart":
                    # Legacy authored path retained; never silently ignore a
                    # duplicate actual-heart refresh in a new presentation.
                    self.trace.append(("NativeCheckHeart", dict(params), self.max_life))
                    self.flush()
                    if params["ActorName"] in {"Obj_Heart_Container", "Obj_Heart_Piece"}:
                        self.pending.append(("cure", params["ActorName"], None))
                        self.flush()
                elif entry not in {"DisplayGetByActorName", "OpenGetWindow", "OpenRupeeUIIfNeed", "CloseRupeeUIIfNeed"}:
                    self.call(target, entry, params)
                node = data.nxt.v
            else:
                raise AssertionError(type(data).__name__)
        return self

    def assert_effect_order(self, test, *, commit=None):
        test.assertEqual(self.grants, 1)
        commands = [row[0] for row in self.trace]
        give = commands.index("EventTriggerAddOrRemovePouchContent")
        waits = [i for i, row in enumerate(self.trace) if row[0] == "EventWait" and row[1] == {"Frames": 1, "IsWaitEnd": True}]
        piece = self.trace[give][1]["Actor"] == "Obj_Heart_Piece"
        needs_cure = self.trace[give][1].get("IsGetEvent", False)
        test.assertEqual(self.cures, int(needs_cure))
        if not needs_cure:
            test.assertNotIn("EventTriggerRecoverByCureItem", commands)
        else:
            cure = commands.index("EventTriggerRecoverByCureItem")
            test.assertGreaterEqual(sum(give < i < cure for i in waits), 2)
        if commit:
            done = next(i for i, row in enumerate(self.trace) if row[1].get("GameDataName") == commit)
            test.assertGreaterEqual(sum((cure if needs_cure else give) < i < done for i in waits), 2 if needs_cure else 4)
        test.assertNotIn("NativeCheckHeart", commands)


class HeartEffectTests(unittest.TestCase):
    def test_growth_is_not_reclassified_as_a_consumable_cure(self):
        for name in HEARTS:
            self.assertFalse(is_cure(ITEM_DATA[name]))
            self.assertTrue(owns_health_refresh(ITEM_DATA[name]))
        self.assertFalse(owns_health_refresh(ITEM_DATA["Rupees (20)"]))

    def test_presented_receipts_settle_before_one_ack_and_one_effect(self):
        raw, shown, _ = receipt_events.build_presented_receipts(native_flow(), native_presenter(), TOKEN, HEARTS)
        charts = {"GetPouchContent": raw, "Dm_SY_GetInEvent": shown, CAMERA_FACING_FLOW: native_facing_animation()}
        for name in HEARTS:
            with self.subTest(item=name):
                run = HeartRun(charts, piece_count=3, commits=[CURSOR])
                run.call("GetPouchContent", receipt_events.event_name(ITEM_IDS[name]))
                run.assert_effect_order(self, commit=CURSOR)
                self.assertEqual(run.values[CURSOR], 1)
                self.assertEqual(run.max_life, 20)
                self.assertTrue(run.saved)
                self.assertTrue(all(snapshot[0] == 20 and snapshot[2][CURSOR] == 1 for snapshot in run.saved))

    def test_shop_commit_and_retries_never_duplicate_growth(self):
        for name in HEARTS:
            with self.subTest(item=name):
                record = shop_records()[0]
                record.update(local_item=name, native_actor=ITEM_DATA[name]["actor"])
                raw = patch_shop_flow(native_shop(), [record], pouch_raw=native_flow())
                run = HeartRun({"DisplayShop": raw}, piece_count=3, selected=record["actor"], commits=[record["flag_name"]])
                run.call("DisplayShop", SHOP_ENTRY)
                run.assert_effect_order(self, commit=record["flag_name"])
                self.assertEqual(run.max_life, 20)
                run.call("DisplayShop", SHOP_ENTRY)
                self.assertEqual((run.grants, run.cures, run.max_life), (1, 1, 20))

    def test_old_save_restoration_is_quiet_once_and_never_acks_network(self):
        for name in HEARTS:
            with self.subTest(item=name):
                raw, entries = restoration.build_restoration_flow(pouch(), {CHEST: reward(name)})
                record = restoration.restoration_records({CHEST: reward(name)})[0]
                run = HeartRun({"GetPouchContent": raw}, piece_count=3, commits=record["flags"])
                entry = next(iter(entries.values()))
                run.call("GetPouchContent", entry)
                run.assert_effect_order(self, commit=record["flags"][0])
                self.assertEqual(run.max_life, 20)
                self.assertFalse(any(row[1].get("GameDataName", "").startswith(receipt_events.CURSOR_PREFIX) for row in run.trace))
                run.call("GetPouchContent", entry)
                self.assertEqual((run.grants, run.cures, run.max_life), (1, 0, 20))

    def test_physical_pickup_normal_and_guest_effect_callbacks_apply_once(self):
        for name in HEARTS:
            records = skull_records(skull_roster([name]))
            raw, effects = patch_skull_flow(pickup_native(), records, return_entries=True)
            record = records[0]
            for quiet in (False, True):
                with self.subTest(item=name, quiet=quiet):
                    run = HeartRun({"GetPouchContent": raw}, piece_count=3, commits=[record["flag_name"]])
                    if quiet:
                        entry, arguments = effects[record["actor"]], {}
                    else:
                        entry, arguments = "GetPouchContent", dict(ActorName=record["actor"], IsGetInEvent=False,
                                                                   IsShowNumDisplay=True, IsTreasureBox=False)
                    run.call("GetPouchContent", entry, arguments)
                    run.assert_effect_order(self, commit=record["flag_name"])
                    self.assertEqual(run.max_life, 20)
                    run.call("GetPouchContent", entry, arguments)
                    self.assertEqual((run.grants, run.cures, run.max_life), (1, 0, 20))

    def test_native_chest_commits_after_health_and_drops_outer_refresh(self):
        for name in HEARTS:
            source = empty_editor("Dm_SY_TreasureboxSmall")
            actor = Actor()
            actor.identifier = ActorIdentifier("TreasureBox_EventStarter")
            source.chart.actors.append(actor)
            get = source.subflow("NativeGet", "GetPouchContent", "GetPouchContentByActorNameForTreasureBox",
                                 {"ActorName": Argument("ContentName")})
            heart = source.subflow("NativeHeart", "Dm_SY_Get", "CheckHeart", {"ActorName": Argument("ContentName")})
            link(get, heart)
            entry = EntryPoint("Success_")
            entry.main_event = make_index(get)
            source.chart.entry_points.append(entry)
            entries = append_local_chests(source, native_flow(), [name])
            raw = source.write("Heart chest")[0]
            with self.subTest(item=name):
                run = HeartRun({"Dm_SY_TreasureboxSmall": raw}, piece_count=3)
                run.call("Dm_SY_TreasureboxSmall", entries[name])
                run.assert_effect_order(self)
                self.assertEqual((run.opened, run.max_life), (1, 20))

    def test_physical_outer_refresh_retains_marker_identity_and_cannot_double_growth(self):
        # Native AP marker PouchActorInfo has special=None, so the authored
        # outer CheckHeart does not treat it as a container/piece. Previewing
        # the actual item must not overwrite that outer argument.
        for name in HEARTS:
            with self.subTest(item=name):
                records = skull_records(skull_roster([name]))
                record = records[0]
                pouch_raw, effects = patch_skull_flow(pickup_native(), records, return_entries=True)
                ground = FlowEditor(ground_flow("Dm_SY_Get"), "native outer heart check")
                outer = ground.subflow("NativeHeartCheck", "", "CheckHeart", {"ActorName": Argument("ActorName")})
                notify = next(e for e in ground.chart.events if e.name == "NativeNotify")
                link(notify, outer)
                raw = patch_pickup_presentation(ground.write("native outer heart check")[0], records, effects, "Dm_SY_Get")
                run = HeartRun({"GetPouchContent": pouch_raw, "Dm_SY_Get": raw}, piece_count=3,
                               commits=[record["flag_name"]])
                run.call("Dm_SY_Get", "PouchAddItem", {"ActorName": record["actor"]})
                self.assertEqual((run.grants, run.cures, run.max_life), (1, 0, 20))
                checks = [row[1]["ActorName"] for row in run.trace if row[0] == "NativeCheckHeart"]
                self.assertEqual(checks, [record["actor"]])
                self.assertNotIn(ITEM_DATA[name]["actor"], checks)

    def test_legacy_receipts_retain_the_native_heart_refresh(self):
        raw, _ = receipt_events.build_receipt_flow(native_flow(), TOKEN, HEARTS)
        for name in HEARTS:
            with self.subTest(item=name):
                run = HeartRun({"GetPouchContent": raw}, piece_count=3, commits=[CURSOR])
                run.call("GetPouchContent", receipt_events.event_name(ITEM_IDS[name]))
                self.assertEqual(sum(row[0] == "NativeCheckHeart" for row in run.trace), 1)
                self.assertEqual(run.cures, 0)
                self.assertEqual(run.max_life, 20)
                refresh = next(i for i, row in enumerate(run.trace) if row[0] == "NativeCheckHeart")
                acknowledge = next(i for i, row in enumerate(run.trace) if row[1].get("GameDataName") == CURSOR)
                self.assertLess(refresh, acknowledge)
                self.assertEqual(run.trace[acknowledge][2], 20)
                self.assertEqual(run.values[CURSOR], 1)

    def test_four_piece_and_life_cap_model_is_explicitly_not_native_proof(self):
        raw, shown, _ = receipt_events.build_presented_receipts(native_flow(), native_presenter(), TOKEN, HEARTS)
        charts = {"GetPouchContent": raw, "Dm_SY_GetInEvent": shown, CAMERA_FACING_FLOW: native_facing_animation()}
        for pieces, life, expected in ((0, 16, (1, 16)), (3, 16, (0, 20)), (3, 80, (0, 80))):
            with self.subTest(pieces=pieces, life=life):
                run = HeartRun(charts, piece_count=pieces, max_life=life, commits=[CURSOR])
                run.call("GetPouchContent", receipt_events.event_name(ITEM_IDS["Piece of Heart"]))
                self.assertEqual((run.inventory["Obj_Heart_Piece"], run.max_life), expected)

    def test_native_piece_grant_followed_by_cure_is_a_detectable_duplicate(self):
        run=HeartRun({},piece_count=3,max_life=12)
        run.pending.append(("pouch","Obj_Heart_Piece",1));run.flush()
        self.assertEqual((run.inventory["Obj_Heart_Piece"],run.max_life),(0,16))
        run.pending.append(("cure","Obj_Heart_Piece",None));run.flush()
        self.assertEqual((run.inventory["Obj_Heart_Piece"],run.max_life),(1,16))

    def test_presented_piece_pouch_add_alone_does_not_credit_the_first_piece(self):
        # Pinned by the native first-receipt control: IsGet became true while
        # count/life remained zero/12. Quiet adds have a different contract.
        run = HeartRun({}, piece_count=0, max_life=12)
        run.pending.append(("pouch", "Obj_Heart_Piece", (1, True)))
        run.flush()
        self.assertEqual((run.inventory["Obj_Heart_Piece"], run.max_life), (0, 12))
        run.pending.append(("cure", "Obj_Heart_Piece", None))
        run.flush()
        self.assertEqual((run.inventory["Obj_Heart_Piece"], run.max_life), (1, 12))

    def test_quiet_container_already_grows_life_without_a_second_cure(self):
        # The same native old-save restoration grew 16 -> 24 with the extra
        # cure, and 16 -> 20 with only its original quiet pouch grant.
        run = HeartRun({}, max_life=16)
        run.pending.append(("pouch", "Obj_Heart_Container", (1, False)))
        run.flush()
        self.assertEqual(run.max_life, 20)
        run.pending.append(("cure", "Obj_Heart_Container", None))
        run.flush()
        self.assertEqual(run.max_life, 24)


if __name__ == "__main__":
    unittest.main()
