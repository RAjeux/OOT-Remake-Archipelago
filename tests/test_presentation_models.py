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
                                               validate_chest_models, receipt_model_aliases,
                                               prepare_receipt_model_aliases)
from ootrr_triforce.receipt_events import build_presented_receipts, event_name
from oot_rando.patching.progressive import FlowEditor
from test_key_presentations import real_model_presenter
from test_presented_receipts import SceneRun, TOKEN, CURSOR, native_facing_animation
from test_receipt_events import native_flow


class PresentationModelTests(unittest.TestCase):
    @staticmethod
    def dungeon_receipt_fixture(*, legacy=False):
        names = [name for name, row in ITEM_DATA.items()
                 if row["actor"].startswith(("Item_Medal_", "Item_Stone_"))]
        fresh = build_presented_receipts(native_flow(), real_model_presenter(), TOKEN, names)[0]
        if not legacy:
            return fresh
        editor = FlowEditor(fresh, "Compatible old receipt fixture")
        actuals = {row["actor"] for row in ITEM_DATA.values()
                   if row["actor"].startswith(("Item_Medal_", "Item_Stone_"))}
        for event in editor.chart.events:
            params = getattr(event.data, "params", None)
            if params is not None and params.data.get("ActorName") in actuals and SHOW_ACTOR_ARGUMENT in params.data:
                params.data[SHOW_ACTOR_ARGUMENT] = params.data["ActorName"] + "_ImportantMenu"
                editor.expected[event.name] = dict(params.data)
        return editor.write("Compatible old receipt fixture")[0]

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
                    from ootrr_triforce.dungeon_messages import message_id
                    dungeon_message = message_id(metadata)
                    self.assertEqual([params["ActorName"] for action, params in run.trace
                                      if action == "FixtureItemWindow"], [] if dungeon_message else [actor])
                    self.assertEqual([params["MessageId"] for action, params in run.trace if action == "EventTalk"],
                                     [dungeon_message] if dungeon_message else [])
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
        self.assertNotEqual(model_actor("Item_Medal_Light"), chest_model_actor("Item_Medal_Light"))
        self.assertNotEqual(model_actor("Item_Stone_Forest"), chest_model_actor("Item_Stone_Forest"))
        self.assertEqual(model_actor("Item_Dungeon_SmallKey"), "Obj_MiniGame_SmallKey")
        self.assertEqual(model_actor("Item_Hookshot"), "Item_Hookshot")
        self.assertEqual(chest_model_actor("Item_Dungeon_SmallKey"), "Obj_MiniGame_SmallKey")
        self.assertEqual(chest_model_actor("Item_Hookshot"), "Item_Hookshot")
        self.assertTrue(chest_model_actor("Item_Medal_Fire").startswith("Item_AP_Chest_"))
        self.assertNotEqual(chest_model_actor("Item_Melody_FireBolero"), model_actor("Item_Melody_FireBolero"))

    def test_all_nine_dungeon_rewards_use_visual_only_models_without_alias_inventory(self):
        names = [name for name, row in ITEM_DATA.items()
                 if row["actor"].startswith(("Item_Medal_", "Item_Stone_"))]
        self.assertEqual(len(names), 9)
        pouch, presented, _ = build_presented_receipts(native_flow(), real_model_presenter(), TOKEN, names)
        charts = {name: FlowEditor(raw, name).chart for name, raw in (
            ("GetPouchContent", pouch), (PRESENTER_NAME, presented),
            (CAMERA_FACING_FLOW, native_facing_animation()))}
        for name in names:
            actor = ITEM_DATA[name]["actor"]
            alias = model_actor(actor)
            with self.subTest(item=name):
                self.assertNotEqual(alias, chest_model_actor(actor))
                self.assertEqual(alias, "Item_AP_Show_" + hashlib.sha256(actor.encode()).hexdigest()[:12])
                self.assertNotIn("ImportantMenu", alias)
                run = SceneRun(charts)
                run.run("GetPouchContent", event_name(ITEM_IDS[name]))
                self.assertEqual([p["Actor"] for command, p in run.trace
                                  if command == "EventCreateShowItemFromActorFileName"], [alias])
                self.assertEqual([p["Actor"] for command, p in run.trace
                                  if command == "EventTriggerAddOrRemovePouchContent"], [actor])
                self.assertEqual([p["ActorName"] for command, p in run.trace
                                  if command == "FixtureItemWindow"], [actor])
                self.assertEqual([p["ContentName"] for flow, _, p in run.calls
                                  if flow == CAMERA_FACING_FLOW], [actor])
                self.assertEqual(run.owned, {actor})
                self.assertEqual(sum(command == "EventTriggerAddOrSubGameDataInt" and p["GameDataName"] == CURSOR
                                     for command, p in run.trace), 1)

    def test_cached_receipt_model_upgrade_matches_fresh_generation_and_is_byte_idempotent(self):
        fresh = self.dungeon_receipt_fixture()
        legacy = self.dungeon_receipt_fixture(legacy=True)
        updated, changes = receipt_model_aliases(legacy)
        self.assertEqual(len(changes), 9)
        self.assertEqual(updated, fresh)
        self.assertEqual(receipt_model_aliases(fresh), (fresh, []))
        self.assertEqual(receipt_model_aliases(updated), (updated, []))

        # A constructor made while testing the existing chest guest must also
        # migrate, without reusing its pouch performer's separate model binding.
        editor = FlowEditor(legacy, "Reviewed intermediate chest guests")
        for event in editor.chart.events:
            params = getattr(event.data, "params", None)
            if params is not None and SHOW_ACTOR_ARGUMENT in params.data:
                params.data[SHOW_ACTOR_ARGUMENT] = chest_model_actor(params.data["ActorName"])
                editor.expected[event.name] = dict(params.data)
        intermediate = editor.write("Reviewed intermediate chest guests")[0]
        updated, changes = receipt_model_aliases(intermediate)
        self.assertEqual(len(changes), 9)
        self.assertEqual(updated, fresh)

    def test_cached_model_upgrade_rejects_crossed_actor_or_item_id_before_any_result(self):
        for field in ("actor", "id"):
            with self.subTest(field=field):
                editor = FlowEditor(self.dungeon_receipt_fixture(legacy=True), "Crossed old model")
                event = next(e for e in editor.chart.events
                             if getattr(e.data, "params", None) is not None
                             and SHOW_ACTOR_ARGUMENT in e.data.params.data)
                if field == "actor":
                    event.data.params.data["ActorName"] = "Item_Stone_Water"
                else:
                    event.name = "OOTRR_APReceive_999999_Show"
                editor.expected[event.name] = dict(event.data.params.data)
                # Renaming changes the test editor's original name snapshot;
                # raw serialization remains the intended malformed fixture.
                if field == "id":
                    import io
                    stream = io.BytesIO(); editor.flow.write(stream); raw = stream.getvalue()
                else:
                    raw = editor.write("Crossed old model")[0]
                with self.assertRaisesRegex(ValueError, "native AP item identity"):
                    receipt_model_aliases(raw)

    def test_cached_model_upgrade_preserves_native_nodes_and_typed_arguments(self):
        from evfl.common import Argument
        editor = FlowEditor(self.dungeon_receipt_fixture(), "Unrelated native model")
        old = "Item_Medal_Forest_ImportantMenu"
        editor.subflow("NativeInventoryMenu", PRESENTER_NAME, "NativeEntry",
                       {SHOW_ACTOR_ARGUMENT: old, "ActorName": "Item_Medal_Forest"})
        event = next(e for e in editor.chart.events
                     if getattr(e.data, "params", None) is not None
                     and SHOW_ACTOR_ARGUMENT in e.data.params.data)
        event.data.params.data[SHOW_ACTOR_ARGUMENT] = Argument(old)
        editor.expected[event.name] = dict(event.data.params.data)
        raw = editor.write("Unrelated native model")[0]
        self.assertEqual(receipt_model_aliases(raw), (raw, []))

    def test_legacy_stage_without_receipts_needs_no_native_flow_or_actor_resources(self):
        with tempfile.TemporaryDirectory(prefix="ootrr-no-model-receipts-") as tmp, patch(
                "ootrr_triforce.mod_codec.Codec", side_effect=AssertionError("Unexpected resource decode")) as codec:
            game, mod = Path(tmp) / "native", Path(tmp) / "legacy"
            self.assertEqual(prepare_receipt_model_aliases(game, mod), {"models": 0, "written": 0})
            codec.assert_not_called()
            self.assertEqual(list(Path(tmp).iterdir()), [])

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
    def test_old_sixteen_model_constructor_gains_nine_visual_packs_before_receipt_migration(self):
        from ootrr_triforce import app_runtime, presentation_models
        from ootrr_triforce.mod_codec import Codec
        from ootrr_triforce.presentation_models import REST
        from ootrr_triforce.receipt_events import FLOW_PATH
        from oot_rando.formats import byml_codec
        from oot_rando.game.resource_allocations import allocation
        game = Path(os.environ["OOTRR_ROMFS"])
        quest = {row["actor"] for row in ITEM_DATA.values()
                 if row["actor"].startswith(("Item_Medal_", "Item_Stone_"))}
        current_separate, current_model = presentation_models._separate_model, presentation_models.model_actor
        def old_model(actor):
            return actor + "_ImportantMenu" if actor in quest else current_model(actor)
        with tempfile.TemporaryDirectory(prefix="ootrr-old-model-base-") as tmp, patch.object(
                app_runtime, "_resource_override", Path(os.environ["OOTRR_CODEC_RESOURCES"])):
            mod = Path(tmp) / "mods/Archipelago/romfs"
            with patch.object(presentation_models, "_separate_model",
                              lambda actor: actor not in quest and current_separate(actor)), patch.object(
                    presentation_models, "model_actor", old_model):
                self.assertEqual(prepare_presentation_models(game, mod),
                                 {"models": 16, "chest_models": 70, "written": 90})
            codec = Codec((game / "Pack/ZsDic.pack.zs").read_bytes())
            aliases = {model_actor(actor) for actor in quest}
            self.assertTrue(all(not (mod / ("Pack/Actor/" + alias + ".pack.zs")).exists() for alias in aliases))
            original = {p.relative_to(mod).as_posix(): p.read_bytes() for p in (mod / "Pack/Actor").glob("*")}
            receipt = mod / FLOW_PATH
            receipt.parent.mkdir(parents=True, exist_ok=True)
            old = PresentationModelTests.dungeon_receipt_fixture(legacy=True)
            receipt.write_bytes(codec.encode(old, (game / FLOW_PATH).read_bytes()))
            self.assertEqual(prepare_receipt_model_aliases(game, mod), {"models": 9, "written": 2})
            self.assertEqual(codec.decode(receipt.read_bytes()), PresentationModelTests.dungeon_receipt_fixture())
            self.assertTrue(all((mod / ("Pack/Actor/" + alias + ".pack.zs")).is_file() for alias in aliases))
            self.assertTrue(all((mod / path).read_bytes() == content for path, content in original.items()))
            rest = codec.decode((mod / REST).read_bytes())
            for table, path in TABLES.items():
                rows = {row["__RowId"] for row in byml_codec.load(codec.decode((mod / path).read_bytes()))["root"]}
                self.assertEqual(aliases & rows, set() if table == "PouchActorInfo" else aliases)
            for alias in aliases:
                self.assertGreater(allocation(rest, "Pack/Actor/" + alias + ".pack.zs"), 0)
                self.assertGreater(allocation(rest, "Actor/" + alias + ".engine__actor__ActorParam.bgyml"), 0)
                self.assertGreater(allocation(rest, "Component/ModelInfo/" + alias + ".engine__component__ModelInfo.bgyml"), 0)
            snapshot = {p.relative_to(mod).as_posix(): p.read_bytes() for p in mod.rglob("*") if p.is_file()}
            with patch.object(presentation_models, "prepare_presentation_models",
                              side_effect=AssertionError("Fresh receipts must not restage models")):
                self.assertEqual(prepare_receipt_model_aliases(game, mod), {"models": 0, "written": 0})
            self.assertEqual(snapshot, {p.relative_to(mod).as_posix(): p.read_bytes() for p in mod.rglob("*") if p.is_file()})

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
            self.assertEqual(result, {"models": 25, "chest_models": 70, "written": 99})
            snapshot = {p.relative_to(mod).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in mod.rglob("*") if p.is_file()}
            self.assertEqual(prepare_presentation_models(game, mod), {"models": 25, "chest_models": 70, "written": 0})
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
                    if actor.startswith(("Item_Medal_", "Item_Stone_")):
                        self.assertNotEqual(alias, chest_model_actor(actor))
                        self.assertIn("Item_GetDemo", components["ASInfoRef"])
                        self.assertEqual(components["ASRef"], "?AS/Item_Common.root.asb")
                        self.assertNotIn("PouchContentRef", components)
                        self.assertNotIn("EventPerformerRef", components)
                        self.assertTrue(components["ModelBindRef"])
                        self.assertNotIn("AIInfoRef", components)
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
                self.assertEqual(len(new), len(old) + (70 if table == "PouchActorInfo" else 95))
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
            self.assertEqual(prepare_presentation_models(game, mod), {"models": 25, "chest_models": 70, "written": 1})
            self.assertEqual(snapshot, {p.relative_to(mod).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                        for p in mod.rglob("*") if p.is_file()})

            # A compatible constructor cache already has receipt graphs. The
            # late migration updates only their nine render arguments, after
            # all safe native guest packs have been staged, without a refill.
            from ootrr_triforce.receipt_events import FLOW_PATH
            receipt = mod / FLOW_PATH
            receipt.parent.mkdir(parents=True, exist_ok=True)
            old_models = PresentationModelTests.dungeon_receipt_fixture(legacy=True)
            receipt.write_bytes(codec.encode(old_models, (game / FLOW_PATH).read_bytes()))
            before_rst = codec.decode((mod / REST).read_bytes())
            self.assertEqual(prepare_receipt_model_aliases(game, mod), {"models": 9, "written": 2})
            self.assertEqual(codec.decode(receipt.read_bytes()), PresentationModelTests.dungeon_receipt_fixture())
            self.assertGreaterEqual(allocation(codec.decode((mod / REST).read_bytes()), FLOW_PATH),
                                    allocation(before_rst, FLOW_PATH))
            migrated = {p.relative_to(mod).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in mod.rglob("*") if p.is_file()}
            self.assertEqual(prepare_receipt_model_aliases(game, mod), {"models": 0, "written": 0})
            self.assertEqual(migrated, {p.relative_to(mod).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in mod.rglob("*") if p.is_file()})


if __name__ == "__main__":
    unittest.main()
