"""Optional shop hours preserve native non-time gates and unrelated services."""
import copy
import io
import itertools
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
import ainb
from ainb.blackboard import Blackboard
from ootrr_triforce import shop_hours as hours


def constant(name, value):
    return {"Name": name, "Default Value": value, "Node Index": -1, "Output Index": 0,
            "Flags": ["Uses Default", "Is Output"]}


def link(name, source, default=True):
    return {"Name": name, "Default Value": default, "Node Index": source[0],
            "Output Index": source[1], "Flags": []}


def node(index, name, inputs=None, outputs=("False", "True")):
    return {"Node Type": "UserDefined", "Node Index": index, "Name": name,
            "GUID": str(uuid.UUID(int=index + 1)), "Flags": ["Is Query"], "Queries": [],
            "Attachments": [], "Properties": {}, "XLink Actions": [], "Plugs": {},
            "Parameters": {"Inputs": inputs or {},
                           "Outputs": {"Bool": [{"Name": value, "Is Output": True} for value in outputs]}}}


def gate(index, kind, sources):
    inputs = {"Bool": [{"Name": "BoolMulti", "Default Value": False,
                        "Sources": [{"Node Index": src, "Output Index": out, "Flags": []}
                                    for src, out in sources]}, constant("UpdateOnce", False)]}
    result = node(index, kind, inputs)
    result["Queries"] = [src for src, _ in sources]
    result["Plugs"] = {"Generic": [{"Node Index": sources[0][0], "Name": "BoolMulti"}]}
    return result


def flag(index, name, *, expression=False):
    return node(index, "HoldGameDataGetBoolExpSimple" if expression else "HoldGameDataGetBoolSimple",
                {"String": [constant("GameDataNameBoolExp" if expression else "GameDataNameBool", name)]},
                ("Bool",))


def inverse(index, source):
    result = node(index, "InvBool.module", {"Bool": [link("BoolMulti", source)]}, ("Bool",))
    result["Queries"] = [source[0]]
    return result


def door(index, name, source, *, indoor=None, enabled=None):
    rows = ([enabled] if enabled is not None else []) + [link("EnableOpen", source),
            link("EnableOpenIndoor", indoor) if indoor else constant("EnableOpenIndoor", True),
            constant("PrefabAllCreate", True), constant("PrefabAllDelete", False)]
    result = node(index, name, {"Bool": rows}, ("IsDoorOpened",))
    result["Queries"] = [row["Node Index"] for row in rows if row["Node Index"] >= 0]
    result["Plugs"] = {"Generic": [{"Node Index": row["Node Index"], "Name": row["Name"]}
                                    for row in rows if row["Node Index"] >= 0]}
    return result


def logic_doc(name):
    def time(index):
        return node(index, "HoldWmGetTimeDiv", outputs=("Day", "Night"))
    if name == hours.BOMBCHU:
        nodes = [gate(0, "OperateAND", [(1, 0), (2, 1)]),
                 flag(1, "Get_StoneOfFire_IsCompleted_Exp", expression=True), time(2),
                 door(3, "Obj_Door_ShopBombChu_26fc.logic.module", (0, 1),
                      enabled=link("EnableDo", (4, 1))),
                 gate(4, "OperateAND", [(1, 0), (5, 1)]), gate(5, "OperateOR", [(2, 0), (2, 1)])]
    elif name == hours.MASK:
        nodes = [time(0), door(1, "Obj_Door_ShopMask_b271.logic.module", (3, 1)),
                 gate(2, "OperateAND", [(0, 0), (4, 0)]), gate(3, "OperateOR", [(2, 1), (5, 0)]),
                 flag(4, "Npc_Hylia_Soldier_003_GateOpen"), inverse(5, (4, 0))]
    elif name == "Market_Child_Prefab_971c":
        nodes = [time(0), flag(1, "Market_Item_Bottle_TutorialEvent_Started"),
                 flag(2, "Market_Item_Bottle_TutorialEvent_Cleared"),
                 gate(3, "OperateAND", [(1, 0), (4, 0)]), inverse(4, (2, 0)),
                 gate(5, "OperateOR", [(0, 0), (4, 0)]),
                 door(6, "Obj_Door_ShopMedicine_9089.logic.module", (5, 1), indoor=(3, 0))]
    else:
        specs = [spec for spec in hours.DOORS if spec[0] == name]
        nodes = [time(0)] + [door(index, module, source) for _, index, module, source in specs]
    # Parameters on an unrelated actor must survive every edit verbatim.
    nodes.append(node(len(nodes), "UnrelatedNativeActor", {"String": [constant("OriginalIntro", "NativeQuest")]}))
    return {"Version": 1032, "Filename": name + ".logic.module", "Category": "Logic",
            "Blackboard ID": 123, "Parent Blackboard ID": 0, "Commands": [], "Nodes": nodes,
            "Replacement Table": [], "Modules": [], "Has Section 0x6C": True}


