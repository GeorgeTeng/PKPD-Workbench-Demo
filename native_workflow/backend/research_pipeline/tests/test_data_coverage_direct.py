import copy
import json

import pytest
from research_pipeline import data_coverage_direct as c
from research_pipeline.common import PipelineError, read_json, write_json


@pytest.fixture
def case(tmp_path):
    main = write_json(tmp_path/'main.json', {'objective': 'Compare existing mouse data.',
        'rules': [{'id': 'R001', 'text': 'Preserve scope.', 'conditions': ['same study'],
                   'exceptions': ['none'], 'scope': 'PK', 'evidence': {'redundant': 'wrapper'}}],
        'data': {'files': [{'id': 'F1', 'name': 'study.xlsx'}, {'id': 'F2', 'name': 'benchmark.xlsx'}]}})
    plan = write_json(tmp_path/'plan.json', {'bindings': {'main': c.rt.file_ref(main),
        'historical_producer': {'path': 'nonexistent historical implementation', 'sha256': 'old'}},
        'requirements': [{'id': 'RQ1', 'description': 'Exposure', 'input_fields': ['dose', 'concentration'],
                          'conditions': ['Only measured concentrations'], 'method_uses': ['model based'],
                          'evidence': {'redundant': 'wrapper'}},
                         {'id': 'RQ2', 'description': 'PD', 'input_fields': ['MIC'], 'conditions': []}]})
    items = [('F1:mouse', 'Mouse', 'PK', 'REVIEW_DATA'),
             ('F1:rat', 'Rat', 'PK', 'REVIEW_DATA'),
             ('F1:horse', 'Horse', 'PK', 'REVIEW_DATA'),
             ('F1:human', 'Human', 'PK', 'REVIEW_DATA'),
             ('F1:notes', 'Mouse, Horse', 'SUPPORTING_EVIDENCE', 'REVIEW_DATA'),
             ('F2:body', 'Mouse', 'PK', 'REVIEW_DATA'),
             ('F1:restricted', 'Mouse', 'PK', 'REFERENCE_ONLY')]
    source = write_json(tmp_path/'source.json', {'main_ref': c.rt.file_ref(main),
        'profiles': [{'item_id': i, 'species': s, 'role': r, 'columns': [], 'stated_values': ['duplicate']}
                     for i,s,r,p in items],
        'permissions': [{'item_id': i, 'disposition': p} for i,s,r,p in items],
        'source_units': {i+':row1': i+' literal µg/mL; no invented join' for i,s,r,p in items}})
    return plan, source, main, tmp_path/'run'


def answer(request, **kwargs):
    checks = {}
    for r in request['payload']['requirements']:
        fields = {name: {'status': 'UNRESOLVED', 'summary': 'Evidence does not establish this field.',
                        'source_scopes': [], 'unresolved_information': 'The relevant value is unconfirmed.',
                        'not_applicable_condition': ''} for name in r['input_fields']}
        checks[r['id']] = {'status': 'UNRESOLVED', 'summary': 'Unconfirmed information.',
                           'fields': fields, 'condition_gaps': []}
    return {'request_sha256': request['request_sha256'], 'checks': checks}


def prepared(case):
    build = c.prepare(*case)
    request = read_json(build['parts'][0]['request_ref']['path'])
    catalog = read_json(build['source_catalog_ref']['path'])
    return build, request, catalog, answer(request)


def supported(raw):
    field = raw['checks']['RQ1']['fields']['dose']
    field.update(status='SUPPORTED', summary='A dose is reported.', unresolved_information='',
        source_scopes=[{'item_id': 'F1:mouse', 'scope_note': 'Mouse study only.', 'source_ids': ['F1:mouse:row1']}])
    raw['checks']['RQ1']['status'] = 'PARTIAL'
    return field


def test_complete_direct_handoff_exact_replay_and_cache(case):
    build, request, catalog, raw = prepared(case)
    supported(raw)
    calls = []
    def generate(request, **kwargs):
        calls.append(1)
        return raw
    result = c.run_prepared(case[3], generator=generate)
    assert c.verify_result(case[3]/'coverage.json') == result
    assert c.run_prepared(case[3], generator=generate) == result and len(calls) == 1
    assert result['requirements'] == read_json(case[0])['requirements']
    assert len(result['checks']) == 2
    assert result['scope'] == 'DR_COMPARISON_ONLY' and result['direct_next_stage'] == 'NECESSITY'
    assert result['execution'] == {'test_generator': True, 'requested_model': 'gpt-6-sol', 'served_models': []}
    evidence = result['checks']['RQ1']['fields']['dose']['source_scopes'][0]['evidence'][0]
    assert evidence['quote'] == catalog['F1:mouse:row1']['quote']
    assert not result['scientific_approval'] and not result['can_enter_qc']
    assert set(build['bindings']) == {'direct_runtime', 'governance', 'coverage_code', 'plan', 'source_view', 'main'}
    with pytest.raises(PipelineError, match='Synthetic'):
        c.run_prepared(case[3])


