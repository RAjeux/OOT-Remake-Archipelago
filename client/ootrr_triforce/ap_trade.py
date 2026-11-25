"""Location-bound adult trade rewards with native presentation and one commit.

The NPC dialogue owns the handover animation. This callback verifies current
stock, presents only the shuffled reward, and consumes only that NPC's input.
It never acknowledges a remote ReceivedItems index.
"""
import json
from pathlib import Path

from .catalog import ITEM_DATA, ITEM_IDS
from .i18n import tr
from .mod_codec import Codec
from .trade_catalog import TALON_AWAKE, TRADE_CHECKS, event_name

FLOW_NAME = "GetPouchContent"
FLOW_PATH = "Event/EventFlow/GetPouchContent.bfevfl.zs"
PRESENTER_PATH = "Event/EventFlow/Dm_SY_GetInEvent.bfevfl.zs"
GROUND_PATH = "Event/EventFlow/Dm_SY_Get.bfevfl.zs"
REST = "System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs"
PREFIX = "OOTRR_APTrade"
GRANT = PREFIX + "QuietGrant"
DISPLAY = PREFIX + "Display"


def _invalid():
    return ValueError(tr("Invalid Archipelago trade metadata."))


def trade_records(roster, *, require_all=False):
    """Resolve only the append-only trade catalogue; legacy rooms stay inert."""
    from oot_rando.patching import ap_item
    names = sorted(set(roster).intersection(TRADE_CHECKS))
    if names and require_all and set(names) != set(TRADE_CHECKS):
        raise _invalid()
    records = []
    for name in names:
        reward, source = roster[name], TRADE_CHECKS[name]
        if (not isinstance(reward, dict) or type(reward.get("local")) is not bool
                or not isinstance(reward.get("item"), str) or not reward["item"]
                or not isinstance(reward.get("player"), str) or not reward["player"]):
            raise _invalid()
        local, item = reward["local"], reward["item"]
        if local and (item not in ITEM_DATA or reward.get("item_id", ITEM_IDS[item]) != ITEM_IDS[item]):
            raise _invalid()
        label = ap_item.ap_item(json.dumps([name, item, reward["player"]], ensure_ascii=False))
        records.append(dict(name=name, id=source["id"], flag_name=source["flag_name"],
                            required_actor=source["required_actor"], wake_talon=source["wake_talon"],
                            local=local, item=item if local else None, actor=ap_item.ap_actor(label)))
    return records


def _preloads(editor, prefix=PREFIX):
    from evfl.event import SubFlowEvent
    from oot_rando.patching.event_info import reachable
    for point in editor.chart.entry_points:
        for node in reachable(point.main_event.v):
            if node.name.startswith(prefix) and isinstance(node.data, SubFlowEvent):
                index = editor.chart.events.index(node)
                if index not in point._sub_flow_event_indices:
                    point._sub_flow_event_indices.append(index)


