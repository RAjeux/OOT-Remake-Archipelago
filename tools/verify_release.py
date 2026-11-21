"""Verify a versioned release against its committed SHA-256 reference."""
import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
CONTAINERS = ("ootrr_remake.apworld", "Client-OOT-Remake.pyz", "sources/Sources-moteur.zip")


def digests(archive):
    names = archive.namelist()
    if len(names) != len(set(names)):
        raise ValueError("Duplicate ZIP members.")
    return {name: hashlib.sha256(archive.read(name)).hexdigest() for name in sorted(names)}


def inspect(release):
    with ZipFile(release) as outer:
        result = {"fichiers": digests(outer)}
        for name in CONTAINERS:
            with ZipFile(BytesIO(outer.read(name))) as child:
                result[name] = digests(child)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=(ROOT / "VERSION").read_text(encoding="utf-8").strip())
    parser.add_argument("--record-reference", action="store_true",
                        help="Record a new reference without overwriting an existing one.")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9.]+)?", args.version):
        parser.error("Invalid version.")
    reference = ROOT / f"tests/reference-{args.version}.json"
    current = inspect(ROOT / f"dist/Archipelago-OOT-Remake-{args.version}.zip")
    if args.record_reference:
        with reference.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(current, output, indent=1, ensure_ascii=False)
            output.write("\n")
        print(f"New reference recorded: {reference.name}")
        return
    if not reference.is_file():
        sys.exit(f"Missing reference: {reference.name}. Use --record-reference after validating this version.")
    expected = json.loads(reference.read_bytes())
    errors = []
    for context in sorted(set(current) | set(expected)):
        actual, original = current.get(context, {}), expected.get(context, {})
        for name in sorted(set(actual) | set(original)):
            # Compare nested contents independently of ZIP metadata/compression.
            if context == "fichiers" and name in CONTAINERS:
                continue
            if name not in actual or name not in original:
                errors.append(f"{context} / {name} (presence)")
            elif actual[name] != original[name]:
                errors.append(f"{context} / {name} (content)")
    if errors:
        sys.exit("\n".join(errors))
    print(f"Release {args.version} matches its reference, including nested archives.")


if __name__ == "__main__":
    main()
