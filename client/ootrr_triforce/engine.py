from .i18n import tr
from .app_runtime import bundled_node, run_process
from contextlib import contextmanager
import filecmp
import json
import os
import shutil
import subprocess
import tempfile
from importlib import resources
from pathlib import Path


class EnginePathError(RuntimeError):
    def __init__(self, message):
        self.public_message = message
        super().__init__(message)


@contextmanager
def _wasi_paths(command, paths):
    """Keep Windows uvwasi paths short without weakening resource validation.

    uvwasi resolves aliases and then fails stat calls above MAX_PATH. Rust's
    is_file() consequently treats an existing overlay as absent and can read
    vanilla data instead. A real working copy avoids that fallback. /load
    remains the original loader namespace, including sibling size tables.
    """
    if os.name != "nt" or command not in ("patch", "shops", "skulls", "sources", "network-flow-base", "localize") or len(paths) < 2:
        yield paths
        return
    mod = Path(paths[1]).resolve()
    if mod.name != "romfs" or mod.parent.name != "Archipelago":
        yield paths
        return
    loader = mod.parent.parent
    if ((loader / "Triforce.exe").exists() or (loader / "image.bin").exists()
            or (loader / "Pack/ZsDic.pack.zs").is_file()):
        raise EnginePathError(tr("Choose a generated Archipelago mod folder, separate from the game files."))
    for directory, directories, files in os.walk(loader):
        for name in (*directories, *files):
            entry = Path(directory) / name
            if entry.is_symlink() or (hasattr(entry, "is_junction") and entry.is_junction()):
                raise EnginePathError(tr("Generated mod resources must use normal files and folders."))
    with tempfile.TemporaryDirectory(prefix="ap-wasi-") as temp:
        short_load = Path(temp).resolve() / "l"
        if short_load.is_relative_to(loader):
            raise EnginePathError(tr("Choose a Windows temporary folder outside the generated mod folder."))
        relative_mod = mod.relative_to(loader)
        # Reserve room for native resource names added by shop/skull passes.
        longest = max([180, *(len(str(path.relative_to(loader))) for path in loader.rglob("*") if path.is_file())])
        if len(str(short_load)) + 1 + longest >= 260:
            raise EnginePathError(tr("The Windows temporary folder path is too long. Choose a shorter temporary folder and try again."))
        shutil.copytree(loader, short_load)
        adjusted = (paths[0], short_load / relative_mod, *paths[2:])
        yield adjusted
        # Publish only after a successful engine exit. Failed validation leaves
        # the caller's working mod intact, including its resource-size table.
        for source in short_load.rglob("*"):
            if not source.is_file():
                continue
            target = loader / source.relative_to(short_load)
            if not target.resolve().is_relative_to(loader):
                raise EnginePathError(tr("Generated mod resources must use normal files and folders."))
            if target.is_file() and filecmp.cmp(source, target, shallow=False):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            handle, name = tempfile.mkstemp(prefix=".ap-wasi-", dir=target.parent)
            os.close(handle)
            staged = Path(name)
            try:
                shutil.copy2(source, staged)
                staged.replace(target)
            finally:
                staged.unlink(missing_ok=True)


def run_engine(command, request, *paths):
    node = bundled_node()
    if not node:
        raise RuntimeError(tr('Install Node.js 22 or 24 on the machine running this step, or set OOTRR_NODE.'))
    with _wasi_paths(command, paths) as paths, tempfile.TemporaryDirectory(prefix="ootrr-ap-") as temp:
        root = Path(temp)
        for file in ("engine.cjs", "engine.wasm"):
            (root / file).write_bytes(resources.files(__package__).joinpath(file).read_bytes())
        proc = run_process([node, "--no-warnings", str(root / "engine.cjs"), str(root / "engine.wasm"),
                               command, *map(str, paths)], input=json.dumps(request).encode(),
                              capture_output=True, timeout=300)
        if proc.returncode:
            raise RuntimeError(proc.stderr.decode(errors="replace")[-3500:] or tr('The OOTRR engine failed.'))
        return proc.stdout.decode()
