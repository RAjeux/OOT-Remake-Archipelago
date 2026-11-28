"""Verified updates of the portable launcher, independent of game profiles.

The current, trusted executable supplies the small replacement helper by being
copied outside PyInstaller's extraction directory. It waits for the old app and
its bootloader, keeps the previous executable and never touches a game/save.
"""
from datetime import datetime, timezone
from contextlib import contextmanager
import ctypes
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from zipfile import BadZipFile, ZipFile

from . import app_runtime
from .i18n import tr
from .save_bridge import atomic, exclusive

REPOSITORY = "RAjeux/OOT-Remake-Archipelago"
API = "https://api.github.com/repos/" + REPOSITORY
MAX_METADATA = 2 << 20
MAX_CHECKSUMS = 32 << 10
MAX_EXECUTABLE = 192 << 20
MAX_APWORLD = 32 << 20
TIMEOUT = 30
SCHEMA = 1
USER_AGENT = "OOT-Remake-Archipelago-update"
PRODUCT_NAME = "OOT Remake Archipelago"
DOWNLOAD_HOSTS = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
VERSION_PATTERN = re.compile(r"(?:v)?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*))?(?:\+[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?\Z")
SHA_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class UpdateError(ValueError):
    def __init__(self, code, detail=""):
        self.code = code
        self.detail = detail
        self.public_message = tr("The update could not be completed. Please try again.")
        super().__init__(self.public_message)


def _fail(code, detail=""):
    raise UpdateError(code, detail)


def version_key(value):
    """SemVer precedence, including numeric alpha.9 < alpha.10 identifiers."""
    if not isinstance(value, str) or len(value) > 100:
        _fail("version")
    match = VERSION_PATTERN.fullmatch(value)
    if not match:
        _fail("version")
    core = tuple(map(int, match.group(1, 2, 3)))
    prerelease = match.group(4)
    if prerelease is None:
        return core, 1, ()
    parts = []
    for part in prerelease.split("."):
        if part.isdigit():
            if len(part) > 1 and part.startswith("0"):
                _fail("version")
            parts.append((0, int(part)))
        else:
            parts.append((1, part))
    return core, 0, tuple(parts)


def compare_versions(left, right):
    a, b = version_key(left), version_key(right)
    return (a > b) - (a < b)


def current_version():
    source = (app_runtime.resource_root() / "VERSION" if getattr(sys, "frozen", False)
              else Path(__file__).resolve().parents[2] / "VERSION")
    value = source.read_text(encoding="utf-8").strip()
    version_key(value)
    return value


def can_replace_executable():
    return os.name == "nt" and bool(getattr(sys, "frozen", False)) and Path(sys.executable).suffix.lower() == ".exe"


def _valid_url(url, *, metadata=False):
    if not isinstance(url, str) or len(url) > 8192:
        _fail("url")
    try:
        value = urllib.parse.urlsplit(url)
    except ValueError:
        _fail("url")
    if (value.scheme != "https" or value.username or value.password or value.fragment
            or value.netloc != value.hostname):
        _fail("url")
    if metadata:
        if value.hostname != "api.github.com" or not value.path.startswith("/repos/" + REPOSITORY + "/"):
            _fail("url")
    elif value.hostname not in DOWNLOAD_HOSTS:
        _fail("url")
    return value


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        if request.get_method() != "GET":
            _fail("redirect")
        _valid_url(url)
        # Never forward cookies, authentication or headers supplied by a proxy.
        return urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")


def _open(url):
    metadata = urllib.parse.urlsplit(url).hostname == "api.github.com"
    _valid_url(url, metadata=metadata)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _Redirect())
    headers = {"User-Agent": USER_AGENT}
    if metadata:
        headers.update(Accept="application/vnd.github+json", **{"X-GitHub-Api-Version": "2022-11-28"})
    return opener.open(urllib.request.Request(url, headers=headers, method="GET"), timeout=TIMEOUT)


def _read(url, maximum):
    try:
        with _open(url) as response:
            raw = response.read(maximum + 1)
        if len(raw) > maximum:
            _fail("size")
        return raw
    except UpdateError:
        raise
    except (OSError, ValueError, urllib.error.URLError) as exc:
        _fail("network", type(exc).__name__)


