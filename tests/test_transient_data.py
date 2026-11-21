"""Pickup arguments must never change saved GameData layout or existing values."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from oot_rando.formats import byml_codec as by
from ootrr_triforce.cursor_resource import append_saved_bool, append_transient_string64


class PickupArgumentTests(unittest.TestCase):
    def test_unsaved_string_preserves_saved_sizes_types_and_both_byte_orders(self):
        for endian in ("<", ">"):
            with self.subTest(endian=endian):
                scalar = dict(Hash=by.U32(1), DefaultValue=False, SaveFileIndex=0, ResetTypeValue=8)
                rows = [dict(Hash=by.U32(17), DefaultValue="existing", SaveFileIndex=0, ResetTypeValue=8),
                        dict(Hash=by.U32(33), DefaultValue="", SaveFileIndex=-1, ResetTypeValue=8)]
                metadata = dict(SaveDataSize=[100, 56], SaveDataOffsetPos=[100, 56],
                                AllDataSaveSize=130, AllDataSaveOffset=145)
                document = dict(Data=dict(Bool=[scalar], String64=rows,
                                          Native64=[by.U64(0x9876543210123456)]), MetaData=metadata)
                raw = by.dump(dict(root=document, version=7, endian=endian))
                result = append_transient_string64(raw, 25)
                parsed = by.load(result)["root"]
                self.assertEqual(parsed["MetaData"], metadata)
                self.assertEqual(parsed["Data"]["Bool"], document["Data"]["Bool"])
                self.assertEqual(parsed["Data"]["Native64"], document["Data"]["Native64"])
                self.assertEqual(parsed["Data"]["String64"], [rows[0],
                    dict(Hash=by.U32(25), DefaultValue="", SaveFileIndex=-1, ResetTypeValue=8), rows[1]])
                second = by.load(append_transient_string64(result, 0xf1234567))["root"]
                self.assertEqual(second["MetaData"], metadata)
                self.assertEqual(second["Data"]["String64"][:-1], parsed["Data"]["String64"])
                self.assertEqual(second["Data"]["String64"][-1]["SaveFileIndex"], -1)
                saved = by.load(append_saved_bool(result, 9))["root"]
                self.assertEqual(saved["MetaData"]["SaveDataSize"], [108, 56])
                self.assertEqual(saved["Data"]["String64"], parsed["Data"]["String64"])
                with self.assertRaises(ValueError):
                    append_transient_string64(result, 25)


if __name__ == "__main__":
    unittest.main()
