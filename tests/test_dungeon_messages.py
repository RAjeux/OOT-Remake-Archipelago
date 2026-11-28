"""Dungeon item windows name their destination without granting inventory."""
import copy
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from evfl.common import Argument
from evfl.entry_point import EntryPoint
from evfl.event import ActionEvent, SubFlowEvent
from evfl.util import make_index
from oot_rando.formats import msbt
from oot_rando.formats.byml_codec import build_sarc
from oot_rando.formats.inspect_resources import sarc
from oot_rando.game.resource_allocations import allocation
from oot_rando.patching.event_patch import GAMEDATA_ACTOR_PARAMS
from oot_rando.patching.progressive import FlowEditor
from ootrr_triforce.catalog import ITEM_DATA
from ootrr_triforce.dungeon_messages import (MESSAGE_FILE, NAMES_FILE, PLACES_FILE, PREFIX, REST,
    append_window, message_id, patch_message_archive, prepare_messages)
from ootrr_triforce.receipt_events import DUNGEONS
from test_network_flows import editor
from test_resource_allocations import table as allocation_table


def book(pairs):
    header = bytearray(32)
    header[:10] = b"MsgStdBn\xff\xfe"
    struct.pack_into("<H", header, 14, 2)
    message = msbt.Msbt(header, [(b"LBL1", struct.pack("<III", 1, 0, 12)), (b"TXT2", b"")], {}, [], 1)
    for label, value in pairs.items():
        message.labels[label] = len(message.texts)
        message.texts.append(value if isinstance(value, bytes) else value.encode("utf-8") + b"\0")
    return msbt.dump(message)


def archive(language="en", *, missing=()):
    # Include binary grammar tags whose arguments end in NUL bytes. Exactly
    # one terminal NUL must be removed when joining the item and place names.
    grammar = b"\x0e\xc9\x00\x00\x00\x04\x00\x01\x02\x00\x00"
    names = {"Item_Dungeon_SmallKey_Name": "Petite clé" if language == "fr" else "Small Key",
             "Item_Dungeon_BossKey_Name": "Clé du boss" if language == "fr" else "Boss Key",
             "Item_Dungeon_Map_Name": "Carte" if language == "fr" else "Map",
             "Item_Dungeon_Compass_Name": "Boussole" if language == "fr" else "Compass"}
    names = {key: value.encode("utf-8") + grammar + b"\0" for key, value in names.items() if key not in missing}
    places = {key: key for key in DUNGEONS.values()}
    places["GanonCastle"] = "Château de Ganon" if language == "fr" else "Ganon's Castle"
    places["ForestTemple"] = "Temple de la Forêt" if language == "fr" else "Forest Temple"
    places = {key: grammar + value.encode("utf-8") + b"\0" for key, value in places.items() if key not in missing}
    return build_sarc({MESSAGE_FILE: book({"Native": b"Native text\0",
                                         "OOTRR_SmallKey_ForestTemple": b"Old counter DungeonInfo.ForestTemple.SmallKeyNum\0"}),
                       NAMES_FILE: book(names), PLACES_FILE: book(places), "Unrelated.bin": b"untouched"})


