"""Preserve native get-item offsets for isolated AP display models.

The native Player command adds the displayed actor's PouchContent offset to
its held-item anchor. Receipt aliases deliberately have no pouch behavior.
Forward the missing vertical offset through that command's existing ItemPos
input instead. Native camera, rotation, effects and inventory actors stay exact.
"""
from __future__ import annotations

import math
from pathlib import Path
import re
import struct

from .presentation_models import SHOW_ACTOR_ARGUMENT, model_actor, held_model_offsets


def _vector(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 3
            or not all(type(number) in (int, float) and math.isfinite(number) for number in value)):
        raise ValueError("Native held-item position is not a finite literal vector.")
    try:
        return list(struct.unpack("<3f", struct.pack("<3f", *value)))
    except (OverflowError, struct.error) as error:
        raise ValueError("Native held-item position exceeds the native float range.") from error


def _offset(value):
    result = _vector(value)
    # ItemPos follows Player rotation, whereas PouchContent's offset is added
    # in world space. All supported native offsets are vertical. For the
    # upright native get pose, yaw rotation preserves this vector exactly.
    if result[0] != 0.0 or result[2] != 0.0:
        raise ValueError("Native held-item offset is not vertical.")
    return result


def display_offset(metadata, read):
    """Return the missing offset, or None for actors which retain a pouch.

    A progressive presenter is shared by its tiers. Refuse a newly divergent
    family instead of silently borrowing the first tier's display position.
    """
    actors = metadata.get("tiers", [metadata["actor"]])
    separate = [model_actor(actor).startswith("Item_AP_Show_") for actor in actors]
    if not any(separate):
        return None
    if not all(separate):
        raise ValueError("Progressive held-item models have different offset contracts.")
    offsets = held_model_offsets(read, actors)
    values = [_offset(offsets[actor]) for actor in actors]
    if any(value != values[0] for value in values[1:]):
        raise ValueError("Progressive held-item models have different native offsets.")
    return values[0]


def compensate_position(params, offset):
    """Offset one fresh native copy, preserving its authored base position."""
    base, offset = _vector(params.get("ItemPos")), _offset(offset)
    return _vector([first + second for first, second in zip(base, offset)])


def _bindings(chart):
    from evfl.event import SubFlowEvent
    from .catalog import ITEM_DATA, ITEM_IDS, TRADE_CHECKS
    from .native_presentations import PRESENTER_ENTRY, PRESENTER_NAME
    from .master_sword import LOCATION_ID as MASTER_LOCATION_ID

    by_id = {value: ITEM_DATA[name] for name, value in ITEM_IDS.items()}
    all_actors = {actor for row in ITEM_DATA.values() for actor in row.get("tiers", [row["actor"]])}
    trade_ids = {row["id"] for row in TRADE_CHECKS.values()}
    result = []
    for node in chart.events:
        data = node.data
        if not isinstance(data, SubFlowEvent) or data.res_flowchart_name != PRESENTER_NAME or data.params is None:
            continue
        params = data.params.data
        shown = params.get(SHOW_ACTOR_ARGUMENT)
        if type(shown) is not str or not shown.startswith("Item_AP_Show_"):
            continue
        actual = params.get("ActorName")
        if (type(actual) is not str or actual not in all_actors or model_actor(actual) != shown
                or params.get("IsNpcEventStarter") is not False):
            raise ValueError("Held-item framing has an invalid AP model identity.")
        receipt = re.fullmatch(r"OOTRR_APReceive_(\d+)(?:_Tier\d+|_Ammo)?_Show", node.name)
        trade = re.fullmatch(r"OOTRR_APTradeReward_(\d+)_Present(?:_Tier\d+|_Ammo)?_Show", node.name)
        master = re.fullmatch(r"OOTRR_APMaster_Reward_(\d+)_Present(?:_Tier\d+|_Ammo)?_Show", node.name)
        if receipt:
            item_id = int(receipt[1])
            metadata = by_id.get(item_id)
            if metadata is None or actual not in metadata.get("tiers", [metadata["actor"]]):
                raise ValueError("Held-item framing has a mismatched receipt identity.")
            prefix = "OOTRR_APShow_" + str(item_id)
        elif trade and int(trade[1]) in trade_ids:
            prefix = "OOTRR_APTradeShow_" + trade[1]
        elif master and int(master[1]) == MASTER_LOCATION_ID:
            prefix = "OOTRR_APMaster_Show_" + master[1]
        else:
            raise ValueError("Held-item framing has an unknown AP presenter caller.")
        if data.entry_point_name != prefix + "_" + PRESENTER_ENTRY:
            raise ValueError("Held-item framing has an unknown AP presenter entry.")
        result.append(dict(entry=data.entry_point_name, prefix=prefix, actor=actual, shown=shown))
    return result


def _closure(chart, root_name, prefix):
    from evfl.event import SubFlowEvent, SubFlowSwitchEvent
    from oot_rando.patching.event_info import reachable

    entries = {}
    for point in chart.entry_points:
        if point.name in entries:
            raise ValueError("Held-item framing has duplicate presenter entries.")
        entries[point.name] = point.main_event.v
    pending, visited, nodes = [root_name], set(), set()
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        if not name.startswith(prefix + "_") or name not in entries:
            raise ValueError("Held-item framing crosses an unknown local presenter.")
        for node in reachable(entries[name]):
            if not node.name.startswith(prefix + "_"):
                raise ValueError("Held-item framing crosses an unprepared native event.")
            nodes.add(node)
            data = node.data
            if isinstance(data, (SubFlowEvent, SubFlowSwitchEvent)) and not data.res_flowchart_name:
                pending.append(data.entry_point_name)
    return nodes


