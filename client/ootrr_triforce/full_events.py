"""Make full-network event rewards one-time while retaining quest continuations."""
from pathlib import Path


def guard_gifts(raw, markers):
    from evfl.event import ActionEvent, SubFlowEvent
    from evfl.util import make_index
    from ootrr_full.patching.event_info import reachable
    from ootrr_full.patching.progressive import AFTER_PREFIX, ACTION_GUIDE, CONVERTER_ENTRY, FlowEditor
    from ootrr_full.patching.song_adapter import GET_FLOW, DISPLAY_ENTRY, display_event_name
    editor = FlowEditor(raw, "Full-network one-time gifts")
    originals = {event.name: event for event in editor.chart.events}
    active = {id(event) for point in editor.chart.entry_points for event in reachable(point.main_event.v)}
    seen = set()
    for record in markers:
        original = originals.get(record.get("event"))
        if original is None or id(original) not in active:
            raise ValueError("A full-network gift collection event is unreachable.")
        if original.name in seen or "OOTRR_APOnce_" + original.name in originals:
            raise ValueError("A full-network gift has duplicate one-time guards.")
        seen.add(original.name)
        if not hasattr(original.data, "nxt") or original.data.nxt.v is None:
            raise ValueError("A full-network gift has no verified continuation.")
        marker = originals.get(record.get("marker"))
        current, followed = original.data.nxt.v, set()
        while current is not marker and current is not None:
            if current.name in followed or not isinstance(current.data, SubFlowEvent):
                break
            followed.add(current.name)
            call = current.data
            converter = (current.name == AFTER_PREFIX + original.name
                         and (call.res_flowchart_name, call.entry_point_name) == (ACTION_GUIDE, CONVERTER_ENTRY)
                         and call.params is None)
            display = (current.name == display_event_name(original.name)
                       and (call.res_flowchart_name, call.entry_point_name) == (GET_FLOW, DISPLAY_ENTRY)
                       and call.params is not None and isinstance(call.params.data.get("ActorName"), str))
            if not converter and not display:
                break
            current = call.nxt.v
        if (marker is None or current is not marker
                or not isinstance(marker.data, ActionEvent)
                or str(marker.data.actor.v.identifier) != "GameDataActor"
                or marker.data.actor_action.v.v != "EventTriggerSetGameDataBool"
                or marker.data.params is None
                or marker.data.params.data != {"GameDataName": record.get("flag"), "Index": -1, "Value": True}):
            raise ValueError("A full-network gift collection flag does not match its hand-over.")
        guard = editor.switch("OOTRR_APOnce_" + original.name, "GameDataActor", "EventQueryIsGameDataBool",
                              {"GameDataName": record["flag"], "Index": -1}, marker.data.nxt.v, original)
        for event in list(editor.chart.events):
            if event is guard:
                continue
            data = event.data
            if hasattr(data, "nxt") and data.nxt.v is original:
                data.nxt = make_index(guard)
            if hasattr(data, "cases"):
                data.cases = {key: make_index(guard) if value.v is original else value for key, value in data.cases.items()}
            if hasattr(data, "forks"):
                data.forks = [make_index(guard) if value.v is original else value for value in data.forks]
            if hasattr(data, "join") and data.join.v is original:
                data.join = make_index(guard)
        for point in editor.chart.entry_points:
            if point.main_event.v is original:
                point.main_event = make_index(guard)
    return editor.write("Full-network one-time gifts")[0]


def prepare_gift_guards(romfs, artifact, records):
    from .mod_codec import Codec
    from .medallions import REST
    from ootrr_full.game.resource_allocations import grow_resources
    import json
    romfs, artifact = Path(romfs), Path(artifact)
    mod = artifact / "romfs"
    tracking = json.loads((artifact / "tracking.json").read_text(encoding="utf-8"))
    flags = {flag for record in records for flag in record["flags"]}
    codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
    def frame(path):
        local = mod / path
        return (local if local.is_file() else romfs / path).read_bytes()
    changed, growth = {}, {}
    for path, markers in tracking.get("event_markers", {}).items():
        wanted = [record for record in markers if record.get("flag") in flags]
        if not wanted:
            continue
        before = codec.decode(frame(path))
        changed[path] = guard_gifts(before, wanted)
        growth[path] = max(0, len(changed[path]) - len(before))
    if not changed:
        return 0
    changed[REST], _ = grow_resources(codec.decode(frame(REST)), growth)
    for path, raw in changed.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(codec.encode(raw, frame(path)))
    return len(changed)
