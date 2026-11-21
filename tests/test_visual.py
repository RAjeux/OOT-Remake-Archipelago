"""An end-to-end RomFS composed from authored miniature game-format resources."""
import hashlib, io, json, struct, sys, tempfile, uuid, zlib
from pathlib import Path
import zstandard as zs
sys.path.insert(0,str(Path("dist/Client-OOT-Remake.pyz").resolve()))
import ainb
from ainb.blackboard import InheritMode
from evfl import EventFlow
from evfl.flowchart import Flowchart
from evfl.entry_point import EntryPoint
from evfl.actor import Actor
from evfl.common import ActorIdentifier, StringHolder, Argument
from evfl.container import Container
from evfl.util import make_index
from evfl.util import make_rindex
from evfl.event import Event,SubFlowEvent,ActionEvent
from oot_rando.formats import byml_codec as by,msbt
from oot_rando.formats.inspect_resources import sarc
from oot_rando.patching import ap_item as ap, soul_adapter as soul, repeatable_adapter as rep, chest_flags as ch,event_info
sys.argv[0]=str(Path('dist/Client-OOT-Remake.pyz').resolve())
from ootrr_triforce.catalog import CHESTS, ITEM_DATA, ITEM_IDS
from ootrr_triforce.medallions import GET,CHEST_ENTRY,REST,prepare,plan_maps,chest_flows
from ootrr_triforce.mod_codec import Codec
from oot_rando.patching.progressive import FlowEditor, link

CHEST_GIVE=('GetPouchContent','GetPouchContentByActorNameForTreasureBox')

def dump(v):
    return by.dump({"root":v,"endian":"<","version":7})

def flow(name, entry):
    f=EventFlow()
    f.name=name
    f.flowchart=Flowchart()
    chart=f.flowchart
    chart.name=name
    e=EntryPoint(entry)
    chart.entry_points=[e]
    s=io.BytesIO()
    assert f.write(s)
    return s.getvalue()

def chest_flow(name):
    f=EventFlow();f.name=name;f.flowchart=chart=Flowchart();chart.name=name
    chest=Actor();chest.identifier=ActorIdentifier('TreasureBox_EventStarter')
    chest.actions=[StringHolder('EventTriggerTreasureBoxOpened')]
    chart.actors=[chest]
    opened=Event();opened.name='OpenChest';opened.data=ActionEvent()
    opened.data.actor=make_rindex(chest);opened.data.actor_action=make_rindex(chest.actions[0])
    token=Event();token.name='PresentContent';token.data=SubFlowEvent()
    token.data.res_flowchart_name,token.data.entry_point_name=CHEST_GIVE
    token.data.params=Container();token.data.params.data={'ActorName':Argument('ContentName')}
    token.data.nxt=make_index(opened)
    original=Event();original.name='OriginalKeyGrant';original.data=SubFlowEvent()
    original.data.res_flowchart_name,original.data.entry_point_name=GET
    original.data.params=Container();original.data.params.data={'ActorName':'TBox_DungeonKey','IsNpcEventStarter':False}
    chart.events=[opened,token,original]
    for label,event in [(CHEST_ENTRY,token),('Success',original),('Success_LocalKey',original)]:
        entry=EntryPoint(label);entry.main_event=make_index(event);chart.entry_points.append(entry)
    stream=io.BytesIO();assert f.write(stream);return stream.getvalue()

def native_pouch():
    f=EventFlow();f.name='GetPouchContent';f.flowchart=Flowchart();f.flowchart.name=f.name
    actor=Actor();actor.identifier=ActorIdentifier('GameSystemActor');f.flowchart.actors=[actor]
    stream=io.BytesIO();assert f.write(stream);editor=FlowEditor(stream.getvalue(),'native pouch fixture')
    prepare=editor.action('Prepare','PouchSystemActor','EventTriggerSetForGetWindow',{'Actor':Argument('ActorName')})
    popup=editor.subflow('Popup','','OpenGetWindow',None)
    grant=editor.action('Grant','PouchSystemActor','EventTriggerAddOrRemovePouchContent',
                       {'Num':1,'Actor':Argument('ActorName'),'IsGetEvent':Argument('IsGetInEvent')})
    save=editor.action('Save','GameSystemActor','EventTriggerRequestAutoSave',None)
    choice=editor.switch('SaveIfNeeded','PouchSystemActor','EventQueryIsAutoSavePouchContent',
                         {'ActorName':Argument('ActorName')},save,None)
    for node,next_node in [(prepare,popup),(popup,grant),(grant,choice)]:link(node,next_node)
    for name,root in [('GetPouchContent',prepare),('OpenGetWindow',None)]:
        entry=EntryPoint(name);entry.main_event=make_index(root);editor.chart.entry_points.append(entry)
    display=editor.action('DisplayPrepare','PouchSystemActor','EventTriggerSetForGetWindow',{'Actor':Argument('ActorName')})
    only_popup=editor.subflow('DisplayPopup','','OpenGetWindow',None);link(display,only_popup)
    entry=EntryPoint('DisplayGetByActorName');entry.main_event=make_index(display);editor.chart.entry_points.append(entry)
    return editor.write('native pouch fixture')[0]

