//! Regression probes for the remake dungeon layout, without changing AP identities.
//!
//! The layout corrections are backported from OOTRR 0.8.2, revision
//! 0fa64f44b5e689f39bcf98a151fc32cb019d538e. The AP fork retains its old
//! actor/name bindings, small-key totals and native-local location families.

use crate::logic_items::ItemId;
use crate::search::{explore, Search};
use crate::slice::data::Data;
use crate::slice::fill::vanilla_place;
use crate::slice::logic::world_with;
use crate::world::{Placement, World};

fn open(d: &Data) -> World {
    world_with(d, &[("open_door_of_time", "open")]).unwrap()
}

fn stripped(w: &World, d: &Data, names: &[&str]) -> Placement {
    let mut p = vanilla_place(w, d).unwrap();
    let gone: Vec<ItemId> = names.iter().map(|name| w.item(name).unwrap()).collect();
    for location in &w.real {
        if p.get(*location).is_some_and(|item| gone.contains(&item)) {
            p.item[*location] = None;
        }
    }
    p
}

fn search<'a>(w: &'a World, p: &Placement, names: &[&str]) -> Search<'a> {
    let items: Vec<ItemId> = names.iter().map(|name| w.item(name).unwrap()).collect();
    explore(w, p, &items)
}

fn location(w: &World, result: &Search, name: &str) -> bool {
    result.loc_access(w.loc(name).unwrap())
}

fn region(w: &World, result: &Search, name: &str) -> bool {
    result.region_reached(w.region(name).unwrap(), None)
}

fn supplied<'a>(w: &'a World, d: &Data, skip: &[&str], key: &str, count: usize) -> Search<'a> {
    let key_id = w.item(key).unwrap();
    let missing: Vec<ItemId> = skip.iter().map(|name| w.item(name).unwrap()).collect();
    let mut p = vanilla_place(w, d).unwrap();
    for location in &w.real {
        if p.get(*location).is_some_and(|item| item == key_id || missing.contains(&item)) {
            p.item[*location] = None;
        }
    }
    let mut extra = Vec::new();
    for (item, _) in w.items.names.iter().enumerate() {
        if w.items.adv[item] && item != key_id && !missing.contains(&item) {
            extra.extend([item; 3]);
        }
    }
    extra.extend(vec![key_id; count]);
    explore(w, &p, &extra)
}

#[test]
fn water_river_requires_longshot_instead_of_the_n64_time_block() {
    let d = Data::load().unwrap();
    let w = open(&d);
    let p = stripped(&w, &d, &["Progressive Hookshot", "Song of Time"]);
    let short = search(&w, &p, &["Progressive Hookshot", "Song of Time"]);
    assert!(region(&w, &short, "Water Temple Dark Link Region"));
    assert!(!region(&w, &short, "Water Temple River"));
    let long = search(&w, &p, &["Progressive Hookshot", "Progressive Hookshot"]);
    assert!(region(&w, &long, "Water Temple River"));
    assert!(location(&w, &long, "Water Temple GS River"));
}

#[test]
fn forest_east_courtyard_is_reached_from_the_drained_well() {
    let d = Data::load().unwrap();
    let w = open(&d);
    let p = stripped(&w, &d, &["Song of Time"]);
    let bow = search(&w, &p, &["Bow"]);
    assert!(region(&w, &bow, "Forest Temple Block Push Room"));
    assert!(!region(&w, &bow, "Forest Temple NE Outdoors"));
    let song = search(&w, &p, &["Song of Time"]);
    assert!(region(&w, &song, "Forest Temple Well"));
    assert!(region(&w, &song, "Forest Temple NE Outdoors"));
}

#[test]
fn well_east_fake_wall_rooms_need_the_lens_but_no_small_key() {
    let d = Data::load().unwrap();
    let w = open(&d);
    let p = stripped(&w, &d, &["Small Key (Bottom of the Well)", "Lens of Truth"]);
    let blind = search(&w, &p, &[]);
    let lens = search(&w, &p, &["Lens of Truth"]);
    for name in ["Bottom of the Well Fire Keese Chest", "Bottom of the Well GS Like Like Cage"] {
        assert!(!location(&w, &blind, name), "{name}");
        assert!(location(&w, &lens, name), "{name}");
    }
}

#[test]
fn fire_boss_approach_needs_the_hammer_floor() {
    let d = Data::load().unwrap();
    let w = open(&d);
    let p = stripped(&w, &d, &["Megaton Hammer"]);
    let unarmed = search(&w, &p, &["Hover Boots", "Progressive Hookshot"]);
    assert!(region(&w, &unarmed, "Fire Temple Upper"));
    assert!(!region(&w, &unarmed, "Fire Temple Before Boss"));
    assert!(region(&w, &search(&w, &p, &["Megaton Hammer"]), "Fire Temple Before Boss"));
}

