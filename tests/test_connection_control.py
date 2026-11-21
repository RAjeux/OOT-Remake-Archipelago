"""The companion edits only connection settings and talks to the game owner."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce import connection_control as control
from ootrr_triforce.save_bridge import exclusive


TOKEN = "a" * 64
BEARER = "b" * 64
PASSWORD = "private-room-password-\u00e9"


def session(root, **changes):
    data = dict(Token=TOKEN, Room="bound-room", Slot="Link", Player=1, Protocol=1,
                CursorHash=0x12345678, Baseline=13, UUID="keep-this-uuid",
                Server="ws://old.example:38281", ProtectedPassword="original-protected-value",
                AutoConnect=False, Language="en", Checks={"123": {"Name": "Check"}},
                FutureMetadata={"keep": [1, {"nested": True}]})
    data.update(changes)
    root.mkdir(parents=True, exist_ok=True)
    (root / "native-session.json").write_text(json.dumps(data), encoding="utf-8")
    return data


def descriptor(root, port, **changes):
    data = dict(version=1, port=port, pid=os.getpid(), token=TOKEN)
    if os.name == "nt":
        data["protected_secret"] = control.protect_password(BEARER)
    else:
        data["secret"] = BEARER
    data.update(changes)
    (root / "connection-control.json").write_text(json.dumps(data), encoding="utf-8")


@contextmanager
def native_service(root, *, response_changes=None, raw_response=None):
    packets = []
    status = dict(server="ws://old.example:38281", slot="Link", room="bound-room",
                  state="synchronizing", error_code="", has_password=True,
                  auto_connect=False, language="fr")
    if response_changes:
        status.update(response_changes)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self):
            if self.headers.get("Authorization") != "Bearer " + BEARER:
                self.send_response(401)
                self.end_headers()
                return
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            packet = json.loads(body) if body else None
            packets.append((self.command, self.path, packet, dict(self.headers)))
            if self.path == "/v1/connect":
                status.update(server=packet["server"], auto_connect=packet["auto_connect"], state="connecting")
                if packet["password_mode"] == 1:
                    status["has_password"] = bool(packet["password"])
                elif packet["password_mode"] == 2:
                    status["has_password"] = False
            elif self.path == "/v1/disconnect":
                status["state"] = "disconnected"
            payload = raw_response if raw_response is not None else json.dumps(dict(result=1, info=status)).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

        do_GET = respond
        do_POST = respond

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    worker.start()
    descriptor(root, server.server_port)
    try:
        with exclusive(root / "client.lock"):
            yield packets, status
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=1)


class ConnectionControlTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ootrr-companion-unit-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve() / TOKEN
        self.before = session(self.root)

    def assert_safe(self, value):
        text = json.dumps(value)
        for secret in (PASSWORD, BEARER, self.before["ProtectedPassword"]):
            self.assertNotIn(secret, text)
        # The selected profile path conventionally contains the manifest identity.
        self.assertNotIn(TOKEN, json.dumps({key: item for key, item in value.items() if key != "profile"}))
        self.assertNotIn("ProtectedPassword", text)
        self.assertNotIn("protected_secret", text)

    def test_offline_save_preserves_every_other_field_and_waits_for_game(self):
        controller = control.Controller(self.root)
        with patch.object(control, "protect_password", return_value="encrypted-replacement") as protect:
            with patch.object(control.http.client, "HTTPConnection", side_effect=AssertionError("offline network")):
                result = controller.apply(" new.example:38282 ", PASSWORD, 1, True)
        protect.assert_called_once_with(PASSWORD)
        self.assertEqual(result["result"], 1)
        self.assertEqual(result["state"], "waiting_for_game")
        self.assertFalse(result["running"])
        self.assertFalse(result["live"])
        self.assertTrue(result["has_password"])
        saved = json.loads((self.root / "native-session.json").read_bytes())
        expected = dict(self.before, Server="ws://new.example:38282", ProtectedPassword="encrypted-replacement", AutoConnect=True)
        self.assertEqual(saved, expected)
        self.assert_safe(result)
        for path in self.root.iterdir():
            self.assertNotIn(PASSWORD.encode(), path.read_bytes())

    def test_keep_clear_and_save_do_not_change_identity_or_cursor(self):
        controller = control.Controller(self.root / "native-session.json")
        with patch.object(control, "protect_password", side_effect=AssertionError("keep must not decrypt")):
            self.assertEqual(controller.save("wss://new.example:9", "ignored", 0, False)["result"], 1)
            saved = json.loads((self.root / "native-session.json").read_bytes())
            self.assertEqual(saved["ProtectedPassword"], self.before["ProtectedPassword"])
            cleared = controller.apply("new.example", "ignored", 2, True)
        self.assertFalse(cleared["has_password"])
        saved = json.loads((self.root / "native-session.json").read_bytes())
        self.assertEqual(saved["ProtectedPassword"], "")
        for key in ("Room", "Slot", "Player", "Baseline", "UUID", "Token", "CursorHash", "Checks", "FutureMetadata"):
            self.assertEqual(saved[key], self.before[key])

    def test_protection_failure_does_not_write_or_leak_exception(self):
        before = (self.root / "native-session.json").read_bytes()
        with patch.object(control, "protect_password", side_effect=OSError(PASSWORD)):
            result = control.Controller(self.root).apply("new.example", PASSWORD, 1, True)
        self.assertEqual(result["error_code"], "credential_error")
        self.assertEqual((self.root / "native-session.json").read_bytes(), before)
        self.assert_safe(result)

    def test_real_exclusive_lock_blocks_old_native_owner_edits(self):
        before = (self.root / "native-session.json").read_bytes()
        with exclusive(self.root / "client.lock"):
            controller = control.Controller(self.root)
            for result in (controller.info(), controller.apply("new.example"), controller.disconnect()):
                self.assertEqual(result["error_code"], "native_update_required")
                self.assertTrue(result["running"])
                self.assertFalse(result["live"])
                self.assert_safe(result)
        self.assertEqual((self.root / "native-session.json").read_bytes(), before)

    def test_offline_read_and_entire_write_hold_client_lock(self):
        original_read, original_atomic = control._read_json, control.atomic
        def assert_locked():
            with self.assertRaises(BlockingIOError):
                with exclusive(self.root / "client.lock"):
                    pass
        def read(*args):
            if Path(args[0]).name == "native-session.json":
                assert_locked()
            return original_read(*args)
        def write(*args):
            assert_locked()
            return original_atomic(*args)
        with patch.object(control, "_read_json", side_effect=read), patch.object(control, "atomic", side_effect=write):
            controller = control.Controller(self.root)
            self.assertEqual(controller.info()["room"], "bound-room")
            self.assertEqual(controller.apply("new.example")["result"], 1)

    def test_live_commands_use_authenticated_loopback_and_ignore_proxies(self):
        before = (self.root / "native-session.json").read_bytes()
        with native_service(self.root) as (packets, status):
            with patch.dict(os.environ, {"HTTP_PROXY": "http://192.0.2.1:1", "HTTPS_PROXY": "http://192.0.2.1:1", "ALL_PROXY": "http://192.0.2.1:1", "NO_PROXY": ""}):
                controller = control.Controller(self.root)
                info = controller.info()
                self.assertEqual(info["state"], "synchronizing")
                self.assertEqual(info["language"], "fr")
                self.assertTrue(info["running"])
                self.assertTrue(info["live"])
                connected = controller.apply("new.example:38282", PASSWORD, 1, True)
                self.assertEqual(connected["state"], "connecting")
                self.assertEqual(controller.disconnect()["state"], "disconnected")
                self.assertEqual(controller.save("new.example")["error_code"], "unsupported_live_save")
        self.assertEqual((self.root / "native-session.json").read_bytes(), before, "Only the native owner persists live settings.")
        posts = [packet for packet in packets if packet[0] == "POST"]
        self.assertEqual([packet[1] for packet in posts], ["/v1/connect", "/v1/disconnect"])
        self.assertEqual(posts[0][2], dict(server="ws://new.example:38282", password=PASSWORD, password_mode=1, auto_connect=True))
        self.assertTrue(all("Origin" not in packet[3] for packet in packets))
        self.assert_safe(info)
        self.assert_safe(connected)

    def test_wrong_profile_token_never_sends_credentials(self):
        with native_service(self.root) as (packets, status):
            desc = json.loads((self.root / "connection-control.json").read_bytes())
            for token in ("c" * 64, "\ud800"):
                desc["token"] = token
                (self.root / "connection-control.json").write_text(json.dumps(desc), encoding="utf-8")
                result = control.Controller(self.root).apply("new.example", PASSWORD, 1, True)
                self.assertEqual(result["error_code"], "rpc_unauthorized")
                self.assert_safe(result)
            self.assertEqual(packets, [])

    def test_stale_bearer_and_wrong_room_do_not_send_password(self):
        with native_service(self.root) as (packets, status):
            original = json.loads((self.root / "connection-control.json").read_bytes())
            bad = dict(original)
            if os.name == "nt":
                bad["protected_secret"] = control.protect_password("c" * 64)
            else:
                bad["secret"] = "c" * 64
            (self.root / "connection-control.json").write_text(json.dumps(bad), encoding="utf-8")
            result = control.Controller(self.root).apply("new.example", PASSWORD, 1, True)
            self.assertEqual(result["error_code"], "rpc_unauthorized")
            self.assertEqual(packets, [])
            (self.root / "connection-control.json").write_text(json.dumps(original), encoding="utf-8")
            status["room"] = "another-room"
            result = control.Controller(self.root).apply("new.example", PASSWORD, 1, True)
            self.assertEqual(result["error_code"], "profile_changed")
            self.assertEqual([packet[0] for packet in packets], ["GET"])

    def test_stale_endpoint_is_offline_when_unlocked_and_readonly_when_busy(self):
        with socket.socket() as unused:
            unused.bind(("127.0.0.1", 0))
            port = unused.getsockname()[1]
        descriptor(self.root, port)
        controller = control.Controller(self.root)
        self.assertEqual(controller.apply("new.example")["state"], "waiting_for_game")
        before = (self.root / "native-session.json").read_bytes()
        with exclusive(self.root / "client.lock"):
            result = controller.apply("different.example", PASSWORD, 1, True)
        self.assertEqual(result["error_code"], "rpc_unavailable")
        self.assertEqual((self.root / "native-session.json").read_bytes(), before)
        self.assert_safe(result)

    def test_rpc_response_is_bounded_and_unknown_fields_never_escape(self):
        with native_service(self.root, raw_response=b"x" * (control.CONTROL_LIMIT + 1)):
            self.assertEqual(control.Controller(self.root).info()["error_code"], "rpc_invalid_response")
        with native_service(self.root, response_changes={"password": PASSWORD, "ProtectedPassword": "cipher", "token": TOKEN}):
            info = control.Controller(self.root).info()
            self.assertTrue(info["live"])
            self.assert_safe(info)
        with native_service(self.root, response_changes={"error_code": PASSWORD}):
            info = control.Controller(self.root).info()
            self.assertEqual(info["error_code"], "rpc_invalid_response")
            self.assert_safe(info)

    def test_invalid_addresses_and_passwords_do_not_write_or_connect(self):
        controller = control.Controller(self.root)
        before = (self.root / "native-session.json").read_bytes()
        invalid = ["", "http://example.com", "ws://", "ws://a:0", "ws://a:65536", "ws://a:abc",
                   "ws://a:", "::1:38281", "ws://a/private", "ws://a/?password=" + PASSWORD,
                   "ws://a/?", "ws://a/#secret", "ws://user:" + PASSWORD + "@a", "server name:3",
                   "ws://a\n", "a" * 2049, "ws://a/%xx", "ws://a/\ud800"]
        with patch.object(control.http.client, "HTTPConnection", side_effect=AssertionError("invalid network")):
            for address in invalid:
                with self.subTest(address=repr(address)):
                    result = controller.apply(address, PASSWORD, 1, True)
                    self.assertEqual(result["error_code"], "invalid_server")
                    self.assert_safe(result)
            for password, mode, automatic in [("x\0y", 1, True), ("x" * 4097, 1, True), ("\ud800", 1, True), ("", 3, True), ("", True, True), ("", 0, 1)]:
                self.assertEqual(controller.apply("valid.example", password, mode, automatic)["error_code"], "invalid_password")
        self.assertEqual((self.root / "native-session.json").read_bytes(), before)

    def test_address_normalization_matches_native_common_cases(self):
        examples = {"127.0.0.1:38281": "ws://127.0.0.1:38281", "archipelago.gg:12345": "ws://archipelago.gg:12345",
                    " [::1]:38281 ": "ws://[::1]:38281", "ws://localhost:1/": "ws://localhost:1/",
                    "wss://archipelago.gg:12345": "wss://archipelago.gg:12345", "example.com": "ws://example.com"}
        for value, expected in examples.items():
            self.assertEqual(control.normalize_server(value), expected)

    def test_profile_identity_change_is_rejected(self):
        controller = control.Controller(self.root)
        self.assertEqual(controller.info()["room"], "bound-room")
        session(self.root, Room="other-room")
        before = (self.root / "native-session.json").read_bytes()
        result = controller.apply("new.example")
        self.assertEqual(result["error_code"], "profile_changed")
        self.assertEqual((self.root / "native-session.json").read_bytes(), before)

    def test_discovery_markers_explicit_path_and_host_language(self):
        # Hosted Windows runners may expose TEMP through an 8.3 alias.
        base = Path(self.temporary.name).resolve()
        second = base / ("c" * 64)
        session(second, Token="c" * 64, Slot="Zelda")
        os.utime(second / "native-session.json", (2_000_000_000, 2_000_000_000))
        (self.root / "language.json").write_text('{"language":"fr"}', encoding="utf-8")
        profiles = control.discover_profiles(base)
        self.assertEqual({profile.slot for profile in profiles}, {"Link", "Zelda"})
        self.assertEqual(control.default_profile(base).root, second)
        (base / "derniere-salle-native.json").write_text(json.dumps(TOKEN), encoding="utf-8")
        self.assertEqual(control.default_profile(base).root, self.root)
        control.remember_profile(second, base)
        self.assertEqual(control.default_profile(base).root, second)
        self.assertEqual(control.default_profile(base, self.root / "native-session.json").language, "fr")
        with self.assertRaises(Exception):
            profiles[0].slot = "Changed"


if __name__ == "__main__":
    unittest.main()
