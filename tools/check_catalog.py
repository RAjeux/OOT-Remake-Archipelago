import json,re
from pathlib import Path
root=Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0,str(root/'client'))
from ootrr_triforce.catalog import CHESTS, GEAR, LOCATION_IDS, ITEM_IDS, FILLER, ITEM_DATA, EXPECTED, SHOP_ITEMS, SHOP_CHECKS, CHECK_FLAGS
from oot_rando.patching.soul_adapter import murmur3
data=root/'moteur/ootrr-ap/data'
load=lambda x:json.loads((data/x).read_text())
flags={f['name']:int(f['hash'],16) for f in load('flags.json')['flags'] if f.get('name') and f.get('save')==0 and f['type'] in {'Bool','Int','Enum'}}
raw=(root/'moteur/ootrr-ap/randomizer/core/src/start_items/table.rs').read_text()
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
assert all_locs==CHESTS and recipes==GEAR, "Le catalogue diffère des données OOTRR."
shops=load('shops.json')
kokiri={row['name']:row for row in shops['slots'] if row['shop']=='KF Shop'}
assert list(SHOP_CHECKS)==sorted(kokiri) and len(SHOP_CHECKS)==8, "Emplacements Kokiri différents du moteur."
location_order=[*sorted(all_locs),*sorted(kokiri)]
assert LOCATION_IDS=={n:0x6F7200+i for i,n in enumerate(location_order)}, "IDs d’emplacement modifiés."
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
assert set(goods)==set(SHOP_ITEMS), "Marchandises différentes des données OOTRR."
for name,actor in goods.items():
 row=SHOP_ITEMS[name]
 assert row['actor']==actor and row['mode']=='shop' and row['kind']=='Shop', f"Marchandise incorrecte : {name}"
 assert row['quantity']>=1, f"Quantité de boutique incorrecte : {name}"
rewards.update(SHOP_ITEMS)
assert rewards==ITEM_DATA, "Récompenses natives ou quantités différentes des données OOTRR."
order=[*native_order,*sorted(SHOP_ITEMS)]
assert ITEM_IDS=={n:0x6F7100+i for i,n in enumerate(order)}, "IDs d’objet modifiés."
for name,item in rewards.items():
 expected={item['actor'],*item.get('tiers',()),*item.get('world',())}
 assert expected<=set(EXPECTED[name]), f"Acteurs de coffre incomplets : {name}"
for name,row in kokiri.items():
 ref=SHOP_CHECKS[name]
 assert all(ref[key]==row[key] for key in ('shop','slot','actor','item','price','counters','target')), f"Slot Kokiri incorrect : {name}"
 assert ref['flag_name']=='Archipelago.Shop.KF.'+str(row['slot']) and ref['flag']==murmur3(ref['flag_name']), f"Drapeau Kokiri incorrect : {name}"
assert CHECK_FLAGS=={**{name:[ref['flag'] for ref in refs] for name,refs in CHESTS.items()},
                     **{name:[row['flag']] for name,row in SHOP_CHECKS.items()}}, "Drapeaux de checks incomplets."
print(f"{len(all_locs)} coffres et {len(kokiri)} achats Kokiri, {len(ITEM_IDS)} objets ; les 128 emplacements et 168 objets antérieurs gardent leurs IDs.")
