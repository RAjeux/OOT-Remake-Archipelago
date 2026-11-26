"""Typed settings editor for new AP rooms; no YAML parser or second schema."""
import copy
import re
import tkinter as tk
from tkinter import messagebox, ttk
import unicodedata

from .settings import OPTION_SPECS, default_options, validate_options
from .settings_labels import (GROUP_ORDER, active_reason, choice_description, choice_label,
                              description, group_label, is_advanced, is_french,
                              normalize_inactive, selection_summary, setting_label, validation_message)
from .ui_theme import apply_theme, COLORS


def search_text(value):
    """Match English/French text and YAML IDs without case or accent sensitivity."""
    return "".join(char for char in unicodedata.normalize("NFKD", str(value)).casefold()
                   if not unicodedata.combining(char)).replace("_", " ").replace("œ", "oe").replace("æ", "ae")


def window_size(screen_width, screen_height):
    """Leave room for window decorations and the desktop taskbar."""
    return min(1320, max(600, screen_width - 60)), min(880, max(440, screen_height - 100))


def setting_search_text(spec):
    text = [spec["id"], spec["group"]]
    for language in ("en", "fr"):
        text.extend((setting_label(spec["id"], language), description(spec["id"], language),
                     group_label(spec["group"], language)))
        for value in spec.get("choices", ()):
            text.extend((str(value), choice_label(spec["id"], value, language),
                         choice_description(spec["id"], value, language)))
    return search_text(" ".join(text))


