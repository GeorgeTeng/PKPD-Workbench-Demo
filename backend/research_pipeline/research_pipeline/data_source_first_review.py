"""Bounded independent review around the original Data coverage validators.

Partitioning changes transport only. Original criterion, condition, source and
ledger validators still decide acceptance; a completed run is not a release.
"""
import copy
import json
from functools import partial
from pathlib import Path
from types import SimpleNamespace

from ctxcomp.io import digest, leaves
from . import data_agents as d
from . import data_requirement_check as coverage
from . import data_source_first_workflow as sf
from .adequacy import file_ref, check_ref
from .common import read_json, write_json, utcnow
from .data_test_workflow import embedded_projection

SOFT_BUDGET = 645_000  # Leaves room for the exact policy/schema/governance envelope.
SEMANTIC_RULE_FIELDS = {'id', 'kind', 'text', 'conditions', 'exceptions', 'scope',
    'requirement', 'usage', 'stages', 'context_path', 'projection_version'}


def _source_ids(value):
    if isinstance(value, dict):
        if set(value) >= {'source', 'quote'}:
            yield value['source']
        for child in value.values():
            yield from _source_ids(child)
    elif isinstance(value, list):
        for child in value:
            yield from _source_ids(child)


def _dedup_evidence(value, catalog):
    """Retain field-to-source relationships; exact original text appears once in catalog.

    The full immutable evidence spans remain in the input artifact and host
    validators. A source without a displayed original text is never compacted.
    """
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            if key == 'evidence' and isinstance(child, list) and all(
                    e['source'] in catalog and e['quote'].strip()
                    and e['quote'] in catalog[e['source']].get('content', '') for e in child):
                result['evidence_source_ids'] = list(dict.fromkeys(e['source'] for e in child))
            else:
                result[key] = _dedup_evidence(child, catalog)
        return result
    if isinstance(value, list):
        return [_dedup_evidence(x, catalog) for x in value]
    return value


def _row_table(records):
    """Lossless repeated-key removal; heterogeneous records retain their dictionaries."""
    if not records or any(set(row) != set(records[0]) for row in records):
        return records
    fields = list(records[0])
    return {'encoding': 'ROWS_V1', 'fields': fields,
            'rows': [[row[key] for key in fields] for row in records]}


def _pack_transport(part):
    """Compact storage keys without dropping a source, fact, condition or finding."""
    catalog = part['evidence_catalog']; groups = {}
    for source, entry in catalog.items():
        item = entry.get('item_id'); prefix = item if item and source.startswith(item) else ''
        group = groups.setdefault((prefix, item), {'source_prefix': prefix, 'item_id': item, 'rows': []})
        # Preserve every entry field, including future provenance metadata.
        rest = {k: v for k, v in entry.items() if k not in {'content', 'kind', 'item_id', 'origin'}}
        group['rows'].append([source[len(prefix):], entry['kind'], entry['content'], entry.get('origin'), rest])
    part['evidence_catalog'] = {'encoding': 'GROUPED_SOURCE_ROWS_V1',
        'fields': ['source_suffix', 'kind', 'content', 'origin', 'other_metadata'], 'groups': list(groups.values())}
    catalog_ids = set(catalog)
    for plan in part['criterion_plans']:
        allowed = set(plan['allowed_source_ids'])
        compact = {'encoding': 'CATALOG_SET_V1', 'except': sorted(catalog_ids - allowed),
                   'plus': sorted(allowed - catalog_ids)}
        if _size(compact) < _size(plan['allowed_source_ids']):
            plan['allowed_source_ids'] = compact
    for label in part['data_labels']['labels']:
        label['columns'] = _row_table(label.get('columns', []))
    part['data_labels']['labels'] = _row_table(part['data_labels']['labels'])
    part['data_labels']['stated_values'] = _row_table(part['data_labels']['stated_values'])
    part['data_labels']['findings'] = _row_table(part['data_labels']['findings'])
    part['requirements']['findings'] = _row_table(part['requirements']['findings'])
    # The frozen profile object already contains these same exact method source records.
    knowledge = part.get('method_knowledge') or {}
    profile_sources = {'method:' + p['id']: json.dumps(p, ensure_ascii=False)
                       for p in knowledge.get('profiles', [])}
    part['context_sources'] = {k: v for k, v in part['context_sources'].items()
                              if not (k in profile_sources and profile_sources[k] == v)}
    part['instructions'] += (
        '\nTRANSPORT TABLES ARE LOSSLESS: evidence_catalog GROUPED_SOURCE_ROWS_V1 groups contain source_prefix and item_id; '
        'each row follows fields, and its exact citation ID is source_prefix + source_suffix. Content is the unchanged original text. '
        'ROWS_V1 uses the listed fields in each row, preserving every value. CATALOG_SET_V1 means all displayed catalog source IDs '
        'except the listed IDs, plus the listed extra IDs. This is the exact allowed set, not permission to use additional sources. '
        'method:MPxxx sources are the matching complete profile records in method_knowledge, with unchanged individual field text. '
        'Use these table encodings as ordinary structured data; they do not change any scientific criterion or evidence requirement.')
    return part


