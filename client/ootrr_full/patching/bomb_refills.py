"""Ammunition must never award its weapon capacity as a side effect.

The engine's SmallBagActor pouch parameter automatically grants that actor on
the first refill. Bombs and bombchus name the small bomb bag in vanilla; arrows
and seeds also reference the smallest quiver or bullet bag. Actual AP weapons
initialize their own capacity when received. Clear only these ammunition actor
references, retaining ammunition counts and the independently earned capacity.
Every embedded copy must agree, regardless of which pack loads it first.
"""
from ootrr_full.formats import byml_codec
from ootrr_full.formats.inspect_resources import sarc
from ootrr_full.patching.soul_adapter import RSDB_FILES

BAG_ACTOR = 'Work/Actor/Item_BombBag_Small.engine__actor__ActorParam.gyml'
BAG_REFERENCES = {
    'Bomb': BAG_ACTOR,
    'Bombchu': BAG_ACTOR,
    'Arrow': 'Work/Actor/Item_Quiver_Small.engine__actor__ActorParam.gyml',
    'DekuSeed': 'Work/Actor/Item_BulletBag_Small.engine__actor__ActorParam.gyml',
}
POUCH_PATHS = tuple(f'Component/PouchContentParam/{actor}.game__component__PouchContentParam.bgyml'
                    for actor in ('Item_Bomb', 'Item_Bombchu', 'ArrowDefault', 'Item_DekuSeed'))
# Exhaustively checked against the supported game's actor packs (see tests).
NATIVE_PACKS = tuple(f'Pack/Actor/{actor}.pack.zs' for actor in (
    'Item_Bomb', 'Item_Bombchu', 'Npc_Hylia_ImperialSoldier_Bomb',
    'Obj_Bomb', 'Obj_Bombchu', 'Pouch_Bomb', 'Pouch_Bombchu',
    'Item_Arrow_Normal', 'NormalArrow', 'Pouch_Arrow_Normal', 'Pouch_Range_BowAndArrow_Normal',
    'Item_DekuSeed', 'Obj_DekuSeed',
    *(f'Shop_BombchuBundle_{i:02}' for i in range(1, 9))))


def patch_pack(raw):
    """Return (SARC bytes, changed pouch paths), including for derived packs."""
    files = dict(sarc(raw))
    changed = []
    for path in files:
        if not path.startswith('Component/PouchContentParam/') or not path.endswith('.bgyml'):
            continue
        document = byml_codec.load(files[path])
        row = document['root']
        expected = BAG_REFERENCES.get(row.get('MaxNumGameData'))
        if expected is None:
            continue
        value = row.get('SmallBagActor', '')
        if not value:
            continue
        if value != expected:
            raise ValueError('Unexpected ammunition capacity actor: ' + path)
        # Empty references are the native representation of an absent actor.
        document['root']['SmallBagActor'] = ''
        files[path] = byml_codec.dump(document)
        changed.append(path)
    return (byml_codec.build_sarc(files) if changed else raw), changed


def apply(existing, generated, read_raw, tables=None):
    """Compose native and generated packs after all other actor changes."""
    records = {}
    paths = set(NATIVE_PACKS) | {p for p in existing if p.startswith('Pack/Actor/')}
    for path in sorted(paths):
        raw = existing[path] if path in existing else read_raw(path)
        patched, changed = patch_pack(raw)
        if changed:
            existing[path] = patched
            records[path] = changed
    for path, (raw, template) in list(generated.items()):
        if path.startswith('Pack/Actor/'):
            patched, changed = patch_pack(raw)
            if changed:
                generated[path] = patched, template
                records[path] = changed
    pouch_document = None
    if tables is None:
        path = RSDB_FILES['PouchActorInfo']
        pouch_document = byml_codec.load(existing[path] if path in existing else read_raw(path))
        tables = {'PouchActorInfo': pouch_document['root']}
    if tables is not None:
        changed = []
        for row in tables.get('PouchActorInfo', ()):
            expected = BAG_REFERENCES.get(row.get('MaxNumGameData'))
            if expected is None or not row.get('SmallBagActor'):
                continue
            if row['SmallBagActor'] != expected:
                raise ValueError('Unexpected ammunition capacity in PouchActorInfo: ' + row['__RowId'])
            row['SmallBagActor'] = ''
            changed.append(row['__RowId'])
        if changed:
            records['RSDB/PouchActorInfo'] = sorted(changed)
            if pouch_document is not None:
                existing[RSDB_FILES['PouchActorInfo']] = byml_codec.dump(pouch_document)
    return records
