"""Native item models that can safely play the game's held-item animation.

Only the displayed actor changes. Inventory, pose queries, item windows and AP
acknowledgements always continue to use the real reward actor. Receipt aliases
are visual only. Chest proxies keep the native pouch guest performer, without
adding any saved flags, IsGet members, checks or custom event performers.
"""
import copy
import hashlib
import math
from pathlib import Path
import struct

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
# The held pose belongs to the displayed mesh. These native presentation
# actors use the same meshes as the inventory/world actors, but also supply
# their authored Pose_GetDemo/Pose_Common clips to Item_Common.
POSE_LENDERS = {
    "Item_Bomb": "Pouch_Bomb",
    "Item_DekuStick": "Shop_DekuStick",
    "Item_Ocarina_Fairy": "Pouch_Ocarina_Fairy",
    "Item_Ocarina_Time": "Pouch_Ocarina_Time",
    "Obj_Heart": "Shop_Heart",
    "Obj_Heart_Piece": "Pouch_Heart_Piece",
}
MASTER_POSE_SOURCE = "Model/Weapon_Sword_Kokiri_Animation.anim.bfres.zs"
MASTER_POSE_PROJECT = "Item_AP_MasterSwordPose"
MASTER_POSE_PATH = "Model/" + MASTER_POSE_PROJECT + ".anim.bfres.zs"
MASTER_MODEL_PATH = "Model/Weapon_Sword_Master.Weapon_Sword_Master.bfres.zs"
# Measured from all native Master Sword vertices under the native Kokiri Sword
# get orientation: 0.65 m maximum frame-zero width/height, centered 0.2 m above
# the binding point. Only its two isolated held aliases use this presentation.
MASTER_POSE_SCALE = 0.673380248831516
MASTER_POSE_TRANSLATE = (0.0053876286634312, 0.20526260579718364, -0.011265083930306218)
MASTER_POSE_SOURCE_SHA256 = "d9e6d1b62a25a4e332ff79e3c72f0f217ba9a28d44fff612e711c2618f02e8b4"
MASTER_MODEL_SHA256 = "96691b71049528412f867727f21050c37d88bf4db56ac37c2c4f220d880e0c51"
BOW_FAMILY = frozenset({"Item_Range_Bow", "Item_Quiver_Medium", "Item_Quiver_Large"})
BOW_POSE_SOURCE = "Model/Weapon_Range_Bow_Animation.anim.bfres.zs"
BOW_POSE_PROJECT = "Item_AP_BowPose"
BOW_POSE_PATH = "Model/" + BOW_POSE_PROJECT + ".anim.bfres.zs"
BOW_MODEL_PATH = "Model/Weapon_Range_Bow.Weapon_Range_Bow.bfres.zs"
BOW_POSE_SOURCE_SHA256 = "803977ea577b13b229c85adea9a1f0c4185525552485fbd89ac91f0a85911e38"
BOW_MODEL_SHA256 = "b2229431f5be2c802f232fb9c127bfef03e2c447b5b627821425182760320229"
# Preserve the native bow orientation and string proportions. Scale every body
# bone together (the limbs use segment-scale compensation), retaining a 0.60 m
# vertical envelope centered at Y=0. Both ages use the same visual profile.
BOW_POSE_FACTOR = 0.6972245681856358
BOW_POSE_TRANSLATE = (0.020468193906702754, 0.024535849649834567, 0.0)
BOW_DISPLAY_OFFSET = struct.unpack("<f", struct.pack("<f", 0.2))[0]


