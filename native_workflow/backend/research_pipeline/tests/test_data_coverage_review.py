import copy
import json

import pytest

from research_pipeline import data_coverage_review as c
from research_pipeline.adequacy import file_ref
from research_pipeline.common import PipelineError, write_json
from ctxcomp.io import digest


@pytest.fixture
def setup(tmp_path, monkeypatch):
    from research_pipeline import data_requirement_planning
    monkeypatch.setattr(data_requirement_planning, 'verify_plan', c.read_json)
    main = write_json(tmp_path / 'main.json', {'objective': 'Mouse plasma profile'})
    raw = write_json(tmp_path / 'raw.json', {'source': 'synthetic'})
    items = []
    units = {}
    for id, species in [('M', 'Mouse'), ('R', 'Rabbit')]:
        item = {'id': id, 'kind': 'TABLE', 'source': file_ref(raw), 'snapshot': file_ref(raw),
                'descriptor': {'sheet': species, 'headers': ['Time', 'Concentration']},
                'region': {'start_row': 1, 'header_row': 2, 'end_row': 3, 'left': 1, 'right': 2}}
        items.append(item)
        units.update({id: json.dumps(item['descriptor'], ensure_ascii=False), id + ':A1': species + ' dose 2 mg/kg',
                      id + ':A2': 'Time', id + ':B2': 'Concentration', id + ':A3': '1', id + ':B3': '2.5'})
    doc = {'id': 'F0005:document', 'kind': 'DOCUMENT', 'descriptor': {'registered_role': 'SUPPORTING_DOCUMENT'},
           'source': file_ref(raw), 'snapshot': file_ref(raw)}
    items.append(doc)
    units.update({doc['id']: json.dumps(doc['descriptor']), doc['id'] + ':line1': 'Mouse regimen: 2 mg/kg at time zero.'})
    protected = {'id': 'SECRET', 'kind': 'PROTECTED', 'descriptor': {}, 'source': {'path': 'DO_NOT_OPEN', 'sha256': 'x'}}
    items.append(protected)
    inv = {'main': file_ref(main), 'items': items}
    source = tmp_path / 'sources'
    write_json(source / 'inventory.json', inv)
    view = {'main_ref': file_ref(main), 'source_units': units, 'permissions': [
        {'item_id': i['id'], 'disposition': 'REFERENCE_ONLY' if i['id'] == 'SECRET' else 'REVIEW_DATA'} for i in items],
        'legacy_findings': [{'reason': 'OLD_GAP_DO_NOT_SEND'}]}
    write_json(source / 'source_view.json', view)
    def content(item):
        assert item['id'] != 'SECRET'
        return [(k, v) for k, v in units.items() if k.startswith(item['id'] + ':')]
    def cells(item):
        if item['kind'] == 'DOCUMENT':
            return content(item)
        return [(k, {'row': int(k[-1]), 'column': 1 if k[-2] == 'A' else 2, 'value': v}) for k, v in content(item)]
    monkeypatch.setattr(c.data, 'content_units', content)
    monkeypatch.setattr(c.data, 'content_cells', cells)
    monkeypatch.setattr(c.data, 'source_map', lambda *_: {'main:/objective': 'Mouse plasma profile'})
    from research_pipeline import data_test_workflow
    monkeypatch.setattr(data_test_workflow, 'embedded_projection', lambda *_: [])
    need = {'id': 'Q', 'task_id': 'PK', 'description': 'Plasma concentrations', 'kind': 'DATA',
            'required_by': 'BEFORE_MODELING', 'fields': ['concentration'], 'conditions': [],
            'origin': 'METHOD_CANDIDATE', 'analysis': 'MODEL_BASED', 'necessity': 'REQUIRED',
            'rule_ids': [], 'evidence': [{'source': 'main:/objective', 'quote': 'Mouse plasma profile'}]}
    plan = {'version': 'REQUIREMENT_PLANNING_3.0', 'requirements': [need], 'methods': [
        {'id': 'MODEL-M', 'group_id': 'G', 'family': 'MODEL_BASED',
         'scope': {'study': 'S', 'species': 'Mouse', 'matrix': 'plasma', 'record_level': 'means'},
         'dataset_ids': ['M'], 'supporting_item_ids': [], 'requirement_ids': ['Q'], 'conditions': []}],
        'bindings': {'main': file_ref(main), 'source_view': file_ref(source / 'source_view.json'),
                     'inventory': file_ref(source / 'inventory.json')}}
    return plan, source, tmp_path


def response(payload, request_sha256='test'):
    answers = []
    for unit in payload['units']:
        evidence = [{'source': unit['dataset_ids'][0] + ':B3', 'quote': '2.5'}]
        answers.append({'method_id': unit['method_id'], 'reviewed_item_ids': unit['criterion_plan']['assigned_item_ids'],
                        'unread_item_ids': [], 'match': {'requirement_id': unit['requirement']['id'],
             'status': 'AVAILABLE_CANDIDATE', 'source_ids': [evidence[0]['source']], 'reason': 'Original cells supplied',
             'needed_material': 'None', 'deferred_outputs': [], 'criteria': [
                 {'id': cr['id'], 'status': 'SUPPORTED', 'evidence': evidence, 'reason': 'Synthetic evidence',
                  'needed_material': 'None'} for cr in unit['criterion_plan']['criteria']]}})
    return {'request_sha256': request_sha256, 'matches': answers}


