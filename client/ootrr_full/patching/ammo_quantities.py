"""Exact AP ammunition bundles, leaving vanilla bundle actors unchanged.

Native get sequences use the actor's bundle metadata, including its count in
the pickup window. AP amounts therefore need distinct native bundle actors.
World pickups use their separately guarded native callback instead.
"""
import copy
import re

PREFIX = 'Item_FullAmmo_'
_FAMILIES = {
    'Bombs': ('Bomb', 'Item_Bomb', 'Item_BombBundle_Small'),
    'Arrows': ('Arrow', 'Item_Arrow_Normal', 'TBox_ArrowBundle_Large'),
    'Deku Seeds': ('Seed', 'Item_DekuSeed', 'TBox_DekuSeedBundle'),
    'Deku Nuts': ('Nut', 'Item_DekuNut', 'TBox_DekuNutBundle'),
}
EXACT_AMMUNITION = (
    ('Bombs (', 'Item_Bomb', ('Item_BombBundle_',)),
    ('Arrows (', 'Item_Arrow_Normal', ('TBox_ArrowBundle_',)),
    ('Deku Seeds (', 'Item_DekuSeed', ('TBox_DekuSeedBundle',)),
    ('Deku Nuts (', 'Item_DekuNut', ('TBox_DekuNutBundle',)),
)
AMMUNITION_CAPACITY = {
    'Item_Bomb': ('Item_BombBag_Small', 'Item_BombBag_Medium', 'Item_BombBag_Large'),
    'Item_Arrow_Normal': ('Item_Quiver_Small', 'Item_Quiver_Medium', 'Item_Quiver_Large'),
    'Item_DekuSeed': ('Item_BulletBag_Small', 'Item_BulletBag_Medium', 'Item_BulletBag_Large'),
}


def exact_ammunition_grant(canonical, item):
    """Native unit/count for an AP ammunition name and its matching physical form."""
    if not isinstance(item, str):
        return None
    for prefix, actor, forms in EXACT_AMMUNITION:
        if not canonical.startswith(forms) or not item.startswith(prefix) or not item.endswith(')'):
            continue
        count = item[len(prefix):-1]
        if not count.isdecimal() or not 0 < int(count) <= 999:
            raise ValueError('Invalid ammunition quantity: ' + item)
        return actor, int(count)
    return None


def ammunition_capacity(canonical, native_info=None):
    """Native bag ownership required by bombs, arrows and seeds, including aliases."""
    if canonical in AMMUNITION_CAPACITY:
        return AMMUNITION_CAPACITY[canonical]
    for _, unit, forms in EXACT_AMMUNITION:
        if unit in AMMUNITION_CAPACITY and canonical.startswith(forms):
            return AMMUNITION_CAPACITY[unit]
    bundle = (native_info or {}).get('BundleActor', '')
    for actor, capacities in AMMUNITION_CAPACITY.items():
        if bundle == 'Work/Actor/' + actor + '.engine__actor__ActorParam.gyml':
            return capacities
    return ()


def quantity_spec(item):
    match = re.fullmatch(r'(Bombs|Arrows|Deku Seeds|Deku Nuts) \(([0-9]+)\)', item)
    if match is None:
        return None
    amount = int(match[2])
    if not 0 < amount <= 999:
        raise ValueError('Invalid ammunition quantity: ' + item)
    code, unit, base = _FAMILIES[match[1]]
    return dict(actor=PREFIX + code + str(amount), unit=unit, amount=amount, base=base)


def quantity_actor(item):
    spec = quantity_spec(item)
    return spec['actor'] if spec else None


def alias_base(actor):
    if not actor.startswith(PREFIX):
        return actor
    for code, unit, base in _FAMILIES.values():
        suffix = actor.removeprefix(PREFIX + code)
        if suffix != actor and suffix.isdecimal() and 0 < int(suffix) <= 999:
            return base
    raise ValueError('Unknown AP ammunition actor: ' + actor)


