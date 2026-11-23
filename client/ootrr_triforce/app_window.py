"""The single desktop entry point for preparing and playing an AP room.

Filesystem, network and build work stays on one worker. The window only sends
explicit requests; it never invokes the console client or simulates game input.
"""
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import queue
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

from .i18n import detect_language, normalize_language, set_language, tr


TEXT = {
    "title": "OOT Remake — Archipelago",
    "subtitle": "Play Ocarina of Time Remake with Archipelago.",
    "intro": "Select your player file, enter the room address, install, and play.",
    "home": "Home",
    "play": "Play",
    "setup": "Set up a room",
    "yaml": "Create YAML",
    "connection": "Connection",
    "host": "Game host",
    "triforce": "Triforce",
    "hookshot": "Hookshot (experimental)",
    "triforce_note": "Use Zelda's Archipelago menu or this app's Connection window. Each host keeps separate saves.",
    "hookshot_note": "Experimental integration: setup verifies the compatible Hookshot build. Hookshot uses separate saves from Triforce.",
    "checking_game": "Checking game files and build tools…",
    "game_ready": "Game files and build tools are ready.",
    "game_invalid": "Choose the selected host's game folder and build tools before installing.",
    "compatibility": "Host compatibility",
    "show_password": "Show password",
    "help": "Help",
    "guide": "Getting started",
    "open_log": "Open log",
    "open_data": "Open app data folder",
    "licenses": "Licenses and source",
    "exporting_licenses": "Preparing licenses and source information…",
    "about": "About",
    "back": "Back",
    "ready": "Ready to play.",
    "not_prepared": "No room prepared yet.",
    "update_title": "Room update required.",
    "prepare_first": "Prepare a room to enable Play.",
    "update_needed": "This room needs an update. Choose Set up a room to prepare it.",
    "finding": "Finding your game and prepared room…",
    "player_room": "{slot} · Room {room}",
    "setup_intro": "Choose the player file generated for you by Archipelago. Your existing saves are kept.",
    "player_file": "Archipelago player file",
    "game_folder": "Game installation folder",
    "romfs": "Game files (romfs)",
    "tools": "Host build tools",
    "browse": "Browse…",
    "folders": "Change detected folders…",
    "server": "Room address",
    "password": "Password (if required)",
    "automatic": "Connect automatically when the game starts",
    "choose_player": "Select your .apootrr player file to see the room and player.",
    "reading_player": "Reading the player file…",
    "invalid_player": "Unable to read this player file. Select the .apootrr file generated for you.",
    "install": "Install and prepare",
    "cancel": "Cancel",
    "preparing": "Preparing your room…",
    "cancelling": "Cancelling safely…",
    "cancelled": "Setup cancelled.",
    "setup_failed": "Setup could not be completed. Check the game folder and server, then try again.",
    "launch_failed": "The game could not be launched. Check the selected host's folder in Set up a room.",
    "launched": "Game launched.",
    "build_needed": "Preparation is complete, but the selected host still needs to build the game.",
    "yaml_intro": "Create a configuration with all supported settings, then generate a room with the other players' YAML files in Archipelago.",
    "player_name": "Player name",
    "save_yaml": "Save YAML…",
    "yaml_name_error": "Choose a name of 1 to 16 characters other than Archipelago.",
    "yaml_saved": "YAML saved. Edit its settings before generating your room.",
    "saving_yaml": "Saving YAML…",
    "yaml_failed": "The YAML could not be saved. Choose a writable folder and try again.",
    "install_world": "Install APWorld…",
    "world_intro": "On the computer generating the room, install the APWorld into Archipelago once.",
    "world_folder": "Choose your Archipelago installation folder",
    "installing_world": "Installing the APWorld…",
    "world_installed": "APWorld installed. Restart Archipelago before generating the room.",
    "world_failed": "The APWorld could not be installed. Choose your Archipelago installation folder and try again.",
    "yaml_file": "YAML configuration",
    "all_files": "All files",
    "choose_game": "Choose the folder containing your installed game",
    "choose_romfs": "Choose the game's romfs folder",
    "choose_tools": "Choose the selected host's build tools folder",
    "path_failed": "This location could not be opened.",
    "about_body": "Ocarina of Time Remake integration for Archipelago.\nYour own game files and a compatible Windows host are required.",
}


