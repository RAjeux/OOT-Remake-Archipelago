"""Native external receipts and server-confirmed physical-check recovery.

The external client uses the same authored item presentations as the native
bridge, with per-record saved Bool acknowledgements instead of a Go cursor.
Local physical checks use their actual collection flag as Got. Replaying an
older save can therefore restore the missing reward once; a physical pickup
already completed in that save cannot be awarded again. Checks belonging to a
friend restore only their native collection/quest state, never an inventory item.
"""
import copy
import json
from pathlib import Path

from .mod_codec import Codec
from .medallions import REST

GAMEDATA = 'GameData/GameDataList.Product.110.byml.zs'
POUCH = 'Event/EventFlow/GetPouchContent.bfevfl.zs'
PRESENTER = 'Event/EventFlow/Dm_SY_GetInEvent.bfevfl.zs'
GROUND = 'Event/EventFlow/Dm_SY_Get.bfevfl.zs'
POUCH_INFO = 'RSDB/PouchActorInfo.Product.111.rstbl.byml.zs'
PREFIX = 'OOTRR_External_'


def required_resources():
    from ootrr_full.patching import ap_mailbox as mailbox
    return ('Pack/ZsDic.pack.zs', REST, GAMEDATA, POUCH, PRESENTER, GROUND, POUCH_INFO,
            mailbox.EVENT_SETTINGS, mailbox.ANALYZED, mailbox.MAIN_UPDATE)


def recovery_records(data, artifact, schema):
    """Bind recovery requests to the validated player's actual saved check flags."""
    from .full_mod import collection_records
    from .full_ap import load_catalog
    from ootrr_full.patching.ap_mailbox import record_key, PREFIX as MAIL_PREFIX, RECV
    names = load_catalog()['locations']
    roster = {names[gid]: {'local': row['own'], 'item': row['item'] if row['own'] else None}
              for gid, row in data['full_patch']['placements'].items()}
    checks = collection_records(data, artifact, roster, schema)
    result = []
    slot_name = data.get('slot') or str(data['player'])
    for row in checks:
        key = record_key(slot_name, row['name'])
        also_set = list(row['flags'][1:])
        if row.get('wake_talon'):
            from .trade_catalog import TALON_AWAKE
            also_set.append(TALON_AWAKE)
        record = {'key': key, 'item': row['item'] if row['local'] else '(checked location)',
                       'player': slot_name, 'location': row['name'],
                       'style': 'recovery' if row['local'] else 'check_only',
                       'event': MAIL_PREFIX + key, 'recv': RECV + key,
                       'got': row['flags'][0], 'also_set': list(dict.fromkeys(also_set)),
                       'counters': list(row.get('counters', ())),
                       'restore_location_id': row['id'], 'restore_only': not row['local']}
        if row.get('progressive_token'):
            record['progressive_token'] = copy.deepcopy(row['progressive_token'])
        if row.get('small_key_token'):
            record['small_key_token'] = copy.deepcopy(row['small_key_token'])
        result.append(record)
    return result


def bind_spent_trades(records, data):
    """Server/location identities of the one real check consuming each trade item."""
    if not data.get('adult_trade_shuffle'):
        return
    from .catalog import ITEM_DATA
    from .trade_catalog import TRADE_ITEMS, TRADE_CHECKS
    consumed = {row['required_actor']: (name, row) for name, row in TRADE_CHECKS.items() if row['required_actor']}
    for record in records:
        if record.get('restore_only') or record['item'] not in TRADE_ITEMS:
            continue
        point, row = consumed[ITEM_DATA[record['item']]['actor']]
        location_id = data['location_ids'].get(point)
        if location_id is None:
            raise ValueError('The shuffled trade item has no consuming Archipelago check.')
        record.update(consumed_by_location_id=location_id, consumed_by_flag=row['flag_name'],
                      spent_actor=ITEM_DATA[record['item']]['actor'],
                      spent='Archipelago.ExternalSpent.' + data['token'] + '.' + str(location_id))


