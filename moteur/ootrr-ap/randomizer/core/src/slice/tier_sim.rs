#[cfg(test)]
mod tests {
    use std::collections::BTreeSet as BS;
    use std::path::PathBuf as PB;

    use crate::bfevfl::Flow;
    use crate::error::Res;
    use crate::flow_sim::db::Db;
    use crate::flow_sim::load::{Disk, Src};
    use crate::flow_sim::run::{End, Env, Fin, Mach, Opts, Sim};
    use crate::flow_sim::state::State;
    use crate::progressive::{entry_name, owners, tiers, wrap, Grant, FAMILIES};
    use crate::flow_sim::state::V;
    use crate::settings::seed::SeedFile;
    use crate::slice::data::Data;
    use crate::slice::flow_wrap::guards;
    use std::collections::BTreeMap as BM;
    use crate::romfs::Romfs;
    use crate::tier_chain::{of, resolve};

    const CHESTS: [&str; 2] = ["Dm_SY_TreasureboxSmall", "Dm_SY_Treasurebox"];

    struct Wrapped {
        disk: Disk,
    }

    impl Src for Wrapped {
        fn flow(&mut self, name: &str) -> Res<Option<Flow>> {
            let f: Option<Flow> = self.disk.flow(name)?;
            match f {
                Some(mut x) if CHESTS.contains(&name) => {
                    for (fam, _) in FAMILIES {
                        wrap(&mut x, fam)?;
                    }
                    Ok(Some(x))
                }
                x => Ok(x),
            }
        }

        fn event(&mut self, name: &str) -> Res<Option<(String, String)>> {
            self.disk.event(name)
        }

        fn cuts(&mut self, name: &str) -> Vec<String> {
            self.disk.cuts(name)
        }
    }

    fn root() -> Option<PB> {
        let p: PB = ootrr_game::test_romfs::path();
        p.join("Pack").join("ZsDic.pack.zs").is_file().then_some(p)
    }

    fn sim(p: &PB) -> Sim {
        let mut rf: Romfs = Romfs::open(p).unwrap();
        let db: Db = Db::load(&mut rf).unwrap();
        let src: Wrapped = Wrapped { disk: Disk::new(Romfs::open(p).unwrap(), None, Vec::new()) };
        Sim::new(db, Box::new(src), Opts::default())
    }

    fn gives(s: &mut Sim, flow: &str, fam: &str, st: State) -> (BS<String>, Vec<String>) {
        let t: &[&str] = tiers(fam).unwrap();
        let m: Mach = s.start(flow, &entry_name(fam), st, Env::new()).unwrap();
        let fins: Vec<Fin> = s.explore(m);
        let mut got: BS<String> = BS::new();
        let mut ends: Vec<String> = Vec::new();
        for f in &fins {
            if f.end != End::Done {
                ends.push(format!("{:?}", f.end));
            }
            for k in f.m.gr.keys() {
                if t.contains(&k.as_str()) {
                    got.insert(k.clone());
                }
            }
        }
        (got, ends)
    }

    #[test]
    #[ignore]
    fn the_real_chest_flows_follow_the_chain_for_every_owned_combination() {
        let Some(p) = root() else {
            eprintln!("skipped: no romfs, set OOTRR_ROMFS");
            return;
        };
        let mut s: Sim = sim(&p);
        let mut bad: Vec<String> = Vec::new();
        let mut runs: usize = 0;
        for flow in CHESTS {
            for (fam, _) in FAMILIES {
                let t: &[&str] = tiers(fam).unwrap();
                let o: &[&str] = owners(fam).unwrap();
                let n: usize = t.len();
                for mask in 0..1usize << n {
                    let owned: Vec<bool> = (0..n).map(|i| mask >> i & 1 == 1).collect();
                    let mut st: State = State::new();
                    s.settle(&mut st);
                    for (i, x) in o.iter().enumerate() {
                        if owned[i] {
                            s.own(&mut st, x, 1);
                        }
                    }
                    let want: usize = resolve(&of(fam, n), &owned).unwrap();
                    let (got, ends): (BS<String>, Vec<String>) = gives(&mut s, flow, fam, st);
                    runs += 1;
                    let line: String = format!("{flow}\t{fam}\t{owned:?}\twant {}\tgot {got:?}\tends {ends:?}", t[want]);
                    println!("SIM\t{line}");
                    if got.len() != 1 || !got.contains(t[want]) {
                        bad.push(line);
                    }
                }
            }
        }
        println!("RUNS {runs} BAD {}", bad.len());
        for b in &bad {
            println!("DIFF\t{b}");
        }
        for (k, v) in &s.assumed {
            println!("NOTE\t{k} x{v}");
        }
        for u in &s.unknown {
            println!("UNKNOWN\t{u}");
        }
        assert!(bad.is_empty());
    }

