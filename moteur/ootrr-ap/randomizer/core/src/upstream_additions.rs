//! Selected OOTRR nightly changes, applied after the pinned 0.8.1 builder.
//!
//! This pass is explicitly selected by a new room's feature envelope. It never
//! reinterprets old seed settings, imports the upstream AP client, or changes
//! the existing reward/receipt protocol.

use std::fs;
use std::path::Path;

use crate::byml::Byml;
use crate::error::{Error, Res};
use crate::json::Json;
use crate::qol;
use crate::romfs::Romfs;
use crate::rsizetable::{self, Rst};
use crate::staging::{self, Out};

pub const SCHEMA: i64 = 1;

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Options {
    pub dungeon_key_tracker: bool,
    pub dpad_gear_cycle: bool,
    pub free_scarecrow: bool,
    pub skip_tower_escape: bool,
    pub skulls_by_day: bool,
    pub night_skulls_suns_song: bool,
    pub fishing_any_fish: bool,
    pub faster_ocarina_minigame: bool,
    pub dampe_one_race: bool,
    pub dampe_first_dig: bool,
    pub disable_low_health_warnings: bool,
    pub owl_warps: bool,
    pub shuffle_ice_traps: bool,
    pub skip_area_intros: bool,
}

impl Options {
    pub fn read(features: &Json) -> Res<Self> {
        if features.get("schema").and_then(Json::as_i64) != Some(SCHEMA) {
            return Err(Error::Format("upstream features: unsupported schema"));
        }
        let settings = features.get("settings").filter(|j| j.as_obj().is_some())
            .ok_or(Error::Format("upstream features: missing settings object"))?;
        let flag = |name: &str| match settings.get(name) {
            None => Ok(false),
            Some(Json::Bool(v)) => Ok(*v),
            _ => Err(Error::Msg(format!("upstream features: {name} must be a boolean"))),
        };
        Ok(Self {
            dungeon_key_tracker: flag("dungeon_key_tracker")?,
            dpad_gear_cycle: flag("dpad_gear_cycle")?,
            free_scarecrow: flag("free_scarecrow")?,
            skip_tower_escape: flag("skip_tower_escape")?,
            skulls_by_day: flag("skulls_by_day")?,
            night_skulls_suns_song: flag("night_skulls_suns_song")?,
            fishing_any_fish: flag("fishing_any_fish")?,
            faster_ocarina_minigame: flag("faster_ocarina_minigame")?,
            dampe_one_race: flag("dampe_one_race")?,
            dampe_first_dig: flag("dampe_first_dig")?,
            disable_low_health_warnings: flag("disable_low_health_warnings")?,
            owl_warps: flag("owl_warps")?,
            shuffle_ice_traps: flag("shuffle_ice_traps")?,
            skip_area_intros: flag("skip_area_intros")?,
        })
    }
}

fn frame(rf: &Romfs, work: &Path, path: &str) -> Res<Vec<u8>> {
    let file = work.join(crate::modpack::rel(path)?);
    if file.is_file() { Ok(fs::read(file)?) } else { rf.read(path) }
}

fn preload(rf: &mut Romfs, outs: &mut Vec<Out>, work: &Path, path: &str) -> Res<()> {
    if outs.iter().any(|o| o.path == path) || !work.join(crate::modpack::rel(path)?).is_file() {
        return Ok(());
    }
    let z = frame(rf, work, path)?;
    let n = rf.zs.decompress(&z)?.len();
    outs.push(Out { path: path.to_string(), z, old: n, new: n });
    Ok(())
}

