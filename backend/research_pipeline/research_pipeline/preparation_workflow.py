"""Reviewed input -> permission partition -> conservative, source-bound technical QC.

Completion never asserts scientific sufficiency. Restricted source bodies remain
in intake; only locators enter the partition manifest. No LLM edits measurements.
"""
import copy
import csv
import math
import re
from collections import Counter
from pathlib import Path

from .common import PipelineError, read_json, write_json, utcnow
from .adequacy import check_ref, file_ref
from .dataset_metadata import export_dataset
from .source_preparation import ranges_for, normalize_segment, field_name


def approved_inputs(approval_ref):
    from .workflow_canvas import CanvasStore, fingerprint
    check_ref(approval_ref)
    approval = read_json(approval_ref['path']); node = approval['adequacy']
    if not CanvasStore.approved(node) or node['output_signature'] != fingerprint(node['artifacts']):
        raise PipelineError('PREPARATION_APPROVAL_REQUIRED', 'Approve the data assessment before preparing its files.')
    for artifact in node['artifacts']: check_ref(artifact)
    refs = {a['name']: a for a in node['artifacts']}
    report = read_json(refs['adequacy.json']['path'])
    qc = read_json(refs['qc_context.json']['path'])
    if qc['assessment']['sha256'] != refs['adequacy.json']['sha256']:
        raise PipelineError('PREPARATION_INPUT_CHANGED', 'QC handoff and assessment do not match.')
    check_ref(qc['assessment']); check_ref(qc['upstream_main'])
    from .demo_data import validated as valid_demo
    if not valid_demo(report) and (not report.get('llm_review', {}).get('validated') or report.get('llm_review', {}).get('decision') != 'PASS'):
        raise PipelineError('PREPARATION_APPROVAL_REQUIRED', 'The independent adequacy review has not been validated.')
    # Unresolved partition/mapping can be investigated, never silently waived.
    if report['assessment_status'] not in {'SUFFICIENT_FOR_DEFINED_SCOPE', 'NOT_CALCULABLE'}:
        raise PipelineError('PREPARATION_INPUTS_MISSING', 'Inputs are insufficient. Supply the missing data before preparation.')
    for ref in report.get('evidence_refs', []): check_ref(ref)
    for ref in qc['files']: check_ref(ref)
    plan = approval.get('preparation_plan')
    if plan:
        check_ref(plan)
        if read_json(plan['path']).get('adequacy_signature') != node['output_signature']:
            raise PipelineError('PREPARATION_PLAN_STALE', 'The mapping plan belongs to a different approved data assessment.')
    return approval, qc, report


def import_inputs(approval_ref, output):
    check_ref(approval_ref)
    if read_json(approval_ref['path']).get('scope') == 'DATA_ASSESSMENT_REVIEW':
        from .direct_preparation import import_inputs as import_direct
        return import_direct(approval_ref, output)
    approval, qc, report = approved_inputs(approval_ref)
    scope = 'DIAGNOSTIC_PREPARATION_ONLY' if not report['can_enter_qc'] else 'TECHNICAL_QC_ONLY'
    from .demo_data import validated as valid_demo
    if valid_demo(report):
        scope = qc['execution_scope']  # Preserve the exact scope approved at the Human gate.
    value = {**qc, 'approval': approval_ref, 'execution_scope': scope,
             'original_assessment_status': report['assessment_status'],
             'preparation_plan': approval.get('preparation_plan'), 'scientific_release': False}
    write_json(output, value)
    return value


def require_dp_approval(context):
    """A technical DC PASS is not a person's approval to start DP.

    Reuse the Canvas approval snapshot and its exact artifact signature. This
    check runs at the DP entry point as well as on later preparation entry points.
    It never creates, infers or upgrades an approval.
    """
    reference = context.get('approval')
    if not isinstance(reference, dict) or not reference.get('path') or not reference.get('sha256'):
        raise PipelineError('DP_HUMAN_APPROVAL_REQUIRED',
                            'Review and explicitly approve the current Data checkpoint before starting DP.')
    if context.get('schema_version') == 'DIRECT_DP_INPUT_1.0':
        from .direct_preparation import require_approval
        return require_approval(context)
    approval, approved_qc, _ = approved_inputs(reference)
    node = approval['adequacy']
    review = node.get('review') or {}
    if (node.get('requires_human_review') is False or review.get('decision') != 'APPROVE'
            or review.get('confirmed') is not True
            or not isinstance(review.get('reviewer'), str) or not review['reviewer'].strip()
            or not isinstance(review.get('at'), str) or not review['at'].strip()):
        raise PipelineError('DP_HUMAN_APPROVAL_REQUIRED',
                            'DP requires an explicit confirmed human approval with reviewer and timestamp; automatic validation is insufficient.')
    # import_inputs adds execution metadata but must preserve every approved input.
    if any(key not in context or context[key] != value for key, value in approved_qc.items()):
        raise PipelineError('DP_HUMAN_APPROVAL_STALE',
                            'DP inputs differ from the human-reviewed checkpoint. Review and approve the current version.')
    return approval