def build_presentations(pouch_raw, presenter_raw, ground_raw, recipes, identifiers, native_info):
    """One native presentation per item, returning normally without a cursor ack."""
    from evfl.common import Argument
    from evfl.entry_point import EntryPoint
    from evfl.util import make_index
    from ootrr_full.patching.progressive import FlowEditor, link
    from .native_presentations import (append_recipe, append_tier_choice, copy_receipt_presenter,
                                       receipt_style, PRESENTER_NAME)
    from .receipt_events import _silent_grant
    from ootrr_full.patching.ammo_quantities import quantity_actor
    pouch, presenter = FlowEditor(pouch_raw, 'External native pouch receipts'), FlowEditor(
        presenter_raw, 'External native receipt animations')
    silent = PREFIX + 'SilentGrant'
    _silent_grant(pouch, None, entry_name=silent, prefix=PREFIX + 'SilentNative')
    entries = {}
    for name, recipe in sorted(recipes.items()):
        metadata = copy.deepcopy(recipe)
        stem = PREFIX + 'Item_' + str(identifiers[name])
        core_name = stem + '_Pouch'
        style = receipt_style(metadata, native_info)
        root = append_recipe(pouch, metadata, core_name, silent, None, pickup=style == 'pickup')
        if style != 'pickup':
            window = pouch.subflow(core_name + '_Window', '', 'DisplayGetByActorName',
                                   {'ActorName': Argument('ActorName')})
            link(window, root)
            root = window
        point = EntryPoint(core_name)
        point.main_event = make_index(root)
        pouch.chart.entry_points.append(point)
        shown = (copy_receipt_presenter(presenter, metadata, identifiers[name], core_name, style=style,
                                        ground_raw=ground_raw, prefix=stem + '_Native')
                 if style not in {'pickup', 'text'} else None)
        display = quantity_actor(name)

        def present(branch, actor):
            display_actor = display or actor
            if style in {'pickup', 'text'}:
                show = pouch.subflow(branch + '_Get', '', core_name, {'ActorName': display_actor})
                if style == 'pickup' and not native_info[metadata['actor']].get('IsNotOpenStockNumDisplay', False):
                    popup = pouch.action(branch + '_Pickup', 'UISystemActor',
                                          'EventTriggerRequestOpenPickUpWindow', {'ActorName': display_actor})
                    link(show, popup)
                return show
            return pouch.subflow(branch + '_Show', PRESENTER_NAME, shown,
                                 {'ActorName': display_actor, 'IsNpcEventStarter': False})

        # A missing bag returns from this subflow without a grant or UI. The
        # caller then commits the receipt/check, just as a consumed native refill.
        root = append_tier_choice(pouch, metadata, stem, present, no_ammo=None)
        point = EntryPoint(stem)
        point.main_event = make_index(root)
        pouch.chart.entry_points.append(point)
        entries[name] = stem
    return (pouch.write('External native pouch receipts')[0],
            presenter.write('External native receipt animations')[0], entries)


