"""Gold Skulltula identities preserve old AP IDs and authored actor evidence."""
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from oot_rando.patching.soul_adapter import murmur3
from ootrr_triforce.catalog import (AP_SKULL_CHECKS, CHECK_FLAGS, CHESTS, LOCATION_IDS,
                                    PINNED_SKULL_CHECKS, LEGACY_SHOP_CHECKS, SKULL_CHECKS)


class SkullCatalogueTests(unittest.TestCase):
    def test_original_chest_and_shop_ids_are_frozen(self):
        original = {name: LOCATION_IDS[name] for name in (*CHESTS, *LEGACY_SHOP_CHECKS)}
        digest = hashlib.sha256(json.dumps(original, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(len(original), 136)
        self.assertEqual(digest, "1e6cec3f013237b6224bddc9531ec49756d5bdccef14142150ed97fdf2d1f3df")
        self.assertEqual(len(set(LOCATION_IDS.values())), len(LOCATION_IDS))
        self.assertEqual(min(LOCATION_IDS[name] for name in SKULL_CHECKS), 0x6F7200 + 136)

    def test_hundred_physical_actors_reserve_ids_but_only_safe_names_join_ap(self):
        self.assertEqual(len(SKULL_CHECKS), 100)
        self.assertEqual(len(AP_SKULL_CHECKS), 77)
        self.assertEqual(len(PINNED_SKULL_CHECKS), 44)
        self.assertTrue(PINNED_SKULL_CHECKS < AP_SKULL_CHECKS)
        self.assertEqual(len({record["actor"] for record in SKULL_CHECKS.values()}), 100)
        self.assertEqual(len({record["flag"] for record in SKULL_CHECKS.values()}), 100)
        old_flags = {flag for name in (*CHESTS, *LEGACY_SHOP_CHECKS) for flag in CHECK_FLAGS[name]}
        self.assertFalse(old_flags.intersection(record["flag"] for record in SKULL_CHECKS.values()))
        for name, record in SKULL_CHECKS.items():
            with self.subTest(location=name):
                self.assertEqual(CHECK_FLAGS[name], [record["flag"]])
                self.assertEqual(record["flag_name"], "Archipelago.Skull." + record["actor"])
                self.assertEqual(record["flag"], murmur3(record["flag_name"]))
                self.assertEqual(name in AP_SKULL_CHECKS, record["grade"] not in {"lean", "tour"})

    def test_metadata_uses_physical_hash_overrides_not_the_old_name_guess(self):
        data = ROOT / "moteur/ootrr-ap/data"
        catalog = json.loads((data / "locations.json").read_text(encoding="utf-8"))
        overrides = json.loads((data / "skull_names.json").read_text(encoding="utf-8"))
        by_hash = {str(ref["hash"]): ref for section in ("locations", "unmatched_remake")
                   for row in catalog[section] if row.get("kind") == "gs" for ref in row["refs"]}
        expected = {row["name"]: str(row["refs"][0]["hash"])
                    for row in catalog["locations"] if row.get("kind") == "gs"}
        expected.update({row["name"]: row["hash"] for row in overrides["spots"]})
        self.assertEqual(set(SKULL_CHECKS), set(expected))
        for name, actor in expected.items():
            with self.subTest(location=name):
                self.assertEqual(SKULL_CHECKS[name]["actor"], actor)
                self.assertEqual(SKULL_CHECKS[name]["files"], sorted(by_hash[actor]["files"]))
                self.assertTrue(all(path.startswith("Banc/") and path.endswith(".bcett.byml.zs")
                                    for path in SKULL_CHECKS[name]["files"]))
        self.assertNotIn("ZR GS Tree", AP_SKULL_CHECKS)
        self.assertIn("Colossus GS Hill", AP_SKULL_CHECKS)


if __name__ == "__main__":
    unittest.main()
