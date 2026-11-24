"""Build ``oot_remake.apworld`` from the local game.

The apworld holds the pure Python logic of the application (vendored), the
logic world data and a catalog of the remake's locations (identifiers, hashes
and positions of reward sources; no game asset). It is needed only by whoever
runs the Archipelago generation: put it in Archipelago's ``custom_worlds``.
"""
import json
from pathlib import Path
import zipfile

from ootrr_full.paths import resource

PACKAGE = 'oot_remake'
WORLD_VERSION = '0.1.0'
MINIMUM_AP_VERSION = '0.6.2'
# Modules needed by the preparation and the bridge: pure Python, no zstd/evfl.
VENDORED = ('__init__.py', 'paths.py',
            'logic/__init__.py', 'logic/rules.py', 'logic/world.py', 'logic/rando_options.py',
            'randomizer/__init__.py', 'randomizer/full_randomizer.py',
            'game/__init__.py', 'game/remake_world.py', 'game/combat.py', 'game/item_forms.py', 'game/extra_sources.py',
            'game/randomizer_categories.py',
            'patching/__init__.py', 'patching/soul_adapter.py', 'patching/key_adapter.py', 'patching/ap_item.py',
            'patching/ap_mailbox.py', 'patching/song_adapter.py', 'patching/child_castle_skip.py',
            'archipelago/__init__.py', 'archipelago/bridge.py')
# Becomes ``oot_remake/__init__.py``. Not a ``.py`` here: it imports Archipelago.
TEMPLATE = 'archipelago/ap_world.py.in'


def scan_game(nup_path, progress=None):
    """(game build, groups, enemies, extra) of a supported NUP, read-only."""
    from ootrr_full.formats.inspect_nup import Nup
    nup = Nup(nup_path)
    try:
        return _scan(nup, progress)
    finally:
        nup.stream.close()


def _scan(nup, progress):
    from ootrr_full.formats.inspect_resources import dictionaries
    from ootrr_full.game.extra_sources import scan_world
    from ootrr_full.game.world_maps import effective_members
    from ootrr_full.patching.randomize_kokiri import BUILD, check_supported_game
    check_supported_game(nup)
    _, groups, enemies, extra = scan_world(nup, dictionaries(nup), effective_members(nup), progress)
    return BUILD, groups, enemies, extra


def vendored_files():
    """(path inside the vendor folder, source file) of the application part."""
    files = [(f'ootrr_full/{name}', resource(name)) for name in VENDORED]
    world = resource('logic', 'world')
    for path in sorted(world.rglob('*')):
        if path.is_file():
            files.append(('ootrr_full/' + path.relative_to(resource()).as_posix(), path))
    missing = [str(source) for _, source in files if not source.is_file()]
    if missing:
        raise ValueError('Application files missing for the apworld: ' + ', '.join(missing[:3]))
    return files


def manifest():
    return {'game': 'OoT Remake', 'world_version': WORLD_VERSION, 'minimum_ap_version': MINIMUM_AP_VERSION,
            'authors': ['OoT Randomizer'], 'version': 8, 'compatible_version': 8}


def write_apworld(catalog, output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + '.tmp')
    with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.write(resource(TEMPLATE), f'{PACKAGE}/__init__.py')
        archive.writestr(f'{PACKAGE}/archipelago.json', json.dumps(manifest(), indent=1))
        archive.writestr(f'{PACKAGE}/catalog.json', json.dumps(catalog, ensure_ascii=False, separators=(',', ':')))
        for name, source in vendored_files():
            archive.write(source, f'{PACKAGE}/vendor/{name}')
    temporary.replace(output)
    return output


def build_apworld(nup_path, output, progress=None):
    """Scan the game, build the catalog and write the apworld. Returns its path."""
    from ootrr_full.archipelago.bridge import build_catalog
    from ootrr_full.logic.world import World
    report = progress or (lambda message: None)
    report('Reading the game…')
    build, groups, enemies, extra = scan_game(nup_path, report)
    catalog = build_catalog(World(), groups, enemies, extra, build, report)
    report(f'{len(catalog["locations"])} locations, {len(catalog["items"])} items.')
    return write_apworld(catalog, output)
