use std::collections::BTreeMap as BM;

use crate::entrances::age_of;
use crate::error::{Error as E, Res};
use crate::json::{self, Json};

pub const CATALOG: &str = include_str!("../../../../data/entrances.json");

pub const DEST_KEYS: [&str; 10] = [
    "NextBancParamNameAdult",
    "NextBancParamNameChild",
    "NextStartPosName",
    "NextEventName",
    "InitEventName",
    "InitEventFlag",
    "AddEventName",
    "AddEventFlag",
    "IsAlternativeGameDataBool",
    "IsChangableAirPos",
];

#[derive(Debug, Clone, PartialEq)]
pub struct Door {
    pub hash: u64,
    pub file: String,
    pub map: String,
    pub name: String,
    pub age: String,
    pub ages: Vec<String>,
    pub adult: String,
    pub child: String,
    pub start: String,
    pub ok: [bool; 2],
}

impl Door {
    pub fn ok_for(&self, age: &str) -> bool {
        match age {
            "adult" => self.ok[0],
            "child" => self.ok[1],
            _ => false,
        }
    }

    pub fn alt(&self) -> bool {
        self.map.ends_with("_Alternative")
    }
}

#[derive(Debug, Default)]
pub struct Cat {
    pub doors: BM<u64, Door>,
}

fn s(j: &Json, k: &str) -> String {
    j.get(k).and_then(|v| v.as_str()).unwrap_or("").to_string()
}

fn fits(param: &str, age: &str) -> bool {
    let a: &str = age_of(param);
    a == "both" || a == age
}

pub fn parse(text: &str) -> Res<Cat> {
    let j: Json = json::parse(text)?;
    let list: &[Json] = j.get("entrances").and_then(|v| v.as_arr()).ok_or(E::Format("entrance catalog has no entrances list"))?;
    let mut out: Cat = Cat::default();
    for e in list {
        let hash: u64 = s(e, "hash").parse().map_err(|_| E::Format("entrance catalog hash is not a number"))?;
        let ok = |age: &str, param: &str| -> bool {
            e.get("start_ok").and_then(|o| o.get(age)).and_then(|v| v.as_str()) == Some("ok") && fits(param, age)
        };
        let adult: String = s(e, "adult");
        let child: String = s(e, "child");
        let ages: Vec<String> = e
            .get("ages")
            .and_then(|v| v.as_arr())
            .map(|a| a.iter().filter_map(|x| x.as_str()).map(|x| x.to_string()).collect())
            .unwrap_or_default();
        let d: Door = Door {
            hash,
            file: s(e, "file"),
            map: s(e, "map"),
            name: s(e, "name"),
            age: s(e, "age"),
            ages,
            ok: [ok("adult", &adult), ok("child", &child)],
            adult,
            child,
            start: s(e, "start"),
        };
        if out.doors.insert(hash, d).is_some() {
            return Err(E::Msg(format!("entrance catalog lists {hash} twice")));
        }
    }
    Ok(out)
}

pub fn load() -> Res<Cat> {
    parse(CATALOG)
}

impl Cat {
    pub fn door(&self, h: u64) -> Res<&Door> {
        self.doors.get(&h).ok_or_else(|| E::Msg(format!("entrance {h} is not in data/entrances.json")))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::entr::pools::DUNGEONS;

    #[test]
    fn the_shipped_catalog_has_every_dungeon_actor_with_the_right_destination() {
        let c: Cat = load().unwrap();
        assert_eq!(c.doors.len(), 167);
        for d in DUNGEONS {
            for h in d.doors {
                let x: &Door = c.door(*h).unwrap();
                assert_eq!(x.adult, d.map, "{}", d.name);
                assert_eq!(x.child, d.map, "{}", d.name);
                assert!(x.ok[0] && x.ok[1], "{} door {h}", d.name);
            }
            let b: &Door = c.door(d.back).unwrap();
            assert_eq!(b.map, d.map, "{}", d.name);
            assert_eq!(b.age, "both");
        }
    }

    #[test]
    fn the_known_broken_returns_are_flagged() {
        let c: Cat = load().unwrap();
        let jabu: &Door = c.door(17995796037457417799).unwrap();
        assert!(!jabu.ok_for("adult") && jabu.ok_for("child"));
        let ice: &Door = c.door(4069798734802445712).unwrap();
        assert!(ice.ok_for("adult") && !ice.ok_for("child"));
        let gtg: &Door = c.door(9849011308940982015).unwrap();
        assert!(gtg.ok_for("adult") && !gtg.ok_for("child"));
        let deku: &Door = c.door(7202597688446125475).unwrap();
        assert!(deku.ok_for("adult") && deku.ok_for("child"));
    }
}