def _digest(value):
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not value.startswith("sha256:") or not SHA_PATTERN.fullmatch(value[7:]):
        _fail("checksum")
    return value[7:]


def _asset(rows, name, version, maximum):
    matches = [row for row in rows if isinstance(row, dict) and row.get("name") == name]
    if len(matches) != 1:
        _fail("release_assets", "The newest release has incomplete assets.")
    row = matches[0]
    size = row.get("size")
    expected = "https://github.com/" + REPOSITORY + "/releases/download/v" + version + "/" + urllib.parse.quote(name)
    if type(size) is not int or not 0 < size <= maximum or row.get("browser_download_url") != expected:
        _fail("release_assets")
    _valid_url(expected)
    return dict(name=name, url=expected, size=size, sha256=_digest(row.get("digest")))


def _checksums(raw):
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeError:
        _fail("checksum")
    found = {}
    if len(lines) > 128:
        _fail("checksum")
    for line in lines:
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64}) [ *]([^\\/\r\n]+)", line)
        if not match or match.group(2) in found:
            _fail("checksum")
        found[match.group(2)] = match.group(1)
    return found


def check_for_updates(current_version=None, include_prereleases=None):
    """Use the most recently published eligible release, never the highest tag.

    Old experimental tags can have a higher version number. A new incomplete
    release is an error; it must not cause a fallback to such an old release.
    """
    current = current_version or globals()["current_version"]()
    key = version_key(current)
    include = key[1] == 0 if include_prereleases is None else bool(include_prereleases)
    try:
        rows = json.loads(_read(API + "/releases?per_page=100", MAX_METADATA))
    except UpdateError:
        raise
    except (ValueError, UnicodeError):
        _fail("metadata")
    if not isinstance(rows, list):
        _fail("metadata")
    eligible = []
    for row in rows:
        if not isinstance(row, dict) or row.get("draft") is not False or (row.get("prerelease") is True and not include):
            continue
        tag = row.get("tag_name")
        try:
            parsed = version_key(tag)
        except UpdateError:
            continue
        if not include and parsed[1] == 0:
            continue
        try:
            published = datetime.fromisoformat(row["published_at"].replace("Z", "+00:00"))
            if published.tzinfo is None:
                _fail("metadata")
        except (KeyError, TypeError, ValueError, AttributeError):
            _fail("metadata")
        eligible.append((published.astimezone(timezone.utc), row))
    can_install = can_replace_executable()
    reason = "" if can_install else tr("Automatic application replacement requires the standalone Windows executable.")
    base_result = dict(current_version=current, include_prereleases=include, can_install=can_install,
                       cannot_install_reason=reason, update_available=False, latest_version=current,
                       release_url="https://github.com/" + REPOSITORY + "/releases", assets={})
    if not eligible:
        return base_result
    _, release = max(eligible, key=lambda pair: pair[0])
    version = release["tag_name"].removeprefix("v")
    expected_page = "https://github.com/" + REPOSITORY + "/releases/tag/v" + version
    if release.get("html_url") != expected_page or not isinstance(release.get("assets"), list):
        _fail("metadata")
    assets = {
        "executable": _asset(release["assets"], "OOT-Remake-Archipelago-" + version + ".exe", version, MAX_EXECUTABLE),
        "apworld": _asset(release["assets"], "ootrr_remake.apworld", version, MAX_APWORLD),
        "checksums": _asset(release["assets"], "SHA256SUMS.txt", version, MAX_CHECKSUMS),
    }
    raw = _read(assets["checksums"]["url"], MAX_CHECKSUMS)
    if len(raw) != assets["checksums"]["size"]:
        _fail("size")
    actual = hashlib.sha256(raw).hexdigest()
    if assets["checksums"]["sha256"] and assets["checksums"]["sha256"] != actual:
        _fail("checksum")
    assets["checksums"]["sha256"] = actual
    sums = _checksums(raw)
    for name in ("executable", "apworld"):
        asset = assets[name]
        digest = sums.get(asset["name"])
        if not digest or (asset["sha256"] and asset["sha256"] != digest):
            _fail("checksum")
        asset["sha256"] = digest
    base_result.update(latest_version=version, update_available=compare_versions(version, current) > 0,
                       release_url=expected_page, published_at=release["published_at"],
                       notes=release.get("body", "") if isinstance(release.get("body", ""), str) else "",
                       assets=assets)
    return base_result


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError(tr("Setup cancelled."))


