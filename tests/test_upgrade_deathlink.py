"""Live native death publications, safe requests and connection-scoped Bounces."""
import copy
import itertools
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client'))
from ootrr_triforce import upgrade_deathlink as death
from ootrr_triforce import upgrade_readiness as ready
from ootrr_triforce.upgrade_runtime import SynchronizedLive
from ootrr_full.patching.soul_adapter import murmur3

TOKEN = 'c' * 64
MANIFEST = {'seed_id': 'native-death-test', 'archipelago': {'token': TOKEN},
            'external_readiness': {'flag': ready.readiness_name(TOKEN)},
            'external_deathlink': death.metadata(TOKEN)}


class Live:
    def __init__(self):
        names = (ready.PAUSE, ready.LOADING, ready.readiness_name(TOKEN),
                 'RandoSeed.native-death-test', *death.metadata(TOKEN)['flags'].values())
        self.flags = {murmur3(name): name in (ready.readiness_name(TOKEN), 'RandoSeed.native-death-test') for name in names}
    def snapshot(self):
        return {'bool': dict(self.flags)}


class Events:
    busy = False
    def playing(self):
        return self.busy


def execute_native(nodes, root, flags, *, life=12, verb=0x28, fishing=False, minigame=False, event=False):
    """Independent graph interpreter; action names come from the real game."""
    state = {'life': life, 'subtractions': 0, 'budget': 500}
    def query(index, output=0):
        node = nodes[index]
        if node['Name'] == 'QueryActorLife': return state['life'] if output == 1 else 12
        if node['Name'] == 'QueryBSAGetActionVerb': return verb
        if node['Name'] == 'QueryNaviIsWaitPlayerStateDrawnFishingRod': return fishing
        if node['Name'] == 'QueryPlayerIsEquipMiniGameItem': return minigame
        if node['Name'] == 'QueryIsPlayingMainEvent': return event
        if node['Name'] in ('QueryGetNonStructGameDataBool', 'SeqQueryGetNonStructGameDataBool'):
            return flags.get(node['Parameters']['Inputs']['String'][0]['Default Value'], False)
        raise AssertionError('Unmodeled query: ' + node['Name'])
    def value(parameter):
        return query(parameter['Node Index'], parameter['Output Index']) if parameter.get('Node Index', -1) >= 0 else parameter['Default Value']
    def execute(index):
        state['budget'] -= 1
        assert state['budget'] >= 0, 'graph cycle'
        node = nodes[index]
        name, kind, children = node['Name'], node['Node Type'], node['Plugs'].get('Child', ())
        if kind in ('Element_Sequential', 'Element_Simultaneous'):
            for child in children: execute(child['Node Index'])
        elif kind == 'Element_S32Selector':
            result = value(node['Parameters']['Inputs']['Int'][0])
            child = next((p for p in children if p.get('Condition') == result), next(p for p in children if p.get('Is Default')))
            execute(child['Node Index'])
        elif kind == 'Element_BoolSelector':
            result = value(node['Parameters']['Inputs']['Bool'][0])
            execute(next(p['Node Index'] for p in children if p['Name'] == ('True' if result else 'False')))
        elif name == 'SelectorMathCompareInt':
            a,b = map(value, node['Parameters']['Inputs']['Int'])
            execute(next(p['Node Index'] for p in children if p['Name'] == ('Bigger' if a>b else 'Equal' if a==b else 'Smaller')))
        elif name in ('OneShotSetNonStructGameDataBool', 'SeqOneShotSetNonStructGameDataBool'):
            flags[node['Parameters']['Inputs']['String'][0]['Default Value']] = value(node['Parameters']['Inputs']['Bool'][0])
        elif name == 'OneShotLifeSetOwnLife':
            mode, amount = map(value, node['Parameters']['Inputs']['Int'])
            assert mode == 3
            state['life'] = max(0, state['life'] - amount)
            state['subtractions'] += 1
        elif name in ('ExecuteGenericSetResultSuccess', 'SeqExecuteGenericDummyAction'):
            pass
        else: raise AssertionError('Unmodeled node: ' + name)
    execute(root)
    return state


