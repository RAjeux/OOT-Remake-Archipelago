"""Safe settings and loopback control for a game-owned native AP connection.

This module never loads the native DLL or opens an Archipelago WebSocket.
``Controller.info()`` returns a safe dictionary; ``apply()``, ``save()`` and
``disconnect()`` return the same dictionary with an integer ``result``. A
positive result means the command succeeded. Offline apply only saves settings
for the next game start and reports ``waiting_for_game``.

Profiles expose display metadata only. Their room, slot and player are immutable.
Passwords are accepted only as command arguments and never returned or logged.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import base64
import ctypes
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import unicodedata
from urllib.parse import unquote, urlsplit

from .catalog import PROTOCOL
from .i18n import profile_language
from .native_setup import protect_password
from .save_bridge import atomic, exclusive


SESSION_LIMIT = 16 << 20
CONTROL_LIMIT = 16 << 10
RPC_TIMEOUT = 0.8
MARKER = "last-profile.json"
_STATES = {"disconnected", "connecting", "authenticating", "synchronizing", "connected", "retrying"}
_NATIVE_ERRORS = {"", "invalid_server", "invalid_password", "credential_error",
                  "settings_error", "wrong_room", "wrong_slot", "unknown_item",
                  "connection_refused", "connection_failed", "connection_lost"}


class ControlError(Exception):
    """A fixed, safe error code; underlying exception text is deliberately omitted."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Profile:
    root: Path
    room: str
    slot: str
    player: int
    server: str
    language: str
    has_password: bool
    auto_connect: bool


def default_base():
    return Path(os.getenv("LOCALAPPDATA") or (Path.home() / ".local/share")) / "OOTRR-Archipelago"


def _profile_root(value):
    path = Path(value).expanduser().resolve()
    return path.parent if path.name == "native-session.json" else path


def _read_json(path, limit, error):
    try:
        with Path(path).open("rb") as source:
            raw = source.read(limit + 1)
        if len(raw) > limit:
            raise ValueError()
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (OSError, ValueError, UnicodeError, RecursionError):
        raise ControlError(error) from None


def normalize_server(value):
    """Validate addresses with the native connection.go endpoint rules."""
    if not isinstance(value, str) or any(unicodedata.category(c) == "Cc" for c in value):
        raise ControlError("invalid_server")
    endpoint = value.strip()
    try:
        size = len(endpoint.encode("utf-8"))
        if not endpoint or size > 2048 or any(c.isspace() for c in endpoint):
            raise ValueError()
        if "://" not in endpoint:
            endpoint = "ws://" + endpoint
        if endpoint.split("://", 1)[0] not in ("ws", "wss"):
            raise ValueError()
        parsed = urlsplit(endpoint)
        host = parsed.netloc
        if (not parsed.hostname or "@" in host or "?" in endpoint
                or parsed.fragment or unquote(parsed.path, errors="strict") not in ("", "/")
                or host.endswith(":") or (host.count(":") > 1 and not host.startswith("["))
                or "\\" in host or re.search(r"%(?![0-9a-fA-F]{2})", endpoint)):
            raise ValueError()
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError()
        # Public hosted rooms require TLS, including legacy saved ws:// URLs.
        # Local addresses and other explicitly selected transports stay intact.
        hostname = parsed.hostname.lower().removesuffix(".")
        if hostname == "archipelago.gg" or hostname.endswith(".archipelago.gg"):
            endpoint = "wss://" + endpoint.split("://", 1)[1]
        # Go URL.String discards an empty fragment marker.
        return endpoint[:-1] if endpoint.endswith("#") else endpoint
    except (ValueError, UnicodeError):
        raise ControlError("invalid_server") from None


def _validate_command(server, password, mode, automatic):
    endpoint = normalize_server(server)
    if (type(mode) is not int or mode not in (0, 1, 2) or type(automatic) is not bool
            or not isinstance(password, str)):
        raise ControlError("invalid_password")
    try:
        if len(password.encode("utf-8")) > 4096 or "\0" in password:
            raise ValueError()
    except (ValueError, UnicodeError):
        raise ControlError("invalid_password") from None
    return endpoint


