use std::collections::BTreeMap as BM;

use crate::byml::{Byml, Node};
use crate::placement::hash_of;
use crate::shelf::actor::int;

pub const FOR_SALE: &str = "ForSale";

fn actors(y: &Byml) -> &[Node] {
    y.root.get("Actors").and_then(|l| l.as_arr()).unwrap_or(&[])
}

fn gyaml(n: &Node) -> &str {
    n.get("Gyaml").and_then(|v| v.as_str()).unwrap_or("")
}

fn slot_of(n: &Node) -> i64 {
    n.get("Dynamic").and_then(|d| int(d, "ShopItemIndex")).unwrap_or(0)
}

pub fn shelves(y: &Byml, keeper: &str, slot: usize) -> Vec<u64> {
    let list: &[Node] = actors(y);
    let by: BM<u64, &Node> = list.iter().filter_map(|n| hash_of(n).map(|h| (h, n))).collect();
    let mut out: Vec<u64> = Vec::new();
    for k in list.iter().filter(|n| gyaml(n) == keeper) {
        for l in k.get("Links").and_then(|l| l.as_arr()).unwrap_or(&[]) {
            if l.get("Name").and_then(|v| v.as_str()) != Some(FOR_SALE) {
                continue;
            }
            let Some(Node::U64(d)) = l.get("Dst") else {
                continue;
            };
            if by.get(d).is_some_and(|t| slot_of(t) == slot as i64 && gyaml(t).starts_with("Shop_")) && !out.contains(d) {
                out.push(*d);
            }
        }
    }
    out
}

pub fn on_shelf(y: &Byml, keeper: &str, slot: usize) -> Vec<String> {
    let hs: Vec<u64> = shelves(y, keeper, slot);
    actors(y).iter().filter(|n| hash_of(n).is_some_and(|h| hs.contains(&h))).map(|n| gyaml(n).to_string()).collect()
}

pub fn swap(y: &mut Byml, keeper: &str, slot: usize, to: &str) -> usize {
    let hs: Vec<u64> = shelves(y, keeper, slot);
    let mut n: usize = 0;
    if let Some(list) = y.root.get_mut("Actors").and_then(|l| l.as_arr_mut()) {
        for a in list.iter_mut() {
            if hash_of(a).is_some_and(|h| hs.contains(&h)) {
                a.set("Gyaml", Node::Str(to.to_string()));
                n += 1;
            }
        }
    }
    n
}

pub const BOARD: &str = "Shop_Board_Bundle";
pub const REFERENCE: &str = "Reference";

fn refs(n: &Node) -> Vec<u64> {
    n.get("Links")
        .and_then(|l| l.as_arr())
        .unwrap_or(&[])
        .iter()
        .filter(|l| l.get("Name").and_then(|v| v.as_str()) == Some(REFERENCE))
        .filter_map(|l| match l.get("Dst") {
            Some(Node::U64(d)) => Some(*d),
            _ => None,
        })
        .collect()
}

pub fn board_map(ys: &[Byml]) -> BM<String, String> {
    let mut out: BM<String, String> = BM::new();
    let mut odd: Vec<String> = Vec::new();
    for y in ys {
        let list: &[Node] = actors(y);
        let by: BM<u64, &Node> = list.iter().filter_map(|n| hash_of(n).map(|h| (h, n))).collect();
        for n in list.iter().filter(|n| gyaml(n).starts_with("Shop_") && !gyaml(n).starts_with("Shop_Board")) {
            for d in refs(n) {
                let Some(b) = by.get(&d).map(|t| gyaml(t)).filter(|g| g.starts_with(BOARD)) else {
                    continue;
                };
                match out.get(gyaml(n)) {
                    Some(x) if x != b => odd.push(gyaml(n).to_string()),
                    _ => {
                        out.insert(gyaml(n).to_string(), b.to_string());
                    }
                }
            }
        }
    }
    for o in odd {
        out.remove(&o);
    }
    out
}

