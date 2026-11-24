"""First-collection rewards for repeatable physical sources.

Generated pickups retain the real item's PouchActor. Their private event AINB
sets a saved check flag only after the native add-to-pouch action. The source
keeps its native destruction and respawn settings; the texture adapter can
give its map instance a private appearance actor. Once the check is collected, the pickup it
drops is not a reward any more: its own AI (a clone of the native ``DropItem``
one) checks the flag when it spawns and hands over to the source's vanilla drop
(:func:`vanilla_drop_files`). Minor rewards run their native Small get callback
every time, retaining the central pickup display and sound; their saved flag is
set after the native pouch push, never when a drop merely spawns. Gameplay
validation remains required.

Shop shelves holding a shuffled item (``Shop_Rando_*``) are bought once the same
way: each gets its own actor whose shop AI writes the check flag when the item is
bought, and restores the native sold counter from that flag on re-entry. Bought
shelves stay hidden but present so the cursor can navigate through their slots.
The map is unchanged (no Presence: some shelves, like the Kokiri
shop's, already have one).

The shuffled Lake Hylia letter uses the same saved check because its native
placement has no persistent hash key. This placed reward always runs its get
event, including for minor items, and is recorded only after the pouch push.
"""
import copy
from collections import OrderedDict
import hashlib
import math
import struct
import uuid

from ootrr_full.formats import byml_codec
from ootrr_full.game.item_forms import (WORLD_CANONICAL, DROP_PREFIX, SHOP_PREFIX, build_pack, canonical_of,
                        is_derived, add_rsdb_rows, resolve_components, underwater_actor, _copy_ref, _pack_path)
from ootrr_full.patching.soul_adapter import FLAG_PREFIX as SOUL_FLAG_PREFIX, murmur3
from ootrr_full.patching.ammo_quantities import (EXACT_AMMUNITION, AMMUNITION_CAPACITY,
                                                exact_ammunition_grant, ammunition_capacity)


def sarc(raw):
    # Item-pool generation uses the pure ammunition rules below inside the
    # frozen AP executable, which does not bundle a game-resource zstd decoder.
    from ootrr_full.formats.inspect_resources import sarc as read_sarc
    return read_sarc(raw)

REPEATABLE = frozenset(('pots', 'bushes', 'rocks', 'crates', 'beehives', 'trees'))
EVENT_PACK = 'Pack/AI.Global.Product.111.pack.zs'
EVENT_MEMBER = 'AI/PouchContent.event.root.ainb'
DROP_AI_MEMBER = 'AI/DropItem.root.ainb'
DROP_AI_INFO = '?AI/AIInfo/DropItem.engine__actor__AIInfo.bgyml'
# The native graph that reserves its actor's drop and requests its death (a Poe's
# lantern leaving its spirit): the template of a collected pickup's hand-over.
HANDOVER_AI_MEMBER = 'AI/Weapon_PoeCantera.root.ainb'
DROP_BLACKBOARD = 'Component/Blackboard/BlackboardParamTable/Drop.engine__component__BlackboardParamTable.bgyml'
DROP_PARAM_DEFAULT = 'Work/Component/DropParam/Default.game__component__DropParam.gyml'
# Drop table item types: a rupee by its pouch category (rocks', beehives' tables),
# another named actor (Gohma's heart, the Poe's spirit).
RUPEE_DROP_TYPE, ACTOR_DROP_TYPE = 995674644, 126134492
LARGE_GET_TYPE = 1746592023
SMALL_GET_TYPE = murmur3('Small')
# Short get (the game's own for gold tokens, heart pieces and the gold rupee on the
# ground): no long held-up pose, but Link still shows the item.
MEDIUM_GET_TYPE = 1027255402
# Minor rewards use Small explicitly, keeping the game's central pickup display.
# Medium played an unwanted pose in earlier pilots. Their own callback still
# runs after pickup, even after another item of that family was already found.
MINOR_LARGE_PREFIXES = ('Item_BombchuBundle_',)
MINOR_PREFIXES = ('TBox_Rupee_', 'TBox_ArrowBundle_', 'TBox_DekuNutBundle', 'TBox_DekuSeedBundle',
                  'Item_BombBundle_', 'Item_DekuStickBundle_', 'Item_BombchuBundle_', 'Tbox_MagicJar_',
                  'Item_ScrubBusinessSeed')
MINOR_ACTORS = frozenset(('Obj_Heart',))   # recovery heart (not a piece nor a container)
SHOP_ONCE_PREFIX = 'Shop_RandoOnce_'
SHOP_AI_MEMBER = 'AI/Shop_Item_Base.root.ainb'
SHOP_EVENT_MEMBER = 'AI/NpcCommon.event.root.ainb'


def is_minor_reward(canonical):
    """Rupees, ammunition and recovery hearts: picked up with the short get."""
    return canonical in MINOR_ACTORS or canonical.startswith(MINOR_PREFIXES)


def get_type(canonical, native_info=None):
    """Use the native short-pickup route for minor rewards, never a held pose."""
    if is_minor_reward(canonical):
        return SMALL_GET_TYPE
    kind = (native_info or {}).get('PouchGetType')
    if kind in ('Small', 'Medium', 'Large'):
        return murmur3(kind)
    return LARGE_GET_TYPE


def pickup_pouch_settings(canonical, native_info=None):
    """PouchContentParam overrides of a first-collection pickup dropping ``canonical``.

    The Small route retains a consumable's native central pickup display. Its
    unique pouch callback runs on every AP source, so collection can be recorded
    after the actual push. Major items retain their native presentation type.
    """
    # Every physical AP pickup must execute its own native pouch callback.
    # Small keeps Dm_SY_Get's central pickup/sound and does not add a pose.
    # A flag written when the source spawns is not evidence of collection.
    settings = {'PlayGetEventManyTimes': True, 'IsAutoSaveAfterPlayGet': True}
    settings['GetType'] = byml_codec.U32(get_type(canonical, native_info))
    return settings


def _guid(text):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'oot-randomizer/' + text))


class _AINBTemplates:
    """Parse and validate repeated native inputs once per generation, not output."""
    LIMIT = 8

    def __init__(self):
        self.cache = OrderedDict()

    def get(self, raw, faithful=False):
        import ainb
        entry = self.cache.get(raw)
        if entry is None:
            script = ainb.AINB.from_binary(raw)
            entry = {'script': script, 'document': script.as_dict(),
                     'blackboard': copy.deepcopy(script.blackboard), 'faithful': False}
            self.cache[raw] = entry
            if len(self.cache) > self.LIMIT:
                self.cache.popitem(last=False)
        else:
            self.cache.move_to_end(raw)
        if faithful and not entry['faithful']:
            rewritten = ainb.AINB.from_dict(entry['document'])
            rewritten.blackboard = copy.deepcopy(entry['blackboard'])
            if rewritten.to_binary() != entry['script'].to_binary():
                raise ValueError('The native AI cannot be rewritten faithfully.')
            entry['faithful'] = True
        return entry


