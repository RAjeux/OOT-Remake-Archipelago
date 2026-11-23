"""Console-free preparation, installation and normal launching for the desktop app.

The service never edits save files or runs the legacy live-input client. Room
scouting is read-only. The old mod and settings are kept until all resources
have been prepared, then retained in the installer backup on failure.
"""
import asyncio
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import traceback
import uuid

from . import install_mod, native_setup, player
from .catalog import LEGACY_GAME, LOCATION_IDS, PROTOCOL, SHOP_CHECKS
from .connection_control import ControlError, default_base, normalize_server
from .engine import EnginePathError
from .i18n import detect_language, tr
from .room_view import RoomView
from .save_bridge import atomic, exclusive, history_cursor, write_json


class InstallError(Exception):
    """A translated public message; detailed failures stay in the private log."""

    def __init__(self, public_message, diagnostic_log=""):
        self.public_message = public_message
        self.diagnostic_log = str(diagnostic_log)
        super().__init__(public_message)


class InstallCancelled(InterruptedError):
    cancelled = True

    def __init__(self):
        self.public_message = tr("Setup cancelled.")
        super().__init__(self.public_message)


def _base(value=None):
    return Path(value).expanduser().resolve() if value else default_base().resolve()


def _json(path, default=None):
    try:
        if Path(path).stat().st_size > 16 << 20:
            return default
        return json.loads(Path(path).read_bytes())
    except (OSError, ValueError, RecursionError):
        return default


def _folder(value):
    path = Path(value).expanduser().resolve()
    if path.name.casefold() in {"triforce.exe", "hookshot.exe"}:
        return path.parent.parent if path.parent.name.casefold() == "bin" else path.parent
    return path


def _host(value=None):
    selected = value or "nx2navi"
    if selected not in {"nx2navi", "hookshot"}:
        raise InstallError(tr("Choose Triforce or the experimental Hookshot integration."))
    return selected


def _adapter(host):
    if host == "hookshot":
        from . import hookshot_setup
        return hookshot_setup
    return native_setup


def _executable_name(host):
    return "hookshot.exe" if host == "hookshot" else "Triforce.exe"


def _host_base(base, host):
    return base / "hosts/hookshot" if host == "hookshot" else base


def _compiled_game(host, romfs, tools):
    return (bool(_adapter(host).compiled_executable(romfs, tools)) if host == "hookshot"
            else native_setup.compiled_game(romfs, tools))


def _tools_for(game, value, host):
    if not value and host == "hookshot":
        found = _adapter(host).discover(game=game)
        value = found.get("native_tools") or found.get("tools")
    return Path(value or "").expanduser().resolve()


def _validate_installation(game, romfs, tools, host):
    if (not any((folder / _executable_name(host)).is_file() for folder in (game, game / "bin"))
            or not (game / "image.bin").is_file()):
        message = ("Choose the Hookshot folder containing hookshot.exe and image.bin." if host == "hookshot"
                   else "Choose the Triforce folder containing Triforce.exe and image.bin.")
        raise InstallError(tr(message))
    if not (romfs / "Pack/ZsDic.pack.zs").is_file():
        raise InstallError(tr("Choose your version 1.1.1 game's romfs folder."))
    if (game / "romfs").resolve() != romfs:
        raise InstallError(tr("The selected romfs must belong to the selected game installation."))
    if host == "hookshot":
        validate = getattr(_adapter(host), "validate_installation", None)
        if validate:
            validate(game, tools)
    elif not (tools / "host/hos_main.c").is_file() or not (tools / "nx2/build.py").is_file():
        raise InstallError(tr("Install Triforce's build tools in Triforce Setup first."))


def inspect_installation(request):
    """Read-only preflight used by the desktop form before any AP connection."""
    host = _host(request.get("host"))
    game = _folder(request.get("game", ""))
    romfs = Path(request.get("romfs") or game / "romfs").expanduser().resolve()
    tools = _tools_for(game, request.get("tools"), host)
    _validate_installation(game, romfs, tools, host)
    return dict(valid=True, host=host, tools=str(tools))


