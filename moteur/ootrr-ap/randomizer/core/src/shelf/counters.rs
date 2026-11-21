use crate::byml::{Byml, Node};
use crate::error::{Error as E, Res};
use crate::flags::hash_name;
use crate::shelf::actor::int;

pub const KEPT: i32 = 8;
pub const DAILY: i64 = 2;

fn rows(y: &Byml) -> &[Node] {
    y.root.get("Data").and_then(|d| d.get("Int")).and_then(|l| l.as_arr()).unwrap_or(&[])
}

pub fn reset_of(y: &Byml, name: &str) -> Option<i64> {
    let h: u32 = hash_name(name);
    rows(y).iter().find(|r| int(r, "Hash").map(|v| v as u32) == Some(h)).and_then(|r| int(r, "ResetTypeValue"))
}

pub fn keep(y: &mut Byml, names: &[String]) -> Res<usize> {
    let hs: Vec<u32> = names.iter().map(|n| hash_name(n)).collect();
    let list: &mut Vec<Node> = y.root.get_mut("Data").and_then(|d| d.get_mut("Int")).and_then(|l| l.as_arr_mut()).ok_or(E::Format("the game data list has no Int table"))?;
    let mut n: usize = 0;
    for r in list.iter_mut() {
        if int(r, "Hash").is_some_and(|h| hs.contains(&(h as u32))) {
            let v: Node = match r.get("ResetTypeValue") {
                Some(Node::U32(_)) => Node::U32(KEPT as u32),
                _ => Node::I32(KEPT),
            };
            if r.set("ResetTypeValue", v) {
                n += 1;
            }
        }
    }
    let mut want: Vec<u32> = hs.clone();
    want.sort_unstable();
    want.dedup();
    if n != want.len() {
        return Err(E::Msg(format!("{n} of {} shop sold counters found in the game data list", want.len())));
    }
    Ok(n)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn list(names: &[&str]) -> Byml {
        let rows: Vec<Node> = names
            .iter()
            .map(|n| Node::Map(vec![("Hash".to_string(), Node::U32(hash_name(n))), ("ResetTypeValue".to_string(), Node::I32(DAILY as i32))]))
            .collect();
        Byml { root: Node::Map(vec![("Data".to_string(), Node::Map(vec![("Int".to_string(), Node::Arr(rows))]))]), version: 7, big: false }
    }

    #[test]
    fn the_sold_counters_of_every_keeper_copy_stop_resetting_daily() {
        let a: &str = "Shop_SoldNum.Npc_Kokiri_001_Shop_Child.6";
        let b: &str = "Shop_SoldNum.Npc_Kokiri_001_Shop_Adult.6";
        let mut y: Byml = list(&[a, b, "Shop_SoldNum.Npc_Kokiri_001_Shop_Child.5"]);
        assert_eq!(keep(&mut y, &[a.to_string(), b.to_string()]).unwrap(), 2);
        assert_eq!(reset_of(&y, a), Some(KEPT as i64));
        assert_eq!(reset_of(&y, b), Some(KEPT as i64));
        assert_eq!(reset_of(&y, "Shop_SoldNum.Npc_Kokiri_001_Shop_Child.5"), Some(DAILY));
        assert!(keep(&mut y, &["Shop_SoldNum.Nobody.1".to_string()]).is_err());
        assert_eq!(hash_name("Shop_SoldNum.Npc_Goron_011_Shop_Child.3"), 0xe783dc08);
    }
}
