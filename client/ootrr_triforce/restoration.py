"""Restore journaled AP rewards into an older save without a network ACK.

Only exported AP locations participate. Their saved location flags commit with
the local item effect; another player's location restores only its used state.
"""
import copy
import json
from pathlib import Path

from .catalog import (AP_SKULL_CHECKS, CHESTS, CHECK_FLAGS, ITEM_DATA, ITEM_IDS,
                      LOCATION_IDS, SHOP_CHECKS, SKULL_CHECKS, TRADE_CHECKS)
from .cursor_resource import append_transient_index
from .i18n import tr
from .mod_codec import Codec

FLOW_NAME = "GetPouchContent"
FLOW_PATH = "Event/EventFlow/GetPouchContent.bfevfl.zs"
GAME_DATA = "GameData/GameDataList.Product.110.byml.zs"
REST = "System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs"
PREFIX = "OOTRR_APRestore_"
RESULT = "Archipelago.RestoreResult"
MARKER = "Archipelago/restore-v1.json"
GRANT = "OOTRR_APRestoreQuietGrant"


def _invalid():
    return ValueError(tr("Invalid Archipelago restoration metadata."))


def event_name(location_id):
    return PREFIX + str(location_id)


def restoration_records(roster):
    """Resolve only known AP identities and verify each native saved hash."""
    from oot_rando.patching.soul_adapter import murmur3
    records = []
    for name, reward in sorted(roster.items()):
        counters = []
        if name in CHESTS:
            flags = ["IsTreasureBoxOpen." + str(row["actor"]) for row in CHESTS[name]]
        elif name in SHOP_CHECKS:
            flags = [SHOP_CHECKS[name]["flag_name"]]
            counters = list(SHOP_CHECKS[name]["counters"])
        elif name in AP_SKULL_CHECKS:
            flags = [SKULL_CHECKS[name]["flag_name"]]
        elif name in TRADE_CHECKS:
            flags = [TRADE_CHECKS[name]["flag_name"]]
        else:
            raise _invalid()
        if [murmur3(flag) for flag in flags] != CHECK_FLAGS[name]:
            raise _invalid()
        if not isinstance(reward, dict) or type(reward.get("local")) is not bool:
            raise _invalid()
        local = reward["local"]
        item = reward.get("item")
        if local and (item not in ITEM_DATA or reward.get("item_id", ITEM_IDS[item]) != ITEM_IDS[item]):
            raise _invalid()
        records.append(dict(name=name, id=LOCATION_IDS[name], flags=list(dict.fromkeys(flags)),
                            counters=counters, local=local, item=item if local else None,
                            wake_talon=name in TRADE_CHECKS and TRADE_CHECKS[name]["wake_talon"]))
    return records


def _native_source(editor):
    """Select the original native fallback in an in-memory copy of a skull dispatcher."""
    from evfl.common import Argument
    from evfl.event import ActionEvent, SwitchEvent
    from evfl.util import make_index
    from .ap_skulls import PREFIX as SKULL_PREFIX, SCRATCH
    point = next((point for point in editor.chart.entry_points if point.name == FLOW_NAME), None)
    if point is None:
        raise _invalid()
    node = point.main_event.v
    if node is None or not node.name.startswith(SKULL_PREFIX):
        return
    if (node.name != SKULL_PREFIX + "Select" or not isinstance(node.data, ActionEvent)
            or str(node.data.actor.v.identifier) != "GameDataActor"
            or node.data.actor_action.v.v != "EventTriggerSetGameDataString64"
            or node.data.params is None):
        raise _invalid()
    params = node.data.params.data
    if (set(params) != {"GameDataName", "Index", "Value"} or params["GameDataName"] != SCRATCH
            or params["Index"] != -1 or not isinstance(params["Value"], Argument)
            or str(params["Value"]) != "ActorName"):
        raise _invalid()
    node, seen = node.data.nxt.v, set()
    if node is not None and node.name == SKULL_PREFIX + "SelectReady":
        if (not isinstance(node.data, ActionEvent)
                or str(node.data.actor.v.identifier) != "EventSystemActor"
                or node.data.actor_action.v.v != "EventWait"
                or node.data.params is None
                or dict(node.data.params.data) != {"Frames": 1, "IsWaitEnd": True}):
            raise _invalid()
        node = node.data.nxt.v
    while node is not None and node.name.startswith(SKULL_PREFIX):
        if node in seen or not isinstance(node.data, SwitchEvent):
            raise _invalid()
        seen.add(node)
        data = node.data
        if (str(data.actor.v.identifier) != "GameDataActor"
                or data.actor_query.v.v != "EventQueryIsGameDataString64"
                or data.params is None or set(data.cases) != {0, 1}):
            raise _invalid()
        params = data.params.data
        if (set(params) != {"GameDataName", "Index", "Value"} or params["GameDataName"] != SCRATCH
                or params["Index"] != -1 or type(params["Value"]) is not str
                or not params["Value"].startswith(("Item_AP_", "Obj_AP_"))):
            raise _invalid()
        node = data.cases[1].v
    if not seen or node is None:
        raise _invalid()
    point.main_event = make_index(node)


