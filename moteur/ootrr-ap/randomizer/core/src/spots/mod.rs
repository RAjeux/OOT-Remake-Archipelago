pub mod audit;
pub mod depth;
pub mod free;
pub mod overrides;
pub mod regions;

use crate::error::Res;
use crate::logic_json::Json as Lj;
use crate::pot_slice::{remake, rocks};
use crate::pot_slice::rocks::Spot;

pub const FULL: [(&str, &str); 3] = [(rocks::KEY, rocks::ON), (remake::KEY, remake::ON), (free::KEY, free::ON)];

pub fn wanted(over: &[(&str, &str)]) -> Res<Vec<Spot>> {
    let mut out: Vec<Spot> = Vec::new();
    if rocks::wanted(over) {
        out.extend(rocks::spots()?);
    }
    if remake::wanted(over) {
        out.extend(remake::spots()?);
    }
    if free::wanted(over) {
        out.extend(free::spots()?);
    }
    Ok(out)
}

pub fn inject(files: &mut [Lj], over: &[(&str, &str)]) -> Res<usize> {
    let sp: Vec<Spot> = wanted(over)?;
    let n: usize = rocks::apply_with(files, &sp)?;
    overrides::apply(files)?;
    Ok(n)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::slice::data::Data;
    use crate::slice::logic::{world, world_with};
    use crate::world::World;

    #[test]
    fn the_full_world_holds_every_spot_once_and_the_default_world_holds_none() {
        let d: Data = Data::load().unwrap();
        let off: World = world(&d).unwrap();
        let on: World = world_with(&d, &FULL).unwrap();
        let sp: Vec<Spot> = wanted(&FULL).unwrap();
        assert_eq!(on.real.len(), off.real.len() + sp.len());
        assert!(sp.iter().all(|s| off.loc(&s.name).is_none() && on.loc(&s.name).is_some()));
        assert!(wanted(&[]).unwrap().is_empty());
    }
}
