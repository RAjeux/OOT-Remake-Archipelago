"""Build one-time AP shelves using OOTRR's shop actor factory and native prices."""
from .i18n import tr
import json
from pathlib import Path

from .catalog import SHOP_CHECKS
from .engine import run_engine


def shop_records(roster, settings):
    from oot_rando.patching import ap_item
    prices = settings.get("shop_prices", {})
    records = []
    for name in sorted(set(roster).intersection(SHOP_CHECKS)):
        row = roster[name]
        if isinstance(row, dict):
            if row.get("local"):
                raise ValueError(tr("This test room reserves Kokiri purchases for other players' items."))
            item, player = row["item"], row["player"]
        else:
            item, player = row
        price = prices.get(name)
        if not isinstance(price, int) or isinstance(price, bool) or not 1 <= price <= 999:
            raise ValueError(tr('Missing or invalid OOTRR price for ') + name)
        metadata = SHOP_CHECKS[name]
        label = ap_item.ap_item(json.dumps([name, item, player], ensure_ascii=False))
        records.append(dict(name=name, actor=ap_item.ap_actor(label), slot=metadata["slot"],
                            price=price, flag_name=metadata["flag_name"],
                            counters=list(metadata["counters"]), keepers=list(metadata["keepers"]),
                            bancs=list(metadata["bancs"])))
    if settings.get("kokiri_shop_checks") and len(records) != len(SHOP_CHECKS):
        raise ValueError(tr('The room did not provide all eight Kokiri shop rewards.'))
    return records


def prepare_shops(romfs, mod, roster, settings):
    """Called inside the visual staging transaction, before its atomic publish."""
    if not settings.get("kokiri_shop_checks"):
        return {}
    from .shop_events import prepare_shop_events
    records = shop_records(roster, settings)
    if Path(mod).name != "romfs" or Path(mod).parent.name != "Archipelago":
        raise ValueError(tr('The shop staging folder is not an Archipelago mod.'))
    print(tr('Preparing the eight Archipelago purchases in Kokiri Shop…'), flush=True)
    # Node's WASI host on Windows cannot implement fd_readdir. Pass the real
    # archive names while Python can enumerate them, keeping Rust's staged I/O.
    messages = sorted({path.relative_to(home).as_posix() for home in (Path(romfs), Path(mod))
                       for path in (home / "Mals").glob("*.Product.110.sarc.zs") if path.is_file()})
    if not messages:
        raise ValueError(tr('Shop text archives were not found in Mals.'))
    print(run_engine("shops", {"shops": records, "messages": messages}, romfs, mod).strip(), flush=True)
    return prepare_shop_events(romfs, mod, records)
