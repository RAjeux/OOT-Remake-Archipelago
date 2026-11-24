"""Current shield stock is distinct from obtained-item and AP receipt history."""
from collections import Counter
import copy
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client'))
from ootrr_full.formats import byml_codec
from ootrr_full.game import tracking_metadata as tracking
from ootrr_full.patching.soul_adapter import murmur3
from ootrr_full.tracker.auto_tracker import TrackerSession

SHIELDS = {'TBox_Shield_Deku': 'Deku Shield', 'TBox_Shield_Hylian': 'Hylian Shield',
           'Item_Shield_Mirror': 'Mirror Shield'}
OBTAINED = murmur3('IsGet.Weapon_Shield_Deku')
STOCK = murmur3('PouchData.Weapon_Shield_Deku.StockNum')


def rules():
    return {'inventory': [{'item': 'Deku Shield', 'hash': str(OBTAINED),
                           'stock_hash': str(STOCK), 'stock_type': 'int', 'count': 1}]}


class StockObservationTests(unittest.TestCase):
    def test_burnt_shield_is_absent_while_its_obtained_and_receipt_history_stays_true(self):
        snapshot = {'bool': {OBTAINED: True, 123: True}, 'int': {STOCK: 0}}
        before = copy.deepcopy(snapshot)
        counts, known = TrackerSession.observed_inventory(snapshot, rules())
        self.assertEqual(counts['Deku Shield'], 0)
        self.assertEqual(known, {'Deku Shield'})
        self.assertEqual(snapshot, before)  # Observation cannot clear/refund a receipt.

    def test_stock_overrides_all_obtained_aliases_and_uses_actual_quantity(self):
        metadata = rules()
        metadata['inventory'].append({'item': 'Deku Shield', 'hash': '234', 'count': 1})
        snapshot = {'bool': {OBTAINED: True, 234: True}, 'int': {STOCK: 0}}
        self.assertFalse(TrackerSession.observed_inventory(snapshot, metadata)[0]['Deku Shield'])
        snapshot['bool'][OBTAINED] = False
        snapshot['int'][STOCK] = 1
        self.assertEqual(TrackerSession.observed_inventory(snapshot, metadata)[0]['Deku Shield'], 1)

    def test_missing_or_invalid_stock_is_unknown_instead_of_ever_obtained(self):
        for integers in ({}, {STOCK: None}, {STOCK: -1}, {STOCK: True}, {STOCK: '1'}):
            with self.subTest(integers=integers):
                counts, known = TrackerSession.observed_inventory({'bool': {OBTAINED: True}, 'int': integers}, rules())
                self.assertNotIn('Deku Shield', known)
                self.assertFalse(counts['Deku Shield'])
        self.assertEqual(TrackerSession.observed_inventory({'bool': {OBTAINED: True}}, rules()), (Counter(), set()))

    def test_legacy_metadata_keeps_recorded_progression_semantics(self):
        metadata = {'inventory': [{'item': 'Deku Shield', 'hash': str(OBTAINED), 'count': 1}]}
        self.assertEqual(TrackerSession.observed_inventory({'bool': {OBTAINED: True}, 'int': {STOCK: 0}}, metadata),
                         (Counter({'Deku Shield': 1}), {'Deku Shield'}))

    def test_observation_labels_distinguish_readable_stock_missing_stock_and_progression(self):
        tracker = TrackerSession.__new__(TrackerSession)
        tracker._lock = threading.RLock()
        tracker.metadata = rules()
        tracker.metadata['inventory'].append({'item': 'Bow', 'hash': '456'})
        tracker._inventory = (Counter({'Bow': 1}), {'Bow', 'Deku Shield'})
        self.assertEqual(tracker.inventory_observations(),
                         {'Deku Shield': 'Observed stock', 'Bow': 'Recorded progression'})
        tracker._inventory = (Counter({'Bow': 1}), {'Bow'})
        self.assertEqual(tracker.inventory_observations()['Deku Shield'], 'Stock unavailable')

    def test_metadata_uses_only_saved_integer_stock_and_preserves_historical_hash(self):
        for kind, saved, expected in (('Int', 0, 'int'), ('UInt', 0, 'uint'), ('Int', -1, None), ('Float', 0, None)):
            with self.subTest(kind=kind, saved=saved):
                schema = {'Bool': [{'Hash': byml_codec.U32(OBTAINED), 'SaveFileIndex': 0}],
                          kind: [{'Hash': byml_codec.U32(STOCK), 'SaveFileIndex': saved}]}
                raw = byml_codec.dump({'endian': '<', 'version': 7, 'root': {'Data': schema}})
                def read(path):
                    if path == tracking.GAMEDATA:
                        return raw
                    raise FileNotFoundError(path)
                with patch.object(tracking, 'ACTOR_ITEMS', {'TBox_Shield_Deku': 'Deku Shield'}):
                    metadata = tracking.build_tracking('seed', [], {}, read)
                self.assertEqual(len(metadata['inventory']), 1)
                row = metadata['inventory'][0]
                self.assertEqual(row['hash'], str(OBTAINED))
                if expected:
                    self.assertEqual((row['stock_hash'], row['stock_type']), (str(STOCK), expected))
                else:
                    self.assertNotIn('stock_hash', row)


@unittest.skipUnless(os.environ.get('OOT_NUP'), 'OOT_NUP not set; native resources remain private')
class NativeStockMetadataTests(unittest.TestCase):
    def test_real_native_shield_pouch_stock_keys_are_saved_signed_integers(self):
        from ootrr_full.formats.inspect_nup import Nup
        from ootrr_full.game.world_maps import effective_members
        from ootrr_full.formats.inspect_resources import Byml, dictionaries, decompress
        source = Nup(os.environ['OOT_NUP'])
        try:
            members, dictionary = effective_members(source), dictionaries(source)
            def read(path):
                raw = source.read(members[path])
                return decompress(raw, dictionary) if path.endswith('.zs') else raw
            schema = Byml(read(tracking.GAMEDATA)).root['Data']
            with patch.object(tracking, 'ACTOR_ITEMS', SHIELDS):
                metadata = tracking.build_tracking('native-seed', [], {}, read)
            self.assertEqual({row['item'] for row in metadata['inventory']}, set(SHIELDS.values()))
            for row in metadata['inventory']:
                key = murmur3('PouchData.' + tracking.SHIELD_POUCH_ACTORS[row['item']] + '.StockNum')
                native = next(entry for entry in schema['Int'] if entry['Hash'] == key)
                self.assertEqual((native['SaveFileIndex'], native['DefaultValue']), (0, 0))
                self.assertEqual((row['stock_hash'], row['stock_type']), (str(key), 'int'))
        finally:
            source.stream.close()


if __name__ == '__main__':
    unittest.main()
