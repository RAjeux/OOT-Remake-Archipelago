"""Build a room-specific visual RomFS from the effective OOTRR mod, before game launch."""
from .i18n import tr
import copy
from collections import defaultdict
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from .catalog import CHESTS, ITEM_DATA, ITEM_IDS, SHOP_CHECKS, AP_SKULL_CHECKS
from .engine import run_engine
from .mod_codec import Codec

REST = "System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs"
GET = ("Dm_SY_GetInEvent", "GetInEvent_NotTurn_NotNpc")
CHEST_ENTRY = "Success_"
REVISION = 21


def chest_flows(raw, records, *, native_pouch=None, small_raw=None):
    from evfl.entry_point import EntryPoint
    from evfl.util import make_index
    from oot_rando.patching.progressive import FlowEditor, link
    editor = FlowEditor(raw, records[0]["flow"])
    local_entries = {}
    local_rewards = {record["local_reward"] for record in records if record.get("local_reward")}
    if local_rewards:
        if native_pouch is None:
            raise ValueError(tr('Native local-item grant not found.'))
        from .native_presentations import append_local_chests
        local_entries = append_local_chests(editor, native_pouch, local_rewards, small_raw=small_raw)
    names = {e.name for e in editor.chart.entry_points}
    events = {e.name for e in editor.chart.events}
    for r in records:
        name = r["event"]
        target = (local_entries[r["local_reward"]] if r.get("local_reward")
                  else r["entry"] if r.get("legacy") else CHEST_ENTRY)
        if target not in names or name in names or {name, name + "_AP"} & events:
            raise ValueError(tr('Incompatible chest event: ') + r["base"])
        # Open the actual chest and present its AP token through the generic
        # chest path. Item-specific OOTRR entries also grant maps, keys or tiers;
        # never call them when the network owns the entire reward.
        if r.get("local_reward"):
            token = editor.subflow(name, "", target, None)
        elif r.get("legacy"):
            token = editor.subflow(name, "", target, None)
            medal = editor.subflow(name + "_AP", *GET,
                                   {"ActorName": r["actor"], "IsNpcEventStarter": False})
            link(token, medal)
        else:
            token = editor.subflow(name, "", target,
                                   {"ContentName": r["actor"], "IsMiniGame": False})
        entry = EntryPoint(name)
        entry.main_event = make_index(token)
        entry._sub_flow_event_indices = ([len(editor.chart.events)-2, len(editor.chart.events)-1]
                                         if r.get("legacy") else [len(editor.chart.events)-1])
        editor.chart.entry_points.append(entry)
        names.add(name)
        events.update((name, name + "_AP"))
    result, parsed = editor.write(tr('The medal presentation'))
    lookup = {e.name: e for e in parsed.flowchart.entry_points}
    for r in records:
        first = lookup[r["event"]].main_event.v
        if r.get("local_reward"):
            if (first.data.res_flowchart_name, first.data.entry_point_name,
                    first.data.params, first.data.nxt.v) != ("", local_entries[r["local_reward"]], None, None):
                raise ValueError(tr('Invalid local-item presentation.'))
            continue
        if r.get("legacy"):
            last = first.data.nxt.v
            if (first.data.res_flowchart_name, first.data.entry_point_name,
                    last.data.res_flowchart_name, last.data.entry_point_name,
                    last.data.params.data["ActorName"], last.data.nxt.v) != ("", r["entry"], *GET, r["actor"], None):
                raise ValueError(tr('Invalid legacy reward chain.'))
            continue
        if (first.data.res_flowchart_name, first.data.entry_point_name,
                first.data.params.data, first.data.nxt.v) != ("", CHEST_ENTRY,
                {"ContentName": r["actor"], "IsMiniGame": False}, None):
            raise ValueError(tr('Invalid reward chain.'))
    return result


