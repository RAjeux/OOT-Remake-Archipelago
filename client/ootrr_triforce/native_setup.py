"""Install the opt-in runtime for a local Windows build, and bind one mod to one room."""
from .i18n import tr, detect_language
from .app_runtime import resource_root
from .item_names import item_names
import base64
import ctypes
import json
import hashlib
import mmap
import os
from pathlib import Path
import shutil
import sys
import uuid

from .catalog import CHESTS, CHECK_FLAGS, SHOP_CHECKS, AP_SKULL_CHECKS, SKULL_CHECKS, LEGACY_GAME, ITEM_IDS, LOCATION_IDS, PROTOCOL
from .medallions import REST
from .mod_codec import Codec
from .save_bridge import atomic, write_json

GAME_DATA = "GameData/GameDataList.Product.110.byml.zs"
MARKER = "Archipelago/room-v1.txt"
BUILD_MARK = b"OOTRR-AP native ABI 1"
RT_FILES = ("ootrr_archipelago.inc", "ootrr_ap_items.inc", "ootrr_ap_digest.h")
MENU_FILES = ("ootrr_ap_menu.inc",)
MENU_BUILD_MARK = b"ootrr_ap_menu16"
BOOTSTRAP = '    hos_mods_init(image);\n#ifdef _WIN32\n    if (!ap_boot16()) {\n        ap_boot_error16();\n        return 3;\n    }\n#endif\n'
# Retain the exact old hook only to upgrade existing installations safely.
LEGACY_BOOTSTRAP = '    hos_mods_init(image);\n#ifdef _WIN32\n    if (!ap_boot16()) {\n        hos_log("OOTRR-AP native ABI 1: activation impossible. Voir archipelago-jeu.log ou relancer la configuration.");\n        MessageBoxW(NULL,L"Le mod Archipelago est actif, mais sa salle ou son module est indisponible. Ferme l’ancien client et relance la configuration du mod.", L"Archipelago", MB_OK | MB_ICONERROR);\n        return 3;\n    }\n#endif\n'


def cursor_hash(token):
    from oot_rando.patching.soul_adapter import murmur3
    return murmur3("Archipelago.ReceivedIndex." + token)


def add_cursor(raw, token, baseline):
    from .cursor_resource import append_saved_index
    return append_saved_index(raw,cursor_hash(token),baseline)


def bind_romfs(source, mod, data, baseline):
    from oot_rando.game.resource_allocations import grow_resources
    codec = Codec((source / "Pack/ZsDic.pack.zs").read_bytes())
    def read(p):
        f = mod / p
        return (f if f.is_file() else source / p).read_bytes()
    def put(p,b):
        f=mod/p
        f.parent.mkdir(parents=True,exist_ok=True)
        f.write_bytes(b)
    frame=read(GAME_DATA)
    before=codec.decode(frame)
    after=add_cursor(before,data["token"],baseline)
    if data.get("shuffle_master_sword"):
        from .master_sword import LOCATION as MASTER_SWORD_LOCATION
        from .cursor_resource import append_saved_bool
        after=append_saved_bool(after,CHECK_FLAGS[MASTER_SWORD_LOCATION][0])
    if data.get("kokiri_shop_checks") or data.get("shop_check_mode") in ("special_deals", "randomized_stock"):
        from .cursor_resource import append_saved_bool
        from .ap_shops import selected_shops
        selected=sorted(selected_shops(data["checks"], data))
        if data.get("network_sources_schema")==1 and data.get("shop_check_mode")=="randomized_stock":
            from .cursor_resource import append_saved_bools
            after=append_saved_bools(after,[SHOP_CHECKS[name]["flag"] for name in selected])
        else:
            for name in selected:
                after=append_saved_bool(after,SHOP_CHECKS[name]["flag"])
    from .network_catalog import enabled, callback_sources, source_flags
    network = enabled(data)
    skulls=set(data.get("checks", ())).intersection(AP_SKULL_CHECKS) if not network else set()
    if skulls:
        from .ap_skulls import SCRATCH, NATIVE_SCRATCH
        from .cursor_resource import append_saved_bool, append_transient_string64
        from oot_rando.patching.soul_adapter import murmur3
        for name in sorted(skulls):
            after=append_saved_bool(after,SKULL_CHECKS[name]["flag"])
        after=append_transient_string64(after,murmur3(SCRATCH))
        after=append_transient_string64(after,murmur3(NATIVE_SCRATCH))
    if network:
        from .ap_skulls import SCRATCH, NATIVE_SCRATCH
        from .cursor_resource import append_saved_bools, append_transient_string64
        from .network_catalog import murmur3
        after=append_saved_bools(after, [source_flags(name)[0] for name in callback_sources(data["checks"], data)])
        after=append_transient_string64(after,murmur3(SCRATCH))
        after=append_transient_string64(after,murmur3(NATIVE_SCRATCH))
    table=read(REST)
    updated,_=grow_resources(codec.decode(table),{GAME_DATA:max(len(after)-len(before),0)})
    put(REST,codec.encode(updated,table))
    put(GAME_DATA,codec.encode(after,frame))
    put(MARKER,(data["token"]+"\n").encode("ascii"))


