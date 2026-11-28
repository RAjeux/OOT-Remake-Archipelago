"""Private constructor substitutions never become AP placements or wrong chest guards."""
import copy
import json
from contextlib import ExitStack
from pathlib import Path
import sys
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce import network_catalog, player
from ootrr_triforce.catalog import CHESTS, EXPECTED

PREFIX = "error: this seed places key items at pickup spots out of upgrade tier order, generate it again with this build: "
DIAGNOSTIC = PREFIX + "LH Freestanding PoH hands out Item_Quiver_Large (Bow tier 3) but the player can reach it holding 2 other copies or fewer\n"


class PortableConstructionTests(unittest.TestCase):
    def fixture(self):
        donor = "KF Midos Top Left Chest"
        seed = dict(checksum="canonical", placements={donor: "Rupees (5)", "LH Freestanding PoH": "Bow"})
        data = dict(seed_file=seed, network_sources_schema=2, local_items=True,
                    reward_mode="all_locations", adult_trade_shuffle=True,
                    moved={donor: "Rupees (5)", "LH Freestanding PoH": "Bow"})
        derived = copy.deepcopy(seed)
        derived.update(checksum="constructor", placements={donor: "Bow", "LH Freestanding PoH": "Rupees (5)"})
        swaps = [dict(source="LH Freestanding PoH", donor=donor, item="Bow", filler="Rupees (5)")]
        return data, derived, swaps

    def test_bound_sources_and_original_seed_are_sent_to_constructor_without_rewriting_room(self):
        data, derived, swaps = self.fixture()
        original = copy.deepcopy(data)
        sources = {"LH Freestanding PoH": {}, "KF Midos Top Left Chest": {}}
        with patch.object(network_catalog, "validate_sources", return_value=sources) as validate, \
                patch.object(player, "run_engine", return_value=json.dumps(dict(seed_file=derived, swaps=swaps))) as run:
            actual = player.construction_seed(data, ["LH Freestanding PoH"])
        self.assertEqual(actual, (derived, swaps))
        self.assertEqual(data, original)
        validate.assert_called_once_with(data)
        run.assert_called_once_with("portable-seed", dict(seed_file=data["seed_file"], ap_sources=sorted(sources),
                                                         project_sources=["LH Freestanding PoH"]))

    def test_ap_donor_chest_guard_uses_actual_constructor_reward_and_canonical_mapping_is_intact(self):
        data, derived, _ = self.fixture()
        original = copy.deepcopy(data)
        actual = player.patch_request(data, construction=derived)
        baseline = player.patch_request(data)
        expected = {ref["actor"] for ref in CHESTS["KF Midos Top Left Chest"]}
        for requests in actual["files"].values():
            for request in requests:
                self.assertIn(request["actor"], expected)
                self.assertEqual(request["expected"], EXPECTED["Bow"])
                self.assertEqual(request["drop"], "TBox_Rupee_Green")
        self.assertTrue(actual["files"])
        self.assertTrue(all(request["expected"] == EXPECTED["Rupees (5)"]
                            for rows in baseline["files"].values() for request in rows))
        self.assertEqual(data, original)

    def test_invalid_network_metadata_cannot_enable_constructor_substitutions(self):
        data, _, _ = self.fixture()
        with patch.object(network_catalog, "validate_sources", side_effect=ValueError("invalid source")), \
                patch.object(player, "run_engine") as run:
            with self.assertRaisesRegex(ValueError, "invalid source"):
                player.construction_seed(data, ["LH Freestanding PoH"])
            run.assert_not_called()

    def test_only_the_exact_portable_diagnostic_for_a_selected_physical_ap_source_authorizes_retry(self):
        data, _, _ = self.fixture()
        selected = {"LH Freestanding PoH": dict(kind="pickup"), "KF Midos Top Left Chest": dict(kind="chest")}
        with patch.object(network_catalog, "validate_sources", return_value=selected):
            error = lambda text: subprocess.CalledProcessError(1, ["ootrr", "build"], stderr=text)
            expected = {"LH Freestanding PoH": "Item_Quiver_Large"}
            self.assertEqual(player.constructor_tier_sources(data, error(DIAGNOSTIC)), expected)
            self.assertEqual(player.constructor_tier_sources(data, error(DIAGNOSTIC.encode())), expected)
            for text in ("file not found", DIAGNOSTIC.replace("LH Freestanding PoH", "Not an AP source"),
                         DIAGNOSTIC.replace("LH Freestanding PoH", "KF Midos Top Left Chest"),
                         DIAGNOSTIC + "an unrelated error\n", DIAGNOSTIC.replace("tier 3", "invalid tier")):
                self.assertEqual(player.constructor_tier_sources(data, error(text)), {})

    def test_valid_modern_rooms_use_the_original_constructor_input_without_speculative_swaps(self):
        data, _, _ = self.fixture()
        with patch.object(player, "run_engine", return_value='{"checksum":"trade-base"}') as run:
            self.assertEqual(player.construction_seed(data), (dict(checksum="trade-base"), []))
            run.assert_called_once_with("base-seed", dict(seed_file=data["seed_file"]))

    def test_failed_constructor_attempt_is_never_reused_or_published(self):
        data, derived, swaps = self.fixture()
        data["network_sources"] = {"LH Freestanding PoH": {}}
        original = copy.deepcopy(data)
        with tempfile.TemporaryDirectory() as directory, ExitStack() as scope:
            root = Path(directory)
            romfs = root / "game"
            (romfs / "Pack").mkdir(parents=True)
            (romfs / "Pack/ZsDic.pack.zs").write_bytes(b"dictionary")
            paths = []
            def construct(arguments, **kwargs):
                stage = Path(arguments[4])
                paths.append(stage)
                mod = stage / "Archipelago/romfs"
                mod.mkdir(parents=True)
                if len(paths) == 1:
                    (mod / "incomplete.bin").write_bytes(b"must never be installed")
                    raise subprocess.CalledProcessError(1, arguments, stderr=DIAGNOSTIC)
                self.assertFalse((mod / "incomplete.bin").exists())
                (mod / "complete.bin").write_bytes(b"complete")
                return SimpleNamespace(stdout="", stderr="")
            scope.enter_context(patch.object(player, "construction_seed", side_effect=[(data["seed_file"], []), (derived, swaps)]))
            scope.enter_context(patch.object(player, "constructor_tier_sources", return_value={"LH Freestanding PoH": "Item_Quiver_Large"}))
            scope.enter_context(patch.object(player, "run_process", side_effect=construct))
            engine = scope.enter_context(patch.object(player, "run_engine", return_value="prepared"))
            scope.enter_context(patch.object(player, "write_title"))
            scope.enter_context(patch.object(network_catalog, "validate_sources", return_value=data["network_sources"]))
            for target in ("builder.validate_builder", "story_fixes.prepare_story_fixes", "quest_fixes.prepare_quest_fixes",
                           "fortress_fixes.prepare_fortress_fixes", "feature_setup.prepare_features",
                           "feature_setup.prepare_cosmetics", "native_setup.prepare_chest_flags", "shop_hours.prepare_shop_hours",
                           "trade_state.prepare_trade_state", "receipt_events.prepare_receipts", "dungeon_messages.prepare_messages"):
                scope.enter_context(patch("ootrr_triforce." + target))
            player.build(root / "cache", dict(ootrr="ootrr", romfs=str(romfs)), data)
            installed = root / "cache/mods/Archipelago"
            self.assertEqual((installed / "romfs/complete.bin").read_bytes(), b"complete")
            self.assertFalse((installed / "romfs/incomplete.bin").exists())
            self.assertEqual(len(paths), 2)
            self.assertNotEqual(paths[0], paths[1])
            calls = engine.call_args_list
            self.assertEqual([call.args[0] for call in calls], ["portable-geometry", "network-flow-base", "patch"])
            self.assertEqual(calls[0].args[1]["project_sources"], ["LH Freestanding PoH"])
            self.assertEqual(calls[0].args[1]["portable_tiers"], {"LH Freestanding PoH": "Item_Quiver_Large"})
            patch_data = calls[-1].args[1]
            self.assertTrue(all(row["expected"] == EXPECTED["Bow"] for rows in patch_data["files"].values() for row in rows))
            provenance = json.loads((installed / ".ootrr-ap-construction.json").read_bytes())
            self.assertEqual(provenance, dict(schema=1, canonical_checksum="canonical", constructor_checksum="constructor", swaps=swaps,
                                             portable_tiers={"LH Freestanding PoH": "Item_Quiver_Large"}))
        self.assertEqual(data, original)

    def test_legacy_and_non_local_modes_keep_their_original_preparation_contract(self):
        data, _, _ = self.fixture()
        for values in (dict(network_sources_schema=None), dict(local_items=False), dict(reward_mode="all_chest_rewards")):
            old = dict(data, **values)
            with self.subTest(values=values), patch.object(player, "run_engine", return_value='{"checksum":"trade-base"}') as run:
                seed, swaps = player.construction_seed(old)
                self.assertEqual((seed, swaps), (dict(checksum="trade-base"), []))
                run.assert_called_once_with("base-seed", dict(seed_file=old["seed_file"]))
        plain = dict(seed_file=data["seed_file"])
        with patch.object(player, "run_engine") as run:
            self.assertEqual(player.construction_seed(plain), (plain["seed_file"], []))
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
