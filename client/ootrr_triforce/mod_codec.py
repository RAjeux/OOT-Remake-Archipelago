"""Zstandard frames used by the v1.1.1 RomFS. Match each resource's dictionary."""
from .i18n import tr
from .app_runtime import resource_root
import ctypes as C
from ctypes.util import find_library
import os
from pathlib import Path
import sys


class Codec:
    def __init__(self, pack):
        from oot_rando.formats.inspect_resources import sarc
        name = (str(resource_root() / "runtime" / "libzstd.dll")
                if os.name == "nt" else find_library("zstd"))
        if not name:
            raise RuntimeError(tr('Zstandard library not found.'))
        self.lib = C.CDLL(name)
        ptr, size, uint = C.c_void_p, C.c_size_t, C.c_uint
        signatures = {
            "getDictID_fromDict": (uint, [ptr, size]), "getDictID_fromFrame": (uint, [ptr, size]),
            "getFrameContentSize": (C.c_ulonglong, [ptr, size]),
            "decompressBound": (C.c_ulonglong, [ptr, size]),
            "isError": (uint, [size]), "getErrorName": (C.c_char_p, [size]),
            "createCCtx": (ptr, []), "createDCtx": (ptr, []),
            "freeCCtx": (size, [ptr]), "freeDCtx": (size, [ptr]),
            "compressBound": (size, [size]),
            "compress_usingDict": (size, [ptr, ptr, size, ptr, size, ptr, size, C.c_int]),
            "decompress_usingDict": (size, [ptr, ptr, size, ptr, size, ptr, size]),
        }
        for key, (ret, args) in signatures.items():
            func = getattr(self.lib, "ZSTD_" + key)
            func.restype, func.argtypes = ret, args
            setattr(self, key, func)
        self.dicts = {0: b""}
        for raw in sarc(self.decode(pack)).values():
            key = self.getDictID_fromDict(raw, len(raw))
            if key:
                self.dicts[key] = raw

    def dictionary(self, frame):
        key = self.getDictID_fromFrame(frame, len(frame))
        if key not in self.dicts:
            raise ValueError(tr('Missing Zstandard dictionary ({value0}).', value0=key))
        return self.dicts[key]

    def run(self, encode, raw, dictionary, capacity):
        if not 0 <= capacity <= 768 * 1024**2:
            raise ValueError(tr('Invalid resource size.'))
        dest = C.create_string_buffer(capacity)
        create, free = (self.createCCtx, self.freeCCtx) if encode else (self.createDCtx, self.freeDCtx)
        ctx = create()
        if not ctx:
            raise MemoryError(tr('Not enough memory for compression.'))
        try:
            args = (ctx, dest, capacity, raw, len(raw), dictionary, len(dictionary))
            count = self.compress_usingDict(*args, 8) if encode else self.decompress_usingDict(*args)
            if self.isError(count):
                raise ValueError(self.getErrorName(count).decode())
            return dest[:count]
        finally:
            free(ctx)

    def decode(self, frame):
        capacity = self.getFrameContentSize(frame, len(frame))
        if capacity == (1 << 64) - 1:
            capacity = self.decompressBound(frame, len(frame))
        return self.run(False, frame, self.dictionary(frame), capacity)

    def encode(self, raw, template):
        frame = self.run(True, raw, self.dictionary(template), self.compressBound(len(raw)))
        if self.decode(frame) != raw:
            raise ValueError(tr('Resource verification failed after recompression.'))
        return frame
