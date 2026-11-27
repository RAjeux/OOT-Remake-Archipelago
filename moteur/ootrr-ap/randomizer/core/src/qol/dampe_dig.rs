use crate::bfevfl::{Bf, Flow, Kind, Val};
use crate::error::{Error, Res};

pub const FLOWS: [&str; 2] = ["Npc_Hylia_Dampe_001", "Npc_Hylia_Dampe_001.110"];
const NAME: &str = "Npc_Hylia_Dampe_001";
pub const DROPPED: &str = "GraveYard_DiggingHoleTour_Drop_HeartPiece";
const LOTTERY: &str = "Event219";
const RUPEE_RATE: &str = "LotteryHitSoil_RupeeRate";
const FOUND: [&str; 2] = ["Event48", "Event259"];
const DIG: &str = "Event314";
const DAMPE: &str = "Npc_Hylia_Dampe_001";
const DEMO_LOCATOR: &str = "EventQueryMiniGameDiggingHoleFindNearDemoLocator";

pub const NOTE: &str = "Dampé's gravedigging tour gives its check on the first dig at one of the three big-hit soils, with no second fee: the dig lottery (Event219) has no rupee share at a big-hit soil, so that dig always finds the Heart Piece while the check is not taken, and Dampé's find (Event48, Event259) goes straight to the Heart Piece dig (Event314), skipping the question and the second fee. Ordinary soils give rupees as before, since the Heart Piece dig needs a big-hit soil's demo locator and crashes without one. Always on.";

fn named(f: &Flow, name: &str) -> Res<usize> {
    let hits: Vec<usize> = (0..f.events.len()).filter(|&i| f.events[i].name == name).collect();
    match hits.as_slice() {
        [i] => Ok(*i),
        _ => Err(Error::Msg(format!("first dig: expected one {name} in {NAME}, found {}", hits.len()))),
    }
}

pub fn patch(b: &mut Bf) -> Res<()> {
    let f: &mut Flow = b.flows.iter_mut().find(|f| f.name == NAME).ok_or(Error::Format("first dig: the Dampé flow has no Npc_Hylia_Dampe_001 flow"))?;
    let idx = |i: usize| crate::dungeon_credit::idx(i);
    let dig_at: usize = named(f, DIG)?;
    let finds: bool = match &f.events[dig_at].kind {
        Kind::Switch { actor, query, .. } => f.actors.get(*actor as usize).is_some_and(|a| a.name == DAMPE && a.queries.get(*query as usize).is_some_and(|q| q == DEMO_LOCATOR)),
        _ => false,
    };
    if !finds {
        return Err(Error::Format("first dig: Event314 no longer finds the Heart Piece demo locator"));
    }
    let dig: u16 = idx(dig_at)?;
    for n in FOUND {
        let i: usize = named(f, n)?;
        match &mut f.events[i].kind {
            Kind::Action { next, .. } => *next = dig,
            _ => return Err(Error::Msg(format!("first dig: {n} is not an action"))),
        }
    }
    let lottery: usize = named(f, LOTTERY)?;
    let mut found: bool = false;
    if let Some(c) = f.events[lottery].kind.params_mut() {
        for (k, v) in c.items.iter_mut() {
            if k == RUPEE_RATE {
                *v = Val::Int(0);
                found = true;
            }
        }
    }
    if !found {
        return Err(Error::Format("first dig: the dig lottery has no rupee rate"));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::romfs::Romfs;

    fn flows() -> Option<Vec<Bf>> {
        let p: std::path::PathBuf = ootrr_game::test_romfs::path();
        if !p.join("Pack").join("ZsDic.pack.zs").is_file() {
            eprintln!("skipped: no romfs at {}, set OOTRR_ROMFS", p.display());
            return None;
        }
        let mut rf: Romfs = Romfs::open(&p).unwrap();
        Some(FLOWS.iter().map(|n| Bf::parse(&rf.read_zs(&format!("Event/EventFlow/{n}.bfevfl.zs")).unwrap()).unwrap()).collect())
    }

    fn into(f: &Flow, to: usize) -> Vec<String> {
        let mut out: Vec<String> = Vec::new();
        for e in &f.events {
            let hit: bool = match &e.kind {
                Kind::Action { next, .. } => *next as usize == to,
                Kind::Switch { cases, .. } => cases.iter().any(|c| c.ev as usize == to),
                _ => false,
            };
            if hit {
                out.push(e.name.clone());
            }
        }
        out.sort();
        out
    }

    #[test]
    fn only_the_finds_and_the_fees_lead_into_the_heart_piece_dig() {
        let Some(mut bs) = flows() else {
            return;
        };
        for b in bs.iter_mut() {
            let before: Vec<String> = {
                let f: &Flow = b.flows.iter().find(|f| f.name == NAME).unwrap();
                into(f, named(f, DIG).unwrap())
            };
            assert_eq!(before, ["Event100", "Event88", "Event99"]);
            let n: usize = b.flows.iter().find(|f| f.name == NAME).unwrap().events.len();
            patch(b).unwrap();
            let f: &Flow = b.flows.iter().find(|f| f.name == NAME).unwrap();
            assert_eq!(f.events.len(), n);
            assert_eq!(into(f, named(f, DIG).unwrap()), ["Event100", "Event259", "Event48", "Event88", "Event99"]);
            let lottery: &Kind = &f.events[named(f, LOTTERY).unwrap()].kind;
            assert_eq!(lottery.params().and_then(|c| c.get(RUPEE_RATE)), Some(&Val::Int(0)));
        }
    }
}
