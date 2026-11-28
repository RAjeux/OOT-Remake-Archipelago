"""Reconcile consumed local shelves without repeating their inventory effect."""
import json
from pathlib import Path

from .i18n import tr
from .mod_codec import Codec

ENTRY = "OOTRR_APShopTracking"
PREFIX = ENTRY + "_"
RESULT = "Archipelago.ShopTrackingResult"
FLOW_PATH = "Event/EventFlow/GetPouchContent.bfevfl.zs"
GAME_DATA = "GameData/GameDataList.Product.110.byml.zs"
INT_QUERY = "EventQueryIsGameDataInt"


def _invalid(detail):
    return ValueError(tr("Invalid Archipelago shop tracking.") + " " + detail)


def validate_native_query(raw):
    """The original three-way Int ABI, also used by native shelf tier tests.

    Native GetPouchContent uses this comparison for the treasure-game count;
    zero/one/two are less/equal/greater. Keep its complete parameter contract.
    The runtime migration additionally has a controlled sold=1/unsold=0 test.
    """
    from evfl.event import SwitchEvent
    from oot_rando.patching.progressive import FlowEditor
    chart = FlowEditor(raw, "Native shop integer query").chart
    matches = [event for event in chart.events if event.name == "Event10"]
    if len(matches) != 1:
        raise _invalid("Missing native integer query.")
    data = matches[0].data
    if (chart.name != "GetPouchContent" or not isinstance(data, SwitchEvent)
            or str(data.actor.v.identifier) != "GameDataActor"
            or data.actor_query.v.v != INT_QUERY or data.params is None
            or data.params.data != {"GameDataName": "Market_MiniGame_ChoiceTreasure_NumOfHit", "Index": -1, "Value": 4}
            or set(data.cases) != {0, 1, 2} or any(case.v is None for case in data.cases.values())):
        raise _invalid("Unknown native integer query ABI.")


def _local_records(records):
    from .shop_events import _records
    return [record for record in _records(records) if "local_item" in record]


def validate_fields(raw, records):
    """Counters are real, persistent Ints, never aliases in the Bool scanner."""
    from oot_rando.formats import byml_codec
    from oot_rando.patching.soul_adapter import murmur3
    data = byml_codec.load(raw)["root"]["Data"]
    fields = [(record["flag_name"], "Bool", False) for record in records]
    fields += [(counter, "Int", 0) for record in records for counter in record["counters"]]
    wanted = {murmur3(name): (kind, default) for name, kind, default in fields}
    if len(wanted) != len(fields):
        raise _invalid("Native shop field hashes collide.")
    matches = {key: [] for key in wanted}
    status = []
    for kind, rows in data.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = row.get("Hash")
            if key in matches:
                matches[key].append((kind, row))
            if key == murmur3(RESULT):
                status.append((kind, row))
    for key, (kind, default) in wanted.items():
        if len(matches[key]) != 1:
            raise _invalid("Missing or ambiguous native shop field.")
        actual, row = matches[key][0]
        value = row.get("DefaultValue")
        valid_value = type(value) is bool if kind == "Bool" else isinstance(value, int) and not isinstance(value, bool)
        if (actual != kind or not valid_value or value != default
                or row.get("SaveFileIndex") != 0 or row.get("ResetTypeValue") != 8):
            raise _invalid("Shop state is not a persistent native field.")
    if not status:
        return False
    if len(status) != 1:
        raise _invalid("Ambiguous shop tracking status.")
    kind, row = status[0]
    if (kind != "Int" or type(row.get("DefaultValue")) is not int or row["DefaultValue"] != 0
            or row.get("SaveFileIndex") != -1 or row.get("ResetTypeValue") != 8):
        raise _invalid("Invalid transient shop tracking status.")
    return True


