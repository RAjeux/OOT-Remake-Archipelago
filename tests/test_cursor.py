import contextlib, io, json, struct, sys,tempfile,subprocess,os,zlib
from pathlib import Path
sys.path.insert(0,'dist/Client-OOT-Remake.pyz')
sys.argv[0]=str(Path('dist/Client-OOT-Remake.pyz').resolve())
from ootrr_triforce import native_setup as ns, mod_codec
from oot_rando.formats import byml_codec as by
from oot_rando.game.resource_allocations import allocation
import zstandard as zs
token='be'*32
def raw(endian):
    row={'Hash':by.U32(1),'DefaultValue':0,'SaveFileIndex':0,'ResetTypeValue':8}
    data={'Int':[row,dict(row,Hash=by.U32(0x90000000))],'Bool':[dict(row,DefaultValue=False)],'Else':[by.U64(0x9876543210123456)]}
    meta={'SaveDataSize':[100,56],'SaveDataOffsetPos':[100,56],'AllDataSaveSize':130,'AllDataSaveOffset':145}
    return by.dump(dict(root={'Data':data,'MetaData':meta},version=7,endian=endian))
for end in ['<','>']:
    src=raw(end); out=ns.add_cursor(src,token,19)
    got=by.load(out)['root'];before=by.load(src)['root']
    key=ns.cursor_hash(token)
    rows=got['Data']['Int'];assert [int(x['Hash']) for x in rows]==sorted([key,1,0x90000000])
    assert next(x['DefaultValue'] for x in rows if x['Hash']==key)==19 and got['Data']['Else']==before['Data']['Else']
    assert got['MetaData']=={'SaveDataSize':[108,56],'SaveDataOffsetPos':[108,56],'AllDataSaveSize':138,'AllDataSaveOffset':153}
    try:ns.add_cursor(out,token,0)
    except ValueError:pass
    else:raise AssertionError('collision was accepted')
with tempfile.TemporaryDirectory() as t:
    root=Path(t);src=root/'game';mod=root/'mod'
    def write(base,n,b):
        p=base/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
    def enc(b):return zs.ZstdCompressor().compress(b)
    write(src,'Pack/ZsDic.pack.zs',enc(by.build_sarc({})))
    write(src,ns.GAME_DATA,enc(raw('<')))
    k=zlib.crc32(ns.GAME_DATA.removesuffix('.zs').encode())
    table=b'RESTBL'+struct.pack('<6I',1,160,1,0,k,65536)
    write(mod,ns.REST,enc(table));ns.bind_romfs(src,mod,{'token':token},0)
    assert (mod/ns.MARKER).read_text().strip()==token
    assert allocation(zs.ZstdDecompressor().decompress((mod/ns.REST).read_bytes()),ns.GAME_DATA)>65536
    assert next(x['DefaultValue'] for x in by.load(zs.ZstdDecompressor().decompress((mod/ns.GAME_DATA).read_bytes()))['root']['Data']['Int'] if x['Hash']==key)==0
print('PASS room cursor and vanilla scalar preservation in both BYML byte orders, shared metadata arrays, signed default, collision guard, real compressed RomFS marker and RESTBL allocation.')
