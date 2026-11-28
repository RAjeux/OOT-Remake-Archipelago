"""Measure native shop-display geometry without distributing game resources.

Run with the same native RomFS used to build the integration:
  python tools/generate_shop_layout_profiles.py --romfs PATH --output FILE

NumPy is required only for this maintainer measurement tool. The client reads
the generated numeric profiles. The tool retains native meshes/animations and
never writes to the supplied RomFS.

Format facts were cross-checked against independently implemented readers:
https://github.com/KillzXGaming/BfresLibrary/tree/e2c5debca60e9b95e0fd220d32886102d65166bf
https://github.com/NuxsGit/HookyMod/blob/7ee7c5eaee83e206d1ac17320a2913302320dc7c/hookymod/animation.py
https://github.com/NuxsGit/HookyMod/blob/7ee7c5eaee83e206d1ac17320a2913302320dc7c/hookycreator/web/model_animation.js
The implementation is independent; these references establish binary-format
facts, not copied code or a runtime dependency.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))

from ootrr_triforce.catalog import ITEM_DATA
from ootrr_triforce import app_runtime
from oot_rando.formats import byml_codec as by
from oot_rando.formats.inspect_resources import sarc
from shop_geometry import PreparedMesh
from shop_pose_animation import animation, pose_at, resolve_shop_clip


def donor(actor):
    if actor.startswith("Item_Melody_"):
        return "Dm_Item_Sheik_Harp"
    return {"Item_Ocarina_Fairy": "Dm_Item_Ocarina_Fairy", "Item_Ocarina_Time": "Obj_Ocarina_Time"}.get(actor, actor)


def components(files, actor):
    result, seen = {}, set()
    path = "Actor/" + actor + ".engine__actor__ActorParam.bgyml"
    while path not in seen:
        seen.add(path)
        root = by.load(files[path])["root"]
        for name, reference in root.get("Components", {}).items():
            result.setdefault(name, reference)
        parent = root.get("$parent")
        if not parent:
            return result
        path = parent.removeprefix("?").removeprefix("Work/")
        path = path.removesuffix(".gyml") + ".bgyml" if path.endswith(".gyml") else path
    raise ValueError("Native actor inheritance cycle")


def critical_times(clip):
    """Include channel extrema as well as a half-frame sampling grid."""
    times = {i / 2 for i in range(2 * clip["length"] + 1)}
    for track in clip["tracks"].values():
        for curve in track["curves"]:
            times.update(curve["times"])
            for i, (first, last) in enumerate(zip(curve["times"], curve["times"][1:])):
                if last <= first:
                    continue
                value, slope = curve["keys"][i]
                following, next_slope = curve["keys"][i + 1]
                duration = last - first
                cubic = 2 * value - 2 * following + duration * (slope + next_slope)
                quadratic = -3 * value + 3 * following - duration * (2 * slope + next_slope)
                linear = duration * slope
                roots = []
                if abs(cubic) > 1e-16:
                    discriminant = 4 * quadratic * quadratic - 12 * cubic * linear
                    if discriminant >= 0:
                        roots = [(-2 * quadratic + sign * math.sqrt(discriminant)) / (6 * cubic) for sign in (-1, 1)]
                elif abs(quadratic) > 1e-16:
                    roots = [-linear / (2 * quadratic)]
                times.update(first + root * duration for root in roots if 0 < root < 1)
    times = sorted(t for t in times if 0 <= t <= clip["length"])
    if len(times) > 20000:
        raise ValueError("Native animation sampling budget exceeded")
    return times


def measure(mesh, clips, alternatives=()):
    rest = {bone["name"]: bone for bone in mesh.bones}
    length = max((clip["length"] for clip in clips), default=1)
    animated = any(track["curves"] for clip in clips for track in clip["tracks"].values())
    times = sorted({t for clip in clips for t in (critical_times(clip) if animated else [0.0])}) if clips else [0.0]
    rest_bounds=mesh.bounds({})
    low,high=[math.inf]*3,[-math.inf]*3
    first = None
    for time in times:
        pose = {}
        for clip in clips:
            pose.update(pose_at(clip, min(time, clip["length"]), rest))
        bounds = mesh.bounds(pose)
        if first is None:
            first = bounds
        low = [min(a, b) for a, b in zip(low, bounds["min"])]
        high = [max(a, b) for a, b in zip(high, bounds["max"])]
    extra_samples=0
    for alternative in alternatives:
        alternate=measure(mesh,alternative)
        low=[min(a,b) for a,b in zip(low,alternate['bounds']['min'])]
        high=[max(a,b) for a,b in zip(high,alternate['bounds']['max'])]
        extra_samples+=alternate['sampling']['samples']
    raw_bounds = dict(min=low, max=high)
    # Sampling is not a symbolic extremum proof for a complete skinned mesh.
    # Keep explicit headroom for fractional-frame interpolation and require
    # native gallery review in addition to these measurements.
    padding = 0.005 + 0.025 * max(b - a for a, b in zip(low, high)) if animated else 0.0
    low = [a - padding for a in low]
    high = [b + padding for b in high]
    scale = 0.36572265625 / max(b - a for a, b in zip(low, high))
    horizontal_radius = scale * max(math.hypot(x, z) for x in (low[0], high[0]) for z in (low[2], high[2]))
    return dict(bounds=dict(min=low, max=high), sample_envelope=raw_bounds, frame_zero=first,rest_bounds=rest_bounds,
                sampling=dict(animated=animated, samples=len(times)+extra_samples, last_frame=length, frame_step=0.5,
                              fractional_frame_padding=padding), horizontal_radius=horizontal_radius,
                vertices=mesh.vertices)


def generate(game, codec):
    cache, resources, meshes, clip_cache = {}, {}, {}, {}
    def read(path):
        if path not in cache:
            cache[path] = codec.decode((game / path).read_bytes())
            resources[path] = hashlib.sha256(cache[path]).hexdigest()
        return cache[path]
    info_path = "RSDB/ActorInfo.Product.111.rstbl.byml.zs"
    infos = {row["__RowId"]: row for row in by.load(read(info_path))["root"]}
    actor_names = sorted({actor for item in ITEM_DATA.values() for actor in (item["actor"], *item.get("tiers", []))})
    if len(actor_names) != 167:
        raise ValueError("The supported item catalogue changed; review the new display actors")
    result = {}
    for actor in actor_names:
        visual = donor(actor)
        info = infos[visual]
        pack_path = "Pack/Actor/" + visual + ".pack.zs"
        files = sarc(read(pack_path))
        component = components(files, visual)
        pose_files,pose_components=files,component
        shop_pose_source=None
        if actor=='Item_DekuStick':
            shop_pose_source='Shop_DekuStick'
            pose_files=sarc(read('Pack/Actor/'+shop_pose_source+'.pack.zs'))
            pose_components=components(pose_files,shop_pose_source)
        model_info = by.load(files[component["ModelInfoRef"].removeprefix("?")])["root"]
        path = "Model/" + model_info["ModelProjectName"] + "." + model_info["FmdbName"] + ".bfres.zs"
        if path not in meshes:
            meshes[path] = PreparedMesh(read(path))
        mesh = meshes[path]
        projects = []
        if "AnimationRef" in pose_components:
            reference = pose_components["AnimationRef"].removeprefix("?")
            animation_info = by.load(pose_files[reference])["root"]
            projects = [row["ModelProjectName"] for row in animation_info.get("AnimationResources", [])]
        mode_clips={name:[] for name in ('Pose_Shop','Rotate_Shop','Pose_Stoped','Rotate_Stoped')}
        dependencies = [pack_path, path]
        if shop_pose_source:dependencies.append('Pack/Actor/'+shop_pose_source+'.pack.zs')
        resolutions=[]
        for project in projects:
            resource = "Model/" + project + ".anim.bfres.zs"
            dependencies.append(resource)
            common='Pose_Common_Longshot' if actor=='Item_Longshot' else 'Pose_Common'
            available={}
            for name in (*mode_clips,common):
                key=resource,name
                if key not in clip_cache:clip_cache[key]=animation(read(resource),name)
                available[name]=clip_cache[key]
            for mode in mode_clips:
                resolved,clip=resolve_shop_clip(available,mode,common)
                if clip is not None:
                    if clip['tracks']:
                        mode_clips[mode].append(clip)
                        resolutions.append(dict(requested=mode,resolved=resolved,project=project))
        clips=mode_clips['Pose_Shop']+mode_clips['Rotate_Shop']
        stopped=mode_clips['Pose_Stoped']+mode_clips['Rotate_Stoped']
        measured = measure(mesh,clips,[stopped] if stopped else [])
        measured['active_pose_clips']={mode:len(values) for mode,values in mode_clips.items() if values}
        measured['resolved_pose_clips']=resolutions
        result[actor] = dict(measured, donor=visual, project=info["ModelProjectName"], fmdb=info["FmdbName"],
            mesh_project=model_info["ModelProjectName"], mesh_fmdb=model_info["FmdbName"],
            native_bounds=dict(min=[info["ModelAabbMin"][k] for k in "XYZ"], max=[info["ModelAabbMax"][k] for k in "XYZ"]),
            resources=dependencies, yaw=0)
        if actor=='Weapon_Sword_Master':result[actor]['rotation']=[math.pi/2,0,math.pi/2]
        if shop_pose_source:result[actor]['shop_pose_source']=shop_pose_source
        print(actor, "samples=" + str(measured["sampling"]["samples"]), flush=True)
    from oot_rando.patching import ap_item
    fire_path = ap_item.MODEL_FILE
    foreign_model = ap_item.remove_relief(ap_item.hide_shapes(read(fire_path)))
    mesh = PreparedMesh(foreign_model)
    for suffix in ap_item.REPLACED:
        foreign_model = ap_item.rename(foreign_model, ap_item.OLD_TEX + "_" + suffix, ap_item.NEW_TEX + "_" + suffix)
    spin_path = "Model/Item_Common_Animation.anim.bfres.zs"
    read(spin_path)
    foreign = dict(measure(mesh, []), donor="Archipelago visual token", project=ap_item.PROJECT,
                   fmdb=ap_item.MODEL_INFO["FmdbName"], resources=[fire_path, spin_path], yaw=0,
                   preserve_native=True, stage_model_sha256=hashlib.sha256(foreign_model).hexdigest())
    template = infos[ap_item.MODEL_ACTOR]
    foreign["native_bounds"] = dict(min=[template["ModelAabbMin"][k] for k in "XYZ"], max=[template["ModelAabbMax"][k] for k in "XYZ"])
    # A renderer's shop AS comes from this native template, not the donor's
    # get-item/camera graph. Record it as a shared geometry assumption.
    template_path = "Pack/Actor/Shop_Armor_Goron.pack.zs"
    read(template_path)
    shared_as="AS/Item_Common.root.asb.zs"
    read(shared_as)
    used = {path for profile in [*result.values(), foreign] for path in profile["resources"]}
    used.add(template_path)
    used.add(shared_as)
    return dict(schema=1, geometry_version="native-bfres10.4-masked-shop-retained-pose-v8", actors=result, foreign=foreign,
        resources={path: resources[path] for path in sorted(used)}, shared_resources=[template_path,shared_as],
        provenance=dict(method="Complete mesh under active native shop body poses and Common fallback, or rest where no body animation exists; Maya segment-scale compensation; half-frame and channel-extrema samples plus explicit interpolation padding",
            commands={'Rotate_Shop':['Pose_Shop','Rotate_Shop'],'Rotate_Stoped':['Pose_Stoped','Rotate_Stoped']},
            pose_fallback='Shop body uses native Pose_Shop or the initialized Common pose; missing Pose_Stoped retains the resolved shop body pose. Verified by comparative native geometry controls.',
            native_bone_blend={'name':'Pose','Root':1.0,'Skl_Root':0.0},
            reader_reference="https://github.com/NuxsGit/HookyMod/tree/7ee7c5eaee83e206d1ac17320a2913302320dc7c",
            implementation="Independent maintainer-only reader; no game meshes or animation keys in this document",
            native_gallery_review_required=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--romfs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--codec-resources", type=Path)
    args = parser.parse_args()
    if args.codec_resources:
        app_runtime._resource_override = args.codec_resources.resolve()
    from ootrr_triforce.mod_codec import Codec
    game = args.romfs.resolve()
    document = generate(game, Codec((game / "Pack/ZsDic.pack.zs").read_bytes()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(dict(output=str(args.output), actors=len(document["actors"]), foreign=1,
                         resources=len(document["resources"]), worst_horizontal_radius=max(p["horizontal_radius"] for p in document["actors"].values()))))


if __name__ == "__main__":
    main()
