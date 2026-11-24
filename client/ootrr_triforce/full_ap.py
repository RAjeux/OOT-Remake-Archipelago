"""Full-network generation, backed by the attributed Mozencaz remake logic.

The legacy OOTRR catalogue and file format remain readable. New source identities
are appended in separate deterministic ranges; none of the old protocol IDs move.
This module has no Archipelago dependency and is shared by the APWorld and app.
"""
from collections import Counter
import copy
import hashlib
import json
from importlib import resources
from functools import lru_cache
from pathlib import Path
import sys

from .catalog import GAME, ITEM_IDS as LEGACY_ITEM_IDS, LOCATION_IDS as LEGACY_LOCATION_IDS, PROTOCOL

FULL_MODE = "full_network"
FULL_FORMAT_VERSION = 2
LEGACY_MODE = "legacy"
PREFIX = "full_"
CATALOG_PATH = Path(__file__).with_name("full_catalog.json")
_CATALOG = None
ADULT_START_UNAVAILABLE = (
    "Adult start is temporarily unavailable in Full network because its native opening transition can stall. "
    "Choose Child when generating a new room. Existing adult player files remain readable for diagnosis."
)

# Archipelago adds only the world's package to its loader search path. The
# separately named pure-Python engine lives at this archive's root so it cannot
# shadow AP's own modules, or another project's original oot_rando package.
_ARCHIVE = Path(__file__).parent.parent
if _ARCHIVE.suffix == ".apworld" and _ARCHIVE.is_file() and str(_ARCHIVE) not in sys.path:
    sys.path.append(str(_ARCHIVE))

# Enable source families, not optional rule-changing gameplay experiments.
# Source eligibility and source/item form rules are still enforced by the solver.
_NETWORK_DEFAULTS = {
    "shuffle_chests": True, "tokensanity": "all", "shopsanity": "all",
    "shuffle_song_items": "everywhere", "shuffle_scrubs": "low",
    "shuffle_freestanding_items": "all", "shuffle_npc_gifts": True,
    "shuffle_boss_rewards": True, "shuffle_great_fairies": True,
    "shuffle_quest_rewards": True, "shuffle_pots": "all", "shuffle_crates": "all",
    "shuffle_beehives": True, "shuffle_bushes": True, "shuffle_rocks": True,
    "shuffle_trees": True, "shuffle_gerudo_card": True,
    "shuffle_mapcompass": "keysanity", "shuffle_smallkeys": "keysanity",
    "shuffle_bosskeys": "keysanity", "key_rings": "all",
    "adult_trade_shuffle": True,
    "shuffle_master_sword": True,
    "shuffle_frog_songs": True, "shuffle_frog_bug_heart": True,
    "shuffle_potion_shop": True, "shuffle_medigoron": True,
    "shuffle_bean_merchant": True, "plant_beans": False, "shuffle_cows": True,
}


def load_catalog():
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = json.loads(resources.files(__package__).joinpath("full_catalog.json").read_text(encoding="utf-8"))
        from ootrr_full.game.adult_trade import entries as trade_entries, TRADE_ITEMS
        _CATALOG['locations'].update({gid: entry['trade_name'] for gid, entry in trade_entries().items()})
        from ootrr_full.game.native_extras import entries as extra_entries
        _CATALOG['extensions'] = dict(trade_entries(), **extra_entries())
        from ootrr_full.game.cows import entries as cow_entries
        _CATALOG['extensions'].update(cow_entries())
        _CATALOG['locations'].update({gid: entry['cow_name'] for gid, entry in cow_entries().items()})
        _CATALOG['locations'].update({gid: entry['extra_name'] for gid, entry in extra_entries().items()})
        from ootrr_full.game.loose_keys import entries as loose_entries
        loose = loose_entries({'individual_smallkeys': True})
        _CATALOG['extensions'].update(loose)
        _CATALOG['locations'].update({gid: entry['extra_name'] for gid, entry in loose.items()})
        _CATALOG['items'] = sorted(set(_CATALOG['items']) | {item for item, _ in TRADE_ITEMS})
        locations = list(_CATALOG["locations"].values())
        # The final sword handover is the same physical location in vanilla
        # and full adult-trade modes. Those source implementations are mutually
        # exclusive and deliberately share its frozen AP identity.
        duplicates = {name: count for name, count in Counter(locations).items() if count > 1}
        if duplicates not in ({}, {"DMT Biggoron": 2}):
            raise ValueError("The full-network location catalogue contains duplicate names.")
    return _CATALOG


