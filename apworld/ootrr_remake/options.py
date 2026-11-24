"""Typed Archipelago options backed by the shared public settings catalogue."""
from dataclasses import make_dataclass
import Options as ap_options

from Options import (Choice, OptionGroup, OptionSet, PerGameCommonOptions, Range, Removed, Toggle,
                     random_weighted_range)

from .settings import OPTION_SPECS, default_options, validate_options
from .full_ap import full_option_specs, full_defaults, validate_full_options


class SteppedRange(Range):
    """Keep AP's random range syntax on the native slider's valid increments."""
    step = 1

    def __init__(self, value):
        super().__init__(value)
        if (value - self.range_start) % self.step:
            raise ValueError(f"{self.__class__.__name__} uses steps of {self.step} from {self.range_start}.")

    @classmethod
    def weighted_range(cls, text):
        style = text
        low, high = cls.range_start, cls.range_end
        if text.startswith("random-range-"):
            parts = text[len("random-range-"):].split("-")
            bias = parts.pop(0) if parts and parts[0] in {"low", "middle", "high"} else None
            if len(parts) != 2:
                raise ValueError("Invalid random range: " + text)
            low, high = sorted(map(int, parts))
            if low < cls.range_start or high > cls.range_end:
                raise ValueError("Random range is out of bounds: " + text)
            style = "random-" + bias if bias else "random"
        first = (low - cls.range_start + cls.step - 1) // cls.step
        last = (high - cls.range_start) // cls.step
        if first > last:
            raise ValueError("This range contains no valid native step: " + text)
        return cls(cls.range_start + cls.step * random_weighted_range(style, first, last))


class SteppedNumericChoice(Choice):
    """Actual numeric IDs keep every AP random roll on the native increments."""
    step = 1

    @classmethod
    def from_text(cls, text):
        # Retain AP's biased/range syntax as a convenience, while ordinary
        # "random" uses Choice's actual finite native values rather than
        # Range.random_range's arbitrary integer between the endpoints.
        if text.casefold().startswith('random-'):
            return SteppedRange.weighted_range.__func__(cls, text.casefold())
        return super().from_text(text)


def _option_type(spec):
    name = "".join(part.title() for part in spec["id"].split("_"))
    attrs = {"__module__": __name__, "__doc__": spec["description"],
             "display_name": spec["label"], "rich_text_doc": False}
    kind = spec["kind"]
    if kind == "choice":
        base = Choice
        # AP reserves "random" for choosing a complete option value. Keep the
        # native per-shop draw at its historical index behind an explicit key.
        attrs.update({"option_" + ("random_deals" if spec["id"] == "shuffle_shops" and value == "random" else value): index
                      for index, value in enumerate(spec["choices"])})
        attrs["default"] = spec["choices"].index(spec["default"])
    elif kind == "range":
        base = SteppedNumericChoice if spec["step"] > 1 else Range
        attrs.update(default=spec["default"], range_start=spec["min"], range_end=spec["max"], step=spec["step"])
        if spec['step'] > 1:
            attrs.update({'option_' + str(value): value
                          for value in range(spec['min'], spec['max'] + 1, spec['step'])})
    elif kind == "set":
        base = OptionSet
        attrs.update(default=frozenset(spec["default"]), valid_keys=frozenset(spec["choices"]))
    else:
        base = Toggle
        attrs["default"] = int(spec["default"])
    return type(name, (base,), attrs)


OPTION_TYPES = {spec["id"]: _option_type(spec) for spec in OPTION_SPECS}
FULL_OPTION_SPECS = tuple(spec for spec in full_option_specs() if spec["id"] != "death_link")
OPTION_TYPES.update({spec["id"]: _option_type(spec) for spec in FULL_OPTION_SPECS})
globals().update({option.__name__: option for option in OPTION_TYPES.values()})


class OOTRRSettingsRemoved(Removed):
    """The old free-text string is replaced by the individual settings below."""

    def __init__(self, value):
        if value:
            raise ValueError("ootrr_settings was replaced by individual YAML settings. "
                             "Create a new YAML with Create-YAML.cmd; existing .apootrr files still work.")
        super().__init__(value)


class KokiriShopChecksRemoved(Removed):
    """Use the native shop shuffle instead of the old foreign-only test option."""

    def __init__(self, value):
        # Removed.from_any stringifies YAML values before constructing us.
        disabled = value is None or value is False or value == 0 or (
            isinstance(value, str) and value.strip().casefold() in {"", "false", "off", "0", "none", "null"})
        if not disabled:
            raise ValueError("kokiri_shop_checks was a test option. Use shuffle_shops: random_deals or deals_1 "
                             "for AP deals across all shops, shuffle_shops: shuffle for ordinary shop goods, "
                             "or shuffle_shops: off to keep vanilla shops.")
        super().__init__("")


