"""Keep native-local gifts available after later story steps.

Targeted adaptation of OOTRR 0.8.2 open_world/quest_order.rs,
commit 0fa64f44b5e689f39bcf98a151fc32cb019d538e (GPL-3.0-or-later).
No gift is replaced here: every hook calls the builder's existing gift block.
"""
import copy
from pathlib import Path

from .mod_codec import Codec
from .story_fixes import _action, _finish, _invalid, REST, SETTINGS, ANALYZED

PREFIX = "OOTRR_APQuestFix_"
CHILD = "Sequence_IsChildhood"
RESCUED = "HavePlayedEvent.Meet_FourCarpenter_ClearEvent"
STORY_AFTER_STEP01 = "Archipelago.Story.SageOfSpiritAfterStep01"
GAME_DATA = "GameData/GameDataList.Product.110.byml.zs"
LATE = (
    ("Npc_Zora_KingZora_adult", ("Talk",), "SageOfWater_IsCompleted_Exp",
     "SageOfWater_KingZora_adult_Talk_Event198", "SageOfWater", "Safety_Entry", "Zora"),
    ("Npc_Goron_DaruniaJr_Adult", ("Talk", "Npc_Goron_DaruniaJr_Step3_on", "SageOfFire_IsCompleted_Exp_Talk"), None,
     "SageOfFire_Step02_DoorOpen", "SageOfFire", "Step02_Npc_Goron_DaruniaJr_Adult_Talk", "Goron"),
    ("SageOfSpirit", ("Step02_Npc_Gerudo_001_Talk",), None,
     "HavePlayedEvent.Dm_Gerudo_0025", None, "Dm_Gerudo_0025", "Card"),
)
ORDER = (
    ("SageOfFire", "SageOfFire", "StopDaruniaJr"),
    ("SageOfFire", "SageOfFire", "TalkDaruniaJr"),
    ("SageOfFire", "SageOfFire", "MoveStatue"),
    ("Npc_Hylia_012_Adult", "SageOfSpirit", "Step01"),
    ("Npc_Gerudo_006", "SageOfSpirit", "Step02"),
    ("SageOfSpirit", "SageOfSpirit", "Step02"),
    ("Dm_SY_BancChangeArrive", "SageOfSpirit", "Step04"),
)
GENERATE_FLOW = "Dm_SY_BancChangeGo"
GENERATE_ENTRY = "DeathMountainCrater_ToGoronCity"
GENERATE_FLAG = "SageOfFire_GenerateDaruniaJr"


def _lookup(editor, name):
    points = [point for point in editor.chart.entry_points if point.name == name]
    if len(points) != 1 or points[0].main_event.v is None:
        raise _invalid()
    return points[0]


def _ask(editor, name, flag, yes, no, *, exp=False):
    params = {"GameDataName": flag}
    if not exp:
        params["Index"] = -1
    return editor.switch(name, "GameDataActor", "EventQueryIsGameDataBoolExp" if exp else "EventQueryIsGameDataBool",
                         params, yes, no)


def _late(editor, record):
    from evfl.util import make_index
    _, names, when, done, flow, entry, tag = record
    points = [_lookup(editor, name) for name in names]
    old_roots = list(dict.fromkeys(point.main_event.v for point in points))
    for index, old in enumerate(old_roots):
        stem = PREFIX + tag + str(index)
        if flow is not None:
            give = editor.subflow(stem + "Give", flow, entry, None)
        else:
            give = editor.action(stem + "Give", "EventSystemActor", "EventTransition",
                                 {"IsWaitEnd": True, "SpecialEventActionType": 1,
                                  "EventName": entry, "FadeInTypeEventEnd": 0})
        owed = _ask(editor, stem + "Done", done, old, give)
        then = _ask(editor, stem + "When", when, owed, old, exp=True) if when else owed
        adult = _ask(editor, stem + "Adult", CHILD, old, then)
        for point in points:
            if point.main_event.v is old:
                point.main_event = make_index(adult)


def _step_targets(editor, quest, step):
    found = []
    for event in editor.chart.events:
        if _action(event) != ("ChallengeSystemActor", "EventExecuteProgressChallengeStep"):
            continue
        params = event.data.params.data if event.data.params else {}
        if params.get("ChallengeName") == quest and params.get("StepName") == step:
            found.append(event)
    if not found:
        raise _invalid()
    return found


def _mark_clear(editor):
    from oot_rando.patching.progressive import link
    targets = _step_targets(editor, "SageOfSpirit", "Step02")
    if len(targets) != 1:
        raise _invalid()
    target = targets[0]
    mark = editor.action(PREFIX + "Rescued", "GameDataActor", "EventTriggerSetGameDataBool",
                         {"GameDataName": RESCUED, "Index": -1, "Value": True})
    link(mark, target.data.nxt.v)
    link(target, mark)


def _order(editor, quest, step):
    from evfl.util import make_index
    from .shop_events import _retarget
    targets = _step_targets(editor, quest, step)
    for index, target in enumerate(targets):
        previous = list(editor.chart.events)
        comparison = STORY_AFTER_STEP01 if (quest, step) == ("SageOfSpirit", "Step01") else quest + "_IsAfter_" + step + "_Exp"
        guard = _ask(editor, PREFIX + "Order_" + step + "_" + str(index), comparison,
                     target.data.nxt.v, target, exp=True)
        for event in previous:
            _retarget(event, target, guard)
        for point in editor.chart.entry_points:
            if point.main_event.v is target:
                point.main_event = make_index(guard)


