"""Opt-in real AP generation, using an isolated copy of the official generator.

First run tools/prepare_ap_test_env.py to create private --dependencies below
build/. Use --ap-root for your Windows Archipelago 0.6.8 installation. This
frozen-executable harness does not use AP_SOURCE. No installed APWorld,
original game, profile or save is modified.
The normal unit suite does not invoke this integration harness.
"""
from collections import Counter, defaultdict, namedtuple
import ast
import copy
from enum import IntEnum
import hashlib
import importlib.util
import io
import json
import os
import pickle
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from zipfile import ZipFile
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
sys.path.insert(0, str(ROOT / "tools"))
from prepare_ap_test_env import RUNTIME_FILES, private_destination, validate_snapshot


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_multidata(archive):
    """Read only the two data types allowed in our own AP-generated room."""
    slot = namedtuple("NetworkSlot", "name game type group_members")
    slot_type = IntEnum("SlotType", {"spectator": 0, "player": 1, "group": 2})
    class DataReader(pickle.Unpickler):
        def find_class(self, module, name):
            if module == "NetUtils" and name == "NetworkSlot":
                return slot
            if module == "NetUtils" and name == "SlotType":
                return slot_type
            raise ValueError("Unexpected AP room data type: " + module + "." + name)
    raw = archive.read(next(name for name in archive.namelist() if name.endswith(".archipelago")))
    assert raw[0] == 3, "Unexpected AP multidata version"
    return DataReader(io.BytesIO(zlib.decompress(raw[1:]))).load()


