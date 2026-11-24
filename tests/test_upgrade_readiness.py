"""Native receipt readiness rejects tunnels, fishing, pause and unknown actions."""
import copy
import itertools
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))
from ootrr_triforce import upgrade_readiness as gate
from ootrr_full.formats import byml_codec as codec
from ootrr_full.patching.soul_adapter import murmur3


def walk_ai(nodes, *, verb, fishing=False, paused=False, loading=False, minigame=False):
    """Interpret selector edges, independently of the publisher's builder."""
    values = {"QueryBSAGetActionVerb": verb,
              "QueryNaviIsWaitPlayerStateDrawnFishingRod": fishing,
              "QueryPlayerIsEquipMiniGameItem": minigame}
    current = 0
    for _ in range(20):
        node = nodes[current]
        if node["Name"] == "OneShotSetNonStructGameDataBool":
            return node["Parameters"]["Inputs"]["Bool"][0]["Default Value"]
        query = nodes[node["Queries"][0]]
        if query["Name"] == "QueryGetNonStructGameDataBool":
            name = query["Parameters"]["Inputs"]["String"][0]["Default Value"]
            value = {gate.PAUSE: paused, gate.LOADING: loading}[name]
        else:
            value = values[query["Name"]]
        children = node["Plugs"]["Child"]
        if node["Node Type"] == "Element_S32Selector":
            chosen = next((p for p in children if p.get("Condition") == value),
                          next(p for p in children if p.get("Is Default")))
        else:
            chosen = next(p for p in children if p["Name"] == ("True" if value else "False"))
        current = chosen["Node Index"]
    raise AssertionError("Readiness graph loops")


class ReadinessTests(unittest.TestCase):
    def test_action_safety_and_unknown_states(self):
        for verb in gate.SAFE_VERBS:
            self.assertTrue(gate.can_receive(verb))
            for constraint in ("fishing", "paused", "loading", "minigame"):
                self.assertFalse(gate.can_receive(verb, **{constraint: True}))
        for verb in (0x34, 0xEA, 0x11A, None, -1, 0, True, "40"):
            self.assertFalse(gate.can_receive(verb))

    def test_transient_readiness_is_not_saved_or_inherited_from_old_saves(self):
        root = {"Data": {"Bool": [{"Hash": codec.U32(murmur3(gate.PAUSE)), "DefaultValue": False,
                                    "ResetTypeValue": 0, "SaveFileIndex": -1}]},
                "MetaData": {"SaveDataSize": [4096], "AllDataSaveSize": 4096}}
        raw = codec.dump({"endian": "<", "version": 7, "root": root})
        flag = gate.readiness_name("a" * 64)
        after = codec.load(gate.add_transient_flag(raw, flag))["root"]
        self.assertEqual(after["MetaData"], root["MetaData"])
        self.assertEqual(after["Data"]["Bool"][0], root["Data"]["Bool"][0])
        self.assertEqual(after["Data"]["Bool"][1],
                         {"Hash": codec.U32(murmur3(flag)), "DefaultValue": False,
                          "ResetTypeValue": 0, "SaveFileIndex": -1})
        with self.assertRaisesRegex(ValueError, "already exists or collides"):
            gate.add_transient_flag(gate.add_transient_flag(raw, flag), flag)

    def test_invalid_token_is_rejected(self):
        for token in ("", "a" * 63, "../room", "A" * 64, None):
            with self.assertRaises(ValueError):
                gate.readiness_name(token)


