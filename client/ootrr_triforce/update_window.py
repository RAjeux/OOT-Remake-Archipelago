"""A small update review window; filesystem and network work belongs to services."""
import tkinter as tk
from tkinter import ttk
import webbrowser

from .i18n import tr


TEXT = {
    "title": "Update launcher",
    "version": "Version {current} → {latest}",
    "intro": "The download is checked before installation. Your rooms and saves stay in place.",
    "world": "Also update the Archipelago world",
    "world_folder": "Archipelago folder",
    "browse": "Browse…",
    "world_choose": "Choose your Archipelago folder to check its installed world.",
    "world_checking": "Checking the installed Archipelago world…",
    "world_changed": "A different APWorld is available. Select the option above to replace it too.",
    "world_current": "Your APWorld already matches this release. It will be kept.",
    "world_failed": "This Archipelago folder could not be checked. Choose its installation folder and try again.",
    "source": "To install updates, open the Windows launcher executable. Source installations can use the release page.",
    "download": "Download update",
    "install": "Install and restart",
    "release": "Open release page",
    "close": "Close",
    "cancel": "Cancel download",
    "cancelling": "Cancelling the update download…",
    "downloading": "Downloading and checking the update…",
    "ready": "Download verified. The launcher is ready to restart.",
    "installing": "Preparing the restart. Please wait…",
    "failed": "The update could not be completed. Your current launcher is kept. Try again.",
    "cancelled": "Update download cancelled.",
}


