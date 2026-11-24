"""Dungeon-specific keys usable outside their dungeon, including repeated copies.

Individual small keys use one short ``Item_SKey_<dungeon>_<copy>`` actor per
physical source and a separate ``..._R<copy>`` namespace for received copies.
Each saved ``RandoSmallKey.<actor>`` flag protects exactly one increment of the
target dungeon's held and total counters. A spent key is never recreated by
an item-get replay, a receipt retry or source restoration. The global watcher
also settles authored gifts that do not call ActionGuide.

The remake's keys are generic: ``Item_Dungeon_SmallKey``/``Item_Dungeon_BossKey``
are credited by native code (``EventGetDungeonSmallKey``…) to the dungeon the
player stands in. Each dungeon keeps its state in the saved GameData struct
``DungeonInfo.<folder>`` (RSDB ``DungeonParam`` rows, verified on the local data):
``.SmallKeyNum`` (Int, keys held, used by the locked doors), ``.IsGetBossKey``
(Bool), ``.IsGetMap``, ``.IsGetCompass``.

As in OoTR, a dungeon can get one *key ring* (every small key of the dungeon at
once) and its boss key can become an item of its own, both placeable anywhere:

* new pouch actors ``Item_KeyRing_<folder>`` and ``Item_BossKey_<folder>`` built
  like the souls (Forest Medallion key-item template, model of the native key);
* every item-get flow ends in ``ActionGuide/ActionGuide`` (see
  ``qol_patches.ocarina_guide_on_get``): it first checks each key item of the
  seed; a ring got not yet applied adds its keys to ``SmallKeyNum``
  and ``SmallKeyTotalNum`` (keys found, credited too by the native key get)
  once (saved flag ``RandoKeyRing.<folder>``), a boss key got sets
  ``IsGetBossKey``. A key obtained by a path that skips the get flow is applied
  on the next item get.

Maps and compasses work the same way (``Item_Map_<folder>``, ``Item_Compass_<folder>``:
``IsGetMap``/``IsGetCompass``). The native ones are only credited by the big chest
sequence (``Dm_SY_Treasurebox/Success_AddContent``: ``EventGetDungeonMap``, to the
dungeon Link stands in); from a small chest, a pickup or an NPC the native map was
shown and credited nothing (Discord 16/11, 0.6.5: Forest Temple map still "???").

"Got" is the saved ``IsGet.<actor>`` Bool the pouch writes for a generated actor (as
for the souls and the progressive tokens), not ``EventQueryIsExistInPouch``: in game
(Longshot, 16/11) a Forest Temple ring in the pouch left ``IsGet`` true but the pouch
query false, so the keys were never added.

A ring gives the AP number of keys of the dungeon (never fewer than the remake's
locked doors seen in the maps): an extra key is harmless. Not validated in game.
"""
import io
import re

from ootrr_full.game.remake_world import FOLDER_DUNGEON

RING_PREFIX = 'Item_KeyRing_'
BOSS_PREFIX = 'Item_BossKey_'
MAP_PREFIX = 'Item_Map_'
COMPASS_PREFIX = 'Item_Compass_'
SMALL_PREFIX = 'Item_SKey_'
SMALL_APPLIED_PREFIX = 'RandoSmallKey.'
SMALL_ENTRY = 'RandoSmallKeys'
SMALL_CODES = {'ForestTemple': 'Forest', 'FireTemple': 'Fire', 'WaterTemple': 'Water',
               'ShadowTemple': 'Shadow', 'SpiritTemple': 'Spirit', 'BottomOfTheWell': 'Well',
               'GerudoTrainingGround': 'GTG', 'InsideGanonCastle': 'Ganon'}
# Bool kinds of dungeon item actor: (AP item kind, DungeonInfo Bool it sets, model).
BOOL_KINDS = {'boss': ('Boss Key', 'IsGetBossKey', 'Item_Dungeon_BossKey'),
              'map': ('Map', 'IsGetMap', 'Item_Dungeon_Map'),
              'compass': ('Compass', 'IsGetCompass', 'Item_Dungeon_Compass')}
