//! Constructor-only projection for physical rewards replaced by AP callbacks.
//! The canonical AP seed and placements are never modified or refilled.
use std::collections::{BTreeMap, BTreeSet};

use ootrr_core::json::Json;
use ootrr_core::settings::seed::SeedFile;
use ootrr_core::slice::{self, data::{Data, State}, tier_order::{Give, slots}};

use super::Result;

// These native fillers have no progressive tier, dungeon credit or quest state.
// Each candidate must additionally have a supported native physical form.
const FILLERS: &[&str] = &[
    "Rupees (5)", "Rupee (1)", "Rupees (20)", "Rupees (50)", "Rupees (200)",
    "Recovery Heart", "Arrows (5)", "Arrows (10)", "Arrows (30)",
    "Bombs (5)", "Bombs (10)", "Bombs (20)", "Deku Nuts (5)", "Deku Sticks (3)",
];

fn inventory(seed: &SeedFile) -> BTreeMap<String, usize> {
    let mut out = BTreeMap::new();
    for item in seed.placements.values() { *out.entry(item.clone()).or_default() += 1; }
    out
}

fn physical_filler(d: &Data, kind: &str, item: &str) -> bool {
    use slice::key_spots::{placeable, Spot};
    match kind {
        "pickup" => slice::pickups::ground_actor(item).is_some() || placeable(d, item, Spot::Free),
        "container" => ootrr_core::pot_slice::pickup::of(item).is_some() || placeable(d, item, Spot::Pot),
        "skull" => slice::skulls::shared().and_then(|t| slice::skulls::pickup(t, d, item)).is_some()
            || placeable(d, item, Spot::Skull),
        _ => false,
    }
}

fn selected(seed: &SeedFile, names: &Json) -> Result<BTreeMap<String, String>> {
    let settings = seed.settings()?.settings;
    let extras = super::additional_sources::selected(&settings)?;
    let catalogue = super::additional_sources::merge(super::network_sources::selected(seed)?, &extras, &settings)?;
    let list = names.as_arr().ok_or("portable seed: ap_sources must be a list of source names")?;
    let mut out = BTreeMap::new();
    for value in list {
        let name = value.as_str().ok_or("portable seed: AP source must be a name")?;
        let source = catalogue.get(name).ok_or_else(|| format!("portable seed: unknown or unselected AP source {name}"))?;
        let kind = source.get("kind").and_then(Json::as_str).ok_or("portable seed: AP source has no native kind")?;
        if out.insert(name.to_string(), kind.to_string()).is_some() {
            return Err(format!("portable seed: duplicate AP source {name}").into());
        }
    }
    Ok(out)
}

