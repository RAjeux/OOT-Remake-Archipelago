"""Targeted OOTRR 0.8.1 story repairs, adapted from upstream 0.8.2.

Upstream: ootrando/ootrr, 0fa64f44b5e689f39bcf98a151fc32cb019d538e,
story_skip.rs, door_fix.rs and door_gate.rs (GPL-3.0-or-later).
Apply to the portable builder's output before AP receipt preparation. Rewards,
location IDs and native collection markers are retained verbatim.
"""
from pathlib import Path

from .i18n import tr
from .mod_codec import Codec

PREFIX = "OOTRR_APStoryFix_"
FLOW_ROOT = "Event/EventFlow/"
DOOR = "DoorOfTime"
ARRIVAL = "Dm_SY_BancChangeArrive"
WINDMILL = "Npc_Hylia_009_Adult"
MOAT_LOGIC = "Logic/HyruleField_Child_Prefab_91f9.logic.module.ainb"
MOAT_BANC = "Banc/HyruleField/HyruleField_Child_Static.bcett.byml.zs"
MOAT_ACTOR = 2802436684568022035
ESCAPED = "HavePlayedEvent.HyruleField_DoorOfTime_Escape"
PICKED = "HavePlayedEvent.HyruleField_DoorOfTime_GetOcarinaOfTime"
REST = "System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs"
SETTINGS = "RSDB/EventSetting.Product.111.rstbl.byml.zs"
ANALYZED = "RSDB/GameAnalyzedEventInfo.Product.111.rstbl.byml.zs"


def _invalid():
    return ValueError(tr("Unsupported prepared story event layout."))


def _action(event):
    from evfl.event import ActionEvent
    if event is None or not isinstance(event.data, ActionEvent):
        return None
    return str(event.data.actor.v.identifier), event.data.actor_action.v.v


def _events(editor, name):
    found = [event for event in editor.chart.events if event.name == name]
    if len(found) != 1:
        raise _invalid()
    return found[0]


def _played_event(editor, entry, flag):
    """Find the builder's mark by behavior, independent of reward node numbers."""
    from oot_rando.patching.event_info import reachable
    points = [point for point in editor.chart.entry_points if point.name == entry]
    if len(points) != 1 or points[0].main_event.v is None:
        raise _invalid()
    found = []
    for event in reachable(points[0].main_event.v):
        if _action(event) != ("GameDataActor", "EventTriggerSetGameDataBool"):
            continue
        params = event.data.params.data if event.data.params else {}
        if params.get("GameDataName") == flag and params.get("Value") is True and params.get("Index") == -1:
            found.append(event)
    if len(found) != 1:
        raise _invalid()
    return found[0]


def _finish(editor):
    """Keep existing preloads and register moved/new local subflow reachability."""
    from evfl.event import SubFlowEvent
    from oot_rando.patching.event_info import reachable
    for point in editor.chart.entry_points:
        for event in reachable(point.main_event.v):
            if isinstance(event.data, SubFlowEvent):
                index = editor.chart.events.index(event)
                if index not in point._sub_flow_event_indices:
                    point._sub_flow_event_indices.append(index)
    return editor.write("Prepared story event repair")[0]


def patch_escape_flow(raw):
    """Exit the escape state instead of retaining its save/warp restriction."""
    from oot_rando.patching.progressive import FlowEditor
    editor = FlowEditor(raw, DOOR)
    if editor.chart.name != DOOR:
        raise _invalid()
    names = ["Event12"]
    if any(event.name == "OOTRRDoorFix4" for event in editor.chart.events):
        names.append("OOTRRDoorFix4")
    changed = False
    for name in names:
        event = _events(editor, name)
        if _action(event) != ("ChallengeSystemActor", "EventExecuteProgressChallengeStep"):
            raise _invalid()
        params = event.data.params.data if event.data.params else {}
        if params.get("ChallengeName") != DOOR or params.get("StepName") not in {"Step04", "Step05"}:
            raise _invalid()
        if params["StepName"] == "Step04":
            params["StepName"] = "Step05"
            editor.expected[name]["StepName"] = "Step05"
            changed = True
    return _finish(editor) if changed else raw


