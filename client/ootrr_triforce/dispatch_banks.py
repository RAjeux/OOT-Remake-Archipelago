"""Bound native binding traversal without changing AP pickup selection.

Native EventFlow binds each switch branch recursively. Long room-wide identity
chains therefore need local entry boundaries even though their serialized
indices fit the file format. Each bank is a tail call with typed forwarding;
the existing match, reward and native fallback nodes retain their identities.
"""
from pathlib import Path
import re

from .i18n import tr

LIMIT = 64
PREFIX = "OOTRR_APDispatchBank_"
FLOW_NAMES = ("GetPouchContent", "Dm_SY_Get", "Dm_SY_Get_WithoutPlayer")
REST = "System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs"
MATCH = re.compile(r"OOTRR_APSkull_(?:\d+_Match[01]|Ground\d+_\d+_Match[01]|GroundMessage\d+_\d+_[01])$")


def _invalid():
    return ValueError(tr("Invalid Archipelago pickup dispatcher."))


def _arguments(value):
    from evfl.common import Argument
    if isinstance(value, Argument):
        return {str(value)}
    values = value.values() if isinstance(value, dict) else value if isinstance(value, (tuple, list)) else ()
    result = set()
    for child in values:
        result.update(_arguments(child))
    return result


def _forwarding(target):
    from oot_rando.patching.event_info import reachable
    names = set()
    for event in reachable(target):
        params = getattr(event.data, "params", None)
        if params is not None:
            names.update(_arguments(params.data))
        actor = getattr(event.data, "actor", None)
        if actor is not None and actor.v.argument_name:
            names.add(actor.v.argument_name)
    return sorted(names)


def _edges(event):
    data = event.data
    out = {}
    for name in ("nxt", "join"):
        if hasattr(data, name):
            value = getattr(data, name).v
            out[name] = value.name if value else None
    if hasattr(data, "cases"):
        out["cases"] = {key: value.v.name if value.v else None for key, value in data.cases.items()}
    if hasattr(data, "forks"):
        out["forks"] = [value.v.name if value.v else None for value in data.forks]
    return out


def _actor_contract(actor):
    return (actor.identifier, actor.argument_name,
            actor.argument_entry_point.v.name if actor.argument_entry_point.v else None,
            actor.concurrent_clips, actor.params.data if actor.params is not None else None,
            tuple(holder.v for holder in actor.actions), tuple(holder.v for holder in actor.queries))


