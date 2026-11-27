use crate::bfevfl::flow::NONE;
use crate::bfevfl::{Bf, Cont, Entry, Event, Flow, Kind, Val};
use crate::byml::{Byml, Node};
use crate::chest_slot::LIST;
use crate::error::{Error, Res};
use crate::flags::hash_name;
use crate::msbt::{self, Msbt};
use crate::romfs::Romfs;
use crate::sarc;
use crate::staging::Out;

pub const MENU_PACK: &str = "Pack/Bootup.Nin_Ounce_NVN2.pack.zs";
pub const MENU_FILE: &str = "Game/UI/ChallengeMenu/ChallengeMenuTable/ChallengeMenuTable.game__ui__ChallengeMenuTable.bgyml";
pub const TABLE: &str = "RSDB/Challenge.Product.111.rstbl.byml.zs";
pub const MENU_OPEN: &str = "UI_IsFinishChallengeMenuOpenEvent";
pub const PARENT: &str = "OOTRR_DungeonKeys";
pub const BOOT_FLOW: &str = "DefaultBootEvent";
pub const UPDATE: &str = "OOTRRKeyUpdate";
const ROW_ID: &str = "__RowId";
const TEMPLATE_ROW: &str = "Work/Challenge/SubEvent_GetMelodySun.game__challenge__Challenge.gyml";
const TEMPLATE_FLAG: &str = "Step_SubEvent_GetMelodySun";
const TEMPLATE_TEXT: &str = "ChallengeMsg/Info_Meet_DekuTree.msbt";
const EXP_TEMPLATE: &str = "SageOfForest_IsCompleted_Exp";
const ANY_FLAG: &str = "IsGet.Weapon_Sword_Kokiri";
const ALWAYS: &str = "OOTRR_Keys_Always_Exp";
const DESCRIPTION: &str = "Total keys earned for this location.";
const SUMMARY: &str = "Small Keys and Boss Keys for each dungeon.";
const HEADING: &str = "Keys";
const MAIN: u32 = 460_120_899;
const DROPPED: [&str; 6] = ["DependFlagName", "GameSafetySetting", "RequestActor", "RequestLocation", "IsCompleteTarget", "IsListAdventureLog"];
const PARENT_PANEL: &str = "DoorOfTime";
const CHILD_PANEL: &str = "Get_StoneOfFire";
const OURS: &str = "OOTRR_";
const QUIET: &str = "IsNotChangeAdventureLog";
const STEP: &str = "Tracking";
const PREFIX: &str = "OOTRRKeys";
const CHECKLIST_KEYS: [&str; 3] = ["NextActionContent", "UseNextActionContentStep", "IsDisplayGameDataFalse"];
const OP_BOOL: u64 = 0;
const OP_OR: u64 = 4;
const OP_NOT: u64 = 5;

pub struct Dungeon {
    pub data: &'static str,
    pub title: &'static str,
    pub logic: &'static str,
    pub boss: bool,
}

const fn dg(data: &'static str, title: &'static str, logic: &'static str, boss: bool) -> Dungeon {
    Dungeon { data, title, logic, boss }
}

pub const DUNGEONS: [Dungeon; 8] = [
    dg("ForestTemple", "Forest Temple", "Forest Temple", true),
    dg("FireTemple", "Fire Temple", "Fire Temple", true),
    dg("WaterTemple", "Water Temple", "Water Temple", true),
    dg("ShadowTemple", "Shadow Temple", "Shadow Temple", true),
    dg("SpiritTemple", "Spirit Temple", "Spirit Temple", true),
    dg("BottomOfTheWell", "Bottom of the Well", "Bottom of the Well", false),
    dg("GerudoTrainingGround", "Gerudo Proving Grounds", "Gerudo Training Ground", false),
    dg("InsideGanonCastle", "Ganon's Castle", "Ganons Castle", true),
];

#[derive(Clone, Debug, Default)]
pub struct Plan {
    pub caps: Vec<u32>,
}

pub fn start_ops() -> crate::start_state::Ops {
    crate::start_state::Ops { flags: vec![(MENU_OPEN.to_string(), true)], ..Default::default() }
}

fn no_boss(dn: &Dungeon) -> String {
    format!("OOTRR_Keys_{}_NoBoss_Exp", dn.data)
}

fn checklist(dn: &Dungeon) -> Vec<String> {
    let mut v: Vec<String> = vec![ALWAYS.to_string()];
    if dn.boss {
        v.push(key_flag(dn, "IsGetBossKey"));
        v.push(no_boss(dn));
    }
    v
}

pub fn child_id(dn: &Dungeon) -> String {
    format!("OOTRR_Keys_{}", dn.data)
}

fn key_flag(dn: &Dungeon, member: &str) -> String {
    crate::dungeon_credit::flag(dn.data, member)
}

fn number_tag(name: &str) -> Res<String> {
    let n: u16 = u16::try_from(name.len()).map_err(|_| Error::Format("key log: flag name too long"))?;
    let mut hex: String = String::new();
    for b in n.to_le_bytes().into_iter().chain(name.bytes()).chain([0xFF, 0xFF, 0x00]) {
        hex.push_str(&format!("{b:02x}"));
    }
    Ok(format!("{{2.1:{hex}}}"))
}

