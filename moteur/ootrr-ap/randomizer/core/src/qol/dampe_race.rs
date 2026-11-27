use crate::bfevfl::{Bf, Event, Flow, Val};
use crate::byml::{Byml, Node};
use crate::error::{Error, Res};

pub const FLOW: &str = "MiniGame_DampeRace";
pub const STATE: &str = "Minigame_DampeRace_TreasureBoxState";
pub const GRAVE: &str = "Banc/Graveyard/Graveyard_Adult_Static.bcett.byml.zs";
pub const LOGIC: &str = "Logic/UnderTheGrave_Prefab_6971.logic.module.ainb";
pub const AP_HEART_CHEST: u64 = 5534919361313859554;

pub const HEART: u64 = 7277816997830770001;
pub const HEART_AT: [f32; 3] = [-3.157, 82.6, 75.47];

pub const BLOCK: u64 = 7277816997830770002;
pub const BLOCK_AT: [f32; 3] = [-22.4205, 84.1, 77.3269];
pub const BLOCK_TURN: f32 = std::f32::consts::FRAC_PI_2;
const BLOCK_ACTOR: &str = "Obj_SongOfTimeBlock_A_01";

pub const RUPEE_CHESTS: [&str; 2] = ["Graveyard Dampe Race Low Rupee Chest", "Graveyard Dampe Race High Rupee Chest"];
pub const RUPEE_WHY: &str = "each later Dampé race shows it again, so it keeps its rupees";

pub const NOTE: &str = "One Dampé race: the original Hookshot and heart-piece reward chests appear after the first race. Each keeps its original AP identity and assigned reward; the second chest stands across from Dampé. A Song of Time block adds a platform. Optional; no extra vanilla reward is created.";

fn named(f: &Flow, name: &str) -> Res<usize> {
    let hits: Vec<usize> = (0..f.events.len()).filter(|&i| f.events[i].name == name).collect();
    match hits.as_slice() {
        [i] => Ok(*i),
        _ => Err(Error::Msg(format!("one dampe race: expected one {name} in {FLOW}, found {}", hits.len()))),
    }
}

fn param<'a>(e: &'a Event, k: &str) -> Option<&'a Val> {
    e.kind.params().and_then(|c| c.get(k))
}

fn is(e: &Event, k: &str, v: &str) -> bool {
    param(e, k) == Some(&Val::Str(v.to_string()))
}

pub fn patch(b: &mut Bf) -> Res<()> {
    let f: &mut Flow = b.flows.iter_mut().find(|f| f.name == FLOW).ok_or(Error::Format("one dampe race: MiniGame_DampeRace has no flow of its name"))?;
    let heart: usize = named(f, "Event364")?;
    if !(is(&f.events[heart], "GameDataName", STATE) && is(&f.events[heart], "Value", "AppearHeartPiece")) {
        return Err(Error::Format("one dampe race: Event364 no longer shows the Heart Piece chest"));
    }
    if let Some(c) = f.events[heart].kind.params_mut() {
        for (k, v) in c.items.iter_mut() {
            if k == "Value" {
                *v = Val::Str("AppearRupee".to_string());
            }
        }
    }
    Ok(())
}

fn at(p: [f32; 3]) -> Node {
    Node::Arr(p.iter().map(|x| Node::F32(*x)).collect())
}

fn actor(gyaml: &str, hash: u64, pos: [f32; 3], rot: Node, srt: u32) -> Node {
    Node::Map(vec![
        ("Gyaml".to_string(), Node::Str(gyaml.to_string())),
        ("Hash".to_string(), Node::U64(hash)),
        ("Phive".to_string(), Node::Map(vec![("Placement".to_string(), Node::Map(vec![("ID".to_string(), Node::U64(hash))]))])),
        ("Rotate".to_string(), rot),
        ("SRTHash".to_string(), Node::U32(srt)),
        ("Translate".to_string(), at(pos)),
    ])
}