def instrument_pickup_event(raw, flag, filename, canonical=None, also_set=(), skip_if_collected=True,
                            source_cache=None, grant=None, capacity=()):
    """Clone an event AI and sequence a GameData write AFTER native pouch push.

    All commands and original nodes are retained. No setter is attached to actor
    death, jar destruction, event entry, animation completion or item possession.
    ``also_set`` lists further saved Bool flags written after ``flag`` (a soul
    picked from a pot also sets its ``IsGet.Item_Soul_*`` flag). With
    ``skip_if_collected`` the push is skipped once ``flag`` is set. Eligibility
    is handled by the native request-get path before this accepted callback;
    checking it a second time here would lose a consumed check at full capacity.
    ``grant`` optionally replaces the bundle push by a native unit actor/count.
    """
    try:
        import ainb
    except ImportError as error:
        raise ValueError('Install ainb==0.2.17 for first-collection rewards.') from error
    original = (source_cache or _AINBTemplates()).get(raw)['document']
    document = copy.deepcopy(original)
    if document['Version'] != 0x408:
        raise ValueError('Unexpected AINB version for first collection.')
    nodes = document['Nodes']
    pushes = [n for n in nodes if n['Name'] == 'OneShotPouchContentPushToPouchOwnInEvent']
    if len(pushes) != 1:
        raise ValueError('Native pickup action ambiguous or missing.')
    push = pushes[0]['Node Index']
    parents = [(n, plug) for n in nodes for plug in n.get('Plugs', {}).get('Child', [])
               if plug['Node Index'] == push]
    if not parents:
        raise ValueError('Pickup action without an executable parent.')
    # A native sequential template from this very graph preserves its policies.
    sequential = next((copy.deepcopy(n) for n in nodes if n['Node Type'] == 'Element_Sequential'), None)
    if sequential is None:
        raise ValueError('Sequential template missing from the get graph.')
    if grant is not None:
        actor, amount = grant
        if actor not in {entry[1] for entry in EXACT_AMMUNITION} or type(amount) is not int or not 0 < amount <= 999:
            raise ValueError('Unexpected exact ammunition grant.')
        template = next((n for n in nodes if n['Name'] == 'OneShotAddOrRemovePouchContent'), None)
        if template is None:
            raise ValueError('Native exact pouch action missing.')
        action = copy.deepcopy(template)
        action.update({'Node Index': push, 'GUID': pushes[0]['GUID'], 'Queries': [], 'Plugs': {}})
        inputs = action['Parameters']['Inputs']
        expected = {'Int': {'Num'}, 'Bool': {'IsEquipDirect', 'IsGetEvent'}, 'String': {'Actor', 'Reason'}}
        if {kind: {value['Name'] for value in values} for kind, values in inputs.items()} != expected:
            raise ValueError('Unexpected native exact pouch action inputs.')
        for value in inputs['Int']:
            value.update(_default('Num', amount))
        for value in inputs['String']:
            value.update(_default(value['Name'], ('Work/Actor/' + actor + '.engine__actor__ActorParam.gyml'
                                                if value['Name'] == 'Actor' else 'Put')))
        for value in inputs['Bool']:
            value.update(_default(value['Name'], False))
        nodes[push] = action
    sequence_index, setter_index = len(nodes), len(nodes) + 1
    for _, plug in parents:
        plug['Node Index'] = sequence_index
    sequential.update({'Node Index': sequence_index, 'GUID': _guid(flag + '/sequence'),
                       'Queries': [], 'Attachments': [], 'Flags': [],
                       'Parameters': {'Inputs': {}, 'Outputs': {}}, 'XLink Actions': [],
                       'Plugs': {'Child': [{'Node Index': push, 'Name': ''},
                                           {'Node Index': setter_index, 'Name': ''}]}})
    for prop in sequential.get('Properties', {}).get('Bool', []):
        if prop['Name'] == 'IsLoop':
            prop['Default Value'] = False
    setter = _flag_setter(setter_index, flag, _guid(flag + '/setter'))
    document['Filename'] = filename
    nodes.extend([sequential, setter])
    eligible = sequence_index
    if capacity:
        if tuple(capacity) not in AMMUNITION_CAPACITY.values():
            raise ValueError('Unknown native ammunition capacity.')
        # This is an equipment guard, not another CanPush/capacity-full test.
        # An accepted AP pickup without its bag still commits the check, while
        # giving neither ammunition, equipment nor a substitute rupee.
        structure_model = next((n for n in nodes[:sequence_index]
                                if n['Name'] == 'QueryGetNonStructGameDataStruct'
                                and any(v.get('Default Value') == 'IsGet'
                                        for v in n['Parameters']['Inputs'].get('String', ()))), None)
        owned_model = next((n for n in nodes[:sequence_index] if n['Name'] == 'QueryGetGameDataBool'), None)
        selector_model = next(n for n in nodes[:sequence_index] if n['Node Type'] == 'Element_BoolSelector')
        if structure_model is None or owned_model is None:
            raise ValueError('Native equipment ownership query missing.')
        eligible = setter_index
        for bag in capacity:
            structure_index, owned_index, choice_index = range(len(nodes), len(nodes) + 3)
            structure = copy.deepcopy(structure_model)
            structure.update({'Node Index': structure_index, 'GUID': _guid(flag + '/bags/' + bag + '/struct'),
                              'Queries': [], 'Plugs': {'Generic': [{'Node Index': owned_index, 'Name': 'Value'}]}})
            owned = copy.deepcopy(owned_model)
            owned.update({'Node Index': owned_index, 'GUID': _guid(flag + '/bags/' + bag + '/owned'),
                          'Queries': [structure_index], 'Plugs': {}})
            owned['Parameters']['Inputs']['String'] = [_default('GameDataName', bag)]
            owned['Parameters']['Inputs']['Pointer'][0]['Node Index'] = structure_index
            selector = _bool_selector(selector_model, choice_index, _guid(flag + '/bags/' + bag + '/choice'),
                                      owned_index, sequence_index, eligible)
            nodes.extend([structure, owned, selector])
            eligible = choice_index
        for _, plug in parents:
            plug['Node Index'] = eligible
    if skip_if_collected:
        # A drop may already exist when another copy of the same location is
        # collected. Recheck the saved per-check flag at native pickup execution,
        # rather than relying only on the source actor's Presence condition.
        flag_query_index, flag_selector_index = len(nodes), len(nodes) + 1
        flag_query = copy.deepcopy(next(n for n in nodes[:sequence_index]
                                       if n['Name'] == 'QueryGetNonStructGameDataBool'))
        flag_query.update({'Node Index': flag_query_index, 'GUID': _guid(flag + '/already-collected'),
                           'Queries': [], 'Plugs': {}})
        flag_query['Parameters']['Inputs']['String'] = [_default('GameDataFullName', flag)]
        flag_selector = copy.deepcopy(next(n for n in nodes[:sequence_index]
                                          if n['Node Type'] == 'Element_BoolSelector'))
        noop = next(n['Node Index'] for n in nodes[:sequence_index] if n['Name'] == 'OneshotDoNothing')
        flag_selector.update({'Node Index': flag_selector_index, 'GUID': _guid(flag + '/first-only'),
                              'Queries': [flag_query_index], 'Attachments': [], 'Flags': [], 'XLink Actions': []})
        flag_selector['Parameters'] = {'Inputs': {'Bool': [{'Name': 'Input', 'Default Value': False,
                                          'Node Index': flag_query_index, 'Output Index': 0, 'Flags': []}]},
                                       'Outputs': {}}
        flag_selector['Plugs'] = {
            'Generic': [{'Node Index': flag_query_index, 'Name': 'Input', 'Unknown 1': 0, 'Unknown 2': 0}],
            'Child': [{'Node Index': noop, 'Name': 'True'}, {'Node Index': eligible, 'Name': 'False'}]}
        for _, plug in parents:
            plug['Node Index'] = flag_selector_index
        nodes.extend([flag_query, flag_selector])
    for extra in also_set:
        extra_setter = copy.deepcopy(setter)
        extra_setter.update({'Node Index': len(nodes), 'GUID': _guid(flag + '/also/' + extra)})
        extra_setter['Parameters']['Inputs']['String'] = [_default('GameDataFullName', extra)]
        sequential['Plugs']['Child'].append({'Node Index': len(nodes), 'Name': ''})
        nodes.append(extra_setter)
    result = ainb.AINB.from_dict(document).to_binary()
    checked = ainb.AINB.from_binary(result).as_dict()
    if checked != document:
        raise ValueError('The modified get graph does not read back identically.')
    # Strong invariant: every original command is untouched and additions occur
    # only at child references to the native pouch-push action.
    if checked['Commands'] != original['Commands']:
        raise ValueError('Get commands changed unexpectedly.')
    return result


