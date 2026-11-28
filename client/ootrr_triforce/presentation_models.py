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
# These native actors are world pickups or have specialized animation graphs,
# rather than the generic chest guest. Shop actors additionally lack a pouch
# event performer. Only their chest model is replaced; their reward stays real.
WORLD_CHEST_MODELS = frozenset({
    "Item_Bomb", "Item_DekuStick", "Item_ScrubBusinessSeed", "Item_Sword_Giant",
    "Obj_Armor_Goron", "Obj_Armor_Zora", "Obj_Fairy", "Obj_Heart",
    "Obj_Heart_Container", "Obj_Heart_Piece",
})


def _separate_model(actor):
    return (actor.startswith(("Item_Melody_", "Item_Medal_", "Item_Stone_")) or actor in {
        "Item_Ocarina_Fairy", "Item_Ocarina_Time", "Weapon_Sword_Master"})


def _pouch_guest_alias(actual_actor):
    # Chest guests retain their native pouch performer. A shown receipt model
    # instead follows Player's own get-item binding and has no pouch performer.
    return "Item_AP_Chest_" + hashlib.sha256(actual_actor.encode()).hexdigest()[:12]


def model_actor(actual_actor):
    """Display alias only; never pass this to a pouch/window command."""
    if actual_actor == "Item_Dungeon_SmallKey":
        return "Obj_MiniGame_SmallKey"
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
    if (model_actor(actual_actor) != actual_actor or actual_actor.startswith("Shop_")
            or actual_actor in WORLD_CHEST_MODELS):
        return _pouch_guest_alias(actual_actor)
    return actual_actor


def receipt_model_aliases(raw):
    """Upgrade only known AP receipt model arguments in a compatible old base.

    The constructor may already contain room-bound receipt graphs. Reusing it
    must not retain inventory-menu actors after the visual guest changes.
    Real pouch/window arguments, graph nodes, continuations and IDs stay exact.
    """
    from evfl.event import SubFlowEvent
    from oot_rando.patching.progressive import FlowEditor
    from .catalog import ITEM_DATA, ITEM_IDS
    from .native_presentations import PRESENTER_NAME, PRESENTER_ENTRY
    from .receipt_events import PREFIX, event_name

    rewards = {old: (name, row["actor"])
               for name, row in ITEM_DATA.items()
               if row["actor"].startswith(("Item_Medal_", "Item_Stone_"))
               for old in (row["actor"] + "_ImportantMenu", _pouch_guest_alias(row["actor"]))}
    editor = FlowEditor(raw, "Archipelago held reward models")
    entries = {}
    for entry in editor.chart.entry_points:
        if entry.name in entries:
            raise ValueError("Receipt model upgrade has duplicate native entries.")
        entries[entry.name] = entry
    planned = []
    for event in editor.chart.events:
        if not event.name.startswith(PREFIX):
            continue
        data = event.data
        params = getattr(data, "params", None)
        old = params.data.get(SHOW_ACTOR_ARGUMENT) if params is not None else None
        if type(old) is not str or old not in rewards:
            continue
        name, actual = rewards[old]
        item_id = ITEM_IDS[name]
        stem = event_name(item_id)
        entry = entries.get(stem)
        if (event.name != stem + "_Show" or not isinstance(data, SubFlowEvent)
                or data.res_flowchart_name != PRESENTER_NAME
                or data.entry_point_name != "OOTRR_APShow_" + str(item_id) + "_" + PRESENTER_ENTRY
                or params.data.get("ActorName") != actual
                or params.data.get("IsNpcEventStarter") is not False
                or entry is None or entry.main_event.v is not event):
            raise ValueError("Receipt model upgrade does not match its native AP item identity: " + event.name)
        planned.append((event, old, actual, model_actor(actual)))
    if not planned:
        return raw, []
    # Validate all candidates before changing any parsed event.
    changes = []
    for event, old, actual, shown in planned:
        event.data.params.data[SHOW_ACTOR_ARGUMENT] = shown
        editor.expected[event.name] = dict(event.data.params.data)
        changes.append(dict(event=event.name, actor=actual, before=old, after=shown))
    return editor.write("Native AP held model upgrade")[0], changes


