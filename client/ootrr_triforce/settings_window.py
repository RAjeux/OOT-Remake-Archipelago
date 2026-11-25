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


def search_text(value):
    """Match English/French text and YAML IDs without case or accent sensitivity."""
    return "".join(char for char in unicodedata.normalize("NFKD", str(value)).casefold()
                   if not unicodedata.combining(char)).replace("_", " ").replace("œ", "oe").replace("æ", "ae")


def window_size(screen_width, screen_height):
    """Leave room for window decorations and the desktop taskbar."""
    return min(1040, max(600, screen_width - 60)), min(800, max(440, screen_height - 100))


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
        self.window.title(self._text("OOT Remake — Archipelago settings", "OOT Remake — Réglages Archipelago"))
        width, height = window_size(self.window.winfo_screenwidth(), self.window.winfo_screenheight())
        self.window.geometry(f"{width}x{height}")
        self.window.minsize(min(880, width), min(650, height))
        self.window.transient(master)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Escape>", self._escape)
        self.window.bind("<Control-f>", self._focus_search)
        self.variables, self.controls, self.reasons = {}, {}, {}
        self.rows, self.group_ids = {}, []
        self.titles = {}
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
        outer = ttk.Frame(self.window, padding=18)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(3, weight=1)
        ttk.Label(outer, text=self._text("Settings for a new room", "Réglages d'une nouvelle salle"),
                  font=("Segoe UI", 16, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(outer, text=self._text(
            "Apply your choices, then save the YAML and generate a room. Existing player files and saves are unchanged.",
            "Applique tes choix, puis enregistre le YAML et génère une salle. Les fichiers joueur et sauvegardes existants ne changent pas."),
            wraplength=880).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 14))
        toolbar = ttk.Frame(outer)
        toolbar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        toolbar.columnconfigure(1, weight=1)
        ttk.Label(toolbar, text=self._text("Search", "Rechercher")).grid(row=0, column=0, padx=(0, 8))
        self.search_entry = ttk.Entry(toolbar, textvariable=self.search_var)
        self.search_entry.grid(row=0, column=1, sticky="ew")
        ttk.Button(toolbar, text=self._text("Clear", "Effacer"), command=lambda: self.search_var.set("")).grid(
            row=0, column=2, padx=(8, 0))
        filters = ttk.Frame(toolbar)
        filters.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.advanced_button = ttk.Checkbutton(filters, variable=self.show_advanced,
            text=self._text("Show advanced options", "Afficher les options avancées"))
        self.advanced_button.pack(side="left")
        self.inactive_button = ttk.Checkbutton(filters, variable=self.hide_inactive,
            text=self._text("Hide inactive options", "Masquer les options inactives"))
        self.inactive_button.pack(side="left", padx=(18, 0))
        self.filter_note = ttk.Label(filters, foreground="#555555")
        self.filter_note.pack(side="right")
        navigation = ttk.Frame(outer)
        navigation.grid(row=3, column=0, sticky="nsew", padx=(0, 15))
        navigation.rowconfigure(0, weight=1)
        navigation.columnconfigure(0, weight=1)
        self.groups = tk.Listbox(navigation, exportselection=False, width=25, activestyle="none", height=10)
        self.groups.grid(row=0, column=0, sticky="nsew")
        group_scroll = ttk.Scrollbar(navigation, orient="vertical", command=self.groups.yview)
        self.groups.configure(yscrollcommand=group_scroll.set)
        group_scroll.grid(row=0, column=1, sticky="ns")
        self.groups.bind("<<ListboxSelect>>", self._group_changed)
        content = ttk.Frame(outer)
        content.grid(row=3, column=1, sticky="nsew")
        content.rowconfigure(2, weight=1)
        content.columnconfigure(0, weight=1)
        self.heading = ttk.Label(content, font=("Segoe UI", 13, "bold"))
        self.heading.grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.status = ttk.Label(content, foreground="#555555")
        self.status.grid(row=1, column=0, sticky="w", pady=(0, 6))
        self.canvas = tk.Canvas(content, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(content, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.grid(row=2, column=0, sticky="nsew")
        scrollbar.grid(row=2, column=1, sticky="ns")
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
        self.empty = ttk.Label(self.body, foreground="#555555", wraplength=620, padding=(0, 20))
        self.empty.grid(row=len(OPTION_SPECS), column=0, sticky="ew")
        summary_box = ttk.LabelFrame(outer, text=self._text("Your room at a glance", "Résumé de ta salle"), padding=(12, 8))
        summary_box.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.summary = ttk.Label(summary_box, wraplength=950, justify="left")
        self.summary.pack(fill="x")
        buttons = ttk.Frame(outer)
        buttons.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        buttons.columnconfigure(1, weight=1)
        ttk.Button(buttons, text=self._text("Reset to defaults", "Rétablir les valeurs par défaut"),
                   command=lambda: self._load_values(default_options())).grid(row=0, column=0)
        ttk.Button(buttons, text=self._text("Cancel", "Annuler"), command=self.close).grid(row=0, column=2, padx=(10, 8))
        self.apply_button = ttk.Button(buttons, text=self._text("Apply settings", "Appliquer les réglages"), command=self.apply)
        self.apply_button.grid(row=0, column=3)
        self.search_var.trace_add("write", lambda *_args: self._filters_changed())
        self.show_advanced.trace_add("write", lambda *_args: self._filters_changed())
        self.hide_inactive.trace_add("write", lambda *_args: self._filters_changed())

    def _add_setting(self, index, spec):
        name, kind = spec["id"], spec["kind"]
        row = ttk.Frame(self.body, padding=(0, 8, 12, 12))
        row.grid(row=index, column=0, sticky="ew")
        row.columnconfigure(0, weight=1)
        title = ttk.Label(row, text=setting_label(name, self.language), font=("Segoe UI", 10, "bold"), wraplength=350)
        title.grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.titles[name] = title
        if kind == "toggle":
            var = tk.BooleanVar(self.window)
            control = ttk.Checkbutton(row, variable=var, text=self._text("Enabled", "Activé"))
        elif kind == "choice":
            var = tk.StringVar(self.window)
            control = ttk.Combobox(row, textvariable=var, state="readonly", width=33,
                                   values=[choice_label(name, value, self.language) for value in spec["choices"]])
        elif kind == "range":
            var = tk.StringVar(self.window)
            control = ttk.Spinbox(row, textvariable=var, from_=spec["min"], to=spec["max"],
                                 increment=spec["step"], width=9)
        else:
            var = None
            field = ttk.Frame(row)
            control = tk.Listbox(field, selectmode="multiple", exportselection=False, height=7,
                                 width=34, activestyle="none")
            scrollbar = ttk.Scrollbar(field, orient="vertical", command=control.yview)
            control.configure(yscrollcommand=scrollbar.set)
            control.grid(row=0, column=0, sticky="nsew")
            scrollbar.grid(row=0, column=1, sticky="ns")
            for value in spec["choices"]:
                control.insert(tk.END, choice_label(name, value, self.language))
            control.bind("<<ListboxSelect>>", lambda _event: self.update_dependencies())
        (field if kind == "set" else control).grid(row=0, column=1, sticky="ne")
        help_text = description(name, self.language)
        if kind == "set":
            help_text += self._text(" Click each item to select or clear it.", " Clique sur chaque objet pour le sélectionner ou le retirer.")
        help_label = ttk.Label(row, text=help_text, wraplength=650, foreground="#555555")
        help_label.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        reason = ttk.Label(row, wraplength=650, foreground="#805600")
        reason.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(3, 0))
        self.variables[name], self.controls[name], self.reasons[name] = var, control, reason
        self.rows[name] = (row, help_label, spec["group"])
        if kind in {"choice", "range"}:
            # Scrolling the settings must not silently change a value beneath
            # the pointer. A combobox's open dropdown keeps its own list scroll.
            control.bind("<MouseWheel>", self._wheel)
        if var is not None:
            var.trace_add("write", lambda *_args: self.update_dependencies())

    def _resized(self, event):
        self.canvas.itemconfigure(self.canvas_item, width=event.width)
        for _row, help_label, _group in self.rows.values():
            help_label.configure(wraplength=max(320, event.width - 28))
        for reason in self.reasons.values():
            reason.configure(wraplength=max(320, event.width - 28))
        for name, title in self.titles.items():
            title.configure(wraplength=max(170, event.width - self.controls[name].winfo_reqwidth() - 42))
        self.summary.configure(wraplength=max(600, self.window.winfo_width() - 70))

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
                self.groups.itemconfigure(tk.END, foreground="#777777")
        self.groups.selection_set(self.group_ids.index(self.current_group))
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
