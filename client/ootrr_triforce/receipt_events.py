"""Room-bound, native item receipts with their acknowledgement in the same flow.

The game's pouch action retains its special handling for capacity upgrades,
bottles, heart pieces and bundles. The effective OOTRR bag hooks are copied too.
V2 uses the native pickup, short-get or major-get presentation for each item;
older rooms retain their silent receipts.
"""
from .i18n import tr
import copy
from pathlib import Path
import re

from .catalog import ITEM_DATA, ITEM_IDS
from .medallions import REST
from .mod_codec import Codec

FLOW_NAME = "GetPouchContent"
FLOW_PATH = "Event/EventFlow/GetPouchContent.bfevfl.zs"
PREFIX = "OOTRR_APReceive_"
SILENT_ENTRY = "OOTRR_APSilentGrant"
CURSOR_PREFIX = "Archipelago.ReceivedIndex."
DUNGEONS = {
    "Deku Tree": "InsideTheDekuTree", "Dodongos Cavern": "DodongoCavern",
    "Jabu Jabus Belly": "InsideJabuJabuBelly", "Forest Temple": "ForestTemple",
    "Fire Temple": "FireTemple", "Ice Cavern": "IceCavern", "Water Temple": "WaterTemple",
    "Bottom of the Well": "BottomOfTheWell", "Shadow Temple": "ShadowTemple",
    "Spirit Temple": "SpiritTemple", "Gerudo Training Ground": "GerudoTrainingGround",
    "Ganons Castle": "InsideGanonCastle", "Thieves Hideout": "GerudoFortress",
}
OWNERS = {
    "Item_Gauntlet_Goron": "Armor_Child_Gauntlet_Goron",
    "Item_Gauntlet_Silver": "Armor_Adult_Gauntlet_Silver",
    "Item_Gauntlet_Gold": "Armor_Adult_Gauntlet_Gold",
    "Item_Range_Bow": "Weapon_Range_Bow",
    "Item_Range_SlingShot": "Weapon_Range_SlingShot",
}
CURES = {"Obj_Heart", "Tbox_MagicJar_Large", "Obj_Fairy"}


def event_name(item_id):
    return PREFIX + str(item_id)


def _action(event):
    data = event.data
    holder = getattr(data, "actor_action", None)
    return holder.v.v if holder is not None else None


def _query(event):
    holder = getattr(event.data, "actor_query", None)
    return holder.v.v if holder is not None else None