pub fn plan(caps: &[u32]) -> Res<Plan> {
    // The integration supplies the room's final AP roster, including keys in
    // other games. The donor seed's placements are not the final multiworld.
    if caps.len() != DUNGEONS.len() || caps.iter().any(|n| *n > i32::MAX as u32) {
        return Err(Error::Format("key log: invalid room dungeon key totals"));
    }
    Ok(Plan { caps: caps.to_vec() })
}

pub fn read_flags() -> Vec<String> {
    let mut v: Vec<String> = vec![ANY_FLAG.to_string()];
    for dn in &DUNGEONS {
        v.push(key_flag(dn, "SmallKeyTotalNum"));
        v.push(key_flag(dn, "SmallKeyNum"));
        if dn.boss {
            v.push(key_flag(dn, "IsGetBossKey"));
        }
    }
    v
}

struct Quest {
    id: String,
    texts: Vec<(String, String)>,
}

fn quests(p: &Plan) -> Res<Vec<Quest>> {
    let mut v: Vec<Quest> = vec![Quest {
        id: PARENT.to_string(),
        texts: vec![
            ("Name".to_string(), "Dungeon Keys".to_string()),
            ("Ready".to_string(), SUMMARY.to_string()),
            ("Ready_NextAction".to_string(), HEADING.to_string()),
            (STEP.to_string(), SUMMARY.to_string()),
            (format!("{STEP}_NextAction"), HEADING.to_string()),
            ("Complete".to_string(), SUMMARY.to_string()),
        ],
    }];
    for (dn, cap) in DUNGEONS.iter().zip(&p.caps) {
        let mut texts: Vec<(String, String)> = vec![
            ("Name".to_string(), dn.title.to_string()),
            ("Ready".to_string(), DESCRIPTION.to_string()),
            ("Ready_NextAction".to_string(), HEADING.to_string()),
            (STEP.to_string(), DESCRIPTION.to_string()),
            (format!("{STEP}_NextAction"), HEADING.to_string()),
            (format!("{STEP}_NextActionContent_00"), format!("Small Keys: {} ({}/{cap} Found)", number_tag(&key_flag(dn, "SmallKeyNum"))?, number_tag(&key_flag(dn, "SmallKeyTotalNum"))?)),
            ("Complete".to_string(), DESCRIPTION.to_string()),
        ];
        if dn.boss {
            texts.push((format!("{STEP}_NextActionContent_01"), "Boss Key: 1/1".to_string()));
            texts.push((format!("{STEP}_NextActionContent_02"), "Boss Key: 0/1".to_string()));
        }
        v.push(Quest { id: child_id(dn), texts });
    }
    Ok(v)
}

fn ids() -> Vec<String> {
    std::iter::once(PARENT.to_string()).chain(DUNGEONS.iter().map(child_id)).collect()
}

pub fn row_id(q: &str) -> String {
    format!("Work/Challenge/{q}.game__challenge__Challenge.gyml")
}

pub fn flag(q: &str) -> String {
    format!("Step_{q}")
}

pub fn text_file(q: &str) -> String {
    format!("ChallengeMsg/Info_{q}.msbt")
}

fn id_of(r: &Node) -> &str {
    r.get(ROW_ID).and_then(Node::as_str).unwrap_or("")
}

fn hash_of(r: &Node) -> Option<u32> {
    match r.get("Hash") {
        Some(Node::U32(h)) => Some(*h),
        _ => None,
    }
}

pub fn edit_table(y: &mut Byml) -> Res<usize> {
    let rows: &mut Vec<Node> = y.root.as_arr_mut().ok_or(Error::Format("key log: the quest table is not a list"))?;
    if rows.iter().any(|r| id_of(r) == row_id(PARENT)) {
        return Err(Error::Format("key log: the quest table already has the key quests"));
    }
    let base: Node = rows.iter().find(|r| id_of(r) == TEMPLATE_ROW).cloned().ok_or(Error::Format("key log: no template quest row"))?;
    let step: Node = base.get("Steps").and_then(Node::as_arr).and_then(|s| s.first()).cloned().ok_or(Error::Format("key log: the template quest has no steps"))?;
    let qs: Vec<String> = ids();
    for q in &qs {
        let mut r: Node = base.clone();
        for k in DROPPED {
            r.remove(k);
        }
        r.set(ROW_ID, Node::Str(row_id(q)));
        r.set("Category", Node::U32(MAIN));
        let steps: Vec<Node> = ["Ready", STEP]
            .iter()
            .map(|s| {
                let mut x: Node = step.clone();
                x.set("Name", Node::Str((*s).to_string()));
                x
            })
            .collect();
        r.set("Steps", Node::Arr(steps));
        rows.push(r);
    }
    Ok(qs.len())
}

