//! The newer consumable message defaults, without changing old seed settings.

use crate::byml::{Byml, Node};
use crate::error::{Error, Res};
use crate::start_defaults;
use crate::start_items::Set;
use crate::start_items::table::{Bag, NUTS, STICKS};

pub const EXTRA: [&str; 5] = ["Item_DekuSeed", "Item_Bomb", "Item_Bombchu", "Item_DekuNut", "Item_DekuStick"];

fn has_tier(y: &Byml, bag: &Bag) -> bool {
    let rows = y.root.get("Data").and_then(|d| d.get("Bool")).and_then(Node::as_arr).unwrap_or(&[]);
    bag.tiers.iter().any(|tier| {
        let hash = start_defaults::key(&format!("IsGet.{tier}"));
        rows.iter().any(|row| row.get("Hash") == Some(&Node::U32(hash))
            && row.get("DefaultValue") == Some(&Node::Bool(true)))
    })
}

pub fn edits(y: &Byml) -> Vec<Set> {
    let mut changes: Vec<Set> = EXTRA.iter().map(|actor|
        Set::Bool(format!("HavePlayedGetEvent.{actor}"), true)).collect();
    for bag in [NUTS, STICKS] {
        if has_tier(y, &bag) { continue; }
        let tier = bag.tiers[0];
        changes.extend([
            Set::Bool(format!("IsGet.{tier}"), true),
            Set::Int(format!("PouchData.{tier}.StockNum"), 1),
            Set::Int(bag.max.to_string(), bag.caps[0]),
            Set::Str(format!("CurrentExpansionActor_{}", bag.kind), tier.to_string()),
        ]);
    }
    changes
}

pub fn patch(raw: &[u8]) -> Res<Vec<u8>> {
    let mut y = Byml::parse(raw)?;
    let changes = edits(&y);
    // The small nut/stick bags are ordinary native capacities, not Bomb Bags.
    // No ammunition is granted, and received bombs still use AP's bag gate.
    if changes.iter().any(|e| matches!(e, Set::Bool(n, _) if n.contains("BombBag"))) {
        return Err(Error::Format("first pickup defaults must not grant a bomb bag"));
    }
    crate::start_items::stage::apply(&mut y, &changes)?;
    y.write()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn messages_and_empty_bags_never_grant_bombs_or_downgrade_a_starting_bag() {
        let medium = format!("IsGet.{}", NUTS.tiers[1]);
        let y = Byml { version: 7, big: false, root: Node::Map(vec![("Data".to_string(),
            Node::Map(vec![("Bool".to_string(), Node::Arr(vec![Node::Map(vec![
                ("Hash".to_string(), Node::U32(start_defaults::key(&medium))),
                ("DefaultValue".to_string(), Node::Bool(true))])]))]))]) };
        let changes = edits(&y);
        assert!(!changes.iter().any(|e| matches!(e, Set::Bool(n, _) if n == "IsGet.Item_NutBag_Small")));
        assert!(changes.iter().any(|e| matches!(e, Set::Bool(n, true) if n == "IsGet.Item_StickBag_Small")));
        assert!(!changes.iter().any(|e| matches!(e, Set::Int(n, _) if n.contains("Item_DekuNut") || n.contains("Item_DekuStick") || n.contains("Item_Bomb"))));
    }

    #[test]
    fn native_defaults_accept_the_extra_flags_and_bag_capacities() {
        let Some(root) = std::env::var_os("OOTRR_ROMFS").map(std::path::PathBuf::from) else { return };
        let mut rf = crate::romfs::Romfs::open(&root).unwrap();
        let raw = rf.read_zs(crate::chest_slot::LIST).unwrap();
        let out = patch(&raw).unwrap();
        let y = Byml::parse(&out).unwrap();
        assert!(has_tier(&y, &NUTS) && has_tier(&y, &STICKS));
        assert_eq!(patch(&out).unwrap(), out);
    }
}
