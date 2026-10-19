"""Independent scoped-impact acceptance tests. Synthetic fixtures, zero providers."""
import copy

import pytest
from ctxcomp.io import digest
from research_pipeline import data_necessity_v6 as n
from research_pipeline.common import PipelineError, read_json, write_json
from test_data_necessity_v4 import fixture, rules


def inputs(*, second_scope=False, gaps=2, family='MODEL_BASED'):
    plan, coverage, catalog = fixture(family=family, status='UNRESOLVED')
    coverage.update(version='COVERAGE_FACTS_5.0', complete=True,
                    scientific_approval=False, can_enter_qc=False, fit_ready=False)
    row = coverage['matches'][0]
    row['unit_id'] = 'U1'
    original = copy.deepcopy(row['criteria'][0])
    row['criteria'] = [{**copy.deepcopy(original), 'id': 'FIELD_' + str(i + 1).zfill(3)}
                       for i in range(gaps)]
    if second_scope:
        scope = copy.deepcopy(coverage['scopes'][0])
        scope.update(id='S2', item_ids=['I2'])
        scope['scientific_scope']['study'] = 'B'
        coverage['scopes'].append(scope)
        other = copy.deepcopy(row)
        other.update(unit_id='U2', scope_id='S2')
        for c in other['criteria']:
            for field in ('evidence', 'counterevidence'):
                for span in c[field]:
                    span['source'] = 'I2:note'
            c['searched_item_ids'] = ['I2']
        coverage['matches'].append(other)
        catalog['I2:note'] = {'content': 'Group means, no individual IDs.',
                              'kind': 'SOURCE_NOTE', 'item_id': 'I2'}
    return plan, coverage, catalog


def payload(**kwargs):
    plan, coverage, catalog = inputs(**kwargs)
    return n.build_payload(plan, coverage, catalog, project_rules=rules())


def answer(p):
    registry, _ = n.evidence_registry(p)
    reviews = {}
    for gid, group in p['review_groups'].items():
        admitted = {eid: row for eid, row in registry.items()
                    if row['source'] in group['allowed_source_ids']}
        authority = next(eid for eid, row in admitted.items() if row['source'].startswith('main:'))
        local = next(eid for eid, row in admitted.items() if row['role'] == 'LOCAL_SOURCE_EVIDENCE')
        refs = [authority, local]
        conditions = ['SYNTHETIC fixture: original source qualification remains unresolved.']
        reviews[gid] = {'impacts': [{'gap_keys': group['gap_keys'], 'level': 'UNCERTAIN',
            'explanation': 'SYNTHETIC fixture: assess recorded shortages without changing Coverage.',
            'affected_actions': group['actions'], 'conditions': conditions, 'evidence_refs': refs}],
            'can_continue': [{'activity': 'Organize existing source references.',
                              'conditions': conditions, 'evidence_refs': refs}],
            'recommendations': [{'kind': 'CONDITIONAL_DATA_OPTION',
                'suggestion': 'If existing permitted sources cannot resolve the input, consider a scoped design option.',
                'conditions': conditions, 'gap_keys': group['gap_keys'], 'evidence_refs': refs}],
            'follow_up': [{'gap_keys': group['gap_keys'], 'question': 'Which original source establishes the input?'}]}
    return {'request_sha256': 'SYNTHETIC', 'reviews': reviews}


def test_unresolved_shortages_yield_conditional_advice_without_scientific_pass():
    p = payload(gaps=5)
    original = copy.deepcopy(p)
    result = n.resolve(answer(p), p)
    assert p == original
    assert len(result['reports']) == 1 and len(result['gap_evidence_map']) == 5
    advice = result['reports'][0]['recommendations'][0]
    assert advice['status'] == 'CONDITIONAL_CANDIDATE_ONLY'
    assert advice['confirms_missing_data'] is False and advice['experiment_authorized'] is False
    assert result['formal_new_data_assessment'] == 'NOT_PERFORMED_CANDIDATE_ADVICE_ONLY'
    assert result['coverage_facts'] == p['units']
    assert all(result[k] is False for k in ('scientific_approval', 'can_enter_qc', 'fit_ready'))


def test_actual_wire_schema_does_not_require_old_gap_action_matrix():
    p = payload(gaps=7)
    schema = n.wire_schema(p)
    assert set(schema['properties']) == {'request_sha256', 'reviews'}
    text = str(schema)
    assert 'criterion_groups' not in text and 'first_dependency_phase' not in text
    assert 'needed_for_current_action' not in text and 'permitted_search_complete' not in text
    assert set(n.transport_payload(p)['review_groups']) == set(p['review_groups'])
    result = n.resolve(answer(p), p)
    assert len(result['reports'][0]['impacts']) == 1
    assert len(result['gap_evidence_map']) == 7


