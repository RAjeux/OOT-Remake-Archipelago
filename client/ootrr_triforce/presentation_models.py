"""Native item models that can safely play the game's held-item animation.

Only the displayed actor changes. Inventory, pose queries, item windows and AP
acknowledgements always continue to use the real reward actor. Receipt aliases
are visual only. Chest proxies keep the native pouch guest performer, without
adding any saved flags, IsGet members, checks or custom event performers.
"""
import copy
import hashlib
from pathlib import Path

SHOW_ACTOR_ARGUMENT = "ArchipelagoShowActor"
TEMPLATE = "Item_Medal_Forest"
REST = "System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs"
TABLES = {name: "RSDB/" + name + ".Product.111.rstbl.byml.zs"
          for name in ("ActorInfo", "GameActorInfo", "PouchActorInfo")}


def _separate_model(actor):
    return (actor.startswith("Item_Melody_") or actor in {
        "Item_Ocarina_Fairy", "Item_Ocarina_Time", "Weapon_Sword_Master"})


def model_actor(actual_actor):
    """Display alias only; never pass this to a pouch/window command."""
    if actual_actor == "Item_Dungeon_SmallKey":
        return "Obj_MiniGame_SmallKey"
    if actual_actor.startswith(("Item_Medal_", "Item_Stone_")):
        return actual_actor + "_ImportantMenu"
    if _separate_model(actual_actor):
        return "Item_AP_Show_" + hashlib.sha256(actual_actor.encode()).hexdigest()[:12]
    return actual_actor


def needs_model_alias(metadata):
    return any(model_actor(actor) != actor
               for actor in metadata.get("tiers", [metadata["actor"]]))


def chest_model_actor(actual_actor):
    """Native pouch guest for a chest; its content argument stays the real item."""
    if actual_actor == "Item_Dungeon_SmallKey":
        # This exact native key already supplies its working key-specific AS.
        return "Obj_MiniGame_SmallKey"
    if model_actor(actual_actor) != actual_actor:
        return "Item_AP_Chest_" + hashlib.sha256(actual_actor.encode()).hexdigest()[:12]
    return actual_actor


def _model(pack, actor, byml_codec):
    path = "Actor/" + actor + ".engine__actor__ActorParam.bgyml"
    visited = set()
    while path not in visited:
        visited.add(path)
        root = byml_codec.load(pack[path])["root"]
        ref = root.get("Components", {}).get("ModelInfoRef")
        if ref:
            return byml_codec.load(pack[_path(ref)])
        parent = root.get("$parent")
        if not parent:
            break
        path = _path(parent)
    raise ValueError("Native presentation model not found: " + actor)


def _path(ref):
    path = ref.removeprefix("?").removeprefix("Work/")
    return path[:-5] + ".bgyml" if path.endswith(".gyml") else path


def _visual_root(pack, path, byml_codec):
    document = byml_codec.load(pack[path])
    chain, seen = [], set()
    root = document["root"]
    while True:
        if path in seen:
            raise ValueError("Native presentation actor inheritance loops.")
        seen.add(path)
        chain.append(root)
        if not root.get("$parent"):
            break
        path = _path(root["$parent"])
        root = byml_codec.load(pack[path])["root"]
    merged, components = {}, {}
    for root in reversed(chain):
        merged.update({key: value for key, value in root.items() if key not in {"$parent", "Components"}})
        components.update(root.get("Components", {}))
    merged["Components"] = components
    document["root"] = merged
    return document


