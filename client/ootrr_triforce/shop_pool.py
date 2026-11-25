"""Select shuffled stock for new rooms and preserve historical shop selections.

Schema-1 network rooms include all randomized shelves. Older player files
retain either their rolled special deals or their eight Kokiri purchases.
"""
from .catalog import LEGACY_SHOP_CHECKS, SHOP_CHECKS
from .i18n import tr
from .network_catalog import SHOP_MODE as NETWORK_SHOP_MODE

SHOP_CHECK_MODE = "special_deals"


def shop_checks(seed, *, mode=SHOP_CHECK_MODE, legacy=False):
    if type(legacy) is not bool:
        raise ValueError(tr("Invalid Archipelago shop mode."))
    shops = seed.get("shops", {})
    if not isinstance(shops, dict):
        raise ValueError(tr("Invalid native shop reward list."))
    if mode is None:
        selected = LEGACY_SHOP_CHECKS if legacy else frozenset()
        if not selected <= shops.keys():
            raise ValueError(tr("The seed does not contain all eight Kokiri purchases."))
    elif mode in (SHOP_CHECK_MODE, NETWORK_SHOP_MODE) and not legacy:
        if shops and set(shops) != set(SHOP_CHECKS):
            raise ValueError(tr("The native shop catalogue is incomplete."))
        selected = set()
        for name, row in shops.items():
            if not isinstance(row, dict) or type(row.get("deal", False)) is not bool:
                raise ValueError(tr("Invalid native shop reward list."))
            if mode == NETWORK_SHOP_MODE or row.get("deal", False):
                selected.add(name)
    else:
        raise ValueError(tr("Invalid Archipelago shop mode."))
    for name in selected:
        row = shops[name]
        if (not isinstance(row, dict) or not isinstance(row.get("item"), str)
                or not row["item"] or type(row.get("price")) is not int
                or not 1 <= row["price"] <= 999):
            raise ValueError(tr("Invalid native shop reward list."))
    return frozenset(selected)


def manifest_shop_checks(data):
    """Reject added, missing, repeated or non-deal checks in a new player file."""
    mode = data.get("shop_check_mode")
    selected = shop_checks(data["seed_file"], mode=mode,
                           legacy=data.get("kokiri_shop_checks", False))
    if mode is None:
        if "shop_checks" in data:
            raise ValueError(tr("Invalid Archipelago shop mode."))
        return selected
    names = data.get("shop_checks")
    if (not isinstance(names, list) or any(not isinstance(name, str) for name in names)
            or len(names) != len(set(names)) or set(names) != selected
            or data.get("foreign_only_shops", False) is not False):
        raise ValueError(tr("The Archipelago shop selection does not match the native deals."))
    return selected
