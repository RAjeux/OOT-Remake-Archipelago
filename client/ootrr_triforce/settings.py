"""Public AP settings, shared by the YAML writer and APWorld without AP imports.

The editor and exporters use this single typed schema. Native item strings
remain an internal format for reading historical player files.
"""
import copy
from importlib import resources
import json
import textwrap
from .feature_settings import (FEATURE_KEYS, FEATURE_SPECS, LEGACY_DIFFICULTY_KEYS,
                               LEGACY_DIFFICULTY_DEFAULTS, QUARANTINED_DEFAULTS,
                               unavailable_setting, validate_mapping)


def _spec(name, kind, default, description, group, **extra):
    return dict(id=name, kind=kind, default=default, description=description, group=group,
                label=name.replace("_", " ").title(), **extra)


def _choice(name, default, choices, description, group="World"):
    return _spec(name, "choice", default, description, group, choices=tuple(choices))


def _toggle(name, default, description, group="Quality of life", *, label=None):
    spec = _spec(name, "toggle", default, description, group)
    if label is not None:
        spec["label"] = label
    return spec


def _range(name, default, low, high, description, group="Difficulty", step=1):
    return _spec(name, "range", default, description, group, min=low, max=high, step=step)


STARTING_ITEMS = (
    "ocarina", "slingshot", "boomerang", "bow", "bomb_bag", "bombchus", "hookshot", "longshot",
    "megaton_hammer", "lens_of_truth", "magic_meter", "dins_fire", "farores_wind", "nayrus_love",
    "fire_arrows", "ice_arrows", "light_arrows", "iron_boots", "hover_boots", "goron_tunic", "zora_tunic",
    "mirror_shield", "bottle", "magic_beans", "stone_of_agony", "gerudo_card", "goron_bracelet",
    "silver_scale", "adult_wallet", "kokiri_sword", "deku_shield", "big_bullet_bag", "biggest_bullet_bag",
    "big_quiver", "biggest_quiver", "big_bomb_bag", "biggest_bomb_bag", "deku_sticks", "big_stick_bag",
    "biggest_stick_bag", "deku_nuts", "big_nut_bag", "biggest_nut_bag", "silver_gauntlets", "golden_gauntlets",
    "golden_scale", "giant_wallet", "double_magic", "ocarina_of_time", "two_bottles", "three_bottles",
    "four_bottles", "hylian_shield",
)
STARTING_SONGS = (
    "zeldas_lullaby", "eponas_song", "sarias_song", "suns_song", "song_of_time", "song_of_storms",
    "minuet_of_forest", "bolero_of_fire", "serenade_of_water", "requiem_of_spirit", "nocturne_of_shadow",
    "prelude_of_light",
)
SMALL_KEYS = ("vanilla", "dungeon", "any_dungeon", "keysanity")
BOSS_KEYS = ("remove", "vanilla", "dungeon", "regional", "overworld", "any_dungeon", "keysanity")
MAP_COMPASS = ("remove", "startwith", "vanilla", "dungeon", "regional", "any_dungeon", "keysanity")

