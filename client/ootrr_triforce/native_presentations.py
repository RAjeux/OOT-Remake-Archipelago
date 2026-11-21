"""Copy native event presentation graphs without sharing their reward callbacks."""
from .i18n import tr
import copy

PRESENTER_NAME = "Dm_SY_GetInEvent"
PRESENTER_PATH = "Event/EventFlow/Dm_SY_GetInEvent.bfevfl.zs"
PRESENTER_ENTRY = "GetInEvent_NotTurn_NotNpc"
LOCAL_CHEST_PREFIX = "OOTRR_APChestLocal_"
# Native BottleItem enum indices (the GameData enum has Empty at index 0).
# Concrete event calls confirm RedPotion=0, BlueFire=3, Fish=4, Bug=8,
# Fairy=9 and MaxMilk=10; the actor command uses enum index minus one.
BOTTLE_ITEMS = {"RedPotion": 0, "GreenPotion": 1, "BluePotion": 2, "BlueFire": 3,
                "Fish": 4, "Letter": 5, "BigPoe": 6, "Poe": 7, "Bug": 8,
                "Fairy": 9, "MaxMilk": 10, "HalfMilk": 11}


def is_cure(metadata):
    from .receipt_events import CURES
    return metadata["actor"] in CURES or metadata.get("pouch_category") == "CureItem"


def receipt_style(metadata, native_info):
    """Use the game's item metadata to choose ordinary, short or major get."""
    if native_info is None:
        return "large"
    actor = metadata["actor"]
    if actor not in native_info:
        raise ValueError(tr('Native presentation not found: ') + actor)
    info = native_info[actor]
    category, special = info.get("PouchCategory"), info.get("PouchSpecialDeal", "None")
    get_type = info.get("PouchGetType", "Small")
    # Every remote rupee uses the gameplay pickup counter, including the gold
    # rupee whose physical get actor normally has a short item presentation.
    if category == "Rupee":
        return "pickup"
    if (get_type == "Small" and ((category in {"Material", "Arrow"} and special == "None")
            or (category == "CureItem" and special == "NotPushToPouch"))):
        return "pickup"
    # OOTRR already uses the native short get for repeatable Bombchu packs.
    # Songs and ocarinas are Small too, but their KeyItem/special effects make
    # them important gets rather than ordinary ammunition or recovery pickups.
    if get_type == "Medium" or actor.startswith(("Item_BombchuBundle_", "Shop_BombchuBundle_")):
        return "medium"
    return "large"


def append_recipe(editor, metadata, stem, grant_entry, commit, *, pickup=False):
    """Add the actual native effect; each successful path ends at commit."""
    from evfl.common import Argument
    from oot_rando.patching.progressive import link
    from .receipt_events import DUNGEONS

    def integer(label, key, after):
        node = editor.action(stem + label, "GameDataActor", "EventTriggerAddOrSubGameDataInt",
                             {"GameDataName": key, "Index": -1, "Value": 1})
        link(node, after)
        return node

    def boolean(label, key, after):
        node = editor.action(stem + label, "GameDataActor", "EventTriggerSetGameDataBool",
                             {"GameDataName": key, "Index": -1, "Value": True})
        link(node, after)
        return node

    if metadata["kind"] == "TCGSmallKey":
        return integer("_Key", "MiniGame_SmallKeyNum",
                       boolean("_Once", "UI_MiniGameGetSmallKeyOnce", commit))
    if is_cure(metadata):
        node = editor.action(stem + "_Cure", "PouchSystemActor", "EventTriggerRecoverByCureItem",
                             {"ActorName": Argument("ActorName")})
        link(node, commit)
        return node
    if metadata["mode"] == "generic":
        kind, dungeon = metadata["kind"], metadata.get("dungeon")
        if dungeon:
            prefix = "DungeonInfo." + DUNGEONS[dungeon] + "."
            if kind in ("SmallKey", "HideoutSmallKey"):
                return integer("_Key", prefix + "SmallKeyNum",
                               integer("_Total", prefix + "SmallKeyTotalNum",
                                       boolean("_Once", prefix + "IsGetSmallKeyOnce", commit)))
            member = {"BossKey": "IsGetBossKey", "GanonBossKey": "IsGetBossKey",
                      "Map": "IsGetMap", "Compass": "IsGetCompass"}[kind]
            return boolean("_Dungeon", prefix + member, commit)
        command = {"SmallKey": "EventGetDungeonSmallKey", "BossKey": "EventGetDungeonBossKey",
                   "Map": "EventGetDungeonMap", "Compass": "EventGetDungeonCompass"}[kind]
        node = editor.action(stem + "_NativeDungeon", "GameSystemActor", command, None)
        link(node, commit)
        return node
    if metadata.get("bottle_item") and metadata.get("pouch_special") == "NotPushToPouch":
        node = editor.action(stem + "_BottleRefill", "PouchSystemActor", "EventTriggerPushToEmptyBottle",
                             {"Item": BOTTLE_ITEMS[metadata["bottle_item"]], "IsSetMessageTargetActorName": False,
                              "IsPushToSelectedBottle": False, "BigPoeFenceId": 0})
        link(node, commit)
        return node
    return editor.subflow(stem + "_Give", "", grant_entry,
                          {"ActorName": Argument("ActorName"), "IsGetInEvent": not pickup,
                           "IsShowNumDisplay": pickup, "IsTreasureBox": not pickup})


