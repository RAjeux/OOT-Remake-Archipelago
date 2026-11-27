//! Restore only geometry changed by the temporary portable construction seed.
//! Rewards, event names, collection flags and canonical AP placements stay intact.
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::Path;

use ootrr_core::byml::{Byml, Node};
use ootrr_core::json::Json;
use ootrr_core::settings::seed::SeedFile;
use ootrr_core::slice::{self, data::Data};
use ootrr_core::{chest_size, modpack, pickup_pack, placement, romfs::Romfs, rsizetable::{self, Rst}, zs};

use super::{read_overlay, Result};

fn actors(y: &Byml) -> Result<&[Node]> {
    Ok(y.root.get("Actors").and_then(Node::as_arr).ok_or("portable geometry: map has no actors")?)
}

fn actor(y: &Byml, hash: u64) -> Result<&Node> {
    let mut found = actors(y)?.iter().filter(|a| placement::hash_of(a) == Some(hash));
    let value = found.next().ok_or_else(|| format!("portable geometry: missing actor {hash}"))?;
    if found.next().is_some() { return Err("portable geometry: duplicate actor identity".into()); }
    Ok(value)
}

fn actor_mut(y: &mut Byml, hash: u64) -> Result<&mut Node> {
    // Validate uniqueness before borrowing the selected row mutably.
    actor(y, hash)?;
    Ok(y.root.get_mut("Actors").and_then(Node::as_arr_mut).ok_or("portable geometry: map has no actors")?
        .iter_mut().find(|a| placement::hash_of(a) == Some(hash)).ok_or("portable geometry: actor vanished")?)
}

fn restore_field(staged: &mut Node, projected: &Node, canonical: &Node, field: &str) -> Result<bool> {
    if staged.get(field) == canonical.get(field) { return Ok(false); }
    if staged.get(field) != projected.get(field) {
        return Err(format!("portable geometry: staged {field} differs from both reviewed construction geometries").into());
    }
    if let Some(value) = canonical.get(field) { staged.set(field, value.clone()); }
    else { staged.remove(field); }
    Ok(true)
}

fn raised(native: &Node, hash: u64, lift: f32) -> Result<Node> {
    if !lift.is_finite() || !(0.0..=pickup_pack::lift::CAP as f32 / 1000.0).contains(&lift) {
        return Err("portable geometry: invalid native pickup lift".into());
    }
    let mut map = Byml { root: Node::Map(vec![("Actors".into(), Node::Arr(vec![native.clone()]))]), version: 7, big: false };
    if lift != 0.0 && pickup_pack::lift::raise(&mut map, hash, lift) != 1 {
        return Err("portable geometry: pickup has no native float position".into());
    }
    let item = actor(&map, hash)?;
    if item.get("Translate").and_then(Node::as_arr).is_none_or(|p| p.len() != 3) {
        return Err("portable geometry: pickup has no native position".into());
    }
    Ok(item.clone())
}

fn restore_pickup(staged: &mut Byml, native: &Byml, hash: u64, canonical_lift: f32, projected_lift: f32) -> Result<bool> {
    let source = actor(native, hash)?;
    let canonical = raised(source, hash, canonical_lift)?;
    let projected = raised(source, hash, projected_lift)?;
    restore_field(actor_mut(staged, hash)?, &projected, &canonical, "Translate")
}

fn allowed_chest_pair(a: &str, b: &str) -> bool {
    chest_size::PAIRS.iter().any(|(small, big)| [*small, *big].contains(&a) && [*small, *big].contains(&b))
        || (chest_size::AREAS.contains(&a) && chest_size::AREAS.contains(&b))
}

fn restore_chests(staged: &mut Byml, projected: &Byml, canonical: &Byml) -> Result<usize> {
    let mut jobs = Vec::new();
    let (correct_rows, temporary_rows) = (actors(canonical)?, actors(projected)?);
    if correct_rows.len() != temporary_rows.len() { return Err("portable geometry: native resize changed actor count".into()); }
    // Both native plans come from the exact same authored map. Resize never
    // inserts/reorders rows; an unrelated non-addressable actor needs no hash.
    for (row, interim) in correct_rows.iter().zip(temporary_rows) {
        if row.get("Gyaml") == interim.get("Gyaml") { continue; }
        let hash = placement::hash_of(row).ok_or("portable geometry: resized native actor lacks hash")?;
        if placement::hash_of(interim) != Some(hash) { return Err("portable geometry: native resize changed actor identity".into()); }
        let (Some(a), Some(b)) = (row.get("Gyaml").and_then(Node::as_str), interim.get("Gyaml").and_then(Node::as_str)) else {
            return Err("portable geometry: chest model is not a native name".into());
        };
        if !allowed_chest_pair(a, b) { return Err("portable geometry: unreviewed chest geometry change".into()); }
        // Native resize changes only Gyaml; reject another structural change.
        let mut unchanged = interim.clone();
        unchanged.set("Gyaml", Node::Str(a.to_string()));
        if &unchanged != row { return Err("portable geometry: native resize changed more than its model".into()); }
        let current = actor(staged, hash)?;
        if current.get("Gyaml") != row.get("Gyaml") && current.get("Gyaml") != interim.get("Gyaml") {
            return Err("portable geometry: staged chest model differs from construction".into());
        }
        jobs.push((hash, interim.clone(), row.clone()));
    }
    let mut changed = 0;
    for (hash, interim, canonical) in jobs {
        changed += usize::from(restore_field(actor_mut(staged, hash)?, &interim, &canonical, "Gyaml")?);
    }
    Ok(changed)
}