def bind_records(raw, records, item_entries):
    """Route existing/new mailbox entries through native receipt then saved flags."""
    from evfl.entry_point import EntryPoint
    from evfl.util import make_index
    from ootrr_full.patching.progressive import FlowEditor, link
    from ootrr_full.patching.ap_mailbox import DISPATCH
    editor = FlowEditor(raw, 'External transaction acknowledgements')
    points = {point.name: point for point in editor.chart.entry_points}
    tails = {}
    for record in records:
        stem = PREFIX + record['key']
        tail = editor.action(stem + '_Save', 'GameSystemActor', 'EventTriggerRequestAutoSave', None)
        if record.get('spent'):
            from .ap_skulls import _after_writes
            settled = _after_writes(editor, stem + '_SpentStockCommitted', tail)
            take = editor.action(stem + '_SpentStockTake', 'PouchSystemActor',
                                  'EventTriggerAddOrRemovePouchContent',
                                  {'Actor': record['spent_actor'], 'Num': -1, 'IsEquipDIrect': False,
                                   'IsSetMessageTargetActorName': False, 'IsGetEvent': False})
            link(take, settled)
            owned = editor.switch(stem + '_SpentStockOwned', 'PouchSystemActor', 'EventQueryIsExistInPouch',
                                   {'Actor': record['spent_actor'], 'Num': 1}, take, tail)
            local = editor.switch(stem + '_SpentStockLocal', 'GameDataActor', 'EventQueryIsGameDataBool',
                                   {'GameDataName': record['consumed_by_flag'], 'Index': -1}, owned, tail)
            tail = editor.switch(stem + '_SpentStockServer', 'GameDataActor', 'EventQueryIsGameDataBool',
                                  {'GameDataName': record['spent'], 'Index': -1}, owned, local)
        if 'restore_location_id' in record:
            from .full_extra_recovery import append_reconcile, append_progressive_reconcile
            physical = dict(record, id=record['restore_location_id'], name=record['location'])
            tail = append_reconcile(editor, physical, tail)
            if not record.get('restore_only'):
                tail = append_progressive_reconcile(editor, physical, tail)
            from .trade_catalog import TRADE_CHECKS
            if record['location'] in TRADE_CHECKS and TRADE_CHECKS[record['location']]['required_actor']:
                from .trade_state import append_reconcile as reconcile_trade_stock
                tail = reconcile_trade_stock(editor, stem + '_TradeStock', tail)
        tails[record['key']] = tail.name
        for index, counter in reversed(list(enumerate(record.get('counters', ())))):
            mark = editor.action(stem + '_Counter' + str(index), 'GameDataActor', 'EventTriggerSetGameDataInt',
                                  {'GameDataName': counter, 'Index': -1, 'Value': 1})
            link(mark, tail)
            tail = mark
        for index, flag in reversed(list(enumerate([record['got'], *record.get('also_set', ())]))):
            mark = editor.action(stem + '_Flag' + str(index), 'GameDataActor', 'EventTriggerSetGameDataBool',
                                  {'GameDataName': flag, 'Index': -1, 'Value': True})
            link(mark, tail)
            tail = mark
        calls = []
        if not record.get('restore_only'):
            if record.get('small_key_token'):
                from ootrr_full.patching.key_adapter import append_small_key_grant, key_actor_item, small_applied_flag
                token = record['small_key_token']
                if (not isinstance(token, dict) or key_actor_item(token.get('actor', '')) != record['item']
                        or token.get('applied') != small_applied_flag(token['actor'])):
                    raise ValueError('Invalid external dungeon small-key source token.')
                source_entry = stem + '_SmallKey'
                point = EntryPoint(source_entry)
                point.main_event = make_index(append_small_key_grant(editor, token['actor'], source_entry, None))
                editor.chart.entry_points.append(point)
                give = editor.subflow(stem + '_Give', '', source_entry, None)
            else:
                give = editor.subflow(stem + '_Give', 'GetPouchContent', item_entries[record['item']], None)
            link(give, tail)
            calls = [give]
            if record.get('spent'):
                local = editor.switch(stem + '_SpentLocal', 'GameDataActor', 'EventQueryIsGameDataBool',
                                       {'GameDataName': record['consumed_by_flag'], 'Index': -1}, tail, give)
                tail = editor.switch(stem + '_SpentServer', 'GameDataActor', 'EventQueryIsGameDataBool',
                                      {'GameDataName': record['spent'], 'Index': -1}, tail, local)
            else:
                tail = give
        point = points.get(record['event'])
        if point is None:
            point = EntryPoint(record['event'])
            editor.chart.entry_points.append(point)
            points[record['event']] = point
        point.main_event = make_index(tail)
        point._sub_flow_event_indices = [editor.chart.events.index(event) for event in calls]
    root, calls = None, []
    for record in reversed(records):
        stem = PREFIX + 'Dispatch_' + record['key']
        give = editor.subflow(stem + '_Give', '', record['event'], None)
        calls.append(give)
        held = editor.switch(stem + '_Got', 'GameDataActor', 'EventQueryIsGameDataBool',
                             {'GameDataName': record['got'], 'Index': -1}, None, give)
        clear = editor.action(stem + '_Clear', 'GameDataActor', 'EventTriggerSetGameDataBool',
                              {'GameDataName': record['recv'], 'Index': -1, 'Value': False})
        link(clear, held)
        root = editor.switch(stem + '_Recv', 'GameDataActor', 'EventQueryIsGameDataBool',
                             {'GameDataName': record['recv'], 'Index': -1}, clear, root)
    point = points.get(DISPATCH)
    if point is None:
        point = EntryPoint(DISPATCH)
        editor.chart.entry_points.append(point)
    point.main_event = make_index(root)
    point._sub_flow_event_indices = [editor.chart.events.index(event) for event in calls]
    result, checked = editor.write('External transaction acknowledgements')
    written = {point.name: point for point in checked.flowchart.entry_points}
    for record in records:
        event = written[record['event']].main_event.v
        if not record.get('restore_only'):
            if record.get('spent'):
                for name in ('spent', 'consumed_by_flag'):
                    if (event is None or type(event.data).__name__ != 'SwitchEvent'
                            or event.data.actor_query.v.v != 'EventQueryIsGameDataBool'
                            or dict(event.data.params.data) != {'GameDataName': record[name], 'Index': -1}
                            or event.data.cases[0].v.name != PREFIX + record['key'] + '_Flag0'):
                        raise ValueError('Spent trade receipt guard is invalid.')
                    event = event.data.cases[1].v
            expected_flow = '' if record.get('small_key_token') else 'GetPouchContent'
            expected_entry = (PREFIX + record['key'] + '_SmallKey' if record.get('small_key_token')
                              else item_entries[record['item']])
            if (type(event.data).__name__ != 'SubFlowEvent' or event.data.res_flowchart_name != expected_flow
                    or event.data.entry_point_name != expected_entry):
                raise ValueError('External receipt does not begin with its native effect.')
            event = event.data.nxt.v
        for flag in [record['got'], *record.get('also_set', ())]:
            if (event is None or type(event.data).__name__ != 'ActionEvent'
                    or event.data.actor_action.v.v != 'EventTriggerSetGameDataBool'
                    or dict(event.data.params.data) != {'GameDataName': flag, 'Index': -1, 'Value': True}):
                raise ValueError('External receipt acknowledgement is not after its native effect.')
            event = event.data.nxt.v
        for counter in record.get('counters', ()):
            if (event is None or type(event.data).__name__ != 'ActionEvent'
                    or event.data.actor_action.v.v != 'EventTriggerSetGameDataInt'
                    or dict(event.data.params.data) != {'GameDataName': counter, 'Index': -1, 'Value': 1}):
                raise ValueError('External receipt counter restoration is invalid.')
            event = event.data.nxt.v
        from ootrr_full.patching.event_info import reachable
        if event is None or event.name != tails[record['key']]:
            raise ValueError('External receipt reconciliation is not after its native acknowledgement.')
        if not any(type(node.data).__name__ == 'ActionEvent'
                   and node.data.actor_action.v.v == 'EventTriggerRequestAutoSave' for node in reachable(event)):
            raise ValueError('External receipt must save only after its acknowledgement/reconciliation.')
    return result