def copy_receipt_presenter(editor, metadata, item_id, core_name, *, style="large", ground_raw=None):
    """Keep the native item model/pose; use ground pickup camera policies.

    The NPC gift scene supplies a model without needing a physical pickup actor.
    Its four instantaneous locator-camera cuts are unsuitable for an unsolicited
    receipt. Major gets use the ground-get camera and its native hand-back;
    short gets keep the player's camera throughout.
    """
    from evfl.common import Argument
    from evfl.container import Container
    from evfl.event import SubFlowEvent
    from evfl.util import make_rindex
    from oot_rando.patching.progressive import FlowEditor
    from .receipt_events import FLOW_NAME, _action

    natural_camera = ground_raw is not None
    cleanup = None
    if natural_camera:
        ground = FlowEditor(ground_raw, "Native ground item presentation")
        if not any(entry.name == "Dm_SY_Get_Camera" for entry in ground.chart.entry_points):
            raise ValueError(tr('Native ground-pickup camera not found.'))
        cleanup = next((event for event in ground.chart.events
                        if _action(event) == "EventTriggerSendKeepStateMessageToPlayerCamera"), None)
        if cleanup is None:
            raise ValueError(tr('Native return to the gameplay camera not found.'))
    replaced = []

    def callback(event, original):
        data = original.data
        if (data.res_flowchart_name == FLOW_NAME
                and data.entry_point_name == "GetPouchContentByActorName_ForGetInEvent"):
            event.data.entry_point_name = core_name
            replaced.append(event.name)

    def skip(event):
        data, action = event.data, _action(event)
        if (is_cure(metadata) and getattr(data, "res_flowchart_name", None) == "Dm_SY_Get"
                and getattr(data, "entry_point_name", None) == "CheckHeart"):
            return True
        if not natural_camera:
            return False
        if not getattr(data, "res_flowchart_name", None) and getattr(data, "entry_point_name", None) in {
                "ChildDoF", "AdultDoF", "GetInEvent_SetLocator"}:
            return True
        if action == "EventTriggerCameraSavePoint":
            return True
        return style == "medium" and action in {
            "EventMoveToTargetPosCamera", "EventMoveCameraToSavePoint", "EventNorifyCutChangeForGraphics"}

    def transform(event, original):
        if not natural_camera or style == "medium":
            return
        if _action(original) == "EventMoveToTargetPosCamera":
            data = SubFlowEvent()
            data.nxt = event.data.nxt
            data.res_flowchart_name, data.entry_point_name = "Dm_SY_Get", "Dm_SY_Get_Camera"
            data.params = Container()
            data.params.data = {"ActorName": Argument("ActorName")}
            event.data = data
        elif _action(original) == "EventMoveCameraToSavePoint":
            owner = event.data.actor.v
            event.data.actor_action = make_rindex(editor._holder(owner.actions, cleanup.data.actor_action.v.v))
            event.data.params = copy.deepcopy(cleanup.data.params)

    entry = copy_entry(editor.chart, editor, PRESENTER_ENTRY, "OOTRR_APShow_" + str(item_id),
                       local_closure=natural_camera, callback=callback, skip=skip, transform=transform)
    if len(replaced) != 1:
        raise ValueError(tr('Unrecognized native animation grant: ') + metadata["actor"])
    return entry


def append_tier_choice(editor, metadata, stem, present):
    """Select a concrete native model using OOTRR's ownership rules."""
    from .receipt_events import OWNERS
    if metadata["mode"] != "tiers":
        return present(stem, metadata["actor"])
    tiers = metadata["tiers"]
    branches = [present(stem + "_Tier" + str(index), actor) for index, actor in enumerate(tiers)]
    root = branches[0]
    for index, actor in enumerate(tiers):
        root = editor.switch(stem + "_Held" + str(index), "GameDataActor", "EventQueryCheckIsGet",
                             {"ActorName": OWNERS.get(actor, actor)},
                             branches[min(index + 1, len(tiers) - 1)], root)
    return root


