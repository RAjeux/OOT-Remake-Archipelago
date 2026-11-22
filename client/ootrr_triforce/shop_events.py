"""Commit AP shelf purchases after the shop's successful native grant.

Native prices, payment, item presentation and sold-out checks stay in DisplayShop.
Unique shelf actors have no Zelda inventory effect. Local rewards use the same
native grant recipes as physical chests, without a network received-item cursor.
Their capacity question is bypassed because NotPushToPouch presentation actors
otherwise reach the native error branch.
"""
from .i18n import tr
from pathlib import Path
import re

from .catalog import ITEM_DATA, SHOP_CHECKS
from .medallions import REST
from .mod_codec import Codec

FLOW_PATH = "Event/EventFlow/DisplayShop.bfevfl.zs"
POUCH_FLOW_PATH = "Event/EventFlow/GetPouchContent.bfevfl.zs"
ENTRY = "OOTRR_APShopPurchased"
PREFIX = "OOTRR_APShop_"
SELECTED = "Shop_SelectItemName"
CAPACITY_QUERY = "EventQueryCanAddToPorchByGameData"
GRANTS = ((156, "Event281"), (461, "Event543"))
CAPACITY = ((6, "Event77"), (170, "Event303"))
BOTTLE_CAPACITY = (186, "Event325")
SHOP_FLAGS = {record["flag_name"] for record in SHOP_CHECKS.values()}
SHOP_BY_FLAG = {record["flag_name"]: record for record in SHOP_CHECKS.values()}


def _command(event, kind):
    holder = getattr(event.data, "actor_" + kind, None)
    return holder.v.v if holder is not None else None


def _records(records):
    result = []
    actors, flags, counters = set(), set(), set()
    for record in records:
        actor, flag = record.get("actor"), record.get("flag_name")
        counts = record.get("counters")
        metadata = SHOP_BY_FLAG.get(flag) if isinstance(flag, str) else None
        if (not isinstance(actor, str) or not re.fullmatch(r"Item_AP_[A-Za-z0-9_]+", actor)
                or not isinstance(flag, str) or flag not in SHOP_FLAGS
                or not isinstance(counts, (list, tuple)) or not 1 <= len(counts) <= 3
                or any(not isinstance(name, str) or not name or "\0" in name for name in counts)
                or len(set(counts)) != len(counts)
                or list(counts) != metadata["counters"]
                or type(record.get("price")) is not int or not 1 <= record["price"] <= 999):
            raise ValueError(tr('Invalid Archipelago shop metadata.'))
        if actor in actors or flag in flags or set(counts) & counters:
            raise ValueError(tr('Each Archipelago purchase must have its own actor, flag and unique counters.'))
        if "local_item" in record or "native_actor" in record:
            item = record.get("local_item")
            if (not isinstance(item, str) or item not in ITEM_DATA
                    or record.get("native_actor") != ITEM_DATA[item]["actor"]):
                raise ValueError(tr('Unknown local Archipelago item: ') + str(item))
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


