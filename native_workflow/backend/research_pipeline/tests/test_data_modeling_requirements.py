"""Regression coverage for objective-led DR planning, with no provider calls."""
import copy
import json

import pytest

from research_pipeline import data_modeling_requirements as m
from research_pipeline import data_source_first_organize as legacy
from research_pipeline import method_profiles as mp


@pytest.fixture
def case(monkeypatch):
    main = {
        'objective': 'Assess animal PK by NCA and model-based methods and compare PD indices.',
        'data': {'files': []},
        'rules': [{'id': 'R1', 'kind': 'REQUIREMENT', 'text': 'Preserve observation units.',
                   'conditions': [], 'exceptions': [], 'scope': {'stages': ['adequacy']},
                   'requirement': {'fields': ['units']}, 'usage': 'planning'}],
        'scientific_context': {'items': [{'statement': 'Rabbit plasma concentration-time data.'},
                                        {'statement': 'Human prediction is a later objective.'}]},
        'missing_information': {'items': []},
    }
    monkeypatch.setattr(legacy, 'embedded_projection', lambda value, stages: [
        {**value['rules'][0], 'stages': ['adequacy'], 'context_path': '/rules/0'}])
    view = {'profiles': [], 'source_units': {}, 'legacy_findings': []}
    for item, species, role in [('M', 'Mouse', 'PK_OBSERVATIONS'),
                                ('R', 'Rabbit', 'PK_OBSERVATIONS'),
                                ('P', 'Mouse', 'PD_OBSERVATIONS')]:
        view['profiles'].append({'item_id': item, 'species': species, 'role': role,
                                 'columns': [], 'stated_values': [],
                                 'evidence_source_ids': [item + ':1']})
        view['source_units'][item] = json.dumps({'title': species + ' source', 'linked_notes': 'Original note'})
        view['source_units'][item + ':1'] = species + ' concentration or response; original units and times.'
    payload, schema, sources, knowledge = m.build_payload(main, view, mp.planning_context())
    raw = {'request_sha256': 'test', 'tasks': [
        {'id': task, 'objective': main['objective'], 'destination': dest,
         'evidence_source_ids': ['main:/objective']}
        for task, dest in [('ANIMAL_PK', 'pk'), ('PD_INDEX', 'index')]],
        'requirements': [], 'method_feasibility': [], 'data_links': [],
        'objective_coverage': [], 'findings': []}
    approaches = []
    for i, (item, analysis, method) in enumerate([
        ('M', 'NCA', 'MP001'), ('R', 'NCA', 'MP001'),
        ('M', 'MODEL_BASED', 'MP004'), ('R', 'MODEL_BASED', 'MP004'),
        ('P', 'PD_INDEX', 'MP009')]):
        task = 'PD_INDEX' if analysis == 'PD_INDEX' else 'ANIMAL_PK'
        selectors = ['main:/objective', 'method:' + method, item + ':1']
        raw['requirements'].append({
            'id': 'Q' + str(i), 'task_id': task, 'description': 'Original observations with units and timing.',
            'kind': 'DATA', 'required_by': 'BEFORE_INDEX_ANALYSIS' if analysis == 'PD_INDEX' else 'BEFORE_MODELING',
            'fields': ['time', 'concentration' if analysis != 'PD_INDEX' else 'response'],
            'rule_ids': ['R1'], 'origin': 'METHOD_CANDIDATE', 'method_profile_ids': [method],
            'conditions': ['For this candidate analysis.'], 'dataset_ids': [item],
            'analysis': analysis, 'evidence_source_ids': selectors})
        approach = {'id': 'A' + str(i), 'name': analysis + ' for ' + item, 'analysis': analysis,
                    'dataset_ids': [item], 'requirement_ids': ['Q' + str(i)],
                    'method_profile_ids': [method], 'status': 'PARTIAL',
                    'available_inputs': ['Original observations'], 'missing_inputs': ['Dose-event confirmation'],
                    'applicability_conditions': ['Use the observed measurement level.'],
                    'reason': 'A candidate based on the available observations.',
                    'evidence_source_ids': selectors, 'next_step': 'Confirm dose events before analysis.'}
        approaches.append(approach)
    for task in m.TASKS:
        raw['method_feasibility'].append({'task_id': task, 'approaches': [
            a for a in approaches if (a['analysis'] == 'PD_INDEX') == (task == 'PD_INDEX')]})
    for item in ('M', 'R', 'P'):
        raw['data_links'].append({'item_id': item, 'requirement_ids': [
            n['id'] for n in raw['requirements'] if item in n['dataset_ids']],
            'reason': 'Supports the linked analyses.', 'evidence_source_ids': [item + ':1']})
    for source in payload['objective_source_ids']:
        deferred = 'Human' in sources[source]
        raw['objective_coverage'].append({
            'source': source, 'scope': 'DEFERRED' if deferred else 'CURRENT',
            'requirement_ids': [] if deferred else (['Q1', 'Q3'] if 'Rabbit' in sources[source] else ['Q0']),
            'reason': 'Later translation.' if deferred else 'Current animal PK scope.',
            'evidence_source_ids': [source]})
    return payload, schema, sources, knowledge, raw, view


