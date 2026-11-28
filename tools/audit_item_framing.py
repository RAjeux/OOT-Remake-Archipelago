"""Measure every supported held-item model using native GetDemo animation.

Maintainer-only, read-only RomFS audit. Requires NumPy and the normal codec
resources; no game meshes or animation keys are included in its JSON report.
Supply --overlay with a prepared Archipelago mod: the native RomFS alone does
not contain the AP visual aliases. Repeat it for additional preparation layers.
Geometry envelopes identify suspicious size/offsets; rendered gameplay review
is still required to judge the composition with Link, the camera and the HUD.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))

from ootrr_triforce import app_runtime
from ootrr_triforce.catalog import ITEM_DATA
from ootrr_triforce.native_presentations import receipt_style
from ootrr_triforce.presentation_models import (_get_demo_offset, _model, _path, _visual_root,
                                               chest_model_actor, held_model_offsets, model_actor)
from oot_rando.formats import byml_codec as by
from oot_rando.formats.inspect_resources import sarc
from generate_shop_layout_profiles import critical_times
from shop_geometry import PreparedMesh, worlds
from shop_pose_animation import animation, pose_at


def getdemo_clips(projects, read, clip_cache, *, common="Pose_Common"):
    """Resolve the native Common/GetDemo body and Root-only blend mask.

    The Pose bone group excludes Root. Missing GetDemo body clips retain the
    initialized Common pose. Rotation contributes Root only, so the Common
    clip's Skl_Root offset must not overwrite an item-specific body pose.
    """
    body, rotation, resolutions = [], [], []
    for project in projects:
        resource = "Model/" + project + ".anim.bfres.zs"
        available = {}
        for name in ("Pose_Common", "Pose_Common_Longshot", "Pose_GetDemo", "Rotate_GetDemo"):
            key = resource, name
            if key not in clip_cache:
                clip_cache[key] = animation(read(resource), name)
            available[name] = clip_cache[key]
        for mode, names, target in (("body", ("Pose_GetDemo", common), body),
                                    ("rotation", ("Rotate_GetDemo",), rotation)):
            for name in names:
                if available[name] is None:
                    continue
                clip = copy.deepcopy(available[name])
                clip["tracks"] = {bone: track for bone, track in clip["tracks"].items()
                                  if (bone == "Root") == (mode == "rotation")}
                if clip["tracks"]:
                    target.append(clip)
                    resolutions.append(dict(project=project, role=mode, clip=name))
                break
    return body + rotation, resolutions


def envelope(mesh, clips):
    rest = {bone["name"]: bone for bone in mesh.bones}
    # The common held spin is a full turn of Root around Y. For a static body
    # its continuous envelope follows directly from each skinned vertex's
    # radial distance, avoiding hundreds of equivalent mesh samples per item.
    rotating = [clip for clip in clips if set(clip["tracks"]) == {"Root"}]
    static_body = all(not track["curves"] for clip in clips if clip not in rotating
                      for track in clip["tracks"].values())
    if len(rotating) == 1 and static_body and "Root" in rest and rest["Root"]["parent"] == -1:
        track = rotating[0]["tracks"]["Root"]
        curves = track["curves"]
        base = track["base"]
        if (rotating[0]["euler"] and base.get("scale") == [1., 1., 1.]
                and base.get("translate") == [0., 0., 0.] and base.get("rotate") == [0., 0., 0., 1.]
                and len(curves) == 1 and curves[0]["target"] == 36
                and abs(curves[0]["keys"][-1][0] - curves[0]["keys"][0][0]) >= 2*math.pi - 1e-6):
            pose = {}
            for clip in clips:
                pose.update(pose_at(clip, 0., rest))
            np = mesh.np
            matrices = np.asarray(worlds(mesh.bones, pose), dtype=np.float64)
            smooth = matrices[mesh.palette[:len(mesh.inverse)]] @ mesh.inverse if len(mesh.inverse) else None
            radius, low_y, high_y = 0., math.inf, -math.inf
            for points, indices, weights in mesh.vertex_groups:
                if weights is None:
                    output = np.einsum("nij,nj->ni", matrices[mesh.palette[indices[:, 0]]], points)
                else:
                    output = np.zeros((len(points), 4))
                    for index in range(weights.shape[1]):
                        active = weights[:, index] > 0
                        output[active] += (np.einsum("nij,nj->ni", smooth[indices[active, index]], points[active])
                                           * weights[active, index, None])
                radius = max(radius, float(np.hypot(output[:, 0], output[:, 2]).max()))
                low_y, high_y = min(low_y, float(output[:, 1].min())), max(high_y, float(output[:, 1].max()))
            return dict(min=[-radius, low_y, -radius], max=[radius, high_y, radius],
                        center=[0., (low_y+high_y)/2, 0.], size=[radius*2, high_y-low_y, radius*2],
                        frame_zero=mesh.bounds(pose), vertices=mesh.vertices, samples=1, animated=True,
                        last_frame=rotating[0]["length"], analytic_full_y_rotation=True)
    animated = any(track["curves"] for clip in clips for track in clip["tracks"].values())
    times = sorted({frame for clip in clips for frame in (critical_times(clip) if animated else [0.0])}) or [0.0]
    low, high = [math.inf] * 3, [-math.inf] * 3
    first = None
    for frame in times:
        pose = {}
        for clip in clips:
            pose.update(pose_at(clip, min(frame, clip["length"]), rest))
        bounds = mesh.bounds(pose)
        if first is None:
            first = bounds
        low = [min(a, b) for a, b in zip(low, bounds["min"])]
        high = [max(a, b) for a, b in zip(high, bounds["max"])]
    return dict(min=low, max=high, center=[(a+b)/2 for a,b in zip(low,high)],
                size=[b-a for a,b in zip(low,high)], frame_zero=first, vertices=mesh.vertices,
                samples=len(times), animated=animated, last_frame=max(times))


def audit(game, codec, overlay=None):
    overlays = ([overlay] if isinstance(overlay, Path) else list(overlay or ()))
    resources, cached, packs, meshes, clip_cache, measured = {}, {}, {}, {}, {}, {}
    def read(path):
        if path not in cached:
            source = next((root / path for root in reversed(overlays) if (root / path).is_file()), game / path)
            cached[path] = codec.decode(source.read_bytes())
            resources[path] = dict(sha256=hashlib.sha256(cached[path]).hexdigest(),
                                   overlay=source != game / path)
        return cached[path]
    actor_info = {row["__RowId"]: row for row in by.load(read("RSDB/ActorInfo.Product.111.rstbl.byml.zs"))["root"]}
    pouch_info = {row["__RowId"]: row for row in by.load(read("RSDB/PouchActorInfo.Product.111.rstbl.byml.zs"))["root"]}
    styles, names = {}, {}
    for name, metadata in ITEM_DATA.items():
        for actual in metadata.get("tiers", [metadata["actor"]]):
            styles.setdefault(actual, set()).add(receipt_style(dict(metadata, actor=actual), pouch_info))
            names.setdefault(actual, []).append(name)
    rows, errors = {}, {}
    for actual in sorted(names):
        rows[actual] = dict(items=names[actual], receipt_styles=sorted(styles[actual]))
        for mode, shown in (("receipt", model_actor(actual)), ("chest", chest_model_actor(actual))):
            try:
                if shown not in packs:
                    packs[shown] = sarc(read("Pack/Actor/" + shown + ".pack.zs"))
                pack = packs[shown]
                components = _visual_root(pack, "Actor/" + shown + ".engine__actor__ActorParam.bgyml", by)["root"]["Components"]
                info = _model(pack, shown, by)["root"]
                path = "Model/" + info["ModelProjectName"] + "." + info["FmdbName"] + ".bfres.zs"
                if path not in meshes:
                    meshes[path] = PreparedMesh(read(path))
                projects = []
                if components.get("AnimationRef"):
                    animation_info = _visual_root(pack, _path(components["AnimationRef"]), by)["root"]
                    projects = [row["ModelProjectName"] for row in animation_info.get("AnimationResources", [])]
                clips, resolution = getdemo_clips(projects, read, clip_cache,
                                                  common="Pose_Common_Longshot" if actual == "Item_Longshot" else "Pose_Common")
                graph = components.get("ASRef")
                has_getdemo = bool(graph and b"Rotate_GetDemo" in read(_path(graph) + ".zs"))
                key = path, json.dumps(clips, sort_keys=True)
                if key not in measured:
                    measured[key] = envelope(meshes[path], clips)
                row = dict(actor=shown, model=path, as_graph=graph, has_getdemo=has_getdemo,
                           animation_resolution=resolution, geometry=measured[key],
                           held_receipt=mode == "receipt" and bool(styles[actual] & {"medium", "large"}))
                if actual not in packs:
                    packs[actual] = sarc(read("Pack/Actor/" + actual + ".pack.zs"))
                row["native_getdemo_offset"] = _get_demo_offset(packs[actual], actual, by)
                row["display_actor_getdemo_offset"] = _get_demo_offset(pack, shown, by)
                row["reviewed_display_anchor"] = held_model_offsets(read, [actual])[actual]
                row["ap_receipt_item_pos_compensation"] = [
                    a - b for a, b in zip(row["reviewed_display_anchor"], row["display_actor_getdemo_offset"])]
                registered = actor_info.get(shown, {})
                row["registered_bounds"] = {side: [registered.get("ModelAabb" + side.title(), {}).get(k) for k in "XYZ"]
                                            for side in ("min", "max")}
                rows[actual][mode] = row
            except Exception as error:
                errors[actual + ":" + mode] = type(error).__name__ + ": " + str(error)
        print(actual, "measured", flush=True)
    # The AP token is a visual reward too. Its generated mesh is available only
    # in a prepared overlay; using the native source would measure another item.
    foreign = None
    if overlays:
        from oot_rando.patching import ap_item
        path = ap_item.NEW_MODEL_FILE
        mesh = PreparedMesh(read(path))
        clips, resolution = getdemo_clips([ap_item.SPIN_ANIMATION], read, clip_cache)
        foreign = dict(model=path, geometry=envelope(mesh, clips), animation_resolution=resolution)
    return dict(schema=1, actors=rows, actor_count=len(rows), foreign=foreign, errors=errors,
                resources=resources, measurement="complete native skinned meshes, active skin counts, segment-scale compensation; native Pose/GetDemo masks; exact full-turn radial envelope for static bodies, otherwise half-frame and channel-extrema samples",
                limits="Geometry audit only: Player's shown-item binding can add runtime weapon scaling; clipping, camera projection, model visibility and visual composition require native screenshots; sampled envelopes are not a symbolic extremum proof.",
                user_files_modified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--romfs", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, action="append", required=True,
                        help="prepared mod layer, repeat from lowest to highest priority")
    parser.add_argument("--codec-resources", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in args.overlay:
        if not path.is_dir():
            parser.error("Prepared RomFS overlay does not exist: " + str(path))
    if args.codec_resources:
        app_runtime._resource_override = args.codec_resources.resolve()
    from ootrr_triforce.mod_codec import Codec
    started = time.monotonic()
    game = args.romfs.resolve()
    result = audit(game, Codec((game / "Pack/ZsDic.pack.zs").read_bytes()), [path.resolve() for path in args.overlay or ()])
    result["seconds"] = time.monotonic() - started
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(dict(actors=result["actor_count"], foreign=bool(result["foreign"]), errors=len(result["errors"]),
                          seconds=result["seconds"], output=str(args.output))))
    return bool(result["errors"])


if __name__ == "__main__":
    raise SystemExit(main())
