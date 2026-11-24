"""External DeathLink through native Player AI, never through saved health.

Only transient mailbox flags cross the process boundary. QueryActorLife publishes
the owning Player's live life and a fresh-tick handshake. A received death uses
the game's own OneShotLifeSetOwnLife action to subtract that exact live life.
Its native action, rod, minigame, pause, load and event queries are checked again
on the game thread. The unsaved arm/request flags are cleared by MainUpdate
during loading, so neither old saves nor a stopped client can replay a death.
"""
import copy
import math
from pathlib import Path
import threading
import time

from . import upgrade_readiness as ready

PREFIX = 'Archipelago.ExternalDeathLink.'
FIELDS = ('heartbeat', 'dead', 'armed', 'request', 'fired')


def metadata(token, *, enabled=True):
    ready.readiness_name(token)  # canonical room identity
    if type(enabled) is not bool:
        raise ValueError('The external DeathLink setting must be a boolean.')
    return dict(version=1, enabled=enabled,
                flags={key: PREFIX + token + '.' + key for key in FIELDS})


def validate_metadata(value, token):
    if not isinstance(value, dict) or type(value.get('enabled')) is not bool or value != metadata(token, enabled=value['enabled']):
        raise ValueError('The external DeathLink metadata is invalid; prepare this room again.')
    return value


def native_templates(global_files):
    """Reject missing/changed native APIs instead of guessing action arguments."""
    import ainb
    document = ainb.AINB.from_binary(global_files['AI/Player.event.root.ainb']).as_dict()
    life = next((node for node in document['Nodes'] if node['Name'] == 'QueryActorLife'
                 and any(p['Name'] == 'Now' and p.get('Is Output') is True
                         for p in node['Parameters']['Outputs'].get('Int', ()))), None)
    action = next((node for node in document['Nodes'] if node['Name'] == 'OneShotLifeSetOwnLife'
                   and [p.get('Default Value') for p in node['Parameters']['Inputs'].get('Int', ())] == [3, 0]), None)
    if (life is None or action is None or life['Parameters']['Inputs']
            or [p['Name'] for p in life['Parameters']['Outputs']['Int']] != ['Max', 'Now']
            or [p['Name'] for p in action['Parameters']['Inputs']['Int']] != ['SetType', 'SetValue']):
        raise ValueError('The supported native live-life query/action was not found.')
    result = {'life': copy.deepcopy(life), 'subtract': copy.deepcopy(action)}
    for key, name in (('compare', 'SelectorMathCompareInt'), ('event', 'QueryIsPlayingMainEvent'),
                      ('idle', 'ExecuteGenericSetResultSuccess')):
        result[key] = ready._template(global_files, name)
    if result['event']['Parameters']['Inputs'] or not any(
            p['Name'] == 'IsPlayingMainEvent' and p.get('Is Output')
            for p in result['event']['Parameters']['Outputs']['Bool']):
        raise ValueError('The supported native event safety query was not found.')
    return result


def _simultaneous(index, flag, children, root=False):
    node = ready._node('Element_Simultaneous', index, flag,
        properties={'Int': [{'Name': name, 'Default Value': 0, 'Flags': []}
                            for name in ('EndPolicy', 'ResultPolicy')]})
    node['Flags'] = ['Is Root Node'] if root else []
    node['Plugs'] = {'Child': [{'Node Index': child, 'Name': ''} for child in children]}
    return node


