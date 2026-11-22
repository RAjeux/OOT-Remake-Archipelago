//! Generation proof for independent Archipelago adult trade checks.
//!
//! The ten tokens stay on the ten trade checks during the native proof fill.
//! Archipelago subsequently mixes them freely with every exported reward.
//! Runtime hand-ins are supplied by the room-bound AP postpass, not the legacy
//! bonus-clone builder. The external portable builder receives a derived base.

use std::collections::BTreeMap;

use crate::error::{Error, Res};
use crate::settings::{seed::SeedFile, Settings, Value};
use crate::slice::data::Data;

pub const SETTING: &str = "adult_trade_shuffle";
pub const NUM: u16 = 142;
pub const FINAL: &str = "DMT Biggoron";
pub const LOCS: [&str; 10] = crate::flow_extra::trade::LOCS;
pub const ITEMS: [&str; 10] = [
    "Pocket Cucco", "Cojiro", "Odd Mushroom", "Odd Potion", "Poachers Saw",
    "Broken Sword", "Prescription", "Eyeball Frog", "Eyedrops", "Claim Check",
];
pub const NOTE: &str = "Adult trade checks replace their vanilla quest gifts. Ten independent trade tokens, starting with an already hatched Pocket Cucco, join Archipelago. Timed spoil and trade reversion are disabled; the AP runtime handles independent hand-ins and their completion flags.";

pub fn is_location(name: &str) -> bool {
    LOCS.contains(&name)
}

pub fn is_item(name: &str) -> bool {
    ITEMS.contains(&name)
}

/// The first entry distinguishes this overlay from the legacy filler bonuses.
pub fn is_data(d: &Data) -> bool {
    d.remake.get(LOCS[0]).is_some_and(|value| value == ITEMS[0])
}

pub fn data_with(d: &Data, enabled: bool) -> Option<Data> {
    enabled.then(|| {
        let mut result = d.clone();
        for (location, item) in LOCS.iter().zip(ITEMS) {
            result.remake.insert((*location).to_string(), item.to_string());
        }
        result
    })
}

/// Reserve both directions so unrelated filler cannot consume a token's proof
/// slot. This is a proof constraint; AP's actual final fill has no such rule.
pub fn placement(name: &str, item: &str) -> Option<bool> {
    (is_location(name) || is_item(item)).then_some(is_location(name) && is_item(item))
}

pub fn validate(seed: &SeedFile) -> Res<()> {
    let mut counts: BTreeMap<&str, usize> = BTreeMap::new();
    for (location, item) in &seed.placements {
        if is_location(location) {
            if !is_item(item) {
                return Err(Error::Msg(format!("adult trade proof: {location} holds non-token {item}")));
            }
            *counts.entry(item).or_default() += 1;
        } else if is_item(item) || item == "Pocket Egg" {
            return Err(Error::Msg(format!("adult trade proof: {item} must originate at a trade AP check, not {location}")));
        }
    }
    if counts.len() != ITEMS.len() || ITEMS.iter().any(|item| counts.get(item).copied() != Some(1))
        || !LOCS.iter().all(|location| seed.placements.contains_key(*location))
        || !seed.placements.contains_key(FINAL)
    {
        return Err(Error::Format("adult trade proof must contain all ten tokens exactly once and the final Biggoron check"));
    }
    Ok(())
}

/// The old portable OOTRR binary does not know the AP full-shuffle setting or
/// independent hand-ins. Remove those placements and omit both false toggles
/// from its settings string; every other source and setting remains identical.
pub fn base_seed(seed: &SeedFile) -> Res<SeedFile> {
    let mut settings = seed.settings()?.settings;
    if !settings.flag(SETTING)? {
        return Ok(seed.clone());
    }
    validate(seed)?;
    let mut result = seed.clone();
    for location in LOCS {
        result.placements.remove(location);
    }
    settings.set(SETTING, Value::Bool(false))?;
    settings.set(crate::flow_extra::trade::SETTING, Value::Bool(false))?;
    result.settings_string = settings.encode()?;
    // Check the complete derived document, including its fresh checksum.
    SeedFile::parse(&result.to_text())?;
    Ok(result)
}

