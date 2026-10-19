"""Offline boundary checks for overview-only DR; no model is invoked."""
import copy
import json
import pytest
from research_pipeline import data_requirement_planning as p


@pytest.fixture
def case():
    main = {'objective': 'Animal PK, PD index, targets and nonhuman PTA.', 'data': {'files': []},
            'scientific_context': {'items': []}, 'missing_information': {'items': []},
            'rules': [{'id': 'R1', 'text': 'Preserve original observations.', 'conditions': ['No invented joins.'],
                       'exceptions': [], 'provenance': {'original': 'preserved'}}]}
    view = {'profiles': [{'item_id': 'A', 'species': 'Mouse', 'matrix': 'plasma', 'record_level': 'group mean',
             'role': 'PK_OBSERVATIONS', 'columns': [{'header': 'Time', 'unit': 'h', 'meaning': 'TIME'}],
             'stated_values': [{'value': '1234567'}], 'reason': 'OLD_BLOCK', 'status': 'MISSING'}],
            'source_units': {'A': json.dumps({'title': 'Study S1', 'source_notes': 'Single dose; group means.'}),
                             'A:note': 'Single dose; group means.', 'A:A5': '1234567'},
            'legacy_findings': ['OLD_BLOCK']}
    payload, schema, sources, knowledge = p.build_payload(main, view)
    raw = {'request_sha256': 'test', 'requirements': [], 'methods': [], 'pk_exclusions': []}
    for family, profile in [('MODEL_BASED', 'MP004'), ('NCA', 'MP001')]:
        raw['requirements'].append({'id': family+'Q', 'task_id': 'ANIMAL_PK', 'description': 'Concentration and time.',
            'kind': 'DATA', 'required_by': 'BEFORE_MODELING', 'fields': ['concentration', 'time'],
            'rule_ids': ['R1'], 'origin': 'METHOD_CANDIDATE', 'method_profile_ids': [profile],
            'conditions': ['When this route is used.'], 'analysis': family, 'necessity': 'REQUIRED',
            'evidence_source_ids': ['main:/objective', 'method:'+profile]})
        raw['methods'].append({'id': family, 'group_id': 'G1', 'family': family,
            'scope': {'study': 'S1', 'species': 'Mouse', 'matrix': 'plasma', 'record_level': 'group mean'},
            'dataset_ids': ['A'], 'supporting_item_ids': [], 'requirement_ids': [family+'Q']})
    return payload, schema, sources, knowledge, raw, main, view


def derive(case):
    payload, _, sources, knowledge, raw, _, _ = case
    return p.materialize(raw, payload, sources, knowledge)


def test_overview_has_no_numeric_body_or_historical_conclusions(case):
    payload, _, sources, _, _, main, _ = case
    text = json.dumps(payload)
    assert '1234567' not in text and 'OLD_BLOCK' not in text
    assert 'source_units' not in payload and 'A:A5' not in sources
    assert payload['project_rules'] == main['rules']
    assert payload['overview_notes'][0]['text'] == 'Single dose; group means.'


def test_plan_is_not_coverage_and_routes_are_alternatives(case):
    plan = derive(case)
    assert plan['policy']['animal_pk']['satisfaction'] == 'ANY_ONE'
    assert plan['policy']['animal_pk']['preferred_family'] == 'MODEL_BASED'
    assert all(plan[k] is False for k in ('scientific_approval', 'can_enter_qc', 'fit_ready'))
    assert 'status' not in plan['methods'][0]


def test_nca_only_group_cannot_preempt_model_based_coverage(case):
    raw = case[4]
    raw['requirements'] = [n for n in raw['requirements'] if n['analysis'] == 'NCA']
    raw['methods'] = [m for m in raw['methods'] if m['family'] == 'NCA']
    with pytest.raises(Exception, match='retain MODEL_BASED'): derive(case)


def test_model_based_only_is_allowed_without_mandatory_nca(case):
    raw = case[4]
    raw['requirements'] = [n for n in raw['requirements'] if n['analysis'] == 'MODEL_BASED']
    raw['methods'] = [m for m in raw['methods'] if m['family'] == 'MODEL_BASED']
    assert len(derive(case)['methods']) == 1


@pytest.mark.parametrize('family,profile', [('PD_TARGET', 'MP012'), ('PTA', 'MP010')])
def test_new_method_loader_supports_target_and_pta(case, family, profile):
    case[0]['data_profiles'][0]['role'] = 'PD_OBSERVATIONS'
    raw = case[4]
    raw['requirements'] = [raw['requirements'][0]]; raw['methods'] = [raw['methods'][0]]
    n = raw['requirements'][0]; n.update(task_id=family, analysis=family, method_profile_ids=[profile])
    n['evidence_source_ids'] = ['main:/objective', 'method:'+profile]
    raw['methods'][0]['family'] = family
    assert derive(case)['requirements'][0]['method_profile_ids'] == [profile]


