"""Inner actor-pack budgets use native peers and stay safe when shared/repeated."""
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client"))
from oot_rando.game.resource_allocations import allocation, reserve_packed_resources


def table(entries=(), names=()):
    raw = b"RESTBL" + struct.pack("<IIII", 1, 160, len(entries), len(names))
    for path, size in sorted(entries, key=lambda row: zlib.crc32(row[0].encode())):
        raw += struct.pack("<II", zlib.crc32(path.encode()), size)
    for path, size in names:
        raw += path.encode().ljust(160, b"\0") + struct.pack("<I", size)
    return raw


ACTOR = "Actor/Native.engine__actor__ActorParam.bgyml"
ALIAS = "Actor/Alias.engine__actor__ActorParam.bgyml"
MODEL = "Component/ModelInfo/Native.engine__component__ModelInfo.bgyml"
NEW_MODEL = "Component/ModelInfo/Alias.engine__component__ModelInfo.bgyml"
ANIMATION = "Component/AnimationParam/Wallet.engine__component__AnimationParam.bgyml"
SPIN = "Component/AnimationParam/Item_AP_Spin.engine__component__AnimationParam.bgyml"


def job(path=ALIAS, data=b"x" * 1040, peer=ACTOR, peer_data=b"n" * 808):
    return dict(path=path, data=data, peer=peer, peer_data=peer_data)


