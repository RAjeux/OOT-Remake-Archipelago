use std::collections::{BTreeMap as BM, BTreeSet as BS, VecDeque};

use crate::bfevfl::flow::NONE;
use crate::bfevfl::{Bf, Case, Cont, Entry, Event, Flow, Kind, Val};
use crate::byml::{Byml, Node};
use crate::error::{Error, Res};
use crate::progressive::{ANALYZED_TABLE, BIG_FLOW, SETTING_TABLE, SMALL_FLOW};
use crate::qol::{edit_zs, Have};
use crate::romfs::Romfs;
use crate::staging::Out;

pub const SETTING: &str = "faster_chests";
pub const PREFIX: &str = "OOTRR_Big_";
pub const ROOT: &str = "Success_";
pub const SMALL_NAME: &str = "Dm_SY_TreasureboxSmall";
pub const BIG_NAME: &str = "Dm_SY_Treasurebox";
pub const BIG_EVFC: &str = "Work/Event/EventFlow/Dm_SY_Treasurebox.evfc";
pub const STARTER: &str = "TreasureBox_EventStarter";
pub const PLAY: &str = "EventPlayAS";
pub const SMALL_LID: &str = "FrontOpenSmall";
pub const BIG_LID: &str = "FrontOpen";
pub const KIND_QUERY: &str = "EventQueryTreasureBoxIsDungeonCommonItemInside";
pub const CALL: &str = "OOTRR_BigCall";
/// The event style fields taken from the small chest row. ExtraResources stays: the big
/// chest flow still declares its camera and Navi with the big chest animation resources.
pub const ROW_FIELDS: [&str; 3] = ["EventBaseSetting", "EventSettingComponentList", "EventSoundSetting"];
pub const WARP: &str = "IsPlayerWarpFirstFrame";
pub const SUBS: &str = "SubFlowList";

/// Query value of EventQueryTreasureBoxIsDungeonCommonItemInside and the native action the
/// big chest flow runs for it. Small keys (3) are left out: the small chest flow already
/// counts them, as every vanilla small key chest is a small chest.
pub const NATIVE: [(u32, &str); 3] = [(0, "EventGetDungeonMap"), (1, "EventGetDungeonCompass"), (2, "EventGetDungeonBossKey")];

pub const NOTE: &str = "Big chests open with the small chest animation: Link opens them like a small chest and the long big chest scene is skipped.";

pub fn files() -> [&'static str; 4] {
    [SMALL_FLOW, BIG_FLOW, SETTING_TABLE, ANALYZED_TABLE]
}

fn targets(k: &Kind) -> Vec<u16> {
    match k {
        Kind::Action { next, .. } | Kind::Join { next } | Kind::Sub { next, .. } => vec![*next],
        Kind::Switch { cases, .. } | Kind::SubSwitch { cases, .. } => cases.iter().map(|c| c.ev).collect(),
        Kind::Fork { join, forks } => forks.iter().copied().chain([*join]).collect(),
        Kind::Label { .. } => Vec::new(),
    }
}

fn remap(k: &Kind, m: &BM<u16, u16>) -> Kind {
    let f = |x: u16| -> u16 { if x == NONE { NONE } else { m.get(&x).copied().unwrap_or(x) } };
    let cs = |c: &[Case]| -> Vec<Case> { c.iter().map(|c| Case { val: c.val, ev: f(c.ev) }).collect() };
    match k {
        Kind::Action { next, actor, act, params } => Kind::Action { next: f(*next), actor: *actor, act: *act, params: params.clone() },
        Kind::Switch { actor, query, cases, params } => Kind::Switch { actor: *actor, query: *query, cases: cs(cases), params: params.clone() },
        Kind::Fork { join, forks } => Kind::Fork { join: f(*join), forks: forks.iter().map(|x| f(*x)).collect() },
        Kind::Join { next } => Kind::Join { next: f(*next) },
        Kind::Sub { next, params, flow, entry } => Kind::Sub { next: f(*next), params: params.clone(), flow: flow.clone(), entry: entry.clone() },
        Kind::SubSwitch { cases, params, flow, entry } => Kind::SubSwitch { cases: cs(cases), params: params.clone(), flow: flow.clone(), entry: entry.clone() },
        Kind::Label { hash } => Kind::Label { hash: *hash },
    }
}

