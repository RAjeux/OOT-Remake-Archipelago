use crate::ainb::{Ainb, Input, Param};
use crate::error::{Error, Res};

pub const RECEIVE: &str = "QueryInsideTheDekuFallingFloorReceiveFallMessage";
pub const SUPPORT: &str = "QueryPhysicsIsSpreadSupportActive";
pub const QUERIES: [&str; 2] = [RECEIVE, SUPPORT];
pub const SELECTOR: u16 = 7;
pub const INPUT: &str = "Input";
pub const CONST: u32 = 0x80_0000;
const BOOL: usize = 1;
const LINKS: usize = 0;
const REC: usize = 16;
const EL_PARAM: usize = 0x14;
const PTRS: [usize; 18] = [0x10, 0x20, 0x24, 0x28, 0x2c, 0x30, 0x34, 0x38, 0x3c, 0x40, 0x44, 0x48, 0x4c, 0x50, 0x5c, 0x68, 0x6c, 0x70];

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Site {
    pub sel: usize,
    pub g: usize,
    pub query: usize,
}

pub fn consumers(a: &Ainb, q: usize) -> usize {
    let by_input: usize = (0..6).map(|k| (0..).map_while(|g| a.input(k, g)).filter(|x| x.src >= 0 && x.src as usize == q).count()).sum();
    let by_plug: usize = a.params.iter().map(|p| p.group(LINKS).iter().filter(|x| x.a as usize == q).count()).sum();
    by_input + by_plug
}

pub fn sites(a: &Ainb, query: &str) -> Vec<Site> {
    let mut out: Vec<Site> = Vec::new();
    for sel in 0..a.els.len() {
        if a.el_type(sel) != SELECTOR {
            continue;
        }
        let Some(g) = a.find_in(sel, BOOL, INPUT) else {
            continue;
        };
        let Some(x) = a.input(BOOL, g) else {
            continue;
        };
        if x.src < 0 || x.src as usize >= a.els.len() {
            continue;
        }
        let q: usize = x.src as usize;
        if a.el_type(q) == 0 && a.el_name(q) == query {
            out.push(Site { sel, g, query: q });
        }
    }
    out
}

pub fn is_pinned(a: &Ainb, sel: usize) -> bool {
    let Some(g) = a.find_in(sel, BOOL, INPUT) else {
        return false;
    };
    let Some(x) = a.input(BOOL, g) else {
        return false;
    };
    x.src == -1 && x.plug == 0 && x.flags == CONST && x.val == [0, 0, 0, 0] && a.params[sel].group(LINKS).is_empty()
}

fn record(name: u32) -> Vec<u8> {
    let mut r: Vec<u8> = Vec::with_capacity(REC);
    r.extend_from_slice(&name.to_le_bytes());
    r.extend_from_slice(&(-1i16).to_le_bytes());
    r.extend_from_slice(&0i16.to_le_bytes());
    r.extend_from_slice(&CONST.to_le_bytes());
    r.extend_from_slice(&0u32.to_le_bytes());
    r
}

pub fn pin(a: &mut Ainb, s: &Site) -> Res<()> {
    let x: Input = a.input(BOOL, s.g).ok_or(Error::Format("deku bridge: selector input out of range"))?;
    let links: Vec<u32> = a.params[s.sel].group(LINKS).iter().map(|p| p.a).collect();
    if links != [s.query as u32] || a.s(a.params[s.sel].group(LINKS)[0].b) != INPUT {
        return Err(Error::Format("deku bridge: the selector does not read its query through one input plug"));
    }
    if consumers(a, s.query) != 2 {
        return Err(Error::Format("deku bridge: the trigger query feeds more than its selector"));
    }
    let o: usize = s.g * REC;
    let d: &mut [u8] = a.ins[BOOL].get_mut(o..o + REC).ok_or(Error::Format("deku bridge: selector input out of range"))?;
    d.copy_from_slice(&record(x.name));
    let p: &mut Param = &mut a.params[s.sel];
    let b: usize = p.pl[LINKS][1] as usize;
    p.plugs.remove(b);
    p.pl[LINKS][0] -= 1;
    for j in LINKS + 1..p.pl.len() {
        p.pl[j][1] -= 1;
    }
    Ok(())
}

