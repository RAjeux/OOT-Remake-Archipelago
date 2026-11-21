use std::collections::BTreeMap as BM;

use crate::bfevfl::flow::NONE;
use crate::bfevfl::{Actor, Bf, Case, Cont, Entry, Event, Flow, Kind, Val};
use crate::cow_clone::data::{of_file, PLAIN, TEMPLATE};
use crate::error::{Error as E, Res};
use crate::flow_locations::{dict_id, path_of};
use crate::romfs::Romfs;

pub const TALK: &str = "Talk";
pub const GIVE: &str = "GiveMilk";
pub const PUSH: &str = "PushToBottleMilk";
pub const DONOR: &str = "PushToBottleMilk_LinkHouse";
pub const TALK_CALL: &str = "CowTalk";
pub const GIVE_CALL: &str = "Cow_GiveMilk";
pub const OLD_PUSH: &str = "Animal_Cow_PushToBottleMilk_LinkHouse";
pub const HEAD: u16 = 2;

pub fn talk_row(class: &str) -> String {
    format!("{class}_D_T")
}

pub fn give_row(class: &str) -> String {
    format!("{class}_GiveMilk")
}

pub fn push_row(class: &str) -> String {
    format!("{class}_PushToBottleMilk")
}

fn outs(k: &Kind) -> Vec<u16> {
    match k {
        Kind::Action { next, .. } | Kind::Join { next } | Kind::Sub { next, .. } => vec![*next],
        Kind::Switch { cases, .. } | Kind::SubSwitch { cases, .. } => cases.iter().map(|c| c.ev).collect(),
        Kind::Fork { join, forks } => forks.iter().copied().chain([*join]).collect(),
        Kind::Label { .. } => Vec::new(),
    }
}

pub fn order(f: &Flow, main: u16) -> Vec<u16> {
    let mut out: Vec<u16> = Vec::new();
    let mut at: usize = 0;
    if main != NONE && usize::from(main) < f.events.len() {
        out.push(main);
    }
    while at < out.len() {
        let i: u16 = out[at];
        at += 1;
        for n in outs(&f.events[usize::from(i)].kind) {
            if n != NONE && usize::from(n) < f.events.len() && !out.contains(&n) {
                out.push(n);
            }
        }
    }
    out
}

fn moved(i: u16, m: &BM<u16, u16>) -> Res<u16> {
    if i == NONE {
        return Ok(NONE);
    }
    m.get(&i).copied().ok_or_else(|| E::Msg(format!("cow clone: event {i} leaves the copied part of the flow")))
}

fn cases(cs: &[Case], m: &BM<u16, u16>) -> Res<Vec<Case>> {
    cs.iter().map(|c| Ok(Case { val: c.val, ev: moved(c.ev, m)? })).collect()
}

fn renamed(p: &Option<Cont>, class: &str) -> Option<Cont> {
    let mut c: Cont = p.clone()?;
    for (_, v) in c.items.iter_mut() {
        match v {
            Val::Str(s) if s == TEMPLATE => *s = class.to_string(),
            Val::Actor(s, _) if s == TEMPLATE => *s = class.to_string(),
            _ => {}
        }
    }
    Some(c)
}

fn relink(k: &Kind, ev: &BM<u16, u16>, ac: &BM<u16, u16>, class: &str) -> Res<Kind> {
    let actor = |a: u16| ac.get(&a).copied().ok_or_else(|| E::Msg(format!("cow clone: actor {a} was not copied")));
    Ok(match k {
        Kind::Action { next, actor: a, act, params } => Kind::Action { next: moved(*next, ev)?, actor: actor(*a)?, act: *act, params: renamed(params, class) },
        Kind::Switch { actor: a, query, cases: cs, params } => Kind::Switch { actor: actor(*a)?, query: *query, cases: cases(cs, ev)?, params: renamed(params, class) },
        Kind::Fork { join, forks } => Kind::Fork { join: moved(*join, ev)?, forks: forks.iter().map(|x| moved(*x, ev)).collect::<Res<Vec<u16>>>()? },
        Kind::Join { next } => Kind::Join { next: moved(*next, ev)? },
        Kind::Sub { next, params, flow, entry } => Kind::Sub { next: moved(*next, ev)?, params: renamed(params, class), flow: flow.clone(), entry: entry.clone() },
        Kind::SubSwitch { cases: cs, params, flow, entry } => Kind::SubSwitch { cases: cases(cs, ev)?, params: renamed(params, class), flow: flow.clone(), entry: entry.clone() },
        Kind::Label { hash } => Kind::Label { hash: *hash },
    })
}