def ai():
    a=ainb.AINB().as_dict()
    a.update(Version=0x408,Category="AI",Filename="PouchContent.event.root")
    a["Replacement Table"]=[]
    a["Has Section 0x6C"]=True
    a["Blackboard"]={"Bool":[{"Name":"test","Notes":"","Inherit Mode":next(iter(InheritMode)).name,"Default Value":False}]}
    for i,(typ,name) in enumerate([("Element_Sequential",""),("UserDefined","OneShotPouchContentPushToPouchOwnInEvent"),("UserDefined","QueryGetNonStructGameDataBool"),("Element_BoolSelector",""),("UserDefined","OneshotDoNothing")]):
        node={"Node Type":typ,"Node Index":i,"Name":name,"GUID":str(uuid.uuid4()),"Flags":[],"Queries":[],"Attachments":[],"Properties":{},"Parameters":{"Inputs":{},"Outputs":{}},"XLink Actions":[],"Plugs":{}}
        if i==0: node["Plugs"]={"Child":[{"Node Index":1,"Name":""}]}
        if i==2: node["Flags"]=["Is Query"]; node["Parameters"]["Outputs"]={"Bool":[{"Name":"Value","Is Output":True}]}
        a["Nodes"].append(node)
    raw=ainb.AINB.from_dict(a).to_binary()
    assert rep.instrument_pickup_event(raw,"IsGet.Test","test")
    return raw

def bntx(name,width,height,fmt):
    data=bytearray(512+max(512,width*height))
    data[:4]=b'BNTX'
    at=64
    data[at:at+4]=b'BRTI'
    for o,pat,v in [(0x16,'H',1),(0x1c,'I',fmt<<8|1),(0x24,'I',width),(0x28,'I',height),(0x50,'I',len(data)-512),(0x70,'Q',384)]:
        struct.pack_into('<'+pat,data,at+o,v)
    struct.pack_into('<Q',data,384,512)
    data[250:250+len(name)]=name.encode()
    return bytes(data)

def bfres():
    data=bytearray(0x2600); data[:8]=b'FRES    '
    rlt=0x1800
    struct.pack_into('<I',data,0x18,rlt);data[rlt:rlt+4]=b'_RLT'
    struct.pack_into('<I',data,rlt+48,0x2000)
    for i,name in enumerate([*ap.HIDDEN_SHAPES,ap.RELIEF[0]]):
        at=0x50+i*0x300; fv=at+0x70; attr=at+0x100; mesh=at+0x120; nm=at+0x160; pos=at+0x1a0
        data[at:at+4]=b'FSHP';data[fv:fv+4]=b'FVTX'
        for o,v in [(at+8,nm),(at+16,fv),(at+24,mesh),(fv+8,attr),(fv+0x38,at+0x1c0),(attr,pos)]:struct.pack_into('<Q',data,o,v)
        for o,st in [(nm,name),(pos,'_p0')]:struct.pack_into('<H',data,o,len(st));data[o+2:o+2+len(st)]=st.encode()
        data[fv+0x4c:fv+0x4e]=b'\1\1';struct.pack_into('<HHH',data,attr+8,0x1505,0,0)
        data[at+0x5b]=1;struct.pack_into('<5I',data,mesh+0x20,0,3,1,6,0)
        struct.pack_into('<6H',data,0x2000,0,1,2,2,3,0)
        struct.pack_into('<I',data,at+0x1c0,8);struct.pack_into('<I',data,fv+0x48,64+i*64);struct.pack_into('<I',data,fv+0x50,4)
        for j in range(4):struct.pack_into('<4e',data,0x2040+i*64+j*8,.01*j,.01*j,.05,1.)
    for j,suffix in enumerate(ap.REPLACED):
        s=(ap.OLD_TEX+'_'+suffix).encode();addr=0x1000+64*j;data[addr:addr+len(s)]=s
    return bytes(data)

