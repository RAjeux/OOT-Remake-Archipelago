"""Exercise APWorld reward conservation and counted sphere rules without generating a room."""
import ast
from collections import Counter
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.catalog import (AP_SKULL_CHECKS, CHESTS, DEFAULT_SETTINGS, FILLER, GAME,
                                    ITEM_DATA, ITEM_IDS, LOCATION_IDS, PROTOCOL,
                                    LOCATION_REWARD_MODE, PINNED_SKULL_CHECKS, SHOP_CHECKS, SKULL_CHECKS,
                                    TRADE_CHECKS)
from ootrr_triforce.trade_catalog import TRADE_ITEMS
from ootrr_triforce.shop_pool import SHOP_CHECK_MODE, shop_checks
from ootrr_triforce.network_catalog import (SCHEMA as NETWORK_SCHEMA, SHOP_MODE as NETWORK_SHOP_MODE,
                                            SOURCES as NETWORK_SOURCES, validate_sources)
from ootrr_triforce.network_placement import (allowed as allowed_placement, placement_priority,
                                             prefill_scoped_items)
from ootrr_triforce.settings import OPTION_SPECS, default_options, engine_settings, validate_options
from ootrr_triforce.master_sword import (SETTING as MASTER_SWORD_SETTING, ITEM as MASTER_SWORD_ITEM,
                                        LOCATION as MASTER_SWORD_LOCATION, proof_wave as master_sword_wave,
                                        token_material as master_sword_token)

DEAL_NAMES = tuple(next(name for name, row in SHOP_CHECKS.items() if row["shop"] == shop)
                   for shop in dict.fromkeys(row["shop"] for row in SHOP_CHECKS.values()))
DEAL_REWARDS = dict(zip(DEAL_NAMES, ("Bow", "Bomb Bag", "Dins Fire", "Rupees (20)",
                                    "Piece of Heart", "Small Key (Forest Temple)", "Ice Arrows", "Deku Nuts (5)")))


class Region:
    def __init__(self, name, player, multiworld):
        self.name, self.locations, self.connections = name, [], []

    def connect(self, region, rule):
        self.connections.append((region, rule))


class Location:
    def __init__(self, player, name, address, region):
        self.name, self.address = name, address
        self.player = player
        self.item_rule = lambda item: True


class Item:
    def __init__(self, name, classification, address, player):
        self.name, self.classification, self.address = name, classification, address
        self.player = player


class State:
    def __init__(self, **counts):
        self.counts = counts

    def has(self, name, player, count=1):
        assert player == 1
        return self.counts.get(name, 0) >= count


# Compile the actual methods so these tests do not depend on an installed
# Archipelago Python interpreter. The real generator additionally checks the
# Options/World integration when generating the local validation room.
tree = ast.parse((ROOT / "apworld/ootrr_remake/__init__.py").read_text(encoding="utf-8"))
world = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "RemakeWorld")
namespace = dict(globals(), RemakeItem=Item, RemakeLocation=Location,
                 ItemClassification=SimpleNamespace(progression=1, progression_skip_balancing=9, filler=0))
option_tree = ast.parse((ROOT / "apworld/ootrr_remake/options.py").read_text(encoding="utf-8"))
option_values = [node for node in option_tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in {"option_values", "_normalize_inactive_options"}]
exec(compile(ast.Module(body=option_values, type_ignores=[]),
             str(ROOT / "apworld/ootrr_remake/options.py"), "exec"), namespace)
exec(compile(ast.Module(body=[node for node in world.body if isinstance(node, ast.FunctionDef)], type_ignores=[]),
             str(ROOT / "apworld/ootrr_remake/__init__.py"), "exec"), namespace)
World = type("WorldMethods", (), {node.name: namespace[node.name] for node in world.body if isinstance(node, ast.FunctionDef)})