def stage_host(ap_root, dependencies, output, engine=None):
    """Own the writable host; share only a verified, independently copied runtime."""
    if os.name != "nt":
        raise ValueError("This harness runs the Windows Archipelago 0.6.8 executable; AP_SOURCE is supported only by the separate protocol tests.")
    ap_root, dependencies, output = map(lambda path: Path(path).resolve(), (ap_root, dependencies, output))
    output = private_destination(output, ap_root)
    validate_snapshot(dependencies, ap_root)
    if output == dependencies or output.is_relative_to(dependencies):
        raise ValueError("The validation folder must be outside the private dependency snapshot.")
    if output.exists():
        raise FileExistsError("Choose a fresh validation folder: " + str(output))
    output.mkdir(parents=True)
    host = output / "Archipelago"
    host.mkdir()
    for name in ("lib", "data"):
        source = dependencies / name
        if not source.is_dir():
            raise ValueError("Missing private AP dependencies: " + str(source))
        if os.name == "nt":
            quote = lambda value: "'" + str(value).replace("'", "''") + "'"
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                            "New-Item -ItemType Junction -Path " + quote(host / name) +
                            " -Target " + quote(source) + " | Out-Null"], check=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            (host / name).symlink_to(source, target_is_directory=True)
    for name in RUNTIME_FILES:
        shutil.copy2(dependencies / name, host / name)
    (host / "custom_worlds").mkdir()
    spec = importlib.util.spec_from_file_location("validation_packaging", ROOT / "tools/build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    entries = list(build.tree(ROOT / "apworld"))
    entries.extend(("ootrr_remake/" + name, Path(engine) if name == "engine.wasm" and engine else
                    ROOT / "client/ootrr_triforce" / name) for name in build.WORLD_FILES)
    candidate = host / "custom_worlds/ootrr_remake.apworld"
    build.archive(candidate, entries)
    with ZipFile(candidate) as archive:
        assert {name.split("/")[0] for name in archive.namelist()} == {"ootrr_remake"}
        assert "ootrr_remake/settings_labels.py" in archive.namelist()
        assert "ootrr_remake/network_sources.json" in archive.namelist()
    return host, candidate


def broad_values():
    from ootrr_triforce.settings import default_options, SPEC_BY_ID
    values = default_options()
    values.update(shuffle_chests="all", shuffle_shops="random", shuffle_skulltulas="matched",
                  shuffle_pots="all", shuffle_crates="all", shuffle_rocks="all", shuffle_grass="all",
                  shuffle_beehives=True, shuffle_freestanding_items="all", shuffle_rewards="supported",
                  shuffle_rewards_extra=True, shuffle_boss_hearts=True, shuffle_songs="anywhere",
                  shuffle_potion_shop=True, adult_trade_shuffle=True, shuffle_scrubs_a=True,
                  shuffle_scrubs_b=True, shuffle_cows=True, shuffle_treasure_reward=True,
                  shuffle_dungeon_rewards="anywhere", shuffle_frog_songs=True,
                  shuffle_frog_bug_heart=True, shuffle_ocarinas=True, shuffle_kokiri_sword=True,
                  shuffle_master_sword=True, shuffle_merchants="all", plant_beans=True,
                  shuffle_smallkeys="keysanity", shuffle_bosskeys="keysanity",
                  shuffle_ganon_bosskey="keysanity", shuffle_mapcompass="keysanity",
                  shops_always_open=True, death_link=True)
    if "all" in SPEC_BY_ID["shuffle_skulltulas"]["choices"]:
        values["shuffle_skulltulas"] = "all"
    return values


def probe_engine(engine, output, *, seed="AP-NETWORK-AUDIT", broad=True):
    """Audit the real native export independently of the AP world wrapper."""
    from ootrr_triforce.catalog import ITEM_DATA
    from ootrr_triforce.network_catalog import validate_sources
    from ootrr_triforce.settings import default_options, engine_settings
    node = os.environ.get("OOTRR_NODE") or shutil.which("node")
    if not node:
        raise RuntimeError("Install Node.js or set OOTRR_NODE before probing the built engine.")
    command = [node, "--no-warnings", str(ROOT / "client/ootrr_triforce/engine.cjs"), str(Path(engine).resolve()), "generate"]
    process = subprocess.run(command, input=json.dumps({"settings": engine_settings(broad_values() if broad else default_options()),
                                                       "seed": seed}).encode(), capture_output=True, timeout=120,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if process.returncode:
        raise RuntimeError(process.stderr.decode("utf-8", errors="replace"))
    result = json.loads(process.stdout)
    Path(output).write_bytes(process.stdout)
    sources = validate_sources(result)
    unsupported = {name: row["generated_item"] for name, row in sources.items() if row["generated_item"] not in ITEM_DATA}
    no_dungeon = {name: row["generated_item"] for name, row in sources.items()
                  if row["generated_item"] in ITEM_DATA and ITEM_DATA[row["generated_item"]]["mode"] == "generic"
                  and not ITEM_DATA[row["generated_item"]].get("dungeon")}
    proven = {name for row in result["waves"] for name in row}
    missing = sorted(sources.keys() - proven)
    graph_won = None
    if "access_logic" in result:
        from ootrr_triforce.access_logic import AccessLogic
        access = AccessLogic(result["access_logic"])
        full = access.sweep(Counter(row["generated_item"] for row in sources.values()))
        missing = sorted(sources.keys() - full.reach)
        graph_won = full.won
    return {"sources": len(sources), "kinds": dict(Counter(row["kind"] for row in sources.values())),
            "missing_proof": missing, "donor_wave_only_missing": sorted(sources.keys() - proven),
            "native_access_graph_victory": graph_won, "unsupported_items": unsupported,
            "unresolved_dungeon_items": no_dungeon, "optional": result.get("optional_sources", {})}


def check_room(archive_path, player_names, candidate=None, settings_by_slot=None):
    """Check exact enabled-source/pool conservation and count actual AP ownership."""
    from ootrr_triforce.catalog import LOCATION_IDS
    from ootrr_triforce.master_sword import LOCATION as SWORD
    from ootrr_triforce.network_catalog import SOURCES, validate_sources
    from ootrr_triforce.pool_adjustments import from_manifest as manifest_pool
    from ootrr_triforce.access_logic import AccessLogic, key_caps
    if candidate is not None:
        # Audit the exact package that generated the room. Source changes made
        # by a parallel worker must not invalidate this frozen proof midway.
        with ZipFile(candidate) as package:
            catalogue = json.loads(package.read("ootrr_remake/network_sources.json"))
            additional = (json.loads(package.read("ootrr_remake/additional_sources.json"))
                          if "ootrr_remake/additional_sources.json" in package.namelist() else
                          dict(schema=catalogue["schema"], sources={}, rewards={}))
            tree = ast.parse(package.read("ootrr_remake/network_catalog.py").decode("utf-8"))
        namespace = {"SCHEMA": additional["schema"], "LEGACY_SOURCES": catalogue["sources"],
                     "ADDITIONAL_SOURCES": additional["sources"], "ADDITIONAL_REWARDS": additional["rewards"],
                     "SOURCES": dict(catalogue["sources"], **additional["sources"]), "copy": copy}
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in {"enabled", "_additional_reward", "validate_sources"}]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "frozen_network_catalog.py", "exec"), namespace)
        SOURCES, validate_sources = namespace["SOURCES"], namespace["validate_sources"]
    with ZipFile(archive_path) as archive:
        manifests = [json.loads(archive.read(name)) for name in archive.namelist() if name.endswith(".apootrr")]
        spoiler = archive.read(next(name for name in archive.namelist() if name.endswith("_Spoiler.txt"))).decode("utf-8-sig")
        multidata = read_multidata(archive)
    lines = spoiler.splitlines()
    # Playthrough repeats some assignments. Map by source+slot to count each once.
    assignments = {}
    expected_pools = {}
    access_models = {}
    for manifest in manifests:
        slot = manifest["slot"]
        # Use the launcher's real input validator as well as independent AP
        # pool/logic checks. This catches an unreadable player file immediately.
        from ootrr_triforce.player import read_manifest
        with tempfile.TemporaryDirectory(prefix="manifest-audit-", dir=Path(archive_path).parent) as folder:
            player_path = Path(folder) / "player.apootrr"
            player_path.write_text(json.dumps(manifest), encoding="utf-8")
            assert read_manifest(player_path) == manifest
        if settings_by_slot and manifest.get("features") is not None:
            from ootrr_triforce.feature_settings import feature_config, read_features
            expected_features = read_features(feature_config(settings_by_slot[slot]))
            assert manifest["features"] == expected_features, "AP option conversion changed the requested native features"
        assert set(manifest["checks"]) == set(manifest["moved"])
        descriptors = validate_sources(manifest)
        expected = set(descriptors)
        if manifest.get("shuffle_master_sword"):
            expected.add(SWORD)
        assert set(manifest["checks"]) == expected
        assert len({LOCATION_IDS[name] for name in expected}) == len(expected)
        assert set(descriptors) <= SOURCES.keys()
        original = Counter(row["generated_item"] for row in descriptors.values())
        if manifest.get("shuffle_master_sword"):
            original["Master Sword"] += 1
        assert Counter(manifest["moved"].values()) == original
        pool = manifest_pool(manifest)
        expected_pools[manifest["player"]] = Counter(pool.values())
        if "access_logic" in manifest:
            access = AccessLogic(manifest["access_logic"], master_sword=manifest.get("shuffle_master_sword", False))
            assert set(access.routes) == set(manifest["checks"]), "Access graph lost an enabled AP check"
            complete = access.sweep(expected_pools[manifest["player"]])
            assert complete.won, "Actual AP pool cannot beat the exported native rules"
            assert set(manifest["checks"]) <= complete.reach, "Actual AP pool cannot reach its enabled checks"
            access_models[manifest["player"]] = access
            if "key_caps" in manifest:
                assert manifest["key_caps"] == key_caps(manifest["access_logic"], pool.values())
        for name in manifest["checks"]:
            prefix = f"{name} ({slot}): " if len(player_names) > 1 else f"{name}: "
            hits = [line.strip() for line in lines if line.startswith(prefix)]
            assert hits, (slot, name, "no final AP assignment")
            item = hits[0][len(prefix):]
            owner = next((owner for owner in player_names if item.endswith(" (" + owner + ")")), None) if len(player_names) > 1 else slot
            assert owner is not None, item
            assignments[(slot, name)] = (owner, item[:-(len(owner) + 3)] if len(player_names) > 1 else item)
        for name, item in (manifest.get("features") or {}).get("settings", {}).get("item_plando", {}).items():
            assert assignments.get((slot, name)) == (slot, item), "The exact requested local plan was not placed"
    owners = Counter()
    all_assignments = {}
    for line in lines:
        # Top-level location entries have no indentation. Settings and the
        # playthrough do not pass this exact final-owner/location delimiter.
        if line[:1].isspace():
            continue
        match = re.match(r"^(.+) \(([^()]*)\): (.+) \(([^()]*)\)$", line)
        if match and match[2] in player_names and match[4] in player_names:
            owners[(match[4], match[3])] += 1
            all_assignments[(match[2], match[1])] = (match[4], match[3])
    if len(player_names) == 1:
        owners.update((owner, item) for owner, item in assignments.values())
        all_assignments.update(assignments)
    if settings_by_slot is not None:
        from ootrr_triforce.catalog import GAME
        from ootrr_triforce.network_placement import allowed
        manifests_by_slot = {row["slot"]: row for row in manifests}
        ids = {row["slot"]: row["player"] for row in manifests}
        for (source_slot, source_name), (owner, item_name) in all_assignments.items():
            source_manifest = manifests_by_slot.get(source_slot)
            descriptor = source_manifest["network_sources"].get(source_name, {}) if source_manifest else {}
            if source_name == SWORD and source_manifest:
                descriptor = {"placement": {"dungeon": None, "region_group": "castle"}}
            assert allowed(item_name, ids.get(owner, 0), GAME if owner in ids else "Dark Souls III",
                           settings_by_slot.get(owner, {}), source_name, ids.get(source_slot, 0),
                           GAME if source_slot in ids else "Dark Souls III", descriptor,
                           settings_by_slot.get(source_slot, {})), (source_slot, source_name, owner, item_name, "violates final placement mode")
    from ootrr_triforce.catalog import ITEM_DATA, ITEM_IDS, GAME
    item_names = {code: name for name, code in ITEM_IDS.items()}
    native_binary_pools = defaultdict(Counter)
    protected_count = Counter()
    for source_player, locations in multidata["locations"].items():
        for _address, (code, recipient, _flags) in locations.items():
            if multidata["slot_info"][recipient].game == GAME:
                assert code in item_names, (recipient, code, "no native delivery recipe")
                native_binary_pools[recipient][item_names[code]] += 1
    for manifest in manifests:
        player = manifest["player"]
        assert native_binary_pools[player] == expected_pools[player], "Binary AP item pool differs from the native recipes"
        actual_locations = multidata["locations"][player]
        assert set(actual_locations) == {LOCATION_IDS[name] for name in manifest["checks"]}
        for name, descriptor in manifest["network_sources"].items():
            if (descriptor.get("placement", {}).get("junk_only")
                    or name in getattr(access_models.get(player), "optional", ())):
                code, recipient, flags = actual_locations[LOCATION_IDS[name]]
                assert not (flags & 1), (name, code, recipient, "unsafe source contains progression")
                if multidata["slot_info"][recipient].game == GAME:
                    assert ITEM_DATA[item_names[code]].get("kind") != "Token", "Unsafe source contains a Zelda token"
                protected_count[player] += 1
    matrix = defaultdict(Counter)
    for (source_slot, _name), (owner, _item) in assignments.items():
        matrix[source_slot][owner] += 1
    results = []
    for manifest in manifests:
        slot = manifest["slot"]
        actual = Counter({item: count for (owner, item), count in owners.items() if owner == slot})
        assert actual == expected_pools[manifest["player"]], (slot, "final AP pool differs", actual - expected_pools[manifest["player"]])
        results.append({"slot": slot, "checks": len(manifest["checks"]),
                        "kinds": dict(Counter(row["kind"] for row in manifest["network_sources"].values())),
                        "ownership_at_checks": dict(matrix[slot]),
                        "pool_exact": True, "all_enabled_sources_ap": True,
                        "final_placement_checked": settings_by_slot is not None,
                        "native_delivery_recipes_exact": True,
                        "launcher_manifest_readable": True,
                        "native_access_graph_checked": manifest["player"] in access_models,
                        "features_round_trip_checked": bool(settings_by_slot and manifest.get("features") is not None),
                        "pool_substitutions": len(manifest.get("pool_substitutions", {})),
                        "planned_local_placements": len((manifest.get("features") or {}).get("settings", {}).get("item_plando", {})),
                        "unsafe_sources_filler_only": protected_count[manifest["player"]]})
    assert "Playthrough:" in spoiler, "Official generation must calculate a playthrough."
    if len(player_names) > 1:
        for result in results:
            assert sum(count for owner, count in result["ownership_at_checks"].items() if owner != result["slot"]) > 0
        assert any(owner not in {row["slot"] for row in results} and count for counts in matrix.values() for owner, count in counts.items())
    return results