PREFIX_KIND = {RING_PREFIX: 'ring', BOSS_PREFIX: 'boss', MAP_PREFIX: 'map', COMPASS_PREFIX: 'compass'}
APPLIED_PREFIX = 'RandoKeyRing.'
SMALL_KEY_MODEL = 'Item_Dungeon_SmallKey'
BOSS_KEY_MODEL = 'Item_Dungeon_BossKey'
ACTION_GUIDE_FLOW = 'Event/EventFlow/ActionGuide.bfevfl.zs'
ACTION_GUIDE_ENTRY = 'ActionGuide'
# Dungeons with small keys (AP vanilla count, Thieves' Hideout apart) and with a boss key.
RING_DUNGEONS = {
    'ForestTemple': 5, 'FireTemple': 8, 'WaterTemple': 6, 'ShadowTemple': 5, 'SpiritTemple': 5,
    'BottomOfTheWell': 3, 'GerudoTrainingGround': 9, 'InsideGanonCastle': 2,
}
BOSS_KEY_DUNGEONS = ('ForestTemple', 'FireTemple', 'WaterTemple', 'ShadowTemple', 'SpiritTemple')
# The audited native OOTRR geographic groups used by regional item placement.
REGION_GROUPS = (
    ('KokiriForest', 'LostWood', 'SacredForestMeadow', 'InsideTheDekuTree', 'ForestTemple'),
    ('DeathMountainTrail', 'DeathMountainCrater', 'GoronCity', 'DodongoCavern', 'FireTemple'),
    ('ZoraRiver', 'ZoraDomain', 'ZoraFountain', 'InsideJabuJabuBelly', 'IceCavern', 'WaterTemple'),
    ('KakarikoVillage', 'Graveyard', 'BottomOfTheWell', 'ShadowTemple'),
    ('GerudoValley', 'GerudoFortress', 'HountedWasteland', 'DesertColossus', 'SpiritTemple', 'GerudoTrainingGround'),
    ('HyruleField', 'Market', 'HyruleCastle', 'GanonCastle', 'InsideGanonCastle'),
)


def regional_folder(item, folder):
    home = item_folder(item)
    return any(home in group and folder in group for group in REGION_GROUPS)
# Dungeons with a map and a compass (AP items ``Map (…)``/``Compass (…)``).
MAP_DUNGEONS = ('InsideTheDekuTree', 'DodongoCavern', 'InsideJabuJabuBelly', 'ForestTemple', 'FireTemple',
                'WaterTemple', 'ShadowTemple', 'SpiritTemple', 'BottomOfTheWell', 'IceCavern')
DUNGEON_FOLDER = {dungeon: folder for folder, dungeon in FOLDER_DUNGEON.items()}
# In-game names for the French message files (EUfr / CAfr).
FRENCH_DUNGEONS = {
    'ForestTemple': 'Temple de la Forêt', 'FireTemple': 'Temple du Feu', 'WaterTemple': 'Temple de l’Eau',
    'ShadowTemple': 'Temple de l’Ombre', 'SpiritTemple': 'Temple de l’Esprit',
    'BottomOfTheWell': 'Puits de Cocorico', 'GerudoTrainingGround': 'Gymnase Gerudo',
    'InsideGanonCastle': 'Château de Ganon', 'InsideTheDekuTree': 'Arbre Mojo',
    'DodongoCavern': 'Caverne Dodongo', 'InsideJabuJabuBelly': 'Ventre de Jabu-Jabu', 'IceCavern': 'Caverne Polaire',
}
ENGLISH_DUNGEONS = {
    'ForestTemple': 'Forest Temple', 'FireTemple': 'Fire Temple', 'WaterTemple': 'Water Temple',
    'ShadowTemple': 'Shadow Temple', 'SpiritTemple': 'Spirit Temple', 'BottomOfTheWell': 'Bottom of the Well',
    'GerudoTrainingGround': 'Gerudo Training Ground', 'InsideGanonCastle': "Ganon's Castle",
    'InsideTheDekuTree': 'Deku Tree', 'DodongoCavern': "Dodongo's Cavern", 'InsideJabuJabuBelly': "Jabu-Jabu's Belly",
    'IceCavern': 'Ice Cavern',
}


def total_keys(held):
    """``DungeonInfo.<folder>.SmallKeyTotalNum`` (keys found) of a ``SmallKeyNum`` (keys held)."""
    if not held.endswith('.SmallKeyNum'):
        raise ValueError('Not a held key count: ' + held)
    return held[:-len('SmallKeyNum')] + 'SmallKeyTotalNum'


def ring_item(folder):
    return f'Small Key Ring ({FOLDER_DUNGEON[folder]})'


def small_key_item(folder):
    return f'Small Key ({FOLDER_DUNGEON[folder]})'


def is_small_key(item):
    return isinstance(item, str) and item.startswith('Small Key (') and item.endswith(')')


def small_key_actor(folder, number, *, remote=False):
    """One saved, short actor per copy; remote and physical sources never overlap."""
    if folder not in SMALL_CODES or type(number) is not int or not 1 <= number <= 999:
        raise ValueError('Invalid dungeon small-key token.')
    return f'{SMALL_PREFIX}{SMALL_CODES[folder]}_{"R" if remote else ""}{number}'


def small_key_folder(actor):
    if not isinstance(actor, str) or not actor.startswith(SMALL_PREFIX):
        return None
    code, _, number = actor[len(SMALL_PREFIX):].rpartition('_')
    if not re.fullmatch(r'R?[1-9][0-9]{0,2}', number):
        return None
    return next((folder for folder, short in SMALL_CODES.items() if short == code), None)


