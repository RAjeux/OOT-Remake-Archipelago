"""Batch AP Bool declarations preserve native BYML pointers and save layout."""
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from oot_rando.formats import byml_codec as byml
from ootrr_triforce.cursor_resource import (append_saved_bool, append_saved_bools, append_saved_index,
                                            append_transient_index, append_transient_string64)


def fixture(endian="<", ordered=True):
    row = {"Hash": byml.U32(1), "DefaultValue": False, "SaveFileIndex": 0, "ResetTypeValue": 8}
    rows = [row, dict(row, Hash=byml.U32(3), SaveFileIndex=-1), dict(row, Hash=byml.U32(0x80000000))]
    if not ordered:
        rows.reverse()
    sizes = [100, 56]
    return byml.dump({"endian": endian, "version": 7, "root": {
        "Data": {"Bool": rows,
                 "Int": [dict(row, Hash=byml.U32(10), DefaultValue=0, SaveFileIndex=-1),
                         dict(row, Hash=byml.U32(20), DefaultValue=0)],
                 "String64": [dict(row, Hash=byml.U32(4), DefaultValue="", SaveFileIndex=-1)],
                 "Else": [byml.U64(0x9876543210123456)]},
        "MetaData": {"SaveDataSize": sizes, "SaveDataOffsetPos": sizes,
                     "AllDataSaveSize": 130, "AllDataSaveOffset": 145}}})


def layout(raw):
    endian = "<" if raw[:2] == b"YB" else ">"
    order = "little" if endian == "<" else "big"
    read = lambda at: struct.unpack_from(endian + "I", raw, at)[0]
    small = lambda at: int.from_bytes(raw[at:at + 3], order)
    table = read(4)
    keys = {}
    for index in range(small(table + 1)):
        at = table + read(table + 4 + 4 * index)
        keys[raw[at:raw.index(b"\0", at)].decode()] = index
    def field(node, name):
        return next(node + 8 + 8 * index for index in range(small(node + 1))
                    if small(node + 4 + 8 * index) == keys[name])
    root = read(12)
    data, metadata = read(field(root, "Data")), read(field(root, "MetaData"))
    group = read(field(data, "Bool"))
    count = small(group + 1)
    first = (group + 4 + count + 3) & ~3
    rows = {}
    for index in range(count):
        node = read(first + 4 * index)
        rows[read(field(node, "Hash"))] = (node, 4 + 8 * small(node + 1))
    return dict(root=root, data=data, metadata=metadata, rows=rows,
                groups={name: read(field(data, name)) for name in ("Bool", "Int", "String64", "Else") if name in keys},
                saved_arrays={name: read(field(metadata, name)) for name in ("SaveDataSize", "SaveDataOffsetPos")})


