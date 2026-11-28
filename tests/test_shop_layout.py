"""Shelf layout must change presentation without changing any reward contract."""
from copy import deepcopy
from pathlib import Path
import math
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce import shop_layout as layout
from ootrr_triforce.catalog import SHOP_CHECKS
from oot_rando.formats import byml_codec as by
from test_receipt_registration import IdentityCodec


def document(actors):
    return dict(root={"Actors": actors, "Unrelated": "native map data"}, endian="<", version=7)


def fixture():
    name, metadata = next((n, r) for n, r in SHOP_CHECKS.items() if r["shop"] == "KF Shop" and r["slot"] == 0)
    record = dict(metadata, name=name, actor="Item_AP_" + "a" * 12,
                  local_item="Progressive Hookshot", native_actor="Item_Hookshot")
    shelf = "Shop_OOTRR_" + record["actor"] + "_" + str(record["price"])
    items = [dict(Hash=by.U64(100 + i), Gyaml="Shop_Native_" + str(i),
                  Dynamic={"ShopItemIndex": i}, Translate=[float(i % 4), 2.0 if i < 4 else 1.0, 4.0],
                  Rotate=[0.0, 0.0, 0.0], Unrelated={"Counter": "unchanged", "Event": "native event"}) for i in range(8)]
    keeper = dict(Hash=by.U64(1), Gyaml=record["keepers"][0],
                  Links=[dict(Name="ForSale", Dst=by.U64(100 + i)) for i in range(8)])
    original = document([keeper, *items, {"WithoutHash": "native marker"}])
    staged = deepcopy(original)
    staged["root"]["Actors"][1]["Gyaml"] = shelf
    registered = dict(min=[-0.1, -0.2, -0.05], max=[0.1, 0.8, 0.05])
    profile = dict(native_bounds=registered, bounds=dict(min=[-0.1, -0.15, -0.05], max=[0.1, 0.35, 0.05]),
                   fmdb="Native_Hookshot", project="Native_Hookshot", resources=[], yaw=0)
    row = dict(ModelAabbMin=dict(zip("XYZ", registered["min"])), ModelAabbMax=dict(zip("XYZ", registered["max"])),
               FmdbName="Native_Hookshot", ModelProjectName="Native_Hookshot")
    return original, staged, record, {shelf: row}, dict(schema=1, actors={"Item_Hookshot": profile}, foreign=profile,
                                                      resources={}, shared_resources=[])