pub fn derive(seed: &SeedFile, names: &Json, project_sources: &Json) -> Result<(SeedFile, Json)> {
    let permitted = selected(seed, names)?;
    let d = Data::load()?;
    let base = ootrr_core::adult_trade::base_seed(seed)?;
    let expected = inventory(&base);
    let mut derived = base.clone();
    // A pinned portable builder may use an older reachability proof than this
    // source tree. Its exact upgrade-tier diagnostic authorizes only these
    // physical AP sources; valid rewards are never moved speculatively.
    let requested = project_sources.as_arr().ok_or("portable seed: project_sources must be a list of source names")?;
    let mut pending = BTreeMap::new();
    for value in requested {
        let name = value.as_str().ok_or("portable seed: projected source must be a name")?;
        let kind = permitted.get(name).ok_or_else(|| format!("portable seed: projected source is not selected for AP: {name}"))?;
        if !matches!(kind.as_str(), "pickup" | "container" | "skull") {
            return Err(format!("portable seed: projected source is not a physical AP reward: {name}").into());
        }
        let item = base.placements.get(name).ok_or_else(|| format!("portable seed: projected source has no native placement: {name}"))?;
        if d.family(item).is_none() || !slice::tier_order::fixed_spot(&d, name) {
            return Err(format!("portable seed: projected source has no native physical upgrade family: {name}").into());
        }
        if pending.insert(name.to_string(), (item.clone(), kind.clone())).is_some() {
            return Err(format!("portable seed: duplicate projected source {name}").into());
        }
    }
    let mut swaps = Vec::new();
    let mut touched = BTreeSet::new();
    for (source, (item, kind)) in pending {
        let family = d.family(&item).ok_or("portable seed: native family vanished")?;
        let mut donors: Vec<_> = derived.placements.iter().filter_map(|(name, filler)| {
            if permitted.get(name).map(String::as_str) != Some("chest") || touched.contains(name)
                || d.state_of(name) != Some(State::Eligible)
                || d.cat.by_name(name).is_none_or(|l| l.kind != "chest") {
                return None;
            }
            let rank = FILLERS.iter().position(|candidate| *candidate == filler)?;
            let entry = d.item(filler)?;
            (!entry.adv && d.family(filler).is_none() && physical_filler(&d, &kind, filler))
                .then(|| (rank, name.clone(), filler.clone()))
        }).collect();
        donors.sort();
        let mut chosen = None;
        for (_, donor, filler) in donors {
            let mut trial = derived.placements.clone();
            trial.insert(source.clone(), filler.clone());
            trial.insert(donor.clone(), item.clone());
            if slots(&d, &trial).iter().any(|s| s.loc == donor && s.family == family && s.give == Give::Flow) {
                chosen = Some((donor, filler, trial));
                break;
            }
        }
        let (donor, filler, placements) = chosen.ok_or_else(|| format!(
            "portable seed: no selected native AP chest with a safe filler can carry {item} from {source}"))?;
        derived.placements = placements;
        touched.insert(source.clone());
        touched.insert(donor.clone());
        swaps.push(Json::obj().with("source", source.into()).with("donor", donor.into())
            .with("item", item.into()).with("filler", filler.into()));
    }
    if inventory(&derived) != expected || derived.placements.keys().ne(base.placements.keys())
        || derived.settings_string != base.settings_string || derived.shops != base.shops
        || derived.entrances != base.entrances || derived.seed != base.seed || derived.game != base.game
        || derived.generator != base.generator {
        return Err("portable seed: construction projection changed an unrelated native field or item count".into());
    }
    let verdict = slice::tier_order::fixed_actors(&d, &derived)?;
    if !verdict.bad.is_empty() {
        return Err(format!("portable seed: native upgrade-tier validation still fails: {}", verdict.bad.join("; ")).into());
    }
    SeedFile::parse(&derived.to_text())?;
    Ok((derived, Json::Arr(swaps)))
}

