"""Deterministic gap impact and within-group input paths; never scientific approval.

Coverage remains an immutable account of facts. A scoped applicability decision
can explain why a conditional gap does not affect one method; it cannot change
the coverage status, waive a required input or rewrite a project rule.
"""
import copy

from ctxcomp.io import digest
from .common import PipelineError
from .data_requirement_check import aggregate, criterion_plan

VERSION = 'DATA_GAP_DISPOSITION_1.0'
COVERAGE_STATUSES = {'SUPPORTED', 'PARTIAL', 'MISSING', 'CONFLICT', 'UNRESOLVED', 'DEFERRED'}
DECISIONS = {'APPLIES', 'NOT_APPLICABLE', 'UNRESOLVED'}
SCOPE_FIELDS = ('study', 'species', 'matrix', 'record_level')
GAP_KINDS = {'DESIGN_DEFINITION', 'EXISTING_SOURCE_REVIEW', 'PLANNED_MODEL_OUTPUT', 'NEW_DATA'}
TASKS = {'MODEL_BASED': 'ANIMAL_PK', 'NCA': 'ANIMAL_PK', 'PD_INDEX': 'PD_INDEX',
         'PD_TARGET': 'PD_TARGET', 'PTA': 'PTA'}


def fail(message):
    raise PipelineError('DATA_GAP_DISPOSITION_INVALID', message)


def indexed(rows, field, label):
    result = {}
    for row in rows:
        key = row[field]
        if not isinstance(key, str) or not key.strip() or key in result:
            fail('Empty or duplicate ' + label)
        result[key] = row
    return result


def evidence_check(spans, sources):
    if not spans or sources is None:
        fail('Applicability decisions need original evidence and its source map.')
    for span in spans:
        source, quote = span.get('source'), span.get('quote')
        if not isinstance(source, str) or source.startswith(('coverage:', 'method:')):
            fail('Coverage conclusions or generic method knowledge cannot prove applicability.')
        if source not in sources or not isinstance(quote, str) or not quote.strip() or quote not in sources[source]:
            fail('Applicability evidence is not an exact quote from an admitted source.')


def decision_map(decisions, methods, needs, sources):
    result = {}
    for decision in decisions:
        key = (decision.get('method_id'), decision.get('requirement_id'))
        if key in result or key[0] not in methods or key[1] not in methods[key[0]]['requirement_ids']:
            fail('Unknown, duplicate or unlinked applicability decision.')
        need = needs[key[1]]
        if decision.get('decision') not in DECISIONS or not str(decision.get('reason', '')).strip():
            fail('Applicability decision needs a valid state and reason.')
        if decision.get('conditions') != need['conditions']:
            fail('Applicability decision must retain the complete original conditions.')
        evidence_check(decision.get('evidence', []), sources)
        if need['necessity'] == 'REQUIRED' and decision['decision'] != 'APPLIES':
            fail('A REQUIRED input cannot be waived or downgraded by applicability review.')
        result[key] = decision
    return result


def applicability(need, decision):
    if need['necessity'] == 'REQUIRED':
        return 'APPLIES'
    if decision is None:
        return 'UNRESOLVED'
    # A conditional published obligation remains unresolved in this minimal
    # automatic resolver even if a reviewer proposes its exception applies.
    if need.get('origin') == 'PROJECT_EXPLICIT' and need.get('rule_ids') and decision['decision'] == 'NOT_APPLICABLE':
        return 'UNRESOLVED'
    return decision['decision']


def next_action(need, criterion, decision):
    """Advice only. No suggested action is counted as a satisfied criterion."""
    kind = decision.get('gap_kind') if decision else None
    if kind is not None and kind not in GAP_KINDS:
        fail('Unknown gap disposition kind.')
    if kind is None:
        kind = ('DESIGN_DEFINITION' if need.get('kind') == 'DEFINITION' else
                'PLANNED_MODEL_OUTPUT' if criterion['status'] == 'DEFERRED' else
                'EXISTING_SOURCE_REVIEW')
    return {'kind': kind, 'needed_material': criterion['needed_material'],
            'counts_as_satisfied': False}


