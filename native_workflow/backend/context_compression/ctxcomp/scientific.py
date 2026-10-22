"""Typed scientific extraction and deterministic handoff projection.

Structural/source checks cannot establish entailment or correct scientific
binding. Independent source-bound reviews remain mandatory.
"""
import copy
import json

from .io import digest
from .schemas import validate_schema, SCIENCE_HANDOFF, COMPACT_SCIENCE_HANDOFF
from .bindings import binding_diagnostics, BindingValidationError, STRICT, options as binding_options


def enabled(bundle):
    return bool(bundle.get('processing_rules', {}).get('scientific_extraction'))


def item_ids(requirements):
    return [r['id'] for r in requirements['items']] + [
        q['id'] for q in requirements.get('potential_questions', [])]


def response_schema(stage, schema, active, proposition_contract=None):
    schema = copy.deepcopy(schema)
    if stage == 'requirements':
        inv = schema['properties']['requirements']
        inv.pop('allOf', None)
        inv['properties']['version'] = {'type': 'string', 'const': '1.1' if active else '1.0'}
        item = inv['properties']['items']['items']
        if active:
            inv['required'].append('potential_questions')
            item['required'].append('science')
        else:
            inv['properties'].pop('potential_questions', None)
            item['properties'].pop('science', None)
    if stage == 'context_review':
        review = schema['properties']['review']
        if active:
            review['required'].append('scientific_checks')
        else:
            review['properties'].pop('scientific_checks', None)
    # New frozen profiles supply field-specific instructions without changing
    # the response shape. Historical requests without the profile stay exact.
    if active and proposition_contract:
        guidance = proposition_contract['schema_guidance']
        # Schema fields share one string definition (deepcopy keeps the sharing), so each guided field gets
        # its own copy; otherwise the guidance would also describe every ID, quote and list in the schema.
        if stage == 'requirements':
            fields = schema['properties']['requirements']['properties']['items']['items']['properties']
            fields['statement'] = {**fields['statement'], 'description': guidance['statement']}
            for name in ('role', 'evidence_status'):
                science = fields['science']['properties']
                science[name] = {**science[name], 'description': guidance[name]}
        elif stage == 'requirements_review':
            fields = schema['properties']['review']['properties']['items']['items']['properties']
            fields['reason'] = {**fields['reason'], 'description': guidance['review_reason']}
    return schema


def method_ref_issues(requirements):
    """method_refs that name a non-METHOD or unknown item, in the binding-diagnostics shape so one repair can fix them."""
    records = {r['id']: r for r in requirements['items']}
    methods = [i for i, r in records.items() if r['science']['role'] == 'METHOD']
    issues = []
    for ri, record in enumerate(requirements['items']):
        for k, ref in enumerate(record['science']['method_refs']):
            if ref in records and records[ref]['science']['role'] == 'METHOD':
                continue
            issues.append({'item_id': record['id'], 'field': 'method_refs', 'ref_index': k,
                'path': f'/requirements/items/{ri}/science/method_refs/{k}', 'proposed_value': ref,
                'target_role': records[ref]['science']['role'] if ref in records else 'MISSING',
                'component_ids': [], 'evidence': [], 'reason': 'METHOD_REF_NOT_METHOD',
                'what_to_change': 'method_refs may name only METHOD items (' + (', '.join(methods) or 'none in this inventory')
                    + '). Replace the reference with the METHOD item the statement relies on, or remove it; '
                    'a requirement, fact or result is linked through relations, never method_refs.'})
    return issues


