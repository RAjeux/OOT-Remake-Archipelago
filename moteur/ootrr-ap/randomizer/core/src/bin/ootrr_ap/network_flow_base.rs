//! Complete the existing native source adapters when a rolled prize stayed
//! vanilla. This staged pass never changes a canonical seed or runs a fill.
use std::collections::{BTreeMap, HashMap};
use std::fs;
use std::path::Path;

use ootrr_core::bfevfl::{Bf, Flow, Kind, Val};
use ootrr_core::byml::Byml;
use ootrr_core::flow_extra::{self, How, Op};
use ootrr_core::flow_locations;
use ootrr_core::settings::seed::SeedFile;
use ootrr_core::slice::data::Data;
use ootrr_core::staging::Out;
use ootrr_core::{cow_clone, progressive, romfs::Romfs, rsizetable::{self, Rst}, scrubs_b, zs};

use super::{network_sources, read_overlay, Result};

struct File {
    original: Vec<u8>,
    dictionary: Option<u32>,
    flow: Bf,
    fresh: bool,
}

fn load<'a>(files: &'a mut BTreeMap<String, File>, game: &mut Romfs, overlay: &Path, name: &str) -> Result<&'a mut File> {
    let path = flow_locations::path_of(name);
    if !files.contains_key(&path) {
        let fresh = !overlay.join(&path).is_file() && !game.root.join(&path).is_file();
        let (raw, dictionary) = if fresh {
            (cow_clone::base(game, name)?.ok_or_else(|| format!("native source flow {name} is missing"))?, cow_clone::flow::dict(game)?)
        } else { read_overlay(game, overlay, &path)? };
        let flow = Bf::parse(&raw)?;
        files.insert(path.clone(), File { original: raw, dictionary, flow, fresh });
    }
    files.get_mut(&path).ok_or("native source flow cache failed".into())
}

fn params_match(kind: &Kind, params: &[(String, Val)]) -> bool {
    params.iter().all(|(key, value)| kind.params().and_then(|p| p.get(key)) == Some(value))
}

fn is_set(f: &Flow, k: &Kind, flag: &str) -> bool {
    let Kind::Action { actor, act, params, .. } = k else { return false; };
    let Some(actor) = f.actors.get(*actor as usize) else { return false; };
    actor.name == "GameDataActor" && actor.actions.get(*act as usize).map(String::as_str) == Some("EventTriggerSetGameDataBool")
        && params.as_ref().and_then(|p| p.get("GameDataName")) == Some(&Val::Str(flag.to_string()))
        && params.as_ref().and_then(|p| p.get("Value")) == Some(&Val::Bool(1))
}

fn already_applied(b: &Bf, op: &Op) -> bool {
    let Some(f) = b.flows.first() else { return false; };
    let event = f.events.get(op.index).filter(|e| e.name == op.event);
    match &op.how {
        How::Once(once) => f.events.iter().any(|e| is_set(f, &e.kind, &once.flag)),
        How::Rename { new, .. } => f.actors.iter().any(|a| a.name == *new && a.sub.is_empty()),
        How::Insert { flag } => event.is_some() && u16::try_from(op.index).ok().is_some_and(|start|
            cow_clone::flow::order(f, start).iter().any(|index| is_set(f, &f.events[*index as usize].kind, flag))),
        How::Retarget { case, new, .. } => event.is_some_and(|e| match &e.kind {
            Kind::Switch { cases, .. } | Kind::SubSwitch { cases, .. } => cases.iter().any(|c| c.val == *case && c.ev == *new), _ => false,
        }),
        How::Next { new, .. } => event.is_some_and(|e| match &e.kind { Kind::Action { next, .. } | Kind::Sub { next, .. } | Kind::Join { next } => *next == *new, _ => false }),
        How::SwapSub { to, params, .. } => event.is_some_and(|e| match &e.kind {
            Kind::Sub { flow, entry, .. } => format!("{flow}:{entry}") == *to && params_match(&e.kind, params), _ => false,
        }),
        How::Query { to, params, .. } => event.is_some_and(|e| match &e.kind {
            Kind::Switch { actor, query, .. } => f.actors.get(*actor as usize).is_some_and(|a|
                a.queries.get(*query as usize).is_some_and(|q| format!("{}.{q}", a.name) == *to)) && params_match(&e.kind, params), _ => false,
        }),
        How::Set { param, new, .. } => event.is_some_and(|e| match e.kind.params().and_then(|p| p.get(param)) {
            Some(Val::Str(value)) | Some(Val::Actor(value, _)) => value == new, _ => false,
        }),
        How::Clone { param, new, .. } => event.and_then(|e| match &e.kind { Kind::Sub { next, .. } => f.events.get(*next as usize), _ => None })
            .is_some_and(|e| e.name.starts_with("Extra") && matches!(e.kind.params().and_then(|p| p.get(param)), Some(Val::Str(value)) if value == new)),
        How::Backfill(_) => false,
    }
}

