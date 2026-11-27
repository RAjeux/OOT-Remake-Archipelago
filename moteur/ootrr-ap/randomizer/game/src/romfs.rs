use std::fs;
use std::path::{Path as P, PathBuf as PB};

use crate::byml::Byml;
use crate::error::{Error, Res};
use crate::modpack::rel;
use crate::sarc;
use crate::zs::Zs;

type FileIndex = Vec<(String, Vec<String>)>;

fn parse_index(raw: &str) -> Res<FileIndex> {
    let data = crate::json::parse(raw)?;
    if data.get("schema").and_then(crate::json::Json::as_i64) != Some(1) {
        return Err(Error::Format("unsupported private WASI file index"));
    }
    let files = data.get("files").and_then(crate::json::Json::as_obj)
        .ok_or(Error::Format("private WASI file index has no roots"))?;
    let mut out = Vec::new();
    for (name, files) in files {
        if !matches!(name.as_str(), "game" | "mod") { return Err(Error::BadPath(name.clone())); }
        let files = files.as_arr().ok_or(Error::Format("private file index is not an array"))?;
        if files.len() > 500_000 { return Err(Error::Format("private file index is too large")); }
        let mut seen = std::collections::BTreeSet::new();
        for file in files {
            let file = file.as_str().ok_or(Error::Format("indexed file name is not text"))?;
            if file.len() > 2048 { return Err(Error::BadPath(file.to_string())); }
            rel(file)?;
            if !seen.insert(file.to_string()) { return Err(Error::Format("duplicate private indexed file")); }
        }
        out.push((name.clone(), seen.into_iter().collect()));
    }
    Ok(out)
}

fn indexed(root: &P, sub: &str) -> Res<Option<Vec<String>>> {
    if !cfg!(target_os = "wasi") { return Ok(None); }
    static INDEX: std::sync::OnceLock<FileIndex> = std::sync::OnceLock::new();
    if INDEX.get().is_none() {
        match fs::read_to_string("/apmeta/files.json") {
            Ok(raw) => { let _ = INDEX.set(parse_index(&raw)?); }
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(e) => return Err(e.into()),
        }
    }
    let root = root.to_string_lossy().replace('\\', "/");
    let (key, base) = if root == "/game" { ("game", "") }
        else if let Some(base) = root.strip_prefix("/game/") { ("game", base) }
        else if root == "/mod" || root == "/load/Archipelago/romfs" { ("mod", "") }
        else if let Some(base) = root.strip_prefix("/mod/") { ("mod", base) }
        else { return Ok(None); };
    if !sub.is_empty() { rel(sub)?; }
    let joined = [base, sub].into_iter().filter(|s| !s.is_empty()).collect::<Vec<_>>().join("/");
    let prefix = if joined.is_empty() { String::new() } else { format!("{joined}/") };
    let base_prefix = if base.is_empty() { String::new() } else { format!("{base}/") };
    let index = INDEX.get().ok_or(Error::Format("private file index was not initialized"))?;
    let files = index.iter().find(|(name, _)| name == key)
        .ok_or(Error::Format("private file index has no requested root"))?;
    Ok(Some(files.1.iter().filter(|file| file.starts_with(&prefix))
        .map(|file| file.strip_prefix(&base_prefix).unwrap_or(file).to_string()).collect()))
}

/// List native files or use the caller's bounded private inventory on WASI.
/// This supplies directory enumeration on Windows without broadening preopens.
pub fn list_files(root: &P, sub: &str) -> Res<Vec<String>> {
    if let Some(files) = indexed(root, sub)? { return Ok(files); }
    let top = if sub.is_empty() { root.to_path_buf() } else { root.join(rel(sub)?) };
    let mut stack = vec![top];
    let mut out = Vec::new();
    while let Some(directory) = stack.pop() {
        for entry in fs::read_dir(directory)? {
            let entry = entry?;
            let path = entry.path();
            if entry.file_type()?.is_dir() || path.is_dir() { stack.push(path); }
            else {
                let relative = path.strip_prefix(root).map_err(|_| Error::BadPath(path.display().to_string()))?;
                out.push(relative.to_string_lossy().replace('\\', "/"));
            }
        }
    }
    out.sort();
    Ok(out)
}

fn missing(e: std::io::Error, r: &str) -> Error {
    if e.kind() == std::io::ErrorKind::NotFound {
        Error::Msg(format!(
            "the game folder has no {r}. The mod build needs the game extracted with the 1.1.1 update installed, so this folder is probably an older version or an incomplete extraction"
        ))
    } else {
        Error::from(e)
    }
}

pub struct Romfs {
    pub root: PB,
    pub zs: Zs,
}

impl Romfs {
    pub fn open(root: &P) -> Res<Romfs> {
        let mut zs: Zs = Zs::new();
        let raw: Vec<u8> = fs::read(root.join("Pack").join("ZsDic.pack.zs"))?;
        let pack: Vec<u8> = zs.decompress(&raw)?;
        for e in sarc::parse(&pack)? {
            if e.name.ends_with(".zsdic") {
                zs.add_dict(&e.data)?;
            }
        }
        Ok(Romfs { root: root.to_path_buf(), zs })
    }

    pub fn read(&self, r: &str) -> Res<Vec<u8>> {
        fs::read(self.root.join(rel(r)?)).map_err(|e| missing(e, r))
    }

    pub fn read_zs(&mut self, r: &str) -> Res<Vec<u8>> {
        let b: Vec<u8> = self.read(r)?;
        self.zs.decompress(&b)
    }

    pub fn read_byml(&mut self, r: &str) -> Res<Byml> {
        let b: Vec<u8> = if r.ends_with(".zs") { self.read_zs(r)? } else { self.read(r)? };
        Byml::parse(&b)
    }

    pub fn list(&self, sub: &str) -> Res<Vec<String>> {
        list_files(&self.root, sub)
    }
}

#[cfg(test)]
mod index_tests {
    use super::*;

    #[test]
    fn private_index_accepts_only_bounded_relative_game_names() {
        let good = r#"{"schema":1,"files":{"game":["Banc/Map.bcett.byml.zs"],"mod":[]}}"#;
        assert_eq!(parse_index(good).unwrap()[0].1, vec!["Banc/Map.bcett.byml.zs"]);
        for bad in [good.replace("Banc/Map.bcett.byml.zs", "../private"),
                    good.replace("Banc/Map.bcett.byml.zs", "/private"),
                    good.replace("\"game\"", "\"other\""),
                    good.replace("\"schema\":1", "\"schema\":2")] {
            assert!(parse_index(&bad).is_err());
        }
    }
}
