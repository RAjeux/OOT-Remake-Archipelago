use std::collections::{BTreeMap as BM, BTreeSet as BS};
use std::fmt::Write as W;
use std::path::{Path as P, PathBuf as PB};

use crate::byml::{Byml, Node};
use crate::error::{Error as E, Res};
use crate::flow_locations::dict_id;
use crate::modpack::Pack;
use crate::pickup_pack::actor::{ATTENTION_REF, POUCH_REF};
use crate::pickup_pack::build::pool_of;
use crate::pickup_pack::closure::{actor_file, chain, dangling_with, is_byml, norm, select, work, Chain, Pool, COMPONENTS, PARENT};
use crate::pickup_pack::kit::{auto, falls, leaf, PHYSICS_REF, REFS};
use crate::pickup_pack::rows::{self, ACTOR_INFO, GAME_ACTOR_INFO, POUCH_INFO};
use crate::pickup_pack::sizes;
use crate::pickup_pack::tag::{Table, TAG};
use crate::pickup_pack::write::{base_dir, earlier, size_table, start, table, Done, File, Opts};
use crate::pickup_pack::{pack_of, BASE, PACK_DICT};
use crate::rsizetable::{Rst, TABLE_PATH};
use crate::romfs::Romfs;
use crate::sarc::{self, Entry};
use crate::staging::MARGIN;
use crate::zs;
use crate::TITLE_ID;

pub const SUFFIX: &str = "_Fall";
pub const HANGS: [&str; 1] = [crate::pickup_pack::kit::TOKEN];
pub const KEEP: [&str; 3] = [ATTENTION_REF, POUCH_REF, crate::pickup_pack::kit::LIFE_REF];

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FallPlan {
    pub name: String,
    pub from: String,
    pub files: Vec<String>,
    pub fresh: Vec<(String, usize)>,
    pub peers: Vec<(String, usize)>,
    pub sarc: Vec<u8>,
}

pub fn name_of(pickup: &str) -> String {
    format!("{pickup}{SUFFIX}")
}

pub fn parent_of(name: &str) -> Option<&'static str> {
    let p: &str = name.strip_suffix(SUFFIX)?;
    HANGS.iter().copied().find(|h| *h == p)
}

pub fn is_fall(name: &str) -> bool {
    parent_of(name).is_some()
}

pub fn dropped(actor: &str) -> String {
    if HANGS.contains(&actor) {
        name_of(actor)
    } else {
        actor.to_string()
    }
}

pub fn wanted<'a>(actors: impl Iterator<Item = &'a str>) -> Vec<&'static str> {
    let got: BS<&'static str> = actors.filter_map(parent_of).collect();
    got.into_iter().collect()
}

fn comp<'a>(c: &'a Chain, k: &str, who: &str) -> Res<&'a str> {
    c.comps.get(k).map(|s| s.as_str()).ok_or_else(|| E::Msg(format!("{who} has no {k}")))
}

