"""Connect selected native rewards to location-bound Archipelago callbacks.

Preparation operates on a staged mod. The native generator remains responsible
for access, story state, cutscenes, and which rewards are shuffled.
"""
import json
from pathlib import Path

from .catalog import ITEM_DATA, ITEM_IDS
from .network_catalog import SOURCES, callback_sources, flag_name, source_flags


def source_records(roster, settings):
    from oot_rando.patching import ap_item
    records = []
    for name, metadata in callback_sources(roster, settings).items():
        reward = roster[name]
        if not isinstance(reward, dict) or type(reward.get("local")) is not bool:
            raise ValueError("The room did not supply a complete native reward mapping: " + name)
        item, player = reward["item"], reward["player"]
        actor = ap_item.ap_actor(ap_item.ap_item(json.dumps([name, item, player], ensure_ascii=False)))
        variants = metadata["variants"]
        record = dict(name=name, actor=actor, pickup="Obj_" + actor[5:] + "_GH",
                      flag_name=flag_name(name), flag_hash=source_flags(name)[0],
                      hash=variants[0]["actor"] if variants else "flow:" + name,
                      files=sorted({row["file"] for row in variants}),
                      network_source=1, metadata=SOURCES[name], display_actor=actor)
        if "generated_item" in metadata:
            record["generated_item"] = metadata["generated_item"]
        if reward["local"]:
            if item not in ITEM_DATA or reward.get("item_id") != ITEM_IDS[item]:
                raise ValueError("Unknown local Archipelago reward: " + str(item))
            record.update(local_item=item, native_actor=ITEM_DATA[item]["actor"])
            record["display_actor"] = ITEM_DATA[item]["actor"]
            if (ITEM_DATA[item].get("bottle_item")
                    and ITEM_DATA[item].get("pouch_special") == "NotPushToPouch"):
                raise ValueError("This reward cannot require an empty bottle: " + name)
        records.append(record)
    return records


def validate_record(record):
    """Accept generic callbacks only for a packaged, immutable source identity."""
    name = record.get("name")
    metadata = SOURCES.get(name)
    if metadata is None or record.get("network_source") != 1 or record.get("metadata") != metadata:
        raise ValueError("Invalid native network reward metadata.")
    variants = metadata["variants"]
    if (record.get("flag_name") != flag_name(name) or record.get("flag_hash") != source_flags(name)[0]
            or record.get("hash") != (variants[0]["actor"] if variants else "flow:" + name)
            or record.get("files") != sorted({row["file"] for row in variants})):
        raise ValueError("Invalid native network reward identity: " + str(name))
    return metadata


def prepare_network_rewards(romfs, mod, roster, settings):
    """Replace effective sources, then attach the native get-event dispatcher."""
    from .engine import run_engine
    from .ap_skulls import prepare_pickup_callbacks
    records = source_records(roster, settings)
    if not records:
        return {}
    physical = [record for record in records if record["metadata"]["kind"] in {"pickup", "container", "skull"}]
    if physical:
        print(run_engine("sources", {"sources": physical}, Path(romfs), Path(mod)).strip(), flush=True)
        from .network_containers import prepare_network_containers, prepare_network_presence
        prepare_network_containers(romfs, mod, physical)
        prepare_network_presence(romfs, mod, physical)
    callbacks = prepare_pickup_callbacks(romfs, mod, records)
    from .network_flows import prepare_flow_rewards
    prepare_flow_rewards(romfs, mod, records, settings, callbacks["effects"])
    return callbacks
