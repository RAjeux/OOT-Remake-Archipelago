"""Native, platform-independent safety gate for externally signalled receipts.

Queries and parameters are taken from the supported game's actual AI resources.
The Player brain is a single native success node in all three supported packs;
only that exact trivial brain is extended. Unknown brains and missing native
query templates are rejected. The player's action/scheduler graphs are untouched.

Player AI publishes a transient readiness flag. The mailbox sequence rechecks
readiness, pause and loading immediately before requesting the item event, so an
external request arriving during a tunnel or fishing waits rather than cancels
the player's action. Our existing C game-thread safety guards remain independent.
"""
import copy
import hashlib
from pathlib import Path
import re
import uuid


PLAYER_PACKS = tuple(f"Pack/Actor/{name}.pack.zs" for name in ("Player_Base", "Player_Child", "Player_Adult"))
BRAIN = "AI/Player.brain.root.ainb"
GLOBAL_PACK = "Pack/AI.Global.Product.111.pack.zs"
NAVI_PACK = "Pack/Actor/Npc_Navi.pack.zs"
MAIN_UPDATE = "Sequence/MainUpdate.module.ainb"
EVENT_TEMPLATE = "Sequence/AfterChangeBanc.module.ainb"
GAMEDATA = "GameData/GameDataList.Product.110.byml.zs"
REST = "System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs"
PAUSE = "Sequence_IsPause"
LOADING = "Sequence_IsLoadingBanc"
SAFE_VERBS = frozenset((0x01, 0x02, 0x03, 0x04, 0x15, 0x16, 0x28, 0x41, 0x42, 0xD1))


def readiness_name(token):
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{64}", token):
        raise ValueError("Invalid room token for native readiness.")
    return "Archipelago.Ready." + token


def can_receive(verb, fishing=False, paused=False, loading=False, minigame=False):
    """Pure reference for the AI whitelist, including fail-closed unknown states."""
    return type(verb) is int and verb in SAFE_VERBS and not (fishing or paused or loading or minigame)


def _guid(name, index):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"ootrr-ap/readiness/{name}/{index}"))


def _default(name, value):
    return {"Name": name, "Default Value": value, "Node Index": -1,
            "Output Index": 0, "Flags": ["Uses Default"]}


def _from_query(name, node, kind="Bool"):
    return {"Name": name, "Default Value": 0 if kind == "Int" else False,
            "Node Index": node, "Output Index": 0, "Flags": []}


def _node(kind, index, flag, *, name="", inputs=None, outputs=None, queries=(), properties=None):
    return {"Node Type": kind, "Node Index": index, "Name": name,
            "GUID": _guid(flag, index), "Flags": [], "Queries": list(queries),
            "Attachments": [], "Properties": properties or {},
            "Parameters": {"Inputs": inputs or {}, "Outputs": outputs or {}},
            "XLink Actions": [], "Plugs": {}}


def _write(document):
    from ootrr_full.patching.ap_mailbox import ainb_to_binary
    import ainb
    result = ainb_to_binary(document)
    if ainb.AINB.from_binary(result).as_dict() != document:
        raise ValueError("Native readiness graph failed round-trip verification.")
    return result


def _template(files, name):
    import ainb
    for path, raw in files.items():
        if path.endswith(".ainb") and name.encode() in raw:
            for node in ainb.AINB.from_binary(raw).as_dict()["Nodes"]:
                if node["Name"] == name:
                    return copy.deepcopy(node)
    raise ValueError("Native readiness query not found: " + name)


def native_templates(global_files, navi_files):
    names = ("QueryPlayerGetCurrentActionVerb", "QueryPlayerIsEquipMiniGameItem",
             "QueryGetNonStructGameDataBool", "OneShotSetNonStructGameDataBool")
    result = {name: _template(global_files, name) for name in names}
    result["QueryNaviIsWaitPlayerStateDrawnFishingRod"] = _template(
        navi_files, "QueryNaviIsWaitPlayerStateDrawnFishingRod")
    action = result["QueryPlayerGetCurrentActionVerb"]
    if (action["Parameters"]["Inputs"].get("Int", [{}])[0].get("Name") != "ActionSlot"
            or action["Parameters"]["Outputs"].get("Int", [{}])[0].get("Name") != "CurrentActionVerb"):
        raise ValueError("Unexpected native action-verb query.")
    for name in ("QueryPlayerIsEquipMiniGameItem", "QueryNaviIsWaitPlayerStateDrawnFishingRod"):
        if result[name]["Parameters"]["Inputs"]:
            raise ValueError("Unexpected native readiness query inputs: " + name)
    return result


