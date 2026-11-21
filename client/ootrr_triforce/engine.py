from .i18n import tr
import json
import os
import shutil
import subprocess
import tempfile
from importlib import resources
from pathlib import Path


def run_engine(command, request, *paths):
    node = os.environ.get("OOTRR_NODE") or shutil.which("node")
    if not node:
        raise RuntimeError(tr('Install Node.js 22 or 24 on the machine running this step, or set OOTRR_NODE.'))
    with tempfile.TemporaryDirectory(prefix="ootrr-ap-") as temp:
        root = Path(temp)
        for file in ("engine.cjs", "engine.wasm"):
            (root / file).write_bytes(resources.files(__package__).joinpath(file).read_bytes())
        proc = subprocess.run([node, "--no-warnings", str(root / "engine.cjs"), str(root / "engine.wasm"),
                               command, *map(str, paths)], input=json.dumps(request).encode(),
                              capture_output=True, timeout=300)
        if proc.returncode:
            raise RuntimeError(proc.stderr.decode(errors="replace")[-3500:] or tr('The OOTRR engine failed.'))
        return proc.stdout.decode()
