"""Build a room-specific visual RomFS from the effective OOTRR mod, before game launch."""
import copy
from collections import defaultdict
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from .catalog import CHESTS, ITEM_DATA, ITEM_IDS
from .mod_codec import Codec

REST = "System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs"
GET = ("Dm_SY_GetInEvent", "GetInEvent_NotTurn_NotNpc")
CHEST_ENTRY = "Success_"
REVISION = 4


def chest_flows(raw, records, *, native_pouch=None, small_raw=None):
    from evfl.entry_point import EntryPoint
    from evfl.util import make_index
    from oot_rando.patching.progressive import FlowEditor, link
    editor = FlowEditor(raw, records[0]["flow"])
    local_entries = {}
    local_rewards = {record["local_reward"] for record in records if record.get("local_reward")}
    if local_rewards:
        if native_pouch is None:
            raise ValueError("Remise native des objets locaux introuvable.")
        from .native_presentations import append_local_chests
        local_entries = append_local_chests(editor, native_pouch, local_rewards, small_raw=small_raw)
    names = {e.name for e in editor.chart.entry_points}
    events = {e.name for e in editor.chart.events}
    for r in records:
        name = r["event"]
        target = (local_entries[r["local_reward"]] if r.get("local_reward")
                  else r["entry"] if r.get("legacy") else CHEST_ENTRY)
        if target not in names or name in names or {name, name + "_AP"} & events:
            raise ValueError("Événement de coffre incompatible : " + r["base"])
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
    result, parsed = editor.write("La présentation du médaillon")
    lookup = {e.name: e for e in parsed.flowchart.entry_points}
    for r in records:
        first = lookup[r["event"]].main_event.v
        if r.get("local_reward"):
            if (first.data.res_flowchart_name, first.data.entry_point_name,
                    first.data.params, first.data.nxt.v) != ("", local_entries[r["local_reward"]], None, None):
                raise ValueError("Présentation de l’objet local invalide.")
            continue
        if r.get("legacy"):
            last = first.data.nxt.v
            if (first.data.res_flowchart_name, first.data.entry_point_name,
                    last.data.res_flowchart_name, last.data.entry_point_name,
                    last.data.params.data["ActorName"], last.data.nxt.v) != ("", r["entry"], *GET, r["actor"], None):
                raise ValueError("Chaîne de récompenses historique invalide.")
            continue
        if (first.data.res_flowchart_name, first.data.entry_point_name,
                first.data.params.data, first.data.nxt.v) != ("", CHEST_ENTRY,
                {"ContentName": r["actor"], "IsMiniGame": False}, None):
            raise ValueError("Chaîne de récompenses invalide.")
    return result


