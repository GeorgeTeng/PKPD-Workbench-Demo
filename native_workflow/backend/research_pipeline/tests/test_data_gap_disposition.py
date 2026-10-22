"""Gap impact does not rewrite source facts, conditions or scoped obligations."""
import copy

import pytest

from ctxcomp.io import digest
from research_pipeline import data_gap_disposition as g
from research_pipeline.common import PipelineError
from research_pipeline.data_requirement_check import aggregate, criterion_plan


def need(rid, necessity='REQUIRED', conditions=None, rule=False, kind='DATA'):
    return {'id': rid, 'task_id': 'ANIMAL_PK', 'description': 'Inputs for ' + rid,
            'necessity': necessity, 'conditions': conditions or [], 'fields': ['Exposure records'],
            'origin': 'PROJECT_EXPLICIT' if rule else 'METHOD_CANDIDATE',
            'rule_ids': ['PRC001'] if rule else [], 'kind': kind, 'required_by': 'BEFORE_PK'}


def method(mid, family, rid, group='MOUSE', species='Mouse'):
    return {'id': mid, 'group_id': group, 'family': family,
            'dataset_ids': [group + '-data'], 'requirement_ids': [rid],
            'scope': {'study': group + '-study', 'species': species, 'matrix': 'plasma', 'record_level': 'GROUP_SUMMARY'}}


def case():
    return {'version': 'REQUIREMENT_PLANNING_3.0',
            'requirements': [need('MODEL_INPUT'), need('NCA_INPUT')],
            'methods': [method('MB', 'MODEL_BASED', 'MODEL_INPUT'), method('NC', 'NCA', 'NCA_INPUT')]}


def coverage(plan, states=None):
    states = states or {}
    needs = {row['id']: row for row in plan['requirements']}
    matches = []
    for m in plan['methods']:
        for rid in m['requirement_ids']:
            rows = []
            for c in criterion_plan(needs[rid]):
                state = states.get((m['id'], rid, c['id']), states.get(m['id'], 'SUPPORTED'))
                rows.append({'id': c['id'], 'status': state, 'evidence': [],
                             'reason': 'Reviewed source fact: ' + state,
                             'needed_material': 'Source-backed ' + c['description']})
            status = aggregate(rows)
            matches.append({'method_id': m['id'], 'requirement_id': rid, 'criteria': rows,
                            'coverage_status': status,
                            'status': 'UNRESOLVED' if status in {'PARTIAL', 'CONFLICT'} else status,
                            'deferred_outputs': []})
    return {'planning_sha256': digest(plan), 'matches': matches}


def decision(plan, state='NOT_APPLICABLE', mid='MB', rid='MODEL_INPUT'):
    n = next(n for n in plan['requirements'] if n['id'] == rid)
    return {'method_id': mid, 'requirement_id': rid, 'decision': state,
            'conditions': copy.deepcopy(n['conditions']), 'reason': 'The original objective defines a different endpoint.',
            'evidence': [{'source': 'main:/objective', 'quote': 'Only finite-window exposure is requested.'}]}


SOURCES = {'main:/objective': 'Only finite-window exposure is requested.'}


def test_model_based_is_preferred_and_coverage_stays_unchanged():
    plan = case()
    facts = coverage(plan)
    before = copy.deepcopy((plan, facts))
    result = g.resolve(plan, facts)
    group = result['groups'][0]
    assert group['eligible_for_next_stage'] and not group['needs_attention']
    assert group['preferred_family'] == 'MODEL_BASED' and group['preferred_method_id'] == 'MB'
    assert group['eligible_method_ids'] == ['MB', 'NC']
    assert result['scientific_approval'] is False
    assert result['coverage_sha256'] == digest(facts)
    assert (plan, facts) == before
    result['methods'][0]['scope']['species'] = 'Changed copy'
    assert plan == before[0]
    assert result['fit_ready'] is False and result['can_enter_qc'] is False
    assert 'PASS' not in str(result)


def test_nca_fallback_retains_failed_model_gap_and_attention():
    plan = case()
    facts = coverage(plan, {'MB': 'MISSING'})
    result = g.resolve(plan, facts)
    group = result['groups'][0]
    assert group['eligible_for_next_stage'] and group['needs_attention']
    assert group['preferred_family'] == 'NCA' and group['preferred_method_id'] == 'NC'
    model = result['methods'][0]
    assert not model['eligible_for_next_stage'] and model['input_gaps']
    assert all(gap['coverage_status'] == 'MISSING' and gap['affects_method'] for gap in model['input_gaps'])
    assert all(c['status'] == 'MISSING' for c in facts['matches'][0]['criteria'])


