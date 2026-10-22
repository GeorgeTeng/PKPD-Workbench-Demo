"""Knowledge authority and context-routing tests; no scientific fits or live LLMs."""
import copy

import pytest

from ctxcomp.governance import load_governance
from ctxcomp.io import digest
from research_pipeline import data_agents as d
from research_pipeline import method_profiles as m
from research_pipeline.common import BACKEND, RULES, PipelineError, read_json, write_json
from test_data_agents import case, assess, requirements


def candidate(model, mutate=None):
    def generate(request, **kwargs):
        result = model(request, **kwargs)
        if request['payload'].get('operation') == 'DEFINE_REQUIREMENTS':
            need = result['requirements'][0]
            profile = request['payload']['method_knowledge']['library']['profiles'][0]
            need.update(origin='METHOD_CANDIDATE', method_profile_ids=[profile['id']],
                        conditions=['Only finite-window exposure is requested.'])
            need['evidence'] = copy.deepcopy(need['evidence'])
            need['evidence'].append({'source':'method:' + profile['id'], 'quote':profile['applies_when']})
            if mutate:
                mutate(need, result)
        elif request['payload'].get('operation') == 'ASSIGN_ACCESS' and mutate:
            mutate(None, result)
        return result
    return generate


def test_library_has_one_general_source_and_no_embedded_project_policy():
    context = m.planning_context()
    assert context['general_rules_sha256'] == digest(load_governance())
    assert context['library']['general_rules']['duplicate_rule_text'] is False
    assert context['scientific_release'] is False
    assert 'minimum_qualified_species' not in str(context)
    assert 'flow_96036fc08334499f9a699212b66fb8f0' not in str(context)
    assert context['library']['status'] == 'DRAFT_PENDING_SCIENTIFIC_REVIEW'


@pytest.mark.parametrize('fault', ['duplicate', 'unknown_source', 'promote_authority'])
def test_invalid_library_is_rejected(fault):
    value = copy.deepcopy(m.load_library())
    if fault == 'duplicate':
        value['profiles'][1]['id'] = value['profiles'][0]['id']
    elif fault == 'unknown_source':
        value['profiles'][0]['source_ids'] = ['MISSING']
    else:
        value['use'] = 'AUTOMATIC_SCIENTIFIC_ACCEPTANCE'
    with pytest.raises(ValueError):
        m.validate_library(value)


def test_scoped_packet_contains_only_referenced_profiles_and_sources():
    context = m.planning_context()
    packet = m.scoped_context(context, ['MP002'])
    assert [p['id'] for p in packet['profiles']] == ['MP002']
    assert [s['id'] for s in packet['sources']] == ['S02', 'S03']
    assert packet['library_sha256'] == context['library_sha256']
    assert not m.scoped_context(context, [])['profiles']
    with pytest.raises(PipelineError, match='Unknown method'):
        m.scoped_context(context, ['MP404'])
    context['library']['profiles'][0]['required_inputs'].append('An unreviewed new requirement')
    with pytest.raises(PipelineError, match='frozen digest'):
        m.scoped_context(context, ['MP001'])


def test_fresh_model_packets_use_method_knowledge_without_extra_calls(case):
    _, run, _, _, model, calls = case
    assess(case, candidate(model))
    assert [p['stage'] for p in calls] == ['DR', 'DR-access', 'DC-label', 'DC-review']
    assert len(calls[0]['method_knowledge']['library']['profiles']) == 10 and 'inventory' not in calls[0]
    assert 'method_knowledge' not in calls[1] and calls[1]['requirements'][0]['origin'] == 'METHOD_CANDIDATE'
    assert [p['id'] for p in calls[2]['method_knowledge']['profiles']] == ['MP001']
    assert calls[2]['context_sources'] == {'main:/study/drug':'Compound Z'}
    assert [p['id'] for p in calls[3]['method_knowledge']['profiles']] == ['MP001']
    assert 'METHOD_APPLICABILITY' in calls[3]['expected_check_ids']
    requirements = read_json(run/'adequacy/requirements.json')
    d.check_ref(requirements['method_knowledge_ref'])
    assert requirements['requirements'][0]['origin'] == 'METHOD_CANDIDATE'
    assert read_json(run/'adequacy/adequacy.json')['scientific_release'] is False


@pytest.mark.parametrize('fault', ['borrow_authority','no_method_evidence','no_objective_evidence',
                                  'no_conditions','unknown_profile','grant_access','wrong_context','wrong_assignment'])
