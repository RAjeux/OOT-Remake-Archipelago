use crate::byml::{Byml, Node};
use crate::error::{Error as E, Res};
use crate::pickup_pack::closure::{chain, norm, Chain, Pool};
use crate::sarc::Entry;

pub const GOODS: &str = "GoodsList";
pub const SLOTS: usize = 8;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Edit {
    pub slot: usize,
    pub actor: String,
    pub offset: i32,
    pub stock: i32,
}

pub fn work_actor(name: &str) -> String {
    format!("Work/Actor/{name}.engine__actor__ActorParam.gyml")
}

pub fn actor_of(path: &str) -> &str {
    path.rsplit('/').next().unwrap_or("").split('.').next().unwrap_or("")
}

pub fn shop_ref(es: &[Entry], keeper: &str) -> Res<String> {
    let mut p: Pool = Pool::default();
    p.add_pack(es)?;
    let c: Chain = chain(&p, keeper)?;
    let r: &str = c.comps.get("ShopRef").map(|v| v.as_str()).ok_or_else(|| E::Msg(format!("{keeper} has no ShopRef")))?;
    norm(r).ok_or(E::Format("ShopRef is not a file"))
}

fn neutral(g: &mut Node) {
    if let Some(r) = g.get_mut("Release") {
        if r.get("IsCheckReleaseGameData").is_some() {
            r.set("IsCheckReleaseGameData", Node::Bool(false));
        }
        if r.get("IsCheckSoldOutGameData").is_some() {
            r.set("IsCheckSoldOutGameData", Node::Bool(false));
        }
    }
}

pub fn apply(g: &mut Node, e: &Edit) {
    g.set("Actor", Node::Str(work_actor(&e.actor)));
    if g.get("StockNum").is_some() || e.stock >= 0 {
        g.set("StockNum", Node::I32(e.stock));
    }
    if g.get("PriceOffset").is_some() || e.offset != 0 {
        g.set("PriceOffset", Node::I32(e.offset));
    }
    if let Some(Node::Arr(l)) = g.get_mut("ConditionalPriceOffsetList") {
        l.clear();
    }
    neutral(g);
}

pub fn edit(raw: &[u8], edits: &[Edit]) -> Res<Vec<u8>> {
    let mut y: Byml = Byml::parse(raw)?;
    if y.write()? != raw {
        return Err(E::Format("a ShopParam file does not round trip"));
    }
    let g: &mut Vec<Node> = y.root.get_mut(GOODS).and_then(|l| l.as_arr_mut()).ok_or(E::Format("a ShopParam file has no GoodsList"))?;
    if g.len() != SLOTS {
        return Err(E::Format("a GoodsList is not 8 long"));
    }
    for e in edits {
        let n: &mut Node = g.get_mut(e.slot).ok_or(E::Format("a shop slot is past the end of the GoodsList"))?;
        apply(n, e);
    }
    y.write()
}

pub fn goods(raw: &[u8]) -> Res<Vec<Node>> {
    let y: Byml = Byml::parse(raw)?;
    Ok(y.root.get(GOODS).and_then(|l| l.as_arr()).ok_or(E::Format("a ShopParam file has no GoodsList"))?.to_vec())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entry(actor: &str, extra: Vec<(String, Node)>) -> Node {
        let mut m: Vec<(String, Node)> = vec![("Actor".to_string(), Node::Str(work_actor(actor)))];
        m.extend(extra);
        Node::Map(m)
    }

    fn file(list: Vec<Node>) -> Vec<u8> {
        Byml { root: Node::Map(vec![(GOODS.to_string(), Node::Arr(list))]), version: 7, big: false }.write().unwrap()
    }

    #[test]
    fn a_deal_sells_once_with_no_gate_and_no_discount() {
        let rel: Node = Node::Map(vec![
            ("IsCheckReleaseGameData".to_string(), Node::Bool(true)),
            ("IsCheckSoldOutGameData".to_string(), Node::Bool(true)),
            ("SoldOutGameData".to_string(), Node::Str("IsGet.Item_Bottle_BlueFire".into())),
        ]);
        let mut list: Vec<Node> = (0..8).map(|i| entry(&format!("Shop_{i}"), vec![("StockNum".to_string(), Node::I32(-1))])).collect();
        list[4] = entry("Shop_Bottle_BlueFire", vec![("StockNum".to_string(), Node::I32(-1)), ("PriceOffset".to_string(), Node::I32(-20)), ("ConditionalPriceOffsetList".to_string(), Node::Arr(vec![Node::I32(1)])), ("Release".to_string(), rel)]);
        let raw: Vec<u8> = file(list);
        let out: Vec<u8> = edit(&raw, &[Edit { slot: 4, actor: "Shop_OOTRR_Item_Boomerang_20".into(), offset: 0, stock: 1 }]).unwrap();
        let g: Vec<Node> = goods(&out).unwrap();
        assert_eq!(g.len(), 8);
        assert_eq!(actor_of(g[4].get("Actor").unwrap().as_str().unwrap()), "Shop_OOTRR_Item_Boomerang_20");
        assert_eq!(g[4].get("StockNum"), Some(&Node::I32(1)));
        assert_eq!(g[4].get("PriceOffset"), Some(&Node::I32(0)));
        assert_eq!(g[4].get("ConditionalPriceOffsetList"), Some(&Node::Arr(Vec::new())));
        let r: &Node = g[4].get("Release").unwrap();
        assert_eq!(r.get("IsCheckReleaseGameData"), Some(&Node::Bool(false)));
        assert_eq!(r.get("IsCheckSoldOutGameData"), Some(&Node::Bool(false)));
        assert_eq!(g[3], goods(&raw).unwrap()[3]);
    }

    #[test]
    fn moved_goods_keep_unlimited_stock_and_only_add_an_offset_when_needed() {
        let raw: Vec<u8> = file((0..8).map(|i| entry(&format!("Shop_{i}"), Vec::new())).collect());
        let out: Vec<u8> = edit(&raw, &[Edit { slot: 0, actor: "Shop_Heart".into(), offset: 0, stock: -1 }, Edit { slot: 1, actor: "Shop_Armor_Goron".into(), offset: -10, stock: -1 }]).unwrap();
        let g: Vec<Node> = goods(&out).unwrap();
        assert_eq!(g[0].get("PriceOffset"), None);
        assert_eq!(g[0].get("StockNum"), None);
        assert_eq!(g[1].get("PriceOffset"), Some(&Node::I32(-10)));
        assert!(edit(&file(vec![entry("A", Vec::new())]), &[]).is_err());
    }
}