def plan_maps(placements, moved, read, settings_rows, *, preserve_local=True, local_rewards=None):
    from .presentation_models import chest_model_actor
    from oot_rando.formats.byml_writer import patch_strings
    from oot_rando.formats.inspect_resources import Byml
    from oot_rando.patching.ap_item import ap_actor
    from oot_rando.patching.chest_flags import default_event
    from oot_rando.patching.event_info import flow_path
    local_rewards = local_rewards or {}
    requests = defaultdict(dict)
    for name in placements:
        for ref in CHESTS[name]:
            for path in ref["files"]:
                key = int(ref["actor"])
                if key in requests[path] and requests[path][key] != name:
                    raise ValueError(tr('Two locations use the same chest.'))
                requests[path][key] = name
    @lru_cache(None)
    def default_entry(path):
        from oot_rando.patching.event_info import entry_names, flow_name
        entries = entry_names(read(path))
        return next((e for e in (flow_name(path), "EntryPoint0") if e in entries),
                    entries[0] if entries else None)
    maps, wrappers, found = {}, {}, set()
    for path, wanted in sorted(requests.items()):
        raw = read(path)
        edits = []
        for i, a in enumerate(Byml(raw).root.get("Actors", ())):
            name = wanted.get(a.get("Hash"))
            if name is None:
                continue
            if (not a.get("Gyaml", "").startswith("Obj_TBox")
                    and a.get("Gyaml") not in {"Obj_HrlCity_Shop_TBox_A_01", "Obj_HrlCity_Shop_TBox_A_02"}):
                raise ValueError(tr('Unexpected actor for {value0}.', value0=name))
            found.add(name)
            local_reward = local_rewards.get(name)
            actor = ITEM_DATA[local_reward]["actor"] if local_reward else ap_actor(placements[name])
            # A new local AP chest gives through its real-item callback, while
            # its physical guest must have a working native get-item AS.
            # Historical moved chests retain their original native grant path.
            shown = (chest_model_actor(actor) if local_reward and not (preserve_local and name in moved)
                     else actor)
            dyn = a.get("Dynamic", {})
            def change(field, value):
                edits.append({"path": ("Actors", i, "Dynamic", field), "before": dyn.get(field), "after": value})
            if preserve_local and name in moved:
                if dyn.get("Drop__DropActor") != "TBox_Rupee_Green":
                    raise ValueError(tr('The base mod no longer matches the seed: ') + name)
                change("Drop__DropActor", shown)
                if dyn.get("Drop__DropActor_Substitute") == "TBox_Rupee_Green":
                    change("Drop__DropActor_Substitute", shown)
                continue
            if not preserve_local:
                change("Drop__DropActor", shown)
                # An absent substitute also has an actor default to override.
                change("Drop__DropActor_Substitute", shown)
            base = ((dyn.get("GetEventName") or default_event(a["Gyaml"]))
                    if preserve_local else default_event(a["Gyaml"]))
            row = settings_rows.get(base, {})
            flow = row.get("FlowchartFileName", "")
            if not flow.endswith(".evfc"):
                raise ValueError(tr('Unknown chest event: ') + base)
            identity = base + "\0" + actor
            if local_reward:
                identity += "\0local:" + str(ITEM_IDS[local_reward])
            event = "OotrrAP_" + hashlib.sha256(identity.encode()).hexdigest()[:16]
            path_flow = flow_path(flow.rsplit("/", 1)[-1][:-5])
            entry = (row.get("EntryPointName") or default_entry(path_flow)) if preserve_local else CHEST_ENTRY
            wrappers[event] = {"event": event, "base": base, "entry": entry,
                               "flow": path_flow, "actor": actor, "legacy": preserve_local}
            if local_reward:
                wrappers[event]["local_reward"] = local_reward
            change("GetEventName", event)
        if edits:
            maps[path] = patch_strings(raw, edits)
    if found != set(placements):
        raise ValueError(tr('Chest missing from RomFS: ') + ", ".join(sorted(set(placements) - found)))
    return maps, list(wrappers.values())