def patch_moat_logic(raw):
    """Keep the moat check available after Step04 is no longer held.

    The four-node native module uses its quest-step query only for the Ocarina's
    creation. Reuse that query slot for the escape-played flag. No node is added,
    and the other three nodes remain intact apart from the new output index.
    The existing explicit 'escape not required' mode remains unconditional.
    """
    import ainb
    original = ainb.AINB.from_binary(raw)
    doc = original.as_dict()
    nodes = doc.get("Nodes", ())
    if (doc.get("Version") != 1032 or doc.get("Filename") != "HyruleField_Child_Prefab_91f9.logic.module"
            or doc.get("Category") != "Logic" or len(nodes) != 4):
        raise _invalid()
    actor = nodes[2]
    if (actor.get("Name") != "ActorLogicOcarinaTime" or actor.get("Properties", {}).get("String") != [
            {"Name": "InstanceName", "Default Value": "Obj_Ocarina_Time_A_01_7cb3", "Flags": []}]):
        raise _invalid()
    inputs = actor.get("Parameters", {}).get("Inputs", {}).get("Bool", ())
    creates = [value for value in inputs if value.get("Name") == "Logic_Create"]
    if len(creates) != 1:
        raise _invalid()
    create = creates[0]
    if create == {"Name": "Logic_Create", "Default Value": True, "Node Index": -1,
                  "Output Index": 0, "Flags": ["Uses Default", "Is Output"]}:
        return raw  # OOTRR's existing zeldas_escape: moat option.
    query = nodes[0]
    expected_inputs = {"String": [
        {"Name": "ChallengeName", "Default Value": "Work/Challenge/DoorOfTime.game__challenge__Challenge.gyml",
         "Node Index": -1, "Output Index": 0, "Flags": ["Uses Default"]},
        {"Name": "ChallengeStepName", "Default Value": "Step04", "Node Index": -1,
         "Output Index": 0, "Flags": ["Uses Default"]},
    ]}
    wanted_inputs = {
        "Int": [{"Name": "GameDataArrayIndex", "Default Value": -1, "Node Index": -1,
                 "Output Index": 0, "Flags": ["Uses Default"]}],
        "String": [{"Name": "GameDataNameBool", "Default Value": ESCAPED, "Node Index": -1,
                    "Output Index": 0, "Flags": ["Uses Default"]}],
    }
    wanted_outputs = {"Bool": [{"Name": "Bool", "Is Output": True}]}
    if (query.get("Name") == "HoldGameDataGetBoolSimple" and query.get("Parameters") == {
            "Inputs": wanted_inputs, "Outputs": wanted_outputs}
            and create == {"Name": "Logic_Create", "Default Value": True, "Node Index": 0,
                           "Output Index": 0, "Flags": []}):
        return raw
    if (query.get("Name") != "HoldChallengeCurrentStepCheckOrder"
            or query.get("Parameters", {}).get("Inputs") != expected_inputs
            or query.get("Flags") != ["Is Query"] or query.get("Queries") != []
            or query.get("Attachments") != [] or query.get("Plugs") != {}
            or create != {"Name": "Logic_Create", "Default Value": True, "Node Index": 0,
                          "Output Index": 2, "Flags": []}):
        raise _invalid()
    # Refuse to change a shared query if another consumer appears in a future dump.
    consumers = []
    for node in nodes:
        for values in node.get("Parameters", {}).get("Inputs", {}).values():
            consumers.extend((node["Node Index"], value["Name"]) for value in values
                             if value.get("Node Index") == 0)
    if consumers != [(2, "Logic_Create")]:
        raise _invalid()
    query["Name"] = "HoldGameDataGetBoolSimple"
    query["Parameters"] = {"Inputs": wanted_inputs, "Outputs": wanted_outputs}
    create["Output Index"] = 0
    updated = ainb.AINB.from_dict(doc)
    # from_dict omits an empty blackboard. Keeping the native object preserves
    # the v1032 seven-type blackboard header and every following section offset.
    updated.blackboard = original.blackboard
    result = updated.to_binary()
    if ainb.AINB.from_binary(result).as_dict() != doc:
        raise _invalid()
    return result