class DungeonWindowTests(unittest.TestCase):
    def test_distinct_dungeons_and_key_families_have_explicit_ids(self):
        expected = {
            "Small Key (Forest Temple)": "SmallKey_ForestTemple",
            "Small Key (Thieves Hideout)": "SmallKey_GerudoFortress",
            "Boss Key (Ganons Castle)": "BossKey_InsideGanonCastle",
            "Boss Key (Water Temple)": "BossKey_WaterTemple",
            "Map (Deku Tree)": "Map_InsideTheDekuTree",
            "Compass (Water Temple)": "Compass_WaterTemple",
        }
        for name, suffix in expected.items():
            with self.subTest(item=name):
                self.assertEqual(message_id(ITEM_DATA[name]), "EventFlowMsg/Dm_SY_Get:" + PREFIX + suffix)
        for name in ("Small Key (Treasure Chest Game)", "Heart Container", "Bow", "Rupees (20)"):
            self.assertIsNone(message_id(ITEM_DATA[name]))
        self.assertIsNone(message_id({}))
        self.assertIsNone(message_id({"mode": "generic", "kind": "SmallKey"}))

    def test_window_is_one_native_talk_with_the_verified_system_actor_and_no_effect(self):
        target = editor("DungeonItemTest")
        metadata = copy.deepcopy(ITEM_DATA["Small Key (Forest Temple)"])
        before = copy.deepcopy(metadata)
        window = append_window(target, metadata, "AP_Test")
        point = EntryPoint("Start")
        point.main_event = make_index(window)
        target.chart.entry_points.append(point)
        raw, _ = target.write("Named dungeon window")
        checked = FlowEditor(raw, "Named dungeon window").chart
        self.assertEqual(len(checked.events), 1)
        self.assertIsInstance(checked.events[0].data, ActionEvent)
        self.assertEqual(checked.events[0].data.actor_action.v.v, "EventTalk")
        params = checked.events[0].data.params.data
        self.assertEqual(params["MessageId"], message_id(metadata))
        self.assertEqual({key for key, value in params.items() if value is True},
                         {"IsWaitEnd", "IsCloseDialog", "IsOverrideStyle"})
        self.assertEqual(params["OverrideStyle"], 4)
        self.assertEqual(params["ASName"], "")
        self.assertEqual(params["ChoiceNumber"], 0)
        self.assertFalse(params["IsAnimeDriven"])
        owner = checked.actors[0]
        self.assertEqual(str(owner.identifier), "SystemTextNPC")
        self.assertEqual(owner.params.data, GAMEDATA_ACTOR_PARAMS)
        self.assertEqual(owner.concurrent_clips, 1)
        self.assertEqual(owner.argument_name, "")
        self.assertIsNone(owner.argument_entry_point.v)
        self.assertEqual(metadata, before)
        append_window(target, metadata, "AP_Test2")
        self.assertEqual(sum(str(actor.identifier) == "SystemTextNPC" for actor in target.chart.actors), 1)

    def test_unrelated_items_keep_the_exact_native_subflow_and_arguments(self):
        target = editor("NormalItemTest")
        params = {"ActorName": Argument("ActorName"), "IsMiniGame": False}
        before = copy.deepcopy(params)
        window = append_window(target, ITEM_DATA["Bow"], "AP_Bow", flow="GetPouchContent",
                               entry="DisplayGetByActorName", params=params)
        self.assertIsInstance(window.data, SubFlowEvent)
        self.assertEqual((window.data.res_flowchart_name, window.data.entry_point_name),
                         ("GetPouchContent", "DisplayGetByActorName"))
        self.assertEqual(window.data.params.data, before)
        self.assertEqual(params, before)
        self.assertFalse(target.chart.actors)
        empty = append_window(target, {}, "AP_Foreign", entry="OpenGetWindow")
        self.assertIsNone(empty.data.params)


