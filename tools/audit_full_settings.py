"""Exhaustive legacy/public/full option parity without claiming gameplay proof.

This reports each native schema key and each public legacy value independently.
A setting name alone never counts as evidence that its native adapter works.
"""
from collections import Counter
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client'))
from ootrr_triforce.settings import OPTION_SPECS
from ootrr_triforce.full_ap import (full_defaults, full_option_specs, translate_legacy_options,
                                   validate_full_options, ADULT_START_UNAVAILABLE)
import audit_settings

SPECIAL = {
    'starting_items': ('ap_common', 'Use AP start_inventory_from_pool with AP item names. '
                       'The legacy native equipment set is not imported automatically.'),
    'starting_songs': ('ap_common', 'Use AP start_inventory_from_pool with AP song names. '
                       'The ocarina remains necessary to play a known song.'),
    'start_reward': ('ap_common', 'Use AP start_inventory for an explicit extra Spiritual Stone or Medallion. '
                     'The legacy random native reward selector is not reproduced.'),
    'death_link': ('full', 'Shared native/runtime DeathLink setting, separate from item placement.'),
    'open_kakariko': ('partial', 'Full opens the gate without also skipping child Zelda or granting her letter '
                       'and Impa song. Those story effects use separate full options.'),
    'time_always_passes': ('always_on', 'Full mode enables the native time progression from the start '
                          'through its owl-advice/start-state adapter. No separate switch freezes it again.'),
    'skip_intro': ('always_on', 'Full mode always enables the native skip input for the otherwise locked '
                  'opening and related movies. There is no independent switch to prohibit skipping them.'),
    'skip_cutscenes': ('always_on', 'Full mode always enables native skipping for the opening, title demos '
                       'and credits, plus its selected dialogue/area presentation flow fixes.'),
    'song_harp_colors': ('always_on', 'Shuffled physical songs already use the native Sheik harp model '
                        'with the matching ocarina-menu song colour. No separate uncoloured full mode is exposed.'),
    'enemy_spawn_combo': ('legacy_only', 'Developer input shortcut is deliberately separate from normal gameplay '
                          'and not enabled by the full-network challenge adapter.'),
}


def _values(spec):
    if spec['kind'] == 'choice':
        return list(spec['choices'])
    if spec['kind'] == 'toggle':
        return [False, True]
    if spec['kind'] == 'range':
        return sorted({spec['min'], spec['default'], spec['max']})
    return [[], list(spec.get('choices', ()))]


