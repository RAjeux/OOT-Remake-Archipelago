"""Held-item measurements must respect native body masks and full rotation."""
from copy import deepcopy
import importlib.util
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import audit_item_framing as audit


def track(*, translate=None, curves=()):
    return dict(base=dict(scale=[1., 1., 1.], rotate=[0., 0., 0., 1.],
                          translate=list(translate or [0., 0., 0.])),
                curves=list(curves), flags=0)


def clip(tracks, length=360):
    return dict(tracks=tracks, length=length, euler=True)


def cache_for(project, clips):
    return {("Model/" + project + ".anim.bfres.zs", name): clips.get(name)
            for name in ("Pose_Common", "Pose_Common_Longshot", "Pose_GetDemo", "Rotate_GetDemo")}


class ItemFramingTests(unittest.TestCase):
    def test_getdemo_body_wins_common_without_rotations_overwriting_its_skeleton(self):
        clips = {
            "Pose_Common": clip({"Skl_Root": track(translate=[0., 1., 0.])}),
            "Pose_GetDemo": clip({"Root": track(translate=[99., 0., 0.]),
                                   "Skl_Root": track(translate=[0., .3, 0.])}),
            "Rotate_GetDemo": clip({"Root": track(), "Skl_Root": track(translate=[0., 99., 0.])}),
        }
        original = deepcopy(clips)
        result, resolution = audit.getdemo_clips(["Native"], lambda _: self.fail("unexpected read"), cache_for("Native", clips))
        self.assertEqual([set(value["tracks"]) for value in result], [{"Skl_Root"}, {"Root"}])
        self.assertEqual(result[0]["tracks"]["Skl_Root"]["base"]["translate"], [0., .3, 0.])
        self.assertEqual([row["clip"] for row in resolution], ["Pose_GetDemo", "Rotate_GetDemo"])
        self.assertEqual(clips, original, "the source animation must remain unchanged")

    def test_common_fallback_and_longshot_are_resolved_for_the_requested_actor(self):
        clips = {"Pose_Common": clip({"Skl_Root": track(translate=[0., .2, 0.])}),
                 "Pose_Common_Longshot": clip({"Skl_Root": track(translate=[0., .7, 0.])})}
        normal, resolution = audit.getdemo_clips(["Native"], lambda _: self.fail("unexpected read"), cache_for("Native", clips))
        self.assertEqual(resolution[0]["clip"], "Pose_Common")
        self.assertEqual(normal[0]["tracks"]["Skl_Root"]["base"]["translate"][1], .2)
        longshot, resolution = audit.getdemo_clips(["Native"], lambda _: self.fail("unexpected read"),
                                                  cache_for("Native", clips), common="Pose_Common_Longshot")
        self.assertEqual(resolution[0]["clip"], "Pose_Common_Longshot")
        self.assertEqual(longshot[0]["tracks"]["Skl_Root"]["base"]["translate"][1], .7)

    def test_missing_body_animation_keeps_the_model_rest_pose(self):
        result, resolution = audit.getdemo_clips(["Native"], lambda _: self.fail("unexpected read"), cache_for("Native", {}))
        self.assertEqual((result, resolution), ([], []))
        class RestMesh:
            bones = []
            vertices = 2
            def bounds(self, pose):
                self.last_pose = pose
                return dict(min=[-.1, -.2, -.3], max=[.2, .3, .4], vertices=2)
        mesh = RestMesh()
        measured = audit.envelope(mesh, result)
        self.assertEqual(measured["samples"], 1)
        self.assertEqual(measured["min"], [-.1, -.2, -.3])
        self.assertEqual(mesh.last_pose, {})

    def test_dynamic_body_measures_fractional_frame_extremum(self):
        # Equal endpoints hide this peak when only first/last frames are used.
        motion = dict(times=[0., 1.], keys=[[0., 4.], [0., -4.]], target=20, kind=0)
        animated = clip({"Body": track(curves=[motion])}, length=1)
        class Mesh:
            bones = [dict(name="Body", scale=[1., 1., 1.], rotate=[0., 0., 0., 1.], translate=[0., 0., 0.])]
            vertices = 1
            def bounds(self, pose):
                height = pose["Body"]["translate"][1]
                return dict(min=[0., height, 0.], max=[0., height, 0.], vertices=1)
        result = audit.envelope(Mesh(), [animated])
        self.assertEqual(result["min"][1], 0.)
        self.assertAlmostEqual(result["max"][1], 1.)
        self.assertGreaterEqual(result["samples"], 3)

    @unittest.skipUnless(importlib.util.find_spec("numpy"), "requires optional maintainer NumPy")
    def test_analytic_continuous_spin_includes_off_axis_vertex_between_quarter_turns(self):
        import numpy as np
        from shop_geometry import worlds
        class Mesh:
            bones = [dict(name="Root", parent=-1, euler=True, ssc=False,
                          scale=[1., 1., 1.], rotate=[0., 0., 0., 1.], translate=[0., 0., 0.])]
            vertices = 2
            palette = np.asarray([0])
            inverse = np.asarray([])
            vertex_groups = [(np.asarray([[1., -.3, 1., 1.], [-.2, .7, 0., 1.]]), np.asarray([[0], [0]]), None)]
            def bounds(self, pose):
                transform = np.asarray(worlds(self.bones, pose)[0])
                points = (transform @ self.vertex_groups[0][0].T).T[:, :3]
                return dict(min=points.min(axis=0).tolist(), max=points.max(axis=0).tolist(), vertices=2)
        mesh = Mesh()
        mesh.np = np
        angle = dict(times=[0., 360.], keys=[[0., math.pi/180], [2*math.pi, math.pi/180]], target=36, kind=0)
        spin = clip({"Root": track(curves=[angle])})
        result = audit.envelope(mesh, [spin])
        self.assertTrue(result["analytic_full_y_rotation"])
        self.assertEqual(result["samples"], 1)
        self.assertAlmostEqual(result["max"][0], math.sqrt(2))
        self.assertAlmostEqual(result["min"][2], -math.sqrt(2))
        self.assertEqual(result["min"][1], -.3)
        self.assertEqual(result["max"][1], .7)
        # The diagonal point reaches this maximum at a fractional portion of
        # the turn, whereas 0/90/180/270-degree samples only see extent 1.
        self.assertGreater(result["max"][0], 1.4)


if __name__ == "__main__":
    unittest.main()