_BASE_SPECS = (
    _toggle("death_link", False, "Share deaths with other DeathLink players.", "Archipelago"),
    _toggle("shops_always_open", False,
            "Keep the eight item shops and the Happy Mask Shop open by day and night. Quest requirements still apply; minigames keep their normal hours.", "World"),
    _choice("shuffle_chests", "all", ("off", "all", "overworld", "dungeons"),
            "Choose which ordinary chest rewards become AP checks: everywhere, outside dungeons, inside dungeons, or none. The three heart-piece chests follow Ground pickups and heart pieces instead, so Off does not disable them. Other enabled source families still work.", "Shuffle"),
    _choice("shuffle_shops", "off", ("off", "shuffle", "deals_1", "deals_2", "deals_3", "deals_4", "random"),
            "Any enabled mode turns all 64 purchases across eight shops into AP checks. Shuffle mixes the native stock; Deals adds special deals to the native item pool and price layout before AP fills the checks. These choices never force a recipient. random_deals rolls zero to four deals per shop; Archipelago's random chooses a whole shop mode, which may be Off.", "Shuffle"),
    _choice("shuffle_skulltulas", "off", ("off", "pinned", "matched"),
            "Off keeps Gold Skulltulas unchanged. Pinned selects 44 native sites; Matched selects all 100 as AP checks. Native filler-only restrictions remain at uncertain sites: no progression or Zelda tokens can be placed there. Collect the dropped reward to complete its check; killing the enemy alone does not complete it.", "Shuffle"),
    _choice("shuffle_smallkeys", "dungeon", SMALL_KEYS,
            "Keep small keys at their original rewards, restrict them to their own or any dungeon in your world, or mix them across Archipelago. Moving them to other dungeons or games requires shuffled dungeon chests.", "Dungeon items"),
    _choice("shuffle_bosskeys", "dungeon", BOSS_KEYS,
            "Choose where your boss keys can appear. Dungeon, region and overworld restrictions keep them in your own Zelda world; Anywhere allows other games. Remove opens the corresponding locks from the start. Moving keys outside their dungeon requires shuffled dungeon chests.", "Dungeon items"),
    _choice("shuffle_ganon_bosskey", "dungeon", (*BOSS_KEYS, "lacs_dungeons", "lacs_medallions"),
            "Choose where to find your Ganon Boss Key, remove its lock, or receive it from Zelda in the Light Arrows scene. That scene can count Stones and Medallions together or Medallions only, using the matching count below. It puts the Light Arrows into the AP pool and requires NPC rewards and dungeon chests.", "Dungeon items"),
    _choice("shuffle_mapcompass", "dungeon", MAP_COMPASS,
            "Choose where maps and compasses can appear. Dungeon and region restrictions stay in your own Zelda world; Anywhere allows other games. Remove and Start with both grant their map effects from the start.",
            "Dungeon items"),
    _choice("open_forest", "closed", ("closed", "open"),
            "Closed keeps Mido's sword-and-shield requirement and the opening quest. Open allows access to the Deku Tree and the forest exit from the start."),
    _choice("open_kakariko", "closed", ("closed", "open"),
            "Open unlocks the Death Mountain gate and skips the Zelda visit. Requires open_forest: open. The two skipped rewards are claimed at the start; shuffled checks follow their Archipelago placements."),
    _choice("zora_fountain", "closed", ("closed", "open"),
            "King Zora blocks the passage normally, or never blocks it."),
    _toggle("jabu_open", False, "Enter Jabu-Jabu without a fish once King Zora no longer blocks the passage.", "World"),
    _toggle("time_always_passes", True, "Enable the day/night cycle from the start of the game.", "World"),
    _toggle("early_beds", False, "Sleep until morning or night before meeting Zelda; requires time_always_passes.", "World"),
    _choice("gerudo_fortress", "normal", ("normal", "fast", "open"),
            "Rescue all four carpenters, rescue only the last one, or start with everyone rescued and the Membership Card already owned."),
    _choice("door_of_time_condition", "vanilla", ("vanilla", "stones", "song", "open"),
            "Open the Door of Time by clearing Dodongo and Jabu-Jabu, by holding the three Stones, with the Song of Time alone, or from the start. The first two choices use the separate Song of Time switch; Open and Song only use the separate Zelda's escape setting."),
    _choice("door_of_time_escape", "moat", ("vanilla", "stones", "moat"),
            "With the open or song condition, Zelda's escape waits for the two dungeons or three stones, or is skipped with the Ocarina available in the moat from the start."),
    _toggle("door_of_time_song", True,
            "With Original game or Three Spiritual Stones, require playing the Song of Time at the altar. If disabled, the door opens when the chosen requirement is met. Ignored with Open or Song of Time only.", "World"),
    _choice("bridge", "vanilla", ("vanilla", "dungeons", "open", "medallions"),
            "Make Ganon's bridge appear after the native Light Arrows scene, after a chosen combined Stone/Medallion count, after a Medallion-only count, or with no requirement when approached. Use the count matching the selected condition. This is separate from the Door of Time and Ganon Boss Key.", "Goal"),
    _range("bridge_rewards", 9, 0, 9,
           "Total Stones and Medallions you must hold for Count Stones and Medallions: any mix of the three Stones and six Medallions counts. Nine requires all nine; zero requires none. Unused with the original bridge condition.", "Goal"),
    _toggle("skip_ganon_trials", False, "Reach Ganon's Tower without completing the trials.", "Goal"),
    _range("trials", 6, 0, 6, "Number of Ganon's Castle trials required: six keeps all; zero skips all. Which trials remain is chosen for the seed. Ignored when Skip Ganon's trials is enabled.", "Goal"),
    _range("starting_hearts", 3, 1, 20, "Number of hearts at the start of the game.", "Starting inventory"),
    _spec("starting_items", "set", [],
          "Starting equipment, removed from the randomized pool. The highest selected upgrade wins. Starting Bombchus also require a bomb bag; Zelda's Letter is not selectable.",
          "Starting inventory", choices=STARTING_ITEMS),
    _spec("starting_songs", "set", [], "Songs known from the start; an ocarina is still needed to play them.",
          "Starting inventory", choices=STARTING_SONGS),
    _choice("start_reward", "off", ("off", "stone", "medal", "any"),
            "Start with a random native stone or medallion. The regular reward still exists.",
            "Starting inventory"),
    _toggle("faster_chests", False, "Shorten native chest-opening and item-receive scenes."),
    _toggle("faster_blocks", False, "Push and pull blocks twice as fast."),
    _toggle("skip_intro", True, "Skip the opening movie and Link's wake-up scene."),
    _toggle("skip_first_pickup_text", False, "Suppress the first pickup message for small consumables."),
    _choice("skip_cutscenes", "off", ("off", "story", "all"),
            "Keep native manual skipping, allow skipping the opening and credits, or also allow title-screen demos to be skipped. This does not automatically skip every cutscene; Skip introduction separately skips the opening movie and Link waking up.",
            "Quality of life"),
    _toggle("anju_one_cucco", False, "One Cucco is enough for Anju's bottle; logic follows this setting."),
    _toggle("big_poe_one", False, "One Big Poe is enough for the Poe Collector's bottle."),
    _choice("navi_return", "everywhere", ("off", "dungeons", "everywhere"),
            "Call Navi with the D-pad for a return-travel question: dungeon entrance only, or also Kokiri Forest as a child and the Temple of Time as an adult outside dungeons. Boss and miniboss arenas never offer it. It replaces ordinary area hints, not enemy-targeting hints.",
            "Quality of life"),
    _choice("bunny_hood", "off", ("off", "speed", "jump"),
            "While wearing the Bunny Hood, keep normal movement, run about 1.5 times as fast, or also jump farther. This does not grant the mask. Experimental.",
            "Quality of life"),
    _toggle("skip_epona_race", True, "Epona's Song grants Epona without racing Ingo.", "World"),
    _toggle("skip_mask_quest", False, "All masks are available when the shop opens.", "World"),
    _toggle("plant_beans", False, "Magic beans are already planted; their adult platforms are available.", "World"),
    _toggle("gerudo_bridge_open", False, "The Gerudo Valley bridge is repaired from the start.", "World"),
    _toggle("deku_bridge_safe", False, "The bridge in the Deku Tree slingshot room does not collapse.", "Quality of life"),
)
_PICKUP_NOTE = (" Enabled sources become AP checks only after collecting the drop. "
                "An uncollected source can be tried again after reloading the area; collected sources stay completed.")
