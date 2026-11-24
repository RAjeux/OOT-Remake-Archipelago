"""An old save consumes only the restored source's stale progressive alias."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client'))
from ootrr_triforce.full_mod import _physical_progressive_tokens, collection_records
from ootrr_triforce.catalog import ITEM_DATA, ITEM_IDS, LOCATION_IDS
from ootrr_triforce.restoration import build_restoration_flow, event_name
from ootrr_full.patching.progressive import applied_flag, got_flag
from ootrr_full.patching.soul_adapter import murmur3
from test_restoration import CHEST, SaveRun, pouch, reward

TOKEN = 'Item_Prog_BombBag_1'
OTHER = 'Item_Prog_BombBag_2'


class SourceTokenTests(unittest.TestCase):
    def inputs(self, root):
        row = {'id': 'own', 'item': 'Bomb Bag', 'reward_actor': 'Obj_Rando_' + TOKEN}
        (root / 'spoiler.json').write_text(json.dumps({'placements': [row]}), encoding='utf-8')
        data = {'full_patch': {'placements': {'own': {'own': True, 'item': 'Bomb Bag'},
                                            'foreign': {'own': False, 'item': 'Foreign'}}}}
        generated = {'skips': {'progressive': {'converter': {'tokens': [TOKEN, OTHER]}}}}
        tracking = {'checks': {'own': {'item': 'Bomb Bag', 'actor': 'Obj_Rando_' + TOKEN}}}
        saved = {murmur3(flag) for token in (TOKEN, OTHER) for flag in (applied_flag(token), got_flag(token))}
        return data, generated, tracking, saved

    def test_only_the_exact_personal_source_token_is_bound_not_other_converter_tokens(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data, generated, tracking, saved = self.inputs(root)
            result = _physical_progressive_tokens(data, root, generated, tracking, saved)
        self.assertEqual(result, {'own': {'actor': TOKEN, 'applied': applied_flag(TOKEN)}})

    def test_wrong_family_actor_or_unsaved_token_flag_is_rejected(self):
        for change in ('family', 'actor', 'flag'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                data, generated, tracking, saved = self.inputs(root)
                if change == 'family':
                    data['full_patch']['placements']['own']['item'] = 'Bow'
                elif change == 'actor':
                    tracking['checks']['own']['actor'] = 'Obj_Rando_' + OTHER
                else:
                    saved.remove(murmur3(applied_flag(TOKEN)))
                with self.assertRaisesRegex(ValueError, 'does not match'):
                    _physical_progressive_tokens(data, root, generated, tracking, saved)

    def test_direct_npc_quest_and_song_tokens_use_their_actual_actor_without_a_repeatable_wrapper(self):
        cases = (('npc#LW Skull Kid', 'Progressive Wallet', 'Item_Prog_Wallet_2'),
                 ('quest#HF Ocarina of Time Item', 'Magic Meter', 'Item_Prog_Magic_1'),
                 ('song#Sheik in Ice Cavern', 'Progressive Hookshot', 'Item_Prog_Hookshot_2'))
        from ootrr_full.patching.progressive import token_family
        for gid, family, token in cases:
            with self.subTest(gid=gid), tempfile.TemporaryDirectory() as temporary:
                # Use the engine's canonical family spelling for the real alias.
                family = token_family(token)
                root = Path(temporary)
                (root / 'spoiler.json').write_text(json.dumps({'placements': [
                    {'id': gid, 'item': family, 'actor': token}]}), encoding='utf-8')
                data = {'full_patch': {'placements': {gid: {'own': True, 'item': family}}}}
                generated = {'skips': {'progressive': {'converter': {'tokens': [token]}}}}
                tracking = {'checks': {gid: {'actor': token, 'item': family}}}
                saved = {murmur3(applied_flag(token)), murmur3(got_flag(token))}
                self.assertEqual(_physical_progressive_tokens(data, root, generated, tracking, saved),
                                 {gid: {'actor': token, 'applied': applied_flag(token)}})


class NativeRecoveryTokenTests(unittest.TestCase):
    def model(self):
        record = {'name': CHEST, 'id': LOCATION_IDS[CHEST], 'local': True, 'item': 'Bomb Bag',
                  'flags': ['Fixture.Source', 'Fixture.Chest'], 'counters': [], 'wake_talon': False,
                  'full_network': True, 'progressive_token': {'actor': TOKEN, 'applied': applied_flag(TOKEN)}}
        raw, _ = build_restoration_flow(pouch(), {CHEST: reward('Bomb Bag')}, records=[record])
        return SaveRun(raw)

    def test_missing_source_gets_one_tier_and_consumes_only_its_own_pending_token_before_save(self):
        run = self.model()
        run.inventory[TOKEN] = 1
        run.inventory[OTHER] = 1
        run.values[got_flag(TOKEN)] = True
        run.run(event_name(LOCATION_IDS[CHEST]))
        self.assertEqual(run.inventory['Item_BombBag_Small'], 1)
        self.assertEqual(run.inventory[TOKEN], 0)
        self.assertEqual(run.inventory[OTHER], 1)
        self.assertTrue(run.values[applied_flag(TOKEN)])
        self.assertNotIn(applied_flag(OTHER), run.values)
        self.assertTrue(run.saves[-1][0]['Fixture.Source'])
        self.assertTrue(run.saves[-1][0][applied_flag(TOKEN)])
        run.run(event_name(LOCATION_IDS[CHEST]))
        self.assertEqual(run.inventory['Item_BombBag_Small'], 1)
        self.assertEqual(run.inventory['Item_BombBag_Medium'], 0)

    def test_ordinary_old_save_does_not_remove_an_absent_token(self):
        run = self.model()
        run.run(event_name(LOCATION_IDS[CHEST]))
        self.assertEqual(run.inventory['Item_BombBag_Small'], 1)
        self.assertEqual(run.inventory[TOKEN], 0)
        self.assertTrue(run.values[applied_flag(TOKEN)])

    def test_already_checked_source_leaves_a_pending_token_for_the_normal_watcher(self):
        run = self.model()
        run.values['Fixture.Source'] = True
        run.inventory[TOKEN] = 1
        run.values[got_flag(TOKEN)] = True
        run.run(event_name(LOCATION_IDS[CHEST]))
        self.assertFalse(run.inventory['Item_BombBag_Small'])
        self.assertEqual(run.inventory[TOKEN], 1)
        self.assertNotIn(applied_flag(TOKEN), run.values)


@unittest.skipUnless(os.environ.get('OOT_NUP') and os.environ.get('OOT_FULL_ARTIFACT'), 'OOT_NUP/OOT_FULL_ARTIFACT not set')
class PreparedSourceTokenTests(unittest.TestCase):
    def test_actual_prepared_tokens_have_saved_flags_and_do_not_become_collection_proof(self):
        from ootrr_full.formats.inspect_nup import Nup
        from ootrr_full.formats.inspect_resources import dictionaries, decompress
        from ootrr_full.formats import byml_codec
        from ootrr_triforce.full_ap import load_catalog
        artifact = Path(os.environ['OOT_FULL_ARTIFACT'])
        data = json.loads((artifact / 'full-player.json').read_bytes())
        names = load_catalog()['locations']
        roster = {names[gid]: {'local': row['own'], 'item': row['item'] if row['own'] else None}
                  for gid, row in data['full_patch']['placements'].items()}
        nup = Nup(os.environ['OOT_NUP'])
        try:
            schema = byml_codec.load(decompress((artifact / 'romfs/GameData/GameDataList.Product.110.byml.zs').read_bytes(),
                                               dictionaries(nup)))['root']
            rows = collection_records(data, artifact, roster, schema)
        finally:
            nup.stream.close()
        tokens = [row for row in rows if row.get('progressive_token')]
        spoiler = json.loads((artifact / 'spoiler.json').read_bytes())
        from ootrr_full.patching.progressive import token_family
        physical = {}
        for row in spoiler['placements']:
            placement = data['full_patch']['placements'].get(row['id'])
            if not placement or not placement['own']:
                continue
            actor = row.get('reward_actor') or row.get('actor', '')
            for prefix in ('Obj_Rando_', 'Obj_RandoWater_', 'Shop_Rando_'):
                if actor.startswith(prefix):
                    actor = actor[len(prefix):]
                    break
            if token_family(actor):
                physical[names[row['id']]] = actor
        self.assertGreater(len(physical), 0)
        self.assertEqual({row['name']: row['progressive_token']['actor'] for row in tokens}, physical,
                         'Every personal source token must be represented, including direct event hand-overs')
        self.assertEqual(len({row['progressive_token']['actor'] for row in tokens}), len(tokens))
        for row in tokens:
            self.assertTrue(row['local'])
            self.assertNotIn(row['progressive_token']['applied'], row['flags'])
            self.assertFalse(any(flag.startswith('IsGet.Item_Prog_') for flag in row['flags']))


if __name__ == '__main__':
    unittest.main()