def materialize(case):
    payload, _, sources, knowledge, raw, _ = case
    return m.materialize(raw, payload, sources, knowledge)


def test_first_response_has_method_plan_and_literal_original_evidence(case):
    payload, schema, sources, _, raw, view = case
    assert 'method_feasibility' in schema['required']
    assert 'analysis_coverage' not in schema['properties']['data_links']['items']['properties']
    result = materialize(case)
    assert len(result['tasks']) == 2
    assert {'MP004', 'MP009'} <= {x for n in result['requirements'] for x in n['method_profile_ids']}
    assert result['requirements'][0]['evidence'][-1] == {'source': 'M:1', 'quote': view['source_units']['M:1']}
    assert payload['source_units']['R:1'] == view['source_units']['R:1']
    assert 'evidence_source_ids' in raw['requirements'][0]  # original model response not mutated


def test_later_human_objective_is_retained_without_current_blocker(case):
    result = materialize(case)
    future = next(x for x in result['objective_coverage'] if x['scope'] == 'DEFERRED')
    assert future['requirement_ids'] == []
    assert all('MP005' not in n['method_profile_ids'] for n in result['requirements'])


@pytest.mark.parametrize('fault', ['missing_model_method', 'unknown_source', 'holdout',
    'rabbit_to_mouse', 'mixed_species', 'unrelated_need', 'lost_dataset', 'method_in_wrong_branch',
    'fitted_status', 'lost_model_branch'])
def test_known_routing_and_evidence_regressions_are_rejected(case, fault):
    raw = case[4]
    if fault == 'missing_model_method':
        raw['requirements'][2]['method_profile_ids'] = []
    elif fault == 'unknown_source':
        raw['requirements'][0]['evidence_source_ids'].append('invented:1')
    elif fault == 'holdout':
        raw['requirements'][0]['dataset_ids'] = ['HORSE_HELD_OUT']
    elif fault == 'rabbit_to_mouse':
        raw['objective_coverage'][1]['requirement_ids'] = ['Q0']
    elif fault == 'mixed_species':
        a = raw['method_feasibility'][0]['approaches'][0]
        a['dataset_ids'].append('R'); a['evidence_source_ids'].append('R:1')
    elif fault == 'unrelated_need':
        raw['method_feasibility'][0]['approaches'][0]['requirement_ids'] = ['Q1']
    elif fault == 'lost_dataset':
        raw['data_links'].pop()
    elif fault == 'method_in_wrong_branch':
        raw['requirements'][2]['method_profile_ids'] = ['MP009']
    elif fault == 'fitted_status':
        raw['method_feasibility'][0]['approaches'][0]['status'] = 'VALIDATED_MODEL'
    elif fault == 'lost_model_branch':
        raw['method_feasibility'][0]['approaches'] = raw['method_feasibility'][0]['approaches'][:2]
    with pytest.raises(Exception):
        materialize(case)


def test_selected_library_is_frozen_without_mutating_full_library():
    full = mp.planning_context(); original = copy.deepcopy(full)
    selected = m.selected_knowledge(full)
    assert full == original
    assert {p['id'] for p in selected['library']['profiles']} == {'MP001', 'MP002', 'MP003', 'MP004', 'MP007', 'MP009'}
    assert mp.check_context(selected)
