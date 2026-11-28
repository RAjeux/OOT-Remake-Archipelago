"""Compatible Bow model upgrades preserve cameras, real grants and typed args."""
from contextlib import nullcontext
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from evfl.common import Argument
from evfl.container import Container
from evfl.event import ActionEvent, SubFlowEvent, SubFlowSwitchEvent
from oot_rando.patching.progressive import FlowEditor
from ootrr_triforce import presentation_models as models
from ootrr_triforce.bow_presentations import FAMILY, patch_bow_presentations, prepare_bow_presentations
from ootrr_triforce.catalog import ITEM_IDS
from ootrr_triforce.native_presentations import CAMERA_FACING_FLOW, PRESENTER_NAME, PRESENTER_PATH
from ootrr_triforce.receipt_events import FLOW_PATH, REST, build_presented_receipts, event_name
from test_held_framing import item_presenter
from test_presented_receipts import SceneRun, TOKEN, CURSOR, native_ground_camera, native_facing_animation
from test_receipt_events import native_flow


def old_models(enabled):
    current = models._separate_model
    return patch.object(models, "_separate_model", lambda actor: actor not in FAMILY and current(actor)) if enabled else nullcontext()


def receipts(old=False):
    with old_models(old):
        return build_presented_receipts(native_flow(), item_presenter(), TOKEN, ["Bow", "Mirror Shield"],
                                        ground_raw=native_ground_camera())[:2]


