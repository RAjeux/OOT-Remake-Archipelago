"""Native BFRES10.4 scalar Hermite sampling for the maintainer layout tool.

The modern quantized format uses value/tangent pairs, an eight-byte tangent
scale/offset header and unsigned keys. This differs from older BFRES cubic
coefficient arrays. Format facts were checked against current native files and
the independent same-game reader NuxsGit/HookyMod, commit
7ee7c5eaee83e206d1ac17320a2913302320dc7c, hookymod/animation.py.
No reader code or game animation data is bundled with the client runtime.
"""
import bisect, copy, math
from shop_geometry import Reader


def resolve_shop_clip(available, mode, common='Pose_Common'):
    """Resolve retained native shop body state and its Root/body blend mask."""
    if mode=='Pose_Shop':names=('Pose_Shop',common)
    elif mode=='Pose_Stoped':names=('Pose_Stoped','Pose_Shop',common)
    elif mode in ('Rotate_Shop','Rotate_Stoped'):names=(mode,)
    else:raise ValueError('Unknown native shop animation mode')
    for name in names:
        if available.get(name) is not None:
            clip=copy.deepcopy(available[name])
            clip['tracks']={bone:track for bone,track in clip['tracks'].items()
                            if (bone=='Root')==mode.startswith('Rotate_')}
            return name,clip
    return None,None

def curve(reader, offset):
    flags = reader.u16(offset + 16)
    count = reader.u16(offset + 18)
    if not 0 < count <= 4096:
        raise ValueError('Invalid native curve keys')
    frames = reader.u64(offset)
    keys = reader.u64(offset + 8)
    ft, kt, kind = (flags & 3, flags >> 2 & 3, flags >> 4 & 7)
    if ft == 0:
        times = list(reader.get(frames, str(count) + 'f')) if count > 1 else [reader.get(frames, 'f')]
    elif ft == 1:
        times = [reader.get(frames + i * 2, 'H') for i in range(count)]
    elif ft == 2:
        times = [reader.u8(frames + i) for i in range(count)]
    else:
        raise ValueError('Unknown native frame type')
    if ft:
        frame_scale = reader.get(offset + 32, 'f') or (1 / 32 if ft == 1 else 1.0)
        times = [v * frame_scale for v in times]
    if any((not math.isfinite(v) or v < 0 for v in times)) or any((a > b for a, b in zip(times, times[1:]))):
        raise ValueError('Invalid native frame order ' + str((offset, ft, times[:16])))
    if kind not in (0, 1, 2, 4):
        raise ValueError('Unsupported native skeletal curve')
    if kind != 0 or kt not in (0, 1, 2) or flags & 0x80:
        raise ValueError('Unsupported native compressed Hermite curve')
    components = 2
    fmt, size = {0: ('f', 4), 1: ('H', 2), 2: ('B', 1)}[kt]
    quantized = kt != 0 or bool(flags & 0x800)
    header = 8 if quantized else 0
    values = [[reader.get(keys + header + (i * components + k) * size, fmt) for k in range(components)] for i in range(count)]
    scale = reader.get(offset + 36, 'f') if quantized else 1.
    bias = reader.get(offset + 40, 'f') if quantized else 0.
    tangent_scale = reader.get(keys, 'f') if quantized else 1.
    tangent_bias = reader.get(keys + 4, 'f') if quantized else 0.
    if quantized and kt == 0:
        scale = scale or 1.
        tangent_scale = tangent_scale or 1.
    if not all((math.isfinite(v) for row in values for v in row)) or not math.isfinite(scale + bias):
        raise ValueError('Invalid native curve values')
    values = [[v * scale + bias, t * tangent_scale + tangent_bias] for v, t in values]
    return dict(times=times, keys=values, kind=kind, target=reader.u32(offset + 20))

def evaluate(curve, frame):
    frames = curve['times']
    index = max(0, min(len(frames) - 1, bisect.bisect_right(frames, frame) - 1))
    value, tangent = curve['keys'][index]
    if index + 1 == len(frames):
        return value
    duration = frames[index + 1] - frames[index]
    u = max(0.0, min(1.0, (frame - frames[index]) / duration))
    following, next_tangent = curve['keys'][index + 1]
    return (2 * u ** 3 - 3 * u * u + 1) * value + (u ** 3 - 2 * u * u + u) * tangent * duration + (-2 * u ** 3 + 3 * u * u) * following + (u ** 3 - u * u) * next_tangent * duration

def animation(raw, name='Pose_Common'):
    reader = Reader(raw)
    hits = []
    offset = raw.find(b'FSKA')
    while offset >= 0:
        if reader.text(reader.u64(offset + 8)) == name:
            hits.append(offset)
        offset = raw.find(b'FSKA', offset + 1)
    if not hits:
        return None
    if len(hits) != 1:
        raise ValueError('Ambiguous native skeletal animation')
    offset = hits[0]
    count = reader.u16(offset + 76)
    array = reader.u64(offset + 40)
    if count > 1024:
        raise ValueError('Invalid native track count')
    tracks = {}
    for i in range(count):
        start = array + i * 56
        name = reader.text(reader.u64(start))
        flags = reader.u32(start + 40)
        data = reader.u64(start + 16)
        base = {}
        for bit, key, fmt, size in ((8, 'scale', '3f', 12), (16, 'rotate', '4f', 16), (32, 'translate', '3f', 12)):
            if flags & bit:
                base[key] = list(reader.get(data, fmt))
                data += size
        curves = [curve(reader, reader.u64(start + 8) + j * 48) for j in range(reader.u8(start + 46))]
        if name in tracks:
            raise ValueError('Duplicate native animation bone')
        tracks[name] = dict(base=base, curves=curves, flags=flags)
    length = reader.u32(offset + 64)
    if not 0 < length <= 4096:
        raise ValueError('Invalid native pose length')
    return dict(tracks=tracks, length=length, euler=bool(reader.u32(offset + 4) & 4096))

def pose_at(animation, frame, rest):
    pose = {}
    for name, track in animation['tracks'].items():
        if name not in rest:
            continue
        base = copy.deepcopy({key: list(rest[name][key]) for key in ('scale', 'rotate', 'translate')})
        base.update(copy.deepcopy(track['base']))
        for curve in track['curves']:
            target = curve['target']
            if target in (4, 8, 12):
                key, index = ('scale', (target - 4) // 4)
            elif target in (16, 20, 24):
                key, index = ('translate', (target - 16) // 4)
            elif target in (32, 36, 40, 44):
                key, index = ('rotate', (target - 32) // 4)
            else:
                raise ValueError('Unsupported native bone channel')
            base[key][index] = evaluate(curve, frame)
        base['euler'] = animation['euler']
        base['ssc'] = bool(track['flags'] & 8388608)
        pose[name] = base
    return pose
