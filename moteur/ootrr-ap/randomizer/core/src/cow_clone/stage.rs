use std::collections::BTreeMap as BM;
use std::fs;
use std::path::PathBuf as PB;

use crate::byml::Byml;
use crate::cow_clone::data::{Cow, PLAIN, TEMPLATE};
use crate::cow_clone::pack::{self, pack_of, path, SCHEDULE};
use crate::cow_clone::rows;
use crate::error::{Error as E, Res};
use crate::flow_locations::{dict_id, path_of};
use crate::modpack::Pack;
use crate::pickup_pack::rows::{ACTOR_INFO, GAME_ACTOR_INFO};
use crate::pickup_pack::sizes::{file_size, pack_size};
use crate::pickup_pack::tag::{Table, TAG};
use crate::pickup_pack::PACK_DICT;
use crate::progressive::{ANALYZED_TABLE, SETTING_TABLE};
use crate::qol::{edit_zs, Have};
use crate::romfs::Romfs;
use crate::rsizetable::{self, Rst};
use crate::sarc::{self, Entry};
use crate::slice::pickups::swap_gyaml;
use crate::staging::{grow_out, Out, BANC_DICT};
use crate::zs;

#[derive(Clone, Debug, Default)]
pub struct Made {
    pub outs: Vec<Out>,
    pub sizes: Vec<(String, u32)>,
    pub lines: Vec<String>,
}

fn current(rf: &mut Romfs, have: Have, p: &str) -> Res<Vec<u8>> {
    match have(p) {
        Some(z) => rf.zs.decompress(&z),
        None => rf.read_zs(p),
    }
}

fn table(rf: &mut Romfs, have: Have, p: &str, f: impl FnOnce(&mut Byml) -> Res<()>) -> Res<Out> {
    edit_zs(rf, have, p, |raw: &[u8]| {
        let mut y: Byml = Byml::parse(raw)?;
        f(&mut y)?;
        y.write()
    })
}

fn banc(rf: &mut Romfs, have: Have, file: &str, cows: &[&Cow]) -> Res<(Out, Vec<String>)> {
    let raw: Vec<u8> = current(rf, have, file)?;
    let mut y: Byml = Byml::parse(&raw)?;
    let mut lines: Vec<String> = Vec::new();
    for c in cows {
        for s in c.spots.iter().filter(|s| s.file == file) {
            let n: usize = swap_gyaml(&mut y, s.hash, PLAIN, &c.class);
            if n != 1 {
                return Err(E::Msg(format!("cow clone: {file} holds {n} {PLAIN} actors with the hash {}, not one, the game files differ", s.hash)));
            }
            lines.push(format!("{file}: actor {} {PLAIN} -> {}", s.hash, c.class));
        }
    }
    let out: Vec<u8> = y.write()?;
    let id: u32 = dict_id(&rf.read(file)?).unwrap_or(BANC_DICT);
    Ok((Out { path: file.to_string(), z: zs::compress_raw(&out, Some(id))?, old: raw.len(), new: out.len() }, lines))
}

fn peers(es: &[Entry]) -> Vec<(String, usize)> {
    es.iter().map(|e| (e.name.clone(), e.data.len())).collect()
}

