"""Publish one complete Archipelago mod in the loader root selected by the player."""
from .i18n import tr
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from .medallions import REST
from .save_bridge import write_json, exclusive

MARK = ".ootrr-ap-installation.json"
OWNER = "ootrr-ap-client"
HOSTS = ("nx2navi", "hookshot", "longshot")
MOD = "Archipelago"


def known_folder(base):
    # The previous OOTRR build in this setup wrote My Seed under this folder.
    folder = base / "Programs" / "Triforce" / "mods"
    return folder if (folder / "My Seed" / "romfs").is_dir() or (folder / MOD / MARK).is_file() else None


def validate_root(folder, romfs, cache):
    at = folder.resolve()
    if at.name.casefold() in {"romfs","exefs"} or (at / "romfs").is_dir() or (at / "exefs").is_dir():
        raise ValueError(tr('Choose the folder containing mods (for example mods), one level above My Seed.'))
    if at == Path(at.anchor) or at.is_relative_to(romfs) or romfs.is_relative_to(at) or at.is_relative_to(cache) or cache.is_relative_to(at):
        raise ValueError(tr('The mod folder must be separate from game files and client data.'))
    at.mkdir(parents=True,exist_ok=True)
    return at


def tables(folder):
    result = {}
    def visit(parent, depth):
        if depth >= 4:
            return
        for p in sorted(parent.iterdir()):
            if p.name.startswith((".", "_", "-")) or not p.is_dir() or p.is_symlink() or (hasattr(p,"is_junction") and p.is_junction()):
                continue
            if (p/"romfs").is_dir() or (p/"exefs").is_dir():
                t = p/"romfs"/REST
                if p != folder/MOD and t.is_file():
                    result[p.relative_to(folder)] = t
            else:
                visit(p,depth+1)
    visit(folder,0)
    return result


def build_cache(base, token, host, entries, romfs):
    stamp = [(str(key),p.stat().st_size,p.stat().st_mtime_ns) for key,p in entries.items()]
    digest = hashlib.sha256(json.dumps([token,host,str(romfs),stamp]).encode()).hexdigest()[:24]
    # Rebuild GameData and pickup resources predating the AP Skulltula markers.
    return base / "mods-v18" / digest


def state_dir(folder):
    return folder.parent / (".ootrr-ap-" + hashlib.sha256(os.fsencode(os.path.normcase(str(folder.resolve())))).hexdigest()[:14])


def offer_old_seed(folder):
    old = folder/"My Seed"
    if not (old/"romfs"/REST).is_file() and not (old/"romfs/UI/Layout2Archive").is_dir():
        return
    print(tr('The old mod {value0} uses the same files as this room. You can move it aside or disable it in your launcher.', value0=old),flush=True)
    if input(tr('Move My Seed aside now? [y/N] ')).strip().casefold() in {"o","oui","y","yes"}:
        backup = state_dir(folder)/"mods-en-pause"/"My Seed"
        backup.parent.mkdir(parents=True,exist_ok=True)
        if backup.exists():
            backup = backup.with_name("My Seed-"+uuid.uuid4().hex[:8])
        old.rename(backup)
        print(tr('Old mod preserved in {value0}.', value0=backup),flush=True)


def marker(path):
    try:
        doc = json.loads((path/MARK).read_text(encoding="utf-8"))
        return doc if isinstance(doc,dict) and doc.get("owner")==OWNER else {}
    except (ValueError,FileNotFoundError):
        return {}


def tree_stamp(root):
    records = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != MARK:
            stat = path.stat()
            records.append((path.relative_to(root).as_posix(), stat.st_size, stat.st_mtime_ns))
    return hashlib.sha256(json.dumps(records).encode()).hexdigest()


def install(source, folder, token):
    src = source/MOD
    if not (src/"romfs").is_dir():
        raise ValueError(tr('Incomplete Archipelago RomFS.'))
    working = state_dir(folder)
    working.mkdir(exist_ok=True)
    dest, old = folder/MOD, working/"previous"
    key = tree_stamp(src)
    with exclusive(working/"install.lock"):
        if old.exists() and not dest.exists():
            old.rename(dest)
        if dest.is_symlink() or (hasattr(dest,"is_junction") and dest.is_junction()) or (dest.exists() and not marker(dest)):
            raise ValueError(tr('{value0} already exists and belongs to another mod. Rename it before installing this room.', value0=dest))
        installed = marker(dest)
        if installed.get("room") == token and installed.get("build") == key and installed.get("installed") == tree_stamp(dest):
            return dest
        with tempfile.TemporaryDirectory(dir=working,prefix="creation-") as tmp:
            staged = Path(tmp)/MOD
            shutil.copytree(src,staged)
            write_json(staged/MARK,{"owner":OWNER,"room":token,"build":key,"installed":tree_stamp(staged)})
            if old.exists():
                old.rename(working/("archive-"+uuid.uuid4().hex[:12]))
            if dest.exists():
                dest.rename(old)
            try:
                staged.rename(dest)
            except BaseException:
                if old.exists() and not dest.exists():
                    old.rename(dest)
                raise
    return dest
