"""Fit AP shop displays to the game's original shelves, keeping purchase logic.

The reviewed profiles describe the displayed mesh in its native shop pose.
ActorInfo alone describes the rest mesh and can miss authored bone scaling.
Only the placement's uniform scale, vertical position and reviewed facing are
changed. Inventory, item actors, animations, prices and events stay untouched.
"""
import copy
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import struct

from .catalog import SHOP_CHECKS
from .i18n import tr

ACTORS = "RSDB/ActorInfo.Product.111.rstbl.byml.zs"
REST = "System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs"
DISPLAY_SIZE = 0.36572265625
DISPLAY_HEIGHT = 0.19
SHELF_MARGIN = 0.02


def _invalid():
    return ValueError(tr("Unsupported native Archipelago shop geometry."))


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise _invalid()
    return float(value)


def _f32(value):
    try:
        value = struct.unpack("<f", struct.pack("<f", _number(value)))[0]
    except (OverflowError, struct.error):
        raise _invalid() from None
    if not math.isfinite(value):
        raise _invalid()
    return value


def _vector(value):
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        raise _invalid()
    return [_number(v) for v in value]


def _bounds(value):
    if not isinstance(value, dict):
        raise _invalid()
    low, high = _vector(value.get("min")), _vector(value.get("max"))
    size = [b - a for a, b in zip(low, high)]
    if min(size) < 0 or max(size) <= 0:
        raise _invalid()
    return low, high


def _registered(info):
    try:
        return _bounds({"min": [info["ModelAabbMin"][k] for k in "XYZ"],
                        "max": [info["ModelAabbMax"][k] for k in "XYZ"]})
    except (KeyError, TypeError):
        raise _invalid() from None


@lru_cache(maxsize=1)
def profiles():
    document = json.loads(Path(__file__).with_name("shop_layout_profiles.json").read_text(encoding="utf-8"))
    if (document.get("schema") != 1 or not isinstance(document.get("actors"), dict)
            or not isinstance(document.get("foreign"), dict)):
        raise _invalid()
    return document


def verify_resources(document, selected, romfs, codec):
    """Reject changed meshes/poses before reusing measurements from another build."""
    resources = document.get("resources")
    shared = document.get("shared_resources")
    if not isinstance(resources, dict) or not isinstance(shared, list):
        raise _invalid()
    used = set(shared)
    for profile in selected:
        paths = profile.get("resources")
        if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
            raise _invalid()
        used.update(paths)
    for path in sorted(used):
        digest = resources.get(path)
        if (not isinstance(path, str) or "\\" in path or ".." in path.split("/")
                or not path.startswith(("Model/", "Pack/Actor/", "AS/"))
                or not path.endswith((".bfres.zs", ".pack.zs", ".asb.zs"))
                or not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest)):
            raise _invalid()
        if hashlib.sha256(codec.decode((romfs / path).read_bytes())).hexdigest() != digest:
            raise _invalid()


def verify_foreign_displays(document, records, read):
    """Recognize the established AP token's exact mesh and animation contract."""
    foreign = [record for record in records if "native_actor" not in record]
    if not foreign:
        return
    from oot_rando.formats import byml_codec as by
    from oot_rando.formats.inspect_resources import sarc
    from oot_rando.patching import ap_item
    from .shop_identity import _component
    profile = document["foreign"]
    if profile.get("preserve_native") is not True:
        raise _invalid()
    if hashlib.sha256(read(ap_item.NEW_MODEL_FILE)).hexdigest() != profile.get("stage_model_sha256"):
        raise _invalid()
    for record in foreign:
        shelf = "Shop_OOTRR_" + record["actor"] + "_" + str(record["price"])
        files = sarc(read("Pack/Actor/" + shelf + ".pack.zs"))
        model = _component(files, shelf, "ModelInfoRef").removeprefix("?")
        animation = _component(files, shelf, "AnimationRef").removeprefix("?")
        if (by.load(files[model])["root"] != ap_item.MODEL_INFO
                or animation != "Component/AnimationParam/Item_AP_Spin.engine__component__AnimationParam.bgyml"
                or by.load(files[animation])["root"] != {"AnimationResources": [{"ModelProjectName": ap_item.SPIN_ANIMATION}]}
                or _component(files, shelf, "ASRef") != "?AS/Item_Common.root.asb"
                or _component(files, shelf, "ASInfoRef") != "?Component/ASInfo/Item_Shop.engine__component__ASInfo.bgyml"):
            raise _invalid()


def display_profile(record, info, document):
    native = record.get("native_actor")
    profile = document["actors"].get(native) if native is not None else document["foreign"]
    if not isinstance(profile, dict):
        raise _invalid()
    actual = _registered(info)
    expected = _bounds(profile.get("native_bounds"))
    if any(abs(a - b) > 0.00001 for v, w in zip(actual, expected) for a, b in zip(v, w)):
        raise _invalid()
    projects = [profile.get("project")]
    if isinstance(native, str) and native.startswith("Item_Melody_"):
        projects.append("Item_Harp_" + native.removeprefix("Item_Melody_"))
    if info.get("ModelProjectName") not in projects or info.get("FmdbName") != profile.get("fmdb"):
        raise _invalid()
    _bounds(profile.get("bounds"))
    yaw = profile.get("yaw", 0)
    if yaw not in (0, math.pi / 2):
        raise _invalid()
    return profile


