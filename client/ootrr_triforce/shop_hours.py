"""Optional opening hours for ordinary shops, using the v0.10 resource engine.

Only time conditions are changed. Quest, age, potion tutorial, purchase and
capacity conditions remain native. Minigames and their attendants are excluded.
The setting is AP-only; it never changes the portable builder's settings schema.
"""
import copy
from pathlib import Path

from .mod_codec import Codec
from .story_fixes import REST

VERSION = 1


def module_path(name):
    return "Logic/" + name + ".logic.module.ainb"


# Shops without an opening-time condition (Kokiri, Goron and Zora) need no edit.
# Module, door node, native module name, time-dependent EnableOpen source.
DOORS = (
    ("Market_Child_Prefab_8c1c", 1, "Obj_Door_ShopAnything_657f.logic.module", (0, 0)),
    ("Market_Child_Prefab_971c", 6, "Obj_Door_ShopMedicine_9089.logic.module", (5, 1)),
    ("KakarikoVillage_Adult_Common_d447", 1, "Obj_Door_Shop_KakarikoNandemoya_4df6.logic.module", (0, 0)),
    ("KakarikoVillage_Adult_Common_426e", 1, "Obj_Door_Shop_KakarikoMedicine_67a6.logic.module", (0, 0)),
    ("KakarikoVillage_Adult_Common_426e", 2, "Obj_Door_Shop_KakarikoMedicine_67a6.logic.module", (0, 0)),
)
MASK = "Market_Child_Prefab_7c39"
BOMBCHU = "Market_Child_Prefab_0c76"
MODULES = tuple(dict.fromkeys(row[0] for row in DOORS)) + (MASK, BOMBCHU)

# Flow, service decision, case allowing service, normal target, closed target.
# Other time decisions in these flows choose greetings, and remain untouched.
SERVICES = (
    ("Npc_Hylia_020_Shop_Child", "Event2", 0, "Event107", "Event90"),
    ("Npc_Hylia_023_Shop_Child", "Event36", 0, "Event134", "Event69"),
    ("Npc_Hylia_021_Shop_Child", "Event2", 1, "Event57", "Event72"),
)


def service_path(name):
    return "Event/EventFlow/" + name + ".bfevfl.zs"


def _invalid(path):
    return ValueError("Unsupported shop opening-hours resource layout: " + str(path))


def _input(node, name, kind="Bool"):
    rows = [row for row in node.get("Parameters", {}).get("Inputs", {}).get(kind, ())
            if row.get("Name") == name]
    if len(rows) != 1:
        raise _invalid(node.get("Name", name))
    return rows[0]


def _source(row):
    if "Sources" in row:
        raise _invalid("multi-source scalar input")
    return row.get("Node Index"), row.get("Output Index")


def _bool_sources(node):
    for row in node.get("Parameters", {}).get("Inputs", {}).get("Bool", ()):
        yield from row.get("Sources", (row,))


def _true(row):
    return (_source(row) == (-1, 0) and row.get("Default Value") is True
            and set(row.get("Flags", ())) == {"Uses Default", "Is Output"})


def _time(nodes, index):
    if nodes[index].get("Name") != "HoldWmGetTimeDiv":
        raise _invalid("opening-time query")


def _flag(nodes, index, name, allowed, *, expression=False):
    node = nodes[index]
    if node.get("Name") != ("HoldGameDataGetBoolExpSimple" if expression else "HoldGameDataGetBoolSimple"):
        raise _invalid(name)
    if _input(node, name, "String").get("Default Value") not in allowed:
        raise _invalid(name)


def _gate(nodes, index, kind, sources, *, patched=None):
    node = nodes[index]
    value = _input(node, "BoolMulti")
    actual = [_source(row) for row in value.get("Sources", ())]
    if node.get("Name") != kind or actual not in [sources, patched]:
        raise _invalid("opening-time gate")
    return node, value, actual


