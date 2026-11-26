"""Real chest guests use safe models while their AP effects retain real actors."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce.catalog import CHESTS, EXACT_BUNDLE_REWARDS, ITEM_DATA, ITEM_IDS
from ootrr_triforce.native_presentations import LOCAL_CHEST_PREFIX
from ootrr_triforce.presentation_models import chest_model_actor


@unittest.skipUnless(os.environ.get("OOTRR_ROMFS"), "requires native v1.1.1 chest graphs and maps")
class NativeChestPresentationTests(unittest.TestCase):
    def test_local_guests_and_native_rewards_are_separate_for_every_supported_chest_path(self):
        from ootrr_triforce import app_runtime, medallions
        from ootrr_triforce.mod_codec import Codec
        from oot_rando.formats import byml_codec
        from oot_rando.formats.inspect_resources import Byml
        from oot_rando.patching import ap_item, chest_flags
        from oot_rando.patching.event_patch import _snapshot
        from oot_rando.patching.progressive import FlowEditor
        from evfl.event import SubFlowEvent
        game = Path(os.environ["OOTRR_ROMFS"])
        staged = Path(os.environ["OOTRR_STARTER_MOD"]) if os.environ.get("OOTRR_STARTER_MOD") else game
        items = ["Ocarina", "Bolero of Fire", "Fire Medallion", "Small Key (Forest Temple)", "Master Sword",
                 *EXACT_BUNDLE_REWARDS]
        locations = list(CHESTS)[:len(items) + 1]
        local = dict(zip(locations, items))
        placements = {location: ap_item.ap_item(location + " fixture reward") for location in locations}
        with patch.object(app_runtime, "_resource_override", Path(os.environ["OOTRR_CODEC_RESOURCES"])):
            codec = Codec((game / "Pack/ZsDic.pack.zs").read_bytes())

            def read(path):
                candidate = staged / path
                return codec.decode((candidate if candidate.is_file() else game / path).read_bytes())

            rows = {row["__RowId"]: row for row in byml_codec.load(read(chest_flags.EVENT_SETTINGS))["root"]}
            maps, wrappers = medallions.plan_maps(placements, {}, read, rows, preserve_local=False,
                                                  local_rewards=local)
            for location in locations:
                actual = ITEM_DATA[local[location]]["actor"] if location in local else ap_item.ap_actor(placements[location])
                shown = chest_model_actor(actual) if location in local else actual
                for ref in CHESTS[location]:
                    for path in ref["files"]:
                        actor = next(actor for actor in Byml(maps[path]).root["Actors"]
                                     if actor["Hash"] == int(ref["actor"]))
                        self.assertEqual(actor["Dynamic"]["Drop__DropActor"], shown)
                        self.assertEqual(actor["Dynamic"]["Drop__DropActor_Substitute"], shown)
                wrapper = next(row for row in wrappers if row["actor"] == actual)
                self.assertEqual(wrapper.get("local_reward"), local.get(location))

            pouch = read("Event/EventFlow/GetPouchContent.bfevfl.zs")
            small = read("Event/EventFlow/Dm_SY_TreasureboxSmall.bfevfl.zs")
            for flow_name in ("Dm_SY_Treasurebox", "Dm_SY_TreasureboxSmall"):
                path = "Event/EventFlow/" + flow_name + ".bfevfl.zs"
                source = read(path)
                group = [dict(record, flow=path) for record in wrappers]
                result = medallions.chest_flows(source, group, native_pouch=pouch, small_raw=small)
                editor = FlowEditor(result, "Native chest AP models")
                before = _snapshot(FlowEditor(source, "Original chest").flow)
                after = _snapshot(editor.flow)
                self.assertTrue(all(after[name] == params for name, params in before.items()))
                for item in items:
                    metadata = ITEM_DATA[item]
                    stem = LOCAL_CHEST_PREFIX + str(ITEM_IDS[item])
                    actual_actors = set(metadata.get("tiers", [metadata["actor"]]))
                    opened = [event for event in editor.chart.events
                              if event.name.startswith(stem) and event.name.endswith("_Open")
                              and isinstance(event.data, SubFlowEvent)]
                    self.assertEqual({event.data.params.data["ContentName"] for event in opened}, actual_actors)
                    # These aliases are physical guests only. No get-window,
                    # inventory recipe, progressive query or pose uses them.
                    for actual in actual_actors:
                        if chest_model_actor(actual) != actual:
                            self.assertNotIn(chest_model_actor(actual).encode(), result)
                    if item.startswith("Small Key"):
                        credit = [event.data.params.data.get("GameDataName") for event in editor.chart.events
                                  if event.name.startswith(stem) and getattr(event.data, "params", None)]
                        self.assertIn("DungeonInfo.ForestTemple.SmallKeyNum", credit)
                        self.assertNotIn("MiniGame_SmallKeyNum", credit)
                foreign = next(row for row in group if not row.get("local_reward"))
                point = next(point for point in editor.chart.entry_points if point.name == foreign["event"])
                self.assertEqual(point.main_event.v.data.params.data["ContentName"], foreign["actor"])
                self.assertEqual(point.main_event.v.data.entry_point_name, "Success_")


if __name__ == "__main__":
    unittest.main()
