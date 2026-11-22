"""Membership never frees prisoners; later Spirit progress never loses them."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
import ainb
from ainb.blackboard import Blackboard
from oot_rando.formats import byml_codec as byml
from ootrr_triforce import fortress_fixes as fortress, quest_fixes as quest


def binary(doc):
    obj = ainb.AINB.from_dict(doc)
    obj.blackboard = Blackboard()
    return obj.to_binary()


def logic_fixture(path):
    step = fortress._node(0, "HoldChallengeCurrentStepCheckOrder", "00000000-0000-4000-8000-000000000001",
        {"String": [fortress._constant("ChallengeName", "Work/Challenge/SageOfSpirit.game__challenge__Challenge.gyml"),
                    fortress._constant("ChallengeStepName", "Step01")]},
        [{"Name": name, "Is Output": True} for name in ("IsAfter", "IsBefore", "IsEqual")])
    actor = fortress._node(1, "ActorLogicNpc", "00000000-0000-4000-8000-000000000002",
        {"Bool": [{"Name": "Friendly", "Default Value": False, "Node Index": 0, "Output Index": 0, "Flags": []},
                  {"Name": "Jailed", "Default Value": False, "Node Index": 0, "Output Index": 2, "Flags": []}]},
        [{"Name": "Alive", "Is Output": False}], [0],
        [{"Node Index": 0, "Name": name} for name in ("Friendly", "Jailed")])
    doc = {"Version": 1032, "Filename": Path(path).name.removesuffix(".ainb"), "Category": "Logic",
           "Blackboard ID": 123, "Parent Blackboard ID": 0, "Commands": [], "Nodes": [step, actor],
           "Replacement Table": [], "Modules": [], "Has Section 0x6C": True}
    return binary(doc)


def boolean(doc, node_id, output, flags):
    node = doc["Nodes"][node_id]
    values = fortress._strings(node)
    if node["Name"] == "HoldGameDataGetBoolSimple":
        return bool(flags.get(values["GameDataNameBool"], False))
    if node["Name"] == "HoldGameDataGetBoolExpSimple":
        return bool(flags.get(values["GameDataNameBoolExp"], False))
    if node["Name"] in ("OperateOR", "OperateAND"):
        inputs = [value for name, value in fortress.bool_sources(node) if name == "BoolMulti"]
        incoming = [boolean(doc, value["Node Index"], value["Output Index"], flags) for value in inputs]
        result = any(incoming) if node["Name"] == "OperateOR" else all(incoming)
        return result if output == 1 else not result
    raise AssertionError("unexpected logic query " + node["Name"])


def schedule_fixture(action, conditions=None):
    doc = {"endian": "<", "version": 7, "root": {"DefaultSchedule": {"Action": action}}}
    if conditions is not None:
        doc["root"]["ConditionalSchedule"] = conditions
    return byml.dump(doc)


class FortressLogicTests(unittest.TestCase):
    def test_clearance_and_rescue_are_independent_when_card_arrives_first(self):
        card_path, rescue_path = fortress.CARD_MODULES[0], fortress.RESCUE_MODULES[0]
        card = ainb.AINB.from_binary(fortress.patch_fortress_logic(logic_fixture(card_path), card_path)).as_dict()
        rescue = ainb.AINB.from_binary(fortress.patch_fortress_logic(logic_fixture(rescue_path), rescue_path)).as_dict()
        flags = {fortress.CLEARED: True, fortress.RESCUED: False}
        friendly = next(value for name, value in fortress.bool_sources(card["Nodes"][1]) if name == "Friendly")
        jailed = next(value for name, value in fortress.bool_sources(rescue["Nodes"][1]) if name == "Jailed")
        self.assertTrue(boolean(card, friendly["Node Index"], friendly["Output Index"], flags))
        self.assertTrue(boolean(rescue, jailed["Node Index"], jailed["Output Index"], flags))
        flags[fortress.RESCUED] = True
        self.assertFalse(boolean(rescue, jailed["Node Index"], jailed["Output Index"], flags))

    def test_no_step_input_remains_and_unrelated_node_parameters_stay_exact(self):
        path = fortress.CARD_MODULES[0]
        original = logic_fixture(path)
        before = ainb.AINB.from_binary(original).as_dict()
        raw = fortress.patch_fortress_logic(original, path)
        after = ainb.AINB.from_binary(raw).as_dict()
        self.assertEqual(after["Nodes"][0], before["Nodes"][0])
        self.assertEqual(after["Blackboard ID"], before["Blackboard ID"])
        steps = fortress.step_nodes(after)
        self.assertFalse(any(value.get("Node Index") in steps for node in after["Nodes"]
                             for _, value in fortress.bool_sources(node)))
        self.assertEqual(fortress.patch_fortress_logic(raw, path), raw)

    def test_schedule_keeps_prisoner_until_rescue_and_preserves_fast_fortress(self):
        own = schedule_fixture("Free")
        jail = schedule_fixture("Jailed", [{"ConditionFlag": "IndividualSaved", "Action": "AlreadyFreed"}])
        raw = fortress.patch_carpenter_schedule(own, jail)
        doc = byml.load(raw)["root"]
        def chosen(flags):
            return next((row["Action"] for row in doc["ConditionalSchedule"]
                         if flags.get(row["ConditionFlag"], False)), doc["DefaultSchedule"]["Action"])
        self.assertEqual(chosen({fortress.CARD: True}), "Jailed")
        self.assertEqual(chosen({"IndividualSaved": True}), "AlreadyFreed")
        self.assertEqual(chosen({fortress.RESCUED: True}), "Free")
        self.assertEqual(fortress.patch_carpenter_schedule(raw, jail), raw)
        with self.assertRaises(ValueError):
            fortress.patch_carpenter_schedule(schedule_fixture("Free", [{"ConditionFlag": "Other", "Action": "Other"}]), jail)


@unittest.skipUnless(os.environ.get("OOTRR_ROMFS"), "requires a private native RomFS")
class NativeFortressTests(unittest.TestCase):
    def test_native_schedules_preserve_both_full_states_and_individual_rescues(self):
        from unittest.mock import patch
        from ootrr_triforce.mod_codec import Codec
        from oot_rando.formats.inspect_resources import sarc
        romfs = Path(os.environ["OOTRR_ROMFS"])
        codec_app = os.environ.get("OOTRR_CODEC_APP", str(ROOT / "dist/Client-OOT-Remake.pyz"))
        with patch.object(sys, "argv", [codec_app]):
            codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
        packed = sarc(codec.decode((romfs / fortress.PACK).read_bytes()))
        for number in fortress.CARPENTERS:
            with self.subTest(carpenter=number):
                own_raw = (romfs / fortress.own_schedule(number)).read_bytes()
                jail_raw = packed[fortress.jail_schedule(number)]
                own, jail = byml.load(own_raw)["root"], byml.load(jail_raw)["root"]
                result = fortress.patch_carpenter_schedule(own_raw, jail_raw)
                merged = byml.load(result)["root"]
                free = dict(merged["ConditionalSchedule"][0])
                self.assertEqual(free.pop("ConditionFlag"), fortress.RESCUED)
                self.assertEqual(free, own["DefaultSchedule"])
                self.assertEqual(merged["DefaultSchedule"], jail["DefaultSchedule"])
                self.assertEqual(merged["ConditionalSchedule"][1:], jail["ConditionalSchedule"])
                self.assertEqual(fortress.patch_carpenter_schedule(result, jail_raw), result)

    def test_fortress_refuses_unpaired_native_story_before_writing_files(self):
        from unittest.mock import patch
        romfs = Path(os.environ["OOTRR_ROMFS"])
        codec_app = os.environ.get("OOTRR_CODEC_APP", str(ROOT / "dist/Client-OOT-Remake.pyz"))
        with tempfile.TemporaryDirectory() as root, patch.object(sys, "argv", [codec_app]):
            mod = Path(root) / "Archipelago/romfs"
            mod.mkdir(parents=True)
            with self.assertRaises(ValueError):
                fortress.prepare_fortress_fixes(romfs, mod)
            self.assertEqual(list(mod.rglob("*")), [])

    def test_all_native_modules_roundtrip_and_requiem_cannot_rewind_late_spirit(self):
        romfs = Path(os.environ["OOTRR_ROMFS"])
        for path in fortress.CARD_MODULES + fortress.RESCUE_MODULES:
            with self.subTest(path=path):
                before = (romfs / path).read_bytes()
                raw = fortress.patch_fortress_logic(before, path)
                doc = ainb.AINB.from_binary(raw).as_dict()
                step_ids = fortress.step_nodes(doc)
                self.assertFalse(any(value.get("Node Index") in step_ids for node in doc["Nodes"]
                                     for _, value in fortress.bool_sources(node)))
                self.assertEqual(fortress.patch_fortress_logic(raw, path), raw)
        raw = fortress.patch_requiem_logic((romfs / fortress.COLOSSUS).read_bytes())
        doc = ainb.AINB.from_binary(raw).as_dict()
        target = next(node for node in doc["Nodes"] if node["Name"] == "TriggerChallengeSetStep")
        drive = next(value for name, value in fortress.bool_sources(target) if name == "IsDrive")
        gate = doc["Nodes"][drive["Node Index"]]
        terms = [value for name, value in fortress.bool_sources(gate) if name == "BoolMulti"]
        # Keep the original event-finished output as the second condition.
        self.assertEqual(doc["Nodes"][terms[1]["Node Index"]]["Name"], "ActorLogicEventRequestActor")
        self.assertEqual(terms[1]["Output Index"], 4)
        inverse = terms[0]
        for late in (False, True):
            allowed = boolean(doc, inverse["Node Index"], inverse["Output Index"], {fortress.AFTER_REQUIEM: late})
            self.assertEqual(allowed, not late)
        self.assertEqual(fortress.patch_requiem_logic(raw), raw)

    def test_private_story_comparison_survives_card_clearance_and_saved_metadata_is_unchanged(self):
        from unittest.mock import patch
        from ootrr_triforce.mod_codec import Codec
        from oot_rando.patching.soul_adapter import murmur3
        romfs = Path(os.environ["OOTRR_ROMFS"])
        codec_app = os.environ.get("OOTRR_CODEC_APP", str(ROOT / "dist/Client-OOT-Remake.pyz"))
        with patch.object(sys, "argv", [codec_app]):
            codec = Codec((romfs / "Pack/ZsDic.pack.zs").read_bytes())
        original = codec.decode((romfs / fortress.DATA).read_bytes())
        prepared = quest.preserve_story_comparison(original, original)
        changed = fortress.patch_clearance_flag(prepared)
        before, after = byml.load(original), byml.load(changed)
        self.assertEqual(before["root"]["MetaData"], after["root"]["MetaData"])
        rows = {int(row["Hash"]): row for row in after["root"]["Data"]["BoolExp"]}
        source = next(row for row in before["root"]["Data"]["BoolExp"] if int(row["Hash"]) == murmur3(fortress.CLEARED))
        self.assertEqual(rows[murmur3(quest.STORY_AFTER_STEP01)]["Values"], source["Values"])
        self.assertEqual(rows[murmur3(fortress.CLEARED)]["Values"], [[0, murmur3(fortress.CARD)]])
        self.assertEqual(rows[murmur3(quest.STORY_AFTER_STEP01)]["SaveFileIndex"], -1)
        self.assertEqual(quest.preserve_story_comparison(changed, original), changed)
        self.assertEqual(fortress.patch_clearance_flag(changed), changed)


if __name__ == "__main__":
    unittest.main()
