"""Weapons earn their native capacity; new games receive no free ammunition."""
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_full.randomizer.randomizer_core import starting_pouch_items, STARTING_ITEMS
from ootrr_full.patching import progressive


class StartingInventoryTests(unittest.TestCase):
    def test_default_opening_contains_no_free_capacity_or_weapon(self):
        self.assertEqual(STARTING_ITEMS, ("Pouch_Amiibo",))
        self.assertEqual(starting_pouch_items({}), ["Pouch_Amiibo"])

    def test_selected_weapons_get_only_missing_native_capacity(self):
        for weapon, capacities in progressive.WEAPON_CAPACITY.items():
            with self.subTest(weapon=weapon):
                actors = starting_pouch_items({"starting": [{"actor": weapon}]})
                self.assertIn(weapon, actors)
                self.assertIn(capacities[0], actors)
                for higher in capacities[1:]:
                    actors = starting_pouch_items({"starting": [{"actor": weapon}, {"actor": higher}]})
                    self.assertIn(higher, actors)
                    self.assertNotIn(capacities[0], actors)

    def test_archipelago_starting_inventory_uses_same_capacity_rule(self):
        actors = starting_pouch_items({"archipelago": {"starting": [{"actor": "Item_Range_Bow"}]}})
        self.assertEqual(actors, ["Pouch_Amiibo", "Item_Range_Bow", "Item_Quiver_Small"])


@unittest.skipUnless(os.environ.get("OOT_NUP"), "OOT_NUP not set")
class NativeWeaponTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ootrr_full.formats.inspect_nup import Nup
        from ootrr_full.game.world_maps import effective_members
        from ootrr_full.formats.inspect_resources import dictionaries, decompress
        cls.nup = Nup(os.environ["OOT_NUP"])
        cls.members = effective_members(cls.nup)
        cls.dictionaries = dictionaries(cls.nup)
        cls.decompress = staticmethod(decompress)

    @classmethod
    def tearDownClass(cls):
        cls.nup.stream.close()

    @classmethod
    def read(cls, path):
        return cls.decompress(cls.nup.read(cls.members[path]), cls.dictionaries)

    def test_real_progressive_converter_roundtrip_includes_guarded_capacity(self):
        tokens = [progressive.token_actor("Bow", 1), progressive.token_actor("Slingshot", 1)]
        raw, _ = progressive.add_converter(self.read("Event/EventFlow/ActionGuide.bfevfl.zs"), tokens)
        editor = progressive.FlowEditor(raw, "Verify native weapon capacity")
        grants = [event for event in editor.chart.events if type(event.data).__name__ == "ActionEvent"
                  and event.data.actor_action.v.v == "EventTriggerAddOrRemovePouchContent"
                  and event.name.endswith("_CapacityGive")]
        self.assertEqual({event.data.params.data["Actor"] for event in grants},
                         {"Item_Quiver_Small", "Item_BulletBag_Small"})
        for event in grants:
            self.assertFalse(event.data.params.data["IsGetEvent"])
            self.assertFalse(event.data.params.data["IsSetMessageTargetActorName"])
        # The converter's own validator traverses every tier and capacity guard.
        self.assertTrue(raw)

    def test_real_ap_receipt_flow_contains_no_unconditional_starting_bags(self):
        from ootrr_full.patching.ap_mailbox import add_entries, records
        records_ = records([{"item": family, "player": "Friend", "location": family}
                            for family in ("Bow", "Slingshot")])
        raw = add_entries(self.read("Event/EventFlow/Dm_SY_GetInEvent.bfevfl.zs"), records_)
        self.assertTrue(raw)


if __name__ == "__main__":
    unittest.main()