def event_resources(records, read):
    from oot_rando.formats import byml_codec
    from oot_rando.patching import chest_flags as ch, event_info as info
    if not records:
        return {}
    modified = {}
    native_pouch = small_raw = None
    if any(record.get("local_reward") for record in records):
        native_pouch = read("Event/EventFlow/GetPouchContent.bfevfl.zs")
        small_raw = read("Event/EventFlow/Dm_SY_TreasureboxSmall.bfevfl.zs")
    for path, group in ch.by_flow(records).items():
        modified[path] = chest_flows(read(path), group, native_pouch=native_pouch, small_raw=small_raw)
        variant = path.replace(".bfevfl.zs", ".110.bfevfl.zs")
        try:
            alternate = read(variant)
        except FileNotFoundError:
            continue
        modified[variant] = chest_flows(alternate, group, native_pouch=native_pouch, small_raw=small_raw)
    modified[ch.EVENT_SETTINGS] = ch.add_rows(read(ch.EVENT_SETTINGS), records)
    analyzed, count = ch.add_analyzed_rows(read(ch.ANALYZED), records)
    if count != len(records):
        doc = byml_codec.load(analyzed)
        rows = {row["__RowId"]: row for row in doc["root"]}
        for record in records:
            if record["event"] in rows:
                continue
            if not record.get("legacy"):
                raise ValueError(tr('Chest animation dependencies were not found.'))
            row = copy.deepcopy(rows.get(record["base"], {}))
            row["__RowId"] = record["event"]
            doc["root"].append(row)
        doc["root"].sort(key=lambda row: row["__RowId"])
        analyzed = byml_codec.dump(doc)
    legacy = {record["event"] for record in records if record.get("legacy")}
    if legacy:
        @lru_cache(None)
        def current(name):
            return read(info.flow_path(name))
        if GET[1] not in info.entry_names(current(GET[0])):
            raise ValueError(tr('Missing get-item animation in this game version.'))
        flows = info.closure({GET}, current)
        if info.SWITCH_CALL[0] in flows:
            raise ValueError(tr('Unknown dynamic animation dependency.'))
        doc = byml_codec.load(analyzed)
        rows = {row["__RowId"]: row for row in doc["root"]}
        children = set(info.reachable_transitions(GET, current))
        for child in list(children):
            children.update(rows.get(child, {}).get("ChildEventList", ()))
        for name in legacy:
            row = rows[name]
            for field, extra in (("SubFlowList", flows), ("ChildEventList", children)):
                if extra:
                    row[field] = sorted(set(row.get(field, ())) | extra, key=str.lower)
        analyzed = byml_codec.dump(doc)
    modified[ch.ANALYZED] = analyzed
    return modified


def patch_mod(romfs, mod, roster, moved, *, full_rewards=False, local_items=False):
    from oot_rando.formats import byml_codec
    from oot_rando.game.resource_allocations import add_resources, allocation, grow_resources
    from oot_rando.patching import ap_item
    from oot_rando.patching.chest_flags import EVENT_SETTINGS
    def source(p):
        candidate = mod / p
        return (candidate if candidate.is_file() else romfs / p).read_bytes()

    codec = Codec(source("Pack/ZsDic.pack.zs"))
    last_resource = ""
    def read(p):
        nonlocal last_resource
        last_resource = p
        return codec.decode(source(p))

    labels, placements, local_rewards = {}, {}, {}
    for name, reward in sorted(roster.items()):
        item, player = ((reward["item"], reward["player"]) if isinstance(reward, dict) else reward[:2])
        key = ap_item.ap_item(json.dumps([name, item, player], ensure_ascii=False))
        local = bool(local_items and isinstance(reward, dict) and reward.get("local"))
        # Shop shelves need a unique per-location actor even for local goods.
        # The shop pass replaces its display with the native item presentation.
        if not local or name not in CHESTS:
            labels[key] = (item, player, reward.get("game")) if isinstance(reward, dict) else (item, player)
        if name in CHESTS:
            placements[name] = key
            if local:
                if item not in ITEM_DATA or reward.get("item_id", ITEM_IDS[item]) != ITEM_IDS[item]:
                    raise ValueError(tr('Unknown local Archipelago item: ') + item)
                local_rewards[name] = item
    messages = sorted({p.relative_to(home).as_posix() for home in (romfs, mod)
                       for p in (home / "Mals").glob("*.Product.110.*.zs")})
    if not messages:
        raise ValueError(tr('Game text archives were not found in Mals.'))
    try:
        phase = tr('Reading chest events')
        rows = {row["__RowId"]: row for row in byml_codec.load(read(EVENT_SETTINGS))["root"]}
        phase = tr('Updating chest maps')
        changed, wrappers = plan_maps(placements, moved, read, rows, preserve_local=not full_rewards,
                                      local_rewards=local_rewards)
        phase = tr('Creating chest animations')
        changed.update(event_resources(wrappers, read))
        phase = tr('Creating models and text')
        existing, new = ap_item.build_ap_files(read, labels, messages) if labels else ({}, {})
    except IndexError as exc:
        raise ValueError(tr('{value0} : missing index. Last resource read: {value1}', value0=phase, value1=last_resource)) from exc
    changed.update(existing)
    rest = read(REST)
    growths, sizes = {}, {}
    def write(p, raw, origin):
        path = mod / p
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(codec.encode(raw, origin))
    for p, raw in changed.items():
        origin = source(p)
        growths[p] = max(0, len(raw) - len(codec.decode(origin)))
        write(p, raw, origin)
    for p, (raw, template) in new.items():
        if (mod / p).exists() or (romfs / p).exists():
            raise ValueError(tr('Medal resource already exists: ') + p)
        sizes[p] = max((len(raw) + 8191) & ~4095, allocation(rest, template) or 0)
        write(p, raw, source(template))
    rest, _ = grow_resources(rest, growths)
    rest, _ = add_resources(rest, sizes)
    write(REST, rest, source(REST))