@pytest.mark.parametrize('change', ['unknown_source', 'wrong_method', 'unknown_dataset', 'same_group_other_scope', 'status', 'terminal_required'])
def test_invalid_plans_rejected(case, change):
    raw = case[4]
    if change == 'unknown_source': raw['requirements'][0]['evidence_source_ids'] = ['UNSEEN']
    elif change == 'wrong_method': raw['requirements'][0]['method_profile_ids'] = ['MP009']
    elif change == 'unknown_dataset': raw['methods'][0]['dataset_ids'] = ['HOLDOUT']
    elif change == 'same_group_other_scope': raw['methods'][1]['scope']['study'] = 'S2'
    elif change == 'status': raw['methods'][0]['status'] = 'PASS'
    else:
        raw['requirements'][1]['method_profile_ids'] = ['MP002']
        raw['requirements'][1]['evidence_source_ids'] = ['main:/objective', 'method:MP002']
    with pytest.raises(Exception): derive(case)


def test_conditional_does_not_assert_missing_or_adequate(case):
    case[4]['requirements'][1]['necessity'] = 'CONDITIONAL'
    assert derive(case)['requirements'][1]['necessity'] == 'CONDITIONAL'


def test_scope_species_cannot_disguise_actual_rabbit_as_mouse(case):
    case[0]['data_profiles'][0]['species'] = 'Rabbit'
    with pytest.raises(Exception, match='species'): derive(case)


def test_duplicate_notes_are_lossless_and_document_body_is_not_automatically_notes(case):
    main, view = case[5:]
    second = copy.deepcopy(view['profiles'][0]); second['item_id'] = 'B'
    view['profiles'].append(second)
    view['source_units'].update({'B': view['source_units']['A'], 'B:note': 'Single dose; group means.'})
    view['profiles'].append({'item_id': 'DOC', 'columns': [], 'evidence_source_ids': ['DOC:line1']})
    view['source_units'].update({'DOC': '{"kind":"document"}', 'DOC:line1': 'Design note.', 'DOC:line2': '9999 8888 7777'})
    payload, _, sources, _ = p.build_payload(main, view)
    notes = [n for n in payload['overview_notes'] if n['text'] == 'Single dose; group means.']
    assert len(notes) == 1 and set(notes[0]['sources']) == {'A:note', 'B:note'}
    assert 'DOC:line2' not in sources and '9999 8888 7777' not in json.dumps(payload)
    assert sources['A:note'] == sources['B:note']


def test_mock_run_publishes_replayable_plan_and_rejects_tampering(case, tmp_path, monkeypatch):
    source = tmp_path/'source'; out = tmp_path/'new'
    main, view = case[5:]
    main_path = p.write_json(source/'main.json', main)
    manifest = {'bindings': {'main': p.file_ref(main_path)}}
    p.write_json(source/'manifest.json', manifest)
    p.write_json(source/'source_view.json', view)
    p.write_json(source/'inventory.json', {'items': []})
    p.write_json(source/'permissions.json', {'access': [{'item_id': 'A', 'disposition': 'REVIEW_DATA'}]})
    monkeypatch.setattr(p.sf, 'verify_run', lambda _: (manifest, {'main': main}))
    def generate(request, **_):
        result = copy.deepcopy(case[4]); result['request_sha256'] = request['request_sha256']; return result
    result = p.run(source, out, generator=generate)
    assert p.verify_plan(out/'plan.json') == result
    result['requirements'][0]['description'] = 'HOST INVENTED OBLIGATION'
    p.write_json(out/'plan.json', result)
    with pytest.raises(Exception, match='replay'): p.verify_plan(out/'plan.json')


def test_schema_rejects_upstream_paper_id_not_catalog_selector(case):
    raw = case[4]; raw['requirements'][0]['evidence_source_ids'] = ['F0003_P0001']
    with pytest.raises(Exception): p.d.validate_schema(raw, p.response_schema(case[0]))


def test_shared_base_requirement_reuses_nca_and_model_profile_authority(case):
    n = copy.deepcopy(case[4]['requirements'][0])
    n.update(id='COMMON', analysis='SHARED', method_profile_ids=['MP001', 'MP004'],
             evidence_source_ids=['main:/objective', 'method:MP001', 'method:MP004'])
    case[4]['requirements'].append(n)
    for m in case[4]['methods']: m['requirement_ids'].append('COMMON')
    assert derive(case)['requirements'][-1]['analysis'] == 'SHARED'


