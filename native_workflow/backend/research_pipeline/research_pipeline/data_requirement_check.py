"""Evidence contracts and deterministic aggregation for input coverage, not PK fits."""
import json
import math

from ctxcomp.schemas import S, arr, enum, obj
from .common import PipelineError

VERSION = '1.4.0'
EVIDENCE = obj(source=S, quote=S)
CRITERION = obj(id=S, status=enum('SUPPORTED', 'PARTIAL', 'MISSING', 'CONFLICT', 'UNRESOLVED', 'DEFERRED'),
                evidence=arr(EVIDENCE), reason=S, needed_material=S)
PLAN = obj(producer_task=S, output=S, evidence=arr(EVIDENCE, 1))
MATCH = obj(requirement_id=S, status=enum('AVAILABLE_CANDIDATE', 'MISSING', 'UNRESOLVED', 'DEFERRED'),
            source_ids=arr(), reason=S, needed_material=S, criteria=arr(CRITERION, 1),
            deferred_outputs=arr(PLAN))
INSTRUCTIONS = (
    'Use the supplied criterion plan for each requirement; return every criterion exactly once. '
    'FULL_REQUIREMENT assesses the complete meaning, not just presence of its fields. '
    'FIELD checks cover declared fields; SCOPE_ALIGNMENT checks the relevant drug/analyte, '
    'species/system, matrix, dosing, units, time window, record level, observed/reported/predicted '
    'status and free/total basis together, without inventing absent joins or requiring irrelevant dimensions. '
    'CONDITION checks preserve applicability and exceptions. Do not invent acceptance thresholds. '
    'Use only exact quotes from evidence_catalog and the allowed sources listed for this requirement. '
    'Metadata/header presence alone is not observation evidence. Entries with origin REVIEW_SAMPLE are original body cells the labels did not cite, '
    'chosen by fixed rules (first and last body rows, rows with non-numeric values in numeric columns); check them for counterevidence such as BLQ, missing or text values. COMPUTED entries are host-computed column summaries '
    '(non-empty count, numeric minimum and maximum, distinct non-numeric markers) of labelled columns; cite them for scope alignment such as '
    'time window or sample counts, never as body evidence, independent animals or precision. Formula cells are counted, not evaluated. For DATA, a supported/partial '
    'FULL_REQUIREMENT needs original source content; source-backed literature reports remain reported '
    'estimates, not recalculated or qualified results. Missing means not found in the reviewed scope. '
    'If coverage is incomplete or an answer requires calculation, use UNRESOLVED and identify the next task. '
    'Conflicting evidence must remain CONFLICT; never choose a convenient source silently. '
    'DEFERRED requires a documented producer task/output supported by main/rule evidence; it is not '
    'a substitute for missing source data. The producing task and output are labels, not instructions to execute. '
    'A missing current prerequisite cannot be deferred. Do not count candidate species as qualified '
    'for a parameter or use rows as independent animals. Compute no NCA, fit, PD target or PTA here. '
    'Host aggregation: any CONFLICT -> CONFLICT; all SUPPORTED -> AVAILABLE_CANDIDATE; '
    'only SUPPORTED/DEFERRED with at least one DEFERRED -> DEFERRED; otherwise any SUPPORTED/PARTIAL '
    '-> PARTIAL; otherwise any UNRESOLVED/DEFERRED -> UNRESOLVED; otherwise MISSING. '
    'For the compatibility status, map PARTIAL/CONFLICT to UNRESOLVED. '
    'source_ids must equal the union of criterion evidence source IDs. '
    'PASS means the input assessment is coherent; it does not require all later inputs to exist. '
    'Explain gaps by task, needed material and phase, keeping independent branches available.'
)


def fail(message):
    raise PipelineError('DATA_REQUIREMENT_EVIDENCE_INVALID', message)


def criterion_plan(need):
    result = [{'id': 'FULL_REQUIREMENT', 'description': need['description']}]
    result += [{'id': f'FIELD_{i:03d}', 'description': value}
               for i, value in enumerate(need['fields'], 1)]
    result += [{'id': 'SCOPE_ALIGNMENT', 'description': 'Evidence belongs to the requested scientific context and data level.'}]
    result += [{'id': f'CONDITION_{i:03d}', 'description': value}
               for i, value in enumerate(need.get('conditions', []), 1)]
    return result


