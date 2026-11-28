"""Bounded read-only BFRES v10 mesh/pose measurements for native shop trials."""
import math
import struct


def skin_influences(indices, weights, count):
    """FVTX's active count excludes padding channels in packed attributes."""
    if type(count) is not int or not 2<=count<=8 or len(indices)<count or len(weights)<count:
        raise ValueError('Invalid native active skin count')
    indices,weights=list(indices[:count]),list(weights[:count])
    if any(type(index) is not int or index<0 for index in indices) or any(not math.isfinite(v) or v<0 for v in weights):
        raise ValueError('Invalid native active skin influence')
    total=sum(weights)
    if total<=0:
        weights[0],total=1.,1.
    return indices,[v/total for v in weights]

def identity():
    return [[float(i == j) for j in range(4)] for i in range(4)]

def mul(a, b):
    return [[sum((a[i][k] * b[k][j] for k in range(4))) for j in range(4)] for i in range(4)]

def point(a, p):
    return [sum((a[i][k] * p[k] for k in range(3))) + a[i][3] for i in range(3)]

def matrix(s, r, t, euler):
    if euler:
        cx, sx = (math.cos(r[0]), math.sin(r[0]))
        cy, sy = (math.cos(r[1]), math.sin(r[1]))
        cz, sz = (math.cos(r[2]), math.sin(r[2]))
        v = [[cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx], [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx], [-sy, cy * sx, cy * cx]]
    else:
        x, y, z, w = r
        v = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    out = identity()
    for i in range(3):
        for j in range(3):
            out[i][j] = v[i][j] * s[j]
        out[i][3] = t[i]
    return out

class Reader:

    def __init__(self, b):
        if not isinstance(b, bytes) or b[:4] != b'FRES' or b[8:12] != bytes.fromhex('00040a00'):
            raise ValueError('Expected native BFRES v10')
        self.b = b

    def get(self, p, fmt):
        size = struct.calcsize('<' + fmt)
        if not isinstance(p, int) or p < 0 or p + size > len(self.b):
            raise ValueError('BFRES field leaves file')
        v = struct.unpack_from('<' + fmt, self.b, p)
        return v[0] if len(v) == 1 else v

    def u64(self, p):
        return self.get(p, 'Q')

    def u32(self, p):
        return self.get(p, 'I')

    def u16(self, p):
        return self.get(p, 'H')

    def u8(self, p):
        return self.get(p, 'B')

    def text(self, p):
        n = self.u16(p)
        if n > 512 or p + 2 + n > len(self.b):
            raise ValueError('BFRES name leaves file')
        return self.b[p + 2:p + 2 + n].decode('utf-8')

def attribute(reader, p, fmt, component):
    if fmt in (6149, 6405, 5893):
        return reader.get(p + component * 4, 'f')
    if fmt in (4613, 5381):
        return reader.get(p + component * 2, 'e')
    if fmt == 4610:
        return max(-1, reader.get(p + component * 2, 'h') / 32767)
    if fmt == 4609:
        return reader.u16(p + component * 2) / 65535
    if fmt in (2307, 2819, 515):
        return reader.u8(p + component)
    if fmt in (2305, 2817, 513):
        return reader.u8(p + component) / 255
    raise ValueError('Unsupported native vertex format: ' + hex(fmt))

def skeleton(reader):
    fmdl = reader.u64(40)
    if reader.b[fmdl:fmdl + 4] != b'FMDL':
        raise ValueError('Missing native model')
    sk = reader.u64(fmdl + 24)
    n = reader.u16(sk + 56)
    ba = reader.u64(sk + 16)
    if not 0 < n <= 1024:
        raise ValueError('Invalid bone count')
    bones = []
    for i in range(n):
        o = ba + i * 88
        parent = reader.get(o + 34, 'h')
        if not -1 <= parent < i:
            raise ValueError('Invalid native bone parent')
        bones.append(dict(name=reader.text(reader.u64(o)), parent=parent, euler=bool(reader.u32(o + 44) & 4096), ssc=bool(reader.u32(o + 44) & 8388608), scale=reader.get(o + 48, '3f'), rotate=reader.get(o + 60, '4f'), translate=reader.get(o + 76, '3f')))
    ns, nr = (reader.u16(sk + 58), reader.u16(sk + 60))
    if ns + nr > 2048:
        raise ValueError('Invalid native matrix palette')
    palette = [reader.u16(reader.u64(sk + 24) + i * 2) for i in range(ns + nr)]
    if any((i >= n for i in palette)):
        raise ValueError('Invalid palette bone')
    inverses = []
    for i in range(ns):
        values = reader.get(reader.u64(sk + 32) + i * 48, '12f')
        inverses.append([list(values[k * 4:k * 4 + 4]) for k in range(3)] + [[0.0, 0.0, 0.0, 1.0]])
    return (fmdl, bones, palette, inverses)

def worlds(bones, pose=None):
    out = []
    local_scales = []
    for bone in bones:
        values = dict(bone)
        if pose and bone['name'] in pose:
            changes = pose[bone['name']]
            for key in ('scale', 'rotate', 'translate'):
                if key in changes:
                    values[key] = changes[key]
            if 'rotate' in changes:
                values['euler'] = changes.get('euler', True)
            if 'ssc' in changes:
                values['ssc'] = values.get('ssc', False) or changes['ssc']
        local = matrix(values['scale'], values['rotate'], values['translate'], values['euler'])
        if bone['parent'] >= 0 and values.get('ssc'):
            scales = local_scales[bone['parent']]
            if any((abs(v) < 1e-08 for v in scales)):
                raise ValueError('Singular compensated parent scale')
            for row in range(3):
                for col in range(3):
                    local[row][col] /= scales[row]
        out.append(mul(out[bone['parent']], local) if bone['parent'] >= 0 else local)
        local_scales.append(values['scale'])
    return out


