//! Native world pickup packs for the selected AP sources.
//!
//! This pass only changes physical rewards. In particular, destroying a pot
//! never sends a check or writes the AP collection bool. The caller installs
//! the guarded native reward callback and source presence/persistence policy.
use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

use ootrr_core::byml::{Byml, Node};
use ootrr_core::json::Json;
use ootrr_core::pickup_pack::{self, kit, model, rows, Layers, Spec, Style, BASE, DONOR};
use ootrr_core::placement::hash_of;
use ootrr_core::romfs::Romfs;
use ootrr_core::rsizetable::{self, Rst};
use ootrr_core::slice::data::Data;
use ootrr_core::{murmur, sarc};

use super::ap_skulls::{display_kit, display_row, donor, pickup_input, write};
use super::{field, network_sources, read_overlay, Result};

#[derive(Clone, Debug)]
struct Variant {
    file: String,
    hash: u64,
    via: String,
    expected: String,
}

#[derive(Clone, Debug)]
struct Job {
    name: String,
    kind: String,
    native_kind: String,
    actor: String,
    pickup: String,
    display: String,
    variants: Vec<Variant>,
}

fn jobs(input: &Json) -> Result<Vec<Job>> {
    let canonical = network_sources::source_map(&Data::load()?)?;
    let records = input.get("records").or_else(|| input.get("sources")).and_then(Json::as_arr)
        .ok_or("missing network source pickup records")?;
    let mut seen_names = BTreeSet::new();
    let mut seen_actors = BTreeSet::new();
    let mut seen_flags = BTreeSet::new();
    let mut seen_variants = BTreeSet::new();
    let mut out = Vec::new();
    for record in records {
        let name = field(record, "name")?;
        let source = canonical.get(name).ok_or_else(|| format!("unknown native network source {name}"))?;
        let kind = field(source, "kind")?;
        if !["pickup", "container", "skull"].contains(&kind) {
            return Err(format!("network source {name} is not a native world pickup").into());
        }
        let supplied = record.get("metadata").ok_or("network source has no trusted metadata")?;
        for (key, value) in source.as_obj().ok_or("invalid native source metadata")? {
            if supplied.get(key) != Some(value) {
                return Err(format!("network source {name} has changed native metadata field {key}").into());
            }
        }
        let actor = field(record, "actor")?;
        let pickup = field(record, "pickup")?;
        let display = field(record, "display_actor")?;
        let flag = field(record, "flag_name")?;
        let flag_hash = record.get("flag_hash").and_then(Json::as_i64).and_then(|v| u32::try_from(v).ok())
            .ok_or("network source has no collection flag hash")?;
        if !actor.starts_with("Item_AP_") || !pickup_pack::is_actor_name(actor)
            || !pickup.starts_with("Obj_AP_") || !pickup.ends_with("_GH") || !pickup_pack::is_actor_name(pickup)
            || !pickup_pack::is_actor_name(display) || flag.is_empty() || flag.len() > 256
            || !flag.starts_with("Archipelago.Source.") || murmur::murmur3_32(flag.as_bytes(), 0) != flag_hash
            || !seen_names.insert(name.to_string()) || !seen_actors.insert(actor.to_string())
            || !seen_actors.insert(pickup.to_string()) || !seen_flags.insert(flag_hash) {
            return Err("each native network pickup needs a distinct valid identity and collection flag".into());
        }
        let mut variants = Vec::new();
        for row in source.get("variants").and_then(Json::as_arr).ok_or("native pickup has no map variants")? {
            let variant = Variant { file: field(row, "file")?.to_string(), hash: field(row, "actor")?.parse()?,
                via: field(row, "via")?.to_string(), expected: field(row, "expected_actor")?.to_string() };
            if !seen_variants.insert((variant.file.clone(), variant.hash)) {
                return Err("two network sources claim the same physical pickup variant".into());
            }
            variants.push(variant);
        }
        if variants.is_empty() { return Err("native pickup has no map variants".into()); }
        out.push(Job { name: name.to_string(), kind: kind.to_string(), native_kind: field(source, "native_kind")?.to_string(),
            actor: actor.to_string(), pickup: pickup.to_string(), display: display.to_string(), variants });
    }
    Ok(out)
}

fn map_actor(y: &mut Byml, hash: u64) -> Result<&mut Node> {
    let actors = y.root.get_mut("Actors").and_then(Node::as_arr_mut).ok_or("network source map has no actors")?;
    let mut matching = actors.iter_mut().filter(|actor| hash_of(actor) == Some(hash));
    let actor = matching.next().ok_or_else(|| format!("network source actor {hash} is absent from its map"))?;
    if matching.next().is_some() { return Err("network source hash occurs twice in one map".into()); }
    Ok(actor)
}

