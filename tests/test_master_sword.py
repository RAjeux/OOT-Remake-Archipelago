"""Pedestal ownership, time travel, AP fill and native reward transactions."""
from collections import Counter
import copy
import io
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from evfl import EventFlow
from evfl.actor import Actor
from evfl.common import ActorIdentifier
from evfl.entry_point import EntryPoint
from evfl.event import ActionEvent, SubFlowEvent, SwitchEvent
from evfl.flowchart import Flowchart
from evfl.util import make_index
from oot_rando.patching.event_info import reachable
from oot_rando.patching.progressive import FlowEditor, link
from oot_rando.patching.soul_adapter import murmur3
from ootrr_triforce import ap_master_sword as patcher
from ootrr_triforce.ap_trade import build_trade_rewards
from ootrr_triforce.catalog import CHECK_FLAGS, ITEM_IDS, LOCATION_IDS
from ootrr_triforce.master_sword import ACTOR, FLAG_NAME, ITEM, LOCATION, LOCATION_ID, proof_wave, token_material
from ootrr_triforce.player import preparation_settings, read_manifest
from ootrr_triforce.restoration import restoration_records
from ootrr_triforce.settings import default_options, engine_settings, yaml_options
from test_ap_trade import INFO, TradeRun, pouch_fixture, presenter_fixture, reward
import test_apworld as world_test
from test_apworld import State
from test_full_chests import fixture as room_fixture


def chart_fixture(name):
    flow = EventFlow()
    flow.name = name
    flow.flowchart = Flowchart()
    flow.flowchart.name = name
    for identifier in ("GameDataActor", "PouchSystemActor", "EventSystemActor"):
        actor = Actor()
        actor.identifier = ActorIdentifier(identifier)
        flow.flowchart.actors.append(actor)
    stream = io.BytesIO()
    assert flow.write(stream)
    return FlowEditor(stream.getvalue(), name)


def register(editor, name, root):
    point = EntryPoint(name)
    point.main_event = make_index(root)
    editor.chart.entry_points.append(point)


def added_sword(editor, name):
    return editor.action(name, "PouchSystemActor", "EventTriggerAddOrRemovePouchContent",
                         {"Actor": ACTOR, "Num": 1, "IsEquipDIrect": False,
                          "IsSetMessageTargetActorName": False, "IsGetEvent": False})


def draw_fixture():
    editor = chart_fixture(patcher.DOOR)
    native = added_sword(editor, "Event115")
    short = added_sword(editor, "OOTRRDraw218")
    gift = editor.action("RauruReward", "PouchSystemActor", "EventTriggerAddOrRemovePouchContent",
                         {"Actor": "Item_Token_Gold", "Num": 1, "IsEquipDIrect": False,
                          "IsSetMessageTargetActorName": False, "IsGetEvent": False})
    travel = editor.action("TimeTravel", "EventSystemActor", "EventTransition",
                           {"EventName": "Market_Child_Field_ChildToAdult"})
    later = editor.action("Event22", "EventSystemActor", "EventTransition",
                          {"EventName": "Market_Child_Field_ChildToAdult"})
    link(short, gift)
    link(gift, travel)
    register(editor, "DoorOfTime_Draw", short)
    register(editor, "SageRoom_MeetGanondorf", native)
    register(editor, "LaterDraw", later)
    return editor.write("draw fixture")[0]


def era_fixture():
    editor = chart_fixture(patcher.ERA)
    swap = editor.action("Event0", "GameDataActor", "EventTriggerCopyGameDataString64",
                         {"SrcGameDataName": "PlayerStatus.AnotherEraEquipWeapon",
                          "DstGameDataName": "PlayerStatus.EquipWeapon", "Index": -1, "SrcIndex": -1})
    forced = editor.action("Event5", "GameDataActor", "EventTriggerSetGameDataString64",
                           {"GameDataName": "PlayerStatus.AnotherEraEquipWeapon", "Value": ACTOR, "Index": -1})
    link(forced, swap)
    register(editor, patcher.ERA, forced)
    register(editor, "ExistingOtherEraEquipment", swap)
    return editor.write("era fixture")[0]


