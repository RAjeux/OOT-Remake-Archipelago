"""Gold Skulltula rewards committed by the native pickup event, never the kill.

OOTRR's token pickup kit retains the enemy/drop persistence protocol. Every AP
drop has a unique pouch identity, used only to select its room-bound callback.
Local rewards use native item UI and effects; foreign rewards retain AP medals.
"""
import json
from pathlib import Path
import re

from .catalog import AP_SKULL_CHECKS, ITEM_DATA, ITEM_IDS, SKULL_CHECKS
from .i18n import tr
from .mod_codec import Codec

FLOW_PATH = "Event/EventFlow/GetPouchContent.bfevfl.zs"
REST = "System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs"
PREFIX = "OOTRR_APSkull_"
SCRATCH = "Archipelago.SelectedPickup"
NATIVE_SCRATCH = "Archipelago.SelectedNativePickup"
PICKUP_FLOWS = {
    "Dm_SY_Get": (("Event35", "Event38"),),
    "Dm_SY_Get_WithoutPlayer": (("Event0", "Event2"),),
}


def _after_writes(editor, name, target):
    """Let native trigger actions commit before querying their GameData values."""
    from evfl.actor import Actor
    from evfl.common import ActorIdentifier
    from evfl.container import Container
    from oot_rando.patching.event_patch import GAMEDATA_ACTOR_PARAMS
    from oot_rando.patching.progressive import link
    if not any(str(actor.identifier) == "EventSystemActor" for actor in editor.chart.actors):
        # Exact native EventSystemActor parameters, also used by GameDataActor.
        actor = Actor()
        actor.identifier = ActorIdentifier("EventSystemActor")
        actor.concurrent_clips = 1
        actor.params = Container()
        actor.params.data = dict(GAMEDATA_ACTOR_PARAMS)
        editor.chart.actors.append(actor)
    wait = editor.action(name, "EventSystemActor", "EventWait", {"Frames": 1, "IsWaitEnd": True})
    link(wait, target)
    return wait


def skull_records(roster):
    from oot_rando.patching import ap_item
    records = []
    for name in sorted(set(roster).intersection(AP_SKULL_CHECKS)):
        reward, metadata = roster[name], SKULL_CHECKS[name]
        item, player = ((reward["item"], reward["player"]) if isinstance(reward, dict) else reward[:2])
        label = ap_item.ap_item(json.dumps([name, item, player], ensure_ascii=False))
        actor = ap_item.ap_actor(label)
        record = dict(name=name, actor=actor, pickup="Obj_" + actor[5:] + "_GH",
                      hash=metadata["actor"], files=list(metadata["files"]), flag_name=metadata["flag_name"])
        if isinstance(reward, dict) and reward.get("local"):
            if item not in ITEM_DATA or reward.get("item_id", ITEM_IDS[item]) != ITEM_IDS[item]:
                raise ValueError(tr('Unknown local Archipelago item: ') + str(item))
            native = ITEM_DATA[item]
            # The token kit completes when its get event returns. A refill that
            # fails for lack of a bottle could otherwise permanently lose a check.
            if native.get("bottle_item") and native.get("pouch_special") == "NotPushToPouch":
                raise ValueError(tr("Invalid Archipelago Skulltula metadata."))
            record.update(local_item=item, native_actor=native["actor"])
        records.append(record)
    return _records(records)


def _records(records):
    out, identities, hashes = [], set(), set()
    for record in records:
        metadata = SKULL_CHECKS.get(record.get("name")) if record.get("name") in AP_SKULL_CHECKS else None
        actor, pickup = record.get("actor"), record.get("pickup")
        if (metadata is None or record.get("hash") != metadata["actor"]
                or record.get("files") != list(metadata["files"])
                or record.get("flag_name") != metadata["flag_name"]
                or not isinstance(actor, str) or not re.fullmatch(r"Item_AP_[A-Za-z0-9_]+", actor)
                or pickup != "Obj_" + actor[5:] + "_GH"
                or actor in identities or record["hash"] in hashes):
            raise ValueError(tr("Invalid Archipelago Skulltula metadata."))
        if "local_item" in record:
            item = record["local_item"]
            if item not in ITEM_DATA or record.get("native_actor") != ITEM_DATA[item]["actor"]:
                raise ValueError(tr("Invalid Archipelago Skulltula metadata."))
            native = ITEM_DATA[item]
            if native.get("bottle_item") and native.get("pouch_special") == "NotPushToPouch":
                raise ValueError(tr("Invalid Archipelago Skulltula metadata."))
        elif "native_actor" in record:
            raise ValueError(tr("Invalid Archipelago Skulltula metadata."))
        identities.add(actor)
        hashes.add(record["hash"])
        out.append(dict(record))
    return out