class DeathLinkTests(unittest.TestCase):
    def setUp(self):
        self.live, self.events, self.now = SynchronizedLive(Live()), Events(), 100.0
        self.link = death.ExternalDeathLink(MANIFEST, self.live, slot='Link', event_state=self.events,
                                             clock=lambda: self.now, wall_clock=lambda: self.now + 1000)
        self.writes = []
        def write(live, key, value):
            self.writes.append((key, value))
            if key not in live.flags:
                return False
            live.flags[key] = value
            return True
        self.writer = patch('ootrr_full.tracker.live_memory.set_bool_in', write)
        self.writer.start()
        self.addCleanup(self.writer.stop)

    def tick(self, dead=False, fresh=True, authenticated=True):
        self.now += .1
        self.live.flags[self.link.keys['dead']] = dead
        self.live.flags[self.link.keys['heartbeat']] = fresh
        return self.link.step(authenticated)

    def alive(self):
        self.tick(); self.tick()
        self.assertEqual(self.link.state, 0)
        self.assertTrue(self.live.flags[self.link.keys['armed']])

    def bounce(self, source='Ami', stamp=42):
        return {'cmd': 'Bounced', 'tags': ['DeathLink'], 'data': {'time': stamp, 'source': source, 'cause': 'test'}}

    def test_one_natural_death_and_no_echo_after_remote_native_ack(self):
        self.alive()
        packet = self.tick(dead=True)
        self.assertEqual(packet['cmd'], 'Bounce')
        self.assertEqual(packet['data']['source'], 'Link')
        for _ in range(4):
            self.assertIsNone(self.tick(dead=True))
        self.tick()
        self.assertTrue(self.link.receive(self.bounce()))
        self.tick()
        self.assertTrue(self.live.flags[self.link.keys['request']])
        self.live.flags[self.link.keys['fired']] = True  # native Player action accepted it
        self.assertIsNone(self.tick(dead=True))
        self.assertFalse(self.live.flags[self.link.keys['request']])

    def test_first_observed_dead_or_stale_saved_dead_never_sends(self):
        self.assertIsNone(self.tick(dead=True))
        self.assertIsNone(self.tick(dead=True))
        self.tick()
        self.assertEqual(self.link.state, 0)
        self.now += 3
        self.assertIsNone(self.tick(dead=True, fresh=False))
        self.assertEqual(self.link.state, -1)

    def test_fresh_tick_handshake_is_required_before_arming_or_accepting(self):
        self.assertFalse(self.link.receive(self.bounce()))
        self.tick()
        self.assertFalse(self.live.flags[self.link.keys['armed']])
        self.tick(fresh=False)
        self.assertFalse(self.live.flags[self.link.keys['armed']])
        self.tick()
        self.assertTrue(self.link.receive(self.bounce()))

    def test_busy_and_paused_death_waits_until_player_control_without_persistence(self):
        self.alive()
        self.live.flags[self.link.pause] = True
        self.tick(fresh=False)
        self.now += 1000
        self.assertTrue(self.link.receive(self.bounce()))
        self.tick(fresh=False)
        self.assertFalse(self.live.flags[self.link.keys['request']])
        self.live.flags[self.link.pause] = False
        self.events.busy = True
        self.tick()
        self.assertFalse(self.live.flags[self.link.keys['request']])
        self.events.busy = False
        self.tick()
        self.assertTrue(self.live.flags[self.link.keys['request']])

    def test_event_can_suspend_player_ticks_without_losing_a_held_death(self):
        self.alive()
        self.events.busy = True
        self.live.flags[self.link.readiness] = False
        self.tick(fresh=False)
        self.now += 1000
        self.assertTrue(self.link.receive(self.bounce()))
        self.tick(fresh=False)
        self.assertFalse(self.live.flags[self.link.keys['request']])
        self.events.busy = False
        self.live.flags[self.link.readiness] = True
        self.tick()
        self.assertTrue(self.live.flags[self.link.keys['request']])

    def test_loading_new_life_wrong_seed_disconnect_and_reconnect_drop_pending_deaths(self):
        for reset in ('loading', 'native_arm', 'marker', 'disconnect'):
            with self.subTest(reset=reset):
                self.setUp()
                self.alive()
                self.assertTrue(self.link.receive(self.bounce()))
                if reset == 'loading': self.live.flags[self.link.loading] = True
                elif reset == 'native_arm': self.live.flags[self.link.keys['armed']] = False
                elif reset == 'marker': self.live.flags[self.link.marker] = False
                self.tick(authenticated=reset != 'disconnect')
                self.assertIsNone(self.link.pending)
                self.assertFalse(self.live.flags[self.link.keys['request']])

    def test_dedupe_self_alias_malformed_and_simultaneous_deaths(self):
        self.alive()
        for packet in (self.bounce('Link'), self.bounce('Alias'), self.bounce(stamp=float('nan')),
                       dict(self.bounce(), data=[]), dict(self.bounce(), tags=[])):
            self.assertFalse(self.link.receive(packet, aliases=('Alias',)))
        self.assertTrue(self.link.receive(self.bounce()))
        self.assertFalse(self.link.receive(self.bounce()))
        self.assertTrue(self.link.receive(self.bounce('Other', stamp=43)))
        self.tick()
        self.assertEqual(sum(value is True and key == self.link.keys['request'] for key, value in self.writes), 1)

    def test_old_artifact_has_no_deathlink_and_metadata_cannot_redirect_flags(self):
        old = copy.deepcopy(MANIFEST)
        del old['external_deathlink']
        self.assertFalse(death.ExternalDeathLink(old, self.live, slot='Link', event_state=self.events).enabled)
        old['archipelago']['death_link'] = False
        self.assertIn('disabled', death.ExternalDeathLink(old, self.live, slot='Link', event_state=self.events).status)
        modified = copy.deepcopy(MANIFEST)
        modified['external_deathlink']['flags']['request'] = ready.LOADING
        with self.assertRaisesRegex(ValueError, 'metadata is invalid'):
            death.ExternalDeathLink(modified, self.live, slot='Link', event_state=self.events)
        disabled = copy.deepcopy(MANIFEST)
        disabled['external_deathlink'] = death.metadata(TOKEN, enabled=False)
        link = death.ExternalDeathLink(disabled, self.live, slot='Link', event_state=self.events)
        self.assertFalse(link.enabled)
        self.assertIn('disabled', link.status)
        self.assertIsNone(link.step(True))
        self.assertFalse(link.receive(self.bounce()))


