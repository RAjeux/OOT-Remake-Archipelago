"""Complete actor-pack budgets prevent real full-mode map-load stalls."""
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client'))
from ootrr_triforce.full_allocations import reconcile
from ootrr_full.game.resource_allocations import allocation


def resource_table(values):
    rows = sorted((zlib.crc32(path.encode()), size) for path, size in values.items())
    return b'RESTBL' + struct.pack('<IIII', 1, 160, len(rows), 0) + b''.join(struct.pack('<II', *row) for row in rows)


class NativeBudgetTests(unittest.TestCase):
    def test_grown_player_brain_keeps_native_overhead_and_is_idempotent(self):
        name = 'AI/Player.brain.root.ainb'
        original = resource_table({name: 984, 'AI/Unrelated.ainb': 65536})
        resources = {name: (800, 4540)}
        changed, report = reconcile(original, original, resources, known_paths=[name])
        self.assertGreaterEqual(allocation(changed, name), 984 + 3740)
        self.assertEqual(allocation(changed, 'AI/Unrelated.ainb'), 65536)
        self.assertEqual(len(report), 1)
        again, report = reconcile(changed, original, resources, known_paths=[name])
        self.assertEqual(again, changed)
        self.assertEqual(report, [])

    def test_new_packed_modules_get_their_own_native_allocation(self):
        original = resource_table({'Pack/Actor/Native.pack': 4096})
        path = 'AI/NewCheck.event.root.ainb'
        changed, _ = reconcile(original, original, {path: (None, 116301)}, known_paths=[])
        self.assertGreaterEqual(allocation(changed, path), 116301 + 4096)

    def test_existing_generous_allocation_is_preserved(self):
        name = 'AI/Shared.ainb'
        original = resource_table({name: 65536})
        result, report = reconcile(original, original, {name: (None, 1024)}, known_paths=[name])
        self.assertEqual(result, original)
        self.assertEqual(report, [])

    def test_real_crc_collision_preserves_both_resources(self):
        native = 'PreComputedCulling/RuntimeId/30e292bcb6202da0.bcul'
        custom = 'Pack/Actor/Item_AP_87453e16f93e.pack'
        self.assertEqual(zlib.crc32(native.encode()), zlib.crc32(custom.encode()))
        original = resource_table({native: 109944})
        changed, _ = reconcile(original, original, {custom: (None, 8192)}, known_paths=[native])
        self.assertEqual(allocation(changed, native), 109944)
        self.assertGreaterEqual(allocation(changed, custom), 8192 + 4096)
        again, report = reconcile(changed, original, {custom: (None, 8192)}, known_paths=[native])
        self.assertEqual(again, changed)
        self.assertEqual(report, [])

    def test_unproved_collision_and_invalid_budget_fail_before_publication(self):
        custom = 'Pack/Actor/Item_AP_87453e16f93e.pack'
        original = resource_table({custom: 109944})
        with self.assertRaisesRegex(ValueError, 'unambiguous'):
            reconcile(original, original, {custom: (None, 8192)}, known_paths=[])
        for old, new in ((-1, 1), (1, True), (1, 1 << 32), (1, 0)):
            with self.subTest(old=old, new=new), self.assertRaises(ValueError):
                reconcile(original, original, {custom: (old, new)}, known_paths=[])


@unittest.skipUnless(os.environ.get('OOT_NUP') and os.environ.get('OOT_FULL_ARTIFACT'), 'native artifact not selected')
class NativeArtifactBudgets(unittest.TestCase):
    def test_every_composed_pack_is_budgeted_and_a_second_audit_changes_nothing(self):
        from ootrr_triforce import app_runtime
        from ootrr_triforce.full_allocations import prepare_allocations
        previous = app_runtime._resource_override
        app_runtime._resource_override = ROOT / 'dist'
        self.addCleanup(setattr, app_runtime, '_resource_override', previous)
        with tempfile.TemporaryDirectory(prefix='ap-budgets-') as temporary:
            artifact = Path(temporary) / 'Archipelago'
            shutil.copytree(os.environ['OOT_FULL_ARTIFACT'], artifact)
            report = prepare_allocations(os.environ['OOT_ROMFS'], artifact, game_source=os.environ['OOT_NUP'])
            self.assertGreater(report['resources'], 1000)
            again = prepare_allocations(os.environ['OOT_ROMFS'], artifact, game_source=os.environ['OOT_NUP'])
            self.assertEqual(again['changed'], [])


if __name__ == '__main__':
    unittest.main()