pub fn stage(rf: &mut Romfs, have: Have, cows: &[&Cow], rst: &Rst, flows: &[(String, usize)]) -> Res<Made> {
    let mut m: Made = Made::default();
    if cows.is_empty() {
        return Ok(m);
    }
    let hraw: Vec<u8> = rf.read_zs(&pack_of(TEMPLATE))?;
    let house: Vec<Entry> = sarc::parse(&hraw)?;
    let house_len: usize = hraw.len();
    let pid: u32 = dict_id(&rf.read(&pack_of(TEMPLATE))?).unwrap_or(PACK_DICT);
    let near: Vec<(String, usize)> = peers(&house);
    let plan_raw: Vec<u8> = rf.read(&path(SCHEDULE, TEMPLATE))?;
    let plan_peer: Vec<(String, usize)> = vec![(path(SCHEDULE, TEMPLATE), plan_raw.len())];
    let flow_peer: Vec<(String, usize)> = vec![(path_of(&format!("{TEMPLATE}.bfevfl")), rf.read_zs(&path_of(&format!("{TEMPLATE}.bfevfl")))?.len())];
    let mut packs: Vec<(String, Vec<u8>)> = Vec::new();
    for c in cows {
        if rf.root.join(pack_of(&c.class)).is_file() {
            return Err(E::Msg(format!("cow clone: the game already ships {}", c.class)));
        }
        let es: Vec<Entry> = pack::build(&house, &c.class)?;
        let raw: Vec<u8> = sarc::write(&es)?;
        for e in es.iter().filter(|e| e.name.contains(c.class.as_str())) {
            m.sizes.push((e.name.clone(), file_size(rst, &near, &e.name, e.data.len())?));
        }
        let p: String = pack_of(&c.class);
        m.sizes.push((p.clone(), pack_size(raw.len())?));
        m.outs.push(Out { path: p.clone(), z: zs::compress_raw(&raw, Some(pid))?, old: 0, new: raw.len() });
        let s: Vec<u8> = pack::schedule(&plan_raw, &c.class)?;
        let sp: String = path(SCHEDULE, &c.class);
        m.sizes.push((sp.clone(), file_size(rst, &plan_peer, &sp, s.len())?));
        m.outs.push(Out { path: sp, new: s.len(), z: s, old: 0 });
        let fp: String = path_of(&c.flow_file());
        let len: usize = flows.iter().find(|f| f.0 == fp).map(|f| f.1).ok_or_else(|| E::Msg(format!("cow clone: the flow of {} was not staged", c.class)))?;
        m.sizes.push((fp, file_size(rst, &flow_peer, &path_of(&c.flow_file()), len)?));
        m.lines.push(format!("{}: new actor class for {}, pack {} bytes with {} files, schedule, flow {} bytes", c.class, c.location, raw.len(), es.len(), len));
        packs.push((c.class.clone(), raw));
    }
    let (iraw, graw): (Vec<u8>, Vec<u8>) = (current(rf, have, ACTOR_INFO)?, current(rf, have, GAME_ACTOR_INFO)?);
    let mut info: Byml = Byml::parse(&iraw)?;
    let mut game: Byml = Byml::parse(&graw)?;
    let (ai, gi): (usize, usize) = (iraw.len(), graw.len());
    for (class, raw) in &packs {
        rows::actors(&mut info, &mut game, class, house_len, raw.len())?;
    }
    for (p, y, old) in [(ACTOR_INFO, &info, ai), (GAME_ACTOR_INFO, &game, gi)] {
        let out: Vec<u8> = y.write()?;
        m.outs.push(Out { path: p.to_string(), z: zs::compress_raw(&out, dict_id(&rf.read(p)?))?, old, new: out.len() });
    }
    m.outs.push(table(rf, have, SETTING_TABLE, |y: &mut Byml| {
        for c in cows {
            rows::events(y, &c.class)?;
        }
        Ok(())
    })?);
    m.outs.push(table(rf, have, ANALYZED_TABLE, |y: &mut Byml| {
        for c in cows {
            rows::analyzed(y, &c.class)?;
        }
        Ok(())
    })?);
    let traw: Vec<u8> = current(rf, have, TAG)?;
    let mut t: Table = Table::parse(&traw)?;
    for c in cows {
        rows::tags(&mut t, &c.class)?;
    }
    let tout: Vec<u8> = t.write()?;
    m.outs.push(Out { path: TAG.to_string(), z: zs::compress_raw(&tout, dict_id(&rf.read(TAG)?))?, old: traw.len(), new: tout.len() });
    let mut by: BM<String, Vec<&Cow>> = BM::new();
    for c in cows {
        for s in &c.spots {
            let v: &mut Vec<&Cow> = by.entry(s.file.clone()).or_default();
            if !v.iter().any(|x| x.class == c.class) {
                v.push(c);
            }
        }
    }
    for (file, cs) in &by {
        let (o, lines): (Out, Vec<String>) = banc(rf, have, file, cs)?;
        m.outs.push(o);
        m.lines.extend(lines);
    }
    Ok(m)
}

pub fn sources() -> Vec<String> {
    vec![
        pack_of(TEMPLATE),
        path(SCHEDULE, TEMPLATE),
        path_of(&format!("{PLAIN}.bfevfl")),
        path_of(&format!("{TEMPLATE}.bfevfl")),
        ACTOR_INFO.to_string(),
        GAME_ACTOR_INFO.to_string(),
        TAG.to_string(),
        SETTING_TABLE.to_string(),
        ANALYZED_TABLE.to_string(),
    ]
}

pub fn sized(rf: &mut Romfs, t: &mut Rst, m: &Made) -> Res<usize> {
    let mut n: usize = 0;
    for (p, sz) in &m.sizes {
        t.set_size(p, *sz)?;
        n += 1;
    }
    for o in m.outs.iter().filter(|o| !m.sizes.iter().any(|s| s.0 == o.path)) {
        n += grow_out(rf, t, o)?;
    }
    Ok(n)
}

pub fn active(staged: &[(String, usize)]) -> Vec<Cow> {
    crate::cow_clone::data::all().into_iter().filter(|c| staged.iter().any(|s| s.0 == path_of(&c.flow_file()))).collect()
}

pub fn write(rf: &mut Romfs, pk: &Pack, rst: &mut Option<Rst>) -> Res<(usize, Vec<String>)> {
    let root: PB = pk.work.join("romfs");
    let mut flows: Vec<(String, usize)> = Vec::new();
    for c in crate::cow_clone::data::all() {
        let p: String = path_of(&c.flow_file());
        let f: PB = p.split('/').fold(root.clone(), |a, s| a.join(s));
        if f.is_file() {
            flows.push((p, rf.zs.decompress(&fs::read(f)?)?.len()));
        }
    }
    let cows: Vec<Cow> = active(&flows);
    if cows.is_empty() {
        return Ok((0, Vec::new()));
    }
    if rst.is_none() {
        *rst = Some(rsizetable::load(rf)?);
    }
    let t: &mut Rst = rst.as_mut().ok_or(E::Format("cow clone: no size table"))?;
    let have = |p: &str| -> Option<Vec<u8>> { fs::read(p.split('/').fold(root.clone(), |a, s| a.join(s))).ok() };
    let refs: Vec<&Cow> = cows.iter().collect();
    let m: Made = stage(rf, &have, &refs, t, &flows)?;
    for o in &m.outs {
        pk.write_romfs(&o.path, &o.z)?;
    }
    sized(rf, t, &m)?;
    Ok((m.outs.len(), m.lines))
}
