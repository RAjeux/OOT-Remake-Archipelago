"""Separate Gerudo rescue and membership from the Spirit Temple quest.

Adapted from OOTRR 0.8.2 open_world/fortress.rs,
0fa64f44b5e689f39bcf98a151fc32cb019d538e (GPL-3.0-or-later).
The fixed native schedules and inventory flag remain authoritative. No AP item,
location, receipt index or native reward is introduced by this patch.
"""
import copy
from pathlib import Path
import uuid

from .mod_codec import Codec
from .quest_fixes import RESCUED, STORY_AFTER_STEP01, PREFIX as QUEST_PREFIX
from .story_fixes import _invalid, REST

CARD = "IsGet.Item_Token_Gerudo"
CLEARED = "SageOfSpirit_IsAfter_Step01_Exp"
AFTER_REQUIEM = "SageOfSpirit_IsAfter_Step05_Exp"
DATA = "GameData/GameDataList.Product.110.byml.zs"
PACK = "Pack/AIScheduleParam.pack.zs"
CARD_MODULES = (
    "Logic/GerudoFortress_Common_178b.logic.module.ainb",
    "Logic/GerudoFortress_Common_1d80.logic.module.ainb",
    "Logic/GerudoFortress_Level_Exterior_01_a401.logic.module.ainb",
    "Logic/GerudoFortress_Level_Room_02_5d06.logic.module.ainb",
    "Logic/GerudoFortress_Level_Room_05_ee1c.logic.module.ainb",
    "Logic/GerudoFortress_Level_Room_06_ade9.logic.module.ainb",
    "Logic/MiniGame_HorsebackArchery_8380.logic.module.ainb",
)
RESCUE_MODULES = (
    "Logic/GerudoFortress_Common_58a8.logic.module.ainb",
    "Logic/GerudoFortress_Common_Level_CarpenterSet_01_e139.logic.module.ainb",
    "Logic/GerudoFortress_Common_Level_CarpenterSet_02_9477.logic.module.ainb",
    "Logic/GerudoFortress_Common_Level_CarpenterSet_03_c7f2.logic.module.ainb",
    "Logic/GerudoFortress_Common_Level_CarpenterSet_04_e9a4.logic.module.ainb",
)
COLOSSUS = "Logic/DesertColossus_Common_665d.logic.module.ainb"
CARPENTERS = ("013", "014", "015", "016")


def schedule(npc):
    return "Component/AIScheduleParam/" + npc + ".game__component__AIScheduleParam.bgyml"


def own_schedule(number):
    return schedule("Npc_Hylia_" + number + "_Adult")


def jail_schedule(number):
    return schedule("SageOfSpirit_Step01_Npc_Hylia_" + number + "_Adult_GerudoFortress")


def _strings(node):
    return {row["Name"]: row.get("Default Value")
            for row in node.get("Parameters", {}).get("Inputs", {}).get("String", ())}


def step_nodes(doc):
    return {node["Node Index"] for node in doc["Nodes"]
            if node["Name"] == "HoldChallengeCurrentStepCheckOrder" and _strings(node) == {
                "ChallengeName": "Work/Challenge/SageOfSpirit.game__challenge__Challenge.gyml",
                "ChallengeStepName": "Step01"}}


def bool_sources(node):
    for row in node.get("Parameters", {}).get("Inputs", {}).get("Bool", ()):
        for value in row.get("Sources", (row,)):
            yield row["Name"], value


def _guid(path, part):
    return str(uuid.uuid5(uuid.NAMESPACE_URL,
        "https://github.com/RAjeux/OOT-Remake-Archipelago/fortress-fixes/" + path + "/" + part))


def _node(index, name, guid, inputs, outputs, queries=(), plugs=()):
    return {"Node Type": "UserDefined", "Node Index": index, "Name": name, "GUID": guid,
            "Flags": ["Is Query"], "Queries": list(queries), "Attachments": [], "Properties": {},
            "Parameters": {"Inputs": inputs, "Outputs": {"Bool": outputs}}, "XLink Actions": [],
            "Plugs": {"Generic": list(plugs)} if plugs else {}}


