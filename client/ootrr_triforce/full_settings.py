"""Apply full-network goal and economy options to a private generated mod.

The placement engine owns sources. This pass changes only the native goal
conditions and prices; it never runs a second fill over Archipelago's rewards.
"""
from pathlib import Path
import json

GAMEDATA = 'GameData/GameDataList.Product.110.byml.zs'
TRIAL_FLOW = 'Event/EventFlow/Defeat_Ganon.bfevfl.zs'
LACS_EXPRESSION = 'RandoFullLacs_Ready'
DOOR_EXPRESSION = 'RandoFullDoor_Ready'


def _expressions(raw, options):
    from ootrr_full.formats import byml_codec
    from ootrr_full.game.goal_settings import reward_program
    from ootrr_full.patching import story_fixes
    from ootrr_full.patching.soul_adapter import murmur3
    document = byml_codec.load(raw)
    data = document['root']['Data']
    entries = {int(entry['Hash']): entry for entry in data['BoolExp']}
    bools = {int(entry['Hash']) for entry in data['Bool']}
    integers = {int(entry['Hash']) for entry in data['Int']}
    programs = {}
    if not options.get('door_of_time_song', True) and not options['open_door_of_time']:
        stones = {'all': story_fixes.STONE_SETS['all'],
                  'vanilla': story_fixes.STONE_SETS['vanilla'], 'song': ()}[options['door_of_time_requirement']]
        if stones:
            program = [(0, story_fixes.STONE_FLAG_PREFIX + stone) for stone in stones]
            program += [(3,)] * (len(stones) - 1)
            program += [(0, story_fixes.DOOR_OPENED), (4,)]
        else:
            program = [(0, story_fixes.DOOR_OPENED), (0, story_fixes.DOOR_OPENED), (5,), (4,)]
        programs[DOOR_EXPRESSION] = program
    if options['bridge'] != 'vanilla':
        programs[story_fixes.BRIDGE_READY] = reward_program(
            options['bridge'], options, 'bridge', story_fixes.BRIDGE_PLAYED)
        if murmur3(story_fixes.BRIDGE_READY) not in entries:
            raise ValueError('The full bridge story adapter is missing.')
    if options['lacs_condition'] != 'vanilla':
        programs[LACS_EXPRESSION] = reward_program(
            options['lacs_condition'], options, 'lacs', story_fixes.LIGHT_ARROWS_PLAYED)
        if murmur3(LACS_EXPRESSION) in entries:
            raise ValueError('The Light Arrows threshold adapter is already present.')
    for name, program in programs.items():
        serialized = []
        for term in program:
            if term[0] == 16:
                if len(term) != 2 or type(term[1]) is not int or not -(1 << 31) <= term[1] < 1 << 31:
                    raise ValueError('A native goal literal must be a signed 32-bit integer.')
                serialized.append([byml_codec.U64(16), term[1]])
                continue
            if len(term) == 2:
                known = integers if term[0] in (18, 19) else bools
                if murmur3(term[1]) not in known:
                    raise ValueError('Unknown goal reward flag: ' + term[1])
                step = [term[0], murmur3(term[1])]
            else:
                step = list(term)
            serialized.append([byml_codec.U64(value) for value in step])
        hashed = murmur3(name)
        if hashed in entries:
            entries[hashed]['Values'] = serialized
        else:
            data['BoolExp'].append({'Hash': byml_codec.U32(hashed), 'ResetTypeValue': 0,
                                    'SaveFileIndex': -1, 'Values': serialized})
    return byml_codec.dump(document) if programs else raw, list(programs)


def _trial_defaults(required):
    from ootrr_full.game.goal_settings import TRIALS
    if required == 6:
        return {}
    values = {'InsideGanonCastle_Dungeon_Barrier_Count': required}
    if required:
        return values
    for name in TRIALS:
        for prefix in ('InsideGanonCastle_Dungeon_BarrierRemove_',
                       'HavePlayedEvent.InsideGanonCastle_Dungeon_BarrierRemove_'):
            values[prefix + name] = True
    values.update({name: True for name in (
        'InsideGanonCastle_Dungeon_SeeBarrierGuide', 'InsideGanonCastle_IsAllBarrierClear',
        'HavePlayedEvent.InsideGanonCastle_Dungeon_BarrierRemove_All',
        'HavePlayedEvent.Dm_InsideGanonCastle_0090')})
    return values