def patch_player_brain(raw, token, templates, *, seed_marker):
    """Extend only the exact readiness graph authored by our existing adapter."""
    import ainb
    document = ainb.AINB.from_binary(raw).as_dict()
    flag, names = ready.readiness_name(token), metadata(token)['flags']
    nodes = document['Nodes']
    expected_names = ('', 'QueryBSAGetActionVerb', '', 'QueryNaviIsWaitPlayerStateDrawnFishingRod',
                      '', 'QueryPlayerIsEquipMiniGameItem', '', 'QueryGetNonStructGameDataBool',
                      '', 'QueryGetNonStructGameDataBool', 'OneShotSetNonStructGameDataBool',
                      'OneShotSetNonStructGameDataBool')
    supported = (len(nodes) == 12 and tuple(n['Name'] for n in nodes) == expected_names
                 and nodes[0]['Node Type'] == 'Element_S32Selector'
                 and nodes[0]['Plugs'].get('Child') == [
                     *({'Node Index': 2, 'Name': '', 'Condition': verb} for verb in sorted(ready.SAFE_VERBS)),
                     {'Node Index': 11, 'Name': '', 'Is Default': True}])
    if supported:
        for selector, query in ((2, 3), (4, 5), (6, 7), (8, 9)):
            node = nodes[selector]
            supported &= (node['Node Type'] == 'Element_BoolSelector' and node['Queries'] == [query]
                and node['Parameters']['Inputs']['Bool'][0]['Node Index'] == query
                and node['Plugs']['Child'] == [{'Node Index': 11, 'Name': 'True'},
                                             {'Node Index': selector + 2, 'Name': 'False'}])
        supported &= all(nodes[index]['Parameters']['Inputs']['String'][0]['Default Value'] == name
                         for index, name in ((7, ready.PAUSE), (9, ready.LOADING), (10, flag), (11, flag)))
        supported &= (nodes[1]['Parameters']['Inputs']['Int'][0]['Default Value'] == 0
                      and nodes[3]['Parameters']['Inputs'] == nodes[5]['Parameters']['Inputs'] == {}
                      and nodes[10]['Parameters']['Inputs']['Bool'][0]['Default Value'] is True
                      and nodes[11]['Parameters']['Inputs']['Bool'][0]['Default Value'] is False)
    if not supported:
        raise ValueError('External DeathLink needs the supported native readiness graph.')
    setters, query_template = copy.deepcopy(nodes[10]), copy.deepcopy(nodes[7])
    # Keep the original receipt readiness publisher unchanged. The independent
    # kill path clones its current native action checks, not its previous Bool.
    nodes[0]['Flags'] = []
    guard = copy.deepcopy(nodes)
    for node in guard:
        node['Node Index'] += 12
        node['GUID'] = ready._guid(names['request'], node['Node Index'])
        node['Queries'] = [index + 12 for index in node['Queries']]
        for group in node['Parameters'].values():
            for parameters in group.values():
                for parameter in parameters:
                    if parameter.get('Node Index', -1) >= 0:
                        parameter['Node Index'] += 12
        for plugs in node['Plugs'].values():
            for plug in plugs:
                if plug.get('Node Index', -1) >= 0:
                    plug['Node Index'] += 12
    nodes.extend(guard)

    def append(node):
        index = len(nodes)
        node = copy.deepcopy(node)
        node.update({'Node Index': index, 'GUID': ready._guid(names['request'], index),
                     'Queries': [], 'Plugs': {}, 'Flags': []})
        nodes.append(node)
        return index

    def setter(name, value):
        index = append(setters)
        nodes[index]['Parameters']['Inputs']['String'][0] = ready._default('GameDataFullName', name)
        nodes[index]['Parameters']['Inputs']['Bool'][0] = ready._default('Value', value)
        return index

    def bool_gate(name, true, false, event=False):
        query = append(templates['event'] if event else query_template)
        nodes[query]['Flags'] = ['Is Query']
        if not event:
            nodes[query]['Parameters']['Inputs'] = {
                'Int': [ready._default('GameDataIndex', -1)], 'Bool': [ready._default('IsDirect', True)],
                'String': [ready._default('GameDataFullName', name)]}
        branch = len(nodes)
        node = ready._node('Element_BoolSelector', branch, names['request'],
            inputs={'Bool': [ready._from_query('Input', query)]}, queries=(query,))
        node['Plugs'] = {'Generic': [{'Node Index': query, 'Name': 'Input', 'Unknown 1': 0, 'Unknown 2': 0}],
                         'Child': [{'Node Index': true, 'Name': 'True'}, {'Node Index': false, 'Name': 'False'}]}
        nodes.append(node)
        return branch

    idle = append(templates['idle'])
    heartbeat, dead, alive = setter(names['heartbeat'], True), setter(names['dead'], True), setter(names['dead'], False)
    not_ready = setter(flag, False)
    dead_branch = len(nodes)
    nodes.append(_simultaneous(dead_branch, names['request'], (dead, not_ready)))
    life = append(templates['life'])
    nodes[life]['Flags'] = ['Is Query']
    subtract = append(templates['subtract'])
    nodes[subtract]['Queries'] = [life]
    nodes[subtract]['Parameters']['Inputs']['Int'] = [ready._default('SetType', 3),
        {'Name': 'SetValue', 'Default Value': 0, 'Node Index': life, 'Output Index': 1, 'Flags': []}]
    nodes[subtract]['Plugs'] = {'Int': [{'Node Index': life, 'Name': 'SetValue'}]}
    # A fired flag is the native acknowledgement and prevents repeating the
    # subtraction while the game's property/life update completes.
    fired = setter(names['fired'], True)
    execute = len(nodes)
    sequence = ready._node('Element_Sequential', execute, names['request'],
        properties={'Int': [{'Name': name, 'Default Value': 0, 'Flags': []}
                            for name in ('BusyPolicy', 'NumLoop', 'PlayPolicy', 'ResultPolicy')],
                    'Bool': [{'Name': name, 'Default Value': value, 'Flags': []}
                             for name, value in (('IsDelayJudge', False), ('IsLoop', False), ('IsUpdateNextInFrame', True))]})
    sequence['Plugs'] = {'Child': [{'Node Index': index, 'Name': ''} for index in (fired, subtract)]}
    nodes.append(sequence)
    kill = bool_gate(None, idle, execute, event=True)
    kill = bool_gate(names['fired'], idle, kill)
    kill = bool_gate(names['request'], kill, idle)
    kill = bool_gate(names['armed'], kill, idle)
    # A just-signalled receipt may not have reached EventMgr yet. Let the
    # already queued native item event finish before applying a linked death.
    kill = bool_gate('RandoAP.Pending', idle, kill)
    if not isinstance(seed_marker, str) or not seed_marker.startswith('RandoSeed.'):
        raise ValueError('The external DeathLink seed marker is missing.')
    kill = bool_gate(seed_marker, kill, idle)
    # The cloned safe true/false setters become the guarded death branch/idle.
    for index, target in ((22, kill), (23, idle)):
        nodes[index] = _simultaneous(index, names['request'], [target])
    alive_branch = len(nodes)
    nodes.append(_simultaneous(alive_branch, names['request'], (alive, 12)))
    compare = append(templates['compare'])
    nodes[compare]['Queries'] = [life]
    nodes[compare]['Parameters']['Inputs'] = {'Int': [ready._from_query('ValueA', life, 'Int'),
                                                           ready._default('ValueB', 0)]}
    nodes[compare]['Parameters']['Inputs']['Int'][0]['Output Index'] = 1
    nodes[compare]['Plugs'] = {'Int': [{'Node Index': life, 'Name': 'ValueA'}],
        'Child': [{'Node Index': alive_branch, 'Name': 'Bigger'}, {'Node Index': dead_branch, 'Name': 'Equal'},
                  {'Node Index': dead_branch, 'Name': 'Smaller'}]}
    root = len(nodes)
    nodes.append(_simultaneous(root, names['request'], (0, heartbeat, compare), root=True))
    document['Commands'][0]['Root Node Index'] = root
    return ready._write(document)


