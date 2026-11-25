"""Opt-in, offline end-to-end build against a private copy of real game data.

Set OOTRR_RUN_NETWORK_BUILD=1 and OOTRR_TEST_ZSTD_DLL to run this integration
test. It never installs a mod, starts a game, or opens an AP connection.
OOTRR_NETWORK_BUILD_ALL_LOCAL=1 selects the maximum native-callback fixture;
this is a test variant and does not impose production item ownership.
"""
import faulthandler
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
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


@unittest.skipUnless(os.name == "nt" and os.environ.get("OOTRR_RUN_NETWORK_BUILD") == "1",
                     "requires the explicitly enabled Windows real-game build fixture")
class NetworkBuildTests(unittest.TestCase):
    def test_maximum_native_sources_prepare_without_a_second_randomizer(self):
        from collections import Counter
        from ootrr_triforce import app_runtime, player, medallions
        from ootrr_triforce.catalog import GAME, PROTOCOL, ITEM_DATA, ITEM_IDS
        from ootrr_triforce.engine import run_engine
        from ootrr_triforce.master_sword import LOCATION, ITEM, token_material
        from ootrr_triforce.network_catalog import validate_sources
        from ootrr_triforce.restoration import GAME_DATA, prepared_locations
        from ootrr_triforce.mod_codec import Codec

        resume = os.environ.get("OOTRR_NETWORK_BUILD_RESUME")
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
            result.update(version=(ROOT / "VERSION").read_text().strip(),
                          native_sha256=hashlib.sha256(native.read_bytes()).hexdigest(),
                          engine_sha256=hashlib.sha256((ROOT / "client/ootrr_triforce/engine.wasm").read_bytes()).hexdigest(),
                          catalogue_sha256=hashlib.sha256((ROOT / "client/ootrr_triforce/network_sources.json").read_bytes()).hexdigest())

            stage = "generate"
            generated = (json.loads((proof / "generated.json").read_text(encoding="utf-8")) if resume else
                         json.loads(run_engine("generate", {"settings": MAX_SETTINGS, "seed": MAX_SEED})))
            native_seed_bytes = json.dumps(generated["seed_file"], ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":")).encode()
            self.assertEqual(hashlib.sha256(native_seed_bytes).hexdigest(), MAX_NATIVE_SEED_SHA256,
                             "source export must not alter the native randomization")
            self.assertTrue(generated["progression_items"])
            self.assertEqual(generated["network_sources_schema"], 1)
            validate_sources(generated)
            (proof / "generated.json").write_text(json.dumps(generated, ensure_ascii=False), encoding="utf-8")
            seed = generated["seed_file"]
            moved = {name: row["generated_item"] for name, row in generated["network_sources"].items()}
            moved[LOCATION] = ITEM
            room = "MAX-build-" + proof.name
            token = hashlib.sha256(token_material(room, 1, seed["checksum"], True).encode()).hexdigest()
            data = dict(game=GAME, protocol=PROTOCOL, room=room, slot="BuildTest", player=1, token=token,
                        seed_file=seed, checks=sorted(moved), moved=moved, death_link=True,
                        reward_mode="all_locations", local_items=True, kokiri_shop_checks=False,
                        shop_check_mode="randomized_stock", shop_checks=sorted(seed.get("shops", {})),
                        foreign_only_shops=False, shuffle_skulltulas="matched", local_skulltulas={},
                        adult_trade_shuffle=True, shuffle_master_sword=True, shops_always_open=True,
                        network_sources_schema=1, network_sources=generated["network_sources"],
                        optional_sources=generated.get("optional_sources", {}), progression_items=generated["progression_items"])
            self.assertGreaterEqual(len(data["checks"]), 1200)
            self.assertEqual(len(data["shop_checks"]), 64)
            manifest = proof / "BuildTest.apootrr"
            manifest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(player.read_manifest(manifest), data)
            roster = {}
            unsafe_refills = []
            for index, name in enumerate(sorted(moved)):
                item = moved[name]
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
                          unsafe_refills_made_foreign=len(unsafe_refills), canonical_seed_unchanged=True)

            stage = "base-build"
            cfg = dict(romfs=os.environ.get("OOTRR_TEST_ROMFS", str(Path.home() / "Games/Triforce/romfs")),
                       ootrr=os.environ.get("OOTRR_TEST_BUILDER", str(app_runtime.default_base() / "tools" / app_runtime.BUILDER_FOLDER / "ootrr.exe")),
                       host="nx2navi", native=True, baseline=0, reward_mode="all_locations", local_items=True,
                       shop_prices={name: row["price"] for name, row in seed.get("shops", {}).items()})
            private_root = proof / "room"
            if resume:
                self.assertTrue((private_root / "mods/Archipelago/romfs").is_dir())
                print("STAGE=base-reused", flush=True)
                result["base_build_seconds"] = result["previous_result"]["base_build_seconds"]
            else:
                print("STAGE=base-build", flush=True)
                player.build(private_root, cfg, data)
                result["base_build_seconds"] = round(time.monotonic() - started, 3)
            self.assertEqual(hashlib.sha256((private_root / "mods/Archipelago/archipelago.dll").read_bytes()).hexdigest(),
                             result["native_sha256"])
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
            prepared = medallions.prepare(private_root, player.preparation_settings(cfg, data), roster, moved)
            mod = prepared / "Archipelago/romfs"
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
            (proof / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main(verbosity=2)
