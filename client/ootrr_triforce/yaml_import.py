"""Read player YAMLs without rolling weights or discarding settings on export.

The typed editor is only a projection. The imported document remains the
authority for every untouched option, including Archipelago common options.
"""
from dataclasses import dataclass, field
import copy
from datetime import date, datetime
import json
import math
from pathlib import Path
import re

import yaml

from .catalog import GAME
from .feature_settings import QUARANTINED_DEFAULTS, validate_mapping
from .settings import (FIXED_SETTINGS, SPEC_BY_ID, ap_choice_key, default_options,
                       native_choice_key, validate_options)
from .settings_labels import normalize_inactive

MAX_BYTES = 2 << 20
MAX_NODES = 30000
MAX_DEPTH = 40
COMMON_OPTIONS = frozenset({
    "progression_balancing", "accessibility", "local_items", "non_local_items",
    "start_inventory", "start_inventory_from_pool", "start_hints", "start_location_hints",
    "exclude_locations", "priority_locations", "item_links", "plando_items", "plando_texts",
    "plando_connections", "__requires_versions",
})
REMOVED = frozenset({"kokiri_shop_checks", "shuffle_trade_checks", *QUARANTINED_DEFAULTS})


class YamlImportError(ValueError):
    def __init__(self, code, detail=""):
        self.code, self.detail = code, detail
        super().__init__(detail or code)


@dataclass(frozen=True)
class ImportNotice:
    code: str
    key: str = ""
    detail: str = ""


@dataclass
class ImportedYaml:
    name: str
    values: dict
    document: dict
    preserved_options: dict
    warnings: tuple
    removed_options: dict = field(default_factory=dict)
    legacy_settings: str | None = None
    source: Path | None = None
    invalid_options: dict = field(default_factory=dict)

    @property
    def requires_review(self):
        """Only actual compatibility changes need an explicit review."""
        return any(notice.code == "legacy_unsupported" or notice.code == "removed" and
                   not _disabled(self.removed_options[notice.key]) for notice in self.warnings)


class _Loader(yaml.SafeLoader):
    """Bound composition and reject ambiguous or executable input."""

    def __init__(self, stream):
        super().__init__(stream)
        self._count, self._depth = 0, 0

    def compose_node(self, parent, index):
        self._count += 1
        self._depth += 1
        try:
            if self._count > MAX_NODES or self._depth > MAX_DEPTH:
                raise YamlImportError("format", "The YAML structure is too large or too deeply nested.")
            return super().compose_node(parent, index)
        finally:
            self._depth -= 1

    def construct_mapping(self, node, deep=False):
        if not isinstance(node, yaml.MappingNode):
            raise YamlImportError("format", "Expected a YAML mapping.")
        seen = set()
        for key_node, _value in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                raise YamlImportError("format", "YAML merge keys are not supported; expand the merged settings first.")
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, (str, int, float, bool, type(None))):
                raise YamlImportError("format", "YAML mapping keys must be scalar values.")
            if (key in seen or isinstance(key, str) and (
                    "+"+key in seen or key.startswith("+") and key[1:] in seen)):
                raise YamlImportError("duplicate_key", str(key))
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


class _Dumper(yaml.SafeDumper):
    def ignore_aliases(self, _data):
        return True


def _bounded(value):
    count = 0
    active = set()
    def visit(node, depth):
        nonlocal count
        count += 1
        if count > MAX_NODES or depth > MAX_DEPTH:
            raise YamlImportError("format", "The expanded YAML structure is too large.")
        if isinstance(node, (dict, list, set)):
            if id(node) in active:
                raise YamlImportError("format", "Recursive YAML aliases are not supported.")
            active.add(id(node))
            if isinstance(node, dict):
                for key, item in node.items():
                    visit(key, depth + 1)
                    visit(item, depth + 1)
            else:
                for item in node:
                    visit(item, depth + 1)
            active.remove(id(node))
        elif not isinstance(node, (str, bytes, int, float, bool, date, datetime, type(None))):
            raise YamlImportError("format", "This YAML value type is not supported.")
        elif isinstance(node, float) and not math.isfinite(node):
            raise YamlImportError("format", "Non-finite YAML numbers are not supported.")
    visit(value, 0)


def _player_name(value):
    if not isinstance(value, str):
        raise YamlImportError("name", "The player name must be text.")
    value = value.strip()
    if not value or len(value) > 16 or value == "Archipelago" or any(ord(c) < 32 for c in value):
        raise YamlImportError("name", "Choose a player name of 1 to 16 characters other than Archipelago.")
    return value


