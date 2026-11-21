use std::collections::BTreeMap as BM;

use ootrr_core::items::model::{Item, Mode, Table};
use crate::tracker::npc_flags;
use crate::tracker::rules::{Rule, rule_of};
use crate::tracker::targets::{How, Target};

pub const PREFIX: &str = "HavePlayedGetEvent.";

pub fn rule_for(t: &Target, item: &str, copies: usize, tbl: &Table) -> Rule {
    let mut o: Target = t.clone();
    let it: Option<&Item> = tbl.get(item).filter(|i| i.mode != Mode::Shop);
    let acts: Vec<&str> = it.map(|i| i.own_actors()).unwrap_or_default();
    if acts.is_empty() {
        o.how = How::None;
        o.flags = Vec::new();
        o.weak = false;
    } else {
        o.how = How::Flag;
        o.flags = acts.iter().map(|a| format!("{PREFIX}{a}")).collect();
        o.weak = it.is_some_and(|i| i.mode != Mode::Actor) || copies > 1;
    }
    rule_of(&o)
}

pub fn own_rule(t: &Target, flags: &[&str]) -> Rule {
    let mut o: Target = t.clone();
    o.how = How::Flag;
    o.flags = flags.iter().map(|f| f.to_string()).collect();
    o.weak = false;
    rule_of(&o)
}

pub fn cow_rule(t: &Target, item: &str) -> Option<Rule> {
    let flag: String = ootrr_core::flow_extra::cows::flag_of(t.ootr.as_deref()?).filter(|_| item != ootrr_core::flow_extra::cows::VANILLA)?;
    let mut o: Target = t.clone();
    o.how = How::Flag;
    o.flags = vec![flag];
    o.weak = false;
    Some(rule_of(&o))
}

pub fn rules(ts: &[Target], placed: &BM<String, String>, tbl: &Table) -> Vec<Option<Rule>> {
    ts.iter()
        .map(|t| {
            let name: &str = t.ootr.as_deref()?;
            let item: &String = placed.get(name)?;
            match t.kind.as_str() {
                "gift" | "cow" if ootrr_core::flow_extra::cows::is(name) => cow_rule(t, item),
                "gift" | "heart_container" if npc_flags::of(name).is_some() => Some(own_rule(t, npc_flags::of(name).unwrap_or(&[]))),
                "gift" => {
                    let n: usize = placed.values().filter(|v| *v == item).count();
                    Some(rule_for(t, item, n, tbl))
                }
                _ => None,
            }
        })
        .collect()
}

pub fn rewired(over: &[Option<Rule>]) -> usize {
    over.iter().filter(|r| r.is_some()).count()
}

#[cfg(test)]
mod tests {
    use super::*;
    use ootrr_core::items::load;
    use ootrr_core::murmur::murmur3_32;
    use crate::tracker::peek::{Lim, Peek, peek_with};
    use crate::tracker::rules::{Hit, eval};
    use crate::tracker::targets::all;
    use ootrr_core::save::fixture::{Cell, raw};

