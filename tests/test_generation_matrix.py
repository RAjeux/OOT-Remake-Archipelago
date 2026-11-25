"""Reproducible settings/interactions matrix for an isolated official AP host.

Without --run this only validates the matrix's typed inputs. For real AP
generation pass --run --ap-root --dependencies --output-root as in
test_network_generation.py. All writable files stay in a new build/ folder.
"""
from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.settings import default_options, validate_options
from test_network_generation import broad_values, run_case, stage_host, digest


def configurations():
    # Source families, progress gates, narrow placement pools, economy and
    # starting ownership are exercised independently before combined cases.
    return [
        ("minimal-ground", False, False, {"shuffle_chests": "off"}),
        ("ordinary-shops", False, True, {"shuffle_chests": "off", "shuffle_shops": "shuffle"}),
        ("pots-without-chests", False, False, {"shuffle_chests": "off", "shuffle_pots": "all"}),
        ("grass-and-hives", False, True, {"shuffle_chests": "off", "shuffle_grass": "all", "shuffle_beehives": True}),
        ("npc-without-chests", False, True, {"shuffle_chests": "off", "shuffle_rewards": "supported"}),
        ("overworld-only", False, True, {"shuffle_chests": "overworld", "shuffle_freestanding_items": "overworld"}),
        ("dungeon-only", False, True, {"shuffle_chests": "dungeons", "shuffle_pots": "dungeons",
                                       "shuffle_freestanding_items": "dungeons", "shuffle_smallkeys": "keysanity"}),
        ("all-skulltulas", False, True, {"shuffle_chests": "off", "shuffle_skulltulas": "matched"}),
        ("subset-skulltulas", False, False, {"shuffle_skulltulas": "pinned"}),
        ("cow-and-potion", False, True, {"shuffle_rewards": "supported", "shuffle_cows": True,
                                       "shuffle_potion_shop": True, "shuffle_rewards_extra": True}),
        ("merchants-fixed-zero", False, True, {"shuffle_rewards": "supported", "shuffle_merchants": "all",
                                              "plant_beans": True, "merchant_prices": "fixed", "merchant_price_fixed": 0}),
        ("scrubs-fixed-99", False, True, {"shuffle_rewards": "supported", "shuffle_scrubs_a": True,
                                         "shuffle_scrubs_b": True, "scrub_prices": "fixed", "scrub_price_fixed": 99,
                                         "scrub_hint_text": True}),
        ("native-cheap-prices", True, True, {"scrub_prices": "cheap", "merchant_prices": "cheap", "fairy_prices": "cheap"}),
        ("open-world", False, True, {"open_forest": "open", "open_kakariko": "open", "zora_fountain": "open",
                                    "jabu_open": True, "door_of_time_condition": "open", "bridge": "open",
                                    "skip_ganon_trials": True, "shops_always_open": True}),
        ("nine-rewards-six-trials", True, True, {"bridge": "dungeons", "bridge_rewards": 9,
                                                "trials": 6, "shuffle_ganon_bosskey": "lacs_dungeons", "lacs_rewards": 9}),
        ("three-stones-no-song", True, False, {"door_of_time_condition": "stones", "door_of_time_song": False,
                                              "bridge": "dungeons", "bridge_rewards": 3, "trials": 0}),
        ("song-only-door", False, False, {"door_of_time_condition": "song", "door_of_time_escape": "vanilla"}),
        ("dungeon-entrances", True, True, {"shuffle_entrances": "dungeons"}),
        ("restricted-items", True, True, {"shuffle_smallkeys": "any_dungeon", "shuffle_bosskeys": "regional",
                                          "shuffle_mapcompass": "regional", "shuffle_songs": "own",
                                          "shuffle_dungeon_rewards": "dungeons", "shuffle_ganon_bosskey": "lacs_dungeons",
                                          "lacs_rewards": 6}),
        ("dungeon-local-keys", True, False, {"shuffle_smallkeys": "dungeon", "shuffle_bosskeys": "dungeon",
                                            "shuffle_mapcompass": "startwith", "shuffle_ganon_bosskey": "dungeon"}),
        ("starting-upgrades", True, True, {"starting_items": ["biggest_bomb_bag", "bombchus", "biggest_quiver",
                                                              "four_bottles", "ocarina_of_time", "giant_wallet"],
                                          "starting_songs": ["sarias_song", "song_of_time"], "starting_hearts": 20}),
        ("one-heart-hard", False, False, {"starting_hearts": 1, "enemy_health": 500, "enemy_damage": 500,
                                         "enemy_speed": 200, "more_enemies": 1000}),
    ]


class GenerationMatrixSpecificationTests(unittest.TestCase):
    def test_every_scenario_is_valid_and_covers_sources_gates_and_repeated_ownership(self):
        rows = configurations()
        self.assertEqual(len({name for name, *_ in rows}), len(rows))
        for name, broad, _mixed, overrides in rows:
            with self.subTest(case=name):
                values = dict(broad_values() if broad else default_options(), **overrides)
                validate_options(values)
        self.assertTrue(any(row[3].get("shuffle_chests") == "off" for row in rows))
        self.assertTrue(any("starting_items" in row[3] for row in rows))
        self.assertTrue(any(row[3].get("shuffle_entrances") == "dungeons" for row in rows))


def campaign():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--ap-root", type=Path, required=True)
    parser.add_argument("--dependencies", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--seeds-per-case", type=int, default=1, choices=(1, 2, 3))
    args = parser.parse_args()
    output = args.output_root.resolve()
    if not output.is_relative_to((ROOT / "build").resolve()):
        parser.error("Use a new output directory inside build/.")
    protected = [path for path in (args.ap_root / "custom_worlds").rglob("*") if path.is_file()]
    protected += [args.ap_root / name for name in ("host.yaml", "manifest.json", "_persistent_storage.yaml")
                  if (args.ap_root / name).is_file()]
    original = {path: digest(path) for path in protected}
    host, candidate = stage_host(args.ap_root, args.dependencies, output)
    report = {"apworld_sha256": digest(candidate), "cases": [], "real_gameplay": False}
    for number, (name, broad, mixed, overrides) in enumerate(configurations()):
        for repeat in range(args.seeds_per_case):
            case = name + "-" + str(repeat + 1)
            try:
                result = run_case(host, output / case, 202611260000 + number * 10 + repeat,
                                  broad=broad, mixed=mixed, overrides=overrides)
            except Exception as error:
                result = {"returncode": 1, "error": type(error).__name__ + ": " + str(error)}
            report["cases"].append({"case": case, **result})
            (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps({"case": case, "returncode": result["returncode"], "seconds": result.get("seconds")}), flush=True)
    report["installed_ap_unchanged"] = all(path.is_file() and digest(path) == value for path, value in original.items())
    report["all_passed"] = all(row["returncode"] == 0 for row in report["cases"])
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    assert report["installed_ap_unchanged"]
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    if "--run" in sys.argv:
        sys.exit(campaign())
    unittest.main()
