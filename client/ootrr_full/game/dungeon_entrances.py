"""Coupled native dungeon entrances, with an identical AP region permutation.

Connection IDs, age/arrival evidence and the destination-only edits come from
the MIT OOTRR entrance adapter. The AP fill remains the only item fill.
"""
from functools import lru_cache
from importlib import resources
import json

DESTINATION_KEYS = ('NextBancParamNameAdult', 'NextBancParamNameChild', 'NextStartPosName',
                    'NextEventName', 'InitEventName', 'InitEventFlag', 'AddEventName',
                    'AddEventFlag', 'IsAlternativeGameDataBool', 'IsChangableAirPos')


@lru_cache(maxsize=1)
def catalogue():
    data = json.loads(resources.files(__package__).joinpath('dungeon_entrances.json').read_text(encoding='utf-8'))
    if data.get('format') != 1 or len(data['connections']) != 11 or len(data['doors']) != 31:
        raise ValueError('The paired native dungeon entrance catalogue is incomplete.')
    return data


def normalize(layout):
    connections = catalogue()['connections']
    names = {row['name'] for row in connections}
    if (not isinstance(layout, dict) or set(layout) != names
            or any(not isinstance(value, str) for value in layout.values())
            or set(layout.values()) != names):
        raise ValueError('Every dungeon entrance and destination must occur exactly once.')
    return dict(sorted(layout.items()))


def _fits(parameter, age):
    return ('_Adult' not in parameter or age == 'adult') and ('_Child' not in parameter or age == 'child')


def age_errors(layout):
    data = catalogue()
    connections = {row['name']: row for row in data['connections']}
    doors = {row['hash']: row for row in data['doors']}
    errors = []
    for spot_name, dungeon_name in normalize(layout).items():
        spot, dungeon = connections[spot_name], connections[dungeon_name]
        ages = set(dungeon['extra'])
        for number in spot['doors']:
            ages.update(doors[number]['ages'])
        back = doors[spot['back']]
        for age in ages:
            if back['start_ok'].get(age) != 'ok' or not _fits(back[age], age):
                errors.append(dungeon_name + ' at ' + spot_name + ' has no safe ' + age + ' return.')
    return errors


def region_targets(layout):
    connections = {row['name']: row for row in catalogue()['connections']}
    result = {}
    for spot_name, dungeon_name in normalize(layout).items():
        spot, dungeon = connections[spot_name], connections[dungeon_name]
        result[tuple(spot['entry'])] = dungeon['entry'][1]
        result[tuple(dungeon['exit'])] = spot['exit'][1]
    return result


def _proof(data, settings, layout):
    from ootrr_full.logic.rules import Logic, vanilla_placements
    values = dict(settings, dungeon_entrances=layout)
    logic = Logic(data, values)
    inventory = {item: 100 for item, row in data.item_table.items() if row.get('type') != 'Event'}
    state, reached, _ = logic.sweep(vanilla_placements(data, logic), logic.new_state(inventory))
    return state.has('Triforce'), reached, state.reached


def layout_candidates(data, settings, seed_key):
    """Deterministic age-safe candidates, proved once each in selection order."""
    from ootrr_full.randomizer.full_randomizer import DetRandom
    connections = catalogue()['connections']
    names = [row['name'] for row in connections]
    baseline = dict(zip(names, names))
    won, available, ages = _proof(data, settings, baseline)
    if not won:
        raise ValueError('The unshuffled full world cannot reach victory under these entrance settings.')
    rng = DetRandom(seed_key + '\0full-paired-dungeons-v1')
    groups = {}
    for row in connections:
        profile = tuple(age for age in ('child', 'adult') if row['entry'][1] in ages[age])
        groups.setdefault(profile, []).append(row['name'])
    seen, broad = {tuple(sorted(baseline.items()))}, 0
    for _ in range(64):
        # The full remake rules retain age-specific boss fights. A child-only
        # dungeon cannot be moved behind an adult-only entrance while keeping
        # every physical check accessible. Shuffle within proven age profiles.
        layout = {}
        for group in groups.values():
            layout.update(zip(group, rng.shuffle(group)))
        identity = tuple(sorted(layout.items()))
        if identity in seen or age_errors(layout):
            continue
        seen.add(identity)
        won, reached, _ = _proof(data, settings, layout)
        if won and set(available) <= set(reached):
            yield normalize(layout)
            broad += 1
            if broad == 8:
                break
    # With native dungeon equipment left in place, broad permutations can put
    # the Hammer behind its own entrance requirement. Try bounded smaller
    # permutations rather than repeating dozens of impossible full prepares.
    pairs = [(left, right) for group in groups.values() for index, left in enumerate(group)
             for right in group[index + 1:]]
    for left, right in rng.shuffle(pairs):
        layout = dict(baseline, **{left: right, right: left})
        identity = tuple(sorted(layout.items()))
        if identity in seen or age_errors(layout):
            continue
        won, reached, _ = _proof(data, settings, layout)
        if won and set(available) <= set(reached):
            yield normalize(layout)


