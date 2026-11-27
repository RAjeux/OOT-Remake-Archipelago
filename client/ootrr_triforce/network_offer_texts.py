"""Keep one-time scrub offers consistent with the final Archipelago reward.

The native generator chooses the sale's price and conversation. Archipelago
only changes its item-name span; the native voice, price variable, questions,
answers, payment and handover remain in their original event flow.
"""
import json
from pathlib import Path

from .catalog import GAME, LOCATION_IDS


MESSAGE_FILE = "EventFlowMsg/Enemy_Event.msbt"
MESSAGE_GROUP = "EventFlowMsg/Enemy_Event"
TEMPLATE = "Enemy_Scrub_Business_Heart_01"
REST = "System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs"
SCRUB_KINDS = frozenset({"scrub_sale", "scrub_menu"})
COLOR_START = bytes.fromhex("0e0000030002000000")
COLOR_END = bytes.fromhex("0e000003000200ffff")


def offer_label(record):
    return "OOTRR_APOffer_" + str(LOCATION_IDS[record["name"]])


def offer_parameters(record, parameters):
    """Retarget only offer-message arguments, before native entries are copied."""
    if record.get("metadata", {}).get("native_kind") not in SCRUB_KINDS:
        return parameters
    selected = {key for key in ("SellerMessageId", "SaleMsg") if key in parameters}
    if not selected:
        raise ValueError("The native scrub sale has no offer message: " + record["name"])
    result = dict(parameters)
    for key in selected:
        result[key] = MESSAGE_GROUP + ":" + offer_label(record)
    return result


def _replace_name(template, name):
    """Replace the first authored colored span; never parse user text as tags."""
    encoded = name.encode("utf-8")
    if not encoded or any(code in encoded for code in (0, 14, 15)):
        raise ValueError("Invalid Archipelago offer name.")
    start = template.find(COLOR_START)
    end = template.find(COLOR_END, start + len(COLOR_START))
    if start < 0 or end < 0:
        raise ValueError("The native scrub offer has no item-name span.")
    start += len(COLOR_START)
    return template[:start] + encoded + template[end:]


def patch_message_archive(raw, records, roster, language, *, hints):
    """Add room-specific offers while retaining every other message verbatim."""
    from oot_rando.formats.byml_codec import build_sarc
    from oot_rando.formats.inspect_resources import sarc
    from oot_rando.formats.msbt import dump, load
    from .item_names import item_name

    archive = sarc(raw)
    if MESSAGE_FILE not in archive:
        raise ValueError("The game text archive has no native scrub offers.")
    messages = load(archive[MESSAGE_FILE])
    template = messages.get(TEMPLATE)
    if template is None:
        raise ValueError("The native scrub offer template is missing.")
    french = language.lower().endswith("fr")
    changed = False
    for record in records:
        if hints:
            reward = roster[record["name"]]
            owning_game = GAME if reward["local"] else reward.get("game", "")
            name = item_name(reward["item"], language, game=owning_game)
            name += " (" + reward["player"] + ")"
        else:
            name = "Objet myst\u00e8re" if french else "Mystery Item"
        label, content = offer_label(record), _replace_name(template, name)
        if messages.get(label) == content:
            continue
        if label not in messages.labels:
            messages.add(label, "")
        messages.texts[messages.labels[label]] = content
        changed = True
    if not changed:
        return raw
    archive[MESSAGE_FILE] = dump(messages)
    return build_sarc(archive)


def prepare_offer_texts(romfs, mod, roster, settings):
    """Run after localization, only for a new native-network room schema."""
    if settings.get("network_sources_schema") not in (1, 2):
        return {}
    from oot_rando.game.resource_allocations import grow_resources
    from .engine import run_engine
    from .mod_codec import Codec
    from .network_rewards import source_records

    records = [record for record in source_records(roster, settings)
               if record["metadata"].get("native_kind") in SCRUB_KINDS]
    if not records:
        return {}
    romfs, mod = Path(romfs), Path(mod)
    codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
    def source(path):
        staged = mod / path
        return (staged if staged.is_file() else romfs / path).read_bytes()

    decoded = json.loads(run_engine("settings", {"settings": settings.get("_seed_settings") or {}}))
    hints = decoded["settings"]["scrub_hint_text"]
    if type(hints) is not bool:
        raise ValueError("The native scrub hint setting is invalid.")
    archives = sorted({path.relative_to(home).as_posix() for home in (romfs, mod)
                       for path in (home / "Mals").glob("*.Product.110.sarc.zs") if path.is_file()})
    if not archives:
        raise ValueError("Game text archives were not found in Mals.")
    changed, growths = {}, {}
    for path in archives:
        frame = source(path)
        before = codec.decode(frame)
        language = Path(path).name.split(".", 1)[0]
        after = patch_message_archive(before, records, roster, language, hints=hints)
        if after != before:
            changed[path] = codec.encode(after, frame)
            growths[path] = max(0, len(after) - len(before))
    if not changed:
        return {"offers": len(records), "archives": 0}
    frame = source(REST)
    table, allocations = grow_resources(codec.decode(frame), growths)
    changed[REST] = codec.encode(table, frame)
    for path, frame in changed.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(frame)
    return {"offers": len(records), "archives": len(changed) - 1, "allocations": allocations}