def _default(name, value):
    return {'Name': name, 'Default Value': value, 'Node Index': -1, 'Output Index': 0, 'Flags': ['Uses Default']}


def _flag_setter(index, flag, guid):
    """``OneShotSetNonStructGameDataBool`` node at ``index`` setting the saved Bool ``flag``."""
    return {'Node Type': 'UserDefined', 'Node Index': index,
            'Name': 'OneShotSetNonStructGameDataBool', 'GUID': guid,
            'Flags': [], 'Queries': [], 'Attachments': [],
            'Properties': {'Bool': [{'Name': 'ExecuteEveryFrame', 'Default Value': False, 'Flags': []}]},
            'Parameters': {'Inputs': {'Int': [_default('GameDataIndex', -1)],
                                      'Bool': [_default('Value', True)],
                                      'String': [_default('GameDataFullName', flag)]}, 'Outputs': {}},
            'XLink Actions': [], 'Plugs': {}}


def _retarget(value, old, new):
    """Replace every ``'Node Index': old`` reference inside a node description."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'Node Index' and item == old:
                value[key] = new
            else:
                _retarget(item, old, new)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if item == old and isinstance(item, int) and not isinstance(item, bool):
                value[index] = new
            else:
                _retarget(item, old, new)


def _refers(value, index):
    """Whether a node description holds a ``'Node Index': index`` reference."""
    if isinstance(value, dict):
        return value.get('Node Index') == index or any(_refers(item, index) for item in value.values())
    if isinstance(value, list):
        return any(_refers(item, index) for item in value)
    return False


def as_command(node):
    """``ASCommand`` of an ``ExecuteASPlay`` node (a property or a default input), or None."""
    values = list(node.get('Properties', {}).get('String', []))
    values += node.get('Parameters', {}).get('Inputs', {}).get('String', [])
    return next((p.get('Default Value') for p in values if p['Name'] == 'ASCommand'), None)


def _shop_stock_restore(raw, nodes, flag, seller, slot, source_cache=None):
    """Reuse the native sold-counter increment, addressed by this shelf's seller/slot.

    NpcCommon normally uses its own actor and Shop_SelectItemIndex. A shelf uses
    its ForSale source and blackboard index instead; nothing depends on which
    item the player is currently looking at.
    """
    import ainb
    source = (source_cache or _AINBTemplates()).get(raw)['document']['Nodes']
    entry, = [n for n in source if n['Name'] == 'EventTriggerAddShopItemSoldNum']
    action, = entry['Plugs']['Child']
    replacements = {}
    # Follow only the increment's dependency tree, not other event commands.
    pending, reachable = [action['Node Index']], {}
    while pending:
        index = pending.pop()
        if index in reachable or index in replacements:
            continue
        node = source[index]
        if node['Name'] == 'QueryGenericGetOwnActorLink':
            replacements[index] = seller
        elif node['Name'] == 'QueryGetNonStructGameDataInt':
            values = node['Parameters']['Inputs']['String']
            if values[0]['Default Value'] != 'Shop_SelectItemIndex':
                raise ValueError('Unexpected shop sold counter index.')
            replacements[index] = slot
        else:
            reachable[index] = node
            pending.extend(node.get('Queries', []))
    if {n['Name'] for n in reachable.values()} != {
            'OneShotAddGameDataInt', 'QueryFormatStringFromInt', 'QueryGetGameDataStruct',
            'QueryGenericGetActorName', 'QueryGetNonStructGameDataStruct'} or len(replacements) != 2:
        raise ValueError('Unexpected native shop sold counter graph.')
    indices = {old: len(nodes) + i for i, old in enumerate(reachable)}
    mapping = {**indices, **replacements}
    for old, template in reachable.items():
        node = copy.deepcopy(template)
        # Discard outgoing metadata links to event nodes that are not cloned.
        node['Plugs'] = {}
        for part in ('Queries', 'Parameters'):
            for before, after in mapping.items():
                _retarget(node[part], before, -after - 1000)
            for after in mapping.values():
                _retarget(node[part], -after - 1000, after)
        node['Node Index'] = indices[old]
        node['GUID'] = _guid(f'{flag}/restore-stock/{old}')
        nodes.append(node)
    return indices[action['Node Index']]


def instrument_shop_ai(raw, flag, filename, shop_event_raw, source_cache=None):
    """Clone the shop item AI so that a shelf is bought once.

    * the saved ``flag`` is set by a node added to the two branches a bought item
      goes through: the get demo (``ExecuteASPlay`` ``Rotate_GetDemo``, the item
      held up by Link: checked in game, bought items take this one) and
      ``ExecuteShopItemPutInPouch``;
    * every reader of the native ``QueryShopItemIsSoldOut`` (model hidden, sold
      out message to the linked ``Shop_Board_SoldOut``) reads ``flag`` instead;
    * once bought, the hidden branch restores the native sold counter if needed
      (StockNum 1, see ``limit_shop_stock``). The shelf stays present and sold out,
      including after reload: deleting it would break navigation between slots.
    """
    try:
        import ainb
    except ImportError as error:
        raise ValueError('Install ainb==0.2.17 for single purchases in shops.') from error
    entry = (source_cache or _AINBTemplates()).get(raw, faithful=True)
    original = entry['document']

    def build(document):
        # ainb 0.2.17 drops this graph's blackboard in as_dict(): restore it (no
        # node refers to it by index), else the written file is unreadable.
        result = ainb.AINB.from_dict(document)
        result.blackboard = copy.deepcopy(entry['blackboard'])
        return result.to_binary()
    document = copy.deepcopy(original)
    if document['Version'] != 0x408:
        raise ValueError('Unexpected AINB version for the shop item AI.')
    nodes = document['Nodes']

    def only(name):
        found = [n for n in nodes if n['Name'] == name]
        if len(found) != 1:
            raise ValueError(f'Shop item AI: {name} ambiguous or missing.')
        return found[0]
    put = only('ExecuteShopItemPutInPouch')['Node Index']
    sold_out = only('QueryShopItemIsSoldOut')['Node Index']
    template = only('QueryGetNonStructGameDataBool')
    def parent_of(index):
        found = [n for n in nodes if any(p['Node Index'] == index for p in n.get('Plugs', {}).get('Child', []))]
        if len(found) != 1 or found[0]['Node Type'] != 'Element_Simultaneous':
            raise ValueError('Shop item AI: purchase step without a simultaneous parent.')
        return found[0]

    demo = [n['Node Index'] for n in nodes if n['Name'] == 'ExecuteASPlay' and as_command(n) == 'Rotate_GetDemo']
    if len(demo) != 1:
        raise ValueError('Shop item AI: get demo ambiguous or missing.')
    parents = [parent_of(demo[0]), parent_of(put)]
    setter_index, query_index = len(nodes), len(nodes) + 1
    setter = _flag_setter(setter_index, flag, _guid(flag + '/bought'))
    readers = [n for n in nodes if n['Node Index'] != sold_out
               and (sold_out in n.get('Queries', []) or _refers(n.get('Parameters'), sold_out))]
    if not readers:
        raise ValueError('Shop item AI: sold out state not read.')
    for node in readers:
        _retarget(node.get('Queries', []), sold_out, query_index)
        _retarget(node.get('Parameters', {}), sold_out, query_index)
        _retarget(node.get('Plugs', {}), sold_out, query_index)
    query = copy.deepcopy(template)
    query.update({'Node Index': query_index, 'GUID': _guid(flag + '/sold-out'), 'Queries': [], 'Plugs': {}})
    query['Parameters']['Inputs']['String'] = [_default('GameDataFullName', flag)]
    for parent in parents:
        parent['Plugs']['Child'].append({'Node Index': setter_index, 'Name': ''})
    # Keep the visibility selector out of the pouch action so restoration cannot
    # affect the sale in progress.
    selectors = [n for n in readers if n['Node Type'] == 'Element_BoolSelector']
    if len(selectors) != 1:
        raise ValueError('Shop item AI: sold out visibility ambiguous or missing.')
    selector = selectors[0]
    branch = next((p for p in selector['Plugs'].get('Child', []) if p['Name'] == 'True'), None)
    if branch is None or nodes[branch['Node Index']]['Name'] != 'OneShotGameModelControllerSetVisible':
        raise ValueError('Shop item AI: sold out branch not recognised.')
    put_parent = parents[1]
    put_parent['Plugs']['Child'] = [p for p in put_parent['Plugs']['Child'] if p['Node Index'] != selector['Node Index']]
    native_index = len(nodes) + 2
    nodes.extend([setter, query])
    native = copy.deepcopy(selector)
    native.update({'Node Index': native_index, 'GUID': _guid(flag + '/native-sold-out'), 'Queries': [sold_out],
                   'Attachments': [], 'Flags': [], 'XLink Actions': []})
    native['Parameters'] = {'Inputs': {'Bool': [{'Name': 'Input', 'Default Value': False, 'Node Index': sold_out,
                                                 'Output Index': 0, 'Flags': []}]}, 'Outputs': {}}
    hidden_index = branch['Node Index']
    branch['Node Index'] = native_index
    nodes.append(native)
    restore = _shop_stock_restore(shop_event_raw, nodes, flag,
                                 only('QueryActorGetReferenceLinkSrcActor')['Node Index'],
                                 only('QueryBlackboardGetS32')['Node Index'], source_cache=source_cache)
    sequence_index = len(nodes)
    sequence = {'Node Type': 'Element_Sequential', 'Node Index': sequence_index, 'Name': '',
                'GUID': _guid(flag + '/restore-and-hide'), 'Flags': [], 'Queries': [], 'Attachments': [],
                'Properties': {}, 'Parameters': {'Inputs': {}, 'Outputs': {}}, 'XLink Actions': [],
                'Plugs': {'Child': [{'Node Index': restore, 'Name': ''},
                                    {'Node Index': hidden_index, 'Name': ''}]}}
    nodes.append(sequence)
    native['Plugs'] = {'Generic': [{'Node Index': sold_out, 'Name': 'Input', 'Unknown 1': 0, 'Unknown 2': 0}],
                       'Child': [{'Node Index': hidden_index, 'Name': 'True'},
                                 {'Node Index': sequence_index, 'Name': 'False'}]}
    document['Filename'] = filename
    binary = build(document)
    result = ainb.AINB.from_binary(binary).as_dict()
    if result != document:
        raise ValueError('The modified shop item AI does not read back identically.')
    if result['Commands'] != original['Commands']:
        raise ValueError('Shop item AI commands changed unexpectedly.')
    return binary


def _bool_selector(template, index, guid, query_index, true_index, false_index):
    """Copy of the BoolSelector ``template``: ``true_index`` when the query outputs true."""
    selector = copy.deepcopy(template)
    selector.update({'Node Index': index, 'GUID': guid, 'Queries': [query_index],
                     'Attachments': [], 'Flags': [], 'XLink Actions': []})
    selector['Parameters'] = {'Inputs': {'Bool': [{'Name': 'Input', 'Default Value': False, 'Node Index': query_index,
                                                   'Output Index': 0, 'Flags': []}]}, 'Outputs': {}}
    selector['Plugs'] = {'Generic': [{'Node Index': query_index, 'Name': 'Input', 'Unknown 1': 0, 'Unknown 2': 0}],
                         'Child': [{'Node Index': true_index, 'Name': 'True'},
                                   {'Node Index': false_index, 'Name': 'False'}]}
    return selector


def instrument_drop_ai(raw, flag, filename, event_raw, mark_on_spawn=None, restore_raw=None, source_cache=None):
    """Clone the native drop AI so that a pickup spawned after its check is not a reward.

    The start-up sequence of the root (one frame of nothing, then the rotation AS)
    first asks the saved ``flag``: set, the pickup goes before it can be touched; not
    set, it stays collectable with its own vanilla drop disabled. The query only
    outputs on entering, and that sequence runs
    once, at spawn: the first pickup is never removed while its own get event writes
    the flag. The query and deletion are copies of the native nodes of the get event
    graph ``event_raw``.

    ``restore_raw``: the native graph that drops its own items and dies
    (``Weapon_PoeCantera.root``). The collected pickup then hands over to its own
    ``DropRef`` (the source's vanilla drop, :func:`vanilla_drop_files`): it reserves
    that drop and requests its death, as that graph does, instead of deleting itself.
    On the first reward only, ``OneShotDropSetDropValid(False)`` disables this
    component before collection. Otherwise ordinary pickup death also emits the
    attached vanilla drop. Later spawns keep it enabled for the hand-over.

    ``mark_on_spawn``: the canonical reward of a minor check, whose short pick-up runs
    no get event that could write ``flag``. The sequence then sets ``flag`` right
    after that check, when the pouch can take the reward then (a full wallet keeps a
    rupee check for later).
    """
    try:
        import ainb
    except ImportError as error:
        raise ValueError('Install ainb==0.2.17 for first-collection rewards.') from error
    sources = source_cache or _AINBTemplates()
    entry = sources.get(raw, faithful=True)
    original = entry['document']

    def build(document):
        # As for the shop AI, the blackboard must be restored after as_dict().
        result = ainb.AINB.from_dict(document)
        result.blackboard = copy.deepcopy(entry['blackboard'])
        return result.to_binary()
    document = copy.deepcopy(original)
    if document['Version'] != 0x408:
        raise ValueError('Unexpected AINB version for the drop AI.')
    nodes = document['Nodes']
    roots = [c['Root Node Index'] for c in document['Commands'] if c['Name'] == 'Root']
    if len(roots) != 1 or nodes[roots[0]]['Node Type'] != 'Element_Simultaneous':
        raise ValueError('Drop AI: root not recognised.')
    starts = [nodes[p['Node Index']] for p in nodes[roots[0]]['Plugs']['Child']
              if nodes[p['Node Index']]['Node Type'] == 'Element_Sequential']
    if len(starts) != 1 or any(prop['Name'] == 'IsLoop' and prop['Default Value']
                               for prop in starts[0]['Properties'].get('Bool', [])):
        raise ValueError('Drop AI: start-up sequence ambiguous or missing.')
    templates = sources.get(event_raw)['document']['Nodes']

    def native(source, name):
        found = [n for n in source if n['Name'] == name]
        if len(found) != 1:
            raise ValueError(f'Drop AI: {name} ambiguous or missing.')
        return copy.deepcopy(found[0])
    query_index, gone_index, noop_index, selector_index = range(len(nodes), len(nodes) + 4)
    query = native(templates, 'QueryGetNonStructGameDataBool')
    query.update({'Node Index': query_index, 'GUID': _guid(flag + '/drop-collected'), 'Queries': [], 'Plugs': {}})
    query['Parameters']['Inputs']['String'] = [_default('GameDataFullName', flag)]
    for prop in query['Properties']['Bool']:
        if prop['Name'] == 'OutputOnlyOnEnter':
            prop['Default Value'] = True
    if restore_raw is None:
        gone = native(templates, 'OneShotGenericDeleteThisActor')
        gone.update({'Node Index': gone_index, 'GUID': _guid(flag + '/drop-delete')})
        for prop in gone['Properties']['Bool']:
            if prop['Name'] == 'IsFade':
                prop['Default Value'] = False
        handover = []
    else:
        restore = sources.get(restore_raw)['document']['Nodes']
        reserve, death = native(restore, 'OneShotDropReserveDropItemCreate'), native(restore, 'OneShotDeathRequestDeath')
        if death['Parameters']['Inputs']['Int'][0].get('Node Index', -1) != -1:
            raise ValueError('Drop AI: the native death request has no fixed reason.')
        reserve_index, death_index = selector_index + 1, selector_index + 2
        gone = copy.deepcopy(starts[0])
        gone.update({'Node Index': gone_index, 'GUID': _guid(flag + '/drop-vanilla'), 'Queries': [],
                     'Attachments': [], 'Flags': [], 'XLink Actions': [],
                     'Plugs': {'Child': [{'Node Index': reserve_index, 'Name': ''},
                                         {'Node Index': death_index, 'Name': ''}]}})
        reserve.update({'Node Index': reserve_index, 'GUID': _guid(flag + '/drop-reserve')})
        death.update({'Node Index': death_index, 'GUID': _guid(flag + '/drop-death')})
        handover = [reserve, death]
    noop_template = next(n for n in nodes if n['Name'] == 'OneshotDoNothing')
    selector_template = next(n for n in nodes if n['Node Type'] == 'Element_BoolSelector')
    noop = copy.deepcopy(noop_template)
    noop.update({'Node Index': noop_index, 'GUID': _guid(flag + '/drop-keep')})
    if restore_raw is not None:
        # Native OneShotDropSetDropValid (Enemy_Leever.brain.root): the same
        # one-shot properties as reserve, with a fixed IsValid Bool input.
        # Do this only on the uncollected branch, before minor rewards mark the
        # flag. The flag must never turn the vanilla drop back on during pickup.
        noop = copy.deepcopy(reserve)
        noop.update({'Node Index': noop_index, 'Name': 'OneShotDropSetDropValid',
                     'GUID': _guid(flag + '/drop-disable'), 'Queries': [], 'Plugs': {}})
        noop['Parameters'] = {'Inputs': {'Bool': [_default('IsValid', False)]}, 'Outputs': {}}
    selector = _bool_selector(selector_template, selector_index, _guid(flag + '/drop-once'),
                              query_index, gone_index, noop_index)
    starts[0]['Plugs']['Child'].insert(0, {'Node Index': selector_index, 'Name': ''})
    nodes.extend([query, gone, noop, selector] + handover)
    if mark_on_spawn:
        can_index, setter_index, skip_index, mark_index = range(len(nodes), len(nodes) + 4)
        can_add = native(templates, 'QueryPouchMgrIsEnablePushToPouch')
        can_add.update({'Node Index': can_index, 'GUID': _guid(flag + '/drop-can-add'), 'Queries': [], 'Plugs': {}})
        can_add['Parameters']['Inputs'] = {'String': [_default('ActorName', mark_on_spawn)]}
        skip = copy.deepcopy(noop_template)
        skip.update({'Node Index': skip_index, 'GUID': _guid(flag + '/drop-mark-later')})
        nodes.extend([can_add, _flag_setter(setter_index, flag, _guid(flag + '/drop-mark')), skip,
                      _bool_selector(selector_template, mark_index, _guid(flag + '/drop-mark-if-room'),
                                     can_index, setter_index, skip_index)])
        starts[0]['Plugs']['Child'].insert(1, {'Node Index': mark_index, 'Name': ''})
    document['Filename'] = filename
    binary = build(document)
    result = ainb.AINB.from_binary(binary).as_dict()
    if result != document:
        raise ValueError('The modified drop AI does not read back identically.')
    if result['Commands'] != original['Commands']:
        raise ValueError('Drop AI commands changed unexpectedly.')
    return binary


def prepare_repeatables(plan, maps):
    """Give repeatable rewards and the shuffled letter their own saved checks.

    Must run BEFORE the normal placement map patches are composed. Original
    placements keep their AP item/spoiler actor; only the physical pickup changes.
    """
    records = []
    for placement in plan['placements']:
        previous = placement['after']
        # A shelf holding a shuffled item (not a native shop refill) is bought once.
        shop = placement.get('source') == 'shop' and previous.startswith(SHOP_PREFIX)
        # The letter's native actor always respawns, and its placement hash has
        # no saved Bool64bitKey. Its replacement needs an independent check flag.
        one_shot = (placement.get('source') in {'skulltula', 'freestanding', 'bossheart'}
                    or (placement.get('source') == 'quest' and placement.get('before') == 'Obj_Arrow_Fire'))
        placed = one_shot or (placement.get('source') == 'quest' and placement.get('before') == 'Obj_Bottle_Letter')
        if placement.get('source') not in REPEATABLE and not shop and not placed:
            continue
        canonical = canonical_of(previous) if is_derived(previous) else WORLD_CANONICAL.get(previous)
        if canonical is None:
            raise ValueError('Repeatable reward without a known native form: ' + previous)
        key = hashlib.sha256(placement['id'].encode('utf-8')).hexdigest()[:16]
        actor = (SHOP_ONCE_PREFIX if shop else 'Obj_RandoOnce_') + key
        flag = 'Rando.Check.' + key
        variants = []
        # One-shot rewards retain their source's native presence/death logic.
        # Their private pickup flag supplies replay protection after loading an
        # older save; a second drop disappears instead of giving vanilla loot.
        for patch in ([] if shop or one_shot else placement['patches']):
            if 'event' in patch or tuple(patch['path'][:1]) != ('Actors',):
                raise ValueError('Repeatable source without a proven physical actor.')
            resource, index = patch['resource'], patch['path'][1]
            original = maps[resource]['root']['Actors'][index]
            # Sources under a condition of their own stay vanilla, but for a native
            # one-shot jar, removed by its own persistent IsCrushed condition.
            presence = original.get('Presence')
            native_once = bool(presence and presence.get('IsNegation') is True
                               and presence.get('FlagName', '').endswith('_IsCrushed'))
            if presence and not native_once:
                raise ValueError('Conditional presence cannot be combined for ' + placement['id'])
            dynamic = original.get('Dynamic') if isinstance(original.get('Dynamic'), dict) else {}
            variants.append({'resource': resource, 'index': index, 'native_once': native_once,
                             'source': original.get('Gyaml'), 'drop_actor': dynamic.get('Drop__DropActor'),
                             'drop_table': dynamic.get('Drop__DropTable')})
        record = {'id': placement['id'], 'actor': actor, 'canonical': canonical,
                  'item': placement.get('item'),
                  'kind': 'shop' if shop else ('placed' if placed else 'pickup'),
                  'underwater': bool(placement.get('underwater')) and not shop,
                  'original_reward_actor': previous, 'flag': flag, 'flag_hash': murmur3(flag),
                  'event_filename': 'RandoOnce_' + key + '.event.root', 'variants': variants}
        native_flags = plan.get('matches', {}).get(placement['id'], {}).get('native_flags')
        if native_flags:
            record['native_flags'] = list(native_flags)
        if shop:
            record['shelves'] = [{'resource': patch['resource'], 'index': patch['path'][1], 'shelf': placement['before'],
                                  'board_hash': int.from_bytes(hashlib.sha256(
                                      f"{placement['id']}/sold-out/{patch['resource']}/{patch['path'][1]}".encode()).digest()[:8],
                                      'little')}
                                 for patch in placement['patches']
                                 if 'event' not in patch and tuple(patch['path'][:1]) == ('Actors',)]
        placement['after'] = actor
        placement['reward_actor'] = previous
        placement['first_collect_flag'] = flag
        records.append(record)
        match = plan.get('matches', {}).get(placement['id'])
        if match is not None:
            match['first_collect_flag'] = flag
    return records


def vanilla_drop_files(record, read_pack):
    """Drop component giving what the record's source drops in the game: ``(files, DropRef)``.

    A source's map entry names the actor it drops (``Drop__DropActor``: a rupee, a
    heart) or, without one, its pack's ``DropRef`` lists its tables, the one named ""
    being its own lottery (pots, grass, crates: hearts, magic, ammo, nuts, bombs;
    rocks and beehives: rupees). The pickup gets that ``DropRef`` (copied from the
    source's pack), or a table of its one actor. ``(None, None)`` without a known
    drop: the collected pickup then deletes itself.
    """
    variants = [v for v in record.get('variants', []) if v.get('source')]
    if not variants:
        return {}, None
    vanilla = variants[0]
    if vanilla.get('drop_table') not in (None, ''):
        return {}, None   # a named table: "None" drops nothing, as deleting the pickup does
    source = read_pack(vanilla['source'])
    if source is None:
        return {}, None
    ref = resolve_components(source, vanilla['source'], byml_codec).get('DropRef')
    if not isinstance(ref, str) or _pack_path(ref) not in source or DROP_BLACKBOARD not in source:
        return {}, None
    files = {DROP_BLACKBOARD: source[DROP_BLACKBOARD]}
    actor = vanilla.get('drop_actor')
    if not actor:
        _copy_ref(source, ref, files, byml_codec)
        path = _pack_path(ref)
        while path in source:
            document = byml_codec.load(source[path])['root']
            for table in document.get('DropTableResourceList', []):
                if _pack_path(table) not in source:
                    return {}, None
                _copy_ref(source, table, files, byml_codec)
                for sub in byml_codec.load(source[_pack_path(table)])['root'].get('SubTableList', []):
                    _copy_ref(source, sub, files, byml_codec)
            parent = document.get('$parent')
            path = _pack_path(parent) if isinstance(parent, str) else None
        return files, ref
    _copy_ref(source, DROP_PARAM_DEFAULT, files, byml_codec)
    name = 'RandoVanilla_' + actor
    sub = f'Work/Drop/DropSubTable/{name}.game__drop__DropSubTable.gyml'
    table = f'Work/Drop/DropTable/{name}.game__drop__DropTable.gyml'
    param = f'Component/DropParam/{name}.game__component__DropParam.bgyml'
    kind = RUPEE_DROP_TYPE if actor.startswith('Obj_Rupee_') else ACTOR_DROP_TYPE
    item = {'BadLuckValueRate': 1.0, 'DropActorName': f'Work/Actor/{actor}.engine__actor__ActorParam.gyml',
            'DropCreateCount': byml_codec.U32(1), 'DropProbability': 100, 'IsReplace': True,
            'MostDepletedResource': [], 'Type': byml_codec.U32(kind)}
    for path, root in ((_pack_path(sub), {'Items': [item]}),
                       (_pack_path(table), {'DropTableName': '', 'SubTableList': [sub]}),
                       (param, {'$parent': DROP_PARAM_DEFAULT, 'DropTableResourceList': [table]})):
        files[path] = byml_codec.dump({'endian': '<', 'version': 7, 'root': root})
    return files, '?' + param


class _AliasTemplates:
    """Generation-local immutable row prototypes, without copying whole RSDBs.

    add_rsdb_rows reads only the canonical/template rows and appends its result.
    Building those rows in a minimal scratch table is equivalent to removing an
    existing standard row from a full copy, while avoiding quadratic deep copies
    as hundreds of independent check actors are added.
    """
    LIMIT = 256

    def __init__(self, tables):
        self.tables = tables
        self.index = {name: {row['__RowId']: row for row in rows} for name, rows in tables.items()}
        self.cache = OrderedDict()

    def append(self, standard, actor):
        from ootrr_full.game.item_forms import (canonical_of, is_world_derived, world_template,
                                               WORLD_TEMPLATE, SHOP_TEMPLATE)
        if any(actor in rows for rows in self.index.values()):
            raise ValueError('A first-collection actor row already exists: ' + actor)
        prototypes = self.cache.get(standard)
        if prototypes is None:
            canonical = canonical_of(standard)
            template = world_template(standard) if is_world_derived(standard) else SHOP_TEMPLATE
            needed = {canonical, template, WORLD_TEMPLATE, SHOP_TEMPLATE}
            scratch = {name: [rows[key] for key in sorted(needed) if key in rows]
                       for name, rows in self.index.items()}
            add_rsdb_rows(scratch, [standard])
            prototypes = {name: copy.deepcopy(next(row for row in rows if row['__RowId'] == standard))
                          for name, rows in scratch.items()}
            self.cache[standard] = prototypes
            if len(self.cache) > self.LIMIT:
                self.cache.popitem(last=False)
        else:
            self.cache.move_to_end(standard)
        for name, prototype in prototypes.items():
            row = copy.deepcopy(prototype)
            row['__RowId'] = actor
            self.tables[name].append(row)
            self.index[name][actor] = row

    def finish(self):
        for rows in self.tables.values():
            rows.sort(key=lambda row: row['__RowId'])


def build_repeatable_packs(records, read_pack, read_raw, tables, progress=None, *, cache_templates=True):
    """Build unique pickups and event graphs, and append their RSDB rows.

    ``read_pack`` sees normal/generated soul packs. ``read_raw`` returns raw
    game resources. ``tables`` are current RSDB row arrays, edited in place.
    Returns new-resource mapping of path -> (raw, compression_template_path).
    Saved Bool flags must be added separately by the caller (8 bytes each).
    """
    if not records:
        return {}
    event = shop_event = None
    new = {}
    aliases = _AliasTemplates(tables) if cache_templates else None
    alias_actor = aliases.append if aliases is not None else lambda standard, actor: _alias_rows(tables, standard, actor)
    native_pouches = {row['__RowId']: row for row in tables.get('PouchActorInfo', [])}
    packs = OrderedDict()
    ai_templates = _AINBTemplates() if cache_templates else None
    presentations = {}
    exact_quantities = {}

    def standard_pack(standard):
        if not cache_templates:
            return build_pack(standard, read_pack, byml_codec)
        cached = packs.get(standard)
        if cached is None:
            # Only immutable SARC bytes and template names are cached. Each
            # actor below still gets a new archive mapping and parsed documents.
            cached = build_pack(standard, read_pack, byml_codec)
            packs[standard] = cached
            if len(packs) > 128:
                packs.popitem(last=False)
        else:
            packs.move_to_end(standard)
        return cached

    for index, record in enumerate(records):
        if progress and index % 20 == 0:
            progress(f'Building first-collection actors: {index + 1}/{len(records)}')
        if record.get('kind') == 'shop':
            standard = record['original_reward_actor']
            raw, template = standard_pack(standard)
            files = sarc(raw)
            document = byml_codec.load(files.pop(f'Actor/{standard}.engine__actor__ActorParam.bgyml'))
            if SHOP_AI_MEMBER not in files:
                raise ValueError('Shop item AI missing from the shop model.')
            root = record['actor'] + '.root'
            ai_info = f'AI/AIInfo/{record["actor"]}.engine__actor__AIInfo.bgyml'
            if shop_event is None:
                shop_event = sarc(read_raw(EVENT_PACK))[SHOP_EVENT_MEMBER]
            files['AI/' + root + '.ainb'] = instrument_shop_ai(files[SHOP_AI_MEMBER], record['flag'], root, shop_event,
                                                            source_cache=ai_templates)
            files[ai_info] = byml_codec.dump({'endian': '<', 'version': 7,
                                              'root': {'RootAIRef': 'Work/AI/Root/' + root + '.ain'}})
            document['root']['Components']['AIInfoRef'] = '?' + ai_info
            files[f'Actor/{record["actor"]}.engine__actor__ActorParam.bgyml'] = byml_codec.dump(document)
            new['Pack/Actor/' + record['actor'] + '.pack.zs'] = (byml_codec.build_sarc(files), template)
            alias_actor(standard, record['actor'])
            continue
        if event is None:
            global_ai = sarc(read_raw(EVENT_PACK))
            event, drop_ai, handover_ai = global_ai[EVENT_MEMBER], global_ai[DROP_AI_MEMBER], global_ai[HANDOVER_AI_MEMBER]
        # Dropped by its source: a falling pickup, not the standing token; it glows
        # under water (item_forms.GLOW_ACTOR).
        standard = DROP_PREFIX + record['canonical']
        if record.get('underwater'):
            standard = underwater_actor(standard)
        raw, template = standard_pack(standard)
        files = sarc(raw)
        old_path = f'Actor/{standard}.engine__actor__ActorParam.bgyml'
        document = byml_codec.load(files.pop(old_path))
        components = document['root']['Components']
        pouch_path = components['PouchContentRef'][1:]
        pouch = byml_codec.load(files[pouch_path])
        display = pickup_pouch_settings(record['canonical'], native_pouches.get(record['canonical']))
        pouch['root'].update(display)
        presentations[record['actor']] = next(name for name in ('Small', 'Medium', 'Large')
                                              if murmur3(name) == int(display['GetType']))
        if record.get('kind') == 'placed':
            # Like the original bottle, this check always plays its get event,
            # even for a rupee. Record collection after the pouch push, never on
            # spawning a reward the player has not reached underwater yet.
            pouch['root']['PlayGetEventManyTimes'] = True
        # The PouchActor remains the canonical reward: no unique inventory item
        # or duplicate bundle is introduced just to track a check.
        files[pouch_path] = byml_codec.dump(pouch)
        event_name = record['event_filename']
        event_member = 'AI/' + event_name + '.ainb'
        event_param = f'Component/EventPerformerParam/{record["actor"]}.engine__component__EventPerformerParam.bgyml'
        files[event_param] = byml_codec.dump({'endian': '<', 'version': 7, 'root': {
            '$parent': 'Work/Component/EventPerformerParam/PouchContent_PickUpItem.engine__component__EventPerformerParam.gyml',
            'AlwaysEventMember': True, 'UseEventUniqueAin': True,
            'EventUniqueAin': 'Work/AI/Root/Event/' + event_name + '.ain'}})
        components['EventPerformerRef'] = '?' + event_param
        also = (SOUL_FLAG_PREFIX + record['canonical'],) if record['canonical'].startswith('Item_Soul_') else ()
        also += tuple(record.get('native_flags', ()))
        grant = exact_ammunition_grant(record['canonical'], record.get('item'))
        if grant is not None:
            exact_quantities[record['actor']] = grant[1]
        # Every reward commits only after its actual native pouch push. The
        # repeated Small get callback handles ordinary consumables too.
        files[event_member] = instrument_pickup_event(event, record['flag'], event_name, record['canonical'], also,
                                                      skip_if_collected=True, source_cache=ai_templates, grant=grant,
                                                      capacity=ammunition_capacity(record['canonical'],
                                                                                   native_pouches.get(record['canonical'])))
        # Once the check is collected, a respawned source drops what it drops in the
        # game: the pickup hands over to the source's own drop.
        behaviour = resolve_components({**files, old_path: byml_codec.dump(document)}, standard, byml_codec)
        if behaviour.get('AIInfoRef') != DROP_AI_INFO:
            raise ValueError('First-collection pickup without the native drop AI: ' + record['actor'])
        drop_files, drop_ref = vanilla_drop_files(record, read_pack)
        files.update(drop_files)
        if drop_ref is not None:
            components['DropRef'] = drop_ref
        root = record['actor'] + '.root'
        ai_info = f'AI/AIInfo/{record["actor"]}.engine__actor__AIInfo.bgyml'
        files['AI/' + root + '.ainb'] = instrument_drop_ai(
            drop_ai, record['flag'], root, event, mark_on_spawn=None,
            restore_raw=handover_ai if drop_ref is not None else None, source_cache=ai_templates)
        files[ai_info] = byml_codec.dump({'endian': '<', 'version': 7,
                                          'root': {'RootAIRef': 'Work/AI/Root/' + root + '.ain'}})
        components['AIInfoRef'] = '?' + ai_info
        files[f'Actor/{record["actor"]}.engine__actor__ActorParam.bgyml'] = byml_codec.dump(document)
        new['Pack/Actor/' + record['actor'] + '.pack.zs'] = (byml_codec.build_sarc(files), template)
        alias_actor(standard, record['actor'])
    pouch_rows = {row['__RowId']: row for row in tables.get('PouchActorInfo', [])}
    for actor, kind in presentations.items():
        pouch_rows[actor]['PouchGetType'] = kind
    for actor, amount in exact_quantities.items():
        # The native central pickup label reads the physical actor's RSDB bundle
        # count. Keep that label consistent with the exact pouch grant above.
        pouch_rows[actor]['BundleActorNum'] = amount
    if aliases is not None:
        aliases.finish()
    return new


def _alias_rows(tables, standard, actor):
    """RSDB rows of ``actor``: those of the derived reward ``standard``, renamed."""
    # Reuse the existing derived-row builder under a temporary name, then
    # rename only those freshly appended rows. Their reward metadata stays.
    existing = {name: {row['__RowId'] for row in rows} for name, rows in tables.items()}
    if any(standard in ids for ids in existing.values()):
        # A standard derived reward might already be needed by another
        # location. Build rows in an isolated copy and copy only the alias.
        scratch = {name: [copy.deepcopy(row) for row in rows if row['__RowId'] != standard]
                   for name, rows in tables.items()}
        add_rsdb_rows(scratch, [standard])
        for name, rows in scratch.items():
            row = copy.deepcopy(next(row for row in rows if row['__RowId'] == standard))
            row['__RowId'] = actor
            tables[name].append(row)
    else:
        add_rsdb_rows(tables, [standard])
        for rows in tables.values():
            row = next(row for row in rows if row['__RowId'] == standard)
            row['__RowId'] = actor
    for rows in tables.values():
        rows.sort(key=lambda row: row['__RowId'])


SOLD_OUT_BOARD = 'Shop_Board_SoldOut'
BOARD_BACK = 0.25   # vanilla sold-out boards sit about this far behind their shelf


def add_sold_out_board(actors, index, ident):
    """Put a native ``Shop_Board_SoldOut`` behind shelf ``actors[index]``, linked to it.

    As in the Kokiri shop before the Deku Tree: the shelf's AI tells the board
    linked by ``Reference`` whether it is sold out (board shown or hidden).
    """
    shelf = actors[index]
    boards = {int(actor['Hash']) for actor in actors if actor.get('Gyaml') == SOLD_OUT_BOARD}
    if any(link.get('Name') == 'Reference' and int(link.get('Dst', 0)) in boards for link in shelf.get('Links', [])):
        return None   # a native one already (Kokiri shop before the Deku Tree)
    used = {int(actor['Hash']) for actor in actors if 'Hash' in actor}
    if ident in used:
        raise ValueError('Sold out board hash collision.')
    rotate = list(shelf.get('Rotate', [0.0, 0.0, 0.0]))
    x, y, z = shelf['Translate']
    yaw = rotate[1]
    def f32(value):   # as stored in the map, so that a replay compares equal
        return struct.unpack('<f', struct.pack('<f', value))[0]
    board = {'Gyaml': SOLD_OUT_BOARD, 'Hash': byml_codec.U64(ident),
             'Translate': [f32(x - math.sin(yaw) * BOARD_BACK), y, f32(z - math.cos(yaw) * BOARD_BACK)]}
    if 'Rotate' in shelf:
        board['Rotate'] = rotate
    if 'SRTHash' in shelf:
        board['SRTHash'] = shelf['SRTHash']
    if 'Presence' in shelf:   # present with its shelf (Kokiri full or short stock)
        board['Presence'] = copy.deepcopy(shelf['Presence'])
    shelf.setdefault('Links', []).append({'Dst': byml_codec.U64(ident), 'Gyaml': 'Reference', 'Name': 'Reference',
                                          'Src': shelf['Hash']})
    actors.append(board)
    return board


def shop_stock_edits(records, maps):
    """{shopkeeper actor: {ShopItemIndex: vanilla shelf actor}} of the shuffled shelves.

    The shopkeeper is the actor whose ``ForSale`` link reaches the shelf.
    """
    edits = {}
    for record in records:
        for shelf in record.get('shelves', []):
            actors = maps[shelf['resource']]['root']['Actors']
            target = actors[shelf['index']]
            sellers = {actor['Gyaml'] for actor in actors for link in actor.get('Links', [])
                       if link.get('Name') == 'ForSale' and link.get('Dst') == target['Hash']}
            if not sellers:
                raise ValueError('Shop shelf without a shopkeeper: ' + record['id'])
            slot = (target.get('Dynamic') or {}).get('ShopItemIndex', 0)
            for seller in sellers:
                old = edits.setdefault(seller, {}).setdefault(slot, shelf['shelf'])
                if old != shelf['shelf']:
                    raise ValueError(f'Two shelves share slot {slot} of {seller}.')
    return edits


def limit_shop_stock(pack_raw, slots):
    """Shopkeeper pack whose ShopParam goods at ``slots`` are sold once (StockNum 1).

    ``slots`` maps ShopItemIndex -> vanilla shelf actor; a good is only changed
    if its Actor is that shelf. Returns (new SARC bytes, changed slots).
    """
    files = dict(sarc(pack_raw))
    changed = set()
    for name in sorted(files):
        if not (name.startswith('Component/ShopParam/') and name.endswith('.bgyml')):
            continue
        document = byml_codec.load(files[name])
        goods = document['root'].get('GoodsList', [])
        touched = False
        for slot, shelf in slots.items():
            if slot < len(goods) and goods[slot].get('Actor', '').endswith(
                    '/' + shelf + '.engine__actor__ActorParam.gyml'):
                goods[slot]['StockNum'] = 1
                changed.add(slot)
                touched = True
        if touched:
            files[name] = byml_codec.dump(document)
    missing = set(slots) - changed
    if missing:
        raise ValueError(f'Shop goods not found for slots {sorted(missing)}.')
    return byml_codec.build_sarc(files), sorted(changed)


def patch_repeatable_sources(records, maps, raw_maps):
    """Add the sold out boards of shuffled shelves. Returns the changed maps.

    Shuffled pots, rocks and other sources keep their map entry as it is, but for
    their drop: no Presence and no vanilla copy. The game remembers a broken source
    by its hash (its Bool64bitKey) until the scene changes; a copy under another
    hash, or a source under a Presence condition, came back while the area stayed loaded.
    The texture adapter later replaces Gyaml while preserving these native fields.
    """
    documents = {}
    for record in records:
        for shelf in record.get('shelves', []):
            resource = shelf['resource']
            if resource not in documents:
                documents[resource] = byml_codec.load(raw_maps.get(resource, maps[resource]['raw']))
            add_sold_out_board(documents[resource]['root']['Actors'], shelf['index'], shelf['board_hash'])
    for resource, document in documents.items():
        raw_maps[resource] = byml_codec.dump(document)
    return sorted(documents)



def register_repeatable_flags(raw, records):
    """Add the saved collection flag of each record (an 8-byte typed Bool).

    Returns (raw_GameData, summary). No names or rewards are stored in saves.
    """
    if not records:
        return raw, {'bools': [], 'saved_bytes_added': 0}
    document = byml_codec.load(raw)
    data, meta = document['root']['Data'], document['root']['MetaData']
    previous_saved_size = meta['AllDataSaveSize']
    known = {int(e['Hash']) for entries in data.values() for e in entries if 'Hash' in e}
    bool_template = next((e for e in data['Bool'] if e.get('SaveFileIndex') == 0
                          and e.get('ResetTypeValue') == 8 and e.get('DefaultValue') is False), None)
    if bool_template is None:
        raise ValueError('Saved collection flag template missing.')
    added_bool = []
    for record in records:
        value = int(record['flag_hash'])
        if value != murmur3(record['flag']) or value in known:
            raise ValueError('Collection flag collision: ' + record['flag'])
        entry = copy.deepcopy(bool_template)
        entry['Hash'] = byml_codec.U32(value)
        data['Bool'].append(entry)
        known.add(value)
        index = entry['SaveFileIndex']
        meta['SaveDataSize'][index] += 8
        meta['SaveDataOffsetPos'][index] += 8
        meta['AllDataSaveSize'] += 8
        meta['AllDataSaveOffset'] += 8
        added_bool.append(value)
    return byml_codec.dump(document), {'bools': added_bool,
                                       'saved_bytes_added': meta['AllDataSaveSize'] - previous_saved_size}
