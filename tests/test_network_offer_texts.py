"""Final AP scrub offers retain native prices, control tags and localized answers."""
import copy
import os
from pathlib import Path
import sys
import json
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))

from evfl.common import Argument
from ootrr_triforce.catalog import LOCATION_IDS
from ootrr_triforce.network_offer_texts import (
    COLOR_END, COLOR_START, MESSAGE_FILE, MESSAGE_GROUP, TEMPLATE,
    _replace_name, offer_label, offer_parameters, patch_message_archive,
    prepare_offer_texts,
)


def record(name="Jabu Jabus Belly Deku Scrub", kind="scrub_menu"):
    return {"name": name, "metadata": {"native_kind": kind}}


class OfferParameterTests(unittest.TestCase):
    def test_only_message_arguments_change_and_original_call_stays_untouched(self):
        for parameter in ("SellerMessageId", "SaleMsg"):
            with self.subTest(parameter=parameter):
                before = {parameter: Argument("SaleMsg"), "SalePrice": 30,
                          "ActorName": "Item_Range_Bow", "ChoiceLabel1": 1,
                          "ChoiceLabel2": 2, "Enemy_Scrub_Business": "NativeNpc"}
                original = copy.deepcopy(before)
                after = offer_parameters(record(), before)
                self.assertEqual(after[parameter], MESSAGE_GROUP + ":" + offer_label(record()))
                self.assertEqual(before, original)
                self.assertEqual({key: value for key, value in after.items() if key != parameter},
                                 {key: value for key, value in original.items() if key != parameter})

    def test_unrelated_rewards_and_historical_schema_are_no_ops(self):
        parameters = {"ActorName": "Item_Range_Bow"}
        self.assertIs(offer_parameters(record(kind="shop"), parameters), parameters)
        self.assertIs(offer_parameters({"name": "Unrelated reward"}, parameters), parameters)
        self.assertEqual(prepare_offer_texts("missing", "missing", {}, {}), {})
        self.assertEqual(prepare_offer_texts("missing", "missing", {}, {"network_sources_schema": 2}), {})

    def test_scrub_without_native_offer_argument_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "no offer message"):
            offer_parameters(record(), {"ActorName": "Item_Range_Bow"})

    def test_player_names_are_plain_text_and_native_tags_remain_exact(self):
        template = b"\x0e\x03\x00\x00\x00\x03\x00\x0f\x00\x00Before " + COLOR_START + b"Old item" + COLOR_END + b" Price {native-price} end\0"
        name = "Bow {2.12:abcd} (Ami)"
        after = _replace_name(template, name)
        self.assertEqual(after, template.replace(b"Old item", name.encode("utf-8")))
        for bad in ("", "Name\0X", "Name\x0eX", "Name\x0fX"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "Invalid"):
                _replace_name(template, bad)