fn actor_of(k: &Kind) -> Option<u16> {
    match k {
        Kind::Action { actor, .. } | Kind::Switch { actor, .. } => Some(*actor),
        _ => None,
    }
}

fn idx(n: usize) -> Res<u16> {
    u16::try_from(n).map_err(|_| E::Format("cow clone: index does not fit in 16 bits"))
}

pub fn graft(to: &mut Flow, from: &Flow, entry: &str, name: &str, class: &str) -> Res<BM<u16, u16>> {
    let en: &Entry = from.entries.iter().find(|e| e.name == entry).ok_or_else(|| E::Msg(format!("cow clone: {} has no entry {entry}, the game files differ", from.name)))?;
    let list: Vec<u16> = order(from, en.main);
    let mut ev: BM<u16, u16> = BM::new();
    for (n, i) in list.iter().enumerate() {
        ev.insert(*i, idx(to.events.len() + n)?);
    }
    let mut ac: BM<u16, u16> = BM::new();
    for i in &list {
        let Some(a) = actor_of(&from.events[usize::from(*i)].kind) else { continue };
        if ac.contains_key(&a) {
            continue;
        }
        let src: &Actor = from.actors.get(usize::from(a)).ok_or_else(|| E::Msg(format!("cow clone: actor {a} is out of range")))?;
        let want: String = if src.name == TEMPLATE && src.sub.is_empty() { class.to_string() } else { src.name.clone() };
        if !src.sub.is_empty() || !src.arg.is_empty() {
            return Err(E::Msg(format!("cow clone: event of {entry} uses the argument actor {}", src.name)));
        }
        let at: usize = match to.actors.iter().position(|x| x.name == want && x.sub.is_empty()) {
            Some(p) if to.actors[p].actions == src.actions && to.actors[p].queries == src.queries => p,
            Some(_) => return Err(E::Msg(format!("cow clone: the actor {want} is declared twice with other actions"))),
            None => {
                let mut c: Actor = src.clone();
                c.name = want;
                to.actors.push(c);
                to.actors.len() - 1
            }
        };
        ac.insert(a, idx(at)?);
    }
    for i in &list {
        let e: &Event = &from.events[usize::from(*i)];
        to.events.push(Event { name: e.name.clone(), kind: relink(&e.kind, &ev, &ac, class)? });
    }
    let subs: Vec<u16> = en.subs.iter().map(|s| moved(*s, &ev)).collect::<Res<Vec<u16>>>()?;
    to.entries.push(Entry { name: name.to_string(), subs, vars: Vec::new(), main: moved(en.main, &ev)?, pad: en.pad });
    Ok(ev)
}

fn call<'a>(f: &'a Flow, flow: &str, entry: &str) -> Res<&'a Event> {
    f.events
        .iter()
        .find(|e| matches!(&e.kind, Kind::Sub { flow: a, entry: b, .. } if a == flow && b == entry))
        .ok_or_else(|| E::Msg(format!("cow clone: {} never calls {flow}:{entry}, the game files differ", f.name)))
}

