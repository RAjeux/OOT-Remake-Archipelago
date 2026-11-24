"""The verified child route through the remake's native Spirit key layout.

The two child chain locks are Door5 and Door10. The original Silver Gauntlets
source in Desert Colossus is reached after spending two keys, before owning any
strength upgrade. The conservative N64 five-key rule remains for shuffled keys,
whose placements can require spending additional keys on the adult side first.
"""

CHILD_DOORS = (5, 10)
SILVER_SOURCE = 'DesertColossus#2490063409521505179'
CHILD_ROUTE = ('is_child and can_use(Kokiri_Sword) and can_use(Slingshot) '
               'and Bomb_Bag and can_use(Dins_Fire) and can_play(Zeldas_Lullaby) '
               'and (Small_Key_Spirit_Temple, 2)')


def native_keys(options):
    """Only the unchanged native key locations justify this two-key route."""
    return (not options.get('individual_smallkeys', False)
            or options.get('shuffle_smallkeys') == 'vanilla'
            or not options.get('shuffle_chests', True)
            or options.get('chest_scope', 'all') == 'overworld')


def child_route(settings):
    return CHILD_ROUTE if settings.get('native_spirit_keys') else None
