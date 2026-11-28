"""Maintainer pose calculations must follow native v10.4 skin/curve semantics."""
from pathlib import Path
import math
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from shop_geometry import Reader, worlds, point, skin_influences
from shop_pose_animation import curve, evaluate, resolve_shop_clip
from generate_shop_layout_profiles import measure


class ShopPoseMeasurementTests(unittest.TestCase):
    def test_declared_seven_skin_influences_exclude_nonzero_eighth_padding(self):
        # Native golden-gauntlet FVTX: seven weights sum1; padding is another
        # full1 at bone1. Including it invents a 50% blend into the wrong bone.
        ids=[29,40,44,44,44,29,29,1]
        weights=[102/255,3/255,150/255,0,0,0,0,1]
        selected,active=skin_influences(ids,weights,7)
        self.assertEqual(selected,ids[:7])
        self.assertAlmostEqual(sum(active),1)
        self.assertEqual(active,weights[:7])
        self.assertNotIn(1,selected)
        bone_y={29:2,40:2,44:2,1:-1}
        self.assertAlmostEqual(sum(bone_y[i]*w for i,w in zip(selected,active)),2)
        self.assertEqual(skin_influences([0,1,99,99],[.25,.75,1,0],2),([0,1],[.25,.75]))
    def test_native_stopped_body_retains_resolved_shop_pose_and_root_mask(self):
        def clip(value):return dict(length=1,euler=True,tracks={name:dict(base=dict(translate=[value,0,0]),curves=[],flags=0) for name in ('Root','Skl_Root')})
        common,shop,stopped=clip(10),clip(20),clip(30)
        available=dict(Pose_Common=common,Pose_Shop=shop)
        name,held=resolve_shop_clip(available,'Pose_Stoped')
        self.assertEqual(name,'Pose_Shop')
        self.assertEqual(set(held['tracks']),{'Skl_Root'})
        self.assertEqual(held['tracks']['Skl_Root']['base']['translate'],[20,0,0])
        available.pop('Pose_Shop')
        self.assertEqual(resolve_shop_clip(available,'Pose_Shop')[0],'Pose_Common')
        self.assertEqual(resolve_shop_clip(available,'Pose_Stoped')[0],'Pose_Common')
        available.update(Pose_Shop=shop,Pose_Stoped=stopped,Rotate_Stoped=common)
        name,held=resolve_shop_clip(available,'Pose_Stoped')
        self.assertEqual(name,'Pose_Stoped')
        self.assertEqual(held['tracks']['Skl_Root']['base']['translate'],[30,0,0])
        self.assertEqual(set(resolve_shop_clip(available,'Rotate_Stoped')[1]['tracks']),{'Root'})
        self.assertEqual(set(stopped['tracks']),{'Root','Skl_Root'})
    def test_v104_quantized_hermite_uses_unsigned_pairs_and_tangent_header(self):
        raw = bytearray(512)
        raw[:4] = b"FRES"; raw[8:12] = bytes.fromhex("00040a00")
        struct.pack_into("<QQHHI5f", raw, 32, 200, 224, 0x4806, 2, 16,
                         1.0, 3.0, 0.0, 0.01, -0.5)
        raw[200:202] = bytes((1, 3))
        struct.pack_into("<2f4H", raw, 224, 0.001, -0.25, 60000, 30000, 50000, 20000)
        parsed = curve(Reader(bytes(raw)), 32)
        self.assertAlmostEqual(evaluate(parsed, 1), 599.5, places=4)
        self.assertAlmostEqual(evaluate(parsed, 3), 499.5, places=4)
        self.assertAlmostEqual(evaluate(parsed, 2), 552.0, places=4)
        self.assertAlmostEqual(evaluate(parsed, -10), 599.5, places=4)
        self.assertAlmostEqual(evaluate(parsed, 100), 499.5, places=4)

    def test_maya_segment_compensation_preserves_parent_scaled_translation(self):
        bones = [dict(name="Root", parent=-1, euler=True, scale=[2, 3, 4], rotate=[0, 0, 0, 1], translate=[0, 0, 0]),
                 dict(name="Child", parent=0, euler=True, ssc=True, scale=[1, 1, 1], rotate=[0, 0, 0, 1], translate=[1, 0, 0])]
        self.assertEqual(point(worlds(bones)[1], [1, 1, 1]), [3, 1, 1])
        bones[1]["ssc"] = False
        self.assertEqual(point(worlds(bones)[1], [1, 1, 1]), [4, 3, 4])

    def test_segment_compensation_handles_rotated_child_and_nonuniform_scale(self):
        bones = [dict(name="Root", parent=-1, euler=True, scale=[2, 3, 4], rotate=[0, 0, 0, 1], translate=[0, 0, 0]),
                 dict(name="Child", parent=0, euler=True, ssc=True, scale=[1, 1, 1], rotate=[0, 0, math.pi / 2, 1], translate=[1, 0, 0])]
        measured = point(worlds(bones)[1], [1, 0, 0])
        for actual, expected in zip(measured, [2, 1, 0]):self.assertAlmostEqual(actual, expected, places=10)

    def test_compensation_rejects_singular_parent_scale_instead_of_invalid_bounds(self):
        bones = [dict(name="Root", parent=-1, euler=True, scale=[0, 1, 1], rotate=[0, 0, 0, 1], translate=[0, 0, 0]),
                 dict(name="Child", parent=0, euler=True, ssc=True, scale=[1, 1, 1], rotate=[0, 0, 0, 1], translate=[0, 0, 0])]
        with self.assertRaises(ValueError):worlds(bones)

    def test_applied_body_pose_uses_posed_vertices_and_missing_animation_uses_rest(self):
        class Mesh:
            bones=[dict(name="Root",scale=[1,1,1],rotate=[0,0,0,1],translate=[0,0,0])]
            vertices=3
            def bounds(self,pose):
                return dict(min=[-2,-.1,-.1],max=[2,.1,.1]) if not pose else dict(min=[-.1,-.1,-.1],max=[.1,.1,.1])
        clip=dict(length=1,euler=True,tracks={"Root":dict(base={},curves=[],flags=0)})
        result=measure(Mesh(),[clip])
        self.assertEqual(result["bounds"],dict(min=[-.1,-.1,-.1],max=[.1,.1,.1]))
        self.assertEqual(result["rest_bounds"],dict(min=[-2,-.1,-.1],max=[2,.1,.1]))
        self.assertEqual(result["frame_zero"],dict(min=[-.1,-.1,-.1],max=[.1,.1,.1]))
        self.assertEqual(measure(Mesh(),[])["bounds"],result["rest_bounds"])

    def test_authored_shop_alternative_is_unioned_without_blending_common_tracks(self):
        class Mesh:
            bones=[dict(name="Root",scale=[1,1,1],rotate=[0,0,0,1],translate=[0,0,0])]
            vertices=3
            def bounds(self,pose):
                shift=pose.get("Root",{}).get("translate",[0,0,0])[0]
                return dict(min=[shift-.1,-.1,-.1],max=[shift+.1,.1,.1])
        def clip(x):return dict(length=1,euler=True,tracks={"Root":dict(base={"translate":[x,0,0]},curves=[],flags=0)})
        result=measure(Mesh(),[clip(-2)],[[clip(3)]])
        self.assertEqual(result["bounds"],dict(min=[-2.1,-.1,-.1],max=[3.1,.1,.1]))
        self.assertEqual(result["sampling"]["samples"],2)


if __name__ == "__main__": unittest.main()
