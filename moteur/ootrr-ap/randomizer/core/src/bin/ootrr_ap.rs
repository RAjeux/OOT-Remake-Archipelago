use std::{env, fs, io::{self, Read}, path::Path};
use ootrr_core::{byml::{Byml, Node}, json::{self, Json}, modpack, placement, romfs::Romfs,
    rsizetable::{self, Rst}, settings::Settings, slice::{self, GenOpts}, zs};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
fn field<'a>(j: &'a Json, name: &str) -> Result<&'a str> {
    j.get(name).and_then(Json::as_str).ok_or_else(|| format!("missing {name}").into())
}

fn read_settings(j: &Json) -> Result<Settings> {
    let input = j.get("settings").ok_or("missing settings")?;
    if let Some(text) = input.as_str() {
        // Kept for old player files and internal diagnostics, not public YAML.
        return Ok(Settings::decode(text)?.settings);
    }
    let loaded = Settings::from_json(input)?;
    if !loaded.warnings.is_empty() {
        return Err(loaded.warnings.join("; ").into());
    }
    Ok(loaded.settings)
}

fn inspect_settings(j: &Json) -> Result<()> {
    let settings = read_settings(j)?;
    println!("{}", Json::obj().with("settings", settings.to_json())
        .with("settings_string", settings.encode()?.into()).pretty());
    Ok(())
}

fn generate(j: &Json) -> Result<()> {
    let settings = read_settings(j)?;
    let g = slice::generate_with(&settings, field(j, "seed")?, &GenOpts::default())?;
    let waves = g.spheres.iter().map(|row| Json::strs(row.iter().map(|(loc, _)| loc.as_str()))).collect();
    println!("{}", Json::obj().with("seed_file", g.seed_file.to_json()).with("waves", Json::Arr(waves)).pretty());
    Ok(())
}

fn message_paths(j: &Json) -> Result<Vec<String>> {
    let paths = j.get("messages").and_then(Json::as_arr).ok_or("missing language archive list")?;
    let mut result = Vec::new();
    for value in paths {
        let path = value.as_str().ok_or("invalid language archive path")?;
        modpack::rel(path)?;
        let filename = path.strip_prefix("Mals/").ok_or("language archive must be under Mals/")?;
        if filename.contains(['/', '\\']) || !filename.ends_with(".Product.110.sarc.zs") {
            return Err(format!("unexpected language archive {path}").into());
        }
        result.push(path.to_string());
    }
    result.sort();
    result.dedup();
    if result.is_empty() {
        return Err("no language archives supplied for native message localization".into());
    }
    Ok(result)
}

fn localized_archive(raw: &[u8], archive: &str, navi: ootrr_core::qol::navi_return::Mode,
                     bean: bool) -> Result<Vec<u8>> {
    let mut result = raw.to_vec();
    if navi != ootrr_core::qol::navi_return::Mode::Off {
        result = ootrr_core::qol::navi_return::localize_text(&result, navi, archive)?;
    }
    if bean {
        result = ootrr_core::difficulty::bean::localize_text(&result, archive)?;
    }
    Ok(result)
}

fn read_overlay(game: &mut Romfs, overlay: &Path, relative: &str) -> Result<(Vec<u8>, Option<u32>)> {
    let path = overlay.join(modpack::rel(relative)?);
    let frame = if path.is_file() { fs::read(path)? } else { game.read(relative)? };
    let dictionary = zs::dict_of(&frame);
    Ok((game.zs.decompress(&frame)?, dictionary))
}

