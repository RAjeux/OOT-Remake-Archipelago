use crate::byml::{Byml, Node};
use crate::cow_clone::data::{PLAIN, TEMPLATE};
use crate::cow_clone::flow::{give_row, push_row, talk_row, GIVE, OLD_PUSH, PUSH, TALK};
use crate::error::{Error as E, Res};
use crate::pickup_pack::rows::{self, HEAP, ROW_ID};
use crate::pickup_pack::tag::Table;

pub const FLOWCHART: &str = "FlowchartFileName";
pub const ENTRY: &str = "EntryPointName";
pub const KIDS: &str = "ChildEventList";

pub fn chart(class: &str) -> String {
    format!("Work/Event/EventFlow/{class}.evfc")
}

fn id(n: &Node) -> &str {
    n.get(ROW_ID).and_then(|v| v.as_str()).unwrap_or("")
}

fn list(y: &mut Byml) -> Res<&mut Vec<Node>> {
    y.root.as_arr_mut().ok_or(E::Format("cow clone: a table root is not a row list"))
}

fn row(y: &Byml, name: &str) -> Res<Node> {
    y.root
        .as_arr()
        .and_then(|a| a.iter().find(|r| id(r) == name))
        .cloned()
        .ok_or_else(|| E::Msg(format!("cow clone: the table has no {name} row, the game files differ")))
}

fn put(y: &mut Byml, r: Node) -> Res<usize> {
    let name: String = id(&r).to_string();
    let l: &mut Vec<Node> = list(y)?;
    if l.iter().any(|x| id(x) == name) {
        return Err(E::Msg(format!("cow clone: the table already holds {name}")));
    }
    let at: usize = l.partition_point(|x| id(x) < name.as_str());
    l.insert(at, r);
    Ok(at)
}

pub fn heap(base: i32, house_len: usize, len: usize) -> Res<i32> {
    let more: i32 = i32::try_from(len.saturating_sub(house_len)).map_err(|_| E::Format("cow clone: the pack grew too much"))?;
    let n: i32 = base.checked_add(more).ok_or(E::Format("cow clone: the heap size does not fit"))?;
    Ok((n + 7) / 8 * 8)
}

pub fn actors(info: &mut Byml, game: &mut Byml, class: &str, house_len: usize, len: usize) -> Res<usize> {
    let mut a: Node = row(info, TEMPLATE)?;
    let base: i32 = rows::own_heap(info, TEMPLATE)?;
    let h: i32 = heap(base, house_len, len)?;
    let v: Node = match a.get(HEAP) {
        Some(Node::U32(_)) => Node::U32(h.max(0) as u32),
        _ => Node::I32(h),
    };
    a.set(HEAP, v);
    a.set(ROW_ID, Node::Str(class.to_string()));
    let mut g: Node = row(game, TEMPLATE)?;
    g.set(ROW_ID, Node::Str(class.to_string()));
    let i: usize = rows::insert(info, a)?;
    let j: usize = rows::insert(game, g)?;
    if i != j {
        return Err(E::Msg(format!("cow clone: {class} sits at {i} in the actor table and at {j} in the game actor table")));
    }
    Ok(i)
}

pub fn events(y: &mut Byml, class: &str) -> Res<()> {
    for (from, to, entry) in [(talk_row(TEMPLATE), talk_row(class), TALK), (give_row(TEMPLATE), give_row(class), GIVE), (OLD_PUSH.to_string(), push_row(class), PUSH)] {
        let mut r: Node = row(y, &from)?;
        r.set(ROW_ID, Node::Str(to));
        r.set(FLOWCHART, Node::Str(chart(class)));
        r.set(ENTRY, Node::Str(entry.to_string()));
        put(y, r)?;
    }
    Ok(())
}

pub fn analyzed(y: &mut Byml, class: &str) -> Res<()> {
    for (from, to) in [(talk_row(TEMPLATE), talk_row(class)), (give_row(TEMPLATE), give_row(class)), (OLD_PUSH.to_string(), push_row(class))] {
        let mut r: Node = row(y, &from)?;
        r.set(ROW_ID, Node::Str(to));
        if let Some(k) = r.get_mut(KIDS).and_then(|k| k.as_arr_mut()) {
            for x in k.iter_mut() {
                if x.as_str() == Some(OLD_PUSH) {
                    *x = Node::Str(push_row(class));
                }
            }
        }
        put(y, r)?;
    }
    Ok(())
}

