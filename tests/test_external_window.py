"""The external UI owns one runtime and never touches native room controls."""
from collections import deque
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.external_window import ExternalWindow


class FakeRuntime:
    def __init__(self):
        self.started = self.stopped = False
        self.messages = []
        self.client = types.SimpleNamespace(log=deque(["Server message"]), log_count=1)
    def start(self):
        self.started = True
    def stop(self):
        self.stopped = True
    def summary(self):
        return dict(connected=self.started and not self.stopped, status="Connected", checks=2, total=20, received=3)
    def say(self, text):
        self.messages.append(text)


class FakeExternal:
    def __init__(self, root):
        self.root, self.calls, self.runtime = root, [], None
        self.data = dict(profile=str(root / "external-profile"), ready=True, source=str(root / "romfs"),
                         mods=str(root / "mods"), executable=str(root / "emulator.exe"), game_file="",
                         save_path="", server="localhost:38281", auto_connect=True, slot="Link", room="External room")
    def call(self, name, *args):
        self.calls.append((name, args, threading.get_ident()))
    def list_profiles(self, base):
        self.call("list", base)
        return [dict(self.data)]
    def open_profile(self, profile):
        self.call("open", profile)
        return dict(self.data)
    def configure(self, request, progress):
        self.call("prepare", request)
        progress(50, "Preparing every Archipelago reward...")
        return dict(self.data)
    def update_preferences(self, profile, **values):
        self.call("preferences", profile, values)
        self.data.update(values)
        return dict(self.data)
    def connect(self, profile, password=None):
        self.call("connect", profile, password)
        self.runtime = FakeRuntime()
        return self.runtime
    def launch(self, profile):
        self.call("launch", profile)


class ExternalWidgets(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.service = FakeExternal(self.base)
        self.window = None
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except tk.TclError as error:
            self.temp.cleanup()
            self.skipTest(str(error))

    def tearDown(self):
        if self.window and not self.window.closed:
            self.window.close()
            self.pump(lambda: self.window.closed)
        elif not self.window:
            self.root.destroy()
        self.temp.cleanup()

    def pump(self, condition, timeout=4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.window and self.window.closed:
                if condition():
                    return
                break
            self.root.update()
            if condition():
                return
            time.sleep(.005)
        self.fail("External UI worker did not finish")

    def open(self, profile=None):
        self.window = ExternalWindow(self.root, base=self.base, service=self.service, profile=profile)
        self.pump(lambda: not self.window.busy)
        return self.window

    def test_opening_profile_does_not_connect_or_launch(self):
        window = self.open(self.service.data["profile"])
        self.assertEqual([row[0] for row in self.service.calls], ["open"])
        self.assertIsNone(window.runtime)
        self.assertEqual(str(window.play_button.cget("state")), "normal")
        self.assertEqual(str(window.send_button.cget("state")), "disabled")

    def test_prepare_erases_visible_password_and_never_connects_implicitly(self):
        window = self.open()
        window.fields["player_file"].set(str(self.base / "player.apootrr"))
        window.fields["password"].set("private-password")
        window.prepare_button.invoke()
        self.assertEqual(window.fields["password"].get(), "")
        self.pump(lambda: not window.busy)
        prepared = next(row for row in self.service.calls if row[0] == "prepare")
        self.assertEqual(prepared[1][0]["password"], "private-password")
        self.assertFalse(any(row[0] == "connect" for row in self.service.calls))
        self.assertTrue(all(row[2] != threading.get_ident() for row in self.service.calls))

    def test_old_room_prefills_original_player_and_exposes_update_without_launch(self):
        self.service.data.update(ready=False, reprepare_required=True)
        window = self.open(self.service.data['profile'])
        self.assertEqual(window.fields['player_file'].get(), str(Path(self.service.data['profile']) / 'player.apootrr'))
        self.assertEqual(str(window.play_button.cget('state')), 'disabled')
        self.assertEqual(str(window.connect_button.cget('state')), 'disabled')
        self.assertEqual(str(window.prepare_button.cget('state')), 'normal')
        self.assertIn('Update', window.prepare_button.cget('text'))
        self.assertIn('same player file', window.status.cget('text'))
        self.assertFalse(any(row[0] in ('connect', 'launch') for row in self.service.calls))

    def test_launch_connect_chat_and_close_share_one_runtime(self):
        window = self.open(self.service.data["profile"])
        window.play_button.invoke()
        self.pump(lambda: window.runtime is not None and not window.busy)
        runtime = window.runtime
        self.assertTrue(runtime.started)
        self.assertEqual([row[0] for row in self.service.calls].count("connect"), 1)
        window.message.set("!hint Bow")
        window.say()
        self.pump(lambda: not window.busy)
        self.assertEqual(runtime.messages, ["!hint Bow"])
        self.assertEqual(window.message.get(), "")
        window.close()
        self.pump(lambda: window.closed)
        self.assertTrue(runtime.stopped)
        self.assertEqual([row[0] for row in self.service.calls].count("connect"), 1)

    def test_changing_save_preferences_does_not_reinstall_or_modify_the_save(self):
        window = self.open(self.service.data["profile"])
        save = self.base / "emulator-save/progress.sav"
        save.parent.mkdir()
        save.write_bytes(b"original-save")
        window.fields["save_path"].set(str(save))
        window.connect_button.invoke()
        self.pump(lambda: window.runtime is not None and not window.busy)
        preferences = next(row for row in self.service.calls if row[0] == "preferences")
        self.assertEqual(preferences[1][1]["save_path"], str(save))
        self.assertFalse(any(row[0] == "prepare" for row in self.service.calls))
        self.assertEqual(save.read_bytes(), b"original-save")


if __name__ == "__main__":
    unittest.main()
