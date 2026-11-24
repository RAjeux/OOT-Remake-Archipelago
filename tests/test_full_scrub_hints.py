"""Native AP offers preserve the actual sale and use final localized item names."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client'))
ROMFS = os.environ.get('OOT_ROMFS') or os.environ.get('OOTRR_ROMFS')


@unittest.skipUnless(ROMFS, 'Set OOT_ROMFS for native offer-text validation.')
class FullScrubHintsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ootrr_triforce import app_runtime
        app_runtime._resource_override = ROOT / 'dist'
        from ootrr_triforce.mod_codec import Codec
        cls.romfs = Path(ROMFS)
        cls.codec = Codec((cls.romfs / 'Pack/ZsDic.pack.zs').read_bytes())

    def read(self, path):
        return self.codec.decode((self.romfs / path).read_bytes())

    def test_english_and_french_offers_use_final_foreign_name_owner_and_price(self):
        from ootrr_triforce.full_scrub_hints import patch_messages, NAMES
        from ootrr_full.formats import byml_codec, msbt
        from ootrr_full.formats.inspect_resources import sarc
        for language, expected in (('EUen', b'I sell Bow (Friend) for 150 rupees.'),
                                   ('EUfr', b'Je vends Bow (Friend) pour 150 rubis.')):
            files = sarc(self.read('Mals/' + language + '.Product.110.sarc.zs'))
            message = msbt.load(files[NAMES])
            message.add('Item_AP_Test_Name', 'Bow (Friend)')
            files[NAMES] = msbt.dump(message)
            before = dict(files)
            raw = patch_messages(byml_codec.build_sarc(files), language,
                                  [{'names': ['Item_AP_Test'], 'label': 'APScrub_Test', 'price': 150}])
            actual = sarc(raw)
            message = msbt.load(actual[NAMES])
            self.assertTrue(message.get('APScrub_Test').startswith(expected))
            for name in files:
                if name != NAMES:
                    self.assertEqual(actual[name], before[name], name)

    def test_missing_localized_final_item_is_rejected(self):
        from ootrr_triforce.full_scrub_hints import patch_messages
        with self.assertRaisesRegex(ValueError, 'localized native pouch name'):
            patch_messages(self.read('Mals/EUen.Product.110.sarc.zs'), 'EUen',
                           [{'names': ['NoSuchItem'], 'label': 'APScrub_Test', 'price': 10}])

    def test_native_seller_payment_cancel_and_reward_arguments_remain_unchanged(self):
        from ootrr_triforce.full_scrub_hints import prepare, FLOW
        from ootrr_full.logic.rando_options import defaults
        from ootrr_full.patching.progressive import FlowEditor
        changed = {}
        paths = ['Mals/EUen.Product.110.sarc.zs', 'Mals/EUfr.Product.110.sarc.zs']
        before = FlowEditor(self.read(FLOW), 'before').chart
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory)
            (artifact / 'spoiler.json').write_text(json.dumps({'placements': [
                {'id': 'scrub#LW Deku Scrub Near Bridge', 'source': 'scrub', 'actor': 'Item_StickBag_Medium'}]}),
                encoding='utf-8')
            count = prepare(artifact, dict(defaults(), shuffle_scrubs='regular'), 'seed', paths,
                            self.read, changed.__setitem__)
        self.assertEqual(count, 1)
        after = FlowEditor(changed[FLOW], 'after').chart
        self.assertEqual(len(before.events), len(after.events))
        self.assertEqual([(entry.name, entry.main_event.v.name) for entry in before.entry_points],
                         [(entry.name, entry.main_event.v.name) for entry in after.entry_points])
        variants = {'Event322', 'Event317', 'Event555'}
        for first, second in zip(before.events, after.events):
            p = getattr(first.data, 'params', None)
            q = getattr(second.data, 'params', None)
            if p is None:
                continue
            expected = dict(p.data)
            if first.name in variants:
                self.assertTrue(q.data['SellerMessageId'].startswith('ActorMsg/PouchContent:APScrub_'))
                expected['SellerMessageId'] = q.data['SellerMessageId']
            self.assertEqual(expected, q.data, first.name)


if __name__ == '__main__':
    unittest.main()
