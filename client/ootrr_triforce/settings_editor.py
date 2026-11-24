"""Schema-driven player settings, lossless AP import and the desktop editor.

The document keeps Archipelago's common options and weighted values when only
game settings are edited. Parsing never imports a player file as Python code.
"""
from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import Path
import queue
import threading

from .catalog import GAME
from .i18n import tr
from .save_bridge import atomic
from . import settings


MAX_DOCUMENT = 2 << 20
MODES = ("full_network", "legacy")


class ConfigurationError(ValueError):
    """A configuration cannot be represented or safely exported."""


def validate_name(name):
    if (not isinstance(name, str) or not name.strip() or len(name.strip()) > 16
            or name.strip() == "Archipelago" or any(ord(char) < 32 for char in name)):
        raise ConfigurationError("Choose a name of 1 to 16 characters other than Archipelago.")
    return name.strip()


def specs_for(mode):
    if mode == "full_network":
        from .full_ap import full_option_specs
        return tuple(deepcopy(spec) for spec in full_option_specs() if spec["id"] != "generation_mode")
    if mode != "legacy":
        raise ConfigurationError("Unknown generation mode.")
    return tuple(deepcopy(spec) for spec in settings.OPTION_SPECS)


def available_modes():
    try:
        from .full_ap import full_option_specs
    except ImportError:
        return ("legacy",)
    return MODES


def _external_value(name, value):
    # AP reserves 'random' for choosing the complete option, unlike the old
    # engine's name for a varying number of special deals.
    return "random_deals" if name == "shuffle_shops" and value == "random" else deepcopy(value)


def _internal_value(name, value):
    return "random" if name == "shuffle_shops" and value == "random_deals" else value


def defaults_for(mode):
    return {spec["id"]: _external_value(spec["id"], spec["default"]) for spec in specs_for(mode)}


def _simple_value(spec, value):
    name, kind = spec["id"], spec["kind"]
    # Both a whole-option random roll and weighted AP values remain intact.
    if value == "random" and kind not in {"set", "items", "dict"}:
        return value
    if value in ("random-low", "random-high", "random-middle") and kind == "range":
        return value
    if isinstance(value, dict):
        if not value or any(type(weight) is not int or weight < 0 for weight in value.values()) or not any(value.values()):
            raise ConfigurationError("Weighted settings need non-negative integer weights and at least one positive weight.")
        for choice in value:
            candidate = choice
            if kind == "range":
                try:
                    candidate = int(choice)
                except (TypeError, ValueError):
                    raise ConfigurationError(name + ": invalid weighted value.") from None
            elif kind == "toggle" and choice in ("true", "false"):
                candidate = choice == "true"
            _simple_value(spec, candidate)
        return deepcopy(value)
    if kind == "toggle":
        if type(value) is not bool:
            raise ConfigurationError(name + " must be true or false.")
    elif kind == "choice":
        allowed = tuple(_external_value(name, choice) for choice in spec["choices"])
        if value not in allowed:
            raise ConfigurationError(name + ": unsupported choice.")
    elif kind == "range":
        if (type(value) is not int or not spec["min"] <= value <= spec["max"]
                or (value - spec["min"]) % spec.get("step", 1)):
            raise ConfigurationError(name + ": outside the supported range.")
    elif kind == "set":
        if not isinstance(value, (list, tuple)) or any(item not in spec["choices"] for item in value):
            raise ConfigurationError(name + ": unsupported list value.")
        value = list(dict.fromkeys(value))
    elif kind in {"items", "dict"}:
        if not isinstance(value, dict):
            raise ConfigurationError(name + ": expected an object.")
    else:
        raise ConfigurationError(name + ": unsupported setting type.")
    return deepcopy(value)