def unpack_catalog(encoded):
    if encoded.get('encoding') != 'GROUPED_SOURCE_ROWS_V1':
        return encoded
    result = {}
    for group in encoded['groups']:
        for suffix, kind, content, origin, extra in group['rows']:
            key = group['source_prefix'] + suffix
            if key in result:
                sf.fail('Repeated catalog source after transport decoding')
            result[key] = {'content': content, 'kind': kind, 'item_id': group['item_id'], **extra}
            if origin is not None:
                result[key]['origin'] = origin
    return result


def visible_sources(part):
    sources = {key: entry['content'] for key, entry in unpack_catalog(part['evidence_catalog']).items()}
    sources.update(part['context_sources'])
    for rule in part['project_rules']:
        sources['rule:' + rule['id']] = json.dumps(rule, ensure_ascii=False)
        if 'context_path' in rule:
            for key, value in rule.items():
                if key not in SEMANTIC_RULE_FIELDS or key in {'context_path', 'stages', 'projection_version'}:
                    continue
                if key == 'text' and value.startswith(rule['id'] + ': '):
                    value = value[len(rule['id']) + 2:]
                for suffix, leaf in leaves(value):
                    sources['main:' + rule['context_path'] + '/' + key + suffix] = str(leaf)
    for profile in (part.get('method_knowledge') or {}).get('profiles', []):
        sources['method:' + profile['id']] = json.dumps(profile, ensure_ascii=False)
    return sources