fn idx(n: usize) -> Res<u16> {
    u16::try_from(n).ok().filter(|x| *x != NONE).ok_or(Error::Format("chest animation: the flow has too many events"))
}

fn reach(f: &Flow, roots: impl IntoIterator<Item = u16>) -> BS<u16> {
    let mut seen: BS<u16> = BS::new();
    let mut todo: Vec<u16> = roots.into_iter().collect();
    while let Some(i) = todo.pop() {
        if i == NONE || (i as usize) >= f.events.len() || !seen.insert(i) {
            continue;
        }
        todo.extend(targets(&f.events[i as usize].kind));
    }
    seen
}

fn local_entry(k: &Kind) -> Option<&str> {
    match k {
        Kind::Sub { flow, entry, .. } | Kind::SubSwitch { flow, entry, .. } if flow.is_empty() => Some(entry.as_str()),
        _ => None,
    }
}

fn entry_events(f: &Flow, e: &Entry) -> BS<u16> {
    reach(f, std::iter::once(e.main).chain(e.subs.iter().copied()))
}

/// Copies the part of the small chest flow that runs from `Success_` (every local entry it
/// calls, and every event they reach) under the `OOTRR_Big_` prefix, with the small chest lid
/// animation swapped for the big chest one. Returns how many lid animations were swapped.
pub fn clone_chain(f: &mut Flow) -> Res<usize> {
    let root: String = format!("{PREFIX}{ROOT}");
    if f.entries.iter().any(|e| e.name == root) {
        return Ok(0);
    }
    let mut names: BS<String> = BS::new();
    let mut queue: VecDeque<String> = VecDeque::from([ROOT.to_string()]);
    while let Some(n) = queue.pop_front() {
        if names.contains(&n) {
            continue;
        }
        let e: &Entry = f.entries.iter().find(|e| e.name == n).ok_or_else(|| Error::Msg(format!("the small chest flow has no {n} entry")))?;
        names.insert(n);
        for i in entry_events(f, e) {
            if let Some(x) = local_entry(&f.events[i as usize].kind) {
                queue.push_back(x.to_string());
            }
        }
    }
    let entries: Vec<Entry> = f.entries.iter().filter(|e| names.contains(&e.name)).cloned().collect();
    let all: BS<u16> = entries.iter().flat_map(|e| entry_events(f, e)).collect();
    let base: usize = f.events.len();
    let mut m: BM<u16, u16> = BM::new();
    for (k, i) in all.iter().enumerate() {
        m.insert(*i, idx(base + k)?);
    }
    let starter: Option<usize> = f.actors.iter().position(|a| a.name == STARTER && a.sub.is_empty());
    let play: Option<usize> = starter.and_then(|s| f.actors[s].actions.iter().position(|a| a == PLAY));
    let mut swapped: usize = 0;
    let mut add: Vec<Event> = Vec::new();
    for i in &all {
        let src: &Event = &f.events[*i as usize];
        let mut k: Kind = remap(&src.kind, &m);
        match &mut k {
            Kind::Sub { flow, entry, .. } | Kind::SubSwitch { flow, entry, .. } if flow.is_empty() && names.contains(entry.as_str()) => {
                *entry = format!("{PREFIX}{entry}");
            }
            Kind::Action { actor, act, params: Some(c), .. } if Some(*actor as usize) == starter && Some(*act as usize) == play => {
                for (n, v) in c.items.iter_mut() {
                    if n == "ASName" && *v == Val::Str(SMALL_LID.to_string()) {
                        *v = Val::Str(BIG_LID.to_string());
                        swapped += 1;
                    }
                }
            }
            _ => {}
        }
        add.push(Event { name: format!("OOTRRBig{}", add.len()), kind: k });
    }
    if swapped == 0 {
        return Err(Error::Msg(format!("the small chest flow never plays {SMALL_LID} from {ROOT}, the game files differ")));
    }
    f.events.extend(add);
    let get = |x: u16| -> u16 { m.get(&x).copied().unwrap_or(NONE) };
    for e in entries {
        f.entries.push(Entry {
            name: format!("{PREFIX}{}", e.name),
            subs: e.subs.iter().map(|x| get(*x)).collect(),
            vars: e.vars.clone(),
            main: get(e.main),
            pad: e.pad,
        });
    }
    Ok(swapped)
}

