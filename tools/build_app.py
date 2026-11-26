"""Build the single Windows application without rebuilding the native game."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from urllib.request import urlopen
from zipfile import ZipFile
from build import HOST_FILES

ROOT = Path(__file__).resolve().parents[1]
NODE_VERSION = "24.22.3"
NODE_SHA256 = "86fc4785327db5f5c7558dc6156c543b433c313e813a222e088086222ab4afa6"
NODE_LICENSE_SHA256 = "ed34dd8e3f0a78dbaf00d0444ce8e285b015b765379c2e17880455f70370f8e9"
NODE_ZIP_SHA256 = "e612af99f626ab415ea225af6bce5c971feb448cb5cae250bb1c3fa50c5f7d9f"
NODE_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/node-v{NODE_VERSION}-win-x64.zip"
PACKAGES = ("ootrr_triforce", "oot_rando", "ainb", "evfl", "websockets")
PYINSTALLER_VERSION = "6.22.3"
PRODUCT_NAME = "OOT Remake Archipelago"


def windows_version(version):
    """Keep SemVer text exact and map its numeric parts to Windows WORDs."""
    match = re.fullmatch(
        r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
        r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
        r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?", version)
    if match is None:
        raise ValueError("Invalid VERSION SemVer.")
    prerelease = match.group(4)
    identifiers = prerelease.split(".") if prerelease else []
    if any(part.isdigit() and len(part) > 1 and part.startswith("0") for part in identifiers):
        raise ValueError("Invalid VERSION SemVer prerelease number.")
    # alpha.3 and rc.12 retain their sequence number. An unnumbered prerelease
    # uses zero; the original channel and build metadata remain in both strings.
    sequence = int(identifiers[-1]) if identifiers and identifiers[-1].isdigit() else 0
    fixed = (*map(int, match.group(1, 2, 3)), sequence)
    if any(part > 0xffff for part in fixed):
        raise ValueError("VERSION exceeds the Windows 16-bit version fields.")
    return fixed, 0x2 if prerelease else 0


def write_version_info(work, version, name):
    """Create PyInstaller's Windows VersionInfo resource in the build workspace."""
    fixed, flags = windows_version(version)
    strings = {"FileDescription": PRODUCT_NAME, "FileVersion": version, "InternalName": name,
               "OriginalFilename": name + ".exe", "ProductName": PRODUCT_NAME, "ProductVersion": version}
    entries = ",\n".join(f"        StringStruct({key!r}, {value!r})" for key, value in strings.items())
    text = ("# UTF-8 Windows version resource generated from VERSION.\n"
            "VSVersionInfo(\n"
            "  ffi=FixedFileInfo(\n"
            f"    filevers={fixed!r}, prodvers={fixed!r},\n"
            f"    mask=0x3f, flags={flags}, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),\n"
            "  kids=[\n"
            "    StringFileInfo([StringTable('040904B0', [\n"
            f"{entries}\n"
            "    ])]),\n"
            "    VarFileInfo([VarStruct('Translation', [0x0409, 1200])])\n"
            "  ]\n"
            ")\n")
    target = Path(work) / "windows-version-info.txt"
    target.write_text(text, encoding="utf-8", newline="\n")
    return target


def freezer_command(name, work, output, icon, version_file):
    """The Windows resource travels with the same versioned executable name."""
    return [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
            "--noupx", "--name", name, "--paths", str(ROOT / "client"), "--distpath", str(output.resolve()),
            "--workpath", str(work / "freeze"), "--specpath", str(work), "--icon", str(icon),
            "--version-file", str(version_file), "--exclude-module", "PIL", "--exclude-module", "texture2ddecoder"]


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pinned_node(executable=None, license_file=None):
    """Use an explicitly supplied pinned runtime, or fetch its official ZIP."""
    cache = ROOT / "build/app-dependencies"
    node = Path(executable).resolve() if executable else cache / "node.exe"
    license_file = Path(license_file).resolve() if license_file else node.with_name("NODE-LICENSE.txt")
    if executable and not node.is_file():
        raise ValueError("The selected Node.js runtime does not exist.")
    for path, expected in ((node, NODE_SHA256), (license_file, NODE_LICENSE_SHA256)):
        if path.exists() and (not path.is_file() or sha(path) != expected):
            raise ValueError(f"The pinned Node.js resource differs: {path.name}")
    if not node.is_file() or not license_file.is_file():
        if executable:
            raise ValueError("Supply the pinned Node.js executable and its NODE-LICENSE.txt.")
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="node-", dir=cache) as directory:
            stage = Path(directory).resolve()
            assert stage.is_relative_to((ROOT / "build").resolve())
            archive = stage / "node.zip"
            with urlopen(NODE_URL, timeout=120) as response, archive.open("wb") as output:
                if response.geturl() != NODE_URL:
                    raise ValueError("Unexpected Node.js download redirect.")
                total = 0
                while chunk := response.read(1 << 20):
                    total += len(chunk)
                    if total > 128 << 20:
                        raise ValueError("Node.js archive exceeds the expected size limit.")
                    output.write(chunk)
            if sha(archive) != NODE_ZIP_SHA256:
                raise ValueError("The official Node.js archive did not match its pinned SHA-256.")
            with ZipFile(archive) as source:
                prefix = f"node-v{NODE_VERSION}-win-x64/"
                for name, target, expected in (("node.exe", node, NODE_SHA256),
                                               ("LICENSE", license_file, NODE_LICENSE_SHA256)):
                    info = source.getinfo(prefix + name)
                    if info.file_size > 128 << 20:
                        raise ValueError("Node.js resource exceeds the expected size limit.")
                    raw = source.read(info)
                    if hashlib.sha256(raw).hexdigest() != expected:
                        raise ValueError("The official Node.js resource did not match its pinned SHA-256.")
                    target.write_bytes(raw)
    return node, license_file


