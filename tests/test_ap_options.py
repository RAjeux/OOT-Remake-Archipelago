"""Exercise AP's reserved Choice contract, including its unoptimized sources.

The portable checks always enforce Archipelago's external reserved-key contract.
Set AP_SOURCE to the official Archipelago 0.6.8 checkout (Options.py/Generate.py)
to also execute its actual classes and generator functions with optimize=0.
Only unrelated common-option/import dependencies are replaced for that probe.

Primary contract: https://github.com/ArchipelagoMW/Archipelago/blob/0.6.8/Options.py
Generator: https://github.com/ArchipelagoMW/Archipelago/blob/0.6.8/Generate.py
"""
import argparse
import ast
import dataclasses
import importlib.util
import json
import os
from pathlib import Path
import random
import sys
import types
import typing
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce import settings
from ootrr_triforce.catalog import GAME


class ReservedChoiceMeta(type):
    """AP's public Choice restrictions, independent of this world's catalogue."""
    def __new__(mcs, name, bases, attrs):
        options = {key[7:].lower(): value for key, value in attrs.items() if key.startswith("option_")}
        aliases = {key[6:].lower(): value for key, value in attrs.items() if key.startswith("alias_")}
        if "random" in options or "random" in aliases:
            raise AssertionError("Archipelago reserves random for choosing an option.")
        if len(options) != len(set(options.values())):
            raise AssertionError("Archipelago Choice IDs must be distinct.")
        inherited = {key: value for base in bases for key, value in getattr(base, "options", {}).items()}
        inherited.update(options)
        attrs["name_lookup"] = {value: key for key, value in inherited.items()}
        attrs["options"] = {**inherited, **aliases}
        attrs["aliases"] = aliases
        return super().__new__(mcs, name, bases, attrs)


class ContractChoice(metaclass=ReservedChoiceMeta):
    default = 0
    supports_weighting = True

    def __init__(self, value):
        self.value = value

    @property
    def current_key(self):
        return self.name_lookup[self.value]

    @classmethod
    def from_any(cls, value):
        if type(value) is int and value in cls.name_lookup:
            return cls(value)
        return cls.from_text(str(value))

    @classmethod
    def from_text(cls, text):
        if text.lower() == "random":
            return cls(random.choice(list(cls.name_lookup)))
        return cls(cls.options[text.lower()])

    def verify(self, *_args):
        pass


class ContractValue:
    default = 0
    supports_weighting = False

    def __init__(self, value):
        self.value = value

    @classmethod
    def from_any(cls, value):
        return cls(value)


class Group(typing.NamedTuple):
    name: str
    options: list
    start_collapsed: bool = False


def contract_module():
    result = types.ModuleType("Options")
    result.Choice = ContractChoice
    for name in ("Range", "Toggle", "OptionSet", "OptionDict", "Removed"):
        setattr(result, name, type(name, (ContractValue,), {}))
    result.PerGameCommonOptions = dataclasses.make_dataclass("PerGameCommonOptions", [])
    result.OptionGroup = Group
    result.random_weighted_range = lambda _style, low, high: random.randint(low, high)
    return result


def world_options(ap_options):
    from ootrr_triforce import feature_settings, settings_labels
    package = types.ModuleType("_ootrr_ap_options_test")
    package.__path__ = []
    spec = importlib.util.spec_from_file_location(package.__name__ + ".options", ROOT / "apworld/ootrr_remake/options.py")
    module = importlib.util.module_from_spec(spec)
    modules = {"Options": ap_options, package.__name__: package,
               package.__name__ + ".settings": settings,
               package.__name__ + ".feature_settings": feature_settings,
               package.__name__ + ".settings_labels": settings_labels, spec.name: module}
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


