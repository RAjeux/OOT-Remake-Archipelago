"""Combat rules for the audited native difficulty::gates overworld passages.

The AP region split is coarser than several physical narrows. Requiring the
same guaranteed melee weapon on ingress is deliberately conservative: it never
claims access through an uncleared fight. New challenge guards are not soul-
bound; existing bound actors retain their ordinary source soul requirements.
"""

# Native gates.rs IDs; ID7 is explicitly held by the resource adapter.
PASSAGES = (
    (1, 'SacredForestMeadow_Child', ('SFM Entryway', 'Sacred Forest Meadow'), 'child', True),
    (2, 'DeathMountainTrail_Child', ('Death Mountain',), 'child', False),
    (3, 'ZoraRiver_Child', ('Zora River',), 'child', False),
    (4, 'ZoraRiver_Child', ('Zora River',), 'child', False),
    (5, 'ZoraRiver_Child', ('Zora River',), 'child', False),
    (6, 'KokiriForest_Child', ('KF Outside Deku Tree',), 'child', False),
    (9, 'LostWood_Child', ('Lost Woods',), 'child', False),
    (11, 'Market_Adult', ('Market Entrance', 'Market'), 'adult', False),
    (12, 'GerudoValley_Adult', ('Gerudo Fortress', 'GV Fortress Side'), 'adult', False),
    (13, 'HyruleField_Adult', ('Gerudo Valley',), 'adult', False),
)
MELEE = '(can_use(Kokiri_Sword) or has_adult_sword or can_use(Megaton_Hammer))'
# The two existing withered Deku Babas within gate6's audited eight-unit radius.
FOREST_GUARDS = frozenset({'3093965792357988492', '18170081087792387166'})


def forest_souls(plan):
    from ootrr_full.patching.soul_adapter import soul_item
    return sorted({soul_item(row['soul']) for row in plan['edits'] if str(row['hash']) in FOREST_GUARDS})


def requirement(source, target, settings):
    if not settings.get('enemy_gates'):
        return None
    rules = []
    for number, _, regions, age, shield in PASSAGES:
        if target not in regions:
            continue
        if number == 6 and (settings.get('open_forest') != 'closed' or settings.get('open_kakariko') == 'open'):
            continue
        # Explicit AP shield names must be referenced too: helper aliases name
        # native shop/drop events, which would otherwise classify these real
        # equipment items as filler before the global AP fill.
        combat = MELEE + (" and ('Deku Shield' or 'Hylian Shield' or Deku_Shield or Hylian_Shield)" if shield else '')
        if number == 6:
            combat += ''.join(' and ' + repr(item) for item in settings.get('enemy_gate_souls', ()))
        value = f'(not is_{age} or ({combat}))'
        if value not in rules:
            rules.append(value)
    return ' and '.join(rules) or None
