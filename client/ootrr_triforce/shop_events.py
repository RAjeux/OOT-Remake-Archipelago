"""Commit AP shelf purchases after the shop's successful native grant.

Native prices, payment, item presentation and sold-out checks stay in DisplayShop.
AP dummy actors have no Zelda inventory effect. Only their capacity question is
bypassed, because NotPushToPouch actors otherwise reach the native error branch.
"""
from pathlib import Path
import re

from .catalog import SHOP_CHECKS
from .medallions import REST
from .mod_codec import Codec

FLOW_PATH = "Event/EventFlow/DisplayShop.bfevfl.zs"
ENTRY = "OOTRR_APShopPurchased"
PREFIX = "OOTRR_APShop_"
SELECTED = "Shop_SelectItemName"
CAPACITY_QUERY = "EventQueryCanAddToPorchByGameData"
GRANTS = ((156, "Event281"), (461, "Event543"))
CAPACITY = ((6, "Event77"), (170, "Event303"))
SHOP_FLAGS = {record["flag_name"] for record in SHOP_CHECKS.values()}


def _command(event, kind):
    holder = getattr(event.data, "actor_" + kind, None)
    return holder.v.v if holder is not None else None


def _records(records):
    result = []
    actors, flags, counters = set(), set(), set()
    for record in records:
        actor, flag = record.get("actor"), record.get("flag_name")
        counts = record.get("counters")
        if (not isinstance(actor, str) or not re.fullmatch(r"Item_AP_[A-Za-z0-9_]+", actor)
                or not isinstance(flag, str) or flag not in SHOP_FLAGS
                or not isinstance(counts, (list, tuple)) or len(counts) != 3
                or any(not isinstance(name, str) or not name or "\0" in name for name in counts)
                or len(set(counts)) != 3
                or type(record.get("price")) is not int or record["price"] < 0):
            raise ValueError("Métadonnées de vente Archipelago invalides.")
        if actor in actors or flag in flags or set(counts) & counters:
            raise ValueError("Chaque vente Archipelago doit avoir son acteur, son drapeau et ses compteurs uniques.")
        actors.add(actor); flags.add(flag); counters.update(counts)
        result.append({**record, "counters": list(counts)})
    return sorted(result, key=lambda record: record["flag_name"])


def _retarget(event, previous, following):
    """Change target references without altering actions, conditions or arguments."""
    from evfl.util import make_index
    data = event.data
    changed = 0
    for attribute in ("nxt", "join"):
        reference = getattr(data, attribute, None)
        if reference is not None and reference.v is previous:
            # Fork joins use RequiredIndex rather than Index; replacing .v
            # keeps that original reference type and its validity rules.
            reference.v = following
            changed += 1
    if hasattr(data, "cases"):
        for key, reference in list(data.cases.items()):
            if reference.v is previous:
                data.cases[key] = make_index(following)
                changed += 1
    if hasattr(data, "forks"):
        for reference in data.forks:
            if reference.v is previous:
                reference.v = following
                changed += 1
    return changed


