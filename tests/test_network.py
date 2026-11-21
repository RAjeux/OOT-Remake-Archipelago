from support import server_command
import asyncio, contextlib, json, socket, subprocess, sys, tempfile
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
sys.path.insert(0,str(Path('dist/Client-OOT-Remake.pyz').resolve()))
from ootrr_triforce import player
from ootrr_triforce.catalog import FILLER, ITEM_IDS, LOCATION_IDS

async def until(pred, task=None):
    for _ in range(160):
        if task and task.done(): task.result()
        if pred(): return
        await asyncio.sleep(.08)
    raise AssertionError("timeout")

async def main(root):
    (root/"user").mkdir()
    with ZipFile(next(Path(sys.argv[1] if len(sys.argv)>1 else 'tests/fixtures/neutre').glob('*.zip'))) as z:
        for n in z.namelist():
            if n.endswith(('.apootrr','.archipelago')):z.extract(n,root)
    d=player.read_manifest(next(root.glob('*.apootrr')))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    log=root/'log'
    with log.open('wb') as stream:
        server=subprocess.Popen([*server_command(),str(next(root.glob('*.archipelago'))),
                  '--host','127.0.0.1','--port',str(port),'--disable_save'],stdin=subprocess.PIPE,stdout=stream,stderr=stream)
    await until(lambda:'server listening on' in log.read_text())
    sessions=[]; rosters=[]; notifications=[]
    class Observe(player.Session):
        def __init__(self,*args):
            super().__init__(*args)
            self.visual.hud.start=lambda pid:None
            self.visual.active=True
            self.pending_launch=True
            self.visual.hud.notify=lambda *msg:notifications.append(msg)
            sessions.append(self)
    class Running:
        pid=11
        def poll(self):return None
    def prepare(root,config,roster,_moved):
        rosters.append(roster)
        return root/'mods'
    def command(s):
        server.stdin.write((s+'\n').encode());server.stdin.flush()
    task=None
    try:
        with patch.object(player,'Session',Observe),patch.object(player,'prepare',prepare),patch.object(player,'spawn_game',return_value=Running()):
            async def start():
                return asyncio.create_task(player.play(root,'auto',d,{},'ws://127.0.0.1:'+str(port),'',headless=True))
            task=await start()
            await until(lambda:sessions and sessions[-1].process and sessions[-1].visual.fenced,task)
            s=sessions[-1]; assert rosters and len(rosters[-1])>8
            assert not s.checked
            assert not s.checked and not notifications
            loc,(item,owner)=next(iter(rosters[-1].items()))
            assert owner=='Ami' and not item.startswith('#')
            # Official server sends from Zelda world to the DS3 slot, including exact DS3 name.
            command('/send_location '+d['slot']+' '+loc)
            await until(lambda:any(m[-1]=='out' for m in notifications),task)
            outgoing=[m for m in notifications if m[-1]=='out'];assert outgoing==[('Item sent to Ami',item,loc,'out')]
            # Actual console transfer, distinct from replayed Sync items.
            command('/send_location Ami LC: Gotthard Twinswords - by Grand Archives door, after PC and AL bosses')
            await until(lambda:any(m[1]=='Mirror Shield' for m in notifications),task)
            assert [m for m in notifications if m[1]=='Mirror Shield']==[('Item received via Archipelago','Mirror Shield','From Ami','in')]
            count=len(notifications)
            task.cancel(); await asyncio.gather(task,return_exceptions=True)
            task=await start()
            await until(lambda:len(sessions)==2 and sessions[-1].visual.fenced and sessions[-1].process,task)
            assert len(notifications)==count
            command('/send '+d['slot']+' Blue Rupee (5)')
            await until(lambda:len(notifications)>count,task)
            assert 'synchronized' in notifications[-1][2] and notifications[-1][1]==FILLER
            print(f'PASS real DS3 + Zelda AP server: {len(rosters[0])} foreign chests scouted silently, correct DS3 item/owner, server delivery popup, no replay on reconnect, separate currency state.')
    finally:
        if task: task.cancel();await asyncio.gather(task,return_exceptions=True)
        server.terminate();server.wait(timeout=8)
with tempfile.TemporaryDirectory() as tmp:asyncio.run(main(Path(tmp)))