/// The game pops a "next objective" card each time a quest step moves on, unless the step is
/// marked as not changing the adventure log (minigame and in-dungeon steps already are). Threads of
/// Time no longer lists the game's quests, so every game step gets the mark; our key quests keep
/// theirs off, their menu text follows the step and their requests already skip the card.
pub fn quiet_steps(y: &mut Byml) -> Res<usize> {
    let rows: &mut Vec<Node> = y.root.as_arr_mut().ok_or(Error::Format("key log: the quest table is not a list"))?;
    let ours: String = format!("Work/Challenge/{OURS}");
    let mut seen: usize = 0;
    let mut n: usize = 0;
    for r in rows.iter_mut().filter(|r| !id_of(r).starts_with(&ours)) {
        let Some(steps) = r.get_mut("Steps").and_then(Node::as_arr_mut) else { continue };
        for st in steps.iter_mut() {
            match st.get(QUIET) {
                Some(Node::Bool(true)) => seen += 1,
                Some(Node::Bool(false)) => {
                    st.set(QUIET, Node::Bool(true));
                    n += 1;
                }
                _ => return Err(Error::Format("key log: a quest step has no adventure log mark, the game files differ")),
            }
        }
    }
    if seen + n == 0 {
        return Err(Error::Format("key log: the quest table has no steps"));
    }
    Ok(n)
}

fn formula_names() -> Vec<String> {
    std::iter::once(ALWAYS.to_string()).chain(DUNGEONS.iter().filter(|d| d.boss).map(no_boss)).collect()
}

pub fn added_hashes() -> Vec<u32> {
    ids().iter().map(|q| hash_name(&flag(q))).chain(formula_names().iter().map(|n| hash_name(n))).collect()
}

fn tok(op: u64, a: Option<u64>) -> Node {
    Node::Arr(std::iter::once(Node::U64(op)).chain(a.map(Node::U64)).collect())
}

pub fn add_flags(y: &mut Byml) -> Res<usize> {
    let list: &mut Vec<Node> = y.root.get_mut("Data").and_then(|d| d.get_mut("Enum")).and_then(Node::as_arr_mut).ok_or(Error::Format("key log: the game data list has no Enum table"))?;
    let k: u32 = hash_name(TEMPLATE_FLAG);
    let base: Node = list.iter().find(|r| hash_of(r) == Some(k)).cloned().ok_or(Error::Format("key log: no template step flag"))?;
    let qs: Vec<String> = ids();
    let values: [&str; 4] = ["NotReady", "Ready", STEP, "Complete"];
    for q in &qs {
        let h: u32 = hash_name(&flag(q));
        if list.iter().any(|r| hash_of(r) == Some(h)) {
            return Err(Error::Msg(format!("key log: {} clashes with a game flag", flag(q))));
        }
        let mut r: Node = base.clone();
        r.set("Hash", Node::U32(h));
        r.set("DefaultValue", Node::U32(hash_name(values[0])));
        r.set("RawValues", Node::Arr(values.iter().map(|v| Node::Str((*v).to_string())).collect()));
        r.set("Values", Node::Arr(values.iter().map(|v| Node::U64(hash_name(v) as u64)).collect()));
        r.set("SaveFileIndex", Node::I32(-1));
        list.push(r);
    }
    let k: u32 = hash_name(EXP_TEMPLATE);
    let exps: &mut Vec<Node> = y.root.get_mut("Data").and_then(|d| d.get_mut("BoolExp")).and_then(Node::as_arr_mut).ok_or(Error::Format("key log: the game data list has no BoolExp table"))?;
    let base: Node = exps.iter().find(|r| hash_of(r) == Some(k)).cloned().ok_or(Error::Format("key log: no template formula"))?;
    let any: u64 = hash_name(ANY_FLAG) as u64;
    let mut formulas: Vec<(String, Vec<Node>)> = vec![(ALWAYS.to_string(), vec![tok(OP_BOOL, Some(any)), tok(OP_BOOL, Some(any)), tok(OP_NOT, None), tok(OP_OR, None)])];
    for dn in DUNGEONS.iter().filter(|d| d.boss) {
        formulas.push((no_boss(dn), vec![tok(OP_BOOL, Some(hash_name(&key_flag(dn, "IsGetBossKey")) as u64)), tok(OP_NOT, None)]));
    }
    for (name, terms) in &formulas {
        let h: u32 = hash_name(name);
        if exps.iter().any(|r| hash_of(r) == Some(h)) {
            return Err(Error::Msg(format!("key log: {name} clashes with a game formula")));
        }
        let mut r: Node = base.clone();
        r.set("Hash", Node::U32(h));
        r.set("Values", Node::Arr(terms.clone()));
        exps.push(r);
    }
    Ok(qs.len() + formulas.len())
}

pub fn add_text(raw: &[u8], p: &Plan) -> Res<Vec<u8>> {
    add_text_localized(raw, p, "USen")
}

pub fn add_text_localized(raw: &[u8], p: &Plan, archive: &str) -> Res<Vec<u8>> {
    let mut es: Vec<sarc::Entry> = sarc::parse(raw)?;
    let base: Vec<u8> = sarc::get(&es, TEMPLATE_TEXT).map(|e| e.data.clone()).ok_or(Error::Format("key log: no template quest text"))?;
    let file = archive.rsplit(['/', '\\']).next().unwrap_or(archive);
    let french = file.get(2..4).is_some_and(|s| s.eq_ignore_ascii_case("fr"));
    for q in &quests(p)? {
        let mut m: Msbt = msbt::parse(&base)?;
        for (l, s) in &q.texts {
            let translated = if french { french_text(s) } else { s.clone() };
            m.put_markup(l, &translated)?;
        }
        sarc::set(&mut es, &text_file(&q.id), m.write()?);
    }
    sarc::write(&es)
}

