"""Chat through the authenticated native owner, without another AP login."""
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk

from .connection_control import Controller
from .i18n import tr


def _work(controller, jobs, results, stop):
    while not stop.is_set():
        try:
            kind, text = jobs.get(timeout=.2)
        except queue.Empty:
            continue
        try:
            result = controller.chat() if kind == "poll" else controller.say(text)
        except Exception:
            result = {"result": -1, "error_code": "rpc_unavailable", "messages": []}
        results.put((kind, text, result))


class ChatWindow:
    def __init__(self, master, profile, *, language="en", controller_factory=Controller, poll_ms=750):
        self.master, self.language = master, language
        self.controller = controller_factory(Path(profile))
        self.poll_ms = max(100, poll_ms)
        self.closed = self.sending = self.polling = False
        self.stream, self.last_id, self.after_ids = None, 0, set()
        self.jobs, self.results = queue.Queue(maxsize=8), queue.Queue()
        self.stop = threading.Event()
        master.title(self.text("Archipelago chat"))
        master.geometry("780x500")
        master.minsize(600, 360)
        master.columnconfigure(0, weight=1)
        master.rowconfigure(1, weight=1)
        ttk.Label(master, text=self.text("Chat uses Zelda's existing connection. Messages are sent only when you press Send."),
                  wraplength=730, padding=16).grid(row=0, column=0, sticky="ew")
        area = ttk.Frame(master, padding=(16, 0))
        area.grid(row=1, column=0, sticky="nsew")
        area.columnconfigure(0, weight=1)
        area.rowconfigure(0, weight=1)
        self.history = tk.Text(area, wrap="word", state="disabled", height=14, takefocus=True)
        self.history.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(area, orient="vertical", command=self.history.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.history.configure(yscrollcommand=scrollbar.set)
        actions = ttk.Frame(master, padding=16)
        actions.grid(row=2, column=0, sticky="ew")
        actions.columnconfigure(0, weight=1)
        self.message = tk.StringVar()
        self.entry = ttk.Entry(actions, textvariable=self.message)
        self.entry.grid(row=0, column=0, sticky="ew")
        self.entry.bind("<Return>", lambda _event: self.send())
        self.send_button = ttk.Button(actions, text=self.text("Send"), command=self.send)
        self.send_button.grid(row=0, column=1, padx=(10, 0))
        self.status = ttk.Label(master, padding=(16, 0, 16, 12), wraplength=730)
        self.status.grid(row=3, column=0, sticky="ew")
        master.protocol("WM_DELETE_WINDOW", self.close)
        master.bind("<Escape>", lambda _event: self.close())
        self.worker = threading.Thread(target=_work, args=(self.controller, self.jobs, self.results, self.stop),
                                       name="Archipelago chat controls", daemon=True)
        self.worker.start()
        self.schedule(40, self.receive)
        self.poll()

    def text(self, message, **values):
        return tr(message, language=self.language, **values)

    def schedule(self, delay, callback):
        def run():
            self.after_ids.discard(identifier)
            if not self.closed:
                callback()
        identifier = self.master.after(delay, run)
        self.after_ids.add(identifier)

    def poll(self):
        if not self.closed and not self.polling:
            try:
                self.jobs.put_nowait(("poll", None))
                self.polling = True
            except queue.Full:
                pass
        if not self.closed:
            self.schedule(self.poll_ms, self.poll)

    def send(self):
        if self.closed or self.sending:
            return
        text = self.message.get()
        if not text.strip():
            return
        try:
            self.jobs.put_nowait(("say", text))
        except queue.Full:
            return
        self.sending = True
        self.send_button.configure(state="disabled")

    def receive(self):
        while True:
            try:
                kind, text, result = self.results.get_nowait()
            except queue.Empty:
                break
            if kind == "poll":
                self.polling = False
            else:
                self.sending = False
                self.send_button.configure(state="normal")
                if result.get("result", -1) > 0 and self.message.get() == text:
                    self.message.set("")
            code = result.get("error_code", "")
            if code:
                messages = {"chat_disconnected": "Connect Zelda to Archipelago before using chat.",
                            "invalid_chat_message": "The message is empty, too long or contains unsupported control characters.",
                            "native_update_required": "Update the installed mod to use chat."}
                self.status.configure(text=self.text(messages.get(code, "Chat is unavailable. Check Zelda's connection and try again.")))
            else:
                self.status.configure(text=self.text("Recent server messages. You can use commands such as !hint."))
            stream = result.get("stream")
            if stream and stream != self.stream:
                self.stream, self.last_id = stream, 0
            rows = [row for row in result.get("messages", []) if row["id"] > self.last_id]
            if rows:
                self.history.configure(state="normal")
                for row in rows:
                    self.history.insert("end", row["text"] + "\n")
                    self.last_id = max(self.last_id, row["id"])
                if int(self.history.index("end-1c").split(".")[0]) > 500:
                    self.history.delete("1.0", "100.0")
                self.history.configure(state="disabled")
                self.history.see("end")
        self.schedule(40, self.receive)

    def close(self):
        if not self.closed:
            self.closed = True
            self.stop.set()
            self.message.set("")
            for identifier in self.after_ids:
                self.master.after_cancel(identifier)
            self.after_ids.clear()
            self.master.destroy()