def patch_moat_banc(raw):
    from oot_rando.formats import byml_codec
    doc = byml_codec.load(raw)
    actors = [actor for actor in doc["root"].get("Actors", ()) if actor.get("Hash") == MOAT_ACTOR]
    if len(actors) != 1 or actors[0].get("Gyaml") != "Obj_Ocarina_Time_A_01":
        raise _invalid()
    presence = {"FlagName": PICKED, "IsCheckLazy": False, "IsNegation": True}
    if actors[0].get("Presence") == presence:
        return raw
    if "Presence" in actors[0]:
        raise _invalid()
    actors[0]["Presence"] = presence
    result = byml_codec.dump(doc)
    if byml_codec.load(result) != doc:
        raise _invalid()
    return result


def patch_windmill(raw):
    """Retain the native windmill/quest post-lesson continuation."""
    from oot_rando.patching.progressive import FlowEditor, link
    editor = FlowEditor(raw, WINDMILL)
    if editor.chart.name != WINDMILL:
        raise _invalid()
    from evfl.event import SubFlowEvent
    name = PREFIX + "StormAfter"
    if not any(point.name == "After_GetStormSong" for point in editor.chart.entry_points):
        raise _invalid()
    # The builder writes the lesson's story flags before its shuffled reward.
    current = _played_event(editor, "PlayStormSong_Adult", "HavePlayedEvent.Dm_MelodyGet_Storm")
    visited = {current}
    while True:
        nxt = current.data.nxt.v
        if nxt is None or nxt in visited:
            raise _invalid()
        visited.add(nxt)
        action = _action(nxt)
        if action is None or action[0] not in {"GameDataActor", "ChallengeSystemActor"}:
            break
        current = nxt
    markers = [event for event in editor.chart.events if event.name == name]
    if markers and (len(markers) != 1 or nxt is not markers[0]):
        raise _invalid()
    if isinstance(nxt.data, SubFlowEvent) and not nxt.data.res_flowchart_name and nxt.data.entry_point_name == "After_GetStormSong":
        if nxt.data.nxt.v is None:
            raise _invalid()
        # Newer portable builders already preserve this native continuation.
        # Retain their call verbatim instead of running the song cleanup twice.
        return raw
    if markers:
        raise _invalid()
    call = editor.subflow(name, "", "After_GetStormSong", None)
    link(current, call)
    link(call, nxt)
    return _finish(editor)


def patch_nocturne(raw):
    """Give the actual shuffled reward before the village changes scenes."""
    from oot_rando.patching.event_info import _successors
    from oot_rando.patching.progressive import FlowEditor, link
    from .shop_events import _retarget
    editor = FlowEditor(raw, ARRIVAL)
    if editor.chart.name != ARRIVAL:
        raise _invalid()
    played = _played_event(editor, "KakarikoVillage_MelodyGet_Shadow", "HavePlayedEvent.Dm_MelodyGet_Shadow")
    wait_name, fade_name = PREFIX + "NocturneLoading", PREFIX + "NocturneFade"
    if any(event.name == wait_name for event in editor.chart.events):
        wait, fade = _events(editor, wait_name), _events(editor, fade_name)
        if (_action(wait) != ("UISystemActor", "EventWaitCloseLoadingFade")
                or _action(fade) != ("UISystemActor", "EventEventFadeIn")
                or wait.data.params is None or wait.data.params.data != {"IsWaitEnd": True}
                or fade.data.params is None or fade.data.params.data != {
                    "Color": 0, "IsNoPlayAnime": False, "Length": 1, "IsWaitEnd": True}
                or wait.data.nxt.v is not fade or fade.data.nxt.v is not _events(editor, "Event280")
                or played.data.nxt.v is not wait):
            raise _invalid()
        return raw
    continuation = _events(editor, "Event280")
    change = _events(editor, "Event329")
    before = _events(editor, "Event496")
    if (played.data.params is None
            or played.data.params.data.get("GameDataName") != "HavePlayedEvent.Dm_MelodyGet_Shadow"
            or _action(change) != ("GameSystemActor", "EventReserveBancChange")
            or change.data.params.data.get("BootEventName") != "KakarikoVillage_MelodyGet_Shadow"
            or _action(before) != ("Player_Event", "EventPlayerUnequip")):
        raise _invalid()
    # Current portable builds can already contain the upstream repair under
    # generated names. Accept only its complete boot and pre-change layout.
    wait = played.data.nxt.v
    if _action(wait) == ("UISystemActor", "EventWaitCloseLoadingFade"):
        fade = wait.data.nxt.v
        if (wait.data.params is None or wait.data.params.data != {"IsWaitEnd": True}
                or _action(fade) != ("UISystemActor", "EventEventFadeIn")
                or fade.data.params is None or fade.data.params.data != {
                    "Color": 0, "IsNoPlayAnime": False, "Length": 1, "IsWaitEnd": True}
                or fade.data.nxt.v is not continuation or before.data.nxt.v is change):
            raise _invalid()
        # Every branch of the existing reward must terminate at the original
        # scene change, with no route back into the boot or the unequip node.
        complete, visiting = set(), set()
        def reaches_change(event):
            if event is change:
                return True
            if event is None or event in {played, wait, fade, continuation, before} or event in visiting:
                return False
            if event in complete:
                return True
            following = _successors(event)
            visiting.add(event)
            valid = bool(following) and all(reaches_change(child) for child in following)
            visiting.remove(event)
            if valid:
                complete.add(event)
            return valid
        if not reaches_change(before.data.nxt.v):
            raise _invalid()
        return raw
    if before.data.nxt.v is not change:
        raise _invalid()
    reward = played.data.nxt.v
    if reward is None or reward is continuation:
        raise _invalid()
    moved, todo = set(), [reward]
    while todo:
        event = todo.pop()
        if event is continuation or event in moved:
            continue
        if event is played or event is change or event is before:
            raise _invalid()
        moved.add(event)
        todo.extend(_successors(event))
    if not any(continuation in _successors(event) for event in moved):
        raise _invalid()
    # Move the already prepared reward graph, preserving upgrades, keys, bottles,
    # counts and all item-specific calls. Only its continuation changes.
    for event in moved:
        _retarget(event, continuation, change)
    link(before, reward)
    wait = editor.action(wait_name, "UISystemActor", "EventWaitCloseLoadingFade", {"IsWaitEnd": True})
    fade = editor.action(fade_name, "UISystemActor", "EventEventFadeIn",
                         {"Color": 0, "IsNoPlayAnime": False, "Length": 1, "IsWaitEnd": True})
    link(played, wait)
    link(wait, fade)
    link(fade, continuation)
    return _finish(editor)


