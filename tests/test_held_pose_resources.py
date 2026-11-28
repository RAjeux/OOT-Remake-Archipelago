"""Held aliases retain authored native body poses without actor behavior."""
import copy
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from oot_rando.formats import byml_codec as by
from oot_rando.formats.inspect_resources import sarc
from ootrr_triforce import presentation_models as models


class HeldPoseResourceTests(unittest.TestCase):
    @staticmethod
    def pack(*, graph="Item_Common", projects=None):
        encode = lambda root: by.dump({"endian": "<", "version": 7, "root": root})
        source = "Component/AnimationParam/Fixture.engine__component__AnimationParam.bgyml"
        projects = projects if projects is not None else ["Item_Common_Animation", "Fixture_Animation"]
        return {
            "Actor/Fixture.engine__actor__ActorParam.bgyml": encode({"Components": {
                "ASRef": "?AS/" + graph + ".root.asb", "AnimationRef": "?" + source,
                "AIInfoRef": "?AI/World.bgyml", "PouchContentRef": "?Pouch/World.bgyml"}}),
            source: encode({"AnimationResources": [{"ModelProjectName": name} for name in projects]})}

    def test_native_body_poses_are_retained_under_an_isolated_alias_component(self):
        pack = self.pack()
        original = copy.deepcopy(pack)
        result = models._held_pose(pack, "Fixture", "Item_AP_Show_fixture", by)
        self.assertEqual(pack, original)
        self.assertEqual(result["path"],
            "Component/AnimationParam/Item_AP_Show_fixture.engine__component__AnimationParam.bgyml")
        self.assertEqual(result["data"], result["peer_data"])
        self.assertEqual(by.load(result["data"])["root"], result["info"])
        self.assertEqual(result["info"]["AnimationResources"], [
            {"ModelProjectName": "Item_Common_Animation"}, {"ModelProjectName": "Fixture_Animation"}])
        self.assertEqual(set(result), {"path", "data", "peer", "peer_data", "info"})

    def test_world_weapon_graphs_are_not_lent_to_held_aliases(self):
        for graph in ("Weapon_Sword_070", "LiftableExplodeObject_BallBomb", "Dummy"):
            with self.subTest(graph=graph):
                self.assertIsNone(models._held_pose(self.pack(graph=graph), "Fixture", "Item_AP_Show_fixture", by))

    def test_a_native_rotation_without_body_pose_keeps_the_established_spin_component(self):
        self.assertIsNone(models._held_pose(self.pack(projects=["Item_Common_Animation"]),
                                           "Fixture", "Item_AP_Show_fixture", by))
        self.assertIsNone(models._held_pose(self.pack(projects=["Fixture_Animation"]),
                                           "Fixture", "Item_AP_Show_fixture", by))

    def test_malformed_resource_metadata_does_not_produce_a_partial_pose(self):
        pack = self.pack()
        source = "Component/AnimationParam/Fixture.engine__component__AnimationParam.bgyml"
        for resources in ([{"ModelProjectName": ""}], [{"ModelProjectName": 12}], "Fixture_Animation"):
            with self.subTest(resources=resources):
                pack[source] = by.dump({"endian": "<", "version": 7, "root": {"AnimationResources": resources}})
                with self.assertRaisesRegex(ValueError, "animation resources are invalid"):
                    models._held_pose(pack, "Fixture", "Item_AP_Show_fixture", by)

    @staticmethod
    def offset_pack(actor, offset=None, *, parent=False):
        encode = lambda root: by.dump({"endian": "<", "version": 7, "root": root})
        source = "Component/PouchContentParam/" + actor + ".game__component__PouchContentParam.bgyml"
        document = {"Category": 123, "GetType": 456, "SpecialDeal": 789}
        if offset is not None:
            document["GetDemoOffsetPos"] = dict(zip("XYZ", offset))
        document["$parent"] = "Work/Component/PouchContentParam/Default.game__component__PouchContentParam.gyml"
        pack = {
            "Actor/" + actor + ".engine__actor__ActorParam.bgyml": encode({"Components": {"PouchContentRef": "?" + source}}),
            source: encode(document)}
        if parent:
            inherited = "Component/PouchContentParam/Parent.game__component__PouchContentParam.bgyml"
            pack[inherited] = pack[source]
            pack[source] = encode({"$parent": "Work/" + inherited.removesuffix(".bgyml") + ".gyml"})
        return pack

    def test_native_offset_resolves_parent_and_missing_engine_default_zero(self):
        for inherited in (False, True):
            self.assertEqual(models._get_demo_offset(self.offset_pack("Fixture", [0, 0.25, 0], parent=inherited),
                                                    "Fixture", by), [0.0, 0.25, 0.0])
        self.assertEqual(models._get_demo_offset(self.offset_pack("Fixture"), "Fixture", by), [0.0, 0.0, 0.0])

    def test_chest_contract_changes_only_native_display_offset(self):
        template = self.offset_pack("Template", [0, 0.2, 0])
        actual = self.offset_pack("Actual", [0, 0.375, 0])
        original_template, original_actual = copy.deepcopy(template), copy.deepcopy(actual)
        result = models._chest_offset(template, "Template", actual, "Actual", "Item_AP_Chest_fixture", by)
        before, after = by.load(result["peer_data"]), by.load(result["data"])
        self.assertEqual(after["root"].pop("GetDemoOffsetPos"), {"X": 0.0, "Y": 0.375, "Z": 0.0})
        before["root"].pop("GetDemoOffsetPos")
        self.assertEqual(before, after)
        self.assertEqual(template, original_template)
        self.assertEqual(actual, original_actual)
        self.assertIsNone(models._chest_offset(template, "Template", template, "Template", "Item_AP_Chest_fixture", by))

    def test_invalid_or_incomplete_pouch_offset_is_rejected(self):
        pack = self.offset_pack("Fixture")
        path = "Component/PouchContentParam/Fixture.game__component__PouchContentParam.bgyml"
        for value in ({"X": 0.0, "Y": 0.2}, {"X": 0.0, "Y": float("nan"), "Z": 0.0}):
            with self.subTest(value=value):
                pack[path] = by.dump({"endian": "<", "version": 7, "root": {"GetDemoOffsetPos": value}})
                with self.assertRaisesRegex(ValueError, "display offset is invalid"):
                    models._get_demo_offset(pack, "Fixture", by)

    def test_master_pose_rejects_unknown_native_binary_before_interpreting_offsets(self):
        with self.assertRaisesRegex(ValueError, "Unsupported native Master Sword presentation pose"):
            models._master_pose_bytes(b"FRES_unrecognized_data")

    def test_master_pose_component_is_only_animation_metadata(self):
        pose = models._master_pose_parts("Item_AP_Show_fixture", "native-peer", b"native", by)
        self.assertEqual(set(by.load(pose["data"])["root"]), {"AnimationResources"})
        self.assertEqual(pose["info"]["AnimationResources"], [
            {"ModelProjectName": "Item_Common_Animation"}, {"ModelProjectName": models.MASTER_POSE_PROJECT}])

    def test_bow_family_uses_separate_generic_visuals_and_uniform_display_offsets(self):
        actors = {"Item_Range_Bow": [0, 0.4, 0], "Item_Quiver_Medium": [0, 0.2, 0],
                  "Item_Quiver_Large": [0, 0.2, 0], "Other": [0, 0.35, 0]}
        resources = {"Pack/Actor/" + actor + ".pack.zs": by.build_sarc(self.offset_pack(actor, offset))
                     for actor, offset in actors.items()}
        original = dict(resources)
        native = models.native_get_demo_offsets(resources.__getitem__, actors)
        visual = models.held_model_offsets(resources.__getitem__, actors)
        self.assertAlmostEqual(native["Item_Range_Bow"][1], 0.4)
        self.assertAlmostEqual(visual["Item_Range_Bow"][1], 0.2)
        for actor in models.BOW_FAMILY:
            self.assertEqual(visual[actor], [0.0, models.BOW_DISPLAY_OFFSET, 0.0])
            self.assertTrue(models.model_actor(actor).startswith("Item_AP_Show_"))
            self.assertTrue(models.chest_model_actor(actor).startswith("Item_AP_Chest_"))
        self.assertEqual(visual["Other"], native["Other"])
        self.assertEqual(resources, original)

    def test_bow_pose_rejects_unknown_native_binary(self):
        with self.assertRaisesRegex(ValueError, "Unsupported native Bow presentation pose"):
            models._bow_pose_bytes(b"FRES_unrecognized_data")