def _file_version(path):
    """Read the version resource without loading or executing the PE file."""
    from ctypes import wintypes as w
    # The extension avoids PyInstaller mistaking the bundled VERSION text for
    # a DLL on Windows; SYSTEM32 keeps the loader on the trusted OS library.
    library = ctypes.WinDLL("version.dll", winmode=0x800, use_last_error=True)
    library.GetFileVersionInfoSizeW.argtypes = [w.LPCWSTR, ctypes.POINTER(w.DWORD)]
    library.GetFileVersionInfoSizeW.restype = w.DWORD
    library.GetFileVersionInfoW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID]
    library.GetFileVersionInfoW.restype = w.BOOL
    library.VerQueryValueW.argtypes = [w.LPCVOID, w.LPCWSTR, ctypes.POINTER(w.LPVOID), ctypes.POINTER(w.UINT)]
    library.VerQueryValueW.restype = w.BOOL
    ignored = w.DWORD()
    size = library.GetFileVersionInfoSizeW(str(path), ctypes.byref(ignored))
    if not 0 < size <= 1 << 20:
        _fail("executable_version")
    buffer = ctypes.create_string_buffer(size)
    if not library.GetFileVersionInfoW(str(path), 0, size, buffer):
        _fail("executable_version")
    values = {}
    for key in ("ProductName", "ProductVersion"):
        pointer, length = w.LPVOID(), w.UINT()
        query = "\\StringFileInfo\\040904B0\\" + key
        if (not library.VerQueryValueW(buffer, query, ctypes.byref(pointer), ctypes.byref(length))
                or not pointer.value or not 1 < length.value <= 256):
            _fail("executable_version")
        text = ctypes.wstring_at(pointer.value, length.value)
        if not text.endswith("\0") or "\0" in text[:-1]:
            _fail("executable_version")
        values[key] = text[:-1]
    return values


def _executable(path, expected_version=None):
    with Path(path).open("rb") as stream:
        header = stream.read(4096)
    if len(header) < 128 or header[:2] != b"MZ":
        _fail("executable")
    offset = struct.unpack_from("<I", header, 0x3c)[0]
    if (offset > len(header) - 96 or header[offset:offset + 4] != b"PE\0\0"
            or struct.unpack_from("<H", header, offset + 4)[0] != 0x8664
            or struct.unpack_from("<H", header, offset + 24)[0] != 0x20b
            or struct.unpack_from("<H", header, offset + 24 + 68)[0] != 2):
        _fail("executable")
    if expected_version is not None and os.name == "nt":
        values = _file_version(path)
        if values.get("ProductName") != PRODUCT_NAME or values.get("ProductVersion") != expected_version:
            _fail("executable_version")


def _world(path):
    try:
        app_runtime.validate_apworld_archive(path)
        with ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or len(names) > 4096 or sum(row.file_size for row in archive.infolist()) > 256 << 20:
                _fail("apworld")
            if "ootrr_remake/__init__.py" not in names or "ootrr_remake/archipelago.json" not in names:
                _fail("apworld")
            for info in archive.infolist():
                name = info.filename
                parts = name.replace("\\", "/").split("/")
                if ("\\" in name or parts[0] != "ootrr_remake" or ".." in parts or "." in parts
                        or "" in parts[:-1] or ":" in name or stat.S_ISLNK(info.external_attr >> 16)):
                    _fail("apworld")
    except UpdateError:
        raise
    except (OSError, ValueError, BadZipFile):
        _fail("apworld")


