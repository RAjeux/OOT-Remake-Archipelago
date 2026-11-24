"""Named prepared rooms and safe activation of their existing isolated profiles.

The library contains display metadata and launch paths, never passwords. It
does not move saves between rooms or hosts. Selecting a previously prepared
mod reuses its verified room marker and the normal transactional installer.
"""
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import uuid

from .connection_control import default_base
from .save_bridge import atomic, exclusive


INDEX = "room-library.json"
TOKEN = re.compile(r"[0-9a-f]{64}\Z")
PATH_KEYS = ("game", "romfs", "tools", "mods", "manifest", "prepared_source", "tracker_source")


class LibraryError(ValueError):
    pass


def _read(path, limit=16 << 20):
    try:
        if path.stat().st_size > limit:
            return {}
        value = json.loads(path.read_bytes())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, RecursionError):
        return {}


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _linked(path):
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _plain(path, *, tree=False):
    path = Path(path).absolute()
    if any(_linked(parent) for parent in (path, *path.parents)):
        raise LibraryError("Linked folders cannot be used for room management.")
    if tree and any(_linked(child) for child in path.rglob("*")):
        raise LibraryError("Linked folders cannot be used for room management.")
    return path.resolve()


class RoomLibrary:
    def __init__(self, base=None):
        self.base = Path(base or default_base()).expanduser().resolve()

    def host_base(self, host):
        if host == "nx2navi":
            return self.base
        if host == "external":
            return self.base / "hosts/external/profiles"
        if not isinstance(host, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", host):
            raise LibraryError("Unknown game host.")
        return self.base / "hosts" / host

    def _profile(self, host, token):
        if not isinstance(token, str) or not TOKEN.fullmatch(token):
            raise LibraryError("The room identity is invalid.")
        return _plain(self.host_base(host) / token)

    def _index(self):
        value = _read(self.base / INDEX, 4 << 20)
        return value.get("rooms", {}) if value.get("version") == 1 and isinstance(value.get("rooms"), dict) else {}

    def _save_index(self, rooms):
        _write(self.base / INDEX, {"version": 1, "rooms": rooms})

    def _session(self, profile):
        value = _read(profile / "native-session.json")
        if not value and (profile / "external-session.json").is_file():
            source = _read(profile / "external-session.json")
            if source.get("backend") != "external" or source.get("version") != 1:
                raise LibraryError("This room's profile is invalid.")
            value = {"Token": source.get("token"), "Room": source.get("room"), "Slot": source.get("slot"),
                     "Player": source.get("player"), "Server": source.get("server", ""), "AutoConnect": source.get("auto_connect", True)}
        if (value.get("Token") != profile.name or not TOKEN.fullmatch(profile.name)
                or not all(isinstance(value.get(key), str) and value[key] for key in ("Room", "Slot"))
                or type(value.get("Player")) is not int or value["Player"] < 1):
            raise LibraryError("This room's profile is invalid.")
        return value

    def rooms(self):
        """Return safe metadata, including older profiles not registered yet."""
        recorded = self._index()
        namespaces = [("nx2navi", self.base)]
        hosts = self.base / "hosts"
        if hosts.is_dir() and not _linked(hosts):
            namespaces.extend((folder.name, folder) for folder in hosts.iterdir()
                              if folder.is_dir() and not _linked(folder) and re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", folder.name))
        result = []
        for host, namespace in namespaces:
            if not namespace.is_dir() or _linked(namespace):
                continue
            for source in namespace.glob("*/native-session.json"):
                if not TOKEN.fullmatch(source.parent.name):
                    continue
                try:
                    profile = self._profile(host, source.parent.name)
                    session = self._session(profile)
                except (LibraryError, OSError):
                    continue
                key = host + ":" + profile.name
                stored = recorded.get(key, {})
                if not isinstance(stored, dict):
                    stored = {}
                record = {"key": key, "host": host, "token": profile.name,
                          "profile": str(profile), "base": str(namespace), "app_base": str(self.base),
                          "room": session["Room"], "slot": session["Slot"], "player": session["Player"],
                          "name": stored.get("name") if isinstance(stored.get("name"), str) and stored["name"] else session["Slot"] + " · " + session["Room"],
                          "last_played": stored.get("last_played", "") if isinstance(stored.get("last_played", ""), str) else "",
                          "server": session.get("Server", ""), "auto_connect": session.get("AutoConnect", True)}
                record.update({name: stored[name] for name in PATH_KEYS if isinstance(stored.get(name), str)})
                result.append(record)
        external = self.host_base("external")
        if external.is_dir() and not _linked(external):
            for source in external.glob("*/external-session.json"):
                if not TOKEN.fullmatch(source.parent.name):
                    continue
                try:
                    profile = self._profile("external", source.parent.name)
                    session = self._session(profile)
                except (LibraryError, OSError):
                    continue
                key = "external:" + profile.name
                stored = recorded.get(key, {})
                stored = stored if isinstance(stored, dict) else {}
                result.append({"key": key, "host": "external", "token": profile.name, "profile": str(profile),
                               "base": str(external.parent), "app_base": str(self.base), "room": session["Room"],
                               "slot": session["Slot"], "player": session["Player"], "server": session["Server"],
                               "name": stored.get("name") if isinstance(stored.get("name"), str) and stored["name"] else session["Slot"] + " · " + session["Room"],
                               "last_played": stored.get("last_played", "") if isinstance(stored.get("last_played", ""), str) else "",
                               "external": True, "auto_connect": session["AutoConnect"]})
        return sorted(result, key=lambda row: (row["last_played"], row["name"].casefold()), reverse=True)

    def register(self, result, manifest=None):
        host = result.get("host") or "nx2navi"
        profile = self._profile(host, result.get("token"))
        if Path(result.get("profile", "")).resolve() != profile:
            raise LibraryError("The selected profile belongs to another host or room.")
        session = self._session(profile)
        if result.get("room") != session["Room"] or result.get("slot") != session["Slot"]:
            raise LibraryError("The selected profile belongs to another host or room.")
        key = host + ":" + profile.name
        self.base.mkdir(parents=True, exist_ok=True)
        with exclusive(self.base / "room-library.lock"):
            rooms = self._index()
            previous = rooms.get(key, {})
            previous = previous if isinstance(previous, dict) else {}
            entry = {"name": previous.get("name", session["Slot"] + " · " + session["Room"]),
                     "last_played": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            entry.update({name: str(result[name]) for name in PATH_KEYS if result.get(name)})
            persistent = profile / "player.apootrr"
            if persistent.is_file():
                entry["manifest"] = str(persistent)
            elif manifest:
                entry["manifest"] = str(Path(manifest).expanduser().resolve())
            rooms[key] = entry
            self._save_index(rooms)
        return next(row for row in self.rooms() if row["key"] == key)

    def rename(self, key, name):
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80 or any(ord(c) < 32 for c in name):
            raise LibraryError("Choose a room name of 1 to 80 characters.")
        if not any(room["key"] == key for room in self.rooms()):
            raise LibraryError("This room is no longer available.")
        with exclusive(self.base / "room-library.lock"):
            rooms = self._index()
            rooms.setdefault(key, {})["name"] = name.strip()
            self._save_index(rooms)

    def _record(self, key):
        record = next((room for room in self.rooms() if room["key"] == key), None)
        if record is None:
            raise LibraryError("This room is no longer available.")
        return record

    def select(self, key):
        """Select a room; activate its cached mod when available and idle.

        Older profiles without launch/cache metadata are returned as needing
        preparation. The GUI opens their setup form instead of guessing paths.
        """
        record = self._record(key)
        record.update(ready=False, build_required=True)
        if record["host"] == "external":
            return record
        if not all(record.get(name) for name in ("game", "romfs", "tools", "mods")):
            return record
        profile = self._profile(record["host"], record["token"])
        mods = Path(record["mods"]).expanduser().resolve()
        marker = mods / "Archipelago/romfs/Archipelago/room-v1.txt"
        matches = False
        try:
            matches = marker.read_text(encoding="utf-8").strip() == profile.name
        except OSError:
            pass
        source = Path(record.get("prepared_source") or "")
        from .room_updates import requires_reprepare
        artifact = mods / 'Archipelago' if matches else source / 'Archipelago'
        if requires_reprepare(artifact):
            record['reprepare_required'] = True
            return record
        if not matches and not record.get("prepared_source"):
            return record
        if not matches:
            source = _plain(source, tree=True)
            if not source.is_relative_to(self.host_base(record["host"])):
                raise LibraryError("This room's prepared files are outside its application data folder.")
            try:
                correct = (source / "Archipelago/romfs/Archipelago/room-v1.txt").read_text(encoding="utf-8").strip() == profile.name
            except OSError:
                correct = False
            if not correct:
                return record
        from . import install_service, install_mod
        from .connection_control import remember_profile
        game, tools = Path(record["game"]), Path(record["tools"])
        if install_service._running_game(game, tools, record["host"]):
            raise LibraryError("Close Zelda and its setup application before changing rooms.")
        base = self.host_base(record["host"])
        install_mod.validate_root(mods, Path(record["romfs"]), base)
        state = install_mod.state_dir(mods)
        state.mkdir(exist_ok=True)
        selected = base / "last-profile.json"
        previous = _read(selected).get("root")
        mutable = [selected, base / "derniere-salle-native.json", self.base / "desktop-host.json", base / "outils.json"]
        changed = False
        with ExitStack() as stack:
            try:
                for path in (base / "setup.lock", profile / "client.lock", state / "session.lock"):
                    stack.enter_context(exclusive(path))
                if previous and Path(previous).resolve() != profile and Path(previous).parent.resolve() == base:
                    stack.enter_context(exclusive(Path(previous) / "client.lock"))
                if (profile / "user").is_dir():
                    stack.enter_context(exclusive(profile / "user/save.lock"))
            except BlockingIOError:
                raise LibraryError("Close Zelda and its setup application before changing rooms.") from None
            before = {path: path.read_bytes() if path.is_file() else None for path in mutable}
            try:
                if not matches:
                    install_mod.install(source, mods, profile.name)
                    changed = True
                config = _read(base / "outils.json")
                config.update(host=record["host"], **{name: record[name] for name in ("game", "romfs", "manifest") if record.get(name)})
                config["native_tools"] = record["tools"]
                config.setdefault("ports", {}).setdefault(record["host"], {}).update(
                    game=record["game"], romfs=record["romfs"], mods=record["mods"], native_tools=record["tools"])
                _write(base / "outils.json", config)
                remember_profile(profile, base)
                _write(base / "derniere-salle-native.json", profile.name)
                _write(self.base / "desktop-host.json", {"host": record["host"]})
            except BaseException:
                if changed and (state / "previous").is_dir():
                    failed = state / ("failed-library-" + uuid.uuid4().hex[:12])
                    (mods / "Archipelago").rename(failed)
                    (state / "previous").rename(mods / "Archipelago")
                for path, raw in before.items():
                    if raw is None:
                        path.unlink(missing_ok=True)
                    else:
                        atomic(path, raw)
                raise
        record["ready"] = install_service._compiled_game(record["host"], Path(record["romfs"]), tools)
        record["build_required"] = not record["ready"]
        self.register(record, record.get("manifest"))
        return record

    def snapshot(self, key):
        """Copy this room's complete user directory while the room is closed."""
        record = self._record(key)
        profile = self._profile(record["host"], record["token"])
        if record["host"] == "external":
            return self._external_snapshot(record, profile)
        user = _plain(profile / "user", tree=True)
        if not user.is_dir():
            raise LibraryError("This room has no save to back up yet.")
        destination = self.base / "room-backups" / record["host"] / profile.name
        destination.mkdir(parents=True, exist_ok=True)
        backup = destination / (datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
        with ExitStack() as stack:
            try:
                stack.enter_context(exclusive(profile / "client.lock"))
                stack.enter_context(exclusive(user / "save.lock"))
            except BlockingIOError:
                raise LibraryError("Close Zelda before backing up this room.") from None
            with tempfile.TemporaryDirectory(dir=destination, prefix="snapshot-") as temporary:
                stage = Path(temporary) / "room"
                shutil.copytree(user, stage / "user", ignore=shutil.ignore_patterns("*.lock"))
                for path in user.rglob("*"):
                    if path.is_file() and not path.name.endswith(".lock"):
                        copied = stage / "user" / path.relative_to(user)
                        if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(copied.read_bytes()).digest():
                            raise LibraryError("The save backup could not be verified.")
                for name in ("native-checks.json", "full-runtime-state.json"):
                    if (profile / name).is_file():
                        shutil.copyfile(profile / name, stage / name)
                _write(stage / "room.json", {name: record[name] for name in ("name", "host", "token", "room", "slot", "player")})
                stage.rename(backup)
        return backup

    def _external_snapshot(self, record, profile):
        from .external_setup import _closed
        with exclusive(profile / "preferences.lock"):
            session = _read(profile / "external-session.json")
            if not session.get("save_path"):
                raise LibraryError("This room has no save to back up yet.")
            _closed(session["executable"])
            save = _plain(session["save_path"])
            if not save.is_file() or save.stat().st_size > 16 << 20:
                raise LibraryError("This room has no save to back up yet.")
            destination = self.base / "room-backups/external" / profile.name
            destination.mkdir(parents=True, exist_ok=True)
            backup = destination / (datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
            with tempfile.TemporaryDirectory(dir=destination, prefix="snapshot-") as temporary:
                stage = Path(temporary) / "room"
                stage.mkdir()
                before = save.stat()
                shutil.copyfile(save, stage / "progress.sav")
                after = save.stat()
                if ((before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
                        or hashlib.sha256(save.read_bytes()).digest() != hashlib.sha256((stage / "progress.sav").read_bytes()).digest()):
                    raise LibraryError("The save backup could not be verified.")
                _write(stage / "room.json", {name: record[name] for name in ("name", "host", "token", "room", "slot", "player")})
                stage.rename(backup)
            return backup


def room_progress(profile):
    """A passive AP checklist; it never sends manually ticked locations."""
    root = Path(profile)
    session, journal = _read(root / "native-session.json"), _read(root / "native-checks.json")
    checks = session.get("Checks", {})
    if not isinstance(checks, dict):
        checks = {}
    checked = journal.get("locations", journal.get("Locations", []))
    checked = set(checked) if isinstance(checked, list) and all(type(v) is int for v in checked) else set()
    rows = []
    for location, value in checks.items():
        if not isinstance(value, dict):
            continue
        try:
            code = int(location)
        except (ValueError, TypeError):
            continue
        rows.append({"id": code, "name": value.get("Name", str(code)), "checked": code in checked})
    return {"room": session.get("Room", ""), "slot": session.get("Slot", ""),
            "won": bool(journal.get("won", journal.get("Won", False))),
            "checked": sum(row["checked"] for row in rows), "total": len(rows), "locations": rows}
