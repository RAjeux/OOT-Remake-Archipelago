"""Pinned Hookshot 3.0.1 host adapter, built from private copies of its tools.

The shared network DLL and receipt transaction stay unchanged. Hookshot owns a
separate profile namespace and uses its native text fields for connection edits.
"""
import hashlib
import json
import mmap
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .app_runtime import resource_root, spawn_process
from .i18n import tr
from .save_bridge import atomic

HOST_SHA = "0aef69b2bc613835a510b42528b849d0ca980987d0c7cf319fb0019e3c6d0b26"
MENU_SHA = "5f1eed6185b31fa6cbeb4a03d44216a2ed8dafe1dad95c04a6da876711077b2e"
MARK = "/* OOTRR Hookshot 3.0.1 adapter v1 */"
FILES = ("ootrr_archipelago.inc", "ootrr_ap_items.inc", "ootrr_ap_digest.h", "ootrr_ap_hookshot.inc")
MENU = "ootrr_ap_hookshot_menu.inc"
METADATA = "ootrr-hookshot-tools.json"


class HookshotError(ValueError):
    def __init__(self, message):
        self.public_message = tr(message)
        super().__init__(self.public_message)


def _read(path):
    try:
        if Path(path).stat().st_size > 1 << 20:
            return {}
        result = json.loads(Path(path).read_bytes())
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def detect(game):
    folder = Path(game)
    if folder.name.casefold() == "hookshot.exe":
        folder = folder.parent.parent if folder.parent.name.casefold() == "bin" else folder.parent
    return (folder / "hookshot.exe").is_file() or (folder / "bin/hookshot.exe").is_file()


def discover(game=None, tools=None):
    folder = Path(game) if game else Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Games/Hookshot"
    if folder.name.casefold() == "hookshot.exe":
        folder = folder.parent.parent if folder.parent.name.casefold() == "bin" else folder.parent
    record = _read(folder / ".hookshot_build.json")
    configured = Path(tools or record.get("tools", ""))
    return dict(host="hookshot", game=str(folder), romfs=str(folder / "romfs"),
                native_tools=str(configured) if configured != Path(".") else "",
                work=record.get("work", ""), setup="")


def _original(tools):
    metadata = _read(Path(tools) / METADATA)
    return Path(metadata.get("source", tools))


def validate_installation(game, tools):
    game, tools = Path(game), _original(tools)
    try:
        supported = ((tools / "version.txt").read_text().strip() == "v3.0.1"
                     and _sha((tools / "host/hos_main.c").read_bytes()) == HOST_SHA
                     and _sha((tools / "gpu/vk/vk_menu.cpp").read_bytes()) == MENU_SHA)
    except OSError:
        supported = False
    if not supported:
        raise HookshotError("Hookshot 3.0.1 tools are required for this adapter.")
    record = _read(game / ".hookshot_build.json")
    required = (tools / "nx2/build.py", tools / "nx2/make_game.py", tools / "python/python.exe",
                tools / "llvm-mingw/bin/x86_64-w64-mingw32-clang.exe")
    work = record.get("work")
    if (not all(path.is_file() for path in required) or not isinstance(work, str) or not work
            or not (Path(work) / "sa/gen/lifted_objects.txt").is_file()
            or not isinstance(record.get("env", {}), dict)
            or any(not isinstance(value, str) for key, value in record.get("env", {}).items()
                   if key in ("HOOKSHOT_NGX_SDK", "WGPU_NATIVE", "EMSDK"))):
        raise HookshotError("Finish the Hookshot game installation before preparing Archipelago.")
    if (not (game / "romfs/Pack/ZsDic.pack.zs").is_file()
            or not (game / "image.bin").is_file() or not (game / ".hookshot_exefs").is_dir()):
        raise HookshotError("Finish the Hookshot game installation before preparing Archipelago.")