def build_trade_rewards(pouch_raw, presenter_raw, roster, *, native_info=None, ground_raw=None,
                        records=None, prefix=PREFIX, event_stem=event_name, reconcile=True):
    """Return both changed charts and the location-bound NPC callback entries."""
    from evfl.common import Argument
    from evfl.entry_point import EntryPoint
    from evfl.event import SubFlowEvent
    from evfl.util import make_index
    from oot_rando.patching.progressive import FlowEditor, link
    from .ap_skulls import _after_writes
    from .native_presentations import (AMMO_BAGS, PRESENTER_NAME, append_recipe, append_tier_choice,
                                       copy_entry, copy_receipt_presenter, receipt_style)
    from .receipt_events import _action, _silent_grant
    from .presentation_models import SHOW_ACTOR_ARGUMENT, model_actor, needs_model_alias
    from .restoration import _native_source
    from .trade_state import append_reconcile

    records = trade_records(roster) if records is None else list(records)
    if not records:
        return pouch_raw, presenter_raw, {}
    pouch, presenter = FlowEditor(pouch_raw, FLOW_PATH), FlowEditor(presenter_raw, PRESENTER_PATH)
    if (pouch.chart.name != FLOW_NAME or presenter.chart.name != PRESENTER_NAME
            or any(point.name.startswith(prefix) for editor in (pouch, presenter)
                   for point in editor.chart.entry_points)):
        raise _invalid()

    def register(editor, name, root):
        point = EntryPoint(name)
        point.main_event = make_index(root)
        editor.chart.entry_points.append(point)

    grant = None
    if any(record["local"] for record in records):
        native = FlowEditor(pouch_raw, "Native adult trade grant source")
        _native_source(native)
        grant_name = prefix + "QuietGrant"
        _silent_grant(native, None, entry_name=grant_name + "Source", prefix=grant_name + "Source")
        grant = copy_entry(native.chart, pouch, grant_name + "Source", grant_name,
                           skip=lambda node: _action(node) in {
                               "EventTriggerSetForGetWindow", "EventTriggerSetHavePlayedGetEvent"})

    # Native display may request a caption save before the grant. The trade's
    # single save must follow its input, reward and completed-location flag.
    display = copy_entry(pouch.chart, pouch, "DisplayGetByActorName", prefix + "Display",
                         local_closure=True,
                         skip=lambda node: _action(node) == "EventTriggerRequestAutoSave")

    entries = {}
    for record in records:
        stem = event_stem(record["id"])
        metadata = (ITEM_DATA[record["item"]] if record["local"]
                    else dict(actor=record["actor"], mode="actor", kind="Item"))
        style = receipt_style(metadata, native_info) if record["local"] else "large"
        core_name = stem + "_Pouch"
        save = pouch.action(stem + "_Save", "GameSystemActor", "EventTriggerRequestAutoSave", None)
        reconciled = (append_reconcile(pouch, stem + "_Reconcile", save) if reconcile
                      else _after_writes(pouch, stem + "_SavedFlag", save))
        commit = pouch.action(stem + "_Complete", "GameDataActor", "EventTriggerSetGameDataBool",
                              {"GameDataName": record["flag_name"], "Index": -1, "Value": True})
        link(commit, reconciled)
        effect = commit
        if record["local"]:
            effect = append_recipe(pouch, metadata, core_name, grant, commit, pickup=style == "pickup")
            if isinstance(effect.data, SubFlowEvent):
                link(effect, commit)

        # All mutation lives in the presentation's real grant callback. A quit
        # during the pose cannot save only a consumed quest item.
        core = effect
        required = record["required_actor"]
        if required:
            consumed = pouch.action(stem + "_Consume", "PouchSystemActor", "EventTriggerAddOrRemovePouchContent",
                                    {"Actor": required, "Num": -1, "IsEquipDIrect": False,
                                     "IsSetMessageTargetActorName": False, "IsGetEvent": False})
            link(consumed, _after_writes(pouch, stem + "_Consumed", effect))
            core = consumed

        def guard(branch, success):
            root = success
            if record["local"] and metadata.get("bottle_item") and metadata.get("pouch_special") == "NotPushToPouch":
                root = pouch.switch(branch + "_Bottle", "PouchSystemActor", "EventQueryIsAnyBottleEmpty", None,
                                    root, None)
            if record["wake_talon"]:
                root = pouch.switch(branch + "_Talon", "GameDataActor", "EventQueryIsGameDataBool",
                                    {"GameDataName": TALON_AWAKE, "Index": -1}, root, None)
            if required:
                root = pouch.switch(branch + "_HasInput", "PouchSystemActor", "EventQueryIsExistInPouch",
                                    {"Actor": required, "Num": 1}, root, None)
            return pouch.switch(branch + "_AlreadyComplete", "GameDataActor", "EventQueryIsGameDataBool",
                                {"GameDataName": record["flag_name"], "Index": -1}, None, root)

        register(pouch, core_name, guard(stem + "_Core", core))
        shown = (copy_receipt_presenter(presenter, metadata, record["id"], core_name, style=style,
                                       ground_raw=ground_raw, prefix=prefix + "Show_" + str(record["id"]))
                 if style != "pickup" else None)
        if shown:
            # Retain all native model/sound/camera actions, except intermediate
            # save requests. Only the callback above commits this transaction.
            from .shop_events import _retarget
            for node in list(presenter.chart.events):
                if node.name.startswith(prefix + "Show_" + str(record["id"])) and _action(node) == "EventTriggerRequestAutoSave":
                    for parent in list(presenter.chart.events):
                        _retarget(parent, node, node.data.nxt.v)
                    for point in presenter.chart.entry_points:
                        if point.main_event.v is node:
                            point.main_event = make_index(node.data.nxt.v)

        def present(branch, actor):
            if style == "pickup":
                call = pouch.subflow(branch + "_Get", "", core_name, {"ActorName": actor})
                if native_info is None or not native_info[actor].get("IsNotOpenStockNumDisplay", False):
                    popup = pouch.action(branch + "_Pickup", "UISystemActor", "EventTriggerRequestOpenPickUpWindow",
                                         {"ActorName": actor})
                    link(call, popup)
                return call
            arguments = {"ActorName": actor, "IsNpcEventStarter": False}
            if needs_model_alias(metadata):
                arguments[SHOW_ACTOR_ARGUMENT] = model_actor(actor)
            call = pouch.subflow(branch + "_Show", PRESENTER_NAME, shown, arguments)
            return call

        # The copied native presenter enters the effect callback directly.
        # Its original DisplayGetByActorName call is redirected to a save-free
        # clone before the actual recipe, preserving native item text and sound.
        point = next(point for point in pouch.chart.entry_points if point.name == core_name)
        recipe_root = point.main_event.v
        if style != "pickup":
            window = pouch.subflow(stem + "_Window", "", display, {"ActorName": Argument("ActorName")})
            link(window, recipe_root)
            point.main_event = make_index(window)
        no_ammo = commit
        if required and metadata["actor"] in AMMO_BAGS:
            consumed_empty = pouch.action(stem + "_EmptyConsume", "PouchSystemActor", "EventTriggerAddOrRemovePouchContent",
                                          {"Actor": required, "Num": -1, "IsEquipDIrect": False,
                                           "IsSetMessageTargetActorName": False, "IsGetEvent": False})
            link(consumed_empty, _after_writes(pouch, stem + "_EmptyConsumed", commit))
            no_ammo = consumed_empty
        root = (append_tier_choice(pouch, metadata, stem + "_Present", present, no_ammo=no_ammo) if record["local"]
                else present(stem + "_Present", record["actor"]))
        register(pouch, stem, guard(stem + "_Outer", root))
        entries[record["id"]] = stem

    _preloads(pouch, prefix)
    _preloads(presenter, prefix)
    return pouch.write("Native Archipelago adult trade rewards")[0], presenter.write("Native adult trade presentations")[0], entries