def small_applied_flag(actor):
    if small_key_folder(actor) is None:
        raise ValueError('Invalid dungeon small-key token: ' + str(actor))
    return SMALL_APPLIED_PREFIX + actor


def individual_key_plan(placed):
    """Bind every personal physical small-key copy to its stable source token."""
    counts, result = {}, {}
    for gid, item in sorted(placed.items()):
        if is_small_key(item):
            folder = item_folder(item)
            if folder not in SMALL_CODES:
                continue
            counts[folder] = counts.get(folder, 0) + 1
            result[gid] = small_key_actor(folder, counts[folder])
    return result


def is_ring(item):
    return item.startswith('Small Key Ring (')


def item_folder(item):
    """Dungeon folder of a key item (``Small Key Ring (X)``, ``Boss Key (X)``…)."""
    return DUNGEON_FOLDER[item[item.index('(') + 1:-1]]


# Actor names of the long dungeon folders. In-game test 13/11: the item get of a
# generated actor named Item_KeyRing_GerudoTrainingGround (33 characters) or
# Item_KeyRing_InsideGanonCastle (30) crashes the game (null read, Link holding
# nothing), while every generated actor of 25 characters or fewer is handed over
# (see soul_adapter.MAX_ACTOR_NAME).
SHORT_FOLDER = {'BottomOfTheWell': 'Well', 'GerudoTrainingGround': 'GTG', 'InsideGanonCastle': 'Ganon',
                'InsideTheDekuTree': 'Deku', 'DodongoCavern': 'Dodongo', 'InsideJabuJabuBelly': 'Jabu'}
FOLDER_OF_SHORT = {short: folder for folder, short in SHORT_FOLDER.items()}


def ring_actor(folder):
    return RING_PREFIX + SHORT_FOLDER.get(folder, folder)


def boss_actor(folder):
    return BOSS_PREFIX + SHORT_FOLDER.get(folder, folder)


def map_actor(folder):
    return MAP_PREFIX + SHORT_FOLDER.get(folder, folder)


def compass_actor(folder):
    return COMPASS_PREFIX + SHORT_FOLDER.get(folder, folder)


def dungeon_item_actor(item):
    """Own actor of a ``Map (X)``/``Compass (X)`` AP item, or None."""
    for kind, make in (('Map (', map_actor), ('Compass (', compass_actor)):
        folder = DUNGEON_FOLDER.get(item[len(kind):-1]) if item.startswith(kind) else None
        if folder in MAP_DUNGEONS:
            return make(folder)
    return None


def actor_kind(actor):
    """Kind of a supported dungeon item actor, else None."""
    if not isinstance(actor, str):
        return None
    if small_key_folder(actor) is not None:
        return 'small'
    return next((kind for prefix, kind in PREFIX_KIND.items() if actor.startswith(prefix)), None)


def specific_actor(item):
    """Dungeon-specific actor for experimental placement modes."""
    if is_small_key(item):
        return small_key_actor(item_folder(item), 1)
    if is_ring(item):
        return ring_actor(item_folder(item))
    if item.startswith('Boss Key ('):
        return boss_actor(item_folder(item))
    actor = dungeon_item_actor(item)
    if actor is None:
        raise ValueError('Not a dungeon item: ' + item)
    return actor


def actor_folder(actor):
    """Dungeon folder of a key actor (``Item_KeyRing_GTG`` → ``GerudoTrainingGround``), or None."""
    if not isinstance(actor, str):
        return None
    small = small_key_folder(actor)
    if small is not None:
        return small
    for prefix in PREFIX_KIND:
        if actor.startswith(prefix):
            name = actor[len(prefix):]
            folder = FOLDER_OF_SHORT.get(name, name)
            return folder if folder in FOLDER_DUNGEON else None
    return None


def key_actor_item(actor):
    """AP item of a dungeon-specific key actor, or None."""
    folder = actor_folder(actor)
    if folder is None:
        return None
    kind = actor_kind(actor)
    name = 'Small Key' if kind == 'small' else 'Small Key Ring' if kind == 'ring' else BOOL_KINDS[kind][0]
    return f'{name} ({FOLDER_DUNGEON[folder]})'


def is_key_actor(actor):
    return key_actor_item(actor) is not None


DUNGEON_ITEM_TEXTS = {
    'fr': {'map': ('Carte : {n}', 'La carte du donjon « {n} ».', 'Vous avez obtenu la carte du donjon : {n} !',
                   'Ouvrez la carte pour voir ses salles.'),
           'compass': ('Boussole : {n}', 'La boussole du donjon « {n} ».',
                       'Vous avez obtenu la boussole du donjon : {n} !',
                       'La carte montre maintenant ses coffres et le boss.')},
    'en': {'map': ('Map: {n}', 'The map of the {n}.', 'You got the {n} map!', 'Open the map to see its rooms.'),
           'compass': ('Compass: {n}', 'The compass of the {n}.', 'You got the {n} compass!',
                       'The map now shows its chests and its boss.')},
}


