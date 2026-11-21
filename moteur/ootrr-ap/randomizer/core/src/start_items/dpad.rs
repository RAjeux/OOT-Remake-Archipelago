use std::collections::{BTreeMap as BM, BTreeSet as BS};

use crate::byml::{Byml, Node};
use crate::error::{Error as E, Res};
use crate::romfs::Romfs;
use crate::staging::Out;
use crate::start_items::give::{Kit, Set};
use crate::start_items::stage::stage_list;

pub const TABLE: &str = "RSDB/PouchActorInfo.Product.111.rstbl.byml.zs";
pub const COUNT: &str = "UI_GetAssignableItemNum";
pub const GUIDE_DONE: &str = "ActionGuide_IsEnd.ItemShortcut";
pub const GUIDE_DUE: &str = "UI_IsNeedOpenShortCutActionGuide";
const EMPTY: [&str; 3] = ["", "Empty", "None"];

pub fn actors(kits: &[&Kit], pouch: &[&str]) -> Vec<String> {
    let mut out: BS<String> = BS::new();
    for k in kits {
        for s in &k.sets {
            if let Set::Bool(n, true) = s
                && let Some(a) = n.strip_prefix("IsGet.")
            {
                out.insert(a.to_string());
            }
        }
        out.extend(k.pushes.iter().map(|a| a.to_string()));
    }
    out.extend(pouch.iter().map(|a| a.to_string()));
    out.into_iter().collect()
}

pub fn slots(y: &Byml) -> Res<BM<String, String>> {
    let rows: &[Node] = y.root.as_arr().ok_or(E::Format("start items: the pouch actor table is not a list"))?;
    let mut out: BM<String, String> = BM::new();
    for r in rows {
        let (Some(id), Some(slot)) = (r.get("__RowId").and_then(|v| v.as_str()), r.get("AssignableItem").and_then(|v| v.as_str())) else {
            continue;
        };
        if !EMPTY.contains(&slot) {
            out.insert(id.to_string(), slot.to_string());
        }
    }
    Ok(out)
}

pub fn count(table: &BM<String, String>, given: &[String]) -> usize {
    given.iter().filter_map(|a| table.get(a)).collect::<BS<&String>>().len()
}

pub fn sets(n: usize) -> Vec<Set> {
    if n == 0 {
        return Vec::new();
    }
    vec![Set::Int(COUNT.to_string(), n as i32), Set::Bool(GUIDE_DONE.to_string(), true), Set::Bool(GUIDE_DUE.to_string(), false)]
}

