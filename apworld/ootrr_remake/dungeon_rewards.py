"""Owner-independent AP prefill for explicitly dungeon-restricted Zelda rewards."""
from .catalog import GAME


def item_rule(world, gid, item):
    full = world.full_world
    own = item.player == world.player and item.game == GAME
    if not (full.can_hold(gid, item.name) if own else full.can_hold_foreign(gid, item.name, item.game)):
        return False
    origin = world.multiworld.worlds.get(item.player)
    source = getattr(origin, 'full_world', None)
    if source is not None and item.name in source.boss_rewards:
        return item.game == GAME and full.c.shuffled[gid]['source'] == 'boss'
    return True


def reserved(world, location):
    """Reserve the requesting world's handovers before local dungeon-key prefill."""
    full = world.full_world
    gid = full.gids.get(location.name)
    return bool(full.boss_rewards and gid and full.c.shuffled[gid]['source'] == 'boss')


def prefill(multiworld):
    from Fill import FillError, fill_restrictive
    worlds = [world for world in multiworld.worlds.values()
              if world.game == GAME and getattr(world, 'full_world', None) is not None]
    origins = {world.player: world.full_world.boss_rewards for world in worlds if world.full_world.boss_rewards}
    if not origins:
        return
    restricted = [item for item in multiworld.itempool
                  if item.game == GAME and item.name in origins.get(item.player, ())]
    # Plando is allowed to choose an owner, but cannot silently violate the
    # selected physical source family before this prefill stage runs.
    for location in multiworld.get_filled_locations():
        item = location.item
        if item and item.game == GAME and item.name in origins.get(item.player, ()):
            world = multiworld.worlds.get(location.player)
            full = getattr(world, 'full_world', None)
            gid = full.gids.get(location.name) if full else None
            if not gid or full.c.shuffled[gid]['source'] != 'boss':
                raise FillError('A dungeon-restricted Zelda reward was planned outside a dungeon reward handover.')
    for item in restricted:
        multiworld.itempool.remove(item)
    locations = []
    for world in worlds:
        full = world.full_world
        locations.extend(location for location in multiworld.get_unfilled_locations(world.player)
                         if full.c.shuffled[full.gids[location.name]]['source'] == 'boss')
    if len(locations) < len(restricted):
        raise FillError('Not enough enabled Zelda dungeon reward handovers for the selected restricted rewards.')
    multiworld.random.shuffle(locations)
    multiworld.random.shuffle(restricted)
    fill_restrictive(multiworld, multiworld.get_all_state(False), locations, restricted,
                     single_player_placement=False, lock=True, allow_excluded=False,
                     one_item_per_player=False, name='Ocarina of Time Remake shared dungeon rewards')
    if restricted:
        raise FillError('A dungeon-restricted Zelda reward could not be placed safely.')