def patch_source(original):
    text=original.decode("utf-8")
    nl="\r\n" if "\r\n" in text else "\n"
    text=text.replace("\r\n","\n")
    normalized=text
    text=text.replace(LEGACY_BOOTSTRAP,BOOTSTRAP)
    anchors=[
        ("static void oot_update_player_cheats(Ctx *c, uint64_t actor, uint64_t components) {",
         '#include "ootrr_archipelago.inc"\n\nstatic void oot_update_player_cheats(Ctx *c, uint64_t actor, uint64_t components) {'),
        ("    oot_inventory_refresh(c, now);","    oot_inventory_refresh(c, now);\n    if (ap_player16(c, actor, components, now)) ap_tick16(c, now);"),
        ("    hos_mods_init(image);",BOOTSTRAP)]
    prior=[new in text for _,new in anchors]
    if all(prior) and text.count("ap_tick16(")==1 and text.count("ap_player16(")==1 and text.count("ap_boot16(")==1:
        return original if text==normalized else text.replace("\n",nl).encode("utf-8")
    required=("oot_gd_int(", "oot_gd_set(", "oot_flag_state(", "oot_item_give(", "oot_item_get(", "oot_gamedata_bool(", "oot_capacity(", "oot_singleton(", "oot_pouch_count(", "hos_oot_is_player(", "hos_user_dir")
    # Upgrade the exact installed 0.1.6 hook without duplicating the bootstrap.
    previous="    oot_inventory_refresh(c, now);\n    ap_tick16(c, now);"
    if prior[0] and prior[2] and text.count(previous)==1 and text.count("ap_tick16(")==1 and text.count("ap_boot16(")==1 and all(name in text for name in required) and "ap_player16(" not in text:
        return text.replace(previous,anchors[1][1],1).replace("\n",nl).encode("utf-8")
    if any(prior) or "ap_boot16(" in text or not all(name in text for name in required) or any(text.count(old)!=1 for old,_ in anchors):
        raise ValueError(tr("This port's sources do not expose the required functions. The port was not modified."))
    for old,new in anchors:
        text=text.replace(old,new,1)
    return text.replace("\n",nl).encode("utf-8")