def _extended_ids(legacy, names, kind):
    result = dict(legacy)
    for name in sorted(set(names) - result.keys()):
        digest = hashlib.sha256((GAME + "|full-network|" + kind + "|" + name).encode("utf-8")).digest()
        result[name] = (0x10000000 if kind == "item" else 0x20000000) | (int.from_bytes(digest[:4], "big") & 0x0FFFFFFF)
    if len(set(result.values())) != len(result):
        raise ValueError("Full-network protocol identity collision; a reviewed explicit ID is required.")
    return result


def item_ids():
    return _extended_ids(LEGACY_ITEM_IDS, load_catalog()["items"], "item")


def location_ids():
    return _extended_ids(LEGACY_LOCATION_IDS, load_catalog()["locations"].values(), "location")


def _public_value(value):
    return "randomized" if value == "random" else str(value)


def full_option_specs():
    """Return app-compatible option descriptions, without importing AP itself."""
    from ootrr_full.archipelago import bridge
    from ootrr_full.logic import rando_options
    specs = [{"id": "generation_mode", "label": "Randomizer engine", "kind": "choice",
              "choices": (LEGACY_MODE, FULL_MODE), "default": FULL_MODE,
              "description": "Full network puts every enabled supported source into Archipelago. Legacy retains the OOTRR engine for existing configurations.",
              "group": "Generation"},
             {"id": "death_link", "label": "DeathLink", "kind": "toggle", "default": False,
              "description": "Share deaths with the other DeathLink participants.", "group": "Archipelago"}]
    for source in bridge.ap_option_specs():
        name, kind = source["name"], source["kind"]
        option = rando_options.BY_NAME.get(name)
        default = _NETWORK_DEFAULTS.get(name, source["default"])
        spec = {"id": PREFIX + name, "label": source["label"], "default": copy.deepcopy(default),
                "description": source["help"], "group": "Full network: " + (option.tab if option else "World")}
        if kind == "bool":
            spec["kind"] = "toggle"
        elif kind == "list":
            spec.update(kind="set", choices=tuple(source["values"]), default=list(default))
        elif kind == "int":
            allowed = tuple(source["values"])
            steps = {b - a for a, b in zip(allowed, allowed[1:])}
            if len(steps) > 1 or (steps and min(steps) < 1):
                raise ValueError("Irregular full-network integer setting: " + name)
            spec.update(kind="range", min=min(allowed), max=max(allowed), step=next(iter(steps), 1))
        else:
            spec.update(kind="choice", choices=tuple(_public_value(v) for v in source["values"]),
                        default=_public_value(default))
        if name == 'starting_age':
            spec['description'] = ADULT_START_UNAVAILABLE
        elif option and option.experimental:
            spec["description"] += " Experimental game adapter: automated checks do not replace gameplay validation."
        specs.append(spec)
    return tuple(specs)


def full_defaults():
    return {spec["id"]: copy.deepcopy(spec["default"]) for spec in full_option_specs()}


def require_playable_start(values):
    """Reject the stalled opening at execution boundaries, keeping files readable.

    Accept public full options, native options, or a player manifest. Validation
    and world reconstruction deliberately remain available to diagnose old files.
    """
    options = values.get('full_patch', {}).get('options', values)
    if options.get('full_starting_age', options.get('starting_age', 'child')) == 'adult':
        raise ValueError(ADULT_START_UNAVAILABLE)


