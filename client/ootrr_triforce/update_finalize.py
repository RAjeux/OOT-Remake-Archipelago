"""Finish filename replacement using the incoming launcher's own helper.

Released schema-1 helpers first replace their original filename. This second
handoff keeps that format compatible while the new bootloader exits before its
executable is renamed. Rollback copies stay in the private update transaction.
"""
from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sys
import time
import uuid

from . import app_runtime
from .save_bridge import atomic


def _updates():
    # update_service.complete_update imports this module after its own checks.
    from . import update_service
    return update_service


def _save(path, value):
    atomic(path, json.dumps(value, indent=2).encode())


@contextmanager
def _lock(path):
    deadline = time.monotonic() + 20
    while True:
        manager = _updates().exclusive(path)
        try:
            manager.__enter__()
            break
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.1)
    try:
        yield
    finally:
        manager.__exit__(*sys.exc_info())


def _unlink(path, expected):
    u = _updates()
    deadline = time.monotonic() + 20
    while True:
        if u._local_path(str(path)) != path or not path.is_file() or u._sha(path) != expected:
            u._fail("target_changed")
        try:
            path.unlink()
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.2)


def _canonical(plan):
    u = _updates()
    u.version_key(plan["version"])
    return Path(plan["target"]).with_name("OOT-Remake-Archipelago-" + plan["version"] + ".exe")


def _rename(source, destination):
    """Publish without overwriting a file created by another transaction."""
    if source.parent != destination.parent:
        _updates()._fail("finalization_path")
    if os.name == "nt":
        deadline = time.monotonic() + 20
        while True:
            try:
                os.rename(source, destination)  # Windows refuses an existing destination.
                return
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.2)
    else:
        # The supported updater runs on Windows. This no-clobber equivalent
        # also lets portable unit tests exercise its filesystem transactions.
        os.link(source, destination)
        try:
            source.unlink()
        except BaseException:
            destination.unlink()
            raise


def _copy(source, destination, expected):
    u = _updates()
    if u._local_path(str(source)) != source or not source.is_file() or u._sha(source) != expected:
        u._fail("checksum")
    temporary = destination.with_name("." + destination.name + ".copy-" + uuid.uuid4().hex + ".tmp")
    try:
        with source.open("rb") as incoming, temporary.open("xb") as output:
            shutil.copyfileobj(incoming, output, 1 << 20)
            output.flush()
            os.fsync(output.fileno())
        if u._sha(temporary) != expected:
            u._fail("checksum")
        _rename(temporary, destination)
    finally:
        if temporary.is_file() and not temporary.is_symlink():
            temporary.unlink()


def _archive(path, plan):
    u = _updates()
    private = path.parent / "previous-launcher.exe"
    backup = u._local_path(plan["backup"])
    if private.exists():
        if u._local_path(str(private)) != private or not private.is_file() or u._sha(private) != plan["original_sha256"]:
            u._fail("backup_changed")
    else:
        if not backup.is_file() or u._sha(backup) != plan["original_sha256"]:
            u._fail("backup_changed")
        _copy(backup, private, plan["original_sha256"])
    if backup.exists():
        if u._local_path(str(backup)) != backup or not backup.is_file() or u._sha(backup) != plan["original_sha256"]:
            u._fail("backup_changed")
        _unlink(backup, plan["original_sha256"])
    changed = plan.get("private_backup") != str(private)
    if changed:
        plan["private_backup"] = str(private)
    if isinstance(plan.get("completion"), dict) and plan["completion"].get("backup") != str(private):
        plan["completion"]["backup"] = str(private)
        changed = True
    if changed:
        _save(path, plan)


def _cleanup_legacy_lock(plan, *, wait=False):
    """Retire only a verified transaction's empty Windows updater lock."""
    if os.name != "nt":
        return
    u = _updates()
    target = Path(plan["target"])
    lock = target.with_name("." + target.name + ".archipelago-update.lock")
    deadline = time.monotonic() + (20 if wait else 0)
    while True:
        try:
            with u._replacement_lock(lock, existing_only=True):
                pass
            return
        except FileNotFoundError:
            return
        except BlockingIOError:
            if time.monotonic() < deadline:
                time.sleep(.1)
                continue
            logging.warning("Preserved an active launcher update lock")
            return
        except (OSError, ValueError) as error:
            logging.warning("Preserved an unverified launcher update lock: %s", type(error).__name__)
            return