pub fn place(raw: &[u8]) -> Res<Vec<u8>> {
    let mut y: Byml = Byml::parse(raw)?;
    let list: &mut Vec<Node> = y.root.get_mut("Actors").and_then(|a| a.as_arr_mut()).ok_or(Error::Format("one dampe race: the grave map has no actors"))?;
    let hash = |a: &Node| match a.get("Hash") {
        Some(Node::U64(h)) => Some(*h),
        _ => None,
    };
    if list.iter().any(|a| matches!(hash(a), Some(h) if h == HEART || h == BLOCK)) {
        return Err(Error::Format("one dampe race: the grave map already holds the new actors"));
    }
    // Preserve the released AP check's actual chest hash and reward. The
    // upstream new untracked Heart Piece must never become a second reward.
    let from = list.iter_mut().find(|a| hash(a) == Some(AP_HEART_CHEST))
        .ok_or(Error::Format("one dampe race: the original reward chest is missing"))?;
    if !from.get("Gyaml").and_then(Node::as_str).is_some_and(|n| n.starts_with("Obj_TBox_")) {
        return Err(Error::Format("one dampe race: the original reward is not a chest"));
    }
    from.set("Translate", at(HEART_AT));
    // Its old callback would mark the Hookshot chest opened when both prizes
    // appear together. Ordinary chest collection remains native and durable.
    let dynamic = from.get_mut("Dynamic").ok_or(Error::Format("one dampe race: no chest parameters"))?;
    if dynamic.get("GetEventName").and_then(Node::as_str) == Some("MiniGame_DampeRace_OpenGoalTBox") {
        dynamic.remove("GetEventName");
    }
    let srt: u32 = match from.get("SRTHash") {
        Some(Node::U32(s)) => *s,
        _ => 0,
    };
    list.push(actor(BLOCK_ACTOR, BLOCK, BLOCK_AT, at([0.0, BLOCK_TURN, 0.0]), srt));
    y.write()
}

pub fn first_race_logic(raw: &[u8]) -> Res<Vec<u8>> {
    use crate::ainb::Ainb;
    let mut a = Ainb::parse(raw)?;
    let targets: Vec<_> = a.find_els("ActorLogicTreasureBox").into_iter()
        .filter(|i| a.prop_str(*i, "InstanceName") == Some("Obj_TBox_A_02_NoBake_669b")).collect();
    let [target] = targets.as_slice() else {
        return Err(Error::Format("one dampe race: expected the original heart reward chest"));
    };
    let appear = a.find_in(*target, 1, "isSpawnAct").and_then(|g| a.input(1, g))
        .ok_or(Error::Format("one dampe race: no native treasure appearance input"))?;
    if appear.src < 0 || a.in_str(appear.src as usize, "GameDataNameBool") != Some("UnderTheGrave_DampeRace_TreasureAppear") {
        return Err(Error::Format("one dampe race: the native race completion gate differs"));
    }
    let create = a.find_in(*target, 1, "Logic_Create")
        .ok_or(Error::Format("one dampe race: no chest creation input"))?;
    let previous = a.input(1, create).ok_or(Error::Format("one dampe race: missing creation source"))?;
    let name = a.pool.add("Logic_Create");
    crate::gerudo_card::rewire(&mut a, *target, create, previous.src, name,
        appear.src as usize, appear.plug)?;
    if !crate::ainb::audit(&a).is_empty() {
        return Err(Error::Format("one dampe race: invalid chest logic after patch"));
    }
    let out = a.write()?;
    if Ainb::parse(&out)? != a { return Err(Error::Format("one dampe race: chest logic did not read back")); }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_native_race_keeps_both_ap_hashes_and_the_assigned_prizes() {
        let Some(root) = std::env::var_os("OOTRR_ROMFS").map(std::path::PathBuf::from) else { return };
        let mut rf = crate::romfs::Romfs::open(&root).unwrap();
        let raw = rf.read_zs(GRAVE).unwrap();
        let original = Byml::parse(&raw).unwrap();
        let before = original.root.get("Actors").unwrap().as_arr().unwrap();
        let output = Byml::parse(&place(&raw).unwrap()).unwrap();
        let after = output.root.get("Actors").unwrap().as_arr().unwrap();
        assert_eq!(after.len(), before.len() + 1);
        assert!(!after.iter().any(|a| a.get("Hash") == Some(&Node::U64(HEART))));
        for hash in [AP_HEART_CHEST, 16041366920820397198] {
            let old = before.iter().find(|a| a.get("Hash") == Some(&Node::U64(hash))).unwrap();
            let new = after.iter().find(|a| a.get("Hash") == Some(&Node::U64(hash))).unwrap();
            assert_eq!(old.get("Dynamic").unwrap().get("Drop__DropActor"), new.get("Dynamic").unwrap().get("Drop__DropActor"));
        }
        let logic = rf.read(LOGIC).unwrap();
        let changed = first_race_logic(&logic).unwrap();
        assert_ne!(changed, logic);
    }
}