class UpdateWindow:
    def __init__(self, master, release, *, language="en", targets=(), on_target=None,
                 on_download=None, on_install=None, on_cancel=None, on_close=None):
        self.master, self.release, self.language = master, release, language
        self.on_target, self.on_download, self.on_install = on_target, on_download, on_install
        self.on_cancel, self.on_close = on_cancel, on_close
        self.closed = self.busy = self.installing = self.close_requested = self.blocked = False
        self.world_checking = self.world_failed = False
        self.world_status, self.download = {}, None
        self.message_key, self.progress_text = "", ""
        self.want_world = tk.BooleanVar(value=False)
        self.target = tk.StringVar()
        master.title(self.text("title"))
        master.geometry("650x550")
        master.minsize(640, 520)
        master.columnconfigure(0, weight=1)
        pane = ttk.Frame(master, padding=24)
        pane.grid(sticky="nsew")
        pane.columnconfigure(0, weight=1)
        self.heading = ttk.Label(pane, font=("Segoe UI", 15, "bold"))
        self.heading.grid(row=0, column=0, sticky="w")
        self.version = ttk.Label(pane, font=("Segoe UI", 11, "bold"))
        self.version.grid(row=1, column=0, sticky="w", pady=(10, 12))
        self.intro = ttk.Label(pane, wraplength=590)
        self.intro.grid(row=2, column=0, sticky="ew", pady=(0, 20))
        self.world = ttk.Checkbutton(pane, variable=self.want_world)
        self.world.grid(row=3, column=0, sticky="w")
        self.folder_label = ttk.Label(pane)
        self.folder_label.grid(row=4, column=0, sticky="w", pady=(12, 4))
        folders = ttk.Frame(pane)
        folders.grid(row=5, column=0, sticky="ew")
        folders.columnconfigure(0, weight=1)
        self.folder = ttk.Combobox(folders, textvariable=self.target, values=tuple(map(str, targets)), state="readonly")
        self.folder.grid(row=0, column=0, sticky="ew")
        self.folder.bind("<<ComboboxSelected>>", lambda _event: self.on_target(self.target.get()) if self.on_target else None)
        self.browse = ttk.Button(folders, command=lambda: self.on_target(None) if self.on_target else None)
        self.browse.grid(row=0, column=1, padx=(10, 0))
        self.world_note = ttk.Label(pane, wraplength=590)
        self.world_note.grid(row=6, column=0, sticky="ew", pady=(7, 16))
        self.source_note = ttk.Label(pane, wraplength=590)
        self.source_note.grid(row=7, column=0, sticky="ew")
        self.status = ttk.Label(pane, wraplength=590)
        self.status.grid(row=8, column=0, sticky="ew", pady=(12, 8))
        self.progress = ttk.Progressbar(pane, maximum=100)
        self.progress.grid(row=9, column=0, sticky="ew")
        actions = ttk.Frame(pane)
        actions.grid(row=10, column=0, sticky="ew", pady=(18, 0))
        actions.columnconfigure(1, weight=1)
        self.release_button = ttk.Button(actions, command=lambda: webbrowser.open(release["release_url"]))
        self.release_button.grid(row=0, column=0, sticky="w")
        self.close_button = ttk.Button(actions, command=self.close)
        self.close_button.grid(row=0, column=2, padx=(0, 10))
        self.primary = ttk.Button(actions, command=self.proceed, style="App.Action.TButton")
        self.primary.grid(row=0, column=3)
        master.protocol("WM_DELETE_WINDOW", self.close)
        master.bind("<Escape>", lambda _event: self.close())
        self.render()

    def text(self, key, **values):
        return tr(TEXT[key], language=self.language, **values)

    def render(self, language=None, blocked=None):
        if self.closed:
            return
        if language:
            self.language = language
        if blocked is not None:
            self.blocked = blocked
        self.master.title(self.text("title"))
        for widget, key in ((self.heading, "title"), (self.intro, "intro"), (self.world, "world"),
                            (self.folder_label, "world_folder"), (self.browse, "browse"),
                            (self.source_note, "source"), (self.release_button, "release")):
            widget.configure(text=self.text(key))
        self.version.configure(text=self.text("version", current=self.release["current_version"], latest=self.release["latest_version"]))
        note = "world_checking" if self.world_checking else "world_failed" if self.world_failed else (
            "world_changed" if self.world_status.get("changed") else "world_current" if self.world_status else "world_choose")
        self.world_note.configure(text=self.text(note))
        allowed = bool(self.release.get("can_install"))
        self.source_note.grid_remove() if allowed else self.source_note.grid()
        editable = allowed and not self.busy and not self.blocked
        self.folder.configure(state="readonly" if editable else "disabled")
        self.browse.configure(state="normal" if editable else "disabled")
        self.world.configure(state="normal" if editable and self.world_status.get("changed") else "disabled")
        self.primary.configure(text=self.text("install" if self.download else "download"),
                               state="normal" if editable and not self.world_checking else "disabled")
        self.close_button.configure(text=self.text("cancel" if self.busy and not self.installing else "close"),
                                    state="disabled" if self.installing else "normal")
        self.release_button.configure(state="disabled" if self.busy else "normal")
        self.status.configure(text=self.progress_text or (self.text(self.message_key) if self.message_key else ""))
        self.progress.grid() if self.busy else self.progress.grid_remove()

    def check_target(self, target):
        self.target.set(str(target))
        self.want_world.set(False)
        self.world_status = {}
        self.world_checking, self.world_failed = True, False
        self.render()

    def checked_target(self, result):
        self.world_checking = False
        self.world_failed = bool(result.get("_failed"))
        self.world_status = {} if self.world_failed else result
        if result.get("target"):
            self.target.set(result["target"])
        if not self.world_status.get("changed"):
            self.want_world.set(False)
        self.render()

    def begin(self, installing=False):
        self.busy, self.installing = True, installing
        self.message_key, self.progress_text = "installing" if installing else "downloading", ""
        self.progress.configure(value=0, mode="indeterminate" if installing else "determinate")
        if installing:
            self.progress.start(15)
        self.render()

    def progress_update(self, percent, message):
        self.progress.configure(value=max(0, min(100, percent)))
        self.progress_text = tr(message, language=self.language)
        self.render()

    def finished(self, result, *, failed=False, cancelled=False):
        self.busy = self.installing = False
        self.progress.stop()
        self.progress_text = ""
        self.message_key = "cancelled" if cancelled else "failed" if failed else "ready"
        if not failed and not cancelled:
            self.download = result
        if self.close_requested:
            self.close()
        else:
            self.render()

    def selected_world(self):
        if (self.want_world.get() and self.world_status.get("changed") and not self.world_checking
                and self.target.get() == self.world_status.get("target")):
            return self.world_status["target"]
        return None

    def proceed(self):
        if self.busy or self.blocked or not self.release.get("can_install") or self.world_checking:
            return
        if self.download:
            if self.on_install:
                self.on_install(self.download, self.selected_world())
        elif self.on_download:
            self.on_download(self.release)

    def close(self):
        if self.closed or self.installing:
            return
        if self.busy:
            self.close_requested = True
            self.message_key, self.progress_text = "cancelling", ""
            if self.on_cancel:
                self.on_cancel()
            self.render()
            return
        self.closed = True
        self.progress.stop()
        self.master.destroy()
        if self.on_close:
            self.on_close()