def prepare_receipt_model_aliases(romfs, mod):
    """Migrate cached AP receipts after their native visual guests are staged."""
    from oot_rando.formats import byml_codec
    from oot_rando.formats.inspect_resources import sarc
    from oot_rando.game.resource_allocations import grow_resources
    from .mod_codec import Codec
    from .receipt_events import FLOW_PATH

    romfs, mod = Path(romfs), Path(mod)
    # Only constructor/staged receipts can contain AP entries. A native game
    # flow, or a historical chest-only stage without receipts, needs no pass.
    if not (mod / FLOW_PATH).is_file():
        return {"models": 0, "written": 0}
    codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
    def frame(path):
        target = mod / path
        return (target if target.is_file() else romfs / path).read_bytes()
    original = frame(FLOW_PATH)
    before = codec.decode(original)
    raw, changes = receipt_model_aliases(before)
    if not changes:
        return {"models": 0, "written": 0}
    # A compatible constructor can predate these nine visual-only actors.
    # Stage their packs/registries/allocations only after every old receipt
    # identity has been validated, before publishing its new model argument.
    prepare_presentation_models(romfs, mod)
    for actual, alias in sorted({(row["actor"], row["after"]) for row in changes}):
        pack = sarc(codec.decode(frame("Pack/Actor/" + alias + ".pack.zs")))
        components = _visual_root(pack, "Actor/" + alias + ".engine__actor__ActorParam.bgyml",
                                  byml_codec)["root"]["Components"]
        if (components.get("ASRef") != "?AS/Item_Common.root.asb"
                or "Item_GetDemo" not in components.get("ASInfoRef", "")
                or not components.get("ModelBindRef") or components.get("AIInfoRef")
                or "PouchContentRef" in components or "EventPerformerRef" in components):
            raise ValueError("Receipt model upgrade has no isolated native held-item model: " + alias)
        native = sarc(codec.decode((romfs / ("Pack/Actor/" + actual + ".pack.zs")).read_bytes()))
        if _model(pack, alias, byml_codec) != _model(native, actual, byml_codec):
            raise ValueError("Receipt model upgrade changed its native item mesh: " + alias)
    rest_frame = frame(REST)
    rest, _ = grow_resources(codec.decode(rest_frame), {FLOW_PATH: max(0, len(raw) - len(before))})
    encoded = {FLOW_PATH: codec.encode(raw, original), REST: codec.encode(rest, rest_frame)}
    # No resource is written before every receipt identity/guest has passed.
    for path, content in encoded.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return {"models": len(changes), "written": len(encoded)}


def _model_path(pack, actor, byml_codec):
    path = "Actor/" + actor + ".engine__actor__ActorParam.bgyml"
    visited = set()
    while path not in visited:
        visited.add(path)
        root = byml_codec.load(pack[path])["root"]
        ref = root.get("Components", {}).get("ModelInfoRef")
        if ref:
            return _path(ref)
        parent = root.get("$parent")
        if not parent:
            break
        path = _path(parent)
    raise ValueError("Native presentation model not found: " + actor)


def _model(pack, actor, byml_codec):
    return byml_codec.load(pack[_model_path(pack, actor, byml_codec)])


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


def validate_chest_models(read):
    """Check the native guest contract and rendered assets for every AP item.

    ``read`` supplies uncompressed effective resources, including the pending
    stage. A valid BYML file alone does not prove that the actor can participate
    in a chest event or that its selected model actually exists.
    """
    from oot_rando.formats import byml_codec
    from oot_rando.formats.inspect_resources import sarc
    from .catalog import ITEM_DATA

    tables = {name: {row["__RowId"]: row for row in byml_codec.load(read(path))["root"]}
              for name, path in TABLES.items()}
    actors = {actor for item in ITEM_DATA.values() for actor in item.get("tiers", [item["actor"]])}
    packs, assets, graphs = {}, set(), {}
    proxies = 0
    for actual in sorted(actors):
        guest = chest_model_actor(actual)
        if guest not in packs:
            packs[guest] = sarc(read("Pack/Actor/" + guest + ".pack.zs"))
        pack = packs[guest]
        components = _visual_root(pack, "Actor/" + guest + ".engine__actor__ActorParam.bgyml",
                                  byml_codec)["root"]["Components"]
        if any(guest not in rows for rows in tables.values()):
            raise ValueError("Native chest guest is missing a registry row: " + guest)
        info = tables["ActorInfo"][guest]
        identity = "?ActorSystem/ActorName/" + info["ActorName"] + ".engine__actor__ActorName.bgyml"
        if components.get("ActorNameRef") != identity:
            raise ValueError("Native chest guest identity differs from ActorInfo: " + guest)
        performer = components.get("EventPerformerRef")
        if not performer or not components.get("PouchContentRef"):
            raise ValueError("Native chest guest has no pouch event performer: " + guest)
        event = _visual_root(pack, _path(performer), byml_codec)["root"]
        expected = ("Work/AI/Root/Event/PouchContent_EnableWarp.event.root.ain"
                    if guest == "Obj_MiniGame_SmallKey" else "Work/AI/Root/Event/PouchContent.event.root.ain")
        if event.get("EventUniqueAin") != expected or not event.get("UseEventUniqueAin"):
            raise ValueError("Native chest guest uses an incompatible event performer: " + guest)
        if _path(components["PouchContentRef"]) not in pack:
            raise ValueError("Native chest guest pouch component is missing: " + guest)
        if guest.startswith("Item_AP_Chest_"):
            proxies += 1
            if components.get("AIInfoRef") or components.get("PhysicsRef") != "?Component/Physics/Dummy.engine__component__PhysicsParam.bgyml":
                raise ValueError("Chest model retained world or shop behavior: " + guest)
            template = tables["PouchActorInfo"][TEMPLATE]
            if tables["PouchActorInfo"][guest] != dict(template, __RowId=guest):
                raise ValueError("Chest model changed the native visual guest pouch contract: " + guest)
        model = _model(pack, guest, byml_codec)["root"]
        project, mesh = model.get("ModelProjectName"), model.get("FmdbName")
        if not project or not mesh or (info.get("ModelProjectName"), info.get("FmdbName")) != (project, mesh):
            raise ValueError("Native chest model disagrees with its render registry: " + guest)
        model_path = "Model/" + project + "." + mesh + ".bfres.zs"
        if model_path not in assets:
            raw = read(model_path)
            if not raw.startswith(b"FRES") or mesh.encode() + b"\0" not in raw:
                raise ValueError("Native chest model mesh is missing: " + guest)
            assets.add(model_path)
        animation = components.get("AnimationRef")
        if not animation:
            raise ValueError("Native chest guest has no item animation resources: " + guest)
        settings = components.get("ASInfoRef")
        if not settings or _path(settings) not in pack:
            raise ValueError("Native chest guest has no item animation settings: " + guest)
        resources = byml_codec.load(pack[_path(animation)])["root"].get("AnimationResources", [])
        if not any(row.get("ModelProjectName") == "Item_Common_Animation" for row in resources):
            raise ValueError("Native chest guest cannot play the common get animation: " + guest)
        for row in resources:
            path = "Model/" + row["ModelProjectName"] + ".anim.bfres.zs"
            if path not in assets:
                if not read(path).startswith(b"FRES"):
                    raise ValueError("Native chest animation resource is invalid: " + guest)
                assets.add(path)
        graph = components.get("ASRef", "").removeprefix("?") + ".zs"
        if graph not in graphs:
            graphs[graph] = read(graph)
        if b"Rotate_GetDemo" not in graphs[graph]:
            raise ValueError("Native chest guest cannot display the held item: " + guest)
    return {"actors": len(actors), "guests": len(packs), "proxies": proxies}


