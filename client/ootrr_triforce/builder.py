"""Reject external builders whose seed fields and location research can differ."""
import hashlib
import json
import subprocess

from .i18n import tr

# Semantic fields from the official portable 0.8.1 settings-dump. Labels and
# tooltip wording do not change the wire format and are deliberately excluded.
SCHEMA_SHA256 = "6164600a2ef69d2796908e285aaddf18bbf08ffaf578f7d94019055289edc94d"


def schema_matches(schema):
    try:
        if (not isinstance(schema, dict) or type(schema.get("schema_version")) is not int
                or schema["schema_version"] != 1 or schema.get("string_prefix", "OOTRR1-") != "OOTRR1-"
                or not isinstance(schema.get("settings"), list) or len(schema["settings"]) != 118):
            return False
        rows = []
        for record in schema["settings"]:
            row = {key: record.get(key) for key in ("id", "num", "kind", "default", "min", "max", "step")}
            row["choices"] = [choice["id"] for choice in record.get("choices", [])]
            rows.append(row)
        raw = json.dumps(sorted(rows, key=lambda row: row["id"]), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest() == SCHEMA_SHA256
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def validate_builder(executable):
    """Run a read-only probe before giving a portable builder a bound seed."""
    message = tr("Use the OOTRR portable 0.8.1 builder. Other versions can change native location identities.")
    try:
        result = subprocess.run([str(executable), "settings-dump", "--compact"],
                                capture_output=True, text=True, encoding="utf-8", timeout=20, check=True)
        schema = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ValueError(message) from exc
    if not schema_matches(schema):
        raise ValueError(message)
