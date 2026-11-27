"""Stable room/save identity for historical seeds and versioned access graphs."""
import hashlib
import json

from .master_sword import token_material


def _stable(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def token(room, player, seed_checksum, shuffle_master_sword=False, *, features=None, access_logic=None):
    base = token_material(room, player, seed_checksum, shuffle_master_sword)
    if features is not None or access_logic is not None:
        graph = (hashlib.sha256(_stable(access_logic).encode("utf-8")).hexdigest()
                 if access_logic is not None else None)
        envelope = dict(schema=1, features=features, access_logic_sha256=graph)
        base += "/versioned-access/" + _stable(envelope)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()
