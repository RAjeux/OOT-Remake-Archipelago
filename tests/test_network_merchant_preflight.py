"""The bean AP purchase checks its own reward; repeats keep native stock limits."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))

from ootrr_triforce.network_merchant_preflight import (
    FLOW_PATH, LOCATION, MERCHANT_PATH, NATIVE_CALLS, REST,
    patch_preflight, prepare_merchant_preflight,
)


class MerchantSelectionTests(unittest.TestCase):
    def test_other_sources_and_old_room_preparation_need_no_resources(self):
        self.assertEqual(prepare_merchant_preflight("missing", "missing", []), {})
        self.assertEqual(prepare_merchant_preflight("missing", "missing", [{"name": "Other merchant"}]), {})


@unittest.skipUnless(os.environ.get("OOTRR_ROMFS"), "requires native v1.1.1 purchase flows")
class NativeMerchantPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ootrr_triforce import app_runtime
        from ootrr_triforce.mod_codec import Codec
        from ootrr_triforce.network_catalog import SOURCES
        from ootrr_triforce.network_rewards import source_records
        cls.native = Path(os.environ["OOTRR_ROMFS"])
        cls.override = patch.object(app_runtime, "_resource_override",
                                   Path(os.environ.get("OOTRR_CODEC_RESOURCES", ROOT / "dist")))
        cls.override.start()
        cls.codec = Codec((cls.native / "Pack/ZsDic.pack.zs").read_bytes())
        roster = {LOCATION: {"item": "Foreign reward", "player": "Other", "local": False}}
        settings = {"network_sources_schema": 1,
                    "network_sources": {LOCATION: dict(SOURCES[LOCATION], generated_item="Compass (Bottom of the Well)")}}
        cls.record = source_records(roster, settings)[0]

    @classmethod
    def tearDownClass(cls):
        cls.override.stop()

    def read(self, path):
        return self.codec.decode((self.native / path).read_bytes())

    def test_native_capacity_query_reads_actor_and_returns_full_for_max_stock(self):
        from ainb import AINB
        from oot_rando.formats.inspect_resources import sarc
        from oot_rando.formats.byml_codec import load
        pack = sarc(self.read("Pack/Actor/PouchSystemActor.pack.zs"))
        ai = AINB.from_binary(pack["AI/PouchSystemActor.event.root.ainb"]).as_dict()
        nodes = {row["Node Index"]: row for row in ai["Nodes"]}
        command = next(row for row in ai["Commands"] if row["Name"] == "EventQueryCanAddToPorch")
        self.assertEqual(command["Root Node Index"], 13)
        self.assertEqual(nodes[13]["Parameters"]["Outputs"]["String"][0]["Name"], "Actor")
        self.assertEqual(nodes[97]["Name"], "QueryIsMaxStockNum")
        self.assertEqual(nodes[97]["Parameters"]["Inputs"]["String"][0]["Node Index"], 13)
        self.assertEqual(nodes[16]["Parameters"]["Inputs"]["Bool"][0]["Node Index"], 97)
        full = next(row for row in nodes[16]["Plugs"]["Child"] if row["Name"] == "True")
        self.assertEqual(nodes[full["Node Index"]]["Name"], "ExecuteEventSetQueryValue")
        self.assertEqual(nodes[full["Node Index"]]["Parameters"]["Inputs"]["Int"][0]["Default Value"], 2)
        bean = sarc(self.read("Pack/Actor/Item_MagicBean.pack.zs"))
        param = load(bean["Component/PouchContentParam/Item_MagicBean.game__component__PouchContentParam.bgyml"])["root"]
        self.assertIs(param["EnableStock"], True)
        self.assertEqual(param["FixedMaxNum"], 10)

    def test_capacity_alone_changes_and_ten_native_beans_cannot_block_the_ap_reward(self):
        from evfl.common import Argument
        from oot_rando.patching.event_patch import _snapshot
        from oot_rando.patching.progressive import FlowEditor
        from ootrr_triforce.catalog import LOCATION_IDS
        before = self.read(FLOW_PATH)
        source = FlowEditor(before, FLOW_PATH)
        original = _snapshot(source.flow)
        after, count = patch_preflight(before, self.record)
        self.assertEqual(count, 1)
        checked = FlowEditor(after, FLOW_PATH)
        snapshot = _snapshot(checked.flow)
        self.assertEqual({name: snapshot[name] for name in original}, original)
        nodes = {event.name: event for event in checked.chart.events}
        stem = "OOTRR_APMerchant_" + str(LOCATION_IDS[LOCATION]) + "_"
        gate = nodes[stem + "Collected"]
        self.assertEqual(nodes["Event100"].data.cases[0].v, gate)
        self.assertEqual(gate.data.cases[0].v.name, "Event126")
        self.assertEqual(gate.data.cases[1].v.name, stem + "RewardCapacity")
        self.assertEqual(nodes["Event126"].data.params.data, {"Actor": Argument("ActorName")})
        reward_capacity = nodes[stem + "RewardCapacity"].data
        self.assertEqual(reward_capacity.params.data, {"Actor": self.record["actor"]})
        self.assertEqual({key: reference.v.name for key, reference in reward_capacity.cases.items()},
                         {0: "Event195", 2: "Event177"})
        # Walk the actual EVFL preflight, supplying only native query results.
        # Case0 is successful capacity; native stock-max returns case2 above.
        def purchase_target(collected, bean_stock, reward_stock=0):
            event = gate
            while event.name not in {"Event195", "Event177"}:
                data = event.data
                if data.actor_query.v.v == "EventQueryIsGameDataBool":
                    outcome = 0 if collected else 1
                else:
                    actor = data.params.data["Actor"]
                    if isinstance(actor, Argument):
                        actor = "Item_MagicBean"
                    full = bean_stock >= 10 if actor == "Item_MagicBean" else reward_stock >= 1
                    outcome = 2 if full else 0
                event = data.cases[outcome].v
            return event.name
        self.assertEqual(purchase_target(False, 10), "Event195")
        self.assertEqual(purchase_target(True, 10), "Event177")
        self.assertEqual(purchase_target(True, 9), "Event195")
        self.assertEqual(purchase_target(False, 10, 1), "Event177")
        self.assertEqual(patch_preflight(after, self.record), (after, 0))

    def test_actual_grant_switch_repeats_native_beans_after_the_once_only_ap_reward(self):
        from evfl.common import ActorIdentifier
        from oot_rando.patching.progressive import FlowEditor
        from ootrr_triforce.catalog import LOCATION_IDS
        from ootrr_triforce.network_flows import patch_reward
        editor = FlowEditor(self.read(FLOW_PATH), FLOW_PATH)
        original = next(event for event in editor.chart.events if event.name == "Event182")
        expected_native = dict(original.data.params.data, ReveiveItem="Item_MagicBean")
        self.assertEqual(expected_native["NpcActor"], ActorIdentifier("Npc_EventStarter"))
        patch_reward(editor, original, "ReveiveItem", self.record, "AP_TestBeanEffect", self.read, 0)
        raw = editor.write("Native repeat bean grant proof")[0]
        checked = FlowEditor(raw, FLOW_PATH).chart
        nodes = {event.name: event for event in checked.events}
        stem = "OOTRR_APSource_" + str(LOCATION_IDS[LOCATION]) + "_0"
        gate = nodes[stem + "_Collected"].data
        repeated, first = gate.cases[0].v.data, gate.cases[1].v.data
        self.assertEqual(repeated.res_flowchart_name, "NpcCommon")
        self.assertEqual(repeated.entry_point_name, "NpcCommon_HandOver_NpcToPlayer_NoDisplay")
        self.assertEqual(repeated.params.data, expected_native)
        self.assertEqual(repeated.nxt.v.name, "Event123")
        self.assertEqual(first.params.data["ReveiveItem"], self.record["actor"])
        self.assertNotEqual(first.params.data["ReveiveItem"], "Item_MagicBean")
        self.assertEqual(first.nxt.v.name, "Event123")

    def test_staged_preflight_preserves_all_price_calls_counter_and_other_resources(self):
        from evfl.event import SubFlowEvent
        from oot_rando.game.resource_allocations import allocation
        from oot_rando.patching.progressive import FlowEditor
        merchant = self.read(MERCHANT_PATH)
        caller = FlowEditor(merchant, MERCHANT_PATH).chart
        calls = [event for event in caller.events if isinstance(event.data, SubFlowEvent)
                 and event.data.res_flowchart_name == "SimpleShop"
                 and event.data.entry_point_name == "SimpleShopRoot_3Choices"]
        self.assertEqual({event.name for event in calls}, NATIVE_CALLS)
        self.assertEqual(next(event for event in calls if event.name == "Event3").data.params.data["Price"], 10)
        before = self.read(FLOW_PATH)
        original_table = self.read(REST)
        with tempfile.TemporaryDirectory(prefix="ootrr-bean-preflight-test-") as directory:
            mod = Path(directory) / "mods/Archipelago/romfs"
            mod.mkdir(parents=True)
            result = prepare_merchant_preflight(self.native, mod, [self.record])
            self.assertEqual(result["merchant_preflight_calls"], 1)
            self.assertFalse((mod / MERCHANT_PATH).exists())
            after = self.codec.decode((mod / FLOW_PATH).read_bytes())
            table = self.codec.decode((mod / REST).read_bytes())
            self.assertGreaterEqual(allocation(table, FLOW_PATH),
                                    allocation(original_table, FLOW_PATH) + len(after) - len(before))
            snapshot = {path.relative_to(mod): path.read_bytes() for path in mod.rglob("*") if path.is_file()}
            self.assertEqual(set(snapshot), {Path(FLOW_PATH), Path(REST)})
            self.assertEqual(prepare_merchant_preflight(self.native, mod, [self.record]), {"merchant_preflight_calls": 0})
            self.assertEqual(snapshot, {path.relative_to(mod): path.read_bytes() for path in mod.rglob("*") if path.is_file()})


if __name__ == "__main__":
    unittest.main()