def test_distinct_impact_levels_and_gap_specific_advice_conditions_are_preserved():
    p = payload(gaps=3)
    raw = answer(p)
    review = next(iter(raw['reviews'].values()))
    first = copy.deepcopy(review['impacts'][0])
    first.update(gap_keys=p['gaps'][0:1] and [p['gaps'][0]['key']], level='BLOCKS_ACTION',
                 explanation='First recorded gap blocks the defined analysis if its original condition applies.',
                 conditions=['Confirm the original consuming action and measurement qualification.'])
    second = copy.deepcopy(review['impacts'][0])
    second.update(gap_keys=[g['key'] for g in p['gaps'][1:]], level='UNCERTAIN',
                  explanation='The remaining inputs have unconfirmed source relevance.',
                  conditions=['Retain uncertainty until the original source scope is verified.'])
    review['impacts'] = [first, second]
    original_advice = copy.deepcopy(review['recommendations'][0])
    review['recommendations'] = [
        {**copy.deepcopy(original_advice), 'gap_keys': first['gap_keys'],
         'suggestion': 'Clarify the action-specific design definition.', 'kind': 'DEFINE_ANALYSIS',
         'conditions': first['conditions']},
        {**copy.deepcopy(original_advice), 'gap_keys': second['gap_keys'],
         'suggestion': 'Review the existing source qualification before choosing an option.',
         'kind': 'REVIEW_EXISTING_SOURCE', 'conditions': second['conditions']}]
    expected = copy.deepcopy(review)
    report = n.resolve(raw, p)['reports'][0]
    assert [i['level'] for i in report['impacts']] == ['BLOCKS_ACTION', 'UNCERTAIN']
    assert [i['conditions'] for i in report['impacts']] == [first['conditions'], second['conditions']]
    assert [(a['gap_keys'], a['conditions'], a['suggestion']) for a in report['recommendations']] == [
        (a['gap_keys'], a['conditions'], a['suggestion']) for a in expected['recommendations']]
    assert report['impact_level'] == 'BLOCKS_ACTION'
    assert 'input_supported' not in report


@pytest.mark.parametrize('mutation', ['duplicate_level', 'empty_all_advice', 'blank_explanation',
                                     'blank_suggestion', 'blank_activity', 'blank_question'])
def test_empty_review_content_or_repeated_impact_bucket_is_rejected(mutation):
    p = payload()
    raw = answer(p)
    review = next(iter(raw['reviews'].values()))
    if mutation == 'duplicate_level':
        impact = review['impacts'][0]
        impact['gap_keys'] = [p['gaps'][0]['key']]
        second = copy.deepcopy(impact)
        second['gap_keys'] = [p['gaps'][1]['key']]
        review['impacts'].append(second)
    elif mutation == 'empty_all_advice':
        review.update(can_continue=[], recommendations=[], follow_up=[])
    elif mutation == 'blank_explanation':
        review['impacts'][0]['explanation'] = '  '
    elif mutation == 'blank_suggestion':
        review['recommendations'][0]['suggestion'] = '  '
    elif mutation == 'blank_activity':
        review['can_continue'][0]['activity'] = '  '
    else:
        review['follow_up'][0]['question'] = '  '
    with pytest.raises(PipelineError):
        n.resolve(raw, p)


@pytest.mark.parametrize('mutation', ['omit_gap', 'duplicate_gap', 'unknown_action', 'unknown_ref', 'formal_new_data'])
def test_mapping_and_evidence_errors_fail_closed(mutation):
    p = payload()
    raw = answer(p)
    review = next(iter(raw['reviews'].values()))
    impact = review['impacts'][0]
    if mutation == 'omit_gap':
        impact['gap_keys'] = impact['gap_keys'][:1]
    elif mutation == 'duplicate_gap':
        review['impacts'].append(copy.deepcopy(impact))
    elif mutation == 'unknown_action':
        impact['affected_actions'] = ['FIT_HUMAN_PK']
    elif mutation == 'unknown_ref':
        impact['evidence_refs'] = ['E_FAKE']
    else:
        review['recommendations'][0]['kind'] = 'NEW_DATA'
    with pytest.raises(PipelineError):
        n.resolve(raw, p)


