"""The native stick shop pose must never alter the AP purchase contract."""
from pathlib import Path
import sys,unittest
from copy import deepcopy
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'client'))
from ootrr_triforce import shop_poses as poses
from oot_rando.formats import byml_codec as by
from oot_rando.formats.inspect_resources import sarc

def encode(root):return by.dump(dict(root=root,endian='<',version=7))

def fixture():
    ap='Item_AP_'+'a'*12;shelf='Shop_OOTRR_'+ap+'_5'
    actor='Actor/'+shelf+'.engine__actor__ActorParam.bgyml'
    components=dict(ActorNameRef='?ActorSystem/ActorName/'+ap+'.engine__actor__ActorName.bgyml',
        ASRef='?AS/Item_Common.root.asb',ASInfoRef='?Component/ASInfo/Item_Shop.engine__component__ASInfo.bgyml',
        PouchContentRef='?Component/PouchContentParam/'+shelf+'.game__component__PouchContentParam.bgyml',
        GameParameterTableRef='?GameParameter/GameParameterTable/'+shelf+'.engine__actor__GameParameterTable.bgyml')
    files={actor:encode(dict(Components=components)),
           'reward-identity-price-event-test':b'unchanged purchase behavior'}
    native={'Actor/'+poses.NATIVE+'.engine__actor__ActorParam.bgyml':encode(dict(Components=dict(AnimationRef='?'+poses.ANIMATION))),
            poses.ANIMATION:encode(dict(AnimationResources=[dict(ModelProjectName='Item_Common_Animation'),dict(ModelProjectName='Item_DekuStick_Animation')]))}
    return shelf,actor,files,native

class NativeShopPoseTests(unittest.TestCase):
    def test_only_native_animation_reference_and_exact_member_are_added(self):
        shelf,actor,files,native=fixture();raw=by.build_sarc(files)
        updated,growth=poses.repair_pose(raw,shelf,native);made=sarc(updated)
        self.assertGreater(growth,0)
        self.assertEqual(made[poses.ANIMATION],native[poses.ANIMATION])
        before,after=by.load(files[actor]),by.load(made[actor])
        after['root']['Components'].pop('AnimationRef')
        self.assertEqual(after,before)
        self.assertEqual(made['reward-identity-price-event-test'],files['reward-identity-price-event-test'])
        self.assertEqual(poses.repair_pose(updated,shelf,native),(updated,0))

    def test_incoherent_identity_native_pose_and_custom_existing_data_fail_closed(self):
        for fault in ('identity','native','existing','animation'):
            with self.subTest(fault=fault):
                shelf,actor,files,native=fixture()
                if fault=='native':native[poses.ANIMATION]=encode(dict(AnimationResources=[]))
                elif fault=='existing':files[poses.ANIMATION]=b'unrelated custom animation'
                else:
                    doc=by.load(files[actor]);doc['root']['Components']['ActorNameRef' if fault=='identity' else 'AnimationRef']='?Unrelated';files[actor]=by.dump(doc)
                raw=by.build_sarc(files)
                with self.assertRaises(ValueError):poses.repair_pose(raw,shelf,native)

    def test_no_relevant_display_never_opens_game_resources(self):
        self.assertEqual(poses.prepare_shop_poses('absent','absent',[]),dict(displays=0,written=0))

if __name__=='__main__':unittest.main()
