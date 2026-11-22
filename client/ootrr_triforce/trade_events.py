"""Independent adult trade NPCs using native talk and hand-over performances.

The reward entry owns the inventory transaction. These routes only choose an
eligible check, perform the native NPC interaction and call that guarded entry.
"""
from collections import defaultdict
import copy
from pathlib import Path

from .catalog import ITEM_DATA, LOCATION_IDS, TRADE_CHECKS
from .i18n import tr
from .mod_codec import Codec
from .trade_catalog import TALON_AWAKE, event_name

PREFIX = "OOTRR_APTrade_"
NOTHING = "OOTRR_APTradeNothing"
NEEDS_BOTTLE = "OOTRR_APTradeNeedsBottle"
REST = "System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs"
SETTINGS = "RSDB/EventSetting.Product.111.rstbl.byml.zs"
ANALYZED = "RSDB/GameAnalyzedEventInfo.Product.111.rstbl.byml.zs"
FLOW_ROOT = "Event/EventFlow/"
SHARED = "SubEvent_GetSwordBigGoron"
GET = "GetPouchContent"
TALON_FLOW = "Npc_Hylia_Talon_Adult_Kakariko"
LOST_WOOD = "Banc/LostWood/LostWood_Adult_Static.bcett.byml.zs"
LOST_LOGIC = "Logic/LostWood_Adult_Prefab_b5e7.logic.module.ainb"
LOST_MODULE = "Logic/Module/LostWood_Adult_Prefab/LostWood_Adult_Prefab_b5e7.logic.module.ain"
LOST_GROUP = 10166097622937307822
GROG = 11959891550395380870
FADO = 4375222428486358625
FADO_ANCHOR = 17404268641527642622
PRESENCE = "SubEvent_GetSwordBigGoron_IsAfter_Step04_Exp"
ACTORS = {
    "Item_PocketEgg", "Item_PocketCucco", "Item_CojiroCucco", "Item_OddMushroom",
    "Item_OddPowder", "Item_PoacherSaw", "Item_BrokenSword", "Item_Prescription",
    "Item_EyeballFrog", "Item_EyeDrop", "Item_ClaimCheck",
}
ASSIGNABLE = {actor: index for index, actor in enumerate((
    "Item_PocketCucco", "Item_CojiroCucco", "Item_OddMushroom", "Item_OddPowder",
    "Item_PoacherSaw", "Item_BrokenSword", "Item_Prescription", "Item_EyeballFrog",
    "Item_EyeDrop", "Item_ClaimCheck"), 35)}
ITEM_POSITION = [0.07500000298023224, -0.6000000238418579, 0.6499999761581421]
NEUTRAL = {
    "Npc_Hylia_049_Adult", "Npc_Hylia_017_Adult", "Npc_Kokiri_Fado_Adult",
    "Npc_Hylia_012_Adult", "Npc_Goron_Biggoron_Adult",
}
# First-grant actions survive OOTRR's ordinary parameter replacement by name.
LEGACY_REWARDS = {
    "Npc_Hylia_049_Adult": {"Event264", "Event234"},
    "Npc_Hylia_017_Adult": {"Event100"},
    "Npc_Hylia_053_Adult": {"Event167"},
    "Npc_Kokiri_Fado_Adult": {"Event123"},
    "Npc_Hylia_012_Adult": {"Event58"},
    "Npc_Goron_Biggoron_Adult": {"Event232", "Event123"},
    "Npc_Zora_KingZora_adult": {"Event131"},
    "Npc_Hylia_045_Adult": {"Event26"},
    "Dm_DeathMtTrail_0050": {"Event21"},
}


def _invalid():
    return ValueError(tr("Unknown native adult trade layout."))


def trade_records(roster):
    result = []
    for name, meta in TRADE_CHECKS.items():
        if name not in roster:
            raise ValueError(tr("The room did not provide every adult trade reward."))
        reward = roster[name]
        if not isinstance(reward, dict) or type(reward.get("local")) is not bool:
            raise ValueError(tr("Invalid adult trade reward metadata."))
        row = dict(meta, name=name)
        row["needs_bottle"] = bool(reward["local"] and ITEM_DATA.get(reward.get("item"), {}).get("bottle_item")
                                   and ITEM_DATA[reward["item"]].get("pouch_special") == "NotPushToPouch")
        if row["id"] != LOCATION_IDS[name]:
            raise _invalid()
        result.append(row)
    return result