def test_omitted_primary_pk_dataset_requires_explicit_source_exclusion(case):
    item = copy.deepcopy(case[0]['data_profiles'][0]); item['item_id'] = 'B'
    case[0]['data_profiles'].append(item)
    with pytest.raises(Exception, match='Primary PK'): derive(case)


def test_current_human_population_requirement_rejected(case):
    case[4]['requirements'][0]['description'] = 'Define the human population and dose scenarios.'
    with pytest.raises(Exception, match='human'): derive(case)


def test_scope_exclusion_requires_same_item_original_note(case):
    item = copy.deepcopy(case[0]['data_profiles'][0]); item['item_id'] = 'B'; item['notes'] = ['B:note']
    case[0]['data_profiles'].append(item)
    case[0]['allowed_evidence_source_ids'].append('B:note')
    case[2]['B:note'] = 'External comparison dataset; support context only.'
    case[4]['pk_exclusions'] = [{'item_id': 'B', 'reason': 'External comparison support only.',
                                'evidence_source_ids': ['B:note']}]
    assert derive(case)['pk_exclusions'][0]['evidence'][0]['quote'] == case[2]['B:note']
    case[4]['pk_exclusions'][0]['evidence_source_ids'] = ['main:/objective']
    with pytest.raises(Exception, match='that item'): derive(case)


def test_shared_pd_definitions_can_link_pd_index_and_target(case):
    raw = case[4]
    for family, method in [('PD_INDEX', 'MP009'), ('PD_TARGET', 'MP012')]:
        n = copy.deepcopy(raw['requirements'][0])
        n.update(id=family+'Q', task_id=family, analysis=family, method_profile_ids=[method],
                 evidence_source_ids=['main:/objective', 'method:'+method])
        raw['requirements'].append(n)
        m = copy.deepcopy(raw['methods'][0]); m.update(id=family, group_id=family, family=family,
                                                     requirement_ids=[family+'Q', 'DEFS'])
        raw['methods'].append(m)
    n = copy.deepcopy(raw['requirements'][-1])
    n.update(id='DEFS', analysis='SHARED', method_profile_ids=['MP009'],
             evidence_source_ids=['main:/objective', 'method:MP009'])
    raw['requirements'].append(n)
    assert derive(case)['requirements'][-1]['id'] == 'DEFS'


def test_ecoli_cannot_become_primary_kp_index_dataset(case):
    case[0]['data_profiles'][0]['role'] = 'PD_OBSERVATIONS'
    case[0]['data_profiles'][0]['title'] = 'E. coli response panels'
    raw = case[4]
    raw['requirements'] = [raw['requirements'][0]]; raw['methods'] = [raw['methods'][0]]
    raw['requirements'][0].update(task_id='PD_INDEX', analysis='PD_INDEX', method_profile_ids=['MP009'],
                                  evidence_source_ids=['main:/objective', 'method:MP009'])
    raw['methods'][0]['family'] = 'PD_INDEX'
    with pytest.raises(Exception, match='E. coli'): derive(case)


def test_generation_schema_rejects_explicit_project_with_method_citation(case):
    raw = case[4]
    raw['requirements'][0]['origin'] = 'PROJECT_EXPLICIT'
    with pytest.raises(Exception): p.d.validate_schema(raw, p.response_schema(case[0]))


def test_generation_schema_requires_method_candidate_conditions(case):
    raw = case[4]; raw['requirements'][0]['conditions'] = []
    with pytest.raises(Exception): p.d.validate_schema(raw, p.response_schema(case[0]))


def correction_for(raw):
    return {'request_sha256': 'corrected',
            'need_updates': [{k: copy.deepcopy(n[k]) for k in p.CORRECTION_FIELDS} for n in raw['requirements']],
            'retired_requirement_ids': [], 'method_links': [{'id': m['id'], 'requirement_ids': m['requirement_ids']}
                                                           for m in raw['methods']], 'additional_methods': []}


def test_targeted_correction_preserves_scientific_fields_and_scopes(case):
    payload, _, sources, knowledge, original, _, _ = case
    corrected = p.apply_correction(original, correction_for(original), payload, sources, knowledge)
    assert corrected['requirements'] == original['requirements']
    assert corrected['methods'] == original['methods']
    assert corrected['request_sha256'] == 'corrected'


