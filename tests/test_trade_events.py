"""Adult trade NPC routes preserve exact stock, independent checks and native UI."""
import copy
import io
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from evfl import EventFlow
from evfl.actor import Actor
from evfl.common import ActorIdentifier
from evfl.entry_point import EntryPoint
from evfl.event import ActionEvent, SubFlowEvent, SwitchEvent
from evfl.flowchart import Flowchart
from evfl.util import make_index
from oot_rando.patching.event_patch import _flow
from oot_rando.patching.event_info import reachable
from oot_rando.patching.progressive import FlowEditor, link
from ootrr_triforce import trade_events as trade
from ootrr_triforce.trade_catalog import TALON_AWAKE, TRADE_CHECKS, event_name


def fixture(name):
    flow = EventFlow()
    flow.name = name
    flow.flowchart = Flowchart()
    flow.flowchart.name = name
    for identifier in (name, "ChallengeSystemActor"):
        actor = Actor()
        actor.identifier = ActorIdentifier(identifier)
        flow.flowchart.actors.append(actor)
    stream = io.BytesIO()
    assert flow.write(stream)
    editor = FlowEditor(stream.getvalue(), name)
    talk = editor.action("NativeTalk", name, "EventTalk",
                         {"MessageId": "EventFlowMsg/" + name + ":Native", "ChoiceNumber": 0,
                          "IsWaitEnd": True, "IsCloseDialog": True})
    old = talk
    for index, event in enumerate(sorted(trade.LEGACY_REWARDS[name])):
        gift = editor.subflow(event, "NpcCommon", "NpcCommon_HandOver_NpcToPlayer_NoDisplay",
                              {"ReveiveItem": "Item_PocketEgg"})
        link(gift, old)
        old = gift
    remove = editor.action("NativeRemove", "PouchSystemActor", "EventTriggerAddOrRemovePouchContent",
                           {"Actor": "Item_PocketCucco", "Num": -1})
    link(remove, old)
    progress = editor.action("NativeStep", "ChallengeSystemActor", "EventExecuteProgressChallengeStep",
                             {"ChallengeName": trade.SHARED, "StepName": "Complete"})
    link(progress, remove)
    for name in ("Talk", "ShowRequiredItem"):
        point = EntryPoint(name)
        point.main_event = make_index(progress)
        editor.chart.entry_points.append(point)
    return editor.write("NPC fixture")[0]


class Run:
    """Execute the real NPC graph; the guarded reward entry is its own test unit."""
    def __init__(self, raw, rows):
        self.chart = _flow(raw).flowchart
        self.rows = {event_name(row["id"]): row for row in rows}
        self.stock, self.flags, self.calls, self.trace = {}, {}, [], []
        self.empty_bottle = True
        self.is_get = set()  # Deliberately irrelevant: a consumed item was once obtained.

    def run(self, entry="Talk"):
        node = next(point.main_event.v for point in self.chart.entry_points if point.name == entry)
        steps = 0
        while node is not None:
            steps += 1
            assert steps < 1000
            data = node.data
            params = data.params.data if getattr(data, "params", None) else {}
            if isinstance(data, ActionEvent):
                command = data.actor_action.v.v
                self.trace.append((command, dict(params)))
                assert command not in {"EventTriggerAddOrRemovePouchContent", "EventExecuteProgressChallengeStep"}, command
                if command == "EventTriggerSetGameDataBool":
                    self.flags[params["GameDataName"]] = params["Value"]
                node = data.nxt.v
            elif isinstance(data, SwitchEvent):
                command = data.actor_query.v.v
                if command == "EventQueryIsGameDataBool":
                    result = self.flags.get(params["GameDataName"], False)
                elif command == "EventQueryIsExistInPouch":
                    result = self.stock.get(params["Actor"], 0) >= params["Num"]
                elif command == "EventQueryIsAnyBottleEmpty":
                    result = self.empty_bottle
                else:
                    raise AssertionError(command)
                node = data.cases[0 if result else 1].v
            elif isinstance(data, SubFlowEvent):
                self.trace.append(("call:" + data.entry_point_name, dict(params)))
                if data.res_flowchart_name == trade.GET:
                    row = self.rows[data.entry_point_name]
                    assert not self.flags.get(row["flag_name"])
                    required = row["required_actor"]
                    if required:
                        assert self.stock.get(required, 0) >= 1
                        self.stock[required] -= 1
                    self.flags[row["flag_name"]] = True
                    self.calls.append(row["name"])
                else:
                    assert data.res_flowchart_name == trade.SHARED
                node = data.nxt.v
            else:
                raise AssertionError(type(data))
        return self