def _bounded_tree(value, *, depth=0, seen=None, budget=None):
    """Reject recursive YAML aliases, excessive nesting and custom objects."""
    if depth > 25:
        raise ConfigurationError("The configuration is nested too deeply.")
    seen = set() if seen is None else seen
    budget = [100000] if budget is None else budget
    budget[0] -= 1
    if budget[0] < 0:
        raise ConfigurationError("The configuration contains too many entries.")
    if isinstance(value, (dict, list)):
        if id(value) in seen:
            raise ConfigurationError("Recursive YAML aliases are not supported.")
        if len(value) > 10000:
            raise ConfigurationError("The configuration contains too many entries.")
        seen.add(id(value))
        children = value.items() if isinstance(value, dict) else enumerate(value)
        for key, child in children:
            if not isinstance(key, (str, int, float, bool, type(None))):
                raise ConfigurationError("The configuration has an unsupported key.")
            _bounded_tree(child, depth=depth + 1, seen=seen, budget=budget)
        seen.remove(id(value))
    elif not isinstance(value, (str, int, float, bool, type(None))):
        raise ConfigurationError("The configuration has an unsupported value.")


def _bounded_yaml_nodes(node, *, depth=0, seen=None, budget=None):
    """Bound aliases before SafeLoader expands merge mappings during construction."""
    from yaml.nodes import MappingNode, SequenceNode
    if depth > 25:
        raise ConfigurationError("The configuration is nested too deeply.")
    seen = set() if seen is None else seen
    budget = [100000] if budget is None else budget
    budget[0] -= 1
    if budget[0] < 0:
        raise ConfigurationError("The configuration contains too many entries.")
    if not isinstance(node, (MappingNode, SequenceNode)):
        return
    if id(node) in seen:
        raise ConfigurationError("Recursive YAML aliases are not supported.")
    if len(node.value) > 10000:
        raise ConfigurationError("The configuration contains too many entries.")
    seen.add(id(node))
    for value in node.value:
        children = value if isinstance(node, MappingNode) else (value,)
        for child in children:
            _bounded_yaml_nodes(child, depth=depth + 1, seen=seen, budget=budget)
    seen.remove(id(node))


def _parse(text, suffix):
    if len(text.encode("utf-8")) > MAX_DOCUMENT:
        raise ConfigurationError("The configuration is too large.")
    try:
        if suffix.lower() == ".json":
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ConfigurationError("Duplicate configuration keys are not supported.")
                    result[key] = value
                return result
            result = json.loads(text, object_pairs_hook=unique)
        else:
            import yaml
            class UniqueLoader(yaml.SafeLoader):
                pass
            def mapping(loader, node, deep=False):
                explicit = set()
                for key_node, _value_node in node.value:
                    if key_node.tag == "tag:yaml.org,2002:merge":
                        continue
                    key = loader.construct_object(key_node, deep=deep)
                    try:
                        duplicate = key in explicit
                        explicit.add(key)
                    except TypeError:
                        raise ConfigurationError("The configuration has an unsupported key.") from None
                    if duplicate:
                        raise ConfigurationError("Duplicate configuration keys are not supported.")
                # YAML merge defaults are intentional: explicit keys override
                # merged mappings without counting as duplicate source keys.
                loader.flatten_mapping(node)
                return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)
            UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
            loader = UniqueLoader(text)
            try:
                node = loader.get_single_node()
                _bounded_yaml_nodes(node)
                result = loader.construct_document(node) if node is not None else None
            finally:
                loader.dispose()
    except ConfigurationError:
        raise
    except ImportError:
        raise ConfigurationError("YAML support is missing. Download the complete application again.") from None
    except (ValueError, RecursionError) as error:
        raise ConfigurationError("The configuration could not be read.") from error
    except Exception as error:
        # PyYAML's exceptions carry arbitrary source lines, including user data.
        # The UI reports a fixed message; developer logs can preserve the cause.
        raise ConfigurationError("The configuration could not be read.") from error
    _bounded_tree(result)
    if not isinstance(result, dict):
        raise ConfigurationError("Choose a single Archipelago player configuration.")
    return result


