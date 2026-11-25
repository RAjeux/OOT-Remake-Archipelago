//! Room-bound Gold Skulltula drops using OOTRR's native pickup kit.
//!
//! Killing the enemy never completes the location. The unmodified token kit
//! writes its permanent enemy rows only after the pickup's get event finishes.
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::Path;

use ootrr_core::byml::{Byml, Node};
use ootrr_core::json::Json;
use ootrr_core::pickup_pack::{self, kit, model, rows, Layers, Spec, Style, BASE, DONOR};
use ootrr_core::romfs::Romfs;
use ootrr_core::rsizetable::{self, Rst};
use ootrr_core::{modpack, sarc, zs};

use super::{field, read_overlay, Result};

#[derive(Clone, Debug)]
struct Job {
    actor: String,
    pickup: String,
    hash: u64,
    files: Vec<String>,
    native_actor: Option<String>,
}

fn jobs(j: &Json) -> Result<Vec<Job>> {
    let records = j.get("skulls").and_then(Json::as_arr).ok_or("missing skulltula jobs")?;
    let mut hashes = BTreeSet::new();
    let mut actors = BTreeSet::new();
    let mut out = Vec::new();
    for row in records {
        let actor = field(row, "actor")?;
        let pickup = field(row, "pickup")?;
        let hash = field(row, "hash")?.parse::<u64>()?;
        if !actor.starts_with("Item_AP_") || !pickup_pack::is_actor_name(actor)
            || !pickup.starts_with("Obj_AP_") || !pickup.ends_with("_GH")
            || !pickup_pack::is_actor_name(pickup) || hash == 0
            || !hashes.insert(hash) || !actors.insert(actor.to_string()) {
            return Err("each AP skulltula needs a unique enemy hash and pickup identity".into());
        }
        let mut files = BTreeSet::new();
        for file in row.get("files").and_then(Json::as_arr).ok_or("missing skulltula maps")? {
            let file = file.as_str().ok_or("invalid skulltula map")?;
            modpack::rel(file)?;
            if !file.starts_with("Banc/") || !file.ends_with(".bcett.byml.zs") {
                return Err("unexpected skulltula map".into());
            }
            files.insert(file.to_string());
        }
        if files.is_empty() { return Err("skulltula has no map".into()); }
        let native_actor = row.get("native_actor").and_then(Json::as_str).map(str::to_string);
        if let Some(native) = &native_actor {
            if !pickup_pack::is_actor_name(native) || native.starts_with("Item_AP_")
                || row.get("local_item").and_then(Json::as_str).is_none() {
                return Err("invalid native skulltula reward".into());
            }
        } else if row.get("local_item").is_some() {
            return Err("local skulltula reward has no native actor".into());
        }
        out.push(Job { actor: actor.to_string(), pickup: pickup.to_string(), hash,
                       files: files.into_iter().collect(), native_actor });
    }
    Ok(out)
}

pub(super) fn donor(actor: &str) -> &str {
    if actor.starts_with("Item_Melody_") { return "Dm_Item_Sheik_Harp"; }
    match actor {
        "Item_Ocarina_Fairy" => "Dm_Item_Ocarina_Fairy",
        "Item_Ocarina_Time" => "Obj_Ocarina_Time",
        _ => actor,
    }
}

pub(super) fn pickup_input(mut pack: Vec<sarc::Entry>, actor: &str) -> Result<Vec<sarc::Entry>> {
    // AP chest models carry a custom presentation AINB. A physical pickup
    // uses Obj_Item_Base's authored PouchContent performer instead. The kit
    // copies only the reachable parameter closure, so this discarded chest
    // performer and its graph must not be imported into the pickup actor.
    let path = ootrr_core::pickup_pack::closure::actor_file(actor);
    let root = pack.iter_mut().find(|entry| entry.name == path).ok_or("AP pickup input has no actor")?;
    let mut y = Byml::parse(&root.data)?;
    y.root.get_mut("Components").ok_or("AP pickup input has no components")?.remove("EventPerformerRef");
    root.data = y.write()?;
    Ok(pack)
}