fn lift_for(wants: &BTreeMap<String, slice::seed_packs::Want>, info: &Byml, source: &str) -> Result<f32> {
    let packs: Vec<_> = wants.values().filter(|want| want.spots.iter().any(|spot| spot == source)).collect();
    if packs.len() > 1 { return Err("portable geometry: ambiguous source pickup pack".into()); }
    Ok(packs.first().and_then(|want| pickup_pack::lift::for_pack(info, &want.name)).unwrap_or(0.0))
}

fn diagnosed_tiers(data: &Data, seed: &SeedFile, requested: &Json, input: &Json) -> Result<BTreeMap<String, String>> {
    let requested = requested.as_arr().ok_or("portable geometry: diagnosed sources must be a list")?;
    let mut names = BTreeSet::new();
    for value in requested {
        let name = value.as_str().ok_or("portable geometry: diagnosed source must be a name")?;
        if !names.insert(name) { return Err("portable geometry: duplicate diagnosed source".into()); }
    }
    let entries = input.as_obj().ok_or("portable geometry: portable_tiers must be an actor map")?;
    if entries.len() != names.len() { return Err("portable geometry: tier actors do not match diagnosed sources".into()); }
    let mut result = BTreeMap::new();
    for (name, value) in entries {
        if !names.contains(name.as_str()) { return Err("portable geometry: tier actor has an undiagnosed source".into()); }
        let actor = value.as_str().ok_or("portable geometry: diagnosed tier actor is not a name")?;
        let item = seed.placements.get(name).ok_or("portable geometry: diagnosed source has no canonical item")?;
        let native = data.item(item).ok_or("portable geometry: diagnosed item has no native metadata")?;
        if data.family(item).is_none() || !native.tiers.iter().any(|tier| tier == actor) {
            return Err(format!("portable geometry: diagnosed actor {actor} is not a native tier of {item}").into());
        }
        // An actor from another family or an unbuilt fixed pickup is never a
        // valid geometry authority, even if supplied by a caller.
        slice::key_spots::resolve(data, item, Some(actor))?;
        if result.insert(name.clone(), actor.to_string()).is_some() {
            return Err("portable geometry: duplicate tier actor source".into());
        }
    }
    Ok(result)
}

struct Map {
    before: Vec<u8>,
    dictionary: Option<u32>,
    staged: Byml,
    native: Byml,
}

fn load<'a>(maps: &'a mut BTreeMap<String, Map>, game: &mut Romfs, overlay: &Path, path: &str) -> Result<&'a mut Map> {
    if !maps.contains_key(path) {
        if !path.starts_with("Banc/") || !path.ends_with(".bcett.byml.zs") { return Err("portable geometry: unexpected map path".into()); }
        modpack::rel(path)?;
        let (before, dictionary) = read_overlay(game, overlay, path)?;
        maps.insert(path.to_string(), Map { staged: Byml::parse(&before)?, before, dictionary,
                                             native: Byml::parse(&game.read_zs(path)?)? });
    }
    Ok(maps.get_mut(path).ok_or("portable geometry: map cache failed")?)
}

pub fn run(input: &Json) -> Result<()> { run_at(input, Path::new("/game"), Path::new("/mod")) }