def localize_mod(romfs, mod, seed_settings):
    """Apply this engine's text patches over the external OOTRR base mod."""
    messages = sorted({path.relative_to(home).as_posix() for home in (romfs, mod)
                       for path in (home / "Mals").glob("*.Product.110.sarc.zs") if path.is_file()})
    if not messages:
        raise ValueError(tr('Game text archives were not found in Mals.'))
    result = run_engine("localize", {"settings": seed_settings, "messages": messages}, romfs, mod).strip()
    if result:
        print(result, flush=True)


def prepare(root, settings, roster, moved):
    if settings.get("adult_trade_shuffle") and not roster:
        raise ValueError(tr("Adult trade shuffle requires the connected room's item mapping."))
    if settings.get("shuffle_master_sword") and not roster:
        raise ValueError(tr("Master Sword shuffle requires the connected room's item mapping."))
    base = root / "mods"
    seed_settings = settings.get("_seed_settings")
    if not roster and seed_settings is None:
        return base
    effective = sorted((p.relative_to(base).as_posix(), p.stat().st_size, p.stat().st_mtime_ns)
                       for p in base.rglob("*") if p.is_file())
    full_rewards = settings.get("reward_mode") in ("all_chest_rewards", "all_locations")
    local_items = bool(settings.get("local_items"))
    payload = json.dumps([REVISION, full_rewards, local_items, settings.get("kokiri_shop_checks", False),
                          settings.get("shop_check_mode"), settings.get("shop_checks", []),
                          settings.get("shop_prices", {}), settings.get("shuffle_skulltulas", "off"),
                          bool(settings.get("adult_trade_shuffle")), bool(settings.get("shuffle_master_sword")),
                          settings.get("network_sources_schema"), settings.get("network_sources"),
                          bool(settings.get("shops_always_open")),
                          seed_settings, roster, effective],
                         ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    home = root / "v14"
    home.mkdir(exist_ok=True)
    dest = home / digest[:16]
    if (dest / "mods" / "Archipelago" / "romfs").is_dir():
        return dest / "mods"
    print(tr("Preparing this room's medals and text…"), flush=True)
    with tempfile.TemporaryDirectory(dir=home, prefix="construction-") as tmp:
        stage = Path(tmp) / "version"
        target = stage / "mods"
        shutil.copytree(base, target)
        romfs, mod = Path(settings["romfs"]), target / "Archipelago" / "romfs"
        if roster:
            patch_mod(romfs, mod, roster, moved, full_rewards=full_rewards, local_items=local_items)
            from .ap_shops import prepare_shops
            prepare_shops(romfs, mod, roster, settings)
            if settings.get("adult_trade_shuffle"):
                from .ap_trade import prepare_trade_rewards
                from .trade_events import prepare_trade_events
                prepare_trade_rewards(romfs, mod, roster, settings)
                prepare_trade_events(romfs, mod, roster, settings)
                from .trade_receipts import prepare_trade_receipt_guard
                prepare_trade_receipt_guard(romfs, mod, settings["_ap_token"])
            if settings.get("network_sources_schema"):
                from .network_rewards import prepare_network_rewards
                prepare_network_rewards(romfs, mod, roster, settings)
            elif settings.get("shuffle_skulltulas", "off")!="off":
                from .ap_skulls import prepare_skulls
                prepare_skulls(romfs, mod, roster, settings)
            if settings.get("shuffle_master_sword"):
                from .ap_master_sword import prepare_master_sword
                prepare_master_sword(romfs, mod, roster, settings)
            if settings.get("reward_mode")=="all_locations" and local_items:
                from .restoration import prepare_restoration
                prepare_restoration(romfs, mod, roster, settings=settings)
        if seed_settings is not None:
            localize_mod(romfs, mod, seed_settings)
        if roster and settings.get("network_sources_schema") in (1, 2):
            from .network_offer_texts import prepare_offer_texts
            prepare_offer_texts(romfs, mod, roster, settings)
        from .presentation_models import prepare_receipt_model_aliases
        prepare_receipt_model_aliases(romfs, mod)
        if settings.get("adult_trade_shuffle"):
            from .trade_receipts import finalize_trade_receipts
            finalize_trade_receipts(romfs, mod, settings["_ap_token"])
        stage.rename(dest)
    print(tr('Medals ready.'), flush=True)
    return dest / "mods"
