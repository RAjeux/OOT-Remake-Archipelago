"""English source messages with a French catalogue and game-language discovery.

The game's language is authoritative. The host publishes language.json in the
room profile; setup can also inspect HOS_LANGUAGE and the game's language.txt.
The operating-system locale is deliberately never used.
"""
import json
import os
from pathlib import Path
from importlib import resources

_language = "en"
_french = json.loads(resources.files(__package__).joinpath("i18n_fr.json").read_text(encoding="utf-8"))
_GAME_CODES = frozenset(code.casefold() for code in (
    "en-US", "en-GB", "fr", "fr-CA", "de", "it", "es", "es-419", "pt-BR", "nl", "pl", "ru",
    "ja", "ko", "zh-Hans", "zh-Hant"))


def normalize_language(value):
    code = str(value or "").strip().replace("_", "-").casefold()
    return "fr" if code in {"fr", "fr-fr", "fr-ca", "eufr", "usfr"} else "en"


def get_language():
    return _language


def set_language(language):
    global _language
    _language = normalize_language(language)
    return _language


def tr(english_text, *, language=None, **values):
    text = _french.get(english_text, english_text) if normalize_language(
        get_language() if language is None else language) == "fr" else english_text
    return text.format(**values) if values else text


def profile_language(profile):
    """Read only the small language marker; never inspect session credentials."""
    if profile is None:
        return None
    try:
        path = Path(profile) / "language.json"
        if path.stat().st_size > 4096:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        language = value.get("language") if isinstance(value, dict) else None
        return language if language in {"en", "fr"} else None
    except (OSError, ValueError, TypeError):
        return None


def _language_file(path):
    try:
        if path.stat().st_size > 65536:
            return None
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            value = line.strip()
            if not value or value.startswith("#"):
                continue
            code = value.split()[0]
            if code.casefold() in _GAME_CODES:
                return normalize_language(code)
        return "en"
    except (OSError, UnicodeError):
        pass
    return None


def detect_language(profile=None, config=None, environ=None):
    """Use host language settings, then its last runtime marker, else English."""
    env = os.environ if environ is None else environ
    if "HOS_LANGUAGE" in env:
        code = str(env["HOS_LANGUAGE"]).split()[0] if str(env["HOS_LANGUAGE"]).split() else ""
        return normalize_language(code) if code.casefold() in _GAME_CODES else "en"
    config = config if isinstance(config, dict) else {}
    sources = [config]
    ports = config.get("ports", {})
    if isinstance(ports, dict) and isinstance(ports.get("nx2navi"), dict):
        sources.append(ports["nx2navi"])
    candidates = []
    for source in sources:
        for key in ("exe", "romfs", "mods", "mods_dir"):
            value = source.get(key)
            if not isinstance(value, (str, os.PathLike)) or not value:
                continue
            path = Path(value)
            parent = path.parent
            if key == "exe" and parent.name.casefold() == "bin":
                candidates.append(parent.parent / "language.txt")
            candidates.append(parent / "language.txt")
    for candidate in dict.fromkeys(candidates):
        language = _language_file(candidate)
        if language is not None:
            return language
    return profile_language(profile) or normalize_language(config.get("language", config.get("Language")))