def test_full_body_notes_and_regimen_no_history_or_other_species(setup):
    plan, source, _ = setup
    original = copy.deepcopy(plan)
    p = c.build(plan, source)['payloads'][0]
    assert plan == original
    assert 'F0005:document:line1' in p['evidence_catalog']
    assert p['evidence_catalog']['M:A1']['kind'] == 'SOURCE_NOTE'
    assert p['evidence_catalog']['M:A2']['kind'] == 'SOURCE_HEADER'
    assert p['evidence_catalog']['M:B3']['kind'] == 'SOURCE_CONTENT'
    assert not any(k.startswith(('R:', 'SECRET')) for k in p['evidence_catalog'])
    assert 'OLD_GAP_DO_NOT_SEND' not in json.dumps(p)
    assert 'necessity' not in p['units'][0]['requirement']
    assert c.validate(response(p), p)[0]['coverage_status'] == 'AVAILABLE_CANDIDATE'


@pytest.mark.parametrize('fault', ['header', 'other_species', 'wrong_quote', 'missing_criterion', 'duplicate_unit', 'unread_missing'])
def test_original_checks_and_scope_reject(setup, fault):
    plan, source, _ = setup
    p = c.build(plan, source)['payloads'][0]; answer = response(p); a = answer['matches'][0]; m = a['match']
    if fault in ['header', 'other_species', 'wrong_quote']:
        e = {'header': {'source': 'M:B2', 'quote': 'Concentration'},
             'other_species': {'source': 'R:B3', 'quote': '2.5'},
             'wrong_quote': {'source': 'M:B3', 'quote': 'invented'}}[fault]
        m['criteria'][0]['evidence'] = [e]
        m['source_ids'] = list({x['source'] for cr in m['criteria'] for x in cr['evidence']})
    elif fault == 'missing_criterion': m['criteria'].pop()
    elif fault == 'duplicate_unit': answer['matches'].append(copy.deepcopy(a))
    else:
        a['reviewed_item_ids'] = ['M']; a['unread_item_ids'] = ['F0005:document']
        for cr in m['criteria']:
            cr.update(status='MISSING', evidence=[], needed_material='Read supporting source')
        m.update(status='MISSING', source_ids=[], needed_material='Read supporting source')
    with pytest.raises(PipelineError): c.validate(answer, p)


def test_unread_remains_unresolved_not_missing(setup):
    plan, source, _ = setup; p = c.build(plan, source)['payloads'][0]; a = response(p)
    row = a['matches'][0]; row['reviewed_item_ids'] = ['M']; row['unread_item_ids'] = ['F0005:document']
    for cr in row['match']['criteria']:
        cr.update(status='UNRESOLVED', evidence=[], needed_material='Complete supporting document review')
    row['match'].update(status='UNRESOLVED', source_ids=[], needed_material='Complete review')
    assert c.validate(a, p)[0]['status'] == 'UNRESOLVED'


def test_same_requirement_isolated_per_method(setup):
    plan, source, _ = setup
    second = copy.deepcopy(plan['methods'][0]); second.update(id='MODEL-R', dataset_ids=['R']);second['scope']['species']='Rabbit'
    plan['methods'].append(second)
    p = c.build(plan, source)['payloads'][0]
    assert len(c.validate(response(p), p)) == 2
    a = response(p); a['matches'][0]['match'] = copy.deepcopy(a['matches'][1]['match'])
    with pytest.raises(PipelineError): c.validate(a, p)


def test_budget_fails_before_provider(setup, monkeypatch):
    plan, source, _ = setup; monkeypatch.setattr(c, 'SOFT_BUDGET', 1)
    with pytest.raises(PipelineError, match='budget'): c.build(plan, source)


def test_prepare_run_and_proof_replay(setup):
    plan, source, folder = setup
    pp = write_json(folder / 'plan.json', plan); out = folder / 'coverage'
    c.prepare(pp, source, out)
    calls = []
    def generator(request, **kwargs):
        calls.append(kwargs['model'])
        return response(request['payload'], request['request_sha256'])
    generator.executor_id = 'coverage-fixture'
    result = c.run(pp, source, out, generator)
    assert calls == ['gpt-6-luna']
    assert result['planning_sha256'] == digest(plan)
    assert c.verify_result(out / 'coverage.json') == result
    source_text = c.result_sources(out / 'coverage.json')
    assert source_text['F0005:document:line1'] == 'Mouse regimen: 2 mg/kg at time zero.'
    assert 'M' not in source_text  # Descriptors are not original body/note evidence.
    assert result['scope']['project_coverage_complete'] is False
    assert next(i for i in result['scope']['items'] if i['item_id'] == 'SECRET')['assigned_methods'] == []
    c.run(pp, source, out, generator)
    assert len(calls) == 1  # Original checked cache, no new provider call.
    bad = copy.deepcopy(result); bad['matches'][0]['criteria'][0]['reason'] = 'Handwritten replacement'
    write_json(out / 'coverage.json', bad)
    with pytest.raises(PipelineError, match='original response'): c.verify_result(out / 'coverage.json')


def test_tampered_source_view_rejected(setup):
    plan, source, _ = setup
    view = c.read_json(source / 'source_view.json'); view['source_units']['M:B3'] = '999'
    write_json(source / 'source_view.json', view)
    with pytest.raises(PipelineError): c.build(plan, source)