def binary(doc):
    parsed = ainb.AINB.from_dict(doc)
    parsed.blackboard = Blackboard()
    return parsed.to_binary()


def boolean(doc, source, *, day, flags):
    index, output = source
    current = doc["Nodes"][index]
    kind = current["Name"]
    if kind == "HoldWmGetTimeDiv":
        return day if output == 0 else not day
    if kind in ("HoldGameDataGetBoolSimple", "HoldGameDataGetBoolExpSimple"):
        name = "GameDataNameBool" if kind.endswith("BoolSimple") else "GameDataNameBoolExp"
        return flags.get(hours._input(current, name, "String")["Default Value"], False)
    if kind == "InvBool.module":
        return not boolean(doc, hours._source(hours._input(current, "BoolMulti")), day=day, flags=flags)
    if kind in ("OperateAND", "OperateOR"):
        values = [boolean(doc, hours._source(row), day=day, flags=flags)
                  for row in hours._input(current, "BoolMulti")["Sources"]]
        result = all(values) if kind == "OperateAND" else any(values)
        return result if output == 1 else not result
    raise AssertionError(kind)


def flow_snapshot(raw):
    """Every event's operation, parameters and edges, plus actor/entry metadata."""
    from oot_rando.patching.event_patch import _flow
    flow = _flow(raw)
    chart = flow.flowchart
    def target(index):
        return index.v.name if index.v is not None else None
    events = {}
    for event in chart.events:
        data = event.data
        record = {"type": type(data).__name__}
        for attribute in ("params", "actor", "actor_action", "actor_query", "nxt", "cases", "forks", "join",
                          "res_flowchart_name", "entry_point_name", "value"):
            if not hasattr(data, attribute):
                continue
            value = getattr(data, attribute)
            if attribute == "params":
                value = dict(value.data) if value is not None else None
            elif attribute == "actor":
                value = str(value.v.identifier)
            elif attribute in ("actor_action", "actor_query"):
                value = value.v.v
            elif attribute in ("nxt", "join"):
                value = target(value)
            elif attribute == "cases":
                value = {key: target(index) for key, index in value.items()}
            elif attribute == "forks":
                value = [target(index) for index in value]
            record[attribute] = value
        events[event.name] = record
    actors = [(str(actor.identifier), dict(actor.params.data) if actor.params else None,
               [action.v for action in actor.actions], [query.v for query in actor.queries],
               actor.concurrent_clips) for actor in chart.actors]
    entries = [(point.name, target(point.main_event), copy.deepcopy(point.variable_defs))
               for point in chart.entry_points]
    return {"flow": flow.name, "chart": chart.name, "actors": actors, "entries": entries, "events": events}


def flow_fixture(spec):
    from evfl import EventFlow
    from evfl.actor import Actor
    from evfl.common import ActorIdentifier
    from evfl.container import Container
    from evfl.entry_point import EntryPoint
    from evfl.flowchart import Flowchart
    from evfl.util import make_index
    from oot_rando.patching.event_patch import GAMEDATA_ACTOR_PARAMS
    from oot_rando.patching.progressive import FlowEditor
    name, decision, normal_case, normal, closed = spec
    flow = EventFlow()
    flow.name = name
    flow.flowchart = Flowchart()
    flow.flowchart.name = name
    for owner in ("EventWorldManagerController", "GameDataActor"):
        actor = Actor()
        actor.identifier = ActorIdentifier(owner)
        actor.params = Container()
        actor.params.data = dict(GAMEDATA_ACTOR_PARAMS)
        flow.flowchart.actors.append(actor)
    stream = io.BytesIO()
    assert flow.write(stream)
    editor = FlowEditor(stream.getvalue(), name)
    opened = editor.action(normal, "GameDataActor", "EventTriggerNativeShopService", {"NativeCapacityCheck": True})
    shut = editor.action(closed, "GameDataActor", "EventTriggerNativeClosedMessage", {"Text": "Closed"})
    normal, opposite = (opened, shut) if normal_case == 0 else (shut, opened)
    service = editor.switch(decision, "EventWorldManagerController", "EventQueryTimeDivision", None, normal, opposite)
    editor.switch("GreetingTime", "EventWorldManagerController", "EventQueryTimeDivision", None, opened, shut)
    editor.switch("BottleTutorial", "GameDataActor", "EventQueryIsGameDataBool",
                  {"GameDataName": "Market_Item_Bottle_TutorialEvent_Cleared", "Index": -1}, service, shut)
    point = EntryPoint("Talk")
    point.main_event = make_index(service)
    editor.chart.entry_points.append(point)
    return editor.write("shop fixture")[0]