def append_local_chests(editor, pouch_raw, rewards, *, small_raw=None):
    """Give local AP rewards in the actual chest scene, without an AP cursor."""
    from evfl.common import Argument
    from evfl.entry_point import EntryPoint
    from evfl.util import make_index
    from oot_rando.patching.progressive import FlowEditor, link
    from .catalog import ITEM_DATA, ITEM_IDS
    from .receipt_events import FLOW_NAME, _action, _silent_grant

    opened = editor.action("OOTRR_APLocalOpened", "TreasureBox_EventStarter",
                           "EventTriggerTreasureBoxOpened", None)
    native = FlowEditor(pouch_raw, "Native local pouch grant")
    _silent_grant(native, None, entry_name="OOTRR_APTemporaryGrant", prefix="OOTRR_APTemporary")
    grant_entry = copy_entry(
        native.chart, editor, "OOTRR_APTemporaryGrant", "OOTRR_APLocalNative",
        skip=lambda event: _action(event) in {"EventTriggerSetForGetWindow", "EventTriggerSetHavePlayedGetEvent"},
        after=opened)
    source, source_entry = editor.chart, "Success_"
    generic = next(entry for entry in source.entry_points if entry.name == source_entry).main_event.v
    if (getattr(generic.data, "res_flowchart_name", None) == "Dm_SY_TreasureboxSmall"
            and generic.data.nxt.v is None):
        # OOTRR's fast big-chest path lives in the small-chest chart, with the
        # lid animation changed to FrontOpen. Inline that exact path here.
        if small_raw is None:
            raise ValueError(tr('Native large-chest animation not found.'))
        source = FlowEditor(small_raw, "Native fast big chest").chart
        source_entry = generic.data.entry_point_name
    result = {}
    for name in sorted(set(rewards)):
        metadata, item_id = ITEM_DATA[name], ITEM_IDS[name]
        stem = LOCAL_CHEST_PREFIX + str(item_id)
        core_name = stem + "_Pouch"
        recipe = append_recipe(editor, metadata, core_name, grant_entry, opened)
        window = editor.subflow(core_name + "_Window", FLOW_NAME, "DisplayGetByActorName",
                                {"ActorName": Argument("ActorName")})
        link(window, recipe)
        core = EntryPoint(core_name)
        core.main_event = make_index(window)
        editor.chart.entry_points.append(core)
        replaced = []

        def callback(event, original):
            data = original.data
            if data.res_flowchart_name == FLOW_NAME and data.entry_point_name in {
                    "DisplayGetByActorName", "GetPouchContentByActorNameForShowPickUpWindow",
                    "GetPouchContentByActorNameForTreasureBox"}:
                event.data.res_flowchart_name = ""
                event.data.entry_point_name = core_name
                replaced.append(event.name)

        def skip(event):
            data = event.data
            return (_action(event) in {"EventGetDungeonMap", "EventGetDungeonCompass",
                                        "EventGetDungeonBossKey", "EventGetDungeonSmallKey"}
                    or (is_cure(metadata) and getattr(data, "res_flowchart_name", None) == "Dm_SY_Get"
                        and getattr(data, "entry_point_name", None) == "CheckHeart"))

        cloned_entry = copy_entry(source, editor, source_entry, stem + "_Native",
                                  local_closure=True, callback=callback, skip=skip)
        if not replaced:
            raise ValueError(tr('Unrecognized native chest grant: ') + name)

        def present(branch, actor):
            return editor.subflow(branch + "_Open", "", cloned_entry,
                                  {"ContentName": actor, "IsMiniGame": False})

        root = append_tier_choice(editor, metadata, stem, present)
        entry = EntryPoint(stem)
        entry.main_event = make_index(root)
        editor.chart.entry_points.append(entry)
        result[name] = stem
    return result