def _constant_open(node, expected):
    value = _input(node, "EnableOpen")
    if _true(value):
        return
    if _source(value) != expected or value.get("Flags") != []:
        raise _invalid("shop door EnableOpen")
    value.update({"Node Index": -1, "Output Index": 0, "Default Value": True,
                  "Flags": ["Uses Default", "Is Output"]})
    # An input may share a dependency with another input. Keep that query then.
    used = {row.get("Node Index") for row in _bool_sources(node)}
    node["Queries"] = [index for index in node.get("Queries", ()) if index in used]
    plugs = node.get("Plugs", {})
    if "Generic" in plugs:
        plugs["Generic"] = [row for row in plugs["Generic"] if row.get("Name") != "EnableOpen"]
        if not plugs["Generic"]:
            del plugs["Generic"]


def _without_time(nodes, index, keep_source, original_sources):
    """Replace just the time operand of quest AND time with quest AND quest."""
    wanted = [keep_source, keep_source]
    node, value, actual = _gate(nodes, index, "OperateAND", original_sources, patched=wanted)
    if actual == wanted:
        return
    replacement = next(row for row in value["Sources"] if _source(row) == keep_source)
    value["Sources"] = [copy.deepcopy(replacement), copy.deepcopy(replacement)]
    node["Queries"] = [keep_source[0], keep_source[0]]
    # A multi-input has one representative plug in these native modules.
    plugs = node.get("Plugs", {}).get("Generic", ())
    if len(plugs) != 1 or plugs[0].get("Name") != "BoolMulti":
        raise _invalid("opening-time multi-input plug")
    plugs[0]["Node Index"] = keep_source[0]


def patch_shop_logic(raw, name):
    """Change only known opening-time inputs; reject an unknown native layout."""
    import ainb
    if name not in MODULES:
        raise _invalid(name)
    original = ainb.AINB.from_binary(raw)
    doc = original.as_dict()
    before = copy.deepcopy(doc)
    if (doc.get("Version") != 1032 or doc.get("Category") != "Logic"
            or doc.get("Filename") != name + ".logic.module"):
        raise _invalid(name)
    nodes = doc["Nodes"]
    if any(node.get("Node Index") != index for index, node in enumerate(nodes)):
        raise _invalid(name)
    for module, index, door, expected in DOORS:
        if name != module:
            continue
        if nodes[index].get("Name") != door:
            raise _invalid(name)
        _time(nodes, 0)
        if name == "Market_Child_Prefab_971c":
            # Outside: day OR tutorial not cleared. Inside: tutorial's original
            # started/not-cleared lock. Keep the indoor lock and every flag.
            _flag(nodes, 1, "GameDataNameBool", {"Market_Item_Bottle_TutorialEvent_Started"})
            _flag(nodes, 2, "GameDataNameBool", {"Market_Item_Bottle_TutorialEvent_Cleared"})
            _gate(nodes, 5, "OperateOR", [(0, 0), (4, 0)])
            if _source(_input(nodes[index], "EnableOpenIndoor")) != (3, 0):
                raise _invalid(name)
        _constant_open(nodes[index], expected)
    if name == MASK:
        _time(nodes, 0)
        _flag(nodes, 4, "GameDataNameBool", {"Npc_Hylia_Soldier_003_GateOpen"})
        if (nodes[1].get("Name") != "Obj_Door_ShopMask_b271.logic.module"
                or _source(_input(nodes[1], "EnableOpen")) != (3, 1)):
            raise _invalid(name)
        _gate(nodes, 3, "OperateOR", [(2, 1), (5, 0)])
        _without_time(nodes, 2, (4, 0), [(0, 0), (4, 0)])
    if name == BOMBCHU:
        _time(nodes, 2)
        _flag(nodes, 1, "GameDataNameBoolExp", {
            "Get_StoneOfFire_IsCompleted_Exp", "Get_StoneOfFire_IsAfter_Ready_Exp"}, expression=True)
        if nodes[3].get("Name") != "Obj_Door_ShopBombChu_26fc.logic.module":
            raise _invalid(name)
        value = _input(nodes[3], "EnableOpen")
        if _source(value) == (0, 1):
            # Native door: quest AND nighttime. Never bypass the quest.
            _without_time(nodes, 0, (1, 0), [(1, 0), (2, 1)])
        elif _source(value) == (2, 1) or _true(value):
            # v0.10's shop shuffle already makes EnableDo unconditional and
            # connects EnableOpen to nighttime. Preserve that builder choice.
            if not _true(_input(nodes[3], "EnableDo")):
                raise _invalid(name)
            _constant_open(nodes[3], (2, 1))
        else:
            raise _invalid(name)
    if doc == before:
        return raw
    updated = ainb.AINB.from_dict(doc)
    updated.blackboard = original.blackboard
    result = updated.to_binary()
    if ainb.AINB.from_binary(result).as_dict() != doc:
        raise _invalid(name)
    return result


