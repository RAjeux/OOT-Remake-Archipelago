"""Internal Windows Longshot source prototype; deliberately not a launcher host.

Stage a clean, exact audited checkout into a private content-addressed directory.
This module does not fetch game files, install a game, import a profile, or imply
that a source/fixture check is a completed gameplay compatibility certification.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

SOURCE_REV = "e8fce9956e2a42972deb9b1274f705ecbb414c84"
SOURCE_URL = "https://git.magicbean.dev/MagicBeanDev/Longshot"
MARK = "/* OOTRR Longshot scheduler adapter v1 */"
METADATA = "ootrr-longshot-prototype.json"
SOURCE_HASHES = {
    "game/oot_tools.c": "d4a80f09086f92aad376974a622a2668d2839c36593889a1ce730b9c48dbbfea",
    "host/hos_main.c": "c9f1422cfb111d959d69bfc39c3ff6ad05e029900a1b1279f213ec46ff639676",
    "host/nn_applet.c": "c1a5543332edd9f8d59968e257a25a8f74f5e268a252a4a7d4aff86f692f9ddd",
    "gpu/vk/vk_menu.cpp": "e41ce33f0a83e25128a00b14551a752ac06be111e08105e7c78a7c41063f1ea4",
    "gpu/vk/vk_menu_i18n.cpp": "affe63074f0763d089cdc9218d7f780d267fa33a4c820ce3bb2d981226a4b46a",
    "host/game_call.c": "394c9b9368fa3980f9081be2e034138d0c98b72a06d9185daa87e78d255da6a9",
    "host/game_call.h": "a320ff0733a4a0e4f7cee65532590313d30e1a9a52a84fab068d8adcdea1cc07",
    "game/flags.c": "da6b43abe61d34c1192e979106268dcf39cfc773846bee36de8e7b2e1b6a409c",
    "game/flags.h": "7be2997bf9593b9acebba6722ef252f134a72cd0709b3a4543dd2adcf0ca0778",
}
NATIVE_FILES = ("ootrr_ap_longshot.inc", "ootrr_ap_longshot_event.inc", "ootrr_ap_items.inc",
                "ootrr_ap_digest.h")


class LongshotError(ValueError):
    """Unknown or incomplete native source; fail before producing output."""


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _patch(raw, edits):
    text = raw.decode("utf-8").replace("\r\n", "\n")
    newline = "\r\n" if b"\r\n" in raw else "\n"
    if MARK in text:
        if text.count(MARK) == 1 and all(text.count(after) == 1 for _, after in edits):
            return raw
        raise LongshotError("The staged Longshot prototype is incomplete.")
    if any(text.count(before) != 1 for before, _ in edits):
        raise LongshotError("The audited Longshot source is required; an anchor changed.")
    for before, after in edits:
        text = text.replace(before, after, 1)
    return text.replace("\n", newline).encode("utf-8")


def patch_game(raw):
    before = "static void oot_update_player_cheats(Ctx *c, uint64_t actor, uint64_t components) {"
    after = (MARK + '\n#include "ootrr_ap_longshot.inc"\n#include "ootrr_archipelago.inc"\n'
             'int ootrr_ap_longshot_boot(void) {\n'
             '    if (ap_boot16()) return 1;\n'
             '    ap_boot_error16(); return 0;\n}\n\n' + before)
    return _patch(raw, [('#include "flags.h"', '#include "flags.h"\n#include "oot_heart_containers.h"'),
                       (before, after),
                       ("    oot_inventory_refresh(c, now);",
                        "    oot_inventory_refresh(c, now);\n"
                        "    if (ap_player16(c, actor, components, now)) ap_tick16(c, now);")])


def patch_host(raw):
    before = "    hos_mods_init(image);"
    after = (before + "\n" + MARK + "\n#ifdef _WIN32\n"
             "    extern int ootrr_ap_longshot_boot(void);\n"
             "    if (!ootrr_ap_longshot_boot()) return 3;\n#endif")
    return _patch(raw, [(before, after)])


def patch_language(raw):
    # nn::oe's own cached language remains the single source of truth.
    wrapper = ("\n" + MARK + "\nconst char *hos_desired_language(void) { return desired_language(); }\n")
    text = raw.decode("utf-8").replace("\r\n", "\n")
    if MARK in text:
        if text.count(wrapper) == 1:
            return raw
        raise LongshotError("The staged Longshot language wrapper is incomplete.")
    if b"static const char *desired_language(void) {" not in raw:
        raise LongshotError("Longshot's native language function changed.")
    newline = "\r\n" if b"\r\n" in raw else "\n"
    return raw + wrapper.replace("\n", newline).encode("utf-8")


def isolated_bridge(raw):
    from .hookshot_setup import isolated_bridge as hookshot_bridge
    text = hookshot_bridge(raw).decode("utf-8").replace("hosts\\\\hookshot", "hosts\\\\longshot")
    start = "static int ap_request_item16(Ctx *c,uint64_t actor,const char *name) {"
    end = "\nstatic void ap_invalidate_delivery16(void) {"
    if text.count(start) != 1 or text.count(end) != 1:
        raise LongshotError("The shared native request contract changed.")
    first, last = text.index(start), text.index(end)
    text = text[:first] + '#include "ootrr_ap_longshot_event.inc"\n' + text[last:]
    before = "    ap_event_mode16=event_delivery();"
    guard = before + '\n    if (!ap_event_mode16) { hos_log("Longshot AP requires native receipt events; prepare this room again."); return 0; }'
    # Keep the shared host's complete readiness gate. The passive Bool hook is
    # installed only by Triforce; its wrapper's ordinary player snapshots also
    # remain valid in this isolated prototype. Recognize only reviewed shapes.
    tick_contracts = (
        "    if (!ap_cursor16 || now<next) return;",
        "    if (!ap_cursor16 || now<next || ap_lifecycle_blocked16()) return;",
    )
    matches = [line for line in tick_contracts if text.count(line) == 1]
    if len(matches) != 1 or any(text.count(line) > 1 for line in tick_contracts):
        raise LongshotError("The shared native delivery contract changed.")
    tick = matches[0]
    user = "    hos_user_dir=ap_profile16;"
    profile_guard = (
        "    extern const char *hos_save_dir_chosen(void);\n"
        "    const char *ap_chosen_saves=hos_save_dir_chosen();\n"
        "    char ap_expected_saves[4096];\n"
        '    snprintf(ap_expected_saves,sizeof ap_expected_saves,"%s\\\\saves",ap_profile16);\n'
        "    if (ap_chosen_saves && _stricmp(ap_chosen_saves,ap_expected_saves)) {\n"
        '        hos_log("Longshot AP: another profile owns the save folder. Use the isolated AP launch environment.");\n'
        "        return 0;\n    }\n" + user)
    if text.count(before) != 1 or text.count(tick) != 1 or text.count(user) != 1:
        raise LongshotError("The shared native delivery contract changed.")
    return text.replace(user, profile_guard).replace(before, guard).replace(
        tick, tick.replace("if (", "if (!ap_event_mode16 || ", 1)).encode("utf-8")


def launch_environment(profiles, token, mods, *, environment=None):
    """An internal private run owns its Longshot settings and saves from boot.

    This only constructs an environment; it neither launches nor installs.
    Native bootstrap separately rejects a save root outside this AP profile.
    """
    if not isinstance(token, str) or len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
        raise LongshotError("Invalid Archipelago room token.")
    profiles, mods = Path(profiles).resolve(), Path(mods).resolve()
    user = profiles / token / "user"
    env = dict(os.environ if environment is None else environment)
    env.update(OOTRR_AP_BASE=str(profiles), HOS_MODS=str(mods), LONGSHOT_PROFILE=str(user))
    return env


def patch_renderer(raw):
    include = '// (#1633) This file\'s own rows: the core module\'s (MENU_MODULE(core) below).'
    rows = 'const FieldRow field_rows[] = {{"Custom output size", &output_field, output_field_apply}};'
    draw = '        text_cell(c, va, vb, *f->field, selected, editing == f->field, "None");'
    close = '            edit_end(false);   // (longshot: a text field being edited, its text as it was)'
    return _patch(raw, [
        ("struct TextField {\n    char text[64];", "struct TextField {\n    char text[1025];"),
        (include, MARK + '\n#include "ootrr_ap_longshot_menu.inc"\n\n' + include),
        (rows, 'const FieldRow field_rows[] = {{"Custom output size", &output_field, output_field_apply}, '
               '{"AP Server", &longshot_ap::server_field, longshot_ap::server_apply}, '
               '{"AP Password", &longshot_ap::password_field, longshot_ap::password_apply}};'),
        (draw, "        if (f->field == &longshot_ap::password_field) { TextField masked=*f->field; "
               "memset(masked.text,'*',masked.len); masked.text[masked.len]=0; "
               'text_cell(c,va,vb,masked,selected,editing==f->field,"None"); }\n        else ' + draw.lstrip()),
        ("    share_finish();   // (Save my pipeline list's worker, done)",
         "    longshot_ap::poll(editing != nullptr);\n    share_finish();   // (Save my pipeline list's worker, done)"),
        (close, close + "\n            longshot_ap::clear_password(); longshot_ap::password_mode=0; "
                       "longshot_ap::dirty=false; memset(edit_kept,0,sizeof edit_kept);"),
    ])


def patch_i18n(raw):
    translations = {
        "AP Server": "AP Serveur", "AP Password": "AP Mot de passe",
        "AP Password action": "AP Mot de passe enregistré",
        "AP Automatic connection": "AP Connexion automatique", "AP Connect": "AP Connexion",
        "AP Disconnect": "AP Déconnexion",
        "Address of the prepared Archipelago room. Enter edits; controller and paste supported.":
            "Adresse de la salle Archipelago préparée. Entrée pour modifier ; manette et collage pris en charge.",
        "Optional room password. Saved passwords are never shown. Use the application for non-ASCII passwords.":
            "Mot de passe facultatif. Le mot de passe enregistré reste masqué. Pour les accents, utilise l'application.",
        "Keep, replace or remove the saved password when connecting.":
            "Conserver, remplacer ou supprimer le mot de passe enregistré lors de la connexion.",
        "Connect at startup. Saved when you choose AP Connect.":
            "Connexion au démarrage. Enregistré avec AP Connexion.",
        "Save these settings and connect to the prepared room.":
            "Enregistrer ces paramètres et se connecter à la salle préparée.",
        "Disconnect from this room.": "Se déconnecter de cette salle.",
    }
    before = "    if (!s || !*s || !lang) return s;"
    after = before + "\n" + MARK + '\n    if (!strncmp(lang_code(),"fr",2)) {\n'
    for english, french in translations.items():
        after += "        if (!strcmp(s," + json.dumps(english) + ")) return " + json.dumps(french, ensure_ascii=False) + ";\n"
    after += "    }"
    return _patch(raw, [(before, after)])


PATCHES = {"game/oot_tools.c": patch_game, "host/hos_main.c": patch_host,
           "host/nn_applet.c": patch_language, "gpu/vk/vk_menu.cpp": patch_renderer,
           "gpu/vk/vk_menu_i18n.cpp": patch_i18n}


def validate_source(source):
    source = Path(source).resolve()
    for name, digest in SOURCE_HASHES.items():
        path = source / name
        if not path.is_file() or _sha(path.read_bytes().replace(b"\r\n", b"\n")) != digest:
            raise LongshotError("The clean audited Longshot checkout is required: " + name)
    def git(*args):
        return subprocess.run(["git", "-C", str(source), *args], capture_output=True, text=True, timeout=30)
    revision, clean = git("rev-parse", "HEAD"), git("diff", "--quiet", "HEAD", "--")
    if revision.returncode or revision.stdout.strip() != SOURCE_REV or clean.returncode:
        raise LongshotError("Longshot prototype requires the exact clean audited revision.")
    return source


def stage_source(source, cache, *, native=None):
    """Return a private patched checkout. The input tree is always read-only."""
    source = validate_source(source)
    cache = Path(cache).resolve()
    if cache == source or cache in source.parents or source in cache.parents:
        raise LongshotError("The prototype cache must be separate from Longshot's source.")
    native = Path(native) if native else Path(__file__).resolve().parents[2] / "native"
    output = {name: fn((source / name).read_bytes()) for name, fn in PATCHES.items()}
    output["game/ootrr_archipelago.inc"] = isolated_bridge((native / "ootrr_archipelago.inc").read_bytes())
    output.update({"game/" + name: (native / name).read_bytes() for name in NATIVE_FILES})
    output["gpu/vk/ootrr_ap_longshot_menu.inc"] = (native / "ootrr_ap_longshot_menu.inc").read_bytes()
    hashes = {name: _sha(value) for name, value in sorted(output.items())}
    key = _sha(json.dumps(hashes, sort_keys=True).encode())[:24]
    target = cache / ("source-" + key)
    metadata = {"source": str(source), "revision": SOURCE_REV, "experimental": True, "files": hashes}
    if target.is_dir():
        try:
            valid = json.loads((target / METADATA).read_bytes()) == metadata and all(
                _sha((target / name).read_bytes()) == digest for name, digest in hashes.items())
        except (OSError, ValueError):
            valid = False
        if not valid:
            raise LongshotError("The private prototype cache changed; use a fresh cache folder.")
        return target
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="longshot-stage-", dir=cache) as temporary:
        staged = Path(temporary) / "source"
        shutil.copytree(source, staged, ignore=shutil.ignore_patterns(".git", "target", "tools", "__pycache__"))
        for name, value in output.items():
            path = staged / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
        (staged / METADATA).write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        staged.rename(target)
    return target
