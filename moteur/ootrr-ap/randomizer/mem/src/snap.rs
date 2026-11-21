#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Snap {
    pub rows: Vec<(u32, u32)>,
    pub keys: Vec<u64>,
}

impl Snap {
    pub fn new(mut rows: Vec<(u32, u32)>, mut keys: Vec<u64>) -> Snap {
        rows.sort_unstable_by_key(|r| r.0);
        rows.dedup_by_key(|r| r.0);
        keys.sort_unstable();
        keys.dedup();
        Snap { rows, keys }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rows_and_keys_come_out_sorted_and_unique() {
        let s: Snap = Snap::new(vec![(9, 1), (7, 1), (3, 0), (9, 1)], vec![5, 2, 5]);
        assert!(s.rows.windows(2).all(|w| w[0].0 < w[1].0));
        assert_eq!(s.rows.len(), 3);
        assert_eq!(s.keys, vec![2, 5]);
    }
}
