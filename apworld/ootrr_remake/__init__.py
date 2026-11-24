import hashlib
import json
from collections import Counter
from pathlib import Path

from BaseClasses import Item, ItemClassification, Location, Region
from worlds.AutoWorld import WebWorld, World
from .catalog import (AP_SKULL_CHECKS, CHESTS, FILLER, GAME, ITEM_DATA, ITEM_IDS, LOCATION_IDS,
                      PINNED_SKULL_CHECKS, PROTOCOL, LOCATION_REWARD_MODE, SHOP_CHECKS, SKULL_CHECKS, TRADE_CHECKS)
from .engine import run_engine
from .options import OPTION_GROUPS, RemakeOptions, option_values
from .full_ap import item_ids as full_item_ids, location_ids as full_location_ids
from .settings import engine_settings
from .shop_pool import SHOP_CHECK_MODE, shop_checks
from .master_sword import (SETTING as MASTER_SWORD_SETTING, ITEM as MASTER_SWORD_ITEM,
                           LOCATION as MASTER_SWORD_LOCATION, proof_wave as master_sword_wave,
                           token_material as master_sword_token)


class RemakeWeb(WebWorld):
    option_groups = OPTION_GROUPS


class RemakeItem(Item):
    game = GAME


class RemakeLocation(Location):
    game = GAME


