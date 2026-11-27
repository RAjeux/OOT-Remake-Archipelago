//! The OOTRR nightly difficulty implementation for explicitly versioned AP
//! rooms. The original `difficulty` module remains the legacy seed contract.
pub mod ambush;
pub mod beamos;
pub mod fireballs;
pub mod gates;
pub mod hook;
pub mod hurt;
pub mod leevers;
pub mod mega_like;
pub mod backup;
pub mod battle_bgm;
pub mod bowling;
pub mod talon;
pub mod cucco;
pub mod drops;
pub mod dupes;
pub mod encounters;
pub mod extras;
pub mod ground;
pub mod horde;
pub mod fairy;
pub mod flows;
pub use crate::frost::elink;
pub mod fuses;
pub mod fx;
pub mod lottery;
pub mod protected;
pub mod minibosses;
pub mod minions;
pub mod regen;
pub mod respawn;
pub mod spawn;
pub mod stats;
pub mod surprises;
pub mod sizes;
pub mod swap;
pub mod target;
pub mod timers;
pub mod volvagia;
pub mod wake;

use std::fs;

use crate::error::Res;
use crate::qol::{edit_plain, edit_zs, Have};
use crate::romfs::Romfs;
use crate::sarc::{self, Entry};
use crate::staging::Out;
use crate::zs;

pub const HEALTH: &str = "enemy_health";
pub const DAMAGE: &str = "enemy_damage";
pub const HURT: &str = "damage_taken";
pub const SPEED: &str = "enemy_speed";
pub const NO_HEARTS: &str = "no_heart_drops";
pub const NO_FAIRIES: &str = "no_gossip_fairies";
pub const NO_AMMO: &str = "no_ammo_drops";
pub const LOSE_HEART: &str = "lose_heart_on_death";
pub const NO_BOTTLES: &str = "no_bottles_in_combat";
pub const NO_TARGET: &str = "no_z_targeting";
pub const NO_DUPES: &str = "no_dupe_items";
pub const MORE: &str = "more_enemies";
pub const RESPAWN: &str = "enemies_respawn_sooner";
pub const MINIBOSSES: &str = "boss_minibosses";
pub const REGEN: &str = "enemy_regen";
pub const MINIONS: &str = "boss_minions";
pub const BEAN_PITCH: &str = "bean_pitch";
pub const ZORA_AMBUSH: &str = "zora_ambush";
pub const FAIRY_HELPS: &str = "fairy_helps_enemies";
pub const BACKUP: &str = "enemy_backup";
pub const GATES: &str = "enemy_gates";
pub const ENCOUNTERS: &str = "special_encounters";
pub const CUCCO: &str = "cucco_revenge";
pub const FOREST: &str = "open_forest";
pub const ENTRANCES: &str = "shuffle_entrances";
pub const SPAWN_COMBO: &str = "enemy_spawn_combo";
pub const KAKARIKO: &str = "open_kakariko";
pub const BOWLING: &str = "unbreakable_bowling_grass";
pub const TALON: &str = "harder_talon_cuccos";
pub const FIREBALLS: &str = "fireball_storms";
pub const VOLVAGIA: &str = "volvagia_roams";
pub const MEGA_LIKE: &str = "mega_like_likes";
pub const FUSES: &str = "random_fuses";
pub const RANDOMIZER: &str = "enemy_randomizer";
pub const SIZES: &str = "enemy_sizes";
pub const SIZES_HEALTH: &str = "enemy_sizes_health";

pub const HEALTH_NUM: u16 = 110;
pub const DAMAGE_NUM: u16 = 111;
pub const HURT_NUM: u16 = 148;
pub const SPEED_NUM: u16 = 112;
pub const NO_HEARTS_NUM: u16 = 113;
pub const NO_FAIRIES_NUM: u16 = 114;
pub const NO_AMMO_NUM: u16 = 115;
pub const LOSE_HEART_NUM: u16 = 116;
pub const NO_BOTTLES_NUM: u16 = 117;
pub const NO_TARGET_NUM: u16 = 124;
pub const NO_DUPES_NUM: u16 = 122;
pub const MORE_NUM: u16 = 119;
pub const RESPAWN_NUM: u16 = 123;
pub const MINIBOSSES_NUM: u16 = 120;
pub const REGEN_NUM: u16 = 118;
pub const MINIONS_NUM: u16 = 121;
pub const BEAN_PITCH_NUM: u16 = 128;
pub const ZORA_AMBUSH_NUM: u16 = 127;
pub const FAIRY_HELPS_NUM: u16 = 125;
pub const BACKUP_NUM: u16 = 126;
pub const GATES_NUM: u16 = 129;
pub const ENCOUNTERS_NUM: u16 = 130;
pub const CUCCO_NUM: u16 = 131;
pub const SPAWN_COMBO_NUM: u16 = 132;
pub const BOWLING_NUM: u16 = 139;
pub const TALON_NUM: u16 = 155;
pub const FIREBALLS_NUM: u16 = 140;
pub const VOLVAGIA_NUM: u16 = 143;
pub const MEGA_LIKE_NUM: u16 = 144;
pub const FUSES_NUM: u16 = 151;
pub const RANDOMIZER_NUM: u16 = 150;
pub const SIZES_NUM: u16 = 145;
pub const SIZES_HEALTH_NUM: u16 = 146;