def _silent_grant(editor, acknowledgement, *, entry_name=SILENT_ENTRY, prefix="OOTRR_APSilent"):
    """Copy the native grant path, retaining effects and removing only UI/save."""
    from evfl.entry_point import EntryPoint
    from evfl.event import Event, ActionEvent, SwitchEvent
    from evfl.util import make_index
    from oot_rando.patching.event_info import reachable

    source = next((entry for entry in editor.chart.entry_points
                   if entry.name == "GetPouchContent"), None)
    if source is None:
        raise ValueError(tr('Native get-item event not found.'))
    ui = {"OpenGetWindow", "OpenRupeeUIIfNeed", "CloseRupeeUIIfNeed"}

    def resolve(event):
        seen = set()
        while event is not None:
            if event in seen:
                raise ValueError(tr('Loop in native item preparation.'))
            seen.add(event)
            data = event.data
            if (getattr(data, "res_flowchart_name", None) == ""
                    and getattr(data, "entry_point_name", None) in ui):
                event = data.nxt.v
            elif _action(event) == "EventTriggerRequestAutoSave":
                event = data.nxt.v
            elif _query(event) == "EventQueryIsAutoSavePouchContent":
                # This is the native terminal auto-save choice. It is moved
                # after the AP cursor, so no save can commit just the item.
                if any(node is not event and _action(node) != "EventTriggerRequestAutoSave"
                       for node in reachable(event)):
                    raise ValueError(tr('Unknown native autosave sequence.'))
                return None
            else:
                return event
        return None

    root = resolve(source.main_event.v)
    originals, stack = [], [root]
    while stack:
        event = stack.pop()
        if event is None or event in originals:
            continue
        if not isinstance(event.data, (ActionEvent, SwitchEvent)):
            raise ValueError(tr('Unrecognized native get-item step: ') + event.name)
        originals.append(event)
        if isinstance(event.data, ActionEvent):
            stack.append(resolve(event.data.nxt.v))
        else:
            stack.extend(resolve(case.v) for case in event.data.cases.values())
    if not any(_action(event) == "EventTriggerAddOrRemovePouchContent" for event in originals):
        raise ValueError(tr('Native inventory action not found.'))
    clones = {}
    for original in originals:
        event = Event()
        event.name = prefix + "_" + original.name
        event.data = copy.copy(original.data)
        event.data.params = copy.deepcopy(original.data.params)
        # Actor, action and query references stay in this very same chart.
        clones[original] = event
        editor.expected[event.name] = (dict(event.data.params.data)
                                       if event.data.params is not None else None)
    for original, event in clones.items():
        if isinstance(original.data, ActionEvent):
            event.data.nxt = make_index(clones.get(resolve(original.data.nxt.v), acknowledgement))
        else:
            event.data.cases = {key: make_index(clones.get(resolve(case.v), acknowledgement))
                                for key, case in original.data.cases.items()}
    if any(_action(event) == "EventTriggerSetHavePlayedGetEvent" for event in editor.chart.events):
        # OpenGetWindow_End also marks the native get-event as played. Keep
        # that flag, while leaving its caption save until after the AP cursor.
        for original, event in clones.items():
            if _action(original) == "EventTriggerSetForGetWindow":
                mark_name = ("OOTRR_APHavePlayed_" if prefix == "OOTRR_APSilent" else prefix + "HavePlayed_")
                mark = editor.action(mark_name + original.name, "PouchSystemActor",
                                     "EventTriggerSetHavePlayedGetEvent", None)
                mark.data.nxt = event.data.nxt
                event.data.nxt = make_index(mark)
    editor.chart.events.extend(clones.values())
    entry = EntryPoint(entry_name)
    entry.main_event = make_index(clones.get(root))
    editor.chart.entry_points.append(entry)


