import copy
import json
import pytest

from research_pipeline import context_builder as cb, context_handoff as handoff


def result(tmp_path, value):
    path = tmp_path / 'formal.json'
    path.write_text(json.dumps(value), encoding='utf-8')
    return {'upstream': cb.file_ref(path)}


def assigned(*ids, output='plot'):
    return [{'output_id': output, 'artifact_id': 'upstream', 'record_ids': list(ids)}]


def test_conditions_unknown_pairing_and_relation_endpoints_survive(tmp_path):
    value = {'conditions': ['Only within the stated regimen'], 'unknowns': ['individual IDs'],
             'records': [{'id': 'pk', 'dose': 'single', 'unit': 'mg/L', 'summary': 'group mean'},
                         {'id': 'pd', 'dose': 'multiple', 'unit': 'log10 CFU'},
                         {'id': 'unrelated', 'content': 'unneeded'}],
             'context_links': [{'from': 'pk', 'to': 'pd', 'kind': 'paired_subjects',
                                'state': 'UNKNOWN', 'evidence_pointers': []}]}
    refs = result(tmp_path, value)
    packed = handoff.build_view(refs, assigned('pk'))
    unit = next(iter(packed['view']['units'].values()))
    assert set(unit['records']) == {'pk', 'pd'}
    assert unit['shared']['conditions'] == value['conditions']
    assert unit['shared']['unknowns'] == value['unknowns']
    assert unit['relations'][0]['state'] == 'UNKNOWN'
    handoff.verify_view(packed, refs, assigned('pk'))
    unit['shared'].pop('conditions')
    with pytest.raises(ValueError, match='omitted'):
        handoff.verify_view(packed, refs, assigned('pk'))


def test_cycles_close_and_negative_relationships_are_not_discarded(tmp_path):
    refs = result(tmp_path, {'records': [{'id': 'a', 'context_requires': ['b']},
                                       {'id': 'b', 'context_requires': ['a']}],
        'context_links': [{'from': 'a', 'to': 'b', 'kind': 'same_animal', 'state': 'ABSENT', 'evidence_pointers': []}]})
    packed = handoff.build_view(refs, assigned('a'))
    unit = next(iter(packed['view']['units'].values()))
    assert len(unit['records']) == 2
    assert unit['relations'][0]['state'] == 'ABSENT'


@pytest.mark.parametrize('change', ['dangling', 'empty_support'])
def test_invalid_relationships_fail_instead_of_becoming_facts(tmp_path, change):
    value = {'records': [{'id': 'a'}, {'id': 'b'}], 'context_links': [
        {'from': 'a', 'to': 'z' if change == 'dangling' else 'b', 'kind': 'paired',
         'state': 'CONFIRMED', 'evidence_pointers': []}]}
    with pytest.raises(ValueError):
        handoff.build_view(result(tmp_path, value), assigned('a'))


def test_confirmed_link_materializes_its_evidence_without_inventing_validation(tmp_path):
    value = {'notes': ['The source reports pairing.'], 'records': [{'id': 'a'}, {'id': 'b'}],
             'context_links': [{'from': 'a', 'to': 'b', 'kind': 'paired', 'state': 'CONFIRMED',
                                'evidence_pointers': ['/notes/0']}]}
    packed = handoff.build_view(result(tmp_path, value), assigned('a'))
    unit = next(iter(packed['view']['units'].values()))
    assert unit['relation_evidence']['/notes/0'] == value['notes'][0]
    assert 'not proof' in packed['audit']['guarantee']


def test_unknown_layout_retains_whole_local_object(tmp_path):
    value = {'narrative': 'No effect estimate without comparable baseline.',
             'nested': {'conditions': ['Do not drop this exception']}}
    packed = handoff.build_view(result(tmp_path, value), assigned('$root'))
    unit = next(iter(packed['view']['units'].values()))
    assert unit['records']['$root']['value'] == value


def test_budget_limits_only_affected_output_and_does_not_mean_absent(tmp_path):
    refs = result(tmp_path, {'records': [{'id': 'small', 'value': 1}, {'id': 'big', 'text': 'x' * 4000}]})
    assignments = assigned('small', output='a') + assigned('big', output='b')
    packed = handoff.build_view(refs, assignments, character_budget=1000)
    assert [o['status'] for o in packed['view']['outputs']] == ['INPUT_LOADED', 'INPUT_NOT_LOADED']
    assert len(packed['view']['units']) == 1


def test_changed_formal_source_is_not_silently_rebound(tmp_path):
    refs = result(tmp_path, {'records': [{'id': 'a'}]})
    (tmp_path / 'formal.json').write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='Changed input'):
        handoff.build_view(refs, assigned('a'))