def patch_loading_reset(raw, token):
    """Run alongside MainUpdate; a new scene/life must be armed afresh."""
    import ainb
    document = ainb.AINB.from_binary(raw).as_dict()
    nodes, names = document['Nodes'], metadata(token)['flags']
    root = nodes[document['Commands'][0]['Root Node Index']]
    if root['Node Type'] != 'Element_Simultaneous':
        raise ValueError('The supported native MainUpdate root was not found.')
    query = next(n for n in nodes if n['Name'] == 'SeqQueryGetNonStructGameDataBool')
    setter = next(n for n in nodes if n['Name'] == 'SeqOneShotSetNonStructGameDataBool')
    idle = next(n['Node Index'] for n in nodes if n['Name'] == 'SeqExecuteGenericDummyAction')
    query = copy.deepcopy(query)
    query.update({'Node Index': len(nodes), 'GUID': ready._guid(names['armed'], len(nodes)), 'Queries': [], 'Plugs': {}})
    query['Parameters']['Inputs'] = {'Int': [ready._default('GameDataIndex', -1)],
        'Bool': [ready._default('IsDirect', True)], 'String': [ready._default('GameDataFullName', ready.LOADING)]}
    nodes.append(query)
    setters = []
    for name in names.values():
        node = copy.deepcopy(setter)
        index = len(nodes)
        node.update({'Node Index': index, 'GUID': ready._guid(names['armed'], index), 'Queries': [], 'Plugs': {}})
        node['Properties'] = {'Bool': [{'Name': 'ExecuteEveryFrame', 'Default Value': True, 'Flags': []}]}
        node['Parameters']['Inputs'] = {'Int': [ready._default('GameDataIndex', -1)],
            'Bool': [ready._default('Value', False)], 'String': [ready._default('GameDataFullName', name)]}
        nodes.append(node)
        setters.append(index)
    clear = len(nodes)
    nodes.append(_simultaneous(clear, names['armed'], setters))
    branch = len(nodes)
    node = ready._node('Element_BoolSelector', branch, names['armed'],
        inputs={'Bool': [ready._from_query('Input', query['Node Index'])]}, queries=(query['Node Index'],))
    node['Plugs'] = {'Generic': [{'Node Index': query['Node Index'], 'Name': 'Input', 'Unknown 1': 0, 'Unknown 2': 0}],
                     'Child': [{'Node Index': clear, 'Name': 'True'}, {'Node Index': idle, 'Name': 'False'}]}
    nodes.append(node)
    root['Plugs']['Child'].append({'Node Index': branch, 'Name': ''})
    return ready._write(document)


