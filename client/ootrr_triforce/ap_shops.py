"""Build one-time AP shelves using OOTRR's shop actor factory and native prices."""
from .i18n import tr
import json
from pathlib import Path

from .catalog import ITEM_DATA, ITEM_IDS, LEGACY_SHOP_CHECKS, SHOP_CHECKS
from .engine import run_engine


def selected_shops(roster, settings):
    """Resolve the room's stock checks; old rooms keep their released selection."""
    actual = set(roster).intersection(SHOP_CHECKS)
    mode = settings.get("shop_check_mode")
    if mode in ("special_deals", "randomized_stock"):
        selected = settings.get("shop_checks")
        if (not isinstance(selected, (list, tuple))
                or any(not isinstance(name, str) or name not in SHOP_CHECKS for name in selected)
                or len(set(selected)) != len(selected) or set(selected) != actual):
            raise ValueError(tr('The room shop selection does not match its Archipelago rewards.'))
        return frozenset(selected)
    if mode is not None:
        raise ValueError(tr('Unsupported Archipelago shop mode.'))
    if settings.get("kokiri_shop_checks"):
        if actual != LEGACY_SHOP_CHECKS:
            raise ValueError(tr('The room did not provide all eight Kokiri shop rewards.'))
        return LEGACY_SHOP_CHECKS
    if actual:
        raise ValueError(tr('The room shop selection does not match its Archipelago rewards.'))
    return frozenset()


def shop_records(roster, settings):
    from oot_rando.patching import ap_item
    prices = settings.get("shop_prices", {})
    records = []
    for name in sorted(selected_shops(roster, settings)):
        row = roster[name]
        local_item = None
        if isinstance(row, dict):
            if row.get("local"):
                if settings.get("foreign_only_shops") and settings.get("shop_check_mode") is None:
                    raise ValueError(tr("This test room reserves Kokiri purchases for other players' items."))
                local_item = row["item"]
                if (not isinstance(local_item, str) or local_item not in ITEM_DATA
                        or row.get("item_id", ITEM_IDS[local_item]) != ITEM_IDS[local_item]):
                    raise ValueError(tr('Unknown local Archipelago item: ') + str(local_item))
            item, player = row["item"], row["player"]
        else:
            item, player = row
        price = prices.get(name)
        if not isinstance(price, int) or isinstance(price, bool) or not 1 <= price <= 999:
            raise ValueError(tr('Missing or invalid OOTRR price for ') + name)
        metadata = SHOP_CHECKS[name]
        label = ap_item.ap_item(json.dumps([name, item, player], ensure_ascii=False))
        record = dict(name=name, shop=metadata["shop"], actor=ap_item.ap_actor(label), slot=metadata["slot"],
                      price=price, flag_name=metadata["flag_name"],
                      counters=list(metadata["counters"]), keepers=list(metadata["keepers"]),
                      bancs=list(metadata["bancs"]))
        if local_item is not None:
            record.update(local_item=local_item, native_actor=ITEM_DATA[local_item]["actor"])
        records.append(record)
    return records


def prepare_shops(romfs, mod, roster, settings):
    """Called inside the visual staging transaction, before its atomic publish."""
    records = shop_records(roster, settings)
    if not records:
        return {}
    from .shop_events import prepare_shop_events
    if Path(mod).name != "romfs" or Path(mod).parent.name != "Archipelago":
        raise ValueError(tr('The shop staging folder is not an Archipelago mod.'))
    print(tr('Preparing Archipelago shop purchases...'), flush=True)
    # Node's WASI host on Windows cannot implement fd_readdir. Pass the real
    # archive names while Python can enumerate them, keeping Rust's staged I/O.
    messages = sorted({path.relative_to(home).as_posix() for home in (Path(romfs), Path(mod))
                       for path in (home / "Mals").glob("*.Product.110.sarc.zs") if path.is_file()})
    if not messages:
        raise ValueError(tr('Shop text archives were not found in Mals.'))
    print(run_engine("shops", {"shops": records, "messages": messages}, romfs, mod).strip(), flush=True)
    from .shop_identity import prepare_shop_identities
    prepare_shop_identities(romfs, mod, records)
    from .shop_poses import prepare_shop_poses
    prepare_shop_poses(romfs, mod, records)
    from .shop_layout import prepare_shop_layout
    prepare_shop_layout(romfs, mod, records)
    return prepare_shop_events(romfs, mod, records)