def _generate(editor):
    from evfl.util import make_index
    from oot_rando.patching.progressive import link
    point = _lookup(editor, GENERATE_ENTRY)
    old = point.main_event.v
    set_flag = editor.action(PREFIX + "GoronGenerate", "GameDataActor", "EventTriggerSetGameDataBool",
                             {"GameDataName": GENERATE_FLAG, "Index": -1, "Value": True})
    link(set_flag, old)
    point.main_event = make_index(_ask(editor, PREFIX + "GoronGenerateAdult", CHILD, old, set_flag))


def patch_quest_flow(raw, name):
    from oot_rando.patching.progressive import FlowEditor
    editor = FlowEditor(raw, name)
    if editor.chart.name != name:
        raise _invalid()
    existing = [event for event in editor.chart.events if event.name.startswith(PREFIX)]
    if existing:
        # Every entry hook and guard remains named and saved in the prepared
        # flow. Reject partial upgrades rather than duplicating native gifts.
        expected = []
        for record in LATE:
            if record[0] == name:
                expected.extend((point, PREFIX + record[-1]) for point in record[1])
        from oot_rando.patching.event_info import reachable
        for point, prefix in expected:
            if not any(event.name.startswith(prefix) for event in reachable(_lookup(editor, point).main_event.v)):
                raise _invalid()
        for flow, quest, step in ORDER:
            if flow == name:
                guards = [event for event in existing if event.name.startswith(PREFIX + "Order_" + step + "_")]
                comparison = STORY_AFTER_STEP01 if (quest, step) == ("SageOfSpirit", "Step01") else quest + "_IsAfter_" + step + "_Exp"
                if not guards or any(event.data.params is None or event.data.params.data != {"GameDataName": comparison}
                                     for event in guards):
                    raise _invalid()
        if name == GENERATE_FLOW and _lookup(editor, GENERATE_ENTRY).main_event.v.name != PREFIX + "GoronGenerateAdult":
            raise _invalid()
        return raw
    for record in LATE:
        if record[0] == name:
            _late(editor, record)
    if name == "SageOfSpirit":
        _mark_clear(editor)
    for flow, quest, step in ORDER:
        if flow == name:
            _order(editor, quest, step)
    if name == GENERATE_FLOW:
        _generate(editor)
    return _finish(editor)


def preserve_story_comparison(raw, native_raw):
    """Keep the real quest comparison separate from the fortress's card rule.

    Fortress clearance reuses the original Step01 expression for the card. The
    carpenter boss's monotonic story guard must still test the actual enum step.
    A computed unsaved alias needs no change to any saved-data size or offset.
    """
    from oot_rando.formats import byml_codec
    from oot_rando.patching.soul_adapter import murmur3
    doc, native = byml_codec.load(raw), byml_codec.load(native_raw)
    rows = doc["root"]["Data"]["BoolExp"]
    target = murmur3(STORY_AFTER_STEP01)
    source = murmur3("SageOfSpirit_IsAfter_Step01_Exp")
    definitions = [row for row in native["root"]["Data"]["BoolExp"] if int(row["Hash"]) == source]
    if len(definitions) != 1 or definitions[0].get("SaveFileIndex") != -1:
        raise _invalid()
    definition = copy.deepcopy(definitions[0])
    definition["Hash"] = type(definition["Hash"])(target)
    existing = [row for row in rows if int(row["Hash"]) == target]
    if existing:
        if existing != [definition]:
            raise _invalid()
        return raw
    hashes = [int(row["Hash"]) for row in rows]
    if hashes == sorted(hashes):
        index = next((index for index, key in enumerate(hashes) if key > target), len(rows))
        rows.insert(index, definition)
    else:
        rows.append(definition)
    result = byml_codec.dump(doc)
    if byml_codec.load(result) != doc:
        raise _invalid()
    return result


def prepare_quest_fixes(romfs, mod):
    from oot_rando.formats import byml_codec
    from oot_rando.game.resource_allocations import grow_resources
    from oot_rando.patching import event_info
    romfs, mod = Path(romfs), Path(mod)
    if mod.name != "romfs" or mod.parent.name != "Archipelago":
        raise _invalid()
    codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
    cache = {}
    def frame(path):
        if path not in cache:
            candidate = mod / path
            cache[path] = (candidate if candidate.is_file() else romfs / path).read_bytes()
        return cache[path]
    def raw(path):
        return codec.decode(frame(path))
    names = {row[0] for row in LATE} | {row[0] for row in ORDER} | {GENERATE_FLOW}
    modified = {event_info.flow_path(name): patch_quest_flow(raw(event_info.flow_path(name)), name) for name in sorted(names)}
    modified[GAME_DATA] = preserve_story_comparison(raw(GAME_DATA), codec.decode((romfs / GAME_DATA).read_bytes()))
    flows = {event_info.flow_name(path): content for path, content in modified.items() if event_info.flow_name(path)}
    original = lambda name: raw(event_info.flow_path(name))
    current = lambda name: flows[name] if name in flows else original(name)
    settings = byml_codec.load(raw(SETTINGS))["root"]
    info, preloads = event_info.add_subflow_dependencies(raw(ANALYZED), settings,
        event_info.new_subflows(flows, original), current)
    info, children = event_info.add_child_events(info, settings, event_info.new_transitions(flows, original), current)
    modified[ANALYZED] = info
    growth = {path: max(0, len(content) - len(raw(path))) for path, content in modified.items()}
    table, allocations = grow_resources(raw(REST), growth)
    modified[REST] = table
    encoded = {path: codec.encode(content, frame(path)) for path, content in modified.items() if content != raw(path)}
    for path, content in encoded.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return dict(version=1, flows=len(flows), late_gifts=len(LATE), guards=len(ORDER),
                preloads=len(preloads), child_events=len(children), files=len(encoded), allocations=allocations)
