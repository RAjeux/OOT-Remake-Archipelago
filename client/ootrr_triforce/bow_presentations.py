"""Upgrade compatible Bow-family receipts to isolated display-only models.

Real Bow/quiver actors continue to drive ownership, text, pose queries and the
single inventory effect. Only the shown model and its typed forwarding argument
change. This also upgrades late adult-trade/pedestal presenters in old caches.
"""
from pathlib import Path
import re

FAMILY = ("Item_Range_Bow", "Item_Quiver_Medium", "Item_Quiver_Large")


def _bindings(chart):
    from evfl.event import SubFlowEvent
    from .catalog import ITEM_IDS, TRADE_CHECKS
    from .master_sword import LOCATION_ID
    from .native_presentations import PRESENTER_ENTRY, PRESENTER_NAME
    from .presentation_models import SHOW_ACTOR_ARGUMENT, model_actor

    rows = []
    trade_ids = {row["id"] for row in TRADE_CHECKS.values()}
    for node in chart.events:
        data = node.data
        if (not isinstance(data, SubFlowEvent) or data.res_flowchart_name != PRESENTER_NAME
                or data.params is None or type(data.params.data.get("ActorName")) is not str
                or data.params.data["ActorName"] not in FAMILY):
            continue
        if not node.name.startswith("OOTRR_AP"):
            continue
        receipt = re.fullmatch(r"OOTRR_APReceive_(\d+)_Tier([0-2])_Show", node.name)
        trade = re.fullmatch(r"OOTRR_APTradeReward_(\d+)_Present_Tier([0-2])_Show", node.name)
        master = re.fullmatch(r"OOTRR_APMaster_Reward_(\d+)_Present_Tier([0-2])_Show", node.name)
        match = receipt or trade or master
        if receipt and int(receipt[1]) == ITEM_IDS["Bow"]:
            prefix, core = "OOTRR_APShow_" + receipt[1], "OOTRR_APReceive_" + receipt[1]
        elif trade and int(trade[1]) in trade_ids:
            prefix, core = "OOTRR_APTradeShow_" + trade[1], "OOTRR_APTradeReward_" + trade[1]
        elif master and int(master[1]) == LOCATION_ID:
            prefix, core = "OOTRR_APMaster_Show_" + master[1], "OOTRR_APMaster_Reward_" + master[1]
        else:
            raise ValueError("Bow model upgrade has an unknown AP caller.")
        actor = data.params.data["ActorName"]
        if actor != FAMILY[int(match[2])] or data.params.data.get("IsNpcEventStarter") is not False:
            raise ValueError("Bow model upgrade has a crossed progressive tier.")
        entry = prefix + "_" + PRESENTER_ENTRY
        if data.entry_point_name != entry:
            raise ValueError("Bow model upgrade has an unknown native presenter.")
        expected = {"ActorName": actor, "IsNpcEventStarter": False}
        modern = SHOW_ACTOR_ARGUMENT in data.params.data
        if modern:
            expected[SHOW_ACTOR_ARGUMENT] = model_actor(actor)
        if data.params.data != expected or (modern and type(data.params.data[SHOW_ACTOR_ARGUMENT]) is not str):
            raise ValueError("Bow model upgrade has an incompatible model argument.")
        rows.append(dict(node=node, actor=actor, prefix=prefix, entry=entry, core=core + "_Pouch", modern=modern))
    return rows


