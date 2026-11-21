"""Assemble the APWorld, the Python zipapp and the complete Windows release."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZIP_DEFLATED, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist"
BUILD = ROOT / "build"
CLIENT = ROOT / "client"
NATIVE = ROOT / "native"
ENGINE = ROOT / "moteur" / "ootrr-ap"
DLL = ROOT / "prebuilt/windows-x64/archipelago.dll"
WORLD_FILES = ("catalog.py", "settings.py", "engine.py", "engine.cjs", "engine.wasm", "LICENSE", "NOTICE")
HOST_FILES = ("ootrr_archipelago.inc", "ootrr_ap_items.inc", "ootrr_ap_digest.h")
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
RELEASE = f"Archipelago-OOT-Remake-{VERSION}.zip"


def tree(root):
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if path.is_file() and not {"__pycache__", ".git", ".codex", ".claude", "target"}.intersection(rel.parts) and path.suffix != ".pyc":
            yield rel.as_posix(), path


def archive(dest, entries):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=dest.parent) as directory:
        tmp = Path(directory) / "package.zip"
        with ZipFile(tmp, "w", ZIP_DEFLATED) as z:
            for name, path in sorted(entries):
                info = ZipInfo(name, (2026, 11, 20, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                z.writestr(info, path.read_bytes(), compress_type=ZIP_DEFLATED)
        tmp.replace(dest)


def copy_file(path, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, dest)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--native", action="store_true", help="Recompile la DLL Windows x64 avec Go et un compilateur C.")
    ap.add_argument("--engine", action="store_true", help="Recompile le moteur Rust pour wasm32-wasip1.")
    ap.add_argument("--linux-test-lib", action="store_true", help="Compile la bibliothèque de test Linux avec Go et C.")
    args = ap.parse_args()
    BUILD.mkdir(exist_ok=True)
    if args.native:
        env = dict(os.environ, GOOS="windows", GOARCH="amd64", CGO_ENABLED="1")
        subprocess.run(["go", "build", "-mod=vendor", "-buildvcs=false", "-trimpath", "-ldflags=-s -w",
                        "-buildmode=c-shared", "-o", str(BUILD/"archipelago.dll"), "."], cwd=NATIVE, env=env, check=True)
        copy_file(BUILD/"archipelago.dll", DLL)
        subprocess.run([sys.executable, str(NATIVE/"write_digest.py"), str(DLL)], check=True)
    if args.linux_test_lib:
        if not sys.platform.startswith("linux"):
            ap.error("--linux-test-lib nécessite Linux. Sous Windows le test utilise la DLL du pack.")
        subprocess.run(["go", "build", "-mod=vendor", "-buildvcs=false", "-trimpath", "-buildmode=c-shared",
                        "-o", str(BUILD/"archipelago.so"), "."], cwd=NATIVE, env=dict(os.environ,CGO_ENABLED="1"), check=True)
    if args.engine:
        dest = BUILD / "cargo"
        # Dependency panic locations must not disclose the builder's home path.
        env = dict(os.environ)
        flags = env.get("CARGO_ENCODED_RUSTFLAGS", "\x1f".join(env.get("RUSTFLAGS", "").split()))
        env["CARGO_ENCODED_RUSTFLAGS"] = (flags + "\x1f" if flags else "") + f"--remap-path-prefix={ROOT}=/source"
        subprocess.run(["cargo", "build", "--release", "--locked", "--offline", "--target", "wasm32-wasip1",
                        "-p", "ootrr-core", "--bin", "ootrr_ap", "--target-dir", str(dest)], cwd=ENGINE, env=env, check=True)
        copy_file(dest/"wasm32-wasip1/release/ootrr_ap.wasm", CLIENT/"ootrr_triforce/engine.wasm")

    digest = ",".join(map(str, hashlib.sha256(DLL.read_bytes()).digest()))
    expected = ("static const unsigned char ap_dll_sha16[32] = {" + digest + "};\n").encode("ascii")
    if (NATIVE/"ootrr_ap_digest.h").read_bytes() != expected:
        raise SystemExit("La DLL et l’en-tête de vérification diffèrent. Relance la compilation avec --native.")

    world = OUT/"ootrr_remake.apworld"
    app = OUT/"Client-OOT-Remake.pyz"
    src = OUT/"sources/Sources-moteur.zip"
    world_entries = list(tree(ROOT/"apworld"))
    world_entries.extend(("ootrr_remake/"+n, CLIENT/"ootrr_triforce"/n) for n in WORLD_FILES)
    archive(world, world_entries)
    archive(app, tree(CLIENT))
    archive(src, tree(ROOT/"moteur"))

    entries = [(p.relative_to(OUT).as_posix(),p) for p in (world,app,src)]
    install = [*tree(ROOT/"distribution"), ("native/archipelago.dll", DLL)]
    install.extend((name, ROOT/name) for name in ("LICENSE", "NOTICE", "VERSION"))
    install.extend(("exemples/"+name, path) for name, path in tree(ROOT/"exemples"))
    install.extend(("native/"+n,NATIVE/n) for n in HOST_FILES)
    install.extend(("sources/native/"+n,p) for n,p in tree(NATIVE))
    for name,path in install:
        copy_file(path, OUT/name)
        entries.append((name, OUT/name))
    archive(OUT/RELEASE, entries)
    print(OUT/RELEASE)


if __name__ == "__main__":
    main()