def prepare_presentation_models(romfs, mod):
    """Stage isolated visual actors using the native Common/GetDemo components."""
    from oot_rando.formats import byml_codec
    from oot_rando.formats.inspect_resources import sarc
    from oot_rando.game.resource_allocations import (add_resources, allocation, grow_resources,
                                                    reserve_packed_resources)
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

    native_packs = {}

    def native_pack(actor):
        if actor not in native_packs:
            native_packs[actor] = sarc(codec.decode((romfs / ("Pack/Actor/" + actor + ".pack.zs")).read_bytes()))
        return native_packs[actor]

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
    native_template = native_pack(TEMPLATE)
    native_spin = native_pack(SPIN_TEMPLATE)
    animation_peer = _path(_visual_root(native_spin, "Actor/" + SPIN_TEMPLATE + ".engine__actor__ActorParam.bgyml",
                                        byml_codec)["root"]["Components"]["AnimationRef"])
    packed_resources = [{"path": path, "data": data, "peer": animation_peer,
                         "peer_data": native_spin[animation_peer]}
                        for path, data in spin_files.items() if path.startswith("Component/AnimationParam/")]
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
        alias_actor = "Actor/" + alias + ".engine__actor__ActorParam.bgyml"
        alias_model = "Component/ModelInfo/" + alias + ".engine__component__ModelInfo.bgyml"
        files[alias_actor] = byml_codec.dump(param)
        files[alias_model] = byml_codec.dump(_model(pack, donor, byml_codec))
        native_donor = native_pack(donor)
        model_peer = _model_path(native_donor, donor, byml_codec)
        packed_resources.extend((
            {"path": alias_actor, "data": files[alias_actor], "peer": actor_file,
             "peer_data": native_template[actor_file]},
            {"path": alias_model, "data": files[alias_model], "peer": model_peer,
             "peer_data": native_donor[model_peer]},
        ))
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

    def effective_read(path):
        if path in outputs:
            return outputs[path][0]
        if path in changed:
            return changed[path][0]
        return read(path)

    validate_chest_models(effective_read)
    rest_frame = frame(REST)
    rest = codec.decode(rest_frame)
    rest, _ = grow_resources(rest, {path: max(0, len(raw) - before)
                                   for path, (raw, _, before) in changed.items()})
    rest, _ = add_resources(rest, {path: max((len(raw) + 8191) & ~4095,
                                            allocation(rest, template_path) or 0)
                                   for path, (raw, _) in outputs.items()})
    native_rest = codec.decode((romfs / REST).read_bytes())
    rest, reserved = reserve_packed_resources(rest, native_rest, packed_resources)
    if not outputs and not changed and not reserved:
        return {"models": len(actors), "chest_models": len(chest_actors), "written": 0}
    encoded = {path: codec.encode(raw, origin) for path, (raw, origin) in outputs.items()}
    encoded.update({path: codec.encode(raw, origin) for path, (raw, origin, _) in changed.items()})
    encoded[REST] = codec.encode(rest, rest_frame)
    # Validate every pack/table/resource allocation before publishing the stage.
    for path, content in encoded.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return {"models": len(actors), "chest_models": len(chest_actors), "written": len(encoded)}
