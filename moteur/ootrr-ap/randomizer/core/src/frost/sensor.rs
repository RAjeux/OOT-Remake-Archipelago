use crate::ainb::build::Spec;
use crate::ainb::graft::{root, set_root, SEQUENTIAL, SIMULTANEOUS};
use crate::ainb::Ainb;
use crate::byml::{Byml, Node};
use crate::error::{Error as E, Res};
use crate::sarc::{self, Entry};

pub const SUN: &str = "SongOfTheSunSensorActor";
pub const FREEZARD: &str = "Enemy_Freezard";
pub const TRAP_CHEST: &str = "Obj_TBox_A_04";
pub const NAME: &str = "OOTRR_ConditionSensor_Cold";
pub const WINDOW: f32 = 60.0;
const AFFILIATION: &str = "Component/AffiliationParam/EnemyCommon.game__component__AffiliationParam.bgyml";
const SUN_AI: &str = "AI/ConditionSensorActor.root.ainb";
const SUN_AI_INFO: &str = "AI/AIInfo/ConditionSensorActor.engine__actor__AIInfo.bgyml";
const S32: usize = 0;
const BOOL: usize = 1;
const F32: usize = 2;

pub struct Made {
    pub pack: Vec<u8>,
    pub fresh: Vec<(String, usize)>,
    pub peers: Vec<(String, usize)>,
}

fn own(path: &str) -> String {
    path.replace(SUN, NAME)
}

fn rename(n: &mut Node) {
    match n {
        Node::Str(t) if t.contains(SUN) => *t = t.replace(SUN, NAME),
        Node::Arr(a) => a.iter_mut().for_each(rename),
        Node::Map(m) => m.iter_mut().for_each(|(_, v)| rename(v)),
        _ => {}
    }
}

fn get<'a>(es: &'a [Entry], name: &str) -> Res<&'a [u8]> {
    sarc::get(es, name).map(|e| e.data.as_slice()).ok_or_else(|| E::Msg(format!("the sensor template has no {name}")))
}

fn attack(src: &[u8]) -> Res<Vec<u8>> {
    let mut y: Byml = Byml::parse(src)?;
    let list: &mut Vec<Node> = y.root.get_mut("AttackParams").and_then(|v| v.as_arr_mut()).ok_or(E::Format("the trap chest has no attack list"))?;
    let mut breath: Node = list.first().cloned().ok_or(E::Format("the trap chest attack list is empty"))?;
    breath.set("Impulse", Node::F32(0.0));
    *list = vec![breath];
    y.write()
}

fn layer(raw: &[u8]) -> Res<Vec<u8>> {
    let mut y: Byml = Byml::parse(raw)?;
    y.root.set("LayerSensor", Node::Str("EnemyAttack".to_string()));
    y.root.remove("EnableLayerHitMask");
    y.root.remove("SubLayerSensor");
    y.write()
}

fn shape(raw: &[u8]) -> Res<Vec<u8>> {
    let mut y: Byml = Byml::parse(raw)?;
    let c: &mut Node = y.root.get_mut("Cylinder").and_then(|v| v.as_arr_mut()).and_then(|a| a.first_mut()).ok_or(E::Format("the sensor shape has no cylinder"))?;
    c.set("Radius", Node::F32(1.0));
    for (k, v) in [("CenterA", 1.0f32), ("CenterB", -1.0f32)] {
        if let Some(p) = c.get_mut(k) {
            p.set("Y", Node::F32(v));
        }
    }
    y.write()
}

fn actor(raw: &[u8]) -> Res<Vec<u8>> {
    let mut y: Byml = Byml::parse(raw)?;
    let c: &mut Node = y.root.get_mut("Components").ok_or(E::Format("the sensor actor has no components"))?;
    c.set("AffiliationRef", Node::Str(format!("?{AFFILIATION}")));
    c.set("AIInfoRef", Node::Str(format!("?AI/AIInfo/{NAME}.engine__actor__AIInfo.bgyml")));
    c.remove("ELinkRef");
    c.remove("SLinkRef");
    y.write()
}

fn ai_info(raw: &[u8]) -> Res<Vec<u8>> {
    let mut y: Byml = Byml::parse(raw)?;
    y.root.set("RootAIRef", Node::Str(format!("Work/AI/Root/{NAME}.root.ain")));
    y.write()
}

fn s32(v: i32) -> Vec<u8> {
    v.to_le_bytes().to_vec()
}

fn f32b(v: f32) -> Vec<u8> {
    v.to_le_bytes().to_vec()
}

fn b(v: bool) -> Vec<u8> {
    (v as u32).to_le_bytes().to_vec()
}