def prepare_external_recovery(romfs, artifact, data, *, game_source=None):
    """Compose only a staged external artifact; original resources remain read-only."""
    from ootrr_full.formats import byml_codec
    from ootrr_full.patching import ap_mailbox as mailbox
    from ootrr_full.patching.event_info import flow_path
    from ootrr_full.game.tracking_metadata import add_saved_flags
    from ootrr_full.game.resource_allocations import grow_resources
    from .full_mod import receipt_catalog
    romfs, artifact = Path(romfs), Path(artifact)
    mod = artifact / 'romfs'
    if (artifact / 'archipelago.dll').exists() or (mod / 'Archipelago/room-v1.txt').exists():
        raise ValueError('External receipt recovery cannot be installed on the native bridge.')
    manifest = json.loads((artifact / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('external_recovery'):
        raise ValueError('External recovery is already prepared.')
    codec = Codec((romfs / 'Pack/ZsDic.pack.zs').read_bytes())
    source, members = None, None
    game_source = Path(game_source or romfs)
    if game_source.is_file():
        from ootrr_full.formats.inspect_nup import Nup
        from ootrr_full.game.world_maps import effective_members
        source = Nup(game_source)
        members = effective_members(source)
    changed, templates = {}, {}
    def frame(path):
        if path not in templates:
            local = mod / path
            if local.is_file():
                templates[path] = local.read_bytes()
            elif (romfs / path).is_file():
                templates[path] = (romfs / path).read_bytes()
            elif source is not None and path in members:
                templates[path] = source.read(members[path])
            else:
                templates[path] = (game_source / path).read_bytes()
        return templates[path]
    def read(path):
        return changed[path] if path in changed else codec.decode(frame(path)) if path.endswith('.zs') else frame(path)
    try:
        schema = byml_codec.load(read(GAMEDATA))['root']
        restore = recovery_records(data, artifact, schema)
        from .full_events import prepare_gift_guards
        prepare_gift_guards(romfs, artifact, [{'flags': [row['got'], *row['also_set']]} for row in restore])
        original = (manifest.get('skips') or {}).get('ap_mailbox') or {}
        records = copy.deepcopy(list(original.get('items') or [])) + restore
        bind_spent_trades(records, data)
        if len({row['key'] for row in records}) != len(records):
            raise ValueError('External receipt keys collide.')
        recipes = receipt_catalog(data)
        native_info = {row['__RowId']: row for row in byml_codec.load(read(POUCH_INFO))['root']}
        changed[POUCH], presenter, entries = build_presentations(
            read(POUCH), read(PRESENTER), read(GROUND), recipes, data['item_ids'], native_info)
        changed[PRESENTER] = bind_records(presenter, records, entries)
        if not original.get('signal'):
            changed[mailbox.MAIN_UPDATE] = mailbox.patch_main_update(read(mailbox.MAIN_UPDATE), records, dispatch=True)
            changed[mailbox.EVENT_SETTINGS] = mailbox.add_event_rows(read(mailbox.EVENT_SETTINGS), records, dispatch=True)
        from .upgrade_readiness import add_transient_flag, patch_external_session_gate
        session_flag = 'Archipelago.ExternalSessionReady.' + data['token']
        changed[mailbox.MAIN_UPDATE] = patch_external_session_gate(read(mailbox.MAIN_UPDATE), session_flag)
        flags = {row['recv']: False for row in restore}
        if not original.get('signal'):
            flags[mailbox.SIGNAL] = False
        changed[GAMEDATA] = add_saved_flags(read(GAMEDATA), flags)
        for flag in sorted({session_flag, *(row['spent'] for row in records if row.get('spent'))}):
            changed[GAMEDATA] = add_transient_flag(changed[GAMEDATA], flag)
        analyzed = byml_codec.load(read(mailbox.ANALYZED))
        analyzed['root'] = [row for row in analyzed['root'] if row['__RowId'] != mailbox.DISPATCH]
        changed[mailbox.ANALYZED], analyzed_row = mailbox.add_analyzed_rows(
            byml_codec.dump(analyzed), records, lambda name: read(flow_path(name)), dispatch=True)
        growth = {path: max(0, len(raw) - len(codec.decode(frame(path)) if path.endswith('.zs') else frame(path)))
                  for path, raw in changed.items()}
        changed[REST], allocations = grow_resources(read(REST), growth)
        for path, raw in changed.items():
            target = mod / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(codec.encode(raw, frame(path)) if path.endswith('.zs') else raw)
        manifest.setdefault('skips', {})['ap_mailbox'] = {
            'items': records, 'row': analyzed_row, 'signal': mailbox.SIGNAL}
        metadata = {'version': 1, 'physical_checks': len(restore),
                    'own_rewards': sum(not row['restore_only'] for row in restore),
                    'native_item_presentations': len(entries), 'cursor': 'saved_collection_bool',
                    'gated_by': 'native_player_readiness', 'session_flag': session_flag,
                    'spent_trade_guards': sum(bool(row.get('spent')) for row in records),
                    'allocations': len(allocations)}
        manifest['external_recovery'] = metadata
        (artifact / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        return metadata
    finally:
        if source is not None:
            source.stream.close()
