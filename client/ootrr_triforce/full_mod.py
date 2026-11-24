"""Prepare full-network resources while retaining the native AP transaction bridge."""
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path

from . import full_ap
from .catalog import ITEM_DATA
from .mod_codec import Codec

NATIVE_METADATA = "Archipelago/full-native-v1.json"


def code_fingerprint():
    import ootrr_full
    from .app_runtime import resource_root
    digest = hashlib.sha256()
    version = resource_root() / "VERSION"
    if version.is_file():
        digest.update(version.read_bytes())
    # Frozen Python modules live inside PYZ. The build manifest binds their
    # exact source digest as well as DLL/WASM/data payloads to cache identity.
    manifest = resource_root() / 'app-manifest.json'
    if manifest.is_file():
        digest.update(manifest.read_bytes())
    native = resource_root() / 'native/archipelago.dll'
    if native.is_file():
        digest.update(hashlib.sha256(native.read_bytes()).digest())
    paths = list(Path(ootrr_full.__file__).parent.rglob('*'))
    paths += [Path(__file__).with_name(name) for name in
              ("full_ap.py", "full_catalog.json", "full_mod.py", "full_events.py", "receipt_events.py", "catalog.py",
               "restoration.py", "native_presentations.py", "upgrade_readiness.py", "full_extra_recovery.py", "full_cows.py",
               "engine.wasm", "full_ammo.py", "upgrade_recovery.py", "upgrade_deathlink.py",
               "full_settings.py", "full_scrub_hints.py", "full_portable.py", "full_allocations.py", "native_player_brain.py", "engine.py", "engine.cjs",
               "ap_trade.py", "trade_events.py", "trade_state.py", "trade_receipts.py")]
    for path in sorted(paths):
        if path.is_file() and path.suffix in {".py", ".json", ".in", ".wasm", ".cjs"} and "__pycache__" not in path.parts:
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:20]


