"""Older saves keep finite purchases and frog-game progression consistent."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client'))

from evfl.entry_point import EntryPoint
from evfl.util import make_index
from oot_rando.patching.progressive import FlowEditor
from ootrr_triforce.full_extra_recovery import append_reconcile, FROG_FLAGS, BEAN_FLAGS
from test_receipt_events import native_flow
from test_restoration import SaveRun


def model(name):
    editor = FlowEditor(native_flow(), 'Additional native quest recovery')
    save = editor.action('ExtraFixtureSave', 'GameSystemActor', 'EventTriggerRequestAutoSave', None)
    root = append_reconcile(editor, {'name': name, 'id': 12345}, save)
    point = EntryPoint('ExtraFixture')
    point.main_event = make_index(root)
    editor.chart.entry_points.append(point)
    return SaveRun(editor.write('Additional native quest recovery')[0])


class ExtraRecoveryTests(unittest.TestCase):
    def test_bean_purchases_rebuild_the_counter_without_buying_or_giving_again(self):
        for purchased in (0, 1, 5, 9, 10):
            run = model('ZR Magic Bean Salesman 1')
            run.values.update({flag: index < purchased for index, flag in enumerate(BEAN_FLAGS)})
            run.values['Get_MagicBeans'] = 10 - purchased
            run.run('ExtraFixture')
            self.assertEqual(run.values['Get_MagicBeans'], purchased)
            self.assertFalse(run.inventory)
            run.run('ExtraFixture')
            self.assertEqual(run.values['Get_MagicBeans'], purchased)
            self.assertEqual(run.saves[-1][0]['Get_MagicBeans'], purchased)

    def test_frog_song_flags_restore_count_and_unlock_the_bug_game_only_after_all_songs(self):
        for played in (0, 1, 5, 6):
            run = model('ZR Frogs Zeldas Lullaby')
            run.values.update({flag: index < played for index, flag in enumerate(FROG_FLAGS)})
            run.values['MiniGame_FrogTenors_GetCount'] = 99
            run.run('ExtraFixture')
            self.assertEqual(run.values['MiniGame_FrogTenors_GetCount'], played)
            self.assertEqual(run.values['MiniGame_FrogTenors_SongClear'], played == 6)
            self.assertFalse(run.inventory)
            run.run('ExtraFixture')
            self.assertEqual(run.values['MiniGame_FrogTenors_GetCount'], played)


if __name__ == '__main__':
    unittest.main()