def validate_full_options(values):
    """Validate explicit full-mode values; never discard an unknown option."""
    if not isinstance(values, dict):
        raise ValueError("Full-network settings must be an object.")
    result = full_defaults()
    unknown = set(values) - set(result)
    if unknown:
        raise ValueError("Unknown full-network settings: " + ", ".join(sorted(unknown)))
    result.update(copy.deepcopy(values))
    for spec in full_option_specs():
        value, kind = result[spec["id"]], spec["kind"]
        valid = ((type(value) is bool) if kind == "toggle" else
                 (type(value) is int and spec["min"] <= value <= spec["max"]
                  and (value - spec['min']) % spec.get('step', 1) == 0) if kind == "range" else
                 (isinstance(value, (list, tuple, set, frozenset)) and set(value) <= set(spec["choices"])) if kind == "set" else
                 (isinstance(value, str) and value in spec["choices"]))
        if not valid:
            raise ValueError("Unsupported full-network value for " + spec["id"] + ": " + repr(value))
    if result["generation_mode"] != FULL_MODE:
        raise ValueError("Use the legacy settings validator for legacy generation.")
    # Apply the same cross-option dependency checks as the generator.
    from ootrr_full.archipelago.bridge import full_options
    full_options(native_options(result))
    return result


def native_options(values):
    """Return the unprefixed options expected by the full-world solver."""
    options = {}
    for spec in full_option_specs():
        if not spec["id"].startswith(PREFIX):
            continue
        name = spec["id"][len(PREFIX):]
        value = values.get(spec["id"], copy.deepcopy(spec["default"]))
        if spec["kind"] == "choice":
            value = "random" if value == "randomized" else value
        elif spec["kind"] == "set":
            value = tuple(v for v in spec["choices"] if v in value)
        options[name] = value
    return options


def full_yaml_options(values=None, name="Player"):
    """Produce an explicit full-network player configuration without hand editing."""
    current = validate_full_options(values or full_defaults())
    lines = ["name: " + json.dumps(str(name), ensure_ascii=False), "game: " + json.dumps(GAME),
             "description: Full-network Ocarina of Time Remake Archipelago", GAME + ":"]
    for spec in full_option_specs():
        value = current[spec["id"]]
        if isinstance(value, (set, frozenset, tuple)):
            value = list(value)
        lines.append("  " + spec["id"] + ": " + json.dumps(value, ensure_ascii=False))
    return "\n".join(lines) + "\n"


def new_world(values, seed_key):
    from ootrr_full.archipelago.bridge import PlayerWorld
    current = validate_full_options(values)
    return PlayerWorld(load_catalog(), native_options(current), seed_key)