def download_update(release, base=None, progress=None, cancel=None):
    if not isinstance(release, dict) or not isinstance(release.get("assets"), dict):
        _fail("release_assets")
    version = release.get("latest_version")
    version_key(version)
    assets = release.get("assets", {})
    for key, maximum in (("executable", MAX_EXECUTABLE), ("apworld", MAX_APWORLD)):
        asset = assets.get(key, {})
        if not isinstance(asset, dict):
            _fail("release_assets")
        name = "ootrr_remake.apworld" if key == "apworld" else "OOT-Remake-Archipelago-" + version + ".exe"
        expected = "https://github.com/" + REPOSITORY + "/releases/download/v" + version + "/" + name
        if (asset.get("name") != name or asset.get("url") != expected
                or type(asset.get("size")) is not int or not 0 < asset["size"] <= maximum
                or not isinstance(asset.get("sha256"), str) or not SHA_PATTERN.fullmatch(asset["sha256"])):
            _fail("release_assets")
    root = Path(base or app_runtime.default_base()).expanduser().resolve() / "updates"
    root.mkdir(parents=True, exist_ok=True)
    stage = root / uuid.uuid4().hex
    stage.mkdir()
    total = sum(assets[key]["size"] for key in ("executable", "apworld"))
    completed, paths = 0, {}
    try:
        for key in ("executable", "apworld"):
            asset = assets[key]
            target = stage / asset["name"]
            temporary = target.with_suffix(target.suffix + ".part")
            count, digest = 0, hashlib.sha256()
            _cancel(cancel)
            with _open(asset["url"]) as source, temporary.open("xb") as output:
                while chunk := source.read(256 << 10):
                    _cancel(cancel)
                    count += len(chunk)
                    if count > asset["size"]:
                        _fail("size")
                    digest.update(chunk)
                    output.write(chunk)
                    if progress:
                        progress(min(95, int(95 * (completed + count) / total)), tr("Downloading the application update…"))
                output.flush()
                os.fsync(output.fileno())
            if count != asset["size"] or digest.hexdigest() != asset["sha256"]:
                _fail("checksum")
            if key == "executable":
                _executable(temporary, version)
            else:
                _world(temporary)
            temporary.replace(target)
            paths[key] = str(target)
            completed += count
        _cancel(cancel)
        result = dict(version=version, stage=str(stage), base=str(root.parent), release_url=release["release_url"],
                      hashes={key: assets[key]["sha256"] for key in ("executable", "apworld")}, **paths)
        atomic(stage / "download.json", json.dumps(result, indent=2).encode())
        if progress:
            progress(100, tr("The application update is ready."))
        return result
    except BaseException:
        # Only files created by this transaction may be removed; no recursive
        # operation is used on a user-supplied or computed directory.
        for path in stage.iterdir():
            if path.is_file() and not path.is_symlink():
                path.unlink()
        stage.rmdir()
        raise


def _world_folder(target):
    destination = Path(target).expanduser().resolve()
    if destination.name.casefold() != "custom_worlds":
        if not (destination / "ArchipelagoGenerate.exe").is_file() and not (destination / "Generate.py").is_file():
            raise ValueError(tr("Choose your Archipelago installation folder."))
        destination /= "custom_worlds"
    return destination


def apworld_status(target, expected_sha256):
    if not isinstance(expected_sha256, str) or not SHA_PATTERN.fullmatch(expected_sha256):
        _fail("checksum")
    destination = _world_folder(target)
    world = destination / "ootrr_remake.apworld"
    current = _sha(world) if world.is_file() else None
    return dict(target=str(destination), world_path=str(world), exists=world.is_file(),
                changed=current != expected_sha256, current_sha256=current, expected_sha256=expected_sha256)


def _download(update, base=None):
    if not isinstance(update, dict) or not isinstance(update.get("hashes"), dict):
        _fail("plan")
    root = Path(base or app_runtime.default_base()).expanduser().resolve()
    stage = _local_path(update.get("stage"))
    if stage.parent != root / "updates" or not re.fullmatch(r"[0-9a-f]{32}", stage.name):
        _fail("plan")
    version = update.get("version")
    version_key(version)
    for key, name, maximum in (("executable", "OOT-Remake-Archipelago-" + version + ".exe", MAX_EXECUTABLE),
                               ("apworld", "ootrr_remake.apworld", MAX_APWORLD)):
        path = _local_path(update.get(key))
        expected = update.get("hashes", {}).get(key)
        if path != stage / name or path.is_symlink() or not isinstance(expected, str) or not SHA_PATTERN.fullmatch(expected):
            _fail("plan")
        if not path.is_file() or not 0 < path.stat().st_size <= maximum or _sha(path) != expected:
            _fail("checksum")
        if key == "executable":
            _executable(path, version)
        else:
            _world(path)
    return stage, root


