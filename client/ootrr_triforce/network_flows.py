"""Bind native NPC/minigame presentations to one AP reward, without extra gains.

Only the selected reward call is replaced. Its authored handover and get-item
graphs are copied into the same chart; their native camera, waits, actor
bindings and cleanup remain intact. Their inventory callback is location bound.
"""
from pathlib import Path
import re

from .catalog import ITEM_DATA, LOCATION_IDS
from .mod_codec import Codec
from .network_rewards import validate_record

REST = "System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs"
GET = "GetPouchContent"
PREFIX = "OOTRR_APSource_"
GRANT_FLOWS = {"Dm_SY_GetInEvent", "NpcCommon", "SimpleShop", "MiniGame_FrogTenors",
               "Enemy_Scrub_Business_Common"}


def _params(event):
    params = getattr(event.data, "params", None)
    return params.data if params is not None else {}


def _find(chart, name):
    found = [event for event in chart.events if event.name == name]
    if len(found) != 1:
        raise ValueError("Unknown native reward event: " + str(name))
    return found[0]


def _dungeon_credit(event, item, *, head=False):
    """Recognize the exact native credit recipe for the superseded prize."""
    from evfl.event import ActionEvent
    from .receipt_events import DUNGEONS
    metadata = ITEM_DATA.get(item, {})
    kind, dungeon = metadata.get("kind"), metadata.get("dungeon")
    if metadata.get("mode") != "generic" or not dungeon:
        return event
    if event is None or (not head and not re.fullmatch(r"Key[0-9]+", event.name)):
        return event
    prefix = "DungeonInfo." + DUNGEONS[dungeon] + "."
    if kind in {"SmallKey", "HideoutSmallKey"}:
        writes = [("EventTriggerAddOrSubGameDataInt", "SmallKeyNum", 1),
                  ("EventTriggerAddOrSubGameDataInt", "SmallKeyTotalNum", 1),
                  ("EventTriggerSetGameDataBool", "IsGetSmallKeyOnce", True)]
        tag = "SmallKey"
    else:
        tag, member = {"Map": ("Map", "IsGetMap"), "Compass": ("Compass", "IsGetCompass"),
                       "BossKey": ("BossKey", "IsGetBossKey"),
                       "GanonBossKey": ("BossKey", "IsGetBossKey")}[kind]
        writes = [("EventTriggerSetGameDataBool", member, True)]
    current = event
    for number, (action, member, value) in enumerate(writes):
        if (current is None or not isinstance(current.data, ActionEvent)
                or (not head or number) and not re.fullmatch(r"Key[0-9]+", current.name)
                or str(current.data.actor.v.identifier) != "GameDataActor"
                or current.data.actor_action.v.v != action
                or dict(_params(current)) != {"GameDataName": prefix + member, "Index": -1, "Value": value}):
            raise ValueError("Unknown native dungeon credit for " + str(item))
        current = current.data.nxt.v
    if (current is None or not isinstance(current.data, ActionEvent)
            or not re.fullmatch(r"Key[0-9]+", current.name)
            or str(current.data.actor.v.identifier) != "SystemTextNPC"
            or current.data.actor_action.v.v != "EventTalk"
            or _params(current).get("MessageId") != "EventFlowMsg/Dm_SY_Get:OOTRR_" + tag + "_" + DUNGEONS[dungeon]):
        raise ValueError("Unknown native dungeon credit message for " + str(item))
    return current.data.nxt.v


def _native_continuation(event, item=None):
    """Remove only OOTRR's generated extra grant for the superseded reward."""
    from evfl.event import ActionEvent
    seen = set()
    while event is not None and event.name.startswith(("OOTRRGiveBag", "OOTRRBag", "OOTRRHeldAdd")):
        if event in seen:
            raise ValueError("Cyclic native reward continuation.")
        seen.add(event)
        data = event.data
        if event.name.startswith(("OOTRRBag", "OOTRRGiveBag")):
            from .receipt_events import native_starter_exit
            following = native_starter_exit(event)
            # A native give with no continuation ends on a one-frame wait.
            # Keep that authored terminal instead of treating it as a grant.
            if following is event:
                return event
            event = following
            continue
        if not isinstance(data, ActionEvent):
            raise ValueError("Unknown native reward continuation.")
        actor, action, params = str(data.actor.v.identifier), data.actor_action.v.v, _params(event)
        if event.name.startswith("OOTRRHeldAdd"):
            native = ITEM_DATA.get(item, {})
            allowed = {native.get("actor"), *native.get("tiers", ())}
            allowed = {name for name in allowed if isinstance(name, str)
                       and (name.startswith("Item_Melody_") or name in {"Item_Ocarina_Fairy", "Item_Ocarina_Time"})}
            give = (actor == "PouchSystemActor" and action == "EventTriggerAddOrRemovePouchContent"
                    and params.get("Actor") in allowed and params.get("Num") == 1)
            equip = (actor == "GameDataActor" and action == "EventTriggerSetGameDataString64"
                     and params.get("GameDataName") == "PlayerStatus.EquipOcarina"
                     and params.get("Value") in allowed and params.get("Index") == -1)
            if not (give or equip):
                raise ValueError("Unknown native held-item compensation for " + str(item))
        elif (actor != "PouchSystemActor" or action != "EventTriggerAddOrRemovePouchContent"
              or params.get("Num", 0) <= 0):
            raise ValueError("Unknown native equipment refill action.")
        event = data.nxt.v
    return _dungeon_credit(event, item)