def prepare_external_deathlink(romfs, mod, token, *, seed_marker, enabled=True):
    """Prepare a staged external mod AFTER its native readiness adapter."""
    from ootrr_full.formats import byml_codec
    from ootrr_full.formats.inspect_resources import sarc
    from ootrr_full.game.resource_allocations import grow_resources
    from .mod_codec import Codec
    romfs, mod = Path(romfs), Path(mod)
    def source(path):
        overlay = mod / path
        return (overlay if overlay.is_file() else romfs / path).read_bytes()
    compression = Codec(source('Pack/ZsDic.pack.zs'))
    def read(path):
        raw = source(path)
        return compression.decode(raw) if path.endswith('.zs') else raw
    templates = native_templates(sarc(read(ready.GLOBAL_PACK)))
    modified = {}
    for path in ready.PLAYER_PACKS:
        files = dict(sarc(read(path)))
        files[ready.BRAIN] = patch_player_brain(files[ready.BRAIN], token, templates, seed_marker=seed_marker)
        modified[path] = byml_codec.build_sarc(files)
    modified[ready.MAIN_UPDATE] = patch_loading_reset(read(ready.MAIN_UPDATE), token)
    raw = read(ready.GAMEDATA)
    for flag in metadata(token)['flags'].values():
        raw = ready.add_transient_flag(raw, flag)
    modified[ready.GAMEDATA] = raw
    growth = {path: max(0, len(raw) - len(read(path))) for path, raw in modified.items()}
    modified[ready.REST], _ = grow_resources(read(ready.REST), growth)
    for path, raw in modified.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(compression.encode(raw, source(path)) if path.endswith('.zs') else raw)
    return metadata(token, enabled=enabled)


