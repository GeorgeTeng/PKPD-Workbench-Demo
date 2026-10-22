"""Simplified DR boundaries; all generators are local fixtures, never providers."""
import copy
import json
import pytest
from research_pipeline import data_requirement_plan_v4 as p


@pytest.fixture
def case():
    main = {'objective': 'Animal PK, PD index, target and nonhuman PTA.', 'data': {'files': []},
        'scientific_context': {'items': [{'id': 'SC1', 'statement': 'Use original observations.'}]},
        'missing_information': {'items': [{'id': 'MI1', 'field': 'An unresolved source question.'}]},
        'rules': [{'id': 'R1', 'text': 'Preserve observations.', 'conditions': ['No invented joins.'],
                   'exceptions': [], 'scope': {'species': []}, 'usage': {'timing': 'before modeling'},
                   'field_evidence': {'text': 'large upstream audit'}},
                  {'id': 'R2', 'text': 'Define the human population.', 'scope': {'species': ['human']}}]}
    view = {'profiles': [{'item_id': 'A', 'species': 'Mouse', 'matrix': 'plasma', 'record_level': 'group mean',
        'role': 'PK_OBSERVATIONS', 'columns': [{'header': 'Time', 'unit': 'h', 'meaning': 'TIME'}],
        'stated_values': [{'value': '1234567'}], 'reason': 'OLD_BLOCK', 'status': 'MISSING'}],
        'source_units': {'A': json.dumps({'title': 'Study S1', 'source_notes': 'Single dose; group means.'}),
                         'A:note': 'Single dose; group means.', 'A:A5': '1234567'},
        'legacy_findings': ['OLD_BLOCK']}
    payload, schema, sources, knowledge = p.build_payload(main, view)
    raw = {'request_sha256': 'test', 'requirements': []}
    for uses, methods in [(['MODEL_BASED'], ['MP004']), (['PD_INDEX', 'PD_TARGET'], ['MP009', 'MP012']), (['PTA'], ['MP010'])]:
        raw['requirements'].append({'description': 'Observed inputs and source identity.', 'method_uses': uses,
            'input_fields': ['time', 'concentration'], 'conditions': ['When this method is used.'],
            'required_by': 'BEFORE_MODELING', 'origin': 'METHOD_CANDIDATE',
            'project_source_ids': ['main:/objective'], 'method_profile_ids': methods})
    return payload, schema, sources, knowledge, raw, main, view


def derive(case):
    return p.materialize(case[4], case[0], case[2], case[3])


def test_no_graph_shared_method_knowledge_and_host_ids(case):
    value = derive(case)
    assert [n['id'] for n in value['requirements']] == ['RQ001', 'RQ002', 'RQ003']
    assert value['requirements'][1]['method_profile_ids'] == ['MP009', 'MP012']
    assert not {'methods', 'tasks', 'data_links'} & value.keys()
    assert not {'analysis', 'task_id', 'group_id', 'dataset_ids'} & value['requirements'][0].keys()
    assert all(value[k] is False for k in ('scientific_approval', 'can_enter_qc', 'fit_ready'))
    assert 'NCA' not in set(u for n in value['requirements'] for u in n['method_uses'])


def test_overview_preserves_fields_notes_and_all_items_not_measurements_or_old_verdicts(case):
    payload, _, _, _, _, main, _ = case
    text = json.dumps(payload)
    assert '1234567' not in text and 'OLD_BLOCK' not in text and 'source_units' not in payload
    assert payload['data_overviews'][0]['columns'][0]['unit'] == 'h'
    assert payload['overview_notes'][0]['text'] == 'Single dose; group means.'
    assert payload['project_context']['missing_information'] == main['missing_information']
    for k in p.RULE_FIELDS:
        if k in main['rules'][0]: assert payload['project_rules'][0][k] == main['rules'][0][k]
    assert 'field_evidence' not in payload['project_rules'][0]
    assert derive(case)['overview_manifest']['item_ids'] == ['A']


def test_no_per_dataset_method_generation_gate(case):
    main, view = case[5:]
    extra = copy.deepcopy(view['profiles'][0]); extra['item_id'] = 'Kp104'
    view['profiles'].append(extra); view['source_units']['Kp104'] = '{}'
    payload, _, sources, knowledge = p.build_payload(main, view)
    assert p.materialize(case[4], payload, sources, knowledge)['overview_manifest']['item_ids'] == ['A', 'Kp104']


@pytest.mark.parametrize('change', ['unknown_paper', 'bare_dataset', 'candidate_upgrade', 'explicit_objective',
    'human_rule', 'unknown_method', 'no_conditions', 'status', 'graph', 'id', 'human_input', 'omit_pta'])