def _system(editor):
    from evfl.actor import Actor
    from evfl.common import ActorIdentifier
    from evfl.container import Container
    from oot_rando.patching.event_patch import GAMEDATA_ACTOR_PARAMS
    if not any(str(actor.identifier) == "EventSystemActor" for actor in editor.chart.actors):
        actor = Actor()
        actor.identifier = ActorIdentifier("EventSystemActor")
        actor.concurrent_clips = 1
        actor.params = Container()
        actor.params.data = dict(GAMEDATA_ACTOR_PARAMS)
        editor.chart.actors.append(actor)


def _wait(editor, name, target=None):
    from oot_rando.patching.progressive import link
    _system(editor)
    node = editor.action(name, "EventSystemActor", "EventWait", {"Frames": 1, "IsWaitEnd": True})
    link(node, target)
    return node


def _skip(editor, events):
    """Make legacy mechanics unreachable while retaining authored continuations."""
    from evfl.util import make_index
    from .shop_events import _retarget
    for index, node in enumerate(events):
        replacement = _wait(editor, PREFIX + "LegacySkip" + str(index), node.data.nxt.v)
        for previous in list(editor.chart.events):
            _retarget(previous, node, replacement)
        for point in editor.chart.entry_points:
            if point.main_event.v is node:
                point.main_event = make_index(replacement)


def _legacy(node, name):
    from evfl.event import ActionEvent, SubFlowEvent
    data = node.data
    params = data.params.data if getattr(data, "params", None) else {}
    if node.name in LEGACY_REWARDS.get(name, ()):
        if not isinstance(data, SubFlowEvent):
            raise _invalid()
        return True
    if isinstance(data, ActionEvent):
        command = data.actor_action.v.v
        actor = str(data.actor.v.identifier)
        if actor == "ChallengeSystemActor" and command == "EventExecuteProgressChallengeStep":
            return params.get("ChallengeName") == SHARED
        if actor == "PouchSystemActor":
            if command == "EventTriggerRemoveSwordBigGoronChallengeActor":
                return True
            if command == "EventTriggerAddOrRemovePouchContent":
                return params.get("Actor") in ACTORS or (name == "Npc_Goron_Biggoron_Adult"
                        and params.get("Actor") in {"Weapon_Sword_Giant", "Weapon_Sword_BrokenGiant"})
        if name == "Dm_DeathMtTrail_0050" and actor.startswith("Item_ClaimCheck"):
            return True
    if isinstance(data, SubFlowEvent):
        if data.res_flowchart_name == SHARED and (data.entry_point_name.startswith("BigGoronTimer")
                                                 or data.entry_point_name.startswith("SubEvent_TimerCheck")):
            return True
        return any(params.get(key) in ACTORS for key in ("ActorName", "ReveiveItem"))
    return False


def _init(editor, name, actor, target):
    from evfl.common import ActorIdentifier
    from oot_rando.patching.progressive import link
    node = editor.subflow(name, SHARED, "InitTalk_OnEvent_ShowItemOnly",
                          {"Arg_Turn": 4, "Arg_Greeting": 4, "ActorNameA": actor,
                           "InstanceNameA": "", "Arg_Actor": ActorIdentifier(actor), "CameraType": False})
    link(node, target)
    return node


