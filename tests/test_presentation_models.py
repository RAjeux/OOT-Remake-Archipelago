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
                                               chest_model_actor, needs_model_alias, prepare_presentation_models)
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


@unittest.skipUnless(os.environ.get("OOTRR_ROMFS"), "requires native v1.1.1 resources")
class NativePresentationModelTests(unittest.TestCase):
    def test_every_alias_has_getdemo_model_and_original_resources_remain_untouched(self):
        from ootrr_triforce import app_runtime
        from ootrr_triforce.mod_codec import Codec
        from oot_rando.formats import byml_codec
        from oot_rando.formats.inspect_resources import sarc
        game = Path(os.environ["OOTRR_ROMFS"])
        with tempfile.TemporaryDirectory(prefix="ootrr-presentation-models-") as tmp, patch.object(
                app_runtime, "_resource_override", Path(os.environ["OOTRR_CODEC_RESOURCES"])):
            mod = Path(tmp) / "mods/Archipelago/romfs"
            result = prepare_presentation_models(game, mod)
            self.assertEqual(result, {"models": 16, "chest_models": 25, "written": 45})
            snapshot = {p.relative_to(mod).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in mod.rglob("*") if p.is_file()}
            self.assertEqual(prepare_presentation_models(game, mod), {"models": 16, "chest_models": 25, "written": 0})
            self.assertEqual(snapshot, {p.relative_to(mod).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                        for p in mod.rglob("*") if p.is_file()})
            self.assertFalse((mod / "GameData").exists())
            self.assertFalse((mod / "Mals").exists())
            codec = Codec((game / "Pack/ZsDic.pack.zs").read_bytes())
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
                self.assertEqual(len(new), len(old) + (25 if table == "PouchActorInfo" else 41))
                self.assertTrue(all(by_id[row["__RowId"]] == row for row in old))
                if table == "PouchActorInfo":
                    native = next(row for row in old if row["__RowId"] == "Item_Medal_Forest")
                    for alias in chest_aliases:
                        self.assertEqual(by_id[alias], dict(native, __RowId=alias))


if __name__ == "__main__":
    unittest.main()
