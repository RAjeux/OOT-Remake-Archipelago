"""Public AP settings, shared by the YAML writer and APWorld without AP imports.

Only tracked chest/shop shuffles are exposed. Native item strings remain an
internal seed-file format, so old player files still build with OOTRR 0.8.1.
"""
import copy
from importlib import resources
import json
import textwrap


def _spec(name, kind, default, description, group, **extra):
    return dict(id=name, kind=kind, default=default, description=description, group=group,
                label=name.replace("_", " ").title(), **extra)


def _choice(name, default, choices, description, group="World"):
    return _spec(name, "choice", default, description, group, choices=tuple(choices))


def _toggle(name, default, description, group="Quality of life"):
    return _spec(name, "toggle", default, description, group)


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
    _choice("shuffle_chests", "all", ("off", "all", "overworld", "dungeons"),
            "Shuffle all chests, overworld chests, or dungeon chests. off requires AP shops or Skulltulas. Only catalogued chests become network checks.", "Shuffle"),
    _choice("shuffle_shops", "off", ("off", "shuffle", "deals_1", "deals_2", "deals_3", "deals_4", "random"),
            "Use OOTRR's shop shuffle or add one to four special deals per shop. The eight Kokiri purchases become AP checks; other shops retain their native local rewards. Goods can belong to you or another player.", "Shuffle"),
    _choice("shuffle_skulltulas", "off", ("off", "pinned", "matched"),
            "Shuffle Gold Skulltula rewards: pinned uses 44 firmly identified locations; matched adds the supported researched matches, normally 76 checks or 77 with planted/starting beans. Uncertain matches stay local. A check is sent only after collecting the reward.", "Shuffle"),
    _choice("shuffle_smallkeys", "dungeon", SMALL_KEYS,
            "Keep small keys vanilla, in their own dungeon, in any dungeon, or anywhere. The last two choices require shuffled dungeon chests.", "Dungeon items"),
    _choice("shuffle_bosskeys", "dungeon", BOSS_KEYS,
            "Boss key placement. remove unlocks the doors from the start. Placements outside the original dungeon require shuffled dungeon chests.", "Dungeon items"),
    _choice("shuffle_ganon_bosskey", "dungeon", (*BOSS_KEYS, "lacs_dungeons"),
            "Ganon boss key placement. remove unlocks access from the start. lacs_dungeons grants it through the native Light Arrows scene after lacs_rewards; requires shuffled NPC rewards and dungeon chests.", "Dungeon items"),
    _choice("shuffle_mapcompass", "dungeon", MAP_COMPASS,
            "Map and compass placement. remove or startwith grants their effects from the start.",
            "Dungeon items"),
    _choice("open_forest", "closed", ("closed", "open"),
            "closed keeps Mido and the opening quest; open unlocks the forest exit and the Deku Tree."),
    _choice("open_kakariko", "closed", ("closed", "open"),
            "open unlocks the Death Mountain gate and skips the Zelda visit. Requires open_forest: open; Zelda's Letter and Impa's song are granted at the start."),
    _choice("zora_fountain", "closed", ("closed", "open"),
            "King Zora blocks the passage normally, or never blocks it."),
    _toggle("jabu_open", False, "Enter Jabu-Jabu without a fish once King Zora no longer blocks the passage.", "World"),
    _toggle("time_always_passes", True, "Enable the day/night cycle from the start of the game.", "World"),
    _toggle("early_beds", False, "Sleep until morning or night before meeting Zelda; requires time_always_passes.", "World"),
    _choice("gerudo_fortress", "normal", ("normal", "fast", "open"),
            "Rescue four carpenters, rescue one, or start with the fortress open."),
    _choice("door_of_time_condition", "vanilla", ("vanilla", "stones", "song", "open"),
            "Door of Time: complete Dodongo and Jabu-Jabu, collect all three stones, play only the Song of Time, or start with the door open."),
    _choice("door_of_time_escape", "moat", ("vanilla", "stones", "moat"),
            "With the open or song condition, Zelda's escape waits for the two dungeons or three stones, or is skipped with the Ocarina available in the moat from the start."),
    _toggle("door_of_time_song", True,
            "With the vanilla or stones condition, also require the Song of Time to open the door.", "World"),
    _choice("bridge", "vanilla", ("vanilla", "dungeons"),
            "Ganon bridge: native condition, or a total number of stones and medallions set by bridge_rewards.", "Goal"),
    _range("bridge_rewards", 9, 0, 9,
           "Number of stones and medallions required; only used with bridge: dungeons.", "Goal"),
    _toggle("skip_ganon_trials", False, "Reach Ganon's Tower without completing the trials.", "Goal"),
    _range("trials", 6, 0, 6, "Number of trials required when skip_ganon_trials is disabled.", "Goal"),
    _range("starting_hearts", 3, 1, 20, "Number of hearts at the start of the game.", "Starting inventory"),
    _spec("starting_items", "set", [],
          "Native starting equipment, removed from the local pool. The highest selected upgrade wins. Starting Bombchus also require a bomb bag; Zelda's Letter is not selectable.",
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
            "Allow skipping no cutscenes, the opening and ending, or also the title-screen demos.",
            "Quality of life"),
    _toggle("anju_one_cucco", False, "One Cucco is enough for Anju's bottle; logic follows this setting."),
    _toggle("big_poe_one", False, "One Big Poe is enough for the Poe Collector's bottle."),
    _choice("navi_return", "everywhere", ("off", "dungeons", "everywhere"),
            "Navi offers to return to the dungeon entrance, or also to Kokiri Forest/the Temple of Time outside dungeons.",
            "Quality of life"),
    _choice("bunny_hood", "off", ("off", "speed", "jump"),
            "Bunny Hood: normal effect, faster running, or faster running and enhanced jumps. Experimental.",
            "Quality of life"),
    _toggle("skip_epona_race", True, "Epona's Song grants Epona without racing Ingo.", "World"),
    _toggle("skip_mask_quest", False, "All masks are available when the shop opens.", "World"),
    _toggle("plant_beans", False, "Magic beans are already planted; their adult platforms are available.", "World"),
    _toggle("gerudo_bridge_open", False, "The Gerudo Valley bridge is repaired from the start.", "World"),
    _toggle("deku_bridge_safe", False, "The bridge in the Deku Tree slingshot room does not collapse.", "Quality of life"),
    _range("enemy_health", 100, 50, 500, "Enemy and boss health as a percentage (100 = normal). Experimental.", step=25),
    _range("enemy_damage", 100, 50, 500, "Enemy attack damage as a percentage; traps and falls are unchanged. Experimental.", step=25),
    _range("enemy_speed", 100, 75, 200, "Enemy speed as a percentage; some animations keep their original pace. Experimental.", step=5),
    _range("more_enemies", 100, 100, 1000, "Enemy density as a percentage (100 = normal), with native limits per area. Experimental.", step=50),
)
_DIFFICULTY = (
    ("enemy_regen", "Living enemies recover health after ten seconds without taking a hit."),
    ("enemy_backup", "Some enemies call for reinforcements during a prolonged fight."),
    ("no_heart_drops", "Random drops no longer give recovery hearts."),
    ("no_gossip_fairies", "Gossip stones no longer spawn fairies."),
    ("no_ammo_drops", "Random drops no longer give ammunition; shops and chests remain available."),
    ("lose_heart_on_death", "Lose one heart container after a Game Over, down to a minimum of three hearts."),
    ("no_bottles_in_combat", "Prevent bottle use while combat music is playing."),
    ("no_z_targeting", "Disable enemy targeting; interactions remain available."),
    ("no_dupe_items", "Native captures and refills reject contents already held in another bottle."),
    ("enemies_respawn_sooner", "Ordinary enemies return after leaving their room or area."),
    ("boss_minibosses", "Add a miniboss to compatible native boss arenas."),
    ("boss_minions", "Add lesser enemies to compatible boss arenas."),
    ("bean_pitch", "The Bean Seller occasionally mentions difficulty mods."),
    ("zora_ambush", "Add a Skulltula ambush to the Zora's Domain caves."),
    ("enemy_gates", "Block the Deku Tree passage until both Deku Babas are defeated; closed forest only."),
    ("cucco_revenge", "One hit on a Cucco triggers the Cucco attack."),
    ("enemy_spawn_combo", "Enable the native two-stick/D-pad shortcut to spawn practice enemies."),
    ("fairy_helps_enemies", "A fairy released from a bottle also heals awake enemies and bosses."),
)
_LOCAL_PICKUP_WARNING = (" Native local rewards retain their seed assignments. Experimental: destroyed sources stay used; "
                         "leaving a dropped reward behind can lose it. Save before breaking shuffled sources.")