fn find_act(f: &Flow, actor: &str, act: &str) -> Option<(u16, u16)> {
    let a: usize = f.actors.iter().position(|x| x.name == actor && x.sub.is_empty())?;
    let j: usize = f.actors[a].actions.iter().position(|x| x == act)?;
    Some((a as u16, j as u16))
}

fn has_args(c: &Option<Cont>, keys: &[&str]) -> bool {
    match c {
        Some(c) => c.items.len() == keys.len() && keys.iter().all(|k| matches!(c.get(k), Some(Val::Arg(a)) if a == k)),
        None => false,
    }
}

/// Points the big chest flow's `Success_` entry at the copied chain in the small chest flow,
/// then runs the native map, compass and boss key credit the big chest flow still reaches.
/// Every big chest event (the default one, the progressive and dungeon credit wrappers) goes
/// through `Success_`, so they all get the small chest animation.
pub fn reroute(f: &mut Flow) -> Res<usize> {
    if f.events.iter().any(|e| e.name == CALL) {
        return Ok(0);
    }
    let at: usize = f.entries.iter().position(|e| e.name == ROOT).ok_or(Error::Format("chest animation: the big chest flow has no Success_ entry"))?;
    let live: BS<u16> = reach(f, f.entries.iter().map(|e| e.main));
    let params: Option<Cont> = f
        .events
        .iter()
        .find_map(|e| match &e.kind {
            Kind::Sub { params, .. } if has_args(params, &["ContentName", "IsMiniGame"]) => Some(params.clone()),
            _ => None,
        })
        .ok_or(Error::Format("chest animation: the big chest flow passes no ContentName and IsMiniGame"))?;
    let (sw_actor, sw_query, sw_params): (u16, u16, Option<Cont>) = f
        .events
        .iter()
        .find_map(|e| match &e.kind {
            Kind::Switch { actor, query, params, .. }
                if f.actors.get(*actor as usize).and_then(|a| a.queries.get(*query as usize)).map(|q| q.as_str()) == Some(KIND_QUERY) =>
            {
                Some((*actor, *query, params.clone()))
            }
            _ => None,
        })
        .ok_or(Error::Format("chest animation: the big chest flow never asks which dungeon item is inside"))?;
    let mut cases: Vec<Case> = Vec::new();
    let mut add: Vec<Event> = Vec::new();
    let base: usize = f.events.len();
    for (val, act) in NATIVE {
        let Some((a, j)) = find_act(f, "GameSystemActor", act) else {
            continue;
        };
        let native: Option<&Event> = f.events.iter().enumerate().find_map(|(i, e)| match &e.kind {
            Kind::Action { actor, act, .. } if *actor == a && *act == j && live.contains(&(i as u16)) => Some(e),
            _ => None,
        });
        let Some(Event { kind: Kind::Action { params: p, .. }, .. }) = native else {
            continue;
        };
        let p: Option<Cont> = p.clone();
        let i: u16 = idx(base + 2 + add.len())?;
        add.push(Event { name: format!("OOTRRBigNative{val}"), kind: Kind::Action { next: NONE, actor: a, act: j, params: p } });
        cases.push(Case { val, ev: i });
    }
    let call: u16 = idx(base)?;
    let sw: u16 = idx(base + 1)?;
    let next: u16 = if cases.is_empty() { NONE } else { sw };
    let n: usize = cases.len();
    f.events.push(Event { name: CALL.to_string(), kind: Kind::Sub { next, params: params.clone(), flow: SMALL_NAME.to_string(), entry: format!("{PREFIX}{ROOT}") } });
    if n > 0 {
        f.events.push(Event { name: "OOTRR_BigNative".to_string(), kind: Kind::Switch { actor: sw_actor, query: sw_query, cases, params: sw_params } });
    }
    f.events.extend(add);
    let e: &mut Entry = &mut f.entries[at];
    e.main = call;
    e.subs = vec![call];
    Ok(n)
}