def prepare_presentation_models(romfs, mod):
    """Stage isolated visual actors using the native Common/GetDemo components."""
    from oot_rando.formats import byml_codec
    from oot_rando.formats.inspect_resources import sarc
    from oot_rando.game.resource_allocations import add_resources, allocation, grow_resources
    from oot_rando.patching.ap_item import SPIN_TEMPLATE, spin_parts
    from .catalog import ITEM_DATA
    from .mod_codec import Codec

    romfs, mod = Path(romfs), Path(mod)
    codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())

    def frame(relative):
        staged = mod / relative
        return (staged if staged.is_file() else romfs / relative).read_bytes()

    def read(relative):
        return codec.decode(frame(relative))

    all_actors = {actor for item in ITEM_DATA.values() for actor in item.get("tiers", [item["actor"]])}
    actors = sorted(actor for actor in all_actors if _separate_model(actor))
    chest_actors = sorted(actor for actor in all_actors
                          if chest_model_actor(actor).startswith("Item_AP_Chest_"))
    jobs = [(actor, model_actor(actor), False) for actor in actors]
    jobs.extend((actor, chest_model_actor(actor), True) for actor in chest_actors)
    spin_files, spin_components, spin_info = spin_parts(read)
    template_path = "Pack/Actor/" + TEMPLATE + ".pack.zs"
    template_frame = frame(template_path)
    template = sarc(codec.decode(template_frame))
    actor_file = "Actor/" + TEMPLATE + ".engine__actor__ActorParam.bgyml"
    model_file = "Component/ModelInfo/" + TEMPLATE + ".engine__component__ModelInfo.bgyml"
    changed, outputs = {}, {}
    donors = {}
    chest_aliases = set()
    for actor, alias, chest in jobs:
        if chest:
            chest_aliases.add(alias)
        donor = "Dm_Item_Sheik_Harp" if actor.startswith("Item_Melody_") else actor
        donors[alias] = donor
        pack = sarc(read("Pack/Actor/" + donor + ".pack.zs"))
        files = {key: value for key, value in template.items() if key not in {actor_file, model_file}}
        param = (byml_codec.load(template[actor_file]) if chest
                 else _visual_root(template, actor_file, byml_codec))
        components = param["root"]["Components"]
        if not chest:
            # A receipt creates only a shown model. A chest instead binds the
            # native PouchContentGuestPerformer from Item_EventObject_Base,
            # exactly like the established AP medallion actor does.
            components.pop("PouchContentRef", None)
            components.pop("EventPerformerRef", None)
        components["ActorNameRef"] = "?ActorSystem/ActorName/" + alias + ".engine__actor__ActorName.bgyml"
        components["ModelInfoRef"] = "?Component/ModelInfo/" + alias + ".engine__component__ModelInfo.bgyml"
        components.update(spin_components)
        files.update(spin_files)
        files["Actor/" + alias + ".engine__actor__ActorParam.bgyml"] = byml_codec.dump(param)
        files["Component/ModelInfo/" + alias + ".engine__component__ModelInfo.bgyml"] = byml_codec.dump(
            _model(pack, donor, byml_codec))
        path = "Pack/Actor/" + alias + ".pack.zs"
        raw = byml_codec.build_sarc(files)
        if (mod / path).is_file():
            if read(path) != raw:
                raise ValueError("Incompatible existing presentation model: " + alias)
        elif (romfs / path).is_file():
            raise ValueError("Native presentation alias collision: " + alias)
        else:
            outputs[path] = (raw, template_frame)

    for table, path in TABLES.items():
        original = read(path)
        document = byml_codec.load(original)
        rows = document["root"]
        by_id = {row["__RowId"]: row for row in rows}
        if len(by_id) != len(rows):
            raise ValueError("Ambiguous native presentation table: " + table)
        template_row = by_id[TEMPLATE]
        new_rows = []
        for alias, donor in donors.items():
            if table == "PouchActorInfo" and alias not in chest_aliases:
                continue
            row = copy.deepcopy(template_row)
            row["__RowId"] = alias
            if table == "ActorInfo":
                donor_row = by_id[donor]
                row["ActorName"] = alias
                for key in ("FmdbName", "ModelProjectName", "ModelAabbMax", "ModelAabbMin",
                            "ModelVariationFmabName", "PreActorRenderInfoHeapSize"):
                    if key in donor_row:
                        row[key] = copy.deepcopy(donor_row[key])
                row.update(copy.deepcopy(spin_info))
                row["InstanceHeapSize"] = max(row["InstanceHeapSize"], donor_row["InstanceHeapSize"],
                                               by_id[SPIN_TEMPLATE]["InstanceHeapSize"])
            if alias in by_id:
                if by_id[alias] != row:
                    raise ValueError("Incompatible presentation actor row: " + alias)
            else:
                new_rows.append(row)
        if new_rows:
            rows.extend(new_rows)
            rows.sort(key=lambda row: row["__RowId"])
            changed[path] = (byml_codec.dump(document), frame(path), len(original))

    if not outputs and not changed:
        return {"models": len(actors), "chest_models": len(chest_actors), "written": 0}
    rest_frame = frame(REST)
    rest = codec.decode(rest_frame)
    rest, _ = grow_resources(rest, {path: max(0, len(raw) - before)
                                   for path, (raw, _, before) in changed.items()})
    rest, _ = add_resources(rest, {path: max((len(raw) + 8191) & ~4095,
                                            allocation(rest, template_path) or 0)
                                   for path, (raw, _) in outputs.items()})
    encoded = {path: codec.encode(raw, origin) for path, (raw, origin) in outputs.items()}
    encoded.update({path: codec.encode(raw, origin) for path, (raw, origin, _) in changed.items()})
    encoded[REST] = codec.encode(rest, rest_frame)
    # Validate every pack/table/resource allocation before publishing the stage.
    for path, content in encoded.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return {"models": len(actors), "chest_models": len(chest_actors), "written": len(encoded)}
