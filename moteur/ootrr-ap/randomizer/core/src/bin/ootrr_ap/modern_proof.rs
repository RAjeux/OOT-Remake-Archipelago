//! Rescue omitted donor catalogue entries only after proving their real AP rules.
//!
//! Donor spheres are not AP access rules. In particular, native optional goods
//! can be absent from that old playthrough even when the current AP pool and
//! versioned rules prove them. Keep known historical exceptions unchanged and
//! never turn an arbitrary unproved check into an optional location.
use std::collections::{BTreeMap, BTreeSet};
use ootrr_core::{json::Json, search::Search, slice, world::{Placement, World}};
use super::Result;

pub fn supplement(w: &World, placement: &Placement, native_sources: &Json,
                  sources: &Json, spheres: &[Vec<(String, String)>])
    -> Result<Vec<Vec<(String, String)>>> {
    let native = native_sources.as_obj().ok_or("invalid native proof sources")?;
    let all = sources.as_obj().ok_or("invalid modern proof sources")?;
    let proven: BTreeSet<&str> = spheres.iter().flatten().map(|(name, _)| name.as_str()).collect();
    let omitted: BTreeSet<&str> = native.iter().map(|(name, _)| name.as_str())
        .filter(|name| !proven.contains(name) && super::network_sources::optional_reason(name).is_none()).collect();
    if omitted.is_empty() { return Ok(spheres.to_vec()); }

    let mut routes: BTreeMap<&str, Vec<usize>> = all.iter().map(|(name, _)| (name.as_str(), Vec::new())).collect();
    if native.iter().any(|(name, _)| !routes.contains_key(name.as_str())) {
        return Err("native proof source is absent from the AP pool".into());
    }
    let mut fixed = Placement::new(w.locs.len());
    for (id, location) in w.locs.iter().enumerate() {
        let base = location.name.split(slice::data::SEP).next().unwrap_or(&location.name);
        if let Some(route) = routes.get_mut(base) {
            if location.event.is_some() { return Err("AP proof source collides with a native event".into()); }
            route.push(id);
        } else if let Some(item) = placement.get(id) { fixed.put(id, item); }
    }
    if let Some((name, _)) = routes.iter().find(|(_, route)| route.is_empty()) {
        return Err(format!("network check has no native access rule: {name}").into());
    }
    let mut search = Search::new(w);
    for (name, source) in all {
        let reward = source.get("generated_item").and_then(Json::as_str)
            .ok_or_else(|| format!("AP proof source has no generated reward: {name}"))?;
        let item = w.item(reward).ok_or_else(|| format!("AP proof reward is absent from native rules: {reward}"))?;
        if w.items.event[item] { return Err("AP proof pool cannot contain native events".into()); }
        search.add(item, 1);
    }
    search.settle(&fixed, true);
    // This final row is only an admission index. The exported, unchanged graph
    // still decides every AP access and the official fill must prove victory.
    let rescued = omitted.into_iter().filter(|name|
        routes[name].iter().any(|id| search.loc_access(*id)))
        .map(|name| (name.to_owned(), String::new())).collect::<Vec<_>>();
    let mut result = spheres.to_vec();
    if !rescued.is_empty() { result.push(rescued); }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    use ootrr_core::world::Spec;

    fn fixture(regions: &str) -> (World, Placement) {
        let mut spec = Spec::new();
        spec.add_item("Key", true, 0);
        spec.add_item("Filler", false, 0);
        spec.add_regions(regions).unwrap();
        let world = World::build(&spec).unwrap();
        let placement = Placement::new(world.locs.len());
        (world, placement)
    }
    fn sources(names: &[(&str, &str)]) -> Json {
        Json::Obj(names.iter().map(|(name, item)| ((*name).into(),
            Json::obj().with("generated_item", (*item).into()))).collect())
    }
    #[test]
    fn rescue_uses_exact_pool_and_keeps_healthy_spheres_byte_equivalent() {
        let (world, place) = fixture(r#"[{"region_name":"Root","locations":{"Omitted":"Key","Known":"True"}}]"#);
        let src = sources(&[("Omitted", "Filler"), ("Known", "Key")]);
        let waves = vec![vec![("Known".into(), "retained metadata".into())]];
        let rescued = supplement(&world, &place, &src, &src, &waves).unwrap();
        assert_eq!(rescued[0], waves[0]);
        assert_eq!(rescued[1], vec![("Omitted".into(), String::new())]);
        assert_eq!(supplement(&world, &place, &src, &src, &rescued).unwrap(), rescued);
    }
    #[test]
    fn genuinely_unreachable_source_is_not_rescued_or_made_optional() {
        let (world, place) = fixture(r#"[{"region_name":"Root","locations":{"Omitted":"Key"}}]"#);
        let src = sources(&[("Omitted", "Filler")]);
        assert!(supplement(&world, &place, &src, &src, &[]).unwrap().is_empty());
    }
    #[test]
    fn every_selected_age_variant_is_removed_before_fixed_reward_sweep() {
        let (world, mut place) = fixture(r#"[{"region_name":"Root","locations":{"Omitted":"Key","Additional":"True"},"exits":{"Other":"True"}},{"region_name":"Other","locations":{"AdditionalOther":"True"}}]"#);
        let key = world.item("Key").unwrap();
        for id in &world.real { place.put(*id, key); }
        // Use the native separator contract for the second physical age route.
        let mut world = world;
        let additional = world.loc("Additional").unwrap();
        let other = world.loc("AdditionalOther").unwrap();
        world.locs[other].name = format!("Additional{}Other", slice::data::SEP);
        assert_ne!(additional, other);
        let native = sources(&[("Omitted", "Filler")]);
        let all = sources(&[("Omitted", "Filler"), ("Additional", "Filler")]);
        assert!(supplement(&world, &place, &native, &all, &[]).unwrap().is_empty());
    }
    #[test]
    fn fixed_rewards_and_native_events_still_supply_real_routes() {
        let (world, mut place) = fixture(r#"[{"region_name":"Root","locations":{"Omitted":"Key and 'Bridge Open'","Fixed":"True"},"events":{"Bridge Open":"True"}}]"#);
        place.put(world.loc("Fixed").unwrap(), world.item("Key").unwrap());
        let src = sources(&[("Omitted", "Filler")]);
        assert_eq!(supplement(&world, &place, &src, &src, &[]).unwrap()[0][0].0, "Omitted");
    }
    #[test]
    fn historical_optional_and_ap_only_sources_keep_their_existing_paths() {
        let (world, place) = fixture(r#"[{"region_name":"Root","locations":{"Colossus Freestanding PoH":"True","Additional":"True"}}]"#);
        let native = sources(&[("Colossus Freestanding PoH", "Filler")]);
        let all = sources(&[("Colossus Freestanding PoH", "Filler"), ("Additional", "Key")]);
        assert!(supplement(&world, &place, &native, &all, &[]).unwrap().is_empty());
    }
    #[test]
    fn unknown_route_and_native_event_rewards_fail_closed() {
        let (world, place) = fixture(r#"[{"region_name":"Root","locations":{"Omitted":"True"},"events":{"Bridge Open":"True"}}]"#);
        for src in [sources(&[("Missing", "Key")]), sources(&[("Omitted", "Bridge Open")])] {
            assert!(supplement(&world, &place, &src, &src, &[]).is_err());
        }
    }
}
