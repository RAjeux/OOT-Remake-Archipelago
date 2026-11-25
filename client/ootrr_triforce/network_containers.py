"""AP containers stay recoverable until their dropped reward is collected.

Breaking a pot, crate, rock, shrub, hive or flying pot never completes its AP
location. A native scene-reset row lets an abandoned drop be tried again; an
inverted AP presence flag hides every layout variant after successful pickup.
Run after the source pickup packs/maps have been prepared. No callbacks, item
grants, receipt cursors or current save values are written here.
"""
import copy
import json
from pathlib import Path
import re
import struct

from oot_rando.formats import byml_codec as byml

from .cursor_resource import append_saved_bools
from .mod_codec import Codec
from .story_fixes import REST

DATA = "GameData/GameDataList.Product.110.byml.zs"
TABLE = "Bool64bitKey"
# Native flying-pot/ordinary enemy rows use 0x118. Unlike permanent 0x18,
# the 0x100 bit resets the actor on each Banc change (ainb/start.rs).
SCENE_RESET = 280
CLASSES = {
    "pot": {"Obj_Pot_A_0" + str(number) for number in range(1, 9)},
    "crate": {"Obj_BrokenBox_A_01", "Obj_BrokenBox_A_03"},
    "flying_pot": {"Enemy_FlyingPot_SpiritTemple", "Enemy_FlyingPot_ShadowTemple", "Enemy_FlyingPot_IceCavern"},
    "beehive": {"Obj_Kokiri_Beehive_A_01"},
    "rock": {"Obj_LiftRock_A_01"},
    "grass": {"Obj_Plant_Grass_A_01"},
}


def _invalid(detail):
    return ValueError("Unsupported AP container persistence layout: " + str(detail))


def _records(records, kinds):
    """Use trusted source metadata and one AP pickup/flag per complete source."""
    from .network_catalog import SOURCES, flag_name, murmur3
    out, identities, hashes, flags, digests = [], set(), {}, set(), set()
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("metadata"), dict):
            raise _invalid("source metadata")
        metadata = record["metadata"]
        kind = metadata.get("kind")
        if kind not in kinds:
            continue
        name = record.get("name")
        pickup = record.get("pickup")
        if (name not in SOURCES or metadata != SOURCES[name]
                or (kind == "container" and metadata.get("native_kind") not in CLASSES)
                or not isinstance(pickup, str) or not re.fullmatch(r"Obj_AP_[A-Za-z0-9_]+_GH", pickup)
                or record.get("flag_name") != flag_name(name) or name in identities
                or record["flag_name"] in flags):
            raise _invalid(name)
        digest = murmur3(record["flag_name"])
        if digest in digests:
            raise _invalid("source flag collision")
        if "flag_hash" in record and (type(record["flag_hash"]) is not int or record["flag_hash"] != digest):
            raise _invalid(name)
        seen = set()
        for variant in metadata["variants"]:
            key = variant["file"], variant["actor"]
            if (variant.get("via") != ("actor" if kind == "pickup" else "drop") or key in seen
                    or not re.fullmatch(r"[1-9][0-9]*", variant["actor"])
                    or not 0 < int(variant["actor"]) < 2**64):
                raise _invalid(name)
            actor_hash = int(variant["actor"])
            if actor_hash in hashes and hashes[actor_hash] != name:
                raise _invalid("shared container identity")
            hashes[actor_hash] = name
            seen.add(key)
        if not seen or metadata.get("collection") != "pickup":
            raise _invalid(name)
        identities.add(name)
        flags.add(record["flag_name"])
        digests.add(digest)
        out.append(dict(record, flag_hash=digest))
    return out


def container_records(records):
    return _records(records, {"container"})


def presence_records(records):
    return _records(records, {"pickup", "skull"})


def _hashes(records):
    return {int(variant["actor"]) for record in records for variant in record["metadata"]["variants"]}


