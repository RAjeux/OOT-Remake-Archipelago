"""Inspect a frozen Windows application, its embedded runtime and private paths."""
import argparse
from io import BytesIO
import hashlib
import json
import marshal
import ntpath
from pathlib import Path, PurePosixPath
import struct
import types
from zipfile import ZipFile, is_zipfile

ROOT = Path(__file__).resolve().parents[1]
MAX_ENTRY = 160 << 20
FORBIDDEN_ROOTS = {"romfs", "exefs", "mods", "user", "saves", "screenshots", "build", "tests", "references", ".git", ".venv"}
FORBIDDEN_NAMES = {"outils.json", "native-session.json", "last-profile.json", "connection-control.json", "contexte-codex.md"}
FORBIDDEN_SUFFIXES = {".sav", ".apsave", ".apootrr", ".archipelago", ".apmultidata", ".apmultisave"}
REQUIRED_MODULES = {"ootrr_triforce.app_window", "ootrr_triforce.app_runtime", "ootrr_triforce.install_service",
                    "ootrr_triforce.player", "ootrr_triforce.connection_window", "ootrr_triforce.hookshot_setup",
                    "ootrr_triforce.settings_editor", "ootrr_triforce.room_library", "ootrr_triforce.tracker_service",
                    "ootrr_triforce.chat_window", "ootrr_triforce.external_window", "ootrr_triforce.full_worker",
                    "ootrr_triforce.full_ap", "ootrr_triforce.full_mod", "ootrr_full.randomizer.randomizer_core",
                    "ootrr_full.archipelago.bridge", "ootrr_full.patching.ammo_quantities", "yaml",
                    "ootrr_triforce.full_allocations", "ootrr_triforce.full_portable", "ootrr_triforce.full_settings",
                    "ootrr_triforce.full_scrub_hints", "ootrr_triforce.room_updates", "ootrr_triforce.upgrade_readiness",
                    "ootrr_triforce.upgrade_deathlink", "ootrr_full.game.loose_keys",
                    "ootrr_full.game.native_key_limits", "ootrr_full.patching.key_adapter",
                    "tkinter", "zstandard"}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_name(name):
    name = name.replace("\\", "/")
    path = PurePosixPath(name)
    if ntpath.isabs(name) or path.is_absolute() or ".." in path.parts:
        raise ValueError("Unsafe archive path: " + name)
    if not path.parts or path.parts[0].casefold() in FORBIDDEN_ROOTS:
        raise ValueError("Private archive root: " + name)
    if path.name.casefold() in FORBIDDEN_NAMES or path.suffix.casefold() in FORBIDDEN_SUFFIXES:
        raise ValueError("Private game/session resource: " + name)
    if path.suffix.casefold() == ".exe" and name != "runtime/node/node.exe":
        raise ValueError("Unexpected executable payload: " + name)
    return name


def markers(extra):
    values = {str(ROOT), str(Path.home()), *extra}
    result = set()
    for value in values:
        if len(value) < 8:
            raise ValueError("Private markers must contain at least eight characters.")
        for spelling in (value.replace("\\", "/"), value.replace("/", "\\")):
            result.add(spelling.lower().encode("utf-8"))
            result.add(spelling.lower().encode("utf-16-le"))
    return result


def private_data(raw, private_markers, context):
    lowered = raw.lower()
    if any(value in lowered for value in private_markers):
        raise ValueError("Private build path or marker in " + context)


def code_paths(code, context):
    if not isinstance(code, types.CodeType):
        raise ValueError("Expected Python code in " + context)
    if ntpath.isabs(code.co_filename) or Path(code.co_filename).is_absolute():
        raise ValueError("Absolute Python source path in " + context)
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            code_paths(value, context)


