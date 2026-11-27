use crate::bfevfl::{Bf, Case, Cont, Event, Flow, Kind, Val};
use crate::error::{Error, Res};
use crate::romfs::Romfs;
use crate::staging::Out;

pub const FLOW: &str = "GetPouchContent";
pub const ENTRY: &str = "GetPouchContent";
pub const PREFIX: &str = "OOTRRFieldSun";
pub const FLAG: &str = crate::start_state::FIELD_FIRST_VISIT;
pub const OWL_PLAYED: [&str; 2] = ["HavePlayedEvent.Dm_HrlField_0010", "HavePlayedEvent.HyruleField_Goto_HyruleCastle_Kaepora"];
pub const OWL_GONE: &str = "Goto_HyruleCastle_IsAfter_Step01_Exp";
const ACTOR: &str = "GameDataActor";
const ASK: &str = "EventQueryIsGameDataBool";
const ASK_EXP: &str = "EventQueryIsGameDataBoolExp";
const SET: &str = "EventTriggerSetGameDataBool";
const NONE: u16 = 0xFFFF;

fn idx(n: usize) -> Res<u16> {
    if n >= NONE as usize {
        return Err(Error::Format("field palette: too many events in the flow"));
    }
    Ok(n as u16)
}

fn name(n: &str) -> Cont {
    Cont { items: vec![("Index".to_string(), Val::Int(-1)), ("GameDataName".to_string(), Val::Str(n.to_string()))] }
}

fn ask(f: &mut Flow, n: &str, yes: u16, no: u16) -> Res<Kind> {
    let (a, q): (u16, u16) = crate::start_state::query_slot(f, ACTOR, ASK)?;
    Ok(Kind::Switch { actor: a, query: q, cases: vec![Case { val: 0, ev: yes }, Case { val: 1, ev: no }], params: Some(name(n)) })
}

fn ask_exp(f: &mut Flow, n: &str, yes: u16, no: u16) -> Res<Kind> {
    let (a, q): (u16, u16) = crate::start_state::query_slot(f, ACTOR, ASK_EXP)?;
    let c: Cont = Cont { items: vec![("GameDataName".to_string(), Val::Str(n.to_string()))] };
    Ok(Kind::Switch { actor: a, query: q, cases: vec![Case { val: 0, ev: yes }, Case { val: 1, ev: no }], params: Some(c) })
}

pub fn patch(b: &mut Bf) -> Res<()> {
    let f: &mut Flow = b.flows.iter_mut().find(|x| x.name == FLOW).ok_or(Error::Format("field palette: no GetPouchContent flow"))?;
    if f.events.iter().any(|e| e.name.starts_with(PREFIX)) {
        return Err(Error::Format("field palette: GetPouchContent already carries the repair"));
    }
    let e: usize = f.entries.iter().position(|x| x.name == ENTRY).ok_or(Error::Format("field palette: GetPouchContent has no GetPouchContent entry"))?;
    let old: u16 = f.entries[e].main;
    if old == NONE || usize::from(old) >= f.events.len() {
        return Err(Error::Format("field palette: the GetPouchContent entry starts nowhere"));
    }
    let base: usize = f.events.len();
    let at: [u16; 5] = [idx(base)?, idx(base + 1)?, idx(base + 2)?, idx(base + 3)?, idx(base + 4)?];
    let (da, dx): (u16, u16) = crate::start_state::slot(f, ACTOR, SET)?;
    let mut clear: Cont = name(FLAG);
    clear.items.push(("Value".to_string(), Val::Bool(0)));
    let kinds: Vec<Kind> = vec![
        ask(f, FLAG, at[1], old)?,
        ask(f, OWL_PLAYED[0], at[4], at[2])?,
        ask(f, OWL_PLAYED[1], at[4], at[3])?,
        ask_exp(f, OWL_GONE, at[4], old)?,
        Kind::Action { next: old, actor: da, act: dx, params: Some(clear) },
    ];
    for (i, k) in kinds.into_iter().enumerate() {
        f.events.push(Event { name: format!("{PREFIX}{}", base + i), kind: k });
    }
    f.entries[e].main = at[0];
    Ok(())
}