class DungeonMessageTests(unittest.TestCase):
    def test_all_ap_destinations_get_localized_names_and_original_tokens(self):
        for language in ("en", "fr"):
            with self.subTest(language=language):
                raw = archive(language)
                original = sarc(raw)
                after = sarc(patch_message_archive(raw))
                messages = msbt.load(after[MESSAGE_FILE])
                names, places = msbt.load(original[NAMES_FILE]), msbt.load(original[PLACES_FILE])
                for name, metadata in ITEM_DATA.items():
                    identity = message_id(metadata)
                    if identity is None:
                        continue
                    dungeon = DUNGEONS[metadata["dungeon"]]
                    place = "GanonCastle" if dungeon == "InsideGanonCastle" else dungeon
                    expected = names.get(metadata["actor"] + "_Name")[:-1] + b"\n" + places.get(place)
                    actual = messages.get(identity.split(":", 1)[1])
                    self.assertEqual(actual, expected, name)
                    self.assertNotIn(b"DungeonInfo.", actual, name)
                for key in original:
                    if key != MESSAGE_FILE:
                        self.assertEqual(after[key], original[key])
                native = msbt.load(original[MESSAGE_FILE])
                for label in native.labels:
                    self.assertEqual(messages.get(label), native.get(label))
                self.assertEqual(patch_message_archive(patch_message_archive(raw)), patch_message_archive(raw))

    def test_missing_native_labels_fall_back_to_readable_english(self):
        raw = archive("fr", missing={"Item_Dungeon_BossKey_Name", "ForestTemple"})
        messages = msbt.load(sarc(patch_message_archive(raw))[MESSAGE_FILE])
        label = message_id(ITEM_DATA["Boss Key (Forest Temple)"]).split(":", 1)[1]
        self.assertEqual(messages.get(label), b"Boss Key\nForest Temple\0")

    def test_replacing_a_shared_existing_text_never_changes_its_native_alias(self):
        members = sarc(archive())
        messages = msbt.load(members[MESSAGE_FILE])
        label = message_id(ITEM_DATA["Small Key (Forest Temple)"]).split(":", 1)[1]
        messages.labels[label] = messages.labels["Native"]
        members[MESSAGE_FILE] = msbt.dump(messages)
        changed = msbt.load(sarc(patch_message_archive(build_sarc(members)))[MESSAGE_FILE])
        self.assertEqual(changed.get("Native"), b"Native text\0")
        self.assertNotEqual(changed.get(label), changed.get("Native"))

    def test_staging_prefers_prepared_languages_grows_budgets_and_is_idempotent(self):
        class IdentityCodec:
            def __init__(self, _pack): pass
            def decode(self, raw): return raw
            def encode(self, raw, _template): return raw
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "native"
            mod = Path(temporary) / "mods/Archipelago/romfs"
            paths = ["Mals/" + code + ".Product.110.sarc.zs" for code in ("USen", "EUfr", "JPja")]
            for path in paths:
                target = source / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive())
            for path, data in (("Pack/ZsDic.pack.zs", b"synthetic dictionaries"),
                               (REST, allocation_table([(name.removesuffix(".zs"), 4096) for name in paths]))):
                target = source / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            (mod / "Mals").mkdir(parents=True)
            (mod / paths[1]).write_bytes(archive("fr"))
            originals = {path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()}
            with patch("ootrr_triforce.mod_codec.Codec", IdentityCodec):
                result = prepare_messages(source, mod)
                self.assertEqual(result["archives"], 3)
                self.assertGreater(result["messages"], 30)
                native_label = message_id(ITEM_DATA["Small Key (Forest Temple)"]).split(":", 1)[1]
                french = msbt.load(sarc((mod / paths[1]).read_bytes())[MESSAGE_FILE]).get(native_label)
                self.assertIn("Petite clé".encode("utf-8"), french)
                for path in paths:
                    self.assertGreater(allocation((mod / REST).read_bytes(), path), 4096)
                staged = {path.relative_to(mod): path.read_bytes() for path in mod.rglob("*") if path.is_file()}
                self.assertEqual(prepare_messages(source, mod)["archives"], 0)
                self.assertEqual(staged, {path.relative_to(mod): path.read_bytes() for path in mod.rglob("*") if path.is_file()})
            self.assertEqual(originals, {path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()})
            with self.assertRaisesRegex(ValueError, "staging folder"):
                prepare_messages(source, source)


@unittest.skipUnless(os.environ.get("OOTRR_ROMFS"), "requires native v1.1.1 messages")
class NativeDungeonMessagesTests(unittest.TestCase):
    def test_native_names_and_system_actor_match_the_window_recipe(self):
        from ootrr_triforce import app_runtime
        from ootrr_triforce.mod_codec import Codec
        game = Path(os.environ["OOTRR_ROMFS"])
        with patch.object(app_runtime, "_resource_override", Path(os.environ.get("OOTRR_CODEC_RESOURCES", ROOT / "dist"))):
            codec = Codec((game / "Pack/ZsDic.pack.zs").read_bytes())
            raw = codec.decode((game / "Event/EventFlow/GetPouchContent.bfevfl.zs").read_bytes())
            source = FlowEditor(raw, "Native pouch").chart
            owner = next(actor for actor in source.actors if str(actor.identifier) == "SystemTextNPC")
            self.assertEqual(owner.params.data, GAMEDATA_ACTOR_PARAMS)
            self.assertEqual(owner.concurrent_clips, 1)
            for code in ("EUfr", "USen"):
                raw = codec.decode((game / ("Mals/" + code + ".Product.110.sarc.zs")).read_bytes())
                changed = msbt.load(sarc(patch_message_archive(raw))[MESSAGE_FILE])
                for metadata in ITEM_DATA.values():
                    identity = message_id(metadata)
                    if identity:
                        self.assertTrue(changed.get(identity.split(":", 1)[1]))


if __name__ == "__main__":
    unittest.main()
