//! Resource-only native patches for the full-network engine. No placement or
//! pool generator is called here; the existing staged AP resources are inputs.
use super::*;
use ootrr_core::{ainb::{self, Ainb}, difficulty, open_world, qol, sarc, staging::Out};
use std::collections::{BTreeMap, BTreeSet};

const ALLOWED: &[&str] = &[
    "faster_blocks", "navi_return", "bunny_hood", "starting_hearts",
    "enemy_health", "enemy_damage", "enemy_speed", "more_enemies", "enemy_regen",
    "enemy_backup", "no_heart_drops", "no_gossip_fairies", "no_ammo_drops",
    "lose_heart_on_death", "no_bottles_in_combat", "no_z_targeting", "no_dupe_items",
    "enemies_respawn_sooner", "boss_minibosses", "boss_minions", "bean_pitch",
    "zora_ambush", "cucco_revenge", "fairy_helps_enemies", "open_forest",
    "open_kakariko", "shuffle_shops", "enemy_gates", "enemy_spawn_combo", "shuffle_entrances",
    "jabu_open", "skip_epona_race", "skip_mask_quest", "early_beds",
    "skip_first_pickup_text", "deku_bridge_safe",
];

fn settings(j: &Json) -> Result<Settings> {
    let object = j.get("settings").and_then(Json::as_obj).ok_or("missing full extras settings")?;
    for (name, _) in object {
        if !ALLOWED.contains(&name.as_str()) { return Err(format!("not a resource-only full setting: {name}").into()); }
    }
    let settings = read_settings(j)?;
    if settings.flag("enemy_spawn_combo")? || settings.text("shuffle_entrances")? != "off" {
        return Err("full extras cannot shuffle entrances or enable developer input".into());
    }
    Ok(settings)
}

fn members(j: &Json) -> Result<Vec<String>> {
    let input = j.get("members").and_then(Json::as_arr).ok_or("missing native source member list")?;
    if input.len() > 200_000 { return Err("native source member list is too large".into()); }
    let mut result = BTreeSet::new();
    for entry in input {
        let path = entry.as_str().ok_or("invalid native source member")?;
        modpack::rel(path)?;
        if !result.insert(path.to_owned()) { return Err("duplicate native source member".into()); }
    }
    Ok(result.into_iter().collect())
}

fn source(j: &Json) -> Result<Romfs> {
    if let Some(name) = j.get("source_file").and_then(Json::as_str) {
        modpack::rel(name)?;
        if name.contains(['/', '\\']) || !name.to_ascii_lowercase().ends_with(".nup") {
            return Err("full native input must be one NUP file name".into());
        }
        let archive = ootrr_core::container::Archive::open(&Path::new("/game").join(name))?;
        let files = archive.game()?.newest.files;
        let reader = move |relative: &str| -> ootrr_core::error::Res<Vec<u8>> {
            let key = format!("romfs/{relative}");
            let member = files.get(&key).ok_or_else(|| ootrr_core::error::Error::Msg(format!("missing native package member: {relative}")))?;
            archive.read(member)
        };
        Ok(Romfs::with_reader(Path::new("/game"), Box::new(reader))?)
    } else {
        Ok(Romfs::open(Path::new("/game"))?)
    }
}

fn raw_source(game: &mut Romfs, overlay: &Path, path: &str) -> Result<Vec<u8>> {
    let target = overlay.join(modpack::rel(path)?);
    let raw = if target.is_file() { fs::read(target)? } else { game.read(path)? };
    Ok(if path.ends_with(".zs") { game.zs.decompress(&raw)? } else { raw })
}

fn remember(sizes: &mut BTreeMap<String, (Option<usize>, usize)>, path: &str,
            before: Option<usize>, after: usize) -> Result<()> {
    if before == Some(after) { return Ok(()); }
    if let Some(previous) = sizes.get_mut(path) {
        // Shared packed modules can occur in many actors. Keep the largest
        // actual increase and never count the same resource twice.
        let growth = after.saturating_sub(before.unwrap_or(0));
        let old_growth = previous.1.saturating_sub(previous.0.unwrap_or(0));
        if growth > old_growth { *previous = (before, after); }
    } else { sizes.insert(path.to_owned(), (before, after)); }
    Ok(())
}