pub fn stage(rf: &mut Romfs, late: &mut Vec<Out>, work: &std::path::Path) -> Res<()> {
    crate::story_skip::stage_late(rf, late, work, FLOW, patch)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::bfevfl::{Actor, Entry};

    fn actor(n: &str, acts: &[&str], qs: &[&str]) -> Actor {
        Actor {
            name: n.to_string(),
            sub: String::new(),
            arg: String::new(),
            actions: acts.iter().map(|s| s.to_string()).collect(),
            queries: qs.iter().map(|s| s.to_string()).collect(),
            params: Some(Cont { items: vec![("EventMemberCreateMethod".to_string(), Val::Int(0))] }),
            ep: 0xFFFF,
            cut: 1,
        }
    }

    fn sample() -> Bf {
        let events: Vec<Event> = vec![
            Event { name: "Event0".to_string(), kind: Kind::Action { next: 1, actor: 0, act: 0, params: None } },
            Event { name: "Event11".to_string(), kind: Kind::Action { next: NONE, actor: 0, act: 0, params: None } },
        ];
        let f: Flow = Flow {
            name: FLOW.to_string(),
            actors: vec![actor("PouchSystemActor", &["EventTriggerSetForGetWindow"], &[]), actor(ACTOR, &["EventTriggerCopyGameDataInt"], &["EventQueryIsGameDataBoolExp"])],
            events,
            entries: vec![
                Entry { name: "GetPouchContentByActorName".to_string(), subs: Vec::new(), vars: Vec::new(), main: 0, pad: 0 },
                Entry { name: ENTRY.to_string(), subs: vec![0], vars: Vec::new(), main: 1, pad: 0 },
            ],
        };
        Bf { ver: [0, 4, 0, 0], bom: 0xFEFF, shift: 3, pad: 0, name: FLOW.to_string(), flows: vec![f], tls: Vec::new() }
    }

    fn param<'a>(k: &'a Kind, key: &str) -> Option<&'a Val> {
        k.params()?.get(key)
    }

    fn walks() -> Vec<[bool; 4]> {
        (0..16u8).map(|m: u8| [m & 1 != 0, m & 2 != 0, m & 4 != 0, m & 8 != 0]).collect()
    }

    fn state(w: &[bool; 4]) -> [(&'static str, bool); 4] {
        [(FLAG, w[0]), (OWL_PLAYED[0], w[1]), (OWL_PLAYED[1], w[2]), (OWL_GONE, w[3])]
    }

    fn ends(f: &Flow, from: u16, flags: &[(&str, bool)]) -> (u16, Vec<String>) {
        let mut i: u16 = from;
        let mut wrote: Vec<String> = Vec::new();
        for _ in 0..16 {
            if !f.events[usize::from(i)].name.starts_with(PREFIX) {
                return (i, wrote);
            }
            match &f.events[usize::from(i)].kind {
                Kind::Switch { cases, params, .. } => {
                    let n: &str = match params.as_ref().and_then(|c| c.get("GameDataName")) {
                        Some(Val::Str(s)) => s.as_str(),
                        _ => panic!("a repair switch without a flag"),
                    };
                    let on: bool = flags.iter().any(|(k, v)| *k == n && *v);
                    i = cases.iter().find(|c| c.val == if on { 0 } else { 1 }).map(|c| c.ev).unwrap();
                }
                Kind::Action { next, params, .. } => {
                    if let Some(Val::Str(s)) = params.as_ref().and_then(|c| c.get("GameDataName")) {
                        wrote.push(format!("{s}={:?}", params.as_ref().and_then(|c| c.get("Value"))));
                    }
                    i = *next;
                }
                _ => panic!("unexpected event in the repair"),
            }
        }
        panic!("the repair loops");
    }

    #[test]
    fn the_repair_clears_the_flag_only_once_the_owl_is_played_or_gone_and_always_lands_on_the_old_start() {
        let mut b: Bf = sample();
        patch(&mut b).unwrap();
        assert!(patch(&mut b).is_err());
        let f: &Flow = &b.flows[0];
        let start: u16 = f.entries.iter().find(|e| e.name == ENTRY).unwrap().main;
        assert_eq!(f.entries[0].main, 0);
        assert_eq!(f.events.len(), 7);
        let clear: Vec<String> = vec![format!("{FLAG}={:?}", Some(&Val::Bool(0)))];
        let ws: Vec<[bool; 4]> = walks();
        assert_eq!(ws.len(), 16);
        for w in &ws {
            let (end, wrote): (u16, Vec<String>) = ends(f, start, &state(w));
            assert_eq!(end, 1, "{w:?}");
            assert_eq!(wrote, if w[0] && (w[1] || w[2] || w[3]) { clear.clone() } else { Vec::new() }, "{w:?}");
        }
        let g: &Actor = &f.actors[1];
        assert!(g.queries.contains(&ASK.to_string()) && g.queries.contains(&ASK_EXP.to_string()) && g.actions.contains(&SET.to_string()));
        assert_eq!(g.queries.iter().filter(|q| q.as_str() == ASK_EXP).count(), 1);
        assert_eq!(f.actors.len(), 2);
        let Kind::Switch { query, params, .. } = &f.events[5].kind else { panic!("the step question is not a switch") };
        assert_eq!(g.queries[usize::from(*query)], ASK_EXP);
        assert_eq!(params.as_ref().map(|c| c.items.len()), Some(1));
        assert_eq!(param(&f.events[6].kind, "Value"), Some(&Val::Bool(0)));
        assert_eq!(Bf::parse(&b.write().unwrap()).unwrap(), b);
    }

    #[test]
    fn a_flow_without_the_entry_is_refused() {
        let mut b: Bf = sample();
        b.flows[0].entries.retain(|e| e.name != ENTRY);
        assert!(patch(&mut b).is_err());
        let mut c: Bf = sample();
        c.flows[0].name = "Other".to_string();
        assert!(patch(&mut c).is_err());
    }

    fn dump() -> Option<std::path::PathBuf> {
        let p: std::path::PathBuf = ootrr_game::test_romfs::path();
        if p.join("Pack").join("ZsDic.pack.zs").is_file() { Some(p) } else { None }
    }

    #[test]
    fn the_real_item_get_flow_takes_the_repair_in_front_of_its_window() {
        let Some(root) = dump() else {
            return;
        };
        let mut rf: Romfs = Romfs::open(&root).unwrap();
        let raw: Vec<u8> = rf.read_zs(&format!("Event/EventFlow/{FLOW}.bfevfl.zs")).unwrap();
        let mut b: Bf = Bf::parse(&raw).unwrap();
        let before: Flow = b.flows.iter().find(|f| f.name == FLOW).unwrap().clone();
        let old: u16 = before.entries.iter().find(|e| e.name == ENTRY).unwrap().main;
        patch(&mut b).unwrap();
        assert!(patch(&mut b).is_err());
        let f: &Flow = b.flows.iter().find(|f| f.name == FLOW).unwrap();
        assert_eq!(f.events[..before.events.len()], before.events[..]);
        assert_eq!(f.actors.len(), before.actors.len());
        for (a, e) in before.entries.iter().zip(&f.entries) {
            assert_eq!(a.subs, e.subs);
            if a.name != ENTRY {
                assert_eq!(a.main, e.main);
            }
        }
        let start: u16 = f.entries.iter().find(|e| e.name == ENTRY).unwrap().main;
        for w in &walks() {
            let (end, wrote): (u16, Vec<String>) = ends(f, start, &state(w));
            assert_eq!(end, old, "{w:?}");
            assert_eq!(wrote.len(), usize::from(w[0] && (w[1] || w[2] || w[3])), "{w:?}");
        }
        let flags: &str = include_str!("../../../data/flags.json");
        assert!(flags.contains(&format!("\"name\":\"{OWL_GONE}\",\"how\":\"exp\",\"type\":\"BoolExp\"")));
        assert_eq!(Bf::parse(&b.write().unwrap()).unwrap(), b);
    }

    #[test]
    fn the_generated_overlay_repair_preserves_the_native_item_window() {
        let Some(root) = dump() else {
            return;
        };
        let mut rf: Romfs = Romfs::open(&root).unwrap();
        let mut b: Bf = Bf::parse(&rf.read_zs(&format!("Event/EventFlow/{FLOW}.bfevfl.zs")).unwrap()).unwrap();
        let before = b.clone();
        patch(&mut b).unwrap();
        let f: &Flow = b.flows.iter().find(|f| f.name == FLOW).unwrap();
        let start: u16 = f.entries.iter().find(|e| e.name == ENTRY).unwrap().main;
        assert!(f.events[usize::from(start)].name.starts_with(PREFIX));
        let mut outs: Vec<u16> = Vec::new();
        for w in &walks() {
            let (end, wrote): (u16, Vec<String>) = ends(f, start, &state(w));
            assert_eq!(wrote.len(), usize::from(w[0] && (w[1] || w[2] || w[3])), "{w:?}");
            outs.push(end);
        }
        assert!(outs.iter().all(|e| *e == outs[0]));
        let original = before.flows.iter().find(|f| f.name == FLOW).unwrap();
        assert_eq!(&f.events[..original.events.len()], original.events.as_slice());
        assert!(patch(&mut b).is_err());
    }
}