pub const NORMAL: i64 = 100;
pub const STAT_RANGE: (i64, i64) = (50, 500);
pub const SPEED_RANGE: (i64, i64) = (75, 200);
pub const STAT_STEP: i64 = 25;
pub const SPEED_STEP: i64 = 5;
pub const ACTOR_PACKS: &str = "Pack/Actor";
pub const MORE_RANGE: (i64, i64) = (100, 1000);
pub const MORE_STEP: i64 = 50;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Opts {
    pub health: i64,
    pub damage: i64,
    pub hurt: hurt::Hurt,
    pub speed: i64,
    pub no_hearts: bool,
    pub no_fairies: bool,
    pub no_ammo: bool,
    pub lose_heart: bool,
    pub no_bottles: bool,
    pub no_target: bool,
    pub no_dupes: bool,
    pub extra: i64,
    pub respawn: bool,
    pub minibosses: bool,
    pub regen: bool,
    pub minions: bool,
    pub fairy_helps: bool,
    pub backup: bool,
    pub gates: bool,
    pub encounters: bool,
    pub cucco: bool,
    pub bowling: bool,
    pub talon: bool,
    pub fireballs: bool,
    pub fuses: bool,
    pub spawn_combo: bool,
    pub volvagia: bool,
    pub mega_like: bool,
    pub randomizer: bool,
    pub sizes: sizes::Range,
    pub sized_health: bool,
    pub forest_open: bool,
    pub shops: bool,
    pub mido_gone: bool,
    pub entrances: gates::Shuffle,
    pub timers: i64,
}

impl Default for Opts {
    fn default() -> Opts {
        Opts { health: NORMAL, damage: NORMAL, hurt: hurt::Hurt::Normal, speed: NORMAL, no_hearts: false, no_fairies: false, no_ammo: false, lose_heart: false, no_bottles: false, no_target: false, no_dupes: false, extra: 0, respawn: false, minibosses: false, regen: false, minions: false, fairy_helps: false, backup: false, gates: false, encounters: false, cucco: false, bowling: false, talon: false, fireballs: false, spawn_combo: false, randomizer: false, sizes: sizes::Range::Off, sized_health: false, fuses: false, mega_like: false, volvagia: false, forest_open: false, shops: false, mido_gone: false, entrances: gates::Shuffle::Off, timers: NORMAL }
    }
}

fn times(pct: i64) -> String {
    let s: String = format!("{:.2}", pct as f64 / 100.0);
    s.trim_end_matches('0').trim_end_matches('.').to_string()
}

impl Opts {
    pub fn cut(&self) -> drops::Cut {
        drops::Cut { hearts: self.no_hearts, ammo: self.no_ammo }
    }

    pub fn packs(&self) -> bool {
        self.health != NORMAL || self.damage != NORMAL || self.hurt != hurt::Hurt::Normal || self.speed != NORMAL || self.cut().any() || self.no_target || self.no_bottles
    }

    pub fn gate_list(&self) -> Vec<gates::Gate> {
        if !self.gates {
            return Vec::new();
        }
        gates::GATES.iter().filter(|g| !gates::HELD.contains(&g.id) && gates::active(g, self.forest_open, self.mido_gone, self.entrances)).copied().collect()
    }

    pub fn gates(&self) -> bool {
        !self.gate_list().is_empty()
    }

    pub fn any(&self) -> bool {
        self.packs() || self.no_fairies || self.lose_heart || self.no_bottles || self.no_dupes || self.extra > 0 || self.respawn || self.minibosses || self.regen || self.minions || self.fairy_helps || self.backup || self.encounters || self.cucco || self.bowling || self.talon || self.fireballs || self.spawn_combo || self.randomizer || self.sizes.on() || self.fuses || self.mega_like || self.volvagia || self.timers != NORMAL || self.gates()
    }

