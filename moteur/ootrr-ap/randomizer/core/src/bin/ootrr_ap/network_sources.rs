//! The native generator owns source selection, physical identity and placement.
//!
//! These descriptors expose that existing work to AP. They do not run another
//! fill, change a native seed, assign protocol IDs, or treat item ownership as a
//! completed location. The caller must commit its own source flag only after a
//! successful collection and use the same flag for every physical variant.
use std::collections::{BTreeMap, BTreeSet};

use ootrr_core::catalog::{Loc, Via};
use ootrr_core::json::{self, Json};
use ootrr_core::settings::seed::SeedFile;
use ootrr_core::slice::data::{Data, State};
use ootrr_core::{flow_extra, flow_locations, shops, slice};

use super::Result;

type Sources = BTreeMap<String, Json>;

fn strings<'a>(xs: impl IntoIterator<Item = &'a str>) -> Json {
    Json::strs(xs)
}

fn physical_variants(loc: &Loc) -> Result<Vec<Json>> {
    let mut seen = BTreeSet::new();
    let mut out = Vec::new();
    for reference in &loc.refs {
        if reference.hash == 0 || reference.files.is_empty() {
            return Err(format!("network source {} has an empty physical reference", loc.name).into());
        }
        for file in &reference.files {
            if !seen.insert((file.clone(), reference.hash)) { continue; }
            out.push(variant(file, reference.hash, match loc.via { Via::Drop => "drop", Via::Actor => "actor" }, &loc.item)?);
        }
    }
    Ok(out)
}

fn variant(file: &str, hash: u64, via: &str, expected: &str) -> Result<Json> {
    ootrr_core::modpack::rel(file)?;
    if !file.starts_with("Banc/") || !file.ends_with(".bcett.byml.zs") || hash == 0 {
        return Err("network source has an invalid physical map reference".into());
    }
    Ok(Json::obj().with("file", file.into()).with("actor", hash.to_string().into())
        .with("via", via.into()).with("expected_actor", expected.into()))
}

fn physical(loc: &Loc, kind: &str) -> Result<Json> {
    let variants = physical_variants(loc)?;
    if variants.is_empty() { return Err(format!("network source {} has no physical variants", loc.name).into()); }
    Ok(Json::obj().with("name", loc.name.clone().into()).with("kind", kind.into())
        .with("native_kind", loc.kind.clone().into()).with("area", loc.area.clone().into())
        .with("variants", Json::Arr(variants)).with("flow_edits", Json::Arr(Vec::new()))
        .with("collection", (if kind == "chest" { "chest_reward" } else { "pickup" }).into()))
}

/// Named Skulltulas can correct an ambiguous location's original actor match.
/// Resolve their authoritative hash through the existing native physical census.
fn skull(d: &Data, name: &str) -> Result<Json> {
    let mut variants = Vec::new();
    let mut seen = BTreeSet::new();
    let hashes = slice::skull_names::hashes(d, name);
    if hashes.is_empty() { return Err(format!("network Skulltula {name} has no native hash").into()); }
    for hash in &hashes {
        let mut found = false;
        for loc in &d.cat.locs {
            for reference in loc.refs.iter().filter(|r| r.hash == *hash) {
                for file in &reference.files {
                    found = true;
                    if seen.insert((file.clone(), *hash)) {
                        variants.push(variant(file, *hash, "drop", "Obj_Token_Gold")?);
                    }
                }
            }
        }
        for loc in &d.cat.gap_rem {
            for reference in loc.refs.iter().filter(|r| r.hash == *hash) {
                for file in &reference.files {
                    found = true;
                    if seen.insert((file.clone(), *hash)) {
                        variants.push(variant(file, *hash, "drop", "Obj_Token_Gold")?);
                    }
                }
            }
        }
        if !found { return Err(format!("network Skulltula {name} has no native map for hash {hash}").into()); }
    }
    let rows: Vec<String> = hashes.iter().flat_map(|h| [h.to_string(), (h ^ 2).to_string()]).collect();
    Ok(Json::obj().with("name", name.into()).with("kind", "skull".into()).with("native_kind", "gs".into())
        .with("variants", Json::Arr(variants)).with("flow_edits", Json::Arr(Vec::new()))
        .with("collection", "pickup".into()).with("native_pickup_rows", strings(rows.iter().map(String::as_str))))
}