def _archive_history(path, current, base):
    """Move only verified, completed transactions' own adjacent backups."""
    u = _updates()
    parent = Path(current["target"]).parent
    scanned = attempted = 0
    try:
        folders = path.parent.parent.iterdir()
        for folder in folders:
            if not re.fullmatch(r"[0-9a-f]{32}", folder.name):
                continue
            if scanned >= 256 or attempted >= 16:
                break
            scanned += 1
            if folder == path.parent:
                continue
            try:
                if u._local_path(str(folder)) != folder or not folder.is_dir():
                    continue
                previous_path = u._local_path(str(folder / "plan.json"))
                if not previous_path.is_file() or previous_path.stat().st_size > 32 << 10:
                    continue
                candidate = json.loads(previous_path.read_bytes())
                if (not isinstance(candidate, dict) or candidate.get("state") != "completed"
                        or u._local_path(candidate.get("target")).parent != parent
                        or u.compare_versions(candidate.get("version"), current["version"]) > 0):
                    continue
                backup = u._local_path(candidate.get("backup"))
                helper = u._local_path(candidate.get("helper"))
                if (helper != folder / "update-helper.exe" or not helper.is_file()
                        or not 0 < helper.stat().st_size <= u.MAX_EXECUTABLE
                        or ("completion" in candidate and not isinstance(candidate["completion"], dict))):
                    continue
                attempted += 1
                # Completed history is best effort: never wait on another
                # transaction, and revalidate everything after taking its lock.
                with u.exclusive(folder / "completion.lock"):
                    previous_path, previous = u._plan(previous_path, base)
                    if (previous.get("state") != "completed" or Path(previous["target"]).parent != parent
                            or u.compare_versions(previous["version"], current["version"]) > 0):
                        continue
                    _cleanup_legacy_lock(previous)
                    backup = Path(previous["backup"])
                    if backup.is_file() and 0 < backup.stat().st_size <= u.MAX_EXECUTABLE:
                        _archive(previous_path, previous)
            except Exception as error:
                logging.warning("Preserved an unverified previous launcher backup (%s): %s", folder.name, type(error).__name__)
    except OSError as error:
        logging.warning("Previous launcher backup history could not be inspected: %s", type(error).__name__)


def prepare_completion(path, plan, base=None):
    """Archive the old binary and arrange a canonical-name restart if needed."""
    u = _updates()
    path, disk = u._plan(path, base)
    if disk != plan or disk.get("state") not in {"applied", "completed"}:
        u._fail("completion_identity")
    source = u._local_path(plan.get("installed_target", plan["target"]))
    expected = plan["hashes"]["executable"]
    if (Path(sys.executable).resolve() != source or not source.is_file()
            or u._sha(source) != expected or u.current_version() != plan["version"]):
        u._fail("completion_identity")
    with _lock(path.parent / "completion.lock"):
        again_path, again = u._plan(path, base)
        if again_path != path or again != plan:
            u._fail("plan_changed")
        _archive(path, plan)
        _cleanup_legacy_lock(plan, wait=True)
        _archive_history(path, plan, base)
        target = _canonical(plan)
        if source == target:
            return None
        if target.exists() and (u._local_path(str(target)) != target or not target.is_file() or u._sha(target) != expected):
            u._fail("target_changed")
        child = path.parent / ("rename-" + uuid.uuid4().hex)
        child.mkdir()
        helper = child / "update-helper.exe"
        _copy(source, helper, expected)
        final = dict(schema=u.SCHEMA, base=plan["base"], version=plan["version"],
                     target=str(source), original_sha256=expected, parents=u._parent_processes(source),
                     helper=str(helper), original_plan_sha256=u._sha(path), state="pending")
        final_path = child / "plan.json"
        _save(final_path, final)
        try:
            process = app_runtime.spawn_process(
                [str(helper), "--finalize-update", str(final_path)], cwd=child,
                env=dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1"),
                stdin=u.subprocess_devnull(), stdout=u.subprocess_devnull(), stderr=u.subprocess_devnull())
            u._await_ready(process, final_path)
        except BaseException:
            final["state"] = "cancelled"
            _save(final_path, final)
            raise
        return dict(restart_scheduled=True, version=plan["version"], target=str(target),
                    backup=plan["private_backup"], plan=str(final_path))


