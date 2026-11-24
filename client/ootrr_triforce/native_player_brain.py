"""Preserve the native Player brain's command-result contract for C clients.

Native C clients have their own game-thread receipt guard. Their Player AI must
retain its original success result instead of publishing the external client's
readiness Bool. Only our exact known v1/v2 replacement can be removed.
"""
import copy
import hashlib
from pathlib import Path

from . import upgrade_readiness as gate


def _document(raw):
    import ainb
    return ainb.AINB.from_binary(raw).as_dict()


def _normalized(document):
    """The shipped global queries differ only in optional diagnostic output."""
    document = copy.deepcopy(document)
    if len(document.get('Nodes', ())) != 12:
        return document
    for index in (7, 9):
        for value in document['Nodes'][index].get('Properties', {}).get('Bool', ()):
            if value.get('Name') == 'DispError' and type(value.get('Default Value')) is bool:
                value['Default Value'] = False
    return document


def recognized_brain(current, original, token, templates, old_query):
    """Return native/v1/v2, rejecting unknown or another room's Player graph."""
    flag = gate.readiness_name(token)
    # The existing publisher validates the immutable native one-node contract.
    expected = _document(gate.patch_player_brain(original, flag, templates))
    document = _document(current)
    if document == _document(original):
        return 'native'
    if _normalized(document) == _normalized(expected):
        return 'v2'
    legacy = copy.deepcopy(expected)
    query = copy.deepcopy(old_query)
    query.update({'Node Index': 1, 'GUID': gate._guid(flag, 1), 'Plugs': {}, 'Queries': []})
    query['Parameters']['Inputs']['Int'][0] = gate._default('ActionSlot', 0)
    legacy['Nodes'][1] = query
    if _normalized(document) == _normalized(legacy):
        return 'v1'
    raise ValueError('Refusing to replace an unknown or different-room Player brain.')


def stage_player_packs(packs, originals, token, templates, old_query, compression):
    """Validate every actor before returning bytes; callers write only on success."""
    from ootrr_full.formats import byml_codec
    from ootrr_full.formats.inspect_resources import sarc
    staged, states, hashes = {}, {}, {}
    for path in gate.PLAYER_PACKS:
        original = originals[path]
        original_files = sarc(compression.decode(original))
        source_brain = original_files[gate.BRAIN]
        # Check immutable sources even when no overlay exists.
        gate.patch_player_brain(source_brain, gate.readiness_name(token), templates)
        hashes[path] = hashlib.sha256(source_brain).hexdigest()
        frame = packs.get(path)
        if frame is None:
            states[path] = 'native'
            continue
        files = dict(sarc(compression.decode(frame)))
        if gate.BRAIN not in files:
            raise ValueError('The overridden Player actor has no native brain: ' + path)
        state = recognized_brain(files[gate.BRAIN], source_brain, token, templates, old_query)
        states[path] = state
        if state == 'native':
            continue
        files[gate.BRAIN] = source_brain
        changed = compression.encode(byml_codec.build_sarc(files), frame)
        verified = sarc(compression.decode(changed))
        if verified != files or set(verified) != set(files):
            raise ValueError('Restored Player actor failed round-trip verification.')
        staged[path] = changed
    return staged, {'version': 1, 'source_brains': hashes}, states


def prepare_native_player_brains(romfs, artifact, token, *, game_source=None):
    """Restore exact native brains, preserving every other overridden pack member."""
    from ootrr_full.formats.inspect_nup import Nup
    from ootrr_full.formats.inspect_resources import decompress, dictionaries, sarc
    from ootrr_full.game.world_maps import effective_members
    from ootrr_triforce.mod_codec import Codec
    romfs, artifact = Path(romfs), Path(artifact)
    source = Path(game_source or romfs)
    if source.is_dir() and (source / 'romfs/Pack/ZsDic.pack.zs').is_file():
        source /= 'romfs'
    nup = Nup(source)
    try:
        members, dictionary = effective_members(nup), dictionaries(nup)
        def read(path):
            raw = nup.read(members[path])
            return decompress(raw, dictionary) if path.endswith('.zs') else raw
        global_files = sarc(read(gate.GLOBAL_PACK))
        templates = gate.native_templates(global_files, sarc(read(gate.NAVI_PACK)))
        old_query = gate._template(global_files, 'QueryPlayerGetCurrentActionVerb')
        compression = Codec((romfs / 'Pack/ZsDic.pack.zs').read_bytes())
        originals = {path: nup.read(members[path]) for path in gate.PLAYER_PACKS}
        mod = artifact / 'romfs'
        packs = {path: (mod / path).read_bytes() for path in gate.PLAYER_PACKS
                 if (mod / path).is_file()}
        staged, metadata, states = stage_player_packs(
            packs, originals, token, templates, old_query, compression)
        # Every decode, recognition and encode has succeeded before any write.
        for path, raw in staged.items():
            (mod / path).write_bytes(raw)
        return metadata, states, tuple(staged)
    finally:
        nup.stream.close()
