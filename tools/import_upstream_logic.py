"""Import the pinned remake rules while retaining published AP location names.

This is a maintainer operation. It reads an upstream source checkout and writes
only the versioned rule bundle, never the legacy catalogue or player data.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REVISION = "4fa6e5a6da839b4766bcedafb718c241a25bdd77"
DEST = ROOT / "moteur/ootrr-ap/data/ap_logic_v2"


def import_rules(source):
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if revision != REVISION:
        raise ValueError("Use the reviewed upstream revision " + REVISION)
    old = json.loads((ROOT / "moteur/ootrr-ap/data/locations.json").read_text(encoding="utf-8"))
    new = json.loads((source / "data/locations.json").read_text(encoding="utf-8"))
    physical = {}
    for row in old["locations"]:
        for reference in row.get("refs", []):
            physical.setdefault(reference["hash"], set()).add(row["name"])
    aliases = {}
    for row in new["locations"]:
        names = set().union(*(physical.get(ref["hash"], set()) for ref in row.get("refs", [])))
        if len(names) == 1 and row["name"] != next(iter(names)):
            aliases[row["name"]] = next(iter(names))
    old_shops = json.loads((ROOT / "moteur/ootrr-ap/data/shops.json").read_text(encoding="utf-8"))
    new_shops = json.loads((source / "data/shops.json").read_text(encoding="utf-8"))
    shelves = {(row["shop"], row["slot"]): row["name"] for row in old_shops["slots"]}
    for row in new_shops["slots"]:
        old_name = shelves[(row["shop"], row["slot"])]
        if row["name"] != old_name:
            aliases[row["name"]] = old_name
    # One substitution pass is essential: several upstream fixes swap two names.
    matcher = re.compile("|".join(re.escape(k) for k in sorted(aliases, key=len, reverse=True)))

    def convert(value):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                key = aliases.get(key, key)
                if key in result:
                    raise ValueError("Aliased rule keys collide: " + key)
                result[key] = convert(item)
            return result
        if isinstance(value, list):
            return [convert(v) for v in value]
        if isinstance(value, str):
            return matcher.sub(lambda m: aliases[m.group()], value)
        return value

    files = [source / "data/logic/LogicHelpers.json", *sorted((source / "data/logic/World").rglob("*.json"))]
    for path in files:
        # OOTRR logic JSON permits line comments. Preserve them and transform
        # quoted names without making its parser stricter than the upstream one.
        relative = path.relative_to(source / "data/logic")
        text = path.read_text(encoding="utf-8")
        text = matcher.sub(lambda m: aliases[m.group()], text)
        destination = DEST / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8", newline="\n")
    defaults = json.loads((ROOT / "moteur/ootrr-ap/data/logic/settings.json").read_text(encoding="utf-8"))
    defaults.update(json.loads((source / "data/logic/settings.json").read_text(encoding="utf-8")))
    (DEST / "settings.json").write_text(json.dumps(defaults, indent=2) + "\n", encoding="utf-8")
    includes = (ROOT / "moteur/ootrr-ap/randomizer/core/src/slice/world_files.rs").read_text(encoding="utf-8")
    includes = includes.replace("../../../../data/logic/", "../../../../data/ap_logic_v2/")
    (ROOT / "moteur/ootrr-ap/randomizer/core/src/slice/modern_world_files.rs").write_text(
        "// Pinned AP-only rule bundle. Legacy generation keeps world_files.rs.\n" + includes,
        encoding="utf-8", newline="\n")
    document = {"schema": 2, "upstream": "https://github.com/ootrando/ootrr", "revision": REVISION,
                "canonical_aliases": aliases, "files": [p.relative_to(source / "data/logic").as_posix() for p in files]}
    (DEST / "provenance.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"Imported {len(files)} logic files with {len(aliases)} identity-preserving aliases.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    import_rules(parser.parse_args().source.resolve())