fn validate_original(y: &mut Byml, job: &Job, variant: &Variant) -> Result<()> {
    let actor = map_actor(y, variant.hash)?;
    let gyaml = actor.get("Gyaml").and_then(Node::as_str).ok_or("native source actor has no class")?;
    if job.kind == "skull" {
        if gyaml != "Enemy_Skulltula_Gold" { return Err("native Skulltula source has another actor class".into()); }
    } else if job.kind == "container" {
        let kind = ootrr_core::pot_slice::data::Kind::of(&job.native_kind).ok_or("unknown native container kind")?;
        if !kind.gyaml(gyaml) { return Err(format!("native container {} has unexpected class {gyaml}", job.name).into()); }
    } else if variant.via != "actor" || gyaml != variant.expected {
        return Err(format!("native pickup {} has unexpected class {gyaml}", job.name).into());
    }
    Ok(())
}

fn replace(y: &mut Byml, job: &Job, variant: &Variant) -> Result<()> {
    let actor = map_actor(y, variant.hash)?;
    if job.kind == "pickup" {
        // OOTRR may have replaced a boss heart with a chest when its local
        // reward lacked a ground actor. The AP pickup restores the authored
        // source position and presence; it has a world actor for every reward.
        actor.set("Gyaml", Node::Str(job.pickup.clone()));
        if let Some(dynamic) = actor.get_mut("Dynamic") {
            for key in ["Drop__DropActor", "Drop__DropActor_Substitute", "GetEventName", "DropViewActor"] { dynamic.remove(key); }
        }
    } else {
        if job.kind == "container" {
            let gyaml = actor.get("Gyaml").and_then(Node::as_str).ok_or("staged container has no class")?;
            let kind = ootrr_core::pot_slice::data::Kind::of(&job.native_kind).ok_or("unknown native container kind")?;
            if !kind.gyaml(gyaml) { return Err(format!("staged container {} changed actor class", job.name).into()); }
        } else if actor.get("Gyaml").and_then(Node::as_str) != Some("Enemy_Skulltula_Gold") {
            return Err("staged Skulltula changed actor class".into());
        }
        if actor.get("Dynamic").is_none() { actor.set("Dynamic", Node::Map(Vec::new())); }
        let dynamic = actor.get_mut("Dynamic").ok_or("network source has no drop parameters")?;
        dynamic.set("Drop__DropActor", Node::Str(job.pickup.clone()));
        if dynamic.get("Drop__DropActor_Substitute").is_some() {
            dynamic.set("Drop__DropActor_Substitute", Node::Str(job.pickup.clone()));
        }
        if ["rock", "grass"].contains(&job.native_kind.as_str()) { dynamic.remove("Drop__DropTable"); }
    }
    Ok(())
}

pub fn run(input: &Json) -> Result<()> { run_at(input, Path::new("/game"), Path::new("/mod")) }