def _program(records, opening_entry=None):
    """A deterministic quiet program: queries, absolute commits, then result."""
    program = {}
    done = PREFIX + "Done"
    program[done] = ("action", "EventTriggerSetGameDataInt", {"GameDataName": RESULT, "Index": -1, "Value": 1}, None)
    save = PREFIX + "Save"
    program[save] = ("action", "EventTriggerRequestAutoSave", None, done)
    dirty = PREFIX + "Dirty"
    program[dirty] = ("query", INT_QUERY, {"GameDataName": RESULT, "Index": -1, "Value": -1}, {0: done, 1: save, 2: done})
    # GameData trigger writes enter the native queue. The same pair of FIFO
    # barriers used by trade reconciliation makes them visible to this query.
    following = dirty
    for number in reversed(range(2)):
        name = PREFIX + "Flush" + str(number)
        program[name] = ("action", "EventWait", {"Frames": 1, "IsWaitEnd": True}, following)
        following = name
    for number, record in reversed(list(enumerate(records))):
        stem = PREFIX + str(number)
        commit = following
        for index, counter in reversed(list(enumerate(record["counters"]))):
            name = stem + "_Sold" + str(index)
            program[name] = ("action", "EventTriggerSetGameDataInt", {"GameDataName": counter, "Index": -1, "Value": 1}, commit)
            commit = name
        name = stem + "_Flag"
        program[name] = ("action", "EventTriggerSetGameDataBool", {"GameDataName": record["flag_name"], "Index": -1, "Value": True}, commit)
        commit = name
        name = stem + "_MarkDirty"
        program[name] = ("action", "EventTriggerSetGameDataInt", {"GameDataName": RESULT, "Index": -1, "Value": -1}, commit)
        commit = name
        query = following
        for index, counter in reversed(list(enumerate(record["counters"]))):
            name = stem + "_Counter" + str(index)
            program[name] = ("query", INT_QUERY, {"GameDataName": counter, "Index": -1, "Value": 0}, {0: query, 1: query, 2: commit})
            query = name
        complete = following
        for index, counter in reversed(list(enumerate(record["counters"]))):
            name = stem + "_Complete" + str(index)
            program[name] = ("query", INT_QUERY, {"GameDataName": counter, "Index": -1, "Value": 0}, {0: commit, 1: commit, 2: complete})
            complete = name
        name = stem + "_Checked"
        program[name] = ("query", "EventQueryIsGameDataBool", {"GameDataName": record["flag_name"], "Index": -1}, {0: complete, 1: query})
        following = name
    if opening_entry is not None:
        from .opening_rewards import ENTRY as OPENING_ENTRY
        if opening_entry != OPENING_ENTRY:
            raise _invalid("Unknown startup reconciliation entry.")
        name = PREFIX + "Opening"
        program[name] = ("subflow", opening_entry, None, following)
        following = name
    begin = PREFIX + "Begin"
    program[begin] = ("action", "EventTriggerSetGameDataInt", {"GameDataName": RESULT, "Index": -1, "Value": 0}, following)
    return program, begin


def _signature(event):
    from evfl.event import ActionEvent, SwitchEvent, SubFlowEvent
    data = event.data
    params = data.params.data if getattr(data, "params", None) is not None else None
    if isinstance(data, ActionEvent):
        value = ("action", data.actor_action.v.v, params, data.nxt.v.name if data.nxt.v else None)
        owner = ("EventSystemActor" if value[1] == "EventWait" else
                 "GameSystemActor" if value[1] == "EventTriggerRequestAutoSave" else "GameDataActor")
    elif isinstance(data, SwitchEvent):
        value = ("query", data.actor_query.v.v, params, {key: target.v.name if target.v else None for key, target in data.cases.items()})
        owner = "GameDataActor"
    elif isinstance(data, SubFlowEvent):
        from .opening_rewards import ENTRY as OPENING_ENTRY
        if data.res_flowchart_name or data.entry_point_name != OPENING_ENTRY or params is not None:
            raise _invalid("Tracking contains an unknown startup call.")
        return json.dumps(("subflow", data.entry_point_name, None, data.nxt.v.name if data.nxt.v else None), sort_keys=True)
    else:
        raise _invalid("Tracking contains a grant or foreign flow.")
    if str(data.actor.v.identifier) != owner:
        raise _invalid("Tracking has an unexpected actor binding.")
    return json.dumps(value, sort_keys=True)


def build_tracking_flow(raw, records, *, opening_entry=None):
    """Append a quiet entry, or validate its exact previously written program."""
    from evfl.entry_point import EntryPoint
    from evfl.util import make_index
    from oot_rando.patching.progressive import FlowEditor, link
    records = _local_records(records)
    if not records and opening_entry is None:
        return raw, False
    editor = FlowEditor(raw, "Native shop tracking")
    if editor.chart.name != "GetPouchContent":
        raise _invalid("Unexpected tracking flow.")
    program, begin = _program(records, opening_entry)
    if opening_entry is not None and sum(p.name==opening_entry for p in editor.chart.entry_points)!=1:
        raise _invalid("Missing startup reconciliation target.")
    def validate_wait_actor():
        from oot_rando.patching.event_patch import GAMEDATA_ACTOR_PARAMS
        matches = [actor for actor in editor.chart.actors if str(actor.identifier) == "EventSystemActor"]
        if (len(matches) != 1 or matches[0].params is None
                or matches[0].params.data != GAMEDATA_ACTOR_PARAMS or matches[0].concurrent_clips != 1):
            raise _invalid("Unknown native queued-write barrier binding.")
    entries = [point for point in editor.chart.entry_points if point.name == ENTRY]
    owned = [event for event in editor.chart.events if event.name.startswith(PREFIX)]
    existing = {event.name: event for event in owned}
    if entries or existing:
        if (len(entries) != 1 or len(existing) != len(owned) or set(existing) != set(program) or entries[0].main_event.v is not existing.get(begin)
                or entries[0]._sub_flow_event_indices != ([editor.chart.events.index(existing[PREFIX+"Opening"])] if opening_entry else [])):
            raise _invalid("Tracking entry differs from its room selection.")
        validate_wait_actor()
        for name, expected in program.items():
            if _signature(existing[name]) != json.dumps(expected, sort_keys=True):
                raise _invalid("Tracking program differs from its quiet commit.")
        return raw, False
    events = {}
    for name, (kind, command, params, _) in program.items():
        if kind == "action":
            if command == "EventWait":
                from .ap_skulls import _after_writes
                events[name] = _after_writes(editor, name, None)
            else:
                actor = "GameSystemActor" if command == "EventTriggerRequestAutoSave" else "GameDataActor"
                events[name] = editor.action(name, actor, command, params)
        elif kind == "query":
            events[name] = editor.switch(name, "GameDataActor", command, params, None, None)
        else:
            events[name] = editor.subflow(name, "", command, None)
    for name, (kind, _, _, target) in program.items():
        if kind in ("action", "subflow"):
            link(events[name], events.get(target))
        else:
            events[name].data.cases = {key: make_index(events[value]) for key, value in target.items()}
    point = EntryPoint(ENTRY)
    point.main_event = make_index(events[begin])
    if opening_entry is not None:
        point._sub_flow_event_indices = [editor.chart.events.index(events[PREFIX+"Opening"])]
    editor.chart.entry_points.append(point)
    validate_wait_actor()
    if len(editor.chart.events) >= 65535:
        raise _invalid("Tracking exceeds the native event capacity.")
    return editor.write("Native shop tracking")[0], True