def _grant_template(event, parameter, item=None):
    """Replace a native progressive selector as a whole, including its refill."""
    from evfl.event import SwitchEvent, SubFlowEvent, ActionEvent
    if not isinstance(event.data, SwitchEvent):
        if not hasattr(event.data, "nxt"):
            raise ValueError("Unsupported native grant shape: " + event.name)
        return event, _native_continuation(event.data.nxt.v, item)
    pending, visited, leaves = [event], set(), []
    while pending:
        node = pending.pop()
        if node is None or node in visited:
            continue
        visited.add(node)
        data = node.data
        if isinstance(data, SwitchEvent):
            if (str(data.actor.v.identifier) != "GameDataActor"
                    or data.actor_query.v.v != "EventQueryCheckIsGet"
                    or set(_params(node)) != {"ActorName"} or set(data.cases) != {0, 1}):
                raise ValueError("Unknown native progressive selector: " + node.name)
            pending.extend(case.v for case in data.cases.values())
        elif isinstance(data, (SubFlowEvent, ActionEvent)):
            leaves.append(node)
        else:
            raise ValueError("Unknown native progressive reward branch.")
    if not leaves:
        raise ValueError("Native progressive reward has no grant.")
    template = leaves[0]
    continuation = _native_continuation(template.data.nxt.v, item)
    shape = (type(template.data), getattr(template.data, "res_flowchart_name", None),
             getattr(template.data, "entry_point_name", None),
             {key: value for key, value in _params(template).items() if key != parameter})
    for leaf in leaves:
        other = (type(leaf.data), getattr(leaf.data, "res_flowchart_name", None),
                 getattr(leaf.data, "entry_point_name", None),
                 {key: value for key, value in _params(leaf).items() if key != parameter})
        if other != shape or _native_continuation(leaf.data.nxt.v, item) is not continuation:
            raise ValueError("Native progressive rewards do not share their cleanup.")
    return template, continuation


def _select(editor, selector):
    from evfl.event import SubFlowEvent
    from oot_rando.patching.event_info import reachable
    chart = editor.chart
    kind = selector["selector"]
    if kind == "event":
        return _find(chart, selector["event"])
    if kind == "next_after_event":
        origin = _find(chart, selector["origin_event"])
        node = getattr(origin.data, "nxt", None)
        node = node.v if node is not None else None
        if node is None or not isinstance(node.data, SubFlowEvent):
            raise ValueError("Missing native extra reward call.")
        return node
    if kind == "after_native_flag":
        entry = next((point for point in chart.entry_points if point.name == selector["entry"]), None)
        if entry is None:
            raise ValueError("Missing native one-time reward adapter: " + selector["entry"])
        candidates = []
        for event in reachable(entry.main_event.v):
            action = getattr(getattr(event.data, "actor_action", None), "v", None)
            if (getattr(action, "v", None) == "EventTriggerSetGameDataBool"
                    and _params(event).get("GameDataName") == selector["flag_name"]
                    and _params(event).get("Value") is True):
                node = event.data.nxt.v
                if node is not None and isinstance(node.data, SubFlowEvent):
                    candidates.append(node)
        if len(candidates) != 1:
            raise ValueError("Unknown native one-time reward sequence.")
        return candidates[0]
    if kind == "entry_subflow_parameter":
        entry = next((point for point in chart.entry_points if point.name == selector["entry"]), None)
        candidates = ([event for event in reachable(entry.main_event.v)
                       if isinstance(event.data, SubFlowEvent) and selector["param"] in _params(event)]
                      if entry is not None else [])
        if len(candidates) != 1:
            raise ValueError("Unknown native one-time sale adapter.")
        return candidates[0]
    raise ValueError("Unknown native reward selector: " + str(kind))