def _new_source_catalog(req, inv, labeled, sources, content_reader, cell_reader):
    """DR may now cite original notes absent from a historical label's citations."""
    plans, catalog = coverage.build_inputs(req, inv, labeled, sources, content_reader, cell_reader)
    wanted = set(_source_ids(req['tasks'] + req['requirements']
                            + req.get('objective_coverage', []) + req.get('data_links', [])
                            + req.get('method_feasibility', []))) - set(catalog)
    # Candidate approaches can cite profiles not selected by any formal requirement.
    # Deliver those exact bound profiles for review without adopting their conditions.
    if any(key.startswith('method:') for key in wanted):
        knowledge = d.requirement_knowledge(req)
        if knowledge:
            sources = {**sources, **d.method_profiles.evidence_sources(knowledge)}
    permissions = {a['item_id']: a['disposition'] for a in req['access']}
    labels = {label['item_id']: label for label in labeled['labels']}
    for item in inv['items']:
        if permissions.get(item['id']) != 'REVIEW_DATA':
            continue
        original = dict(content_reader(item))
        original[item['id']] = sources[item['id']]
        cells = dict(cell_reader(item)) if item['kind'] == 'TABLE' else {}
        label = labels.get(item['id'])
        retained = set(_source_ids(label)) if label else set()
        sample = set(coverage.review_rows(item, label, cells)) if item['kind'] == 'TABLE' and label else set()
        for key in ((wanted | retained | sample) & set(original)) - set(catalog):
            kind = 'DESCRIPTOR' if key == item['id'] else 'SOURCE_CONTENT'
            if item['kind'] == 'TABLE' and key != item['id']:
                cell, region = cells[key], item['region']
                inside = d.in_regions(cell, [region])
                kind = ('SOURCE_NOTE' if not inside else 'SOURCE_CONTENT'
                        if cell['row'] > region['header_row'] and cell.get('value') is not None
                        and str(cell.get('value')).strip() else 'SOURCE_HEADER')
            catalog[key] = {'content': original[key], 'kind': kind, 'item_id': item['id'],
                            'origin': 'REVIEW_SAMPLE' if key in sample - retained else 'RETAINED_OR_DR_CITATION'}
        if item['kind'] == 'TABLE' and label:
            for summary in coverage.column_summaries(item, label, cells):
                catalog.setdefault(item['id'] + ':column:' + summary['column'], {
                    'content': json.dumps(summary, ensure_ascii=False), 'kind': 'COMPUTED', 'item_id': item['id']})
        wanted -= set(original)
    # Method-library entries motivate candidates; they are never data measurements.
    for key in list(wanted):
        if key in sources and key.startswith(('main:', 'rule:', 'method:')):
            catalog[key] = {'content': sources[key], 'kind': key.split(':', 1)[0].upper(), 'item_id': None}
            wanted.remove(key)
    if wanted:
        sf.fail('DR evidence is not in permitted original sources: ' + ', '.join(sorted(wanted)))
    for need, plan in zip(req['requirements'], plans):
        task = next(t for t in req['tasks'] if t['id'] == need['task_id'])
        ids = set(_source_ids([need, task]))
        plan['allowed_source_ids'] = sorted(set(plan['allowed_source_ids']) | ids)
    return plans, catalog