def _disabled(value):
    return value is None or value is False or value == 0 or (
        isinstance(value, str) and value.strip().casefold() in {"", "false", "off", "0", "none", "null"})


def _typed(name, value):
    """Validate one value without guessing its dependent settings."""
    spec = SPEC_BY_ID[name]
    kind = spec["kind"]
    if kind == "toggle":
        if isinstance(value, str):
            normalized = value.strip().casefold()
            if normalized in {"true", "on", "yes", "1", "enabled"}:
                return True
            if normalized in {"false", "off", "no", "0", "disabled", "none", "null"}:
                return False
        if isinstance(value, (bool, int, float)):
            return bool(int(value))
        raise ValueError(name + " must be true or false.")
    if kind == "choice":
        if isinstance(value, str):
            value = native_choice_key(name, value.strip().casefold())
            if value in {"false", "true"}:
                alias = "off" if value == "false" else "on"
                if alias in spec["choices"]:
                    value = alias
        elif isinstance(value, bool):
            alias = "on" if value else "off"
            value = alias if alias in spec["choices"] else None
        elif type(value) is int and 0 <= value < len(spec["choices"]):
            value = spec["choices"][int(value)]
        if not isinstance(value, str) or value not in spec["choices"]:
            raise ValueError(name + " has an unsupported choice.")
        return value
    if kind == "range":
        if isinstance(value, str):
            value = value.strip().casefold()
            aliases = {"default": spec["default"], "low": spec["min"], "high": spec["max"]}
            if spec["min"] == 0 and spec["default"] != 0:
                aliases.update(true=spec["default"], false=0)
            if value in aliases:
                value = aliases[value]
            elif re.fullmatch(r"-?\d+", value):
                value = int(value)
        elif isinstance(value, bool) and spec["min"] == 0 and spec["default"] != 0:
            value = spec["default"] if value else 0
        if (type(value) is not int or not spec["min"] <= value <= spec["max"]
                or (value-spec["min"]) % spec["step"]):
            raise ValueError(name + " has an unsupported numeric value.")
        return value
    if kind == "set":
        if isinstance(value, str):
            value = [part.strip() for part in value.split(",") if part.strip()]
        if isinstance(value, dict):
            value = list(value)
        if not isinstance(value, (list, tuple, set)) or any(item not in spec["choices"] for item in value):
            raise ValueError(name + " contains unsupported entries.")
        return [item for item in spec["choices"] if item in value]
    return validate_mapping(name, value)


def _random(name, value):
    if not isinstance(value, str):
        return False
    value = value.strip().casefold()
    if value == "random" and SPEC_BY_ID[name]["kind"] in {"choice", "range", "toggle", "set"}:
        return True
    spec = SPEC_BY_ID[name]
    if spec["kind"] not in {"range", "set"}:
        return False
    if value in {"random-low", "random-middle", "random-high"}:
        return True
    match = re.fullmatch(r"random-range-(?:(low|middle|high)-)?(-?\d+)-(-?\d+)", value)
    if not match:
        return False
    low, high = sorted(map(int, match.group(2, 3)))
    minimum, maximum, step = ((0, len(spec["choices"]), 1) if spec["kind"] == "set"
                              else (spec["min"], spec["max"], spec["step"]))
    return minimum <= low <= high <= maximum and any(
        (number-minimum) % step == 0 for number in range(low, min(high, low+step)+1))


def _value(name, raw):
    """Return a deterministic value or None for a valid AP random selection."""
    spec = SPEC_BY_ID[name]
    if _random(name, raw):
        return None
    if spec["kind"] not in {"set", "dict"} and isinstance(raw, (list, dict)):
        if isinstance(raw, dict):
            if not raw:
                return copy.deepcopy(spec["default"])
            try:
                weights = {value: int(weight) for value, weight in raw.items()}
            except (ValueError, TypeError, OverflowError) as error:
                raise ValueError(name + " has invalid weights.") from error
            if any(weight < 0 for weight in weights.values()) or not any(weight > 0 for weight in weights.values()):
                raise ValueError(name + " has invalid weights.")
            options = [value for value, weight in weights.items() if weight]
        else:
            options = raw
        if not options:
            raise ValueError(name + " has no available choices.")
        values = [None if _random(name, value) else _typed(name, value) for value in options]
        return values[0] if len(values) == 1 else None
    return _typed(name, raw)


def _decode_legacy(text):
    from .engine import run_engine
    return json.loads(run_engine("settings", {"settings": text}))["settings"]


