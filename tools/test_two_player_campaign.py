"""Private two-OOT-player AP generation and native-DLL protocol campaign.

This exhausts enabled network checks, not physical Zelda scenes. The two DLL
processes are real; game collection flags, restoration completion and receipt
consumption cursors are explicit API models. No game, installed APWorld,
personal profile, save or public room is opened or modified.
"""
from __future__ import annotations
import argparse
import asyncio
from collections import Counter, defaultdict
import contextlib
import ctypes as C
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import shutil
import socket
import subprocess
import sys
import time
import traceback
import uuid
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
WORKER_SCRIPT = Path(__file__).resolve()
PLAYERS = ("AuditLinkA", "AuditLinkB")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def native_worker(profile, token, library):
    """One DLL lifetime. No game memory or native inventory is fabricated."""
    dll=C.CDLL(str(library))
    for name,args,restype in (
        ("AP_Start",[C.c_char_p,C.c_char_p],C.c_int),("AP_ConnectionInfo",[C.c_void_p,C.c_int],C.c_int),
        ("AP_Flags",[C.POINTER(C.c_uint32),C.c_int],C.c_int),
        ("AP_Opened",[C.POINTER(C.c_uint32),C.c_int,C.c_int],None),
        ("AP_Next",[C.c_int],C.c_int),("AP_Applied",[C.c_int],None),
        ("AP_Restore",[C.POINTER(C.c_uint8),C.c_int],C.c_int),
        ("AP_RestoreDeferred",[C.c_int],None),("AP_ReceiptReplay",[C.c_int,C.c_int],C.c_int),
        ("AP_Connect",[C.c_char_p,C.c_char_p,C.c_int,C.c_int],C.c_int),
        ("AP_Disconnect",[],C.c_int),("AP_DeathLink",[C.c_int],C.c_int)):
        fn=getattr(dll,name);fn.argtypes=args;fn.restype=restype
    dll.AP_Cursor.restype=C.c_uint32
    assert dll.AP_Start(os.fsencode(profile),token.encode("ascii"))==1
    config=json.loads((Path(profile)/"native-session.json").read_bytes())
    flags=(C.c_uint32*4096)();count=dll.AP_Flags(flags,4096)
    assert 0<count<=4096
    flags=list(flags[:count]);positions={value:i for i,value in enumerate(flags)}
    states=[ord('0')]*count
    def snapshot():
        info=C.create_string_buffer(16384);assert dll.AP_ConnectionInfo(info,len(info))>0
        history=[]
        for index in range(20000):
            item=dll.AP_Next(index)
            if not item:break
            history.append(item)
        else:raise AssertionError("Native history exceeds the bounded test stream")
        return dict(info=json.loads(info.value),history=history,flags=flags,cursor_hash=dll.AP_Cursor())
    print(json.dumps(snapshot()),flush=True)
    for line in sys.stdin:
        q=json.loads(line);out={}
        if q.get('disconnect'):out['disconnect']=dll.AP_Disconnect()
        if 'connect' in q:out['connect']=dll.AP_Connect(q['connect'].encode(),b'',0,1)
        if 'opened' in q or q.get('goal'):
            values=q.get('opened',[]);arr=(C.c_uint32*max(1,len(values)))(*values)
            dll.AP_Opened(arr,len(values),int(q.get('goal',False)))
        if 'applied' in q:
            for index in q['applied']:dll.AP_Applied(index)
        if 'death' in q:out['death']=dll.AP_DeathLink(q['death'])
        if 'states' in q:states=q['states']
        if q.get('defer_first_restore'):
            arr=(C.c_uint8*len(states))(*states)
            location=dll.AP_Restore(arr,len(states));assert location>0
            dll.AP_RestoreDeferred(location);out['deferred']=location
        if q.get('restore_all'):
            recovered=[];arr=(C.c_uint8*len(states))(*states)
            while True:
                location=dll.AP_Restore(arr,len(states))
                if not location:break
                assert location not in recovered,"Restoration selected a completed modeled check twice"
                recovered.append(location)
                for flag in config['Checks'][str(location)]['Flags']:
                    arr[positions[flag]]=ord('1')
            states=list(arr);out['restored']=recovered
        if q.get('invalid_restore'):
            a=(C.c_uint8*len(states))(*states);a[0]=255
            out['invalid_restore']=dll.AP_Restore(a,len(states))
            out['short_restore']=dll.AP_Restore(a,len(states)-1)
        if q.get('trade_replays'):
            history=snapshot()['history']
            out['trade_replays']=[i for i,item in enumerate(history) if dll.AP_ReceiptReplay(i,item)]
            out['invalid_trade_replay']=dll.AP_ReceiptReplay(len(history)+1,history[0] if history else 1)
        print(json.dumps({**snapshot(),**out}),flush=True)
        if q.get('stop'):os._exit(0)


