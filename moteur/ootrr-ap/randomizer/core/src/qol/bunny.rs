//! Bunny Hood effect, done entirely in the player's AI graphs (no code patch).
//!
//! Masks have no effect fields and running is code (ExecutePlayerMove), but the node
//! table (AI/NodeDefinition) has everything needed to scale the result each frame.
//! The worn head armor comes from QueryEquipmentUserGetStaticEquipmentGameActorLink
//! (slot 0 = Head) checked with QueryCheckActorFileName, the same pair the game's own
//! Player.event.root uses for EventQueryPlayerIsEquipArmor.
//!
//! The head slot keeps the selected mask (the one on D-pad up) even while it is not
//! worn, so the hood check alone stayed true after the hood came off. Whether the head
//! armor is worn is game data PlayerStatus.IsActiveHeadArmor (the era change flow sets
//! it false to take the mask off), read with QueryGetNonStructGameDataBool.
//!
//! One speed node joins the move node's parallel and runs right after it every frame:
//! speed = min(QueryPhysicsCctGetForwardSpeedMps x rate, cap), where rate and cap come
//! from QuerySelectF32ByBool (true picks A): 1.5 and the cap while the hood is worn,
//! 1.0 and no cap otherwise. A first version switched between two move nodes with a
//! selector; the selector kept the hood branch after the hood came off, and the extra
//! move node was a likely cause of stutters.
//!
//! The cap depends on the form: QueryIsPlayerChild (the check Enemy_Beamos.root uses)
//! picks the child or the adult cap. Player_Child, Player_Adult and Player_Base carry
//! byte-identical copies of these graphs under the same path, and with only the child
//! pack patched the adult ran the child graph anyway, held at the child cap. So both
//! packs get the same graph, and the form is read at run time, not baked in per pack.
//!
//! Growing the graphs needs their own size table entries grown too (staging::grow_out),
//! and each actor's heap grows to fit the added nodes.

use crate::ainb::build::Spec;
use crate::ainb::{audit, Ainb, Plug};
use crate::byml::{Byml, Node};
use crate::error::{Error, Res};
use crate::qol::{edit_zs, Have};
use crate::romfs::Romfs;
use crate::sarc;
use crate::staging::Out;

pub const FILE: &str = "Pack/Actor/Player_Child.pack.zs";
pub const ADULT_FILE: &str = "Pack/Actor/Player_Adult.pack.zs";
pub const ACTOR_INFO: &str = crate::pickup_pack::rows::ACTOR_INFO;
pub const ACTOR: &str = "Player_Child";
pub const ADULT_ACTOR: &str = "Player_Adult";
/// The player packs that carry the graphs, with the actor whose heap runs them.
pub const PACKS: [(&str, &str); 2] = [(FILE, ACTOR), (ADULT_FILE, ADULT_ACTOR)];
/// AI node instances come out of the actor's InstanceHeapSize, which the game sizes
/// tightly (Player_Child 5692448); a little room for the added nodes.
pub const HEAP_EXTRA: i32 = 0x20000;
pub const MASK: &str = "Armor_Child_Mask_Bunny";
pub const RATE: f32 = 1.5;
/// Effectively no cap, used while the hood is off.
pub const OPEN: f32 = 1000.0;
/// Adult over child speed. Run speed is code and animation, not a parameter, but the
/// paired parameters scale by this: RollingMaxSpeed 6.75 (Player) over 5.625 (Player_Child).
pub const ADULT_SCALE: f32 = 6.75 / 5.625;
pub const WALK: Site = Site { file: "AI/Player.action.walk.module.ainb", node: "ExecutePlayerMove", cap: 10.0, adult_cap: 10.0 * ADULT_SCALE };
/// Child jump take-off speed is JumpMaxInitSpeed 4.5 in PlayerGameParam/Player_Child.
pub const JUMP: Site = Site { file: "AI/Player.action.jump.module.ainb", node: "ExecutePlayerJump", cap: 4.5 * RATE, adult_cap: 4.5 * RATE * ADULT_SCALE };

const LINK: &str = "game::actor::ActorLinkBase";
const MARK: &str = "QueryCheckActorFileName";
const SET: &str = "ExecutePhysicsCctSetForwardSpeedMps";
pub const WORN: &str = "PlayerStatus.IsActiveHeadArmor";
const GET_BOOL: &str = "QueryGetNonStructGameDataBool";
pub const IS_CHILD: &str = "QueryIsPlayerChild";