def key_texts(actor, language):
    folder = actor_folder(actor)
    ring = actor.startswith(RING_PREFIX)
    kind = actor_kind(actor)
    if kind == 'small':
        if language.endswith('fr'):
            name = FRENCH_DUNGEONS[folder]
            return {'Name': f'Petite clé : {name}', 'Caption': f'Une petite clé du donjon « {name} ».',
                    'GetMessage': f'Vous avez obtenu une petite clé du donjon : {name} !',
                    'GetCaption': 'Elle ouvre une porte verrouillée de ce donjon.'}
        name = ENGLISH_DUNGEONS[folder]
        return {'Name': f'Small Key: {name}', 'Caption': f'A small key of the {name}.',
                'GetMessage': f'You got a {name} small key!',
                'GetCaption': 'It opens one locked door of this dungeon.'}
    if kind in ('map', 'compass'):
        french = language.endswith('fr')
        texts = DUNGEON_ITEM_TEXTS['fr' if french else 'en'][kind]
        name = (FRENCH_DUNGEONS if french else ENGLISH_DUNGEONS)[folder]
        return dict(zip(('Name', 'Caption', 'GetMessage', 'GetCaption'), (t.format(n=name) for t in texts)))
    if language.endswith('fr'):
        name = FRENCH_DUNGEONS[folder]
        if ring:
            return {'Name': f'Trousseau : {name}',
                    'Caption': f'Toutes les petites clés du donjon « {name} ».',
                    'GetMessage': f'Vous avez obtenu le trousseau du donjon : {name} !',
                    'GetCaption': 'Ses portes verrouillées peuvent maintenant s’ouvrir.'}
        return {'Name': f'Clé du boss : {name}',
                'Caption': f'La grande clé du donjon « {name} ».',
                'GetMessage': f'Vous avez obtenu la clé du boss : {name} !',
                'GetCaption': 'Elle ouvre la porte du boss de ce donjon.'}
    name = ENGLISH_DUNGEONS[folder]
    if ring:
        return {'Name': f'Key Ring: {name}', 'Caption': f'Every small key of the {name}.',
                'GetMessage': f'You got the {name} key ring!', 'GetCaption': 'Its locked doors can now open.'}
    return {'Name': f'Boss Key: {name}', 'Caption': f'The boss key of the {name}.',
            'GetMessage': f'You got the {name} boss key!', 'GetCaption': 'It opens the boss door of this dungeon.'}


def start_dungeon_values(options):
    """GameData values written at the end of the opening for the "start with" / "removed" modes.

    * maps and compasses "Start with": ``IsGetMap``/``IsGetCompass`` of every dungeon;
    * small keys "Removed": ``SmallKeyNum`` = every key of the dungeon (AP count),
      so the locked doors open as if the keys were found (an extra key is harmless);
    * boss keys "Removed": ``IsGetBossKey`` of the five temples (Ganon's key apart).
    """
    values = {}
    if options.get('shuffle_mapcompass') == 'startwith':
        for folder in MAP_DUNGEONS:
            values[f'DungeonInfo.{folder}.IsGetMap'] = True
            values[f'DungeonInfo.{folder}.IsGetCompass'] = True
    if options.get('shuffle_smallkeys') == 'remove':
        for folder, count in RING_DUNGEONS.items():
            values[f'DungeonInfo.{folder}.SmallKeyNum'] = count
            values[f'DungeonInfo.{folder}.SmallKeyTotalNum'] = count
    if options.get('shuffle_bosskeys') == 'remove':
        for folder in BOSS_KEY_DUNGEONS:
            values[f'DungeonInfo.{folder}.IsGetBossKey'] = True
    if options.get('shuffle_ganon_bosskey') == 'remove':
        values['DungeonInfo.InsideGanonCastle.IsGetBossKey'] = True
    return values


def start_logic_items(options):
    """AP items the logic holds from the start for the "removed" key modes."""
    items = {}
    if options.get('shuffle_smallkeys') == 'remove':
        items.update({small_key_item(folder): count for folder, count in RING_DUNGEONS.items()})
    if options.get('shuffle_bosskeys') == 'remove':
        items.update({f'Boss Key ({FOLDER_DUNGEON[folder]})': 1 for folder in BOSS_KEY_DUNGEONS})
    if options.get('shuffle_ganon_bosskey') == 'remove':
        items['Boss Key (Ganons Castle)'] = 1
    return items


def check_start_values(gamedata_raw, values):
    """Every start value names a saved GameData entry of the matching type."""
    from ootrr_full.formats.inspect_resources import Byml
    from ootrr_full.patching.soul_adapter import murmur3
    data = Byml(gamedata_raw).root['Data']
    for name, value in values.items():
        kind = 'Bool' if type(value) is bool else 'Int'
        entry = next((e for e in data[kind] if e['Hash'] == murmur3(name)), None)
        if entry is None or entry.get('SaveFileIndex') != 0:
            raise ValueError('Start value not found in the saved game data: ' + name)


