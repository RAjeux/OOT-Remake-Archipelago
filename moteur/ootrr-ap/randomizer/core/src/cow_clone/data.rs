use crate::error::{Error as E, Res};
use crate::json::{self, Json};

pub const JSON: &str = include_str!("../../../../data/cow_clones.json");
pub const PLAIN: &str = "Animal_Cow";
pub const TEMPLATE: &str = "Animal_Cow_LinkHouse";
pub const PREFIX: &str = "Animal_Cow_";
pub const MAX_NAME: usize = 20;
pub const EXT: &str = ".bfevfl";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Spot {
    pub file: String,
    pub hash: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Cow {
    pub location: String,
    pub class: String,
    pub pilot: bool,
    pub spots: Vec<Spot>,
}

impl Cow {
    pub fn flow_file(&self) -> String {
        format!("{}{EXT}", self.class)
    }
}

fn text(j: &Json, k: &str) -> Res<String> {
    j.get(k).and_then(|v| v.as_str()).map(|s| s.to_string()).ok_or_else(|| E::Msg(format!("cow clones json: missing text field {k}")))
}

fn arr<'a>(j: &'a Json, k: &str) -> Res<&'a [Json]> {
    j.get(k).and_then(|v| v.as_arr()).ok_or_else(|| E::Msg(format!("cow clones json: missing list {k}")))
}

pub fn named(class: &str) -> bool {
    class.starts_with(PREFIX) && class.len() <= MAX_NAME && class.len() > PREFIX.len() && class.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') && class != TEMPLATE
}

fn spot(j: &Json) -> Res<Spot> {
    let file: String = text(j, "file")?;
    if !file.starts_with("Banc/") || !file.ends_with(".bcett.byml.zs") {
        return Err(E::Msg(format!("cow clones json: {file} is not a scene file")));
    }
    let h: String = text(j, "hash")?;
    let hash: u64 = h.parse().map_err(|_| E::Msg(format!("cow clones json: {h} is not an actor hash")))?;
    Ok(Spot { file, hash })
}

pub fn parse(t: &str) -> Res<Vec<Cow>> {
    let j: Json = json::parse(t)?;
    if j.get("format").and_then(|v| v.as_i64()) != Some(1) {
        return Err(E::Format("cow clones json: unsupported format"));
    }
    let mut out: Vec<Cow> = Vec::new();
    for c in arr(&j, "clones")? {
        let class: String = text(c, "class")?;
        if !named(&class) {
            return Err(E::Msg(format!("cow clones json: {class} must start with {PREFIX} and keep to {MAX_NAME} letters, digits and underscores")));
        }
        let mut spots: Vec<Spot> = Vec::new();
        for s in arr(c, "spots")? {
            spots.push(spot(s)?);
        }
        if spots.is_empty() {
            return Err(E::Msg(format!("cow clones json: {class} has no scene placement")));
        }
        let cow: Cow = Cow { location: text(c, "location")?, class, pilot: c.get("pilot").and_then(|v| v.as_bool()).unwrap_or(false), spots };
        if out.iter().any(|o| o.class == cow.class || o.location == cow.location || o.spots.iter().any(|s| cow.spots.contains(s))) {
            return Err(E::Msg(format!("cow clones json: {} is listed twice", cow.class)));
        }
        out.push(cow);
    }
    Ok(out)
}

pub fn load() -> Res<Vec<Cow>> {
    parse(JSON)
}

pub fn all() -> Vec<Cow> {
    load().unwrap_or_default()
}

pub fn by_location(name: &str) -> Option<Cow> {
    all().into_iter().find(|c| c.location == name)
}

pub fn of_file(file: &str) -> Option<Cow> {
    let class: &str = file.strip_suffix(EXT)?;
    all().into_iter().find(|c| c.class == class)
}

pub fn is_location(name: &str) -> bool {
    by_location(name).is_some()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_table_holds_the_five_plain_cows_and_one_pilot() {
        let cs: Vec<Cow> = load().unwrap();
        assert_eq!(cs.len(), 5);
        assert_eq!(cs.iter().filter(|c| c.pilot).map(|c| c.location.as_str()).collect::<Vec<&str>>(), vec!["DMT Cow Grotto Cow"]);
        assert_eq!(cs.iter().map(|c| c.spots.len()).sum::<usize>(), 11);
        for c in &cs {
            assert!(named(&c.class) && c.class.len() <= TEMPLATE.len(), "{}", c.class);
            assert_eq!(of_file(&c.flow_file()), Some(c.clone()));
        }
        assert!(of_file("Animal_Cow.bfevfl").is_none() && of_file("Animal_Cow_LinkHouse.bfevfl").is_none());
        assert!(is_location("LLR Stables Right Cow") && !is_location("GV Cow"));
    }

    #[test]
    fn bad_tables_are_refused() {
        let one = |class: &str, file: &str, hash: &str| format!("{{\"format\":1,\"clones\":[{{\"location\":\"L\",\"class\":\"{class}\",\"spots\":[{{\"file\":\"{file}\",\"hash\":\"{hash}\"}}]}}]}}");
        let f: &str = "Banc/X/X_Child_Dynamic.bcett.byml.zs";
        assert!(parse(&one("Animal_Cow_Ok", f, "1")).is_ok());
        assert!(parse(&one("Animal_Cow_ThisNameIsFarTooLong", f, "1")).is_err());
        assert!(parse(&one("Cow_Other", f, "1")).is_err());
        assert!(parse(&one("Animal_Cow_LinkHouse", f, "1")).is_err());
        assert!(parse(&one("Animal_Cow_Ok", "Pack/X.pack.zs", "1")).is_err());
        assert!(parse(&one("Animal_Cow_Ok", f, "x")).is_err());
        assert!(parse("{\"format\":2,\"clones\":[]}").is_err());
    }
}