def _trials(raw):
    """Stop the any-N counter at zero; native negative-count case is not a sixth trial."""
    from ootrr_full.patching.progressive import FlowEditor
    editor = FlowEditor(raw, 'Defeat_Ganon')
    event = next((event for event in editor.chart.events if event.name == 'Event606'), None)
    if (event is None or type(event.data).__name__ != 'SwitchEvent'
            or event.data.actor_query.v.v != 'EventQueryIsGameDataInt'
            or event.data.params.data.get('GameDataName') != 'InsideGanonCastle_Dungeon_Barrier_Count'
            or event.data.params.data.get('Value') != 0
            or set(event.data.cases) != {0, 1}):
        raise ValueError('The native Ganon trial barrier check differs from the supported game.')
    del event.data.cases[0]
    result, check = editor.write('Ganon trial threshold')
    actual = next(event for event in check.flowchart.events if event.name == 'Event606')
    if set(actual.data.cases) != {1}:
        raise ValueError('The Ganon barrier threshold did not round-trip.')
    return result


def _lacs_module(raw):
    from ootrr_full.patching import story_fixes
    def check(nodes):
        if len(nodes) != 9:
            raise ValueError('The full Light Arrows story adapter is missing.')
        for index, medal in zip((5, 6), story_fixes.LIGHT_ARROWS_MEDALS):
            node = nodes[index]
            strings = node.get('Parameters', {}).get('Inputs', {}).get('String', [])
            if (node.get('Name') != 'HoldGameDataGetBoolSimple' or len(strings) != 1
                    or strings[0].get('Default Value') != medal):
                raise ValueError('The native Light Arrows reward reader differs.')
    def edit(nodes):
        for index in (5, 6):
            node = nodes[index]
            parameter = dict(node['Parameters']['Inputs']['String'][0])
            parameter.update(Name='GameDataNameBoolExp', **{'Default Value': LACS_EXPRESSION})
            node['Name'] = 'HoldGameDataGetBoolExpSimple'
            node['Parameters']['Inputs'] = {'String': [parameter]}
    return story_fixes._module_edit(raw, check, edit)


def _songless_door(raw):
    """Let the native sliding door use its stones rather than a played-song event."""
    from ootrr_full.patching import story_fixes
    def check(nodes):
        if len(nodes) != 19:
            raise ValueError('The full saved-flag Door of Time adapter is missing.')
        node = nodes[6]
        strings = node.get('Parameters', {}).get('Inputs', {}).get('String', [])
        if (node.get('Name') != 'HoldGameDataGetBoolSimple' or len(strings) != 1
                or strings[0].get('Default Value') != story_fixes.DOOR_OPENED
                or node['Parameters']['Outputs']['Bool'] != [{'Name': 'Bool', 'Is Output': True}]):
            raise ValueError('The native Door of Time saved-flag reader differs.')
    def edit(nodes):
        node = nodes[6]
        parameter = dict(node['Parameters']['Inputs']['String'][0])
        parameter.update(Name='GameDataNameBoolExp', **{'Default Value': DOOR_EXPRESSION})
        node['Name'] = 'HoldGameDataGetBoolExpSimple'
        node['Parameters']['Inputs'] = {'String': [parameter]}
    return story_fixes._module_edit(raw, check, edit)


