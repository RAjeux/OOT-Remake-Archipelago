"""Isolate CPU-heavy full-network preparation from Tk and its Python GIL.

Only private-cache build/prepare stages run here. Installing mods, changing
profiles, connecting to AP and launching games remain in the parent service.
The bounded channel forwards progress and logs without carrying game assets.
"""
from contextlib import redirect_stderr, redirect_stdout
from contextlib import contextmanager
import ctypes
from ctypes.util import find_library
import json
import multiprocessing
import os
from pathlib import Path
import queue
import shutil
import sys
import traceback
import uuid

from .i18n import tr


QUEUE_SIZE = 64
LOG_CHUNK = 4096
LOG_LIMIT = 1 << 20
MAX_ARGUMENTS = 32 << 20


class WorkerError(RuntimeError):
    def __init__(self, detail=""):
        self.public_message = tr("The randomized game could not be prepared. Your installed room is preserved.")
        self.detail = detail
        super().__init__(self.public_message)


class WorkerCancelled(InterruptedError):
    cancelled = True

    def __init__(self):
        self.public_message = tr("Setup cancelled.")
        super().__init__(self.public_message)


def _linked(path):
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


@contextmanager
def _parent_workspace(root):
    """Own one stage directory, including cleanup after a killed child.

    No directory discovered from a glob or returned by the child is deleted.
    A concurrent worker's directory and every installed cache remain untouched.
    """
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    container = root / ".full-workers"
    created_container = not container.exists()
    if _linked(container):
        raise WorkerError("The generation workspace container is linked.")
    container.mkdir(exist_ok=True)
    if container.resolve() != container or not container.is_dir():
        raise WorkerError("Invalid generation workspace container.")
    workspace = container / uuid.uuid4().hex
    workspace.mkdir(exist_ok=False)
    expected = workspace.resolve()
    try:
        if _linked(workspace) or expected != workspace or expected.parent != container:
            raise WorkerError("Invalid owned generation workspace.")
        yield workspace
    finally:
        if workspace.exists() or _linked(workspace):
            if (_linked(workspace) or workspace.resolve() != expected
                    or expected.parent != container or container.parent != root
                    or _linked(container) or container.resolve() != container):
                raise WorkerError("The owned generation workspace changed before cleanup.")
            shutil.rmtree(workspace)
        if created_container:
            try:
                container.rmdir()  # Empty only; another worker is never removed.
            except OSError:
                pass


def _json_value(value, depth=0):
    if depth > 40:
        raise ValueError("Generation arguments are nested too deeply.")
    if isinstance(value, os.PathLike):
        return os.fspath(value)
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if isinstance(key, os.PathLike):
                key = os.fspath(key)
            elif type(key) is int:
                key = str(key)
            if not isinstance(key, str) or key in result:
                raise ValueError("Generation arguments contain an invalid or duplicate key.")
            result[key] = _json_value(item, depth + 1)
        return result
    if isinstance(value, (tuple, list)):
        return [_json_value(item, depth + 1) for item in value]
    if value is None or type(value) in (str, bool, int, float):
        return value
    raise ValueError("Generation arguments must contain only JSON values and paths.")


class _Output:
    encoding = "utf-8"

    def __init__(self, messages, kind):
        self.messages, self.kind = messages, kind
        self.pending, self.total, self.omitted = "", 0, False

    def write(self, value):
        text = str(value)
        count = len(text)
        if self.total >= LOG_LIMIT:
            self.omitted = True
            return count
        text = text[: min(LOG_LIMIT - self.total, 2 * LOG_CHUNK)]
        self.total += len(text)
        self.pending += text
        while "\n" in self.pending or len(self.pending) >= LOG_CHUNK:
            end = self.pending.find("\n") + 1
            if not end or end > LOG_CHUNK:
                end = LOG_CHUNK
            part, self.pending = self.pending[:end], self.pending[end:]
            try:
                self.messages.put_nowait((self.kind, part))
            except queue.Full:
                self.omitted = True
        return count

    def flush(self):
        if self.pending:
            try:
                self.messages.put_nowait((self.kind, self.pending))
            except queue.Full:
                self.omitted = True
            self.pending = ""

    def isatty(self):
        return False


def _terminal(messages, kind, value):
    try:
        messages.put((kind, value), timeout=5)
    except queue.Full:
        # A dead parent cannot turn a finished private cache into a successful
        # installation. Normal parent cleanup terminates this one process.
        return


def _bind_resources(root):
    from . import app_runtime
    directory = Path(root).resolve()
    if not directory.is_dir():
        raise ValueError("The application resource folder is unavailable.")
    app_runtime._resource_override = directory


def _worker_entry(messages, stage, args, resource_root):
    out, err = _Output(messages, "stdout"), _Output(messages, "stderr")
    try:
        with redirect_stdout(out), redirect_stderr(err):
            _bind_resources(resource_root)
            from . import full_mod
            if stage == "build":
                result = full_mod._build_cached(*args)
            elif stage == "prepare":
                result = full_mod._prepare_cached(*args)
            else:
                raise ValueError("Unknown full-network generation stage.")
            result = _json_value(result)
        out.flush()
        err.flush()
        _terminal(messages, "done", result)
    except BaseException as error:
        out.flush()
        err.flush()
        _terminal(messages, "error", {"type": type(error).__name__, "traceback": traceback.format_exc()[-65536:]})