def _row_index(doc, group):
    rows = doc["root"].get("Data", {}).get(group)
    if not isinstance(rows, list):
        raise _invalid(group)
    result = {}
    for row in rows:
        if not isinstance(row, dict) or type(row.get("Hash")) not in (int, byml.U32, byml.U64, byml.I64):
            raise _invalid(group)
        value = int(row["Hash"])
        if value in result:
            raise _invalid("duplicate " + group + " hash")
        result[value] = row
    return result


def _scene_rows(raw, hashes):
    """Splice only changed row maps, preserving all native save/layout offsets."""
    if raw[:2] not in (b"YB", b"BY"):
        raise _invalid(DATA)
    out = bytearray(raw)
    endian = "<" if raw[:2] == b"YB" else ">"
    order = "little" if endian == "<" else "big"
    word = struct.Struct(endian + "I")
    def read(position):
        return word.unpack_from(out, position)[0]
    def put(position, value):
        word.pack_into(out, position, value)
    def small(position):
        return int.from_bytes(out[position:position + 3], order)
    table = read(4)
    if not table or out[table] != 0xc2:
        raise _invalid("BYML keys")
    keys = {}
    for index in range(small(table + 1)):
        start = table + read(table + 4 + 4 * index)
        keys[out[start:out.index(0, start)].decode()] = index
    def fields(node):
        if out[node] != 0xc1:
            raise _invalid("BYML dictionary")
        return {small(node + 4 + index * 8): node + 4 + index * 8
                for index in range(small(node + 1))}
    def child(node, name, kind):
        position = fields(node).get(keys.get(name))
        if position is None or out[position + 3] != kind:
            raise _invalid(name)
        target = read(position + 4)
        if out[target] != kind:
            raise _invalid(name)
        return target
    data = child(read(12), "Data", 0xc1)
    rows = child(data, TABLE, 0xc0)
    count = small(rows + 1)
    first = (rows + 4 + count + 3) & ~3
    found = set()
    for index in range(count):
        if out[rows + 4 + index] != 0xc1:
            raise _invalid(TABLE)
        pointer = first + 4 * index
        start = read(pointer)
        slots = fields(start)
        hash_at = slots.get(keys.get("Hash"))
        if hash_at is None or out[hash_at + 3] != 0xd5:
            raise _invalid("64-bit actor hash")
        value = struct.unpack_from(endian + "Q", out, read(hash_at + 4))[0]
        if value not in hashes:
            continue
        if value in found:
            raise _invalid("duplicate actor row")
        found.add(value)
        reset = slots.get(keys.get("ResetTypeValue"))
        save = slots.get(keys.get("SaveFileIndex"))
        if (reset is None or save is None or out[reset + 3] not in (0xd1, 0xd3)
                or read(reset + 4) not in (24, 88, SCENE_RESET)
                or out[save + 3] not in (0xd1, 0xd3) or read(save + 4) != 0):
            raise _invalid(value)
        extra = slots.get(keys.get("ExtraByte"))
        if read(reset + 4) == SCENE_RESET and extra is None:
            continue
        # Redirect just this array element. Hash/SaveFileIndex, the array count,
        # every other row and all save size metadata keep their original bytes.
        kept = [position for position in slots.values() if position != extra]
        clone = bytearray(b"\xc1" + len(kept).to_bytes(3, order))
        for position in kept:
            entry = bytearray(out[position:position + 8])
            if position == reset:
                word.pack_into(entry, 4, SCENE_RESET)
            clone.extend(entry)
        out.extend(bytes(-len(out) % 4))
        new_position = len(out)
        out.extend(clone)
        put(pointer, new_position)
    if found != hashes:
        raise _invalid("missing actor persistence row")
    return bytes(out)


def _ensure_source_bools(raw, records):
    bools = _row_index(byml.load(raw), "Bool")
    missing = []
    for record in records:
        row = bools.get(record["flag_hash"])
        if row is not None:
            if (row.get("DefaultValue") is not False or row.get("ResetTypeValue") != 8
                    or row.get("SaveFileIndex") != 0):
                raise _invalid(record["flag_name"])
        else:
            missing.append(record["flag_hash"])
    return append_saved_bools(raw, missing)


