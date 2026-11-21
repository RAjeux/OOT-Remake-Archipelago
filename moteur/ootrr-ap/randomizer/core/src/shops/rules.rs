use std::collections::{BTreeSet as BS, HashMap as HM};

use crate::error::{Error as E, Res};
use crate::slice::generate::allowed;
use crate::logic_items::ItemId;
use crate::shops::data::{is_loc, table, Table};
use crate::shops::layout::Room;
use crate::shops::plan::Opts;
use crate::slice::data::Data;
use crate::slice::fill::vanilla_place;
use crate::slice::logic::world_with;
use crate::slice::pick::{pick, Pick};
use crate::slice::support::{Plan, Songs};
use crate::world::{LocId, Placement, World};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Class {
    Unique,
    Stack,
    Upgrade,
    Heart,
    Song,
}

impl Class {
    pub fn once_only(self) -> bool {
        matches!(self, Class::Stack | Class::Heart)
    }

    pub fn on(self, o: &Opts, songs: bool) -> bool {
        match self {
            Class::Unique => true,
            Class::Stack => o.kinds.stacks,
            Class::Upgrade => o.kinds.upgrades,
            Class::Heart => o.kinds.hearts,
            Class::Song => o.kinds.songs && songs,
        }
    }
}

pub fn class(d: &Data, item: &str) -> Option<Class> {
    let t: &Table = table().ok()?;
    if t.deal_items.iter().any(|i| i == item) {
        return Some(Class::Unique);
    }
    if t.stack.iter().any(|(i, _)| i == item) {
        return Some(Class::Stack);
    }
    if t.hearts.iter().any(|i| i == item) {
        return Some(Class::Heart);
    }
    if d.family(item).is_some_and(|f| t.upgrades.iter().any(|u| u == f)) {
        return Some(Class::Upgrade);
    }
    let i = d.item(item)?;
    (i.kind == "Song" && i.actor.as_deref().is_some_and(crate::slice::generate::is_song)).then_some(Class::Song)
}

pub fn shelf_ok(d: &Data, item: &str) -> bool {
    class(d, item).is_some()
}

pub fn at(d: &Data, o: &Opts, songs: bool, name: &str, item: &str) -> Option<bool> {
    if !o.on() || !is_loc(name) {
        return None;
    }
    if !o.deals() {
        return Some(false);
    }
    let t: &Table = table().ok()?;
    let once: bool = t.slot(name).and_then(|s| t.shop(&s.shop)).is_some_and(|s| s.once);
    // A shop with one keeper closes a slot after one purchase, so it can sell anything once.
    // The others sell a deal again and again, so only items that cannot be held twice.
    Some(class(d, item).is_some_and(|c| c.on(o, songs) && (once || !c.once_only())))
}

pub fn room(d: &Data, p: &Plan) -> Res<Room> {
    if !p.shops.deals() {
        return Ok(Room::default());
    }
    let songs: bool = p.songs == Songs::Anywhere;
    let w: World = world_with(d, &p.logic())?;
    let pk: Pick = pick(d, &w, p);
    let v: Placement = vanilla_place(&w, d)?;
    let mut any: usize = 0;
    let mut once: usize = 0;
    // Only one copy of each upgrade family counts. A shelf sells the tier the reach order
    // forces (slice::tier_order), so a second copy on a shelf fits only when the first one is
    // always found before that shop. Counting every copy opened deals that only duplicate
    // upgrades could fill, and no fill then kept the tiers in order.
    let mut fams: BS<&str> = BS::new();
    for i in pk.free.iter().filter_map(|l| v.get(*l)) {
        let name: &str = &w.items.names[i];
        match class(d, name).filter(|c| c.on(&p.shops, songs)) {
            Some(Class::Upgrade) if !d.family(name).is_some_and(|f| fams.insert(f)) => {}
            Some(c) if c.once_only() => once += 1,
            Some(_) => any += 1,
            None => {}
        }
    }
    let dear: bool = p.shops.max > crate::shops::price::CHILD;
    let left: usize = margin(d, &w, p, &pk.free, &v)?.saturating_sub(SLACK);
    let any: usize = spare(any, dear).min(left);
    let once: usize = if p.shops.kinds.stacks { spare(once, dear) } else { spare(once, dear).min(left - any) };
    Ok(Room { any, once })
}

pub fn margin(d: &Data, w: &World, p: &Plan, free: &[LocId], v: &Placement) -> Res<usize> {
    let junk: ItemId = w.item(JUNK).ok_or(E::Format("the logic has no Rupees (20)"))?;
    let open: Vec<LocId> = free.iter().copied().filter(|l| !is_loc(&w.locs[*l].name)).collect();
    let picky: Vec<LocId> = open.iter().copied().filter(|l| !allowed(d, w, p, junk, *l)).collect();
    let spots: usize = open.len() - picky.len();
    let stuck: usize = open.iter().filter_map(|l| v.get(*l)).filter(|i| !picky.iter().any(|l| allowed(d, w, p, *i, *l))).count();
    Ok(spots.saturating_sub(stuck))
}

pub fn spare(n: usize, dear: bool) -> usize {
    let keep: usize = if dear { n / 2 } else { n / 3 };
    n.saturating_sub(SLACK.max(keep))
}

pub const SLACK: usize = 3;
pub const JUNK: &str = "Rupees (20)";