fn french_text(text: &str) -> String {
    let exact = match text {
        "Dungeon Keys" => "Clés des donjons",
        "Small Keys and Boss Keys for each dungeon." => "Petites clés et clés de boss de chaque donjon.",
        "Total keys earned for this location." => "Clés obtenues pour ce donjon.",
        "Keys" => "Clés",
        "Forest Temple" => "Temple de la Forêt",
        "Fire Temple" => "Temple du Feu",
        "Water Temple" => "Temple de l'Eau",
        "Shadow Temple" => "Temple de l'Ombre",
        "Spirit Temple" => "Temple de l'Esprit",
        "Bottom of the Well" => "Puits",
        "Gerudo Proving Grounds" => "Gymnase Gerudo",
        "Ganon's Castle" => "Château de Ganon",
        _ => return text.replace("Small Keys:", "Petites clés :").replace("Found)", "trouvées)")
            .replace("Boss Key:", "Clé de boss :"),
    };
    exact.to_string()
}

fn panel_name(r: &Node) -> &str {
    r.get("ChallengeShort").and_then(Node::as_str).unwrap_or("")
}

pub fn edit_menu(y: &mut Byml) -> Res<usize> {
    let rows: &mut Vec<Node> = y.root.get_mut("ChallengeMenuParamArray").and_then(Node::as_arr_mut).ok_or(Error::Format("key log: the menu table has no panel list"))?;
    let mut parent: Node = rows.iter().find(|r| panel_name(r) == PARENT_PANEL).cloned().ok_or(Error::Format("key log: no Door of Time panel"))?;
    let child: Node = rows.iter().find(|r| panel_name(r) == CHILD_PANEL).cloned().ok_or(Error::Format("key log: no Fire Stone panel"))?;
    parent.set("ChallengeShort", Node::Str(PARENT.to_string()));
    for k in CHECKLIST_KEYS {
        parent.remove(k);
    }
    let mut group: Vec<Node> = vec![parent];
    for dn in &DUNGEONS {
        let mut x: Node = child.clone();
        x.set("ChallengeShort", Node::Str(child_id(dn)));
        for k in CHECKLIST_KEYS {
            x.remove(k);
        }
        x.set("NextActionContent", Node::Arr(checklist(dn).into_iter().map(Node::Str).collect()));
        x.set("UseNextActionContentStep", Node::Arr(vec![Node::Str(STEP.to_string())]));
        group.push(x);
    }
    // Keep the game's own quest panels and other mods' panels. Only replace
    // this optional tracker's entries; AP preparation must not erase the log.
    let added = ids();
    rows.retain(|r| !added.iter().any(|id| panel_name(r) == id));
    let n: usize = group.len();
    rows.splice(0..0, group);
    Ok(n)
}

pub fn stage_menu(rf: &mut Romfs, more: &mut Vec<Out>) -> Res<()> {
    let prior = more.iter().position(|o| o.path == MENU_PACK);
    let zc: Vec<u8> = match prior { Some(i) => more[i].z.clone(), None => rf.read(MENU_PACK)? };
    let dict: Option<u32> = crate::zs::dict_of(&zc);
    let raw: Vec<u8> = rf.zs.decompress(&zc)?;
    let mut es: Vec<sarc::Entry> = sarc::parse(&raw)?;
    let e: &sarc::Entry = sarc::get(&es, MENU_FILE).ok_or(Error::Format("key log: the boot pack has no menu table"))?;
    let mut y: Byml = Byml::parse(&e.data)?;
    edit_menu(&mut y)?;
    sarc::set(&mut es, MENU_FILE, y.write()?);
    let out: Vec<u8> = sarc::write(&es)?;
    let changed = Out { path: MENU_PACK.to_string(), z: crate::zs::compress_raw(&out, dict)?,
        old: prior.map(|i| more[i].old).unwrap_or(raw.len()), new: out.len() };
    match prior { Some(i) => more[i] = changed, None => more.push(changed) }
    Ok(())
}

/// A menu panel is deserialized into native objects, not just copied from BYML.
/// Its heap therefore grows with the panel count as well as the serialized file.
/// Keep the native per-panel allowance, rounded to 256 bytes, and another 1 KiB
/// for each added panel's strings, checklist arrays and allocator metadata.
pub fn menu_budget(native: u32, old_panels: usize, new_panels: usize, old_bytes: usize, new_bytes: usize) -> Res<u32> {
    const PANEL_ALIGN: u64 = 0x100;
    const PANEL_HEADROOM: u64 = 0x400;
    let bad = || Error::Format("key log: the menu allocation size does not fit");
    if native == 0 || old_panels == 0 || new_panels < old_panels || old_bytes == 0 || new_bytes == 0 {
        return Err(Error::Format("key log: invalid native or staged menu allocation inputs"));
    }
    let aligned = |n: u64, a: u64| -> Res<u64> {
        n.checked_add(a - 1).map(|v| v / a * a).ok_or_else(bad)
    };
    let before = u64::try_from(old_panels).map_err(|_| bad())?;
    let added = u64::try_from(new_panels - old_panels).map_err(|_| bad())?;
    let peer = aligned(u64::from(native).div_ceil(before), PANEL_ALIGN)?
        .checked_add(PANEL_HEADROOM).ok_or_else(bad)?;
    let parsed = added.checked_mul(peer).and_then(|v| u64::from(native).checked_add(v)).ok_or_else(bad)?;
    let old = aligned(u64::try_from(old_bytes).map_err(|_| bad())?, crate::rsizetable::ALIGN)?;
    let new = aligned(u64::try_from(new_bytes).map_err(|_| bad())?, crate::rsizetable::ALIGN)?;
    let serialized = if new_bytes > old_bytes {
        u64::from(native).checked_add(new.saturating_sub(old))
            .and_then(|v| v.checked_add(u64::from(crate::staging::MARGIN))).ok_or_else(bad)?
    } else { u64::from(native) };
    u32::try_from(parsed.max(serialized)).map_err(|_| bad())
}