pub fn plan(packs: &[Vec<Entry>], from: &str) -> Res<FallPlan> {
    if !HANGS.contains(&from) {
        return Err(E::Msg(format!("{from} is not a pickup that hangs in the air, it needs no falling twin")));
    }
    let name: String = name_of(from);
    let mut p: Pool = pool_of(packs)?;
    let own: Chain = chain(&p, from)?;
    let base: Chain = chain(&p, BASE)?;
    if falls(&p, &own)? {
        return Err(E::Msg(format!("{from} already falls, a falling twin would change nothing")));
    }
    let body: String = comp(&base, PHYSICS_REF, BASE)?.to_string();
    if !norm(&body).is_some_and(|f| p.get(&f).is_some()) {
        return Err(E::Msg(format!("the falling body {body} of {BASE} is not in the source packs")));
    }
    let f: String = actor_file(&name);
    if p.get(&f).is_some() {
        return Err(E::Msg(format!("{f} already exists, {name} is taken")));
    }
    let peers: Vec<(String, usize)> = p.files.iter().map(|e| (e.0.clone(), e.1.len())).collect();
    let version: u16 = p.byml(&actor_file(from))?.version;
    let mut comps: Node = Node::Map(Vec::new());
    comps.set(PHYSICS_REF, Node::Str(body.clone()));
    let mut actor: Node = Node::Map(Vec::new());
    actor.set(PARENT, Node::Str(work(&actor_file(from))));
    actor.set(COMPONENTS, comps);
    let d: Vec<u8> = Byml { root: actor, version, big: false }.write()?;
    p.add(&f, &d)?;
    let fresh: Vec<(String, usize)> = vec![(f.clone(), d.len())];
    let files: Vec<String> = select(&p, &name)?;
    if !files.contains(&f) {
        return Err(E::Msg(format!("{f} did not make it into the pack")));
    }
    if let Some(x) = files.iter().find(|x| !p.get(x).is_some_and(|d| is_byml(d) || leaf(d))) {
        return Err(E::Msg(format!("{x} is neither a parameter file nor an AI graph, the twin cannot carry it")));
    }
    let c: Chain = chain(&p, &name)?;
    let known: BS<String> = p.files.keys().cloned().collect();
    if let Some(x) = dangling_with(&p, &files, &known, &c)?.first() {
        return Err(E::Msg(format!("{x} is referenced but left out of the pack")));
    }
    check(&p, &name, from, &body)?;
    let es: Vec<Entry> = files.iter().map(|x| Entry { name: x.clone(), data: p.get(x).unwrap_or(&[]).to_vec() }).collect();
    Ok(FallPlan { name, from: from.to_string(), files, fresh, peers, sarc: sarc::write(&es)? })
}

fn check(p: &Pool, name: &str, from: &str, body: &str) -> Res<()> {
    let c: Chain = chain(p, name)?;
    let own: Chain = chain(p, from)?;
    let mut diff: Vec<&str> = Vec::new();
    for (k, v) in &c.comps {
        if own.comps.get(k) != Some(v) {
            diff.push(k.as_str());
        }
    }
    if diff != vec![PHYSICS_REF] || own.comps.len() != c.comps.len() {
        return Err(E::Msg(format!("{name} differs from {from} in {diff:?}, only {PHYSICS_REF} may change")));
    }
    if c.comps.get(PHYSICS_REF).map(|v| v.as_str()) != Some(body) {
        return Err(E::Msg(format!("{name} does not take the body of {BASE}")));
    }
    for k in REFS.iter().chain(KEEP.iter()) {
        if c.comps.get(*k).is_none() {
            return Err(E::Msg(format!("{name} has no {k}")));
        }
    }
    if !falls(p, &c)? {
        return Err(E::Msg(format!("{name} still hangs in the air, a body of its {PHYSICS_REF} is not Dynamic")));
    }
    if !auto(p, &c)? {
        return Err(E::Msg(format!("{name} is not taken by touch")));
    }
    Ok(())
}

pub fn verify(es: &[Entry], name: &str, from: &[Entry]) -> Res<Vec<String>> {
    let parent: &str = parent_of(name).ok_or_else(|| E::Msg(format!("{name} is not a falling twin")))?;
    let p: Pool = pool_of(&[es.to_vec()])?;
    let t: Pool = pool_of(&[from.to_vec()])?;
    let mut names: Vec<String> = es.iter().map(|e| e.name.clone()).collect();
    names.sort();
    if select(&p, name)? != names {
        return Err(E::Msg(format!("{name} holds a file its actor does not reach")));
    }
    let body: String = comp(&chain(&p, name)?, PHYSICS_REF, name)?.to_string();
    check(&p, name, parent, &body)?;
    let mut same: usize = 0;
    for e in es.iter().filter(|e| e.name != actor_file(name)) {
        match t.get(&e.name) {
            Some(d) if d != e.data.as_slice() => return Err(E::Msg(format!("{name} holds another {} than {parent}", e.name))),
            Some(_) => same += 1,
            None => {}
        }
    }
    let tc: Chain = chain(&t, parent)?;
    for k in REFS {
        let f: String = norm(comp(&tc, k, parent)?).ok_or_else(|| E::Msg(format!("{parent} keeps its {k} outside its pack")))?;
        if p.get(&f) != t.get(&f) || p.get(&f).is_none() {
            return Err(E::Msg(format!("{name} does not carry the shipped {f} of {parent}")))
        }
    }
    Ok(vec![
        format!("{name}: a child of {parent} whose only override is {PHYSICS_REF} {body}, every body falls, taken by touch"),
        format!("{name}: {same} files are the shipped files of {parent} byte for byte, its AI graph, blackboard and death table are the ones of {parent}"),
    ])
}