// Portable OOTRR builds the gameplay mod. This pass only translates its existing
// generated messages, using an explicit file list for Windows WASI hosts.
fn localize(j: &Json) -> Result<()> {
    use ootrr_core::qol::navi_return::Mode;
    let settings = read_settings(j)?;
    let navi = match settings.text("navi_return")? {
        "off" => Mode::Off,
        "dungeons" => Mode::Dungeons,
        "everywhere" => Mode::Everywhere,
        _ => return Err("unsupported Navi return setting".into()),
    };
    let bean = settings.flag("bean_pitch")?;
    if navi == Mode::Off && !bean {
        println!("No native messages require localization.");
        return Ok(());
    }
    let paths = message_paths(j)?;
    let mut game = Romfs::open(Path::new("/game"))?;
    let overlay = Path::new("/mod");
    let mut changed = Vec::new();
    for path in paths {
        let (before, dictionary) = read_overlay(&mut game, overlay, &path)?;
        let after = localized_archive(&before, &path, navi, bean)?;
        if after != before {
            changed.push((path, before.len(), after, dictionary));
        }
    }
    if !changed.is_empty() {
        let (raw_table, dictionary) = read_overlay(&mut game, overlay, rsizetable::TABLE_PATH)?;
        let mut table = Rst::parse(&raw_table)?;
        for (path, old, raw, _) in &changed {
            table.grow(path, *old as u64, raw.len() as u64, slice::edit::MARGIN)?;
        }
        let table_frame = zs::compress_raw(&table.write()?, dictionary)?;
        // Validate every archive and its allocation before writing the staged mod.
        for (path, _, raw, dictionary) in &changed {
            let target = overlay.join(modpack::rel(path)?);
            fs::create_dir_all(target.parent().ok_or("invalid language archive destination")?)?;
            fs::write(target, zs::compress_raw(raw, *dictionary)?)?;
        }
        let target = overlay.join(rsizetable::TABLE_PATH);
        fs::create_dir_all(target.parent().ok_or("invalid resource table destination")?)?;
        fs::write(target, table_frame)?;
    }
    println!("Localized {} native message archives without changing gameplay flows.", changed.len());
    Ok(())
}

// Replace the physical reward of network gear only. Native OOTRR has already generated
// the complete mod, including its original tier ordering, shops and resource sizes.
fn patch(j: &Json) -> Result<()> {
    let mut game = Romfs::open(Path::new("/game"))?;
    let overlay = Path::new("/mod");
    let mut read = |relative: &str| -> Result<Vec<u8>> {
        let path = overlay.join(modpack::rel(relative)?);
        if path.is_file() { Ok(game.zs.decompress(&fs::read(path)?)?) }
        else { Ok(game.read_zs(relative)?) }
    };
    let mut table = Rst::parse(&read(rsizetable::TABLE_PATH)?)?;
    let files = j.get("files").and_then(Json::as_obj).ok_or("missing file list")?;
    let mut count = 0;
    for (file, requests) in files {
        let rel = modpack::rel(file)?;
        if !file.starts_with("Banc/") || !file.ends_with(".bcett.byml.zs") { return Err("unexpected map".into()); }
        let raw = read(file)?;
        let mut byml = Byml::parse(&raw)?;
        let Some(Node::Arr(actors)) = byml.root.get_mut("Actors") else { return Err("map has no Actors".into()) };
        for request in requests.as_arr().ok_or("invalid request")? {
            let hash = field(request, "actor")?.parse::<u64>()?;
            let desired = field(request, "drop")?;
            let mut matches = actors.iter_mut().filter(|a| placement::hash_of(a) == Some(hash));
            let actor = matches.next().ok_or_else(|| format!("missing chest {hash} in {file}"))?;
            if matches.next().is_some() { return Err("duplicate chest".into()); }
            let d = actor.get_mut("Dynamic").ok_or("missing Dynamic")?;
            let old = d.get("Drop__DropActor").and_then(Node::as_str).ok_or("missing chest drop")?;
            // The native builder may preserve TBox_ actors or assign their Item_/Armor_ equivalent.
            let allowed = request.get("expected").and_then(Json::as_arr).ok_or("missing actor types")?;
            if !allowed.iter().any(|a| a.as_str()==Some(old)) {
                return Err(format!("unexpected chest reward {old} at {file}/{hash}; no final mod published").into());
            }
            d.set("Drop__DropActor", Node::Str(desired.to_string()));
            if d.get("Drop__DropActor_Substitute").is_some() {
                d.set("Drop__DropActor_Substitute", Node::Str(desired.to_string()));
            }
            d.remove("GetEventName");
            count += 1;
        }
        let bytes = byml.write()?;
        table.grow(file, raw.len() as u64, bytes.len() as u64, slice::edit::MARGIN)?;
        let dest = overlay.join(rel);
        fs::create_dir_all(dest.parent().ok_or("invalid destination")?)?;
        fs::write(dest, zs::compress_raw(&bytes, Some(3))?)?;
    }
    let dest = overlay.join(rsizetable::TABLE_PATH);
    fs::create_dir_all(dest.parent().ok_or("invalid table destination")?)?;
    fs::write(dest, zs::compress_raw(&table.write()?, None)?)?;
    println!("Patched {count} physical chest entries in {} map files.", files.len());
    Ok(())
}

