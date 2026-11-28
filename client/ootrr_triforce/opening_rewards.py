"""Replace only AP checks gifted by OOTRR's skipped castle visit.

The opening keeps its native story state but gives no selected donor reward.
The existing ready-player tracking transaction later grants the actual room
rewards, repairing older saves too, without a received-item ACK or presentation.
"""
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from .i18n import tr
from oot_rando.patching.event_info import analysis_scope

FLOW = "OpeningEvent"
PATH = "Event/EventFlow/OpeningEvent.bfevfl.zs"
POUCH = "Event/EventFlow/GetPouchContent.bfevfl.zs"
REST = "System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs"
MARKER = "Archipelago/opening-rewards-v1.json"
PREFIX = "OOTRR_APOpening_"
ENTRY = PREFIX + "Reconcile"
LOCATIONS = ("HC Zeldas Letter", "Song from Impa")
VANILLA = ("Zeldas Letter", "Zeldas Lullaby")
GIVE = "EventTriggerAddOrRemovePouchContent"
GIFT_PARAMS = dict(Num=1, IsSetMessageTargetActorName=False, IsEquipDIrect=False, IsGetEvent=False)


def _invalid(detail=""):
    return ValueError(tr("Unsupported Archipelago opening rewards.") + (" " + detail if detail else ""))


def opening_records(roster, settings):
    from .catalog import ITEM_DATA
    from .network_rewards import source_records, validate_record
    from .network_catalog import enabled
    if not enabled(settings):
        return []
    records = []
    for record in source_records(roster, settings):
        if record["name"] not in LOCATIONS:
            continue
        validate_record(record)
        donor = record.get("generated_item")
        if donor not in ITEM_DATA:
            raise _invalid("Missing native donor identity.")
        records.append(record)
    return sorted(records, key=lambda record: LOCATIONS.index(record["name"]))


def _action(event):
    from evfl.event import ActionEvent
    if not isinstance(event.data, ActionEvent):
        return None
    return str(event.data.actor.v.identifier), event.data.actor_action.v.v


def _params(event):
    return event.data.params.data if event.data.params else {}


def _retarget(event, old, new):
    from evfl.event import ActionEvent, ForkEvent, JoinEvent, SubFlowEvent, SwitchEvent
    from evfl.util import make_index
    data = event.data
    if isinstance(data, (ActionEvent, JoinEvent, SubFlowEvent)):
        if data.nxt.v is old:
            data.nxt = make_index(new)
    elif isinstance(data, SwitchEvent):
        for key, target in data.cases.items():
            if target.v is old:
                data.cases[key] = make_index(new)
    elif isinstance(data, ForkEvent):
        for index, target in enumerate(data.forks):
            if target.v is old:
                data.forks[index] = make_index(new)
        if data.join.v is old:
            data.join = make_index(new)


def _actors(item):
    from .catalog import ITEM_DATA
    metadata = ITEM_DATA[item]
    return set(metadata.get("tiers", (metadata["actor"],)))


def build_opening_flow(raw, pouch_raw, records, *, get_flags=None):
    """Bypass selected native gifts only; no new grant runs inside Opening."""
    from evfl.util import make_index
    from oot_rando.patching.progressive import FlowEditor

    if not records:
        return raw
    if len({r["name"] for r in records}) != len(records) or any(r["name"] not in LOCATIONS for r in records):
        raise _invalid("Invalid skipped checks.")
    editor = FlowEditor(raw, PATH)
    if editor.chart.name != FLOW:
        raise _invalid("Unexpected opening flow.")
    original_events = list(editor.chart.events)
    gifts = [e for e in original_events if e.name.startswith("OOTRRState")
             and _action(e) == ("PouchSystemActor", GIVE)]
    if len(gifts) != 3 or _params(gifts[0]) != dict(GIFT_PARAMS, Actor="Pouch_Amiibo"):
        raise _invalid("Unexpected skipped-story grant sequence.")
    by_name = {r["name"]: r for r in records}
    actual_actors, selected, retained = {}, [], set()
    for name, vanilla, event in zip(LOCATIONS, VANILLA, gifts[1:]):
        record = by_name.get(name)
        donor = record["generated_item"] if record else None
        params = _params(event)
        actor = params.get("Actor")
        if (not isinstance(actor,str) or not actor
                or (record and actor not in _actors(donor)) or params != dict(GIFT_PARAMS, Actor=actor)):
            raise _invalid("Native donor no longer matches " + name + ".")
        actual_actors[name] = actor
        if record:
            selected.append((record, event))
        else:
            retained.add(actor)
    removed = {"IsGet." + actual_actors[r["name"]] for r, _ in selected
               if actual_actors[r["name"]] not in retained}
    expected=removed if get_flags is None else removed & set(get_flags)
    flags = [e for e in original_events if e.name.startswith("OOTRRState")
             and _action(e) == ("GameDataActor", "EventTriggerSetGameDataBool")
             and _params(e).get("GameDataName") in removed]
    if len(flags)!=len(expected) or {str(_params(e).get("GameDataName")) for e in flags} != expected:
        raise _invalid("Missing skipped-story ownership markers.")
    for event in flags:
        if _params(event) != dict(GameDataName=_params(event)["GameDataName"], Index=-1, Value=True):
            raise _invalid("Unexpected skipped-story ownership write.")
    # Remove only incoming references, preserving every authored node/index.
    # Consecutive ownership writes are resolved together before any mutation.
    bypassed = flags + [event for _, event in selected]
    def following(event):
        seen = set()
        while event in bypassed:
            if event in seen:
                raise _invalid("Cyclic skipped ownership writes.")
            seen.add(event)
            event = event.data.nxt.v
        return event
    for event in bypassed:
        target = following(event)
        for caller in original_events:
            _retarget(caller, event, target)
        for point in editor.chart.entry_points:
            if point.main_event.v is event:
                point.main_event = make_index(target)
    return editor.write("Archipelago skipped-story donor suppression")[0]