class Worker:
    def __init__(self,profile,token,library,log):
        self.profile,self.token,self.library,self.log=profile,token,library,log
        self.process=None
    async def start(self):
        self.process=await asyncio.create_subprocess_exec(sys.executable,'-B','-X','utf8',str(WORKER_SCRIPT),
            '--worker',str(self.profile),self.token,str(self.library),stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,stderr=self.log,limit=2<<20)
        return await self.read()
    async def read(self):
        raw=await asyncio.wait_for(self.process.stdout.readline(),30)
        if not raw:raise RuntimeError('Native worker exited; inspect private workers.log')
        return json.loads(raw)
    async def request(self,**value):
        self.process.stdin.write((json.dumps(value)+'\n').encode());await self.process.stdin.drain()
        return await self.read()
    async def ready(self,expected=None,timeout=35):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            result=await self.request()
            if result['info']['state']=='connected' and (expected is None or result['history']==expected):return result
            await asyncio.sleep(.04)
        raise AssertionError('Native DLL did not synchronize its exact filtered history')
    async def close(self):
        if self.process and self.process.returncode is None:
            try:
                await self.request(stop=True);await asyncio.wait_for(self.process.wait(),10)
            finally:
                if self.process.returncode is None:self.process.kill();await self.process.wait()


def configurations():
    """Independent families first, then combined and asymmetric configurations."""
    return [
        ('default',False,{},{}),
        ('broad',True,{},{}),
        # Retain the original regression settings/seeds: AP must support all
        # 100 skulls and ground pickups with ordinary chests disabled.
        ('ground-and-skulls',False,dict(shuffle_chests='off',shuffle_skulltulas='matched',shuffle_freestanding_items='all'),{}),
        ('pots-crates-grass',False,dict(shuffle_pots='all',shuffle_crates='all',shuffle_grass='all',shuffle_beehives=True),{}),
        ('shops-and-merchants',True,dict(merchant_prices='fixed',merchant_price_fixed=0,scrub_prices='fixed',scrub_price_fixed=99),dict(merchant_prices='cheap',scrub_prices='cheap')),
        ('trade-cows-potion',False,dict(shuffle_rewards='supported',shuffle_rewards_extra=True,adult_trade_shuffle=True,shuffle_cows=True,shuffle_potion_shop=True),{}),
        ('dungeon-scopes',True,dict(shuffle_smallkeys='dungeon',shuffle_bosskeys='regional',shuffle_mapcompass='regional',shuffle_songs='own'),{}),
        ('keysanity-vs-native',True,dict(shuffle_smallkeys='keysanity',shuffle_bosskeys='keysanity',shuffle_mapcompass='keysanity'),dict(shuffle_smallkeys='dungeon',shuffle_bosskeys='dungeon',shuffle_mapcompass='startwith')),
        ('rewards-lacs',True,dict(shuffle_dungeon_rewards='dungeons',shuffle_ganon_bosskey='lacs_dungeons',lacs_rewards=9,bridge='dungeons',bridge_rewards=9),{}),
        ('medallions-lacs',True,dict(bridge='medallions',bridge_medallions=6,shuffle_ganon_bosskey='lacs_medallions',lacs_medallions=6),{}),
        ('entrances',True,dict(shuffle_entrances='dungeons'),{}),
        ('starting-items',True,dict(starting_items=['biggest_bomb_bag','biggest_quiver','four_bottles','ocarina_of_time','giant_wallet'],starting_songs=['sarias_song','song_of_time'],starting_hearts=20),{}),
        ('traps-and-qol',True,dict(shuffle_ice_traps=True,ice_trap_count=10,free_scarecrow=True,skip_tower_escape=True,dungeon_key_tracker=True,dpad_gear_cycle=True,death_link=True),{}),
        ('hard-mode',False,dict(starting_hearts=1,enemy_health=500,enemy_damage=500,damage_taken='double',enemy_speed=200,more_enemies=1000,random_fuses=True,enemy_randomizer=True,death_link=True),{}),
        ('open-world',True,dict(open_forest='open',open_kakariko='open',zora_fountain='open',jabu_open=True,door_of_time_condition='open',bridge='open',skip_ganon_trials=True,shops_always_open=True),{}),
        ('map-removal',True,dict(shuffle_mapcompass='remove'),dict(shuffle_mapcompass='startwith')),
        ('wallet-prices',True,dict(shopsanity_prices='giant'),dict(shopsanity_prices='adult')),
        # This exposed a real standalone-constructor/AP capacity mismatch. Keep
        # it separate from the ordinary ground family as a regression case.
        ('ground-without-chests',False,dict(shuffle_chests='off',shuffle_skulltulas='matched',shuffle_freestanding_items='all'),
            dict(shuffle_chests='all',shuffle_skulltulas='matched',shuffle_freestanding_items='all')),
    ]