def issue(code, dataset, reason, needed, severity='BEFORE_MODELING'):
    return {'code': code, 'dataset_id': dataset, 'severity': severity,
            'reason': reason, 'needed_material': needed}


def table_descriptor(sheet, region):
    header_cells = {c['column']: c['value'] for c in sheet['cells'] if c['row'] == region['header_row']}
    headers = [header_cells.get(column) for column in range(region['left'], region['right'] + 1)]
    notes = '\n'.join(str(c['value']) for c in sheet['cells']
                      if region['start_row'] <= c['row'] < region['header_row'])
    return {'sheet': sheet['name'], 'title': region['title'], 'headers': headers, 'source_notes': notes}


def partition(descriptor):
    text = ' '.join([descriptor['sheet'], descriptor['title'], descriptor['source_notes']]).lower()
    headers = ' '.join(map(str, descriptor['headers'])).lower()
    if re.search(r'\bhuman\b|\bpatient\b|\bhealthy volunteer', text.replace('_', ' ')):
        return 'WITHHELD_VALIDATION', 'Human observations/binding and human estimates are reserved for separately authorized validation.'
    if re.search(r'published pk simulation|model.derived|population pk parameter|post.?hoc|bayesian|model estimates|benchmark', text):
        return 'WITHHELD_BENCHMARK', 'Published/model-derived values cannot enter primary estimation or index selection.'
    if re.search(r'exposure summar|parameter summar|pharmacokinetic parameters', text):
        return 'WITHHELD_PERMISSION_REVIEW', 'Summary/parameter provenance and intended use need review before development access.'
    if re.search(r'\b(mouse|mice|murine|rat|rats|rabbit|rabbits|rodent)\b', text) or re.search(r'in.?vitro|time.kill|susceptibility|mic distribution', text):
        return 'DEVELOPMENT_CANDIDATE', 'Source table metadata identifies animal or in-vitro material; scientific use remains pending review.'
    return 'WITHHELD_PERMISSION_REVIEW', 'Scientific destination is unresolved from metadata; the body is not exported.'


def csv_sheet(snapshot):
    from openpyxl.utils.cell import get_column_letter
    rows = snapshot['rows']
    if not rows: raise PipelineError('EMPTY_SOURCE_TABLE', 'CSV has no rows.')
    width = max(map(len, rows))
    return {'name': 'CSV', 'rows': len(rows), 'columns': width, 'merged_ranges': [],
        'tables': [{'name': 'CSV source table', 'ref': f'A1:{get_column_letter(width)}{len(rows)}'}],
        'cells': [{'cell': f'{get_column_letter(c+1)}{r+1}', 'row': r+1, 'column': c+1,
                   'value': v, 'data_type': 's'} for r, row in enumerate(rows) for c, v in enumerate(row)]}


