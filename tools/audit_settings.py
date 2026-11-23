"""Compare the AP catalogue with OOTRR's versioned native settings schema.

The fixture was exported by OOTRR 0.8.1's settings-dump command. Use --ootrr to
compare a locally installed executable instead. This audit does not enable any
setting or establish gameplay compatibility merely because a key exists.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.settings import AP_ONLY, BRIDGE_OPEN_ALIAS, ENGINE_EXTENSIONS, FIXED_SETTINGS, SPEC_BY_ID

SCHEMA = ROOT / "tests/fixtures/ootrr-settings-schema.json"
LOCAL_SHUFFLES = frozenset({
    "shuffle_pots", "shuffle_crates", "shuffle_rocks", "shuffle_grass",
    "shuffle_beehives", "shuffle_freestanding_items", "shuffle_rewards",
    "shuffle_rewards_extra", "shuffle_boss_hearts", "shuffle_songs",
    "shuffle_trade_checks", "shuffle_scrubs_a", "shuffle_scrubs_b", "shuffle_cows",
    "shuffle_frog_songs", "shuffle_frog_bug_heart", "shuffle_potion_shop",
    "shuffle_treasure_reward", "shuffle_dungeon_rewards", "shuffle_ocarinas",
    "shuffle_kokiri_sword", "shuffle_merchants", "shuffle_entrances",
})
NETWORK_SHUFFLES = frozenset({"shuffle_chests", "shuffle_shops", "shuffle_skulltulas"})
SPECIAL = {
    "shuffle_trade_checks": ("legacy_additive_replaced", "This portable OOTRR setting adds a bonus while retaining vanilla quest items. New AP rooms use the integration's adult_trade_shuffle extension for complete replacement; old generated rooms retain their additive behavior."),
    "open_door_of_time": ("legacy_alias", "The legacy boolean is superseded by door_of_time_condition and its related controls."),
    "shuffle_scrubs": ("native_rejected", "The native planner accepts only off for this old selector; shuffle_scrubs_a and shuffle_scrubs_b implement the available subsets."),
    "shuffle_hideoutkeys": ("native_rejected", "The native planner accepts only vanilla; roaming hideout-key placement is not implemented."),
    "shuffle_cows_other": ("derived_alias", "The native reward plan derives cows_other from shuffle_cows and does not read this independent flag."),
    "shuffle_silver_rupees": ("delivery_missing", "The native shuffle introduces dungeon-specific Silver Rupee items which have no AP item IDs or native AP receipt recipes."),
    "disabled_locations": ("placement_adapter_missing", "Native disabled locations receive junk rather than disappearing. AP refill would have to preserve that constraint, including its filler pool and counted access rules."),
    "gossip_hints": ("ap_mapping_missing", "Native hints describe OOTRR's pre-AP placements. They need the final AP item and owner mapping to avoid misleading hints."),
    "misc_hints": ("ap_mapping_missing", "Character hints may reference locations whose items AP moves later. An AP-aware hint pass is required."),
    "chests_match_contents": ("ap_mapping_missing", "Native chest size is selected before AP replaces chest contents. Sizes must be recalculated from the final AP reward."),
    "bombchus_in_logic": ("known_native_gameplay_gap", "The native source documents Bombchus being unusable without a Bomb Bag even though this option's logic assumes they work. A logic-only toggle can therefore produce an unusable required explosive."),
}
DESTRUCTIBLE_SHUFFLES = frozenset({"shuffle_pots", "shuffle_crates", "shuffle_rocks", "shuffle_grass", "shuffle_beehives"})
PARTIAL_REASONS = {
    "shuffle_smallkeys": "The native dungeon-item planner implements only vanilla, dungeon, any_dungeon and keysanity for Small Keys.",
    "shuffle_mapcompass": "The native dungeon-item planner rejects Overworld-only Maps/Compasses; its other supported placement modes remain available.",
    "shuffle_ganon_bosskey": "The native planner supports the regular key-placement modes and lacs_dungeons, but not the other schema-advertised reward triggers.",
    "bridge": "The native bridge code implements Vanilla and the combined dungeon-reward threshold. AP's open choice maps to that threshold at zero rewards; the remaining schema goal variants are not implemented.",
    "zora_fountain": "The native world-opening code implements Closed and Open, not the advertised child-only blockage variant.",
    "starting_items": "Zelda's Letter cannot be granted as an isolated starting pouch item; the supported open Kakariko story state grants it together with the corresponding quest progress.",
    "shuffle_entrances": "Only dungeon entrance pairing is implemented. Native overworld/everything modes are explicitly rejected because age/return/story transition handling is incomplete.",
}


def load_schema(ootrr=None):
    if ootrr:
        result = subprocess.run([str(ootrr), "settings-dump", "--compact"],
                                capture_output=True, check=True)
        return json.loads(result.stdout)
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def public_errors(schema):
    """Reject misspelled keys, unsupported choices and ranges outside native bounds."""
    native = {row["id"]: row for row in schema["settings"]}
    errors = []
    for key, public in SPEC_BY_ID.items():
        if key in AP_ONLY:
            continue
        if key in ENGINE_EXTENSIONS and key not in native:
            extension = ENGINE_EXTENSIONS[key]
            if any(public[field] != extension[field] for field in ("kind", "default")):
                errors.append(f"Invalid integration extension contract: {key}")
            continue
        row = native.get(key)
        if row is None:
            errors.append(f"Unknown native key: {key}")
            continue
        if row.get("unsupported"):
            errors.append(f"Native planner marks this key unsupported: {key}")
        kinds = {"toggle": "toggle", "choice": "choice", "number": "range", "multi": "set", "list": "set"}
        if kinds.get(row["kind"]) != public["kind"]:
            errors.append(f"Public and native value kinds differ: {key}")
        choices = {choice["id"] for choice in row.get("choices", [])}
        if public["kind"] in {"choice", "set"} and choices:
            unknown = set(public["choices"]) - choices
            if unknown:
                errors.append(f"Unknown native choices for {key}: {', '.join(sorted(unknown))}")
        if public["kind"] == "range":
            if public["min"] < row["min"] or public["max"] > row["max"]:
                errors.append(f"Range outside native bounds: {key}")
            native_step = row.get("step", 1)
            if public.get("step", 1) % native_step:
                errors.append(f"Range step incompatible with native menu: {key}")
    return errors


def report(schema):
    rows = []
    for native in schema["settings"]:
        key = native["id"]
        public = SPEC_BY_ID.get(key)
        row = {"id": key, "label": native["label"], "native_kind": native["kind"],
               "native_default": native["default"], "native_dependencies": native.get("deps", [])}
        if native.get("choices"):
            row["native_choices"] = [choice["id"] for choice in native["choices"]]
        for name in ("min", "max", "step"):
            if name in native:
                row["native_" + name] = native[name]
        if public is not None:
            row.update(ap_default=public["default"], ap_kind=public["kind"])
            if key == "bridge":
                row["integration_choice_aliases"] = {"open": dict(BRIDGE_OPEN_ALIAS)}
            if public.get("choices"):
                row["ap_choices"] = list(public["choices"])
                row["omitted_native_choices"] = sorted(set(row.get("native_choices", [])) - set(public["choices"]))
                if row["omitted_native_choices"]:
                    row["omitted_native_reason"] = PARTIAL_REASONS.get(key, "The AP catalogue retains the implemented, supported subset of the broader native schema.")
            for name in ("min", "max", "step"):
                if name in public:
                    row["ap_" + name] = public[name]
            if key in LOCAL_SHUFFLES:
                status = "public_native_local"
                reason = "OOTRR keeps these non-catalogued rewards local; AP moves only its separately catalogued locations. The native search settles local rewards before each counted AP sphere."
                if key == "shuffle_trade_checks":
                    reason += " This adds a first-time bonus to each supported adult trade hand-in; the normal quest item is also given. Full replacement/shuffling of adult trade items is not implemented."
            elif key in NETWORK_SHUFFLES:
                status = "public_network"
                reason = "The supported AP location family is connected to native checks and rewards; see the setting description for its exact scope."
            else:
                status = "public"
                reason = "The AP catalogue forwards this supported native control. Dependent options remain subject to catalogue validation."
        elif native.get("unsupported"):
            status = "native_unavailable"
            reason = "OOTRR's native planner accepts only the default; the schema marks alternate values unsupported."
        elif key in SPECIAL:
            status, reason = SPECIAL[key]
        else:
            status = "not_exposed"
            reason = "Implemented by the native schema but absent from the AP catalogue; review its dependencies, staging and reward coverage before enabling it."
        row.update(status=status, reason=reason)
        if key in DESTRUCTIBLE_SHUFFLES:
            row["native_caution"] = "These experimental native drops persist when their container is broken. Leaving before collecting a required drop can lose it; save before breaking containers."
        if key in FIXED_SETTINGS:
            row["ap_fixed_value"] = FIXED_SETTINGS[key]
        rows.append(row)
    counts = Counter(row["status"] for row in rows)
    placeholders = schema.get("menu_placeholders")
    if placeholders is None:
        placeholders = [{"page": page["id"], "section": section["label"], "label": item["stub"]}
                        for page in schema.get("menu", []) for section in page["sections"]
                        for item in section.get("items", []) if "stub" in item]
    return {"basis": "OOTRR 0.8.1 native schema and the current AP settings catalogue",
            "native_setting_count": len(rows), "public_native_count": sum(row["id"] in SPEC_BY_ID for row in rows),
            "ap_only": sorted(AP_ONLY), "engine_extensions": ENGINE_EXTENSIONS,
            "status_counts": dict(sorted(counts.items())),
            "menu_placeholders": placeholders, "settings": rows, "errors": public_errors(schema)}


def markdown(result):
    lines = ["# Settings compatibility", "",
             "This comparison uses the **OOTRR remake 0.8.1** schema vendored by this project. It does not claim parity with every setting of the separate N64 OoT Randomizer or Ship of Harkinian. The remake's menu also contains placeholder controls which its own engine cannot apply.", "",
             f"The native schema has **{result['native_setting_count']} keys**. The current AP catalogue exposes **{result['public_native_count']} native keys**, the integration extension {', '.join('`' + key + '`' for key in result['engine_extensions'])}, and {', '.join('`' + key + '`' for key in result['ap_only'])}. Some native choice lists are deliberately restricted to implemented values.", "",
             "Archipelago rolls each Random? control independently. Before generation, unused sub-options are reset to their native defaults: for example, `scrub_price_fixed` is ignored unless enabled Scrub sales use `scrub_prices: fixed`. The same rule applies to inactive shop prices, merchant prices, goal counts and song colors. Active prices, goals and progression settings are preserved. Invalid combinations of active settings still report an error; choosing Random? for every option does not guarantee a valid combination.", "",
             "A local shuffle can be compatible with AP without turning all of its locations into network checks: OOTRR builds the complete canonical seed, then the AP pass changes only catalogued locations. The native search collects reachable local rewards before recording each AP sphere. Requiring every earlier AP reward preserves that conservative reachability proof. Local pickups and NPC rewards must remain present and must not receive an additional AP grant.", "",
             "Settings which depend on the *final placement* need extra care. Native hint text, chest sizing and junk-only exclusions cannot simply be copied before AP replaces a reward. Silver Rupee shuffling also adds new item types that need AP IDs and receipt effects.", "",
             "The `adult_trade_shuffle` integration extension replaces the legacy additive trade control. It shuffles ten quest items and exports eleven trade checks, with independent inventory guards and native item delivery. It is implemented by this project's engine and client rather than the unmodified portable OOTRR 0.8.1 application. See [adult trade rewards](ADULT-TRADE-REWARDS.md). For local versus remote item ownership and the scope of the network pool, see [multiworld distribution](MULTIWORLD-DISTRIBUTION.md).", "",
             "The machine-readable companion is [settings-compatibility.json](settings-compatibility.json). Regenerate both files with `python tools/audit_settings.py --write-docs`; use `--ootrr <ootrr.exe>` to audit another installed native schema. These comparisons validate catalogue coverage, not gameplay for every combination.", "",
             "| Native key | AP status | Details |", "| --- | --- | --- |"]
    for row in result["settings"]:
        detail = row["reason"]
        if row.get("omitted_native_choices"):
            detail += " Omitted native choices: " + ", ".join("`" + value + "`" for value in row["omitted_native_choices"]) + "."
            detail += " " + row["omitted_native_reason"]
        if row.get("native_caution"):
            detail += " " + row["native_caution"]
        if row.get("integration_choice_aliases"):
            detail += " The integration's `open` choice uses `bridge: dungeons` with `bridge_rewards: 0`; the bridge opens on approach without requiring dungeon rewards."
        lines.append(f"| `{row['id']}` | `{row['status']}` | {detail} |")
    lines += ["", "## Native menu placeholders", "",
              "These controls appear as unavailable placeholders in OOTRR itself; listing them in a YAML would not add their engine implementation.", ""]
    lines.extend(f"- {row['label']} ({row['page']} / {row['section']})." for row in result["menu_placeholders"])
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ootrr", type=Path, help="Compare a local OOTRR executable instead of the captured 0.8.1 schema.")
    parser.add_argument("--write-docs", action="store_true", help="Regenerate the public comparison documents.")
    args = parser.parse_args()
    result = report(load_schema(args.ootrr))
    if args.write_docs:
        (ROOT / "docs/settings-compatibility.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        (ROOT / "docs/SETTINGS-COMPATIBILITY.md").write_text(markdown(result), encoding="utf-8", newline="\n")
    print(json.dumps({key: result[key] for key in ("native_setting_count", "public_native_count", "ap_only", "status_counts", "errors")}))
    raise SystemExit(bool(result["errors"]))


if __name__ == "__main__":
    main()
