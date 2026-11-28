"""Windows replacement locks disappear without weakening old-helper exclusion."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce import update_finalize as finish, update_service as updates
import test_update_finalize as fixtures


@unittest.skipUnless(os.name == "nt", "Native Windows replacement-lock handles")
class WindowsReplacementLockTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="updater lock é ")
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name).resolve()
        self.path = self.folder / ".Launcher.exe.archipelago-update.lock"

    def test_new_lock_is_exclusive_and_removed_when_the_handle_closes(self):
        self.assertFalse(self.path.exists())
        with updates._replacement_lock(self.path):
            with self.assertRaises(BlockingIOError):
                with updates._replacement_lock(self.path):
                    self.fail("Two replacement transactions held the same lock")
        self.assertFalse(self.path.exists())
        with updates._replacement_lock(self.path):
            pass
        self.assertFalse(self.path.exists())

    def test_existing_empty_legacy_lock_is_removed_without_creating_another_file(self):
        self.path.write_bytes(b"")
        sentinel = self.folder / "Unrelated user file.txt"
        sentinel.write_bytes(b"keep")
        with updates._replacement_lock(self.path, existing_only=True):
            pass
        self.assertFalse(self.path.exists())
        self.assertEqual(sentinel.read_bytes(), b"keep")
        self.assertEqual(list(self.folder.iterdir()), [sentinel])

    def test_exception_inside_transaction_closes_and_removes_the_lock(self):
        with self.assertRaisesRegex(RuntimeError, "synthetic transaction failure"):
            with updates._replacement_lock(self.path):
                raise RuntimeError("synthetic transaction failure")
        self.assertFalse(self.path.exists())

    def test_missing_existing_only_lock_is_not_created(self):
        with self.assertRaises(FileNotFoundError):
            with updates._replacement_lock(self.path, existing_only=True):
                self.fail("A missing historical lock must not be created")
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_old_persistent_lock_and_new_lock_exclude_each_other(self):
        with updates.exclusive(self.path):
            with self.assertRaises(BlockingIOError):
                with updates._replacement_lock(self.path):
                    self.fail("A legacy replacement helper still owns this lock")
        self.assertTrue(self.path.is_file())
        with updates._replacement_lock(self.path):
            # Released helpers can report delete-pending as access denied;
            # either error must exclude them from the held transaction.
            with self.assertRaises((BlockingIOError, PermissionError)):
                with updates.exclusive(self.path):
                    self.fail("A legacy helper entered the new transaction")
        self.assertFalse(self.path.exists())

    def test_nonempty_file_is_preserved(self):
        original = b"This is not an updater lock."
        self.path.write_bytes(original)
        with self.assertRaises(updates.UpdateError):
            with updates._replacement_lock(self.path):
                self.fail("Unrecognised file must not be marked for deletion")
        self.assertEqual(self.path.read_bytes(), original)

    def test_empty_hardlink_and_its_other_name_are_preserved(self):
        original = self.folder / "user-owned-empty-file"
        original.write_bytes(b"")
        self.path.hardlink_to(original)
        identity = original.stat().st_ino
        with self.assertRaises(updates.UpdateError):
            with updates._replacement_lock(self.path):
                self.fail("A multiply linked file is not an owned updater lock")
        self.assertEqual(self.path.stat().st_ino, identity)
        self.assertEqual(original.stat().st_ino, identity)
        self.assertEqual(original.stat().st_nlink, 2)

    def test_symlink_is_preserved_and_its_target_is_never_deleted(self):
        original = self.folder / "user-owned-empty-file"
        original.write_bytes(b"")
        try:
            self.path.symlink_to(original)
        except OSError as error:
            self.skipTest("This Windows account cannot create symbolic links: " + type(error).__name__)
        with self.assertRaises(updates.UpdateError):
            with updates._replacement_lock(self.path):
                self.fail("An updater lock cannot follow a leaf reparse point")
        self.assertTrue(self.path.is_symlink())
        self.assertTrue(original.is_file())

    def test_directory_is_preserved(self):
        self.path.mkdir()
        with self.assertRaises((updates.UpdateError, OSError)):
            with updates._replacement_lock(self.path):
                self.fail("A directory cannot become an updater lock")
        self.assertTrue(self.path.is_dir())

    def test_terminated_process_releases_and_removes_its_lock(self):
        ready = self.folder / "child-ready"
        script = "\n".join((
            "from pathlib import Path",
            "import sys",
            "sys.path.insert(0, sys.argv[1])",
            "from ootrr_triforce import update_service as updates",
            "with updates._replacement_lock(Path(sys.argv[2])):",
            "    Path(sys.argv[3]).write_bytes(b'locked')",
            "    sys.stdin.readline()",
        ))
        child = subprocess.Popen(
            [sys.executable, "-X", "utf8", "-c", script, str(ROOT / "client"), str(self.path), str(ready)],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"),
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            deadline = time.monotonic() + 15
            while not ready.is_file():
                if child.poll() is not None:
                    self.fail("Lock child exited before readiness: " + child.communicate(timeout=5)[1].decode("utf-8", "replace"))
                if time.monotonic() >= deadline:
                    self.fail("Lock child did not become ready")
                time.sleep(.02)
            self.assertEqual(ready.read_bytes(), b"locked")
            with self.assertRaises(BlockingIOError):
                with updates._replacement_lock(self.path):
                    self.fail("A second process entered a held replacement lock")
            child.kill()  # Simulate an abrupt helper crash: no Python finally runs.
            child.communicate(timeout=10)
            self.assertNotEqual(child.returncode, 0)
            self.assertFalse(self.path.exists())
            with updates._replacement_lock(self.path):
                pass
            self.assertFalse(self.path.exists())
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)


@unittest.skipUnless(os.name == "nt", "Native Windows historical-lock cleanup")
class WindowsHistoricalLockCleanupTests(unittest.TestCase):
    def setUp(self):
        # Reuse the coherent schema-1 file fixture, without importing its tests
        # as additional discoverable cases or mocking any Windows lock calls.
        self.fixture = fixtures.FinalizationTests("test_canonical_source_only_archives_and_is_idempotent")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    @staticmethod
    def lock_for(target):
        return target.with_name("." + target.name + ".archipelago-update.lock")

    def archived_history(self, digit, *, state="completed"):
        f = self.fixture
        path, plan, backup, old = f.historical(digit, state=state)
        target = f.folder / ("OOT-Remake-Archipelago-0.9." + digit + "-alpha.1.exe")
        private = path.parent / "previous-launcher.exe"
        private.write_bytes(old)
        backup.unlink()
        plan.update(target=str(target), parents=[dict(pid=303, created=3, image=str(target))],
                    backup=str(target.with_name(target.name + ".previous-" + digit * 12 + ".exe")),
                    adjacent=str(target.with_name("." + target.name + ".update-" + digit * 32 + ".tmp")),
                    private_backup=str(private))
        plan["completion"]["backup"] = str(private)
        f.write(path, plan)
        return path, plan, self.lock_for(target), private, old

    def test_current_completion_removes_its_legacy_lock_and_preserves_unregistered_files(self):
        f = self.fixture
        legacy = self.lock_for(f.source)
        legacy.write_bytes(b"")
        unrelated = self.lock_for(f.folder / "Manual copy.exe")
        unrelated.write_bytes(b"")
        f.prepare()
        self.assertFalse(legacy.exists())
        self.assertTrue(unrelated.is_file())
        f.check_profile()

    def test_completed_history_lock_is_removed_after_its_backup_was_already_archived(self):
        f = self.fixture
        path, plan, legacy, private, old = self.archived_history("d")
        legacy.write_bytes(b"")
        before = path.read_bytes()
        f.prepare()
        self.assertFalse(legacy.exists())
        self.assertEqual(private.read_bytes(), old)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(Path(plan["backup"]).exists())
        f.check_profile()

    def test_active_history_and_user_modified_lock_are_preserved(self):
        f = self.fixture
        active_path, _, active_lock, _, _ = self.archived_history("d", state="applied")
        active_lock.write_bytes(b"")
        completed_path, _, changed_lock, _, _ = self.archived_history("e")
        changed_lock.write_bytes(b"user content")
        before = {path: path.read_bytes() for path in (active_path, completed_path)}
        f.prepare()
        self.assertTrue(active_lock.is_file())
        self.assertEqual(changed_lock.read_bytes(), b"user content")
        for path, raw in before.items():
            self.assertEqual(path.read_bytes(), raw)
        f.check_profile()

    def test_busy_historical_lock_is_left_for_a_later_completed_update(self):
        f = self.fixture
        _, plan, legacy, _, _ = self.archived_history("d")
        with updates.exclusive(legacy):
            finish._cleanup_legacy_lock(plan)
        self.assertTrue(legacy.is_file())
        finish._cleanup_legacy_lock(plan)
        self.assertFalse(legacy.exists())
        f.check_profile()


if __name__ == "__main__":
    unittest.main()