def build_receipt_flow(raw, token, names=None):
    """Return (modified GetPouchContent bytes, {item id: registered entry name})."""
    from evfl.entry_point import EntryPoint
    from evfl.util import make_index
    from oot_rando.patching.progressive import FlowEditor, link
    if not re.fullmatch("[a-f0-9]{64}", token):
        raise ValueError(tr('Invalid room identifier for native receipts.'))
    names = sorted(ITEM_DATA if names is None else set(names))
    if not set(names) <= ITEM_DATA.keys():
        raise ValueError(tr('Archipelago item has no native recipe.'))
    editor = FlowEditor(raw, FLOW_PATH)
    if any(entry.name.startswith(PREFIX) or entry.name == SILENT_ENTRY
           for entry in editor.chart.entry_points):
        raise ValueError(tr('Archipelago receipts are already prepared.'))
    silent_acknowledgement = editor.action("OOTRR_APSilentAcknowledge", "GameDataActor",
                                          "EventTriggerAddOrSubGameDataInt",
                                          {"GameDataName": CURSOR_PREFIX + token, "Index": -1, "Value": 1})
    _silent_grant(editor, silent_acknowledgement)

    def action(name, command, params):
        return editor.action(name, "GameDataActor", command, params)

    def boolean(name, key, after):
        node = action(name, "EventTriggerSetGameDataBool",
                      {"GameDataName": key, "Index": -1, "Value": True})
        link(node, after)
        return node

    def integer(name, key, after):
        node = action(name, "EventTriggerAddOrSubGameDataInt",
                      {"GameDataName": key, "Index": -1, "Value": 1})
        link(node, after)
        return node

    def finish(stem, actor=None):
        # No animation, popup, wait or save occurs between the native grant
        # and this cursor update. Both use the game's GameData update queue.
        save = editor.action(stem + "_Save", "GameSystemActor", "EventTriggerRequestAutoSave", None)
        after = save
        if actor is not None:
            refresh = editor.subflow(stem + "_Refresh", "Dm_SY_Get", "CheckHeart", {"ActorName": actor})
            link(refresh, after)
            after = refresh
        return (integer(stem + "_Acknowledge", CURSOR_PREFIX + token, after)
                if actor is None else after)

    def grant(stem, actor):
        tail = finish(stem, actor)
        give = editor.subflow(stem + "_Give", "", SILENT_ENTRY,
                              {"ActorName": actor, "IsGetInEvent": True,
                               "IsShowNumDisplay": False, "IsTreasureBox": False})
        link(give, tail)
        return give

    entries = {}
    for name in names:
        metadata = ITEM_DATA[name]
        item_id = ITEM_IDS[name]
        stem = event_name(item_id)
        if metadata["kind"] == "TCGSmallKey":
            root = finish(stem)
            root = boolean(stem + "_Once", "UI_MiniGameGetSmallKeyOnce", root)
            root = integer(stem + "_Key", "MiniGame_SmallKeyNum", root)
        elif metadata["actor"] in CURES:
            # These pickups are NotPushToPouch. The native CheckHeart flow
            # applies their actual recovery through this action, after a UI
            # delay. Apply it once here, immediately before acknowledgement.
            root = editor.action(stem + "_Cure", "PouchSystemActor", "EventTriggerRecoverByCureItem",
                                 {"ActorName": metadata["actor"]})
            link(root, finish(stem))
        elif metadata["mode"] == "generic":
            root = finish(stem)
            kind, dungeon = metadata["kind"], metadata.get("dungeon")
            if dungeon:
                prefix = "DungeonInfo." + DUNGEONS[dungeon] + "."
                if kind in ("SmallKey", "HideoutSmallKey"):
                    root = boolean(stem + "_Once", prefix + "IsGetSmallKeyOnce", root)
                    root = integer(stem + "_Total", prefix + "SmallKeyTotalNum", root)
                    root = integer(stem + "_Key", prefix + "SmallKeyNum", root)
                else:
                    member = {"BossKey": "IsGetBossKey", "GanonBossKey": "IsGetBossKey",
                              "Map": "IsGetMap", "Compass": "IsGetCompass"}[kind]
                    root = boolean(stem + "_Dungeon", prefix + member, root)
            else:
                command = {"SmallKey": "EventGetDungeonSmallKey", "BossKey": "EventGetDungeonBossKey",
                           "Map": "EventGetDungeonMap", "Compass": "EventGetDungeonCompass"}[kind]
                node = editor.action(stem + "_NativeDungeon", "GameSystemActor", command, None)
                link(node, root)
                root = node
        elif metadata["mode"] == "tiers":
            tiers = metadata["tiers"]
            gives = [grant(stem + "_Tier" + str(index), actor) for index, actor in enumerate(tiers)]
            # Highest owned tier wins; after saturation the last tier is given
            # again, exactly like OOTRR's progressive chest wrappers.
            root = gives[0]
            for index in range(len(tiers)):
                owner = OWNERS.get(tiers[index], tiers[index])
                root = editor.switch(stem + "_Held" + str(index), "GameDataActor", "EventQueryCheckIsGet",
                                     {"ActorName": owner}, gives[min(index + 1, len(tiers) - 1)], root)
        else:
            # Bundle actors already encode their yield. Giving quantity copies
            # here would multiply a 20-Bombchu pickup into 400 Bombchus.
            from .native_presentations import append_tier_choice
            root = append_tier_choice(editor, metadata, stem, grant)
        entry = EntryPoint(stem)
        entry.main_event = make_index(root)
        editor.chart.entry_points.append(entry)
        entries[item_id] = stem
    result, _ = editor.write(tr('The native Archipelago receipt'))
    return result, entries


