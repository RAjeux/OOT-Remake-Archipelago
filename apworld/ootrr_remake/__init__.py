import hashlib
import json
from collections import Counter
from pathlib import Path

from BaseClasses import Item, ItemClassification, Location, Region
from worlds.AutoWorld import WebWorld, World
from .catalog import CHESTS, FILLER, GAME, ITEM_DATA, ITEM_IDS, LOCATION_IDS, PROTOCOL, LOCATION_REWARD_MODE, SHOP_CHECKS
from .engine import run_engine
from .options import OPTION_GROUPS, RemakeOptions, option_values
from .settings import engine_settings


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
        settings = engine_settings(values)
        if values["kokiri_shop_checks"] and getattr(self.multiworld, "players", 2) < 2:
            raise ValueError("Les achats Kokiri pour les autres joueurs nécessitent une salle d'au moins deux joueurs.")
        local_seed = f"AP-{self.random.getrandbits(64):016X}"
        generated = json.loads(run_engine("generate", {"settings": settings, "seed": local_seed}))
        self.seed_file = generated["seed_file"]
        self.kokiri_shop_checks = bool(self.options.kokiri_shop_checks.value)
        rewards = {name: prize for name, prize in self.seed_file["placements"].items() if name in CHESTS}
        if self.kokiri_shop_checks:
            shops = self.seed_file.get("shops", {})
            if not all(name in shops for name in SHOP_CHECKS):
                raise ValueError("Les checks Kokiri nécessitent les huit boutiques générées par les réglages OOTRR de shuffle_shops.")
            rewards.update({name: shops[name]["item"] for name in SHOP_CHECKS})
        self.waves = {}
        self.moved = {}
        self.goal_wave = None
        for wave, names in enumerate(generated["waves"]):
            for name in names:
                if name == "Ganon":
                    self.goal_wave = wave
                if name in rewards:
                    self.waves[name] = wave
                    prize = rewards[name]
                    if prize not in ITEM_DATA:
                        raise ValueError(f"Récompense sans livraison Archipelago : {name} : {prize}")
                    metadata = ITEM_DATA[prize]
                    if metadata["mode"] == "generic" and not metadata.get("dungeon"):
                        raise ValueError(f"Récompense de donjon sans destination Archipelago : {name} : {prize}")
                    self.moved[name] = prize
        if self.goal_wave is None or not self.moved:
            raise ValueError("Cette configuration ne fournit pas de victoire Ganon et d’emplacements échangeables.")
        missing = set(rewards).difference(self.waves)
        if missing:
            raise ValueError("Le moteur n’a pas démontré l’accès à ces emplacements : " + ", ".join(sorted(missing)))
        self.token = hashlib.sha256(f"{self.multiworld.seed_name}/{self.player}/{self.seed_file['checksum']}".encode()).hexdigest()

    def create_regions(self):
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
                    if name in SHOP_CHECKS:
                        location.item_rule = lambda item, player=self.player: item.player != player
                    region.locations.append(location)
        self.multiworld.completion_condition[self.player] = self.rules_at[self.goal_wave]

    def create_item(self, name):
        classification = ItemClassification.filler if name == FILLER else ItemClassification.progression
        return RemakeItem(name, classification, ITEM_IDS[name], self.player)

    def get_filler_item_name(self):
        return FILLER

    def create_items(self):
        self.multiworld.itempool.extend(self.create_item(self.moved[name]) for name in self.waves)

    def fill_slot_data(self):
        return {"protocol": PROTOCOL, "token": self.token, "checks": sorted(LOCATION_IDS[n] for n in self.waves),
                "death_link": bool(self.options.death_link.value), "reward_mode": LOCATION_REWARD_MODE,
                "local_items": True, "kokiri_shop_checks": self.kokiri_shop_checks,
                "foreign_only_shops": self.kokiri_shop_checks}

    def generate_output(self, output_directory):
        output = {"game": self.game, "protocol": PROTOCOL, "room": self.multiworld.seed_name, "slot": self.player_name,
                  "player": self.player, "token": self.token, "seed_file": self.seed_file,
                  "checks": sorted(self.waves), "moved": self.moved,
                  "death_link": bool(self.options.death_link.value), "reward_mode": LOCATION_REWARD_MODE,
                  "local_items": True, "kokiri_shop_checks": self.kokiri_shop_checks,
                  "foreign_only_shops": self.kokiri_shop_checks}
        path = Path(output_directory) / (self.multiworld.get_out_file_name_base(self.player) + ".apootrr")
        path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
