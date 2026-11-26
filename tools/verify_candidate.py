"""Check a development package against its current sources, not a release pin.

Published references are verified separately by verify_release.py on a release
tag. A contribution may change packaged code without changing VERSION or any
immutable reference.
"""
import argparse
import hashlib
from io import BytesIO
from pathlib import Path, PurePosixPath
import re
from zipfile import ZipFile

import build

ROOT = Path(__file__).resolve().parents[1]
CONTAINERS = ("ootrr_remake.apworld", "Client-OOT-Remake.pyz", "sources/Sources-moteur.zip")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def members(archive):
    rows = archive.infolist()
    names = [row.filename for row in rows]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate ZIP members.")
    for name in names:
        path = PurePosixPath(name)
        if (not name or "\\" in name or path.is_absolute() or ".." in path.parts
                or ":" in name or any(part in {".git", "__pycache__"} for part in path.parts)):
            raise ValueError("Unsafe package path: " + name)
    if len(rows) > 20000 or sum(row.file_size for row in rows) > 512 << 20:
        raise ValueError("Package exceeds validation limits.")
    return {name: digest(archive.read(name)) for name in names}


def source_hashes(rows):
    result = {}
    for name, path in rows:
        if name in result:
            raise ValueError("Duplicate source member: " + name)
        result[name] = digest(path.read_bytes())
    return result


def compare(actual, expected, context):
    errors = []
    for name in sorted(set(actual) | set(expected)):
        if name not in actual or name not in expected:
            errors.append(f"{context} / {name} (presence)")
        elif actual[name] != expected[name]:
            errors.append(f"{context} / {name} (stale or changed content)")
    if errors:
        raise ValueError("\n".join(errors))


def verify(root, artifact=None):
    root = Path(root).resolve()
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9.]+)?", version):
        raise ValueError("Invalid VERSION.")
    artifact = Path(artifact) if artifact else root / f"dist/Archipelago-OOT-Remake-{version}.zip"
    world = list(build.tree(root / "apworld"))
    world.extend(("ootrr_remake/" + name, root / "client/ootrr_triforce" / name) for name in build.WORLD_FILES)
    expected_nested = {
        CONTAINERS[0]: source_hashes(world),
        CONTAINERS[1]: source_hashes(build.tree(root / "client")),
        CONTAINERS[2]: source_hashes(build.tree(root / "moteur")),
    }
    native = root / "native"
    dll = root / "prebuilt/windows-x64/archipelago.dll"
    header = ("static const unsigned char ap_dll_sha16[32] = {" +
              ",".join(map(str, hashlib.sha256(dll.read_bytes()).digest())) + "};\n").encode("ascii")
    if (native / "ootrr_ap_digest.h").read_bytes() != header:
        raise ValueError("The native DLL and verification header differ.")
    outer = [*build.tree(root / "distribution"), ("native/archipelago.dll", dll)]
    outer.extend((name, root / name) for name in ("LICENSE", "NOTICE", "VERSION"))
    outer.extend(("examples/" + name, path) for name, path in build.tree(root / "examples"))
    outer.extend(("native/" + name, native / name) for name in build.HOST_FILES)
    outer.extend(("sources/native/" + name, path) for name, path in build.tree(native))
    expected_outer = source_hashes(outer)
    with ZipFile(artifact) as packaged:
        actual_outer = members(packaged)
        if not set(CONTAINERS) <= actual_outer.keys():
            raise ValueError("Missing package container.")
        for name, expected in expected_nested.items():
            with ZipFile(BytesIO(packaged.read(name))) as nested:
                actual = members(nested)
                if name == CONTAINERS[0] and {part.split("/")[0] for part in actual} != {"ootrr_remake"}:
                    raise ValueError("APWorld must contain only its single package directory.")
                compare(actual, expected, name)
            actual_outer.pop(name)
        compare(actual_outer, expected_outer, artifact.name)
    return version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path)
    args = parser.parse_args()
    version = verify(ROOT, args.artifact)
    print(f"Development candidate {version} matches current sources; release references were not changed.")


if __name__ == "__main__":
    main()