_ADDITIONAL_SPECS = (
    _choice("shuffle_pots", "off", ("off", "overworld", "dungeons", "all"),
            "Shuffle rewards in the supported pots, including flying pots." + _PICKUP_NOTE, "Shuffle"),
    _choice("shuffle_crates", "off", ("off", "overworld", "dungeons", "all"),
            "Shuffle rewards in the supported crates." + _PICKUP_NOTE, "Shuffle"),
    _choice("shuffle_rocks", "off", ("off", "overworld", "dungeons", "all"),
            "Shuffle rewards under the supported rocks." + _PICKUP_NOTE, "Shuffle"),
    _choice("shuffle_grass", "off", ("off", "overworld", "dungeons", "all"),
            "Shuffle supported grass drops; Lost Woods bug grass is preserved." + _PICKUP_NOTE, "Shuffle"),
    _toggle("shuffle_beehives", False,
            "Shuffle the supported beehive drops." + _PICKUP_NOTE, "Shuffle"),
    _choice("shuffle_freestanding_items", "off", ("off", "pieces", "all", "dungeons", "overworld"),
            "Shuffle supported ground pickups as AP checks. Off and Pieces both shuffle heart pieces in this engine, including three dedicated heart-piece chests. All also adds ordinary rupees and recovery hearts; Dungeons or Overworld adds those ordinary pickups only in that area, while heart pieces stay enabled everywhere.", "Shuffle"),
    _choice("shuffle_rewards", "off", ("off", "supported"),
            "Turn supported NPC, minigame, Great Fairy and story rewards into AP checks. Songs and dungeon rewards have separate controls.", "Shuffle"),
    _toggle("shuffle_rewards_extra", False,
            "Also turn the supported 20-token reward, Biggoron and Medigoron rewards into AP checks. Requires NPC rewards to be enabled.", "Shuffle"),
    _toggle("shuffle_boss_hearts", False,
            "Turn boss heart-container pickups into AP checks. The assigned reward appears after the boss falls.", "Shuffle"),
    _choice("shuffle_songs", "off", ("off", "own", "anywhere"),
            "Turn supported song lessons into AP checks, with songs restricted to lessons or mixed into the wider pool. Scarecrow's Song is preserved. Experimental.", "Shuffle"),
    _toggle("shuffle_potion_shop", False,
            "Turn the Market Potion Shop's empty-bottle and bug-tutorial potion rewards into AP checks. Requires NPC rewards and an empty bottle.", "Shuffle"),
    _toggle("adult_trade_shuffle", False,
            "Make the adult trading quest AP checks and mix its ten quest items across the multiworld. Each NPC still requires and consumes the correct owned input, then gives only the AP reward. The starting Cucco is hatched, timed items never expire, and the final Claim Check has no three-day wait. Requires NPC rewards.",
            "Shuffle", label="Adult Trade Shuffle"),
    _toggle("shuffle_scrubs_a", False,
            "Add the three one-time sellers in Death Mountain Crater and the Lost Woods (near the bridge and front of the grotto) as AP checks. Requires NPC rewards; ordinary repeatable stock is separate.", "Shuffle"),
    _toggle("shuffle_scrubs_b", False,
            "Add the Jabu-Jabu seller and the rear Lost Woods grotto seller as one-time AP checks instead of their ordinary menus. Requires NPC rewards.", "Shuffle"),
    _toggle("shuffle_cows", False,
            "Turn supported cow rewards into AP checks. Requires NPC rewards; includes all cows supported by the engine.", "Shuffle"),
    _toggle("shuffle_treasure_reward", False,
            "Turn the Treasure Chest Game's first-win heart piece into an AP check; later wins retain their normal reward.", "Shuffle"),
    _choice("shuffle_dungeon_rewards", "vanilla", ("vanilla", "anywhere", "dungeons"),
            "Keep Spiritual Stones and Medallions unchanged, put them in the AP pool, or restrict them to dungeon reward checks. Non-vanilla modes require NPC rewards.", "Shuffle"),
    _toggle("shuffle_frog_songs", False,
            "Turn the five supported first-time frog-song rewards into AP checks. Requires NPC rewards.", "Shuffle"),
    _toggle("shuffle_frog_bug_heart", False,
            "Turn the frog bug game's first-win heart piece into an AP check. Requires NPC rewards.", "Shuffle"),
    _toggle("shuffle_ocarinas", False,
            "Turn Saria's Fairy Ocarina and Zelda's moat Ocarina of Time into AP checks and mix the instruments into the pool. Requires NPC rewards.", "Shuffle"),
    _toggle("shuffle_kokiri_sword", False,
            "Shuffle the Kokiri Sword when overworld chests are shuffled. Its catalogued chest participates in AP.", "Shuffle"),
    _toggle("shuffle_master_sword", False,
            "Mix the Master Sword into the multiworld and replace its first pedestal gift with one AP reward. Rauru's reward stays separate. You can travel in time before finding the sword, but must find it to finish the game. Requires a new room and a new save.", "Shuffle"),
    _choice("shuffle_entrances", "off", ("off", "dungeons"),
            "Shuffle the dungeon entrances supported by OOTRR. The native logic and mod use the same rolled entrances. Overworld and mixed entrance shuffles are not implemented.", "World"),
    _choice("shuffle_merchants", "off", ("off", "beans", "no_beans", "all"),
            "Choose the Bean Merchant's one AP purchase, Medigoron, or both. This does not include every NPC who asks for rupees. Later bean purchases stay native. Requires NPC rewards; Beans and All also require pre-planted beans.", "Shuffle"),
    _choice("shopsanity_prices", "starting", ("affordable", "starting", "adult", "giant"),
            "Set special-deal prices: 10 rupees each, or random prices up to 200, 500 or 995 rupees. The wallets hold 200, 500 and 1,000. Kokiri deals never exceed 200; ordinary goods keep their prices. Only used by a special-deal or random-deal shop mode.", "Economy"),
    _choice("scrub_prices", "vanilla", ("vanilla", "cheap", "fixed"),
            "Set enabled Deku Scrub sale prices: native, low random prices from 0 to 95 in steps of 5, or the fixed amount below. Cheap favors low prices; it does not mean 10 rupees each. Requires at least one Scrub shuffle.", "Economy"),
    _range("scrub_price_fixed", 10, 0, 99,
           "Price of each enabled shuffled Scrub sale with scrub_prices: fixed.", "Economy"),
    _toggle("scrub_hint_text", False,
            "Show the assigned item in enabled Deku Scrub offers instead of a mystery item. Requires at least one Scrub shuffle.", "Economy"),
    _choice("merchant_prices", "vanilla", ("vanilla", "cheap", "fixed"),
            "Set the selected merchant-sale prices: native, low random prices from 0 to 95 in steps of 5, or the fixed amount below. Cheap is random, not a fixed 10 rupees. This does not reprice every ordinary repeat purchase. Requires shuffled merchants.", "Economy"),
    _range("merchant_price_fixed", 10, 0, 99,
           "Price of each enabled shuffled merchant sale with merchant_prices: fixed.", "Economy"),
    _choice("fairy_prices", "vanilla", ("vanilla", "cheap", "fixed"),
            "Set the six Great Fairy offerings: native, low random amounts from 0 to 95 in steps of 5, or the fixed amount below. This applies whether their gifts are unchanged or shuffled; Cheap is not a fixed 10 rupees.", "Economy"),
    _range("fairy_price_fixed", 10, 0, 99,
           "Offering requested by each Great Fairy with fairy_prices: fixed.", "Economy"),
    _range("lacs_rewards", 9, 1, 9,
           "Total Spiritual Stones and Medallions needed for the native Light Arrows scene to grant Ganon's Boss Key with shuffle_ganon_bosskey: lacs_dungeons.", "Goal"),
    _toggle("song_harp_colors", True,
            "Color native song pickup harps to match their song. Only applies to shuffle_songs: anywhere. Experimental.", "Quality of life"),
)
OPTION_SPECS = _BASE_SPECS + _ADDITIONAL_SPECS + FEATURE_SPECS
SPEC_BY_ID = {spec["id"]: spec for spec in OPTION_SPECS}
AP_ONLY = (frozenset({"death_link", "shuffle_master_sword", "shops_always_open"})
           | (FEATURE_KEYS - LEGACY_DIFFICULTY_KEYS))
