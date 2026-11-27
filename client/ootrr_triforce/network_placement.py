"""Final AP placement constraints for the existing native settings.

This predicate never fills, rolls or grants items. Apply it to AP locations'
item_rule, using the recipient's settings as well as the source world's.
"""
from .catalog import GAME, LEGACY_GAME, ITEM_DATA

ZELDA_GAMES = frozenset((GAME, LEGACY_GAME))
LACS_SOURCE = "ToT Light Arrows Cutscene"
GANON_KEY = "Boss Key (Ganons Castle)"

# Same dungeon folders and regional groups as native slice/dungeon_items.rs.
DUNGEON_FOLDERS = {
    "InsideTheDekuTree": "Deku Tree", "DodongoCavern": "Dodongos Cavern",
    "InsideJabuJabuBelly": "Jabu Jabus Belly", "ForestTemple": "Forest Temple",
    "FireTemple": "Fire Temple", "WaterTemple": "Water Temple", "ShadowTemple": "Shadow Temple",
    "SpiritTemple": "Spirit Temple", "BottomOfTheWell": "Bottom of the Well", "IceCavern": "Ice Cavern",
    "GerudoTrainingGround": "Gerudo Training Ground", "InsideGanonCastle": "Ganons Castle",
}
REGION_FOLDERS = {
    "forest": ("KokiriForest", "LostWood", "SacredForestMeadow", "InsideTheDekuTree", "ForestTemple"),
    "mountain": ("DeathMountainTrail", "DeathMountainCrater", "GoronCity", "DodongoCavern", "FireTemple"),
    "water": ("ZoraRiver", "ZoraDomain", "ZoraFountain", "InsideJabuJabuBelly", "IceCavern", "WaterTemple"),
    "kakariko": ("KakarikoVillage", "Graveyard", "BottomOfTheWell", "ShadowTemple"),
    "gerudo": ("GerudoValley", "GerudoFortress", "HountedWasteland", "DesertColossus", "SpiritTemple", "GerudoTrainingGround"),
    "castle": ("HyruleField", "Market", "HyruleCastle", "GanonCastle", "InsideGanonCastle"),
}
FOLDER_REGION = {folder: region for region, folders in REGION_FOLDERS.items() for folder in folders}
DUNGEON_REGION = {dungeon: FOLDER_REGION[folder] for folder, dungeon in DUNGEON_FOLDERS.items()}
FAMILY_OPTIONS = {"SmallKey": "shuffle_smallkeys", "BossKey": "shuffle_bosskeys",
                  "GanonBossKey": "shuffle_ganon_bosskey", "Map": "shuffle_mapcompass", "Compass": "shuffle_mapcompass"}


def placement_priority(name, settings):
    """Place scarce nonlogical rewards in AP's restrictive phase.

    This does not make a reward an access requirement. Skip balancing when the
    AP classification carries this priority solely to preserve legal slots.
    """
    metadata = ITEM_DATA.get(name, {})
    if metadata.get("bottle_item") and metadata.get("pouch_special") == "NotPushToPouch":
        return True
    kind = metadata.get("kind")
    option = FAMILY_OPTIONS.get(kind)
    if option is not None:
        return settings.get(option, "dungeon") != "keysanity"
    if kind == "Song":
        return settings.get("shuffle_songs") == "own"
    if kind == "DungeonReward":
        return settings.get("shuffle_dungeon_rewards") == "dungeons"
    return False


def prefill_scoped_items(multiworld, fill_restrictive, sweep_from_pool):
    """Reserve scarce domains using AP's standard restrictive prefill.

    Native seeds and their proofs are untouched. Compatible songs and dungeon
    rewards share all eligible Zelda sources, with no owner allocation quota.
    A failed AP fill restores the pool, locations, locks and seeded RNG.
    """
    selected = [item for item in multiworld.itempool if item.game in ZELDA_GAMES
                and placement_priority(item.name, getattr(multiworld.worlds[item.player], "native_options", {}))]
    if not selected:
        return ()
    originals = tuple(selected)
    selected_ids = {id(item) for item in originals}
    other = [item for item in multiworld.itempool if id(item) not in selected_ids]
    locations = [location for location in multiworld.get_unfilled_locations() if location.address is not None]
    previous = [(location, location.item, location.locked) for location in locations]
    random_state = multiworld.random.getstate()
    try:
        multiworld.random.shuffle(selected)
        multiworld.random.shuffle(locations)
        for world in multiworld.worlds.values():
            if (world.game not in ZELDA_GAMES or not hasattr(world, "waves")
                    or getattr(world, "access_logic", None) is not None):
                continue
            indexes = [index for index, location in enumerate(locations) if location.player == world.player]
            ordered = sorted((locations[index] for index in indexes),
                             key=lambda location: world.waves.get(location.name, 0), reverse=True)
            for index, location in zip(indexes, ordered):
                locations[index] = location
        domains = {}
        for item in selected:
            key = item.player, item.game, item.name
            if key not in domains:
                domains[key] = sum(location.item_rule(item) for location in locations)
            if not domains[key]:
                raise ValueError(f"No eligible AP locations for {item.name} (player {item.player}).")
        # AP pops from the end; stable ties retain the seeded random order.
        selected.sort(key=lambda item: -domains[item.player, item.game, item.name])
        fill_restrictive(multiworld, sweep_from_pool(multiworld.state, other), locations, selected,
                         single_player_placement=False, lock=True, swap=True,
                         one_item_per_player=False, name="Zelda placement scopes")
        if selected or any(item.location is None for item in originals):
            raise ValueError("The AP scope prefill did not place every selected item.")
    except Exception:
        for location, item, locked in previous:
            location.item, location.locked = item, locked
        for item in originals:
            item.location = None
        multiworld.random.setstate(random_state)
        raise
    multiworld.itempool[:] = [item for item in multiworld.itempool if id(item) not in selected_ids]
    return originals


