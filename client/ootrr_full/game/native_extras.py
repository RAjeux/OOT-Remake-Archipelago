"""Additional real remake rewards derived from the integration's Rust adapters.

Unlike ordinary source substitution these handovers need structural flow edits.
Their vanilla saved completion flags distinguish a successful purchase/minigame
from cancelling its dialogue. The matching patcher replays the audited edits.
"""

FROG_SONGS = (
    ('ZR Frogs Zeldas Lullaby', 'Zeldas Lullaby', 'ZeldaLullaby', 'Event172'),
    ('ZR Frogs Eponas Song', 'Eponas Song', 'EponaSong', 'Event220'),
    ('ZR Frogs Sarias Song', 'Sarias Song', 'SariaSong', 'Event221'),
    ('ZR Frogs Suns Song', 'Suns Song', 'SunSong', 'Event222'),
    ('ZR Frogs Song of Time', 'Song of Time', 'TimeSong', 'Event223'),
)


def _entry(name, folder, item, actor, flow, variants, guards, flag):
    gid = 'native_extra#' + name
    return {'id': gid, 'source': 'native_extra', 'form': 'event', 'folder': folder,
            'hash': '', 'actor': actor, 'before': actor, 'vanilla': item,
            'variants': [{'resource': 'Event/EventFlow/' + flow + '.bfevfl.zs',
                          'event': event, 'param': param, 'before': before}
                         for event, param, before in variants],
            'event': flow, 'dungeon': None, 'kind': 'exact', 'ap': [], 'reason': None,
            'guards': list(guards), 'native_flag': flag, 'extra_name': name}


def entries(options=None):
    enabled = options or {'shuffle_frog_songs': True, 'shuffle_frog_bug_heart': True,
                          'shuffle_potion_shop': True, 'shuffle_medigoron': True, 'shuffle_bean_merchant': True}
    rows = []
    if enabled.get('shuffle_frog_songs'):
        for name, song, suffix, event in FROG_SONGS:
            rows.append(_entry(name, 'ZoraRiver', 'Rupees (50)', 'Obj_Rupee_Purple', 'MiniGame_FrogTenors',
                               [(event, 'ActorName', 'Obj_Rupee_Purple')],
                               ['Region|child|Zora River', 'Souls|Ocarina|' + song],
                               'MiniGame_FrogTenors_' + suffix))
    if enabled.get('shuffle_frog_bug_heart'):
        rows.append(_entry('ZR Frogs Bug Game', 'ZoraRiver', 'Piece of Heart', 'Obj_Heart_Piece', 'MiniGame_FrogTenors',
                           [('Event161', 'ActorName', 'Obj_Heart_Piece'), ('Event75', 'ActorName', 'Obj_Heart_Piece')],
                           ['Region|child|Zora River', 'Souls|Ocarina|Zeldas Lullaby|Eponas Song|Sarias Song|Suns Song|Song of Time|Song of Storms'],
                           'MiniGame_FrogTenors_InsectRepellent'))
    if enabled.get('shuffle_potion_shop'):
        rules = ['Region|child|Market Potion Shop', 'HC Zeldas Letter', 'Bottle|']
        # The tutorial closes the shop until its bug is caught. A bottle is a
        # prerequisite when the keeper's own bottle becomes another AP item.
        for name, item, actor, event, flag in (
            ('Market Potion Shop Free Bottle', 'Bottle', 'Item_Bottle', 'Event171', 'Market_Item_Bottle_TutorialEvent_Started'),
            ('Market Potion Shop Red Potion', 'Rupees (5)', 'Item_Bottle_RedPotion', 'Event172', 'Market_Item_Bottle_TutorialEvent_Cleared')):
            row = _entry(name, 'Market', item, actor, 'Npc_Hylia_020_Shop_Child',
                         [(event, 'ActorName', actor)], rules, flag)
            row['needs_bottle'] = True
            rows.append(row)
    if enabled.get('shuffle_medigoron'):
        rows.append(_entry('GC Medigoron', 'GoronCity', 'Giants Knife', 'Item_Sword_Giant', 'Npc_Goron_Medigoron_Adult',
                           [('Event11', 'DisplayItemActor', 'Item_Sword_Giant')],
                           ['Region|adult|Goron City'], 'HaveTalked_Special.Npc_Goron_Medigoron_Adult_Talk_Event26'))
    if enabled.get('shuffle_bean_merchant'):
        for index in range(10):
            name = 'ZR Magic Bean Salesman ' + str(index + 1)
            item = 'Rupees (5)' if enabled.get('plant_beans') else 'Magic Bean'
            row = _entry(name, 'ZoraRiver', item, 'Item_MagicBean', 'SimpleShop',
                         [('Event182', 'ReveiveItem', 'Item_MagicBean')], ['Region|child|Zora River'],
                         'RandoFullBeanPurchase.' + str(index + 1))
            row['bean_index'] = index
            rows.append(row)
    return {row['id']: row for row in rows}
