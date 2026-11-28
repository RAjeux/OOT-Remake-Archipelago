"""Skipped native story gifts use actual AP rewards, without a second donor."""
import copy
import json
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'client')]
from evfl.entry_point import EntryPoint
from evfl.common import Argument
from evfl.event import ActionEvent, SubFlowEvent, SwitchEvent
from evfl.util import make_index
from oot_rando.patching.event_info import reachable
from oot_rando.patching.progressive import FlowEditor, link
from ootrr_triforce import opening_rewards as opening
from ootrr_triforce.catalog import ITEM_DATA, LOCATION_IDS
from ootrr_triforce.network_catalog import SOURCES, flag_name
from test_network_flows import editor as empty_editor
from test_restoration import pouch, reward
from test_heart_effects import HeartRun
from ootrr_triforce import shop_tracking as tracking


def records(items=(None, None), donors=opening.VANILLA, selected=(0, 1)):
    result = []
    for index in selected:
        name = opening.LOCATIONS[index]
        result.append(dict(name=name, generated_item=donors[index], flag_name=flag_name(name),
                           actor='Item_AP_OpeningFixture'+str(index),
                           **({'local_item': items[index]} if items[index] is not None else {})))
    return result


def native_opening(donors=opening.VANILLA, explicit=False, get_flags=None):
    editor = empty_editor(opening.FLOW)
    from ootrr_triforce.ap_skulls import _after_writes
    end = _after_writes(editor, 'NativeFinish', None)
    chain = []
    if explicit:
        explicit_actor=explicit if isinstance(explicit,str) else 'Item_DekuNut'
        chain.append(editor.action('OOTRRStartGet','GameDataActor','EventTriggerSetGameDataBool',
                                   dict(GameDataName='IsGet.'+explicit_actor,Index=-1,Value=True)))
        chain.append(editor.action('OOTRRStartGive', 'PouchSystemActor', opening.GIVE,
                                   dict(opening.GIFT_PARAMS, Actor=explicit_actor)))
    chain.append(editor.action('OOTRRStateQuest', 'GameDataActor', 'EventTriggerSetGameDataBool',
                               dict(GameDataName='Fixture.CastleStoryComplete', Index=-1, Value=True)))
    for actor in dict.fromkeys(ITEM_DATA[item]['actor'] for item in donors):
        if get_flags is not None and 'IsGet.'+actor not in get_flags:continue
        chain.append(editor.action('OOTRRStateGet'+str(len(chain)), 'GameDataActor', 'EventTriggerSetGameDataBool',
                                   dict(GameDataName='IsGet.'+actor, Index=-1, Value=True)))
    for actor in ['Pouch_Amiibo', *(ITEM_DATA[item]['actor'] for item in donors)]:
        chain.append(editor.action('OOTRRStateGive'+str(len(chain)), 'PouchSystemActor', opening.GIVE,
                                   dict(opening.GIFT_PARAMS, Actor=actor)))
    for left, right in zip(chain, [*chain[1:], end]):link(left, right)
    point = EntryPoint('Opening_Introduction');point.main_event = make_index(chain[0]);editor.chart.entry_points.append(point)
    return editor.write('native opening fixture')[0]


def build(raw, selected, *, trade_mode=False):
    return {opening.FLOW:opening.build_opening_flow(raw,pouch(),selected),
            'GetPouchContent':opening.build_reconciliation_flow(pouch(),selected,trade_mode=trade_mode)}


def run(raw, *, inventory=None, values=None, piece_count=0, old_save=False):
    result = HeartRun(raw, piece_count=piece_count,
                      commits=[flag_name(name) for name in opening.LOCATIONS])
    result.inventory.update(inventory or {})
    result.values.update(values or {})
    if not old_save:result.call(opening.FLOW, 'Opening_Introduction')
    result.call('GetPouchContent',opening.ENTRY)
    result.flush()
    return result


