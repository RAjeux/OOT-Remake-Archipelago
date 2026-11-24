"""Room binding and passive tracking cannot promote planned or manual rewards."""
from collections import Counter
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.tracker_service import ProfileTracker, RuntimeTracker


class FakeTracker:
    checks = [{"id": "gid", "name": "A chest"}]
    goal_reached = False
    def __init__(self, _artifact=None, _slot=None, **_options):
        self.save_path = ""
        self.refreshed = []
    def refresh(self):
        self.refreshed.append(self.save_path)
        return {"status": "Synced with the latest save"}
    def check_state(self, _gid):
        return {"completed": True, "observed": False, "reward": "Secret planned Bow", "access": "blocked"}
    def inventory(self):
        return Counter({"Kokiri Sword": 1}), {"Kokiri Sword", "Bow"}, {"Kokiri Sword", "Bow"}
    def keys(self):
        return []
    def souls(self):
        return []


class TrackerServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.profile = self.base / ("a" * 64)
        self.profile.mkdir()
        (self.profile / "native-session.json").write_text(json.dumps({"Room": "room", "Slot": "Link", "Checks": {"123": {"Name": "A chest", "Item": "Secret planned Bow"}}}))
        self.artifact = self.base / "artifact"
        self.artifact.mkdir()
        (self.artifact / "manifest.json").write_text(json.dumps({"archipelago": {"token": self.profile.name}}))

    def tearDown(self):
        self.temp.cleanup()

    def test_matching_room_uses_observed_inventory_and_never_shows_planned_reward(self):
        with patch("ootrr_full.tracker.auto_tracker.TrackerSession", FakeTracker):
            tracker = ProfileTracker(self.profile, self.artifact)
        save = self.profile / "user/save/account/slot_00/progress.sav"
        save.parent.mkdir(parents=True)
        save.write_bytes(b"untouched")
        result = tracker.refresh(save)
        self.assertEqual(result["checked"], 0)
        self.assertEqual(result["locations"][0]["access"], "blocked")
        self.assertFalse(result["locations"][0]["observed"])
        self.assertNotIn("Secret planned", json.dumps(result))
        self.assertEqual({row["name"]: row["count"] for row in result["inventory"]}, {"Bow": 0, "Kokiri Sword": 1})
        self.assertEqual(save.read_bytes(), b"untouched")

    def test_wrong_artifact_token_or_foreign_save_cannot_supply_inventory(self):
        (self.artifact / "manifest.json").write_text(json.dumps({"archipelago": {"token": "b" * 64}}))
        with patch("ootrr_full.tracker.auto_tracker.TrackerSession", side_effect=AssertionError("wrong room")):
            tracker = ProfileTracker(self.profile, self.artifact)
        self.assertEqual(tracker.refresh()["inventory"], [])
        (self.artifact / "manifest.json").write_text(json.dumps({"archipelago": {"token": self.profile.name}}))
        with patch("ootrr_full.tracker.auto_tracker.TrackerSession", FakeTracker):
            tracker = ProfileTracker(self.profile, self.artifact)
        result = tracker.refresh(self.base / "another-room/progress.sav")
        self.assertEqual(result["inventory"], [])
        self.assertEqual(tracker.tracker.refreshed, [])

    def test_external_tracker_reads_existing_runtime_and_ignores_manual_completion(self):
        class Reporter:
            server_checked = set()
            location_ids = {"gid": 123}
        class Client:
            _lock = threading.Lock()
            reporter = Reporter()
            slot_name = "Link"
        class Runtime:
            client, tracker = Client(), FakeTracker()
            def summary(self):
                return {"tracking": "Real time"}
        result = RuntimeTracker(Runtime()).refresh()
        self.assertFalse(result["locations"][0]["checked"])
        self.assertNotIn("Secret planned", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