def _granny_shop(editor, name):
    """Keep Granny's native sale unlocked by her completed mushroom exchange."""
    if name != "Npc_Hylia_053_Adult":
        return
    from evfl.event import SwitchEvent
    from evfl.util import make_index
    from .shop_events import _retarget
    expected = {"Event29": "SubEvent_GetSwordBigGoron_IsAfter_Step03_03_Exp",
                "Event30": "SubEvent_GetSwordBigGoron_IsAfter_Step04_Exp",
                "Event3": "SubEvent_GetSwordBigGoron_IsAfter_Step05_01_Exp"}
    gates = [node for node in editor.chart.events if node.name in expected]
    if len(gates) != len(expected):
        raise _invalid()
    for node in gates:
        data = node.data
        if (not isinstance(data, SwitchEvent) or str(data.actor.v.identifier) != "GameDataActor"
                or data.actor_query.v.v != "EventQueryIsGameDataBoolExp" or data.params is None
                or data.params.data != {"GameDataName": expected[node.name]} or set(data.cases) != {0,1}):
            raise _invalid()
    flag = TRADE_CHECKS["Kak Granny Trade Odd Mushroom"]["flag_name"]
    for node in gates:
        replacement = editor.switch(PREFIX + "GrannyShop" + node.name, "GameDataActor", "EventQueryIsGameDataBool",
                                    {"GameDataName": flag, "Index": -1}, node.data.cases[0].v, node.data.cases[1].v)
        for previous in list(editor.chart.events):
            _retarget(previous, node, replacement)
        for point in editor.chart.entry_points:
            if point.main_event.v is node:
                point.main_event = make_index(replacement)


def patch_trade_flow(raw, records, name):
    """Guard each NPC's native talk/show-item entry by stock and AP completion."""
    from evfl.common import ActorIdentifier
    from evfl.event import SubFlowEvent
    from evfl.util import make_index
    from oot_rando.patching.event_info import reachable
    from oot_rando.patching.progressive import FlowEditor, link
    editor = FlowEditor(raw, name)
    if editor.chart.name != name or any(node.name.startswith(PREFIX) for node in editor.chart.events):
        raise _invalid()
    expected = LEGACY_REWARDS.get(name)
    if expected is None or not expected <= {node.name for node in editor.chart.events}:
        raise _invalid()
    rows = [row for row in records if row["flow"] == name]
    if not rows:
        raise _invalid()
    _granny_shop(editor, name)
    _skip(editor, [node for node in editor.chart.events if _legacy(node, name)])
    points = [point for point in editor.chart.entry_points if (
        point.name == "Talk" or point.name.endswith("_Talk") or point.name.startswith("Talk_")
        or point.name.startswith("SubEvent_GetSwordBigGoron") or "Show" in point.name)]
    if not any(point.name == "Talk" for point in points):
        raise _invalid()
    def dialogue(label):
        template = next((node for node in editor.chart.events
                         if getattr(node.data, "actor_action", None)
                         and node.data.actor_action.v.v == "EventTalk"
                         and str(node.data.actor.v.identifier) == name
                         and node.data.params is not None), None)
        if template is None:
            raise _invalid()
        params = dict(template.data.params.data)
        params.update(MessageId="EventFlowMsg/" + name + ":" + label,
                      ChoiceNumber=0, IsCloseDialog=True, IsWaitEnd=True)
        text = editor.action(PREFIX + label, name, "EventTalk", params)
        return _init(editor, PREFIX + label + "Init", name, text)
    neutral = dialogue(NOTHING) if name in NEUTRAL else None
    bottle = dialogue(NEEDS_BOTTLE) if any(row.get("needs_bottle") for row in rows) else None
    # Each public entry gets the same priority order; only its native non-quest
    # fallback differs. The callback rechecks every precondition transactionally.
    for number, point in enumerate(points):
        fallback = neutral or point.main_event.v
        branch = fallback
        for row in reversed(rows):
            stem = PREFIX + str(number) + "_" + str(row["id"])
            reward = editor.subflow(stem + "_Reward", GET, event_name(row["id"]), None)
            perform = reward
            actor = row["required_actor"]
            if actor:
                hand = editor.subflow(stem + "_Handover", SHARED,
                                      "GetSwordBiggoron_HandOver_PlayerToNpc_ForYou",
                                      {"NpcActor": ActorIdentifier(name), "EmotionType": 1})
                link(hand, reward)
                show = editor.subflow(stem + "_Show", SHARED,
                                      "ShowItemSuccess_NoCamera_SwordBigGoron",
                                      {"AssignableItem": ASSIGNABLE[actor], "LookAtActorName": name,
                                       "ItemPos_Adult": list(ITEM_POSITION)})
                link(show, hand)
                perform = show
            perform = _init(editor, stem + "_Init", name, perform)
            if row.get("needs_bottle"):
                perform = editor.switch(stem + "_Bottle", "PouchSystemActor", "EventQueryIsAnyBottleEmpty",
                                         None, perform, bottle)
            if row.get("wake_talon"):
                perform = editor.switch(stem + "_Talon", "GameDataActor", "EventQueryIsGameDataBool",
                                         {"GameDataName": TALON_AWAKE, "Index": -1}, perform, branch)
            if actor:
                perform = editor.switch(stem + "_Owns", "PouchSystemActor", "EventQueryIsExistInPouch",
                                         {"Actor": actor, "Num": 1}, perform, branch)
            branch = editor.switch(stem + "_Done", "GameDataActor", "EventQueryIsGameDataBool",
                                    {"GameDataName": row["flag_name"], "Index": -1}, branch, perform)
        point.main_event = make_index(branch)
    for point in editor.chart.entry_points:
        for node in reachable(point.main_event.v):
            if node.name.startswith(PREFIX) and isinstance(node.data, SubFlowEvent):
                index = editor.chart.events.index(node)
                if index not in point._sub_flow_event_indices:
                    point._sub_flow_event_indices.append(index)
    return editor.write("Independent adult trade routes")[0]