#[test]
fn fire_real_key_source_is_not_the_side_room_map() {
    let d = Data::load().unwrap();
    let w = open(&d);
    assert_eq!(d.vanilla_of("Fire Temple Boulder Maze Side Room Chest"), Some("Map (Fire Temple)"));
    assert_eq!(d.vanilla_of("Fire Temple Compass Chest"), Some("Small Key (Fire Temple)"));
    let p = vanilla_place(&w, &d).unwrap();
    let key = w.item("Small Key (Fire Temple)").unwrap();
    assert_eq!(w.real.iter().filter(|location| p.get(**location) == Some(key)).count(), 8);
    assert_eq!(p.get(w.loc("Fire Temple Compass Chest").unwrap()), Some(key));
    assert_ne!(p.get(w.loc("Fire Temple Boulder Maze Side Room Chest").unwrap()), Some(key));
    let strict = world_with(&d, &[("open_door_of_time", "open"), ("fire_key_layout", "shuffled")]).unwrap();
    let first = supplied(&strict, &d, &[], "Small Key (Fire Temple)", 4);
    assert!(location(&strict, &first, "Fire Temple Boulder Maze Side Room Chest"));
    assert!(!location(&strict, &first, "Fire Temple Compass Chest"));
    let later = supplied(&strict, &d, &[], "Small Key (Fire Temple)", 6);
    assert!(location(&strict, &later, "Fire Temple Compass Chest"));
}

#[test]
fn frozen_water_skull_name_keeps_the_existing_boss_key_passage_actor() {
    let d = Data::load().unwrap();
    let w = open(&d);
    let old_ap_name = w.loc("Water Temple GS Falling Platform Room").unwrap();
    assert_eq!(w.regions[w.locs[old_ap_name].region].name, "Water Temple North Basement");
    let old_local_name = w.loc("Water Temple GS Near Boss Key Chest").unwrap();
    assert_eq!(w.regions[w.locs[old_local_name].region].name, "Water Temple Cracked Wall");
}

#[test]
fn water_basement_pots_cannot_hold_a_key_needed_to_reach_them() {
    let d = Data::load().unwrap();
    let w = world_with(&d, &[("open_door_of_time", "open"), ("water_key_layout", "shuffled"),
                           (crate::pot_slice::remake::KEY, crate::pot_slice::remake::ON)]).unwrap();
    for name in ["Water Temple Dive Remake Pot 1", "Water Temple Dive Remake Pot 2"] {
        let id = w.loc(name).unwrap();
        assert_eq!(w.regions[w.locs[id].region].name, "Water Temple Central Pillar Basement");
        assert!(!location(&w, &supplied(&w, &d, &[], "Small Key (Water Temple)", 1), name));
        assert!(!location(&w, &supplied(&w, &d, &["Zeldas Lullaby"], "Small Key (Water Temple)", 4), name));
        assert!(location(&w, &supplied(&w, &d, &[], "Small Key (Water Temple)", 2), name));
    }
}

#[test]
fn shadow_five_key_doors_remain_in_order() {
    let d = Data::load().unwrap();
    let w = open(&d);
    for (count, name) in [(1, "Shadow Temple Huge Pit"), (2, "Shadow Temple Invisible Spikes"),
                          (3, "Shadow Temple Wind Tunnel"), (4, "Shadow Temple Boat"),
                          (5, "Shadow Temple Boss Key Chest")] {
        let before = supplied(&w, &d, &[], "Small Key (Shadow Temple)", count - 1);
        let after = supplied(&w, &d, &[], "Small Key (Shadow Temple)", count);
        let access = |result: &Search| match w.loc(name) {
            Some(id) => result.loc_access(id),
            None => region(&w, result, name),
        };
        assert!(!access(&before), "{name} opens before key {count}");
        assert!(access(&after), "{name} stays closed with key {count}");
    }
}

#[test]
fn unchanged_native_key_totals_hold_after_the_world_backport() {
    let d = Data::load().unwrap();
    let w = open(&d);
    let p = vanilla_place(&w, &d).unwrap();
    for (name, count) in [("Small Key (Forest Temple)", 5), ("Small Key (Fire Temple)", 8),
                          ("Small Key (Water Temple)", 4), ("Small Key (Shadow Temple)", 5),
                          ("Small Key (Bottom of the Well)", 2)] {
        let item = w.item(name).unwrap();
        assert_eq!(w.real.iter().filter(|location| p.get(**location) == Some(item)).count(), count, "{name}");
    }
}

#[test]
fn frozen_native_actor_names_keep_their_physical_regions() {
    let d = Data::load().unwrap();
    let w = open(&d);
    for (name, hash, at) in [
        ("Fire Temple Near Boss Chest", 3949488292768750868, "Fire Temple Big Lava Room"),
        ("Fire Temple Big Lava Room Lower Open Door Chest", 5634724236470386190, "Fire Temple Near Boss"),
    ] {
        assert_eq!(d.cat.by_name(name).unwrap().refs[0].hash, hash);
        assert_eq!(w.regions[w.locs[w.loc(name).unwrap()].region].name, at);
    }
    let skulls = crate::slice::skull_names::shared().unwrap();
    assert_eq!(skulls.spot("Water Temple GS Falling Platform Room").unwrap().hash, 186694424287048567);
    assert_eq!(skulls.spot("Forest Temple GS Level Island Courtyard").unwrap().hash, 2014780391754316762);
    assert_eq!(skulls.spot("Forest Temple GS Raised Island Courtyard").unwrap().hash, 10970805784153267902);
}

