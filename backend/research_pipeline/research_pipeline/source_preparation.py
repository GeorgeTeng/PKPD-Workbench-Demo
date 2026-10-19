"""B2 source-table extraction from B1 snapshots, before scientific data QC.

Only declared Excel tables, source-title/DOI sections, or explicit ranges define
boundaries. Unsupported layouts stop; blank-row heuristics never imply a table.
"""
import re
from collections import defaultdict
from pathlib import Path
from ctxcomp.intake import verify_intake, file_hash
from .common import PipelineError, read_json, write_json


def field_name(value, index):
    slug = re.sub(r'[^a-z0-9]+', '_', str(value).lower()).strip('_')
    return f'c{index:03d}_' + (slug or 'unnamed')


def ranges_for(sheet, explicit=None):
    from openpyxl.utils.cell import range_boundaries
    if explicit is not None:
        ranges = []
        for spec in explicit:
            left, top, right, bottom = range_boundaries(spec['range'])
            header = spec['header_row']
            if not (1 <= left <= right <= sheet['columns'] and 1 <= top <= header <= bottom <= sheet['rows']):
                raise PipelineError('SOURCE_RANGE', 'Table range/header lies outside the sheet')
            ranges.append({'start_row': top, 'end_row': bottom, 'left': left, 'right': right,
                           'header_row': header, 'title': spec['title'], 'boundary_method': 'EXPLICIT_PLAN'})
    elif sheet['tables']:
        ranges = []
        for table in sheet['tables']:
            left, top, right, bottom = range_boundaries(table['ref'])
            ranges.append({'start_row': top, 'end_row': bottom, 'left': left, 'right': right,
                           'header_row': top, 'title': table['name'], 'boundary_method': 'EXCEL_TABLE'})
    else:
        rows = defaultdict(list)
        for cell in sheet['cells']:
            if cell['value'] is not None:
                rows[cell['row']].append(cell)
        anchors = []
        for row, cells in sorted(rows.items()):
            if len(cells) == 1 and isinstance(cells[0]['value'], str) and re.match(
                    r'^S\d+\s*\|\s*(?:DOI\s+|https?://(?:dx\.)?doi\.org/)10\.',
                    cells[0]['value'], re.I):
                title = rows.get(row - 1, [])
                if len(title) != 1 or not isinstance(title[0]['value'], str):
                    raise PipelineError('AMBIGUOUS_SOURCE_TITLE', f'{sheet["name"]}: row {row}')
                anchors.append((row - 1, title[0]['value']))
        if not anchors:
            raise PipelineError('TABLE_BOUNDARIES_REQUIRED', f'{sheet["name"]}: provide explicit ranges or Excel table definitions')
        ranges = []
        for i, (start, title) in enumerate(anchors):
            end = anchors[i + 1][0] - 1 if i + 1 < len(anchors) else sheet['rows']
            header = next((r for r in range(start + 2, end + 1)
                           if len(rows.get(r, [])) >= 2 and all(isinstance(c['value'], str) for c in rows[r])), None)
            if header is None:
                raise PipelineError('TABLE_HEADER_REQUIRED', title)
            columns = [c['column'] for c in rows[header]]
            ranges.append({'start_row': start, 'end_row': end, 'left': min(columns), 'right': max(columns),
                           'header_row': header, 'title': title, 'boundary_method': 'SOURCE_TITLE_AND_DOI_ANCHOR'})
    for i, a in enumerate(ranges):
        for b in ranges[i + 1:]:
            if not (a['end_row'] < b['start_row'] or b['end_row'] < a['start_row'] or a['right'] < b['left'] or b['right'] < a['left']):
                raise PipelineError('OVERLAPPING_SOURCE_TABLES', sheet['name'])
    return ranges


def value_status(value, cell=None, notes=''):
    if cell and cell.get('data_type') == 'f':
        return 'FORMULA_REQUIRES_REVIEW'
    if cell and cell.get('data_type') == 'e':
        return 'SOURCE_CELL_ERROR'
    if value is None or value == '':
        return 'EMPTY_SLOT'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return 'QUANTIFIED'
    if str(value).strip().upper() in {'<LLOQ', 'BLQ'}:
        return 'BLQ'
    if str(value).strip().lower() == 'no sampling':
        return 'NOT_SAMPLED'
    if value == '*' and 'cannula' in notes.lower():
        return 'MISSING_CANNULA_BLOCKAGE'
    if value == '.':
        return 'MISSING_OR_NOT_APPLICABLE'
    return 'SOURCE_TEXT_REQUIRES_REVIEW'