def patch_trade_timers(raw):
    """Timeless trade items never expire, revert, or regenerate from retry paths."""
    from evfl.util import make_index
    from oot_rando.patching.progressive import FlowEditor
    editor = FlowEditor(raw, SHARED)
    if editor.chart.name != SHARED or any(node.name.startswith(PREFIX) for node in editor.chart.events):
        raise _invalid()
    stop = _wait(editor, PREFIX + "Timeless")
    changed = 0
    for point in editor.chart.entry_points:
        if (point.name.startswith("BigGoronTimer_Step") or point.name.startswith("SubEvent_TimerCheck")
                or point.name in {"EggHatch_PocketEgg", "WaitEggHatch_Npc_Navi_StepStart"}):
            point.main_event = make_index(stop)
            changed += 1
    if changed < 12:
        raise _invalid()
    _skip(editor, [node for node in editor.chart.events if _legacy(node, SHARED)])
    return editor.write("Timeless adult trade items")[0]


def patch_talon_flow(raw):
    """A hidden owned Pocket Cucco can still perform Talon's real wake-up."""
    from evfl.util import make_index
    from evfl.event import SubFlowEvent
    from oot_rando.patching.event_info import reachable
    from oot_rando.patching.progressive import FlowEditor
    editor = FlowEditor(raw, TALON_FLOW)
    if editor.chart.name != TALON_FLOW or any(node.name.startswith(PREFIX) for node in editor.chart.events):
        raise _invalid()
    entries = {point.name: point for point in editor.chart.entry_points}
    shown_name = "Npc_Hylia_Talon_Adult_ShowPocketCucco"
    if not {"Talk", shown_name} <= entries.keys():
        raise _invalid()
    shown = entries[shown_name].main_event.v
    # The original shown-item entry already creates AssignableItem35 explicitly
    # inside its native fork, crows, wakes Talon and writes TALON_AWAKE. It never
    # removes the Cucco. Keep that whole authored performance and its schedule.
    for number, point in enumerate(list(editor.chart.entry_points)):
        if point.name == "Talk" or point.name.endswith("_Talk"):
            fallback = point.main_event.v
            awake = editor.switch(PREFIX + "TalonAwake" + str(number), "GameDataActor", "EventQueryIsGameDataBool",
                                   {"GameDataName": TALON_AWAKE, "Index": -1}, fallback, shown)
            stock = editor.switch(PREFIX + "TalonOwns" + str(number), "PouchSystemActor", "EventQueryIsExistInPouch",
                                   {"Actor": "Item_PocketCucco", "Num": 1}, awake, fallback)
            point.main_event = make_index(stock)
    fallback = entries["Talk"].main_event.v
    own = editor.switch(PREFIX + "TalonShownOwns", "PouchSystemActor", "EventQueryIsExistInPouch",
                         {"Actor": "Item_PocketCucco", "Num": 1}, shown, fallback)
    entries[shown_name].main_event = make_index(own)
    for point in editor.chart.entry_points:
        for node in reachable(point.main_event.v):
            if isinstance(node.data, SubFlowEvent):
                index = editor.chart.events.index(node)
                if index not in point._sub_flow_event_indices:
                    point._sub_flow_event_indices.append(index)
    return editor.write("Native Pocket Cucco wake-up from ordinary talk")[0]


