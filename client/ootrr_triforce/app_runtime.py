"""Resources and external tools shared by the portable Windows application.

Runtime files belong to the executable's extraction directory. User data and
downloaded tools belong to LocalAppData, so moving or closing the executable
never removes a prepared room, its saves or the generator's Node runtime.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import urllib.request
import uuid
from zipfile import ZipFile

from .i18n import tr

NODE_VERSION = "24.22.3"
NODE_SHA256 = "86fc4785327db5f5c7558dc6156c543b433c313e813a222e088086222ab4afa6"
BUILDER_FOLDER = "OOTRR-0.8.1-windows-x64-portable"
BUILDER_URL = "https://github.com/ootrando/ootrr/releases/download/v0.8.1/" + BUILDER_FOLDER + ".zip"
BUILDER_ZIP_SHA256 = "f1c1b31bb59cf3b023424f59e72ba50f9a9e64f399db1871407762454d02f4e6"
BUILDER_SHA256 = "5f09d177194cfd57e048ec67bf417f6563db499c16866cd52ae9527dad7d8077"
_resource_override = None
_dll_lock = threading.RLock()
_log_stream = None


def default_base():
    return Path(os.getenv("LOCALAPPDATA") or (Path.home() / ".local/share")) / "OOTRR-Archipelago"


def resource_root():
    if _resource_override is not None:
        return Path(_resource_override)
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(sys.argv[0]).resolve().parent


def log_path(base=None):
    return Path(base or default_base()) / "diagnostics/application.log"


def bundled_node(base=None):
    embedded = resource_root() / "runtime/node/node.exe"
    persistent = Path(base or default_base()) / "tools" / ("node-v" + NODE_VERSION) / "node.exe"
    if os.name == "nt" and embedded.is_file():
        return str(embedded)
    if os.environ.get("OOTRR_NODE"):
        return os.environ["OOTRR_NODE"]
    if os.name == "nt" and persistent.is_file():
        return str(persistent)
    return shutil.which("node")


def initialize():
    """Prepare the GUI runtime without changing existing room settings."""
    global _resource_override, _log_stream
    if not getattr(sys, "frozen", False):
        source_dist = Path(__file__).resolve().parents[2] / "dist"
        if not (resource_root() / "native/archipelago.dll").is_file() and (source_dist / "native/archipelago.dll").is_file():
            _resource_override = source_dist
    node = bundled_node()
    if node:
        os.environ["OOTRR_NODE"] = node
    if getattr(sys, "frozen", False) and _log_stream is None:
        target = log_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.stat().st_size > 5 << 20:
            target.replace(target.with_name("application.previous.log"))
        _log_stream = target.open("a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = _log_stream


def subprocess_options():
    if os.name == "nt" and getattr(sys, "frozen", False):
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _child_environment(given=None):
    env = dict(os.environ if given is None else given)
    if not getattr(sys, "frozen", False):
        return env
    # External programs must not import our bundled Python or DLLs.
    for name in ("PYTHONHOME", "PYTHONPATH", "TCL_LIBRARY", "TK_LIBRARY"):
        env.pop(name, None)
    home = resource_root().resolve()
    def outside(value):
        try:
            return not Path(value).resolve().is_relative_to(home)
        except (OSError, ValueError):
            return True
    env["PATH"] = os.pathsep.join(value for value in env.get("PATH", "").split(os.pathsep) if value and outside(value))
    for key in ("LD_LIBRARY_PATH", "LIBPATH"):
        if key + "_ORIG" in env:
            env[key] = env[key + "_ORIG"]
        else:
            env.pop(key, None)
    return env


@contextmanager
def _external_dll_search():
    if os.name != "nt" or not getattr(sys, "frozen", False):
        yield
        return
    import ctypes as C
    kernel = C.WinDLL("kernel32", use_last_error=True)
    kernel.SetDllDirectoryW.argtypes = [C.c_wchar_p]
    kernel.GetDllDirectoryW.argtypes = [C.c_uint, C.c_wchar_p]
    with _dll_lock:
        size = kernel.GetDllDirectoryW(0, None)
        previous = C.create_unicode_buffer(size + 1)
        kernel.GetDllDirectoryW(len(previous), previous)
        if not kernel.SetDllDirectoryW(None):
            raise OSError(C.get_last_error(), "Unable to isolate the external program.")
        try:
            yield
        finally:
            kernel.SetDllDirectoryW(previous.value or None)


def spawn_process(*args, **kwargs):
    """Create a child without a console or inherited frozen DLL search path."""
    if not getattr(sys, "frozen", False):
        return subprocess.Popen(*args, **kwargs)
    options = subprocess_options()
    kwargs["creationflags"] = kwargs.get("creationflags", 0) | options.get("creationflags", 0)
    kwargs["env"] = _child_environment(kwargs.get("env"))
    with _external_dll_search():
        return subprocess.Popen(*args, **kwargs)


def run_process(*args, input=None, capture_output=False, timeout=None, check=False, **kwargs):
    if not getattr(sys, "frozen", False):
        if input is not None:
            kwargs["input"] = input
        if capture_output:
            kwargs["capture_output"] = True
        if timeout is not None:
            kwargs["timeout"] = timeout
        if check:
            kwargs["check"] = True
        return subprocess.run(*args, **kwargs)
    if input is not None:
        if kwargs.get("stdin") is not None:
            raise ValueError("stdin and input arguments may not both be used.")
        kwargs["stdin"] = subprocess.PIPE
    if capture_output:
        if kwargs.get("stdout") is not None or kwargs.get("stderr") is not None:
            raise ValueError("stdout and stderr arguments may not be used with capture_output.")
        kwargs["stdout"] = kwargs["stderr"] = subprocess.PIPE
    else:
        for name, stream in (("stdout", sys.stdout), ("stderr", sys.stderr)):
            if kwargs.get(name) is None and stream is not None:
                try:
                    stream.fileno()
                except (AttributeError, OSError, ValueError):
                    continue
                kwargs[name] = stream
    with spawn_process(*args, **kwargs) as process:
        try:
            output, errors = process.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            output, errors = process.communicate()
            raise subprocess.TimeoutExpired(process.args, timeout, output=output, stderr=errors) from None
        except BaseException:
            process.kill()
            process.wait()
            raise
        if check and process.returncode:
            raise subprocess.CalledProcessError(process.returncode, process.args, output, errors)
        return subprocess.CompletedProcess(process.args, process.returncode, output, errors)


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError(tr("Setup cancelled."))


def _extract_builder(archive, destination):
    allowed = {"LICENSE", "NOTICE", "ootrr.exe", "portable.txt", "README.md"}
    with ZipFile(archive) as contents:
        found = set()
        for info in contents.infolist():
            path = PurePosixPath(info.filename)
            if ("\\" in info.filename or path.is_absolute() or ".." in path.parts
                    or len(path.parts) != 2 or path.parts[0] != BUILDER_FOLDER
                    or path.parts[1] not in allowed or path.parts[1].casefold() in found
                    or stat.S_ISLNK(info.external_attr >> 16) or info.file_size > 24 << 20):
                raise ValueError(tr("The randomizer download is invalid. Please try again."))
            found.add(path.parts[1].casefold())
            target = destination / path.parts[1]
            with contents.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
        if found != {name.casefold() for name in allowed}:
            raise ValueError(tr("The randomizer download is invalid. Please try again."))


def ensure_builder(base=None, progress=None, cancel=None):
    """Reuse or download the exact compatible portable builder, transactionally."""
    from .builder import validate_builder
    from .save_bridge import exclusive
    tools = Path(base or default_base()) / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    target = tools / BUILDER_FOLDER
    executable = target / "ootrr.exe"
    with exclusive(tools / "randomizer-download.lock"):
        _check_cancel(cancel)
        if executable.is_file() and _sha(executable) == BUILDER_SHA256:
            validate_builder(executable)
            return executable
        if progress:
            progress(tr("Downloading the compatible randomizer…"))
        with tempfile.TemporaryDirectory(prefix="randomizer-", dir=tools) as temporary:
            stage = Path(temporary)
            archive = stage / "download.zip"
            try:
                request = urllib.request.Request(BUILDER_URL, headers={"User-Agent": "OOT-Remake-Archipelago"})
                with urllib.request.urlopen(request, timeout=30) as response, archive.open("wb") as output:
                    total = 0
                    while chunk := response.read(256 << 10):
                        _check_cancel(cancel)
                        total += len(chunk)
                        if total > 16 << 20:
                            raise ValueError("Download exceeds its maximum size.")
                        output.write(chunk)
                if _sha(archive) != BUILDER_ZIP_SHA256:
                    raise ValueError("Download checksum differs.")
                unpacked = stage / "tool"
                unpacked.mkdir()
                _extract_builder(archive, unpacked)
                if _sha(unpacked / "ootrr.exe") != BUILDER_SHA256:
                    raise ValueError("Builder checksum differs.")
                validate_builder(unpacked / "ootrr.exe")
            except InterruptedError:
                raise
            except Exception as error:
                raise ValueError(tr("The compatible randomizer could not be downloaded. Check your connection and try again.")) from error
            _check_cancel(cancel)
            previous = None
            if target.exists():
                previous = tools / (BUILDER_FOLDER + "-before-" + uuid.uuid4().hex[:8])
                target.rename(previous)
            try:
                unpacked.rename(target)
            except BaseException:
                if previous is not None:
                    previous.rename(target)
                raise
    return executable


def install_apworld(target, base=None):
    """Install the APWorld and its persistent engine runtime for this user."""
    from .save_bridge import atomic, exclusive
    destination = Path(target).expanduser().resolve()
    if destination.name.casefold() != "custom_worlds":
        if not (destination / "ArchipelagoGenerate.exe").is_file() and not (destination / "Generate.py").is_file():
            raise ValueError(tr("Choose your Archipelago installation folder."))
        destination /= "custom_worlds"
    destination.mkdir(parents=True, exist_ok=True)
    archive = resource_root() / "ootrr_remake.apworld"
    with ZipFile(archive) as packaged:
        if "ootrr_remake/__init__.py" not in packaged.namelist():
            raise ValueError(tr("The application is incomplete. Download it again."))
    node = resource_root() / "runtime/node/node.exe"
    if not node.is_file() or _sha(node) != NODE_SHA256:
        raise ValueError(tr("The application is incomplete. Download it again."))
    base = Path(base or default_base())
    runtime = base / "tools" / ("node-v" + NODE_VERSION)
    runtime.mkdir(parents=True, exist_ok=True)
    world = destination / "ootrr_remake.apworld"
    # The global APWorld may be shared by multiple users. Their existing world
    # remains backed up, and each user's generator runtime stays in LocalAppData.
    with exclusive(base / "apworld-install.lock"):
        for name in ("node.exe", "LICENSE"):
            source = node if name == "node.exe" else node.parent / "LICENSE"
            atomic(runtime / name, source.read_bytes())
        previous = None
        if world.is_file() and world.read_bytes() != archive.read_bytes():
            backups = base / "backups/apworld"
            backups.mkdir(parents=True, exist_ok=True)
            previous = backups / ("ootrr_remake-" + uuid.uuid4().hex[:12] + ".apworld")
            shutil.copy2(world, previous)
        atomic(world, archive.read_bytes())
    return world


def export_licenses(base=None):
    """Expose bundled notices from Help without depending on temporary paths."""
    version = (resource_root() / "VERSION").read_text(encoding="utf-8").strip()
    if not version or any(char not in "0123456789abcdefghijklmnopqrstuvwxyz.-" for char in version):
        raise ValueError(tr("The application is incomplete. Download it again."))
    destination = Path(base or default_base()) / "licenses" / version
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("LICENSE", "NOTICE", "SOURCES.txt"):
        source = resource_root() / name
        if source.is_file():
            shutil.copyfile(source, destination / name)
    if (resource_root() / "licenses").is_dir():
        shutil.copytree(resource_root() / "licenses", destination / "third-party", dirs_exist_ok=True)
    return destination