def _emit(progress, percent, message):
    if progress:
        progress(percent, message)


def _cancelled(cancel):
    if cancel is not None and cancel.is_set():
        raise InstallCancelled()


def _profile(base):
    marker = _json(base / "last-profile.json", {})
    candidate = marker.get("root") if isinstance(marker, dict) else None
    if not candidate:
        token = _json(base / "derniere-salle-native.json")
        candidate = str(base / token) if isinstance(token, str) and re.fullmatch(r"[0-9a-f]{64}", token) else None
    if isinstance(candidate, (str, os.PathLike)) and candidate:
        path = Path(candidate).expanduser().resolve()
        if path.parent == base and re.fullmatch(r"[0-9a-f]{64}", path.name):
            return path
    return None


def _registered_game():
    if os.name != "nt":
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Triforce") as key:
            value, _ = winreg.QueryValueEx(key, "GameFolder")
        return Path(value) if isinstance(value, str) and value else None
    except OSError:
        return None


def discover(base=None, host=None):
    """Read remembered and standard paths; do not create files or start a game."""
    app_base = _base(base)
    desktop = _json(app_base / "desktop-host.json", {})
    desktop = desktop if isinstance(desktop, dict) else {}
    previous = _json(app_base / "outils.json", {})
    previous = previous if isinstance(previous, dict) else {}
    remembered_host = desktop.get("host") or previous.get("host")
    if remembered_host not in {"nx2navi", "hookshot"}:
        remembered_host = None
    host = _host(host or remembered_host)
    base = _host_base(app_base, host)
    cfg = _json(base / "outils.json", {})
    if not isinstance(cfg, dict):
        cfg = {}
    cfg = dict(cfg)
    for name in ("game", "romfs", "native_tools", "ootrr", "manifest"):
        if name in cfg and not isinstance(cfg[name], (str, os.PathLike)):
            cfg.pop(name)
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share"))
    ports = cfg.get("ports", {})
    port = ports.get(host, {}) if isinstance(ports, dict) else {}
    port = port if isinstance(port, dict) else {}
    port = {name: value for name, value in port.items() if isinstance(value, (str, os.PathLike))}
    remembered = cfg if cfg.get("host", "nx2navi") == host else {}
    candidates = [Path(port["game"]) if isinstance(port.get("game"), str) and port["game"] else None,
                  Path(remembered["game"]) if remembered.get("game") else None,
                  Path(remembered["romfs"]).parent if remembered.get("romfs") else None,
                  _registered_game(), Path.home() / "Games/Triforce"]
    game = next((path for path in candidates if path and any((folder / "Triforce.exe").is_file()
                 for folder in (path, path / "bin"))), Path.home() / "Games/Triforce")
    tools = Path(port.get("native_tools") or remembered.get("native_tools") or local / "Programs/Triforce/tools")
    if host == "hookshot":
        found = _adapter(host).discover(game=port.get("game") or remembered.get("game"),
                                       tools=port.get("native_tools") or remembered.get("native_tools"))
        game = Path(found["game"])
        tools = Path(found.get("native_tools") or found.get("tools") or "")
    configured_mods = port.get("mods")
    mods = Path(configured_mods if isinstance(configured_mods, (str, os.PathLike)) and configured_mods else game / "mods")
    profile = _profile(base)
    session = _json(profile / "native-session.json", {}) if profile else {}
    if not isinstance(session, dict):
        session = {}
    try:
        from .app_runtime import bundled_node
        node = bundled_node() or ""
    except (ImportError, OSError):
        node = os.environ.get("OOTRR_NODE") or shutil.which("node") or ""
    pinned = base / "tools/OOTRR-0.8.1-windows-x64-portable/ootrr.exe"
    # Old preferences can point at an automatically updated OOTRR 0.8.2.
    # Leave the default empty so setup obtains its verified compatible tool.
    builder = str(pinned) if pinned.is_file() else ""
    romfs = Path(port.get("romfs") or remembered.get("romfs") or game / "romfs")
    try:
        ready = bool(profile and session.get("Token") == profile.name
                     and (mods / "Archipelago/romfs/Archipelago/room-v1.txt").read_text().strip() == profile.name
                     and (game / "romfs").resolve() == romfs.resolve()
                     and _compiled_game(host, game / "romfs", tools))
    except (OSError, ValueError):
        ready = False
    return dict(base=str(base), app_base=str(app_base), host=host, game=str(game), romfs=str(romfs),
                tools="" if host == "hookshot" and tools == Path(".") else str(tools), mods=str(mods),
                builder=builder, node=str(node), manifest=cfg.get("manifest", ""),
                server=session.get("Server", "127.0.0.1:38281"), profile=str(profile or ""),
                auto_connect=bool(session.get("AutoConnect", True)),
                room=session.get("Room", ""), slot=session.get("Slot", ""), token=session.get("Token", ""),
                language=detect_language(profile or base, dict(cfg, exe=str(game / _executable_name(host)), romfs=str(romfs))),
                ready=ready, build_required=not ready,
                diagnostic_log=str(base / "setup-diagnostic.log"))


