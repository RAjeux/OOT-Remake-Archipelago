import json,re
from pathlib import Path
root=Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0,str(root/'client'))
from ootrr_triforce.catalog import CHESTS, GEAR, LOCATION_IDS, ITEM_IDS, FILLER, ITEM_DATA, EXPECTED, SHOP_ITEMS, SHOP_CHECKS, CHECK_FLAGS, SKULL_CHECKS, TRADE_CHECKS
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
assert list(SHOP_CHECKS)==sorted(kokiri) and len(SHOP_CHECKS)==8, "Kokiri locations differ from the engine."
location_order=[*sorted(all_locs),*sorted(kokiri),*SKULL_CHECKS,*TRADE_CHECKS]
assert LOCATION_IDS=={n:0x6F7200+i for i,n in enumerate(location_order)}, "Location IDs changed."
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
assert rewards==ITEM_DATA, "Native rewards or quantities differ from OOTRR data."
order=[*native_order,*sorted(SHOP_ITEMS)]
assert ITEM_IDS=={n:0x6F7100+i for i,n in enumerate(order)}, "Item IDs changed."
for name,item in rewards.items():
 expected={item['actor'],*item.get('tiers',()),*item.get('world',())}
 assert expected<=set(EXPECTED[name]), f"Incomplete chest actors: {name}"
for name,row in kokiri.items():
 ref=SHOP_CHECKS[name]
 assert all(ref[key]==row[key] for key in ('shop','slot','actor','item','price','counters','target')), f"Incorrect Kokiri slot: {name}"
 assert ref['flag_name']=='Archipelago.Shop.KF.'+str(row['slot']) and ref['flag']==murmur3(ref['flag_name']), f"Incorrect Kokiri flag: {name}"
assert CHECK_FLAGS=={**{name:[ref['flag'] for ref in refs] for name,refs in CHESTS.items()},
                     **{name:[row['flag']] for name,row in SHOP_CHECKS.items()},
                     **{name:[row['flag']] for name,row in SKULL_CHECKS.items()},
                     **{name:[row['flag']] for name,row in TRADE_CHECKS.items()}}, "Incomplete check flags."
for family in (SKULL_CHECKS, TRADE_CHECKS):
 for name,row in family.items():
  assert row['flag']==murmur3(row['flag_name']), f"Incorrect saved check flag: {name}"
  if family is TRADE_CHECKS:
   assert row['id']==LOCATION_IDS[name], f"Incorrect adult trade ID: {name}"
print(f"{len(all_locs)} chests, {len(kokiri)} Kokiri purchases, {len(SKULL_CHECKS)} reserved Skulltulas and {len(TRADE_CHECKS)} adult trades; {len(ITEM_IDS)} items. Frozen IDs and all check flags match.")
