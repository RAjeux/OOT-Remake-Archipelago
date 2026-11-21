"""Saved purchase flags must preserve all existing GameData types and counters."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from oot_rando.formats import byml_codec as by
from ootrr_triforce.catalog import SHOP_CHECKS
from ootrr_triforce.cursor_resource import append_saved_bool, append_saved_index


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
            self.assertEqual(len(booleans), 9)
            for metadata in SHOP_CHECKS.values():
                flag = booleans[metadata["flag"]]
                self.assertIs(flag["DefaultValue"], False)
                self.assertEqual((flag["SaveFileIndex"], flag["ResetTypeValue"]), (0, 8))
            self.assertEqual(result["Data"]["Else"], source["Data"]["Else"])
            self.assertEqual(result["MetaData"]["SaveDataSize"], [172, 56])
            self.assertEqual(result["MetaData"]["AllDataSaveSize"], 202)
            with self.assertRaises(ValueError):
                append_saved_bool(raw, next(iter(SHOP_CHECKS.values()))["flag"])


if __name__ == "__main__":
    unittest.main()
