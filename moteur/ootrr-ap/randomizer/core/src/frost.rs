//! Native Ice Trap effect adapted from OOTRR nightly 4fa6e5a.
//!
//! AP delivery calls a dedicated event through the existing safe receipt queue.
//! No counterfeit equipment, pouch grant, receipt watcher or second network
//! client is involved. The sensor applies the game's ordinary frozen attack.

pub mod elink;
pub mod sensor;

use std::path::Path;

use crate::bfevfl::{Bf, Cont, Entry, Event, Kind, Val};
use crate::byml::{Byml, Node};
use crate::error::{Error, Res};
use crate::pickup_pack::{pack_of, rows, sizes, PACK_DICT};
use crate::romfs::Romfs;
use crate::rsizetable::Rst;
use crate::sarc;
use crate::staging::{self, Out};

pub const EVENT: &str = "AP_IceTrap";
pub const FLOW: &str = "Dm_SY_GetInEvent";
pub const CHILD_PACK: &str = "Pack/Actor/Player_Child.pack.zs";
const CHILD_CONDITION: &str = "Component/ConditionParam/Player_Child.game__component__ConditionParam.bgyml";
const CHILD_LINK: &str = "Component/ELink/Player.engine__component__ELinkParam.bgyml";
const CHILD_USER: &str = "AP_Player_Child_Cold";
const FROZEN_CALL: &str = "Condition_Frozen";
const FULL_BODY_CALL: &str = "全身凍結";
const PARAM_AT: usize = 0x20;

pub fn add_event(b: &mut Bf) -> Res<()> {
    let f = b.flows.iter_mut().find(|f| f.name == FLOW)
        .ok_or(Error::Format("ice trap: no native get-in flow"))?;
    if f.entries.iter().any(|e| e.name == EVENT) {
        return Err(Error::Format("ice trap: duplicate receipt entry"));
    }
    let (a, make) = crate::dungeon_credit::action_slot(f, "GameSystemActor", "EventTriggerRequestCreateConditionSensor")?;
    let (_, clear) = crate::dungeon_credit::action_slot(f, "GameSystemActor", "EventTriggerRequestDeleteConditionSensor")?;
    let at = crate::dungeon_credit::idx(f.events.len())?;
    let end = crate::dungeon_credit::idx(f.events.len() + 1)?;
    f.events.push(Event { name: format!("{EVENT}Clear"), kind: Kind::Action {
        next: end, actor: a, act: clear, params: None } });
    f.events.push(Event { name: format!("{EVENT}Create"), kind: Kind::Action {
        next: crate::bfevfl::flow::NONE, actor: a, act: make,
        params: Some(Cont { items: vec![("ActorName".to_string(), Val::Str(sensor::NAME.to_string()))] }) } });
    f.entries.push(Entry { name: EVENT.to_string(), subs: Vec::new(), vars: Vec::new(), main: at, pad: 0 });
    Ok(())
}

fn child(raw: &[u8]) -> Res<Vec<u8>> {
    let mut es = sarc::parse(raw)?;
    let c = sarc::get(&es, CHILD_CONDITION).ok_or(Error::Format("ice trap: child condition resource missing"))?;
    let mut y = Byml::parse(&c.data)?;
    y.root.set("IsEnableFrozen", Node::Bool(true));
    sarc::set(&mut es, CHILD_CONDITION, y.write()?);
    let c = sarc::get(&es, CHILD_LINK).ok_or(Error::Format("ice trap: child effect resource missing"))?;
    let mut y = Byml::parse(&c.data)?;
    y.root.set("UserName", Node::Str(CHILD_USER.to_string()));
    sarc::set(&mut es, CHILD_LINK, y.write()?);
    sarc::write(&es)
}

fn frozen_effects(raw: &[u8]) -> Res<Vec<u8>> {
    let mut link = elink::Link::parse(raw)?;
    let mut hits = 0;
    for user in 0..link.users.len() {
        if let (Some(cold), Some(full)) = (link.find_key(user, FROZEN_CALL), link.find_key(user, FULL_BODY_CALL)) {
            let pos = link.users[user].calls[full].param_pos();
            link.users[user].calls[cold].raw[PARAM_AT..PARAM_AT + 8].copy_from_slice(&pos.to_le_bytes());
            hits += 1;
        }
    }
    if hits == 0 { return Err(Error::Format("ice trap: native full-body frozen effect missing")); }
    if link.user(CHILD_USER).is_none() {
        let adult = link.user("Player_Adult").ok_or(Error::Format("ice trap: adult effect user missing"))?;
        let scale = link.direct_f32(0.5).ok_or(Error::Format("ice trap: child scale constant missing"))?;
        let mut user = link.users[adult].clone();
        for shell in 1..=16 {
            let c = link.find_key(adult, &format!("Condition_Frozen_{shell:02}"))
                .ok_or(Error::Format("ice trap: a native frozen shell is missing"))?;
            let mut param = link.param_at(user.calls[c].param_pos()).cloned()
                .ok_or(Error::Format("ice trap: a frozen shell has no parameters"))?;
            const BONE: u64 = 1 << 12;
            const SCALE: u64 = 1 << 13;
            if param.mask & BONE == 0 || param.mask & SCALE != 0 {
                return Err(Error::Format("ice trap: frozen shell scale schema differs"));
            }
            let slot = (param.mask & (BONE - 1)).count_ones() as usize;
            *param.vals.get_mut(slot).ok_or(Error::Format("ice trap: short frozen shell record"))? = scale;
            param.mask = (param.mask & !BONE) | SCALE;
            let position = link.add_param(param);
            user.calls[c].raw[PARAM_AT..PARAM_AT + 8].copy_from_slice(&position.to_le_bytes());
        }
        let hash = crate::rsizetable::hash(CHILD_USER);
        if link.hashes.contains(&hash) { return Err(Error::Format("ice trap: effect user hash collision")); }
        user.hash = hash;
        let index = link.hashes.partition_point(|h| *h < hash);
        link.users.push(user);
        link.hashes.insert(index, hash);
        link.slots.insert(index, link.users.len() - 1);
    }
    link.write()
}

