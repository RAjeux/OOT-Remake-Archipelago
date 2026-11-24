"""External receipt runtime sends only at a native safe point and in order."""
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce import upgrade_runtime as runtime
from ootrr_full.patching.soul_adapter import murmur3
from ootrr_full.randomizer.randomizer_core import save_marker
from ootrr_full.tracker.auto_tracker import TrackerSession


FLAG = "Archipelago.Ready." + "a" * 64
RECORDS = [{"key": key, "recv": "RandoAP.Recv." + key, "got": "RandoAP.Got." + key,
            "item": "Bow", "player": "Ami"} for key in ("first", "second")]
MANIFEST = {"seed_id": "external-seed-test", "external_readiness": {"flag": FLAG, "version": 1},
            "skips": {"ap_mailbox": {"items": RECORDS, "signal": "RandoAP.Pending"}}}


class Memory:
    def close(self):
        pass


class Live:
    memory = Memory()
    def __init__(self):
        names = (FLAG, runtime.PAUSE, runtime.LOADING, "RandoAP.Pending",
                 *(r["recv"] for r in RECORDS), *(r["got"] for r in RECORDS), save_marker(MANIFEST))
        self.flags = {murmur3(name): name in (FLAG, save_marker(MANIFEST)) for name in names}

    def snapshot(self):
        return {"bool": dict(self.flags), "sha256": "fixture"}