def build_presented_receipts(pouch_raw, presenter_raw, token, names=None, *, native_info=None, ground_raw=None):
    """V2: native pickup/short/major gets, one inventory effect and AP ack."""
    from evfl.common import Argument
    from evfl.entry_point import EntryPoint
    from evfl.util import make_index
    from oot_rando.patching.progressive import FlowEditor, link
    from .native_presentations import (PRESENTER_NAME, PRESENTER_PATH,
                                       append_recipe, append_tier_choice, copy_receipt_presenter, receipt_style)
    if not re.fullmatch("[a-f0-9]{64}", token):
        raise ValueError(tr('Invalid room identifier for native receipts.'))
    names = sorted(ITEM_DATA if names is None else set(names))
    if not set(names) <= ITEM_DATA.keys():
        raise ValueError(tr('Archipelago item has no native recipe.'))
    pouch = FlowEditor(pouch_raw, FLOW_PATH)
    presenter = FlowEditor(presenter_raw, PRESENTER_PATH)
    if any(entry.name.startswith(PREFIX) for entry in pouch.chart.entry_points):
        raise ValueError(tr('Archipelago receipts are already prepared.'))
    ack = pouch.action("OOTRR_APVisualAcknowledge", "GameDataActor", "EventTriggerAddOrSubGameDataInt",
                       {"GameDataName": CURSOR_PREFIX + token, "Index": -1, "Value": 1})
    _silent_grant(pouch, ack, entry_name="OOTRR_APVisualGrant", prefix="OOTRR_APVisualNative")
    entries = {}
    for name in names:
        metadata, item_id = ITEM_DATA[name], ITEM_IDS[name]
        stem = event_name(item_id)
        core_name = stem + "_Pouch"
        style = receipt_style(metadata, native_info)
        recipe = append_recipe(pouch, metadata, core_name, "OOTRR_APVisualGrant", ack,
                               pickup=style == "pickup")
        root = recipe
        if style != "pickup":
            window = pouch.subflow(core_name + "_Window", "", "DisplayGetByActorName",
                                   {"ActorName": Argument("ActorName")})
            link(window, root)
            root = window
        core = EntryPoint(core_name)
        core.main_event = make_index(root)
        pouch.chart.entry_points.append(core)
        shown_entry = (copy_receipt_presenter(presenter, metadata, item_id, core_name,
                                             style=style, ground_raw=ground_raw)
                       if style != "pickup" else None)

        def present(branch, actor):
            save = pouch.action(branch + "_Save", "GameSystemActor", "EventTriggerRequestAutoSave", None)
            tail = save
            if style == "pickup":
                # This is the game's own non-blocking pickup display, not its
                # get-item dialogue. Recovery hearts suppress stock numbers.
                if not native_info[actor].get("IsNotOpenStockNumDisplay", False):
                    popup = pouch.action(branch + "_Pickup", "UISystemActor",
                                          "EventTriggerRequestOpenPickUpWindow", {"ActorName": actor})
                    link(popup, tail)
                    tail = popup
                show = pouch.subflow(branch + "_Get", "", core_name, {"ActorName": actor})
            else:
                show = pouch.subflow(branch + "_Show", PRESENTER_NAME, shown_entry,
                                     {"ActorName": actor, "IsNpcEventStarter": False})
            link(show, tail)
            return show

        root = append_tier_choice(pouch, metadata, stem, present)
        entry = EntryPoint(stem)
        entry.main_event = make_index(root)
        pouch.chart.entry_points.append(entry)
        entries[item_id] = stem
    pouch_result, _ = pouch.write(tr('Archipelago receipts with native presentation'))
    presenter_result, _ = presenter.write("Les animations natives Archipelago")
    return pouch_result, presenter_result, entries