def _separate_model(actor):
    return (actor in BOW_FAMILY or actor.startswith(("Item_Melody_", "Item_Medal_", "Item_Stone_")) or actor in {
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


def _held_pose(pack, actor, alias, byml_codec):
    """Retain an item's native body pose alongside the shared rotation.

    Item_Common blends Root rotation with the mesh's Pose_GetDemo (or its
    native Common fallback). Keeping only Item_Common_Animation loses the
    authored body scale, orientation and translation. Do not borrow world,
    shop or weapon actor behavior; only the matching animation resource list
    is attached to the isolated held model.
    """
    components = _visual_root(pack, "Actor/" + actor + ".engine__actor__ActorParam.bgyml",
                              byml_codec)["root"]["Components"]
    source = components.get("AnimationRef")
    if components.get("ASRef") != "?AS/Item_Common.root.asb" or not source:
        return None
    source = _path(source)
    animation = byml_codec.load(pack[source])
    resources = animation["root"].get("AnimationResources", [])
    if (not isinstance(resources, list) or not all(isinstance(row, dict) and
            isinstance(row.get("ModelProjectName"), str) and row["ModelProjectName"]
            for row in resources)):
        raise ValueError("Native held-item animation resources are invalid: " + actor)
    if not any(row["ModelProjectName"] == "Item_Common_Animation" for row in resources):
        return None
    if len(resources) == 1:
        return None
    target = "Component/AnimationParam/" + alias + ".engine__component__AnimationParam.bgyml"
    return {"path": target, "data": pack[source], "peer": source,
            "peer_data": pack[source], "info": {"AnimationResources": copy.deepcopy(resources)}}


def _get_demo_offset(pack, actor, byml_codec):
    """The native displayed actor's pouch offset, independent of its grant."""
    components = _visual_root(pack, "Actor/" + actor + ".engine__actor__ActorParam.bgyml",
                              byml_codec)["root"]["Components"]
    reference = components.get("PouchContentRef")
    seen = set()
    while reference:
        path = _path(reference)
        if path in seen:
            raise ValueError("Native held-item pouch inheritance loops: " + actor)
        seen.add(path)
        # The omitted engine Default uses its zero-initialized Vec3f. Other
        # omitted components cannot be interpreted safely.
        if path not in pack:
            if path != "Component/PouchContentParam/Default.game__component__PouchContentParam.bgyml":
                raise ValueError("Native held-item pouch component is missing: " + actor)
            break
        root = byml_codec.load(pack[path])["root"]
        if "GetDemoOffsetPos" in root:
            value = root["GetDemoOffsetPos"]
            if (not isinstance(value, dict) or set(value) != {"X", "Y", "Z"}
                    or not all(type(value[key]) in (int, float) and math.isfinite(value[key]) for key in "XYZ")):
                raise ValueError("Native held-item display offset is invalid: " + actor)
            return [float(value[key]) for key in "XYZ"]
        reference = root.get("$parent")
    return [0.0, 0.0, 0.0]


def native_get_demo_offsets(read, actors=None):
    """Read display offsets for receipt aliases without adding pouch behavior.

    ``read`` supplies uncompressed effective RomFS resources. The values are
    suitable for the native EventIgnitionShowItem.ItemPos input only when the
    shown alias has no pouch component; ordinary actors already add their own.
    """
    from oot_rando.formats import byml_codec
    from oot_rando.formats.inspect_resources import sarc
    if actors is None:
        from .catalog import ITEM_DATA
        actors = {actor for row in ITEM_DATA.values() for actor in row.get("tiers", [row["actor"]])}
    return {actor: _get_demo_offset(sarc(read("Pack/Actor/" + actor + ".pack.zs")), actor, byml_codec)
            for actor in sorted(set(actors))}


def _held_offset(actor, native):
    return [0.0, BOW_DISPLAY_OFFSET, 0.0] if actor == "Item_Range_Bow" else native


def held_model_offsets(read, actors=None):
    """Display-only offsets; the factual native pouch metadata stays intact.

    The Bow uses the same 0.2 m display anchor as its native quiver tiers.
    Real inventory actors and their native pouch components are never edited.
    """
    return {actor: _held_offset(actor, value) for actor, value in native_get_demo_offsets(read, actors).items()}


def _chest_offset(template, template_actor, actual_pack, actor, alias, byml_codec):
    """Copy only the visual offset onto the established chest guest contract."""
    offset = _held_offset(actor, _get_demo_offset(actual_pack, actor, byml_codec))
    if offset == _get_demo_offset(template, template_actor, byml_codec):
        return None
    components = _visual_root(template, "Actor/" + template_actor + ".engine__actor__ActorParam.bgyml",
                              byml_codec)["root"]["Components"]
    source = _path(components["PouchContentRef"])
    document = byml_codec.load(template[source])
    document["root"]["GetDemoOffsetPos"] = dict(zip("XYZ", offset))
    target = "Component/PouchContentParam/" + alias + ".game__component__PouchContentParam.bgyml"
    return {"path": target, "data": byml_codec.dump(document), "peer": source,
            "peer_data": template[source]}


def _master_pose_bytes(raw):
    """Adapt a user's exact native static sword pose without rewriting a mesh."""
    if hashlib.sha256(raw).hexdigest() != MASTER_POSE_SOURCE_SHA256:
        raise ValueError("Unsupported native Master Sword presentation pose.")
    def u64(offset):
        return struct.unpack_from("<Q", raw, offset)[0]
    def text(offset):
        count = struct.unpack_from("<H", raw, offset)[0]
        return raw[offset + 2:offset + 2 + count].decode("utf-8")
    offset = raw.find(b"FSKA")
    if raw[:4] != b"FRES" or offset < 0 or raw.count(b"FSKA") != 1:
        raise ValueError("Unsupported native Master Sword presentation animation.")
    tracks = u64(offset + 40)
    count = struct.unpack_from("<H", raw, offset + 76)[0]
    if count != 2 or text(u64(offset + 8)) != "Pose_Common":
        raise ValueError("Unsupported native Master Sword presentation tracks.")
    positions = {}
    for index in range(count):
        track = tracks + index * 56
        flags = struct.unpack_from("<I", raw, track + 40)[0]
        if flags & 56 != 56 or raw[track + 46] != 0:
            raise ValueError("Native Master Sword presentation must use static transforms.")
        name, base = text(u64(track)), u64(track + 16)
        if name in positions or base + 40 > len(raw):
            raise ValueError("Ambiguous native Master Sword presentation bone.")
        positions[name] = (base, track)
    if set(positions) != {"Root", "Skl_Root"}:
        raise ValueError("Native Master Sword presentation has incompatible bones.")
    base, track = positions["Skl_Root"]
    result = bytearray(raw)
    struct.pack_into("<3f", result, base, *([MASTER_POSE_SCALE] * 3))
    struct.pack_into("<3f", result, base + 28, *MASTER_POSE_TRANSLATE)
    # Native Kokiri's zero translation uses BoneAnimFlagsTransform.TranslateZero
    # (bit 27). The generated nonzero center must not retain that shortcut.
    flags = struct.unpack_from("<I", raw, track + 40)[0]
    struct.pack_into("<I", result, track + 40, flags & ~(1 << 27))
    return bytes(result)


def _master_pose_parts(alias, peer, peer_data, byml_codec):
    info = {"AnimationResources": [{"ModelProjectName": "Item_Common_Animation"},
                                   {"ModelProjectName": MASTER_POSE_PROJECT}]}
    return {"path": "Component/AnimationParam/" + alias + ".engine__component__AnimationParam.bgyml",
            "peer": peer, "peer_data": peer_data, "info": info,
            "data": byml_codec.dump({"endian": "<", "version": 7, "root": copy.deepcopy(info)})}


def _bow_pose_bytes(raw):
    """Fit only the native static held pose, preserving every weapon clip."""
    if hashlib.sha256(raw).hexdigest() != BOW_POSE_SOURCE_SHA256:
        raise ValueError("Unsupported native Bow presentation pose.")
    def u64(offset):
        return struct.unpack_from("<Q", raw, offset)[0]
    def text(offset):
        count = struct.unpack_from("<H", raw, offset)[0]
        return raw[offset + 2:offset + 2 + count].decode("utf-8")
    poses = []
    offset = raw.find(b"FSKA")
    while offset >= 0:
        if text(u64(offset + 8)) == "Pose_Common":
            poses.append(offset)
        offset = raw.find(b"FSKA", offset + 1)
    if raw[:4] != b"FRES" or len(poses) != 1:
        raise ValueError("Unsupported native Bow presentation animation.")
    tracks = u64(poses[0] + 40)
    count = struct.unpack_from("<H", raw, poses[0] + 76)[0]
    expected = {"Root", "Skl_Root", "Bow_1_L", "Bow_2_L", "String_1_L", "String_2_L",
                "Bow_1_R", "Bow_2_R", "String_1_R", "String_2_R"}
    if count != len(expected):
        raise ValueError("Unsupported native Bow presentation tracks.")
    found, result = set(), bytearray(raw)
    for index in range(count):
        track = tracks + index * 56
        flags = struct.unpack_from("<I", raw, track + 40)[0]
        name, base = text(u64(track)), u64(track + 16)
        if name in found or name not in expected or base + 40 > len(raw):
            raise ValueError("Ambiguous native Bow presentation bone.")
        found.add(name)
        if flags & 56 != 56 or raw[track + 46] != 0:
            raise ValueError("Native Bow presentation must use static transforms.")
        if name == "Root":
            continue
        # The limbs' native segment-scale compensation cancels their parent's
        # basis scale. Scale each body bone by the same factor, preserving the
        # native nonuniform string scale ratios and all authored rotations.
        scale = struct.unpack_from("<3f", raw, base)
        scale = struct.unpack("<3f", struct.pack("<3f", *(value * BOW_POSE_FACTOR for value in scale)))
        struct.pack_into("<3f", result, base, *scale)
        flags = (flags | (1 << 24)) if scale[0] == scale[1] == scale[2] else (flags & ~(1 << 24))
        flags &= ~(1 << 25)  # the reviewed body scales do not have unit volume
        if name == "Skl_Root":
            struct.pack_into("<3f", result, base + 28, *BOW_POSE_TRANSLATE)
            flags &= ~(1 << 27)  # the recentered root still has a nonzero translation
        struct.pack_into("<I", result, track + 40, flags)
    if found != expected:
        raise ValueError("Native Bow presentation has incompatible bones.")
    return bytes(result)


def _bow_pose_parts(alias, peer, peer_data, byml_codec):
    info = {"AnimationResources": [{"ModelProjectName": "Item_Common_Animation"},
                                   {"ModelProjectName": BOW_POSE_PROJECT}]}
    return {"path": "Component/AnimationParam/" + alias + ".engine__component__AnimationParam.bgyml",
            "peer": peer, "peer_data": peer_data, "info": info,
            "data": byml_codec.dump({"endian": "<", "version": 7, "root": copy.deepcopy(info)})}


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
    changed, outputs, pack_growth = {}, {}, {}
    master_pose = None
    if "Weapon_Sword_Master" in all_actors:
        if hashlib.sha256(read(MASTER_MODEL_PATH)).hexdigest() != MASTER_MODEL_SHA256:
            raise ValueError("Unsupported native Master Sword presentation mesh.")
        master_pose = _master_pose_bytes(read(MASTER_POSE_SOURCE))
        if (mod / MASTER_POSE_PATH).is_file():
            if read(MASTER_POSE_PATH) != master_pose:
                raise ValueError("Incompatible existing Master Sword presentation pose.")
        elif (romfs / MASTER_POSE_PATH).is_file():
            raise ValueError("Native Master Sword presentation resource collision.")
        else:
            outputs[MASTER_POSE_PATH] = (master_pose, frame(MASTER_POSE_SOURCE))
    if "Item_Range_Bow" in all_actors:
        if hashlib.sha256(read(BOW_MODEL_PATH)).hexdigest() != BOW_MODEL_SHA256:
            raise ValueError("Unsupported native Bow presentation mesh.")
        bow_pose = _bow_pose_bytes(read(BOW_POSE_SOURCE))
        if (mod / BOW_POSE_PATH).is_file():
            if read(BOW_POSE_PATH) != bow_pose:
                raise ValueError("Incompatible existing Bow presentation pose.")
        elif (romfs / BOW_POSE_PATH).is_file():
            raise ValueError("Native Bow presentation resource collision.")
        else:
            outputs[BOW_POSE_PATH] = (bow_pose, frame(BOW_POSE_SOURCE))
    donors = {}
    pose_infos = {}
    pose_lenders = {}
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
        # Recognize the exact previous generated actor before upgrading its
        # visual-only animation resource. Unknown constructor overrides still
        # fail closed rather than silently changing a third-party actor.
        legacy_raw = byml_codec.build_sarc(files)
        if chest:
            actual_pack = pack if actor == donor else sarc(read("Pack/Actor/" + actor + ".pack.zs"))
            offset = _chest_offset(template, TEMPLATE, actual_pack, actor, alias, byml_codec)
            if offset is not None:
                components["PouchContentRef"] = "?" + offset["path"]
                files[alias_actor] = byml_codec.dump(param)
                files[offset["path"]] = offset["data"]
                if native_template[offset["peer"]] != offset["peer_data"]:
                    raise ValueError("Unsupported modified native chest guest pouch: " + actor)
                packed_resources.append(offset)
        lender = POSE_LENDERS.get(actor, donor)
        pose_pack = pack if lender == donor else sarc(read("Pack/Actor/" + lender + ".pack.zs"))
        donor_model, pose_model = (_model(source, name, byml_codec)["root"]
                                   for source, name in ((pack, donor), (pose_pack, lender)))
        if any(donor_model.get(key) != pose_model.get(key) for key in ("FmdbName", "ModelProjectName")):
            raise ValueError("Native held-item pose uses a different mesh: " + actor)
        pose = _held_pose(pose_pack, lender, alias, byml_codec)
        if actor == "Weapon_Sword_Master":
            # No native Master Sword get-item actor exists. Reuse the game's
            # authored sword orientation on the compatible Root/Skl_Root
            # skeleton, with the measured size and center above. The weapon,
            # original model and all inventory/gameplay actors remain native.
            lender = SPIN_TEMPLATE
            pose = _master_pose_parts(alias, animation_peer, native_spin[animation_peer], byml_codec)
        elif actor == "Item_Range_Bow":
            # The actual weapon is kept for queries and inventory. Only these
            # generic display actors use the bounded native held pose, without
            # the weapon's age-dependent display behavior.
            lender = SPIN_TEMPLATE
            pose = _bow_pose_parts(alias, animation_peer, native_spin[animation_peer], byml_codec)
        if pose is not None:
            components["AnimationRef"] = "?" + pose["path"]
            files[alias_actor] = byml_codec.dump(param)
            files[pose["path"]] = pose["data"]
            pose_infos[alias] = pose["info"]
            pose_lenders[alias] = lender
            native_pose = native_pack(lender)
            if native_pose[pose["peer"]] != pose["peer_data"]:
                raise ValueError("Unsupported modified native held-item pose: " + actor)
            packed_resources.append({key: pose[key] for key in ("path", "data", "peer", "peer_data")})
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
            before = read(path)
            if before != raw:
                if before != legacy_raw:
                    raise ValueError("Incompatible existing presentation model: " + alias)
                outputs[path] = (raw, frame(path))
                pack_growth[path] = max(0, len(raw) - len(before))
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
        new_rows, updated = [], False
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
            legacy_row = copy.deepcopy(row)
            if table == "ActorInfo" and alias in pose_infos:
                row.update(copy.deepcopy(pose_infos[alias]))
                lender_row = by_id[pose_lenders[alias]]
                for key in ("InstanceHeapSize", "PreActorRenderInfoHeapSize"):
                    if key in lender_row:
                        row[key] = max(row.get(key, 0), lender_row[key])
            if alias in by_id:
                if by_id[alias] != row:
                    if by_id[alias] != legacy_row:
                        raise ValueError("Incompatible presentation actor row: " + alias)
                    by_id[alias].clear()
                    by_id[alias].update(row)
                    updated = True
            else:
                new_rows.append(row)
        if new_rows or updated:
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
                                   for path, (raw, _, before) in changed.items()} | pack_growth)
    profile_sources = {MASTER_POSE_PATH: MASTER_POSE_SOURCE, BOW_POSE_PATH: BOW_POSE_SOURCE}
    rest, _ = add_resources(rest, {path: max((len(raw) + 8191) & ~4095,
                                            allocation(rest, profile_sources.get(path, template_path)) or 0)
                                   for path, (raw, _) in outputs.items() if allocation(rest, path) is None})
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