class OpeningRewardsTests(unittest.TestCase):
    def test_foreign_sources_replace_both_donors_and_retain_story(self):
        before = native_opening(('Zeldas Letter', 'Piece of Heart'))
        after = build(before, records(donors=('Zeldas Letter', 'Piece of Heart')))
        result = run(after)
        self.assertEqual(result.inventory['Pouch_Amiibo'], 1)
        self.assertEqual(result.inventory['Item_ZeldaLetter'], 0)
        self.assertEqual(result.inventory['Obj_Heart_Piece'], 0)
        self.assertTrue(result.values['Fixture.CastleStoryComplete'])
        for name in opening.LOCATIONS:self.assertTrue(result.values[flag_name(name)])
        self.assertNotIn('IsGet.Item_ZeldaLetter', result.values)
        self.assertNotIn('IsGet.Obj_Heart_Piece', result.values)
        self.assertFalse(result.saved)
        self.assertFalse(any('ReceivedIndex' in str(row) for row in result.trace))
        self.assertEqual(native_opening(('Zeldas Letter', 'Piece of Heart')), before)

    def test_both_hearts_use_one_native_effect_before_the_source_commit(self):
        for item in ('Heart Container', 'Piece of Heart'):
            with self.subTest(item=item):
                after = build(native_opening(), records((None,item)))
                result = run(after, piece_count=3)
                # Structural amiibo grant is retained, alongside exactly one actual heart.
                self.assertEqual(result.grants, 2)
                self.assertEqual(result.cures, 0)
                self.assertEqual(result.max_life, 20)
                self.assertTrue(result.values[flag_name(opening.LOCATIONS[1])])
                self.assertFalse(result.saved)
                again = run(after, inventory=dict(result.inventory), values=result.values)
                self.assertEqual(again.cures, 0)
                self.assertEqual(again.inventory[ITEM_DATA[item]['actor']], result.inventory[ITEM_DATA[item]['actor']])

    def test_progressive_reward_selects_next_owned_tier(self):
        after = build(native_opening(), records((None,'Progressive Hookshot')))
        result = run(after, inventory={'Item_Hookshot': 1})
        self.assertEqual(result.inventory['Item_Hookshot'], 1)
        self.assertEqual(result.inventory['Item_Longshot'], 1)
        self.assertEqual(result.inventory['Item_Melody_ZeldaLullaby'], 0)

    def test_two_progressive_start_checks_settle_between_their_native_tiers(self):
        after=build(native_opening(),records(('Progressive Hookshot','Progressive Hookshot')))
        result=run(after,old_save=True)
        self.assertEqual((result.inventory['Item_Hookshot'],result.inventory['Item_Longshot']),(1,1))
        self.assertTrue(all(result.values[flag_name(n)] for n in opening.LOCATIONS))

    def test_dungeon_key_uses_its_actual_dungeon_and_no_pouch_duplicate(self):
        item = 'Small Key (Fire Temple)'
        after = build(native_opening(), records((None,item)))
        result = run(after)
        self.assertEqual(result.values['DungeonInfo.FireTemple.SmallKeyNum'], 1)
        self.assertEqual(result.values['DungeonInfo.FireTemple.SmallKeyTotalNum'], 1)
        self.assertEqual(result.inventory[ITEM_DATA[item]['actor']], 0)

    def test_unselected_shared_donor_retains_its_deduplicated_isget(self):
        donors = ('Zeldas Letter', 'Zeldas Letter')
        after = build(native_opening(donors), records(donors=donors, selected=(1,)))
        result = run(after)
        self.assertEqual(result.inventory['Item_ZeldaLetter'], 1)
        self.assertTrue(result.values['IsGet.Item_ZeldaLetter'])
        self.assertNotIn(flag_name(opening.LOCATIONS[0]), result.values)
        self.assertTrue(result.values[flag_name(opening.LOCATIONS[1])])

    def test_identical_selected_donors_are_replaced_by_source_order(self):
        donors = ('Zeldas Letter', 'Zeldas Letter')
        after = build(native_opening(donors), records(('Deku Stick (1)',None),donors=donors))
        result = run(after)
        self.assertEqual(result.inventory['Item_ZeldaLetter'], 0)
        self.assertEqual(result.inventory['Item_DekuStick'], 1)
        self.assertNotIn('IsGet.Item_ZeldaLetter', result.values)

    def test_donor_without_native_isget_has_no_fictional_ownership_requirement(self):
        donors=('Zeldas Letter','Rupees (20)')
        flags={'IsGet.Item_ZeldaLetter'}
        raw=native_opening(donors,get_flags=flags)
        after=opening.build_opening_flow(raw,pouch(),records(donors=donors),get_flags=flags)
        result=HeartRun({opening.FLOW:after});result.call(opening.FLOW,'Opening_Introduction');result.flush()
        self.assertEqual(result.inventory['Pouch_Amiibo'],1)
        self.assertEqual(result.inventory[ITEM_DATA['Rupees (20)']['actor']],0)
        with self.assertRaises(ValueError):opening.build_opening_flow(raw,pouch(),records(donors=donors),get_flags=flags|{'IsGet.'+ITEM_DATA['Rupees (20)']['actor']})

    def test_explicit_starting_items_and_native_story_nodes_are_unchanged(self):
        before = native_opening(explicit=True)
        after = build(before, records())
        self.assertEqual(run(after).inventory['Item_DekuNut'], 1)
        left = FlowEditor(before, 'before').chart;right = FlowEditor(after[opening.FLOW], 'after').chart
        for name in ('OOTRRStartGive','OOTRRStateQuest'):
            a = next(e for e in left.events if e.name==name);b = next(e for e in right.events if e.name==name)
            self.assertEqual(a.data.params.data,b.data.params.data)
            self.assertEqual(str(a.data.actor.v.identifier),str(b.data.actor.v.identifier))
        self.assertEqual(opening.build_opening_flow(before,pouch(),[]),before)

    def test_explicit_starting_grant_with_exact_donor_actor_overlap_is_retained(self):
        donors=('Zeldas Letter','Bottle')
        before=native_opening(donors,explicit=ITEM_DATA['Bottle']['actor'])
        after=build(before,records(donors=donors))
        result=run(after)
        self.assertEqual(result.inventory[ITEM_DATA['Bottle']['actor']],1)
        self.assertTrue(result.values['IsGet.'+ITEM_DATA['Bottle']['actor']])
        left=FlowEditor(before,'before').chart;right=FlowEditor(after[opening.FLOW],'after').chart
        for name in ('OOTRRStartGet','OOTRRStartGive'):
            a=next(e for e in left.events if e.name==name);b=next(e for e in right.events if e.name==name)
            self.assertEqual(a.data.params.data,b.data.params.data)
            self.assertEqual(opening._action(a),opening._action(b))

    def test_reconciliation_does_not_change_existing_pouch_entry_targets_or_parameters(self):
        raw=pouch();before=FlowEditor(raw,'before').chart
        after=FlowEditor(opening.build_reconciliation_flow(raw,records((None,'Piece of Heart'))),'after').chart
        points={p.name:p for p in after.entry_points}
        for point in before.entry_points:
            actual=points[point.name]
            self.assertEqual(actual.main_event.v.name if actual.main_event.v else None,point.main_event.v.name if point.main_event.v else None)
            self.assertEqual(actual._sub_flow_event_indices,point._sub_flow_event_indices)
        events={e.name:e for e in after.events}
        for event in before.events:
            actual=events[event.name]
            self.assertEqual(type(actual.data),type(event.data))
            self.assertEqual(actual.data.params.data if actual.data.params else None,event.data.params.data if event.data.params else None)
            if hasattr(event.data,'nxt'):
                self.assertEqual(actual.data.nxt.v.name if actual.data.nxt.v else None,event.data.nxt.v.name if event.data.nxt.v else None)

    def test_canonical_selected_donor_contract_and_legacy_noop(self):
        settings=dict(network_sources_schema=2,network_sources={})
        roster={}
        for name, donor in zip(opening.LOCATIONS,opening.VANILLA):
            settings['network_sources'][name]=dict(SOURCES[name],generated_item=donor)
            roster[name]=reward(local=False)
        self.assertEqual([r['name'] for r in opening.opening_records(roster,settings)],list(opening.LOCATIONS))
        self.assertEqual(opening.opening_records(roster,{}),[])
        self.assertEqual(opening.prepare_opening_rewards(Path('missing-game'),Path('missing-mod'),roster,{}),{'checks':[],'changed':False})
        self.assertEqual(opening.opening_records({},dict(network_sources_schema=1,network_sources={})),[])
        with patch('ootrr_triforce.engine.run_engine',return_value=json.dumps({'settings':{'open_kakariko':'closed'}})):
            self.assertEqual(opening.prepare_opening_rewards(Path('missing-game'),Path('missing-mod'),roster,dict(settings,_seed_settings='closed-fixture')),{'checks':[],'changed':False})
        # Released schema1 required generated_item too; malformed metadata has
        # never been a valid old player file and is not guessed from actors.
        schema1=copy.deepcopy(settings);schema1['network_sources_schema']=1
        self.assertEqual(len(opening.opening_records(roster,schema1)),2)
        del schema1['network_sources'][opening.LOCATIONS[0]]['generated_item']
        with self.assertRaises(ValueError):opening.opening_records(roster,schema1)
        settings['network_sources'][opening.LOCATIONS[0]]['generated_item']='Unsupported invented item'
        with self.assertRaises(ValueError):opening.opening_records(roster,settings)

    def test_changed_native_grants_are_rejected_and_owned_subflows_are_registered(self):
        raw = native_opening()
        ed = FlowEditor(raw,'changed')
        event = next(e for e in ed.chart.events if opening._params(e).get('Actor')=='Item_ZeldaLetter')
        event.data.params.data['Num']=2;ed.expected[event.name]=dict(event.data.params.data)
        changed=ed.write('changed')[0]
        with self.assertRaises(ValueError):opening.build_opening_flow(changed,pouch(),records())
        after=build(raw,records((None,'Progressive Hookshot')))
        chart=FlowEditor(after['GetPouchContent'],'after').chart
        for point in chart.entry_points:
            used={chart.events.index(e) for e in reachable(point.main_event.v) if isinstance(e.data,SubFlowEvent)}
            self.assertTrue(used<=set(point._sub_flow_event_indices),point.name)
        self.assertEqual(opening.build_opening_flow(after[opening.FLOW],pouch(),records()),after[opening.FLOW])

    def test_older_save_receives_real_sources_once_without_replaying_opening(self):
        after=build(native_opening(),records((None,'Progressive Hookshot')))
        result=run(after,old_save=True,inventory={'Item_ZeldaLetter':1,'Obj_Heart_Piece':1})
        self.assertEqual(result.inventory['Item_ZeldaLetter'],1)
        self.assertEqual(result.inventory['Obj_Heart_Piece'],1)
        self.assertEqual(result.inventory['Item_Hookshot'],1)
        repeated=run(after,old_save=True,inventory=dict(result.inventory),values=result.values)
        self.assertEqual(repeated.inventory,result.inventory)

    def test_consumed_trade_and_missing_ammo_finish_without_resurrection(self):
        from ootrr_triforce.catalog import TRADE_CHECKS
        trade=next(r for r in TRADE_CHECKS.values() if r['required_actor']==ITEM_DATA['Odd Potion']['actor'])
        after=build(native_opening(),records(('Odd Potion','Bombs (5)')),trade_mode=True)
        result=run(after,old_save=True,values={trade['flag_name']:True})
        self.assertFalse(any(result.inventory.values()))
        self.assertTrue(all(result.values[flag_name(name)] for name in opening.LOCATIONS))

    def test_no_bottle_capacity_keeps_native_no_grant_and_finishes_tracking(self):
        ed=FlowEditor(pouch(),'native full bottle')
        point=next(p for p in ed.chart.entry_points if p.name=='GetPouchContent')
        capacity=ed.switch('NativeBottleCapacity','GameDataActor','EventQueryIsGameDataBool',
                           {'GameDataName':'Fixture.BottleCanBeAdded','Index':-1},point.main_event.v,None)
        point.main_event=make_index(capacity)
        quiet=opening.build_reconciliation_flow(ed.write('native full bottle')[0],records((None,'Bottle')))
        result=HeartRun({'GetPouchContent':quiet})
        result.values['Fixture.BottleCanBeAdded']=False
        result.call('GetPouchContent',opening.ENTRY);result.flush()
        self.assertFalse(any(result.inventory.values()))
        self.assertTrue(all(result.values[flag_name(name)] for name in opening.LOCATIONS))

    def test_ready_gate_without_any_local_shop_saves_once_and_replays_cleanly(self):
        quiet=opening.build_reconciliation_flow(pouch(),records((None,'Heart Container')))
        complete,changed=tracking.build_tracking_flow(quiet,[],opening_entry=opening.ENTRY)
        self.assertTrue(changed)
        self.assertEqual(tracking.build_tracking_flow(complete,[],opening_entry=opening.ENTRY),(complete,False))
        class Run(HeartRun):
            def call(self,flow,entry,arguments=None):
                if entry!=tracking.ENTRY:return super().call(flow,entry,arguments)
                node=self.entries[flow][entry]
                while node is not None:
                    data=node.data
                    if isinstance(data,SwitchEvent):
                        params=data.params.data
                        value=self.values.get(params['GameDataName'],0)
                        if data.actor_query.v.v==tracking.INT_QUERY:
                            case=0 if value<params['Value'] else 1 if value==params['Value'] else 2
                        else:case=0 if value else 1
                        node=data.cases[case].v
                    else:
                        following=data.nxt
                        data.nxt=make_index(None)
                        self.entries[flow]['FixtureOneStep']=node
                        try:super().call(flow,'FixtureOneStep',arguments)
                        finally:data.nxt=following
                        node=following.v
                return self
        result=Run({'GetPouchContent':complete},commits=[flag_name(n) for n in opening.LOCATIONS])
        result.call('GetPouchContent',tracking.ENTRY)
        result.flush()
        self.assertEqual(result.max_life,20)
        self.assertEqual(len(result.saved),1)
        self.assertEqual(result.values[tracking.RESULT],1)
        self.assertTrue(all(result.saved[0][2][flag_name(n)] for n in opening.LOCATIONS))
        grants=result.grants;cures=result.cures;save_count=len(result.saved)
        result.call('GetPouchContent',tracking.ENTRY)
        self.assertEqual((result.grants,result.cures,len(result.saved)),(grants,cures,save_count))

    def test_resource_wrapper_registers_and_seals_zero_shop_startup_idempotently(self):
        from ootrr_triforce.network_catalog import murmur3
        from oot_rando.formats import byml_codec as by
        from oot_rando.patching import chest_flags
        from test_shop_tracking import game_data,document,native_flow as native_tracking
        from test_receipt_registration import IdentityCodec
        selected=records()
        # Native query ABI plus quiet inventory routes in one synthetic chart.
        ed=FlowEditor(native_tracking(),'native tracker')
        native=FlowEditor(pouch(),'native pouch')
        from ootrr_triforce.native_presentations import copy_entry
        copied=copy_entry(native.chart,ed,'GetPouchContent','FixturePouch')
        target=next(p for p in ed.chart.entry_points if p.name==copied)
        target.name='GetPouchContent'
        gd=by.load(game_data([]))
        gd['root']['Data']['Bool']=[dict(Hash=by.U32(murmur3(name)),DefaultValue=False,SaveFileIndex=0,ResetTypeValue=8)
                                  for name in [*(r['flag_name'] for r in selected),*('IsGet.'+ITEM_DATA[item]['actor'] for item in opening.VANILLA)]]
        source={"Pack/ZsDic.pack.zs":b'dict',opening.PATH:native_opening(),opening.POUCH:ed.write('combined native')[0],
                tracking.GAME_DATA:by.dump(gd),opening.REST:b'sizes',
                chest_flags.EVENT_SETTINGS:document([dict(__RowId='Dm_SY_Get',EntryPointName='Dm_SY_Get',FixtureNative=True),dict(__RowId='Opening',EntryPointName='Opening_Introduction',FlowchartFileName='Work/Event/EventFlow/OpeningEvent.evfc')]),
                chest_flags.ANALYZED:document([dict(__RowId='Dm_SY_Get',SubFlowList=['KeepNative']),dict(__RowId='Opening',SubFlowList=['KeepOriginal'])])}
        settings={'_seed_settings':'fixture'}
        with tempfile.TemporaryDirectory() as tmp:
            romfs=Path(tmp)/'game';mod=Path(tmp)/'mods/Archipelago/romfs';mod.mkdir(parents=True)
            for path,raw in source.items():
                p=romfs/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
            with patch('ootrr_triforce.mod_codec.Codec',IdentityCodec),patch.object(tracking,'Codec',IdentityCodec), \
                    patch.object(opening,'opening_records',return_value=selected), \
                    patch('ootrr_triforce.engine.run_engine',return_value=json.dumps({'settings':{'open_kakariko':'open'}})), \
                    patch('ootrr_triforce.ap_shops.shop_records',return_value=[]), \
                    patch('oot_rando.game.resource_allocations.grow_resources',side_effect=lambda raw,sizes:(raw,len(sizes))):
                self.assertTrue(opening.prepare_opening_rewards(romfs,mod,{},settings)['changed'])
                self.assertTrue(tracking.prepare_shop_tracking(romfs,mod,{},settings)['changed'])
                snapshot={p.relative_to(mod):p.read_bytes() for p in mod.rglob('*') if p.is_file()}
                self.assertFalse(opening.prepare_opening_rewards(romfs,mod,{},settings)['changed'])
                self.assertFalse(tracking.prepare_shop_tracking(romfs,mod,{},settings)['changed'])
                self.assertEqual(snapshot,{p.relative_to(mod):p.read_bytes() for p in mod.rglob('*') if p.is_file()})
                broken=FlowEditor((mod/opening.POUCH).read_bytes(),'broken startup')
                node=next(e for e in broken.chart.events if e.name.endswith('_Dirty') and e.name.startswith(opening.PREFIX))
                node.data.params.data['Value']=0;broken.expected[node.name]=dict(node.data.params.data)
                (mod/opening.POUCH).write_bytes(broken.write('broken startup')[0])
                before={p:p.read_bytes() for p in mod.rglob('*') if p.is_file()}
                with self.assertRaises(ValueError):tracking.prepare_shop_tracking(romfs,mod,{},settings)
                self.assertEqual(before,{p:p.read_bytes() for p in mod.rglob('*') if p.is_file()})


if __name__=='__main__':unittest.main()
