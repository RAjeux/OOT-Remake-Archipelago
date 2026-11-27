//! Additional reviewed physical checks. They are AP-only: the portable 0.8.1
//! builder never receives location names it does not recognize.
use std::collections::BTreeSet;
use std::fs;
use std::path::Path;
use ootrr_core::{byml::{Byml, Node}, json::{self, Json}, modpack, placement,
    romfs::Romfs, rsizetable::{self, Rst}, settings::Settings, staging, zs};
use super::Result;

const DATA: &str = include_str!("../../../../../../../client/ootrr_triforce/additional_sources.json");

pub fn document() -> Result<Json> { Ok(json::parse(DATA)?) }

pub fn catalog() -> Result<Vec<(String, Json)>> {
    Ok(document()?.get("sources").and_then(Json::as_obj).ok_or("missing additional source table")?.to_vec())
}

pub fn selected(settings: &Settings) -> Result<Vec<String>> {
    let doc = document()?;
    let rewards = doc.get("rewards").ok_or("missing additional rewards")?;
    let chest_mode = settings.text("shuffle_chests")?;
    let pickups = settings.text("shuffle_freestanding_items")?;
    let mut names = Vec::new();
    for (name, source) in catalog()? {
        let reward = rewards.get(&name).and_then(Json::as_str).ok_or("unknown additional reward")?;
        let kind = source.get("kind").and_then(Json::as_str).ok_or("invalid additional source")?;
        if kind == "chest" {
            if !matches!(chest_mode, "all" | "dungeons") { continue; }
            if reward.starts_with("Small Key (") && settings.text("shuffle_smallkeys")? == "vanilla" { continue; }
            if (reward.starts_with("Map (") || reward.starts_with("Compass ("))
                && settings.text("shuffle_mapcompass")? == "vanilla" { continue; }
        } else if !matches!(pickups, "all" | "overworld") {
            continue;
        }
        names.push(name);
    }
    names.sort();
    Ok(names)
}

fn maps_start(settings: &Settings) -> Result<bool> {
    Ok(matches!(settings.text("shuffle_mapcompass")?, "startwith" | "remove"))
}

pub fn merge(sources: Json, selected: &[String], settings: &Settings) -> Result<Json> {
    let mut rows = sources.as_obj().ok_or("invalid source table")?.to_vec();
    let doc = document()?;
    let descriptors = doc.get("sources").ok_or("missing extra descriptors")?;
    let rewards = doc.get("rewards").ok_or("missing extra rewards")?;
    for name in selected {
        if rows.iter().any(|(key, _)| key == name) { return Err("duplicate native AP source".into()); }
        let row = descriptors.get(name).ok_or("unknown additional source")?.clone();
        let reward = rewards.get(name).and_then(Json::as_str).ok_or("missing extra reward")?;
        let reward = if maps_start(settings)? && (reward.starts_with("Map (") || reward.starts_with("Compass (")) {
            "Rupee (1)"
        } else { reward };
        rows.push((name.clone(), row.with("generated_item", reward.into())));
    }
    rows.sort_by(|a,b| a.0.cmp(&b.0));
    Ok(Json::Obj(rows))
}

fn normalize_chest(map: &mut Byml, hash: u64, expected: &str, name: &str, started_map: bool) -> ootrr_core::error::Res<()> {
    use ootrr_core::error::Error;
    let actors = map.root.get_mut("Actors").and_then(Node::as_arr_mut)
        .ok_or(Error::Format("additional map has no actors"))?;
    let matches: Vec<_> = actors.iter().enumerate().filter(|(_, a)| placement::hash_of(a) == Some(hash)).map(|(i,_)| i).collect();
    let [index] = matches.as_slice() else { return Err(Error::Format("additional chest identity is ambiguous")); };
    let actor = &mut actors[*index];
    if actor.get("Dynamic").is_some_and(|value| !matches!(value, Node::Map(_))) {
        return Err(Error::Format("additional chest dynamic parameters are not an object"));
    }
    // These two reviewed native chests inherit their drop from their actor
    // configuration, instead of spelling it in Dynamic. Do not generalize this
    // exception to another identity or an unexpected explicit drop.
    let inherited_class = match name {
        "Forest Temple Falling Ceiling Room Chest" => Some("Obj_TBox_A_01"),
        "Gerudo Training Ground Lobby Left Chest" => Some("Obj_TBox_GlassTruth_A_01"),
        _ => None,
    };
    let inherited = inherited_class.is_some_and(|class| actor.get("Gyaml").and_then(Node::as_str) == Some(class))
        && ["Drop__DropActor", "Drop__DropActor_Substitute"].iter()
            .all(|key| actor.get("Dynamic").and_then(|dynamic| dynamic.get(key)).is_none());
    let explicit = ["Drop__DropActor", "Drop__DropActor_Substitute"].iter()
        .any(|key| actor.get("Dynamic").and_then(|dynamic| dynamic.get(key)).and_then(Node::as_str)
            .is_some_and(|drop| drop == expected || started_map && drop == "TBox_Rupee_Green"));
    if !explicit && !inherited {
        return Err(Error::Msg(format!(
            "additional chest reward differs from the reviewed source: {name}, actor {hash}, expected {expected}, found {:?}",
            actor.get("Dynamic").and_then(|dynamic| dynamic.get("Drop__DropActor")).and_then(Node::as_str))));
    }
    if actor.get("Dynamic").is_none() { actor.set("Dynamic", Node::Map(Vec::new())); }
    let dynamic = actor.get_mut("Dynamic").ok_or(Error::Format("additional chest has no dynamic parameters"))?;
    dynamic.set("Drop__DropActor", Node::Str("TBox_Rupee_Green".into()));
    if dynamic.get("Drop__DropActor_Substitute").is_some() {
        dynamic.set("Drop__DropActor_Substitute", Node::Str("TBox_Rupee_Green".into()));
    }
    dynamic.remove("Drop__CheckActor");
    dynamic.remove("GetEventName");
    Ok(())
}