fn clone_row(y: &mut Byml, t: &str, from: &str, name: &str) -> Res<usize> {
    let mut r: Node = rows::need(y, from, t)?.clone();
    r.set(rows::ROW_ID, Node::Str(name.to_string()));
    if t == GAME_ACTOR_INFO {
        if let Some(v) = rows::need(y, BASE, t)?.get(rows::LAYER).cloned() {
            r.set(rows::LAYER, v);
        }
    }
    rows::insert(y, r)
}

fn tag_file(rf: &mut Romfs, o: &Opts, modded: bool, plans: &[FallPlan]) -> Res<File> {
    let first: Vec<u8> = start(rf, o.base.as_ref(), TAG)?;
    let mut t: Table = Table::parse(&first)?;
    for pl in plans {
        let tags: Vec<String> = t.tags_of(&pl.from);
        t.insert(&pl.name, &tags)?;
    }
    let raw: Vec<u8> = t.write()?;
    let id: Option<u32> = dict_id(&rf.read(TAG)?);
    let old: usize = if modded { first.len() } else { rf.read_zs(TAG)?.len() };
    Ok(File { path: TAG.to_string(), z: zs::compress_raw(&raw, id)?, raw, old, fresh: false })
}

pub fn audit_tags(old: &Table, now: &Table, plans: &[FallPlan]) -> Res<String> {
    if now.tags != old.tags || now.version != old.version || !now.sorted() {
        return Err(E::Format("audit: the tag list changed or the tag table is not sorted"));
    }
    let fresh: BS<&str> = plans.iter().map(|pl| pl.name.as_str()).collect();
    let had: usize = old.paths.iter().filter(|x| fresh.contains(x[1].as_str())).count();
    if now.paths.len() + had != old.paths.len() + plans.len() {
        return Err(E::Format("audit: the tag table is not the table it started from plus one row per twin"));
    }
    for x in old.paths.iter().filter(|x| !fresh.contains(x[1].as_str())) {
        if now.tags_of(&x[1]) != old.tags_of(&x[1]) {
            return Err(E::Msg(format!("audit: the tag row of {} changed", x[1])));
        }
    }
    let mut out: Vec<String> = Vec::new();
    for pl in plans {
        let want: Vec<String> = old.tags_of(&pl.from);
        if now.find(&pl.name).is_none() || now.tags_of(&pl.name) != want {
            return Err(E::Msg(format!("audit: the tag row of {} is not the one of {}", pl.name, pl.from)));
        }
        out.push(format!("{} carries {want:?} like {}", pl.name, pl.from));
    }
    Ok(format!("{TAG}: {} -> {} rows, {}, every other row unchanged", old.paths.len(), now.paths.len(), out.join(", ")))
}