def make_part(payload, *, requirement_ids=(), item_ids=(), condition_ids=(), due_ids=(),
              kind='SCOPED', part_id='PENDING'):
    """Lossless scoped decision context, not a new scientific assessment algorithm."""
    req_ids, own_items = set(requirement_ids), set(item_ids)
    conditions = copy.deepcopy([x for x in payload['condition_checklist'] if x['id'] in set(condition_ids)])
    req = payload['requirements']
    ancillary_ids = {rid for row in conditions for rid in row['requirement_ids']}
    wanted_needs = req_ids | ancillary_ids
    needs = [n for n in req['requirements'] if n['id'] in wanted_needs]
    seen = own_items | {a['item_id'] for a in req['access'] if wanted_needs & set(a['requirement_ids'])}
    seen |= {c['item_id'] for c in conditions}
    global_part = kind.startswith('GLOBAL')
    if global_part:
        needs = req['requirements']
        seen = {a['item_id'] for a in req['access']}
    tasks = [t for t in req['tasks'] if t['id'] in {n['task_id'] for n in needs}]
    plans = copy.deepcopy([p for p in payload['criterion_plans'] if p['requirement_id'] in req_ids])
    labels = [l for l in payload['data_labels']['labels'] if l['item_id'] in seen]
    values = [v for v in payload['data_labels'].get('stated_values', []) if v['item_id'] in seen]
    if kind == 'GLOBAL_OBJECTIVE':
        values = []  # All values are reviewed in GLOBAL_CROSS_SOURCE and their owning item/requirement part.
    labels = [{k: copy.deepcopy(v) for k, v in l.items() if k != 'stated_values'} for l in labels]
    # A global check sees all dataset scope and column meanings; item parts retain complete labels.
    if global_part:
        labels = [{**l, 'columns': [{k: v for k, v in c.items() if k != 'evidence'}
                    for c in l.get('columns', [])]} for l in labels]
    findings = payload['data_labels']['findings']
    if not global_part:
        findings = [f for f in findings if f['affected_id'] in seen | wanted_needs]
    context_ids = set(_source_ids(needs + tasks))
    if kind == 'GLOBAL_OBJECTIVE':
        claims = payload.get('post_source_objective_coverage', [])
        context_ids |= {row['source'] for row in claims}
        context_ids |= set(_source_ids(claims + payload.get('post_source_data_links', [])
                                      + payload.get('post_source_method_feasibility', [])))
    context_ids |= {sid for p in plans for sid in p['allowed_source_ids']}
    context_ids |= set(_source_ids(labels + values + conditions))
    context_ids |= {'main:' + p for a in req['access'] if a['item_id'] in seen for p in a.get('context_paths', [])}
    rule_ids = {r for n in needs for r in n['rule_ids']}
    rule_ids |= {r for a in req['access'] if a['item_id'] in seen for r in a['rule_ids']}
    rules = [r for r in payload['project_rules'] if global_part or r['id'] in rule_ids]
    rule_ids = {r['id'] for r in rules}
    original_catalog = payload['evidence_catalog']
    catalog = {}
    for key, entry in original_catalog.items():
        if key.startswith('rule:') and key.removeprefix('rule:') in rule_ids:
            continue  # Complete operative fields appear once in project_rules.
        if key.startswith('main:/rules/') and key not in context_ids:
            continue
        shared_context = key.startswith('main:') and not key.startswith('main:/rules/')
        scoped_content = entry.get('item_id') in seen and not global_part
        if key in context_ids or shared_context or scoped_content:
            catalog[key] = entry
    sources = {}
    for key, value in payload['context_sources'].items():
        if key in catalog or (key.startswith('rule:') and key.removeprefix('rule:') in rule_ids):
            continue
        if key.startswith('main:/rules/') and key not in context_ids:
            continue
        if key in context_ids or (kind == 'GLOBAL_OBJECTIVE' and key.startswith('main:')
                                  and not key.startswith('main:/rules/')):
            sources[key] = value
    globals_expected = [g for g in payload['expected_check_ids'] if g in d.GLOBAL_CHECKS]
    if kind == 'GLOBAL_OBJECTIVE':
        checks = [g for g in globals_expected if g not in {'MATCHING', 'PERMISSIONS'}]
    elif kind == 'GLOBAL_CROSS_SOURCE':
        checks = [g for g in globals_expected if g in {'MATCHING', 'PERMISSIONS'}]
    else:
        checks = list(requirement_ids) + list(item_ids)
        checks += [g for g in globals_expected if g in {'MATCHING', 'TIMING', 'PERMISSIONS'}]
    method_ids = {mid for n in needs for mid in n.get('method_profile_ids', [])}
    method_context = copy.deepcopy(payload['method_knowledge'])
    if method_context and not global_part:
        method_context['profiles'] = [p for p in method_context['profiles'] if p['id'] in method_ids]
        method_source_ids = {sid for p in method_context['profiles'] for sid in p['source_ids']}
        method_context['sources'] = [s for s in method_context['sources'] if s['id'] in method_source_ids]
        if not method_context['profiles']:
            method_context = None
    scoped = {
        'operation': 'ASSESS_SOURCE_FIRST_COVERAGE_PART', 'part_id': part_id, 'part_kind': kind,
        'objective': payload['objective'],
        'project_rules': [{k: v for k, v in r.items() if k in SEMANTIC_RULE_FIELDS} for r in rules],
        'context_sources': sources, 'evidence_catalog': catalog,
        'requirements': {'tasks': tasks, 'requirements': needs,
            'access': [a for a in req['access'] if a['item_id'] in seen],
            'findings': req['findings'] if global_part else [f for f in req['findings']
                if f['affected_id'] in seen | wanted_needs]},
        'data_labels': _dedup_evidence({'labels': labels, 'stated_values': values,
            'coverage': [x for x in payload['data_labels']['coverage'] if x['item_id'] in seen],
            'findings': findings}, catalog),
        'criterion_plans': plans, 'condition_checklist': conditions,
        'unresolved_ledger': payload['unresolved_ledger'] if kind == 'GLOBAL_OBJECTIVE' else [],
        'due_item_ids': list(due_ids), 'expected_check_ids': checks,
        'label_vocabulary': payload['label_vocabulary'], 'pk_terminology': payload['pk_terminology'],
        'method_knowledge': method_context,
        'assessment_algorithm_version': payload['assessment_algorithm_version'],
        'instructions': payload['instructions'] +
            '\nSOURCE_FIRST_PART: Return matches ONLY for criterion_plans requirement IDs, condition_checks only for supplied condition rows, ledger_outcomes only for due_item_ids, and checks exactly for expected_check_ids. Requirements present as ancillary context need no additional match. '
            'Original source-backed labels are reused with their historical model provenance; old associations are not scientific evidence. '
            'Repeated label and value evidence quotes are omitted only when their exact original cell/line text is in evidence_catalog; evidence_source_ids preserve their field links. Read that complete original text for counterevidence. '
            'project_rules retains every operative field verbatim (text, conditions, exceptions, scope, requirement and usage). Upstream classification explanations and repeated provenance are retained in the immutable main but are not re-sent as operative rules. '
            'For allowed rule:Rxxx sources, quote an unchanged individual operative field from project_rules; the host checks the full original canonical source. Never cite an omitted field or invent a quote. '
            'Global objective checks cover every project endpoint and unmet need. Global cross-source checks see ALL stated values/findings and must check duplicate/conflicting values, source-declared joins and permissions across task boundaries. Neither check grants QC or scientific acceptance.'
    }
    if kind == 'GLOBAL_OBJECTIVE':
        scoped['post_source_dr_claims_to_review'] = {
            'objective_coverage': payload.get('post_source_objective_coverage', []),
            'data_links': payload.get('post_source_data_links', []),
            'method_feasibility': payload.get('post_source_method_feasibility', []),
            'authority': 'MODEL_CLAIMS_TO_CHECK_NOT_SOURCE_EVIDENCE'}
        scoped['instructions'] += (' Independently verify the post-source objective associations, their reasons, '
            'unassigned items and any method-feasibility claims against the supplied original evidence. '
            'An empty association needs a real explanation; an index-shifted description is a correction request, not coverage.')
    return _pack_transport(scoped)