pub fn stage(rf: &mut Romfs, work: &Path, opts: &Options,
             key_caps: Option<&[u32]>) -> Res<Vec<Out>> {
    let have = |path: &str| fs::read(work.join(path)).ok();
    let mut outs = qol::stage(rf, &qol::Opts {
        owls: opts.owl_warps, gear_cycle: opts.dpad_gear_cycle,
        low_health: opts.disable_low_health_warnings, ..Default::default()
    }, &have)?;

    // These native repairs are tied to the new room schema, independently of
    // optional convenience settings. Reuse the builder's existing choices.
    // The modern graph permits tunic purchases as child, including when shop
    // shuffle is off and the AP shelf factory therefore does not run.
    staging::edit_staged(rf, &mut outs, work, crate::shelf::hook::FLOW, true,
        |raw| crate::shelf::hook::edit(raw, &[], true))?;
    crate::story_skip::stage_late(rf, &mut outs, work, qol::navi_return::FLOW,
        |b| qol::navi_return::repair_generated_safety(b).map(|_| ()))?;
    crate::field_palette::stage(rf, &mut outs, work)?;
    crate::lake_tree_wall::stage(rf, &mut outs, work)?;

    if opts.free_scarecrow {
        crate::story_skip::stage_late(rf, &mut outs, work, qol::scarecrow::FLOW, qol::scarecrow::patch_flow)?;
    }
    if opts.skip_tower_escape {
        crate::story_skip::stage_late(rf, &mut outs, work, qol::tower_escape::FLOW, qol::tower_escape::patch_flow)?;
        staging::edit_staged(rf, &mut outs, work, qol::tower_escape::ANCHOR_FILE, true, |raw| {
            let mut y = Byml::parse(raw)?;
            if qol::tower_escape::patch_anchor(&mut y) == 0 {
                return Err(Error::Format("tower escape: no next-map anchor"));
            }
            y.write()
        })?;
    }
    if opts.fishing_any_fish {
        crate::story_skip::stage_late(rf, &mut outs, work, qol::fishing::FLOW, qol::fishing::patch)?;
    }
    if opts.faster_ocarina_minigame {
        crate::story_skip::stage_late(rf, &mut outs, work, qol::skull_kid_session::FLOW, qol::skull_kid_session::patch)?;
    }
    if opts.dampe_first_dig {
        for flow in qol::dampe_dig::FLOWS {
            crate::story_skip::stage_late(rf, &mut outs, work, flow, qol::dampe_dig::patch)?;
        }
    }
    if opts.dampe_one_race {
        staging::edit_staged(rf, &mut outs, work, qol::dampe_race::GRAVE, true, qol::dampe_race::place)?;
        staging::edit_staged(rf, &mut outs, work, qol::dampe_race::LOGIC, false, qol::dampe_race::first_race_logic)?;
    }
    if opts.skulls_by_day {
        let mut woke = 0;
        for file in crate::placement::banc_files(rf)? {
            let raw = rf.zs.decompress(&frame(rf, work, &file)?)?;
            let relevant = [qol::skull_day::FLAG, qol::skull_day::NIGHT].iter()
                .any(|s| raw.windows(s.len()).any(|b| b == s.as_bytes()));
            if !relevant { continue; }
            staging::edit_staged(rf, &mut outs, work, &file, true, |bytes| {
                let mut y = Byml::parse(bytes)?;
                woke += qol::skull_day::wake(&mut y) + qol::skull_day::regroup(&mut y)?;
                y.write()
            })?;
        }
        qol::skull_day::all_woke(true, woke)?;
    }
    if opts.dungeon_key_tracker {
        let p = crate::key_log::plan(key_caps.ok_or(Error::Format(
            "key log: the room must supply final AP dungeon key totals"))?)?;
        for path in [crate::key_log::MENU_PACK, crate::key_log::TABLE, crate::chest_slot::LIST] {
            preload(rf, &mut outs, work, path)?;
        }
        for language in crate::hints::languages(rf)? { preload(rf, &mut outs, work, &language)?; }
        crate::key_log::stage(rf, &mut outs, &p)?;
        crate::key_log::stage_table(rf, &mut outs)?;
        crate::key_log::stage_flows(rf, &mut outs, work)?;
    }
    // Every new-format room can receive a legitimate AP Ice Trap (including
    // !getitem or item links). Pool settings control placement, not whether
    // the native receipt exists. The effect runs only when explicitly called.
    crate::frost::stage(rf, &mut outs, work)?;
    if opts.skip_area_intros {
        staging::edit_staged(rf, &mut outs, work, crate::chest_slot::LIST, true, |raw| {
            let mut table = Byml::parse(raw)?;
            let edits: Vec<_> = qol::area_intros::start_flags().into_iter()
                .map(|(name, value)| crate::start_defaults::Edit::Bool(name, value)).collect();
            crate::start_defaults::apply(&mut table, &edits)?;
            table.write()
        })?;
    }
    let mut names = std::collections::BTreeSet::new();
    for out in &outs {
        if !names.insert(out.path.as_str()) {
            return Err(Error::Msg(format!("upstream features: duplicate staged resource {}", out.path)));
        }
    }
    Ok(outs)
}

