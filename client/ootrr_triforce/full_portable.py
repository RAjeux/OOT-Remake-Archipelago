"""Apply independent OOTRR native patches to a staged full-network mod.

The Rust helper never generates a pool or replaces an AP placement. Its exact
resource ledger is reconciled with the existing RESTBL, including packed AI
modules and native CRC collisions, before the artifact can be published.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import struct
import zlib

from ootrr_full.game.portable_options import native_values, unrecorded
from ootrr_full.game.resource_allocations import add_resources, grow_resources

REST = 'System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs'
_PREFIXES = ('Pack/Actor/', 'AI/', 'Banc/', 'Component/', 'Sequence/', 'Logic/', 'GameParameter/',
             'Event/EventFlow/', 'Event/EventSetting/', 'RSDB/', 'Mals/', 'GameData/',
             'Phive/NavMesh/', 'Phive/StitchedNavMesh/')
_FILES = ('Pack/ZsDic.pack.zs', 'Pack/AI.Global.Product.111.pack.zs', 'Pack/FoliageDropParam.pack.zs', REST)


@contextmanager
def portable_source(source, parent, mod=None):
    """Index inputs once; the native reader verifies NUP members on demand."""
    from ootrr_full.game.world_maps import effective_members
    source = Path(source)
    if source.is_dir():
        if (source / 'romfs/Pack/ZsDic.pack.zs').is_file():
            source /= 'romfs'
    with NupSource(source) as nup:
        members = effective_members(nup)
        selected = {path for path in members if path in _FILES or path.startswith(_PREFIXES)}
        if mod is not None:
            # Native challenge stages enumerate actor packs. Include full-mode
            # enemy clones as well as vanilla actors, without exposing writes
            # to the user's source directory or running another item fill.
            actor_packs = Path(mod) / 'Pack/Actor'
            if actor_packs.is_dir():
                for path in actor_packs.rglob('*.pack.zs'):
                    relative = path.relative_to(mod)
                    if relative.as_posix() not in members:
                        selected.add(relative.as_posix())
        yield source, tuple(members), sorted(selected)


class NupSource:
    def __init__(self, source):
        from ootrr_full.formats.inspect_nup import Nup
        self.nup = Nup(source)

    def __enter__(self):
        return self.nup

    def __exit__(self, *args):
        self.nup.stream.close()


def allocations(raw, rows, known_paths):
    """Grow shared modules once and preserve unrelated CRC allocations."""
    if not isinstance(rows, list) or len(rows) > 100_000:
        raise ValueError('Invalid native resource allocation ledger.')
    known = {path.removesuffix('.zs') for path in known_paths}
    if raw[:6] != b'RESTBL' or len(raw) < 22:
        raise ValueError('Invalid native resource allocation table.')
    version, block, count, names = struct.unpack_from('<IIII', raw, 6)
    if version != 1 or block != 160 or len(raw) != 22 + count * 8 + names * (block + 4):
        raise ValueError('Invalid native resource allocation table.')
    hashed = dict(struct.iter_unpack('<II', raw[22:22 + count * 8]))
    named = {}
    for index in range(names):
        position = 22 + count * 8 + index * (block + 4)
        named[raw[position:position + block].split(b'\0', 1)[0].decode()] = struct.unpack_from('<I', raw, position + block)[0]
    growth, added, seen = {}, {}, set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'path', 'old', 'new'}:
            raise ValueError('Invalid native resource allocation record.')
        path, old, new = row['path'], row['old'], row['new']
        if (not isinstance(path, str) or not path or '\\' in path or ':' in path
                or any(part in ('', '.', '..') for part in path.split('/')) or path in seen
                or (old is not None and (type(old) is not int or old < 0))
                or type(new) is not int or not 0 < new < 1 << 32):
            raise ValueError('Invalid native resource allocation record.')
        seen.add(path)
        target = path.removesuffix('.zs')
        current = named.get(target, hashed.get(zlib.crc32(target.encode())))
        if old is None:
            if target in known and current is not None:
                # A newly packed copy of an existing shared native module.
                growth[path] = max(0, new + 4096 - current)
            else:
                added[path] = (new + 4095) & ~4095
        elif new > old:
            if current is None:
                added[path] = (new + 4095) & ~4095
            else:
                growth[path] = new - old
    result, grown = grow_resources(raw, growth)
    if added:
        result, inserted = add_resources(result, added, known_paths=known_paths)
    else:
        inserted = []
    return result, grown + inserted


def prepare_portable(romfs, artifact, data, *, game_source=None):
    """Called inside the owned generation workspace before runtime binding."""
    options = data['full_patch']['options']
    changed = {name: options.get(name, default) for name, default in unrecorded().items()
               if options.get(name, default) != default}
    hearts = options.get('starting_hearts', 3)
    if not changed and hearts == 3:
        return {'version': 1, 'settings': {}, 'files': [], 'allocations': []}
    from .engine import run_engine
    from .mod_codec import Codec
    from .i18n import tr
    print(tr('Applying your gameplay options...'), flush=True)
    romfs, artifact = Path(romfs), Path(artifact)
    mod = artifact / 'romfs'
    codec = Codec((romfs / 'Pack/ZsDic.pack.zs').read_bytes())
    with portable_source(game_source or romfs, artifact.parent, mod) as (source, known, members):
        request = {'settings': native_values(dict(options, open_forest=data['full_patch']['open_forest'])),
                   'seed': data['token'], 'members': members}
        if source.is_file():
            request['source_file'] = source.name
        result = json.loads(run_engine('full-extras', request, source, mod))
        if not isinstance(result, dict) or set(result) != {'files', 'allocations'}:
            raise ValueError('Invalid native resource patch report.')
        path = mod / REST
        frame = path.read_bytes()
        after, report = allocations(codec.decode(frame), result['allocations'], known)
        path.write_bytes(codec.encode(after, frame))
    print(tr('Gameplay options applied.'), flush=True)
    return {'version': 1, 'settings': dict(changed, **({'starting_hearts': hearts} if hearts != 3 else {})),
            'files': result['files'], 'allocations': report}