def normalize_segment(file, sheet, region, table_id):
    from openpyxl.utils.cell import get_column_letter
    lookup = {(c['row'], c['column']): c for c in sheet['cells']}
    left, right, header = region['left'], region['right'], region['header_row']
    headers = [lookup.get((header, c), {}).get('value') for c in range(left, right + 1)]
    if not all(isinstance(h, str) and h.strip() for h in headers) or len(headers) != len(set(headers)):
        raise PipelineError('AMBIGUOUS_HEADER', f'{table_id}: nonempty unique column labels required')
    relevant = [c for c in sheet['cells'] if region['start_row'] <= c['row'] <= region['end_row'] and left <= c['column'] <= right]
    notes = '\n'.join(str(c['value']) for c in relevant if c['row'] < header)
    raw = {'source_file_id': file['id'], 'source_sha256': file['sha256'], 'source_sheet': sheet['name'],
           'region': region, 'cells': relevant, 'merged_ranges': sheet['merged_ranges']}
    wide_pk = headers[0] == 'Time (h)' and all(re.fullmatch(r'(?:Mouse|Rat)\s+\d+', h) for h in headers[1:])
    terminal = headers[0] == 'Group' and all(re.fullmatch(r'Mouse\s+\d+', h) for h in headers[1:])
    kind = ('pk_observations_candidate' if wide_pk else 'terminal_endpoint_candidate' if terminal else
            'static_time_kill_records' if headers == ['ID', 'AMT', 'AMT_CMT', 'TIME', 'Y', 'CENS'] else
            'model_specification_catalog' if 'model_id' in headers else 'source_records')
    records, missing = [], []
    for row in range(header + 1, region['end_row'] + 1):
        if not any((row, col) in lookup for col in range(left, right + 1)):
            continue
        anchor = lookup.get((row, left), {}).get('value')
        if wide_pk and (not isinstance(anchor, (int, float)) or isinstance(anchor, bool)):
            raise PipelineError('NONNUMERIC_TIME_ROW', f'{table_id}: row {row}')
        if wide_pk or terminal:
            for col in range(left + 1, right + 1):
                cell = lookup.get((row, col))
                value = cell['value'] if cell else None
                address = f'{get_column_letter(col)}{row}'
                status = value_status(value, cell, notes)
                record = {'record_id': f'{table_id}_{address}', 'source_file_id': file['id'],
                          'source_sha256': file['sha256'], 'source_sheet': sheet['name'], 'source_cell': address,
                          'source_row': row, 'source_header_cell': f'{get_column_letter(col)}{header}',
                          'source_anchor_cell': f'{get_column_letter(left)}{row}',
                          'source_raw_value': value, 'status': status, 'subject_label': headers[col - left],
                          'subject_id': 'NOT_FOUND', 'identity_status': 'REQUIRES_REVIEW'}
                if wide_pk:
                    record['time_h'] = anchor
                    record['subject_id_candidate'] = table_id + '::' + headers[col - left]
                    if 'concentration mg/L' in notes:
                        record['concentration_mg_L'] = value if status == 'QUANTIFIED' else None
                        record['concentration_unit'] = 'mg/L'
                    else:
                        record['concentration_value'] = value if status == 'QUANTIFIED' else None
                        record['concentration_unit'] = 'NOT_FOUND'
                else:
                    record['group_label'] = anchor
                    record['unit_id_candidate'] = table_id + '::' + str(anchor) + '::' + headers[col - left]
                    record['response_raw'] = value
                records.append(record)
                if status != 'QUANTIFIED':
                    missing.append({'record_id': record['record_id'], 'source_cell': address, 'status': status, 'raw': value})
        else:
            mapping = {field_name(h, i + 1): f'{get_column_letter(left + i)}{row}' for i, h in enumerate(headers)}
            record = {key: lookup.get((row, left + i), {}).get('value') for i, key in enumerate(mapping)}
            record.update(record_id=f'{table_id}_R{row}', source_file_id=file['id'], source_sha256=file['sha256'],
                          source_sheet=sheet['name'], source_row=row, source_cells=mapping)
            if kind == 'static_time_kill_records':
                event = record[field_name('AMT_CMT', 3)]
                record['record_type'] = 'EXPOSURE_EVENT' if event == 2 else 'OBSERVATION' if event == 1 else 'UNRESOLVED'
                record['source_group_key'] = table_id + '::' + str(record[field_name('ID', 1)])
                record['independent_replicate_id'] = 'NOT_FOUND'
            records.append(record)
            for i, key in enumerate(mapping):
                cell = lookup.get((row, left + i))
                if record[key] in (None, '', '.', '<LLOQ') or (cell and cell.get('data_type') in {'f', 'e'}):
                    missing.append({'record_id': record['record_id'], 'source_cell': mapping[key],
                                    'status': value_status(record[key], cell, notes), 'raw': record[key]})
    result = {'table_id': table_id, 'kind': kind, 'title': region['title'], 'source_notes': notes,
              'source_file_id': file['id'], 'source_sha256': file['sha256'], 'source_sheet': sheet['name'],
              'region': region, 'column_map': {field_name(h, i + 1): h for i, h in enumerate(headers)},
              'records': records, 'missingness': missing, 'qc_status': 'PENDING_HUMAN_REVIEW',
              'fit_ready': False, 'independent_animal_count': 'NOT_FOUND'}
    return result, raw