fn event_edits(loc: &flow_locations::Loc) -> Result<Vec<Json>> {
    let mut out = Vec::new();
    let mut seen = BTreeSet::new();
    for edit in &loc.edits {
        for file in std::iter::once(&edit.file).chain(edit.also.iter()) {
            let file = flow_locations::path_of(file);
            ootrr_core::modpack::rel(&file)?;
            if !seen.insert((file.clone(), edit.event.clone(), edit.param.clone(), edit.role.clone())) { continue; }
            out.push(Json::obj().with("file", file.into()).with("index", (edit.index as i64).into())
                .with("event", edit.event.clone().into()).with("param", edit.param.clone().into())
                .with("role", edit.role.clone().into()).with("via", edit.via.clone().into())
                .with("expected_actor", edit.item.clone().into()).with("entries", strings(edit.entries.iter().map(String::as_str))));
        }
    }
    Ok(out)
}

fn flow(loc: &flow_locations::Loc, native_ops: &BTreeMap<String, Json>) -> Result<Json> {
    let route = if flow_extra::cows::is(&loc.name) { "cow_once" }
        else if flow_extra::frogs::is(&loc.name) { "frog_once" }
        else if flow_extra::trade::is(&loc.name) { "adult_trade" }
        else if flow_extra::potion::is(&loc.name) { "potion_sale" }
        else if ootrr_core::scrubs_b::is_b(loc) { "scrub_b_sale" }
        else if ootrr_core::scrubs_a::is_a(loc) { "scrub_a_sale" }
        else { "reward" };
    let mut value = Json::obj().with("name", loc.name.clone().into()).with("kind", "flow".into())
        .with("native_kind", loc.cat.clone().into()).with("native_route", route.into())
        .with("variants", Json::Arr(Vec::new())).with("flow_edits", Json::Arr(event_edits(loc)?))
        .with("collection", "reward_grant".into())
        .with("post_build_grants", Json::Arr(post_build_grants(loc, native_ops.get(&loc.name))?));
    if let Some(ops) = native_ops.get(&loc.name) { value = value.with("native_ops", ops.clone()); }
    if let Some(flag) = flow_extra::cows::flag_of(&loc.name) { value = value.with("native_once_flag", flag.into()); }
    if let Some(cow) = ootrr_core::cow_clone::by_location(&loc.name) {
        value = value.with("native_flow", flow_locations::path_of(&cow.flow_file()).into())
            .with("variants", Json::Arr(cow.spots.iter().map(|s| variant(&s.file, s.hash, "actor", &cow.class)).collect::<Result<_>>()?));
    }
    Ok(value)
}