def _tk_license_text(interpreter, language):
    """Read vendor terms, including CPython's consolidated Windows notices."""
    directory = "tcl" if language == "Tcl" else "tk"
    zipped = int(str(interpreter.call("info", "patchlevel")).split(".")[0]) >= 9
    source = f"//zipfs:/lib/{directory}/{directory}_library/license.terms"
    if zipped and interpreter.call("file", "exists", source):
        handle = interpreter.call("open", source, "r")
        try:
            return interpreter.call("read", handle)
        finally:
            interpreter.call("close", handle)
    folder = interpreter.call("info", "library") if language == "Tcl" else interpreter.eval("set tk_library")
    terms = Path(folder) / "license.terms"
    if terms.is_file():
        return terms.read_text(encoding="utf-8")
    # CPython's Windows layout may omit these individual files. Its build
    # concatenates both notices into LICENSE.txt (PCbuild/regen.targets).
    # Keep the entire file, and reject a PSF-only or truncated license.
    combined = (Path(sys.base_prefix) / "LICENSE.txt").read_text(encoding="utf-8")
    normalized = " ".join(combined.split())
    markers = (
        "This software is copyrighted by the Regents of the University of California, Sun Microsystems, Inc., Scriptics Corporation",
        "The authors hereby grant permission to use, copy, modify, distribute,",
        "IN NO EVENT SHALL THE AUTHORS OR DISTRIBUTORS BE LIABLE",
        "permission to use and distribute the software in accordance with the terms specified in this license.",
    )
    if any(normalized.count(marker) < 2 for marker in markers):
        raise ValueError("Tcl and Tk license terms are missing from this Python distribution.")
    return combined


def licenses(work, node_license):
    """Keep redistribution notices inside the executable, accessible from Help."""
    result = {}
    for name, path in (("Python-LICENSE.txt", Path(sys.base_prefix) / "LICENSE.txt"),
                       ("Node-LICENSE.txt", node_license),
                       ("Go-LICENSE.txt", ROOT / "native/vendor/golang.org/x/sys/LICENSE"),
                       ("Gorilla-WebSocket-LICENSE.txt", ROOT / "native/vendor/github.com/gorilla/websocket/LICENSE"),
                       ("WebSockets-LICENSE.txt", ROOT / "client/websockets/LICENSE")):
        result["licenses/" + name] = path
    for distribution, label in (("pyinstaller", "PyInstaller"), ("zstandard", "Python-Zstandard")):
        package = importlib.metadata.distribution(distribution)
        for file in package.files or ():
            if file.name in ("COPYING.txt", "LICENSE"):
                result[f"licenses/{label}-{file.name}"] = Path(package.locate_file(file))
    # Tcl/Tk 9 embed their script library and its license in their DLL zipfs.
    import tkinter
    window = tkinter.Tk()
    window.withdraw()
    try:
        for language in ("Tcl", "Tk"):
            raw = _tk_license_text(window.tk, language)
            target = work / (language + "-license.terms")
            target.write_text(raw, encoding="utf-8", newline="\n")
            result["licenses/" + target.name] = target
    finally:
        window.destroy()
    for file in (ROOT / "client/credits").iterdir():
        if file.is_file():
            result["licenses/credits/" + file.name] = file
    return result


def source_notice(work, version):
    text = ("OOT Remake Archipelago - corresponding source and third-party notices\n\n"
            f"Application and adapted engine: https://github.com/RAjeux/OOT-Remake-Archipelago/tree/v{version}\n"
            f"Source archive: https://github.com/RAjeux/OOT-Remake-Archipelago/archive/refs/tags/v{version}.zip\n"
            f"Node.js {NODE_VERSION}: https://nodejs.org/dist/v{NODE_VERSION}/node-v{NODE_VERSION}.tar.xz\n"
            f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}: https://www.python.org/downloads/source/\n"
            f"PyInstaller {PYINSTALLER_VERSION}: https://github.com/pyinstaller/pyinstaller/tree/v{PYINSTALLER_VERSION}\n"
            "Go runtime: https://go.dev/dl/\n\n"
            "LICENSE, NOTICE and the licenses/ folder are bundled inside this application.\n"
            "No game files, ROM, save, Triforce executable or OOTRR builder are bundled.\n")
    target = work / "SOURCES.txt"
    target.write_text(text, encoding="utf-8", newline="\n")
    return target


