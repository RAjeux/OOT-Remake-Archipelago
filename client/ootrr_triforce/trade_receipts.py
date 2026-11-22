"""Quietly acknowledge replayed trade tokens already spent in the loaded save."""
from pathlib import Path
import copy
import hashlib
import json
import re

from .catalog import ITEM_DATA, ITEM_IDS, TRADE_CHECKS
from .i18n import tr
from .mod_codec import Codec
from .native_presentations import PRESENTER_NAME, PRESENTER_PATH
from .receipt_events import CURSOR_PREFIX, event_name
from .trade_catalog import TRADE_ITEMS

FLOW_PATH = "Event/EventFlow/GetPouchContent.bfevfl.zs"
REST = "System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs"
PREFIX = "OOTRR_APTradeReplay_"
MARKER = "Archipelago/trade-replay-v1.json"
SETTINGS = "RSDB/EventSetting.Product.111.rstbl.byml.zs"
ANALYZED = "RSDB/GameAnalyzedEventInfo.Product.111.rstbl.byml.zs"
CAPABILITY_RESOURCES = (FLOW_PATH, SETTINGS, ANALYZED)


def _invalid():
    return ValueError(tr("Invalid adult trade replay capability."))


def replay_receipts():
    """Protocol item identities mapped to the single check that consumes each."""
    consumed = {row["required_actor"]: row["id"] for row in TRADE_CHECKS.values() if row["required_actor"]}
    return {ITEM_IDS[name]: consumed[ITEM_DATA[name]["actor"]] for name in sorted(TRADE_ITEMS)}


def replay_event(item_id):
    return PREFIX + str(item_id)


def _receipt_nodes(chart, root, presenter=None):
    """Follow receipt helpers across the known pouch/presentation pair."""
    from evfl.event import SubFlowEvent
    from oot_rando.patching.event_info import reachable
    charts = {chart.name: chart}
    if presenter is not None:
        charts[presenter.name] = presenter
    entries = {name: {point.name: point.main_event.v for point in current.entry_points}
               for name, current in charts.items()}
    roots, visited, nodes = [(chart.name, root)], set(), []
    while roots:
        flow, current = roots.pop()
        for node in reachable(current):
            if (flow, node) in visited:
                continue
            visited.add((flow, node))
            nodes.append(node)
            data = node.data
            if isinstance(data, SubFlowEvent):
                destination = data.res_flowchart_name or flow
                if destination not in charts:
                    continue
                if data.entry_point_name not in entries[destination]:
                    raise ValueError(tr("Unknown local item receipt entry."))
                roots.append((destination, entries[destination][data.entry_point_name]))
    return nodes


def patch_trade_receipt_guard(raw, token, *, presenter_raw=None):
    """Preserve an unspent receipt verbatim; a spent token only advances its ACK."""
    from evfl.event import ActionEvent
    from evfl.entry_point import EntryPoint
    from oot_rando.patching.event_patch import _flow
    from evfl.util import make_index
    from oot_rando.patching.progressive import FlowEditor, link
    from .ap_skulls import _after_writes
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{64}", token):
        raise ValueError(tr("Invalid room token for adult trade receipt replay."))
    editor = FlowEditor(raw, "Adult trade receipt replay")
    chart = editor.chart
    if chart.name != "GetPouchContent" or any(node.name.startswith(PREFIX) for node in chart.events):
        raise ValueError(tr("Adult trade receipt replay is already prepared or unsupported."))
    presenter = _flow(presenter_raw).flowchart if presenter_raw is not None else None
    if presenter is not None and presenter.name != PRESENTER_NAME:
        raise ValueError(tr("Unknown native adult trade presentation flow."))
    consumed = {record["required_actor"]: record for record in TRADE_CHECKS.values() if record["required_actor"]}
    entries = {point.name: point for point in chart.entry_points}
    cursor = CURSOR_PREFIX + token
    bindings = []
    for name in sorted(TRADE_ITEMS):
        actor = ITEM_DATA[name]["actor"]
        point = entries.get(event_name(ITEM_IDS[name]))
        if actor not in consumed or point is None or point.main_event.v is None:
            raise ValueError(tr("The room is missing an adult trade item receipt."))
        acknowledgements = []
        for node in _receipt_nodes(chart, point.main_event.v, presenter):
            data = node.data
            if not isinstance(data, ActionEvent) or data.params is None:
                continue
            params = data.params.data
            if str(params.get("GameDataName", "")).startswith(CURSOR_PREFIX):
                if (str(data.actor.v.identifier) != "GameDataActor"
                        or data.actor_action.v.v != "EventTriggerAddOrSubGameDataInt"
                        or params != {"GameDataName": cursor, "Index": -1, "Value": 1}):
                    raise ValueError(tr("An adult trade receipt belongs to a different room."))
                acknowledgements.append(node)
        if not acknowledgements:
            raise ValueError(tr("An adult trade receipt has no room-bound acknowledgement."))
        bindings.append((name, point, consumed[actor]))
    for name, point, record in bindings:
        stem = PREFIX + str(ITEM_IDS[name])
        save = editor.action(stem + "_Save", "GameSystemActor", "EventTriggerRequestAutoSave", None)
        ready = _after_writes(editor, stem + "_Committed", save)
        ack = editor.action(stem + "_Ack", "GameDataActor", "EventTriggerAddOrSubGameDataInt",
                            {"GameDataName": cursor, "Index": -1, "Value": 1})
        link(ack, ready)
        # A host that already knows the consuming check was completed can use
        # this room-bound event before an older save's check flags are restored.
        # Do not set the check here: its own reward still needs restoration.
        quiet = EntryPoint(replay_event(ITEM_IDS[name]))
        quiet.main_event = make_index(ack)
        chart.entry_points.append(quiet)
        guard = editor.switch(stem + "_Spent", "GameDataActor", "EventQueryIsGameDataBool",
                              {"GameDataName": record["flag_name"], "Index": -1}, ack, point.main_event.v)
        point.main_event = make_index(guard)
    return editor.write("Quiet acknowledgement of spent trade tokens")[0]


