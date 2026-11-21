use crate::byml::{Byml, Node};
use crate::cow_clone::data::{PLAIN, TEMPLATE};
use crate::cow_clone::flow::{give_row, talk_row};
use crate::error::{Error as E, Res};
use crate::sarc::Entry;

pub const ACTOR: (&str, &str) = ("Actor/", ".engine__actor__ActorParam.bgyml");
pub const TABLE: (&str, &str) = ("GameParameter/GameParameterTable/", ".engine__actor__GameParameterTable.bgyml");
pub const OCARINA: (&str, &str) = ("GameParameter/ReplaceEventParam/", ".game__ocarina__ReplaceEventParam.bgyml");
pub const TALK: (&str, &str) = ("GameParameter/EventRequestParam/", ".game__event__EventRequestParam.bgyml");
pub const SCHEDULE: (&str, &str) = ("Component/AIScheduleParam/", ".game__component__AIScheduleParam.bgyml");
pub const SETTING: (&str, &str) = ("Work/Event/EventSetting/", ".engine__event__EventSettingParam.gyml");
pub const OWN: [(&str, &str); 4] = [ACTOR, TABLE, OCARINA, TALK];

pub fn path(p: (&str, &str), name: &str) -> String {
    format!("{}{name}{}", p.0, p.1)
}

pub fn pack_of(name: &str) -> String {
    format!("Pack/Actor/{name}.pack.zs")
}

fn refer(p: (&str, &str), name: &str) -> Node {
    Node::Str(format!("?{}", path(p, name)))
}

fn event(row: &str) -> Node {
    Node::Str(path(SETTING, row))
}

fn get<'a>(es: &'a [Entry], p: &str) -> Res<&'a Entry> {
    es.iter().find(|e| e.name == p).ok_or_else(|| E::Msg(format!("cow clone: the {TEMPLATE} pack has no {p}, the game files differ")))
}

fn text<'a>(n: &'a Node, k: &str) -> Res<&'a str> {
    n.get(k).and_then(|v| v.as_str()).ok_or_else(|| E::Msg(format!("cow clone: {k} is missing, the game files differ")))
}

fn expect(n: &Node, k: &str, want: &str) -> Res<()> {
    let have: &str = text(n, k)?;
    if have != want {
        return Err(E::Msg(format!("cow clone: {k} holds {have} and not {want}, the game files differ")));
    }
    Ok(())
}

fn comps(y: &mut Byml) -> Res<&mut Node> {
    y.root.get_mut("Components").ok_or(E::Format("cow clone: a parameter file has no Components"))
}

fn actor(raw: &[u8], class: &str) -> Res<Vec<u8>> {
    let mut y: Byml = Byml::parse(raw)?;
    expect(&y.root, "$parent", &format!("Work/Actor/{PLAIN}.engine__actor__ActorParam.gyml"))?;
    let c: &mut Node = comps(&mut y)?;
    expect(c, "AIScheduleRef", &format!("?{}", path(SCHEDULE, TEMPLATE)))?;
    expect(c, "GameParameterTableRef", &format!("?{}", path(TABLE, TEMPLATE)))?;
    c.set("AIScheduleRef", refer(SCHEDULE, class));
    c.set("GameParameterTableRef", refer(TABLE, class));
    y.write()
}

fn table(raw: &[u8], class: &str) -> Res<Vec<u8>> {
    let mut y: Byml = Byml::parse(raw)?;
    let c: &mut Node = comps(&mut y)?;
    expect(c, "EventRequestParam", &format!("?{}", path(TALK, TEMPLATE)))?;
    expect(c, "ReplaceEventParam", &format!("?{}", path(OCARINA, TEMPLATE)))?;
    c.set("EventRequestParam", refer(TALK, class));
    c.set("ReplaceEventParam", refer(OCARINA, class));
    y.write()
}

fn named(raw: &[u8], old: &str, new: &str) -> Res<Vec<u8>> {
    let mut y: Byml = Byml::parse(raw)?;
    expect(&y.root, "EventName", &path(SETTING, old))?;
    y.root.set("EventName", event(new));
    y.write()
}

pub fn schedule(raw: &[u8], class: &str) -> Res<Vec<u8>> {
    let mut y: Byml = Byml::parse(raw)?;
    let list: &mut Vec<Node> = y
        .root
        .get_mut("DefaultSchedule")
        .and_then(|d| d.get_mut("EventEntry"))
        .and_then(|e| e.as_arr_mut())
        .ok_or(E::Format("cow clone: the house schedule has no event list"))?;
    if list.len() != 1 {
        return Err(E::Format("cow clone: the house schedule does not hold exactly one event, the game files differ"));
    }
    expect(&list[0], "EventName", &path(SETTING, &talk_row(TEMPLATE)))?;
    list[0].set("EventName", event(&talk_row(class)));
    y.write()
}