fn menu_panels(raw: &[u8]) -> Res<usize> {
    let y = Byml::parse(raw)?;
    let panels = y.root.get("ChallengeMenuParamArray").and_then(Node::as_arr)
        .ok_or(Error::Format("key log: the menu table has no panel list"))?;
    if panels.is_empty() || panels.iter().any(|r| panel_name(r).is_empty()) {
        return Err(Error::Format("key log: the menu has an empty panel or panel list"));
    }
    Ok(panels.len())
}

fn reserve_menu(table: &mut crate::rsizetable::Rst, minimum: u32) -> Res<()> {
    let current = table.get(MENU_FILE).filter(|n| *n > 0)
        .ok_or(Error::Format("key log: the menu has no native allocation table entry"))?;
    if minimum > current {
        table.set_size(MENU_FILE, minimum)?;
    }
    Ok(())
}

/// Run after generic packed-file growth, taking the original game's allowance
/// as the stable baseline. Repeated preparation never compounds this reserve.
pub fn allocate_menu(rf: &mut Romfs, outs: &[Out], table: &mut crate::rsizetable::Rst) -> Res<()> {
    let native = crate::rsizetable::load(rf)?.get(MENU_FILE).filter(|n| *n > 0)
        .ok_or(Error::Format("key log: the original menu has no native allocation table entry"))?;
    let original = sarc::parse(&rf.read_zs(MENU_PACK)?)?;
    let before = &sarc::get(&original, MENU_FILE)
        .ok_or(Error::Format("key log: the original boot pack has no menu table"))?.data;
    let staged = outs.iter().find(|out| out.path == MENU_PACK)
        .ok_or(Error::Format("key log: the staged boot pack is missing"))?;
    let entries = sarc::parse(&rf.zs.decompress(&staged.z)?)?;
    let after = &sarc::get(&entries, MENU_FILE)
        .ok_or(Error::Format("key log: the staged boot pack has no menu table"))?.data;
    reserve_menu(table, menu_budget(native, menu_panels(before)?, menu_panels(after)?, before.len(), after.len())?)
}

pub fn stage(rf: &mut Romfs, more: &mut Vec<Out>, p: &Plan) -> Res<()> {
    stage_menu(rf, more)?;
    let l: crate::flags::FlagList = crate::flags_build::load(rf)?;
    let missing: Vec<String> = read_flags().into_iter().filter(|f| l.by_hash(hash_name(f) as u64).is_none()).collect();
    if !missing.is_empty() {
        return Err(Error::Msg(format!("key log: the game has no flag {}", missing.join(", "))));
    }
    crate::dungeon_grant::merge(rf, more, LIST, |raw| {
        let mut y: Byml = Byml::parse(raw)?;
        add_flags(&mut y)?;
        y.write()
    })?;
    for lang in crate::hints::languages(rf)? {
        crate::dungeon_grant::merge(rf, more, &lang, |raw| add_text_localized(raw, p, &lang))?;
    }
    Ok(())
}

pub fn stage_table(rf: &mut Romfs, outs: &mut Vec<Out>) -> Res<()> {
    crate::dungeon_grant::merge(rf, outs, TABLE, |raw| {
        let mut y: Byml = Byml::parse(raw)?;
        edit_table(&mut y)?;
        y.write()
    })
}

fn idx(n: usize) -> Res<u16> {
    u16::try_from(n).ok().filter(|v| *v != NONE).ok_or(Error::Format("key log: the flow has too many events"))
}

fn push(f: &mut Flow, k: Kind) -> Res<u16> {
    let i: u16 = idx(f.events.len())?;
    f.events.push(Event { name: format!("{PREFIX}{i}"), kind: k });
    Ok(i)
}

fn ask_step(q: &str, s: &str) -> Cont {
    Cont {
        items: vec![
            ("ChallengeName".to_string(), Val::Str(q.to_string())),
            ("StepName".to_string(), Val::Str(s.to_string())),
            ("IsIgnoreCompletedChallenge".to_string(), Val::Bool(1)),
            ("IsIgnoreChallengeProgressUI".to_string(), Val::Bool(1)),
            ("IsWaitEnd".to_string(), Val::Bool(1)),
        ],
    }
}

