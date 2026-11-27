"""New physical checks append identities and preserve old seed provenance."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.catalog import CHESTS, LOCATION_IDS
from ootrr_triforce.network_catalog import (
    ADDITIONAL_SOURCES, ADDITIONAL_REWARDS, LEGACY_SOURCES, validate_sources)


class AdditionalSourceTests(unittest.TestCase):
    def room(self, modern):
        name = "KF Midos Top Left Chest"
        rows = {name: dict(LEGACY_SOURCES[name], generated_item="Rupees (5)")}
        data = dict(network_sources_schema=2 if modern else 1,
                    seed_file=dict(placements={name: "Rupees (5)"}, shops={}), network_sources=rows)
        if modern:
            data["additional_sources"] = sorted(ADDITIONAL_SOURCES)
            rows.update({name: dict(row, generated_item=ADDITIONAL_REWARDS[name])
                         for name, row in ADDITIONAL_SOURCES.items()})
        return data

    def test_new_sources_have_appended_ids_and_six_frozen_chests_become_normal_checks(self):
        self.assertEqual(len(ADDITIONAL_SOURCES), 17)
        self.assertGreater(min(LOCATION_IDS[name] for name in ADDITIONAL_SOURCES),
                           max(LOCATION_IDS[name] for name in LEGACY_SOURCES))
        frozen = [name for name, row in ADDITIONAL_SOURCES.items() if row["native_route"] == "frozen_chest"]
        self.assertEqual(len(frozen), 6)
        self.assertTrue(all(name in CHESTS for name in frozen))
        self.assertTrue(all(ADDITIONAL_REWARDS[name] != "Ice Trap" for name in frozen))

    def test_historical_sources_and_complete_new_selections_validate_without_seed_rewrites(self):
        for modern in (False, True):
            data = self.room(modern)
            self.assertEqual(validate_sources(data), data["network_sources"])
        self.assertEqual(len(self.room(True)["seed_file"]["placements"]), 1)

    def test_forged_extra_locations_rewards_or_builder_seed_entries_are_rejected(self):
        original = self.room(True)
        first = next(iter(ADDITIONAL_SOURCES))
        for corruption in ("missing", "actor", "reward", "legacy", "seed"):
            data = copy.deepcopy(original)
            if corruption == "missing": data["additional_sources"].remove(first)
            elif corruption == "actor": data["network_sources"][first]["variants"][0]["actor"] = "1"
            elif corruption == "reward": data["network_sources"][first]["generated_item"] = "Master Sword"
            elif corruption == "legacy": data["network_sources_schema"] = 1
            else: data["seed_file"]["placements"][first] = ADDITIONAL_REWARDS[first]
            with self.assertRaises(ValueError, msg=corruption): validate_sources(data)

    def test_a_compass_already_owned_from_native_start_flags_is_replaced_by_filler(self):
        name = "Fire Temple Boulder Maze Side Room Chest"
        data = self.room(True)
        data["access_logic"] = dict(world=dict(items=[dict(name="Compass (Fire Temple)")], start=[[0, 1]]))
        with self.assertRaises(ValueError):
            validate_sources(data)  # No ineffective extra Compass may reenter the pool.
        data["network_sources"][name]["generated_item"] = "Rupee (1)"
        self.assertEqual(validate_sources(data), data["network_sources"])
        data["access_logic"]["world"]["start"] = []
        with self.assertRaises(ValueError):
            validate_sources(data)  # A normal room still keeps that Compass.


if __name__ == "__main__":
    unittest.main()
