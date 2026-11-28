"""Display-only AP offsets retain the game's native item command and effects."""
import copy
from pathlib import Path
import sys
import struct
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from evfl.common import Argument
from evfl.entry_point import EntryPoint
from evfl.event import ActionEvent, SubFlowEvent
from evfl.util import make_index, make_rindex
from oot_rando.patching.progressive import FlowEditor, link
from ootrr_triforce.catalog import ITEM_DATA, ITEM_IDS
from ootrr_triforce.held_framing import (compensate_position, display_offset,
                                        patch_receipt_framing, prepare_held_framing)
from ootrr_triforce.native_presentations import PRESENTER_ENTRY, PRESENTER_NAME, PRESENTER_PATH
from ootrr_triforce.presentation_models import SHOW_ACTOR_ARGUMENT, model_actor
from ootrr_triforce.receipt_events import FLOW_PATH, REST, build_presented_receipts
from test_key_presentations import real_model_presenter
from test_presented_receipts import TOKEN, native_ground_camera
from test_receipt_events import native_flow


def item_presenter(position=(0., 0., 0.), duplicate=False):
    editor = FlowEditor(real_model_presenter(), "Native item placement fixture")
    model = next(node for node in editor.chart.events if node.name == "NativeModel")
    player = next(actor for actor in editor.chart.actors if str(actor.identifier) == "Player_Event")
    model.data.actor = make_rindex(player)
    model.data.actor_action = make_rindex(editor._holder(player.actions, "EventCreateShowItemFromActorFileName"))
    position = list(struct.unpack("<3f", struct.pack("<3f", *position)))
    native = editor.action("NativeShowPosition", "Player_Event", "EventIgnitionShowItem",
                           {"IsWaitEnd": True, "ItemPos": list(position), "IsScale": False,
                            "CreateTime": 0.0, "IsInvalidateShadow": True, "IsAsPlay": True,
                            "ASCommand": "Rotate_GetDemo"})
    if duplicate:
        other = editor.action("UnexpectedSecondShow", "Player_Event", "EventIgnitionShowItem",
                              dict(native.data.params.data))
        link(native, other)
    point = EntryPoint("Item_Position")
    point.main_event = make_index(native)
    editor.chart.entry_points.append(point)
    call = editor.subflow("NativePositionCall", "", "Item_Position", {"ActorName": Argument("ActorName")})
    link(call, model.data.nxt.v)
    link(model, call)
    return editor.write("Native item placement fixture")[0]


def fixture(names=None, **kwargs):
    return build_presented_receipts(native_flow(), item_presenter(**kwargs), TOKEN, names,
                                    ground_raw=native_ground_camera())[:2]


def offsets():
    actors = {actor for row in ITEM_DATA.values() for actor in row.get("tiers", [row["actor"]])}
    return {actor: ([0., 0., 0.] if actor.startswith("Item_Melody_") or actor == "Weapon_Sword_Master"
                    else [0., .2, 0.]) for actor in actors}


def positions(raw):
    editor = FlowEditor(raw, "Observed display commands")
    return {node.name: dict(node.data.params.data) for node in editor.chart.events
            if isinstance(node.data, ActionEvent) and node.data.actor_action.v.v == "EventIgnitionShowItem"}


