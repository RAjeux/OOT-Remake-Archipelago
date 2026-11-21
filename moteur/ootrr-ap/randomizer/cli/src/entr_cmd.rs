use std::collections::{BTreeMap as BM, BTreeSet as BS};
use std::fs;
use std::path::{Path as P, PathBuf as PB};

use ootrr_core::TITLE_ID;
use ootrr_core::byml::{Byml, Node};
use ootrr_core::entr::build::{moves, stage, swap_moves, Move, Staged};
use ootrr_core::entr::data::{load, Cat, Door, DEST_KEYS};
use ootrr_core::entr::layout::{ages_fit, Layout};
use ootrr_core::entr::pools::{find, DUNGEONS};
use ootrr_core::entrance_swap::{diff, select};
use ootrr_core::entrances::{self as en, Analysis, Scan, St, StartIdx};
use ootrr_core::error::{Error, Res};
use ootrr_core::modpack::{Host, Pack};
use ootrr_core::placement::hash_of;
use ootrr_core::romfs::Romfs;
use ootrr_core::rsizetable::{self, align, Rst, TABLE_PATH};
use ootrr_core::slice::edit::{Edited, MARGIN};
use ootrr_core::zs;

struct Opts {
    host: Host,
    age: Option<String>,
    swaps: Vec<(String, String)>,
    dungeons: Vec<(String, String)>,
    pos: Vec<String>,
}

fn opts(a: &[String]) -> Res<Opts> {
    let mut o: Opts = Opts { host: Host::Eden, age: None, swaps: Vec::new(), dungeons: Vec::new(), pos: Vec::new() };
    let mut i: usize = 0;
    let get = |i: usize, what: &'static str| -> Res<String> { a.get(i).cloned().ok_or(Error::Format(what)) };
    while i < a.len() {
        match a[i].as_str() {
            "--host" => {
                o.host = Host::parse(&get(i + 1, "--host needs a value")?).ok_or(Error::Format("--host is eden, hookshot or nx2navi"))?;
                i += 2;
            }
            "--age" => {
                let v: String = get(i + 1, "--age needs adult or child")?;
                if v != "adult" && v != "child" {
                    return Err(Error::Format("--age needs adult or child"));
                }
                o.age = Some(v);
                i += 2;
            }
            "--swap" => {
                o.swaps.push((get(i + 1, "--swap needs two entrances")?, get(i + 2, "--swap needs two entrances")?));
                i += 3;
            }
            "--dungeon" => {
                let v: String = get(i + 1, "--dungeon needs Spot=Dungeon")?;
                let (k, d): (&str, &str) = v.split_once('=').ok_or(Error::Format("--dungeon needs Spot=Dungeon"))?;
                o.dungeons.push((k.to_string(), d.to_string()));
                i += 2;
            }
            _ => {
                o.pos.push(a[i].clone());
                i += 1;
            }
        }
    }
    Ok(o)
}

fn arg<'a>(v: &'a [String], i: usize, what: &'static str) -> Res<&'a str> {
    v.get(i).map(|s| s.as_str()).ok_or(Error::Format(what))
}

fn side(s: &Scan, an: &Analysis, sel: &str, age: &Option<String>) -> Res<(Vec<u64>, Vec<u64>)> {
    let keep = |e: &en::Ent| -> bool { age.as_deref().is_none_or(|a| e.age == a || e.age == "both") };
    let idx: Vec<usize> = select(s, sel)?.into_iter().filter(|i| keep(&s.ents[*i])).collect();
    let mut back: BS<u64> = BS::new();
    for i in &idx {
        for (_, h) in &an.rows[*i].rets {
            let r: Option<&en::Ent> = s.ents.iter().find(|e| e.hash == *h);
            if r.is_some_and(keep) {
                back.insert(*h);
            }
        }
    }
    let named: Vec<(String, String)> = s.ents.iter().filter(|e| back.contains(&e.hash)).map(|e| (en::base(&e.map), e.name.clone())).collect();
    for e in &s.ents {
        if keep(e) && named.contains(&(en::base(&e.map), e.name.clone())) {
            back.insert(e.hash);
        }
    }
    let fwd: Vec<u64> = idx.iter().map(|i| s.ents[*i].hash).collect();
    if fwd.is_empty() || back.is_empty() {
        return Err(Error::Msg(format!("{sel} has no entrance or no way back for that age, pick a two way transition")));
    }
    Ok((fwd, back.into_iter().collect()))
}