def patch_trade_cutscene(raw):
    """The ordinary Biggoron route replaces the old Claim Check timeline."""
    from evfl.util import make_index
    from oot_rando.patching.progressive import FlowEditor
    editor = FlowEditor(raw, "Dm_DeathMtTrail_0050")
    if editor.chart.name != "Dm_DeathMtTrail_0050" or not {"C08", "EntryPoint0"} <= {
            point.name for point in editor.chart.entry_points}:
        raise _invalid()
    stop = _wait(editor, PREFIX + "LegacyCutscene")
    for point in editor.chart.entry_points:
        point.main_event = make_index(stop)
    return editor.write("Adult trade cutscene replacement")[0]


def patch_trade_scene(raw):
    """Keep Grog and Fado available independently and put them side by side."""
    from oot_rando.formats import byml_codec
    document = byml_codec.load(raw)
    actors = {row.get("Hash"): row for row in document["root"]["Actors"]}
    groups = [row for row in document["root"].get("AiGroups", ()) if row.get("Hash") == LOST_GROUP]
    expected_refs = {"Npc_Kokiri_Fado_Adult_7409": FADO, "Npc_Hylia_017_Adult_7d7e": GROG}
    if (len(groups) != 1 or groups[0].get("Logic") != LOST_MODULE
            or {row.get("Id"): row.get("Reference") for row in groups[0].get("References", ())
                if row.get("Id") in expected_refs} != expected_refs):
        raise _invalid()
    anchor = actors.get(FADO_ANCHOR)
    fado = actors.get(FADO)
    if (not anchor or anchor.get("Gyaml") != "AnchorAction1" or not fado
            or fado.get("Links") != [{"Dst": FADO_ANCHOR, "Gyaml": "Reference", "Name": "Reference", "Src": FADO}]
            or anchor.get("Translate") != fado.get("Translate")
            or not isinstance(anchor.get("Translate"), list) or len(anchor["Translate"]) != 3):
        raise _invalid()
    for key, gyaml, negation in ((GROG, "Npc_Hylia_017_Adult", True), (FADO, "Npc_Kokiri_Fado_Adult", False)):
        row = actors.get(key)
        if (row is None or row.get("Gyaml") != gyaml
                or row.get("Presence") != {"FlagName": PRESENCE, "IsCheckLazy": False, "IsNegation": negation}):
            raise _invalid()
        del row["Presence"]
    actors[FADO]["Translate"][0] += 2.0
    anchor["Translate"][0] += 2.0
    return byml_codec.dump(document)


def patch_trade_logic(raw):
    """Create both independent NPCs without changing enemies or area logic."""
    import ainb
    import struct
    document = ainb.AINB.from_binary(raw).as_dict()
    if (document.get("Version") != 1032 or document.get("Filename") != "LostWood_Adult_Prefab_b5e7.logic.module"
            or document.get("Category") != "Logic" or len(document.get("Nodes", ())) != 22
            or document.get("Commands") != []):
        raise _invalid()
    # Keep every section, string and unused slot at its original offset. The
    # native format stores query/plug counts separately from their backing data.
    # Clearing these two dependency counts leaves only inert unused table slots.
    result, allowed = bytearray(raw), set()
    io_offset = struct.unpack_from("<I", raw, 0x34)[0]
    bool_pool = struct.unpack_from("<I", raw, io_offset + 8)[0]
    for index, instance, source in ((0, "Npc_Kokiri_Fado_Adult_7409", 9), (4, "Npc_Hylia_017_Adult_7d7e", 7)):
        node = document["Nodes"][index]
        expected = {"Name": "Logic_Create", "Default Value": True, "Node Index": source, "Output Index": 1, "Flags": []}
        rows = node.get("Parameters", {}).get("Inputs", {}).get("Bool", ())
        inputs = [row for row in rows if row.get("Name") == "Logic_Create"]
        if (node.get("Node Index") != index or node.get("Name") != "ActorLogicNpc"
                or node.get("Properties", {}).get("String") != [{"Name": "InstanceName", "Default Value": instance, "Flags": []}]
                or inputs != [expected] or node.get("Queries") != [source]
                or node.get("Plugs") != {"Generic": [{"Node Index": source, "Name": "Logic_Create"}]}):
            raise _invalid()
        header = 0x74 + index * 0x3c
        parameter = struct.unpack_from("<I", raw, header + 0x14)[0]
        base, count = struct.unpack_from("<II", raw, parameter + 0x40)
        item = bool_pool + (base + rows.index(inputs[0])) * 0x10
        if (struct.unpack_from("<h", raw, header + 2)[0] != index or count != len(rows)
                or struct.unpack_from("<H", raw, header + 0x26)[0] != 1 or raw[parameter + 0x90] != 1
                or struct.unpack_from("<hhII", raw, item + 4) != (source, 1, 0, 1)):
            raise _invalid()
        struct.pack_into("<hhI", result, item + 4, -1, 0, 0x01800000)
        struct.pack_into("<H", result, header + 0x26, 0)
        result[parameter + 0x90] = 0
        allowed.update(range(item + 4, item + 12))
        allowed.update(range(header + 0x26, header + 0x28))
        allowed.add(parameter + 0x90)
        inputs[0].update({"Node Index": -1, "Output Index": 0, "Flags": ["Uses Default", "Is Output"]})
        node["Queries"], node["Plugs"] = [], {}
    result = bytes(result)
    if (any(before != after and index not in allowed for index,(before,after) in enumerate(zip(raw,result)))
            or ainb.AINB.from_binary(result).as_dict() != document):
        raise _invalid()
    return result


