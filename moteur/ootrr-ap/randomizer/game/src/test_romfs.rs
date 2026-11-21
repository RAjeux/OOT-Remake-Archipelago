use std::path::PathBuf as PB;

pub const VAR: &str = "OOTRR_ROMFS";

const KNOWN: [&str; 2] = ["C:/o/nup dump/updates/131072/romfs", "D:/Oot/romfs"];

pub fn path() -> PB {
    if let Some(p) = std::env::var_os(VAR) {
        return PB::from(p);
    }
    KNOWN.iter().map(PB::from).find(|p| p.join("Pack").join("ZsDic.pack.zs").is_file()).unwrap_or_else(|| PB::from(KNOWN[0]))
}