pub fn run(j: &Json) -> Result<()> {
    let settings = settings(j)?;
    let mut bad = Vec::new();
    let read_qol = qol::read(&settings, &mut bad);
    let comfort = qol::Opts { blocks: read_qol.blocks, bunny: read_qol.bunny, navi: read_qol.navi, ..qol::Opts::default() };
    let challenge = difficulty::read(&settings, &mut bad);
    if !bad.is_empty() { return Err(bad.join("; ").into()); }
    let mut game = source(j)?;
    game.members = Some(members(j)?);
    let overlay = Path::new("/mod");
    let have = |path: &str| fs::read(overlay.join(path)).ok();
    let mut outputs = qol::stage(&mut game, &comfort, &have)?;
    let more = {
        let have_staged = |path: &str| outputs.iter().find(|row| row.path == path).map(|row| row.z.clone()).or_else(|| have(path));
        difficulty::stage(&mut game, &challenge, &have_staged, field(j, "seed")?)?
    };
    difficulty::merge(&mut outputs, more);
    let world = open_world::Opts { jabu: settings.flag("jabu_open")?, beds: settings.flag("early_beds")?,
        epona: settings.flag("skip_epona_race")?, ..open_world::Opts::default() };
    let more = {
        let have_staged = |path: &str| outputs.iter().find(|row| row.path == path).map(|row| row.z.clone()).or_else(|| have(path));
        open_world::stage(&mut game, &world, &have_staged)?
    };
    difficulty::merge(&mut outputs, more);
    if settings.flag("deku_bridge_safe")? {
        let more = {
            let have_staged = |path: &str| outputs.iter().find(|row| row.path == path).map(|row| row.z.clone()).or_else(|| have(path));
            ootrr_core::deku_bridge::stage(&mut game, &have_staged)?
        };
        difficulty::merge(&mut outputs, more);
    }
    let mut edits = Vec::new();
    if settings.flag("skip_mask_quest")? {
        edits.extend(ootrr_core::start_defaults::presets::chosen(&[("skip_mask_quest", "true")])?);
    }
    if settings.flag("skip_first_pickup_text")? {
        edits.extend(ootrr_core::first_pickups::start_flags().into_iter()
            .map(|(name, value)| ootrr_core::start_defaults::Edit::Bool(name, value)));
    }
    if !edits.is_empty() {
        let path = ootrr_core::chest_slot::LIST;
        let patched = {
            let have_staged = |p: &str| outputs.iter().find(|row| row.path == p).map(|row| row.z.clone()).or_else(|| have(p));
            qol::edit_zs(&mut game, &have_staged, path, |raw| {
                let mut document = Byml::parse(raw)?;
                ootrr_core::start_defaults::apply(&mut document, &edits)?;
                document.write()
            })?
        };
        difficulty::merge(&mut outputs, vec![patched]);
    }
    if world.epona {
        let song = raw_source(&mut game, overlay, open_world::skips::EPONA_FILE)?;
        let own = open_world::skips::own_bytes(&song)?;
        let (_, dictionary) = read_overlay(&mut game, overlay, open_world::skips::EPONA_FILE)?;
        outputs.push(Out { path: open_world::skips::OWN_FILE.into(), old: 0, new: own.len(), z: zs::compress_raw(&own, dictionary)? });
        for (path, analyzed) in [(ootrr_core::progressive::SETTING_TABLE, false), (ootrr_core::progressive::ANALYZED_TABLE, true)] {
            let patched = {
                let have_staged = |p: &str| outputs.iter().find(|row| row.path == p).map(|row| row.z.clone()).or_else(|| have(p));
                qol::edit_zs(&mut game, &have_staged, path, |raw| {
                    let mut document = Byml::parse(raw)?;
                    open_world::skips::own_row(&mut document, analyzed)?;
                    if analyzed {
                        if let Some(rows) = document.root.as_arr_mut() {
                            for row in rows {
                                if row.get("__RowId").and_then(Node::as_str) == Some(open_world::skips::EPONA_FLOW) {
                                    let mut children = row.get("ChildEventList").and_then(Node::as_arr).unwrap_or(&[]).to_vec();
                                    if !children.iter().any(|v| v.as_str() == Some(open_world::skips::OWN_EVENT)) {
                                        children.push(Node::Str(open_world::skips::OWN_EVENT.into()));
                                        row.set("ChildEventList", Node::Arr(children));
                                    }
                                }
                            }
                        }
                    }
                    document.write()
                })?
            };
            difficulty::merge(&mut outputs, vec![patched]);
        }
    }
    let hearts = settings.int("starting_hearts")?;
    if hearts != 3 {
        let path = ainb::start::MODULE;
        let before = raw_source(&mut game, overlay, path)?;
        let mut graph = Ainb::parse(&before)?;
        ainb::start::set_hearts(&mut graph, hearts.try_into()?)?;
        outputs.push(Out { path: path.into(), old: before.len(), new: 0, z: graph.write()? });
    }
    let mut sizes = BTreeMap::new();
    let mut paths = BTreeSet::new();
    for output in &outputs {
        modpack::rel(&output.path)?;
        if !paths.insert(&output.path) { return Err("duplicate full extras resource".into()); }
        let exists = overlay.join(&output.path).is_file()
            || game.members.as_ref().is_some_and(|members| members.binary_search(&output.path).is_ok());
        let before = if exists { Some(raw_source(&mut game, overlay, &output.path)?) } else { None };
        let after = if output.path.ends_with(".zs") { game.zs.decompress(&output.z)? } else { output.z.clone() };
        remember(&mut sizes, &output.path, before.as_ref().map(Vec::len), after.len())?;
        if output.path.ends_with(".pack.zs") {
            let old = if let Some(before) = &before { sarc::parse(before)? } else { Vec::new() };
            for entry in sarc::parse(&after)? {
                let was = sarc::get(&old, &entry.name).map(|row| row.data.len());
                remember(&mut sizes, &entry.name, was, entry.data.len())?;
            }
        }
    }
    let records = sizes.iter().map(|(path, (old, new))| Json::obj().with("path", path.as_str().into())
        .with("old", old.map(|n| Json::from(n as i64)).unwrap_or(Json::Null))
        .with("new", (*new as i64).into())).collect();
    // All edits and round trips are prepared before the private workspace changes.
    // The Python owner updates RESTBL with collision-aware allocation helpers.
    for output in &outputs {
        let target = overlay.join(modpack::rel(&output.path)?);
        fs::create_dir_all(target.parent().ok_or("invalid full extras output")?)?;
        fs::write(target, &output.z)?;
    }
    println!("{}", Json::obj().with("files", Json::strs(outputs.iter().map(|row| row.path.as_str())))
        .with("allocations", Json::Arr(records)).pretty());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resource_only_request_rejects_shuffle_or_debug_operations() {
        for (name, value) in [("shuffle_chests", Json::Bool(false)), ("enemy_spawn_combo", Json::Bool(true)),
                              ("shuffle_entrances", "dungeons".into())] {
            let request = Json::obj().with("settings", Json::obj().with(name, value));
            assert!(settings(&request).is_err(), "{name}");
        }
        let request = Json::obj().with("settings", Json::obj().with("enemy_gates", Json::Bool(true)));
        assert!(settings(&request).unwrap().flag("enemy_gates").unwrap());
    }

    #[test]
    fn shared_module_growth_is_counted_once_with_the_largest_delta() {
        let mut sizes = BTreeMap::new();
        remember(&mut sizes, "AI/Test.ainb", Some(100), 120).unwrap();
        remember(&mut sizes, "AI/Test.ainb", Some(200), 210).unwrap();
        assert_eq!(sizes["AI/Test.ainb"], (Some(100), 120));
        remember(&mut sizes, "AI/Test.ainb", Some(100), 150).unwrap();
        assert_eq!(sizes["AI/Test.ainb"], (Some(100), 150));
    }

    #[test]
    fn explicit_member_listing_is_sorted_bounded_and_relative() {
        let j = Json::obj().with("members", Json::strs(["Pack/Actor/Z.pack.zs", "Pack/Actor/A.pack.zs"]));
        assert_eq!(members(&j).unwrap(), vec!["Pack/Actor/A.pack.zs", "Pack/Actor/Z.pack.zs"]);
        for paths in [vec!["../private"], vec!["/absolute"], vec!["same", "same"]] {
            assert!(members(&Json::obj().with("members", Json::strs(paths))).is_err());
        }
    }

    #[test]
    fn native_editors_keep_the_dictionary_after_a_window_descriptor() {
        for dictionary in [4, 0x102, 0x10203] {
            let mut frame = zs::compress_raw(b"native parameters", Some(dictionary)).unwrap();
            frame[4] &= !0x20;
            frame.insert(5, 0x58);
            assert_eq!(ootrr_core::flow_locations::dict_id(&frame), Some(dictionary));
        }
    }
}