def _projection(options, notices):
    defaults = default_options()
    values, preserved, invalid = copy.deepcopy(defaults), {}, {}
    for name, raw in options.items():
        if name not in SPEC_BY_ID:
            if name not in COMMON_OPTIONS:
                preserved[name] = copy.deepcopy(raw)
                notices.append(ImportNotice("unknown", name))
            continue
        try:
            value = _value(name, raw)
        except (TypeError, ValueError) as error:
            value = None
            invalid[name] = str(error)
        if value is None:
            preserved[name] = copy.deepcopy(raw)
            notices.append(ImportNotice("preserved", name, invalid.get(name, "Archipelago random selection")))
        else:
            values[name] = value
    normalized = normalize_inactive(values)
    for name in values:
        if normalized[name] != values[name] and name in options:
            preserved[name] = copy.deepcopy(options[name])
            notices.append(ImportNotice("projection", name, "Inactive imported value is preserved on export."))
    values = normalized
    # An old invalid combination must not prevent editing another field. Keep
    # its raw options opaque, with a valid editor baseline and a visible notice.
    for _ in range(len(SPEC_BY_ID)+1):
        try:
            return validate_options(values), preserved, invalid
        except ValueError as error:
            changed = [name for name in values if values[name] != defaults[name]]
            involved = [name for name in changed if re.search(r"\b"+re.escape(name)+r"\b", str(error))]
            reset = involved or changed
            if not reset:
                raise YamlImportError("settings", str(error)) from error
            for name in reset:
                values[name] = copy.deepcopy(defaults[name])
                if name in options:
                    preserved[name] = copy.deepcopy(options[name])
                    notices.append(ImportNotice("projection", name, str(error)))
    raise YamlImportError("settings", "The imported settings could not be projected into the editor.")


def parse_yaml(text, *, decoder=None):
    if isinstance(text, bytes):
        if len(text) > MAX_BYTES:
            raise YamlImportError("too_large")
        try:
            text = text.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise YamlImportError("syntax", "The YAML must use UTF-8 text.") from error
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_BYTES:
        raise YamlImportError("too_large")
    loader = _Loader(text.lstrip("\ufeff"))
    root_node = None
    try:
        root_node = loader.get_single_node()
        document = loader.construct_document(root_node) if root_node is not None else None
    except YamlImportError:
        raise
    except yaml.constructor.ConstructorError as error:
        raise YamlImportError("unsupported_tag", str(error)) from error
    except (yaml.YAMLError, RecursionError, ValueError, OverflowError, TypeError) as error:
        raise YamlImportError("syntax", str(error)) from error
    finally:
        loader.dispose()
    _bounded(document)
    if not isinstance(document, dict) or any(not isinstance(key, str) for key in document):
        raise YamlImportError("format", "A player YAML must contain one top-level mapping with text keys.")
    game = document.get("game")
    if isinstance(game, dict) and game and all(type(weight) is int and weight >= 0 for weight in game.values()):
        positive = [name for name, weight in game.items() if weight]
        game = positive[0] if positive == [GAME] else None
    if game != GAME:
        raise YamlImportError("game", GAME)
    name = _player_name(document.get("name"))
    original = document.get(GAME)
    if not isinstance(original, dict) or any(not isinstance(key, str) for key in original):
        raise YamlImportError("format", "The OOT Remake settings must be a mapping with text keys.")
    document = copy.deepcopy(document)
    # Deepcopy alone retains aliases. Detach this block before migrating it.
    options = copy.deepcopy(original)
    document[GAME] = options
    notices, removed, legacy = [], {}, None
    if "ootrr_settings" in options:
        raw = options.pop("ootrr_settings")
        removed["ootrr_settings"] = copy.deepcopy(raw)
        if not _disabled(raw):
            if not isinstance(raw, str) or not raw.startswith("OOTRR1-") or len(raw) > 65536:
                raise YamlImportError("legacy", "The legacy settings string is not supported.")
            try:
                decoded = (decoder or _decode_legacy)(raw)
                if not isinstance(decoded, dict):
                    raise ValueError("The legacy decoder did not return settings.")
                _bounded(decoded)
            except Exception as error:
                raise YamlImportError("legacy", str(error)) from error
            legacy = raw
            for key, value in decoded.items():
                if key in SPEC_BY_ID:
                    if key not in options:
                        options[key] = ap_choice_key(key, value) if SPEC_BY_ID[key]["kind"] == "choice" else copy.deepcopy(value)
                elif key not in FIXED_SETTINGS or value != FIXED_SETTINGS[key]:
                    notices.append(ImportNotice("legacy_unsupported", key, repr(value)))
                    removed.setdefault(key, copy.deepcopy(value))
            notices.append(ImportNotice("legacy_migrated", "ootrr_settings"))
    for key in REMOVED:
        if key in options:
            raw = options.pop(key)
            removed[key] = copy.deepcopy(raw)
            notices.append(ImportNotice("removed", key, repr(raw)))
    values, preserved, invalid = _projection(options, notices)
    return ImportedYaml(name, values, document, preserved, tuple(notices), removed, legacy,
                        invalid_options=invalid)