def patch_container_gamedata(raw, records):
    """Add missing AP Bool declarations; make only source holders scene-local."""
    records = container_records(records)
    if not records:
        return raw
    before = byml.load(raw)
    rows = _row_index(before, TABLE)
    wanted = _hashes(records)
    for actor_hash in wanted:
        row = rows.get(actor_hash)
        if row is None or row.get("ResetTypeValue") not in (24, 88, SCENE_RESET) or row.get("SaveFileIndex") != 0:
            raise _invalid(actor_hash)
    output = _ensure_source_bools(raw, records)
    after_bools = byml.load(output)
    result = _scene_rows(output, wanted)
    expected = copy.deepcopy(after_bools)
    expected_rows = _row_index(expected, TABLE)
    for actor_hash in wanted:
        row = expected_rows[actor_hash]
        row["ResetTypeValue"] = type(row["ResetTypeValue"])(SCENE_RESET)
        row.pop("ExtraByte", None)
    if byml.load(result) != expected:
        raise _invalid("unexpected GameData change")
    return result


def _actor(doc, actor_hash):
    matches = [actor for actor in doc["root"].get("Actors", ()) if actor.get("Hash") == actor_hash]
    if len(matches) != 1:
        raise _invalid(actor_hash)
    return matches[0]


def patch_container_banc(raw, native_raw, path, records):
    """Gate the physical holder only; never alter its AP drop or other actors."""
    records = container_records(records)
    doc, native = byml.load(raw), byml.load(native_raw)
    before = copy.deepcopy(doc)
    for record in records:
        for variant in record["metadata"]["variants"]:
            if variant["file"] != path:
                continue
            actor_hash = int(variant["actor"])
            source = _actor(native, actor_hash)
            actor = _actor(doc, actor_hash)
            if (source.get("Gyaml") not in CLASSES[record["metadata"]["native_kind"]]
                    or "Presence" in source or actor.get("Gyaml") != source["Gyaml"]
                    or source.get("Dynamic", {}).get("Drop__DropActor", "") != variant["expected_actor"]
                    or actor.get("Dynamic", {}).get("Drop__DropActor") != record["pickup"]):
                raise _invalid(record["name"])
            presence = {"FlagName": record["flag_name"], "IsCheckLazy": False, "IsNegation": True}
            if "Presence" in actor and actor["Presence"] != presence:
                raise _invalid(record["name"])
            actor["Presence"] = presence
    if doc == before:
        return raw
    result = byml.dump(doc)
    if byml.load(result) != doc:
        raise _invalid(path)
    return result


def prepare_network_containers(romfs, mod, records):
    """Validate the full bundle before writing any resource in the mod overlay."""
    from oot_rando.game.resource_allocations import grow_resources
    records = container_records(records)
    if not records:
        return {"version": 1, "containers": 0, "files": 0}
    romfs, mod = Path(romfs), Path(mod)
    if (mod.name != "romfs" or mod.parent.name != "Archipelago"
            or mod.resolve().is_relative_to(romfs.resolve())
            or romfs.resolve().is_relative_to(mod.resolve())):
        raise _invalid(mod)
    codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
    frames, raws = {}, {}
    def frame(path):
        if path not in frames:
            staged = mod / path
            frames[path] = (staged if staged.is_file() else romfs / path).read_bytes()
        return frames[path]
    def raw(path):
        if path not in raws:
            raws[path] = codec.decode(frame(path))
        return raws[path]
    native_rows = _row_index(byml.load(codec.decode((romfs / DATA).read_bytes())), TABLE)
    prepared_rows = _row_index(byml.load(raw(DATA)), TABLE)
    for actor_hash in _hashes(records):
        native = native_rows.get(actor_hash)
        prepared = prepared_rows.get(actor_hash)
        if (native is None or prepared is None or native.get("ResetTypeValue") not in (88, SCENE_RESET)
                or {key: value for key, value in native.items() if key not in ("ResetTypeValue", "ExtraByte")}
                != {key: value for key, value in prepared.items() if key not in ("ResetTypeValue", "ExtraByte")}):
            raise _invalid(actor_hash)
    paths = sorted({variant["file"] for record in records for variant in record["metadata"]["variants"]})
    changed = {}
    for path in paths:
        native = codec.decode((romfs / path).read_bytes())
        changed[path] = patch_container_banc(raw(path), native, path, records)
    changed[DATA] = patch_container_gamedata(raw(DATA), records)
    growth = {path: max(0, len(content) - len(raw(path))) for path, content in changed.items()}
    table, allocations = grow_resources(raw(REST), growth)
    changed[REST] = table
    encoded = {path: codec.encode(content, frame(path)) for path, content in changed.items() if content != raw(path)}
    for path, content in encoded.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return {"version": 1, "containers": len(records), "variants": sum(len(record["metadata"]["variants"]) for record in records),
            "files": len(encoded), "allocations": allocations}