def run_case(host, case, seed, broad=False, mixed=False, overrides=None, extra_players=None):
    from ootrr_triforce.app_window import yaml_content
    for name in ("players", "output", "local", "roaming", "temp"):
        (case / name).mkdir(parents=True, exist_ok=True)
    values = broad_values() if broad else None
    if overrides:
        from ootrr_triforce.settings import default_options
        values = dict(values or default_options(), **overrides)
    slots = ["AuditZelda"]
    zelda_slots = set(slots)
    (case / "players/AuditZelda.yaml").write_text(yaml_content("AuditZelda", values), encoding="utf-8")
    if mixed:
        slots += ["AuditZeldaTwo", "AuditFriend"]
        zelda_slots.add("AuditZeldaTwo")
        (case / "players/AuditZeldaTwo.yaml").write_text(yaml_content("AuditZeldaTwo", values), encoding="utf-8")
        (case / "players/AuditFriend.yaml").write_text(
            "name: AuditFriend\ngame: Dark Souls III\nDark Souls III:\n  accessibility: full\n", encoding="utf-8")
    for player in extra_players or ():
        slots.append(player["name"])
        content = ("name: " + json.dumps(player["name"]) + "\ngame: " + json.dumps(player["game"]) +
                   "\n" + json.dumps(player["game"]) + ":\n  accessibility: full\n")
        content += "".join("  " + name + ": " + json.dumps(value) + "\n" for name, value in player.get("options", {}).items())
        (case / "players" / (player["name"] + ".yaml")).write_text(content, encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if not key.startswith("HOS_INPUT_")}
    env.update(LOCALAPPDATA=str(case / "local"), APPDATA=str(case / "roaming"), TEMP=str(case / "temp"),
               TMP=str(case / "temp"), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    command = [str(host / "ArchipelagoGenerate.exe"), "--player_files_path", str(case / "players"),
               "--outputpath", str(case / "output"), "--multi", str(len(slots)), "--seed", str(seed),
               "--spoiler", "2", "--log_level", "info", "--log_time"]
    start = time.monotonic()
    with (case / "generation.log").open("wb") as log:
        process = subprocess.run(command, cwd=host, env=env, stdin=subprocess.DEVNULL, stdout=log,
                                 stderr=subprocess.STDOUT, timeout=600,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    result = {"seed": seed, "broad": broad, "players": len(slots), "returncode": process.returncode,
              "seconds": round(time.monotonic() - start, 3)}
    if process.returncode == 0:
        from ootrr_triforce.settings import default_options
        with ZipFile(host / "custom_worlds/ootrr_remake.apworld") as package:
            scoped = b"def stage_set_rules" in package.read("ootrr_remake/__init__.py")
        settings_by_slot = {slot: values or default_options() for slot in zelda_slots} if scoped else None
        result["validation"] = check_room(next((case / "output").glob("*.zip")), slots,
                                          host / "custom_worlds/ootrr_remake.apworld", settings_by_slot)
    else:
        failure = (case / "generation.log").read_text(encoding="utf-8", errors="replace")
        result["error"] = failure[failure.rfind("Traceback"):][-8000:] if "Traceback" in failure else failure[-2000:]
    (case / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ap-root", required=True, type=Path, help="Your Windows Archipelago 0.6.8 installation (read-only).")
    parser.add_argument("--dependencies", required=True, type=Path, help="Private snapshot created by tools/prepare_ap_test_env.py.")
    parser.add_argument("--output-root", required=True, type=Path, help="Fresh result directory below build/.")
    parser.add_argument("--quick", action="store_true", help="Only the baseline single-player room.")
    parser.add_argument("--restricted", action="store_true", help="Also test song-only, end-of-dungeon and LACS restrictions together in a three-player room.")
    parser.add_argument("--engine", type=Path, help="Stage this built engine only inside the private APWorld.")
    args = parser.parse_args()
    protected = [*args.ap_root.joinpath("custom_worlds").rglob("*"),
                 *(args.ap_root / name for name in ("host.yaml", "manifest.json", "_persistent_storage.yaml"))]
    original_hashes = {path: digest(path) for path in protected if path.is_file()}
    host, candidate = stage_host(args.ap_root, args.dependencies, args.output_root, args.engine)
    report = {"apworld_sha256": digest(candidate), "engine_sha256": digest(args.engine or ROOT / "client/ootrr_triforce/engine.wasm"), "cases": []}
    cases = [("default-1", 202611250101, False, False, None)]
    if not args.quick:
        cases += [("default-2", 202611250102, False, False, None), ("broad-solo", 202611250103, True, False, None),
                  ("broad-mixed", 202611250104, True, True, None)]
    if args.restricted:
        cases.append(("restricted-mixed", 202611250105, True, True,
                      {"shuffle_songs": "own", "shuffle_dungeon_rewards": "dungeons",
                       "shuffle_ganon_bosskey": "lacs_dungeons", "lacs_rewards": 6}))
    for name, seed, broad, mixed, overrides in cases:
        result = run_case(host, args.output_root.resolve() / name, seed, broad, mixed, overrides)
        report["cases"].append(result)
        (args.output_root / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"case": name, **result}), flush=True)
    report["installed_ap_files_unchanged"] = all(path.is_file() and digest(path) == value for path, value in original_hashes.items())
    assert report["installed_ap_files_unchanged"], "The installed APWorld and preferences must remain untouched."
    (args.output_root / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    raise SystemExit(any(row["returncode"] for row in report["cases"]))


if __name__ == "__main__":
    main()
