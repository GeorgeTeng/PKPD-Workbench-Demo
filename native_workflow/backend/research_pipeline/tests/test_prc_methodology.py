"""Adopted-method contract regressions; fixture judgments are not LLM accuracy."""
import copy
from pathlib import Path

import pytest
from ctxcomp.io import digest
from research_pipeline import project_rule_agent as a
from research_pipeline.common import PipelineError, read_json, write_json
from test_project_rule_agent import bundle, extraction, reviewer, run


def test_both_agents_receive_adopted_methods_and_full_rule_text_once(bundle):
    value = bundle[2]
    first = a.request(value, 'project_rules_extract')
    second = a.request(value, 'project_rules_review', extraction(first))
    for req in (first, second):
        p = req['payload']
        assert [m['id'] for m in p['extraction_methodology']['adopted_methods']] == ['M01', 'M02', 'M03']
        assert [r['id'] for r in p['processing_rules']] == ['PRC001','PRC002','PRC003','PRC004','PRC005','PRC006','PRC007']
        assert all(r['text'] and r['checks'] for r in p['processing_rules'])
        assert len(p['scientific_preservation']['cc005_details.json']['preserve']) == 13
        assert p['policy_sha256'] == digest(value['extraction_policy'])
        assert req['request_sha256'] == digest(p)
    assert first['request_sha256'] != second['request_sha256']


@pytest.mark.parametrize('mode', ['missing_action', 'blank_action', 'missing_binding', 'extra_binding', 'invented_quote', 'unknown_slot'])
def test_slot_or_evidence_contract_errors_stop_before_review(bundle, mode):
    def bad(req, **kwargs):
        c = extraction(req); item = c['items'][0]
        if mode == 'missing_action': item['requirement']['action'] = 'NOT_SPECIFIED'
        elif mode == 'blank_action': item['requirement']['action'] = '  '
        elif mode == 'missing_binding': item['field_evidence'].pop()
        elif mode == 'extra_binding': item['field_evidence'].append(copy.deepcopy(item['field_evidence'][0]))
        elif mode == 'invented_quote': item['field_evidence'][0]['spans'][0]['quote'] = 'An unsupported quotation'
        else: item['requirement']['time'] = 'invented slot'
        return c
    with pytest.raises(ValueError): run(bundle, generator=bad)
    assert (bundle[0]/'extraction/response.json').is_file()
    assert not (bundle[0]/'review').exists()
    assert not (bundle[0]/'published/main.json').exists()


@pytest.mark.parametrize('mode', ['reverse', 'forward'])
def test_coverage_cannot_hide_or_invent_source_links(bundle, mode):
    def bad(req, **kwargs):
        c = extraction(req)
        if mode == 'reverse':
            c['source_coverage'][0].update(item_ids=[], disposition='NO_REQUIREMENT')
        else:
            c['source_coverage'][1]['item_ids'].append('P1')
        return c
    with pytest.raises(PipelineError, match='coverage'): run(bundle, generator=bad)


def test_conditions_and_phase_get_separate_bindings_and_remain_in_final_review(bundle):
    captured = []
    def conditional(req, **kwargs):
        captured.append(req['payload']['stage'])
        c = extraction(req); item = c['items'][0]
        item['conditions'] = ['after predictions are frozen']
        item['requirement']['workflow_phase'] = 'final validation'
        item['field_evidence'] = [{'path': p, 'spans': copy.deepcopy(item['evidence'])}
                                  for p in a.required_field_paths(item)]
        return c
    def inspect_review(req, **kwargs):
        captured.append(req['payload']['stage'])
        final = req['payload']['publication_candidate']['rules'][0]
        assert final['conditions'] == ['after predictions are frozen']
        assert 'Conditions: after predictions are frozen.' in final['text']
        assert final['usage']['required_phase'] == 'final validation'
        assert final['usage']['source_window'] == 'NOT_SPECIFIED'
        return reviewer(req)
    result = run(bundle, generator=conditional, review_generator=inspect_review)
    preview = read_json(bundle[0]/'review/publication_candidate.json')
    published = read_json(result['project_rules_ref']['path'])
    assert published['rules'] == preview['rules']
    assert digest(published['rules']) == read_json(result['audit_ref']['path'])['final_rules_sha256']
    assert captured == ['project_rules_extract', 'project_rules_review']