    pub fn notes(&self) -> Vec<String> {
        let mut out: Vec<String> = Vec::new();
        if self.health != NORMAL {
            out.push(format!("Enemies and bosses have {} times their usual health, up to 99. Enemies that always go down to one scripted hit, like Deku Scrubs, are not changed.", times(self.health)));
        }
        if self.damage != NORMAL {
            out.push(format!("Enemies and their projectiles hit {} times as hard. Grabs, traps, lava and falls do their usual damage.", times(self.damage)));
        }
        if self.hurt != hurt::Hurt::Normal {
            out.push(hurt::note(self.hurt));
        }
        if self.speed != NORMAL {
            out.push(format!("Enemies are set to move and attack {} times as fast. Experimental: most enemies ignore it, and in our tests only Lizalfos clearly sped up.", times(self.speed)));
        }
        if self.regen {
            out.push("Enemies and bosses you leave alone heal. About 15 seconds after the last hit they get back one point of health every 5 seconds, up to their usual health.".to_string());
        }
        if self.backup {
            out.push("An ordinary enemy that fights you for 10 to 25 seconds calls in one weaker enemy at its side, once. Helpers never call anyone. Bosses, minibosses and Iron Knuckles never call.".to_string());
        }
        if self.no_hearts {
            out.push("Enemies, pots, grass and other random drops never give recovery hearts. Where the game would hand you a heart because you're low, you get a green rupee.".to_string());
        }
        if self.no_ammo {
            let shops: &str = if self.shops { " Shopsanity is on: a special deal can take the place of a shelf that sold arrows, bombs or seeds, and the logic does not check that any ammo can still be bought, so you may find a seed where the only arrows are in the shops you cannot afford or cannot reach." } else { "" };
            out.push(format!("Enemies, pots, grass and other random drops never give arrows, seeds, bombs, Deku Nuts or Deku Sticks, except where the game stocks a boss fight: the Gohma larvae and eggs, the pots before the boss doors, the Ganon castle rubble and the Poe Meg fight.{shops} Round 2 is not played in the game yet."));
        }
        if self.no_fairies {
            out.push("Playing a song at a gossip stone no longer brings out a fairy.".to_string());
        }
        if self.lose_heart {
            out.push(match flows::KEEP {
                flows::Keep::CountSave => "Each game over you continue from costs a heart container, down to three hearts. The game saves right after, so the loss stays. A bottled fairy that revives you costs nothing.".to_string(),
                flows::Keep::Count => "Each game over you continue from costs a heart container, down to three hearts. The loss lasts until you quit to the title screen. A bottled fairy that revives you costs nothing.".to_string(),
            });
        }
        if self.no_bottles {
            out.push("While the battle music plays or during a boss fight, Link shakes his head and puts the bottle away. A bottled fairy still revives you. Leevers and Moblins now start the battle music.".to_string());
        }
        if self.no_target {
            out.push("Enemies and bosses can't be locked on to. Aim assist, people, signs and everything else still work as usual.".to_string());
        }
        if self.no_dupes {
            out.push("A bottle won't take something another bottle already holds. This covers catching things, shops, Deku Scrubs, cows, Talon and the potion shops. A refused catch can still use up what you swung at. Bottle contents from chests and other items in the seed are not blocked.".to_string());
        }
        if self.extra > 0 {
            out.push(format!("About {} in 100 of the ordinary enemies that no door, chest or event depends on get a twin next to them.", self.extra.min(extras::FULL)));
        }
        if self.extra > horde::FROM {
            out.push(format!("More enemies at {}x: each area fills up toward that many times its usual enemies (at most {} per map), with fliers, water enemies and, from 5x, new kinds, small groups and the odd miniboss.", (self.extra + 100) as f32 / 100.0, horde::MAP_CAP));
        }
        if self.respawn {
            out.push("Most ordinary enemies come back when you leave their room or area and return. Bosses, minibosses, Gold Skulltulas, Poes and Deku Scrubs stay beaten. Experimental, untested in the game.".to_string());
        }
        if self.minibosses {
            out.push(format!("A strong enemy joins these boss fights when the boss appears and leaves when the boss is beaten: {}. Played with Gohma and Phantom Ganon; the other bosses are untested.", minibosses::covered()));
        }
        if self.minions {
            out.push(minions::NOTE.to_string());
        }
        if self.encounters {
            out.push(encounters::NOTE.to_string());
            out.push(ambush::NOTE.to_string());
            out.push(surprises::NOTE.to_string());
        }
        if self.cucco {
            out.push(cucco::NOTE.to_string());
        }
        if self.bowling {
            out.push(bowling::NOTE.to_string());
        }
        if self.talon {
            out.push(talon::NOTE.to_string());
        }
        if self.fireballs {
            out.push(fireballs::NOTE.to_string());
        }
        if self.fuses {
            out.push(fuses::NOTE.to_string());
        }
        if self.timers != NORMAL {
            out.push(timers::NOTE.to_string());
        }
        if self.spawn_combo {
            out.push(spawn::NOTE.to_string());
        }
        if self.volvagia {
            out.push(volvagia::NOTE.to_string());
        }
        if self.mega_like {
            out.push(mega_like::NOTE.to_string());
        }
        if self.randomizer {
            out.push(swap::NOTE.to_string());
        }
        if self.sizes.on() {
            out.push(sizes::NOTE.to_string());
            if self.sized_health {
                out.push(sizes::NOTE_HEALTH.to_string());
            }
        }
        if self.fairy_helps {
            out.push("When you use a bottled fairy, or one revives you, every enemy and boss that is awake heals to full health too.".to_string());
        }
        if self.gates {
            let names: Vec<&str> = self.gate_list().iter().map(|g| g.name).collect();
            if names.is_empty() {
                out.push("Enemies block the way is on, but no gate fits these entrance and forest settings, so nothing is blocked.".to_string());
            } else {
                out.push(format!("A barrier blocks the way at {} while its guards are alive, and drops when they are beaten. At Zora's River the guards are Lizalfos added for this. The barrier and guards come back whenever the area reloads.", names.join(", ")));
            }
            if self.gate_list().iter().any(|g| g.new_kind == gates::LEEVER_GIANT) {
                out.push(leevers::NOTE.to_string());
            }
            if let Some(n) = gates::shuffle_note(self.entrances) {
                out.push(n);
            }
        }
        out
    }
}