def build_reconciliation_flow(raw, records, *, trade_mode=False):
    """Quiet real rewards, called only by the existing ready-player gate."""
    from evfl.entry_point import EntryPoint
    from evfl.event import SubFlowEvent
    from evfl.util import make_index
    from oot_rando.patching.event_info import reachable
    from oot_rando.patching.event_bindings import complete_forwarded_actor_bindings
    from oot_rando.patching.progressive import FlowEditor, link
    from .ap_skulls import _after_writes
    from .catalog import ITEM_DATA, LOCATION_IDS
    from .native_presentations import append_recipe, append_tier_choice, copy_entry
    from .receipt_events import _action as native_action, _silent_grant
    from .restoration import _native_source
    from .shop_tracking import RESULT
    if not records:
        return raw
    editor = FlowEditor(raw, POUCH)
    if editor.chart.name != "GetPouchContent" or any(e.name.startswith(PREFIX) for e in editor.chart.events):
        raise _invalid("Unexpected startup reconciliation flow.")
    grant_entry = None
    if any("local_item" in record for record in records):
        native = FlowEditor(raw, "Native opening inventory source")
        _native_source(native)
        _silent_grant(native, None, entry_name=PREFIX + "GrantSource", prefix=PREFIX + "GrantSource")
        grant_entry = copy_entry(native.chart, editor, PREFIX + "GrantSource", PREFIX + "Grant",
                                 skip=lambda e: native_action(e) in {"EventTriggerSetForGetWindow", "EventTriggerSetHavePlayedGetEvent"})
    following = None
    for record in reversed(records):
        stem = PREFIX + str(LOCATION_IDS[record["name"]])
        settled = _after_writes(editor, stem + "_Committed0", _after_writes(editor, stem + "_Committed1", following))
        dirty = editor.action(stem + "_Dirty", "GameDataActor", "EventTriggerSetGameDataInt",
                              dict(GameDataName=RESULT, Index=-1, Value=-1))
        link(dirty, settled)
        commit = editor.action(stem + "_Flag", "GameDataActor", "EventTriggerSetGameDataBool",
                               dict(GameDataName=record["flag_name"], Index=-1, Value=True))
        link(commit, dirty)
        ready = _after_writes(editor, stem + "_Ready0", _after_writes(editor, stem + "_Ready1", commit))
        reward = ready
        if "local_item" in record:
            metadata = ITEM_DATA[record["local_item"]]
            core_name = stem + "_Pouch"
            recipe = append_recipe(editor, metadata, core_name, grant_entry, ready, pickup=True)
            if isinstance(recipe.data, SubFlowEvent):
                if recipe.data.params:
                    recipe.data.params.data.update(IsShowNumDisplay=False, IsTreasureBox=False)
                    editor.expected[recipe.name] = dict(recipe.data.params.data)
                link(recipe, ready)
            core = EntryPoint(core_name)
            core.main_event = make_index(recipe)
            editor.chart.entry_points.append(core)
            def give(branch, actor):
                return editor.subflow(branch + "_Give", "", core_name, {"ActorName": actor})
            reward = append_tier_choice(editor, metadata, stem, give, no_ammo=ready)
            if trade_mode:
                from .catalog import TRADE_CHECKS
                spent = [r for r in TRADE_CHECKS.values() if r['required_actor']==metadata['actor']]
                if spent:
                    if len(spent)!=1:raise _invalid("Ambiguous consumed trade item.")
                    reward=editor.switch(stem+"_Spent","GameDataActor","EventQueryIsGameDataBool",
                                         dict(GameDataName=spent[0]['flag_name'],Index=-1),ready,reward)
        following = editor.switch(stem + "_Checked", "GameDataActor", "EventQueryIsGameDataBool",
                                  dict(GameDataName=record["flag_name"], Index=-1), following, reward)
    entry = EntryPoint(ENTRY)
    entry.main_event = make_index(following)
    editor.chart.entry_points.append(entry)
    complete_forwarded_actor_bindings(editor.chart)
    for point in editor.chart.entry_points:
        if not point.name.startswith(PREFIX):continue
        for event in reachable(point.main_event.v):
            if isinstance(event.data, SubFlowEvent):
                index = editor.chart.events.index(event)
                if index not in point._sub_flow_event_indices:
                    point._sub_flow_event_indices.append(index)
    if len(editor.chart.events) >= 65535 or len(editor.chart.entry_points) >= 65535:
        raise _invalid("Native event capacity exceeded.")
    return editor.write("Archipelago ready-player startup rewards")[0]


