"""Real per-cow AP handovers using the audited native cow resource classes."""
import json
from pathlib import Path

from .mod_codec import Codec
from .ap_skulls import REST, _after_writes

GAMEDATA = 'GameData/GameDataList.Product.110.byml.zs'
ANALYZED = 'RSDB/GameAnalyzedEventInfo.Product.111.rstbl.byml.zs'
EVENT_SETTINGS = 'RSDB/EventSetting.Product.111.rstbl.byml.zs'
# Complete native closure of Dm_SY_GetInEvent/GetInEvent_NotTurn_NotNpc for
# supported 1.1.1 files. Existing ActionGuide dependencies are retained, including
# those added by the full generator before these per-cow classes are cloned.
GET_DEPENDENCIES = frozenset(('ActionGuide', 'Dm_SY_Get', 'Dm_SY_GetInEvent',
                              'GetPouchContent', 'NaviEventCommon'))


def required_resources(classes=None):
    """Original resources to extract into an external NUP's private cache."""
    from ootrr_full.game.cows import clones
    rows = clones()
    known = {row['class'] for row in rows}
    if classes is not None and not set(classes) <= known:
        raise ValueError('Unknown physical cow class.')
    selected = known if classes is None else set(classes)
    resources = {
        'Pack/ZsDic.pack.zs', REST, GAMEDATA,
        'Pack/Actor/Animal_Cow_LinkHouse.pack.zs',
        'Component/AIScheduleParam/Animal_Cow_LinkHouse.game__component__AIScheduleParam.bgyml',
        'Event/EventFlow/Animal_Cow.bfevfl.zs',
        'Event/EventFlow/Animal_Cow_LinkHouse.bfevfl.zs',
        'RSDB/ActorInfo.Product.111.rstbl.byml.zs',
        'RSDB/GameActorInfo.Product.111.rstbl.byml.zs',
        'RSDB/Tag.Product.111.rstbl.byml.zs',
        'RSDB/EventSetting.Product.111.rstbl.byml.zs',
        'RSDB/GameAnalyzedEventInfo.Product.111.rstbl.byml.zs',
    }
    resources.update(spot['file'] for row in rows if row['class'] in selected for spot in row['spots'])
    return tuple(sorted(resources))


def patch_flow(raw, rows):
    """Replace only the first milk handover; leave later native refill flow intact."""
    from evfl.actor import Actor
    from evfl.common import ActorIdentifier
    from evfl.container import Container
    from evfl.util import make_index
    from ootrr_full.patching.event_patch import GAMEDATA_ACTOR_PARAMS
    from ootrr_full.patching.progressive import FlowEditor, link
    editor = FlowEditor(raw, 'Full-network first cow rewards')
    entries = {entry.name: entry for entry in editor.chart.entry_points}
    for name in ('GameSystemActor', 'EventSystemActor'):
        if not any(str(actor.identifier) == name for actor in editor.chart.actors):
            actor = Actor()
            actor.identifier, actor.concurrent_clips = ActorIdentifier(name), 1
            actor.params = Container()
            actor.params.data = dict(GAMEDATA_ACTOR_PARAMS)
            editor.chart.actors.append(actor)
    grouped = {}
    for row in rows:
        grouped.setdefault(row['cow_entry'], []).append(row)
    for entry_name, members in grouped.items():
        if entry_name not in entries:
            raise ValueError('The native cow handover is missing: ' + entry_name)
        point = entries[entry_name]
        original = point.main_event.v
        if original is None:
            raise ValueError('The native cow handover is empty.')
        heads = {}
        for row in members:
            stem = 'FullCow_' + row['native_flag'].split('.')[-1]
            save = editor.action(stem + '_Save', 'GameSystemActor', 'EventTriggerRequestAutoSave', None)
            barrier = _after_writes(editor, stem + '_Committed', save)
            mark = editor.action(stem + '_Mark', 'GameDataActor', 'EventTriggerSetGameDataBool',
                                 {'GameDataName': row['native_flag'], 'Index': -1, 'Value': True})
            link(mark, barrier)
            give = editor.subflow(stem + '_Reward', 'Dm_SY_GetInEvent', 'GetInEvent_NotTurn_NotNpc',
                                  {'ActorName': row['actor'], 'IsMessageShow': True})
            link(give, mark)
            heads[row['cow_age']] = editor.switch(stem + '_Once', 'GameDataActor', 'EventQueryIsGameDataBool',
                                                   {'GameDataName': row['native_flag'], 'Index': -1}, original, give)
        if len(members) == 2:
            if set(heads) != {'child', 'adult'}:
                raise ValueError('The shared Gerudo cow reward needs both age-specific sources.')
            # Native childhood state, independent of the actor's shared flow.
            head = editor.switch('FullCow_GerudoAge', 'GameDataActor', 'EventQueryIsGameDataBool',
                                 {'GameDataName': 'Sequence_IsChildhood', 'Index': -1}, heads['child'], heads['adult'])
        elif len(members) == 1:
            head = next(iter(heads.values()))
        else:
            raise ValueError('Two independent cow checks share one physical handover.')
        point.main_event = make_index(head)
    return editor.write('Full-network first cow rewards')[0]


