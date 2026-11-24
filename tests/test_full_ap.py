"""Real full-engine access proofs and protocol compatibility (no game required)."""
from collections import Counter
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))

from ootrr_triforce.catalog import ITEM_IDS, LOCATION_IDS
from ootrr_triforce.full_ap import (full_defaults, full_option_specs, full_yaml_options, item_ids,
                                    location_ids, manifest, new_world, translate_legacy_options,
                                    validate_full_options, validate_manifest, patch_token)


class FullNetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = new_world(full_defaults(), "full-network-regression")
        cls.inventory = Counter(cls.world.pool)

    def test_every_active_source_and_victory_has_an_actual_complete_inventory_proof(self):
        self.assertGreater(len(self.world.names), 1000)
        self.assertEqual(len(self.world.pool), len(self.world.names))
        self.assertTrue(self.world.reach(self.inventory)[1])
        unreachable = [name for gid, name in self.world.names.items()
                       if not self.world.reachable(gid, self.inventory)]
        self.assertEqual(unreachable, [])
        families = Counter(entry["source"] for entry in self.world.c.shuffled.values())
        self.assertEqual(families["skulltula"], 98)
        self.assertEqual(families["shop"], 64)
        self.assertEqual(families["adult_trade"], 11)
        self.assertEqual(families["native_cow"], 8)
        for family in ("npc", "song", "boss", "bossheart", "fairy", "pots", "crates", "trees"):
            self.assertGreater(families[family], 0, family)

    def test_token_threshold_rewards_are_real_progression_locations(self):
        for threshold in (10, 20, 30, 40, 50):
            gid = self.world.gids[f"Kak {threshold} Gold Skulltula Reward"]
            self.assertTrue(self.world.in_logic[gid])
            missing = self.inventory.copy()
            missing["Gold Skulltula Token"] = threshold - 1
            self.assertFalse(self.world.reachable(gid, missing))
            missing["Gold Skulltula Token"] = threshold
            self.assertTrue(self.world.reachable(gid, missing))

    def test_adult_trades_require_the_exact_item_without_forcing_previous_trades(self):
        pairs = (("LW Trade Cojiro", "Cojiro"), ("LW Trade Odd Potion", "Odd Potion"),
                 ("DMT Biggoron", "Claim Check"), ("ZD Trade Prescription", "Prescription"))
        for name, required in pairs:
            gid = self.world.gids[name]
            self.assertTrue(self.world.in_logic[gid])
            missing = self.inventory.copy()
            missing.pop(required, None)
            self.assertFalse(self.world.reachable(gid, missing), name)
            self.assertEqual(self.inventory[required], 1)
        # Owning the potion independently allows Fado even without Cojiro.
        independent = self.inventory.copy()
        independent.pop("Cojiro", None)
        self.assertTrue(self.world.reachable(self.world.gids["LW Trade Odd Potion"], independent))
        self.assertNotIn("quest#DMT Biggoron", self.world.c.shuffled)
        self.assertEqual(self.inventory["Biggoron Sword"], 1)

    def test_foreign_items_are_allowed_at_every_shop_and_trade_source(self):
        for gid, entry in self.world.c.shuffled.items():
            if entry["source"] in {"shop", "adult_trade", "npc", "song"}:
                with self.subTest(source=gid):
                    self.assertTrue(self.world.can_hold(gid, None))

    def test_unproved_child_only_sources_are_not_exported_as_unreachable_checks(self):
        self.assertNotIn("HountedWasteland#crates#17072091790119450948", self.world.names)
        self.assertNotIn("scrub#DMC Deku Scrub", self.world.names)

    def test_ten_finite_bean_purchases_export_ten_real_beans_without_planting_them(self):
        self.assertFalse(full_defaults()["full_plant_beans"])
        self.assertEqual(self.inventory["Magic Bean"], 10)
        checks = [entry for entry in self.world.c.shuffled.values() if 'bean_index' in entry]
        self.assertEqual(sorted(entry['bean_index'] for entry in checks), list(range(10)))
        for count in (0, 1, 9, 10):
            inventory = self.inventory.copy()
            inventory['Magic Bean'] = count
            state, _, _ = self.world.c.sweep({}, inventory)
            self.assertEqual(self.world.c.logic.accessible(state, "Colossus Freestanding PoH"), count == 10)
            for expression in ('_oot_has_beans', '_oot_has_beans()'):
                self.assertEqual(self.world.c.logic.compile(expression)(state, inventory, 'adult'), count == 10)

    def test_all_original_protocol_ids_remain_identical(self):
        self.assertTrue(all(item_ids()[name] == number for name, number in ITEM_IDS.items()))
        self.assertTrue(all(location_ids()[name] == number for name, number in LOCATION_IDS.items()))
        for values in (item_ids(), location_ids()):
            self.assertEqual(len(values), len(set(values.values())))
            self.assertTrue(all(0 < number < 1 << 31 for number in values.values()))

    def test_manifest_binds_room_player_catalogue_and_ids(self):
        placements = {gid: {"item": "Other game's item", "own": False, "player": "Friend",
                            "game": "Other Game", "progression": False, "sphere": None}
                      for gid in self.world.names}
        data = manifest(self.world, placements, [], "Room", "Zelda", 1, True)
        self.assertIs(validate_manifest(data), data)
        self.assertEqual(data["item_pool"], dict(Counter(self.world.pool)))
        for field, changed in (("room", "Wrong room"), ("player", 2), ("token", "0" * 64),
                               ("reward_mode", "legacy_gear")):
            broken = copy.deepcopy(data)
            broken[field] = changed
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_manifest(broken)
        broken = copy.deepcopy(data)
        broken["location_ids"][data["checks"][0]] += 1
        with self.assertRaises(ValueError):
            validate_manifest(broken)

    def test_full_yaml_uses_explicit_mode_and_reserved_random_alias(self):
        text = full_yaml_options(name="A name with spaces")
        self.assertIn('generation_mode: "full_network"', text)
        self.assertIn('full_shopsanity: "all"', text)
        self.assertNotIn("option_random", text)
        for spec in full_option_specs():
            if spec["kind"] == "choice":
                self.assertNotIn("random", spec["choices"])

    def test_player_file_derived_metadata_cannot_change_the_physical_postpasses(self):
        placements = {gid: {'item': 'Foreign reward', 'own': False, 'player': 'Friend', 'game': 'Other Game'}
                      for gid in self.world.names}
        original = manifest(self.world, placements, [], 'MetadataRoom', 'Zelda', 1)
        mutations = (
            ('adult_trade_shuffle', False), ('catalog_scan', 'wrong'), ('death_link', 'false'),
            ('player', True), ('player', 0), ('protocol', True), ('checks', [{}]),
            ('item_pool', {'Rupee (1)': len(self.world.pool)}),
            ('full_options', dict(original['full_options'], shuffle_cows=False)),
        )
        for field, value in mutations:
            changed = copy.deepcopy(original)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_manifest(changed)
        changed = copy.deepcopy(original)
        changed['full_patch']['game_build'] = 'Another game build'
        changed['token'] = patch_token(changed['full_patch'])
        with self.assertRaisesRegex(ValueError, 'game build'):
            validate_manifest(changed)

    def test_full_manifest_validation_does_not_import_physical_codecs(self):
        placements = {gid: {'item': 'Foreign reward', 'own': False, 'player': 'Friend', 'game': 'Other Game'}
                      for gid in self.world.names}
        data = manifest(self.world, placements, [], 'PureValidation', 'Zelda', 1)
        code = '''import builtins,json,sys
sys.path.insert(0,sys.argv[1])
original=builtins.__import__
def guarded(name,*args,**kwargs):
    if name.split('.')[0] in {'zstandard','ainb','evfl'}:
        raise AssertionError('Physical codec imported: '+name)
    return original(name,*args,**kwargs)
builtins.__import__=guarded
from ootrr_triforce.full_ap import validate_manifest
with open(sys.argv[2],encoding='utf-8') as source: validate_manifest(json.load(source))
'''
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'player.apootrr'
            path.write_text(json.dumps(data), encoding='utf-8')
            process = subprocess.run([sys.executable, '-B', '-c', code, str(ROOT / 'client'), str(path)],
                                     capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)

    @unittest.skipUnless(importlib.util.find_spec('zstandard'), 'native build codec not installed')
    def test_patch_order_has_one_native_resource_identity_without_mutating_the_input(self):
        from ootrr_full.archipelago.bridge import settings_from_patch
        from ootrr_full.randomizer.randomizer_core import settings_identity
        placements = {gid: {'item': 'Foreign reward', 'own': False, 'player': 'Friend', 'game': 'Other Game'}
                      for gid in self.world.names}
        remote = [{'item': 'Rupee (1)', 'location': 'B', 'player': 'Z'},
                  {'item': 'Arrows (30)', 'location': 'A', 'player': 'A'}]
        data = manifest(self.world, placements, remote, 'CanonicalBuild', 'Zelda', 1,
                        precollected=['Kokiri Sword', 'Rupees (5)'])
        patch = data['full_patch']
        before = copy.deepcopy(patch)
        reordered = copy.deepcopy(patch)
        reordered['remote'].reverse()
        reordered['precollected'].reverse()
        self.assertEqual(patch_token(patch), patch_token(reordered))
        self.assertEqual(settings_identity(settings_from_patch(patch)),
                         settings_identity(settings_from_patch(reordered)))
        self.assertEqual(patch, before)

    def test_room_identity_binds_final_options_rewards_ownership_and_starting_inventory(self):
        patch = {'seed_name': 'RepeatedRoom', 'options': {'a': True, 'b': False},
                 'placements': {'chest': {'item': 'Bow', 'own': True}},
                 'remote': [{'player': 'Z', 'location': 'B', 'item': 'Bow'},
                            {'player': 'A', 'location': 'A', 'item': 'Bottle'}],
                 'precollected': ['Bottle', 'Kokiri Sword']}
        token = patch_token(patch)
        reordered = copy.deepcopy(patch)
        reordered['options'] = {'b': False, 'a': True}
        reordered['remote'].reverse()
        reordered['precollected'].reverse()
        self.assertEqual(token, patch_token(reordered))
        for field, value in (('options', {'a': False, 'b': False}),
                             ('placements', {'chest': {'item': 'Slingshot', 'own': True}}),
                             ('placements', {'chest': {'item': 'Bow', 'own': False}}),
                             ('remote', []), ('precollected', ['Bottle'])):
            changed = copy.deepcopy(patch)
            changed[field] = value
            self.assertNotEqual(token, patch_token(changed), field)

    def test_virtual_logic_events_cannot_be_given_as_starting_items(self):
        for item in ('Time Travel', 'Triforce', 'Forest Trial Clear', 'Water Trial Clear'):
            with self.subTest(item=item):
                self.assertIn('native effect', self.world.starting_error({item: 1}, {}))
        self.assertIsNone(self.world.starting_error({'Magic Bean': 1, 'Kokiri Sword': 1}, {}))

    def test_exposed_settings_have_unique_names(self):
        names = [row['id'] for row in full_option_specs()]
        self.assertEqual(len(names), len(set(names)))

    def test_conflicting_or_unsupported_native_settings_are_not_silently_discarded(self):
        changed = translate_legacy_options({"shuffle_shops": "random", "shuffle_skulltulas": "matched", "shuffle_cows": False})
        self.assertEqual(changed["full_shopsanity"], "randomized")
        self.assertEqual(changed["full_tokensanity"], "all")
        self.assertFalse(changed["full_shuffle_cows"])
        self.assertEqual(validate_full_options(changed), changed)
        with self.assertRaisesRegex(ValueError, "legacy"):
            translate_legacy_options({"enemy_damage": 200})
        explicit = full_defaults()
        explicit["full_shopsanity"] = "2"
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            translate_legacy_options({"shuffle_shops": "deals_3"}, explicit)


if __name__ == "__main__":
    unittest.main()