pub fn stage(rf: &mut Romfs, more: &mut Vec<Out>, given: &[String]) -> Res<usize> {
    if given.is_empty() {
        return Ok(0);
    }
    let y: Byml = Byml::parse(&rf.read_zs(TABLE)?)?;
    let n: usize = count(&slots(&y)?, given);
    stage_list(rf, more, &sets(n))?;
    Ok(n)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf as PB;

    fn row(id: &str, slot: Option<&str>) -> Node {
        let mut m: Vec<(String, Node)> = vec![("__RowId".to_string(), Node::Str(id.to_string()))];
        if let Some(s) = slot {
            m.push(("AssignableItem".to_string(), Node::Str(s.to_string())));
        }
        Node::Map(m)
    }

    #[test]
    fn only_assignable_actors_count_and_a_shared_slot_counts_once() {
        let y: Byml = Byml { root: Node::Arr(vec![row("Weapon_Range_Bow", Some("Bow")), row("Item_Arrow_Normal", Some("Bow")), row("Item_Bomb", Some("Bomb")), row("Animal_Fish_Blue", Some("Empty")), row("Weapon_Sword_Kokiri", None)]), version: 7, big: false };
        let t: BM<String, String> = slots(&y).unwrap();
        assert_eq!(t.len(), 3);
        let g = |v: &[&str]| v.iter().map(|s| s.to_string()).collect::<Vec<String>>();
        assert_eq!(count(&t, &g(&["Weapon_Range_Bow", "Item_Arrow_Normal", "Weapon_Sword_Kokiri"])), 1);
        assert_eq!(count(&t, &g(&["Weapon_Range_Bow", "Item_Bomb"])), 2);
        assert!(sets(0).is_empty());
        assert_eq!(sets(2), vec![Set::Int(COUNT.to_string(), 2), Set::Bool(GUIDE_DONE.to_string(), true), Set::Bool(GUIDE_DUE.to_string(), false)]);
    }

    #[test]
    fn the_given_actors_come_from_flag_grants_pushes_and_the_pouch() {
        let mut k: Kit = Kit::default();
        k.sets.push(Set::Bool("IsGet.Item_Hookshot".to_string(), true));
        k.sets.push(Set::Bool("IsGet.Item_Gone".to_string(), false));
        k.sets.push(Set::Int("PouchData.Item_Bomb.StockNum".to_string(), 20));
        k.pushes.push("Item_Wallet_Medium");
        let mut c: Kit = Kit::default();
        c.pushes.push("Item_ZeldaLetter");
        assert_eq!(actors(&[&k, &c], &["Weapon_Range_SlingShot", "Item_Hookshot"]), vec!["Item_Hookshot", "Item_Wallet_Medium", "Item_ZeldaLetter", "Weapon_Range_SlingShot"]);
        assert!(actors(&[&Kit::default()], &[]).is_empty());
    }

    fn real() -> Option<PB> {
        let p: PB = ootrr_game::test_romfs::path();
        if p.join("Pack").join("ZsDic.pack.zs").is_file() {
            Some(p)
        } else {
            eprintln!("skipped, no RomFS dump at {} (set OOTRR_ROMFS)", p.display());
            None
        }
    }

    #[test]
    fn the_real_table_knows_the_starting_kit_slots_and_the_three_flags_are_new_game_flags() {
        let Some(root) = real() else {
            return;
        };
        let mut rf: Romfs = Romfs::open(&root).unwrap();
        let t: BM<String, String> = slots(&Byml::parse(&rf.read_zs(TABLE).unwrap()).unwrap()).unwrap();
        for (a, s) in [("Weapon_Range_Bow", "Bow"), ("Item_Hookshot", "Hookshot"), ("Item_Bottle", "BottleA"), ("Item_ZeldaLetter", "ZeldaLetter"), ("Weapon_Range_SlingShot", "SlingShot"), ("Item_Bombchu", "Bombchu")] {
            assert_eq!(t.get(a).map(|x| x.as_str()), Some(s), "{a}");
        }
        for a in ["Weapon_Sword_Kokiri", "Item_HeavyBoot", "Item_Wallet_Medium", "Item_Ocarina_Fairy"] {
            assert!(!t.contains_key(a), "{a}");
        }
        let mut more: Vec<Out> = Vec::new();
        let n: usize = stage(&mut rf, &mut more, &["Item_Hookshot".to_string(), "Item_Bomb".to_string(), "Item_HeavyBoot".to_string()]).unwrap();
        assert_eq!(n, 2);
        assert_eq!(more.len(), 1);
        let l: crate::flags::FlagList = crate::flags::from_json(&crate::json::parse(include_str!("../../../../data/flags.json")).unwrap()).unwrap();
        for (name, ty) in [(COUNT, "Int"), (GUIDE_DONE, "Bool"), (GUIDE_DUE, "Bool")] {
            let f: &crate::flags::Flag = l.find(name).unwrap();
            assert_eq!(f.ty, ty, "{name}");
            assert!(crate::start_defaults::allowed(f.reset as i32, f.save as i32), "{name}");
        }
        let mut none: Vec<Out> = Vec::new();
        assert_eq!(stage(&mut rf, &mut none, &[]).unwrap(), 0);
        assert!(none.is_empty());
    }
}
