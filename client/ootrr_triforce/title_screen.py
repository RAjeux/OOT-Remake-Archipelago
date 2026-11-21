"""Stamp the two v1.1.1 title textures with our lettering and the credited AP icon."""
from importlib import resources
import struct
import zlib
from oot_rando.patching import title_badge as badge
from .mod_codec import Codec


def apply_badge(raw, tiles, expected=badge.AREA_SHA256):
    candidates = [t for t in badge.textures(raw) if t[0] == badge.LOGO]
    if len(candidates) != 1:
        raise ValueError("Logo de titre européen/américain absent ou ambigu.")
    _, fmt, width, height, block_height, start, size = candidates[0]
    if (fmt, width, height) != (badge.ASTC_4X4_SRGB, 1664, 1280) or start + size > len(raw):
        raise ValueError("Texture de titre incompatible avec OOTRR 1.1.1.")
    area = badge.badge_area(708,72)
    if badge.area_digest(raw,start,width//4,block_height,area) != expected:
        raise ValueError("La zone sous le logo a déjà été modifiée dans les fichiers du jeu.")
    left, top, cols, rows = area
    out = bytearray(raw)
    for x,y,block in struct.iter_unpack("<BB16s",tiles):
        offset = badge.block_offset(left+x,top+y,width//4,block_height)
        if x >= cols or y >= rows or offset + 16 > size:
            raise ValueError("Bloc du logo en dehors de la texture.")
        out[start+offset:start+offset+16] = block
    return bytes(out)


def write_title(romfs, mod):
    tiles = zlib.decompress(resources.files(__package__).joinpath("title.tiles").read_bytes())
    codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
    for rel in badge.BADGE_FILES:
        output = mod / rel
        source = (output if output.is_file() else romfs / rel).read_bytes()
        patched = apply_badge(codec.decode(source),tiles)
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_bytes(codec.encode(patched,source))
    print("Logo Archipelago installé dans le titre et le menu principal.",flush=True)