def small_key_pose_parts(read_raw):
    """The authored native key pose and capture framing, without its generic effect."""
    from ootrr_full.patching.progressive import pose_parts
    from ootrr_full.formats import byml_codec
    from ootrr_full.formats.inspect_resources import sarc
    from ootrr_full.game.item_forms import _copy_ref, _pack_path, resolve_components
    from ootrr_full.patching.soul_adapter import RSDB_FILES, TEMPLATE
    import copy
    native_path = f'Pack/Actor/{SMALL_KEY_MODEL}.pack.zs'
    native_raw = read_raw(native_path)
    pose = pose_parts(lambda path: native_raw if path == native_path else read_raw(path), lender=SMALL_KEY_MODEL)
    if pose is None:
        raise ValueError('The native dungeon small-key item-get pose is missing.')
    files, refs, info = pose
    pack = sarc(native_raw)
    native_components = resolve_components(pack, SMALL_KEY_MODEL, byml_codec)
    capture = native_components.get('CaptureRef')
    if not capture:
        raise ValueError('The native dungeon small-key capture settings are missing.')
    _copy_ref(pack, capture, files, byml_codec)
    refs['CaptureRef'] = capture
    # The get display uses the centered medallion template's anchor. The key
    # mesh is authored from its bottom (Y center ~0.28), so preserving the raw
    # anchor clips it in a child's native camera. Recenter the mesh using only
    # original native bounds and the original native key's authored offset.
    # Never read the custom offset back: cache refreshes must not accumulate it.
    rows = {row['__RowId']: row for row in byml_codec.load(read_raw(RSDB_FILES['ActorInfo']))['root']}
    baseline = byml_codec.load(pack[_pack_path(native_components['PouchContentRef'])])['root']['GetDemoOffsetPos']
    template_pack = sarc(read_raw(f'Pack/Actor/{TEMPLATE}.pack.zs'))
    template_components = resolve_components(template_pack, TEMPLATE, byml_codec)
    pouch = byml_codec.load(template_pack[_pack_path(template_components['PouchContentRef'])])
    def center(actor, axis):
        return (rows[actor]['ModelAabbMin'][axis] + rows[actor]['ModelAabbMax'][axis]) / 2
    pouch['root']['GetDemoOffsetPos'] = {axis: baseline[axis] - center(SMALL_KEY_MODEL, axis) + center(TEMPLATE, axis)
                                        for axis in ('X', 'Y', 'Z')}
    pouch_path = 'Component/PouchContentParam/RandoSmallKeyGet.game__component__PouchContentParam.bgyml'
    files[pouch_path] = byml_codec.dump(pouch)
    refs['PouchContentRef'] = '?' + pouch_path
    info.update({key: copy.deepcopy(rows[SMALL_KEY_MODEL][key]) for key in ('ModelAabbMin', 'ModelAabbMax')})
    return files, refs, info


def key_specs(actors, read_raw=None):
    actors = tuple(actors)
    specs, pose = [], None
    if read_raw is not None and any(actor_kind(actor) == 'small' for actor in actors):
        pose = small_key_pose_parts(read_raw)
    for actor in sorted(actors):
        name = 'RandoKey_' + actor[len('Item_'):] + '.event.root'
        kind = actor_kind(actor)
        spec = {'actor': actor, 'model': SMALL_KEY_MODEL if kind in ('ring', 'small') else BOOL_KINDS[kind][2],
                'event_name': name, 'event_member': 'AI/' + name + '.ainb',
                'event_ain': 'Work/AI/Root/Event/' + name + '.ain',
                'texts': (lambda language, actor=actor: key_texts(actor, language))}
        if kind == 'small' and pose is not None:
            spec['files'], spec['components'], spec['actor_info'] = pose
        specs.append(spec)
    return specs


def key_records(items, actors=()):
    """Hook records for the key items of a seed (AP item names)."""
    items = set(items)
    records = []
    for item in sorted(items):
        if is_small_key(item):
            continue  # Repeated keys must be bound to actual per-copy actors.
        folder = item_folder(item)
        if is_ring(item):
            records.append({'kind': 'ring', 'actor': ring_actor(folder), 'folder': folder,
                            'count': RING_DUNGEONS[folder], 'applied': APPLIED_PREFIX + folder,
                            'gamedata': f'DungeonInfo.{folder}.SmallKeyNum'})
        else:
            actor = dungeon_item_actor(item) or boss_actor(folder)
            kind = actor_kind(actor)
            records.append({'kind': kind, 'actor': actor, 'folder': folder,
                            'gamedata': f'DungeonInfo.{folder}.{BOOL_KINDS[kind][1]}'})
    for actor in sorted(set(actors)):
        folder = small_key_folder(actor)
        if folder is not None:
            records.append({'kind': 'small', 'actor': actor, 'folder': folder, 'count': 1,
                            'applied': small_applied_flag(actor),
                            'once': f'DungeonInfo.{folder}.IsGetSmallKeyOnce',
                            'gamedata': f'DungeonInfo.{folder}.SmallKeyNum'})
    missing = {item for item in items if is_small_key(item)} - {
        key_actor_item(record['actor']) for record in records if record['kind'] == 'small'}
    if missing:
        raise ValueError('Dungeon small keys require distinct per-copy actors: ' + ', '.join(sorted(missing)))
    return records