def build_restoration_flow(raw, roster):
    """Append quiet, location-bound restoration entries; never advance AP history."""
    from evfl.common import Argument
    from evfl.entry_point import EntryPoint
    from evfl.event import SubFlowEvent
    from evfl.util import make_index
    from oot_rando.patching.event_info import reachable
    from oot_rando.patching.progressive import FlowEditor, link
    from .native_presentations import append_recipe, append_tier_choice, copy_entry
    from .receipt_events import _action, _silent_grant

    records = restoration_records(roster)
    if not records:
        return raw, {}
    editor = FlowEditor(raw, FLOW_PATH)
    chart = editor.chart
    if chart.name != FLOW_NAME or any(point.name.startswith(PREFIX) for point in chart.entry_points):
        raise _invalid()
    grant_entry = None
    if any(record["local"] for record in records):
        native = FlowEditor(raw, "Native restoration inventory source")
        _native_source(native)
        _silent_grant(native, None, entry_name=GRANT + "Source", prefix=GRANT + "Source")
        grant_entry = copy_entry(
            native.chart, editor, GRANT + "Source", GRANT,
            skip=lambda event: _action(event) in {"EventTriggerSetForGetWindow", "EventTriggerSetHavePlayedGetEvent"})

    def status(stem, value):
        return editor.action(stem, "GameDataActor", "EventTriggerSetGameDataInt",
                             {"GameDataName": RESULT, "Index": -1, "Value": value})

    entries = {}
    trade_mode = bool(set(roster).intersection(TRADE_CHECKS))
    for record in records:
        stem = event_name(record["id"])
        done = status(stem + "_Done", record["id"])
        save = editor.action(stem + "_Save", "GameSystemActor", "EventTriggerRequestAutoSave", None)
        link(save, done)
        commit = save
        if trade_mode:
            from .trade_state import append_reconcile
            commit = append_reconcile(editor, stem + "_TradeSettle", save)
        # Sold-out counters are location state, not a second purchase/payment.
        for index, counter in reversed(list(enumerate(record["counters"]))):
            sold = editor.action(stem + "_Sold" + str(index), "GameDataActor", "EventTriggerSetGameDataInt",
                                 {"GameDataName": counter, "Index": -1, "Value": 1})
            link(sold, commit)
            commit = sold
        for index, flag in reversed(list(enumerate(record["flags"]))):
            opened = editor.action(stem + "_Flag" + str(index), "GameDataActor", "EventTriggerSetGameDataBool",
                                   {"GameDataName": flag, "Index": -1, "Value": True})
            link(opened, commit)
            commit = opened
        if record["wake_talon"]:
            from .trade_catalog import TALON_AWAKE
            awake = editor.action(stem + "_Talon", "GameDataActor", "EventTriggerSetGameDataBool",
                                  {"GameDataName": TALON_AWAKE, "Index": -1, "Value": True})
            link(awake, commit)
            commit = awake

        reward = commit
        if record["local"]:
            metadata = ITEM_DATA[record["item"]]
            core_name = stem + "_Pouch"
            recipe = append_recipe(editor, metadata, core_name, grant_entry, commit, pickup=True)
            if isinstance(recipe.data, SubFlowEvent) and recipe.data.entry_point_name == grant_entry:
                recipe.data.params.data["IsShowNumDisplay"] = False
                recipe.data.params.data["IsTreasureBox"] = False
                editor.expected[recipe.name] = dict(recipe.data.params.data)
                link(recipe, commit)
            core = EntryPoint(core_name)
            core.main_event = make_index(recipe)
            chart.entry_points.append(core)

            def give(branch, actor):
                return editor.subflow(branch + "_Give", "", core_name, {"ActorName": actor})

            reward = append_tier_choice(editor, metadata, stem, give)
            if metadata.get("bottle_item") and metadata.get("pouch_special") == "NotPushToPouch":
                deferred = status(stem + "_Deferred", -record["id"])
                reward = editor.switch(stem + "_Bottle", "PouchSystemActor", "EventQueryIsAnyBottleEmpty",
                                       None, reward, deferred)
        # Any existing physical reference proves this reward was already given.
        # Complete the other references, but never repeat its inventory effect.
        guarded = reward
        for index, flag in reversed(list(enumerate(record["flags"]))):
            guarded = editor.switch(stem + "_Checked" + str(index), "GameDataActor", "EventQueryIsGameDataBool",
                                    {"GameDataName": flag, "Index": -1}, commit, guarded)
        begin = status(stem + "_Begin", 0)
        link(begin, guarded)
        point = EntryPoint(stem)
        point.main_event = make_index(begin)
        chart.entry_points.append(point)
        entries[record["id"]] = stem

    for point in chart.entry_points:
        for event in reachable(point.main_event.v):
            if event.name.startswith(PREFIX) and isinstance(event.data, SubFlowEvent):
                index = chart.events.index(event)
                if index not in point._sub_flow_event_indices:
                    point._sub_flow_event_indices.append(index)
    return editor.write(tr("The native Archipelago restoration"))[0], entries


