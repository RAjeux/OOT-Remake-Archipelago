"""Chat authenticates to the existing native owner and never logs in to AP."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce import connection_control as control
from test_connection_control import native_service, session, TOKEN, PASSWORD, BEARER


class ChatControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / TOKEN
        session(self.root)
        self.info = dict(server="ws://old.example:38281", slot="Link", room="bound-room", state="connected",
                         error_code="", has_password=True, auto_connect=False, language="en")

    def tearDown(self):
        self.temp.cleanup()

    def test_offline_chat_does_not_write_or_contact_any_server(self):
        before = (self.root / "native-session.json").read_bytes()
        with patch.object(control.http.client, "HTTPConnection", side_effect=AssertionError("offline network")):
            controller = control.Controller(self.root)
            self.assertEqual(controller.chat()["error_code"], "chat_disconnected")
            self.assertEqual(controller.say("!hint")["error_code"], "chat_disconnected")
        self.assertEqual((self.root / "native-session.json").read_bytes(), before)

    def test_chat_and_say_use_authenticated_native_endpoint_and_strip_extra_fields(self):
        raw = json.dumps({"result": 1, "info": self.info, "messages": [
            {"id": 1, "text": "Friend joined", "ProtectedPassword": PASSWORD}], "password": PASSWORD}).encode()
        with native_service(self.root, raw_response=raw) as (packets, _status):
            controller = control.Controller(self.root)
            snapshot = controller.chat()
            self.assertEqual(snapshot["messages"], [{"id": 1, "text": "Friend joined"}])
            self.assertGreater(snapshot["stream"], 0)
            self.assertEqual(controller.say("!hint Bow")["result"], 1)
        self.assertEqual([row[1] for row in packets], ["/v1/status", "/v1/chat", "/v1/status", "/v1/chat"])
        self.assertEqual(packets[-1][2], {"text": "!hint Bow"})
        for secret in (PASSWORD, BEARER):
            self.assertNotIn(secret, json.dumps(snapshot))

    def test_invalid_messages_and_bad_native_batches_are_rejected(self):
        controller = control.Controller(self.root)
        for message in ("", "  ", "line\nline", "a" * 513, "é" * 257, "\ud800", 1):
            self.assertEqual(controller.say(message)["error_code"], "invalid_chat_message")
        for messages in ([{"id": -1, "text": "bad"}], [{"id": 1, "text": "x" * 513}],
                         [{"id": 1, "text": "\ud800"}], [{"id": 1}], [{}] * 21):
            raw = json.dumps({"result": 1, "info": self.info, "messages": messages}).encode()
            with self.subTest(messages=repr(messages)), native_service(self.root, raw_response=raw):
                self.assertEqual(controller.chat()["error_code"], "rpc_invalid_response")

    def test_changed_room_does_not_send_chat_to_another_profile(self):
        raw = json.dumps({"result": 1, "info": dict(self.info, room="another-room"), "messages": []}).encode()
        with native_service(self.root, raw_response=raw) as (packets, _status):
            result = control.Controller(self.root).say("hello")
            self.assertEqual(result["error_code"], "profile_changed")
            self.assertEqual([row[0] for row in packets], ["GET"])


if __name__ == "__main__":
    unittest.main()
