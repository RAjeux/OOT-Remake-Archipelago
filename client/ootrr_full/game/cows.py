"""Eight finite first cow rewards; ordinary later milk refills stay native."""
import json
from importlib import resources


def clones():
    return json.loads(resources.files('ootrr_full').joinpath('game/cow_sources.json').read_text(encoding='utf-8'))['clones']


def entries():
    rows = [('KF Links House Cow', 'KokiriForest', 'Animal_Cow', 'PushToBottleMilk_LinkHouse'),
            ('GV Cow', 'GerudoValley', 'Animal_Cow', 'PushToBottleMilk_LinkHouse0'),
            ('GF Cow', 'GerudoFortress', 'Animal_Cow', 'PushToBottleMilk_LinkHouse0')]
    folders = ('DeathMountainTrail', 'KakarikoVillage', 'HyruleField', 'HyruleField', 'HyruleField')
    rows += [(row['location'], folder, row['class'], 'PushToBottleMilk')
             for row, folder in zip(clones(), folders)]
    result = {}
    for index, (name, folder, flow, entry) in enumerate(rows):
        gid, flag = 'native_cow#' + name, 'RandoFullCow.' + str(index + 1)
        result[gid] = {'id': gid, 'source': 'native_cow', 'form': 'event', 'folder': folder,
                       'hash': '', 'actor': 'Item_Bottle_Milk', 'before': 'Item_Bottle_Milk',
                       'vanilla': 'Rupees (5)', 'variants': [], 'event': flow, 'dungeon': None,
                       'kind': 'exact', 'ap': [name] if name != 'GF Cow' else [], 'reason': None,
                       'guards': ([] if name != 'GF Cow' else
                                  ['Region|adult|Gerudo Fortress', 'Souls|Ocarina|Eponas Song|Gerudo Membership Card']),
                       'native_flag': flag, 'tracking_flag': flag, 'cow_name': name,
                       'cow_entry': entry, 'cow_age': ('child' if name == 'GV Cow' else 'adult')}
    return result
