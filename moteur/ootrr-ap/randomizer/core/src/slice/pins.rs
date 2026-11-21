use std::collections::BTreeMap as BM;
use std::path::PathBuf as PB;

use crate::json::{self, Json};

pub const UPDATE: &str = "OOTRR_UPDATE_PINS";

fn path(name: &str) -> PB {
    PB::from(env!("CARGO_MANIFEST_DIR")).join("../../data/pins").join(format!("{name}.json"))
}

pub fn verify(name: &str, got: &BM<String, String>) {
    let p: PB = path(name);
    if std::env::var_os(UPDATE).is_some() {
        let mut j: Json = Json::obj();
        for (k, v) in got {
            j.put(k, Json::from(v.as_str()));
        }
        std::fs::create_dir_all(p.parent().unwrap()).unwrap();
        std::fs::write(&p, j.pretty() + "
").unwrap();
        return;
    }
    let text: String = std::fs::read_to_string(&p).unwrap_or_else(|e| panic!("{}: {e}, run the test with {UPDATE}=1 to write it", p.display()));
    let want: Json = json::parse(&text).unwrap();
    let mut bad: Vec<String> = Vec::new();
    for (k, v) in got {
        let w: Option<&str> = want.get(k).and_then(|x| x.as_str());
        if w != Some(v.as_str()) {
            bad.push(format!("{k}: pinned {}, now {v}", w.unwrap_or("nothing")));
        }
    }
    for (k, _) in want.as_obj().unwrap_or(&[]) {
        if !got.contains_key(k) {
            bad.push(format!("{k}: pinned but no longer checked"));
        }
    }
    assert!(bad.is_empty(), "the {name} pins moved. If the change is meant, run the test again with {UPDATE}=1 and commit data/pins/{name}.json:
{}", bad.join("
"));
}
