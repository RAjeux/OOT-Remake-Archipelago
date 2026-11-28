"""Keep a shop's AP selection identity separate from its displayed native item.

The native shop writes ActorNameRef into Shop_SelectItemName. Using the
displayed item's identity bypasses the location-bound AP capacity/grant/commit
callbacks. Native names and descriptions already have localized AP aliases;
the visual model, price, pouch routing and purchase sequence stay unchanged.
"""
import re
from pathlib import Path

from .i18n import tr

ACTORS = "RSDB/ActorInfo.Product.111.rstbl.byml.zs"
REST = "System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs"


def _invalid():
    return ValueError(tr("Invalid Archipelago shop identity."))


def _path(reference):
    if not isinstance(reference, str):
        raise _invalid()
    path = reference.removeprefix("?").removeprefix("Work/")
    return path.removesuffix(".gyml") + ".bgyml" if path.endswith(".gyml") else path


def _component(files, actor, key):
    """Read native inheritance without flattening or modifying that actor."""
    from oot_rando.formats import byml_codec as by
    path, seen = "Actor/" + actor + ".engine__actor__ActorParam.bgyml", set()
    while path not in seen:
        seen.add(path)
        if path not in files:
            raise _invalid()
        root = by.load(files[path])["root"]
        if key in root.get("Components", {}):
            return root["Components"][key]
        if not root.get("$parent"):
            break
        path = _path(root["$parent"])
    raise _invalid()


def _identity(reference):
    if not isinstance(reference, str):
        raise _invalid()
    match = re.fullmatch(r"\?ActorSystem/ActorName/([A-Za-z0-9_]+)\.engine__actor__ActorName\.bgyml", reference)
    if match is None:
        raise _invalid()
    return match[1]


def repair_shelf_pack(raw, *, shelf, ap_actor, native_reference, ap_reference):
    """Change only the exact known display-to-AP identity of one wrapper."""
    from oot_rando.formats import byml_codec as by
    from oot_rando.formats.inspect_resources import sarc
    if (not re.fullmatch(r"Item_AP_[0-9a-f]{12}", ap_actor)
            or not re.fullmatch(r"Shop_OOTRR_" + re.escape(ap_actor) + r"_[1-9][0-9]{0,2}", shelf)
            or _identity(ap_reference) != ap_actor):
        raise _invalid()
    _identity(native_reference)
    files = sarc(raw)
    path = "Actor/" + shelf + ".engine__actor__ActorParam.bgyml"
    if path not in files:
        raise _invalid()
    document = by.load(files[path])
    root = document["root"]
    components = root.get("Components", {})
    if (root.get("$parent") != "Work/Actor/Shop_Item_Base.engine__actor__ActorParam.gyml"
            or components.get("PouchContentRef") != "?Component/PouchContentParam/" + shelf + ".game__component__PouchContentParam.bgyml"
            or components.get("GameParameterTableRef") != "?GameParameter/GameParameterTable/" + shelf + ".engine__actor__GameParameterTable.bgyml"):
        raise _invalid()
    current = components.get("ActorNameRef")
    if current not in (native_reference, ap_reference):
        raise _invalid()
    if current == ap_reference:
        return raw, 0, current
    components["ActorNameRef"] = ap_reference
    updated = by.dump(document)
    growth = max(0, len(updated) - len(files[path]))
    files[path] = updated
    return by.build_sarc(files), growth, current


def prepare_shop_identities(romfs, mod, records):
    """Validate every local shelf before writing staged packs/registry budgets.

    A repeated pass is byte-idempotent. Foreign shelves retain their existing
    AP identity. No saved data, inventory or location history is rewritten.
    """
    from .shop_events import _records
    records = [row for row in _records(records) if "local_item" in row]
    if not records:
        return {"shops": 0, "written": 0}
    from .mod_codec import Codec
    from oot_rando.formats import byml_codec as by
    from oot_rando.formats.inspect_resources import sarc
    from oot_rando.game.resource_allocations import grow_resources
    romfs, mod = Path(romfs), Path(mod)
    if mod.name != "romfs" or mod.parent.name != "Archipelago":
        raise _invalid()
    codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())

    def frame(path):
        target = mod / path
        return (target if target.is_file() else romfs / path).read_bytes()

    def read(path):
        return codec.decode(frame(path))

    actor_frame = frame(ACTORS)
    actor_raw = codec.decode(actor_frame)
    actor_table = by.load(actor_raw)
    rows = {row["__RowId"]: row for row in actor_table["root"]}
    if len(rows) != len(actor_table["root"]):
        raise _invalid()
    outputs, growth, changed = {}, {}, 0
    for record in records:
        ap_actor, native = record["actor"], record["native_actor"]
        if not re.fullmatch(r"Item_AP_[0-9a-f]{12}", ap_actor):
            raise _invalid()
        shelf = "Shop_OOTRR_" + ap_actor + "_" + str(record["price"])
        if not all(actor in rows for actor in (ap_actor, native, shelf)):
            raise _invalid()
        ap_files = sarc(read("Pack/Actor/" + ap_actor + ".pack.zs"))
        native_files = sarc(codec.decode((romfs / ("Pack/Actor/" + native + ".pack.zs")).read_bytes()))
        ap_ref = _component(ap_files, ap_actor, "ActorNameRef")
        native_ref = _component(native_files, native, "ActorNameRef")
        if (_identity(ap_ref) != ap_actor or rows[ap_actor].get("ActorName") != ap_actor
                or _identity(native_ref) != rows[native].get("ActorName")):
            raise _invalid()
        path = "Pack/Actor/" + shelf + ".pack.zs"
        original_frame = frame(path)
        before = codec.decode(original_frame)
        after, inner_growth, previous_ref = repair_shelf_pack(before, shelf=shelf, ap_actor=ap_actor,
            native_reference=native_ref, ap_reference=ap_ref)
        # A pack/registry disagreement is not a known intact constructor output.
        if rows[shelf].get("ActorName") != _identity(previous_ref):
            raise _invalid()
        if after == before:
            continue
        changed += 1
        rows[shelf]["ActorName"] = ap_actor
        outputs[path] = (after, original_frame)
        growth[path] = max(0, len(after) - len(before))
        growth["Actor/" + shelf + ".engine__actor__ActorParam.bgyml"] = inner_growth
    if not changed:
        return {"shops": 0, "written": 0}
    actor_after = by.dump(actor_table)
    outputs[ACTORS] = (actor_after, actor_frame)
    growth[ACTORS] = max(0, len(actor_after) - len(actor_raw))
    rest_frame = frame(REST)
    rest, _ = grow_resources(codec.decode(rest_frame), growth)
    outputs[REST] = (rest, rest_frame)
    encoded = {path: codec.encode(raw, template) for path, (raw, template) in outputs.items()}
    for path, raw in encoded.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    return {"shops": changed, "written": len(encoded)}