fn run_at(input: &Json, game_path: &Path, overlay: &Path) -> Result<()> {
    let seed = SeedFile::parse(&input.get("seed_file").ok_or("portable geometry: missing canonical seed")?.pretty())?;
    let names = input.get("ap_sources").ok_or("portable geometry: missing AP source selection")?;
    let requested = input.get("project_sources").ok_or("portable geometry: missing diagnosed source selection")?;
    // Never trust a caller-supplied set of swaps or constructor seed.
    let (projected, swaps) = super::portable_seed::derive(&seed, names, requested)?;
    let canonical = ootrr_core::adult_trade::base_seed(&seed)?;
    let data = Data::load()?;
    let tiers = diagnosed_tiers(&data, &canonical, requested,
        input.get("portable_tiers").ok_or("portable geometry: missing diagnosed tier actors")?)?;
    let swaps = swaps.as_arr().ok_or("portable geometry: projection has no swap list")?;
    if swaps.is_empty() { println!("No construction geometry differs."); return Ok(()); }
    let catalogue = super::network_sources::source_map(&data)?;
    let mut original_order = slice::tier_order::fixed_actors(&data, &canonical)?;
    // The pinned portable builder and the in-tree logic can disagree about
    // reach order. Bind these exact sources to that builder's validated error
    // actors rather than silently substituting an in-tree first-tier model.
    for (source, actor) in tiers { original_order.assign.insert(source, actor); }
    // A bad original reach-order verdict is exactly what AP projection fixes.
    // Its assignments only reproduce the original intended display geometry;
    // derive() still enforces the strict native guard for the constructed seed.
    let native_wants = slice::seed_packs::need(&data, &canonical, &original_order.assign)?;
    let projected_order = slice::tier_order::fixed_actors(&data, &projected)?;
    if !projected_order.bad.is_empty() { return Err("portable geometry: constructed seed lost its tier proof".into()); }
    let projected_wants = slice::seed_packs::need(&data, &projected, &projected_order.assign)?;
    let mut game = Romfs::open(game_path)?;
    let actor_info = game.read_byml(pickup_pack::rows::ACTOR_INFO)?;
    let mut maps = BTreeMap::new();
    let mut pickups = 0;
    for swap in swaps {
        let source = swap.get("source").and_then(Json::as_str).ok_or("portable geometry: swap has no source")?;
        let metadata = catalogue.get(source).ok_or("portable geometry: unknown native source")?;
        if metadata.get("kind").and_then(Json::as_str) != Some("pickup") { continue; }
        let canonical_lift = lift_for(&native_wants, &actor_info, source)?;
        let projected_lift = lift_for(&projected_wants, &actor_info, source)?;
        for variant in metadata.get("variants").and_then(Json::as_arr).ok_or("portable geometry: no source variants")? {
            let path = variant.get("file").and_then(Json::as_str).ok_or("portable geometry: source variant lacks file")?;
            let hash = variant.get("actor").and_then(Json::as_str).ok_or("portable geometry: source variant lacks hash")?.parse::<u64>()?;
            let expected = variant.get("expected_actor").and_then(Json::as_str).ok_or("portable geometry: source variant lacks actor")?;
            let map = load(&mut maps, &mut game, overlay, path)?;
            if actor(&map.native, hash)?.get("Gyaml").and_then(Node::as_str) != Some(expected) {
                return Err(format!("portable geometry: native source {source} changed its identity").into());
            }
            pickups += usize::from(restore_pickup(&mut map.staged, &map.native, hash, canonical_lift, projected_lift)?);
        }
    }
    let plan = slice::support::plan(&canonical.settings()?.settings)?;
    let mut chests = 0;
    if plan.chest_sizes {
        let ctx = chest_size::Ctx { chus: plan.chus, owned: plan.start.owned.clone() };
        let credited = slice::dungeon_items::credited(plan.keys.map);
        let wanted = chest_size::wanted(&data, &canonical, &ctx, credited);
        let interim = chest_size::wanted(&data, &projected, &ctx, credited);
        if wanted != interim {
            let files = placement::banc_files(&game)?;
            let mut scenes: BTreeMap<String, Vec<chest_size::Seen>> = BTreeMap::new();
            for file in &files {
                let native = Byml::parse(&game.read_zs(file)?)?;
                scenes.entry(chest_size::stem(file)).or_default().extend(chest_size::seen(&native));
            }
            let moves = chest_size::moves(&scenes, &wanted);
            let interim_moves = chest_size::moves(&scenes, &interim);
            // A changed donor can affect a neighbouring chest's room test or
            // the paired Dampe chests, so compare the two full native plans.
            for file in files {
                let native = game.read_zs(&file)?;
                let correct = chest_size::resize(&native, &file, &wanted, &moves)?.map(|v| v.0).unwrap_or_else(|| native.clone());
                let temporary = chest_size::resize(&native, &file, &interim, &interim_moves)?.map(|v| v.0).unwrap_or(native);
                if correct == temporary { continue; }
                let map = load(&mut maps, &mut game, overlay, &file)?;
                chests += restore_chests(&mut map.staged, &Byml::parse(&temporary)?, &Byml::parse(&correct)?)?;
            }
        }
    }
    let mut outputs = Vec::new();
    for (path, map) in maps {
        let raw = map.staged.write()?;
        if raw != map.before { outputs.push((path, map.before.len(), raw, map.dictionary)); }
    }
    if !outputs.is_empty() {
        let (raw, dictionary) = read_overlay(&mut game, overlay, rsizetable::TABLE_PATH)?;
        let mut table = Rst::parse(&raw)?;
        for (path, before, after, _) in &outputs { table.grow(path, *before as u64, after.len() as u64, slice::edit::MARGIN)?; }
        let rst_frame = zs::compress_raw(&table.write()?, dictionary)?;
        let frames = outputs.iter().map(|(path, _, raw, dictionary)| Ok((path, zs::compress_raw(raw, *dictionary)?)))
            .collect::<Result<Vec<_>>>()?;
        for (path, frame) in frames {
            let target = overlay.join(modpack::rel(path)?);
            fs::create_dir_all(target.parent().ok_or("portable geometry: invalid target")?)?;
            fs::write(target, frame)?;
        }
        fs::write(overlay.join(rsizetable::TABLE_PATH), rst_frame)?;
    }
    println!("Restored construction geometry: {pickups} pickup positions, {chests} chest/keep-away models, {} maps; rewards and event bindings preserved.", outputs.len());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn item(hash: u64, class: &str) -> Node {
        Node::Map(vec![("Hash".into(), Node::U64(hash)), ("Gyaml".into(), Node::Str(class.into())),
            ("Translate".into(), Node::Arr(vec![Node::F32(1.0), Node::F32(2.0), Node::F32(3.0)])),
            ("Dynamic".into(), Node::Map(vec![("Drop__DropActor".into(), Node::Str("ACTUAL_AP_DONOR".into())),
                ("GetEventName".into(), Node::Str("ActualConstructedEvent".into()))])),
            ("Presence".into(), Node::Str("NativeQuestGate".into()))])
    }
    fn map(rows: Vec<Node>) -> Byml {
        Byml { root: Node::Map(vec![("Actors".into(), Node::Arr(rows))]), version: 7, big: false }
    }

    #[test]
    fn canonical_pickup_lift_is_native_based_idempotent_and_keeps_real_reward() {
        let native = map(vec![item(1, "Obj_Heart_Piece")]);
        let mut staged = map(vec![item(1, "Obj_Rupee_Green")]);
        let before = actor(&staged, 1).unwrap().clone();
        assert!(restore_pickup(&mut staged, &native, 1, 0.527, 0.0).unwrap());
        let correct = raised(actor(&native, 1).unwrap(), 1, 0.527).unwrap();
        assert_eq!(actor(&staged, 1).unwrap().get("Translate"), correct.get("Translate"));
        for key in ["Gyaml", "Dynamic", "Presence"] { assert_eq!(actor(&staged, 1).unwrap().get(key), before.get(key)); }
        assert!(!restore_pickup(&mut staged, &native, 1, 0.527, 0.0).unwrap());
    }

    #[test]
    fn pickup_refuses_unreviewed_position_and_ambiguous_identity() {
        let native = map(vec![item(1, "Obj_Heart_Piece")]);
        let mut staged = map(vec![raised(&item(1, "Obj_Rupee_Green"), 1, 0.2).unwrap()]);
        let before = staged.write().unwrap();
        assert!(restore_pickup(&mut staged, &native, 1, 0.5, 0.0).is_err());
        assert_eq!(staged.write().unwrap(), before);
        assert!(restore_pickup(&mut map(vec![item(1, "X"), item(1, "X")]), &native, 1, 0.5, 0.0).is_err());
        assert!(raised(&item(1, "X"), 1, f32::NAN).is_err());
        assert!(raised(&item(1, "X"), 1, 1.0).is_err());
    }

    #[test]
    fn chest_and_matching_keepaway_use_canonical_size_without_touching_constructed_bindings() {
        let canonical = map(vec![item(1, "Obj_TBox_A_01"), item(2, chest_size::AREAS[0]), item(3, "OtherActor")]);
        let projected = map(vec![item(1, "Obj_TBox_A_02"), item(2, chest_size::AREAS[1]), item(3, "OtherActor")]);
        let mut chest = item(1, "Obj_TBox_A_02");
        chest.get_mut("Dynamic").unwrap().set("Drop__DropActor", Node::Str("Item_Range_Bow".into()));
        chest.get_mut("Dynamic").unwrap().set("GetEventName", Node::Str("ConstructedBowEntry".into()));
        let mut staged = map(vec![chest.clone(), item(2, chest_size::AREAS[1]), item(3, "OtherActor")]);
        assert_eq!(restore_chests(&mut staged, &projected, &canonical).unwrap(), 2);
        assert_eq!(actor(&staged, 1).unwrap().get("Dynamic"), chest.get("Dynamic"));
        assert_eq!(actor(&staged, 1).unwrap().get("Gyaml").and_then(Node::as_str), Some("Obj_TBox_A_01"));
        assert_eq!(actor(&staged, 2).unwrap().get("Gyaml").and_then(Node::as_str), Some(chest_size::AREAS[0]));
        assert_eq!(actor(&staged, 3).unwrap(), actor(&canonical, 3).unwrap());
        assert_eq!(restore_chests(&mut staged, &projected, &canonical).unwrap(), 0);
    }

    #[test]
    fn unrelated_unaddressable_native_rows_do_not_require_an_identity() {
        let unchanged = Node::Map(vec![("Gyaml".into(), Node::Str("NativeNonAddressableMarker".into()))]);
        let canonical = map(vec![item(1, "Obj_TBox_A_01"), unchanged.clone()]);
        let projected = map(vec![item(1, "Obj_TBox_A_02"), unchanged.clone()]);
        let mut staged = map(vec![item(1, "Obj_TBox_A_02"), unchanged.clone()]);
        assert_eq!(restore_chests(&mut staged, &projected, &canonical).unwrap(), 1);
        assert_eq!(actors(&staged).unwrap()[1], unchanged);
    }

    #[test]
    fn chest_refuses_unknown_model_or_non_geometry_native_diff_without_mutating_stage() {
        let canonical = map(vec![item(1, "Obj_TBox_A_01")]);
        let projected = map(vec![item(1, "Obj_TBox_A_02")]);
        let mut staged = map(vec![item(1, "UnrelatedActor")]);
        let before = staged.write().unwrap();
        assert!(restore_chests(&mut staged, &projected, &canonical).is_err());
        assert_eq!(staged.write().unwrap(), before);
        let mut changed = item(1, "Obj_TBox_A_02");
        changed.set("Presence", Node::Str("ChangedQuestGate".into()));
        assert!(restore_chests(&mut map(vec![item(1, "Obj_TBox_A_02")]), &map(vec![changed]), &canonical).is_err());
    }

    #[test]
    fn diagnosed_actor_map_requires_exact_sources_and_their_native_family() {
        let data = Data::load().unwrap();
        let seed = SeedFile::new("geometry diagnostic", &ootrr_core::settings::Settings::default(), "game", [
            ("LH Freestanding PoH".into(), "Bow".into())].into_iter().collect()).unwrap();
        let names = Json::strs(["LH Freestanding PoH"]);
        let valid = Json::obj().with("LH Freestanding PoH", "Item_Quiver_Large".into());
        assert_eq!(diagnosed_tiers(&data, &seed, &names, &valid).unwrap()["LH Freestanding PoH"], "Item_Quiver_Large");
        for invalid in [Json::obj(), Json::Arr(Vec::new()),
            Json::obj().with("LH Freestanding PoH", 1_i64.into()),
            Json::obj().with("LH Freestanding PoH", "Item_Hookshot".into()),
            Json::obj().with("KF Midos Top Left Chest", "Item_Quiver_Large".into()),
            valid.clone().with("KF Midos Top Left Chest", "Item_Range_Bow".into())] {
            assert!(diagnosed_tiers(&data, &seed, &names, &invalid).is_err(), "{invalid:?}");
        }
        assert!(diagnosed_tiers(&data, &seed, &Json::strs(["LH Freestanding PoH", "LH Freestanding PoH"]), &valid).is_err());
    }

    #[test]
    fn diagnosed_large_quiver_lift_does_not_use_the_in_tree_bow_fallback() {
        let native = map(vec![item(1, "Obj_Heart_Piece")]);
        let mut staged = map(vec![item(1, "Obj_Rupee_Green")]);
        assert!(restore_pickup(&mut staged, &native, 1, 0.562, 0.0).unwrap());
        let exact = raised(actor(&native, 1).unwrap(), 1, 0.562).unwrap();
        let incorrect = raised(actor(&native, 1).unwrap(), 1, 0.600).unwrap();
        assert_eq!(actor(&staged, 1).unwrap().get("Translate"), exact.get("Translate"));
        assert_ne!(actor(&staged, 1).unwrap().get("Translate"), incorrect.get("Translate"));
    }
}