def protect_password(value):
    if not value:
        return ""
    from ctypes import wintypes as w
    class Blob(ctypes.Structure): _fields_=[("size",w.DWORD),("data",ctypes.c_void_p)]
    raw=value.encode("utf-8")
    buf=ctypes.create_string_buffer(raw)
    inp=Blob(len(raw),ctypes.cast(buf,ctypes.c_void_p))
    out=Blob()
    protect=ctypes.WinDLL("crypt32",use_last_error=True).CryptProtectData
    protect.argtypes=[ctypes.POINTER(Blob),w.LPCWSTR,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,w.DWORD,ctypes.POINTER(Blob)]
    if not protect(ctypes.byref(inp),"OOTRR Archipelago",None,None,None,1,ctypes.byref(out)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return base64.b64encode(ctypes.string_at(out.data,out.size)).decode()
    finally:
        free=ctypes.WinDLL("kernel32").LocalFree
        free.argtypes=[ctypes.c_void_p]
        free(out.data)


def install_tools(base, chooser, configured=None):
    from .menu_setup import patch_renderer
    bundle=resource_root()/"native"
    guess=Path(configured) if configured else base.parent/"Programs/Triforce/tools"
    if not (guess/"host/hos_main.c").is_file():
        guess=chooser(tr('Choose the Triforce tools folder containing host and nx2'),folder=True)
    host=guess/"host"
    source=host/"hos_main.c"
    orig=source.read_bytes()
    new=patch_source(orig)
    if not (guess/"nx2/build.py").is_file() or "HOS_SHARE_NOTICE" not in (guess/"gpu/vk/vk_api.h").read_text(encoding="utf-8"):
        raise ValueError(tr('Triforce tools are incompatible with the native client.'))
    applet=host/"nn_applet.c"
    if not applet.is_file() or "const char *hos_desired_language(void)" not in applet.read_text(encoding="utf-8"):
        raise ValueError(tr('Triforce tools are incompatible with the native client.'))
    helpers={n:(bundle/n).read_bytes() for n in RT_FILES}
    renderer=guess/"gpu/vk/vk_menu.cpp"
    if not renderer.is_file():
        raise ValueError(tr('Triforce tools are incompatible with the native client.'))
    renderer_original=renderer.read_bytes()
    renderer_updated=patch_renderer(renderer_original)
    menu_helpers={n:(bundle/n).read_bytes() for n in MENU_FILES}
    digest=hashlib.sha256((bundle/"archipelago.dll").read_bytes()).digest()
    expected=("static const unsigned char ap_dll_sha16[32] = {"+",".join(map(str,digest))+"};\n").encode()
    if helpers["ootrr_ap_digest.h"]!=expected:
        raise ValueError(tr("The ZIP's native module is incomplete or does not match this version."))
    if new!=orig:
        backup=source.with_name("hos_main.before-archipelago-"+hashlib.sha256(orig).hexdigest()[:12]+".bak")
        if not backup.exists():
            shutil.copy2(source,backup)
    if renderer_updated!=renderer_original:
        backup=renderer.with_name("vk_menu.before-archipelago-"+hashlib.sha256(renderer_original).hexdigest()[:12]+".bak")
        if not backup.exists():
            shutil.copy2(renderer,backup)
    for n,raw in helpers.items():
        path=host/n
        if not path.exists() or path.read_bytes()!=raw:
            atomic(path,raw)
    for n,raw in menu_helpers.items():
        path=renderer.parent/n
        if not path.exists() or path.read_bytes()!=raw:
            atomic(path,raw)
    if renderer_updated!=renderer_original:
        atomic(renderer,renderer_updated)
    if new!=orig:
        atomic(source,new)
    return guess


def save_session(root, config, data, roster, *, prepared=None):
    old=root/"native-session.json"
    previous=json.loads(old.read_bytes()) if old.is_file() else {}
    checks={}
    from .network_catalog import enabled, check_flags
    network = enabled(data)
    for n in data["checks"]:
        row=roster.get(n,("",""))
        item,owner=(row["item"],row["player"]) if isinstance(row,dict) else row
        checks[LOCATION_IDS[n]]=dict(Name=n,Flags=check_flags(n, network=True) if network else CHECK_FLAGS[n],Item=item,Owner=owner)
        if isinstance(row,dict):
            checks[LOCATION_IDS[n]]["ItemID"]=row.get("item_id",0)
            checks[LOCATION_IDS[n]]["Recipient"]=row.get("owner",0)
        if isinstance(row,dict) and row.get("game"):
            checks[LOCATION_IDS[n]]["Game"]=row["game"]
    recovery=[]
    if prepared is not None and data.get("local_items") and data.get("reward_mode")=="all_locations":
        from .restoration import prepared_locations
        recovery=prepared_locations(prepared,data["checks"])
        if recovery:
            for name in data["checks"]:
                row=roster.get(name)
                if (not isinstance(row,dict) or type(row.get("item_id")) is not int or row["item_id"]<=0
                        or type(row.get("owner")) is not int or row["owner"]<=0
                        or type(row.get("local")) is not bool or row["local"]!=(row["owner"]==data["player"])
                        or (row["local"] and ITEM_IDS.get(row["item"])!=row["item_id"])):
                    raise ValueError(tr("Invalid Archipelago restoration metadata."))
    trade_replay = {}
    if prepared is not None and data.get("adult_trade_shuffle"):
        from .trade_receipts import prepared_trade_receipts
        trade_replay = prepared_trade_receipts(prepared, data["token"])
        if trade_replay and (not data.get("local_items") or data.get("reward_mode") != "all_locations"
                             or not set(trade_replay.values()) <= set(recovery)
                             or not set(trade_replay.values()) <= set(checks)):
            raise ValueError(tr("Invalid adult trade replay capability."))
    doc=dict(Room=data["room"],Slot=data["slot"],Game=data.get("game",LEGACY_GAME),Token=data["token"],Player=data["player"],Protocol=PROTOCOL,
             RewardMode=data.get("reward_mode","legacy_gear"),
             LocalItems=bool(data.get("local_items",False)),
             Server=config["server"],ProtectedPassword=config["protected"],UUID=previous.get("UUID") or str(uuid.uuid4()),
             AutoConnect=previous.get("AutoConnect",True),
             CursorHash=cursor_hash(data["token"]),Baseline=config["baseline"],DeathLink=bool(data.get("death_link",False)),
             Language=detect_language(root,config),
             ItemNames={ITEM_IDS[n]:names for n,names in item_names().items() if n in ITEM_IDS},
             Items={i:n for n,i in ITEM_IDS.items()},Checks=checks,RecoveryLocations=recovery)
    if trade_replay:
        doc["TradeReplayReceipts"] = trade_replay
    write_json(old,doc)


def runtime_cache_name(baseline):
    from importlib import resources
    bundle=resource_root()/"native/archipelago.dll"
    digest=hashlib.sha256(bundle.read_bytes())
    version=resource_root()/"VERSION"
    if getattr(sys, "frozen", False) and version.is_file():
        digest.update(version.read_bytes())
    for source in sorted(resources.files(__package__).iterdir(), key=lambda path:path.name):
        if source.is_file() and source.name.endswith((".py", ".cjs", ".wasm", ".json")):
            digest.update(source.name.encode("utf-8")); digest.update(source.read_bytes())
    return "jeu-016-mod-"+str(baseline)+"-"+digest.hexdigest()[:16]


def compiled_executable(romfs, tools=None):
    bundle=resource_root()/"native/archipelago.dll"
    try:
        module=bundle.read_bytes()
    except OSError:
        return None
    if not module:
        return None
    expected=hashlib.sha256(module).digest()
    helpers = [Path(tools)/"host"/name for name in RT_FILES] if tools else []
    menu_helpers = ([Path(tools)/"gpu/vk"/name for name in (*MENU_FILES,"vk_menu.cpp")]
                    if tools else [])
    if any(not helper.is_file() for helper in (*helpers,*menu_helpers)):
        return None
    for path in (romfs.parent/"Triforce.exe",romfs.parent/"bin/Triforce.exe"):
        renderer=path.parent/"triforce_vk.dll"
        if path.is_file() and path.stat().st_size and renderer.is_file() and renderer.stat().st_size:
            with path.open("rb") as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as binary:
                if (binary.find(BUILD_MARK)>=0 and binary.find(expected)>=0
                        and all(helper.stat().st_mtime_ns<=path.stat().st_mtime_ns for helper in helpers)
                        and all(helper.stat().st_mtime_ns<=renderer.stat().st_mtime_ns for helper in menu_helpers)):
                    with renderer.open("rb") as vf,mmap.mmap(vf.fileno(),0,access=mmap.ACCESS_READ) as menu_binary:
                        if menu_binary.find(MENU_BUILD_MARK)>=0:
                            return path
    return None


def compiled_game(romfs, tools=None):
    return compiled_executable(romfs, tools) is not None
