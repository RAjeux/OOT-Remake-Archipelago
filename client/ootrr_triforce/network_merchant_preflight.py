"""Check the AP bean reward's capacity without changing native repeat sales.

The bean merchant's eight price branches share SimpleShop's three-choice
conversation. Only its capacity query changes: before the one AP source is
collected it checks the unique AP actor. Afterwards it checks the original
magic-bean argument. Conversation arguments, prices and counters never change.
"""
from pathlib import Path

from .catalog import LOCATION_IDS


LOCATION = "ZR Magic Bean Salesman"
FLOW = "SimpleShop"
FLOW_PATH = "Event/EventFlow/" + FLOW + ".bfevfl.zs"
MERCHANT_PATH = "Event/EventFlow/Npc_Hylia_047_Child.bfevfl.zs"
NATIVE_ACTOR = "Item_MagicBean"
SHOP_FLOW = "SimpleShop"
SHOP_ENTRY = "SimpleShopRoot_3Choices"
NATIVE_CALLS = frozenset({"Event3", "Event33", "Event7", "Event11", "Event15", "Event35", "Event55", "Event56"})
REST = "System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs"


def patch_preflight(raw, record):
    """Retarget one capacity query; no sale or presentation arguments change."""
    from evfl.common import Argument
    from evfl.event import SwitchEvent
    from evfl.util import make_index
    from oot_rando.patching.event_info import reachable
    from oot_rando.patching.progressive import FlowEditor
    from .network_rewards import validate_record
    from .shop_events import _retarget

    if record["name"] != LOCATION:
        raise ValueError("Unsupported native merchant preflight.")
    validate_record(record)
    editor = FlowEditor(raw, FLOW_PATH)
    if editor.chart.name != FLOW:
        raise ValueError("The native SimpleShop flow is missing.")
    chart = editor.chart
    originals = list(chart.events)
    stem = "OOTRR_APMerchant_" + str(LOCATION_IDS[LOCATION]) + "_"
    found = [event for event in originals if event.name == "Event126"]
    if len(found) != 1:
        raise ValueError("The native bean merchant capacity query is missing.")
    original = found[0]
    data = original.data
    if (not isinstance(data, SwitchEvent)
            or str(data.actor.v.identifier) != "PouchSystemActor"
            or data.actor_query.v.v != "EventQueryCanAddToPorch"
            or data.params is None or data.params.data != {"Actor": Argument("ActorName")}
            or not isinstance(data.params.data["Actor"], Argument)
            or set(data.cases) != {0, 2}
            or data.cases[0].v is None or data.cases[0].v.name != "Event195"
            or data.cases[2].v is None or data.cases[2].v.name != "Event177"):
        raise ValueError("The native bean merchant capacity query differs from the supported game.")
    existing = {event.name: event for event in originals if event.name.startswith(stem)}
    if existing:
        expected = {stem + suffix for suffix in ("RewardCapacity", "Collected")}
        if set(existing) != expected:
            raise ValueError("The Archipelago merchant preflight is incomplete.")
        offer, gate = existing[stem + "RewardCapacity"], existing[stem + "Collected"]
        if (not isinstance(offer.data, SwitchEvent)
                or str(offer.data.actor.v.identifier) != "PouchSystemActor"
                or offer.data.actor_query.v.v != "EventQueryCanAddToPorch"
                or offer.data.params is None or offer.data.params.data != {"Actor": record["actor"]}
                or set(offer.data.cases) != {0, 2}
                or any(offer.data.cases[key].v is not original.data.cases[key].v for key in (0, 2))
                or not isinstance(gate.data, SwitchEvent)
                or str(gate.data.actor.v.identifier) != "GameDataActor"
                or gate.data.actor_query.v.v != "EventQueryIsGameDataBool"
                or gate.data.params is None
                or gate.data.params.data != {"GameDataName": record["flag_name"], "Index": -1}
                or set(gate.data.cases) != {0, 1}
                or gate.data.cases[0].v is not original or gate.data.cases[1].v is not offer):
            raise ValueError("The Archipelago merchant preflight differs from its room.")
        return raw, 0
    owners = {point.name for point in chart.entry_points if original in reachable(point.main_event.v)}
    if owners != {SHOP_ENTRY}:
        raise ValueError("The native bean merchant capacity query is shared with another shop.")
    capacity = SwitchEvent()
    capacity.actor, capacity.actor_query = data.actor, data.actor_query
    capacity.cases = dict(data.cases)
    offer = editor._event(stem + "RewardCapacity", capacity, {"Actor": record["actor"]})
    gate = editor.switch(stem + "Collected", "GameDataActor", "EventQueryIsGameDataBool",
                         {"GameDataName": record["flag_name"], "Index": -1}, original, offer)
    incoming = sum(_retarget(event, original, gate) for event in originals)
    for point in chart.entry_points:
        if point.main_event.v is original:
            point.main_event = make_index(gate)
            incoming += 1
    if not incoming:
        raise ValueError("The native bean merchant capacity query has no caller.")
    return editor.write("Native AP merchant capacity arguments")[0], 1


def prepare_merchant_preflight(romfs, mod, records):
    """Run inside the new schema's staged flow preparation only."""
    selected = [record for record in records if record.get("name") == LOCATION]
    if not selected:
        return {}
    if len(selected) != 1:
        raise ValueError("The room has duplicate native bean merchant rewards.")
    from oot_rando.game.resource_allocations import grow_resources
    from .mod_codec import Codec
    romfs, mod = Path(romfs), Path(mod)
    codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
    def source(path):
        staged = mod / path
        return (staged if staged.is_file() else romfs / path).read_bytes()

    # Every native caller of Root_3Choices belongs to this bean merchant. Check
    # those authored calls without editing any price, actor or dialogue value.
    from evfl.event import SubFlowEvent
    from oot_rando.patching.progressive import FlowEditor
    merchant = FlowEditor(codec.decode(source(MERCHANT_PATH)), MERCHANT_PATH).chart
    calls = [event for event in merchant.events if isinstance(event.data, SubFlowEvent)
             and event.data.res_flowchart_name == SHOP_FLOW and event.data.entry_point_name == SHOP_ENTRY]
    if ({event.name for event in calls} != NATIVE_CALLS or len(calls) != len(NATIVE_CALLS)
            or any(event.data.params is None or event.data.params.data.get("ActorName") != NATIVE_ACTOR
                   for event in calls)):
        raise ValueError("The native bean merchant's purchase arguments differ from the supported game.")
    frame = source(FLOW_PATH)
    before = codec.decode(frame)
    after, count = patch_preflight(before, selected[0])
    if not count:
        return {"merchant_preflight_calls": 0}
    table_frame = source(REST)
    table, allocations = grow_resources(codec.decode(table_frame), {FLOW_PATH: max(0, len(after) - len(before))})
    changed = {FLOW_PATH: codec.encode(after, frame), REST: codec.encode(table, table_frame)}
    for path, content in changed.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return {"merchant_preflight_calls": count, "allocations": allocations}
