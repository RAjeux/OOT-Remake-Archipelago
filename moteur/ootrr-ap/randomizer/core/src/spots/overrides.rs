use crate::error::{Error as E, Res};
use crate::json::{self, Json};
use crate::logic_json::Json as Lj;

pub const JSON: &str = include_str!("../../../../data/logic/spot_overrides.json");

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Over {
    pub name: String,
    pub region: Option<String>,
    pub rule: Option<String>,
    pub reason: String,
}

fn opt(j: &Json, k: &str) -> Option<String> {
    j.get(k).and_then(|v| v.as_str()).map(|s| s.trim().to_string()).filter(|s| !s.is_empty())
}

pub fn parse(t: &str) -> Res<Vec<Over>> {
    let j: Json = json::parse(t)?;
    if j.get("format").and_then(|v| v.as_i64()) != Some(1) {
        return Err(E::Format("spot overrides: unsupported format"));
    }
    let rows: &[Json] = j.get("overrides").and_then(|v| v.as_arr()).ok_or(E::Format("spot overrides: no overrides list"))?;
    let mut out: Vec<Over> = Vec::with_capacity(rows.len());
    for r in rows {
        let name: String = opt(r, "name").ok_or(E::Format("spot overrides: a row has no name"))?;
        let o: Over = Over { region: opt(r, "region"), rule: opt(r, "rule"), reason: opt(r, "reason").unwrap_or_default(), name };
        if o.reason.is_empty() {
            return Err(E::Msg(format!("spot overrides: {} gives no reason", o.name)));
        }
        if o.region.is_none() && o.rule.is_none() {
            return Err(E::Msg(format!("spot overrides: {} changes neither the region nor the rule", o.name)));
        }
        if out.iter().any(|x: &Over| x.name == o.name) {
            return Err(E::Msg(format!("spot overrides: {} is listed twice", o.name)));
        }
        out.push(o);
    }
    Ok(out)
}

pub fn all() -> Res<Vec<Over>> {
    parse(JSON)
}

fn region_name(fields: &[(String, Lj)]) -> Option<&str> {
    fields.iter().find(|(k, _)| k == "region_name").and_then(|(_, v)| v.as_str())
}

fn take(files: &mut [Lj], name: &str) -> Option<(String, Lj)> {
    for f in files.iter_mut() {
        let Lj::Arr(regions) = f else {
            continue;
        };
        for reg in regions.iter_mut() {
            let Lj::Obj(fields) = reg else {
                continue;
            };
            let from: String = region_name(fields).unwrap_or("").to_string();
            let Some((_, Lj::Obj(list))) = fields.iter_mut().find(|(k, _)| k == "locations") else {
                continue;
            };
            if let Some(i) = list.iter().position(|(k, _)| k == name) {
                let (_, rule): (String, Lj) = list.remove(i);
                return Some((from, rule));
            }
        }
    }
    None
}

fn put(files: &mut [Lj], region: &str, name: &str, rule: Lj) -> Res<()> {
    let mut hit: usize = 0;
    let mut row: Option<(String, Lj)> = Some((name.to_string(), rule));
    for f in files.iter_mut() {
        let Lj::Arr(regions) = f else {
            continue;
        };
        for reg in regions.iter_mut() {
            let Lj::Obj(fields) = reg else {
                continue;
            };
            if region_name(fields) != Some(region) {
                continue;
            }
            hit += 1;
            let Some(r) = row.take() else {
                continue;
            };
            match fields.iter_mut().find(|(k, _)| k == "locations") {
                Some((_, Lj::Obj(list))) => list.push(r),
                Some(_) => return Err(E::Msg(format!("spot overrides: the locations of {region} are not an object"))),
                None => fields.push(("locations".to_string(), Lj::Obj(vec![r]))),
            }
        }
    }
    match hit {
        1 => Ok(()),
        n => Err(E::Msg(format!("spot overrides: {name} moves to {region}, which names {n} regions instead of one"))),
    }
}

pub fn apply_with(files: &mut [Lj], list: &[Over]) -> Res<usize> {
    let mut n: usize = 0;
    for o in list {
        let Some((from, old)) = take(files, &o.name) else {
            continue;
        };
        let rule: Lj = o.rule.clone().map(Lj::Str).unwrap_or(old);
        let to: &str = o.region.as_deref().unwrap_or(&from);
        put(files, to, &o.name, rule)?;
        n += 1;
    }
    Ok(n)
}

pub fn apply(files: &mut [Lj]) -> Res<usize> {
    apply_with(files, &all()?)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::logic_json::parse as lp;

    fn files() -> Vec<Lj> {
        vec![lp("[{\"region_name\":\"R\",\"locations\":{\"A\":\"True\",\"B\":\"is_child\"}},{\"region_name\":\"S\"}]").unwrap()]
    }

    #[test]
    fn a_rule_override_keeps_the_region_and_a_region_override_keeps_the_rule() {
        let mut f: Vec<Lj> = files();
        let list: Vec<Over> = vec![
            Over { name: "A".to_string(), region: None, rule: Some("Bow".to_string()), reason: "tester".to_string() },
            Over { name: "B".to_string(), region: Some("S".to_string()), rule: None, reason: "tester".to_string() },
            Over { name: "Gone".to_string(), region: Some("S".to_string()), rule: None, reason: "not in this world".to_string() },
        ];
        assert_eq!(apply_with(&mut f, &list).unwrap(), 2);
        let want: Lj = lp("[{\"region_name\":\"R\",\"locations\":{\"A\":\"Bow\"}},{\"region_name\":\"S\",\"locations\":{\"B\":\"is_child\"}}]").unwrap();
        assert_eq!(f[0], want);
        let bad: Vec<Over> = vec![Over { name: "A".to_string(), region: Some("Nowhere".to_string()), rule: None, reason: "x".to_string() }];
        assert!(apply_with(&mut files(), &bad).is_err());
    }

    #[test]
    fn rows_need_a_reason_and_a_change() {
        assert!(parse("{\"format\":1,\"overrides\":[{\"name\":\"A\",\"rule\":\"True\"}]}").is_err());
        assert!(parse("{\"format\":1,\"overrides\":[{\"name\":\"A\",\"reason\":\"x\"}]}").is_err());
        assert!(parse("{\"format\":1,\"overrides\":[{\"name\":\"A\",\"rule\":\"True\",\"reason\":\"x\"},{\"name\":\"A\",\"rule\":\"Bow\",\"reason\":\"y\"}]}").is_err());
        assert_eq!(parse("{\"format\":1,\"overrides\":[{\"name\":\"A\",\"region\":\"S\",\"reason\":\"x\"}]}").unwrap().len(), 1);
        assert!(parse("{\"format\":2,\"overrides\":[]}").is_err());
    }

    #[test]
    fn every_shipped_override_names_a_location_of_the_full_world() {
        let d: crate::slice::data::Data = crate::slice::data::Data::load().unwrap();
        let w: crate::world::World = crate::slice::logic::world_with(&d, &crate::spots::FULL).unwrap();
        for o in all().unwrap() {
            let l: crate::world::LocId = w.loc(&o.name).unwrap_or_else(|| panic!("{} is not a location", o.name));
            if let Some(r) = &o.region {
                assert_eq!(&w.regions[w.locs[l].region].name, r, "{}", o.name);
            }
        }
    }
}