def test_method_cannot_replace_project_authority_or_untraceable_inputs(case, fault):
    _, run, _, _, model, _ = case
    def corrupt(need, result):
        if (need is None) != (fault in {'wrong_context', 'wrong_assignment'}):
            return  # Requirement faults go to DR, assignment faults to DR-access.
        if fault == 'borrow_authority': need['origin'] = 'PROJECT_EXPLICIT'
        elif fault == 'no_method_evidence': need['evidence'] = need['evidence'][:1]
        elif fault == 'no_objective_evidence': need['evidence'] = need['evidence'][1:]
        elif fault == 'no_conditions': need['conditions'] = []
        elif fault == 'unknown_profile': need['method_profile_ids'] = ['MP404']
        elif fault == 'grant_access': need['kind'] = 'SOURCE_PERMISSION'
        elif fault == 'wrong_context': result['access'][0]['context_paths'] = ['/missing']
        elif fault == 'wrong_assignment': result['access'][0]['requirement_ids'] = ['N404']
    with pytest.raises(PipelineError):
        assess(case, candidate(model, corrupt))
    assert not (run/'adequacy/qc_context.json').exists()


def test_method_snapshot_change_cannot_inherit_prior_requirements(case):
    _, run, main, inv, model, _ = case
    req = run/'adequacy/requirements.json'
    requirements(run, main, inv, req, candidate(model))
    binding = read_json(req)['method_knowledge_ref']
    changed = read_json(binding['path'])
    changed['library']['version'] = 'changed'
    write_json(binding['path'], changed)
    with pytest.raises(PipelineError):
        d.label(run, main, inv, req, run/'labels.json', generator=model)


def test_missing_candidate_is_retained_without_becoming_a_published_prerequisite(case):
    _, run, _, _, model, _ = case
    generator = candidate(model)
    def missing(request, **kwargs):
        result = generator(request, **kwargs)
        if request['payload']['stage'] == 'DC-review':
            result['matches'][0].update(status='MISSING', source_ids=[],
                reason='Synthetic candidate gap', needed_material='Clarify the optional endpoint window')
            for criterion in result['matches'][0]['criteria']:
                criterion.update(status='MISSING', evidence=[], reason='Synthetic candidate gap',
                                 needed_material='Clarify the optional endpoint window')
        return result
    assess(case, missing)
    report = read_json(run/'adequacy/adequacy.json')
    assert report['can_enter_qc'] is True
    gap = next(f for f in report['findings'] if f['code'] == 'UNMATCHED_REQUIREMENT')
    assert gap['severity'] == 'FOLLOW_UP'
    assert report['requirements'][0]['status'] == 'MISSING'
    assert report['scientific_release'] is False


def test_file_worker_cannot_match_an_unassigned_requirement(case):
    _, run, _, _, model, _ = case
    def unassigned(request, **kwargs):
        result = model(request, **kwargs)
        if request['payload'].get('operation') == 'ASSIGN_ACCESS':
            result['access'][0]['requirement_ids'] = []
        return result
    with pytest.raises(PipelineError, match='unassigned requirement'):
        assess(case, unassigned)


def test_downstream_omits_an_unassigned_branchs_methods(case):
    _, run, main, inv, model, calls = case
    def extra(request, **kwargs):
        result = candidate(model)(request, **kwargs)
        if request['payload'].get('operation') == 'DEFINE_REQUIREMENTS':
            need = copy.deepcopy(result['requirements'][0])
            p = next(x for x in request['payload']['method_knowledge']['library']['profiles'] if x['id'] == 'MP009')
            need.update(id='N002', method_profile_ids=['MP009'], description='PD data for a separate task')
            need['evidence'][-1] = {'source':'method:MP009', 'quote':p['applies_when']}
            result['requirements'].append(need)
        return result
    req=run/'adequacy/requirements.json'
    requirements(run, main, inv, req, extra)
    d.label(run, main, inv, req, run/'labels.json', generator=extra)
    packet = calls[-1]
    assert [n['id'] for n in packet['requirements']] == ['N001']
    assert [p['id'] for p in packet['method_knowledge']['profiles']] == ['MP001']
    assert 'MP009' not in str(packet)