fn head(e: &Event, class: &str, name: &str, push: Option<&str>) -> Res<Event> {
    let Kind::Sub { params, flow, entry, .. } = &e.kind else {
        return Err(E::Format("cow clone: the template call is not a sub flow call"));
    };
    let mut p: Option<Cont> = renamed(params, class);
    if let Some(row) = push {
        let c: &mut Cont = p.as_mut().ok_or(E::Format("cow clone: the milk call has no parameters"))?;
        let v: &mut Val = c.items.iter_mut().find(|(k, _)| k == "EventName").map(|(_, v)| v).ok_or(E::Format("cow clone: the milk call names no event"))?;
        if *v != Val::Str(OLD_PUSH.to_string()) {
            return Err(E::Msg(format!("cow clone: the milk call of {TEMPLATE} starts {v:?} and not {OLD_PUSH}, the game files differ")));
        }
        *v = Val::Str(row.to_string());
    }
    Ok(Event { name: name.to_string(), kind: Kind::Sub { next: NONE, params: p, flow: flow.clone(), entry: entry.clone() } })
}

pub fn build(cow: &Bf, house: &Bf, class: &str) -> Res<Bf> {
    let donor: &Flow = cow.flows.first().ok_or(E::Format("cow clone: Animal_Cow holds no flow"))?;
    let home: &Flow = house.flows.first().ok_or(E::Format("cow clone: Animal_Cow_LinkHouse holds no flow"))?;
    let me: &Actor = donor
        .actors
        .iter()
        .find(|a| a.name == TEMPLATE && a.sub.is_empty())
        .ok_or_else(|| E::Msg(format!("cow clone: {PLAIN} declares no plain {TEMPLATE} actor, the game files differ")))?;
    let mut a: Actor = me.clone();
    a.name = class.to_string();
    let push: String = push_row(class);
    let mut f: Flow = Flow {
        name: class.to_string(),
        actors: vec![a],
        events: vec![head(call(home, PLAIN, TALK_CALL)?, class, "Event_Talk", None)?, head(call(home, PLAIN, GIVE_CALL)?, class, "Event_GiveMilk", Some(&push))?],
        entries: vec![
            Entry { name: TALK.to_string(), subs: vec![0], vars: Vec::new(), main: 0, pad: 0 },
            Entry { name: GIVE.to_string(), subs: vec![1], vars: Vec::new(), main: 1, pad: 0 },
        ],
    };
    graft(&mut f, donor, DONOR, PUSH, class)?;
    let out: Bf = Bf { ver: house.ver, bom: house.bom, shift: house.shift, pad: house.pad, name: class.to_string(), flows: vec![f], tls: Vec::new() };
    if Bf::parse(&out.write()?)? != out {
        return Err(E::Format("cow clone: the new flow does not read back"));
    }
    Ok(out)
}

pub fn mapped(cow: &Bf, donor: u16) -> Res<u16> {
    let f: &Flow = cow.flows.first().ok_or(E::Format("cow clone: Animal_Cow holds no flow"))?;
    let en: &Entry = f.entries.iter().find(|e| e.name == DONOR).ok_or(E::Format("cow clone: the donor entry is missing"))?;
    let at: usize = order(f, en.main).iter().position(|i| *i == donor).ok_or_else(|| E::Msg(format!("cow clone: event {donor} is not in {DONOR}")))?;
    idx(usize::from(HEAD) + at)
}

pub fn sources(rf: &mut Romfs) -> Res<(Bf, Bf)> {
    Ok((Bf::parse(&rf.read_zs(&path_of(&format!("{PLAIN}.bfevfl")))?)?, Bf::parse(&rf.read_zs(&path_of(&format!("{TEMPLATE}.bfevfl")))?)?))
}

pub fn dict(rf: &Romfs) -> Res<Option<u32>> {
    Ok(dict_id(&rf.read(&path_of(&format!("{TEMPLATE}.bfevfl")))?))
}

pub fn base(rf: &mut Romfs, file: &str) -> Res<Option<Vec<u8>>> {
    let Some(c) = of_file(file) else { return Ok(None) };
    let (cow, house): (Bf, Bf) = sources(rf)?;
    Ok(Some(build(&cow, &house, &c.class)?.write()?))
}