def patch_skull_flow(raw, records, *, return_entries=False):
    """Dispatch unique skull pickup identities before the ordinary native grant."""
    from evfl.common import Argument
    from evfl.entry_point import EntryPoint
    from evfl.event import SubFlowEvent
    from evfl.util import make_index
    from oot_rando.patching.event_info import reachable
    from oot_rando.patching.progressive import FlowEditor, link
    from .native_presentations import NO_AMMO_BAG, append_recipe, append_tier_choice, copy_entry
    from .receipt_events import _action, _silent_grant

    records = _records(records)
    if not records:
        return (raw, {}) if return_entries else raw
    editor = FlowEditor(raw, FLOW_PATH)
    chart = editor.chart
    entries = {entry.name: entry for entry in chart.entry_points}
    required = {"GetPouchContent", "OpenGetWindow", "OpenRupeeUIIfNeed", "CloseRupeeUIIfNeed"}
    if chart.name != "GetPouchContent" or not required <= entries.keys():
        raise ValueError(tr("Unknown native pickup flow."))
    if any(event.name.startswith(PREFIX) for event in chart.events):
        raise ValueError(tr("Archipelago Skulltula rewards are already prepared."))
    original = entries["GetPouchContent"].main_event.v
    native = FlowEditor(raw, FLOW_PATH)
    _silent_grant(native, None, entry_name=PREFIX + "TemporaryGrant", prefix=PREFIX + "Temporary")
    grant = copy_entry(native.chart, editor, PREFIX + "TemporaryGrant", PREFIX + "Native",
                       skip=lambda event: _action(event) in {"EventTriggerSetForGetWindow", "EventTriggerSetHavePlayedGetEvent"})

    def register(name, root):
        entry = EntryPoint(name)
        entry.main_event = make_index(root)
        chart.entry_points.append(entry)

    dispatch = original
    effect_entries = {}
    for index, record in reversed(list(enumerate(records, 1))):
        stem = PREFIX + str(index)
        save = editor.action(stem + "_Save", "GameSystemActor", "EventTriggerRequestAutoSave", None)
        commit = editor.action(stem + "_Collected", "GameDataActor", "EventTriggerSetGameDataBool",
                               {"GameDataName": record["flag_name"], "Index": -1, "Value": True})
        link(commit, save)
        close = editor.subflow(stem + "_Close", "", "CloseRupeeUIIfNeed",
                               {"ActorName": Argument("ActorName"), "IsShowNumDisplay": True})
        link(close, commit)
        metadata = ITEM_DATA.get(record.get("local_item"))
        if metadata is not None:
            recipe = append_recipe(editor, metadata, stem + "_Recipe", grant, close, pickup=True)
        else:
            recipe = editor.subflow(stem + "_Recipe_Give", "", grant,
                                   {"ActorName": Argument("ActorName"), "IsGetInEvent": False,
                                    "IsShowNumDisplay": True, "IsTreasureBox": False})
        if isinstance(recipe.data, SubFlowEvent) and recipe.data.entry_point_name == grant:
            link(recipe, close)
        amount = editor.subflow(stem + "_Counter", "", "OpenRupeeUIIfNeed",
                                {"ActorName": Argument("ActorName"), "IsShowNumDisplay": True})
        link(amount, recipe)
        window = editor.subflow(stem + "_Window", "", "OpenGetWindow", None)
        link(window, amount)
        target = editor.action(stem + "_Target", "PouchSystemActor", "EventTriggerSetForGetWindow",
                               {"Actor": Argument("ActorName")})
        link(target, window)
        core = stem + "_Pickup"
        register(core, target)

        def present(branch, actor):
            return editor.subflow(branch + "_Get", "", core, {"ActorName": actor})

        reward = (append_tier_choice(editor, metadata, stem, present, no_ammo=commit) if metadata is not None
                  else present(stem, record["actor"]))
        guarded = editor.switch(stem + "_AlreadyCollected", "GameDataActor", "EventQueryIsGameDataBool",
                                {"GameDataName": record["flag_name"], "Index": -1}, save, reward)
        # Ground pickups use Dm_SY_Get's GuestPerformer grant, not this chart's
        # GetPouchContent entry. Give that authored presentation a quiet effect
        # callback, retaining its original window, pose and camera sequence.
        effect_name = stem + "_Effect"
        def preview(branch, actor):
            target = editor.action(branch + "_PreviewTarget", "PouchSystemActor", "EventTriggerSetForGetWindow",
                                   {"Actor": actor})
            cached = editor.action(branch + "_PreviewCache", "GameDataActor", "EventTriggerSetGameDataString64",
                                   {"GameDataName": NATIVE_SCRATCH, "Index": -1, "Value": actor})
            link(cached, _after_writes(editor, branch + "_PreviewReady", target))
            return cached
        if metadata is not None:
            # The physical get flow opens its window before it grants. Resolve
            # the native item at that earlier boundary without changing inventory
            # or acknowledging the location.
            no_preview = editor.action(stem + "_PreviewNoAmmo", "GameDataActor", "EventTriggerSetGameDataString64",
                                       {"GameDataName": NATIVE_SCRATCH, "Index": -1, "Value": NO_AMMO_BAG})
            register(effect_name + "_Preview", append_tier_choice(editor, metadata, stem + "_Preview", preview,
                                                                    no_ammo=no_preview))
            quiet = append_recipe(editor, metadata, stem + "_QuietRecipe", grant, commit, pickup=True)
            if isinstance(quiet.data, SubFlowEvent) and quiet.data.entry_point_name == grant:
                link(quiet, commit)
            target = editor.action(stem + "_QuietTarget", "PouchSystemActor", "EventTriggerSetForGetWindow",
                                   {"Actor": Argument("ActorName")})
            link(target, quiet)
            quiet_core = stem + "_QuietPouch"
            register(quiet_core, target)
            def effect(branch, actor):
                return editor.subflow(branch + "_Apply", "", quiet_core, {"ActorName": actor})
            quiet_root = append_tier_choice(editor, metadata, stem + "_Quiet", effect, no_ammo=commit)
            quiet_root = editor.switch(stem + "_QuietAlreadyCollected", "GameDataActor", "EventQueryIsGameDataBool",
                                       {"GameDataName": record["flag_name"], "Index": -1}, save, quiet_root)
        else:
            register(effect_name + "_Preview", preview(stem + "_Preview", record["actor"]))
            # The unmodified native GuestPerformer action grants the AP token;
            # this callback only commits its location after that action.
            quiet_root = commit
        register(effect_name, quiet_root)
        effect_entries[record["actor"]] = effect_name
        for number, identity in enumerate((record["actor"], record["pickup"])):
            dispatch = editor.switch(stem + "_Match" + str(number), "GameDataActor", "EventQueryIsGameDataString64",
                                     {"GameDataName": SCRATCH, "Index": -1, "Value": identity}, guarded, dispatch)
    selected = editor.action(PREFIX + "Select", "GameDataActor", "EventTriggerSetGameDataString64",
                             {"GameDataName": SCRATCH, "Index": -1, "Value": Argument("ActorName")})
    link(selected, _after_writes(editor, PREFIX + "SelectReady", dispatch))
    entries["GetPouchContent"].main_event = make_index(selected)

    # Every entry that reaches the dispatcher must preload the new local calls.
    # Existing native/receipt preload lists retain their original prefix.
    for point in chart.entry_points:
        reached = set(reachable(point.main_event.v))
        for call in chart.events:
            if call.name.startswith(PREFIX) and isinstance(call.data, SubFlowEvent) and call in reached:
                position = chart.events.index(call)
                if position not in point._sub_flow_event_indices:
                    point._sub_flow_event_indices.append(position)
    result, _ = editor.write("Archipelago Gold Skulltula pickups")
    return (result, effect_entries) if return_entries else result