def patch_shop_service(raw, spec):
    """Keep the native conversation; route only its closed-time service case."""
    from evfl.event import SwitchEvent
    from evfl.util import make_index
    from oot_rando.patching.progressive import FlowEditor
    if spec not in SERVICES:
        raise _invalid(spec)
    name, decision, normal_case, normal, closed = spec
    editor = FlowEditor(raw, name)
    if editor.chart.name != name:
        raise _invalid(name)
    matches = [event for event in editor.chart.events if event.name == decision]
    if len(matches) != 1:
        raise _invalid(name)
    data = matches[0].data
    if (not isinstance(data, SwitchEvent) or str(data.actor.v.identifier) != "EventWorldManagerController"
            or data.actor_query.v.v != "EventQueryTimeDivision"
            or (data.params.data if data.params is not None else {}) != {}
            or set(data.cases) != {0, 1}
            or data.cases[normal_case].v is None or data.cases[normal_case].v.name != normal):
        raise _invalid(name)
    opposite = data.cases[1 - normal_case].v
    if opposite is not None and opposite.name == normal:
        return raw
    if opposite is None or opposite.name != closed:
        raise _invalid(name)
    data.cases[1 - normal_case] = make_index(data.cases[normal_case].v)
    result, checked = editor.write("Shop opening hours")
    changed = next(event for event in checked.flowchart.events if event.name == decision)
    if {case: target.v.name for case, target in changed.data.cases.items()} != {0: normal, 1: normal}:
        raise _invalid(name)
    return result


def prepare_shop_hours(romfs, mod, enabled=False):
    """Prepare only the optional overlay. Disabled/legacy rooms perform no I/O."""
    if type(enabled) is not bool:
        raise ValueError("shops_always_open must be a boolean.")
    if not enabled:
        return {"version": VERSION, "enabled": False, "files": 0}
    from oot_rando.game.resource_allocations import grow_resources
    romfs, mod = Path(romfs), Path(mod)
    if (mod.name != "romfs" or mod.parent.name != "Archipelago"
            or mod.resolve().is_relative_to(romfs.resolve())
            or romfs.resolve().is_relative_to(mod.resolve())):
        raise _invalid(mod)
    codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
    cache = {}
    def frame(path):
        if path not in cache:
            target = mod / path
            cache[path] = (target if target.is_file() else romfs / path).read_bytes()
        return cache[path]
    def raw(path):
        return codec.decode(frame(path)) if path.endswith(".zs") else frame(path)
    # Validate and encode the entire bundle before creating/writing any files.
    changed = {module_path(name): patch_shop_logic(raw(module_path(name)), name) for name in MODULES}
    changed.update({service_path(spec[0]): patch_shop_service(raw(service_path(spec[0])), spec)
                    for spec in SERVICES})
    growth = {path: max(0, len(content) - len(raw(path))) for path, content in changed.items()}
    table, allocations = grow_resources(raw(REST), growth)
    changed[REST] = table
    encoded = {path: codec.encode(content, frame(path)) if path.endswith(".zs") else content
               for path, content in changed.items() if content != raw(path)}
    for path, content in encoded.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return {"version": VERSION, "enabled": True, "logic_modules": len(MODULES),
            "services": len(SERVICES), "files": len(encoded), "allocations": allocations}