def source_context(source):
    """Return (dungeon, region, known), with no guesses from display names.

    Native descriptors can provide authoritative placement metadata for flows.
    Physical sources can use their real Banc folder without a new export.
    """
    context = source.get("placement")
    if isinstance(context, dict):
        return context.get("dungeon"), context.get("region_group"), True
    folders = set()
    for variant in source.get("variants", ()):
        parts = variant.get("file", "").split("/")
        if len(parts) >= 3 and parts[0] == "Banc":
            folders.add(parts[1])
    if len(folders) != 1:
        return None, None, False
    folder = next(iter(folders))
    return DUNGEON_FOLDERS.get(folder), FOLDER_REGION.get(folder), True


def allowed(item_name, item_player, item_game, item_settings, source_name, source_player,
            source_game, source_descriptor=None, source_settings=None):
    """Respect explicit placement modes without imposing a default owner quota.

    Restricted dungeon-item modes describe the recipient's Hyrule. Song-only
    and end-of-dungeon pools can exchange compatible Zelda items between Zelda
    players. Anywhere/keysanity items remain eligible for other games.
    """
    source = source_descriptor or {}
    source_options = source_settings or {}
    item_options = item_settings or {}
    zelda_item, zelda_source = item_game in ZELDA_GAMES, source_game in ZELDA_GAMES
    metadata = ITEM_DATA.get(item_name, {}) if zelda_item else {}
    kind = metadata.get("kind")
    song = kind == "Song" and metadata.get("actor") != "Item_Melody_ScarecrowSong"
    sacred = kind == "DungeonReward"
    song_spot = zelda_source and source.get("native_kind") == "song"
    sacred_spot = zelda_source and source.get("native_kind") == "dungeon_reward"

    # A restricted source category accepts compatible Zelda rewards of any
    # Zelda player; a foreign game's identically named item is not compatible.
    if song_spot and source_options.get("shuffle_songs") == "own" and not song:
        return False
    if sacred_spot and source_options.get("shuffle_dungeon_rewards") == "dungeons" and not sacred:
        return False
    if (zelda_source and source_name == LACS_SOURCE
            and source_options.get("shuffle_ganon_bosskey") in {"lacs_dungeons", "lacs_medallions"}):
        return zelda_item and item_player == source_player and item_name == GANON_KEY
    if not zelda_item:
        return True
    if song and item_options.get("shuffle_songs") == "own":
        return song_spot
    if sacred and item_options.get("shuffle_dungeon_rewards") == "dungeons":
        return sacred_spot

    option = FAMILY_OPTIONS.get(kind)
    if option is None:
        return True
    mode = item_options.get(option, "dungeon")
    if mode == "keysanity":
        return True
    if mode in {"remove", "startwith"}:
        # Such rewards should have been removed by the native generator. Do
        # not silently put a removed requirement back into the AP pool.
        return False
    if mode in {"lacs_dungeons", "lacs_medallions"}:
        return zelda_source and source_player == item_player and source_name == LACS_SOURCE
    if not zelda_source or source_player != item_player:
        return False
    if mode == "vanilla":
        return source.get("generated_item") == item_name
    dungeon, region, known = source_context(source)
    if not known:
        return False
    if mode == "dungeon":
        return dungeon == metadata.get("dungeon")
    if mode == "any_dungeon":
        return dungeon is not None
    if mode == "overworld":
        return dungeon is None
    if mode == "regional":
        home = DUNGEON_REGION.get(metadata.get("dungeon"))
        return home is not None and home == region
    return False