def _constant(name, value):
    return {"Name": name, "Default Value": value, "Node Index": -1, "Output Index": 0,
            "Flags": ["Uses Default"]}


def _read_node(index, path, part, flag, *, expression=False):
    inputs = {"String": [_constant("GameDataNameBoolExp" if expression else "GameDataNameBool", flag)]}
    if not expression:
        inputs["Int"] = [_constant("GameDataArrayIndex", -1)]
    return _node(index, "HoldGameDataGetBoolExpSimple" if expression else "HoldGameDataGetBoolSimple",
                 _guid(path, part), inputs, [{"Name": "Bool", "Is Output": True}])


def _gate_node(index, path, part, kind, sources):
    values = [{"Node Index": node, "Output Index": output, "Flags": []} for node, output in sources]
    multi = {"Name": "BoolMulti", "Default Value": False}
    if len(values) == 1:
        multi.update(values[0])
    else:
        multi["Sources"] = values
    return _node(index, kind, _guid(path, part),
                 {"Bool": [multi, _constant("UpdateOnce", False)]},
                 [{"Name": "False", "Is Output": True}, {"Name": "True", "Is Output": True}],
                 [source for source, _ in sources],
                 [{"Node Index": source, "Name": "BoolMulti"} for source, _ in dict.fromkeys(sources)])


def _serialize(original, doc):
    import ainb
    updated = ainb.AINB.from_dict(doc)
    # Preserve the empty v1032 blackboard object; losing it changes the writer's
    # header size and would corrupt the offsets of every following section.
    updated.blackboard = original.blackboard
    raw = updated.to_binary()
    if ainb.AINB.from_binary(raw).as_dict() != doc:
        raise _invalid()
    return raw


def patch_fortress_logic(raw, path):
    import ainb
    if path not in CARD_MODULES + RESCUE_MODULES:
        raise _invalid()
    original = ainb.AINB.from_binary(raw)
    doc = original.as_dict()
    if (doc.get("Version") != 1032 or doc.get("Category") != "Logic"
            or doc.get("Filename") != Path(path).name.removesuffix(".ainb")):
        raise _invalid()
    nodes, steps = doc["Nodes"], step_nodes(doc)
    gate_id = next((node["Node Index"] for node in nodes if node["GUID"] == _guid(path, "cleared")), None)
    if gate_id is not None:
        readers = [node for node in nodes if node["GUID"] == _guid(path, "read")]
        if (len(readers) != 1 or nodes[gate_id] != _gate_node(gate_id, path, "cleared", "OperateOR", [(readers[0]["Node Index"], 0)])
                or readers[0] != _read_node(readers[0]["Node Index"], path, "read",
                    CLEARED if path in CARD_MODULES else RESCUED, expression=path in CARD_MODULES)
                or any(value.get("Node Index") in steps for node in nodes for _, value in bool_sources(node))):
            raise _invalid()
        return raw
    if not steps:
        raise _invalid()
    read, gate = len(nodes), len(nodes) + 1
    reader = _read_node(read, path, "read", CLEARED if path in CARD_MODULES else RESCUED,
                        expression=path in CARD_MODULES)
    moved = 0
    for node in nodes:
        if node["Node Index"] in steps:
            continue
        changed = False
        for _, value in bool_sources(node):
            if value.get("Node Index") not in steps:
                continue
            output = value.get("Output Index")
            if output not in (0, 1, 2):
                raise _invalid()
            value.update({"Node Index": gate, "Output Index": 1 if output == 0 else 0})
            moved += 1
            changed = True
        if changed:
            node["Queries"] = [gate if index in steps else index for index in node.get("Queries", ())]
            for plug in node.get("Plugs", {}).get("Generic", ()):
                if plug.get("Node Index") in steps:
                    plug["Node Index"] = gate
    if not moved:
        raise _invalid()
    nodes.extend([reader, _gate_node(gate, path, "cleared", "OperateOR", [(read, 0)])])
    if any(value.get("Node Index") in steps for node in nodes for _, value in bool_sources(node)):
        raise _invalid()
    return _serialize(original, doc)