def program_digest(raw):
    """Bind only this module's nodes, ignoring later tracking/native additions."""
    from evfl.common import Argument, ActorIdentifier
    from evfl.event import ActionEvent, SwitchEvent, SubFlowEvent
    from oot_rando.patching.progressive import FlowEditor
    chart = FlowEditor(raw, POUCH).chart
    def value(v):
        if isinstance(v, (Argument, ActorIdentifier)):
            return [type(v).__name__, str(v)]
        if isinstance(v, dict):return {k:value(x) for k,x in v.items()}
        if isinstance(v, (list,tuple)):return [value(x) for x in v]
        return v
    rows = []
    for event in chart.events:
        if not event.name.startswith(PREFIX):continue
        data = event.data
        params = value(data.params.data) if data.params else None
        if isinstance(data, ActionEvent):
            row = [event.name,"action",str(data.actor.v.identifier),data.actor_action.v.v,params,data.nxt.v.name if data.nxt.v else None]
        elif isinstance(data, SwitchEvent):
            row = [event.name,"query",str(data.actor.v.identifier),data.actor_query.v.v,params,{k:v.v.name if v.v else None for k,v in data.cases.items()}]
        elif isinstance(data, SubFlowEvent):
            row = [event.name,"call",data.res_flowchart_name,data.entry_point_name,params,data.nxt.v.name if data.nxt.v else None]
        else:raise _invalid("Unexpected quiet startup node.")
        rows.append(row)
    entries = [[p.name,p.main_event.v.name if p.main_event.v else None,
                [chart.events[i].name for i in p._sub_flow_event_indices]]
               for p in chart.entry_points if p.name.startswith(PREFIX)]
    if not rows or sum(p.name==ENTRY for p in chart.entry_points)!=1:
        raise _invalid("Missing startup reconciliation entry.")
    return hashlib.sha256(json.dumps([rows,entries],sort_keys=True,separators=(",", ":")).encode()).hexdigest()


def _bound(records):
    return [{key: record[key] for key in ("name", "generated_item", "actor", "flag_name")}
            | {"local_item": record.get("local_item")} for record in records]


def _source_fields(raw, records, *, trade_mode=False):
    from oot_rando.formats import byml_codec as by
    from .network_catalog import murmur3
    from .catalog import ITEM_DATA, TRADE_CHECKS
    wanted={r['flag_name'] for r in records}
    if trade_mode:
        actors={ITEM_DATA[r['local_item']]['actor'] for r in records if 'local_item' in r}
        wanted.update(r['flag_name'] for r in TRADE_CHECKS.values() if r['required_actor'] in actors)
    hashes={murmur3(name):name for name in wanted}
    if len(hashes)!=len(wanted):raise _invalid("Colliding source fields.")
    found={key:[] for key in hashes}
    for kind,rows in by.load(raw)['root']['Data'].items():
        if not isinstance(rows,list):continue
        for row in rows:
            if isinstance(row,dict) and row.get('Hash') in found:found[row['Hash']].append((kind,row))
    for matches in found.values():
        if len(matches)!=1:raise _invalid("Missing source state.")
        kind,row=matches[0]
        if (kind!='Bool' or row.get('DefaultValue') is not False
                or row.get('SaveFileIndex')!=0 or row.get('ResetTypeValue')!=8):
            raise _invalid("Nonpersistent source state.")


def _native_get_flags(raw,records):
    """Native start_state writes only IsGet fields present in native Bool data."""
    from oot_rando.formats import byml_codec as by
    from .network_catalog import murmur3
    names={'IsGet.'+actor for r in records for actor in _actors(r['generated_item'])}
    hashes={murmur3(name):name for name in names}
    if len(hashes)!=len(names):raise _invalid("Colliding native ownership fields.")
    result=set()
    for kind,rows in by.load(raw)['root']['Data'].items():
        if not isinstance(rows,list):continue
        for row in rows:
            if not isinstance(row,dict) or row.get('Hash') not in hashes:continue
            name=hashes[row['Hash']]
            if kind!='Bool' or name in result:raise _invalid("Ambiguous native ownership field.")
            result.add(name)
    return result