def patch_player_brain(raw, flag, templates):
    import ainb
    original = ainb.AINB.from_binary(raw).as_dict()
    nodes = original["Nodes"]
    if (original.get("Category") != "AI" or original.get("Filename") != "Player.brain.root"
            or len(nodes) != 1 or nodes[0]["Name"] != "ExecuteGenericSetResultSuccess"
            or nodes[0]["Parameters"] != {"Inputs": {}, "Outputs": {}}
            or nodes[0]["Plugs"] or nodes[0]["Queries"] or nodes[0]["Attachments"]
            or len(original.get("Commands", [])) != 1
            or original["Commands"][0].get("Root Node Index") != 0):
        raise ValueError("The Player brain is not the supported trivial native graph.")
    document = copy.deepcopy(original)
    nodes = document["Nodes"] = []
    # Root -> action whitelist -> rod check -> minigame check -> pause -> load.
    # Every failure writes false. The native setters run every frame, including
    # while the same branch stays selected (there is no timing-only retry).
    action = copy.deepcopy(templates["QueryPlayerGetCurrentActionVerb"])
    action.update({"Node Index": 1, "GUID": _guid(flag, 1), "Plugs": {}, "Queries": []})
    action["Parameters"]["Inputs"]["Int"][0] = _default("ActionSlot", 0)
    root = _node("Element_S32Selector", 0, flag, inputs={"Int": [_from_query("Input", 1, "Int")]}, queries=(1,))
    root["Flags"] = ["Is Root Node"]
    root["Plugs"] = {"Int": [{"Node Index": 1, "Name": "Input", "Unknown": 0, "Default Value": 0}],
                     "Child": [{"Node Index": 2, "Name": "", "Condition": verb} for verb in sorted(SAFE_VERBS)]
                              + [{"Node Index": 11, "Name": "", "Is Default": True}]}
    nodes.extend((root, action))
    checks = (("QueryNaviIsWaitPlayerStateDrawnFishingRod", None),
              ("QueryPlayerIsEquipMiniGameItem", None),
              ("QueryGetNonStructGameDataBool", PAUSE),
              ("QueryGetNonStructGameDataBool", LOADING))
    for number, (name, game_flag) in enumerate(checks):
        selector_index, query_index = 2 + number * 2, 3 + number * 2
        query = copy.deepcopy(templates[name])
        query.update({"Node Index": query_index, "GUID": _guid(flag, query_index), "Queries": [], "Plugs": {}})
        if game_flag:
            query["Parameters"]["Inputs"] = {
                "Int": [_default("GameDataIndex", -1)], "Bool": [_default("IsDirect", True)],
                "String": [_default("GameDataFullName", game_flag)]}
        selector = _node("Element_BoolSelector", selector_index, flag,
                         inputs={"Bool": [_from_query("Input", query_index)]}, queries=(query_index,))
        selector["Plugs"] = {"Generic": [{"Node Index": query_index, "Name": "Input", "Unknown 1": 0, "Unknown 2": 0}],
                             "Child": [{"Node Index": 11, "Name": "True"},
                                       {"Node Index": selector_index + 2, "Name": "False"}]}
        nodes.extend((selector, query))
    for index, value in ((10, True), (11, False)):
        setter = copy.deepcopy(templates["OneShotSetNonStructGameDataBool"])
        setter.update({"Node Index": index, "GUID": _guid(flag, index), "Queries": [], "Plugs": {}, "Flags": []})
        setter["Properties"] = {"Bool": [{"Name": "ExecuteEveryFrame", "Default Value": True, "Flags": []}]}
        setter["Parameters"] = {"Inputs": {"Int": [_default("GameDataIndex", -1)],
            "Bool": [_default("Value", value)], "String": [_default("GameDataFullName", flag)]}, "Outputs": {}}
        nodes.append(setter)
    return _write(document)