def patch_source(raw):
    from .native_setup import BOOTSTRAP
    text = raw.decode("utf-8").replace("\r\n", "\n")
    newline = "\r\n" if b"\r\n" in raw else "\n"
    anchors = [
        ("static void oot_update_player_cheats(Ctx *c, uint64_t actor, uint64_t components) {",
         MARK + '\n#include "ootrr_ap_hookshot.inc"\n#include "ootrr_archipelago.inc"\n\nstatic void oot_update_player_cheats(Ctx *c, uint64_t actor, uint64_t components) {'),
        ("    oot_inventory_refresh(c, now);", "    oot_inventory_refresh(c, now);\n    if (ap_player16(c, actor, components, now)) ap_tick16(c, now);"),
        ("    hos_mods_init(image);", BOOTSTRAP),
    ]
    if MARK in text:
        if text.count(MARK) == 1 and all(text.count(after) == 1 for _, after in anchors):
            return raw
        raise HookshotError("The Hookshot adapter sources are incomplete. Prepare the room again.")
    if "ap_boot16(" in text or any(text.count(before) != 1 for before, _ in anchors):
        raise HookshotError("Hookshot 3.0.1 tools are required for this adapter.")
    for before, after in anchors:
        text = text.replace(before, after, 1)
    return text.replace("\n", newline).encode("utf-8")


def isolated_bridge(raw):
    text = raw.decode("utf-8")
    before = 'DWORD got=GetEnvironmentVariableW(L"LOCALAPPDATA",base,1024);'
    after = ('DWORD got=GetEnvironmentVariableW(L"OOTRR_AP_BASE",base,1024);\n'
             '    int ap_explicit_base=got>0;\n'
             '    if (!got) got=GetEnvironmentVariableW(L"LOCALAPPDATA",base,1024);')
    room = 'swprintf(room,1400,L"%ls\\\\OOTRR-Archipelago\\\\%ls",base,wt);'
    target = ('swprintf(room,1400,ap_explicit_base ? L"%ls\\\\%ls" : '
              'L"%ls\\\\OOTRR-Archipelago\\\\hosts\\\\hookshot\\\\%ls",base,wt);')
    if text.count(before) != 1 or text.count(room) != 1:
        raise HookshotError("The Hookshot adapter sources are incomplete. Prepare the room again.")
    return text.replace(before, after).replace(room, target).encode("utf-8")


def _menu_edits():
    rows = '''    {TAB_GAMEPLAY, "AP Server", nullptr, 0, 0, 0, nullptr, "Server address for the prepared Archipelago room. Enter to edit; controller and paste supported.", nullptr, false, true},
    {TAB_GAMEPLAY, "AP Password", nullptr, 0, 0, 0, nullptr, "Optional room password. Saved passwords are never displayed. Text entry uses Hookshot's native printable-character editor.", nullptr, false, true},
    {TAB_GAMEPLAY, "AP Password action", &hookshot_ap::password_mode, 0, 2, 1, hookshot_ap::mode_text, "Keep, replace or remove the saved password when connecting.", nullptr, false, true},
    {TAB_GAMEPLAY, "AP Automatic connection", &hookshot_ap::auto_connect, 0, 1, 1, tx_onoff, "Connect at startup. Changes are saved with AP Connect.", nullptr, false, true},
    {TAB_GAMEPLAY, "AP Connect", nullptr, 0, 0, 0, nullptr, "Save these connection settings and connect to the prepared room.", nullptr, false, true},
    {TAB_GAMEPLAY, "AP Disconnect", nullptr, 0, 0, 0, nullptr, "Disconnect without changing your saved items or checks.", nullptr, false, true},
'''
    return [
        ("struct TextField {\n    char text[64];", "struct TextField {\n    char text[1025];"),
        ("// (hookshot) the NFC tab: the NFC tags in the player's folder", '#include "ootrr_ap_hookshot_menu.inc"\n\n// (hookshot) the NFC tab: the NFC tags in the player\'s folder'),
        ("    // (Restart and Quit stay the table's last two:", rows + "    // (Restart and Quit stay the table's last two:"),
        ('const FieldRow field_rows[] = {{"Custom output size", &output_field, output_field_apply}};',
         'const FieldRow field_rows[] = {{"Custom output size", &output_field, output_field_apply}, {"AP Server", &hookshot_ap::server_field, hookshot_ap::server_apply}, {"AP Password", &hookshot_ap::password_field, hookshot_ap::password_apply}};'),
        ('        text_cell(c, va, vb, *f->field, selected, editing == f->field, "None");',
         '        if (f->field == &hookshot_ap::password_field) { TextField masked=*f->field; memset(masked.text,\'*\',masked.len); masked.text[masked.len]=0; text_cell(c,va,vb,masked,selected,editing==f->field,"None"); }\n        else text_cell(c, va, vb, *f->field, selected, editing == f->field, "None");'),
        ("    share_finish();   // (Save my pipeline list's worker, done)", "    hookshot_ap::poll(editing != nullptr);\n    share_finish();   // (Save my pipeline list's worker, done)"),
        ("void set_row(Row& r, int v, int dir, bool keep = true) {", "void set_row(Row& r, int v, int dir, bool keep = true) {\n    if(r.value==&hookshot_ap::password_mode || r.value==&hookshot_ap::auto_connect) hookshot_ap::dirty=true;"),
        ("    if ((is_nfc_tap(selr) || is_nfc_remove(selr))", '    if (!strncmp(selr.name,"AP ",3)) hint=hookshot_ap::row_hint(selr);\n    if ((is_nfc_tap(selr) || is_nfc_remove(selr))'),
        ("            else if (press[7] && is_share_row(r))", "            else if (press[7] && hookshot_ap::action_row(r)) hookshot_ap::invoke(r), press[7]=false, changed=true;\n            else if (press[7] && is_share_row(r))"),
        ("            edit_end(false);   // (hookshot: a text field being edited, its text as it was)",
         "            edit_end(false);   // (hookshot: a text field being edited, its text as it was)\n            hookshot_ap::clear_password(); hookshot_ap::password_mode=0; hookshot_ap::dirty=false; memset(edit_kept,0,sizeof edit_kept);"),
    ]