fn edit_entry(e: &Entry, o: &Opts) -> Res<Option<Vec<u8>>> {
    let n: &str = &e.name;
    if o.minions && n == minions::DODONGO_PARAM {
        return minions::babies(&e.data);
    }
    if o.health != NORMAL
        && let Some(s) = stats::stem(n, stats::LIFE_DIR, stats::LIFE_EXT)
    {
        return if stats::is_enemy(s) { stats::life(&e.data, o.health) } else { Ok(None) };
    }
    if o.damage != NORMAL
        && let Some(s) = stats::stem(n, stats::ATTACK_DIR, stats::ATTACK_EXT)
    {
        return if stats::is_enemy_attack(s) { stats::attack(&e.data, o.damage) } else { Ok(None) };
    }
    if n == hurt::FILE && o.hurt != hurt::Hurt::Normal {
        return hurt::edit(&e.data, o.hurt);
    }
    if o.hurt != hurt::Hurt::Normal && hurt::is_grab(n) {
        return hurt::grab(&e.data, o.hurt);
    }
    if o.speed != NORMAL
        && let Some(s) = stats::stem(n, stats::MOVE_DIR, stats::MOVE_EXT)
    {
        return if stats::is_enemy(s) { stats::movement(&e.data, o.speed) } else { Ok(None) };
    }
    if o.speed != NORMAL
        && let Some(s) = stats::stem(n, stats::PACE_DIR, stats::PACE_EXT)
    {
        return if stats::is_enemy(s) { stats::pace(&e.data, o.speed) } else { Ok(None) };
    }
    if n.starts_with(drops::DIR) {
        return drops::edit(&e.data, drops::for_table(n, o.cut()));
    }
    if o.no_target
        && let Some(s) = stats::stem(n, target::DIR, target::EXT)
    {
        return if target::is_foe(s) { target::edit(&e.data) } else { Ok(None) };
    }
    Ok(None)
}

pub fn edit_pack(raw: &[u8], o: &Opts) -> Res<Option<Vec<u8>>> {
    let mut es: Vec<Entry> = sarc::parse(raw)?;
    let mut hit: bool = false;
    for e in es.iter_mut() {
        if let Some(d) = edit_entry(e, o)? {
            e.data = d;
            hit = true;
        }
    }
    if o.no_bottles {
        for (n, d) in battle_bgm::edit(&es)? {
            if let Some(e) = es.iter_mut().find(|e| e.name == n) {
                e.data = d;
                hit = true;
            }
        }
    }
    if !hit {
        return Ok(None);
    }
    Ok(Some(sarc::write(&es)?))
}

fn pack_out(rf: &mut Romfs, have: Have, path: &str, o: &Opts) -> Res<Option<Out>> {
    let z: Vec<u8> = match have(path) {
        Some(b) => b,
        None => rf.read(path)?,
    };
    let id: Option<u32> = zs::dict_of(&z);
    let raw: Vec<u8> = rf.zs.decompress(&z)?;
    let Some(out) = edit_pack(&raw, o)? else {
        return Ok(None);
    };
    Ok(Some(Out { path: path.to_string(), old: raw.len(), new: out.len(), z: zs::compress_raw(&out, id)? }))
}

pub fn pack_files(rf: &Romfs, o: &Opts) -> Res<Vec<String>> {
    if !o.packs() {
        return Ok(if o.minions { vec![minions::DODONGO_PACK.to_string()] } else { Vec::new() });
    }
    let mut out: Vec<String> = rf.list(ACTOR_PACKS)?.into_iter().filter(|p| p.ends_with(".pack.zs")).collect();
    if o.cut().any() {
        out.push(drops::FOLIAGE.to_string());
    }
    out.sort();
    Ok(out)
}

pub fn merge(late: &mut Vec<Out>, outs: Vec<Out>) {
    for x in outs {
        match late.iter_mut().rev().find(|y| y.path == x.path) {
            Some(y) => {
                y.z = x.z;
                y.new = x.new;
            }
            None => late.push(x),
        }
    }
}

fn step(rf: &mut Romfs, outs: &mut Vec<Out>, have: Have, f: impl FnOnce(&mut Romfs, Have) -> Res<Vec<Out>>) -> Res<()> {
    let more: Vec<Out> = {
        let seen = |p: &str| -> Option<Vec<u8>> { outs.iter().find(|x| x.path == p).map(|x| x.z.clone()).or_else(|| have(p)) };
        f(rf, &seen)?
    };
    merge(outs, more);
    Ok(())
}

pub fn stage(rf: &mut Romfs, o: &Opts, have: Have, seed: &str) -> Res<Vec<Out>> {
    stage_noted(rf, o, have, seed, &mut Vec::new())
}

pub fn stage_noted(rf: &mut Romfs, o: &Opts, have: Have, seed: &str, notes: &mut Vec<String>) -> Res<Vec<Out>> {
    stage_noted_protected(rf, o, have, seed, notes, &protected::Sources::new())
}

