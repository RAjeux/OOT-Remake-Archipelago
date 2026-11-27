"""All AP delivery routes apply the trap, never its displayed weapon actor."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))

from evfl.entry_point import EntryPoint
from evfl.actor import Actor
from evfl.common import ActorIdentifier
from evfl.util import make_index
from oot_rando.patching.progressive import FlowEditor
from ootrr_triforce import restoration
from ootrr_triforce.ap_skulls import patch_skull_flow, skull_records
from ootrr_triforce.catalog import ITEM_DATA, ITEM_IDS
from ootrr_triforce.native_presentations import append_local_chests
from ootrr_triforce.shop_events import ENTRY as SHOP_ENTRY, patch_shop_flow
from test_network_flows import editor
from test_presented_receipts import native_presenter, SceneRun
from test_receipt_events import native_flow
from test_restoration import CHEST, SaveRun, pouch, reward
from test_shop_events import native_shop, records, Purchase
from test_skull_events import native_flow as skull_pouch, Pickup, roster


class IceTrapRouteTests(unittest.TestCase):
    def assert_no_inventory_disguise(self, trace):
        self.assertFalse(any(command in {"EventTriggerAddOrRemovePouchContent", "EventTriggerPushToEmptyBottle"}
                             for command, _ in trace))

    def test_native_chest_opens_and_applies_trap_without_granting_displayed_bow(self):
        source = editor("Dm_SY_TreasureboxSmall")
        chest = Actor()
        chest.identifier = ActorIdentifier("TreasureBox_EventStarter")
        source.chart.actors.append(chest)
        grant = source.subflow("OriginalGet", "GetPouchContent", "GetPouchContentByActorNameForTreasureBox",
                               {"ActorName": "TBox_Rupee_Green"})
        entry = EntryPoint("Success_")
        entry.main_event = make_index(grant)
        source.chart.entry_points.append(entry)
        entries = append_local_chests(source, native_flow(), ["Ice Trap"])
        raw = source.write("trap chest")[0]
        run = SceneRun({"Dm_SY_TreasureboxSmall": FlowEditor(raw, "trap chest").chart,
                        "Dm_SY_GetInEvent": FlowEditor(native_presenter(), "trap fixture").chart})
        run.run("Dm_SY_TreasureboxSmall", entries["Ice Trap"])
        self.assert_no_inventory_disguise(run.trace)
        self.assertEqual(sum(command == "FixtureNativeIceTrap" for command, _ in run.trace), 1)
        self.assertEqual(sum(command == "EventTriggerTreasureBoxOpened" for command, _ in run.trace), 1)

    def test_shop_trap_charges_once_and_exhausts_without_adding_bow_or_quiver(self):
        selected = records()[0]
        selected.update(local_item="Ice Trap", native_actor=ITEM_DATA["Ice Trap"]["actor"])
        raw = patch_shop_flow(native_shop(), [selected], pouch_raw=native_flow())
        run = Purchase(raw, selected["actor"], rewards=[selected])
        run.run("FirstBuy")
        self.assertEqual(run.money, 100 - selected["price"])
        self.assertTrue(run.values[selected["flag_name"]])
        self.assert_no_inventory_disguise(run.trace)
        self.assertEqual(sum(command == "FixtureNativeIceTrap" for command, _ in run.trace), 1)
        run.run(SHOP_ENTRY)
        self.assert_no_inventory_disguise(run.trace)
        self.assertEqual(sum(command == "FixtureNativeIceTrap" for command, _ in run.trace), 1)

    def test_collected_skull_trap_applies_once_and_does_not_grant_disguise(self):
        selected = skull_records(roster(["Ice Trap"]))
        raw = patch_skull_flow(skull_pouch(), selected)
        run = Pickup(raw, ignored_entries={("Dm_SY_GetInEvent", "AP_IceTrap")})
        run.run(selected[0]["actor"])
        run.run(selected[0]["actor"])
        self.assertTrue(run.values[selected[0]["flag_name"]])
        self.assert_no_inventory_disguise(run.trace)
        self.assertEqual(sum(command == "call:AP_IceTrap" for command, _ in run.trace), 1)

    def test_old_save_restores_consumed_local_trap_check_without_freezing_again(self):
        raw, _ = restoration.build_restoration_flow(pouch(), {CHEST: reward("Ice Trap")})
        run = SaveRun(raw)
        run.restore(CHEST)
        run.restore(CHEST)
        self.assertFalse(run.inventory)
        self.assert_no_inventory_disguise(run.trace)
        self.assertFalse(any("IceTrap" in action for action, _ in run.trace))
        self.assertTrue(all(run.values[flag] for flag in restoration.restoration_records({CHEST: reward("Ice Trap")})[0]["flags"]))

    def test_new_item_id_is_appended_after_every_published_item(self):
        self.assertEqual(ITEM_IDS["Ice Trap"], max(ITEM_IDS.values()))
        self.assertEqual(ITEM_DATA["Ice Trap"]["mode"], "trap")


if __name__ == "__main__":
    unittest.main()
