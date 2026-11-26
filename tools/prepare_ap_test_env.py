"""Copy the Windows Archipelago 0.6.8 generator dependencies into build/.

This prepares a fresh private snapshot for test_network_generation.py and the
generation matrix. It does not run Archipelago, install an APWorld, download
anything, or copy player files, output rooms, settings or saves. AP_SOURCE is
not an input to these frozen Windows generator tests.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import stat
from zipfile import BadZipFile, ZipFile

ROOT = Path(__file__).resolve().parents[1]
AP_VERSION = (0, 6, 8)
RUNTIME_FILES = ("ArchipelagoGenerate.exe", "python3.dll", "python313.dll", "manifest.json")
DATA_DIRS = ("lib", "data")
MARKER = "ap-test-env.json"
INCOMPLETE = ".ap-test-env-incomplete"
MAX_FILES = 20000
MAX_FILE_BYTES = 256 << 20
MAX_TOTAL_BYTES = 2 << 30
MAX_MANIFEST_BYTES = 8 << 20


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def private_destination(path, source=None):
    """Resolve aliases before checking both the workspace and source boundary."""
    path = Path(path).resolve()
    root = ROOT.resolve()
    build = (root / "build").resolve()
    if not build.is_relative_to(root):
        raise ValueError("The build folder must stay inside this checkout.")
    if path == build or not path.is_relative_to(build):
        raise ValueError("Choose a private destination below this repository's build/ directory.")
    if source is not None:
        source = Path(source).resolve()
        if path == source or path.is_relative_to(source) or source.is_relative_to(path):
            raise ValueError("The private destination must be separate from the Archipelago installation.")
    return path


def _regular(path, *, directory=False):
    try:
        info = path.lstat()
    except OSError as error:
        raise ValueError("Missing Archipelago runtime resource: " + path.name) from error
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError("Archipelago test dependencies cannot contain symbolic links or junctions.")
    correct = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not correct:
        raise ValueError("Unexpected Archipelago resource type: " + path.name)
    return info


def installation_version(root):
    """Only the known frozen Python 3.13 / AP 0.6.8 layout is supported here."""
    manifest = Path(root) / "manifest.json"
    info = _regular(manifest)
    if info.st_size > 65536:
        raise ValueError("The Archipelago installation manifest exceeds its size limit.")
    try:
        value = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError("Invalid Archipelago installation manifest.") from error
    version = value.get("version") if isinstance(value, dict) else None
    if not isinstance(version, list) or len(version) != 3 or any(type(part) is not int for part in version) or tuple(version) != AP_VERSION:
        raise ValueError("These generation tests require a Windows Archipelago 0.6.8 installation.")
    return tuple(version)


def inspect_installation(root):
    """Bound and hash the generator's allowlisted files without executing them."""
    root = Path(root).resolve()
    _regular(root, directory=True)
    version = installation_version(root)
    paths = [root / name for name in RUNTIME_FILES]
    visited = len(paths)
    for name in DATA_DIRS:
        directory = root / name
        _regular(directory, directory=True)
        pending = [(directory, 0)]
        while pending:
            current, depth = pending.pop()
            if depth > 32:
                raise ValueError("The Archipelago dependency layout exceeds its depth limit.")
            for child in sorted(current.iterdir()):
                visited += 1
                if visited > MAX_FILES:
                    raise ValueError("The Archipelago dependency layout exceeds its file-count limit.")
                info = child.lstat()
                if stat.S_ISDIR(info.st_mode):
                    _regular(child, directory=True)
                    pending.append((child, depth + 1))
                else:
                    _regular(child)
                    paths.append(child)
    files, total = {}, 0
    for path in sorted(paths):
        info = _regular(path)
        if info.st_size > MAX_FILE_BYTES:
            raise ValueError("An Archipelago dependency exceeds its file-size limit.")
        total += info.st_size
        if total > MAX_TOTAL_BYTES:
            raise ValueError("The Archipelago dependencies exceed their total-size limit.")
        files[path.relative_to(root).as_posix()] = dict(bytes=info.st_size, mtime_ns=info.st_mtime_ns, sha256=digest(path))
    for name in RUNTIME_FILES[:-1]:
        with (root / name).open("rb") as stream:
            if stream.read(2) != b"MZ":
                raise ValueError("The generator and Python runtime must be Windows executables.")
    library = root / "lib/library.zip"
    if library.relative_to(root).as_posix() not in files or "data/options.yaml" not in files:
        raise ValueError("Missing frozen Archipelago library.zip or bundled data/options.yaml.")
    try:
        with ZipFile(library) as archive:
            members = archive.infolist()
            if len(members) > MAX_FILES or sum(row.file_size for row in members) > MAX_TOTAL_BYTES:
                raise ValueError("The frozen Archipelago library exceeds its size limits.")
            if not {"Generate.pyc", "Main.pyc", "NetUtils.pyc", "Utils.pyc"} <= set(archive.namelist()):
                raise ValueError("The frozen Archipelago generator library is incomplete.")
    except BadZipFile as error:
        raise ValueError("Invalid frozen Archipelago library.zip.") from error
    return dict(ap_version=list(version), files=files, file_count=len(files), total_bytes=total)