def load_yaml(path, *, decoder=None):
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise YamlImportError("too_large")
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES+1)
    result = parse_yaml(raw, decoder=decoder)
    result.source = path
    return result


def _ap_inactive(values):
    """Match the generator's inactive resets, not the GUI's broader helpers.

    A parity test extracts apworld/options.py's authoritative normalizer without
    importing Archipelago. In particular, invalid active dependencies such as
    open Kakariko with a closed forest must remain errors at export.
    """
    result = copy.deepcopy(values)
    defaults = default_options()
    def reset(*names):
        for name in names:
            result[name] = copy.deepcopy(defaults[name])
    if result["bridge"] != "dungeons": reset("bridge_rewards")
    if result["bridge"] != "medallions": reset("bridge_medallions")
    if result["shuffle_ganon_bosskey"] != "lacs_medallions": reset("lacs_medallions")
    if result["skulls_by_day"]: reset("night_skulls_suns_song")
    if result["cosmetic_color_mode"] != "custom": reset("cosmetic_colors")
    if not result["shuffle_ice_traps"]: reset("ice_trap_count")
    if result["skip_ganon_trials"]: reset("trials")
    if result["door_of_time_condition"] in {"open", "song"}: reset("door_of_time_song")
    else: reset("door_of_time_escape")
    if result["shuffle_ganon_bosskey"] != "lacs_dungeons": reset("lacs_rewards")
    if result["shuffle_shops"] not in {"deals_1", "deals_2", "deals_3", "deals_4", "random"}: reset("shopsanity_prices")
    if not(result["shuffle_scrubs_a"] or result["shuffle_scrubs_b"]): reset("scrub_prices", "scrub_hint_text")
    if result["shuffle_merchants"] == "off": reset("merchant_prices")
    for kind in ("scrub", "merchant", "fairy"):
        if result[kind+"_prices"] != "fixed": reset(kind+"_price_fixed")
    if result["shuffle_songs"] != "anywhere": reset("song_harp_colors")
    return result


def render_imported_yaml(imported, name, values, language="en", changed_keys=None):
    """Replace edited settings only; leave advanced selections unrolled."""
    name = _player_name(name)
    if not isinstance(imported, ImportedYaml):
        raise YamlImportError("format", "Expected an imported player YAML.")
    try:
        given = dict(values)
        selected = validate_options(dict(imported.values, **given))
    except (ValueError, TypeError) as error:
        raise YamlImportError("settings", str(error)) from error
    changed = ({key for key in given if selected[key] != imported.values[key]}
               if changed_keys is None else set(changed_keys))
    if any(key not in SPEC_BY_ID for key in changed):
        raise YamlImportError("settings", "An unknown setting was edited.")
    unresolved = set(imported.invalid_options)-changed
    if unresolved:
        raise YamlImportError("settings", "Review unsupported imported values: "+", ".join(sorted(unresolved)))
    result = copy.deepcopy(imported.document)
    result["name"] = name
    options = copy.deepcopy(result[GAME])
    result[GAME] = options
    for key in changed:
        value = copy.deepcopy(selected[key])
        options[key] = ap_choice_key(key, value) if SPEC_BY_ID[key]["kind"] == "choice" else value
    _bounded(result)
    # Check a deterministic exported combination, using AP's inactive semantics.
    concrete = default_options()
    for key, raw in options.items():
        if key not in SPEC_BY_ID:
            continue
        try:
            value = _value(key, raw)
        except (ValueError, TypeError) as error:
            raise YamlImportError("settings", str(error)) from error
        if value is None:
            break
        concrete[key] = value
    else:
        try:
            validate_options(_ap_inactive(concrete))
        except ValueError as error:
            raise YamlImportError("settings", str(error)) from error
    french = str(language).lower().replace("_", "-").startswith("fr")
    heading = ("# Configuration importée : les réglages non modifiés sont conservés.\n" if french else
               "# Imported configuration: untouched settings are preserved.\n")
    if imported.legacy_settings:
        heading += "# Original OOTRR settings: " + imported.legacy_settings + "\n"
    rendered = heading + yaml.dump(result, Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=100)
    if len(rendered.encode("utf-8")) > MAX_BYTES:
        raise YamlImportError("too_large")
    return rendered
