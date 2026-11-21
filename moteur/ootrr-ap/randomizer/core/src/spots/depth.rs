use crate::rules::Age;
use crate::search::Search;
use crate::world::{LocId, Placement, RegionId, World};

pub const NEVER: u32 = u32::MAX;

pub fn spheres(w: &World, place: &Placement) -> Vec<[u32; 2]> {
    let mut out: Vec<[u32; 2]> = vec![[NEVER; 2]; w.regions.len()];
    let mut s: Search = Search::new(w);
    let mut n: u32 = 0;
    loop {
        let found: Vec<LocId> = s.settle(place, false);
        for (r, o) in out.iter_mut().enumerate() {
            for (a, age) in Age::BOTH.iter().enumerate() {
                if o[a] == NEVER && s.region_reached(r, Some(*age)) {
                    o[a] = n;
                }
            }
        }
        if found.is_empty() {
            break;
        }
        for l in found {
            if let Some(i) = place.get(l) {
                s.add(i, 1);
            }
        }
        n += 1;
    }
    out
}

pub fn of(sp: &[[u32; 2]], r: RegionId, age: &str) -> u32 {
    match age {
        "child" => sp[r][Age::Child.idx()],
        "adult" => sp[r][Age::Adult.idx()],
        _ => sp[r][0].min(sp[r][1]),
    }
}

pub fn show(n: u32) -> String {
    if n == NEVER { "never".to_string() } else { n.to_string() }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::slice::data::Data;
    use crate::slice::fill::vanilla_place;
    use crate::slice::logic::world;

    #[test]
    fn the_root_is_sphere_zero_and_late_regions_are_deeper() {
        let d: Data = Data::load().unwrap();
        let w: World = world(&d).unwrap();
        let v: Placement = vanilla_place(&w, &d).unwrap();
        let sp: Vec<[u32; 2]> = spheres(&w, &v);
        assert_eq!(of(&sp, w.root, "both"), 0);
        let r = |n: &str| w.regions.iter().position(|x| x.name == n).unwrap();
        let kf: u32 = of(&sp, r("Kokiri Forest"), "child");
        let boss: u32 = of(&sp, r("Ganons Castle Tower"), "adult");
        assert!(kf < boss && boss != NEVER, "{kf} {boss}");
        assert!(of(&sp, r("Water Temple Lobby"), "adult") > of(&sp, r("Lake Hylia"), "adult"));
        assert_eq!(show(NEVER), "never");
    }
}