def test_permission_holdout_and_projection(case):
    build, request, catalog, raw = prepared(case)
    assert set(catalog) == {'F1:mouse:row1', 'F1:rat:row1', 'F1:notes:row1'}
    payload = request['payload']
    assert 'evidence' not in payload['requirements'][0]
    assert 'evidence' not in payload['rules'][0]
    assert payload['rules'][0]['exceptions'] == ['none']
    assert all('stated_values' not in p for p in payload['profiles'])
    assert next(p for p in payload['profiles'] if p['item_id'] == 'F1:notes')['evidence_role'].startswith('CONTEXT_ONLY')


@pytest.mark.parametrize('damage', ['omitted_field', 'extra_requirement', 'action', 'foreign_source',
    'cross_item', 'duplicate_scope', 'unknown_condition', 'bad_overall', 'empty_summary', 'hidden_uncertainty'])
def test_invalid_claims_fail_closed(case, damage):
    build, request, catalog, raw = prepared(case)
    field = supported(raw)
    if damage == 'omitted_field': del raw['checks']['RQ1']['fields']['concentration']
    if damage == 'extra_requirement': raw['checks']['RQ3'] = copy.deepcopy(raw['checks']['RQ2'])
    if damage == 'action': field['recommendation'] = 'Fit now.'
    if damage == 'foreign_source': field['source_scopes'][0]['source_ids'] = ['F1:horse:row1']
    if damage == 'cross_item': field['source_scopes'][0]['source_ids'] = ['F1:rat:row1']
    if damage == 'duplicate_scope': field['source_scopes'] *= 2
    if damage == 'unknown_condition':
        field.update(status='NOT_APPLICABLE', not_applicable_condition='Invented exemption')
    if damage == 'bad_overall': raw['checks']['RQ1']['status'] = 'SUPPORTED'
    if damage == 'empty_summary': field['summary'] = '  '
    if damage == 'hidden_uncertainty': field['unresolved_information'] = 'Actually not linked.'
    with pytest.raises(ValueError):
        c.validate(raw, build['requirements'], catalog)


def test_not_applicable_requires_original_condition_and_evidence(case):
    build, request, catalog, raw = prepared(case)
    field = supported(raw)
    field.update(status='NOT_APPLICABLE', not_applicable_condition='Only measured concentrations')
    raw['checks']['RQ1']['status'] = 'UNRESOLVED'
    c.validate(raw, build['requirements'], catalog)
    field['source_scopes'] = []
    with pytest.raises(PipelineError, match='local evidence'):
        c.validate(raw, build['requirements'], catalog)


def test_original_condition_gap_blocks_full_support(case):
    build, request, catalog, raw = prepared(case)
    field = supported(raw)
    raw['checks']['RQ1']['fields']['concentration'] = copy.deepcopy(field)
    raw['checks']['RQ1']['condition_gaps'] = [{'condition': 'Only measured concentrations',
        'summary': 'Measurement identity unconfirmed.', 'source_ids': []}]
    c.validate(raw, build['requirements'], catalog)
    raw['checks']['RQ1']['status'] = 'SUPPORTED'
    with pytest.raises(PipelineError, match='Overall status'):
        c.validate(raw, build['requirements'], catalog)


@pytest.mark.parametrize('stage', ['before', 'during', 'after'])
def test_actual_inputs_drift_blocks_execution_or_handoff(case, stage):
    prepared(case)
    def change():
        value = read_json(case[1]); value['new_content'] = True; write_json(case[1], value)
    if stage == 'before': change()
    def generate(request, **kwargs):
        if stage == 'during': change()
        return answer(request)
    if stage != 'after':
        with pytest.raises(PipelineError, match='Active input changed'):
            c.run_prepared(case[3], generator=generate)
        assert not (case[3]/'coverage.json').exists()
    else:
        c.run_prepared(case[3], generator=generate); change()
        with pytest.raises(PipelineError, match='Active input changed'):
            c.verify_result(case[3]/'coverage.json')


def test_transport_splits_only_complete_requirements(case, monkeypatch):
    bindings, requirements, catalog, wire = c._inputs(*case[:3])
    full = c.rt.make_request(wire, c.response_schema(wire['requirements']))
    one_sizes = [len(json.dumps(c.rt.make_request({**wire, 'requirements': [r]}, c.response_schema([r])), ensure_ascii=False)) for r in wire['requirements']]
    assert max(one_sizes) < len(json.dumps(full, ensure_ascii=False))
    monkeypatch.setattr(c.rt, 'MAX_REQUEST_CHARS', max(one_sizes))
    parts = c._requests(wire)
    assert [[r['id'] for r in reqs] for reqs, request in parts] == [['RQ1'], ['RQ2']]
    assert all(request['payload']['source_units'] == wire['source_units'] for reqs, request in parts)