def split_sources(context_path, output):
    from ctxcomp.intake import parse_file
    context = read_json(context_path); approved_inputs(context['approval'])
    plan = read_json(context['preparation_plan']['path']) if context.get('preparation_plan') else {}
    output = Path(output); entries, tables, findings, files = [], [], [], []
    for file in context['files']:
        if file['role'] != 'DATA_CANDIDATE':
            files.append({'id': file['id'], 'action': 'REGISTRY_ONLY', 'sha256': file['sha256']})
            continue
        if file['kind'] not in {'csv', 'xlsx'}:
            findings.append(issue('UNSUPPORTED_DATA_FORMAT', file['id'], 'No table adapter for this registered data format.', 'CSV/XLSX tables and a data dictionary.', 'BEFORE_PREPARATION'))
            continue
        snapshot = parse_file(Path(file['path']))
        sheets = snapshot['sheets'] if snapshot['kind'] == 'xlsx' else [csv_sheet(snapshot)]
        for sheet in sheets:
            explicit = plan.get('ranges', {}).get(file['id'] + ':' + sheet['name'])
            try: regions = ranges_for(sheet, explicit)
            except PipelineError as exc:
                findings.append(issue(exc.code, file['id'] + ':' + sheet['name'], str(exc), 'Explicit nonoverlapping table ranges and header rows in the preparation plan.', 'BEFORE_PREPARATION'))
                entries.append({'file_id': file['id'], 'source_sha256': file['sha256'], 'sheet': sheet['name'],
                                'access': 'WITHHELD_LAYOUT_REVIEW', 'reason': str(exc)})
                continue
            covered = set()
            for region in regions:
                tid = f'T{len(entries)+1:04d}'; desc = table_descriptor(sheet, region)
                access, reason = partition(desc)
                entry = {'id': tid, 'file_id': file['id'], 'source_sha256': file['sha256'],
                         'sheet': sheet['name'], 'title': region['title'], 'region': region,
                         'access': access, 'reason': reason, 'body_exported': access == 'DEVELOPMENT_CANDIDATE'}
                entries.append(entry)
                covered.update(c['cell'] for c in sheet['cells'] if region['start_row'] <= c['row'] <= region['end_row']
                               and region['left'] <= c['column'] <= region['right'])
                if access != 'DEVELOPMENT_CANDIDATE': continue
                table, raw = normalize_segment(file, sheet, region, tid)
                record_path = write_json(output / 'tables' / (tid + '.records.json'), table)
                raw_path = write_json(output / 'tables' / (tid + '.source.json'), raw)
                tables.append({'id': tid, 'title': table['title'], 'kind': table['kind'],
                    'records_path': str(record_path.relative_to(output)), 'sha256': file_ref(record_path)['sha256'],
                    'raw': file_ref(raw_path), 'source_ref': file_ref(file['path'])})
            # Never export unassigned body cells: they may contain held-out values.
            unassigned = [c['cell'] for c in sheet['cells'] if c['cell'] not in covered]
            if unassigned:
                entries.append({'file_id': file['id'], 'source_sha256': file['sha256'], 'sheet': sheet['name'],
                    'access': 'WITHHELD_UNASSIGNED', 'body_exported': False, 'cell_locators': unassigned,
                    'reason': 'Outside detected table boundaries; retained in original source, never silently discarded.'})
        check_ref(file)
    manifest = {'schema_version': '1.0', 'entries': entries, 'files': files,
                'release_policy': 'No restricted body export. Later validation requires a separate authorized release after model freeze.',
                'enforcement': 'Workflow artifact isolation, not an operating-system access sandbox.'}
    write_json(output / 'partition_manifest.json', manifest)
    result = {'schema_version': '1.0', 'status': 'SPLIT_FOR_TECHNICAL_QC', 'tables': tables,
              'findings': findings, 'partition_manifest': file_ref(output / 'partition_manifest.json'),
              'fit_ready': False, 'released_datasets': []}
    write_json(output / 'output.json', result)
    return result


def numeric(value):
    if isinstance(value, bool): return None
    try: result = float(value)
    except (ValueError, TypeError): return None
    return result if math.isfinite(result) else None


def unit_mapping(header, target):
    h = str(header).lower().replace('μ', 'u').replace('µ', 'u').replace(' ', '')
    # Match the complete unit expression, never a concentration substring in AUC or a slope.
    unit = re.search(r'(?:\(([^()]*)\)|\[([^\[\]]*)\])$', h)
    expression = next((value for value in unit.groups() if value is not None), '') if unit else h
    factors = {'time_h': {'h': 1, 'min': 1/60, 's': 1/3600},
               'concentration_mg_L': {'mg/l': 1, 'ug/ml': 1, 'ng/ml': .001, 'ug/l': .001}}
    return factors.get(target, {}).get(expression)