def translate_legacy_options(changed, values=None):
    """Translate changed old YAML keys only when their behaviour is equivalent.

    The two engines do not implement identical options. Rejecting an unsupported
    request is preferable to producing a seed whose game disagrees with its rules.
    """
    result = copy.deepcopy(values or full_defaults())
    direct = {"open_kakariko", "zora_fountain", "shuffle_master_sword", "shuffle_kokiri_sword", "adult_trade_shuffle",
              "shuffle_mapcompass", "shuffle_bosskeys", "shuffle_smallkeys", "gerudo_fortress", "plant_beans",
              "shuffle_cows", "bridge", "bridge_rewards", "trials", "shuffle_ganon_bosskey", "lacs_rewards",
              "starting_hearts", "shopsanity_prices", "scrub_prices", "scrub_price_fixed",
              "merchant_prices", "merchant_price_fixed", "fairy_prices", "fairy_price_fixed", "scrub_hint_text"}
    direct.update(('shuffle_entrances', 'door_of_time_song'))
    from ootrr_full.game.portable_options import unrecorded as portable_defaults
    direct.update(portable_defaults())
    aliases = {"gerudo_bridge_open": "open_gerudo_valley_bridge", "faster_chests": "fast_chests",
               "shuffle_boss_hearts": "shuffle_boss_rewards", "shuffle_ocarinas": "shuffle_quest_rewards"}
    for name, value in changed.items():
        updates = {}
        if name in direct:
            updates[name] = value
            if (name == "shuffle_smallkeys" and value not in {"vanilla", "remove"}
                    and not result.get('full_individual_smallkeys', False)):
                updates["key_rings"] = "all"
            elif name == 'shuffle_smallkeys' and value in {'vanilla', 'remove'}:
                updates['key_rings'] = 'off'
        elif name == 'skip_ganon_trials':
            updates['trials'] = 0 if value else 6
        elif name == 'shuffle_treasure_reward':
            updates[name] = 'shuffled' if value else 'vanilla'
        elif name == 'door_of_time_escape':
            updates['spiritual_stones'] = {'vanilla': 'vanilla', 'stones': 'all', 'moat': 'song'}[value]
        elif name in aliases:
            updates[aliases[name]] = value
        elif name == "open_forest":
            updates[name] = value == "open"
        elif name == "shuffle_chests":
            updates[name] = value != 'off'
            updates['chest_scope'] = value if value in {'overworld', 'dungeons'} else 'all'
            if value == 'overworld':
                updates.update(shuffle_smallkeys='vanilla', shuffle_bosskeys='vanilla',
                               shuffle_ganon_bosskey='vanilla', shuffle_mapcompass='vanilla', key_rings='off')
        elif name == "shuffle_skulltulas":
            updates["tokensanity"] = "off" if value == "off" else "all"
        elif name == "shuffle_shops" and value in {"off", "random", "deals_1", "deals_2", "deals_3", "deals_4"}:
            updates["shopsanity"] = value.removeprefix("deals_")
        elif name in {'shuffle_pots', 'shuffle_crates'}:
            updates[name] = 'off' if value == 'off' else 'all'
            updates['pot_scope' if name == 'shuffle_pots' else 'crate_scope'] = value if value in {'overworld', 'dungeons'} else 'all'
        elif name in {'shuffle_grass', 'shuffle_rocks'}:
            updates['shuffle_bushes' if name == 'shuffle_grass' else 'shuffle_rocks'] = value != 'off'
            updates['bush_scope' if name == 'shuffle_grass' else 'rock_scope'] = value if value in {'overworld', 'dungeons'} else 'all'
        elif name == "shuffle_beehives":
            updates[name] = value
        elif name == "shuffle_freestanding_items":
            updates[name] = value
        elif name == "shuffle_rewards":
            updates.update(shuffle_npc_gifts=value == "supported", shuffle_quest_rewards=value == "supported",
                           shuffle_great_fairies=value == "supported")
        elif name == "shuffle_rewards_extra":
            updates["shuffle_npc_gifts"] = value
        elif name == "shuffle_merchants":
            updates["shuffle_medigoron"] = value in {"all", "no_beans"}
            updates["shuffle_bean_merchant"] = value in {"all", "beans"}
        elif name in {"shuffle_frog_songs", "shuffle_frog_bug_heart", "shuffle_potion_shop"}:
            updates[name] = value
        elif name in {"shuffle_scrubs_a", "shuffle_scrubs_b"}:
            if value:
                updates["shuffle_scrubs"] = "low"
        elif name == "shuffle_songs":
            updates["shuffle_song_items"] = {"off": "song", "own": "shuffled", "anywhere": "everywhere"}[value]
        elif name == "shuffle_dungeon_rewards":
            updates["shuffle_boss_rewards"] = True
            updates['dungeon_reward_placement'] = value
        elif name == "anju_one_cucco":
            updates["chicken_count"] = 1 if value else 7
        elif name == "big_poe_one":
            updates["big_poe_count"] = 1 if value else 10
        elif name == "door_of_time_condition":
            updates["open_door_of_time"] = value == "open"
            updates["door_of_time_requirement"] = {"vanilla": "vanilla", "stones": "all", "song": "song", "open": "song"}[value]
        else:
            raise ValueError("The native setting '" + name + "' has no equivalent full-network adapter. "
                             "Choose generation_mode: legacy to retain it, or use the full_* settings in the new editor.")
        for target, translated in updates.items():
            key = PREFIX + target
            if translated == "random":
                translated = "randomized"
            spec = next((s for s in full_option_specs() if s["id"] == key), None)
            if spec is None or (spec["kind"] == "choice" and translated not in spec["choices"]):
                raise ValueError("The native setting '" + name + "' value " + repr(value) + " has no full-network equivalent. Choose generation_mode: legacy.")
            # Full-specific non-default fields are explicit instructions too.
            # Refuse a conflict instead of guessing which YAML field wins.
            default = full_defaults()[key]
            if result[key] != default and result[key] != translated:
                raise ValueError("Conflicting settings: " + name + " and " + key + ".")
            result[key] = translated
    return result