def _local_path(value):
    """Require absolute local transaction paths, without leaf redirection."""
    if not isinstance(value, str) or not value or "\0" in value:
        _fail("plan")
    path = Path(value)
    if (not path.is_absolute() or path.is_symlink()
            or (getattr(path, "is_junction", lambda: False)())):
        _fail("plan")
    return path.resolve()


def install_world(update, target, base=None):
    """World-only update using this already matching app's bundled runtime."""
    _download(update, base)
    expected = update["hashes"]["apworld"]
    bundled = app_runtime.resource_root() / "ootrr_remake.apworld"
    if not bundled.is_file() or _sha(bundled) != expected:
        _fail("application_first", "The new application's bundled runtime is required.")
    status = apworld_status(target, expected)
    if not status["changed"]:
        return dict(world_updated=False, world_path=status["world_path"])
    world = app_runtime.install_apworld(status["target"], base=base)
    return dict(world_updated=True, world_path=str(world))


def _identity_for_handle(kernel, handle, pid):
    from ctypes import wintypes as w
    created, exited, kernel_time, user_time = w.FILETIME(), w.FILETIME(), w.FILETIME(), w.FILETIME()
    kernel.GetProcessTimes.argtypes = [w.HANDLE, ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME)]
    if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel_time), ctypes.byref(user_time)):
        _fail("process")
    path = ctypes.create_unicode_buffer(32768)
    size = w.DWORD(len(path))
    kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    if not kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
        _fail("process")
    return dict(pid=pid, created=(created.dwHighDateTime << 32) | created.dwLowDateTime,
                image=str(Path(path.value).resolve()))