/// Added native grants have dynamically assigned ExtraNN names. Describe their
/// structural anchor instead of inventing an event index that changes with
/// the other enabled native patches in the same flow.
fn post_build_grants(loc: &flow_locations::Loc, ops: Option<&Json>) -> Result<Vec<Json>> {
    let mut out = Vec::new();
    let ops = ops.and_then(Json::as_arr).unwrap_or(&[]);
    let own_grant = ootrr_core::scrubs_b::is_b(loc) || ops.iter().any(|op| {
        ["once_grant", "clone_sub"].contains(&op.get("kind").and_then(Json::as_str).unwrap_or(""))
    });
    for edit in loc.edits.iter().filter(|_| !own_grant) {
        if edit.role != "grant" { continue; }
        for file in std::iter::once(&edit.file).chain(edit.also.iter()) {
            out.push(Json::obj().with("selector", "event".into()).with("file", flow_locations::path_of(file).into())
                .with("event", edit.event.clone().into()).with("param", edit.param.clone().into())
                .with("via", edit.via.clone().into()));
        }
    }
    {
        for op in ops {
            let kind = super::field(op, "kind")?;
            let file = flow_locations::path_of(super::field(op, "file")?);
            match kind {
                "once_grant" => {
                    // Its native bool is set before the call. It is an anchor,
                    // never an AP check or evidence that the grant succeeded.
                    out.push(Json::obj().with("selector", "after_native_flag".into()).with("file", file.into())
                        .with("entry", super::field(op, "entry")?.into()).with("flag_name", super::field(op, "flag")?.into())
                        .with("param", "ActorName".into()).with("via", super::field(op, "sub")?.into()));
                },
                "clone_sub" => {
                    out.push(Json::obj().with("selector", "next_after_event".into()).with("file", file.into())
                        .with("origin_event", super::field(op, "event")?.into()).with("param", super::field(op, "param")?.into())
                        .with("original_actor", super::field(op, "old")?.into()));
                },
                "swap_sub" => {
                    let params = op.get("params").and_then(Json::as_arr).ok_or("native subflow replacement has no parameters")?;
                    for pair in params {
                        if let Some([key, value]) = pair.as_arr() {
                            if value.as_str() == Some("$item") {
                                out.push(Json::obj().with("selector", "event".into()).with("file", file.clone().into())
                                    .with("event", super::field(op, "event")?.into()).with("param", key.clone())
                                    .with("via", super::field(op, "to")?.into()));
                            }
                        }
                    }
                },
                "set" if op.get("new").and_then(Json::as_str) == Some("$item") => {
                    out.push(Json::obj().with("selector", "event".into()).with("file", file.into())
                        .with("event", super::field(op, "event")?.into()).with("param", super::field(op, "param")?.into()));
                },
                _ => {},
            }
        }
    }
    if ootrr_core::scrubs_b::is_b(loc) {
        let book = ootrr_core::scrubs_b::book()?;
        let scrub = book.by_location(&loc.name).ok_or("native scrub has no sale descriptor")?;
        out.push(Json::obj().with("selector", "entry_subflow_parameter".into()).with("file", flow_locations::path_of(&book.flow).into())
            .with("entry", scrub.entry().into()).with("param", "SaleActor".into())
            .with("native_flag", scrub.flag.clone().into()));
    }
    let mut seen = BTreeSet::new();
    out.retain(|row| seen.insert(["selector", "file", "event", "origin_event", "entry", "flag_name", "param"]
        .map(|key| row.get(key).and_then(Json::as_str).unwrap_or("").to_string())));
    Ok(out)
}

fn native_ops() -> Result<BTreeMap<String, Json>> {
    let raw = json::parse(flow_extra::JSON)?;
    let rows = raw.get("locations").and_then(Json::as_arr).ok_or("network source catalogue has no native event adapters")?;
    rows.iter().map(|row| {
        let name = super::field(row, "name")?;
        let ops = row.get("ops").and_then(Json::as_arr).ok_or("native reward adapter has no operations")?;
        Ok((name.to_string(), Json::Arr(ops.to_vec())))
    }).collect()
}

/// Retain the existing native fill's physical-mapping precautions for rewards
/// from every AP game. These properties are deliberately conservative and do
/// not vary with the selected seed or its original vanilla reward.
fn junk_only(plan: &slice::support::Plan, name: &str) -> bool {
    slice::junk_spots::only(plan, name)
        || slice::remake_overworld::UNSURE.contains(&name)
        || slice::pickups::UNSURE.contains(&name)
        || ["Colossus Freestanding PoH", "DMC Volcano Freestanding PoH", "DMT Freestanding PoH"].contains(&name)
}

fn placement_context(d: &Data, world: &ootrr_core::world::World, plan: &slice::support::Plan, name: &str, metadata: &Json) -> Json {
    let region = world.loc(name).map(|id| &world.regions[world.locs[id].region]);
    let dungeon = region.and_then(|r| r.dungeon.as_deref());
    let physical_group = metadata.get("variants").and_then(Json::as_arr).and_then(|rows| rows.first())
        .and_then(|row| row.get("file")).and_then(Json::as_str).and_then(|file| file.split('/').nth(1))
        .and_then(slice::dungeon_items::group)
        .or_else(|| metadata.get("bancs").and_then(Json::as_arr).and_then(|rows| rows.first())
            .and_then(Json::as_str).and_then(|file| file.split('/').nth(1)).and_then(slice::dungeon_items::group));
    let group = physical_group.or_else(|| dungeon.and_then(ootrr_core::dungeon_grant::struct_of).and_then(slice::dungeon_items::group))
        .or_else(|| region.and_then(|r| r.scene.as_deref()).and_then(|scene|
            d.cat.locs.iter().find(|loc| loc.area == scene).and_then(|loc| slice::dungeon_items::group(&loc.folder))));
    Json::obj().with("dungeon", dungeon.map(|value| value.into()).unwrap_or(Json::Null))
        .with("region_group", group.map(|value| value.into()).unwrap_or(Json::Null))
        .with("junk_only", junk_only(plan, name).into())
}