def manifest(world, placements, remote, room, slot, player, death_link=False, precollected=()):
    """Build a full .apootrr while keeping old manifests on their original path."""
    catalog = load_catalog()
    patch = world.patch(placements, remote, room, slot, player, catalog["game_build"], precollected)
    ids = location_ids()
    patch["location_ids"] = {gid: ids[world.names[gid]] for gid in sorted(world.names)}
    token = patch_token(patch)
    return {"game": GAME, "protocol": PROTOCOL, "generation_mode": FULL_MODE,
            "full_format_version": FULL_FORMAT_VERSION,
            "room": str(room), "slot": str(slot), "player": player, "token": token,
            "death_link": bool(death_link), "reward_mode": "all_locations", "local_items": True,
            "checks": sorted(world.names.values()), "full_patch": patch,
            "adult_trade_shuffle": bool(world.options.get("adult_trade_shuffle", False)),
            "item_pool": dict(sorted(Counter(world.pool).items())),
            "item_ids": item_ids(), "location_ids": {name: ids[name] for name in sorted(world.names.values())},
            "catalog_scan": catalog["scan"], "full_options": world.values}


def patch_token(patch):
    """Bind a save/profile to the final room, settings, ownership and rewards.

    AP seed names can intentionally repeat across generations with different
    settings. Their name alone must never share a room journal or save marker.
    Dictionary order and order-insensitive remote/starting inventories do not
    change this identity.
    """
    from ootrr_full.archipelago.bridge import canonical_patch
    canonical = canonical_patch(patch)
    content = {"full_format_version": FULL_FORMAT_VERSION, "patch": canonical}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def _manifest_options(data, patch):
    """Normalize the stored native option summary to the public full settings."""
    raw = data.get('full_options')
    specs = [spec for spec in full_option_specs() if spec['id'].startswith(PREFIX)]
    from ootrr_full.logic import rando_options
    from ootrr_full.game.goal_settings import NEW_DEFAULTS
    optional = dict(NEW_DEFAULTS, bridge='vanilla', trials=6, shuffle_ganon_bosskey='vanilla')
    from ootrr_full.game.economy_settings import DEFAULTS as ECONOMY_DEFAULTS
    optional.update(ECONOMY_DEFAULTS)
    try:
        from ootrr_full.game import portable_options
    except ImportError:
        pass
    else:
        optional.update(portable_options.unrecorded())
    expected = {spec['id'][len(PREFIX):] for spec in specs}
    if not isinstance(raw, dict) or set(raw) - expected or expected - set(raw) - set(optional):
        raise ValueError('The full-network option summary is incomplete or invalid.')
    raw = dict(optional, **raw)
    values = {'generation_mode': FULL_MODE, 'death_link': data['death_link']}
    for spec in specs:
        value = raw[spec['id'][len(PREFIX):]]
        if spec['kind'] == 'choice':
            value = _public_value(value)
        values[spec['id']] = value
    current = validate_full_options(values)
    from ootrr_full.archipelago.bridge import full_options
    normalized, open_forest = full_options(native_options(current))
    same = json.dumps(normalized, sort_keys=True) == json.dumps(
        rando_options.validate(dict(rando_options.UNRECORDED, **patch['options']), supported_only=True), sort_keys=True)
    if not same or open_forest != patch['open_forest']:
        raise ValueError('The full-network option summary disagrees with its patch.')
    return current


@lru_cache(maxsize=4)
def _manifest_world(serialized, seed_key):
    """Cache the actual enabled-source/pool contract for repeated profile reads."""
    return new_world(json.loads(serialized), seed_key)


