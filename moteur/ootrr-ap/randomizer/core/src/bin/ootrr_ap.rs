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
    let extra = additional_sources::selected(&settings)?;
    let sources = additional_sources::merge(network_sources::selected(&g.seed_file)?, &extra, &settings)?;
    let optional = network_sources::optional_sources(&g.seed_file, &g.spheres)?;
    let features = j.get("features").cloned().unwrap_or_else(Json::obj);
    let (world, placement) = ootrr_core::slice::modern::rebuild(&g.seed_file, &features)?;
    let access = access_logic::from_world(&world, &placement, &sources)?;
    let mut output = Json::obj().with("seed_file", g.seed_file.to_json()).with("waves", Json::Arr(waves))
        .with("access_logic", access)
        .with("network_sources_schema", 2_i64.into()).with("network_sources", sources)
        .with("additional_sources", Json::strs(extra.iter().map(String::as_str)))
        .with("optional_sources", optional)
        .with("progression_items", Json::strs(g.progression_items.iter().map(String::as_str)));
    if let Some(wave) = g.master_sword_wave {
        output = output.with("master_sword_wave", (wave as i64).into());
    }
    println!("{}", output.pretty());
    Ok(())
}

fn base_seed(j: &Json) -> Result<()> {
    let input = j.get("seed_file").ok_or("missing seed_file")?;
    let seed = ootrr_core::settings::seed::SeedFile::parse(&input.pretty())?;
    let derived = ootrr_core::adult_trade::base_seed(&seed)?;
    println!("{}", derived.to_json().pretty());
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
fn shop_jobs(j: &Json) -> Result<Vec<ootrr_core::shelf::Job>> {
    use std::collections::BTreeSet;
    use ootrr_core::shelf::{Job, What};
    let table = ootrr_core::shops::table()?;
    let records = j.get("shops").and_then(Json::as_arr).ok_or("missing shop jobs")?;
    let strings = |r: &Json, key: &str| -> Result<Vec<String>> {
        r.get(key).and_then(Json::as_arr).ok_or_else(|| format!("missing {key}").into())
            .and_then(|xs| xs.iter().map(|x| x.as_str().map(str::to_owned).ok_or_else(|| "invalid shop string".into())).collect())
    };
    let mut jobs = Vec::new();
    let mut slots = BTreeSet::new();
    let mut actors = BTreeSet::new();
    for r in records {
        let price = r.get("price").and_then(Json::as_i64).ok_or("missing shop price")?;
        let slot = r.get("slot").and_then(Json::as_i64).ok_or("missing shop slot")?;
        if !(1..=999).contains(&price) || !(0..8).contains(&slot) {
            return Err("invalid AP shop price or slot".into());
        }
        let name = field(r, "name")?;
        // Old player files only contain Kokiri purchases and omit the shop.
        // New rooms identify every shelf by its canonical shop and slot pair.
        let shop = match r.get("shop") {
            Some(value) => value.as_str().ok_or("invalid AP shop name")?,
            None => "KF Shop",
        };
        let source = table.slot(name).ok_or("unknown AP shop location")?;
        let metadata = table.shop(shop).ok_or("unknown AP shop")?;
        if source.shop != shop || source.slot != slot as usize {
            return Err("AP shop location does not match its shop and slot".into());
        }
        let keepers = strings(r, "keepers")?;
        let bancs = strings(r, "bancs")?;
        let counters = strings(r, "counters")?;
        if keepers != metadata.keepers || bancs != metadata.bancs || counters != source.counters {
            return Err("AP shop resources do not match the canonical shelf".into());
        }
        let item = field(r, "actor")?;
        if !item.starts_with("Item_AP_") || !ootrr_core::pickup_pack::is_actor_name(item) {
            return Err("AP shelf must contain a presentation token".into());
        }
        if !slots.insert((shop, slot)) || !actors.insert(item) {
            return Err("each AP shop slot needs a unique presentation token".into());
        }
        // All shelves use their own no-effect AP pouch identity. A local
        // reward borrows the native item's display only; DisplayShop applies
        // its complete, room-specific grant recipe after a successful sale.
        let model = match (r.get("local_item"), r.get("native_actor")) {
            (None, None) => None,
            (Some(local), Some(native)) => {
                let name = local.as_str().ok_or("invalid local shop reward")?;
                let actor = native.as_str().ok_or("invalid local shop actor")?;
                if name.is_empty() || name.len() > 256 || name.chars().any(char::is_control) ||
                    !ootrr_core::pickup_pack::is_actor_name(actor) || actor.starts_with("Item_AP_") {
                    return Err("invalid local shop reward".into());
                }
                Some(actor.to_string())
            }
            _ => return Err("a local shop reward needs its name and native actor".into()),
        };
        jobs.push(Job { label: name.to_string(), shop: shop.to_string(),
            slot: slot as usize, keepers, bancs, counters,
            what: What::Deal { item: item.to_string(), price: price as i32, model }, tiered: None });
    }
    Ok(jobs)
}

fn shops(j: &Json) -> Result<()> {
    use ootrr_core::shelf;
    let jobs = shop_jobs(j)?;
    let strings = |r: &Json, key: &str| -> Result<Vec<String>> {
        r.get(key).and_then(Json::as_arr).ok_or_else(|| format!("missing {key}").into())
            .and_then(|xs| xs.iter().map(|x| x.as_str().map(str::to_owned).ok_or_else(|| "invalid shop string".into())).collect())
    };
    let messages = strings(j, "messages")?;
    let done = shelf::stage::run_with_messages(Path::new("/game"), Some(Path::new("/mod")),
        Path::new("/load"), "Archipelago", modpack::Host::Nx2navi, &jobs, Some(&messages))?;
    println!("{}", done.report);
    println!("Prepared {} AP shop shelves in {} files.", jobs.len(), done.files);
    Ok(())
}
#[path = "ootrr_ap/skulls.rs"]
mod ap_skulls;
#[path = "ootrr_ap/network_sources.rs"]
mod network_sources;
#[path = "ootrr_ap/portable_seed.rs"]
mod portable_seed;
#[path = "ootrr_ap/portable_geometry.rs"]
mod portable_geometry;
#[path = "ootrr_ap/network_pickups.rs"]
mod network_pickups;
#[path = "ootrr_ap/network_flow_base.rs"]
mod network_flow_base;
#[path = "ootrr_ap/access_logic.rs"]
mod access_logic;
#[path = "ootrr_ap/cosmetics.rs"]
mod ap_cosmetics;
#[path = "ootrr_ap/additional_sources.rs"]
mod additional_sources;

fn upstream_features(j: &Json) -> Result<()> {
    let mut features = j.get("features").ok_or("missing features")?.clone()
        .with("seed", field(j, "seed")?.into()).with("native_settings", read_settings(j)?.to_json());
    if let Some(context) = j.get("protected_sources") {
        features = features.with("protected_sources", context.clone());
    }
    // Reject missing mutation context before either native stage writes files.
    // An explicit empty object is valid for a room with no physical AP checks.
    ootrr_core::upstream_additions::Options::read(&features)?;
    let difficulty = ootrr_core::feature_difficulty::read_features(&features)?;
    ootrr_core::feature_difficulty::protected::read(&features, difficulty.randomizer || difficulty.encounters)?;
    let caps = match j.get("key_caps") {
        None => None,
        Some(value) => {
            let values = value.as_arr().ok_or("dungeon key totals must be an array")?;
            if values.len() != 8 { return Err("expected eight dungeon key totals".into()); }
            Some(values.iter().map(|v| v.as_i64().filter(|n| (0..=i32::MAX as i64).contains(n))
                .map(|n| n as u32).ok_or("invalid dungeon key total")).collect::<std::result::Result<Vec<_>, _>>()?)
        }
    };
    let names = match j.get("additional_sources") {
        None => Vec::new(),
        Some(value) => value.as_arr().ok_or("invalid additional native source selection")?.iter()
            .map(|name| name.as_str().map(str::to_owned).ok_or("invalid additional native source name"))
            .collect::<std::result::Result<Vec<_>, _>>()?,
    };
    additional_sources::prepare(Path::new("/game"), Path::new("/mod"), &names, &read_settings(j)?)?;
    let count = ootrr_core::upstream_additions::prepare(Path::new("/game"), Path::new("/mod"), &features, caps.as_deref())?;
    println!("Prepared {count} resources for versioned AP features.");
    Ok(())
}

fn run() -> Result<()> {
    let mut input = String::new();
    io::stdin().read_to_string(&mut input)?;
    let j=json::parse(&input)?;
    match env::args().nth(1).as_deref() {
        Some("generate") => generate(&j),
        Some("catalog") => { println!("{}", network_sources::catalog()?.pretty()); Ok(()) },
        Some("sources") => network_pickups::run(&j),
        Some("network-flow-base") => network_flow_base::run(&j),
        Some("base-seed") => base_seed(&j),
        Some("portable-seed") => portable_seed::run(&j),
        Some("portable-geometry") => portable_geometry::run(&j),
        Some("settings") => inspect_settings(&j),
        Some("localize") => localize(&j),
        Some("patch") => patch(&j),
        Some("shops") => shops(&j),
        Some("skulls") => ap_skulls::run(&j),
        Some("features") => upstream_features(&j),
        Some("cosmetics") => ap_cosmetics::run(&j),
        _ => Err("expected generate, catalog, sources, network-flow-base, base-seed, portable-seed, portable-geometry, settings, localize, patch, shops or skulls".into()),
    }
}
fn main() {
    if let Err(e) = run() { eprintln!("{e}"); std::process::exit(1); }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ootrr_core::{difficulty::bean, msbt::{self, Msbt, Sec}, qol::navi_return::{self, Mode}, sarc};

    #[test]
    fn physical_actor_changes_require_explicit_ap_protection_before_reading_resources() {
        let request = Json::obj().with("settings", Json::obj()).with("seed", "AP-guard".into())
            .with("features", Json::obj().with("schema", 1_i64.into()).with("settings",
                Json::obj().with("enemy_randomizer", true.into())));
        let error = upstream_features(&request).unwrap_err().to_string();
        assert!(error.contains("missing AP source protection context"), "{error}");
    }

    fn book(pairs: &[(&str, &str)]) -> Vec<u8> {
        let mut m = Msbt { be: false, unk_a: [0, 0], enc: 0, ver: 3, unk_b: [0, 0], pad: [0; 10],
            secs: vec![Sec::Lbl(vec![Vec::new()]), Sec::Txt(Vec::new())] };
        for (label, text) in pairs {
            m.put_markup(label, text).unwrap();
        }
        m.write().unwrap()
    }

    fn shop_record_in(actor: &str, shop: &str, slot: i64) -> Json {
        let table = ootrr_core::shops::table().unwrap();
        let source = table.at(shop, slot as usize).unwrap();
        let metadata = table.shop(shop).unwrap();
        Json::obj().with("name", source.name.clone().into()).with("shop", shop.into())
            .with("actor", actor.into()).with("slot", slot.into()).with("price", 20_i64.into())
            .with("keepers", Json::strs(metadata.keepers.iter().map(String::as_str)))
            .with("bancs", Json::strs(metadata.bancs.iter().map(String::as_str)))
            .with("counters", Json::strs(source.counters.iter().map(String::as_str)))
    }

    fn shop_record(actor: &str, slot: i64) -> Json {
        let Json::Obj(mut fields) = shop_record_in(actor, "KF Shop", slot) else { unreachable!() };
        fields.retain(|(name, _)| name != "shop");
        Json::Obj(fields)
    }

    #[test]
    fn local_and_remote_shelves_keep_distinct_no_effect_tokens() {
        use ootrr_core::shelf::What;
        let local = shop_record("Item_AP_1234", 0)
            .with("local_item", "Bow".into()).with("native_actor", "Item_Range_Bow".into());
        let remote = shop_record("Item_AP_5678", 1);
        let jobs = shop_jobs(&Json::obj().with("shops", Json::Arr(vec![local.clone(), remote.clone()]))).unwrap();
        assert!(matches!(&jobs[0].what, What::Deal { item, model: Some(model), .. }
            if item == "Item_AP_1234" && model == "Item_Range_Bow"));
        assert!(matches!(&jobs[1].what, What::Deal { item, model: None, .. }
            if item == "Item_AP_5678"));
        assert_ne!(jobs[0].shelf_actor(), jobs[1].shelf_actor());
        for rows in [vec![local.clone(), local.clone()],
                     vec![local.clone().with("native_actor", "../Pack/unsafe".into())],
                     vec![remote.clone().with("local_item", "Bow".into())],
                     vec![local.with("native_actor", "Item_AP_8765".into())]] {
            assert!(shop_jobs(&Json::obj().with("shops", Json::Arr(rows))).is_err());
        }
    }

    #[test]
    fn every_shop_can_use_the_same_slot_number_with_distinct_local_or_foreign_rewards() {
        use ootrr_core::shelf::What;
        let table = ootrr_core::shops::table().unwrap();
        let records = table.slots.iter().enumerate().map(|(index, slot)| {
            let record = shop_record_in(&format!("Item_AP_{}", 10000 + index), &slot.shop, slot.slot as i64);
            if index % 2 == 0 {
                record.with("local_item", "Bow".into()).with("native_actor", "Item_Range_Bow".into())
            } else { record }
        }).collect();
        let jobs = shop_jobs(&Json::obj().with("shops", Json::Arr(records))).unwrap();
        assert_eq!(jobs.len(), 64);
        for (index, job) in jobs.iter().enumerate() {
            let source = &table.slots[index];
            assert_eq!((job.label.as_str(), job.shop.as_str(), job.slot),
                       (source.name.as_str(), source.shop.as_str(), source.slot));
            assert_eq!(job.counters, source.counters);
            assert_eq!(job.keepers, table.shop(&source.shop).unwrap().keepers);
            assert!(matches!(&job.what, What::Deal { model, .. } if model.is_some() == (index % 2 == 0)));
        }
    }

    #[test]
    fn legacy_kokiri_jobs_keep_their_physical_slots_without_an_explicit_shop() {
        let records = (0..8).map(|slot| shop_record(&format!("Item_AP_{}", 20000 + slot), slot)).collect();
        let jobs = shop_jobs(&Json::obj().with("shops", Json::Arr(records))).unwrap();
        assert_eq!(jobs.len(), 8);
        assert!(jobs.iter().enumerate().all(|(slot, job)| job.shop == "KF Shop" && job.slot == slot));
    }

    #[test]
    fn shops_reject_crossed_identities_shared_tokens_and_tampered_resources() {
        let first = shop_record_in("Item_AP_1234", "KF Shop", 0);
        let second = shop_record_in("Item_AP_5678", "Market Bazaar", 0);
        for records in [
            vec![first.clone(), first.clone()],
            vec![first.clone(), second.clone().with("actor", "Item_AP_1234".into())],
            vec![first.clone().with("shop", "Market Bazaar".into())],
            vec![first.clone().with("shop", "Unknown Shop".into())],
            vec![first.clone().with("slot", 1_i64.into())],
            vec![first.clone().with("keepers", Json::strs(["Npc_Hylia_018_Shop_Child"]))],
            vec![first.clone().with("bancs", Json::strs(["Banc/../unsafe"]))],
            vec![second.with("counters", Json::strs(["Shop_SoldNum.Npc_Kokiri_001_Shop_Child.0"]))],
        ] {
            assert!(shop_jobs(&Json::obj().with("shops", Json::Arr(records))).is_err());
        }
    }

    #[test]
    fn local_shop_text_copies_native_controls_and_preserves_remote_text() {
        use std::collections::BTreeMap;
        use ootrr_core::shelf::text::{archive_with_aliases, POUCH_MSG};
        let source = sarc::write(&[
            sarc::Entry { name: POUCH_MSG.into(), data: book(&[
                ("Weapon_Range_Bow_Name", "Native bow{5.1}"),
                ("Weapon_Range_Bow_Caption", "Native item description"),
                ("Item_AP_1234_Name", "Old AP name"),
                ("Item_AP_1234_GetCaption", "Old AP recipient text"),
                ("Item_AP_1234_GetMessage", "Old AP recipient message"),
                ("Item_AP_5678_Name", "Foreign item for Ami"),
                ("Item_AP_5678_Caption", "Keep this foreign description")]) },
            sarc::Entry { name: "Unrelated.msbt".into(), data: vec![1, 2, 3] },
        ]).unwrap();
        let aliases = BTreeMap::from([("Item_AP_1234".into(), "Weapon_Range_Bow".into())]);
        let ids = vec!["Item_AP_1234".into(), "Item_AP_5678".into()];
        let (result, changed) = archive_with_aliases(&source, &ids, &aliases).unwrap();
        assert!(changed > 0);
        let entries = sarc::parse(&result).unwrap();
        let after = msbt::parse(&sarc::get(&entries, POUCH_MSG).unwrap().data).unwrap();
        assert_eq!(after.raw("Item_AP_1234_Name"), after.raw("Weapon_Range_Bow_Name"));
        for suffix in ["_Caption", "_GetCaption", "_GetMessage", "_ShopCaption"] {
            assert_eq!(after.raw(&format!("Item_AP_1234{suffix}")), after.raw("Weapon_Range_Bow_Caption"));
        }
        let original = sarc::parse(&source).unwrap();
        let before = msbt::parse(&sarc::get(&original, POUCH_MSG).unwrap().data).unwrap();
        assert_eq!(after.raw("Item_AP_5678_Name"), before.raw("Item_AP_5678_Name"));
        assert_eq!(after.raw("Item_AP_5678_Caption"), before.raw("Item_AP_5678_Caption"));
        assert_eq!(sarc::get(&entries, "Unrelated.msbt").unwrap().data, vec![1, 2, 3]);
        assert_eq!(archive_with_aliases(&result, &ids, &aliases).unwrap(), (result, 0));
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