def validate_inventory(requirements, units, options=STRICT):
    from .retention import span_check
    if requirements['version'] != '1.1':
        return
    diagnostics = binding_diagnostics(requirements, units, options)
    refs = method_ref_issues(requirements)
    if refs:
        issues = diagnostics['issues'] + refs
        diagnostics = {**diagnostics, 'issues': issues, 'issue_count': len(issues),
                       'affected_item_count': len({i['item_id'] for i in issues})}
    if diagnostics['issue_count']:
        raise BindingValidationError(diagnostics)
    ids = item_ids(requirements)
    if len(ids) != len(set(ids)):
        raise ValueError('Scientific inventory and question IDs must be unique')
    records = {r['id']: r for r in requirements['items']}
    for record in records.values():
        science = record['science']
        components = {c['id']: c for c in record['components']}
        if science['role'] == 'ASSUMPTION' and science['evidence_status'] != 'ASSUMED':
            raise ValueError('A project assumption must be source-adopted and marked ASSUMED; inferred premises belong in potential_questions')
        for method in science['method_refs']:
            if method not in records or records[method]['science']['role'] != 'METHOD':
                raise ValueError('Scientific method_refs must resolve to METHOD inventory items')
        if len(science['method_refs']) != len(set(science['method_refs'])):
            raise ValueError('Repeated scientific method reference')
        for relation in science['relations'] + science['adoption_relations']:
            if relation['target_id'] not in records:
                raise ValueError('Scientific relation must resolve to a source inventory item, never an inferred question')
            if not set(relation['component_ids']) <= components.keys():
                raise ValueError('Scientific relation has an unknown source component')
    for question in requirements['potential_questions']:
        for span in question['source_refs']:
            span_check(span, units)


def project(requirements, units, sources, options=STRICT):
    """Lossless typed metadata, quoted evidence retained in the inventory audit."""
    from .retention import span_check
    validate_inventory(requirements, units, options)
    def locators(spans, component_id):
        return [{'component_id': component_id, 'source_id': s['source_id'],
                 'unit_id': s['unit_id'], **position}
                for s in spans for position in span_check(s, units)['matches']]
    items = []
    for r in requirements['items']:
        refs = [ref for c in r['components'] for ref in locators(c['evidence'], c['id'])]
        items.append({'id': r['id'], 'statement': r['statement'],
                      'science': copy.deepcopy(r['science']), 'source_refs': refs})
    questions = [{**{k: copy.deepcopy(v) for k, v in q.items() if k != 'source_refs'},
                  'source_refs': locators(q['source_refs'], 'QUESTION_BASIS')}
                 for q in requirements['potential_questions']]
    used = {s['source_id'] for item in items + questions for s in item['source_refs']}
    registry = [{**{k: str(s.get(k, 'NOT_FOUND')) for k in ('id', 'name', 'role', 'original_sha256')},
                 'file_id': str(s.get('file_id', s['id'])),
                 'locator': str(s.get('locator', 'Character offsets in the frozen extracted source text'))}
                for s in sources if s['id'] in used]
    result = {'version': '1.0', 'items': items, 'potential_questions': questions, 'sources': registry}
    validate_handoff(result)
    return result


def compact_projection(audit):
    """Remove evidence machinery, never rewrite a statement after its review."""
    validate_handoff(audit)
    if audit['version'] == '2.0':
        return copy.deepcopy(audit)
    value = copy.deepcopy(audit)
    value['version'] = '2.0'
    value.pop('sources')
    for record in value['items'] + value['potential_questions']:
        record.pop('source_refs')
        if 'science' not in record:
            continue
        science = record['science']
        science.pop('bindings')
        for relation in science['relations'] + science['adoption_relations']:
            relation.pop('component_ids')
    validate_handoff(value)
    return value


def audit_record(main, reviewed):
    p = reviewed['payload']
    return {'main_sha256':digest(main), 'review_request_sha256':reviewed['request_sha256'],
            'projection':project(p['requirements'], p['source_units'], p['sources'], binding_options(p)),
            'scope':'Extraction provenance; review PASS confirms the transformation, not scientific validity.'}


def validate_handoff(value):
    compact = value.get('version') == '2.0'
    validate_schema(value, COMPACT_SCIENCE_HANDOFF if compact else SCIENCE_HANDOFF)
    ids = [x['id'] for x in value['items'] + value['potential_questions']]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate scientific handoff ID')
    records = {r['id']: r for r in value['items']}
    sources = {s['id'] for s in value.get('sources', [])}
    if len(sources) != len(value.get('sources', [])):
        raise ValueError('Duplicate scientific source ID')
    for record in value['items'] + value['potential_questions']:
        for ref in record.get('source_refs', []):
            if ref['source_id'] not in sources or ref['end_char'] <= ref['start_char']:
                raise ValueError('Invalid scientific source locator')
        if 'science' not in record:
            continue
        science = record['science']
        if science['role'] == 'ASSUMPTION' and science['evidence_status'] != 'ASSUMED':
            raise ValueError('Scientific assumption must remain ASSUMED')
        for mid in science['method_refs']:
            if mid not in records or records[mid]['science']['role'] != 'METHOD':
                raise ValueError('Unresolved METHOD in scientific handoff')
        components = {r['component_id'] for r in record.get('source_refs', [])}
        for binding in science.get('bindings', []):
            if not set(binding['component_ids']) <= components:
                raise ValueError('Scientific binding lost its source component')
        for relation in science['relations'] + science['adoption_relations']:
            if relation['target_id'] not in records or (not compact and not set(relation['component_ids']) <= components):
                raise ValueError('Scientific relation lost its target or evidence')