pub fn cut_note(cut: usize, room: Room) -> Option<String> {
    (cut > 0).then(|| format!("{cut} special deals stay shop goods. Only {} deals fit this seed, so that a few of the items that can stand on a shelf stay free for other spots.", room.any + room.once))
}
pub fn caps(w: &World, free: &[LocId], vanilla: &Placement, ok: &dyn Fn(ItemId, LocId) -> bool) -> HM<LocId, usize> {
    let mut out: HM<LocId, usize> = HM::new();
    if !free.iter().any(|l| is_loc(&w.locs[*l].name)) {
        return out;
    }
    let pool: Vec<ItemId> = free.iter().filter_map(|l| vanilla.get(*l)).collect();
    for l in free {
        let n: usize = if is_loc(&w.locs[*l].name) { pool.iter().filter(|i| ok(**i, *l)).count() } else { usize::MAX };
        out.insert(*l, n);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::shops::plan::{Kinds, Level, Prices};

    #[test]
    fn deals_leave_some_shelf_items_free() {
        assert_eq!(spare(15, false), 10);
        assert_eq!(spare(15, true), 8);
        assert_eq!(spare(6, false), 3);
        assert_eq!(spare(2, true), 0);
        assert!(cut_note(0, Room::any(5)).is_none());
        assert!(cut_note(2, Room::any(10)).unwrap().starts_with("2 special deals"));
    }

    #[test]
    fn deal_slots_take_the_classes_that_are_on() {
        let d: Data = Data::load().unwrap();
        let off: Opts = Opts::default();
        let on: Opts = Opts { level: Level::Deals(2), prices: Prices::Weighted, min: 10, max: 200, kinds: Kinds::default() };
        let all: Opts = Opts { kinds: Kinds { stacks: true, upgrades: true, hearts: true, songs: true }, ..on };
        let plain: Opts = Opts { level: Level::Shuffle, ..on };
        assert_eq!(at(&d, &off, true, "KF Shop Item 1", "Boomerang"), None);
        assert_eq!(at(&d, &on, true, "KF Midos Top Left Chest", "Boomerang"), None);
        assert_eq!(at(&d, &on, true, "KF Shop Item 1", "Boomerang"), Some(true));
        assert_eq!(at(&d, &plain, true, "KF Shop Item 1", "Boomerang"), Some(false));
        for bad in ["Progressive Hookshot", "Bow", "Piece of Heart", "Bombchus (10)", "Rupees (20)", "Small Key (Forest Temple)", "Minuet of Forest", "Bottle", "Kokiri Emerald", "Buy Heart", "Bombs (10)"] {
            assert_eq!(at(&d, &on, true, "GC Shop Item 5", bad), Some(false), "{bad}");
        }
        assert_eq!(at(&d, &all, true, "GC Shop Item 5", "Progressive Hookshot"), Some(true));
        assert_eq!(at(&d, &all, true, "GC Shop Item 5", "Minuet of Forest"), Some(true));
        assert_eq!(at(&d, &all, false, "GC Shop Item 5", "Minuet of Forest"), Some(false));
        assert_eq!(at(&d, &all, true, "GC Shop Item 5", "Bombs (10)"), Some(false));
        assert_eq!(at(&d, &all, true, "Market Bazaar Item 1", "Bombs (10)"), Some(true));
        assert_eq!(at(&d, &all, true, "Market Bazaar Item 1", "Piece of Heart"), Some(true));
        assert_eq!(at(&d, &all, true, "Market Bazaar Item 1", "Boomerang"), Some(true), "a one keeper shop sells anything once");
        assert_eq!(at(&d, &all, true, "Market Bazaar Item 1", "Progressive Hookshot"), Some(true));
        assert_eq!(at(&d, &on, true, "Market Bazaar Item 1", "Boomerang"), Some(true));
        assert_eq!(at(&d, &all, true, "KF Shop Item 1", "Piece of Heart"), Some(false));
        for bad in ["Bow", "Slingshot", "Bomb Bag", "Magic Meter", "Bombchus (10)", "Small Key (Forest Temple)", "Kokiri Emerald", "Bottle", "Bottle with Fish", "Rupees (20)"] {
            assert_eq!(at(&d, &all, true, "Market Bazaar Item 1", bad), Some(false), "{bad}");
        }
        assert_eq!(class(&d, "Progressive Wallet"), Some(Class::Upgrade));
        assert_eq!(class(&d, "Recovery Heart"), Some(Class::Stack));
        for g in ["Bow", "Slingshot", "Bomb Bag", "Magic Meter"] {
            assert_eq!(class(&d, g), None, "{g}");
            assert_eq!(at(&d, &all, true, "GC Shop Item 5", g), Some(false), "{g}");
        }
        assert_eq!(class(&d, "Progressive Strength Upgrade"), Some(Class::Upgrade));
        assert_eq!(at(&d, &all, true, "GC Shop Item 5", "Progressive Strength Upgrade"), Some(true));
        for bad in ["Small Key (Forest Temple)", "Boss Key (Forest Temple)", "Map (Forest Temple)", "Compass (Forest Temple)", "Progressive Hookshot", "Bottle"] {
            assert_eq!(at(&d, &on, true, "GC Shop Item 5", bad), Some(false), "{bad}");
        }
    }
}