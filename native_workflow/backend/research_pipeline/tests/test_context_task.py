"""Shared orchestration preserves stage responsibility and input identity."""
import copy

import pytest

from research_pipeline import context_builder as cb, context_task as task, eda_context
from research_pipeline.common import read_json


SCHEMA = {'type': 'object', 'properties': {'version': {'type': 'string'}}}


def fixture(route):
    config = read_json(cb.CONFIG)['routes'][route]
    if route.startswith('eda.'):
        call_id = config['identity']['stage'][0]
        pack, call, agent, *_ = eda_context._contract(call_id)
        names = set(agent['inputs']) - {'human_confirmation', 'scientific_reference'}
        inputs = {name: {'status': 'TEST_ONLY', 'limitations': ['No invented identities']}
                  for name in names}
        inputs['task_context']['implemented_r_operations'] = []
        schema = {'type': 'object', 'required': pack['artifact_contracts'][eda_context.MODEL_OUTPUT[call_id]]['required_fields']}
        return eda_context.prepare(call_id, inputs, schema)
    payload = {'instructions': 'Perform only the original assigned task.'}
    payload.update({key: values[0] for key, values in config['identity'].items()})
    for key in config['required']:
        payload.setdefault(key, [])
    if config.get('preserve_adapter_fields'):
        payload['upstream_result'] = {'decision': 'CONDITIONAL', 'source_scope': 'S02 group means',
            'conditions': ['No animal pairing'], 'limitations': ['Unknown assay limit'],
            'counterevidence': ['Independent contradictory source'], 'future_field': 'keep'}
    return cb.build_context(*route.split('.', 1), payload, SCHEMA)


@pytest.mark.parametrize('route', list(read_json(cb.CONFIG)['routes']))
def test_every_registered_step_uses_same_zero_retrieval_orchestrator(route):
    original = fixture(route)
    before = copy.deepcopy(original)
    assembled = task.assemble(original)
    assert assembled['request'] == original['request']
    assert original == before
    cb.verify_bundle(assembled)
    assert assembled['context_manifest']['model_calls'] == 0


@pytest.mark.parametrize('route', ['data.coverage', 'data.human_summary', 'compression.review',
                                  'eda.findings', 'eda.review'])
def test_evidence_and_downstream_tasks_cannot_start_optional_retrieval(route):
    calls = []
    with pytest.raises(ValueError, match='outside this task responsibility'):
        task.assemble(fixture(route), retrieval_needs=[{'question': 'irrelevant'}],
                      retriever=lambda *a, **k: calls.append(1))
    assert calls == []


def test_bound_retrieval_changes_only_declared_optional_field(tmp_path):
    original = fixture('eda.plan')
    packet = tmp_path / 'packet.json'
    packet.write_text('{"test":"frozen methods"}', encoding='utf-8')
    seen = []
    def retrieve(needs, project, *, consumer_route):
        seen.append((needs, project, consumer_route))
        return {'background': {'method': 'Group means remain group means'},
                'bindings': {'test_packet': cb.file_ref(packet)}}
    needs = [{'question': 'Which display is supported?', 'query': 'concentration time',
              'stage': 'data_eda', 'allowed_source_ids': ['S_METHOD']}]
    result = task.assemble(original, retrieval_needs=needs, retriever=retrieve)
    payload = copy.deepcopy(result['request']['payload'])
    payload.pop('context_task_bindings')
    assert payload['task_context'].pop('reviewed_method_background_v1') == {
        'method': 'Group means remain group means'}
    assert payload == original['request']['payload']
    assert len(seen) == 1
    assert seen[0][2] == 'method_background'
    # The mandatory gateway reconstructs from the request, without the wrapper's
    # Python bundle. Bound evidence must still survive this exact boundary.
    from research_pipeline import context_gateway, context_model_view
    rebuilt = context_gateway.assemble(result['request'])
    assert rebuilt['context_manifest']['input_bindings']['test_packet'] == cb.file_ref(packet)
    visible, _ = context_model_view.project(result['request'])
    assert 'context_task_bindings' not in visible['payload']
    packet.write_text('{}', encoding='utf-8')
    with pytest.raises(Exception, match='Changed input'):
        cb.verify_bundle(result)
    with pytest.raises(Exception, match='Changed input'):
        context_gateway.assemble(result['request'])


def test_authoritative_source_changed_during_retrieval_is_not_rebound(tmp_path):
    source = tmp_path / 'source.txt'
    source.write_text('Original input', encoding='utf-8')
    original = fixture('eda.plan')
    payload = original['request']['payload']
    original = cb.build_context('eda', 'plan', payload, payload['schema'],
                                 input_bindings={'source': cb.file_ref(source)})
    def retrieve(*args, **kwargs):
        source.write_text('Changed while retrieving', encoding='utf-8')
        return {'background': {'method': 'unused'}, 'bindings': {}}
    with pytest.raises(Exception, match='Changed input'):
        task.assemble(original, retrieval_needs=[{'question': 'Question', 'query': 'query',
            'stage': 'data_eda', 'allowed_source_ids': ['S_METHOD']}], retriever=retrieve)


@pytest.mark.parametrize('route', ['data.requirements', 'data.necessity', 'eda.plan'])
def test_declared_downstream_needs_survive_shared_projection_without_creating_execution(route):
    from research_pipeline import context_gateway, context_model_view
    from research_pipeline.minimal_context_reducer import expand_payload

    original = fixture(route)
    payload = copy.deepcopy(original['request']['payload'])
    field = 'task_context' if route.startswith('eda.') else 'project_context'
    if not isinstance(payload.get(field), dict):
        payload[field] = {}
    needs = [{'id': 'OBSERVED_RESPONSE_RANGE',
              'question': 'Which reported effects support later target analysis?',
              'downstream_use': 'Identify observed range before fitting.',
              'conditions': ['Use a supported group baseline; retain ND.'],
              'limitations': ['No fitted target or paired-animal uncertainty is authorized.']}]
    payload[field]['decision_needs'] = needs
    payload[field]['conditional_candidates'] = [
        {'id': 'FIXED_ENDPOINT', 'question': 'Absolute and supported baseline-change response',
         'implemented': False, 'disposition_required': True}]
    original = cb.build_context(*route.split('.', 1), payload, payload['schema'],
                                input_bindings=original['context_manifest']['input_bindings'])
    assembled = task.assemble(original)
    assert context_gateway.assemble(assembled['request'])['request'] == original['request']
    visible, _ = context_model_view.project(assembled['request'])
    expanded = expand_payload(visible['payload'])
    assert expanded[field]['decision_needs'] == needs
    assert expanded[field]['conditional_candidates'] == payload[field]['conditional_candidates']
    assert assembled['context_manifest']['model_calls'] == 0
