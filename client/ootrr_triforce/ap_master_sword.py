"""Replace only the pedestal's sword grant, retaining the native era change.

Rauru's independent reward and the abstract time-travel event are never removed.
The native item presenter/effect callback is shared with location-bound rewards.
"""
import json
from pathlib import Path

from .catalog import ITEM_DATA, ITEM_IDS
from .i18n import tr
from .master_sword import ACTOR, FLAG_NAME, ITEM, LOCATION, LOCATION_ID
from .mod_codec import Codec

PREFIX = "OOTRR_APMaster_"
FLOW_ROOT = "Event/EventFlow/"
POUCH = "GetPouchContent"
PRESENTER = "Dm_SY_GetInEvent"
DOOR = "DoorOfTime"
ERA = "ReplaceEquipmentForEraChange"
FINAL = "Dm_FinalBattle_0010"
REST = "System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs"
SETTINGS = "RSDB/EventSetting.Product.111.rstbl.byml.zs"
ANALYZED = "RSDB/GameAnalyzedEventInfo.Product.111.rstbl.byml.zs"


def event_name(identifier):
    return PREFIX + "Reward_" + str(identifier)


def _invalid():
    return ValueError(tr("Unsupported Master Sword shuffle event layout."))


def reward_record(roster):
    from oot_rando.patching import ap_item
    reward = roster.get(LOCATION)
    if (not isinstance(reward, dict) or type(reward.get("local")) is not bool
            or not isinstance(reward.get("item"), str) or not reward["item"]
            or not isinstance(reward.get("player"), str) or not reward["player"]):
        raise _invalid()
    local, item = reward["local"], reward["item"]
    if local and (item not in ITEM_DATA or reward.get("item_id", ITEM_IDS[item]) != ITEM_IDS[item]):
        raise _invalid()
    label = ap_item.ap_item(json.dumps([LOCATION, item, reward["player"]], ensure_ascii=False))
    return dict(name=LOCATION, id=LOCATION_ID, flag_name=FLAG_NAME, required_actor=None,
                wake_talon=False, local=local, item=item if local else None,
                actor=ap_item.ap_actor(label))


def _action(node):
    from evfl.event import ActionEvent
    if isinstance(node.data, ActionEvent):
        return str(node.data.actor.v.identifier), node.data.actor_action.v.v
    return None


def _params(node):
    return node.data.params.data if getattr(node.data, "params", None) else {}


def _replace(editor, old, replacement):
    from evfl.util import make_index
    from .shop_events import _retarget
    for node in list(editor.chart.events):
        if node is not replacement:
            _retarget(node, old, replacement)
    for point in editor.chart.entry_points:
        if point.main_event.v is old:
            point.main_event = make_index(replacement)


def _finish(editor):
    from evfl.event import SubFlowEvent
    from oot_rando.patching.event_info import reachable
    for point in editor.chart.entry_points:
        for node in reachable(point.main_event.v):
            if isinstance(node.data, SubFlowEvent):
                index = editor.chart.events.index(node)
                if index not in point._sub_flow_event_indices:
                    point._sub_flow_event_indices.append(index)
    return editor.write("Native Master Sword shuffle")[0]


def patch_draw(raw):
    """Keep the native first draw and commit its AP reward before age change.

    Native Rauru presentation may save while the first-draw flags are already
    written. Calling the guarded reward on later draws too recovers an interrupted
    first draw without either repeating Rauru or losing the pedestal AP check.
    """
    from oot_rando.patching.progressive import FlowEditor, link
    editor = FlowEditor(raw, DOOR)
    if editor.chart.name != DOOR or any(node.name.startswith(PREFIX) for node in editor.chart.events):
        raise _invalid()
    grants = [node for node in editor.chart.events
              if _action(node) == ("PouchSystemActor", "EventTriggerAddOrRemovePouchContent")
              and _params(node).get("Actor") == ACTOR and _params(node).get("Num") == 1]
    if (len(grants) != 2 or not any(node.name == "Event115" for node in grants)
            or not any(node.name.startswith("OOTRRDraw") for node in grants)):
        raise _invalid()
    for node in grants:
        _replace(editor, node, node.data.nxt.v)
    transitions = [node for node in editor.chart.events
                   if _action(node) == ("EventSystemActor", "EventTransition")
                   and _params(node).get("EventName") == "Market_Child_Field_ChildToAdult"]
    if len(transitions) != 2 or not any(node.name == "Event22" for node in transitions):
        raise _invalid()
    for index, node in enumerate(transitions):
        call = editor.subflow(PREFIX + "Draw" + str(index), POUCH, event_name(LOCATION_ID), None)
        link(call, node)
        _replace(editor, node, call)
    return _finish(editor)