def prepare_story_fixes(romfs, mod):
    """Repair the portable 0.8.1 base before AP-specific event cloning."""
    from oot_rando.formats import byml_codec
    from oot_rando.game.resource_allocations import grow_resources
    from oot_rando.patching import event_info
    romfs, mod = Path(romfs), Path(mod)
    if mod.name != "romfs" or mod.parent.name != "Archipelago":
        raise _invalid()
    codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
    cached = {}
    def frame(path):
        if path not in cached:
            target = mod / path
            cached[path] = (target if target.is_file() else romfs / path).read_bytes()
        return cached[path]
    def raw(path):
        return codec.decode(frame(path)) if path.endswith(".zs") else frame(path)
    changed = {}
    for name, transform in ((DOOR, patch_escape_flow), (WINDMILL, patch_windmill), (ARRIVAL, patch_nocturne)):
        path = FLOW_ROOT + name + ".bfevfl.zs"
        changed[path] = transform(raw(path))
    changed[MOAT_LOGIC] = patch_moat_logic(raw(MOAT_LOGIC))
    changed[MOAT_BANC] = patch_moat_banc(raw(MOAT_BANC))
    flows = {event_info.flow_name(path): value for path, value in changed.items() if event_info.flow_name(path)}
    original = lambda name: raw(event_info.flow_path(name))
    current = lambda name: flows[name] if name in flows else original(name)
    settings = byml_codec.load(raw(SETTINGS))["root"]
    info, preloads = event_info.add_subflow_dependencies(raw(ANALYZED), settings,
        event_info.new_subflows(flows, original), current)
    info, children = event_info.add_child_events(info, settings, event_info.new_transitions(flows, original), current)
    changed[ANALYZED] = info
    growth = {path: max(0, len(value) - len(raw(path))) for path, value in changed.items()}
    table, allocations = grow_resources(raw(REST), growth)
    changed[REST] = table
    encoded = {path: codec.encode(value, frame(path)) if path.endswith(".zs") else value
               for path, value in changed.items() if value != raw(path)}
    for path, value in encoded.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value)
    return dict(version=1, fixes=["escape_quest_and_moat", "windmill_post_song", "nocturne_before_loading"],
                files=len(encoded), preloads=len(preloads), child_events=len(children), allocations=allocations)