pub(super) fn source_map(d: &Data) -> Result<Sources> {
    let mut sources = Sources::new();
    for loc in &d.cat.locs {
        if slice::skulls::is_skull(d, &loc.name) { continue; }
        let kind = match loc.kind.as_str() {
            "chest" | "key" => {
                if !slice::pickups::is_held(&loc.name)
                    && !d.state_of(&loc.name).is_some_and(|s| s == State::Eligible || s == State::Event) { continue; }
                "chest"
            },
            "freestanding" | "heart" | "bossheart" => "pickup",
            _ => continue,
        };
        sources.insert(loc.name.clone(), physical(loc, kind)?);
    }
    // PotData already merges, retires and replaces old identities. Never
    // concatenate the raw JSON catalogues: they contain superseded references.
    for loc in &d.pots.locs {
        if d.pots.state_of(&loc.name) == Some(State::Eligible) {
            sources.insert(loc.name.clone(), physical(loc, "container")?);
        }
    }
    let skull_names: BTreeSet<&str> = d.cat.locs.iter().filter(|l| l.kind == "gs").map(|l| l.name.as_str())
        .chain(slice::skull_names::extra(d)).collect();
    for name in skull_names { sources.insert(name.to_string(), skull(d, name)?); }
    let ops = native_ops()?;
    for loc in &d.flow.locs {
        if d.flow_ok(&loc.name) || d.song_ok(&loc.name) {
            sources.insert(loc.name.clone(), flow(loc, &ops)?);
        }
    }
    let shops = shops::table()?;
    for slot in &shops.slots {
        let shop = shops.shop(&slot.shop).ok_or("native shelf has no shop")?;
        sources.insert(slot.name.clone(), Json::obj().with("name", slot.name.clone().into()).with("kind", "shop".into())
            .with("native_kind", "shelf".into()).with("shop", slot.shop.clone().into()).with("slot", (slot.slot as i64).into())
            .with("variants", Json::Arr(Vec::new())).with("flow_edits", Json::Arr(Vec::new()))
            .with("native_actor", slot.actor.clone().into()).with("counters", strings(slot.counters.iter().map(String::as_str)))
            .with("keepers", strings(shop.keepers.iter().map(String::as_str))).with("bancs", strings(shop.bancs.iter().map(String::as_str)))
            .with("collection", "successful_purchase".into()));
    }
    // Access settings change rules, not the physical source's dungeon/region.
    // Use the existing complete native world to cover optional source families
    // while keeping this packaged context identical for every generated seed.
    let mut complete = ootrr_core::spots::FULL.to_vec();
    complete.push((flow_extra::potion::KEY, flow_extra::potion::ON));
    let world = slice::logic::world_with(d, &complete)?;
    let mut caution_settings = ootrr_core::settings::Settings::default();
    caution_settings.set("shuffle_skulltulas", ootrr_core::settings::Value::s("matched"))?;
    let caution_plan = slice::support::plan(&caution_settings)?;
    for (name, metadata) in &mut sources {
        let placement = placement_context(d, &world, &caution_plan, name, metadata);
        *metadata = metadata.clone().with("placement", placement);
    }
    for (name, metadata) in super::additional_sources::catalog()? {
        if sources.insert(name, metadata).is_some() { return Err("additional source collides with native catalogue".into()); }
    }
    Ok(sources)
}

pub fn catalog() -> Result<Json> {
    Ok(Json::obj().with("schema", 2_i64.into()).with("sources", Json::Obj(source_map(&Data::load()?)?.into_iter().collect())))
}

