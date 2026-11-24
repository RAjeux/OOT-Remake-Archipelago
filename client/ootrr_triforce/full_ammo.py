"""Preserve native ammunition capacity on every full-network gift path."""
from pathlib import Path

ARGUMENT = 'RandoFull.AmmoActor'
GET = 'Event/EventFlow/GetPouchContent.bfevfl.zs'
GAMEDATA = 'GameData/GameDataList.Product.110.byml.zs'


def guard_flow(raw, specs, *, dynamic=False):
    """Guard only real adds of AP bundle aliases; preserve their continuations.

    The shared native get passes ActorName as an argument. A transient String64,
    using the same native set/compare commands as DisplayShop, identifies the
    alias. It is never saved and never changes the item's presentation.
    """
    from evfl.common import Argument
    from evfl.util import make_index
    from ootrr_full.patching.progressive import FlowEditor, link
    from .native_presentations import AMMO_BAGS
    editor = FlowEditor(raw, 'Full-network ammunition capacity')
    originals = list(editor.chart.events)
    known = {spec['actor']: spec for spec in specs if spec['unit'] in AMMO_BAGS}
    guards = {}
    for event in originals:
        data = event.data
        if not hasattr(data, 'actor_action') or data.actor_action.v.v != 'EventTriggerAddOrRemovePouchContent':
            continue
        params = data.params.data if data.params else {}
        actor = params.get('Actor')
        value = params.get('Num')
        if not isinstance(value, int) or value <= 0:
            continue
        is_dynamic = isinstance(actor, Argument) and actor == 'ActorName' and dynamic
        if not is_dynamic and (isinstance(actor, Argument) or actor not in known):
            continue
        after = data.nxt.v
        choices = known.values() if is_dynamic else [known[actor]]
        head = event
        for index, spec in enumerate(sorted(choices, key=lambda row: row['actor'])):
            stem = 'FullAmmo_' + event.name + '_' + str(index)
            ready = after
            for bag_index, bag in enumerate(AMMO_BAGS[spec['unit']]):
                ready = editor.switch(stem + '_Bag' + str(bag_index), 'GameDataActor', 'EventQueryCheckIsGet',
                                      {'ActorName': bag}, event, ready)
            if is_dynamic:
                head = editor.switch(stem + '_Actor', 'GameDataActor', 'EventQueryIsGameDataString64',
                                     {'GameDataName': ARGUMENT, 'Index': -1, 'Value': spec['actor']}, ready, head)
            else:
                head = ready
        if is_dynamic:
            from .ap_skulls import _after_writes
            save = editor.action('FullAmmo_' + event.name + '_Argument', 'GameDataActor',
                                 'EventTriggerSetGameDataString64',
                                 {'GameDataName': ARGUMENT, 'Index': -1, 'Value': Argument('ActorName')})
            link(save, _after_writes(editor, 'FullAmmo_' + event.name + '_Ready', head))
            head = save
        guards[event] = head
    # Rewire original edges only: the newly created success branch deliberately
    # enters the original add. Rewiring it again would loop before the add.
    for event in originals:
        data = event.data
        if hasattr(data, 'nxt') and data.nxt.v in guards:
            data.nxt = make_index(guards[data.nxt.v])
        if hasattr(data, 'cases'):
            data.cases = {key: make_index(guards.get(value.v, value.v)) for key, value in data.cases.items()}
        if hasattr(data, 'forks'):
            data.forks = [make_index(guards.get(value.v, value.v)) for value in data.forks]
    for point in editor.chart.entry_points:
        if point.main_event.v in guards:
            point.main_event = make_index(guards[point.main_event.v])
    return (editor.write('Full-network ammunition capacity')[0] if guards else raw), len(guards)


def prepare_ammunition(romfs, artifact, data):
    from ootrr_full.patching.ammo_quantities import quantity_spec
    from ootrr_full.patching.soul_adapter import murmur3
    from ootrr_full.game.resource_allocations import grow_resources
    from .cursor_resource import append_transient_string64
    from .mod_codec import Codec
    from .medallions import REST
    from .full_mod import active_items
    romfs, artifact = Path(romfs), Path(artifact)
    mod = artifact / 'romfs'
    specs = [spec for item in active_items(data) if (spec := quantity_spec(item))]
    if not specs:
        return 0
    codec = Codec((romfs / 'Pack/ZsDic.pack.zs').read_bytes())
    def frame(path):
        local = mod / path
        return (local if local.is_file() else romfs / path).read_bytes()
    paths = {path.relative_to(mod).as_posix() for path in (mod / 'Event/EventFlow').glob('*.zs')}
    paths.add(GET)
    modified, growth, count = {}, {}, 0
    for path in sorted(paths):
        before = codec.decode(frame(path))
        after, changed = guard_flow(before, specs, dynamic=path == GET)
        if changed:
            modified[path] = after
            growth[path] = max(0, len(after) - len(before))
            count += changed
    before = codec.decode(frame(GAMEDATA))
    modified[GAMEDATA] = append_transient_string64(before, murmur3(ARGUMENT))
    growth[GAMEDATA] = len(modified[GAMEDATA]) - len(before)
    modified[REST], _ = grow_resources(codec.decode(frame(REST)), growth)
    for path, raw in modified.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(codec.encode(raw, frame(path)))
    return count