def patch_renderer(raw):
    text = raw.decode("utf-8").replace("\r\n", "\n")
    newline = "\r\n" if b"\r\n" in raw else "\n"
    edits = _menu_edits()
    marker = '#include "ootrr_ap_hookshot_menu.inc"'
    if marker in text:
        if text.count(marker) == 1 and all(text.count(after) == 1 for _, after in edits):
            return raw
        raise HookshotError("The Hookshot adapter sources are incomplete. Prepare the room again.")
    if any(text.count(before) != 1 for before, _ in edits):
        raise HookshotError("Hookshot 3.0.1 tools are required for this adapter.")
    for before, after in edits:
        text = text.replace(before, after, 1)
    return text.replace("\n", newline).encode("utf-8")


def _bundle():
    bundle = resource_root() / "native"
    if not (bundle / MENU).is_file() and not getattr(__import__("sys"), "frozen", False):
        bundle = Path(__file__).resolve().parents[2] / "native"
    return bundle


def patch_i18n(raw):
    translations = {
        "AP Server": "AP Serveur", "AP Password": "AP Mot de passe", "AP Password action": "AP Mot de passe enregistré",
        "AP Automatic connection": "AP Connexion automatique", "AP Connect": "AP Connexion", "AP Disconnect": "AP Déconnexion",
        "Server address for the prepared Archipelago room. Enter to edit; controller and paste supported.": "Adresse du serveur de la salle Archipelago préparée. Entrée pour modifier ; manette et collage pris en charge.",
        "Optional room password. Saved passwords are never displayed. Text entry uses Hookshot's native printable-character editor.": "Mot de passe facultatif. Le mot de passe enregistré reste masqué. La saisie utilise l’éditeur natif de caractères imprimables de Hookshot.",
        "Keep, replace or remove the saved password when connecting.": "Conserver, remplacer ou supprimer le mot de passe enregistré lors de la connexion.",
        "Connect at startup. Changes are saved with AP Connect.": "Connexion au démarrage. Les changements sont enregistrés avec AP Connexion.",
        "Save these connection settings and connect to the prepared room.": "Enregistrer ces paramètres et se connecter à la salle préparée.",
        "Disconnect without changing your saved items or checks.": "Déconnecter sans modifier les objets ni les checks enregistrés.",
    }
    text = raw.decode("utf-8")
    anchor = "    if (!s || !*s || !lang) return s;"
    addition = "\n    // OOTRR Hookshot AP translations v1\n    if (!strncmp(lang_code(),\"fr\",2)) {\n"
    for english, french in translations.items():
        addition += "        if (!strcmp(s," + json.dumps(english) + ")) return " + json.dumps(french, ensure_ascii=False) + ";\n"
    addition += "    }\n"
    if text.count(anchor) != 1:
        raise HookshotError("Hookshot 3.0.1 tools are required for this adapter.")
    return text.replace(anchor, anchor + addition).encode("utf-8")


