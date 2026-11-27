"""Trusted identities for rewards selected by the existing OOTRR engine.

The generated catalogue describes possible sources, not enabled checks. A room
must provide exactly its engine-selected sources. Old player files do not use
this schema and retain their released flags and preparation path.
"""
import copy
import json
from importlib import resources

SCHEMA = 2
SHOP_MODE = "randomized_stock"
_document = json.loads(resources.files(__package__).joinpath("network_sources.json").read_text(encoding="utf-8"))
if _document.get("schema") != 1 or not isinstance(_document.get("sources"), dict):
    raise ValueError("Unsupported native source catalogue.")
LEGACY_SOURCES = _document["sources"]
_additional = json.loads(resources.files(__package__).joinpath("additional_sources.json").read_text(encoding="utf-8"))
if (_additional.get("schema") != SCHEMA or not isinstance(_additional.get("sources"), dict)
        or set(_additional["sources"]) & LEGACY_SOURCES.keys()):
    raise ValueError("Unsupported additional native source catalogue.")
ADDITIONAL_SOURCES = _additional["sources"]
ADDITIONAL_REWARDS = _additional["rewards"]
SOURCES = dict(LEGACY_SOURCES, **ADDITIONAL_SOURCES)
_identities = json.loads(resources.files(__package__).joinpath("network_ids.json").read_text(encoding="utf-8"))
if _identities.get("schema") != 1 or not isinstance(_identities.get("locations"), dict):
    raise ValueError("Unsupported native source identity registry.")
APPENDED_IDS = _identities["locations"]


def murmur3(text):
    """The game's unsigned MurmurHash3 x86_32, with its native zero seed."""
    raw = text.encode("utf-8")
    value = 0
    def rotate(n, bits):
        return ((n << bits) | (n >> (32 - bits))) & 0xffffffff
    def mix(n):
        return (rotate((n * 0xcc9e2d51) & 0xffffffff, 15) * 0x1b873593) & 0xffffffff
    for at in range(0, len(raw) - len(raw) % 4, 4):
        value = rotate(value ^ mix(int.from_bytes(raw[at:at + 4], "little")), 13)
        value = (value * 5 + 0xe6546b64) & 0xffffffff
    tail = raw[len(raw) - len(raw) % 4:]
    if tail:
        value ^= mix(int.from_bytes(tail, "little"))
    value ^= len(raw)
    value ^= value >> 16
    value = (value * 0x85ebca6b) & 0xffffffff
    value ^= value >> 13
    value = (value * 0xc2b2ae35) & 0xffffffff
    return value ^ (value >> 16)


def extend_ids(ids):
    """Append only: every identity shipped before this catalogue stays intact."""
    if (set(APPENDED_IDS) != SOURCES.keys() - ids.keys()
            or any(type(value) is not int or value <= max(ids.values()) for value in APPENDED_IDS.values())
            or len(set(APPENDED_IDS.values())) != len(APPENDED_IDS)):
        raise ValueError("Native sources need an append-only protocol identity registry.")
    ids.update(APPENDED_IDS)


def enabled(data):
    value = data.get("network_sources_schema")
    if value is None:
        if "network_sources" in data:
            raise ValueError("Native source metadata has no schema.")
        return False
    if type(value) is not int or value not in (1, SCHEMA):
        raise ValueError("Unsupported native source schema.")
    if value == 1 and data.get("additional_sources"):
        raise ValueError("Additional native sources require schema 2.")
    return True


def flag_name(name):
    from .catalog import LOCATION_IDS
    if name not in SOURCES:
        raise ValueError("Unknown native source: " + str(name))
    return "Archipelago.Source." + str(LOCATION_IDS[name])


def source_flags(name):
    return [murmur3(flag_name(name))]


def flag_names(name, *, network=False):
    from .catalog import CHESTS, SHOP_CHECKS, SKULL_CHECKS, TRADE_CHECKS
    from .master_sword import LOCATION, FLAG_NAME
    if name in CHESTS:
        return ["IsTreasureBoxOpen." + str(row["actor"]) for row in CHESTS[name]]
    if name in SHOP_CHECKS:
        return [SHOP_CHECKS[name]["flag_name"]]
    if name in TRADE_CHECKS:
        return [TRADE_CHECKS[name]["flag_name"]]
    if name == LOCATION:
        return [FLAG_NAME]
    if network and name in SOURCES:
        return [flag_name(name)]
    if name in SKULL_CHECKS:
        return [SKULL_CHECKS[name]["flag_name"]]
    raise ValueError("Unknown source completion flag: " + str(name))


def check_flags(name, *, network=False):
    return [murmur3(flag) for flag in flag_names(name, network=network)]


def _additional_reward(name, data):
    reward = ADDITIONAL_REWARDS[name]
    if not reward.startswith(("Map (", "Compass (")):
        return reward
    world = data.get("access_logic", {}).get("world", {})
    items = world.get("items", [])
    for entry in world.get("start", []):
        if (isinstance(entry, list) and len(entry) == 2
                and type(entry[0]) is int and 0 <= entry[0] < len(items)
                and type(entry[1]) is int and entry[1] > 0
                and items[entry[0]].get("name") == reward):
            return "Rupee (1)"
    return reward


def validate_sources(data):
    """Validate descriptors against packaged native data and exact seed rewards."""
    if not enabled(data):
        return {}
    rows = data.get("network_sources")
    if not isinstance(rows, dict):
        raise ValueError("Missing native source metadata.")
    seed = data["seed_file"]
    placements, shops = seed["placements"], seed.get("shops", {})
    expected = set(placements) | set(shops)
    if set(placements) & ADDITIONAL_SOURCES.keys():
        raise ValueError("Additional AP checks must not rewrite the compatible builder's native seed.")
    additions = data.get("additional_sources", [])
    if (not isinstance(additions, list) or any(not isinstance(name, str) for name in additions)
            or len(set(additions)) != len(additions) or not set(additions) <= ADDITIONAL_SOURCES.keys()
            or set(additions) & expected):
        raise ValueError("Invalid additional native source selection.")
    expected.update(additions)
    if set(rows) != expected:
        raise ValueError("Network sources do not match all randomized native rewards.")
    for name, row in rows.items():
        native = SOURCES.get(name)
        if native is None or not isinstance(row, dict):
            raise ValueError("Unknown native source: " + str(name))
        actual = dict(row)
        reward = actual.pop("generated_item", None)
        if name in shops:
            shop = shops[name]
            if (actual.pop("price", None) != shop["price"]
                    or type(row.get("deal")) is not bool
                    or type(shop.get("deal", False)) is not bool
                    or actual.pop("deal", None) != shop.get("deal", False)):
                raise ValueError("Native shop descriptor differs from its seed: " + name)
            expected_reward = shop["item"]
        elif name in additions:
            expected_reward = _additional_reward(name, data)
        else:
            expected_reward = placements[name]
        if actual != native or reward != expected_reward:
            raise ValueError("Native source descriptor differs from its seed: " + name)
    return copy.deepcopy(rows)


def callback_sources(roster, settings):
    """Sources needing the generic native get callback, rather than old adapters."""
    from .catalog import CHESTS, SHOP_CHECKS, TRADE_CHECKS
    if not enabled(settings):
        return {}
    rows = settings.get("network_sources")
    if not isinstance(rows, dict):
        raise ValueError("Missing native source metadata.")
    handled = set(CHESTS) | set(SHOP_CHECKS)
    if settings.get("adult_trade_shuffle"):
        handled.update(TRADE_CHECKS)
    return {name: rows[name] for name in sorted(set(roster) & rows.keys() - handled)}
