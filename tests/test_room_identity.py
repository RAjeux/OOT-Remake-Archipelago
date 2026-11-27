"""New logic/features bind the save identity; released legacy tokens stay exact."""
import hashlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.master_sword import token_material
from ootrr_triforce.room_identity import token


class RoomIdentityTests(unittest.TestCase):
    def test_legacy_tokens_are_byte_for_byte_unchanged_with_and_without_sword_shuffle(self):
        for sword in (False, True):
            expected = hashlib.sha256(token_material("room", 2, "checksum", sword).encode()).hexdigest()
            self.assertEqual(token("room", 2, "checksum", sword), expected)

    def test_json_mapping_order_does_not_change_the_bound_room(self):
        self.assertEqual(token("room", 2, "sum", features={"schema": 1, "settings": {"a": True, "b": 2}},
                               access_logic={"schema": 1, "world": {"a": 1, "b": 2}}),
                         token("room", 2, "sum", features={"settings": {"b": 2, "a": True}, "schema": 1},
                               access_logic={"world": {"b": 2, "a": 1}, "schema": 1}))

    def test_features_and_graph_changes_cannot_reuse_the_old_save_identity(self):
        base = token("room", 2, "sum")
        empty = token("room", 2, "sum", features={"schema": 1, "settings": {}}, access_logic={"schema": 1})
        feature = token("room", 2, "sum", features={"schema": 1, "settings": {"free_scarecrow": True}}, access_logic={"schema": 1})
        graph = token("room", 2, "sum", features={"schema": 1, "settings": {}}, access_logic={"schema": 2})
        self.assertEqual(len({base, empty, feature, graph}), 4)

    def test_slot_and_donor_checksum_remain_part_of_new_identity(self):
        args = dict(features={}, access_logic={})
        self.assertNotEqual(token("room", 1, "sum", **args), token("room", 2, "sum", **args))
        self.assertNotEqual(token("room", 1, "sum", **args), token("room", 1, "other", **args))


if __name__ == "__main__":
    unittest.main()