def prepared_reconciliation(mod, roster, settings, read):
    marker=Path(mod)/MARKER
    if not marker.is_file():return None
    proof=json.loads(marker.read_bytes())
    records=opening_records(roster,settings)
    if (proof.get("schema")!=1 or proof.get("checks")!=_bound(records)
            or proof.get("flow_sha256")!=hashlib.sha256(read(PATH)).hexdigest()
            or proof.get("program_sha256")!=program_digest(read(POUCH))):
        raise _invalid("Changed prepared startup reward proof.")
    return ENTRY


@analysis_scope()
def prepare_opening_rewards(romfs, mod, roster, settings):
    from oot_rando.formats import byml_codec as by
    from oot_rando.game.resource_allocations import grow_resources
    from oot_rando.patching import chest_flags, event_info
    from .engine import run_engine
    from .mod_codec import Codec
    records = opening_records(roster, settings)
    if not records:
        return {"checks": [], "changed": False}
    encoded_settings = settings.get("_seed_settings")
    if not isinstance(encoded_settings, str):
        raise _invalid("Missing canonical settings.")
    options = json.loads(run_engine("settings", {"settings": encoded_settings}))["settings"]
    if options.get("open_kakariko") != "open":
        return {"checks": [], "changed": False}
    romfs, mod = Path(romfs), Path(mod)
    if mod.name != "romfs" or mod.parent.name != "Archipelago":
        raise _invalid("Invalid staged mod.")
    bound = _bound(records)
    @lru_cache(None)
    def frame(path):
        staged = mod / path
        return (staged if staged.is_file() else romfs / path).read_bytes()
    codec = Codec(frame("Pack/ZsDic.pack.zs"))
    @lru_cache(None)
    def read(path):
        return codec.decode(frame(path))
    before = read(PATH)
    _source_fields(read("GameData/GameDataList.Product.110.byml.zs"),records,
                   trade_mode=bool(settings.get('adult_trade_shuffle')))
    marker = mod / MARKER
    if marker.is_file():
        prepared_reconciliation(mod,roster,settings,read)
        return {"checks": [r["name"] for r in records], "changed": False}
    native_gets=_native_get_flags(codec.decode((romfs/"GameData/GameDataList.Product.110.byml.zs").read_bytes()),records)
    after = build_opening_flow(before, read(POUCH), records,get_flags=native_gets)
    quiet = build_reconciliation_flow(read(POUCH), records, trade_mode=bool(settings.get('adult_trade_shuffle')))
    modified = {PATH: after, POUCH: quiet}
    def original(name):
        return read(event_info.flow_path(name))
    def current(name):
        path=event_info.flow_path(name)
        return modified[path] if path in modified else original(name)
    root = by.load(read(chest_flags.EVENT_SETTINGS))["root"]
    # Suppression only removes Opening links. Reconciliation appends new entry
    # bodies without changing existing pouch entry targets, so analyze exactly
    # those new bodies instead of revisiting every receipt/restoration entry.
    from oot_rando.patching.progressive import FlowEditor
    names=[p.name for p in FlowEditor(quiet,POUCH).chart.entry_points if p.name.startswith(PREFIX)]
    added={}
    for name in names:
        calls=event_info.entry_calls(quiet,name)
        if calls:added[('GetPouchContent',name)]=calls
    analyzed, dependencies = event_info.add_subflow_dependencies(read(chest_flags.ANALYZED), root, added, current)
    transitions={}
    for name in names:
        children=event_info.reachable_transitions(('GetPouchContent',name),current)
        if children:transitions[('GetPouchContent',name)]=children
    analyzed, children = event_info.add_child_events(analyzed, root, transitions, current)
    if analyzed != read(chest_flags.ANALYZED):
        modified[chest_flags.ANALYZED] = analyzed
    table, _ = grow_resources(read(REST), {name: max(0, len(raw)-len(read(name))) for name, raw in modified.items()})
    modified[REST] = table
    output = {name: codec.encode(raw, frame(name)) for name, raw in modified.items()}
    proof = dict(schema=1, checks=bound, original_sha256=hashlib.sha256(before).hexdigest(),
                 flow_sha256=hashlib.sha256(after).hexdigest(),program_sha256=program_digest(quiet))
    for name, raw in output.items():
        target = mod / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(proof, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return {"checks": [r["name"] for r in records], "changed": True,
            "dependencies": dependencies, "children": children}
