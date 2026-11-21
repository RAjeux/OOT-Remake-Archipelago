use crate::byml::{Byml, Node};
use crate::error::{Error as E, Res};
use crate::pickup_pack::actor::{MODEL_REF, SHARED_ANIM};
use crate::pickup_pack::closure::{chain, local, norm, Chain, Pool};

pub const HARP: &str = "Dm_Item_Sheik_Harp";
pub const ROW_KEYS: [&str; 5] = ["FmdbName", "ModelProjectName", "ModelAabbMax", "ModelAabbMin", "PreActorRenderInfoHeapSize"];
const ANIM_LIST: &str = "AnimationResources";
const ANIM_NAME: &str = "ModelProjectName";

pub fn anim_file(name: &str) -> String {
    format!("Component/AnimationParam/{name}.engine__component__AnimationParam.bgyml")
}

pub fn shared_list() -> Node {
    let mut one: Node = Node::Map(Vec::new());
    one.set(ANIM_NAME, Node::Str(SHARED_ANIM.to_string()));
    Node::Arr(vec![one])
}

pub fn anim(name: &str, version: u16) -> Res<(String, String, Vec<u8>)> {
    let mut root: Node = Node::Map(Vec::new());
    root.set(ANIM_LIST, shared_list());
    let f: String = anim_file(name);
    Ok((local(&f), f, Byml { root, version, big: false }.write()?))
}

pub fn model_ref(p: &Pool, donor: &str) -> Res<String> {
    let c: Chain = chain(p, donor)?;
    let v: &str = c.comps.get(MODEL_REF).map(|s| s.as_str()).ok_or_else(|| E::Msg(format!("the model donor {donor} has no {MODEL_REF}")))?;
    if !norm(v).is_some_and(|f| p.get(&f).is_some()) {
        return Err(E::Msg(format!("the model donor {donor} keeps its model file outside its pack")));
    }
    Ok(v.to_string())
}

pub fn row(r: &mut Node, donor: &Node) -> Res<()> {
    for k in ROW_KEYS {
        let v: &Node = donor.get(k).ok_or_else(|| E::Msg(format!("the model donor row has no {k}")))?;
        r.set(k, v.clone());
    }
    r.set(ANIM_LIST, shared_list());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_donor_row_gives_the_model_fields_and_the_shared_animation() {
        let mut d: Node = Node::Map(Vec::new());
        for k in ROW_KEYS {
            d.set(k, Node::Str(format!("harp {k}")));
        }
        let mut r: Node = Node::Map(Vec::new());
        r.set("FmdbName", Node::Str("Obj_Rupee".to_string()));
        r.set("ActorName", Node::Str("Item_Melody_SunSong".to_string()));
        row(&mut r, &d).unwrap();
        assert_eq!(r.get("FmdbName").and_then(|v| v.as_str()), Some("harp FmdbName"));
        assert_eq!(r.get("ActorName").and_then(|v| v.as_str()), Some("Item_Melody_SunSong"));
        assert_eq!(r.get(ANIM_LIST), Some(&shared_list()));
        assert!(row(&mut r, &Node::Map(Vec::new())).is_err());
        let (refd, f, b): (String, String, Vec<u8>) = anim("Obj_Melody_SunSong", 7).unwrap();
        assert_eq!(refd, format!("?{f}"));
        assert_eq!(Byml::parse(&b).unwrap().root.get(ANIM_LIST), Some(&shared_list()));
    }
}