    #[test]
    #[ignore]
    fn three_chests_in_a_row_hand_out_the_tiers_in_order_when_grants_credit_the_owner() {
        let Some(p) = root() else {
            eprintln!("skipped: no romfs, set OOTRR_ROMFS");
            return;
        };
        let mut s: Sim = sim(&p);
        for (fam, _) in FAMILIES {
            let t: &[&str] = tiers(fam).unwrap();
            let o: &[&str] = owners(fam).unwrap();
            let mut st: State = State::new();
            s.settle(&mut st);
            let mut seq: Vec<String> = Vec::new();
            for _ in 0..t.len() + 1 {
                let (got, _): (BS<String>, Vec<String>) = gives(&mut s, CHESTS[0], fam, st.clone());
                let Some(g) = got.iter().next().cloned() else {
                    seq.push("nothing".to_string());
                    break;
                };
                let i: usize = t.iter().position(|x| *x == g).unwrap();
                s.own(&mut st, o[i], 1);
                seq.push(g);
            }
            println!("SEQ\t{fam}\t{}", seq.join(" then "));
            assert_eq!(seq[..t.len()].iter().map(|x| x.as_str()).collect::<Vec<&str>>(), t.to_vec(), "{fam}");
        }
    }

    struct Guarded {
        disk: Disk,
        grants: Vec<Grant>,
    }

    impl Src for Guarded {
        fn flow(&mut self, name: &str) -> Res<Option<Flow>> {
            let f: Option<Flow> = self.disk.flow(name)?;
            match f {
                Some(mut x) => {
                    let file: String = format!("{name}.bfevfl");
                    for g in self.grants.iter().filter(|g| g.file == file) {
                        g.apply(&mut x)?;
                    }
                    Ok(Some(x))
                }
                None => Ok(None),
            }
        }

        fn event(&mut self, name: &str) -> Res<Option<(String, String)>> {
            self.disk.event(name)
        }

        fn cuts(&mut self, name: &str) -> Vec<String> {
            self.disk.cuts(name)
        }
    }

    fn prize_sim(p: &PB, grants: Vec<Grant>) -> Sim {
        let mut rf: Romfs = Romfs::open(p).unwrap();
        let db: Db = Db::load(&mut rf).unwrap();
        let src: Guarded = Guarded { disk: Disk::new(Romfs::open(p).unwrap(), None, Vec::new()), grants };
        Sim::new(db, Box::new(src), Opts::default())
    }

    #[derive(Clone, Copy, PartialEq, Eq, Debug)]
    enum Credit {
        Both,
        FlagOnly,
        PouchOnly,
    }

