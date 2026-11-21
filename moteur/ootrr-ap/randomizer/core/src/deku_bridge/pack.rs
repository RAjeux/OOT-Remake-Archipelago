use crate::error::{Error, Res};
use crate::sarc::{self, Entry};

pub fn patch(raw: &[u8], member: &str, f: impl FnOnce(&[u8]) -> Res<Vec<u8>>) -> Res<Vec<u8>> {
    let es: Vec<Entry> = sarc::parse(raw)?;
    if raw.get(6..8) != Some([0xFF, 0xFE].as_slice()) {
        return Err(Error::Format("deku bridge: the pack is not a little endian archive"));
    }
    let old: &Entry = sarc::get(&es, member).ok_or_else(|| Error::Msg(format!("deku bridge: the pack has no {member}")))?;
    let new: Vec<u8> = f(&old.data)?;
    if new.len() > old.data.len() {
        return Err(Error::Msg(format!("deku bridge: {member} would grow, which needs its own size table entry")));
    }
    let mut ed: Vec<Entry> = es.clone();
    sarc::set(&mut ed, member, new.clone());
    let out: Vec<u8> = sarc::write(&ed)?;
    let back: Vec<Entry> = sarc::parse(&out)?;
    if back != ed || sarc::write(&back)? != out {
        return Err(Error::Format("deku bridge: the patched pack does not read back"));
    }
    if changed(&es, &back) != [member.to_string()] {
        return Err(Error::Format("deku bridge: the patched pack changed more than its graph"));
    }
    Ok(out)
}

pub fn changed(a: &[Entry], b: &[Entry]) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    for x in a {
        match sarc::get(b, &x.name) {
            Some(y) if y.data == x.data => {}
            _ => out.push(x.name.clone()),
        }
    }
    out.extend(b.iter().filter(|y| sarc::get(a, &y.name).is_none()).map(|y| y.name.clone()));
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pack() -> Vec<u8> {
        let es: Vec<Entry> = vec![
            Entry { name: "AI/X.root.ainb".to_string(), data: vec![1, 2, 3, 4, 5, 6, 7, 8] },
            Entry { name: "Actor/X.engine__actor__ActorParam.bgyml".to_string(), data: vec![9; 12] },
        ];
        sarc::write(&es).unwrap()
    }

    #[test]
    fn only_the_member_changes_and_the_rest_is_kept_in_order() {
        let raw: Vec<u8> = pack();
        let out: Vec<u8> = patch(&raw, "AI/X.root.ainb", |b| Ok(b[..4].to_vec())).unwrap();
        let a: Vec<Entry> = sarc::parse(&raw).unwrap();
        let b: Vec<Entry> = sarc::parse(&out).unwrap();
        assert_eq!(changed(&a, &b), vec!["AI/X.root.ainb".to_string()]);
        assert_eq!(b[0].data, vec![1, 2, 3, 4]);
        assert_eq!(b[1], a[1]);
        assert_eq!(b.iter().map(|e| e.name.clone()).collect::<Vec<String>>(), a.iter().map(|e| e.name.clone()).collect::<Vec<String>>());
    }

    #[test]
    fn growth_a_missing_member_and_a_no_op_are_refused() {
        let raw: Vec<u8> = pack();
        assert!(patch(&raw, "AI/X.root.ainb", |b| Ok([b, b].concat())).is_err());
        assert!(patch(&raw, "AI/Y.root.ainb", |b| Ok(b.to_vec())).is_err());
        assert!(patch(&raw, "AI/X.root.ainb", |b| Ok(b.to_vec())).is_err());
        assert!(patch(&raw, "AI/X.root.ainb", |_| Err(Error::Format("no"))).is_err());
    }

    #[test]
    fn a_big_endian_archive_is_refused() {
        let es: Vec<Entry> = vec![Entry { name: "AI/X.root.ainb".to_string(), data: vec![1, 2, 3, 4] }];
        let raw: Vec<u8> = sarc::write_be(&es).unwrap();
        assert!(patch(&raw, "AI/X.root.ainb", |b| Ok(b[..2].to_vec())).is_err());
    }
}
