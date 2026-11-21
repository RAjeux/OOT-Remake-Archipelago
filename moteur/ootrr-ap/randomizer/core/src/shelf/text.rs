use crate::error::{Error as E, Res};
use crate::msbt::{self, Msbt};
use crate::sarc::{self, Entry};
use std::collections::BTreeMap;

pub const POUCH_MSG: &str = "ActorMsg/PouchContent.msbt";
pub const ARCHIVE_TAIL: &str = ".Product.110.sarc.zs";

pub fn caption(id: &str) -> String {
    format!("{id}_ShopCaption")
}

pub fn add(m: &mut Msbt, id: &str) -> Res<bool> {
    if m.find(&format!("{id}_Name")).is_none() {
        return Err(E::Msg(format!("{id} has no _Name text, it cannot be named on a shelf")));
    }
    let cap: String = caption(id);
    if m.find(&cap).is_some() {
        return Ok(false);
    }
    let src: Vec<u8> = ["_Caption", "_GetCaption"]
        .iter()
        .find_map(|sfx| m.raw(&format!("{id}{sfx}")).map(|b| b.to_vec()))
        .ok_or_else(|| E::Msg(format!("{id} has no caption to copy for the shelf")))?;
    m.add_raw(&cap, src)?;
    Ok(true)
}

pub fn archive(raw: &[u8], ids: &[String]) -> Res<(Vec<u8>, usize)> {
    archive_with_aliases(raw, ids, &BTreeMap::new())
}

/// Keep the native item wording on local AP display-only shelves. Copy the
/// authored MSBT bytes, rather than translating or rebuilding control codes.
pub fn archive_with_aliases(raw: &[u8], ids: &[String], aliases: &BTreeMap<String, String>) -> Res<(Vec<u8>, usize)> {
    let mut es: Vec<Entry> = sarc::parse(raw)?;
    let b: Vec<u8> = sarc::get(&es, POUCH_MSG).ok_or(E::Format("a message archive has no PouchContent.msbt"))?.data.clone();
    let mut m: Msbt = msbt::parse(&b)?;
    if m.write()? != b {
        return Err(E::Format("PouchContent.msbt does not round trip"));
    }
    let mut n: usize = 0;
    for (id, source) in aliases {
        let name = m.raw(&format!("{source}_Name")).ok_or_else(||
            E::Msg(format!("{source} has no native shop name")))?.to_vec();
        let caption = ["_ShopCaption", "_Caption", "_GetCaption"].iter()
            .find_map(|suffix| m.raw(&format!("{source}{suffix}"))).ok_or_else(||
                E::Msg(format!("{source} has no native shop description")))?.to_vec();
        let mut entries = vec![(format!("{id}_Name"), name)];
        for suffix in ["_Caption", "_GetCaption", "_GetMessage", "_ShopCaption"] {
            entries.push((format!("{id}{suffix}"), m.raw(&format!("{source}{suffix}"))
                .map_or_else(|| caption.clone(), <[u8]>::to_vec)));
        }
        for (label, bytes) in entries {
            if m.raw(&label) == Some(bytes.as_slice()) { continue; }
            if m.find(&label).is_some() { m.set_raw(&label, bytes)?; }
            else { m.add_raw(&label, bytes)?; }
            n += 1;
        }
    }
    for id in ids {
        if add(&mut m, id)? {
            n += 1;
        }
    }
    if n == 0 {
        return Ok((raw.to_vec(), 0));
    }
    let w: Vec<u8> = m.write()?;
    msbt::parse(&w)?;
    sarc::set(&mut es, POUCH_MSG, w);
    Ok((sarc::write(&es)?, n))
}

pub fn has(raw: &[u8], id: &str) -> Res<bool> {
    let es: Vec<Entry> = sarc::parse(raw)?;
    let m: Msbt = msbt::parse(&sarc::get(&es, POUCH_MSG).ok_or(E::Format("a message archive has no PouchContent.msbt"))?.data)?;
    Ok(m.raw(&caption(id)).is_some() && m.raw(&format!("{id}_Name")).is_some())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn captions_are_named_after_the_pouch_identity() {
        assert_eq!(caption("Item_Hookshot"), "Item_Hookshot_ShopCaption");
        assert_eq!(caption("Weapon_Sword_Kokiri"), "Weapon_Sword_Kokiri_ShopCaption");
    }
}