def resolve(planning, coverage, applicability_decisions=(), evidence_sources=None):
    """Evaluate immutable facts within each planned method and analysis group.

    Applicability decisions contain method_id, requirement_id, decision,
    conditions (the entire unchanged planning list), reason and exact evidence.
    Quote validation proves traceability, not semantic correctness of a review.
    The caller supplies only admitted original project/source texts in the map.
    """
    applicability_decisions = list(applicability_decisions)
    if planning.get('version') != 'REQUIREMENT_PLANNING_3.0':
        fail('Expected a REQUIREMENT_PLANNING_3.0 planning artifact.')
    if coverage.get('planning_sha256') != digest(planning):
        fail('Coverage does not bind this unchanged planning artifact.')
    needs = indexed(planning['requirements'], 'id', 'requirement ID')
    methods = indexed(planning['methods'], 'id', 'method ID')
    if not methods:
        fail('At least one planned method is required.')
    groups = {}
    for need in needs.values():
        if need.get('necessity') not in {'REQUIRED', 'CONDITIONAL'}:
            fail('A requirement must retain its planned necessity.')
        if not isinstance(need.get('conditions'), list) or (need['necessity'] == 'CONDITIONAL' and not need['conditions']):
            fail('A conditional requirement needs explicit original conditions.')
    expected = set()
    for method in methods.values():
        if method.get('family') not in TASKS:
            fail('Unknown planned method family.')
        required = method['requirement_ids']
        if not required or len(required) != len(set(required)) or not set(required) <= set(needs):
            fail('Method has missing, duplicated or unknown requirement links.')
        datasets = method['dataset_ids']
        if len(datasets) != len(set(datasets)):
            fail('Method has duplicate dataset links.')
        scope = method.get('scope', {})
        if any(not isinstance(scope.get(key), str) or not scope[key].strip() for key in SCOPE_FIELDS):
            fail('Method scope must name study, species, matrix and record_level.')
        group_id = method.get('group_id')
        if not isinstance(group_id, str) or not group_id.strip():
            fail('Every method needs its own analysis-group identity.')
        group = groups.setdefault(group_id, [])
        if group and (any(scope[key] != group[0]['scope'][key] for key in SCOPE_FIELDS)
                      or TASKS[method['family']] != TASKS[group[0]['family']]):
            fail('Methods in one group must have identical study/species/matrix/record-level scope and task.')
        group.append(method)
        expected.update((method['id'], rid) for rid in required)
    matches = {}
    for match in coverage['matches']:
        key = (match['method_id'], match['requirement_id'])
        if key in matches or key not in expected:
            fail('Coverage contains duplicate or unplanned method/requirement pairs.')
        criteria = match['criteria']
        expected_ids = {item['id'] for item in criterion_plan(needs[key[1]])}
        actual_ids = [item['id'] for item in criteria]
        if len(actual_ids) != len(set(actual_ids)) or set(actual_ids) != expected_ids:
            fail('Coverage must retain every planned criterion exactly once.')
        if any(item['status'] not in COVERAGE_STATUSES for item in criteria):
            fail('Unknown coverage criterion state.')
        actual_status = aggregate(criteria)
        compatibility = 'UNRESOLVED' if actual_status in {'PARTIAL', 'CONFLICT'} else actual_status
        if match.get('coverage_status') != actual_status or match.get('status') != compatibility:
            fail('Coverage aggregation conflicts with the preserved criterion facts.')
        matches[key] = match
    if set(matches) != expected:
        fail('Coverage must account for every planned method/requirement pair.')
    decisions = decision_map(applicability_decisions, methods, needs, evidence_sources)
    rows = []
    for method in methods.values():
        gaps = []
        for rid in method['requirement_ids']:
            need, match = needs[rid], matches[method['id'], rid]
            decision = decisions.get((method['id'], rid))
            # Necessity is consulted only for actual gaps. A covered conditional
            # input does not become blocked just because no separate ruling exists.
            for criterion in match['criteria']:
                if criterion['status'] == 'SUPPORTED':
                    continue
                state = applicability(need, decision)
                gaps.append({
                    'requirement_id': rid, 'criterion_id': criterion['id'],
                    'coverage_status': criterion['status'], 'necessity': need['necessity'],
                    'applicability': state, 'affects_method': state != 'NOT_APPLICABLE',
                    'applicability_reason': (
                        'An explicit rule condition or exception needs separate judgment; the obligation is not waived.'
                        if decision and decision['decision'] == 'NOT_APPLICABLE' and state == 'UNRESOLVED'
                        else decision['reason'] if decision else
                        'Required by the unchanged plan.' if state == 'APPLIES' else
                        'No evidence-backed applicability decision was provided.'),
                    'reason': criterion['reason'], 'needed_material': criterion['needed_material'],
                    'rule_ids': copy.deepcopy(need.get('rule_ids', [])),
                    'next_action': next_action(need, criterion, decision),
                })
        blocking = [gap for gap in gaps if gap['affects_method']]
        rows.append({'method_id': method['id'], 'group_id': method['group_id'],
                     'task_id': TASKS[method['family']], 'family': method['family'],
                     'scope': copy.deepcopy(method['scope']),
                     'dataset_ids': copy.deepcopy(method['dataset_ids']),
                     'eligible_for_next_stage': not blocking, 'needs_attention': bool(blocking),
                     'input_gaps': gaps})
    method_results = {row['method_id']: row for row in rows}
    group_rows = []
    for group_id, members in groups.items():
        members = [method_results[method['id']] for method in members]
        eligible = [method for method in members if method['eligible_for_next_stage']]
        available_families = {method['family'] for method in eligible}
        if members[0]['task_id'] == 'ANIMAL_PK':
            if any(method['family'] not in {'MODEL_BASED', 'NCA'} for method in members):
                fail('ANIMAL_PK groups contain MODEL_BASED or NCA methods only.')
            family = next((family for family in ('MODEL_BASED', 'NCA') if family in available_families), None)
            preferred = sorted(method['method_id'] for method in eligible if method['family'] == family)
        else:
            # There is no implicit scientific ranking for other task families.
            family = next(iter(available_families)) if len(available_families) == 1 else None
            preferred = sorted(method['method_id'] for method in eligible)
        group_rows.append({
            'group_id': group_id, 'task_id': members[0]['task_id'],
            'scope': copy.deepcopy(members[0]['scope']),
            'method_ids': [method['method_id'] for method in members],
            'eligible_for_next_stage': bool(eligible),
            'needs_attention': any(method['needs_attention'] for method in members),
            'eligible_method_ids': sorted(method['method_id'] for method in eligible),
            'preferred_family': family, 'preferred_method_ids': preferred,
            'preferred_method_id': preferred[0] if len(preferred) == 1 else None,
        })
    return {'version': VERSION, 'planning_sha256': digest(planning), 'coverage_sha256': digest(coverage),
            'applicability_decisions': copy.deepcopy(list(applicability_decisions)),
            'methods': rows, 'groups': group_rows,
            'scientific_approval': False, 'can_enter_qc': False, 'fit_ready': False,
            'assessment_scope': 'LINKED_REQUIREMENT_INPUT_GAPS_ONLY',
            'interpretation': 'Input eligibility for the next stage only; no model, fit or scientific result is qualified. '
                              'Original coverage and rule scope are retained. Evidence quotes establish traceability; '
                              'applicability semantics require separate review. Other pending coverage checks remain '
                              'in the bound coverage artifact; input eligibility does not resolve them or open a scientific gate.'}