pub fn tags(t: &mut Table, class: &str) -> Res<()> {
    let own: Vec<String> = t.tags_of(PLAIN);
    if own.is_empty() {
        return Err(E::Msg(format!("cow clone: {PLAIN} has no tag row, the game files differ")));
    }
    if t.find(class).is_some() {
        return Err(E::Msg(format!("cow clone: the tag table already holds {class}")));
    }
    t.insert(class, &own)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::pickup_pack::rows::{ACTOR_INFO, GAME_ACTOR_INFO};
    use crate::pickup_pack::tag::TAG;
    use crate::progressive::{ANALYZED_TABLE, SETTING_TABLE};
    use crate::romfs::Romfs;
    use std::path::PathBuf as PB;

    fn root() -> Option<PB> {
        let p: PB = ootrr_game::test_romfs::path();
        if p.join("RSDB").is_dir() { Some(p) } else { None }
    }

    fn ids(y: &Byml) -> Vec<String> {
        y.root.as_arr().unwrap().iter().map(|r| id(r).to_string()).collect()
    }

    #[test]
    fn each_table_gains_the_rows_of_one_class_copied_from_its_house_sibling() {
        let Some(r) = root() else { return };
        let mut rf: Romfs = Romfs::open(&r).unwrap();
        let (mut a, mut g): (Byml, Byml) = (rf.read_byml(ACTOR_INFO).unwrap(), rf.read_byml(GAME_ACTOR_INFO).unwrap());
        let (a0, g0): (Byml, Byml) = (a.clone(), g.clone());
        actors(&mut a, &mut g, "Animal_Cow_DMT", 1000, 1010).unwrap();
        assert!(rows::sorted(&a).unwrap() && rows::sorted(&g).unwrap());
        assert_eq!(ids(&a).len(), ids(&a0).len() + 1);
        let n: Node = row(&a, "Animal_Cow_DMT").unwrap();
        let mut h: Node = row(&a0, TEMPLATE).unwrap();
        h.set(ROW_ID, Node::Str("Animal_Cow_DMT".to_string()));
        h.set(HEAP, Node::I32(472608 + 16));
        assert_eq!(n, h);
        assert_eq!(n.get("ActorName").and_then(|v| v.as_str()), Some(PLAIN));
        assert_eq!(row(&g, "Animal_Cow_DMT").unwrap().get("DefaultAffiliation"), row(&g0, TEMPLATE).unwrap().get("DefaultAffiliation"));
        assert_eq!(ids(&g).len(), ids(&g0).len() + 1);
        let mut s: Byml = rf.read_byml(SETTING_TABLE).unwrap();
        let s0: usize = ids(&s).len();
        events(&mut s, "Animal_Cow_DMT").unwrap();
        assert_eq!(ids(&s).len(), s0 + 3);
        let p: Node = row(&s, "Animal_Cow_DMT_PushToBottleMilk").unwrap();
        assert_eq!(p.get(FLOWCHART).and_then(|v| v.as_str()), Some("Work/Event/EventFlow/Animal_Cow_DMT.evfc"));
        assert_eq!(p.get(ENTRY).and_then(|v| v.as_str()), Some(PUSH));
        assert_eq!(row(&s, "Animal_Cow_DMT_D_T").unwrap().get(ENTRY).and_then(|v| v.as_str()), Some(TALK));
        assert_eq!(row(&s, "Animal_Cow_DMT_GiveMilk").unwrap().get(ENTRY).and_then(|v| v.as_str()), Some(GIVE));
        assert!(events(&mut s, "Animal_Cow_DMT").is_err());
        let mut y: Byml = rf.read_byml(ANALYZED_TABLE).unwrap();
        analyzed(&mut y, "Animal_Cow_DMT").unwrap();
        let k: Node = row(&y, "Animal_Cow_DMT_GiveMilk").unwrap();
        let kids: Vec<&str> = k.get(KIDS).unwrap().as_arr().unwrap().iter().filter_map(|x| x.as_str()).collect();
        assert!(kids.contains(&"Animal_Cow_DMT_PushToBottleMilk") && !kids.contains(&OLD_PUSH));
        let mut t: Table = Table::parse(&rf.read_zs(TAG).unwrap()).unwrap();
        tags(&mut t, "Animal_Cow_DMT").unwrap();
        assert_eq!(t.tags_of("Animal_Cow_DMT"), t.tags_of(PLAIN));
        assert!(t.sorted());
        assert!(Table::parse(&t.write().unwrap()).unwrap() == t);
    }
}
