"""Collision safety and transaction boundaries in full-network native resources."""
import struct
import sys
from pathlib import Path
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_full.game.resource_allocations import add_resources, allocation, grow_resources


class ResourceCollisionTests(unittest.TestCase):
    def test_real_crc_collision_keeps_both_native_allocations(self):
        original = "PreComputedCulling/RuntimeId/30e292bcb6202da0.bcul"
        added = "Pack/Actor/Item_AP_87453e16f93e.pack"
        self.assertEqual(zlib.crc32(original.encode()), zlib.crc32(added.encode()))
        other = "Event/EventFlow/OpeningEvent.bfevfl"
        entries = sorted([(zlib.crc32(original.encode()), 109944), (zlib.crc32(other.encode()), 2048)])
        raw = b"RESTBL" + struct.pack("<IIII", 1, 160, len(entries), 0)
        raw += b"".join(struct.pack("<II", *entry) for entry in entries)
        changed, _ = add_resources(raw, {added + ".zs": 8192}, known_paths=[original + ".zs", other])
        self.assertEqual(allocation(changed, original), 109944)
        self.assertEqual(allocation(changed, added), 8192)
        self.assertEqual(allocation(changed, other), 2048)
        grown, _ = grow_resources(changed, {added + ".zs": 1})
        self.assertEqual(allocation(grown, added), 12288)
        self.assertEqual(allocation(grown, original), 109944)
        with self.assertRaisesRegex(ValueError, "unambiguous"):
            add_resources(raw, {added: 8192})

    def test_existing_named_resource_is_never_silently_replaced(self):
        path = "Pack/Actor/Test.pack"
        raw = b"RESTBL" + struct.pack("<IIII", 1, 160, 0, 1)
        raw += path.encode().ljust(160, b"\0") + struct.pack("<I", 1024)
        with self.assertRaisesRegex(ValueError, "Existing"):
            add_resources(raw, {path + ".zs": 9999}, known_paths=[path])


if __name__ == "__main__":
    unittest.main()