class PackedResourceTests(unittest.TestCase):
    def test_real_actor_model_and_shared_animation_sizes(self):
        native = table([(ACTOR, 6312), (MODEL, 5320), (ANIMATION, 5464)])
        jobs = [job(), job(NEW_MODEL, b"m" * 128, MODEL, b"n" * 108),
                job(SPIN, b"s" * 140, ANIMATION, b"n" * 188)]
        result, records = reserve_packed_resources(native, native, jobs)
        self.assertEqual([allocation(result, p) for p in (ALIAS, NEW_MODEL, SPIN)], [7560, 6344, 5464])
        self.assertEqual([allocation(result, p) for p in (ACTOR, MODEL, ANIMATION)], [6312, 5320, 5464])
        self.assertEqual(len(records), 3)
        again, changes = reserve_packed_resources(result, native, jobs)
        self.assertEqual((again, changes), (result, []))

    def test_active_event_and_ai_peers_keep_parser_allowance(self):
        peer = "Component/EventPerformerParam/Pouch.engine__component__EventPerformerParam.bgyml"
        new = peer.replace("/Pouch.", "/Alias.")
        native = table([(peer, 5304), ("AI/Pouch.event.root.ainb", 115384)])
        result, _ = reserve_packed_resources(native, native, [
            job(new, b"x" * 156, peer, b"n" * 148),
            job("AI/Alias.event.root.ainb", b"x" * 116301, "AI/Pouch.event.root.ainb", b"n" * 114982)])
        self.assertEqual(allocation(result, new), 6328)
        self.assertEqual(allocation(result, "AI/Alias.event.root.ainb"), 117720)

    def test_no_shrink_existing_named_override_and_unrelated_entries(self):
        unrelated = "Actor/Other.engine__actor__ActorParam.bgyml"
        native = table([(ACTOR, 6312), (MODEL, 5320), (unrelated, 9000)])
        staged = table([(ACTOR, 6312), (MODEL, 5320), (unrelated, 9000)], [(ALIAS, 20000)])
        self.assertEqual(reserve_packed_resources(staged, native, [job()]), (staged, []))
        result, records = reserve_packed_resources(staged, native,
            [job(), job(NEW_MODEL, b"m" * 128, MODEL, b"n" * 108)])
        self.assertEqual(len(records), 1)
        self.assertEqual(allocation(result, ALIAS), 20000)
        self.assertEqual(allocation(result, NEW_MODEL), 6344)
        self.assertEqual(allocation(result, ACTOR), 6312)
        self.assertEqual(allocation(result, MODEL), 5320)
        self.assertEqual(allocation(result, unrelated), 9000)

    def test_existing_native_member_grows_from_immutable_baseline_once(self):
        native = table([(ACTOR, 6312)])
        jobs = [job(path=ACTOR)]
        result, _ = reserve_packed_resources(native, native, jobs)
        self.assertEqual(allocation(result, ACTOR), 7560)
        self.assertEqual(reserve_packed_resources(result, native, jobs), (result, []))

    def test_identical_shared_members_coalesce_and_different_peers_take_maximum(self):
        other = ANIMATION.replace("/Wallet.", "/Other.")
        native = table([(ANIMATION, 5464), (other, 8000)])
        first = job(SPIN, b"s" * 140, ANIMATION, b"n" * 188)
        second = job(SPIN, first["data"], other, b"o" * 188)
        result, records = reserve_packed_resources(native, native, [first, first.copy(), second])
        self.assertEqual(allocation(result, SPIN), 8000)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["peers"], sorted([ANIMATION, other]))

    def test_shared_byte_and_peer_provenance_conflicts_are_transactional(self):
        native = table([(ACTOR, 6312)])
        for second in [job(data=b"y" * 1040), job(path=ALIAS.replace("Alias", "Other"), peer_data=b"q" * 808)]:
            with self.subTest(second=second["path"]), self.assertRaisesRegex(ValueError, "Conflicting"):
                reserve_packed_resources(native, native, [job(), second])
        self.assertEqual(allocation(native, ALIAS), None)

    def test_missing_zero_undersized_and_ambiguous_native_peers_rejected(self):
        for native in [table(), table([(ACTOR, 0)]), table([(ACTOR, 100)]),
                       table([(ACTOR, 6312), (ACTOR, 6312)]),
                       table(names=[(ACTOR, 6312), (ACTOR, 6312)])]:
            with self.subTest(native_size=len(native)), self.assertRaises(ValueError):
                reserve_packed_resources(table(), native, [job()])

    def test_ambiguous_effective_target_rejected(self):
        native = table([(ACTOR, 6312)])
        staged = table([(ALIAS, 2000), (ALIAS, 3000)])
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            reserve_packed_resources(staged, native, [job()])

    def test_alias_cannot_overwrite_an_unrelated_native_allocation(self):
        native = table([(ACTOR, 6312), (ALIAS, 10000)])
        with self.assertRaisesRegex(ValueError, "collides with a native"):
            reserve_packed_resources(native, native, [job()])

    def test_generated_crc_collision_is_rejected_before_any_reservation(self):
        native = table([(ACTOR, 6312)])
        other = ALIAS.replace("Alias", "Other")
        original_crc = zlib.crc32
        def collision(value):
            return 123 if value in {ALIAS.encode(), other.encode()} else original_crc(value)
        with patch("oot_rando.game.resource_allocations.zlib.crc32", side_effect=collision):
            with self.assertRaisesRegex(ValueError, "CRC collision"):
                reserve_packed_resources(native, native, [job(), job(path=other)])
        self.assertIsNone(allocation(native, ALIAS))

    def test_overflow_and_incompatible_resource_kinds_rejected(self):
        native = table([(ACTOR, 0xffffffff), (MODEL, 5320)])
        with self.assertRaisesRegex(ValueError, "too large"):
            reserve_packed_resources(native, native, [job(data=b"x" * 33, peer_data=b"n")])
        with self.assertRaisesRegex(ValueError, "kinds differ"):
            reserve_packed_resources(native, native, [job(peer=MODEL, peer_data=b"n" * 108)])

    def test_soft_actor_names_bad_paths_empty_bytes_and_bad_records_rejected(self):
        native = table([(ACTOR, 6312)])
        for path in ["?ActorSystem/ActorName/Alias.engine__actor__ActorName.bgyml",
                     "ActorSystem/ActorName/Alias.engine__actor__ActorName.bgyml",
                     "Work/" + ALIAS, "../" + ALIAS, ALIAS.replace("/", "\\"), ALIAS + ".zs"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                reserve_packed_resources(native, native, [job(path=path)])
        for bad in [job(data=b""), job(peer_data=b""), job(data=123), {}, "not a resource"]:
            with self.subTest(bad=type(bad).__name__), self.assertRaises(ValueError):
                reserve_packed_resources(native, native, [bad])

    def test_malformed_tables_rejected_even_with_no_jobs(self):
        native = table([(ACTOR, 6312)])
        for bad in [b"", native[:-1], b"WRONG!" + native[6:]]:
            with self.assertRaises(ValueError):
                reserve_packed_resources(bad, native, [])
            with self.assertRaises(ValueError):
                reserve_packed_resources(native, bad, [])
        self.assertEqual(reserve_packed_resources(native, native, []), (native, []))


if __name__ == "__main__":
    unittest.main()