def copy_entry(source, editor, entry_name, prefix, *, local_closure=False,
               callback=None, skip=None, after=None, transform=None):
    """Copy an entry and its graph, optionally its local callees, into a chart.

    Native actor bindings, typed arguments, queries, forks and return values are
    retained. A callback may replace a copied external subflow's target.
    """
    from evfl.entry_point import EntryPoint
    from evfl.event import ActionEvent, SwitchEvent, ForkEvent, JoinEvent, SubFlowEvent, SubFlowSwitchEvent, Event
    from evfl.util import make_index, make_rindex

    entries = {entry.name: entry for entry in source.entry_points}
    if entry_name not in entries:
        raise ValueError(tr('Native presentation not found: ') + entry_name)

    def resolve(event):
        visited = set()
        while event is not None and skip is not None and skip(event):
            if event in visited or not hasattr(event.data, "nxt"):
                raise ValueError(tr('Native step cannot be bypassed: ') + event.name)
            visited.add(event)
            event = event.data.nxt.v
        return event

    def successors(event):
        data = event.data
        if isinstance(data, (ActionEvent, JoinEvent, SubFlowEvent)):
            return [resolve(data.nxt.v)]
        if isinstance(data, (SwitchEvent, SubFlowSwitchEvent)):
            return [resolve(case.v) for case in data.cases.values()]
        if isinstance(data, ForkEvent):
            return [resolve(data.join.v), *(resolve(fork.v) for fork in data.forks)]
        return []

    wanted, nodes, pending_entries = {}, {}, [entry_name]
    while pending_entries:
        name = pending_entries.pop()
        if name in wanted:
            continue
        wanted[name] = entries[name]
        stack = [resolve(entries[name].main_event.v)]
        while stack:
            event = stack.pop()
            if event is None or event in nodes:
                continue
            nodes[event] = None
            stack.extend(successors(event))
            data = event.data
            if (local_closure and isinstance(data, (SubFlowEvent, SubFlowSwitchEvent))
                    and not data.res_flowchart_name):
                if data.entry_point_name not in entries:
                    raise ValueError(tr('Native subflow not found: ') + data.entry_point_name)
                pending_entries.append(data.entry_point_name)

    def actor_for(original):
        owner = next((actor for actor in editor.chart.actors
                      if actor.identifier == original.identifier), None)
        if owner is None:
            if original.argument_entry_point.v is not None:
                raise ValueError(tr('Native actor belongs to another entry: ') + str(original.identifier))
            owner = copy.deepcopy(original)
            owner.argument_entry_point = make_index(None)
            editor.chart.actors.append(owner)
        return owner

    occupied = {event.name for event in editor.chart.events}
    for original in nodes:
        event = Event()
        event.name = prefix + "_" + original.name
        if event.name in occupied:
            raise ValueError(tr('Native presentation already copied: ') + event.name)
        occupied.add(event.name)
        event.data = copy.copy(original.data)
        if hasattr(original.data, "params"):
            event.data.params = copy.deepcopy(original.data.params)
        if hasattr(original.data, "actor"):
            owner = actor_for(original.data.actor.v)
            event.data.actor = make_rindex(owner)
            if hasattr(original.data, "actor_action"):
                event.data.actor_action = make_rindex(editor._holder(owner.actions, original.data.actor_action.v.v))
            if hasattr(original.data, "actor_query"):
                event.data.actor_query = make_rindex(editor._holder(owner.queries, original.data.actor_query.v.v))
        nodes[original] = event

    def target(original):
        original = resolve(original)
        return nodes[original] if original is not None else after

    for original, event in nodes.items():
        data = event.data
        if isinstance(data, (ActionEvent, JoinEvent, SubFlowEvent)):
            data.nxt = make_index(target(original.data.nxt.v))
        elif isinstance(data, (SwitchEvent, SubFlowSwitchEvent)):
            data.cases = {key: make_index(target(case.v)) for key, case in original.data.cases.items()}
        elif isinstance(data, ForkEvent):
            data.join = make_rindex(target(original.data.join.v))
            # A removed terminal branch (for example an independent camera
            # action) has no target. EVFL fork indices must remain non-null.
            data.forks = [make_rindex(target(fork.v)) for fork in original.data.forks
                          if resolve(fork.v) is not None]
            if not data.forks:
                raise ValueError(tr('All native branches were removed: ') + original.name)
        if isinstance(data, (SubFlowEvent, SubFlowSwitchEvent)):
            if local_closure and not original.data.res_flowchart_name:
                data.entry_point_name = prefix + "_" + original.data.entry_point_name
            if callback is not None:
                callback(event, original)
        if transform is not None:
            transform(event, original)
            data = event.data
        editor.expected[event.name] = (dict(data.params.data) if getattr(data, "params", None) is not None else None)
    editor.chart.events.extend(nodes.values())
    for name, original in wanted.items():
        entry = EntryPoint(prefix + "_" + name)
        entry.variable_defs = copy.deepcopy(original.variable_defs)
        entry.main_event = make_index(target(original.main_event.v))
        editor.chart.entry_points.append(entry)
    return prefix + "_" + entry_name