class ShopLayoutTests(unittest.TestCase):
    def test_effective_pose_bounds_control_fit_and_original_row_makes_it_idempotent(self):
        original, staged, record, rows, profiles = fixture()
        fitted, count = layout.fit_map(original, staged, [record], rows, profiles)
        self.assertEqual(count, 1)
        before, after = staged["root"]["Actors"][1], fitted["root"]["Actors"][1]
        scale = after["Scale"][0]
        self.assertAlmostEqual(scale * 0.5, layout.DISPLAY_SIZE, places=6)
        self.assertAlmostEqual(after["Translate"][1] + scale * 0.1, 2.0 + layout.DISPLAY_HEIGHT, places=6)
        self.assertEqual({k: v for k, v in before.items() if k not in ("Scale", "Translate")},
                         {k: v for k, v in after.items() if k not in ("Scale", "Translate")})
        self.assertEqual(after["Translate"][::2], before["Translate"][::2])
        self.assertEqual(fitted["root"]["Actors"][0], staged["root"]["Actors"][0])
        self.assertEqual(fitted["root"]["Actors"][2:], staged["root"]["Actors"][2:])
        self.assertEqual(layout.fit_map(original, fitted, [record], rows, profiles), (fitted, 0))
        self.assertEqual(staged["root"]["Actors"][1], before)

    def test_reviewed_facing_is_absolute_and_does_not_accumulate(self):
        original, staged, record, rows, profiles = fixture()
        profiles["actors"]["Item_Hookshot"]["yaw"] = math.pi / 2
        fitted, count = layout.fit_map(original, staged, [record], rows, profiles)
        self.assertEqual(count, 1)
        self.assertAlmostEqual(fitted["root"]["Actors"][1]["Rotate"][1], math.pi / 2, places=6)
        self.assertEqual(layout.fit_map(original, fitted, [record], rows, profiles), (fitted, 0))
        staged["root"]["Actors"][1]["Rotate"][1] = 0.3
        with self.assertRaises(ValueError):
            layout.fit_map(original, staged, [record], rows, profiles)

    def test_native_pi_euler_representations_are_upright_but_true_tilts_are_not(self):
        original, staged, record, rows, profiles = fixture()
        for doc in (original, staged):
            doc["root"]["Actors"][1]["Rotate"] = [math.pi, 1.1, -math.pi]
        self.assertEqual(layout.fit_map(original, staged, [record], rows, profiles)[1], 1)
        for doc in (original, staged):
            doc["root"]["Actors"][1]["Rotate"] = [0.1, 0, 0]
        with self.assertRaises(ValueError):layout.fit_map(original, staged, [record], rows, profiles)

    def test_reviewed_local_tilt_composes_native_pi_alias_and_refits_vertical_bounds(self):
        original,staged,record,rows,profiles=fixture()
        profile=profiles["actors"]["Item_Hookshot"]
        profile["bounds"]=dict(min=[-.15,-.02,-.7],max=[.15,.02,.7])
        profile["rotation"]=[math.pi/4,math.pi/2,0]
        for doc in (original,staged):doc["root"]["Actors"][1]["Rotate"]=[math.pi,1.1,-math.pi]
        result,count=layout.fit_map(original,staged,[record],rows,profiles)
        self.assertEqual(count,1)
        actor=result["root"]["Actors"][1]
        native_matrix=layout._rotation(original["root"]["Actors"][1]["Rotate"])
        local=layout._rotation(profile["rotation"])
        expected=[[sum(native_matrix[i][k]*local[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
        actual=layout._rotation(actor["Rotate"])
        for a,b in zip(sum(actual,[]),sum(expected,[])):self.assertAlmostEqual(a,b,places=6)
        low,high=layout._oriented_bounds(*layout._bounds(profile["bounds"]),local)
        self.assertAlmostEqual(actor["Translate"][1]+actor["Scale"][0]*(low[1]+high[1])/2,2+layout.DISPLAY_HEIGHT,places=6)
        self.assertGreater((high[1]-low[1])*actor["Scale"][0],.2)
        encoded=by.load(by.dump(result))
        self.assertEqual(layout.fit_map(original,encoded,[record],rows,profiles),(encoded,0))

    def test_euler_conversion_preserves_singular_and_regular_reviewed_orientations(self):
        for x,y,z in ((.7,math.pi/2,.5),(.7,-math.pi/2,.5),(.7,.6,-.4),(-math.pi,1.1,math.pi)):
            expected=layout._rotation([x,y,z]);actual=layout._rotation(layout._angles(expected))
            for a,b in zip(sum(actual,[]),sum(expected,[])):self.assertAlmostEqual(a,b,places=6)

    def test_unknown_geometry_and_unreviewed_native_model_fail_closed(self):
        for mutation in ("bounds", "project", "fmdb", "profile"):
            with self.subTest(mutation=mutation):
                original, staged, record, rows, profiles = fixture()
                row = next(iter(rows.values()))
                if mutation == "bounds": row["ModelAabbMin"]["X"] = -2.0
                elif mutation == "profile": profiles["actors"].clear()
                else: row["ModelProjectName" if mutation == "project" else "FmdbName"] = "Unreviewed"
                with self.assertRaises(ValueError): layout.fit_map(original, staged, [record], rows, profiles)

    def test_shelves_are_bound_to_native_keeper_slot_and_unchanged_horizontal_position(self):
        for mutation in ("keeper", "slot", "x", "duplicate", "grid"):
            with self.subTest(mutation=mutation):
                original, staged, record, rows, profiles = fixture()
                if mutation == "keeper": original["root"]["Actors"][0]["Gyaml"] = "Unrelated NPC"
                elif mutation == "slot": record["slot"] = 5
                elif mutation == "x": staged["root"]["Actors"][1]["Translate"][0] += 1
                elif mutation == "duplicate": original["root"]["Actors"].append(deepcopy(original["root"]["Actors"][1]))
                else: original["root"]["Actors"][0]["Links"].pop()
                with self.assertRaises(ValueError): layout.fit_map(original, staged, [record], rows, profiles)

    def test_invalid_and_extreme_bounds_never_write_nonfinite_transforms(self):
        original, staged, record, rows, profiles = fixture()
        for bounds in (dict(min=[0, 0, 0], max=[0, 0, 0]), dict(min=[0, 0, 0], max=[float("nan"), 1, 1]),
                       dict(min=[1, 1, 1], max=[0, 0, 0]), dict(min=[0, 0, 0], max=[1e-44] * 3)):
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                layout.fit_transform(staged["root"]["Actors"][1], original["root"]["Actors"][1], 2.0, dict(bounds=bounds))

    def test_tight_native_rows_cap_off_center_radial_extent_without_moving_xz(self):
        original, staged, record, rows, profiles = fixture()
        for doc in (original, staged):
            for i, actor in enumerate(doc["root"]["Actors"][1:9]):
                actor["Translate"][0] = (i % 4) * 0.5528
        profile = profiles["actors"]["Item_Hookshot"]
        profile["bounds"] = dict(min=[0.4, -0.1, 0.1], max=[1.4, 0.5, 0.2])
        result, count = layout.fit_map(original, staged, [record], rows, profiles)
        target = result["root"]["Actors"][1]
        self.assertEqual(count, 1)
        radius = math.hypot(1.4, 0.2) * target["Scale"][0]
        self.assertLessEqual(radius, 0.5528 / 2 - layout.SHELF_MARGIN + 1e-7)
        self.assertEqual(target["Translate"][::2], staged["root"]["Actors"][1]["Translate"][::2])
        self.assertEqual(layout.fit_map(original, result, [record], rows, profiles), (result, 0))

    def test_foreign_tokens_use_their_own_reviewed_profile_without_becoming_local(self):
        original, staged, record, rows, profiles = fixture()
        record.pop("local_item"); record.pop("native_actor")
        profiles["actors"].clear()
        profiles["foreign"].update(preserve_native=True, horizontal_radius=0.19)
        result, count = layout.fit_map(original, staged, [record], rows, profiles)
        self.assertEqual(count, 0)
        self.assertEqual(result, staged)
        self.assertEqual(result["root"]["Actors"][1]["Gyaml"], staged["root"]["Actors"][1]["Gyaml"])
        self.assertNotIn("local_item", record)

    def test_empty_selection_does_not_open_game_resources(self):
        with patch("ootrr_triforce.mod_codec.Codec", side_effect=AssertionError("unexpected codec")):
            self.assertEqual(layout.prepare_shop_layout("absent", "absent", []), {"displays": 0, "written": 0})

    def test_geometry_hashes_prevent_using_profiles_with_changed_native_resources(self):
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = "Model/NativeModel.NativeModel.bfres.zs"
            target = root / path; target.parent.mkdir(); target.write_bytes(b"reviewed mesh")
            document = dict(resources={path: hashlib.sha256(b"reviewed mesh").hexdigest()}, shared_resources=[])
            layout.verify_resources(document, [dict(resources=[path])], root, IdentityCodec(b"fixture"))
            target.write_bytes(b"changed native mesh")
            with self.assertRaises(ValueError):layout.verify_resources(document, [dict(resources=[path])], root, IdentityCodec(b"fixture"))
            with self.assertRaises(ValueError):layout.verify_resources(document, [dict(resources=["../unrelated"])], root, IdentityCodec(b"fixture"))

    def test_preserved_foreign_reference_requires_exact_staged_mesh_and_animation(self):
        import hashlib
        from oot_rando.patching import ap_item
        actor = "Item_AP_" + "b" * 12
        shelf = "Shop_OOTRR_" + actor + "_10"
        model = "Component/ModelInfo/AP.engine__component__ModelInfo.bgyml"
        animation = "Component/AnimationParam/Item_AP_Spin.engine__component__AnimationParam.bgyml"
        def encode(root):return by.dump(dict(root=root,endian="<",version=7))
        files = {"Actor/"+shelf+".engine__actor__ActorParam.bgyml":encode({"Components":{
            "ModelInfoRef":"?"+model,"AnimationRef":"?"+animation,
            "ASRef":"?AS/Item_Common.root.asb",
            "ASInfoRef":"?Component/ASInfo/Item_Shop.engine__component__ASInfo.bgyml"}}),
            model:encode(ap_item.MODEL_INFO),animation:encode({"AnimationResources":[{"ModelProjectName":ap_item.SPIN_ANIMATION}]})}
        resources={ap_item.NEW_MODEL_FILE:b"reviewed AP mesh","Pack/Actor/"+shelf+".pack.zs":by.build_sarc(files)}
        document=dict(foreign=dict(preserve_native=True,stage_model_sha256=hashlib.sha256(b"reviewed AP mesh").hexdigest()))
        record=dict(actor=actor,price=10)
        layout.verify_foreign_displays(document,[record],resources.__getitem__)
        resources[ap_item.NEW_MODEL_FILE]=b"changed AP mesh"
        with self.assertRaises(ValueError):layout.verify_foreign_displays(document,[record],resources.__getitem__)
        resources[ap_item.NEW_MODEL_FILE]=b"reviewed AP mesh"
        files[animation]=encode({"AnimationResources":[{"ModelProjectName":"Unreviewed animation"}]})
        resources["Pack/Actor/"+shelf+".pack.zs"]=by.build_sarc(files)
        with self.assertRaises(ValueError):layout.verify_foreign_displays(document,[record],resources.__getitem__)

    def test_stage_validates_every_map_before_writing_and_never_changes_other_resources(self):
        original, staged, record, rows, profiles = fixture()
        with tempfile.TemporaryDirectory() as folder:
            game, mod = Path(folder)/"game", Path(folder)/"mods/Archipelago/romfs"
            def write(home, path, raw):
                target=home/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
            write(game,"Pack/ZsDic.pack.zs",b"identity codec")
            for path in record["bancs"]:
                write(game,path,by.dump(original));write(mod,path,by.dump(staged))
            write(mod,layout.ACTORS,by.dump(dict(root=list(dict(row,__RowId=name) for name,row in rows.items()),endian="<",version=7)))
            # Real RST format: two Banc names use exact-size native records.
            body=b"RESTBL"+struct.pack("<IIII",1,160,2,0)
            for path in sorted(record["bancs"]): body+=struct.pack("<II",zlib.crc32(path.removesuffix(".zs").encode()),10000)
            write(mod,layout.REST,body)
            write(mod,"Pack/Actor/unchanged.pack.zs",b"grant identity and animation stay unchanged")
            bad=deepcopy(staged);bad["root"]["Actors"][0]["Gyaml"]="Unknown owner"
            # Corrupt the immutable native map, not the expected staged alias.
            write(game,record["bancs"][-1],by.dump(bad))
            before={p.relative_to(mod):p.read_bytes() for p in mod.rglob('*') if p.is_file()}
            with patch("ootrr_triforce.mod_codec.Codec",IdentityCodec),patch.object(layout,"profiles",return_value=profiles):
                with self.assertRaises(ValueError):layout.prepare_shop_layout(game,mod,[record])
            self.assertEqual(before,{p.relative_to(mod):p.read_bytes() for p in mod.rglob('*') if p.is_file()})
            # After restoring the native anchor, the same public preparation
            # must touch only shelf placements and their allocation table.
            write(game,record["bancs"][-1],by.dump(original))
            with patch("ootrr_triforce.mod_codec.Codec",IdentityCodec),patch.object(layout,"profiles",return_value=profiles):
                result=layout.prepare_shop_layout(game,mod,[record])
                self.assertEqual(result,{"displays":len(record["bancs"]),"written":len(record["bancs"])+1})
                fitted={p.relative_to(mod):p.read_bytes() for p in mod.rglob('*') if p.is_file()}
                self.assertEqual({path for path in before if before[path]!=fitted[path]},
                                 {Path(path) for path in (*record["bancs"],layout.REST)})
                self.assertEqual(layout.prepare_shop_layout(game,mod,[record]),{"displays":0,"written":0})
            self.assertEqual(fitted,{p.relative_to(mod):p.read_bytes() for p in mod.rglob('*') if p.is_file()})


if __name__ == "__main__": unittest.main()