class AllChestRewardTests(unittest.TestCase):
    def make_world(self, changes=None, shops=False, option_changes=None, players=2, engine=None):
        names = list(CHESTS)[:4]
        rewards = ["Small Key (Forest Temple)", "Small Key (Forest Temple)", "Rupees (20)", "Piece of Heart"]
        seed = dict(checksum="synthetic", placements=dict(zip(names, rewards)))
        generated = dict(seed_file=seed, waves=[names[:2] + ["Local NPC reward"], names[2:] + ["Ganon"]])
        if shops:
            seed["shops"] = {name: {"item": DEAL_REWARDS.get(name, row["item"]), "price": row["price"],
                                    "deal": name in DEAL_REWARDS} for name, row in SHOP_CHECKS.items()}
            generated["waves"][0].extend(SHOP_CHECKS)
        if changes:
            changes(generated)
        # The engine selects sources once. Every selected native reward now
        # joins AP, including ordinary shops and formerly local source kinds.
        generated["network_sources_schema"] = NETWORK_SCHEMA
        rows = {}
        for name, reward in seed["placements"].items():
            rows[name] = dict(deepcopy(NETWORK_SOURCES[name]), generated_item=reward)
        for name, row in seed.get("shops", {}).items():
            rows[name] = dict(deepcopy(NETWORK_SOURCES[name]), generated_item=row["item"],
                              price=row["price"], deal=row.get("deal", False))
        generated["network_sources"] = rows
        generated.setdefault("progression_items", [name for name, row in ITEM_DATA.items()
                                                   if row.get("advancement", False)])
        calls = []
        def run_engine(command, request):
            calls.append((command, request))
            return engine(command, request) if engine is not None else json.dumps(generated)
        namespace["run_engine"] = run_engine
        w = World()
        w.game, w.player, w.player_name = GAME, 1, "Zelda"
        w.random = SimpleNamespace(getrandbits=lambda bits: 17)
        values = default_options()
        values.update(death_link=True, shuffle_shops="deals_1" if shops else "off")
        values.update(option_changes or {})
        w.options = SimpleNamespace(**{
            spec["id"]: SimpleNamespace(value=(spec["choices"].index(values[spec["id"]])
                                               if spec["kind"] == "choice" else values[spec["id"]]),
                                        current_key=values[spec["id"]]) for spec in OPTION_SPECS})
        w.multiworld = SimpleNamespace(seed_name="AP-synthetic", regions=[], itempool=[], completion_condition={},
                                      players=players, get_out_file_name_base=lambda player: "AP_synthetic_P1_Zelda")
        w.generate_early()
        w.engine_calls = calls
        return w, names, rewards

    @staticmethod
    def add_adult_trades(generated):
        names = list(TRADE_CHECKS)
        rewards = [*sorted(TRADE_ITEMS), "Rupees (50)"]
        generated["seed_file"]["placements"].update(zip(names, rewards))
        generated["waves"][0].extend(names)

    def test_adult_trades_conserve_ten_tokens_and_export_all_eleven_checks(self):
        w, names, rewards = self.make_world(
            self.add_adult_trades,
            option_changes={"shuffle_rewards": "supported", "shuffle_rewards_extra": False,
                            "adult_trade_shuffle": True})
        self.assertEqual(set(w.moved), set(names) | set(TRADE_CHECKS))
        self.assertEqual(w.engine_calls[0][1]["settings"]["adult_trade_shuffle"], True)
        self.assertEqual(w.engine_calls[0][1]["settings"]["shuffle_rewards_extra"], False)
        w.create_items()
        w.create_regions()
        pool = Counter(item.name for item in w.multiworld.itempool)
        self.assertEqual(pool, Counter([*rewards, *TRADE_ITEMS, "Rupees (50)"]))
        self.assertTrue(all(pool[name] == 1 for name in TRADE_ITEMS))
        self.assertNotIn("Pocket Egg", pool)
        locations = [location for region in w.multiworld.regions for location in region.locations]
        self.assertEqual(len(w.multiworld.itempool), len(locations))
        trades = [location for location in locations if location.name in TRADE_CHECKS]
        self.assertEqual(len(trades), 11)
        self.assertEqual(sorted(location.address for location in trades), list(range(7303916, 7303927)))
        self.assertIn("DMT Biggoron", {location.name for location in trades})
        for location in trades:
            self.assertTrue(all(location.item_rule(item) for item in w.multiworld.itempool))
            self.assertTrue(location.item_rule(SimpleNamespace(player=2, name="A friend's item")))
        slot = w.fill_slot_data()
        self.assertIs(slot["adult_trade_shuffle"], True)
        self.assertIs(slot["death_link"], True)
        self.assertEqual(slot["checks"], sorted(location.address for location in locations))
        with tempfile.TemporaryDirectory() as folder:
            w.generate_output(folder)
            manifest = json.loads(next(Path(folder).glob("*.apootrr")).read_bytes())
        self.assertIs(manifest["adult_trade_shuffle"], True)
        self.assertEqual(set(manifest["checks"]), set(w.moved))
        self.assertEqual(manifest["moved"], w.moved)
        self.assertEqual(manifest["seed_file"], w.seed_file)
        self.assertEqual(manifest["token"], slot["token"])

    def test_adult_trades_require_each_reward_and_its_reachability_proof(self):
        for name in TRADE_CHECKS:
            with self.subTest(missing_reward=name):
                def missing_reward(generated):
                    self.add_adult_trades(generated)
                    del generated["seed_file"]["placements"][name]
                with self.assertRaisesRegex(ValueError, "all eleven supported trade rewards"):
                    self.make_world(missing_reward,
                                    option_changes={"shuffle_rewards": "supported", "adult_trade_shuffle": True})
            with self.subTest(missing_proof=name):
                def missing_proof(generated):
                    self.add_adult_trades(generated)
                    generated["waves"][0].remove(name)
                with self.assertRaisesRegex(ValueError, "did not prove access.*" + re.escape(name)):
                    self.make_world(missing_proof,
                                    option_changes={"shuffle_rewards": "supported", "adult_trade_shuffle": True})

    def test_every_engine_selected_trade_reward_joins_ap_without_a_second_selector(self):
        w, names, rewards = self.make_world(self.add_adult_trades,
                                           option_changes={"shuffle_rewards": "supported"})
        self.assertEqual(set(w.moved), set(names) | set(TRADE_CHECKS))
        self.assertTrue(set(TRADE_CHECKS) <= w.seed_file["placements"].keys())
        w.create_items()
        self.assertEqual(Counter(item.name for item in w.multiworld.itempool), Counter([*rewards, *TRADE_ITEMS, "Rupees (50)"]))
        self.assertIs(w.fill_slot_data()["adult_trade_shuffle"], False)
        with tempfile.TemporaryDirectory() as folder:
            w.generate_output(folder)
            manifest = json.loads(next(Path(folder).glob("*.apootrr")).read_bytes())
        self.assertIs(manifest["adult_trade_shuffle"], False)
        self.assertTrue(set(TRADE_CHECKS) <= set(manifest["checks"]))

    def test_legacy_additive_trade_yaml_requires_explicit_migration(self):
        class Removed:
            def __init__(self, value):
                self.value = value
        removed = next(node for node in option_tree.body
                       if isinstance(node, ast.ClassDef) and node.name == "TradeBonusRemoved")
        scope = {"Removed": Removed}
        exec(compile(ast.Module(body=[removed], type_ignores=[]),
                     str(ROOT / "apworld/ootrr_remake/options.py"), "exec"), scope)
        option = scope["TradeBonusRemoved"]
        for value in (None, False, "false", "False", "off", 0, "0", "", "none", "null"):
            with self.subTest(disabled_legacy_value=value):
                self.assertFalse(option(value).value)
        for value in (True, "true", "True", "on", 1, "1"):
            with self.subTest(enabled_legacy_value=value):
                with self.assertRaisesRegex(ValueError, "adult_trade_shuffle: true"):
                    option(value)
        self.assertNotIn("shuffle_trade_checks", {spec["id"] for spec in OPTION_SPECS})
        self.assertIs(default_options()["adult_trade_shuffle"], False)

    @unittest.skipUnless(os.environ.get("OOTRR_NODE") or shutil.which("node"),
                         "Node.js needed for the native adult-trade access proof")
    def test_real_native_trade_proof_preserves_each_required_item_in_ap_rules(self):
        from ootrr_triforce.engine import run_engine
        w, _, _ = self.make_world(
            option_changes={"shuffle_rewards": "supported", "shuffle_rewards_extra": False,
                            "adult_trade_shuffle": True}, engine=run_engine)
        self.assertEqual(len(w.engine_calls), 1)
        self.assertEqual(set(TRADE_CHECKS) - w.moved.keys(), set())
        self.assertEqual(Counter(item for item in w.moved.values() if item in TRADE_ITEMS),
                         Counter({item: 1 for item in TRADE_ITEMS}))
        self.assertFalse(TRADE_ITEMS.intersection(item for name, item in w.seed_file["placements"].items()
                                                 if name not in w.moved))
        w.create_items()
        w.create_regions()
        self.assertEqual(len(w.multiworld.itempool), sum(len(region.locations) for region in w.multiworld.regions))
        required_names = {ITEM_DATA[name]["actor"]: name for name in TRADE_ITEMS}
        for check, row in TRADE_CHECKS.items():
            if row["required_actor"] is None:
                continue
            required = required_names[row["required_actor"]]
            with self.subTest(hand_in=check, required_item=required):
                source, = [name for name, item in w.moved.items() if item == required]
                self.assertLess(w.waves[source], w.waves[check])
                earlier = Counter(item for name, item in w.moved.items() if w.waves[name] < w.waves[check])
                rule = w.rules_at[w.waves[check]]
                self.assertTrue(rule(State(**earlier)))
                earlier[required] = 0
                self.assertFalse(rule(State(**earlier)), "A remote hand-in token must stay in the AP access rule")

    @unittest.skipUnless(os.environ.get("OOTRR_NODE") or shutil.which("node"),
                         "Node.js needed for the native shop-to-AP integration")
    def test_real_native_shops_project_all_selected_goods_and_deals_into_ap(self):
        from ootrr_triforce.engine import run_engine
        w, _, _ = self.make_world(option_changes={"shuffle_shops": "deals_1"}, engine=run_engine)
        native = w.seed_file["shops"]
        selected = {name for name, row in native.items() if row.get("deal", False)}
        ordinary = set(native) - selected
        self.assertEqual(set(native), set(SHOP_CHECKS))
        self.assertTrue(selected)
        self.assertLessEqual(len(selected), 8)
        self.assertTrue(any(SHOP_CHECKS[name]["shop"] != "KF Shop" for name in selected))
        self.assertEqual(w.shop_checks, set(native))
        self.assertEqual(set(w.moved) & set(SHOP_CHECKS), set(native))
        self.assertTrue(ordinary <= set(w.waves))
        w.create_items()
        w.create_regions()
        expected = Counter(w.seed_file["placements"][name] for name in w.waves if name not in SHOP_CHECKS)
        expected.update(native[name]["item"] for name in native)
        self.assertEqual(Counter(item.name for item in w.multiworld.itempool), expected)
        locations = [location for region in w.multiworld.regions for location in region.locations]
        self.assertEqual(len(w.multiworld.itempool), len(locations))
        self.assertEqual({location.name for location in locations if location.name in SHOP_CHECKS}, set(native))
        for location in locations:
            if location.name in selected:
                self.assertTrue(all(location.item_rule(item) for item in w.multiworld.itempool))
                self.assertTrue(location.item_rule(SimpleNamespace(player=2, name="Other game's reward")))
        self.assertEqual(w.fill_slot_data()["shop_checks"], sorted(native))

    def test_every_reward_is_conserved_and_repeated_keys_count(self):
        w, names, rewards = self.make_world()
        self.assertEqual(w.moved, dict(zip(names, rewards)))
        w.create_items()
        self.assertEqual(Counter(item.name for item in w.multiworld.itempool), Counter(rewards))
        self.assertNotIn(FILLER, [item.name for item in w.multiworld.itempool])
        self.assertTrue(all(item.classification == (1 if item.name in w.progression_items else 0)
                            for item in w.multiworld.itempool))
        w.create_regions()
        goal = w.multiworld.completion_condition[1]
        self.assertFalse(goal(State(**{"Small Key (Forest Temple)": 1})))
        self.assertTrue(goal(State(**{"Small Key (Forest Temple)": 2})))
        self.assertEqual(len(w.multiworld.regions[0].connections), 2)
        self.assertTrue(w.multiworld.regions[0].connections[0][1](State()))
        self.assertEqual(sum(len(r.locations) for r in w.multiworld.regions), 4)
        self.assertEqual(w.fill_slot_data()["reward_mode"], LOCATION_REWARD_MODE)
        self.assertIs(w.fill_slot_data()["local_items"], True)
        self.assertIs(w.fill_slot_data()["kokiri_shop_checks"], False)
        self.assertIs(w.fill_slot_data()["foreign_only_shops"], False)
        with tempfile.TemporaryDirectory() as folder:
            w.generate_output(folder)
            manifest = json.loads(next(Path(folder).glob("*.apootrr")).read_bytes())
            self.assertEqual(manifest["moved"], dict(zip(names, rewards)))
            self.assertEqual(manifest["reward_mode"], LOCATION_REWARD_MODE)
            self.assertIs(manifest["death_link"], True)

    def test_selected_npc_ground_and_container_sources_all_join_the_same_global_pool(self):
        extra = {next(name for name, row in NETWORK_SOURCES.items() if row["kind"] == kind): reward
                 for kind, reward in (("flow", "Bow"), ("pickup", "Progressive Hookshot"),
                                      ("container", "Bomb Bag"))}
        def selected(generated):
            generated["seed_file"]["placements"].update(extra)
            generated["waves"][0].extend(extra)
        w, names, rewards = self.make_world(selected)
        self.assertEqual(set(w.moved), set(names) | extra.keys())
        w.create_regions()
        w.create_items()
        self.assertEqual(Counter(item.name for item in w.multiworld.itempool),
                         Counter([*rewards, *extra.values()]))
        self.assertEqual(len(w.multiworld.itempool), sum(len(region.locations) for region in w.multiworld.regions))
        progression = ("Bow", "Bomb Bag", "Progressive Hookshot", "Master Sword")
        for location in (location for region in w.multiworld.regions for location in region.locations):
            for name in progression:
                self.assertTrue(location.item_rule(SimpleNamespace(name=name, player=1)))
                self.assertTrue(location.item_rule(SimpleNamespace(name=name, player=2)),
                                "No recipient quota or owner-local progression requirement")

    def test_source_metadata_must_match_selected_seed_rewards_and_physical_identity(self):
        w, names, _ = self.make_world()
        valid = dict(seed_file=w.seed_file, network_sources_schema=NETWORK_SCHEMA,
                     network_sources=w.network_sources)
        self.assertEqual(validate_sources(valid), w.network_sources)
        for mutation in ("missing", "extra", "reward", "identity"):
            with self.subTest(mutation=mutation):
                data = deepcopy(valid)
                rows = data["network_sources"]
                if mutation == "missing":
                    rows.pop(names[0])
                elif mutation == "extra":
                    unused = next(name for name in NETWORK_SOURCES if name not in rows)
                    rows[unused] = dict(deepcopy(NETWORK_SOURCES[unused]), generated_item="Bow")
                elif mutation == "reward":
                    rows[names[0]]["generated_item"] = "Bow"
                else:
                    rows[names[0]]["variants"][0]["actor"] = "1"
                with self.assertRaises(ValueError):
                    validate_sources(data)

    def test_optional_hundred_token_reward_requires_last_token_even_if_placed_here(self):
        hundred = "Kak 100 Gold Skulltula Reward"
        ordinary = "ZR GS Near Raised Grottos"
        skulls = sorted(SKULL_CHECKS)
        self.assertEqual(len(skulls), 100)
        def add_optional(generated):
            rewards = generated["seed_file"]["placements"]
            rewards.update({name: "Gold Skulltula Token" for name in skulls})
            rewards[ordinary] = "Rupees (20)"
            rewards[hundred] = "Gold Skulltula Token"
            generated["waves"][0].extend(name for name in skulls if name != ordinary)
            generated["optional_sources"] = {
                ordinary: {"reason": "Known native bean route outside the progression proof."},
                hundred: {"reason": "Known native hundred-token reward outside the progression proof."}}
        w, names, _ = self.make_world(add_optional, option_changes={"shuffle_rewards": "supported",
                                                                   "shuffle_skulltulas": "matched"})
        self.assertEqual(set(w.moved), set(names) | set(skulls) | {hundred})
        self.assertEqual(w.goal_wave, 1, "Optional checks must not move or bypass the Ganon proof")
        self.assertGreater(w.waves[ordinary], w.goal_wave)
        self.assertGreater(w.waves[hundred], w.waves[ordinary])
        w.create_items()
        w.create_regions()
        self.assertEqual(Counter(item.name for item in w.multiworld.itempool)["Gold Skulltula Token"], 100)
        before_hundred = Counter(prize for name, prize in w.moved.items() if w.waves[name] < w.waves[hundred])
        self.assertEqual(before_hundred["Gold Skulltula Token"], 99)
        self.assertTrue(w.rules_at[w.waves[ordinary]](State(**before_hundred)))
        self.assertFalse(w.rules_at[w.waves[hundred]](State(**before_hundred)),
                         "A last token at its own 100-token reward cannot unlock itself")
        before_hundred["Gold Skulltula Token"] += 1
        self.assertTrue(w.rules_at[w.waves[hundred]](State(**before_hundred)))

    def test_global_rule_stage_restricts_zelda_items_in_foreign_games_without_replacing_existing_rules(self):
        w, _, _ = self.make_world()
        forest = next(name for name, row in NETWORK_SOURCES.items() if row["kind"] == "chest"
                      and row["variants"][0]["file"].startswith("Banc/ForestTemple/"))
        song = next(name for name, row in NETWORK_SOURCES.items() if row.get("native_kind") == "song")
        w.network_sources[forest] = deepcopy(NETWORK_SOURCES[forest])
        w.native_options["shuffle_songs"] = "anywhere"
        foreign_world = SimpleNamespace(game="Dark Souls III")
        second_zelda = SimpleNamespace(game=GAME, native_options=dict(default_options(), shuffle_songs="own",
                                                                      shuffle_smallkeys="keysanity"),
                                       network_sources={song: deepcopy(NETWORK_SOURCES[song])})
        own_location = SimpleNamespace(name=forest, player=1, item_rule=lambda item: item.name != "Forbidden")
        foreign_location = SimpleNamespace(name="Friend's source", player=2, item_rule=lambda item: item.name != "Their restriction")
        song_location = SimpleNamespace(name=song, player=3, item_rule=lambda item: True)
        locations = [own_location, foreign_location, song_location]
        multiworld = SimpleNamespace(worlds={1: w, 2: foreign_world, 3: second_zelda},
                                     get_locations=lambda: locations)
        World.stage_set_rules(multiworld)
        def item(name, player=1, game=GAME):
            return SimpleNamespace(name=name, player=player, game=game)
        self.assertTrue(own_location.item_rule(item("Small Key (Forest Temple)")))
        self.assertFalse(own_location.item_rule(item("Small Key (Fire Temple)")))
        self.assertFalse(foreign_location.item_rule(item("Small Key (Forest Temple)")))
        self.assertTrue(foreign_location.item_rule(item("Small Key (Forest Temple)", player=3)),
                        "The other Zelda player's explicit keysanity remains global")
        self.assertTrue(foreign_location.item_rule(item("Bow")))
        self.assertTrue(own_location.item_rule(item("Small Key (Fire Temple)", player=2, game="Dark Souls III")))
        self.assertFalse(own_location.item_rule(item("Forbidden")))
        self.assertFalse(foreign_location.item_rule(item("Their restriction")))
        self.assertTrue(song_location.item_rule(item("Suns Song", player=1)))
        self.assertFalse(song_location.item_rule(item("Bow", player=1)))
        self.assertFalse(song_location.item_rule(item("Suns Song", player=2, game="Dark Souls III")))

    def test_nonlogical_junk_and_placement_priority_never_become_access_requirements(self):
        def only_keys_are_logical(generated):
            generated["progression_items"] = ["Small Key (Forest Temple)"]
            names = list(generated["seed_file"]["placements"])
            generated["seed_file"]["placements"][names[1]] = "Rupees (20)"
        w, _, _ = self.make_world(only_keys_are_logical)
        w.create_regions()
        self.assertTrue(w.rules_at[1](State(**{"Small Key (Forest Temple)": 1})))
        self.assertFalse(w.rules_at[1](State(**{"Rupees (20)": 999})))
        self.assertEqual(w.create_item("Rupees (20)").classification, 0)
        self.assertEqual(w.create_item("Map (Ice Cavern)").classification, 9,
                         "Scarce maps must reserve legal slots before unrestricted filler")
        self.assertEqual(w.create_item("Buy Blue Fire").classification, 9,
                         "Refills have scarce shelf slots but need not gate every sphere")
        self.assertNotIn("Map (Ice Cavern)", w.progression_items)
        self.assertTrue(w.rules_at[1](State(**{"Small Key (Forest Temple)": 1})))

    def test_native_progression_export_is_required_and_cannot_have_duplicate_or_untyped_names(self):
        for value in (None, "Bow", ["Bow", "Bow"], [False]):
            def invalid(generated):
                generated["progression_items"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "progression proof"):
                self.make_world(invalid)

    def test_native_junk_only_source_never_takes_foreign_or_local_progression_or_tokens(self):
        w, _, _ = self.make_world()
        name = next(name for name, row in NETWORK_SOURCES.items() if row["kind"] == "skull")
        descriptor = deepcopy(NETWORK_SOURCES[name])
        descriptor["placement"] = {"dungeon": None, "region_group": "forest", "junk_only": True}
        w.network_sources[name] = descriptor
        location = SimpleNamespace(name=name, player=1, item_rule=lambda item: True)
        multiworld = SimpleNamespace(worlds={1: w, 2: SimpleNamespace(game="Dark Souls III")},
                                     get_locations=lambda: [location])
        World.stage_set_rules(multiworld)
        def item(name, *, game=GAME, player=1, advancement=False):
            return SimpleNamespace(name=name, game=game, player=player, advancement=advancement)
        self.assertFalse(location.item_rule(item("Bow", advancement=True)))
        self.assertFalse(location.item_rule(item("Coiled Sword", player=2, game="Dark Souls III", advancement=True)))
        self.assertFalse(location.item_rule(item("Gold Skulltula Token", advancement=False)),
                         "A token is protected even if a goal currently classifies it as filler")
        self.assertTrue(location.item_rule(item("Rupee (1)")))
        self.assertTrue(location.item_rule(item("Titanite Shard", player=2, game="Dark Souls III")))
        self.assertTrue(location.item_rule(item("Gold Skulltula Token", player=2, game="Dark Souls III")),
                        "Foreign names are not Zelda's tokens")

    def test_unsupported_reward_is_rejected(self):
        def change(generated):
            generated["seed_file"]["placements"][next(iter(CHESTS))] = "No native reward"
        with self.assertRaisesRegex(ValueError, "no Archipelago delivery"):
            self.make_world(change)

    def test_all_engine_selected_skulltulas_join_the_pool_and_conserve_rewards(self):
        active = sorted(AP_SKULL_CHECKS)
        uncertain = sorted(set(SKULL_CHECKS) - AP_SKULL_CHECKS)
        def add_skulls(generated):
            generated["seed_file"]["placements"].update({name: "Gold Skulltula Token" for name in active})
            generated["seed_file"]["placements"].update({name: "Rupees (5)" for name in uncertain})
            generated["waves"][0].extend([*active, *uncertain])
        w, names, rewards = self.make_world(add_skulls, option_changes={"shuffle_skulltulas": "matched"})
        self.assertEqual(set(w.moved), set(names) | set(active) | set(uncertain))
        w.create_items()
        self.assertEqual(Counter(item.name for item in w.multiworld.itempool),
                         Counter([*rewards, *(["Gold Skulltula Token"] * len(active)), *(["Rupees (5)"] * len(uncertain))]))
        self.assertEqual(w.fill_slot_data()["shuffle_skulltulas"], "matched")
        self.assertTrue(set(LOCATION_IDS[name] for name in active).issubset(w.fill_slot_data()["checks"]))
        self.assertTrue(set(LOCATION_IDS[name] for name in uncertain).issubset(w.fill_slot_data()["checks"]))
        with tempfile.TemporaryDirectory() as folder:
            w.generate_output(folder)
            manifest = json.loads(next(Path(folder).glob("*.apootrr")).read_bytes())
        self.assertEqual(manifest["shuffle_skulltulas"], "matched")
        self.assertEqual(set(manifest["checks"]), set(names) | set(active) | set(uncertain))

    def test_skulltula_checks_need_a_reachable_proof_and_follow_the_setting(self):
        first, second = sorted(AP_SKULL_CHECKS)[:2]
        def omitted(generated):
            generated["seed_file"]["placements"][first] = "Gold Skulltula Token"
        with self.assertRaisesRegex(ValueError, "did not prove"):
            self.make_world(omitted, option_changes={"shuffle_skulltulas": "matched"})
        with self.assertRaisesRegex(ValueError, "did not prove"):
            self.make_world(omitted, option_changes={"shuffle_skulltulas": "off"})
        def one(generated):
            generated["seed_file"]["placements"][second] = "Gold Skulltula Token"
            generated["waves"][0].append(second)
        w, names, _ = self.make_world(one, option_changes={"shuffle_skulltulas": "matched"})
        self.assertEqual(set(w.moved), {*names, second})

    def test_skulltulas_accept_both_players_but_not_local_bottle_refills(self):
        first = next(iter(sorted(AP_SKULL_CHECKS)))
        def add_skull(generated):
            generated["seed_file"]["placements"][first] = "Gold Skulltula Token"
            generated["waves"][0].append(first)
        w, _, _ = self.make_world(add_skull, option_changes={"shuffle_skulltulas": "matched"})
        w.create_regions()
        location = next(location for region in w.multiworld.regions for location in region.locations
                        if location.name == first)
        refills = [name for name, row in ITEM_DATA.items()
                   if row.get("bottle_item") and row.get("pouch_special") == "NotPushToPouch"]
        self.assertTrue(refills)
        for name in ITEM_DATA:
            with self.subTest(item=name):
                self.assertEqual(bool(location.item_rule(SimpleNamespace(player=1, name=name))), name not in refills)
                self.assertTrue(location.item_rule(SimpleNamespace(player=2, name=name)))

    def test_missing_selected_skulltula_proof_cannot_silently_keep_a_local_reward(self):
        bean_ride = "ZR GS Near Raised Grottos"
        other = next(name for name in sorted(AP_SKULL_CHECKS) if name != bean_ride)
        def skulls_without_bean_ride(generated):
            generated["seed_file"]["placements"].update({name: "Gold Skulltula Token" for name in AP_SKULL_CHECKS})
            generated["seed_file"]["placements"][bean_ride] = "Rupees (20)"
            generated["waves"][0].extend(name for name in AP_SKULL_CHECKS if name != bean_ride)
        with self.assertRaisesRegex(ValueError, "did not prove"):
            self.make_world(skulls_without_bean_ride, option_changes={"shuffle_skulltulas": "matched"})
        # Settings that should make the bean ride reachable do not turn a
        # missing proof into an optimistic check; all other misses are fatal.
        for changes in ({"plant_beans": True}, {"starting_items": ["magic_beans"]}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "did not prove"):
                self.make_world(skulls_without_bean_ride,
                                option_changes={"shuffle_skulltulas": "matched", **changes})
        def other_missing(generated):
            skulls_without_bean_ride(generated)
            generated["waves"][0].remove(other)
        with self.assertRaisesRegex(ValueError, "did not prove"):
            self.make_world(other_missing, option_changes={"shuffle_skulltulas": "matched"})

    def test_proved_bean_ride_joins_with_preplanted_or_starting_beans(self):
        def all_skulls(generated):
            generated["seed_file"]["placements"].update({name: "Gold Skulltula Token" for name in AP_SKULL_CHECKS})
            generated["waves"][0].extend(AP_SKULL_CHECKS)
        for changes in ({"plant_beans": True}, {"starting_items": ["magic_beans"]}):
            with self.subTest(changes=changes):
                w, names, _ = self.make_world(all_skulls,
                                             option_changes={"shuffle_skulltulas": "matched", **changes})
                self.assertEqual(set(w.moved), set(names) | AP_SKULL_CHECKS)
                self.assertFalse(w.local_skulltulas)

    def test_python_does_not_refilter_the_native_source_selection_by_legacy_skull_mode(self):
        def all_skulls(generated):
            generated["seed_file"]["placements"].update({name: "Gold Skulltula Token" for name in SKULL_CHECKS})
            generated["waves"][0].extend(SKULL_CHECKS)
        w, names, rewards = self.make_world(all_skulls, option_changes={"shuffle_skulltulas": "pinned"})
        self.assertEqual(set(w.moved), set(names) | set(SKULL_CHECKS))
        self.assertEqual(w.fill_slot_data()["shuffle_skulltulas"], "pinned")
        self.assertEqual(w.local_skulltulas, {})
        w.create_items()
        self.assertEqual(Counter(item.name for item in w.multiworld.itempool),
                         Counter([*rewards, *(["Gold Skulltula Token"] * len(SKULL_CHECKS))]))

    def test_active_chest_without_reachability_proof_is_rejected(self):
        def change(generated):
            generated["waves"][0].remove(next(iter(CHESTS)))
        with self.assertRaisesRegex(ValueError, "did not prove"):
            self.make_world(change)

    def test_dungeon_reward_without_destination_is_rejected(self):
        for reward in ("Map", "Compass", "Small Key", "Boss Key"):
            with self.subTest(reward=reward):
                def change(generated):
                    generated["seed_file"]["placements"][next(iter(CHESTS))] = reward
                with self.assertRaisesRegex(ValueError, "no Archipelago destination"):
                    self.make_world(change)

    def test_all_selected_shop_goods_join_the_pool_and_counted_rules_across_all_shops(self):
        w, names, rewards = self.make_world(shops=True)
        self.assertEqual(set(w.waves), set(names) | set(SHOP_CHECKS))
        self.assertEqual(w.shop_checks, set(SHOP_CHECKS))
        self.assertEqual(len(w.seed_file["shops"]), 64)
        goods = [row["item"] for row in w.seed_file["shops"].values()]
        w.create_items()
        self.assertEqual(Counter(item.name for item in w.multiworld.itempool), Counter(rewards + goods))
        w.create_regions()
        state = State(**Counter([*rewards[:2], *goods]))
        self.assertTrue(w.multiworld.completion_condition[1](state))
        state.counts[goods[0]] -= 1
        self.assertFalse(w.multiworld.completion_condition[1](state))
        self.assertIs(w.fill_slot_data()["kokiri_shop_checks"], False)
        self.assertEqual(w.fill_slot_data()["shop_check_mode"], NETWORK_SHOP_MODE)
        self.assertEqual(w.fill_slot_data()["shop_checks"], sorted(SHOP_CHECKS))
        self.assertIs(w.fill_slot_data()["foreign_only_shops"], False)
        self.assertEqual(sum(len(region.locations) for region in w.multiworld.regions), 68)
        locations = [location for region in w.multiworld.regions for location in region.locations]
        self.assertEqual(sum(location.name in SHOP_CHECKS for location in locations), 64)
        for location in locations:
            self.assertTrue(location.item_rule(SimpleNamespace(player=2, name="Other game's progression")))
            if location.name in SHOP_CHECKS:
                self.assertTrue(all(location.item_rule(item) for item in w.multiworld.itempool))
            else:
                for item in w.multiworld.itempool:
                    metadata = ITEM_DATA[item.name]
                    refill = metadata.get("bottle_item") and metadata.get("pouch_special") == "NotPushToPouch"
                    self.assertEqual(location.item_rule(item), not refill)
        with tempfile.TemporaryDirectory() as folder:
            w.generate_output(folder)
            manifest = json.loads(next(Path(folder).glob("*.apootrr")).read_bytes())
            self.assertIs(manifest["kokiri_shop_checks"], False)
            self.assertEqual(manifest["shop_check_mode"], NETWORK_SHOP_MODE)
            self.assertEqual(manifest["shop_checks"], sorted(SHOP_CHECKS))
            self.assertEqual(set(manifest["checks"]) & set(SHOP_CHECKS), set(SHOP_CHECKS))
            self.assertIs(manifest["foreign_only_shops"], False)

    def test_shuffled_shops_work_in_a_single_player_pool(self):
        w, names, rewards = self.make_world(shops=True, players=1)
        w.create_items()
        w.create_regions()
        locations = [location for region in w.multiworld.regions for location in region.locations]
        shops = [location for location in locations if location.name in SHOP_CHECKS]
        self.assertEqual(len(shops), 64)
        self.assertEqual(len(w.multiworld.itempool), len(locations))
        self.assertEqual(w.engine_calls[0][1]["settings"]["shuffle_shops"], "deals_1")
        expected = Counter(rewards + [row["item"] for row in w.seed_file["shops"].values()])
        self.assertEqual(Counter(item.name for item in w.multiworld.itempool), expected)
        for location in shops:
            self.assertTrue(all(location.item_rule(item) for item in w.multiworld.itempool))
            self.assertTrue(location.item_rule(SimpleNamespace(player=2)))

    def test_ordinary_shuffled_goods_are_ap_checks_without_forcing_foreign_ownership(self):
        def ordinary(generated):
            for name, row in generated["seed_file"]["shops"].items():
                row.update(item=SHOP_CHECKS[name]["item"], deal=False)
        w, names, rewards = self.make_world(ordinary, shops=True, option_changes={"shuffle_shops": "shuffle"})
        self.assertEqual(w.shop_checks, set(SHOP_CHECKS))
        self.assertEqual(set(w.moved), set(names) | set(SHOP_CHECKS))
        self.assertEqual(len(w.seed_file["shops"]), 64)
        w.create_items()
        self.assertEqual(Counter(item.name for item in w.multiworld.itempool),
                         Counter(rewards + [row["item"] for row in w.seed_file["shops"].values()]))
        self.assertEqual(w.fill_slot_data()["shop_checks"], sorted(SHOP_CHECKS))

    def test_native_deal_count_does_not_exclude_ordinary_purchases_from_ap(self):
        selected = {"Kak Bazaar Item 8", "Market Potion Shop Item 2", "ZD Shop Item 8"}
        def only_three(generated):
            for name, row in generated["seed_file"]["shops"].items():
                row.update(item="Rupees (50)" if name in selected else SHOP_CHECKS[name]["item"],
                           deal=name in selected)
        w, names, rewards = self.make_world(only_three, shops=True, option_changes={"shuffle_shops": "random"})
        self.assertEqual(w.shop_checks, set(SHOP_CHECKS))
        self.assertEqual(set(w.moved), set(names) | set(SHOP_CHECKS))
        self.assertTrue(any(name.startswith("KF Shop") for name in w.shop_checks))
        w.create_items()
        w.create_regions()
        self.assertEqual(Counter(item.name for item in w.multiworld.itempool),
                         Counter(rewards + [row["item"] for row in w.seed_file["shops"].values()]))
        self.assertEqual(sum(len(region.locations) for region in w.multiworld.regions), len(names) + 64)

    def test_old_foreign_only_yaml_option_reports_its_replacement(self):
        class Removed:
            def __init__(self, value):
                self.value = value
        removed = next(node for node in option_tree.body
                       if isinstance(node, ast.ClassDef) and node.name == "KokiriShopChecksRemoved")
        scope = {"Removed": Removed}
        exec(compile(ast.Module(body=[removed], type_ignores=[]),
                     str(ROOT / "apworld/ootrr_remake/options.py"), "exec"), scope)
        option = scope["KokiriShopChecksRemoved"]
        for value in (False, "false", "False", "off", 0, "0", ""):
            with self.subTest(disabled_legacy_value=value):
                self.assertFalse(option(value).value)
        for value in (True, "true", "True", "on", 1, "1"):
            with self.subTest(enabled_legacy_value=value):
                with self.assertRaisesRegex(ValueError, "shuffle_shops: random_deals or deals_1"):
                    option(value)
        self.assertNotIn("kokiri_shop_checks", {spec["id"] for spec in OPTION_SPECS})
        w, _, _ = self.make_world(shops=True)
        w.options.kokiri_shop_checks = SimpleNamespace(value=False)
        self.assertEqual(namespace["option_values"](w.options)["shuffle_shops"], "deals_1")

    def test_ap_random_deals_choice_reaches_the_native_random_mode_at_the_same_index(self):
        w, _, _ = self.make_world(shops=True)
        native_choices = next(spec["choices"] for spec in OPTION_SPECS if spec["id"] == "shuffle_shops")
        w.options.shuffle_shops = SimpleNamespace(value=6, current_key="random_deals")
        values = namespace["option_values"](w.options)
        self.assertEqual(native_choices[6], "random")
        self.assertEqual(values["shuffle_shops"], "random")
        self.assertEqual(engine_settings(values)["shuffle_shops"], "random")
        w.generate_early()
        self.assertEqual(w.engine_calls[-1][1]["settings"]["shuffle_shops"], "random")

    def test_reverse_fill_preserves_early_slots_needed_by_counted_rules(self):
        w, names, rewards = self.make_world()
        w.create_regions()
        locations = [location for region in w.multiworld.regions for location in region.locations]

        def fill(order):
            # Reverse fill assumes every unplaced item is obtainable, then adds
            # already placed rewards only when their locations can be reached.
            remaining = [rewards[3], rewards[2], rewards[0], rewards[1]]
            unfilled, placed = list(order), {}
            while remaining:
                item = remaining.pop(0)
                counts = Counter(remaining)
                collected = set()
                changed = True
                while changed:
                    changed = False
                    for name, reward in placed.items():
                        if name not in collected and w.rules_at[w.waves[name]](State(**counts)):
                            collected.add(name)
                            counts[reward] += 1
                            changed = True
                location = next((location for location in unfilled
                                 if w.rules_at[w.waves[location.name]](State(**counts))), None)
                if location is None:
                    return None
                placed[location.name] = item
                unfilled.remove(location)
            return placed

        self.assertIsNone(fill(locations), "Late rewards should consume both scarce early slots in this counterexample")
        foreign = SimpleNamespace(player=2, name="Other player's location")
        unknown = SimpleNamespace(player=1, name="Untracked event")
        mixed = [foreign, locations[0], locations[2], unknown, locations[1], locations[3]]
        early = [location for location in mixed if location in locations and w.waves[location.name] == 0]
        late = [location for location in mixed if location in locations and w.waves[location.name] == 1]
        pool = [w.create_item(reward) for reward in rewards]
        before_pool = list(pool)
        w.fill_hook(pool, [], [], mixed)
        self.assertIs(mixed[0], foreign)
        self.assertIs(mixed[3], unknown)
        self.assertEqual(pool, before_pool)
        ordered = [location for location in mixed if location in locations]
        self.assertEqual(ordered, late + early)
        placed = fill(ordered)
        self.assertIsNotNone(placed)
        self.assertEqual(Counter(placed.values()), Counter(rewards))
        self.assertEqual([placed[name] for name in names[:2]], rewards[:2])

    def test_global_shop_selection_requires_complete_metadata_price_and_reachability_proof(self):
        def no_goods(generated):
            generated["seed_file"]["shops"].pop(next(iter(SHOP_CHECKS)))
        with self.assertRaisesRegex(ValueError, "catalogue is incomplete"):
            self.make_world(no_goods, shops=True)
        for price in (None, False, 0, 1000):
            def bad_price(generated):
                generated["seed_file"]["shops"][DEAL_NAMES[0]]["price"] = price
            with self.subTest(price=price), self.assertRaisesRegex(ValueError, "native shop reward list"):
                self.make_world(bad_price, shops=True)
        def no_reach(generated):
            generated["waves"][0].remove(DEAL_NAMES[-1])
        with self.assertRaisesRegex(ValueError, "did not prove"):
            self.make_world(no_reach, shops=True)


    def test_direct_yaml_values_reach_the_generator_as_native_json(self):
        changed = {"open_forest": "open", "starting_hearts": 6, "faster_blocks": True,
                   "starting_items": frozenset({"deku_shield"}), "trials": 3}
        w, _, _ = self.make_world(option_changes=changed)
        self.assertEqual(len(w.engine_calls), 1)
        command, request = w.engine_calls[0]
        self.assertEqual(command, "generate")
        self.assertIsInstance(request["settings"], dict)
        for name, value in changed.items():
            self.assertEqual(request["settings"][name], ["deku_shield"] if name == "starting_items" else value)
        self.assertNotIn("ootrr_settings", request["settings"])
        self.assertEqual(request["settings"]["shuffle_dungeon_rewards"], "vanilla")

    def test_incompatible_native_combinations_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "open_forest"):
            self.make_world(option_changes={"open_kakariko": "open"})


if __name__ == "__main__":
    unittest.main()
