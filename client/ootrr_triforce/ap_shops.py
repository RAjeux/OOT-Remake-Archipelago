"""Build one-time AP shelves using OOTRR's shop actor factory and native prices."""
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
                raise ValueError("Cette salle de test réserve les achats Kokiri aux objets des autres joueurs.")
            item, player = row["item"], row["player"]
        else:
            item, player = row
        price = prices.get(name)
        if not isinstance(price, int) or isinstance(price, bool) or not 1 <= price <= 999:
            raise ValueError("Prix OOTRR absent ou invalide pour " + name)
        metadata = SHOP_CHECKS[name]
        label = ap_item.ap_item(json.dumps([name, item, player], ensure_ascii=False))
        records.append(dict(name=name, actor=ap_item.ap_actor(label), slot=metadata["slot"],
                            price=price, flag_name=metadata["flag_name"],
                            counters=list(metadata["counters"]), keepers=list(metadata["keepers"]),
                            bancs=list(metadata["bancs"])))
    if settings.get("kokiri_shop_checks") and len(records) != len(SHOP_CHECKS):
        raise ValueError("La salle n’a pas fourni les huit récompenses de la boutique Kokiri.")
    return records


def prepare_shops(romfs, mod, roster, settings):
    """Called inside the visual staging transaction, before its atomic publish."""
    if not settings.get("kokiri_shop_checks"):
        return {}
    from .shop_events import prepare_shop_events
    records = shop_records(roster, settings)
    if Path(mod).name != "romfs" or Path(mod).parent.name != "Archipelago":
        raise ValueError("Le dossier de préparation des boutiques n’est pas un mod Archipelago.")
    print("Préparation des huit achats Archipelago de la boutique Kokiri…", flush=True)
    # Node's WASI host on Windows cannot implement fd_readdir. Pass the real
    # archive names while Python can enumerate them, keeping Rust's staged I/O.
    messages = sorted({path.relative_to(home).as_posix() for home in (Path(romfs), Path(mod))
                       for path in (home / "Mals").glob("*.Product.110.sarc.zs") if path.is_file()})
    if not messages:
        raise ValueError("Archives des textes de boutique introuvables dans Mals.")
    print(run_engine("shops", {"shops": records, "messages": messages}, romfs, mod).strip(), flush=True)
    return prepare_shop_events(romfs, mod, records)