    fn gift(ootr: &str) -> &'static Target {
        all().unwrap().iter().find(|t| t.kind == "gift" && t.ootr.as_deref() == Some(ootr)).unwrap()
    }

    fn peek(flag: &str) -> Peek {
        let cells: Vec<(u32, Cell)> = vec![(murmur3_32(flag.as_bytes(), 0), Cell::Inline(1))];
        peek_with(&raw(&cells, &[]), &Lim::ANY).unwrap()
    }

    fn placed(rows: &[(&str, &str)]) -> BM<String, String> {
        rows.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect()
    }

    fn hit(ootr: &str, p: &BM<String, String>, flag: &str) -> Hit {
        let tbl: Table = load::load().unwrap();
        let ts: &[Target] = all().unwrap();
        let o: Vec<Option<Rule>> = rules(ts, p, &tbl);
        let i: usize = ts.iter().position(|t| t.kind == "gift" && t.ootr.as_deref() == Some(ootr)).unwrap();
        eval(o[i].as_ref().unwrap(), &peek(flag))
    }

    #[test]
    fn a_gift_is_seen_by_the_song_it_gave() {
        let p: BM<String, String> = placed(&[("ZD King Zora Thawed", "Minuet of Forest"), ("Deku Theater Skull Mask", "Zeldas Lullaby")]);
        assert_eq!(hit("ZD King Zora Thawed", &p, "HavePlayedGetEvent.Item_Melody_ForestMinuet"), Hit::On);
        assert_eq!(hit("Deku Theater Skull Mask", &p, "HavePlayedGetEvent.Item_Melody_ForestMinuet"), Hit::Off);
        assert_eq!(hit("Deku Theater Skull Mask", &p, "HavePlayedGetEvent.Item_Melody_ZeldaLullaby"), Hit::On);
    }

    #[test]
    fn a_medallion_at_a_skulltula_reward_is_exact() {
        let p: BM<String, String> = placed(&[("ToT Light Arrows Cutscene", "Water Medallion")]);
        assert_eq!(hit("ToT Light Arrows Cutscene", &p, "HavePlayedGetEvent.Item_Medal_Water"), Hit::On);
        assert_eq!(hit("ToT Light Arrows Cutscene", &p, "HavePlayedGetEvent.Item_Wallet_Medium"), Hit::Off);
    }

    #[test]
    fn an_npc_with_its_own_flag_is_exact_whatever_it_holds() {
        let p: BM<String, String> = placed(&[("Kak 10 Gold Skulltula Reward", "Piece of Heart"), ("Market 5 Big Poes", "Piece of Heart")]);
        assert_eq!(hit("Kak 10 Gold Skulltula Reward", &p, "KakarikoVillage_GatheringTokenGold_GetReward10"), Hit::On);
        assert_eq!(hit("Kak 10 Gold Skulltula Reward", &p, "HavePlayedGetEvent.Obj_Heart_Piece"), Hit::Off);
        assert_eq!(hit("Market 5 Big Poes", &p, "HavePlayedGetEvent.Obj_Heart_Piece"), Hit::Weak);
    }

    #[test]
    fn an_npc_seen_only_by_an_enum_step_needs_that_exact_value() {
        let p: BM<String, String> = placed(&[("Kak 100 Gold Skulltula Reward", "Piece of Heart")]);
        let tbl: Table = load::load().unwrap();
        let ts: &[Target] = all().unwrap();
        let o: Vec<Option<Rule>> = rules(ts, &p, &tbl);
        let i: usize = ts.iter().position(|t| t.kind == "gift" && t.ootr.as_deref() == Some("Kak 100 Gold Skulltula Reward")).unwrap();
        let at = |v: &str| {
            let cells: Vec<(u32, Cell)> = vec![(murmur3_32(b"Step_GatheringTokenGold", 0), Cell::Inline(murmur3_32(v.as_bytes(), 0)))];
            eval(o[i].as_ref().unwrap(), &peek_with(&raw(&cells, &[]), &Lim::ANY).unwrap())
        };
        assert_eq!(at("Complete"), Hit::On);
        assert_eq!(at("Ready"), Hit::Off);
    }

    #[test]
    fn a_boss_heart_is_seen_by_the_boss_kill_whatever_it_holds() {
        let p: BM<String, String> = placed(&[("Deku Tree Queen Gohma Heart", "Gold Skulltula Token")]);
        let tbl: Table = load::load().unwrap();
        let ts: &[Target] = all().unwrap();
        let o: Vec<Option<Rule>> = rules(ts, &p, &tbl);
        let i: usize = ts.iter().position(|t| t.kind == "heart_container" && t.ootr.as_deref() == Some("Deku Tree Queen Gohma Heart")).unwrap();
        assert_eq!(eval(o[i].as_ref().unwrap(), &peek("DefeatedEnemyNum.Enemy_DungeonBoss_Gohma")), Hit::On);
        assert_eq!(eval(o[i].as_ref().unwrap(), &peek("DefeatedEnemyNum.Enemy_DungeonBoss_Barinade")), Hit::Off);
    }

    #[test]
    fn shared_items_are_only_a_weak_sign() {
        let p: BM<String, String> = placed(&[("Market 5 Big Poes", "Piece of Heart"), ("ToT Light Arrows Cutscene", "Piece of Heart")]);
        assert_eq!(hit("Market 5 Big Poes", &p, "HavePlayedGetEvent.Obj_Heart_Piece"), Hit::Weak);
        let w: BM<String, String> = placed(&[("ToT Light Arrows Cutscene", "Progressive Wallet")]);
        assert_eq!(hit("ToT Light Arrows Cutscene", &w, "HavePlayedGetEvent.Item_Wallet_Large"), Hit::Weak);
    }

    #[test]
    fn rows_a_seed_does_not_place_keep_the_vanilla_rule() {
        let ts: &[Target] = all().unwrap();
        let o: Vec<Option<Rule>> = rules(ts, &placed(&[("Song from Impa", "Minuet of Forest")]), &load::load().unwrap());
        assert_eq!(rewired(&o), 1);
        assert!(gift("Song from Saria").how == How::Flag);
    }

    #[test]
    fn every_cow_row_names_its_location() {
        let ts: &[Target] = all().unwrap();
        for n in ootrr_core::flow_extra::cows::LOCS.iter().chain(ootrr_core::flow_extra::cows::OTHER.iter()) {
            assert_eq!(ts.iter().filter(|t| t.kind == "cow" && t.ootr.as_deref() == Some(*n)).count(), 1, "{n}");
        }
        assert!(ts.iter().filter(|t| t.kind == "cow").all(|t| t.ootr.is_some()));
    }

    #[test]
    fn a_shuffled_cow_is_seen_by_its_once_flag_and_a_milk_cow_keeps_the_old_rule() {
        let ts: &[Target] = all().unwrap();
        let tbl: Table = load::load().unwrap();
        let ix = |n: &str| ts.iter().position(|t| t.kind == "cow" && t.ootr.as_deref() == Some(n)).unwrap();
        let (home, gv, other): (usize, usize, usize) = (ix("KF Links House Cow"), ix("GV Cow"), ix("Kak Impas House Cow"));
        let o: Vec<Option<Rule>> = rules(ts, &placed(&[("KF Links House Cow", "Hookshot"), ("GV Cow", "Milk"), ("Kak Impas House Cow", "Hookshot")]), &tbl);
        let flag: String = ootrr_core::flow_extra::cows::flag_of("KF Links House Cow").unwrap();
        assert_eq!(eval(o[home].as_ref().unwrap(), &peek(&flag)), Hit::On);
        assert_eq!(eval(o[home].as_ref().unwrap(), &peek("HavePlayedEvent.Animal_Cow_LinkHouse_GiveMilk")), Hit::Off);
        assert!(o[gv].is_none());
        let kak: String = ootrr_core::flow_extra::cows::flag_of("Kak Impas House Cow").unwrap();
        assert_eq!(eval(o[other].as_ref().unwrap(), &peek(&kak)), Hit::On);
        assert_eq!(eval(o[other].as_ref().unwrap(), &peek("HavePlayedEvent.Animal_Cow_GiveMilk")), Hit::Off);
        let gift_home: usize = ts.iter().position(|t| t.kind == "gift" && t.ootr.as_deref() == Some("KF Links House Cow")).unwrap();
        assert_eq!(eval(o[gift_home].as_ref().unwrap(), &peek(&flag)), Hit::On);
        assert_eq!(rewired(&o), 3);
        assert_eq!(rewired(&rules(ts, &placed(&[]), &tbl)), 0);
    }

    #[test]
    fn an_item_with_no_actor_cannot_be_seen() {
        let p: BM<String, String> = placed(&[("Song from Impa", "Ice Trap")]);
        let tbl: Table = load::load().unwrap();
        let r: Rule = rule_for(gift("Song from Impa"), "Ice Trap", 1, &tbl);
        assert_eq!(r.how, How::None);
        assert_eq!(eval(&r, &peek("HavePlayedGetEvent.Item_Melody_ForestMinuet")), Hit::Unknown);
        assert!(p.len() == 1);
    }
}
