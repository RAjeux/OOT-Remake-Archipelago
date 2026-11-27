//! Export the rolled native rules, not an ordering inferred from one playthrough.
//!
//! AST serialization is adapted from ootrando/ootrr's Archipelago exporter,
//! revision 4fa6e5a6 (GPL-3.0-or-later; upstream notices remain in this tree).
use std::collections::{BTreeMap, BTreeSet};
use ootrr_core::{json::Json, logic_val::Val, rule_ast::{Bop, Cmp}, rules::{Node, Rule},
    slice, world::{Placement, World}};
use super::Result;

fn int(n: usize) -> Json { Json::Int(n as i64) }
fn tag(t: &str, rest: Vec<Json>) -> Json {
    Json::Arr(std::iter::once(Json::Str(t.into())).chain(rest).collect())
}
fn val(v: &Val) -> Json {
    match v {
        Val::Bool(b) => Json::Bool(*b), Val::Int(n) => Json::Int(*n),
        Val::Float(n) => Json::Num(*n), Val::Str(s) => Json::Str(s.clone()),
        Val::List(v) => Json::Arr(v.iter().map(val).collect()),
        Val::Map(v) => Json::Obj(v.iter().map(|(k,v)| (k.clone(), val(v))).collect()),
    }
}
fn cmp(c: Cmp) -> &'static str {
    match c { Cmp::Eq=>"==", Cmp::Ne=>"!=", Cmp::Lt=>"<", Cmp::Le=>"<=",
        Cmp::Gt=>">", Cmp::Ge=>">=", Cmp::In=>"in", Cmp::NotIn=>"not in" }
}
fn bop(c: Bop) -> &'static str {
    match c { Bop::Add=>"+", Bop::Sub=>"-", Bop::Mul=>"*", Bop::Div=>"/",
        Bop::Floor=>"//", Bop::Rem=>"%" }
}
fn ids(v: &[usize]) -> Json { Json::Arr(v.iter().map(|i| int(*i)).collect()) }
fn node(n: &Node) -> Json {
    match n {
        Node::Const(v)=>tag("c",vec![val(v)]),
        Node::Has(i,k)=>tag("h",vec![int(*i),Json::Int(*k as i64)]),
        Node::Any(v)=>tag("any",vec![ids(v)]), Node::All(v)=>tag("all",vec![ids(v)]),
        Node::Item(i)=>tag("i",vec![int(*i)]), Node::Distinct(v)=>tag("d",vec![ids(v)]),
        Node::Age=>tag("age",vec![]), Node::AgeIs(a)=>tag("ageis",vec![a.name().into()]),
        Node::Tod(f,s)=>tag("tod",vec![Json::Int(*f as i64),node(s)]),
        Node::Not(x)=>tag("not",vec![node(x)]), Node::Neg(x)=>tag("neg",vec![node(x)]),
        Node::And(v)=>tag("and",vec![Json::Arr(v.iter().map(node).collect())]),
        Node::Or(v)=>tag("or",vec![Json::Arr(v.iter().map(node).collect())]),
        Node::Cmp(c,a,b)=>tag("cmp",vec![cmp(*c).into(),node(a),node(b)]),
        Node::Bin(c,a,b)=>tag("bin",vec![bop(*c).into(),node(a),node(b)]),
        Node::If(k,t,e)=>tag("if",vec![node(k),node(t),node(e)]),
        Node::List(v)=>tag("list",vec![Json::Arr(v.iter().map(node).collect())]),
    }
}
fn rule(r: &Rule) -> Json {
    if r.always { Json::Bool(true) } else if r.never { Json::Bool(false) } else { node(&r.node) }
}

