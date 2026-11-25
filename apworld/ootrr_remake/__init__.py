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
from .settings import engine_settings
from .shop_pool import SHOP_CHECK_MODE, shop_checks
from .master_sword import (SETTING as MASTER_SWORD_SETTING, ITEM as MASTER_SWORD_ITEM,
                           LOCATION as MASTER_SWORD_LOCATION, proof_wave as master_sword_wave,
                           token_material as master_sword_token)
from .network_catalog import SCHEMA as NETWORK_SCHEMA, SHOP_MODE as NETWORK_SHOP_MODE, validate_sources
from .network_placement import allowed as allowed_placement, placement_priority, prefill_scoped_items


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
    item_name_to_id = ITEM_IDS
    location_name_to_id = LOCATION_IDS
    required_client_version = (0, 6, 7)

    def generate_early(self):
        values = option_values(self.options)
        self.native_options = dict(values)
        settings = engine_settings(values)
        local_seed = f"AP-{self.random.getrandbits(64):016X}"
        generated = json.loads(run_engine("generate", {"settings": settings, "seed": local_seed}))
        progression = generated.get("progression_items")
        if (not isinstance(progression, list) or any(not isinstance(name, str) for name in progression)
                or len(progression) != len(set(progression))):
            raise ValueError("The packaged engine does not expose its progression proof.")
        self.progression_items = set(progression) & ITEM_IDS.keys()
        self.seed_file = generated["seed_file"]
        self.network_sources = validate_sources(generated)
        if not self.network_sources:
            raise ValueError("The packaged engine does not expose randomized network sources.")
        self.shop_checks = shop_checks(self.seed_file, mode=NETWORK_SHOP_MODE)
        self.shops_always_open = bool(values.get("shops_always_open", False))
        self.kokiri_shop_checks = False
        self.shuffle_skulltulas = values.get("shuffle_skulltulas", "off")
        self.adult_trade_shuffle = bool(values.get("adult_trade_shuffle", False))
        self.shuffle_master_sword = bool(values.get(MASTER_SWORD_SETTING, False))
        self.local_skulltulas = {}
        rewards = {name: row["generated_item"] for name, row in self.network_sources.items()}
        if self.adult_trade_shuffle and not set(TRADE_CHECKS) <= rewards.keys():
            raise ValueError("Adult trade shuffle requires all eleven supported trade rewards.")
        shops = self.seed_file.get("shops", {})
        rewards.update({name: shops[name]["item"] for name in self.shop_checks})
        proof_waves = [list(names) for names in generated["waves"]]
        missing = set(rewards) - {name for names in proof_waves for name in names}
        self.optional_sources = {name: row for name, row in generated.get("optional_sources", {}).items()
                                 if name in missing}
        if missing != set(self.optional_sources):
            raise ValueError("The engine did not prove access to these locations: "
                             + ", ".join(sorted(missing - self.optional_sources.keys())))
        # Native out-of-logic collectibles stay networked. They cannot provide
        # anything needed by the native proof: their region requires every
        # proven logical reward first. Unknown unproved sources still fail generation.
        if missing:
            hundred = "Kak 100 Gold Skulltula Reward"
            ordinary = sorted(missing - {hundred})
            if ordinary:
                proof_waves.append(ordinary)
            if hundred in missing:
                proof_waves.append([hundred])
        if self.shuffle_master_sword:
            self.progression_items.add(MASTER_SWORD_ITEM)
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
        start = Region("Menu", self.player, self.multiworld)
        self.multiworld.regions.append(start)
        self.rules_at = {}
        for wave in sorted({*self.waves.values(), self.goal_wave}):
            # Preserve the native search's logical inventory, including counted
            # keys, conditional hearts and progressive tiers. Nonlogical junk
            # must not create extra gates merely because it enters the AP pool.
            required = tuple(sorted(Counter(prize for name, prize in self.moved.items()
                                            if self.waves[name] < wave and prize in self.progression_items).items()))
            if ("Kak 100 Gold Skulltula Reward" in self.optional_sources
                    and self.waves["Kak 100 Gold Skulltula Reward"] == wave):
                counts = Counter(dict(required))
                token = "Gold Skulltula Token"
                # Unshuffled tokens retain their native sources. Every moved
                # token must be owned before the 100-token reward, even when
                # the native seed originally left that last token here.
                counts[token] = max(counts[token], sum(prize == token for prize in self.moved.values()))
                required = tuple(sorted((name, count) for name, count in counts.items() if count))
            rule = lambda state, counts=required: all(state.has(name, self.player, count) for name, count in counts)
            self.rules_at[wave] = rule
            region = Region(f"Hyrule {wave + 1}", self.player, self.multiworld)
            self.multiworld.regions.append(region)
            start.connect(region, rule=rule)
            for name, depth in self.waves.items():
                if depth == wave:
                    location = RemakeLocation(self.player, name, LOCATION_IDS[name], region)
                    if self.network_sources.get(name, {}).get("kind") != "shop":
                        # Shelf purchases can refuse a refill before payment.
                        # Other sources must always complete their own reward.
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
        if name in self.progression_items:
            classification = ItemClassification.progression
        else:
            # Maps/compasses and refills can have few legal locations. Use
            # AP's restrictive placement phase without counting them as logical
            # requirements or using them for progression balancing.
            classification = (ItemClassification.progression_skip_balancing
                              if placement_priority(name, self.native_options) else ItemClassification.filler)
        return RemakeItem(name, classification, ITEM_IDS[name], self.player)

    @classmethod
    def stage_set_rules(cls, multiworld):
        """Apply explicit Zelda placement modes to every world's AP locations.

        A keysanity item can leave Hyrule. A dungeon-only item must also be
        rejected by another game's location, so a Zelda-only rule is not enough.
        AP calls this hook after all worlds have installed their own rules.
        """
        for location in multiworld.get_locations():
            source_world = multiworld.worlds[location.player]
            source_options = getattr(source_world, "native_options", {})
            descriptor = getattr(source_world, "network_sources", {}).get(location.name, {})
            if location.name == MASTER_SWORD_LOCATION and source_world.game == GAME:
                descriptor = {"native_kind": "master_sword",
                              "placement": {"dungeon": None, "region_group": "castle"}}
            previous = location.item_rule
            def rule(item, previous=previous, source=location, source_world=source_world,
                     descriptor=descriptor, source_options=source_options):
                recipient = multiworld.worlds[item.player]
                if descriptor.get("placement", {}).get("junk_only"):
                    token = item.game == GAME and ITEM_DATA.get(item.name, {}).get("kind") == "Token"
                    if item.advancement or token:
                        return False
                return previous(item) and allowed_placement(
                    item.name, item.player, item.game, getattr(recipient, "native_options", {}),
                    source.name, source.player, source_world.game, descriptor, source_options)
            location.item_rule = rule

    @classmethod
    def stage_pre_fill(cls, multiworld):
        """Let AP place narrowly scoped pools before unrestricted rewards."""
        from Fill import fill_restrictive, sweep_from_pool
        prefill_scoped_items(multiworld, fill_restrictive, sweep_from_pool)

    def get_filler_item_name(self):
        return FILLER

    def create_items(self):
        self.multiworld.itempool.extend(self.create_item(self.moved[name]) for name in self.waves)

    def fill_hook(self, progitempool, usefulitempool, filleritempool, fill_locations):
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
        return {"protocol": PROTOCOL, "token": self.token, "checks": sorted(LOCATION_IDS[n] for n in self.waves),
                "death_link": bool(self.options.death_link.value), "reward_mode": LOCATION_REWARD_MODE,
                "local_items": True, "kokiri_shop_checks": self.kokiri_shop_checks,
                "shop_check_mode": NETWORK_SHOP_MODE, "shop_checks": sorted(self.shop_checks),
                "network_sources_schema": NETWORK_SCHEMA, "shops_always_open": self.shops_always_open,
                "foreign_only_shops": False, "shuffle_skulltulas": self.shuffle_skulltulas,
                "local_skulltulas": self.local_skulltulas, "adult_trade_shuffle": self.adult_trade_shuffle,
                MASTER_SWORD_SETTING: self.shuffle_master_sword}

    def generate_output(self, output_directory):
        output = {"game": self.game, "protocol": PROTOCOL, "room": self.multiworld.seed_name, "slot": self.player_name,
                  "player": self.player, "token": self.token, "seed_file": self.seed_file,
                  "checks": sorted(self.waves), "moved": self.moved,
                  "death_link": bool(self.options.death_link.value), "reward_mode": LOCATION_REWARD_MODE,
                  "local_items": True, "kokiri_shop_checks": self.kokiri_shop_checks,
                  "shop_check_mode": NETWORK_SHOP_MODE, "shop_checks": sorted(self.shop_checks),
                  "network_sources_schema": NETWORK_SCHEMA, "network_sources": self.network_sources,
                  "shops_always_open": self.shops_always_open,
                  "foreign_only_shops": False, "shuffle_skulltulas": self.shuffle_skulltulas,
                  "local_skulltulas": self.local_skulltulas, "adult_trade_shuffle": self.adult_trade_shuffle,
                  MASTER_SWORD_SETTING: self.shuffle_master_sword}
        path = Path(output_directory) / (self.multiworld.get_out_file_name_base(self.player) + ".apootrr")
        path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
