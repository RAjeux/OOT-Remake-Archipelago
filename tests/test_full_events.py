"""One-time gift guards follow actual hand-overs and retain native story exits."""
from collections import Counter
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client'))
from evfl.entry_point import EntryPoint
from evfl.event import ActionEvent, SubFlowEvent, SwitchEvent
from evfl.util import make_index
from ootrr_full.patching.event_patch import _flow, add_collection_markers
from ootrr_full.patching.progressive import FlowEditor, link, add_converter_calls
from ootrr_full.randomizer.randomizer_core import _relocate_gift_marker
from ootrr_triforce.full_events import guard_gifts
from test_receipt_events import native_flow


def fixture(converter=False, text=False):
    editor = FlowEditor(native_flow(), 'One-time gift fixture')
    finish = editor.action('StoryContinues', 'GameDataActor', 'EventTriggerSetGameDataBool',
                           {'GameDataName': 'Fixture.Story', 'Index': -1, 'Value': True})
    gift = editor.subflow('Gift', 'GetPouchContent', 'GetPouchContentByActorName', {'ActorName': 'Item_Test'})
    link(gift, finish)
    point = EntryPoint('GiftFixture')
    point.main_event = make_index(gift)
    point._sub_flow_event_indices = [editor.chart.events.index(gift)]
    editor.chart.entry_points.append(point)
    raw, markers = add_collection_markers(editor.write('One-time gift fixture')[0], {'Gift': 'Fixture.Collected'})
    if text:
        from ootrr_full.patching.song_adapter import patch_flow
        raw = patch_flow(raw, {'text_get': [('Gift', 'Item_Test', True)]})
    if converter:
        raw = add_converter_calls(raw, ['Gift'], 'One-time gift fixture')
    return raw, markers


class GiftRun:
    def __init__(self, raw, collected=False):
        self.chart = _flow(raw).flowchart
        self.values = {'Fixture.Collected': collected}
        self.calls = Counter()

    def run(self):
        node = next(point.main_event.v for point in self.chart.entry_points if point.name == 'GiftFixture')
        for _ in range(100):
            if node is None:
                return self
            data = node.data
            params = data.params.data if getattr(data, 'params', None) else {}
            if isinstance(data, ActionEvent):
                self.assert_action(data.actor_action.v.v)
                self.values[params['GameDataName']] = params['Value']
                node = data.nxt.v
            elif isinstance(data, SwitchEvent):
                assert data.actor_query.v.v == 'EventQueryIsGameDataBool'
                node = data.cases.get(0 if self.values.get(params['GameDataName']) else 1)
                node = node.v if node else None
            elif isinstance(data, SubFlowEvent):
                self.calls[(data.res_flowchart_name, data.entry_point_name)] += 1
                node = data.nxt.v
            else:
                raise AssertionError(type(data).__name__)
        raise AssertionError('Gift guard loop')

    @staticmethod
    def assert_action(action):
        assert action == 'EventTriggerSetGameDataBool', action


class GiftGuardTests(unittest.TestCase):
    def test_first_pickup_then_story_revisit_grants_once_and_keeps_story_continuation(self):
        for converter, text in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(converter=converter, text=text):
                raw, markers = fixture(converter, text)
                run = GiftRun(guard_gifts(raw, markers))
                run.run()
                self.assertTrue(run.values['Fixture.Collected'])
                self.assertTrue(run.values['Fixture.Story'])
                self.assertGreater(sum(run.calls.values()), 0)
                first = run.calls.copy()
                run.values['Fixture.Story'] = False
                run.run()
                self.assertEqual(run.calls, first, 'Do not repeat the item, converter or display')
                self.assertTrue(run.values['Fixture.Story'])

    def test_older_save_restored_check_skips_the_physical_grant_without_skipping_story(self):
        raw, markers = fixture(converter=True, text=True)
        run = GiftRun(guard_gifts(raw, markers), collected=True)
        run.run()
        self.assertFalse(run.calls)
        self.assertTrue(run.values['Fixture.Story'])

    def test_wrong_flag_duplicate_marker_and_dead_event_are_rejected(self):
        raw, markers = fixture()
        with self.assertRaisesRegex(ValueError, 'flag does not match'):
            guard_gifts(raw, [dict(markers[0], flag='Another.Check')])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            guard_gifts(raw, markers + markers)
        chart = FlowEditor(raw, 'Dead gift fixture')
        point = next(point for point in chart.chart.entry_points if point.name == 'GiftFixture')
        point.main_event = make_index(None)
        with self.assertRaisesRegex(ValueError, 'unreachable'):
            guard_gifts(chart.write('Dead gift fixture')[0], markers)

    def test_metadata_relocation_moves_only_the_actual_gift_and_preserves_other_records(self):
        old = {'event': 'OldGift', 'marker': 'RandoCollected_OldGift', 'flag': 'Check.Gift'}
        other = {'event': 'Other', 'marker': 'RandoCollected_Other', 'flag': 'Check.Other'}
        rows = {'cutscene': [old, other]}
        _relocate_gift_marker(rows, 'cutscene', 'OldGift', 'gameplay', 'RandoGiftGet', 'Check.Gift')
        self.assertEqual(rows['cutscene'], [other])
        self.assertEqual(rows['gameplay'], [{'event': 'RandoGiftGet', 'marker': 'RandoCollected_RandoGiftGet',
                                            'flag': 'Check.Gift'}])
        with self.assertRaisesRegex(ValueError, 'inconsistent'):
            _relocate_gift_marker(rows, 'cutscene', 'OldGift', 'gameplay', 'RandoGiftGet', 'Check.Gift')


