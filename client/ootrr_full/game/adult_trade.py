"""AP adult trades using the integration's independent native NPC adapters.

These identities and physical handovers originate in OOT-Remake-Archipelago.
The full engine supplies access rules and pool entries; the mod preparation
layer installs the same native inventory guards and handover events as legacy.
"""

TRADE_ITEMS = (
    ('Pocket Cucco', 'Item_PocketCucco'), ('Cojiro', 'Item_CojiroCucco'),
    ('Odd Mushroom', 'Item_OddMushroom'), ('Odd Potion', 'Item_OddPowder'),
    ('Poachers Saw', 'Item_PoacherSaw'), ('Broken Sword', 'Item_BrokenSword'),
    ('Prescription', 'Item_Prescription'), ('Eyeball Frog', 'Item_EyeballFrog'),
    ('Eyedrops', 'Item_EyeDrop'), ('Claim Check', 'Item_ClaimCheck'),
)

# name, native flow, physical area, exact reachable region/spot, required item
TRADE_SOURCES = (
    ('Kak Anju as Adult', 'Npc_Hylia_049_Adult', 'KakarikoVillage', 'Region|adult|Kakariko Village', None),
    ('Kak Anju Trade Pocket Cucco', 'Npc_Hylia_049_Adult', 'KakarikoVillage', 'Region|adult|Kakariko Village', 'Pocket Cucco'),
    ('LW Trade Cojiro', 'Npc_Hylia_017_Adult', 'LostWood', 'Region|adult|Lost Woods', 'Cojiro'),
    ('Kak Granny Trade Odd Mushroom', 'Npc_Hylia_053_Adult', 'KakarikoVillage', 'Region|adult|Kak Potion Shop Back', 'Odd Mushroom'),
    ('LW Trade Odd Potion', 'Npc_Kokiri_Fado_Adult', 'LostWood', 'Region|adult|Lost Woods', 'Odd Potion'),
    ('GV Trade Poachers Saw', 'Npc_Hylia_012_Adult', 'GerudoValley', 'Region|adult|GV Carpenter Tent', 'Poachers Saw'),
    ('DMT Trade Broken Sword', 'Npc_Goron_Biggoron_Adult', 'DeathMountainTrail', 'Region|adult|Death Mountain Summit', 'Broken Sword'),
    ('ZD Trade Prescription', 'Npc_Zora_KingZora_adult', 'ZoraDomain', 'Adult|ZD King Zora Thawed', 'Prescription'),
    ('LH Trade Eyeball Frog', 'Npc_Hylia_045_Adult', 'LakeHylia', 'Region|adult|LH Lab', 'Eyeball Frog'),
    ('DMT Trade Eyedrops', 'Npc_Goron_Biggoron_Adult', 'DeathMountainTrail', 'Region|adult|Death Mountain Summit', 'Eyedrops'),
    ('DMT Biggoron', 'Npc_Goron_Biggoron_Adult', 'DeathMountainTrail', 'Region|adult|Death Mountain Summit', 'Claim Check'),
)


def entries():
    items = TRADE_ITEMS + (('Biggoron Sword', 'Item_Sword_Biggoron'),)
    result = {}
    for source, (item, actor) in zip(TRADE_SOURCES, items):
        name, flow, folder, area, required = source
        gid = 'adult_trade#' + name
        # Empty variants are deliberate: these NPCs need independent inventory
        # transactions, not ordinary parameter replacement in a native grant.
        # The integration's trade_events pass installs their physical handovers.
        result[gid] = {'id': gid, 'source': 'adult_trade', 'form': 'event',
                       'folder': folder, 'hash': '', 'actor': actor, 'before': actor,
                       'vanilla': item, 'variants': [], 'event': flow, 'dungeon': None,
                       'kind': 'exact', 'ap': [], 'reason': None,
                       'guards': [area] + (['Souls|' + required] if required else []),
                       'trade_name': name, 'required_item': required}
    return result