def build_key_files(read_raw, records, message_archives=()):
    """``(modified, new)`` resources of the key actors, plus their saved flags."""
    from ootrr_full.patching.soul_adapter import build_item_files, GAMEDATA
    from ootrr_full.game.tracking_metadata import add_saved_flags
    if not records:
        return {}, {}
    modified, new = build_item_files(read_raw, key_specs([r['actor'] for r in records], read_raw), message_archives)
    applied = {r['applied']: False for r in records if r['kind'] in ('ring', 'small')}
    if applied:
        raw = modified.get(GAMEDATA)
        modified[GAMEDATA] = add_saved_flags(raw if raw is not None else read_raw(GAMEDATA), applied)
    return modified, new


def got_flag(actor):
    """Saved Bool the pouch sets once ``actor`` is got (``soul_adapter.FLAG_PREFIX``)."""
    return 'IsGet.' + actor


def check_dungeon_data(gamedata_raw, records):
    """Every GameData name written by the hook exists (saved) in the game."""
    from ootrr_full.formats.inspect_resources import Byml
    from ootrr_full.patching.soul_adapter import murmur3
    data = Byml(gamedata_raw).root['Data']
    types = {'ring': 'Int', 'small': 'Int', 'boss': 'Bool', 'map': 'Bool', 'compass': 'Bool'}
    for record in records:
        entries = {e['Hash']: e for e in data[types[record['kind']]]}
        names = [record['gamedata']] + ([total_keys(record['gamedata'])] if record['kind'] in ('ring', 'small') else [])
        for name in names:
            entry = entries.get(murmur3(name))
            if entry is None or entry.get('SaveFileIndex') != 0:
                raise ValueError('Dungeon data not found: ' + name)
        if record['kind'] == 'small':
            once = next((e for e in data['Bool'] if e['Hash'] == murmur3(record['once'])), None)
            if once is None or once.get('SaveFileIndex') != 0:
                raise ValueError('Dungeon data not found: ' + record['once'])


def check_got_flags(gamedata_raw, records):
    """The hook's ``IsGet.<actor>`` tests are saved Bools of the seed's GameData."""
    from ootrr_full.formats.inspect_resources import Byml
    from ootrr_full.patching.soul_adapter import murmur3
    saved = {e['Hash'] for e in Byml(gamedata_raw).root['Data']['Bool'] if e.get('SaveFileIndex') == 0}
    for record in records:
        if murmur3(got_flag(record['actor'])) not in saved:
            raise ValueError('Get flag of a key item not saved: ' + got_flag(record['actor']))