def prepare_receipts(romfs, mod, data):
    """Add native receipt events to one staged mod; never touch the game dump."""
    from oot_rando.formats import byml_codec
    from oot_rando.game.resource_allocations import grow_resources
    from oot_rando.patching import chest_flags, event_info
    romfs, mod = Path(romfs), Path(mod)

    def source(relative):
        candidate = mod / relative
        return (candidate if candidate.is_file() else romfs / relative).read_bytes()

    codec = Codec(source("Pack/ZsDic.pack.zs"))

    def read(relative):
        return codec.decode(source(relative))

    native_presentations = bool(data.get("local_items"))
    if native_presentations:
        from .native_presentations import PRESENTER_PATH, receipt_style
        native_info = {row["__RowId"]: row for row in byml_codec.load(
            read("RSDB/PouchActorInfo.Product.111.rstbl.byml.zs"))["root"]}
        changed_flow, changed_presenter, entries = build_presented_receipts(
            read(FLOW_PATH), read(PRESENTER_PATH), data["token"], native_info=native_info,
            ground_raw=read("Event/EventFlow/Dm_SY_Get.bfevfl.zs"))
        modified = {FLOW_PATH: changed_flow, PRESENTER_PATH: changed_presenter}
    else:
        changed_flow, entries = build_receipt_flow(read(FLOW_PATH), data["token"])
        modified = {FLOW_PATH: changed_flow}
    settings = byml_codec.load(read(chest_flags.EVENT_SETTINGS))
    template = next(row for row in settings["root"] if row["__RowId"] == "Dm_SY_Get")
    existing = {row["__RowId"] for row in settings["root"]}
    analyzed = byml_codec.load(read(chest_flags.ANALYZED))
    analyzed_existing = {row["__RowId"] for row in analyzed["root"]}
    analyzed_template = next((row for row in analyzed["root"] if row["__RowId"] == "Dm_SY_Get"), {})
    analyzed_rows = {row["__RowId"]: row for row in analyzed["root"]}
    from functools import lru_cache

    @lru_cache(None)
    def current(name):
        relative = event_info.flow_path(name)
        return modified[relative] if relative in modified else read(relative)

    walk_memo = {}
    item_names = {item_id: name for name, item_id in ITEM_IDS.items()}
    for item_id, name in entries.items():
        if name in existing or name in analyzed_existing:
            raise ValueError(tr('Receipt event already registered: ') + name)
        style = receipt_style(ITEM_DATA[item_names[item_id]], native_info) if native_presentations else None
        dependencies, children = {"Dm_SY_Get", FLOW_NAME}, set()
        if native_presentations:
            # Analyse the entry we actually generated, including its copied
            # local callees. A pickup never needs to load the major get scene.
            root = (FLOW_NAME, name)
            children = event_info.reachable_transitions(root, current, walk_memo)
            dependencies, pending, seen = set(), [root], set()
            while pending:
                call = pending.pop()
                if call in seen:
                    continue
                if call == event_info.SWITCH_CALL:
                    raise ValueError(tr('Unknown native receipt dynamic dependencies.'))
                seen.add(call)
                dependencies.add(call[0])
                pending.extend(walk_memo[call][0] - seen)
            pending = list(children)
            while pending:
                child = pending.pop()
                for descendant in analyzed_rows.get(child, {}).get("ChildEventList", ()):
                    if descendant not in children:
                        children.add(descendant)
                        pending.append(descendant)
        row = copy.deepcopy(template)
        row.update(__RowId=name, EntryPointName=name,
                   FlowchartFileName="Work/Event/EventFlow/" + FLOW_NAME + ".evfc")
        if native_presentations:
            # The ordinary native get style, without the windmill's unrelated
            # forced participants inherited by Dm_SY_Get's registration.
            component = ("FellingInGameFlowchartWithIgnoreDissentPlay" if style == "large"
                         else "FellingInGameFlowchartEvent")
            row["EventSettingComponentList"] = ("Work/Event/EventSetting/EventSettingComponentList/"
                                                + component + ".engine__event__EventSettingComponentList.gyml")
            if style != "large":
                row["EventSoundSetting"] = ("Work/Event/GameEventSoundSetting/IgnoreDuckingOnFlowchart."
                                            "game__event__GameEventSoundSetting.gyml")
        settings["root"].append(row)
        # Keep camera analysis only for the actual major presentation. Simple
        # pickups and short gets have no recorded camera or first-frame warp.
        row = copy.deepcopy(analyzed_template) if style == "large" else {}
        if native_presentations:
            for flag in ("IsPlayerEventStartWithClimb", "IsPlayerEventStartWithDrawn"):
                if flag in analyzed_template:
                    row[flag] = analyzed_template[flag]
        row.update(__RowId=name, SubFlowList=sorted(dependencies, key=str.lower))
        if native_presentations:
            row["IsPlayerWarpFirstFrame"] = False
        if children:
            row["ChildEventList"] = sorted(children, key=str.lower)
        analyzed["root"].append(row)
    for document, relative in ((settings, chest_flags.EVENT_SETTINGS), (analyzed, chest_flags.ANALYZED)):
        document["root"].sort(key=lambda row: row["__RowId"])
        modified[relative] = byml_codec.dump(document)
    growths = {relative: max(0, len(raw) - len(read(relative))) for relative, raw in modified.items()}
    table, _ = grow_resources(read(REST), growths)
    modified[REST] = table
    for relative, raw in modified.items():
        frame = codec.encode(raw, source(relative))
        target = mod / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(frame)
    return entries