pub fn stage_noted_protected(rf: &mut Romfs, o: &Opts, have: Have, seed: &str,
                             notes: &mut Vec<String>, protected: &protected::Sources) -> Res<Vec<Out>> {
    let mut outs: Vec<Out> = Vec::new();
    for f in pack_files(rf, o)? {
        if let Some(x) = pack_out(rf, have, &f, o)? {
            outs.push(x);
        }
    }
    if o.cut().any() {
        let raw: Vec<u8> = match have(lottery::FILE) {
            Some(b) => b,
            None => rf.read(lottery::FILE)?,
        };
        if let Some(out) = lottery::edit(&raw, o.cut())? {
            outs.push(Out { path: lottery::FILE.to_string(), old: raw.len(), new: out.len(), z: out });
        }
    }
    if o.regen {
        step(rf, &mut outs, have, |rf, have| Ok(regen::stage(rf, have, ACTOR_PACKS)?.1))?;
    }
    if o.fairy_helps {
        step(rf, &mut outs, have, |rf, have| Ok(fairy::stage(rf, have, ACTOR_PACKS)?.1))?;
    }
    if o.regen || o.fairy_helps {
        step(rf, &mut outs, have, fx::link_stage)?;
    } else if o.mega_like {
        step(rf, &mut outs, have, |rf, have| fx::link_stage_for(rf, have, vec![mega_like::BASE.to_string()]))?;
    }
    if o.backup {
        step(rf, &mut outs, have, |rf, have| Ok(backup::stage(rf, have, ACTOR_PACKS)?.1))?;
    }
    if o.no_fairies {
        step(rf, &mut outs, have, |rf, have| Ok(vec![edit_zs(rf, have, flows::GOSSIP_FILE, flows::no_gossip)?]))?;
    }
    if o.lose_heart {
        step(rf, &mut outs, have, |rf, have| Ok(vec![edit_zs(rf, have, flows::OVER_FILE, flows::lose_heart)?]))?;
        step(rf, &mut outs, have, |rf, have| Ok(vec![edit_zs(rf, have, flows::BOOT_FILE, flows::lose_heart_boot)?]))?;
    }
    if o.fairy_helps {
        step(rf, &mut outs, have, |rf, have| Ok(vec![edit_zs(rf, have, flows::OVER_FILE, |raw| flows::fairy_used(raw, flows::OVER_FLOW, flows::REVIVE))?]))?;
        step(rf, &mut outs, have, |rf, have| Ok(vec![edit_zs(rf, have, flows::OUT_FAIRY_FILE, |raw| flows::fairy_used(raw, flows::OUT_FAIRY_FLOW, flows::OUT_FAIRY))?]))?;
    }
    if o.no_bottles {
        for (file, name) in flows::BOTTLE_FLOWS {
            step(rf, &mut outs, have, |rf, have| Ok(vec![edit_zs(rf, have, file, |raw| flows::no_bottles(raw, name))?]))?;
        }
    }
    if o.no_dupes {
        step(rf, &mut outs, have, |rf, have| Ok(vec![edit_zs(rf, have, dupes::CATCH_FILE, |raw| dupes::entries(raw, dupes::CATCH_FLOW, &dupes::CATCH_ENTRIES, dupes::Ending::Catch))?]))?;
        step(rf, &mut outs, have, |rf, have| Ok(vec![edit_zs(rf, have, dupes::GIVE_FILE, |raw| dupes::entries(raw, dupes::GIVE_FLOW, &dupes::GIVE_ENTRIES, dupes::Ending::Give))?]))?;
        step(rf, &mut outs, have, |rf, have| Ok(vec![edit_zs(rf, have, dupes::SHOP_FILE, |raw| dupes::fronts(raw, dupes::SHOP_FLOW, &dupes::goods()))?]))?;
        for (file, name, item) in dupes::SELLERS {
            step(rf, &mut outs, have, |rf, have| Ok(vec![edit_zs(rf, have, file, |raw| dupes::fronts(raw, name, &[(None, item)]))?]))?;
        }
    }
    if o.respawn {
        for f in respawn::files() {
            step(rf, &mut outs, have, |rf, have| Ok(vec![edit_plain(rf, have, &f, respawn::always)?]))?;
        }
    }
    if o.extra > 0 {
        step(rf, &mut outs, have, |rf, have| extras::stage(rf, have, seed, o.extra.min(extras::FULL)))?;
    }
    if o.minibosses {
        for s in &minibosses::SPOTS {
            step(rf, &mut outs, have, |rf, have| Ok(minibosses::one(rf, have, s)?.to_vec()))?;
        }
    }
    if o.minions {
        step(rf, &mut outs, have, minions::stage)?;
    }
    if o.encounters {
        step(rf, &mut outs, have, ambush::stage)?;
        step(rf, &mut outs, have, encounters::stage)?;
        step(rf, &mut outs, have, |rf, have| surprises::stage_protected(rf, have, seed, protected))?;
    }
    if o.cucco {
        step(rf, &mut outs, have, cucco::stage)?;
    }
    if o.bowling {
        step(rf, &mut outs, have, bowling::stage)?;
    }
    if o.talon {
        step(rf, &mut outs, have, talon::stage)?;
    }
    if o.fireballs {
        step(rf, &mut outs, have, fireballs::stage)?;
    }
    if o.fuses {
        step(rf, &mut outs, have, fuses::stage)?;
    }
    if o.timers != NORMAL {
        step(rf, &mut outs, have, |rf, have| timers::stage(rf, have, o.timers))?;
    }
    if o.spawn_combo {
        step(rf, &mut outs, have, spawn::stage)?;
    }
    let gl: Vec<gates::Gate> = o.gate_list();
    if !gl.is_empty() {
        step(rf, &mut outs, have, |rf, have| gates::stage(rf, have, &gl))?;
    }
    if o.randomizer {
        step(rf, &mut outs, have, |rf, have| swap::stage_protected(rf, have, seed, notes, protected))?;
    }
    if o.extra > horde::FROM {
        step(rf, &mut outs, have, |rf, have| horde::stage(rf, have, seed, o.extra, o.encounters))?;
    }
    if o.sizes.on() {
        step(rf, &mut outs, have, |rf, have| sizes::stage(rf, have, seed, o.sizes, o.sized_health, notes))?;
    }
    Ok(outs)
}