def _process_identity(pid):
    """Capture a Windows process creation time so a reused PID is harmless."""
    if os.name != "nt":
        _fail("platform")
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.OpenProcess(0x1000 | 0x100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            return None
        _fail("process")
    try:
        return _identity_for_handle(kernel, handle, pid)
    finally:
        kernel.CloseHandle(handle)


def _parent_processes(target):
    current = _process_identity(os.getpid())
    if current is None or Path(current["image"]) != target:
        _fail("process")
    values = [current]
    parent = _process_identity(os.getppid())
    # A PyInstaller one-file bootloader can keep the target locked until its
    # child exits and extraction cleanup finishes. Wait for it as well.
    if parent is not None and Path(parent["image"]) == target:
        values.append(parent)
    return values


def schedule_install(update, base=None, world_target=None, apworld_target=None):
    if not can_replace_executable():
        _fail("standalone_required")
    if not isinstance(update, dict):
        _fail("plan")
    if compare_versions(update.get("version"), current_version()) <= 0:
        _fail("not_newer")
    stage, root = _download(update, base)
    target = _local_path(sys.executable)
    if target.is_symlink() or target.parent == stage or target.suffix.lower() != ".exe":
        _fail("target")
    if world_target is not None and apworld_target is not None:
        _fail("plan")
    world_target = world_target if world_target is not None else apworld_target
    if world_target is not None:
        world_target = apworld_status(world_target, update["hashes"]["apworld"])["target"]
    helper = stage / "update-helper.exe"
    if helper.exists() or (stage / "plan.json").exists():
        _fail("already_scheduled")
    original_hash = _sha(target)
    shutil.copy2(target, helper)
    if _sha(helper) != original_hash:
        _fail("checksum")
    nonce = uuid.uuid4().hex
    plan = dict(schema=SCHEMA, base=str(root), stage=str(stage), version=update["version"],
                executable=update["executable"], apworld=update["apworld"], hashes=update["hashes"],
                target=str(target), original_sha256=original_hash, helper=str(helper), parents=_parent_processes(target),
                backup=str(target.with_name(target.name + ".previous-" + nonce[:12] + ".exe")),
                adjacent=str(target.with_name("." + target.name + ".update-" + nonce + ".tmp")),
                world_target=world_target, state="pending")
    path = stage / "plan.json"
    atomic(path, json.dumps(plan, indent=2).encode())
    environment = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    try:
        process = app_runtime.spawn_process([str(helper), "--apply-update", str(path)], cwd=stage, env=environment,
                                          stdin=subprocess_devnull(), stdout=subprocess_devnull(), stderr=subprocess_devnull())
        _await_ready(process, path)
    except BaseException:
        plan["state"] = "cancelled"
        atomic(path, json.dumps(plan, indent=2).encode())
        raise
    return dict(helper_started=True, plan=str(path), version=update["version"])


def subprocess_devnull():
    import subprocess
    return subprocess.DEVNULL


def _ready(path, plan):
    atomic(path.parent / "ready.json", json.dumps(dict(schema=SCHEMA, plan_sha256=_sha(path),
           target=plan["target"], helper_sha256=plan["original_sha256"], pid=os.getpid())).encode())


def _await_ready(process, path, timeout=30):
    expected = _sha(path)
    deadline = time.monotonic() + timeout
    ready = path.parent / "ready.json"
    while True:
        if process.poll() is not None:
            _fail("helper_start")
        if ready.is_file():
            if ready.stat().st_size > 4096:
                _fail("helper_start")
            try:
                value = json.loads(ready.read_bytes())
                plan = json.loads(path.read_bytes())
            except (ValueError, UnicodeError):
                _fail("helper_start")
            if (not isinstance(value, dict) or not isinstance(plan, dict)
                    or value.get("schema") != SCHEMA or value.get("plan_sha256") != expected
                    or _sha(path) != expected or value.get("target") != plan["target"]
                    or value.get("helper_sha256") != plan["original_sha256"]
                    or type(value.get("pid")) is not int or value["pid"] <= 0):
                _fail("helper_start")
            return
        if time.monotonic() >= deadline:
            _fail("helper_timeout")
        time.sleep(.1)


def _plan(path, base=None):
    path = _local_path(str(path))
    if path.name != "plan.json" or path.is_symlink() or path.stat().st_size > 32 << 10:
        _fail("plan")
    try:
        plan = json.loads(path.read_bytes())
    except (ValueError, UnicodeError):
        _fail("plan")
    if not isinstance(plan, dict) or plan.get("schema") != SCHEMA:
        _fail("plan")
    stage, root = _download(plan, base)
    if path.parent != stage or plan.get("base") != str(root):
        _fail("plan")
    target = _local_path(plan.get("target"))
    helper = _local_path(plan.get("helper"))
    if (helper != stage / "update-helper.exe" or not helper.is_file()
            or _sha(helper) != plan.get("original_sha256") or target.suffix.lower() != ".exe"
            or target.parent == stage or target.is_symlink()):
        _fail("plan")
    backup, adjacent = _local_path(plan.get("backup")), _local_path(plan.get("adjacent"))
    if (backup.parent != target.parent or not re.fullmatch(re.escape(target.name) + r"\.previous-[0-9a-f]{12}\.exe", backup.name)
            or adjacent.parent != target.parent or not re.fullmatch(r"\." + re.escape(target.name) + r"\.update-[0-9a-f]{32}\.tmp", adjacent.name)):
        _fail("plan")
    # New applications finish schema-1 updates initiated by older launchers.
    # These paths are derived from the already verified transaction, never
    # accepted as a general destination or cleanup instruction.
    if "installed_target" in plan:
        installed = _local_path(plan["installed_target"])
        if (installed != target.with_name("OOT-Remake-Archipelago-" + plan["version"] + ".exe")
                or plan.get("state") not in {"applied", "completed"}):
            _fail("plan")
    if "private_backup" in plan:
        private_backup = _local_path(plan["private_backup"])
        if (private_backup != stage / "previous-launcher.exe" or not private_backup.is_file()
                or _sha(private_backup) != plan["original_sha256"]):
            _fail("plan")
    parents = plan.get("parents")
    if not isinstance(parents, list) or not 1 <= len(parents) <= 2:
        _fail("plan")
    for parent in parents:
        if (not isinstance(parent, dict) or type(parent.get("pid")) is not int or parent["pid"] <= 0
                or type(parent.get("created")) is not int or parent["created"] <= 0
                or _local_path(parent.get("image")) != target):
            _fail("plan")
    if plan.get("world_target") is not None:
        _world_folder(plan["world_target"])
    return path, plan


def _wait_for_parents(plan, timeout=180):
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    kernel.WaitForSingleObject.restype = w.DWORD
    deadline = time.monotonic() + timeout
    for parent in plan["parents"]:
        if parent["pid"] == os.getpid():
            _fail("process")
        handle = kernel.OpenProcess(0x100000 | 0x1000, False, parent["pid"])
        if not handle:
            if ctypes.get_last_error() == 87:
                continue
            _fail("process")
        try:
            if kernel.WaitForSingleObject(handle, 0) == 0:
                continue
            try:
                identity = _identity_for_handle(kernel, handle, parent["pid"])
            except UpdateError:
                # The pinned process can finish between opening its handle
                # and querying its image. A signalled handle proves its exit
                # without trusting a potentially reused PID.
                if kernel.WaitForSingleObject(handle, 0) == 0:
                    continue
                raise
            if identity != parent:
                continue  # Keep the checked handle; PID reuse cannot change it.
            milliseconds = max(0, int((deadline - time.monotonic()) * 1000))
            if kernel.WaitForSingleObject(handle, milliseconds) != 0:
                _fail("process_timeout")
        finally:
            kernel.CloseHandle(handle)


def _replace(source, destination, timeout=20):
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.2)