def rows_for(name, *, bottle=False):
    return [dict(row, name=label, needs_bottle=bottle) for label, row in TRADE_CHECKS.items() if row["flow"] == name]


class NativeTradeRouteTests(unittest.TestCase):
    def setup_run(self, name, *, bottle=False):
        rows = rows_for(name, bottle=bottle)
        return Run(trade.patch_trade_flow(fixture(name), rows, name), rows), rows

    def test_no_eligible_item_never_grants_or_removes_a_quest_item(self):
        for name in sorted({row["flow"] for row in TRADE_CHECKS.values()}):
            with self.subTest(npc=name):
                run, rows = self.setup_run(name)
                for row in rows:
                    if row["required_actor"] is None:
                        run.flags[row["flag_name"]] = True
                run.run()
                self.assertFalse(run.calls)
                if name in trade.NEUTRAL:
                    self.assertEqual([args["MessageId"] for cmd,args in run.trace if cmd == "EventTalk"],
                                     ["EventFlowMsg/" + name + ":" + trade.NOTHING])

    def test_every_trade_is_independent_and_consumes_only_its_owned_item(self):
        for label, meta in TRADE_CHECKS.items():
            for entry in ("Talk", "ShowRequiredItem"):
                with self.subTest(check=label, entry=entry):
                    run, rows = self.setup_run(meta["flow"])
                    for row in rows:
                        if row["name"] != label:
                            run.flags[row["flag_name"]] = True
                    untouched = "Item_Prescription" if meta["required_actor"] != "Item_Prescription" else "Item_CojiroCucco"
                    run.stock[untouched] = 1
                    if meta["required_actor"]:
                        run.stock[meta["required_actor"]] = 1
                    run.flags[TALON_AWAKE] = True
                    run.run(entry)
                    self.assertEqual(run.calls, [label])
                    self.assertEqual(run.stock[untouched], 1)
                    if meta["required_actor"]:
                        self.assertEqual(run.stock[meta["required_actor"]], 0)
                        shows = [p for cmd,p in run.trace if cmd == "call:ShowItemSuccess_NoCamera_SwordBigGoron"]
                        self.assertEqual(shows[0]["AssignableItem"], trade.ASSIGNABLE[meta["required_actor"]])
                    run.run(entry)
                    self.assertEqual(run.calls, [label])

    def test_talon_must_be_awake_but_other_trade_items_can_arrive_first(self):
        run, rows = self.setup_run("Npc_Hylia_049_Adult")
        run.flags[rows[0]["flag_name"]] = True
        run.stock["Item_PocketCucco"] = 1
        run.run()
        self.assertFalse(run.calls)
        self.assertEqual(run.stock["Item_PocketCucco"], 1)
        run.flags[TALON_AWAKE] = True
        run.run()
        self.assertEqual(run.calls, ["Kak Anju Trade Pocket Cucco"])
        final, rows = self.setup_run("Npc_Goron_Biggoron_Adult")
        final.stock["Item_ClaimCheck"] = 1
        final.run()
        self.assertEqual(final.calls, ["DMT Biggoron"])

    def test_obtained_flag_without_stock_does_not_authorize_another_trade(self):
        run, rows = self.setup_run("Npc_Hylia_017_Adult")
        run.is_get.add("Item_CojiroCucco")
        run.stock["Item_CojiroCucco"] = 0
        run.run()
        self.assertFalse(run.calls)

    def test_full_bottle_keeps_the_required_item_and_explains_the_block(self):
        run, rows = self.setup_run("Npc_Hylia_017_Adult", bottle=True)
        run.stock["Item_CojiroCucco"] = 1
        run.empty_bottle = False
        run.run()
        self.assertFalse(run.calls)
        self.assertEqual(run.stock["Item_CojiroCucco"], 1)
        self.assertFalse(run.flags.get(rows[0]["flag_name"]))
        self.assertEqual([p["MessageId"] for cmd,p in run.trace if cmd == "EventTalk"],
                         ["EventFlowMsg/Npc_Hylia_017_Adult:" + trade.NEEDS_BOTTLE])
        run.empty_bottle = True
        run.run()
        self.assertEqual(run.calls, [rows[0]["name"]])

    def test_all_new_local_calls_are_preloaded_and_repatch_is_rejected(self):
        rows = rows_for("Npc_Goron_Biggoron_Adult")
        raw = trade.patch_trade_flow(fixture("Npc_Goron_Biggoron_Adult"), rows, "Npc_Goron_Biggoron_Adult")
        chart = _flow(raw).flowchart
        for point in chart.entry_points:
            for node in reachable(point.main_event.v):
                if node.name.startswith(trade.PREFIX) and isinstance(node.data, SubFlowEvent):
                    self.assertIn(chart.events.index(node), point._sub_flow_event_indices)
        with self.assertRaises(ValueError):
            trade.patch_trade_flow(raw, rows, "Npc_Goron_Biggoron_Adult")

    def test_native_show_item_parameters_remain_intact_and_all_routes_are_guarded(self):
        from oot_rando.formats import byml_codec as by
        from oot_rando.patching.soul_adapter import murmur3
        name = "Npc_Kokiri_Fado_Adult"
        own = {"ShowItemType": by.U32(murmur3("OddPowder")),
               "EventName": "Work/Event/EventSetting/Fado_Show.engine__event__EventSettingParam.gyml",
               "UseBeforehandLoadCondition": True,
               "BeforehandLoadGameData": "OldQuestStep", "BeforehandLoadGameDataHash": by.U32(123)}
        unrelated = {"ShowItemType": by.U32(12345), "EventName": own["EventName"]}
        before = {"root": {"ShowItemReplaceEventParamList": [own, unrelated]}, "endian": "<", "version": 7}
        raw = by.dump(before)
        settings = {"Fado_Show": {"FlowchartFileName": "Work/Event/EventFlow/" + name + ".evfc",
                                  "EntryPointName": "ShowRequiredItem"}}
        patched = trade.patch_trade_flow(fixture(name), rows_for(name), name)
        self.assertEqual(trade._validate_show_item_routes(raw, name, settings, patched), 2)
        self.assertEqual(by.load(raw), before)
        bad_settings = copy.deepcopy(settings)
        bad_settings["Fado_Show"]["FlowchartFileName"] = "Work/Event/EventFlow/Unrelated.evfc"
        with self.assertRaises(ValueError):
            trade._validate_show_item_routes(raw, name, bad_settings, patched)
        with self.assertRaises(ValueError):
            trade._validate_show_item_routes(raw, name, settings, fixture(name))
        missing = copy.deepcopy(before)
        missing["root"]["ShowItemReplaceEventParamList"] = [unrelated]
        with self.assertRaises(ValueError):
            trade._validate_show_item_routes(by.dump(missing), name, settings, patched)

    def test_neutral_and_empty_bottle_messages_follow_the_archive_language(self):
        from oot_rando.formats import byml_codec as by, msbt
        from oot_rando.formats.inspect_resources import sarc
        import struct
        header = bytearray(32)
        header[:10] = b"MsgStdBn\xff\xfe"
        struct.pack_into("<H", header, 14, 2)
        table = msbt.Msbt(header, [(b"LBL1", struct.pack("<III", 1, 0, 12)), (b"TXT2", b"")], {}, [], 1)
        table.add("Native", "Unchanged native text")
        message = msbt.dump(table)
        files = {"EventFlowMsg/" + name + ".msbt": message for name in {row["flow"] for row in TRADE_CHECKS.values()}}
        files["Unrelated.bin"] = b"unchanged"
        frames = {"Mals/" + code + ".Product.110.sarc.zs": by.build_sarc(files)
                  for code in ("USen", "EUfr", "JPja")}
        class Identity:
            def decode(self, raw): return raw
        for path, content in trade._messages(frames, frames.__getitem__, Identity()):
            members = sarc(content)
            self.assertEqual(members["Unrelated.bin"], b"unchanged")
            for name in {row["flow"] for row in TRADE_CHECKS.values()}:
                text = msbt.load(members["EventFlowMsg/" + name + ".msbt"])
                self.assertEqual(text.get("Native"), table.get("Native"))
                if "EUfr" in path:
                    self.assertIn("bouteille vide".encode(), text.get(trade.NEEDS_BOTTLE))
                    self.assertIn("échanger".encode(), text.get(trade.NOTHING))
                else:
                    self.assertIn(b"empty bottle", text.get(trade.NEEDS_BOTTLE))
                    self.assertIn(b"trade here", text.get(trade.NOTHING))

    def test_hidden_owned_cucco_wakes_talon_through_his_native_entry_without_consumption(self):
        flow = EventFlow()
        flow.name = trade.TALON_FLOW
        flow.flowchart = Flowchart()
        flow.flowchart.name = trade.TALON_FLOW
        npc = Actor()
        npc.identifier = ActorIdentifier(trade.TALON_FLOW)
        flow.flowchart.actors.append(npc)
        stream = io.BytesIO()
        assert flow.write(stream)
        editor = FlowEditor(stream.getvalue(), trade.TALON_FLOW)
        fallback = editor.action("NativeTalk", trade.TALON_FLOW, "EventTalk", {"MessageId": "Native"})
        wake = editor.action("NativeWake", "GameDataActor", "EventTriggerSetGameDataBool",
                             {"GameDataName": TALON_AWAKE, "Index": -1, "Value": True})
        show = editor.subflow("NativeShow", trade.SHARED, "ShowItemSuccess_NoCamera_SwordBigGoron",
                              {"AssignableItem": 35})
        link(show, wake)
        for name, root in (("Talk", fallback), ("Npc_Hylia_Talon_Adult_ShowPocketCucco", show)):
            point = EntryPoint(name)
            point.main_event = make_index(root)
            editor.chart.entry_points.append(point)
        raw = trade.patch_talon_flow(editor.write("Talon native fixture")[0])
        run = Run(raw, [])
        run.stock.update(Item_PocketCucco=1, Item_Prescription=1)
        run.run()
        self.assertTrue(run.flags[TALON_AWAKE])
        self.assertEqual(run.stock, {"Item_PocketCucco": 1, "Item_Prescription": 1})
        self.assertFalse(run.calls)
        before = list(run.trace)
        run.run()
        self.assertEqual(sum(cmd.startswith("call:") for cmd,_ in run.trace),
                         sum(cmd.startswith("call:") for cmd,_ in before))
        empty = Run(raw, [])
        empty.is_get.add("Item_PocketCucco")
        empty.run()
        self.assertFalse(empty.flags.get(TALON_AWAKE))
        self.assertFalse(any(cmd.startswith("call:") for cmd,_ in empty.trace))
        for point in run.chart.entry_points:
            for node in reachable(point.main_event.v):
                if isinstance(node.data, SubFlowEvent):
                    self.assertIn(run.chart.events.index(node), point._sub_flow_event_indices)

    def test_fado_and_her_schedule_anchor_move_together_without_other_scene_changes(self):
        from oot_rando.formats import byml_codec as by
        presence = {"FlagName": trade.PRESENCE, "IsCheckLazy": False, "IsNegation": False}
        fado = dict(Hash=by.U64(trade.FADO), Gyaml="Npc_Kokiri_Fado_Adult", Translate=[-32.5,100.5,-4.0],
                    Presence=presence, Links=[dict(Dst=by.U64(trade.FADO_ANCHOR), Gyaml="Reference", Name="Reference", Src=by.U64(trade.FADO))])
        anchor = dict(Hash=by.U64(trade.FADO_ANCHOR), Gyaml="AnchorAction1", Translate=list(fado["Translate"]))
        grog = dict(Hash=by.U64(trade.GROG), Gyaml="Npc_Hylia_017_Adult", Translate=[-32.8,100.5,-3.8],
                    Presence=dict(presence,IsNegation=True))
        other = dict(Hash=by.U64(1234), Gyaml="UnrelatedActor", Translate=[1.0,2.0,3.0])
        group = dict(Hash=by.U64(trade.LOST_GROUP),Logic=trade.LOST_MODULE,
                     References=[dict(Id="Npc_Kokiri_Fado_Adult_7409",Reference=by.U64(trade.FADO)),
                                 dict(Id="Npc_Hylia_017_Adult_7d7e",Reference=by.U64(trade.GROG))])
        doc = dict(root=dict(Actors=[grog,fado,anchor,other],AiGroups=[group]),endian="<",version=7)
        result = by.load(trade.patch_trade_scene(by.dump(doc)))["root"]["Actors"]
        self.assertEqual(result[1]["Translate"],[-30.5,100.5,-4.0])
        self.assertEqual(result[2]["Translate"],result[1]["Translate"])
        self.assertEqual(result[3],other)
        self.assertNotIn("Presence",result[0])
        self.assertNotIn("Presence",result[1])
        broken = copy.deepcopy(doc)
        broken["root"]["Actors"][1]["Links"][0]["Dst"] = by.U64(1234)
        with self.assertRaises(ValueError):trade.patch_trade_scene(by.dump(broken))