def payload(work, version, node, node_license):
    # Assemble the APWorld directly. Do not overwrite any historical ZIP/reference.
    from build import WORLD_FILES, archive, tree
    world = work / "ootrr_remake.apworld"
    rows = list(tree(ROOT / "apworld"))
    rows.extend(("ootrr_remake/" + name, ROOT / "client/ootrr_triforce" / name) for name in WORLD_FILES)
    archive(world, rows)
    files = {"ootrr_remake.apworld": world, "native/archipelago.dll": ROOT / "prebuilt/windows-x64/archipelago.dll",
             "runtime/libzstd.dll": ROOT / "distribution/runtime/libzstd.dll",
             "runtime/LICENSE.txt": ROOT / "distribution/runtime/LICENSE.txt",
             "runtime/node/node.exe": node, "runtime/node/LICENSE": node_license,
             "SOURCES.txt": source_notice(work, version), "assets/icon.png": ROOT / "assets/icon.png"}
    files.update({"native/" + name: ROOT / "native" / name for name in HOST_FILES})
    files.update({name: ROOT / name for name in ("VERSION", "LICENSE", "NOTICE")})
    for path in (ROOT / "client/ootrr_triforce").iterdir():
        if path.is_file() and path.suffix != ".py":
            files["ootrr_triforce/" + path.name] = path
    files.update(licenses(work, node_license))
    digest = ",".join(map(str, hashlib.sha256(files["native/archipelago.dll"].read_bytes()).digest()))
    if files["native/ootrr_ap_digest.h"].read_bytes() != ("static const unsigned char ap_dll_sha16[32] = {" + digest + "};\n").encode("ascii"):
        raise ValueError("The native DLL and host verification header differ.")
    manifest = dict(schema=1, version=version, platform="windows-x64", node_version=NODE_VERSION,
                    python_version=".".join(map(str, sys.version_info[:3])), pyinstaller_version=PYINSTALLER_VERSION,
                    payload={name: sha(path) for name, path in sorted(files.items())})
    manifest_path = work / "app-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    files["app-manifest.json"] = manifest_path
    return files, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", type=Path, help="Use the official pinned Node.js executable already downloaded locally.")
    parser.add_argument("--node-license", type=Path, help="The unmodified LICENSE shipped with the pinned Node.js runtime.")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--work", type=Path, default=ROOT / "build/application")
    parser.add_argument("--plan", action="store_true", help="Prepare/verify resources without freezing the application.")
    args = parser.parse_args()
    if sys.platform != "win32" or sysconfig.get_platform() != "win-amd64":
        parser.error("Build the standalone Windows x64 app using Windows x64 Python.")
    if importlib.metadata.version("pyinstaller") != PYINSTALLER_VERSION:
        parser.error("Install the pinned build dependencies from requirements-app.txt.")
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    try:
        windows_version(version)
    except ValueError as error:
        parser.error(str(error))
    args.work = args.work.resolve()
    if not args.work.is_relative_to((ROOT / "build").resolve()):
        parser.error("The build workspace must be inside build/.")
    args.work.mkdir(parents=True, exist_ok=True)
    name = "OOT-Remake-Archipelago-" + version
    version_file = write_version_info(args.work, version, name)
    node, node_license = pinned_node(args.node, args.node_license)
    files, manifest = payload(args.work, version, node, node_license)
    if args.plan:
        print(json.dumps(dict(result="PLAN", version=version, payload_files=len(files),
                              node_sha256=sha(node), manifest=str(args.work / "app-manifest.json"),
                              version_resource=str(version_file))))
        return
    required = ("app_window.py", "app_runtime.py", "install_service.py")
    if any(not (ROOT / "client/ootrr_triforce" / name).is_file() for name in required):
        parser.error("The application UI and installation service must be present before freezing.")
    from PIL import Image
    icon = args.work / "application.ico"
    with Image.open(ROOT / "assets/icon.png") as image:
        image.save(icon, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    command = freezer_command(name, args.work, args.output, icon, version_file)
    for package in PACKAGES:
        command.extend(("--collect-submodules", package))
    # PyInstaller's CLI destination selects a folder, not the target filename.
    # Stage renamed license files explicitly so their names and manifest agree.
    staged_files = {}
    for name, path in files.items():
        target = args.work / "payload" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        staged_files[name] = target
    for name, path in sorted(staged_files.items()):
        destination = Path(name).parent.as_posix()
        switch = "--add-binary" if Path(name).suffix.lower() in (".dll", ".exe") else "--add-data"
        command.extend((switch, str(path.resolve()) + ":" + destination))
    command.append(str(ROOT / "client/app.py"))
    environment = dict(os.environ, PYINSTALLER_CONFIG_DIR=str(args.work / "cache"))
    subprocess.run(command, cwd=ROOT, env=environment, check=True)
    app = args.output.resolve() / ("OOT-Remake-Archipelago-" + version + ".exe")
    report = dict(result="PASS", artifact=app.name, sha256=sha(app), bytes=app.stat().st_size,
                  version=version, payload=manifest["payload"], console=False, onefile=True)
    (args.work / "build-result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("result", "artifact", "sha256", "bytes", "version")}))


if __name__ == "__main__":
    main()