def patch_shop_flow(raw, records, *, pouch_raw=None):
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
        raise ValueError(tr('The expected shop flow is missing.'))
    if any(entry.name == ENTRY for entry in chart.entry_points) or any(event.name.startswith(PREFIX) for event in chart.events):
        raise ValueError(tr('Archipelago purchase tracking is already prepared.'))
    original_events = list(chart.events)
    original_entries = list(chart.entry_points)
    local_records = [record for record in records if "local_item" in record]
    def bottle_refill(record):
        metadata = ITEM_DATA.get(record.get("local_item"), {})
        return bool(metadata.get("bottle_item") and metadata.get("pouch_special") == "NotPushToPouch")

    bottle_refusal = None
    if any(bottle_refill(record) for record in records):
        index, name = BOTTLE_CAPACITY
        event = chart.events[index] if index < len(chart.events) else None
        if (event is None or event.name != name or not isinstance(event.data, SwitchEvent)
                or str(event.data.actor.v.identifier) != "PouchSystemActor"
                or _command(event, "query") != "EventQueryIsAnyBottleEmpty"
                or event.data.params is not None
                or set(event.data.cases) != {0, 1}
                or any(case.v is None for case in event.data.cases.values())):
            raise ValueError(tr('Unknown shop capacity condition: ') + name)
        # The authored refusal reselects the shelf and runs NotAvailableTalk.
        # Reusing it avoids paying or closing the AP check when no bottle fits.
        bottle_refusal = event.data.cases[1].v
        if (event.data.cases[0].v.name != "Event240" or bottle_refusal.name != "Event333"
                or not isinstance(bottle_refusal.data, ActionEvent)
                or str(bottle_refusal.data.actor.v.identifier) != "Npc_EventStarter"
                or _command(bottle_refusal, "action") != "EventTriggerShopItemSelect"
                or bottle_refusal.data.params is not None):
            raise ValueError(tr('Unknown shop capacity condition: ') + name)
    grant_entry = None
    if local_records:
        if pouch_raw is None:
            raise ValueError(tr('Native get-item event not found.'))
        from .native_presentations import copy_entry
        from .receipt_events import _action, _silent_grant
        native = FlowEditor(pouch_raw, POUCH_FLOW_PATH)
        _silent_grant(native, None, entry_name=PREFIX + "TemporaryGrant", prefix=PREFIX + "Temporary")
        grant_entry = copy_entry(
            native.chart, editor, PREFIX + "TemporaryGrant", PREFIX + "Native",
            skip=lambda event: _action(event) in {"EventTriggerSetForGetWindow", "EventTriggerSetHavePlayedGetEvent"})
    continuations = {}
    for index, name in GRANTS:
        event = chart.events[index] if index < len(chart.events) else None
        if (event is None or event.name != name or not isinstance(event.data, ActionEvent)
                or str(event.data.actor.v.identifier) != "Npc_EventStarter"
                or _command(event, "action") != "EventTriggerGetItemAtShop"
                or event.data.params is None or event.data.params.data != {"IsGetEvent": False}):
            raise ValueError(tr('Unknown native purchase action: ') + name)
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
            raise ValueError(tr('Unknown shop capacity condition: ') + name)
        gates.append(event)

    def selected(name, actor, yes, no):
        return editor.switch(name, "GameDataActor", "EventQueryIsGameDataString64",
                             {"GameDataName": SELECTED, "Index": -1, "Value": actor}, yes, no)

    # This local entry is reached only after either successful native grant.
    # Counter values are absolute: repeat callbacks cannot increase stock usage.
    hook = None
    for number, record in reversed(list(enumerate(records, 1))):
        tail = editor.action(PREFIX + f"Save{number}", "GameSystemActor", "EventTriggerRequestAutoSave", None)
        for index, name in reversed(list(enumerate(record["counters"]))):
            node = editor.action(PREFIX + f"Sold{number}_{index}", "GameDataActor",
                                 "EventTriggerSetGameDataInt", {"GameDataName": name, "Index": -1, "Value": 1})
            link(node, tail)
            tail = node
        collected = editor.action(PREFIX + f"Collected{number}", "GameDataActor",
                                  "EventTriggerSetGameDataBool",
                                  {"GameDataName": record["flag_name"], "Index": -1, "Value": True})
        link(collected, tail)
        reward = collected
        if "local_item" in record:
            from .native_presentations import append_recipe, append_tier_choice
            metadata = ITEM_DATA[record["local_item"]]
            stem = PREFIX + f"Local{number}"
            core_name = stem + "_Pouch"
            recipe = append_recipe(editor, metadata, core_name, grant_entry, collected)
            # A normal pouch subflow returns here; direct dungeon/cure recipes
            # already terminate at the purchase commit supplied above.
            if (isinstance(recipe.data, SubFlowEvent)
                    and recipe.data.entry_point_name == grant_entry):
                link(recipe, collected)
            core = EntryPoint(core_name)
            core.main_event = make_index(recipe)
            chart.entry_points.append(core)
            def give(branch, actor):
                return editor.subflow(branch + "_Give", "", core_name, {"ActorName": actor})
            reward = append_tier_choice(editor, metadata, stem, give)
            # A retried successful-purchase callback must not grant a local
            # item twice. The saved location flag commits with its effect.
            reward = editor.switch(stem + "_AlreadyCollected", "GameDataActor", "EventQueryIsGameDataBool",
                                   {"GameDataName": record["flag_name"], "Index": -1}, collected, reward)
        hook = selected(PREFIX + f"Which{number}", record["actor"], reward, hook)
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
            available = success
            if bottle_refill(record):
                available = editor.switch(PREFIX + f"Bottle_{gate.name}_{number}", "PouchSystemActor",
                                          "EventQueryIsAnyBottleEmpty", None, success, bottle_refusal)
            root = selected(PREFIX + f"Capacity_{gate.name}_{number}", record["actor"], available, root)
        replaced = sum(_retarget(event, gate, root) for event in original_events)
        for point in original_entries:
            if point.main_event.v is gate:
                point.main_event = make_index(root)
                replaced += 1
        if not replaced:
            raise ValueError(tr('No access to the capacity condition: ') + gate.name)

    # Local subflow calls must be preloaded by every entry that can reach them.
    # Existing OOTRR subflow preload lists retain their original prefix.
    for point in chart.entry_points:
        reached = set(reachable(point.main_event.v))
        for call in [event for event in chart.events if event.name.startswith(PREFIX)
                     and isinstance(event.data, SubFlowEvent)]:
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
            raise ValueError(tr('The native purchase sequence was modified.'))
    for point in parsed.flowchart.entry_points:
        for event in reachable(point.main_event.v):
            if event.name.startswith(PREFIX) and isinstance(event.data, SubFlowEvent):
                if parsed.flowchart.events.index(event) not in point._sub_flow_event_indices:
                    raise ValueError(tr('Missing local purchase preload: ') + point.name)
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
    pouch_raw = codec.decode(source(POUCH_FLOW_PATH)) if any("local_item" in row for row in records) else None
    after = patch_shop_flow(before, records, pouch_raw=pouch_raw)
    table, allocations = grow_resources(codec.decode(table_frame), {FLOW_PATH: max(0, len(after) - len(before))})
    encoded = {FLOW_PATH: codec.encode(after, frame), REST: codec.encode(table, table_frame)}
    for relative, compressed in encoded.items():
        destination = mod / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(compressed)
    return {"purchases": len(records), "grants_hooked": len(GRANTS), "capacity_gates": len(CAPACITY), "allocations": allocations}