class NativeReward:
    """Copy only the native handover/presentation calls reached by one reward."""
    def __init__(self, editor, record, effect, read):
        from .presentation_models import SHOW_ACTOR_ARGUMENT, needs_model_alias
        self.editor, self.record, self.effect, self.read = editor, record, effect, read
        self.prefix = PREFIX + str(LOCATION_IDS[record["name"]])
        self.copies = {}
        self.grants = 0
        self.show_argument = SHOW_ACTOR_ARGUMENT
        self.separate_model = "local_item" in record and needs_model_alias(ITEM_DATA[record["local_item"]])
        self._held_offset = None

    def clone(self, flow, entry):
        from evfl.event import SubFlowEvent, ActionEvent
        from evfl.common import Argument
        from evfl.container import Container
        from oot_rando.patching.progressive import FlowEditor
        from .native_presentations import copy_entry, owns_health_refresh
        key = (flow, entry)
        if key in self.copies:
            return self.copies[key]
        source = FlowEditor(self.read("Event/EventFlow/" + flow + ".bfevfl.zs"), flow)
        stem = self.prefix + "_Native" + str(len(self.copies))
        target = stem + "_" + entry
        self.copies[key] = target

        def effect(data):
            call = SubFlowEvent()
            call.nxt = data.nxt
            call.res_flowchart_name, call.entry_point_name = GET, self.effect
            return call

        def transform(event, original):
            data = event.data
            if not isinstance(data, ActionEvent):
                return
            actor = str(data.actor.v.identifier)
            action = data.actor_action.v.v
            params = _params(event)
            if (self.separate_model and action == "EventCreateShowItemFromActorFileName"
                    and isinstance(params.get("Actor"), Argument) and str(params["Actor"]) == "ActorName"):
                params["Actor"] = Argument(self.show_argument)
            if self.separate_model and action == "EventIgnitionShowItem":
                from .held_framing import compensate_position, display_offset
                if self._held_offset is None:
                    self._held_offset = display_offset(ITEM_DATA[self.record["local_item"]], self.read)
                if self._held_offset is not None and any(self._held_offset):
                    # A copied NPC gift retains its authored camera and base
                    # ItemPos. The isolated show model lacks the pouch offset
                    # which this native command normally adds automatically.
                    params["ItemPos"] = compensate_position(params, self._held_offset)
            inventory = (actor == "PouchSystemActor" and (
                (action == "EventTriggerAddOrRemovePouchContent" and params.get("Num", 1) > 0)
                or action in {"EventTriggerPushToEmptyBottle", "EventTriggerAddGameDataIntToRupee"}))
            if inventory:
                event.data = effect(data)
                self.grants += 1

        def forward_model(data):
            if self.separate_model:
                if data.params is None:
                    data.params = Container()
                data.params.data[self.show_argument] = Argument(self.show_argument)

        def callback(event, original):
            data = event.data
            owner = data.res_flowchart_name or flow
            if owner == GET:
                if data.entry_point_name.startswith("GetPouchContent"):
                    if data.params is None or "ActorName" not in data.params.data:
                        raise ValueError("Native reward call has no item argument.")
                    data.params.data["ActorName"] = self.record["actor"]
                    self.grants += 1
                elif data.entry_point_name in {"PushToEmptyBottle", "PushToSelectedBottle"}:
                    event.data = effect(data)
                    self.grants += 1
                return
            # Local subflows were already copied with their exact native args.
            if not original.data.res_flowchart_name:
                forward_model(data)
                return
            if owner in GRANT_FLOWS or owner == flow:
                data.res_flowchart_name = ""
                data.entry_point_name = self.clone(owner, original.data.entry_point_name)
                forward_model(data)

        def skip(event):
            data = event.data
            action = getattr(getattr(data, "actor_action", None), "v", None)
            if getattr(action, "v", None) == "EventTriggerSetHavePlayedGetEvent":
                return True
            return ("local_item" in self.record and owns_health_refresh(ITEM_DATA[self.record["local_item"]])
                    and getattr(data, "res_flowchart_name", None) == "Dm_SY_Get"
                    and getattr(data, "entry_point_name", None) == "CheckHeart")

        copied = copy_entry(source.chart, self.editor, entry, stem, local_closure=True,
                            callback=callback, transform=transform, skip=skip, bind_arguments=True)
        if copied != target:
            raise ValueError("Native reward entry identity changed.")
        return copied