def metadata_for(table):
    text = (table['title'] + '\n' + table['source_notes']).lower()
    species = [v for v, pattern in [('mouse', r'\bmouse\b|\bmice\b|\bmurine\b'), ('rat', r'\brat\b|\brats\b'),
                                   ('rabbit', r'\brabbit\b|\brabbits\b')] if re.search(pattern, text)]
    # Prefer the table title/explicit matrix declaration over other matrices
    # mentioned in shared assay notes (e.g. plasma binding in an ELF table).
    matrix_text = table['title'].lower().replace('whole-lung','whole lung')
    matrices = [m for m in ['plasma', 'serum', 'elf', 'whole lung'] if m in matrix_text]
    headers = ' '.join(table['column_map'].values()).lower()
    role = 'SOURCE_TABLE'
    if table['kind'] == 'pk_observations_candidate' or ('time' in headers and ('concentration' in text or bool(matrices))): role = 'PK_OBSERVATIONS'
    if table['kind'] == 'static_time_kill_records': role = 'IN_VITRO_TIME_KILL'
    elif 'binding' in table['title'].lower(): role = 'BINDING'
    elif 'susceptibility' in table['title'].lower() or 'mic distribution' in table['title'].lower(): role = 'MIC'
    elif 'regimen' in table['title'].lower() or ('dose' in headers and 'interval' in headers and 'cfu' not in headers): role = 'DOSING'
    elif table['kind'] == 'terminal_endpoint_candidate' or 'cfu' in headers or 'endpoint' in headers: role = 'PD_OBSERVATIONS'
    level = ('UNVERIFIED_OBSERVATION_IDENTITY' if table['kind'] in {'pk_observations_candidate','terminal_endpoint_candidate'}
             else 'DIGITIZED_GROUP_SUMMARY' if 'digitiz' in text and re.search(r'\bmean\b',text)
             else 'GROUP_SUMMARY' if re.search(r'\bmean\b',text) else 'UNVERIFIED_OBSERVATION_IDENTITY')
    return {'role': role, 'species': species[0] if len(species) == 1 else 'MIXED_OR_NOT_FOUND',
        'matrix': matrices[0] if len(matrices) == 1 else 'MIXED_OR_NOT_FOUND',
        'exposure_basis': 'NOT_FOUND', 'record_level': level,
        'independent_animal_count': 'NOT_ESTABLISHED', 'route': 'NOT_FOUND', 'dose': 'NOT_FOUND',
        'endpoint_window': 'NOT_FOUND', 'drug': 'polymyxin B' if re.search(r'polymyxin b|\bpmb\b', text) else 'NOT_FOUND',
        'source_table': {'title': table['title'], 'sheet': table['source_sheet'], 'region': table['region'],
                         'notes': table['source_notes'], 'column_map': table['column_map']},
        'classification_status': 'CANDIDATE_PENDING_REVIEW', 'permission': 'DEVELOPMENT_CANDIDATE'}