def add_key_hook(raw, records):
    """Prepend the key checks to ``ActionGuide/ActionGuide``. Returns (bytes, report).

    Bool switches: case 0 = true (as the vanilla flows).
    """
    from evfl.actor import Actor
    from evfl.common import ActorIdentifier, StringHolder
    from evfl.container import Container
    from evfl.event import Event, ActionEvent, SwitchEvent
    from evfl.util import make_index, make_rindex
    from ootrr_full.patching.event_patch import _flow, _snapshot, GAMEDATA_ACTOR_PARAMS
    flow = _flow(raw)
    chart = flow.flowchart
    expected = _snapshot(flow)
    entries = {e.name: e for e in chart.entry_points}
    if ACTION_GUIDE_ENTRY not in entries or entries[ACTION_GUIDE_ENTRY].main_event.v is None:
        raise ValueError('Flow ActionGuide inattendu.')
    if any(e.name.startswith('RandoKey') for e in chart.events):
        raise ValueError('ActionGuide flow already has the keys.')

    def system_actor(name, params):
        actor = next((a for a in chart.actors if a.identifier.name == name and a.identifier.sub_name == ''), None)
        if actor is None:
            actor = Actor()
            actor.identifier = ActorIdentifier(name)
            actor.concurrent_clips = 1
            actor.params = Container()
            actor.params.data = dict(params)
            chart.actors.append(actor)
        return actor

    def holder(collection, name):
        found = next((h for h in collection if h.v == name), None)
        if found is None:
            found = StringHolder(name)
            collection.append(found)
        return found

    # A named actor without its parameter container crashes the game (seen with
    # GameDataActor at the end of the intro): vanilla parameters.
    gamedata = system_actor('GameDataActor', GAMEDATA_ACTOR_PARAMS)
    is_bool = holder(gamedata.queries, 'EventQueryIsGameDataBool')
    set_bool = holder(gamedata.actions, 'EventTriggerSetGameDataBool')
    add_int = holder(gamedata.actions, 'EventTriggerAddOrSubGameDataInt')

    def event(name, data):
        e = Event()
        e.name, e.data = name, data
        chart.events.append(e)
        return e

    def action(name, actor, act, params):
        data = ActionEvent()
        data.actor, data.actor_action = make_rindex(actor), make_rindex(act)
        data.params = Container()
        data.params.data = dict(params)
        expected[name] = dict(params)
        return event(name, data)

    def switch(name, actor, query, params, true, false):
        data = SwitchEvent()
        data.actor, data.actor_query = make_rindex(actor), make_rindex(query)
        data.params = Container()
        data.params.data = dict(params)
        data.cases = {0: make_index(true), 1: make_index(false)}
        expected[name] = dict(params)
        return event(name, data)

    entry = entries[ACTION_GUIDE_ENTRY]
    following = entry.main_event.v
    report = []
    # Built from the last record backwards: each check continues to the next one.
    for record in reversed(records):
        stem = record['actor'][len('Item_'):]
        if record['kind'] in ('ring', 'small'):
            mark = action(f'RandoKeyApplied_{stem}', gamedata, set_bool,
                          {'GameDataName': record['applied'], 'Value': True, 'Index': -1})
            mark.data.nxt = make_index(following)
            # Keys found too (SmallKeyTotalNum), as the native key get credits them:
            # held keys alone did not show in the dungeon (15/11, Discord report).
            found = action(f'RandoKeyFound_{stem}', gamedata, add_int,
                           {'GameDataName': total_keys(record['gamedata']), 'Value': record['count'], 'Index': -1})
            found.data.nxt = make_index(mark)
            if record['kind'] == 'small':
                once = action(f'RandoKeyOnce_{stem}', gamedata, set_bool,
                              {'GameDataName': record['once'], 'Value': True, 'Index': -1})
                once.data.nxt = make_index(mark)
                found.data.nxt = make_index(once)
            give = action(f'RandoKeyGive_{stem}', gamedata, add_int,
                          {'GameDataName': record['gamedata'], 'Value': record['count'], 'Index': -1})
            give.data.nxt = make_index(found)
            done = switch(f'RandoKeyDone_{stem}', gamedata, is_bool,
                          {'GameDataName': record['applied'], 'Index': -1}, following, give)
            first = switch(f'RandoKeyHeld_{stem}', gamedata, is_bool,
                           {'GameDataName': got_flag(record['actor']), 'Index': -1}, done, following)
        else:
            give = action(f'RandoKeyGive_{stem}', gamedata, set_bool,
                          {'GameDataName': record['gamedata'], 'Value': True, 'Index': -1})
            give.data.nxt = make_index(following)
            first = switch(f'RandoKeyHeld_{stem}', gamedata, is_bool,
                           {'GameDataName': got_flag(record['actor']), 'Index': -1}, give, following)
        report.append({'actor': record['actor'], 'start': first.name})
        following = first
    entry.main_event = make_index(following)
    stream = io.BytesIO()
    flow.write(stream)
    result = stream.getvalue()
    checked = _flow(result)
    if _snapshot(checked) != expected:
        raise ValueError('Dungeon keys changed other parameters.')
    start = {e.name: e for e in checked.flowchart.entry_points}[ACTION_GUIDE_ENTRY].main_event.v
    if records and start.name != f"RandoKeyHeld_{records[0]['actor'][len('Item_'):]}":
        raise ValueError('ActionGuide entry wrongly attached to the keys.')
    if any(r['kind'] == 'small' for r in records):
        result = add_small_converter(result, records)
    return result, list(reversed(report))


def append_small_key_grant(editor, actor, stem, after):
    """Apply precisely this copy once, including spent-key and retry protection."""
    from ootrr_full.patching.progressive import link
    folder = small_key_folder(actor)
    if folder is None:
        raise ValueError('Invalid dungeon small-key token: ' + str(actor))
    flag = small_applied_flag(actor)
    mark = editor.action(stem + '_Applied', 'GameDataActor', 'EventTriggerSetGameDataBool',
                         {'GameDataName': flag, 'Index': -1, 'Value': True})
    link(mark, after)
    once = editor.action(stem + '_Once', 'GameDataActor', 'EventTriggerSetGameDataBool',
                         {'GameDataName': f'DungeonInfo.{folder}.IsGetSmallKeyOnce', 'Index': -1, 'Value': True})
    link(once, mark)
    total = editor.action(stem + '_Total', 'GameDataActor', 'EventTriggerAddOrSubGameDataInt',
                          {'GameDataName': f'DungeonInfo.{folder}.SmallKeyTotalNum', 'Index': -1, 'Value': 1})
    link(total, once)
    held = editor.action(stem + '_Key', 'GameDataActor', 'EventTriggerAddOrSubGameDataInt',
                         {'GameDataName': f'DungeonInfo.{folder}.SmallKeyNum', 'Index': -1, 'Value': 1})
    link(held, total)
    return editor.switch(stem + '_Done', 'GameDataActor', 'EventQueryIsGameDataBool',
                         {'GameDataName': flag, 'Index': -1}, after, held)


