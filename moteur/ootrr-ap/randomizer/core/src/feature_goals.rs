//! Opt-in AP goal predicates layered on the compatible native builder output.
use std::path::Path;

use crate::ainb::Ainb;
use crate::byml::Byml;
use crate::error::{Error, Res};
use crate::json::Json;
use crate::medal_gate;
use crate::romfs::Romfs;
use crate::staging::{edit_staged, Out};
use crate::start_defaults::{self, Edit};

pub const MEDALLIONS: [&str; 6] = [
    "IsGet.Item_Medal_Light", "IsGet.Item_Medal_Forest", "IsGet.Item_Medal_Fire",
    "IsGet.Item_Medal_Water", "IsGet.Item_Medal_Spirit", "IsGet.Item_Medal_Shadow",
];

fn selected<'a>(features: &'a Json, key: &str) -> Option<&'a Json> {
    features.get("settings").and_then(|s| s.get(key))
}

fn mode(features: &Json, key: &str, value: &str) -> bool {
    selected(features, key).and_then(Json::as_str) == Some(value)
}

fn count(features: &Json, key: &str) -> Res<usize> {
    let n = selected(features, key).and_then(Json::as_i64).unwrap_or(6);
    if !(0..=6).contains(&n) { return Err(Error::Msg(format!("{key} must be from 0 to 6"))); }
    Ok(n as usize)
}

pub fn terms(count: usize, played: &str) -> Vec<(i32, String)> {
    let mut values = medal_gate::at_least(&MEDALLIONS, count).unwrap_or_default();
    let counted = !values.is_empty();
    values.push((0, played.to_string()));
    values.push((5, String::new()));
    if counted { values.push((3, String::new())); }
    values
}

pub fn edits(features: &Json) -> Res<Vec<Edit>> {
    if features.get("schema").and_then(Json::as_i64) != Some(1) { return Ok(Vec::new()); }
    let mut out = Vec::new();
    let flags = if mode(features, "nocturne_trigger", "classic") {
        ["IsGet.Item_Medal_Forest", "IsGet.Item_Medal_Fire", "IsGet.Item_Medal_Water"]
    } else {
        ["SageOfForest_IsCompleted_Exp", "SageOfFire_IsCompleted_Exp", "SageOfWater_IsCompleted_Exp"]
    };
    out.push(Edit::Exp(medal_gate::KAKARIKO_EXP.to_string(), medal_gate::at_least(&flags, 3).unwrap_or_default()));
    if mode(features, "prelude_trigger", "classic") {
        out.push(Edit::Exp(medal_gate::PRELUDE_EXP.to_string(), vec![(0, "IsGet.Item_Medal_Forest".to_string())]));
    }
    if mode(features, "bridge", "medallions") {
        out.push(Edit::Exp(crate::rainbow_bridge::BRIDGE_EXP.to_string(),
            terms(count(features, "bridge_medallions")?, crate::rainbow_bridge::PLAYED)));
    }
    if mode(features, "shuffle_ganon_bosskey", "lacs_medallions") {
        out.push(Edit::Exp(medal_gate::LACS_EXP.to_string(),
            terms(count(features, "lacs_medallions")?, medal_gate::LACS_PLAYED)));
    }
    Ok(out)
}

pub fn stage(rf: &mut Romfs, more: &mut Vec<Out>, work: &Path, features: &Json) -> Res<()> {
    let changes = edits(features)?;
    if !changes.is_empty() {
        edit_staged(rf, more, work, crate::chest_slot::LIST, true, |raw| {
            let mut table = Byml::parse(raw)?;
            start_defaults::apply(&mut table, &changes)?;
            table.write()
        })?;
    }
    if features.get("schema").and_then(Json::as_i64) == Some(1) {
        let target = if mode(features, "prelude_trigger", "classic") { medal_gate::PRELUDE_EXP } else { medal_gate::FOREST_EXP };
        edit_staged(rf, more, work, medal_gate::PRELUDE_MODULE, false, |raw| {
            let mut module = Ainb::parse(raw)?;
            let hits: Vec<_> = module.find_els("HoldGameDataGetBoolExpSimple").into_iter()
                .filter(|&id| matches!(module.in_str(id, "GameDataNameBoolExp"),
                    Some(medal_gate::PRELUDE_EXP) | Some(medal_gate::FOREST_EXP))).collect();
            let [id] = hits.as_slice() else { return Err(Error::Format("Prelude: ambiguous native access predicate")); };
            let input = module.find_in(*id, 3, "GameDataNameBoolExp").ok_or(Error::Format("Prelude: missing predicate input"))?;
            let offset = module.pool.add(target);
            module.set_in_val(3, input, &offset.to_le_bytes())?;
            module.write()
        })?;
    }
    if selected(features, "starting_bunny_hood").and_then(Json::as_bool) == Some(true) {
        edit_staged(rf, more, work, crate::ainb::start::MODULE, false,
            |raw| crate::start_reward::give(raw, "Item_Mask_Bunny"))?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn medallion_only_formulas_never_count_spiritual_stones() {
        for n in 0..=6 {
            let terms = terms(n, "Test.Played");
            assert!(!terms.iter().any(|(_, flag)| flag.starts_with("IsGet.Item_Stone_")));
            assert!(terms.iter().any(|(_, flag)| flag == "Test.Played"));
            if n == 0 { assert_eq!(terms.len(), 2); }
        }
    }

    #[test]
    fn no_envelope_never_changes_old_native_predicates() {
        assert!(edits(&Json::obj()).unwrap().is_empty());
        let features = Json::obj().with("schema", 1_i64.into()).with("settings", Json::obj().with("bridge", "medallions".into())
            .with("bridge_medallions", 7_i64.into()));
        assert!(edits(&features).is_err());
    }
}