class NetworkDeathLinkTests(unittest.TestCase):
    def test_network_only_advertises_prepared_capability_and_requires_current_history_fence(self):
        from ootrr_full.archipelago.client import ArchipelagoClient
        class Link:
            enabled = True
            calls = []
            def receive(self, packet, aliases): self.calls.append((packet, aliases))
            def suspend(self): pass
        class Socket:
            packets = []
            def send(self, raw): self.packets.extend(json.loads(raw))
        link, socket = Link(), Socket()
        manifest = {'archipelago': {'slot_name': 'Link', 'location_ids': {'one': 1}}}
        client = ArchipelagoClient(manifest, 'ws://127.0.0.1:1', delivery=object(), deathlink=link)
        client._handle(socket, {'cmd': 'RoomInfo', 'games': []})
        self.assertEqual(next(p for p in socket.packets if p['cmd'] == 'Connect')['tags'], ['AP', 'DeathLink'])
        packet = {'cmd': 'Bounced', 'tags': ['DeathLink'], 'data': {'time': 42, 'source': 'Ami'}}
        client.connected = True
        client._handle(socket, packet)
        self.assertEqual(link.calls, [])
        client._history_synced = True
        client.slot, client.players = 1, {1: 'Alias'}
        client._handle(socket, packet)
        self.assertEqual(link.calls, [(packet, ('Alias',))])
        client.connected = False
        client._handle(socket, packet)
        self.assertEqual(len(link.calls), 1)


