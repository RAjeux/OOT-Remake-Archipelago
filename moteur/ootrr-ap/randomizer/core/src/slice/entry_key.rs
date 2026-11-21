use crate::error::{Error as E, Res};
use crate::logic_items::ItemId;
use crate::slice::support::{Keep, Plan};
use crate::world::{LocId, Placement, World};

pub const CHEST: &str = "Forest Temple First Room Chest";
pub const KEY: &str = "Small Key (Forest Temple)";
pub const NOTE: &str = "The Forest Temple First Room Chest holds a Forest Temple small key, because it is the only chest before the locked front door.";

pub fn forced(w: &World, p: &Plan, free: &[LocId], base: &Placement, plan: &[(LocId, ItemId)], ok: &dyn Fn(ItemId, LocId) -> bool) -> Res<Vec<(LocId, ItemId)>> {
    if p.keys.small != Keep::Dungeon {
        return Ok(Vec::new());
    }
    let (Some(l), Some(k)) = (w.loc(CHEST), w.item(KEY)) else {
        return Ok(Vec::new());
    };
    if !free.contains(&l) || plan.iter().any(|x| x.0 == l) {
        return Ok(Vec::new());
    }
    if p.excluded.iter().any(|x| x == CHEST) {
        return Err(E::Msg(format!("{CHEST} cannot be excluded while small keys stay in their own dungeon, it is the only chest before the locked front door of the Forest Temple and must hold a Forest Temple small key")));
    }
    let held: usize = plan.iter().filter(|x| x.1 == k).count();
    let have: usize = free.iter().filter(|x| base.get(**x) == Some(k)).count();
    if have <= held || !ok(k, l) {
        return Ok(Vec::new());
    }
    Ok(vec![(l, k)])
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::settings::{Settings, Value};
    use crate::slice::data::Data;
    use crate::slice::fill::vanilla_place;
    use crate::slice::generate::{generate_data, GenOpts, Generated};
    use crate::slice::logic::world_with;
    use crate::slice::support::plan;

    fn with(mode: &str) -> Settings {
        let mut s: Settings = Settings::default();
        s.set("shuffle_smallkeys", Value::s(mode)).unwrap();
        s
    }

    fn keys_in(d: &Data, s: &Settings, g: &Generated) -> usize {
        let w: World = world_with(d, &plan(s).unwrap().logic()).unwrap();
        let v: Placement = vanilla_place(&w, d).unwrap();
        let k: ItemId = w.item(KEY).unwrap();
        let kept: usize = w.real.iter().filter(|l| v.get(**l) == Some(k) && !g.seed_file.placements.contains_key(&w.locs[**l].name)).count();
        kept + g.seed_file.placements.values().filter(|x| x.as_str() == KEY).count()
    }

    #[test]
    fn own_dungeon_keys_always_put_a_forest_key_in_the_first_room_chest() {
        let d: Data = Data::load().unwrap();
        let s: Settings = Settings::default();
        assert_eq!(plan(&s).unwrap().keys.small, Keep::Dungeon);
        for n in 0..6 {
            let g: Generated = generate_data(&d, &s, &format!("entry {n}"), &GenOpts::default()).unwrap();
            assert_eq!(g.seed_file.placements.get(CHEST).map(|x| x.as_str()), Some(KEY), "entry {n}");
            assert_eq!(keys_in(&d, &s, &g), 5, "entry {n}");
            assert!(g.report.contains(NOTE), "entry {n}");
            for (l, i) in &g.seed_file.placements {
                if i.starts_with("Boss Key (Forest") || i.starts_with("Map (Forest") || i.starts_with("Compass (Forest") {
                    assert!(l.starts_with("Forest Temple") && l != CHEST, "{i} at {l}");
                }
            }
        }
    }

    #[test]
    fn roaming_keys_are_not_forced_and_still_count_five() {
        let d: Data = Data::load().unwrap();
        for mode in ["any_dungeon", "keysanity"] {
            let s: Settings = with(mode);
            let mut moved: usize = 0;
            for n in 0..3 {
                let g: Generated = generate_data(&d, &s, &format!("roam {n}"), &GenOpts::default()).unwrap();
                assert!(!g.report.contains(NOTE), "{mode} {n}");
                assert_eq!(keys_in(&d, &s, &g), 5, "{mode} {n}");
                if g.seed_file.placements.get(CHEST).map(|x| x.as_str()) != Some(KEY) {
                    moved += 1;
                }
            }
            assert!(moved > 0, "{mode}");
        }
    }

    #[test]
    fn a_fixed_chest_or_a_refused_key_is_left_alone_and_vanilla_keys_need_nothing() {
        let d: Data = Data::load().unwrap();
        let s: Settings = Settings::default();
        let p: Plan = plan(&s).unwrap();
        let w: World = world_with(&d, &p.logic()).unwrap();
        let base: Placement = vanilla_place(&w, &d).unwrap();
        let free: Vec<LocId> = w.real.clone();
        let l: LocId = w.loc(CHEST).unwrap();
        let k: ItemId = w.item(KEY).unwrap();
        let yes = |_: ItemId, _: LocId| true;
        let no = |_: ItemId, _: LocId| false;
        assert_eq!(forced(&w, &p, &free, &base, &[], &yes).unwrap(), vec![(l, k)]);
        assert!(forced(&w, &p, &free, &base, &[(l, k)], &yes).unwrap().is_empty());
        assert!(forced(&w, &p, &free, &base, &[], &no).unwrap().is_empty());
        assert!(forced(&w, &p, &[], &base, &[], &yes).unwrap().is_empty());
        let mut x: Plan = p.clone();
        x.excluded = vec![CHEST.to_string()];
        assert!(forced(&w, &x, &free, &base, &[], &yes).err().unwrap().to_string().contains("cannot be excluded"));
        let v: Settings = with("vanilla");
        let g: Generated = generate_data(&d, &v, "entry vanilla", &GenOpts::default()).unwrap();
        assert!(!g.report.contains(NOTE));
        assert!(!g.seed_file.placements.contains_key(CHEST));
    }
}