@pytest.mark.parametrize('mutation', ['description', 'fields', 'retire_linked', 'new_scope', 'missing_update'])
def test_targeted_correction_rejects_unscoped_changes(case, mutation):
    payload, _, sources, knowledge, original, _, _ = case
    correction = correction_for(original)
    if mutation in ('description', 'fields'): correction['need_updates'][0][mutation] = 'UNAUTHORIZED'
    elif mutation == 'retire_linked': correction['retired_requirement_ids'] = [original['requirements'][0]['id']]
    elif mutation == 'missing_update': correction['need_updates'].pop()
    else:
        m = copy.deepcopy(original['methods'][1]); m['id'] = 'NEW'; m['scope']['study'] = 'OTHER'
        correction['additional_methods'] = [m]
    with pytest.raises(Exception): p.apply_correction(original, correction, payload, sources, knowledge)


def test_correction_mock_run_and_proof_replay(case, tmp_path, monkeypatch):
    source = tmp_path/'source'; prior = tmp_path/'prior'; out = tmp_path/'correction'
    main, view = case[5:]
    main_path = p.write_json(source/'main.json', main)
    manifest = {'bindings': {'main': p.file_ref(main_path)}}
    p.write_json(source/'manifest.json', manifest); p.write_json(source/'source_view.json', view)
    p.write_json(source/'inventory.json', {'items': []})
    p.write_json(source/'permissions.json', {'access': [{'item_id': 'A', 'disposition': 'REVIEW_DATA'}]})
    monkeypatch.setattr(p.sf, 'verify_run', lambda _: (manifest, {'main': main}))
    request = p.prepare(source, prior)
    original = copy.deepcopy(case[4]); original['request_sha256'] = request['request_sha256']
    directory = prior/'data_agents/audit/DR/prior'
    p.write_json(directory/'request.json', request); p.write_json(directory/'response.json', original)
    def generate(req, **_):
        correction = correction_for(original); correction['request_sha256'] = req['request_sha256']; return correction
    result = p.run_correction(prior, out, generator=generate)
    assert p.verify_plan(out/'plan.json') == result
    assert p.read_json(directory/'response.json') == original
    result['methods'][0]['scope']['study'] = 'EDITED'
    p.write_json(out/'plan.json', result)
    with pytest.raises(Exception, match='replay'): p.verify_plan(out/'plan.json')


def test_correction_cannot_promote_original_method_candidate_to_project(case):
    payload, _, sources, knowledge, original, _, _ = case
    patch = correction_for(original)
    patch['need_updates'][0]['origin'] = 'PROJECT_EXPLICIT'
    patch['need_updates'][0]['evidence_source_ids'] = ['main:/objective']
    with pytest.raises(Exception): p.apply_correction(original, patch, payload, sources, knowledge)


def test_nonhuman_correction_cannot_cite_human_specific_rule(case):
    payload, _, sources, knowledge, original, _, _ = case
    payload['project_rules'].append({'id': 'R051', 'text': 'Human population uncertainty.', 'scope': {'species': ['human']}})
    payload['allowed_evidence_source_ids'].append('main:/rules/1/text')
    sources['main:/rules/1/text'] = 'Human population uncertainty.'
    original['requirements'][0]['rule_ids'].append('R051')
    patch = correction_for(original)
    patch['need_updates'][0]['evidence_source_ids'].append('main:/rules/1/text')
    with pytest.raises(Exception): p.apply_correction(original, patch, payload, sources, knowledge)


def test_human_scope_uses_original_metadata_not_id_or_clinical_keyword(case):
    payload = case[0]
    payload['project_rules'] += [
        {'id': 'R777', 'scope': {'species': ['human'], 'stages': ['clinical']}},
        {'id': 'R049', 'scope': {'species': [], 'stages': ['clinical']}},
        {'id': 'R888', 'scope': {'species': ['human', 'mouse']}}]
    assert p.human_only_rules(payload) == {'R777'}


def test_correction_delivers_all_host_routes_and_orphan_usage_constraints(case):
    payload, _, sources, knowledge, original, _, _ = case
    cp, _ = p.correction_payload(original, payload, sources, knowledge)
    assert cp['analysis_routes']['PD_TARGET'] == ['MP012']
    assert cp['task_routes']['PTA'] == ['PTA']
    assert cp['group_constraints']['same_group_scope'] == 'EXACT_OBJECT_EQUALITY'
    assert set(cp['original_method_candidate_ids_locked']) == {n['id'] for n in original['requirements']}
    assert cp['need_to_method_usages']['NCAQ'] == [{'method_id': 'NCA', 'family': 'NCA'}]
