use crate::byml::{Byml, Node};
use crate::error::{Error as E, Res};
use crate::pickup_pack::rows::{self, need, pouch_row, POUCH_INFO};

pub const ITEMS: [&str; 7] = ["Item_GlassTruth", "Item_DinFire", "Item_FaroreWind", "Item_NayruLove", "Item_Arrow_Fire", "Item_Arrow_Ice", "Item_Arrow_Light"];
pub const ALIASES: [&str; 2] = ["Armor_GlassTruth", "Obj_Arrow_Fire"];
pub const METER: &str = "FairyBless_MP";
pub const KIND: &str = "ExpansionAvility";
pub const AMOUNT: &str = "MPMax";
pub const RAISE: &str = "MPMaxUP";

pub fn applies(who: &str) -> bool {
    ITEMS.contains(&who) || ALIASES.contains(&who)
}

pub fn keeps(id: &str) -> bool {
    id.contains(METER)
}

pub fn raises(r: &Node) -> bool {
    r.get(KIND).and_then(|v| v.as_str()) == Some(RAISE)
}

pub fn loses(r: &Node) -> bool {
    raises(r) && !rows::id(r).is_some_and(keeps)
}

pub fn strip(r: &mut Node) -> bool {
    if !raises(r) {
        return false;
    }
    r.remove(KIND);
    r.remove(AMOUNT);
    true
}

pub fn strip_all(y: &mut Byml) -> Res<usize> {
    let list: &mut Vec<Node> = y.root.as_arr_mut().ok_or(E::Format("actor table: the root is not a row list"))?;
    let mut n: usize = 0;
    for r in list.iter_mut().filter(|r| loses(r)) {
        strip(r);
        n += 1;
    }
    Ok(n)
}

pub fn apply(y: &mut Byml, name: &str, identity: &str) -> Res<usize> {
    for who in [name, identity] {
        need(y, who, POUCH_INFO)?;
    }
    strip_all(y)
}

pub fn audit(was: &Byml, now: &Byml, name: &str, identity: &str) -> Res<String> {
    let after: &[Node] = now.root.as_arr().ok_or(E::Format("actor table: the root is not a row list"))?;
    if let Some(r) = after.iter().find(|r| loses(r) || (r.get(AMOUNT).is_some() && !rows::id(r).is_some_and(keeps))) {
        return Err(E::Msg(format!("audit: {} still carries a magic raise", rows::id(r).unwrap_or(""))));
    }
    let before: &[Node] = was.root.as_arr().ok_or(E::Format("actor table: the root is not a row list"))?;
    let mut cut: usize = 0;
    for old in before.iter().filter(|r| rows::id(r) != Some(name)) {
        let id: &str = rows::id(old).ok_or(E::Format("actor table: a row has no id"))?;
        let mut want: Node = old.clone();
        cut += usize::from(loses(&want) && strip(&mut want));
        if need(now, id, POUCH_INFO)? != &want {
            return Err(E::Msg(format!("audit: the row of {id} changed in more than the magic raise")));
        }
    }
    let mut parent: Node = need(was, identity, POUCH_INFO)?.clone();
    if loses(&parent) {
        strip(&mut parent);
    }
    if need(now, name, POUCH_INFO)? != &pouch_row(&parent, name) {
        return Err(E::Msg(format!("audit: the row of {name} is not the row of {identity} without its magic raise")));
    }
    let kept: usize = after.iter().filter(|r| raises(r)).count();
    Ok(format!("magic raise: {cut} rows lost {KIND} and {AMOUNT} in {POUCH_INFO}, {kept} meter rows kept theirs, {name} and {identity} carry none, no other column changed"))
}