pub(super) fn display_row(target: &mut Node, native: &Node) -> Result<()> {
    let category = native.get("PouchCategory").and_then(Node::as_str).ok_or("native reward has no pouch category")?;
    let get_type = native.get("PouchGetType").and_then(Node::as_str).unwrap_or("Small");
    target.set("PouchCategory", Node::Str(category.to_string()));
    target.set("PouchGetType", Node::Str(get_type.to_string()));
    Ok(())
}

pub(super) fn display_kit(plan: &mut ootrr_core::pickup_pack::build::Plan, native: &Node) -> Result<()> {
    // This new, unique leaf carries display metadata only. Keep its AP pouch
    // identity, neutral special-deal handling and token persistence untouched.
    // Never edit the shared KeyItemDefault component carried by the AP source.
    let path = ootrr_core::pickup_pack::actor::pouch_file(&plan.spec.name);
    let mut entries = sarc::parse(&plan.sarc)?;
    let leaf = entries.iter_mut().find(|entry| entry.name == path).ok_or("AP kit has no pouch leaf")?;
    let mut y = Byml::parse(&leaf.data)?;
    for (column, parameter, fallback) in [("PouchCategory", "Category", "KeyItem"),
                                          ("PouchGetType", "GetType", "Small")] {
        let value = native.get(column).and_then(Node::as_str).unwrap_or(fallback);
        y.root.set(parameter, Node::U32(ootrr_core::murmur::murmur3_32(value.as_bytes(), 0)));
    }
    leaf.data = y.write()?;
    let size = plan.fresh.iter_mut().find(|(name, _)| *name == path).ok_or("AP kit pouch is not fresh")?;
    size.1 = leaf.data.len();
    plan.sarc = sarc::write(&entries)?;
    Ok(())
}

pub(super) fn write(overlay: &Path, path: &str, raw: &[u8], dictionary: Option<u32>) -> Result<()> {
    let target = overlay.join(modpack::rel(path)?);
    fs::create_dir_all(target.parent().ok_or("invalid skulltula output")?)?;
    fs::write(target, zs::compress_raw(raw, dictionary)?)?;
    Ok(())
}

pub(super) fn run(j: &Json) -> Result<()> {
    run_at(j, Path::new("/game"), Path::new("/mod"))
}