class SettingsWindow:
    def __init__(self, master, values=None, language="en", on_apply=None):
        self.language = language
        self.on_apply = on_apply
        self.closed = False
        self.initial = validate_options({} if values is None else values)
        self.window = tk.Toplevel(master)
        apply_theme(self.window)
        self.window.title(self._text("OOT Remake — Archipelago settings", "OOT Remake — Réglages Archipelago"))
        width, height = window_size(self.window.winfo_screenwidth(), self.window.winfo_screenheight())
        self.window.geometry(f"{width}x{height}")
        self.window.minsize(min(820, width), min(500, height))
        self.window.transient(master)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Escape>", self._escape)
        self.window.bind("<Control-f>", self._focus_search)
        self.window.bind("<Control-Return>", lambda _event: self.apply())
        self.variables, self.controls, self.reasons = {}, {}, {}
        self.rows, self.group_ids = {}, []
        self.titles = {}
        self.fields = {}
        self._panel_mode = None
        self._compact_controls = None
        self.summary_expanded = False
        self.search_var = tk.StringVar(self.window)
        self.show_advanced = tk.BooleanVar(self.window, value=False)
        self.hide_inactive = tk.BooleanVar(self.window, value=True)
        self.current_group = "Shuffle"
        self._before_search_group = self.current_group
        self._searching = False
        self.filtered_names, self.visible_names = [], []
        self._draft_values = self.initial
        self._defaults = default_options()
        self._search_index = {spec["id"]: setting_search_text(spec) for spec in OPTION_SPECS}
        self._updating = False
        self._build()
        self._load_values(self.initial)
        self._select_group(self.group_ids.index("Shuffle"))
        self.window.grab_set()

    def _text(self, english, french):
        return french if is_french(self.language) else english

    def _build(self):
        self.outer = outer = ttk.Frame(self.window, padding=(22, 18))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(2, weight=1)
        self.header = header = ttk.Frame(outer)
        header.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 16))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text=self._text("Settings for a new room", "Réglages d'une nouvelle salle"),
                  style="App.Title.TLabel").grid(row=0, column=0, sticky="w")
        self.intro = ttk.Label(header, text=self._text(
            "Apply your choices, then save the YAML and generate a room. Existing player files and saves are unchanged.",
            "Applique tes choix, puis enregistre le YAML et génère une salle. Les fichiers joueur et sauvegardes existants ne changent pas."),
            wraplength=1100, style="App.Muted.TLabel")
        self.intro.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.toolbar = toolbar = ttk.Frame(outer)
        toolbar.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 16))
        toolbar.columnconfigure(0, weight=1)
        self.search_box = search = ttk.Frame(toolbar, style="App.Card.TFrame", padding=(12, 8))
        search.grid(row=0, column=0, sticky="ew")
        search.columnconfigure(1, weight=1)
        ttk.Label(search, text=self._text("Search", "Rechercher"), style="App.CardHeading.TLabel").grid(
            row=0, column=0, padx=(0, 12))
        self.search_entry = ttk.Entry(search, textvariable=self.search_var)
        self.search_entry.grid(row=0, column=1, sticky="ew", ipady=3)
        self.search_entry.bind("<Down>", self._focus_first_setting)
        ttk.Label(search, text="Ctrl+F", style="App.CardCaption.TLabel").grid(row=0, column=2, padx=12)
        ttk.Button(search, text=self._text("Clear", "Effacer"), style="App.Quiet.TButton",
                   command=lambda: self.search_var.set("")).grid(row=0, column=3)
        self.filters = filters = ttk.Frame(toolbar)
        filters.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        filters.columnconfigure(2, weight=1)
        self.advanced_button = ttk.Checkbutton(filters, variable=self.show_advanced,
            text=self._text("Show advanced options", "Afficher les options avancées"))
        self.advanced_button.grid(row=0, column=0, sticky="w")
        self.inactive_button = ttk.Checkbutton(filters, variable=self.hide_inactive,
            text=self._text("Hide inactive options", "Masquer les options inactives"))
        self.inactive_button.grid(row=0, column=1, sticky="w", padx=(18, 0))
        self.filter_note = ttk.Label(filters, style="App.Caption.TLabel")
        self.filter_note.grid(row=0, column=2, sticky="e")
        self.navigation = navigation = ttk.Frame(outer, style="App.Sidebar.TFrame", padding=(10, 14))
        navigation.grid(row=2, column=0, sticky="nsew", padx=(0, 18))
        navigation.rowconfigure(1, weight=1)
        navigation.columnconfigure(0, weight=1)
        self.category_label = ttk.Label(navigation, text=self._text("Categories", "Catégories"),
                                        background=COLORS["sidebar"], foreground=COLORS["muted"],
                                        font=("Segoe UI", 9, "bold"))
        self.category_label.grid(row=0, column=0, sticky="w", padx=8, pady=(0, 12))
        self.groups = tk.Listbox(navigation, exportselection=False, width=23, activestyle="none", height=9,
                                background=COLORS["sidebar"], foreground=COLORS["text"],
                                selectbackground=COLORS["gold"], selectforeground=COLORS["bg"],
                                borderwidth=0, highlightthickness=0, font=("Segoe UI", 11),
                                selectborderwidth=0)
        self.groups.grid(row=1, column=0, sticky="nsew")
        group_scroll = ttk.Scrollbar(navigation, orient="vertical", command=self.groups.yview)
        self.groups.configure(yscrollcommand=group_scroll.set)
        group_scroll.grid(row=1, column=1, sticky="ns", padx=(5, 0))
        self.groups.bind("<<ListboxSelect>>", self._group_changed)
        self.summary_toggle = ttk.Button(navigation, style="App.Nav.TButton", command=self._toggle_summary)
        self.content = content = ttk.Frame(outer)
        content.grid(row=2, column=1, sticky="nsew")
        content.rowconfigure(2, weight=1)
        content.columnconfigure(0, weight=1)
        self.heading = ttk.Label(content, style="App.Heading.TLabel")
        self.heading.grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.status = ttk.Label(content, style="App.Caption.TLabel")
        self.status.grid(row=1, column=0, sticky="w", pady=(0, 12))
        self.canvas = tk.Canvas(content, highlightthickness=0, borderwidth=0, background=COLORS["bg"])
        scrollbar = ttk.Scrollbar(content, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.grid(row=2, column=0, sticky="nsew")
        scrollbar.grid(row=2, column=1, sticky="ns", padx=(7, 0))
        self.body = ttk.Frame(self.canvas)
        self.body.columnconfigure(0, weight=1)
        self.canvas_item = self.canvas.create_window(0, 0, anchor="nw", window=self.body)
        self.body.bind("<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._resized)
        self.window.bind("<MouseWheel>", self._wheel, add="+")
        available_groups = list(dict.fromkeys(spec["group"] for spec in OPTION_SPECS))
        groups = [group for group in GROUP_ORDER if group in available_groups]
        groups.extend(group for group in available_groups if group not in groups)
        self.group_ids.append(None)
        for group in groups:
            self.group_ids.append(group)
        positions = {group: index for index, group in enumerate(self.group_ids)}
        ordered = sorted(enumerate(OPTION_SPECS), key=lambda pair: (positions[pair[1]["group"]], pair[0]))
        for index, (_original, spec) in enumerate(ordered):
            self._add_setting(index, spec)
        self.empty = ttk.Label(self.body, style="App.Muted.TLabel", wraplength=620, padding=(0, 20))
        self.empty.grid(row=len(OPTION_SPECS), column=0, sticky="ew")
        self.summary_box = ttk.Frame(outer, style="App.Card.TFrame", padding=(16, 14))
        self.summary_box.columnconfigure(0, weight=1)
        self.summary_heading = ttk.Label(self.summary_box,
            text=self._text("Your room at a glance", "Résumé de ta salle"), style="App.CardHeading.TLabel")
        self.summary_heading.grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.summary = ttk.Label(self.summary_box, wraplength=950, justify="left", style="App.CardMuted.TLabel", font=("Segoe UI", 9))
        self.summary.grid(row=1, column=0, sticky="ew")
        self.footer = buttons = ttk.Frame(outer)
        buttons.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(16, 0))
        buttons.columnconfigure(1, weight=1)
        ttk.Button(buttons, text=self._text("Reset to defaults", "Rétablir les valeurs par défaut"), style="App.Quiet.TButton",
                   command=lambda: self._load_values(default_options())).grid(row=0, column=0)
        ttk.Button(buttons, text=self._text("Cancel", "Annuler"), style="App.Quiet.TButton", command=self.close).grid(row=0, column=2, padx=(10, 8))
        self.apply_button = ttk.Button(buttons, text=self._text("Apply settings", "Appliquer les réglages"),
                                      style="App.Primary.TButton", command=self.apply)
        self.apply_button.grid(row=0, column=3)
        self.window.bind("<Configure>", self._layout_panels, add="+")
        self._layout_panels()
        self.search_var.trace_add("write", lambda *_args: self._filters_changed())
        self.show_advanced.trace_add("write", lambda *_args: self._filters_changed())
        self.hide_inactive.trace_add("write", lambda *_args: self._filters_changed())

    def _add_setting(self, index, spec):
        name, kind = spec["id"], spec["kind"]
        row = ttk.Frame(self.body, style="App.Card.TFrame", padding=(16, 14))
        row.grid(row=index, column=0, sticky="ew", pady=(0, 9))
        row.columnconfigure(0, weight=1)
        title = ttk.Label(row, text=setting_label(name, self.language), style="App.CardHeading.TLabel", wraplength=350)
        title.grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.titles[name] = title
        if kind == "toggle":
            var = tk.BooleanVar(self.window)
            control = ttk.Checkbutton(row, variable=var, style="App.Card.TCheckbutton",
                                      text=self._text("Enabled", "Activé"))
        elif kind == "choice":
            var = tk.StringVar(self.window)
            control = ttk.Combobox(row, textvariable=var, state="readonly", width=28,
                                   values=[choice_label(name, value, self.language) for value in spec["choices"]])
        elif kind == "range":
            var = tk.StringVar(self.window)
            control = ttk.Spinbox(row, textvariable=var, from_=spec["min"], to=spec["max"],
                                 increment=spec["step"], width=9)
        else:
            var = None
            field = ttk.Frame(row, style="App.Card.TFrame")
            field.columnconfigure(0, weight=1)
            control = tk.Listbox(field, selectmode="multiple", exportselection=False, height=7,
                                 width=28, activestyle="none", background=COLORS["elevated"],
                                 foreground=COLORS["text"], selectbackground=COLORS["gold"],
                                 selectforeground=COLORS["bg"], disabledforeground=COLORS["muted"],
                                 highlightbackground=COLORS["border"], highlightcolor=COLORS["gold"],
                                 highlightthickness=1, borderwidth=0, font=("Segoe UI", 10))
            scrollbar = ttk.Scrollbar(field, orient="vertical", command=control.yview)
            control.configure(yscrollcommand=scrollbar.set)
            control.grid(row=0, column=0, sticky="nsew")
            scrollbar.grid(row=0, column=1, sticky="ns")
            for value in spec["choices"]:
                control.insert(tk.END, choice_label(name, value, self.language))
            control.bind("<<ListboxSelect>>", lambda _event: self.update_dependencies())
        self.fields[name] = field if kind == "set" else control
        self.fields[name].grid(row=0, column=1, sticky="ne")
        help_text = description(name, self.language)
        if kind == "set":
            help_text += self._text(" Click each item to select or clear it.", " Clique sur chaque objet pour le sélectionner ou le retirer.")
        help_label = ttk.Label(row, text=help_text, wraplength=650, style="App.CardMuted.TLabel")
        help_label.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        reason = ttk.Label(row, wraplength=650, background=COLORS["surface"], foreground=COLORS["gold"])
        reason.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(3, 0))
        self.variables[name], self.controls[name], self.reasons[name] = var, control, reason
        self.rows[name] = (row, help_label, spec["group"])
        control.bind("<FocusIn>", lambda _event, name=name: self._reveal_control(name), add="+")
        if kind in {"choice", "range"}:
            # Scrolling the settings must not silently change a value beneath
            # the pointer. A combobox's open dropdown keeps its own list scroll.
            control.bind("<MouseWheel>", self._wheel)
        if var is not None:
            var.trace_add("write", lambda *_args: self.update_dependencies())

    def _resized(self, event):
        self.canvas.itemconfigure(self.canvas_item, width=event.width)
        compact = event.width < 610
        if compact != self._compact_controls:
            self._compact_controls = compact
            for name, (row, help_label, _group) in self.rows.items():
                self.fields[name].grid_configure(row=1 if compact else 0, column=0 if compact else 1,
                                                columnspan=2 if compact else 1,
                                                sticky="ew" if compact else "ne", pady=(10, 0) if compact else 0)
                help_label.grid_configure(row=2 if compact else 1)
                reason = self.reasons[name]
                shown = bool(reason.grid_info())
                reason.grid_configure(row=3 if compact else 2)
                if not shown:
                    reason.grid_remove()
        for _row, help_label, _group in self.rows.values():
            help_label.configure(wraplength=max(180, event.width - 38))
        for reason in self.reasons.values():
            reason.configure(wraplength=max(180, event.width - 38))
        for name, title in self.titles.items():
            title.configure(wraplength=max(150, event.width - (38 if compact else self.fields[name].winfo_reqwidth() + 52)))

    def _layout_panels(self, event=None):
        if event is not None and event.widget is not self.window:
            return
        width = self.window.winfo_width()
        height = self.window.winfo_height()
        if width < 10:
            width, height = map(int, self.window.geometry().split("+")[0].split("x"))
        wide = width >= 1200 and height >= 720
        compact_summary = height < 650
        mode = (wide, height < 680, compact_summary, self.summary_expanded)
        if mode != self._panel_mode:
            self._panel_mode = mode
            compact_height = height < 680
            self.outer.configure(padding=(18, 12) if compact_height else (22, 18))
            self.header.grid_configure(pady=(0, 10) if compact_height else (0, 16))
            self.intro.grid_remove() if compact_height else self.intro.grid()
            self.toolbar.grid_configure(pady=(0, 10) if compact_height else (0, 16))
            self.search_box.configure(padding=(10, 5) if compact_height else (12, 8))
            self.filters.grid_configure(pady=(6, 0) if compact_height else (10, 0))
            self.summary_box.configure(padding=(12, 8) if compact_height else (16, 14))
            self.summary_heading.grid_remove() if compact_height else self.summary_heading.grid()
            self.footer.grid_configure(pady=(10, 0) if compact_height else (16, 0))
            self.summary_box.grid_forget()
            if wide:
                self.outer.columnconfigure(2, minsize=278, weight=0)
                self.summary_box.grid(row=2, column=2, sticky="new", padx=(18, 0))
            else:
                self.outer.columnconfigure(2, minsize=0, weight=0)
                if not compact_summary or self.summary_expanded:
                    self.summary_box.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
            self.summary_toggle.configure(text=self._text(
                "Hide summary" if self.summary_expanded else "Show summary",
                "Masquer le résumé" if self.summary_expanded else "Afficher le résumé"))
            if compact_summary:
                self.summary_toggle.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
            else:
                self.summary_toggle.grid_remove()
            self.summary.configure(wraplength=246 if wide else max(300, width - 78))
            self.navigation.configure(padding=(8, 12) if width < 1000 else (10, 14))
            self.groups.configure(width=20 if width < 1000 else 23)
        self.intro.configure(wraplength=max(350, width - 60))
        self.filter_note.grid_configure(row=1 if width < 800 else 0,
                                       column=0 if width < 800 else 2,
                                       columnspan=3 if width < 800 else 1,
                                       sticky="w" if width < 800 else "e", pady=(6, 0) if width < 800 else 0)
        if not wide:
            self.summary.configure(wraplength=max(300, width - 78))

    def _toggle_summary(self):
        self.summary_expanded = not self.summary_expanded
        self._layout_panels()

    def _reveal_control(self, name):
        """Keyboard navigation keeps the focused setting inside the viewport."""
        if name not in self.visible_names:
            return
        self.window.update_idletasks()
        row = self.rows[name][0]
        top, height = self.canvas.canvasy(0), self.canvas.winfo_height()
        position, row_height = row.winfo_y(), row.winfo_height()
        if position < top:
            self.canvas.yview_moveto(position / max(1, self.body.winfo_height()))
        elif position + min(row_height, height) > top + height:
            self.canvas.yview_moveto((position + min(row_height, height) - height) / max(1, self.body.winfo_height()))

    def _focus_first_setting(self, _event=None):
        for name in self.visible_names:
            if str(self.controls[name].cget("state")) != "disabled":
                self.controls[name].focus_set()
                self._reveal_control(name)
                break
        return "break"

    def _wheel(self, event):
        if isinstance(event.widget, tk.Listbox):
            return
        self.canvas.yview_scroll(-int(event.delta / 120), "units")
        return "break"

    def _group_changed(self, _event=None):
        selection = self.groups.curselection()
        if selection and self.group_ids[selection[0]] != self.current_group:
            self._select_group(selection[0])

    def _select_group(self, index):
        self.current_group = self.group_ids[index]
        self._refresh_visibility(reset_scroll=True)

    def _escape(self, _event=None):
        if self.search_var.get():
            self.search_var.set("")
        else:
            self.close()
        return "break"

    def _focus_search(self, _event=None):
        self.search_entry.focus_set()
        self.search_entry.selection_range(0, tk.END)
        return "break"

    def _filters_changed(self):
        if not self.rows or self._updating:
            return
        searching = bool(self.search_var.get().strip())
        if searching and not self._searching:
            self._before_search_group = self.current_group
            self.current_group = None
        elif not searching and self._searching:
            self.current_group = self._before_search_group
        self._searching = searching
        self._refresh_visibility(reset_scroll=True)

    def _refresh_visibility(self, *, reset_scroll=False):
        words = search_text(self.search_var.get()).split()
        searching = bool(words)
        matching = []
        for spec in OPTION_SPECS:
            name = spec["id"]
            if words:
                if not all(word in self._search_index[name] for word in words):
                    continue
            elif ((not self.show_advanced.get() and is_advanced(name))
                  or (self.hide_inactive.get() and self.reasons[name].cget("text"))):
                continue
            matching.append(name)
        self.filtered_names = matching
        self.visible_names = [name for name in matching if self.current_group is None or self.rows[name][2] == self.current_group]
        visible = set(self.visible_names)
        self.groups.delete(0, tk.END)
        for group in self.group_ids:
            count = sum(group is None or self.rows[name][2] == group for name in matching)
            label = self._text("All settings", "Tous les réglages") if group is None else group_label(group, self.language)
            self.groups.insert(tk.END, f"{label} ({count})")
            if not count:
                self.groups.itemconfigure(tk.END, foreground=COLORS["muted"])
        selected = self.group_ids.index(self.current_group)
        self.groups.selection_set(selected)
        self.groups.activate(selected)
        title = self._text("Search results", "Résultats de recherche") if searching and self.current_group is None else (
            self._text("All settings", "Tous les réglages") if self.current_group is None else group_label(self.current_group, self.language))
        self.heading.configure(text=title)
        self.status.configure(text=self._text(
            f"{len(visible)} shown · {len(OPTION_SPECS)} settings available",
            f"{len(visible)} affichés · {len(OPTION_SPECS)} réglages disponibles"))
        for name, (row, _help, group) in self.rows.items():
            row.grid() if name in visible else row.grid_remove()
            label = setting_label(name, self.language)
            self.titles[name].configure(text=(group_label(group, self.language) + " · " + label
                                              if self.current_group is None else label))
        self.advanced_button.configure(state="disabled" if searching else "normal")
        self.inactive_button.configure(state="disabled" if searching else "normal")
        custom_hidden = sum(name not in matching and value != self._defaults[name]
                            for name, value in self._draft_values.items())
        note = self._text("Hidden values are retained", "Les valeurs masquées sont conservées")
        if custom_hidden:
            note = self._text(f"{custom_hidden} customized choices hidden", f"{custom_hidden} choix personnalisés masqués")
        self.filter_note.configure(text=self._text("Search includes every option", "Recherche dans toutes les options")
                                   if searching else note)
        if visible:
            self.empty.grid_remove()
        else:
            self.empty.configure(text=self._text(
                "No matching settings. Try an English or French name, or a YAML identifier." if searching else
                "No options match these filters. Show advanced options or turn off Hide inactive options.",
                "Aucun résultat. Essaie un nom en français ou en anglais, ou un identifiant YAML." if searching else
                "Aucune option avec ces filtres. Affiche les options avancées ou désactive le masquage des options inactives."))
            self.empty.grid()
        if reset_scroll:
            self.canvas.yview_moveto(0)

    def _set_value(self, spec, value):
        name = spec["id"]
        if spec["kind"] == "set":
            control = self.controls[name]
            previous = control.cget("state")
            control.configure(state="normal")
            control.selection_clear(0, tk.END)
            for index, item in enumerate(spec["choices"]):
                if item in value:
                    control.selection_set(index)
            control.configure(state=previous)
        elif spec["kind"] == "choice":
            self.variables[name].set(choice_label(name, value, self.language))
        else:
            self.variables[name].set(value)

    def _load_values(self, values):
        self._updating = True
        try:
            for spec in OPTION_SPECS:
                self._set_value(spec, values[spec["id"]])
        finally:
            self._updating = False
        self.update_dependencies()

    def _read_values(self, *, allow_invalid=False):
        values = {}
        self._last_invalid = None
        for spec in OPTION_SPECS:
            name, kind = spec["id"], spec["kind"]
            if kind == "set":
                value = [spec["choices"][index] for index in self.controls[name].curselection()]
            elif kind == "choice":
                labels = [choice_label(name, item, self.language) for item in spec["choices"]]
                value = spec["choices"][labels.index(self.variables[name].get())]
            elif kind == "range":
                value = self.variables[name].get()
                try:
                    value = int(value)
                except ValueError as error:
                    self._last_invalid = self._last_invalid or name
                    if not allow_invalid:
                        raise ValueError(setting_label(name, self.language) + self._text(" must be an integer.", " doit être un entier.")) from error
            else:
                value = self.variables[name].get()
            values[name] = value
        return values

    def update_dependencies(self):
        if self._updating:
            return
        try:
            values = self._read_values(allow_invalid=True)
        except (ValueError, tk.TclError):
            return
        normalized = normalize_inactive(values)
        self._draft_values = values
        self._updating = True
        try:
            for spec in OPTION_SPECS:
                name = spec["id"]
                reason = active_reason(name, normalized, self.language)
                state = "disabled" if reason else "readonly" if spec["kind"] == "choice" else "normal"
                self.controls[name].configure(state=state)
                self.reasons[name].configure(text=reason)
                self.reasons[name].grid() if reason else self.reasons[name].grid_remove()
                try:
                    help_text = choice_description(name, values[name], self.language)
                except (ValueError, TypeError):
                    help_text = description(name, self.language)
                if spec["kind"] == "set":
                    help_text += self._text(" Click to select or clear an item.", " Clique pour sélectionner ou retirer un élément.")
                self.rows[name][1].configure(text=help_text)
            try:
                self.summary.configure(text="\n".join(selection_summary(values, self.language)))
            except (ValueError, TypeError):
                self.summary.configure(text=self._text("Check the entered numbers before applying.", "Vérifie les nombres saisis avant d'appliquer."))
        finally:
            self._updating = False
        self._refresh_visibility()

    def selected_values(self):
        # Filtering and disabling never erase the editor's remembered choices.
        # Apply/export retains the existing normalization and native validation.
        normalized = normalize_inactive(self._read_values(allow_invalid=True))
        if self._last_invalid and not isinstance(normalized[self._last_invalid], str):
            self._last_invalid = None
        return validate_options(normalized)

    def apply(self):
        try:
            values = self.selected_values()
        except (ValueError, tk.TclError) as error:
            mentioned = re.search(r"\b(?:" + "|".join(re.escape(spec["id"]) for spec in OPTION_SPECS) + r")\b", str(error))
            name = self._last_invalid or next((spec["id"] for spec in OPTION_SPECS
                                               if str(error).startswith(spec["id"])), None) or (mentioned.group() if mentioned else None)
            if name:
                self.search_var.set("")
                self.show_advanced.set(True)
                self.hide_inactive.set(False)
                self._select_group(self.group_ids.index(self.rows[name][2]))
                self.controls[name].focus_set()
                self.window.update_idletasks()
                self.canvas.yview_moveto(self.rows[name][0].winfo_y() / max(1, self.body.winfo_height()))
            messagebox.showerror(self._text("Check settings", "Vérifier les réglages"),
                                 validation_message(error, self.language), parent=self.window)
            return
        if self.on_apply is not None:
            self.on_apply(copy.deepcopy(values))
        self.close()

    def close(self):
        if not self.closed:
            self.closed = True
            self.window.destroy()