def yaml_content(name):
    """Build the same supported, English YAML as the command-line exporter."""
    from .catalog import GAME
    from .settings import yaml_options
    name = name.strip()
    if not name or len(name) > 16 or name == "Archipelago" or any(ord(char) < 32 for char in name):
        raise ValueError("invalid_player_name")
    return ("# Supported OOT Remake Archipelago settings.\n"
            "# Edit the values below before generating the room.\n"
            f"name: {json.dumps(name, ensure_ascii=False)}\n"
            f"game: {json.dumps(GAME)}\n{json.dumps(GAME)}:\n" + yaml_options() +
            "\n  # Share deaths with other DeathLink players.\n  death_link: false\n")


@dataclass
class _Task:
    kind: str
    operation: object
    identity: object = None


class AppWindow:
    def __init__(self, master, *, service=None, base=None, dialogs=filedialog,
                 connection_factory=None, open_path=None):
        if service is None:
            from . import install_service as service
        self.master, self.service, self.base = master, service, base
        self.dialogs, self.connection_factory = dialogs, connection_factory
        self.path_opener = open_path
        self.language = "en"
        self.current = {}
        self.target_mods = ""
        self.page = "home"
        self.busy = self.closed = self.close_requested = False
        self.cancel_event = threading.Event()
        self.jobs, self.results = queue.Queue(), queue.Queue()
        self.stop = threading.Event()
        self.after_ids = set()
        self.inspect_after = None
        self.game_after = None
        self.game_revision = 0
        self.installation_info = None
        self.installation_message = "checking_game"
        self.installation_detail = ""
        self.host = "nx2navi"
        self.manifest_revision = 0
        self.manifest_info = None
        self.manifest_message = "choose_player"
        self.dirty = set()
        self.updating = False
        self.status_key, self.status_values = "finding", {}
        self.progress_text = ""
        self.connection_window = None
        self.about_window = None
        self.translated_widgets = []
        self.menu_language = None
        self.form_widgets = []
        self.fields = {name: tk.StringVar() for name in ("manifest", "game", "romfs", "tools", "server", "password")}
        self.automatic = tk.BooleanVar(value=True)
        self.extra_folders = tk.BooleanVar(value=False)
        self.show_password = tk.BooleanVar(value=False)
        self.player_name = tk.StringVar(value="Link")
        self._build()
        for name, variable in self.fields.items():
            variable.trace_add("write", lambda *_args, name=name: self._edited(name))
        self.automatic.trace_add("write", lambda *_args: self._edited("auto_connect"))
        self.worker = threading.Thread(target=self._work, name="Archipelago setup", daemon=True)
        self.worker.start()
        self.master.protocol("WM_DELETE_WINDOW", self.close)
        self.master.bind("<MouseWheel>", self._wheel, add="+")
        self._submit("discover", lambda: self.service.discover(base=self.base))
        self._schedule(40, self._receive)
        self._render()

    def _text(self, key, **values):
        return tr(TEXT[key], language=self.language, **values)

    def _label(self, parent, key, **options):
        widget = ttk.Label(parent, **options)
        self.translated_widgets.append((widget, key))
        return widget

    def _button(self, parent, key, command, **options):
        widget = ttk.Button(parent, command=command, **options)
        self.translated_widgets.append((widget, key))
        return widget

    def _build(self):
        height = min(840, max(580, self.master.winfo_screenheight() - 100))
        self.master.geometry(f"780x{height}")
        self.master.minsize(680, 580)
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(1, weight=1)
        style = ttk.Style(self.master)
        style.configure("App.Title.TLabel", font=("Segoe UI", 21, "bold"))
        style.configure("App.Heading.TLabel", font=("Segoe UI", 15, "bold"))
        style.configure("App.Primary.TButton", font=("Segoe UI", 11, "bold"), padding=(20, 12))
        style.configure("App.Action.TButton", padding=(14, 8))
        header = ttk.Frame(self.master, padding=(26, 18, 26, 14))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        self._label(header, "title", style="App.Title.TLabel").grid(row=0, column=0, sticky="w")
        self._label(header, "subtitle").grid(row=1, column=0, sticky="w", pady=(5, 0))
        self.help_button = ttk.Menubutton(header)
        self.help_button.grid(row=0, column=1, rowspan=2, sticky="ne", padx=(12, 0))
        self.help_menu = tk.Menu(self.help_button, tearoff=False)
        self.help_button.configure(menu=self.help_menu)
        self.pages = ttk.Frame(self.master, padding=(26, 0, 26, 0))
        self.pages.grid(row=1, column=0, sticky="nsew")
        self.pages.rowconfigure(0, weight=1)
        self.pages.columnconfigure(0, weight=1)
        self.page_frames = {name: ttk.Frame(self.pages) for name in ("home", "setup", "yaml")}
        for frame in self.page_frames.values():
            frame.grid(row=0, column=0, sticky="nsew")
        self._build_home(self.page_frames["home"])
        self._build_setup(self.page_frames["setup"])
        self._build_yaml(self.page_frames["yaml"])
        footer = ttk.Frame(self.master, padding=(26, 12, 26, 18))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.status = ttk.Label(footer, wraplength=690)
        self.status.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.progress = ttk.Progressbar(footer, maximum=100)
        self.progress.grid(row=1, column=0, sticky="ew")
        self.progress.grid_remove()

    def _build_home(self, pane):
        pane.columnconfigure(0, weight=1)
        pane.columnconfigure(1, weight=1)
        pane.rowconfigure(0, weight=1)
        pane.rowconfigure(5, weight=1)
        self._label(pane, "intro", wraplength=680).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 18))
        summary = ttk.LabelFrame(pane, padding=22)
        summary.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 18))
        summary.columnconfigure(0, weight=1)
        self.home_status = ttk.Label(summary, style="App.Heading.TLabel")
        self.home_status.grid(row=0, column=0, sticky="w")
        self.home_room = ttk.Label(summary, wraplength=640)
        self.home_room.grid(row=1, column=0, sticky="w", pady=(9, 18))
        self.play_button = self._button(summary, "play", self.play, style="App.Primary.TButton")
        self.play_button.grid(row=2, column=0, sticky="ew")
        self.setup_button = self._button(pane, "setup", lambda: self.show_page("setup"), style="App.Action.TButton")
        self.setup_button.grid(row=3, column=0, sticky="ew", padx=(0, 7))
        self.yaml_button = self._button(pane, "yaml", lambda: self.show_page("yaml"), style="App.Action.TButton")
        self.yaml_button.grid(row=3, column=1, sticky="ew", padx=(7, 0))
        self.connection_button = self._button(pane, "connection", self.open_connection)
        self.connection_button.grid(row=4, column=0, columnspan=2, sticky="w", pady=(16, 0))

    def _page_title(self, pane, key):
        pane.columnconfigure(0, weight=1)
        nav = ttk.Frame(pane)
        nav.grid(row=0, column=0, sticky="ew", pady=(4, 15))
        nav.columnconfigure(1, weight=1)
        back = self._button(nav, "back", lambda: self.show_page("home"))
        back.grid(row=0, column=0, padx=(0, 16))
        self.form_widgets.append(back)
        self._label(nav, key, style="App.Heading.TLabel").grid(row=0, column=1, sticky="w")

    def _build_setup(self, pane):
        self._page_title(pane, "setup")
        pane.rowconfigure(1, weight=1)
        scroll = ttk.Frame(pane)
        scroll.grid(row=1, column=0, sticky="nsew")
        scroll.columnconfigure(0, weight=1)
        scroll.rowconfigure(0, weight=1)
        self.setup_canvas = tk.Canvas(scroll, highlightthickness=0, borderwidth=0)
        self.setup_canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(scroll, orient="vertical", command=self.setup_canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.setup_canvas.configure(yscrollcommand=scrollbar.set)
        form = ttk.Frame(self.setup_canvas, padding=(0, 0, 14, 8))
        form.columnconfigure(0, weight=1)
        window = self.setup_canvas.create_window((0, 0), window=form, anchor="nw")
        form.bind("<Configure>", lambda _event: self.setup_canvas.configure(scrollregion=self.setup_canvas.bbox("all")))
        self.setup_canvas.bind("<Configure>", lambda event: self.setup_canvas.itemconfigure(window, width=event.width))
        self._label(form, "setup_intro", wraplength=640).grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self._path_field(form, 1, "manifest", "player_file", self.browse_manifest)
        self.manifest_label = ttk.Label(form, wraplength=640)
        self.manifest_label.grid(row=2, column=0, sticky="ew", pady=(6, 14))
        host_row = ttk.Frame(form)
        host_row.columnconfigure(0, weight=1)
        host_row.grid(row=3, column=0, sticky="ew", pady=(0, 14))
        self._label(host_row, "host").grid(row=0, column=0, sticky="w", pady=(0, 5))
        self.host_choice = ttk.Combobox(host_row, state="readonly", width=32)
        self.host_choice.grid(row=1, column=0, sticky="ew")
        self.host_choice.bind("<<ComboboxSelected>>", self._choose_host)
        self.host_note = ttk.Label(host_row, wraplength=640)
        self.host_note.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self._path_field(form, 4, "game", "game_folder", lambda: self.browse_folder("game", "choose_game"))
        folders = ttk.Checkbutton(form, variable=self.extra_folders, command=self._render_folders)
        self.translated_widgets.append((folders, "folders"))
        self.form_widgets.append(folders)
        folders.grid(row=6, column=0, sticky="w", pady=(10, 0))
        self.folder_details = ttk.Frame(form)
        self.folder_details.columnconfigure(0, weight=1)
        self.folder_details.grid(row=7, column=0, sticky="ew", pady=(10, 0))
        self._path_field(self.folder_details, 0, "romfs", "romfs", lambda: self.browse_folder("romfs", "choose_romfs"))
        self._path_field(self.folder_details, 1, "tools", "tools", lambda: self.browse_folder("tools", "choose_tools"))
        self.folder_details.grid_remove()
        self.installation_label = ttk.Label(form, wraplength=640)
        self.installation_label.grid(row=5, column=0, sticky="ew", pady=(4, 0))
        for row, (name, key) in enumerate((("server", "server"), ("password", "password")), 8):
            frame = ttk.Frame(form)
            frame.columnconfigure(0, weight=1)
            frame.grid(row=row, column=0, sticky="ew", pady=(15, 0))
            self._label(frame, key).grid(row=0, column=0, sticky="w", pady=(0, 5))
            entry = ttk.Entry(frame, textvariable=self.fields[name], show="•" if name == "password" else "")
            entry.grid(row=1, column=0, sticky="ew")
            if name == "password":
                self.password_entry = entry
            self.form_widgets.append(entry)
        reveal = ttk.Checkbutton(form, variable=self.show_password, command=self._reveal_password)
        self.translated_widgets.append((reveal, "show_password"))
        self.form_widgets.append(reveal)
        reveal.grid(row=10, column=0, sticky="w", pady=(6, 0))
        auto = ttk.Checkbutton(form, variable=self.automatic)
        self.translated_widgets.append((auto, "automatic"))
        self.form_widgets.append(auto)
        auto.grid(row=11, column=0, sticky="w", pady=(15, 0))
        actions = ttk.Frame(pane)
        actions.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        actions.columnconfigure(0, weight=1)
        self.cancel_button = self._button(actions, "cancel", self.cancel)
        self.cancel_button.grid(row=0, column=0, sticky="w")
        self.install_button = self._button(actions, "install", self.install, style="App.Action.TButton")
        self.install_button.grid(row=0, column=1, sticky="e")

    def _path_field(self, parent, row, name, key, browse):
        field = ttk.Frame(parent)
        field.grid(row=row, column=0, sticky="ew", pady=(0, 5))
        field.columnconfigure(0, weight=1)
        self._label(field, key).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 5))
        entry = ttk.Entry(field, textvariable=self.fields[name])
        entry.grid(row=1, column=0, sticky="ew")
        button = self._button(field, "browse", browse)
        button.grid(row=1, column=1, padx=(9, 0))
        self.form_widgets.extend((entry, button))

    def _build_yaml(self, pane):
        self._page_title(pane, "yaml")
        self._label(pane, "yaml_intro", wraplength=680).grid(row=1, column=0, sticky="ew", pady=(0, 22))
        self._label(pane, "player_name").grid(row=2, column=0, sticky="w", pady=(0, 6))
        self.name_entry = ttk.Entry(pane, textvariable=self.player_name)
        self.name_entry.grid(row=3, column=0, sticky="ew")
        self.form_widgets.append(self.name_entry)
        self.save_yaml_button = self._button(pane, "save_yaml", self.save_yaml, style="App.Action.TButton")
        self.save_yaml_button.grid(row=4, column=0, sticky="w", pady=(16, 24))
        ttk.Separator(pane).grid(row=5, column=0, sticky="ew", pady=(0, 18))
        self._label(pane, "world_intro", wraplength=680).grid(row=6, column=0, sticky="ew", pady=(0, 14))
        self.world_button = self._button(pane, "install_world", self.install_world)
        self.world_button.grid(row=7, column=0, sticky="w")
        pane.rowconfigure(8, weight=1)

    def _wheel(self, event):
        if self.page != "setup" or event.widget.winfo_toplevel() != self.master:
            return
        x, y = self.master.winfo_pointerxy()
        canvas = self.setup_canvas
        if (canvas.winfo_rootx() <= x < canvas.winfo_rootx() + canvas.winfo_width()
                and canvas.winfo_rooty() <= y < canvas.winfo_rooty() + canvas.winfo_height()):
            canvas.yview_scroll(-int(event.delta / 120), "units")

    def _schedule(self, delay, callback):
        def run():
            self.after_ids.discard(identifier)
            if not self.closed:
                callback()
        identifier = self.master.after(delay, run)
        self.after_ids.add(identifier)
        return identifier

    def _edited(self, name):
        if self.updating:
            return
        self.dirty.add(name)
        if name == "game":
            value = self.fields["game"].get().strip()
            folder = Path(value).expanduser() if value else None
            if folder is not None and folder.name.casefold() in {"triforce.exe", "hookshot.exe"}:
                folder = folder.parent.parent if folder.parent.name.casefold() == "bin" else folder.parent
            self._set_field("romfs", folder / "romfs" if folder is not None else "")
            self.target_mods = str(folder / "mods") if folder is not None else ""
            # A delayed discovery must not overwrite folders selected by the
            # user. Triforce's shared build tools remain independently chosen.
            self.dirty.add("romfs")
        if name in {"game", "romfs", "tools"}:
            self._queue_installation_check()
        if name == "manifest":
            self.manifest_revision += 1
            self.manifest_info = None
            self.manifest_message = "choose_player"
            if self.inspect_after:
                self.master.after_cancel(self.inspect_after)
                self.after_ids.discard(self.inspect_after)
            if self.fields["manifest"].get().strip():
                self.manifest_message = "reading_player"
                self.inspect_after = self._schedule(250, self._inspect_manifest)
        self._render()

    def _set_field(self, name, value):
        self.updating = True
        try:
            self.fields[name].set(str(value or ""))
        finally:
            self.updating = False

    def _inspect_manifest(self):
        self.inspect_after = None
        path = self.fields["manifest"].get().strip()
        identity = (self.manifest_revision, path)
        self._submit("manifest", lambda: self.service.inspect_manifest(path), identity)

    def _choose_host(self, _event=None):
        if self.busy:
            return
        selected = "hookshot" if self.host_choice.current() == 1 else "nx2navi"
        if selected == self.host:
            return
        self.host = selected
        self.current = {}
        if self.connection_window and not self.connection_window.closed:
            self.connection_window.close()
        self.dirty.add("host")
        self.dirty.difference_update({"game", "romfs", "tools"})
        self.game_revision += 1
        self.installation_info = None
        self.installation_message, self.installation_detail = "checking_game", ""
        self._submit("discover", lambda: self.service.discover(base=self.base, host=selected), selected)
        self._render()

    def _queue_installation_check(self):
        self.game_revision += 1
        self.installation_info = None
        self.installation_message, self.installation_detail = "checking_game", ""
        if self.game_after:
            self.master.after_cancel(self.game_after)
            self.after_ids.discard(self.game_after)
        self.game_after = self._schedule(200, self._inspect_installation)

    def _inspect_installation(self):
        self.game_after = None
        request = {name: self.fields[name].get().strip() for name in ("game", "romfs", "tools")}
        request["host"] = self.host
        identity = self.game_revision
        inspect = getattr(self.service, "inspect_installation", None)
        if inspect is None:
            self.installation_info = {"valid": True}
            self.installation_message = "game_ready"
            self._render()
            return
        self._submit("installation", lambda: inspect(request), identity)

    def _reveal_password(self):
        self.password_entry.configure(show="" if self.show_password.get() else "•")

    def _submit(self, kind, operation, identity=None):
        self.jobs.put_nowait(_Task(kind, operation, identity))

    def _work(self):
        while not self.stop.is_set():
            try:
                task = self.jobs.get(timeout=.2)
            except queue.Empty:
                continue
            try:
                result = task.operation()
            except Exception as error:
                logging.getLogger(__name__).warning("Application operation %s failed (%s).", task.kind, type(error).__name__)
                result = {"_failed": True, "_cancelled": bool(getattr(error, "cancelled", False)),
                          "_message": getattr(error, "public_message", "")}
            self.results.put((task, result))
            del task, result

    def _receive(self):
        while True:
            try:
                task, result = self.results.get_nowait()
            except queue.Empty:
                break
            if task.kind == "progress":
                percent, message = result
                self.progress.configure(value=max(0, min(100, percent)))
                self.progress_text = str(message)
            elif task.kind == "discover":
                if task.identity is not None and task.identity != self.host:
                    continue
                if (task.identity is None and "host" in self.dirty
                        and result.get("host", "nx2navi") != self.host):
                    continue
                if not result.get("_failed"):
                    self.current = dict(result)
                    if "host" not in self.dirty:
                        self.host = result.get("host", "nx2navi")
                    self.language = normalize_language(result.get("language"))
                    set_language(self.language)
                    for name in ("manifest", "game", "romfs", "tools", "server"):
                        if name not in self.dirty:
                            self._set_field(name, result.get(name, ""))
                    if "auto_connect" not in self.dirty:
                        self.updating = True
                        try:
                            self.automatic.set(bool(result.get("auto_connect", True)))
                        finally:
                            self.updating = False
                    if "game" not in self.dirty:
                        self.target_mods = str(result.get("mods") or Path(self.fields["game"].get()) / "mods")
                    if self.fields["manifest"].get():
                        self._inspect_manifest()
                    self._queue_installation_check()
                    self.status_key = "ready" if result.get("ready") else "prepare_first"
                else:
                    self.status_key = "prepare_first"
                    self.installation_info = None
                    self.installation_message = "game_invalid"
                    self.installation_detail = result.get("_message", "")
            elif task.kind == "installation":
                if task.identity != self.game_revision:
                    continue
                self.installation_info = None if result.get("_failed") else result
                self.installation_message = "game_invalid" if result.get("_failed") else "game_ready"
                self.installation_detail = result.get("_message", "")
                if result.get("tools") and not self.fields["tools"].get().strip():
                    self._set_field("tools", result["tools"])
                if result.get("_failed"):
                    self.extra_folders.set(True)
                    self._render_folders()
            elif task.kind == "manifest":
                if task.identity == (self.manifest_revision, self.fields["manifest"].get().strip()):
                    self.manifest_info = None if result.get("_failed") else result
                    self.manifest_message = "invalid_player" if result.get("_failed") else "player_room"
            else:
                self.busy = False
                self.progress_text = ""
                if result.get("_failed"):
                    self.status_key = "cancelled" if result.get("_cancelled") else {
                        "install": "setup_failed", "launch": "launch_failed", "yaml": "yaml_failed",
                        "world": "world_failed", "licenses": "path_failed"
                    }[task.kind]
                    self.progress_text = result.get("_message", "")
                elif task.kind == "install":
                    old_profile = self.current.get("profile")
                    self.current.update(result)
                    if (old_profile != self.current.get("profile") and self.connection_window
                            and not self.connection_window.closed):
                        self.connection_window.close()
                    self.current["manifest"] = self.fields["manifest"].get().strip()
                    self.status_key = "ready" if result.get("ready") else "build_needed"
                    self.page = "home"
                elif task.kind == "licenses":
                    self.status_key = "ready" if self.current.get("ready") else "prepare_first"
                    if not self.close_requested:
                        self._open_path(result["path"])
                else:
                    self.status_key = {"launch": "launched", "yaml": "yaml_saved", "world": "world_installed"}[task.kind]
                if self.close_requested:
                    self.close()
                    return
            self._render()
        self._schedule(40, self._receive)

    def show_page(self, name):
        if not self.busy:
            self.page = name
            self._render()

    def _render_folders(self):
        if self.extra_folders.get():
            self.folder_details.grid()
        else:
            self.folder_details.grid_remove()

    def _render(self):
        self.master.title(self._text("title"))
        for widget, key in self.translated_widgets:
            widget.configure(text=self._text(key))
        self.help_button.configure(text=self._text("help"))
        if self.menu_language != self.language:
            self.help_menu.delete(0, "end")
            for key, command in (("guide", self.open_guide), ("open_log", self.open_log),
                                 ("compatibility", self.open_compatibility),
                                 ("open_data", self.open_data), ("licenses", self.open_licenses),
                                 ("about", self.about)):
                self.help_menu.add_command(label=self._text(key), command=command)
            self.menu_language = self.language
        self.page_frames[self.page].tkraise()
        self.host_choice.configure(values=(self._text("triforce"), self._text("hookshot")),
                                   state="disabled" if self.busy else "readonly")
        self.host_choice.current(1 if self.host == "hookshot" else 0)
        self.host_note.configure(text=self._text("hookshot_note" if self.host == "hookshot" else "triforce_note"))
        self.installation_label.configure(text=self.installation_detail or self._text(self.installation_message))
        ready = bool(self.current.get("ready"))
        self.home_status.configure(text=self._text("ready" if ready else "update_title" if self.current.get("profile") else "not_prepared"))
        if self.current.get("profile"):
            detail = (self._text("player_room", slot=self.current.get("slot", ""), room=self.current.get("room", ""))
                      if ready else self._text("update_needed"))
        else:
            detail = self._text("prepare_first")
        self.home_room.configure(text=detail)
        self.play_button.configure(state="normal" if ready and not self.busy else "disabled")
        self.connection_button.configure(state="normal" if self.current.get("profile") and not self.busy else "disabled")
        for widget in (self.setup_button, self.yaml_button, self.save_yaml_button, self.world_button, *self.form_widgets):
            widget.configure(state="disabled" if self.busy else "normal")
        can_install = bool(self.manifest_info and self.installation_info and self.installation_info.get("valid")
                           and self.fields["game"].get().strip() and self.fields["server"].get().strip())
        self.install_button.configure(state="normal" if can_install and not self.busy else "disabled")
        self.cancel_button.configure(state="normal" if self.busy and not self.cancel_event.is_set() else "disabled")
        self.manifest_label.configure(text=self._text("player_room", slot=self.manifest_info.get("slot", ""),
                                                     room=self.manifest_info.get("room", ""))
                                      if self.manifest_info else self._text(self.manifest_message))
        self.status.configure(text=self.progress_text or self._text(self.status_key, **self.status_values))
        if self.busy:
            self.progress.grid()
        else:
            self.progress.grid_remove()

    def browse_manifest(self):
        selected = self.dialogs.askopenfilename(parent=self.master, title=self._text("player_file"),
            filetypes=((self._text("player_file"), "*.apootrr"), (self._text("all_files"), "*.*")))
        if selected:
            self.fields["manifest"].set(selected)

    def browse_folder(self, name, title):
        selected = self.dialogs.askdirectory(parent=self.master, title=self._text(title),
                                             initialdir=self.fields[name].get() or None, mustexist=True)
        if selected:
            self.fields[name].set(selected)
            if name == "game":
                self.language = detect_language(config={"romfs": str(Path(selected) / "romfs")})
                set_language(self.language)
                self._render()

    def _start(self, kind, operation, key):
        if self.busy:
            return
        self.busy = True
        self.cancel_event.clear()
        self.status_key, self.progress_text = key, ""
        self.progress.configure(value=0)
        self._submit(kind, operation)
        self._render()

    def install(self):
        if self.busy or not self.manifest_info:
            return
        request = {key: value.get().strip() if key != "password" else value.get() for key, value in self.fields.items()}
        if not self.installation_info or not self.installation_info.get("valid"):
            return
        request.update(host=self.host, mods=self.target_mods, rebuild=True, auto_connect=self.automatic.get())
        if self.base is not None:
            request["base"] = self.base
        self._set_field("password", "")
        def progress(percent, message):
            self.results.put((_Task("progress", None), (percent, message)))
        self._start("install", lambda: self.service.install(request, progress=progress, cancel=self.cancel_event), "preparing")

    def cancel(self):
        if self.busy:
            self.cancel_event.set()
            self.status_key, self.progress_text = "cancelling", ""
            self._render()

    def play(self):
        if not self.busy and self.current.get("ready"):
            request = dict(self.current)
            self._start("launch", lambda: (self.service.launch(request), {})[1], "launched")

    def save_yaml(self):
        if self.busy:
            return
        try:
            content = yaml_content(self.player_name.get())
        except ValueError:
            self.status_key = "yaml_name_error"
            self._render()
            self.name_entry.focus_set()
            return
        safe_name = re.sub(r"[^\w -]", "_", self.player_name.get().strip())
        target = self.dialogs.asksaveasfilename(parent=self.master, title=self._text("save_yaml"),
            defaultextension=".yaml", initialfile=f"Player-{safe_name}.yaml",
            filetypes=((self._text("yaml_file"), "*.yaml"),))
        if target:
            def save():
                from .save_bridge import atomic
                atomic(Path(target), content.encode("utf-8"))
                return {}
            self._start("yaml", save, "saving_yaml")

    def install_world(self):
        if self.busy:
            return
        initial = Path(os.getenv("PROGRAMDATA", "C:/ProgramData")) / "Archipelago"
        target = self.dialogs.askdirectory(parent=self.master, title=self._text("world_folder"),
                                          initialdir=str(initial) if initial.is_dir() else None, mustexist=True)
        if target:
            def install():
                from .app_runtime import install_apworld
                install_apworld(Path(target))
                return {}
            self._start("world", install, "installing_world")

    def open_connection(self):
        if self.busy or not self.current.get("profile"):
            return
        if self.connection_window and not self.connection_window.closed:
            self.connection_window.master.lift()
            self.connection_window.master.focus_set()
            return
        factory = self.connection_factory
        if factory is None:
            from .connection_window import ConnectionWindow
            factory = ConnectionWindow
        child = tk.Toplevel(self.master)
        self.connection_window = factory(child, base=self.current.get("base") or self.base,
                                         explicit=Path(self.current["profile"]))

    def _open_path(self, path):
        try:
            if self.path_opener:
                self.path_opener(Path(path))
            elif os.name == "nt":
                os.startfile(str(path))
            else:
                webbrowser.open(Path(path).resolve().as_uri())
        except OSError:
            messagebox.showerror(self._text("title"), self._text("path_failed"), parent=self.master)

    def open_guide(self):
        webbrowser.open("https://github.com/RAjeux/OOT-Remake-Archipelago#play")

    def open_compatibility(self):
        webbrowser.open("https://github.com/RAjeux/OOT-Remake-Archipelago/blob/main/docs/PORT-COMPATIBILITY.md")

    def open_log(self):
        from .app_runtime import log_path
        application = log_path(base=self.base)
        setup = Path(self.current.get("diagnostic_log") or application)
        candidates = [path for path in (application, setup) if path.is_file()]
        self._open_path(max(candidates, key=lambda path: path.stat().st_mtime_ns) if candidates else application)

    def open_data(self):
        from .app_runtime import default_base
        self._open_path(Path(self.base or self.current.get("base") or default_base()))

    def open_licenses(self):
        def export():
            from .app_runtime import export_licenses
            return {"path": export_licenses(base=self.base)}
        self._start("licenses", export, "exporting_licenses")

    def about(self):
        if self.about_window and self.about_window.winfo_exists():
            self.about_window.lift()
            return
        version = ""
        try:
            from .app_runtime import resource_root
            version = (resource_root() / "VERSION").read_text(encoding="utf-8").strip()
        except (ImportError, OSError):
            pass
        dialog = self.about_window = tk.Toplevel(self.master)
        dialog.title(self._text("about"))
        dialog.transient(self.master)
        dialog.resizable(False, False)
        content = ttk.Frame(dialog, padding=22)
        content.grid(sticky="nsew")
        ttk.Label(content, text=self._text("title"), style="App.Heading.TLabel").grid(row=0, column=0, sticky="w")
        if version:
            ttk.Label(content, text=version).grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(content, text=self._text("about_body"), wraplength=460).grid(row=2, column=0, sticky="w", pady=(16, 16))
        url = "https://github.com/RAjeux/OOT-Remake-Archipelago"
        link = ttk.Label(content, text=url, foreground="#005ca9", cursor="hand2", takefocus=True)
        link.grid(row=3, column=0, sticky="w")
        link.bind("<Button-1>", lambda _event: webbrowser.open(url))
        link.bind("<Return>", lambda _event: webbrowser.open(url))
        dialog.bind("<Escape>", lambda _event: dialog.destroy())

    def close(self):
        if self.closed:
            return
        if self.busy:
            self.close_requested = True
            self.cancel()
            return
        self.closed = True
        self.stop.set()
        self._set_field("password", "")
        if self.connection_window and not self.connection_window.closed:
            self.connection_window.close()
        for identifier in self.after_ids:
            self.master.after_cancel(identifier)
        self.after_ids.clear()
        self.master.destroy()


def main():
    root = tk.Tk()
    AppWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