def inspect_zip(raw, private_markers, context):
    with ZipFile(BytesIO(raw)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate ZIP member in " + context)
        if sum(row.file_size for row in archive.infolist()) > 192 << 20:
            raise ValueError("Oversized ZIP contents in " + context)
        for name in names:
            safe_name(name)
            data = archive.read(name)
            private_data(data, private_markers, context + "/" + name)
            if name.endswith(".pyc"):
                code_paths(marshal.loads(data[16:]), context + "/" + name)


def inspect_app(path, extra_markers=()):
    from PyInstaller.archive.readers import CArchiveReader
    from build_app import HOST_FILES, NODE_SHA256

    path = Path(path)
    private_markers = markers(extra_markers)
    with path.open("rb") as stream:
        header = stream.read(4096)
    if header[:2] != b"MZ":
        raise ValueError("The application is not a Windows executable.")
    pe = struct.unpack_from("<I", header, 0x3C)[0]
    if (header[pe:pe+4] != b"PE\x00\x00" or struct.unpack_from("<H", header, pe+4)[0] != 0x8664
            or struct.unpack_from("<H", header, pe+24+68)[0] != 2):
        raise ValueError("The application must use the Windows x64 GUI subsystem.")
    archive = CArchiveReader(str(path))
    entries = {safe_name(name): name for name in archive.toc}
    if len(entries) != len(archive.toc):
        raise ValueError("Colliding normalized archive paths.")
    manifest = json.loads(archive.extract(entries["app-manifest.json"]))
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if manifest.get("schema") != 1 or manifest.get("version") != version or manifest.get("platform") != "windows-x64":
        raise ValueError("The application manifest does not match this source version.")
    from build_app import client_code_digest
    if manifest.get('code_sha256') != client_code_digest():
        raise ValueError('The embedded Python code differs from the reviewed source.')
    expected_native = sha((ROOT / "prebuilt/windows-x64/archipelago.dll").read_bytes())
    expected_wasm = sha((ROOT / "client/ootrr_triforce/engine.wasm").read_bytes())
    components = [("native/archipelago.dll", expected_native),
                  ("ootrr_triforce/engine.wasm", expected_wasm),
                  ("runtime/node/node.exe", NODE_SHA256)]
    components.extend(("native/" + name, sha((ROOT / "native" / name).read_bytes())) for name in HOST_FILES)
    for name, expected in components:
        if manifest["payload"].get(name) != expected:
            raise ValueError("Embedded component differs from the reviewed source: " + name)
    for name, digest in manifest["payload"].items():
        if name not in entries or sha(archive.extract(entries[name])) != digest:
            raise ValueError("Missing or altered embedded resource: " + name)
    modules = set()
    counts = dict(archive_entries=len(entries), python_modules=0, nested_zips=0)
    for name, original in entries.items():
        if archive.toc[original][2] > MAX_ENTRY:
            raise ValueError("Oversized application resource: " + name)
        if archive.toc[original][-1] == "z":
            pyz = archive.open_embedded_archive(original)
            modules.update(pyz.toc)
            for module in pyz.toc:
                raw = pyz.extract(module, raw=True)
                if raw is not None:
                    private_data(raw, private_markers, module)
                    code_paths(marshal.loads(raw), module)
            continue
        data = archive.extract(original)
        private_data(data, private_markers, name)
        if archive.toc[original][-1] in ("s", "m", "M"):
            code_paths(marshal.loads(data), name)
        elif is_zipfile(BytesIO(data)):
            inspect_zip(data, private_markers, name)
            counts["nested_zips"] += 1
    missing = REQUIRED_MODULES - modules
    if missing:
        raise ValueError("Required application modules are not frozen: " + ", ".join(sorted(missing)))
    counts["python_modules"] = len(modules)
    return dict(result="PASS", version=version, artifact=path.name, bytes=path.stat().st_size,
                sha256=sha(path.read_bytes()), console=False, onefile=True,
                native_sha256=expected_native, wasm_sha256=expected_wasm, node_sha256=NODE_SHA256,
                payload_hashes=True, private_paths_absent=True, absolute_python_paths_absent=True, **counts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("application", type=Path)
    parser.add_argument("--private-marker", action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = inspect_app(args.application, args.private_marker)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
