use crate::error::Res;
use crate::rules::Age;
use crate::slice::data::Data;
use crate::slice::fill::vanilla_place;
use crate::slice::logic::world_with;
use crate::spots::depth::{show, spheres};
use crate::spots::FULL;
use crate::world::{Placement, World};

pub fn table(d: &Data) -> Res<String> {
    let w: World = world_with(d, &FULL)?;
    let v: Placement = vanilla_place(&w, d)?;
    let sp: Vec<[u32; 2]> = spheres(&w, &v);
    let mut out: String = String::from("region\tdungeon\tchild\tadult\tlocations\n");
    for (i, r) in w.regions.iter().enumerate() {
        out.push_str(&format!(
            "{}\t{}\t{}\t{}\t{}\n",
            r.name,
            r.dungeon.as_deref().unwrap_or(""),
            show(sp[i][Age::Child.idx()]),
            show(sp[i][Age::Adult.idx()]),
            r.locations.len()
        ));
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_table_lists_every_region_with_its_spheres() {
        let d: Data = Data::load().unwrap();
        let t: String = table(&d).unwrap();
        let w: World = world_with(&d, &FULL).unwrap();
        assert_eq!(t.lines().count(), w.regions.len() + 1);
        assert!(t.lines().any(|l| l.starts_with("Kokiri Forest\t\t0\t")));
    }
}
