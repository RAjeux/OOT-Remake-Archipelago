"""Separate setup and lifetime owner for an external port/emulator AP client."""
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from .i18n import tr


FIELD_TEXT = {
    "player_file": "Full-network player file",
    "source": "Game resources (RomFS folder or NUP file)",
    "mods": "This game's mods folder",
    "executable": "Port or emulator executable",
    "game_file": "Game file to open (optional)",
    "save_path": "Save to observe (optional before the first save)",
    "server": "Room address",
    "password": "Password (leave blank to keep the saved password)",
}


class ExternalWindow:
    def __init__(self, master, *, base=None, language="en", profile=None, service=None, dialogs=filedialog):
        if service is None:
            from . import external_setup as service
        self.master, self.base, self.language, self.service, self.dialogs = master, base, language, service, dialogs
        self.closed = self.busy = self.close_requested = False
        self.runtime, self.current, self.profiles, self.tracker_window = None, {}, [], None
        self.log_count = -1
        self.jobs, self.results = queue.Queue(), queue.Queue()
        self.stop = threading.Event()
        self.after_ids, self.widgets, self.installation_widgets = set(), [], []
        self.fields = {name: tk.StringVar() for name in FIELD_TEXT}
        self.automatic = tk.BooleanVar(value=True)
        self.clear_password = tk.BooleanVar(value=False)
        self.master.title(self.text("Other ports and emulators"))
        self.master.geometry("860x820")
        self.master.minsize(700, 600)
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(1, weight=1)
        ttk.Label(master, text=self.text("External connection · full-network rooms"),
                  font=("Segoe UI", 15, "bold"), padding=16).grid(row=0, column=0, sticky="ew")
        notebook = ttk.Notebook(master)
        notebook.grid(row=1, column=0, sticky="nsew", padx=16)
        setup = ttk.Frame(notebook)
        setup.columnconfigure(0, weight=1)
        setup.rowconfigure(0, weight=1)
        notebook.add(setup, text=self.text("Set up a room"))
        canvas = tk.Canvas(setup, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(setup, orient="vertical", command=canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scrollbar.set)
        form = ttk.Frame(canvas, padding=(12, 12, 24, 20))
        form.columnconfigure(0, weight=1)
        window = canvas.create_window((0, 0), window=form, anchor="nw")
        form.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
        canvas.bind("<MouseWheel>", lambda event: canvas.yview_scroll(-int(event.delta / 120), "units"))
        ttk.Label(form, text=self.text("Keep this window open while playing: it owns the external Archipelago connection. Native Triforce and Hookshot setup stays separate."),
                  wraplength=740).grid(row=0, column=0, sticky="ew", pady=(0, 12))
        profiles = ttk.Frame(form)
        profiles.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        profiles.columnconfigure(0, weight=1)
        self.profile_choice = ttk.Combobox(profiles, state="readonly")
        self.profile_choice.grid(row=0, column=0, sticky="ew")
        self.profile_choice.bind("<<ComboboxSelected>>", self.choose_profile)
        ttk.Button(profiles, text=self.text("Refresh"), command=self.refresh_profiles).grid(row=0, column=1, padx=(10, 0))
        self.widgets.append(self.profile_choice)
        self.installation_widgets.append(self.profile_choice)
        for row, (name, label) in enumerate(FIELD_TEXT.items(), 2):
            area = ttk.Frame(form)
            area.grid(row=row, column=0, sticky="ew", pady=(0, 10))
            area.columnconfigure(0, weight=1)
            ttk.Label(area, text=self.text(label)).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
            entry = ttk.Entry(area, textvariable=self.fields[name], show="•" if name == "password" else "")
            entry.grid(row=1, column=0, sticky="ew")
            self.widgets.append(entry)
            if name not in {"save_path", "server", "password"}:
                self.installation_widgets.append(entry)
            if name not in {"server", "password"}:
                browse = ttk.Button(area, text=self.text("Browse…"), command=lambda key=name: self.browse(key))
                browse.grid(row=1, column=1, padx=(10, 0))
                self.widgets.append(browse)
                if name != "save_path":
                    self.installation_widgets.append(browse)
            if name == "source":
                button = ttk.Button(area, text=self.text("Choose NUP…"), command=lambda: self.browse("source", file=True))
                button.grid(row=1, column=2, padx=(10, 0))
                self.widgets.append(button)
                self.installation_widgets.append(button)
        self.fields["server"].set("archipelago.gg:38281")
        clear = ttk.Checkbutton(form, text=self.text("Forget the saved password"), variable=self.clear_password)
        clear.grid(row=10, column=0, sticky="w", pady=(2, 8))
        automatic = ttk.Checkbutton(form, text=self.text("Connect automatically after launching"), variable=self.automatic)
        automatic.grid(row=11, column=0, sticky="w")
        self.widgets.extend((clear, automatic))
        ttk.Label(form, text=self.text("DeathLink currently requires native Triforce or Hookshot setup."),
                  wraplength=740).grid(row=12, column=0, sticky="ew", pady=(12, 0))
        self.chat_pane = ttk.Frame(notebook, padding=12)
        self.chat_pane.columnconfigure(0, weight=1)
        self.chat_pane.rowconfigure(0, weight=1)
        notebook.add(self.chat_pane, text=self.text("Archipelago chat"))
        self.history = tk.Text(self.chat_pane, wrap="word", state="disabled")
        self.history.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.message = tk.StringVar()
        self.chat_entry = ttk.Entry(self.chat_pane, textvariable=self.message)
        self.chat_entry.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        self.chat_entry.bind("<Return>", lambda _event: self.say())
        self.send_button = ttk.Button(self.chat_pane, text=self.text("Send"), command=self.say)
        self.send_button.grid(row=1, column=1, padx=(10, 0), pady=(12, 0))
        actions = ttk.Frame(master, padding=(16, 12))
        actions.grid(row=2, column=0, sticky="ew")
        self.prepare_button = ttk.Button(actions, text=self.text("Install and prepare"), command=self.prepare)
        self.prepare_button.grid(row=0, column=0)
        self.play_button = ttk.Button(actions, text=self.text("Play"), command=self.play)
        self.play_button.grid(row=0, column=1, padx=10)
        self.connect_button = ttk.Button(actions, text=self.text("Connect"), command=self.connect)
        self.connect_button.grid(row=0, column=2)
        self.disconnect_button = ttk.Button(actions, text=self.text("Disconnect"), command=self.disconnect)
        self.disconnect_button.grid(row=0, column=3, padx=10)
        self.tracker_button = ttk.Button(actions, text=self.text("Archipelago tracker"), command=self.open_tracker)
        self.tracker_button.grid(row=0, column=4)
        self.status = ttk.Label(master, wraplength=800, padding=(16, 0, 16, 12))
        self.status.grid(row=3, column=0, sticky="ew")
        self.progress = ttk.Progressbar(master, maximum=100)
        self.progress.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 16))
        self.progress.grid_remove()
        self.worker = threading.Thread(target=self.work, name="External Archipelago setup", daemon=True)
        self.worker.start()
        master.protocol("WM_DELETE_WINDOW", self.close)
        master.bind("<Escape>", lambda _event: self.close())
        self.schedule(40, self.receive)
        self.schedule(500, self.tick)
        if profile:
            self.start("open", lambda: self.service.open_profile(profile), "Reading the prepared external room…")
        else:
            self.refresh_profiles()
        self.render()

    def text(self, message, **values):
        return tr(message, language=self.language, **values)

    def schedule(self, delay, callback):
        def run():
            self.after_ids.discard(identifier)
            if not self.closed:
                callback()
        identifier = self.master.after(delay, run)
        self.after_ids.add(identifier)

    def work(self):
        while not self.stop.is_set():
            try:
                kind, operation = self.jobs.get(timeout=.2)
            except queue.Empty:
                continue
            try:
                result = operation()
            except Exception as error:
                result = {"_failed": True, "message": getattr(error, "public_message", "")}
            self.results.put((kind, result))
            del kind, operation, result

    def start(self, kind, operation, message):
        if self.busy or self.closed:
            return
        self.busy = True
        self.status.configure(text=self.text(message))
        self.progress.configure(value=0)
        self.jobs.put((kind, operation))
        self.render()

    def receive(self):
        while True:
            try:
                kind, result = self.results.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                self.progress.configure(value=result[0])
                self.status.configure(text=self.text(result[1]))
                continue
            self.busy = False
            if isinstance(result, dict) and result.get("_failed"):
                self.status.configure(text=result.get("message") or self.text("The external operation could not be completed. Check the selected files and connection."))
            elif kind == "profiles":
                self.profiles = result
                self.profile_choice.configure(values=(self.text("New external room"), *(
                    row.get("display_name") or row["slot"] + " · " + row["room"] for row in self.profiles)))
                self.profile_choice.current(0)
                self.status.configure(text=self.text("Choose a full-network player file and your game installation."))
            elif kind in {"open", "prepare"}:
                self.populate(result)
                self.status.configure(text=self.text("The external room is ready. Launch the game, then connect."))
            elif kind == "connect":
                self.runtime = result
                self.status.configure(text=self.text("Connecting…"))
            elif kind == "disconnect":
                self.runtime = None
                self.status.configure(text=self.text("Disconnected"))
            elif kind == "launch":
                self.status.configure(text=self.text("Port or emulator launched."))
                if self.automatic.get():
                    self.connect()
            elif kind == "say":
                if self.message.get() == result.get("sent_text"):
                    self.message.set("")
            if self.close_requested and not self.busy:
                self.close()
                return
            self.render()
        self.schedule(40, self.receive)

    def populate(self, result):
        self.current = dict(result)
        for name in self.fields:
            if name == "password":
                self.fields[name].set("")
            elif name == "player_file":
                self.fields[name].set(str(Path(result["profile"]) / "player.apootrr"))
            else:
                self.fields[name].set(result.get(name) or "")
        self.automatic.set(result.get("auto_connect", True))
        self.clear_password.set(False)

    def render(self):
        for widget in self.widgets:
            widget.configure(state="disabled" if self.busy else "readonly" if widget == self.profile_choice else "normal")
        if self.runtime:
            for widget in self.installation_widgets:
                widget.configure(state="disabled")
        ready = bool(self.current.get("ready"))
        self.prepare_button.configure(state="disabled" if self.busy or self.runtime else "normal")
        for button in (self.play_button, self.connect_button):
            button.configure(state="normal" if ready and not self.busy else "disabled")
        self.disconnect_button.configure(state="normal" if self.runtime and not self.busy else "disabled")
        self.tracker_button.configure(state="normal" if self.runtime and not self.busy else "disabled")
        connected = bool(self.runtime and self.runtime.summary().get("connected"))
        self.send_button.configure(state="normal" if connected and not self.busy else "disabled")
        if self.busy:
            self.progress.grid()
        else:
            self.progress.grid_remove()

    def browse(self, name, file=False):
        if self.busy:
            return
        if name in {"mods", "source"} and not file:
            path = self.dialogs.askdirectory(parent=self.master, title=self.text(FIELD_TEXT[name]), mustexist=True)
        else:
            filters = {"player_file": ((self.text("Archipelago player file"), "*.apootrr"),),
                       "source": (("NUP", "*.nup"),), "save_path": (("progress.sav", "*.sav"),)}
            path = self.dialogs.askopenfilename(parent=self.master, title=self.text(FIELD_TEXT[name]),
                filetypes=filters.get(name, ((self.text("All files"), "*.*"),)))
        if path:
            self.fields[name].set(path)

    def refresh_profiles(self):
        if not self.busy and not self.runtime:
            def read():
                from .room_library import RoomLibrary
                rows = self.service.list_profiles(self.base)
                names = {row["profile"]: row["name"] for row in RoomLibrary(self.base).rooms()}
                return [dict(row, display_name=names.get(row["profile"], "")) for row in rows]
            self.start("profiles", read, "Finding prepared external rooms…")

    def choose_profile(self, _event=None):
        if self.busy or self.runtime:
            return
        index = self.profile_choice.current() - 1
        if 0 <= index < len(self.profiles):
            self.start("open", lambda: self.service.open_profile(self.profiles[index]["profile"]), "Reading the prepared external room…")
        else:
            self.current = {}
            for name, variable in self.fields.items():
                variable.set("" if name != "server" else "archipelago.gg:38281")
            self.render()

    def open_profile(self, profile):
        if self.busy:
            return
        previous, self.runtime = self.runtime, None
        def operation():
            if previous:
                previous.stop()
            return self.service.open_profile(profile)
        self.start("open", operation, "Reading the prepared external room…")

    def prepare(self):
        if self.busy or self.runtime:
            return
        request = {name: variable.get().strip() if name != "password" else variable.get() for name, variable in self.fields.items()}
        request.update(base=self.base, auto_connect=self.automatic.get(), clear_password=self.clear_password.get())
        self.fields["password"].set("")
        def progress(percent, message):
            self.results.put(("progress", (percent, message)))
        def operation():
            result = self.service.configure(request, progress=progress)
            try:
                from .room_library import RoomLibrary
                RoomLibrary(self.base).register(result)
            except (OSError, ValueError):
                pass
            return result
        self.start("prepare", operation, "Preparing the external Archipelago room…")

    def connect(self):
        if self.busy or not self.current.get("profile"):
            return
        selected = self.current["profile"]
        password = self.fields["password"].get() or None
        preferences = dict(save_path=self.fields["save_path"].get().strip(), server=self.fields["server"].get().strip(),
                           password=password, clear_password=self.clear_password.get(), auto_connect=self.automatic.get())
        self.fields["password"].set("")
        previous = self.runtime
        self.runtime = None
        if self.tracker_window and not self.tracker_window.closed:
            self.tracker_window.close()
        def operation():
            if previous:
                previous.stop()
            self.service.update_preferences(selected, **preferences)
            runtime = self.service.connect(selected, password=password)
            try:
                runtime.start()
            except BaseException:
                runtime.stop()
                raise
            return runtime
        self.start("connect", operation, "Connecting…")

    def disconnect(self):
        if self.busy or not self.runtime:
            return
        runtime, self.runtime = self.runtime, None
        if self.tracker_window and not self.tracker_window.closed:
            self.tracker_window.close()
        self.start("disconnect", lambda: (runtime.stop(), {})[1], "Disconnecting…")

    def play(self):
        if self.current.get("profile") and not self.busy:
            selected = self.current["profile"]
            self.start("launch", lambda: (self.service.launch(selected), {})[1], "Launching the selected port or emulator…")

    def say(self):
        if self.busy or not self.runtime or not self.message.get().strip():
            return
        runtime, message = self.runtime, self.message.get()
        self.start("say", lambda: (runtime.say(message), {"sent_text": message})[1], "Sending chat message…")

    def tick(self):
        if self.runtime:
            snapshot = self.runtime.summary()
            if not self.busy:
                self.status.configure(text=self.text(snapshot.get("status", "")) + " · " +
                    self.text("{checked}/{total} checks · {received} items received", checked=snapshot.get("checks", 0),
                              total=snapshot.get("total", 0), received=snapshot.get("received", 0)))
            client = self.runtime.client
            if client.log_count != self.log_count:
                try:
                    rows = list(client.log)
                except RuntimeError:
                    rows = None
                if rows is not None:
                    self.history.configure(state="normal")
                    self.history.delete("1.0", "end")
                    self.history.insert("end", "\n".join(rows) + "\n")
                    self.history.configure(state="disabled")
                    self.history.see("end")
                    self.log_count = client.log_count
            self.render()
        self.schedule(750, self.tick)

    def open_tracker(self):
        if self.busy or not self.runtime:
            return
        if self.tracker_window and not self.tracker_window.closed:
            self.tracker_window.master.lift()
            return
        from .room_windows import ProgressWindow
        from .tracker_service import RuntimeTracker
        runtime = self.runtime
        self.tracker_window = ProgressWindow(tk.Toplevel(self.master), self.current["profile"],
            language=self.language, provider_factory=lambda _profile, _artifact: RuntimeTracker(runtime), save_selection=False)

    def close(self):
        if self.closed:
            return
        if self.busy:
            self.close_requested = True
            self.status.configure(text=self.text("Finishing the current operation before closing…"))
            return
        if self.runtime:
            self.close_requested = True
            self.disconnect()
            return
        self.closed = True
        self.stop.set()
        self.worker.join(timeout=.3)
        self.fields["password"].set("")
        self.message.set("")
        if self.tracker_window and not self.tracker_window.closed:
            self.tracker_window.close()
        for identifier in self.after_ids:
            self.master.after_cancel(identifier)
        self.after_ids.clear()
        self.master.destroy()
