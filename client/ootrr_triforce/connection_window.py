"""Optional desktop controls for the in-game Archipelago connection.

Only the controller talks to the game's authenticated local endpoint. All of
that I/O runs on a daemon worker; Tk widgets are touched by the Tk thread only.
"""
import argparse
from dataclasses import dataclass
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk

from .connection_control import Controller, default_profile, discover_profiles, remember_profile
from .i18n import normalize_language, tr


STATES = {
    "waiting_for_game": "Waiting for the game",
    "disconnected": "Disconnected",
    "connecting": "Connecting…",
    "authenticating": "Signing in…",
    "synchronizing": "Synchronizing…",
    "connected": "Connected",
    "retrying": "Reconnecting…",
}
ERRORS = {
    "invalid_server": "Enter a server address and a port from 1 to 65535.",
    "invalid_password": "The password is invalid. Choose Keep, Replace or Clear explicitly.",
    "empty_password": "Enter a replacement password, or choose Keep or Clear.",
    "credential_error": "The saved password cannot be used on this PC. Replace or clear it.",
    "settings_error": "Connection settings could not be saved.",
    "no_profile": "This profile is unavailable. Run Configure-Archipelago.cmd first.",
    "profile_changed": "The profile changed. Refresh the profile list before trying again.",
    "native_update_required": "Update the installed mod to control its connection from this window.",
    "rpc_unavailable": "The game's local controls are unavailable. Try again in a moment.",
    "rpc_unauthorized": "The game's local controls could not be authenticated. Restart this window.",
    "rpc_invalid_response": "The game returned an invalid local response. Update the installed mod.",
    "busy": "The game is busy. Try again in a moment.",
    "unsupported_live_save": "Use Connect to apply settings while the game is running.",
    "wrong_room": "This server is hosting a different room.",
    "wrong_slot": "The player does not match this prepared mod.",
    "connection_refused": "Connection refused. Check the room and password.",
    "unknown_item": "This room requires a newer client.",
    "connection_lost": "Server unavailable. Check its address and connection.",
    "connection_failed": "Server unavailable. Check its address and connection.",
    "unexpected": "The local connection controls are unavailable. Refresh and try again.",
}


@dataclass
class _Task:
    generation: int
    kind: str
    operation: object
    revisions: dict