_ADDITIONAL_SPECS = (
    _choice("shuffle_pots", "off", ("off", "overworld", "dungeons", "all"),
            "Shuffle rewards in the supported pots, including flying pots." + _LOCAL_PICKUP_WARNING, "Shuffle"),
    _choice("shuffle_crates", "off", ("off", "overworld", "dungeons", "all"),
            "Shuffle rewards in the supported crates." + _LOCAL_PICKUP_WARNING, "Shuffle"),
    _choice("shuffle_rocks", "off", ("off", "overworld", "dungeons", "all"),
            "Shuffle rewards under the supported rocks." + _LOCAL_PICKUP_WARNING, "Shuffle"),
    _choice("shuffle_grass", "off", ("off", "overworld", "dungeons", "all"),
            "Shuffle supported grass drops; Lost Woods bug grass is preserved." + _LOCAL_PICKUP_WARNING, "Shuffle"),
    _toggle("shuffle_beehives", False,
            "Shuffle the supported beehive drops." + _LOCAL_PICKUP_WARNING, "Shuffle"),
    _choice("shuffle_freestanding_items", "off", ("off", "pieces", "all", "dungeons", "overworld"),
            "Shuffle supported ground pickups. pieces limits this to heart pieces. Non-AP pickups keep their native local rewards; sources shared between ages retain OOTRR's duplication restrictions.", "Shuffle"),
    _choice("shuffle_rewards", "off", ("off", "supported"),
            "Shuffle supported NPC, minigame, fairy and story rewards locally with OOTRR. Songs and dungeon rewards have separate controls. These sources do not become AP checks.", "Shuffle"),
    _toggle("shuffle_rewards_extra", False,
            "Also shuffle the supported 20-token reward, Biggoron and Medigoron locally. Requires shuffle_rewards: supported.", "Shuffle"),
    _toggle("shuffle_boss_hearts", False,
            "Shuffle boss heart-container pickups locally. The assigned reward appears after the boss falls.", "Shuffle"),
    _choice("shuffle_songs", "off", ("off", "own", "anywhere"),
            "Shuffle the native song lessons among themselves or into the wider pool. Native lessons remain local; songs placed at AP locations join AP. Scarecrow's Song is preserved. Experimental.", "Shuffle"),
    _toggle("shuffle_potion_shop", False,
            "Shuffle the Market Potion Shop's empty-bottle and bug-tutorial potion rewards locally. Requires shuffle_rewards: supported; both checks need an empty bottle.", "Shuffle"),
    _toggle("shuffle_trade_checks", False,
            "Each supported adult trade hand-in grants one extra shuffled local reward the first time. Requires shuffle_rewards: supported.", "Shuffle"),
    _toggle("shuffle_scrubs_a", False,
            "Shuffle the first supported set of Deku Scrub sales locally. Requires shuffle_rewards: supported.", "Shuffle"),
    _toggle("shuffle_scrubs_b", False,
            "Shuffle the second supported set of Deku Scrub sales locally. Requires shuffle_rewards: supported.", "Shuffle"),
    _toggle("shuffle_cows", False,
            "Shuffle supported cow rewards locally. Requires shuffle_rewards: supported; the native plan includes its other supported cows too.", "Shuffle"),
    _toggle("shuffle_treasure_reward", False,
            "Shuffle the Treasure Chest Game's first-win heart piece locally; later wins retain their native reward.", "Shuffle"),
    _choice("shuffle_dungeon_rewards", "vanilla", ("vanilla", "anywhere", "dungeons"),
            "Keep Spiritual Stones and Medallions vanilla, put them in the wider pool, or restrict them to dungeon rewards. Requires shuffled NPC rewards for non-vanilla modes; native reward events remain local.", "Shuffle"),
    _toggle("shuffle_frog_songs", False,
            "Shuffle the five supported first-time frog-song rewards locally. Requires shuffle_rewards: supported.", "Shuffle"),
    _toggle("shuffle_frog_bug_heart", False,
            "Shuffle the frog bug game's first-win heart piece locally. Requires shuffle_rewards: supported.", "Shuffle"),
    _toggle("shuffle_ocarinas", False,
            "Shuffle Saria's Fairy Ocarina and Zelda's moat Ocarina of Time into the native pool. Requires shuffle_rewards: supported; their source events remain local.", "Shuffle"),
    _toggle("shuffle_kokiri_sword", False,
            "Shuffle the Kokiri Sword when overworld chests are shuffled. Its catalogued chest participates in AP.", "Shuffle"),
    _choice("shuffle_entrances", "off", ("off", "dungeons"),
            "Shuffle the dungeon entrances supported by OOTRR. The native logic and mod use the same rolled entrances. Overworld and mixed entrance shuffles are not implemented.", "World"),
    _choice("shuffle_merchants", "off", ("off", "beans", "no_beans", "all"),
            "Shuffle the supported Bean Merchant and Medigoron sales locally. Requires shuffled NPC rewards; beans and all also require plant_beans.", "Shuffle"),
    _choice("shopsanity_prices", "starting", ("affordable", "starting", "adult", "giant"),
            "Set the native special-deal price range by wallet tier. Requires a deals or random shop mode for a non-default value. Kokiri deals remain within the starting wallet; ordinary goods keep their prices.", "Economy"),
    _choice("scrub_prices", "vanilla", ("vanilla", "cheap", "fixed"),
            "Set prices for the enabled native-local Scrub sales. A non-default price mode requires shuffle_scrubs_a or shuffle_scrubs_b.", "Economy"),
    _range("scrub_price_fixed", 10, 0, 99,
           "Price of each enabled shuffled Scrub sale with scrub_prices: fixed.", "Economy"),
    _toggle("scrub_hint_text", False,
            "Enabled shuffled Scrubs name the actual native-local item instead of a mystery item. Requires a supported Scrub shuffle.", "Economy"),
    _choice("merchant_prices", "vanilla", ("vanilla", "cheap", "fixed"),
            "Set prices for the enabled native-local merchant sales. A non-default value requires shuffle_merchants.", "Economy"),
    _range("merchant_price_fixed", 10, 0, 99,
           "Price of each enabled shuffled merchant sale with merchant_prices: fixed.", "Economy"),
    _choice("fairy_prices", "vanilla", ("vanilla", "cheap", "fixed"),
            "Set the offering requested by the six native Great Fairies. Works with their vanilla or shuffled local rewards.", "Economy"),
    _range("fairy_price_fixed", 10, 0, 99,
           "Offering requested by each Great Fairy with fairy_prices: fixed.", "Economy"),
    _range("lacs_rewards", 9, 1, 9,
           "Total Spiritual Stones and Medallions needed for the native Light Arrows scene to grant Ganon's Boss Key with shuffle_ganon_bosskey: lacs_dungeons.", "Goal"),
    _toggle("song_harp_colors", True,
            "Color native song pickup harps to match their song. Only applies to shuffle_songs: anywhere. Experimental.", "Quality of life"),
)
OPTION_SPECS = _BASE_SPECS + _ADDITIONAL_SPECS + tuple(_toggle(name, False, description + " Experimental.", "Difficulty")
                                  for name, description in _DIFFICULTY)
