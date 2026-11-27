"""Exercise remake access predicates from the actual packaged Rust engine."""
from collections import Counter
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.access_logic import AccessLogic, Ctx, ev, key_caps
from ootrr_triforce.engine import run_engine
from ootrr_triforce.settings import engine_settings
from ootrr_triforce.network_catalog import validate_sources


class NativeAccessGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generated = json.loads(run_engine("generate", dict(seed="AP-ACCESS-REGRESSION",
            settings=engine_settings(dict(shuffle_rewards="supported", shuffle_ocarinas=True,
                                          shuffle_songs="anywhere")),
            features=dict(schema=1, settings={}))))
        cls.sources = validate_sources(cls.generated)
        cls.access = AccessLogic(cls.generated["access_logic"])

    def test_memory_game_uses_native_child_ocarina_without_unshuffled_n64_buttons(self):
        access = self.access
        w = access.world
        names = access.routes["LW Ocarina Memory Game"]
        counts = [0] * len(w.items)
        counts[w.item_ix["Ocarina"]] = 1
        self.assertTrue(any(ev(w.loc_rule[l], Ctx(counts, 1, 0, w.loc_region[l], None)) for l in names))
        self.assertFalse(any(ev(w.loc_rule[l], Ctx(counts, 0, 0, w.loc_region[l], None)) for l in names))
        counts[w.item_ix["Ocarina"]] = 0
        self.assertFalse(any(ev(w.loc_rule[l], Ctx(counts, 1, 0, w.loc_region[l], None)) for l in names))
        self.assertIn("LW Ocarina Memory Game", access.sweep({"Ocarina": 1}).reach)

    def test_every_declared_new_source_has_an_exact_rule_and_owned_item_pool(self):
        self.assertEqual(self.generated["network_sources_schema"], 2)
        additions = self.generated["additional_sources"]
        self.assertTrue(additions)
        self.assertTrue(set(additions) <= self.sources.keys())
        held = Counter(row["generated_item"] for row in self.sources.values())
        result = self.access.sweep(held)
        self.assertTrue(result.won)
        self.assertFalse(set(self.sources) - result.reach)
        self.assertFalse(set(additions) & self.generated["seed_file"]["placements"].keys())

    def test_rolled_key_totals_use_the_remake_layout_and_include_all_owned_keys(self):
        pool = (row["generated_item"] for row in self.sources.values())
        self.assertEqual(key_caps(self.access.raw, pool), [5, 8, 4, 5, 5, 2, 9, 1])


if __name__ == "__main__":
    unittest.main()
