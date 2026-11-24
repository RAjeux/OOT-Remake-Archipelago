"""Real native loose-key identities and post-grant completion flags."""
from pathlib import Path
import os
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'client'))
from ootrr_full.game.loose_keys import entries
from ootrr_full.game.item_forms import form_actor
from ootrr_full.patching.repeatable_adapter import prepare_repeatables,instrument_pickup_event
from ootrr_full.randomizer.full_randomizer import _patches
from ootrr_triforce.full_ap import full_defaults,new_world


class LooseKeys(unittest.TestCase):
    def test_historical_mode_retains_its_native_sources_and_new_sources_have_distinct_ids(self):
        self.assertEqual(entries({}),{})
        old=new_world(dict(full_defaults(),full_individual_smallkeys=False),'old-loose-key-contract')
        new=new_world(full_defaults(),'new-loose-key-contract')
        added=set(new.names)-set(old.names)
        self.assertEqual(added,set(entries({'individual_smallkeys':True})))
        self.assertEqual(len(added),2)
        self.assertTrue(all(new.in_logic[gid] for gid in added))
        for gid,name in old.names.items():self.assertEqual(new.names[gid],name)

    def test_filler_pickup_uses_its_replacement_and_keeps_native_completion_flags(self):
        source=entries({'individual_smallkeys':True})
        placements=[dict(id=gid,source='freestanding',form='world',before=row['before'],
                         after=form_actor('TBox_Rupee_Blue','world'),item='Rupees (5)',
                         patches=_patches(row)) for gid,row in source.items()]
        records=prepare_repeatables({'placements':placements,'matches':source},{})
        for record in records:
            self.assertEqual(record['canonical'],'TBox_Rupee_Blue')
            self.assertEqual(record['native_flags'],source[record['id']]['native_flags'])
            self.assertEqual(record['kind'],'placed')
            self.assertEqual(record['variants'],[])


@unittest.skipUnless(os.environ.get('OOT_NUP') and os.environ.get('OOT_ROMFS'),'native game not selected')
class NativeLooseKeys(unittest.TestCase):
    def test_real_sources_and_saved_completion_schema_and_native_callback(self):
        from ootrr_triforce import app_runtime
        from ootrr_triforce.mod_codec import Codec
        from ootrr_full.formats import byml_codec
        from ootrr_full.formats.inspect_nup import Nup
        from ootrr_full.formats.inspect_resources import sarc
        from ootrr_full.game.world_maps import effective_members
        from ootrr_full.patching.soul_adapter import murmur3
        import ainb
        previous=app_runtime._resource_override;app_runtime._resource_override=ROOT/'dist'
        self.addCleanup(setattr,app_runtime,'_resource_override',previous)
        codec=Codec((Path(os.environ['OOT_ROMFS'])/'Pack/ZsDic.pack.zs').read_bytes())
        nup=Nup(os.environ['OOT_NUP']);self.addCleanup(nup.stream.close)
        members=effective_members(nup)
        def read(path):
            raw=nup.read(members[path]);return codec.decode(raw) if path.endswith('.zs') else raw
        saved={int(row['Hash']) for row in byml_codec.load(read('GameData/GameDataList.Product.110.byml.zs'))['root']['Data']['Bool']
               if row.get('SaveFileIndex')==0}
        template=sarc(read('Pack/AI.Global.Product.111.pack.zs'))['AI/PouchContent.event.root.ainb']
        for gid,row in entries({'individual_smallkeys':True}).items():
            with self.subTest(gid=gid):
                variant=row['variants'][0]
                actor=byml_codec.load(read(variant['resource']))['root']['Actors'][variant['index']]
                self.assertEqual((str(actor['Hash']),actor['Gyaml']),(row['hash'],row['before']))
                self.assertTrue(all(murmur3(flag) in saved for flag in row['native_flags']))
                binary=instrument_pickup_event(template,'Rando.Check.NativeLooseKeyTest',
                                                'NativeLooseKeyTest.event.root','TBox_Rupee_Blue',
                                                tuple(row['native_flags']))
                graph=ainb.AINB.from_binary(binary).as_dict()
                text=repr(graph)
                for flag in row['native_flags']:self.assertIn(flag,text)
                self.assertIn('Rando.Check.NativeLooseKeyTest',text)


if __name__=='__main__':unittest.main()