fn run_at(j: &Json, game_path: &Path, overlay: &Path) -> Result<()> {
    let jobs = jobs(j)?;
    if jobs.is_empty() { println!("No AP skulltula drops."); return Ok(()); }
    let mut game = Romfs::open(game_path)?;
    kit::world(&mut game)?;
    kit::clean_base(&game, Some(&overlay.to_path_buf()))?;
    let saved = ootrr_core::pickup_persist::rows(&mut game)?;
    for job in &jobs {
        if [job.hash, job.hash ^ 2].iter().any(|hash| !ootrr_core::pickup_persist::kept(&saved, *hash)) {
            return Err(format!("skulltula {} has no permanent pickup rows", job.hash).into());
        }
    }
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
        let look = donor(job.native_actor.as_deref().unwrap_or(&job.actor));
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
        if let Some(native_actor) = &job.native_actor {
            let native = rows::need(&tables[2].3, native_actor, rows::POUCH_INFO)?.clone();
            display_kit(&mut plan, &native)?;
            let mut item = rows::need(&tables[2].3, &job.actor, rows::POUCH_INFO)?.clone();
            display_row(&mut item, &native)?;
            rows::insert(&mut tables[2].3, item)?;
        }
        kit::verify(&sarc::parse(&plan.sarc)?, &job.pickup, &token)?;
        let heap = rows::heap(&tables[0].3, &job.actor)?.max(rows::heap(&tables[0].3, look)?);
        let mut actor = rows::actor_row(rows::need(&tables[0].3, &job.actor, rows::ACTOR_INFO)?, &job.pickup, heap);
        model::row(&mut actor, rows::need(&tables[0].3, look, rows::ACTOR_INFO)?)?;
        let game_row = rows::game_row(rows::need(&tables[1].3, kit::TOKEN, rows::GAME_ACTOR_INFO)?,
                                     rows::need(&tables[1].3, if job.native_actor.is_some() { look } else { &job.actor },
                                                rows::GAME_ACTOR_INFO)?, &job.pickup);
        let pouch = rows::pouch_row(rows::need(&tables[2].3, &job.actor, rows::POUCH_INFO)?, &job.pickup);
        let a = rows::insert(&mut tables[0].3, actor)?;
        let b = rows::insert(&mut tables[1].3, game_row)?;
        rows::insert(&mut tables[2].3, pouch)?;
        if a != b { return Err("AP pickup actor tables no longer align".into()); }
        kit::fresh_sizes(&mut rst, &plan, &shared)?;
        plans.push(plan);
    }
    let mut maps: BTreeMap<String, Vec<&Job>> = BTreeMap::new();
    for job in &jobs { for file in &job.files { maps.entry(file.clone()).or_default().push(job); } }
    let mut changed = Vec::new();
    let mut found = BTreeSet::new();
    for (file, jobs) in maps {
        let (raw, dict) = read_overlay(&mut game, overlay, &file)?;
        let mut y = Byml::parse(&raw)?;
        for job in jobs {
            let n = ootrr_core::slice::skull_edit::set_drop(&mut y, job.hash, &job.pickup)?;
            if n > 1 { return Err("duplicate AP skulltula hash in one map".into()); }
            if n == 1 { found.insert(job.hash); }
        }
        let out = y.write()?;
        rst.grow(&file, raw.len() as u64, out.len() as u64, ootrr_core::slice::edit::MARGIN)?;
        changed.push((file, out, dict));
    }
    if jobs.iter().any(|job| !found.contains(&job.hash)) { return Err("AP skulltula was not found in its maps".into()); }
    for plan in plans { write(overlay, &pickup_pack::pack_of(&plan.spec.name), &plan.sarc, Some(pickup_pack::PACK_DICT))?; }
    for (path, raw, dict, y) in tables {
        let out = y.write()?;
        rst.grow(path, raw.len() as u64, out.len() as u64, ootrr_core::slice::edit::MARGIN)?;
        write(overlay, path, &out, dict)?;
    }
    for (path, raw, dict) in changed { write(overlay, &path, &raw, dict)?; }
    write(overlay, rsizetable::TABLE_PATH, &rst.write()?, rst_dict)?;
    println!("Prepared {} AP skulltula drops with native pickup-only persistence.", jobs.len());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn unique_skull_jobs_reject_aliases_and_unsafe_files() {
        let row = Json::obj().with("actor", "Item_AP_abcdef".into())
            .with("pickup", "Obj_AP_abcdef_GH".into()).with("hash", "1234".into())
            .with("files", Json::strs(["Banc/Area/Map.bcett.byml.zs"]));
        assert_eq!(jobs(&Json::obj().with("skulls", Json::Arr(vec![row.clone()]))).unwrap().len(), 1);
        for values in [vec![row.clone(), row.clone()], vec![row.clone().with("pickup", "../bad".into())],
                       vec![row.clone().with("files", Json::strs(["Banc/../bad.bcett.byml.zs"]))],
                       vec![row.with("local_item", "Bow".into())]] {
            assert!(jobs(&Json::obj().with("skulls", Json::Arr(values))).is_err());
        }
        assert_eq!(donor("Item_Melody_FireBolero"), "Dm_Item_Sheik_Harp");
        assert_eq!(donor("Item_Ocarina_Fairy"), "Dm_Item_Ocarina_Fairy");
    }

    #[test]
    fn real_skull_pickup_kit_resources_keep_native_collect_only_persistence() {
        let Some(game) = std::env::var_os("OOTRR_ROMFS") else { return; };
        let Some(stage) = std::env::var_os("OOTRR_AP_SKULL_STAGE") else { return; };
        let Some(job_file) = std::env::var_os("OOTRR_AP_SKULL_JOBS") else { return; };
        let raw = fs::read_to_string(job_file).unwrap();
        let j = ootrr_core::json::parse(&raw).unwrap();
        run_at(&j, Path::new(&game), Path::new(&stage)).unwrap();
    }
}