def _plan(path, base=None):
    u = _updates()
    path = u._local_path(str(path))
    if (path.name != "plan.json" or not re.fullmatch(r"rename-[0-9a-f]{32}", path.parent.name)
            or not path.is_file() or path.stat().st_size > 32 << 10):
        u._fail("finalization_plan")
    try:
        value = json.loads(path.read_bytes())
    except (ValueError, UnicodeError):
        u._fail("finalization_plan")
    fields = {"schema", "base", "version", "target", "original_sha256", "parents", "helper", "original_plan_sha256", "state"}
    if (not isinstance(value, dict) or set(value) != fields or type(value["schema"]) is not int
            or value["schema"] != u.SCHEMA or not isinstance(value["state"], str)
            or value["state"] not in {"pending", "cancelled", "applied", "failed"}):
        u._fail("finalization_plan")
    original_path, original = u._plan(path.parent.parent / "plan.json", base)
    if (original_path.parent != path.parent.parent or value["base"] != original["base"]
            or value["version"] != original["version"] or original.get("state") not in {"applied", "completed"}
            or not isinstance(value["original_plan_sha256"], str)
            or not u.SHA_PATTERN.fullmatch(value["original_plan_sha256"])
            or u._sha(original_path) != value["original_plan_sha256"]
            or value["original_sha256"] != original["hashes"]["executable"]
            or original.get("private_backup") != str(original_path.parent / "previous-launcher.exe")):
        u._fail("finalization_plan")
    source = u._local_path(value["target"])
    helper = u._local_path(value["helper"])
    if (source != Path(original["target"]) or source == _canonical(original)
            or helper != path.parent / "update-helper.exe" or not helper.is_file()
            or u._sha(helper) != value["original_sha256"] or not source.is_file()
            or u._sha(source) != value["original_sha256"]):
        u._fail("finalization_identity")
    u._executable(helper, value["version"])
    parents = value["parents"]
    if not isinstance(parents, list) or not 1 <= len(parents) <= 2:
        u._fail("finalization_plan")
    for parent in parents:
        if (not isinstance(parent, dict) or set(parent) != {"pid", "created", "image"}
                or type(parent["pid"]) is not int or parent["pid"] <= 0
                or type(parent["created"]) is not int or parent["created"] <= 0
                or u._local_path(parent["image"]) != source):
            u._fail("finalization_plan")
    return path, value, original_path, original


def apply_finalization(path, base=None, wait_parent=None, launcher=None):
    """Wait for both new bootloaders, rename in place and resume completion."""
    u = _updates()
    path, final, original_path, original = _plan(path, base)
    if final["state"] != "pending":
        u._fail("already_applied")
    (wait_parent or u._wait_for_parents)(final)
    with _lock(original_path.parent / "completion.lock"):
        path, final, original_path, original = _plan(path, base)
        if final["state"] != "pending":
            u._fail("cancelled")
        source, target = Path(final["target"]), _canonical(original)
        expected = final["original_sha256"]
        original_raw = original_path.read_bytes()
        changed = False
        preexisting = target.exists()
        if preexisting and (u._local_path(str(target)) != target or not target.is_file() or u._sha(target) != expected):
            u._fail("target_changed")
        try:
            if preexisting:
                _unlink(source, expected)
            else:
                _rename(source, target)
            changed = True
            original["installed_target"] = str(target)
            _save(original_path, original)
            final["state"] = "applied"
            _save(path, final)
            (launcher or u._launch)([str(target), "--complete-update", str(original_path)])
        except BaseException:
            if changed and not source.exists() and target.is_file() and u._sha(target) == expected:
                if preexisting:
                    _copy(target, source, expected)
                else:
                    _rename(target, source)
            atomic(original_path, original_raw)
            final["state"] = "failed"
            _save(path, final)
            raise
    return dict(applied=True, target=str(target), backup=original["private_backup"], version=final["version"])


def helper_main(path):
    u = _updates()
    if not u.can_replace_executable():
        u._fail("standalone_required")
    path, final, _, _ = _plan(path)
    if Path(sys.executable).resolve() != Path(final["helper"]):
        u._fail("helper_identity")
    if final["state"] != "pending":
        u._fail("cancelled")
    u._ready(path, final)
    apply_finalization(path)
    return 0