def test_success_in_another_species_does_not_hide_group_without_a_path():
    plan = case()
    plan['requirements'].append(need('RAT_INPUT'))
    plan['methods'].append(method('RAT_MB', 'MODEL_BASED', 'RAT_INPUT', group='RAT', species='Rat'))
    result = g.resolve(plan, coverage(plan, {'MB': 'MISSING', 'NC': 'MISSING'}))
    groups = {row['group_id']: row for row in result['groups']}
    assert not groups['MOUSE']['eligible_for_next_stage']
    assert groups['MOUSE']['preferred_method_ids'] == []
    assert groups['RAT']['eligible_for_next_stage']


@pytest.mark.parametrize('field,value', [('study', 'Other experiment'), ('species', 'Rat'),
                                        ('matrix', 'urine'), ('record_level', 'INDIVIDUAL')])
def test_incompatible_scope_cannot_share_a_fallback_group(field, value):
    plan = case()
    plan['methods'][1]['scope'][field] = value
    with pytest.raises(PipelineError, match='identical study'):
        g.resolve(plan, coverage(plan))


def test_multiple_models_remain_candidates_without_selecting_structure():
    plan = case()
    plan['methods'].append(method('MB_TWO_COMP', 'MODEL_BASED', 'MODEL_INPUT'))
    group = g.resolve(plan, coverage(plan))['groups'][0]
    assert group['preferred_method_ids'] == ['MB', 'MB_TWO_COMP']
    assert group['preferred_method_id'] is None


def test_other_families_cannot_satisfy_each_other_in_a_shared_group():
    plan = case()
    plan['methods'][0]['family'] = 'PD_INDEX'
    plan['methods'][1]['family'] = 'PD_TARGET'
    with pytest.raises(PipelineError, match='identical study'):
        g.resolve(plan, coverage(plan))


def test_non_pk_method_uses_its_own_family_without_pk_fallback():
    plan = case()
    plan['methods'] = [plan['methods'][0]]
    plan['methods'][0]['family'] = 'PTA'
    plan['requirements'] = [plan['requirements'][0]]
    result = g.resolve(plan, coverage(plan))
    assert result['methods'][0]['task_id'] == 'PTA'
    assert result['groups'][0]['preferred_family'] == 'PTA'


def test_missing_conditional_input_is_unresolved_not_automatically_excluded():
    plan = case()
    plan['requirements'][0].update(necessity='CONDITIONAL', conditions=['If terminal exposure is requested'])
    model = g.resolve(plan, coverage(plan, {'MB': 'MISSING'}))['methods'][0]
    assert not model['eligible_for_next_stage']
    assert {gap['applicability'] for gap in model['input_gaps']} == {'UNRESOLVED'}


def test_fully_supported_conditional_input_needs_no_extra_applicability_gate():
    plan = case()
    plan['requirements'][0].update(necessity='CONDITIONAL', conditions=['If terminal exposure is requested'])
    model = g.resolve(plan, coverage(plan))['methods'][0]
    assert model['eligible_for_next_stage'] and not model['input_gaps']


@pytest.mark.parametrize('missing', ['version', 'planning_sha256'])
def test_absent_plan_version_or_coverage_digest_is_never_trusted(missing):
    plan = case()
    facts = coverage(plan)
    if missing == 'version':
        del plan['version']
        facts['planning_sha256'] = digest(plan)
    else:
        del facts['planning_sha256']
    with pytest.raises(PipelineError):
        g.resolve(plan, facts)


def test_evidence_backed_nonapplicability_preserves_gap_without_blocking_method():
    plan = case()
    plan['requirements'][0].update(necessity='CONDITIONAL', conditions=['If terminal exposure is requested'])
    facts = coverage(plan, {'MB': 'MISSING'})
    result = g.resolve(plan, facts, [decision(plan)], SOURCES)
    model = result['methods'][0]
    assert model['eligible_for_next_stage'] and not model['needs_attention']
    assert model['input_gaps'] and all(not gap['affects_method'] for gap in model['input_gaps'])
    assert {gap['coverage_status'] for gap in model['input_gaps']} == {'MISSING'}
    assert result['applicability_decisions'] == [decision(plan)]


def test_conditional_applies_and_unresolved_both_retain_missing_input_block():
    plan = case()
    plan['requirements'][0].update(necessity='CONDITIONAL', conditions=['If terminal exposure is requested'])
    for state in ('APPLIES', 'UNRESOLVED'):
        row = g.resolve(plan, coverage(plan, {'MB': 'PARTIAL'}), [decision(plan, state)], SOURCES)['methods'][0]
        assert not row['eligible_for_next_stage']


@pytest.mark.parametrize('state', ['NOT_APPLICABLE', 'UNRESOLVED'])
def test_required_inputs_cannot_be_waived_or_downgraded(state):
    plan = case()
    with pytest.raises(PipelineError, match='REQUIRED input cannot be waived'):
        g.resolve(plan, coverage(plan, {'MB': 'MISSING'}), [decision(plan, state)], SOURCES)


