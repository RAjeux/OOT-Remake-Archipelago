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
                                            append_transient_index, append_transient_string64,
                                            register_chest_flags)


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


class ConvertedChestFlagTests(unittest.TestCase):
    def fixture(self, endian="<"):
        from ootrr_triforce.network_catalog import ADDITIONAL_SOURCES, murmur3
        actors = sorted({int(variant["actor"]) for source in ADDITIONAL_SOURCES.values()
                         if source.get("native_route") == "frozen_chest" for variant in source["variants"]})
        self.assertEqual(len(actors), 6)
        doc = byml.load(fixture(endian))
        data = doc["root"]["Data"]
        template = data["Bool"][0]
        data["Bool"].extend(dict(template, Hash=byml.U32(100 + index), ResetTypeValue=24)
                            for index in range(len(actors)))
        data["Struct"] = [
            {"Hash": byml.U32(murmur3("IsTreasureBoxOpen")), "DefaultValue": [
                {"Hash": byml.U32(murmur3(str(actor))), "Value": byml.U32(100 + index)}
                for index, actor in enumerate(actors)]},
            {"Hash": byml.U32(murmur3("Untouched.Native.Struct")), "DefaultValue": [
                {"Hash": byml.U32(7), "Value": byml.U32(100)}]},
        ]
        # The BYML writer interns equal arrays/maps. This native struct must
        # keep the original spare targets even when its bytes alias the chest
        # members array and all six member dictionaries.
        data["Struct"].append({"Hash": byml.U32(murmur3("Shared.Native.Struct")),
                               "DefaultValue": data["Struct"][0]["DefaultValue"]})
        return doc, actors

    def members(self, doc):
        from ootrr_triforce.network_catalog import murmur3
        return next(row["DefaultValue"] for row in doc["root"]["Data"]["Struct"]
                    if row["Hash"] == murmur3("IsTreasureBoxOpen"))

    def test_six_chests_have_the_same_qualified_bool_and_struct_key_in_both_byte_orders(self):
        from ootrr_triforce.network_catalog import murmur3
        for endian in ("<", ">"):
            doc, actors = self.fixture(endian)
            before = byml.load(byml.dump(doc))
            result = register_chest_flags(byml.dump(doc), actors)
            after = byml.load(result)
            rows = {int(row["Hash"]): row for row in after["root"]["Data"]["Bool"]}
            members = {int(row["Hash"]): row["Value"] for row in self.members(after)}
            for actor in actors:
                qualified = murmur3("IsTreasureBoxOpen." + str(actor))
                self.assertEqual(members[murmur3(str(actor))], qualified)
                self.assertEqual(rows[qualified], {"Hash": qualified, "DefaultValue": False,
                                                   "SaveFileIndex": 0, "ResetTypeValue": 8})
            self.assertEqual(after["root"]["MetaData"]["SaveDataSize"], [148, 56])
            self.assertEqual(after["root"]["MetaData"]["SaveDataOffsetPos"], [148, 56])
            self.assertEqual(after["root"]["MetaData"]["AllDataSaveSize"], 178)
            for row in before["root"]["Data"]["Bool"]:
                self.assertEqual(rows[row["Hash"]], row, "Spare/native Bool definitions are never reused or changed.")

    def test_only_the_member_array_pointer_changes_and_shared_native_nodes_remain_intact(self):
        from ootrr_triforce.network_catalog import murmur3
        for endian in ("<", ">"):
            doc, actors = self.fixture(endian)
            raw = byml.dump(doc)
            plain_append = append_saved_bools(raw, [murmur3("IsTreasureBoxOpen." + str(actor)) for actor in actors])
            actual = register_chest_flags(raw, actors)
            differences = [index for index in range(len(plain_append)) if actual[index] != plain_append[index]]
            self.assertTrue(differences)
            self.assertLessEqual(len(differences), 4)
            # All appended definitions, native row positions and save-array
            # offsets are exactly those of the existing surgical Bool helper.
            self.assertEqual(actual[len(raw):len(plain_append)], plain_append[len(raw):])
            old, new = layout(raw), layout(actual)
            for key, (at, length) in old["rows"].items():
                self.assertEqual(new["rows"][key], (at, length))
                self.assertEqual(actual[at:at + length], raw[at:at + length])
            expected = byml.load(plain_append)
            for row, actor in zip(self.members(expected), actors):
                row["Value"] = byml.U32(murmur3("IsTreasureBoxOpen." + str(actor)))
            self.assertEqual(byml.load(actual), expected)

    def test_idempotence_empty_selection_and_an_existing_qualified_bool(self):
        from ootrr_triforce.network_catalog import murmur3
        doc, actors = self.fixture()
        raw = byml.dump(doc)
        self.assertIs(register_chest_flags(raw, []), raw)
        qualified = murmur3("IsTreasureBoxOpen." + str(actors[0]))
        partial = append_saved_bools(raw, [qualified])
        complete = register_chest_flags(partial, actors)
        self.assertIs(register_chest_flags(complete, actors), complete)
        self.assertEqual(len(byml.load(complete)["root"]["Data"]["Bool"]),
                         len(doc["root"]["Data"]["Bool"]) + len(actors))

    def test_missing_ambiguous_and_unregistered_or_wrong_type_targets_are_rejected(self):
        for mode in ("missing", "duplicate", "unregistered", "int", "true"):
            with self.subTest(mode=mode):
                doc, actors = self.fixture()
                members = self.members(doc)
                if mode == "missing": members.pop(0)
                elif mode == "duplicate": members.append(dict(members[0]))
                elif mode == "unregistered": members[0]["Value"] = byml.U32(123456)
                elif mode == "int": members[0]["Value"] = byml.U32(20)
                elif mode == "true": next(row for row in doc["root"]["Data"]["Bool"] if row["Hash"] == 100)["DefaultValue"] = True
                with self.assertRaises(ValueError):
                    register_chest_flags(byml.dump(doc), actors)

    def test_qualified_hash_collisions_invalid_persistence_and_bad_actor_inputs_are_rejected(self):
        from ootrr_triforce.network_catalog import murmur3
        for mode in ("int", "duplicate_bool", "reset", "save", "true"):
            with self.subTest(mode=mode):
                doc, actors = self.fixture()
                qualified = murmur3("IsTreasureBoxOpen." + str(actors[0]))
                row = dict(doc["root"]["Data"]["Bool"][0], Hash=byml.U32(qualified))
                if mode == "int":
                    doc["root"]["Data"]["Int"].append(dict(row, DefaultValue=0))
                else:
                    if mode == "reset": row["ResetTypeValue"] = 24
                    elif mode == "save": row["SaveFileIndex"] = -1
                    elif mode == "true": row["DefaultValue"] = True
                    doc["root"]["Data"]["Bool"].append(row)
                    if mode == "duplicate_bool": doc["root"]["Data"]["Bool"].append(dict(row))
                with self.assertRaises(ValueError):
                    register_chest_flags(byml.dump(doc), actors)
        raw = byml.dump(self.fixture()[0])
        for actors in ([True], [0], [-1], [2**64], ["100"], [100, 100]):
            with self.subTest(actors=actors), self.assertRaises(ValueError):
                register_chest_flags(raw, actors)

    def test_room_binding_uses_only_selected_schema_two_frozen_chests_and_grows_allocations(self):
        import tempfile
        import zlib
        from oot_rando.game.resource_allocations import allocation
        from ootrr_triforce import cursor_resource, native_setup
        from ootrr_triforce.network_catalog import ADDITIONAL_SOURCES
        doc, actors = self.fixture()
        frozen = next(name for name, row in ADDITIONAL_SOURCES.items() if row.get("native_route") == "frozen_chest")
        expected = sorted(int(row["actor"]) for row in ADDITIONAL_SOURCES[frozen]["variants"])
        data = {"token": "ba" * 32, "checks": [frozen], "additional_sources": [frozen],
                "network_sources_schema": 2, "network_sources": {frozen: ADDITIONAL_SOURCES[frozen]}}
        self.assertEqual(native_setup.converted_chest_hashes(data), expected)
        for change in ({"checks": []}, {"additional_sources": []}, {"network_sources_schema": 1},
                       {"network_sources_schema": None}):
            self.assertEqual(native_setup.converted_chest_hashes(data | change), [])
        class IdentityCodec:
            def __init__(self, _): pass
            def decode(self, raw): return raw
            def encode(self, raw, _): return raw
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source, mod = root / "source", root / "mod"
            for name, content in (("Pack/ZsDic.pack.zs", b"unused dictionary"),
                                  (native_setup.GAME_DATA, byml.dump(doc))):
                target = source / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(content)
            key = zlib.crc32(native_setup.GAME_DATA.removesuffix(".zs").encode())
            rest = b"RESTBL" + struct.pack("<6I", 1, 160, 1, 0, key, 65536)
            target = mod / native_setup.REST; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(rest)
            with patch.object(native_setup, "Codec", IdentityCodec), patch.object(cursor_resource, "register_chest_flags", wraps=register_chest_flags) as repair:
                native_setup.bind_romfs(source, mod, data, 0)
            repair.assert_called_once()
            self.assertEqual(repair.call_args.args[1], expected)
            self.assertGreater(allocation(target.read_bytes(), native_setup.GAME_DATA), 65536)
            self.assertEqual((mod / native_setup.MARKER).read_text().strip(), data["token"])
            all_names = [name for name, row in ADDITIONAL_SOURCES.items() if row.get("native_route") == "frozen_chest"]
            all_data = data | {"checks": all_names, "additional_sources": all_names}
            original = (source / native_setup.GAME_DATA).read_bytes()
            with patch.object(native_setup, "Codec", IdentityCodec):
                self.assertTrue(native_setup.prepare_chest_flags(source, mod, all_data))
                repaired = (mod / native_setup.GAME_DATA).read_bytes()
                repaired_rest = target.read_bytes()
                self.assertFalse(native_setup.prepare_chest_flags(source, mod, all_data))
                self.assertEqual((mod / native_setup.GAME_DATA).read_bytes(), repaired)
                self.assertEqual(target.read_bytes(), repaired_rest)
                self.assertFalse(native_setup.prepare_chest_flags(source, mod, {"token": "old room"}))
            self.assertEqual((source / native_setup.GAME_DATA).read_bytes(), original)


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
