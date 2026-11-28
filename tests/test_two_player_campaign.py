"""Guard the independent oracle used by the optional real two-player campaign."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
sys.path.insert(0, str(ROOT / "tests"))
spec = importlib.util.spec_from_file_location("two_player_campaign", ROOT / "tools/test_two_player_campaign.py")
campaign = importlib.util.module_from_spec(spec)
spec.loader.exec_module(campaign)


class HistoryOracleTests(unittest.TestCase):
    def test_wallet_probe_excludes_only_fixed_wallet_gifts(self):
        from test_access_logic import fixture
        from ootrr_triforce.access_logic import AccessLogic
        raw = fixture()
        raw['fixed'] = [[3, 3]]
        raw['world']['locs'][2]['rule'] = ['h', 3, 1]
        graph = AccessLogic(raw)
        self.assertIn('Shop', graph.sweep({}).reach)
        probe = campaign.wallet_capacity_probe(graph)
        self.assertNotIn('Shop', probe.sweep({}).reach)
        self.assertIn('Shop', probe.sweep({'Progressive Wallet': 1}).reach)
        self.assertEqual(graph.raw['fixed'], [[3, 3]])
        raw = fixture()
        self.assertEqual(campaign.wallet_capacity_probe(AccessLogic(raw)).raw['fixed'], raw['fixed'])

    def test_native_packet_shapes_and_duplicate_replays_preserve_one_copy(self):
        first = {"item": 12, "location": 31, "player": 2, "flags": 1}
        history = campaign.reconcile_history([], 0, [first])
        history = campaign.reconcile_history(history, 0, [[12, 31, 2, 1], [15, 33, 1, 0]])
        self.assertEqual(history, [(12, 31, 2), (15, 33, 1)])
        self.assertEqual(campaign.reconcile_history(history, 0, [first]), history)
        self.assertEqual(campaign.reconcile_history(history, 1, [[15, 33, 1, 0]]), history)

    def test_different_owners_locations_or_items_are_not_silently_overwritten(self):
        original = [(12, 31, 2)]
        for bad in ((13, 31, 2), (12, 32, 2), (12, 31, 1)):
            with self.subTest(bad=bad), self.assertRaises(AssertionError):
                campaign.reconcile_history(original, 0, [bad])
            self.assertEqual(original, [(12, 31, 2)])

    def test_index_holes_and_negative_indices_are_rejected(self):
        for index in (-1, 2, 100):
            with self.subTest(index=index), self.assertRaises(AssertionError):
                campaign.reconcile_history([(12, 31, 2)], index, [(15, 33, 1)])

    def test_distinct_checks_with_the_same_bundle_are_both_retained(self):
        # Two Bombs (20) packets represent two separate AP receipts; item-name
        # deduplication would silently lose one even though item IDs match.
        self.assertEqual(campaign.reconcile_history([], 0, [(12, 31, 2), (12, 32, 2)]),
                         [(12, 31, 2), (12, 32, 2)])

    def test_all_campaign_configurations_are_valid_current_options(self):
        from ootrr_triforce.settings import default_options, validate_options
        from test_network_generation import broad_values
        names = set()
        for name, broad, left, right in campaign.configurations():
            self.assertNotIn(name, names)
            names.add(name)
            for overrides in (left, right or left):
                with self.subTest(case=name, overrides=overrides):
                    validate_options(dict(broad_values() if broad else default_options(), **overrides))
        self.assertGreaterEqual(len(names), 16)
        self.assertIn("wallet-prices", names)


if __name__ == "__main__":
    unittest.main()