fn run_at(input: &Json, game_path: &Path, overlay: &Path) -> Result<()> {
    let jobs = jobs(input)?;
    if jobs.is_empty() { println!("No native network pickup sources."); return Ok(()); }
    let mut game = Romfs::open(game_path)?;
    kit::world(&mut game)?;
    kit::clean_base(&game, Some(&overlay.to_path_buf()))?;
    let token = kit::token_pack(&mut game)?;
    let shared = kit::shared_files(&token)?;
    let (raw_rst, rst_dict) = read_overlay(&mut game, overlay, rsizetable::TABLE_PATH)?;
    let mut rst = Rst::parse(&raw_rst)?;
    let mut tables = Vec::new();
    for path in [rows::ACTOR_INFO, rows::GAME_ACTOR_INFO, rows::POUCH_INFO] {
        let (raw, dict) = read_overlay(&mut game, overlay, path)?;
        tables.push((path, raw.clone(), dict, Byml::parse(&raw)?));
    }
    let mut plans = Vec::new();
    for job in &jobs {
        let look = donor(&job.display);
        let mut packs = Vec::new();
        for name in BTreeSet::from([BASE, DONOR, job.actor.as_str(), look]) {
            let (raw, _) = read_overlay(&mut game, overlay, &pickup_pack::pack_of(name))?;
            let pack = sarc::parse(&raw)?;
            packs.push(if name == job.actor { pickup_input(pack, &job.actor)? } else { pack });
        }
        packs.push(token.clone());
        let spec = Spec { item: job.actor.clone(), name: job.pickup.clone(), style: Style::Touch, heap: None };
        let layers = Layers { model: Some(look.to_string()), ..Layers::default() };
        let mut plan = kit::plan_with(&packs, &spec, &layers)?;
        let native = rows::need(&tables[2].3, &job.display, rows::POUCH_INFO)?.clone();
        display_kit(&mut plan, &native)?;
        let mut item = rows::need(&tables[2].3, &job.actor, rows::POUCH_INFO)?.clone();
        display_row(&mut item, &native)?;
        rows::insert(&mut tables[2].3, item)?;
        kit::verify(&sarc::parse(&plan.sarc)?, &job.pickup, &token)?;
        let heap = rows::heap(&tables[0].3, &job.actor)?.max(rows::heap(&tables[0].3, look)?);
        let mut actor = rows::actor_row(rows::need(&tables[0].3, &job.actor, rows::ACTOR_INFO)?, &job.pickup, heap);
        model::row(&mut actor, rows::need(&tables[0].3, look, rows::ACTOR_INFO)?)?;
        let game_row = rows::game_row(rows::need(&tables[1].3, kit::TOKEN, rows::GAME_ACTOR_INFO)?,
            rows::need(&tables[1].3, look, rows::GAME_ACTOR_INFO)?, &job.pickup);
        let pouch = rows::pouch_row(rows::need(&tables[2].3, &job.actor, rows::POUCH_INFO)?, &job.pickup);
        let a = rows::insert(&mut tables[0].3, actor)?;
        let b = rows::insert(&mut tables[1].3, game_row)?;
        rows::insert(&mut tables[2].3, pouch)?;
        if a != b { return Err("network pickup actor tables no longer align".into()); }
        kit::fresh_sizes(&mut rst, &plan, &shared)?;
        plans.push(plan);
    }
    let mut maps: BTreeMap<&str, Vec<(&Job, &Variant)>> = BTreeMap::new();
    for job in &jobs { for variant in &job.variants { maps.entry(&variant.file).or_default().push((job, variant)); } }
    let mut changed = Vec::new();
    for (file, jobs) in maps {
        let mut original = Byml::parse(&game.read_zs(file)?)?;
        let (raw, dictionary) = read_overlay(&mut game, overlay, file)?;
        let mut staged = Byml::parse(&raw)?;
        for (job, variant) in jobs {
            validate_original(&mut original, job, variant)?;
            replace(&mut staged, job, variant)?;
        }
        let output = staged.write()?;
        rst.grow(file, raw.len() as u64, output.len() as u64, ootrr_core::slice::edit::MARGIN)?;
        changed.push((file.to_string(), output, dictionary));
    }
    // No file is published until every native identity, pack and table passed.
    for plan in plans { write(overlay, &pickup_pack::pack_of(&plan.spec.name), &plan.sarc, Some(pickup_pack::PACK_DICT))?; }
    for (path, raw, dictionary, y) in tables {
        let output = y.write()?;
        rst.grow(path, raw.len() as u64, output.len() as u64, ootrr_core::slice::edit::MARGIN)?;
        write(overlay, path, &output, dictionary)?;
    }
    for (path, raw, dictionary) in changed { write(overlay, &path, &raw, dictionary)?; }
    write(overlay, rsizetable::TABLE_PATH, &rst.write()?, rst_dict)?;
    println!("Prepared {} native network pickup sources; collection callbacks own their AP flags.", jobs.len());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn record(name: &str) -> Json {
        let catalogue = network_sources::source_map(&Data::load().unwrap()).unwrap();
        let flag = "Archipelago.Source.123";
        Json::obj().with("name", name.into()).with("actor", "Item_AP_Source_123".into())
            .with("pickup", "Obj_AP_Source_123_GH".into()).with("display_actor", "Item_AP_Source_123".into())
            .with("flag_name", flag.into()).with("flag_hash", (murmur::murmur3_32(flag.as_bytes(), 0) as i64).into())
            .with("metadata", catalogue.get(name).unwrap().clone())
    }
    fn input(records: Vec<Json>) -> Json { Json::obj().with("records", Json::Arr(records)) }

    #[test]
    fn physical_jobs_are_bound_to_the_native_catalogue_and_distinct_source_flags() {
        let row = record("KF House of Twins Pot 1");
        assert_eq!(jobs(&input(vec![row.clone()])).unwrap().len(), 1);
        assert!(jobs(&input(vec![row.clone(), row.clone()])).is_err());
        assert!(jobs(&input(vec![row.clone().with("flag_hash", 0_i64.into())])).is_err());
        assert!(jobs(&input(vec![row.with("metadata", Json::obj())])).is_err());
        assert!(jobs(&input(vec![record("KF Midos Top Left Chest")])).is_err());
    }

    #[test]
    fn breaking_container_replacement_never_writes_a_collection_flag() {
        let job = jobs(&input(vec![record("KF House of Twins Pot 1")])).unwrap().remove(0);
        let variant = &job.variants[0];
        let flag = Node::Map(vec![("Gyaml".into(), Node::Str("Obj_Pot_A_01".into())),
            ("Hash".into(), Node::U64(variant.hash)), ("Dynamic".into(), Node::Map(vec![("Keep".into(), Node::Bool(true))]))]);
        let mut y = Byml { root: Node::Map(vec![("Actors".into(), Node::Arr(vec![flag]))]), version: 2, big: false };
        validate_original(&mut y, &job, variant).unwrap();
        replace(&mut y, &job, variant).unwrap();
        let actor = map_actor(&mut y, variant.hash).unwrap();
        assert_eq!(actor.get("Dynamic").unwrap().get("Drop__DropActor").and_then(Node::as_str), Some(job.pickup.as_str()));
        assert_eq!(actor.get("Dynamic").unwrap().get("Keep"), Some(&Node::Bool(true)));
        assert!(actor.get("Presence").is_none());
        assert!(!format!("{actor:?}").contains("Archipelago.Source"));
    }
}
