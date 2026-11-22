"""Keep native trade stocks consistent with independently completed AP trades."""
from pathlib import Path

from .catalog import TRADE_CHECKS
from .cursor_resource import append_saved_bool
from .i18n import tr
from .mod_codec import Codec
from .trade_catalog import TALON_AWAKE

FLOW_PATH = "Event/EventFlow/GetPouchContent.bfevfl.zs"
GAME_DATA = "GameData/GameDataList.Product.110.byml.zs"
REST = "System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs"
PREFIX = "OOTRR_APTradeState"


def append_reconcile(editor, stem, after):
    """Discard a spent token if older-save replay delivered its source later.

    Native stocks already hold concurrent trade items. A location's saved flag
    proves consumption, so no second ownership database is needed. Both frame
    waits are native event actions: preceding flag/item writes and the final
    removals must settle before another query or save observes their result.
    """
    from oot_rando.patching.progressive import link
    from .ap_skulls import _after_writes

    root = _after_writes(editor, stem + "_Committed", after)
    for index, record in reversed(list(enumerate(TRADE_CHECKS.values()))):
        actor = record["required_actor"]
        if actor is None:
            continue
        remove = editor.action(stem + "_Remove" + str(index), "PouchSystemActor",
                               "EventTriggerAddOrRemovePouchContent",
                               {"Actor": actor, "Num": -1, "IsEquipDIrect": False,
                                "IsSetMessageTargetActorName": False, "IsGetEvent": False})
        link(remove, root)
        owned = editor.switch(stem + "_Owned" + str(index), "PouchSystemActor", "EventQueryIsExistInPouch",
                              {"Actor": actor, "Num": 1}, remove, root)
        root = editor.switch(stem + "_Spent" + str(index), "GameDataActor", "EventQueryIsGameDataBool",
                             {"GameDataName": record["flag_name"], "Index": -1}, owned, root)
    return _after_writes(editor, stem + "_Ready", root)


def patch_native_grant(raw):
    """Apply reconciliation to the source copied by receipts, chests and shops."""
    from evfl.event import ActionEvent
    from evfl.util import make_index
    from oot_rando.patching.progressive import FlowEditor

    editor = FlowEditor(raw, "Native adult trade stock reconciliation")
    if any(event.name.startswith(PREFIX) for event in editor.chart.events):
        raise ValueError(tr("Adult trade inventory is already prepared."))
    grants = [event for event in editor.chart.events if isinstance(event.data, ActionEvent)
              and str(event.data.actor.v.identifier) == "PouchSystemActor"
              and event.data.actor_action.v.v == "EventTriggerAddOrRemovePouchContent"]
    grant = next((event for event in grants if event.name == "Event0"), None)
    if grant is None or grant.data.params is None or grant.data.params.data.get("Num") != 1:
        raise ValueError(tr("The native pouch grant does not match this game version."))
    grant.data.nxt = make_index(append_reconcile(editor, PREFIX, grant.data.nxt.v))
    return editor.write("Adult trade inventory reconciliation")[0]


def prepare_trade_state(romfs, mod, data):
    """Add saved check flags and native stock cleanup before receipt cloning."""
    if not data.get("adult_trade_shuffle"):
        return {}
    from oot_rando.game.resource_allocations import grow_resources
    from oot_rando.patching.soul_adapter import murmur3
    romfs, mod = Path(romfs), Path(mod)
    codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
    def source(path):
        current = mod / path
        return (current if current.is_file() else romfs / path).read_bytes()
    frames = {path: source(path) for path in (FLOW_PATH, GAME_DATA, REST)}
    old = {path: codec.decode(frame) for path, frame in frames.items()}
    state = old[GAME_DATA]
    for record in TRADE_CHECKS.values():
        assert murmur3(record["flag_name"]) == record["flag"]
        state = append_saved_bool(state, record["flag"])
    changed = {FLOW_PATH: patch_native_grant(old[FLOW_PATH]), GAME_DATA: state}
    table, allocations = grow_resources(old[REST], {path: max(0, len(raw)-len(old[path]))
                                                   for path, raw in changed.items()})
    changed[REST] = table
    for path, raw in changed.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(codec.encode(raw, frames[path]))
    return dict(locations=len(TRADE_CHECKS), allocations=allocations)