@unittest.skipUnless(os.environ.get("OOTRR_ROMFS"), "requires native v1.1.1 messages and flows")
class NativeOfferResourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ootrr_triforce import app_runtime
        from ootrr_triforce.mod_codec import Codec
        cls.native = Path(os.environ["OOTRR_ROMFS"])
        cls.override = patch.object(app_runtime, "_resource_override",
                                   Path(os.environ.get("OOTRR_CODEC_RESOURCES", ROOT / "dist")))
        cls.override.start()
        cls.codec = Codec((cls.native / "Pack/ZsDic.pack.zs").read_bytes())

    @classmethod
    def tearDownClass(cls):
        cls.override.stop()

    def read(self, path):
        return self.codec.decode((self.native / path).read_bytes())

    def test_all_native_languages_keep_every_other_message_choice_and_price(self):
        from oot_rando.formats.inspect_resources import sarc
        from oot_rando.formats.msbt import load
        records = [record(), record("LW Deku Scrub Grotto Rear")]
        roster = {row["name"]: {"item": "Bow", "player": "Ami", "local": True} for row in records}
        languages = sorted((self.native / "Mals").glob("*.Product.110.sarc.zs"))
        self.assertGreaterEqual(len(languages), 2)
        for path in languages:
            language = path.name.split(".", 1)[0]
            with self.subTest(language=language):
                raw = self.read("Mals/" + path.name)
                before = sarc(raw)
                original = load(before[MESSAGE_FILE])
                changed = patch_message_archive(raw, records, roster, language, hints=True)
                after = sarc(changed)
                self.assertEqual(set(before), set(after))
                for member in before:
                    if member != MESSAGE_FILE:
                        self.assertEqual(before[member], after[member])
                messages = load(after[MESSAGE_FILE])
                for label in original.labels:
                    self.assertEqual(original.get(label), messages.get(label))
                self.assertTrue(messages.get("0001").strip(b"\0"))
                self.assertTrue(messages.get("0002").strip(b"\0"))
                expected = "Arc (Ami)" if language.endswith("fr") else "Bow (Ami)"
                for row in records:
                    self.assertEqual(messages.get(offer_label(row)),
                                     _replace_name(original.get(TEMPLATE), expected))
                self.assertEqual(patch_message_archive(changed, records, roster, language, hints=True), changed)

    def test_hidden_rewards_remain_hidden_and_foreign_names_are_not_mistranslated(self):
        from oot_rando.formats.inspect_resources import sarc
        from oot_rando.formats.msbt import load
        records = [record()]
        roster = {records[0]["name"]: {"item": "Bow", "player": "Friend", "local": False}}
        raw = self.read("Mals/EUfr.Product.110.sarc.zs")
        hidden = load(sarc(patch_message_archive(raw, records, roster, "EUfr", hints=False))[MESSAGE_FILE])
        hidden_name = hidden.get(offer_label(records[0]))
        self.assertIn("Objet myst\u00e8re".encode(), hidden_name)
        self.assertNotIn(b"Friend", hidden_name)
        shown = load(sarc(patch_message_archive(raw, records, roster, "EUfr", hints=True))[MESSAGE_FILE])
        self.assertIn(b"Bow (Friend)", shown.get(offer_label(records[0])))
        self.assertNotIn(b"Arc", shown.get(offer_label(records[0])))

    def test_actual_native_sale_graph_uses_new_message_and_same_price_and_choices(self):
        from evfl.event import SubFlowEvent
        from oot_rando.patching.progressive import FlowEditor
        from ootrr_triforce.network_catalog import SOURCES, flag_name
        from ootrr_triforce.network_flows import patch_reward
        name = "DMC Deku Scrub"
        row = {"name": name, "metadata": SOURCES[name], "actor": "Item_AP_OfferTest",
               "flag_name": flag_name(name), "generated_item": "Piece of Heart"}
        path = "Event/EventFlow/Enemy_Scrub_Business_Common.bfevfl.zs"
        editor = FlowEditor(self.read(path), path)
        original = next(e for e in editor.chart.events if e.name == "Event293")
        old_price = original.data.params.data["Price"]
        patch_reward(editor, original, "ActorName", row, "AP_OfferTestEffect", self.read, 0)
        checked = FlowEditor(editor.write("Native scrub offer proof")[0], path).chart
        stem = "OOTRR_APSource_" + str(LOCATION_IDS[name])
        calls = [e.data for e in checked.events if isinstance(e.data, SubFlowEvent)
                 and e.name == stem + "_0_Get"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].params.data["Price"], old_price)
        self.assertEqual(calls[0].params.data["SellerMessageId"], MESSAGE_GROUP + ":" + offer_label(row))
        talk = next(e.data for e in checked.events if e.name == stem + "_Native0_Event289")
        self.assertEqual(talk.params.data["ChoiceNumber"], 2)
        self.assertEqual([talk.params.data["ChoiceLabel1"], talk.params.data["ChoiceLabel2"]], [1, 2])

    def test_encoded_native_settings_and_staged_allocations_roundtrip_idempotently(self):
        from oot_rando.formats.inspect_resources import sarc
        from oot_rando.formats.msbt import load
        from oot_rando.game.resource_allocations import allocation
        from ootrr_triforce.catalog import ITEM_IDS
        from ootrr_triforce.engine import run_engine
        from ootrr_triforce.network_catalog import SOURCES
        from ootrr_triforce.network_offer_texts import REST
        name = "Jabu Jabus Belly Deku Scrub"
        encoded = json.loads(run_engine("settings", {"settings": {"scrub_hint_text": False}}))["settings_string"]
        self.assertTrue(encoded.startswith("OOTRR1-"))
        metadata = dict(SOURCES[name], generated_item="Piece of Heart")
        roster = {name: {"item": "Bow", "player": "Ami", "local": True, "item_id": ITEM_IDS["Bow"]}}
        settings = {"network_sources_schema": 1, "network_sources": {name: metadata},
                    "_seed_settings": encoded}
        original_table = self.read(REST)
        with tempfile.TemporaryDirectory(prefix="ootrr-offer-text-test-") as directory:
            mod = Path(directory) / "mods/Archipelago/romfs"
            mod.mkdir(parents=True)
            result = prepare_offer_texts(self.native, mod, roster, settings)
            self.assertEqual(result["offers"], 1)
            self.assertGreaterEqual(result["archives"], 2)
            table = self.codec.decode((mod / REST).read_bytes())
            for path in (mod / "Mals").glob("*.Product.110.sarc.zs"):
                relative = path.relative_to(mod).as_posix()
                before, after = self.read(relative), self.codec.decode(path.read_bytes())
                self.assertGreaterEqual(allocation(table, relative),
                                        allocation(original_table, relative) + max(0, len(after) - len(before)))
                messages = load(sarc(after)[MESSAGE_FILE])
                offer = messages.get(offer_label(record()))
                self.assertNotIn(b"Ami", offer)
                self.assertNotIn(b"Bow", offer)
            snapshot = {path.relative_to(mod): path.read_bytes() for path in mod.rglob("*") if path.is_file()}
            self.assertEqual(prepare_offer_texts(self.native, mod, roster, settings), {"offers": 1, "archives": 0})
            self.assertEqual(snapshot, {path.relative_to(mod): path.read_bytes() for path in mod.rglob("*") if path.is_file()})


if __name__ == "__main__":
    unittest.main()