pub fn world_json(w: &World) -> Json {
    let items = w.items.names.iter().enumerate().map(|(i,n)| Json::obj()
        .with("name",n.clone().into()).with("adv",(w.items.adv[i] || !w.users[i].is_empty() || w.goal.deps.contains(&i)).into())
        .with("event",w.items.event[i].into())).collect();
    let regions = w.regions.iter().map(|r| Json::obj().with("name",r.name.clone().into())
        .with("time",Json::Int(r.provides_time as i64)).with("exits",ids(&r.exits))
        .with("locs",ids(&r.locations))).collect();
    let exits = w.exits.iter().map(|e| Json::obj().with("from",int(e.from))
        .with("to",int(e.to)).with("rule",rule(&e.rule))).collect();
    let locs = w.locs.iter().map(|l| Json::obj().with("name",l.name.clone().into())
        .with("region",int(l.region)).with("rule",rule(&l.rule))
        .with("event",l.event.map(int).unwrap_or(Json::Null))).collect();
    Json::obj().with("items",Json::Arr(items)).with("regions",Json::Arr(regions))
        .with("exits",Json::Arr(exits)).with("locs",Json::Arr(locs))
        .with("goal",rule(&w.goal)).with("root",int(w.root)).with("real",ids(&w.real))
        .with("start",Json::Arr(w.start.iter().map(|(i,n)|
            Json::Arr(vec![int(*i),Json::Int(*n as i64)])).collect()))
}

/// Fixed rewards remain native. Every physical variant of an exported check
/// is removed from that fixed placement, including aliases for a second age.
pub fn from_world(w: &World, placement: &Placement, sources: &Json) -> Result<Json> {
    let selected: BTreeSet<&str> = sources.as_obj().ok_or("access sources must be an object")?
        .iter().map(|(n,_)| n.as_str()).collect();
    let mut routes: BTreeMap<&str,Vec<usize>> = selected.iter().map(|n| (*n,Vec::new())).collect();
    let mut fixed = Vec::new();
    for (id,l) in w.locs.iter().enumerate() {
        let base = l.name.split(slice::data::SEP).next().unwrap_or(&l.name);
        if let Some(route) = routes.get_mut(base) { route.push(id); }
        else if let Some(item) = placement.get(id) {
            fixed.push(Json::Arr(vec![int(id),int(item)]));
        }
    }
    for (name,route) in &routes {
        if route.is_empty() { return Err(format!("network check has no native access rule: {name}").into()); }
    }
    Ok(Json::obj().with("schema",1_i64.into()).with("world",world_json(w))
        .with("sources",Json::Obj(routes.into_iter().map(|(n,v)| (n.to_owned(),ids(&v))).collect()))
        .with("fixed",Json::Arr(fixed))
        .with("master_sword",w.loc("Master Sword Pedestal").map(int).unwrap_or(Json::Null)))
}

#[cfg(test)]
mod tests {
    use super::*;
    use ootrr_core::{rules::Rule, world::Spec};

    #[test]
    fn serialization_preserves_integer_precision_and_constant_boolean_rules() {
        assert_eq!(node(&Node::Const(Val::Int(9007199254740993))).as_arr().unwrap()[1],Json::Int(9007199254740993));
        assert_eq!(rule(&Rule::truth(false)),Json::Bool(false));
    }

    #[test]
    fn exported_checks_remove_all_fixed_age_variants_but_keep_native_events() {
        let mut spec = Spec::new();
        spec.lenient = true;
        spec.add_item("Key",true,1);
        spec.add_regions(r#"[{"region_name":"Root","locations":{"Check":"True","Fixed":"True"},"events":{"Bridge Open":"True"},"exits":{"Other":"True"}},{"region_name":"Other","locations":{"Check":"True"}}]"#).unwrap();
        let w = World::build(&spec).unwrap();
        let mut p = Placement::new(w.locs.len());
        for l in &w.real { p.put(*l,w.item("Key").unwrap()); }
        let j = from_world(&w,&p,&Json::obj().with("Check",Json::Null)).unwrap();
        assert_eq!(j.get("sources").unwrap().get("Check").unwrap().as_arr().unwrap().len(),2);
        let fixed = j.get("fixed").unwrap().as_arr().unwrap();
        assert_eq!(fixed.len(),1);
        assert_eq!(fixed[0].as_arr().unwrap()[0].as_i64(),Some(w.loc("Fixed").unwrap() as i64));
    }
}