def _launch(command):
    return app_runtime.spawn_process(command, cwd=Path(command[0]).parent,
        env=dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1"),
        stdin=subprocess_devnull(), stdout=subprocess_devnull(), stderr=subprocess_devnull())


@contextmanager
def _replacement_lock(path, *, existing_only=False):
    """Keep the legacy lock identity, deleting it atomically on Windows close.

    Removing a shared lock after releasing it can split concurrent updaters
    across different files. Windows instead marks this exclusively held handle
    for deletion, including when its helper exits unexpectedly. Save locks keep
    their existing persistent behavior; the updater only runs on Windows.
    """
    path = Path(path)
    if _local_path(str(path)) != path:
        _fail("update_lock")
    if os.name != "nt":
        if existing_only and not path.exists():
            raise FileNotFoundError(path)
        with exclusive(path):
            yield
        return
    from ctypes import wintypes as w
    class FileInfo(ctypes.Structure):
        _fields_ = [("attributes", w.DWORD), ("created", w.FILETIME),
                    ("accessed", w.FILETIME), ("written", w.FILETIME),
                    ("volume", w.DWORD), ("size_high", w.DWORD), ("size_low", w.DWORD),
                    ("links", w.DWORD), ("index_high", w.DWORD), ("index_low", w.DWORD)]
    class Disposition(ctypes.Structure):
        _fields_ = [("delete", w.BYTE)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
    kernel.CreateFileW.restype = w.HANDLE
    kernel.GetFileInformationByHandle.argtypes = [w.HANDLE, ctypes.POINTER(FileInfo)]
    kernel.GetFileInformationByHandle.restype = w.BOOL
    kernel.SetFileInformationByHandle.argtypes = [w.HANDLE, w.DWORD, ctypes.c_void_p, w.DWORD]
    kernel.SetFileInformationByHandle.restype = w.BOOL
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle.restype = w.BOOL
    # OPEN_REPARSE_POINT never follows a replaced leaf. Existing legacy helpers
    # use this same filename and share mode, so their lock still excludes ours.
    handle = kernel.CreateFileW(str(path), 0xC0010000, 0, None,
                                3 if existing_only else 4, 0x200080, None)
    if handle == ctypes.c_void_p(-1).value:
        error = ctypes.get_last_error()
        if error in (5, 32, 33):
            # Windows reports ACCESS_DENIED for an existing delete-pending
            # handle as well as SHARING_VIOLATION for a legacy helper's lock.
            raise BlockingIOError(error, "The launcher update lock is unavailable.", str(path))
        raise ctypes.WinError(error)
    try:
        info = FileInfo()
        if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if info.attributes & (0x10 | 0x400) or info.size_high or info.size_low or info.links != 1:
            _fail("update_lock")
        disposition = Disposition(True)
        if not kernel.SetFileInformationByHandle(handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)):
            raise ctypes.WinError(ctypes.get_last_error())
        yield
    finally:
        kernel.CloseHandle(handle)


