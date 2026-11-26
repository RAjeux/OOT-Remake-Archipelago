"""Run the project's portable checks, optionally including a real Archipelago server."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
args=argparse.ArgumentParser(description=__doc__)
args.add_argument("--network",action="store_true",help="Run local tests using the server set by AP_SERVER or AP_SOURCE.")
args.add_argument("--c",action="store_true",help="Test item delivery using a C gameplay model.")
options=args.parse_args()

def run(*args):
    print(">",*args,flush=True)
    subprocess.run([sys.executable,*map(str,args)],cwd=ROOT,check=True)

run("tools/build.py")
run("tests/test_release.py")
run("tests/test_builder.py")
run("tests/test_app_runtime.py")
run("tests/test_apworld_installation.py")
run("tests/test_app_update_entry.py")
run("tests/test_update_service.py")
run("tests/test_engine_paths.py")
run("tests/test_app_packaging.py")
run("tests/test_app_window.py")
run("tests/test_settings_window.py")
run("tests/test_settings_help.py")
run("tests/test_shop_hours.py")
run("tests/test_event_graph_depth.py")
run("tests/test_network_catalog.py")
run("tests/test_network_placement.py")
run("tests/test_network_containers.py")
run("tests/test_network_rewards.py")
run("tests/test_network_flows.py")
run("tests/test_network_offer_texts.py")
run("tests/test_network_merchant_preflight.py")
run("tests/test_key_presentations.py")
run("tests/test_presentation_models.py")
run("tests/test_chest_presentation_models.py")
run("tests/test_starter_equipment.py")
run("tests/test_cursor_batch.py")
run("tests/test_event_analysis_cache.py")
# Real AP generation is a separate opt-in harness: test_network_generation.py
# requires an isolated generator and explicit --ap-root/--dependencies paths.
run("tests/test_network_build.py")
run("tests/test_generation_matrix.py")
run("tests/test_native_gameplay_audit.py")
run("tests/test_install_service.py")
run("tests/test_hookshot_setup.py")
run("tools/check_catalog.py")
run("tests/test_native_bundle_quantities.py")
run("tests/test_shop_catalog.py")
run("tests/test_shop_pool.py")
run("tests/test_localization_catalog.py")
run("tests/test_i18n.py")
run("tests/test_localization_pipeline.py")
run("tests/test_settings_parity.py")
run("tests/test_ap_options.py")
run("tests/test_skull_catalog.py")
run("tests/test_skull_events.py")
run("tests/test_transient_data.py")
run("tests/test_restoration.py")
run("tests/test_restoration_capacity.py")
run("tests/test_trade_state.py")
run("tests/test_ap_trade.py")
run("tests/test_trade_events.py")
run("tests/test_trade_receipts.py")
run("tests/test_trade_protocol.py")
run("tests/test_master_sword.py")
run("tests/test_story_fixes.py")
run("tests/test_quest_fixes.py")
run("tests/test_fortress_fixes.py")
run("tests/test_connection_control.py")
run("tests/test_connection_window.py")
for check in ("test_cursor","test_title_install","test_visual","test_hud","test_evfl","test_native_setup","test_menu_setup","test_settings","test_settings_engine","test_apworld","test_full_chests","test_receipt_events","test_presented_receipts","test_receipt_registration","test_shop_records","test_shop_flags","test_shop_events"):
    run(f"tests/{check}.py")
if options.c:
    run("tests/test_restore_host.py")
    run("tests/test_menu_bridge.py")
    run("tests/test_menu_editing.py")
    run("tests/test_language_host.py")
    run("tests/test_link.py")
    run("tests/test_deathlink_host.py")
if options.network:
    if not (os.environ.get("AP_SERVER") or os.environ.get("AP_SOURCE")):
        sys.exit("Set AP_SERVER or AP_SOURCE before running network tests.")
    if sys.platform.startswith("linux") and not (ROOT/"build/archipelago.so").is_file():
        run("tools/build.py","--linux-test-lib")
    run("tests/test_installer.py")
    run("tests/test_install_service_network.py")
    for name in ("neutre","ancienne"):
        room=f"tests/fixtures/{name}"
        run("tests/test_network.py",room)
        run("tests/test_native.py",room)
    run("tests/test_native.py", "tests/fixtures/complet-v2", "--language", "fr")
    for name in ("complet", "complet-v2"):
        run("tests/test_offline_deathlink.py", "tests/fixtures/" + name)
    run("tests/test_local_items.py", "--room", "tests/fixtures/complet-v2")
    run("tests/test_native_rollback.py")
    run("tests/test_connection_menu.py")
    run("tests/test_connection_companion.py")