def bank_dispatch_flow(raw, flow_name):
    """Return unchanged bytes or validated local banks for one known AP chart.

    A partial, renamed or modified existing bank is rejected. Native charts
    without AP identity matches are a no-op. Existing entries are never renamed
    and no original parameter, participant, reward or true branch is edited.
    """
    from evfl.common import Argument
    from evfl.entry_point import EntryPoint
    from evfl.event import SubFlowEvent, SwitchEvent
    from evfl.util import make_index
    from oot_rando.patching.event_info import analysis_scope, entry_calls, entry_transitions
    from oot_rando.patching.progressive import FlowEditor

    if flow_name not in FLOW_NAMES:
        raise _invalid()
    editor = FlowEditor(raw, flow_name)
    chart = editor.chart
    if chart.name != flow_name:
        raise _invalid()
    original_events, original_entries = list(chart.events), list(chart.entry_points)
    events = {event.name: event for event in chart.events}
    entries = {point.name: point for point in chart.entry_points}
    if len(events) != len(chart.events) or len(entries) != len(chart.entry_points):
        raise _invalid()
    bank_events = {event for event in chart.events if event.name.startswith(PREFIX)}
    bank_entries = {point for point in chart.entry_points if point.name.startswith(PREFIX)}
    matches = {event for event in chart.events if MATCH.fullmatch(event.name)}
    if not matches:
        if bank_events or bank_entries:
            raise _invalid()
        return raw, dict(changed=False, chains=0, banks=0)
    for event in matches:
        data = event.data
        params = data.params.data if getattr(data, "params", None) is not None else {}
        if (not isinstance(data, SwitchEvent) or set(data.cases) != {0, 1}
                or str(data.actor.v.identifier) != "GameDataActor"
                or data.actor_query.v.v != "EventQueryIsGameDataString64"
                or set(params) != {"GameDataName", "Index", "Value"}
                or params["GameDataName"] != "Archipelago.SelectedPickup"
                or type(params["Index"]) is not int or params["Index"] != -1
                or type(params["Value"]) is not str
                or not params["Value"].startswith(("Item_AP_", "Obj_AP_"))):
            raise _invalid()

    def false_target(event):
        target = event.data.cases[1].v
        if target in bank_events:
            data = target.data
            if (not isinstance(data, SubFlowEvent) or data.res_flowchart_name or data.nxt.v is not None
                    or data.entry_point_name not in entries
                    or entries[data.entry_point_name] not in bank_entries):
                raise _invalid()
            return entries[data.entry_point_name].main_event.v
        return target

    heads = matches - {false_target(event) for event in matches if false_target(event) in matches}
    seen, chains = set(), []
    for head in sorted(heads, key=lambda event: event.name):
        chain, current = [], head
        while current in matches:
            if current in seen:
                raise _invalid()
            seen.add(current)
            chain.append(current)
            current = false_target(current)
        chains.append(chain)
    if seen != matches:
        raise _invalid()
    cuts, used_events, used_entries = [], set(), set()
    has_banks = bool(bank_events or bank_entries)
    for chain_index, chain in enumerate(chains):
        for offset in range(LIMIT, len(chain), LIMIT):
            previous, target = chain[offset - 1], chain[offset]
            name = PREFIX + str(chain_index) + "_" + str(offset // LIMIT)
            arguments = _forwarding(target)
            params = {argument: Argument(argument) for argument in arguments}
            cuts.append((previous, target, name, params))
            if has_banks:
                call = previous.data.cases[1].v
                point = entries.get(name)
                actual = call.data.params.data if call is not None and getattr(call.data, "params", None) else {}
                if (call not in bank_events or call.name != name + "_Call" or point not in bank_entries
                        or not isinstance(call.data, SubFlowEvent) or call.data.entry_point_name != name
                        or point.main_event.v is not target or actual != params
                        or any(not isinstance(value, Argument) for value in actual.values())):
                    raise _invalid()
                used_events.add(call)
                used_entries.add(point)
    if has_banks:
        if used_events != bank_events or used_entries != bank_entries:
            raise _invalid()
        if any(point.variable_defs for point in bank_entries):
            raise _invalid()
        declared = {point.name: list(point._sub_flow_event_indices) for point in bank_entries}
        # Recompute only in memory: an idempotent repeat returns the input bytes,
        # but must not accept a malformed preloading list ignored by the reader.
        chart._set_indexes_from_values()
        if any(declared[point.name] != point._sub_flow_event_indices for point in bank_entries):
            raise _invalid()
        return raw, dict(changed=False, chains=len(chains), banks=len(cuts), validated_existing=True)
    if not cuts:
        return raw, dict(changed=False, chains=len(chains), banks=0)

    old_edges = {event.name: _edges(event) for event in original_events}
    actor_contracts = [_actor_contract(actor) for actor in chart.actors]
    for previous, target, name, params in cuts:
        point = EntryPoint(name)
        point.main_event = make_index(target)
        chart.entry_points.append(point)
        call = editor.subflow(name + "_Call", "", name, params or None)
        previous.data.cases[1] = make_index(call)
        old_edges[previous.name]["cases"][1] = call.name
    result, checked = editor.write("Archipelago pickup dispatcher banks")
    current = checked.flowchart
    if [_actor_contract(actor) for actor in current.actors] != actor_contracts:
        raise _invalid()
    for event in current.events:
        if event.name in old_edges and _edges(event) != old_edges[event.name]:
            raise _invalid()
    if [(point.name, point.main_event.v.name if point.main_event.v else None) for point in current.entry_points
            if not point.name.startswith(PREFIX)] != [(point.name, point.main_event.v.name if point.main_event.v else None)
                                                     for point in original_entries]:
        raise _invalid()
    # Local boundaries must preserve every caller's external preload/transition
    # closure. No RSDB additions are necessary when these sets stay identical.
    with analysis_scope():
        for point in original_entries:
            if (entry_calls(raw, point.name) != entry_calls(result, point.name)
                    or entry_transitions(raw, point.name) != entry_transitions(result, point.name)):
                raise _invalid()
    # The same strict validation is the repeat path and detects broken banks.
    repeated, report = bank_dispatch_flow(result, flow_name)
    if repeated != result or report.get("banks") != len(cuts):
        raise _invalid()
    return result, dict(changed=True, chains=len(chains), banks=len(cuts),
                        max_switches_per_bank=LIMIT,
                        max_direct_subflows=max((len(point._sub_flow_event_indices) for point in current.entry_points), default=0))


def prepare_dispatch_banks(romfs, mod):
    """Final preparation pass; callers seal resource capabilities afterwards."""
    from oot_rando.game.resource_allocations import grow_resources
    from .mod_codec import Codec
    romfs, mod = Path(romfs), Path(mod)
    if mod.name != "romfs" or mod.parent.name != "Archipelago":
        raise _invalid()
    staged = {}
    for name in FLOW_NAMES:
        path = "Event/EventFlow/" + name + ".bfevfl.zs"
        if (mod / path).is_file():
            staged[name] = path
    if not staged:
        return {}
    codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
    outputs, growth, report = {}, {}, {}
    for name, path in staged.items():
        frame = (mod / path).read_bytes()
        before = codec.decode(frame)
        after, details = bank_dispatch_flow(before, name)
        if after != before:
            outputs[path] = codec.encode(after, frame)
            growth[path] = max(0, len(after) - len(before))
            report[name] = details
    if not outputs:
        return {}
    table_path = mod / REST
    frame = (table_path if table_path.is_file() else romfs / REST).read_bytes()
    after, allocations = grow_resources(codec.decode(frame), growth)
    outputs[REST] = codec.encode(after, frame)
    # Validate the complete plan before the first staged-resource write.
    for path, frame in outputs.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(frame)
    return dict(flows=report, allocations=allocations)
