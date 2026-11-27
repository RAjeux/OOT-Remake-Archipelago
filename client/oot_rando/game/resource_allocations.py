"""Read and reserve exact resource allocations without shrinking native budgets."""
import struct
import zlib


def grow_resources(raw, growth_by_path):
    if raw[:6] != b'RESTBL':
        raise ValueError('Invalid RESTBL table.')
    version, block, count, names = struct.unpack_from('<IIII', raw, 6)
    if version != 1 or block != 160 or len(raw) != 22 + count * 8 + names * (block + 4):
        raise ValueError('Unsupported RESTBL format.')
    hashes = {}
    for index in range(count):
        position = 22 + index * 8
        hashes.setdefault(struct.unpack_from('<I', raw, position)[0], []).append(position + 4)
    named = {}
    for index in range(names):
        position = 22 + count * 8 + index * (block + 4)
        name = raw[position:position + block].split(b'\0', 1)[0].decode()
        named.setdefault(name, []).append(position + block)
    result, records, used = bytearray(raw), [], set()
    for path, growth in sorted(growth_by_path.items()):
        if type(growth) is not int or growth < 0:
            raise ValueError('Invalid resource growth.')
        if not growth:
            continue
        target = path.removesuffix('.zs')
        digest = zlib.crc32(target.encode())
        slots = named.get(target, hashes.get(digest, []))
        if len(slots) != 1 or slots[0] in used:
            raise ValueError('Missing or ambiguous allocation: ' + target)
        offset = slots[0]
        used.add(offset)
        before = struct.unpack_from('<I', raw, offset)[0]
        after = (before + growth + 4095) & ~4095
        if after >= 1 << 32:
            raise ValueError('Resource allocation too large.')
        struct.pack_into('<I', result, offset, after)
        records.append({'path': target, 'crc32': f'{digest:08x}', 'before': before, 'after': after})
    allowed = {offset + index for offset in used for index in range(4)}
    if any(a != b and index not in allowed for index, (a, b) in enumerate(zip(raw, result))):
        raise ValueError('Unexpected RESTBL change.')
    return bytes(result), records


def add_resources(raw, sizes_by_path):
    """Insert CRC entries for NEW resources (sorted table); existing ones refused."""
    if raw[:6] != b'RESTBL':
        raise ValueError('Invalid RESTBL table.')
    version, block, count, names = struct.unpack_from('<IIII', raw, 6)
    if version != 1 or block != 160 or len(raw) != 22 + count * 8 + names * (block + 4):
        raise ValueError('Unsupported RESTBL format.')
    entries = [struct.unpack_from('<II', raw, 22 + i * 8) for i in range(count)]
    known = {crc for crc, _ in entries}
    named = {raw[22 + count * 8 + i * (block + 4):][:block].split(b'\0', 1)[0].decode() for i in range(names)}
    records = []
    for path, size in sorted(sizes_by_path.items()):
        target = path.removesuffix('.zs')
        digest = zlib.crc32(target.encode())
        if digest in known or target in named or type(size) is not int or not 0 < size < 1 << 32:
            raise ValueError('Existing RESTBL entry or invalid size: ' + target)
        entries.append((digest, size))
        known.add(digest)
        records.append({'path': target, 'crc32': f'{digest:08x}', 'before': None, 'after': size})
    entries.sort()
    result = bytearray(raw[:6]) + struct.pack('<IIII', version, block, len(entries), names)
    for crc, size in entries:
        result.extend(struct.pack('<II', crc, size))
    result.extend(raw[22 + count * 8:])
    return bytes(result), records


def allocation(raw, path):
    """Current RESTBL allocation of a resource, or None when it has no entry."""
    version, block, count, names = struct.unpack_from('<IIII', raw, 6)
    target = path.removesuffix('.zs')
    for index in range(names):
        position = 22 + count * 8 + index * (block + 4)
        if raw[position:position + block].split(b'\0', 1)[0].decode() == target:
            return struct.unpack_from('<I', raw, position + block)[0]
    digest = zlib.crc32(target.encode())
    for index in range(count):
        crc, size = struct.unpack_from('<II', raw, 22 + index * 8)
        if crc == digest:
            return size
    return None


def _packed_member_kind(path):
    """Only reviewed real pack members, never soft ActorName references."""
    if (not isinstance(path, str) or not path or "\\" in path or "\0" in path
            or path.startswith(("/", "?", "Work/"))
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or len(path.encode("utf-8")) >= 160):
        raise ValueError("Invalid packed resource path.")
    kinds = (
        ("Actor/", ".engine__actor__ActorParam.bgyml", "ActorParam"),
        ("Component/ModelInfo/", ".engine__component__ModelInfo.bgyml", "ModelInfo"),
        ("Component/AnimationParam/", ".engine__component__AnimationParam.bgyml", "AnimationParam"),
        ("Component/EventPerformerParam/", ".engine__component__EventPerformerParam.bgyml", "EventPerformer"),
        ("AI/", ".ainb", "AI"),
    )
    for prefix, suffix, kind in kinds:
        if path.startswith(prefix) and path.endswith(suffix) and len(path) > len(prefix) + len(suffix):
            return kind
    raise ValueError("Unreviewed packed resource kind: " + path)