class BowPresenterTests(unittest.TestCase):
    def test_cached_all_three_tiers_match_fresh_generation_byte_for_byte(self):
        before = receipts(old=True)
        fresh = receipts()
        pouch, presenter, changes = patch_bow_presentations(*before)
        self.assertEqual((pouch, presenter), fresh)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["actors"], list(FAMILY))
        self.assertEqual(len(changes[0]["callers"]), 3)
        self.assertEqual(patch_bow_presentations(pouch, presenter), (pouch, presenter, []))
        self.assertEqual(patch_bow_presentations(*fresh), (*fresh, []))

    def test_models_and_forwarded_arguments_are_typed_but_real_actors_stay_literal(self):
        pouch, presenter, _ = patch_bow_presentations(*receipts(old=True))
        chart = FlowEditor(pouch, "Bow actor identity").chart
        calls = [node for node in chart.events if isinstance(node.data, SubFlowEvent)
                 and node.name.startswith(event_name(ITEM_IDS["Bow"]) + "_Tier") and node.name.endswith("_Show")]
        self.assertEqual({node.data.params.data["ActorName"] for node in calls}, set(FAMILY))
        for node in calls:
            params = node.data.params.data
            self.assertIs(type(params["ActorName"]), str)
            self.assertIs(type(params[models.SHOW_ACTOR_ARGUMENT]), str)
            self.assertEqual(params[models.SHOW_ACTOR_ARGUMENT], models.model_actor(params["ActorName"]))
        chart = FlowEditor(presenter, "Typed display arguments").chart
        prefix = "OOTRR_APShow_" + str(ITEM_IDS["Bow"]) + "_"
        for node in chart.events:
            if not node.name.startswith(prefix): continue
            data = node.data
            if isinstance(data, ActionEvent) and data.actor_action.v.v == "EventCreateShowItemFromActorFileName":
                self.assertIsInstance(data.params.data["Actor"], Argument)
                self.assertEqual(data.params.data["Actor"], models.SHOW_ACTOR_ARGUMENT)
            elif isinstance(data, (SubFlowEvent, SubFlowSwitchEvent)) and not data.res_flowchart_name:
                self.assertIsInstance(data.params.data[models.SHOW_ACTOR_ARGUMENT], Argument)

    def test_all_cameras_and_real_grant_effects_are_unchanged_on_each_tier(self):
        old_pouch, old_presenter = receipts(old=True)
        pouch, presenter, _ = patch_bow_presentations(old_pouch, old_presenter)
        for previous, updated in ((old_pouch, pouch), (old_presenter, presenter)):
            a, b = FlowEditor(previous, "Before").chart, FlowEditor(updated, "After").chart
            self.assertEqual([node.name for node in a.events], [node.name for node in b.events])
            for first, second in zip(a.events, b.events):
                if isinstance(first.data, ActionEvent) and "Camera" in first.data.actor_action.v.v:
                    self.assertEqual(first.data.params.data if first.data.params else None,
                                     second.data.params.data if second.data.params else None)
                if isinstance(first.data, SubFlowEvent):
                    self.assertEqual((first.data.res_flowchart_name, first.data.entry_point_name),
                                     (second.data.res_flowchart_name, second.data.entry_point_name))
        for owned, actor in ((set(), FAMILY[0]), ({"Weapon_Range_Bow"}, FAMILY[1]), ({FAMILY[1]}, FAMILY[2])):
            traces = []
            for first, second in ((old_pouch, old_presenter), (pouch, presenter)):
                charts = {name: FlowEditor(raw, name).chart for name, raw in (
                    ("GetPouchContent", first), (PRESENTER_NAME, second), (CAMERA_FACING_FLOW, native_facing_animation()))}
                run = SceneRun(charts, owned=owned.copy())
                run.run("GetPouchContent", event_name(ITEM_IDS["Bow"]))
                self.assertEqual(sum(command == "EventTriggerAddOrRemovePouchContent" and params["Actor"] == actor
                                     for command, params in run.trace), 1)
                self.assertEqual(sum(command == "EventTriggerAddOrSubGameDataInt" and params["GameDataName"] == CURSOR
                                     for command, params in run.trace), 1)
                self.assertFalse(any(command == "EventTriggerAddOrRemovePouchContent" and params["Actor"].startswith("Item_AP_")
                                     for command, params in run.trace))
                traces.append([(command, dict(params, Actor="display-model") if command == "EventCreateShowItemFromActorFileName" else params)
                               for command, params in run.trace])
            self.assertEqual(*traces)

    def test_late_adult_trade_and_pedestal_presenters_match_fresh_models(self):
        from ootrr_triforce import ap_master_sword
        from ootrr_triforce.ap_trade import build_trade_rewards
        from ootrr_triforce.trade_catalog import TRADE_CHECKS
        from test_ap_trade import pouch_fixture, reward
        cases = [({next(iter(TRADE_CHECKS)): reward("Bow")}, {})]
        roster = {ap_master_sword.LOCATION: reward("Bow")}
        cases.append((roster, dict(records=[ap_master_sword.reward_record(roster)], prefix=ap_master_sword.PREFIX,
                                  event_stem=ap_master_sword.event_name, reconcile=False)))
        for roster, kwargs in cases:
            graphs = []
            for old in (True, False):
                with old_models(old):
                    graphs.append(build_trade_rewards(pouch_fixture(), item_presenter(), roster,
                                                      ground_raw=native_ground_camera(), **kwargs)[:2])
            migrated = patch_bow_presentations(*graphs[0])
            self.assertEqual(migrated[:2], graphs[1])
            self.assertEqual(len(migrated[2]), 1)

    def test_partial_or_crossed_family_arguments_are_refused(self):
        for mode in ("partial", "alias", "tier", "entry"):
            pouch, presenter = receipts(old=True)
            editor = FlowEditor(pouch, "Incompatible cached identity")
            node = next(node for node in editor.chart.events if node.name == event_name(ITEM_IDS["Bow"]) + "_Tier0_Show")
            if mode == "partial": node.data.params.data[models.SHOW_ACTOR_ARGUMENT] = models.model_actor(FAMILY[0])
            elif mode == "alias": node.data.params.data[models.SHOW_ACTOR_ARGUMENT] = "Item_AP_Unknown"
            elif mode == "tier": node.data.params.data["ActorName"] = FAMILY[1]
            else: node.data.entry_point_name = "UnpublishedCameraWorkaround"
            editor.expected[node.name] = dict(node.data.params.data)
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                patch_bow_presentations(editor.write("Incompatible cached identity")[0], presenter)

    def test_unknown_creator_or_forwarded_argument_is_refused(self):
        for mode in ("creator", "forward"):
            pouch, presenter = receipts(old=True)
            editor = FlowEditor(presenter, "Unknown native model binding")
            prefix = "OOTRR_APShow_" + str(ITEM_IDS["Bow"]) + "_"
            if mode == "creator":
                node = next(node for node in editor.chart.events if node.name.startswith(prefix)
                            and isinstance(node.data, ActionEvent) and node.data.actor_action.v.v == "EventCreateShowItemFromActorFileName")
                node.data.params.data["Actor"] = "ActorName"  # Literal is not an EVFL Argument.
            else:
                node = next(node for node in editor.chart.events if node.name.startswith(prefix)
                            and isinstance(node.data, SubFlowEvent) and not node.data.res_flowchart_name)
                if node.data.params is None: node.data.params = Container()
                node.data.params.data[models.SHOW_ACTOR_ARGUMENT] = Argument("UnknownModelArgument")
            editor.expected[node.name] = dict(node.data.params.data)
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                patch_bow_presentations(pouch, editor.write("Unknown native model binding")[0])

    def test_staging_prepares_visual_resources_before_flow_publication_then_is_idempotent(self):
        pouch, presenter = receipts(old=True)
        class Codec:
            def __init__(self, _): pass
            def decode(self, raw): return raw
            def encode(self, raw, _): return raw
        with tempfile.TemporaryDirectory() as tmp:
            game, mod = Path(tmp) / "original", Path(tmp) / "stage"
            for root, path, value in ((game, "Pack/ZsDic.pack.zs", b"dictionary"), (game, REST, b"budgets"),
                                      (mod, FLOW_PATH, pouch), (mod, PRESENTER_PATH, presenter)):
                at = root / path; at.parent.mkdir(parents=True, exist_ok=True); at.write_bytes(value)
            def models_first(*_):
                self.assertEqual((mod / FLOW_PATH).read_bytes(), pouch)
                self.assertEqual((mod / PRESENTER_PATH).read_bytes(), presenter)
            with patch("ootrr_triforce.mod_codec.Codec", Codec), patch.object(models, "prepare_presentation_models", side_effect=models_first) as stage, patch(
                    "oot_rando.game.resource_allocations.grow_resources", side_effect=lambda raw, _: (raw, None)):
                self.assertEqual(prepare_bow_presentations(game, mod), {"presenters": 1, "written": 3})
                self.assertEqual(prepare_bow_presentations(game, mod), {"presenters": 0, "written": 0})
                stage.assert_called_once_with(game, mod)
            self.assertEqual((game / REST).read_bytes(), b"budgets")

    def test_legacy_without_family_does_not_require_presenter_or_model_resources(self):
        raw = native_flow()
        self.assertEqual(patch_bow_presentations(raw, b"not needed"), (raw, b"not needed", []))

    def test_ice_trap_shares_bow_metadata_without_becoming_a_bow_presenter_or_grant(self):
        with old_models(True):
            pouch, presenter, _ = build_presented_receipts(native_flow(), item_presenter(), TOKEN, ["Bow", "Ice Trap"],
                                                          ground_raw=native_ground_camera())
        pouch, presenter, changes = patch_bow_presentations(pouch, presenter)
        self.assertEqual(len(changes), 1)
        charts = {"GetPouchContent": FlowEditor(pouch, "Trap pouch").chart,
                  PRESENTER_NAME: FlowEditor(presenter, "Trap effect").chart}
        run = SceneRun(charts)
        run.run("GetPouchContent", event_name(ITEM_IDS["Ice Trap"]))
        self.assertEqual(sum(command == "FixtureNativeIceTrap" for command, _ in run.trace), 1)
        self.assertFalse(any(command == "EventTriggerAddOrRemovePouchContent" for command, _ in run.trace))
        self.assertEqual(sum(command == "EventTriggerAddOrSubGameDataInt" and params["GameDataName"] == CURSOR
                             for command, params in run.trace), 1)


if __name__ == "__main__":
    unittest.main()