def patch_reward(editor, original, parameter, record, effect, read, number, native=None):
    from evfl.event import SubFlowEvent, ActionEvent
    from evfl.util import make_index
    from oot_rando.patching.progressive import link
    from .native_presentations import append_tier_choice
    from .shop_events import _retarget

    prior = list(editor.chart.events)
    stem = PREFIX + str(LOCATION_IDS[record["name"]]) + "_" + str(number)
    direct_credit = (isinstance(original.data, ActionEvent)
                     and str(original.data.actor.v.identifier) == "GameDataActor"
                     and _params(original).get("GameDataName", "").startswith("DungeonInfo."))
    if direct_credit:
        template = original
        continuation = _dungeon_credit(original, record.get("generated_item"), head=True)
        if continuation is original:
            raise ValueError("Missing canonical native dungeon reward metadata.")
        params = {}
    else:
        template, continuation = _grant_template(original, parameter, record.get("generated_item"))
        params = dict(_params(template))
        if parameter not in params or not isinstance(params[parameter], str):
            raise ValueError("Native source has no supported reward argument: " + record["name"])
    from .network_offer_texts import offer_parameters
    params = offer_parameters(record, params)
    native = native or NativeReward(editor, record, effect, read)
    if isinstance(template.data, SubFlowEvent):
        flow = template.data.res_flowchart_name or editor.chart.name
        entry = template.data.entry_point_name
        for prefix in ("OOTRR_W_", "OOTRR_K_"):
            if entry.startswith(prefix):
                entry = entry[len(prefix):]
                break
        if flow == GET and entry == "DisplayGetByActorName":
            entry = "GetPouchContentByActorName"
        if flow == GET and entry.startswith("GetPouchContent"):
            def present(branch, actor):
                call = editor.subflow(branch + "_Get", GET, entry, dict(params, **{parameter: record["actor"]}))
                link(call, continuation)
                return call
        else:
            copied = native.clone(flow, entry)
            if not native.grants:
                raise ValueError("Native presentation has no inventory callback: " + record["name"])
            def present(branch, actor):
                actual = dict(params, **{parameter: actor})
                if "DisplayItemActor" in actual:
                    actual["DisplayItemActor"] = actor
                if native.separate_model:
                    from .presentation_models import model_actor
                    actual[native.show_argument] = model_actor(actor)
                call = editor.subflow(branch + "_Get", "", copied, actual)
                link(call, continuation)
                return call
    elif isinstance(template.data, ActionEvent):
        if not direct_credit and (str(template.data.actor.v.identifier) != "PouchSystemActor"
                or template.data.actor_action.v.v != "EventTriggerAddOrRemovePouchContent"
                or params.get("Num") != 1):
            raise ValueError("Unsupported direct native reward: " + record["name"])
        def present(branch, actor):
            call = editor.subflow(branch + "_Effect", GET, effect, None)
            link(call, continuation)
            return call
    else:
        raise ValueError("Native reward is not a grant call: " + record["name"])
    empty = editor.subflow(stem + "_Empty", GET, effect, None)
    link(empty, continuation)
    reward = (append_tier_choice(editor, ITEM_DATA[record["local_item"]], stem, present, no_ammo=empty)
              if "local_item" in record else present(stem, record["actor"]))
    collected = continuation
    if record["name"] == "ZR Magic Bean Salesman":
        # Only the first bean purchase is this AP location. Later purchases
        # retain the native bean handover, price ladder and purchase counter.
        if (not isinstance(template.data, SubFlowEvent) or flow != "NpcCommon"
                or entry != "NpcCommon_HandOver_NpcToPlayer_NoDisplay"
                or parameter != "ReveiveItem"):
            raise ValueError("Unknown native repeat bean purchase.")
        collected = editor.subflow(stem + "_RepeatBean", flow, entry,
                                   dict(params, ReveiveItem="Item_MagicBean"))
        link(collected, continuation)
    root = editor.switch(stem + "_Collected", "GameDataActor", "EventQueryIsGameDataBool",
                         {"GameDataName": record["flag_name"], "Index": -1}, collected, reward)
    incoming = sum(_retarget(event, original, root) for event in prior)
    for point in editor.chart.entry_points:
        if point.main_event.v is original:
            point.main_event = make_index(root)
            incoming += 1
    if not incoming:
        raise ValueError("Native reward has no reachable caller: " + record["name"])