def clean_table(table, raw, mapping=None):
    """Preserve source values. Transformations are explicit and recorded per cell."""
    mapping = mapping or {}; tid = table['table_id']; metadata = metadata_for(table)
    accepted, quarantine, changes, findings = [], [], [], []
    headers = table['column_map']; selected = {}
    for target in ['time_h', 'concentration_mg_L']:
        label = mapping.get('columns', {}).get(target)
        candidates = [k for k, h in headers.items() if h == label] if label else [k for k, h in headers.items()
            if (re.match(r'^time\s*\(', h, re.I) if target == 'time_h' else
                (re.search(r'^(mean\s+)?(plasma\s+)?concentration\s*\(', h, re.I)
                 or (metadata['role'] == 'PK_OBSERVATIONS' and re.match(r'^Mean\s*\(', h, re.I))))]
        if len(candidates) == 1:
            key = candidates[0]; factor = unit_mapping(headers[key], target)
            if factor is not None: selected[target] = (key, factor)
            elif label: raise PipelineError('QC_MAPPING_UNIT_UNKNOWN', f'{tid}: {label} has no supported explicit unit for {target}.')
        elif label: raise PipelineError('QC_MAPPING_COLUMN_UNKNOWN', f'{tid}: expected one exact header for {label}.')
    cells = {c['cell']: c for c in raw['cells']}
    signatures = set()
    for original in table['records']:
        row = copy.deepcopy(original); reasons = []
        source_keys = list(headers) if 'source_cells' in row else ['source_raw_value']
        for key in source_keys:
            value = row.get(key)
            if isinstance(value, str) and value != value.strip():
                changes.append({'record_id': row['record_id'], 'field': key, 'action': 'TRIM_OUTER_WHITESPACE', 'before': value, 'after': value.strip()})
                row[key] = value.strip()
        for target, (key, factor) in selected.items():
            if key not in row: continue
            cell = cells.get(row.get('source_cells', {}).get(key), {})
            value = numeric(row[key]) if cell.get('data_type') not in {'e', 'f'} else None
            if value is None: reasons.append('NONQUANTIFIED_' + target.upper())
            elif target == 'concentration_mg_L' and value < 0: reasons.append('NEGATIVE_CONCENTRATION')
            else:
                row[target] = value * factor
                changes.append({'record_id': row['record_id'], 'field': target, 'source_field': key,
                    'action': 'EXPLICIT_UNIT_CONVERSION', 'factor': factor, 'source_header': headers[key]})
        if table['kind'] in {'pk_observations_candidate', 'terminal_endpoint_candidate'}:
            if row.get('status') != 'QUANTIFIED': reasons.append(row.get('status', 'UNRESOLVED'))
            value = numeric(row.get('source_raw_value'))
            if value is None and not reasons: reasons.append('NONFINITE_OR_NONNUMERIC_VALUE')
            if table['kind'] == 'pk_observations_candidate':
                if numeric(row.get('time_h')) is None: reasons.append('NONFINITE_TIME')
                if value is not None and value < 0: reasons.append('NEGATIVE_CONCENTRATION')
                if row.get('concentration_unit') == 'NOT_FOUND': reasons.append('CONCENTRATION_UNIT_NOT_FOUND')
        else:
            for key in source_keys:
                cell = cells.get(row.get('source_cells', {}).get(key), {})
                if cell.get('data_type') in {'e', 'f'}: reasons.append('SOURCE_CELL_ERROR' if cell['data_type'] == 'e' else 'FORMULA_REQUIRES_REVIEW')
                if isinstance(row.get(key), float) and not math.isfinite(row[key]): reasons.append('NONFINITE_VALUE')
        if table['kind'] == 'static_time_kill_records':
            event, y, cens = (field_name(k, i) for k, i in [('AMT_CMT',3),('Y',5),('CENS',6)])
            event_value = numeric(row[event]); row['record_type'] = 'EXPOSURE_EVENT' if event_value == 2 else 'OBSERVATION' if event_value == 1 else 'UNRESOLVED'
            if event_value == 1:
                if numeric(row[y]) is None: reasons.append('MISSING_RESPONSE')
                if numeric(row[cens]) == 1: reasons.append('CENSORED_RESPONSE')
                elif numeric(row[cens]) != 0: reasons.append('CENSOR_FLAG_UNRESOLVED')
            elif event_value == 2:
                if numeric(row[field_name('AMT',2)]) is None: reasons.append('MISSING_EXPOSURE')
            else: reasons.append('EVENT_TYPE_UNRESOLVED')
            if numeric(row[field_name('TIME',4)]) is None: reasons.append('MISSING_TIME')
        import json
        signature = json.dumps([row.get(k) for k in source_keys], sort_keys=True, ensure_ascii=False)
        # Equal concentrations in different animals/times are not duplicate records.
        identity = (signature, row.get('time_h'), row.get('subject_label'), row.get('group_label'))
        if identity in signatures: row['duplicate_value_pattern'] = True
        signatures.add(identity)
        row['qc_status'] = 'QUARANTINED' if reasons else 'TECHNICALLY_RETAINED'
        row['qc_reasons'] = sorted(set(reasons))
        (quarantine if reasons else accepted).append(row)
    if table['kind'] == 'pk_observations_candidate':
        findings.append(issue('ANIMAL_IDENTITY_UNCONFIRMED', tid, 'Column labels do not establish repeated measures from the same animal.', 'Source-confirmed animal identifiers and sampling design before individual/NLME fitting.'))
    if metadata['role'] == 'PK_OBSERVATIONS':
        findings.append(issue('PK_DESIGN_REVIEW', tid, 'Dosing, route, matrix, total/free basis and sampling design require source-qualified mapping.', 'Dose and infusion records, units, matrix, LLOQ, body weight and experimental-unit definitions.'))
    if metadata['role'] in {'BINDING','MIC','PD_OBSERVATIONS','IN_VITRO_TIME_KILL','DOSING','SOURCE_TABLE'}:
        findings.append(issue('SEMANTIC_MAPPING_REVIEW', tid, 'Technical extraction retains source columns; no cross-table scientific linkage is assumed.', 'Review the data dictionary, species/strain, matrix, endpoint window, units and permitted joins.'))
    if quarantine:
        findings.append(issue('QUARANTINED_VALUES', tid, f'{len(quarantine)} records are excluded from numeric candidates; original values are retained.', 'Confirm missingness/censoring handling and supply corrections or LLOQ where documented.'))
    if any(r.get('duplicate_value_pattern') for r in accepted + quarantine):
        findings.append(issue('REPEATED_VALUE_PATTERN', tid, 'Repeated source value patterns are flagged and retained; biological duplicates are unproven.', 'Confirm duplicate records versus genuine replicates; no automatic averaging or deletion.'))
    readiness = 'CANDIDATE_FOR_DESCRIPTIVE_EDA' if accepted else 'NO_USABLE_NUMERIC_CANDIDATE'
    if metadata['role'] == 'SOURCE_TABLE': readiness = 'SUPPORTING_SOURCE_TABLE_ONLY'
    if metadata['role'] == 'PK_OBSERVATIONS' and not any(numeric(r.get('concentration_mg_L')) is not None and numeric(r.get('time_h')) is not None for r in accepted):
        readiness = 'MAPPING_REQUIRED'
        findings.append(issue('PK_NUMERIC_MAPPING_REQUIRED',tid,'No source-qualified time/concentration pair is normalized for this table.',
            'Map a compatible concentration header with an explicit unit; mixed matrices and mean±SD fields need a separate declared transformation.'))
    summary = {'source_records': len(table['records']), 'retained_records': len(accepted), 'quarantined_records': len(quarantine),
               'quarantine_reasons': dict(Counter(k for r in quarantine for k in r['qc_reasons'])),
               'source_missingness_cells': len(table['missingness']), 'independent_animals': 'NOT_ESTABLISHED'}
    metadata['normalized_fields'] = {k: {'source_header': headers[v[0]], 'factor': v[1]} for k,v in selected.items()}
    return {'id': tid, 'records': accepted, 'quarantine': quarantine, 'metadata': metadata,
            'summary': summary, 'readiness': readiness}, changes, findings