class ShopHoursTests(unittest.TestCase):
    def test_disabled_and_legacy_calls_never_read_or_create_a_directory(self):
        with patch.object(Path, "read_bytes", side_effect=AssertionError("unexpected I/O")), \
                patch.object(Path, "mkdir", side_effect=AssertionError("unexpected I/O")):
            self.assertEqual(hours.prepare_shop_hours("missing", "missing"),
                             {"version": 1, "enabled": False, "files": 0})
            self.assertEqual(hours.prepare_shop_hours("missing", "missing", False)["files"], 0)
        with self.assertRaises(ValueError):
            hours.prepare_shop_hours("missing", "missing", 1)

    def test_all_known_logic_modules_roundtrip_without_changing_unrelated_nodes(self):
        for name in hours.MODULES:
            with self.subTest(module=name):
                raw = binary(logic_doc(name))
                before = ainb.AINB.from_binary(raw).as_dict()
                changed = hours.patch_shop_logic(raw, name)
                after = ainb.AINB.from_binary(changed).as_dict()
                self.assertEqual(before["Nodes"][-1], after["Nodes"][-1])
                self.assertEqual(before["Blackboard ID"], after["Blackboard ID"])
                self.assertEqual(hours.patch_shop_logic(changed, name), changed)
                self.assertNotEqual(changed, raw)

    def test_bombchu_time_is_removed_without_removing_the_quest(self):
        name = hours.BOMBCHU
        raw = binary(logic_doc(name))
        before = ainb.AINB.from_binary(raw).as_dict()
        after = ainb.AINB.from_binary(hours.patch_shop_logic(raw, name)).as_dict()
        expected = copy.deepcopy(before)
        expected["Nodes"][0] = after["Nodes"][0]
        self.assertEqual(expected, after)
        for day, ruby in itertools.product((False, True), repeat=2):
            flags = {"Get_StoneOfFire_IsCompleted_Exp": ruby}
            self.assertEqual(boolean(before, (0, 1), day=day, flags=flags), ruby and not day)
            self.assertEqual(boolean(after, (0, 1), day=day, flags=flags), ruby)
            self.assertEqual(boolean(before, (4, 1), day=day, flags=flags),
                             boolean(after, (4, 1), day=day, flags=flags))

    def test_builder_bombchu_shapes_keep_the_builder_quest_policy(self):
        name = hours.BOMBCHU
        for expression in ("Get_StoneOfFire_IsCompleted_Exp", "Get_StoneOfFire_IsAfter_Ready_Exp"):
            doc = logic_doc(name)
            hours._input(doc["Nodes"][1], "GameDataNameBoolExp", "String")["Default Value"] = expression
            raw = binary(doc)
            result = hours.patch_shop_logic(raw, name)
            self.assertEqual(hours.patch_shop_logic(result, name), result)
            self.assertEqual(hours._input(ainb.AINB.from_binary(result).as_dict()["Nodes"][1],
                                         "GameDataNameBoolExp", "String")["Default Value"], expression)
        doc["Nodes"][3] = door(3, "Obj_Door_ShopBombChu_26fc.logic.module", (2, 1),
                               enabled=constant("EnableDo", True))
        raw = binary(doc)
        result = hours.patch_shop_logic(raw, name)
        after = ainb.AINB.from_binary(result).as_dict()
        self.assertTrue(hours._true(hours._input(after["Nodes"][3], "EnableOpen")))
        self.assertEqual(hours.patch_shop_logic(result, name), result)
        self.assertEqual(doc["Nodes"][0]["Parameters"], after["Nodes"][0]["Parameters"])

    def test_mask_quest_and_potion_tutorial_are_preserved_for_every_state(self):
        for name, gate_id in ((hours.MASK, 2), ("Market_Child_Prefab_971c", 6)):
            raw = binary(logic_doc(name))
            before = ainb.AINB.from_binary(raw).as_dict()
            after = ainb.AINB.from_binary(hours.patch_shop_logic(raw, name)).as_dict()
            expected = copy.deepcopy(before)
            expected["Nodes"][gate_id] = after["Nodes"][gate_id]
            self.assertEqual(expected, after)
            if name == hours.MASK:
                for day, gate_open in itertools.product((False, True), repeat=2):
                    self.assertEqual(boolean(after, (2, 1), day=day,
                                             flags={"Npc_Hylia_Soldier_003_GateOpen": gate_open}), gate_open)
            else:
                for day, started, cleared in itertools.product((False, True), repeat=3):
                    flags = {"Market_Item_Bottle_TutorialEvent_Started": started,
                             "Market_Item_Bottle_TutorialEvent_Cleared": cleared}
                    indoor = hours._source(hours._input(after["Nodes"][6], "EnableOpenIndoor"))
                    self.assertEqual(boolean(after, indoor, day=day, flags=flags), not (started and not cleared))
                    self.assertTrue(hours._true(hours._input(after["Nodes"][6], "EnableOpen")))

    def test_only_the_closed_service_branch_changes_and_all_greetings_stay_native(self):
        for spec in hours.SERVICES:
            with self.subTest(flow=spec[0]):
                raw = flow_fixture(spec)
                changed = hours.patch_shop_service(raw, spec)
                before, after = flow_snapshot(raw), flow_snapshot(changed)
                before["events"][spec[1]]["cases"][1 - spec[2]] = spec[3]
                self.assertEqual(before, after)
                self.assertEqual(hours.patch_shop_service(changed, spec), changed)

    def test_unknown_gate_and_nonshop_service_are_rejected(self):
        doc = logic_doc(hours.BOMBCHU)
        hours._input(doc["Nodes"][1], "GameDataNameBoolExp", "String")["Default Value"] = "OtherQuest"
        with self.assertRaises(ValueError):
            hours.patch_shop_logic(binary(doc), hours.BOMBCHU)
        with self.assertRaises(ValueError):
            hours.patch_shop_logic(binary(doc), "MiniGame_BombchuBowling_e64e")
        with self.assertRaises(ValueError):
            hours.patch_shop_service(flow_fixture(hours.SERVICES[0]),
                                     ("MiniGame_HitTarget_Child", "Event2", 0, "Event3", "Event4"))


