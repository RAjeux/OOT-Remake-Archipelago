"""Windows WASI must see long-path overlays and publish only successful edits."""
from contextlib import nullcontext
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib
from types import SimpleNamespace

import zstandard

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce import engine
from oot_rando.formats import byml_codec as by

TABLE = "System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs"
MAP = "Banc/Fixture/Fixture_Adult_Dynamic.bcett.byml.zs"
SECOND_MAP = "Banc/Fixture/Fixture_Child_Dynamic.bcett.byml.zs"
ACTOR = 12786193094758345086


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def encoded(value):
    return zstandard.ZstdCompressor().compress(value)


def banc(drop):
    return encoded(by.dump(dict(version=7, endian="<", root=dict(Actors=[dict(Hash=by.U64(ACTOR), Dynamic={"Drop__DropActor": drop})]))))


def table():
    rows = sorted((zlib.crc32(name.removesuffix(".zs").encode()), 65536) for name in (MAP, SECOND_MAP))
    return encoded(b"RESTBL" + struct.pack("<4I", 1, 160, len(rows), 0) + b"".join(struct.pack("<II", *row) for row in rows))


def decode_engine_raw_frame(frame):
    # The engine writes raw Zstandard blocks tagged with the game's dictionary
    # ID. This synthetic game has no real dictionary; raw blocks do not refer
    # to one, so remove that header field for independent fixture decoding.
    frame = bytearray(frame)
    size = (0, 1, 2, 4)[frame[4] & 3]
    at = 5 if frame[4] & 0x20 else 6
    frame[4] &= ~3
    del frame[at:at + size]
    return zstandard.ZstdDecompressor().decompress(frame)


class WindowsEnginePathTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="ap-path-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.game = self.root / "game"
        self.mod = self.root / ("long_" + "x" * 170) / "load/Archipelago/romfs"
        put(self.game / "Pack/ZsDic.pack.zs", encoded(by.build_sarc({})))
        for name in (MAP, SECOND_MAP):
            put(self.game / name, banc("TBox_Rupee_Blue"))
            put(self.mod / name, banc("Obj_Heart_Piece"))
        put(self.mod / TABLE, table())
        self.assertGreater(len(str(self.mod / MAP)), 260)

    def request(self, both=False):
        files = {MAP: [dict(actor=str(ACTOR), drop="TBox_Rupee_Green", expected=["Obj_Heart_Piece"])]}
        if both:
            files[SECOND_MAP] = [dict(actor=str(ACTOR), drop="TBox_Rupee_Green", expected=["UnrelatedActor"])]
        return dict(files=files)

    @unittest.skipUnless(os.environ.get("OOTRR_NODE") or shutil.which("node"), "requires Node for the actual WASM")
    def test_long_overlay_is_read_instead_of_falling_back_to_vanilla(self):
        result = engine.run_engine("patch", self.request(), self.game, self.mod)
        self.assertIn("Patched 1 physical chest", result)
        raw = decode_engine_raw_frame((self.mod / MAP).read_bytes())
        actor = by.load(raw)["root"]["Actors"][0]
        self.assertEqual(actor["Dynamic"]["Drop__DropActor"], "TBox_Rupee_Green")
        original = by.load(zstandard.ZstdDecompressor().decompress((self.game / MAP).read_bytes()))
        self.assertEqual(original["root"]["Actors"][0]["Dynamic"]["Drop__DropActor"], "TBox_Rupee_Blue")

    @unittest.skipUnless(os.name == "nt" and (os.environ.get("OOTRR_NODE") or shutil.which("node")), "requires Windows WASI staging")
    def test_engine_failure_does_not_copy_back_an_earlier_partial_edit(self):
        before = {name: (self.mod / name).read_bytes() for name in (MAP, SECOND_MAP, TABLE)}
        with self.assertRaisesRegex(RuntimeError, "UnrelatedActor|unexpected chest reward"):
            engine.run_engine("patch", self.request(both=True), self.game, self.mod)
        self.assertEqual(before, {name: (self.mod / name).read_bytes() for name in before})

    @unittest.skipUnless(os.name == "nt", "requires Windows WASI staging")
    def test_loader_namespace_includes_sibling_tables_and_new_shop_files(self):
        load = self.mod.parent.parent
        put(load / "Cosmetics/romfs" / TABLE, b"sibling resource table")
        with engine._wasi_paths("shops", (self.game, self.mod)) as paths:
            short_mod = Path(paths[1])
            short_load = short_mod.parent.parent
            self.assertNotEqual(short_mod, self.mod)
            self.assertEqual((short_load / "Cosmetics/romfs" / TABLE).read_bytes(), b"sibling resource table")
            put(short_load / "Archipelago/romfs/Pack/NewShop.pack.zs", b"new shelf")
        self.assertEqual((self.mod / "Pack/NewShop.pack.zs").read_bytes(), b"new shelf")
        self.assertEqual((load / "Cosmetics/romfs" / TABLE).read_bytes(), b"sibling resource table")

    @unittest.skipUnless(os.name == "nt", "requires Windows WASI staging")
    def test_a_long_temporary_folder_is_rejected_before_reading_vanilla(self):
        temporary = self.root / ("temp_" + "y" * 190)
        temporary.mkdir()
        before = (self.mod / MAP).read_bytes()
        with patch.object(engine.tempfile, "TemporaryDirectory", return_value=nullcontext(str(temporary))):
            with self.assertRaises(engine.EnginePathError) as error:
                with engine._wasi_paths("patch", (self.game, self.mod)):
                    self.fail("WASI must not start with an unusable temporary path")
        self.assertIn("temporary folder path is too long", error.exception.public_message)
        self.assertEqual((self.mod / MAP).read_bytes(), before)

    @unittest.skipUnless(os.name == "nt", "requires Windows WASI staging")
    def test_a_temporary_folder_inside_the_loader_cannot_be_copied_recursively(self):
        temporary = self.mod.parent.parent / "nested-temp"
        temporary.mkdir()
        with patch.object(engine.tempfile, "TemporaryDirectory", return_value=nullcontext(str(temporary))):
            with self.assertRaises(engine.EnginePathError):
                with engine._wasi_paths("patch", (self.game, self.mod)):
                    self.fail("A recursive projection must not start")


