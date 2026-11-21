use std::collections::{BTreeMap as BM, BTreeSet as BS};

use crate::entr::data::{Cat, Door};
use crate::entr::pools::{find, Conn, DUNGEONS};
use crate::error::{Error as E, Res};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Layout {
    pub at: Vec<usize>,
}

impl Layout {
    pub fn vanilla() -> Layout {
        Layout { at: (0..DUNGEONS.len()).collect() }
    }

    pub fn moved(&self) -> usize {
        self.at.iter().enumerate().filter(|(i, d)| i != *d).count()
    }

    pub fn to_map(&self) -> BM<String, String> {
        self.at.iter().enumerate().map(|(i, d)| (DUNGEONS[i].name.to_string(), DUNGEONS[*d].name.to_string())).collect()
    }

    pub fn from_map(m: &BM<String, String>) -> Res<Layout> {
        let mut at: Vec<Option<usize>> = vec![None; DUNGEONS.len()];
        for (k, v) in m {
            let i: usize = find(k).ok_or_else(|| E::Msg(format!("seed file: {k} is not a dungeon entrance this build knows")))?;
            let d: usize = find(v).ok_or_else(|| E::Msg(format!("seed file: {v} is not a dungeon this build knows")))?;
            at[i] = Some(d);
        }
        let at: Vec<usize> = at.into_iter().enumerate().map(|(i, x)| x.unwrap_or(i)).collect();
        let l: Layout = Layout { at };
        l.check()?;
        Ok(l)
    }

    pub fn check(&self) -> Res<()> {
        let set: BS<usize> = self.at.iter().copied().collect();
        if self.at.len() != DUNGEONS.len() || set.len() != DUNGEONS.len() || set.iter().any(|d| *d >= DUNGEONS.len()) {
            return Err(E::Format("the dungeon entrance layout does not use every dungeon exactly once"));
        }
        Ok(())
    }

    pub fn spot_of(&self, d: usize) -> usize {
        self.at.iter().position(|x| *x == d).unwrap_or(d)
    }
}

pub fn door_ages(cat: &Cat, c: &Conn) -> Res<BS<String>> {
    let mut out: BS<String> = BS::new();
    for h in c.doors {
        let d: &Door = cat.door(*h)?;
        out.extend(d.ages.iter().cloned());
    }
    Ok(out)
}

pub fn inside(cat: &Cat, spot: usize, dungeon: usize) -> Res<BS<String>> {
    let mut a: BS<String> = door_ages(cat, &DUNGEONS[spot])?;
    a.extend(DUNGEONS[dungeon].extra.iter().map(|x| x.to_string()));
    Ok(a)
}

pub fn ages_fit(cat: &Cat, l: &Layout) -> Res<Vec<String>> {
    let mut bad: Vec<String> = Vec::new();
    for (spot, d) in l.at.iter().enumerate() {
        let back: &Door = cat.door(DUNGEONS[spot].back)?;
        for a in inside(cat, spot, *d)? {
            if !back.ok_for(&a) {
                bad.push(format!(
                    "{} at the {} entrance would send the {a} player to {}/{} on the way out",
                    DUNGEONS[*d].name,
                    DUNGEONS[spot].name,
                    if a == "adult" { &back.adult } else { &back.child },
                    back.start
                ));
            }
        }
    }
    Ok(bad)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::entr::data::load;

    #[test]
    fn maps_round_trip_and_reject_duplicates() {
        let mut l: Layout = Layout::vanilla();
        l.at.swap(0, 5);
        let m: BM<String, String> = l.to_map();
        assert_eq!(m["Deku Tree"], "Fire Temple");
        assert_eq!(Layout::from_map(&m).unwrap(), l);
        assert_eq!(l.moved(), 2);
        assert_eq!(l.spot_of(5), 0);
        let mut bad: BM<String, String> = m.clone();
        bad.insert("Fire Temple".to_string(), "Fire Temple".to_string());
        assert!(Layout::from_map(&bad).is_err());
        let mut odd: BM<String, String> = BM::new();
        odd.insert("Hyrule Castle".to_string(), "Deku Tree".to_string());
        assert!(Layout::from_map(&odd).is_err());
    }

    #[test]
    fn vanilla_fits_and_the_broken_returns_rule_out_some_spots() {
        let c: Cat = load().unwrap();
        assert!(ages_fit(&c, &Layout::vanilla()).unwrap().is_empty());
        let ice: usize = find("Ice Cavern").unwrap();
        let jabu: usize = find("Jabu Jabus Belly").unwrap();
        let spirit: usize = find("Spirit Temple").unwrap();
        let gtg: usize = find("Gerudo Training Ground").unwrap();
        let mut l: Layout = Layout::vanilla();
        l.at.swap(ice, jabu);
        let bad: Vec<String> = ages_fit(&c, &l).unwrap();
        assert_eq!(bad.len(), 1, "{bad:?}");
        assert!(bad[0].starts_with("Ice Cavern at the Jabu Jabus Belly entrance would send the adult player"));
        let mut g: Layout = Layout::vanilla();
        g.at.swap(spirit, gtg);
        assert!(ages_fit(&c, &g).unwrap().iter().any(|b| b.starts_with("Spirit Temple at the Gerudo Training Ground entrance would send the child")));
    }
}
