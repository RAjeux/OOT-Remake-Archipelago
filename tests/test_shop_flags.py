"""Saved purchase flags must preserve all existing GameData types and counters."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from oot_rando.formats import byml_codec as by
from ootrr_triforce.catalog import LEGACY_SHOP_CHECKS, SHOP_CHECKS
from ootrr_triforce.cursor_resource import append_saved_bool, append_saved_index
from ootrr_triforce import native_setup


class PurchaseFlagTests(unittest.TestCase):
    def test_all_purchase_flags_survive_roundtrip_in_both_byte_orders(self):
        row = {"Hash": by.U32(1), "DefaultValue": 0, "SaveFileIndex": 0, "ResetTypeValue": 8}
        source = {"Data": {"Int": [row], "Bool": [dict(row, DefaultValue=False)],
                           "Else": [by.U64(0x9876543210123456)]},
                  "MetaData": {"SaveDataSize": [100, 56], "SaveDataOffsetPos": [100, 56],
                               "AllDataSaveSize": 130, "AllDataSaveOffset": 145}}
        for endian in ("<", ">"):
            raw = by.dump(dict(root=source, version=7, endian=endian))
            raw = append_saved_index(raw, 0x55667788, 17)
            for metadata in SHOP_CHECKS.values():
                raw = append_saved_bool(raw, metadata["flag"])
            result = by.load(raw)["root"]
            self.assertEqual(result["Data"]["Int"][1]["DefaultValue"], 17)
            booleans = {int(r["Hash"]): r for r in result["Data"]["Bool"]}
            self.assertEqual(len(booleans), 1 + len(SHOP_CHECKS))
            for metadata in SHOP_CHECKS.values():
                flag = booleans[metadata["flag"]]
                self.assertIs(flag["DefaultValue"], False)
                self.assertEqual((flag["SaveFileIndex"], flag["ResetTypeValue"]), (0, 8))
            self.assertEqual(result["Data"]["Else"], source["Data"]["Else"])
            added = 8 + 8 * len(SHOP_CHECKS)
            self.assertEqual(result["MetaData"]["SaveDataSize"], [100 + added, 56])
            self.assertEqual(result["MetaData"]["AllDataSaveSize"], 130 + added)
            with self.assertRaises(ValueError):
                append_saved_bool(raw, next(iter(SHOP_CHECKS.values()))["flag"])

    def test_room_binding_registers_only_selected_deals_and_keeps_legacy_eight(self):
        from oot_rando.game import resource_allocations
        class IdentityCodec:
            def __init__(self, _dictionary): pass
            def decode(self, raw): return raw
            def encode(self, raw, _original): return raw
        row = {"Hash": by.U32(1), "DefaultValue": 0, "SaveFileIndex": 0, "ResetTypeValue": 8}
        source = {"Data": {"Int": [row], "Bool": [dict(row, DefaultValue=False)]},
                  "MetaData": {"SaveDataSize": [100, 56], "SaveDataOffsetPos": [100, 56],
                               "AllDataSaveSize": 130, "AllDataSaveOffset": 145}}
        selected = [next(name for name, row in SHOP_CHECKS.items() if row["shop"] == shop)
                    for shop in dict.fromkeys(row["shop"] for row in SHOP_CHECKS.values())]
        for settings, checks in ((dict(shop_check_mode="special_deals", shop_checks=selected), selected),
                                 (dict(shop_check_mode="special_deals", shop_checks=[]), []),
                                 (dict(kokiri_shop_checks=True), sorted(LEGACY_SHOP_CHECKS))):
            with self.subTest(settings=settings), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                game, mod = root / "game", root / "mod"
                for path, raw in ((game / "Pack/ZsDic.pack.zs", b"dictionary"),
                                  (game / native_setup.GAME_DATA, by.dump(dict(root=source, version=7, endian="<"))),
                                  (mod / native_setup.REST, b"resource table")):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(raw)
                data = dict(settings, token="ab" * 32, checks=checks)
                with patch.object(native_setup, "Codec", IdentityCodec), \
                        patch.object(resource_allocations, "grow_resources", side_effect=lambda raw, _growth: (raw, {})):
                    native_setup.bind_romfs(game, mod, data, 0)
                result = by.load((mod / native_setup.GAME_DATA).read_bytes())["root"]
                flags = {int(row["Hash"]) for row in result["Data"]["Bool"]}
                self.assertEqual(flags, {1, *(SHOP_CHECKS[name]["flag"] for name in checks)})
                self.assertEqual((mod / native_setup.MARKER).read_text(), data["token"] + "\n")


if __name__ == "__main__":
    unittest.main()