pub const NOTE_SPEED: &str = "Wearing the Bunny Hood makes Link run 1.5 times as fast, like in Majora's Mask. Experimental.";
pub const NOTE_JUMP: &str = "Wearing the Bunny Hood makes Link run 1.5 times as fast and jump 1.5 times as far. Experimental.";

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Mode {
    #[default]
    Off,
    Speed,
    Jump,
}

#[derive(Clone, Copy, Debug)]
pub struct Site {
    pub file: &'static str,
    pub node: &'static str,
    /// Highest speed while the hood is worn, for child and for adult Link.
    pub cap: f32,
    pub adult_cap: f32,
}

pub fn sites(m: Mode) -> Vec<Site> {
    match m {
        Mode::Off => Vec::new(),
        Mode::Speed => vec![WALK],
        Mode::Jump => vec![WALK, JUMP],
    }
}

fn f(v: f32) -> Vec<u8> {
    v.to_le_bytes().to_vec()
}

/// A float that is `on` while the bool from `check` is true, else `off`.
fn pick(seed: &str, check: usize, on: f32, off: f32) -> Spec<'_> {
    Spec::query("QuerySelectF32ByBool", seed).linked(1, "Bool", check, 0).constant(2, "A", f(on)).constant(2, "B", f(off)).out(2, "F32")
}

/// The float from `inner` while the bool from `cond` is true, else `off`.
fn linked_or(seed: &str, cond: usize, inner: usize, off: f32) -> Spec<'_> {
    Spec::query("QuerySelectF32ByBool", seed).linked(1, "Bool", cond, 0).linked(2, "A", inner, 0).constant(2, "B", f(off)).out(2, "F32")
}

/// Adds the hood-scaled speed node as the next child after the move node.
pub fn patch_graph(raw: &[u8], s: &Site) -> Res<Vec<u8>> {
    let mut a: Ainb = Ainb::parse(raw)?;
    if !a.find_els(MARK).is_empty() {
        return Err(Error::Format("bunny hood: the graph is already patched"));
    }
    let mv: usize = match a.find_els(s.node).as_slice() {
        [one] => *one,
        _ => return Err(Error::Msg(format!("bunny hood: {} does not have exactly one {}", s.file, s.node))),
    };
    let (parent, plug): (usize, usize) = a.parent_of(mv)?;
    if a.el_type(parent) != 3 {
        return Err(Error::Msg(format!("bunny hood: {} no longer sits in a parallel", s.node)));
    }
    let seed = |n: &str| format!("ootrr bunny hood {} {n}", s.file);
    let (s1, s2, s3, s4, s5, s6, s7, s8) = (seed("head"), seed("check"), seed("rate"), seed("limit"), seed("speed"), seed("mul"), seed("cap"), seed("set"));
    let (s9, s10, s11, s12, s13) = (seed("worn"), seed("worn rate"), seed("worn limit"), seed("is child"), seed("form cap"));
    let head: usize = a.add_node(&Spec::query("QueryEquipmentUserGetStaticEquipmentGameActorLink", &s1).constant(0, "Slot", vec![0; 4]).out_ptr("Actor", LINK))?;
    let name: Vec<u8> = a.pool.add(MASK).to_le_bytes().to_vec();
    let check: usize = a.add_node(&Spec::query(MARK, &s2).constant(3, "ActorFileName", name).linked_ptr("Actor", LINK, head).out(1, "Bool"))?;
    let key: Vec<u8> = a.pool.add(WORN).to_le_bytes().to_vec();
    let mut get: Spec = Spec::node(GET_BOOL, &s9)
        .prop(1, "DispError", vec![0; 4])
        .prop(1, "OutputOnlyOnEnter", vec![0; 4])
        .constant(0, "GameDataIndex", (-1i32).to_le_bytes().to_vec())
        .constant(1, "IsDirect", vec![0; 4])
        .constant(3, "GameDataFullName", key)
        .out(1, "Value");
    get.role = crate::ainb::build::QUERY;
    let worn: usize = a.add_node(&get)?;
    let child: usize = a.add_node(&Spec::query(IS_CHILD, &s12).out(1, "IsChild"))?;
    let form_cap: usize = a.add_node(&pick(&s13, child, s.cap, s.adult_cap))?;
    let hood_rate: usize = a.add_node(&pick(&s3, check, RATE, 1.0))?;
    let hood_limit: usize = a.add_node(&linked_or(&s4, check, form_cap, OPEN))?;
    let rate: usize = a.add_node(&linked_or(&s10, worn, hood_rate, 1.0))?;
    let limit: usize = a.add_node(&linked_or(&s11, worn, hood_limit, OPEN))?;
    let speed: usize = a.add_node(&Spec::query("QueryPhysicsCctGetForwardSpeedMps", &s5).out(2, "SpeedMps"))?;
    let mul: usize = a.add_node(&Spec::query("QueryMathMulF32", &s6).linked(2, "InputA", speed, 0).linked(2, "InputB", rate, 0).out(2, "Result"))?;
    let cap: usize = a.add_node(&Spec::query("QueryMathF32Min2", &s7).linked(2, "a", mul, 0).linked(2, "b", limit, 0).out(2, "F32"))?;
    let set: usize = a.add_node(&Spec::node(SET, &s8).linked(2, "SpeedMps", cap, 0))?;
    let b: usize = a.params[parent].pl[2][1] as usize;
    let name: u32 = a.params[parent].plugs[plug].b;
    a.params[parent].add_plug(2, plug - b + 1, Plug { a: set as u32, b: name, extra: Vec::new() })?;
    let bad: Vec<String> = audit(&a);
    if !bad.is_empty() {
        return Err(Error::Msg(format!("bunny hood: {}", bad.join("; "))));
    }
    let out: Vec<u8> = a.write()?;
    let back: Ainb = Ainb::parse(&out)?;
    if back.write()? != out || back.params != a.params || back.ins != a.ins || back.outs != a.outs || back.qids != a.qids {
        return Err(Error::Format("bunny hood: the written graph does not read back"));
    }
    Ok(out)
}