pub fn left(y: &Byml) -> Vec<String> {
    y.root.as_arr().unwrap_or(&[]).iter().filter(|r| raises(r)).filter_map(|r| rows::id(r).map(|s| s.to_string())).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::pickup_pack::rows::tests::{row, table};
    use crate::pickup_pack::rows::{find, insert};

    fn s(x: &str) -> Node {
        Node::Str(x.to_string())
    }

    fn up(id: &str, n: i32) -> Node {
        row(id, &[(KIND, s(RAISE)), (AMOUNT, Node::I32(n)), ("PouchCategory", s("Material"))])
    }

    fn sample() -> Byml {
        let mut y: Byml = table(vec![
            up("Armor_GlassTruth", 24),
            up("Item_DinFire", 24),
            up("Item_FairyBless_MP", 24),
            up("Item_FairyBless_MPDouble", 48),
            row("Item_Hookshot", &[("PouchCategory", s("Material"))]),
            up("Pouch_DinFire", 24),
            up("Pouch_FairyBless_MP", 24),
            up("Pouch_Range_BowAndArrow_Normal", 24),
        ]);
        let new: Node = pouch_row(find(&y, "Item_DinFire").unwrap(), "Obj_DinFire");
        insert(&mut y, new).unwrap();
        y
    }

    #[test]
    fn the_seven_magic_items_lose_the_raise_and_the_meter_items_do_not() {
        for item in ["Item_GlassTruth", "Item_DinFire", "Item_FaroreWind", "Item_NayruLove", "Item_Arrow_Fire", "Item_Arrow_Ice", "Item_Arrow_Light", "Armor_GlassTruth", "Obj_Arrow_Fire"] {
            assert!(applies(item), "{item}");
        }
        for keep in ["Item_FairyBless_MP", "Item_FairyBless_MPDouble", "Obj_FairyBless_MP", "Item_Hookshot", "Weapon_Range_Bow", "Item_FairyBless_DefenseDouble"] {
            assert!(!applies(keep), "{keep}");
        }
        for id in ["Item_FairyBless_MP", "Item_FairyBless_MPDouble", "Pouch_FairyBless_MP", "Pouch_FairyBless_MPDouble", "Obj_FairyBless_MP_GS"] {
            assert!(keeps(id), "{id}");
        }
        assert!(!keeps("Item_FairyBless_DefenseDouble") && !keeps("Pouch_DinFire"));
    }

    #[test]
    fn every_row_but_the_meter_rows_loses_the_raise_and_nothing_else() {
        let was: Byml = sample();
        let mut y: Byml = was.clone();
        assert_eq!(apply(&mut y, "Obj_DinFire", "Item_DinFire").unwrap(), 5);
        for who in ["Obj_DinFire", "Item_DinFire", "Armor_GlassTruth", "Pouch_DinFire", "Pouch_Range_BowAndArrow_Normal"] {
            let r: &Node = find(&y, who).unwrap();
            assert_eq!(r.get(KIND), None, "{who}");
            assert_eq!(r.get(AMOUNT), None, "{who}");
            assert_eq!(r.get("PouchCategory"), Some(&s("Material")), "{who}");
        }
        for who in ["Item_FairyBless_MP", "Item_FairyBless_MPDouble", "Pouch_FairyBless_MP"] {
            assert_eq!(find(&y, who), find(&was, who), "{who}");
            assert!(raises(find(&y, who).unwrap()), "{who}");
        }
        assert_eq!(find(&y, "Item_Hookshot"), find(&was, "Item_Hookshot"));
        assert_eq!(left(&y), vec!["Item_FairyBless_MP", "Item_FairyBless_MPDouble", "Pouch_FairyBless_MP"]);
        assert!(audit(&was, &y, "Obj_DinFire", "Item_DinFire").unwrap().contains("no other column changed"));
        assert!(audit(&was, &was, "Obj_DinFire", "Item_DinFire").is_err());
        assert_eq!(apply(&mut y, "Obj_DinFire", "Item_DinFire").unwrap(), 0);
        assert!(audit(&y, &y, "Obj_DinFire", "Item_DinFire").is_ok());
    }

    #[test]
    fn the_audit_refuses_a_row_changed_in_another_column() {
        let was: Byml = sample();
        let mut y: Byml = was.clone();
        apply(&mut y, "Obj_DinFire", "Item_DinFire").unwrap();
        let mut bad: Byml = y.clone();
        let r: &mut Node = bad.root.as_arr_mut().unwrap().iter_mut().find(|r| rows::id(r) == Some("Item_Hookshot")).unwrap();
        r.set("PouchCategory", s("Bow"));
        assert!(audit(&was, &bad, "Obj_DinFire", "Item_DinFire").unwrap_err().to_string().contains("changed in more than the magic raise"));
        let mut kept: Byml = y.clone();
        let r: &mut Node = kept.root.as_arr_mut().unwrap().iter_mut().find(|r| rows::id(r) == Some("Item_FairyBless_MP")).unwrap();
        strip(r);
        assert!(audit(&was, &kept, "Obj_DinFire", "Item_DinFire").is_err());
    }

    #[test]
    fn a_missing_row_is_refused() {
        let mut y: Byml = sample();
        assert!(apply(&mut y, "Obj_Gone", "Item_DinFire").is_err());
        assert!(apply(&mut y, "Obj_DinFire", "Item_Gone").is_err());
    }
}