pub fn build(house: &[Entry], class: &str) -> Res<Vec<Entry>> {
    let own: Vec<String> = OWN.iter().map(|p| path(*p, TEMPLATE)).collect();
    let mut out: Vec<Entry> = house.iter().filter(|e| !own.contains(&e.name)).cloned().collect();
    if out.iter().any(|e| e.name.contains(TEMPLATE)) || out.len() + OWN.len() != house.len() {
        return Err(E::Msg(format!("cow clone: the {TEMPLATE} pack holds other files of its own, the game files differ")));
    }
    out.push(Entry { name: path(ACTOR, class), data: actor(&get(house, &own[0])?.data, class)? });
    out.push(Entry { name: path(TABLE, class), data: table(&get(house, &own[1])?.data, class)? });
    out.push(Entry { name: path(OCARINA, class), data: named(&get(house, &own[2])?.data, &give_row(TEMPLATE), &give_row(class))? });
    out.push(Entry { name: path(TALK, class), data: named(&get(house, &own[3])?.data, &talk_row(TEMPLATE), &talk_row(class))? });
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::romfs::Romfs;
    use crate::sarc;
    use std::path::PathBuf as PB;

    fn root() -> Option<PB> {
        let p: PB = ootrr_game::test_romfs::path();
        if p.join("Pack/Actor").is_dir() { Some(p) } else { None }
    }

    #[test]
    fn a_clone_pack_is_the_house_pack_with_four_files_of_its_own() {
        let Some(r) = root() else { return };
        let mut rf: Romfs = Romfs::open(&r).unwrap();
        let house: Vec<Entry> = sarc::parse(&rf.read_zs(&pack_of(TEMPLATE)).unwrap()).unwrap();
        let es: Vec<Entry> = build(&house, "Animal_Cow_DMT").unwrap();
        assert_eq!(es.len(), house.len());
        let back: Vec<Entry> = sarc::parse(&sarc::write(&es).unwrap()).unwrap();
        assert_eq!(back.len(), es.len());
        for e in &house {
            if e.name.contains(TEMPLATE) {
                assert!(sarc::get(&back, &e.name).is_none(), "{}", e.name);
            } else {
                assert_eq!(sarc::get(&back, &e.name).map(|x| &x.data), Some(&e.data), "{}", e.name);
            }
        }
        let y = |p: (&str, &str)| Byml::parse(&sarc::get(&back, &path(p, "Animal_Cow_DMT")).unwrap().data).unwrap();
        let a: Byml = y(ACTOR);
        assert_eq!(a.root.get("Components").and_then(|c| c.get("AIScheduleRef")).and_then(|v| v.as_str()), Some("?Component/AIScheduleParam/Animal_Cow_DMT.game__component__AIScheduleParam.bgyml"));
        assert_eq!(a.root.get("$parent").and_then(|v| v.as_str()), Some("Work/Actor/Animal_Cow.engine__actor__ActorParam.gyml"));
        let t: Byml = y(TABLE);
        assert_eq!(t.root.get("Components").and_then(|c| c.get("NaviAttentionParam")).and_then(|v| v.as_str()), Some("?GameParameter/NaviAttentionParam/Animal_Cow.game__navi__NaviAttentionParam.bgyml"));
        assert_eq!(y(OCARINA).root.get("EventName").and_then(|v| v.as_str()), Some("Work/Event/EventSetting/Animal_Cow_DMT_GiveMilk.engine__event__EventSettingParam.gyml"));
        assert_eq!(y(TALK).root.get("EventName").and_then(|v| v.as_str()), Some("Work/Event/EventSetting/Animal_Cow_DMT_D_T.engine__event__EventSettingParam.gyml"));
        for p in OWN {
            let txt: String = format!("{:?}", y(p));
            assert!(!txt.contains(TEMPLATE), "{txt}");
        }
        let s: Vec<u8> = schedule(&rf.read(&path(SCHEDULE, TEMPLATE)).unwrap(), "Animal_Cow_DMT").unwrap();
        let txt: String = format!("{:?}", Byml::parse(&s).unwrap());
        assert!(txt.contains("Animal_Cow_DMT_D_T") && !txt.contains(TEMPLATE) && txt.contains("OnPlayerTalkBase"), "{txt}");
        let mut bad: Vec<Entry> = house.clone();
        bad.push(Entry { name: path(SCHEDULE, TEMPLATE), data: Vec::new() });
        assert!(build(&bad, "Animal_Cow_DMT").is_err());
    }
}