def inspect_manifest(path):
    try:
        if Path(path).stat().st_size > 16 << 20:
            raise ValueError()
        data = player.read_manifest(path)
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        raise InstallError(tr("Choose a valid Archipelago .apootrr player file.")) from None
    return {key: data[key] for key in ("room", "slot", "player", "token")} | {"checks": len(data["checks"])}


async def fetch_roster(data, server, password, cancel=None, timeout=45):
    """Authenticate and scout without checking locations or consuming items."""
    from websockets.legacy.client import connect
    room = RoomView(data["player"])
    scouts = {}
    stable_names = {}
    authenticated = False
    _cancelled(cancel)
    async with asyncio.timeout(timeout):
        async with connect(server, open_timeout=min(timeout, 15), max_size=32 << 20) as ws:
            async def send(*packets):
                await ws.send(json.dumps(packets))
            while True:
                _cancelled(cancel)
                try:
                    raw = await asyncio.wait_for(ws.recv(), .25)
                except asyncio.TimeoutError:
                    continue
                for message in json.loads(raw):
                    command = message.get("cmd")
                    if command == "RoomInfo":
                        if str(message.get("seed_name")) != data["room"]:
                            raise InstallError(tr("This server is hosting a different room. Check the server address and player file."))
                        await send(dict(cmd="Connect", name=data["slot"], game=data.get("game", LEGACY_GAME),
                                        uuid=str(uuid.uuid4()), password=password or None,
                                        items_handling=5 if data.get("local_items") else 7,
                                        tags=["AP"], slot_data=True,
                                        version=dict(major=0, minor=6, build=7, **{"class": "Version"})))
                    elif command == "ConnectionRefused":
                        errors = message.get("errors", [])
                        if "InvalidPassword" in errors:
                            raise InstallError(tr("The room password is incorrect."))
                        if "SlotAlreadyTaken" in errors:
                            raise InstallError(tr("This player is already connected. Close Zelda or its older client first."))
                        raise InstallError(tr("The server refused this player. Check the player file and room settings."))
                    elif command == "Connected":
                        slot_data = message.get("slot_data") or {}
                        expected = {LOCATION_IDS[name] for name in data["checks"]}
                        if (slot_data.get("protocol") != PROTOCOL or slot_data.get("token") != data["token"]
                                or message.get("slot") != data["player"] or set(slot_data.get("checks", [])) != expected):
                            raise InstallError(tr("The player file and server slot belong to different generations."))
                        authenticated = True
                        needed = room.connected(message)
                        stable_names = {int(key): value["name"] for key, value in message["slot_info"].items()}
                        await send(dict(cmd="LocationScouts", locations=sorted(expected), create_as_hint=0))
                        if needed:
                            await send(dict(cmd="GetDataPackage", games=needed))
                    elif command == "DataPackage" and authenticated:
                        room.load_package(message)
                    elif command == "LocationInfo" and authenticated:
                        for record in message["locations"]:
                            item, location, owner = ((record["item"], record["location"], record["player"])
                                                     if isinstance(record, dict) else record[:3])
                            scouts[location] = (item, owner)
                expected = {LOCATION_IDS[name]: name for name in data["checks"]}
                if not authenticated or room.waiting or not expected.keys() <= scouts.keys():
                    continue
                roster = {}
                for location, name in expected.items():
                    item, owner = scouts[location]
                    if owner == data["player"] and not (data.get("local_items") or data.get("reward_mode") == "all_chest_rewards"):
                        continue
                    names = room.names.get(room.games.get(owner), {}).get("item_id", {})
                    if item not in names or owner not in stable_names:
                        raise InstallError(tr("The server did not provide an item or recipient name."))
                    item_name, owner_name = room.name("item_id", item, owner), stable_names[owner]
                    roster[name] = (dict(item=item_name, player=owner_name, owner=owner, item_id=item,
                                         local=owner == data["player"], game=room.games.get(owner))
                                    if data.get("local_items") else (item_name, owner_name))
                return roster