def run_simple(raw, entry, *, stock=0, values=None):
    chart = FlowEditor(raw, "native sword branch").chart
    node = next(point.main_event.v for point in chart.entry_points if point.name == entry)
    values, trace, pending = dict(values or {}), [], {}
    while node is not None:
        assert len(trace) < 100, "event loop"
        data = node.data
        params = data.params.data if data.params else {}
        trace.append(node.name)
        if isinstance(data, SwitchEvent):
            query = data.actor_query.v.v
            if query == "EventQueryIsExistInPouch":
                yes = stock >= params["Num"]
            elif query == "EventQueryIsGameDataString64":
                yes = values.get(params["GameDataName"], "") == params["Value"]
            elif query == "EventQueryIsGameDataBool":
                yes = bool(values.get(params["GameDataName"]))
            else:
                raise AssertionError(query)
            target = data.cases.get(0 if yes else 1)
            node = target.v if target else None
        elif isinstance(data, ActionEvent):
            action = data.actor_action.v.v
            if action == "EventTriggerSetGameDataString64":
                pending[params["GameDataName"]] = params["Value"]
            elif action == "EventTriggerCopyGameDataString64":
                pending[params["DstGameDataName"]] = values.get(params["SrcGameDataName"], "")
            elif action == "EventWait":
                values.update(pending)
                pending.clear()
            elif action == "EventTriggerAddOrRemovePouchContent":
                stock += params["Num"]
            else:
                raise AssertionError(action)
            node = data.nxt.v
        else:
            raise AssertionError(type(data))
    values.update(pending)
    return values, stock, trace


