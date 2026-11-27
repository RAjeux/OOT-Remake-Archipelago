"""Versioned native preparation preserves old rooms and protects AP sources."""
from pathlib import Path
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.feature_setup import prepare_features, prepare_cosmetics


class FeaturePreparationTests(unittest.TestCase):
    def room(self, **settings):
        return dict(features=dict(schema=1, settings=settings), token="a" * 64,
                    seed_file=dict(seed="AP-native-fixture", settings="OOTRR1-fixture"),
                    additional_sources=[], network_sources={})

    def test_old_rooms_never_invoke_new_native_passes(self):
        with patch("ootrr_triforce.feature_setup.run_engine") as run:
            self.assertIsNone(prepare_features("unused", "unused", {}))
            self.assertIsNone(prepare_cosmetics("unused", "unused", {}))
        run.assert_not_called()

    def test_additional_sources_cannot_skip_the_required_native_normalization(self):
        with patch("ootrr_triforce.feature_setup.run_engine") as run:
            with self.assertRaisesRegex(ValueError, "versioned feature"):
                prepare_features("unused", "unused", dict(additional_sources=["A native extra"]))
            run.assert_not_called()

    def test_protected_physical_sources_and_recipient_key_totals_reach_the_native_pass(self):
        data = self.room(dungeon_key_tracker=True)
        data["key_caps"] = [5, 8, 4, 5, 5, 2, 9, 1]
        data["network_sources"] = {"Example": {"variants": [
            dict(file="Banc/Example/Map.bcett.byml.zs", actor="18446744073709551614"),
            dict(file="Banc/Example/Map.bcett.byml.zs", actor="18446744073709551614")]}}
        with patch("ootrr_triforce.feature_setup.run_engine", return_value="prepared") as run:
            prepare_features("game", "stage", data)
        command, request, game, stage = run.call_args.args
        self.assertEqual((command, game, stage), ("features", "game", "stage"))
        self.assertEqual(request["seed"], data["seed_file"]["seed"])
        self.assertEqual(request["key_caps"], data["key_caps"])
        self.assertEqual(request["protected_sources"], {
            "Banc/Example/Map.bcett.byml.zs": ["18446744073709551614"]})

    def test_invalid_key_totals_fail_before_any_native_resource_write(self):
        data = self.room(dungeon_key_tracker=True)
        for caps in (None, [1] * 7, [True] * 8, [2**31] * 8):
            data["key_caps"] = caps
            with patch("ootrr_triforce.feature_setup.run_engine") as run:
                with self.assertRaises(ValueError):
                    prepare_features("game", "stage", data)
                run.assert_not_called()

    def test_cosmetics_retry_uses_the_same_room_seed_without_gameplay_placements(self):
        data = self.room(shuffle_music="grouped", cosmetic_color_mode="random")
        with patch("ootrr_triforce.feature_setup.run_engine", return_value="colors") as run:
            prepare_cosmetics("game", "stage", data)
            prepare_cosmetics("game", "stage", data)
        self.assertEqual(run.call_args_list[0], run.call_args_list[1])
        request = run.call_args.args[1]
        self.assertEqual(request["seed"], "AP-cosmetics-" + data["token"])
        self.assertNotIn("placements", request)


@unittest.skipUnless(os.environ.get("OOTRR_NODE") or shutil.which("node"), "requires the actual compiled WASM")
class NativeCommandBoundaryTests(unittest.TestCase):
    def test_invalid_feature_context_is_rejected_before_reading_or_writing_game_resources(self):
        from ootrr_triforce.engine import run_engine
        with tempfile.TemporaryDirectory(prefix="ap-native-guard-") as folder:
            game, mod = Path(folder) / "game", Path(folder) / "stage"
            game.mkdir(); mod.mkdir()
            request = dict(seed="AP-test", settings={}, features=dict(schema=1, settings=dict(enemy_randomizer=True)))
            with self.assertRaisesRegex(RuntimeError, "missing AP source protection context"):
                run_engine("features", request, game, mod)
            with self.assertRaisesRegex(RuntimeError, "unsupported cosmetic feature schema"):
                run_engine("cosmetics", dict(seed="AP-test", features=dict(schema=2, settings={})), game, mod)
            self.assertFalse(list(game.iterdir()))
            self.assertFalse(list(mod.iterdir()))


if __name__ == "__main__":
    unittest.main()