fn ensure_op(b: &mut Bf, op: &Op) -> Result<bool> {
    if already_applied(b, op) { return Ok(false); }
    flow_extra::apply_op(b, op)?;
    Ok(true)
}

fn out(path: String, original: &[u8], dictionary: Option<u32>, raw: Vec<u8>) -> Result<Out> {
    Ok(Out { path, old: original.len(), new: raw.len(), z: zs::compress_raw(&raw, dictionary)? })
}

pub fn run(input: &ootrr_core::json::Json) -> Result<()> { run_at(input, Path::new("/game"), Path::new("/mod")) }

fn run_at(input: &ootrr_core::json::Json, game_path: &Path, overlay: &Path) -> Result<()> {
    let seed = SeedFile::parse(&input.get("seed_file").ok_or("missing canonical seed file")?.pretty())?;
    // Validate every selected source against the generator-owned catalogue.
    network_sources::selected(&seed)?;
    let data = Data::load()?;
    let settings = seed.settings()?.settings;
    let plan = ootrr_core::slice::support::plan(&settings)?;
    let independent_trades = input.get("adult_trade_shuffle").and_then(ootrr_core::json::Json::as_bool).unwrap_or(plan.adult_trade);
    let mut game = Romfs::open(game_path)?;
    let mut files = BTreeMap::new();
    let mut ops = 0;
    let mut missing_scrubs = Vec::new();
    for (name, reward) in &seed.placements {
        let Some(location) = data.flow.by_name(name) else { continue; };
        if independent_trades && (ootrr_core::adult_trade::is_location(name) || name == ootrr_core::adult_trade::FINAL) { continue; }
        let actor = data.item(reward).and_then(|i| i.actor.as_deref()).ok_or_else(|| format!("native reward {reward} has no actor"))?;
        if scrubs_b::is_b(location) {
            let book = scrubs_b::book()?;
            let scrub = book.by_location(name).ok_or("native scrub has no catalogue entry")?;
            let file = load(&mut files, &mut game, overlay, &book.flow)?;
            let flow = file.flow.flows.first_mut().ok_or("native scrub file has no flow")?;
            if !flow.entries.iter().any(|entry| entry.name == scrub.entry()) {
                let sale = scrubs_b::Sale { entry: scrub.entry(), flag: scrub.flag.clone(), actor: actor.to_string(),
                    price: ootrr_core::scrub_prices::price(plan.rewards.scrub_prices, &seed.seed, name).unwrap_or(scrub.price) };
                let based = flow.events.iter().any(|e| e.kind.params().and_then(|p| p.get("SaleActor")).is_some());
                if based { scrubs_b::add(flow, &sale, &book.label)?; }
                else { scrubs_b::edit(flow, &[sale], &book.label)?; }
                missing_scrubs.push(scrub.clone());
                ops += 1;
            }
            continue;
        }
        // Other native source operations also adjust authored story graphs.
        // Their original grant anchors remain available to the AP postpass;
        // replaying them over a progressive/cutscene build would be unsafe.
        // Only these adapters create a grant that otherwise does not exist.
        if !flow_extra::cows::is(name) && !flow_extra::frogs::is(name) && !flow_extra::trade::is(name) { continue; }
        for op in flow_extra::ops_of(name, actor)? {
            let file = load(&mut files, &mut game, overlay, &op.file)?;
            match ensure_op(&mut file.flow, &op) {
                Ok(changed) => ops += usize::from(changed),
                Err(error) => return Err(format!("native network adapter {name}, {} in {}: {error}", op.kind(), op.file).into()),
            }
        }
    }
    let (raw_rst, rst_dictionary) = read_overlay(&mut game, overlay, rsizetable::TABLE_PATH)?;
    let mut rst = Rst::parse(&raw_rst)?;
    let mut outputs: BTreeMap<String, Out> = BTreeMap::new();
    let mut flow_sizes = Vec::new();
    let mut changed_flows = HashMap::new();
    let mut new_cows = Vec::new();
    for (path, file) in &files {
        let raw = file.flow.write()?;
        if Bf::parse(&raw)? != file.flow { return Err("native network adapter does not roundtrip".into()); }
        if file.fresh || raw != file.original {
            let output = out(path.clone(), &file.original, file.dictionary, raw)?;
            flow_sizes.push((path.clone(), output.new));
            for flow in &file.flow.flows { changed_flows.insert(flow.name.clone(), flow.clone()); }
            outputs.insert(path.clone(), output);
        }
        let name = path.strip_prefix("Event/EventFlow/").and_then(|p| p.strip_suffix(".zs")).unwrap_or("");
        if let Some(cow) = cow_clone::of_file(name) {
            if !overlay.join(ootrr_core::pickup_pack::pack_of(&cow.class)).is_file() {
                new_cows.push(cow);
                if !flow_sizes.iter().any(|(p, _)| p == path) { flow_sizes.push((path.clone(), file.original.len())); }
            }
        }
    }
    if !missing_scrubs.is_empty() {
        let book = scrubs_b::book()?;
        let mut by_map: BTreeMap<String, Vec<_>> = BTreeMap::new();
        for scrub in &missing_scrubs { for spot in &scrub.spots { by_map.entry(spot.file.clone()).or_default().push((spot, scrub.entry())); } }
        for (path, spots) in by_map {
            let (raw, dictionary) = read_overlay(&mut game, overlay, &path)?;
            let mut y = Byml::parse(&raw)?;
            for (spot, entry) in spots {
                if !scrubs_b::point(&mut y, spot, &entry)? { return Err("native AP scrub was not found in its map".into()); }
            }
            outputs.insert(path.clone(), out(path, &raw, dictionary, y.write()?)?);
        }
        for path in [progressive::SETTING_TABLE, progressive::ANALYZED_TABLE] {
            let (raw, dictionary) = read_overlay(&mut game, overlay, path)?;
            let mut y = Byml::parse(&raw)?;
            let rows: Vec<_> = missing_scrubs.iter().map(|scrub| (scrub.entry(),
                (path == progressive::SETTING_TABLE).then(|| scrub.entry()))).collect();
            progressive::add_rows(&mut y, &book.template, &rows)?;
            outputs.insert(path.to_string(), out(path.to_string(), &raw, dictionary, y.write()?)?);
        }
    }
    if !new_cows.is_empty() {
        let have = |path: &str| outputs.get(path).map(|o| o.z.clone()).or_else(|| fs::read(overlay.join(path)).ok());
        let cows: Vec<_> = new_cows.iter().collect();
        let made = cow_clone::stage(&mut game, &have, &cows, &rst, &flow_sizes)?;
        cow_clone::sized(&mut game, &mut rst, &made)?;
        for output in made.outs { outputs.insert(output.path.clone(), output); }
    }
    if !changed_flows.is_empty() {
        let have = |path: &str| outputs.get(path).map(|o| o.z.clone()).or_else(|| fs::read(overlay.join(path)).ok());
        if let Some((output, _)) = flow_extra::analyzed::stage(&mut game, &have, changed_flows)? {
            outputs.insert(output.path.clone(), output);
        }
    }
    for output in outputs.values() {
        if output.old > 0 { rst.grow(&output.path, output.old as u64, output.new as u64, ootrr_core::slice::edit::MARGIN)?; }
    }
    if outputs.is_empty() { println!("All native network reward adapters are already present."); return Ok(()); }
    // Validation, new cow classes, map bindings and preload analysis all finish
    // before publishing anything into the caller's temporary mod.
    for output in outputs.values() {
        let path = overlay.join(ootrr_core::modpack::rel(&output.path)?);
        fs::create_dir_all(path.parent().ok_or("invalid staged reward destination")?)?;
        fs::write(path, &output.z)?;
    }
    super::ap_skulls::write(overlay, rsizetable::TABLE_PATH, &rst.write()?, rst_dictionary)?;
    println!("Completed {ops} missing native reward adapter steps in {} staged resources.", outputs.len());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use ootrr_core::bfevfl::{Actor, Cont, Entry, Event};

    #[test]
    fn a_missing_once_adapter_is_added_once_and_keeps_the_repeatable_native_grant() {
        let original = Event { name: "Event0".to_string(), kind: Kind::Sub { next: 0xffff,
            params: Some(Cont { items: vec![("ActorName".to_string(), Val::Str("Item_Bottle_Milk".to_string()))] }),
            flow: "Dm_SY_GetInEvent".to_string(), entry: "GetInEventInBottle".to_string() } };
        let mut b = Bf { ver: [0, 4, 0, 0], bom: 0xfeff, shift: 3, pad: 0, name: "Cow".to_string(), tls: Vec::new(),
            flows: vec![Flow { name: "Cow".to_string(), actors: vec![Actor { name: "GameDataActor".to_string(),
                sub: String::new(), arg: String::new(), actions: Vec::new(), queries: Vec::new(), params: None, ep: 0xffff, cut: 1 }],
                events: vec![original.clone()], entries: vec![Entry { name: "GiveMilk".to_string(), subs: vec![0], vars: Vec::new(), main: 0, pad: 0 }] }] };
        let op = Op { file: "Cow.bfevfl".to_string(), index: 0, event: "Event0".to_string(),
            how: How::Once(flow_extra::Once { entry: "GiveMilk".to_string(), flag: "NativeUnusedOnceFlag".to_string(),
                child: false, adult: false, sub: "Dm_SY_GetInEvent:GetInEvent_NotTurn_NotNpc".to_string(),
                params: vec![("ActorName".to_string(), Val::Str("Item_Bottle_Milk".to_string()))] }) };
        assert!(ensure_op(&mut b, &op).unwrap());
        assert_eq!(b.flows[0].events[0], original);
        let once = b.clone();
        assert!(!ensure_op(&mut b, &op).unwrap());
        assert_eq!(b, once);
        assert_eq!(Bf::parse(&b.write().unwrap()).unwrap(), b);
    }

    #[test]
    fn real_staged_native_reward_adapters_are_complete_and_repeatable_when_fixture_supplied() {
        let Some(game) = std::env::var_os("OOTRR_ROMFS") else { return; };
        let Some(stage) = std::env::var_os("OOTRR_AP_FLOW_STAGE") else { return; };
        let Some(seed) = std::env::var_os("OOTRR_AP_FLOW_SEED") else { return; };
        let raw = fs::read_to_string(seed).unwrap();
        let value = ootrr_core::json::parse(&raw).unwrap();
        let input = ootrr_core::json::Json::obj().with("seed_file", value);
        run_at(&input, Path::new(&game), Path::new(&stage)).unwrap();
        run_at(&input, Path::new(&game), Path::new(&stage)).unwrap();
    }
}