SPEC_BY_ID = {spec["id"]: spec for spec in OPTION_SPECS}
AP_ONLY = frozenset({"death_link"})

# These are internal constraints, never free-form YAML options. In particular,
# bosses, pots, NPCs and other untracked rewards retain their native sources.
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
# Native-local sources keep the complete OOTRR seed reward. Only the explicit
# AP catalogue is moved a second time by Archipelago.
for _specification in _ADDITIONAL_SPECS:
    FIXED_SETTINGS.pop(_specification["id"],None)
del _specification


def default_options():
    """Independent, explicit defaults for every supported public option."""
    return {spec["id"]: copy.deepcopy(spec["default"]) for spec in OPTION_SPECS}


def validate_options(values):
    """Validate public values and combinations before calling the native engine."""
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
        result[name] = value
    if result["open_kakariko"] == "open":
        if result["open_forest"] != "open":
            raise ValueError("open_kakariko: open requires open_forest: open.")
        if "zeldas_lullaby" in result["starting_songs"]:
            raise ValueError("open_kakariko: open already grants Impa's song; remove zeldas_lullaby from starting_songs.")
    if result["early_beds"] and not result["time_always_passes"]:
        raise ValueError("early_beds requires time_always_passes: true.")
    if result["bridge"] != "dungeons" and result["bridge_rewards"] != 9:
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
        if result["shuffle_shops"]=="off" and result["shuffle_skulltulas"]=="off":
            raise ValueError("shuffle_chests: off requires shuffled AP shops or Skulltulas.")
        for name in ("shuffle_smallkeys", "shuffle_bosskeys", "shuffle_ganon_bosskey", "shuffle_mapcompass"):
            if result[name] in {"regional", "overworld", "any_dungeon", "keysanity", "lacs_dungeons"}:
                raise ValueError(name + " requires shuffled chests for this placement mode.")
    npc_children=("shuffle_potion_shop", "shuffle_rewards_extra", "shuffle_trade_checks",
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
    if result["shuffle_ganon_bosskey"]=="lacs_dungeons":
        if result["shuffle_rewards"]!="supported" or result["shuffle_chests"] not in {"all", "dungeons"}:
            raise ValueError("lacs_dungeons requires shuffle_rewards: supported and dungeon or all chests.")
    elif result["lacs_rewards"]!=9:
        raise ValueError("lacs_rewards is only used with shuffle_ganon_bosskey: lacs_dungeons.")
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
    result.update({name: value for name, value in options.items() if name not in AP_ONLY})
    return result


def yaml_options(indent="  ", language="en"):
    """OOTRR-only YAML block; the caller writes DeathLink separately."""
    french = str(language).lower().replace("_", "-").startswith("fr")
    descriptions = json.loads(resources.files(__package__).joinpath("settings_fr.json").read_text(encoding="utf-8")) if french else {}
    groups = {"Shuffle": "Mélange", "Dungeon items": "Objets de donjon", "World": "Monde", "Goal": "Objectif",
              "Starting inventory": "Inventaire initial", "Quality of life": "Confort", "Difficulty": "Difficulté",
              "Economy": "Économie"} if french else {}
    heading = "Objectif fixe : vaincre Ganon. Réglages compatibles AP uniquement." if french else "Fixed goal: defeat Ganon. AP-compatible settings only."
    lines = [indent + "# " + heading]
    previous = None
    for spec in OPTION_SPECS:
        if spec["id"] in AP_ONLY:
            continue
        if spec["group"] != previous:
            lines += ["", indent + "# " + groups.get(spec["group"], spec["group"])]
            previous = spec["group"]
        lines += [indent + "# " + line for line in textwrap.wrap(descriptions.get(spec["id"], spec["description"]), width=94)]
        if spec["kind"] in ("choice", "set"):
            lines += [indent + "# " + line for line in textwrap.wrap(("Valeurs : " if french else "Values: ") + ", ".join(spec["choices"]), width=94)]
        elif spec["kind"] == "range":
            step = ((f", pas de {spec['step']}" if french else f", step {spec['step']}") if spec["step"] > 1 else "")
            limits = f"Entier : {spec['min']} à {spec['max']}" if french else f"Integer: {spec['min']} to {spec['max']}"
            lines.append(indent + f"# {limits}{step}.")
        lines.append(indent + spec["id"] + ": " + json.dumps(spec["default"], ensure_ascii=False))
    return "\n".join(lines) + "\n"