fn fits(param: &str, age: &str) -> bool {
    let a: &str = en::age_of(param);
    a == "both" || a == age
}

fn served(cat: &Cat, s: &Scan, ix: &StartIdx, t: u64, src: u64) -> Res<Vec<String>> {
    let to: &Door = cat.door(t)?;
    let from: &Door = cat.door(src)?;
    let mut bad: Vec<String> = Vec::new();
    for a in &to.ages {
        let p: &str = if a == "adult" { &from.adult } else { &from.child };
        if en::resolve(s, ix, p, &from.start) != St::Ok || !fits(p, a) {
            bad.push(format!("{}/{} ({t}) would send the {a} player to {p}/{}", to.map, to.name, from.start));
        }
    }
    Ok(bad)
}

fn check_catalog(cat: &Cat, s: &Scan) -> Res<()> {
    for e in &s.ents {
        let d: &Door = cat.door(e.hash)?;
        if d.file != e.file || d.start != e.start || d.adult != e.adult || d.child != e.child {
            return Err(Error::Msg(format!("data/entrances.json does not match these game files at {} {}", e.map, e.name)));
        }
    }
    Ok(())
}

fn write_mod(rf: &mut Romfs, load_dir: &str, name: &str, host: Host, edits: &[Edited]) -> Res<PB> {
    let pk: Pack = Pack::begin_for(P::new(load_dir), TITLE_ID, name, host)?;
    let mut rst: Rst = rsizetable::load(rf)?;
    for e in edits {
        let z: Vec<u8> = zs::compress_raw(&e.bytes, Some(3))?;
        if rf.zs.decompress(&z)? != e.bytes {
            return Err(Error::Format("compressed output does not round trip"));
        }
        pk.write_romfs(&e.file, &z)?;
        let g: Option<u32> = rst.grow(&e.file, e.old_len as u64, e.bytes.len() as u64, MARGIN)?;
        println!("{}  {} -> {} bytes, size table entry {}", e.file, e.old_len, e.bytes.len(), g.map(|x| x.to_string()).unwrap_or_else(|| "absent".to_string()));
    }
    if host == Host::Hookshot {
        rsizetable::fold_mods(&mut rst, P::new(load_dir), name)?;
    }
    pk.write_romfs(TABLE_PATH, &rst.to_zs()?)?;
    pk.commit()?;
    Ok(pk.root.clone())
}