pub fn worked(rf: &mut Romfs, pk: &crate::modpack::Pack, o: &Opts, seed: &str, late: &mut Vec<Out>) -> Res<Vec<String>> {
    let mut notes: Vec<String> = Vec::new();
    if !o.any() {
        return Ok(notes);
    }
    let root: std::path::PathBuf = pk.work.join("romfs");
    let outs: Vec<Out> = {
        let have = |p: &str| -> Option<Vec<u8>> { late.iter().rev().find(|x| x.path == p).map(|x| x.z.clone()).or_else(|| fs::read(p.split('/').fold(root.clone(), |a, s| a.join(s))).ok()) };
        stage_noted(rf, o, &have, seed, &mut notes)?
    };
    merge(late, outs);
    Ok(notes)
}

/// Decode the shared AP feature schema, never the frozen builder wire schema.
pub fn read_features(features: &crate::json::Json) -> Res<Opts> {
    use crate::error::Error;
    use crate::json::Json;
    if features.get("schema").and_then(Json::as_i64) != Some(1) { return Ok(Opts::default()); }
    let settings = features.get("settings").filter(|s| s.as_obj().is_some())
        .ok_or(Error::Format("difficulty features: missing settings"))?;
    let flag = |id: &str| match settings.get(id) {
        None => Ok(false), Some(Json::Bool(v)) => Ok(*v),
        _ => Err(Error::Msg(format!("difficulty features: {id} must be a boolean"))),
    };
    let number = |id: &str, default: i64, low: i64, high: i64, step: i64| -> Res<i64> {
        let value = match settings.get(id) {
            None => default,
            Some(v) => v.as_i64().ok_or_else(|| Error::Msg(format!("difficulty features: {id} must be an integer")))?,
        };
        if value < low || value > high || (value - low) % step != 0 {
            return Err(Error::Msg(format!("difficulty features: {id} is outside its supported range")));
        }
        Ok(value)
    };
    let choice = |id: &str, default: &str, choices: &[&str]| -> Res<String> {
        let value = match settings.get(id) {
            None => default,
            Some(v) => v.as_str().ok_or_else(|| Error::Msg(format!("difficulty features: {id} must be a choice")))?,
        };
        if !choices.contains(&value) {
            return Err(Error::Msg(format!("difficulty features: invalid {id} choice")));
        }
        Ok(value.to_string())
    };
    let hurt = choice(HURT, "normal", &["normal", "double", "quadruple", "one_hit"])?;
    let sizes = choice(SIZES, "off", &["off", "mild", "wild"])?;
    let timers = choice(timers::SETTING, "off", &["off", "three_quarters", "half"])?;
    // Keep the source for continued research, but do not offer upstream's
    // known ineffective scaling or roaming-boss softlock to AP players.
    if sizes != "off" || flag(SIZES_HEALTH)? {
        return Err(Error::Format("Random enemy sizes are unavailable: the native game does not reliably apply their visual scale."));
    }
    if flag(VOLVAGIA)? {
        return Err(Error::Format("Roaming Volvagia is unavailable: upstream reports a softlock before the enemy dies."));
    }
    let native = features.get("native_settings");
    let native_choice = |id: &str| native.and_then(|j| j.get(id)).and_then(Json::as_str);
    let forest_open = native_choice(FOREST) == Some("open");
    let o = Opts {
        health: number(HEALTH, NORMAL, 50, 500, 25)?,
        damage: number(DAMAGE, NORMAL, 50, 500, 25)?,
        speed: number(SPEED, NORMAL, 75, 200, 5)?,
        extra: number(MORE, NORMAL, 100, 1000, 50)? - NORMAL,
        hurt: hurt::Hurt::from_setting(&hurt),
        sizes: sizes::Range::from_setting(&sizes),
        timers: timers::percent(&timers).unwrap_or(NORMAL),
        no_hearts: flag(NO_HEARTS)?, no_fairies: flag(NO_FAIRIES)?, no_ammo: flag(NO_AMMO)?,
        lose_heart: flag(LOSE_HEART)?, no_bottles: flag(NO_BOTTLES)?, no_target: flag(NO_TARGET)?,
        no_dupes: flag(NO_DUPES)?, respawn: flag(RESPAWN)?, minibosses: flag(MINIBOSSES)?,
        regen: flag(REGEN)?, minions: flag(MINIONS)?, fairy_helps: flag(FAIRY_HELPS)?,
        backup: flag(BACKUP)?, gates: flag(GATES)?, cucco: flag(CUCCO)?, bowling: flag(BOWLING)?,
        talon: flag(TALON)?, fireballs: flag(FIREBALLS)?, fuses: flag(FUSES)?,
        spawn_combo: flag(SPAWN_COMBO)?, randomizer: flag(RANDOMIZER)?,
        sized_health: flag(SIZES_HEALTH)?, mega_like: flag(MEGA_LIKE)?, volvagia: flag(VOLVAGIA)?,
        forest_open, mido_gone: forest_open && native_choice(KAKARIKO) == Some("open"),
        entrances: gates::Shuffle::from_setting(native_choice(ENTRANCES).unwrap_or("off")),
        shops: native_choice(crate::shops::plan::SETTING).is_some_and(|mode| mode != "off"),
        ..Default::default()
    };
    Ok(Opts { encounters: o.extra > 0, ..o })
}