def _running_game(game, tools, host="nx2navi"):
    if os.name != "nt":
        return False
    import ctypes as C
    from ctypes import wintypes as W
    class Process(C.Structure):
        _fields_ = [("size", W.DWORD), ("usage", W.DWORD), ("pid", W.DWORD), ("heap", C.c_size_t),
                    ("module", W.DWORD), ("threads", W.DWORD), ("parent", W.DWORD),
                    ("priority", W.LONG), ("flags", W.DWORD), ("exe", W.WCHAR * 260)]
    kernel = C.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = W.HANDLE
    kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = [W.HANDLE, C.POINTER(Process)]
    kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    kernel.OpenProcess.restype = W.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
    kernel.CloseHandle.argtypes = [W.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == C.c_void_p(-1).value:
        raise InstallError(tr("Unable to check whether Zelda is running. Close it and try again."))
    executable = _executable_name(host)
    setup = "HookshotSetup.exe" if host == "hookshot" else "TriforceSetup.exe"
    targets = {(game / executable).resolve(), (game / "bin" / executable).resolve(),
               (tools.parent / setup).resolve()}
    try:
        entry = Process(size=C.sizeof(Process))
        found = kernel.Process32FirstW(snapshot, C.byref(entry))
        while found:
            if entry.exe.casefold() in {executable.casefold(), setup.casefold()}:
                handle = kernel.OpenProcess(0x1000, False, entry.pid)
                if not handle:
                    return True
                try:
                    size = W.DWORD(32768)
                    value = C.create_unicode_buffer(size.value)
                    if not kernel.QueryFullProcessImageNameW(handle, 0, value, C.byref(size)) or Path(value.value).resolve() in targets:
                        return True
                finally:
                    kernel.CloseHandle(handle)
            found = kernel.Process32NextW(snapshot, C.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    return False


@contextmanager
def _node_environment(node):
    previous = os.environ.get("OOTRR_NODE")
    if node:
        os.environ["OOTRR_NODE"] = str(node)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("OOTRR_NODE", None)
        else:
            os.environ["OOTRR_NODE"] = previous


def _backup_files(paths, backup):
    backup.mkdir(parents=True)
    result = {}
    for number, path in enumerate(dict.fromkeys(map(Path, paths))):
        if path.is_file():
            copy = backup / (str(number) + "-" + path.name)
            shutil.copy2(path, copy)
            result[path] = copy
        elif path.exists():
            raise InstallError(tr("An installation file is occupied by a folder. Choose another installation."))
        else:
            result[path] = None
    return result


def _restore_files(files):
    for path, copy in files.items():
        if copy is None:
            path.unlink(missing_ok=True)
        else:
            atomic(path, copy.read_bytes())
            shutil.copystat(copy, path)


def _build_environment(game, tools, mods):
    """Keep the renderer/SDK choices already supplied by Triforce Setup."""
    environment = dict(os.environ, HOS_MODS=str(mods))
    for key in list(environment):
        if key.startswith("HOS_INPUT_"):
            environment.pop(key)
    def wgpu(value):
        if not value:
            return False
        root = Path(value).expanduser()
        return ((root / "include/webgpu/webgpu.h").is_file() and (root / "lib/wgpu_native.dll").is_file()
                and any((root / "lib" / name).is_file() for name in ("wgpu_native.dll.lib", "libwgpu_native.dll.a")))
    if not wgpu(environment.get("WGPU_NATIVE")) and wgpu(tools / "wgpu-native"):
        environment["WGPU_NATIVE"] = str(tools / "wgpu-native")
    def ngx(value):
        if not value:
            return False
        root = Path(value).expanduser()
        return (root / "include/nvsdk_ngx.h").is_file() and (root / "lib/nvsdk_ngx_s.lib").is_file()
    sdk = tools.parent / "ngx-sdk"
    if (game / "ngx").is_dir() and not ngx(environment.get("HOOKSHOT_NGX_SDK")) and ngx(sdk):
        environment["HOOKSHOT_NGX_SDK"] = str(sdk)
    return environment


def _build_game(game, tools, mods, log, progress):
    """Use Triforce's own update path, preserving its options and game files."""
    from .app_runtime import spawn_process
    python = tools / "python/python.exe"
    script = tools / "nx2/make_game.py"
    if not python.is_file() or not script.is_file() or not (game / ".triforce_exefs").is_dir():
        raise InstallError(tr("Update Triforce in its setup application before using automatic installation."))
    environment = _build_environment(game, tools, mods)
    command = [str(python), "-I", "-u", "-X", "utf8", str(script), "--update", str(game), "--no-prepare-shaders"]
    process = spawn_process(command, cwd=tools, env=environment, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    for line in process.stdout:
        log.write(line)
        log.flush()
        if line.startswith("@@stage "):
            _emit(progress, 91, tr("Building Triforce. This may take several minutes."))
        elif line.startswith("@@progress "):
            try:
                _emit(progress, 90 + int(float(line.split()[1]) * 7), tr("Building Triforce. This may take several minutes."))
            except (ValueError, IndexError):
                pass
    if process.wait() != 0:
        raise InstallError(tr("Triforce could not be rebuilt. Your previous installation has been restored."))


def install(request, progress=None, cancel=None):
    """Prepare and commit one room; callbacks run on the calling worker thread."""
    _cancelled(cancel)
    app_base = _base(request.get("base"))
    host = _host(request.get("host"))
    base = _host_base(app_base, host)
    base.mkdir(parents=True, exist_ok=True)
    diagnostic = base / "setup-diagnostic.log"
    password = request.get("password", "")
    try:
        return _install(dict(request, app_base=app_base), progress, cancel, base, diagnostic)
    except InstallCancelled:
        raise
    except InterruptedError:
        raise InstallCancelled() from None
    except EnginePathError as exc:
        raise InstallError(exc.public_message, diagnostic) from None
    except InstallError as exc:
        exc.diagnostic_log = str(diagnostic)
        raise
    except Exception as error:
        if host == "hookshot" and isinstance(error, getattr(_adapter(host), "HookshotError", ())):
            raise InstallError(error.public_message, diagnostic) from None
        detail = traceback.format_exc()
        if password:
            detail = detail.replace(password, "[redacted]")
        with diagnostic.open("a", encoding="utf-8") as log:
            log.write(detail)
        raise InstallError(tr("Setup could not be completed. Your previous saves are preserved. Open the diagnostic log for details."), diagnostic) from None


def _install(request, progress, cancel, base, diagnostic):
    from .app_runtime import bundled_node, ensure_builder
    _emit(progress, 0, tr("Checking your installation..."))
    manifest = Path(request.get("manifest", "")).expanduser().resolve()
    inspect_manifest(manifest)
    data = player.read_manifest(manifest)
    host = _host(request.get("host"))
    adapter = _adapter(host)
    try:
        server = normalize_server(request.get("server", ""))
    except ControlError:
        raise InstallError(tr("Enter a valid Archipelago server address.")) from None
    game = _folder(request.get("game", ""))
    romfs = Path(request.get("romfs") or game / "romfs").expanduser().resolve()
    tools = _tools_for(game, request.get("tools"), host)
    mods = Path(request.get("mods") or game / "mods").expanduser().resolve()
    _validate_installation(game, romfs, tools, host)
    if _running_game(game, tools, host):
        raise InstallError(tr("Close Zelda and its setup application before installing."))
    profile = base / data["token"]
    if profile.is_symlink() or (hasattr(profile, "is_junction") and profile.is_junction()):
        raise InstallError(tr("This room's profile is linked to another folder. Choose a normal application data folder."))
    previous_file = profile / "native-session.json"
    previous = _json(previous_file) if previous_file.exists() else {}
    if not isinstance(previous, dict):
        raise InstallError(tr("This room's existing profile is invalid. Open the diagnostic log for details."))
    if previous_file.exists() and any(previous.get(key) != data[value] for key, value in
                        (("Token", "token"), ("Room", "room"), ("Player", "player"), ("Slot", "slot"))):
        raise InstallError(tr("This room's existing profile does not match the player file."))
    automatic = bool(request.get("auto_connect", previous.get("AutoConnect", True)))
    baseline = previous.get("Baseline", history_cursor(profile))
    if type(baseline) is not int or baseline < 0:
        raise InstallError(tr("This room's existing profile is invalid. Open the diagnostic log for details."))
    profile.mkdir(parents=True, exist_ok=True)
    mods = install_mod.validate_root(mods, romfs, base)
    state = install_mod.state_dir(mods)
    state.mkdir(exist_ok=True)
    cfg = _json(base / "outils.json", {})
    if not isinstance(cfg, dict):
        cfg = {}
    with ExitStack() as locks:
        try:
            for path in (base / "setup.lock", profile / "client.lock", state / "session.lock"):
                locks.enter_context(exclusive(path))
            if (profile / "user").is_dir():
                locks.enter_context(exclusive(profile / "user/save.lock"))
        except BlockingIOError:
            raise InstallError(tr("Close Zelda and its setup application before installing.")) from None
        _cancelled(cancel)
        _emit(progress, 4, tr("Connecting to your Archipelago room..."))
        try:
            roster = asyncio.run(fetch_roster(data, server, request.get("password", ""), cancel))
        except (OSError, TimeoutError):
            raise InstallError(tr("The server could not be reached. Check its address and try again.")) from None
        _cancelled(cancel)
        _emit(progress, 10, tr("Preparing the required tools..."))
        builder_base = Path(request["app_base"])
        pinned_builder = builder_base / "tools/OOTRR-0.8.1-windows-x64-portable/ootrr.exe"
        if request.get("builder") and Path(request["builder"]).expanduser().resolve() != pinned_builder:
            builder = Path(request["builder"]).expanduser().resolve()
            from .builder import validate_builder
            validate_builder(builder)
        else:
            builder = Path(ensure_builder(builder_base, progress=lambda message: _emit(progress, 12, message), cancel=cancel))
        node = request.get("node") or bundled_node()
        if not node:
            raise InstallError(tr("The bundled randomizer runtime is missing. Download the complete application again."))
        _cancelled(cancel)
        runtime = dict(romfs=str(romfs), ootrr=str(builder), native=True, baseline=baseline, host="nx2navi",
                       install_only=True, exe=str(game / _executable_name(host)), server=server,
                       protected=native_setup.protect_password(request.get("password", "")),
                       reward_mode=data.get("reward_mode", "legacy_gear"), local_items=bool(data.get("local_items")),
                       player=data["player"], kokiri_shop_checks=bool(data.get("kokiri_shop_checks")),
                       shop_check_mode=data.get("shop_check_mode"), shop_checks=list(data.get("shop_checks", ())),
                       foreign_only_shops=bool(data.get("foreign_only_shops")), shuffle_skulltulas=data.get("shuffle_skulltulas", "off"),
                       adult_trade_shuffle=bool(data.get("adult_trade_shuffle")),
                       shop_prices={name: row["price"] for name, row in data["seed_file"].get("shops", {}).items() if name in SHOP_CHECKS})
        runtime["host"] = host
        assets = install_mod.build_cache(base, data["token"], host, {}, romfs) / native_setup.runtime_cache_name(baseline)
        runtime.update(assets=assets, other_tables={})
        with diagnostic.open("w", encoding="utf-8") as log, redirect_stdout(log), redirect_stderr(log), _node_environment(node):
            _emit(progress, 18, tr("Preparing your randomized game..."))
            player.build(assets, runtime, data)
            _cancelled(cancel)
            _emit(progress, 45, tr("Preparing item models and native rewards..."))
            source = player.prepare(assets, player.preparation_settings(runtime, data), roster, data["moved"])
            _cancelled(cancel)
            if _running_game(game, tools, host):
                raise InstallError(tr("Close Zelda and its setup application before installing."))
            _emit(progress, 74, tr("Finishing setup. Please keep this window open..."))
            backup = base / "backups" / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
            mutable = [base / name for name in ("outils.json", "last-profile.json", "derniere-salle-native.json")]
            mutable.append(Path(request["app_base"]) / "desktop-host.json")
            mutable.append(profile / "native-session.json")
            if host == "nx2navi":
                mutable += [tools / "host" / name for name in (*native_setup.RT_FILES, "hos_main.c")]
                mutable += [tools / "gpu/vk" / name for name in (*native_setup.MENU_FILES, "vk_menu.cpp")]
            copies = _backup_files(mutable, backup / "files")
            old_mod = mods / "Archipelago"
            old_inode = old_mod.stat().st_ino if old_mod.exists() else None
            mod_changed = False
            moved_seed = None
            try:
                tools = adapter.install_tools(base, lambda *args, **kwargs: tools, tools)
                native_setup.save_session(profile, runtime, data, roster, prepared=source / "Archipelago/romfs")
                session = _json(profile / "native-session.json", {})
                session["AutoConnect"] = automatic
                write_json(profile / "native-session.json", session)
                seed = mods / "My Seed"
                if seed.is_dir() and ((seed / "romfs" / install_mod.REST).is_file() or (seed / "romfs/UI/Layout2Archive").is_dir()):
                    if seed.is_symlink() or (hasattr(seed, "is_junction") and seed.is_junction()):
                        raise InstallError(tr("The old randomizer mod is linked to another folder. Disable it in the selected host before installing."))
                    moved_seed = state / ("previous-randomizer-" + uuid.uuid4().hex[:12])
                    seed.rename(moved_seed)
                dest = install_mod.install(source, mods, data["token"])
                mod_changed = old_inode is None or dest.stat().st_ino != old_inode
                compatible = _compiled_game(host, game / "romfs", tools)
                if not compatible and request.get("rebuild", True):
                    # A normal room change does not rebuild Triforce or copy
                    # hundreds of megabytes of unchanged executable files.
                    outputs = [folder / name for folder in (game, game / "bin")
                               for name in (_executable_name(host), "triforce_vk.dll", "hookshot_vk.dll", "SDL2.dll", "SDL3.dll", "wgpu_native.dll")]
                    outputs += [game / name for name in ("image.bin", ".triforce_installed.json", ".hookshot_build.json", "language.txt")]
                    outputs += [path for folder in (game, game / "bin") for path in folder.glob("*.dll")]
                    copies.update(_backup_files(outputs, backup / "game"))
                    if host == "hookshot":
                        _emit(progress, 86, tr("Building the experimental Hookshot integration. This may take several minutes."))
                        adapter.build_game(game, tools, log, progress=progress, cancel=cancel)
                    else:
                        _emit(progress, 86, tr("Building Triforce. This may take several minutes."))
                        _build_game(game, tools, mods, log, progress)
                    compatible = _compiled_game(host, game / "romfs", tools)
                    if not compatible:
                        raise InstallError(tr("The rebuilt game does not match the installed Archipelago module."))
                cfg.update(host=host, game=str(game), exe=str(game / _executable_name(host)), romfs=str(romfs),
                           ootrr=str(builder), native_tools=str(tools), manifest=str(manifest))
                cfg.setdefault("ports", {}).setdefault(host, {}).update(mods=str(mods), exe=str(game / _executable_name(host)),
                                                                       game=str(game), romfs=str(romfs), native_tools=str(tools))
                write_json(base / "outils.json", cfg)
                write_json(base / "last-profile.json", dict(root=str(profile)))
                write_json(base / "derniere-salle-native.json", data["token"])
                write_json(Path(request["app_base"]) / "desktop-host.json", dict(host=host))
                write_json(backup / "installation.json", dict(room=data["room"], token=data["token"], saves_modified=False,
                           files={str(path): str(copy) if copy else None for path, copy in copies.items()},
                           moved_previous_randomizer=str(moved_seed or "")))
            except BaseException:
                if mod_changed and old_mod.exists():
                    old_mod.rename(backup / "failed-mod")
                    if old_inode is not None:
                        previous_mod = state / "previous"
                        if previous_mod.is_dir():
                            previous_mod.rename(old_mod)
                if moved_seed and moved_seed.exists() and not (mods / "My Seed").exists():
                    moved_seed.rename(mods / "My Seed")
                _restore_files(copies)
                raise
    result = dict(base=str(base), app_base=str(request["app_base"]), host=host, profile=str(profile), game=str(game), romfs=str(romfs), tools=str(tools), mods=str(mods),
                  room=data["room"], slot=data["slot"], token=data["token"], ready=compatible,
                  build_required=not compatible, backup=str(backup), diagnostic_log=str(diagnostic),
                  setup=str(tools.parent / ("HookshotSetup.exe" if host == "hookshot" else "TriforceSetup.exe")),
                  auto_connect=automatic)
    _emit(progress, 100, tr("Ready to play.") if compatible else tr("The mod is installed. Finish building the selected game host before playing."))
    return result


def launch(result):
    """Launch the selected host normally, preserving keyboard and controller input."""
    from .app_runtime import spawn_process
    game = _folder(result["game"])
    host = _host(result.get("host"))
    romfs = Path(result.get("romfs") or game / "romfs").resolve()
    tools = Path(result["tools"]).resolve()
    mods = Path(result.get("mods") or game / "mods").resolve()
    profile = Path(result["profile"]).resolve()
    session = _json(profile / "native-session.json", {})
    executable = _adapter(host).compiled_executable(game / "romfs", tools)
    if (not isinstance(session, dict) or session.get("Token") != profile.name
            or not (game / "image.bin").is_file() or (game / "romfs").resolve() != romfs
            or executable is None
            or not (mods / "Archipelago/romfs/Archipelago/room-v1.txt").is_file()
            or (mods / "Archipelago/romfs/Archipelago/room-v1.txt").read_text().strip() != profile.name):
        raise InstallError(tr("Prepare this room before launching Zelda."))
    if _running_game(game, tools, host):
        raise InstallError(tr("Zelda or its setup application is already running."))
    environment = {key: value for key, value in os.environ.items() if not key.startswith("HOS_INPUT_")}
    environment.update(HOS_MODS=str(mods), HOS_SAVE_LOCK="1")
    if host == "hookshot":
        environment["OOTRR_AP_BASE"] = str(profile.parent)
    process = spawn_process([str(executable), str(game / "image.bin"), "--romfs", str(romfs),
                             "--user", str(profile / "user")], cwd=executable.parent, env=environment)
    if result.get("app_base"):
        try:
            write_json(Path(result["app_base"]) / "desktop-host.json", dict(host=host))
        except OSError:
            pass
    return process
