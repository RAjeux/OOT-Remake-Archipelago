"""Versioned AP pool substitutions; native seed/check provenance stays intact."""
from .catalog import FILLER, ITEM_DATA


RESTRICTED = frozenset(("SmallKey", "BossKey", "GanonBossKey", "Map", "Compass", "Song", "DungeonReward", "Token", "Trap"))


def eligible_filler(item, progression):
    row = ITEM_DATA.get(item, {})
    return (bool(row) and item not in progression and row.get("kind") not in RESTRICTED
            and not (row.get("bottle_item") and row.get("pouch_special") == "NotPushToPouch"))


def starting_pool(moved, options):
    rewards = dict(moved)
    if options.get("starting_bunny_hood"):
        for name in sorted(rewards):
            if rewards[name] == "Bunny Hood":
                rewards[name] = FILLER
                break
    return rewards


def prepare(moved, options, progression, rng):
    rewards = starting_pool(moved, options)
    if options.get("shuffle_ice_traps"):
        count = options.get("ice_trap_count", 6)
        if type(count) is not int or not 1 <= count <= 10:
            raise ValueError("Invalid Ice Trap count.")
        candidates = sorted(name for name, item in rewards.items() if eligible_filler(item, progression))
        if len(candidates) < count:
            raise ValueError(f"Ice Traps need {count} unrestricted filler rewards, but only {len(candidates)} are available. "
                             "Reduce Ice Trap count or enable more shuffled checks.")
        for name in rng.sample(candidates, count):
            rewards[name] = "Ice Trap"
    return rewards


def from_manifest(data):
    """Validate the exact pool change before auditing or preparing a new room."""
    moved = data.get("moved")
    features = data.get("features")
    if (not isinstance(moved, dict)
            or any(not isinstance(name, str) or not isinstance(item, str) or item not in ITEM_DATA
                   for name, item in moved.items())
            or (features is not None and not isinstance(features, dict))):
        raise ValueError("Invalid native AP item pool.")
    options = (features or {}).get("settings", {})
    if not isinstance(options, dict):
        raise ValueError("Invalid AP pool feature settings.")
    replacements = data.get("pool_substitutions", {})
    if not isinstance(replacements, dict) or not set(replacements) <= moved.keys():
        raise ValueError("Invalid AP pool substitutions.")
    if any(not isinstance(value, str) or value not in ITEM_DATA or value == moved[name]
           for name, value in replacements.items()):
        raise ValueError("Invalid AP pool replacement item.")
    actual = dict(moved, **replacements)
    baseline = starting_pool(moved, options)
    if not options.get("shuffle_ice_traps"):
        if actual != baseline:
            raise ValueError("AP pool substitutions differ from the starting equipment.")
        return actual
    from .access_logic import validate
    graph = validate(data.get("access_logic"))
    progression = {row["name"] for row in graph["world"]["items"] if row["adv"]}
    if data.get("shuffle_master_sword"):
        progression.add("Master Sword")
    count = options.get("ice_trap_count", 6)
    if type(count) is not int or not 1 <= count <= 10:
        raise ValueError("Invalid Ice Trap count.")
    traps = 0
    for name, item in actual.items():
        if item == "Ice Trap":
            if not eligible_filler(baseline[name], progression):
                raise ValueError("An Ice Trap replaced a restricted or progression reward.")
            traps += 1
        elif item != baseline[name]:
            raise ValueError("An AP pool item changed without a matching feature.")
    if traps != count:
        raise ValueError("The AP pool does not contain its configured Ice Trap count.")
    return actual