def add_transient_flag(raw, flag):
    from ootrr_full.formats import byml_codec as codec
    from ootrr_full.patching.soul_adapter import murmur3
    document = codec.load(raw)
    data = document["root"]["Data"]
    key = murmur3(flag)
    if any(entry.get("Hash") == key for entries in data.values() for entry in entries):
        raise ValueError("Native readiness flag already exists or collides.")
    pause = next((entry for entry in data["Bool"] if entry.get("Hash") == murmur3(PAUSE)), None)
    if pause is None or pause.get("SaveFileIndex") != -1 or pause.get("ResetTypeValue") != 0:
        raise ValueError("Native transient Bool template was not found.")
    entry = copy.deepcopy(pause)
    entry.update(Hash=codec.U32(key), DefaultValue=False)
    data["Bool"].append(entry)
    return codec.dump(document)


def patch_mailbox_gate(raw, flag, pending="RandoAP.Pending", *, event_query):
    """Gate the exact mailbox branch, retaining requests while Link is busy."""
    import ainb
    document = ainb.AINB.from_binary(raw).as_dict()
    nodes = document["Nodes"]
    pending_queries = [n["Node Index"] for n in nodes if n["Name"] == "SeqQueryGetNonStructGameDataBool"
                       and any(p.get("Default Value") == pending
                               for p in n["Parameters"]["Inputs"].get("String", []))]
    if not pending_queries:
        if any(n["Name"] == "SeqOneShotRequestEvent" and any(
                p.get("Default Value", "").startswith("RandoAP_")
                for p in n["Parameters"]["Inputs"].get("String", [])) for n in nodes):
            raise ValueError("An unsupported legacy Archipelago mailbox cannot be gated safely.")
        # Solo or wholly local placement has no remote mailbox to execute.
        return raw
    selectors = [n for n in nodes if n["Node Type"] == "Element_BoolSelector"
                 and any(p.get("Node Index") in pending_queries
                         for p in n["Parameters"]["Inputs"].get("Bool", []))]
    if len(selectors) != 1:
        raise ValueError("The supported shared Archipelago mailbox was not found.")
    selector = selectors[0]
    target = selector["Node Index"]
    parents = [(n, p) for n in nodes for p in n.get("Plugs", {}).get("Child", []) if p["Node Index"] == target]
    if len(parents) != 1:
        raise ValueError("The shared mailbox has an ambiguous execution parent.")
    idle = next((n["Node Index"] for n in nodes if n["Name"] == "SeqExecuteGenericDummyAction"), None)
    if idle is None:
        raise ValueError("The mailbox has no native idle action.")
    query_template = next(n for n in nodes if n["Name"] == "SeqQueryGetNonStructGameDataBool")
    setter_template = next((n for n in nodes if n["Name"] == "SeqOneShotSetNonStructGameDataBool"), None)
    if setter_template is None:
        raise ValueError("The mailbox has no native flag setter.")
    first = len(nodes)
    clear_index = first + 8
    parents[0][1]["Node Index"] = first + 1
    # Check all three here, in the game's sequence, rather than trusting the
    # interval between an external memory read and its signal write.
    if (event_query.get("Name") != "SeqQueryIsPlayingMainEvent"
            or not any(p.get("Name") == "IsPlayingMainEvent"
                       for p in event_query.get("Parameters", {}).get("Outputs", {}).get("Bool", []))):
        raise ValueError("The native main-event query template is invalid.")
    for number, (name, wanted) in enumerate(((flag, True), (PAUSE, False), (LOADING, False), (None, False))):
        query_index, branch_index = first + number * 2, first + number * 2 + 1
        next_index = first + (number + 1) * 2 + 1 if number < 3 else target
        query = copy.deepcopy(query_template if name else event_query)
        query.update({"Node Index": query_index, "GUID": _guid(flag + "/sequence", query_index), "Queries": [], "Plugs": {}})
        query["Parameters"]["Inputs"] = ({"Int": [_default("GameDataIndex", -1)],
            "Bool": [_default("IsDirect", True)], "String": [_default("GameDataFullName", name)]} if name else {
                "Bool": [_default("IsIncludePrepare", True), _default("IsIncludeRequest", True)]})
        branch = copy.deepcopy(selector)
        branch.update({"Node Index": branch_index, "GUID": _guid(flag + "/sequence", branch_index), "Queries": [query_index]})
        branch["Parameters"] = {"Inputs": {"Bool": [_from_query("Input", query_index)]}, "Outputs": {}}
        branch["Plugs"] = {"Generic": [{"Node Index": query_index, "Name": "Input", "Unknown 1": 0, "Unknown 2": 0}],
            "Child": [{"Node Index": next_index if wanted else clear_index, "Name": "True"},
                      {"Node Index": idle if wanted else next_index, "Name": "False"}]}
        nodes.extend((query, branch))
    # Loading and pause invalidate the previous player's publication even if
    # its brain no longer ticks. After loading, only a fresh Player AI tick can
    # restore readiness. This flag is not imported from the selected save.
    clear = copy.deepcopy(setter_template)
    clear.update({"Node Index": clear_index, "GUID": _guid(flag + "/clear", clear_index), "Queries": [], "Plugs": {}})
    clear["Properties"] = {"Bool": [{"Name": "ExecuteEveryFrame", "Default Value": True, "Flags": []}]}
    clear["Parameters"] = {"Inputs": {"Int": [_default("GameDataIndex", -1)],
        "Bool": [_default("Value", False)], "String": [_default("GameDataFullName", flag)]}, "Outputs": {}}
    nodes.append(clear)
    return _write(document)


