"""Import reviewed physical sources absent from the released AP catalogue."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.catalog import CHESTS, ITEM_DATA, LOCATION_IDS
from ootrr_triforce.network_catalog import LEGACY_SOURCES, ADDITIONAL_SOURCES


def main(source):
    import subprocess
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if revision != "4fa6e5a6da839b4766bcedafb718c241a25bdd77":
        raise ValueError("Use the reviewed upstream revision.")
    old_names = json.loads((ROOT / "moteur/ootrr-ap/data/ap_logic_v2/provenance.json").read_text())["canonical_aliases"]
    known = {v["actor"] for row in LEGACY_SOURCES.values() for v in row.get("variants", [])}
    known.update(ref["actor"] for name, refs in CHESTS.items() if name not in ADDITIONAL_SOURCES for ref in refs)
    source_rows = json.loads((source / "data/locations.json").read_text(encoding="utf-8"))["locations"]
    sources, rewards = {}, {}
    groups = {"Fire Temple": "fire", "Water Temple": "water", "Forest Temple": "forest",
              "Spirit Temple": "spirit", "Gerudo Training Ground": "gerudo", "Ganon's Castle": "castle",
              "Lake Hylia": "lake"}
    # Real-resource audit verified these chests' effective native grants. Their
    # historical N64 labels describe a different item, so do not copy that pool.
    effective = {"Fire Temple Boulder Maze Side Room Chest": "Compass (Fire Temple)",
                 "Fire Temple Compass Chest": "Small Key (Fire Temple)",
                 "Forest Temple Falling Ceiling Room Chest": "Bombs (5)",
                 "Gerudo Training Ground Lobby Left Chest": "Rupees (5)"}
    for row in source_rows:
        if row["kind"] not in {"chest", "freestanding"} or not row.get("refs"):
            continue
        if any(ref["hash"] in known for ref in row["refs"]):
            continue
        name = old_names.get(row["name"], row["name"])
        if name in LOCATION_IDS and name not in ADDITIONAL_SOURCES:
            raise ValueError("A new physical identity collides with a released name: " + name)
        frozen = row["item"] == "Obj_TBox_A_04"
        reward = effective.get(row["name"], "Rupees (5)" if frozen else row["vanilla"])
        if reward not in ITEM_DATA:
            raise ValueError("No native AP recipe for " + reward)
        descriptor = dict(name=name, kind="chest" if row["kind"] == "chest" else "pickup",
                          native_kind=row["kind"], area=row["area"],
                          variants=[dict(file=file, actor=ref["hash"], via=row["via"], expected_actor=row["item"])
                                    for ref in row["refs"] for file in ref["files"]],
                          flow_edits=[], collection="chest_reward" if row["kind"] == "chest" else "pickup",
                          placement=dict(dungeon=row["area"].replace("Ganon's Castle", "Ganons Castle")
                                         if row["area"] != "Lake Hylia" else None,
                                         region_group=groups[row["area"]], junk_only=False),
                          native_route="frozen_chest" if frozen else "additional_native_source")
        sources[name] = descriptor
        rewards[name] = reward
    if len(sources) != 17:
        raise ValueError(f"Reviewed source set changed ({len(sources)} instead of 17).")
    document = dict(schema=2, revision=revision, sources=dict(sorted(sources.items())), rewards=dict(sorted(rewards.items())))
    path = ROOT / "client/ootrr_triforce/additional_sources.json"
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    registry_path = ROOT / "client/ootrr_triforce/network_ids.json"
    registry = json.loads(registry_path.read_text())
    next_id = max(LOCATION_IDS.values()) + 1
    for name in sorted(sources):
        if name not in registry["locations"]:
            registry["locations"][name] = next_id
            next_id += 1
    registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"Added {len(sources)} reviewed sources with appended IDs.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    main(parser.parse_args().source.resolve())