def _status_field(raw):
    from oot_rando.formats import byml_codec
    from oot_rando.patching.soul_adapter import murmur3
    matches = [(kind, row) for kind, rows in byml_codec.load(raw)["root"]["Data"].items()
               if isinstance(rows, list) for row in rows
               if isinstance(row, dict) and row.get("Hash") == murmur3(RESULT)]
    if not matches:
        return False
    if len(matches) != 1:
        raise _invalid()
    kind, row = matches[0]
    if (kind != "Int" or row.get("DefaultValue") != 0 or row.get("SaveFileIndex") != -1
            or row.get("ResetTypeValue") != 8):
        raise _invalid()
    return True


def _register_restorations(modified, entries, read):
    """Register the exact quiet routes and only their actual dependencies."""
    from functools import lru_cache
    from oot_rando.formats import byml_codec
    from oot_rando.patching import chest_flags, event_info
    settings = byml_codec.load(read(chest_flags.EVENT_SETTINGS))
    analyzed = byml_codec.load(read(chest_flags.ANALYZED))
    template = next(row for row in settings["root"] if row["__RowId"] == "Dm_SY_Get")
    analyzed_template = next(row for row in analyzed["root"] if row["__RowId"] == "Dm_SY_Get")
    setting_ids = {row["__RowId"] for row in settings["root"]}
    analyzed_ids = {row["__RowId"] for row in analyzed["root"]}
    analyzed_rows = {row["__RowId"]: row for row in analyzed["root"]}

    @lru_cache(None)
    def current(name):
        path = event_info.flow_path(name)
        return modified[path] if path in modified else read(path)

    memo = {}
    for entry in entries.values():
        if entry in setting_ids or entry in analyzed_ids:
            raise _invalid()
        root = (FLOW_NAME, entry)
        children = event_info.reachable_transitions(root, current, memo)
        dependencies, pending, seen = set(), [root], set()
        while pending:
            call = pending.pop()
            if call in seen:
                continue
            if call == event_info.SWITCH_CALL:
                raise _invalid()
            seen.add(call)
            dependencies.add(call[0])
            pending.extend(memo[call][0] - seen)
        pending = list(children)
        while pending:
            child = pending.pop()
            for descendant in analyzed_rows.get(child, {}).get("ChildEventList", ()):
                if descendant not in children:
                    children.add(descendant)
                    pending.append(descendant)
        row = copy.deepcopy(template)
        row.update(__RowId=entry, EntryPointName=entry,
                   FlowchartFileName="Work/Event/EventFlow/" + FLOW_NAME + ".evfc",
                   EventSettingComponentList=("Work/Event/EventSetting/EventSettingComponentList/"
                                              "FellingInGameFlowchartEvent.engine__event__EventSettingComponentList.gyml"),
                   EventSoundSetting=("Work/Event/GameEventSoundSetting/IgnoreDuckingOnFlowchart."
                                      "game__event__GameEventSoundSetting.gyml"))
        settings["root"].append(row)
        row = {"__RowId": entry, "SubFlowList": sorted(dependencies, key=str.lower),
               "IsPlayerWarpFirstFrame": False}
        for flag in ("IsPlayerEventStartWithClimb", "IsPlayerEventStartWithDrawn"):
            if flag in analyzed_template:
                row[flag] = analyzed_template[flag]
        if children:
            row["ChildEventList"] = sorted(children, key=str.lower)
        analyzed["root"].append(row)
    for document, path in ((settings, chest_flags.EVENT_SETTINGS), (analyzed, chest_flags.ANALYZED)):
        document["root"].sort(key=lambda row: row["__RowId"])
        modified[path] = byml_codec.dump(document)


