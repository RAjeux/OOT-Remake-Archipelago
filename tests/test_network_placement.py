"""Explicit native placement choices survive the final AP item placement."""
from copy import deepcopy
from pathlib import Path
from random import Random
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.catalog import GAME
from ootrr_triforce.network_catalog import SOURCES
from ootrr_triforce.network_placement import allowed, placement_priority, prefill_scoped_items, source_context


def physical(folder, *, kind="chest"):
    return {"kind": kind, "native_kind": kind,
            "variants": [{"file": "Banc/" + folder + "/Map_Static.bcett.byml.zs"}]}


class PlacementTests(unittest.TestCase):
    def permits(self, item="Small Key (Forest Temple)", *, mode="dungeon", source=None,
                item_player=1, source_player=1, source_game=GAME, item_game=GAME,
                option="shuffle_smallkeys", source_options=None, source_name="Native source"):
        return allowed(item, item_player, item_game, {option: mode}, source_name,
                       source_player, source_game, source or physical("ForestTemple"), source_options)

    def test_explicit_key_modes_use_real_physical_dungeons_and_regions(self):
        forest, fire = physical("ForestTemple"), physical("FireTemple")
        self.assertTrue(self.permits(source=forest))
        self.assertFalse(self.permits(source=fire))
        self.assertFalse(self.permits(source=forest, source_player=2))
        self.assertFalse(self.permits(source_game="Dark Souls III"))
        self.assertTrue(self.permits(mode="any_dungeon", source=fire))
        self.assertFalse(self.permits(mode="any_dungeon", source=physical("KokiriForest")))
        self.assertTrue(self.permits(item="Boss Key (Forest Temple)", option="shuffle_bosskeys",
                                     mode="regional", source=physical("LostWood")))
        self.assertFalse(self.permits(item="Boss Key (Forest Temple)", option="shuffle_bosskeys",
                                      mode="regional", source=physical("GoronCity")))
        self.assertTrue(self.permits(item="Boss Key (Forest Temple)", option="shuffle_bosskeys",
                                     mode="overworld", source=physical("KakarikoVillage")))
        self.assertFalse(self.permits(item="Boss Key (Forest Temple)", option="shuffle_bosskeys",
                                      mode="overworld", source=forest))

    def test_keysanity_and_ordinary_progression_have_no_global_owner_quota(self):
        for game in (GAME, "Dark Souls III", "Bloodborne"):
            for player in (1, 2, 3):
                self.assertTrue(self.permits(mode="keysanity", source_game=game, source_player=player))
                for item in ("Bow", "Bomb Bag", "Progressive Hookshot", "Master Sword"):
                    self.assertTrue(self.permits(item=item, source_game=game, source_player=player))
        self.assertTrue(self.permits(item="Small Key (Forest Temple)", item_game="Another game",
                                     source=physical("FireTemple")), "Foreign namespace collisions are not Zelda keys")

    def test_only_scarce_domains_get_nonlogical_fill_priority_not_junk_balancing(self):
        for item, option in (("Map (Ice Cavern)", "shuffle_mapcompass"),
                             ("Compass (Forest Temple)", "shuffle_mapcompass"),
                             ("Small Key (Forest Temple)", "shuffle_smallkeys")):
            self.assertTrue(placement_priority(item, {option: "dungeon"}))
            self.assertFalse(placement_priority(item, {option: "keysanity"}))
        self.assertTrue(placement_priority("Suns Song", {"shuffle_songs": "own"}))
        self.assertFalse(placement_priority("Suns Song", {"shuffle_songs": "anywhere"}))
        self.assertTrue(placement_priority("Goron Ruby", {"shuffle_dungeon_rewards": "dungeons"}))
        self.assertFalse(placement_priority("Goron Ruby", {"shuffle_dungeon_rewards": "anywhere"}))
        self.assertTrue(placement_priority("Buy Blue Fire", {}))
        for item in ("Rupee (1)", "Rupees (5)", "Recovery Heart", "Bow", "Bomb Bag"):
            self.assertFalse(placement_priority(item, {}), item)

    def test_all_dungeon_item_families_read_their_own_setting(self):
        examples = (("Small Key (Forest Temple)", "shuffle_smallkeys"),
                    ("Boss Key (Forest Temple)", "shuffle_bosskeys"),
                    ("Boss Key (Ganons Castle)", "shuffle_ganon_bosskey"),
                    ("Map (Forest Temple)", "shuffle_mapcompass"),
                    ("Compass (Forest Temple)", "shuffle_mapcompass"))
        for item, option in examples:
            with self.subTest(item=item):
                self.assertTrue(self.permits(item=item, option=option, mode="keysanity", source_game="Dark Souls III"))
                self.assertFalse(self.permits(item=item, option=option, mode="dungeon", source_game="Dark Souls III"))
                self.assertFalse(self.permits(item=item, option=option, mode="remove"))

    def test_song_only_categories_allow_other_zelda_players_but_not_other_item_types(self):
        song = {"kind": "flow", "native_kind": "song"}
        options = {"shuffle_songs": "own"}
        self.assertTrue(self.permits(item="Suns Song", option="shuffle_songs", mode="own", source=song,
                                    source_player=2, source_options=options))
        self.assertFalse(self.permits(item="Suns Song", option="shuffle_songs", mode="own", source=physical("ForestTemple")))
        self.assertFalse(self.permits(item="Suns Song", item_game="Other game", source=song, source_options=options))
        self.assertFalse(self.permits(item="Bow", source=song, source_options=options))
        self.assertTrue(self.permits(item="Suns Song", option="shuffle_songs", mode="anywhere", source_game="Dark Souls III"))

    def test_end_of_dungeons_rewards_have_two_sided_typed_restrictions(self):
        boss = {"kind": "flow", "native_kind": "dungeon_reward"}
        options = {"shuffle_dungeon_rewards": "dungeons"}
        self.assertTrue(self.permits(item="Goron Ruby", option="shuffle_dungeon_rewards", mode="dungeons",
                                    source=boss, source_player=2, source_options=options))
        self.assertFalse(self.permits(item="Goron Ruby", option="shuffle_dungeon_rewards", mode="dungeons",
                                     source_game="Dark Souls III"))
        self.assertFalse(self.permits(item="Bow", source=boss, source_options=options))
        self.assertFalse(self.permits(item="Goron Ruby", item_game="Other game", source=boss, source_options=options))
        self.assertTrue(self.permits(item="Goron Ruby", option="shuffle_dungeon_rewards", mode="anywhere",
                                    source_game="Dark Souls III"))

    def test_lacs_reserves_only_its_owners_key_and_its_native_scene(self):
        kwargs = dict(item="Boss Key (Ganons Castle)", option="shuffle_ganon_bosskey", mode="lacs_dungeons",
                      source={"kind": "flow", "native_kind": "cutscene_gift"},
                      source_options={"shuffle_ganon_bosskey": "lacs_dungeons"}, source_name="ToT Light Arrows Cutscene")
        self.assertTrue(self.permits(**kwargs))
        self.assertFalse(self.permits(**dict(kwargs, source_player=2)))
        self.assertFalse(self.permits(**dict(kwargs, source_name="Other scene")))
        self.assertFalse(self.permits(**dict(kwargs, item="Bow")))

    def test_flow_location_context_must_be_exported_not_guessed_from_its_name(self):
        self.assertEqual(source_context({"kind": "flow"}), (None, None, False))
        self.assertFalse(self.permits(source={"kind": "flow"}, source_name="Forest Temple Gift"))
        flow = {"kind": "flow", "placement": {"dungeon": "Forest Temple", "region_group": "forest"}}
        self.assertTrue(self.permits(source=flow))
        self.assertEqual(source_context(physical("ForestTemple")), ("Forest Temple", "forest", True))

    def test_every_existing_physical_catalogue_source_can_be_classified_without_mutation(self):
        before = deepcopy(SOURCES)
        physical_count = 0
        for name, row in SOURCES.items():
            if row["variants"]:
                physical_count += 1
                self.assertTrue(source_context(row)[2], name)
        self.assertGreater(physical_count, 1000)
        self.assertEqual(SOURCES, before)


