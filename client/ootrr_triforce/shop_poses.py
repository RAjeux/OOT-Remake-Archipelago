"""Use a native shop's display animation where a pickup has no shop pose."""
from pathlib import Path
import re

NATIVE = "Shop_DekuStick"
TARGET = "Item_DekuStick"
ANIMATION = "Component/AnimationParam/Item_DekuStick.engine__component__AnimationParam.bgyml"
REST = "System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs"


def repair_pose(raw, shelf, native_files):
    from oot_rando.formats import byml_codec as by
    from oot_rando.formats.inspect_resources import sarc
    from .shop_identity import _component
    from .shop_layout import _invalid
    expected = "?" + ANIMATION
    if _component(native_files, NATIVE, "AnimationRef") != expected:
        raise _invalid()
    native = native_files.get(ANIMATION)
    if native is None or by.load(native)["root"] != {"AnimationResources": [
            {"ModelProjectName": "Item_Common_Animation"}, {"ModelProjectName": "Item_DekuStick_Animation"}]}:
        raise _invalid()
    files = sarc(raw)
    match=re.fullmatch(r"Shop_OOTRR_(Item_AP_[0-9a-f]{12})_([0-9]{1,3})",shelf)
    if match is None:
        raise _invalid()
    path = "Actor/" + shelf + ".engine__actor__ActorParam.bgyml"
    document = by.load(files[path])
    components = document["root"].get("Components", {})
    if (not isinstance(components,dict)
            or components.get("ActorNameRef") != "?ActorSystem/ActorName/"+match[1]+".engine__actor__ActorName.bgyml"
            or components.get("ASRef") != "?AS/Item_Common.root.asb"
            or components.get("ASInfoRef") != "?Component/ASInfo/Item_Shop.engine__component__ASInfo.bgyml"
            or components.get("PouchContentRef") != "?Component/PouchContentParam/" + shelf + ".game__component__PouchContentParam.bgyml"
            or components.get("GameParameterTableRef") != "?GameParameter/GameParameterTable/" + shelf + ".engine__actor__GameParameterTable.bgyml"
            or components.get("AnimationRef") not in (None, expected)):
        raise _invalid()
    if ANIMATION in files and files[ANIMATION] != native:
        raise _invalid()
    if components.get("AnimationRef") == expected and files.get(ANIMATION) == native:
        return raw, 0
    components["AnimationRef"] = expected
    changed = by.dump(document)
    growth = max(0, len(changed) - len(files[path]))
    files[path], files[ANIMATION] = changed, native
    return by.build_sarc(files), growth


def prepare_shop_poses(romfs, mod, records):
    from .shop_events import _records
    selected = [record for record in _records(records) if record.get("native_actor") == TARGET]
    if not selected:
        return {"displays": 0, "written": 0}
    from .mod_codec import Codec
    from .shop_layout import _invalid
    from oot_rando.formats.inspect_resources import sarc
    from oot_rando.game.resource_allocations import allocation, grow_resources
    romfs, mod = Path(romfs), Path(mod)
    if mod.name != "romfs" or mod.parent.name != "Archipelago":
        raise _invalid()
    codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
    native_files = sarc(codec.decode((romfs / ("Pack/Actor/" + NATIVE + ".pack.zs")).read_bytes()))
    def frame(path):
        return ((mod / path) if (mod / path).is_file() else romfs / path).read_bytes()
    rest_frame = frame(REST)
    rest = codec.decode(rest_frame)
    native_rest = codec.decode((romfs / REST).read_bytes())
    grow_resources(native_rest, {})
    budget, effective = allocation(native_rest, ANIMATION), allocation(rest, ANIMATION)
    if budget is None or effective is None or effective < budget or budget < len(native_files.get(ANIMATION, b"")):
        raise _invalid()
    output, growth = {}, {}
    for record in selected:
        shelf = "Shop_OOTRR_" + record["actor"] + "_" + str(record["price"])
        path = "Pack/Actor/" + shelf + ".pack.zs"
        template = frame(path)
        before = codec.decode(template)
        after, inner = repair_pose(before, shelf, native_files)
        if after == before:
            continue
        output[path] = (after, template)
        growth[path] = max(0, len(after) - len(before))
        growth["Actor/" + shelf + ".engine__actor__ActorParam.bgyml"] = inner
    if not output:
        return {"displays": 0, "written": 0}
    rest, _ = grow_resources(rest, growth)
    count = len(output)
    output[REST] = (rest, rest_frame)
    encoded = {path: codec.encode(raw, template) for path, (raw, template) in output.items()}
    for path, raw in encoded.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    return {"displays": count, "written": len(encoded)}