fn row_id(n: &Node) -> &str {
    n.get("__RowId").and_then(|v| v.as_str()).unwrap_or("")
}

fn rows(y: &mut Byml) -> Res<&mut Vec<Node>> {
    y.root.as_arr_mut().ok_or(Error::Format("chest animation: the event table root is not a list"))
}

/// Gives every event that runs the big chest flow the small chest flow's event settings
/// (the in-game event style instead of the hide-everything cutscene). Returns their names.
pub fn settings(y: &mut Byml) -> Res<BS<String>> {
    let list: &mut Vec<Node> = rows(y)?;
    let small: Node = list.iter().find(|r| row_id(r) == SMALL_NAME).cloned().ok_or(Error::Format("chest animation: the event settings have no small chest row"))?;
    let mut out: BS<String> = BS::new();
    for r in list.iter_mut() {
        if r.get("FlowchartFileName").and_then(|v| v.as_str()) != Some(BIG_EVFC) {
            continue;
        }
        for k in ROW_FIELDS {
            if let Some(v) = small.get(k) {
                r.set(k, v.clone());
            }
        }
        out.insert(row_id(r).to_string());
    }
    if !out.contains(BIG_NAME) {
        return Err(Error::Format("chest animation: no event runs the big chest flow"));
    }
    Ok(out)
}

/// Lets the big chest events load the small chest flow they now call into.
pub fn analyzed(y: &mut Byml, big: &BS<String>) -> Res<usize> {
    let list: &mut Vec<Node> = rows(y)?;
    let small: Vec<String> = list
        .iter()
        .find(|r| row_id(r) == SMALL_NAME)
        .and_then(|r| r.get(SUBS))
        .and_then(|s| s.as_arr())
        .map(|s| s.iter().filter_map(|x| x.as_str().map(|x| x.to_string())).collect())
        .ok_or(Error::Format("chest animation: the analyzed events have no small chest row"))?;
    let mut n: usize = 0;
    for r in list.iter_mut() {
        let id: String = row_id(r).to_string();
        let mine: bool = big.contains(&id);
        let calls: bool = r.get(SUBS).and_then(|s| s.as_arr()).is_some_and(|s| s.iter().any(|x| x.as_str() == Some(BIG_NAME)));
        if !mine && !calls {
            continue;
        }
        let mut want: BS<String> = r.get(SUBS).and_then(|s| s.as_arr()).map(|s| s.iter().filter_map(|x| x.as_str().map(|x| x.to_string())).collect()).unwrap_or_default();
        want.extend(small.iter().cloned());
        want.insert(SMALL_NAME.to_string());
        r.set(SUBS, Node::Arr(want.into_iter().map(Node::Str).collect()));
        if mine {
            r.remove(WARP);
        }
        n += 1;
    }
    Ok(n)
}

fn flow_of(b: &mut Bf) -> Res<&mut Flow> {
    b.flows.first_mut().ok_or(Error::Format("chest animation: the flow file has no flow"))
}

fn check(f: &Flow, what: &str) -> Res<()> {
    match crate::dungeon_credit::sound(f).first() {
        Some(m) => Err(Error::Msg(format!("chest animation: the {what} chest flow is broken, {m}"))),
        None => Ok(()),
    }
}