def install_tools(base, chooser=None, configured=None):
    source = _original(configured or "")
    if not (source / "host/hos_main.c").is_file():
        raise HookshotError("Hookshot 3.0.1 tools are required for this adapter.")
    host_raw, menu_raw = (source / "host/hos_main.c").read_bytes(), (source / "gpu/vk/vk_menu.cpp").read_bytes()
    if _sha(host_raw) != HOST_SHA or _sha(menu_raw) != MENU_SHA:
        raise HookshotError("Hookshot 3.0.1 tools are required for this adapter.")
    bundle = _bundle()
    helpers = {name: (bundle / name).read_bytes() for name in (*FILES, MENU)}
    helpers["ootrr_archipelago.inc"] = isolated_bridge(helpers["ootrr_archipelago.inc"])
    patched_host, patched_menu = patch_source(host_raw), patch_renderer(menu_raw)
    translated = patch_i18n((source / "gpu/vk/vk_menu_i18n.cpp").read_bytes())
    key = _sha(str(source.resolve()).encode("utf-8") + b"\0" + patched_host + patched_menu
               + translated + b"".join(helpers.values()))[:16]
    target = Path(base) / "hookshot-tools" / key
    if (target / METADATA).is_file():
        expected = {target / "host/hos_main.c": patched_host, target / "gpu/vk/vk_menu.cpp": patched_menu,
                    **{target / "host" / name: helpers[name] for name in FILES},
                    target / "gpu/vk" / MENU: helpers[MENU], target / "gpu/vk/vk_menu_i18n.cpp": translated}
        if all(path.is_file() and path.read_bytes() == raw for path, raw in expected.items()):
            return target
        raise HookshotError("The Hookshot adapter sources are incomplete. Prepare the room again.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".hookshot-", dir=target.parent) as stage:
        scratch = Path(stage) / "tools"
        scratch.mkdir()
        for name in ("host", "gpu", "nx2", "native", "third_party", "assets", "scripts", "cpm"):
            if (source / name).is_dir():
                shutil.copytree(source / name, scratch / name)
        shutil.copy2(source / "version.txt", scratch / "version.txt")
        atomic(scratch / "host/hos_main.c", patched_host)
        atomic(scratch / "gpu/vk/vk_menu.cpp", patched_menu)
        atomic(scratch / "gpu/vk/vk_menu_i18n.cpp", translated)
        for name in FILES:
            atomic(scratch / "host" / name, helpers[name])
        atomic(scratch / "gpu/vk" / MENU, helpers[MENU])
        atomic(scratch / METADATA, json.dumps(dict(source=str(source), key=key)).encode())
        scratch.replace(target)
    return target


def mutable_files(tools):
    return []  # Tool revisions are immutable, content-addressed private copies.


def compiled_executable(romfs, tools=None):
    try:
        from .native_setup import BUILD_MARK
        module = _bundle() / "archipelago.dll"
        if not module.is_file() and not getattr(__import__("sys"), "frozen", False):
            module = Path(__file__).resolve().parents[2] / "prebuilt/windows-x64/archipelago.dll"
        expected = hashlib.sha256(module.read_bytes()).digest()
        for executable in (Path(romfs).parent / "bin/hookshot.exe", Path(romfs).parent / "hookshot.exe"):
            renderer = executable.parent / "hookshot_vk.dll"
            if not executable.is_file() or not renderer.is_file():
                continue
            with executable.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                if (data.find(BUILD_MARK) < 0 or data.find(expected) < 0
                        or data.find("OOTRR_AP_BASE".encode("utf-16-le")) < 0):
                    continue
            with renderer.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                if data.find(b"ootrr_ap_menu16") < 0 or data.find(b"AP Connect") < 0:
                    continue
            if tools:
                for name in FILES:
                    packaged = (_bundle()/name).read_bytes()
                    if name == "ootrr_archipelago.inc":
                        packaged = isolated_bridge(packaged)
                    if (Path(tools)/"host"/name).read_bytes()!=packaged:
                        return None
                if (Path(tools)/"gpu/vk"/MENU).read_bytes()!=(_bundle()/MENU).read_bytes():
                    return None
                if any((Path(tools) / "host" / name).stat().st_mtime_ns > executable.stat().st_mtime_ns for name in FILES):
                    continue
                if (Path(tools) / "gpu/vk" / MENU).stat().st_mtime_ns > renderer.stat().st_mtime_ns:
                    continue
            return executable
    except (OSError, ValueError):
        return None
    return None


def build_game(game, tools, log, progress=None, cancel=None):
    game, tools = Path(game), Path(tools)
    validate_installation(game, tools)
    source = _original(tools)
    record = _read(game / ".hookshot_build.json")
    source_work = Path(record.get("work", ""))
    work = tools.parent.parent / "hookshot-work" / tools.name
    work.mkdir(parents=True, exist_ok=True)
    for name in ("objcache", "sa/gen", "image"):
        if not (work / name).exists() and (source_work / name).is_dir():
            shutil.copytree(source_work / name, work / name)
    for name in ("hookshot_pieces.prof", "hot_funcs.txt", "hot_order.txt", "build_times.json", "hookshot.res"):
        if not (work / name).exists() and (source_work / name).is_file():
            shutil.copy2(source_work / name, work / name)
    environment = {name: value for name, value in os.environ.items() if not name.startswith(("HOS_INPUT_", "OOT_", "A64_"))}
    environment.update(RX_CPM=str(tools / "cpm"), HOOKSHOT_MINGW=str(source / "llvm-mingw"),
                       HOOKSHOT_KEEP_BUILD_FILES="1", PYTHONDONTWRITEBYTECODE="1",
                       OOT_WORK=str(work), OOT_EXEFS=str(game / ".hookshot_exefs"),
                       OOT_ROMFS=str(game / "romfs"), RX_RELEASE="1", A64_HOT_CHUNK="1",
                       RX_PGO=str(work / "hookshot_pieces.prof"), HOOKSHOT_OBJ_STORE=str(work / "object-store"),
                       HOOKSHOT_TIMES=str(work / "build_times.json"), LOCALAPPDATA=str(work / "local"),
                       APPDATA=str(work / "roaming"))
    for name, value in record.get("env", {}).items():
        if name in ("HOOKSHOT_NGX_SDK", "WGPU_NATIVE", "EMSDK") and Path(value).is_dir():
            environment[name] = value
    if (source / "wgpu-native").is_dir():
        environment.setdefault("WGPU_NATIVE", str(source / "wgpu-native"))
    kept = work / "sa/gen/lifted_objects.txt"
    if not kept.is_file():
        raise HookshotError("Finish the Hookshot game installation before preparing Archipelago.")
    command = [str(source / "python/python.exe"), "-I", "-u", "-X", "utf8", str(tools / "nx2/build.py"),
               "--standalone", "--jobs", "8", "--kept-lift", str(kept)]
    process = spawn_process(command, cwd=tools, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    for line in process.stdout:
        log.write(line)
        log.flush()
        if progress and line.startswith(("@@stage ", "@@progress ")):
            progress(93, tr("Building Hookshot. This may take several minutes."))
    if process.wait() != 0:
        raise HookshotError("Hookshot could not be rebuilt. Your previous installation has been restored.")
    # Publish just the two native binaries. Game data, options, build stamps and
    # the original builder's caches stay untouched by this host-only rebuild.
    output = game / "bin"
    built = work / "sa/build"
    if not all((built / name).is_file() for name in ("hookshot.exe", "hookshot_vk.dll")):
        raise HookshotError("Hookshot could not be rebuilt. Your previous installation has been restored.")
    if compiled_executable(built / "romfs") is None:
        raise HookshotError("Hookshot could not be rebuilt. Your previous installation has been restored.")
    output.mkdir(parents=True, exist_ok=True)
    for name in ("hookshot.exe", "hookshot_vk.dll"):
        temporary = output / (name + ".archipelago-new")
        shutil.copy2(built / name, temporary)
        temporary.replace(output / name)