pub fn prepare(game: &Path, work: &Path, names: &[String], settings: &Settings) -> Result<()> {
    let unique: BTreeSet<_> = names.iter().collect();
    if unique.len() != names.len() { return Err("duplicate additional native source".into()); }
    let document = document()?;
    let descriptors = document.get("sources").ok_or("missing extra descriptors")?;
    let mut rf = Romfs::open(game)?;
    let mut outs = Vec::new();
    let mut chest_flags = Vec::new();
    for name in names {
        let source = descriptors.get(name).ok_or("unknown additional source")?;
        if source.get("kind").and_then(Json::as_str) != Some("chest") { continue; }
        let reward = document.get("rewards").and_then(|rewards| rewards.get(name)).and_then(Json::as_str)
            .ok_or("missing additional native reward")?;
        let started_map = maps_start(settings)? && (reward.starts_with("Map (") || reward.starts_with("Compass ("));
        for variant in source.get("variants").and_then(Json::as_arr).ok_or("missing extra source variants")? {
            let file = variant.get("file").and_then(Json::as_str).ok_or("missing extra map")?;
            let hash: u64 = variant.get("actor").and_then(Json::as_str).ok_or("missing extra actor")?.parse()?;
            let expected = variant.get("expected_actor").and_then(Json::as_str).ok_or("missing original reward")?;
            let trap = source.get("native_route").and_then(Json::as_str) == Some("frozen_chest");
            staging::edit_staged(&mut rf, &mut outs, work, file, true, |raw| {
                let mut map = Byml::parse(raw)?;
                if trap {
                    if ootrr_core::qol::trap_chests::open(&mut map, hash, "TBox_Rupee_Green")? != 1 {
                        return Err(ootrr_core::error::Error::Format("additional trap chest does not match the supported game"));
                    }
                } else {
                    normalize_chest(&mut map, hash, expected, name, started_map)?;
                }
                map.write()
            })?;
            chest_flags.push(hash);
        }
    }
    ootrr_core::qol::trap_chests::stage(&mut rf, &mut outs, work, &chest_flags)?;
    let path = work.join(rsizetable::TABLE_PATH);
    let frame = if path.is_file() { fs::read(&path)? } else { rf.read(rsizetable::TABLE_PATH)? };
    let mut table = Rst::parse(&rf.zs.decompress(&frame)?)?;
    for out in &outs { staging::grow_out(&mut rf, &mut table, out)?; }
    let table = zs::compress_raw(&table.write()?, ootrr_core::flow_locations::dict_id(&frame))?;
    for out in outs {
        let path = work.join(modpack::rel(&out.path)?);
        fs::create_dir_all(path.parent().ok_or("invalid extra source output")?)?;
        fs::write(path, out.z)?;
    }
    fs::create_dir_all(path.parent().ok_or("invalid resource table output")?)?;
    fs::write(path, table)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn native_starting_maps_do_not_reenter_the_extra_ap_pool() {
        let name = "Fire Temple Boulder Maze Side Room Chest".to_string();
        for (mode, reward) in [("dungeon", "Compass (Fire Temple)"), ("startwith", "Rupee (1)"), ("remove", "Rupee (1)")] {
            let mut settings = Settings::default();
            settings.set("shuffle_mapcompass", ootrr_core::settings::Value::s(mode)).unwrap();
            let rows = merge(Json::obj(), &[name.clone()], &settings).unwrap();
            assert_eq!(rows.get(&name).unwrap().get("generated_item").and_then(Json::as_str), Some(reward));
        }
    }

    #[test]
    fn inherited_drops_are_limited_to_the_reviewed_chests_and_reject_explicit_conflicts() {
        for (name, class) in [("Forest Temple Falling Ceiling Room Chest", "Obj_TBox_A_01"),
                              ("Gerudo Training Ground Lobby Left Chest", "Obj_TBox_GlassTruth_A_01")] {
            let actor = Node::Map(vec![("Hash".into(), Node::U64(42)), ("Gyaml".into(), Node::Str(class.into()))]);
            let original = Byml { version: 7, big: false,
                root: Node::Map(vec![("Actors".into(), Node::Arr(vec![actor]))]) };
            let mut edited = original.clone();
            normalize_chest(&mut edited, 42, "InheritedDrop", name, false).unwrap();
            assert_eq!(edited.root.get("Actors").unwrap().as_arr().unwrap()[0].get("Dynamic").unwrap()
                .get("Drop__DropActor").and_then(Node::as_str), Some("TBox_Rupee_Green"));
            assert!(normalize_chest(&mut original.clone(), 42, "InheritedDrop", "Unreviewed chest", false).is_err());
            let mut conflict = original.clone();
            conflict.root.get_mut("Actors").unwrap().as_arr_mut().unwrap()[0]
                .set("Dynamic", Node::Map(vec![("Drop__DropActor".into(), Node::Str("UnexpectedDrop".into()))]));
            assert!(normalize_chest(&mut conflict, 42, "InheritedDrop", name, false).is_err());
        }
    }
}
