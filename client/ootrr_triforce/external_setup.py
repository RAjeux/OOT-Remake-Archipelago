"""Prepare and run the full-network mod on an external port or emulator.

Profiles and build caches are separate from native Triforce/Hookshot profiles.
The selected progress.sav is observed in place: it is never copied, edited or
moved. Only this service's managed Archipelago mod folder is exchanged, using a
journal and backups outside the emulator's active mods directory.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid

from .app_runtime import default_base
from .connection_control import normalize_server
from .full_ap import validate_manifest
from .save_bridge import atomic, exclusive
from .i18n import tr
from .full_cows import required_resources as cow_resources
from .upgrade_recovery import required_resources as recovery_resources


SESSION = "external-session.json"
MARKER = ".external-install.json"
UPDATE_REQUIRED = "Update this prepared room using the same player file. Your room identity and existing saves are preserved."
RESOURCE_FILES = tuple(sorted(set(("Pack/ZsDic.pack.zs", "Pack/AI.Global.Product.111.pack.zs", "Pack/Actor/Npc_Navi.pack.zs",
                  "Pack/Actor/Player_Base.pack.zs", "Pack/Actor/Player_Child.pack.zs", "Pack/Actor/Player_Adult.pack.zs",
                  "GameData/GameDataList.Product.110.byml.zs", "Sequence/MainUpdate.module.ainb",
                  "Sequence/AfterChangeBanc.module.ainb",
                  "System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs"))
                              | set(cow_resources()) | set(recovery_resources())))


class ExternalSetupError(ValueError):
    """A fixed translated GUI message; chained technical errors stay in logs."""
    def __init__(self, message):
        self.public_message = tr(message)
        super().__init__(self.public_message)


@dataclass(frozen=True)
class ExternalSetupRequest:
    player_file: str | Path
    source: str | Path
    mods: str | Path
    executable: str | Path
    save_path: str | Path
    server: str
    password: str = ""
    auto_connect: bool = True
    base: str | Path | None = None
    game_file: str | Path | None = None
    clear_password: bool = False


def namespace(base=None):
    return Path(base or default_base()).expanduser().resolve() / "hosts/external"


def _read(path):
    raw = Path(path).read_bytes()
    if len(raw) > 32 << 20:
        raise ExternalSetupError("The external profile file is too large.")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ExternalSetupError("Invalid external profile.")
    return value


def _json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic(path, json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))


def _unprotect_password(value):
    import base64
    import ctypes
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.c_void_p)]
    raw = base64.b64decode(value, validate=True)
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.c_void_p))
    target = Blob()
    decrypt = ctypes.WinDLL("crypt32", use_last_error=True).CryptUnprotectData
    decrypt.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    if not decrypt(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ExternalSetupError("This room's saved password could not be opened by the current account.")
    try:
        if not 0 < target.size <= 16384:
            raise ExternalSetupError("Invalid protected room password.")
        return ctypes.string_at(target.data, target.size).decode("utf-8")
    finally:
        free = ctypes.WinDLL("kernel32").LocalFree
        free.argtypes = [ctypes.c_void_p]
        free(target.data)


def _source(value):
    path = Path(value).expanduser().resolve()
    if path.is_dir() and (path / "romfs/Pack/ZsDic.pack.zs").is_file():
        path /= "romfs"
    if path.is_dir():
        if not all((path / member).is_file() for member in RESOURCE_FILES):
            raise ExternalSetupError("Choose the complete supported RomFS folder or its NUP container.")
    elif not path.is_file() or path.suffix.lower() != ".nup":
        raise ExternalSetupError("Choose the supported game's NUP file or extracted RomFS folder.")
    return path


def _running(executable):
    executable = Path(executable).resolve()
    if os.name == "nt":
        from ootrr_full.tracker.save_patch import process_images
        for image in process_images():
            try:
                if os.path.normcase(str(Path(image).resolve())) == os.path.normcase(str(executable)):
                    return True
            except OSError:
                continue
        return False
    proc = Path("/proc")
    if proc.is_dir():
        for entry in proc.iterdir():
            if entry.name.isdecimal():
                try:
                    if (entry / "exe").resolve() == executable:
                        return True
                except OSError:
                    continue
    return False


def _closed(executable):
    if _running(executable):
        raise ExternalSetupError("Close the selected game or emulator before changing its mod.")


def _no_native(directory):
    directory = Path(directory)
    if (directory / "archipelago.dll").exists() or (directory / "romfs/Archipelago/room-v1.txt").exists():
        raise ExternalSetupError("This mod uses the native connection. Use native setup to avoid two active clients.")


def inspect(request):
    """Validate selected files without connecting, launching or writing anything."""
    if not isinstance(request, ExternalSetupRequest):
        request = ExternalSetupRequest(**request)
    player_file = Path(request.player_file).expanduser().resolve()
    data = validate_manifest(_read(player_file))
    source = _source(request.source)
    executable = Path(request.executable).expanduser().resolve()
    if not executable.is_file():
        raise ExternalSetupError("Choose the port or emulator executable.")
    mods = Path(request.mods).expanduser().resolve()
    if mods.exists() and not mods.is_dir():
        raise ExternalSetupError("Choose the emulator's title-specific mods directory.")
    if mods == source or mods in source.parents or source in mods.parents:
        raise ExternalSetupError("The mods and game-resource folders must be separate.")
    target = mods / "Archipelago"
    if target.exists():
        _no_native(target)
        if not (target / MARKER).is_file():
            raise ExternalSetupError("The existing Archipelago folder is unmanaged. Preserve it before installing here.")
    if mods.is_dir():
        for child in mods.iterdir():
            if child == target or not child.is_dir():
                continue
            if ((child / "manifest.json").is_file() or (child / "full-player.json").is_file()):
                raise ExternalSetupError("Another randomizer is active in this mods folder. Disable it before installing.")
    game_file = Path(request.game_file).expanduser().resolve() if request.game_file else None
    if game_file is not None and not game_file.is_file():
        raise ExternalSetupError("The selected game file does not exist.")
    save_path = Path(request.save_path).expanduser().resolve() if request.save_path else None
    if save_path is not None and save_path.exists() and not save_path.is_file():
        raise ExternalSetupError("Choose the progress.sav file to observe.")
    normalize_server(request.server)  # validate; retain secure-first bare addresses
    return {"ready": True, "host": "external", "token": data["token"], "slot": data["slot"],
            "room": data["room"], "player": data["player"], "source": str(source),
            "mods": str(mods), "executable": str(executable), "save_path": str(save_path) if save_path else "",
            "game_file": str(game_file) if game_file else "", "player_file": str(player_file),
            "server": request.server.strip(), "auto_connect": bool(request.auto_connect),
            "check_count": len(data["checks"])}


def _fingerprint(source):
    source = Path(source)
    digest = hashlib.sha256(str(source).encode("utf-8"))
    entries = sorted(source.rglob("*")) if source.is_dir() else [source]
    for entry in entries:
        if entry.is_file():
            info = entry.stat()
            digest.update(str(entry.relative_to(source) if source.is_dir() else entry.name).encode("utf-8"))
            digest.update(f"|{info.st_size}|{info.st_mtime_ns}".encode())
    return digest.hexdigest()


def resource_cache(source, base=None):
    """Extract only original resources needed by postpasses, into private storage."""
    source = _source(source)
    if source.is_dir():
        return source
    # A new postpass can require more originals without invalidating or replacing
    # an earlier cache. Bind its immutable directory to the exact resource set.
    cache_key = hashlib.sha256((_fingerprint(source) + '\0' + '\0'.join(RESOURCE_FILES)).encode()).hexdigest()
    root = namespace(base) / "resources" / cache_key
    if all((root / member).is_file() for member in RESOURCE_FILES):
        return root
    from ootrr_full.formats.inspect_nup import Nup
    from ootrr_full.game.world_maps import effective_members
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root.parent, prefix="resources-") as temporary:
        staging = Path(temporary) / "romfs"
        nup = Nup(source)
        try:
            members = effective_members(nup)
            for member in RESOURCE_FILES:
                target = staging / member
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(nup.read(members[member]))
        finally:
            nup.stream.close()
        if root.exists():
            raise ExternalSetupError("The private resource cache is incomplete. Keep it for diagnosis and use a fresh cache.")
        staging.rename(root)
    return root


def _artifact(directory, token):
    from ootrr_full.randomizer.randomizer_services import read_artifact
    directory = Path(directory)
    _no_native(directory)
    manifest, _ = read_artifact(directory)
    if (manifest.get("archipelago") or {}).get("token") != token:
        raise ExternalSetupError("The prepared external mod belongs to another room.")
    if not (manifest.get("external_readiness") or {}).get("flag"):
        raise ExternalSetupError("The external mod has no native receipt-safety gate.")
    recovery = manifest.get("external_recovery") or {}
    if (recovery.get("version") != 1
            or recovery.get("session_flag") != 'Archipelago.ExternalSessionReady.' + token):
        raise ExternalSetupError("Prepare this room again to enable complete external item recovery.")
    if manifest.get('external_deathlink') is not None:
        from .upgrade_deathlink import validate_metadata
        try:
            validate_metadata(manifest['external_deathlink'], token)
        except ValueError as error:
            raise ExternalSetupError(str(error)) from error
    return manifest


def _plain(directory):
    from ootrr_full.parties import _plain_tree
    _plain_tree(directory)


def _remove_stage(path, parent):
    path, parent = Path(path), Path(parent).resolve()
    if path.exists():
        if path.resolve().parent != parent or not re.fullmatch("[0-9a-f]{32}", path.name):
            raise ExternalSetupError("Refusing to clean an unexpected installation stage.")
        _plain(path)
        shutil.rmtree(path)


def _recover_locked(root):
    journal = root / "install-transaction.json"
    if not journal.is_file():
        return
    operation = _read(journal)
    token, ident = operation.get("token"), operation.get("transaction")
    if (not isinstance(token, str) or not re.fullmatch("[0-9a-f]{64}", token)
            or not isinstance(ident, str) or not re.fullmatch("[0-9a-f]{32}", ident)):
        raise ExternalSetupError("The interrupted external installation journal is invalid.")
    mods = Path(operation["mods"]).resolve()
    destination = mods / "Archipelago"
    stage_parent = mods.parent / ".ootrr-ap-staging"
    backup_parent = mods.parent / ".ootrr-ap-backups"
    stage, backup = stage_parent / ident, backup_parent / ident
    _closed(operation["executable"])
    profile = root / "profiles" / token
    current = _read(profile / SESSION) if (profile / SESSION).is_file() else {}
    committed = current.get("transaction") == ident
    if not committed:
        if destination.exists() and (backup.exists() or not operation.get("had_original")):
            _no_native(destination)
            marker = _read(destination / MARKER) if (destination / MARKER).is_file() else {}
            if marker.get("transaction") != ident:
                raise ExternalSetupError("The installed mod changed after interruption. Its backup was preserved.")
            failed = backup_parent / (ident + "-failed")
            if failed.exists():
                raise ExternalSetupError("An interrupted installation backup already exists.")
            _plain(destination)
            destination.rename(failed)
        if backup.exists():
            if backup.resolve().parent != backup_parent.resolve():
                raise ExternalSetupError("Invalid external mod backup location.")
            _plain(backup)
            backup.rename(destination)
    _remove_stage(stage, stage_parent)
    journal.unlink()


def recover(base=None):
    root = namespace(base)
    if not root.exists():
        return
    with exclusive(root / "setup.lock"):
        _recover_locked(root)


def configure(request, progress=None):
    """Build, verify and install only a managed external mod, with rollback."""
    if not isinstance(request, ExternalSetupRequest):
        request = ExternalSetupRequest(**request)
    state = inspect(request)
    data = validate_manifest(_read(state["player_file"]))
    root = namespace(request.base)
    root.mkdir(parents=True, exist_ok=True)
    progress = progress or (lambda *_: None)
    with exclusive(root / "setup.lock"):
        _recover_locked(root)
        _closed(state["executable"])
        profile = root / "profiles" / data["token"]
        _plain(profile)
        profile.mkdir(parents=True, exist_ok=True)
        previous = _read(profile / SESSION) if (profile / SESSION).is_file() else {}
        if previous and any(previous.get(name) != data[name] for name in ("token", "slot", "room", "player")):
            raise ExternalSetupError("The existing external profile belongs to another room or player.")
        from .full_mod import build, code_fingerprint
        source_key = _fingerprint(state["source"])
        cache_key = hashlib.sha256((data["token"] + source_key + code_fingerprint()).encode()).hexdigest()[:24]
        cache = profile / "builds" / cache_key
        artifact = cache / "mods/Archipelago"
        progress(5, tr("Checking the external game and room..."))
        if not artifact.exists():
            cache.parent.mkdir(parents=True, exist_ok=True)
            resources = resource_cache(state["source"], request.base)
            with tempfile.TemporaryDirectory(dir=cache.parent, prefix="build-") as temporary:
                staging = Path(temporary) / "completed"
                staging.mkdir()
                progress(15, tr("Preparing every Archipelago reward..."))
                build(staging, {"romfs": str(resources), "game_source": state["source"],
                                "native": False, "baseline": 0, "generation_process": True,
                                "_progress": progress}, data)
                _artifact(staging / "mods/Archipelago", data["token"])
                staging.rename(cache)
        _artifact(artifact, data["token"])
        mods = Path(state["mods"])
        mods.mkdir(parents=True, exist_ok=True)
        destination = mods / "Archipelago"
        ident = uuid.uuid4().hex
        stage_parent, backup_parent = mods.parent / ".ootrr-ap-staging", mods.parent / ".ootrr-ap-backups"
        for parent in (stage_parent, backup_parent):
            _plain(parent)
            parent.mkdir(parents=True, exist_ok=True)
        stage, backup = stage_parent / ident, backup_parent / ident
        # Persist intent before copying: an interrupted copy remains inactive.
        operation = {"version": 1, "transaction": ident, "token": data["token"],
                     "mods": str(mods), "executable": state["executable"],
                     "had_original": destination.exists()}
        _json(root / "install-transaction.json", operation)
        try:
            progress(85, tr("Installing the verified mod..."))
            shutil.copytree(artifact, stage)
            _artifact(stage, data["token"])
            _json(stage / MARKER, {"version": 1, "token": data["token"], "transaction": ident})
            _closed(state["executable"])
            if destination.exists():
                _no_native(destination)
                if not (destination / MARKER).is_file():
                    raise ExternalSetupError("The target mod changed while preparation was running.")
                _plain(destination)
                destination.rename(backup)
            stage.rename(destination)
            secret = ""
            has_password = bool(request.password)
            if request.password and os.name == "nt":
                from .native_setup import protect_password
                secret = protect_password(request.password)
            elif not request.clear_password and previous.get("has_password"):
                secret = previous.get("protected_password", "")
                has_password = True
            session = dict(state, version=1, backend="external", generation_mode="full_network",
                           transaction=ident, profile=str(profile), installed_mod=str(destination),
                           artifact=str(artifact), has_password=has_password,
                           protected_password=secret, backup=str(backup) if backup.exists() else "")
            _json(profile / "player.apootrr", data)
            _json(profile / SESSION, session)  # transaction commit point
            _recover_locked(root)
        except BaseException:
            _recover_locked(root)
            raise
        _json(root / "last-profile.json", {"version": 1, "profile": str(profile)})
        progress(100, tr("The external Archipelago mod is ready."))
    return open_profile(profile)


def _session(profile):
    profile = Path(profile).expanduser().resolve()
    if profile.name == SESSION:
        profile = profile.parent
    data = _read(profile / SESSION)
    if (data.get("version") != 1 or data.get("backend") != "external"
            or data.get("generation_mode") != "full_network" or profile.name != data.get("token")):
        raise ExternalSetupError("This is not an external full-network room profile.")
    return profile, data


def open_profile(profile):
    """Safe GUI data: passwords and DPAPI ciphertext are never returned."""
    profile, data = _session(profile)
    from .room_updates import requires_reprepare
    reprepare_required = requires_reprepare(data['installed_mod'], external=True)
    ready = False
    manifest = {}
    try:
        manifest = _artifact(data["installed_mod"], data["token"])
        ready = not reprepare_required
    except (OSError, ValueError, KeyError):
        pass
    safe = {key: value for key, value in data.items() if key not in {"protected_password", "password"}}
    safe.update(profile=str(profile), mod=data["installed_mod"], prepared_source=data["artifact"],
                tracker_source=data["installed_mod"], host="external", ready=ready,
                reprepare_required=reprepare_required,
                deathlink_supported=bool((manifest.get('external_deathlink') or {}).get('enabled')))
    return safe


def list_profiles(base=None):
    folder = namespace(base) / "profiles"
    result = []
    if folder.is_dir():
        for child in sorted(folder.iterdir()):
            if (child / SESSION).is_file():
                try:
                    result.append(open_profile(child))
                except (OSError, ValueError, KeyError):
                    continue
    return result


def update_preferences(profile, *, save_path=None, server=None, password=None,
                       clear_password=False, auto_connect=None):
    """Update only connection/tracker preferences, even while the game runs."""
    profile, current = _session(profile)
    with exclusive(profile / "preferences.lock"):
        _, current = _session(profile)
        if save_path is not None:
            path = Path(save_path).expanduser().resolve() if save_path else None
            if path is not None and path.exists() and not path.is_file():
                raise ExternalSetupError("Choose the progress.sav file to observe.")
            current["save_path"] = str(path) if path else ""
        if server is not None:
            normalize_server(server)
            current["server"] = server.strip()
        if password is not None and password:
            current["has_password"] = True
            if os.name == "nt":
                from .native_setup import protect_password
                current["protected_password"] = protect_password(password)
            else:
                current["protected_password"] = ""
        elif clear_password:
            current.update(has_password=False, protected_password="")
        if auto_connect is not None:
            if type(auto_connect) is not bool:
                raise ExternalSetupError("Automatic connection must be enabled or disabled.")
            current["auto_connect"] = auto_connect
        _json(profile / SESSION, current)
    return open_profile(profile)


def connect(profile, *, password=None, on_change=None):
    """Return an idle runtime; the UI starts and owns its lifetime."""
    profile, data = _session(profile)
    external_root = profile.parent.parent
    if (profile.parent.name != "profiles" or external_root.name != "external"
            or external_root.parent.name != "hosts"):
        raise ExternalSetupError("Invalid external profile namespace.")
    base = external_root.parent.parent
    from .connection_control import Controller
    for native in (base / data["token"], base / "hosts/hookshot" / data["token"]):
        if (native / "native-session.json").is_file() and Controller(native).info().get("running"):
            raise ExternalSetupError("Close the native client for this room before starting its external connection.")
    opened = open_profile(profile)
    if opened.get('reprepare_required'):
        raise ExternalSetupError(UPDATE_REQUIRED)
    if not opened["ready"]:
        raise ExternalSetupError("Prepare this external room again before connecting.")
    if password is None:
        password = ""
        if data.get("has_password"):
            if os.name == "nt" and data.get("protected_password"):
                password = _unprotect_password(data["protected_password"])
            else:
                raise ExternalSetupError("Enter this room's password to connect; it is not stored on this platform.")
    from .upgrade_runtime import ExternalRuntime
    return ExternalRuntime(data["installed_mod"], data["server"], save_path=data["save_path"],
                           password=password, slot=data["slot"], local_data=profile / "tracker",
                           on_change=on_change, executable=data["executable"])


def launch(profile):
    """Open the selected executable normally, without input or save overrides."""
    _, data = _session(profile)
    opened = open_profile(profile)
    if opened.get('reprepare_required'):
        raise ExternalSetupError(UPDATE_REQUIRED)
    if not opened["ready"]:
        raise ExternalSetupError("Prepare this external room again before launching.")
    command = [data["executable"]]
    if data.get("game_file"):
        command.append(data["game_file"])
    environment = {key: value for key, value in os.environ.items() if not key.startswith("HOS_INPUT_")}
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    return subprocess.Popen(command, cwd=Path(data["executable"]).parent, env=environment, **options)