def review_check(review, requirements, branch=False):
    from .retention import exact_ids, reject_false_pass
    if requirements['version'] != '1.1':
        return
    checks = review.get('scientific_checks', [])
    exact_ids([c['id'] for c in checks], item_ids(requirements), 'Scientific role/status/binding review')
    fields = ['verdict'] if branch else ['faithfulness', 'completeness']
    reject_false_pass(review, any(c[k] != 'PRESERVED' for c in checks for k in fields))


def attach(payload, requirements, units, sources, compact=False):
    """Make the exact future main.json extension visible before final review."""
    value = project(requirements, units, sources, binding_options(payload))
    if compact:
        value = compact_projection(value)
    payload['scientific_context'] = value
    payload['scientific_context_sha256'] = digest(value)
    payload['instructions'] += (
        '\nThe host will copy scientific_context unchanged into main.json. '
        'Audit it together with the compact context against ORIGINAL sources. '
        'Every scientific item and potential question needs scientific_checks in the final review. '
        'FACT/UNKNOWN inventory kind is not discourse role or proof of truth. '
        'A model-inferred question is not an adopted project assumption. '
        'Check complete study/analysis-specific tuples, not just individual matching words. '
        'Keep the objective and consequential qualifications in the compact fields too. '
        'Do not insert the scientific_context object into the legacy context schema yourself.')
    if compact:
        payload['instructions'] += (
            '\nBindings, quotes and original-source locators remain in the private requirements/evidence audit, '
            'not in main.json. Compare the actual compact scientific_context and context against that inventory '
            'and original sources. All consequential quantities, units, associations, conditions, negations, '
            'assumptions and unresolved information must be understandable from the delivered text itself. '
            'Reject any missing meaning; a fact existing only in an omitted binding is not preserved. '
            'Do not require downstream agents to open the audit to understand the task.')


def scoped_projection(value, source_ids=()):
    """Select by validated source IDs or explicit identifiers, never filenames.

    Routing callers can attach this to a branch once their task evidence is
    known. Referenced methods and linked premises are included transitively.
    """
    validate_handoff(value)
    requested = set(source_ids)
    records = {r['id']: r for r in value['items']}
    wanted = {i for i, r in records.items() if i in requested or any(
        ref['source_id'] in requested for ref in r.get('source_refs', []))}
    # No guessed relevance from keywords or partial string matching.
    while True:
        linked = {target for i in wanted for target in records[i]['science']['method_refs']}
        linked |= {r['target_id'] for i in wanted for r in
                   records[i]['science']['relations'] + records[i]['science']['adoption_relations']}
        expanded = wanted | linked
        if expanded == wanted:
            break
        wanted = expanded
    questions = [q for q in value['potential_questions'] if q['id'] in requested]
    items = [r for r in value['items'] if r['id'] in wanted]
    result = {**value, 'items': copy.deepcopy(items), 'potential_questions': copy.deepcopy(questions)}
    if 'sources' in value:
        sources = {ref['source_id'] for r in items + questions for ref in r['source_refs']}
        result['sources'] = [copy.deepcopy(s) for s in value['sources'] if s['id'] in sources]
    return result


def from_context_citations(main, citations):
    """Project only records explicitly cited by reviewed downstream tasks/needs."""
    value = main['scientific_context']
    records = {f'/scientific_context/{name}/{i}': r
               for name in ('items', 'potential_questions') for i, r in enumerate(value[name])}
    selected = set()
    for citation in citations:
        path = citation['path']
        if not path.startswith('/scientific_context/'):
            continue
        if path not in records or not citation['quote'].strip() or citation['quote'] not in json.dumps(records[path], ensure_ascii=False):
            raise ValueError('Scientific routing requires a verified whole-record context citation')
        selected.add(records[path]['id'])
    return scoped_projection(value, selected)