def test_authority_scope_and_serialization_negative_cases(case, change):
    n = case[4]['requirements'][0]
    if change == 'unknown_paper': n['project_source_ids'] = ['F0003_P0001']
    elif change == 'bare_dataset': n['project_source_ids'] = ['A']
    elif change == 'candidate_upgrade': n.update(origin='PROJECT_EXPLICIT', project_source_ids=['main:/rules/0/text'])
    elif change == 'explicit_objective': n.update(origin='PROJECT_EXPLICIT', method_profile_ids=[])
    elif change == 'human_rule': n['project_source_ids'] = ['main:/rules/1/text']
    elif change == 'unknown_method': n['method_profile_ids'] = ['MP999']
    elif change == 'no_conditions': n['conditions'] = []
    elif change == 'status': n['status'] = 'ADEQUATE'
    elif change == 'graph': case[4]['methods'] = []
    elif change == 'id': n['id'] = 'MODEL_GENERATED_ID'
    elif change == 'human_input': n['description'] = 'Define the human population.'
    else: case[4]['requirements'].pop()
    with pytest.raises(Exception): derive(case)


def test_direct_project_requirement_has_no_method_authority(case):
    case[4]['requirements'][0].update(origin='PROJECT_EXPLICIT', method_profile_ids=[], project_source_ids=['main:/rules/0/text'])
    n = derive(case)['requirements'][0]
    assert n['evidence'] == [{'source': 'main:/rules/0/text', 'quote': 'Preserve observations.'}]


def test_exact_duplicate_notes_and_document_exclusion(case):
    main, view = case[5:]
    item = copy.deepcopy(view['profiles'][0]); item['item_id'] = 'B'
    view['profiles'].extend([item, {'item_id': 'DOC', 'columns': [], 'evidence_source_ids': ['DOC:line1']}])
    view['source_units'].update({'B': view['source_units']['A'], 'B:note': 'Single dose; group means.',
        'DOC': '{"kind":"document"}', 'DOC:line1': 'Design note.', 'DOC:line2': '777 888 999'})
    payload, *_ = p.build_payload(main, view)
    notes = [n for n in payload['overview_notes'] if n['text'] == 'Single dose; group means.']
    assert len(notes) == 1 and set(notes[0]['source_ids']) == {'A:note', 'B:note'}
    assert '777 888 999' not in json.dumps(payload)


def checkpoint(case, tmp_path, monkeypatch):
    source = tmp_path/'source'; main, view = case[5:]
    main_path = p.write_json(source/'main.json', main)
    manifest = {'version': p.sf.VERSION, 'bindings': {'main': p.file_ref(main_path)}}
    p.write_json(source/'manifest.json', manifest); p.write_json(source/'source_view.json', view)
    p.write_json(source/'inventory.json', {'items': []})
    p.write_json(source/'permissions.json', {'access': [{'item_id': 'A', 'disposition': 'REVIEW_DATA'}]})
    monkeypatch.setattr(p.sf, 'verify_final_main', lambda _: {'main': main, 'main_ref': p.file_ref(main_path)})
    baseline = p.write_json(tmp_path/'input_bindings.json', {'main': p.file_ref(main_path), 'source_view': p.file_ref(source/'source_view.json')})
    return source, baseline


def test_mock_run_replays_and_rejects_derived_tampering(case, tmp_path, monkeypatch):
    source, baseline = checkpoint(case, tmp_path, monkeypatch)
    def generate(request, **_):
        result = copy.deepcopy(case[4]); result['request_sha256'] = request['request_sha256']; return result
    out = tmp_path/'new'
    result = p.run(source, out, input_bindings=baseline, generator=generate)
    assert p.verify_plan(out/'plan.json') == result
    result['requirements'][0]['description'] = 'Changed'
    p.write_json(out/'plan.json', result)
    with pytest.raises(Exception, match='raw derivation'): p.verify_plan(out/'plan.json')


def test_only_exact_authorized_historical_checker_can_resolve(case, tmp_path, monkeypatch):
    source, _ = checkpoint(case, tmp_path, monkeypatch)
    manifest = p.read_json(source/'manifest.json')
    manifest['bindings']['original_data_checker'] = {'path': str(p.Path(p.d.__file__).resolve()), 'sha256': p.HISTORICAL_CHECKER_SHA}
    p.write_json(source/'manifest.json', manifest)
    _, _, resolution = p.verify_source_checkpoint(source)
    assert resolution['snapshot_ref']['sha256'] == p.HISTORICAL_CHECKER_SHA
    assert resolution['current_checker_ref'] == p.file_ref(p.d.__file__)
    manifest['bindings']['original_data_checker']['sha256'] = '0'*64
    p.write_json(source/'manifest.json', manifest)
    with pytest.raises(Exception, match='authorized snapshot'): p.verify_source_checkpoint(source)


def test_other_changed_source_binding_is_not_bypassed(case, tmp_path, monkeypatch):
    source, _ = checkpoint(case, tmp_path, monkeypatch)
    manifest = p.read_json(source/'manifest.json')
    manifest['bindings']['other'] = {'path': str(source/'inventory.json'), 'sha256': '0'*64}
    p.write_json(source/'manifest.json', manifest)
    with pytest.raises(Exception, match='changed'): p.verify_source_checkpoint(source)