pub fn audit_rows(was: &Byml, now: &Byml, t: &str, plans: &[FallPlan]) -> Res<String> {
    let fresh: BS<&str> = plans.iter().map(|pl| pl.name.as_str()).collect();
    let m: usize = was.root.as_arr().map(|a| a.len()).unwrap_or(0);
    let n: usize = now.root.as_arr().map(|a| a.len()).unwrap_or(0);
    let had: usize = was.root.as_arr().unwrap_or(&[]).iter().filter(|r| rows::id(r).is_some_and(|i| fresh.contains(i))).count();
    if !rows::sorted(now)? || n + had != m + plans.len() {
        return Err(E::Msg(format!("audit: {t} is not the table it started from plus one sorted row per twin")));
    }
    let index: std::collections::HashMap<&str, &Node> = rows::index(now);
    for r in was.root.as_arr().unwrap_or(&[]).iter().filter(|r| !rows::id(r).is_some_and(|i| fresh.contains(i))) {
        let i: &str = rows::id(r).unwrap_or("");
        if index.get(i).copied() != Some(r) {
            return Err(E::Msg(format!("audit: {t} changed the row {i}")));
        }
    }
    for pl in plans {
        let mut want: Node = rows::need(was, &pl.from, t)?.clone();
        want.set(rows::ROW_ID, Node::Str(pl.name.clone()));
        if t == GAME_ACTOR_INFO {
            if let Some(v) = rows::need(was, BASE, t)?.get(rows::LAYER) {
                want.set(rows::LAYER, v.clone());
            }
        }
        if rows::find(now, &pl.name) != Some(&want) {
            return Err(E::Msg(format!("audit: the {t} row of {} is not the row of {}", pl.name, pl.from)));
        }
    }
    Ok(format!("{t}: {m} -> {n} rows, every earlier row unchanged, each twin row is the row of its parent"))
}

pub fn run(romfs: &P, load: &P, mod_name: &str, from: &[&str], o: &Opts) -> Res<Done> {
    let o: &Opts = &Opts { base: base_dir(o)?, ..o.clone() };
    let mut rf: Romfs = Romfs::open(romfs)?;
    let base: Vec<Entry> = sarc::parse(&rf.read_zs(&pack_of(BASE))?)?;
    let (mut rst, modded): (Rst, bool) = size_table(&mut rf, o)?;
    let id: u32 = dict_id(&rf.read(&pack_of(BASE))?).unwrap_or(PACK_DICT);
    let mut note: String = String::new();
    let mut files: Vec<File> = Vec::new();
    let mut plans: Vec<FallPlan> = Vec::new();
    let mut parents: BM<String, Vec<Entry>> = BM::new();
    for a in from {
        let name: String = name_of(a);
        if rf.root.join(pack_of(&name)).is_file() {
            return Err(E::Msg(format!("the game already ships {name}")));
        }
        let own: Vec<Entry> = sarc::parse(&rf.read_zs(&pack_of(a))?)?;
        let pl: FallPlan = plan(&[base.clone(), own.clone()], a)?;
        files.push(File { path: pack_of(&pl.name), z: zs::compress_raw(&pl.sarc, Some(id))?, raw: pl.sarc.clone(), old: 0, fresh: true });
        parents.insert(pl.name.clone(), own);
        plans.push(pl);
    }
    if plans.is_empty() {
        return Err(E::Format("falling twins: no pickup was asked for"));
    }
    let mut at: [usize; 2] = [0; 2];
    for (i, t) in [ACTOR_INFO, GAME_ACTOR_INFO, POUCH_INFO].iter().enumerate() {
        let f: File = table(&mut rf, o, modded, t, |y: &mut Byml| {
            for pl in &plans {
                let k: usize = clone_row(y, t, &pl.from, &pl.name)?;
                if i < 2 {
                    at[i] = k;
                }
            }
            Ok(())
        })?;
        files.push(f);
    }
    if at[0] != at[1] {
        return Err(E::Msg(format!("the new rows sit at {} in the actor table and at {} in the game actor table, the two tables no longer line up", at[0], at[1])));
    }
    files.push(tag_file(&mut rf, o, modded, &plans)?);
    for pl in &plans {
        let n: u32 = sizes::pack_size(pl.sarc.len())?;
        rst.set_size(&pack_of(&pl.name), n)?;
        let _ = writeln!(note, "{}: {} files, {} bytes, size table entry {n}", pl.name, pl.files.len(), pl.sarc.len());
        for (f, len) in &pl.fresh {
            let n: u32 = sizes::file_size(&rst, &pl.peers, f, *len)?;
            rst.set_size(f, n)?;
            let _ = writeln!(note, "{f}: new file in the pack, {len} bytes, size table entry {n}");
        }
        if let Some(f) = pl.files.iter().find(|f| rst.get(f).is_none()) {
            return Err(E::Msg(format!("{f} of {} has no size table entry, the game files differ", pl.name)));
        }
    }
    for f in files.iter().filter(|f| !f.fresh) {
        let was: Option<u32> = rst.get(&f.path);
        let now: Option<u32> = rst.grow(&f.path, f.old as u64, f.raw.len() as u64, MARGIN)?;
        let _ = writeln!(note, "{}: {} -> {} bytes, size table entry {:?} -> {:?}", f.path, f.old, f.raw.len(), was, now);
    }
    let mine: BS<String> = plans.iter().map(|pl| pack_of(&pl.name)).collect();
    let carried: Vec<File> = earlier(&mut rf, o.base.as_ref(), "")?.into_iter().filter(|f| !mine.contains(&f.path)).collect();
    let rst_z: Vec<u8> = rst.to_zs()?;
    for l in audit(&mut rf, o.base.as_ref(), &plans, &files, &rst_z, &parents)? {
        let _ = writeln!(note, "{l}");
    }
    let mut root: Option<PB> = None;
    if !o.dry {
        let pk: Pack = Pack::create_for(load, TITLE_ID, mod_name, o.host)?;
        for f in files.iter().chain(carried.iter()) {
            pk.write_romfs(&f.path, &f.z)?;
        }
        pk.write_romfs(TABLE_PATH, &rst_z)?;
        let _ = writeln!(note, "wrote {} files to {}", files.len() + carried.len() + 1, pk.root.display());
        root = Some(pk.root);
    }
    Ok(Done { report: note, root, files, carried, heap: 0, kept: Vec::new() })
}