class BatchBoolTests(unittest.TestCase):
    def test_one_key_keeps_the_exact_released_byte_layout(self):
        golden = json.loads((ROOT / "tests/fixtures/cursor-single-v010.json").read_text())
        for endian in ("<", ">"):
            raw = fixture(endian)
            operations = {"bool_false": append_saved_bool(raw, 0x12345678),
                          "bool_true": append_saved_bool(raw, 0x12345678, True),
                          "index": append_saved_index(raw, 0x12345678, 7),
                          "transient_index": append_transient_index(raw, 0x12345678),
                          "transient_string": append_transient_string64(raw, 0x12345678)}
            for name, result in operations.items():
                self.assertEqual(hashlib.sha256(result).hexdigest(), golden[endian][name])
            self.assertEqual(append_saved_bools(raw, [0x12345678]), operations["bool_false"])
            self.assertEqual(append_saved_bools(raw, [0x12345678], True), operations["bool_true"])

    def test_thousand_markers_match_repeated_semantics_with_linear_storage(self):
        marker_keys = list(reversed(range(100, 1100)))
        for endian in ("<", ">"):
            for ordered in (False, True):
                with self.subTest(endian=endian, ordered=ordered):
                    raw = fixture(endian, ordered)
                    repeated = raw
                    for key in marker_keys:
                        repeated = append_saved_bool(repeated, key)
                    batch = append_saved_bools(raw, marker_keys)
                    self.assertEqual(byml.load(batch), byml.load(repeated))
                    self.assertLess(len(batch) - len(raw), 50_000)
                    self.assertLess(len(batch), len(repeated) // 10)
                    meta = byml.load(batch)["root"]["MetaData"]
                    self.assertEqual(meta, {"SaveDataSize": [8100, 56], "SaveDataOffsetPos": [8100, 56],
                                           "AllDataSaveSize": 8130, "AllDataSaveOffset": 8145})

    def test_existing_row_and_unrelated_container_offsets_stay_identical(self):
        for endian in ("<", ">"):
            raw = fixture(endian)
            before = layout(raw)
            result = append_saved_bools(raw, list(range(100, 1100)))
            after = layout(result)
            for name in ("root", "data", "metadata"):
                self.assertEqual(before[name], after[name])
            for name in ("Int", "String64", "Else"):
                self.assertEqual(before["groups"][name], after["groups"][name])
            self.assertEqual(raw[:12], result[:12])
            for key, (offset, length) in before["rows"].items():
                self.assertEqual(after["rows"][key], (offset, length))
                self.assertEqual(result[offset:offset + length], raw[offset:offset + length])
            for offset in before["saved_arrays"].values():
                self.assertEqual(result[offset:offset + 16], raw[offset:offset + 16])

    def test_empty_duplicate_existing_and_cross_type_collisions_are_strict(self):
        raw = fixture()
        self.assertIs(append_saved_bools(raw, []), raw)
        for marker_keys in ([100, 100], [1], [20], [4], [True], [-1], [2**32], ["100"]):
            with self.subTest(keys=marker_keys):
                with self.assertRaises(ValueError):
                    append_saved_bools(raw, marker_keys)
        result = append_saved_bools(raw, [100, 101])
        with self.assertRaises(ValueError):
            append_saved_bools(result, [102, 100])
        with self.assertRaises(ValueError):
            append_saved_bool(result, 100)

    def test_transient_values_still_leave_save_metadata_unchanged(self):
        for endian in ("<", ">"):
            raw = fixture(endian)
            meta = byml.load(raw)["root"]["MetaData"]
            for operation in (append_transient_index, append_transient_string64):
                result = operation(raw, 100)
                self.assertEqual(byml.load(result)["root"]["MetaData"], meta)
            result = append_saved_bools(raw, [100, 101], True)
            rows = byml.load(result)["root"]["Data"]["Bool"]
            self.assertTrue(all(row["DefaultValue"] is True for row in rows if row["Hash"] in (100, 101)))


@unittest.skipUnless(os.environ.get("OOTRR_ROMFS"), "requires private native GameData")
class NativeBatchBoolTests(unittest.TestCase):
    def test_native_thousand_flags_add_under_256_kib_and_keep_every_existing_pointer(self):
        from ootrr_triforce import app_runtime
        from ootrr_triforce.mod_codec import Codec
        from ootrr_triforce.network_catalog import murmur3
        game = Path(os.environ["OOTRR_ROMFS"])
        with patch.object(app_runtime, "_resource_override", Path(os.environ["OOTRR_CODEC_RESOURCES"])):
            codec = Codec((game / "Pack/ZsDic.pack.zs").read_bytes())
            raw = codec.decode((game / "GameData/GameDataList.Product.110.byml.zs").read_bytes())
        marker_keys = [murmur3("Archipelago.BatchProof." + str(index)) for index in range(1000)]
        before = byml.load(raw)
        result = append_saved_bools(raw, marker_keys)
        after = byml.load(result)
        self.assertLess(len(result) - len(raw), 256 * 1024)
        self.assertEqual(len(after["root"]["Data"]["Bool"]), len(before["root"]["Data"]["Bool"]) + 1000)
        self.assertEqual(after["root"]["MetaData"]["AllDataSaveSize"], before["root"]["MetaData"]["AllDataSaveSize"] + 8000)
        old, new = layout(raw), layout(result)
        for key, original in old["rows"].items():
            self.assertEqual(new["rows"][key], original)
        for name, rows in before["root"]["Data"].items():
            if name != "Bool":
                self.assertEqual(after["root"]["Data"][name], rows)


if __name__ == "__main__":
    unittest.main()
