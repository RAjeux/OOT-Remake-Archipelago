"""Check AP controls against the independent native OOTRR settings export."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import audit_settings as audit


class NativeSettingsParityTests(unittest.TestCase):
    def test_public_keys_choices_and_ranges_fit_the_native_schema(self):
        self.assertEqual(audit.public_errors(audit.load_schema()), [])

    def test_every_native_key_has_a_status_and_specific_unavailable_reasons(self):
        schema = audit.load_schema()
        report = audit.report(schema)
        names = [row["id"] for row in report["settings"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), {row["id"] for row in schema["settings"]})
        self.assertEqual(sum(report["status_counts"].values()), len(names))
        self.assertEqual(report["status_counts"].get("not_exposed", 0), 0,
                         "Every omitted native key needs an explicit compatibility decision.")
        for row in report["settings"]:
            self.assertGreater(len(row["reason"]), 30, row["id"])
        blocked = {row["id"]: row for row in report["settings"]}
        self.assertEqual(blocked["starting_age"]["status"], "native_unavailable")
        self.assertEqual(blocked["shuffle_silver_rupees"]["status"], "delivery_missing")
        self.assertIn("junk", blocked["disabled_locations"]["reason"])
        self.assertIn("final AP", blocked["gossip_hints"]["reason"])
        self.assertTrue(report["menu_placeholders"])

    def test_a_new_unknown_choice_or_wider_slider_is_rejected(self):
        invalid = deepcopy(audit.SPEC_BY_ID)
        invalid["shuffle_chests"]["choices"] += ("not_a_native_mode",)
        invalid["enemy_health"]["max"] += 1
        invalid["not_a_native_key"] = deepcopy(invalid["enemy_health"])
        with patch.object(audit, "SPEC_BY_ID", invalid):
            errors = audit.public_errors(audit.load_schema())
        self.assertTrue(any("Unknown native choices for shuffle_chests" in error for error in errors))
        self.assertIn("Range outside native bounds: enemy_health", errors)
        self.assertIn("Unknown native key: not_a_native_key", errors)


if __name__ == "__main__":
    unittest.main()
