"""AP counts use one exact native bundle, including replay and shop effects.

The quantity fixture is extracted from v1.1.1 PouchActorInfo. These tests resolve
the real bundle's units instead of treating a pouch actor as one ammunition.
Native capacity clamping remains the game's responsibility, not this model's.
"""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from oot_rando.patching.progressive import FlowEditor
from oot_rando.patching.event_patch import _snapshot
from ootrr_triforce import restoration
from ootrr_triforce.catalog import CHESTS, EXPECTED, FILLER, GEAR, ITEM_DATA, ITEM_IDS, SHOP_CHECKS
from ootrr_triforce.native_presentations import AMMO_BAGS, PRESENTER_NAME
from ootrr_triforce.receipt_events import build_presented_receipts, build_receipt_flow, event_name
from ootrr_triforce.shop_events import ENTRY, patch_shop_flow
from test_presented_receipts import SceneRun, native_ground_camera, native_presenter
from test_receipt_events import CURSOR, TOKEN, GraphRun, native_flow
from test_restoration import SaveRun, pouch, reward
from test_shop_events import Purchase, native_shop

# Independent regression expectations; the previous metadata gives 5/5/10/5/3/3.
CASES = {
    "Bombs (10)": ("Item_BombBundle_Small", "Shop_BombBundle_02", "Item_Bomb", 10),
    "Bombs (20)": ("Item_BombBundle_Small", "Shop_BombBundle_03", "Item_Bomb", 20),
    "Arrows (30)": ("TBox_ArrowBundle_Large", "Shop_ArrowBundle_02", "Item_Arrow_Normal", 30),
    "Deku Seeds (30)": ("TBox_DekuSeedBundle", "Shop_DekuSeedBundle_01", "Item_DekuSeed", 30),
    "Deku Nuts (5)": ("TBox_DekuNutBundle", "Shop_DekuNutBundle_01", "Item_DekuNut", 5),
    "Deku Nuts (10)": ("TBox_DekuNutBundle", "Shop_DekuNutBundle_02", "Item_DekuNut", 10),
}
NATIVE = json.loads((ROOT / "tests/fixtures/native-bundle-quantities.json").read_bytes())["actors"]
INFO = json.loads((ROOT / "tests/fixtures/pouch-presentation-info.json").read_bytes())["actors"]


def bag_for(actor):
    return {AMMO_BAGS[actor][0]} if actor in AMMO_BAGS else set()


class NativeBundleQuantityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.silent, _ = build_receipt_flow(native_flow(), TOKEN, CASES)
        raw, presenter, _ = build_presented_receipts(native_flow(), native_presenter(), TOKEN, CASES,
                                                    native_info=INFO, ground_raw=native_ground_camera())
        cls.charts = {"GetPouchContent": FlowEditor(raw, "receipts").chart,
                      PRESENTER_NAME: FlowEditor(presenter, "presenter").chart}

    def assert_quantity(self, trace, name, *, collected=True):
        _, actor, base, amount = CASES[name]
        calls = [params for action, params in trace if action == "EventTriggerAddOrRemovePouchContent"]
        if not collected:
            self.assertFalse(calls)
            return
        self.assertEqual([(call["Actor"], call["Num"]) for call in calls], [(actor, 1)])
        self.assertEqual(NATIVE[actor]["BundleActor"], "Work/Actor/" + base + ".engine__actor__ActorParam.gyml")
        self.assertEqual(sum(call["Num"] * NATIVE[call["Actor"]]["BundleActorNum"] for call in calls), amount)

    def test_exact_native_bundle_keeps_its_original_capacity_family_and_item_classification(self):
        engine = {row["name"]: row for row in json.loads(
            (ROOT / "moteur/ootrr-ap/data/items.json").read_bytes())["items"]}
        for name, (old, actor, base, amount) in CASES.items():
            with self.subTest(item=name):
                self.assertEqual((ITEM_DATA[name]["actor"], ITEM_DATA[name]["quantity"]), (actor, amount))
                self.assertEqual(ITEM_DATA[name]["mode"], "bundle")
                self.assertEqual(ITEM_DATA[name]["kind"], "Item")
                self.assertEqual(ITEM_DATA[name]["advancement"], bool(engine[name]["adv"]))
                self.assertEqual(engine[name]["actor"], old)
                self.assertTrue({old, actor} <= set(EXPECTED[name]))
                self.assertEqual(NATIVE[actor]["PouchSpecialDeal"], "None")
                self.assertEqual(NATIVE[actor]["PouchCategory"], NATIVE[old]["PouchCategory"])
                self.assertEqual(NATIVE[actor]["PouchGetType"], "Small")
                self.assertEqual(NATIVE[base]["MaxNumGameData"],
                                 {"Item_Bomb": "Bomb", "Item_Arrow_Normal": "Arrow",
                                  "Item_DekuSeed": "DekuSeed", "Item_DekuNut": "DekuNut"}[base])
                if base != "Item_DekuNut":
                    self.assertEqual(AMMO_BAGS[actor], AMMO_BAGS[old])

    def test_incoming_silent_and_presented_receipts_grant_exactly_one_bundle_before_one_ack(self):
        for name, (_, actor, _, _) in CASES.items():
            with self.subTest(item=name):
                trace = GraphRun(FlowEditor(self.silent, "silent").chart, bag_for(actor)).run(event_name(ITEM_IDS[name]))
                self.assert_quantity(trace, name)
                scene = SceneRun(self.charts, owned=bag_for(actor), native_info=INFO)
                shown = scene.run("GetPouchContent", event_name(ITEM_IDS[name]))
                self.assert_quantity(shown, name)
                for actions in (trace, shown):
                    acks = [i for i, (action, params) in enumerate(actions)
                            if action == "EventTriggerAddOrSubGameDataInt" and params["GameDataName"] == CURSOR]
                    self.assertEqual(len(acks), 1)
                    grant = next(i for i, (action, _) in enumerate(actions)
                                 if action == "EventTriggerAddOrRemovePouchContent")
                    self.assertLess(grant, acks[0])
                self.assertEqual([params["ActorName"] for action, params in shown
                                  if action == "EventTriggerRequestOpenPickUpWindow"], [actor])

    def test_missing_ammo_bag_still_has_no_item_presentation_or_substitute_reward(self):
        for name, (_, actor, _, _) in CASES.items():
            if actor not in AMMO_BAGS:
                continue
            with self.subTest(item=name):
                scene = SceneRun(self.charts, native_info=INFO)
                trace = scene.run("GetPouchContent", event_name(ITEM_IDS[name]))
                self.assert_quantity(trace, name, collected=False)
                self.assertEqual(trace, [("EventTriggerAddOrSubGameDataInt",
                                          {"GameDataName": CURSOR, "Index": -1, "Value": 1}),
                                         ("EventTriggerRequestAutoSave", {})])

    def test_old_save_recovers_exact_bundle_once_without_network_cursor_or_second_send(self):
        location = next(iter(CHESTS))
        for name, (_, actor, _, _) in CASES.items():
            with self.subTest(item=name):
                raw, _ = restoration.build_restoration_flow(pouch(), {location: reward(name)})
                run = SaveRun(raw)
                run.inventory.update(bag_for(actor))
                run.restore(location)
                self.assert_quantity(run.trace, name)
                self.assertNotIn(CURSOR, run.values)
                before = len(run.trace)
                run.restore(location)
                self.assert_quantity(run.trace[before:], name, collected=False)

    def test_local_shop_exact_bundle_keeps_saved_stock_price_and_repeated_callback_deduplication(self):
        location, metadata = next(iter(SHOP_CHECKS.items()))
        for name, (_, actor, _, _) in CASES.items():
            with self.subTest(item=name):
                row = dict(metadata, name=location, actor="Item_AP_bundle_fixture", price=15,
                           local_item=name, native_actor=actor)
                raw = patch_shop_flow(native_shop(), [row], pouch_raw=native_flow())
                run = Purchase(raw, row["actor"], rewards=[row], owned=bag_for(actor))
                run.run("FirstBuy")
                self.assert_quantity(run.trace, name)
                self.assertEqual(run.money, 85)
                self.assertTrue(run.values[row["flag_name"]])
                self.assertTrue(all(run.values[counter] == 1 for counter in row["counters"]))
                self.assertNotIn(CURSOR, run.values)
                before = len(run.trace)
                run.run(ENTRY)
                self.assert_quantity(run.trace[before:], name, collected=False)

    def test_legacy_gear_pool_does_not_use_ammunition_and_its_c_route_stays_unchanged(self):
        self.assertFalse(set(CASES).intersection(GEAR))
        self.assertNotIn(FILLER, CASES)
        source = (ROOT / "native/ootrr_ap_items.inc").read_text(encoding="utf-8")
        legacy, events = source.split("static const char *ap_eventname16", 1)
        for name in CASES:
            self.assertNotIn("case " + str(ITEM_IDS[name]) + ":", legacy)
            self.assertIn('return "' + event_name(ITEM_IDS[name]) + '";', events)

    @unittest.skipUnless(os.environ.get("OOTRR_ROMFS"), "requires read-only native v1.1.1 resources")
    def test_real_native_receipt_flow_accepts_exact_bundles_without_changing_original_commands(self):
        from ootrr_triforce import app_runtime
        from ootrr_triforce.mod_codec import Codec
        from oot_rando.formats.byml_codec import load
        game = Path(os.environ["OOTRR_ROMFS"])
        staged = Path(os.environ.get("OOTRR_STARTER_MOD", game))
        resources = Path(os.environ.get("OOTRR_CODEC_RESOURCES", ROOT / "distribution"))
        with patch.object(app_runtime, "_resource_override", resources):
            codec = Codec((game / "Pack/ZsDic.pack.zs").read_bytes())

            def read(relative):
                candidate = staged / relative
                return codec.decode((candidate if candidate.is_file() else game / relative).read_bytes())

            info = {row["__RowId"]: row for row in load(read(
                "RSDB/PouchActorInfo.Product.111.rstbl.byml.zs"))["root"]}
            for actor, expected in NATIVE.items():
                self.assertEqual({key: info[actor][key] for key in expected}, expected)
            original = read("Event/EventFlow/GetPouchContent.bfevfl.zs")
            actual, _, entries = build_presented_receipts(original,
                read("Event/EventFlow/Dm_SY_GetInEvent.bfevfl.zs"), TOKEN, CASES, native_info=info,
                ground_raw=read("Event/EventFlow/Dm_SY_Get.bfevfl.zs"))
            before = _snapshot(FlowEditor(original, "native before").flow)
            prepared = FlowEditor(actual, "native receipts")
            after = _snapshot(prepared.flow)
            self.assertTrue(all(after[name] == params for name, params in before.items()))
            self.assertEqual(entries, {ITEM_IDS[name]: event_name(ITEM_IDS[name]) for name in CASES})
            events = {event.name: event for event in prepared.chart.events}
            for name, (_, actor, _, _) in CASES.items():
                stem = event_name(ITEM_IDS[name])
                call = events[stem + ("_Ammo_Get" if actor in AMMO_BAGS else "_Get")]
                self.assertEqual(call.data.params.data["ActorName"], actor)
                self.assertEqual(call.data.entry_point_name, stem + "_Pouch")


if __name__ == "__main__":
    unittest.main()
