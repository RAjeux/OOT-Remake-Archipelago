//! Versioned AP reachability over the reviewed remake-specific rule bundle.
//! The native builder seed stays in its released format; only newly generated
//! AP rooms export this graph. Old manifests never reconstruct it at launch.
use crate::error::{Error, Res};
use crate::json::Json;
use crate::logic_json::Json as RuleJson;
use crate::settings::seed::SeedFile;
use crate::slice::data::Data;
use crate::slice::{fill, logic, starts, support};
use crate::world::{Placement, Spec, World};

fn feature<'a>(features: &'a Json, name: &str) -> Option<&'a Json> {
    features.get("settings").and_then(|s| s.get(name))
}

fn flag(features: &Json, name: &str) -> bool {
    feature(features, name).and_then(Json::as_bool) == Some(true)
}

fn text<'a>(features: &'a Json, name: &str) -> Option<&'a str> {
    feature(features, name).and_then(Json::as_str)
}

fn count(features: &Json, name: &str, maximum: i64) -> Res<i64> {
    let n = feature(features, name).and_then(Json::as_i64).unwrap_or(maximum);
    if !(0..=maximum).contains(&n) {
        return Err(Error::Msg(format!("{name} is outside 0..{maximum}")));
    }
    Ok(n)
}

fn replace_location(spec: &mut Spec, name: &str, rule: &str) {
    for file in &mut spec.regions {
        let RuleJson::Arr(regions) = file else { continue };
        for region in regions {
            let RuleJson::Obj(fields) = region else { continue };
            for (key, value) in fields {
                if key != "locations" { continue; }
                let RuleJson::Obj(locations) = value else { continue };
                for (location, value) in locations {
                    if location == name { *value = RuleJson::Str(rule.to_string()); }
                }
            }
        }
    }
}

pub fn apply_features(spec: &mut Spec, features: &Json) -> Res<()> {
    // The remake always supplies the five note buttons. It never shuffles
    // those N64-only button items, including in the full-length memory game.
    replace_location(spec, "LW Ocarina Memory Game", "is_child and Ocarina");
    for key in ["skip_tower_escape", "night_skulls_suns_song"] {
        spec.settings.set_bool(key, flag(features, key));
    }
    if flag(features, "skulls_by_day") {
        spec.settings.set_bool("gold_skulls_ignore_daytime", true);
        spec.settings.set_bool("night_skulls_suns_song", false);
    }
    if flag(features, "free_scarecrow") {
        spec.settings.set_str("scarecrow_behavior", "free");
    }
    let classic_prelude = text(features, "prelude_trigger") == Some("classic");
    spec.settings.set_bool("prelude_medallion", classic_prelude);
    replace_location(spec, "Sheik at Temple", if classic_prelude {
        "is_adult and Forest_Medallion"
    } else {
        "is_adult and 'Defeat Phantom Ganon'"
    });
    // Upstream's generic helper assumes medallions for this scene. Bind both
    // modes explicitly to the native predicate installed for this AP room.
    replace_location(spec, "Sheik in Kakariko", if text(features, "nocturne_trigger") == Some("classic") {
        "is_adult and Forest_Medallion and Fire_Medallion and Water_Medallion"
    } else {
        "is_adult and 'Defeat Phantom Ganon' and 'Defeat Volvagia' and 'Defeat Morpha'"
    });
    if text(features, "bridge") == Some("medallions") {
        spec.settings.set_str("bridge", "medallions");
        spec.settings.set_int("bridge_medallions", count(features, "bridge_medallions", 6)?);
    }
    if text(features, "shuffle_ganon_bosskey") == Some("lacs_medallions") {
        spec.settings.set_str("lacs_condition", "medallions");
        spec.settings.set_int("lacs_medallions", count(features, "lacs_medallions", 6)?);
        spec.settings.set_str("shuffle_ganon_bosskey", "on_lacs");
    }
    Ok(())
}