def _register_quiet_events(settings_raw, analyzed_raw):
    from oot_rando.formats import byml_codec
    settings, analyzed = byml_codec.load(settings_raw), byml_codec.load(analyzed_raw)
    rows, information = settings["root"], analyzed["root"]
    template = next((row for row in rows if row.get("__RowId") == "Dm_SY_Get"), None)
    if template is None:
        raise _invalid()
    existing = {row.get("__RowId") for row in rows + information}
    for item in replay_receipts():
        name = replay_event(item)
        if name in existing:
            raise _invalid()
        row = copy.deepcopy(template)
        row.update(__RowId=name, EntryPointName=name,
                   FlowchartFileName="Work/Event/EventFlow/GetPouchContent.evfc",
                   EventSettingComponentList=("Work/Event/EventSetting/EventSettingComponentList/"
                                              "FellingInGameFlowchartEvent.engine__event__EventSettingComponentList.gyml"),
                   EventSoundSetting=("Work/Event/GameEventSoundSetting/IgnoreDuckingOnFlowchart."
                                      "game__event__GameEventSoundSetting.gyml"))
        rows.append(row)
        information.append(dict(__RowId=name, SubFlowList=["GetPouchContent"], IsPlayerWarpFirstFrame=False))
        existing.add(name)
    for doc in (settings, analyzed):
        doc["root"].sort(key=lambda row: row["__RowId"])
    return {SETTINGS: byml_codec.dump(settings), ANALYZED: byml_codec.dump(analyzed)}


