"""Prepare and run the Windows source application with isolated development data."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build
import build_app

BOOTSTRAP = """from pathlib import Path
import runpy, sys
client, resources, entry, *arguments = sys.argv[1:]
sys.path.insert(0, client)
from ootrr_triforce import app_runtime
app_runtime._resource_override = Path(resources)
sys.argv = [entry, *arguments]
runpy.run_path(entry, run_name='__main__')
"""


def owned(path, directory):
    """Reject a development destination redirected outside its private tree."""
    resolved, directory = Path(path).resolve(), Path(directory).resolve()
    if not resolved.is_relative_to(directory):
        raise ValueError("Development paths must stay inside their build workspace.")
    return resolved


def workspace_path(value=None, root=ROOT):
    root = Path(root).resolve()
    base = root / "build"
    if not base.resolve().is_relative_to(root):
        raise ValueError("The build folder must stay inside this checkout.")
    path = Path(value) if value is not None else base / "development"
    if not path.is_absolute():
        path = root / path
    path = owned(path, base)
    if path == base.resolve():
        raise ValueError("Choose a dedicated subfolder of build, not build itself.")
    return path


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            result.update(chunk)
    return result.hexdigest()


def write_changed(path, raw, workspace):
    path = owned(path, workspace)
    if path.is_file() and path.read_bytes() == raw:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".dev-", dir=path.parent) as temporary:
        staged = Path(temporary) / "resource"
        staged.write_bytes(raw)
        staged.replace(path)
    return True


def copy_changed(source, target, workspace):
    target = owned(target, workspace)
    if target.is_file() and digest(source) == digest(target):
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".dev-", dir=target.parent) as temporary:
        staged = Path(temporary) / "resource"
        shutil.copyfile(source, staged)
        staged.replace(target)
    return True


def source_entries(root):
    root = Path(root)
    rows = list(build.tree(root / "apworld"))
    rows.extend(("ootrr_remake/" + name, root / "client/ootrr_triforce" / name)
                for name in build.WORLD_FILES)
    return sorted(rows)


def source_fingerprint(rows):
    return hashlib.sha256(json.dumps([(name, digest(path)) for name, path in rows],
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def prepare_resources(workspace=None, *, root=ROOT, node=None, node_license=None, runtime_provider=None):
    """Stage only development resources; never install a world or change a profile."""
    root = Path(root).resolve()
    workspace = workspace_path(workspace, root)
    if bool(node) != bool(node_license):
        raise ValueError("Supply both --node and --node-license, or neither.")
    if node and not all(Path(path).is_file() for path in (node, node_license)):
        raise ValueError("The supplied Node executable and license must already exist.")
    resources = owned(workspace / "resources", workspace)
    library = root / "prebuilt/windows-x64/archipelago.dll"
    header = root / "native/ootrr_ap_digest.h"
    expected = ("static const unsigned char ap_dll_sha16[32] = {"
                + ",".join(map(str, bytes.fromhex(digest(library)))) + "};\n").encode("ascii")
    if header.read_bytes() != expected:
        raise ValueError("The native DLL and digest differ. Rebuild them with tools/build.py --native.")
    if not node:
        cache = owned(root / "build/app-dependencies", root / "build")
        for filename in ("node.exe", "NODE-LICENSE.txt"):
            owned(cache / filename, cache)
    provider = runtime_provider or build_app.pinned_node
    executable, license_file = provider(node, node_license)
    workspace.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    entries = source_entries(root)
    fingerprint = source_fingerprint(entries)
    index_path = owned(workspace / "source-resources.json", workspace)
    try:
        prior = json.loads(index_path.read_bytes())
    except (FileNotFoundError, ValueError):
        prior = {}
    world = owned(resources / "ootrr_remake.apworld", workspace)
    rebuilt = (not isinstance(prior, dict) or prior.get("world_inputs") != fingerprint
               or not world.is_file() or prior.get("world_sha256") != digest(world))
    if rebuilt:
        build.archive(world, entries)
    files = {
        "native/archipelago.dll": library,
        "runtime/libzstd.dll": root / "distribution/runtime/libzstd.dll",
        "runtime/LICENSE.txt": root / "distribution/runtime/LICENSE.txt",
        "runtime/node/node.exe": Path(executable), "runtime/node/LICENSE": Path(license_file),
        "assets/icon.png": root / "assets/icon.png",
    }
    files.update({"native/" + name: root / "native" / name for name in build.HOST_FILES})
    files.update({name: root / name for name in ("VERSION", "LICENSE", "NOTICE")})
    copied = sum(copy_changed(source, resources / name, workspace) for name, source in files.items())
    notice = ("Development resources for OOT Remake Archipelago.\n"
              "Run and modify the source in this checkout; this folder is not a player release.\n"
              "See CONTRIBUTING.md, LICENSE, NOTICE and client/credits in the checkout.\n")
    write_changed(resources / "SOURCES.txt", notice.encode("utf-8"), workspace)
    payload = {name: digest(resources / name) for name in files}
    payload.update({name: digest(resources / name) for name in ("ootrr_remake.apworld", "SOURCES.txt")})
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    manifest = dict(schema=1, version=version, platform="windows-x64", node_version=build_app.NODE_VERSION,
                    development=True, payload=dict(sorted(payload.items())))
    write_changed(resources / "app-manifest.json", (json.dumps(manifest, indent=2) + "\n").encode(), workspace)
    index = dict(schema=1, world_inputs=fingerprint, world_sha256=digest(world))
    write_changed(index_path, (json.dumps(index, indent=2) + "\n").encode(), workspace)
    for name in ("local", "roaming", "pycache"):
        owned(workspace / name, workspace).mkdir(exist_ok=True)
    return dict(workspace=str(workspace), resources=str(resources), version=version,
                local_appdata=str(workspace / "local"), appdata=str(workspace / "roaming"),
                world_rebuilt=rebuilt, resources_copied=copied, node_version=build_app.NODE_VERSION)


def child_environment(prepared, environ=None):
    environment = dict(os.environ if environ is None else environ)
    workspace = Path(prepared["workspace"])
    environment.update(LOCALAPPDATA=prepared["local_appdata"], APPDATA=prepared["appdata"],
                       PYTHONPYCACHEPREFIX=str(workspace / "pycache"), PYTHONNOUSERSITE="1", PYTHONUTF8="1",
                       OOTRR_NODE=str(Path(prepared["resources"]) / "runtime/node/node.exe"))
    # Preserve OS TEMP/TMP: deep checkout paths exceed Windows WASI limits.
    return environment


def launch_command(prepared, *, root=ROOT, executable=None, arguments=()):
    root = Path(root).resolve()
    return [executable or sys.executable, "-X", "utf8", "-c", BOOTSTRAP,
            str(root / "client"), prepared["resources"], str(root / "client/app.py"), *map(str, arguments)]


def check_environment(*, dependencies=True):
    if sys.platform != "win32" or sys.maxsize <= 2**32 or sysconfig.get_platform() != "win-amd64":
        raise ValueError("The source GUI requires Windows x64 Python with Tcl/Tk.")
    if sys.version_info < (3, 13):
        raise ValueError("Use Python 3.13 or later; Python 3.13 is the CI baseline.")
    missing = [name for name in ("tkinter", "zstandard", "PIL", "texture2ddecoder")
               if dependencies and importlib.util.find_spec(name) is None]
    if missing:
        raise ValueError("Missing development dependencies: " + ", ".join(missing)
                         + ". Install requirements-dev.txt with this virtual environment's Python.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        "Uses requirements-dev.txt, not PyInstaller. The first preparation downloads and verifies the pinned "
        "Node runtime unless --node and --node-license provide it. No global APWorld, profile or save is installed."))
    parser.add_argument("--workspace", type=Path, help="A dedicated subfolder of build/ (default: build/development).")
    parser.add_argument("--node", type=Path, help="An existing official pinned Windows x64 Node executable.")
    parser.add_argument("--node-license", type=Path, help="Its original Node LICENSE file; requires --node.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare-only", action="store_true", help="Prepare resources without opening the GUI or running Node.")
    mode.add_argument("--self-test", action="store_true", help="Run the actual source runtime self-test, then exit.")
    options = parser.parse_args(argv)
    try:
        check_environment(dependencies=not options.prepare_only)
        prepared = prepare_resources(options.workspace, node=options.node, node_license=options.node_license)
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + "\n")
    print(json.dumps(prepared, indent=2), flush=True)
    if options.prepare_only:
        return 0
    arguments = ("--self-test", str(Path(prepared["workspace"]) / "self-test.json")) if options.self_test else ()
    return subprocess.run(launch_command(prepared, arguments=arguments),
                          cwd=ROOT, env=child_environment(prepared)).returncode


if __name__ == "__main__":
    sys.exit(main())
