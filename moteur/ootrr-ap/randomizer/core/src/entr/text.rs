use std::fmt::Write as W;

use crate::entr::layout::Layout;
use crate::entr::pools::{Conn, DUNGEONS};

pub const NOTE: &str = "Dungeon entrances are shuffled (coupled, both ways). The eleven dungeon doors lead to other dungeons and each dungeon's way out leads back to the door you came in by. Ganon's Castle, boss rooms, blue warps, warp songs and the Spirit Temple hands stay as they are. Experimental and untested in the game.";

pub fn spoiler(l: &Layout) -> String {
    let mut out: String = String::new();
    let _ = writeln!(out, "Entrances (dungeons, coupled), {} of {} moved", l.moved(), DUNGEONS.len());
    for (spot, d) in l.at.iter().enumerate() {
        let c: &Conn = &DUNGEONS[spot];
        let mark: &str = if spot == *d { " (vanilla)" } else { "" };
        let _ = writeln!(out, "  {} entrance in {} leads to {}{mark}", c.name, c.area, DUNGEONS[*d].name);
    }
    out
}

pub fn report(l: &Layout) -> String {
    let mut out: String = String::new();
    let _ = writeln!(out, "{NOTE}");
    for (spot, d) in l.at.iter().enumerate() {
        if spot != *d {
            let _ = writeln!(out, "  The {} entrance in {} leads to {}.", DUNGEONS[spot].name, DUNGEONS[spot].area, DUNGEONS[*d].name);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lines_name_the_door_and_the_dungeon() {
        let mut l: Layout = Layout::vanilla();
        l.at.swap(0, 1);
        let t: String = spoiler(&l);
        assert!(t.starts_with("Entrances (dungeons, coupled), 2 of 11 moved"));
        assert!(t.contains("  Deku Tree entrance in Kokiri Forest leads to Dodongos Cavern\n"));
        assert!(t.contains("  Fire Temple entrance in Death Mountain Crater leads to Fire Temple (vanilla)\n"));
        let r: String = report(&l);
        assert!(r.contains("The Dodongos Cavern entrance in Death Mountain Trail leads to Deku Tree."));
        assert!(!r.contains("Fire Temple entrance"));
    }
}