def report():
    rows = []
    defaults = full_defaults()
    for spec in OPTION_SPECS:
        name = spec['id']
        accepted, unavailable, targets, contexts = [], [], set(), []
        for value in _values(spec):
            context = dict(defaults)
            if name == 'no_ammo_drops' and value:
                context['full_shopsanity'] = '4'
                contexts.append({'value': value, 'settings': {'full_shopsanity': '4'},
                                 'reason': 'Requires retained renewable shop ammunition; use numbered Shopsanity, not all shop items.'})
            try:
                translated = translate_legacy_options({name: copy.deepcopy(value)}, context)
                normalized = validate_full_options(translated)
            except ValueError as error:
                unavailable.append({'value': value, 'reason': str(error)})
            else:
                accepted.append(value)
                targets.update(key for key, field in normalized.items() if field != context[key])
        status = 'full' if not unavailable else 'partial' if accepted else 'legacy_only'
        reason = ('Every public legacy value translates to a supported full setting. Native resource and '
                  'gameplay evidence are tracked by the relevant adapter tests, independently of this schema audit.'
                  if status == 'full' else
                  'Only the listed values have full equivalents; unsupported values are rejected explicitly.'
                  if status == 'partial' else
                  'No equivalent independent full setting is exposed. Keep this setting in legacy mode until its '
                  'game resources and AP logic can be adapted together.')
        if name in SPECIAL:
            status, reason = SPECIAL[name]
        rows.append({'id': name, 'status': status, 'reason': reason, 'full_fields': sorted(targets),
                     'accepted_legacy_values': accepted, 'unavailable_legacy_values': unavailable,
                     'compatible_validation_contexts': contexts})
    native = audit_settings.report(audit_settings.load_schema())
    by_id = {row['id']: row for row in rows}
    full_specs = {row['id']: row for row in full_option_specs()}
    for row in native['settings']:
        full = by_id.get(row['id'])
        row['full_status'] = full['status'] if full else 'not_public_in_legacy'
        row['full_reason'] = full['reason'] if full else row['reason']
        field = 'full_' + row['id']
        if full is None and field in full_specs:
            row['full_status'] = 'full'
            row['full_reason'] = ('Available through ' + field + '. Full-network resource/logic adapters '
                                  'support the values listed in that control, independently of the older native planner.')
        if row['id'] == 'starting_age':
            row['full_status'] = 'partial'
            row['full_reason'] = ADULT_START_UNAVAILABLE
        if row['id'].startswith('ganon_bosskey_'):
            suffix = row['id'][len('ganon_bosskey_'):]
            control = 'full_lacs_' + suffix
            if control in full_specs:
                mode = 'dungeons' if suffix == 'rewards' else suffix
                row['full_status'] = 'mapped_to_lacs'
                row['full_reason'] = (
                    'Full network provides this threshold through ' + control + ' with '
                    'full_shuffle_ganon_bosskey=lacs_' + mode + '. The key uses the native Light Arrows '
                    'handover; this older planner field is not exposed as a separate key-reward mode.')
    return {'format': 1, 'legacy_public_count': len(rows), 'full_public_count': len(full_option_specs()),
            'legacy_status_counts': dict(Counter(row['status'] for row in rows)),
            'legacy_public': rows, 'native_schema': native['settings'],
            'full_options': list(full_option_specs()),
            'execution_restrictions': [{'field': 'full_starting_age', 'available': ['child'],
                                        'reason': ADULT_START_UNAVAILABLE}],
            'validation_boundary': 'Value translation and resource tests do not replace actual-game route validation.'}


def markdown(data):
    lines = ['# Full-network settings parity', '',
             'This report is generated by `tools/audit_full_settings.py`. It covers every public legacy '
             'setting and the complete native settings schema. A rejected value is never silently applied '
             'with different logic. Actual-game evidence remains separate from this schema report.', '',
             f"Legacy public settings: {data['legacy_public_count']}. Full public controls: {data['full_public_count']}.", '',
             ADULT_START_UNAVAILABLE, '',
             '| Legacy setting | Full status | Full controls / reason |', '| --- | --- | --- |']
    for row in data['legacy_public']:
        target = ', '.join('`' + name + '`' for name in row['full_fields'])
        detail = target or row['reason']
        if row['status'] == 'partial':
            values = ', '.join(str(value['value']) for value in row['unavailable_legacy_values'])
            detail += '. ' + (('Unavailable values: ' + values) if values else row['reason'])
        if row.get('compatible_validation_contexts'):
            detail += '. ' + row['compatible_validation_contexts'][0]['reason']
        lines.append(f"| `{row['id']}` | {row['status']} | {detail.replace('|', '/')} |")
    lines += ['', '## Native settings outside the public legacy catalogue', '',
              '| Native setting | Current compatibility decision |', '| --- | --- |']
    for row in data['native_schema']:
        if row['id'] not in {public['id'] for public in data['legacy_public']}:
            lines.append(f"| `{row['id']}` | {row['full_reason'].replace('|', '/')} |")
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', type=Path)
    parser.add_argument('--markdown', type=Path)
    args = parser.parse_args()
    data = report()
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown(data), encoding='utf-8')
    print(json.dumps({key: data[key] for key in ('legacy_public_count', 'full_public_count', 'legacy_status_counts')}))


if __name__ == '__main__':
    main()
