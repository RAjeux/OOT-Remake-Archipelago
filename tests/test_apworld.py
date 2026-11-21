"""Exercise APWorld reward conservation and counted sphere rules without generating a room."""
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.catalog import CHESTS, DEFAULT_SETTINGS, FILLER, GAME, ITEM_DATA, ITEM_IDS, LOCATION_IDS, PROTOCOL, LOCATION_REWARD_MODE, SHOP_CHECKS
from ootrr_triforce.settings import OPTION_SPECS, default_options, engine_settings, validate_options


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
                 ItemClassification=SimpleNamespace(progression=1, filler=0))
option_tree = ast.parse((ROOT / "apworld/ootrr_remake/options.py").read_text(encoding="utf-8"))
option_values = next(node for node in option_tree.body if isinstance(node, ast.FunctionDef) and node.name == "option_values")
exec(compile(ast.Module(body=[option_values], type_ignores=[]),
             str(ROOT / "apworld/ootrr_remake/options.py"), "exec"), namespace)
exec(compile(ast.Module(body=[node for node in world.body if isinstance(node, ast.FunctionDef)], type_ignores=[]),
             str(ROOT / "apworld/ootrr_remake/__init__.py"), "exec"), namespace)
World = type("WorldMethods", (), {node.name: namespace[node.name] for node in world.body if isinstance(node, ast.FunctionDef)})


class AllChestRewardTests(unittest.TestCase):
    def make_world(self, changes=None, shops=False, option_changes=None, players=2):
        names = list(CHESTS)[:4]
        rewards = ["Small Key (Forest Temple)", "Small Key (Forest Temple)", "Rupees (20)", "Piece of Heart"]
        seed = dict(checksum="synthetic", placements=dict(zip(names, rewards)))
        generated = dict(seed_file=seed, waves=[names[:2] + ["Local NPC reward"], names[2:] + ["Ganon"]])
        if shops:
            seed["shops"] = {name: {"item": row["item"], "price": row["price"]} for name, row in SHOP_CHECKS.items()}
            generated["waves"][0].extend(SHOP_CHECKS)
        if changes:
            changes(generated)
        calls = []
        def run_engine(command, request):
            calls.append((command, request))
            return json.dumps(generated)
        namespace["run_engine"] = run_engine
        w = World()
        w.game, w.player, w.player_name = GAME, 1, "Zelda"
        w.random = SimpleNamespace(getrandbits=lambda bits: 17)
        values = default_options()
        values.update(death_link=True, shuffle_shops="shuffle" if shops else "off")
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

    def test_every_reward_is_conserved_and_repeated_keys_count(self):
        w, names, rewards = self.make_world()
        self.assertEqual(w.moved, dict(zip(names, rewards)))
        w.create_items()
        self.assertEqual(Counter(item.name for item in w.multiworld.itempool), Counter(rewards))
        self.assertNotIn(FILLER, [item.name for item in w.multiworld.itempool])
        self.assertTrue(all(item.classification == 1 for item in w.multiworld.itempool))
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

    def test_unsupported_reward_is_rejected(self):
        def change(generated):
            generated["seed_file"]["placements"][next(iter(CHESTS))] = "No native reward"
        with self.assertRaisesRegex(ValueError, "no Archipelago delivery"):
            self.make_world(change)

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

    def test_all_kokiri_goods_join_the_pool_and_counted_rules(self):
        w, names, rewards = self.make_world(shops=True)
        self.assertEqual(set(w.waves), set(names) | set(SHOP_CHECKS))
        goods = [row["item"] for row in SHOP_CHECKS.values()]
        w.create_items()
        self.assertEqual(Counter(item.name for item in w.multiworld.itempool), Counter(rewards + goods))
        w.create_regions()
        state = State(**{"Small Key (Forest Temple)": 2, **Counter(goods)})
        self.assertTrue(w.multiworld.completion_condition[1](state))
        state.counts[goods[0]] -= 1
        self.assertFalse(w.multiworld.completion_condition[1](state))
        self.assertIs(w.fill_slot_data()["kokiri_shop_checks"], True)
        self.assertIs(w.fill_slot_data()["foreign_only_shops"], False)
        self.assertEqual(sum(len(region.locations) for region in w.multiworld.regions), 12)
        locations = [location for region in w.multiworld.regions for location in region.locations]
        self.assertEqual(sum(location.name in SHOP_CHECKS for location in locations), 8)
        for location in locations:
            self.assertTrue(location.item_rule(SimpleNamespace(player=2)))
            self.assertTrue(location.item_rule(SimpleNamespace(player=1)))
        with tempfile.TemporaryDirectory() as folder:
            w.generate_output(folder)
            manifest = json.loads(next(Path(folder).glob("*.apootrr")).read_bytes())
            self.assertIs(manifest["kokiri_shop_checks"], True)
            self.assertIs(manifest["foreign_only_shops"], False)

    def test_shuffled_shops_work_in_a_single_player_pool(self):
        w, names, rewards = self.make_world(shops=True, players=1)
        w.create_items()
        w.create_regions()
        locations = [location for region in w.multiworld.regions for location in region.locations]
        shops = [location for location in locations if location.name in SHOP_CHECKS]
        self.assertEqual(len(shops), 8)
        self.assertEqual(len(w.multiworld.itempool), len(locations))
        self.assertEqual(w.engine_calls[0][1]["settings"]["shuffle_shops"], "shuffle")
        expected = Counter(rewards + [row["item"] for row in SHOP_CHECKS.values()])
        self.assertEqual(Counter(item.name for item in w.multiworld.itempool), expected)
        for location in shops:
            self.assertTrue(all(location.item_rule(item) for item in w.multiworld.itempool))
            self.assertTrue(location.item_rule(SimpleNamespace(player=2)))

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
                with self.assertRaisesRegex(ValueError, "shuffle_shops: shuffle"):
                    option(value)
        self.assertNotIn("kokiri_shop_checks", {spec["id"] for spec in OPTION_SPECS})
        w, _, _ = self.make_world(shops=True)
        w.options.kokiri_shop_checks = SimpleNamespace(value=False)
        self.assertEqual(namespace["option_values"](w.options)["shuffle_shops"], "shuffle")

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

    def test_kokiri_requires_every_price_and_reachability_proof(self):
        def no_goods(generated):
            generated["seed_file"]["shops"].pop(next(iter(SHOP_CHECKS)))
        with self.assertRaisesRegex(ValueError, "eight shop slots"):
            self.make_world(no_goods, shops=True)
        def no_reach(generated):
            generated["waves"][0].remove(next(iter(SHOP_CHECKS)))
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