def validate_manifest(data):
    """Reject tampered/mismatched full-network files before preparation."""
    from ootrr_full.archipelago.bridge import check_patch
    if not isinstance(data, dict) or data.get("generation_mode") != FULL_MODE:
        raise ValueError("Not a full-network Ocarina of Time Remake player file.")
    if data.get("game") != GAME or type(data.get('protocol')) is not int or data.get("protocol") != PROTOCOL:
        raise ValueError("Unsupported full-network game or protocol.")
    if data.get("full_format_version") != FULL_FORMAT_VERSION:
        raise ValueError("This full-network player file needs its matching application version. Generate a new room with the updated APWorld.")
    patch = check_patch(data.get("full_patch"))
    catalog = load_catalog()
    if patch["scan"] != catalog["scan"] or patch["world"] != catalog["world"]:
        raise ValueError("The player file requires a different full-network catalogue. Use its matching application.")
    if patch['game_build'] != catalog['game_build'] or data.get('catalog_scan') != catalog['scan']:
        raise ValueError('The full-network game build or catalogue summary is invalid.')
    if type(data.get('death_link')) is not bool:
        raise ValueError('The full-network DeathLink setting must be a boolean.')
    if (type(data.get('adult_trade_shuffle')) is not bool
            or data['adult_trade_shuffle'] != patch['options'].get('adult_trade_shuffle', False)):
        raise ValueError('The full-network adult-trade setting disagrees with its patch.')
    if type(data.get('player')) is not int or not 1 <= data['player'] <= 65535:
        raise ValueError('The full-network player number is invalid.')
    checks = data.get("checks")
    if not isinstance(checks, list) or not all(isinstance(name, str) for name in checks) or len(checks) != len(set(checks)):
        raise ValueError("Invalid full-network check list.")
    expected = {catalog["locations"][gid] for gid in patch["placements"] if gid in catalog["locations"]}
    if len(expected) != len(patch["placements"]) or set(checks) != expected:
        raise ValueError("The full-network player file has missing or unknown checks.")
    ids = location_ids()
    if data.get("location_ids") != {name: ids[name] for name in checks} or data.get("item_ids") != item_ids():
        raise ValueError("The full-network protocol identities do not match this application.")
    if patch.get("location_ids") != {gid: ids[catalog["locations"][gid]] for gid in patch["placements"]}:
        raise ValueError("The full-network patch location identities do not match the player file.")
    token = patch_token(patch)
    if data.get("token") != token or data.get("reward_mode") != "all_locations" or data.get("local_items") is not True:
        raise ValueError("The full-network player file identity or delivery mode is invalid.")
    if patch.get("seed_name") != data.get("room") or patch.get("slot_name") != data.get("slot") or patch.get("player") != data.get("player"):
        raise ValueError("The full-network patch belongs to a different room or player.")
    values = _manifest_options(data, patch)
    world = _manifest_world(json.dumps(values, sort_keys=True), patch['seed_key'])
    if patch.get('dungeon_entrances', {}) != world.c.entrances:
        raise ValueError('The full-network dungeon entrance layout disagrees with its seed and logic.')
    if set(patch['placements']) != set(world.names):
        raise ValueError('The full-network sources disagree with their enabled settings.')
    pool = data.get('item_pool')
    if (not isinstance(pool, dict) or any(type(count) is not int or count < 1 for count in pool.values())
            or pool != dict(Counter(world.pool))):
        raise ValueError('The full-network item-pool summary disagrees with its settings.')
    for gid, placement in patch['placements'].items():
        if placement['own'] and placement['item'] not in data['item_ids']:
            raise ValueError('The full-network reward is not a known physical item.')
        eligible = (world.can_hold(gid, placement['item']) if placement['own'] else
                    world.can_hold_foreign(gid, placement['item'], placement.get('game')))
        if not eligible:
            raise ValueError('The full-network source cannot grant its assigned reward.')
    # Kept at the native boundary: the mailbox verifies real physical recipes.
    # Avoid importing the physical resource codecs into Archipelago generation.
    from ootrr_full.patching.ap_mailbox import records
    records(patch['remote'])
    error = world.starting_error({}, Counter(patch.get('precollected', ())))
    if error:
        raise ValueError('Full-network starting inventory: ' + error)
    return data
