"""Recognize prepared full mods that need a same-room resource update."""
import json
from pathlib import Path


def requires_reprepare(artifact, *, external=False):
    """Read-only capability check; historical OOTRR rooms keep their own path.

    An application update cannot replace AI/resource budgets already installed
    into a game. Repreparing the same player file preserves its token and save.
    """
    artifact = Path(artifact)
    path = artifact / 'manifest.json'
    try:
        if path.stat().st_size > 16 << 20:
            return True
        value = json.loads(path.read_bytes())
    except (OSError, ValueError, RecursionError):
        return (artifact / 'full-player.json').is_file()
    if not isinstance(value, dict):
        return (artifact / 'full-player.json').is_file()
    metadata = value.get('archipelago')
    full = (isinstance(metadata, dict) and metadata.get('generation_mode') == 'full_network'
            or (artifact / 'full-player.json').is_file())
    if not full:
        return False
    allocations = value.get('resource_allocations')
    if not isinstance(allocations, dict) or allocations.get('version') != 1:
        return True
    if external:
        readiness, life = value.get('external_readiness'), value.get('external_deathlink')
        return (not isinstance(readiness, dict) or readiness.get('version') != 2
                or not isinstance(life, dict) or life.get('version') != 1)
    return False