pub fn ai(raw: &[u8], frames: f32) -> Res<Vec<u8>> {
    let mut a: Ainb = Ainb::parse(raw)?;
    let hit: usize = root(&a).ok_or(E::Format("the sensor graph has no root"))?;
    let count: usize = a.add_node(
        &Spec::node("ExecuteGenericCounterByPlug", "ootrr-cold#count")
            .idle(S32, "ResultBeforeFinish", s32(0))
            .idle(S32, "ResultOnFinish", s32(2))
            .constant(F32, "BaseFrameTime", f32b(frames))
            .idle(F32, "RandomTimeMax", f32b(0.0))
            .out(F32, "ElapsedFrameTime")
            .out(F32, "PercentComplete")
            .out(F32, "RemainingFrameTime"),
    )?;
    let both: usize = a.add_node(&Spec::composite(SIMULTANEOUS, "ootrr-cold#both").prop(S32, "EndPolicy", s32(0)).prop(S32, "ResultPolicy", s32(1)).kid(count, "").kid(hit, ""))?;
    let rest: usize = a.add_node(&Spec::node("ExecuteGenericDummyAction", "ootrr-cold#rest"))?;
    let seq: usize = a.add_node(
        &Spec::composite(SEQUENTIAL, "ootrr-cold#seq")
            .prop(S32, "BusyPolicy", s32(0))
            .prop(S32, "NumLoop", s32(0))
            .prop(S32, "PlayPolicy", s32(0))
            .prop(S32, "ResultPolicy", s32(0))
            .prop(BOOL, "IsDelayJudge", b(false))
            .prop(BOOL, "IsLoop", b(false))
            .prop(BOOL, "IsUpdateNextInFrame", b(true))
            .kid(both, "")
            .kid(rest, ""),
    )?;
    set_root(&mut a, seq)?;
    let bad: Vec<String> = crate::ainb::audit(&a);
    if !bad.is_empty() {
        return Err(E::Msg(format!("the cold sensor graph has problems: {}", bad.join(", "))));
    }
    a.write()
}

pub fn make(sun: &[Entry], frz: &[Entry], chest: &[Entry]) -> Res<Made> {
    let peers: Vec<(String, usize)> = sun.iter().chain(frz.iter()).chain(chest.iter()).map(|e| (e.name.clone(), e.data.len())).collect();
    let mut out: Vec<Entry> = Vec::new();
    for e in sun {
        let name: String = own(&e.name);
        let data: Vec<u8> = match Byml::parse(&e.data) {
            Ok(mut y) if e.name.contains(SUN) || e.name.starts_with("Phive/") => {
                rename(&mut y.root);
                y.write()?
            }
            _ => e.data.clone(),
        };
        out.push(Entry { name, data });
    }
    let set = |out: &mut Vec<Entry>, name: &str, data: Vec<u8>| {
        match out.iter_mut().find(|e| e.name == name) {
            Some(e) => e.data = data,
            None => out.push(Entry { name: name.to_string(), data }),
        }
    };
    let atk: String = format!("GameBalance/AttackParam/{NAME}.game__gamebalance__AttackParam.bgyml");
    set(&mut out, &atk, attack(get(chest, &format!("GameBalance/AttackParam/{TRAP_CHEST}.game__gamebalance__AttackParam.bgyml"))?)?);
    let body: String = format!("Phive/RigidBodySensorParam/{NAME}_Atk.phive__RigidBodySensorParam.bgyml");
    let raw: Vec<u8> = get(&out, &body)?.to_vec();
    set(&mut out, &body, layer(&raw)?);
    let sh: String = format!("Phive/ShapeParam/{NAME}.phive__ShapeParam.bgyml");
    let raw: Vec<u8> = get(&out, &sh)?.to_vec();
    set(&mut out, &sh, shape(&raw)?);
    let ap: String = format!("Actor/{NAME}.engine__actor__ActorParam.bgyml");
    let raw: Vec<u8> = get(&out, &ap)?.to_vec();
    set(&mut out, &ap, actor(&raw)?);
    set(&mut out, AFFILIATION, get(frz, AFFILIATION)?.to_vec());
    set(&mut out, &format!("AI/AIInfo/{NAME}.engine__actor__AIInfo.bgyml"), ai_info(get(sun, SUN_AI_INFO)?)?);
    set(&mut out, &format!("AI/{NAME}.root.ainb"), ai(get(sun, SUN_AI)?, WINDOW)?);
    let fresh: Vec<(String, usize)> = out.iter().filter(|e| e.name.contains(NAME)).map(|e| (e.name.clone(), e.data.len())).collect();
    Ok(Made { pack: sarc::write(&out)?, fresh, peers })
}