@unittest.skipUnless(os.environ.get("OOTRR_ROMFS"), "requires a private native v1.1.1 RomFS")
class NativeShopHoursTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ootrr_triforce.mod_codec import Codec
        from ootrr_triforce import app_runtime
        cls.romfs = Path(os.environ["OOTRR_ROMFS"])
        runtime = os.environ.get("OOTRR_CODEC_RESOURCES")
        cls.override = patch.object(app_runtime, "_resource_override", Path(runtime)) if runtime else \
            patch.object(sys, "argv", [os.environ.get("OOTRR_CODEC_APP", str(ROOT / "dist/Client-OOT-Remake.pyz"))])
        cls.override.start()
        cls.addClassCleanup(cls.override.stop)
        cls.codec = Codec((cls.romfs / "Pack/ZsDic.pack.zs").read_bytes())

    def test_native_modules_have_only_the_intended_semantic_changes(self):
        changed_ids = {name: {index for module, index, _, _ in hours.DOORS if module == name}
                       for name in hours.MODULES}
        changed_ids.update({hours.MASK: {2}, hours.BOMBCHU: {0}})
        for name in hours.MODULES:
            with self.subTest(module=name):
                raw = (self.romfs / hours.module_path(name)).read_bytes()
                result = hours.patch_shop_logic(raw, name)
                before, after = ainb.AINB.from_binary(raw).as_dict(), ainb.AINB.from_binary(result).as_dict()
                expected = copy.deepcopy(before)
                for index in changed_ids[name]:
                    expected["Nodes"][index] = after["Nodes"][index]
                self.assertEqual(expected, after)
                self.assertEqual(hours.patch_shop_logic(result, name), result)

    def test_native_service_flows_preserve_all_other_parameters_and_edges(self):
        for spec in hours.SERVICES:
            with self.subTest(flow=spec[0]):
                raw = self.codec.decode((self.romfs / hours.service_path(spec[0])).read_bytes())
                result = hours.patch_shop_service(raw, spec)
                before, after = flow_snapshot(raw), flow_snapshot(result)
                before["events"][spec[1]]["cases"][1 - spec[2]] = spec[3]
                self.assertEqual(before, after)
                self.assertEqual(hours.patch_shop_service(result, spec), result)

    def test_native_vendor_availability_needs_no_schedule_or_presence_bypass(self):
        from oot_rando.formats import byml_codec
        shops = json.loads((ROOT / "moteur/ootrr-ap/data/shops.json").read_text())["shops"]
        self.assertEqual(len(shops), 8)
        names = {name for shop in shops for name in shop["keepers"]}
        names.add("Npc_Hylia_023_Shop_Child")  # Happy Mask Shop, not a shelf shop.
        for name in sorted(names):
            if name.endswith("_ShortStock"):
                continue  # Native variant inherits the Kokiri keeper's schedule.
            path = "Component/AIScheduleParam/" + name + ".game__component__AIScheduleParam.bgyml"
            doc = byml_codec.load((self.romfs / path).read_bytes())["root"]
            for schedule in [doc["DefaultSchedule"], *doc.get("ConditionalSchedule", [])]:
                rows = schedule["ActionSchedule"]
                self.assertEqual(len(rows), 1, name)
                # The game's all-day schedule, also used by the native Kokiri
                # keeper. No sleeping/absent night action needs replacing.
                self.assertIn(rows[0].get("ActionTimeDivision"), (None, 3710534274), name)
        allowed = {"Meet_DekuTree_IsAfter_Step02_Exp", "Get_StoneOfFire_IsCompleted_Exp",
                   "Npc_Hylia_Soldier_003_GateOpen"}
        seen = set()
        for path in {path for shop in shops for path in shop["bancs"]}:
            doc = byml_codec.load(self.codec.decode((self.romfs / path).read_bytes()))["root"]
            for actor in doc.get("Actors", []):
                if actor.get("Gyaml") in names:
                    seen.add(actor["Gyaml"])
                    presence = actor.get("Presence")
                    if presence is not None:
                        self.assertIn(presence["FlagName"], allowed)
        self.assertEqual(seen, names)

    def test_native_overlay_is_exact_idempotent_and_keeps_other_mod_files(self):
        from oot_rando.game.resource_allocations import allocation
        expected = {hours.module_path(name) for name in hours.MODULES}
        expected.update(hours.service_path(spec[0]) for spec in hours.SERVICES)
        original = {path: (self.romfs / path).read_bytes() for path in expected}
        with tempfile.TemporaryDirectory() as root:
            mod = Path(root) / "Archipelago/romfs"
            mod.mkdir(parents=True)
            marker = mod / "unrelated.bin"
            marker.write_bytes(b"keep existing mod overlay")
            result = hours.prepare_shop_hours(self.romfs, mod, True)
            self.assertEqual(result["files"], len(expected))
            self.assertEqual(result["allocations"], [])
            self.assertEqual({path.relative_to(mod).as_posix() for path in mod.rglob("*") if path.is_file()},
                             expected | {"unrelated.bin"})
            mtimes = {path: path.stat().st_mtime_ns for path in mod.rglob("*") if path.is_file()}
            self.assertEqual(hours.prepare_shop_hours(self.romfs, mod, True)["files"], 0)
            self.assertEqual(mtimes, {path: path.stat().st_mtime_ns for path in mod.rglob("*") if path.is_file()})
            table = self.codec.decode((self.romfs / hours.REST).read_bytes())
            for path in expected:
                raw = (mod / path).read_bytes()
                content = self.codec.decode(raw) if path.endswith(".zs") else raw
                self.assertGreater(allocation(table, path), len(content))
                self.assertEqual((self.romfs / path).read_bytes(), original[path])
            self.assertEqual(marker.read_bytes(), b"keep existing mod overlay")

    def test_unknown_late_resource_fails_before_creating_any_overlay_file(self):
        with tempfile.TemporaryDirectory() as root:
            mod = Path(root) / "Archipelago/romfs"
            path = hours.service_path(hours.SERVICES[-1][0])
            malformed = mod / path
            malformed.parent.mkdir(parents=True)
            malformed.write_bytes(b"unknown future event layout")
            with self.assertRaises((ValueError, EOFError, AssertionError)):
                hours.prepare_shop_hours(self.romfs, mod, True)
            self.assertEqual([file.relative_to(mod).as_posix() for file in mod.rglob("*") if file.is_file()], [path])
            self.assertEqual(malformed.read_bytes(), b"unknown future event layout")


if __name__ == "__main__":
    unittest.main()