def _allocation_index(raw):
    """Keep exact offsets and native named collision overrides for one table."""
    if not isinstance(raw, bytes) or len(raw) < 22 or raw[:6] != b"RESTBL":
        raise ValueError("Invalid RESTBL table.")
    version, block, count, names = struct.unpack_from("<IIII", raw, 6)
    if version != 1 or block != 160 or len(raw) != 22 + count * 8 + names * (block + 4):
        raise ValueError("Unsupported RESTBL format.")
    hashed, named = {}, {}
    for i in range(count):
        offset = 22 + i * 8
        crc, size = struct.unpack_from("<II", raw, offset)
        hashed.setdefault(crc, []).append((offset + 4, size))
    for i in range(names):
        offset = 22 + count * 8 + i * (block + 4)
        field = raw[offset:offset + block]
        if b"\0" not in field:
            raise ValueError("Invalid RESTBL named entry.")
        path = field.split(b"\0", 1)[0].decode("utf-8")
        named.setdefault(path, []).append((offset + block, struct.unpack_from("<I", raw, offset + block)[0]))

    def lookup(path):
        slots = named.get(path, hashed.get(zlib.crc32(path.encode("utf-8")), ()))
        if len(slots) > 1:
            raise ValueError("Ambiguous resource allocation: " + path)
        return slots[0] if slots else None

    return lookup


def reserve_packed_resources(raw, native_raw, resources):
    """Reserve generated inner members from exact, immutable native peers.

    Each resource is ``dict(path, data, peer, peer_data)`` with real SARC member
    names and uncompressed bytes. ``native_raw`` is the original game's RESTBL,
    separate from the effective staged ``raw``. Never pass a previously grown
    table as the native baseline. Peer selection belongs to the pack producer.

    Keep the peer's parser allowance, plus positive 32-byte-aligned serialized
    growth and 1 KiB when the new body grows. Existing larger budgets survive.
    Shared member paths must contain identical bytes, including across packs;
    compatible peer descriptions coalesce to their greatest required budget.
    Both inputs remain untouched on invalid peers, conflicts or overflow.
    """
    current, native = _allocation_index(raw), _allocation_index(native_raw)
    jobs, peers, digests = {}, {}, {}
    required_keys = {"path", "data", "peer", "peer_data"}
    for resource in resources:
        if not isinstance(resource, dict) or set(resource) != required_keys:
            raise ValueError("Invalid packed resource reservation.")
        path, data, peer, peer_data = (resource[k] for k in ("path", "data", "peer", "peer_data"))
        kind = _packed_member_kind(path)
        if _packed_member_kind(peer) != kind:
            raise ValueError("Packed resource and native peer kinds differ: " + path)
        if (not isinstance(data, bytes) or not isinstance(peer_data, bytes)
                or not 0 < len(data) < 1 << 32 or not 0 < len(peer_data) < 1 << 32):
            raise ValueError("Invalid packed resource bytes: " + path)
        if peer in peers and peers[peer] != peer_data:
            raise ValueError("Conflicting native peer bytes: " + peer)
        peers[peer] = peer_data
        found = native(peer)
        if found is None or found[1] == 0 or found[1] < len(peer_data):
            raise ValueError("Missing or undersized native peer allocation: " + peer)
        # A generated alias may not borrow another native path's CRC slot.
        if path != peer and native(path) is not None:
            raise ValueError("Packed alias collides with a native resource: " + path)
        minimum = found[1]
        if len(data) > len(peer_data):
            minimum += ((len(data) + 31) & ~31) - ((len(peer_data) + 31) & ~31) + 0x400
        if minimum >= 1 << 32:
            raise ValueError("Packed resource allocation too large: " + path)
        crc = zlib.crc32(path.encode("utf-8"))
        if crc in digests and digests[crc] != path:
            raise ValueError("Generated packed resource CRC collision: " + path)
        digests[crc] = path
        if path in jobs:
            job = jobs[path]
            if job["data"] != data:
                raise ValueError("Conflicting shared packed resource bytes: " + path)
            job["minimum"] = max(job["minimum"], minimum)
            job["peers"].add(peer)
        else:
            jobs[path] = {"data": data, "minimum": minimum, "peers": {peer}, "kind": kind}

    result, additions, records = bytearray(raw), {}, []
    for path, job in sorted(jobs.items()):
        found = current(path)
        before = found[1] if found else None
        after = max(before or 0, job["minimum"])
        if after == before:
            continue
        if found:
            struct.pack_into("<I", result, found[0], after)
        else:
            additions[path] = after
        records.append({"path": path, "crc32": f"{zlib.crc32(path.encode('utf-8')):08x}",
                        "before": before, "after": after, "minimum": job["minimum"],
                        "size": len(job["data"]), "kind": job["kind"], "peers": sorted(job["peers"])})
    amended = bytes(result)
    if additions:
        amended, _ = add_resources(amended, additions)
    return amended, records
