"""Replay the checked Rust reward-flow edits for full-network source families.

Derived from moteur/ootrr-ap/data/flow_extra.json, GPL-3.0-or-later.
Only enabled physical checks are changed. Purchases keep their native payment
and completion branches; cancelling a dialogue never counts as collection.
"""
import copy
from importlib import resources
import json

from ootrr_full.patching.progressive import FlowEditor


def start_values(options):
    if not options.get('plant_beans'):
        return {}
    values = json.loads(resources.files('ootrr_full').joinpath('game/bean_start_values.json').read_text(encoding='utf-8'))
    if options.get('shuffle_bean_merchant'):
        values['Get_MagicBeans'] = 0  # all ten AP purchases remain available
    return values


def _operations(plan):
    data = json.loads(resources.files('ootrr_full').joinpath('game/native_extras_ops.json').read_text(encoding='utf-8'))
    specs = {row['name']: row['ops'] for row in data['locations']}
    result, seen, beans = {}, set(), []
    for placement in plan['placements']:
        entry = plan['matches'][placement['id']]
        if entry.get('source') != 'native_extra':
            continue
        name = entry.get('extra_name')
        if name is None:
            continue
        if 'bean_index' in entry:
            beans.append({'index': entry['bean_index'], 'actor': placement['after'], 'flag': entry['native_flag']})
            continue
        operations = copy.deepcopy(specs[name])
        # The free bottle's ordinary handover can use parameter substitution.
        # Other sources need the structural operations listed in the table.
        if name == 'Market Potion Shop Free Bottle':
            operations.append({'kind': 'set', 'file': 'Npc_Hylia_020_Shop_Child.bfevfl',
                               'index': 162, 'event': 'Event171', 'param': 'ActorName',
                               'old': 'Item_Bottle', 'new': '$item'})
        for operation in operations:
            operation = _bind(operation, placement['after'])
            key = json.dumps(operation, sort_keys=True)
            if key not in seen:
                seen.add(key)
                path = 'Event/EventFlow/' + operation['file'] + '.zs'
                result.setdefault(path, []).append(operation)
    if beans:
        if sorted(row['index'] for row in beans) != list(range(10)):
            raise ValueError('Every finite bean purchase must have its own Archipelago reward.')
        path = 'Event/EventFlow/SimpleShop.bfevfl.zs'
        result.setdefault(path, []).append({'kind': 'bean_dispatch', 'event': 'Event182', 'index': 63,
                                            'purchases': sorted(beans, key=lambda row: row['index'])})
        result.setdefault('Event/EventFlow/Npc_Hylia_047_Child.bfevfl.zs', []).append({'kind': 'bean_shop_call'})
    return result


def _bind(value, actor):
    if isinstance(value, str):
        return actor if value == '$item' else value
    if isinstance(value, list):
        return [_bind(item, actor) for item in value]
    if isinstance(value, dict):
        return {key: _bind(item, actor) for key, item in value.items()}
    return value


def _params(values):
    from evfl.common import ActorIdentifier, Argument
    result = {}
    for key, value in values:
        if isinstance(value, str) and value.startswith('arg:'):
            value = Argument(value[4:])
        elif isinstance(value, str) and value.startswith('actor:'):
            value = ActorIdentifier(value[6:])
        result[key] = value
    return result