class Events:
    busy = False
    def playing(self):
        return self.busy


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.live, self.events = Live(), Events()
        self.now = 0.0
        self.delivery = runtime.SafeLiveDelivery(MANIFEST, self.live, event_state=self.events, clock=lambda: self.now)
        self.writes = []
        def write(data, key, value):
            self.writes.append((key, value))
            if key not in self.live.flags:
                return False
            self.live.flags[key] = value
            return True
        self.writer = patch("ootrr_full.tracker.live_memory.set_bool_in", write)
        self.writer.start()
        self.addCleanup(self.writer.stop)

    def test_safe_receipt_requests_native_event_and_shared_signal(self):
        self.assertEqual(self.delivery.step(["first", "second"]), RECORDS[0])
        self.assertEqual(self.writes, [(murmur3(RECORDS[0]["recv"]), True), (murmur3("RandoAP.Pending"), True)])

    def test_pause_load_event_unknown_and_tunnel_state_never_signal(self):
        for name, value in ((FLAG, False), (runtime.PAUSE, True), (runtime.LOADING, True), (FLAG, None)):
            with self.subTest(name=name, value=value):
                original = dict(self.live.flags)
                if value is None:
                    del self.live.flags[murmur3(name)]
                else:
                    self.live.flags[murmur3(name)] = value
                self.assertIsNone(self.delivery.step(["first"]))
                self.assertEqual(self.delivery.waiting, 1)
                self.assertFalse(self.writes)
                self.live.flags = original
        self.events.busy = True
        self.assertIsNone(self.delivery.step(["first"]))
        self.assertFalse(self.writes)

    def test_missing_mailbox_flag_is_not_reported_as_delivered(self):
        del self.live.flags[murmur3(RECORDS[0]["got"])]
        self.assertIsNone(self.delivery.step(["first"]))
        self.assertIn("flags unavailable", self.delivery.status)
        self.assertFalse(self.writes)

    def test_old_mod_without_readiness_stays_closed(self):
        manifest = dict(MANIFEST)
        manifest.pop("external_readiness")
        delivery = runtime.SafeLiveDelivery(manifest, self.live, event_state=self.events)
        self.assertIsNone(delivery.step(["first"]))
        self.assertIn("native readiness gate", delivery.status)
        self.assertFalse(self.writes)

    def test_no_received_history_reordering_after_retries(self):
        for _ in range(9):
            result = self.delivery.step(["first", "second"])
            self.assertEqual(result["key"], "first")
            self.live.flags[murmur3(RECORDS[0]["recv"])] = False
            self.live.flags[murmur3("RandoAP.Pending")] = False
            self.now += 10
        self.live.flags[murmur3(RECORDS[0]["got"])] = True
        self.assertEqual(self.delivery.step(["first", "second"])["key"], "second")

    def test_native_received_flag_prevents_duplicate_in_same_save(self):
        self.live.flags[murmur3(RECORDS[0]["got"])] = True
        self.assertIsNone(self.delivery.step(["first"]))
        self.assertFalse(self.writes)
        # Loading a prior save makes its receipt false; replay then works.
        self.live.flags[murmur3(RECORDS[0]["got"])] = False
        self.assertEqual(self.delivery.step(["first"])["key"], "first")

    def test_linked_death_prevents_a_new_receipt_until_native_acknowledgement(self):
        from ootrr_triforce.upgrade_deathlink import metadata
        import copy
        manifest = copy.deepcopy(MANIFEST)
        manifest['external_deathlink'] = metadata('a' * 64)
        fields = manifest['external_deathlink']['flags']
        for name in ('dead', 'request', 'fired'):
            self.live.flags[murmur3(fields[name])] = False
        delivery = runtime.SafeLiveDelivery(manifest, self.live, event_state=self.events)
        for name in ('dead', 'request', 'fired'):
            self.live.flags[murmur3(fields[name])] = True
            self.assertIsNone(delivery.step(['first']))
            self.assertFalse(self.writes)
            self.live.flags[murmur3(fields[name])] = False
        self.assertEqual(delivery.step(['first']), RECORDS[0])

    def session_delivery(self):
        import copy
        manifest = copy.deepcopy(MANIFEST)
        session = 'Archipelago.ExternalSessionReady.' + 'a' * 64
        spent = 'Archipelago.ExternalSpent.' + 'a' * 64 + '.999'
        manifest['external_recovery'] = {'version': 1, 'session_flag': session}
        manifest['skips']['ap_mailbox']['items'][0].update(spent=spent, consumed_by_location_id=999)
        self.live.flags.update({murmur3(session): False, murmur3(spent): False})
        delivery = runtime.SafeLiveDelivery(manifest, self.live, event_state=self.events, clock=lambda: self.now)
        return delivery, murmur3(session), murmur3(spent)

    def test_authenticated_spent_trade_state_precedes_session_and_any_receipt_request(self):
        delivery, session, spent = self.session_delivery()
        self.assertIsNone(delivery.step(['first']))
        self.assertFalse(self.writes)
        delivery.confirm_checks({999})
        self.assertEqual(delivery.step(['first'])['key'], 'first')
        self.assertEqual(self.writes, [(spent, True), (session, True),
            (murmur3(RECORDS[0]['recv']), True), (murmur3('RandoAP.Pending'), True)])

    def test_disconnection_closes_transient_session_without_discarding_pending_item(self):
        delivery, session, spent = self.session_delivery()
        delivery.confirm_checks({999})
        delivery.step(['first'])
        delivery.suspend()
        self.assertFalse(self.live.flags[session])
        self.assertTrue(self.live.flags[murmur3('RandoAP.Pending')])
        old = list(self.writes)
        self.assertIsNone(delivery.step(['first']))
        self.assertEqual(self.writes, old)

    def test_other_seed_never_receives_session_or_spent_flag_writes(self):
        delivery, session, spent = self.session_delivery()
        self.live.flags[delivery.marker] = False
        delivery.confirm_checks({999})
        self.assertIsNone(delivery.step(['first']))
        self.assertFalse(self.writes)

    def test_manual_tracker_marks_are_not_automatic_ap_checks(self):
        tracker = TrackerSession.__new__(TrackerSession)
        tracker._lock = threading.RLock()
        tracker._automatic = {"actual-game-check"}
        tracker.manual = type("Manual", (), {"completed": {"manual-mark"}})()
        self.assertEqual(tracker.completed, {"actual-game-check", "manual-mark"})
        self.assertEqual(tracker.observed_completed, {"actual-game-check"})
        observed = tracker.observed_completed
        observed.clear()
        self.assertEqual(tracker.observed_completed, {"actual-game-check"})

    def test_actual_emulator_names_include_fritchii(self):
        self.assertIn("fritchii.exe", runtime.live_memory.EMULATOR_EXES)
        self.assertIn("yuzu.exe", runtime.live_memory.EMULATOR_EXES)

    def test_chat_is_bounded_connected_only_and_cleared_on_disconnect(self):
        from ootrr_full.archipelago.client import ArchipelagoClient
        client = ArchipelagoClient({"archipelago": {"slot_name": "Link", "location_ids": {"check": 1}}},
                                   "ws://127.0.0.1:1", delivery=object())
        owner = runtime.ExternalRuntime.__new__(runtime.ExternalRuntime)
        owner.client = client
        with self.assertRaisesRegex(ValueError, "Connect to the room"):
            owner.say("hello")
        self.assertFalse(client._outbox)
        client.connected = True
        for text in ("", " ", "hello\n", "é" * 300):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    owner.say(text)
        owner.say("!hint Bow")
        self.assertEqual(list(client._outbox), [{"cmd": "Say", "text": "!hint Bow"}])
        for _ in range(31):
            owner.say("hello")
        with self.assertRaisesRegex(ValueError, "queue is full"):
            owner.say("one too many")
        client._set_status("Disconnected", connected=False)
        self.assertFalse(client._outbox)

    def test_selected_executable_cannot_attach_a_different_game(self):
        self.assertTrue(runtime.live_memory.selected_executable("/games/one/emulator", "/games/one/emulator"))
        self.assertFalse(runtime.live_memory.selected_executable("/games/other/emulator", "/games/one/emulator"))
        self.assertFalse(runtime.live_memory.selected_executable("", "/games/one/emulator"))

    def test_tracker_observes_live_checks_before_the_first_save_exists(self):
        tracker = TrackerSession.__new__(TrackerSession)
        tracker._lock = threading.RLock()
        marker, check = 1234, 5678
        tracker.live = type("ReadOnlyLive", (), {"snapshot": lambda self: {
            "bool": {marker: True, check: True}, "bool64": {}, "bool64_complete": True,
            "sha256": "live-before-first-save"}})()
        tracker.metadata = {"seed_marker": str(marker), "checks": {
            "actual": {"collection": {"type": "bool", "hash": str(check)}}}, "known_bool64": []}
        tracker.checks = [{"id": "actual"}]
        tracker.save_path = ""
        tracker._fingerprint = None
        tracker._good_summary = None
        tracker._logic_error = ""
        tracker._goal = False
        tracker._availability = lambda snapshot, metadata: {"actual": "available"}
        result = tracker.refresh()
        self.assertEqual(result["automatic"], 1)
        self.assertEqual(tracker.observed_completed, {"actual"})
        self.assertIn("Real time", result["status"])


if __name__ == "__main__":
    unittest.main()