@unittest.skipUnless(os.environ.get("OOTRR_ROMFS"), "requires native v1.1.1 resources")
class NativeHeldPoseResourceTests(unittest.TestCase):
    def test_bow_profile_keeps_native_rotations_and_weapon_clips_with_a_bounded_body(self):
        import struct
        from ootrr_triforce import app_runtime
        from ootrr_triforce.mod_codec import Codec
        sys.path.insert(0, str(ROOT / "tools"))
        from shop_geometry import PreparedMesh, Reader
        from shop_pose_animation import animation, pose_at
        game = Path(os.environ["OOTRR_ROMFS"])
        with patch.object(app_runtime, "_resource_override", Path(os.environ["OOTRR_CODEC_RESOURCES"])):
            codec = Codec((game / "Pack/ZsDic.pack.zs").read_bytes())
            raw = codec.decode((game / models.BOW_POSE_SOURCE).read_bytes())
            new = models._bow_pose_bytes(raw)
            self.assertEqual(len(raw), len(new))
            reader = Reader(raw)
            offset, clips = raw.find(b"FSKA"), {}
            while offset >= 0:
                clips[reader.text(reader.u64(offset + 8))] = offset
                offset = raw.find(b"FSKA", offset + 1)
            pose = clips["Pose_Common"]
            tracks = reader.u64(pose + 40)
            permitted = set()
            for index in range(reader.u16(pose + 76)):
                track = tracks + index * 56
                name, base = reader.text(reader.u64(track)), reader.u64(track + 16)
                if name == "Root":
                    continue
                permitted.update(range(base, base + 12))
                permitted.update(range(track + 40, track + 44))
                if name == "Skl_Root":
                    permitted.update(range(base + 28, base + 40))
                self.assertEqual(raw[base + 12:base + 28], new[base + 12:base + 28], name)
                old_flags, new_flags = reader.u32(track + 40), struct.unpack_from("<I", new, track + 40)[0]
                self.assertEqual(old_flags & (1 << 23), new_flags & (1 << 23), "retain segment compensation")
            changed = {index for index, (a, b) in enumerate(zip(raw, new)) if a != b}
            self.assertTrue(changed)
            self.assertLessEqual(changed, permitted)
            for name in clips.keys() - {"Pose_Common"}:
                self.assertEqual(animation(raw, name), animation(new, name), name)
            mesh = PreparedMesh(codec.decode((game / models.BOW_MODEL_PATH).read_bytes()))
            body = animation(new, "Pose_Common")
            body["tracks"].pop("Root")
            bounds = mesh.bounds(pose_at(body, 0, {bone["name"]: bone for bone in mesh.bones}))
            self.assertAlmostEqual(bounds["max"][1] - bounds["min"][1], 0.60, places=6)
            self.assertAlmostEqual((bounds["max"][1] + bounds["min"][1]) / 2, 0.0, places=6)

    def test_every_explicit_pose_lender_uses_the_same_native_mesh_and_get_graph(self):
        from ootrr_triforce import app_runtime
        from ootrr_triforce.mod_codec import Codec
        game = Path(os.environ["OOTRR_ROMFS"])
        with patch.object(app_runtime, "_resource_override", Path(os.environ["OOTRR_CODEC_RESOURCES"])):
            codec = Codec((game / "Pack/ZsDic.pack.zs").read_bytes())
            for actual, lender in models.POSE_LENDERS.items():
                with self.subTest(actual=actual, lender=lender):
                    packs = {actor: sarc(codec.decode((game / ("Pack/Actor/" + actor + ".pack.zs")).read_bytes()))
                             for actor in (actual, lender)}
                    native, shown = (models._model(packs[actor], actor, by)["root"] for actor in (actual, lender))
                    self.assertEqual((native["ModelProjectName"], native["FmdbName"]),
                                     (shown["ModelProjectName"], shown["FmdbName"]))
                    pose = models._held_pose(packs[lender], lender, models.chest_model_actor(actual), by)
                    self.assertIsNotNone(pose)
                    self.assertEqual(pose["data"], packs[lender][pose["peer"]])
                    self.assertIn({"ModelProjectName": "Item_Common_Animation"}, pose["info"]["AnimationResources"])
                    self.assertGreater(len(pose["info"]["AnimationResources"]), 1)

    def test_master_pose_changes_only_static_body_transform_and_translation_zero_flag(self):
        import struct
        from ootrr_triforce import app_runtime
        from ootrr_triforce.mod_codec import Codec
        game = Path(os.environ["OOTRR_ROMFS"])
        with patch.object(app_runtime, "_resource_override", Path(os.environ["OOTRR_CODEC_RESOURCES"])):
            codec = Codec((game / "Pack/ZsDic.pack.zs").read_bytes())
            raw = codec.decode((game / models.MASTER_POSE_SOURCE).read_bytes())
            new = models._master_pose_bytes(raw)
            self.assertEqual(len(new), len(raw))
            u64 = lambda offset: struct.unpack_from("<Q", raw, offset)[0]
            def text(offset):
                count = struct.unpack_from("<H", raw, offset)[0]
                return raw[offset + 2:offset + 2 + count].decode("utf-8")
            tracks = u64(raw.index(b"FSKA") + 40)
            bone = next(tracks + 56 * index for index in range(2) if text(u64(tracks + 56 * index)) == "Skl_Root")
            base = u64(bone + 16)
            changed = {index for index, (before, after) in enumerate(zip(raw, new)) if before != after}
            self.assertTrue(changed)
            self.assertLessEqual(changed, set(range(base, base + 12)) | set(range(base + 28, base + 40))
                                 | set(range(bone + 40, bone + 44)))
            before_flags, after_flags = (struct.unpack_from("<I", value, bone + 40)[0] for value in (raw, new))
            self.assertEqual(before_flags ^ after_flags, 1 << 27)
            self.assertFalse(after_flags & (1 << 27), "nonzero center cannot use the native TranslateZero shortcut")
            self.assertAlmostEqual(struct.unpack_from("<f", new, base)[0], models.MASTER_POSE_SCALE, places=6)
            self.assertEqual(raw[base + 12:base + 28], new[base + 12:base + 28], "keep native sword orientation")
            self.assertEqual(hashlib.sha256(codec.decode((game / models.MASTER_MODEL_PATH).read_bytes())).hexdigest(),
                             models.MASTER_MODEL_SHA256)

    def test_exact_old_aliases_upgrade_once_and_unknown_overrides_remain_untouched(self):
        from ootrr_triforce import app_runtime
        from ootrr_triforce.catalog import ITEM_DATA
        from ootrr_triforce.mod_codec import Codec
        from oot_rando.game.resource_allocations import allocation
        game = Path(os.environ["OOTRR_ROMFS"])
        codec = None
        with tempfile.TemporaryDirectory(prefix="ootrr-held-body-poses-") as tmp, patch.object(
                app_runtime, "_resource_override", Path(os.environ["OOTRR_CODEC_RESOURCES"])):
            mod = Path(tmp) / "romfs"
            codec = Codec((game / "Pack/ZsDic.pack.zs").read_bytes())
            # Reproduce the exact public alpha13 packages and actor rows.
            with patch.object(models, "_held_pose", return_value=None), patch.object(
                    models, "_chest_offset", return_value=None), patch.object(models, "_master_pose_parts", return_value=None), patch.object(
                    models, "_bow_pose_parts", return_value=None):
                models.prepare_presentation_models(game, mod)
            original = {p.relative_to(mod).as_posix(): p.read_bytes() for p in mod.rglob("*") if p.is_file()}
            self.assertGreater(models.prepare_presentation_models(game, mod)["written"], 0)
            upgraded = {p.relative_to(mod).as_posix(): p.read_bytes() for p in mod.rglob("*") if p.is_file()}
            self.assertEqual(models.prepare_presentation_models(game, mod)["written"], 0)
            self.assertEqual(upgraded, {p.relative_to(mod).as_posix(): p.read_bytes() for p in mod.rglob("*") if p.is_file()})
            def read(path):
                target = mod / path
                return codec.decode((target if target.is_file() else game / path).read_bytes())
            infos = {row["__RowId"]: row for row in by.load(read(models.TABLES["ActorInfo"]))["root"]}
            rest = read(models.REST)
            checked = 0
            actors = {actor for row in ITEM_DATA.values() for actor in row.get("tiers", [row["actor"]])}
            for actor in sorted(actors):
                for alias in {models.model_actor(actor), models.chest_model_actor(actor)}:
                    if not alias.startswith(("Item_AP_Show_", "Item_AP_Chest_")):
                        continue
                    donor = "Dm_Item_Sheik_Harp" if actor.startswith("Item_Melody_") else actor
                    lender = models.POSE_LENDERS.get(actor, donor)
                    native = sarc(codec.decode((game / ("Pack/Actor/" + lender + ".pack.zs")).read_bytes()))
                    pose = models._held_pose(native, lender, alias, by)
                    if actor == "Item_Range_Bow":
                        spin = sarc(codec.decode((game / "Pack/Actor/Item_Wallet_Medium.pack.zs").read_bytes()))
                        peer = "Component/AnimationParam/Item_Wallet_Medium.engine__component__AnimationParam.bgyml"
                        pose = models._bow_pose_parts(alias, peer, spin[peer], by)
                    if pose is None:
                        continue
                    checked += 1
                    path = "Pack/Actor/" + alias + ".pack.zs"
                    self.assertNotEqual(upgraded[path], original[path])
                    pack = sarc(read(path))
                    components = models._visual_root(pack, "Actor/" + alias + ".engine__actor__ActorParam.bgyml", by)["root"]["Components"]
                    self.assertEqual(components["AnimationRef"], "?" + pose["path"])
                    self.assertEqual(pack[pose["path"]], pose["data"])
                    self.assertEqual(infos[alias]["AnimationResources"], pose["info"]["AnimationResources"])
                    self.assertGreaterEqual(allocation(rest, pose["path"]), allocation(rest, pose["peer"]))
                    if alias.startswith("Item_AP_Show_"):
                        self.assertNotIn("PouchContentRef", components)
                        self.assertNotIn("EventPerformerRef", components)
            self.assertGreater(checked, 20)
            # An unrecognized package is rejected before publishing changes.
            path = "Pack/Actor/" + models.chest_model_actor("Shop_DekuStick") + ".pack.zs"
            pack = sarc(read(path))
            pack["UnknownOverride.bin"] = b"preserve third-party customization"
            (mod / path).write_bytes(codec.encode(by.build_sarc(pack), (mod / path).read_bytes()))
            snapshot = {p.relative_to(mod).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in mod.rglob("*") if p.is_file()}
            with self.assertRaisesRegex(ValueError, "Incompatible existing presentation model"):
                models.prepare_presentation_models(game, mod)
            self.assertEqual(snapshot, {p.relative_to(mod).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                        for p in mod.rglob("*") if p.is_file()})


if __name__ == "__main__":
    unittest.main()