def _size(part):
    return len(json.dumps(part, ensure_ascii=False))


def governed_part_request(part):
    """Use the original request constructor, stopping before audit/cache/provider I/O."""
    class Captured(Exception):
        def __init__(self, request):
            self.request = request
    module = sf.private_module()
    def capture(payload):
        raise Captured(d.governed_request(payload))
    module.governed_request = capture
    try:
        module.invoke(Path('.'), 'DC-review',
            {**copy.deepcopy(part), 'source_first_contract': sf.VERSION, 'scientific_approval': False},
            d.ADEQUACY_REVIEW, model=sf.MODEL)
    except Captured as result:
        return result.request
    sf.fail('Request capture unexpectedly reached execution')


def restore_frozen_part(run, part):
    """Reuse only a byte-equivalent governed request after lossless catalog reordering."""
    candidates = []
    for path in (Path(run)/'data_agents/audit/DC-review').glob('*/request.json'):
        request = read_json(path); old = request.get('payload', {})
        if old.get('operation') != part['operation'] or old.get('part_id') != part['part_id']:
            continue
        if digest(old) != request.get('request_sha256'):
            sf.fail('Frozen review request digest is invalid')
        if unpack_catalog(old['evidence_catalog']) != unpack_catalog(part['evidence_catalog']):
            continue
        restored = copy.deepcopy(part)
        restored['evidence_catalog'] = copy.deepcopy(old['evidence_catalog'])
        if governed_part_request(restored) == request:
            candidates.append((request['request_sha256'], restored))
    if not candidates or len({key for key, _ in candidates}) != 1:
        sf.fail('Cannot uniquely restore the unchanged frozen review request: ' + part['part_id'])
    return candidates[0][1]


