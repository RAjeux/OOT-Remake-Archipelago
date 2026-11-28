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
from .ui_theme import COLORS, apply_theme, draw_brand, set_window_icon


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
    "resources_update_needed": "Prepare this room again to apply the fixes, using the same player file and save.",
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
    "yaml_intro": "Create a configuration or import an existing YAML, adjust its settings, then generate a room in Archipelago.",
    "player_name": "Player name",
    "yaml_settings": "Choose settings…",
    "save_yaml": "Save YAML…",
    "yaml_name_error": "Choose a name of 1 to 16 characters other than Archipelago.",
    "yaml_saved": "YAML saved. Generate your room in Archipelago.",
    "saving_yaml": "Saving YAML…",
    "yaml_failed": "The YAML could not be saved. Choose a writable folder and try again.",
    "import_yaml": "Import YAML…",
    "importing_yaml": "Reading the YAML settings…",
    "yaml_imported": "YAML imported. Adjust the settings, then save a copy.",
    "yaml_import_failed": "The YAML could not be imported. Your current settings are kept.",
    "yaml_loaded": "Imported: {filename}",
    "yaml_import_tip": "Import a previous configuration to reuse its settings.",
    "yaml_import_details": "Import details…",
    "new_yaml": "New configuration",
    "yaml_new": "New configuration. Choose your settings, then save the YAML.",
    "yaml_preserved_note": "Additional and weighted settings are kept unless you replace them.",
    "yaml_review_note": "Some imported settings need review. Open Import details.",
    "yaml_preserved_preview": "Imported settings are loaded. Values kept from the file are marked in the settings editor.",
    "yaml_import_review_title": "Review older settings",
    "yaml_import_review_body": "Some older settings cannot be used by this version.\n\n{details}\n\nImport the compatible settings? Your original file is kept.",
    "yaml_notice_preserved": "Kept as written in the file: {settings}",
    "yaml_notice_unknown": "Additional settings kept in the YAML: {settings}",
    "yaml_notice_projection": "Kept from the file; replace in the editor to change: {settings}",
    "yaml_notice_invalid": "Replace these unsupported values in the settings editor before saving: {settings}",
    "yaml_notice_normalized": "Equivalent option names adapted for this version: {settings}",
    "yaml_notice_removed": "Older options removed from the new copy: {settings}",
    "yaml_notice_legacy_migrated": "The old settings code was decoded and its supported settings were loaded.",
    "yaml_notice_legacy_unsupported": "Settings from the old code without an equivalent in this version: {settings}",
    "yaml_details_original": "Saving uses a file chooser. The imported file is not changed automatically.",
    "yaml_error_read": "This YAML could not be read. Choose an existing, readable file.",
    "yaml_error_size": "This YAML is too large. Choose a player configuration file.",
    "yaml_error_syntax": "This YAML has invalid syntax. Check its indentation and try again.",
    "yaml_error_duplicate": "This YAML contains a duplicate setting. Keep one value for each setting.",
    "yaml_error_tag": "This YAML uses unsupported data tags. Choose a standard Archipelago player YAML.",
    "yaml_error_format": "Choose a single Archipelago player YAML configuration.",
    "yaml_error_game": "Choose a player YAML for Ocarina of Time Remake.",
    "yaml_error_legacy": "The older settings code could not be decoded. Your current settings are kept.",
    "yaml_error_settings": "Some imported settings need replacement before saving. Review the values marked in the editor.",
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
    "check_updates": "Check for launcher updates",
    "checking_updates": "Checking for launcher updates…",
    "launcher_update": "Update available…",
    "launcher_version": "Launcher {version} is available.",
    "launcher_current": "Your launcher is up to date.",
    "launcher_check_failed": "Updates could not be checked. Try again from Help.",
    "launcher_downloading": "Downloading the launcher update…",
    "launcher_installing": "Preparing the launcher restart. Please wait…",
    "launcher_update_failed": "The launcher update could not be completed. Your current application is kept.",
    "launcher_download_ready": "Launcher update downloaded and checked. Choose Install and restart when ready.",
    "launcher_download_cancelled": "Launcher update download cancelled.",
    "launcher_updated": "Launcher updated.",
    "launcher_finalize_failed": "The launcher update could not be finalized. You can keep using this application. See the log for details.",
    "launcher_world_updated": "Launcher and Archipelago world updated. Restart Archipelago before generating a room.",
    "launcher_world_failed": "Launcher updated, but its Archipelago world could not be installed. Use Install APWorld to try again.",
    "nav_play": "YOUR ADVENTURE",
    "nav_tools": "RESOURCES",
    "home_eyebrow": "OCARINA OF TIME REMAKE",
    "home_title": "A world to share.",
    "home_caption": "Your game. Your friends. One adventure.",
    "current_room": "CURRENT ROOM",
    "setup_card_note": "Prepare your player file and connect your game.",
    "yaml_card_note": "Choose the rules for your next multiworld.",
    "setup_player_step": "1 · Your player file",
    "setup_game_step": "2 · Your game",
    "setup_connection_step": "3 · Your room",
    "server_hint": "For example: archipelago.gg:38281 or localhost:38281",
    "yaml_flow": "Choose settings → Save YAML → Generate in Archipelago",
    "settings_preview": "Your configuration",
    "world_step": "Before generating a room",
    "appworld_note": "Install this launcher's APWorld, then restart Archipelago to use the matching version.",
    "yaml_tip": "Your choices are kept while you switch between these pages.",
}


def yaml_content(name, values=None, language="en"):
    """Export the selected typed settings, with comments in the UI language."""
    from .catalog import GAME
    from .settings import validate_options, yaml_options
    from .settings_labels import description, is_french
    name = name.strip()
    if not name or len(name) > 16 or name == "Archipelago" or any(ord(char) < 32 for char in name):
        raise ValueError("invalid_player_name")
    selected = validate_options({} if values is None else values)
    heading = ("# Réglages OOT Remake Archipelago.\n# Génère une salle avec ce fichier et ceux des autres joueurs.\n"
               if is_french(language) else
               "# Supported OOT Remake Archipelago settings.\n# Generate a room with this file and the other players' files.\n")
    return (heading +
            f"name: {json.dumps(name, ensure_ascii=False)}\n"
            f"game: {json.dumps(GAME)}\n{json.dumps(GAME)}:\n" + yaml_options(language=language, values=selected) +
            "\n  # " + description("death_link", language) + "\n  death_link: " + json.dumps(selected["death_link"]) + "\n")


