use crate::error::{Error as E, Res};
use crate::msbt::{self, Msbt};
use crate::sarc::{self, Entry};

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
    let mut es: Vec<Entry> = sarc::parse(raw)?;
    let b: Vec<u8> = sarc::get(&es, POUCH_MSG).ok_or(E::Format("a message archive has no PouchContent.msbt"))?.data.clone();
    let mut m: Msbt = msbt::parse(&b)?;
    if m.write()? != b {
        return Err(E::Format("PouchContent.msbt does not round trip"));
    }
    let mut n: usize = 0;
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
