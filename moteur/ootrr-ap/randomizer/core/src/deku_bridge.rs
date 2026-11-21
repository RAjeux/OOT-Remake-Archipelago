pub mod pack;
pub mod pin;

use std::fs;
use std::path::{Path as P, PathBuf as PB};

use crate::error::{Error, Res};
use crate::modpack::Pack;
use crate::pickup_pack::sizes::pack_size;
use crate::qol::{edit_zs, Have};
use crate::romfs::Romfs;
use crate::rsizetable::Rst;
use crate::sarc::{self, Entry};
use crate::settings::Settings;
use crate::staging::{self, Out};

pub const KEY: &str = "deku_bridge_safe";
pub const NUM: u16 = 96;

pub const FLOORS: [(&str, &str); 2] = [
    ("Pack/Actor/Obj_InsideTheDekuTree_FallingFloor_A_01.pack.zs", "AI/Obj_FallFloor_A_01.root.ainb"),
    ("Pack/Actor/Obj_InsideTheDekuTree_FallingFloor_A_02.pack.zs", "AI/Obj_InsideTheDekuTree_FallingFloor_A_02.root.ainb"),
];

pub const STAIR: &str = "Pack/Actor/Obj_InsideTheDekuTree_FallingFloor_A_03.pack.zs";

pub const SHADOW: [&str; 2] = ["Pack/Actor/Obj_ShadowTemple_FallingFloor_A_01.pack.zs", "Pack/Actor/Obj_ShadowTemple_FallingFloor_A_03.pack.zs"];

pub const HASHES: [u64; 2] = [16857684421111642545, 7059309790216407104];

pub const NOTE: &str = "The wooden bridge in the Deku Tree slingshot room never breaks. Its two falling floor pieces ignore Link and each other, so the bridge stays solid. A bridge that already broke in a save stays broken. Experimental and untested in the game.";

pub fn mode(s: &Settings, bad: &mut Vec<String>) -> bool {
    s.flag(KEY).unwrap_or_else(|e| {
        bad.push(e.to_string());
        false
    })
}

pub fn patch_pack(raw: &[u8], member: &str) -> Res<Vec<u8>> {
    pack::patch(raw, member, pin::patch)
}

pub fn stage(rf: &mut Romfs, have: Have) -> Res<Vec<Out>> {
    let mut outs: Vec<Out> = Vec::new();
    for (path, member) in FLOORS {
        outs.push(edit_zs(rf, have, path, |raw| patch_pack(raw, member))?);
    }
    Ok(outs)
}

pub fn worked(rf: &mut Romfs, pk: &Pack) -> Res<Vec<Out>> {
    let root: PB = pk.work.join("romfs");
    let have = |p: &str| -> Option<Vec<u8>> { fs::read(p.split('/').fold(root.clone(), |a, s| a.join(s))).ok() };
    stage(rf, &have)
}

pub fn sizes(rf: &mut Romfs, rst: &Rst, outs: &[Out]) -> Res<Vec<String>> {
    let mut bad: Vec<String> = Vec::new();
    for o in outs {
        let (_, member): &(&str, &str) = FLOORS.iter().find(|(p, _)| *p == o.path).ok_or_else(|| Error::Msg(format!("deku bridge: {} is not a floor pack", o.path)))?;
        let raw: Vec<u8> = rf.zs.decompress(&o.z)?;
        let need: u32 = pack_size(raw.len())?;
        match rst.get(&o.path) {
            Some(n) if n >= need => {}
            Some(n) => bad.push(format!("{} needs {need} bytes in the size table, it has {n}", o.path)),
            None => bad.push(format!("{} has no size table entry", o.path)),
        }
        let es: Vec<Entry> = sarc::parse(&raw)?;
        let e: &Entry = sarc::get(&es, member).ok_or_else(|| Error::Msg(format!("deku bridge: {member} is missing from {}", o.path)))?;
        if let Some(n) = rst.get(member)
            && (n as usize) < e.data.len()
        {
            bad.push(format!("{member} is {} bytes, its size table entry is {n}", e.data.len()));
        }
    }
    Ok(bad)
}