def presence_expression(flag, vanilla):
    """One unsaved native condition for a source/layout's original presence."""
    from .network_catalog import murmur3
    if (not isinstance(vanilla, dict) or set(vanilla) != {"FlagName", "IsNegation", "IsCheckLazy"}
            or not isinstance(vanilla["FlagName"], str) or not vanilla["FlagName"]
            or type(vanilla["IsNegation"]) is not bool or type(vanilla["IsCheckLazy"]) is not bool):
        raise _invalid("native presence condition")
    suffix = murmur3(json.dumps(vanilla, sort_keys=True, separators=(",", ":")))
    return flag.replace("Archipelago.Source.", "Archipelago.SourcePresence.", 1) + "." + str(suffix)


def patch_network_presence_banc(raw, native_raw, path, records):
    """Conjoin AP completion with the native gate, preserving all Banc links."""
    records = presence_records(records)
    doc, native = byml.load(raw), byml.load(native_raw)
    before, expressions = copy.deepcopy(doc), {}
    for record in records:
        for variant in record["metadata"]["variants"]:
            if variant["file"] != path:
                continue
            actor_hash = int(variant["actor"])
            source, actor = _actor(native, actor_hash), _actor(doc, actor_hash)
            if record["metadata"]["kind"] == "skull":
                # Native gold tokens are implicit, not a Dynamic drop override.
                valid = (source.get("Gyaml") == "Enemy_Skulltula_Gold"
                         and source.get("Dynamic", {}).get("Drop__DropActor", "Obj_Token_Gold") == variant["expected_actor"]
                         and actor.get("Gyaml") == source["Gyaml"]
                         and actor.get("Dynamic", {}).get("Drop__DropActor") == record["pickup"])
            else:
                valid = source.get("Gyaml") == variant["expected_actor"] and actor.get("Gyaml") == record["pickup"]
            if not valid:
                raise _invalid(record["name"])
            vanilla = source.get("Presence")
            if vanilla is None:
                wanted = {"FlagName": record["flag_name"], "IsCheckLazy": False, "IsNegation": True}
            else:
                expression = presence_expression(record["flag_name"], vanilla)
                expressions[expression] = {"flag_name": record["flag_name"], "vanilla": copy.deepcopy(vanilla)}
                wanted = {"FlagName": expression, "IsCheckLazy": vanilla["IsCheckLazy"], "IsNegation": False}
            if actor.get("Presence") not in (vanilla, wanted):
                raise _invalid("changed source presence: " + record["name"])
            actor["Presence"] = wanted
    if doc == before:
        return raw, expressions
    result = byml.dump(doc)
    if byml.load(result) != doc:
        raise _invalid(path)
    return result, expressions


