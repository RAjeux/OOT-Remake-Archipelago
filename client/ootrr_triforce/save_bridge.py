"""Save IO for the private Triforce profile. No game or process memory access."""
import hashlib
import json
import os
import re
import struct
import tempfile
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from .catalog import CHESTS, FILLER, GEAR, ITEM_IDS, LOCATION_IDS

WORD = struct.Struct("<I")
PAIR = struct.Struct("<II")
SENTINEL = 0xA3DB7114
RUPEES = 0xA77921D7
GOAL_STEP = 0x746F47C0
COMPLETE = 0x4C0A63F4
GANON_SECOND_HALF = 0x641E0375
ITEM_NAMES = {v: k for k, v in ITEM_IDS.items()}


class Snapshot:
    def __init__(self, data):
        if len(data) < 56 or WORD.unpack_from(data)[0] != 0x01020304:
            raise ValueError("Format de progress.sav inconnu.")
        start = WORD.unpack_from(data, 8)[0]
        if start < 48 or start > len(data) - 8 or (start - 40) % 8:
            raise ValueError("Table des données de sauvegarde invalide.")
        sentinel, keyed = PAIR.unpack_from(data, start - 8)
        if sentinel != SENTINEL or not start <= keyed <= len(data) - 8:
            raise ValueError("Fin de table de sauvegarde invalide.")
        if not any(data[i:i+8] == bytes(8) for i in range(keyed, len(data) - 7, 8)):
            raise ValueError("Liste de données incomplète.")
        self.data = bytearray(data)
        self.offsets = {}
        for at in range(40, start - 8, 8):
            h = WORD.unpack_from(data, at)[0]
            if h == SENTINEL or (h and h in self.offsets):
                raise ValueError("Clé de sauvegarde répétée.")
            if h:
                self.offsets[h] = at + 4

    def get(self, flag):
        if flag not in self.offsets:
            raise ValueError(f"Le champ attendu 0x{flag:08x} est absent de cette sauvegarde.")
        return WORD.unpack_from(self.data, self.offsets[flag])[0]

    def set(self, flag, value):
        self.get(flag)
        WORD.pack_into(self.data, self.offsets[flag], value)

    def checks(self, names):
        return {LOCATION_IDS[n] for n in names if any(self.get(ref["flag"]) == 1 for ref in CHESTS[n])}

    def won(self):
        return self.get(GOAL_STEP) == COMPLETE or 0 < self.get(GANON_SECOND_HALF) < 0x80000000

    def deliver(self, history, cursor):
        for code in set(history):
            name = ITEM_NAMES[code]
            for flag in GEAR.get(name, ()):
                if self.get(flag) == 0:
                    self.set(flag, 1)
        coins = history[cursor:].count(ITEM_IDS[FILLER]) * 5
        if coins:
            # Never reduce a balance acquired with a wallet upgrade or a custom limit.
            # 99 is the base game's capacity; bonus blue rupees stop there.
            current = self.get(RUPEES)
            self.set(RUPEES, max(current, min(99, current + coins)))


def atomic(path, data):
    path = Path(path)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        tmp = Path(f.name)
        try:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def write_json(path, value):
    atomic(path, json.dumps(value, ensure_ascii=False).encode())


