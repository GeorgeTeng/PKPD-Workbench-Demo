"""Mechanical preparation checks. No model calls or scientific adequacy decisions."""
import copy
import csv
import json
from collections import Counter

from .adequacy import check_ref
from .common import read_json

EXECUTION_VERSION = 'data-preparation-views-v3'


def freeze_refs(*values):
    """Keep the original bindings, including nested predecessor/source references."""
    refs = {}

    def visit(value):
        if isinstance(value, dict):
            if isinstance(value.get('path'), str) and isinstance(value.get('sha256'), str):
                refs[(value['path'], value['sha256'])] = {
                    'path': value['path'], 'sha256': value['sha256']}
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for value in values:
        visit(value)
    result = list(refs.values())
    verify_frozen(result)
    return result


def verify_frozen(refs):
    for ref in refs:
        check_ref(ref)


def verify_preparation(manifest, plan, inventory, changes, dictionary, labels=None):
    """Check persisted records against the permitted snapshot, plan and actual log.

    Only the current one-source-row-to-one-output-record adapter is supported.
    Exact numeric agreement is appropriate here: both values are unrounded
    Python scalar results. This is not an assay-precision acceptance criterion.
    """
    from openpyxl.utils.cell import get_column_letter
    from .preparation_workflow import csv_sheet, numeric, unit_mapping
    from .source_preparation import value_status
    from .preparation_semantics import row_value_statuses,dose_metadata
    from . import preparation_views as views

    results = []
    records_by_id = {}
    items = {item['id']: item for item in inventory['items']}
    mappings = {table['item_id']: table for table in plan['tables']}
    expected_items = [t['item_id'] for t in plan['tables'] if t['action'] == 'PREPARE']
    actual_items = [d['metadata']['source_item_id'] for d in manifest['datasets']]
    package_errors = []
    if Counter(expected_items) != Counter(actual_items):
        package_errors.append('Prepared datasets do not account for the PREPARE table plan.')
    expected_changes = []
    for dataset in manifest['datasets']:
        errors = []
        metadata = dataset['metadata']
        item = items[metadata['source_item_id']]
        mapping = mappings[item['id']]
        check_ref(item['snapshot'])
        snap = read_json(item['snapshot']['path'])
        sheet = (snap['sheets'] if snap['kind'] == 'xlsx' else [csv_sheet(snap)])[item['sheet_index']]
        region = item['region']
        cells = {(c['row'], c['column']): c for c in sheet['cells']}
        fields = metadata['source_table']['column_map']
        if dictionary.get(dataset['id']) != fields:
            errors.append('Data dictionary differs from the source-column mapping.')
        notes = {link['cell']: link['note'] for link in item['descriptor'].get('footnote_links', [])}
        retained = read_json(dataset['data']['path'])['records']
        quarantined = read_json(dataset['quarantine']['path'])['records']
        records = retained + quarantined
        records_by_id.update({r['record_id']: r for r in records})
        expected_rows = [row for row in range(region['header_row'] + 1, region['end_row'] + 1)
                         if any((row, c) in cells for c in range(region['left'], region['right'] + 1))]
        if Counter(r['source_row'] for r in records) != Counter(expected_rows):
            errors.append('Source rows are missing, duplicated or added.')
        if len({r['record_id'] for r in records}) != len(records):
            errors.append('Output record identifiers are not unique.')
        source_label=next((x for x in (labels or {}).get('labels',[]) if x['item_id']==item['id']),metadata)
        selected = {c['target']: (next(k for k, h in fields.items() if h == c['source_header']),
                                  views.mapping_factor(mapping,source_label,c))
                    for c in mapping['columns']}
        expected_normalized = {target: {'source_header': fields[key], 'factor': factor}
                               for target, (key, factor) in selected.items()}
        if metadata['normalized_fields'] != expected_normalized:
            errors.append('Metadata conversion parameters differ from the implemented adapter.')
        if labels is not None:
            label=next(x for x in labels['labels'] if x['item_id']==item['id'])
            if mapping.get('preparation_policy')==views.POLICY and metadata.get('columns')!=label['columns']:
                errors.append('Column semantics differ from the bound reviewed source label.')
            if metadata.get('dose')!=dose_metadata(label,labels.get('stated_values',[])):
                errors.append('Dose metadata differs from reviewed source statements.')
        quarantined_ids = {r['record_id'] for r in quarantined}
        for record in records:
            prefix = record['record_id'] + ': '
            row = record['source_row']
            reasons = []
            source_values={key:cells.get((row,col),{}).get('value') for col,key in enumerate(fields,region['left'])}
            source_statuses={key:value_status(source_values[key],cells.get((row,col),{}),
                notes.get(f'{get_column_letter(col)}{row}') or item['descriptor'].get('source_notes',''))
                for col,key in enumerate(fields,region['left'])}
            source_statuses=row_value_statuses(source_values,fields,item['descriptor'].get('source_notes',''),source_statuses)
            if (record['source_file_id'] != item['file_id']
                    or record['source_sha256'] != item['source']['sha256']
                    or record['source_sheet'] != sheet['name']):
                errors.append(prefix + 'Source identity does not match.')
            if set(record['source_raw_values']) != set(fields) or set(record['source_cells']) != set(fields):
                errors.append(prefix + 'Source field coverage differs.')
            for column, key in enumerate(fields, region['left']):
                cell = cells.get((row, column), {})
                raw = cell.get('value')
                value = raw.strip() if isinstance(raw, str) else raw
                address = f'{get_column_letter(column)}{row}'
                status = source_statuses[key]
                if (record['source_raw_values'].get(key) != raw or record.get(key) != value
                        or record['source_cells'].get(key) != address or record['value_status'].get(key) != status):
                    errors.append(prefix + 'Source value, locator or status differs at ' + address)
                if notes.get(address) != record.get('source_footnotes', {}).get(key):
                    errors.append(prefix + 'Footnote differs at ' + address)
                if cell.get('data_type') in {'f', 'e'}:
                    reasons.append(status)
                if value != raw:
                    expected_changes.append({'record_id': record['record_id'], 'field': key,
                                             'action': 'TRIM_OUTER_WHITESPACE', 'before': raw, 'after': value})
            for target, (key, factor) in selected.items():
                raw = record['source_raw_values'].get(key)
                value = numeric(raw)
                if mapping.get('preparation_policy')==views.POLICY:
                    column=next(c for c in source_label['columns'] if c['header']==fields[key])
                    mapped,reason=views.scalar_result(raw,column,source_statuses[key],target,factor)
                    if reason:reasons.append(reason)
                    if mapped is None:
                        if target in record:errors.append(prefix+'Unusable scalar was converted.')
                    else:
                        if record.get(target)!=mapped:errors.append(prefix+'Conversion differs for '+target)
                        expected_changes.append({'record_id':record['record_id'],'field':target,'source_field':key,
                            'factor':factor,'action':'EXPLICIT_UNIT_CONVERSION','before':raw,'after':mapped})
                    continue
                if source_statuses[key] in {'CENSORED','MISSING_CENSORED_OBSERVATION'} or value is None or (target == 'concentration_mg_L' and value < 0):
                    if target in record:
                        errors.append(prefix + 'An unusable value was converted.')
                    reasons.append(source_statuses[key] if source_statuses[key] in {'CENSORED','MISSING_CENSORED_OBSERVATION'} else 'NEGATIVE_CONCENTRATION' if value is not None else
                                   record['value_status'][key] if record['value_status'][key] != 'QUANTIFIED'
                                   else 'NONNUMERIC_' + target)
                else:
                    if factor is None or record.get(target) != value * factor:
                        errors.append(prefix + 'Conversion differs for ' + target)
                    expected_changes.append({'record_id': record['record_id'], 'field': target,
                                             'source_field': key, 'factor': factor,
                                             'action': 'EXPLICIT_UNIT_CONVERSION', 'before': raw,
                                             'after': value * factor if factor is not None else None})
            if any(target in record for target in {'time_h', 'concentration_mg_L'} - set(selected)):
                errors.append(prefix + 'Unplanned normalized field.')
            if (record['qc_reasons'] != sorted(set(reasons))
                    or (record['record_id'] in quarantined_ids) != bool(reasons)
                    or record['qc_status'] != ('QUARANTINED' if reasons else 'TECHNICALLY_RETAINED')):
                errors.append(prefix + 'Quarantine disposition differs from the executed policy.')
        if mapping.get('preparation_policy')==views.POLICY:
            if not dataset.get('observation_view'):
                errors.append('Missing source-bound observation view.')
            else:
                check_ref(dataset['observation_view'])
                view=read_json(dataset['observation_view']['path'])
                errors.extend(views.verify_view(view,metadata,records))
                if dataset.get('observation_summary')!=view['counts']:
                    errors.append('Observation accounting summary differs.')
                if dataset.get('observation_restrictions')!=view['operation_restrictions']:
                    errors.append('Observation action restrictions differ.')
        with open(dataset['csv']['path'], encoding='utf-8-sig', newline='') as handle:
            csv_records = list(csv.DictReader(handle))
        expected_csv = [{k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list))
                         else '' if v is None else str(v) for k, v in r.items()} for r in retained]
        keys = set().union(*(r.keys() for r in expected_csv))
        if csv_records != [{k: r.get(k, '') for k in keys} for r in expected_csv]:
            errors.append('CSV values differ from the retained JSON records.')
        if any(dataset['summary'].get(k) != v for k, v in {
                'source_records': len(expected_rows), 'retained_records': len(retained),
                'quarantined_records': len(quarantined)}.items()):
            errors.append('Summary counts differ from actual source/output records.')
        results.append({'dataset_id': dataset['id'], 'decision': 'REVISE' if errors else 'PASS',
                        'checked_scope': {'source_item_id': item['id'], 'source_records': len(expected_rows),
                                          'retained_records': len(retained), 'quarantined_records': len(quarantined)},
                        'errors': errors})
    # Compare the change multiset because retained/quarantined files partition source order.
    core_keys = ('record_id', 'field', 'source_field', 'factor', 'action', 'before', 'after')
    core = lambda value: json.dumps({k: value[k] for k in core_keys if k in value}, sort_keys=True)
    if Counter(map(core, expected_changes)) != Counter(map(core, changes)):
        package_errors.append('Actual-change log differs from source/output transformations.')
    for change in changes:
        record = records_by_id.get(change['record_id'])
        source_field = change.get('source_field', change['field'])
        if (record is None or change.get('source_sha256') != record['source_sha256']
                or change.get('source_cell') != record['source_cells'].get(source_field)
                or change.get('source_file_id') != record['source_file_id']
                or change.get('source_sheet') != record['source_sheet']
                or change.get('execution_version') != EXECUTION_VERSION
                or change.get('rule_refs') != ['DP003', 'DP009']):
            package_errors.append('A change is missing its exact provenance or execution binding.')
            break
    return {'schema_version': '1.0', 'executor': 'HOST_PROGRAM', 'execution_version': EXECUTION_VERSION,
            'decision': 'REVISE' if package_errors or any(r['errors'] for r in results) else 'PASS',
            'datasets': results, 'errors': package_errors,
            'held_items': [t['item_id'] for t in plan['tables'] if t['action'] == 'HOLD'],
            'scientific_adequacy_assessed': False}


