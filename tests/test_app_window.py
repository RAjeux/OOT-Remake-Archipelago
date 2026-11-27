"""Actual-widget coverage for the app's normal setup and launch workflow."""
import json
import copy
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


class FakeUpdater:
    def __init__(self):
        self.release = {"current_version": "0.10.1-alpha.3", "latest_version": "0.10.1-alpha.3",
                        "update_available": False, "can_install": True,
                        "release_url": "https://github.com/RAjeux/OOT-Remake-Archipelago/releases",
                        "assets": {"apworld": {"sha256": "b" * 64}}}
        self.check_gate = self.download_gate = self.schedule_gate = None
        self.check_started, self.download_started, self.schedule_started = (threading.Event() for _ in range(3))
        self.check_error = self.schedule_error = None
        self.checks, self.downloads, self.schedules, self.world_checks = [], [], [], []
        self.changed = True

    def available(self, *, can_install=True):
        self.release.update(latest_version="0.10.1-alpha.4", update_available=True, can_install=can_install)

    def check_for_updates(self):
        self.checks.append(threading.get_ident())
        self.check_started.set()
        if self.check_gate:
            self.check_gate.wait(4)
        if self.check_error:
            raise self.check_error
        return copy.deepcopy(self.release)

    def apworld_status(self, target, expected):
        self.world_checks.append((target, expected, threading.get_ident()))
        return {"target": str(Path(target).resolve()), "changed": self.changed,
                "current_sha256": "a" * 64, "expected_sha256": expected, "exists": True}

    def download_update(self, release, *, base=None, progress=None, cancel=None):
        self.downloads.append((release, base, threading.get_ident()))
        self.download_started.set()
        if progress:
            progress(30, "Downloading the launcher update…")
        while self.download_gate and not self.download_gate.wait(.01):
            if cancel.is_set():
                raise InterruptedError("Setup cancelled.")
        if cancel.is_set():
            raise InterruptedError("Setup cancelled.")
        return {"version": release["latest_version"], "stage": "private synthetic download " + str(len(self.downloads))}

    def schedule_install(self, download, *, base=None, world_target=None):
        self.schedules.append((download, base, world_target, threading.get_ident()))
        self.schedule_started.set()
        if self.schedule_gate:
            self.schedule_gate.wait(4)
        if self.schedule_error:
            raise self.schedule_error
        return {"helper_started": True}


class AppWindowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.service = FakeService(self.base)
        self.dialogs = FakeDialogs()
        self.updater = FakeUpdater()
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
        for gate in (self.updater.check_gate, self.updater.download_gate, self.updater.schedule_gate):
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
        self.window = AppWindow(self.root, service=self.service, base=self.base, dialogs=self.dialogs,
                                updater=self.updater, **kwargs)
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

    def test_sidebar_navigation_keeps_the_yaml_draft_and_connection_fields(self):
        window = self.open()
        window.player_name.set("My player")
        window.yaml_values["death_link"] = True
        window.fields["server"].set("archipelago.gg:12345")
        for page in ("yaml", "home", "setup", "yaml"):
            window.nav_buttons[page].invoke()
            self.assertEqual(window.page, page)
            self.assertEqual(window.nav_buttons[page].cget("style"), "App.NavActive.TButton")
        self.assertEqual(window.player_name.get(), "My player")
        self.assertTrue(window.yaml_values["death_link"])
        self.assertEqual(window.fields["server"].get(), "archipelago.gg:12345")

    def test_keyboard_focus_reveals_lower_form_fields_on_a_small_window(self):
        window = self.open()
        self.root.geometry("900x640")
        self.root.deiconify()
        window.show_page("setup")
        self.root.update()
        window.password_entry.focus_force()
        self.root.update()
        canvas = window.setup_canvas
        field = window.password_entry
        self.assertGreaterEqual(field.winfo_rooty(), canvas.winfo_rooty())
        self.assertLessEqual(field.winfo_rooty() + field.winfo_height(), canvas.winfo_rooty() + canvas.winfo_height())
        self.assertGreater(canvas.yview()[0], 0)
        self.assertLessEqual(window.install_button.winfo_rooty() + window.install_button.winfo_height(),
                             self.root.winfo_rooty() + self.root.winfo_height())

    def test_small_window_wraps_the_room_description_instead_of_clipping_it(self):
        window = self.open()
        self.root.geometry("900x640")
        self.root.deiconify()
        window.show_page("setup")
        self.root.update()
        self.assertLessEqual(int(window.setup_intro.cget("wraplength")), window.setup_canvas.winfo_width())

    def test_tab_navigation_does_not_enter_controls_on_another_page(self):
        window = self.open()
        self.root.deiconify()
        for page in ("home", "setup", "yaml"):
            window.show_page(page)
            self.root.update()
            hidden = [str(frame) + "." for name, frame in window.page_frames.items() if name != page]
            target, seen = str(self.root), set()
            for _ in range(200):
                target = str(self.root.tk.call("tk_focusNext", target))
                if target in seen:
                    break
                seen.add(target)
                self.assertFalse(any(target.startswith(prefix) for prefix in hidden), (page, target))
            self.assertTrue(seen)

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

    def test_background_update_check_does_not_block_play_or_open_a_dialog(self):
        self.updater.check_gate = threading.Event()
        self.updater.available()
        self.service.discovery.update(ready=True, profile=str(self.base / "profile"))
        window = self.open()
        self.pump(self.updater.check_started.is_set)
        self.assertFalse(window.busy)
        window.play_button.invoke()
        self.pump(lambda: any(call[0] == "launch" for call in self.service.calls) and not window.busy)
        self.assertTrue(window.update_checking)
        self.assertIsNone(window.update_window)
        self.updater.check_gate.set()
        self.pump(lambda: window.update_release is not None)
        self.assertEqual(window.update_button.winfo_manager(), "grid")
        self.assertIsNone(window.update_window)
        self.assertTrue(all(ident != threading.get_ident() for ident in self.updater.checks))

    def test_current_version_has_no_update_button_and_manual_errors_keep_play_available(self):
        self.service.discovery.update(ready=True, profile=str(self.base / "profile"))
        window = self.open()
        self.pump(lambda: self.updater.checks and not window.update_checking)
        self.assertEqual(window.update_button.winfo_manager(), "")
        self.updater.check_error = RuntimeError("private-token-must-not-appear")
        window.check_updates(manual=True)
        self.pump(lambda: not window.update_checking)
        self.assertEqual(window.update_notice.cget("text"), window._text("launcher_check_failed"))
        self.assertEqual(str(window.play_button.cget("state")), "normal")
        self.assertNotIn("private-token", window.update_notice.cget("text"))

    def open_available_update(self, *, changed=True, can_install=True):
        self.updater.available(can_install=can_install)
        self.updater.changed = changed
        window = self.open()
        self.pump(lambda: window.update_release is not None)
        window.update_targets = [str(self.base / "AP/custom_worlds")]
        window.update_button.invoke()
        self.pump(lambda: not window.update_window.world_checking)
        return window, window.update_window

    def test_changed_apworld_is_optional_and_only_selected_target_is_passed_to_installer(self):
        window, review = self.open_available_update()
        self.assertFalse(review.want_world.get())
        self.assertFalse(review.world.instate(["disabled"]))
        review.world.invoke()
        review.primary.invoke()
        self.pump(lambda: not window.busy)
        self.assertTrue(review.download)
        self.assertTrue(review.want_world.get())
        review.primary.invoke()
        self.pump(lambda: window.closed)
        self.assertEqual(self.updater.schedules[0][2], str((self.base / "AP/custom_worlds").resolve()))
        self.assertNotEqual(self.updater.schedules[0][3], threading.get_ident())
        self.assertFalse(self.service.calls)

    def test_identical_apworld_cannot_be_selected_and_is_not_passed_to_installer(self):
        window, review = self.open_available_update(changed=False)
        self.assertTrue(review.world.instate(["disabled"]))
        review.want_world.set(True)  # Programmatic changes must not bypass the identity guard.
        review.primary.invoke()
        self.pump(lambda: not window.busy)
        review.primary.invoke()
        self.pump(lambda: window.closed)
        self.assertIsNone(self.updater.schedules[0][2])

    def test_source_mode_can_review_release_but_cannot_schedule_python_replacement(self):
        window, review = self.open_available_update(can_install=False)
        self.assertTrue(review.primary.instate(["disabled"]))
        self.assertTrue(review.source_note.winfo_manager())
        review.proceed()
        self.assertFalse(self.updater.downloads)
        self.assertFalse(self.updater.schedules)
        self.assertFalse(window.closed)

    def test_french_source_update_review_keeps_its_actions_inside_the_window(self):
        self.service.discovery["language"] = "fr"
        window, review = self.open_available_update(can_install=False)
        self.root.update_idletasks()
        bottom = review.master.winfo_rooty() + review.master.winfo_height()
        for button in (review.primary, review.close_button, review.release_button):
            self.assertLessEqual(button.winfo_rooty() + button.winfo_height(), bottom)

    def test_closing_during_final_update_handoff_does_not_cancel_or_destroy_the_launcher(self):
        window, review = self.open_available_update()
        review.primary.invoke()
        self.pump(lambda: not window.busy)
        self.updater.schedule_gate = threading.Event()
        review.primary.invoke()
        self.pump(self.updater.schedule_started.is_set)
        window.close()
        review.close()
        window.cancel()
        self.assertFalse(window.closed)
        self.assertFalse(review.closed)
        self.assertFalse(window.cancel_event.is_set())
        self.updater.schedule_gate.set()
        self.pump(lambda: window.closed)

    def test_failed_update_handoff_keeps_the_launcher_open_and_does_not_show_private_details(self):
        window, review = self.open_available_update()
        review.primary.invoke()
        self.pump(lambda: not window.busy)
        self.updater.schedule_error = RuntimeError("secret-in-private-helper-error")
        review.primary.invoke()
        self.pump(lambda: not window.busy)
        self.assertFalse(window.closed)
        self.assertFalse(review.closed)
        self.assertEqual(window.status_key, "launcher_update_failed")
        self.assertNotIn("secret", review.status.cget("text"))
        self.assertIsNone(window.update_download)
        self.assertIsNone(review.download)

    def test_failed_helper_handoff_retries_via_a_fresh_download_while_keeping_the_world_choice(self):
        window, review = self.open_available_update()
        review.world.invoke()
        selected = review.selected_world()
        review.primary.invoke()
        self.pump(lambda: not window.busy)
        previous_stage = review.download["stage"]
        self.updater.schedule_error = RuntimeError("temporary helper startup failure")
        review.primary.invoke()
        self.pump(lambda: not window.busy)
        self.assertFalse(window.closed)
        self.assertTrue(review.want_world.get())
        self.assertEqual(review.selected_world(), selected)
        self.assertIsNone(review.download)
        self.updater.schedule_error = None
        review.primary.invoke()
        self.pump(lambda: not window.busy)
        self.assertEqual(len(self.updater.downloads), 2)
        self.assertEqual(len(self.updater.schedules), 1)
        self.assertNotEqual(review.download["stage"], previous_stage)
        review.primary.invoke()
        self.pump(lambda: window.closed)
        self.assertEqual(len(self.updater.schedules), 2)
        self.assertEqual(self.updater.schedules[-1][2], selected)

    def test_closing_during_download_cancels_and_waits_for_worker_before_exit(self):
        window, review = self.open_available_update()
        self.updater.download_gate = threading.Event()
        review.primary.invoke()
        self.pump(self.updater.download_started.is_set)
        window.close()
        self.assertFalse(window.closed)
        self.assertTrue(window.cancel_event.is_set())
        self.pump(lambda: window.closed)
        self.assertFalse(self.updater.schedules)

    def test_apworld_check_from_a_previous_folder_cannot_change_the_selected_target(self):
        window, review = self.open_available_update()
        gate, started = threading.Event(), threading.Event()
        first, second = str(self.base / "AP-one"), str(self.base / "AP-two")
        original = self.updater.apworld_status
        def check(target, expected):
            if target == first:
                started.set()
                gate.wait(3)
                return dict(original(target, expected), changed=False)
            return original(target, expected)
        with patch.object(self.updater, "apworld_status", check):
            window.choose_update_world(first)
            self.pump(started.is_set)
            window.choose_update_world(second)
            self.pump(lambda: not review.world_checking)
            gate.set()
            self.pump(lambda: len(self.updater.world_checks) >= 3)
            for _ in range(12):
                self.root.update()
                time.sleep(.005)
        self.assertEqual(review.world_status["target"], str(Path(second).resolve()))
        self.assertTrue(review.world_status["changed"])

    def test_open_update_review_cannot_change_its_target_during_room_preparation(self):
        window, review = self.open_available_update()
        self.prepare_form(window)
        self.service.install_gate = threading.Event()
        window.install()
        self.pump(self.service.install_started.is_set)
        self.assertTrue(review.primary.instate(["disabled"]))
        self.assertTrue(review.folder.instate(["disabled"]))
        self.assertTrue(review.browse.instate(["disabled"]))
        review.proceed()
        self.assertFalse(self.updater.downloads)
        self.service.install_gate.set()
        self.pump(lambda: not window.busy)
        self.assertFalse(review.primary.instate(["disabled"]))

    def test_unchecked_folder_value_cannot_replace_the_previous_verified_world(self):
        window, review = self.open_available_update()
        review.want_world.set(True)
        review.target.set(str(self.base / "Unverified-folder"))
        self.assertIsNone(review.selected_world())

    def test_update_completion_notice_uses_french_without_an_automatic_dialog(self):
        self.service.discovery["language"] = "fr"
        window = self.open(startup_notice={"world_updated": False, "error_code": "world_failed"})
        self.pump(lambda: self.updater.checks and not window.update_checking)
        self.assertEqual(window.update_notice.cget("text"), window._text("launcher_world_failed"))
        self.assertNotEqual(window.update_notice.cget("text"), TEXT["launcher_world_failed"])
        self.assertIsNone(window.update_window)
        self.assertEqual(window.update_world_button.winfo_manager(), "grid")

    def test_filename_failure_does_not_offer_an_unrelated_apworld_repair(self):
        self.service.discovery["language"] = "fr"
        window = self.open(startup_notice={"world_updated": False, "error_code": "update_completion_failed", "completion_failed": True})
        self.pump(lambda: self.updater.checks and not window.update_checking)
        self.assertEqual(window.update_notice.cget("text"), window._text("launcher_finalize_failed"))
        self.assertNotEqual(window.update_notice.cget("text"), TEXT["launcher_finalize_failed"])
        self.assertEqual(window.update_world_button.winfo_manager(), "")

    def test_stale_prepared_resources_explain_repreparation_without_asking_for_a_new_save(self):
        self.service.discovery.update(ready=False, profile=str(self.base / "profile"), resources_update_required=True)
        self.service.discovery["language"] = "fr"
        window = self.open()
        self.assertEqual(window.home_room.cget("text"), window._text("resources_update_needed"))
        self.assertEqual(str(window.play_button.cget("state")), "disabled")

    def test_cancel_download_in_review_keeps_launcher_open_with_a_cancelled_result(self):
        window, review = self.open_available_update()
        self.updater.download_gate = threading.Event()
        review.primary.invoke()
        self.pump(self.updater.download_started.is_set)
        review.close()
        self.pump(lambda: not window.busy)
        self.assertFalse(window.closed)
        self.assertTrue(review.closed)
        self.assertEqual(window.status_key, "launcher_download_cancelled")


class YamlTests(unittest.TestCase):
    def test_every_app_message_has_a_french_translation(self):
        catalogue = json.loads((ROOT / "client/ootrr_triforce/i18n_fr.json").read_bytes())
        self.assertEqual(set(TEXT.values()) - set(catalogue), set())
        from ootrr_triforce.update_window import TEXT as update_text
        self.assertEqual(set(update_text.values()) - set(catalogue), set())

    def test_invalid_player_names_fail_without_any_file_operation(self):
        for name in ("", " ", "Archipelago", "a" * 17, "Link\nOther"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                yaml_content(name)


if __name__ == "__main__":
    unittest.main()