def build_files(read_raw, items, message_archives=()):
    """(modified resources, new packs), composed with earlier generator patches."""
    from ootrr_full.formats import byml_codec
    from ootrr_full.formats.inspect_resources import sarc
    from ootrr_full.game.item_forms import resolve_components, _pack_path
    from ootrr_full.patching.soul_adapter import RSDB_FILES
    specs = {row['actor']: row for item in items if (row := quantity_spec(item))}
    if not specs:
        return {}, {}
    modified, new = {}, {}
    for actor, spec in sorted(specs.items()):
        base = spec['base']
        template_path = 'Pack/Actor/' + base + '.pack.zs'
        files = dict(sarc(read_raw(template_path)))
        param_path = 'Actor/' + base + '.engine__actor__ActorParam.bgyml'
        param = byml_codec.load(files.pop(param_path))
        # Retain the original model and native localized name. Pouch identity is
        # distinct so the engine resolves this amount, not the template's count.
        components = param['root'].setdefault('Components', {})
        merged = resolve_components(dict(files, **{param_path: byml_codec.dump(param)}), base, byml_codec)
        native_pouch = merged.get('PouchContentRef')
        if not native_pouch or _pack_path(native_pouch) not in files:
            raise ValueError('Native ammunition bundle pouch is missing: ' + base)
        pouch_path = 'Component/PouchContentParam/' + actor + '.game__component__PouchContentParam.bgyml'
        files[pouch_path] = byml_codec.dump({'endian': '<', 'version': 7, 'root': {
            '$parent': 'Work/' + _pack_path(native_pouch)[:-6] + '.gyml',
            'PouchActor': 'Work/Actor/' + actor + '.engine__actor__ActorParam.gyml',
            'BundleActor': 'Work/Actor/' + spec['unit'] + '.engine__actor__ActorParam.gyml',
            'BundleActorNum': spec['amount'], 'SmallBagActor': '', 'IsAbleToGetBagIfGet': False,
            'IsBundle': True}})
        name_path = 'ActorSystem/ActorName/' + actor + '.engine__actor__ActorName.bgyml'
        components.update(PouchContentRef='?' + pouch_path, ActorNameRef='?' + name_path)
        files['Actor/' + actor + '.engine__actor__ActorParam.bgyml'] = byml_codec.dump(param)
        new['Pack/Actor/' + actor + '.pack.zs'] = byml_codec.build_sarc(files), template_path
    for table, path in RSDB_FILES.items():
        document = byml_codec.load(read_raw(path))
        rows = document['root']
        by_id = {row['__RowId']: row for row in rows}
        for actor, spec in sorted(specs.items()):
            if actor in by_id or spec['base'] not in by_id:
                raise ValueError('Unexpected ammunition alias table: ' + table)
            row = copy.deepcopy(by_id[spec['base']])
            row['__RowId'] = actor
            if table == 'ActorInfo':
                row['ActorName'] = actor
            elif table == 'PouchActorInfo':
                row.update(BundleActor='Work/Actor/' + spec['unit'] + '.engine__actor__ActorParam.gyml',
                           BundleActorNum=spec['amount'], SmallBagActor='')
            rows.append(row)
        rows.sort(key=lambda row: row['__RowId'])
        modified[path] = byml_codec.dump(document)
    from ootrr_full.patching.soul_adapter import patch_item_messages
    def texts(spec, language):
        french = language.endswith('fr')
        unit = {'Item_Bomb': ('bombs', 'bombes'), 'Item_Arrow_Normal': ('arrows', 'flèches'),
                'Item_DekuSeed': ('Deku Seeds', 'graines Mojo'), 'Item_DekuNut': ('Deku Nuts', 'noix Mojo')}[spec['unit']]
        name = str(spec['amount']) + ' ' + unit[french]
        return {'Name': name, 'Caption': name, 'GetMessage': name, 'GetCaption': ''}
    for path in message_archives:
        language = path.rsplit('/', 1)[-1].split('.')[0]
        modified[path] = patch_item_messages(read_raw(path), language,
                                             {actor: (lambda lang, spec=spec: texts(spec, lang))
                                              for actor, spec in specs.items()})
    return modified, new