def _unprotect_secret(protected):
    """Decrypt only the local RPC bearer, never the saved AP password."""
    try:
        from ctypes import wintypes as w
        class Blob(ctypes.Structure):
            _fields_ = [("size", w.DWORD), ("data", ctypes.c_void_p)]
        raw = base64.b64decode(protected, validate=True)
        if not raw:
            raise ValueError()
        buf = ctypes.create_string_buffer(raw)
        source = Blob(len(raw), ctypes.cast(buf, ctypes.c_void_p))
        dest = Blob()
        decrypt = ctypes.WinDLL("crypt32", use_last_error=True).CryptUnprotectData
        decrypt.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                            ctypes.c_void_p, ctypes.c_void_p, w.DWORD, ctypes.POINTER(Blob)]
        if not decrypt(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(dest)):
            raise ValueError()
        try:
            if not 0 < dest.size <= CONTROL_LIMIT:
                raise ValueError()
            return ctypes.string_at(dest.data, dest.size).decode("ascii")
        finally:
            free = ctypes.WinDLL("kernel32").LocalFree
            free.argtypes = [ctypes.c_void_p]
            free(dest.data)
    except (OSError, AttributeError, ValueError, UnicodeError, TypeError):
        raise ControlError("rpc_unauthorized") from None


def _descriptor(root, token):
    path = root / "connection-control.json"
    if not path.is_file():
        raise ControlError("native_update_required")
    data = _read_json(path, CONTROL_LIMIT, "rpc_unavailable")
    if (type(data.get("version")) is not int or data["version"] != 1
            or type(data.get("port")) is not int or not 1 <= data["port"] <= 65535
            or type(data.get("pid")) is not int or data["pid"] < 1
            or not isinstance(data.get("token"), str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", data["token"])
            or not secrets.compare_digest(data["token"], token)):
        raise ControlError("rpc_unauthorized")
    if os.name == "nt":
        protected = data.get("protected_secret")
        if not isinstance(protected, str):
            raise ControlError("rpc_unauthorized")
        secret = _unprotect_secret(protected)
    else:
        secret = data.get("secret")
    if not isinstance(secret, str) or not re.fullmatch(r"[0-9a-f]{64}", secret):
        raise ControlError("rpc_unauthorized")
    return data["port"], secret


def _request(descriptor, method, path, body=None):
    port, secret = descriptor
    # HTTPConnection connects directly; urllib/environment proxy settings are never consulted.
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=RPC_TIMEOUT)
    try:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        if payload is not None and len(payload) > CONTROL_LIMIT:
            raise ControlError("invalid_password")
        connection.request(method, path, payload, {"Authorization": "Bearer " + secret,
                                                   "Content-Type": "application/json"})
        response = connection.getresponse()
        raw = response.read(CONTROL_LIMIT + 1)
        if response.status in (401, 403):
            raise ControlError("rpc_unauthorized")
        if response.status == 404 and path == "/v1/chat":
            raise ControlError("native_update_required")
        if response.status != 200 or len(raw) > CONTROL_LIMIT:
            raise ControlError("rpc_invalid_response")
        value = json.loads(raw)
        if (not isinstance(value, dict) or type(value.get("result")) is not int
                or not isinstance(value.get("info"), dict)):
            raise ControlError("rpc_invalid_response")
        return value
    except (OSError, http.client.HTTPException, TimeoutError):
        raise ControlError("rpc_unavailable") from None
    except (ValueError, UnicodeError, RecursionError):
        raise ControlError("rpc_invalid_response") from None
    finally:
        connection.close()