def _replay(kind, text, progress, phase):
    if not isinstance(text, str):
        raise WorkerError("Invalid generation worker output.")
    stream = sys.stderr if kind == "stderr" else sys.stdout
    if stream is not None:
        stream.write(text)
        stream.flush()
    if progress is not None and kind == "stdout" and text.strip():
        progress(phase, text.strip()[:512])


def _run_process(entry, args, *, progress=None, cancel=None, phase=18):
    """Private transport, also exercised with real isolated worker fixtures."""
    if cancel is not None and cancel.is_set():
        raise WorkerCancelled()
    context = multiprocessing.get_context("spawn")
    messages = context.Queue(maxsize=QUEUE_SIZE)
    process = context.Process(target=entry, args=(messages, *args), daemon=True,
                              name="OOT Remake generation")
    started = False
    try:
        process.start()
        started = True
        while True:
            if cancel is not None and cancel.is_set():
                raise WorkerCancelled()
            try:
                kind, value = messages.get(timeout=.05)
            except queue.Empty:
                if process.is_alive():
                    continue
                process.join()
                try:
                    kind, value = messages.get(timeout=.2)
                except queue.Empty:
                    raise WorkerError("Worker exit code " + str(process.exitcode) + ".") from None
            if kind in {"stdout", "stderr"}:
                _replay(kind, value, progress, phase)
            elif kind == "done":
                process.join(timeout=5)
                if process.is_alive() or process.exitcode != 0:
                    raise WorkerError("The generation worker did not exit cleanly.")
                return value
            elif kind == "error":
                detail = value.get("traceback", "") if isinstance(value, dict) else ""
                if detail and sys.stderr is not None:
                    sys.stderr.write(detail)
                    sys.stderr.flush()
                raise WorkerError(detail)
            else:
                raise WorkerError("Invalid generation worker response.")
    finally:
        if started:
            if process.is_alive():
                process.terminate()
            process.join(timeout=3)
            if process.is_alive():
                process.kill()
                process.join(timeout=3)
            process.close()
        messages.close()
        messages.join_thread()


def run_stage(stage, args, resource_root, *, progress=None, cancel=None):
    """Run one native/full-network stage, keeping its return type unchanged."""
    if stage not in {"build", "prepare"} or not isinstance(args, (tuple, list)):
        raise ValueError("Unknown full-network generation stage.")
    expected = 3 if stage == "build" else 4
    if len(args) != expected:
        raise ValueError("Invalid full-network generation arguments.")
    values = _json_value(args)
    raw = json.dumps(values, allow_nan=False, ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_ARGUMENTS:
        raise ValueError("The full-network generation request is too large.")
    if cancel is not None and cancel.is_set():
        raise WorkerCancelled()
    with _parent_workspace(values[0]) as workspace:
        if not isinstance(values[1], dict):
            raise ValueError("Invalid full-network generation settings.")
        values[1]["_work_root"] = str(workspace)
        result = _run_process(_worker_entry, (stage, values, str(Path(resource_root).resolve())),
                              progress=progress, cancel=cancel, phase=18 if stage == "build" else 45)
    if stage == "prepare":
        if not isinstance(result, str):
            raise WorkerError("The prepare worker returned no resource folder.")
        return Path(result)
    if result is not None:
        raise WorkerError("The build worker returned an unexpected result.")
    return None


def _probe_entry(messages, resource_root, milliseconds):
    """Frozen-runtime selftest: real Codec loading plus a child-held GIL."""
    try:
        _bind_resources(resource_root)
        import zstandard
        from oot_rando.formats.byml_codec import build_sarc
        from .mod_codec import Codec
        from .app_runtime import resource_root as current_root
        codec = Codec(zstandard.ZstdCompressor().compress(build_sarc({"probe": b"synthetic"})))
        raw = b"Isolated generation codec."
        frame = zstandard.ZstdCompressor().compress(raw)
        if codec.decode(codec.encode(raw, frame)) != raw:
            raise ValueError("Background codec round trip failed.")
        if os.name == "nt":
            library = ctypes.PyDLL("kernel32")
            library.Sleep.argtypes, library.Sleep.restype = [ctypes.c_ulong], None
            library.Sleep(milliseconds)
        else:
            library = ctypes.PyDLL(find_library("c"))
            library.usleep.argtypes, library.usleep.restype = [ctypes.c_uint], ctypes.c_int
            library.usleep(milliseconds * 1000)
        _terminal(messages, "done", {"pid": os.getpid(), "codec": True,
                                     "resource_root": str(current_root().resolve())})
    except BaseException:
        _terminal(messages, "error", {"traceback": traceback.format_exc()[-65536:]})


def probe(resource_root, milliseconds=350):
    if type(milliseconds) is not int or not 1 <= milliseconds <= 5000:
        raise ValueError("Invalid background probe duration.")
    return _run_process(_probe_entry, (str(Path(resource_root).resolve()), milliseconds))