def _validate_show_item_routes(raw, actor, settings, patched_flow):
    """Keep actor parameters native and verify every item route is guarded.

    The native item-selection menu already calls an entry in the same NPC flow.
    Editing its GameParameter fields is unnecessary and can break native preload.
    Ordinary talk handles owned items hidden by the single adult-trade menu slot.
    """
    from oot_rando.formats import byml_codec
    from oot_rando.patching.event_patch import _flow
    from oot_rando.patching.soul_adapter import murmur3
    doc = byml_codec.load(raw)
    wanted = ({"Item_PocketCucco"} if actor == TALON_FLOW else {
        row["required_actor"] for row in TRADE_CHECKS.values() if row["flow"] == actor and row["required_actor"]})
    required = {murmur3(name[5:]) for name in wanted}
    chart = _flow(patched_flow).flowchart
    points = {point.name: point.main_event.v for point in chart.entry_points}
    rows = doc["root"].get("ShowItemReplaceEventParamList", ())
    found = set()
    for row in rows:
        event = row.get("EventName", "")
        prefix, suffix = "Work/Event/EventSetting/", ".engine__event__EventSettingParam.gyml"
        if not event.startswith(prefix) or not event.endswith(suffix):
            raise _invalid()
        setting = settings.get(event[len(prefix):-len(suffix)])
        if not setting or setting.get("FlowchartFileName") != "Work/Event/EventFlow/" + actor + ".evfc":
            raise _invalid()
        point = points.get(setting.get("EntryPointName"))
        if point is None or not point.name.startswith(PREFIX):
            raise _invalid()
        found.add(row.get("ShowItemType"))
    if chart.name != actor or not required <= found:
        raise _invalid()
    return len(rows)


def _messages(frames, read, codec):
    from oot_rando.formats import byml_codec, msbt
    from oot_rando.formats.inspect_resources import sarc
    for path in frames:
        old = read(path)
        members = sarc(codec.decode(old))
        french = Path(path).name[2:4] == "fr"
        texts = {NOTHING: ("Il n'y a rien d'autre à échanger ici pour le moment." if french
                           else "There is nothing else to trade here right now."),
                 NEEDS_BOTTLE: ("Il te faut une bouteille vide pour cet échange." if french
                                else "You need an empty bottle for this trade.")}
        for name in sorted({row["flow"] for row in TRADE_CHECKS.values()}):
            member = "EventFlowMsg/" + name + ".msbt"
            if member not in members:
                raise _invalid()
            table = msbt.load(members[member])
            for label, text in texts.items():
                if label in table.labels:
                    if table.get(label) != text.encode("utf-8") + b"\0":
                        raise _invalid()
                else:
                    table.add(label, text)
            members[member] = msbt.dump(table)
        yield path, byml_codec.build_sarc(members)