# Additions implemented by this integration's engine, not portable OOTRR 0.8.1.
ENGINE_EXTENSIONS = {"adult_trade_shuffle": {"kind": "toggle", "default": False}}
# The portable engine rejects its own schema's open value. Its existing native
# reward gate at zero gives the same unrestricted access on approaching it.
BRIDGE_OPEN_ALIAS = {"bridge": "dungeons", "bridge_rewards": 0}

# These native-engine constraints are not free-form YAML options. Public
# settings below replace their fixed values before the engine is invoked.
FIXED_SETTINGS = {
    "logic_rules": "glitchless", "starting_age": "child", "triforce_hunt": False,
    "shuffle_pots": "off", "shuffle_crates": "off", "shuffle_rocks": "off", "shuffle_grass": "off",
    "shuffle_beehives": False, "shuffle_freestanding_items": "off",
    "shuffle_scrubs": "off", "shuffle_hideoutkeys": "vanilla", "shuffle_rewards": "off",
    "shuffle_rewards_extra": False, "shuffle_dungeon_rewards": "vanilla", "shuffle_boss_hearts": False,
    "shuffle_songs": "off", "shuffle_ocarinas": False, "shuffle_kokiri_sword": False,
    "shuffle_trade_checks": False, "shuffle_cows": False, "shuffle_cows_other": False,
    "shuffle_frog_songs": False, "shuffle_frog_bug_heart": False, "shuffle_silver_rupees": False,
    "shuffle_potion_shop": False, "shuffle_scrubs_a": False, "shuffle_scrubs_b": False,
    "shuffle_merchants": "off",
    "shuffle_treasure_reward": False, "shuffle_entrances": "off", "bombchus_in_logic": False,
    "gossip_hints": False, "misc_hints": [], "chests_match_contents": False,
}
# Current new rooms apply difficulty once in the versioned feature pass. Keep
# the old builder's difficulty inputs explicitly inert, rather than scaling
# enemies there and scaling the same resources again afterward.
FIXED_SETTINGS.update(LEGACY_DIFFICULTY_DEFAULTS)
# Public source selectors use the same native randomization pass. The AP
# catalogue and delivery layer bind the selected checks after that pass.
for _specification in _ADDITIONAL_SPECS:
    FIXED_SETTINGS.pop(_specification["id"],None)
