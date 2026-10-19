import copy
import json

import pytest

from research_pipeline import context_builder as cb, context_handoff_selection as selection
from research_pipeline import context_library


def build(tmp_path, value, ids, **kwargs):
    path = tmp_path / 'formal.json'
    path.write_text(json.dumps(value), encoding='utf-8')
    refs = {'formal': cb.file_ref(path)}
    assignments = [{'output_id': rid, 'artifact_id': 'formal', 'record_ids': [rid]} for rid in ids]
    return selection.build_view(refs, assignments, **kwargs), refs, assignments


def test_only_declared_closure_preserves_conditions_and_time_axes(tmp_path):
    value = {'conditions': ['Source-specific dose basis only'], 'records': [
        {'id': 'curve', 'level': 'group mean', 'context_requires': ['dose']},
        {'id': 'dose', 'basis': 'as reported', 'context_requires': ['time']},
        {'id': 'time', 'nominal_h': 1, 'actual_h': 1.2},
        {'id': 'other', 'basis': 'different source'}]}
    result, refs, assignments = build(tmp_path, value, ['curve'])
    unit = next(iter(result['view']['units'].values()))
    assert set(unit['records']) == {'curve', 'dose', 'time'}
    assert unit['records']['time']['value'] == value['records'][2]
    assert unit['shared']['conditions'] == value['conditions']
    audit = result['audit']['selections'][0]
    assert audit['relation_scope'] == 'NO_RELATIONS_DECLARED'
    assert audit['semantic_completeness'] == 'NOT_ASSESSED'
    assert result['audit']['model_calls'] == 0
    selection.verify_view(result, refs, assignments)
    altered = copy.deepcopy(result)
    next(iter(altered['view']['units'].values()))['records'].pop('time')
    with pytest.raises(ValueError, match='omitted'):
        selection.verify_view(altered, refs, assignments)


@pytest.mark.parametrize('mode', ['missing_dependency', 'dangling_link', 'unknown_relation', 'absent_declaration'])
def test_local_relation_gap_does_not_block_other_output(tmp_path, mode):
    first = {'id': 'a'}
    links = []
    if mode == 'missing_dependency': first['context_requires'] = ['missing']
    if mode == 'dangling_link':
        links = [{'from': 'a', 'to': 'missing', 'kind': 'pair', 'state': 'UNKNOWN', 'evidence_pointers': []}]
    if mode in {'unknown_relation', 'absent_declaration'}:
        first['context_required_relations'] = ['pair']
    if mode == 'unknown_relation':
        links = [{'from': 'a', 'to': 'related', 'kind': 'pair', 'state': 'UNKNOWN', 'evidence_pointers': []}]
    result, _, _ = build(tmp_path, {'records': [first, {'id': 'related'}, {'id': 'independent'}],
        'context_links': links}, ['a', 'independent'])
    assert [o['status'] for o in result['view']['outputs']] == ['INPUT_RELATION_GAP', 'INPUT_LOADED']
    assert result['view']['outputs'][0]['missing_context']


def test_budget_names_omitted_records_without_truncating(tmp_path):
    result, _, _ = build(tmp_path, {'records': [{'id': 'large', 'context_requires': ['condition'], 'text': 'x'*3000},
        {'id': 'condition', 'text': 'must retain'}, {'id': 'small'}]}, ['large', 'small'], character_budget=1000)
    assert result['view']['outputs'][0]['omitted_record_ids'] == ['condition', 'large']
    assert result['view']['outputs'][1]['status'] == 'INPUT_LOADED'


def test_empty_relations_do_not_create_scientific_completeness(tmp_path):
    result, _, _ = build(tmp_path, {'records': [{'id': 'a', 'unknowns': ['animal identity']}]}, ['a'])
    assert result['audit']['selections'][0]['semantic_completeness'] == 'NOT_ASSESSED'
    assert next(iter(result['view']['units'].values()))['records']['a']['value']['unknowns'] == ['animal identity']


def test_pinned_run_does_not_follow_mutable_pointer(tmp_path):
    library = tmp_path / 'library.json'; library.write_text('{}')
    binding = tmp_path / 'binding.json'; binding.write_text(json.dumps({'bindings': {'source': cb.file_ref(library)}}))
    config = tmp_path / 'current.json'
    config.write_text(json.dumps({'version': 'ACTIVE_CONTEXT_LIBRARY_1.0',
        'library_binding': cb.file_ref(binding), 'runtime_bindings': {}}))
    selected, _ = context_library.pin_run(tmp_path / 'run', config_path=config)
    config.write_text('not a valid future pointer')
    assert context_library.pin_run(tmp_path / 'run', config_path=config)[0] == selected
    library.write_text('changed')
    with pytest.raises(ValueError, match='Changed input'):
        context_library.pin_run(tmp_path / 'run', config_path=config)


def test_request_transform_is_scoped_and_does_not_recurse():
    from ctxcomp import governance
    from ctxcomp.io import digest
    calls = []
    original = {'stage': 'TEST', 'instructions': 'Test only.'}
    def transform(request):
        calls.append(request)
        nested = governance.governed_request({'stage': 'NESTED'})
        assert nested['payload']['stage'] == 'NESTED'
        result = copy.deepcopy(request)
        result['payload']['prepared'] = True
        result['request_sha256'] = digest(result['payload'])
        return result
    with governance.request_transform(transform):
        assert governance.governed_request(copy.deepcopy(original))['payload']['prepared'] is True
    assert len(calls) == 1
    assert 'prepared' not in governance.governed_request(copy.deepcopy(original))['payload']


def test_active_scope_does_not_retrieve_for_unrelated_steps(tmp_path, monkeypatch):
    from ctxcomp import governance
    monkeypatch.setattr(context_library, 'pin_run', lambda *a, **k: pytest.fail('Unexpected library access'))
    with context_library.request_scope(tmp_path):
        result = governance.governed_request({'stage': 'HUMAN_REVIEW_SUMMARY_ONLY'})
    assert 'context_support' not in result['payload']
