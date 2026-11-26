"""Windowed entry point for the standalone Windows application."""
import argparse
import hashlib
from importlib import resources
import json
import logging
from pathlib import Path
import sys
import tempfile
from zipfile import ZipFile


def self_test(destination):
    """Exercise the frozen runtime without a room, game dump or connection."""
    from ootrr_triforce import app_runtime
    from ootrr_triforce.catalog import DEFAULT_SETTINGS
    from ootrr_triforce.engine import run_engine
    from ootrr_triforce.mod_codec import Codec
    from oot_rando.formats.byml_codec import build_sarc
    import ctypes
    import tkinter as tk
    from tkinter import ttk
    from ootrr_triforce.ui_theme import apply_theme, COLORS
    import zstandard

    at = app_runtime.resource_root()
    manifest = json.loads((at / "app-manifest.json").read_bytes())
    assert manifest["platform"] == "windows-x64"
    from ootrr_triforce import update_service
    assert update_service.current_version() == manifest["version"]
    assert update_service.compare_versions(manifest["version"], manifest["version"]) == 0
    if getattr(sys, "frozen", False):
        assert update_service._file_version(Path(sys.executable)) == {
            "ProductName": "OOT Remake Archipelago", "ProductVersion": manifest["version"]}
    for name, digest in manifest["payload"].items():
        assert hashlib.sha256((at / name).read_bytes()).hexdigest() == digest, name
    for name in ("ootrr_ap_hookshot.inc", "ootrr_ap_hookshot_menu.inc"):
        assert "native/" + name in manifest["payload"] and (at / "native" / name).is_file(), name
    library = ctypes.CDLL(str(at / "native/archipelago.dll"))
    for symbol in ("AP_Start", "AP_ConnectionInfo", "AP_ReceiptReplay"):
        assert getattr(library, symbol)
    settings = json.loads(run_engine("settings", {"settings": DEFAULT_SETTINGS}))
    assert settings["settings_string"].startswith("OOTRR1-")
    from ootrr_triforce.network_catalog import SCHEMA, SOURCES
    native_catalog = json.loads(run_engine("catalog", {}))
    assert native_catalog == {"schema": SCHEMA, "sources": SOURCES}
    frame = zstandard.ZstdCompressor().compress(build_sarc({"probe": b"synthetic"}))
    codec = Codec(frame)
    value = b"Standalone codec round trip."
    assert codec.decode(codec.encode(value, frame)) == value
    for language in ("i18n_fr.json", "settings_fr.json"):
        assert json.loads(resources.files("ootrr_triforce").joinpath(language).read_bytes())
    window = tk.Tk()
    window.withdraw()
    apply_theme(window)
    assert window.cget("background") == COLORS["bg"]
    assert ttk.Style(window).lookup("App.Primary.TButton", "background") == COLORS["gold"]
    ttk.Label(window, text="Runtime verification").pack()
    window.update_idletasks()
    from ootrr_triforce.settings import OPTION_SPECS, validate_options
    from ootrr_triforce.settings_window import SettingsWindow
    for language in ("en", "fr"):
        editor = SettingsWindow(window, language=language)
        assert len(editor.controls) == len(OPTION_SPECS)
        editor.search_var.set("skull")
        window.update_idletasks()
        assert "shuffle_skulltulas" in editor.visible_names
        assert editor.selected_values() == validate_options({})
        editor.close()
    window.destroy()
    temporary_root = Path(tempfile.gettempdir()).resolve()
    with tempfile.TemporaryDirectory(prefix="ootrr-app-check-", dir=temporary_root) as temporary:
        work = Path(temporary).resolve()
        assert work.is_relative_to(temporary_root)
        worlds = work / "custom_worlds"
        worlds.mkdir()
        previous = b"Previous synthetic APWorld"
        (worlds / "ootrr_remake.apworld").write_bytes(previous)
        installed = app_runtime.install_apworld(worlds, base=work / "local")
        assert hashlib.sha256(installed.read_bytes()).hexdigest() == manifest["payload"]["ootrr_remake.apworld"]
        backup, = (work / "local/backups/apworld").glob("*.apworld")
        assert backup.read_bytes() == previous
        assert app_runtime.discover_apworld_targets(base=work / "local")[0] == worlds.resolve()
        node = work / "local/tools" / ("node-v" + manifest["node_version"]) / "node.exe"
        assert hashlib.sha256(node.read_bytes()).hexdigest() == manifest["payload"]["runtime/node/node.exe"]
        assert node.with_name("LICENSE").read_bytes() == (at / "runtime/node/LICENSE").read_bytes()
        with ZipFile(installed) as world:
            assert {name.split("/")[0] for name in world.namelist()} == {"ootrr_remake"}
            assert json.loads(world.read("ootrr_remake/network_sources.json")) == native_catalog
            for name in ("engine.cjs", "engine.wasm"):
                (work / name).write_bytes(world.read("ootrr_remake/" + name))
        run = app_runtime.run_process([str(node), "--no-warnings", str(work / "engine.cjs"),
                                      str(work / "engine.wasm"), "settings"],
                                     input=json.dumps({"settings": DEFAULT_SETTINGS}).encode(),
                                     capture_output=True, check=True, timeout=30)
        assert json.loads(run.stdout)["settings_string"].startswith("OOTRR1-")
    result = dict(result="PASS", frozen=bool(getattr(sys, "frozen", False)),
                  version=manifest["version"], node=manifest["node_version"],
                  wasm_settings=True, zstd_round_trip=True, native_exports=True,
                  tkinter=True, translations=True, payload_hashes=True,
                  desktop_theme=True,
                  updater=True, windows_version_metadata=bool(getattr(sys, "frozen", False)),
                  hookshot_resources=True,
                  apworld_install=True, previous_apworld_preserved=True,
                  persistent_node_engine=True,
                  network_catalogue=True, native_sources=len(SOURCES),
                  yaml_editor_languages=["en", "fr"], yaml_editor_controls=len(OPTION_SPECS),
                  game_started=False, server_connected=False)
    Path(destination).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