def plan_parts(payload):
    """Greedily group complete requirement units; never split their decision context."""
    req = payload['requirements']; ids = [n['id'] for n in req['requirements']]
    order = {rid: n for n, rid in enumerate(ids)}
    owner = {a['item_id']: min(a['requirement_ids'], key=order.__getitem__)
             for a in req['access'] if a['requirement_ids']}
    conditions = payload['condition_checklist']
    condition_owner = {c['id']: min(c['requirement_ids'], key=order.__getitem__) for c in conditions}
    parts = []; held = []

    def group(requirements):
        return make_part(payload, requirement_ids=requirements,
            item_ids=[a['item_id'] for a in req['access'] if owner.get(a['item_id']) in requirements],
            condition_ids=[c['id'] for c in conditions if condition_owner[c['id']] in requirements])

    for rid in ids:
        trial = group(held + [rid])
        if _size(trial) > SOFT_BUDGET and held:
            parts.append(group(held)); held = []
            trial = group([rid])
        if _size(trial) > SOFT_BUDGET:
            sf.fail('One complete requirement exceeds the bounded review budget: ' + rid)
        held.append(rid)
    if held:
        parts.append(group(held))
    held = []
    for a in req['access']:
        if a['item_id'] in owner:
            continue
        trial = make_part(payload, item_ids=held + [a['item_id']])
        if _size(trial) > SOFT_BUDGET and held:
            parts.append(make_part(payload, item_ids=held)); held = []
            trial = make_part(payload, item_ids=[a['item_id']])
        if _size(trial) > SOFT_BUDGET:
            sf.fail('One complete source item exceeds the bounded review budget: ' + a['item_id'])
        held.append(a['item_id'])
    if held:
        parts.append(make_part(payload, item_ids=held))
    parts.append(make_part(payload, kind='GLOBAL_OBJECTIVE', due_ids=payload['due_item_ids']))
    parts.append(make_part(payload, kind='GLOBAL_CROSS_SOURCE'))
    for index, part in enumerate(parts, 1):
        part['part_id'] = f'REVIEW_{index:03d}'
        if _size(part) > SOFT_BUDGET:
            sf.fail('Review decision part exceeds its bounded budget: ' + part['part_id'] + ' ' + part['part_kind'])
    assert_partition(payload, parts)
    return parts


def assert_partition(payload, parts):
    non_global = [k for p in parts for k in p['expected_check_ids'] if k not in d.GLOBAL_CHECKS]
    expected = [k for k in payload['expected_check_ids'] if k not in d.GLOBAL_CHECKS]
    d.exact(non_global, expected, 'Partitioned requirements and source items')
    d.exact([c['id'] for p in parts for c in p['condition_checklist']],
            [c['id'] for c in payload['condition_checklist']], 'Partitioned method conditions')
    d.exact([k for p in parts for k in p['due_item_ids']], payload['due_item_ids'], 'Partitioned due ledger')
    d.exact([c['requirement_id'] for p in parts for c in p['criterion_plans']],
            [c['requirement_id'] for c in payload['criterion_plans']], 'Partitioned criterion plans')
    present = {k for p in parts for k in p['expected_check_ids']}
    if present != set(payload['expected_check_ids']):
        sf.fail('Global review checks were lost at a partition boundary')
    if not {'GLOBAL_OBJECTIVE', 'GLOBAL_CROSS_SOURCE'} <= {p['part_kind'] for p in parts}:
        sf.fail('Explicit cross-source review is missing')