@unittest.skipUnless(os.environ.get('OOT_NUP'), 'OOT_NUP not set')
class NativeGiftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ootrr_full.formats.inspect_nup import Nup
        from ootrr_full.formats.inspect_resources import dictionaries, decompress
        cls.nup = Nup(os.environ['OOT_NUP'])
        cls.dictionary, cls.decompress = dictionaries(cls.nup), staticmethod(decompress)

    @classmethod
    def tearDownClass(cls):
        cls.nup.stream.close()

    @classmethod
    def read(cls, path):
        return cls.decompress(cls.nup.read(cls.nup.latest('romfs/' + path)), cls.dictionary)

    def test_every_relocated_cutscene_gift_is_guarded_at_its_live_hand_over(self):
        from ootrr_full.patching.qol_patches import GIFT_AFTER_CUTSCENE, GIFT_GET_EVENT, bypass_cutscene_gift, give_gift_after
        from ootrr_full.patching.event_info import reachable
        for source, spec in GIFT_AFTER_CUTSCENE.items():
            with self.subTest(source=source):
                flag = 'Fixture.DekuTree'
                marked, old = add_collection_markers(self.read(source), {spec['event']: flag})
                bypassed, report = bypass_cutscene_gift(marked, spec['event'])
                active = {event.name for point in _flow(bypassed).flowchart.entry_points
                          for event in reachable(point.main_event.v)}
                self.assertNotIn(spec['event'], active)
                target, _ = give_gift_after(self.read(spec['flow']), spec['after'], report['actor'], flag)
                metadata = {source: old}
                _relocate_gift_marker(metadata, source, spec['event'], spec['flow'], GIFT_GET_EVENT, flag)
                guarded = _flow(guard_gifts(target, metadata[spec['flow']])).flowchart
                named = {event.name: event for event in guarded.events}
                gate = named['OOTRR_APOnce_' + GIFT_GET_EVENT]
                self.assertIs(gate.data.cases[1].v, named[GIFT_GET_EVENT])
                self.assertIs(gate.data.cases[0].v, named['RandoCollected_' + GIFT_GET_EVENT].data.nxt.v)
                self.assertNotIn(source, metadata)

    @unittest.skipUnless(os.environ.get('OOT_FULL_ARTIFACT'), 'OOT_FULL_ARTIFACT not set')
    def test_all_prepared_gift_markers_match_live_sources_and_saved_schema_flags(self):
        from ootrr_full.patching.soul_adapter import murmur3
        from ootrr_full.formats import byml_codec
        artifact = Path(os.environ['OOT_FULL_ARTIFACT'])
        tracking = json.loads((artifact / 'tracking.json').read_bytes())
        def read(path):
            return self.decompress((artifact / 'romfs' / path).read_bytes(), self.dictionary)
        schema = byml_codec.load(read('GameData/GameDataList.Product.110.byml.zs'))['root']['Data']['Bool']
        saved = {int(row['Hash']) for row in schema if row.get('SaveFileIndex') == 0}
        wanted = {int(row['collection']['hash']) for row in tracking['checks'].values()
                  if row.get('collection') and row['collection']['type'] == 'bool'}
        count = 0
        for path, markers in tracking['event_markers'].items():
            selected = [row for row in markers if murmur3(row['flag']) in wanted]
            if selected:
                self.assertTrue({murmur3(row['flag']) for row in selected} <= saved)
                guard_gifts(read(path), selected)
                count += len(selected)
        self.assertGreater(count, 70)


if __name__ == '__main__':
    unittest.main()