// Build the AP shelf actors with OOTRR's own shop factory, using the staged
// AP item packs as model/pouch inputs and preserving the seed's prices.
fn shops(j: &Json) -> Result<()> {
    use ootrr_core::shelf::{self, Job, What};
    let records = j.get("shops").and_then(Json::as_arr).ok_or("missing shop jobs")?;
    let strings = |r: &Json, key: &str| -> Result<Vec<String>> {
        r.get(key).and_then(Json::as_arr).ok_or_else(|| format!("missing {key}").into())
            .and_then(|xs| xs.iter().map(|x| x.as_str().map(str::to_owned).ok_or_else(|| "invalid shop string".into())).collect())
    };
    let mut jobs = Vec::new();
    for r in records {
        let price = r.get("price").and_then(Json::as_i64).ok_or("missing shop price")?;
        let slot = r.get("slot").and_then(Json::as_i64).ok_or("missing shop slot")?;
        if !(1..=999).contains(&price) || !(0..8).contains(&slot) {
            return Err("invalid AP shop price or slot".into());
        }
        let item = field(r, "actor")?;
        if !item.starts_with("Item_AP_") { return Err("AP shelf must contain a presentation token".into()); }
        jobs.push(Job { label: field(r,"name")?.to_string(), shop: "KF Shop".to_string(),
            slot: slot as usize, keepers: strings(r,"keepers")?, bancs: strings(r,"bancs")?,
            counters: strings(r,"counters")?,
            what: What::Deal { item: item.to_string(), price: price as i32, model: None }, tiered: None });
    }
    let messages = strings(j, "messages")?;
    let done = shelf::stage::run_with_messages(Path::new("/game"), Some(Path::new("/mod")),
        Path::new("/load"), "Archipelago", modpack::Host::Nx2navi, &jobs, Some(&messages))?;
    println!("{}", done.report);
    println!("Prepared {} AP shop shelves in {} files.", jobs.len(), done.files);
    Ok(())
}
fn run() -> Result<()> {
    let mut input = String::new();
    io::stdin().read_to_string(&mut input)?;
    let j=json::parse(&input)?;
    match env::args().nth(1).as_deref() {
        Some("generate") => generate(&j),
        Some("settings") => inspect_settings(&j),
        Some("localize") => localize(&j),
        Some("patch") => patch(&j),
        Some("shops") => shops(&j),
        _ => Err("expected generate, settings, localize, patch or shops".into()),
    }
}
fn main() {
    if let Err(e) = run() { eprintln!("{e}"); std::process::exit(1); }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ootrr_core::{difficulty::bean, msbt::{self, Msbt, Sec}, qol::navi_return::{self, Mode}, sarc};

    fn book(pairs: &[(&str, &str)]) -> Vec<u8> {
        let mut m = Msbt { be: false, unk_a: [0, 0], enc: 0, ver: 3, unk_b: [0, 0], pad: [0; 10],
            secs: vec![Sec::Lbl(vec![Vec::new()]), Sec::Txt(Vec::new())] };
        for (label, text) in pairs {
            m.put_markup(label, text).unwrap();
        }
        m.write().unwrap()
    }

    #[test]
    fn combined_localization_is_idempotent_and_preserves_native_entries() {
        let source = sarc::write(&[
            sarc::Entry { name: navi_return::CHOICES_FROM.into(), data: book(&[
                (navi_return::YES, "Native yes{5.1}"), (navi_return::NO, "Native no")]) },
            sarc::Entry { name: navi_return::MSG.into(), data: book(&[("Keep", "Native Navi text")]) },
            sarc::Entry { name: bean::MSG.into(), data: book(&[("Keep", "Native merchant text")]) },
            sarc::Entry { name: "Unrelated.bfevfl".into(), data: vec![3, 2, 1] },
        ]).unwrap();
        let base = navi_return::apply_text(&source, Mode::Everywhere, "Mals/USen.Product.110.sarc.zs").unwrap();
        let base = bean::text(&base, "Mals/USen.Product.110.sarc.zs").unwrap();
        let original = sarc::parse(&base).unwrap();
        for archive in ["Mals/EUfr.Product.110.sarc.zs", "Mals/USfr.Product.110.sarc.zs",
                        "Mals/USen.Product.110.sarc.zs", "Mals/JPja.Product.110.sarc.zs"] {
            let result = localized_archive(&base, archive, Mode::Everywhere, true).unwrap();
            assert_eq!(localized_archive(&result, archive, Mode::Everywhere, true).unwrap(), result);
            let entries = sarc::parse(&result).unwrap();
            assert_eq!(entries.len(), original.len());
            for entry in &original {
                if entry.name != navi_return::MSG && entry.name != bean::MSG {
                    assert_eq!(sarc::get(&entries, &entry.name).unwrap().data, entry.data);
                }
            }
            for file in [navi_return::MSG, bean::MSG] {
                let before = msbt::parse(&sarc::get(&original, file).unwrap().data).unwrap();
                let after = msbt::parse(&sarc::get(&entries, file).unwrap().data).unwrap();
                assert_eq!(before.names().len(), after.names().len());
                assert_eq!(before.raw("Keep"), after.raw("Keep"));
                if file == navi_return::MSG {
                    for answer in [navi_return::YES, navi_return::NO] {
                        assert_eq!(before.raw(answer), after.raw(answer));
                    }
                }
            }
            if !archive.contains("fr.") {
                assert_eq!(result, base);
            }
        }
        assert_eq!(localized_archive(b"unchanged", "Mals/EUfr.Product.110.sarc.zs", Mode::Off, false).unwrap(), b"unchanged");
        assert!(localized_archive(&source, "Mals/EUfr.Product.110.sarc.zs", Mode::Everywhere, true).is_err());
    }

    #[test]
    fn explicit_archive_paths_are_deduplicated_and_other_resources_are_refused() {
        let make = |paths: &[&str]| Json::obj().with("messages", Json::strs(paths.iter().copied()));
        assert_eq!(message_paths(&make(&["Mals/USen.Product.110.sarc.zs", "Mals/EUfr.Product.110.sarc.zs",
                                        "Mals/USen.Product.110.sarc.zs"])).unwrap(),
                   vec!["Mals/EUfr.Product.110.sarc.zs", "Mals/USen.Product.110.sarc.zs"]);
        for path in ["Event/EventFlow/NaviHint.bfevfl.zs", "Mals/../NaviHint.Product.110.sarc.zs",
                     "/Mals/EUfr.Product.110.sarc.zs", "Mals/EUfr.Product.110.sarc",
                     "Mals/..\\Event\\EUfr.Product.110.sarc.zs", "Mals/nested/EUfr.Product.110.sarc.zs"] {
            assert!(message_paths(&make(&[path])).is_err());
        }
        assert!(message_paths(&make(&[])).is_err());
    }

    #[test]
    fn overlay_reads_dictionary_ids_after_optional_window_descriptors() {
        let unique = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos();
        let root = env::temp_dir().join(format!("ootrr-localize-frame-{}-{unique}", std::process::id()));
        let original = root.join("game");
        let overlay = root.join("mod");
        let path = "Mals/EUfr.Product.110.sarc.zs";
        fs::create_dir_all(original.join("Mals")).unwrap();
        fs::create_dir_all(overlay.join("Mals")).unwrap();
        let raw = b"synthetic localized message archive";
        // ID zero is legal and needs no trained dictionary. A windowed frame
        // puts its descriptor before the ID, unlike a single-segment frame.
        let single = zs::compress_raw(raw, Some(0)).unwrap();
        let mut windowed = single.clone();
        windowed[4] &= !0x20;
        windowed.insert(5, 0x58);
        fs::write(original.join(path), &single).unwrap();
        fs::write(overlay.join(path), &windowed).unwrap();
        let mut game = Romfs { root: original, zs: zs::Zs::new() };
        assert_eq!(read_overlay(&mut game, &overlay, path).unwrap(), (raw.to_vec(), Some(0)));
        fs::remove_file(overlay.join(path)).unwrap();
        assert_eq!(read_overlay(&mut game, &overlay, path).unwrap(), (raw.to_vec(), Some(0)));
        let cleanup_root = root.canonicalize().unwrap();
        let cleanup_parent = env::temp_dir().canonicalize().unwrap();
        assert_eq!(cleanup_root.parent(), Some(cleanup_parent.as_path()));
        fs::remove_dir_all(cleanup_root).unwrap();
    }
}