def numeric(value):
    """A number, or text that reads as one finite number (CSV cells are text); anything else is None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        number = float(str(value).strip())
    except ValueError:
        return None
    return number if math.isfinite(number) else None


SAMPLE_EDGE_ROWS = 3  # Uncited rows from the start and the end of each table body.
SAMPLE_MARKED_ROWS = 20  # Uncited rows with a non-numeric value in a numeric column.
NUMERIC_MEANINGS = {'TIME', 'CONCENTRATION', 'DOSE', 'RESPONSE', 'MIC', 'BINDING', 'URINE_VOLUME', 'URINE_AMOUNT',
                    'PARAMETER_VALUE', 'SUMMARY_STATISTIC'}


def review_rows(item, label, cells):
    """R2: body rows chosen by fixed rules, so review can see more than the cells the labels cited."""
    from openpyxl.utils.cell import get_column_letter
    region = item['region']; rows = {}
    for key, c in cells.items():
        if region['header_row'] < c['row'] <= region['end_row'] and region['left'] <= c['column'] <= region['right']:
            rows.setdefault(c['row'], {})[key] = c
    numbered = {c['column'] for c in label.get('columns', []) if c.get('column') and c['meaning'] in NUMERIC_MEANINGS}
    order = sorted(rows)
    marked = [r for r in order if any(get_column_letter(c['column']) in numbered and c.get('data_type') != 'f'
              and str(c.get('value') or '').strip() and numeric(c['value']) is None for c in rows[r].values())]
    chosen = dict.fromkeys(order[:SAMPLE_EDGE_ROWS] + order[-SAMPLE_EDGE_ROWS:] + marked[:SAMPLE_MARKED_ROWS])
    return [key for r in chosen for key in rows[r]]


def column_summaries(item, label, cells):
    """DC005: deterministic per-column facts from the snapshot, so review can check scope without the whole table."""
    from openpyxl.utils.cell import column_index_from_string, get_column_letter
    region = item['region']
    cells = [c for c in cells.values() if region['start_row'] <= c['row'] <= region['end_row'] and region['left'] <= c['column'] <= region['right']]
    result = []
    for column in label.get('columns', []):
        if column.get('column'):  # DC004: labels carry the column position.
            index = column_index_from_string(column['column'])
        else:
            heads = [c for c in cells if c['row'] == region['header_row'] and str(c.get('value')) == column['header']]
            if len(heads) != 1:
                continue  # Header not found once in the header row: no summary rather than a guessed column.
            index = heads[0]['column']
        body = [c for c in cells if c['column'] == index and c['row'] > region['header_row']
                and c.get('value') is not None and str(c.get('value')).strip()]
        formulas = [c for c in body if c.get('data_type') == 'f']
        values = [(c['value'], numeric(c['value'])) for c in body if c not in formulas]
        numbers = [n for _, n in values if n is not None]
        text = sorted({str(v) for v, n in values if n is None})
        result.append({'source': 'COMPUTED_BY_HOST_FROM_INTAKE_SNAPSHOT', 'header': column['header'],
                       'column': get_column_letter(index), 'rows': [region['header_row'] + 1, region['end_row']],
                       'non_empty': len(body), 'numeric': len(numbers),
                       'numeric_written_as_text': sum(1 for v, n in values if n is not None and isinstance(v, str)),
                       'numeric_min': min(numbers) if numbers else None, 'numeric_max': max(numbers) if numbers else None,
                       'non_numeric_values': text, 'formula_cells': len(formulas)})
    return result


def build_inputs(req, inv, labeled, sources, content_reader, cell_reader=None):
    """Rehydrate retained citations from verified snapshots; never send whole attachments.

    content_reader gives the text a model reads for each source unit; cell_reader gives table cells as data."""
    catalog = {key: {'content': value, 'kind': key.split(':', 1)[0].upper(), 'item_id': None}
               for key, value in sources.items() if key.startswith(('main:', 'rule:'))}
    items = {item['id']: item for item in inv['items']}
    access = {a['item_id']: a for a in req['access']}
    coverage = {c['item_id']: c for c in labeled['coverage']}
    labels = {label['item_id']: label for label in labeled['labels']}
    for label in labeled['labels']:
        item_id = label['item_id']
        if item_id not in items or access[item_id]['disposition'] != 'REVIEW_DATA':
            fail('Evidence is not admitted for body review: ' + item_id)
        item = items[item_id]
        original = dict(content_reader(item))
        cells = dict(cell_reader(item)) if item['kind'] == 'TABLE' else {}
        original[item_id] = sources[item_id]
        for span in label['evidence'] + [e for c in label.get('columns', []) + label.get('stated_values', []) for e in c['evidence']]:
            key, quote = span['source'], span['quote']
            if key not in original or not quote.strip() or quote not in original[key]:
                fail('Retained citation does not match original content: ' + key)
            kind = 'SOURCE_CONTENT' if key != item_id else 'DESCRIPTOR'
            if kind == 'SOURCE_CONTENT' and item['kind'] == 'TABLE':
                cell = cells[key]; region = item['region']
                inside = region['start_row'] <= cell['row'] <= region['end_row'] and region['left'] <= cell['column'] <= region['right']
                kind = ('SOURCE_NOTE' if not inside  # Linked notes and footnotes below or beside the table are not body.
                        else 'SOURCE_CONTENT' if cell['row'] > region['header_row']
                        and cell.get('value') is not None and str(cell.get('value')).strip()
                        else 'SOURCE_HEADER')
            catalog[key] = {'content': original[key], 'kind': kind, 'item_id': item_id}
        if item['kind'] == 'TABLE':
            for key in review_rows(item, label, cells):  # Original cells; labels did not choose them.
                if key not in catalog:
                    cell = cells[key]
                    if cell.get('value') is not None and str(cell['value']).strip():
                        catalog[key] = {'content': original[key], 'kind': 'SOURCE_CONTENT', 'item_id': item_id, 'origin': 'REVIEW_SAMPLE'}
            for summary in column_summaries(item, label, cells):
                catalog[item_id + ':column:' + summary['column']] = {
                    'content': json.dumps(summary, ensure_ascii=False), 'kind': 'COMPUTED', 'item_id': item_id}

    plans = []
    for need in req['requirements']:
        assigned = [a for a in req['access'] if need['id'] in a.get('requirement_ids', [])]
        # Labels may acknowledge a potential requirement without establishing fulfillment.
        relevant_items = {a['item_id'] for a in assigned}
        context_ids = {e['source'] for e in need['evidence']}
        context_ids.update('rule:' + key for key in need['rule_ids'])
        for a in assigned:
            context_ids.update('main:' + path for path in a.get('context_paths', []))
        task = next(t for t in req['tasks'] if t['id'] == need['task_id'])
        context_ids.update(e['source'] for e in task['evidence'])
        allowed = [key for key, value in catalog.items()
                   if key in context_ids or value['item_id'] in relevant_items]
        incomplete = [a['item_id'] for a in assigned
                      if a['disposition'] in {'REVIEW_DATA', 'NEEDS_REVIEW'}
                      and (coverage.get(a['item_id'], {}).get('status') != 'BODY_REVIEWED'
                           or a['item_id'] not in labels)]
        plans.append({'requirement_id': need['id'], 'criteria': criterion_plan(need),
                      'allowed_source_ids': allowed, 'assigned_item_ids': sorted(relevant_items),
                      'unresolved_review_items': incomplete,
                      'search_scope': 'Assigned permitted sources only; protected/deferred bodies were not searched.'})
    used = {key for plan in plans for key in plan['allowed_source_ids']}
    return plans, {key: value for key, value in catalog.items() if key in used}


def aggregate(criteria):
    statuses = {c['status'] for c in criteria}
    if 'CONFLICT' in statuses:
        return 'CONFLICT'
    if statuses == {'SUPPORTED'}:
        return 'AVAILABLE_CANDIDATE'
    if 'DEFERRED' in statuses and statuses <= {'SUPPORTED', 'DEFERRED'}:
        return 'DEFERRED'
    if statuses & {'SUPPORTED', 'PARTIAL'}:
        return 'PARTIAL'
    if statuses & {'UNRESOLVED', 'DEFERRED'}:
        return 'UNRESOLVED'
    return 'MISSING'


def validate_match(need, match, plan, catalog):
    expected = [c['id'] for c in plan['criteria']]
    ids = [c['id'] for c in match['criteria']]
    if len(ids) != len(set(ids)) or set(ids) != set(expected):
        fail('Incomplete or duplicated criterion checklist: ' + need['id'])
    cited = set()
    for criterion in match['criteria']:
        for span in criterion['evidence']:
            key = span['source']
            if (key not in plan['allowed_source_ids'] or key not in catalog
                    or not span['quote'].strip() or span['quote'] not in catalog[key]['content']):
                fail('Invalid or unassigned evidence for ' + need['id'] + ': ' + key)
            cited.add(key)
        if criterion['status'] in {'SUPPORTED', 'PARTIAL', 'CONFLICT'} and not criterion['evidence']:
            fail('A positive/partial/conflicting criterion needs source evidence: ' + criterion['id'])
        if criterion['status'] != 'SUPPORTED' and criterion['needed_material'].strip().upper() in {'NONE', 'NOT_FOUND', 'N/A'}:
            fail('An unresolved criterion needs a concrete correction or next action: ' + criterion['id'])
        if (need['kind'] == 'DATA' and criterion['id'] == 'FULL_REQUIREMENT'
                and criterion['status'] in {'SUPPORTED', 'PARTIAL'}
                and not any(catalog[e['source']]['kind'] == 'SOURCE_CONTENT' for e in criterion['evidence'])):
            fail('Data availability requires original body evidence, not a header or descriptor: ' + need['id'])
    if len(match['source_ids']) != len(set(match['source_ids'])) or set(match['source_ids']) != cited:
        fail('Match source IDs must equal the criterion evidence sources: ' + need['id'])
    has_deferred = any(c['status'] == 'DEFERRED' for c in match['criteria'])
    if has_deferred:
        if need['required_by'] == 'BEFORE_QC' and need.get('origin') != 'METHOD_CANDIDATE':
            fail('A current prerequisite cannot be deferred: ' + need['id'])
        if not match['deferred_outputs']:
            fail('Deferred output needs a documented producer and output: ' + need['id'])
    elif match['deferred_outputs']:
        fail('A deferred-output plan must correspond to a deferred criterion: ' + need['id'])
    for output in match['deferred_outputs']:
        if output['producer_task'].strip().upper() in {'NOT_FOUND', 'NONE', 'N/A'} or output['output'].strip().upper() in {'NOT_FOUND', 'NONE', 'N/A'}:
            fail('Deferred-output producer and output must be specified: ' + need['id'])
        for span in output['evidence']:
            key = span['source']
            if (key not in plan['allowed_source_ids'] or key not in catalog
                    or catalog[key]['kind'] not in {'MAIN', 'RULE'} or not span['quote'].strip()
                    or span['quote'] not in catalog[key]['content']):
                fail('Deferred-output plan needs approved context/rule evidence: ' + need['id'])
    coverage = aggregate(match['criteria'])
    if any(c['status'] == 'MISSING' for c in match['criteria']) and plan['unresolved_review_items']:
        fail('Incomplete source review cannot establish missing data: ' + need['id'])
    status = 'UNRESOLVED' if coverage in {'PARTIAL', 'CONFLICT'} else coverage
    if match['status'] != status:
        fail('Declared status disagrees with criterion aggregation for ' + need['id'] + ': expected ' + status)
    if status != 'AVAILABLE_CANDIDATE' and match['needed_material'].strip().upper() in {'NONE', 'NOT_FOUND', 'N/A'}:
        fail('A requirement gap needs an actionable summary: ' + need['id'])
    return {'requirement_id': need['id'], 'task_id': need['task_id'], 'required_by': need['required_by'],
            'origin': need['origin'], 'coverage_status': coverage, 'status': status,
            'source_ids': match['source_ids'], 'criteria': match['criteria'],
            'deferred_outputs': match['deferred_outputs'], 'reason': match['reason'],
            'needed_material': match['needed_material'], 'search_scope': plan['search_scope'],
            'current_prerequisite_gap': status != 'AVAILABLE_CANDIDATE'
                and need['required_by'] == 'BEFORE_QC' and need['origin'] == 'PROJECT_EXPLICIT'}


def task_summaries(tasks, rows):
    result = []
    for task in tasks:
        selected = [r for r in rows if r['task_id'] == task['id']]
        result.append({'task_id': task['id'],
                       'input_coverage': {key: [r['requirement_id'] for r in selected if r['coverage_status'] == key]
                                          for key in ['AVAILABLE_CANDIDATE', 'PARTIAL', 'MISSING', 'CONFLICT', 'UNRESOLVED', 'DEFERRED']},
                       'current_prerequisite_gaps': [r['requirement_id'] for r in selected if r['current_prerequisite_gap']],
                       'requirements_assessed': len(selected),
                       'precision_sufficiency': 'NOT_ASSESSED', 'fit_ready': False})
    return result