def patch_pickup_presentation(raw, records, effect_entries, flow_name):
    """Route the real ground-pickup grant, leaving its authored UI intact."""
    from evfl.common import Argument
    from evfl.actor import Actor
    from evfl.common import ActorIdentifier
    from evfl.event import ActionEvent, SubFlowEvent
    from evfl.util import make_index
    from oot_rando.patching.event_info import reachable
    from oot_rando.patching.progressive import FlowEditor, link
    from .shop_events import _retarget
    from .native_presentations import AMMO_BAGS, NO_AMMO_BAG, append_tier_choice

    records = _records(records)
    editor = FlowEditor(raw, flow_name)
    chart = editor.chart
    if chart.name != flow_name or flow_name not in PICKUP_FLOWS:
        raise ValueError(tr("Unknown native pickup flow."))
    if any(event.name.startswith(PREFIX) for event in chart.events):
        raise ValueError(tr("Archipelago Skulltula rewards are already prepared."))
    if not any(str(actor.identifier) == "GameDataActor" for actor in chart.actors):
        actor = Actor()
        actor.identifier = ActorIdentifier("GameDataActor")
        chart.actors.append(actor)
    originals = list(chart.events)
    for number, (grant_name, message_name) in enumerate(PICKUP_FLOWS[flow_name]):
        grant = next((event for event in chart.events if event.name == grant_name), None)
        message = next((event for event in chart.events if event.name == message_name), None)
        for event, command in ((grant, "EventTriggerAddOwnToPouch"), (message, "EventTriggerSetOwnNameToMessage")):
            if (event is None or not isinstance(event.data, ActionEvent)
                    or str(event.data.actor.v.identifier) != "PouchContentGuestPerformer"
                    or event.data.actor_action.v.v != command or event.data.params is not None):
                raise ValueError(tr("Unknown native pickup flow."))
        continuation = grant.data.nxt.v
        branch = grant
        for index, record in reversed(list(enumerate(records, 1))):
            stem = PREFIX + f"Ground{number}_{index}"
            call = editor.subflow(stem + "_Effect", "GetPouchContent", effect_entries[record["actor"]], None)
            link(call, continuation)
            reward = call
            if "local_item" not in record:
                token = editor.action(stem + "_NativeToken", "PouchContentGuestPerformer",
                                      "EventTriggerAddOwnToPouch", None)
                link(token, call)
                reward = editor.switch(stem + "_AlreadyCollected", "GameDataActor", "EventQueryIsGameDataBool",
                                       {"GameDataName": record["flag_name"], "Index": -1}, call, token)
            for alias, identity in enumerate((record["actor"], record["pickup"])):
                branch = editor.switch(stem + "_Match" + str(alias), "GameDataActor", "EventQueryIsGameDataString64",
                                       {"GameDataName": SCRATCH, "Index": -1, "Value": identity}, reward, branch)
        capture = editor.action(PREFIX + f"GroundSelect{number}", "GameDataActor", "EventTriggerSetGameDataString64",
                                {"GameDataName": SCRATCH, "Index": -1, "Value": Argument("ActorName")})
        link(capture, _after_writes(editor, PREFIX + f"GroundSelectReady{number}", branch))
        incoming = sum(_retarget(event, grant, capture) for event in originals)
        for entry in chart.entry_points:
            if entry.main_event.v is grant:
                entry.main_event = make_index(capture)
                incoming += 1
        if not incoming:
            raise ValueError(tr("Unknown native pickup flow."))

        # Authored order is message -> native window -> grant. Resolve every AP
        # identity explicitly before its window. A foreign GuestPerformer still
        # performs its authored message action first; its actor alias must not
        # overwrite the room-bound pouch identity selected for the AP medal.
        local_message = message
        for index, record in reversed(list(enumerate(records, 1))):
            preview = editor.subflow(PREFIX + f"GroundPreview{number}_{index}", "GetPouchContent",
                                     effect_entries[record["actor"]] + "_Preview", None)
            link(preview, message.data.nxt.v)
            presentation = preview
            if "local_item" not in record:
                presentation = editor.action(PREFIX + f"GroundForeignMessage{number}_{index}",
                                             "PouchContentGuestPerformer", "EventTriggerSetOwnNameToMessage", None)
                link(presentation, preview)
            elif record["native_actor"] in AMMO_BAGS:
                # Skip the authored item window as well as its actual grant.
                # Continue through the native cleanup and commit this location.
                empty = editor.subflow(PREFIX + f"GroundEmptyEffect{number}_{index}", "GetPouchContent",
                                       effect_entries[record["actor"]], None)
                link(empty, continuation)
                mark = editor.action(PREFIX + f"GroundEmpty{number}_{index}", "GameDataActor",
                                     "EventTriggerSetGameDataString64",
                                     {"GameDataName": NATIVE_SCRATCH, "Index": -1, "Value": NO_AMMO_BAG})
                link(mark, _after_writes(editor, PREFIX + f"GroundEmptyReady{number}_{index}", empty))
                presentation = append_tier_choice(editor, ITEM_DATA[record["local_item"]],
                                                  PREFIX + f"GroundAmmo{number}_{index}",
                                                  lambda branch, actor, shown=presentation: shown, no_ammo=mark)
            for alias, identity in enumerate((record["actor"], record["pickup"])):
                local_message = editor.switch(PREFIX + f"GroundMessage{number}_{index}_{alias}", "GameDataActor",
                                              "EventQueryIsGameDataString64",
                                              {"GameDataName": SCRATCH, "Index": -1, "Value": identity},
                                              presentation, local_message)
        selected = editor.action(PREFIX + f"GroundMessageSelect{number}", "GameDataActor", "EventTriggerSetGameDataString64",
                                 {"GameDataName": SCRATCH, "Index": -1, "Value": Argument("ActorName")})
        link(selected, _after_writes(editor, PREFIX + f"GroundMessageReady{number}", local_message))
        clear = editor.action(PREFIX + f"GroundMessageClear{number}", "GameDataActor", "EventTriggerSetGameDataString64",
                              {"GameDataName": NATIVE_SCRATCH, "Index": -1, "Value": ""})
        link(clear, selected)
        incoming = sum(_retarget(event, message, clear) for event in originals)
        for entry in chart.entry_points:
            if entry.main_event.v is message:
                entry.main_event = make_index(clear)
                incoming += 1
        if not incoming:
            raise ValueError(tr("Unknown native pickup flow."))

    # This native notification takes an explicit actor after the grant. A
    # progressive reward may already own its new tier by then; use the concrete
    # actor selected for its original window instead of choosing another tier.
    actors = sorted({actor for record in records
                     for actor in (ITEM_DATA[record["local_item"]].get("tiers", [record["native_actor"]])
                                   if "local_item" in record else [record["actor"]])})
    for number, event in enumerate(originals):
        data = event.data
        if not (isinstance(data, ActionEvent)
                and data.actor_action.v.v == "EventTriggerRequestOpenPickUpWindow"):
            continue
        if (str(data.actor.v.identifier) != "UISystemActor" or data.params is None
                or dict(data.params.data) != {"ActorName": Argument("ActorName")}):
            raise ValueError(tr("Unknown native pickup flow."))
        previous_nodes = list(chart.events)
        branch = event
        for index, actor in reversed(list(enumerate(actors))):
            local = editor.action(PREFIX + f"GroundWindow{number}_{index}", "UISystemActor",
                                  "EventTriggerRequestOpenPickUpWindow", {"ActorName": actor})
            link(local, data.nxt.v)
            branch = editor.switch(PREFIX + f"GroundWindowMatch{number}_{index}", "GameDataActor",
                                   "EventQueryIsGameDataString64",
                                   {"GameDataName": NATIVE_SCRATCH, "Index": -1, "Value": actor}, local, branch)
        branch = editor.switch(PREFIX + f"GroundEmptyWindow{number}", "GameDataActor", "EventQueryIsGameDataString64",
                               {"GameDataName": NATIVE_SCRATCH, "Index": -1, "Value": NO_AMMO_BAG}, data.nxt.v, branch)
        for previous in previous_nodes:
            _retarget(previous, event, branch)
        for entry in chart.entry_points:
            if entry.main_event.v is event:
                entry.main_event = make_index(branch)
    for entry in chart.entry_points:
        for event in reachable(entry.main_event.v):
            if event.name.startswith(PREFIX) and isinstance(event.data, SubFlowEvent):
                index = chart.events.index(event)
                if index not in entry._sub_flow_event_indices:
                    entry._sub_flow_event_indices.append(index)
    return editor.write("Native Skulltula pickup presentation")[0]