@unittest.skipUnless(os.environ.get('OOT_NUP'), 'OOT_NUP not set; native resources remain private')
class NativeDeathLinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import ainb
        from ootrr_full.formats.inspect_nup import Nup
        from ootrr_full.game.world_maps import effective_members
        from ootrr_full.formats.inspect_resources import dictionaries, decompress, sarc
        cls.ainb, cls.sarc = ainb, staticmethod(sarc)
        cls.nup = Nup(os.environ['OOT_NUP'])
        cls.members, cls.dictionaries = effective_members(cls.nup), dictionaries(cls.nup)
        cls.decompress = staticmethod(decompress)
        files = sarc(cls.read(ready.GLOBAL_PACK))
        cls.templates = death.native_templates(files)
        cls.readiness_templates = ready.native_templates(files, sarc(cls.read(ready.NAVI_PACK)))

    @classmethod
    def tearDownClass(cls): cls.nup.stream.close()

    @classmethod
    def read(cls, path):
        raw = cls.nup.read(cls.members[path])
        return cls.decompress(raw, cls.dictionaries) if path.endswith('.zs') else raw

    def test_real_live_query_and_subtract_action_and_all_three_brains_roundtrip(self):
        self.assertEqual(self.templates['subtract']['Parameters']['Inputs']['Int'][0]['Default Value'], 3)
        for path in ready.PLAYER_PACKS:
            source = self.sarc(self.read(path))[ready.BRAIN]
            gated = ready.patch_player_brain(source, ready.readiness_name(TOKEN), self.readiness_templates)
            raw = death.patch_player_brain(gated, TOKEN, self.templates, seed_marker='RandoSeed.native-death-test')
            document = self.ainb.AINB.from_binary(raw).as_dict()
            actions = [n for n in document['Nodes'] if n['Name'] == 'OneShotLifeSetOwnLife']
            self.assertEqual(len(actions), 1)
            value = actions[0]['Parameters']['Inputs']['Int'][1]
            self.assertEqual(value['Output Index'], 1)
            self.assertEqual(document['Nodes'][value['Node Index']]['Name'], 'QueryActorLife')
            self.assertFalse(any('PlayerStatus.Life' in json.dumps(n) for n in document['Nodes']))
            # No repeated wrapping or unsupported Player graph overwrite.
            with self.assertRaisesRegex(ValueError, 'supported native readiness graph'):
                death.patch_player_brain(raw, TOKEN, self.templates, seed_marker='RandoSeed.native-death-test')
            from ootrr_full.patching.ap_mailbox import ainb_to_binary
            modified = self.ainb.AINB.from_binary(gated).as_dict()
            modified['Nodes'][0]['Plugs']['Child'][0]['Node Index'] = 10
            with self.assertRaisesRegex(ValueError, 'supported native readiness graph'):
                death.patch_player_brain(ainb_to_binary(modified), TOKEN, self.templates,
                                        seed_marker='RandoSeed.native-death-test')

    def test_loading_reset_roundtrips_and_clears_only_unsaved_death_mailbox(self):
        from ootrr_full.patching import ap_mailbox as mailbox
        main = mailbox.patch_main_update(self.read(ready.MAIN_UPDATE), [{}], dispatch=True)
        changed = death.patch_loading_reset(main, TOKEN)
        document = self.ainb.AINB.from_binary(changed).as_dict()
        setters = [n for n in document['Nodes'] if n['Name'] == 'SeqOneShotSetNonStructGameDataBool'
                   and any(str(p.get('Default Value', '')).startswith(death.PREFIX)
                           for p in n['Parameters']['Inputs'].get('String', ()))]
        self.assertEqual(len(setters), 5)
        self.assertTrue(all(n['Parameters']['Inputs']['Bool'][0]['Default Value'] is False for n in setters))

    def test_actual_native_graph_blocks_all_constraints_and_only_subtracts_live_life_once(self):
        source = self.sarc(self.read(ready.PLAYER_PACKS[0]))[ready.BRAIN]
        gated = ready.patch_player_brain(source, ready.readiness_name(TOKEN), self.readiness_templates)
        raw = death.patch_player_brain(gated, TOKEN, self.templates, seed_marker='RandoSeed.native-death-test')
        doc = self.ainb.AINB.from_binary(raw).as_dict()
        names = death.metadata(TOKEN)['flags']
        original = dict.fromkeys(names.values(), False)
        original.update({names['armed']: True, names['request']: True, 'RandoSeed.native-death-test': True})
        cases = 0
        for verb in (*sorted(ready.SAFE_VERBS), 0x34, 0xEA, 0x11A):
            for fishing, minigame, paused, loading, event, seeded, armed in itertools.product((False, True), repeat=7):
                flags = dict(original)
                flags.update({ready.PAUSE: paused, ready.LOADING: loading,
                              'RandoSeed.native-death-test': seeded, names['armed']: armed})
                result = execute_native(doc['Nodes'], doc['Commands'][0]['Root Node Index'], flags,
                    life=17, verb=verb, fishing=fishing, minigame=minigame, event=event)
                allowed = verb in ready.SAFE_VERBS and seeded and armed and not any((fishing, minigame, paused, loading, event))
                self.assertEqual(result['subtractions'], int(allowed))
                self.assertEqual(result['life'], 0 if allowed else 17)
                self.assertEqual(flags[names['fired']], allowed)
                # Repeated game frames do not repeat an accepted death request.
                again = execute_native(doc['Nodes'], doc['Commands'][0]['Root Node Index'], flags,
                    life=result['life'], verb=verb, fishing=fishing, minigame=minigame, event=event)
                self.assertEqual(again['subtractions'], 0)
                cases += 1
        self.assertEqual(cases, 1664)
        flags = dict(original, **{'RandoAP.Pending': True})
        result = execute_native(doc['Nodes'], doc['Commands'][0]['Root Node Index'], flags)
        self.assertEqual(result['subtractions'], 0)
        self.assertFalse(flags[names['fired']])
        for life in (0, -1):
            flags = dict(original)
            execute_native(doc['Nodes'], doc['Commands'][0]['Root Node Index'], flags, life=life)
            self.assertTrue(flags[names['dead']])
            self.assertFalse(flags[ready.readiness_name(TOKEN)])


if __name__ == '__main__': unittest.main()
