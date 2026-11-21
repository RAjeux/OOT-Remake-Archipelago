"""Optional read-only viewer. The game owns the socket and the process-lifetime marker."""
import ctypes
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import re
import sys
import time

bundle = Path(__file__).resolve().with_name("Client-OOT-Remake.pyz")
sys.path.insert(0, str(bundle if bundle.is_file() else Path(__file__).resolve().parents[1] / "client"))
from ootrr_triforce.i18n import tr, set_language, profile_language


def observer_language(root, active):
    return (profile_language(root) or "en") if active else "en"


def main():
    base=Path(os.environ["LOCALAPPDATA"])/"OOTRR-Archipelago"
    k=ctypes.WinDLL("kernel32",use_last_error=True)
    create=k.CreateFileW
    create.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,ctypes.c_void_p,w.DWORD,w.DWORD,w.HANDLE]
    create.restype=w.HANDLE
    close=k.CloseHandle
    close.argtypes=[w.HANDLE]
    invalid=ctypes.c_void_p(-1).value
    root=None
    live=None
    pos=0
    set_language("en")
    intro=False
    while True:
        try:
            token=json.loads((base/"derniere-salle-native.json").read_bytes())
        except (FileNotFoundError,ValueError):
            token=""
        if not isinstance(token,str) or not re.fullmatch("[a-f0-9]{64}",token):
            set_language("en")
            if not intro:
                print(tr("Local observer. You can close this window while playing."),flush=True)
                intro=True
            if live is not False: print(tr("Waiting for room setup."),flush=True)
            live=False
            time.sleep(1)
            continue
        new=base/token
        if new!=root:
            root=new;live=None;pos=0
        handle=create(str(root/"native-active.lock"),0x80000000,7,None,3,0,None)
        if handle!=invalid:
            close(handle);active=False
        else:
            active=ctypes.get_last_error() in (32,33)
        set_language(observer_language(root, active))
        if not intro:
            print(tr("Local observer. You can close this window while playing."),flush=True)
            intro=True
        journal=root/"archipelago-jeu.log"
        if active and not live:
            print(tr("Game detected · Archipelago mod active."),flush=True)
            try:
                with journal.open("rb") as f:
                    f.seek(max(0,journal.stat().st_size-65536))
                    chunk=f.read()
                    last=max(chunk.rfind(b"Archipelago mod active"),chunk.rfind(b"Mod Archipelago actif"))
                    if last>=0:
                        print(chunk[last:].decode("utf-8","replace").rstrip(),flush=True)
                    pos=f.tell()
            except FileNotFoundError:pos=0
        elif active:
            try:
                with journal.open("rb") as f:
                    f.seek(pos);chunk=f.read();pos=f.tell()
                if chunk:print(chunk.decode("utf-8","replace"),end="",flush=True)
            except FileNotFoundError:pass
        elif live is not False:
            print(tr("Waiting for the game with the mod enabled.") if live is None
                  else tr("The in-game client is closed."),flush=True)
        live=active
        time.sleep(.5)
if __name__ == "__main__":
    try:main()
    except KeyboardInterrupt:pass