def prepare_trade_events(romfs, mod, roster, settings):
    """Prepare only full-shuffle rooms; legacy bonus rooms are left untouched."""
    if not settings.get("adult_trade_shuffle"):
        return {}
    from oot_rando.formats import byml_codec
    from oot_rando.formats.inspect_resources import sarc
    from oot_rando.game.resource_allocations import grow_resources
    from oot_rando.patching import event_info
    from oot_rando.patching.event_patch import _flow
    romfs, mod = Path(romfs), Path(mod)
    if mod.name != "romfs" or mod.parent.name != "Archipelago":
        raise ValueError(tr("Invalid adult trade staging folder."))
    records = trade_records(roster)
    codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
    cache = {}
    def read(path):
        if path not in cache:
            target = mod / path
            cache[path] = (target if target.is_file() else romfs / path).read_bytes()
        return cache[path]
    def decoded(path):
        return codec.decode(read(path)) if path.endswith(".zs") else read(path)
    callbacks = {point.name for point in _flow(decoded(FLOW_ROOT + GET + ".bfevfl.zs")).flowchart.entry_points}
    if not {event_name(row["id"]) for row in records} <= callbacks:
        raise ValueError(tr("Adult trade reward entries must be prepared before the NPC routes."))
    modified = {}
    by_flow = defaultdict(list)
    for row in records:
        by_flow[row["flow"]].append(row)
    for name, rows in by_flow.items():
        path = event_info.flow_path(name)
        modified[path] = patch_trade_flow(decoded(path), rows, name)
    modified[event_info.flow_path(TALON_FLOW)] = patch_talon_flow(decoded(event_info.flow_path(TALON_FLOW)))
    modified[event_info.flow_path(SHARED)] = patch_trade_timers(decoded(event_info.flow_path(SHARED)))
    movie = event_info.flow_path("Dm_DeathMtTrail_0050")
    modified[movie] = patch_trade_cutscene(decoded(movie))
    modified[LOST_WOOD] = patch_trade_scene(decoded(LOST_WOOD))
    modified[LOST_LOGIC] = patch_trade_logic(decoded(LOST_LOGIC))
    event_settings = byml_codec.load(decoded(SETTINGS))["root"]
    native_settings = {row["__RowId"]: row for row in event_settings}
    recipients = set(by_flow) | {TALON_FLOW}
    native_show_routes = 0
    for name in sorted(recipients):
        path = "Pack/Actor/" + name + ".pack.zs"
        members = sarc(decoded(path))
        member = "GameParameter/ShowItemReplaceEventParam/" + name + ".game__event__ShowItemReplaceEventParam.bgyml"
        if member not in members:
            raise _invalid()
        native_show_routes += _validate_show_item_routes(members[member], name, native_settings,
                                                        modified[event_info.flow_path(name)])
    frames = sorted({"Mals/" + path.name for root in (romfs, mod) for path in (root / "Mals").glob("*.Product.110.sarc.zs")})
    if not frames:
        raise _invalid()
    modified.update(_messages(frames, read, codec))
    flows = {event_info.flow_name(path): raw for path, raw in modified.items() if event_info.flow_name(path)}
    original = lambda name: decoded(event_info.flow_path(name))
    current = lambda name: flows.get(name) if name in flows else original(name)
    added = event_info.new_subflows(flows, original)
    analyzed, preload = event_info.add_subflow_dependencies(decoded(ANALYZED), event_settings, added, current)
    modified[ANALYZED] = analyzed
    children = event_info.new_transitions(flows, original)
    modified[ANALYZED], child_report = event_info.add_child_events(modified[ANALYZED], event_settings, children, current)
    growth = {path: max(0, len(raw) - len(decoded(path))) for path, raw in modified.items()}
    table, allocations = grow_resources(decoded(REST), growth)
    encoded = {path: codec.encode(raw, read(path)) if path.endswith(".zs") else raw for path, raw in modified.items()}
    encoded[REST] = codec.encode(table, read(REST))
    for path, content in encoded.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return dict(locations=len(records), npc_flows=len(recipients), native_show_routes=native_show_routes, messages=len(frames),
                preloads=len(preload), child_events=len(child_report), allocations=allocations)