class RemakeWorld(World):
    """Play the Ocarina of Time remake in a multiworld using OOTRR."""
    game = GAME
    web = RemakeWeb()
    options_dataclass = RemakeOptions
    item_name_to_id = full_item_ids()
    location_name_to_id = full_location_ids()
    required_client_version = (0, 6, 7)

    def generate_early(self):
        if getattr(getattr(self.options, "generation_mode", None), "current_key", "legacy") == "full_network":
            return self._generate_full_network()
        values = option_values(self.options)
        settings = engine_settings(values)
        local_seed = f"AP-{self.random.getrandbits(64):016X}"
        generated = json.loads(run_engine("generate", {"settings": settings, "seed": local_seed}))
        self.seed_file = generated["seed_file"]
        self.shop_checks = shop_checks(self.seed_file)
        self.kokiri_shop_checks = False
        self.shuffle_skulltulas = values.get("shuffle_skulltulas", "off")
        self.adult_trade_shuffle = bool(values.get("adult_trade_shuffle", False))
        self.shuffle_master_sword = bool(values.get(MASTER_SWORD_SETTING, False))
        eligible_skulls = (PINNED_SKULL_CHECKS if self.shuffle_skulltulas == "pinned" else
                           AP_SKULL_CHECKS if self.shuffle_skulltulas == "matched" else frozenset())
        self.local_skulltulas = {}
        if self.shuffle_skulltulas != "off":
            self.local_skulltulas = {
                name: ("Native-only: actor mapping is outside the pinned set; OOTRR's reward stays local."
                       if self.shuffle_skulltulas == "pinned" else
                       "Native-only: uncertain actor mapping; OOTRR's generated reward stays local.")
                for name in self.seed_file["placements"] if name in SKULL_CHECKS and name not in eligible_skulls}
            reachable = {name for wave in generated["waves"] for name in wave}
            bean_ride = "ZR GS Near Raised Grottos"
            # OOTRR explicitly marks this optional bean ride out of logic until
            # beans are preplanted or the player starts with all ten beans.
            # Keep its native reward rather than exporting an unproved AP check.
            if (bean_ride in self.seed_file["placements"] and bean_ride not in reachable
                    and not values.get("plant_beans") and "magic_beans" not in values.get("starting_items", ())):
                self.local_skulltulas[bean_ride] = (
                    "Native-only: OOTRR does not prove this bean ride without preplanted or starting beans.")
        rewards = {name: prize for name, prize in self.seed_file["placements"].items()
                   if name in CHESTS or (name in eligible_skulls and name not in self.local_skulltulas)
                   or (self.adult_trade_shuffle and name in TRADE_CHECKS)}
        if self.adult_trade_shuffle and not set(TRADE_CHECKS) <= rewards.keys():
            raise ValueError("Adult trade shuffle requires all eleven supported trade rewards.")
        shops = self.seed_file.get("shops", {})
        rewards.update({name: shops[name]["item"] for name in self.shop_checks})
        proof_waves = [list(names) for names in generated["waves"]]
        if self.shuffle_master_sword:
            # The native engine still proves vanilla sword ownership at the
            # first draw. Export its grant independently of the Time Travel
            # event, using the pedestal observer even when NPCs are vanilla.
            sword_wave = (master_sword_wave(proof_waves, generated["master_sword_wave"])
                          if "master_sword_wave" in generated else master_sword_wave(proof_waves))
            proof_waves[sword_wave].append(MASTER_SWORD_LOCATION)
            rewards[MASTER_SWORD_LOCATION] = MASTER_SWORD_ITEM
        self.waves = {}
        self.moved = {}
        self.goal_wave = None
        for wave, names in enumerate(proof_waves):
            for name in names:
                if name == "Ganon":
                    self.goal_wave = wave
                if name in rewards:
                    self.waves[name] = wave
                    prize = rewards[name]
                    if prize not in ITEM_DATA:
                        raise ValueError(f"Reward has no Archipelago delivery: {name}: {prize}")
                    metadata = ITEM_DATA[prize]
                    if metadata["mode"] == "generic" and not metadata.get("dungeon"):
                        raise ValueError(f"Dungeon reward has no Archipelago destination: {name}: {prize}")
                    self.moved[name] = prize
        if self.goal_wave is None or not self.moved:
            raise ValueError("This configuration provides no Ganon victory and exchangeable locations.")
        missing = set(rewards).difference(self.waves)
        if missing:
            raise ValueError("The engine did not prove access to these locations: " + ", ".join(sorted(missing)))
        self.token = hashlib.sha256(master_sword_token(self.multiworld.seed_name, self.player,
            self.seed_file['checksum'], self.shuffle_master_sword).encode()).hexdigest()

    def create_regions(self):
        if getattr(self, "full_world", None) is not None:
            return self._create_full_regions()
        start = Region("Menu", self.player, self.multiworld)
        self.multiworld.regions.append(start)
        self.rules_at = {}
        for wave in sorted({*self.waves.values(), self.goal_wave}):
            # The native search already collects reachable non-AP rewards, including
            # events, shops and starting inventory. Requiring every AP reward from
            # earlier spheres preserves that reachability proof after AP moves them.
            # Counts matter: repeated keys, hearts and progressive tiers are distinct.
            required = tuple(sorted(Counter(prize for name, prize in self.moved.items()
                                            if self.waves[name] < wave).items()))
            rule = lambda state, counts=required: all(state.has(name, self.player, count) for name, count in counts)
            self.rules_at[wave] = rule
            region = Region(f"Hyrule {wave + 1}", self.player, self.multiworld)
            self.multiworld.regions.append(region)
            start.connect(region, rule=rule)
            for name, depth in self.waves.items():
                if depth == wave:
                    location = RemakeLocation(self.player, name, LOCATION_IDS[name], region)
                    if name in AP_SKULL_CHECKS:
                        # The native drop commits collection after its get event.
                        # A refill could fail without an empty bottle, so keep
                        # those local rewards at sources that can refuse them.
                        def skull_item_rule(item, player=self.player):
                            metadata = ITEM_DATA.get(getattr(item, "name", ""), {})
                            refill = metadata.get("bottle_item") and metadata.get("pouch_special") == "NotPushToPouch"
                            return item.player != player or not refill
                        location.item_rule = skull_item_rule
                    region.locations.append(location)
        goal = self.rules_at[self.goal_wave]
        self.multiworld.completion_condition[self.player] = (
            (lambda state: goal(state) and state.has(MASTER_SWORD_ITEM, self.player))
            if self.shuffle_master_sword else goal)

    def create_item(self, name):
        if getattr(self, "full_world", None) is not None:
            from BaseClasses import ItemClassification as FullItemClassification
            from .full_ap import item_ids
            kinds = {"progression": FullItemClassification.progression, "useful": FullItemClassification.useful,
                     "filler": FullItemClassification.filler}
            return RemakeItem(name, kinds[self.full_world.classification(name)], item_ids()[name], self.player)
        classification = ItemClassification.filler if name == FILLER else ItemClassification.progression
        return RemakeItem(name, classification, ITEM_IDS[name], self.player)

    def get_filler_item_name(self):
        if getattr(self, "full_world", None) is not None:
            return "Rupee (1)"
        return FILLER

    def create_items(self):
        if getattr(self, "full_world", None) is not None:
            self.multiworld.itempool.extend(self.create_item(name) for name in self.full_world.pool)
            return
        self.multiworld.itempool.extend(self.create_item(self.moved[name]) for name in self.waves)

    def fill_hook(self, progitempool, usefulitempool, filleritempool, fill_locations):
        if getattr(self, "full_world", None) is not None:
            return
        # Reverse fill should consume later reachable shelves/chests first. With
        # counted sphere gates, filling scarce early slots with later rewards can
        # otherwise strand the earlier rewards needed to unlock the rest.
        # Keep AP's random order within each sphere and every other player's
        # position; this changes neither item ownership nor the access proof.
        indexes = [index for index, location in enumerate(fill_locations)
                   if location.player == self.player and location.name in self.waves]
        ordered = sorted((fill_locations[index] for index in indexes),
                         key=lambda location: self.waves[location.name], reverse=True)
        for index, location in zip(indexes, ordered):
            fill_locations[index] = location

    def fill_slot_data(self):
        if getattr(self, "full_world", None) is not None:
            output = self._full_manifest()
            return {"protocol": PROTOCOL, "token": output['token'], "generation_mode": "full_network",
                    "full_format_version": output['full_format_version'],
                    "checks": sorted(output['location_ids'].values()),
                    "death_link": bool(self.options.death_link.value), "reward_mode": "all_locations",
                    "local_items": True, "catalog_scan": self.full_world.catalog["scan"]}
        return {"protocol": PROTOCOL, "token": self.token, "checks": sorted(LOCATION_IDS[n] for n in self.waves),
                "death_link": bool(self.options.death_link.value), "reward_mode": LOCATION_REWARD_MODE,
                "local_items": True, "kokiri_shop_checks": self.kokiri_shop_checks,
                "shop_check_mode": SHOP_CHECK_MODE, "shop_checks": sorted(self.shop_checks),
                "foreign_only_shops": False, "shuffle_skulltulas": self.shuffle_skulltulas,
                "local_skulltulas": self.local_skulltulas, "adult_trade_shuffle": self.adult_trade_shuffle,
                MASTER_SWORD_SETTING: self.shuffle_master_sword}

    def generate_output(self, output_directory):
        if getattr(self, "full_world", None) is not None:
            return self._output_full_network(output_directory)
        output = {"game": self.game, "protocol": PROTOCOL, "room": self.multiworld.seed_name, "slot": self.player_name,
                  "player": self.player, "token": self.token, "seed_file": self.seed_file,
                  "checks": sorted(self.waves), "moved": self.moved,
                  "death_link": bool(self.options.death_link.value), "reward_mode": LOCATION_REWARD_MODE,
                  "local_items": True, "kokiri_shop_checks": self.kokiri_shop_checks,
                  "shop_check_mode": SHOP_CHECK_MODE, "shop_checks": sorted(self.shop_checks),
                  "foreign_only_shops": False, "shuffle_skulltulas": self.shuffle_skulltulas,
                  "local_skulltulas": self.local_skulltulas, "adult_trade_shuffle": self.adult_trade_shuffle,
                  MASTER_SWORD_SETTING: self.shuffle_master_sword}
        path = Path(output_directory) / (self.multiworld.get_out_file_name_base(self.player) + ".apootrr")
        path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    def _generate_full_network(self):
        from .options import full_option_values
        from .full_ap import new_world
        values = full_option_values(self.options)
        key = f"archipelago|{self.multiworld.seed_name}|{self.player}"
        self.full_world = new_world(values, key)
        # Final ownership/placements are not known yet. Both slot_data and the
        # player file materialize the same final manifest after fill.
        self.token, self._full_manifest_cache = None, None
        extra = dict(getattr(getattr(self.options, "start_inventory", None), "value", {}))
        from_pool = dict(getattr(getattr(self.options, "start_inventory_from_pool", None), "value", {}))
        error = self.full_world.starting_error(extra, from_pool)
        if error:
            raise ValueError("Full-network starting inventory: " + error)
        self.options.local_items.value |= self.full_world.local_only

    def _create_full_regions(self):
        from BaseClasses import LocationProgressType
        from .full_ap import location_ids
        ids, full, player = location_ids(), self.full_world, self.player
        region = Region("Menu", player, self.multiworld)
        self.multiworld.regions.append(region)
        for gid in sorted(full.names):
            name = full.names[gid]
            location = RemakeLocation(player, name, ids[name], region)
            location.access_rule = lambda state, gid=gid: full.reachable(gid, state.prog_items[player])
            if not full.in_logic[gid]:
                location.progress_type = LocationProgressType.EXCLUDED
            location.item_rule = lambda item, gid=gid: full.can_hold(gid, item.name if item.player == player and item.game == GAME else None)
            region.locations.append(location)
        self.multiworld.completion_condition[player] = lambda state: full.reach(state.prog_items[player])[1]

    def pre_fill(self):
        if getattr(self, "full_world", None) is None:
            return
        from Fill import FillError, fill_restrictive
        from BaseClasses import LocationProgressType
        full = self.full_world
        restricted = [item for item in self.multiworld.itempool if item.player == self.player and item.name in full.restricted]
        for item in restricted:
            self.multiworld.itempool.remove(item)
        progression = [item for item in restricted if item.advancement]
        if progression:
            places = self.multiworld.get_unfilled_locations(self.player)
            self.random.shuffle(places)
            fill_restrictive(self.multiworld, self.multiworld.get_all_state(False), places, progression,
                             single_player_placement=True, lock=True, allow_excluded=False,
                             name="Ocarina of Time Remake dungeon items")
        for item in (item for item in restricted if not item.advancement):
            places = [place for place in self.multiworld.get_unfilled_locations(self.player)
                      if place.can_fill(self.multiworld.state, item, False)]
            if not places:
                raise FillError("No full-network location can hold " + item.name)
            junk = [place for place in places if place.progress_type == LocationProgressType.EXCLUDED]
            self.random.choice(junk or places).place_locked_item(item)

    def _output_full_network(self, output_directory):
        output = self._full_manifest()
        path = Path(output_directory) / (self.multiworld.get_out_file_name_base(self.player) + ".apootrr")
        path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    def _full_manifest(self):
        if self._full_manifest_cache is not None:
            return self._full_manifest_cache
        from .full_ap import manifest
        full = self.full_world
        spheres = {}
        for index, sphere in enumerate(self.multiworld.get_spheres()):
            for location in sphere:
                if location.player == self.player and location.name in full.gids:
                    spheres[full.gids[location.name]] = index
        placements = {}
        for gid, name in full.names.items():
            item = self.multiworld.get_location(name, self.player).item
            own = item.player == self.player and item.game == GAME
            if not full.can_hold(gid, item.name if own else None):
                raise ValueError("The full-network source cannot grant its assigned item: " + name)
            placements[gid] = {"item": item.name, "own": own,
                               "player": self.multiworld.get_player_name(item.player), "game": item.game,
                               "progression": bool(item.advancement), "sphere": spheres.get(gid)}
        remote = [{"item": location.item.name, "location": location.name,
                   "player": self.multiworld.get_player_name(location.player)}
                  for location in self.multiworld.get_locations()
                  if location.item and location.address is not None and location.item.player == self.player
                  and location.player != self.player]
        start = [item.name for item in self.multiworld.precollected_items[self.player]]
        output = manifest(full, placements, remote, self.multiworld.seed_name, self.player_name,
                          self.player, bool(self.options.death_link.value), start)
        self.token, self._full_manifest_cache = output['token'], output
        return output
