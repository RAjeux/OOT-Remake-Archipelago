use std::collections::HashMap as HM;

use crate::error::Res;
use crate::json::{self, Json};
use crate::settings::seed::SeedFile;
use crate::settings::Settings;
use crate::slice::data::Data;
use crate::slice::fill::vanilla_place;
use crate::slice::logic::world_with;
use crate::slice::pickups;
use crate::slice::support::{plan, Plan};
use crate::spots::depth::{self, spheres};
use crate::world::{LocId, Placement, World};

const SOURCES: [&str; 5] = [
    include_str!("../../../../data/locations.json"),
    crate::pot_slice::data::CATALOG_JSON,
    crate::pot_slice::rocks::CATALOG_JSON,
    crate::pot_slice::remake::CATALOG_JSON,
    crate::spots::free::CATALOG_JSON,
];

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Row {
    pub name: String,
    pub kind: String,
    pub item: String,
    pub region: String,
    pub dungeon: bool,
    pub rule: String,
    pub sphere: u32,
    pub share: usize,
    pub grade: String,
    pub basis: String,
    pub fresh: bool,
}

impl Row {
    pub fn risk(&self) -> (bool, bool, bool, u32, std::cmp::Reverse<usize>) {
        (self.fresh, self.grade == "guess", self.dungeon, self.sphere, std::cmp::Reverse(self.share))
    }
}

fn evidence() -> Res<HM<String, (String, String)>> {
    let mut out: HM<String, (String, String)> = HM::new();
    for t in SOURCES {
        let j: Json = json::parse(t)?;
        for r in j.get("locations").and_then(|v| v.as_arr()).unwrap_or(&[]) {
            let Some(n) = r.get("name").and_then(|v| v.as_str()) else {
                continue;
            };
            let s = |k: &str| r.get(k).and_then(|v| v.as_str()).unwrap_or("").to_string();
            let grade: String = if s("grade").is_empty() { s("conf") } else { s("grade") };
            let ev: Vec<String> = r.get("ev").and_then(|v| v.as_arr()).unwrap_or(&[]).iter().filter_map(|v| v.as_str().map(|x| x.to_string())).collect();
            let basis: String = if s("basis").is_empty() { ev.join(" ") } else { s("basis") };
            out.insert(n.to_string(), (grade, basis));
        }
    }
    Ok(out)
}

pub fn is_spot(d: &Data, name: &str) -> bool {
    d.pots.has(name) || d.cat.by_name(name).is_some_and(pickups::is_world)
}

fn kind_of(d: &Data, name: &str) -> String {
    d.pots.get(name).or_else(|| d.cat.by_name(name)).map(|l| l.kind.clone()).unwrap_or_default()
}

fn fresh(d: &Data, name: &str) -> bool {
    d.pots.is_remake(name) || crate::spots::free::is(d, name) || d.pots.kind_of(name).is_some_and(|k| k.wild())
}

pub fn rows(d: &Data, seed: &SeedFile, all: bool) -> Res<(Vec<Row>, usize)> {
    let s: Settings = seed.settings()?.settings;
    let p: Plan = plan(&s)?;
    let w: World = world_with(d, &p.logic())?;
    let mut pl: Placement = vanilla_place(&w, d)?;
    let mut missing: usize = 0;
    for (loc, item) in &seed.placements {
        match (w.loc(loc), w.item(item)) {
            (Some(l), Some(i)) => pl.put(l, i),
            _ => missing += 1,
        }
    }
    let sp: Vec<[u32; 2]> = spheres(&w, &pl);
    let ev: HM<String, (String, String)> = evidence()?;
    let mut per: HM<usize, usize> = HM::new();
    for l in &w.real {
        if is_spot(d, &w.locs[*l].name) {
            *per.entry(w.locs[*l].region).or_insert(0) += 1;
        }
    }
    let mut out: Vec<Row> = Vec::new();
    for (loc, item) in &seed.placements {
        let Some(l) = w.loc(loc) else {
            continue;
        };
        if !is_spot(d, loc) || !(all || d.item(item).is_some_and(|i| i.adv)) {
            continue;
        }
        let r: usize = w.locs[l].region;
        let age: &str = d.pots.get(loc).or_else(|| d.cat.by_name(loc)).map(|x| x.age.as_str()).unwrap_or("both");
        let (grade, basis): (String, String) = ev.get(loc).cloned().unwrap_or_default();
        out.push(Row {
            name: loc.clone(),
            kind: kind_of(d, loc),
            item: item.clone(),
            region: w.regions[r].name.clone(),
            dungeon: w.regions[r].dungeon.is_some(),
            rule: rule_text(&w, l),
            sphere: depth::of(&sp, r, age),
            share: per.get(&r).copied().unwrap_or(1).saturating_sub(1),
            grade,
            basis,
            fresh: fresh(d, loc),
        });
    }
    out.sort_by(|a, b| b.risk().cmp(&a.risk()).then_with(|| a.name.cmp(&b.name)));
    Ok((out, missing))
}

fn rule_text(w: &World, l: LocId) -> String {
    let r = &w.locs[l].rule;
    if r.always {
        "True".to_string()
    } else {
        format!("{:?}", r.node)
    }
}

pub fn render(rows: &[Row], missing: usize) -> String {
    let mut out: String = String::from("spot\tkind\titem\tregion\tsphere\tshare\tgrade\tnew\tbasis\n");
    for r in rows {
        out.push_str(&format!(
            "{}\t{}\t{}\t{}{}\t{}\t{}\t{}\t{}\t{}\n",
            r.name,
            r.kind,
            r.item,
            r.region,
            if r.dungeon { " (dungeon)" } else { "" },
            depth::show(r.sphere),
            r.share,
            r.grade,
            if r.fresh { "yes" } else { "no" },
            r.basis
        ));
    }
    let fresh: usize = rows.iter().filter(|r| r.fresh).count();
    out.push_str(&format!("{} spots listed, {} of them catalogued by region only (new), {} placements not in the logic world\n", rows.len(), fresh, missing));
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::settings::Value;
    use crate::slice::generate::{generate_data, GenOpts, Generated};

    #[test]
    fn a_seed_with_remake_spots_lists_its_key_items_riskiest_first() {
        let d: Data = Data::load().unwrap();
        let mut s: Settings = Settings::default();
        for (k, v) in [("shuffle_crates", "all"), ("shuffle_pots", "all"), (pickups::SETTING, "all")] {
            s.set(k, Value::s(v)).unwrap();
        }
        let g: Generated = generate_data(&d, &s, "spot audit", &GenOpts::default()).unwrap();
        let (all, missing): (Vec<Row>, usize) = rows(&d, &g.seed_file, true).unwrap();
        assert_eq!(missing, 0);
        assert!(all.iter().any(|r| r.fresh));
        assert!(all.iter().all(|r| r.sphere != depth::NEVER), "{:?}", all.iter().find(|r| r.sphere == depth::NEVER));
        let keys: Vec<Row> = rows(&d, &g.seed_file, false).unwrap().0;
        assert!(keys.iter().all(|r| d.item(&r.item).is_some_and(|i| i.adv)));
        assert!(keys.windows(2).all(|p| p[0].risk() >= p[1].risk()));
        let t: String = render(&all, missing);
        assert!(t.starts_with("spot\tkind\t") && t.lines().count() == all.len() + 2);
    }
}