def _open_fortress(options, read, stage):
    """Real rescued-carpenter defaults and native cell locks; card remains an AP item."""
    from ootrr_full.patching import game_defaults, world_openings, gerudo_fortress, quest_guard
    values = {'Step_SageOfSpirit': 'Step02', world_openings.CARPENTERS_HELPED: 4,
              world_openings.CARPENTERS_LEFT: 0,
              'HavePlayedEvent.Meet_FourCarpenter_ClearEvent': True,
              'GerudoFortress_IsAfterCompleteTalk_Npc_Gerudo_001': True,
              'GerudoFortress_GoToPrison_AfterClear': True,
              'GerudoFortress_IsAfterClearEvent_Npc_Hylia_012_Adult': True}
    for number in range(13, 17):
        for prefix in ('Saved', 'DestroyGerudoThief', 'IsAfterHelpCarpenter'):
            values[f'GerudoFortress_{prefix}_Npc_Hylia_{number:03}_Adult'] = True
    for number in range(1, 5):
        values[f'GerudoFortress_WarpPoint{number:02}_ClearEvent'] = True
    if not options['shuffle_gerudo_card']:
        values[gerudo_fortress.CARD] = True
    raw = game_defaults.set_new_game_defaults(read(GAMEDATA), values)
    stage(GAMEDATA, raw)
    steps = quest_guard.challenge_steps(read(quest_guard.CHALLENGES))
    path = gerudo_fortress.SPIRIT_FLOW
    flow, guards = quest_guard.guard_regressions(read(path), 'SageOfSpirit', steps, 'Step02',
                                                gamedata_raw=raw, prefix='RandoOpenFortress_')
    stage(path, flow)
    stage(gerudo_fortress.UNLOCK_FLOW, gerudo_fortress.skip_completed_unlocks(
        read(gerudo_fortress.UNLOCK_FLOW))[0])
    stage(gerudo_fortress.CELL_MODULE, gerudo_fortress.open_completed_cells(read(gerudo_fortress.CELL_MODULE)))
    if not options['open_gerudo_valley_bridge']:
        _, files, _ = world_openings.gerudo_valley_bridge(read, raw, b'', read)
        for path, member in files.items():
            stage(path, member)
    return {'defaults': values, 'guarded': guards['guarded'],
            'rescue_check_removed': True, 'membership_card_shuffled': options['shuffle_gerudo_card']}


def _flow_prices(raw, changes):
    from ootrr_full.patching.progressive import FlowEditor
    editor = FlowEditor(raw, 'Full-network native prices')
    events = {event.name: event for event in editor.chart.events}
    for event_name, parameters in changes.items():
        event = events.get(event_name)
        data = getattr(event, 'data', None)
        if getattr(data, 'params', None) is None:
            raise ValueError('Native price event is missing: ' + event_name)
        for key, (before, after) in parameters.items():
            if data.params.data.get(key) != before or type(before) is not int:
                raise ValueError('Native price differs: ' + event_name + '/' + key)
            data.params.data[key] = after
        editor.expected[event_name] = dict(data.params.data)
    return editor.write('Full-network native prices')[0]


def _fairy_display(raw, prices):
    from ootrr_full.formats import byml_codec
    from ootrr_full.patching.soul_adapter import murmur3
    from ootrr_full.game.economy_settings import FAIRIES
    document = byml_codec.load(raw)
    entries = {int(entry['Hash']): entry for entry in document['root']['Data']['Int']}
    for index, row in enumerate(FAIRIES, 1):
        entry = entries.get(murmur3('GreatFairy_Price' + str(index)))
        if (entry is None or entry.get('SaveFileIndex') != -1 or entry.get('ResetTypeValue') != 8
                or entry.get('DefaultValue') != row[2]):
            raise ValueError('The native Great Fairy price display differs.')
        entry['DefaultValue'] = prices[row[0]]
    return byml_codec.dump(document)


def _shop_pack(raw, price):
    from ootrr_full.formats import byml_codec
    from ootrr_full.formats.inspect_resources import sarc
    files = sarc(raw)
    count = 0
    for path, member in list(files.items()):
        if '/PriceParam/' not in path or not path.rsplit('/', 1)[-1].startswith('Shop_Rando_'):
            continue
        document = byml_codec.load(member)
        if document['root'].get('BuyingPrice') != 10:
            raise ValueError('Generated AP shop has an unexpected starting price.')
        document['root']['BuyingPrice'] = price
        files[path] = byml_codec.dump(document)
        count += 1
    if count != 1:
        raise ValueError('Generated AP shop must have exactly one native price resource.')
    result = byml_codec.build_sarc(files)
    if sarc(result) != files:
        raise ValueError('The shop price pack did not round-trip.')
    return result


