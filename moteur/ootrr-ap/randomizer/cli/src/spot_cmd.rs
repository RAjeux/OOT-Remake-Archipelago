use std::fs;
use std::path::Path as P;

use ootrr_core::error::{Error, Res};
use ootrr_core::settings::seed::SeedFile;
use ootrr_core::slice::data::Data;
use ootrr_core::spots::audit::{render, rows, Row};
use ootrr_core::spots::regions::table;

pub fn audit(a: &[String]) -> Res<()> {
    let p: &str = a.first().map(|s| s.as_str()).ok_or(Error::Format("missing seed file"))?;
    let all: bool = a.iter().skip(1).any(|s| s == "--all");
    let d: Data = Data::load()?;
    let seed: SeedFile = SeedFile::read(P::new(p))?;
    let (list, missing): (Vec<Row>, usize) = rows(&d, &seed, all)?;
    print!("{}", render(&list, missing));
    Ok(())
}

pub fn regions(a: &[String]) -> Res<()> {
    let out: &str = a.first().map(|s| s.as_str()).ok_or(Error::Format("missing out file"))?;
    let d: Data = Data::load()?;
    let t: String = table(&d)?;
    fs::write(out, &t)?;
    println!("{} regions written to {out}", t.lines().count().saturating_sub(1));
    Ok(())
}