pub fn selected(seed: &SeedFile) -> Result<Json> {
    let d = Data::load()?;
    let catalogue = source_map(&d)?;
    let settings = seed.settings()?.settings;
    let plan = slice::support::plan(&settings)?;
    let mut names: BTreeSet<&str> = seed.placements.keys().map(String::as_str).collect();
    // The existing shop layout shuffles ordinary goods in every enabled mode,
    // even when the rolled item happens to equal its vanilla item.
    if plan.shops.on() { names.extend(seed.shops.keys().map(String::as_str)); }
    else if !seed.shops.is_empty() { return Err("disabled shop shuffle has native shelf placements".into()); }
    let mut out = Vec::new();
    for name in names {
        let mut descriptor = catalogue.get(name).cloned()
            .ok_or_else(|| format!("native randomized source has no network descriptor: {name}"))?;
        let reward = seed.shops.get(name).map(|s| s.item.as_str()).or_else(|| seed.placements.get(name).map(String::as_str))
            .ok_or("network source has no generated reward")?;
        descriptor = descriptor.with("generated_item", reward.into());
        if let Some(shop) = seed.shops.get(name) {
            descriptor = descriptor.with("price", shop.price.into()).with("deal", shop.deal.into());
        }
        out.push((name.to_string(), descriptor));
    }
    Ok(Json::Obj(out))
}

/// The native fill deliberately allows optional rewards outside its progression
/// proof. Keep these locations explicit instead of silently leaving them local
/// or pretending that an arbitrary missing sphere is safe.
pub(super) fn optional_reason(name: &str) -> Option<&'static str> {
    Some(match name {
        "Colossus Freestanding PoH" | "DMC Volcano Freestanding PoH" | "DMT Freestanding PoH" =>
            "The native logic requires a planted bean route that this rolled world did not prove.",
        "LW GS Above Theater" | "ZR GS Near Raised Grottos" =>
            "The native conservative Skulltula rule requires a bean route that this rolled world did not prove.",
        "Kak 100 Gold Skulltula Reward" =>
            "The native search did not prove all one hundred tokens with its mapped token sources.",
        "LW Ocarina Memory Game" =>
            "The native imported rule requires individual ocarina-button items that the remake does not shuffle.",
        _ => return None,
    })
}

pub fn optional_sources(seed: &SeedFile, spheres: &[Vec<(String, String)>]) -> Result<Json> {
    let proven: BTreeSet<&str> = spheres.iter().flatten().map(|(name, _)| name.as_str()).collect();
    let selected = selected(seed)?;
    let mut optional = Vec::new();
    for (name, _) in selected.as_obj().ok_or("native sources are not an object")? {
        if proven.contains(name.as_str()) { continue; }
        let reason = optional_reason(name).ok_or_else(||
            format!("native randomized source has no access proof or known optional rule: {name}"))?;
        optional.push((name.clone(), Json::obj().with("reason", reason.into())));
    }
    Ok(Json::Obj(optional))
}

#[cfg(test)]
mod tests {
    use super::*;
    use ootrr_core::settings::{Settings, Value};
    use ootrr_core::settings::seed::ShopEntry;

    fn seed(pairs: &[(&str, &str)], settings: &Settings) -> SeedFile {
        SeedFile::new("source-contract", settings, &Data::load().unwrap().scan.game,
            pairs.iter().map(|(a, b)| (a.to_string(), b.to_string())).collect()).unwrap()
    }

    #[test]
    fn descriptors_cover_native_families_and_never_confuse_item_flags_with_checks() {
        let value = catalog().unwrap();
        assert_eq!(value.get("schema").and_then(Json::as_i64), Some(2));
        let sources = value.get("sources").unwrap();
        for name in ["KF Midos Top Left Chest", "Kak Anju as Child", "Song from Impa", "ToT Reward from Rauru",
            "KF Links House Cow", "Market Bombchu Bowling First Prize", "Kak 100 Gold Skulltula Reward",
            "Deku Tree Queen Gohma Heart", "KF House of Twins Pot 1", "KF Shop Item 1", "ZD Shop Item 8"] {
            assert!(sources.get(name).is_some(), "missing native source {name}");
        }
        let deku = sources.get("Deku Tree Map Chest").unwrap().get("placement").unwrap();
        assert_eq!(deku.get("dungeon").and_then(Json::as_str), Some("Deku Tree"));
        assert_eq!(deku.get("region_group").and_then(Json::as_str), Some("forest"));
        // Native adapter operations can legitimately test item ownership. Such
        // a test must never be exported as the source's collection identity.
        for (_, source) in sources.as_obj().unwrap() {
            assert!(source.get("grant_flags").is_none());
            assert!(source.get("check_flags").is_none());
            assert!(source.get("location_id").is_none());
            assert!(!source.get("collection").and_then(Json::as_str).unwrap().contains("IsGet"));
        }
    }