@unittest.skipUnless(os.environ.get("OOTRR_ROMFS"), "requires a private native RomFS")
class RealTradeLayoutTests(unittest.TestCase):
    def test_native_npc_timer_and_spawn_layouts_are_supported(self):
        from ootrr_triforce.mod_codec import Codec
        from oot_rando.patching.event_info import entry_calls, entry_names
        from unittest.mock import patch
        romfs = Path(os.environ["OOTRR_ROMFS"])
        with patch.object(sys, "argv", [str(ROOT / "dist/Client-OOT-Remake.pyz")]):
            codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
        def raw(name):
            return codec.decode((romfs / (trade.FLOW_ROOT + name + ".bfevfl.zs")).read_bytes())
        from oot_rando.formats import byml_codec
        from oot_rando.formats.inspect_resources import sarc
        settings = {row["__RowId"]: row for row in byml_codec.load(codec.decode((romfs / trade.SETTINGS).read_bytes()))["root"]}
        routes = 0
        for name in sorted({row["flow"] for row in TRADE_CHECKS.values()}):
            before = raw(name)
            result = trade.patch_trade_flow(before, rows_for(name), name)
            self.assertNotEqual(before, result)
            members = sarc(codec.decode((romfs / ("Pack/Actor/" + name + ".pack.zs")).read_bytes()))
            member = "GameParameter/ShowItemReplaceEventParam/" + name + ".game__event__ShowItemReplaceEventParam.bgyml"
            routes += trade._validate_show_item_routes(members[member], name, settings, result)
            for entry in entry_names(result):
                if "Near" in entry:
                    self.assertFalse(any(flow == trade.GET and target.startswith("OOTRR_APTradeReward_")
                                         for flow, target in entry_calls(result, entry)), (name, entry))
        timers = _flow(trade.patch_trade_timers(raw(trade.SHARED))).flowchart
        for point in timers.entry_points:
            if point.name.startswith(("BigGoronTimer_Step", "SubEvent_TimerCheck")):
                self.assertTrue(point.main_event.v.name.startswith(trade.PREFIX))
        movie = _flow(trade.patch_trade_cutscene(raw("Dm_DeathMtTrail_0050"))).flowchart
        self.assertTrue(all(point.main_event.v.name.startswith(trade.PREFIX) for point in movie.entry_points))
        talon = trade.patch_talon_flow(raw(trade.TALON_FLOW))
        self.assertNotEqual(talon, raw(trade.TALON_FLOW))
        members = sarc(codec.decode((romfs / ("Pack/Actor/" + trade.TALON_FLOW + ".pack.zs")).read_bytes()))
        member = "GameParameter/ShowItemReplaceEventParam/" + trade.TALON_FLOW + ".game__event__ShowItemReplaceEventParam.bgyml"
        routes += trade._validate_show_item_routes(members[member], trade.TALON_FLOW, settings, talon)
        self.assertEqual(routes, 24)
        before = codec.decode((romfs / trade.LOST_WOOD).read_bytes())
        after = trade.patch_trade_scene(before)
        old = byml_codec.load(before)["root"]
        new = byml_codec.load(after)["root"]
        self.assertEqual({key:value for key,value in old.items() if key != "Actors"},
                         {key:value for key,value in new.items() if key != "Actors"})
        for original, patched in zip(old["Actors"], new["Actors"]):
            if original.get("Hash") == trade.FADO_ANCHOR:
                expected = copy.deepcopy(original)
                expected["Translate"][0] += 2.0
                self.assertEqual(patched,expected)
            elif original.get("Hash") not in {trade.GROG, trade.FADO}:
                self.assertEqual(original, patched)
            else:
                self.assertNotIn("Presence", patched)
                expected = copy.deepcopy(original)
                del expected["Presence"]
                if original["Hash"] == trade.FADO:expected["Translate"][0] += 2.0
                self.assertEqual(patched,expected)

    def test_lost_woods_only_two_npc_create_inputs_ignore_the_linear_quest(self):
        import ainb
        romfs = Path(os.environ["OOTRR_ROMFS"])
        raw = (romfs / trade.LOST_LOGIC).read_bytes()
        before = ainb.AINB.from_binary(raw).as_dict()
        result = trade.patch_trade_logic(raw)
        after = ainb.AINB.from_binary(result).as_dict()
        self.assertEqual({key:value for key,value in before.items() if key != "Nodes"},
                         {key:value for key,value in after.items() if key != "Nodes"})
        self.assertEqual(len(before["Nodes"]),22)
        for index,(old,new) in enumerate(zip(before["Nodes"],after["Nodes"])):
            if index not in (0,4):
                self.assertEqual(old,new)
                continue
            expected = copy.deepcopy(old)
            create = next(row for row in expected["Parameters"]["Inputs"]["Bool"] if row["Name"]=="Logic_Create")
            create.update({"Node Index":-1,"Output Index":0,"Flags":["Uses Default","Is Output"]})
            expected["Queries"],expected["Plugs"] = [],{}
            self.assertEqual(new,expected)
            self.assertTrue(create["Default Value"])
        with self.assertRaises(ValueError):trade.patch_trade_logic(result)


if __name__ == "__main__":
    unittest.main()