def add_small_converter(raw, records):
    """Quiet fallback for pickups whose authored gift skips ActionGuide."""
    from evfl.entry_point import EntryPoint
    from evfl.util import make_index
    from ootrr_full.patching.progressive import FlowEditor
    editor = FlowEditor(raw, 'ActionGuide')
    if any(e.name == SMALL_ENTRY for e in editor.chart.entry_points):
        raise ValueError('Small-key converter already present.')
    following = None
    for record in reversed([r for r in records if r['kind'] == 'small']):
        actor = record['actor']
        stem = 'RandoSmall_' + actor[len('Item_'):]
        give = append_small_key_grant(editor, actor, stem, following)
        following = editor.switch(stem + '_Got', 'GameDataActor', 'EventQueryIsGameDataBool',
                                  {'GameDataName': got_flag(actor), 'Index': -1}, give, following)
    entry = EntryPoint(SMALL_ENTRY)
    entry.main_event = make_index(following)
    editor.chart.entry_points.append(entry)
    return editor.write('Dungeon small-key converter')[0]


def small_key_watch(raw, actors):
    from ootrr_full.patching.progressive import patch_main_update
    return patch_main_update(raw, actors, event_name=SMALL_ENTRY, got_name=got_flag,
                             applied_name=small_applied_flag, guid_prefix='0a9a9b01')


# Tracker: Ganon's Castle boss key (Ganon's Tower) is shown with the temples' ones.
TRACKED_BOSS_KEYS = BOSS_KEY_DUNGEONS + ('InsideGanonCastle',)


def key_tracking(options, saved_keys):
    """Tracker rows of the dungeon keys: GameData hashes to read, per dungeon.

    ``saved_keys``: {'Int': hashes, 'Bool': hashes} of the saved GameData entries.
    Small keys found = max(``SmallKeyTotalNum``, ``SmallKeyNum`` held), or every key
    once the key ring is applied (``RandoKeyRing.<folder>``) or with keys "Removed".
    """
    from ootrr_full.game.remake_world import ZONE_LABELS
    from ootrr_full.patching.soul_adapter import murmur3
    options = options or {}
    removed_small = options.get('shuffle_smallkeys') == 'remove'
    removed_boss = options.get('shuffle_bosskeys') == 'remove'
    rows = []
    for folder in dict.fromkeys(list(RING_DUNGEONS) + list(TRACKED_BOSS_KEYS)):
        base = f'DungeonInfo.{folder}.'
        row = {'folder': folder, 'dungeon': ZONE_LABELS.get(folder, folder), 'small': None, 'boss': None}
        if folder in RING_DUNGEONS:
            found, held = murmur3(base + 'SmallKeyTotalNum'), murmur3(base + 'SmallKeyNum')
            if {found, held} <= saved_keys.get('Int', set()):
                ring = murmur3(APPLIED_PREFIX + folder)
                total = RING_DUNGEONS[folder]
                from ootrr_full.game.native_key_limits import NATIVE_SMALL_KEYS, enabled as native_keys_enabled
                if native_keys_enabled(options) and not removed_small and ring not in saved_keys.get('Bool', set()):
                    total = NATIVE_SMALL_KEYS[folder]
                row['small'] = {'total': total, 'found': str(found), 'held': str(held),
                                'ring': str(ring) if ring in saved_keys.get('Bool', set()) else None,
                                'all': removed_small}
        if folder in TRACKED_BOSS_KEYS:
            boss = murmur3(base + 'IsGetBossKey')
            if boss in saved_keys.get('Bool', set()):
                row['boss'] = {'hash': str(boss), 'all': removed_boss and folder in BOSS_KEY_DUNGEONS}
        if row['small'] or row['boss']:
            rows.append(row)
    return rows


def dungeon_keys(rows, snapshot):
    """``[(dungeon, (found, total) or None, has boss key or None)]`` from a save snapshot."""
    ints, bools = (snapshot or {}).get('int', {}), (snapshot or {}).get('bool', {})
    result = []
    for row in rows or ():
        small = row.get('small')
        if small:
            found = max(int(ints.get(int(small['found']), 0) or 0), int(ints.get(int(small['held']), 0) or 0))
            if small['all'] or (small['ring'] and bools.get(int(small['ring']))):
                found = max(found, small['total'])
            small = (found, max(small['total'], found))
        boss = row.get('boss')
        if boss:
            boss = bool(boss['all'] or bools.get(int(boss['hash'])))
        result.append((row['dungeon'], small, boss))
    return result