    #[test]
    fn selected_sources_equal_native_placements_and_keep_rewards_unchanged() {
        let native = seed(&[("KF Midos Top Left Chest", "Progressive Bomb Bag"), ("Song from Impa", "Rupees (20)"),
            ("KF House of Twins Pot 1", "Boomerang")], &Settings::default());
        let before = native.to_json();
        let resolved = selected(&native).unwrap();
        let rows = resolved.as_obj().unwrap();
        assert_eq!(rows.len(), native.placements.len());
        for (name, reward) in &native.placements {
            assert_eq!(resolved.get(name).unwrap().get("generated_item").and_then(Json::as_str), Some(reward.as_str()));
        }
        assert_eq!(native.to_json(), before);
        assert_eq!(resolved, selected(&native).unwrap());
    }

    #[test]
    fn native_mapping_precautions_remain_junk_only_for_every_network_owner() {
        let sources = source_map(&Data::load().unwrap()).unwrap();
        let guarded: BTreeSet<&str> = sources.iter().filter_map(|(name, source)| {
            source.get("placement").and_then(|p| p.get("junk_only"))
                .filter(|value| **value == Json::Bool(true)).map(|_| name.as_str())
        }).collect();
        assert_eq!(guarded.len(), 35);
        let mut settings = Settings::default();
        settings.set("shuffle_skulltulas", Value::s("matched")).unwrap();
        let plan = slice::support::plan(&settings).unwrap();
        let skulls: BTreeSet<&str> = sources.keys().map(String::as_str)
            .filter(|name| slice::junk_spots::only(&plan, name)).collect();
        assert_eq!(skulls.len(), 23);
        assert!(skulls.is_subset(&guarded));
        for name in slice::remake_overworld::UNSURE.into_iter().chain(slice::pickups::UNSURE)
            .chain(["Colossus Freestanding PoH", "DMC Volcano Freestanding PoH", "DMT Freestanding PoH"]) {
            assert!(guarded.contains(name), "native precaution lost for {name}");
        }
        assert!(!guarded.contains("KF Midos Top Left Chest"));
        assert!(!guarded.contains("KF GS Bean Patch"));
        assert!(!guarded.contains("Graveyard Dampe Race Freestanding PoH"));
        let native = seed(&[("Colossus GS Tree", "Rupees (20)"), ("KF Midos Top Left Chest", "Bow")], &settings);
        let resolved = selected(&native).unwrap();
        for (name, row) in resolved.as_obj().unwrap() {
            assert_eq!(row.get("placement"), sources[name].get("placement"));
        }
    }

    #[test]
    fn every_enabled_shop_good_is_a_source_even_without_special_deals() {
        let mut settings = Settings::default();
        settings.set("shuffle_shops", Value::s("shuffle")).unwrap();
        let mut native = seed(&[], &settings);
        for slot in &shops::table().unwrap().slots {
            native.shops.insert(slot.name.clone(), ShopEntry { item: slot.item.clone(), price: slot.price as i64,
                deal: false, pool: String::new() });
        }
        let sources = selected(&native).unwrap();
        assert_eq!(sources.as_obj().unwrap().len(), 64);
        assert_eq!(sources.get("KF Shop Item 8").unwrap().get("deal"), Some(&Json::Bool(false)));
    }

    #[test]
    fn unknown_sources_are_rejected_instead_of_becoming_unreported_local_rewards() {
        let native = seed(&[("A location not in this native game", "Rupees (5)")], &Settings::default());
        assert!(selected(&native).unwrap_err().to_string().contains("no network descriptor"));
    }