fn append_update(f: &mut Flow, then: u16) -> Res<u16> {
    let (a, x): (u16, u16) = crate::start_state::slot(f, "ChallengeSystemActor", "EventExecuteProgressChallengeStep")?;
    let mut next: u16 = then;
    for q in ids().iter().rev() {
        next = push(f, Kind::Action { next, actor: a, act: x, params: Some(ask_step(q, STEP)) })?;
    }
    let (data, set) = crate::start_state::slot(f, "GameDataActor", "EventTriggerSetGameDataBool")?;
    next = push(f, Kind::Action { next, actor: data, act: set, params: Some(Cont { items: vec![
        ("GameDataName".to_string(), Val::Str(MENU_OPEN.to_string())),
        ("Index".to_string(), Val::Int(-1)), ("Value".to_string(), Val::Bool(1))] }) })?;
    Ok(next)
}

pub fn add_update(b: &mut Bf) -> Res<u16> {
    let f: &mut Flow = b.flows.iter_mut().find(|f| f.name == BOOT_FLOW).ok_or(Error::Format("key log: DefaultBootEvent has no flow"))?;
    if f.entries.iter().any(|e| e.name == UPDATE) {
        return Err(Error::Format("key log: DefaultBootEvent already has the update"));
    }
    let pad: u16 = f.entries.first().map(|e| e.pad).unwrap_or(0);
    let main = append_update(f, NONE)?;
    f.entries.push(Entry { name: UPDATE.to_string(), subs: Vec::new(), vars: Vec::new(), main, pad });
    let boot: usize = f.entries.iter().position(|e| e.name == BOOT_FLOW).ok_or(Error::Format("key log: DefaultBootEvent has no boot entry"))?;
    let old: u16 = f.entries[boot].main;
    let call: u16 = push(f, Kind::Sub { next: old, params: None, flow: String::new(), entry: UPDATE.to_string() })?;
    f.entries[boot].main = call;
    f.entries[boot].subs.push(call);
    Ok(main)
}

pub fn hook_opening(b: &mut Bf) -> Res<()> {
    let f: &mut Flow = b.flows.iter_mut().find(|f| f.name == crate::start_state::FLOW).ok_or(Error::Format("key log: no OpeningEvent flow"))?;
    let asks = |e: &Event| -> bool { matches!(&e.kind, Kind::Action { params: Some(p), .. } if p.items.iter().any(|(k, v)| k == "ChallengeName" && *v == Val::Str(crate::start_state::ANCHOR_CHALLENGE.to_string()))) };
    let mine: Vec<usize> = (0..f.events.len()).filter(|&i| !f.events[i].name.starts_with(crate::start_state::PREFIX) && asks(&f.events[i])).collect();
    let [anchor] = mine.as_slice() else {
        return Err(Error::Msg(format!("key log: expected one Deku Tree quest request in the opening, found {}", mine.len())));
    };
    let mut at: usize = *anchor;
    let mut seen: usize = 0;
    while let Kind::Action { next, .. } = &f.events[at].kind {
        let n: usize = usize::from(*next);
        if *next == NONE || n >= f.events.len() || !f.events[n].name.starts_with(crate::start_state::PREFIX) || seen > f.events.len() {
            break;
        }
        at = n;
        seen += 1;
    }
    let Kind::Action { next: old, .. } = f.events[at].kind else {
        return Err(Error::Format("key log: the opening hook point is not an action"));
    };
    // Opening_LoadingKokiriForest does not preload DefaultBootEvent. Calling
    // into that file here leaves the opening waiting forever before its native
    // fade-in and player cleanup. Keep these actions local to the opening flow.
    let update = append_update(f, old)?;
    if let Kind::Action { next, .. } = &mut f.events[at].kind {
        *next = update;
    }
    Ok(())
}

