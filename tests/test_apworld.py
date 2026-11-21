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
        self.item_rule = lambda item: True


class Item:
    def __init__(self, name, classification, address, player):
        self.name, self.classification, self.address = name, classification, address


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
        values.update(death_link=True, kokiri_shop_checks=shops)
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
        with tempfile.TemporaryDirectory() as folder:
            w.generate_output(folder)
            manifest = json.loads(next(Path(folder).glob("*.apootrr")).read_bytes())
            self.assertEqual(manifest["moved"], dict(zip(names, rewards)))
            self.assertEqual(manifest["reward_mode"], LOCATION_REWARD_MODE)
            self.assertIs(manifest["death_link"], True)

    def test_unsupported_reward_is_rejected(self):
        def change(generated):
            generated["seed_file"]["placements"][next(iter(CHESTS))] = "No native reward"
        with self.assertRaisesRegex(ValueError, "sans livraison Archipelago"):
            self.make_world(change)

    def test_active_chest_without_reachability_proof_is_rejected(self):
        def change(generated):
            generated["waves"][0].remove(next(iter(CHESTS)))
        with self.assertRaisesRegex(ValueError, "pas démontré"):
            self.make_world(change)

    def test_dungeon_reward_without_destination_is_rejected(self):
        for reward in ("Map", "Compass", "Small Key", "Boss Key"):
            with self.subTest(reward=reward):
                def change(generated):
                    generated["seed_file"]["placements"][next(iter(CHESTS))] = reward
                with self.assertRaisesRegex(ValueError, "sans destination Archipelago"):
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
        self.assertIs(w.fill_slot_data()["foreign_only_shops"], True)
        self.assertEqual(sum(len(region.locations) for region in w.multiworld.regions), 12)
        locations = [location for region in w.multiworld.regions for location in region.locations]
        self.assertEqual(sum(location.name in SHOP_CHECKS for location in locations), 8)
        for location in locations:
            self.assertTrue(location.item_rule(SimpleNamespace(player=2)))
            self.assertEqual(location.item_rule(SimpleNamespace(player=1)), location.name not in SHOP_CHECKS)

    def test_kokiri_requires_every_price_and_reachability_proof(self):
        def no_goods(generated):
            generated["seed_file"]["shops"].pop(next(iter(SHOP_CHECKS)))
        with self.assertRaisesRegex(ValueError, "huit boutiques"):
            self.make_world(no_goods, shops=True)
        def no_reach(generated):
            generated["waves"][0].remove(next(iter(SHOP_CHECKS)))
        with self.assertRaisesRegex(ValueError, "pas démontré"):
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

    def test_single_player_kokiri_and_incompatible_native_combinations_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "deux joueurs"):
            self.make_world(shops=True, players=1)
        with self.assertRaisesRegex(ValueError, "open_forest"):
            self.make_world(option_changes={"open_kakariko": "open"})


if __name__ == "__main__":
    unittest.main()