def test_conditional_rule_exception_requires_separate_judgment_not_automatic_waiver():
    plan = case()
    plan['requirements'][0] = need('MODEL_INPUT', 'CONDITIONAL', ['If terminal exposure is requested'], rule=True)
    result = g.resolve(plan, coverage(plan, {'MB': 'MISSING'}), [decision(plan)], SOURCES)
    assert not result['methods'][0]['eligible_for_next_stage']
    assert {gap['applicability'] for gap in result['methods'][0]['input_gaps']} == {'UNRESOLVED'}
    # Keep the original method-specific rule scope; do not invent a group-wide rule.
    assert result['groups'][0]['eligible_for_next_stage'] and result['groups'][0]['needs_attention']
    assert result['groups'][0]['preferred_family'] == 'NCA'


def test_shared_rule_need_is_evaluated_for_both_linked_routes():
    plan = case()
    shared = need('SHARED_RULE', rule=True)
    plan['requirements'].append(shared)
    for m in plan['methods']:
        m['requirement_ids'].append('SHARED_RULE')
    states = {(mid, 'SHARED_RULE', 'FULL_REQUIREMENT'): 'MISSING' for mid in ('MB', 'NC')}
    result = g.resolve(plan, coverage(plan, states))
    assert not result['groups'][0]['eligible_for_next_stage']
    assert all(any(gap['rule_ids'] == ['PRC001'] for gap in m['input_gaps']) for m in result['methods'])


@pytest.mark.parametrize('fault', ['conditions', 'foreign_quote', 'missing_evidence', 'coverage_evidence', 'unlinked', 'duplicate'])
def test_applicability_decisions_require_original_conditions_and_admitted_evidence(fault):
    plan = case()
    plan['requirements'][0].update(necessity='CONDITIONAL', conditions=['If terminal exposure is requested'])
    d = decision(plan)
    sources = copy.deepcopy(SOURCES)
    decisions = [d]
    if fault == 'conditions': d['conditions'] = ['Changed condition']
    elif fault == 'foreign_quote': d['evidence'][0]['quote'] = 'Not in the source'
    elif fault == 'missing_evidence': d['evidence'] = []
    elif fault == 'coverage_evidence':
        d['evidence'][0] = {'source': 'coverage:MB', 'quote': 'Missing PK data'}
        sources['coverage:MB'] = 'Missing PK data'
    elif fault == 'unlinked': d['method_id'] = 'NC'
    else: decisions.append(copy.deepcopy(d))
    with pytest.raises(PipelineError):
        g.resolve(plan, coverage(plan, {'MB': 'MISSING'}), decisions, sources)


@pytest.mark.parametrize('state', ['PARTIAL', 'MISSING', 'CONFLICT', 'UNRESOLVED', 'DEFERRED'])
def test_all_unmet_required_criterion_states_remain_gaps(state):
    plan = case()
    result = g.resolve(plan, coverage(plan, {('MB', 'MODEL_INPUT', 'FIELD_001'): state}))
    gap = result['methods'][0]['input_gaps'][0]
    assert not result['methods'][0]['eligible_for_next_stage']
    assert gap['coverage_status'] == state and gap['affects_method']
    assert gap['next_action']['counts_as_satisfied'] is False
    if state == 'DEFERRED':
        assert gap['next_action']['kind'] == 'PLANNED_MODEL_OUTPUT'


def test_disposition_advice_does_not_satisfy_definition_or_new_data_gaps():
    plan = case()
    plan['requirements'][0]['kind'] = 'DEFINITION'
    facts = coverage(plan, {'MB': 'MISSING'})
    model = g.resolve(plan, facts)['methods'][0]
    assert all(gap['next_action']['kind'] == 'DESIGN_DEFINITION' for gap in model['input_gaps'])
    d = decision(plan, 'APPLIES')
    d['gap_kind'] = 'NEW_DATA'
    model = g.resolve(plan, facts, [d], SOURCES)['methods'][0]
    assert not model['eligible_for_next_stage']
    assert all(gap['next_action']['kind'] == 'NEW_DATA' and not gap['next_action']['counts_as_satisfied'] for gap in model['input_gaps'])


@pytest.mark.parametrize('fault', ['digest', 'pair_missing', 'pair_duplicate', 'criterion_missing', 'aggregate'])
def test_coverage_facts_must_match_complete_plan_without_status_rewriting(fault):
    plan = case()
    facts = coverage(plan)
    if fault == 'digest': facts['planning_sha256'] = 'old-plan'
    elif fault == 'pair_missing': facts['matches'].pop()
    elif fault == 'pair_duplicate': facts['matches'].append(copy.deepcopy(facts['matches'][0]))
    elif fault == 'criterion_missing': facts['matches'][0]['criteria'].pop()
    else: facts['matches'][0]['coverage_status'] = 'MISSING'
    with pytest.raises(PipelineError):
        g.resolve(plan, facts)
