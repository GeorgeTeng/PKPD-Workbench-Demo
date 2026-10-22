import copy
import pytest
from ctxcomp import providers
from ctxcomp.io import digest
from research_pipeline import context_optimization as opt, context_routes, context_model_view
from research_pipeline import data_direct_runtime as rt
from test_context_linear import coverage


@pytest.mark.parametrize('envelope', [
    {'contract_correction': {'prior_rejected_response': {}, 'instruction': 'LOCAL CITATION PATCH'}},
    {'prior_rejected_response': {}},
    {'control': {'request': {'payload': {'contract_correction': {}}}}},
    {'execution': {'operation': 'PATCH_CITATIONS'}},
])
def test_hidden_repairs_never_reach_provider(envelope, tmp_path, monkeypatch):
    payload = {'stage': 'DC-label', 'operation': 'LABEL_SOURCE_PAGE',
               'instructions': 'Label source page.', **envelope}
    req = rt.make_request(payload, {'type': 'object'})
    monkeypatch.setattr(providers, '_codex_generate_raw', lambda *a, **k: pytest.fail('Provider called'))
    with pytest.raises(ValueError, match='repair calls are disabled'):
        providers.codex_generate(req, context_scope=tmp_path)
    with pytest.raises(ValueError, match='repair calls are disabled'):
        context_model_view.project(req)


def test_source_text_and_evidence_are_not_control_envelopes():
    payload = {'stage': 'DC-label', 'operation': 'LABEL_SOURCE_PAGE',
               'source_units': [{'text': 'contract_correction PATCH', 'contract_correction': {}}]}
    assert context_routes.select(payload) == ('data', 'adapter_DC-label')


def sample():
    payload = copy.deepcopy(coverage(['RQ1'])['payload'])
    payload['rules'] = [{'id': 'R'+str(i), 'kind': 'PROJECT_REQUIREMENT',
        'text': 'Rule text '+str(i), 'conditions': ['Only study '+str(i)],
        'exceptions': [], 'usage': {'timing_policy': 'Keep future dependencies without requiring them early. '*3,
        'deadline': 'NOT_SPECIFIED' if i < 9 else 'Before the next action'},
        'scope': {'matrix': 'NOT_SPECIFIED', 'species': ['mouse']}}
        for i in range(10)]
    quote = {'source': 'S1_U1', 'item_id': 'A', 'quote': 'A source-specific observation. '*15}
    payload['requirements'] = [{'id': 'RQ1', 'evidence': [copy.deepcopy(quote)]},
                               {'id': 'RQ2', 'evidence': [copy.deepcopy(quote)]}]
    return payload


@pytest.mark.parametrize('variant', ['baseline', 'dedup', 'scoped'])
def test_profiles_roundtrip_exactly_and_leave_host_unchanged(variant):
    original = sample(); saved = copy.deepcopy(original)
    with opt.experiment_profile(variant):
        actual, audit = opt.optimize(original)
    assert original == saved
    assert opt.expand(actual) == original
    assert audit['roundtrip_exact']
    assert audit['before_sha256'] == audit['restored_sha256']
    if variant != 'baseline':
        assert actual['context_rule_defaults']['rules']['usage']['deadline'] == 'NOT_SPECIFIED'
        assert actual['rules'][9]['usage']['deadline'] == 'Before the next action'
        assert actual['rules'][0]['conditions'] == ['Only study 0']
        assert audit['quote_definitions'] == 1
        assert audit['characters_after'] < audit['characters_before']


def test_equal_text_different_source_scope_is_not_merged():
    p = sample()
    p['requirements'][1]['evidence'][0]['item_id'] = 'B'
    with opt.experiment_profile('dedup'):
        result, audit = opt.optimize(p)
    assert not audit['quote_definitions']
    assert result['requirements'] == p['requirements']


def test_missing_field_is_not_filled_with_invented_default():
    p = sample(); del p['rules'][0]['usage']['deadline']
    with opt.experiment_profile('dedup'):
        result, audit = opt.optimize(p)
    assert 'deadline' not in result.get('context_rule_defaults', {}).get('rules', {}).get('usage', {})
    assert opt.expand(result) == p


def test_explicit_empty_value_overrides_common_default():
    p = sample(); p['rules'][4]['usage']['timing_policy'] = ''
    with opt.experiment_profile('dedup'):
        result, audit = opt.optimize(p)
    assert result['rules'][4]['usage']['timing_policy'] == ''
    assert opt.expand(result) == p


def test_experiment_profile_is_task_local_and_resets():
    from concurrent.futures import ThreadPoolExecutor
    with opt.experiment_profile('dedup'):
        assert opt.optimize(sample())[1]['profile'] == 'dedup'
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(opt.optimize, sample()).result()[1]['profile'] == 'baseline'
    assert opt.optimize(sample())[1]['profile'] == 'baseline'


def test_summary_rejects_raw_evidence_even_in_legacy_projection():
    p = {'stage': 'HUMAN_REVIEW_SUMMARY_ONLY', 'assessment': {}, 'analyses': [], 'raw_tables': []}
    with pytest.raises(ValueError, match='Out-of-stage'):
        opt.optimize(p)


def test_unknown_scope_keeps_all_mp_and_evidence():
    p = sample(); p['stage'] = 'DC-review'; p['method_knowledge'] = {'profiles': [{'id': 'MP007'}]}
    p['source_units'] = [{'text': 'Full source content', 'id': 'S1'}]
    with opt.experiment_profile('scoped'):
        result, audit = opt.optimize(p)
    assert opt.expand(result) == p
    assert audit['dropped_evidence'] == audit['dropped_scientific_rules'] == []


def test_focused_profile_uses_existing_contract_and_never_failed_output():
    p = {'stage': 'NECESSITY_SCOPED_ASSESSMENT',
         'instructions': 'Keep all generated prose under 1100 words. '
             'Each action finding <=45 words; next_step <=25 words; source_scope <=20 words. '
             'The assessment opinion is one direct sentence, <=30 words.',
         'recorded_shortages': {'RQ001:F2': {'status': 'PARTIAL'}, 'RQ002:C1': {'status': 'CONFLICT'}},
         'schema': {'properties': {'action_decisions': {'properties': {'NCA': {}}}}}}
    with opt.experiment_profile('focused'):
        wire, audit = opt.optimize(p)
    assert wire['output_focus']['analysis_gap_ids_exactly_once'] == ['RQ001:F2', 'RQ002:C1']
    assert wire['output_focus']['action_decision_keys'] == ['NCA']
    assert opt.expand(wire) == p
    assert 'prior_rejected_response' not in str(wire)
    with opt.experiment_profile('focused'), pytest.raises(ValueError, match='explicit 1100-word'):
        opt.optimize(sample())
    p['instructions'] = p['instructions'].replace('<=45', '<=30')
    with opt.experiment_profile('focused'), pytest.raises(ValueError, match='explicit 1100-word'):
        opt.optimize(p)