pub fn boards(y: &mut Byml, keeper: &str, slot: usize, want: &str) -> usize {
    let hs: Vec<u64> = shelves(y, keeper, slot);
    let list: &[Node] = actors(y);
    let bs: Vec<u64> = list.iter().filter(|n| hash_of(n).is_some_and(|h| hs.contains(&h))).flat_map(refs).collect();
    let mut n: usize = 0;
    if let Some(list) = y.root.get_mut("Actors").and_then(|l| l.as_arr_mut()) {
        for a in list.iter_mut() {
            if hash_of(a).is_some_and(|h| bs.contains(&h)) && gyaml(a).starts_with(BOARD) && gyaml(a) != want {
                a.set("Gyaml", Node::Str(want.to_string()));
                n += 1;
            }
        }
    }
    n
}
#[cfg(test)]
mod tests {
    use super::*;

    fn actor(hash: u64, g: &str, slot: Option<i32>, links: &[u64]) -> Node {
        let mut m: Vec<(String, Node)> = vec![("Gyaml".to_string(), Node::Str(g.to_string())), ("Hash".to_string(), Node::U64(hash))];
        if let Some(s) = slot {
            m.push(("Dynamic".to_string(), Node::Map(vec![("ShopItemIndex".to_string(), Node::I32(s))])));
        }
        if !links.is_empty() {
            let ls: Vec<Node> = links.iter().map(|d| Node::Map(vec![("Dst".to_string(), Node::U64(*d)), ("Name".to_string(), Node::Str(FOR_SALE.into()))])).collect();
            m.push(("Links".to_string(), Node::Arr(ls)));
        }
        Node::Map(m)
    }

    fn refd(hash: u64, g: &str, slot: i32, board: u64) -> Node {
        let mut n: Node = actor(hash, g, Some(slot), &[]);
        n.set("Links", Node::Arr(vec![Node::Map(vec![("Dst".to_string(), Node::U64(board)), ("Name".to_string(), Node::Str(REFERENCE.into()))])]));
        n
    }

    #[test]
    fn only_the_shelf_actor_of_that_keeper_and_slot_changes() {
        let mut y: Byml = Byml {
            root: Node::Map(vec![(
                "Actors".to_string(),
                Node::Arr(vec![
                    actor(1, "Npc_Kokiri_001_Shop_Child", None, &[10, 11]),
                    actor(2, "Npc_Kokiri_001_Shop_Adult", None, &[20]),
                    actor(10, "Shop_Heart", Some(0), &[]),
                    actor(11, "Shop_Weapon_Shield_Deku", Some(6), &[]),
                    actor(20, "Shop_Weapon_Shield_Deku", Some(6), &[]),
                ]),
            )]),
            version: 7,
            big: false,
        };
        assert_eq!(swap(&mut y, "Npc_Kokiri_001_Shop_Child", 6, "Shop_OOTRR_Item_Boomerang_20"), 1);
        assert_eq!(on_shelf(&y, "Npc_Kokiri_001_Shop_Child", 6), vec!["Shop_OOTRR_Item_Boomerang_20"]);
        assert_eq!(on_shelf(&y, "Npc_Kokiri_001_Shop_Adult", 6), vec!["Shop_Weapon_Shield_Deku"]);
        assert_eq!(on_shelf(&y, "Npc_Kokiri_001_Shop_Child", 0), vec!["Shop_Heart"]);
        assert_eq!(swap(&mut y, "Npc_Kokiri_001_Shop_Child", 5, "X"), 0);
        let mut z: Byml = Byml { root: Node::Map(vec![("Actors".to_string(), Node::Arr(vec![actor(1, "Npc_K", None, &[10]), refd(10, "Shop_DekuNutBundle_02", 0, 30), actor(30, "Shop_Board_Bundle_10", None, &[])]))]), version: 7, big: false };
        assert_eq!(board_map(&[z.clone()]).get("Shop_DekuNutBundle_02").map(|s| s.as_str()), Some("Shop_Board_Bundle_10"));
        assert_eq!(boards(&mut z, "Npc_K", 0, "Shop_Board_Bundle_05"), 1);
        assert_eq!(board_map(&[z]).get("Shop_DekuNutBundle_02").map(|s| s.as_str()), Some("Shop_Board_Bundle_05"));
    }
}
