"""Actual widgets send chat only on explicit submission, outside Tk's thread."""
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.chat_window import ChatWindow


class ChatWidgets(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.window = None
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except tk.TclError as error:
            self.temp.cleanup()
            self.skipTest(str(error))

    def tearDown(self):
        if self.window:
            self.window.close()
        else:
            self.root.destroy()
        self.temp.cleanup()

    def pump(self, condition, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.root.update()
            if condition():
                return
            time.sleep(.005)
        self.fail("Chat worker did not finish")

    def test_opening_only_reads_and_send_is_explicit_and_asynchronous(self):
        calls = []
        class FakeController:
            def __init__(self, _profile):
                pass
            def chat(self):
                calls.append(("read", threading.get_ident()))
                return {"result": 1, "messages": [{"id": 1, "text": "Server message"}], "stream": 7}
            def say(self, text):
                calls.append((text, threading.get_ident()))
                return {"result": 1, "messages": [{"id": 1, "text": "Server message"}], "stream": 7}
        self.window = ChatWindow(self.root, Path(self.temp.name), controller_factory=FakeController, poll_ms=100)
        self.pump(lambda: "Server message" in self.window.history.get("1.0", "end"))
        self.assertFalse(any(row[0] != "read" for row in calls))
        self.window.message.set("!hint Bow")
        self.window.send_button.invoke()
        self.pump(lambda: self.window.message.get() == "")
        self.assertIn("!hint Bow", [row[0] for row in calls])
        self.assertTrue(all(row[1] != threading.get_ident() for row in calls))
        self.assertEqual(self.window.history.get("1.0", "end").count("Server message"), 1)


if __name__ == "__main__":
    unittest.main()
