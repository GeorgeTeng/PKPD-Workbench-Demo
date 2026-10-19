import copy
import pytest
from research_pipeline import data_necessity_direct as nec, data_coverage_direct as cov
from research_pipeline.common import read_json, write_json, PipelineError


@pytest.fixture
def case(tmp_path, monkeypatch):
    main = write_json(tmp_path/'main.json', {'objective': 'Animal PK', 'rules': []})
    coverage = {'requirements': [{'id': 'RQ001', 'input_fields': ['Dose', 'Animal ID'], 'conditions': []}],
        'checks': {'RQ001': {'status': 'PARTIAL', 'summary': 'Group means present, animal IDs unresolved.',
            'fields': {'Dose': {'status': 'SUPPORTED', 'summary': 'Reported dose'},
                       'Animal ID': {'status': 'UNRESOLVED', 'summary': 'Group means',
                           'unresolved_information': 'Individual identities not established',
                           'source_scopes': [{'item_id': 'A', 'scope_note': 'A group means', 'source_ids': ['A:1']}] }},
            'condition_gaps': []}}, 'bindings': {'main': nec.rt.file_ref(main)},
        'execution': {'test_generator': True}}
    coverage_path = write_json(tmp_path/'coverage.json', coverage)
    monkeypatch.setattr(cov, 'verify_result', lambda path: read_json(path))
    mp = write_json(tmp_path/'mp.json', {'profiles': [{'id': 'MP004'}]})
    out = tmp_path/'necessity'
    prepared = nec.prepare(coverage_path, main, mp, out)
    return out, prepared


def answer(request, **kwargs):
    return {'request_sha256': request['request_sha256'], 'analyses': [{
        'gap_ids': list(request['payload']['recorded_shortages']), 'affected_scope': 'A group summary study',
        'next_action': 'Assess aggregate model inputs', 'impact': 'LIMITS_ANALYSIS',
        'impact_summary': 'Does not establish individual IIV inputs', 'can_continue': ['Aggregate input preparation'],
        'recommendation_kind': 'CLARIFY', 'recommendation': 'Clarify any existing individual records',
        'conditions_to_verify': ['Whether individual records exist'], 'local_method_profile_ids': ['MP004']}]}


def test_direct_handoff_one_actual_shortage_one_call_and_reuse(case):
    out, prepared = case
    assert list(prepared['gaps']) == ['RQ001:F2']
    calls = []
    def provider(request, **kwargs):
        calls.append(1)
        return answer(request)
    result = nec.run_prepared(out, generator=provider)
    assert result['analyses'][0]['requirement_ids'] == ['RQ001']
    assert nec.verify_result(out/'necessity.json') == result
    assert nec.run_prepared(out, generator=provider) == result and len(calls) == 1
    assert not result['downstream_executed'] and not result['scientific_approval']


@pytest.mark.parametrize('damage', ['omit', 'duplicate', 'invent', 'formal_new_data', 'conditional_no_conditions'])
def test_no_lost_invented_or_overstated_gap(case, damage):
    out, prepared = case
    def bad(request, **kwargs):
        raw = answer(request)
        if damage == 'omit': raw['analyses'] = []
        elif damage == 'duplicate': raw['analyses'].append(copy.deepcopy(raw['analyses'][0]))
        elif damage == 'invent': raw['analyses'][0]['gap_ids'] = ['INVENTED']
        elif damage == 'formal_new_data': raw['analyses'][0]['recommendation_kind'] = 'NEW_EXPERIMENT_REQUIRED'
        else:
            raw['analyses'][0]['recommendation_kind'] = 'CONDITIONAL_NEW_DATA'
            raw['analyses'][0]['conditions_to_verify'] = []
        return raw
    with pytest.raises(Exception):
        nec.run_prepared(out, generator=bad)
    assert not (out/'necessity.json').exists()


def test_no_synthetic_coverage_in_real_run(case):
    out, _ = case
    with pytest.raises(PipelineError, match='synthetic Coverage'):
        nec.run_prepared(out)


def test_changed_actual_input_blocks_reuse(case):
    out, prepared = case
    nec.run_prepared(out, generator=answer)
    write_json(prepared['bindings']['main']['path'], {'objective': 'changed'})
    with pytest.raises(PipelineError, match='Active input changed'):
        nec.verify_result(out/'necessity.json')


def test_tampered_handoff_rejected(case):
    out, _ = case
    result = nec.run_prepared(out, generator=answer)
    result['scientific_approval'] = True
    write_json(out/'necessity.json', result)
    with pytest.raises(PipelineError, match='metadata changed'):
        nec.verify_result(out/'necessity.json')


def test_transport_schema_without_uniqueitems_still_checks_duplicates(case):
    import json
    out, prepared = case
    assert 'uniqueItems' not in json.dumps(prepared['request']['payload']['schema'])
    def duplicate(request, **kwargs):
        raw = answer(request)
        raw['analyses'][0]['local_method_profile_ids'] *= 2
        return raw
    with pytest.raises(PipelineError, match='repeated values'):
        nec.run_prepared(out, generator=duplicate)
