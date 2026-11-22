"""Exercise actual Tk widgets and asynchronous controls with isolated profiles."""
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.connection_control import Profile
from ootrr_triforce.connection_window import ConnectionWindow, ERRORS, STATES
from ootrr_triforce.i18n import tr


class FakeController:
    def __init__(self, profile):
        self.current = dict(server=profile.server, room=profile.room, slot=profile.slot,
                            player=profile.player, language=profile.language,
                            has_password=profile.has_password, auto_connect=profile.auto_connect,
                            state="waiting_for_game", live=False, running=False, error_code="")
        self.calls = []
        self.info_gate = self.action_gate = None
        self.started = threading.Event()

    def info(self):
        snapshot = dict(self.current)
        if self.info_gate:
            self.started.set()
            self.info_gate.wait(3)
        return snapshot

    def _apply(self, kind, server, password, mode, automatic):
        self.calls.append((kind, server, password, mode, automatic))
        if self.action_gate:
            self.started.set()
            self.action_gate.wait(3)
        self.current.update(server=server, auto_connect=automatic, error_code="")
        if mode:
            self.current["has_password"] = mode == 1
        return dict(self.current, result=1)

    def apply(self, *args):
        return self._apply("connect", *args)

    def save(self, *args):
        return self._apply("save", *args)

    def disconnect(self):
        self.calls.append(("disconnect",))
        self.current.update(state="disconnected")
        return dict(self.current, result=1)


class ConnectionWindowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.profiles = [
            Profile(self.base / "a", "Room A", "Link", 1, "ws://localhost:1234", "en", True, True),
            Profile(self.base / "b", "Room B", "Zelda", 2, "ws://localhost:5678", "fr", False, False),
        ]
        self.controls = {profile.root: FakeController(profile) for profile in self.profiles}
        for profile in self.profiles:
            profile.root.mkdir()
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except tk.TclError as error:
            self.temporary.cleanup()
            self.skipTest(f"Tk display unavailable: {error}")
        self.window = None

    def tearDown(self):
        for control in self.controls.values():
            for gate in (control.info_gate, control.action_gate):
                if gate:
                    gate.set()
        if self.window and not self.window.closed:
            self.window.close()
        elif not self.window:
            self.root.destroy()
        self.temporary.cleanup()

    def open(self, profiles=None):
        selected = self.profiles if profiles is None else profiles
        self.window = ConnectionWindow(
            self.root, base=self.base, poll_ms=100,
            controller_factory=lambda root: self.controls[root],
            discover=lambda **kwargs: selected,
            choose_default=lambda **kwargs: selected[0] if selected else None,
        )
        self.pump(lambda: not self.window.refreshing)
        return self.window

    def pump(self, condition, timeout=2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.root.update()
            if condition():
                return
            time.sleep(.005)
        self.fail("Timed out waiting for the Tk worker result")

    def idle(self):
        self.pump(lambda: not self.window.pending_poll and not self.window.busy)

    def test_no_profiles_explains_setup_and_disables_actions(self):
        window = self.open([])
        self.assertEqual(window.status_label.cget("text"), "No configured profile")
        self.assertIn("Set up a room", window.detail_label.cget("text"))
        self.assertEqual(str(window.primary_button.cget("state")), "disabled")

    def test_profile_identity_is_readonly_and_language_follows_selection(self):
        window = self.open()
        self.idle()
        self.assertEqual(window.profile_choice.cget("values"), ("Room A · Link", "Room B · Zelda"))
        self.assertEqual(window.room.get(), "Room A")
        self.assertEqual(window.slot.get(), "Link")
        self.assertEqual(window.primary_button.cget("text"), "Save")
        self.assertFalse(window.disconnect_button.winfo_manager())
        window.profile_choice.current(1)
        window.profile_choice.event_generate("<<ComboboxSelected>>")
        self.pump(lambda: window.selected == self.profiles[1] and not window.pending_poll)
        self.assertEqual(window.master.title(), "Connexion Archipelago")
        self.assertEqual(window.primary_button.cget("text"), "Enregistrer")
        self.assertEqual(window.room.get(), "Room B")
        self.assertEqual(window.slot.get(), "Zelda")
        identities = [widget for widget in window.server_entry.master.winfo_children()
                      if isinstance(widget, tk.ttk.Entry) and not isinstance(widget, tk.ttk.Combobox)
                      and widget != window.server_entry]
        self.assertEqual(len(identities), 2)
        self.assertTrue(all(str(widget.cget("state")) == "readonly" for widget in identities))

    def test_keep_replace_and_clear_are_explicit_and_plaintext_is_erased(self):
        window = self.open()
        self.idle()
        control = self.controls[self.profiles[0].root]
        self.assertEqual(window.mode.get(), 0)
        self.assertEqual(str(window.password_entry.cget("state")), "disabled")
        window.server.set("ws://localhost:9999")
        window.primary_button.invoke()
        self.pump(lambda: bool(control.calls) and not window.busy)
        self.assertEqual(control.calls[-1], ("save", "ws://localhost:9999", "", 0, True))
        self.assertTrue(window.info["has_password"])
        window.mode.set(1)
        window.primary_button.invoke()
        self.assertEqual(len(control.calls), 1)
        self.assertEqual(window.local_error, "empty_password")
        window.password.set("private-password-é")
        self.assertTrue(window.password_entry.cget("show"))
        window.primary_button.invoke()
        self.pump(lambda: len(control.calls) == 2 and not window.busy)
        self.assertEqual(control.calls[-1][2:4], ("private-password-é", 1))
        self.assertEqual(window.password.get(), "")
        self.assertEqual(window.mode.get(), 0)
        window.mode.set(2)
        window.primary_button.invoke()
        self.pump(lambda: len(control.calls) == 3 and not window.busy)
        self.assertEqual(control.calls[-1][2:4], ("", 2))
        self.assertFalse(window.info["has_password"])

    def test_polls_follow_game_changes_and_preserve_user_edits(self):
        window = self.open()
        self.idle()
        control = self.controls[self.profiles[0].root]
        control.current.update(server="ws://game-menu:3333", auto_connect=False, live=True,
                               running=True, state="connected")
        self.pump(lambda: window.server.get() == "ws://game-menu:3333")
        self.assertFalse(window.automatic.get())
        self.assertEqual(window.primary_button.cget("text"), "Connect")
        self.assertTrue(window.disconnect_button.winfo_manager())
        window.server.set("ws://unfinished-edit:4444")
        window.automatic.set(True)
        control.current.update(server="ws://game-menu:5555", auto_connect=False, state="retrying")
        self.pump(lambda: window.info.get("state") == "retrying")
        self.assertEqual(window.server.get(), "ws://unfinished-edit:4444")
        self.assertTrue(window.automatic.get())
        window.primary_button.invoke()
        self.pump(lambda: bool(control.calls) and not window.busy)
        self.assertEqual(control.calls[-1][0], "connect")
        window.disconnect_button.invoke()
        self.pump(lambda: control.calls[-1] == ("disconnect",) and not window.busy)
        self.assertEqual(window.info["state"], "disconnected")

    def test_slow_io_keeps_tk_responsive_and_old_profile_results_are_ignored(self):
        first = self.controls[self.profiles[0].root]
        first.info_gate = threading.Event()
        window = self.open()
        self.pump(first.started.is_set)
        callbacks = []
        self.root.after(20, lambda: callbacks.append(True))
        self.pump(lambda: bool(callbacks), timeout=.5)
        window.mode.set(1)
        window.password.set("never-copy-to-next-profile")
        window.profile_choice.current(1)
        window.profile_choice.event_generate("<<ComboboxSelected>>")
        self.root.update()
        self.assertEqual(window.password.get(), "")
        self.assertEqual(window.mode.get(), 0)
        self.assertEqual(window.slot.get(), "Zelda")
        first.info_gate.set()
        self.pump(lambda: not window.pending_poll)
        self.assertEqual(window.server.get(), self.profiles[1].server)
        self.assertEqual(window.slot.get(), "Zelda")

    def test_action_does_not_overwrite_edits_made_while_request_is_running(self):
        window = self.open()
        self.idle()
        control = self.controls[self.profiles[0].root]
        control.action_gate = threading.Event()
        window.server.set("ws://submitted:1234")
        window.primary_button.invoke()
        self.pump(control.started.is_set)
        window.server.set("ws://next-edit:2345")
        control.action_gate.set()
        self.pump(lambda: not window.busy)
        self.assertEqual(window.server.get(), "ws://next-edit:2345")
        self.assertIn("server", window.dirty)

    def test_password_for_next_request_survives_an_earlier_success(self):
        window = self.open()
        self.idle()
        control = self.controls[self.profiles[0].root]
        control.action_gate = threading.Event()
        window.mode.set(1)
        window.password.set("submitted-password")
        window.primary_button.invoke()
        self.pump(control.started.is_set)
        window.password.set("next-password")
        control.action_gate.set()
        self.pump(lambda: not window.busy)
        self.assertEqual(control.calls[-1][2], "submitted-password")
        self.assertEqual(window.password.get(), "next-password")
        self.assertEqual(window.mode.get(), 1)
        self.assertIn("password", window.dirty)

    def test_disconnect_preserves_unsaved_connection_edits(self):
        window = self.open()
        self.idle()
        control = self.controls[self.profiles[0].root]
        control.current.update(live=True, running=True, state="connected")
        self.pump(lambda: window.info.get("live"))
        window.server.set("ws://unsaved:3456")
        window.automatic.set(False)
        window.mode.set(1)
        window.password.set("unsaved-password")
        dirty = set(window.dirty)
        window.disconnect_button.invoke()
        self.pump(lambda: bool(control.calls) and not window.busy)
        self.assertEqual(control.calls[-1], ("disconnect",))
        self.assertEqual(window.server.get(), "ws://unsaved:3456")
        self.assertFalse(window.automatic.get())
        self.assertEqual(window.password.get(), "unsaved-password")
        self.assertEqual(window.mode.get(), 1)
        self.assertEqual(window.dirty, dirty)

    def test_closing_clears_plaintext_and_never_disconnects_the_game(self):
        window = self.open()
        self.idle()
        control = self.controls[self.profiles[0].root]
        control.current.update(live=True, running=True, state="connected")
        self.pump(lambda: window.info.get("live"))
        window.mode.set(1)
        window.password.set("private-close-password")
        window.close()
        self.assertEqual(window.password.get(), "")
        self.assertEqual(control.calls, [])

    def test_refresh_replaces_controller_binding_and_preserves_address_edit(self):
        window = self.open()
        self.idle()
        recreated = []
        window.controller_factory = lambda root: recreated.append(root) or self.controls[root]
        window.server.set("ws://unsaved-refresh:3456")
        window.mode.set(1)
        window.password.set("clear-on-refresh")
        window.refresh_button.invoke()
        self.pump(lambda: not window.refreshing and not window.pending_poll)
        self.assertEqual(recreated, [self.profiles[0].root])
        self.assertEqual(window.server.get(), "ws://unsaved-refresh:3456")
        self.assertEqual(window.password.get(), "")
        self.assertEqual(window.mode.get(), 0)

    def test_all_state_and_error_messages_have_french_translations(self):
        for text in [*STATES.values(), *ERRORS.values()]:
            with self.subTest(text=text):
                self.assertNotEqual(tr(text, language="fr"), text)


if __name__ == "__main__":
    unittest.main()