def prepare_trade_rewards(romfs, mod, roster, settings=None):
    """Stage reward callbacks; NPC wrappers register their dependency closure."""
    records = trade_records(roster, require_all=True)
    if not records:
        return {}
    from oot_rando.formats import byml_codec
    from oot_rando.game.resource_allocations import grow_resources
    romfs, mod = Path(romfs), Path(mod)
    if mod.name != "romfs" or mod.parent.name != "Archipelago":
        raise _invalid()

    def source(path):
        staged = mod / path
        return (staged if staged.is_file() else romfs / path).read_bytes()

    codec = Codec(source("Pack/ZsDic.pack.zs"))
    paths = (FLOW_PATH, PRESENTER_PATH)
    frames = {path: source(path) for path in paths}
    before = {path: codec.decode(frame) for path, frame in frames.items()}
    info = {row["__RowId"]: row for row in byml_codec.load(
        codec.decode(source("RSDB/PouchActorInfo.Product.111.rstbl.byml.zs")))["root"]}
    pouch, presenter, entries = build_trade_rewards(before[FLOW_PATH], before[PRESENTER_PATH], roster,
        native_info=info, ground_raw=codec.decode(source(GROUND_PATH)))
    modified = {FLOW_PATH: pouch, PRESENTER_PATH: presenter}
    rest_frame = source(REST)
    table, allocations = grow_resources(codec.decode(rest_frame),
        {path: max(0, len(raw) - len(before[path])) for path, raw in modified.items()})
    encoded = {path: codec.encode(raw, frames[path]) for path, raw in modified.items()}
    encoded[REST] = codec.encode(table, rest_frame)
    for path, content in encoded.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return dict(trades=len(records), entries=entries, allocations=allocations)
