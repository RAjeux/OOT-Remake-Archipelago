"""Reserve explicit local plans using existing items and AP placement rules."""
from collections import defaultdict, deque

from .catalog import GAME
from .feature_settings import validate_mapping


def apply_item_plando(multiworld, sweep_from_pool):
    """Validate all plans before locking anything; never mint or reroll items.

    The reachability probe holds every unplanned pool item, then obtains planned
    progression only from reachable planned checks.  It rejects a self-lock or
    a cycle between planned progression items.  Archipelago's final accessibility
    validation still checks the completed multiworld after ordinary placement.
    """
    available = defaultdict(deque)
    for item in multiworld.itempool:
        available[item.player, item.name].append(item)
    planned = []
    for player, world in multiworld.worlds.items():
        if world.game != GAME:
            continue
        mapping = validate_mapping("item_plando", getattr(world, "native_options", {}).get("item_plando", {}))
        for name, reward in mapping.items():
            prefix = f"Item plan for player {player}: "
            if name not in world.moved:
                raise ValueError(prefix + "check is not enabled: " + name)
            location = multiworld.get_location(name, player)
            if location.address is None or location.item is not None:
                raise ValueError(prefix + "check is already reserved: " + name)
            choices = available[player, reward]
            if not choices:
                raise ValueError(prefix + "not enough pool copies of " + reward)
            item = choices.popleft()
            if not location.item_rule(item):
                raise ValueError(prefix + reward + " is not allowed at " + name)
            planned.append((location, item))
    if not planned:
        return ()
    planned_ids = {id(item) for _, item in planned}
    others = [item for item in multiworld.itempool if id(item) not in planned_ids]
    state = sweep_from_pool(multiworld.state.copy(), others)
    pending = list(planned)
    while pending:
        reached = [(location, item) for location, item in pending if location.can_reach(state)]
        if not reached:
            break
        reached_ids = {id(item) for _, item in reached}
        for location, item in reached:
            state.collect(item, True, location)
        pending = [(location, item) for location, item in pending if id(item) not in reached_ids]
    blocked = [(location, item) for location, item in pending if item.advancement]
    if blocked:
        detail = "; ".join(f"{location.name} = {item.name} (player {item.player})" for location, item in blocked)
        raise ValueError("Item plan locks progression behind its own requirements: " + detail)
    previous = [(location, location.item, location.locked, item, item.location) for location, item in planned]
    try:
        for location, item in planned:
            location.place_locked_item(item)
    except Exception:
        for location, old_item, locked, item, old_location in previous:
            location.item, location.locked, item.location = old_item, locked, old_location
        raise
    multiworld.itempool[:] = others
    return tuple(item for _, item in planned)