def primary_options(directory):
    """Execute original AP classes; do not reimplement their metaclass/parser."""
    path = directory / "Options.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    names = {"OptionError", "Visibility", "AssembleOptions", "Option", "FreeText", "NumericOption",
             "Toggle", "Choice", "Range", "FreezeValidKeys", "VerifyKeys", "OptionSet", "OptionDict", "Removed", "OptionGroup"}
    helpers = {"triangular", "random_weighted_range"}
    selected = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
    for node in tree.body:
        if isinstance(node, ast.Import):
            selected.append(node)
        elif isinstance(node, ast.ImportFrom) and node.module in {"collections", "copy", "dataclasses"}:
            selected.append(node)
        elif isinstance(node, ast.ClassDef) and node.name in names:
            selected.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in helpers:
            selected.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in {"T", "_RANDOM_OPTS"}
                                                  for target in node.targets):
            selected.append(node)
    result = types.ModuleType("Options")
    result.__dict__.update(Self=typing.Self, is_iterable_except_str=lambda value: isinstance(value, typing.Iterable) and not isinstance(value, str))
    with patch.dict(sys.modules, {"Options": result}):
        exec(compile(ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])), str(path), "exec", optimize=0), result.__dict__)
    result.PerGameCommonOptions = dataclasses.make_dataclass("PerGameCommonOptions", [])
    return result


def primary_generator(directory, ap_options):
    path = directory / "Generate.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    selected = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
    selected += [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in {"get_choice", "handle_option"}]
    namespace = dict(argparse=argparse, random=random, Options=ap_options)
    exec(compile(ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])), str(path), "exec", optimize=0), namespace)
    return types.SimpleNamespace(**namespace)


class APChoiceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ap = contract_module()
        cls.world = world_options(cls.ap)

    def test_option_creator_uses_the_same_category_order_without_duplicates(self):
        from ootrr_triforce.settings_labels import GROUP_ORDER
        self.assertEqual([group.name for group in self.world.OPTION_GROUPS], list(GROUP_ORDER))
        grouped = [option for group in self.world.OPTION_GROUPS for option in group.options]
        self.assertEqual(len(grouped), len(settings.OPTION_SPECS))
        self.assertEqual(set(grouped), set(self.world.OPTION_TYPES.values()))

    def test_every_exposed_choice_loads_with_reserved_key_checks_enabled(self):
        for name, option in self.world.OPTION_TYPES.items():
            with self.subTest(option=name):
                self.assertNotIn("random", getattr(option, "options", {}))
                self.assertNotIn("random", getattr(option, "aliases", {}))
        for prefix in ("option_", "alias_"):
            with self.assertRaises(AssertionError):
                type("ForbiddenReservedValue", (self.ap.Choice,), {prefix + "random": 1})

    def test_explicit_random_deals_keeps_its_id_and_native_mode_without_a_roll(self):
        option = self.world.OPTION_TYPES["shuffle_shops"]
        self.assertEqual(option.option_random_deals, 6)
        self.assertEqual(option.name_lookup[6], "random_deals")
        self.assertNotIn("from_any", option.__dict__)
        self.assertNotIn("from_text", option.__dict__)
        with patch.object(random, "choice", side_effect=AssertionError("Explicit mode must not be rolled")):
            rolled = option.from_any("random_deals")
        self.assertEqual(rolled.current_key, "random_deals")
        values = self.world.option_values(types.SimpleNamespace(shuffle_shops=rolled))
        self.assertEqual(values["shuffle_shops"], "random")
        self.assertEqual(settings.engine_settings(values)["shuffle_shops"], "random")

    def test_standard_ap_random_can_choose_each_global_shop_mode(self):
        option = self.world.OPTION_TYPES["shuffle_shops"]
        for value in range(7):
            with self.subTest(mode=value), patch.object(random, "choice", return_value=value) as choose:
                rolled = option.from_any("random")
                self.assertEqual(rolled.value, value)
                self.assertEqual(choose.call_args.args[0], list(range(7)))

    def test_explicit_random_colours_keep_their_native_mode_without_an_ap_roll(self):
        option = self.world.OPTION_TYPES["cosmetic_color_mode"]
        self.assertEqual(option.option_random_colors, 2)
        self.assertEqual(option.name_lookup[2], "random_colors")
        self.assertNotIn("from_any", option.__dict__)
        self.assertNotIn("from_text", option.__dict__)
        with patch.object(random, "choice", side_effect=AssertionError("Explicit native colour mode must not roll AP choices")):
            rolled = option.from_any("random_colors")
        self.assertEqual(rolled.current_key, "random_colors")
        values = self.world.option_values(types.SimpleNamespace(cosmetic_color_mode=rolled))
        self.assertEqual(values["cosmetic_color_mode"], "random")
        from ootrr_triforce.feature_settings import feature_config
        self.assertEqual(feature_config(values)["settings"]["cosmetic_color_mode"], "random")

    def test_standard_ap_random_can_choose_each_colour_mode(self):
        option = self.world.OPTION_TYPES["cosmetic_color_mode"]
        for index, native in enumerate(("off", "custom", "random", "shared")):
            with self.subTest(mode=native), patch.object(random, "choice", return_value=index) as choose:
                rolled = option.from_any("random")
                self.assertEqual(rolled.value, index)
                self.assertEqual(choose.call_args.args[0], list(range(4)))
                self.assertEqual(self.world.option_values(types.SimpleNamespace(cosmetic_color_mode=rolled))["cosmetic_color_mode"], native)

    def rolled_options(self, **values):
        return types.SimpleNamespace(**{
            name: (self.world.OPTION_TYPES[name].from_any(value)
                   if settings.SPEC_BY_ID[name]["kind"] == "choice" else types.SimpleNamespace(value=value))
            for name, value in values.items()})

    def test_inactive_economy_rolls_are_ignored_without_mutating_ap_choices(self):
        raw = dict(scrub_prices="fixed", scrub_price_fixed=99, scrub_hint_text=True,
                   merchant_prices="fixed", merchant_price_fixed=0,
                   fairy_prices="cheap", fairy_price_fixed=99, shopsanity_prices="giant")
        with self.assertRaises(ValueError):
            settings.validate_options(raw)
        rolled = self.rolled_options(**raw)
        normalized = self.world.option_values(rolled)
        for name in ("scrub_prices", "scrub_price_fixed", "scrub_hint_text", "merchant_prices",
                     "merchant_price_fixed", "fairy_price_fixed", "shopsanity_prices"):
            self.assertEqual(normalized[name], settings.default_options()[name], name)
        self.assertEqual(normalized["fairy_prices"], "cheap")
        self.assertEqual(rolled.scrub_prices.current_key, "fixed")
        self.assertEqual(rolled.scrub_price_fixed.value, 99)
        self.assertEqual(settings.engine_settings(normalized)["fairy_prices"], "cheap")

    def test_active_economy_values_are_preserved_including_free_fixed_purchases(self):
        for kind in ("scrub", "merchant", "fairy"):
            for price in (0, 10, 99):
                raw = dict(shuffle_rewards="supported", shuffle_scrubs_a=True,
                           shuffle_merchants="all", plant_beans=True,
                           **{kind + "_prices": "fixed", kind + "_price_fixed": price})
                with self.subTest(kind=kind, price=price):
                    normalized = self.world.option_values(self.rolled_options(**raw))
                    for name, value in raw.items():
                        self.assertEqual(normalized[name], value)
                    self.assertEqual(settings.engine_settings(normalized)[kind + "_price_fixed"], price)

    def test_inactive_goal_and_hint_rolls_do_not_reject_valid_active_modes(self):
        raw = dict(bridge="open", bridge_rewards=3, skip_ganon_trials=True, trials=2,
                   door_of_time_condition="open", door_of_time_song=False,
                   lacs_rewards=1, song_harp_colors=False)
        normalized = self.world.option_values(self.rolled_options(**raw))
        self.assertEqual(normalized["bridge"], "open")
        self.assertEqual(normalized["bridge_rewards"], 0)
        self.assertIs(normalized["skip_ganon_trials"], True)
        for name in ("trials", "door_of_time_song", "lacs_rewards", "song_harp_colors"):
            self.assertEqual(normalized[name], settings.default_options()[name], name)
        self.assertEqual(settings.engine_settings(normalized)["bridge_rewards"], 0)

    def test_door_suboptions_follow_their_active_native_condition(self):
        for condition in ("vanilla", "stones", "song", "open"):
            raw = dict(door_of_time_condition=condition, door_of_time_song=False, door_of_time_escape="vanilla")
            with self.subTest(condition=condition):
                normalized = self.world.option_values(self.rolled_options(**raw))
                self.assertEqual(normalized["door_of_time_condition"], condition)
                self.assertEqual(normalized["door_of_time_song"], condition in {"open", "song"})
                self.assertEqual(normalized["door_of_time_escape"], "vanilla" if condition in {"open", "song"} else "moat")
                settings.engine_settings(normalized)

    def test_active_progression_and_invalid_combinations_are_never_silently_changed(self):
        raw = dict(bridge="dungeons", bridge_rewards=3, trials=2, shuffle_chests="all",
                   shuffle_rewards="supported", shuffle_ganon_bosskey="lacs_dungeons", lacs_rewards=4,
                   door_of_time_condition="stones", door_of_time_song=False,
                   shuffle_songs="anywhere", song_harp_colors=False,
                   shuffle_shops="deals_1", shopsanity_prices="giant")
        self.assertEqual(self.world.option_values(self.rolled_options(**raw)), settings.validate_options(raw))
        for invalid in (dict(shuffle_cows=True), dict(open_kakariko="open"),
                        dict(early_beds=True, time_always_passes=False), dict(shuffle_merchants="beans")):
            with self.subTest(active_invalid=invalid), self.assertRaises(ValueError):
                self.world.option_values(self.rolled_options(**invalid))