@unittest.skipUnless(os.environ.get("OOT_NUP"), "OOT_NUP not set; native resources remain private")
class NativeReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import ainb
        from ootrr_full.formats.inspect_nup import Nup
        from ootrr_full.game.world_maps import effective_members
        from ootrr_full.formats.inspect_resources import dictionaries, decompress, sarc
        cls.ainb = ainb
        cls.nup = Nup(os.environ["OOT_NUP"])
        cls.members = effective_members(cls.nup)
        cls.dictionaries = dictionaries(cls.nup)
        cls.unpack = staticmethod(decompress)
        cls.sarc = staticmethod(sarc)
        cls.templates = gate.native_templates(cls.sarc(cls.read(gate.GLOBAL_PACK)), cls.sarc(cls.read(gate.NAVI_PACK)))
        cls.flag = gate.readiness_name("b" * 64)

    @classmethod
    def tearDownClass(cls):
        cls.nup.stream.close()

    @classmethod
    def read(cls, path):
        raw = cls.nup.read(cls.members[path])
        return cls.unpack(raw, cls.dictionaries) if path.endswith(".zs") else raw

    def test_real_child_adult_and_base_graphs_for_all_guard_combinations(self):
        for path in gate.PLAYER_PACKS:
            source = self.sarc(self.read(path))[gate.BRAIN]
            changed = gate.patch_player_brain(source, self.flag, self.templates)
            nodes = self.ainb.AINB.from_binary(changed).as_dict()["Nodes"]
            for verb in (*sorted(gate.SAFE_VERBS), 0x34, 0xEA, 0x11A, 0xDEADBEEF):
                for fishing, paused, loading, minigame in itertools.product((False, True), repeat=4):
                    actual = walk_ai(nodes, verb=verb, fishing=fishing, paused=paused,
                                     loading=loading, minigame=minigame)
                    expected = verb in gate.SAFE_VERBS and not (fishing or paused or loading or minigame)
                    self.assertEqual(actual, expected, (path, verb, fishing, paused, loading, minigame))
            for node in nodes:
                if node["Name"] == "OneShotSetNonStructGameDataBool":
                    self.assertTrue(node["Properties"]["Bool"][0]["Default Value"])

    def test_nontrivial_player_brain_cannot_be_overwritten(self):
        from ootrr_full.patching.ap_mailbox import ainb_to_binary
        doc = self.ainb.AINB.from_binary(self.sarc(self.read(gate.PLAYER_PACKS[0]))[gate.BRAIN]).as_dict()
        doc["Nodes"][0]["Name"] = "PlayerSpecialBrainThatMustBePreserved"
        raw = ainb_to_binary(doc)
        with self.assertRaisesRegex(ValueError, "supported trivial native graph"):
            gate.patch_player_brain(raw, self.flag, self.templates)

    def test_request_branch_is_gated_and_pending_remains_set_while_busy(self):
        from ootrr_full.patching.ap_mailbox import patch_main_update
        raw = patch_main_update(self.read(gate.MAIN_UPDATE), [{}], dispatch=True)
        original = self.ainb.AINB.from_binary(raw).as_dict()
        event_query = next(n for n in self.ainb.AINB.from_binary(self.read(gate.EVENT_TEMPLATE)).as_dict()["Nodes"]
                           if n["Name"] == "SeqQueryIsPlayingMainEvent")
        changed = self.ainb.AINB.from_binary(gate.patch_mailbox_gate(raw, self.flag, event_query=event_query)).as_dict()
        nodes = changed["Nodes"]
        root = len(original["Nodes"]) + 1
        for ready, paused, loading, pending, playing in itertools.product((False, True), repeat=5):
            flags = {self.flag: ready, gate.PAUSE: paused, gate.LOADING: loading, "RandoAP.Pending": pending}
            index = root
            for _ in range(8):
                node = nodes[index]
                if node["Node Type"] != "Element_BoolSelector":
                    break
                query = nodes[node["Queries"][0]]
                value = playing if query["Name"] == "SeqQueryIsPlayingMainEvent" else flags[
                    query["Parameters"]["Inputs"]["String"][0]["Default Value"]]
                index = next(p["Node Index"] for p in node["Plugs"]["Child"]
                             if p["Name"] == ("True" if value else "False"))
            request = nodes[index]["Node Type"] == "Element_Simultaneous"
            self.assertEqual(request, ready and not paused and not loading and not playing and pending)
            if not request:
                self.assertIn(nodes[index]["Name"], ("SeqExecuteGenericDummyAction", "SeqOneShotSetNonStructGameDataBool"))
                if ready and (paused or loading or playing):
                    self.assertEqual(nodes[index]["Name"], "SeqOneShotSetNonStructGameDataBool")
                    self.assertFalse(nodes[index]["Parameters"]["Inputs"]["Bool"][0]["Default Value"])
        self.assertEqual(len(nodes) - len(original["Nodes"]), 9)

    def test_native_transient_registration_preserves_all_save_metadata(self):
        before = codec.load(self.read(gate.GAMEDATA))["root"]
        after = codec.load(gate.add_transient_flag(self.read(gate.GAMEDATA), self.flag))["root"]
        self.assertEqual(before["MetaData"], after["MetaData"])
        self.assertEqual(len(after["Data"]["Bool"]), len(before["Data"]["Bool"]) + 1)

    def test_saved_pending_cannot_execute_before_external_session_resynchronizes(self):
        from ootrr_full.patching.ap_mailbox import patch_main_update
        raw = patch_main_update(self.read(gate.MAIN_UPDATE), [{}], dispatch=True)
        event_query = next(n for n in self.ainb.AINB.from_binary(self.read(gate.EVENT_TEMPLATE)).as_dict()['Nodes']
                           if n['Name'] == 'SeqQueryIsPlayingMainEvent')
        session = 'Archipelago.ExternalSessionReady.' + 'b' * 64
        for order in (0, 1):
            if order:
                changed = gate.patch_external_session_gate(gate.patch_mailbox_gate(
                    raw, self.flag, event_query=event_query), session)
            else:
                changed = gate.patch_mailbox_gate(gate.patch_external_session_gate(raw, session),
                                                  self.flag, event_query=event_query)
            nodes = self.ainb.AINB.from_binary(changed).as_dict()['Nodes']
            group = nodes[nodes[0]['Plugs']['Child'][-1]['Node Index']]
            start = group['Plugs']['Child'][0]['Node Index']
            for synchronized, ready, paused, loading, playing in itertools.product((False, True), repeat=5):
                flags = {session: synchronized, self.flag: ready, gate.PAUSE: paused,
                         gate.LOADING: loading, 'RandoAP.Pending': True}
                index = start
                for _ in range(10):
                    node = nodes[index]
                    if node['Node Type'] != 'Element_BoolSelector': break
                    query = nodes[node['Queries'][0]]
                    value = playing if query['Name'] == 'SeqQueryIsPlayingMainEvent' else flags[
                        query['Parameters']['Inputs']['String'][0]['Default Value']]
                    index = next(p['Node Index'] for p in node['Plugs']['Child']
                                 if p['Name'] == ('True' if value else 'False'))
                self.assertEqual(nodes[index]['Node Type'] == 'Element_Simultaneous',
                                 synchronized and ready and not (paused or loading or playing))
                if paused or loading:
                    self.assertEqual(nodes[index]['Name'], 'SeqOneShotSetNonStructGameDataBool')
                    self.assertEqual(nodes[index]['Parameters']['Inputs']['String'][0]['Default Value'], session)
                    self.assertFalse(nodes[index]['Parameters']['Inputs']['Bool'][0]['Default Value'])
            with self.assertRaisesRegex(ValueError, 'already gated'):
                gate.patch_external_session_gate(changed, session)

    def test_solo_seed_without_remote_mailbox_preserves_sequence(self):
        raw = self.read(gate.MAIN_UPDATE)
        event_query = next(n for n in self.ainb.AINB.from_binary(self.read(gate.EVENT_TEMPLATE)).as_dict()["Nodes"]
                           if n["Name"] == "SeqQueryIsPlayingMainEvent")
        self.assertEqual(gate.patch_mailbox_gate(raw, self.flag, event_query=event_query), raw)


if __name__ == "__main__":
    unittest.main()