def patch_era_equipment(raw):
    """The native era swap only equips a sword that is actually in the pouch."""
    from oot_rando.patching.progressive import FlowEditor, link
    from .ap_skulls import _after_writes
    editor = FlowEditor(raw, ERA)
    if editor.chart.name != ERA or any(node.name.startswith(PREFIX) for node in editor.chart.events):
        raise _invalid()
    forced = [node for node in editor.chart.events
              if _action(node) == ("GameDataActor", "EventTriggerSetGameDataString64")
              and _params(node).get("GameDataName") == "PlayerStatus.AnotherEraEquipWeapon"
              and _params(node).get("Value") == ACTOR]
    copies = [node for node in editor.chart.events
              if _action(node) == ("GameDataActor", "EventTriggerCopyGameDataString64")
              and _params(node).get("DstGameDataName") == "PlayerStatus.EquipWeapon"]
    if len(forced) != 1 or len(copies) != 1:
        raise _invalid()
    node = forced[0]
    empty = editor.action(PREFIX + "EmptyOtherEra", "GameDataActor", "EventTriggerSetGameDataString64",
                          {"GameDataName": "PlayerStatus.AnotherEraEquipWeapon", "Value": "", "Index": -1})
    node_after = node.data.nxt.v
    settled = _after_writes(editor, PREFIX + "OtherEraReady", node_after)
    link(empty, settled)
    link(node, settled)
    held = editor.switch(PREFIX + "OwnForOtherEra", "PouchSystemActor", "EventQueryIsExistInPouch",
                         {"Actor": ACTOR, "Num": 1}, node, empty)
    _replace(editor, node, held)
    # The stored weapon may also come from a prior forced-equipment story
    # scene. Preserve every other weapon; clear only an unowned Master Sword.
    copied = copies[0]
    after = copied.data.nxt.v
    empty = editor.action(PREFIX + "EmptyCurrentEra", "GameDataActor", "EventTriggerSetGameDataString64",
                          {"GameDataName": "PlayerStatus.EquipWeapon", "Value": "", "Index": -1})
    link(empty, after)
    held = editor.switch(PREFIX + "OwnForCurrentEra", "PouchSystemActor", "EventQueryIsExistInPouch",
                         {"Actor": ACTOR, "Num": 1}, after, empty)
    selected = editor.switch(PREFIX + "SelectedMaster", "GameDataActor", "EventQueryIsGameDataString64",
                             {"GameDataName": "PlayerStatus.EquipWeapon", "Value": ACTOR, "Index": -1}, held, after)
    link(copied, _after_writes(editor, PREFIX + "CurrentEraReady", selected))
    return _finish(editor)


def patch_final_recovery(raw):
    """Recover Ganon's knocked-away sword only after the real item was obtained."""
    from oot_rando.patching.progressive import FlowEditor
    editor = FlowEditor(raw, FINAL)
    if editor.chart.name != FINAL or any(node.name.startswith(PREFIX) for node in editor.chart.events):
        raise _invalid()
    grants = [node for node in editor.chart.events
              if _action(node) == ("PouchSystemActor", "EventTriggerAddOrRemovePouchContent")
              and _params(node).get("Actor") == ACTOR and _params(node).get("Num") == 1]
    if len(grants) != 1:
        raise _invalid()
    node = grants[0]
    guard = editor.switch(PREFIX + "RecoverOwnedSword", "GameDataActor", "EventQueryIsGameDataBool",
                          {"GameDataName": "IsGet." + ACTOR, "Index": -1}, node, node.data.nxt.v)
    _replace(editor, node, guard)
    return _finish(editor)


def prepare_master_sword(romfs, mod, roster, settings):
    """Stage this opt-in room's native callbacks, story routes and preloads."""
    if not settings.get("shuffle_master_sword"):
        return {}
    from oot_rando.formats import byml_codec
    from oot_rando.game.resource_allocations import grow_resources
    from oot_rando.patching import event_info
    from .ap_trade import build_trade_rewards
    romfs, mod = Path(romfs), Path(mod)
    if mod.name != "romfs" or mod.parent.name != "Archipelago":
        raise _invalid()
    record = reward_record(roster)
    codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
    cache = {}
    def source(path):
        if path not in cache:
            staged = mod / path
            cache[path] = (staged if staged.is_file() else romfs / path).read_bytes()
        return cache[path]
    def read(path):
        return codec.decode(source(path))
    info = {row["__RowId"]: row for row in byml_codec.load(read("RSDB/PouchActorInfo.Product.111.rstbl.byml.zs"))["root"]}
    pouch, presenter, entries = build_trade_rewards(
        read(event_info.flow_path(POUCH)), read(event_info.flow_path(PRESENTER)), roster,
        native_info=info, ground_raw=read(event_info.flow_path("Dm_SY_Get")), records=[record],
        prefix=PREFIX, event_stem=event_name, reconcile=False)
    changed = {event_info.flow_path(POUCH): pouch, event_info.flow_path(PRESENTER): presenter}
    for name, patch in ((DOOR, patch_draw), (ERA, patch_era_equipment), (FINAL, patch_final_recovery)):
        path = event_info.flow_path(name)
        changed[path] = patch(read(path))
    flows = {event_info.flow_name(path): raw for path, raw in changed.items()}
    original = lambda name: read(event_info.flow_path(name))
    current = lambda name: flows[name] if name in flows else original(name)
    event_settings = byml_codec.load(read(SETTINGS))["root"]
    # Pouch/presenter edits only append private callbacks reached from the
    # changed DoorOfTime routes. Existing public entries remain byte-for-byte
    # in behavior, so analyse the actual callers instead of reparsing every
    # already prepared receipt entry. Closures still use all modified charts.
    routes = {name: flows[name] for name in (DOOR, ERA, FINAL)}
    added = event_info.new_subflows(routes, original)
    changed[ANALYZED], preloads = event_info.add_subflow_dependencies(read(ANALYZED), event_settings, added, current)
    transitions, memo_now, memo_before = {}, {}, {}
    for name, raw in routes.items():
        for entry in event_info.entry_names(raw):
            events = (event_info.reachable_transitions((name, entry), current, memo_now)
                      - event_info.reachable_transitions((name, entry), original, memo_before))
            if events:
                transitions[(name, entry)] = events
    changed[ANALYZED], children = event_info.add_child_events(changed[ANALYZED], event_settings, transitions, current)
    table, allocations = grow_resources(read(REST), {path: max(0, len(raw) - len(read(path)))
                                                   for path, raw in changed.items()})
    encoded = {path: codec.encode(raw, source(path)) for path, raw in changed.items()}
    encoded[REST] = codec.encode(table, source(REST))
    for path, content in encoded.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return dict(locations=1, entries=entries, preloads=len(preloads), children=len(children), allocations=allocations)