def validate_metadata(manifest, qc_results):
    """Bind and compare existing metadata; never repeat scientific definition review."""
    results = []
    qc_by_id = {r['dataset_id']: r for r in qc_results['datasets']}
    freeze_refs([d[k] for d in manifest['datasets'] for k in ('data', 'csv', 'metadata_file', 'quarantine')])
    sidecars = [read_json(d['metadata_file']['path']) for d in manifest['datasets']]
    freeze_refs([s.get('source_refs', []) for s in sidecars])
    for dataset, sidecar in zip(manifest['datasets'], sidecars):
        checks = {
            'DATA_BINDING': sidecar['data_file'] == dataset['data'],
            'METADATA_IDENTITY': (sidecar['dataset_id'] == dataset['id']
                                  and sidecar['role'] == dataset['role']
                                  and sidecar['metadata'] == dataset['metadata']
                                  and sidecar['summary'] == dataset['summary']),
            'PROGRAM_QC': qc_results['decision'] == 'PASS' and qc_by_id.get(dataset['id'], {}).get('decision') == 'PASS',
            'PERMISSION_PRESERVATION': (sidecar.get('human_prediction_allowed') is False
                                        and sidecar.get('release_authority') == 'SEPARATE_SIGNED_HANDOFF'
                                        and not manifest.get('scientific_release')),
        }
        failed = [key for key, passed in checks.items() if not passed]
        findings = [{'code': 'METADATA_PROGRAM_CHECK_FAILED', 'affected_id': dataset['id'],
                     'reason': ', '.join(failed), 'needed_material': 'Repair the affected bindings or execution evidence.',
                     'required_by': 'BEFORE_EDA', 'severity': 'BLOCK'}] if failed else []
        results.append({'dataset_id': dataset['id'], 'metadata_ref': copy.deepcopy(dataset['metadata_file']),
                        'review': {'executor': 'HOST_PROGRAM', 'decision': 'REVISE' if failed else 'PASS',
                                   'checks': [{'id': key, 'decision': 'PASS' if passed else 'REVISE',
                                               'reason': 'Mechanical binding/preservation check only.'}
                                              for key, passed in checks.items()], 'findings': findings}})
    return results