def validate_part(response, part, full):
    def spans(value):
        if isinstance(value, dict):
            if set(value) >= {'source', 'quote'}:
                yield value
            for child in value.values():
                yield from spans(child)
        elif isinstance(value, list):
            for child in value:
                yield from spans(child)
    # A valid source elsewhere in this run does not authorize an unseen quote in this part.
    d.evidence_check(list(spans(response)), visible_sources(part))
    d.check_review(response, part['expected_check_ids'])
    d.exact([m['requirement_id'] for m in response['matches']],
            [p['requirement_id'] for p in part['criterion_plans']], 'Part requirement matches')
    for match in response['matches']:
        need = next(n for n in full['requirements']['requirements'] if n['id'] == match['requirement_id'])
        plan = next(p for p in full['criterion_plans'] if p['requirement_id'] == match['requirement_id'])
        coverage.validate_match(need, match, plan, full['evidence_catalog'])
    linked = {n['id']: {a['item_id'] for a in full['requirements']['access']
                      if a['disposition'] == 'REVIEW_DATA' and n['id'] in a['requirement_ids']}
              for n in full['requirements']['requirements']}
    d.check_conditions(copy.deepcopy(part['condition_checklist']), response['condition_checks'], full['evidence_catalog'], linked)
    d.exact([x['item_id'] for x in response['ledger_outcomes']], part['due_item_ids'], 'Part ledger outcomes')
    ledger = copy.deepcopy(full['unresolved_ledger'])
    if part['due_item_ids']:
        def cited(span):
            entry = full['evidence_catalog'].get(span['source'], {})
            text = entry.get('content') or full['context_sources'].get(span['source'], '')
            return entry.get('kind') != 'COMPUTED' and bool(span['quote'].strip()) and span['quote'] in text
        d.unresolved_ledger.apply_outcomes(ledger, 'BEFORE_QC', response['ledger_outcomes'],
                                          'DC-review', cited, [])


def seal_test_outputs(run):
    """Close all machine-readable preparation gates while retaining exact technical originals."""
    run = Path(run); folder = run/'adequacy'; archive = run/'audit/unapproved_technical_review'
    originals = {}
    for name in ('adequacy.json', 'qc_context.json', 'checkpoint.json', 'checkpoint.md', 'report.md'):
        path = folder/name
        if path.exists():
            target = archive/name; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes()); originals[name] = file_ref(target)
    report = read_json(folder/'adequacy.json'); technical = report['can_enter_qc']
    scope = {'status': 'UNAPPROVED_SOURCE_FIRST_TEST', 'preparation_authorized': False,
             'scientific_release': False, 'human_approval': 'NOT_GRANTED'}
    report.update(test_scope=scope, technical_can_enter_qc=technical, can_enter_qc=False,
                  requires_human_review=True, test_original_ref=originals['adequacy.json'])
    write_json(folder/'adequacy.json', report)
    for name in ('qc_context.json', 'checkpoint.json'):
        path = folder/name
        if not path.exists():
            continue
        value = read_json(path)
        value.update(test_scope=scope, technical_can_enter_qc=technical, can_enter_qc=False,
                     assessment=file_ref(folder/'adequacy.json'), test_original_ref=originals[name],
                     confirmation_required=True, production_release=False)
        write_json(path, value)
    for name in ('checkpoint.md', 'report.md'):
        path = folder/name
        if path.exists():
            path.write_text('UNAPPROVED SOURCE-FIRST TEST. Preparation and scientific release remain closed.\n\n'
                            + path.read_text(encoding='utf-8'), encoding='utf-8')


