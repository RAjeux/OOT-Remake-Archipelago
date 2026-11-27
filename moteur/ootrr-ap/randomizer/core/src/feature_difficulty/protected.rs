//! Network source identities are runtime context, never randomizer settings.
//! Keep the exact AP actors intact while adding or replacing ordinary enemies.
use std::collections::{BTreeMap, HashSet};

use crate::byml::{Byml, Node};
use crate::error::{Error, Res};
use crate::json::Json;
use crate::placement::hash_of;
use crate::qol::Have;
use crate::romfs::Romfs;

pub type Sources = BTreeMap<String, HashSet<u64>>;
pub type Snapshot = BTreeMap<String, BTreeMap<u64, Node>>;

pub fn read(features: &Json, required: bool) -> Res<Sources> {
    let Some(value) = features.get("protected_sources") else {
        return if required {
            Err(Error::Format("difficulty features: missing AP source protection context"))
        } else { Ok(Sources::new()) };
    };
    let values = value.as_obj().ok_or(Error::Format("difficulty features: AP source context must be an object"))?;
    let mut out = Sources::new();
    for (file, hashes) in values {
        if !file.starts_with("Banc/") || !file.ends_with(".bcett.byml.zs")
            || file.split('/').any(|p| p.is_empty() || p == "." || p == "..") || file.contains('\\') {
            return Err(Error::Msg(format!("difficulty features: invalid AP source file {file}")));
        }
        let hashes = hashes.as_arr().ok_or(Error::Format("difficulty features: AP source hashes must be an array"))?;
        let mut selected = HashSet::new();
        for hash in hashes {
            let hash = hash.as_str().and_then(|s| s.parse::<u64>().ok()).filter(|h| *h != 0)
                .ok_or(Error::Format("difficulty features: AP actor hash must be a decimal uint64 string"))?;
            selected.insert(hash);
        }
        if !selected.is_empty() { out.insert(file.clone(), selected); }
    }
    Ok(out)
}

fn actors(rf: &mut Romfs, have: Have, file: &str) -> Res<Vec<Node>> {
    let raw = match have(file) { Some(z) => rf.zs.decompress(&z)?, None => rf.read_zs(file)? };
    let parsed = Byml::parse(&raw)?;
    parsed.root.get("Actors").and_then(Node::as_arr).map(|a| a.to_vec())
        .ok_or_else(|| Error::Msg(format!("AP source protection: no actor list in {file}")))
}

pub fn snapshot(rf: &mut Romfs, have: Have, sources: &Sources) -> Res<Snapshot> {
    let mut out = Snapshot::new();
    for (file, hashes) in sources {
        let mut selected = BTreeMap::new();
        for actor in actors(rf, have, file)? {
            if let Some(hash) = hash_of(&actor).filter(|h| hashes.contains(h)) {
                if selected.insert(hash, actor).is_some() {
                    return Err(Error::Msg(format!("AP source protection: duplicate actor {hash} in {file}")));
                }
            }
        }
        for hash in hashes {
            if !selected.contains_key(hash) {
                return Err(Error::Msg(format!("AP source protection: actor {hash} is missing in {file}")));
            }
        }
        out.insert(file.clone(), selected);
    }
    Ok(out)
}

pub fn unchanged(rf: &mut Romfs, have: Have, before: &Snapshot) -> Res<()> {
    let ids = before.iter().map(|(file, actors)| (file.clone(), actors.keys().copied().collect())).collect();
    let after = snapshot(rf, have, &ids)?;
    for (file, actors) in before {
        for (hash, actor) in actors {
            if after.get(file).and_then(|a| a.get(hash)) != Some(actor) {
                return Err(Error::Msg(format!("Difficulty changes would modify AP source actor {hash} in {file}")));
            }
        }
    }
    Ok(())
}

#[cfg(test)]
pub fn network_catalogue() -> Json {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../../../client/ootrr_triforce/network_sources.json");
    let catalogue = crate::json::parse(&std::fs::read_to_string(&path).unwrap()).unwrap();
    let mut sources: BTreeMap<String, std::collections::BTreeSet<String>> = BTreeMap::new();
    for (_, source) in catalogue.get("sources").unwrap().as_obj().unwrap() {
        for variant in source.get("variants").unwrap().as_arr().unwrap() {
            let file = variant.get("file").unwrap().as_str().unwrap();
            if !file.starts_with("Banc/") || !file.ends_with(".bcett.byml.zs") { continue; }
            let hash = variant.get("actor").unwrap().as_str().unwrap();
            sources.entry(file.to_string()).or_default().insert(hash.to_string());
        }
    }
    Json::Obj(sources.into_iter().map(|(file, ids)|
        (file, Json::Arr(ids.into_iter().map(Json::Str).collect()))).collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn requires_explicit_context_for_actor_substitution_and_lossless_ids() {
        assert!(read(&Json::obj(), true).is_err());
        assert!(read(&Json::obj(), false).unwrap().is_empty());
        let file = "Banc/Test/Test_Child_Static.bcett.byml.zs";
        let request = Json::obj().with("protected_sources", Json::obj().with(file,
            Json::Arr(vec![u64::MAX.to_string().into(), "42".into(), "42".into()])));
        assert_eq!(read(&request, true).unwrap()[file].len(), 2);
        for invalid in [Json::Int(42), "0".into(), "-1".into(), "18446744073709551616".into()] {
            let request = Json::obj().with("protected_sources", Json::obj().with(file, Json::Arr(vec![invalid])));
            assert!(read(&request, true).is_err());
        }
        for invalid in ["../outside.bcett.byml.zs", "Banc/../outside.bcett.byml.zs", "Banc/Test\\outside.bcett.byml.zs"] {
            let request = Json::obj().with("protected_sources", Json::obj().with(invalid, Json::Arr(vec!["42".into()])));
            assert!(read(&request, true).is_err());
        }
    }
}