def patch_requiem_logic(raw):
    import ainb
    original = ainb.AINB.from_binary(raw)
    doc = original.as_dict()
    if (doc.get("Version") != 1032 or doc.get("Category") != "Logic"
            or doc.get("Filename") != Path(COLOSSUS).name.removesuffix(".ainb")):
        raise _invalid()
    nodes = doc["Nodes"]
    targets = [node for node in nodes if node["Name"] == "TriggerChallengeSetStep" and _strings(node) == {
        "ChallengeName": "Work/Challenge/SageOfSpirit.game__challenge__Challenge.gyml", "StepName": "Step05"}]
    if len(targets) != 1:
        raise _invalid()
    inputs = [value for name, value in bool_sources(targets[0]) if name == "IsDrive"]
    if len(inputs) != 1:
        raise _invalid()
    drive = inputs[0]
    existing = next((node for node in nodes if node["GUID"] == _guid(COLOSSUS, "request")), None)
    if existing:
        if drive.get("Node Index") != existing["Node Index"] or drive.get("Output Index") != 1:
            raise _invalid()
        return raw
    source, output = drive.get("Node Index", -1), drive.get("Output Index", -1)
    if source < 0 or output < 0:
        raise _invalid()
    read, inverse, gate = len(nodes), len(nodes) + 1, len(nodes) + 2
    nodes.extend([_read_node(read, COLOSSUS, "after", AFTER_REQUIEM, expression=True),
                  _gate_node(inverse, COLOSSUS, "not_after", "OperateOR", [(read, 0)]),
                  _gate_node(gate, COLOSSUS, "request", "OperateAND", [(inverse, 0), (source, output)])])
    drive.update({"Node Index": gate, "Output Index": 1})
    target = targets[0]
    target["Queries"] = [gate if node == source else node for node in target.get("Queries", ())]
    for plug in target.get("Plugs", {}).get("Generic", ()):
        if plug.get("Node Index") == source and plug.get("Name") == "IsDrive":
            plug["Node Index"] = gate
    return _serialize(original, doc)


def patch_carpenter_schedule(own_raw, jail_raw):
    from oot_rando.formats import byml_codec
    own, jail = byml_codec.load(own_raw), byml_codec.load(jail_raw)
    a, b = own["root"], jail["root"]
    if "DefaultSchedule" not in a or "DefaultSchedule" not in b or not isinstance(b.get("ConditionalSchedule"), list):
        raise _invalid()
    existing = a.get("ConditionalSchedule", ())
    if existing:
        if (existing[0].get("ConditionFlag") != RESCUED or existing[1:] != b["ConditionalSchedule"]
                or a["DefaultSchedule"] != b["DefaultSchedule"]):
            raise _invalid()
        return own_raw
    first = copy.deepcopy(a["DefaultSchedule"])
    first["ConditionFlag"] = RESCUED
    a["ConditionalSchedule"] = [first, *copy.deepcopy(b["ConditionalSchedule"])]
    a["DefaultSchedule"] = copy.deepcopy(b["DefaultSchedule"])
    result = byml_codec.dump(own)
    if byml_codec.load(result) != own:
        raise _invalid()
    return result


def patch_clearance_flag(raw):
    from oot_rando.formats import byml_codec
    from oot_rando.patching.soul_adapter import murmur3
    doc = byml_codec.load(raw)
    data = doc["root"]["Data"]
    rows = [row for row in data["BoolExp"] if int(row["Hash"]) == murmur3(CLEARED)]
    if len(rows) != 1 or not any(int(row["Hash"]) == murmur3(CARD) for row in data["Bool"]):
        raise _invalid()
    old = rows[0].get("Values")
    if not old or len(old[0]) != 2:
        raise _invalid()
    wanted = [[type(old[0][0])(0), type(old[0][1])(murmur3(CARD))]]
    aliases = [row for row in data["BoolExp"] if int(row["Hash"]) == murmur3(STORY_AFTER_STEP01)]
    if (len(aliases) != 1 or aliases[0].get("SaveFileIndex") != -1
            or aliases[0].get("Values") != [[12, murmur3("Step_SageOfSpirit")], [2, murmur3("Step01")]]):
        raise _invalid()
    if old == wanted:
        return raw
    rows[0]["Values"] = wanted
    result = byml_codec.dump(doc)
    if byml_codec.load(result) != doc:
        raise _invalid()
    return result