SOURCE = Path(os.environ["AP_SOURCE"]).resolve() if os.environ.get("AP_SOURCE") else None


@unittest.skipUnless(SOURCE and (SOURCE / "Options.py").is_file() and (SOURCE / "Generate.py").is_file(),
                     "Set AP_SOURCE to the official AP 0.6.8 sources for the primary-source probe")
class PrimaryAPChoiceTests(APChoiceContractTests):
    @classmethod
    def setUpClass(cls):
        cls.ap = primary_options(SOURCE)
        cls.world = world_options(cls.ap)
        cls.generator = primary_generator(SOURCE, cls.ap)

    def test_unoptimized_primary_metaclass_rejects_both_reserved_forms(self):
        for prefix in ("option_", "alias_"):
            with self.assertRaises(AssertionError):
                type("ForbiddenReservedValue", (self.ap.Choice,), {prefix + "random": 1})

    def test_actual_generator_rolls_scalar_weighted_and_list_inputs_before_native_mapping(self):
        option = self.world.OPTION_TYPES["shuffle_shops"]
        # JSON documents are a YAML subset, and preserve the exact decoded
        # scalar, mapping and list inputs consumed by Generate.handle_option.
        documents = ('{"shuffle_shops":"random_deals"}',
                     '{"shuffle_shops":{"random_deals":10,"deals_1":0}}',
                     '{"shuffle_shops":["random_deals"]}')
        worlds = types.ModuleType("worlds")
        worlds.AutoWorldRegister = types.SimpleNamespace(world_types={GAME: types.SimpleNamespace()})
        for document in documents:
            with self.subTest(yaml=document), patch.dict(sys.modules, {"worlds": worlds}):
                rolled = argparse.Namespace(game=GAME, name="ContractTest")
                with patch.object(random, "choice", side_effect=AssertionError("Explicit native mode must not use AP's random choice")):
                    self.generator.handle_option(rolled, json.loads(document), "shuffle_shops", option, None)
                self.assertEqual(rolled.shuffle_shops.value, 6)
                self.assertEqual(self.world.option_values(rolled)["shuffle_shops"], "random")
        for value in range(7):
            with patch.dict(sys.modules, {"worlds": worlds}), patch.object(random, "choice", return_value=value):
                rolled = argparse.Namespace(game=GAME, name="ContractTest")
                self.generator.handle_option(rolled, {"shuffle_shops": {"random": 10}}, "shuffle_shops", option, None)
                self.assertEqual(rolled.shuffle_shops.value, value)

    def test_actual_ap_random_economy_rolls_normalize_only_unused_fields(self):
        for seed in range(32):
            with self.subTest(seed=seed):
                state = random.getstate()
                try:
                    random.seed(seed)
                    rolled = types.SimpleNamespace(**{
                        name: self.world.OPTION_TYPES[name].from_any("random")
                        for name in ("scrub_prices", "scrub_price_fixed", "scrub_hint_text",
                                     "merchant_prices", "merchant_price_fixed", "fairy_prices", "fairy_price_fixed",
                                     "shopsanity_prices")})
                    normalized = self.world.option_values(rolled)
                    self.assertEqual(normalized["scrub_prices"], "vanilla")
                    self.assertEqual(normalized["merchant_prices"], "vanilla")
                    self.assertEqual(normalized["fairy_prices"], rolled.fairy_prices.current_key)
                    expected_price = rolled.fairy_price_fixed.value if normalized["fairy_prices"] == "fixed" else 10
                    self.assertEqual(normalized["fairy_price_fixed"], expected_price)
                    settings.engine_settings(normalized)
                finally:
                    random.setstate(state)


if __name__ == "__main__":
    unittest.main()