    #[test]
    fn multiage_variants_share_one_source_and_hashes_remain_lossless_strings() {
        let value = catalog().unwrap();
        let source = value.get("sources").unwrap().get("KF House of Twins Pot 1").unwrap();
        let variants = source.get("variants").unwrap().as_arr().unwrap();
        assert!(variants.len() >= 2);
        let mut files = BTreeSet::new();
        for variant in variants {
            files.insert(variant.get("file").and_then(Json::as_str).unwrap());
            let hash = variant.get("actor").and_then(Json::as_str).unwrap();
            assert!(hash.parse::<u64>().unwrap() > 0);
        }
        assert!(files.iter().any(|f| f.contains("_Child_")));
        assert!(files.iter().any(|f| f.contains("_Adult_")));
        assert_eq!(source.get("collection").and_then(Json::as_str), Some("pickup"));
    }

    #[test]
    fn disabled_shops_cannot_sneak_into_the_network_source_list() {
        let mut native = seed(&[], &Settings::default());
        native.shops.insert("KF Shop Item 8".into(), ShopEntry { item: "Buy Heart".into(), price: 5, deal: false, pool: String::new() });
        assert!(selected(&native).is_err());
    }

    #[test]
    fn every_source_selected_by_the_native_family_pickers_has_a_descriptor() {
        let mut settings = Settings::default();
        for (name, value) in [("shuffle_rewards", "supported"), ("shuffle_songs", "anywhere"),
            ("shuffle_skulltulas", "matched"), ("shuffle_pots", "all"), ("shuffle_crates", "all"),
            ("shuffle_rocks", "all"), ("shuffle_grass", "all"), ("shuffle_freestanding_items", "all"),
            ("shuffle_dungeon_rewards", "anywhere")] {
            settings.set(name, Value::s(value)).unwrap();
        }
        for name in ["shuffle_rewards_extra", "shuffle_cows", "shuffle_frog_songs", "shuffle_frog_bug_heart",
            "shuffle_boss_hearts", "shuffle_treasure_reward", "shuffle_beehives", "shuffle_potion_shop"] {
            settings.set(name, Value::Bool(true)).unwrap();
        }
        let plan = slice::support::plan(&settings).unwrap();
        let data = slice::treasure::with(Data::load().unwrap(), plan.treasure);
        let world = slice::logic::world_with(&data, &plan.logic()).unwrap();
        let picked = slice::pick::pick(&data, &world, &plan);
        let catalogue = source_map(&data).unwrap();
        assert!(picked.free.len() > 300);
        let absent: Vec<&str> = picked.free.iter().map(|id| world.locs[*id].name.as_str())
            .filter(|name| !catalogue.contains_key(*name)).collect();
        assert!(absent.is_empty(), "native selected sources without descriptors: {absent:?}");
    }

    #[test]
    fn generated_grants_have_structural_anchors_instead_of_unstable_event_numbers() {
        let catalogue = catalog().unwrap();
        let sources = catalogue.get("sources").unwrap();
        let cow = sources.get("KF Links House Cow").unwrap().get("post_build_grants").unwrap().as_arr().unwrap();
        assert!(cow.iter().any(|g| g.get("selector").and_then(Json::as_str) == Some("after_native_flag")));
        assert_eq!(cow.len(), 1, "the repeatable milk grant is not randomized");
        let trade = sources.get("Kak Anju as Adult").unwrap().get("post_build_grants").unwrap().as_arr().unwrap();
        assert!(trade.iter().any(|g| g.get("selector").and_then(Json::as_str) == Some("next_after_event")));
        assert_eq!(trade.len(), 1, "the original native quest grant is a different transaction");
    }

    #[test]
    fn optional_export_only_names_known_native_exceptions_without_inventing_spheres() {
        let native = seed(&[("Colossus Freestanding PoH", "Rupees (20)"), ("KF Midos Top Left Chest", "Bow")], &Settings::default());
        let proven = vec![vec![("KF Midos Top Left Chest".to_string(), String::new())]];
        let optional = optional_sources(&native, &proven).unwrap();
        assert_eq!(optional.as_obj().unwrap().len(), 1);
        assert!(optional.get("Colossus Freestanding PoH").unwrap().get("reason").is_some());
        assert!(optional_sources(&native, &[]).is_err(), "a missing ordinary chest must not become optional");
        assert_eq!(native.placements.len(), 2);
    }