#[test]
fn supported_generation_profiles_remain_beatable_without_moving_fixed_fire_rewards() {
    use crate::settings::{Settings, Value};
    use crate::slice::generate::{generate_data, GenOpts};
    let d = Data::load().unwrap();
    let profiles = [
        ("default", vec![]),
        ("roaming", vec![("shuffle_smallkeys", Value::s("keysanity")), ("shuffle_bosskeys", Value::s("keysanity"))]),
        ("hybrid", vec![("shuffle_rewards", Value::s("supported")), ("shuffle_shops", Value::s("shuffle")),
                        ("shuffle_skulltulas", Value::s("matched")), ("plant_beans", Value::Bool(true)),
                        ("adult_trade_shuffle", Value::Bool(true))]),
        ("pots-entrances", vec![("shuffle_rewards", Value::s("supported")), ("shuffle_pots", Value::s("all")),
                                ("shuffle_crates", Value::s("all")), ("shuffle_entrances", Value::s("dungeons")),
                                ("bridge", Value::s("dungeons")), ("bridge_rewards", Value::Int(0))]),
    ];
    for (label, options) in profiles {
        let mut settings = Settings::default();
        for (key, value) in options {
            settings.set(key, value).unwrap();
        }
        for n in 0..2 {
            let generated = generate_data(&d, &settings, &format!("AP dungeon logic v2 {label} {n}"), &GenOpts::default()).unwrap();
            assert!(generated.spheres.iter().flatten().any(|(name, _)| name == "Ganon"), "{label} {n}");
            // These old native-builder sources stay unshuffled. Their corrected
            // fixed rewards affect the access proof, not the portable build.
            assert!(!generated.seed_file.placements.contains_key("Fire Temple Compass Chest"));
            assert!(!generated.seed_file.placements.contains_key("Fire Temple Boulder Maze Side Room Chest"));
        }
    }
}

#[test]
fn a_frozen_pre_fix_seed_still_decodes_and_roundtrips_unchanged() {
    use crate::settings::{seed::SeedFile, Settings};
    const LEGACY: &str = include_str!("../../../../data/pins/ap_dungeon_logic_v2/legacy_seed_file.json");
    let seed = SeedFile::parse(LEGACY).unwrap();
    assert_eq!(seed.seed, "default 0");
    assert_eq!(seed.placements.len(), 178);
    assert_eq!(seed.checksum(), "9fe5af16a5b70cc7671b75f5389931b56668ecffd7fec511ebff85a4b696f705");
    assert_eq!(SeedFile::parse(&seed.to_json().pretty()).unwrap(), seed);
    let settings = Settings::decode(&seed.settings_string).unwrap();
    assert!(settings.warnings.is_empty());
    crate::slice::support::plan(&settings.settings).unwrap();
}

#[test]
fn gerudo_valley_bridge_follows_the_card_instead_of_the_rescue_events() {
    use crate::rules::{eval, Age, Ctx};
    let d = Data::load().unwrap();
    let normal = open(&d);
    let override_bridge = world_with(&d, &[("gerudo_bridge_open", "true")]).unwrap();
    let open_fortress = world_with(&d, &[("gerudo_fortress", "open")]).unwrap();
    let rescues = ["Hideout 1 Torch Jail Carpenter", "Hideout 2 Torches Jail Carpenter",
                   "Hideout 3 Torches Jail Carpenter", "Hideout 4 Torches Jail Carpenter"];
    let accepts = |w: &World, name: &str, items: &[&str]| {
        let mut counts = vec![0; w.items.len()];
        for item in rescues.iter().chain(items.iter()) {
            counts[w.item(item).unwrap()] += 1;
        }
        let edge = w.exits.iter().find(|edge| edge.name == name).unwrap();
        let context = Ctx { cnt: &counts, age: Some(Age::Adult), tod: 0, region: edge.from, q: None };
        edge.rule.always || (!edge.rule.never && eval(&edge.rule.node, &context))
    };
    for name in ["Gerudo Valley -> GV Fortress Side", "GV Fortress Side -> Gerudo Valley"] {
        assert!(!accepts(&normal, name, &[]), "rescues alone opened {name}");
        assert!(accepts(&normal, name, &["Gerudo Membership Card"]), "card did not open {name}");
        assert!(accepts(&override_bridge, name, &[]), "bridge override did not open {name}");
        assert!(accepts(&open_fortress, name, &[]), "open fortress did not open {name}");
        assert!(accepts(&normal, name, &["Progressive Hookshot", "Progressive Hookshot"]), "Longshot did not open {name}");
        assert!(accepts(&normal, name, &["Epona", "Eponas Song", "Ocarina"]), "Epona did not open {name}");
    }
}
