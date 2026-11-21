import os
from pathlib import Path
import sys


def server_command():
    if os.environ.get("AP_SERVER"):
        return [os.environ["AP_SERVER"]]
    base = os.environ.get("AP_SOURCE")
    if base and (Path(base)/"MultiServer.py").is_file():
        return [sys.executable, str(Path(base).resolve()/"MultiServer.py")]
    raise RuntimeError("Définis AP_SERVER avec le chemin de ton serveur Archipelago ou AP_SOURCE avec le dépôt installé.")


def triforce_root():
    base = os.environ.get("TRIFORCE_SOURCE") or str(Path(__file__).resolve().parents[1] / "references" / "triforce")
    if not base or not (Path(base)/"host/hos_main.c").is_file():
        raise RuntimeError("Définis TRIFORCE_SOURCE avec le dossier de sources de Triforce.")
    return Path(base)