def test_data_profiles_reject_analysis_fields_but_keep_legacy_snapshots_readable():
    library = m.load_library()
    for profile in library['profiles']:
        assert profile['assessment_scope'] == 'DATA_REQUIREMENTS_ONLY'
        assert profile['needed_at'] == 'DATA_REQUIREMENTS_ASSESSMENT'
        assert profile['target_endpoints'] and profile['data_checks']
        assert 'preflight_checks' not in profile and 'post_analysis_checks' not in profile
    polluted = copy.deepcopy(library)
    polluted['profiles'][0]['post_analysis_checks'] = ['Run numerical diagnostics now']
    with pytest.raises(ValueError):
        m.validate_library(polluted)
    archive = BACKEND / 'research_pipeline/docs/review_drafts/history/pkpd_method_profiles.1.0.0-draft.5.json'
    legacy = read_json(archive)
    m.check_context({**m.planning_context(), 'library': legacy, 'library_sha256': digest(legacy)})
    frozen = {**m.planning_context(), 'library': legacy, 'library_sha256': digest(legacy)}
    assert m.scoped_context(frozen, ['MP010'])['profiles'] == legacy['profiles'][9:]
    with pytest.raises(PipelineError, match='Unknown method'):
        m.scoped_context(m.planning_context(), ['MP010'])


def test_relocation_preserves_analysis_requirements_and_original_approval_boundary():
    deferred = read_json(RULES / 'data/deferred/pk_analysis_followup.json')
    archive = BACKEND / deferred['source_library']['path']
    legacy = read_json(archive)
    assert deferred['source_library']['sha256'] == digest(legacy)
    for saved, original in zip(deferred['profiles'], legacy['profiles'][:4], strict=True):
        assert saved['source_profile_sha256'] == digest(original)
        assert saved['analysis_method_requirements'] == original['preflight_checks']
        assert saved['result_evaluation_requirements'] == original['post_analysis_checks']
    assert deferred['profiles'][-1]['review_status'] == 'PENDING_SCIENTIFIC_REVIEW'
    assert deferred['status'] == 'DEFERRED_REFERENCE_NOT_EXECUTION_POLICY'


def test_fresh_data_agent_calls_do_not_receive_relocated_analysis_requirements(case):
    _, run, _, _, model, calls = case
    assess(case, candidate(model))
    for packet in calls:
        assert m.DATA_SCOPE_INSTRUCTIONS in packet['instructions']
        if packet['stage'] == 'DR-access':
            assert 'method_knowledge' not in packet and 'MP010' not in str(packet)
            continue  # Assigns files to requirements; needs no method knowledge.
        knowledge = packet['method_knowledge']
        profiles = knowledge.get('profiles', knowledge.get('library', {}).get('profiles', []))
        revised = [p for p in profiles if p['id'] in {'MP001', 'MP002', 'MP003', 'MP004', 'MP005', 'MP006', 'MP007', 'MP008', 'MP009', 'MP011'}]
        assert revised
        assert all(p['assessment_scope'] == 'DATA_REQUIREMENTS_ONLY' for p in revised)
        assert all('post_analysis_checks' not in p for p in revised)
        assert 'ln(C) = intercept - lambda_z' not in str(packet)
        assert 'result_evaluation_requirements' not in str(packet)
        assert 'MP010' not in str(packet)
    report = read_json(run / 'adequacy/adequacy.json')
    assert report['fit_ready'] is False and report['scientific_release'] is False


def test_index_priority_preserves_stable_ids_and_independent_context_selection():
    context = m.planning_context()
    ids = [p['id'] for p in context['library']['profiles']]
    assert ids == ['MP001', 'MP002', 'MP003', 'MP011', 'MP004', 'MP009', 'MP005', 'MP006', 'MP007', 'MP008']
    index = m.scoped_context(context, ['MP009'])
    assert [p['id'] for p in index['profiles']] == ['MP009']
    assert {s['id'] for s in index['sources']} == {'S07', 'S08'}
    pk = m.scoped_context(context, ['MP004'])
    assert [p['id'] for p in pk['profiles']] == ['MP004']
    assert 'MP009' not in str(pk)
    interface = read_json(BACKEND / 'research_pipeline/docs/interfaces/pkpd_knowledge_layers.json')
    assert [entry.split(' ', 1)[0] for entry in interface['profile_review_order']] == ids


def labelled(model, mutate_label=None, mutate_review=None):
    def generate(request, **kwargs):
        result = model(request, **kwargs)
        payload = request['payload']
        if payload.get('operation') == 'LABEL_FILE_DATA' and mutate_label:
            mutate_label(result['labels'][0])
        if payload.get('stage') == 'DC-review' and mutate_review:
            mutate_review(payload, result)
        return result
    return generate


def plasma_group_bolus(label):
    label.update(route_category='IV_BOLUS', matrix_category='PLASMA_SERUM_BLOOD',
                 record_category='GROUP_SUMMARY', observation_source='SOURCE_VALUES')