def patch_external_session_gate(raw, flag, pending="RandoAP.Pending"):
    """Require authenticated external state after each load before native dispatch."""
    if not isinstance(flag, str) or not re.fullmatch(r'Archipelago\.ExternalSessionReady\.[0-9a-f]{64}', flag):
        raise ValueError('Invalid external session readiness flag.')
    import ainb
    document = ainb.AINB.from_binary(raw).as_dict()
    nodes = document['Nodes']
    queries = {node['Node Index'] for node in nodes if node['Name'] == 'SeqQueryGetNonStructGameDataBool'
               and any(value.get('Default Value') == pending
                       for value in node['Parameters']['Inputs'].get('String', ()))}
    selectors = [node for node in nodes if node['Node Type'] == 'Element_BoolSelector'
                 and any(value.get('Node Index') in queries
                         for value in node['Parameters']['Inputs'].get('Bool', ()))]
    if len(selectors) != 1:
        raise ValueError('External recovery requires the shared native mailbox.')
    target = selectors[0]['Node Index']
    parents = [(node, plug) for node in nodes for plug in node.get('Plugs', {}).get('Child', ())
               if plug['Node Index'] == target]
    if len(parents) != 1:
        raise ValueError('External session mailbox parent is ambiguous.')
    if any(node['Name'] == 'SeqQueryGetNonStructGameDataBool' and any(
            value.get('Default Value') == flag for value in node['Parameters']['Inputs'].get('String', ()))
           for node in nodes):
        raise ValueError('The external session mailbox is already gated.')
    # Put the session wrapper before an existing readiness wrapper too. Its
    # loading/pause reset must run even when normal player readiness is false.
    while parents[0][0]['Node Type'] == 'Element_BoolSelector':
        wrapper = parents[0][0]
        known = all(nodes[index]['Name'] == 'SeqQueryIsPlayingMainEvent' or (
            nodes[index]['Name'] == 'SeqQueryGetNonStructGameDataBool' and any(
                value.get('Default Value') in (PAUSE, LOADING)
                or str(value.get('Default Value', '')).startswith('Archipelago.Ready.')
                for value in nodes[index]['Parameters']['Inputs'].get('String', ())))
                    for index in wrapper.get('Queries', ()))
        if not known or not wrapper.get('Queries'):
            raise ValueError('Unknown native mailbox readiness wrapper.')
        target = wrapper['Node Index']
        parents = [(node, plug) for node in nodes for plug in node.get('Plugs', {}).get('Child', ())
                   if plug['Node Index'] == target]
        if len(parents) != 1:
            raise ValueError('External session readiness parent is ambiguous.')
    first, clear_index = len(nodes), len(nodes) + 6
    query_template = next(node for node in nodes if node['Name'] == 'SeqQueryGetNonStructGameDataBool')
    idle = next(node['Node Index'] for node in nodes if node['Name'] == 'SeqExecuteGenericDummyAction')
    parents[0][1]['Node Index'] = first + 1
    for number, (name, wanted) in enumerate(((PAUSE, False), (LOADING, False), (flag, True))):
        query_index, branch_index = first + 2 * number, first + 2 * number + 1
        next_index = first + 2 * (number + 1) + 1 if number < 2 else target
        query = copy.deepcopy(query_template)
        query.update({'Node Index': query_index, 'GUID': _guid(flag, query_index), 'Queries': [], 'Plugs': {}})
        query['Parameters']['Inputs'] = {'Int': [_default('GameDataIndex', -1)],
            'Bool': [_default('IsDirect', True)], 'String': [_default('GameDataFullName', name)]}
        branch = copy.deepcopy(selectors[0])
        branch.update({'Node Index': branch_index, 'GUID': _guid(flag, branch_index), 'Queries': [query_index]})
        branch['Parameters'] = {'Inputs': {'Bool': [_from_query('Input', query_index)]}, 'Outputs': {}}
        branch['Plugs'] = {'Generic': [{'Node Index': query_index, 'Name': 'Input', 'Unknown 1': 0, 'Unknown 2': 0}],
            'Child': [{'Node Index': next_index if wanted else clear_index, 'Name': 'True'},
                      {'Node Index': idle if wanted else next_index, 'Name': 'False'}]}
        nodes.extend((query, branch))
    clear = copy.deepcopy(next(node for node in nodes if node['Name'] == 'SeqOneShotSetNonStructGameDataBool'))
    clear.update({'Node Index': clear_index, 'GUID': _guid(flag, clear_index), 'Queries': [], 'Plugs': {}})
    clear['Properties'] = {'Bool': [{'Name': 'ExecuteEveryFrame', 'Default Value': True, 'Flags': []}]}
    clear['Parameters'] = {'Inputs': {'Int': [_default('GameDataIndex', -1)],
        'Bool': [_default('Value', False)], 'String': [_default('GameDataFullName', flag)]}, 'Outputs': {}}
    nodes.append(clear)
    return _write(document)


