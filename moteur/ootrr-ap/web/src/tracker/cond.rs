use ootrr_core::murmur::murmur3_32;
use crate::tracker::peek::Peek;

pub fn eq_of(f: &str) -> Option<(u32, u32)> {
    let (n, v): (&str, &str) = f.split_once('=')?;
    let val: u32 = v.parse::<u32>().unwrap_or_else(|_| murmur3_32(v.as_bytes(), 0));
    Some((murmur3_32(n.as_bytes(), 0), val))
}

pub fn name_of(f: &str) -> &str {
    f.split_once('=').map(|(n, _)| n).unwrap_or(f)
}

pub fn holds(p: &Peek, e: &(u32, u32)) -> bool {
    p.val(e.0) == Some(e.1)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_enum_test_hashes_both_sides_and_a_number_stays_a_number() {
        assert_eq!(eq_of("Step_GatheringTokenGold=Complete"), Some((murmur3_32(b"Step_GatheringTokenGold", 0), 0x4c0a63f4)));
        assert_eq!(eq_of("Get_MagicBeans=10"), Some((murmur3_32(b"Get_MagicBeans", 0), 10)));
        assert_eq!(eq_of("Plain"), None);
        assert_eq!(name_of("A=B"), "A");
        assert_eq!(name_of("A"), "A");
    }
}
