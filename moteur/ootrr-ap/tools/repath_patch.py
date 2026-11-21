import re
import sys

GAME = ["bfevfl", "bfres", "byml", "catalog", "catalog_json", "chest_slot", "dungeon_text", "entrance_swap", "entrances", "error", "flags", "flags_build", "flags_gen", "flags_harvest", "flags_keyed", "flags_map", "flags_names", "flags_rel", "flags_scan", "ips", "items", "json", "modpack", "msbt", "murmur", "placement", "rng", "romfs", "rsizetable", "sarc", "save", "tex", "zs"]
LOGIC = ["fill", "logic_demo", "logic_items", "logic_json", "logic_synth", "logic_val", "rule_ast", "rules", "search", "spoiler", "tier_chain", "world"]
COSMETICS = ["colors", "cosmetic", "sfx", "slink"]


def crate_of(module: str) -> str:
    if module in GAME:
        return "randomizer/game"
    if module in LOGIC:
        return "randomizer/logic"
    if module in COSMETICS:
        return "randomizer/cosmetics"
    return "randomizer/core"


def move(path: str) -> str:
    m = re.match(r"crates/core/src/tracker(/.*)$", path)
    if m:
        return "web/src/tracker" + m.group(1)
    if path == "crates/core/src/tracker.rs":
        return path
    m = re.match(r"crates/core/src/([a-z0-9_]+)((?:/.*|\.rs))$", path)
    if m:
        return f"{crate_of(m.group(1))}/src/{m.group(1)}{m.group(2)}"
    if path.startswith("crates/cli/"):
        return "randomizer/cli/" + path[len("crates/cli/"):]
    if path.startswith("crates/web/"):
        return "web/" + path[len("crates/web/"):]
    return path


def main() -> None:
    src, dst = sys.argv[1], sys.argv[2]
    data = open(src, "rb").read().decode("utf-8")
    out = re.sub(r"(?<=[ab]/)crates/[^\s]+|(?<=^--- a/)crates/[^\s]+|(?<=^\+\+\+ b/)crates/[^\s]+", lambda m: move(m.group(0)), data, flags=re.M)
    open(dst, "wb").write(out.encode("utf-8"))
    if "data/logic/World/Overworld.json" in out:
        print("this patch edits data/logic/World/Overworld.json, which is now split by area in data/logic/World/Overworld. Apply those hunks by hand.")


main()