@dataclass
class _Task:
    kind: str
    operation: object
    identity: object = None


def _update_probe(kind, operation, results, identity):
    """A slow release check never occupies the game/setup worker or owns Tk."""
    try:
        result = operation()
    except Exception as error:
        logging.getLogger(__name__).info("Application update probe %s failed (%s).", kind, type(error).__name__)
        result = {"_failed": True}
    results.put((_Task(kind, None, identity), result))


class AppWindow:
    def __init__(self, master, *, service=None, base=None, dialogs=filedialog,
                 connection_factory=None, open_path=None, updater=None, startup_notice=None):
        if service is None:
            from . import install_service as service
        self.master, self.service, self.base = master, service, base
        self.dialogs, self.connection_factory = dialogs, connection_factory
        self.path_opener = open_path
        if updater is None:
            from . import update_service as updater
        self.updater = updater
        self.update_checking = self.update_installing = False
        self.update_release, self.update_download = None, None
        self.update_targets = []
        self.update_window = None
        self.update_window_revision = self.update_target_revision = 0
        self.update_notice_key, self.update_notice_values = "", {}
        if startup_notice:
            self.update_notice_key = ("launcher_finalize_failed" if startup_notice.get("completion_failed") else
                                      "launcher_world_failed" if startup_notice.get("error_code") else
                                      "launcher_world_updated" if startup_notice.get("world_updated") else "launcher_updated")
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
        from .settings import default_options
        self.yaml_values = default_options()
        self.yaml_imported = None
        self.yaml_source = None
        self.yaml_changed_keys = set()
        self.settings_window = None
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
        self._schedule(100, self.check_updates)
        self._render()

    def _text(self, key, **values):
        return tr(TEXT[key], language=self.language, **values)

    def _label(self, parent, key, **options):
        options.setdefault("background", ttk.Style(parent).lookup(parent.cget("style") or "TFrame", "background"))
        widget = ttk.Label(parent, **options)
        self.translated_widgets.append((widget, key))
        return widget

    def _button(self, parent, key, command, **options):
        widget = ttk.Button(parent, command=command, **options)
        widget.bind("<FocusIn>", lambda event: self._scroll_control_into_view(event.widget), add="+")
        self.translated_widgets.append((widget, key))
        return widget

    def _build(self):
        apply_theme(self.master)
        set_window_icon(self.master)
        width = min(1100, max(880, self.master.winfo_screenwidth() - 100))
        height = min(820, max(600, self.master.winfo_screenheight() - 100))
        self.master.geometry(f"{width}x{height}")
        self.master.minsize(min(880, width), min(620, height))
        self.master.columnconfigure(1, weight=1)
        self.master.rowconfigure(1, weight=1)
        sidebar = ttk.Frame(self.master, style="App.Sidebar.TFrame", padding=(18, 22, 18, 18), width=234)
        sidebar.grid(row=0, column=0, rowspan=3, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.columnconfigure(0, weight=1)
        sidebar.rowconfigure(6, weight=1)
        mark = tk.Canvas(sidebar, width=60, height=58, background=COLORS["sidebar"], highlightthickness=0)
        mark.grid(row=0, column=0, sticky="w", pady=(0, 10))
        draw_brand(mark, 2, 3, 52)
        ttk.Label(sidebar, text="OOT REMAKE", style="App.Brand.TLabel").grid(row=1, column=0, sticky="w")
        ttk.Label(sidebar, text="ARCHIPELAGO", style="App.Sidebar.TLabel",
                  font=("Segoe UI", 9), foreground=COLORS["muted"]).grid(row=2, column=0, sticky="w", pady=(3, 26))
        self._label(sidebar, "nav_play", style="App.Eyebrow.TLabel").grid(row=3, column=0, sticky="w", pady=(0, 10))
        nav = ttk.Frame(sidebar, style="App.Sidebar.TFrame")
        nav.grid(row=4, column=0, sticky="ew")
        nav.columnconfigure(0, weight=1)
        self.nav_buttons = {}
        for row, (name, key) in enumerate((("home", "home"), ("setup", "setup"), ("yaml", "yaml"))):
            button = self._button(nav, key, lambda name=name: self.show_page(name), style="App.Nav.TButton")
            button.grid(row=row, column=0, sticky="ew", pady=(0, 5))
            self.nav_buttons[name] = button
        tools = ttk.Frame(sidebar, style="App.Sidebar.TFrame")
        tools.grid(row=7, column=0, sticky="ew")
        tools.columnconfigure(0, weight=1)
        self._label(tools, "nav_tools", style="App.Eyebrow.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.sidebar_connection = self._button(tools, "connection", self.open_connection, style="App.Nav.TButton")
        self.sidebar_connection.grid(row=1, column=0, sticky="ew", pady=(0, 5))
        self.sidebar_world = self._button(tools, "install_world", self.install_world, style="App.Nav.TButton")
        self.sidebar_world.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        self.help_button = ttk.Menubutton(tools, style="App.Quiet.TMenubutton")
        self.help_button.grid(row=3, column=0, sticky="ew")
        self.help_menu = tk.Menu(self.help_button, tearoff=False, background=COLORS["surface"],
                                 foreground=COLORS["text"], activebackground=COLORS["elevated"],
                                 activeforeground=COLORS["gold"], borderwidth=0)
        self.help_button.configure(menu=self.help_menu)
        try:
            from .update_service import current_version
            version = current_version()
        except (OSError, ValueError):
            version = ""
        ttk.Label(sidebar, text=version, style="App.Sidebar.TLabel", foreground=COLORS["muted"],
                  font=("Segoe UI", 9)).grid(row=8, column=0, sticky="w", pady=(18, 0))
        header = ttk.Frame(self.master, padding=(30, 22, 30, 18))
        header.grid(row=0, column=1, sticky="ew")
        header.columnconfigure(0, weight=1)
        self._label(header, "home_eyebrow", style="App.Eyebrow.TLabel").grid(row=0, column=0, sticky="w")
        self._label(header, "subtitle", style="App.Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.host_badge = ttk.Label(header, style="App.Status.TLabel", padding=(12, 6))
        self.host_badge.grid(row=0, column=1, rowspan=2, sticky="e", padx=(10, 0))
        self.pages = ttk.Frame(self.master, padding=(30, 0, 30, 0))
        self.pages.grid(row=1, column=1, sticky="nsew")
        self.pages.rowconfigure(0, weight=1)
        self.pages.columnconfigure(0, weight=1)
        self.pages.bind("<Configure>", self._resize, add="+")
        self.page_frames = {name: ttk.Frame(self.pages) for name in ("home", "setup", "yaml")}
        for frame in self.page_frames.values():
            frame.grid(row=0, column=0, sticky="nsew")
        self._build_home(self.page_frames["home"])
        self._build_setup(self.page_frames["setup"])
        self._build_yaml(self.page_frames["yaml"])
        footer = ttk.Frame(self.master, padding=(30, 16, 30, 18))
        footer.grid(row=2, column=1, sticky="ew")
        footer.columnconfigure(1, weight=1)
        self.status_dot = tk.Canvas(footer, width=14, height=14, background=COLORS["bg"], highlightthickness=0)
        self.status_dot.grid(row=0, column=0, sticky="n", padx=(0, 9), pady=3)
        self.status_dot.create_oval(3, 3, 10, 10, fill=COLORS["mint"], outline="", tags="dot")
        self.status = ttk.Label(footer, wraplength=640, style="App.Caption.TLabel")
        self.status.grid(row=0, column=1, sticky="ew", pady=(0, 8))
        self.progress = ttk.Progressbar(footer, maximum=100)
        self.progress.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.progress.grid_remove()
        self.master.bind("<Configure>", self._resize, add="+")
        self.master.bind("<Control-1>", lambda _event: self.show_page("home"), add="+")
        self.master.bind("<Control-2>", lambda _event: self.show_page("setup"), add="+")
        self.master.bind("<Control-3>", lambda _event: self.show_page("yaml"), add="+")

    def _build_home(self, pane):
        outer = pane
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)
        self.home_canvas = tk.Canvas(outer, background=COLORS["bg"], highlightthickness=0, borderwidth=0)
        self.home_canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=self.home_canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        def scrolled(first, last):
            scrollbar.set(first, last)
            scrollbar.grid_remove() if float(first) <= 0 and float(last) >= 1 else scrollbar.grid()
        self.home_canvas.configure(yscrollcommand=scrolled)
        pane = ttk.Frame(self.home_canvas)
        self.home_content = pane
        window = self.home_canvas.create_window((0, 0), window=pane, anchor="nw")
        pane.bind("<Configure>", lambda _event: self.home_canvas.configure(scrollregion=self.home_canvas.bbox("all")))
        self.home_canvas.bind("<Configure>", lambda event: self.home_canvas.itemconfigure(window, width=event.width))
        pane.columnconfigure(0, weight=1)
        self._label(pane, "home_title", style="App.Title.TLabel").grid(row=0, column=0, sticky="w", pady=(8, 7))
        self._label(pane, "home_caption", style="App.Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 24))
        self.hero = tk.Canvas(pane, height=234, background=COLORS["surface"], highlightthickness=1,
                              highlightbackground=COLORS["border"], borderwidth=0)
        self.hero.grid(row=2, column=0, sticky="ew", pady=(0, 18))
        summary = ttk.Frame(self.hero, style="App.Card.TFrame")
        summary.columnconfigure(0, weight=1)
        self.hero_window = self.hero.create_window((26, 23), window=summary, anchor="nw", tags="content")
        self._label(summary, "current_room", style="App.Eyebrow.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 14))
        self.home_status = ttk.Label(summary, style="App.CardHeading.TLabel")
        self.home_status.grid(row=1, column=0, sticky="w")
        self.home_room = ttk.Label(summary, wraplength=390, style="App.CardMuted.TLabel")
        self.home_room.grid(row=2, column=0, sticky="w", pady=(8, 20))
        self.play_button = self._button(summary, "play", self.play, style="App.Primary.TButton")
        self.play_button.grid(row=3, column=0, sticky="w", ipadx=38)
        self.hero.bind("<Configure>", self._draw_hero)
        shortcuts = ttk.Frame(pane)
        shortcuts.grid(row=3, column=0, sticky="ew")
        shortcuts.columnconfigure(0, weight=1, uniform="shortcut")
        shortcuts.columnconfigure(1, weight=1, uniform="shortcut")
        for column, key, note, name in ((0, "setup", "setup_card_note", "setup_button"),
                                         (1, "yaml", "yaml_card_note", "yaml_button")):
            card = ttk.Frame(shortcuts, padding=17, style="App.Card.TFrame")
            card.grid(row=0, column=column, sticky="nsew", padx=(0, 8) if column == 0 else (8, 0))
            card.columnconfigure(0, weight=1)
            button = self._button(card, key, lambda page="setup" if column == 0 else "yaml": self.show_page(page),
                                  style="App.Action.TButton")
            button.grid(row=0, column=0, sticky="ew")
            setattr(self, name, button)
            self._label(card, note, style="App.CardMuted.TLabel", wraplength=255).grid(row=1, column=0, sticky="ew", pady=(11, 0))
        self.connection_button = self._button(pane, "connection", self.open_connection, style="App.Quiet.TButton")
        self.connection_button.grid(row=4, column=0, sticky="w", pady=(14, 0))
        pane.rowconfigure(6, weight=1)
        self.update_banner = ttk.Frame(pane, style="App.Inset.TFrame", padding=(16, 12))
        self.update_banner.grid(row=5, column=0, sticky="ew", pady=(16, 0))
        self.update_banner.columnconfigure(0, weight=1)
        self.update_notice = ttk.Label(self.update_banner, wraplength=420, style="App.Inset.TLabel")
        self.update_notice.grid(row=0, column=0, sticky="w")
        self.update_button = self._button(self.update_banner, "launcher_update", self.open_update, style="App.Action.TButton")
        self.update_button.grid(row=0, column=1, sticky="e", padx=(12, 0))
        self.update_world_button = self._button(self.update_banner, "install_world", self.install_world)
        self.update_world_button.grid(row=1, column=0, sticky="w", pady=(8, 0))

    def _page_title(self, pane, key):
        pane.columnconfigure(0, weight=1)
        nav = ttk.Frame(pane)
        nav.grid(row=0, column=0, sticky="ew", pady=(4, 15))
        nav.columnconfigure(0, weight=1)
        back = self._button(nav, "back", lambda: self.show_page("home"), style="App.Quiet.TButton")
        back.grid(row=0, column=1, padx=(16, 0))
        self.form_widgets.append(back)
        self._label(nav, key, style="App.Title.TLabel").grid(row=0, column=0, sticky="w")

    def _card(self, parent, row, key):
        card = ttk.Frame(parent, style="App.Card.TFrame", padding=20)
        card.grid(row=row, column=0, sticky="ew", pady=(0, 15))
        card.columnconfigure(0, weight=1)
        self._label(card, key, style="App.Subheading.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 16))
        return card

    def _build_setup(self, pane):
        self._page_title(pane, "setup")
        pane.rowconfigure(1, weight=1)
        scroll = ttk.Frame(pane)
        scroll.grid(row=1, column=0, sticky="nsew")
        scroll.columnconfigure(0, weight=1)
        scroll.rowconfigure(0, weight=1)
        self.setup_canvas = tk.Canvas(scroll, highlightthickness=0, borderwidth=0, background=COLORS["bg"])
        self.setup_canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(scroll, orient="vertical", command=self.setup_canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.setup_canvas.configure(yscrollcommand=scrollbar.set)
        form = ttk.Frame(self.setup_canvas, padding=(0, 0, 14, 8))
        form.columnconfigure(0, weight=1)
        window = self.setup_canvas.create_window((0, 0), window=form, anchor="nw")
        form.bind("<Configure>", lambda _event: self.setup_canvas.configure(scrollregion=self.setup_canvas.bbox("all")))
        self.setup_canvas.bind("<Configure>", lambda event: self.setup_canvas.itemconfigure(window, width=event.width))
        self.setup_intro = self._label(form, "setup_intro", style="App.Muted.TLabel", wraplength=640)
        self.setup_intro.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        player_card = self._card(form, 1, "setup_player_step")
        self._path_field(player_card, 1, "manifest", "player_file", self.browse_manifest)
        self.manifest_label = ttk.Label(player_card, wraplength=590, style="App.CardMuted.TLabel")
        self.manifest_label.grid(row=2, column=0, sticky="ew", pady=(9, 0))
        game_card = self._card(form, 2, "setup_game_step")
        host_row = ttk.Frame(game_card, style="App.Card.TFrame")
        host_row.columnconfigure(0, weight=1)
        host_row.grid(row=1, column=0, sticky="ew", pady=(0, 17))
        self._label(host_row, "host").grid(row=0, column=0, sticky="w", pady=(0, 5))
        self.host_choice = ttk.Combobox(host_row, state="readonly", width=32)
        self.host_choice.grid(row=1, column=0, sticky="ew")
        self.host_choice.bind("<<ComboboxSelected>>", self._choose_host)
        self.host_choice.bind("<FocusIn>", lambda event: self._scroll_control_into_view(event.widget), add="+")
        self.host_note = ttk.Label(host_row, wraplength=590, style="App.CardMuted.TLabel")
        self.host_note.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self._path_field(game_card, 2, "game", "game_folder", lambda: self.browse_folder("game", "choose_game"))
        folders = ttk.Checkbutton(game_card, variable=self.extra_folders, command=self._render_folders, style="App.Card.TCheckbutton")
        self.translated_widgets.append((folders, "folders"))
        self.form_widgets.append(folders)
        folders.grid(row=4, column=0, sticky="w", pady=(12, 0))
        self.folder_details = ttk.Frame(game_card, style="App.Card.TFrame")
        self.folder_details.columnconfigure(0, weight=1)
        self.folder_details.grid(row=5, column=0, sticky="ew", pady=(14, 0))
        self._path_field(self.folder_details, 0, "romfs", "romfs", lambda: self.browse_folder("romfs", "choose_romfs"))
        self._path_field(self.folder_details, 1, "tools", "tools", lambda: self.browse_folder("tools", "choose_tools"))
        self.folder_details.grid_remove()
        self.installation_label = ttk.Label(game_card, wraplength=590, style="App.CardMuted.TLabel")
        self.installation_label.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        connection_card = self._card(form, 3, "setup_connection_step")
        for row, (name, key) in enumerate((("server", "server"), ("password", "password")), 1):
            frame = ttk.Frame(connection_card, style="App.Card.TFrame")
            frame.columnconfigure(0, weight=1)
            frame.grid(row=row, column=0, sticky="ew", pady=(0, 14))
            self._label(frame, key).grid(row=0, column=0, sticky="w", pady=(0, 5))
            entry = ttk.Entry(frame, textvariable=self.fields[name], show="•" if name == "password" else "")
            entry.grid(row=1, column=0, sticky="ew")
            entry.bind("<FocusIn>", lambda event: self._scroll_control_into_view(event.widget), add="+")
            if name == "password":
                self.password_entry = entry
            else:
                self._label(frame, "server_hint", style="App.CardCaption.TLabel").grid(row=2, column=0, sticky="w", pady=(6, 0))
            self.form_widgets.append(entry)
        reveal = ttk.Checkbutton(connection_card, variable=self.show_password, command=self._reveal_password, style="App.Card.TCheckbutton")
        self.translated_widgets.append((reveal, "show_password"))
        self.form_widgets.append(reveal)
        reveal.grid(row=3, column=0, sticky="w", pady=(0, 10))
        auto = ttk.Checkbutton(connection_card, variable=self.automatic, style="App.Card.TCheckbutton")
        self.translated_widgets.append((auto, "automatic"))
        self.form_widgets.append(auto)
        auto.grid(row=4, column=0, sticky="w", pady=(3, 0))
        actions = ttk.Frame(pane)
        actions.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        actions.columnconfigure(0, weight=1)
        self.cancel_button = self._button(actions, "cancel", self.cancel, style="App.Quiet.TButton")
        self.cancel_button.grid(row=0, column=0, sticky="w")
        self.install_button = self._button(actions, "install", self.install, style="App.Primary.TButton")
        self.install_button.grid(row=0, column=1, sticky="e")

    def _path_field(self, parent, row, name, key, browse):
        field = ttk.Frame(parent, style=parent.cget("style") or "TFrame")
        field.grid(row=row, column=0, sticky="ew", pady=(0, 5))
        field.columnconfigure(0, weight=1)
        self._label(field, key).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 5))
        entry = ttk.Entry(field, textvariable=self.fields[name])
        entry.grid(row=1, column=0, sticky="ew")
        entry.bind("<FocusIn>", lambda event: self._scroll_control_into_view(event.widget), add="+")
        button = self._button(field, "browse", browse)
        button.grid(row=1, column=1, padx=(9, 0))
        self.form_widgets.extend((entry, button))

    def _build_yaml(self, pane):
        self._page_title(pane, "yaml")
        pane.rowconfigure(1, weight=1)
        scroll = ttk.Frame(pane)
        scroll.grid(row=1, column=0, sticky="nsew")
        scroll.columnconfigure(0, weight=1)
        scroll.rowconfigure(0, weight=1)
        self.yaml_canvas = tk.Canvas(scroll, background=COLORS["bg"], borderwidth=0, highlightthickness=0)
        self.yaml_canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(scroll, orient="vertical", command=self.yaml_canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.yaml_canvas.configure(yscrollcommand=scrollbar.set)
        form = ttk.Frame(self.yaml_canvas, padding=(0, 0, 14, 8))
        form.columnconfigure(0, weight=1)
        window = self.yaml_canvas.create_window((0, 0), window=form, anchor="nw")
        form.bind("<Configure>", lambda _event: self.yaml_canvas.configure(scrollregion=self.yaml_canvas.bbox("all")))
        self.yaml_canvas.bind("<Configure>", lambda event: self.yaml_canvas.itemconfigure(window, width=event.width))
        self.yaml_intro = self._label(form, "yaml_intro", style="App.Muted.TLabel", wraplength=640)
        self.yaml_intro.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        configuration = self._card(form, 1, "settings_preview")
        imports = ttk.Frame(configuration, style="App.Card.TFrame")
        imports.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        imports.columnconfigure(0, weight=1)
        self.import_yaml_button = self._button(imports, "import_yaml", self.import_yaml, style="App.Action.TButton")
        self.import_yaml_button.grid(row=0, column=0, sticky="w")
        self.new_yaml_button = self._button(imports, "new_yaml", self.new_yaml, style="App.Quiet.TButton")
        self.new_yaml_button.grid(row=0, column=1, sticky="e", padx=(12, 0))
        self.yaml_import_note = ttk.Label(configuration, style="App.CardMuted.TLabel", wraplength=590)
        self.yaml_import_note.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        self.yaml_details_button = self._button(configuration, "yaml_import_details", self.show_yaml_details,
                                                style="App.Quiet.TButton")
        self.yaml_details_button.grid(row=3, column=0, sticky="w", pady=(0, 12))
        self._label(configuration, "player_name").grid(row=4, column=0, sticky="w", pady=(0, 6))
        self.name_entry = ttk.Entry(configuration, textvariable=self.player_name)
        self.name_entry.grid(row=5, column=0, sticky="ew")
        self.form_widgets.append(self.name_entry)
        actions = ttk.Frame(configuration, style="App.Card.TFrame")
        actions.grid(row=6, column=0, sticky="ew", pady=(16, 16))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        self.settings_button = self._button(actions, "yaml_settings", self.open_settings, style="App.Action.TButton")
        self.settings_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.save_yaml_button = self._button(actions, "save_yaml", self.save_yaml, style="App.Primary.TButton")
        self.save_yaml_button.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.yaml_preview = ttk.Label(configuration, style="App.CardMuted.TLabel", wraplength=590)
        self.yaml_preview.grid(row=7, column=0, sticky="ew", pady=(2, 12))
        self._label(configuration, "yaml_tip", style="App.CardCaption.TLabel", wraplength=590).grid(row=8, column=0, sticky="ew")
        world = self._card(form, 2, "world_step")
        self._label(world, "appworld_note", style="App.CardMuted.TLabel", wraplength=590).grid(row=1, column=0, sticky="ew", pady=(0, 16))
        self.world_button = self._button(world, "install_world", self.install_world, style="App.Action.TButton")
        self.world_button.grid(row=2, column=0, sticky="w")
        self._label(form, "yaml_flow", style="App.Caption.TLabel", wraplength=640).grid(row=3, column=0, sticky="ew", pady=(0, 8))

    def _wheel(self, event):
        if event.widget.winfo_toplevel() != self.master:
            return
        x, y = self.master.winfo_pointerxy()
        canvas = {"home": self.home_canvas, "setup": self.setup_canvas, "yaml": self.yaml_canvas}[self.page]
        if (canvas.winfo_rootx() <= x < canvas.winfo_rootx() + canvas.winfo_width()
                and canvas.winfo_rooty() <= y < canvas.winfo_rooty() + canvas.winfo_height()):
            canvas.yview_scroll(-int(event.delta / 120), "units")

    def _scroll_control_into_view(self, widget):
        canvas = {"home": self.home_canvas, "setup": self.setup_canvas, "yaml": self.yaml_canvas}[self.page]
        if not str(widget).startswith(str(canvas) + ".") or not canvas.winfo_ismapped():
            return
        bounds = canvas.bbox("all")
        if not bounds or bounds[3] <= canvas.winfo_height():
            return
        top = widget.winfo_rooty() - canvas.winfo_rooty()
        bottom = top + widget.winfo_height()
        offset = canvas.canvasy(0)
        if top < 12:
            canvas.yview_moveto(max(0, offset + top - 20) / bounds[3])
        elif bottom > canvas.winfo_height() - 12:
            canvas.yview_moveto(max(0, offset + bottom - canvas.winfo_height() + 20) / bounds[3])

    def _resize(self, event):
        if event.widget not in (self.master, self.pages):
            return
        available = max(300, self.pages.winfo_width() - 110)
        for label in (self.status, self.manifest_label, self.host_note, self.installation_label,
                      self.setup_intro, self.yaml_intro, self.yaml_preview, self.yaml_import_note):
            label.configure(wraplength=available)
        self.home_room.configure(wraplength=max(210, available - 130))
        self.update_notice.configure(wraplength=max(220, available - 190))

    def _draw_hero(self, event):
        """Original vector scenery; no game assets or animation loops."""
        canvas, width, height = self.hero, event.width, event.height
        canvas.delete("scenery")
        right = width - 20
        canvas.create_oval(right - 170, 28, right - 20, 178, fill="#1c3435", outline="", tags="scenery")
        canvas.create_oval(right - 144, 54, right - 46, 152, outline="#49605a", width=1, tags="scenery")
        canvas.create_oval(right - 128, 70, right - 62, 136, outline=COLORS["gold"], width=1, tags="scenery")
        canvas.create_polygon(width * .55, height, width * .66, height * .69, width * .79, height * .88,
                              width * .9, height * .62, width, height * .73, width, height,
                              fill="#1e3838", outline="", smooth=True, tags="scenery")
        canvas.create_polygon(width * .52, height, width * .73, height * .84, width * .87, height * .94,
                              width, height * .80, width, height,
                              fill="#284641", outline="", smooth=True, tags="scenery")
        points = [(right - 157, 95), (right - 95, 36), (right - 18, 98), (right - 64, 173)]
        canvas.create_line(*sum(([x, y] for x, y in points), []), fill="#617869", dash=(2, 5), tags="scenery")
        for x, y in points:
            canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill=COLORS["gold"], outline=COLORS["surface"], width=2, tags="scenery")
        # An abstract doorway at the centre of a connected constellation.
        x, y = right - 95, 102
        canvas.create_polygon(x - 13, y + 24, x - 13, y - 14, x, y - 27, x + 13, y - 14, x + 13, y + 24,
                              fill=COLORS["surface"], outline=COLORS["gold"], width=2, tags="scenery")
        canvas.create_line(x, y - 16, x, y + 19, fill=COLORS["gold"], tags="scenery")
        canvas.tag_lower("scenery")
        canvas.itemconfigure(self.hero_window, width=max(270, width - 225))

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
                result = {"_failed": True, "_cancelled": bool(getattr(error, "cancelled", False))
                          or (task.kind == "update_download" and isinstance(error, InterruptedError)),
                          "_message": getattr(error, "public_message", ""),
                          "_yaml_error": getattr(error, "code", "read") if task.kind == "yaml_import" else ""}
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
            elif task.kind == "update_progress":
                if self.update_window and not self.update_window.closed:
                    self.update_window.progress_update(*result)
            elif task.kind == "update_check":
                self.update_checking = False
                if result.get("_failed"):
                    if task.identity:
                        self.update_notice_key, self.update_notice_values = "launcher_check_failed", {}
                else:
                    self.update_release = result["release"] if result["release"].get("update_available") else None
                    self.update_targets = result.get("targets", [])
                    if self.update_release:
                        self.update_notice_key = "launcher_version"
                        self.update_notice_values = {"version": self.update_release["latest_version"]}
                        if self.update_download and self.update_download.get("version") != self.update_release["latest_version"]:
                            self.update_download = None
                    elif task.identity:
                        self.update_notice_key, self.update_notice_values = "launcher_current", {}
            elif task.kind == "update_world_check":
                if (task.identity == (self.update_window_revision, self.update_target_revision)
                        and self.update_window and not self.update_window.closed):
                    self.update_window.checked_target(result)
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
                        "yaml_import": "yaml_import_failed",
                        "world": "world_failed", "licenses": "path_failed",
                        "update_download": "launcher_update_failed", "update_schedule": "launcher_update_failed"
                    }[task.kind]
                    self.progress_text = result.get("_message", "")
                    if task.kind == "yaml_import":
                        self.progress_text = self._yaml_error_text(result.get("_yaml_error", "read"))
                    if task.kind in {"update_download", "update_schedule"}:
                        self.update_installing = False
                        if task.kind == "update_schedule":
                            self.close_requested = False
                            # A timed-out helper can still be alive with a
                            # cancelled plan. Retain that stage and retry in a
                            # newly downloaded one; never reuse its plan/files.
                            self.update_download = None
                            if self.update_window and not self.update_window.closed:
                                self.update_window.download = None
                        if result.get("_cancelled"):
                            self.status_key = "launcher_download_cancelled"
                        if self.update_window and not self.update_window.closed:
                            self.update_window.finished(None, failed=True, cancelled=result.get("_cancelled", False))
                elif task.kind == "yaml_import":
                    if self.cancel_event.is_set():
                        self.status_key = "cancelled"
                    elif not self.close_requested:
                        self._accept_yaml_import(result["imported"])
                elif task.kind == "update_download":
                    self.update_download = result
                    self.status_key = "launcher_download_ready"
                    if self.update_window and not self.update_window.closed:
                        self.update_window.finished(result)
                elif task.kind == "update_schedule":
                    self.update_installing = False
                    if self.update_window and not self.update_window.closed:
                        self.update_window.busy = self.update_window.installing = False
                    self.close()
                    return
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
                                 ("check_updates", lambda: self.check_updates(manual=True)),
                                 ("open_data", self.open_data), ("licenses", self.open_licenses),
                                 ("about", self.about)):
                self.help_menu.add_command(label=self._text(key), command=command)
            self.menu_language = self.language
        for name, frame in self.page_frames.items():
            frame.grid() if name == self.page else frame.grid_remove()
        for name, button in self.nav_buttons.items():
            button.configure(style="App.NavActive.TButton" if name == self.page else "App.Nav.TButton",
                             state="disabled" if self.busy else "normal")
        self.host_badge.configure(text=self._text("hookshot" if self.host == "hookshot" else "triforce"))
        self.host_choice.configure(values=(self._text("triforce"), self._text("hookshot")),
                                   state="disabled" if self.busy else "readonly")
        self.host_choice.current(1 if self.host == "hookshot" else 0)
        self.host_note.configure(text=self._text("hookshot_note" if self.host == "hookshot" else "triforce_note"))
        self.installation_label.configure(text=self.installation_detail or self._text(self.installation_message))
        self.installation_label.configure(foreground=COLORS["mint"] if self.installation_info else
                                         COLORS["danger"] if self.installation_message == "game_invalid" else COLORS["muted"])
        ready = bool(self.current.get("ready"))
        self.home_status.configure(text=self._text("ready" if ready else "update_title" if self.current.get("profile") else "not_prepared"))
        if self.current.get("profile"):
            detail = (self._text("player_room", slot=self.current.get("slot", ""), room=self.current.get("room", ""))
                      if ready else self._text("resources_update_needed" if self.current.get("resources_update_required") else "update_needed"))
        else:
            detail = self._text("prepare_first")
        self.home_room.configure(text=detail)
        self.play_button.configure(state="normal" if ready and not self.busy else "disabled")
        self.connection_button.configure(state="normal" if self.current.get("profile") and not self.busy else "disabled")
        self.sidebar_connection.configure(state=self.connection_button.cget("state"))
        for widget in (self.setup_button, self.yaml_button, self.settings_button, self.save_yaml_button,
                       self.import_yaml_button, self.new_yaml_button, self.yaml_details_button,
                       self.world_button, self.sidebar_world, *self.form_widgets):
            widget.configure(state="disabled" if self.busy else "normal")
        can_install = bool(self.manifest_info and self.installation_info and self.installation_info.get("valid")
                           and self.fields["game"].get().strip() and self.fields["server"].get().strip())
        self.install_button.configure(state="normal" if can_install and not self.busy else "disabled")
        self.cancel_button.configure(state="normal" if self.busy and not self.cancel_event.is_set() else "disabled")
        if self.update_installing:
            self.cancel_button.configure(state="disabled")
        self.manifest_label.configure(text=self._text("player_room", slot=self.manifest_info.get("slot", ""),
                                                     room=self.manifest_info.get("room", ""))
                                      if self.manifest_info else self._text(self.manifest_message))
        self.manifest_label.configure(foreground=COLORS["mint"] if self.manifest_info else
                                      COLORS["danger"] if self.manifest_message == "invalid_player" else COLORS["muted"])
        from .settings_labels import selection_summary
        from .settings import SPEC_BY_ID
        preserved = (set(self.yaml_imported.preserved_options) - self.yaml_changed_keys
                     if self.yaml_imported is not None else set())
        opaque = preserved.intersection(SPEC_BY_ID)
        self.yaml_preview.configure(text=self._text("yaml_preserved_preview") if opaque else
                                    "\n".join(selection_summary(self.yaml_values, self.language)[:4]))
        note = self._text("yaml_loaded", filename=self.yaml_source.name) if self.yaml_source else self._text("yaml_import_tip")
        if self.yaml_imported is not None:
            invalid = set(getattr(self.yaml_imported, "invalid_options", {})) - self.yaml_changed_keys
            if invalid:
                note += "\n" + self._text("yaml_review_note")
            elif preserved:
                note += "\n" + self._text("yaml_preserved_note")
            self.yaml_details_button.grid()
        else:
            self.yaml_details_button.grid_remove()
        self.yaml_import_note.configure(text=note)
        self.status.configure(text=self.progress_text or self._text(self.status_key, **self.status_values))
        failed = self.status_key.endswith("_failed") or self.status_key == "yaml_name_error"
        self.status_dot.itemconfigure("dot", fill=COLORS["gold"] if self.busy else COLORS["danger"] if failed else COLORS["mint"])
        self.status.configure(foreground=COLORS["danger"] if failed else COLORS["muted"])
        if self.busy:
            self.progress.grid()
        else:
            self.progress.grid_remove()
        self.update_notice.configure(text=self._text(self.update_notice_key, **self.update_notice_values) if self.update_notice_key else "")
        if self.update_release:
            self.update_button.grid()
            self.update_button.configure(state="disabled" if self.busy else "normal")
        else:
            self.update_button.grid_remove()
        if self.update_notice_key == "launcher_world_failed":
            self.update_world_button.grid()
            self.update_world_button.configure(state="disabled" if self.busy else "normal")
        else:
            self.update_world_button.grid_remove()
        self.update_banner.grid() if self.update_release or self.update_notice_key else self.update_banner.grid_remove()
        if self.update_window and not self.update_window.closed:
            self.update_window.render(self.language, blocked=self.busy and not self.update_window.busy)

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
        if self.update_installing:
            return
        if self.busy:
            self.cancel_event.set()
            self.status_key, self.progress_text = "cancelling", ""
            self._render()

    def check_updates(self, manual=False):
        if self.closed or self.update_checking:
            return
        self.update_checking = True
        if manual:
            self.update_notice_key, self.update_notice_values = "checking_updates", {}
        updater, base, results = self.updater, self.base, self.results
        def check():
            release = updater.check_for_updates()
            from . import app_runtime
            discover = getattr(app_runtime, "discover_apworld_targets", None)
            try:
                targets = discover(base=base) if discover else []
            except (OSError, ValueError):
                targets = []
            return {"release": release, "targets": [str(target) for target in targets]}
        threading.Thread(target=_update_probe, args=("update_check", check, results, manual),
                         name="Archipelago update check", daemon=True).start()
        self._render()

    def open_update(self):
        if self.busy or not self.update_release:
            return
        if self.update_window and not self.update_window.closed:
            self.update_window.master.lift()
            return
        from .update_window import UpdateWindow
        self.update_window_revision += 1
        self.update_window = UpdateWindow(tk.Toplevel(self.master), self.update_release,
            language=self.language, targets=self.update_targets, on_target=self.choose_update_world,
            on_download=self.download_update, on_install=self.install_update, on_cancel=self.cancel)
        if self.update_download and self.update_download.get("version") == self.update_release["latest_version"]:
            self.update_window.finished(self.update_download)
        if self.update_targets:
            self.choose_update_world(self.update_targets[0])

    def choose_update_world(self, target):
        window = self.update_window
        if self.busy or not window or window.closed:
            return
        if target is None:
            target = self.dialogs.askdirectory(parent=window.master, title=self._text("world_folder"), mustexist=True)
        if not target:
            return
        window.check_target(target)
        self.update_target_revision += 1
        identity = (self.update_window_revision, self.update_target_revision)
        expected = window.release["assets"]["apworld"]["sha256"]
        updater, results = self.updater, self.results
        threading.Thread(target=_update_probe,
            args=("update_world_check", lambda: updater.apworld_status(target, expected), results, identity),
            name="Archipelago world update check", daemon=True).start()

    def download_update(self, release):
        if self.busy:
            return
        updater, base, cancel, results = self.updater, self.base, self.cancel_event, self.results
        def progress(percent, message):
            results.put((_Task("update_progress", None), (percent, message)))
        operation = lambda: updater.download_update(release, base=base, progress=progress, cancel=cancel)
        if self.update_window and not self.update_window.closed:
            self.update_window.begin()
        self._start("update_download", operation, "launcher_downloading")

    def install_update(self, download, world_target=None):
        if self.busy:
            return
        updater, base = self.updater, self.base
        def schedule():
            result = updater.schedule_install(download, base=base, world_target=world_target)
            if not result.get("helper_started"):
                raise RuntimeError("The update helper did not start.")
            return result
        self.update_installing = True
        if self.update_window and not self.update_window.closed:
            self.update_window.begin(installing=True)
        self._start("update_schedule", schedule, "launcher_installing")

    def play(self):
        if not self.busy and self.current.get("ready"):
            request = dict(self.current)
            self._start("launch", lambda: (self.service.launch(request), {})[1], "launched")

    def save_yaml(self):
        if self.busy:
            return
        try:
            if self.yaml_imported is None:
                content = yaml_content(self.player_name.get(), self.yaml_values, self.language)
            else:
                from .yaml_import import render_imported_yaml
                content = render_imported_yaml(self.yaml_imported, self.player_name.get(), self.yaml_values,
                                               self.language, changed_keys=self.yaml_changed_keys)
        except ValueError as error:
            name_error = str(error) == "invalid_player_name" or getattr(error, "code", "") == "name"
            self.status_key = "yaml_name_error" if name_error else "yaml_import_failed"
            self.progress_text = "" if name_error else self._yaml_error_text(getattr(error, "code", "settings"))
            self._render()
            if name_error:
                self.name_entry.focus_set()
            return
        safe_name = re.sub(r"[^\w -]", "_", self.player_name.get().strip())
        options = dict(parent=self.master, title=self._text("save_yaml"), defaultextension=".yaml",
                       initialfile=f"Player-{safe_name}.yaml", filetypes=((self._text("yaml_file"), "*.yaml *.yml"),))
        if self.yaml_source is not None:
            options.update(initialdir=str(self.yaml_source.parent), initialfile=self.yaml_source.stem + "-modified.yaml")
        target = self.dialogs.asksaveasfilename(**options)
        if target:
            def save():
                from .save_bridge import atomic
                atomic(Path(target), content.encode("utf-8"))
                return {}
            self._start("yaml", save, "saving_yaml")

    def open_settings(self):
        if self.busy:
            return
        if self.settings_window and not self.settings_window.closed:
            self.settings_window.window.lift()
            return
        from .settings_window import SettingsWindow
        def apply(values):
            if self.yaml_imported is None:
                self.yaml_values = values
            else:
                changed = self.settings_window.changed_keys
                self.yaml_values.update({name: values[name] for name in changed})
                self.yaml_changed_keys.update(changed)
            self._render()
        self.settings_window = SettingsWindow(self.master, values=self.yaml_values,
                                               language=self.language, on_apply=apply,
                                               preserve_unchanged=self.yaml_imported is not None,
                                               preserved_options=(set(self.yaml_imported.preserved_options) - self.yaml_changed_keys
                                                                  if self.yaml_imported is not None else ()))

    def _yaml_error_text(self, code):
        key = {"too_large": "yaml_error_size", "syntax": "yaml_error_syntax", "duplicate_key": "yaml_error_duplicate",
               "unsupported_tag": "yaml_error_tag", "format": "yaml_error_format", "game": "yaml_error_game",
               "name": "yaml_name_error", "legacy": "yaml_error_legacy", "settings": "yaml_error_settings"}.get(code, "yaml_error_read")
        return self._text(key)

    def import_yaml(self):
        if self.busy:
            return
        options = dict(parent=self.master, title=self._text("import_yaml"),
                       filetypes=((self._text("yaml_file"), "*.yaml *.yml"), (self._text("all_files"), "*.*")))
        if self.yaml_source is not None:
            options["initialdir"] = str(self.yaml_source.parent)
        chosen = self.dialogs.askopenfilename(**options)
        if chosen:
            from .yaml_import import load_yaml
            self._start("yaml_import", lambda: {"imported": load_yaml(chosen)}, "importing_yaml")

    def _accept_yaml_import(self, imported):
        if imported.requires_review and not messagebox.askyesno(self._text("yaml_import_review_title"),
                self._text("yaml_import_review_body", details=self._yaml_details_text(imported)), parent=self.master):
            self.status_key = "cancelled"
            return
        if self.settings_window and not self.settings_window.closed:
            self.settings_window.close()
        self.yaml_imported = imported
        self.yaml_source = imported.source
        from copy import deepcopy
        self.yaml_values = deepcopy(imported.values)
        self.yaml_changed_keys.clear()
        self.player_name.set(imported.name)
        self.status_key, self.progress_text = "yaml_imported", ""

    def _yaml_details_text(self, imported=None):
        from .settings import SPEC_BY_ID
        from .settings_labels import setting_label
        imported = imported or self.yaml_imported
        if imported is None:
            return ""
        lines = []
        invalid = set(imported.invalid_options)
        if imported is self.yaml_imported:
            invalid -= self.yaml_changed_keys
        if invalid:
            labels = [setting_label(name, self.language) for name in sorted(invalid)]
            lines.append(self._text("yaml_notice_invalid", settings=", ".join(labels)))
        for code in ("legacy_migrated", "removed", "legacy_unsupported", "normalized", "preserved", "projection", "unknown"):
            notices = [notice for notice in imported.warnings if notice.code == code]
            if not notices:
                continue
            names = sorted({notice.key for notice in notices if notice.key})
            labels = [setting_label(name, self.language) if name in SPEC_BY_ID else name for name in names]
            lines.append(self._text("yaml_notice_" + code, settings=", ".join(labels)))
        lines.append(self._text("yaml_details_original"))
        return "\n\n".join(lines)

    def show_yaml_details(self):
        if self.yaml_imported is not None and not self.busy:
            messagebox.showinfo(self._text("yaml_import_details"), self._yaml_details_text(), parent=self.master)

    def new_yaml(self):
        if self.busy:
            return
        if self.settings_window and not self.settings_window.closed:
            self.settings_window.close()
        from .settings import default_options
        self.yaml_imported = self.yaml_source = None
        self.yaml_changed_keys.clear()
        self.yaml_values = default_options()
        self.player_name.set("Link")
        self.status_key, self.progress_text = "yaml_new", ""
        self._render()

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
        apply_theme(dialog)
        set_window_icon(dialog)
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
        link = ttk.Label(content, text=url, foreground=COLORS["gold"], cursor="hand2", takefocus=True)
        link.grid(row=3, column=0, sticky="w")
        link.bind("<Button-1>", lambda _event: webbrowser.open(url))
        link.bind("<Return>", lambda _event: webbrowser.open(url))
        dialog.bind("<Escape>", lambda _event: dialog.destroy())

    def close(self):
        if self.closed:
            return
        if self.busy:
            self.close_requested = True
            if not self.update_installing:
                self.cancel()
            return
        self.closed = True
        self.stop.set()
        self.worker.join(timeout=.3)
        self._set_field("password", "")
        if self.connection_window and not self.connection_window.closed:
            self.connection_window.close()
        if self.update_window and not self.update_window.closed:
            self.update_window.close()
        for identifier in self.after_ids:
            self.master.after_cancel(identifier)
        self.after_ids.clear()
        self.master.destroy()


def main(startup_notice=None):
    root = tk.Tk()
    AppWindow(root, startup_notice=startup_notice)
    root.mainloop()


if __name__ == "__main__":
    main()
