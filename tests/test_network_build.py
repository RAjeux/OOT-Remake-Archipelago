"""Opt-in, offline end-to-end build against a private copy of real game data.

Set OOTRR_RUN_NETWORK_BUILD=1 and OOTRR_TEST_ZSTD_DLL to run this integration
test. It never installs a mod, starts a game, or opens an AP connection.
OOTRR_NETWORK_BUILD_ALL_LOCAL=1 selects the maximum native-callback fixture;
this is a test variant and does not impose production item ownership.
An explicit OOTRR_NETWORK_BUILD_PREPARED_RESUME reuses a completed private
overlay while applying the product's idempotent saved-chest registration.
"""
import faulthandler
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import sys
import time
from types import SimpleNamespace
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))

# All native source families supported by this adapter, with the same single
# engine and a fixed seed. No generated files from a developer's build folder
# are needed to reproduce the fixture.
MAX_SETTINGS = {
    "shuffle_pots": "all", "shuffle_crates": "all", "shuffle_freestanding_items": "all",
    "shuffle_smallkeys": "keysanity", "shuffle_bosskeys": "keysanity", "shuffle_mapcompass": "keysanity",
    "shuffle_ganon_bosskey": "keysanity", "shuffle_songs": "anywhere", "shuffle_potion_shop": True,
    "shuffle_skulltulas": "matched", "shuffle_scrubs_a": True, "shuffle_scrubs_b": True,
    "shuffle_shops": "random", "shuffle_cows": True, "shuffle_beehives": True,
    "shuffle_treasure_reward": True, "shuffle_dungeon_rewards": "anywhere", "plant_beans": True,
    "shuffle_rocks": "all", "shuffle_grass": "all", "shuffle_frog_songs": True,
    "shuffle_frog_bug_heart": True, "shuffle_merchants": "all", "shuffle_ocarinas": True,
    "shuffle_kokiri_sword": True, "adult_trade_shuffle": True,
}
MAX_SEED = "AP-NETWORK-AUDIT"
MAX_NATIVE_SEED_SHA256 = "aca6228e7bc8b4bd6a8ba07d5a44a6ab5f9826102e930290df472fe4859bbe3f"
MAX_FEATURES = dict(schema=1, settings=dict(
    nocturne_trigger="classic", prelude_trigger="classic", skulls_by_day=True,
    free_scarecrow=True, skip_tower_escape=True, skip_area_intros=True, dungeon_key_tracker=True,
    dpad_gear_cycle=True, fishing_any_fish=True, faster_ocarina_minigame=True,
    dampe_one_race=True, dampe_first_dig=True, disable_low_health_warnings=True,
    owl_warps=True, starting_bunny_hood=True, shuffle_ice_traps=True, ice_trap_count=6,
    cosmetic_color_mode="custom", cosmetic_colors={"kokiri": "#2288AA", "navi": "random"},
    shuffle_music="grouped", shuffle_sfx="grouped",
    damage_taken="double", unbreakable_bowling_grass=True, harder_talon_cuccos=True,
    fireball_storms=True, mega_like_likes=True, random_fuses=True, enemy_randomizer=True,
    shorter_timers="half", enemy_health=125, enemy_damage=125, enemy_speed=110, more_enemies=150,
    enemy_regen=True, enemy_backup=True, no_heart_drops=True, no_gossip_fairies=True,
    no_ammo_drops=True, lose_heart_on_death=True, no_bottles_in_combat=True, no_z_targeting=True,
    no_dupe_items=True, enemies_respawn_sooner=True, boss_minibosses=True, boss_minions=True,
    bean_pitch=True, zora_ambush=True, enemy_gates=True, cucco_revenge=True,
    enemy_spawn_combo=True, fairy_helps_enemies=True))