def _validate_quiet_resources(resources, token):
    """Check the final native event graph and registrations before sealing it."""
    from evfl.event import ActionEvent
    from oot_rando.formats import byml_codec
    from oot_rando.patching.event_patch import _flow
    chart = _flow(resources[FLOW_PATH]).flowchart
    expected = {replay_event(item) for item in replay_receipts()}
    points = [point for point in chart.entry_points if point.name.startswith(PREFIX)]
    entries = {point.name: point.main_event.v for point in points}
    if chart.name != "GetPouchContent" or set(entries) != expected or len(points) != len(expected):
        raise _invalid()
    settings = byml_codec.load(resources[SETTINGS])["root"]
    analyzed = byml_codec.load(resources[ANALYZED])["root"]
    for name, root in entries.items():
        node = root
        sequence = (
            ("GameDataActor", "EventTriggerAddOrSubGameDataInt", {"GameDataName": CURSOR_PREFIX + token, "Index": -1, "Value": 1}),
            ("EventSystemActor", "EventWait", {"Frames": 1, "IsWaitEnd": True}),
            ("GameSystemActor", "EventTriggerRequestAutoSave", {}),
        )
        for actor, action, params in sequence:
            actual = node.data.params.data if node is not None and getattr(node.data,"params",None) else {}
            if (node is None or not isinstance(node.data, ActionEvent)
                    or str(node.data.actor.v.identifier) != actor or node.data.actor_action.v.v != action
                    or actual != params or any(type(actual[key]) is not type(value) for key,value in params.items())):
                raise _invalid()
            node = node.data.nxt.v
        if node is not None:
            raise _invalid()
        registration = [row for row in settings if row.get("__RowId") == name]
        details = [row for row in analyzed if row.get("__RowId") == name]
        if (len(registration) != 1 or registration[0].get("EntryPointName") != name
                or registration[0].get("FlowchartFileName") != "Work/Event/EventFlow/GetPouchContent.evfc"
                or not registration[0].get("EventSettingComponentList", "").endswith("/FellingInGameFlowchartEvent.engine__event__EventSettingComponentList.gyml")
                or registration[0].get("EventSoundSetting") != ("Work/Event/GameEventSoundSetting/IgnoreDuckingOnFlowchart."
                                                                "game__event__GameEventSoundSetting.gyml")
                or len(details) != 1 or details[0].get("SubFlowList") != ["GetPouchContent"]
                or details[0].get("IsPlayerWarpFirstFrame") is not False or details[0].get("ChildEventList")):
            raise _invalid()


def finalize_trade_receipts(romfs, mod, token):
    """Seal final resources after other patchers have extended these tables."""
    romfs, mod = Path(romfs), Path(mod)
    if not isinstance(token,str) or not re.fullmatch(r"[0-9a-f]{64}", token):
        raise _invalid()
    codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
    frames = {path: (mod / path).read_bytes() for path in CAPABILITY_RESOURCES}
    _validate_quiet_resources({path: codec.decode(frame) for path, frame in frames.items()}, token)
    marker = dict(schema=1, token=token, receipts={str(key): value for key,value in replay_receipts().items()},
                  resources={path: hashlib.sha256(frame).hexdigest() for path,frame in frames.items()})
    target = mod / MARKER
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return replay_receipts()


def prepared_trade_receipts(prepared, token):
    """Read a capability only when its validated final resources are unchanged."""
    prepared = Path(prepared)
    marker = prepared / MARKER
    if not marker.is_file():
        return {}
    try:
        data = json.loads(marker.read_bytes())
        expected = {str(key): value for key,value in replay_receipts().items()}
        if (not isinstance(data, dict) or type(data.get("schema")) is not int or data.get("schema") != 1
                or data.get("token") != token or not re.fullmatch(r"[0-9a-f]{64}", token)
                or data.get("receipts") != expected
                or any(type(value) is not int for value in data["receipts"].values())
                or not isinstance(data.get("resources"), dict)
                or set(data["resources"]) != set(CAPABILITY_RESOURCES)):
            raise _invalid()
        for path, digest in data["resources"].items():
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise _invalid()
            if hashlib.sha256((prepared / path).read_bytes()).hexdigest() != digest:
                raise _invalid()
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise _invalid() from exc
    return replay_receipts()


def prepare_trade_receipt_guard(romfs, mod, token):
    """Run only for full trade rooms after their ordinary receipts are prepared."""
    from oot_rando.game.resource_allocations import grow_resources
    romfs, mod = Path(romfs), Path(mod)
    if mod.name != "romfs" or mod.parent.name != "Archipelago":
        raise ValueError(tr("Invalid adult trade staging folder."))
    codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
    def source(path):
        target = mod / path
        return (target if target.is_file() else romfs / path).read_bytes()
    frame, table_frame = source(FLOW_PATH), source(REST)
    before = codec.decode(frame)
    after = patch_trade_receipt_guard(before, token, presenter_raw=codec.decode(source(PRESENTER_PATH)))
    changed = {FLOW_PATH: after}
    changed.update(_register_quiet_events(codec.decode(source(SETTINGS)), codec.decode(source(ANALYZED))))
    growth = {path: max(0, len(raw) - len(codec.decode(source(path)))) for path,raw in changed.items()}
    table, allocations = grow_resources(codec.decode(table_frame), growth)
    output = {path: codec.encode(raw, source(path)) for path,raw in changed.items()}
    output[REST] = codec.encode(table, table_frame)
    for path, content in output.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return dict(receipts=len(TRADE_ITEMS), allocations=allocations)
