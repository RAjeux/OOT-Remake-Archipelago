from support import triforce_root
from support import server_command
import sys,tempfile,shutil,asyncio,socket,subprocess,time,json
from pathlib import Path
from zipfile import ZipFile
from unittest.mock import patch
dist=Path('dist').resolve()
sys.path.insert(0,str(dist/'Client-OOT-Remake.pyz'))
from ootrr_triforce import native_setup as n,player,install_mod
from ootrr_triforce.menu_setup import patch_renderer
sys.argv[0]=str(dist/'Client-OOT-Remake.pyz')
def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
async def check(tmp):
    tools=tmp/'tools';host=tools/'host';host.mkdir(parents=True)
    orig=(triforce_root()/'host/hos_main.c').read_bytes()
    write(host/'hos_main.c',orig)
    write(host/'nn_applet.c',b'const char *hos_desired_language(void) { return "en-US"; }\n')
    write(tools/'nx2/build.py',b'')
    write(tools/'gpu/vk/vk_api.h',(triforce_root()/'gpu/vk/vk_api.h').read_bytes())
    renderer_orig=Path('tests/fixtures/triforce-menu-source.cpp').read_bytes()
    renderer=tools/'gpu/vk/vk_menu.cpp'
    write(renderer,renderer_orig)
    profile=tmp/'userdata'
    assert n.install_tools(profile,None,tools).samefile(tools)
    assert n.install_tools(profile,None,tools).samefile(tools)
    assert len(list(host.glob('*.bak')))==1 and next(host.glob('*.bak')).read_bytes()==orig
    assert (host/'hos_main.c').read_bytes()==n.patch_source(orig)
    assert renderer.read_bytes()==patch_renderer(renderer_orig)
    assert len(list(renderer.parent.glob('*.bak')))==1
    assert next(renderer.parent.glob('*.bak')).read_bytes()==renderer_orig
    assert not (profile/'native-016/archipelago.dll').exists()
    for name in n.RT_FILES:assert (host/name).read_bytes()==(dist/'native'/name).read_bytes()
    for name in n.MENU_FILES:assert (renderer.parent/name).read_bytes()==(dist/'native'/name).read_bytes()
    with ZipFile(next(Path('tests/fixtures/neutre').glob('*.zip'))) as z:
        for name in z.namelist():
            if name.endswith(('.apootrr','.archipelago')):z.extract(name,tmp)
    d=player.read_manifest(next(tmp.glob('*.apootrr')))
    root=profile/d['token'];root.mkdir(parents=True)
    assets=tmp/'cache';shared=tmp/'Games/Triforce/mods';romfs=tmp/'source/romfs'
    write(romfs/'Pack/ZsDic.pack.zs',b'dict')
    def fake_ootrr(args,check,**kwargs):
        write(Path(args[4])/'Archipelago/romfs/test',b'base')
        return subprocess.CompletedProcess(args,0,'','')
    def fixture_cursor(raw,mod,data,baseline):write(mod/n.MARKER,(data['token']+'\n').encode())
    cfg={'native':True,'baseline':0,'assets':assets,'install_only':True,'mods_dir':str(shared),'host':'nx2navi','romfs':str(romfs),'ootrr':'fixture'}
    with patch.object(player.subprocess,'run',fake_ootrr),patch.object(player,'write_title'),patch.object(player,'run_engine',return_value=''),patch.object(n,'bind_romfs',fixture_cursor),patch('ootrr_triforce.builder.validate_builder') as builder,patch('ootrr_triforce.story_fixes.prepare_story_fixes') as story_fixes,patch('ootrr_triforce.quest_fixes.prepare_quest_fixes') as quest_fixes,patch('ootrr_triforce.fortress_fixes.prepare_fortress_fixes') as fortress_fixes:
        player.build(assets,cfg,d)
    builder.assert_called_once_with('fixture')
    story_fixes.assert_called_once()
    quest_fixes.assert_called_once()
    fortress_fixes.assert_called_once()
    assert (assets/'mods/Archipelago/archipelago.dll').read_bytes()==(dist/'native/archipelago.dll').read_bytes()
    write(shared/'costumes/romfs/check',b'other mod')
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    logfile=tmp/'serverlog'
    with logfile.open('wb') as s:
        srv=subprocess.Popen([*server_command(),str(next(tmp.glob('*.archipelago'))),'--host','127.0.0.1','--port',str(port),'--disable_save'],stdout=s,stderr=s,stdin=subprocess.PIPE)
    cfg.update(server=f'ws://127.0.0.1:{port}',protected='')
    try:
        for _ in range(120):
            if 'server listening on' in logfile.read_text():break
            await asyncio.sleep(.1)
        with patch.object(player,'prepare',side_effect=IndexError('list index out of range')),patch.object(player,'spawn_game',side_effect=AssertionError('installer launched game')):
            await asyncio.wait_for(player.play(root,'auto',d,cfg,cfg['server'],'',headless=True),15)
        dest=shared/'Archipelago'
        assert (dest/'archipelago.dll').read_bytes()==(dist/'native/archipelago.dll').read_bytes()
        assert (dest/'romfs'/n.MARKER).read_text().strip()==d['token']
        assert (shared/'costumes/romfs/check').read_bytes()==b'other mod'
        assert 'IndexError' in (root/'medaillons-diagnostic.txt').read_text()
        data=json.loads((root/'native-session.json').read_bytes());assert len(data['Checks'])==len(d['checks']) and sum(v['Owner']=='Ami' for v in data['Checks'].values())==119
        assert not list(dest.rglob('native-session.json'))
    finally:
        srv.terminate();srv.wait(timeout=8)
    print('PASS full normal connected installer, exact shipped Windows DLL under the active mod, room token, passive source installation/idempotence, medal-failure reproduction and native names on all 119 foreign locations.')
with tempfile.TemporaryDirectory() as t:asyncio.run(check(Path(t)))