pub fn patch_pack(raw: &[u8], m: Mode) -> Res<Vec<u8>> {
    let mut es: Vec<sarc::Entry> = sarc::parse(raw)?;
    for s in sites(m) {
        let g: Vec<u8> = sarc::get(&es, s.file).ok_or(Error::Msg(format!("bunny hood: the player pack has no {}", s.file)))?.data.clone();
        sarc::set(&mut es, s.file, patch_graph(&g, &s)?);
    }
    sarc::write(&es)
}

pub fn heap_of(y: &Byml, actor: &str) -> Option<i32> {
    match crate::pickup_pack::rows::find(y, actor)?.get(crate::pickup_pack::rows::HEAP)? {
        Node::I32(v) => Some(*v),
        Node::U32(v) => i32::try_from(*v).ok(),
        _ => None,
    }
}

/// Grows the heap of every player actor in PACKS.
pub fn grow_heap(raw: &[u8]) -> Res<Vec<u8>> {
    let mut y: Byml = Byml::parse(raw)?;
    let mut want: Vec<(&str, i32)> = Vec::new();
    for (_, actor) in PACKS {
        let old: i32 = heap_of(&y, actor).ok_or(Error::Msg(format!("bunny hood: the actor table has no {actor} heap size")))?;
        let new: i32 = old.checked_add(HEAP_EXTRA).ok_or(Error::Format("bunny hood: the heap size does not fit"))?;
        let rows: &mut Vec<Node> = y.root.as_arr_mut().ok_or(Error::Format("bunny hood: the actor table is not a row list"))?;
        let row: &mut Node = rows.iter_mut().find(|r| crate::pickup_pack::rows::id(r) == Some(actor)).ok_or(Error::Msg(format!("bunny hood: no {actor} row")))?;
        let v: Node = match row.get(crate::pickup_pack::rows::HEAP) {
            Some(Node::U32(_)) => Node::U32(new as u32),
            _ => Node::I32(new),
        };
        row.set(crate::pickup_pack::rows::HEAP, v);
        want.push((actor, new));
    }
    let out: Vec<u8> = y.write()?;
    let back: Byml = Byml::parse(&out)?;
    if want.iter().any(|(actor, new)| heap_of(&back, actor) != Some(*new)) {
        return Err(Error::Format("bunny hood: the actor table does not read back"));
    }
    Ok(out)
}