pub fn make(a: &[String]) -> Res<()> {
    let o: Opts = opts(a)?;
    let root: &str = arg(&o.pos, 0, "missing romfs_root")?;
    let load_dir: &str = arg(&o.pos, 1, "missing load_dir")?;
    let name: &str = arg(&o.pos, 2, "missing mod_name")?;
    if o.swaps.is_empty() && o.dungeons.is_empty() {
        return Err(Error::Format("give at least one --swap A B or --dungeon Spot=Dungeon"));
    }
    let mut rf: Romfs = Romfs::open(P::new(root))?;
    let s: Scan = en::scan(&mut rf)?;
    let an: Analysis = en::analyze(&s);
    let ix: StartIdx = en::start_index(&s);
    let cat: Cat = load()?;
    check_catalog(&cat, &s)?;
    let mut mv: Vec<Move> = Vec::new();
    let mut bad: Vec<String> = Vec::new();
    for (x, y) in &o.swaps {
        let a: (Vec<u64>, Vec<u64>) = side(&s, &an, x, &o.age)?;
        let b: (Vec<u64>, Vec<u64>) = side(&s, &an, y, &o.age)?;
        println!("swap {x} ({} doors, {} ways back) with {y} ({} doors, {} ways back)", a.0.len(), a.1.len(), b.0.len(), b.1.len());
        for m in swap_moves(&cat, (&a.0, &a.1), (&b.0, &b.1))? {
            bad.extend(served(&cat, &s, &ix, m.0, m.1)?);
            mv.push(m);
        }
    }
    if !o.dungeons.is_empty() {
        let mut l: Layout = Layout::vanilla();
        for (k, d) in &o.dungeons {
            let i: usize = find(k).ok_or_else(|| Error::Msg(format!("{k} is not a dungeon entrance")))?;
            let j: usize = find(d).ok_or_else(|| Error::Msg(format!("{d} is not a dungeon")))?;
            l.at[i] = j;
        }
        l.check()?;
        bad.extend(ages_fit(&cat, &l)?);
        for (spot, d) in l.at.iter().enumerate() {
            if spot != *d {
                println!("the {} entrance leads to {}", DUNGEONS[spot].name, DUNGEONS[*d].name);
            }
        }
        mv.extend(moves(&cat, &l)?);
    }
    if !bad.is_empty() {
        return Err(Error::Msg(format!("refused, the swap would break an arrival:\n  {}", bad.join("\n  "))));
    }
    let mut edits: Vec<Edited> = Vec::new();
    let st: Staged = stage(&mut rf, &cat, &mv, &mut edits)?;
    for (t, src) in &mv {
        let to: &Door = cat.door(*t)?;
        let from: &Door = cat.door(*src)?;
        println!("  {}/{} now leads to adult {} child {} at {}", to.map, to.name, from.adult, from.child, from.start);
    }
    let at: PB = write_mod(&mut rf, load_dir, name, o.host, &edits)?;
    println!("{} entrance actors rewritten in {} files", st.actors, st.files.len());
    println!("mod folder: {}", at.display());
    Ok(())
}

fn banc_in(dir: &P, base: &P, out: &mut Vec<String>) -> Res<()> {
    for e in fs::read_dir(dir)? {
        let p: PB = e?.path();
        if p.is_dir() {
            banc_in(&p, base, out)?;
        } else if p.to_string_lossy().ends_with(".bcett.byml.zs") {
            let r: String = p.strip_prefix(base).map_err(|_| Error::Format("bad mod path"))?.to_string_lossy().replace('\\', "/");
            out.push(r);
        }
    }
    Ok(())
}

fn actor_at(y: &Byml, i: usize) -> Option<&Node> {
    y.root.get("Actors")?.as_arr()?.get(i)
}