fn sensor_pack(rf: &mut Romfs) -> Res<sensor::Made> {
    let sun = sarc::parse(&rf.read_zs(&pack_of(sensor::SUN))?)?;
    let ice = sarc::parse(&rf.read_zs(&pack_of(sensor::FREEZARD))?)?;
    let chest = sarc::parse(&rf.read_zs(&pack_of(sensor::TRAP_CHEST))?)?;
    sensor::make(&sun, &ice, &chest)
}

pub fn stage(rf: &mut Romfs, outs: &mut Vec<Out>, work: &Path) -> Res<()> {
    let made = sensor_pack(rf)?;
    outs.push(Out { path: pack_of(sensor::NAME), old: 0, new: made.pack.len(),
        z: crate::zs::compress_raw(&made.pack, Some(PACK_DICT))? });
    for (path, actor_table) in [(rows::ACTOR_INFO, true), (rows::GAME_ACTOR_INFO, false)] {
        staging::edit_staged(rf, outs, work, path, true, |raw| {
            let mut y = Byml::parse(raw)?;
            let source = rows::need(&y, sensor::SUN, path)?.clone();
            let mut row = if actor_table {
                rows::actor_row(&source, sensor::NAME, rows::heap(&y, sensor::SUN)?)
            } else { rows::game_row(&source, &source, sensor::NAME) };
            if actor_table && row.get("ActorName").is_some() {
                row.set("ActorName", Node::Str(sensor::NAME.to_string()));
            }
            rows::insert(&mut y, row)?;
            y.write()
        })?;
    }
    crate::story_skip::stage_late(rf, outs, work, FLOW, add_event)?;
    staging::edit_staged(rf, outs, work, CHILD_PACK, true, child)?;
    staging::edit_staged(rf, outs, work, elink::FILE, true, frozen_effects)?;
    Ok(())
}

pub fn allocate(rf: &mut Romfs, table: &mut Rst, out: &Out) -> Res<()> {
    if out.path != pack_of(sensor::NAME) || out.old != 0 {
        return Err(Error::Format("ice trap: unexpected new resource allocation"));
    }
    let made = sensor_pack(rf)?;
    table.set_size(&out.path, sizes::pack_size(out.new)?)?;
    for (name, len) in made.fresh {
        table.set_size(&name, sizes::file_size(table, &made.peers, &name, len)?)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sarc::Entry as SarcEntry;

    #[test]
    fn receipt_uses_only_native_sensor_actions_without_a_pouch_grant() {
        let Some(root) = std::env::var_os("OOTRR_ROMFS").map(std::path::PathBuf::from) else { return };
        let mut rf = Romfs::open(&root).unwrap();
        let mut b = Bf::parse(&rf.read_zs(&format!("Event/EventFlow/{FLOW}.bfevfl.zs")).unwrap()).unwrap();
        add_event(&mut b).unwrap();
        let f = b.flows.iter().find(|f| f.name == FLOW).unwrap();
        let start = f.entries.iter().find(|e| e.name == EVENT).unwrap().main;
        let mut at = start;
        for expected in ["EventTriggerRequestDeleteConditionSensor", "EventTriggerRequestCreateConditionSensor"] {
            let Kind::Action { next, actor, act, .. } = &f.events[at as usize].kind else { panic!() };
            assert_eq!(f.actors[*actor as usize].name, "GameSystemActor");
            assert_eq!(f.actors[*actor as usize].actions[*act as usize], expected);
            at = *next;
        }
        assert_eq!(at, crate::bfevfl::flow::NONE);
        assert_eq!(Bf::parse(&b.write().unwrap()).unwrap(), b);
    }

    #[test]
    fn condition_sensor_and_effects_build_from_read_only_game_resources() {
        let Some(root) = std::env::var_os("OOTRR_ROMFS").map(std::path::PathBuf::from) else { return };
        let mut rf = Romfs::open(&root).unwrap();
        let made = sensor_pack(&mut rf).unwrap();
        let entries: Vec<SarcEntry> = sarc::parse(&made.pack).unwrap();
        assert!(entries.iter().any(|e| e.name == format!("Actor/{}.engine__actor__ActorParam.bgyml", sensor::NAME)));
        let raw = rf.read_zs(CHILD_PACK).unwrap();
        let out = child(&raw).unwrap();
        assert_ne!(out, raw);
        let raw = rf.read_zs(elink::FILE).unwrap();
        let changed = frozen_effects(&raw).unwrap();
        let link = elink::Link::parse(&changed).unwrap();
        assert!(link.user(CHILD_USER).is_some());
        let mut outs = Vec::new();
        stage(&mut rf, &mut outs, Path::new("no-test-overlay")).unwrap();
        let mut table = crate::rsizetable::load(&mut rf).unwrap();
        for out in outs {
            if out.old == 0 { allocate(&mut rf, &mut table, &out).unwrap(); }
            else { staging::grow_out(&mut rf, &mut table, &out).unwrap(); }
        }
        assert!(table.get(&pack_of(sensor::NAME)).is_some());
    }
}