pub fn read(rf: &mut Romfs, file: &str) -> Res<(Vec<u8>, Option<u32>)> {
    if let Some(b) = base(rf, file)? {
        return Ok((b, dict(rf)?));
    }
    let z: Vec<u8> = rf.read(&path_of(file))?;
    Ok((rf.zs.decompress(&z)?, dict_id(&z)))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf as PB;


    fn root() -> Option<PB> {
        let p: PB = ootrr_game::test_romfs::path();
        if p.join("Event/EventFlow").is_dir() {
            Some(p)
        } else {
            eprintln!("skipped: no romfs at {}, set OOTRR_ROMFS", p.display());
            None
        }
    }

    fn lookup(b: &[u8], dic: usize, key: &str) -> bool {
        let n: usize = u32::from_le_bytes(b[dic + 4..dic + 8].try_into().unwrap()) as usize;
        let node = |i: usize| -> (i64, usize, usize, usize) {
            let o: usize = dic + 8 + 16 * i;
            let raw: u32 = u32::from_le_bytes(b[o..o + 4].try_into().unwrap());
            let bit: i64 = if raw == u32::MAX { -1 } else { i64::from(raw) };
            let l: usize = u16::from_le_bytes(b[o + 4..o + 6].try_into().unwrap()) as usize;
            let r: usize = u16::from_le_bytes(b[o + 6..o + 8].try_into().unwrap()) as usize;
            let s: usize = u64::from_le_bytes(b[o + 8..o + 16].try_into().unwrap()) as usize;
            (bit, l, r, s)
        };
        let k: &[u8] = key.as_bytes();
        let get = |bit: i64| -> usize {
            let j: usize = (bit >> 3) as usize;
            if j < k.len() { ((k[k.len() - 1 - j] >> (bit & 7)) & 1) as usize } else { 0 }
        };
        let text = |s: usize| -> String {
            let len: usize = u16::from_le_bytes(b[s..s + 2].try_into().unwrap()) as usize;
            String::from_utf8_lossy(&b[s + 2..s + 2 + len]).to_string()
        };
        let mut cur: (i64, usize, usize, usize) = node(0);
        let mut nxt: (i64, usize, usize, usize) = node(cur.1);
        while cur.0 < nxt.0 {
            cur = nxt;
            nxt = node(if get(cur.0) == 1 { cur.2 } else { cur.1 });
        }
        n > 0 && text(nxt.3) == key
    }

    #[test]
    fn a_clone_flow_names_only_its_class_and_keeps_the_house_milk_path() {
        let Some(r) = root() else { return };
        let mut rf: Romfs = Romfs::open(&r).unwrap();
        let (cow, house): (Bf, Bf) = sources(&mut rf).unwrap();
        let b: Bf = build(&cow, &house, "Animal_Cow_DMT").unwrap();
        let f: &Flow = &b.flows[0];
        let txt: String = format!("{b:?}");
        assert!(!txt.contains(TEMPLATE) && !txt.contains("KokiriForest"), "the clone still names the house cow");
        assert_eq!(f.entries.iter().map(|e| e.name.as_str()).collect::<Vec<&str>>(), vec![TALK, GIVE, PUSH]);
        assert_eq!(f.events.len(), 2 + 28);
        assert_eq!(f.entries[2].main, HEAD);
        assert_eq!(f.events[usize::from(HEAD)].name, "Event2");
        let milk: u16 = mapped(&cow, 45).unwrap();
        assert_eq!(f.entries[2].subs, vec![milk]);
        let Kind::Sub { flow, entry, params, .. } = &f.events[usize::from(milk)].kind else { panic!("milk") };
        assert_eq!((flow.as_str(), entry.as_str()), ("Dm_SY_GetInEvent", "GetInEventInBottle"));
        assert_eq!(params.as_ref().unwrap().get("ActorName"), Some(&Val::Str("Item_Bottle_Milk".to_string())));
        let Kind::Sub { params, entry, .. } = &f.events[1].kind else { panic!("give") };
        assert_eq!(entry, GIVE_CALL);
        let p: &Cont = params.as_ref().unwrap();
        assert_eq!(p.get("EventName"), Some(&Val::Str("Animal_Cow_DMT_PushToBottleMilk".to_string())));
        assert_eq!(p.get("Cow"), Some(&Val::Str("Animal_Cow_DMT".to_string())));
        assert_eq!(p.get("Actor"), Some(&Val::Actor("Animal_Cow_DMT".to_string(), String::new())));
        let Kind::Sub { params, entry, next, .. } = &f.events[0].kind else { panic!("talk") };
        assert_eq!((entry.as_str(), *next), (TALK_CALL, NONE));
        assert_eq!(params.as_ref().unwrap().get("ActorCawName"), Some(&Val::Str("Animal_Cow_DMT".to_string())));
        let names: Vec<&str> = f.actors.iter().map(|a| a.name.as_str()).collect();
        assert_eq!(names.iter().filter(|n| **n == "Animal_Cow_DMT").count(), 1);
        assert!(f.actors.iter().all(|a| a.sub.is_empty() && a.arg.is_empty()));
        let d: &Flow = &cow.flows[0];
        let en: &Entry = d.entries.iter().find(|e| e.name == DONOR).unwrap();
        for (n, i) in order(d, en.main).iter().enumerate() {
            let (x, y): (&Event, &Event) = (&d.events[usize::from(*i)], &f.events[usize::from(HEAD) + n]);
            assert_eq!(x.name, y.name);
            assert_eq!(format!("{:?}", x.kind.params()).replace(TEMPLATE, "Animal_Cow_DMT"), format!("{:?}", y.kind.params()));
            if let (Some(p), Some(q)) = (actor_of(&x.kind), actor_of(&y.kind)) {
                let (pa, qa): (&Actor, &Actor) = (&d.actors[usize::from(p)], &f.actors[usize::from(q)]);
                assert_eq!(pa.name.replace(TEMPLATE, "Animal_Cow_DMT"), qa.name);
                assert_eq!((&pa.actions, &pa.queries, &pa.params), (&qa.actions, &qa.queries, &qa.params));
            }
        }
    }

    #[test]
    fn our_writer_builds_a_name_dictionary_the_game_search_finds_for_every_class() {
        let Some(r) = root() else { return };
        let mut rf: Romfs = Romfs::open(&r).unwrap();
        let (cow, house): (Bf, Bf) = sources(&mut rf).unwrap();
        for c in crate::cow_clone::data::load().unwrap() {
            let raw: Vec<u8> = build(&cow, &house, &c.class).unwrap().write().unwrap();
            let dic: usize = u64::from_le_bytes(raw[0x30..0x38].try_into().unwrap()) as usize;
            assert!(lookup(&raw, dic, &c.class), "{}", c.class);
            assert!(!lookup(&raw, dic, TEMPLATE) && !lookup(&raw, dic, "Animal_Cow_DMX"), "{}", c.class);
            assert_eq!(base(&mut rf, &c.flow_file()).unwrap(), Some(raw));
        }
        let own: Vec<u8> = rf.read_zs(&path_of("Animal_Cow_LinkHouse.bfevfl")).unwrap();
        let dic: usize = u64::from_le_bytes(own[0x30..0x38].try_into().unwrap()) as usize;
        assert!(lookup(&own, dic, TEMPLATE));
        assert!(base(&mut rf, "Animal_Cow.bfevfl").unwrap().is_none());
        assert_eq!(dict(&rf).unwrap(), Some(1));
    }

    #[test]
    fn a_graft_refuses_an_entry_the_flow_lacks() {
        let Some(r) = root() else { return };
        let mut rf: Romfs = Romfs::open(&r).unwrap();
        let (cow, _): (Bf, Bf) = sources(&mut rf).unwrap();
        let mut f: Flow = Flow { name: "X".to_string(), actors: Vec::new(), events: Vec::new(), entries: Vec::new() };
        assert!(graft(&mut f, &cow.flows[0], "Missing", PUSH, "Animal_Cow_X").is_err());
        let m: BM<u16, u16> = graft(&mut f, &cow.flows[0], "PushToBottleMilk", PUSH, "Animal_Cow_X").unwrap();
        assert_eq!(m.len(), 28);
        assert_eq!(f.entries[0].main, 0);
        assert!(f.actors.iter().any(|a| a.name == PLAIN));
    }
}