def test_dataset_labels_decide_which_selected_profile_conditions_are_reviewed(case):
    _, run, _, _, model, calls = case
    assess(case, labelled(candidate(model), plasma_group_bolus))
    review = calls[-1]
    sent = {r['id'].rsplit(':', 1)[1]: r['applicability'] for r in review['condition_checklist']}
    assert {r['profile_id'] for r in review['condition_checklist']} == {'MP001'}
    assert sent['CI03'] == 'APPLIES' and sent['CI01'] == 'REVIEW_OBJECTIVE'
    assert 'CI02' not in sent and 'CI06' not in sent  # not digitized; not a tissue matrix
    saved = read_json(run / 'adequacy/condition_checklist.json')['conditions']
    assert len(saved) == 14 and {r['decision'] for r in saved if r['applicability'] == 'NOT_APPLICABLE'} == {'NOT_APPLICABLE'}
    report = read_json(run / 'adequacy/adequacy.json')
    gaps = [f for f in report['findings'] if f['code'] == 'METHOD_CONDITION_GAP']
    assert len(gaps) == len(sent) and {f['severity'] for f in gaps} == {'FOLLOW_UP'}
    assert not [f for f in report['why_cannot_pass'] if f['code'] == 'METHOD_CONDITION_GAP']
    assert read_json(run / 'adequacy/adequacy.json')['condition_checklist']['path'].endswith('condition_checklist.json')


def test_undecided_labels_leave_conditions_to_review(case):
    _, _, _, _, model, calls = case
    assess(case, candidate(model))
    sent = {r['id'].rsplit(':', 1)[1]: r for r in calls[-1]['condition_checklist']}
    assert sent['CI02']['applicability'] == 'UNDETERMINED'
    assert sent['CI02']['label_basis'] == {'role': 'PK_OBSERVATIONS', 'observation_source': 'NOT_FOUND'}


@pytest.mark.parametrize('fault', ['exclude_applicable', 'met_without_evidence', 'missing_row', 'foreign_quote'])
def test_condition_decisions_are_verified_by_host(case, fault):
    _, _, _, _, model, _ = case
    def mutate(payload, result):
        checks = result['condition_checks']
        row = next(c for c in checks if c['id'].endswith(':CI03'))
        if fault == 'exclude_applicable':
            row['decision'] = 'NOT_APPLICABLE'
        elif fault == 'met_without_evidence':
            row['decision'] = 'MET'
        elif fault == 'missing_row':
            checks.remove(row)
        else:
            row.update(decision='MET', evidence=[{'source': 'main:/objective', 'quote': 'not in the objective'}])
    with pytest.raises(PipelineError) as error:
        assess(case, labelled(candidate(model), plasma_group_bolus, mutate))
    assert error.value.code == ('DATA_AGENT_CONTRACT_INVALID' if fault == 'missing_row' else 'DATA_CONDITION_INVALID')


def test_data_without_a_requirement_is_routed_to_review_not_added(case):
    _, run, _, _, model, calls = case
    def mic_only(label):
        label.update(role='MIC', requirement_ids=[])
    assess(case, labelled(model, mic_only))
    assert calls[-1]['condition_checklist'] == []
    report = read_json(run / 'adequacy/adequacy.json')
    routed = [f for f in report['findings'] if f['code'] == 'DATA_FITS_UNREQUESTED_METHOD']
    assert len(routed) == 1 and 'MP009' in routed[0]['reason'] and routed[0]['severity'] == 'FOLLOW_UP'
    assert [n['method_profile_ids'] for n in read_json(run / 'adequacy/requirements.json')['requirements']] == [[]]


def test_condition_triggers_cover_every_condition_and_old_snapshots_stay_readable():
    library = m.load_library()
    for p in library['profiles']:
        assert len(p['condition_triggers']['conditional_inputs']) == len(p['conditional_inputs'])
        assert len(p['condition_triggers']['data_checks']) == len(p['data_checks'])
    broken = copy.deepcopy(library)
    broken['profiles'][0]['condition_triggers']['data_checks'].pop()
    with pytest.raises(PipelineError, match='exactly one trigger'):
        m.validate_library(broken)
    broken = copy.deepcopy(library)
    broken['profiles'][0]['condition_triggers']['data_checks'][0]['labels'] = {'route_category': ['NOT_FOUND']}
    with pytest.raises(PipelineError, match='Invalid trigger'):
        m.validate_library(broken)
    old = copy.deepcopy(library)
    for p in old['profiles']:
        del p['condition_triggers'], p['data_roles']
    m.validate_library(old)
    context = {**m.planning_context(), 'library': old, 'library_sha256': digest(old)}
    assert m.condition_checklist(context, [{'id': 'N1', 'method_profile_ids': ['MP001']}],
                                 [{'item_id': 'I1', 'role': 'PK_OBSERVATIONS', 'requirement_ids': ['N1']}]) == []
