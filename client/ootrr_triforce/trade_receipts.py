"""Quietly acknowledge replayed trade tokens already spent in the loaded save."""
from pathlib import Path
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
        guard = editor.switch(stem + "_Spent", "GameDataActor", "EventQueryIsGameDataBool",
                              {"GameDataName": record["flag_name"], "Index": -1}, ack, point.main_event.v)
        point.main_event = make_index(guard)
    return editor.write("Quiet acknowledgement of spent trade tokens")[0]


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
    table, allocations = grow_resources(codec.decode(table_frame), {FLOW_PATH: max(0, len(after) - len(before))})
    output = {FLOW_PATH: codec.encode(after, frame), REST: codec.encode(table, table_frame)}
    for path, content in output.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return dict(receipts=len(TRADE_ITEMS), allocations=allocations)