class ExternalDeathLink:
    """Ephemeral network/life state. No event is persisted or replayed on login."""
    def __init__(self, manifest, live, *, event_state, slot, clock=time.monotonic, wall_clock=time.time):
        from ootrr_full.patching.soul_adapter import murmur3
        from ootrr_full.randomizer.randomizer_core import save_marker
        info = manifest.get('archipelago') or {}
        token = info.get('token') or manifest.get('token')
        value = validate_metadata(manifest['external_deathlink'], token) if manifest.get('external_deathlink') is not None else None
        self.enabled = bool(value and value['enabled'])
        self.keys = {name: murmur3(flag) for name, flag in value['flags'].items()} if value else {}
        self.marker, self.pause, self.loading = map(murmur3, (save_marker(manifest), ready.PAUSE, ready.LOADING))
        readiness = manifest.get('external_readiness') or {}
        self.readiness = murmur3(readiness['flag']) if readiness.get('flag') else None
        self.live, self.events, self.slot = live, event_state, slot
        self.clock, self.wall_clock = clock, wall_clock
        self._lock = threading.RLock()
        self._seen = []
        self.authenticated = False
        self.state, self.pending, self._fresh, self._last_tick = -1, None, 0, None
        self._armed, self._suppress = False, False
        self.status = ('DeathLink waiting for a live player' if self.enabled else
                       'DeathLink disabled in this player file' if value is not None or info.get('death_link') is False else
                       'DeathLink unavailable; prepare this room again')

    def _write(self, field, value):
        from ootrr_full.tracker.live_memory import set_bool_in, LiveUnavailable
        if not set_bool_in(self.live, self.keys[field], value):
            raise LiveUnavailable('the native DeathLink mailbox is missing')

    def _reset(self):
        self.state, self.pending, self._fresh, self._last_tick = -1, None, 0, None
        self._armed, self._suppress = False, False

    def suspend(self):
        from ootrr_full.tracker.live_memory import LiveUnavailable
        with self._lock, self.live.lock:
            self.authenticated = False
            self._reset()
            if not self.enabled:
                return
            try:
                flags = self.live.snapshot()['bool']
                if flags.get(self.marker) is True:
                    for field in ('armed', 'request', 'fired', 'heartbeat'):
                        self._write(field, False)
            except (OSError, LiveUnavailable):
                pass

    def receive(self, packet, aliases=()):
        data = packet.get('data') or {}
        if not isinstance(data, dict):
            return False
        stamp, source, cause = data.get('time'), data.get('source'), data.get('cause', '')
        if ('DeathLink' not in (packet.get('tags') or ()) or type(stamp) not in (int, float)
                or not math.isfinite(stamp) or stamp <= 0 or not isinstance(source, str)
                or not source.strip() or len(source) > 256 or not isinstance(cause, str) or len(cause) > 2048):
            return False
        key = stamp, source
        with self._lock:
            if not self.enabled or not self.authenticated or key in self._seen:
                return False
            self._seen = (self._seen + [key])[-128:]
            if source in (self.slot, *aliases) or self.state not in (0, 2) or self._suppress:
                return False
            if self._last_tick is None or (self.state != 2 and self.clock() - self._last_tick > 2):
                return False
            if self.pending is None:
                self.pending = dict(data)
            return True

    def step(self, authenticated):
        """Return at most one outgoing Bounce; callers enqueue on this connection."""
        from ootrr_full.tracker.live_memory import LiveUnavailable
        if not self.enabled:
            return None
        with self._lock, self.live.lock:
            self.authenticated = bool(authenticated)
            if not authenticated:
                self.suspend()
                return None
            try:
                flags = self.live.snapshot()['bool']
                required = {*self.keys.values(), self.marker, self.pause, self.loading, self.readiness}
                if not required <= flags.keys() or flags.get(self.marker) is not True:
                    self._reset()
                    self.status = 'DeathLink waiting for this seed and native mailbox'
                    return None
                if flags[self.loading]:
                    self._reset()
                    self.status = 'DeathLink waiting for loading to finish'
                    return None
                if self._armed and flags[self.keys['armed']] is not True:
                    self._reset()  # the native sequence observed a new scene/life
                now = self.clock()
                paused = flags[self.pause]
                if paused and self.state in (0, 2):
                    self.state = 2
                    self.status = 'DeathLink held while paused'
                    return None
                fresh = flags[self.keys['heartbeat']]
                if (not fresh and self.state in (0, 2)
                        and (not flags[self.readiness] or self.events.playing())):
                    # A native cutscene can suspend the Player brain just as
                    # pause does. Its explicit busy publication holds a death;
                    # only a fresh live tick may later consume or report it.
                    self.state = 2
                    self.status = 'DeathLink waiting for normal player control'
                    return None
                if fresh:
                    self._write('heartbeat', False)
                    self._last_tick, self._fresh = now, self._fresh + 1
                elif self._last_tick is None or now - self._last_tick > 2:
                    for field in ('armed', 'request', 'fired'):
                        self._write(field, False)
                    self._reset()
                    self.status = 'DeathLink waiting for fresh Player AI'
                    return None
                else:
                    return None  # never infer death from a stale publication
                if self._fresh < 2:
                    return None
                dead = flags[self.keys['dead']]
                if dead:
                    outgoing = self.state in (0, 2) and not self._suppress and not flags[self.keys['fired']]
                    self.state, self.pending, self._suppress = 1, None, False
                    for field in ('request', 'fired'):
                        self._write(field, False)
                    self.status = 'DeathLink observed a live Player death'
                    if outgoing:
                        data = {'time': self.wall_clock(), 'source': self.slot, 'cause': self.slot + ' died.'}
                        self._seen = (self._seen + [(data['time'], data['source'])])[-128:]
                        return {'cmd': 'Bounce', 'tags': ['DeathLink'], 'data': data}
                    return None
                if self.state == 1:
                    self._suppress = False
                if not self._armed:
                    # Clear a previous client request before opening this live
                    # session, including a client restart on an unsaved game.
                    self._write('request', False)
                    self._write('fired', False)
                    self._write('armed', True)
                    self._armed = True
                busy = paused or not flags[self.readiness] or self.events.playing()
                self.state = 2 if busy else 0
                if self.pending is not None and not busy and not self._suppress:
                    self._write('request', True)
                    self._suppress = True
                    self.pending = None
                    self.status = 'DeathLink requested through native Player AI'
                else:
                    self.status = 'DeathLink active' if not busy else 'DeathLink waiting for normal player control'
            except (OSError, LiveUnavailable) as error:
                self._reset()
                self.status = 'DeathLink unavailable (' + str(error) + ')'
            return None