def test_another_study_cannot_support_a_local_impact():
    p = payload(second_scope=True)
    raw = answer(p)
    registry, _ = n.evidence_registry(p)
    wrong = next(eid for eid, row in registry.items() if row['source'] == 'I2:note')
    gid = next(gid for gid, group in p['review_groups'].items() if group['scope_id'] == 'S1')
    raw['reviews'][gid]['impacts'][0]['evidence_refs'].append(wrong)
    with pytest.raises(PipelineError):
        n.resolve(raw, p)


def test_method_option_retains_candidate_identity_and_original_rule_clauses():
    p = payload()
    wire = n.transport_payload(p)
    local = [row for source, row in p['evidence_catalog'].items() if source.startswith('method:local/')]
    assert local and all(row['kind'] == 'METHOD' for row in local)
    assert wire['local_mp_context']['authority'] == 'CANDIDATE_KNOWLEDGE_ONLY_NOT_APPLICABILITY'
    original_rule = rules()[0]
    registry, _ = n.evidence_registry(p)
    for field in ('text', 'conditions', 'exceptions', 'scope', 'requirement', 'usage'):
        assert any(row['source'] == 'main:/rules/0/' + field for row in registry.values())
    raw = answer(p)
    review = next(iter(raw['reviews'].values()))
    review['recommendations'][0]['kind'] = 'METHOD_OPTION'
    result = n.resolve(raw, p)
    assert result['reports'][0]['recommendations'][0]['experiment_authorized'] is False
    assert result['method_preference'] == {'animal_pk': 'MODEL_BASED', 'alternative': 'NCA_IF_APPLICABLE'}


def test_pending_output_dependencies_are_retained_without_new_missingness():
    plan, coverage, catalog = inputs()
    row = coverage['matches'][0]
    row['criteria'][0]['status'] = 'DEFERRED'
    row['deferred_outputs'] = [{'producer_task': 'PK_MODEL', 'output': 'Qualified model output',
                               'evidence': [plan['requirements'][0]['evidence'][0]]}]
    row['deferred_dependencies'] = ['Use after original model evaluation.']
    p = n.build_payload(plan, coverage, catalog, project_rules=rules())
    result = n.resolve(answer(p), p)
    dep = result['reports'][0]['future_dependencies'][0]
    assert dep['outputs'] == row['deferred_outputs'] and dep['dependencies'] == row['deferred_dependencies']


def test_real_prepare_fake_resume_result_replay_and_budget_retention(tmp_path, monkeypatch):
    plan, coverage, catalog = inputs(second_scope=True)
    engine = n._engine()
    monkeypatch.setattr(engine, '_verified_inputs', lambda *args:
        (copy.deepcopy(plan), copy.deepcopy(coverage), copy.deepcopy(catalog), rules()))
    monkeypatch.setattr(n, '_engine', lambda: engine)
    monkeypatch.setattr(n, 'MAX_GROUPS_PER_PART', 1)
    pp = write_json(tmp_path / 'inputs/plan.json', plan)
    cp = write_json(tmp_path / 'inputs/coverage.json', coverage)
    out = tmp_path / 'SYNTHETIC_impact'
    n.prepare(pp, cp, out)
    assert len(engine.verify_prepared(out)[-1]) == 2
    synthetic_calls = []
    def generate(request, **kwargs):
        synthetic_calls.append(request['request_sha256'])
        parts = engine.verify_prepared(out)[-1]
        part = next(p for p in parts if p['request']['request_sha256'] == request['request_sha256'])
        raw = answer(part['payload'])
        raw['request_sha256'] = request['request_sha256']
        return raw
    generate.executor_id = 'SYNTHETIC_INDEPENDENT_IMPACT_ACCEPTANCE'
    first = n.run_prepared(out, generator=generate, max_new_calls=1)
    assert first['complete'] is False and len(synthetic_calls) == 1
    ledger_before = read_json(out / 'provider_budget_ledger.json')
    final = n.run_prepared(out, generator=generate, max_new_calls=1)
    assert final['complete'] is True and len(final['reports']) == 2
    assert len(final['gap_evidence_map']) == 4 and len(synthetic_calls) == 2
    assert n.verify_result(out / 'necessity.json') == final
    ledger_after = read_json(out / 'provider_budget_ledger.json')
    assert ledger_after['provider_elapsed_seconds'] >= ledger_before['provider_elapsed_seconds']
    assert len(ledger_after['attempts']) == 2
    assert n.run_prepared(out, generator=generate) == final and len(synthetic_calls) == 2