def _clone_bean_shop(editor):
    """Keep native payment/cancel paths while avoiding an unrelated bean-cap check.

    AP rewards may be equipment or another player's item even when Link already
    owns ten beans. Only the bean NPC calls this cloned shop entry; ordinary
    purchases keep their original native capacity checks.
    """
    from evfl.entry_point import EntryPoint
    from evfl.event import Event
    from evfl.util import make_index
    source = next(point for point in editor.chart.entry_points if point.name == 'SimpleShopRoot_3Choices')
    originals, pending = {}, [source.main_event.v]
    while pending:
        event = pending.pop()
        if event is None or event.name in originals:
            continue
        originals[event.name] = event
        data = event.data
        if hasattr(data, 'nxt'):
            pending.append(data.nxt.v)
        pending.extend(value.v for value in getattr(data, 'cases', {}).values())
        pending.extend(value.v for value in getattr(data, 'forks', []))
        if hasattr(data, 'join'):
            pending.append(data.join.v)
    copies = {}
    for name, original in originals.items():
        event = Event()
        event.name, event.data = 'FullBeanShop_' + name, copy.copy(original.data)
        if hasattr(event.data, 'params') and event.data.params is not None:
            event.data.params = copy.deepcopy(event.data.params)
        editor.chart.events.append(event)
        params = getattr(event.data, 'params', None)
        editor.expected[event.name] = dict(params.data) if params is not None else None
        copies[name] = event
    def target(index):
        return make_index(copies[index.v.name]) if index.v is not None else index
    for name, event in copies.items():
        original, data = originals[name].data, event.data
        if hasattr(original, 'nxt'):
            data.nxt = target(original.nxt)
        if hasattr(original, 'cases'):
            data.cases = {key: target(value) for key, value in original.cases.items()}
        if hasattr(original, 'forks'):
            data.forks = [target(value) for value in original.forks]
        if hasattr(original, 'join'):
            data.join = target(original.join)
    capacity = copies.get('Event126')
    if (capacity is None or capacity.data.actor_query.v.v != 'EventQueryCanAddToPorch'
            or set(capacity.data.cases) != {0, 2}):
        raise ValueError('Native bean shop capacity branch changed.')
    capacity.data.cases[2] = capacity.data.cases[0]
    point = EntryPoint('FullBeanShopRoot_3Choices')
    point.main_event = make_index(copies[source.main_event.v.name])
    point.variable_defs = copy.deepcopy(source.variable_defs)
    editor.chart.entry_points.append(point)


