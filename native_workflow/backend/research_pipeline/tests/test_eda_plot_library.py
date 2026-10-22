"""Offline contract tests; no model, extraction or renderer execution."""
import copy
import json
import pytest
from ctxcomp.io import digest
from research_pipeline import eda_plot_library as library, eda_context as eda
from research_pipeline import context_builder as cb, context_model_view as cmv
from research_pipeline.context_gateway import assemble
from research_pipeline.minimal_context_reducer import expand_payload
from research_pipeline.eda_ep_full import OPERATIONS, schema as full_schema
from test_eda_context import fixtures


def test_catalog_candidates_do_not_expand_renderer_registry():
    data = library.load()
    assert len(data['methods']) == 21
    assert len(data['shared_options']) == 8
    assert OPERATIONS == ['SOURCE_TABLE', 'SOURCE_XY_POINTS']
    assert {op for m in data['methods'] for op in m['execution']['candidate_operation_ids']} == {'SOURCE_XY_POINTS'}
    assert 'EPG001' not in json.dumps(full_schema([]))


@pytest.mark.parametrize('call', ['EP-plan', 'EI-findings', 'ER-review'])
def test_only_ep_receives_library_and_preserves_inputs(call):
    inputs, schema = fixtures(call)
    original = copy.deepcopy(inputs)
    bundle = eda.prepare(call, inputs, schema)
    cb.verify_bundle(bundle)
    visible, _ = cmv.project(bundle['request'])
    payload = expand_payload(visible['payload'])
    for name, value in original.items():
        assert payload[name] == value
    reference = payload['scientific_reference']
    if call == 'EP-plan':
        assert reference['plot_method_library'] == library.load()
        assert bundle['request']['payload']['eda_context_bindings']['ep_plot_library'] == cb.file_ref(library.CATALOG)
    else:
        assert 'plot_method_library' not in reference
        assert 'ep_plot_library' not in bundle['request']['payload']['eda_context_bindings']


def test_modified_planning_guidance_cannot_bypass_authoritative_input():
    inputs, schema = fixtures('EP-plan')
    request = eda.prepare('EP-plan', inputs, schema)['request']
    request['payload']['scientific_reference']['plot_method_library']['methods'][0]['limitations'] = 'No limitations'
    request['request_sha256'] = digest(request['payload'])
    with pytest.raises(ValueError, match='authoritative context mismatch'):
        assemble(request)


def test_library_change_invalidates_prepared_request(tmp_path, monkeypatch):
    path = tmp_path / 'catalog.json'
    data = library.load()
    path.write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr(library, 'CATALOG', path)
    inputs, schema = fixtures('EP-plan')
    request = eda.prepare('EP-plan', inputs, schema)['request']
    data['methods'][0]['limitations'] += ' Changed after assembly.'
    path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='changed EDA context bindings'):
        assemble(request)


@pytest.mark.parametrize('mutation', ['duplicate_id', 'unknown_source', 'execution_authority'])
def test_invalid_library_fails_closed(tmp_path, monkeypatch, mutation):
    data = library.load()
    if mutation == 'duplicate_id':
        data['methods'][1]['id'] = data['methods'][0]['id']
    elif mutation == 'unknown_source':
        data['methods'][0]['source_ids'] = ['NONEXISTENT']
    else:
        data['methods'][0]['execution']['planning_status'] = 'IMPLEMENTED'
    path = tmp_path / 'invalid.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr(library, 'CATALOG', path)
    with pytest.raises(ValueError):
        library.load()
