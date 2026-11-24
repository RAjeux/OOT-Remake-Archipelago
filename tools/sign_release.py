"""Provision a protected publisher key or sign an existing release checksum list.

Only the public verification key belongs in source control. Private key storage
is outside the repository, encrypted with the current Windows account's DPAPI
and restricted to that account. No private key material is printed.
"""
import argparse
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_MODULE = ROOT / "client/ootrr_triforce/update_key.py"
DEFAULT_KEY_DIR = Path.home() / ".codex/secrets/ootrr-release-signing"
PRIVATE_FILE = "publisher-key.dpapi.json"


def _crypto():
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
    except ImportError:
        raise RuntimeError("Install requirements-publisher.txt to use the signing tool.") from None
    return Ed25519PrivateKey, serialization


def _outside_repository(directory):
    directory = Path(directory).expanduser().resolve()
    if directory == ROOT or ROOT in directory.parents:
        raise ValueError("Publisher private keys must be stored outside the repository.")
    return directory


def _restrict(directory):
    if os.name != "nt":
        raise RuntimeError("Local key provisioning requires Windows DPAPI.")
    whoami = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/whoami.exe"
    rows = list(csv.reader(io.StringIO(subprocess.check_output(
        [str(whoami), "/user", "/fo", "csv", "/nh"], text=True, encoding="utf-8"))))
    sid = rows[0][-1].strip() if rows and rows[0] else ""
    if not re.fullmatch(r"S-\d+(?:-\d+)+", sid):
        raise RuntimeError("The current account SID could not be determined.")
    subprocess.run(["icacls", str(directory), "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F"],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   creationflags=subprocess.CREATE_NO_WINDOW)


def _load(directory):
    directory = _outside_repository(directory)
    path = directory / PRIVATE_FILE
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("format") != "ootrr-ed25519-dpapi-v1" or os.name != "nt":
        raise RuntimeError("This publisher key requires its original Windows account.")
    sys.path.insert(0, str(ROOT / "client"))
    from ootrr_triforce.connection_control import _unprotect_secret
    raw = base64.b64decode(_unprotect_secret(value["protected_key"]), validate=True)
    key_class, _ = _crypto()
    if len(raw) != 32:
        raise RuntimeError("Invalid publisher key.")
    return key_class.from_private_bytes(raw)


def provision(directory=DEFAULT_KEY_DIR, public_module=PUBLIC_MODULE):
    directory = _outside_repository(directory)
    directory.mkdir(parents=True, exist_ok=True)
    _restrict(directory)
    path = directory / PRIVATE_FILE
    reused = path.exists()
    key_class, serialization = _crypto()
    if reused:
        key = _load(directory)
    else:
        key = key_class.generate()
        raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                serialization.NoEncryption())
        sys.path.insert(0, str(ROOT / "client"))
        from ootrr_triforce.native_setup import protect_password
        value = {"format": "ootrr-ed25519-dpapi-v1",
                 "protected_key": protect_password(base64.b64encode(raw).decode("ascii"))}
        # Exclusive creation prevents silently replacing an established key.
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = hashlib.sha256(public).hexdigest()[:16]
    content = ('"""Publisher Ed25519 verification key; contains no private signing material."""\n'
               f'PUBLIC_KEY_HEX = "{public.hex()}"\n'
               f'KEY_ID = "{key_id}"\n')
    public_module = Path(public_module)
    if public_module.exists() and public_module.read_text(encoding="utf-8") != content:
        raise RuntimeError("The checked-in public key differs; key rotation requires an explicit migration.")
    public_module.parent.mkdir(parents=True, exist_ok=True)
    if not public_module.exists():
        with public_module.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
    return {"key_id": key_id, "protected": True, "reused": reused}


def sign(checksums, directory=DEFAULT_KEY_DIR, public_module=PUBLIC_MODULE):
    checksums = Path(checksums)
    raw = checksums.read_bytes()
    sys.path.insert(0, str(ROOT / "client"))
    from ootrr_triforce.update_service import _checksum
    key = _load(directory)
    _, serialization = _crypto()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    module = Path(public_module).read_text(encoding="utf-8")
    expected = re.search(r'^PUBLIC_KEY_HEX = "([a-f0-9]{64})"$', module, re.M)
    if expected is None or public.hex() != expected.group(1):
        raise RuntimeError("The signing key does not match the application's verification key.")
    names = []
    for line in raw.decode("utf-8").splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"[a-fA-F0-9]{64} [ *](.+)", line)
        if match is None:
            raise ValueError("Invalid release checksum list.")
        name = match.group(1)
        digest = _checksum(raw, name)
        source = checksums.parent / name
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError("A release file does not match its checksum: " + name)
        names.append(name)
    if not names:
        raise ValueError("Cannot sign an empty release checksum list.")
    signature = key.sign(raw)
    from ootrr_full.ed25519 import verify
    if not verify(public, raw, signature):
        raise RuntimeError("The signature does not pass the player's verifier.")
    target = checksums.with_name(checksums.name + ".sig")
    if target.exists():
        if target.read_bytes() != signature.hex().encode("ascii") + b"\n":
            raise RuntimeError("A different release signature already exists.")
    else:
        with target.open("xb") as stream:
            stream.write(signature.hex().encode("ascii") + b"\n")
    return {"key_id": hashlib.sha256(public).hexdigest()[:16], "signed_files": len(names),
            "signature_sha256": hashlib.sha256(target.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("provision", "sign"))
    parser.add_argument("checksums", nargs="?", type=Path)
    parser.add_argument("--key-dir", type=Path, default=DEFAULT_KEY_DIR)
    parser.add_argument("--public-module", type=Path, default=PUBLIC_MODULE)
    args = parser.parse_args()
    if args.command == "provision":
        result = provision(args.key_dir, args.public_module)
    else:
        if args.checksums is None:
            parser.error("sign requires the SHA256SUMS.txt path")
        result = sign(args.checksums, args.key_dir, args.public_module)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