fn staged_source(outs: &[Out], work: &std::path::Path, path: &str) -> Option<Vec<u8>> {
    outs.iter().rev().find(|o| o.path == path).map(|o| o.z.clone())
        .or_else(|| fs::read(work.join(path)).ok())
}

/// Apply modern difficulty once, reading earlier AP/QOL edits from the staged
/// overlay and reserving every newly cloned actor's resource allocations.
pub fn stage_features(rf: &mut Romfs, outs: &mut Vec<Out>, work: &std::path::Path,
                      features: &crate::json::Json, table: &mut crate::rsizetable::Rst) -> Res<Vec<String>> {
    use crate::error::Error;
    use crate::json::Json;
    let options = read_features(features)?;
    let compatibility_flag = |id: &str| -> Res<bool> {
        match features.get("settings").and_then(|s| s.get(id)) {
            None => Ok(false), Some(Json::Bool(v)) => Ok(*v),
            _ => Err(Error::Msg(format!("difficulty features: {id} must be a boolean"))),
        }
    };
    let bean_pitch = compatibility_flag(BEAN_PITCH)?;
    let zora_ambush = compatibility_flag(ZORA_AMBUSH)? && !options.encounters;
    if !options.any() && !bean_pitch && !zora_ambush { return Ok(Vec::new()); }
    let seed = features.get("seed").and_then(Json::as_str)
        .filter(|s| !s.is_empty()).ok_or(Error::Format("difficulty features: missing room seed"))?;
    let protected = protected::read(features, options.randomizer || options.encounters)?;
    let before = { let have = |path: &str| staged_source(outs, work, path);
        protected::snapshot(rf, &have, &protected)? };
    let mut notes = Vec::new();
    let changed = {
        let have = |path: &str| staged_source(outs, work, path);
        stage_noted_protected(rf, &options, &have, seed, &mut notes, &protected)?
    };
    merge(outs, changed);
    if bean_pitch || zora_ambush {
        let legacy = crate::difficulty::Opts { bean_pitch, zora_ambush, ..Default::default() };
        let compatibility = {
            let have = |path: &str| staged_source(outs, work, path);
            crate::difficulty::stage(rf, &legacy, &have, seed)?
        };
        merge(outs, compatibility);
        if bean_pitch {
            for archive in crate::hints::languages(rf)? {
                crate::staging::edit_staged(rf, outs, work, &archive, true,
                    |raw| crate::difficulty::bean::localize_text(raw, &archive))?;
            }
        }
    }
    if options.backup { backup::size(rf, table)?; }
    if options.gate_list().iter().any(|g| g.new_kind == gates::LEEVER_GIANT) {
        let made = { let have = |path: &str| staged_source(outs, work, path);
            leevers::stage(rf, &have, table, &[leevers::SMALL_CLASS, leevers::GIANT_CLASS])? };
        leevers::sized(rf, table, &made)?;
        merge(outs, made.outs);
    }
    if options.encounters {
        let made = { let have = |path: &str| staged_source(outs, work, path);
            beamos::stage(rf, &have, table)? };
        leevers::sized(rf, table, &made)?;
        merge(outs, made.outs);
    }
    if options.volvagia {
        let made = { let have = |path: &str| staged_source(outs, work, path);
            volvagia::stage(rf, &have, table, &volvagia::shape())? };
        volvagia::sized(rf, table, &made)?;
        notes.extend(made.lines);
        merge(outs, made.outs);
    }
    if options.mega_like {
        let made = { let have = |path: &str| staged_source(outs, work, path);
            mega_like::stage(rf, &have, table)? };
        mega_like::sized(rf, table, &made)?;
        notes.extend(made.lines);
        merge(outs, made.outs);
    }
    if options.sizes.on() && options.sized_health {
        let mut classes = sizes::classes_in(rf, work)?;
        for out in outs.iter().filter(|o| o.path.starts_with("Banc/") && o.path.ends_with(".bcett.byml.zs")) {
            classes.extend(sizes::used(&rf.zs.decompress(&out.z)?));
        }
        let made = { let have = |path: &str| staged_source(outs, work, path);
            sizes::build(rf, &have, table, &classes)? };
        leevers::sized(rf, table, &made)?;
        merge(outs, made.outs);
    }
    let have = |path: &str| staged_source(outs, work, path);
    protected::unchanged(rf, &have, &before)?;
    Ok(notes)
}

#[cfg(test)]
mod feature_tests {
    use super::*;
    use crate::json::Json;