def review(run, *, generator=None):
    run = Path(run); manifest, verified = sf.verify_run(run)
    if (run/'adequacy/adequacy.json').exists():
        sf.fail('Review already completed; inspect its gaps rather than resampling the decision')
    inputs = [file_ref(run/name) for name in ('inventory.json', 'requirements.json', 'labels.json')]
    repair_index = run/'review_repair_index.json'
    if repair_index.exists():
        inputs.append(file_ref(repair_index))
    organized = read_json(run/'requirements.json')
    if organized.get('source_first_evidence_ref'):
        check_ref(organized['source_first_evidence_ref'])
        inputs.append(organized['source_first_evidence_ref'])
    code_ref = file_ref(__file__)
    module = sf.private_module()
    module.rules_for = lambda main, stages: embedded_projection(main, stages)
    check_module = SimpleNamespace(**vars(coverage)); check_module.build_inputs = _new_source_catalog
    module.data_requirement_check = check_module

    def bounded(out, stage, payload, schema, **options):
        if stage != 'DC-review':
            sf.fail('Only independent coverage review is authorized here')
        payload = {**payload,
            'post_source_objective_coverage': organized.get('objective_coverage', []),
            'post_source_data_links': organized.get('data_links', []),
            'post_source_method_feasibility': organized.get('method_feasibility', [])}
        parts = plan_parts(payload)
        if repair_index.exists():
            parts = [restore_frozen_part(run, part) for part in parts]
        plan = {'version': 'SOURCE_FIRST_BOUNDED_REVIEW_1.0', 'at': utcnow(), 'input_refs': inputs,
            'code_ref': code_ref, 'hard_request_budget': d.REQUEST_BUDGET,
            'parts': [{'id': p['part_id'], 'kind': p['part_kind'], 'payload_sha256': digest(p),
                'payload_chars': _size(p), 'check_ids': p['expected_check_ids'],
                'requirement_ids': [x['requirement_id'] for x in p['criterion_plans']],
                'condition_ids': [x['id'] for x in p['condition_checklist']], 'due_item_ids': p['due_item_ids']}
                for p in parts], 'scientific_release': False}
        prior_plan = run/'review_partition_manifest.json'
        if prior_plan.exists():
            archive = run/'audit/review_plans'/(digest(read_json(prior_plan))[:16]+'.json')
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive.write_bytes(prior_plan.read_bytes())
        write_json(prior_plan, plan)

        def call(part):
            if repair_index.exists():
                from . import data_source_first_review_repair as repair
                repaired = repair.load_checked_response(run, part, payload)
                if repaired is not None:
                    validate_part(repaired, part, payload)
                    sf.emit(run, 'REPAIRED_REVIEW_RESPONSE_REUSED', part=part['part_id'],
                            repair_index_ref=file_ref(repair_index), model_calls=0)
                    return repaired
            return sf.invoke(out, stage, part, schema, generator=generator,
                             check=lambda answer: validate_part(answer, part, payload))

        responses = d.run_calls([partial(call, part) for part in parts])
        for reference in inputs + [code_ref]:
            check_ref(reference)
        return d.merge_reviews(responses, [{'scope': p['part_id']} for p in parts])

    module.invoke = bounded
    module.assess(run, manifest['bindings']['main']['path'], run/'inventory.json',
                  run/'requirements.json', run/'labels.json', run/'adequacy', model=sf.MODEL)
    seal_test_outputs(run)
    # Original scientific/checkpoint outputs remain accurate; this test never grants execution permission.
    report = read_json(run/'adequacy/adequacy.json')
    result = {'status': 'COVERAGE_REVIEW_EXECUTED', 'decision': report['llm_review']['decision'],
        'review_model': sf.MODEL, 'report_ref': file_ref(run/'adequacy/adequacy.json'),
        'matrix_ref': file_ref(run/'adequacy/requirement_matrix.json'),
        'partition_manifest_ref': file_ref(run/'review_partition_manifest.json'),
        'requirement_count': len(report['requirements']), 'findings_count': len(report['findings']),
        'can_enter_qc': False, 'scientific_approval': False, 'human_review_required': True}
    sf.bind_outputs(run, ('review_partition_manifest.json', 'adequacy/adequacy.json',
                         'adequacy/requirement_matrix.json', 'adequacy/review.json'))
    return result