@dataclass
class PlayerConfiguration:
    name: str = "Link"
    mode: str = "legacy"
    values: dict = field(default_factory=dict)
    common: dict = field(default_factory=dict)

    @classmethod
    def new(cls, mode=None, name="Link"):
        mode = mode or available_modes()[0]
        return cls(validate_name(name), mode, defaults_for(mode), {})

    @classmethod
    def read(cls, path):
        path = Path(path)
        if path.stat().st_size > MAX_DOCUMENT:
            raise ConfigurationError("The configuration is too large.")
        with path.open("rb") as stream:
            raw = stream.read(MAX_DOCUMENT + 1)
        if len(raw) > MAX_DOCUMENT:
            raise ConfigurationError("The configuration is too large.")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeError:
            raise ConfigurationError("The configuration could not be read.") from None
        source = _parse(text, path.suffix)
        if source.get("game") != GAME or not isinstance(source.get(GAME), dict):
            raise ConfigurationError("Choose an Ocarina of Time Remake player configuration.")
        mode = source[GAME].get("generation_mode", "legacy")
        if mode not in available_modes():
            raise ConfigurationError("Unknown generation mode.")
        values = deepcopy(source[GAME])
        values.pop("generation_mode", None)
        result = cls(validate_name(source.get("name")), mode, values,
                     {key: deepcopy(value) for key, value in source.items() if key not in {"name", "game", GAME}})
        result.validate()
        return result

    def validate(self):
        self.name = validate_name(self.name)
        specs = {spec["id"]: spec for spec in specs_for(self.mode)}
        values = {**defaults_for(self.mode), **deepcopy(self.values)}
        for name, spec in specs.items():
            values[name] = _simple_value(spec, values[name])
        # Validate dependencies when the document contains concrete values.
        # AP itself resolves weighted/random values during generation.
        concrete = {key: values[key] for key in specs}
        dynamic = any(isinstance(value, dict) or value in ("random", "random-low", "random-high", "random-middle")
                      for value in concrete.values() if not isinstance(value, list))
        if not dynamic:
            try:
                if self.mode == "legacy":
                    settings.validate_options({key: _internal_value(key, value) for key, value in concrete.items()})
                else:
                    from .full_ap import validate_full_options
                    validate_full_options(concrete)
            except ValueError as error:
                raise ConfigurationError(str(error)) from None
        self.values = values
        return self

    def apply(self, updates):
        result = deepcopy(self)
        result.values.update(deepcopy(updates))
        result.validate()
        self.values = result.values

    def preset(self, name):
        values = defaults_for(self.mode)
        if name not in {"standard", "maximum_ap", "quick_start"}:
            raise ConfigurationError("Unknown preset.")
        if name != "standard":
            if self.mode == "legacy":
                values.update(shuffle_rewards="supported", shuffle_skulltulas="matched",
                              shuffle_shops="random_deals", adult_trade_shuffle=True,
                              shuffle_master_sword=True)
                if name == "quick_start":
                    values.update(open_forest="open", open_kakariko="open", faster_chests=True, skip_intro=True)
            else:
                choices = {spec["id"]: spec for spec in specs_for(self.mode)}
                requested = {"full_shuffle_npc_gifts": True, "full_shuffle_boss_rewards": True,
                             "full_shuffle_great_fairies": True, "full_shuffle_quest_rewards": True,
                             "full_shuffle_pots": "all", "full_shuffle_crates": "all",
                             "full_shuffle_beehives": True, "full_shuffle_bushes": True,
                             "full_shuffle_rocks": True, "full_shuffle_trees": True,
                             "full_shuffle_freestanding_items": "all", "full_tokensanity": "all",
                             "full_shopsanity": "all", "full_shuffle_scrubs": "low",
                             "full_shuffle_song_items": "everywhere", "full_shuffle_master_sword": True,
                             "full_shuffle_gerudo_card": True}
                if name == "quick_start":
                    requested.update(full_open_forest=True, full_fast_chests=True, full_skip_child_zelda=True)
                for key, value in requested.items():
                    if key in choices:
                        _simple_value(choices[key], value)
                        values[key] = value
        known = {spec["id"] for spec in specs_for(self.mode)}
        values.update({key: deepcopy(value) for key, value in self.values.items() if key not in known})
        result = PlayerConfiguration(self.name, self.mode, values, deepcopy(self.common)).validate()
        self.values = result.values

    def as_mapping(self):
        self.validate()
        block = deepcopy(self.values)
        # An explicit mode prevents a future default change from silently
        # converting an imported legacy configuration.
        block["generation_mode"] = self.mode
        return {**deepcopy(self.common), "name": self.name, "game": GAME, GAME: block}

    def dumps(self, suffix=".yaml"):
        mapping = self.as_mapping()
        if suffix.lower() == ".json":
            return json.dumps(mapping, ensure_ascii=False, indent=2) + "\n"
        import yaml
        return ("# OOT Remake Archipelago player configuration.\n"
                "# Generate the room with Archipelago and the other players' YAML files.\n"
                + "name: " + json.dumps(mapping.pop("name"), ensure_ascii=False) + "\n"
                + yaml.safe_dump(mapping, allow_unicode=True, sort_keys=False, width=100))

    def write(self, path):
        path = Path(path)
        atomic(path, self.dumps(path.suffix).encode("utf-8"))