pub fn rebuild(seed: &SeedFile, features: &Json) -> Res<(World, Placement)> {
    let original = Data::load()?;
    let loaded = seed.settings()?;
    let mut plan = support::plan(&loaded.settings)?;
    let trade = crate::adult_trade::data_with(&original, plan.adult_trade);
    let data = trade.as_ref().unwrap_or(&original);
    let layout = crate::shops::seed::layout(seed)?;
    let shop_data = layout.as_ref().map(|l| crate::shops::logic::data_with(data, l)).transpose()?;
    let data = shop_data.as_ref().unwrap_or(data);
    let mut spec = logic::spec_for(data, &plan.logic(), true)?;
    apply_features(&mut spec, features)?;
    if let Some(layout) = &layout { crate::shops::logic::patch(&mut spec, layout)?; }
    let mut world = logic::world_from(spec)?;
    // The new rules can make an old "useful" item (for example the Deku
    // Shield) logically required. Derive advancement from the compiled rules,
    // rather than carrying the donor catalogue's older classification forward.
    for item in 0..world.items.names.len() {
        if !world.users[item].is_empty() || world.goal.deps.contains(&item) {
            world.items.adv[item] = true;
        }
    }
    starts::add(data, &plan, &mut world, &seed.seed)?;
    // Native map/compass starting effects are saved dungeon flags rather
    // than pouch objects. Record those real effects in the exported inventory
    // as well, so extra AP sources cannot reintroduce already-owned maps.
    let flags: std::collections::BTreeSet<_> = crate::slice::dungeon_items::start_flags(&plan)
        .into_iter().filter(|(_, enabled)| *enabled).map(|(name, _)| name).collect();
    for item in &data.items {
        let member = match item.kind.as_str() { "Map" => "IsGetMap", "Compass" => "IsGetCompass", _ => continue };
        let Some(dungeon) = item.dungeon.as_deref().and_then(crate::dungeon_grant::struct_of) else { continue };
        if flags.contains(&crate::dungeon_credit::flag(dungeon, member)) {
            if let Some(id) = world.item(&item.name) {
                if !world.start.iter().any(|(i, _)| *i == id) { world.start.push((id, 1)); }
            }
        }
    }
    if flag(features, "starting_bunny_hood") {
        if let Some(item) = world.item("Bunny Hood") { world.start.push((item, 1)); }
    }
    crate::entr::restore(&mut world, &seed.entrances)?;
    let mut placement = fill::vanilla_place(&world, data)?;
    if crate::start_items::pool::active(&plan) {
        plan.excluded = plan.excluded.iter().filter_map(|name| crate::slice::plando::loc_of(&world, name).ok()
            .map(|id| world.locs[id].name.clone())).collect();
        let picked = crate::slice::pick::pick(data, &world, &plan);
        placement = crate::start_items::pool::base(data, &world, &plan, &placement, &picked.free)?.0;
    }
    for (name, item) in &seed.placements {
        if let (Some(location), Some(item)) = (world.loc(name), world.item(item)) { placement.put(location, item); }
    }
    Ok((world, placement))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::logic_val::Val;

    #[test]
    fn exported_starting_maps_match_the_real_native_dungeon_flags() {
        for mode in ["dungeon", "startwith", "remove"] {
            let mut settings = crate::settings::Settings::default();
            settings.set("shuffle_mapcompass", crate::settings::Value::s(mode)).unwrap();
            let generated = crate::slice::generate_with(&settings, "AP-starting-maps", &crate::slice::GenOpts::default()).unwrap();
            let (world, _) = rebuild(&generated.seed_file, &Json::obj()).unwrap();
            let compass = world.item("Compass (Fire Temple)").unwrap();
            assert_eq!(world.start.iter().any(|(item, count)| *item == compass && *count > 0), mode != "dungeon");
        }
    }

    #[test]
    fn modern_rules_compile_without_changing_the_legacy_bundle() {
        let data = Data::load().unwrap();
        let legacy = logic::world(&data).unwrap();
        let mut spec = logic::spec_for(&data, &[], true).unwrap();
        apply_features(&mut spec, &Json::obj()).unwrap();
        let modern = logic::world_from(spec).unwrap();
        assert!(modern.loc("Ganon").is_some());
        assert!(modern.loc("KF Midos Top Left Chest").is_some());
        assert!(modern.real.len() < legacy.real.len());
        assert!(legacy.real.len() > 1000);
    }

    #[test]
    fn explicit_feature_modes_preserve_typed_logic_values() {
        let data = Data::load().unwrap();
        let mut spec = logic::spec_for(&data, &[], true).unwrap();
        let features = Json::obj().with("settings", Json::obj().with("skulls_by_day", true.into())
            .with("night_skulls_suns_song", true.into()).with("bridge", "medallions".into())
            .with("bridge_medallions", 3_i64.into()));
        apply_features(&mut spec, &features).unwrap();
        assert_eq!(spec.settings.get("gold_skulls_ignore_daytime"), Some(&Val::Bool(true)));
        assert_eq!(spec.settings.get("night_skulls_suns_song"), Some(&Val::Bool(false)));
        assert_eq!(spec.settings.get("bridge_medallions"), Some(&Val::Int(3)));
    }

    #[test]
    fn randomized_shops_keep_every_released_shelf_identity_in_the_modern_graph() {
        let mut settings = crate::settings::Settings::default();
        settings.set("shuffle_shops", crate::settings::Value::s("shuffle")).unwrap();
        let generated = crate::slice::generate_with(&settings, "AP-modern-shelves", &crate::slice::GenOpts::default()).unwrap();
        let (world, _) = rebuild(&generated.seed_file, &Json::obj()).unwrap();
        for name in generated.seed_file.shops.keys() {
            assert!(world.loc(name).is_some(), "missing released shelf {name}");
        }
    }
}
