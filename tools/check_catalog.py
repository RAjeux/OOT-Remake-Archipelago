import json,re
from pathlib import Path
root=Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0,str(root/'client'))
from ootrr_triforce.catalog import CHESTS, GEAR, LOCATION_IDS, ITEM_IDS, FILLER, ITEM_DATA, EXPECTED, SHOP_ITEMS, SHOP_CHECKS, LEGACY_SHOP_CHECKS, CHECK_FLAGS, SKULL_CHECKS, TRADE_CHECKS
from ootrr_triforce.shop_catalog import ADDITIONAL_SHOP_CHECKS, SHOP_FIRST_ID
from ootrr_triforce.master_sword import ACTOR as MASTER_ACTOR, ITEM as MASTER_ITEM, LOCATION as MASTER_LOCATION, LOCATION_ID as MASTER_ID, FLAG_NAME as MASTER_FLAG
from oot_rando.patching.soul_adapter import murmur3
data=root/'moteur/ootrr-ap/data'
load=lambda x:json.loads((data/x).read_text(encoding='utf-8'))
flags={f['name']:int(f['hash'],16) for f in load('flags.json')['flags'] if f.get('name') and f.get('save')==0 and f['type'] in {'Bool','Int','Enum'}}
raw=(root/'moteur/ootrr-ap/randomizer/core/src/start_items/table.rs').read_text(encoding='utf-8')
recipes={}
for name, actor in re.findall(r'logic: "([^"]+)", offset: 0, strip: Strip::Unique, recipe: Recipe::Grant\(&\["([^"]+)"\]\)',raw):
 if name=='Hylian Shield': continue
 names=['IsGet.'+actor,'PouchData.'+actor+'.StockNum']
 recipes[name]=[flags[n] for n in names]
for name,n in re.findall(r'\("[a-z_]+", "([^"]+)", "(IsGet.Item_Melody_[^"]+)"\)',raw):
 recipes[name]=[flags[n]]
all_locs={}
eligible={r['name'] for r in load('slice.json')['chests'] if r['state']=='eligible'}
for l in load('locations.json')['locations']:
 if l['kind']!='chest' or l['name'] not in eligible or l.get('via')!='drop':continue
 refs=[]
 for ref in l['refs']:
  n='IsTreasureBoxOpen.'+ref['hash']
  if n not in flags:break
  refs.append({'actor':ref['hash'],'flag':flags[n],'files':ref['files']})
 else:
  if refs:all_locs[l['name']]=refs
assert all_locs==CHESTS and recipes==GEAR, "The catalogue differs from OOTRR data."
shops=load('shops.json')
kokiri={row['name']:row for row in shops['slots'] if row['shop']=='KF Shop'}
assert LEGACY_SHOP_CHECKS==set(kokiri) and len(LEGACY_SHOP_CHECKS)==8, "Legacy Kokiri locations differ from the engine."
location_order=[*sorted(all_locs),*sorted(kokiri),*SKULL_CHECKS,*TRADE_CHECKS]
expected_ids={n:0x6F7200+i for i,n in enumerate(location_order)}
expected_ids.update({n:row['id'] for n,row in ADDITIONAL_SHOP_CHECKS.items()})
expected_ids[MASTER_LOCATION]=MASTER_ID
assert LOCATION_IDS==expected_ids, "Location IDs changed."
assert set(LOCATION_IDS[n] for n in ADDITIONAL_SHOP_CHECKS)==set(range(SHOP_FIRST_ID,SHOP_FIRST_ID+56)), "Global shop ID reservation changed."
assert len(set(LOCATION_IDS.values()))==len(LOCATION_IDS), "Location IDs overlap."
assert set(SHOP_CHECKS)=={row['name'] for row in shops['slots']} and len(SHOP_CHECKS)==64, "Shop locations differ from the engine."
legacy=[*sorted(recipes),FILLER]
rewards={}
for item in sorted(load('items.json')['items'],key=lambda row:row['name']):
 if not item.get('actor') or item['kind']=='Shop':continue
 row={key:item[key] for key in ('actor','mode','kind','dungeon','tiers','world') if key in item}
 row.update(quantity=item.get('qty',1),advancement=bool(item['adv']))
 rewards[item['name']]=row
