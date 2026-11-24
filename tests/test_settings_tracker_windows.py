"""The full settings editor and passive tracker work with actual Tk widgets."""
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.settings_editor import PlayerConfiguration, SettingsEditorWindow
from ootrr_triforce.room_windows import ProgressWindow


class SettingsAndTrackerWidgets(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.profile = Path(self.temp.name) / ("a" * 64)
        self.profile.mkdir()
        self.window = None
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except tk.TclError as error:
            self.temp.cleanup()
            self.skipTest(str(error))

    def tearDown(self):
        if self.window and not self.window.closed:
            self.window.close()
        elif not self.window:
            self.root.destroy()
        self.temp.cleanup()

    def pump(self, condition, timeout=4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.root.update()
            if condition():
                return
            time.sleep(.005)
        self.fail("Tracker worker did not finish")

    def test_full_editor_applies_validated_settings_and_cancels_without_mutation(self):
        document = PlayerConfiguration.new("full_network")
        applied = []
        self.window = SettingsEditorWindow(self.root, document, language="fr", on_apply=applied.append)
        self.assertEqual(self.root.title(), "Paramètres du joueur")
        self.window.variables["death_link"].set("true")
        self.window.variables["full_tokensanity"].set("overworld")
        self.window.apply()
        self.assertEqual(len(applied), 1)
        self.assertTrue(applied[0].values["death_link"])
        self.assertEqual(applied[0].values["full_tokensanity"], "overworld")
        self.assertFalse(document.values["death_link"])
        self.assertEqual(document.values["full_tokensanity"], "all")

    def test_editor_mode_switch_preserves_archipelago_common_options(self):
        document = PlayerConfiguration.new("legacy")
        document.values["local_items"] = ["Kokiri Sword"]
        document.common["description"] = "Keep me"
        self.window = SettingsEditorWindow(self.root, document)
        self.window.mode_choice.current(self.window.mode_ids.index("full_network"))
        self.window.change_mode()
        self.assertEqual(self.window.document.common["description"], "Keep me")
        self.assertEqual(self.window.document.values["local_items"], ["Kokiri Sword"])
        self.window.preset_choice.current(1)
        self.window.apply_preset()
        self.assertEqual(self.window.document.values["local_items"], ["Kokiri Sword"])
        self.assertEqual(self.window.document.values["full_shopsanity"], "all")

    def test_tracker_filters_actual_state_without_changing_a_save_or_check(self):
        calls = []
        save = self.profile / "user/save/account/slot_00/progress.sav"
        save.parent.mkdir(parents=True)
        save.write_bytes(b"unchanged-save")
        class Provider:
            def __init__(self, profile, artifact):
                calls.append(("init", threading.get_ident()))
            def refresh(self, path):
                calls.append((path, threading.get_ident()))
                return {"slot": "Link", "checked": 1, "total": 2,
                        "locations": [{"id": 1, "name": "Kokiri chest", "checked": True, "access": "available"},
                                      {"id": 2, "name": "Forest chest", "checked": False, "access": "blocked"}],
                        "saves": [str(save)], "inventory": [{"name": "Bow", "count": 1, "known": True}],
                        "keys": [("Forest Temple", (1, 5), False)], "souls": [], "tracking_status": "Inventory and access are read from the selected save."}
        self.window = ProgressWindow(self.root, self.profile, provider_factory=Provider)
        self.pump(lambda: len(self.window.list.get_children()) == 2)
        self.assertEqual(len(self.window.inventory.get_children()), 1)
        first = self.window.inventory.get_children()[0]
        self.assertEqual(self.window.inventory.item(first, 'values'), ('1', 'Recorded progression'))
        self.window.hide_completed.set(True)
        self.window.render()
        self.assertEqual(self.window.list.get_children(), ("2",))
        self.window.search.set("Kokiri")
        self.assertEqual(self.window.list.get_children(), ())
        self.assertEqual(save.read_bytes(), b"unchanged-save")
        self.assertTrue(all(thread != threading.get_ident() for _operation, thread in calls))

    def test_tracker_distinguishes_saved_stock_and_recorded_progression_in_french(self):
        class Provider:
            def __init__(self, *_args):
                pass
            def refresh(self, _path):
                return {'slot': 'Link', 'checked': 0, 'total': 0, 'locations': [], 'saves': [],
                        'keys': [], 'souls': [], 'tracking_status': '', 'inventory': [
                            {'name': 'Deku Shield', 'count': 0, 'known': True, 'observation': 'Observed stock'},
                            {'name': 'Hylian Shield', 'count': 0, 'known': False, 'observation': 'Stock unavailable'},
                            {'name': 'Bow', 'count': 1, 'known': True, 'observation': 'Recorded progression'}]}
        self.window = ProgressWindow(self.root, self.profile, language='fr', provider_factory=Provider)
        self.pump(lambda: len(self.window.inventory.get_children()) == 3)
        rows = [self.window.inventory.item(ident, 'values') for ident in self.window.inventory.get_children()]
        self.assertEqual(rows, [('0', 'Stock observé'), ('Inconnu', 'Stock non disponible'),
                                ('1', 'Progression enregistrée')])
        self.assertEqual(self.window.inventory.heading('observation', 'text'), 'Observation')


if __name__ == "__main__":
    unittest.main()
