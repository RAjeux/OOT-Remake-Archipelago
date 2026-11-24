"""Actual-widget coverage for the app's normal setup and launch workflow."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.app_window import AppWindow, TEXT, yaml_content
from ootrr_triforce.i18n import tr


class Cancelled(InterruptedError):
    cancelled = True
    public_message = "Setup cancelled."


class UnsupportedGame(ValueError):
    public_message = "Choose a compatible game installation."


class FakeService:
    def __init__(self, base):
        self.base = base
        self.discovery = dict(game=str(base / "Triforce"), romfs=str(base / "Triforce/romfs"),
                              tools=str(base / "tools"), mods=str(base / "Triforce/mods"),
                              server="127.0.0.1:38281", language="en",
                              profile="", ready=False, manifest="")
        self.calls = []
        self.discover_gate = self.inspect_gate = self.install_gate = None
        self.discover_started = threading.Event()
        self.inspect_started = threading.Event()
        self.install_started = threading.Event()
        self.install_error = None
        self.preflight_gate = None
        self.preflight_started = threading.Event()
        self.preflight_calls = []

    def discover(self, base=None, host=None):
        self.discover_started.set()
        if self.discover_gate:
            self.discover_gate.wait(4)
        result = dict(self.discovery)
        if host == "hookshot":
            result.update(game=str(self.base / "Hookshot"), romfs=str(self.base / "Hookshot/romfs"),
                          tools=str(self.base / "Hookshot tools"), mods=str(self.base / "Hookshot/mods"),
                          host="hookshot", base=str(self.base / "hosts/hookshot"), ready=False, profile="")
        return result

    def inspect_installation(self, request):
        self.preflight_calls.append((dict(request), threading.get_ident()))
        self.preflight_started.set()
        if self.preflight_gate:
            self.preflight_gate.wait(4)
        if "Unsupported" in request["game"]:
            raise UnsupportedGame()
        return dict(valid=True, host=request["host"])

    def inspect_manifest(self, path):
        self.inspect_started.set()
        if self.inspect_gate:
            self.inspect_gate.wait(4)
        if "invalid" in path:
            raise ValueError("private details must not appear in the window")
        return dict(room=Path(path).stem, slot="Link", player=2, token="a" * 64, checks=224)

    def install(self, request, progress, cancel):
        self.calls.append(("install", dict(request), threading.get_ident()))
        self.install_started.set()
        progress(20, "Preparing test room")
        while self.install_gate and not self.install_gate.wait(.02):
            if cancel.is_set():
                raise Cancelled()
        if cancel.is_set():
            raise Cancelled()
        if self.install_error:
            raise self.install_error
        return dict(ready=True, build_required=False, game=request["game"],
                    profile=str(self.base / "profile"), room="Test Room", slot="Link", token="a" * 64)

    def launch(self, result):
        self.calls.append(("launch", dict(result), threading.get_ident()))


class FakeDialogs:
    def __init__(self):
        self.open = self.directory = self.save = ""
        self.calls = []

    def askopenfilename(self, **kwargs):
        self.calls.append(("open", kwargs))
        return self.open

    def askdirectory(self, **kwargs):
        self.calls.append(("directory", kwargs))
        return self.directory

    def asksaveasfilename(self, **kwargs):
        self.calls.append(("save", kwargs))
        return self.save


class AppWindowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.service = FakeService(self.base)
        self.dialogs = FakeDialogs()
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except tk.TclError as error:
            self.temp.cleanup()
            self.skipTest(f"Tk display unavailable: {error}")
        self.window = None

    def tearDown(self):
        for gate in (self.service.discover_gate, self.service.inspect_gate, self.service.install_gate, self.service.preflight_gate):
            if gate:
                gate.set()
        if self.window and not self.window.closed:
            if self.window.busy:
                self.window.cancel_event.set()
                self.pump(lambda: not self.window.busy)
            self.window.close()
        elif not self.window:
            self.root.destroy()
        self.temp.cleanup()

    def pump(self, condition, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.window and self.window.closed:
                if condition():
                    return
                break
            self.root.update()
            if condition():
                return
            time.sleep(.005)
        self.fail("The application worker did not finish in time")

    def open(self, wait=True, **kwargs):
        self.window = AppWindow(self.root, service=self.service, base=self.base, dialogs=self.dialogs, **kwargs)
        if wait:
            self.pump(lambda: self.window.status_key != "finding")
        return self.window

    def prepare_form(self, window):
        window.show_page("setup")
        window.fields["manifest"].set(str(self.base / "player.apootrr"))
        self.pump(lambda: window.manifest_info is not None)

    def test_home_has_one_play_path_and_setup_hides_internal_controls(self):
        window = self.open()
        self.assertEqual(str(window.play_button.cget("state")), "disabled")
        self.assertEqual(window.home_status.cget("text"), tr(TEXT["not_prepared"]))
        self.assertEqual(window.page, "home")
        self.assertFalse(window.folder_details.winfo_manager())
        self.assertEqual(set(window.fields), {"manifest", "game", "romfs", "tools", "server", "password"})
        self.assertFalse(any(key in window.fields for key in ("baseline", "builder", "node", "protocol", "host")))
        window.setup_button.invoke()
        self.assertEqual(window.page, "setup")

    def test_existing_room_resource_update_offers_same_player_setup_before_play(self):
        self.service.discovery.update(ready=False, profile=str(self.base/'room'), reprepare_required=True)
        window = self.open()
        self.assertEqual(window.setup_button.cget('text'), tr(TEXT['update_room']))
        self.assertEqual(str(window.play_button.cget('state')), 'disabled')
        self.assertEqual(window.home_room.cget('text'), tr(TEXT['resource_update']))
        window.setup_button.invoke()
        self.assertEqual(window.page, 'setup')

    def test_discovery_preserves_text_entered_while_it_is_running(self):
        self.service.discover_gate = threading.Event()
        window = self.open(wait=False)
        self.pump(self.service.discover_started.is_set)
        window.fields["game"].set(str(self.base / "My Triforce"))
        window.fields["server"].set("archipelago.gg:45678")
        ticks = []
        self.root.after(20, lambda: ticks.append(True))
        self.pump(lambda: bool(ticks), timeout=.5)
        self.service.discover_gate.set()
        self.pump(lambda: window.status_key != "finding")
        self.assertEqual(window.fields["game"].get(), str(self.base / "My Triforce"))
        self.assertEqual(window.fields["romfs"].get(), str(self.base / "My Triforce/romfs"))
        self.assertEqual(window.target_mods, str(self.base / "My Triforce/mods"))
        self.assertEqual(window.fields["tools"].get(), str(self.base / "tools"))
        self.assertEqual(window.fields["server"].get(), "archipelago.gg:45678")

    def test_discovery_preserves_saved_auto_connect_and_explicit_user_changes(self):
        self.service.discovery["auto_connect"] = False
        window = self.open()
        self.assertFalse(window.automatic.get())
        self.prepare_form(window)
        window.install_button.invoke()
        self.pump(lambda: not window.busy)
        self.assertFalse(self.service.calls[-1][1]["auto_connect"])

    def test_delayed_discovery_does_not_reenable_auto_connect_after_user_disables_it(self):
        self.service.discover_gate = threading.Event()
        window = self.open(wait=False)
        self.pump(self.service.discover_started.is_set)
        window.automatic.set(False)
        self.service.discover_gate.set()
        self.pump(lambda: window.status_key != "finding")
        self.assertFalse(window.automatic.get())

    def test_selecting_another_game_retargets_setup_and_preserves_shared_tools(self):
        game_a, game_b = self.base / "Game A", self.base / "Game B"
        shared_tools = self.base / "Shared tools"
        old_mods = self.base / "Existing mods A"
        self.service.discovery.update(game=str(game_a), romfs=str(game_a / "romfs"),
                                      tools=str(shared_tools), mods=str(old_mods))
        for folder in (game_a / "romfs", game_b / "romfs", old_mods, game_b / "mods"):
            folder.mkdir(parents=True)
            (folder / "untouched.bin").write_bytes(str(folder).encode())
        before = {path.relative_to(self.base): path.read_bytes() for path in self.base.rglob("*") if path.is_file()}
        window = self.open()
        self.assertEqual(window.target_mods, str(old_mods))
        window.fields["romfs"].set(str(game_a / "custom romfs"))
        self.dialogs.directory = str(game_b)
        window.browse_folder("game", "choose_game")
        self.prepare_form(window)
        window.install_button.invoke()
        self.pump(lambda: not window.busy)
        request = self.service.calls[-1][1]
        self.assertEqual(request["game"], str(game_b))
        self.assertEqual(request["romfs"], str(game_b / "romfs"))
        self.assertEqual(request["mods"], str(game_b / "mods"))
        self.assertEqual(request["tools"], str(shared_tools))
        after = {path.relative_to(self.base): path.read_bytes() for path in self.base.rglob("*") if path.is_file()}
        self.assertEqual(after, before)

    def test_host_switch_uses_only_the_selected_host_paths_and_request(self):
        window = self.open()
        window.host_choice.current(1)
        window._choose_host()
        self.pump(lambda: window.fields["game"].get() == str(self.base / "Hookshot") and window.installation_info is not None)
        self.assertEqual(window.host, "hookshot")
        self.assertEqual(window.target_mods, str(self.base / "Hookshot/mods"))
        self.assertIn("experimental", window.host_note.cget("text").lower())
        self.prepare_form(window)
        window.install_button.invoke()
        self.pump(lambda: not window.busy)
        request = self.service.calls[-1][1]
        self.assertEqual(request["host"], "hookshot")
        self.assertEqual(request["romfs"], str(self.base / "Hookshot/romfs"))
        self.assertEqual(request["tools"], str(self.base / "Hookshot tools"))

    def test_initial_discovery_cannot_replace_a_host_selected_while_it_is_running(self):
        self.service.discover_gate = threading.Event()
        window = self.open(wait=False)
        self.pump(self.service.discover_started.is_set)
        window.host_choice.current(1)
        window._choose_host()
        self.service.discover_gate.set()
        self.pump(lambda: window.installation_info is not None)
        self.assertEqual(window.host, "hookshot")
        self.assertEqual(window.fields["game"].get(), str(self.base / "Hookshot"))
        self.assertEqual(window.fields["romfs"].get(), str(self.base / "Hookshot/romfs"))
        self.assertEqual(window.target_mods, str(self.base / "Hookshot/mods"))

    def test_stale_installation_check_cannot_enable_an_unsupported_edited_folder(self):
        self.service.preflight_gate = threading.Event()
        window = self.open()
        self.pump(self.service.preflight_started.is_set)
        window.fields["game"].set(str(self.base / "Unsupported game"))
        self.service.preflight_gate.set()
        self.prepare_form(window)
        self.pump(lambda: window.installation_message == "game_invalid")
        self.assertIsNone(window.installation_info)
        self.assertEqual(str(window.install_button.cget("state")), "disabled")
        self.assertEqual(window.installation_label.cget("text"), UnsupportedGame.public_message)
        self.assertTrue(all(thread != threading.get_ident() for _, thread in self.service.preflight_calls))
        self.assertFalse(self.service.calls)
        self.assertEqual(window.fields["romfs"].get(), str(self.base / "Unsupported game/romfs"))

    def test_password_visibility_is_explicit_and_does_not_change_the_password(self):
        window = self.open()
        window.fields["password"].set("example-value")
        self.assertTrue(window.password_entry.cget("show"))
        window.show_password.set(True)
        window._reveal_password()
        self.assertEqual(window.password_entry.cget("show"), "")
        window.show_password.set(False)
        window._reveal_password()
        self.assertTrue(window.password_entry.cget("show"))
        self.assertEqual(window.fields["password"].get(), "example-value")

    def test_install_erases_password_and_runs_service_outside_tk_thread(self):
        window = self.open()
        self.prepare_form(window)
        self.service.install_gate = threading.Event()
        window.fields["password"].set("temporary-password-123")
        window.install_button.invoke()
        self.assertEqual(window.fields["password"].get(), "")
        self.pump(self.service.install_started.is_set)
        self.assertTrue(window.busy)
        self.assertEqual(str(window.install_button.cget("state")), "disabled")
        self.assertEqual(str(window.help_button.cget("state")), "normal")
        self.assertEqual(self.service.calls[0][1]["password"], "temporary-password-123")
        self.assertNotEqual(self.service.calls[0][2], threading.get_ident())
        self.assertTrue(self.service.calls[0][1]["rebuild"])
        self.service.install_gate.set()
        self.pump(lambda: not window.busy)
        self.assertEqual(window.page, "home")
        self.assertEqual(str(window.play_button.cget("state")), "normal")
        self.assertIn("Test Room", window.home_room.cget("text"))
        window.play_button.invoke()
        self.pump(lambda: not window.busy)
        self.assertEqual(self.service.calls[-1][0], "launch")

    def test_close_waits_for_safe_worker_cancellation(self):
        window = self.open()
        self.prepare_form(window)
        self.service.install_gate = threading.Event()
        window.install_button.invoke()
        self.pump(self.service.install_started.is_set)
        window.close()
        self.assertTrue(window.cancel_event.is_set())
        self.assertFalse(window.closed)
        self.pump(lambda: window.closed)
        self.assertFalse(window.current.get("ready"))

    def test_stale_manifest_result_cannot_enable_install_for_another_file(self):
        window = self.open()
        self.service.inspect_gate = threading.Event()
        window.fields["manifest"].set(str(self.base / "old.apootrr"))
        self.pump(self.service.inspect_started.is_set)
        window.fields["manifest"].set(str(self.base / "invalid.apootrr"))
        self.service.inspect_gate.set()
        self.pump(lambda: window.manifest_message == "invalid_player")
        self.assertIsNone(window.manifest_info)
        self.assertEqual(str(window.install_button.cget("state")), "disabled")
        self.assertNotIn("private details", window.manifest_label.cget("text"))

    def test_arbitrary_worker_exception_is_not_shown_as_a_password_or_traceback(self):
        window = self.open()
        self.prepare_form(window)
        self.service.install_error = RuntimeError("secret-password-in-the-lower-level-error")
        window.install_button.invoke()
        self.pump(lambda: not window.busy)
        self.assertEqual(window.status.cget("text"), tr(TEXT["setup_failed"]))
        self.assertNotIn("secret-password", window.status.cget("text"))

    def test_saved_yaml_preserves_quoted_player_name_and_leaves_other_files_untouched(self):
        window = self.open()
        window.show_page("yaml")
        window.player_name.set('Link: "A"')
        self.dialogs.save = str(self.base / "Player.yaml")
        untouched = self.base / "Other.yaml"
        untouched.write_bytes(b"unchanged")
        window.save_yaml_button.invoke()
        self.pump(lambda: not window.busy)
        text = Path(self.dialogs.save).read_text(encoding="utf-8")
        self.assertEqual(json.loads(next(line[6:] for line in text.splitlines() if line.startswith("name: "))), 'Link: "A"')
        self.assertIn("  death_link: false\n", text)
        self.assertEqual(untouched.read_bytes(), b"unchanged")
        window.player_name.set("Archipelago")
        count = len(self.dialogs.calls)
        window.save_yaml_button.invoke()
        self.assertEqual(len(self.dialogs.calls), count)
        self.assertEqual(window.status_key, "yaml_name_error")

    def test_cancelled_save_dialog_writes_nothing(self):
        window = self.open()
        window.save_yaml()
        self.assertFalse(window.busy)
        self.assertFalse(list(self.base.iterdir()))

    def test_apworld_install_uses_the_selected_folder_and_no_game_setup(self):
        window = self.open()
        self.dialogs.directory = str(self.base)
        calls = []
        runtime = types.SimpleNamespace(install_apworld=lambda target: calls.append(target))
        with patch.dict(sys.modules, {"ootrr_triforce.app_runtime": runtime}):
            window.install_world()
            self.pump(lambda: not window.busy)
        self.assertEqual(calls, [self.base])
        self.assertFalse(self.service.calls)
        self.assertEqual(window.status_key, "world_installed")

    def test_connection_controls_are_in_process_and_do_not_close_the_main_app(self):
        created = []
        class Child:
            def __init__(self, master, **kwargs):
                self.master, self.closed = master, False
                created.append(kwargs)
            def close(self):
                self.closed = True
                self.master.destroy()
        self.service.discovery.update(ready=True, profile=str(self.base / "profile"), slot="Link", room="Room A")
        window = self.open(connection_factory=Child)
        window.connection_button.invoke()
        child = window.connection_window
        window.connection_button.invoke()
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["explicit"], self.base / "profile")
        child.close()
        self.assertTrue(window.master.winfo_exists())
        self.assertFalse(window.closed)

    def test_game_language_translates_the_actual_widgets(self):
        self.service.discovery["language"] = "fr"
        window = self.open()
        self.assertEqual(window.language, "fr")
        self.assertNotEqual(window.play_button.cget("text"), TEXT["play"])
        for widget, key in window.translated_widgets:
            self.assertEqual(widget.cget("text"), tr(TEXT[key], language="fr"))
        self.assertEqual(window.master.title(), tr(TEXT["title"], language="fr"))

    def test_licenses_are_exported_on_the_worker_and_opened_afterwards(self):
        opened, exported = [], []
        window = self.open(open_path=lambda path: opened.append((path, threading.get_ident())))
        def export(base):
            exported.append((base, threading.get_ident()))
            return base / "licenses"
        runtime = types.SimpleNamespace(export_licenses=export)
        with patch.dict(sys.modules, {"ootrr_triforce.app_runtime": runtime}):
            window.open_licenses()
            self.pump(lambda: not window.busy)
        self.assertEqual(exported[0][0], self.base)
        self.assertNotEqual(exported[0][1], threading.get_ident())
        self.assertEqual(opened, [(self.base / "licenses", threading.get_ident())])

    def test_about_has_the_packaged_version_and_an_interactive_project_link(self):
        (self.base / "VERSION").write_text("0.7.0-alpha.1\n", encoding="utf-8")
        window = self.open()
        runtime = types.SimpleNamespace(resource_root=lambda: self.base)
        with patch.dict(sys.modules, {"ootrr_triforce.app_runtime": runtime}):
            window.about()
        window.about()
        self.root.update()
        children = window.about_window.winfo_children()[0].winfo_children()
        texts = [child.cget("text") for child in children]
        self.assertIn("0.7.0-alpha.1", texts)
        link, = [child for child in children if child.cget("text").startswith("https://github.com/")]
        self.assertTrue(link.bind("<Button-1>"))
        self.assertTrue(link.bind("<Return>"))

    def test_settings_editor_changes_are_exported_and_import_preserves_legacy_mode(self):
        from ootrr_triforce.settings_editor import PlayerConfiguration
        window = self.open()
        window.open_settings()
        window.settings_window.variables["death_link"].set("true")
        window.settings_window.apply()
        self.assertTrue(window.yaml_document.values["death_link"])
        self.dialogs.save = str(self.base / "full.yaml")
        window.save_yaml()
        self.pump(lambda: not window.busy)
        self.assertEqual(PlayerConfiguration.read(self.dialogs.save).mode, "full_network")
        original = PlayerConfiguration.new("legacy", "Old Link")
        original.values["starting_hearts"] = 5
        original.write(self.base / "legacy.yaml")
        self.dialogs.open = str(self.base / "legacy.yaml")
        window.import_configuration()
        self.pump(lambda: not window.busy)
        self.assertEqual(window.yaml_document.mode, "legacy")
        self.assertEqual(window.player_name.get(), "Old Link")
        self.assertEqual(window.yaml_document.values["starting_hearts"], 5)

    def test_update_check_runs_on_worker_and_does_not_launch_a_game(self):
        window = self.open()
        (self.base / "VERSION").write_text("0.11.0-alpha.1\n", encoding="utf-8")
        calls = []
        def check(version, include_prereleases=False):
            calls.append((version, include_prereleases, threading.get_ident()))
            return None
        runtime = types.SimpleNamespace(resource_root=lambda: self.base)
        updater = types.SimpleNamespace(check_for_update=check)
        with patch.dict(sys.modules, {"ootrr_triforce.app_runtime": runtime, "ootrr_triforce.update_service": updater}):
            window.check_updates()
            self.pump(lambda: not window.busy)
        self.assertEqual(window.status_key, "up_to_date")
        self.assertEqual(calls[0][:2], ("0.11.0-alpha.1", True))
        self.assertNotEqual(calls[0][2], threading.get_ident())
        self.assertFalse(self.service.calls)

    def test_verified_update_is_staged_on_worker_without_replacing_the_application(self):
        window = self.open()
        target = self.base / "updates/new.exe"
        calls = []
        update = types.SimpleNamespace(path=target)
        def prepare(release, destination):
            calls.append((release, destination, threading.get_ident()))
            return update
        updater = types.SimpleNamespace(prepare_update=prepare)
        release = types.SimpleNamespace(version="0.12.0", signed=True)
        with patch.dict(sys.modules, {"ootrr_triforce.update_service": updater}):
            window.download_update(release)
            self.pump(lambda: not window.busy)
        self.assertEqual(window.pending_update, update)
        self.assertEqual(calls[0][1], self.base / "updates")
        self.assertNotEqual(calls[0][2], threading.get_ident())
        self.assertEqual(window.status_key, "verified_update")
        self.assertFalse(self.service.calls)

    def test_failed_updated_application_start_restores_previous_executable(self):
        import hashlib
        from ootrr_triforce.update_service import install_prepared
        window = self.open()
        executable, downloaded = self.base / "app.exe", self.base / "new.exe"
        executable.write_bytes(b"previous executable")
        downloaded.write_bytes(b"verified replacement")
        window.pending_update = types.SimpleNamespace(path=downloaded, sha256=hashlib.sha256(downloaded.read_bytes()).hexdigest())
        runtime = types.SimpleNamespace(spawn_process=lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("private error")))
        updater = types.SimpleNamespace(install_prepared=install_prepared)
        with patch.dict(sys.modules, {"ootrr_triforce.app_runtime": runtime, "ootrr_triforce.update_service": updater}), \
             patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(executable)):
            window.install_update()
            self.pump(lambda: not window.busy)
        self.assertEqual(executable.read_bytes(), b"previous executable")
        self.assertEqual(window.status_key, "update_install_failed")
        self.assertNotIn("private", window.status.cget("text"))

    def test_connected_external_room_blocks_application_restart_without_replacing_files(self):
        window = self.open()
        window.pending_update = types.SimpleNamespace(path=self.base / "not-installed.exe")
        window.external_window = types.SimpleNamespace(closed=False, runtime=object(), busy=False,
                                                       close=lambda: None)
        with patch.object(sys, "frozen", True, create=True):
            window.install_update()
        self.assertFalse(window.busy)
        self.assertEqual(window.status_key, "external_update_busy")
        self.assertFalse(window.pending_update.path.exists())
        window.external_window = None

    def test_help_uses_the_bundled_french_guide_with_language_matched_online_fallback(self):
        opened = []
        window = self.open(open_path=opened.append)
        window.language = "fr"
        guide = self.base / "distribution/Guide-FR.txt"
        guide.parent.mkdir()
        guide.write_text("Guide utilisateur de test.", encoding="utf-8")
        runtime = types.SimpleNamespace(resource_root=lambda: self.base)
        with patch.dict(sys.modules, {"ootrr_triforce.app_runtime": runtime}), \
             patch("ootrr_triforce.app_window.webbrowser.open") as browser:
            window.open_guide()
            self.assertEqual(opened, [guide])
            browser.assert_not_called()
            window.language = "en"
            window.open_guide()
            self.assertTrue(browser.call_args.args[0].endswith("/distribution/Guide.txt"))


class YamlTests(unittest.TestCase):
    def test_every_app_message_has_a_french_translation(self):
        catalogue = json.loads((ROOT / "client/ootrr_triforce/i18n_fr.json").read_bytes())
        self.assertEqual(set(TEXT.values()) - set(catalogue), set())

    def test_invalid_player_names_fail_without_any_file_operation(self):
        for name in ("", " ", "Archipelago", "a" * 17, "Link\nOther"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                yaml_content(name)


if __name__ == "__main__":
    unittest.main()