del _specification


def default_options():
    """Independent, explicit defaults for every supported public option."""
    return {spec["id"]: copy.deepcopy(spec["default"]) for spec in OPTION_SPECS}


_AP_CHOICE_KEYS = {
    ("shuffle_shops", "random"): "random_deals",
    ("cosmetic_color_mode", "random"): "random_colors",
}


def ap_choice_key(name, value):
    """Name an explicit native mode without taking AP's reserved random key."""
    return _AP_CHOICE_KEYS.get((name, value), value)


def native_choice_key(name, value):
    """Convert an AP Choice result after Archipelago has rolled its value."""
    return next((native for (setting, native), public in _AP_CHOICE_KEYS.items()
                 if setting == name and public == value), value)


def validate_options(values):
    """Validate public values and combinations before calling the native engine."""
    values = dict(values)
    for name, default in QUARANTINED_DEFAULTS.items():
        if name in values:
            if type(values[name]) is not type(default) or values[name] != default:
                raise unavailable_setting(name)
            values.pop(name)
    unknown = set(values).difference(SPEC_BY_ID)
    if unknown:
        raise ValueError("Unsupported Archipelago setting: " + ", ".join(sorted(unknown)))
    result = default_options()
    for name, value in values.items():
        spec = SPEC_BY_ID[name]
        kind = spec["kind"]
        if kind == "toggle":
            if not isinstance(value, (bool, int)) or value not in (False, True):
                raise ValueError(name + " must be true or false.")
            value = bool(value)
        elif kind == "choice":
            if value not in spec["choices"]:
                raise ValueError(name + " must be one of: " + ", ".join(spec["choices"]))
        elif kind == "range":
            if type(value) is not int or not spec["min"] <= value <= spec["max"]:
                raise ValueError(f"{name} must be an integer between {spec['min']} and {spec['max']}.")
            if (value - spec["min"]) % spec["step"]:
                raise ValueError(f"{name} uses steps of {spec['step']} from {spec['min']}.")
        elif kind == "set":
            if not isinstance(value, (list, tuple, set, frozenset)) or any(item not in spec["choices"] for item in value):
                raise ValueError(name + " contains an unsupported starting item.")
            value = [item for item in spec["choices"] if item in value]
        elif kind == "dict":
            value = validate_mapping(name, value)
        result[name] = value
    if result["open_kakariko"] == "open":
        if result["open_forest"] != "open":
            raise ValueError("open_kakariko: open requires open_forest: open.")
        if "zeldas_lullaby" in result["starting_songs"]:
            raise ValueError("Remove zeldas_lullaby from starting_songs when open_kakariko is open.")
    if result["early_beds"] and not result["time_always_passes"]:
        raise ValueError("early_beds requires time_always_passes: true.")
    if result["bridge"] == "open":
        if result["bridge_rewards"] not in {0, 9}:
            raise ValueError("bridge: open fixes bridge_rewards at zero; leave its default value or set it to zero.")
        result["bridge_rewards"] = 0
    elif result["bridge"] != "dungeons" and result["bridge_rewards"] != 9:
        raise ValueError("bridge_rewards is only used with bridge: dungeons.")
    if result["skip_ganon_trials"] and result["trials"] != 6:
        raise ValueError("trials is only used when skip_ganon_trials is false.")
    if result["door_of_time_condition"] in {"open", "song"}:
        if not result["door_of_time_song"]:
            raise ValueError("door_of_time_song is only used with the vanilla or stones condition.")
    elif result["door_of_time_escape"] != "moat":
        raise ValueError("door_of_time_escape is only used with the open or song condition.")
    if result["enemy_gates"] and result["open_forest"] != "closed":
        raise ValueError("enemy_gates requires open_forest: closed.")
    if "bombchus" in result["starting_items"] and not set(result["starting_items"]).intersection(
            {"bomb_bag", "big_bomb_bag", "biggest_bomb_bag"}):
        raise ValueError("Starting Bombchus also require a bomb bag in starting_items.")
    for name in ("shuffle_smallkeys", "shuffle_bosskeys", "shuffle_ganon_bosskey", "shuffle_mapcompass"):
        roaming = result[name] in {"regional", "overworld", "any_dungeon", "keysanity"}
        if roaming and result["shuffle_chests"] == "overworld":
            raise ValueError(name + " requires shuffle_chests: dungeons or all to move dungeon items.")
        if result[name] == "overworld" and result["shuffle_chests"] == "dungeons":
            raise ValueError(name + ": overworld requires shuffle_chests: all.")
    if result["shuffle_chests"]=="off":
        # The native source export includes ground rewards, NPCs and ordinary
        # shop stock too. Its exact selected catalogue, not a historical list
        # of AP-enabled families, determines whether a room has checks.
        for name in ("shuffle_smallkeys", "shuffle_bosskeys", "shuffle_ganon_bosskey", "shuffle_mapcompass"):
            if result[name] in {"regional", "overworld", "any_dungeon", "keysanity", "lacs_dungeons"}:
                raise ValueError(name + " requires shuffled chests for this placement mode.")
    npc_children=("shuffle_potion_shop", "shuffle_rewards_extra", "adult_trade_shuffle",
                  "shuffle_scrubs_a", "shuffle_scrubs_b", "shuffle_cows", "shuffle_frog_songs",
                  "shuffle_frog_bug_heart", "shuffle_ocarinas")
    for name in npc_children:
        if result[name] and result["shuffle_rewards"]!="supported":
            raise ValueError(name + " requires shuffle_rewards: supported.")
    if result["shuffle_dungeon_rewards"]!="vanilla" and result["shuffle_rewards"]!="supported":
        raise ValueError("shuffle_dungeon_rewards requires shuffle_rewards: supported.")
    if result["shuffle_kokiri_sword"] and result["shuffle_chests"] not in {"all", "overworld"}:
        raise ValueError("shuffle_kokiri_sword requires shuffle_chests: all or overworld.")
    if result["enemy_gates"] and result["shuffle_entrances"]!="off":
        raise ValueError("enemy_gates requires shuffle_entrances: off.")
    if result["shuffle_ganon_bosskey"] in {"lacs_dungeons", "lacs_medallions"}:
        if result["shuffle_rewards"]!="supported" or result["shuffle_chests"] not in {"all", "dungeons"}:
            raise ValueError("lacs_dungeons requires shuffle_rewards: supported and dungeon or all chests.")
    if result["shuffle_ganon_bosskey"] != "lacs_dungeons" and result["lacs_rewards"]!=9:
        raise ValueError("lacs_rewards is only used with shuffle_ganon_bosskey: lacs_dungeons.")
    if result["bridge"] != "medallions" and result["bridge_medallions"] != 6:
        raise ValueError("bridge_medallions is only used with bridge: medallions.")
    if result["shuffle_ganon_bosskey"] != "lacs_medallions" and result["lacs_medallions"] != 6:
        raise ValueError("lacs_medallions is only used with shuffle_ganon_bosskey: lacs_medallions.")
    if result["skulls_by_day"] and result["night_skulls_suns_song"]:
        raise ValueError("night_skulls_suns_song is only used when skulls_by_day is false.")
    if result["cosmetic_colors"] and result["cosmetic_color_mode"] != "custom":
        raise ValueError("cosmetic_colors is only used with cosmetic_color_mode: custom.")
    if not result["shuffle_ice_traps"] and result["ice_trap_count"] != 6:
        raise ValueError("ice_trap_count is only used with shuffle_ice_traps: true.")
    if result["shuffle_merchants"]!="off":
        if result["shuffle_rewards"]!="supported":
            raise ValueError("shuffle_merchants requires shuffle_rewards: supported.")
        if result["shuffle_merchants"] in {"beans", "all"} and not result["plant_beans"]:
            raise ValueError("Shuffling the Bean Merchant requires plant_beans: true.")
    deals=result["shuffle_shops"] in {"deals_1", "deals_2", "deals_3", "deals_4", "random"}
    if result["shopsanity_prices"]!="starting" and not deals:
        raise ValueError("shopsanity_prices requires a deals or random shop mode.")
    scrubs=result["shuffle_scrubs_a"] or result["shuffle_scrubs_b"]
    if (result["scrub_prices"]!="vanilla" or result["scrub_hint_text"]) and not scrubs:
        raise ValueError("Scrub prices and hints require shuffle_scrubs_a or shuffle_scrubs_b.")
    for kind in ("scrub", "merchant", "fairy"):
        if result[kind+"_price_fixed"]!=10 and result[kind+"_prices"]!="fixed":
            raise ValueError(kind+"_price_fixed is only used with "+kind+"_prices: fixed.")
    if result["merchant_prices"]!="vanilla" and result["shuffle_merchants"]=="off":
        raise ValueError("merchant_prices requires shuffle_merchants.")
    if not result["song_harp_colors"] and result["shuffle_songs"]!="anywhere":
        raise ValueError("song_harp_colors is only used with shuffle_songs: anywhere.")
    return result