def patch_network_presence_gamedata(raw, records, expressions):
    """The native BoolExp VM preserves quest/boss gates without a saved value."""
    from .network_catalog import murmur3
    records = presence_records(records)
    if not records:
        if expressions:
            raise _invalid("orphan presence expression")
        return raw
    output = _ensure_source_bools(raw, records)
    doc = byml.load(output)
    before = copy.deepcopy(doc)
    data = doc["root"]["Data"]
    kinds = {}
    for kind in ("Bool", "BoolExp"):
        for key in _row_index(doc, kind):
            if key in kinds:
                raise _invalid("ambiguous presence flag")
            kinds[key] = kind
    known = {int(row["Hash"]) for rows in data.values() if isinstance(rows, list)
             for row in rows if isinstance(row, dict) and "Hash" in row}
    bool_expressions = _row_index(doc, "BoolExp")
    flags = {record["flag_name"] for record in records}
    for name, spec in sorted(expressions.items()):
        flag, vanilla = spec["flag_name"], spec["vanilla"]
        if flag not in flags or name != presence_expression(flag, vanilla):
            raise _invalid("presence expression identity")
        kind = kinds.get(murmur3(vanilla["FlagName"]))
        if kind not in ("Bool", "BoolExp"):
            raise _invalid("undeclared native presence flag")
        # Native postfix instructions: push Bool=0 / BoolExp=10, NOT=5,
        # AND=3. Preserve either sense of the original gate before the AND.
        program = [[0, murmur3(flag)], [5], [0 if kind == "Bool" else 10, murmur3(vanilla["FlagName"])]]
        if vanilla["IsNegation"]:
            program.append([5])
        program.append([3])
        row = {"Hash": byml.U32(murmur3(name)), "ResetTypeValue": 0, "SaveFileIndex": -1,
               "Values": [[byml.U64(value) for value in instruction] for instruction in program]}
        existing = bool_expressions.get(int(row["Hash"]))
        if existing is not None:
            if existing != row:
                raise _invalid("changed presence expression")
        elif int(row["Hash"]) in known:
            raise _invalid("presence expression hash collision")
        else:
            data["BoolExp"].append(row)
            bool_expressions[int(row["Hash"])] = row
            known.add(int(row["Hash"]))
    if doc == before:
        return output
    result = byml.dump(doc)
    if byml.load(result) != doc or doc["root"]["MetaData"] != before["root"]["MetaData"]:
        raise _invalid("unexpected presence GameData change")
    return result


def prepare_network_presence(romfs, mod, records):
    """Hide collected AP pickups/skulls without treating a kill as collection."""
    from oot_rando.game.resource_allocations import grow_resources
    records = presence_records(records)
    if not records:
        return {"version": 1, "sources": 0, "files": 0}
    romfs, mod = Path(romfs), Path(mod)
    if (mod.name != "romfs" or mod.parent.name != "Archipelago"
            or mod.resolve().is_relative_to(romfs.resolve())
            or romfs.resolve().is_relative_to(mod.resolve())):
        raise _invalid(mod)
    codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
    frames, raws = {}, {}
    def frame(path):
        if path not in frames:
            target = mod / path
            frames[path] = (target if target.is_file() else romfs / path).read_bytes()
        return frames[path]
    def raw(path):
        if path not in raws:
            raws[path] = codec.decode(frame(path))
        return raws[path]
    paths = sorted({variant["file"] for record in records for variant in record["metadata"]["variants"]})
    changed, expressions = {}, {}
    for path in paths:
        native = codec.decode((romfs / path).read_bytes())
        content, programs = patch_network_presence_banc(raw(path), native, path, records)
        changed[path] = content
        for name, spec in programs.items():
            if name in expressions and expressions[name] != spec:
                raise _invalid("conflicting native presence")
            expressions[name] = spec
    changed[DATA] = patch_network_presence_gamedata(raw(DATA), records, expressions)
    growth = {path: max(0, len(content) - len(raw(path))) for path, content in changed.items()}
    table, allocations = grow_resources(raw(REST), growth)
    changed[REST] = table
    encoded = {path: codec.encode(content, frame(path)) for path, content in changed.items() if content != raw(path)}
    for path, content in encoded.items():
        target = mod / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return {"version": 1, "sources": len(records), "variants": sum(len(record["metadata"]["variants"]) for record in records),
            "expressions": len(expressions), "files": len(encoded), "allocations": allocations}
