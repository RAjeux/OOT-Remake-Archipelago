use std::collections::BTreeMap as BM;
use std::path::Path as P;

use crate::byml::{Byml, Node};
use crate::chest_slot::{self, LIST};
use crate::error::{Error as E, Res};
use crate::placement::{drops, hash_of};
use crate::romfs::Romfs;
use crate::staging::{edit_staged, Out};

pub const ACTOR: &str = "Obj_TBox_A_04";
pub const CHEST: &str = "Obj_TBox_A_01";
pub const LOGIC: &str = "Gimmick_TrapTreasureBox_Set";
pub const OFF: &str = "it is a trap chest in the game";

pub const NAMES: [&str; 6] = [
    "Spirit Temple First Mirror Left Chest",
    "Gerudo Training Ground Heavy Block Fourth Chest",
    "Ganons Castle Water Trial Left Chest",
    "Ganons Castle Light Trial First Right Chest",
    "Ganons Castle Light Trial Second Left Chest",
    "Ganons Castle Light Trial Third Right Chest",
];

pub fn gated(name: &str) -> bool {
    NAMES.contains(&name)
}

fn reference(n: &Node) -> Option<u64> {
    match n.get("Reference") {
        Some(Node::U64(x)) => Some(*x),
        Some(Node::I64(x)) => Some(*x as u64),
        _ => None,
    }
}

fn text<'a>(n: &'a Node, k: &str) -> &'a str {
    n.get(k).and_then(|v| v.as_str()).unwrap_or("")
}

fn unhook(g: &mut Node, hash: u64) -> usize {
    let whole: bool = text(g, "Logic").contains(LOGIC);
    let Some(refs) = g.get_mut("References").and_then(|r| r.as_arr_mut()) else {
        return 0;
    };
    let subs: Vec<String> = refs
        .iter()
        .filter(|r| text(r, "Id") == "AiGroup" && text(r, "Logic").contains(LOGIC))
        .filter_map(|r| text(r, "Path").strip_suffix("AiGroup").map(|p| p.to_string()))
        .collect();
    let before: usize = refs.len();
    refs.retain(|r| reference(r) != Some(hash) || !(whole || subs.iter().any(|p| text(r, "Path").starts_with(p.as_str()))));
    before - refs.len()
}

pub fn open(y: &mut Byml, hash: u64, drop: &str) -> Res<usize> {
    let mut n: usize = 0;
    if let Some(list) = y.root.get_mut("Actors").and_then(|a| a.as_arr_mut()) {
        for a in list.iter_mut() {
            if hash_of(a) != Some(hash) || a.get("Gyaml").and_then(|v| v.as_str()) != Some(ACTOR) {
                continue;
            }
            a.set("Gyaml", Node::Str(CHEST.to_string()));
            let set: bool = match a.get_mut("Dynamic") {
                Some(d) => d.set("Drop__DropActor", Node::Str(drop.to_string())),
                None => a.set("Dynamic", Node::Map(vec![("Drop__DropActor".to_string(), Node::Str(drop.to_string()))])),
            };
            if !set {
                return Err(E::Msg(format!("trap chest {hash} could not take an item")));
            }
            n += 1;
        }
    }
    if n == 0 {
        return Ok(0);
    }
    let mut cut: usize = 0;
    if let Some(gs) = y.root.get_mut("AiGroups").and_then(|g| g.as_arr_mut()) {
        for g in gs.iter_mut() {
            cut += unhook(g, hash);
        }
    }
    if cut == 0 {
        return Err(E::Msg(format!("trap chest {hash} has no trap logic to unhook, the game files differ")));
    }
    Ok(n)
}

pub fn stage(rf: &mut Romfs, more: &mut Vec<Out>, work: &P, hashes: &[u64]) -> Res<()> {
    if hashes.is_empty() {
        return Ok(());
    }
    let mut want: Vec<u64> = hashes.to_vec();
    want.sort_unstable();
    want.dedup();
    let names: BM<u32, String> = chest_slot::names_of(drops(rf)?.into_iter().map(|x| x.hash));
    edit_staged(rf, more, work, LIST, true, |raw| {
        let mut y: Byml = Byml::parse(raw)?;
        let free: Vec<u32> = chest_slot::spares(&y);
        let mut i: usize = 0;
        for h in &want {
            if chest_slot::has(&y, *h) {
                continue;
            }
            let s: u32 = *free.get(i).ok_or(E::Format("no spare flag left for a trap chest"))?;
            chest_slot::add(&mut y, *h, s, &names)?;
            i += 1;
        }
        y.write()
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_native_trap_chest_becomes_one_persistent_ap_reward_without_its_trap() {
        let Some(root) = std::env::var_os("OOTRR_ROMFS").map(std::path::PathBuf::from) else { return };
        let mut rf = Romfs::open(&root).unwrap();
        let mut found = Vec::new();
        for file in crate::placement::banc_files(&rf).unwrap() {
            let raw = rf.read_zs(&file).unwrap();
            if !raw.windows(ACTOR.len()).any(|s| s == ACTOR.as_bytes()) { continue; }
            let original = Byml::parse(&raw).unwrap();
            let targets: Vec<u64> = original.root.get("Actors").and_then(Node::as_arr).unwrap_or(&[])
                .iter().filter(|a| a.get("Gyaml").and_then(Node::as_str) == Some(ACTOR))
                .filter_map(hash_of).collect();
            for hash in targets {
                let mut edited = original.clone();
                assert_eq!(open(&mut edited, hash, "Item_AP_TrapCheck").unwrap(), 1);
                let old = original.root.get("Actors").unwrap().as_arr().unwrap();
                let new = edited.root.get("Actors").unwrap().as_arr().unwrap();
                assert_eq!(new.len(), old.len());
                for (a, b) in old.iter().zip(new) {
                    if hash_of(a) == Some(hash) {
                        assert_eq!(b.get("Gyaml").and_then(Node::as_str), Some(CHEST));
                        assert_eq!(b.get("Dynamic").unwrap().get("Drop__DropActor").and_then(Node::as_str), Some("Item_AP_TrapCheck"));
                        assert_eq!(hash_of(b), Some(hash));
                    } else { assert_eq!(a, b); }
                }
                assert_eq!(Byml::parse(&edited.write().unwrap()).unwrap().root, edited.root);
                found.push(hash);
            }
        }
        assert_eq!(found.len(), 6);
        let mut outs = Vec::new();
        stage(&mut rf, &mut outs, &root.join("nonexistent-overlay"), &found).unwrap();
        let raw = rf.zs.decompress(&outs[0].z).unwrap();
        let y = Byml::parse(&raw).unwrap();
        assert!(found.iter().all(|hash| chest_slot::has(&y, *hash)));
    }
}