class HeldFramingTests(unittest.TestCase):
    def test_every_catalogue_presenter_keeps_native_commands_and_only_missing_offsets_change(self):
        pouch, presenter = fixture()
        updated, changes = patch_receipt_framing(pouch, presenter, offsets())
        self.assertEqual(len(changes), 11)  # dungeon rewards, shared ocarinas and Bow family.
        before, after = positions(presenter), positions(updated)
        self.assertEqual(before.keys(), after.keys())
        changed = {row["event"] for row in changes}
        for name, original in before.items():
            self.assertEqual(after[name], dict(original, ItemPos=[0., .20000000298023224, 0.])
                             if name in changed else original)
        self.assertEqual(patch_receipt_framing(pouch, updated, offsets()), (updated, []))
        # Actor identities, grants, calls, next pointers, camera and sounds are
        # byte-for-byte the same event objects apart from this one vector.
        old, new = FlowEditor(presenter, "Before").chart, FlowEditor(updated, "After").chart
        self.assertEqual([p.name for p in old.entry_points], [p.name for p in new.entry_points])
        self.assertEqual([n.name for n in old.events], [n.name for n in new.events])
        for first, second in zip(old.events, new.events):
            self.assertEqual(type(first.data), type(second.data))
            a, b = getattr(first.data, "params", None), getattr(second.data, "params", None)
            expected = dict(a.data) if a is not None else None
            if first.name in changed:
                expected["ItemPos"] = second.data.params.data["ItemPos"]
            self.assertEqual(b.data if b is not None else None, expected)
            if hasattr(first.data, "nxt"):
                self.assertEqual(first.data.nxt.v.name if first.data.nxt.v else None,
                                 second.data.nxt.v.name if second.data.nxt.v else None)

    def test_existing_native_key_pouch_offset_is_never_added_twice(self):
        pouch, presenter = fixture(["Small Key (Forest Temple)", "Mirror Shield"])
        self.assertEqual(patch_receipt_framing(pouch, presenter, {}), (presenter, []))
        with patch("ootrr_triforce.held_framing.held_model_offsets") as read:
            self.assertIsNone(display_offset(ITEM_DATA["Small Key (Forest Temple)"], lambda _: None))
            read.assert_not_called()

    def test_late_adult_trade_and_pedestal_rewards_use_their_own_generated_presenters(self):
        from ootrr_triforce import ap_master_sword
        from ootrr_triforce.ap_trade import build_trade_rewards
        from ootrr_triforce.trade_catalog import TRADE_CHECKS
        from test_ap_trade import pouch_fixture, reward
        name = next(iter(TRADE_CHECKS))
        configurations = [({name: reward("Forest Medallion")}, {})]
        roster = {ap_master_sword.LOCATION: reward("Forest Medallion")}
        configurations.append((roster, dict(records=[ap_master_sword.reward_record(roster)],
                                              prefix=ap_master_sword.PREFIX,
                                              event_stem=ap_master_sword.event_name, reconcile=False)))
        for roster, kwargs in configurations:
            with self.subTest(roster=roster):
                pouch, presenter, _ = build_trade_rewards(pouch_fixture(), item_presenter(), roster,
                                                          ground_raw=native_ground_camera(), **kwargs)
                updated, changes = patch_receipt_framing(pouch, presenter, offsets())
                self.assertEqual(len(changes), 1)
                self.assertEqual(changes[0]["actors"], ["Item_Medal_Forest"])
                self.assertEqual(patch_receipt_framing(pouch, updated, offsets()), (updated, []))

    def test_shared_progressive_entry_requires_every_tier_to_have_the_same_offset(self):
        pouch, presenter = fixture(["Ocarina"])
        values = offsets()
        values["Item_Ocarina_Time"] = [0., .3, 0.]
        with self.assertRaisesRegex(ValueError, "different native offsets"):
            patch_receipt_framing(pouch, presenter, values)
        with patch("ootrr_triforce.held_framing.held_model_offsets", return_value=values):
            with self.assertRaisesRegex(ValueError, "different native offsets"):
                display_offset(ITEM_DATA["Ocarina"], lambda _: None)

    def test_crossed_alias_and_receipt_id_are_refused(self):
        for field in ("model", "item_id", "entry"):
            pouch, presenter = fixture(["Forest Medallion"])
            editor = FlowEditor(pouch, "Crossed AP model")
            node = next(node for node in editor.chart.events if isinstance(node.data, SubFlowEvent)
                        and node.data.params is not None and SHOW_ACTOR_ARGUMENT in node.data.params.data)
            if field == "model":
                node.data.params.data[SHOW_ACTOR_ARGUMENT] = model_actor("Item_Medal_Fire")
            elif field == "item_id":
                # A wrong entry is a public identity mismatch without renaming
                # nodes referenced by the fixture's received-item entry.
                node.data.params.data["ActorName"] = "Item_Medal_Fire"
                node.data.params.data[SHOW_ACTOR_ARGUMENT] = model_actor("Item_Medal_Fire")
            else:
                node.data.entry_point_name = "GetInEvent"
            editor.expected[node.name] = dict(node.data.params.data)
            bad = editor.write("Crossed AP model")[0]
            with self.subTest(field=field), self.assertRaises(ValueError):
                patch_receipt_framing(bad, presenter, offsets())

    def test_unknown_or_duplicate_native_position_is_not_silently_replaced(self):
        for kwargs in ({"position": [0., .8, 0.]}, {"duplicate": True}):
            pouch, presenter = fixture(["Forest Medallion"], **kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                patch_receipt_framing(pouch, presenter, offsets())

    def test_non_vertical_or_non_finite_offsets_are_refused(self):
        pouch, presenter = fixture(["Forest Medallion"])
        actor = ITEM_DATA["Forest Medallion"]["actor"]
        for value in ([1., .2, 0.], [0., .2, 1.], [0., float("nan"), 0.], [0., True, 0.]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                patch_receipt_framing(pouch, presenter, {actor: value})

    def test_staged_copy_is_idempotent_and_original_game_resources_are_untouched(self):
        pouch, presenter = fixture(["Forest Medallion"])
        class Codec:
            def __init__(self, _): pass
            def decode(self, raw): return raw
            def encode(self, raw, _): return raw
        with tempfile.TemporaryDirectory() as tmp:
            romfs, mod = Path(tmp) / "original", Path(tmp) / "stage"
            for root, path, raw in ((romfs, "Pack/ZsDic.pack.zs", b"dictionary"),
                                    (romfs, PRESENTER_PATH, presenter), (romfs, REST, b"allocations"),
                                    (mod, FLOW_PATH, pouch)):
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            with patch("ootrr_triforce.mod_codec.Codec", Codec), \
                    patch("ootrr_triforce.held_framing.held_model_offsets", return_value=offsets()), \
                    patch("oot_rando.game.resource_allocations.grow_resources", side_effect=lambda raw, _: (raw, None)):
                self.assertEqual(prepare_held_framing(romfs, mod), {"presenters": 1, "written": 2})
                first = (mod / PRESENTER_PATH).read_bytes()
                self.assertEqual(prepare_held_framing(romfs, mod), {"presenters": 0, "written": 0})
                self.assertEqual((mod / PRESENTER_PATH).read_bytes(), first)
            self.assertEqual((romfs / PRESENTER_PATH).read_bytes(), presenter)
            self.assertEqual((mod / FLOW_PATH).read_bytes(), pouch)
            self.assertEqual((romfs / REST).read_bytes(), b"allocations")


class NativeGiftOffsetTests(unittest.TestCase):
    def clone(self, name, position):
        from ootrr_triforce.network_catalog import SOURCES
        from ootrr_triforce.network_flows import NativeReward
        from test_network_flows import editor
        source = item_presenter(position)
        location = next(name for name, row in SOURCES.items() if row["kind"] == "flow")
        target = editor("Npc_Target")
        record = dict(name=location, local_item=name, actor="Item_AP_Test")
        native = NativeReward(target, record, "AP_Effect", lambda _: source)
        with patch("ootrr_triforce.held_framing.held_model_offsets", return_value=offsets()):
            native.clone(PRESENTER_NAME, PRESENTER_ENTRY)
        return source, target.write("Native gift with original base position")[0]

    def test_npc_model_adds_only_missing_offset_and_retains_authored_position(self):
        source, target = self.clone("Forest Medallion", [.1, .05, .15])
        source_position = next(iter(positions(source).values()))["ItemPos"]
        actual = next(iter(positions(target).values()))["ItemPos"]
        self.assertEqual(source_position, [.10000000149011612, .05000000074505806, .15000000596046448])
        for expected, observed in zip([.1, .25, .15], actual):
            self.assertAlmostEqual(expected, observed)

    def test_native_and_small_key_models_retain_their_original_position(self):
        for item in ("Mirror Shield", "Small Key (Forest Temple)"):
            with self.subTest(item=item):
                source, target = self.clone(item, [.1, .05, .15])
                self.assertEqual(next(iter(positions(source).values())), next(iter(positions(target).values())))

    def test_fresh_copy_vector_validation_preserves_authored_base(self):
        params = {"ItemPos": [1., 2., 3.]}
        for expected, observed in zip([1., 2.2, 3.], compensate_position(params, [0., .2, 0.])):
            self.assertAlmostEqual(expected, observed, places=6)
        self.assertEqual(params, {"ItemPos": [1., 2., 3.]})
        with self.assertRaises(ValueError):
            compensate_position({"ItemPos": Argument("UnknownDynamicPosition")}, [0., .2, 0.])


if __name__ == "__main__":
    unittest.main()