class MasterSwordTests(unittest.TestCase):
    def test_preparation_follows_the_room_without_retaining_another_rooms_sword_flag(self):
        config = {"assets": "cache", "shuffle_master_sword": True}
        self.assertEqual(preparation_settings(config, {"seed_file": {}}), {"assets": "cache"})
        enabled = preparation_settings({"assets": "cache"}, {"seed_file": {}, "shuffle_master_sword": True})
        self.assertIs(enabled["shuffle_master_sword"], True)
        self.assertIs(config["shuffle_master_sword"], True)

    def test_opt_in_option_does_not_change_portable_engine_input(self):
        self.assertIs(default_options()["shuffle_master_sword"], False)
        self.assertEqual(engine_settings({}), engine_settings({"shuffle_master_sword": True}))
        self.assertIn("  shuffle_master_sword: false\n", yaml_options())
        self.assertIn("Épée de légende", yaml_options(language="fr"))
        self.assertEqual(CHECK_FLAGS[LOCATION], [murmur3(FLAG_NAME)])
        self.assertEqual(LOCATION_IDS[LOCATION], LOCATION_ID)
        self.assertEqual(ITEM_IDS[ITEM], 0x6F71CC)

    def test_native_proof_is_required_and_not_modified(self):
        waves = [["Early chest"], ["ToT Reward from Rauru"], ["Ganon"]]
        before = copy.deepcopy(waves)
        self.assertEqual(proof_wave(waves), 1)
        self.assertEqual(proof_wave([["Early chest"], [], ["Ganon"]], 1), 1)
        for invalid in (None, -1, 3, True, "1"):
            with self.assertRaises(ValueError):
                proof_wave(waves, invalid)
        self.assertEqual(waves, before)
        for bad in ([], [["Ganon"]], [["ToT Reward from Rauru"], ["ToT Reward from Rauru"]]):
            with self.assertRaises(ValueError):
                proof_wave(bad)

    def test_ap_pool_adds_one_freely_placeable_item_and_conservative_later_gate(self):
        helper = world_test.AllChestRewardTests()
        def add(generated):
            generated["master_sword_wave"] = 0
        off, _, _ = helper.make_world(add)
        on, _, _ = helper.make_world(add, option_changes={"shuffle_master_sword": True})
        self.assertEqual(off.seed_file, on.seed_file)
        self.assertNotEqual(off.token, on.token)
        self.assertEqual(off.token, hashlib.sha256(
            f"{off.multiworld.seed_name}/{off.player}/{off.seed_file['checksum']}".encode()).hexdigest())
        self.assertNotIn(LOCATION, off.moved)
        self.assertEqual(on.moved[LOCATION], ITEM)
        self.assertEqual(len(on.moved), len(off.moved) + 1)
        on.create_items()
        on.create_regions()
        self.assertEqual(Counter(item.name for item in on.multiworld.itempool)[ITEM], 1)
        pedestal = next(location for region in on.multiworld.regions for location in region.locations
                        if location.name == LOCATION)
        self.assertTrue(pedestal.item_rule(type("Foreign", (), {"name": "A friend's item", "player": 2})()))
        old = Counter(off.moved.values())
        self.assertFalse(on.rules_at[1](State(**old)))
        self.assertFalse(on.multiworld.completion_condition[1](State(**old)))
        old[ITEM] += 1
        self.assertTrue(on.rules_at[1](State(**old)))
        self.assertTrue(on.multiworld.completion_condition[1](State(**old)))
        self.assertTrue(on.fill_slot_data()["shuffle_master_sword"])

    def test_manifest_is_explicit_and_keeps_canonical_seed_unchanged(self):
        original = room_fixture("complet-v2")
        original_seed = copy.deepcopy(original["seed_file"])
        enabled = copy.deepcopy(original)
        enabled["shuffle_master_sword"] = True
        enabled["checks"].append(LOCATION)
        enabled["moved"][LOCATION] = ITEM
        enabled["token"] = hashlib.sha256(token_material(enabled["room"], enabled["player"],
                                                        enabled["seed_file"]["checksum"], True).encode()).hexdigest()
        def read(data):
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "player.apootrr"
                path.write_text(json.dumps(data), encoding="utf-8")
                return read_manifest(path)
        self.assertEqual(read(original), original)
        self.assertEqual(read(enabled)["seed_file"], original_seed)
        for mutate in (lambda d: d.pop("shuffle_master_sword"),
                       lambda d: d.update(shuffle_master_sword="true"),
                       lambda d: d["checks"].remove(LOCATION)):
            bad = copy.deepcopy(enabled)
            mutate(bad)
            with self.assertRaises(ValueError):
                read(bad)
        records = restoration_records({LOCATION: reward(ITEM)})
        self.assertEqual(records[0]["flags"], [FLAG_NAME])

    def test_pedestal_replaces_both_sword_grants_preserving_rauru_and_time_travel(self):
        raw = draw_fixture()
        changed = patcher.patch_draw(raw)
        before, after = (FlowEditor(value, "draw").chart for value in (raw, changed))
        for name in ("DoorOfTime_Draw", "LaterDraw"):
            root = next(point.main_event.v for point in after.entry_points if point.name == name)
            calls = [node for node in reachable(root) if isinstance(node.data, SubFlowEvent)]
            self.assertEqual(len(calls), 1)
            self.assertEqual((calls[0].data.res_flowchart_name, calls[0].data.entry_point_name),
                             ("GetPouchContent", patcher.event_name(LOCATION_ID)))
            self.assertFalse(any(isinstance(node.data, ActionEvent) and node.data.params
                                 and node.data.params.data.get("Actor") == ACTOR for node in reachable(root)))
        for name in ("RauruReward", "TimeTravel"):
            old = next(node for node in before.events if node.name == name)
            new = next(node for node in after.events if node.name == name)
            self.assertEqual(old.data.params.data, new.data.params.data)
        first = next(point.main_event.v for point in after.entry_points if point.name == "DoorOfTime_Draw")
        self.assertEqual(first.name, "RauruReward")
        self.assertEqual(first.data.nxt.v.data.entry_point_name, patcher.event_name(LOCATION_ID))
        self.assertEqual(first.data.nxt.v.data.nxt.v.name, "TimeTravel")
        with self.assertRaises(ValueError):
            patcher.patch_draw(changed)

    def test_native_reward_callback_once_even_if_sword_was_received_before_draw(self):
        for item, local in (("Bow", True), (ITEM, True), ("Rupees (5)", False)):
            roster = {LOCATION: reward(item, local=local)}
            record = patcher.reward_record(roster)
            pouch, presenter, entries = build_trade_rewards(
                pouch_fixture(), presenter_fixture(), roster, native_info=INFO,
                records=[record], prefix=patcher.PREFIX, event_stem=patcher.event_name, reconcile=False)
            run = TradeRun(pouch, presenter)
            for raw in (pouch, presenter):
                chart = FlowEditor(raw, "Master reward preloads").chart
                for point in chart.entry_points:
                    for node in reachable(point.main_event.v):
                        if isinstance(node.data, SubFlowEvent) and node.name.startswith(patcher.PREFIX):
                            self.assertIn(chart.events.index(node), point._sub_flow_event_indices)
            run.inventory[ACTOR] = 1
            run.run(entries[LOCATION_ID])
            self.assertTrue(run.values[FLAG_NAME])
            inventory = run.inventory.copy()
            self.assertEqual(len(run.saves), 1)
            run.run(entries[LOCATION_ID])
            self.assertEqual(run.inventory, inventory)
            self.assertEqual(len(run.saves), 1)
            if local:
                self.assertGreater(run.inventory["Weapon_Range_Bow" if item == "Bow" else ACTOR], 0)
            else:
                self.assertEqual(run.inventory, Counter({ACTOR: 1}))
            self.assertFalse(any(params.get("GameDataName", "").startswith("Archipelago.ReceivedIndex.")
                                 for _, params in run.trace))

    def test_era_swap_equips_only_owned_sword_and_preserves_other_weapons(self):
        raw = patcher.patch_era_equipment(era_fixture())
        for owned in (0, 1):
            values, stock, _ = run_simple(raw, patcher.ERA, stock=owned)
            self.assertEqual(stock, owned)
            self.assertEqual(values["PlayerStatus.EquipWeapon"], ACTOR if owned else "")
            for stored in (ACTOR, "Weapon_Sword_Giant", "Weapon_Sword_Kokiri", ""):
                values, stock, _ = run_simple(raw, "ExistingOtherEraEquipment", stock=owned,
                                              values={"PlayerStatus.AnotherEraEquipWeapon": stored})
                self.assertEqual(stock, owned)
                self.assertEqual(values["PlayerStatus.EquipWeapon"], "" if stored == ACTOR and not owned else stored)

    def test_finale_recovers_only_a_legitimately_received_sword(self):
        editor = chart_fixture(patcher.FINAL)
        grant = added_sword(editor, "Event173")
        register(editor, "PlayerAddPouchAndEquip", grant)
        raw = patcher.patch_final_recovery(editor.write("Ganon recovery fixture")[0])
        for owned in (False, True):
            values, stock, _ = run_simple(raw, "PlayerAddPouchAndEquip", values={"IsGet." + ACTOR: owned})
            self.assertEqual(stock, int(owned))

    def test_interrupted_first_draw_recovers_ap_reward_via_native_later_draw(self):
        """Rauru's earlier native save cannot permanently skip the AP reward."""
        record = patcher.reward_record({LOCATION: reward("Bow")})
        pouch, presenter, entries = build_trade_rewards(
            pouch_fixture(), presenter_fixture(), {}, native_info=INFO,
            records=[record], prefix=patcher.PREFIX, event_stem=patcher.event_name, reconcile=False)
        run = TradeRun(pouch, presenter)
        door = FlowEditor(patcher.patch_draw(draw_fixture()), "interrupted draw").chart
        first = next(point.main_event.v for point in door.entry_points if point.name == "DoorOfTime_Draw")
        self.assertEqual(first.name, "RauruReward")
        # Native first-draw flags and Rauru's grant have persisted, but execution
        # stops before the new callback. Native reload now follows the later route.
        run.inventory["Item_Token_Gold"] = 1
        later = next(point.main_event.v for point in door.entry_points if point.name == "LaterDraw")
        self.assertEqual(later.data.entry_point_name, entries[LOCATION_ID])
        self.assertEqual(later.data.nxt.v.data.params.data["EventName"], "Market_Child_Field_ChildToAdult")
        run.run(later.data.entry_point_name)
        self.assertTrue(run.values[FLAG_NAME])
        self.assertEqual(run.inventory["Weapon_Range_Bow"], 1)
        self.assertEqual(run.inventory["Item_Token_Gold"], 1)
        self.assertEqual(run.inventory[ACTOR], 0)
        self.assertEqual(len(run.saves), 1)
        # A second quit after callback commit but before the age transition also
        # takes the later route; its completed flag suppresses every second grant.
        inventory = run.inventory.copy()
        run.run(later.data.entry_point_name)
        self.assertEqual(run.inventory, inventory)
        self.assertEqual(len(run.saves), 1)


if __name__ == "__main__":
    unittest.main()