rewards[FILLER]=dict(rewards['Rupees (5)'])
native_order=[*legacy,*sorted(set(rewards).difference(legacy))]
goods={row['item']:row['actor'] for row in shops['slots']}
assert set(goods)==set(SHOP_ITEMS), "Shop goods differ from OOTRR data."
for name,actor in goods.items():
 row=SHOP_ITEMS[name]
 assert row['actor']==actor and row['mode']=='shop' and row['kind']=='Shop', f"Incorrect shop goods: {name}"
 assert row['quantity']>=1, f"Incorrect shop quantity: {name}"
rewards.update(SHOP_ITEMS)
rewards[MASTER_ITEM]=dict(actor=MASTER_ACTOR,mode='actor',kind='Item',quantity=1,advancement=True)
# AP packet quantities are exact. The native bundle actor remains the display
# identity; the receipt gives this unit actor the independently specified count.
# Keep this explicit protocol contract separate from catalog.py's implementation.
for name,unit,amount in (
 ('Bombs (10)','Item_Bomb',10), ('Bombs (20)','Item_Bomb',20),
 ('Arrows (30)','Item_Arrow_Normal',30), ('Deku Seeds (30)','Item_DekuSeed',30),
 ('Deku Nuts (5)','Item_DekuNut',5), ('Deku Nuts (10)','Item_DekuNut',10),
):
 rewards[name].update(grant_actor=unit,grant_amount=amount,quantity=amount)
assert rewards==ITEM_DATA, "Native rewards or quantities differ from OOTRR data."
order=[*native_order,*sorted(SHOP_ITEMS),MASTER_ITEM]
assert ITEM_IDS=={n:0x6F7100+i for i,n in enumerate(order)}, "Item IDs changed."
for name,item in rewards.items():
 expected={item['actor'],*item.get('tiers',()),*item.get('world',())}
 assert expected<=set(EXPECTED[name]), f"Incomplete chest actors: {name}"
shop_metadata={row['shop']:row for row in shops['shops']}
for row in shops['slots']:
 name=row['name']
 ref=SHOP_CHECKS[name]
 assert all(ref[key]==row[key] for key in ('shop','slot','actor','item','price','counters','target')), f"Incorrect shop slot: {name}"
 assert all(ref[key]==shop_metadata[row['shop']][key] for key in ('keepers','files','bancs')), f"Incorrect shop placement: {name}"
 assert ref['flag']==murmur3(ref['flag_name']), f"Incorrect shop flag: {name}"
 if name in LEGACY_SHOP_CHECKS:
  assert ref['flag_name']=='Archipelago.Shop.KF.'+str(row['slot']), f"Legacy Kokiri flag changed: {name}"
assert len({row['flag'] for row in SHOP_CHECKS.values()})==64, "Shop saved flags overlap."
counters=[counter for row in SHOP_CHECKS.values() for counter in row['counters']]
assert len(counters)==len(set(counters))==96, "Shop stock identities overlap."
assert CHECK_FLAGS=={**{name:[ref['flag'] for ref in refs] for name,refs in CHESTS.items()},
                     **{name:[row['flag']] for name,row in SHOP_CHECKS.items()},
                     **{name:[row['flag']] for name,row in SKULL_CHECKS.items()},
                     **{name:[row['flag']] for name,row in TRADE_CHECKS.items()},
                     MASTER_LOCATION:[murmur3(MASTER_FLAG)]}, "Incomplete check flags."
for family in (SKULL_CHECKS, TRADE_CHECKS):
 for name,row in family.items():
  assert row['flag']==murmur3(row['flag_name']), f"Incorrect saved check flag: {name}"
  if family is TRADE_CHECKS:
   assert row['id']==LOCATION_IDS[name], f"Incorrect adult trade ID: {name}"
print(f"{len(all_locs)} chests, {len(SHOP_CHECKS)} shop slots (including {len(kokiri)} legacy Kokiri purchases), {len(SKULL_CHECKS)} reserved Skulltulas and {len(TRADE_CHECKS)} adult trades; {len(ITEM_IDS)} items. Frozen IDs and all check flags match.")