def preload_rewards(raw, settings_raw, flow_names):
    """Retain native metadata and preload the handover's proven native closure."""
    from ootrr_full.formats import byml_codec
    settings = byml_codec.load(settings_raw)['root']
    owners = {row['__RowId'] for row in settings
              if Path(row.get('FlowchartFileName', '')).stem in flow_names}
    document = byml_codec.load(raw)
    for row in document['root']:
        if row.get('__RowId') in owners or set(row.get('SubFlowList', ())) & set(flow_names):
            row['SubFlowList'] = sorted(set(row.get('SubFlowList', ())) | GET_DEPENDENCIES, key=str.lower)
    return byml_codec.dump(document)


def prepare_cows(romfs, artifact, data):
    """Run after full generation, before native binding, into a private mod only."""
    if not data.get('full_patch', {}).get('options', {}).get('shuffle_cows'):
        return
    from ootrr_full.game.cows import entries, clones
    from ootrr_full.game.tracking_metadata import add_saved_flags
    from ootrr_full.game.resource_allocations import grow_resources
    from .engine import run_engine
    romfs, artifact = Path(romfs).resolve(), Path(artifact).resolve()
    mod = artifact / 'romfs'
    mod.mkdir(parents=True, exist_ok=True)
    sources = entries()
    placements = data['full_patch']['placements']
    if set(sources) - placements.keys():
        raise ValueError('Every enabled cow must have exactly one Archipelago reward.')
    spoiler = json.loads((artifact / 'spoiler.json').read_text(encoding='utf-8'))
    actors = {row['id']: row['actor'] for row in spoiler['placements'] if row.get('source') == 'native_cow'}
    if set(actors) != set(sources):
        raise ValueError('The generated cow rewards do not match their physical sources.')
    run_engine('cow-classes', {'classes': [row['class'] for row in clones()]}, romfs, mod)
    codec = Codec((romfs / 'Pack/ZsDic.pack.zs').read_bytes())
    def read(path):
        target = mod / path
        return (target if target.is_file() else romfs / path).read_bytes()
    flows = {}
    for gid, row in sources.items():
        flows.setdefault('Event/EventFlow/' + row['event'] + '.bfevfl.zs', []).append(dict(row, actor=actors[gid]))
    pending, growth = {}, {}
    for path, rows in flows.items():
        frame = read(path)
        before = codec.decode(frame)
        after = patch_flow(before, rows)
        pending[path], growth[path] = codec.encode(after, frame), max(0, len(after) - len(before))
    frame = read(ANALYZED)
    before = codec.decode(frame)
    after = preload_rewards(before, codec.decode(read(EVENT_SETTINGS)),
                            {row['event'] for row in sources.values()})
    pending[ANALYZED], growth[ANALYZED] = codec.encode(after, frame), max(0, len(after) - len(before))
    frame = read(GAMEDATA)
    before = codec.decode(frame)
    after = add_saved_flags(before, {row['native_flag']: False for row in sources.values()})
    pending[GAMEDATA], growth[GAMEDATA] = codec.encode(after, frame), len(after) - len(before)
    frame = read(REST)
    table, _ = grow_resources(codec.decode(frame), growth)
    pending[REST] = codec.encode(table, frame)
    for path, frame in pending.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(frame)