@contextmanager
def exclusive(path):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                           wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        close = kernel.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        handle = create(str(path), 0xC0000000, 0, None, 4, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            error = ctypes.get_last_error()
            if error in (32, 33):
                raise BlockingIOError("Triforce utilise la sauvegarde.")
            raise ctypes.WinError(error)
        try:
            yield
        finally:
            close(handle)
    else:
        import fcntl
        with path.open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield


CAPTION_DATE = (0x9811A3F7, 0xDFD840D3, 0xBD46F485, 0x23F3D75E, 0x27853BF7, 0x5EE50BED)


@lru_cache(maxsize=32)
def caption_time(path, stamp):
    # Triforce commits every slot together. Read the game's six integer date fields.
    with path.open("rb") as f:
        header = f.read(32)
        if len(header) != 32 or WORD.unpack_from(header)[0] != 0x01020304:
            return None
        size = WORD.unpack_from(header, 8)[0] - len(header)
        if not 0 < size <= 65536 or size % PAIR.size:
            return None
        rows = f.read(size)
    if len(rows) != size:
        return None
    fields = {}
    kind = None
    for key, value in PAIR.iter_unpack(rows):
        if key == 0:
            kind = value
        elif kind == 2 and key in CAPTION_DATE:
            fields[key] = value
    try:
        return datetime(*(fields[key] for key in CAPTION_DATE))
    except (KeyError, ValueError, OverflowError):
        return None


def save_path(user, slot, slots_dir=None):
    pattern = "slot_[0-9][0-9]" if slot == "auto" else slot
    if slots_dir is not None:
        matches = list(slots_dir.glob(f"{pattern}/progress.sav"))
    else:
        matches = [p for p in (user / "save").glob(f"*/{pattern}/progress.sav")
                   if re.fullmatch(r"[0-9a-fA-F]{32}", p.parents[1].name)]
    if len({p.parents[1] for p in matches}) > 1:
        raise ValueError("Plusieurs profils Triforce dans le dossier de cette salle.")
    if len(matches) < 2:
        return matches[0] if matches else None
    dated = []
    for p in matches:
        cap = p.with_name("caption.sav")
        try:
            st = cap.stat()
            date = caption_time(cap, (st.st_mtime_ns, st.st_size, st.st_ino))
        except FileNotFoundError:
            date = None
        if date is not None:
            dated.append((date, p))
    dated.sort(reverse=True)
    if not dated or (len(dated) > 1 and dated[0][0] == dated[1][0]):
        return None
    return dated[0][1]


def history_cursor(root):
    return max((json.loads(p.read_text()) for p in root.glob("cursor-slot_[0-9][0-9].json")), default=0)


def apply_history(root, slot, history, slots_dir=None):
    """Recover a partial save/ledger commit before applying any new deliveries."""
    user = root / "user"
    if slots_dir is not None:
        user = slots_dir.parent.parent if slots_dir.parent.name == "save" else root
    with exclusive(user / "save.lock"):
        path = save_path(user, slot, slots_dir)
        if path is None or any((user / "save-tx" / path.parents[1].name).glob("ready-*")):
            return False
        for journal in root.glob("delivery-slot_[0-9][0-9].json"):
            pending_slot = journal.stem.removeprefix("delivery-")
            pending_path = save_path(user, pending_slot, slots_dir)
            if not pending_path:
                return False
            digest = hashlib.sha256(pending_path.read_bytes()).hexdigest()
            entry = json.loads(journal.read_text())
            if digest == entry["after"]:
                write_json(root / ("cursor-" + pending_slot + ".json"), entry["cursor"])
            elif digest != entry["before"]:
                raise ValueError("Sauvegarde modifiée pendant une livraison interrompue. Conserve le dossier de session pour récupération.")
            journal.unlink()
        slot = path.parent.name
        journal = root / ("delivery-" + slot + ".json")
        ledger = root / ("cursor-" + slot + ".json")
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        cursor = history_cursor(root)
        if cursor > len(history):
            raise ValueError("Le serveur fournit un historique plus court que celui de cette sauvegarde.")
        snap = Snapshot(data)
        snap.deliver(history, cursor)
        if data != snap.data:
            backup = root / ("before-delivery-" + slot + ".sav")
            atomic(backup, data)
            write_json(journal, {"before": digest, "after": hashlib.sha256(snap.data).hexdigest(), "cursor": len(history)})
            atomic(path, snap.data)
        if cursor != len(history) or journal.exists():
            write_json(ledger, len(history))
        journal.unlink(missing_ok=True)
        return True