def message():
    head=bytearray(32);head[:10]=b'MsgStdBn\xff\xfe';struct.pack_into('<H',head,14,2)
    lbl=struct.pack('<III',1,0,12)
    m=msbt.Msbt(head,[(b'LBL1',lbl),(b'TXT2',b'')],{},[],1)
    m.add(soul.TEMPLATE+'_GetMessage','Base')
    return by.build_sarc({soul.MESSAGE_FILE:msbt.dump(m)})

def resources(roster, moved):
    d={}
    by_path={}
    for n in roster:
        for ref in CHESTS[n]:
            for path in ref['files']:
                dyn={'Drop__DropActor':('TBox_Rupee_Green' if n in moved else 'TBox_DungeonKey')}
                if n not in moved:
                    dyn.update(Drop__DropActor_Substitute='LocalAlternative',GetEventName='LocalKeyGrant')
                by_path.setdefault(path,[]).append({'Hash':by.U64(int(ref['actor'])),
                    'Gyaml':'Obj_TBox_A_02' if n in moved else 'Obj_TBox_A_01','Dynamic':dyn})
    for path,actors in by_path.items():d[path]=dump({'Actors':actors+[{'Hash':by.U64(1982),'Gyaml':'Other'}]})
    chest_events=('Dm_SY_TreasureboxSmall','Dm_SY_Treasurebox')
    settings=[{'__RowId':event,'FlowchartFileName':'Work/Event/EventFlow/'+event+'.evfc','EntryPointName':'Success'}
              for event in chest_events]
    settings.append({'__RowId':'LocalKeyGrant','FlowchartFileName':'Work/Event/EventFlow/Dm_SY_TreasureboxSmall.evfc',
                     'EntryPointName':'Success_LocalKey'})
    d[ch.EVENT_SETTINGS]=dump(settings)
    d[ch.ANALYZED]=dump([{'__RowId':event,'SubFlowList':[CHEST_GIVE[0],'ExistingFlow']} for event in chest_events])
    for event in chest_events:d[event_info.flow_path(event)]=chest_flow(event)
    d[event_info.flow_path(GET[0])]=flow(*GET)
    d[event_info.flow_path('GetPouchContent')]=native_pouch()
    d[rep.EVENT_PACK]=by.build_sarc({rep.EVENT_MEMBER:ai()})
    def actorpack(actor,files):
        d['Pack/Actor/'+actor+'.pack.zs']=by.build_sarc(files)
    for actor in [soul.TEMPLATE,ap.MODEL_ACTOR]:
        actorpack(actor,{f'Actor/{actor}.engine__actor__ActorParam.bgyml':dump({'Components':{'ActorNameRef':'?Base'}}),
                         f'Component/ModelInfo/{actor}.engine__component__ModelInfo.bgyml':dump({'FmdbName':actor})})
    actorpack(ap.SPIN_TEMPLATE,{'Component/ASInfo/Item_GetDemo.engine__component__ASInfo.bgyml':dump({})})
    for path in soul.RSDB_FILES.values():
        d[path]=dump([{'__RowId':a,'InstanceHeapSize':8192,'ActorName':a} for a in (soul.TEMPLATE,ap.MODEL_ACTOR)])
    flag=by.U32(soul.murmur3('IsGet.'+soul.TEMPLATE))
    d[soul.GAMEDATA]=dump({'Data':{'Bool':[{'Hash':flag,'DefaultValue':False,'SaveFileIndex':0}],
        'Struct':[{'Hash':by.U32(soul.murmur3('IsGet')),'DefaultValue':[{'Hash':by.U32(soul.murmur3(soul.TEMPLATE)),'Value':flag}]}]},
        'MetaData':{'SaveDataSize':[32],'SaveDataOffsetPos':[32],'AllDataSaveSize':32,'AllDataSaveOffset':32}})
    for lang in ('EUfr','USen'):d[f'Mals/{lang}.Product.110.sarc.zs']=message()
    for suffix in ap.REPLACED:
        src=ap.SOURCES.get(suffix,f'Tex/{ap.OLD_TEX}_{suffix}.bntx.zs')
        d[src]=bntx(src[4:-8],576 if suffix in ('Alb','Mtl') else 32,576 if suffix in ('Alb','Mtl') else 32,
                    ap.BC1 if suffix=='Alb' else 0x2d if suffix in ('Nrm','Emc') else ap.BC4)
    d[ap.MODEL_FILE]=bfres()
    crcs=sorted((zlib.crc32(p[:-3].encode()),len(v)+4096) for p,v in d.items())
    d[REST]=b'RESTBL'+struct.pack('<4I',1,160,len(crcs),0)+b''.join(struct.pack('<II',*t) for t in crcs)
    return d, by_path