def refresh_artifact(artifact, data):
    """Retain an auditable manifest after native/QoL post-processing."""
    artifact = Path(artifact)
    document = _read_json(artifact / "manifest.json")
    document.setdefault("archipelago", {}).update(token=data["token"], generation_mode=full_ap.FULL_MODE,
                                                catalog_scan=data["catalog_scan"], death_link=bool(data.get('death_link')))
    document["files"] = {path.relative_to(artifact / "romfs").as_posix():
                         {"size": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                         for path in sorted((artifact / "romfs").rglob('*')) if path.is_file()}
    tracking = (artifact / "tracking.json").read_bytes()
    document["tracking"]["sha256"] = hashlib.sha256(tracking).hexdigest()
    (artifact / "manifest.json").write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")


def active_items(data):
    patch = data["full_patch"]
    return sorted({row["item"] for row in patch["placements"].values() if row["own"]}
                  | {row["item"] for row in patch["remote"]} | set(patch.get("precollected", ())))


def receipt_catalog(data):
    """Resolve real physical effects; logical events are never delivery recipes."""
    from ootrr_full.game.remake_world import PROGRESSIVE
    from ootrr_full.patching.ap_mailbox import records
    from ootrr_full.patching.key_adapter import is_small_key, item_folder, small_key_actor
    remote_keys = {}
    if data['full_patch'].get('options', {}).get('individual_smallkeys', False):
        for record in records(data['full_patch']['remote']):
            if is_small_key(record['item']):
                remote_keys.setdefault(record['item'], []).append(record['actor'])
    result = {}
    for name in active_items(data):
        if name in ITEM_DATA:
            row = copy.deepcopy(ITEM_DATA[name])
        else:
            record = records([{"item": name, "player": "recipe", "location": name}])[0]
            row = {"actor": record["actor"], "kind": "FullNetwork", "mode": "pouch"}
        if is_small_key(name) and data['full_patch'].get('options', {}).get('individual_smallkeys', False):
            row.update(mode='small_keys', small_key_tokens=remote_keys.get(name, []),
                       actor=(remote_keys.get(name) or [small_key_actor(item_folder(name), 1)])[0])
        if name in PROGRESSIVE:
            row.update(mode="tiers", tiers=list(PROGRESSIVE[name]), actor=PROGRESSIVE[name][0])
        if name == "Bow":
            row["ensure_capacity"] = ("Item_Quiver_Small", "Item_Quiver_Medium", "Item_Quiver_Large")
        elif name == "Slingshot":
            row["ensure_capacity"] = ("Item_BulletBag_Small", "Item_BulletBag_Medium", "Item_BulletBag_Large")
        row["display_only"] = (row["actor"] in {"Item_Ocarina_Fairy", "Item_Ocarina_Time"}
                               or row["actor"].startswith("Item_Melody_"))
        for prefix, actor in (("Bombs (", "Item_Bomb"), ("Arrows (", "Item_Arrow_Normal"),
                              ("Deku Seeds (", "Item_DekuSeed"), ("Deku Nuts (", "Item_DekuNut")):
            if name.startswith(prefix) and name.endswith(")"):
                amount = name[len(prefix):-1]
                if amount.isdecimal() and 0 < int(amount) <= 999:
                    row.update(grant_actor=actor, grant_amount=int(amount))
                    from ootrr_full.patching.ammo_quantities import quantity_actor
                    row['actor'] = quantity_actor(name)
        result[name] = row
    return result


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _physical_progressive_tokens(data, artifact, generated, tracking, known):
    """Bind a source token to its own physical reward, never a native neighbour."""
    from ootrr_full.patching.progressive import applied_flag, got_flag, token_family
    from ootrr_full.patching.soul_adapter import murmur3
    tokens = ((generated.get("skips") or {}).get("progressive") or {}).get("converter", {}).get("tokens", ())
    if not tokens:
        return {}
    if (not isinstance(tokens, list) or any(not isinstance(token, str) for token in tokens)
            or len(set(tokens)) != len(tokens) or any(not token_family(token) for token in tokens)):
        raise ValueError("The full-network progressive converter is invalid.")
    spoiler = _read_json(Path(artifact) / "spoiler.json")
    rows = {}
    for row in spoiler["placements"]:
        gid = row.get("id")
        if gid not in data["full_patch"]["placements"]:
            continue
        if gid in rows:
            raise ValueError("A full-network physical source appears more than once.")
        rows[gid] = row
    result, assigned = {}, set()
    for gid, placement in data["full_patch"]["placements"].items():
        if not placement["own"]:
            continue
        row = rows.get(gid)
        if row is None:
            raise ValueError("The full-network physical reward metadata is incomplete.")
        actor = row.get("reward_actor") or row.get("actor", "")
        if not isinstance(actor, str):
            raise ValueError("The full-network physical reward actor is invalid.")
        token = actor
        for prefix in ("Obj_Rando_", "Obj_RandoWater_", "Shop_Rando_"):
            if token.startswith(prefix):
                token = token[len(prefix):]
                break
        family = token_family(token)
        if family is None:
            continue
        if (token not in tokens or token in assigned or family != placement["item"]
                or row.get("item") != placement["item"]
                or tracking["checks"][gid].get("actor") != actor
                or tracking["checks"][gid].get("item") != placement["item"]
                or any(murmur3(flag) not in known for flag in (got_flag(token), applied_flag(token)))):
            raise ValueError("The full-network progressive token does not match its physical source.")
        assigned.add(token)
        result[gid] = {"actor": token, "applied": applied_flag(token)}
    return result


def _physical_small_key_tokens(data, artifact, generated, tracking, known):
    """Bind exact saved per-copy effects; collection flags remain source-specific."""
    from ootrr_full.patching.key_adapter import (is_small_key, key_actor_item, small_key_folder,
                                                small_applied_flag, got_flag)
    from ootrr_full.patching.soul_adapter import murmur3
    if not data['full_patch'].get('options', {}).get('individual_smallkeys', False):
        return {}
    prepared = {r['actor'] for r in (generated.get('skips', {}).get('key_items') or {}).get('records', ())
                if r.get('kind') == 'small'}
    rows = {}
    for row in _read_json(Path(artifact) / 'spoiler.json')['placements']:
        if row['id'] in rows:
            raise ValueError('A physical small-key source appears more than once.')
        rows[row['id']] = row
    result, assigned = {}, set()
    for gid, placement in data['full_patch']['placements'].items():
        if not placement['own'] or not is_small_key(placement['item']):
            continue
        row = rows.get(gid, {})
        actor = row.get('reward_actor') or row.get('actor', '')
        if not isinstance(actor, str):
            raise ValueError('The dungeon small-key source actor is invalid.')
        token = actor
        for prefix in ('Obj_Rando_', 'Obj_RandoWater_', 'Shop_Rando_'):
            if token.startswith(prefix):
                token = token[len(prefix):]
                break
        if (small_key_folder(token) is None or token not in prepared or token in assigned
                or key_actor_item(token) != placement['item'] or '_R' in token[len('Item_SKey_'):]
                or row.get('item') != placement['item']
                or tracking['checks'].get(gid, {}).get('actor') != actor
                or tracking['checks'].get(gid, {}).get('item') != placement['item']
                or any(murmur3(flag) not in known for flag in (got_flag(token), small_applied_flag(token)))):
            raise ValueError('The dungeon small-key token does not match its physical source.')
        assigned.add(token)
        result[gid] = {'actor': token, 'applied': small_applied_flag(token)}
    return result


def collection_records(data, artifact, roster, schema):
    """Bind every actual check to a proven, saved Bool and its physical state."""
    from ootrr_full.patching.soul_adapter import murmur3
    catalog = full_ap.load_catalog()
    generated = _read_json(Path(artifact) / "manifest.json")
    tracking = _read_json(Path(artifact) / "tracking.json")
    known = {int(row["Hash"]) for row in schema["Data"]["Bool"] if row.get("SaveFileIndex") == 0}
    tokens = _physical_progressive_tokens(data, artifact, generated, tracking, known)
    small_tokens = _physical_small_key_tokens(data, artifact, generated, tracking, known)
    repeatables = {row["id"]: row for row in tracking.get("repeatables", ())}
    result = []
    for gid, placement in sorted(data["full_patch"]["placements"].items()):
        name = catalog["locations"][gid]
        reward = roster.get(name)
        if (not isinstance(reward, dict) or reward.get("local") is not placement["own"]
                or (placement["own"] and reward.get("item") != placement["item"])):
            raise ValueError("The full-network server reward differs from the player file: " + name)
        progressive = {"progressive_token": tokens[gid]} if gid in tokens else {}
        if gid in small_tokens:
            progressive['small_key_token'] = small_tokens[gid]
        from .catalog import TRADE_CHECKS
        if data.get("adult_trade_shuffle") and name in TRADE_CHECKS:
            flags = [TRADE_CHECKS[name]["flag_name"]]
            if any(murmur3(value) not in known for value in flags):
                raise ValueError("The full-network adult trade flags were not prepared.")
            result.append({"name": name, "id": data["location_ids"][name], "flags": flags, "counters": [],
                           "local": placement["own"], "item": placement["item"] if placement["own"] else None,
                           "wake_talon": TRADE_CHECKS[name]["wake_talon"], "full_network": True, **progressive})
            continue
        row = tracking["checks"][gid].get("collection")
        if not row or row["type"] != "bool":
            raise ValueError("The full-network source has no safe saved collection flag: " + name)
        candidates = ["RandoCheck." + generated["seed_id"][:16] + "." + gid]
        if gid in repeatables:
            candidates.append(repeatables[gid]["flag"])
        extra = catalog["extra"].get(gid, catalog.get("extensions", {}).get(gid, {}))
        if extra.get("native_flag"):
            candidates.append(extra["native_flag"])
        flag = next((value for value in candidates if murmur3(value) == int(row["hash"])), None)
        if flag is None or murmur3(flag) not in known:
            raise ValueError("The full-network collection flag does not match its source: " + name)
        flags = [flag]
        flags.extend(extra.get('native_flags', ()))
        from .full_extra_recovery import additional_flags
        flags.extend(additional_flags(name))
        if any(murmur3(value) not in known for value in flags):
            raise ValueError("The full-network quest state is not available: " + name)
        for variant in catalog["groups"].get(gid, ()):
            original = "IsTreasureBoxOpen." + str(variant["hash"])
            if murmur3(original) not in known:
                raise ValueError("Native chest restoration is unavailable: " + name)
            flags.append(original)
        result.append({"name": name, "id": data["location_ids"][name], "flags": list(dict.fromkeys(flags)),
                       "counters": [], "local": placement["own"],
                       "item": placement["item"] if placement["own"] else None, "wake_talon": False,
                       "full_network": True, **progressive})
    if len(result) != len(data["checks"]):
        raise ValueError("The full-network collection list is incomplete.")
    return result


def build(root, settings, data):
    full_ap.require_playable_start(data)
    import sys
    if settings.get("generation_process", getattr(sys, "frozen", False)):
        from .full_worker import run_stage
        from .app_runtime import resource_root
        clean = {key: value for key, value in settings.items() if key not in {"_progress", "_cancel"}}
        return run_stage("build", (root, clean, data), resource_root(),
                         progress=settings.get("_progress"), cancel=settings.get("_cancel"))
    return _build_cached(root, settings, data)


def _build_cached(root, settings, data):
    """Build into the private cache, leaving installed games and saves untouched."""
    full_ap.require_playable_start(data)
    import tempfile
    full_ap.validate_manifest(data)
    root = Path(root)
    output = root / "mods" / "Archipelago"
    if output.exists():
        marker = output / "full-player.json"
        if marker.is_file() and _read_json(marker).get("token") == data["token"]:
            refresh_native_player_brains(output, settings, data)
            refresh_small_key_poses(output, settings, data)
            return
        raise ValueError("The cached full-network mod is incomplete or belongs to another room.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=settings.get('_work_root', root), prefix="full-build-") as temporary:
        staged = Path(temporary) / "Archipelago"
        _build_into(staged, settings, data)
        staged.rename(output)


def _build_into(output, settings, data):
    from ootrr_full.archipelago.bridge import settings_from_patch
    from ootrr_full.randomizer.randomizer_core import generate
    from .native_setup import bind_romfs
    from .app_runtime import resource_root
    import shutil
    configuration = settings_from_patch(data["full_patch"], bool(settings.get("skulltulas_always_present")))
    generate(settings.get("game_source") or settings["romfs"], output, configuration, progress=print)
    from .full_cows import prepare_cows
    prepare_cows(Path(settings["romfs"]), output, data)
    if data.get("adult_trade_shuffle"):
        from .trade_state import prepare_trade_state
        from .catalog import TRADE_CHECKS
        from ootrr_full.patching.soul_adapter import murmur3
        prepare_trade_state(Path(settings["romfs"]), output / "romfs", data)
        tracking = _read_json(output / "tracking.json")
        for gid in data["full_patch"]["placements"]:
            name = full_ap.load_catalog()["locations"][gid]
            if name in TRADE_CHECKS:
                tracking["checks"][gid]["collection"] = {"type": "bool", "hash": str(murmur3(TRADE_CHECKS[name]["flag_name"]))}
        (output / "tracking.json").write_text(json.dumps(tracking, ensure_ascii=False, indent=2), encoding="utf-8")
    from .full_ammo import prepare_ammunition
    prepare_ammunition(Path(settings['romfs']), output, data)
    from .full_portable import prepare_portable
    portable = prepare_portable(Path(settings['romfs']), output, data,
                                game_source=settings.get('game_source') or settings['romfs'])
    from .full_settings import prepare_settings
    full_settings = prepare_settings(Path(settings['romfs']), output, data,
                                     game_source=settings.get('game_source') or settings['romfs'])
    if not settings.get('native'):
        from .upgrade_recovery import prepare_external_recovery
        prepare_external_recovery(Path(settings['romfs']), output, data,
                                  game_source=settings.get('game_source') or settings['romfs'])
    if settings.get("native"):
        bind_romfs(Path(settings["romfs"]), output / "romfs", data, settings.get("baseline", 0))
        shutil.copy2(resource_root() / "native/archipelago.dll", output / "archipelago.dll")
    if settings.get('native'):
        # C hosts already guard receipts on the game thread. Keep the Player's
        # original AI contract; the external readiness publisher can stall the
        # native fishing-rod handover even with no network receipt pending.
        from .native_player_brain import prepare_native_player_brains
        native_brain, _, _ = prepare_native_player_brains(
            Path(settings['romfs']), output, data['token'],
            game_source=settings.get('game_source') or settings['romfs'])
        readiness = None
    else:
        from .upgrade_readiness import prepare_external_readiness
        readiness = prepare_external_readiness(Path(settings["romfs"]), output / "romfs", data["token"])
    generated = _read_json(output / "manifest.json")
    generated["portable_settings"] = portable
    generated["full_settings"] = full_settings
    if settings.get('native'):
        generated['native_player_brain'] = native_brain
        generated.pop('external_readiness', None)
    else:
        generated["external_readiness"] = readiness
    if not settings.get('native'):
        from .upgrade_deathlink import prepare_external_deathlink
        from ootrr_full.randomizer.randomizer_core import save_marker
        generated['external_deathlink'] = prepare_external_deathlink(
            Path(settings['romfs']), output / 'romfs', data['token'], seed_marker=save_marker(generated),
            enabled=bool(data.get('death_link')))
    refresh_small_key_poses(output, settings, data, refresh=False)
    from .full_allocations import prepare_allocations
    generated['resource_allocations'] = prepare_allocations(
        Path(settings['romfs']), output, game_source=settings.get('game_source') or settings['romfs'])
    (output / "manifest.json").write_text(json.dumps(generated, ensure_ascii=False, indent=2), encoding="utf-8")
    refresh_artifact(output, data)
    (output / "full-player.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def refresh_native_player_brains(artifact, settings, data):
    """Repair old native caches without changing placements, receipts or saves."""
    if not settings.get('native'):
        return ()
    from .native_player_brain import prepare_native_player_brains
    artifact = Path(artifact)
    metadata, _, changed = prepare_native_player_brains(
        Path(settings['romfs']), artifact, data['token'],
        game_source=settings.get('game_source') or settings['romfs'])
    generated = _read_json(artifact / 'manifest.json')
    if (not changed and generated.get('native_player_brain') == metadata
            and 'external_readiness' not in generated):
        return ()
    if changed:
        from .full_allocations import prepare_allocations
        generated['resource_allocations'] = prepare_allocations(
            Path(settings['romfs']), artifact,
            game_source=settings.get('game_source') or settings['romfs'])
    generated['native_player_brain'] = metadata
    generated.pop('external_readiness', None)
    (artifact / 'manifest.json').write_text(json.dumps(generated, ensure_ascii=False, indent=2), encoding='utf8')
    refresh_artifact(artifact, data)
    return changed


def refresh_small_key_poses(artifact, settings, data, *, refresh=True):
    """Give generated small keys their native get pose, including cached seeds.

    The medallion template's DemoDummy leaves the key mesh above the camera.
    Copy only native animation references/resources; the saved actor identity,
    pickup callbacks and per-copy effects remain bound to their source.
    """
    if not data['full_patch'].get('options', {}).get('individual_smallkeys', False):
        return []
    from ootrr_full.formats import byml_codec
    from ootrr_full.formats.inspect_resources import sarc
    from ootrr_full.patching.key_adapter import small_key_folder, small_key_pose_parts
    artifact = Path(artifact)
    manifest = _read_json(artifact / 'manifest.json')
    actors = [row['actor'] for row in (manifest.get('skips', {}).get('key_items') or {}).get('records', ())
              if row.get('kind') == 'small']
    if not actors:
        return []
    romfs, mod = Path(settings['romfs']), artifact / 'romfs'
    codec = Codec((romfs / 'Pack/ZsDic.pack.zs').read_bytes())
    game_source = Path(settings.get('game_source') or settings['romfs'])
    if game_source.is_file():
        from ootrr_full.formats.inspect_nup import Nup
        source = Nup(game_source)
        try:
            pose = small_key_pose_parts(lambda path: codec.decode(source.read(source.latest('romfs/' + path))))
        finally:
            source.stream.close()
    else:
        pose = small_key_pose_parts(lambda path: codec.decode((game_source / path).read_bytes()))
    if pose is None:
        raise ValueError('The native dungeon small-key item-get pose is missing.')
    files, refs, info = pose
    changed = []
    for actor in actors:
        if small_key_folder(actor) is None:
            raise ValueError('Invalid dungeon small-key pose actor.')
        relative = f'Pack/Actor/{actor}.pack.zs'
        path = mod / relative
        compressed = path.read_bytes()
        pack = sarc(codec.decode(compressed))
        param_path = f'Actor/{actor}.engine__actor__ActorParam.bgyml'
        param = byml_codec.load(pack[param_path])
        if (all(param['root']['Components'].get(key) == value for key, value in refs.items())
                and all(pack.get(name) == raw for name, raw in files.items())):
            continue
        param['root']['Components'].update(refs)
        pack.update(files)
        pack[param_path] = byml_codec.dump(param)
        path.write_bytes(codec.encode(byml_codec.build_sarc(pack), compressed))
        changed.append(relative)
    from ootrr_full.patching.soul_adapter import RSDB_FILES
    info_path = mod / RSDB_FILES['ActorInfo']
    compressed_info = info_path.read_bytes()
    document = byml_codec.load(codec.decode(compressed_info))
    rows = {row['__RowId']: row for row in document['root']}
    info_changed = False
    for actor in actors:
        for key, value in info.items():
            if rows[actor].get(key) != value:
                rows[actor][key] = value
                info_changed = True
    if info_changed:
        info_path.write_bytes(codec.encode(byml_codec.dump(document), compressed_info))
        changed.append(RSDB_FILES['ActorInfo'])
    if changed and refresh:
        from .full_allocations import prepare_allocations
        manifest['resource_allocations'] = prepare_allocations(
            romfs, artifact, game_source=settings.get('game_source') or settings['romfs'])
        (artifact / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        refresh_artifact(artifact, data)
    return changed


def prepare(root, settings, roster, data):
    full_ap.require_playable_start(data)
    import sys
    if settings.get("generation_process", getattr(sys, "frozen", False)):
        from .full_worker import run_stage
        from .app_runtime import resource_root
        clean = {key: value for key, value in settings.items() if key not in {"_progress", "_cancel"}}
        return run_stage("prepare", (root, clean, roster, data), resource_root(),
                         progress=settings.get("_progress"), cancel=settings.get("_cancel"))
    return _prepare_cached(root, settings, roster, data)


def _prepare_cached(root, settings, roster, data):
    """Add cursor-bound receipts and older-save recovery to the generated mod."""
    full_ap.require_playable_start(data)
    from oot_rando.formats import byml_codec
    from .receipt_events import prepare_receipts
    from .restoration import prepare_restoration
    import shutil
    import tempfile
    root = Path(root)
    source = root / "mods"
    refresh_native_player_brains(source / 'Archipelago', settings, data)
    refresh_small_key_poses(source / 'Archipelago', settings, data)
    payload = json.dumps([data["token"], roster, code_fingerprint()], sort_keys=True, ensure_ascii=False)
    cache = root / "full-native" / hashlib.sha256(payload.encode()).hexdigest()[:20]
    final = cache / "mods"
    if (final / "Archipelago/romfs" / NATIVE_METADATA).is_file():
        refresh_native_player_brains(final / 'Archipelago', settings, data)
        return final
    cache.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=settings.get('_work_root', cache.parent), prefix="prepare-") as temporary:
        staged = Path(temporary) / "completed"
        shutil.copytree(source, staged / "mods")
        artifact = staged / "mods/Archipelago"
        romfs, mod = Path(settings["romfs"]), artifact / "romfs"
        codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
        game_data = mod / "GameData/GameDataList.Product.110.byml.zs"
        schema = byml_codec.load(codec.decode(game_data.read_bytes()))["root"]
        records = collection_records(data, artifact, roster, schema)
        recipes = receipt_catalog(data)
        from .full_events import prepare_gift_guards
        prepare_gift_guards(romfs, artifact, records)
        prepare_receipts(romfs, mod, data, item_data=recipes, item_ids=data["item_ids"])
        if data.get("adult_trade_shuffle"):
            from .ap_trade import trade_records, prepare_trade_rewards
            from .trade_events import prepare_trade_events
            from ootrr_full.patching.ap_item import ap_actor, ap_item
            trade = trade_records(roster, require_all=True, item_data=recipes, item_ids=data["item_ids"])
            source_tokens = {record['name']: record['small_key_token'] for record in records
                             if record.get('small_key_token')}
            by_name = {full_ap.load_catalog()["locations"][gid]: row for gid, row in data["full_patch"]["placements"].items()}
            for record in trade:
                if record['name'] in source_tokens:
                    record['small_key_token'] = source_tokens[record['name']]
                if not record["local"]:
                    placed = by_name[record["name"]]
                    record["actor"] = ap_actor(ap_item(placed["item"] + " (" + placed.get("player", "?") + ")"))
            prepare_trade_rewards(romfs, mod, roster, records=trade, item_data=recipes, item_ids=data["item_ids"])
            prepare_trade_events(romfs, mod, roster, {"adult_trade_shuffle": True})
            from .trade_receipts import prepare_trade_receipt_guard
            prepare_trade_receipt_guard(romfs, mod, data['token'])
        prepare_restoration(romfs, mod, roster, records=records, item_data=recipes,
                            location_ids=data["location_ids"])
        if data.get("adult_trade_shuffle"):
            from .trade_receipts import finalize_trade_receipts
            finalize_trade_receipts(romfs, mod, data["token"])
        metadata = {"version": 1, "token": data["token"], "records": records,
                    "seed_marker": int(_read_json(artifact / "tracking.json")["seed_marker"]),
                    "item_ids": {name: data["item_ids"][name] for name in recipes}}
        marker = mod / NATIVE_METADATA
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(metadata, sort_keys=True), encoding="utf-8")
        from .full_allocations import prepare_allocations
        allocations = prepare_allocations(romfs, artifact, game_source=settings.get('game_source') or settings['romfs'])
        generated = _read_json(artifact / 'manifest.json')
        generated['resource_allocations'] = allocations
        (artifact / 'manifest.json').write_text(json.dumps(generated, ensure_ascii=False, indent=2), encoding='utf-8')
        refresh_artifact(artifact, data)
        staged.rename(cache)
    return final


def session_catalog(data, prepared):
    from ootrr_full.patching.soul_adapter import murmur3
    from .restoration import prepared_locations
    document = _read_json(Path(prepared) / NATIVE_METADATA)
    if document.get("version") != 1 or document.get("token") != data["token"]:
        raise ValueError("The native full-network cache belongs to a different player file.")
    rows = {row["name"]: row for row in document["records"]}
    if set(rows) != set(data["checks"]):
        raise ValueError("The native full-network cache has missing or additional checks.")
    flags = {name: [murmur3(value) for value in rows[name]["flags"]] for name in rows}
    recovery = prepared_locations(Path(prepared), rows, location_ids=data["location_ids"])
    marker = document.get("seed_marker")
    if type(marker) is not int or not 0 < marker < 1 << 32:
        raise ValueError("The native full-network save marker is missing.")
    return document["item_ids"], data["location_ids"], flags, recovery, marker