pub fn require_base(seed: &SeedFile) -> Res<()> {
    if seed.settings()?.settings.flag(SETTING)? {
        return Err(Error::Format("Full adult trade shuffle requires the room-bound AP postpass; derive its portable OOTRR base with base-seed first."));
    }
    Ok(())
}

pub fn check_settings(settings: &Settings, rewards_on: bool, legacy_bonus: bool, bad: &mut Vec<String>) -> bool {
    let enabled = settings.flag(SETTING).unwrap_or(false);
    if enabled && !rewards_on {
        bad.push("adult_trade_shuffle requires shuffle_rewards=supported".to_string());
    }
    if enabled && legacy_bonus {
        bad.push("adult_trade_shuffle replaces quest rewards; shuffle_trade_checks additive bonuses must be false".to_string());
    }
    enabled
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::search::explore;
    use crate::slice::{generate::{GenOpts, generate_data}, fill::vanilla_place, logic::world_with, support::plan};

    const OLD: &str = "OOTRR1-AMAQABABAADACAQOAEDA6AIGCAAQOEQBA4PQCBRGAEASOAIBFAAQEKIBAEVACAJTAEATIAICGUAQCNQBAE5ACBSGAEBEOAIBJAAQCSIBAFFACASMAEAU4AICKABQEAICKIAQCXIBAFPACALAAEAWCAICNUAQHCABAEAY2AIBAGTXO";

    fn settings() -> Settings {
        let mut settings = Settings::default();
        settings.set("shuffle_rewards", Value::s("supported")).unwrap();
        settings.set(SETTING, Value::Bool(true)).unwrap();
        settings
    }

    fn proof() -> SeedFile {
        let mut placements = BTreeMap::new();
        for (location, item) in LOCS.iter().zip(ITEMS) {
            placements.insert((*location).to_string(), item.to_string());
        }
        placements.insert(FINAL.to_string(), "Biggoron Sword".to_string());
        SeedFile::new("independent trades", &settings(), "oot-remake:test", placements).unwrap()
    }

    #[test]
    fn default_off_preserves_old_strings_and_legacy_bonus_meaning() {
        let old = Settings::decode(OLD).unwrap().settings;
        assert!(!old.flag(SETTING).unwrap());
        let mut previous = crate::settings::schema().clone();
        previous.settings.retain(|setting| setting.num != NUM);
        assert_eq!(old.encode().unwrap(), previous.encode(old.values()).unwrap());
        let mut legacy = Settings::default();
        legacy.set(crate::flow_extra::trade::SETTING, Value::Bool(true)).unwrap();
        let p = plan(&legacy).unwrap();
        assert!(p.rewards.trade && !p.adult_trade);
        let mut conflict = settings();
        conflict.set(crate::flow_extra::trade::SETTING, Value::Bool(true)).unwrap();
        assert!(plan(&conflict).is_err());
    }

    #[test]
    fn full_mode_changes_only_its_ten_pool_entries_and_proof_targets() {
        let d = Data::load().unwrap();
        let full = data_with(&d, true).unwrap();
        for (location, item) in LOCS.iter().zip(ITEMS) {
            assert_eq!(d.vanilla_of(location), Some("Rupees (5)"));
            assert_eq!(full.vanilla_of(location), Some(item));
            assert!(full.flow_ok(location), "{location}");
        }
        for (location, item) in &d.remake {
            if !is_location(location) {
                assert_eq!(full.remake.get(location), Some(item));
            }
        }
        assert_eq!(placement(LOCS[0], "Cojiro"), Some(true));
        assert_eq!(placement(LOCS[0], "Rupees (5)"), Some(false));
        assert_eq!(placement("Deku Tree Map Chest", "Cojiro"), Some(false));
        assert_eq!(placement("Deku Tree Map Chest", "Bow"), None);
    }

    #[test]
    fn derived_base_removes_trade_edits_and_new_setting_without_mutating_original() {
        let original = proof();
        let encoded = original.to_text();
        let base = base_seed(&original).unwrap();
        assert_eq!(original.to_text(), encoded);
        assert_eq!(base.placements.len(), original.placements.len() - 10);
        assert_eq!(base.placements[FINAL], "Biggoron Sword");
        assert_ne!(base.checksum(), original.checksum());
        assert!(!base.settings().unwrap().settings.flag(SETTING).unwrap());
        assert!(!base.settings().unwrap().settings.flag(crate::flow_extra::trade::SETTING).unwrap());
        let mut portable = crate::settings::schema().clone();
        portable.settings.retain(|setting| setting.num != NUM);
        let (_, warnings) = portable.decode(&base.settings_string).unwrap();
        assert!(warnings.is_empty(), "the old portable schema must see no unknown setting: {warnings:?}");
        assert!(require_base(&original).is_err());
        assert!(require_base(&base).is_ok());
        let mut missing = original.clone();
        missing.placements.remove(LOCS[0]);
        assert!(base_seed(&missing).is_err());
        let mut wrong = original.clone();
        wrong.placements.insert("Deku Tree Map Chest".to_string(), "Cojiro".to_string());
        assert!(base_seed(&wrong).is_err());
    }

    #[test]
    fn each_trade_check_requires_its_own_token_without_prior_chain_access() {
        let d = Data::load().unwrap();
        let p = plan(&settings()).unwrap();
        let full = data_with(&d, true).unwrap();
        let w = world_with(&full, &p.logic()).unwrap();
        // Supply all ordinary access equipment, but no trade tokens or rewards
        // in the world. Each isolated late token must open its own exchange.
        let mut equipment = Vec::new();
        for item in &d.items {
            if !is_item(&item.name) && item.name != "Pocket Egg" && item.kind != "Event" {
                if let Some(id) = w.item(&item.name) {
                    equipment.extend([id; 4]);
                }
            }
        }
        let mut empty = vanilla_place(&w, &full).unwrap();
        let filler = w.item("Rupees (5)").unwrap();
        for loc in &w.real {
            if empty.get(*loc).is_some_and(|item| is_item(&w.items.names[item]) || w.items.names[item] == "Pocket Egg") {
                empty.put(*loc, filler);
            }
        }
        let before = explore(&w, &empty, &equipment);
        assert!(before.loc_access(w.loc(LOCS[0]).unwrap()));
        for (location, item) in LOCS.into_iter().skip(1).zip(ITEMS).chain([(FINAL, ITEMS[9])]) {
            let loc = w.loc(location).unwrap();
            assert!(!before.loc_access(loc), "{location} was accessible without a token");
            let mut carrying = equipment.clone();
            carrying.push(w.item(item).unwrap());
            let after = explore(&w, &empty, &carrying);
            assert!(after.loc_access(loc), "{location} did not accept isolated {item}");
        }
        assert!(w.settings.flag("adult_trade_shuffle"));
        assert!(w.settings.flag("disable_trade_revert"));
    }

    #[test]
    fn generated_proofs_export_each_token_once_and_reach_all_eleven_checks() {
        let d = Data::load().unwrap();
        for index in 0..3 {
            let g = generate_data(&d, &settings(), &format!("adult trade proof {index}"), &GenOpts::default()).unwrap();
            validate(&g.seed_file).unwrap();
            for name in LOCS.into_iter().chain([FINAL]) {
                assert!(g.spheres.iter().flatten().any(|(location, _)| location == name), "missing access proof for {name}");
            }
            let (w, place) = crate::slice::starts::rebuild(&d, &g.seed_file).unwrap();
            assert!(explore(&w, &place, &[]).won());
            let base = base_seed(&g.seed_file).unwrap();
            assert!(base.placements.values().all(|item| !is_item(item)));
        }
    }
}