pub fn only_sites_changed(x: &Ainb, y: &Ainb, done: &[Site]) -> bool {
    let mut m: Ainb = y.clone();
    for s in done {
        let r: std::ops::Range<usize> = s.g * REC..s.g * REC + REC;
        let (Some(old), Some(new)) = (x.ins[BOOL].get(r.clone()), m.ins[BOOL].get_mut(r)) else {
            return false;
        };
        new.copy_from_slice(old);
        let (p, q): (&Param, &Param) = (&x.params[s.sel], &y.params[s.sel]);
        if p.pe != q.pe || p.ioe != q.ioe || p.plugs.get(1..) != Some(&q.plugs[..]) || p.group(LINKS).len() != 1 {
            return false;
        }
        m.params[s.sel] = p.clone();
    }
    steady(&m) == steady(x)
}

pub fn steady(a: &Ainb) -> Ainb {
    let mut c: Ainb = a.clone();
    for o in PTRS {
        c.hdr[o..o + 4].fill(0);
    }
    for e in c.els.iter_mut() {
        e[EL_PARAM..EL_PARAM + 4].fill(0);
    }
    c
}

pub fn patch(raw: &[u8]) -> Res<Vec<u8>> {
    let before: Ainb = Ainb::parse(raw)?;
    let mut a: Ainb = before.clone();
    let mut done: Vec<Site> = Vec::new();
    for q in QUERIES {
        let v: Vec<Site> = sites(&a, q);
        let [s] = v.as_slice() else {
            return Err(Error::Msg(format!("deku bridge: expected one selector reading {q}, found {}", v.len())));
        };
        pin(&mut a, s)?;
        done.push(s.clone());
    }
    let out: Vec<u8> = a.write()?;
    let b: Ainb = Ainb::parse(&out)?;
    if steady(&b) != steady(&a) || b.write()? != out {
        return Err(Error::Format("deku bridge: the patched graph does not read back"));
    }
    if !crate::ainb::audit(&b).is_empty() {
        return Err(Error::Format("deku bridge: the patched graph fails the table audit"));
    }
    for s in &done {
        if !is_pinned(&b, s.sel) || consumers(&b, s.query) != 0 {
            return Err(Error::Format("deku bridge: a trigger selector is not pinned after the edit"));
        }
    }
    if QUERIES.iter().any(|q| !sites(&b, q).is_empty()) {
        return Err(Error::Format("deku bridge: a trigger query still feeds a selector"));
    }
    if !only_sites_changed(&before, &b, &done) {
        return Err(Error::Format("deku bridge: the edit touched more than the two trigger inputs"));
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ainb::tests::{node, synth};
    use crate::ainb::Plug;

    fn flag(v: bool) -> Vec<u8> {
        u32::from(v).to_le_bytes().to_vec()
    }

    fn link(a: &mut Ainb, sel: usize, q: usize) {
        let g: usize = a.find_in(sel, BOOL, INPUT).unwrap();
        let o: usize = g * REC;
        a.ins[BOOL][o + 4..o + 6].copy_from_slice(&(q as i16).to_le_bytes());
        a.ins[BOOL][o + 8..o + 12].copy_from_slice(&0u32.to_le_bytes());
        let nm: u32 = a.pool.add(INPUT);
        a.params[sel].add_plug(LINKS, 0, Plug { a: q as u32, b: nm, extra: vec![0; 8] }).unwrap();
    }

    fn branch(a: &mut Ainb, sel: usize, t: usize, f: usize) {
        let tn: u32 = a.pool.add("True");
        let fname: u32 = a.pool.add("False");
        a.params[sel].add_plug(2, 0, Plug { a: t as u32, b: tn, extra: Vec::new() }).unwrap();
        a.params[sel].add_plug(2, 1, Plug { a: f as u32, b: fname, extra: Vec::new() }).unwrap();
    }

    fn selector(a: &mut Ainb) -> usize {
        let s: usize = node(a, "", SELECTOR, &[(1, INPUT, flag(false))]);
        for (k, n) in [12usize, 12, 12, 12, 20, 12].into_iter().enumerate() {
            a.params[s].pe[k] = [(a.props[k].len() / n) as u32, 0];
        }
        s
    }

    fn floor() -> (Ainb, usize, usize, usize, usize) {
        let mut a: Ainb = synth();
        let recv: usize = node(&mut a, RECEIVE, 0, &[]);
        let sup: usize = node(&mut a, SUPPORT, 0, &[]);
        let none: usize = node(&mut a, "ExecuteGenericSetResultNone", 0, &[]);
        let send: usize = node(&mut a, "OneShotInsideTheDekuFallingFloorSendFallMessage", 0, &[]);
        let shake: usize = node(&mut a, "ExecuteBlackboardSetBool", 0, &[(1, "Bool", flag(true))]);
        let s2: usize = selector(&mut a);
        let s1: usize = selector(&mut a);
        link(&mut a, s2, sup);
        link(&mut a, s1, recv);
        branch(&mut a, s2, send, none);
        branch(&mut a, s1, shake, s2);
        (a, s1, s2, recv, sup)
    }

    #[test]
    fn the_synthetic_floor_finds_one_site_per_query() {
        let (a, s1, s2, recv, sup): (Ainb, usize, usize, usize, usize) = floor();
        assert_eq!(crate::ainb::audit(&a), Vec::<String>::new());
        assert_eq!(sites(&a, RECEIVE), vec![Site { sel: s1, g: a.find_in(s1, BOOL, INPUT).unwrap(), query: recv }]);
        assert_eq!(sites(&a, SUPPORT), vec![Site { sel: s2, g: a.find_in(s2, BOOL, INPUT).unwrap(), query: sup }]);
        assert_eq!(consumers(&a, recv), 2);
        assert!(!is_pinned(&a, s1));
    }

    #[test]
    fn both_selectors_are_pinned_to_a_constant_false_and_keep_their_branches() {
        let (a, s1, s2, recv, sup): (Ainb, usize, usize, usize, usize) = floor();
        let raw: Vec<u8> = a.write().unwrap();
        let out: Vec<u8> = patch(&raw).unwrap();
        assert_eq!(out.len(), raw.len() - 40);
        let b: Ainb = Ainb::parse(&out).unwrap();
        assert!(is_pinned(&b, s1) && is_pinned(&b, s2));
        assert_eq!(consumers(&b, recv), 0);
        assert_eq!(consumers(&b, sup), 0);
        for s in [s1, s2] {
            let names: Vec<&str> = b.params[s].group(2).iter().map(|p| b.s(p.b)).collect();
            assert_eq!(names, vec!["True", "False"]);
            assert_eq!(b.params[s].group(2), a.params[s].group(2));
        }
        assert_eq!(steady(&b).els, steady(&a).els);
        assert!(crate::ainb::audit(&b).is_empty());
    }

    #[test]
    fn a_second_patch_and_a_graph_without_the_trigger_are_refused() {
        let (a, ..): (Ainb, usize, usize, usize, usize) = floor();
        let out: Vec<u8> = patch(&a.write().unwrap()).unwrap();
        assert!(patch(&out).is_err());
        assert!(patch(&synth().write().unwrap()).is_err());
    }

    #[test]
    fn a_query_that_feeds_two_selectors_is_refused() {
        let (mut a, _, _, recv, _): (Ainb, usize, usize, usize, usize) = floor();
        let s3: usize = selector(&mut a);
        link(&mut a, s3, recv);
        assert!(patch(&a.write().unwrap()).is_err());
    }
}