class Controller:
    """Control one prepared profile, using its native owner while the game runs."""

    def __init__(self, root):
        self.root = _profile_root(root)
        self._binding = None
        self._last = self._empty()

    def _empty(self):
        return dict(server="", slot="", room="", player=0, state="waiting_for_game",
                    error_code="", has_password=False, auto_connect=True, language="en",
                    running=False, live=False, profile=str(self.root))

    def _session(self):
        data = _read_json(self.root / "native-session.json", SESSION_LIMIT, "no_profile")
        if (not all(isinstance(data.get(key), str) and data[key] for key in ("Token", "Room", "Slot"))
                or not re.fullmatch(r"[0-9a-fA-F]{64}", data["Token"])
                or type(data.get("Player")) is not int or data["Player"] < 1
                or type(data.get("Protocol")) is not int or data["Protocol"] != PROTOCOL
                or type(data.get("CursorHash")) is not int or not 0 < data["CursorHash"] <= 0xFFFFFFFF):
            raise ControlError("no_profile")
        try:
            if any(len(data[key].encode("utf-8")) > 4096 for key in ("Room", "Slot")):
                raise ValueError()
        except (ValueError, UnicodeError):
            raise ControlError("no_profile") from None
        binding = tuple(data.get(key) for key in ("Token", "Room", "Slot", "Player", "Protocol", "CursorHash"))
        if self._binding is not None and binding != self._binding:
            raise ControlError("profile_changed")
        self._binding = binding
        return data

    def _offline_info(self, data):
        info = self._empty()
        try:
            info["server"] = normalize_server(data.get("Server", ""))
        except ControlError:
            info["error_code"] = "invalid_server"
        info.update(slot=data["Slot"], room=data["Room"], player=data["Player"],
                    has_password=bool(data.get("ProtectedPassword")),
                    auto_connect=data.get("AutoConnect") is not False,
                    language=profile_language(self.root) or ("fr" if data.get("Language") == "fr" else "en"))
        self._last = info
        return info

    def _live_info(self, reply, data):
        raw = reply["info"]
        if raw.get("room") != data["Room"] or raw.get("slot") != data["Slot"]:
            raise ControlError("profile_changed")
        if (raw.get("state") not in _STATES or raw.get("error_code") not in _NATIVE_ERRORS
                or type(raw.get("has_password")) is not bool
                or type(raw.get("auto_connect")) is not bool):
            raise ControlError("rpc_invalid_response")
        try:
            server = normalize_server(raw.get("server"))
        except ControlError:
            raise ControlError("rpc_invalid_response") from None
        info = dict(self._last, server=server, slot=data["Slot"], room=data["Room"], player=data["Player"],
                    state=raw["state"], error_code=raw["error_code"],
                    has_password=raw["has_password"], auto_connect=raw["auto_connect"],
                    language="fr" if raw.get("language") == "fr" else "en", running=True, live=True)
        self._last = info
        return info

    def _failure(self, code, running=None):
        info = dict(self._last, error_code=code, result=-1)
        if running is not None:
            info["running"] = running
            if not running:
                info["live"] = False
        return info

    @contextmanager
    def _owner(self):
        """Hold the existing game/setup exclusion for the complete offline operation."""
        try:
            lock = exclusive(self.root / "client.lock")
            lock.__enter__()
        except BlockingIOError:
            yield False
            return
        except OSError:
            raise ControlError("no_profile") from None
        try:
            yield True
        finally:
            lock.__exit__(None, None, None)

    def _live(self, data):
        descriptor = _descriptor(self.root, data["Token"])
        self._live_info(_request(descriptor, "GET", "/v1/status"), data)
        return descriptor

    def info(self):
        running = False
        try:
            with self._owner() as offline:
                running = not offline
                # Live native settings commits are atomic. Only their display metadata is used.
                data = self._session()
                self._offline_info(data)
                if offline:
                    return dict(self._last)
                self._live(data)
                return dict(self._last)
        except ControlError as error:
            return self._failure(error.code, running)

    def _edit(self, server, password, mode, automatic, connect):
        running = None
        try:
            endpoint = _validate_command(server, password, mode, automatic)
            with self._owner() as offline:
                running = not offline
                data = self._session()
                self._offline_info(data)
                if not offline:
                    descriptor = self._live(data)
                    if not connect:
                        raise ControlError("unsupported_live_save")
                    reply = _request(descriptor, "POST", "/v1/connect", dict(
                        server=endpoint, password=password if mode == 1 else "",
                        password_mode=mode, auto_connect=automatic))
                    return dict(self._live_info(reply, data), result=reply["result"])
                protected = data.get("ProtectedPassword", "")
                if mode == 1:
                    try:
                        protected = protect_password(password)
                    except Exception:
                        raise ControlError("credential_error") from None
                elif mode == 2:
                    protected = ""
                data.update(Server=endpoint, ProtectedPassword=protected, AutoConnect=automatic)
                try:
                    atomic(self.root / "native-session.json", (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
                except (OSError, ValueError, UnicodeError):
                    raise ControlError("settings_error") from None
                return dict(self._offline_info(data), result=1)
        except ControlError as error:
            return self._failure(error.code, running)

    def apply(self, server, password="", mode=0, automatic=True):
        return self._edit(server, password, mode, automatic, True)

    def save(self, server, password="", mode=0, automatic=True):
        return self._edit(server, password, mode, automatic, False)

    def disconnect(self):
        running = False
        try:
            with self._owner() as offline:
                running = not offline
                data = self._session()
                self._offline_info(data)
                if offline:
                    return dict(self._last, result=1)
                descriptor = self._live(data)
                reply = _request(descriptor, "POST", "/v1/disconnect", {})
                return dict(self._live_info(reply, data), result=reply["result"])
        except ControlError as error:
            return self._failure(error.code, running)

    def chat(self):
        """Read recent server messages from the game-owned connection only."""
        return self._chat()

    def say(self, text):
        """Send an explicitly submitted message; never queue it while offline."""
        try:
            valid = (isinstance(text, str) and bool(text.strip()) and len(text.encode("utf-8")) <= 512
                     and not any(unicodedata.category(character) == "Cc" for character in text))
        except UnicodeError:
            valid = False
        if not valid:
            return self._failure("invalid_chat_message")
        return self._chat(text)

    def _chat(self, text=None):
        running = False
        try:
            with self._owner() as offline:
                running = not offline
                data = self._session()
                self._offline_info(data)
                if offline:
                    raise ControlError("chat_disconnected")
                descriptor = self._live(data)
                reply = (_request(descriptor, "GET", "/v1/chat") if text is None else
                         _request(descriptor, "POST", "/v1/chat", {"text": text}))
                info = self._live_info(reply, data)
                rows = reply.get("messages")
                if (not isinstance(rows, list) or len(rows) > 20
                        or any(not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] < 1
                               or not isinstance(row.get("text"), str) or len(row["text"].encode("utf-8")) > 512
                               for row in rows)):
                    raise ControlError("rpc_invalid_response")
                code = reply.get("chat_error", "")
                if not isinstance(code, str) or code not in {"", "invalid_chat_message", "chat_disconnected"}:
                    raise ControlError("rpc_invalid_response")
                return dict(info, result=reply["result"], messages=[{"id": row["id"], "text": row["text"]} for row in rows], stream=descriptor[0],
                            error_code=code or info.get("error_code", ""))
        except ControlError as error:
            return dict(self._failure(error.code, running), messages=[], stream=0)
        except UnicodeError:
            return dict(self._failure("rpc_invalid_response", running), messages=[], stream=0)


def discover_profiles(base=None, explicit=None):
    """List prepared profiles, newest first; an explicit folder/file is supported."""
    if explicit is not None:
        roots = [_profile_root(explicit)]
    else:
        parent = Path(base) if base is not None else default_base()
        try:
            paths = list(parent.glob("*/native-session.json"))
            paths.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)
            roots = [path.parent.resolve() for path in paths]
        except OSError:
            return []
    profiles = []
    for root in roots:
        info = Controller(root).info()
        if info["slot"]:
            profiles.append(Profile(root, info["room"], info["slot"], info["player"], info["server"],
                                    info["language"], info["has_password"], info["auto_connect"]))
    return profiles


def default_profile(base=None, explicit=None):
    profiles = discover_profiles(base, explicit)
    if not profiles:
        return None
    if explicit is None:
        parent = Path(base) if base is not None else default_base()
        try:
            remembered = _read_json(parent / MARKER, CONTROL_LIMIT, "no_profile").get("root")
            if isinstance(remembered, str):
                root = _profile_root(remembered)
                for profile in profiles:
                    if profile.root == root:
                        return profile
        except (ControlError, OSError, ValueError):
            pass
        try:
            with (parent / "derniere-salle-native.json").open("rb") as source:
                raw = source.read(CONTROL_LIMIT + 1)
            if len(raw) <= CONTROL_LIMIT:
                token = json.loads(raw)
                if isinstance(token, str) and re.fullmatch(r"[0-9a-fA-F]{64}", token):
                    for profile in profiles:
                        if profile.root.name == token:
                            return profile
        except (OSError, ValueError, UnicodeError, RecursionError):
            pass
    return profiles[0]


def remember_profile(root, base=None):
    parent = Path(base) if base is not None else default_base()
    parent.mkdir(parents=True, exist_ok=True)
    atomic(parent / MARKER, json.dumps({"root": str(_profile_root(root))}).encode("utf-8"))