def _economy(options, seed_key, artifact, read, stage, changed, message_paths=()):
    from ootrr_full.formats import byml_codec
    from ootrr_full.game.economy_settings import FAIRIES, sale_price, shop_price
    report = {}
    if options['shopsanity_prices'] != 'starting':
        spoiler = json.loads((artifact / 'spoiler.json').read_text(encoding='utf-8'))
        shops = [row for row in spoiler['placements'] if row.get('source') == 'shop']
        prices = {}
        for row in shops:
            actor = row['actor']
            price = shop_price(options, seed_key, row.get('reward_actor', actor))
            prices[actor] = price
            path = 'Pack/Actor/' + actor + '.pack.zs'
            stage(path, _shop_pack(read(path), price))
        if prices:
            path = 'RSDB/PouchActorInfo.Product.111.rstbl.byml.zs'
            document = byml_codec.load(read(path))
            applied = set()
            for row in document['root']:
                if row['__RowId'] in prices:
                    row['BuyingPrice'] = prices[row['__RowId']]
                    applied.add(row['__RowId'])
            if applied != set(prices):
                raise ValueError('The AP shop price table has missing shelf actors.')
            stage(path, byml_codec.dump(document))
        report['shops'] = prices
    if options['fairy_prices'] != 'vanilla':
        prices = {}
        for name, flow, native, check, pay in FAIRIES:
            price = sale_price(options, 'fairy', native)
            prices[name] = price
            path = 'Event/EventFlow/' + flow + '.bfevfl.zs'
            stage(path, _flow_prices(read(path), {check: {'Value': (native, price)},
                                                pay: {'Value': (-native, -price)}}))
        stage(GAMEDATA, _fairy_display(changed[GAMEDATA], prices))
        report['fairies'] = prices
    if options['merchant_prices'] != 'vanilla':
        price = sale_price(options, 'merchant', 200)
        if options['shuffle_medigoron']:
            path = 'Event/EventFlow/Npc_Goron_Medigoron_Adult.bfevfl.zs'
            stage(path, _flow_prices(read(path), {'Event11': {'Price': (200, price),
                                                            'MinusRupeeValue': (-200, -price)},
                                                'Event29': {'Value': (200, price)}}))
            report['medigoron'] = price
        if options['shuffle_bean_merchant']:
            from ootrr_full.patching.progressive import FlowEditor
            path = 'Event/EventFlow/Npc_Hylia_047_Child.bfevfl.zs'
            raw = read(path)
            editor = FlowEditor(raw, 'Native bean prices')
            changes = {}
            for event in editor.chart.events:
                params = getattr(event.data, 'params', None)
                if params is None or type(params.data.get('Price')) is not int:
                    continue
                original = params.data['Price']
                values = {'Price': (original, price)}
                if 'MinusRupeeValue' in params.data:
                    if params.data['MinusRupeeValue'] != -original:
                        raise ValueError('The native bean debit does not match its advertised price.')
                    values['MinusRupeeValue'] = (-original, -price)
                changes[event.name] = values
            if len(changes) != 20:
                raise ValueError('The native bean merchant price branches differ from the supported game.')
            stage(path, _flow_prices(raw, changes))
            report['beans'] = price
    if options.get('scrub_hint_text', False):
        from .full_scrub_hints import prepare
        report['scrub_item_names'] = prepare(artifact, options, seed_key, message_paths, read, stage)
    return report