def main():
    parser = argparse.ArgumentParser(add_help=False)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--self-test", type=Path, help=argparse.SUPPRESS)
    mode.add_argument("--apply-update", type=Path, help=argparse.SUPPRESS)
    mode.add_argument("--complete-update", type=Path, help=argparse.SUPPRESS)
    options = parser.parse_args()
    try:
        # A detached helper must not open Tk or initialize the old app's Node
        # and log files while it waits for the original executable to close.
        if options.apply_update:
            from ootrr_triforce.update_service import helper_main
            return helper_main(options.apply_update)
        from ootrr_triforce import app_runtime
        app_runtime.initialize()
        if options.self_test:
            return self_test(options.self_test)
        startup_notice = None
        if options.complete_update:
            try:
                from ootrr_triforce.update_service import complete_update
                startup_notice = complete_update(options.complete_update)
            except Exception:
                logging.exception("Update completion could not be recorded")
                startup_notice = dict(world_updated=False, error_code="update_completion_failed")
        from ootrr_triforce.app_window import main as open_window
        open_window(startup_notice=startup_notice)
        return 0
    except Exception as exc:
        if options.apply_update:
            # A helper can fail after the parent window has closed. Keep its
            # traceback in the same persistent log exposed by Help, without
            # initializing Tk, Node or the old extraction directory.
            try:
                import traceback
                from ootrr_triforce.app_runtime import log_path
                target = log_path()
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("a", encoding="utf-8") as output:
                    output.write("\nLauncher update helper failed:\n")
                    traceback.print_exception(type(exc), exc, exc.__traceback__, file=output)
            except Exception:
                pass
            return 1
        logging.exception("Application startup failed")
        if options.self_test:
            options.self_test.write_text(json.dumps(dict(result="FAIL", error_type=type(exc).__name__,
                                                         error=str(exc)), indent=2) + "\n", encoding="utf-8")
        elif sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,
                "Unable to open OOT Remake Archipelago. Download the application again from the project's GitHub releases.",
                "OOT Remake Archipelago", 16)
        return 1


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
