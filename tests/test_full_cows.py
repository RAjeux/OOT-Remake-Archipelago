"""Execute finite cow rewards, then their untouched repeatable milk branch."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client'))
from evfl.entry_point import EntryPoint
from evfl.event import ActionEvent, SubFlowEvent, SwitchEvent
from evfl.util import make_index
from ootrr_full.formats import byml_codec
from ootrr_full.game.cows import entries
from ootrr_full.patching.progressive import FlowEditor
from ootrr_triforce.full_cows import patch_flow, preload_rewards, GET_DEPENDENCIES, required_resources
from test_receipt_events import native_flow


def cow_graph(rows):
    editor = FlowEditor(native_flow(), 'Synthetic cow input')
    for entry in sorted({row['cow_entry'] for row in rows}):
        milk = editor.subflow('Vanilla_' + entry, 'Dm_SY_GetInEvent', 'GetInEventInBottle',
                              {'ActorName': 'Item_Bottle_Milk', 'BottleItem': 10, 'IsTalkCamera': False})
        point = EntryPoint(entry)
        point.main_event = make_index(milk)
        editor.chart.entry_points.append(point)
    return FlowEditor(patch_flow(editor.write('Synthetic cow input')[0], rows), 'Cow test output').chart


def run(chart, entry, values):
    node = next(point.main_event.v for point in chart.entry_points if point.name == entry)
    rewards, saved = [], []
    for _ in range(100):
        if node is None:
            return rewards, saved
        data = node.data
        params = data.params.data if data.params else {}
        if isinstance(data, SwitchEvent):
            assert data.actor_query.v.v == 'EventQueryIsGameDataBool'
            node = data.cases[0 if values.get(params['GameDataName']) else 1].v
        elif isinstance(data, ActionEvent):
            command = data.actor_action.v.v
            if command == 'EventTriggerSetGameDataBool':
                values[params['GameDataName']] = params['Value']
            elif command == 'EventTriggerRequestAutoSave':
                saved.append(copy.deepcopy(values))
            else:
                assert command == 'EventWait'
            node = data.nxt.v
        elif isinstance(data, SubFlowEvent):
            assert data.res_flowchart_name == 'Dm_SY_GetInEvent'
            rewards.append(params['ActorName'])
            node = data.nxt.v
        else:
            raise AssertionError(type(data))
    raise AssertionError('Cow handover loops')


class FullCowTests(unittest.TestCase):
    def test_each_first_reward_replaces_milk_and_later_refills_do_not_resend_it(self):
        for source in entries().values():
            row = dict(source, actor='Item_AP_TestReward')
            chart = cow_graph([row])
            values = {'Sequence_IsChildhood': row['cow_age'] == 'child'}
            rewards, saves = run(chart, row['cow_entry'], values)
            self.assertEqual(rewards, ['Item_AP_TestReward'], row['cow_name'])
            self.assertTrue(saves[-1][row['native_flag']])
            rewards, saves = run(chart, row['cow_entry'], values)
            self.assertEqual(rewards, ['Item_Bottle_Milk'])
            self.assertEqual(saves, [])

    def test_shared_gerudo_flow_keeps_child_and_adult_sources_independent(self):
        rows = [dict(row, actor='Item_AP_' + row['cow_age']) for row in entries().values()
                if row['cow_name'] in {'GV Cow', 'GF Cow'}]
        chart, values = cow_graph(rows), {'Sequence_IsChildhood': True}
        self.assertEqual(run(chart, rows[0]['cow_entry'], values)[0], ['Item_AP_child'])
        values['Sequence_IsChildhood'] = False
        self.assertEqual(run(chart, rows[0]['cow_entry'], values)[0], ['Item_AP_adult'])
        self.assertEqual(run(chart, rows[0]['cow_entry'], values)[0], ['Item_Bottle_Milk'])
        self.assertTrue(all(values[row['native_flag']] for row in rows))

    def test_native_handover_preloads_preserve_unrelated_rows_and_existing_dependencies(self):
        def encode(root):
            return byml_codec.dump({'root': root, 'version': 7, 'endian': '<'})
        settings = [{'__RowId': 'CowRow', 'FlowchartFileName': 'Work/Event/EventFlow/Animal_Cow.evfc'}]
        original = [{'__RowId': 'CowRow', 'SubFlowList': ['CustomActionGuide'], 'Field': 123},
                    {'__RowId': 'Caller', 'SubFlowList': ['Animal_Cow'], 'Field': 456},
                    {'__RowId': 'Unrelated', 'SubFlowList': ['UnrelatedFlow'], 'Field': 789}]
        rows = byml_codec.load(preload_rewards(encode(original), encode(settings), {'Animal_Cow'}))['root']
        self.assertEqual(rows[-1], original[-1])
        for index in (0, 1):
            self.assertTrue(GET_DEPENDENCIES <= set(rows[index]['SubFlowList']))
            self.assertTrue(set(original[index]['SubFlowList']) <= set(rows[index]['SubFlowList']))
            self.assertEqual(rows[index]['Field'], original[index]['Field'])

    def test_external_source_cache_names_only_proven_original_resources(self):
        paths = required_resources()
        self.assertEqual(len(paths), 20)
        self.assertEqual(len(paths), len(set(paths)))
        self.assertEqual(sum(path.startswith('Banc/') for path in paths), 8)
        with self.assertRaises(ValueError):
            required_resources(['../Animal_Cow'])


if __name__ == '__main__':
    unittest.main()
