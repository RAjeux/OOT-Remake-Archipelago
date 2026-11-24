"""Reconcile complete native resource budgets after composing full-mode passes.

Actor packs contain independently allocated AI and parameter files. Budgeting
only the outer pack can leave a larger Player brain unbuilt during a map load.
This pass compares against immutable game resources, so repeating it is safe.
"""
import struct
from pathlib import Path
import zlib

from ootrr_full.game.resource_allocations import add_resources, grow_resources

REST = 'System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs'


def table(raw):
    if len(raw) < 22 or raw[:6] != b'RESTBL':
        raise ValueError('Invalid full-network resource-size table.')
    version, block, count, names = struct.unpack_from('<IIII', raw, 6)
    if version != 1 or block != 160 or len(raw) != 22 + count * 8 + names * (block + 4):
        raise ValueError('Unsupported full-network resource-size table.')
    hashed = dict(struct.iter_unpack('<II', raw[22:22 + count * 8]))
    named = {}
    for index in range(names):
        position = 22 + count * 8 + index * (block + 4)
        name = raw[position:position + block].split(b'\0', 1)[0].decode('utf-8')
        if name in named:
            raise ValueError('Duplicate named resource allocation.')
        named[name] = struct.unpack_from('<I', raw, position + block)[0]
    if len(hashed) != count:
        raise ValueError('Duplicate hashed resource allocation.')
    return hashed, named


def reconcile(raw, original_table, resources, *, known_paths):
    """resources: path -> (original byte size or None, maximum composed size)."""
    current_h, current_n = table(raw)
    source_h, source_n = table(original_table)
    known = {path.removesuffix('.zs') for path in known_paths}
    growth, additions = {}, {}
    for path, (old, new) in sorted(resources.items()):
        target = path.removesuffix('.zs')
        digest = zlib.crc32(target.encode('utf-8'))
        current = current_n.get(target, current_h.get(digest))
        original = source_n.get(target, source_h.get(digest))
        native = old is not None or target in known
        if (old is not None and (type(old) is not int or old < 0)
                or type(new) is not int or not 0 < new < 1 << 32):
            raise ValueError('Invalid composed native resource size.')
        if original is not None and native and old is not None:
            # Keep native parser/object overhead, in addition to the byte growth.
            required = original + max(0, new - old)
        else:
            required = new + 4096
        if required >= 1 << 32:
            raise ValueError('Composed native resource budget is too large.')
        if current is None:
            additions[path] = (required + 4095) & ~4095
        elif old is None and not native and target not in current_n and digest in source_h:
            # A new resource must not silently reuse another native path's CRC.
            additions[path] = (required + 4095) & ~4095
        elif current < required:
            growth[path] = required - current
    result, grown = grow_resources(raw, growth)
    if additions:
        result, inserted = add_resources(result, additions, known_paths=known_paths)
    else:
        inserted = []
    return result, grown + inserted


def prepare_allocations(romfs, artifact, *, game_source=None):
    from ootrr_full.formats.inspect_nup import Nup
    from ootrr_full.formats.inspect_resources import decompress, dictionaries, sarc
    from ootrr_full.game.world_maps import effective_members
    from .mod_codec import Codec
    romfs, artifact = Path(romfs), Path(artifact)
    source = Path(game_source or romfs)
    if source.is_dir() and (source / 'romfs/Pack/ZsDic.pack.zs').is_file():
        source /= 'romfs'
    nup = Nup(source)
    try:
        members = effective_members(nup)
        dictionary = dictionaries(nup)
        mod = artifact / 'romfs'
        codec = Codec((romfs / 'Pack/ZsDic.pack.zs').read_bytes())
        def original(path):
            if path not in members:
                return None
            frame = nup.read(members[path])
            return decompress(frame, dictionary) if path.endswith('.zs') else frame
        original_rest = original(REST)
        if original_rest is None:
            raise ValueError('The original native resource-size table is missing.')
        resources, known = {}, set(members)
        def record(path, before, after):
            previous = resources.get(path)
            old = len(before) if before is not None else None
            size = len(after)
            if previous is None:
                resources[path] = (old, size)
            else:
                if old is not None and (previous[0] is None or old < previous[0]):
                    previous = (old, previous[1])
                resources[path] = (previous[0], max(previous[1], size))
        for file in sorted(mod.rglob('*')):
            if not file.is_file():
                continue
            path = file.relative_to(mod).as_posix()
            if path == REST or not path.endswith(('.zs', '.ainb', '.bgyml', '.byml')):
                continue
            frame = file.read_bytes()
            after = codec.decode(frame) if path.endswith('.zs') else frame
            before = original(path)
            record(path, before, after)
            if path.endswith(('.pack.zs', '.sarc.zs')):
                old_pack = sarc(before) if before is not None else {}
                known.update(old_pack)
                for name, raw in sarc(after).items():
                    previous = old_pack.get(name)
                    if previous is None:
                        previous = original(name)
                    record(name, previous, raw)
        # A cloned pack also carries unchanged parameters inherited from its
        # template. Their native names live inside another pack, rather than as
        # loose NUP members. Resolve those names before identifying CRC aliases.
        for path in members:
            if path.startswith('Pack/') and path.endswith('.pack.zs'):
                known.update(sarc(original(path)))
        target = mod / REST
        frame = target.read_bytes()
        after, changed = reconcile(codec.decode(frame), original_rest, resources, known_paths=known)
        if after != codec.decode(frame):
            target.write_bytes(codec.encode(after, frame))
        return {'version': 1, 'resources': len(resources), 'changed': changed}
    finally:
        nup.stream.close()