def prepare_skulls(romfs, mod, roster, settings=None):
    """Stage the native drop kits, then their exactly-once get-event callbacks."""
    from oot_rando.game.resource_allocations import grow_resources
    from .engine import run_engine
    records = skull_records(roster)
    if not records:
        return {}
    romfs, mod = Path(romfs), Path(mod)
    if mod.name != "romfs" or mod.parent.name != "Archipelago":
        raise ValueError(tr("Invalid Archipelago Skulltula metadata."))
    print(tr("Preparing Archipelago Gold Skulltula rewards…"), flush=True)
    print(run_engine("skulls", {"skulls": records}, romfs, mod).strip(), flush=True)
    codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())

    def source(path):
        staged = mod / path
        return (staged if staged.is_file() else romfs / path).read_bytes()

    frame, table_frame = source(FLOW_PATH), source(REST)
    before = codec.decode(frame)
    after, effects = patch_skull_flow(before, records, return_entries=True)
    changed = {FLOW_PATH: (after, frame, len(before))}
    for name in PICKUP_FLOWS:
        path = "Event/EventFlow/" + name + ".bfevfl.zs"
        old_frame = source(path)
        old = codec.decode(old_frame)
        changed[path] = (patch_pickup_presentation(old, records, effects, name), old_frame, len(old))
    table, allocations = grow_resources(codec.decode(table_frame),
                                         {path: max(0, len(raw) - size) for path, (raw, _, size) in changed.items()})
    encoded = {path: codec.encode(raw, old) for path, (raw, old, _) in changed.items()}
    encoded[REST] = codec.encode(table, table_frame)
    for path, content in encoded.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return {"purchases": 0, "pickups": len(records), "allocations": allocations}