@pytest.mark.parametrize('mode', ['wrong_hash', 'missing_final_check', 'false_pass'])
def test_review_must_bind_and_pass_final_collection(bundle, mode):
    def invalid(req, **kwargs):
        response = reviewer(req)
        if mode == 'wrong_hash': response['final_rules_sha256'] = 'old'
        elif mode == 'missing_final_check': response['final_rule_checks'].pop()
        else: response['final_rule_checks'][0]['verdict'] = 'REVISE'
        return response
    with pytest.raises(ValueError): run(bundle, review_generator=invalid)
    assert not (bundle[0]/'published/main.json').exists()


def test_semantic_error_requires_reviewer_even_if_quote_is_valid(bundle):
    # Contract validation deliberately cannot detect the meaning of every clause.
    def shifted(req, **kwargs):
        c = extraction(req)
        c['items'][0]['text'] = 'Use human PK to calibrate the initial prediction.'
        c['items'][0]['requirement']['action'] = 'Calibrate the initial prediction with human PK'
        return c
    def reject(req, **kwargs):
        r = reviewer(req); r['decision'] = 'REVISE'
        next(x for x in r['global_checks'] if x['id']=='GROUNDING')['verdict'] = 'REVISE'
        r['findings'] = [{'code':'UNSUPPORTED_RULE', 'severity':'REQUIRES_CLARIFICATION', 'item_ids':['P1'],
                         'reason':'The retained source limits human PK to validation.',
                         'needed_material':'Correct the extraction; no new scientific data is required.'}]
        return r
    result = run(bundle, generator=shifted, review_generator=reject)
    assert result['status'] == 'RULES_REVISION_REQUIRED'
    assert not (bundle[0]/'published/main.json').exists()


def test_non_rule_cannot_sneak_in_normative_slots(bundle):
    req = a.request(bundle[2], 'project_rules_extract'); c = extraction(req)
    c['items'][2]['requirement']['forms'] = ['REQUIRED_ACTION']
    with pytest.raises(PipelineError, match='Non-rule'):
        a.validate_candidate(c, req, bundle[2])


def test_unspecified_actor_deadline_are_not_invented_or_blocking(bundle):
    result = run(bundle)
    rule = read_json(result['project_rules_ref']['path'])['rules'][0]
    assert rule['requirement']['actor'] == 'NOT_SPECIFIED'
    assert rule['usage']['deadline'] == 'NOT_SPECIFIED'
    assert '/requirement/actor' not in {x['path'] for x in rule['field_evidence']}


def test_slots_with_different_meanings_are_not_merged(bundle):
    def differing(req, **kwargs):
        c = extraction(req); same = copy.deepcopy(c['items'][0]); same['id'] = 'DIFFERENT'
        same['requirement']['forms'] = ['PROHIBITION']
        c['items'].append(same); c['source_coverage'][0]['item_ids'].append('DIFFERENT')
        return c
    result = run(bundle, generator=differing)
    assert result['rule_count'] == 3


def test_governance_snapshot_is_used_for_a_new_contract(bundle, monkeypatch):
    before = a.request(bundle[2], 'project_rules_extract')
    monkeypatch.setattr(a, 'load_governance', lambda: {'version':'future'})
    assert a.request(bundle[2], 'project_rules_extract') == before


def test_changed_policy_snapshot_is_rejected(bundle):
    root, ref, value = bundle
    value['extraction_policy']['methodology']['execution'] = 'Skip independent review'
    write_json(ref['path'], value)
    with pytest.raises(PipelineError, match='policy'):
        a.validate_input(a.file_ref(ref['path']))


def test_historical_policy_keeps_its_numbering_in_both_agents(bundle):
    root, ref, value = bundle
    old = read_json(a.POLICY_PATH.with_name('extraction_policy.1.2.json'))
    value.update(extraction_policy=old, policy_sha256=digest(old), processing_rules=copy.deepcopy(old['rules']))
    write_json(ref['path'], value)
    frozen = a.validate_input(a.file_ref(ref['path']))
    first = a.request(frozen, 'project_rules_extract')
    second = a.request(frozen, 'project_rules_review', extraction(first))
    for req in (first, second):
        assert req['payload']['processing_rules'] == old['rules']
        assert req['payload']['policy_version'] == '1.2.0'
    value['processing_rules'] = copy.deepcopy(a.PROCESSING_RULES)
    write_json(ref['path'], value)
    with pytest.raises(PipelineError, match='processing rules'):
        a.validate_input(a.file_ref(ref['path']))


def test_unregistered_policy_cannot_self_authorize_with_a_matching_hash(bundle):
    root, ref, value = bundle
    value['extraction_policy']['version'] = 'unregistered'
    value['policy_sha256'] = digest(value['extraction_policy'])
    write_json(ref['path'], value)
    with pytest.raises(PipelineError, match='policy'):
        a.validate_input(a.file_ref(ref['path']))