class NativeFileIndexTests(unittest.TestCase):
    def test_feature_and_cosmetic_passes_receive_private_relative_file_indexes(self):
        with tempfile.TemporaryDirectory(prefix="ap-index-") as folder:
            root = Path(folder)
            game, mod = root / "game", root / "stage"
            put(game / "Pack/Original.pack.zs", b"original")
            put(mod / "Banc/Changed.byml.zs", b"overlay")
            calls = []

            def run(arguments, **kwargs):
                metadata = Path(arguments[-1]) / "files.json"
                self.assertTrue(metadata.is_file())
                self.assertEqual(json.loads(metadata.read_text()), dict(schema=1, files={
                    "game": ["Pack/Original.pack.zs"], "mod": ["Banc/Changed.byml.zs"]}))
                self.assertNotEqual(metadata.parent, game)
                self.assertNotEqual(metadata.parent, mod)
                calls.append(metadata)
                return SimpleNamespace(returncode=0, stdout=b"prepared", stderr=b"")

            with patch.object(engine, "bundled_node", return_value="node"), patch.object(engine, "run_process", side_effect=run):
                for command in ("features", "cosmetics", "portable-geometry"):
                    self.assertEqual(engine.run_engine(command, {}, game, mod), "prepared")
            self.assertEqual(len(calls), 3)
            self.assertTrue(all(not metadata.exists() for metadata in calls), "Indexes must be removed after preparation.")
            self.assertEqual((game / "Pack/Original.pack.zs").read_bytes(), b"original")
            self.assertEqual((mod / "Banc/Changed.byml.zs").read_bytes(), b"overlay")


if __name__ == "__main__":
    unittest.main()