pub fn stage(rf: &mut Romfs, have: Have) -> Res<Vec<Out>> {
    let mut outs: Vec<Out> = Vec::new();
    outs.push(edit_zs(rf, have, SMALL_FLOW, |raw: &[u8]| {
        let mut b: Bf = Bf::parse(raw)?;
        let f: &mut Flow = flow_of(&mut b)?;
        clone_chain(f)?;
        check(f, "small")?;
        b.write()
    })?);
    outs.push(edit_zs(rf, have, BIG_FLOW, |raw: &[u8]| {
        let mut b: Bf = Bf::parse(raw)?;
        let f: &mut Flow = flow_of(&mut b)?;
        reroute(f)?;
        check(f, "big")?;
        b.write()
    })?);
    let mut big: BS<String> = BS::new();
    outs.push(edit_zs(rf, have, SETTING_TABLE, |raw: &[u8]| {
        let mut y: Byml = Byml::parse(raw)?;
        big = settings(&mut y)?;
        y.write()
    })?);
    outs.push(edit_zs(rf, have, ANALYZED_TABLE, |raw: &[u8]| {
        let mut y: Byml = Byml::parse(raw)?;
        analyzed(&mut y, &big)?;
        y.write()
    })?);
    Ok(outs)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::bfevfl::Actor;

    fn actor(name: &str, acts: &[&str], qs: &[&str]) -> Actor {
        Actor {
            name: name.to_string(),
            sub: String::new(),
            arg: String::new(),
            actions: acts.iter().map(|s| s.to_string()).collect(),
            queries: qs.iter().map(|s| s.to_string()).collect(),
            params: None,
            ep: 0xFFFF,
            cut: 1,
        }
    }

    fn ev(n: &str, kind: Kind) -> Event {
        Event { name: n.to_string(), kind }
    }

    fn entry(n: &str, main: u16, subs: Vec<u16>) -> Entry {
        Entry { name: n.to_string(), subs, vars: Vec::new(), main, pad: 0 }
    }

    fn args() -> Option<Cont> {
        Some(Cont { items: vec![("ContentName".to_string(), Val::Arg("ContentName".to_string())), ("IsMiniGame".to_string(), Val::Arg("IsMiniGame".to_string()))] })
    }

    fn lid(name: &str) -> Option<Cont> {
        Some(Cont { items: vec![("ASName".to_string(), Val::Str(name.to_string()))] })
    }

    fn small() -> Flow {
        Flow {
            name: SMALL_NAME.to_string(),
            actors: vec![actor("GameSystemActor", &["EventWait"], &[]), actor(STARTER, &["EventTriggerTreasureBoxOpened", PLAY], &[])],
            events: vec![
                ev("E0", Kind::Sub { next: 1, params: args(), flow: String::new(), entry: "Open".to_string() }),
                ev("E1", Kind::Action { next: NONE, actor: 0, act: 0, params: None }),
                ev("E2", Kind::Sub { next: NONE, params: None, flow: String::new(), entry: "Anim".to_string() }),
                ev("E3", Kind::Action { next: NONE, actor: 1, act: 1, params: lid(SMALL_LID) }),
                ev("E4", Kind::Sub { next: NONE, params: None, flow: "Dm_SY_Get".to_string(), entry: "X".to_string() }),
                ev("E5", Kind::Action { next: NONE, actor: 0, act: 0, params: None }),
            ],
            entries: vec![entry("Success", 5, vec![]), entry(ROOT, 0, vec![0]), entry("Open", 2, vec![2]), entry("Anim", 3, vec![]), entry("Other", 4, vec![4])],
        }
    }

    #[test]
    fn the_copied_chain_opens_the_big_lid_and_calls_its_own_copies() {
        let mut f: Flow = small();
        assert_eq!(clone_chain(&mut f).unwrap(), 1);
        assert_eq!(clone_chain(&mut f).unwrap(), 0);
        assert_eq!(f.events.len(), 6 + 4);
        let names: Vec<&str> = f.entries.iter().map(|e| e.name.as_str()).collect();
        assert!(names.contains(&"OOTRR_Big_Success_") && names.contains(&"OOTRR_Big_Open") && names.contains(&"OOTRR_Big_Anim"));
        assert!(!names.contains(&"OOTRR_Big_Other") && !names.contains(&"OOTRR_Big_Success"));
        let root: &Entry = f.entries.iter().find(|e| e.name == "OOTRR_Big_Success_").unwrap();
        let Kind::Sub { next, entry, .. } = &f.events[root.main as usize].kind else { panic!() };
        assert_eq!(entry, "OOTRR_Big_Open");
        assert!(*next as usize >= 6);
        let anim: &Entry = f.entries.iter().find(|e| e.name == "OOTRR_Big_Anim").unwrap();
        assert_eq!(f.events[anim.main as usize].kind.params(), lid(BIG_LID).as_ref());
        assert_eq!(f.events[3].kind.params(), lid(SMALL_LID).as_ref());
        assert!(crate::dungeon_credit::sound(&f).is_empty());
    }

    #[test]
    fn a_flow_without_the_small_lid_is_refused() {
        let mut f: Flow = small();
        f.events[3].kind = Kind::Action { next: NONE, actor: 1, act: 1, params: lid("Other") };
        assert!(clone_chain(&mut f).is_err());
    }

    fn big() -> Flow {
        let kind = Some(Cont { items: vec![("ActorName".to_string(), Val::Arg("ContentName".to_string()))] });
        Flow {
            name: BIG_NAME.to_string(),
            actors: vec![
                actor("GameSystemActor", &["EventWait", "EventGetDungeonMap", "EventGetDungeonCompass", "EventGetDungeonBossKey", "EventGetDungeonSmallKey"], &[]),
                actor(STARTER, &[], &[KIND_QUERY]),
            ],
            events: vec![
                ev("E0", Kind::Sub { next: 1, params: args(), flow: String::new(), entry: "AddContent".to_string() }),
                ev("E1", Kind::Action { next: NONE, actor: 0, act: 0, params: None }),
                ev("E2", Kind::Switch { actor: 1, query: 0, cases: vec![Case { val: 0, ev: 3 }, Case { val: 1, ev: 1 }, Case { val: 2, ev: 4 }, Case { val: 3, ev: 5 }], params: kind }),
                ev("E3", Kind::Action { next: 1, actor: 0, act: 1, params: None }),
                ev("E4", Kind::Action { next: 1, actor: 0, act: 3, params: None }),
                ev("E5", Kind::Action { next: 1, actor: 0, act: 4, params: None }),
                ev("E6", Kind::Action { next: NONE, actor: 0, act: 2, params: None }),
            ],
            entries: vec![entry(ROOT, 0, vec![0]), entry("AddContent", 2, vec![])],
        }
    }

    #[test]
    fn the_big_flow_calls_the_copy_then_credits_the_reachable_dungeon_items() {
        let mut f: Flow = big();
        assert_eq!(reroute(&mut f).unwrap(), 2);
        assert_eq!(reroute(&mut f).unwrap(), 0);
        let e: &Entry = f.entries.iter().find(|e| e.name == ROOT).unwrap();
        let Kind::Sub { next, flow, entry, params } = &f.events[e.main as usize].kind else { panic!() };
        assert_eq!((flow.as_str(), entry.as_str()), (SMALL_NAME, "OOTRR_Big_Success_"));
        assert_eq!(params, &args());
        let Kind::Switch { cases, .. } = &f.events[*next as usize].kind else { panic!() };
        let vals: Vec<u32> = cases.iter().map(|c| c.val).collect();
        assert_eq!(vals, vec![0, 2]);
        for c in cases {
            let Kind::Action { next, act, .. } = &f.events[c.ev as usize].kind else { panic!() };
            assert_eq!(*next, NONE);
            assert!(*act == 1 || *act == 3);
        }
        assert!(crate::dungeon_credit::sound(&f).is_empty());
    }

    fn row(id: &str, file: &str, list: &str) -> Node {
        Node::Map(vec![
            ("EventSettingComponentList".to_string(), Node::Str(list.to_string())),
            ("FlowchartFileName".to_string(), Node::Str(file.to_string())),
            ("__RowId".to_string(), Node::Str(id.to_string())),
        ])
    }

    fn arow(id: &str, subs: &[&str], warp: bool) -> Node {
        let mut m: Vec<(String, Node)> = Vec::new();
        if warp {
            m.push((WARP.to_string(), Node::Bool(true)));
        }
        m.push((SUBS.to_string(), Node::Arr(subs.iter().map(|s| Node::Str(s.to_string())).collect())));
        m.push(("__RowId".to_string(), Node::Str(id.to_string())));
        Node::Map(m)
    }

    #[test]
    fn big_chest_events_take_the_small_settings_and_load_the_small_flow() {
        let small_file: &str = "Work/Event/EventFlow/Dm_SY_TreasureboxSmall.evfc";
        let mut y: Byml = Byml {
            root: Node::Arr(vec![
                row(BIG_NAME, BIG_EVFC, "Hide"),
                row(SMALL_NAME, small_file, "InGame"),
                row("OOTRR_Prog_Bow_Big", BIG_EVFC, "Hide"),
                row("Story", "Work/Event/EventFlow/Story.evfc", "Hide"),
            ]),
            version: 7,
            big: false,
        };
        let big: BS<String> = settings(&mut y).unwrap();
        assert_eq!(big.len(), 2);
        let list: &[Node] = y.root.as_arr().unwrap();
        assert_eq!(list[2].get("EventSettingComponentList").and_then(|v| v.as_str()), Some("InGame"));
        assert_eq!(list[3].get("EventSettingComponentList").and_then(|v| v.as_str()), Some("Hide"));
        let mut a: Byml = Byml {
            root: Node::Arr(vec![
                arow(BIG_NAME, &["ActionGuide", "Dm_SY_Get"], true),
                arow(SMALL_NAME, &["Dm_SY_Get", "NaviHint"], false),
                arow("MiniGame", &["Dm_SY_Treasurebox"], false),
                arow("Story", &["Dm_SY_Get"], true),
            ]),
            version: 7,
            big: false,
        };
        assert_eq!(analyzed(&mut a, &big).unwrap(), 2);
        let list: &[Node] = a.root.as_arr().unwrap();
        let subs = |i: usize| -> Vec<&str> { list[i].get(SUBS).unwrap().as_arr().unwrap().iter().filter_map(|x| x.as_str()).collect() };
        assert_eq!(subs(0), vec!["ActionGuide", "Dm_SY_Get", SMALL_NAME, "NaviHint"]);
        assert!(list[0].get(WARP).is_none());
        assert_eq!(subs(2), vec!["Dm_SY_Get", "Dm_SY_Treasurebox", SMALL_NAME, "NaviHint"]);
        assert!(list[3].get(WARP).is_some());
        assert_eq!(subs(3), vec!["Dm_SY_Get"]);
    }

    #[test]
    fn the_real_game_files_take_the_change() {
        let p: std::path::PathBuf = ootrr_game::test_romfs::path();
        if !p.join("Pack").join("ZsDic.pack.zs").is_file() {
            eprintln!("skipped, no RomFS dump at {}", p.display());
            return;
        }
        let mut rf: Romfs = Romfs::open(&p).unwrap();
        let outs: Vec<Out> = stage(&mut rf, &|_: &str| None).unwrap();
        assert_eq!(outs.len(), 4);
        let small: Bf = Bf::parse(&rf.zs.decompress(&outs[0].z).unwrap()).unwrap();
        assert!(small.flows[0].entries.iter().any(|e| e.name == "OOTRR_Big_Success_"));
        let big: Bf = Bf::parse(&rf.zs.decompress(&outs[1].z).unwrap()).unwrap();
        assert!(big.flows[0].events.iter().any(|e| e.name == CALL));
    }
}