pub fn build(romfs: &P, load: &P, name: &str) -> Res<String> {
    let mut rf: Romfs = Romfs::open(romfs)?;
    let outs: Vec<Out> = stage(&mut rf, &|_: &str| None)?;
    let rst: Rst = crate::rsizetable::load(&mut rf)?;
    let bad: Vec<String> = sizes(&mut rf, &rst, &outs)?;
    if !bad.is_empty() {
        return Err(Error::Msg(format!("deku bridge: size table check failed: {}", bad.join(", "))));
    }
    let c: staging::Committed = staging::commit(&mut rf, load, name, &outs, None)?;
    Ok(format!("{}deku bridge: {} floor graphs pinned, size table checked\n", c.report, outs.len()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ainb::Ainb;
    use crate::settings::Value;

    fn dump() -> Option<PB> {
        let p: PB = ootrr_game::test_romfs::path();
        if p.join("Pack").join("ZsDic.pack.zs").is_file() {
            Some(p)
        } else {
            eprintln!("skipped: no romfs at {}, set OOTRR_ROMFS", p.display());
            None
        }
    }

    fn none(_p: &str) -> Option<Vec<u8>> {
        None
    }

    fn member(rf: &mut Romfs, path: &str, m: &str) -> Vec<u8> {
        let raw: Vec<u8> = rf.read_zs(path).unwrap();
        sarc::get(&sarc::parse(&raw).unwrap(), m).unwrap().data.clone()
    }

    #[test]
    fn the_setting_is_off_by_default_and_read_when_on() {
        let mut bad: Vec<String> = Vec::new();
        assert!(!mode(&Settings::default(), &mut bad));
        assert!(!mode(&off(), &mut bad));
        assert!(mode(&on(), &mut bad));
        assert!(bad.is_empty());
    }

    #[test]
    fn the_note_is_plain_prose() {
        assert!(!NOTE.contains(';') && !NOTE.contains('\u{2014}'));
        assert!(NOTE.contains("Experimental"));
    }

    #[test]
    fn both_vanilla_packs_round_trip_and_hold_one_trigger_pair() {
        let Some(root) = dump() else {
            return;
        };
        let mut rf: Romfs = Romfs::open(&root).unwrap();
        for (path, m) in FLOORS {
            let raw: Vec<u8> = rf.read_zs(path).unwrap();
            assert_eq!(sarc::write(&sarc::parse(&raw).unwrap()).unwrap(), raw, "{path}");
            let b: Vec<u8> = member(&mut rf, path, m);
            let a: Ainb = Ainb::parse(&b).unwrap();
            assert_eq!(a.write().unwrap(), b, "{m}");
            for q in pin::QUERIES {
                let v: Vec<pin::Site> = pin::sites(&a, q);
                assert_eq!(v.len(), 1, "{m} {q}");
                assert_eq!(pin::consumers(&a, v[0].query), 2, "{m} {q}");
            }
        }
    }

    #[test]
    fn the_trigger_sites_are_the_ones_read_from_the_dump() {
        let Some(root) = dump() else {
            return;
        };
        let mut rf: Romfs = Romfs::open(&root).unwrap();
        let want: [[(usize, usize); 2]; 2] = [[(26, 14), (2, 33)], [(10, 8), (6, 37)]];
        for (i, (path, m)) in FLOORS.iter().enumerate() {
            let a: Ainb = Ainb::parse(&member(&mut rf, path, m)).unwrap();
            let got: Vec<(usize, usize)> = pin::QUERIES.iter().map(|q| pin::sites(&a, q)[0].clone()).map(|s| (s.sel, s.query)).collect();
            assert_eq!(got, want[i].to_vec(), "{m}");
        }
    }

    #[test]
    fn the_patched_graphs_lose_exactly_two_links_and_change_nothing_else() {
        let Some(root) = dump() else {
            return;
        };
        let mut rf: Romfs = Romfs::open(&root).unwrap();
        for (path, m) in FLOORS {
            let raw: Vec<u8> = member(&mut rf, path, m);
            let out: Vec<u8> = pin::patch(&raw).unwrap();
            assert_eq!(out.len() + 40, raw.len(), "{m}");
            let a: Ainb = Ainb::parse(&raw).unwrap();
            let b: Ainb = Ainb::parse(&out).unwrap();
            let done: Vec<pin::Site> = pin::QUERIES.iter().map(|q| pin::sites(&a, q)[0].clone()).collect();
            assert!(pin::only_sites_changed(&a, &b, &done), "{m}");
            for s in &done {
                assert!(pin::is_pinned(&b, s.sel), "{m}");
                assert_eq!(pin::consumers(&b, s.query), 0, "{m}");
                assert_eq!(b.params[s.sel].group(2), a.params[s.sel].group(2), "{m}");
            }
            assert_eq!(pin::steady(&b).els, pin::steady(&a).els);
            assert!(crate::ainb::audit(&b).is_empty());
            assert!(pin::patch(&out).is_err());
        }
    }

    #[test]
    fn staging_writes_two_smaller_packs_and_the_size_table_still_covers_them() {
        let Some(root) = dump() else {
            return;
        };
        let mut rf: Romfs = Romfs::open(&root).unwrap();
        let outs: Vec<Out> = stage(&mut rf, &none).unwrap();
        assert_eq!(outs.iter().map(|o| o.path.as_str()).collect::<Vec<&str>>(), FLOORS.iter().map(|f| f.0).collect::<Vec<&str>>());
        for o in &outs {
            assert!(o.new < o.old, "{}", o.path);
            let z: Vec<u8> = rf.read(&o.path).unwrap();
            assert_eq!(crate::flow_locations::dict_id(&z), crate::flow_locations::dict_id(&o.z));
            let a: Vec<Entry> = sarc::parse(&rf.zs.decompress(&z).unwrap()).unwrap();
            let b: Vec<Entry> = sarc::parse(&rf.zs.decompress(&o.z).unwrap()).unwrap();
            assert_eq!(pack::changed(&a, &b).len(), 1);
        }
        let rst: Rst = crate::rsizetable::load(&mut rf).unwrap();
        assert!(sizes(&mut rf, &rst, &outs).unwrap().is_empty());
        for (_, m) in FLOORS {
            assert!(rst.get(m).is_some(), "{m}");
        }
        let first: Vec<Out> = outs.clone();
        let again = |p: &str| -> Option<Vec<u8>> { first.iter().find(|o| o.path == p).map(|o| o.z.clone()) };
        assert!(stage(&mut rf, &again).is_err());
    }

    #[test]
    fn the_stair_and_the_shadow_temple_floors_are_left_alone() {
        let Some(root) = dump() else {
            return;
        };
        let mut rf: Romfs = Romfs::open(&root).unwrap();
        let stair: Vec<Entry> = sarc::parse(&rf.read_zs(STAIR).unwrap()).unwrap();
        assert!(stair.iter().all(|e| !e.name.starts_with("AI/")));
        let shadow: Vec<Entry> = sarc::parse(&rf.read_zs(SHADOW[0]).unwrap()).unwrap();
        let info: &Entry = sarc::get(&shadow, "AI/AIInfo/Obj_ShadowTemple_FallingFloor_A_01.engine__actor__AIInfo.bgyml").unwrap();
        let y: crate::byml::Byml = crate::byml::Byml::parse(&info.data).unwrap();
        assert_eq!(y.root.get("RootAIRef"), Some(&crate::byml::Node::Str("Work/AI/Root/Obj_ShadowTemple_FallingFloor_A_01.root.ain".to_string())));
        assert!(FLOORS.iter().all(|(p, _)| !SHADOW.contains(p) && *p != STAIR));
    }

    fn files(d: &P, base: &P, out: &mut Vec<String>) {
        for e in fs::read_dir(d).unwrap() {
            let p: PB = e.unwrap().path();
            if p.is_dir() {
                files(&p, base, out);
            } else {
                out.push(p.strip_prefix(base).unwrap().to_string_lossy().replace('\\', "/"));
            }
        }
    }

    #[test]
    fn the_test_mod_holds_the_two_packs_and_one_size_table() {
        let Some(root) = dump() else {
            return;
        };
        let load: PB = std::env::temp_dir().join("ootrr_deku_bridge_mods");
        let name: &str = "OOTRR Deku Bridge Test";
        let report: String = build(&root, &load, name).unwrap();
        assert!(report.contains("2 floor graphs pinned"));
        let out: PB = load.join(crate::TITLE_ID).join(name).join("romfs");
        let mut got: Vec<String> = Vec::new();
        files(&out, &out, &mut got);
        got.sort();
        let mut want: Vec<String> = FLOORS.iter().map(|f| f.0.to_string()).collect();
        want.push(crate::rsizetable::TABLE_PATH.to_string());
        want.sort();
        assert_eq!(got, want);
        let mut rf: Romfs = Romfs::open(&root).unwrap();
        let outs: Vec<Out> = stage(&mut rf, &none).unwrap();
        for o in &outs {
            assert_eq!(fs::read(out.join(&o.path)).unwrap(), o.z, "{}", o.path);
        }
        let rst: Rst = Rst::parse(&rf.zs.decompress(&fs::read(out.join(crate::rsizetable::TABLE_PATH)).unwrap()).unwrap()).unwrap();
        assert!(sizes(&mut rf, &rst, &outs).unwrap().is_empty());
        assert_eq!(rst, crate::rsizetable::load(&mut rf).unwrap());
    }

    fn on() -> Settings {
        let mut s: Settings = Settings::default();
        s.set(KEY, Value::Bool(true)).unwrap();
        s
    }

    fn off() -> Settings {
        let mut s: Settings = Settings::default();
        s.set(KEY, Value::Bool(false)).unwrap();
        s
    }

    #[test]
    fn the_plan_carries_the_toggle_and_its_note_and_no_logic() {
        use crate::slice::support::{plan, Plan};
        let o: Plan = plan(&off()).unwrap();
        let p: Plan = plan(&on()).unwrap();
        assert!(!o.bridge && p.bridge);
        assert!(!o.notes.iter().any(|n| n == NOTE));
        assert_eq!(p.notes.iter().filter(|n| *n == NOTE).count(), 1);
        assert_eq!(p.notes.len(), o.notes.len() + 1);
        assert_eq!(p.logic(), o.logic());
    }

    #[test]
    fn old_strings_mean_off_and_the_default_string_round_trips() {
        let old: &str = "OOTRR1-BEAQGGABAUOACZBEAMBAABWEOQ";
        let s: Settings = Settings::decode(old).unwrap().settings;
        assert!(!s.flag(KEY).unwrap());
        assert_eq!(s.encode().unwrap(), old);
        let d: String = Settings::default().encode().unwrap();
        assert_eq!(Settings::decode(&d).unwrap().settings.encode().unwrap(), d);
        assert!(!Settings::decode(&d).unwrap().settings.flag(KEY).unwrap());
        let x: String = on().encode().unwrap();
        assert_ne!(x, d);
        assert!(Settings::decode(&x).unwrap().settings.flag(KEY).unwrap());
    }

    #[test]
    fn the_toggle_never_changes_the_placements() {
        use crate::slice::data::Data;
        use crate::slice::generate::{generate_data, GenOpts, Generated};
        let d: Data = Data::load().unwrap();
        for seed in ["bridge a", "bridge b"] {
            let a: Generated = generate_data(&d, &off(), seed, &GenOpts::default()).unwrap();
            let b: Generated = generate_data(&d, &on(), seed, &GenOpts::default()).unwrap();
            assert_eq!(a.seed_file.placements, b.seed_file.placements, "{seed}");
        }
    }

    #[test]
    fn a_seed_build_with_the_toggle_writes_the_same_two_packs_and_a_covering_size_table() {
        use crate::slice::data::Data;
        use crate::slice::generate::{generate_data, GenOpts, Generated};
        let Some(root) = dump() else {
            return;
        };
        let d: Data = Data::load().unwrap();
        let load: PB = std::env::temp_dir().join("ootrr_deku_bridge_mods");
        let mut s: Settings = on();
        s.set("shuffle_rewards", Value::s("off")).unwrap();
        let g: Generated = generate_data(&d, &s, "bridge seed", &GenOpts::default()).unwrap();
        let out: PB = crate::slice::edit::build(&g.seed_file, &root, &load, "OOTRR Deku Bridge Seed Test").unwrap().root.join("romfs");
        let mut rf: Romfs = Romfs::open(&root).unwrap();
        let outs: Vec<Out> = stage(&mut rf, &none).unwrap();
        for o in &outs {
            assert_eq!(fs::read(out.join(&o.path)).unwrap(), o.z, "{}", o.path);
        }
        let t: PB = out.join(crate::rsizetable::TABLE_PATH);
        let rst: Rst = if t.is_file() { Rst::parse(&rf.zs.decompress(&fs::read(&t).unwrap()).unwrap()).unwrap() } else { crate::rsizetable::load(&mut rf).unwrap() };
        assert!(sizes(&mut rf, &rst, &outs).unwrap().is_empty());
        let mut o: Settings = off();
        o.set("shuffle_rewards", Value::s("off")).unwrap();
        let g: Generated = generate_data(&d, &o, "bridge seed", &GenOpts::default()).unwrap();
        let out: PB = crate::slice::edit::build(&g.seed_file, &root, &load, "OOTRR Deku Bridge Seed Off Test").unwrap().root.join("romfs");
        for (p, _) in FLOORS {
            assert!(!out.join(p).exists(), "{p}");
        }
    }
}