pub fn stage_flows(rf: &mut Romfs, late: &mut Vec<Out>, work: &std::path::Path) -> Res<()> {
    crate::story_skip::stage_late(rf, late, work, BOOT_FLOW, |b| add_update(b).map(|_| ()))?;
    crate::story_skip::stage_late(rf, late, work, crate::start_state::FLOW, hook_opening)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn external_calls(f: &Flow) -> Vec<(String, String)> {
        f.events.iter().filter_map(|e| match &e.kind {
            Kind::Sub { flow, entry, .. } | Kind::SubSwitch { flow, entry, .. } if !flow.is_empty() =>
                Some((flow.clone(), entry.clone())),
            _ => None,
        }).collect()
    }

    fn action_next(e: &Event) -> u16 {
        match e.kind { Kind::Action { next, .. } => next, _ => panic!("not a local action") }
    }

    fn check_opening_update(mut b: Bf) {
        let before = &b.flows[0];
        let anchor = crate::start_state::anchor(before).unwrap();
        let native_next = action_next(&before.events[anchor]);
        let native_events = before.events.clone();
        let mut ops = crate::story_skip::deku();
        ops.flags.push((MENU_OPEN.to_string(), true));
        crate::start_state::patch(&mut b.flows[0], &ops).unwrap();
        let original_calls = external_calls(&b.flows[0]);
        let original_entries = b.flows[0].entries.clone();
        hook_opening(&mut b).unwrap();
        let f = &b.flows[0];
        assert_eq!(external_calls(f), original_calls, "the opening must not need another unloaded flow file");
        assert_eq!(f.entries, original_entries, "inline actions add no subflow references");
        for (i, e) in native_events.iter().enumerate().filter(|(i, _)| *i != anchor) {
            assert_eq!(&f.events[i], e, "native opening cleanup must remain intact");
        }
        let mut at = action_next(&f.events[anchor]);
        let mut seen = std::collections::BTreeSet::new();
        let mut tracked = Vec::new();
        let mut opened = 0;
        while at != native_next {
            assert!(at != NONE && seen.insert(at), "the opening must return to its native continuation without a loop");
            let event = &f.events[usize::from(at)];
            assert!(event.name.starts_with(crate::start_state::PREFIX) || event.name.starts_with(PREFIX));
            if event.name.starts_with(PREFIX) {
                let Kind::Action { actor, act, params: Some(p), .. } = &event.kind else { panic!("tracker opening action is not inline") };
                let actor = &f.actors[usize::from(*actor)];
                if p.get("GameDataName") == Some(&Val::Str(MENU_OPEN.to_string())) {
                    assert_eq!(actor.name, "GameDataActor");
                    assert_eq!(actor.actions[usize::from(*act)], "EventTriggerSetGameDataBool");
                    opened += 1;
                } else {
                    assert_eq!(actor.name, "ChallengeSystemActor");
                    assert_eq!(actor.actions[usize::from(*act)], "EventExecuteProgressChallengeStep");
                    assert_eq!(p.get("StepName"), Some(&Val::Str(STEP.to_string())));
                    let Some(Val::Str(name)) = p.get("ChallengeName") else { panic!("missing tracker challenge") };
                    tracked.push(name.clone());
                }
            }
            at = action_next(event);
        }
        assert_eq!(opened, 1);
        assert_eq!(tracked, ids(), "every tracker row updates before the game's fade-in and control cleanup");
        assert_eq!(Bf::parse(&b.write().unwrap()).unwrap(), b);
    }

    #[test]
    fn opening_tracker_updates_inline_and_preserves_native_cleanup_and_subflows() {
        let actor = |name: &str, actions: &[&str]| crate::bfevfl::Actor {
            name: name.to_string(), sub: String::new(), arg: String::new(),
            actions: actions.iter().map(|s| (*s).to_string()).collect(), queries: Vec::new(),
            params: Some(Cont { items: vec![("EventMemberCreateMethod".to_string(), Val::Int(0))] }), ep: NONE, cut: 1,
        };
        let f = Flow {
            name: crate::start_state::FLOW.to_string(),
            actors: vec![actor("EventSystemActor", &["EventWait"]), actor("ChallengeSystemActor", &["EventExecuteProgressChallengeStep"])],
            events: vec![
                Event { name: "Anchor".to_string(), kind: Kind::Action { next: 1, actor: 1, act: 0,
                    params: Some(ask_step(crate::start_state::ANCHOR_CHALLENGE, crate::start_state::ANCHOR_STEP)) } },
                Event { name: "Event31".to_string(), kind: Kind::Action { next: 2, actor: 0, act: 0, params: None } },
                Event { name: "NativeCleanup".to_string(), kind: Kind::Sub { next: NONE, params: None,
                    flow: "Common".to_string(), entry: "Cleanup".to_string() } },
            ],
            entries: vec![Entry { name: "Opening_LoadingKokiriForest".to_string(), subs: vec![2], vars: Vec::new(), main: 0, pad: 0 }],
        };
        check_opening_update(Bf { ver: [0, 4, 0, 0], bom: 0xFEFF, shift: 3, pad: 0,
            name: crate::start_state::FLOW.to_string(), flows: vec![f], tls: Vec::new() });
    }

    #[test]
    fn real_opening_with_our_story_state_needs_no_new_external_flow() {
        let Some(mut rf) = real() else { return };
        let raw = rf.read_zs(&format!("Event/EventFlow/{}.bfevfl.zs", crate::start_state::FLOW)).unwrap();
        check_opening_update(Bf::parse(&raw).unwrap());
        let raw = rf.read_zs(&format!("Event/EventFlow/{BOOT_FLOW}.bfevfl.zs")).unwrap();
        let mut boot = Bf::parse(&raw).unwrap();
        let original_calls = external_calls(&boot.flows[0]);
        add_update(&mut boot).unwrap();
        assert_eq!(external_calls(&boot.flows[0]), original_calls, "the boot hook only calls its local update entry");
        assert_eq!(Bf::parse(&boot.write().unwrap()).unwrap(), boot);
    }

    #[test]
    fn expanded_menu_reserves_native_objects_instead_of_only_byml_bytes() {
        // The reported startup crash: 20 native panels become 29. Generic
        // filesize growth only allowed 17,648 bytes and exhausted the parser.
        assert_eq!(menu_budget(14_992, 20, 29, 4_564, 6_204).unwrap(), 31_120);
        assert_eq!(menu_budget(14_992, 20, 20, 4_564, 4_564).unwrap(), 14_992);
        assert!(menu_budget(14_992, 20, 29, 4_564, 100_000).unwrap() >= 111_440,
            "large serialized changes must also retain the generic byte-growth floor");
    }

    #[test]
    fn menu_reserve_is_monotonic_idempotent_and_requires_a_native_entry() {
        let mut table = crate::rsizetable::Rst { version: 1, name_len: 160, crc: Vec::new(), names: Vec::new() };
        assert!(reserve_menu(&mut table, 31_120).is_err());
        table.set_size(MENU_FILE, 17_648).unwrap();
        reserve_menu(&mut table, 31_120).unwrap();
        assert_eq!(table.get(MENU_FILE), Some(31_120));
        let once = table.clone();
        reserve_menu(&mut table, 31_120).unwrap();
        assert_eq!(table, once);
        table.set_size(MENU_FILE, 100_000).unwrap();
        reserve_menu(&mut table, 31_120).unwrap();
        assert_eq!(table.get(MENU_FILE), Some(100_000));
    }

    #[test]
    fn menu_budget_rejects_bad_counts_and_checked_size_overflow() {
        assert!(menu_budget(0, 20, 29, 4_564, 6_204).is_err());
        assert!(menu_budget(14_992, 0, 29, 4_564, 6_204).is_err());
        assert!(menu_budget(14_992, 20, 19, 4_564, 6_204).is_err());
        assert!(menu_budget(14_992, 20, 29, 0, 6_204).is_err());
        assert!(menu_budget(u32::MAX, 1, 2, 4_564, 6_204).is_err());
        assert!(menu_budget(14_992, 20, usize::MAX, 4_564, 6_204).is_err());
        assert!(menu_budget(14_992, 20, 29, 4_564, usize::MAX).is_err());
    }

    #[test]
    fn tracker_keeps_native_and_archipelago_menu_panels() {
        let panel = |name: &str| Node::Map(vec![("ChallengeShort".to_string(), Node::Str(name.to_string()))]);
        let original = vec![panel(PARENT_PANEL), panel(CHILD_PANEL), panel("Archipelago"), panel("OtherMod")];
        let mut y = Byml { version: 7, big: false, root: Node::Map(vec![
            ("ChallengeMenuParamArray".to_string(), Node::Arr(original.clone()))]) };
        assert_eq!(edit_menu(&mut y).unwrap(), 9);
        let rows = y.root.get("ChallengeMenuParamArray").unwrap().as_arr().unwrap();
        assert_eq!(&rows[9..], original.as_slice());
        edit_menu(&mut y).unwrap();
        assert_eq!(y.root.get("ChallengeMenuParamArray").unwrap().as_arr().unwrap().len(), original.len() + 9);
    }

    #[test]
    fn totals_are_explicit_and_french_keeps_native_number_tags() {
        assert!(plan(&[0; 7]).is_err());
        assert!(plan(&[0; 8]).is_ok());
        assert!(plan(&[33; 8]).is_ok(), "item-linked recipients may have more keys than one native pool");
        assert!(plan(&[i32::MAX as u32; 8]).is_ok());
        assert!(plan(&[i32::MAX as u32 + 1; 8]).is_err());
        let linked = quests(&plan(&[1024; 8]).unwrap()).unwrap();
        assert!(linked[1].texts.iter().any(|(_, text)| text.contains("/1024 Found)")));
        let caps = [5, 8, 4, 5, 5, 2, 9, 2];
        let p = plan(&caps).unwrap();
        let qs = quests(&p).unwrap();
        let (_, text) = qs[1].texts.iter().find(|(id, _)| id.ends_with("Content_00")).unwrap();
        let fr = french_text(text);
        assert!(fr.starts_with("Petites clés :"));
        assert!(fr.ends_with("/5 trouvées)"));
        assert_eq!(fr.matches("{2.1:").count(), 2);
    }

    fn real() -> Option<Romfs> {
        let p: std::path::PathBuf = ootrr_game::test_romfs::path();
        if p.join("Pack").join("ZsDic.pack.zs").is_file() {
            Romfs::open(&p).ok()
        } else {
            eprintln!("skipped, no RomFS dump at {} (set OOTRR_ROMFS)", p.display());
            None
        }
    }

    fn quiet(r: &Node) -> Vec<bool> {
        r.get("Steps").and_then(Node::as_arr).unwrap_or(&[]).iter().map(|s| s.get(QUIET) == Some(&Node::Bool(true))).collect()
    }

    #[test]
    fn every_game_quest_step_stops_the_next_objective_card_and_ours_stay() {
        let Some(mut rf) = real() else { return };
        let mut y: Byml = rf.read_byml(TABLE).unwrap();
        let before: usize = y.root.as_arr().unwrap().len();
        edit_table(&mut y).unwrap();
        assert!(quiet_steps(&mut y).unwrap() > 100);
        let rows: &[Node] = y.root.as_arr().unwrap();
        assert_eq!(rows.len(), before + ids().len());
        for r in rows {
            let q: Vec<bool> = quiet(r);
            assert!(!q.is_empty(), "{} has no steps", id_of(r));
            if id_of(r).starts_with(&format!("Work/Challenge/{OURS}")) {
                assert!(q.iter().all(|b| !b), "{} was quieted", id_of(r));
            } else {
                assert!(q.iter().all(|b| *b), "{} still shows the card", id_of(r));
            }
        }
        assert_eq!(quiet_steps(&mut y).unwrap(), 0);
    }
}
