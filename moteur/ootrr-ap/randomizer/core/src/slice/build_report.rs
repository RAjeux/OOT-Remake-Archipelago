use std::collections::BTreeMap as BM;
use std::fmt::Write as W;
use std::path::Path as P;

use crate::slice::banc_edit::Edited;
use crate::slice::chest_targets::Target;
use crate::slice::edit::{BuildCounts, ChestLine, LISTED};


fn area(file: &str) -> String {
    file.split('/').nth(1).unwrap_or("").to_string()
}

pub(crate) fn lines(ts: &[Target], edits: &[Edited]) -> Vec<ChestLine> {
    let mut by: BM<String, ChestLine> = BM::new();
    for e in edits {
        for (i, f) in &e.hits {
            let t: &Target = &ts[*i];
            let c: &mut ChestLine = by.entry(t.name.clone()).or_insert_with(|| ChestLine {
                name: t.name.clone(),
                area: area(&e.file),
                pos: f.pos.clone(),
                old_item: t.old_item.clone(),
                new_item: t.new_item.clone(),
                old_actor: t.old_actor.clone(),
                new_actor: t.new_actor.clone(),
                copies: 0,
            });
            c.copies += 1;
        }
    }
    let mut v: Vec<ChestLine> = by.into_values().collect();
    v.sort_by(|a, b| (&a.area, &a.name).cmp(&(&b.area, &b.name)));
    v
}

pub(crate) fn coords(p: &[f32]) -> String {
    match p {
        [x, y, z] => format!("({x:.1}, {y:.1}, {z:.1})"),
        _ => "(unknown)".to_string(),
    }
}

pub(crate) fn describe(c: &BuildCounts, root: &P, chests: &[ChestLine], notes: &[String]) -> String {
    let mut out: String = String::new();
    let _ = writeln!(out, "Mod folder: {}", root.display());
    let _ = writeln!(
        out,
        "{} chests in the seed, {} changed, {} unchanged. {} candidate chests stay vanilla.",
        c.placed, c.changed, c.unchanged, c.left_vanilla
    );
    let _ = writeln!(out, "{} files written, {} needed a resource size table update.", c.files, c.grown);
    if !chests.is_empty() {
        let _ = writeln!(out, "Check these in game ({} of {} changed chests):", chests.len().min(LISTED), chests.len());
        for ch in chests.iter().take(LISTED) {
            let _ = writeln!(
                out,
                "  {} | area {} | at {} | vanilla {} ({}) | now {} ({})",
                ch.name,
                ch.area,
                coords(&ch.pos),
                ch.old_item,
                ch.old_actor,
                ch.new_item,
                ch.new_actor
            );
        }
    }
    for n in notes {
        let _ = writeln!(out, "{n}");
    }
    out
}

pub(crate) fn coop_word(seed: &str) -> String {
    let s: String = seed
        .chars()
        .filter(|c| c.is_ascii_alphanumeric() || *c == '_' || *c == '-')
        .take(63)
        .collect();
    if s.is_empty() { "seed".to_string() } else { s }
}