def prepare_sources(manifest_path, output, plan=None):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise PipelineError('RUN_EXISTS', 'Source-preparation output already contains files')
    output.mkdir(parents=True, exist_ok=True)
    result = {'schema_version': '1.0', 'stage': 'B2_SOURCE_PREPARATION', 'status': 'RUNNING',
              'source_manifest': str(Path(manifest_path).resolve()), 'tables': [], 'files': [],
              'errors': [], 'model_execution': 'NOT_RUN', 'released_datasets': []}
    try:
        supplied = read_json(manifest_path)
        # Recognize the handoff here; verify_main enforces supported versions
        # and their complete contracts before any source table is consumed.
        portable_main = 'version' in supplied and 'objective' in supplied
        scoped_qc = supplied.get('module') == 'data_preparation' and 'task_requirements' in supplied and 'assessment' in supplied
        if scoped_qc:
            from .adequacy import check_ref
            from ctxcomp.io import digest
            check_ref(supplied['assessment']); check_ref(supplied['upstream_main'])
            assessment = read_json(supplied['assessment']['path'])
            if not supplied.get('can_enter_qc') or not assessment.get('can_enter_qc'):
                raise PipelineError('QC_GATE_REQUIRED', 'The scoped handoff is not ready for QC')
            for file in supplied['files']: check_ref(file)
            result['source_handoff'] = str(Path(manifest_path).resolve())
            result['context'] = {'task_requirements': supplied['task_requirements'], 'upstream_main': supplied['upstream_main'],
                                 'assessment': supplied['assessment'], 'fit_ready': False}
            manifest = {'files': [{**f, 'original_name': f['name'], 'raw_path': f['path'],
                'handoff_purpose': f['role'], 'role': 'PRIMARY_SOURCE'} for f in supplied['files']],
                'manifest_sha256': digest(supplied['files'])}
        elif portable_main:
            from ctxcomp.handoff import verify_main
            from ctxcomp.io import digest
            from copy import deepcopy
            verify_main(supplied)
            result['source_handoff'] = str(Path(manifest_path).resolve())
            result['context'] = deepcopy(supplied)
            result['context']['data'].pop('files')
            # All checks below use the one main JSON plus its original attachments.
            # B1 logs, snapshots and acceptance records are not downstream inputs.
            manifest = {'files': [{**f, 'original_name': f['name'], 'raw_path': f['path'],
                                   'handoff_purpose': f['role'],
                                   'role': 'REFERENCE_ONLY' if f['role'] == 'REFERENCE_ONLY' else 'PRIMARY_SOURCE'}
                                  for f in supplied['data']['files']],
                        'manifest_sha256': digest(supplied['data']['files'])}
        elif supplied.get('stage') == 'B1_FILE_HANDOFF':
            from ctxcomp.engine import verify_context
            if supplied.get('status') != 'READY_FOR_DATA_PREPARATION':
                raise PipelineError('CONTEXT_NOT_READY', 'Proposal context review must pass before this handoff is consumed')
            verify_context(Path(manifest_path).resolve().parent)
            canonical_handoff = read_json(Path(manifest_path).resolve().parent / 'audit/file_registry.json')
            if supplied != canonical_handoff:
                raise PipelineError('HANDOFF_CHANGED', 'Supplied handoff does not match the verified B1 handoff')
            if not supplied.get('intake_manifest'):
                raise PipelineError('NO_ATTACHMENT_MANIFEST', 'No data attachments were supplied')
            result['source_handoff'] = str(Path(manifest_path).resolve())
            result['context'] = supplied['context']
            manifest_path = supplied['intake_manifest']['path']
            result['source_manifest'] = manifest_path
        if not (portable_main or scoped_qc):
            manifest = verify_intake(manifest_path)
        result['source_manifest_sha256'] = manifest['manifest_sha256']
        root = Path(manifest_path).parent
        plan = plan or {}
        for file in manifest['files']:
            if file['role'] == 'REFERENCE_ONLY':
                result['files'].append({'id': file['id'], 'action': 'RETAINED_REFERENCE_ONLY', 'fit_ready': False})
                continue
            if file.get('handoff_purpose') == 'MODEL_CATALOG':
                result['files'].append({'id': file['id'], 'action': 'ROUTED_TO_LITERATURE_SEARCH',
                                        'raw_path': str((root / file['raw_path']).resolve()),
                                        'sha256': file['sha256'], 'fit_ready': False})
                continue
            if portable_main or scoped_qc:
                if file['kind'] not in {'csv', 'xlsx'}:
                    result['files'].append({'id': file['id'], 'action': 'RETAINED_CONTEXT', 'fit_ready': False})
                    continue
                from ctxcomp.intake import parse_file
                snapshot = parse_file(Path(file['path']))
            else:
                snapshot = read_json(root / file['snapshot_path'])
            if snapshot['kind'] == 'xlsx':
                sheets = snapshot['sheets']
            elif snapshot['kind'] == 'csv':
                rows = snapshot['rows']
                if not rows:
                    raise PipelineError('EMPTY_SOURCE_TABLE', file['id'])
                sheets = [{'name': 'CSV', 'rows': len(rows), 'columns': max(map(len, rows)), 'merged_ranges': [],
                           'tables': [{'name': file['original_name'], 'ref': f'A1:{__import__("openpyxl").utils.get_column_letter(max(map(len, rows)))}{len(rows)}'}],
                           'cells': [{'cell': f'{__import__("openpyxl").utils.get_column_letter(c+1)}{r+1}',
                                      'row': r+1, 'column': c+1, 'value': value, 'data_type': 's'}
                                     for r, row in enumerate(rows) for c, value in enumerate(row)]}]
            else:
                result['files'].append({'id': file['id'], 'action': 'RETAINED_CONTEXT', 'fit_ready': False})
                continue
            for sheet in sheets:
                key = file['id'] + ':' + sheet['name']
                regions = ranges_for(sheet, plan.get(key))
                covered = set()
                for region in regions:
                    tid = f'T{len(result["tables"]) + 1:04d}'
                    table, raw = normalize_segment(file, sheet, region, tid)
                    record_path = 'tables/' + tid + '.records.json'
                    raw_path = 'tables/' + tid + '.source.json'
                    write_json(output / record_path, table)
                    write_json(output / raw_path, raw)
                    result['tables'].append({'id': tid, 'kind': table['kind'], 'title': table['title'],
                                             'source_file_id': file['id'], 'source_sheet': sheet['name'],
                                             'region': region, 'record_count_including_empty_slots': len(table['records']),
                                             'missing_or_nonquantified_cells': len(table['missingness']),
                                             'records_path': record_path, 'sha256': file_hash(output / record_path),
                                             'source_path': raw_path, 'source_sha256': file_hash(output / raw_path),
                                             'fit_ready': False})
                    covered.update(c['cell'] for c in raw['cells'])
                unassigned = [c for c in sheet['cells'] if c['cell'] not in covered]
                write_json(output / 'unassigned' / (file['id'] + '_' + str(sheets.index(sheet) + 1) + '.json'),
                           {'source_file_id': file['id'], 'sheet': sheet['name'], 'cells': unassigned,
                            'reason': 'Outside detected regions; retained, never silently dropped.'})
            result['files'].append({'id': file['id'], 'action': 'SPLIT_INTO_CANDIDATE_TABLES', 'fit_ready': False})
        result['status'] = 'WAITING_FOR_REVIEW'
        result['next'] = 'Confirm table boundaries, sourced metadata, identities and missingness; then submit the selected records and explicit analysis plan to the existing data_preparation QC/release interface.'
        result['index_status'] = 'NO_INDEX_COMPARISON_INPUT_PREPARED'
    except Exception as error:
        result['status'] = 'FAILED'
        result['errors'].append({'code': getattr(error, 'code', 'SOURCE_PREPARATION_ERROR'), 'message': str(error)})
    write_json(output / 'output.json', result)
    return result