/// All resource parsing and allocation checks finish before any staged mod
/// file is written. The caller publishes the complete mod transactionally.
pub fn prepare(game: &Path, work: &Path, features: &Json, key_caps: Option<&[u32]>) -> Res<usize> {
    let options = Options::read(features)?;
    let mut rf = Romfs::open(game)?;
    let mut outs = stage(&mut rf, work, &options, key_caps)?;
    crate::feature_goals::stage(&mut rf, &mut outs, work, features)?;
    if features.get("native_settings").and_then(|s| s.get("skip_first_pickup_text")).and_then(Json::as_bool) == Some(true) {
        staging::edit_staged(&mut rf, &mut outs, work, crate::chest_slot::LIST, true,
            qol::first_pickup_extras::patch)?;
    }
    let table_frame = frame(&rf, work, rsizetable::TABLE_PATH)?;
    let dict = crate::flow_locations::dict_id(&table_frame);
    let mut table = Rst::parse(&rf.zs.decompress(&table_frame)?)?;
    crate::feature_difficulty::stage_features(&mut rf, &mut outs, work, features, &mut table)?;
    for out in &outs {
        if out.old == 0 && out.path == crate::pickup_pack::pack_of(crate::frost::sensor::NAME) {
            crate::frost::allocate(&mut rf, &mut table, out)?;
        } else if out.old == 0 && out.path.ends_with(".pack.zs") && table.get(&out.path).is_some() {
            // Modern difficulty factories have already budgeted the complete
            // new actor pack and every renamed component using native peers.
        } else { staging::grow_out(&mut rf, &mut table, out)?; }
    }
    if options.dungeon_key_tracker {
        crate::key_log::allocate_menu(&mut rf, &outs, &mut table)?;
    }
    let table_frame = crate::zs::compress_raw(&table.write()?, dict)?;
    for out in &outs {
        let target = work.join(crate::modpack::rel(&out.path)?);
        fs::create_dir_all(target.parent().ok_or(Error::Format("upstream features: invalid resource path"))?)?;
        fs::write(target, &out.z)?;
    }
    let table_path = work.join(rsizetable::TABLE_PATH);
    fs::create_dir_all(table_path.parent().ok_or(Error::Format("upstream features: invalid allocation table path"))?)?;
    fs::write(table_path, table_frame)?;
    Ok(outs.len())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn new_features_need_an_explicit_schema_and_never_default_shorter_minigames() {
        assert!(Options::read(&Json::obj()).is_err());
        let empty = Json::obj().with("schema", 1_i64.into()).with("settings", Json::obj());
        assert_eq!(Options::read(&empty).unwrap(), Options::default());
        let wrong = Json::obj().with("schema", 2_i64.into()).with("settings", Json::obj());
        assert!(Options::read(&wrong).is_err());
        let on = Json::obj().with("schema", 1_i64.into()).with("settings",
            Json::obj().with("fishing_any_fish", true.into()).with("dpad_gear_cycle", true.into()));
        let read = Options::read(&on).unwrap();
        assert!(read.fishing_any_fish && read.dpad_gear_cycle);
        assert!(!read.dampe_one_race && !read.faster_ocarina_minigame);
        let invalid = Json::obj().with("schema", 1_i64.into()).with("settings",
            Json::obj().with("fishing_any_fish", "true".into()));
        assert!(Options::read(&invalid).is_err());
    }

    #[test]
    fn stage_selected_features_on_read_only_game_resources() {
        let Some(game) = std::env::var_os("OOTRR_ROMFS").map(std::path::PathBuf::from) else { return };
        if !game.join("Pack/ZsDic.pack.zs").is_file() { return; }
        let mut rf = Romfs::open(&game).unwrap();
        let work = std::path::PathBuf::from("nonexistent-test-overlay");
        let options = Options { dungeon_key_tracker: true, dpad_gear_cycle: true,
            free_scarecrow: true, skip_tower_escape: true, skulls_by_day: true,
            fishing_any_fish: true, faster_ocarina_minigame: true, dampe_one_race: true,
            dampe_first_dig: true, disable_low_health_warnings: true, owl_warps: true,
            ..Default::default() };
        let outs = stage(&mut rf, &work, &options, Some(&[5, 8, 4, 5, 5, 2, 9, 2])).unwrap();
        assert!(outs.iter().any(|o| o.path == crate::key_log::MENU_PACK));
        assert!(outs.iter().any(|o| o.path == qol::gear_cycle::COUNTER_FILE));
        assert!(outs.iter().any(|o| o.path == qol::dampe_race::GRAVE));
        for out in outs {
            assert!(out.new > 0);
            if out.path.ends_with(".zs") { assert_eq!(rf.zs.decompress(&out.z).unwrap().len(), out.new); }
        }
    }

    #[test]
    fn new_rooms_allow_native_child_tunic_purchases_without_shuffling_shops() {
        let Some(game) = std::env::var_os("OOTRR_ROMFS").map(std::path::PathBuf::from) else { return };
        if !game.join("Pack/ZsDic.pack.zs").is_file() { return; }
        let mut rf = Romfs::open(&game).unwrap();
        let file = crate::shelf::hook::FLOW;
        let original = rf.read_zs(file).unwrap();
        let patched = crate::shelf::hook::edit(&original, &[], true).unwrap();
        assert_ne!(patched, original);
        assert_eq!(crate::shelf::hook::edit(&patched, &[], true).unwrap(), patched,
            "a previously prepared shop flow remains byte-identical");
        let staged = stage(&mut rf, Path::new("no-shop-override-test"), &Options::default(), None).unwrap();
        let shop = staged.iter().find(|out| out.path == file).unwrap();
        assert_eq!(rf.zs.decompress(&shop.z).unwrap(), patched);
        assert_eq!(rf.read_zs(file).unwrap(), original, "game resources are read-only");
    }

    #[test]
    fn prepare_full_feature_overlay_and_allocation_table_without_touching_the_game() {
        let Some(game) = std::env::var_os("OOTRR_ROMFS").map(std::path::PathBuf::from) else { return };
        if !game.join("Pack/ZsDic.pack.zs").is_file() { return; }
        let mut settings = Json::obj();
        for key in ["dungeon_key_tracker", "dpad_gear_cycle", "free_scarecrow", "skip_tower_escape",
            "skulls_by_day", "fishing_any_fish", "faster_ocarina_minigame", "dampe_one_race",
            "dampe_first_dig", "disable_low_health_warnings", "owl_warps", "shuffle_ice_traps",
            "skip_area_intros", "enemy_regen", "fairy_helps_enemies", "enemy_backup", "random_fuses"] {
            settings = settings.with(key, true.into());
        }
        settings = settings.with("enemy_health", 200_i64.into()).with("damage_taken", "double".into());
        let features = Json::obj().with("schema", 1_i64.into()).with("settings", settings)
            .with("seed", "AP-combined-resource-smoke".into())
            .with("native_settings", Json::obj().with("skip_first_pickup_text", true.into()));
        let base = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../..").canonicalize().unwrap().join("build");
        let unique = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos();
        let work = base.join(format!("upstream-features-resource-smoke-{}-{unique}", std::process::id()));
        fs::create_dir_all(&work).unwrap();
        let original = fs::read(game.join(crate::key_log::MENU_PACK)).unwrap();
        let written = prepare(&game, &work, &features, Some(&[5, 8, 4, 5, 5, 2, 9, 2])).unwrap();
        assert!(written > 30);
        assert_eq!(fs::read(game.join(crate::key_log::MENU_PACK)).unwrap(), original);
        let mut rf = Romfs::open(&game).unwrap();
        let table = Rst::parse(&rf.zs.decompress(&fs::read(work.join(rsizetable::TABLE_PATH)).unwrap()).unwrap()).unwrap();
        assert!(table.get(&crate::pickup_pack::pack_of(crate::frost::sensor::NAME)).is_some());
        let menu = rf.zs.decompress(&fs::read(work.join(crate::key_log::MENU_PACK)).unwrap()).unwrap();
        let entries = crate::sarc::parse(&menu).unwrap();
        let y = Byml::parse(&crate::sarc::get(&entries, crate::key_log::MENU_FILE).unwrap().data).unwrap();
        let panels = y.root.get("ChallengeMenuParamArray").unwrap().as_arr().unwrap();
        assert!(panels.iter().any(|r| r.get("ChallengeShort").and_then(crate::byml::Node::as_str) == Some("DoorOfTime")));
        assert!(panels.iter().any(|r| r.get("ChallengeShort").and_then(crate::byml::Node::as_str) == Some(crate::key_log::PARENT)));
        let native_entries = crate::sarc::parse(&rf.zs.decompress(&original).unwrap()).unwrap();
        let native_menu = &crate::sarc::get(&native_entries, crate::key_log::MENU_FILE).unwrap().data;
        let native_y = Byml::parse(native_menu).unwrap();
        let native_panels = native_y.root.get("ChallengeMenuParamArray").unwrap().as_arr().unwrap();
        assert_eq!(native_panels.len(), 20);
        assert_eq!(panels.len(), 29, "the tracker retains every native quest panel");
        let native_table = crate::rsizetable::load(&mut rf).unwrap();
        let minimum = crate::key_log::menu_budget(native_table.get(crate::key_log::MENU_FILE).unwrap(),
            native_panels.len(), panels.len(), native_menu.len(),
            crate::sarc::get(&entries, crate::key_log::MENU_FILE).unwrap().data.len()).unwrap();
        assert!(table.get(crate::key_log::MENU_FILE).unwrap() >= minimum,
            "the expanded native menu needs parsed-object capacity, not only BYML byte growth");
    }
}
