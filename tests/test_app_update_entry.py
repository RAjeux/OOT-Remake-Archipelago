"""The updater helper bypasses the GUI; completion failures keep it usable."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
spec = importlib.util.spec_from_file_location("desktop_entry", ROOT / "client/app.py")
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


class ApplicationUpdateEntryTests(unittest.TestCase):
    def test_filename_finalizer_never_initializes_runtime_or_opens_gui(self):
        with patch.object(sys, "argv", ["app", "--finalize-update", "private-plan.json"]), \
             patch("ootrr_triforce.update_finalize.helper_main", return_value=0) as helper, \
             patch("ootrr_triforce.app_runtime.initialize") as initialize, \
             patch("ootrr_triforce.app_window.main") as window:
            self.assertEqual(entry.main(), 0)
        helper.assert_called_once_with(Path("private-plan.json"))
        initialize.assert_not_called()
        window.assert_not_called()

    def test_filename_handoff_exits_before_opening_the_old_named_window(self):
        with patch.object(sys, "argv", ["app", "--complete-update", "private-plan.json"]), \
             patch("ootrr_triforce.app_runtime.initialize"), \
             patch("ootrr_triforce.update_service.complete_update", return_value={"restart_scheduled": True}), \
             patch("ootrr_triforce.app_window.main") as window:
            self.assertEqual(entry.main(), 0)
        window.assert_not_called()

    def test_helper_runs_before_runtime_and_never_opens_the_main_window(self):
        with patch.object(sys, "argv", ["app", "--apply-update", "private-plan.json"]), \
             patch("ootrr_triforce.update_service.helper_main", return_value=0) as helper, \
             patch("ootrr_triforce.app_runtime.initialize") as initialize, \
             patch("ootrr_triforce.app_window.main") as window:
            self.assertEqual(entry.main(), 0)
        helper.assert_called_once_with(Path("private-plan.json"))
        initialize.assert_not_called()
        window.assert_not_called()

    def test_completion_uses_new_runtime_before_opening_window(self):
        events = []
        notice = dict(world_updated=True, world_path="private/custom_worlds/ootrr_remake.apworld")
        with patch.object(sys, "argv", ["app", "--complete-update", "private-plan.json"]), \
             patch("ootrr_triforce.app_runtime.initialize", side_effect=lambda: events.append("new-runtime")), \
             patch("ootrr_triforce.update_service.complete_update", side_effect=lambda path: events.append("complete") or notice), \
             patch("ootrr_triforce.app_window.main", side_effect=lambda **kwargs: events.append(kwargs)):
            self.assertEqual(entry.main(), 0)
        self.assertEqual(events, ["new-runtime", "complete", {"startup_notice": notice}])

    def test_helper_failure_is_logged_without_initializing_or_showing_gui(self):
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "diagnostics/application.log"
            with patch.object(sys, "argv", ["app", "--apply-update", "private-plan.json"]), \
                 patch("ootrr_triforce.update_service.helper_main", side_effect=OSError("Synthetic locked target")), \
                 patch("ootrr_triforce.app_runtime.log_path", return_value=log), \
                 patch("ootrr_triforce.app_runtime.initialize") as initialize, \
                 patch("ootrr_triforce.app_window.main") as window:
                self.assertEqual(entry.main(), 1)
            self.assertIn("Synthetic locked target", log.read_text(encoding="utf-8"))
            initialize.assert_not_called()
            window.assert_not_called()

    def test_optional_completion_failure_does_not_close_the_updated_app(self):
        with patch.object(sys, "argv", ["app", "--complete-update", "missing-plan.json"]), \
             patch("ootrr_triforce.app_runtime.initialize"), \
             patch("ootrr_triforce.update_service.complete_update", side_effect=ValueError("Synthetic missing plan")), \
             patch.object(entry.logging, "exception"), \
             patch("ootrr_triforce.app_window.main") as window:
            self.assertEqual(entry.main(), 0)
        self.assertEqual(window.call_args.kwargs["startup_notice"]["error_code"], "update_completion_failed")

    def test_test_and_update_modes_cannot_be_combined(self):
        with patch.object(sys, "argv", ["app", "--self-test", "result", "--apply-update", "plan"]), \
             patch.object(sys, "stderr"):
            with self.assertRaises(SystemExit) as failure:
                entry.main()
        self.assertEqual(failure.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
