"""AP quantities agree with the native bundle, UI and capacity gates."""
import copy
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client'))
from ootrr_full.patching.ammo_quantities import quantity_spec, quantity_actor, build_files, alias_base
from ootrr_triforce.full_ammo import guard_flow, ARGUMENT


class QuantityTests(unittest.TestCase):
    def test_protocol_names_have_distinct_exact_actors(self):
        names = ('Bombs (5)', 'Bombs (10)', 'Bombs (20)', 'Arrows (5)', 'Arrows (10)',
                 'Arrows (30)', 'Deku Seeds (30)', 'Deku Nuts (5)', 'Deku Nuts (10)')
        self.assertEqual(len({quantity_actor(name) for name in names}), len(names))
        for name in names:
            spec = quantity_spec(name)
            self.assertEqual(spec['amount'], int(name.split('(')[1][:-1]))
            self.assertEqual(alias_base(spec['actor']), spec['base'])
        for name in ('Bombs (20) (Friend)', 'AP: Arrows (30)', 'Bomb Bag', 'Bow'):
            self.assertIsNone(quantity_actor(name))
        for name in ('Bombs (0)', 'Arrows (1000)'):
            with self.assertRaises(ValueError):
                quantity_spec(name)


@unittest.skipUnless(os.environ.get('OOT_ROMFS'), 'OOT_ROMFS not set')
class RealResourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ootrr_triforce import app_runtime
        from ootrr_triforce.mod_codec import Codec
        cls.romfs = Path(os.environ['OOT_ROMFS'])
        app_runtime._resource_override = ROOT / 'dist'
        cls.codec = Codec((cls.romfs / 'Pack/ZsDic.pack.zs').read_bytes())
        cls.items = ['Bombs (5)', 'Bombs (10)', 'Bombs (20)', 'Arrows (5)', 'Arrows (10)',
                     'Arrows (30)', 'Deku Seeds (30)', 'Deku Nuts (5)', 'Deku Nuts (10)']

    @classmethod
    def read(cls, path):
        raw = (cls.romfs / path).read_bytes()
        return cls.codec.decode(raw) if path.endswith('.zs') else raw

    def test_native_bundle_pack_and_tables_agree_without_modifying_templates(self):
        from ootrr_full.formats import byml_codec
        from ootrr_full.formats.inspect_resources import sarc
        from ootrr_full.game.item_forms import resolve_components
        from ootrr_full.patching.soul_adapter import RSDB_FILES
        before = {path: self.read(path) for path in RSDB_FILES.values()}
        changed, new = build_files(self.read, self.items)
        rows = {name: {r['__RowId']: r for r in byml_codec.load(changed[path])['root']}
                for name, path in RSDB_FILES.items()}
        for name in self.items:
            spec = quantity_spec(name)
            files = sarc(new['Pack/Actor/' + spec['actor'] + '.pack.zs'][0])
            comp = resolve_components(files, spec['actor'], byml_codec)
            pouch = byml_codec.load(files[comp['PouchContentRef'][1:]])['root']
            self.assertEqual(pouch['BundleActorNum'], spec['amount'])
            self.assertIn('/' + spec['unit'] + '.', pouch['BundleActor'])
            self.assertFalse(pouch['IsAbleToGetBagIfGet'])
            self.assertEqual(pouch['SmallBagActor'], '')
            row = rows['PouchActorInfo'][spec['actor']]
            self.assertEqual(row['BundleActorNum'], spec['amount'])
            self.assertEqual(row['BundleActor'], pouch['BundleActor'])
        for table, path in RSDB_FILES.items():
            for original in byml_codec.load(before[path])['root']:
                self.assertEqual(original, rows[table][original['__RowId']])

    def test_every_capacity_branch_preserves_native_continuation(self):
        from ootrr_full.patching.progressive import FlowEditor
        from ootrr_triforce.native_presentations import AMMO_BAGS
        raw = self.read('Event/EventFlow/GetPouchContent.bfevfl.zs')
        specs = [quantity_spec(name) for name in self.items]
        result, count = guard_flow(raw, specs, dynamic=True)
        self.assertEqual(count, 1)
        flow = FlowEditor(result, 'Proof')
        events = {e.name: e for e in flow.chart.events}
        original = events['Event0']
        def allowed(actor, bags):
            current = events['FullAmmo_Event0_Argument']
            for _ in range(100):
                if not current.name.startswith('FullAmmo_'):
                    return current is original
                d = current.data
                p = d.params.data
                if hasattr(d, 'actor_action'):
                    if d.actor_action.v.v == 'EventTriggerSetGameDataString64':
                        self.assertEqual(p['GameDataName'], ARGUMENT)
                    else:
                        self.assertEqual(d.actor_action.v.v, 'EventWait')
                        self.assertEqual(p['Frames'], 1)
                    current = d.nxt.v
                else:
                    query = d.actor_query.v.v
                    if query == 'EventQueryIsGameDataString64':
                        yes = actor == p['Value']
                    else:
                        self.assertEqual(query, 'EventQueryCheckIsGet')
                        yes = p['ActorName'] in bags
                    current = d.cases[0 if yes else 1].v
            self.fail('capacity guard loops')
        for spec in specs:
            bags = AMMO_BAGS.get(spec['unit'])
            if bags:
                self.assertFalse(allowed(spec['actor'], set()))
                for bag in bags:
                    self.assertTrue(allowed(spec['actor'], {bag}))
            else:
                self.assertTrue(allowed(spec['actor'], set()))
        self.assertTrue(allowed('Item_Hammer', set()))
        self.assertTrue(allowed('Item_AP_Friend', set()))

    def test_french_and_english_alias_messages_exist(self):
        from ootrr_full.formats.inspect_resources import sarc
        paths = ['Mals/EUfr.Product.110.sarc.zs', 'Mals/USen.Product.110.sarc.zs']
        changed, _ = build_files(self.read, ['Arrows (30)'], paths)
        for path in paths:
            archive = sarc(changed[path])
            self.assertTrue(any(quantity_actor('Arrows (30)').encode() in raw for raw in archive.values()))


if __name__ == '__main__':
    unittest.main()
