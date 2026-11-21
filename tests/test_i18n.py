"""Game language changes display text without changing Archipelago identities."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce import i18n, native_setup
from ootrr_triforce.catalog import CHESTS, GAME, ITEM_IDS, LEGACY_GAME, LOCATION_IDS
from ootrr_triforce.item_names import item_name
from ootrr_triforce.presentation import Presentation
from ootrr_triforce.room_view import RoomView


class LanguageTests(unittest.TestCase):
    def setUp(self):
        self.previous = i18n.get_language()
        i18n.set_language("en")

    def tearDown(self):
        i18n.set_language(self.previous)

    def test_english_default_french_catalogue_and_templates(self):
        self.assertEqual(i18n.tr("Selection cancelled."), "Selection cancelled.")
        self.assertEqual(i18n.tr("Unknown new message."), "Unknown new message.")
        i18n.set_language("fr-CA")
        self.assertEqual(i18n.tr("Selection cancelled."), "Sélection annulée.")
        self.assertEqual(i18n.tr("Player file created: {value0}", value0="Zelda.yaml"),
                         "Fichier joueur créé : Zelda.yaml")
        self.assertEqual(i18n.tr("Selection cancelled.", language="en"), "Selection cancelled.")
        self.assertEqual(i18n.tr("Unknown new message."), "Unknown new message.")
        for code in ("fr", "fr-CA", "fr_FR", "EUfr", "USfr"):
            self.assertEqual(i18n.normalize_language(code), "fr")
        for code in (None, "en-GB", "de", "ja", "invalid"):
            self.assertEqual(i18n.normalize_language(code), "en")

    def test_game_language_precedence_and_legacy_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game, profile = root / "game", root / "room"
            (game / "bin").mkdir(parents=True)
            profile.mkdir()
            config = {"ports": {"nx2navi": {"exe": str(game / "bin/Triforce.exe")}}}
            (profile / "language.json").write_text('{"language":"fr"}', encoding="utf-8")
            # Host-written state works with old configs lacking language fields.
            self.assertEqual(i18n.detect_language(profile, {}, environ={}), "fr")
            language = game / "language.txt"
            language.write_text("\ufeff# settings\n\nunknown\nfr-CA\n# en-US\n", encoding="utf-8")
            self.assertEqual(i18n.detect_language(profile, config, environ={}), "fr")
            self.assertEqual(i18n.detect_language(profile, config, environ={"HOS_LANGUAGE": "de"}), "en")
            self.assertEqual(i18n.detect_language(profile, config, environ={"HOS_LANGUAGE": "fr"}), "fr")
            # A present empty/unknown host override suppresses language.txt.
            self.assertEqual(i18n.detect_language(profile, config, environ={"HOS_LANGUAGE": ""}), "en")
            self.assertEqual(i18n.detect_language(profile, config, environ={"HOS_LANGUAGE": "fr-FR"}), "en")
            language.write_text("en-GB\nfr\n", encoding="utf-8")
            self.assertEqual(i18n.detect_language(profile, config, environ={}), "en")
            language.write_text("# no valid language\nunknown\n", encoding="utf-8")
            self.assertEqual(i18n.detect_language(profile, config, environ={}), "en")
            (profile / "language.json").write_text('{"language":[]}', encoding="utf-8")
            self.assertEqual(i18n.detect_language(profile, {}, environ={"LANG": "fr_FR.UTF-8"}), "en")
            (profile / "language.json").unlink()
            self.assertEqual(i18n.detect_language(profile, {}, environ={}), "en")

    def test_names_and_roster_remain_canonical_even_when_french_is_displayed(self):
        original = dict(ITEM_IDS)
        view = RoomView(2)
        packet = {"team": 0, "slot_info": {
            "1": {"name": "Ami", "game": "Dark Souls III"},
            "2": {"name": "Zelda", "game": GAME}}, "checked_locations": []}
        view.connected(packet)
        view.load_package({"data": {"games": {"Dark Souls III": {
            "item_name_to_id": {"Bow": 77}, "location_name_to_id": {}}}}})
        i18n.set_language("fr")
        self.assertEqual(view.name("item_id", ITEM_IDS["Bow"], 2), "Bow")
        self.assertEqual(view.display_name("item_id", ITEM_IDS["Bow"], 2), "Arc")
        self.assertEqual(view.display_name("item_id", 77, 1), "Bow")
        with tempfile.TemporaryDirectory() as directory:
            chest = next(iter(CHESTS))
            presentation = Presentation(Path(directory), {"checks": [chest], "local_items": True}, view)
            presentation.join(packet)
            presentation.scout([(77, LOCATION_IDS[chest], 1, 0)])
            reward = presentation.roster()[chest]
            self.assertEqual(reward["item"], "Bow")
            self.assertEqual(reward["game"], "Dark Souls III")
            self.assertFalse(reward["local"])
            presentation.local_items = False
            self.assertEqual(presentation.roster()[chest], ("Bow", "Ami"))
        self.assertEqual(ITEM_IDS, original)

    def test_receipt_notifications_follow_language_without_changing_receipt_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            view = RoomView(2)
            view.players[1] = "Ami"
            display = Presentation(Path(directory), {"checks": []}, view)
            display.fenced, display.cursor = True, 0
            notices = []
            display.hud.notify = lambda *args: notices.append(args)
            code = ITEM_IDS["Mirror Shield"]
            display.receipts([code], [(1, 42)])
            self.assertEqual(notices[-1], ("Item received via Archipelago", "Mirror Shield", "From Ami", "in"))
            i18n.set_language("fr")
            display.receipts([code, code], [(1, 42), (1, 43)])
            self.assertEqual(notices[-1], ("Objet reçu via Archipelago", item_name("Mirror Shield", "fr"), "De Ami", "in"))
            self.assertEqual(display.cursor, 2)
            self.assertEqual(code, ITEM_IDS["Mirror Shield"])

    def test_native_session_carries_language_names_and_foreign_game_without_replacing_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "language.json").write_text('{"language":"fr"}', encoding="utf-8")
            chest = next(iter(CHESTS))
            data = {"room": "test", "slot": "Zelda", "player": 2, "token": "0" * 64, "checks": [chest]}
            reward = {"item": "Bow", "player": "Ami", "game": "Dark Souls III"}
            with patch.dict("os.environ", {}, clear=True):
                native_setup.save_session(root, {"server": "ws://localhost:1", "protected": "", "baseline": 0},
                                          data, {chest: reward})
            session = json.loads((root / "native-session.json").read_bytes())
            self.assertEqual(session["Language"], "fr")
            self.assertEqual(session["Items"][str(ITEM_IDS["Bow"])], "Bow")
            self.assertEqual(session["ItemNames"][str(ITEM_IDS["Bow"])], {"en": "Bow", "fr": "Arc"})
            self.assertEqual(session["Checks"][str(LOCATION_IDS[chest])]["Game"], "Dark Souls III")
            self.assertEqual(session["Checks"][str(LOCATION_IDS[chest])]["Item"], "Bow")

    def test_observer_uses_only_the_active_game_marker(self):
        path = ROOT / "distribution/Observer-Archipelago.py"
        spec = importlib.util.spec_from_file_location("observer_i18n_test", path)
        observer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(observer)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(observer.observer_language(root, True), "en")
            (root / "language.json").write_text('{"language":"fr"}', encoding="utf-8")
            self.assertEqual(observer.observer_language(root, True), "fr")
            self.assertEqual(observer.observer_language(root, False), "en")

    def test_old_bootstrap_is_upgraded_once_and_missing_language_api_never_patches_tools(self):
        source = (ROOT / "references/triforce/host/hos_main.c").read_bytes().replace(b"\r\n", b"\n")
        patched = native_setup.patch_source(source)
        self.assertIn(b"ap_boot_error16();", patched)
        self.assertEqual(native_setup.patch_source(patched), patched)
        legacy = patched.replace(native_setup.BOOTSTRAP.encode(), native_setup.LEGACY_BOOTSTRAP.encode())
        self.assertNotEqual(legacy, patched)
        self.assertEqual(native_setup.patch_source(legacy), patched)
        with tempfile.TemporaryDirectory() as directory:
            tools = Path(directory) / "tools"
            host = tools / "host"
            host.mkdir(parents=True)
            target = host / "hos_main.c"
            target.write_bytes(source)
            (tools / "nx2").mkdir()
            (tools / "nx2/build.py").write_bytes(b"")
            (tools / "gpu/vk").mkdir(parents=True)
            (tools / "gpu/vk/vk_api.h").write_text("HOS_SHARE_NOTICE", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "incompatible"):
                native_setup.install_tools(Path(directory) / "profile", None, tools)
            self.assertEqual(target.read_bytes(), source)
            self.assertEqual(sorted(p.name for p in host.iterdir()), ["hos_main.c"])


if __name__ == "__main__":
    unittest.main()
