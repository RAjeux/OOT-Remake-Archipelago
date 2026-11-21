import contextlib, hashlib, io, os, shutil, struct, sys, tempfile
from pathlib import Path
from unittest.mock import patch
from importlib import resources
import zlib
import zstandard as zs
from PIL import Image,ImageChops,ImageStat
import texture2ddecoder
sys.path.insert(0,str(Path('dist/Client-OOT-Remake.pyz').resolve()))
sys.argv[0]=str(Path('dist/Client-OOT-Remake.pyz').resolve())
from ootrr_triforce import install_mod as im, title_screen as title, player
from oot_rando.formats.byml_codec import build_sarc
from ootrr_triforce.mod_codec import Codec
from ootrr_triforce.catalog import FILLER,ITEM_IDS
from ootrr_triforce.save_bridge import apply_history,history_cursor

def put(p,b):p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
def image_archive():
    start=4096
    pix=1664*1536
    raw=bytearray(start+pix)
    raw[:4]=b'BNTX'
    struct.pack_into('<I',raw,0x24,1);struct.pack_into('<q',raw,0x28,0x80);struct.pack_into('<q',raw,0x80,0x100)
    brti=0x100;raw[brti:brti+4]=b'BRTI'
    struct.pack_into('<IIiiiii',raw,brti+0x1c,title.badge.ASTC_4X4_SRGB,0,1664,1280,1,1,4)
    struct.pack_into('<I',raw,brti+0x50,pix)
    struct.pack_into('<qqq',raw,brti+0x60,0x300,0,0x350)
    name=title.badge.LOGO.encode();struct.pack_into('<H',raw,0x300,len(name));raw[0x302:0x302+len(name)]=name
    struct.pack_into('<q',raw,0x350,start)
    block=bytes.fromhex('fcfdffffffffffff0000000000000000')
    raw[start:]=block*(pix//16)
    return bytes(raw)

def check_title(root):
    game=root/'game';mod=root/'stage'/'Archipelago'/'romfs'
    c=zs.ZstdCompressor()
    pack=c.compress(build_sarc({'unused':b'anything'}))
    put(game/'Pack/ZsDic.pack.zs',pack);codec=Codec(pack)
    start,w=4096,416
    raw=image_archive()
    for rel in title.badge.BADGE_FILES:put(game/rel,c.compress(raw))
    spec=title.badge.badge_area(708,72)
    digest=title.badge.area_digest(raw,start,w,4,spec)
    original=title.apply_badge
    with patch.object(title,'apply_badge',side_effect=lambda raw,tiles:original(raw,tiles,digest)):
        title.write_title(game,mod)
    for rel in title.badge.BADGE_FILES:
        result=codec.decode((mod/rel).read_bytes())
        assert len(raw)==len(result) and codec.decode((game/rel).read_bytes())==raw
        left,top,cols,rows=spec;restored=bytearray(result);blocks=bytearray()
        for y in range(rows):
            for x in range(cols):
                off=start+title.badge.block_offset(left+x,top+y,w,4)
                blocks+=result[off:off+16];restored[off:off+16]=raw[off:off+16]
        assert bytes(restored)==raw
        decoded=Image.frombytes('RGBA',(708,72),texture2ddecoder.decode_astc(bytes(blocks),708,72,4,4),'raw','BGRA')
        src=Image.open('assets/badge-preview.png')
        for color in ('black','white'):
            bg=Image.new('RGBA',src.size,color)
            err=ImageChops.difference(Image.alpha_composite(bg,src).convert('RGB'),Image.alpha_composite(bg,decoded).convert('RGB'))
            assert max(ImageStat.Stat(err).mean)<7
        try:original(raw,(b''))
        except ValueError:pass
        else:raise AssertionError('Stock fingerprint check missing')
    print('PASS both compressed menu/title textures, independent ASTC decoder and pixel check; untouched Zelda artwork.')

def check_install(root):
    src=root/'stage'
    mods=root/'Programs'/'Triforce'/'mods';mods.mkdir(parents=True)
    old=mods/'My Seed/romfs'/im.REST;put(old,b'old')
    assert im.known_folder(root)==mods
    with patch('builtins.input',return_value='n'):im.offer_old_seed(mods)
    assert old.exists()
    with patch('builtins.input',return_value='o'):im.offer_old_seed(mods)
    assert not old.exists() and (im.state_dir(mods)/'mods-en-pause/My Seed/romfs'/im.REST).read_bytes()==b'old'
    other=mods/'Cosmetics/romfs'/im.REST;put(other,b'other')
    assert list(im.tables(mods))==[Path('Cosmetics')]
    root_valid=im.validate_root(mods,root/'game',root/'apdata')
    new=im.install(src,root_valid,'test');assert new==mods/'Archipelago'
    inode=new.stat().st_ino
    assert im.install(src,mods,'test').stat().st_ino==inode
    put(src/'Archipelago/romfs/changed',b'changed')
    im.install(src,mods,'test2')
    assert im.marker(new)['room']=='test2' and im.marker(im.state_dir(mods)/'previous')['room']=='test'
    assert other.read_bytes()==b'other'
    (new/im.MARK).unlink()
    try:im.install(src,mods,'test')
    except ValueError:pass
    else:raise AssertionError('unowned overwrite')
    assert not (new/im.MARK).exists()
    print('PASS reuse real folder layout; existing mods preserved, cache hit, seed rotation, unrelated Archipelago protected.')
def make_synthetic_slots(folder):
    from ootrr_triforce.catalog import GEAR
    from ootrr_triforce.save_bridge import RUPEES,SENTINEL
    flags=sorted({RUPEES} | {h for values in GEAR.values() for h in values})
    for i in range(2):
        header=bytearray(40)
        start=48+8*len(flags)
        struct.pack_into("<I",header,0,0x01020304)
        struct.pack_into("<I",header,8,start)
        data=bytes(header)+b"".join(struct.pack("<II",h,0) for h in flags)
        put(folder/f"slot_{i:02}"/"progress.sav",data+struct.pack("<II",SENTINEL,start)+bytes(8))
def check_external(root):
    folder=root/'external';make_synthetic_slots(folder)
    ledger=root/'ledger';ledger.mkdir();history=[ITEM_IDS[FILLER]]
    assert apply_history(ledger,'slot_01',history,folder)
    assert history_cursor(ledger)==1 and apply_history(ledger,'slot_01',history,folder)
    assert history_cursor(ledger)==1
    print('PASS external saves: actual multi-slot format, offline delivery, replay deduplication.')
with tempfile.TemporaryDirectory() as t:
    root=Path(t);check_title(root);check_install(root);check_external(root)