def patch_bow_presentations(pouch_raw, presenter_raw):
    """Upgrade an exact old family or retain an exact current family unchanged."""
    from evfl.common import Argument
    from evfl.container import Container
    from evfl.event import ActionEvent, SubFlowEvent, SubFlowSwitchEvent
    from oot_rando.patching.progressive import FlowEditor
    from .held_framing import _closure
    from .native_presentations import PRESENTER_NAME
    from .presentation_models import SHOW_ACTOR_ARGUMENT, model_actor

    pouch = FlowEditor(pouch_raw, "AP Bow model identities")
    bindings = _bindings(pouch.chart)
    if not bindings:
        return pouch_raw, presenter_raw, []
    presenter = FlowEditor(presenter_raw, "Native Bow display models")
    if pouch.chart.name != "GetPouchContent" or presenter.chart.name != PRESENTER_NAME:
        raise ValueError("Bow model upgrade has an unexpected native flowchart.")
    core_names = [point.name for point in pouch.chart.entry_points]
    groups = {}
    for binding in bindings:
        groups.setdefault(binding["entry"], []).append(binding)
    plans = []
    for entry, rows in groups.items():
        first = rows[0]
        if (len(rows) != 3 or {row["actor"] for row in rows} != set(FAMILY)
                or len({row["modern"] for row in rows}) != 1
                or core_names.count(first["core"]) != 1):
            raise ValueError("Bow model upgrade has an incomplete progressive family.")
        modern = first["modern"]
        reached = _closure(presenter.chart, entry, first["prefix"])
        callbacks = [node for node in reached if isinstance(node.data, SubFlowEvent)
                     and node.data.res_flowchart_name == "GetPouchContent"
                     and node.data.entry_point_name == first["core"]]
        if (len(callbacks) != 1 or callbacks[0].data.params is None
                or not isinstance(callbacks[0].data.params.data.get("ActorName"), Argument)
                or str(callbacks[0].data.params.data["ActorName"]) != "ActorName"):
            raise ValueError("Bow model upgrade has an unknown real-item grant callback.")
        creates, forwards = [], []
        for node in presenter.chart.events:
            if not node.name.startswith(first["prefix"] + "_"):
                continue
            data = node.data
            params = data.params.data if getattr(data, "params", None) is not None else {}
            if isinstance(data, ActionEvent) and data.actor_action.v.v == "EventCreateShowItemFromActorFileName":
                expected = SHOW_ACTOR_ARGUMENT if modern else "ActorName"
                if (str(data.actor.v.identifier) != "Player_Event"
                        or not isinstance(params.get("Actor"), Argument) or str(params["Actor"]) != expected):
                    raise ValueError("Bow model upgrade has an incompatible shown actor binding.")
                creates.append(node)
            elif isinstance(data, (SubFlowEvent, SubFlowSwitchEvent)) and not data.res_flowchart_name:
                if not data.entry_point_name.startswith(first["prefix"] + "_"):
                    raise ValueError("Bow model upgrade crosses an unknown local presenter.")
                value = params.get(SHOW_ACTOR_ARGUMENT)
                if ((modern and (not isinstance(value, Argument) or str(value) != SHOW_ACTOR_ARGUMENT))
                        or (not modern and SHOW_ACTOR_ARGUMENT in params)):
                    raise ValueError("Bow model upgrade has an incompatible forwarded model argument.")
                forwards.append(node)
        if len(creates) != 1 or creates[0] not in reached:
            raise ValueError("Bow model upgrade has an ambiguous native shown model.")
        if not modern:
            plans.append(dict(rows=rows, creates=creates, forwards=forwards))
    if not plans:
        return pouch_raw, presenter_raw, []
    changes = []
    for plan in plans:
        for row in plan["rows"]:
            node = row["node"]
            node.data.params.data[SHOW_ACTOR_ARGUMENT] = model_actor(row["actor"])
            pouch.expected[node.name] = dict(node.data.params.data)
        for node in plan["creates"]:
            node.data.params.data["Actor"] = Argument(SHOW_ACTOR_ARGUMENT)
            presenter.expected[node.name] = dict(node.data.params.data)
        for node in plan["forwards"]:
            if node.data.params is None:
                node.data.params = Container()
            node.data.params.data[SHOW_ACTOR_ARGUMENT] = Argument(SHOW_ACTOR_ARGUMENT)
            presenter.expected[node.name] = dict(node.data.params.data)
        changes.append(dict(entry=plan["rows"][0]["entry"], actors=list(FAMILY),
                            callers=[row["node"].name for row in plan["rows"]]))
    return pouch.write("AP Bow model arguments")[0], presenter.write("Native Bow shown models")[0], changes


def prepare_bow_presentations(romfs, mod):
    """Migrate old staged receipts before their display-offset pass."""
    from oot_rando.game.resource_allocations import grow_resources
    from oot_rando.patching.progressive import FlowEditor
    from .mod_codec import Codec
    from .native_presentations import PRESENTER_PATH
    from .presentation_models import prepare_presentation_models
    from .receipt_events import FLOW_PATH, REST
    romfs, mod = Path(romfs), Path(mod)
    if not (mod / FLOW_PATH).is_file():
        return {"presenters": 0, "written": 0}
    codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
    def frame(path):
        target = mod / path
        return (target if target.is_file() else romfs / path).read_bytes()
    pouch_frame = frame(FLOW_PATH)
    pouch_raw = codec.decode(pouch_frame)
    if not _bindings(FlowEditor(pouch_raw, "Bow model bindings").chart):
        return {"presenters": 0, "written": 0}
    presenter_frame = frame(PRESENTER_PATH)
    before = codec.decode(presenter_frame)
    pouch, presenter, changes = patch_bow_presentations(pouch_raw, before)
    if not changes:
        return {"presenters": 0, "written": 0}
    # Every old caller and its typed native presenter was validated first.
    # The new visual actors must exist before publishing their arguments.
    prepare_presentation_models(romfs, mod)
    rest_frame = frame(REST)
    rest, _ = grow_resources(codec.decode(rest_frame), {FLOW_PATH: max(0, len(pouch) - len(pouch_raw)),
                                                       PRESENTER_PATH: max(0, len(presenter) - len(before))})
    encoded = {FLOW_PATH: codec.encode(pouch, pouch_frame), PRESENTER_PATH: codec.encode(presenter, presenter_frame),
               REST: codec.encode(rest, rest_frame)}
    for path, content in encoded.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return {"presenters": len(changes), "written": len(encoded)}