def prepare(context_path, sources_path, output):
    context = read_json(context_path); _, _, assessment = approved_inputs(context['approval'])
    source = read_json(sources_path); output = Path(output)
    plan = read_json(context['preparation_plan']['path']) if context.get('preparation_plan') else {}
    datasets, changes, findings, dictionary, template = [], [], list(source['findings']), {}, {}
    known = {t['id'] for t in source['tables']}
    if set(plan.get('tables', {})) - known:
        raise PipelineError('QC_MAPPING_TABLE_UNKNOWN', 'Preparation plan names a missing or restricted table.')
    for item in source['tables']:
        table_path = Path(sources_path).parent / item['records_path']; check_ref({'path':str(table_path),'sha256':item['sha256']})
        table = read_json(table_path); check_ref(item['raw'])
        group, log, issues = clean_table(table, read_json(item['raw']['path']), plan.get('tables', {}).get(item['id']))
        result = export_dataset(output / 'normalized', group, [file_ref(table_path), item['raw']])
        result['json'] = result['data']; result['metadata'] = group['metadata']; datasets.append(result)
        changes += log; findings += issues
        dictionary[item['id']] = {'source_columns': table['column_map'], 'missingness': table['missingness'],
                                  'normalized_fields': group['metadata']['normalized_fields']}
        template[item['id']] = {'columns': {}, 'available_headers': list(table['column_map'].values())}
    partition_report = read_json(source['partition_manifest']['path'])
    count = Counter(e['access'] for e in partition_report['entries'])
    findings += [issue('SCIENTIFIC_PRECISION_NOT_ESTABLISHED', 'ALL', 'Record/column counts do not establish independent sample size, parameter precision or predictive reliability.', 'An estimand-specific precision/design plan, independence definition and suitable variance evidence.')]
    findings += [issue('INDEX_SCOPE_PENDING_INPUTS', 'INDEX', 'Only fAUC/MIC, fCmax/MIC and fT>MIC are in scope. No index values or best-index fit are calculated by QC.', 'Species/matrix-matched free exposure, MIC and integration window; matched PD responses are needed later for R²/AIC-based comparison.')]
    for gap in assessment.get('why_cannot_pass', []):
        findings.append(issue('UPSTREAM_REQUIREMENT_REVIEW', gap.get('requirement_id','ALL'), gap['reason'], gap.get('needed_material','Review the upstream requirement.')))
    write_json(output / 'partition_manifest.json', partition_report)
    write_json(output / 'data_dictionary.json', dictionary)
    write_json(output / 'cleaning_log.json', {'changes': changes, 'no_imputation': True, 'no_duplicate_averaging': True})
    write_json(output / 'preparation_plan.template.json', {'schema_version':'1.0', 'ranges':{}, 'tables':template,
        'help':'Optional exact source-header mappings: time_h and concentration_mg_L only. Units must be explicit in headers. No science/permission override.'})
    manifest = {'schema_version':'1.0','datasets':datasets,'scientific_release':False, 'review_status':'PENDING'}
    write_json(output / 'normalization_manifest.json', manifest)
    for target, roles in [('eda',None),('pk',['PK_OBSERVATIONS','DOSING']),('index',['MIC','BINDING','PD_OBSERVATIONS','DOSING','IN_VITRO_TIME_KILL'])]:
        selected = [d for d in datasets if roles is None or d['role'] in roles]
        handoff = {'schema_version':'1.0','module':target,'status':'PENDING_HUMAN_REVIEW','scientific_release':False,
            'fit_ready':False, 'files':[{k:d[k] for k in ['id','role','data','csv','metadata_file','quarantine','readiness']} for d in selected],
            'task_requirements':[r for r in context['task_requirements'] if target=='eda' or target in str(r).lower()],
            'assumptions':['No exposure conversion using unreviewed binding; no inferred joins; no human/benchmark body values.'],
            'unknowns':[f for f in findings if f['dataset_id'] in {d['id'] for d in selected} or f['dataset_id'] in {'ALL',target.upper()}]}
        if target == 'index': handoff['candidate_indices'] = ['fAUC/MIC','fCmax/MIC','fT>MIC']
        write_json(output / 'handoffs' / (target+'_context.json'), handoff)
    report = {'schema_version':'1.0','module':'data_preparation','created_at':utcnow(), 'status':'WAITING_FOR_HUMAN_REVIEW',
        'execution_scope':context['execution_scope'],'original_assessment_status':context['original_assessment_status'],
        'cleaning_complete':not source['findings'], 'fit_ready':False,'scientific_release':False, 'released_datasets':[],
        'sample_size_status':'NOT_CALCULABLE','human_prediction_validated':False,'requires_human_review':True,
        'summary':{'development_tables':len(datasets),'partitions':dict(count),
            'source_records':sum(d['summary']['source_records'] for d in datasets),
            'retained_records':sum(d['summary']['retained_records'] for d in datasets),
            'quarantined_records':sum(d['summary']['quarantined_records'] for d in datasets)},
        'findings':findings,'why_cannot_pass':findings,'missing_materials':[{'code':f['code'],'dataset_id':f['dataset_id'],'needed_material':f['needed_material']} for f in findings],
        'normalization_manifest':file_ref(output/'normalization_manifest.json'), 'partition_manifest':file_ref(output/'partition_manifest.json'),
        'upstream':{'approval':context['approval'],'assessment':context['assessment']},
        'review_scope':'Accept source partition and technical processing for descriptive EDA only. This signature cannot authorize fitting or validation.',
        'next_api':'/ui-api/workflow/sessions/{session_id}/preparation-plan',
        'limitations':['Source notes are retained evidence, not independent verification of paper bodies.',
            'Generic source columns remain unconverted where meaning or units are unresolved.',
            'Human binding/PK remains withheld until a separately authorized final-validation release.']}
    write_json(output/'main.json',report)
    write_json(output/'data_report.json',report)
    with (output/'issues.csv').open('w',encoding='utf-8-sig',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=['code','dataset_id','severity','reason','needed_material']);writer.writeheader();writer.writerows(findings)
    (output/'report.md').write_text('# Data preparation & QC\n\nTechnical preparation complete; scientific acceptance is pending.\n\n'
        +str(report['summary'])+'\n\n## Why modeling is not released\n\n'+'\n'.join('- '+f['dataset_id']+': '+f['reason']+' Needed: '+f['needed_material'] for f in findings)+'\n',encoding='utf-8')
    approved_inputs(context['approval'])
    return report
