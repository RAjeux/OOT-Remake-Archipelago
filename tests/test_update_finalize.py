"""Schema-1 incoming completion: real file transactions and separate identities."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce import update_finalize as finish, update_service as updates
from test_update_service import executable, world


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class FinalizationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="filename update é ")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.base = self.home / "private app data"
        self.stage = self.base / "updates" / ("a" * 32)
        self.stage.mkdir(parents=True)
        self.folder = self.home / "portable launcher"
        self.folder.mkdir()
        self.old, self.new = executable(b"OLD 0.10.4"), executable(b"NEW fixed launcher")
        self.version = "2.0.0-alpha.1"
        self.source = self.folder / "OOT-Remake-Archipelago-1.0.0-alpha.1.exe"
        self.target = self.folder / ("OOT-Remake-Archipelago-" + self.version + ".exe")
        self.source.write_bytes(self.new)  # The released helper already replaced its bytes.
        incoming = self.stage / self.target.name
        incoming.write_bytes(self.new)
        apworld = self.stage / "ootrr_remake.apworld"
        apworld.write_bytes(world())
        helper = self.stage / "update-helper.exe"
        helper.write_bytes(self.old)
        self.backup = self.source.with_name(self.source.name + ".previous-" + "b" * 12 + ".exe")
        self.backup.write_bytes(self.old)
        self.original = dict(schema=updates.SCHEMA, base=str(self.base), stage=str(self.stage), version=self.version,
            executable=str(incoming), apworld=str(apworld), hashes=dict(executable=sha(self.new), apworld=sha(world())),
            target=str(self.source), original_sha256=sha(self.old), helper=str(helper),
            parents=[dict(pid=101, created=1, image=str(self.source))], backup=str(self.backup),
            adjacent=str(self.source.with_name("." + self.source.name + ".update-" + "c" * 32 + ".tmp")),
            world_target=None, state="applied")
        self.path = self.stage / "plan.json"
        self.write(self.path, self.original)
        self.sentinel = self.base / "profiles/room/save.sav"
        self.sentinel.parent.mkdir(parents=True)
        self.sentinel.write_bytes(b"untouched profile")
        self.versions = {sha(self.new): self.version, sha(self.old): "1.0.0-alpha.1"}
        for value in (patch.object(updates, "_file_version", side_effect=lambda path: {
                          "ProductName": updates.PRODUCT_NAME, "ProductVersion": self.versions[updates._sha(path)]}),
                      patch.object(updates, "current_version", return_value=self.version),
                      patch.object(updates, "_parent_processes", side_effect=lambda source: [dict(pid=202, created=2, image=str(source))])):
            value.start()
            self.addCleanup(value.stop)

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def prepare(self):
        plan = json.loads(self.path.read_bytes())
        def spawn(command, **kwargs):
            child = Path(command[-1])
            updates._ready(child, json.loads(child.read_bytes()))
            return Mock(poll=lambda: None)
        with patch.object(updates.sys, "executable", str(self.source)), \
             patch.object(finish.app_runtime, "spawn_process", side_effect=spawn) as started:
            result = finish.prepare_completion(self.path, plan, base=self.base)
        self.last_spawn = started
        return result

    def check_profile(self):
        self.assertEqual(self.sentinel.read_bytes(), b"untouched profile")

    def historical(self, digit, *, state="completed"):
        stage = self.base / "updates" / (digit * 32)
        stage.mkdir()
        version = "1.5.0-alpha.1"
        old = executable(("historical old " + digit).encode())
        incoming = executable(("historical incoming " + digit).encode())
        self.versions[sha(incoming)] = version
        self.versions[sha(old)] = "1.0.0-alpha.1"
        payload = stage / ("OOT-Remake-Archipelago-" + version + ".exe")
        payload.write_bytes(incoming)
        helper = stage / "update-helper.exe"
        helper.write_bytes(old)
        apworld = stage / "ootrr_remake.apworld"
        apworld.write_bytes(world())
        backup = self.source.with_name(self.source.name + ".previous-" + digit * 12 + ".exe")
        backup.write_bytes(old)
        plan = dict(self.original, stage=str(stage), version=version, executable=str(payload),
            apworld=str(apworld), helper=str(helper), original_sha256=sha(old), backup=str(backup), state=state,
            hashes=dict(executable=sha(incoming), apworld=sha(world())),
            completion=dict(version=version, backup=str(backup), world_updated=False))
        path = stage / "plan.json"
        self.write(path, plan)
        return path, plan, backup, old

    def test_archive_copies_to_private_folder_before_unlink_and_separates_old_new_hashes(self):
        calls = []
        original_rename, original_unlink = finish._rename, Path.unlink
        def rename(source, destination):
            self.assertEqual(source.parent, destination.parent, "No cross-volume rename may be required")
            self.assertNotEqual(source, self.backup)
            calls.append((source, destination))
            return original_rename(source, destination)
        def unlink(path, *args, **kwargs):
            if path == self.backup:
                self.assertEqual((self.stage / "previous-launcher.exe").read_bytes(), self.old)
            return original_unlink(path, *args, **kwargs)
        with patch.object(finish, "_rename", side_effect=rename), patch.object(Path, "unlink", unlink), \
             patch.object(updates, "_replace", side_effect=AssertionError("No cross-volume move")):
            result = self.prepare()
        self.assertTrue(result["restart_scheduled"])
        self.assertTrue(calls)
        self.assertFalse(self.backup.exists())
        self.assertEqual(Path(result["backup"]).read_bytes(), self.old)
        original = json.loads(self.path.read_bytes())
        child = json.loads(Path(result["plan"]).read_bytes())
        self.assertEqual(original["original_sha256"], sha(self.old))
        self.assertEqual(child["original_sha256"], sha(self.new))
        self.assertEqual(Path(child["helper"]).read_bytes(), self.new)
        self.assertEqual(child["original_plan_sha256"], updates._sha(self.path))
        self.assertEqual(self.last_spawn.call_args.args[0][1], "--finalize-update")
        self.assertEqual(self.last_spawn.call_args.kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")
        self.assertEqual(self.source.read_bytes(), self.new)
        self.assertFalse(self.target.exists())
        self.check_profile()

    def test_canonical_source_only_archives_and_is_idempotent(self):
        self.source.rename(self.target)
        self.source = self.target
        self.original.update(target=str(self.source), parents=[dict(pid=101, created=1, image=str(self.source))],
            backup=str(self.source.with_name(self.source.name + ".previous-" + "b" * 12 + ".exe")),
            adjacent=str(self.source.with_name("." + self.source.name + ".update-" + "c" * 32 + ".tmp")))
        self.backup.rename(Path(self.original["backup"]))
        self.backup = Path(self.original["backup"])
        self.write(self.path, self.original)
        self.assertIsNone(self.prepare())
        self.last_spawn.assert_not_called()
        before = self.path.read_bytes()
        self.assertIsNone(self.prepare())
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual((self.stage / "previous-launcher.exe").read_bytes(), self.old)
        self.check_profile()

    def test_wait_then_rename_restart_and_completed_legacy_replay(self):
        result = self.prepare()
        commands = []
        def wait(plan):
            self.assertEqual(self.source.read_bytes(), self.new)
            self.assertFalse(self.target.exists())
        def launch(command):
            self.assertEqual(json.loads(Path(result["plan"]).read_bytes())["state"], "applied")
            self.assertEqual(json.loads(self.path.read_bytes())["installed_target"], str(self.target))
            commands.append(command)
        applied = finish.apply_finalization(result["plan"], base=self.base, wait_parent=wait, launcher=launch)
        self.assertFalse(self.source.exists())
        self.assertEqual(self.target.read_bytes(), self.new)
        self.assertEqual(commands, [[str(self.target), "--complete-update", str(self.path)]])
        self.assertEqual(Path(applied["backup"]).read_bytes(), self.old)
        with patch.object(updates.sys, "executable", str(self.target)):
            notice = updates.complete_update(self.path, base=self.base)
            again = updates.complete_update(self.path, base=self.base)
        self.assertEqual(notice, again)
        self.assertEqual(notice["backup"], str(self.stage / "previous-launcher.exe"))
        self.assertEqual([path.name for path in self.folder.glob("*.exe")], [self.target.name])
        self.check_profile()

    def test_identical_existing_destination_is_reused(self):
        self.target.write_bytes(self.new)
        identity = self.target.stat().st_ino
        result = self.prepare()
        finish.apply_finalization(result["plan"], base=self.base, wait_parent=lambda plan: None, launcher=lambda command: None)
        self.assertFalse(self.source.exists())
        self.assertEqual(self.target.stat().st_ino, identity)
        self.assertEqual(self.target.read_bytes(), self.new)
        self.check_profile()

    def test_unrelated_destination_is_never_overwritten_even_if_created_while_waiting(self):
        result = self.prepare()
        def wait(plan):
            self.target.write_bytes(b"unrelated user file")
        with self.assertRaises(updates.UpdateError):
            finish.apply_finalization(result["plan"], base=self.base, wait_parent=wait)
        self.assertEqual(self.target.read_bytes(), b"unrelated user file")
        self.assertEqual(self.source.read_bytes(), self.new)
        self.assertNotIn("installed_target", json.loads(self.path.read_bytes()))
        self.check_profile()

    def test_existing_private_backup_is_not_overwritten_or_used_when_its_hash_is_wrong(self):
        private = self.stage / "previous-launcher.exe"
        private.write_bytes(b"unrelated private file")
        with self.assertRaises(updates.UpdateError):
            self.prepare()
        self.assertEqual(private.read_bytes(), b"unrelated private file")
        self.assertEqual(self.backup.read_bytes(), self.old)
        self.assertEqual(self.source.read_bytes(), self.new)

    def test_completed_owned_historical_backups_move_private_but_manual_copies_stay(self):
        path, historical, backup, old = self.historical("d")
        manual = self.folder / "My manual launcher copy.exe"
        manual.write_bytes(old)
        unregistered = self.source.with_name(self.source.name + ".previous-" + "f" * 12 + ".exe")
        unregistered.write_bytes(old)
        self.prepare()
        self.assertFalse(backup.exists())
        private = path.parent / "previous-launcher.exe"
        self.assertEqual(private.read_bytes(), old)
        recorded = json.loads(path.read_bytes())
        self.assertEqual(recorded["private_backup"], str(private))
        self.assertEqual(recorded["completion"]["backup"], str(private))
        self.assertEqual(recorded["state"], "completed")
        self.assertEqual(manual.read_bytes(), old)
        self.assertEqual(unregistered.read_bytes(), old)
        self.check_profile()

    def test_changed_historical_backup_and_active_transaction_are_preserved(self):
        path, historical, changed, old = self.historical("d")
        changed.write_bytes(b"changed by the user")
        active_path, _, active_backup, active_old = self.historical("e", state="applied")
        previous, active = path.read_bytes(), active_path.read_bytes()
        with self.assertLogs(level="WARNING"):
            result = self.prepare()
        self.assertTrue(result["restart_scheduled"], "Invalid history must not block the current update")
        self.assertEqual(changed.read_bytes(), b"changed by the user")
        self.assertEqual(active_backup.read_bytes(), active_old)
        self.assertEqual(path.read_bytes(), previous)
        self.assertEqual(active_path.read_bytes(), active)
        self.assertFalse((path.parent / "previous-launcher.exe").exists())
        self.assertFalse((active_path.parent / "previous-launcher.exe").exists())
        self.check_profile()

    def test_restart_failure_restores_filename_and_metadata(self):
        for identical in (False, True):
            with self.subTest(preexisting_identical=identical):
                if identical:
                    self.target.write_bytes(self.new)
                result = self.prepare()
                original = self.path.read_bytes()
                with self.assertRaises(OSError):
                    finish.apply_finalization(result["plan"], base=self.base, wait_parent=lambda plan: None,
                        launcher=Mock(side_effect=OSError("Could not restart")))
                self.assertEqual(self.source.read_bytes(), self.new)
                self.assertEqual(self.path.read_bytes(), original)
                self.assertEqual(self.target.exists(), identical)
                if identical:
                    self.assertEqual(self.target.read_bytes(), self.new)
                self.assertEqual((self.stage / "previous-launcher.exe").read_bytes(), self.old)
                self.assertEqual(json.loads(Path(result["plan"]).read_bytes())["state"], "failed")
        self.check_profile()

    def test_rename_failure_preserves_both_original_metadata_and_working_launcher(self):
        result = self.prepare()
        original = self.path.read_bytes()
        with patch.object(finish, "_rename", side_effect=PermissionError("Still locked")), self.assertRaises(PermissionError):
            finish.apply_finalization(result["plan"], base=self.base, wait_parent=lambda plan: None)
        self.assertEqual(self.source.read_bytes(), self.new)
        self.assertFalse(self.target.exists())
        self.assertEqual(self.path.read_bytes(), original)

    def test_metadata_failure_after_rename_rolls_back_before_any_restart(self):
        result = self.prepare()
        original = self.path.read_bytes()
        save = finish._save
        def reject_installed_target(path, value):
            if path == self.path and "installed_target" in value:
                raise OSError("Synthetic metadata write failure")
            return save(path, value)
        launch = Mock()
        with patch.object(finish, "_save", side_effect=reject_installed_target), self.assertRaises(OSError):
            finish.apply_finalization(result["plan"], base=self.base, wait_parent=lambda plan: None, launcher=launch)
        launch.assert_not_called()
        self.assertEqual(self.source.read_bytes(), self.new)
        self.assertFalse(self.target.exists())
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual((self.stage / "previous-launcher.exe").read_bytes(), self.old)
        self.check_profile()

    def test_cancelled_or_modified_plan_is_rechecked_after_wait(self):
        result = self.prepare()
        path = Path(result["plan"])
        def wait(plan):
            changed = json.loads(path.read_bytes())
            changed["state"] = "cancelled"
            self.write(path, changed)
        with self.assertRaises(updates.UpdateError):
            finish.apply_finalization(path, base=self.base, wait_parent=wait)
        self.assertEqual(self.source.read_bytes(), self.new)
        self.assertFalse(self.target.exists())

    def test_tampered_child_bindings_and_parent_identities_are_rejected(self):
        result = self.prepare()
        path = Path(result["plan"])
        initial = json.loads(path.read_bytes())
        changes = [dict(target=str(self.home / "other.exe")), dict(original_sha256=sha(self.old)),
                   dict(helper=str(self.stage / "update-helper.exe")), dict(original_plan_sha256="0" * 64),
                   dict(base=str(self.home)), dict(version="9.0.0"), dict(schema=True), dict(state=[]),
                   dict(parents=[dict(pid=True, created=2, image=str(self.source))]),
                   dict(parents=[dict(pid=202, created=2, image=str(self.target))])]
        for change in changes:
            self.write(path, dict(initial, **change))
            with self.subTest(change=change), self.assertRaises(updates.UpdateError):
                finish.apply_finalization(path, base=self.base, wait_parent=Mock(side_effect=AssertionError("Invalid plan must not wait")))
            self.assertEqual(self.source.read_bytes(), self.new)
            self.assertFalse(self.target.exists())
        self.write(path, initial)
        original = json.loads(self.path.read_bytes())
        original["unreviewed_change"] = True
        self.write(self.path, original)
        with self.assertRaises(updates.UpdateError):
            finish.apply_finalization(path, base=self.base, wait_parent=lambda plan: None)
        self.check_profile()

    def test_failed_ready_handshake_cancels_helper_before_any_rename(self):
        with patch.object(updates, "_await_ready", side_effect=updates.UpdateError("helper_timeout")):
            with self.assertRaises(updates.UpdateError):
                self.prepare()
        child, = self.stage.glob("rename-*/plan.json")
        self.assertEqual(json.loads(child.read_bytes())["state"], "cancelled")
        with self.assertRaises(updates.UpdateError):
            finish.apply_finalization(child, base=self.base, wait_parent=lambda plan: None)
        self.assertEqual(self.source.read_bytes(), self.new)
        self.assertFalse(self.target.exists())

    def test_helper_verifies_new_payload_identity_before_ready(self):
        result = self.prepare()
        path = Path(result["plan"])
        child = json.loads(path.read_bytes())
        with patch.object(updates, "can_replace_executable", return_value=True), \
             patch.object(updates.app_runtime, "default_base", return_value=self.base), \
             patch.object(updates.sys, "executable", child["helper"]), \
             patch.object(finish, "apply_finalization") as apply:
            self.assertEqual(finish.helper_main(path), 0)
        ready = json.loads((path.parent / "ready.json").read_bytes())
        self.assertEqual(ready["helper_sha256"], sha(self.new))
        apply.assert_called_once_with(path)
        with patch.object(updates, "can_replace_executable", return_value=True), \
             patch.object(updates.app_runtime, "default_base", return_value=self.base), \
             patch.object(updates.sys, "executable", str(self.stage / "update-helper.exe")):
            with self.assertRaises(updates.UpdateError):
                finish.helper_main(path)


if __name__ == "__main__":
    unittest.main()
