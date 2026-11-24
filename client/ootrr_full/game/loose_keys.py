"""Two audited native loose keys, supplemental to the frozen chest catalogue.

The original native room flags are committed after the replacement pickup, and
restored together with the AP check. Their coffin/Skull Pot sources correspond
to the existing imported Collectable rules. Old player files keep their native
pickups through individual_smallkeys=False.
"""

SOURCES = (
    ('Shadow Temple Freestanding Key', 'ShadowTemple', 12562389953863361839, 765,
     (28.1456298828125, 52.86785888671875, 33.06930923461914),
     ('ShadowTemple_Level_Room_13_GetKey',)),
    ('Bottom of the Well Freestanding Key', 'BottomOfTheWell', 17649154319341333603, 297,
     (-62.33295822143555, 100.88990020751953, -18.492660522460938),
     ('BottomOfTheWell_Level_Room_03_Get_SmallKey', 'BottomOfTheWell_Level_Room_03_Get_Key')),
)


def entries(options):
    if not options.get('individual_smallkeys', False):
        return {}
    from .remake_world import FOLDER_DUNGEON
    result = {}
    for name, folder, ident, index, position, flags in SOURCES:
        gid = f'{folder}#loose_key#{ident}'
        actor = 'Obj_Dungeon_SmallKey'
        result[gid] = {'id': gid, 'source': 'freestanding', 'form': 'world', 'folder': folder,
                       'hash': str(ident), 'actor': actor, 'before': actor,
                       'vanilla': f'Small Key ({FOLDER_DUNGEON[folder]})',
                       'variants': [{'resource': f'Banc/{folder}/{folder}_Static.bcett.byml.zs',
                                     'index': index, 'field': 'Gyaml', 'before': actor,
                                     'position': list(position), 'label': name}],
                       'event': None, 'dungeon': FOLDER_DUNGEON[folder],
                       'kind': 'exact', 'ap': [name], 'guards': [], 'reason': None,
                       'extra_name': name, 'native_loose_key': True,
                       'native_flag': flags[0], 'native_flags': list(flags)}
    return result