def check():
    roster={'KF Midos Bottom Left Chest':('Longsword +3','Ami'),'KF Midos Bottom Right Chest':('Mirror Shield','Fée')}
    moved={'KF Midos Bottom Right Chest'}
    if "--room" in sys.argv:
        roster, moved = json.loads(Path("tests/fixtures/scouts.json").read_text())
    with tempfile.TemporaryDirectory() as td:
        root=Path(td); game=root/'game'; base=root/'mods'/'Archipelago'/'romfs';base.mkdir(parents=True)
        dic=zs.train_dictionary(1024,[f'the map record {i} has a value {i%11+j} '.encode()*15 for i in range(250) for j in range(2)],dict_id=3)
        plain=zs.ZstdCompressor(); enc=zs.ZstdCompressor(dict_data=dic)
        pack=plain.compress(by.build_sarc({'map.dict':dic.as_bytes()}))
        p=game/'Pack/ZsDic.pack.zs';p.parent.mkdir(parents=True);p.write_bytes(pack)
        res,paths=resources(roster,moved)
        for k,v in res.items():
            # Active map comes from the old AP mod, including 0.1.3's dummy item.
            p=(base if k in paths else game)/k;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(enc.compress(v))
        def tree(path):return {p.relative_to(path):hashlib.sha256(p.read_bytes()).digest() for p in path.rglob('*') if p.is_file()}
        baseline=tree(base);vanilla=tree(game)
        # Rooms created before full reward routing must keep native rewards.
        placements={name:ap.ap_item(json.dumps([name,*reward],ensure_ascii=False)) for name,reward in roster.items()}
        def source_raw(relative):
            path=base/relative
            return Codec(pack).decode((path if path.is_file() else game/relative).read_bytes())
        rows={row['__RowId']:row for row in by.load(source_raw(ch.EVENT_SETTINGS))['root']}
        legacy_maps,legacy_records=plan_maps(placements,moved,source_raw,rows)
        for path,patched_map in legacy_maps.items():
            for actor in by.load(patched_map)['root']['Actors'][:-1]:
                if actor['Gyaml']=='Obj_TBox_A_01':
                    assert actor['Dynamic']['Drop__DropActor']=='TBox_DungeonKey'
                    assert actor['Dynamic']['Drop__DropActor_Substitute']=='LocalAlternative'
        for path,records in ch.by_flow(legacy_records).items():
            legacy=EventFlow();legacy.read(chest_flows(source_raw(path),records))
            for record in records:
                first=next(e for e in legacy.flowchart.entry_points if e.name==record['event']).main_event.v
                assert record['legacy'] and first.data.entry_point_name=='Success_LocalKey'
                assert first.data.nxt.v.data.res_flowchart_name==GET[0]
        cfg={'romfs':str(game),'reward_mode':'all_chest_rewards'}
        dest=prepare(root,cfg,roster,moved);patched=dest/'Archipelago'/'romfs'; codec=Codec(pack)
        def raw(p):return codec.decode((patched/p).read_bytes())
        actors={}
        for n,(item,player) in roster.items():
            key=ap.ap_item(json.dumps([n,item,player],ensure_ascii=False));actor=ap.ap_actor(key);actors[n]=actor
            assert soul.soul_event_member(actor) in sarc(raw(f'Pack/Actor/{actor}.pack.zs'))
            texts=msbt.load(sarc(raw('Mals/EUfr.Product.110.sarc.zs'))[soul.MESSAGE_FILE])
            assert item in texts.get(actor+'_Caption').decode() and player in texts.get(actor+'_Caption').decode()
            assert texts.get(actor+'_GetMessage').decode().rstrip('\0')==f'Vous avez trouvé « {item} » pour {player} !'
        for path,native in paths.items():
            output=by.load(raw(path))['root']['Actors']
            assert output[-1]['Gyaml']=='Other'
            for a in output[:-1]:
                dyn=a['Dynamic']; n=next(n for n in roster if any(a['Hash']==int(ref['actor']) and path in ref['files'] for ref in CHESTS[n]))
                assert dyn['Drop__DropActor']==dyn['Drop__DropActor_Substitute']==actors[n]
                event=dyn['GetEventName']; table=by.load(raw(ch.ANALYZED))['root']
                assert next(r for r in table if r['__RowId']==event)['SubFlowList']==[CHEST_GIVE[0],'ExistingFlow']
                setting=next(r for r in by.load(raw(ch.EVENT_SETTINGS))['root'] if r['__RowId']==event)
                expected_flow=ch.default_event(a['Gyaml'])
                assert setting['FlowchartFileName'].endswith('/'+expected_flow+'.evfc')
                chart=EventFlow();chart.read(raw(event_info.flow_path(expected_flow)))
                entry=next(e for e in chart.flowchart.entry_points if e.name==event)
                only=entry.main_event.v
                assert only.data.entry_point_name==CHEST_ENTRY and only.data.res_flowchart_name==''
                assert only.data.params.data=={'ContentName':actors[n],'IsMiniGame':False}
                assert only.data.nxt.v is None
                generic=next(e for e in chart.flowchart.entry_points if e.name==CHEST_ENTRY)
                reachable=event_info.reachable(generic.main_event.v)
                assert [e.name for e in reachable]==['PresentContent','OpenChest']
                assert not any(e.name=='OriginalKeyGrant' for e in reachable)
                assert CHEST_GIVE in event_info.entry_calls(raw(event_info.flow_path(expected_flow)),event)
        assert ap.NEW_TEX.encode() in raw(ap.NEW_MODEL_FILE) and raw(REST).startswith(b'RESTBL')
        assert tree(base)==baseline and tree(game)==vanilla
        assert prepare(root,cfg,roster,moved)==dest
        if '--room' not in sys.argv:
            # V2 keeps foreign medals and gives self-owned rewards physically,
            # with a native model and no ReceivedItems cursor increment.
            owned='KF Midos Bottom Right Chest'
            own_roster={name:{'item':reward[0],'player':reward[1],'owner':2 if name==owned else 1,
                               'item_id':ITEM_IDS['Mirror Shield'] if name==owned else 100,
                               'local':name==owned} for name,reward in roster.items()}
            own_cfg={**cfg,'reward_mode':'all_locations','local_items':True,'player':2}
            own_dest=prepare(root,own_cfg,own_roster,moved)
            own_mod=own_dest/'Archipelago/romfs'
            def own_raw(relative):
                target=own_mod/relative
                return codec.decode((target if target.is_file() else game/relative).read_bytes())
            original_ref=CHESTS[owned][0]
            for relative in original_ref['files']:
                actor=next(a for a in by.load(own_raw(relative))['root']['Actors'] if a['Hash']==int(original_ref['actor']))
                assert actor['Dynamic']['Drop__DropActor']==ITEM_DATA['Mirror Shield']['actor']
                assert actor['Dynamic']['Drop__DropActor_Substitute']==ITEM_DATA['Mirror Shield']['actor']
                row=next(r for r in by.load(own_raw(ch.EVENT_SETTINGS))['root'] if r['__RowId']==actor['Dynamic']['GetEventName'])
                flow_path=event_info.flow_path(row['FlowchartFileName'].split('/')[-1][:-5])
                flow=EventFlow();flow.read(own_raw(flow_path));chart=flow.flowchart
                calls=event_info.entry_calls(own_raw(flow_path),row['EntryPointName'])
                assert calls=={('GetPouchContent','DisplayGetByActorName')}
                entries={e.name:e for e in chart.entry_points};seen=set();stack=[entries[row['EntryPointName']].main_event.v]
                actions=[]
                while stack:
                    event=stack.pop()
                    if event is None or event in seen:continue
                    seen.add(event);data=event.data
                    if isinstance(data,ActionEvent):
                        actions.append((data.actor_action.v.v,data.params.data if data.params else {}))
                    if isinstance(data,SubFlowEvent) and not data.res_flowchart_name:
                        stack.append(entries[data.entry_point_name].main_event.v)
                    stack.extend(event_info._successors(event))
                assert any(action=='EventTriggerAddOrRemovePouchContent' for action,params in actions)
                assert any(action=='EventTriggerTreasureBoxOpened' for action,params in actions)
                assert not any(str(params.get('GameDataName','')).startswith('Archipelago.ReceivedIndex.') for action,params in actions)
            local_actor=ap.ap_actor(ap.ap_item(json.dumps([owned,*roster[owned]],ensure_ascii=False)))
            assert not (own_mod/f'Pack/Actor/{local_actor}.pack.zs').exists()
            assert tree(base)==baseline and tree(game)==vanilla
        print(f'{len(roster)} chests; PASS AP-only staged mod: all normal/substitute drops replaced, one presentation, original key grant bypassed, chest opening preserved, actor packs, model, textures, text, allocations, cache, originals unchanged.')
if __name__=='__main__': check()