class ConnectionWindow:
    """A small Tk window, with injectable controls for actual-widget tests."""

    def __init__(self, master, *, base=None, explicit=None, controller_factory=Controller,
                 poll_ms=750, discover=discover_profiles, choose_default=default_profile):
        self.master, self.base, self.explicit = master, base, explicit
        self.controller_factory = controller_factory
        self.discover, self.choose_default = discover, choose_default
        self.poll_ms = max(100, poll_ms)
        self.profiles, self.controller, self.selected = [], None, None
        self.language, self.info = "en", {}
        self.generation = 0
        self.dirty, self.revisions = set(), {name: 0 for name in ("server", "automatic", "password", "mode")}
        self.updating = False
        self.closed = self.busy = self.pending_poll = self.refreshing = False
        self.local_error, self.notice = "", ""
        self.jobs, self.results = queue.Queue(maxsize=4), queue.Queue(maxsize=8)
        self.stop = threading.Event()
        self.after_ids = set()
        self.labels = []
        self._build()
        self.worker = threading.Thread(target=self._work, name="Archipelago local controls", daemon=True)
        self.worker.start()
        self.master.protocol("WM_DELETE_WINDOW", self.close)
        self._schedule(40, self._receive)
        self._schedule(self.poll_ms, self._poll)
        self.refresh_profiles()

    def _text(self, text, **values):
        return tr(text, language=self.language, **values)

    def _label(self, parent, text, **options):
        widget = ttk.Label(parent, **options)
        self.labels.append((widget, text))
        return widget

    def _build(self):
        self.master.minsize(600, 520)
        self.master.geometry("660x560")
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)
        pane = ttk.Frame(self.master, padding=20)
        pane.grid(sticky="nsew")
        pane.columnconfigure(1, weight=1)
        self._label(pane, "Archipelago connection", font=("Segoe UI", 15, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 16))
        self._label(pane, "Profile").grid(row=1, column=0, sticky="w", padx=(0, 12))
        self.profile_choice = ttk.Combobox(pane, state="readonly", width=38)
        self.profile_choice.grid(row=1, column=1, sticky="ew")
        self.profile_choice.bind("<<ComboboxSelected>>", self._select_event)
        self.refresh_button = ttk.Button(pane, command=self.refresh_profiles)
        self.labels.append((self.refresh_button, "Refresh"))
        self.refresh_button.grid(row=1, column=2, padx=(10, 0))
        self.room, self.slot = tk.StringVar(), tk.StringVar()
        for row, (label, variable) in enumerate((("Room", self.room), ("Slot", self.slot)), 2):
            self._label(pane, label).grid(row=row, column=0, sticky="w", pady=(10, 0))
            ttk.Entry(pane, textvariable=variable, state="readonly").grid(
                row=row, column=1, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Separator(pane).grid(row=4, column=0, columnspan=3, sticky="ew", pady=16)
        self.server, self.password = tk.StringVar(), tk.StringVar()
        self.mode, self.automatic = tk.IntVar(value=0), tk.BooleanVar(value=True)
        self._label(pane, "Server address").grid(row=5, column=0, sticky="w", padx=(0, 12))
        self.server_entry = ttk.Entry(pane, textvariable=self.server)
        self.server_entry.grid(row=5, column=1, columnspan=2, sticky="ew")
        self.server_entry.bind("<Return>", self._apply_event)
        self._label(pane, "Room password").grid(row=6, column=0, sticky="nw", padx=(0, 12), pady=(16, 0))
        password_box = ttk.Frame(pane)
        password_box.grid(row=6, column=1, columnspan=2, sticky="ew", pady=(12, 0))
        password_box.columnconfigure(0, weight=1)
        self.password_status = ttk.Label(password_box)
        self.password_status.grid(row=0, column=0, sticky="w", pady=(0, 5))
        modes = ttk.Frame(password_box)
        modes.grid(row=1, column=0, sticky="w")
        self.mode_buttons = []
        for index, text in enumerate(("Keep", "Replace", "Clear")):
            button = ttk.Radiobutton(modes, variable=self.mode, value=index)
            self.labels.append((button, text))
            button.grid(row=0, column=index, padx=(0, 20))
            self.mode_buttons.append(button)
        self.password_entry = ttk.Entry(password_box, textvariable=self.password, show="•", state="disabled")
        self.password_entry.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.password_entry.bind("<Return>", self._apply_event)
        self.auto_button = ttk.Checkbutton(pane, variable=self.automatic)
        self.labels.append((self.auto_button, "Connect automatically when the game starts"))
        self.auto_button.grid(row=7, column=0, columnspan=3, sticky="w", pady=(16, 0))
        status_box = ttk.Frame(pane)
        status_box.grid(row=8, column=0, columnspan=3, sticky="nsew", pady=(18, 12))
        status_box.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(status_box, font=("Segoe UI", 10, "bold"), wraplength=600)
        self.status_label.grid(row=0, column=0, sticky="w")
        self.detail_label = ttk.Label(status_box, wraplength=600)
        self.detail_label.grid(row=1, column=0, sticky="w", pady=(6, 0))
        pane.rowconfigure(8, weight=1)
        actions = ttk.Frame(pane)
        actions.grid(row=9, column=0, columnspan=3, sticky="e")
        self.disconnect_button = ttk.Button(actions, command=self.disconnect)
        self.labels.append((self.disconnect_button, "Disconnect"))
        self.disconnect_button.grid(row=0, column=0, padx=(0, 10))
        self.primary_button = ttk.Button(actions, command=self.apply)
        self.primary_button.grid(row=0, column=1)
        self._label(pane, "You can close this window while playing.").grid(
            row=10, column=0, columnspan=3, sticky="w", pady=(14, 0))
        for name, variable in (("server", self.server), ("password", self.password),
                               ("mode", self.mode), ("automatic", self.automatic)):
            variable.trace_add("write", lambda *_args, name=name: self._edited(name))
        self._render()

    def _edited(self, name):
        if self.updating:
            return
        self.dirty.add(name)
        self.revisions[name] += 1
        self.local_error = self.notice = ""
        if name == "mode":
            # Merely visiting an empty field never requests password removal.
            if self.mode.get() != 1:
                self._set(self.password, "")
            self.password_entry.configure(state="normal" if self.mode.get() == 1 else "disabled")
        self._render()

    def _set(self, variable, value):
        self.updating = True
        try:
            variable.set(value)
        finally:
            self.updating = False

    def _schedule(self, delay, callback):
        def run():
            self.after_ids.discard(identifier)
            if not self.closed:
                callback()
        identifier = self.master.after(delay, run)
        self.after_ids.add(identifier)

    def _submit(self, kind, operation):
        try:
            self.jobs.put_nowait(_Task(self.generation, kind, operation, dict(self.revisions)))
            return True
        except queue.Full:
            return False

    def _work(self):
        while not self.stop.is_set():
            try:
                task = self.jobs.get(timeout=.2)
            except queue.Empty:
                continue
            try:
                result = task.operation()
            except Exception:
                # Never put arbitrary exceptions in the UI: they may contain credentials.
                result = {"result": -1, "error_code": "unexpected"}
            if not self.stop.is_set():
                try:
                    self.results.put((task, result), timeout=.2)
                except queue.Full:
                    pass
            del task, result

    def refresh_profiles(self):
        if self.refreshing or self.closed:
            return
        def discover():
            profiles = self.discover(base=self.base, explicit=self.explicit)
            preferred = self.choose_default(base=self.base, explicit=self.explicit)
            return profiles, preferred.root if preferred else None
        self.refreshing = self._submit("profiles", discover)
        self._render()

    def _select_event(self, _event=None):
        index = self.profile_choice.current()
        if 0 <= index < len(self.profiles):
            self.select_profile(self.profiles[index])

    def select_profile(self, profile):
        self.generation += 1
        self.selected, self.controller = profile, self.controller_factory(profile.root)
        self.language = normalize_language(profile.language)
        self.info = {"server": profile.server, "slot": profile.slot, "room": profile.room,
                     "has_password": profile.has_password, "auto_connect": profile.auto_connect,
                     "state": "waiting_for_game", "live": False, "language": self.language}
        self.pending_poll = self.busy = False
        self.local_error = self.notice = ""
        self.dirty.clear()
        self._set(self.password, "")
        self._set(self.mode, 0)
        self._update_info(self.info)
        # Remembering the selected profile also stays outside the Tk thread.
        self._submit("remember", lambda: remember_profile(profile.root, base=self.base))
        self._request_info()

    def _request_info(self):
        if self.controller is not None and not self.pending_poll and not self.busy:
            self.pending_poll = self._submit("info", self.controller.info)

    def _poll(self):
        self._request_info()
        self._schedule(self.poll_ms, self._poll)

    def _receive(self):
        while True:
            try:
                task, result = self.results.get_nowait()
            except queue.Empty:
                break
            if task.kind == "profiles":
                self.refreshing = False
                if isinstance(result, tuple):
                    profiles, preferred = result
                    previous = self.selected.root if self.selected else preferred
                    self.profiles = profiles
                    self.profile_choice.configure(values=[f"{p.room} · {p.slot}" for p in profiles])
                    if profiles:
                        index = next((i for i, p in enumerate(profiles) if p.root == previous), 0)
                        self.profile_choice.current(index)
                        if self.selected is None or self.selected.root != profiles[index].root:
                            self.select_profile(profiles[index])
                        else:
                            # Refresh also accepts a newly prepared session in the same folder.
                            # Retire the old controller's immutable identity binding.
                            self.generation += 1
                            self.selected = profiles[index]
                            self.controller = self.controller_factory(self.selected.root)
                            self.pending_poll = self.busy = False
                            self.local_error = self.notice = ""
                            self._set(self.password, "")
                            self._set(self.mode, 0)
                            self.dirty.difference_update(("password", "mode"))
                            self._request_info()
                    else:
                        self.generation += 1
                        self.selected = self.controller = None
                        self.info, self.dirty = {}, set()
                        self._set(self.password, "")
                        self._set(self.mode, 0)
                        for variable in (self.room, self.slot, self.server):
                            self._set(variable, "")
                        self.profile_choice.set("")
                else:
                    self.local_error = "unexpected"
            elif task.generation == self.generation:
                if task.kind == "info":
                    self.pending_poll = False
                    if isinstance(result, dict):
                        self._update_info(result)
                elif task.kind in {"apply", "disconnect"}:
                    self.busy = False
                    if isinstance(result, dict):
                        succeeded = isinstance(result.get("result"), int) and result["result"] >= 0
                        if succeeded:
                            if task.kind == "apply":
                                for name, revision in task.revisions.items():
                                    if self.revisions[name] == revision:
                                        self.dirty.discard(name)
                                # A password typed for the next command is still an unsaved edit.
                                if all(self.revisions[name] == task.revisions[name]
                                       for name in ("password", "mode")):
                                    self._set(self.password, "")
                                    self._set(self.mode, 0)
                                    self.dirty.difference_update(("password", "mode"))
                            self.local_error = ""
                            self.notice = "saved" if task.kind == "apply" and not result.get("live") else ""
                        else:
                            self.local_error = result.get("error_code") or "unexpected"
                        self._update_info(result)
            self._render()
        self._schedule(40, self._receive)

    def _update_info(self, info):
        self.info.update(info)
        self.language = normalize_language(self.info.get("language", self.language))
        self._set(self.room, self.info.get("room", self.room.get()))
        self._set(self.slot, self.info.get("slot", self.slot.get()))
        if "server" not in self.dirty:
            self._set(self.server, self.info.get("server", self.server.get()))
        if "automatic" not in self.dirty:
            self._set(self.automatic, self.info.get("auto_connect", self.automatic.get()))
        self._render()

    def apply(self):
        if self.controller is None or self.busy:
            return
        mode, password = self.mode.get(), self.password.get()
        if mode == 1 and not password:
            self.local_error = "empty_password"
            self._render()
            self.password_entry.focus_set()
            return
        controller = self.controller
        server, automatic = self.server.get(), self.automatic.get()
        method = controller.apply if self.info.get("live") else controller.save
        self.local_error = self.notice = ""
        self.busy = self._submit("apply", lambda: method(server, password if mode == 1 else "", mode, automatic))
        self._render()

    def _apply_event(self, _event):
        self.apply()
        return "break"

    def disconnect(self):
        if self.controller is not None and self.info.get("live") and not self.busy:
            self.local_error = self.notice = ""
            self.busy = self._submit("disconnect", self.controller.disconnect)
            self._render()

    def _render(self):
        self.master.title(self._text("Archipelago connection"))
        for widget, text in self.labels:
            widget.configure(text=self._text(text))
        self.refresh_button.configure(state="disabled" if self.refreshing else "normal")
        available, live = self.selected is not None, bool(self.info.get("live"))
        for widget in (self.server_entry, self.auto_button, *self.mode_buttons):
            widget.configure(state="normal" if available else "disabled")
        self.password_entry.configure(state="normal" if available and self.mode.get() == 1 else "disabled")
        self.primary_button.configure(text=self._text("Connect" if live else "Save"),
                                      state="normal" if available and not self.busy else "disabled")
        if live:
            self.disconnect_button.grid()
            self.disconnect_button.configure(state="disabled" if self.busy else "normal")
        else:
            self.disconnect_button.grid_remove()
        self.password_status.configure(text=self._text(
            "A password is saved on this PC." if self.info.get("has_password") else "No password is saved."))
        if not available:
            status = "Searching for profiles…" if self.refreshing else "No configured profile"
            detail = "Run Configure-Archipelago.cmd to prepare a room, then click Refresh."
        else:
            status = STATES.get(self.info.get("state"), "Waiting for the game")
            detail = ("Game detected. These controls use the in-game client." if live else
                      "Settings will be used when the game starts with this room's mod.")
            if self.notice == "saved":
                detail = "Settings saved. Start the game with this room's mod to connect."
        error = self.local_error or self.info.get("error_code")
        if error:
            detail = ERRORS.get(error, ERRORS["unexpected"])
        self.status_label.configure(text=self._text("Applying…" if self.busy else status))
        self.detail_label.configure(text=self._text(detail))

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.stop.set()
        while True:
            try:
                self.jobs.get_nowait()
            except queue.Empty:
                break
        self._set(self.password, "")
        self._set(self.mode, 0)
        for identifier in self.after_ids:
            self.master.after_cancel(identifier)
        self.after_ids.clear()
        # The connection belongs to the game; closing this window makes no call.
        self.master.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Desktop controls for the in-game Archipelago client.")
    parser.add_argument("--profile", type=Path, help="Use only this prepared profile (also useful for private tests).")
    parser.add_argument("--base", type=Path, help="Override the local profile directory.")
    args = parser.parse_args(argv)
    root = tk.Tk()
    ConnectionWindow(root, base=args.base, explicit=args.profile)
    root.mainloop()


if __name__ == "__main__":
    main()
