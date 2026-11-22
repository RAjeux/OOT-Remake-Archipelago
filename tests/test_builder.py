"""A newer portable tool must never silently reinterpret a frozen AP seed."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.builder import schema_matches, validate_builder


class BuilderTests(unittest.TestCase):
    def schema(self):
        return json.loads((ROOT / "tests/fixtures/ootrr-settings-schema.json").read_bytes())

    def test_official_schema_is_independent_of_menu_order_and_translation(self):
        data = self.schema()
        self.assertTrue(schema_matches(data))
        data["settings"].reverse()
        for record in data["settings"]:
            record["label"] = "Libellé traduit"
            record["description"] = "Translated tooltip"
        self.assertTrue(schema_matches(data))

    def test_wire_changes_and_unrecognized_schema_are_rejected(self):
        for change in (
            lambda d: d["settings"].pop(),
            lambda d: d["settings"].append(copy.deepcopy(d["settings"][0])),
            lambda d: d["settings"][0].update(num=999),
            lambda d: d["settings"][0]["choices"].reverse(),
            lambda d: d.update(schema_version=True),
            lambda d: d.update(string_prefix="OOTRR2-"),
        ):
            data = self.schema()
            change(data)
            self.assertFalse(schema_matches(data))
        for data in (None, {}, [], {"schema_version": 1, "settings": [None] * 118}):
            self.assertFalse(schema_matches(data))

    def test_probe_is_read_only_and_rejects_newer_builder(self):
        completed = subprocess.CompletedProcess([], 0, json.dumps(self.schema()), "")
        with patch("ootrr_triforce.builder.subprocess.run", return_value=completed) as run:
            validate_builder("portable/ootrr.exe")
        self.assertEqual(run.call_args.args[0], ["portable/ootrr.exe", "settings-dump", "--compact"])
        self.assertTrue(run.call_args.kwargs["check"])
        data = self.schema()
        data["settings"].append({"id": "new_setting"})
        with patch("ootrr_triforce.builder.subprocess.run", return_value=subprocess.CompletedProcess([], 0, json.dumps(data), "")):
            with self.assertRaisesRegex(ValueError, "portable 0.8.1"):
                validate_builder("updated/ootrr.exe")

    def test_failed_or_malformed_probes_fail_before_build(self):
        for error in (OSError("unavailable"), subprocess.TimeoutExpired("probe", 20),
                      subprocess.CalledProcessError(1, "probe")):
            with patch("ootrr_triforce.builder.subprocess.run", side_effect=error):
                with self.assertRaisesRegex(ValueError, "portable 0.8.1"):
                    validate_builder("bad-builder")
        with patch("ootrr_triforce.builder.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "not JSON", "")):
            with self.assertRaises(ValueError):
                validate_builder("bad-builder")


if __name__ == "__main__":
    unittest.main()
