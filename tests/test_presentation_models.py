"""Held models use native AS; the real item remains the only inventory reward."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.catalog import ITEM_DATA, ITEM_IDS
from ootrr_triforce.native_presentations import CAMERA_FACING_FLOW, PRESENTER_NAME
from ootrr_triforce.presentation_models import (SHOW_ACTOR_ARGUMENT, TABLES, model_actor,
                                               chest_model_actor, needs_model_alias, prepare_presentation_models,
                                               validate_chest_models)
from ootrr_triforce.receipt_events import build_presented_receipts, event_name
from oot_rando.patching.progressive import FlowEditor
from test_key_presentations import real_model_presenter
from test_presented_receipts import SceneRun, TOKEN, native_facing_animation
from test_receipt_events import native_flow


class PresentationModelTests(unittest.TestCase):
    def test_alias_is_applied_only_to_model_and_all_progressive_tiers_keep_actual_reward(self):
        names = ["Ocarina", "Bolero of Fire", "Forest Medallion", "Kokiri Emerald", "Master Sword",
                 "Small Key (Forest Temple)", "Bow"]
        pouch, presented, _ = build_presented_receipts(native_flow(), real_model_presenter(), TOKEN, names)
        charts = {name: FlowEditor(raw, name).chart for name, raw in (
            ("GetPouchContent", pouch), (PRESENTER_NAME, presented),
            (CAMERA_FACING_FLOW, native_facing_animation()))}
        for name in names:
            metadata = ITEM_DATA[name]
            tiers = metadata.get("tiers", [metadata["actor"]])
            owned = set()
            for actor in tiers:
                with self.subTest(item=name, actor=actor):
                    run = SceneRun(charts, owned=owned)
                    run.run("GetPouchContent", event_name(ITEM_IDS[name]))
                    models = [params["Actor"] for action, params in run.trace
                              if action == "EventCreateShowItemFromActorFileName"]
                    self.assertEqual(models, [model_actor(actor)])
                    self.assertEqual([params["ActorName"] for action, params in run.trace
                                      if action == "FixtureItemWindow"], [actor])
                    self.assertEqual([params["ContentName"] for flow, entry, params in run.calls
                                      if flow == CAMERA_FACING_FLOW], [actor])
                    self.assertNotIn(model_actor(actor), [params["Actor"] for action, params in run.trace
                                                         if action == "EventTriggerAddOrRemovePouchContent"]
                                     if needs_model_alias(metadata) else [])

    def test_model_aliases_are_frozen_distinct_and_unrelated_items_unchanged(self):
        actors = {actor for row in ITEM_DATA.values() for actor in row.get("tiers", [row["actor"]])}
        changed = {actor: model_actor(actor) for actor in actors if model_actor(actor) != actor}
        self.assertEqual(len(changed), 26)  # 25 incompatible models plus the known dungeon key.
        self.assertEqual(len(set(changed.values())), len(changed))
        self.assertEqual(model_actor("Item_Medal_Light"), "Item_Medal_Light_ImportantMenu")
        self.assertEqual(model_actor("Item_Stone_Forest"), "Item_Stone_Forest_ImportantMenu")
        self.assertEqual(model_actor("Item_Dungeon_SmallKey"), "Obj_MiniGame_SmallKey")
        self.assertEqual(model_actor("Item_Hookshot"), "Item_Hookshot")
        self.assertEqual(chest_model_actor("Item_Dungeon_SmallKey"), "Obj_MiniGame_SmallKey")
        self.assertEqual(chest_model_actor("Item_Hookshot"), "Item_Hookshot")
        self.assertTrue(chest_model_actor("Item_Medal_Fire").startswith("Item_AP_Chest_"))
        self.assertNotEqual(chest_model_actor("Item_Melody_FireBolero"), model_actor("Item_Melody_FireBolero"))

    def test_shop_and_world_pickups_only_change_their_chest_guest(self):
        actors = {actor for row in ITEM_DATA.values() for actor in row.get("tiers", [row["actor"]])}
        proxies = {actor: chest_model_actor(actor) for actor in actors
                   if chest_model_actor(actor).startswith("Item_AP_Chest_")}
        self.assertEqual(len(proxies), 70)
        for actor in ("Shop_DekuStick", "Shop_Bottle_Bug", "Shop_ArrowBundle_03", "Item_DekuStick",
                      "Item_Bomb", "Obj_Heart_Piece", "Obj_Fairy", "Item_Sword_Giant"):
            with self.subTest(actor=actor):
                self.assertIn(actor, proxies)
                self.assertEqual(model_actor(actor), actor, "ordinary receipt actors must remain native")
                self.assertNotEqual(proxies[actor], actor)
        self.assertEqual(chest_model_actor("Obj_MiniGame_SmallKey"), "Obj_MiniGame_SmallKey")

    def test_model_validation_checks_the_native_performer_and_actual_mesh(self):
        from oot_rando.formats import byml_codec
        actor = "Shop_DekuStick"
        guest = chest_model_actor(actor)
        encode = lambda root: byml_codec.dump({"endian": "<", "version": 7, "root": root})
        performer = "Component/EventPerformerParam/PouchContent.engine__component__EventPerformerParam.bgyml"
        pouch = "Component/PouchContentParam/KeyItemDefault.game__component__PouchContentParam.bgyml"
        model = "Component/ModelInfo/" + guest + ".engine__component__ModelInfo.bgyml"
        animation = "Component/AnimationParam/Item_AP_Spin.engine__component__AnimationParam.bgyml"
        settings = "Component/ASInfo/Item_GetDemo.engine__component__ASInfo.bgyml"
        param = "Actor/" + guest + ".engine__actor__ActorParam.bgyml"
        actor_pack = "Pack/Actor/" + guest + ".pack.zs"
        mesh = "Model/Item_DekuStick.Item_DekuStick.bfres.zs"
        pack = {
            param: encode({"Components": {
                "ActorNameRef": "?ActorSystem/ActorName/" + guest + ".engine__actor__ActorName.bgyml",
                "EventPerformerRef": "?" + performer, "PouchContentRef": "?" + pouch,
                "PhysicsRef": "?Component/Physics/Dummy.engine__component__PhysicsParam.bgyml",
                "ModelInfoRef": "?" + model, "AnimationRef": "?" + animation, "ASInfoRef": "?" + settings,
                "ASRef": "?AS/Item_Common.root.asb"}}),
            performer: encode({"EventUniqueAin": "Work/AI/Root/Event/PouchContent.event.root.ain", "UseEventUniqueAin": True}),
            pouch: encode({}), settings: encode({}),
            model: encode({"ModelProjectName": "Item_DekuStick", "FmdbName": "Item_DekuStick"}),
            animation: encode({"AnimationResources": [{"ModelProjectName": "Item_Common_Animation"}]}),
        }
        resources = {
            actor_pack: byml_codec.build_sarc(pack),
            TABLES["ActorInfo"]: encode([{"__RowId": guest, "ActorName": guest,
                                         "ModelProjectName": "Item_DekuStick", "FmdbName": "Item_DekuStick"}]),
            TABLES["GameActorInfo"]: encode([{"__RowId": guest}]),
            TABLES["PouchActorInfo"]: encode([{"__RowId": "Item_Medal_Forest", "BundleActorNum": 1},
                                              {"__RowId": guest, "BundleActorNum": 1}]),
            mesh: b"FRES_fixture_Item_DekuStick\0",
            "Model/Item_Common_Animation.anim.bfres.zs": b"FRES_fixture_animation",
            "AS/Item_Common.root.asb.zs": b"ASB_fixture_Rotate_GetDemo\0",
        }
        with patch("ootrr_triforce.catalog.ITEM_DATA", {"fixture": {"actor": actor}}):
            self.assertEqual(validate_chest_models(resources.__getitem__), {"actors": 1, "guests": 1, "proxies": 1})
            resources[mesh] = b"FRES_present_but_no_selected_mesh\0"
            with self.assertRaisesRegex(ValueError, "model mesh is missing"):
                validate_chest_models(resources.__getitem__)
            resources[mesh] = b"FRES_fixture_Item_DekuStick\0"
            broken = dict(pack)
            broken[param] = encode({"Components": {"ActorNameRef": "?ActorSystem/ActorName/" + guest + ".engine__actor__ActorName.bgyml"}})
            resources[actor_pack] = byml_codec.build_sarc(broken)
            with self.assertRaisesRegex(ValueError, "no pouch event performer"):
                validate_chest_models(resources.__getitem__)


@unittest.skipUnless(os.environ.get("OOTRR_ROMFS"), "requires native v1.1.1 resources")
class NativePresentationModelTests(unittest.TestCase):
    def test_every_alias_has_getdemo_model_and_original_resources_remain_untouched(self):
        import struct
        import zlib
        from ootrr_triforce import app_runtime
        from ootrr_triforce.mod_codec import Codec
        from oot_rando.formats import byml_codec
        from oot_rando.formats.inspect_resources import sarc
        from oot_rando.game.resource_allocations import allocation
        from ootrr_triforce.presentation_models import REST, TEMPLATE, _model_path
        game = Path(os.environ["OOTRR_ROMFS"])
        with tempfile.TemporaryDirectory(prefix="ootrr-presentation-models-") as tmp, patch.object(
                app_runtime, "_resource_override", Path(os.environ["OOTRR_CODEC_RESOURCES"])):
            mod = Path(tmp) / "mods/Archipelago/romfs"
            result = prepare_presentation_models(game, mod)
            self.assertEqual(result, {"models": 16, "chest_models": 70, "written": 90})
            snapshot = {p.relative_to(mod).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in mod.rglob("*") if p.is_file()}
            self.assertEqual(prepare_presentation_models(game, mod), {"models": 16, "chest_models": 70, "written": 0})
            self.assertEqual(snapshot, {p.relative_to(mod).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                        for p in mod.rglob("*") if p.is_file()})
            self.assertFalse((mod / "GameData").exists())
            self.assertFalse((mod / "Mals").exists())
            codec = Codec((game / "Pack/ZsDic.pack.zs").read_bytes())
            native_rest = codec.decode((game / REST).read_bytes())
            effective_rest = codec.decode((mod / REST).read_bytes())
            def read(path):
                staged = mod / path
                return codec.decode((staged if staged.is_file() else game / path).read_bytes())
            self.assertEqual(validate_chest_models(read), {"actors": 167, "guests": 166, "proxies": 70})
            actors = {actor for row in ITEM_DATA.values() for actor in row.get("tiers", [row["actor"]])}
            aliases = {actor: model_actor(actor) for actor in actors if model_actor(actor) != actor}
            for actor, alias in aliases.items():
                with self.subTest(actor=actor, alias=alias):
                    rel = Path("Pack/Actor/" + alias + ".pack.zs")
                    path = mod / rel if (mod / rel).is_file() else game / rel
                    pack = sarc(codec.decode(path.read_bytes()))
                    root = byml_codec.load(pack["Actor/" + alias + ".engine__actor__ActorParam.bgyml"])["root"]
                    components = dict(root["Components"])
                    while root.get("$parent"):
                        parent = root["$parent"].removeprefix("Work/").removesuffix(".gyml") + ".bgyml"
                        root = byml_codec.load(pack[parent])["root"]
                        components = {**root.get("Components", {}), **components}
                    if alias.startswith("Item_AP_Show_"):
                        self.assertNotIn("PouchContentRef", components)
                        self.assertNotIn("EventPerformerRef", components)
                        self.assertIn("Item_GetDemo", components["ASInfoRef"])
                        animation = byml_codec.load(pack[components["AnimationRef"][1:]])["root"]
                        self.assertEqual(animation["AnimationResources"], [{"ModelProjectName": "Item_Common_Animation"}])
                    as_file = components["ASRef"][1:] + ".zs"
                    self.assertIn(b"Rotate_GetDemo", codec.decode((game / as_file).read_bytes()))
            chest_aliases = {chest_model_actor(actor) for actor in actors
                             if chest_model_actor(actor).startswith("Item_AP_Chest_")}
            generated = [(actor, model_actor(actor)) for actor in actors
                         if model_actor(actor).startswith("Item_AP_Show_")]
            generated.extend((actor, chest_model_actor(actor)) for actor in actors
                             if chest_model_actor(actor).startswith("Item_AP_Chest_"))
            for actual, alias in generated:
                with self.subTest(inner_allocation=alias):
                    actor_path = "Actor/" + alias + ".engine__actor__ActorParam.bgyml"
                    self.assertGreaterEqual(allocation(effective_rest, actor_path), allocation(native_rest,
                        "Actor/" + TEMPLATE + ".engine__actor__ActorParam.bgyml"))
                    donor = "Dm_Item_Sheik_Harp" if actual.startswith("Item_Melody_") else actual
                    native_pack = sarc(codec.decode((game / ("Pack/Actor/" + donor + ".pack.zs")).read_bytes()))
                    peer = _model_path(native_pack, donor, byml_codec)
                    self.assertGreaterEqual(allocation(effective_rest,
                        "Component/ModelInfo/" + alias + ".engine__component__ModelInfo.bgyml"),
                        allocation(native_rest, peer))
            spin = "Component/AnimationParam/Item_AP_Spin.engine__component__AnimationParam.bgyml"
            self.assertGreaterEqual(allocation(effective_rest, spin), allocation(native_rest,
                "Component/AnimationParam/Item_Wallet_Medium.engine__component__AnimationParam.bgyml"))
            template = sarc(codec.decode((game / "Pack/Actor/Item_Medal_Forest.pack.zs").read_bytes()))
            for alias in chest_aliases:
                pack = sarc(codec.decode((mod / ("Pack/Actor/" + alias + ".pack.zs")).read_bytes()))
                root = byml_codec.load(pack["Actor/" + alias + ".engine__actor__ActorParam.bgyml"])["root"]
                self.assertEqual(root["$parent"], "Work/Actor/Item_EventObject_Base.engine__actor__ActorParam.gyml")
                self.assertEqual(root["Components"]["PouchContentRef"],
                                 "?Component/PouchContentParam/KeyItemDefault.game__component__PouchContentParam.bgyml")
                # Retain the exact same native pouch guest binding as the AP
                # medallion chest actor; add no custom get-event/AI component.
                for path in ("Actor/Item_EventObject_Base.engine__actor__ActorParam.bgyml",
                             "Component/EventPerformerParam/PouchContent.engine__component__EventPerformerParam.bgyml",
                             "Component/PouchContentParam/KeyItemDefault.game__component__PouchContentParam.bgyml"):
                    self.assertEqual(pack[path], template[path])
                self.assertNotIn("EventPerformerRef", root["Components"])
                self.assertEqual(root["Components"]["ASRef"], "?AS/Item_Common.root.asb")
            for table, path in TABLES.items():
                old = byml_codec.load(codec.decode((game / path).read_bytes()))["root"]
                new = byml_codec.load(codec.decode((mod / path).read_bytes()))["root"]
                by_id = {row["__RowId"]: row for row in new}
                self.assertEqual(len(new), len(old) + (70 if table == "PouchActorInfo" else 86))
                self.assertTrue(all(by_id[row["__RowId"]] == row for row in old))
                if table == "PouchActorInfo":
                    native = next(row for row in old if row["__RowId"] == "Item_Medal_Forest")
                    for alias in chest_aliases:
                        self.assertEqual(by_id[alias], dict(native, __RowId=alias))

            # Upgrade a complete previous stage whose packs and registry rows
            # exist, but whose inner components have no resource allocation.
            missing = {spin, "Actor/" + chest_model_actor("Shop_DekuStick") + ".engine__actor__ActorParam.bgyml"}
            digests = {zlib.crc32(path.encode()) for path in missing}
            version, block, count, named = struct.unpack_from("<IIII", effective_rest, 6)
            entries = [struct.unpack_from("<II", effective_rest, 22 + i * 8) for i in range(count)]
            kept = [entry for entry in entries if entry[0] not in digests]
            self.assertEqual(len(entries) - len(kept), len(missing))
            legacy = (effective_rest[:6] + struct.pack("<IIII", version, block, len(kept), named)
                      + b"".join(struct.pack("<II", *entry) for entry in kept) + effective_rest[22 + count * 8:])
            original_frame = (mod / REST).read_bytes()
            (mod / REST).write_bytes(codec.encode(legacy, original_frame))
            self.assertEqual(prepare_presentation_models(game, mod), {"models": 16, "chest_models": 70, "written": 1})
            self.assertEqual(snapshot, {p.relative_to(mod).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                        for p in mod.rglob("*") if p.is_file()})


if __name__ == "__main__":
    unittest.main()
