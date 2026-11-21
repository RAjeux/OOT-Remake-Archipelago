use crate::error::{Error as E, Res};
use crate::rsizetable::{align, Rst};

pub const INNER_MARGIN: u32 = 0x400;

pub fn need(was: u32, old: usize, new: usize) -> u64 {
    was as u64 + align(new as u64).saturating_sub(align(old as u64)) + align(INNER_MARGIN as u64)
}

pub fn grow(rst: &mut Rst, path: &str, old: usize, new: usize) -> Res<u32> {
    let cur: u32 = rst.get(path).ok_or_else(|| E::Msg(format!("{path} has no size table entry, the game would size its buffer from nothing")))?;
    let n: u32 = u32::try_from(need(cur, old, new)).map_err(|_| E::Format("an inner file size does not fit in 32 bits"))?;
    rst.set_size(path, n)?;
    Ok(n)
}

pub fn enough(rst: &Rst, path: &str, was: u32, old: usize, new: usize) -> bool {
    rst.get(path).is_some_and(|now| now > was && now as u64 >= need(was, old, new))
}

#[cfg(test)]
mod tests {
    use super::*;

    const SHOP: &str = "Component/ShopParam/Npc_Kokiri_001_Shop_Child.game__component__ShopParam.bgyml";
    const PACK: &str = "Pack/Actor/Npc_Kokiri_001_Shop_Child.pack.zs";

    fn table() -> Rst {
        let mut t: Rst = Rst { version: 1, name_len: 160, crc: Vec::new(), names: Vec::new() };
        t.set_size(SHOP, 8080).unwrap();
        t.set_size(PACK, 300_000).unwrap();
        t
    }

    #[test]
    fn an_edited_file_inside_a_pack_grows_its_own_entry_and_reads_back() {
        let mut t: Rst = table();
        let n: u32 = grow(&mut t, SHOP, 1156, 1264).unwrap();
        assert_eq!(n as u64, 8080 + align(1264) - align(1156) + 0x400);
        t.grow(PACK, 287_860, 287_868, crate::staging::MARGIN).unwrap();
        let back: Rst = Rst::parse(&t.write().unwrap()).unwrap();
        assert_eq!(back.get(SHOP), Some(n));
        assert!(enough(&back, SHOP, 8080, 1156, 1264));
        assert!(!enough(&table(), SHOP, 8080, 1156, 1264));
        assert!(back.get(PACK).unwrap() > 300_000);
    }

    #[test]
    fn a_same_size_edit_still_gets_the_margin_and_a_missing_entry_is_an_error() {
        let mut t: Rst = table();
        assert_eq!(grow(&mut t, SHOP, 1156, 1150).unwrap(), 8080 + 0x400);
        assert!(grow(&mut t, "Component/ShopParam/Nobody.bgyml", 1, 2).is_err());
    }
}