def _rotation(angles):
    x,y,z=_vector(angles)
    cx,sx,cy,sy,cz,sz=math.cos(x),math.sin(x),math.cos(y),math.sin(y),math.cos(z),math.sin(z)
    return [[cz*cy,cz*sy*sx-sz*cx,cz*sy*cx+sz*sx],
            [sz*cy,sz*sy*sx+cz*cx,sz*sy*cx-cz*sx],[-sy,cy*sx,cy*cx]]


def _angles(matrix):
    y=math.asin(max(-1,min(1,-matrix[2][0])))
    if abs(math.cos(y))>1e-7:
        x,z=math.atan2(matrix[2][1],matrix[2][2]),math.atan2(matrix[1][0],matrix[0][0])
    else:
        x,z=math.atan2(-matrix[1][2],matrix[1][1]),0
    return [_f32(v) for v in (x,y,z)]


def _oriented_bounds(low,high,rotation):
    corners=[[sum(rotation[i][j]*point[j] for j in range(3)) for i in range(3)]
             for point in ((x,y,z) for x in (low[0],high[0]) for y in (low[1],high[1]) for z in (low[2],high[2]))]
    return [min(p[i] for p in corners) for i in range(3)],[max(p[i] for p in corners) for i in range(3)]


def fit_transform(actor, native, row_height, profile, radius_limit=None):
    """Compute an absolute display transform from immutable native geometry."""
    low, high = _bounds(profile.get("bounds"))
    adjustment=_vector(profile.get("rotation",[0,profile.get("yaw",0),0]))
    if any(abs(v)>math.pi for v in adjustment):
        raise _invalid()
    local=_rotation(adjustment)
    if adjustment[0] or adjustment[2]:
        # A native selected shelf can spin around its upright local Y axis.
        # After tilting that axis, the full spin also affects visible height.
        radius=max(math.hypot(x,z) for x in (low[0],high[0]) for z in (low[2],high[2]))
        low,high=[-radius,low[1],-radius],[radius,high[1],radius]
    low,high=_oriented_bounds(low,high,local)
    desired = DISPLAY_SIZE / max(b - a for a, b in zip(low, high))
    if radius_limit is not None:
        radius_limit = _number(radius_limit)
        if radius_limit <= 0:
            raise _invalid()
        radius = max(math.hypot(x, z) for x in (low[0], high[0]) for z in (low[2], high[2]))
        if radius:
            desired = min(desired, radius_limit / radius)
    scale = _f32(desired)
    if scale <= 0:
        raise _invalid()
    current = _vector(actor.get("Translate"))
    original = _vector(native.get("Translate"))
    if any(abs(current[i] - original[i]) > 0.00001 for i in (0, 2)):
        raise _invalid()
    result = copy.deepcopy(actor)
    result["Scale"] = [scale] * 3
    result["Translate"] = [current[0], _f32(_number(row_height) + DISPLAY_HEIGHT - scale * (low[1] + high[1]) / 2), current[2]]
    original_rotation = _vector(native.get("Rotate", [0, 0, 0]))
    if _vector(native.get("Scale", [1, 1, 1])) != [1, 1, 1]:
        raise _invalid()
    # Native shops also encode upright yaw as pitch/roll both +/-pi. Test
    # their matrix, rather than mistaking those equivalent Euler angles for
    # tilted shelves whose effective vertical bounds would need recomputing.
    original_matrix=_rotation(original_rotation)
    vertical=[original_matrix[i][1] for i in range(3)]
    if max(abs(a - b) for a, b in zip(vertical, (0, 1, 0))) > 0.00001:
        raise _invalid()
    rotation = _vector(actor.get("Rotate", [0, 0, 0]))
    expected = [_f32(v) for v in original_rotation]
    if any(adjustment):
        composed=[[sum(original_matrix[i][k]*local[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
        expected=_angles(composed)
    if rotation not in (original_rotation, expected):
        raise _invalid()
    if any(adjustment) or "Rotate" in native:
        result["Rotate"] = expected
    return result


def _indexed(document):
    actors = document.get("root", {}).get("Actors")
    if not isinstance(actors, list):
        raise _invalid()
    indexed = {}
    for actor in actors:
        if not isinstance(actor, dict):
            raise _invalid()
        value = actor.get("Hash")
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < 2**64 or value in indexed:
            raise _invalid()
        indexed[value] = actor
    return actors, indexed


def fit_map(original, staged, jobs, actor_rows, document):
    """Change only AP shelf transforms at their original keeper/slot identities."""
    _, native = _indexed(original)
    result = copy.deepcopy(staged)
    _, target = _indexed(result)
    edits, visited = 0, set()
    for record in jobs:
        name = "Shop_OOTRR_" + record["actor"] + "_" + str(record["price"])
        if name not in actor_rows:
            raise _invalid()
        profile = display_profile(record, actor_rows[name], document)
        found = set()
        for keeper in native.values():
            if keeper.get("Gyaml") not in record["keepers"]:
                continue
            links = keeper.get("Links", [])
            if not isinstance(links, list):
                raise _invalid()
            destinations = [link.get("Dst") for link in links if isinstance(link, dict) and link.get("Name") == "ForSale"]
            if not destinations:
                continue
            if (any(not isinstance(d, int) or isinstance(d, bool) for d in destinations)
                    or len(destinations) != 8 or len(set(destinations)) != 8 or any(d not in native for d in destinations)):
                raise _invalid()
            group = [native[d] for d in destinations]
            for source in group:
                dynamic = source.get("Dynamic", {})
                if not isinstance(dynamic, dict):
                    raise _invalid()
                if dynamic.get("ShopItemIndex", 0) != record["slot"]:
                    continue
                key = source["Hash"]
                if key not in target or target[key].get("Gyaml") != name or not source.get("Gyaml", "").startswith("Shop_"):
                    raise _invalid()
                height = _vector(source.get("Translate"))[1]
                peers = [item for item in group if abs(_vector(item.get("Translate"))[1] - height) < 0.25]
                row = sorted(_vector(item.get("Translate"))[1] for item in peers)
                if len(peers) != 4:
                    raise _invalid()
                position = _vector(source.get("Translate"))
                spacing = min(math.hypot(position[0] - _vector(item.get("Translate"))[0],
                                         position[2] - _vector(item.get("Translate"))[2])
                              for item in peers if item["Hash"] != key)
                radius_limit = spacing / 2 - SHELF_MARGIN
                if "native_actor" not in record and profile.get("preserve_native") is True:
                    # The AP_Spin token already uses the native, visible shop
                    # presentation. It is our reference, not a static pickup
                    # whose authored pose should be fitted a second time.
                    scale = _vector(target[key].get("Scale", [1, 1, 1]))
                    if max(scale) <= 0 or max(scale) * profile["horizontal_radius"] > radius_limit:
                        raise _invalid()
                    following = copy.deepcopy(target[key])
                else:
                    following = fit_transform(target[key], source, (row[1] + row[2]) / 2, profile, radius_limit)
                if key in visited and following != target[key]:
                    raise _invalid()
                if following != target[key]:
                    target[key].clear()
                    target[key].update(following)
                    edits += 1
                visited.add(key)
                found.add(key)
        if not found:
            raise _invalid()
    return result, edits


def prepare_shop_layout(romfs, mod, records):
    from .shop_events import _records
    records = _records(records)
    if not records:
        return {"displays": 0, "written": 0}
    for record in records:
        known = SHOP_CHECKS.get(record.get("name"))
        if known is None or any(record.get(k) != known[k] for k in ("shop", "slot", "bancs", "keepers")):
            raise _invalid()
    from .mod_codec import Codec
    from oot_rando.formats import byml_codec as by
    from oot_rando.game.resource_allocations import grow_resources
    romfs, mod = Path(romfs), Path(mod)
    if mod.name != "romfs" or mod.parent.name != "Archipelago":
        raise _invalid()
    codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
    def frame(path):
        return ((mod / path) if (mod / path).is_file() else romfs / path).read_bytes()
    rows = by.load(codec.decode(frame(ACTORS)))["root"]
    indexed = {row["__RowId"]: row for row in rows}
    if len(indexed) != len(rows):
        raise _invalid()
    document, output, growth, count = profiles(), {}, {}, 0
    selected = []
    for record in records:
        name = "Shop_OOTRR_" + record["actor"] + "_" + str(record["price"])
        if name not in indexed:
            raise _invalid()
        selected.append(display_profile(record, indexed[name], document))
    verify_resources(document, selected, romfs, codec)
    verify_foreign_displays(document, records, lambda path: codec.decode(frame(path)))
    paths = sorted({p for record in records for p in record["bancs"]})
    for path in paths:
        original = by.load(codec.decode((romfs / path).read_bytes()))
        current_frame = frame(path)
        current_raw = codec.decode(current_frame)
        staged = by.load(current_raw)
        fitted, edits = fit_map(original, staged, [r for r in records if path in r["bancs"]], indexed, document)
        if edits:
            raw = by.dump(fitted)
            output[path] = (raw, current_frame)
            growth[path] = max(0, len(raw) - len(current_raw))
            count += edits
    if not output:
        return {"displays": 0, "written": 0}
    rest_frame = frame(REST)
    rest, _ = grow_resources(codec.decode(rest_frame), growth)
    output[REST] = (rest, rest_frame)
    encoded = {path: codec.encode(raw, template) for path, (raw, template) in output.items()}
    for path, raw in encoded.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    return {"displays": count, "written": len(encoded)}
