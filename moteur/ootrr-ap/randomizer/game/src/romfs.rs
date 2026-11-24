use std::fs;
use std::path::{Path as P, PathBuf as PB};

use crate::byml::Byml;
use crate::error::{Error, Res};
use crate::modpack::rel;
use crate::sarc;
use crate::zs::Zs;

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
    /// Explicit immutable listing for Windows WASI hosts without fd_readdir.
    pub members: Option<Vec<String>>,
    /// Immutable package access supplied by the container layer, when present.
    pub reader: Option<Box<dyn Fn(&str) -> Res<Vec<u8>> + Send + Sync>>,
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
        Ok(Romfs { root: root.to_path_buf(), zs, members: None, reader: None })
    }

    pub fn with_reader(root: &P, reader: Box<dyn Fn(&str) -> Res<Vec<u8>> + Send + Sync>) -> Res<Romfs> {
        let mut zs = Zs::new();
        let raw = reader("Pack/ZsDic.pack.zs")?;
        let pack = zs.decompress(&raw)?;
        for entry in sarc::parse(&pack)? {
            if entry.name.ends_with(".zsdic") { zs.add_dict(&entry.data)?; }
        }
        Ok(Romfs { root: root.to_path_buf(), zs, members: None, reader: Some(reader) })
    }

    pub fn read(&self, r: &str) -> Res<Vec<u8>> {
        rel(r)?;
        if let Some(reader) = &self.reader { return reader(r); }
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

    pub fn is_file(&self, relative: &str) -> bool {
        if rel(relative).is_err() { return false; }
        if let Some(members) = &self.members {
            return members.binary_search_by(|path| path.as_str().cmp(relative)).is_ok();
        }
        self.root.join(relative).is_file()
    }

    pub fn is_dir(&self, relative: &str) -> bool {
        if rel(relative).is_err() { return false; }
        if let Some(members) = &self.members {
            let prefix = format!("{}/", relative.trim_end_matches('/'));
            let index = members.partition_point(|path| path < &prefix);
            return members.get(index).is_some_and(|path| path.starts_with(&prefix));
        }
        self.root.join(relative).is_dir()
    }

    pub fn list(&self, sub: &str) -> Res<Vec<String>> {
        rel(sub)?;
        if let Some(members) = &self.members {
            let prefix = format!("{}/", sub.trim_end_matches('/'));
            return Ok(members.iter().filter(|path| path.starts_with(&prefix)).cloned().collect());
        }
        let top: PB = self.root.join(rel(sub)?);
        let mut stack: Vec<PB> = vec![top];
        let mut out: Vec<String> = Vec::new();
        while let Some(d) = stack.pop() {
            for e in fs::read_dir(&d)? {
                let e: fs::DirEntry = e?;
                let p: PB = e.path();
                if e.file_type()?.is_dir() || p.is_dir() {
                    stack.push(p);
                } else {
                    let r: &P = p
                        .strip_prefix(&self.root)
                        .map_err(|_| Error::BadPath(p.display().to_string()))?;
                    out.push(r.to_string_lossy().replace('\\', "/"));
                }
            }
        }
        out.sort();
        Ok(out)
    }
}