def prepare_shop_tracking(romfs, mod, roster, settings):
    """Stage only validated local stock/flags and an unsaved completion field."""
    from .ap_shops import shop_records
    from .cursor_resource import append_transient_index
    from .restoration import _register_restorations
    from .medallions import REST
    from oot_rando.formats import byml_codec
    from oot_rando.patching.soul_adapter import murmur3
    from oot_rando.game.resource_allocations import grow_resources
    records = _local_records(shop_records(roster, settings))
    from .opening_rewards import MARKER as OPENING_MARKER
    if not records and not (Path(mod)/OPENING_MARKER).is_file():
        return {"shops": 0, "changed": False}
    romfs, mod = Path(romfs), Path(mod)
    if mod.name != "romfs" or mod.parent.name != "Archipelago":
        raise _invalid("Tracking destination is not an Archipelago mod.")
    def source(path):
        staged = mod / path
        return (staged if staged.is_file() else romfs / path).read_bytes()
    codec = Codec(source("Pack/ZsDic.pack.zs"))
    def read(path):
        return codec.decode(source(path))
    from .opening_rewards import prepared_reconciliation
    opening_entry = prepared_reconciliation(mod, roster, settings, read)
    if not records and opening_entry is None:
        return {"shops": 0, "changed": False}
    validate_native_query(codec.decode((romfs / FLOW_PATH).read_bytes()))
    current, data = read(FLOW_PATH), read(GAME_DATA)
    present = validate_fields(data, records)
    flow, changed = build_tracking_flow(current, records, opening_entry=opening_entry)
    if present != (not changed):
        raise _invalid("Tracking status and entry disagree.")
    if not changed:
        from oot_rando.patching.chest_flags import EVENT_SETTINGS, ANALYZED
        from oot_rando.patching import event_info
        def current_chart(name):return read(event_info.flow_path(name))
        dependencies=sorted(event_info.closure({("GetPouchContent",ENTRY)},current_chart),key=str.lower)
        children=sorted(event_info.reachable_transitions(("GetPouchContent",ENTRY),current_chart),key=str.lower)
        rows = {p: [row for row in byml_codec.load(read(p))["root"] if row.get("__RowId") == ENTRY] for p in (EVENT_SETTINGS, ANALYZED)}
        if (len(rows[EVENT_SETTINGS]) != 1 or len(rows[ANALYZED]) != 1
                or rows[EVENT_SETTINGS][0].get("EntryPointName") != ENTRY
                or rows[EVENT_SETTINGS][0].get("FlowchartFileName") != "Work/Event/EventFlow/GetPouchContent.evfc"
                or rows[ANALYZED][0].get("SubFlowList") != dependencies
                or rows[ANALYZED][0].get("ChildEventList",[]) != children):
            raise _invalid("Tracking registration differs from its quiet entry.")
        return {"shops": len(records), "changed": False}
    modified = {FLOW_PATH: flow, GAME_DATA: append_transient_index(data, murmur3(RESULT))}
    _register_restorations(modified, {"tracking": ENTRY}, read)
    table, allocations = grow_resources(read(REST), {path: max(0, len(raw) - len(read(path))) for path, raw in modified.items()})
    modified[REST] = table
    encoded = {path: codec.encode(raw, source(path)) for path, raw in modified.items()}
    for path, frame in encoded.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(frame)
    return {"shops": len(records), "changed": True, "allocations": allocations}