def plan_maps(placements, moved, read, settings_rows, *, preserve_local=True, local_rewards=None):
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
                    raise ValueError("Deux emplacements utilisent le même coffre.")
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
            if not a.get("Gyaml", "").startswith("Obj_TBox"):
                raise ValueError(f"Acteur inattendu pour {name}.")
            found.add(name)
            local_reward = local_rewards.get(name)
            actor = ITEM_DATA[local_reward]["actor"] if local_reward else ap_actor(placements[name])
            dyn = a.get("Dynamic", {})
            def change(field, value):
                edits.append({"path": ("Actors", i, "Dynamic", field), "before": dyn.get(field), "after": value})
            if preserve_local and name in moved:
                if dyn.get("Drop__DropActor") != "TBox_Rupee_Green":
                    raise ValueError("Le mod de base ne correspond plus à la seed : " + name)
                change("Drop__DropActor", actor)
                if dyn.get("Drop__DropActor_Substitute") == "TBox_Rupee_Green":
                    change("Drop__DropActor_Substitute", actor)
                continue
            if not preserve_local:
                change("Drop__DropActor", actor)
                # An absent substitute also has an actor default to override.
                change("Drop__DropActor_Substitute", actor)
            base = ((dyn.get("GetEventName") or default_event(a["Gyaml"]))
                    if preserve_local else default_event(a["Gyaml"]))
            row = settings_rows.get(base, {})
            flow = row.get("FlowchartFileName", "")
            if not flow.endswith(".evfc"):
                raise ValueError("Événement de coffre inconnu : " + base)
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
        raise ValueError("Coffre absent du RomFS : " + ", ".join(sorted(set(placements) - found)))
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
                raise ValueError("Dépendances de l’animation de coffre introuvables.")
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
            raise ValueError("Animation de récupération absente de cette version du jeu.")
        flows = info.closure({GET}, current)
        if info.SWITCH_CALL[0] in flows:
            raise ValueError("Dépendance dynamique de l’animation inconnue.")
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
        if not local:
            labels[key] = (item, player)
        if name in CHESTS:
            placements[name] = key
            if local:
                if item not in ITEM_DATA or reward.get("item_id", ITEM_IDS[item]) != ITEM_IDS[item]:
                    raise ValueError("Objet local Archipelago inconnu : " + item)
                local_rewards[name] = item
    messages = sorted({p.relative_to(home).as_posix() for home in (romfs, mod)
                       for p in (home / "Mals").glob("*.Product.110.*.zs")})
    if not messages:
        raise ValueError("Archives des textes du jeu introuvables dans Mals.")
    try:
        phase = "Lecture des événements de coffre"
        rows = {row["__RowId"]: row for row in byml_codec.load(read(EVENT_SETTINGS))["root"]}
        phase = "Modification des cartes de coffre"
        changed, wrappers = plan_maps(placements, moved, read, rows, preserve_local=not full_rewards,
                                      local_rewards=local_rewards)
        phase = "Création des animations de coffre"
        changed.update(event_resources(wrappers, read))
        phase = "Création des modèles et des textes"
        existing, new = ap_item.build_ap_files(read, labels, messages) if labels else ({}, {})
    except IndexError as exc:
        raise ValueError(f"{phase} : index absent. Dernière ressource lue : {last_resource}") from exc
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
            raise ValueError("Ressource de médaillon déjà présente : " + p)
        sizes[p] = max((len(raw) + 8191) & ~4095, allocation(rest, template) or 0)
        write(p, raw, source(template))
    rest, _ = grow_resources(rest, growths)
    rest, _ = add_resources(rest, sizes)
    write(REST, rest, source(REST))


def prepare(root, settings, roster, moved):
    base = root / "mods"
    if not roster:
        return base
    effective = sorted((p.relative_to(base).as_posix(), p.stat().st_size, p.stat().st_mtime_ns)
                       for p in base.rglob("*") if p.is_file())
    full_rewards = settings.get("reward_mode") in ("all_chest_rewards", "all_locations")
    local_items = bool(settings.get("local_items"))
    payload = json.dumps([REVISION, full_rewards, local_items, settings.get("kokiri_shop_checks", False),
                          settings.get("shop_prices", {}), roster, effective], ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    home = root / "v14"
    home.mkdir(exist_ok=True)
    dest = home / digest[:16]
    if (dest / "mods" / "Archipelago" / "romfs").is_dir():
        return dest / "mods"
    print("Préparation des médaillons et des textes de cette salle…", flush=True)
    with tempfile.TemporaryDirectory(dir=home, prefix="construction-") as tmp:
        stage = Path(tmp) / "version"
        target = stage / "mods"
        shutil.copytree(base, target)
        patch_mod(Path(settings["romfs"]), target / "Archipelago" / "romfs", roster, moved,
                  full_rewards=full_rewards, local_items=local_items)
        if settings.get("kokiri_shop_checks"):
            from .ap_shops import prepare_shops
            prepare_shops(Path(settings["romfs"]), target / "Archipelago" / "romfs", roster, settings)
        stage.rename(dest)
    print("Médaillons prêts.", flush=True)
    return dest / "mods"