pub fn run(request: &Json) -> Result<()> {
    let raw = request.get("seed_file").ok_or("portable seed: missing canonical seed_file")?;
    let seed = SeedFile::parse(&raw.pretty())?;
    let sources = request.get("ap_sources").ok_or("portable seed: missing AP source selection")?;
    let empty = Json::Arr(Vec::new());
    let project_sources = request.get("project_sources").unwrap_or(&empty);
    let (derived, swaps) = derive(&seed, sources, project_sources)?;
    println!("{}", Json::obj().with("seed_file", derived.to_json()).with("swaps", swaps).pretty());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use ootrr_core::settings::Settings;

    fn fixture() -> SeedFile {
        SeedFile::new("private constructor proof", &Settings::default(), "native-game-111", [
            ("LH Freestanding PoH".to_string(), "Bow".to_string()),
            ("Kak GS House Under Construction".to_string(), "Bomb Bag".to_string()),
            ("KF Midos Top Left Chest".to_string(), "Rupees (5)".to_string()),
            ("KF Midos Top Right Chest".to_string(), "Rupees (20)".to_string()),
            ("KF Midos Bottom Left Chest".to_string(), "Rupee (1)".to_string()),
        ].into_iter().collect()).unwrap()
    }

    fn names(seed: &SeedFile) -> Json { Json::strs(seed.placements.keys().map(String::as_str)) }

    fn projects() -> Json { Json::strs(["LH Freestanding PoH", "Kak GS House Under Construction"]) }

    fn empty() -> Json { Json::Arr(Vec::new()) }

    #[test]
    fn physical_progressive_rewards_use_only_selected_flow_chests_with_counts_intact() {
        let original = fixture();
        let frozen = original.to_json();
        let (projected, swaps) = derive(&original, &names(&original), &projects()).unwrap();
        assert_eq!(original.to_json(), frozen);
        assert_eq!(inventory(&projected), inventory(&original));
        assert_eq!(swaps.as_arr().unwrap().len(), 2);
        assert_eq!(projected.placements["Kak GS House Under Construction"], "Rupees (5)");
        assert_eq!(projected.placements["KF Midos Top Left Chest"], "Bomb Bag");
        assert_eq!(projected.placements["LH Freestanding PoH"], "Rupee (1)");
        assert!(slice::tier_order::fixed_actors(&Data::load().unwrap(), &projected).unwrap().bad.is_empty());
        assert_eq!(derive(&original, &names(&original), &projects()).unwrap(), (projected.clone(), swaps.clone()));
        assert!(derive(&projected, &names(&projected), &projects()).is_err());
    }

    #[test]
    fn unknown_duplicate_and_uncovered_sources_cannot_authorize_changes() {
        let original = fixture();
        assert!(derive(&original, &Json::obj(), &empty()).is_err());
        assert!(derive(&original, &Json::Arr(vec![1_i64.into()]), &empty()).is_err());
        assert!(derive(&original, &Json::strs(["not a source"]), &empty()).is_err());
        assert!(derive(&original, &Json::strs(["LH Freestanding PoH", "LH Freestanding PoH"]), &empty()).is_err());
        assert!(derive(&original, &Json::strs(["LH Freestanding PoH"]), &Json::strs(["LH Freestanding PoH"])).is_err());
        assert!(derive(&original, &names(&original), &Json::obj()).is_err());
        assert!(derive(&original, &names(&original), &Json::Arr(vec![1_i64.into()])).is_err());
        assert!(derive(&original, &names(&original), &Json::strs(["not a source"])).is_err());
        assert!(derive(&original, &names(&original), &Json::strs(["LH Freestanding PoH", "LH Freestanding PoH"])).is_err());
        assert!(derive(&original, &names(&original), &Json::strs(["KF Midos Top Left Chest"])).is_err());
        let mut no_upgrade = original.clone();
        no_upgrade.placements.insert("LH Freestanding PoH".into(), "Rupees (5)".into());
        assert!(derive(&no_upgrade, &names(&no_upgrade), &Json::strs(["LH Freestanding PoH"])).is_err());
    }

    #[test]
    fn unselected_progressive_sources_are_not_silently_rewritten() {
        let original = fixture();
        let selected = Json::strs(["KF Midos Top Left Chest"]);
        let result = derive(&original, &selected, &empty());
        match result {
            Ok((base, changes)) => {
                assert!(changes.as_arr().unwrap().is_empty());
                assert_eq!(base, original);
            },
            Err(error) => assert!(error.to_string().contains("native upgrade-tier validation still fails"), "{error}"),
        }
    }

    #[test]
    fn real_manifest_projection_is_private_and_keeps_its_canonical_document() {
        let Some(path) = std::env::var_os("OOTRR_PORTABLE_SEED_MANIFEST") else { return };
        let raw = std::fs::read_to_string(path).unwrap();
        let doc = ootrr_core::json::parse(&raw).unwrap();
        let seed = SeedFile::from_json(doc.get("seed_file").unwrap()).unwrap();
        let canonical = seed.to_json();
        let names = Json::strs(doc.get("network_sources").unwrap().as_obj().unwrap().iter().map(|(name, _)| name.as_str()));
        let native_base = ootrr_core::adult_trade::base_seed(&seed).unwrap();
        assert_eq!(derive(&seed, &names, &empty()).unwrap(), (native_base.clone(), empty()));
        let (projected, swaps) = derive(&seed, &names, &Json::strs(["LH Freestanding PoH"])).unwrap();
        assert_eq!(seed.to_json(), canonical);
        assert_eq!(swaps.as_arr().unwrap().len(), 1);
        assert_eq!(swaps.as_arr().unwrap()[0].get("source").and_then(Json::as_str), Some("LH Freestanding PoH"));
        assert_eq!(inventory(&projected), inventory(&native_base));
        assert_eq!(projected.placements["Fire Temple GS Boulder Maze"], native_base.placements["Fire Temple GS Boulder Maze"]);
        if let Some(dest) = std::env::var_os("OOTRR_PORTABLE_SEED_OUTPUT") {
            std::fs::write(dest, Json::obj().with("seed_file", projected.to_json()).with("swaps", swaps).pretty()).unwrap();
        }
    }
}