def prepare_fortress_fixes(romfs, mod):
    from oot_rando.formats.inspect_resources import sarc
    from oot_rando.game.resource_allocations import allocation, grow_resources
    romfs, mod = Path(romfs), Path(mod)
    if mod.name != "romfs" or mod.parent.name != "Archipelago":
        raise _invalid()
    codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
    cache = {}
    def frame(path):
        if path not in cache:
            candidate = mod / path
            cache[path] = (candidate if candidate.is_file() else romfs / path).read_bytes()
        return cache[path]
    def raw(path):
        return codec.decode(frame(path)) if path.endswith(".zs") else frame(path)
    # These repairs form one bundle. Without the monotonic story guard and the
    # rescue mark, changing fortress clearance could reopen the old lost-check
    # path or make a later carpenter conversation move Spirit back to Step01.
    from oot_rando.patching.event_patch import _flow
    boss = _flow(raw("Event/EventFlow/Npc_Hylia_012_Adult.bfevfl.zs")).flowchart
    spirit = _flow(raw("Event/EventFlow/SageOfSpirit.bfevfl.zs")).flowchart
    if (not any(event.name.startswith(QUEST_PREFIX + "Order_Step01_") and event.data.params is not None
                and event.data.params.data.get("GameDataName") == STORY_AFTER_STEP01 for event in boss.events)
            or not any(event.name == QUEST_PREFIX + "Rescued" and event.data.params is not None
                       and event.data.params.data.get("GameDataName") == RESCUED for event in spirit.events)):
        raise _invalid()
    changed = {path: patch_fortress_logic(raw(path), path) for path in CARD_MODULES + RESCUE_MODULES}
    changed[COLOSSUS] = patch_requiem_logic(raw(COLOSSUS))
    packed = sarc(raw(PACK))
    for number in CARPENTERS:
        source = jail_schedule(number)
        if source not in packed:
            raise _invalid()
        changed[own_schedule(number)] = patch_carpenter_schedule(raw(own_schedule(number)), packed[source])
    changed[DATA] = patch_clearance_flag(raw(DATA))
    growth = {path: max(0, len(content) - len(raw(path))) for path, content in changed.items()}
    table, allocations = grow_resources(raw(REST), growth)
    # The native schedule parser needs both complete parsed structures, not a
    # small margin over their file growth. Upstream observed a loader crash
    # without the sum of these two original native allocation budgets.
    base = codec.decode((romfs / REST).read_bytes())
    budgets, needed = {}, {}
    for number in CARPENTERS:
        own, jail = own_schedule(number), jail_schedule(number)
        own_size, jail_size, current = allocation(base, own), allocation(base, jail), allocation(table, own)
        if own_size is None or jail_size is None or current is None:
            raise _invalid()
        target = own_size + jail_size
        needed[own] = target
        budgets[own] = max(0, target - current)
    table, schedule_allocations = grow_resources(table, budgets)
    if any(allocation(table, path) < minimum for path, minimum in needed.items()):
        raise _invalid()
    changed[REST] = table
    encoded = {path: codec.encode(content, frame(path)) if path.endswith(".zs") else content
               for path, content in changed.items() if content != raw(path)}
    for path, content in encoded.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return dict(version=1, logic_modules=len(CARD_MODULES) + len(RESCUE_MODULES) + 1,
                schedules=len(CARPENTERS), files=len(encoded), allocations=allocations,
                schedule_allocations=schedule_allocations, minimum_schedule_budgets=needed)
