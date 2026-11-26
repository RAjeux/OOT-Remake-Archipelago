"""Run real settings/catalogue tests against an explicitly built WASM module.

The selected module is copied into a temporary resource root. The checked-in
engine, installed APWorlds, game data and user profiles are never replaced.
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, type=Path, help="Freshly built ootrr_ap.wasm.")
    parser.add_argument("--node", help="Node.js 22 or 24 executable; otherwise use OOTRR_NODE or PATH.")
    args = parser.parse_args()
    selected = args.engine.resolve()
    if not selected.is_file() or selected.read_bytes()[:4] != b"\0asm":
        parser.error("Choose a compiled WebAssembly module.")
    node = args.node or os.environ.get("OOTRR_NODE") or shutil.which("node")
    if not node:
        parser.error("Install Node.js 22 or 24, or pass --node.")
    sys.path.insert(0, str(ROOT / "client"))
    sys.path.insert(0, str(ROOT / "tests"))
    from ootrr_triforce import engine
    packaged = ROOT / "client/ootrr_triforce/engine.wasm"
    before = hashlib.sha256(packaged.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="ap-built-engine-") as temporary:
        resources = Path(temporary)
        shutil.copyfile(selected, resources / "engine.wasm")
        shutil.copyfile(ROOT / "client/ootrr_triforce/engine.cjs", resources / "engine.cjs")
        # Replace this module's resource provider only, not importlib.resources
        # globally: the trusted settings and source catalogue stay unchanged.
        with patch.object(engine, "resources", SimpleNamespace(files=lambda _package: resources)), \
                patch.dict(os.environ, {"OOTRR_NODE": str(node)}):
            suite = unittest.defaultTestLoader.loadTestsFromNames(("test_settings_engine", "test_network_catalog"))
            result = unittest.TextTestRunner(verbosity=2).run(suite)
    assert hashlib.sha256(packaged.read_bytes()).hexdigest() == before, "The packaged engine must remain untouched."
    print("Built engine SHA-256:", hashlib.sha256(selected.read_bytes()).hexdigest())
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
