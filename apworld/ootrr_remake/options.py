"""Typed Archipelago options backed by the shared public settings catalogue."""
from dataclasses import make_dataclass

from Options import (Choice, OptionGroup, OptionSet, PerGameCommonOptions, Range, Removed, Toggle,
                     random_weighted_range)

from .settings import OPTION_SPECS, default_options, validate_options


class SteppedRange(Range):
    """Keep AP's random range syntax on the native slider's valid increments."""
    step = 1

    def __init__(self, value):
        super().__init__(value)
        if (value - self.range_start) % self.step:
            raise ValueError(f"{self.__class__.__name__} utilise des pas de {self.step} depuis {self.range_start}.")

    @classmethod
    def weighted_range(cls, text):
        style = text
        low, high = cls.range_start, cls.range_end
        if text.startswith("random-range-"):
            parts = text[len("random-range-"):].split("-")
            bias = parts.pop(0) if parts and parts[0] in {"low", "middle", "high"} else None
            if len(parts) != 2:
                raise ValueError("Plage aléatoire invalide : " + text)
            low, high = sorted(map(int, parts))
            if low < cls.range_start or high > cls.range_end:
                raise ValueError("Plage aléatoire hors limites : " + text)
            style = "random-" + bias if bias else "random"
        first = (low - cls.range_start + cls.step - 1) // cls.step
        last = (high - cls.range_start) // cls.step
        if first > last:
            raise ValueError("Cette plage ne contient aucun palier natif : " + text)
        return cls(cls.range_start + cls.step * random_weighted_range(style, first, last))


def _option_type(spec):
    name = "".join(part.title() for part in spec["id"].split("_"))
    attrs = {"__module__": __name__, "__doc__": spec["description"],
             "display_name": spec["label"], "rich_text_doc": False}
    kind = spec["kind"]
    if kind == "choice":
        base = Choice
        attrs.update({"option_" + value: index for index, value in enumerate(spec["choices"])})
        attrs["default"] = spec["choices"].index(spec["default"])
    elif kind == "range":
        base = SteppedRange if spec["step"] > 1 else Range
        attrs.update(default=spec["default"], range_start=spec["min"], range_end=spec["max"], step=spec["step"])
    elif kind == "set":
        base = OptionSet
        attrs.update(default=frozenset(spec["default"]), valid_keys=frozenset(spec["choices"]))
    else:
        base = Toggle
        attrs["default"] = int(spec["default"])
    return type(name, (base,), attrs)


OPTION_TYPES = {spec["id"]: _option_type(spec) for spec in OPTION_SPECS}
globals().update({option.__name__: option for option in OPTION_TYPES.values()})


class OOTRRSettingsRemoved(Removed):
    """The old free-text string is replaced by the individual settings below."""

    def __init__(self, value):
        if value:
            raise ValueError("ootrr_settings a été remplacé par les réglages YAML individuels. "
                             "Recrée le YAML avec Creer-YAML.cmd ; les anciens .apootrr restent utilisables.")
        super().__init__(value)


RemakeOptions = make_dataclass(
    "RemakeOptions", [(name, option) for name, option in OPTION_TYPES.items()]
    + [("ootrr_settings", OOTRRSettingsRemoved)], bases=(PerGameCommonOptions,),
    namespace={"__module__": __name__})

OPTION_GROUPS = [OptionGroup(group, [OPTION_TYPES[spec["id"]] for spec in OPTION_SPECS if spec["group"] == group],
                            start_collapsed=group == "Difficulty")
                 for group in dict.fromkeys(spec["group"] for spec in OPTION_SPECS)]


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
        elif spec["kind"] == "toggle":
            value = bool(value)
        values[name] = value
    return validate_options(values)