def patch_flow(raw, operations):
    from evfl.common import ActorIdentifier
    from evfl.container import Container
    from evfl.event import SubFlowEvent, SwitchEvent
    from evfl.util import make_index, make_rindex
    editor = FlowEditor(raw, 'Full-network native reward adapters')
    original = list(editor.chart.events)
    events = {event.name: event for event in original}

    def event_of(operation):
        event = events.get(operation['event'])
        if event is None or original[operation['index']] is not event:
            raise ValueError('Native reward event layout changed: ' + operation['event'])
        return event

    for operation in operations:
        kind = operation['kind']
        if kind == 'bean_shop_call':
            count = 0
            for event in original:
                data = event.data
                if (isinstance(data, SubFlowEvent) and data.res_flowchart_name == 'SimpleShop'
                        and data.entry_point_name == 'SimpleShopRoot_3Choices'):
                    data.entry_point_name = 'FullBeanShopRoot_3Choices'
                    count += 1
            if count != 8:
                raise ValueError('The native bean merchant sale layout changed.')
            continue
        if kind == 'bean_dispatch':
            from evfl.entry_point import EntryPoint
            _clone_bean_shop(editor)
            original_event = event_of(operation)
            original_data = original_event.data
            if (not isinstance(original_data, SubFlowEvent) or original_data.params is None
                    or original_data.params.data.get('ReveiveItem') != 'Item_MagicBean'):
                raise ValueError('Native bean purchase handover changed.')
            branches = {}
            for purchase in operation['purchases']:
                suffix = str(purchase['index'] + 1)
                params = dict(original_data.params.data)
                params['ReveiveItem'] = purchase['actor']
                grant = editor.subflow('FullBeanPurchase_' + suffix, original_data.res_flowchart_name,
                                       original_data.entry_point_name, params)
                committed = editor.action('FullBeanCommitted_' + suffix, 'GameDataActor',
                                          'EventTriggerSetGameDataBool',
                                          {'GameDataName': purchase['flag'], 'Index': -1, 'Value': True})
                grant.data.nxt = make_index(committed)
                once = editor.switch('FullBeanOnce_' + suffix, 'GameDataActor', 'EventQueryIsGameDataBool',
                                     {'GameDataName': purchase['flag'], 'Index': -1}, None, grant)
                branches[purchase['index']] = make_index(once)
            owner = editor.actor('GameDataActor')
            selector = SwitchEvent()
            selector.actor = make_rindex(owner)
            selector.actor_query = make_rindex(editor._holder(owner.queries, 'EventQueryGameDataIntBranch'))
            selector.cases = branches
            selected = editor._event('FullBeanSelectPurchase', selector, {'GameDataName': 'Get_MagicBeans'})
            point = EntryPoint('FullBeanAward')
            point.main_event = make_index(selected)
            editor.chart.entry_points.append(point)
            call = SubFlowEvent()
            call.res_flowchart_name, call.entry_point_name = '', point.name
            call.nxt = original_data.nxt
            original_event.data = call
            editor.expected[original_event.name] = None
            continue
        if kind == 'rename_actor':
            before, after = operation['old'], operation['new']
            targets = [actor for actor in editor.chart.actors if str(actor.identifier) == before]
            if not targets:
                raise ValueError('Native reward model actor is missing: ' + before)
            for actor in targets:
                actor.identifier = ActorIdentifier(after)
            for event in editor.chart.events:
                params = getattr(event.data, 'params', None)
                if params:
                    for name, value in list(params.data.items()):
                        if isinstance(value, ActorIdentifier) and str(value) == before:
                            params.data[name] = ActorIdentifier(after)
                    editor.expected[event.name] = dict(params.data)
            continue
        event = event_of(operation)
        data = event.data
        if kind == 'set':
            if data.params is None or data.params.data.get(operation['param']) != operation['old']:
                raise ValueError('Native reward parameter changed: ' + event.name)
            data.params.data[operation['param']] = operation['new']
            editor.expected[event.name] = dict(data.params.data)
        elif kind == 'next':
            if not hasattr(data, 'nxt') or data.nxt.v is not original[operation['old']]:
                raise ValueError('Native reward continuation changed: ' + event.name)
            data.nxt = make_index(original[operation['new']])
        elif kind == 'retarget':
            case = getattr(data, 'cases', {}).get(operation['case'])
            if case is None or case.v is not original[operation['old']]:
                raise ValueError('Native reward switch changed: ' + event.name)
            data.cases[operation['case']] = make_index(original[operation['new']])
        elif kind == 'swap_sub':
            if not isinstance(data, SubFlowEvent) or data.res_flowchart_name + ':' + data.entry_point_name != operation['from']:
                raise ValueError('Native reward handover changed: ' + event.name)
            flow, entry = operation['to'].split(':', 1)
            data.res_flowchart_name, data.entry_point_name = flow, entry
            data.params = Container()
            data.params.data = _params(operation.get('params', ()))
            editor.expected[event.name] = dict(data.params.data)
        elif kind == 'query':
            if not isinstance(data, SwitchEvent) or str(data.actor.v.identifier) + '.' + data.actor_query.v.v != operation['from']:
                raise ValueError('Native reward ownership query changed: ' + event.name)
            actor, query = operation['to'].split('.', 1)
            owner = editor.actor(actor)
            data.actor = make_rindex(owner)
            data.actor_query = make_rindex(editor._holder(owner.queries, query))
            values = _params(operation.get('params', ()))
            data.params = Container() if values else None
            if data.params is not None:
                data.params.data = values
            editor.expected[event.name] = values or None
        elif kind == 'insert_set':
            if not hasattr(data, 'nxt'):
                raise ValueError('Native reward completion has no continuation: ' + event.name)
            inserted = editor.action('FullNativeCompletion_' + event.name, 'GameDataActor',
                                     'EventTriggerSetGameDataBool',
                                     {'GameDataName': operation['flag'], 'Index': -1, 'Value': True})
            inserted.data.nxt = data.nxt
            data.nxt = make_index(inserted)
        else:
            raise ValueError('Unsupported native reward edit: ' + kind)
    return editor.write('Full-network native reward adapters')[0]


def apply(plan, current, read):
    """Mutate the generator's uncompressed flow map before tracking/dependency analysis."""
    operations = _operations(plan)
    for path, edits in operations.items():
        current[path] = patch_flow(current[path] if path in current else read(path), edits)
    flags = {entry['native_flag']: False for entry in plan['matches'].values() if 'bean_index' in entry}
    if flags:
        from ootrr_full.game.tracking_metadata import add_saved_flags, GAMEDATA
        current[GAMEDATA] = add_saved_flags(current[GAMEDATA] if GAMEDATA in current else read(GAMEDATA), flags)
    return {path: len(edits) for path, edits in operations.items()}