def input_snapshot(romfs):
    """Inventory all source RomFS metadata and immutable host/SDK source files."""
    records = {}
    for path in romfs.rglob("*"):
        if path.is_file():
            value = path.stat()
            records["romfs/" + path.relative_to(romfs).as_posix()] = (value.st_size, value.st_mtime_ns)
    sdk = Path(os.environ.get("OOTRR_TEST_HOST_SDK", str(Path.home() / "AppData/Local/Programs/Triforce/tools")))
    for part in ("host", "gpu", "include"):
        for path in (sdk / part).rglob("*") if (sdk / part).is_dir() else ():
            if path.is_file() and path.suffix.lower() in {".c", ".h", ".cpp", ".hpp", ".inc", ".glsl", ".json"}:
                records["sdk/" + path.relative_to(sdk).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ("Triforce.exe", "triforce_vk.dll", "image.bin"):
        path = romfs.parent / name
        if path.is_file():
            value = path.stat()
            records["host/" + name] = (value.st_size, value.st_mtime_ns)
    return records


def action_name(event):
    data = event.data
    if not hasattr(data, "actor_action"):
        return None
    return str(data.actor.v.identifier) + "." + data.actor_action.v.v


@unittest.skipUnless(os.name == "nt" and os.environ.get("OOTRR_RUN_NETWORK_BUILD") == "1",
                     "requires the explicitly enabled Windows real-game build fixture")
class NetworkBuildTests(unittest.TestCase):
    def test_maximum_native_sources_prepare_without_a_second_randomizer(self):
        from collections import Counter
        from ootrr_triforce import app_runtime, player, medallions, engine, feature_setup
        from ootrr_triforce.catalog import GAME, PROTOCOL, ITEM_DATA, ITEM_IDS
        from ootrr_triforce.engine import run_engine
        from ootrr_triforce.master_sword import LOCATION, ITEM
        from ootrr_triforce.access_logic import AccessLogic, key_caps
        from ootrr_triforce.feature_settings import read_features
        from ootrr_triforce.pool_adjustments import prepare as prepare_pool, from_manifest as manifest_pool
        from ootrr_triforce.room_identity import token as room_token
        from ootrr_triforce.network_catalog import validate_sources
        from ootrr_triforce.restoration import GAME_DATA, prepared_locations
        from ootrr_triforce.mod_codec import Codec

        resume = os.environ.get("OOTRR_NETWORK_BUILD_RESUME")
        prepared_resume = os.environ.get("OOTRR_NETWORK_BUILD_PREPARED_RESUME")
        self.assertFalse(prepared_resume and not resume,
                         "A prepared-overlay resume requires its private base fixture.")
        all_local = os.environ.get("OOTRR_NETWORK_BUILD_ALL_LOCAL") == "1"
        proof = Path(resume).resolve() if resume else ROOT / "build" / ("MAX-e2e-" + uuid.uuid4().hex[:10])
        self.assertTrue(proof.resolve().is_relative_to((ROOT / "build").resolve()))
        self.assertTrue(proof.name.startswith("MAX-e2e-"))
        proof.mkdir(parents=True, exist_ok=bool(resume))
        print("PROOF_DIR=" + str(proof), flush=True)
        started = time.monotonic()
        stage = "resources"
        result = {"proof": str(proof), "synthetic_roster": True, "actual_ap_fill": False,
                  "resumed": bool(resume), "all_local_test_variant": all_local}
        if resume:
            result["previous_result"] = json.loads((proof / "result.json").read_text(encoding="utf-8"))
        prior_resources = app_runtime._resource_override
        prior_engine_resources = engine.resources
        packaged_engine = ROOT / "client/ootrr_triforce/engine.wasm"
        packaged_engine_before = hashlib.sha256(packaged_engine.read_bytes()).hexdigest()
        source_before = None
        source_hashes = {}
        prior_feature_methods = {}
        faulthandler.dump_traceback_later(300, repeat=True)
        try:
            resources = proof / "resources"
            (resources / "native").mkdir(parents=True, exist_ok=True)
            (resources / "runtime").mkdir(exist_ok=True)
            # Only the current 0.10 native client is used. The compression DLL
            # is an independent runtime dependency, supplied explicitly.
            native = ROOT / "prebuilt/windows-x64/archipelago.dll"
            compression = Path(os.environ["OOTRR_TEST_ZSTD_DLL"]).resolve()
            self.assertTrue(native.is_file())
            self.assertTrue(compression.is_file())
            shutil.copy2(native, resources / "native/archipelago.dll")
            shutil.copy2(compression, resources / "runtime/libzstd.dll")
            shutil.copy2(ROOT / "VERSION", resources / "VERSION")
            app_runtime._resource_override = resources
            selected_engine = Path(os.environ.get("OOTRR_TEST_ENGINE", str(packaged_engine))).resolve()
            self.assertEqual(selected_engine.read_bytes()[:4], b"\0asm")
            shutil.copy2(selected_engine, resources / "engine.wasm")
            shutil.copy2(ROOT / "client/ootrr_triforce/engine.cjs", resources / "engine.cjs")
            engine.resources = SimpleNamespace(files=lambda _package: resources)
            result.update(version=(ROOT / "VERSION").read_text().strip(),
                          native_sha256=hashlib.sha256(native.read_bytes()).hexdigest(),
                          engine_sha256=hashlib.sha256((resources / "engine.wasm").read_bytes()).hexdigest(),
                          catalogue_sha256=hashlib.sha256((ROOT / "client/ootrr_triforce/network_sources.json").read_bytes()).hexdigest())

            stage = "generate"
            generated = (json.loads((proof / "generated.json").read_text(encoding="utf-8")) if resume else
                         json.loads(run_engine("generate", {"settings": MAX_SETTINGS, "seed": MAX_SEED,
                                                             "features": MAX_FEATURES})))
            native_seed_bytes = json.dumps(generated["seed_file"], ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":")).encode()
            self.assertEqual(hashlib.sha256(native_seed_bytes).hexdigest(), MAX_NATIVE_SEED_SHA256,
                             "source export must not alter the native randomization")
            self.assertTrue(generated["progression_items"])
            self.assertEqual(generated["network_sources_schema"], 2)
            validate_sources(generated)
            (proof / "generated.json").write_text(json.dumps(generated, ensure_ascii=False), encoding="utf-8")
            seed = generated["seed_file"]
            moved = {name: row["generated_item"] for name, row in generated["network_sources"].items()}
            moved[LOCATION] = ITEM
            access = AccessLogic(generated["access_logic"], master_sword=True)
            progression = {name for name, advances in zip(access.world.items, access.world.adv) if advances}
            progression.add(ITEM)
            features = read_features(MAX_FEATURES)
            pool = prepare_pool(moved, features["settings"], progression, random.Random(20261127))
            complete = access.sweep(Counter(pool.values()))
            missing = set(moved) - complete.reach
            if missing:
                self.assertTrue(missing <= generated.get("optional_sources", {}).keys())
                required = Counter(item for item in pool.values() if item in progression)
                access = AccessLogic(generated["access_logic"], master_sword=True,
                                     optional=missing, required=required.items())
            self.assertTrue(access.sweep(Counter(pool.values())).won)
            self.assertEqual(sum(item == "Ice Trap" for item in pool.values()), 6)
            room = "MAX-build-" + proof.name
            token = room_token(room, 1, seed["checksum"], True, features=features, access_logic=access.raw)
            data = dict(game=GAME, protocol=PROTOCOL, room=room, slot="BuildTest", player=1, token=token,
                        seed_file=seed, checks=sorted(moved), moved=moved, death_link=True,
                        reward_mode="all_locations", local_items=True, kokiri_shop_checks=False,
                        shop_check_mode="randomized_stock", shop_checks=sorted(seed.get("shops", {})),
                        foreign_only_shops=False, shuffle_skulltulas="matched", local_skulltulas={},
                        adult_trade_shuffle=True, shuffle_master_sword=True, shops_always_open=True,
                        network_sources_schema=2, network_sources=generated["network_sources"],
                        additional_sources=generated["additional_sources"], access_logic=access.raw,
                        features=features, key_caps=key_caps(access.raw, pool.values()),
                        pool_substitutions={name: item for name, item in pool.items() if item != moved[name]},
                        optional_sources=generated.get("optional_sources", {}), progression_items=generated["progression_items"])
            self.assertGreaterEqual(len(data["checks"]), 1200)
            self.assertEqual(len(data["shop_checks"]), 64)
            manifest = proof / "BuildTest.apootrr"
            manifest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(player.read_manifest(manifest), data)
            self.assertEqual(manifest_pool(data), pool)
            roster = {}
            unsafe_refills = []
            for index, name in enumerate(sorted(pool)):
                item = pool[name]
                self.assertIn(item, ITEM_DATA)
                metadata = ITEM_DATA[item]
                local = all_local or index % 2 == 0
                if (local and name not in data["shop_checks"] and metadata.get("bottle_item")
                        and metadata.get("pouch_special") == "NotPushToPouch"):
                    local = False
                    unsafe_refills.append(name)
                roster[name] = dict(item=item, player="BuildTest" if local else "Ami", local=local,
                                    owner=1 if local else 2, item_id=ITEM_IDS[item] if local else 50000000 + index,
                                    game=GAME if local else "Another Test Game")
            (proof / "roster.json").write_text(json.dumps(roster, ensure_ascii=False), encoding="utf-8")
            result.update(checks=len(moved), kinds=dict(Counter(row["kind"] for row in generated["network_sources"].values())),
                          own_rewards=sum(row["local"] for row in roster.values()),
                          foreign_rewards=sum(not row["local"] for row in roster.values()),
                          local_item_types=len({row["item"] for row in roster.values() if row["local"]}),
                          unsafe_refills_made_foreign=len(unsafe_refills), canonical_seed_unchanged=True,
                          features=features, key_caps=data["key_caps"], additional_sources=data["additional_sources"],
                          pool_substitutions=data["pool_substitutions"])

            stage = "base-build"
            cfg = dict(romfs=os.environ.get("OOTRR_TEST_ROMFS", str(Path.home() / "Games/Triforce/romfs")),
                       ootrr=os.environ.get("OOTRR_TEST_BUILDER", str(app_runtime.default_base() / "tools" / app_runtime.BUILDER_FOLDER / "ootrr.exe")),
                       host="nx2navi", native=True, baseline=0, reward_mode="all_locations", local_items=True,
                       shop_prices={name: row["price"] for name, row in seed.get("shops", {}).items()})
            source_romfs = Path(cfg["romfs"]).resolve()
            source_before = input_snapshot(source_romfs)
            result["protected_romfs_files"] = sum(name.startswith("romfs/") for name in source_before)
            result["protected_sdk_files"] = sum(name.startswith("sdk/") for name in source_before)
            result["protected_host_files"] = sum(name.startswith("host/") for name in source_before)
            from oot_rando.patching.title_badge import BADGE_FILES
            for relative in (GAME_DATA, "Event/EventFlow/NaviHint.bfevfl.zs", "Pack/ZsDic.pack.zs", *BADGE_FILES):
                path = source_romfs / relative
                source_hashes[path] = hashlib.sha256(path.read_bytes()).hexdigest()
            # Preserve a failed private intermediate for diagnosis before the
            # production transaction removes its temporary staging directory.
            for method_name in ("prepare_features", "prepare_cosmetics"):
                original = getattr(feature_setup, method_name)
                prior_feature_methods[method_name] = original
                def observed(romfs, mod, data, _original=original, _name=method_name):
                    try:
                        return _original(romfs, mod, data)
                    except Exception:
                        diagnostic = proof / ("failed-" + _name)
                        if Path(mod).resolve().is_relative_to(proof.resolve()) and not diagnostic.exists():
                            try:
                                shutil.copytree(mod, diagnostic)
                                result["failed_stage_overlay"] = str(diagnostic)
                            except OSError as snapshot_error:
                                result["failed_stage_snapshot_error"] = str(snapshot_error)
                        raise
                setattr(feature_setup, method_name, observed)
            private_root = proof / "room"
            if resume:
                self.assertTrue((private_root / "mods/Archipelago/romfs").is_dir())
                print("STAGE=base-reused", flush=True)
                result["base_build_seconds"] = result["previous_result"]["base_build_seconds"]
                from ootrr_triforce.native_setup import prepare_chest_flags
                result["resumed_base_chest_registration_changed"] = prepare_chest_flags(
                    Path(cfg["romfs"]), private_root / "mods/Archipelago/romfs", data)
            else:
                print("STAGE=base-build", flush=True)
                player.build(private_root, cfg, data)
                result["base_build_seconds"] = round(time.monotonic() - started, 3)
            self.assertEqual(hashlib.sha256((private_root / "mods/Archipelago/archipelago.dll").read_bytes()).hexdigest(),
                             result["native_sha256"])
            self.assertFalse((private_root / "mods/Archipelago/romfs/romfs").exists(),
                             "Cosmetics must target the mod root, not create a nested overlay.")
            # A resumed private fixture can predate a new native display alias.
            # Complete its visual resources before the room cache fingerprint
            # is computed. Fresh builds already carry them; this is idempotent.
            from ootrr_triforce.presentation_models import prepare_presentation_models
            result["presentation_models"] = prepare_presentation_models(
                Path(cfg["romfs"]), private_root / "mods/Archipelago/romfs")
            codec = Codec((Path(cfg["romfs"]) / "Pack/ZsDic.pack.zs").read_bytes())
            native_data_size = len(codec.decode((Path(cfg["romfs"]) / GAME_DATA).read_bytes()))
            base_data_size = len(codec.decode((private_root / "mods/Archipelago/romfs" / GAME_DATA).read_bytes()))
            result.update(native_game_data_bytes=native_data_size, base_game_data_bytes=base_data_size)
            # A source adds a handful of saved values. Appending one enlarged
            # BYML pointer table per value previously inflated this to 63MB.
            self.assertLess(base_data_size, native_data_size + len(data["checks"]) * 8192)
            result["base_build_pass"] = True

            stage = "room-prepare"
            print("STAGE=room-prepare", flush=True)
            if prepared_resume:
                prepared = Path(prepared_resume).resolve()
                self.assertTrue(prepared.is_relative_to((private_root / "v14").resolve()))
                self.assertEqual(prepared.name, "mods")
                self.assertTrue((prepared / "Archipelago/romfs").is_dir())
                from ootrr_triforce.native_setup import prepare_chest_flags
                repaired = prepared / "Archipelago/romfs"
                result["resumed_prepared_chest_registration_changed"] = prepare_chest_flags(
                    Path(cfg["romfs"]), repaired, data)
                from ootrr_triforce.medallions import REST
                stable = {path: hashlib.sha256((repaired / path).read_bytes()).hexdigest()
                          for path in (GAME_DATA, REST)}
                self.assertFalse(prepare_chest_flags(Path(cfg["romfs"]), repaired, data))
                self.assertEqual(stable, {path: hashlib.sha256((repaired / path).read_bytes()).hexdigest()
                                          for path in stable})
                result["prepared_overlay_reused"] = True
                result["chest_registration_idempotent"] = True
            else:
                prepared = medallions.prepare(private_root, player.preparation_settings(cfg, data), roster, moved)
            mod = prepared / "Archipelago/romfs"
            self.assertFalse((mod / "romfs").exists())
            recovery = prepared_locations(mod, data["checks"])
            self.assertEqual(len(recovery), len(data["checks"]))
            self.assertTrue((mod / "Archipelago/room-v1.txt").is_file())
            self.assertEqual((mod / "Archipelago/room-v1.txt").read_text().strip(), token)
            self.assertEqual(hashlib.sha256((prepared / "Archipelago/archipelago.dll").read_bytes()).hexdigest(), result["native_sha256"])
            model_counts = {
                "receipt": len(list((mod / "Pack/Actor").glob("Item_AP_Show_*.pack.zs"))),
                "chest": len(list((mod / "Pack/Actor").glob("Item_AP_Chest_*.pack.zs"))),
            }
            self.assertEqual(model_counts["receipt"], result["presentation_models"]["models"])
            self.assertEqual(model_counts["chest"], result["presentation_models"]["chest_models"])
            # Native event counts and indices are u16. The all-local variant
            # catches growth hidden by multiworlds with mostly foreign items.
            from oot_rando.patching.event_patch import _flow
            from oot_rando.formats import byml_codec
            from ootrr_triforce.network_catalog import check_flags, murmur3
            native_data = byml_codec.load(codec.decode((mod / GAME_DATA).read_bytes()))["root"]["Data"]
            bool_hashes = {int(row["Hash"]) for row in native_data["Bool"]}
            extra_chests = [name for name in data["additional_sources"]
                            if data["network_sources"][name]["kind"] == "chest"]
            self.assertEqual(len(extra_chests), 16)
            for name in extra_chests:
                self.assertTrue(set(check_flags(name, network=True)) <= bool_hashes,
                                "Additional chest completion is not registered: " + name)
            open_struct, = [row for row in native_data["Struct"] if row["Hash"] == murmur3("IsTreasureBoxOpen")]
            open_members = {int(row["Hash"]): int(row["Value"]) for row in open_struct["DefaultValue"]}
            for name in extra_chests:
                for variant in data["network_sources"][name]["variants"]:
                    actor = str(variant["actor"])
                    self.assertEqual(open_members.get(murmur3(actor)), murmur3("IsTreasureBoxOpen." + actor),
                                     "Native opening and AP tracking must read the same saved Bool: " + name)
            result["additional_chest_flags_registered"] = len(extra_chests)

            # The six frozen vanilla chests are ordinary persistent AP chests.
            # Neither their original trap actor nor a trap-AI reference may
            # remain attached to these physical identities.
            maps = {}
            frozen = [name for name in extra_chests
                      if data["network_sources"][name].get("native_route") == "frozen_chest"]
            self.assertEqual(len(frozen), 6)
            for name in frozen:
                for variant in data["network_sources"][name]["variants"]:
                    filename, actor_hash = variant["file"], int(variant["actor"])
                    if filename not in maps:
                        maps[filename] = byml_codec.load(codec.decode((mod / filename).read_bytes()))["root"]
                    document = maps[filename]
                    actors = [row for row in document["Actors"] if int(row.get("Hash", 0)) == actor_hash]
                    self.assertEqual(len(actors), 1)
                    self.assertEqual(actors[0]["Gyaml"], "Obj_TBox_A_01")
                    for group in document.get("AiGroups", []):
                        refs = group.get("References", [])
                        whole = "Gimmick_TrapTreasureBox_Set" in str(group.get("Logic", ""))
                        prefixes = [str(row.get("Path", ""))[:-len("AiGroup")] for row in refs
                                    if row.get("Id") == "AiGroup"
                                    and "Gimmick_TrapTreasureBox_Set" in str(row.get("Logic", ""))]
                        for row in refs:
                            if row.get("Reference") == actor_hash:
                                self.assertFalse(whole or any(str(row.get("Path", "")).startswith(p) for p in prefixes), name)
            result["frozen_chests_normalized"] = len(frozen)

            navi = _flow(codec.decode((mod / "Event/EventFlow/NaviHint.bfevfl.zs").read_bytes())).flowchart
            field = next(entry for entry in navi.entry_points if entry.name == "NaviHint_Field")
            self.assertTrue(field.main_event.v.name.startswith("APNaviSafetyTimer"))
            query = field.main_event.v.data
            self.assertEqual(str(query.actor.v.identifier), "ChallengeSystemActor")
            self.assertEqual(query.actor_query.v.v, "EventQueryMiniGameTimerIsCounting")
            leaves = [event for event in navi.events if event.name.startswith("OOTRRNavi")
                      and action_name(event) == "GameSystemActor.EventTriggerLeaveGameSafetySection"]
            self.assertEqual(len(leaves), 14, "The maximum fixture uses the builder's default Everywhere Navi return.")
            for leave in leaves:
                node = leave
                for expected in ("GameSystemActor.EventTriggerLeaveGameSafetySection",
                                 "ChallengeSystemActor.EventTriggerMiniGameTimerStop",
                                 "ChallengeSystemActor.EventTriggerUnshowTimerUI",
                                 "GameSystemActor.EventReserveBancChange"):
                    self.assertEqual(action_name(node), expected)
                    node = node.data.nxt.v
            result["navi_generated_safety_guards"] = len(leaves)

            from ootrr_triforce.receipt_events import FLOW_PATH, event_name
            from oot_rando.patching.event_info import reachable, entry_calls
            receive_raw = codec.decode((mod / FLOW_PATH).read_bytes())
            receive = _flow(receive_raw).flowchart
            trap_entry = next(entry for entry in receive.entry_points if entry.name == event_name(ITEM_IDS["Ice Trap"]))
            self.assertIn(("Dm_SY_GetInEvent", "AP_IceTrap"), entry_calls(receive_raw, trap_entry.name))
            self.assertFalse(any(action_name(event) == "PouchSystemActor.EventTriggerAddOrRemovePouchContent"
                                 for event in reachable(trap_entry.main_event.v)))
            self.assertTrue((mod / "Pack/Actor/OOTRR_ConditionSensor_Cold.pack.zs").is_file())
            result["ice_trap_native_effect_without_inventory_grant"] = True

            from importlib import resources as package_resources
            import zlib
            from ootrr_triforce.title_screen import apply_badge
            tiles = zlib.decompress(package_resources.files("ootrr_triforce").joinpath("title.tiles").read_bytes())
            for relative in BADGE_FILES:
                original = codec.decode((source_romfs / relative).read_bytes())
                self.assertEqual(codec.decode((mod / relative).read_bytes()), apply_badge(original, tiles),
                                 "Cosmetics must preserve the exact Archipelago title branding.")
            result["archipelago_branding_preserved"] = True
            event_counts = {}
            for path in sorted((mod / "Event/EventFlow").glob("*.bfevfl.zs")):
                chart = _flow(codec.decode(path.read_bytes())).flowchart
                self.assertIsNotNone(chart)
                event_counts[path.name] = len(chart.events)
            largest = max(event_counts, key=event_counts.get)
            self.assertLess(event_counts[largest], 65535)
            (proof / "flow-capacity.json").write_text(json.dumps(event_counts, indent=2), encoding="utf-8")
            result.update(pass_build=True, prepared=str(prepared), restoration_locations=len(recovery),
                          room_preparation_revision=medallions.REVISION, staged_native_models=model_counts,
                          largest_flow=largest, largest_event_count=event_counts[largest],
                          event_capacity_remaining=65535 - event_counts[largest],
                          elapsed_seconds=round(time.monotonic() - started, 3))
            print("MAX_BUILD_PASS=" + str(prepared), flush=True)
        except Exception as exc:
            result.update(pass_build=False, stage=stage, error=type(exc).__name__ + ": " + str(exc),
                          elapsed_seconds=round(time.monotonic() - started, 3))
            raise
        finally:
            faulthandler.cancel_dump_traceback_later()
            app_runtime._resource_override = prior_resources
            engine.resources = prior_engine_resources
            for name, method in prior_feature_methods.items():
                setattr(feature_setup, name, method)
            result["packaged_engine_unchanged"] = hashlib.sha256(packaged_engine.read_bytes()).hexdigest() == packaged_engine_before
            if source_before is not None:
                result["original_romfs_and_sdk_unchanged"] = (
                    input_snapshot(source_romfs) == source_before
                    and all(hashlib.sha256(path.read_bytes()).hexdigest() == value for path, value in source_hashes.items()))
                result["protected_source_files"] = len(source_before)
                result["protected_source_state_sha256"] = hashlib.sha256(
                    json.dumps(source_before, sort_keys=True).encode()).hexdigest()
            (proof / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            self.assertTrue(result["packaged_engine_unchanged"])
            if source_before is not None:
                self.assertTrue(result["original_romfs_and_sdk_unchanged"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