def engine_settings(values):
    """A typed OOTRR JSON object; a settings string is never needed from players."""
    options = validate_options(values)
    result = copy.deepcopy(FIXED_SETTINGS)
    result.update({name: value for name, value in options.items()
                   if name not in AP_ONLY and name not in LEGACY_DIFFICULTY_KEYS})
    if options["bridge"] == "open":
        result.update(BRIDGE_OPEN_ALIAS)
    elif options["bridge"] == "medallions":
        result.update(bridge="dungeons", bridge_rewards=options["bridge_medallions"])
    if options["shuffle_ganon_bosskey"] == "lacs_medallions":
        # The legacy builder's combined-reward range starts at one. The
        # versioned feature pass applies the selected zero-medallion gate.
        result.update(shuffle_ganon_bosskey="lacs_dungeons", lacs_rewards=max(1, options["lacs_medallions"]))
    return result


def yaml_options(indent="  ", language="en", values=None):
    """OOTRR-only YAML block; the caller writes DeathLink separately."""
    selected = validate_options({} if values is None else values)
    french = str(language).lower().replace("_", "-").startswith("fr")
    descriptions = json.loads(resources.files(__package__).joinpath("settings_fr.json").read_text(encoding="utf-8")) if french else {}
    groups = {"Shuffle": "Mélange", "Dungeon items": "Objets de donjon", "World": "Monde", "Goal": "Objectif",
              "Starting inventory": "Inventaire initial", "Quality of life": "Confort", "Difficulty": "Difficulté",
              "Economy": "Économie", "Cosmetics": "Apparence et sons", "Planned placements": "Placements choisis"} if french else {}
    heading = "Objectif fixe : vaincre Ganon. Réglages compatibles AP uniquement." if french else "Fixed goal: defeat Ganon. AP-compatible settings only."
    lines = [indent + "# " + heading]
    previous = None
    for spec in OPTION_SPECS:
        if spec["id"] == "death_link":
            continue
        if spec["group"] != previous:
            lines += ["", indent + "# " + groups.get(spec["group"], spec["group"])]
            previous = spec["group"]
        lines += [indent + "# " + line for line in textwrap.wrap(descriptions.get(spec["id"], spec["description"]), width=94)]
        if spec["kind"] in ("choice", "set"):
            choices = [ap_choice_key(spec["id"], value) for value in spec["choices"]]
            lines += [indent + "# " + line for line in textwrap.wrap(("Valeurs : " if french else "Values: ") + ", ".join(choices), width=94)]
        elif spec["kind"] == "range":
            step = ((f", pas de {spec['step']}" if french else f", step {spec['step']}") if spec["step"] > 1 else "")
            limits = f"Entier : {spec['min']} à {spec['max']}" if french else f"Integer: {spec['min']} to {spec['max']}"
            lines.append(indent + f"# {limits}{step}.")
        value = selected[spec["id"]]
        if spec["kind"] == "choice":
            value = ap_choice_key(spec["id"], value)
        lines.append(indent + spec["id"] + ": " + json.dumps(value, ensure_ascii=False))
    return "\n".join(lines) + "\n"
