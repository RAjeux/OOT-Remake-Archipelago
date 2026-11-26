"""A small update review window; filesystem and network work belongs to services."""
import tkinter as tk
from tkinter import ttk
import re
import webbrowser

from .i18n import tr
from .ui_theme import COLORS, apply_theme, draw_brand, set_window_icon


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
    "notes": "Release notes",
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
        self.style = apply_theme(master)
        set_window_icon(master)
        master.title(self.text("title"))
        screen_width, screen_height = master.winfo_screenwidth(), master.winfo_screenheight()
        master.geometry(f"{min(800, max(640, screen_width - 100))}x{min(740, max(540, screen_height - 120))}")
        master.minsize(620, min(560, max(460, screen_height - 120)))
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        pane = ttk.Frame(master, padding=(28, 24, 28, 20))
        pane.grid(sticky="nsew")
        pane.columnconfigure(0, weight=1)
        pane.rowconfigure(1, weight=1)

        header = ttk.Frame(pane)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        header.columnconfigure(1, weight=1)
        brand = tk.Canvas(header, width=40, height=46, background=COLORS["bg"], highlightthickness=0)
        brand.grid(row=0, column=0, rowspan=2, padx=(0, 16), sticky="n")
        draw_brand(brand, 2, 2, 36)
        ttk.Label(header, text="OOT REMAKE / ARCHIPELAGO", style="App.Eyebrow.TLabel").grid(row=0, column=1, sticky="w")
        self.heading = ttk.Label(header, style="App.Heading.TLabel")
        self.heading.grid(row=1, column=1, sticky="w", pady=(3, 0))
        self.intro = ttk.Label(header, style="App.Muted.TLabel", wraplength=680)
        self.intro.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(14, 0))

        content = ttk.Frame(pane)
        content.grid(row=1, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(content, background=COLORS["bg"], highlightthickness=0, borderwidth=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(content, orient="vertical", command=self.canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(10, 0))
        self.canvas.configure(yscrollcommand=scrollbar.set)
        body = ttk.Frame(self.canvas)
        body.columnconfigure(0, weight=1)
        self.body_item = self.canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._resize_body)
        self.canvas.bind("<MouseWheel>", self._scroll)

        summary = ttk.Frame(body, style="App.Card.TFrame", padding=20)
        summary.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        summary.columnconfigure(0, weight=1)
        self.version = ttk.Label(summary, style="App.CardHeading.TLabel", wraplength=640)
        self.version.grid(row=0, column=0, sticky="ew")
        self.notes_section = ttk.Frame(summary, style="App.Card.TFrame")
        self.notes_section.grid(row=1, column=0, sticky="ew", pady=(18, 0))
        self.notes_section.columnconfigure(0, weight=1)
        self.notes_heading = ttk.Label(self.notes_section, style="App.CardCaption.TLabel")
        self.notes_heading.grid(row=0, column=0, sticky="w", pady=(0, 8))
        notes_box = ttk.Frame(self.notes_section, style="App.Inset.TFrame", padding=12)
        notes_box.grid(row=1, column=0, sticky="ew")
        notes_box.columnconfigure(0, weight=1)
        self.notes = tk.Text(notes_box, height=6, width=1, wrap="word", state="disabled", relief="flat",
                             background=COLORS["elevated"], foreground=COLORS["text"],
                             selectbackground=COLORS["gold"], selectforeground=COLORS["bg"],
                             insertbackground=COLORS["mint"], highlightthickness=0, borderwidth=0,
                             font=("Segoe UI", 10), spacing1=3, spacing3=5, padx=2, pady=2, exportselection=False)
        self.notes.grid(row=0, column=0, sticky="nsew")
        notes_scroll = ttk.Scrollbar(notes_box, orient="vertical", command=self.notes.yview)
        notes_scroll.grid(row=0, column=1, sticky="ns", padx=(10, 0))
        self.notes.configure(yscrollcommand=notes_scroll.set)
        self._set_notes(release.get("notes", ""))

        world_box = ttk.Frame(body, style="App.Card.TFrame", padding=20)
        world_box.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        world_box.columnconfigure(0, weight=1)
        self.world = ttk.Checkbutton(world_box, variable=self.want_world, style="App.Card.TCheckbutton")
        self.world.grid(row=0, column=0, sticky="w")
        self.folder_label = ttk.Label(world_box, style="App.CardCaption.TLabel")
        self.folder_label.grid(row=1, column=0, sticky="w", pady=(18, 6))
        folders = ttk.Frame(world_box, style="App.Card.TFrame")
        folders.grid(row=2, column=0, sticky="ew")
        folders.columnconfigure(0, weight=1)
        self.folder = ttk.Combobox(folders, textvariable=self.target, values=tuple(map(str, targets)), state="readonly")
        self.folder.grid(row=0, column=0, sticky="ew")
        self.folder.bind("<<ComboboxSelected>>", lambda _event: self.on_target(self.target.get()) if self.on_target else None)
        self.browse = ttk.Button(folders, command=lambda: self.on_target(None) if self.on_target else None,
                                 style="App.Quiet.TButton")
        self.browse.grid(row=0, column=1, padx=(10, 0))
        self.world_note = ttk.Label(world_box, style="App.CardMuted.TLabel", wraplength=640)
        self.world_note.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.source_note = ttk.Label(body, style="App.Muted.TLabel", wraplength=680)
        self.source_note.grid(row=2, column=0, sticky="ew", pady=(0, 8))

        actions = ttk.Frame(pane)
        actions.grid(row=2, column=0, sticky="ew", pady=(16, 0))
        actions.columnconfigure(1, weight=1)
        self.status = ttk.Label(actions, style="App.Caption.TLabel", wraplength=680)
        self.status.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 10))
        self.progress = ttk.Progressbar(actions, maximum=100)
        self.progress.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(0, 14))
        self.release_button = ttk.Button(actions, command=lambda: webbrowser.open(release["release_url"]), style="App.Quiet.TButton")
        self.release_button.grid(row=2, column=0, sticky="w")
        self.close_button = ttk.Button(actions, command=self.close, style="App.Quiet.TButton")
        self.close_button.grid(row=2, column=2, padx=(10, 10))
        self.primary = ttk.Button(actions, command=self.proceed, style="App.Primary.TButton")
        self.primary.grid(row=2, column=3)
        self._bind_wheel(body)
        master.bind("<Configure>", self._resize_window, add="+")
        master.protocol("WM_DELETE_WINDOW", self.close)
        master.bind("<Escape>", lambda _event: self.close())
        self.render()

    def _set_notes(self, notes):
        notes = notes.strip() if isinstance(notes, str) else ""
        self.notes.configure(state="normal")
        self.notes.delete("1.0", "end")
        self.notes.insert("1.0", notes)
        self.notes.tag_configure("link", foreground=COLORS["mint"], underline=True)
        for index, match in enumerate(re.finditer(r"https?://[^\s<>]+", notes)):
            url = match.group().rstrip(".,;:)]}")
            tag = "url_" + str(index)
            start = "1.0+" + str(match.start()) + "c"
            end = "1.0+" + str(match.start() + len(url)) + "c"
            self.notes.tag_add("link", start, end)
            self.notes.tag_add(tag, start, end)
            self.notes.tag_bind(tag, "<Button-1>", lambda _event, url=url: webbrowser.open(url))
            self.notes.tag_bind(tag, "<Enter>", lambda _event: self.notes.configure(cursor="hand2"))
            self.notes.tag_bind(tag, "<Leave>", lambda _event: self.notes.configure(cursor="xterm"))
        self.notes.configure(state="disabled")
        if not notes:
            self.notes_section.grid_remove()

    def _resize_body(self, event):
        self.canvas.itemconfigure(self.body_item, width=event.width)
        for label in (self.version, self.world_note):
            label.configure(wraplength=max(260, event.width - 40))

    def _resize_window(self, event):
        if not self.closed and event.widget is self.master:
            width = max(280, event.width - 56)
            for label in (self.intro, self.source_note, self.status):
                label.configure(wraplength=width)

    def _bind_wheel(self, widget):
        widget.bind("<FocusIn>", self._reveal_focus, add="+")
        if not isinstance(widget, (tk.Text, ttk.Combobox)):
            widget.bind("<MouseWheel>", self._scroll, add="+")
            widget.bind("<Button-4>", self._scroll, add="+")
            widget.bind("<Button-5>", self._scroll, add="+")
        for child in widget.winfo_children():
            self._bind_wheel(child)

    def _reveal_focus(self, event):
        extent = self.canvas.bbox("all")
        height = self.canvas.winfo_height()
        if not extent or height <= 1:
            return
        top = event.widget.winfo_rooty() - self.canvas.winfo_rooty()
        bottom = top + event.widget.winfo_height()
        offset = top - 8 if top < 8 else bottom - height + 8 if bottom > height - 8 else 0
        if offset:
            self.canvas.yview_moveto(max(0, self.canvas.canvasy(0) + offset) / max(extent[3], height))

    def _scroll(self, event):
        if self.canvas.bbox("all") and self.canvas.bbox("all")[3] > self.canvas.winfo_height():
            delta = -1 if getattr(event, "num", None) == 4 else 1 if getattr(event, "num", None) == 5 else (-1 if event.delta > 0 else 1)
            self.canvas.yview_scroll(delta * 3, "units")
            return "break"

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
                            (self.source_note, "source"), (self.release_button, "release"), (self.notes_heading, "notes")):
            widget.configure(text=self.text(key))
        self.version.configure(text=self.text("version", current=self.release["current_version"], latest=self.release["latest_version"]))
        note = "world_checking" if self.world_checking else "world_failed" if self.world_failed else (
            "world_changed" if self.world_status.get("changed") else "world_current" if self.world_status else "world_choose")
        self.world_note.configure(text=self.text(note), foreground=COLORS["danger"] if self.world_failed else
                                  COLORS["gold"] if self.world_status.get("changed") else COLORS["muted"])
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
        self.status.configure(text=self.progress_text or (self.text(self.message_key) if self.message_key else ""),
                              foreground=COLORS["danger"] if self.message_key == "failed" else
                              COLORS["mint"] if self.message_key == "ready" else COLORS["muted"])
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