class SettingsEditorWindow:
    """A modal editor driven by the same schema used for generation."""
    def __init__(self, master, document, *, language="en", on_apply=None, dialogs=None):
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
        self.tk, self.ttk, self.messagebox = tk, ttk, messagebox
        self.master, self.language, self.on_apply = master, language, on_apply
        self.dialogs = dialogs or filedialog
        self.document = deepcopy(document)
        self.variables = {}
        self.closed = False
        self.importing, self.import_after = False, None
        self.import_results = queue.Queue()
        self.import_controls = []
        self.master.title(self.text("Player settings"))
        self.master.geometry("850x730")
        self.master.minsize(680, 500)
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(2, weight=1)
        bar = ttk.Frame(master, padding=16)
        bar.grid(row=0, column=0, sticky="ew")
        ttk.Label(bar, text=self.text("Generation mode")).grid(row=0, column=0, sticky="w")
        self.mode_ids = available_modes()
        self.mode = tk.StringVar()
        modes = self.mode_choice = ttk.Combobox(bar, textvariable=self.mode,
            values=tuple(self.text("Full network" if mode == "full_network" else "Legacy OOTRR") for mode in self.mode_ids),
            state="readonly", width=19)
        modes.current(self.mode_ids.index(self.document.mode))
        modes.grid(row=0, column=1, padx=(8, 20))
        modes.bind("<<ComboboxSelected>>", self.change_mode)
        ttk.Label(bar, text=self.text("Preset")).grid(row=0, column=2)
        self.preset_ids = ("standard", "maximum_ap", "quick_start")
        self.preset_var = tk.StringVar()
        preset = self.preset_choice = ttk.Combobox(bar, textvariable=self.preset_var,
            values=tuple(self.text(label) for label in ("Standard", "Maximum AP", "Quick start")), state="readonly", width=17)
        preset.current(0)
        preset.grid(row=0, column=3, padx=8)
        ttk.Button(bar, text=self.text("Apply preset"), command=self.apply_preset).grid(row=0, column=4)
        ttk.Label(master, text=self.text("Random and weighted values are preserved. Archipelago resolves them when generating the room."),
                  wraplength=790, padding=(16, 0, 16, 10)).grid(row=1, column=0, sticky="ew")
        self.body = ttk.Frame(master, padding=(16, 0))
        self.body.grid(row=2, column=0, sticky="nsew")
        self.body.columnconfigure(0, weight=1)
        self.body.rowconfigure(0, weight=1)
        actions = ttk.Frame(master, padding=16)
        actions.grid(row=3, column=0, sticky="ew")
        actions.columnconfigure(2, weight=1)
        ttk.Button(actions, text=self.text("Import configuration…"), command=self.import_document).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text=self.text("Export JSON…"), command=self.export_json).grid(row=0, column=1)
        ttk.Button(actions, text=self.text("Cancel"), command=self.close).grid(row=0, column=3, padx=8)
        ttk.Button(actions, text=self.text("Apply settings"), command=self.apply).grid(row=0, column=4)
        self.error = ttk.Label(master, foreground="#a52323", wraplength=790, padding=(16, 0, 16, 12))
        self.error.grid(row=4, column=0, sticky="ew")
        self.master.protocol("WM_DELETE_WINDOW", self.close)
        self.master.bind("<Escape>", lambda _event: self.close())
        self.render()

    def text(self, message, **values):
        return tr(message, language=self.language, **values)

    def render(self):
        for child in self.body.winfo_children():
            child.destroy()
        notebook = self.ttk.Notebook(self.body)
        notebook.grid(sticky="nsew")
        groups, self.variables = {}, {}
        for spec in specs_for(self.document.mode):
            group = spec.get("group", "Settings")
            if group not in groups:
                tab = self.ttk.Frame(notebook)
                tab.columnconfigure(0, weight=1)
                tab.rowconfigure(0, weight=1)
                canvas = self.tk.Canvas(tab, highlightthickness=0)
                scrollbar = self.ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
                canvas.configure(yscrollcommand=scrollbar.set)
                canvas.grid(row=0, column=0, sticky="nsew")
                scrollbar.grid(row=0, column=1, sticky="ns")
                form = self.ttk.Frame(canvas, padding=(8, 8, 18, 12))
                form.columnconfigure(0, weight=1)
                window = canvas.create_window((0, 0), window=form, anchor="nw")
                form.bind("<Configure>", lambda _event, c=canvas: c.configure(scrollregion=c.bbox("all")))
                canvas.bind("<Configure>", lambda event, c=canvas, w=window: c.itemconfigure(w, width=event.width))
                canvas.bind("<MouseWheel>", lambda event, c=canvas: c.yview_scroll(-int(event.delta / 120), "units"))
                notebook.add(tab, text=self.text(group))
                groups[group] = (form, 0)
            form, row = groups[group]
            value = self.document.values.get(spec["id"], _external_value(spec["id"], spec["default"]))
            self.ttk.Label(form, text=self.text(spec.get("label", spec["id"].replace("_", " ").title())),
                           font=("Segoe UI", 10, "bold")).grid(row=row, column=0, sticky="w", pady=(10, 3))
            description = self.text(spec.get("description", ""))
            if spec["kind"] == "range":
                description += " " + self.text("Range: {minimum}–{maximum}, step {step}.", minimum=spec["min"], maximum=spec["max"], step=spec.get("step", 1))
            self.ttk.Label(form, text=description, wraplength=700).grid(row=row + 1, column=0, sticky="ew", pady=(0, 5))
            encoded = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
            variable = self.tk.StringVar(value=encoded)
            self.variables[spec["id"]] = variable
            if spec["kind"] in {"choice", "toggle"}:
                choices = ("false", "true") if spec["kind"] == "toggle" else tuple(_external_value(spec["id"], c) for c in spec["choices"])
                widget = self.ttk.Combobox(form, textvariable=variable, values=(*choices, "random"))
            elif spec["kind"] == "set":
                widget = self.ttk.Frame(form)
                widget.columnconfigure(0, weight=1)
                self.ttk.Entry(widget, textvariable=variable, state="readonly").grid(row=0, column=0, sticky="ew")
                self.ttk.Button(widget, text=self.text("Choose…"),
                    command=lambda s=spec, v=variable: self.choose_set(s, v)).grid(row=0, column=1, padx=(8, 0))
            else:
                widget = self.ttk.Entry(form, textvariable=variable)
            widget.grid(row=row + 2, column=0, sticky="ew")
            groups[group] = (form, row + 3)

    def collect(self):
        values = {}
        for spec in specs_for(self.document.mode):
            raw = self.variables[spec["id"]].get().strip()
            if raw == "random" or raw in {"random-low", "random-high", "random-middle"}:
                value = raw
            elif raw.startswith("{") or spec["kind"] in {"toggle", "range", "set", "items", "dict"}:
                try:
                    value = json.loads(raw)
                except ValueError:
                    raise ConfigurationError(spec["id"] + ": invalid value.") from None
            else:
                value = raw
            values[spec["id"]] = value
        self.document.apply(values)
        return self.document

    def change_mode(self, _event=None):
        if self.importing:
            return
        old = self.document
        known = {spec["id"] for spec in specs_for(old.mode)}
        self.document = PlayerConfiguration.new(self.mode_ids[self.mode_choice.current()], old.name)
        self.document.common = deepcopy(old.common)
        self.document.values.update({key: deepcopy(value) for key, value in old.values.items() if key not in known})
        self.error.configure(text="")
        self.render()

    def apply_preset(self):
        if self.importing:
            return
        try:
            self.document.preset(self.preset_ids[self.preset_choice.current()])
        except ConfigurationError as error:
            self.error.configure(text=self.text(str(error)))
            return
        self.error.configure(text="")
        self.render()

    def import_document(self):
        if self.importing:
            return
        path = self.dialogs.askopenfilename(parent=self.master, title=self.text("Import configuration…"),
            filetypes=((self.text("Player configuration"), "*.yaml *.yml *.json"),))
        if path:
            self.importing = True
            self.error.configure(text=self.text("Reading the configuration…"))
            def disable(parent):
                for child in parent.winfo_children():
                    if isinstance(child, (self.ttk.Entry, self.ttk.Combobox, self.ttk.Button)):
                        self.import_controls.append((child, child.cget("state")))
                        child.configure(state="disabled")
                    disable(child)
            disable(self.master)
            results = self.import_results
            def read():
                try:
                    results.put(PlayerConfiguration.read(path))
                except Exception:
                    results.put(None)
            threading.Thread(target=read, name="Player configuration import", daemon=True).start()
            self.import_after = self.master.after(40, self.receive_import)

    def receive_import(self):
        if self.closed:
            return
        try:
            result = self.import_results.get_nowait()
        except queue.Empty:
            self.import_after = self.master.after(40, self.receive_import)
            return
        self.importing, self.import_after = False, None
        for widget, state in self.import_controls:
            if widget.winfo_exists():
                widget.configure(state=state)
        self.import_controls = []
        if result is None:
            self.error.configure(text=self.text("The configuration could not be read."))
            return
        self.document = result
        self.mode_choice.current(self.mode_ids.index(self.document.mode))
        self.error.configure(text="")
        self.render()

    def export_json(self):
        if self.importing:
            return
        try:
            self.collect()
        except ConfigurationError as error:
            self.error.configure(text=self.text(str(error)))
            return
        path = self.dialogs.asksaveasfilename(parent=self.master, title=self.text("Export JSON…"),
            defaultextension=".json", initialfile="Player-" + self.document.name + ".json", filetypes=(("JSON", "*.json"),))
        if path:
            try:
                self.document.write(path)
            except (OSError, ConfigurationError):
                self.error.configure(text=self.text("The configuration could not be saved."))

    def apply(self):
        if self.importing:
            return
        try:
            self.collect()
        except ConfigurationError as error:
            self.error.configure(text=self.text(str(error)))
            return
        if self.on_apply:
            self.on_apply(deepcopy(self.document))
        self.close()

    def close(self):
        if not self.closed:
            self.closed = True
            if self.import_after:
                self.master.after_cancel(self.import_after)
            self.master.destroy()

    def choose_set(self, spec, variable):
        dialog = self.tk.Toplevel(self.master)
        dialog.transient(self.master)
        dialog.grab_set()
        dialog.title(self.text(spec.get("label", spec["id"])))
        dialog.geometry("480x560")
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)
        canvas = self.tk.Canvas(dialog, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        scroll = self.ttk.Scrollbar(dialog, orient="vertical", command=canvas.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scroll.set)
        pane = self.ttk.Frame(canvas, padding=16)
        window = canvas.create_window((0, 0), window=pane, anchor="nw")
        pane.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
        try:
            selected = json.loads(variable.get())
        except ValueError:
            selected = []
        choices = {}
        for row, value in enumerate(spec["choices"]):
            choices[value] = self.tk.BooleanVar(value=value in selected)
            self.ttk.Checkbutton(pane, text=self.text(value.replace("_", " ").title()),
                variable=choices[value]).grid(row=row, column=0, sticky="w", pady=3)
        def apply():
            variable.set(json.dumps([value for value in spec["choices"] if choices[value].get()], ensure_ascii=False))
            dialog.destroy()
        self.ttk.Button(dialog, text=self.text("Apply selection"), command=apply).grid(row=1, column=0, columnspan=2, pady=14)
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