def prepare_environment(ap_root, output):
    """Create one independent snapshot; an existing destination is never reused."""
    source = Path(ap_root).resolve()
    target = private_destination(output, source)
    if target.exists():
        raise FileExistsError("Choose a fresh snapshot directory, or reuse the existing one with --dependencies.")
    before = inspect_installation(source)
    target.mkdir(parents=True)
    (target / INCOMPLETE).write_text("Private dependency copy in progress.\n", encoding="ascii")
    for relative, expected in before["files"].items():
        source_file, destination = source / relative, target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination)
        if destination.stat().st_size != expected["bytes"] or digest(destination) != expected["sha256"]:
            raise ValueError("A copied Archipelago dependency failed verification: " + relative)
    if inspect_installation(source) != before:
        raise ValueError("The Archipelago installation changed while copying; use a fresh destination after its update finishes.")
    if inspect_installation(target) != before:
        raise ValueError("The private Archipelago dependency snapshot differs from its source.")
    report = dict(schema=1, purpose="private-windows-ap-generation-dependencies", **before,
                  original_files_unchanged=True, copied_player_data=False)
    (target / MARKER).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (target / INCOMPLETE).unlink()
    return report


def validate_snapshot(path, ap_root=None):
    """Accept only a complete private copy whose runtime bytes still match."""
    path = private_destination(path, ap_root)
    _regular(path, directory=True)
    marker = path / MARKER
    if (path / INCOMPLETE).exists() or _regular(marker).st_size > MAX_MANIFEST_BYTES:
        raise ValueError("The private Archipelago snapshot is incomplete or invalid.")
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError("Invalid private Archipelago snapshot manifest.") from error
    if not isinstance(value, dict) or value.get("schema") != 1 or value.get("purpose") != "private-windows-ap-generation-dependencies":
        raise ValueError("Prepare dependencies with tools/prepare_ap_test_env.py first.")
    if {child.name for child in path.iterdir()} != {*RUNTIME_FILES, *DATA_DIRS, MARKER}:
        raise ValueError("The private dependency snapshot contains unexpected root files.")
    actual = inspect_installation(path)
    if any(value.get(key) != actual[key] for key in ("ap_version", "files", "file_count", "total_bytes")):
        raise ValueError("The private Archipelago snapshot changed; prepare a fresh copy.")
    if ap_root is not None and installation_version(Path(ap_root).resolve()) != tuple(actual["ap_version"]):
        raise ValueError("The Archipelago installation and dependency snapshot versions differ.")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ap-root", required=True, type=Path,
                        help="Your own Windows Archipelago 0.6.8 installation containing ArchipelagoGenerate.exe, lib/ and data/.")
    parser.add_argument("--output", type=Path, default=ROOT / "build/ap-test-dependencies",
                        help="Fresh private destination below build/ (default: build/ap-test-dependencies).")
    args = parser.parse_args(argv)
    try:
        report = prepare_environment(args.ap_root, args.output)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(dict(result="PASS", dependencies=str(args.output.resolve()), ap_version=report["ap_version"],
                          files=report["file_count"], bytes=report["total_bytes"], original_files_unchanged=True)))


if __name__ == "__main__":
    main()