def stage(args):
    global WORKER_SCRIPT
    sys.path.insert(0,str(ROOT/'tests'))
    from test_network_generation import stage_host
    output=args.output.resolve()
    host,candidate=stage_host(args.ap_root,args.dependencies,output)
    shutil.copy2(args.ap_root/'ArchipelagoServer.exe',host/'ArchipelagoServer.exe')
    source=output/'source-snapshot';shutil.copytree(ROOT/'client',source/'client',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    runtime=output/'runtime';runtime.mkdir();shutil.copy2(ROOT/'dist/native/archipelago.dll',runtime/'archipelago.dll')
    shutil.copy2(Path(__file__),output/'frozen-runner.py');WORKER_SCRIPT=output/'frozen-runner.py'
    shutil.copy2(ROOT/'dist/Client-OOT-Remake.pyz',runtime/'dependencies.pyz')
    sys.path.append(str(runtime/'dependencies.pyz'))
    sys.path.insert(0,str(source/'client'))
    from ootrr_triforce import app_runtime
    app_runtime._resource_override=runtime
    manifest=dict(source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        apworld_sha256=sha(candidate),dll_sha256=sha(runtime/'archipelago.dll'),server_sha256=sha(host/'ArchipelagoServer.exe'),
        runner_sha256=sha(WORKER_SCRIPT),
        root=str(output),actual_gameplay=False,scope='Official two-player generation and native-DLL network API simulation only')
    write(output/'campaign.json',manifest)
    return output,host,candidate,manifest


def generate(host,case,seed,values):
    from ootrr_triforce.app_window import yaml_content
    for name in ('players','output','local','roaming','temp'):(case/name).mkdir(parents=True,exist_ok=True)
    for player,value in zip(PLAYERS,values):
        (case/'players'/(player+'.yaml')).write_text(yaml_content(player,value),encoding='utf-8')
    env=dict(os.environ,LOCALAPPDATA=str(case/'local'),APPDATA=str(case/'roaming'),TEMP=str(case/'temp'),TMP=str(case/'temp'),PYTHONUTF8='1')
    command=[str(host/'ArchipelagoGenerate.exe'),'--player_files_path',str(case/'players'),'--outputpath',str(case/'output'),
             '--multi','2','--seed',str(seed),'--spoiler','2','--log_level','info','--log_time']
    tick=time.monotonic()
    with (case/'generation.log').open('wb') as log:
        result=subprocess.run(command,cwd=host,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
            timeout=600,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        lines=(case/'generation.log').read_text(encoding='utf-8',errors='replace').splitlines()
        detail=next((line for line in reversed(lines) if line.startswith(('RuntimeError:','ValueError:','FillError:'))),'See the private generation log.')
        raise AssertionError('Official generation failed: '+detail+' Log: '+str(case/'generation.log'))
    archive=next((case/'output').glob('*.zip'))
    return archive,round(time.monotonic()-tick,3)


def audit_generation(archive,values):
    from test_network_generation import read_multidata
    from ootrr_triforce.catalog import ITEM_IDS,ITEM_DATA,LOCATION_IDS,GAME
    from ootrr_triforce.player import read_manifest
    from ootrr_triforce.pool_adjustments import from_manifest
    from ootrr_triforce.access_logic import AccessLogic
    from ootrr_triforce.network_placement import allowed
    from ootrr_triforce.feature_settings import feature_config,read_features
    with ZipFile(archive) as z:
        data=read_multidata(z)
        manifests=[]
        for n in z.namelist():
            if n.endswith('.apootrr'):
                destination=archive.parent/'validated-manifests'/Path(n).name
                destination.parent.mkdir(exist_ok=True)
                destination.write_bytes(z.read(n));manifests.append(read_manifest(destination))
    assert len(manifests)==2 and {m['slot'] for m in manifests}==set(PLAYERS)
    byslot={m['player']:m for m in manifests};byitem={v:k for k,v in ITEM_IDS.items()}
    options={m['player']:values[PLAYERS.index(m['slot'])] for m in manifests}
    for m in manifests:
        assert m['features']==read_features(feature_config(options[m['player']])),('YAML feature conversion changed settings',m['slot'])
    inventories={slot:Counter() for slot in byslot};expected={slot:Counter(from_manifest(m).values()) for slot,m in byslot.items()}
    actual=defaultdict(Counter);ownership={slot:Counter() for slot in byslot};progression={slot:Counter() for slot in byslot}
    graphs={slot:AccessLogic(m['access_logic'],master_sword=m.get('shuffle_master_sword',False)) for slot,m in byslot.items()}
    scope=Counter();cross_domains={}
    shop_ownership={slot:Counter() for slot in byslot}
    for source,locations in data['locations'].items():
        assert set(locations)=={LOCATION_IDS[n] for n in byslot[source]['checks']}
        names={LOCATION_IDS[n]:n for n in byslot[source]['checks']}
        for location,(item,owner,flags) in locations.items():
            assert owner in byslot and item in byitem
            actual[owner][byitem[item]]+=1;ownership[source][owner]+=1
            if flags&1:
                progression[source][owner]+=1
                if (owner,item) not in cross_domains:
                    cross_domains[owner,item]=any(
                        allowed(byitem[item],owner,GAME,options[owner],candidate,other,GAME,descriptor,options[other])
                        for other,manifest in byslot.items() if other!=owner
                        for candidate,descriptor in manifest['network_sources'].items())
                scope['cross_eligible' if cross_domains[owner,item] else 'explicitly_own_hyrule_scoped']+=1
                if cross_domains[owner,item]:scope['cross_eligible_local' if owner==source else 'cross_eligible_foreign']+=1
            name=names[location];descriptor=byslot[source]['network_sources'].get(name,{'placement':{'region_group':'castle','dungeon':None}})
            assert allowed(byitem[item],owner,GAME,options[owner],name,source,GAME,descriptor,options[source])
            metadata=ITEM_DATA[byitem[item]]
            if descriptor.get('kind')=='shop':shop_ownership[source]['local' if source==owner else 'foreign']+=1
            if descriptor.get('placement',{}).get('junk_only') or name in graphs[source].optional:
                assert not flags&1 and metadata.get('kind')!='Token',('unsafe progression placement',source,name,byitem[item])
            if owner==source and descriptor.get('kind')!='shop':
                assert not (metadata.get('bottle_item') and metadata.get('pouch_special')=='NotPushToPouch'),('unrepeatable source contains conditional bottle refill',name)
            family={'SmallKey':'shuffle_smallkeys','BossKey':'shuffle_bosskeys','GanonBossKey':'shuffle_ganon_bosskey',
                    'Map':'shuffle_mapcompass','Compass':'shuffle_mapcompass'}.get(metadata.get('kind'))
            if family and options[owner][family]!='keysanity':
                assert owner==source,('restricted dungeon item left its recipient Hyrule',byitem[item],options[owner][family])
    for slot in byslot:assert actual[slot]==expected[slot],('pool',slot,actual[slot]-expected[slot],expected[slot]-actual[slot])
    checked={slot:set() for slot in byslot};spheres=0
    while True:
        found=[]
        for slot,graph in graphs.items():
            reach=graph.sweep(inventories[slot]).reach
            found.extend((slot,LOCATION_IDS[n]) for n in reach if LOCATION_IDS[n] not in checked[slot])
        if not found:break
        spheres+=1
        for slot,location in found:
            checked[slot].add(location);item,owner,_=data['locations'][slot][location];inventories[owner][byitem[item]]+=1
    for slot,m in byslot.items():
        assert checked[slot]==set(data['locations'][slot]),('unreachable',slot,set(data['locations'][slot])-checked[slot])
        assert graphs[slot].sweep(inventories[slot]).won
    # Independent native wallet bounds: remake wallets hold 200/500/1000.
    # Unaffordable shelves must remain inaccessible even with every other item.
    wallet_assertions=0
    for slot,m in byslot.items():
        graph=wallet_capacity_probe(graphs[slot])
        start_wallet=sum(n for i,n in graph.world.start if graph.world.items[i]=='Progressive Wallet')
        for level,capacity in enumerate((200,500,1000)):
            held=Counter({n:1000 for n in graph.names});held['Progressive Wallet']=level
            reached=graph.sweep(held).reach
            for name,row in m['network_sources'].items():
                if row['kind']=='shop':
                    assert row['price']==m['seed_file']['shops'][name]['price']
                    if row['price']>(200,500,1000)[min(2,level+start_wallet)]:
                        assert name not in reached,('unaffordable shop reachable',slot,name,row['price'],capacity)
                        wallet_assertions+=1
    return manifests,data,dict(checks={s:len(m['checks']) for s,m in byslot.items()},ownership={s:dict(v) for s,v in ownership.items()},
        progression_ownership={s:dict(v) for s,v in progression.items()},progression_scope=dict(scope),wallet_gate_assertions=wallet_assertions,
        shop_ownership={s:dict(v) for s,v in shop_ownership.items()},
        joint_spheres=spheres,pool_conserved=True,all_checks_reachable=True,features_roundtrip_exact=True)


def wallet_capacity_probe(graph):
    """Isolate wallet rules without sweeping unshuffled native wallet gifts.

    The real fill/reachability audit uses the unchanged graph. This separate
    counterfactual asks what a given wallet can buy; its all-other-items input
    must not also collect the vanilla Skulltula wallet upgrades.
    """
    from ootrr_triforce.access_logic import AccessLogic
    wallet = graph.world.item_ix.get('Progressive Wallet')
    raw = dict(graph.raw, fixed=[row for row in graph.raw['fixed'] if row[1] != wallet])
    return AccessLogic(raw, master_sword=graph.master_sword)


def network_item(value):
    if isinstance(value,dict):return value['item'],value['location'],value['player']
    return tuple(value[:3])


def reconcile_history(history,index,items):
    """An independent observer must never invent or silently replace history."""
    if not 0<=index<=len(history):raise AssertionError('Authoritative history has an index hole')
    values=[network_item(item) for item in items]
    overlap=min(len(values),len(history)-index)
    if history[index:index+overlap]!=values[:overlap]:raise AssertionError('Authoritative history changed an acknowledged tuple')
    return history+values[overlap:]


async def until(predicate,label,timeout=35):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        result=predicate()
        if result:return result
        await asyncio.sleep(.025)
    raise AssertionError('Timed out: '+label)


class Observer:
    def __init__(self,uri,name,game):
        self.uri,self.name,self.game=uri,name,game
        self.ws=self.task=None;self.info=self.connected=None
        self.history=[];self.checked=set();self.scouts={};self.retrieved=set();self.bounces=[];self.goals=set()
    async def send(self,*packets):await self.ws.send(json.dumps(packets))
    async def wait(self,predicate,label='observer condition'):
        def check():
            if self.task.done():self.task.result();raise AssertionError('Observer disconnected')
            return predicate()
        return await until(check,label)
    async def start(self):
        from websockets.legacy.client import connect
        self.ws=await connect(self.uri,max_size=40<<20)
        async def reading():
            async for raw in self.ws:
                for packet in json.loads(raw):
                    cmd=packet['cmd']
                    if cmd=='RoomInfo':self.info=packet
                    elif cmd=='ConnectionRefused':raise AssertionError(packet)
                    elif cmd=='Connected':self.connected=packet;self.checked.update(packet['checked_locations'])
                    elif cmd=='RoomUpdate':self.checked.update(packet.get('checked_locations',[]))
                    elif cmd=='LocationInfo':self.scouts.update({network_item(row)[1]:(network_item(row)[0],network_item(row)[2]) for row in packet['locations']})
                    elif cmd=='ReceivedItems':self.history=reconcile_history(self.history,packet['index'],packet['items'])
                    elif cmd=='Retrieved':self.retrieved.update(packet['keys'])
                    elif cmd=='Bounced':self.bounces.append(packet)
                    elif cmd=='PrintJSON' and packet.get('type')=='Goal':self.goals.add(packet['slot'])
        self.task=asyncio.create_task(reading());await self.wait(lambda:self.info,'RoomInfo')
        await self.send(dict(cmd='Connect',name=self.name,game=self.game,password='',uuid=str(uuid.uuid4()),items_handling=7,
            slot_data=True,tags=['AP','DeathLink'],version=dict(major=0,minor=6,build=7,**{'class':'Version'})))
        await self.wait(lambda:self.connected,'Connected');await self.fence();return self
    async def fence(self):
        key='ootrr-two-player-'+uuid.uuid4().hex
        await self.send(dict(cmd='Get',keys=[key]));await self.wait(lambda:key in self.retrieved,'Get fence')
    async def scout(self,locations):
        for start in range(0,len(locations),200):await self.send(dict(cmd='LocationScouts',locations=locations[start:start+200],create_as_hint=0))
        await self.wait(lambda:set(locations)<=self.scouts.keys(),'all source scouts')
    async def close(self):
        if self.ws:await self.ws.close()
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):await self.task


class Proxy:
    """Loopback transport fault injection, retaining real AP authentication."""
    def __init__(self,upstream):
        self.upstream=upstream;self.server=None;self.packets=[];self.compression=[]
        self.inject_hole=True;self.holes=0;self.duplicates=0;self.syncs=0;self.active=[]
        self.last_receipt=None;self.conflicts=0
    async def start(self):
        from websockets.legacy.client import connect
        from websockets.legacy.server import serve
        from websockets.exceptions import ConnectionClosed
        async def relay(incoming):
            self.compression.append(bool(incoming.extensions));self.active.append(incoming)
            async with connect(self.upstream,max_size=40<<20) as outgoing:
                async def forward(source,target,from_client):
                    try:
                        async for frame in source:
                            packets=json.loads(frame)
                            if from_client:
                                self.packets.extend(packets)
                                self.syncs+=sum(p.get('cmd')=='Sync' for p in packets)
                            else:
                                amended=[]
                                for packet in packets:
                                    if packet.get('cmd')=='ReceivedItems' and packet.get('items'):
                                        self.last_receipt=packet
                                        if self.inject_hole:
                                            self.inject_hole=False;self.holes+=1
                                            amended.append({**packet,'index':packet['index']+len(packet['items'])+1})
                                        amended.append(packet);amended.append(packet);self.duplicates+=1
                                    else:amended.append(packet)
                                packets=amended
                            await target.send(json.dumps(packets))
                    except ConnectionClosed:pass
                    finally:await target.close()
                await asyncio.gather(forward(incoming,outgoing,True),forward(outgoing,incoming,False))
        self.server=await serve(relay,'127.0.0.1',0,max_size=40<<20)
        self.uri='ws://127.0.0.1:'+str(self.server.sockets[0].getsockname()[1]);return self
    async def conflict(self,known_items):
        """Corrupt one previously committed tuple, never an unknown item ID."""
        assert self.last_receipt and self.active
        packet=json.loads(json.dumps(self.last_receipt));first=packet['items'][0]
        item=network_item(first)[0];replacement=next(i for i in known_items if i!=item)
        if isinstance(first,dict):first['item']=replacement
        else:first[0]=replacement
        await self.active[-1].send(json.dumps([packet]));self.conflicts+=1
    async def close(self):
        if self.server:self.server.close();await self.server.wait_closed()


async def exercise_network(case,host,manifests,data,library):
    from unittest.mock import patch
    from ootrr_triforce import native_setup
    from ootrr_triforce.catalog import GAME,ITEM_IDS,LOCATION_IDS
    from ootrr_triforce.trade_receipts import replay_receipts
    root=case/'network';root.mkdir()
    with ZipFile(next((case/'output').glob('*.zip'))) as archive:
        member=next(n for n in archive.namelist() if n.endswith('.archipelago'))
        multidata=root/Path(member).name;multidata.write_bytes(archive.read(member))
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    serverlog=(root/'server.log').open('wb');workerlog=(root/'workers.log').open('wb')
    env=dict(os.environ,LOCALAPPDATA=str(root/'local'),APPDATA=str(root/'roaming'),TEMP=str(root/'temp'),TMP=str(root/'temp'))
    for directory in ('local','roaming','temp'):(root/directory).mkdir()
    server=subprocess.Popen([str(host/'ArchipelagoServer.exe'),str(multidata),'--host','127.0.0.1','--port',str(port),'--disable_save'],
        cwd=root,env=env,stdin=subprocess.PIPE,stdout=serverlog,stderr=serverlog,creationflags=subprocess.CREATE_NO_WINDOW)
    upstream='ws://127.0.0.1:'+str(port)
    peers={};proxies={};workers={};allworkers=[];configs={};rosters={};last={};results={}
    byslot={m['player']:m for m in manifests};byitem={v:k for k,v in ITEM_IDS.items()}
    bylocation={v:k for k,v in LOCATION_IDS.items()};started=time.monotonic()
    async def boot(slot):
        instance=Worker(root/('profile-'+str(slot)),byslot[slot]['token'],library,workerlog)
        allworkers.append(instance);workers[slot]=instance;await instance.start();return await instance.ready()
    def expected(slot):return [item for item,location,source in peers[slot].history if source!=slot or location<0]
    def packet_locations(slot):return [loc for p in proxies[slot].packets if p['cmd']=='LocationChecks' for loc in p['locations']]
    def flags_for(slot,locations):return sorted({flag for loc in locations for flag in configs[slot]['Checks'][str(loc)]['Flags']})
    async def settle(slot,checked):
        await peers[slot].wait(lambda:peers[slot].checked==set(checked),'exact authoritative checked set')
        await peers[slot].fence()
        return await workers[slot].ready(expected(slot))
    async def collect(slot,locations):
        await workers[slot].request(opened=flags_for(slot,locations))
    try:
        def listening():
            assert server.poll() is None,'Private AP server exited'
            return 'server listening on' in (root/'server.log').read_text(encoding='utf-8',errors='replace')
        await until(listening,'private server listen')
        for slot,m in sorted(byslot.items()):
            peer=await Observer(upstream,m['slot'],m.get('game',GAME)).start();peers[slot]=peer
            await peer.scout(sorted(data['locations'][slot]))
            assert peer.connected['slot']==slot and peer.scouts=={loc:(item,owner) for loc,(item,owner,_) in data['locations'][slot].items()}
            proxies[slot]=await Proxy(upstream).start()
            roster={bylocation[loc]:dict(item=byitem[item],item_id=item,owner=owner,player=byslot[owner]['slot'],local=owner==slot,game=GAME)
                    for loc,(item,owner,_) in data['locations'][slot].items()};rosters[slot]=roster
            profile=root/('profile-'+str(slot));profile.mkdir()
            with patch.object(native_setup,'detect_language',return_value='en'):
                native_setup.save_session(profile,dict(server=proxies[slot].uri,protected='',baseline=0),m,roster)
            config=json.loads((profile/'native-session.json').read_bytes())
            # Explicit ABI capability fixture. This is not an EVFL seal or an
            # inventory restoration test; the root effect matrix covers those.
            config['RecoveryLocations']=sorted(data['locations'][slot])
            trades=replay_receipts()
            if set(trades.values())<=set(config['RecoveryLocations']):config['TradeReplayReceipts']=trades
            write(profile/'native-session.json',config);configs[slot]=config
            last[slot]=await boot(slot)
            assert set(last[slot]['flags'])=={f for row in config['Checks'].values() for f in row['Flags']}
            assert last[slot]['history']==expected(slot)
        slots=sorted(byslot);a,b=slots
        orders={s:sorted(data['locations'][s]) for s in slots}
        for s in slots:random.Random(1000+s).shuffle(orders[s])
        chunks={s:[orders[s][:max(1,len(orders[s])//8)],orders[s][max(1,len(orders[s])//8):len(orders[s])//2],orders[s][len(orders[s])//2:]] for s in slots}
        checked={s:set() for s in slots}
        # Start connected, including deliberately duplicated and gapped item
        # packets. A true Sync/Get round trip must recover the authoritative stream.
        for s in slots:
            await collect(s,chunks[s][0]);checked[s].update(chunks[s][0]);await settle(s,checked[s])
        for s in slots:last[s]=await workers[s].ready(expected(s))
        initial_counts={s:len(expected(s)) for s in slots}
        # Both local collection while disconnected and friend's offline sends.
        assert (await workers[b].request(disconnect=True))['disconnect']==1
        await until(lambda:any(p['cmd']=='Connect' for p in proxies[b].packets),'initial connection captured')
        await collect(b,chunks[b][1]);checked[b].update(chunks[b][1])
        await collect(a,chunks[a][1]);checked[a].update(chunks[a][1]);await settle(a,checked[a])
        await peers[b].fence();assert peers[b].checked==set(chunks[b][0]),'Offline observations escaped disconnected transport'
        assert (await workers[b].request(connect=proxies[b].uri))['connect']==1
        await settle(b,checked[b])
        await workers[a].ready(expected(a));await workers[b].ready(expected(b))
        # The other player disappears as a process while all final checks are
        # collected by its friend; restart must replay remote history exactly.
        await workers[a].close()
        await collect(b,chunks[b][2]);checked[b].update(chunks[b][2]);await settle(b,checked[b])
        last[a]=await boot(a);await workers[a].ready(expected(a))
        await collect(a,chunks[a][2]);checked[a].update(chunks[a][2]);await settle(a,checked[a])
        for s in slots:
            await peers[s].fence();last[s]=await workers[s].ready(expected(s))
            previous_syncs=proxies[s].syncs
            await proxies[s].conflict(ITEM_IDS.values())
            await until(lambda:proxies[s].syncs>previous_syncs,'conflicting tuple Sync request')
            last[s]=await workers[s].ready(expected(s))
            assert peers[s].checked==set(data['locations'][s])
            required=Counter((item,loc,source) for source,rows in data['locations'].items() for loc,(item,owner,_) in rows.items() if owner==s)
            start=[row for row in peers[s].history if row[1]<0]
            assert Counter(row for row in peers[s].history if row[1]>=0)==required
            assert len(peers[s].history)==sum(required.values())+len(start)
            assert proxies[s].holes==1 and proxies[s].duplicates>0 and proxies[s].syncs>=2
            assert all(p['items_handling']==5 for p in proxies[s].packets if p['cmd']=='Connect')
            assert all(proxies[s].compression)
            history=list(last[s]['history'])
            # The game cursor is explicitly modeled; AP_Applied announces a
            # completed receipt, it does not own the saved game cursor.
            await workers[s].request(applied=list(range(len(history)))+list(range(len(history))))
            assert (await workers[s].request())['history']==history
            duplicate_before=len(packet_locations(s));await collect(s,orders[s])
            await asyncio.sleep(.4);assert len(packet_locations(s))==duplicate_before
            assert set(packet_locations(s))==set(orders[s])
            journal=root/('profile-'+str(s))/'native-checks.json'
            assert set(json.loads(journal.read_bytes())['Locations'])==set(orders[s])
            await workers[s].close();journal.rename(journal.with_name('native-checks.before-rollback.json'))
            restarted=await boot(s);await workers[s].ready(history)
            assert restarted['cursor_hash']==last[s]['cursor_hash']
            assert set(json.loads(journal.read_bytes())['Locations'])==set(orders[s])
            invalid=await workers[s].request(invalid_restore=True)
            assert invalid['invalid_restore']==invalid['short_restore']==0
            deferred=(await workers[s].request(defer_first_restore=True))['deferred']
            restored=await workers[s].request(restore_all=True)
            assert set(restored['restored'])==set(orders[s])-{deferred}
            await asyncio.sleep(2.1)
            final_restore=await workers[s].request(restore_all=True)
            assert final_restore['restored']==[deferred]
            restored['restored']+=final_restore['restored']
            assert len(restored['restored'])==len(orders[s])
            assert (await workers[s].request(restore_all=True))['restored']==[]
            await collect(s,orders[s]);await asyncio.sleep(.4)
            assert len(packet_locations(s))==duplicate_before,'Server-restored check was re-emitted'
            assert (await workers[s].request())['history']==history,'Rollback shifted received-item indices'
            replay=await workers[s].request(trade_replays=True)
            expected_replays=[i for i,item in enumerate(history) if str(item) in {str(k) for k in configs[s].get('TradeReplayReceipts',{})}]
            assert replay['trade_replays']==expected_replays and replay['invalid_trade_replay']==0
            results[s]=dict(checks=len(orders[s]),complete_observer_history=len(peers[s].history),native_remote_history=len(history),
                starting_items=len(start),restored_modeled_checks=len(restored['restored']),trade_replay_indices=len(expected_replays),
                initial_remote_history=initial_counts[s],location_check_packets=len(packet_locations(s)),duplicate_receipt_packets=proxies[s].duplicates,
                injected_index_holes=proxies[s].holes,sync_requests=proxies[s].syncs,
                conflicting_historical_tuples=proxies[s].conflicts,deferred_restoration_retried=True,
                history_sha256=hashlib.sha256(json.dumps(peers[s].history).encode()).hexdigest())
        # Two real native clients/server Bounces, only for YAMLs enabling it.
        deathlink=False
        if all(configs[s]['DeathLink'] for s in slots):
            # Title/loading invalidates a live event. Explicit busy/paused state
            # holds it until ordinary control resumes; these are distinct APIs.
            await workers[a].request(death=0);await workers[b].request(death=-1)
            before=len(peers[b].bounces);assert (await workers[a].request(death=1))['death']==0
            await peers[b].wait(lambda:len(peers[b].bounces)>before,'inactive DeathLink Bounce')
            await asyncio.sleep(.15);assert (await workers[b].request(death=0))['death']==0
            await workers[a].request(death=0);await workers[b].request(death=2)
            before=len(peers[b].bounces);assert (await workers[a].request(death=1))['death']==0
            await peers[b].wait(lambda:len(peers[b].bounces)>before,'paused DeathLink Bounce')
            assert (await workers[b].request(death=2))['death']==0
            deadline=time.monotonic()+3
            while not (await workers[b].request(death=0))['death']:
                assert time.monotonic()<deadline,'Busy DeathLink was not released after control resumed'
                await asyncio.sleep(.025)
            sent_before=sum(p['cmd']=='Bounce' for p in proxies[b].packets)
            assert (await workers[b].request(death=1))['death']==0
            await asyncio.sleep(.35)
            assert sum(p['cmd']=='Bounce' for p in proxies[b].packets)==sent_before,'Received DeathLink echoed back'
            # A subsequent independent death in the other game must still work.
            await workers[a].request(death=0);await workers[b].request(death=0)
            before=len(peers[a].bounces);await workers[b].request(death=1)
            await peers[a].wait(lambda:len(peers[a].bounces)>before,'reverse DeathLink Bounce')
            deadline=time.monotonic()+3
            while not (await workers[a].request(death=0))['death']:
                assert time.monotonic()<deadline,'Reverse DeathLink was not delivered'
                await asyncio.sleep(.025)
            deathlink=True
        for s in slots:await workers[s].request(goal=True)
        await until(lambda:all(any(p['cmd']=='StatusUpdate' and p['status']==30 for p in proxies[s].packets) for s in slots),'both goal statuses')
        await until(lambda:all(m['slot']+' (Team #1) has completed their goal.' in
            (root/'server.log').read_text(encoding='utf-8',errors='replace') for m in manifests),'authoritative server goals')
        await asyncio.sleep(.35)
        for s in slots:assert (await workers[s].request())['history']==expected(s),'Completion released duplicate or unexpected items'
        for s in slots:
            statuses=sum(p['cmd']=='StatusUpdate' and p['status']==30 for p in proxies[s].packets)
            checks_before=len(packet_locations(s));await workers[s].close();await boot(s)
            await workers[s].ready(expected(s))
            await until(lambda:sum(p['cmd']=='StatusUpdate' and p['status']==30 for p in proxies[s].packets)>statuses,
                'completed status after process restart')
            assert len(packet_locations(s))==checks_before,'Completion restart re-emitted source checks'
        write(root/'wire-summary.json',{s:proxies[s].packets for s in slots})
        return dict(result='PASS',seconds=round(time.monotonic()-started,3),players=results,
            actual_local_server=True,actual_native_dlls=True,all_enabled_checks_both_players=True,
            packet_owner_item_multiplicity_validated=True,offline_pending_checks_recovered=True,offline_remote_items_recovered=True,
            process_restart_exact_history=True,out_of_order_sync_recovered=True,conflicting_history_sync_recovered=True,
            duplicate_packets_do_not_duplicate_items=True,deferred_restoration_does_not_starve_other_checks=True,
            old_save_model_all_checks_recovered=True,server_rebuilt_lost_journal=True,goals_both_players=True,
            completion_survives_process_restart=True,deathlink_tested=deathlink,deathlink_bidirectional=deathlink,
            game_started=False,inventory_effects_tested=False,source_collection='Modeled registered flag API calls, not physical Zelda walkthrough',
            restoration_capability='Explicit private native-session fixture, not prepared EVFL capability validation',
            receipt_cursor='Explicit game cursor model; AP_Applied is a notice, not a saved inventory acknowledgement')
    finally:
        for worker in reversed(allworkers):await worker.close()
        for proxy in proxies.values():await proxy.close()
        for peer in peers.values():await peer.close()
        if server.poll() is None:
            with contextlib.suppress(BrokenPipeError):server.stdin.write(b'/exit\n');server.stdin.flush()
            try:await asyncio.wait_for(asyncio.to_thread(server.wait),10)
            except asyncio.TimeoutError:server.terminate();await asyncio.to_thread(server.wait,10)
        serverlog.close();workerlog.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ap-root',type=Path,default=Path('C:/ProgramData/Archipelago'))
    parser.add_argument('--dependencies',type=Path,default=ROOT/'build/ap-test-dependencies-0103-public')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--cases',default='default,broad')
    parser.add_argument('--seeds-per-case',type=int,default=1)
    parser.add_argument('--generate-only',action='store_true')
    parser.add_argument('--room',type=Path,help='Network-only replay of a previously generated two-OOT-player room ZIP; never copy its save')
    args=parser.parse_args()
    output,host,candidate,report=stage(args)
    if args.room:
        from test_network_generation import read_multidata
        from ootrr_triforce.player import read_manifest
        case=output/'existing-room';(case/'output').mkdir(parents=True)
        copied=case/'output'/args.room.name;shutil.copy2(args.room,copied)
        with ZipFile(copied) as archive:
            data=read_multidata(archive);manifests=[]
            for name in archive.namelist():
                if name.endswith('.apootrr'):
                    path=case/Path(name).name;path.write_bytes(archive.read(name));manifests.append(read_manifest(path))
        assert len(manifests)==2 and len(data['locations'])==2,'Choose exactly two OOT Remake players'
        assert all(m.get('local_items') and m.get('reward_mode')=='all_locations' for m in manifests)
        report['source_room_sha256']=sha(copied)
        try:report['network']=asyncio.run(exercise_network(case,host,manifests,data,output/'runtime/archipelago.dll'));report['result']='PASS'
        except BaseException:report.update(result='FAIL',error=traceback.format_exc())
        write(output/'campaign.json',report);print(json.dumps(report),flush=True)
        return int(report['result']!='PASS')
    from test_network_generation import broad_values
    from ootrr_triforce.settings import default_options,validate_options
    selected=set(args.cases.split(',')) if args.cases!='all' else {x[0] for x in configurations()}
    assert selected<={x[0] for x in configurations()}
    report['cases']=[]
    for number,(name,broad,left,right) in enumerate(configurations()):
        if name not in selected:continue
        for repeat in range(args.seeds_per_case):
            case=output/(name+'-'+str(repeat+1));seed=202611280000+number*100+repeat
            values=[dict(broad_values() if broad else default_options(),**left),dict(broad_values() if broad else default_options(),**(right or left))]
            result=dict(case=case.name,seed=seed,result='RUNNING',real_gameplay=False,requested_options=dict(zip(PLAYERS,values)))
            try:
                for value in values:validate_options(value)
                archive,seconds=generate(host,case,seed,values)
                manifests,data,audit=audit_generation(archive,values)
                result.update(generation_seconds=seconds,generation=audit,archive=str(archive))
                if not args.generate_only:
                    result['network']=asyncio.run(exercise_network(case,host,manifests,data,output/'runtime/archipelago.dll'))
                result['result']='PASS'
            except BaseException:
                result.update(result='FAIL',error=traceback.format_exc())
            report['cases'].append(result);write(output/'campaign.json',report);write(case/'result.json',result)
            print(json.dumps(result),flush=True)
    return int(any(x['result']!='PASS' for x in report['cases']))


if __name__=='__main__':
    if len(sys.argv)==5 and sys.argv[1]=='--worker':native_worker(Path(sys.argv[2]),sys.argv[3],Path(sys.argv[4]))
    else:raise SystemExit(main())
