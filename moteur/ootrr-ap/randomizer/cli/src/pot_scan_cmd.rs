use std::fs;
use std::path::Path as P;

use ootrr_core::error::{Error, Res};
use ootrr_core::pot_slice::scan::{scan, summary, to_json, PotScan};

pub fn run(a: &[String]) -> Res<()> {
    run_with(a, scan)
}

pub fn run_rocks(a: &[String]) -> Res<()> {
    run_with(a, ootrr_core::pot_slice::rocks::scan)
}

pub fn run_remake(a: &[String]) -> Res<()> {
    run_with(a, ootrr_core::pot_slice::remake::scan)
}

fn run_with(a: &[String], f: fn(&P) -> Res<PotScan>) -> Res<()> {
    let root: &str = a.first().map(|s| s.as_str()).ok_or(Error::Format("missing romfs_root"))?;
    let out: &str = a.get(1).map(|s| s.as_str()).ok_or(Error::Format("missing out file"))?;
    let s: PotScan = f(P::new(root))?;
    let mut t: String = to_json(&s).pretty();
    t.push('\n');
    fs::write(out, t)?;
    print!("{}", summary(&s));
    Ok(())
}