pub fn stage(rf: &mut Romfs, m: Mode, have: Have) -> Res<Vec<Out>> {
    if m == Mode::Off {
        return Ok(Vec::new());
    }
    let mut outs: Vec<Out> = Vec::new();
    for (file, _) in PACKS {
        outs.push(edit_zs(rf, have, file, |raw| patch_pack(raw, m))?);
    }
    outs.push(edit_zs(rf, have, ACTOR_INFO, grow_heap)?);
    Ok(outs)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn dump() -> Option<PathBuf> {
        let p: PathBuf = ootrr_game::test_romfs::path();
        if p.is_dir() {
            Some(p)
        } else {
            eprintln!("skipped: no romfs at {}, set OOTRR_ROMFS", p.display());
            None
        }
    }

    #[test]
    fn modes_pick_their_graphs() {
        assert!(sites(Mode::Off).is_empty());
        assert_eq!(sites(Mode::Speed).len(), 1);
        assert_eq!(sites(Mode::Jump).iter().map(|s| s.node).collect::<Vec<_>>(), vec!["ExecutePlayerMove", "ExecutePlayerJump"]);
    }

    #[test]
    fn adult_caps_sit_above_the_child_caps() {
        for s in [WALK, JUMP] {
            assert!(s.adult_cap > s.cap, "{}", s.file);
            assert!((s.adult_cap / s.cap - 1.2).abs() < 1e-6, "{}", s.file);
        }
    }

    #[test]
    fn the_player_graphs_get_the_hood_check() {
        let Some(root) = dump() else { return };
        let mut rf: Romfs = Romfs::open(&root).unwrap();
        let outs: Vec<Out> = stage(&mut rf, Mode::Jump, &|_: &str| None).unwrap();
        assert_eq!(outs.iter().map(|o| o.path.as_str()).collect::<Vec<_>>(), vec![FILE, ADULT_FILE, ACTOR_INFO]);
        let table: Byml = rf.read_byml(ACTOR_INFO).unwrap();
        let grown: Byml = Byml::parse(&rf.zs.decompress(&outs[2].z).unwrap()).unwrap();
        for (_, actor) in PACKS {
            assert_eq!(heap_of(&grown, actor), Some(heap_of(&table, actor).unwrap() + HEAP_EXTRA), "{actor} heap");
        }
        let mut t: crate::rsizetable::Rst = crate::rsizetable::load(&mut rf).unwrap();
        let before: Vec<u32> = [WALK, JUMP].iter().map(|s| t.get(s.file).unwrap()).collect();
        assert!(crate::staging::grow_out(&mut rf, &mut t, &outs[0]).unwrap() >= 3, "the pack and both graphs");
        assert!(crate::staging::grow_out(&mut rf, &mut t, &outs[1]).unwrap() >= 1, "the adult pack");
        for (s, b) in [WALK, JUMP].iter().zip(before) {
            assert!(t.get(s.file).unwrap() > b, "{} keeps its vanilla budget", s.file);
        }
        let child: Vec<sarc::Entry> = sarc::parse(&rf.zs.decompress(&outs[0].z).unwrap()).unwrap();
        let adult: Vec<sarc::Entry> = sarc::parse(&rf.zs.decompress(&outs[1].z).unwrap()).unwrap();
        for s in [WALK, JUMP] {
            assert_eq!(sarc::get(&child, s.file).unwrap().data, sarc::get(&adult, s.file).unwrap().data, "{} matches in both packs", s.file);
        }
        let es: Vec<sarc::Entry> = child;
        for s in [WALK, JUMP] {
            let a: Ainb = Ainb::parse(&sarc::get(&es, s.file).unwrap().data).unwrap();
            assert!(audit(&a).is_empty());
            assert_eq!(a.find_els(s.node).len(), 1, "no second move node");
            let chk: usize = a.find_els(MARK)[0];
            assert_eq!(a.in_str(chk, "ActorFileName"), Some(MASK));
            let mv: usize = a.find_els(s.node)[0];
            let set: usize = a.find_els(SET)[0];
            let (p, at) = a.parent_of(mv).unwrap();
            assert_eq!(a.parent_of(set).unwrap(), (p, at + 1), "the speed node runs right after the move node");
            assert_eq!(a.find_els("QuerySelectF32ByBool").len(), 5);
            assert_eq!(a.find_els(IS_CHILD).len(), 1, "the cap follows the form");
            let w: usize = a.find_els(GET_BOOL)[0];
            assert_eq!(a.in_str(w, "GameDataFullName"), Some(WORN));
            assert_eq!(a.in_s32(w, "GameDataIndex"), Some(-1));
            assert!(patch_graph(&sarc::get(&es, s.file).unwrap().data, &s).is_err());
        }
        let speed: Vec<Out> = stage(&mut rf, Mode::Speed, &|_: &str| None).unwrap();
        let es: Vec<sarc::Entry> = sarc::parse(&rf.zs.decompress(&speed[0].z).unwrap()).unwrap();
        assert!(Ainb::parse(&sarc::get(&es, JUMP.file).unwrap().data).unwrap().find_els(MARK).is_empty());
        assert!(stage(&mut rf, Mode::Off, &|_: &str| None).unwrap().is_empty());
    }
}