def prepare_external_readiness(romfs, mod, token):
    """Patch one staged mod and return the exact readiness metadata."""
    from ootrr_full.formats import byml_codec as codec
    from ootrr_full.formats.inspect_resources import sarc
    from ootrr_full.game.resource_allocations import grow_resources
    from .mod_codec import Codec
    flag = readiness_name(token)
    romfs, mod = Path(romfs), Path(mod)
    def source(path):
        overlay = mod / path
        return (overlay if overlay.is_file() else romfs / path).read_bytes()
    compression = Codec(source("Pack/ZsDic.pack.zs"))
    def read(path):
        raw = source(path)
        return compression.decode(raw) if path.endswith(".zs") else raw
    templates = native_templates(sarc(read(GLOBAL_PACK)), sarc(read(NAVI_PACK)))
    modified = {}
    for path in PLAYER_PACKS:
        files = dict(sarc(read(path)))
        files[BRAIN] = patch_player_brain(files[BRAIN], flag, templates)
        modified[path] = codec.build_sarc(files)
    modified[GAMEDATA] = add_transient_flag(read(GAMEDATA), flag)
    import ainb
    event_query = next((n for n in ainb.AINB.from_binary(read(EVENT_TEMPLATE)).as_dict()["Nodes"]
                        if n["Name"] == "SeqQueryIsPlayingMainEvent"), None)
    if event_query is None:
        raise ValueError("The native main-event query was not found.")
    modified[MAIN_UPDATE] = patch_mailbox_gate(read(MAIN_UPDATE), flag, event_query=event_query)
    growth = {path: max(0, len(raw) - len(read(path))) for path, raw in modified.items()}
    modified[REST], _ = grow_resources(read(REST), growth)
    encoded = {path: compression.encode(raw, source(path)) if path.endswith(".zs") else raw
               for path, raw in modified.items()}
    for path, raw in encoded.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    return {"flag": flag, "version": 1, "safe_verbs": sorted(SAFE_VERBS),
            "resources": {path: hashlib.sha256(raw).hexdigest() for path, raw in modified.items()}}