def patch_receipt_framing(pouch_raw, presenter_raw, offsets):
    """Patch only generated AP presenter positions; return raw bytes and report.

    The incoming pouch graph supplies each display actor's actual identity.
    It is never rewritten. Every closure and current position is checked before
    changing the presenter, including a shared progressive family's tiers.
    """
    from evfl.common import Argument
    from evfl.event import ActionEvent
    from oot_rando.patching.progressive import FlowEditor
    from .native_presentations import PRESENTER_NAME

    pouch = FlowEditor(pouch_raw, "AP held model identities")
    bindings = _bindings(pouch.chart)
    if not bindings:
        return presenter_raw, []
    editor = FlowEditor(presenter_raw, "Native AP held item framing")
    if pouch.chart.name != "GetPouchContent" or editor.chart.name != PRESENTER_NAME:
        raise ValueError("Held-item framing has an unexpected native flowchart.")
    groups = {}
    for binding in bindings:
        try:
            position = _offset(offsets[binding["actor"]])
        except KeyError as error:
            raise ValueError("Held-item framing has no native item offset.") from error
        group = groups.setdefault(binding["entry"], dict(prefix=binding["prefix"], position=position, actors=set()))
        if group["position"] != position:
            raise ValueError("Progressive held-item presenter has different native offsets.")
        group["actors"].add(binding["actor"])
    changes = []
    for entry, group in sorted(groups.items()):
        nodes = _closure(editor.chart, entry, group["prefix"])
        creates, positions = [], []
        for node in nodes:
            data = node.data
            if not isinstance(data, ActionEvent):
                continue
            command = data.actor_action.v.v
            params = data.params.data if data.params is not None else {}
            if command == "EventCreateShowItemFromActorFileName":
                if (str(data.actor.v.identifier) != "Player_Event"
                        or not isinstance(params.get("Actor"), Argument)
                        or str(params["Actor"]) != SHOW_ACTOR_ARGUMENT):
                    raise ValueError("Held-item framing has an unexpected model binding.")
                creates.append(node)
            elif command == "EventIgnitionShowItem":
                if (str(data.actor.v.identifier) != "Player_Event" or params.get("ASCommand") != "Rotate_GetDemo"
                        or params.get("IsScale") is not False or params.get("IsAsPlay") is not True):
                    raise ValueError("Held-item framing has an unexpected native item command.")
                positions.append(node)
        if len(creates) != 1 or len(positions) != 1:
            raise ValueError("Held-item framing has an ambiguous native display position.")
        node = positions[0]
        before = _vector(node.data.params.data.get("ItemPos"))
        target = group["position"]
        same = all(abs(a - b) <= 1e-7 for a, b in zip(before, target))
        if before != [0.0, 0.0, 0.0] and not same:
            raise ValueError("Held-item framing would replace an unknown authored position.")
        if not same:
            changes.append(dict(entry=entry, event=node.name, actors=sorted(group["actors"]), before=before, after=target))
    if not changes:
        return presenter_raw, []
    events = {node.name: node for node in editor.chart.events}
    for change in changes:
        node = events[change["event"]]
        node.data.params.data["ItemPos"] = change["after"]
        editor.expected[node.name] = dict(node.data.params.data)
    return editor.write("Native AP held item offsets")[0], changes


def prepare_held_framing(romfs, mod, *, refresh_models=False):
    """Apply display-only offsets to a staged or compatible cached receipt set."""
    from oot_rando.game.resource_allocations import grow_resources
    from oot_rando.patching.progressive import FlowEditor
    from .mod_codec import Codec
    from .native_presentations import PRESENTER_PATH
    from .receipt_events import FLOW_PATH, REST

    romfs, mod = Path(romfs), Path(mod)
    if not (mod / FLOW_PATH).is_file():
        return {"presenters": 0, "written": 0}
    codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
    def frame(path):
        target = mod / path
        return (target if target.is_file() else romfs / path).read_bytes()
    def read(path):
        return codec.decode(frame(path))
    pouch_raw = read(FLOW_PATH)
    bindings = _bindings(FlowEditor(pouch_raw, "AP held framing bindings").chart)
    if not bindings:
        return {"presenters": 0, "written": 0}
    if refresh_models:
        # Compatible modern caches can already name the correct display
        # actors while retaining their old Common-only body animations.
        # Legacy chest-only stages without presented receipts need no pass.
        from .presentation_models import prepare_presentation_models
        prepare_presentation_models(romfs, mod)
    offsets = held_model_offsets(read, {binding["actor"] for binding in bindings})
    original = frame(PRESENTER_PATH)
    before = codec.decode(original)
    raw, changes = patch_receipt_framing(pouch_raw, before, offsets)
    if not changes:
        return {"presenters": 0, "written": 0}
    rest_frame = frame(REST)
    rest, _ = grow_resources(codec.decode(rest_frame), {PRESENTER_PATH: max(0, len(raw) - len(before))})
    encoded = {PRESENTER_PATH: codec.encode(raw, original), REST: codec.encode(rest, rest_frame)}
    for path, content in encoded.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return {"presenters": len(changes), "written": len(encoded)}