    #[test]
    fn advancement_export_uses_conditional_native_world_flags() {
        let data = Data::load().unwrap();
        let ordinary = slice::logic::world_with(&data, &[]).unwrap();
        let heart_goal = slice::logic::world_with(&data, &[("bridge", "hearts")]).unwrap();
        let heart = ordinary.item("Heart Container").unwrap();
        assert!(!ordinary.items.adv[heart]);
        assert!(heart_goal.items.adv[heart_goal.item("Heart Container").unwrap()]);
        assert!(!ordinary.items.adv[ordinary.item("Rupees (5)").unwrap()]);
        assert!(ordinary.items.adv[ordinary.item("Bow").unwrap()]);
        assert!(ordinary.items.adv[ordinary.item("Buy Blue Fire").unwrap()]);
    }

    #[test]
    fn held_heart_piece_locations_are_real_native_chests_when_game_files_are_available() {
        let Some(root) = std::env::var_os("OOTRR_ROMFS") else { return; };
        let mut game = ootrr_core::romfs::Romfs::open(std::path::Path::new(&root)).unwrap();
        let sources = source_map(&Data::load().unwrap()).unwrap();
        for (name, _) in slice::pickups::HELD {
            let source = sources.get(name).unwrap();
            for variant in source.get("variants").unwrap().as_arr().unwrap() {
                let file = super::super::field(variant, "file").unwrap();
                let hash = super::super::field(variant, "actor").unwrap().parse::<u64>().unwrap();
                let y = game.read_byml(file).unwrap();
                let found: Vec<_> = y.root.get("Actors").unwrap().as_arr().unwrap().iter()
                    .filter(|a| ootrr_core::placement::hash_of(a) == Some(hash)).collect();
                assert_eq!(found.len(), 1, "{name} in {file}");
                let gyaml = found[0].get("Gyaml").and_then(ootrr_core::byml::Node::as_str).unwrap();
                assert!(gyaml.starts_with("Obj_TBox") || ["Obj_HrlCity_Shop_TBox_A_01", "Obj_HrlCity_Shop_TBox_A_02"].contains(&gyaml), "{name} is {gyaml}, not a native chest");
            }
        }
    }

    #[test]
    fn every_exported_chest_is_a_real_chest_in_each_native_map_when_available() {
        let Some(root) = std::env::var_os("OOTRR_ROMFS") else { return; };
        let mut game = ootrr_core::romfs::Romfs::open(std::path::Path::new(&root)).unwrap();
        let sources = source_map(&Data::load().unwrap()).unwrap();
        let mut maps = BTreeMap::new();
        let mut count = 0;
        for (name, source) in &sources {
            if source.get("kind").and_then(Json::as_str) != Some("chest") { continue; }
            count += 1;
            for variant in source.get("variants").unwrap().as_arr().unwrap() {
                let file = super::super::field(variant, "file").unwrap();
                if !maps.contains_key(file) { maps.insert(file.to_string(), game.read_byml(file).unwrap()); }
                let hash = super::super::field(variant, "actor").unwrap().parse::<u64>().unwrap();
                let y = maps.get(file).unwrap();
                let found: Vec<_> = y.root.get("Actors").unwrap().as_arr().unwrap().iter()
                    .filter(|a| ootrr_core::placement::hash_of(a) == Some(hash)).collect();
                assert_eq!(found.len(), 1, "{name} in {file}");
                let gyaml = found[0].get("Gyaml").and_then(ootrr_core::byml::Node::as_str).unwrap();
                assert!(gyaml.starts_with("Obj_TBox") || ["Obj_HrlCity_Shop_TBox_A_01", "Obj_HrlCity_Shop_TBox_A_02"].contains(&gyaml), "{name} is {gyaml}, not a native chest");
            }
        }
        assert!(count >= 128);
    }
}