def choose(data, settings, seed_key):
    """One deterministic, age-safe layout retaining maximum-inventory access."""
    try:
        return next(layout_candidates(data, settings, seed_key))
    except StopIteration:
        raise ValueError('No safe dungeon entrance layout retains these age routes. Try another seed.') from None


def moves(layout):
    """(target-door, vanilla-source-door) pairs; ordinary exits are coupled."""
    data = catalogue()
    connections = {row['name']: row for row in data['connections']}
    doors = {row['hash']: row for row in data['doors']}
    result = []
    for spot_name, dungeon_name in normalize(layout).items():
        if spot_name == dungeon_name:
            continue
        spot, dungeon = connections[spot_name], connections[dungeon_name]
        for target in spot['doors']:
            target_door = doors[target]
            def score(source):
                door = doors[source]
                age = door['age'] == target_door['age']
                alt = door['map'].endswith('_Alternative') == target_door['map'].endswith('_Alternative')
                return 0 if age and alt else 1 if age else 2
            source = min(dungeon['doors'], key=score)
            result.append((target, source))
        result.append((dungeon['back'], spot['back']))
    if len({target for target, _ in result}) != len(result):
        raise ValueError('An entrance actor is rewritten twice.')
    return result


def apply(layout, read, stage):
    """Rewrite only the ten destination fields, preserving every AP reward edit."""
    import copy
    from ootrr_full.formats import byml_codec
    normalized = normalize(layout)
    if age_errors(normalized):
        raise ValueError('The dungeon entrance layout has an unsafe native arrival age.')
    doors = {row['hash']: row for row in catalogue()['doors']}
    documents, originals = {}, {}
    def document(path):
        if path not in documents:
            documents[path] = byml_codec.load(read(path))
            originals[path] = copy.deepcopy(documents[path])
        return documents[path]
    def actor(path, number):
        rows = document(path)['root']['Actors']
        found = [row for row in rows if str(row.get('Hash')) == number]
        if len(found) != 1 or found[0].get('Gyaml') != 'FieldAndDungeonEntranceEventRequestActor':
            raise ValueError('A supported native dungeon entrance actor is missing: ' + number)
        if not isinstance(found[0].get('Dynamic'), dict):
            raise ValueError('A supported native entrance has no destination parameters.')
        return found[0]
    # Snapshot every destination before mutating any source map.
    edits = []
    for target, source in moves(normalized):
        source_row = actor(doors[source]['file'], source)
        values = {key: copy.deepcopy(source_row['Dynamic'][key]) for key in DESTINATION_KEYS
                  if key in source_row['Dynamic']}
        edits.append((doors[target]['file'], target, values))
    for path, number, values in edits:
        row = actor(path, number)
        for key in DESTINATION_KEYS:
            row['Dynamic'].pop(key, None)
        row['Dynamic'].update(copy.deepcopy(values))
    touched = {path for path, _, _ in edits}
    for path in touched:
        result = byml_codec.dump(documents[path])
        if byml_codec.load(result) != documents[path]:
            raise ValueError('The native dungeon entrance map did not round-trip.')
        # The only possible edits above are the declared destination keys.
        before, after = copy.deepcopy(originals[path]), copy.deepcopy(documents[path])
        wanted = {number for target, number, _ in edits if target == path}
        for left, right in zip(before['root']['Actors'], after['root']['Actors']):
            if str(left.get('Hash')) in wanted:
                for key in DESTINATION_KEYS:
                    left['Dynamic'].pop(key, None)
                    right['Dynamic'].pop(key, None)
        if before != after:
            raise ValueError('The dungeon entrance patch changed an unrelated resource field.')
        stage(path, result)
    return {'layout': normalized, 'actors': len(edits), 'map_files': sorted(touched)}