class PreparedMesh:
    """Decode vertex bindings once, then sample complete skinned poses quickly.

    NumPy is a maintainer dependency only. The game-facing client reads the
    resulting small numeric profiles and never imports this module.
    """

    def __init__(self, raw):
        import numpy as np
        self.np = np
        reader = Reader(raw)
        model, self.bones, palette, inverse = skeleton(reader)
        self.palette = np.asarray(palette, dtype=np.int32)
        self.inverse = np.asarray(inverse, dtype=np.float64)
        self.vertex_groups = []
        data = reader.u64(0x170)
        shapes = reader.u64(model + 0x28)
        count = reader.u16(model + 0x6a)
        if not 0 < count <= 1024 or data >= len(raw):
            raise ValueError('Invalid native model shapes')
        seen = set()
        for shape in range(count):
            vertex = reader.u64(shapes + shape * 0x60 + 0x10)
            if vertex in seen:
                continue
            seen.add(vertex)
            vertices = reader.u32(vertex + 0x50)
            skin = reader.u8(vertex + 0x54)
            attributes, buffers = reader.u8(vertex + 0x4c), reader.u8(vertex + 0x4d)
            if not 0 < vertices <= 250000 or not 0 < skin <= 8 or not 0 < buffers <= 8 or not 0 < attributes <= 64:
                raise ValueError('Unsupported native vertex binding')
            starts, strides = [], []
            start = data + reader.u32(vertex + 0x48)
            for i in range(buffers):
                starts.append(start)
                strides.append(reader.u32(reader.u64(vertex + 0x38) + i * 16))
                start += reader.u32(reader.u64(vertex + 0x30) + i * 16) + 7 & ~7
            fields = {}
            for i in range(attributes):
                entry = reader.u64(vertex + 8) + i * 16
                buffer = reader.u16(entry + 0xe)
                if buffer >= buffers:
                    raise ValueError('Invalid native vertex stream')
                fields[reader.text(reader.u64(entry))] = (starts[buffer] + reader.u16(entry + 0xc), strides[buffer], reader.u32(entry + 8))
            if not {'_p0', '_i0'} <= fields.keys() or skin > 1 and '_w0' not in fields:
                raise ValueError('Missing native skin attributes')
            def field(name, components):
                offset, stride, fmt = fields[name]
                return np.asarray([[attribute(reader, offset + i * stride, fmt, k) for k in range(components)]
                                   for i in range(vertices)])
            positions = np.concatenate((field('_p0', 3), np.ones((vertices, 1))), axis=1)
            fmt = fields['_i0'][2]
            width = 4 if fmt >> 8 == 0xb else 2 if fmt >> 8 == 9 else 1
            indices = field('_i0', width).astype(np.int32)
            if skin == 1:
                if np.any(indices[:, 0] >= len(palette)):
                    raise ValueError('Rigid vertex leaves native matrix palette')
                weights = None
            else:
                fmt = fields['_w0'][2]
                width = 4 if fmt >> 8 == 0xb else 2 if fmt >> 8 == 9 else 1
                weights = field('_w0', width)
                if skin > 4:
                    if not {'_i1', '_w1'} <= fields.keys():
                        raise ValueError('Missing secondary native skin influences')
                    fmt = fields['_i1'][2]
                    width = 4 if fmt >> 8 == 0xb else 2 if fmt >> 8 == 9 else 1
                    indices = np.concatenate((indices, field('_i1', width).astype(np.int32)), axis=1)
                    fmt = fields['_w1'][2]
                    width = 4 if fmt >> 8 == 0xb else 2 if fmt >> 8 == 9 else 1
                    weights = np.concatenate((weights, field('_w1', width)), axis=1)
                active=[skin_influences(i,w,skin) for i,w in zip(indices.tolist(),weights.tolist())]
                indices=np.asarray([i for i,w in active],dtype=np.int32)
                weights=np.asarray([w for i,w in active],dtype=np.float64)
                if indices.shape != weights.shape or np.any(indices[weights > 0] >= len(inverse)):
                    raise ValueError('Smooth vertex leaves native matrix palette')
            self.vertex_groups.append((positions, indices, weights))
        self.vertices = sum(len(group[0]) for group in self.vertex_groups)

    def bounds(self, pose=None):
        np = self.np
        matrices = np.asarray(worlds(self.bones, pose), dtype=np.float64)
        smooth = matrices[self.palette[:len(self.inverse)]] @ self.inverse if len(self.inverse) else None
        low, high = np.full(3, np.inf), np.full(3, -np.inf)
        for points, indices, weights in self.vertex_groups:
            if weights is None:
                output = np.einsum('nij,nj->ni', matrices[self.palette[indices[:, 0]]], points)
            else:
                output = np.zeros((len(points), 4))
                for i in range(weights.shape[1]):
                    active = weights[:, i] > 0
                    output[active] += np.einsum('nij,nj->ni', smooth[indices[active, i]], points[active]) * weights[active, i, None]
            if not np.all(np.isfinite(output)) or np.max(np.abs(output)) > 10000:
                raise ValueError('Invalid posed native mesh')
            low = np.minimum(low, output[:, :3].min(axis=0))
            high = np.maximum(high, output[:, :3].max(axis=0))
        return dict(min=low.tolist(), max=high.tolist(), vertices=self.vertices)