class ScopePrefillTests(unittest.TestCase):
    def fixture(self):
        options = {"shuffle_songs": "own", "shuffle_dungeon_rewards": "dungeons",
                   "shuffle_mapcompass": "dungeon", "shuffle_smallkeys": "keysanity"}
        worlds = {player: SimpleNamespace(game=GAME, player=player, native_options=dict(options), waves={})
                  for player in (1, 2)}
        worlds[3] = SimpleNamespace(game="Dark Souls III", player=3)
        def item(name, player=1, game=GAME):
            return SimpleNamespace(name=name, player=player, game=game, location=None)
        selected = [item("Suns Song"), item("Serenade of Water", 2), item("Goron Ruby"), item("Map (Forest Temple)")]
        other = [item("Bow"), item("Rupee (1)"), item("Suns Song", 3, "Dark Souls III")]
        locations = []
        for player, name, descriptor in ((1, "Song1", {"native_kind": "song"}),
                                          (2, "Song2", {"native_kind": "song"}),
                                          (2, "Boss2", {"native_kind": "dungeon_reward"}),
                                          (1, "Forest", physical("ForestTemple"))):
            location = SimpleNamespace(name=name, player=player, address=100 + len(locations), item=None, locked=False)
            location.item_rule = lambda reward, location=location, descriptor=descriptor: allowed(
                reward.name, reward.player, reward.game, getattr(worlds[reward.player], "native_options", {}),
                location.name, location.player, GAME, descriptor, options)
            locations.append(location)
            worlds[player].waves[name] = len(locations)
        event = SimpleNamespace(name="Unaddressed event", player=1, address=None, item=None, locked=False,
                                item_rule=lambda _item: self.fail("Network rewards cannot prefill an unaddressed event"))
        all_locations = [*locations, event]
        multiworld = SimpleNamespace(itempool=[*selected, *other], worlds=worlds, state=object(), random=Random(17),
                                     get_unfilled_locations=lambda: [loc for loc in all_locations if loc.item is None])
        return multiworld, selected, other, all_locations

    def test_standard_ap_prefill_uses_other_items_as_assumed_and_keeps_cross_zelda_categories(self):
        multiworld, selected, other, locations = self.fixture()
        snapshot = deepcopy({player: getattr(world, "native_options", {}) for player, world in multiworld.worlds.items()})
        swept = []
        def sweep(state, pool):
            self.assertIs(state, multiworld.state)
            swept.extend(pool)
            return "assumed"
        def ap_fill(world, state, candidates, pool, **kwargs):
            self.assertIs(world, multiworld)
            self.assertEqual(state, "assumed")
            self.assertFalse(kwargs["single_player_placement"])
            self.assertFalse(kwargs["one_item_per_player"])
            self.assertTrue(kwargs["lock"])
            # Deterministic assignments test the helper contract, not a second
            # implementation of AP's fill algorithm (real AP has its own test).
            destinations = {"Suns Song": "Song2", "Serenade of Water": "Song1",
                            "Goron Ruby": "Boss2", "Map (Forest Temple)": "Forest"}
            for reward in list(pool):
                destination = next(loc for loc in candidates if loc.name == destinations[reward.name])
                self.assertTrue(destination.item_rule(reward))
                destination.item, destination.locked, reward.location = reward, True, destination
                pool.remove(reward)
        placed = prefill_scoped_items(multiworld, ap_fill, sweep)
        self.assertEqual({id(item) for item in placed}, {id(item) for item in selected})
        self.assertEqual([id(item) for item in multiworld.itempool], [id(item) for item in other])
        self.assertEqual({id(item) for item in swept}, {id(item) for item in other})
        self.assertTrue(all(item.location.player != item.player for item in selected if item.name != "Map (Forest Temple)"))
        self.assertIsNone(locations[-1].item)
        self.assertEqual(snapshot, {player: getattr(world, "native_options", {}) for player, world in multiworld.worlds.items()})

    def test_partial_ap_failure_restores_pool_locations_locks_and_rng(self):
        multiworld, selected, _other, locations = self.fixture()
        original_pool = multiworld.itempool
        ids_before = [id(item) for item in original_pool]
        random_before = multiworld.random.getstate()
        def fail(world, state, candidates, pool, **kwargs):
            reward = pool.pop()
            location = candidates[0]
            location.item, location.locked, reward.location = reward, True, location
            raise RuntimeError("Simulated AP FillError after a placement")
        with self.assertRaisesRegex(RuntimeError, "FillError"):
            prefill_scoped_items(multiworld, fail, lambda state, other: state)
        self.assertIs(multiworld.itempool, original_pool)
        self.assertEqual([id(item) for item in multiworld.itempool], ids_before)
        self.assertTrue(all(item.location is None for item in selected))
        self.assertTrue(all(loc.item is None and not loc.locked for loc in locations))
        self.assertEqual(multiworld.random.getstate(), random_before)

    def test_zero_domain_is_rejected_before_calling_ap_and_preserves_everything(self):
        multiworld, selected, _other, locations = self.fixture()
        for location in locations[:-1]:
            location.item_rule = lambda _item: False
        rng = multiworld.random.getstate()
        with self.assertRaisesRegex(ValueError, "No eligible AP locations"):
            prefill_scoped_items(multiworld, lambda *args, **kwargs: self.fail("No invalid fill call"),
                                 lambda state, other: state)
        self.assertTrue(all(item.location is None for item in selected))
        self.assertEqual(multiworld.random.getstate(), rng)

    def test_unrestricted_pool_skips_prefill_completely(self):
        multiworld, _selected, other, _locations = self.fixture()
        multiworld.itempool[:] = other
        before = list(multiworld.itempool)
        self.assertEqual(prefill_scoped_items(multiworld, lambda *args, **kwargs: self.fail("No fill"),
                                              lambda *args: self.fail("No state sweep")), ())
        self.assertEqual(multiworld.itempool, before)


if __name__ == "__main__":
    unittest.main()