def patch_display(editor, original, parameter, record, number):
    """Keep an authored preview/fanfare consistent with the actual AP reward."""
    from evfl.event import ActionEvent, SubFlowEvent
    from evfl.util import make_index
    from oot_rando.patching.progressive import link
    from .native_presentations import append_tier_choice
    from .shop_events import _retarget
    prior = list(editor.chart.events)
    stem = PREFIX + str(LOCATION_IDS[record["name"]]) + "_Display" + str(number)
    template, continuation = _grant_template(original, parameter, record.get("generated_item"))
    params = dict(_params(template))
    if parameter not in params or not isinstance(params[parameter], str):
        raise ValueError("Native source has no supported display argument: " + record["name"])
    def present(branch, actor):
        actual = dict(params, **{parameter: actor})
        data = template.data
        if isinstance(data, ActionEvent):
            call = editor.action(branch + "_Show", str(data.actor.v.identifier), data.actor_action.v.v, actual)
        elif isinstance(data, SubFlowEvent):
            call = editor.subflow(branch + "_Show", data.res_flowchart_name, data.entry_point_name, actual)
        else:
            raise ValueError("Unknown native reward preview.")
        link(call, continuation)
        return call
    selected = (append_tier_choice(editor, ITEM_DATA[record["local_item"]], stem, present, no_ammo=continuation)
                if "local_item" in record else present(stem, record["actor"]))
    root = editor.switch(stem + "_Collected", "GameDataActor", "EventQueryIsGameDataBool",
                         {"GameDataName": record["flag_name"], "Index": -1}, continuation, selected)
    incoming = sum(_retarget(event, original, root) for event in prior)
    for point in editor.chart.entry_points:
        if point.main_event.v is original:
            point.main_event = make_index(root)
            incoming += 1
    if not incoming:
        raise ValueError("Native reward preview has no caller: " + record["name"])


def prepare_flow_rewards(romfs, mod, records, settings, effects):
    from evfl.event import SubFlowEvent
    from oot_rando.patching.event_info import reachable
    from oot_rando.patching.progressive import FlowEditor
    from oot_rando.game.resource_allocations import grow_resources
    from oot_rando.patching.event_bindings import complete_forwarded_actor_bindings
    romfs, mod = Path(romfs), Path(mod)
    flows = [record for record in records if validate_record(record)["kind"] == "flow"]
    if not flows:
        return {}
    codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
    def frame(path):
        target = mod / path
        return (target if target.is_file() else romfs / path).read_bytes()
    cache = {}
    def read(path):
        if path not in cache:
            cache[path] = codec.decode(frame(path))
        return cache[path]
    editors, counts, native_copies = {}, {}, {}
    for record in flows:
        selectors = record["metadata"].get("post_build_grants", ())
        if not selectors:
            raise ValueError("Native source has no effective grant adapter: " + record["name"])
        seen = set()
        for number, selector in enumerate(selectors):
            path = selector["file"]
            if path not in editors:
                editors[path] = FlowEditor(read(path), path)
            editor = editors[path]
            original = _select(editor, selector)
            identity = (path, original.name, selector["param"])
            if identity in seen:
                continue
            seen.add(identity)
            key = (path, record["name"])
            if key not in native_copies:
                native_copies[key] = NativeReward(editor, record, effects[record["actor"]], read)
            patch_reward(editor, original, selector["param"], record, effects[record["actor"]], read,
                         number, native_copies[key])
            counts[record["name"]] = counts.get(record["name"], 0) + 1
        for number, display in enumerate(record["metadata"].get("flow_edits", ())):
            if display["role"] != "display":
                continue
            path = display["file"]
            if path not in editors:
                editors[path] = FlowEditor(read(path), path)
            patch_display(editors[path], _find(editors[path].chart, display["event"]),
                          display["param"], record, number)
    changed = {}
    for path, editor in editors.items():
        # Local native copies can forward the same NPC through several entry
        # aliases. Their provider must expose the children's native callbacks.
        complete_forwarded_actor_bindings(editor.chart)
        for point in editor.chart.entry_points:
            for event in reachable(point.main_event.v):
                if event.name.startswith(PREFIX) and isinstance(event.data, SubFlowEvent):
                    index = editor.chart.events.index(event)
                    if index not in point._sub_flow_event_indices:
                        point._sub_flow_event_indices.append(index)
        changed[path] = editor.write("Native Archipelago reward callbacks")[0]
    table, _ = grow_resources(read(REST), {path: max(0, len(raw) - len(read(path))) for path, raw in changed.items()})
    changed[REST] = table
    encoded = {path: codec.encode(raw, frame(path)) for path, raw in changed.items()}
    for path, content in encoded.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    from .network_merchant_preflight import prepare_merchant_preflight
    prepare_merchant_preflight(romfs, mod, flows)
    return counts