    #[test]
    fn old_rooms_and_new_default_rooms_do_not_apply_difficulty() {
        assert_eq!(read_features(&Json::obj()).unwrap(), Opts::default());
        let value = Json::obj().with("schema", 1_i64.into()).with("settings", Json::obj());
        assert_eq!(read_features(&value).unwrap(), Opts::default());
        let active = value.with("settings", Json::obj().with("enemy_health", 200_i64.into())
            .with("damage_taken", "quadruple".into()).with("shorter_timers", "half".into()));
        let options = read_features(&active).unwrap();
        assert_eq!(options.health, 200);
        assert_eq!(options.hurt, hurt::Hurt::Quadruple);
        assert_eq!(options.timers, 50);
    }

    #[test]
    fn invalid_feature_values_are_rejected_before_preparation() {
        for settings in [Json::obj().with("enemy_health", 201_i64.into()),
            Json::obj().with("fireball_storms", "yes".into()),
            Json::obj().with("enemy_sizes", "huge".into())] {
            let value = Json::obj().with("schema", 1_i64.into()).with("settings", settings);
            assert!(read_features(&value).is_err());
        }
        for settings in [Json::obj().with("enemy_sizes", "mild".into()),
            Json::obj().with("enemy_sizes_health", true.into()),
            Json::obj().with("volvagia_roams", true.into())] {
            let value = Json::obj().with("schema", 1_i64.into()).with("settings", settings);
            assert!(read_features(&value).is_err());
        }
    }

    #[test]
    fn the_selected_factor_is_applied_once_to_native_resources() {
        let Some(root) = std::env::var_os("OOTRR_ROMFS").map(std::path::PathBuf::from) else { return };
        let mut rf = Romfs::open(&root).unwrap();
        let raw = rf.read_zs("Pack/Actor/Enemy_Stalfos.pack.zs").unwrap();
        let value = Json::obj().with("schema", 1_i64.into()).with("settings",
            Json::obj().with("enemy_health", 200_i64.into()));
        let opts = read_features(&value).unwrap();
        let once = edit_pack(&raw, &opts).unwrap().unwrap();
        let before = sarc::parse(&raw).unwrap();
        let after = sarc::parse(&once).unwrap();
        let names: Vec<_> = before.iter().filter(|e| stats::stem(&e.name, stats::LIFE_DIR, stats::LIFE_EXT).is_some()).collect();
        assert!(!names.is_empty());
        for original in names {
            let expected = stats::life(&original.data, 200).unwrap();
            if let Some(expected) = expected {
                assert_eq!(sarc::get(&after, &original.name).unwrap().data, expected);
            }
        }
    }

    #[test]
    fn modern_difficulty_stages_supported_combinations_without_writing_game_files() {
        let Some(root) = std::env::var_os("OOTRR_ROMFS").map(std::path::PathBuf::from) else { return };
        if !root.join("Pack/ZsDic.pack.zs").is_file() { return; }
        let mut settings = Json::obj().with(HEALTH, 200_i64.into()).with(DAMAGE, 150_i64.into())
            .with(SPEED, 125_i64.into()).with(MORE, 150_i64.into())
            .with(HURT, "double".into()).with(timers::SETTING, "half".into());
        for key in [NO_HEARTS, NO_FAIRIES, NO_AMMO, LOSE_HEART, NO_BOTTLES, NO_TARGET,
            NO_DUPES, RESPAWN, MINIBOSSES, REGEN, MINIONS, FAIRY_HELPS, BACKUP, GATES,
            CUCCO, BOWLING, TALON, FIREBALLS, FUSES, SPAWN_COMBO, RANDOMIZER, MEGA_LIKE] {
            settings = settings.with(key, true.into());
        }
        let features = Json::obj().with("schema", 1_i64.into()).with("settings", settings)
            .with("seed", "AP-native-difficulty-resource-smoke".into())
            .with("protected_sources", protected::network_catalogue())
            .with("native_settings", Json::obj().with(FOREST, "closed".into())
                .with(KAKARIKO, "closed".into()).with(ENTRANCES, "off".into()));
        let mut rf = Romfs::open(&root).unwrap();
        let mut outs = Vec::new();
        let mut table = crate::rsizetable::load(&mut rf).unwrap();
        let notes = stage_features(&mut rf, &mut outs, std::path::Path::new("no-difficulty-overlay"), &features, &mut table).unwrap();
        let source_ids = protected::read(&features, true).unwrap();
        let protected_count: usize = source_ids.values().map(|ids| ids.len()).sum();
        assert!(protected_count >= 1000, "the complete AP source catalogue must be exercised");
        eprintln!("Protected {protected_count} AP actor variants in {} resource files through all supported difficulty features", source_ids.len());
        assert!(!notes.is_empty());
        assert!(!outs.is_empty());
        let mut paths = std::collections::BTreeSet::new();
        for out in &outs {
            assert!(paths.insert(&out.path));
            assert!(out.new > 0);
            if out.old == 0 && out.path.ends_with(".pack.zs") {
                assert!(table.get(&out.path).is_some());
            } else { crate::staging::grow_out(&mut rf, &mut table, out).unwrap(); }
        }
        assert!(outs.iter().any(|o| o.path == mega_like::pack_of(mega_like::CLASS)));
    }
}