def apply_update_plan(path, base=None, wait_parent=None, launcher=None):
    """Wait, replace and restart only the launcher. Never terminate a process."""
    path, plan = _plan(path, base)
    if plan.get("state") != "pending":
        _fail("already_applied")
    (wait_parent or _wait_for_parents)(plan)
    path, plan = _plan(path, base)
    if plan.get("state") != "pending":
        _fail("cancelled")
    target, backup, adjacent = (Path(plan[key]) for key in ("target", "backup", "adjacent"))
    moved, replaced = False, False
    # Share the lock between different staging directories and app instances.
    with _replacement_lock(target.with_name("." + target.name + ".archipelago-update.lock")):
        if (not target.is_file() or _sha(target) != plan["original_sha256"] or backup.exists() or adjacent.exists()):
            _fail("target_changed")
        try:
            with Path(plan["executable"]).open("rb") as incoming, adjacent.open("xb") as output:
                shutil.copyfileobj(incoming, output, 1 << 20)
                output.flush()
                os.fsync(output.fileno())
            if _sha(adjacent) != plan["hashes"]["executable"]:
                _fail("checksum")
            if _local_path(str(target)) != target or _sha(target) != plan["original_sha256"]:
                _fail("target_changed")
            _replace(target, backup)
            moved = True
            _replace(adjacent, target)
            replaced = True
            plan["state"] = "applied"
            atomic(path, json.dumps(plan, indent=2).encode())
            (launcher or _launch)([str(target), "--complete-update", str(path)])
        except BaseException:
            if moved and (not target.exists() or (replaced and _sha(target) == plan["hashes"]["executable"])):
                _replace(backup, target)
            if adjacent.exists() and adjacent.is_file() and not adjacent.is_symlink():
                adjacent.unlink()
            plan["state"] = "failed"
            atomic(path, json.dumps(plan, indent=2).encode())
            raise
    return dict(applied=True, target=str(target), backup=str(backup), version=plan["version"])


def helper_main(plan_path):
    if not can_replace_executable():
        _fail("standalone_required")
    path, plan = _plan(plan_path)
    if Path(sys.executable).resolve() != Path(plan["helper"]):
        _fail("helper_identity")
    if plan.get("state") != "pending":
        _fail("cancelled")
    _ready(path, plan)
    apply_update_plan(path)
    return 0


def complete_update(plan_path, base=None):
    """Run inside the NEW app so an optional APWorld gets its NEW Node runtime."""
    path, plan = _plan(plan_path, base)
    installed = plan.get("installed_target", plan["target"])
    if (plan.get("state") not in {"applied", "completed"} or Path(sys.executable).resolve() != Path(installed)
            or _sha(installed) != plan["hashes"]["executable"] or current_version() != plan["version"]):
        _fail("completion_identity")
    if plan["state"] == "completed":
        if not isinstance(plan.get("completion"), dict):
            _fail("plan")
        return dict(plan["completion"])
    from .update_finalize import prepare_completion
    handoff = prepare_completion(path, plan, base=base)
    if handoff is not None:
        return handoff
    path, plan = _plan(path, base)
    result = dict(world_updated=False, world_path=None, version=plan["version"],
                  backup=plan.get("private_backup", plan["backup"]))
    if plan.get("world_target") is not None:
        try:
            result.update(install_world(plan, plan["world_target"], base=base))
        except Exception as error:
            logging.exception("Optional APWorld update failed after launcher replacement")
            result.update(error_code=getattr(error, "code", "apworld_update_failed"),
                          error=tr("The application was updated, but the APWorld could not be replaced."))
    plan["state"] = "completed"
    plan["completion"] = result
    atomic(path, json.dumps(plan, indent=2).encode())
    return result