    fn prize_gives(s: &mut Sim, flow: &str, entry: &str, fam: &str, owned: &[bool], flags: &[(&str, bool)], credit: Credit) -> (BS<String>, Vec<String>) {
        let t: &[&str] = tiers(fam).unwrap();
        let o: &[&str] = owners(fam).unwrap();
        let mut st: State = State::new();
        s.settle(&mut st);
        for (i, x) in o.iter().enumerate() {
            if owned[i] {
                s.own(&mut st, x, 1);
            }
        }
        if owned[0] {
            let flag: u32 = s.db.reg(&format!("IsGet.{}", o[0]));
            let stock: u32 = s.db.reg(&format!("PouchData.{}.StockNum", o[0]));
            match credit {
                Credit::Both => {}
                Credit::FlagOnly => {
                    st.v.insert(stock, V::I(0));
                }
                Credit::PouchOnly => {
                    st.v.insert(flag, V::B(false));
                }
            }
        }
        for (name, v) in flags {
            let h: u32 = s.db.reg(name);
            st.v.insert(h, V::B(*v));
        }
        let m: Mach = s.start(flow, entry, st, Env::new()).unwrap();
        let fins: Vec<Fin> = s.explore(m);
        let mut got: BS<String> = BS::new();
        let mut ends: Vec<String> = Vec::new();
        for f in &fins {
            if f.end != End::Done {
                ends.push(format!("{:?}", f.end));
            }
            for k in f.m.gr.keys() {
                if t.contains(&k.as_str()) {
                    got.insert(k.clone());
                }
            }
        }
        (got, ends)
    }

    #[test]
    #[ignore]
    fn the_guarded_vanilla_prizes_never_hand_out_an_upgrade_before_its_base_on_the_real_flows() {
        let Some(p) = root() else {
            eprintln!("skipped: no romfs, set OOTRR_ROMFS");
            return;
        };
        let d: Data = Data::load().unwrap();
        let seed: SeedFile = SeedFile::new("t", &crate::settings::Settings::default(), &d.scan.game, BM::new()).unwrap();
        let grants: Vec<Grant> = guards(&d, &seed);
        assert_eq!(grants.len(), 5);
        let mut plain: Sim = prize_sim(&p, Vec::new());
        let mut guarded: Sim = prize_sim(&p, grants);
        let cases: [(&str, &str, &str, Vec<(&str, bool)>); 3] = [
            ("MiniGame_HitTarget", "Child_Reward", "Slingshot", vec![("MiniGame_HitTarget_HrlCity_Get_BulletBag", false)]),
            ("MiniGame_BombchuBowling", "MiniGame_BombchuBowling_GetPrise", "BombBag", vec![("MiniGame_BombchuBowling_ClearFirstTime", true), ("MiniGame_BombchuBowling_ClearSecondTime", false)]),
            ("Dm_FairyFountain_Wisdom", "C15-01", "Magic", Vec::new()),
        ];
        let mut bad: Vec<String> = Vec::new();
        let mut runs: usize = 0;
        for (flow, entry, fam, flags) in &cases {
            let t: &[&str] = tiers(fam).unwrap();
            let n: usize = t.len();
            for mask in 0..1usize << n {
                let owned: Vec<bool> = (0..n).map(|i| mask >> i & 1 == 1).collect();
                let lawful: bool = (1..n).all(|i| !owned[i] || owned[i - 1]);
                let credits: &[Credit] = if owned[0] { &[Credit::Both, Credit::FlagOnly, Credit::PouchOnly] } else { &[Credit::Both] };
                for credit in credits {
                    let (vanilla, _): (BS<String>, Vec<String>) = prize_gives(&mut plain, flow, entry, fam, &owned, flags, Credit::Both);
                    let (got, ends): (BS<String>, Vec<String>) = prize_gives(&mut guarded, flow, entry, fam, &owned, flags, *credit);
                    runs += 1;
                    let line: String = format!("{flow}	{fam}	{owned:?}	{credit:?}	vanilla {vanilla:?}	guarded {got:?}	ends {ends:?}");
                    println!("PRIZE	{line}");
                    let ok: bool = if !owned[0] {
                        got.len() == 1 && got.contains(t[0])
                    } else {
                        got == vanilla && !got.is_empty()
                    };
                    if !ok && (owned[0] || lawful || mask == 0) {
                        bad.push(line);
                    }
                }
            }
        }
        println!("RUNS {runs} BAD {}", bad.len());
        for b in &bad {
            println!("DIFF	{b}");
        }
        for u in &guarded.unknown {
            println!("UNKNOWN	{u}");
        }
        assert!(bad.is_empty());
    }
}