def patch_shop_flow(raw, records):
    """Return the edited flow; refuse unknown grant/capacity layouts before editing."""
    from evfl.entry_point import EntryPoint
    from evfl.event import ActionEvent, SubFlowEvent, SwitchEvent
    from evfl.util import make_index
    from oot_rando.patching.event_info import reachable
    from oot_rando.patching.progressive import FlowEditor, link

    records = _records(records)
    if not records:
        return raw
    editor = FlowEditor(raw, FLOW_PATH)
    chart = editor.chart
    if chart.name != "DisplayShop":
        raise ValueError("Le flow de boutique attendu est absent.")
    if any(entry.name == ENTRY for entry in chart.entry_points) or any(event.name.startswith(PREFIX) for event in chart.events):
        raise ValueError("Le suivi des achats Archipelago est déjà préparé.")
    original_events = list(chart.events)
    original_entries = list(chart.entry_points)
    continuations = {}
    for index, name in GRANTS:
        event = chart.events[index] if index < len(chart.events) else None
        if (event is None or event.name != name or not isinstance(event.data, ActionEvent)
                or str(event.data.actor.v.identifier) != "Npc_EventStarter"
                or _command(event, "action") != "EventTriggerGetItemAtShop"
                or event.data.params is None or event.data.params.data != {"IsGetEvent": False}):
            raise ValueError("Action d’achat natif inconnue : " + name)
        continuations[name] = event.data.nxt.v
    gates = []
    for index, name in CAPACITY:
        event = chart.events[index] if index < len(chart.events) else None
        if (event is None or event.name != name or not isinstance(event.data, SwitchEvent)
                or str(event.data.actor.v.identifier) != "PouchSystemActor"
                or _command(event, "query") != CAPACITY_QUERY
                or event.data.params is None
                or event.data.params.data != {"GameDataForActorName": SELECTED}
                or set(event.data.cases) != {0, 1, 2} or event.data.cases[0].v is None):
            raise ValueError("Condition de capacité de boutique inconnue : " + name)
        gates.append(event)

    def selected(name, actor, yes, no):
        return editor.switch(name, "GameDataActor", "EventQueryIsGameDataString64",
                             {"GameDataName": SELECTED, "Index": -1, "Value": actor}, yes, no)

    # This local entry is reached only after either successful native grant.
    # Counter values are absolute: repeat callbacks cannot increase stock usage.
    hook = None
    for number, record in reversed(list(enumerate(records, 1))):
        tail = None
        for index, name in reversed(list(enumerate(record["counters"]))):
            node = editor.action(PREFIX + f"Sold{number}_{index}", "GameDataActor",
                                 "EventTriggerSetGameDataInt", {"GameDataName": name, "Index": -1, "Value": 1})
            link(node, tail)
            tail = node
        collected = editor.action(PREFIX + f"Collected{number}", "GameDataActor",
                                  "EventTriggerSetGameDataBool",
                                  {"GameDataName": record["flag_name"], "Index": -1, "Value": True})
        link(collected, tail)
        hook = selected(PREFIX + f"Which{number}", record["actor"], collected, hook)
    entry = EntryPoint(ENTRY)
    entry.main_event = make_index(hook)
    chart.entry_points.append(entry)
    calls = []
    for index, name in GRANTS:
        grant = chart.events[index]
        call = editor.subflow(PREFIX + "After_" + name, "", ENTRY, None)
        link(call, continuations[name])  # includes an existing OOTRR_ShelfGive call
        grant.data.nxt = make_index(call)
        calls.append(call)

    for gate in gates:
        root = gate
        success = gate.data.cases[0].v
        for number, record in reversed(list(enumerate(records, 1))):
            root = selected(PREFIX + f"Capacity_{gate.name}_{number}", record["actor"], success, root)
        replaced = sum(_retarget(event, gate, root) for event in original_events)
        for point in original_entries:
            if point.main_event.v is gate:
                point.main_event = make_index(root)
                replaced += 1
        if not replaced:
            raise ValueError("Aucun accès à la condition de capacité : " + gate.name)

    # Local subflow calls must be preloaded by every entry that can reach them.
    # Existing OOTRR subflow preload lists retain their original prefix.
    for point in chart.entry_points:
        reached = set(reachable(point.main_event.v))
        for call in calls:
            index = chart.events.index(call)
            if call in reached and index not in point._sub_flow_event_indices:
                point._sub_flow_event_indices.append(index)
    result, parsed = editor.write("Le suivi des achats Archipelago")
    parsed_events = {event.name: event for event in parsed.flowchart.events}
    for _, name in GRANTS:
        original_next = continuations[name]
        call = parsed_events[name].data.nxt.v
        if (not isinstance(call.data, SubFlowEvent) or call.data.res_flowchart_name != ""
                or call.data.entry_point_name != ENTRY
                or (call.data.nxt.v.name if call.data.nxt.v else None) != (original_next.name if original_next else None)):
            raise ValueError("La suite native de l’achat a été modifiée.")
    for point in parsed.flowchart.entry_points:
        for event in reachable(point.main_event.v):
            if event.name.startswith(PREFIX) and isinstance(event.data, SubFlowEvent):
                if parsed.flowchart.events.index(event) not in point._sub_flow_event_indices:
                    raise ValueError("Préchargement local d’achat manquant : " + point.name)
    return result


def prepare_shop_events(romfs, mod, records):
    """Write only DisplayShop and its REST allocation into the staging mod RomFS."""
    from oot_rando.game.resource_allocations import grow_resources
    records = _records(records)
    if not records:
        return {}
    romfs, mod = Path(romfs), Path(mod)
    codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())

    def source(relative):
        staged = mod / relative
        return (staged if staged.is_file() else romfs / relative).read_bytes()

    frame, table_frame = source(FLOW_PATH), source(REST)
    before = codec.decode(frame)
    after = patch_shop_flow(before, records)
    table, allocations = grow_resources(codec.decode(table_frame), {FLOW_PATH: max(0, len(after) - len(before))})
    encoded = {FLOW_PATH: codec.encode(after, frame), REST: codec.encode(table, table_frame)}
    for relative, compressed in encoded.items():
        destination = mod / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(compressed)
    return {"purchases": len(records), "grants_hooked": len(GRANTS), "capacity_gates": len(CAPACITY), "allocations": allocations}