def prepare_settings(romfs, artifact, manifest, *, game_source=None):
    """Mutate staged resources only, and return the exact applied goal settings."""
    from ootrr_full.logic import rando_options
    from ootrr_full.patching import game_defaults, story_fixes
    from ootrr_full.game.resource_allocations import grow_resources
    from ootrr_full.game.economy_settings import DEFAULTS as ECONOMY_DEFAULTS
    from .mod_codec import Codec
    from .medallions import REST
    romfs, artifact = Path(romfs), Path(artifact)
    mod = artifact / 'romfs'
    if romfs.resolve() == mod.resolve() or not (artifact / 'manifest.json').is_file():
        raise ValueError('Full settings need a separate generated Archipelago mod.')
    options = rando_options.validate(manifest['full_patch']['options'], supported_only=True)
    if (options['bridge'] == 'vanilla' and options['lacs_condition'] == 'vanilla' and options['trials'] == 6
            and options.get('shuffle_entrances', 'off') == 'off'
            and options.get('door_of_time_song', True) and options['gerudo_fortress'] != 'open'
            and all(options.get(name, value) == value for name, value in ECONOMY_DEFAULTS.items())):
        return {'expressions': [], 'trials': 6}
    codec = Codec((romfs / 'Pack/ZsDic.pack.zs').read_bytes())
    def frame(path):
        local = mod / path
        if local.is_file():
            return local.read_bytes()
        native = romfs / path
        if native.is_file():
            return native.read_bytes()
        if game_source is not None and Path(game_source).is_file():
            from ootrr_full.formats.inspect_nup import Nup
            source = Nup(game_source)
            try:
                return source.read(source.latest('romfs/' + path))
            finally:
                source.stream.close()
        raise ValueError('The native resource needed by this setting is unavailable: ' + path)
    changed, growth = {}, {}
    def read(path):
        if path in changed:
            return changed[path]
        raw = frame(path)
        return codec.decode(raw) if path.endswith('.zs') else raw
    def stage(path, raw):
        original = frame(path)
        before = codec.decode(original) if path.endswith('.zs') else original
        changed[path] = raw
        growth[path] = max(0, len(raw) - len(before))
    before = codec.decode(frame(GAMEDATA))
    after, expressions = _expressions(before, options)
    after = game_defaults.set_new_game_defaults(after, _trial_defaults(options['trials']))
    changed[GAMEDATA] = after
    growth[GAMEDATA] = max(0, len(after) - len(before))
    if 0 < options['trials'] < 6:
        raw = codec.decode(frame(TRIAL_FLOW))
        changed[TRIAL_FLOW] = _trials(raw)
        growth[TRIAL_FLOW] = max(0, len(changed[TRIAL_FLOW]) - len(raw))
    if options['lacs_condition'] != 'vanilla':
        path = story_fixes.LIGHT_ARROWS_MODULE
        raw = frame(path)
        changed[path] = _lacs_module(raw)
        growth[path] = max(0, len(changed[path]) - len(raw))
    if not options.get('door_of_time_song', True) and not options['open_door_of_time']:
        stage(story_fixes.DOOR_MODULE, _songless_door(read(story_fixes.DOOR_MODULE)))
    fortress = _open_fortress(options, read, stage) if options['gerudo_fortress'] == 'open' else None
    message_paths = sorted(path.relative_to(mod).as_posix() for path in (mod / 'Mals').glob('*.sarc.zs'))
    if options.get('scrub_hint_text', False) and not message_paths:
        message_paths = sorted(path.relative_to(romfs).as_posix() for path in (romfs / 'Mals').glob('*.sarc.zs'))
    economy = _economy(options, manifest['full_patch']['seed_key'], artifact, read, stage, changed,
                       message_paths)
    entrances = None
    if options.get('shuffle_entrances') == 'dungeons':
        from ootrr_full.game.dungeon_entrances import apply
        entrances = apply(manifest['full_patch']['dungeon_entrances'], read, stage)
    changed[REST], _ = grow_resources(codec.decode(frame(REST)), growth)
    for path, raw in changed.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(codec.encode(raw, frame(path)) if path.endswith('.zs') else raw)
    return {'expressions': expressions, 'trials': options['trials'], 'economy': economy,
            'dungeon_entrances': entrances, 'open_fortress': fortress,
            'door_requires_song': options.get('door_of_time_song', True)}