def prepared_locations(mod, expected):
    """Return opt-in IDs only when their flow, registration and result field exist."""
    from oot_rando.formats import byml_codec
    from oot_rando.patching import chest_flags
    from oot_rando.patching.event_patch import _flow
    mod = Path(mod)
    marker = mod / MARKER
    if not marker.is_file():
        return []
    try:
        proof = json.loads(marker.read_bytes())
        ids = sorted(LOCATION_IDS[name] for name in expected)
        wanted = {event_name(location) for location in ids}
        if (proof != {"version": 1, "locations": ids, "events": sorted(wanted)}
                or not all(type(location) is int for location in ids)):
            raise _invalid()
        codec = Codec((mod / "Pack/ZsDic.pack.zs").read_bytes())
        raw = {path: codec.decode((mod / path).read_bytes())
               for path in (FLOW_PATH, GAME_DATA, chest_flags.EVENT_SETTINGS, chest_flags.ANALYZED)}
        if not _status_field(raw[GAME_DATA]):
            raise _invalid()
        if not wanted <= {point.name for point in _flow(raw[FLOW_PATH]).flowchart.entry_points}:
            raise _invalid()
        settings = {row["__RowId"]: row for row in byml_codec.load(raw[chest_flags.EVENT_SETTINGS])["root"]}
        analyzed = {row["__RowId"]: row for row in byml_codec.load(raw[chest_flags.ANALYZED])["root"]}
        if not wanted <= settings.keys() or not wanted <= analyzed.keys():
            raise _invalid()
        for entry in wanted:
            row = settings[entry]
            if (row.get("EntryPointName") != entry
                    or row.get("FlowchartFileName") != "Work/Event/EventFlow/" + FLOW_NAME + ".evfc"
                    or analyzed[entry].get("IsPlayerWarpFirstFrame") is not False):
                raise _invalid()
        return ids
    except (OSError, ValueError, KeyError, TypeError):
        raise _invalid() from None


def prepare_restoration(romfs, mod, roster):
    """Add the status field and registered AP recovery routes inside staging."""
    from oot_rando.game.resource_allocations import grow_resources
    from oot_rando.patching.soul_adapter import murmur3
    romfs, mod = Path(romfs), Path(mod)
    if mod.name != "romfs" or mod.parent.name != "Archipelago":
        raise _invalid()
    records = restoration_records(roster)
    if not records:
        return {"locations": [], "changed": False}

    def source(path):
        staged = mod / path
        return (staged if staged.is_file() else romfs / path).read_bytes()

    codec = Codec(source("Pack/ZsDic.pack.zs"))
    def read(path):
        return codec.decode(source(path))

    flow, entries = build_restoration_flow(read(FLOW_PATH), roster)
    data = read(GAME_DATA)
    if _status_field(data):
        raise _invalid()
    modified = {FLOW_PATH: flow, GAME_DATA: append_transient_index(data, murmur3(RESULT))}
    _register_restorations(modified, entries, read)
    table, allocations = grow_resources(read(REST),
                                        {path: max(0, len(raw) - len(read(path))) for path, raw in modified.items()})
    modified[REST] = table
    encoded = {path: codec.encode(raw, source(path)) for path, raw in modified.items()}
    for path, frame in encoded.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(frame)
    # A staged dictionary copy lets native-session activation verify the exact
    # written resources without trusting an in-memory list or a stale cache.
    dictionary = mod / "Pack/ZsDic.pack.zs"
    if not dictionary.is_file():
        dictionary.parent.mkdir(parents=True, exist_ok=True)
        dictionary.write_bytes(source("Pack/ZsDic.pack.zs"))
    proof = {"version": 1, "locations": sorted(entries), "events": sorted(entries.values())}
    target = mod / MARKER
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(proof, separators=(",", ":")) + "\n", encoding="utf-8")
    if prepared_locations(mod, roster) != sorted(entries):
        raise _invalid()
    return {"locations": sorted(entries), "changed": True, "allocations": allocations}