pub fn verify(a: &[String]) -> Res<()> {
    let root: &str = arg(a, 0, "missing romfs_root")?;
    let m: PB = PB::from(arg(a, 1, "missing mod folder")?);
    let base: PB = m.join("romfs");
    let mut rf: Romfs = Romfs::open(P::new(root))?;
    let s: Scan = en::scan(&mut rf)?;
    let ix: StartIdx = en::start_index(&s);
    let cat: Cat = load()?;
    let van: Rst = rsizetable::load(&mut rf)?;
    let mine: Option<Rst> = match fs::read(base.join(TABLE_PATH)) {
        Ok(b) => Some(Rst::parse(&rf.zs.decompress(&b)?)?),
        Err(_) => None,
    };
    let mut files: Vec<String> = Vec::new();
    if base.join("Banc").is_dir() {
        banc_in(&base.join("Banc"), &base, &mut files)?;
    }
    files.sort();
    let mut fails: usize = 0;
    let mut changed: usize = 0;
    let mut by_kind: BM<&str, usize> = BM::new();
    for f in &files {
        let raw: Vec<u8> = rf.zs.decompress(&fs::read(base.join(f))?)?;
        let y: Byml = Byml::parse(&raw)?;
        let exact: bool = y.write()? == raw;
        let old_raw: Vec<u8> = rf.read_zs(f)?;
        let old: Byml = Byml::parse(&old_raw)?;
        let mut d: Vec<String> = Vec::new();
        diff(&old.root, &y.root, "", &mut d);
        let mut hit: BS<usize> = BS::new();
        let mut others: usize = 0;
        for p in &d {
            let gate: Option<usize> = p
                .strip_prefix(".Actors[")
                .and_then(|r| r.split_once(']'))
                .filter(|(_, t)| DEST_KEYS.iter().any(|k| t.split(": ").next() == Some(&format!(".Dynamic.{k}"))))
                .and_then(|(i, _)| i.parse::<usize>().ok())
                .filter(|i| actor_at(&y, *i).and_then(|n| n.get("Gyaml")).and_then(|g| g.as_str()) == Some(en::ENTRANCE));
            match gate {
                Some(i) => {
                    hit.insert(i);
                    *by_kind.entry("entrance field").or_insert(0) += 1;
                }
                None => {
                    others += 1;
                    *by_kind.entry("other change").or_insert(0) += 1;
                }
            }
        }
        let grow: bool = raw.len() > old_raw.len();
        let size_ok: bool = if !grow {
            true
        } else {
            match (mine.as_ref().and_then(|t| t.get(f)), van.get(f)) {
                (Some(n), Some(v)) => n as u64 >= v as u64 + align(raw.len() as u64) - align(old_raw.len() as u64),
                (None, Some(_)) => false,
                (_, None) => true,
            }
        };
        println!(
            "{f}: {} -> {} bytes, rewrites byte exact {exact}, {} entrance actors changed, {} other differences, size table {}",
            old_raw.len(),
            raw.len(),
            hit.len(),
            others,
            if !grow { "not needed".to_string() } else if size_ok { "ok".to_string() } else { "TOO SMALL".to_string() }
        );
        if !exact || !size_ok {
            fails += 1;
        }
        for i in hit {
            changed += 1;
            let n: &Node = actor_at(&y, i).ok_or(Error::Format("actor vanished"))?;
            let h: u64 = hash_of(n).unwrap_or(0);
            let dy: Option<&Node> = n.get("Dynamic");
            let g = |k: &str| -> String { dy.and_then(|x| x.get(k)).and_then(|v| v.as_str()).unwrap_or("").to_string() };
            let (pa, pc, st): (String, String, String) = (g("NextBancParamNameAdult"), g("NextBancParamNameChild"), g("NextStartPosName"));
            let door: Option<&Door> = cat.doors.get(&h);
            let ages: Vec<String> = door.map(|x| x.ages.clone()).unwrap_or_default();
            let mut verdict: Vec<String> = Vec::new();
            for age in &ages {
                let p: &str = if age == "adult" { &pa } else { &pc };
                let ok: bool = en::resolve(&s, &ix, p, &st) == St::Ok && fits(p, age);
                verdict.push(format!("{age} {}", if ok { "ok" } else { "MISSING" }));
            }
            println!(
                "  {} {} ({h}) -> adult {pa} child {pc} at {st}, arrival {} | {}",
                door.map(|x| x.map.as_str()).unwrap_or("?"),
                door.map(|x| x.name.as_str()).unwrap_or("?"),
                g("NextEventName"),
                verdict.join(", ")
            );
        }
    }
    println!("{} Banc files in the mod, {changed} entrance actors changed, {:?}", files.len(), by_kind);
    if mine.is_none() && !files.is_empty() {
        println!("no size table in the mod");
    }
    if fails > 0 {
        return Err(Error::Msg(format!("{fails} files failed the read back or size table check")));
    }
    println!("read back and size table checks passed");
    Ok(())
}
