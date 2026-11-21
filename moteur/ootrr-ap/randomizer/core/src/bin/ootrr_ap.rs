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
        Some("patch") => patch(&j),
        Some("shops") => shops(&j),
        _ => Err("expected generate, settings, patch or shops".into()),
    }
}
fn main() {
    if let Err(e) = run() { eprintln!("{e}"); std::process::exit(1); }
}
