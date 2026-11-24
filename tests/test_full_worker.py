"""Real spawned processes keep native GIL calls, crashes and cancellation away from Tk."""
from contextlib import redirect_stderr, redirect_stdout
import ctypes
from ctypes.util import find_library
import io
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce import full_worker


def return_worker(messages, value):
    messages.put(("stdout", "Building private test resources\n"))
    messages.put(("done", {"pid": os.getpid(), "value": value}))


def crash_worker(_messages):
    os._exit(23)


def error_worker(messages):
    messages.put(("error", {"traceback": "Developer-only worker diagnostic"}))


def waiting_worker(messages, marker):
    Path(marker).write_text("private stage started", encoding="utf-8")
    while True:
        time.sleep(.1)


def blocking_worker(messages, milliseconds):
    if os.name == "nt":
        library = ctypes.PyDLL("kernel32")
        library.Sleep.argtypes, library.Sleep.restype = [ctypes.c_ulong], None
        library.Sleep(milliseconds)
    else:
        library = ctypes.PyDLL(find_library("c"))
        library.usleep.argtypes, library.usleep.restype = [ctypes.c_uint], ctypes.c_int
        library.usleep(milliseconds * 1000)
    messages.put(("done", os.getpid()))


def workspace_worker(messages, stage, args, resource_root):
    workspace = Path(args[1]["_work_root"])
    (workspace / "stage").mkdir()
    (workspace / "stage/created").write_bytes(b"private partial output")
    if args[-1].get("wait"):
        while True:
            time.sleep(.1)
    messages.put(("done", None))


class GenerationWorkerTests(unittest.TestCase):
    def test_real_process_returns_results_and_parent_progress_without_game_access(self):
        messages, progress = io.StringIO(), []
        with redirect_stdout(messages):
            result = full_worker._run_process(return_worker, ({"path": "synthetic"},),
                progress=lambda percent, text: progress.append((percent, text)), phase=45)
        self.assertNotEqual(result["pid"], os.getpid())
        self.assertEqual(result["value"], {"path": "synthetic"})
        self.assertEqual(progress, [(45, "Building private test resources")])
        self.assertIn("Building private test resources", messages.getvalue())

    def test_worker_crash_and_exception_cannot_report_success(self):
        for target in (crash_worker, error_worker):
            log = io.StringIO()
            with self.subTest(target=target.__name__), redirect_stderr(log):
                with self.assertRaises(full_worker.WorkerError) as raised:
                    full_worker._run_process(target, ())
            self.assertNotIn("Developer-only", raised.exception.public_message)
            if target == error_worker:
                self.assertIn("Developer-only worker diagnostic", log.getvalue())

    def test_cancel_terminates_only_the_worker_and_preserves_installed_room(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker, sentinel = root / "private-stage", root / "installed-room"
            sentinel.write_bytes(b"installed resources stay untouched")
            cancel = threading.Event()
            def cancel_started_worker():
                deadline = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                cancel.set()
            monitor = threading.Thread(target=cancel_started_worker, daemon=True)
            monitor.start()
            with self.assertRaises(full_worker.WorkerCancelled):
                full_worker._run_process(waiting_worker, (str(marker),), cancel=cancel)
            monitor.join(timeout=1)
            self.assertTrue(marker.is_file())
            self.assertEqual(sentinel.read_bytes(), b"installed resources stay untouched")

    def test_parent_tk_heartbeat_runs_during_child_gil_holding_native_call(self):
        import tkinter as tk
        try:
            window = tk.Tk()
            window.withdraw()
        except tk.TclError as error:
            self.skipTest(str(error))
        ticks, result, errors = [], [], []
        def tick():
            ticks.append(time.monotonic())
            window.after(10, tick)
        def run():
            try:
                result.append(full_worker._run_process(blocking_worker, (700,)))
            except Exception as error:
                errors.append(type(error).__name__)
        tick()
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        deadline = time.monotonic() + 10
        while worker.is_alive() and time.monotonic() < deadline:
            window.update()
            time.sleep(.005)
        worker.join(timeout=.1)
        window.destroy()
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertNotEqual(result[0], os.getpid())
        self.assertGreater(len(ticks), 20)
        self.assertLess(max(b - a for a, b in zip(ticks, ticks[1:])), .3)

    def test_stages_accept_only_bounded_json_safe_arguments_and_restore_path_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(full_worker, "_run_process", return_value=str(root / "mods")) as process:
                result = full_worker.run_stage("prepare", (root, {"romfs": root / "romfs"}, {}, {"token": "test"}), root)
                self.assertEqual(result, root / "mods")
                self.assertEqual(process.call_args.args[1][1][0], str(root))
            for stage, args in (("launch", ()), ("build", (root, {}, {}, {})), ("build", (root, {"callback": lambda: None}, {}))):
                with self.subTest(stage=stage), self.assertRaises(ValueError):
                    full_worker.run_stage(stage, args, root)

    def test_output_buffer_is_bounded_when_parent_cannot_drain(self):
        messages = queue.Queue(maxsize=2)
        output = full_worker._Output(messages, "stdout")
        for _ in range(1000):
            output.write("x" * 9000)
        output.flush()
        self.assertLessEqual(messages.qsize(), 2)
        self.assertLessEqual(len(output.pending), full_worker.LOG_CHUNK)
        self.assertLessEqual(output.total, full_worker.LOG_LIMIT)
        self.assertTrue(output.omitted)

    def test_cancel_before_start_never_spawns_a_process(self):
        cancel = threading.Event()
        cancel.set()
        with patch.object(full_worker.multiprocessing, "get_context", side_effect=AssertionError("started")):
            with self.assertRaises(full_worker.WorkerCancelled):
                full_worker._run_process(return_worker, (None,), cancel=cancel)

    def test_success_and_cancellation_remove_only_the_parent_owned_stage_directory(self):
        for cancelled in (False, True):
            with self.subTest(cancelled=cancelled), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                other = root / ".full-workers/another-active-worker"
                other.mkdir(parents=True)
                (other / "keep").write_bytes(b"another worker")
                installed = root / "mods/Archipelago/cache-success"
                installed.parent.mkdir(parents=True)
                installed.write_bytes(b"completed cache stays")
                cancel = threading.Event()
                def cancel_started():
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        if any(root.glob(".full-workers/*/stage/created")):
                            cancel.set()
                            return
                        time.sleep(.01)
                    cancel.set()
                monitor = threading.Thread(target=cancel_started, daemon=True) if cancelled else None
                if monitor:
                    monitor.start()
                with patch.object(full_worker, "_worker_entry", workspace_worker):
                    if cancelled:
                        with self.assertRaises(full_worker.WorkerCancelled):
                            full_worker.run_stage("build", (root, {}, {"wait": True}), root, cancel=cancel)
                    else:
                        full_worker.run_stage("build", (root, {}, {}), root)
                if monitor:
                    monitor.join(timeout=1)
                self.assertEqual(list((root / ".full-workers").iterdir()), [other])
                self.assertEqual((other / "keep").read_bytes(), b"another worker")
                self.assertEqual(installed.read_bytes(), b"completed cache stays")


if __name__ == "__main__":
    unittest.main()
