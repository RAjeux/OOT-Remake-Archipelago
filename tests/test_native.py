from support import server_command
import argparse,ctypes as C,json,os, socket, subprocess,sys,tempfile,time
from pathlib import Path
from zipfile import ZipFile
sys.path.insert(0,str(Path('dist/Client-OOT-Remake.pyz').resolve()))
from ootrr_triforce import player,native_setup as ns
from ootrr_triforce.catalog import FILLER, ITEM_IDS, LOCATION_IDS,CHESTS,CHECK_FLAGS
from ootrr_triforce.item_names import item_name
from ootrr_triforce.room_view import RoomView
from ootrr_triforce.presentation import Presentation
def wait(ok,secs=15):
    until=time.monotonic()+secs
    while time.monotonic()<until:
        if ok():return
        time.sleep(.06)
    raise AssertionError("timeout")
def main(t,source,language="en"):
    with ZipFile(next(Path(source).glob('*.zip'))) as z:
        for n in z.namelist():
            if n.endswith(('.apootrr','.archipelago')):z.extract(n,t)
    data=player.read_manifest(next(t.glob('*.apootrr')));root=t/data["token"];root.mkdir()
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    config={'server':'ws://127.0.0.1:'+str(port),'protected':'','baseline':0}
    ns.save_session(root,config,data,{n:('Test item','Ami') for n in data['checks']})
    verify=json.loads((root/'native-session.json').read_bytes());assert verify['Game']==data.get('game','Ocarina of Time Remake (Triforce)')
    # The host's real game language must win over a stale setup preference.
    verify['Language']='en' if language=='fr' else 'fr'
    (root/'native-session.json').write_text(json.dumps(verify),encoding='utf-8')
    def boot():
        with (t/'server.log').open('ab') as out:
            return subprocess.Popen([*server_command(),str(next(t.glob('*.archipelago'))),'--host','127.0.0.1','--port',str(port)],stdin=subprocess.PIPE,stdout=out,stderr=out)
    def command(server,s):server.stdin.write((s+'\n').encode());server.stdin.flush()
    dll=C.CDLL(str(Path('dist/native/archipelago.dll' if os.name=='nt' else 'build/archipelago.so').resolve()))
    u32=C.c_uint32;P=C.POINTER(u32)
    dll.AP_Start.argtypes=[C.c_char_p,C.c_char_p];dll.AP_Flags.argtypes=[P,C.c_int];dll.AP_Opened.argtypes=[P,C.c_int,C.c_int]
    dll.AP_Cursor.restype=u32
    dll.AP_SetLanguage.argtypes=[C.c_char_p];dll.AP_SetLanguage.restype=None
    dll.AP_Note.argtypes=[C.c_void_p,C.c_int];dll.AP_Note.restype=C.c_int
    dll.AP_SetLanguage(language.encode('ascii'))
    assert dll.AP_Start(os.fsencode(root),b'unknown')==0
    assert dll.AP_Start(os.fsencode(root),data['token'].encode())==1
    assert dll.AP_Cursor()==ns.cursor_hash(data['token'])
    assert json.loads((root/'language.json').read_bytes())=={'language':language}
    notes=[]
    def compact(text):return ''.join(text.split())
    def has_note(expected):
        # A deliberately short ABI buffer splits multi-byte French text. Every
        # returned chunk must remain valid UTF-8 and preserve its characters.
        buffer=C.create_string_buffer(9)
        while dll.AP_Note(buffer,len(buffer)):
            chunk=buffer.value.decode('utf-8',errors='strict')
            assert chunk, 'AP_Note returned an empty fragment'
            notes.append(chunk)
        return compact(expected) in compact(''.join(notes))
    assert has_note('Mod Archipelago actif' if language=='fr' else 'Archipelago mod active')
    native_log=lambda:(root/'archipelago-jeu.log').read_text(encoding='utf-8',errors='replace')
    flags=(u32*4096)();count=dll.AP_Flags(flags,len(flags));assert set(flags[:count])=={f for n in data['checks'] for f in CHECK_FLAGS[n]}
    chests=[name for name in data['checks'] if name in CHESTS]
    loc=chests[0];flag=CHESTS[loc][0]['flag']
    # The mod collected this before a server even existed.
    dll.AP_Opened((u32*1)(flag),1,0)
    wait(lambda:(root/'native-checks.json').is_file())
    assert LOCATION_IDS[loc] in json.loads((root/'native-checks.json').read_bytes())['Locations']
    def roomlog():return (t/'server.log').read_text(encoding='utf-8',errors='replace')
    server=boot()
    try:
        wait(lambda:'Archipelago connected' in native_log());wait(lambda:loc in roomlog())
        wait(lambda:has_note('Archipelago connecté' if language=='fr' else 'Archipelago connected'))
        # A physical pickup can grant either player's own item or a foreign item.
        before=[]
        time.sleep(.5)
        while dll.AP_Next(len(before)):before.append(dll.AP_Next(len(before)))
        command(server,'/send '+data['slot']+' Mirror Shield')
        wait(lambda:dll.AP_Next(len(before))==ITEM_IDS['Mirror Shield'])
        command(server,'/send '+data['slot']+' Blue Rupee (5)')
        wait(lambda:dll.AP_Next(len(before)+1)==ITEM_IDS[FILLER]);assert dll.AP_Next(len(before)+2)==0
        dll.AP_Applied(len(before));wait(lambda:'Mirror Shield received from' in native_log());wait(lambda:'sent to Ami' in native_log())
        wait(lambda:has_note(item_name('Mirror Shield',language)+(' reçu de' if language=='fr' else ' received from')))
        wait(lambda:has_note('Test item envoyé à Ami' if language=='fr' else 'Test item sent to Ami'))
        assert 'Archipelago connecté' not in native_log() and 'reçu de' not in native_log() and 'envoyé à' not in native_log()
        assert verify['Items'][str(ITEM_IDS['Mirror Shield'])]=='Mirror Shield'
        command(server,'/save');time.sleep(.45)
        server.terminate();server.wait(timeout=8)
        wait(lambda:dll.AP_Next(0)==0)
        offline=chests[3];dll.AP_Opened((u32*1)(CHESTS[offline][0]['flag']),1,0)
        server=boot();wait(lambda:native_log().count('Archipelago connected')>=2)
        wait(lambda:offline in roomlog())
        wait(lambda:dll.AP_Next(len(before))==ITEM_IDS['Mirror Shield'])
        assert dll.AP_Next(len(before)+1)==ITEM_IDS[FILLER] and dll.AP_Next(len(before)+2)==0
        assert dll.AP_Cursor()==ns.cursor_hash(data['token'])
        assert json.loads((root/'language.json').read_bytes())=={'language':language}
        print(f'PASS real native shared client ({language}): host language overrides setup, normalized marker, localized UTF-8 ABI notices/English logs, unchanged AP names/IDs/cursor, offline flags, receipt order, reconnect and no extra deliveries.')
    finally:
        if server.poll() is None:server.terminate();server.wait(timeout=8)
        print(native_log()[-1700:])
if __name__ == "__main__":
    parser=argparse.ArgumentParser(description='Test the native DLL ABI against an isolated real Archipelago room.')
    parser.add_argument('room',nargs='?',default='tests/fixtures/neutre')
    parser.add_argument('--language',choices=('en','fr'),default='en')
    parser.add_argument('--worker',type=Path,help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.worker is not None:
        main(args.worker,args.room,args.language)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([sys.executable,"-X","utf8",__file__,args.room,'--language',args.language,'--worker',tmp],check=True)