pub fn audit(rf: &mut Romfs, base: Option<&PB>, plans: &[FallPlan], files: &[File], rst_z: &[u8], parents: &BM<String, Vec<Entry>>) -> Res<Vec<String>> {
    let mut out: Vec<String> = Vec::new();
    let rst: Rst = Rst::parse(&rf.zs.decompress(rst_z)?)?;
    let get = |p: &str| files.iter().find(|f| f.path == p).ok_or_else(|| E::Msg(format!("audit: {p} was not written")));
    for pl in plans {
        let pk: &File = get(&pack_of(&pl.name))?;
        let raw: Vec<u8> = rf.zs.decompress(&pk.z)?;
        if raw != pl.sarc {
            return Err(E::Msg(format!("audit: the pack of {} does not read back to its own bytes", pl.name)));
        }
        let es: Vec<Entry> = sarc::parse(&raw)?;
        let from: &[Entry] = parents.get(&pl.name).map(|v| v.as_slice()).ok_or_else(|| E::Msg(format!("audit: the pack of {} is missing", pl.from)))?;
        out.extend(verify(&es, &pl.name, from)?);
        if rst.get(&pk.path) != Some(sizes::pack_size(raw.len())?) {
            return Err(E::Msg(format!("audit: {} has the wrong size table entry", pl.name)));
        }
        for (f, len) in &pl.fresh {
            if (rst.get(f).unwrap_or(0) as usize) < *len {
                return Err(E::Msg(format!("audit: {f} has no size table entry or one below its size")));
            }
        }
        out.push(format!("pack reads back: {} files, {} bytes, dictionary {:?}, size entry {:?}", es.len(), raw.len(), dict_id(&pk.z), rst.get(&pk.path)));
    }
    for t in [ACTOR_INFO, GAME_ACTOR_INFO, POUCH_INFO] {
        let f: &File = get(t)?;
        let now: Byml = Byml::parse(&rf.zs.decompress(&f.z)?)?;
        let was: Byml = Byml::parse(&start(rf, base, t)?)?;
        out.push(audit_rows(&was, &now, t, plans)?);
        if (rst.get(t).unwrap_or(0) as usize) < f.raw.len() {
            return Err(E::Msg(format!("audit: {t} has a size table entry below its size")));
        }
    }
    let tf: &File = get(TAG)?;
    let now: Table = Table::parse(&rf.zs.decompress(&tf.z)?)?;
    if now.write()? != tf.raw {
        return Err(E::Format("audit: the tag table does not read back to its own bytes"));
    }
    if (rst.get(TAG).unwrap_or(0) as usize) < tf.raw.len() {
        return Err(E::Format("audit: the tag table has a size table entry below its size"));
    }
    let old: Table = Table::parse(&start(rf, base, TAG)?)?;
    out.push(audit_tags(&old, &now, plans)?);
    Ok(out)
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap as HM;
    use std::fs;

    use super::*;
    use crate::modpack::Host;
    use crate::pickup_pack::kit::{DYNAMIC, TOKEN};
    use crate::pickup_persist::{respawn_flags, verdict_with, Extra, Verdict};

    fn real() -> Option<PB> {
        let p: PB = ootrr_game::test_romfs::path();
        if p.join("Pack").join("ZsDic.pack.zs").is_file() {
            Some(p)
        } else {
            eprintln!("skipped, no RomFS dump at {} (set OOTRR_ROMFS)", p.display());
            None
        }
    }

    fn load(rf: &mut Romfs, name: &str) -> Vec<Entry> {
        sarc::parse(&rf.read_zs(&pack_of(name)).unwrap()).unwrap()
    }

    fn opts(base: Option<PB>, dry: bool) -> Opts {
        Opts { host: Host::Longshot, base, rst_from: None, places: Vec::new(), dry }
    }

    fn temp(tag: &str) -> PB {
        let p: PB = std::env::temp_dir().join(format!("ootrr_fall_{tag}_{}", std::process::id()));
        let _ = fs::remove_dir_all(&p);
        p
    }

    fn listed(base: &P) -> BM<String, Vec<u8>> {
        let mut out: BM<String, Vec<u8>> = BM::new();
        let mut todo: Vec<PB> = vec![base.to_path_buf()];
        while let Some(d) = todo.pop() {
            for e in fs::read_dir(&d).unwrap() {
                let p: PB = e.unwrap().path();
                if p.is_dir() {
                    todo.push(p);
                } else {
                    out.insert(p.strip_prefix(base).unwrap().to_string_lossy().replace('\\', "/"), fs::read(&p).unwrap());
                }
            }
        }
        out
    }

    #[test]
    fn only_a_hanging_pickup_gets_a_falling_twin_and_only_from_a_container() {
        assert_eq!(name_of(TOKEN), "Obj_Token_Gold_Fall");
        assert_eq!(dropped(TOKEN), "Obj_Token_Gold_Fall");
        assert_eq!(dropped("Obj_Rupee_Red"), "Obj_Rupee_Red");
        assert_eq!(dropped("Obj_Hammer_GS"), "Obj_Hammer_GS");
        assert_eq!(parent_of("Obj_Token_Gold_Fall"), Some(TOKEN));
        assert_eq!(parent_of("Obj_Rupee_Red_Fall"), None);
        assert_eq!(parent_of(TOKEN), None);
        assert!(is_fall("Obj_Token_Gold_Fall") && !is_fall("Obj_Token_Gold"));
        assert!(crate::pickup_pack::is_actor_name(&name_of(TOKEN)));
        assert!(name_of(TOKEN).len() < 25);
        assert_eq!(wanted(["Obj_Rupee_Red", "Obj_Token_Gold_Fall", "Obj_Token_Gold_Fall", TOKEN].into_iter()), vec![TOKEN]);
        assert!(wanted(["Obj_Rupee_Red", TOKEN].into_iter()).is_empty());
    }

    #[test]
    fn the_real_token_hangs_because_its_body_is_kinematic_and_the_rupee_falls_on_the_drop_item_body() {
        let Some(root) = real() else {
            return;
        };
        let mut rf: Romfs = Romfs::open(&root).unwrap();
        let tok: Pool = pool_of(&[load(&mut rf, TOKEN)]).unwrap();
        let tc: Chain = chain(&tok, TOKEN).unwrap();
        assert!(!falls(&tok, &tc).unwrap());
        assert!(auto(&tok, &tc).unwrap());
        assert_eq!(tc.comps.get(PHYSICS_REF).map(|s| s.as_str()), Some("?Component/Physics/Obj_Token_Gold.engine__component__PhysicsParam.bgyml"));
        let body: Byml = tok.byml("Phive/RigidBodyEntityParam/Token_Gold_0.phive__RigidBodyEntityParam.bgyml").unwrap();
        assert_eq!(body.root.get("MotionType"), Some(&Node::U32(crate::murmur::murmur3_32(b"Kinematic", 0))));
        let rupee: Pool = pool_of(&[load(&mut rf, "Obj_Rupee_Red")]).unwrap();
        assert!(falls(&rupee, &chain(&rupee, "Obj_Rupee_Red").unwrap()).unwrap());
        let drop: Byml = rupee.byml("Phive/RigidBodyEntityParam/DropItem_0.phive__RigidBodyEntityParam.bgyml").unwrap();
        assert_eq!(drop.root.get("MotionType"), Some(&Node::U32(DYNAMIC)));
        let base: Pool = pool_of(&[load(&mut rf, BASE)]).unwrap();
        assert!(falls(&base, &chain(&base, BASE).unwrap()).unwrap());
    }

    #[test]
    fn the_real_twin_is_the_token_with_the_drop_item_body_and_nothing_else() {
        let Some(root) = real() else {
            return;
        };
        let mut rf: Romfs = Romfs::open(&root).unwrap();
        let tok: Vec<Entry> = load(&mut rf, TOKEN);
        let base: Vec<Entry> = load(&mut rf, BASE);
        let pl: FallPlan = plan(&[base.clone(), tok.clone()], TOKEN).unwrap();
        assert_eq!(pl.name, "Obj_Token_Gold_Fall");
        assert_eq!(pl.fresh.len(), 1);
        let es: Vec<Entry> = sarc::parse(&pl.sarc).unwrap();
        let y: Byml = Byml::parse(&sarc::get(&es, &actor_file(&pl.name)).unwrap().data).unwrap();
        assert_eq!(y.root.get(PARENT).and_then(|v| v.as_str()), Some("Work/Actor/Obj_Token_Gold.engine__actor__ActorParam.gyml"));
        let c: &Node = y.root.get(COMPONENTS).unwrap();
        assert_eq!(c.get(PHYSICS_REF).and_then(|v| v.as_str()), Some("?Component/Physics/Obj_Item_Base.engine__component__PhysicsParam.bgyml"));
        assert!(matches!(c, Node::Map(m) if m.len() == 1));
        assert_eq!(verify(&es, &pl.name, &tok).unwrap().len(), 2);
        for f in ["AI/Item_Token_Gold.root.ainb", "Component/DeathParam/Item_Token_Gold.game__component__DeathParam.bgyml", "Component/PouchContentParam/Obj_Token_Gold.game__component__PouchContentParam.bgyml", "Phive/RigidBodyEntityParam/DropItem_0.phive__RigidBodyEntityParam.bgyml"] {
            assert!(sarc::get(&es, f).is_some(), "{f}");
        }
        for f in ["Phive/RigidBodyEntityParam/Token_Gold_0.phive__RigidBodyEntityParam.bgyml", "Component/Physics/Obj_Token_Gold.engine__component__PhysicsParam.bgyml"] {
            assert!(sarc::get(&es, f).is_none(), "{f}");
        }
        assert!(plan(&[tok.clone()], TOKEN).is_err());
        assert!(plan(&[base.clone(), load(&mut rf, "Obj_Rupee_Red")], "Obj_Rupee_Red").is_err());
        let again: FallPlan = plan(&[base, tok.clone()], TOKEN).unwrap();
        assert_eq!(again.sarc, pl.sarc);
        let mut bent: Vec<Entry> = es.clone();
        let i: usize = bent.iter().position(|e| e.name == "AI/Item_Token_Gold.root.ainb").unwrap();
        bent[i].data.push(0);
        assert!(verify(&bent, &pl.name, &tok).is_err());
    }

    #[test]
    fn the_real_twin_writes_three_rows_a_tag_row_and_its_size_entries_and_a_rerun_is_stable() {
        let Some(root) = real() else {
            return;
        };
        let mut rf: Romfs = Romfs::open(&root).unwrap();
        let d: Done = run(&root, P::new("unused"), "unused", &[TOKEN], &opts(None, true)).unwrap();
        assert!(d.root.is_none());
        let paths: Vec<&str> = d.files.iter().map(|f| f.path.as_str()).collect();
        assert_eq!(paths, vec!["Pack/Actor/Obj_Token_Gold_Fall.pack.zs", ACTOR_INFO, GAME_ACTOR_INFO, POUCH_INFO, TAG]);
        assert!(d.report.contains("8363 -> 8364 rows"), "{}", d.report);
        assert!(d.report.contains("395 -> 396 rows"), "{}", d.report);
        assert!(d.report.contains("Obj_Token_Gold_Fall carries [\"Token_Gold\"] like Obj_Token_Gold"), "{}", d.report);
        let g: Byml = Byml::parse(&d.files[2].raw).unwrap();
        let r: &Node = rows::find(&g, "Obj_Token_Gold_Fall").unwrap();
        assert_eq!(r.get(rows::RESPAWN), Some(&Node::Bool(true)));
        assert_eq!(r.get(rows::LAYER).and_then(|v| v.as_str()), Some("SmallObject"));
        let q: Byml = Byml::parse(&d.files[3].raw).unwrap();
        assert_eq!(rows::find(&q, "Obj_Token_Gold_Fall").and_then(|r| r.get("PouchSpecialDeal")).and_then(|v| v.as_str()), Some("TokenGold"));
        let x: Extra = crate::pickup_pack::guard::extra(&d.files, &d.carried).unwrap();
        let flags: HM<String, bool> = respawn_flags(&mut rf).unwrap();
        let v: Verdict = verdict_with(&mut rf, &flags, &x, "Obj_Token_Gold_Fall").unwrap();
        let t: Verdict = verdict_with(&mut rf, &flags, &Extra::default(), TOKEN).unwrap();
        assert_eq!((v.respawn, v.setting.as_str(), v.table.as_str(), &v.cells), (t.respawn, t.setting.as_str(), t.table.as_str(), &t.cells));
        assert_eq!(v.table, crate::pickup_pack::kit::DEATH_TABLE);
        let load: PB = temp("rerun");
        let one: Done = run(&root, &load, "one", &[TOKEN], &opts(None, false)).unwrap();
        let dir: PB = one.root.unwrap().join("romfs");
        let first: BM<String, Vec<u8>> = listed(&dir);
        assert_eq!(first.len(), 6);
        run(&root, &load, "one", &[TOKEN], &opts(Some(dir.clone()), false)).unwrap();
        let second: BM<String, Vec<u8>> = listed(&dir);
        let moved: Vec<&String> = first.keys().filter(|k| second.get(*k) != first.get(*k)).collect();
        assert!(moved.is_empty(), "{moved:?}");
        assert_eq!(second.len(), first.len());
        assert!(run(&root, &load, "x", &["Obj_Rupee_Red"], &opts(None, true)).is_err());
        assert!(run(&root, &load, "x", &[], &opts(None, true)).is_err());
        let _ = fs::remove_dir_all(&load);
    }
}