class TradeBonusRemoved(Removed):
    """New rooms replace the additive test-era trade rewards with full trades."""

    def __init__(self, value):
        disabled = value is None or value is False or value == 0 or (
            isinstance(value, str) and value.strip().casefold() in {"", "false", "off", "0", "none", "null"})
        if not disabled:
            raise ValueError("shuffle_trade_checks added bonus rewards. Replace it with adult_trade_shuffle: true "
                             "for quest-item replacement; existing generated rooms keep their legacy behavior.")
        super().__init__("")


RemakeOptions = make_dataclass(
    "RemakeOptions", [(name, option) for name, option in OPTION_TYPES.items()]
    + ([("start_inventory_from_pool", ap_options.StartInventoryPool)] if hasattr(ap_options, "StartInventoryPool") else [])
    + [("ootrr_settings", OOTRRSettingsRemoved), ("kokiri_shop_checks", KokiriShopChecksRemoved),
       ("shuffle_trade_checks", TradeBonusRemoved)], bases=(PerGameCommonOptions,),
    namespace={"__module__": __name__})

OPTION_GROUPS = [OptionGroup(group, [OPTION_TYPES[spec["id"]] for spec in OPTION_SPECS if spec["group"] == group],
                            start_collapsed=group == "Difficulty")
                 for group in dict.fromkeys(spec["group"] for spec in OPTION_SPECS)]
OPTION_GROUPS += [OptionGroup(group, [OPTION_TYPES[spec["id"]] for spec in FULL_OPTION_SPECS if spec["group"] == group],
                             start_collapsed=group != "Generation")
                  for group in dict.fromkeys(spec["group"] for spec in FULL_OPTION_SPECS)]


def full_option_values(options):
    """Read the dedicated full-mode fields, rejecting unnoticed native changes."""
    from .full_ap import translate_legacy_options
    values = full_defaults()
    for spec in full_option_specs():
        option = getattr(options, spec["id"], None)
        if option is None:
            continue
        values[spec["id"]] = (option.current_key if spec["kind"] == "choice" else
                              bool(option.value) if spec["kind"] == "toggle" else option.value)
    # Old YAML keys retain their old meaning. Translate deliberate changes where
    # an equivalent exists and report unsupported ones instead of ignoring them.
    changed = {}
    defaults = default_options()
    for spec in OPTION_SPECS:
        name = spec["id"]
        if name == "death_link":
            continue
        option = getattr(options, name, None)
        if option is None:
            continue
        value = option.current_key if spec["kind"] == "choice" else option.value
        if name == "shuffle_shops" and value == "random_deals":
            value = "random"
        if spec["kind"] == "toggle":
            value = bool(value)
        if spec["kind"] == "set":
            value = list(v for v in spec["choices"] if v in value)
        if value != defaults[name]:
            changed[name] = value
    return validate_full_options(translate_legacy_options(changed, values))


def _normalize_inactive_options(values):
    """Discard rolled sub-options whose native parent does not use them.

    Archipelago rolls each YAML option independently. Its options page cannot
    hide OOTRR's dependent controls, so their unused rolls must not invalidate
    an otherwise valid room. Active choices and progression options stay exact.
    """
    values = dict(values)
    defaults = default_options()

    def reset(*names):
        for name in names:
            values[name] = defaults[name]

    if values["bridge"] != "dungeons":
        reset("bridge_rewards")
    if values["skip_ganon_trials"]:
        reset("trials")
    if values["door_of_time_condition"] in {"open", "song"}:
        reset("door_of_time_song")
    else:
        reset("door_of_time_escape")
    if values["shuffle_ganon_bosskey"] != "lacs_dungeons":
        reset("lacs_rewards")
    if values["shuffle_shops"] not in {"deals_1", "deals_2", "deals_3", "deals_4", "random"}:
        reset("shopsanity_prices")
    if not (values["shuffle_scrubs_a"] or values["shuffle_scrubs_b"]):
        reset("scrub_prices", "scrub_hint_text")
    if values["shuffle_merchants"] == "off":
        reset("merchant_prices")
    for kind in ("scrub", "merchant", "fairy"):
        if values[kind + "_prices"] != "fixed":
            reset(kind + "_price_fixed")
    if values["shuffle_songs"] != "anywhere":
        reset("song_harp_colors")
    return values


def option_values(options):
    """Convert AP's rolled Choice/Toggle/Range/Set values to native JSON types."""
    values = default_options()
    for spec in OPTION_SPECS:
        name = spec["id"]
        option = getattr(options, name, None)
        if option is None:
            continue
        value = option.value
        if spec["kind"] == "choice":
            value = option.current_key
            if name == "shuffle_shops" and value == "random_deals":
                value = "random"
        elif spec["kind"] == "toggle":
            value = bool(value)
        values[name] = value
    return validate_options(_normalize_inactive_options(values))
