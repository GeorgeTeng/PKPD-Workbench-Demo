"""Typed EP -> TEST row-selection EC: contracts, provenance and actual R smoke."""
import copy
import importlib.util
from pathlib import Path

import pytest
from jsonschema import ValidationError
from ctxcomp.io import digest
from research_pipeline import context_builder as cb, eda_ec, eda_ep_execution as bridge
from research_pipeline.common import read_json, write_json

ROOT = Path(__file__).resolve().parents[3]
INPUTS = ROOT / 'outputs/EDA_ContextBuilder_TEST_20261015/ep_inputs.json'
MAIN = ROOT / 'outputs/ContextBuilder_Minimal_Fixture_20261015/main.json'
EXAMPLE = ROOT / 'outputs/EDA_EP_EC_Bridge_REVIEW_20261015/fixture_plan.py'
module_spec = importlib.util.spec_from_file_location('ep_ec_manual_fixture', EXAMPLE)
example = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(example)
SELECTION = [{'path': ['scientific_reference', 'text'], 'catalog': cb.file_ref(bridge.CATALOG),
              'selected': ['01', '02', '03', '06', '08', '11', '15']}]


@pytest.fixture(scope='module')
def prepared(tmp_path_factory):
    directory = tmp_path_factory.mktemp('ep_ec_original_request')
    bundle, _ = bridge.prepare(INPUTS, rule_context_path=MAIN, reference_selection=SELECTION)
    return write_json(directory / 'request.json', bundle['request'])


def receipt(tmp_path, prepared, mutate=None):
    plan = example.hand_authored_plan(INPUTS)
    if mutate:
        mutate(plan)
    path = write_json(tmp_path / 'plan.json', plan)
    target = tmp_path / 'receipt.json'
    bridge.record_test_plan(path, prepared, target)
    return target


def test_schema_keeps_original_output_fields_and_exposes_exact_signatures(prepared):
    from research_pipeline import eda_context
    pack = read_json(eda_context.PACK)['artifact_contracts']['eda_plan']
    schema = bridge.execution_schema()
    assert schema['required'] == pack['required_fields']
    assert set(schema['properties']['analyses']['items']['properties']) == set(pack['analysis_fields'])
    operations = read_json(prepared)['payload']['task_context']['implemented_r_operations']
    assert len(operations) == 3
    assert all(o['experimental_unit'] and o['executable_status'] == 'PLANNED' for o in operations)
    assert 'operation_version' not in str(schema)


def test_actual_r_smoke_preserves_all_values_groups_notes_nd_and_null(tmp_path, prepared):
    frozen = bridge.freeze(receipt(tmp_path, prepared))
    output = tmp_path / 'ec'
    bundle = eda_ec.execute(frozen, output)
    result = read_json(output / 'results.json')
    assert [len(r['rows']) for r in result['results']] == [8, 8, 3]
    assert [sum(len(row['cells']) for row in r['rows']) for r in result['results']] == [24, 64, 9]
    for actual, task in zip(result['results'], frozen['request']['tasks']):
        assert actual['rows'] == frozen['expected_rows'][actual['analysis_id']]
        assert actual['source_context'] == task['source_context']
        assert actual['computed_statistics'] is False
    pd = result['results'][1]
    assert pd['grouping']['columns'] == ['A', 'B', 'C']
    assert all([c['column'] for c in row['cells']] == list('ABCDEFGH') for row in pd['rows'])
    nd = [c['raw_value'] for row in pd['rows'] if row['source_row'] == 191 for c in row['cells'] if c['column'] in ['D','E','F']]
    assert nd == ['ND', 'ND', 'ND']
    assert pd['transform_aggregation_order']['transform'] == 'NONE'
    assert pd['transform_aggregation_order']['units']['D'] == 'log10 CFU/thigh'
    assert result['results'][0]['source_context']['notes'][0]['source_row'] is None
    assert result['results'][0]['source_context']['notes'][1]['cells'][0]['header'] is None
    assert (output / 'results.rds').is_file()
    assert bundle['checks']['r_started'] is True
    assert not bundle['checks']['computed_statistics'] and not bundle['checks']['figures_rendered']
    assert len(read_json(output / 'provenance.json')['source_cells']['EP_TEST_PD']) == 64


def test_cell_selector_resolves_exact_authorized_cells(tmp_path, prepared):
    def mutate(plan):
        analysis = plan['analyses'][0]
        analysis['record_selection'] = {'dataset_id': analysis['dataset_ids'][0], 'cell_ids': analysis['source_refs']}
    frozen = bridge.freeze(receipt(tmp_path, prepared, mutate))
    assert len(frozen['expected_rows']['EP_TEST_PK']) == 8


@pytest.mark.parametrize('mutate', [
    lambda p: p['analyses'][0]['formula_definition'].update(contract='STALE_TASK_0.1'),
    lambda p: p['analyses'][0]['record_selection'].update(columns=['A', 'Z']),
    lambda p: p['analyses'][0]['record_selection'].update(row_numbers=[9999]),
    lambda p: p['analyses'][0].update(record_selection={'dataset_id':'F0004:S1:T28','cell_ids':['F0004:S1:T13:D184']}),
    lambda p: p['analyses'][0]['input_relationships'].update(cross_dataset_join=True),
    lambda p: p['analyses'][1]['transform_aggregation_order'].update(transform='LOG10'),
    lambda p: p['analyses'][1]['censoring_policy'].update(mode='ND_AS_ZERO'),
    lambda p: p['analyses'][0]['formula_definition']['parameters'].update(code='system("arbitrary code")'),
    lambda p: p['input_refs']['rule_ids'].append('R001'),
    lambda p: p['input_refs']['reference_sections'].append('04'),
    lambda p: p['analyses'][0].update(source_refs=['F0004:S1:T13:A183']),
    lambda p: p['analyses'][0]['reference_sections'].append('04'),
])
def test_bad_version_selector_join_transform_or_citation_never_dispatches(tmp_path, prepared, mutate, monkeypatch):
    monkeypatch.setattr(eda_ec.subprocess, 'run', lambda *a, **k: pytest.fail('No R dispatch'))
    with pytest.raises((ValueError, ValidationError)):
        bridge.freeze(receipt(tmp_path, prepared, mutate))


@pytest.mark.parametrize('mutate', [
    lambda a: a['formula_definition'].update(operation_id='UNREGISTERED_NEW_AUC'),
    lambda a: a.update(experimental_unit='individual animals'),
    lambda a: a['grouping'].update(columns=['A']),
    lambda a: a['transform_aggregation_order']['units'].update(D='CFU/thigh'),
    lambda a: a['input_relationships'].update(baseline_scope='NOT_APPLICABLE'),
])
def test_local_unsupported_semantics_are_scoped_omissions_with_valid_siblings(tmp_path, prepared, mutate):
    frozen = bridge.freeze(receipt(tmp_path, prepared, lambda p: mutate(p['analyses'][1])))
    assert [t['analysis_id'] for t in frozen['request']['tasks']] == ['EP_TEST_PK','EP_TEST_MIC']
    assert frozen['request']['not_calculable'][0]['analysis_id'] == 'EP_TEST_PD'


def test_explicit_not_calculable_with_prose_fields_does_not_break_siblings(tmp_path, prepared):
    def mutate(plan):
        a = plan['analyses'][1]
        a.update(status='NOT_CALCULABLE', reason='No supported operation for this local question.',
                 record_selection='Not applicable: unsupported task.', grouping='Not applicable.',
                 transform_aggregation_order='Not applicable.', censoring_policy='Not applicable.',
                 input_relationships='Not applicable.')
    frozen = bridge.freeze(receipt(tmp_path, prepared, mutate))
    assert len(frozen['request']['tasks']) == 2 and len(frozen['request']['not_calculable']) == 1


def test_unknown_capability_with_prose_nonapplicable_fields_is_local(tmp_path, prepared):
    def mutate(plan):
        a = plan['analyses'][1]
        a['formula_definition']['operation_id'] = 'UNIMPLEMENTED_CALCULATION'
        a.update(record_selection='Not applicable: operation unsupported.', grouping='Not applicable.',
                 transform_aggregation_order='Not applicable.', censoring_policy='Not applicable.',
                 input_relationships='Not applicable.')
    frozen = bridge.freeze(receipt(tmp_path, prepared, mutate))
    assert len(frozen['request']['tasks']) == 2
    assert frozen['request']['not_calculable'][0]['analysis_id'] == 'EP_TEST_PD'


def test_legacy_prose_and_unknown_operations_do_not_start_r(tmp_path, prepared, monkeypatch):
    def mutate(plan):
        for a in plan['analyses']:
            a['formula_definition'] = 'Original prose is replay evidence, never a compiled operation.'
    frozen = bridge.freeze(receipt(tmp_path, prepared, mutate))
    monkeypatch.setattr(eda_ec.subprocess, 'run', lambda *a, **k: pytest.fail('No R dispatch'))
    result = eda_ec.execute(frozen, tmp_path / 'no_r')
    assert not result['checks']['r_started']
    assert len(result['not_calculable']) == 3


def test_late_changed_inputs_reject_original_receipt_without_rebinding(tmp_path):
    source = write_json(tmp_path / 'inputs.json', read_json(INPUTS))
    bundle, _ = bridge.prepare(source, rule_context_path=MAIN, reference_selection=SELECTION)
    request = write_json(tmp_path / 'request.json', bundle['request'])
    receipt_path = receipt(tmp_path, request)
    value = read_json(source)
    value['data_handoff']['scope_note'] += ' changed after EP preparation'
    write_json(source, value)
    with pytest.raises(ValueError, match='Changed input'):
        bridge.freeze(receipt_path)


@pytest.mark.parametrize('binding', ['REGISTRY', 'HANDLER'])
def test_late_changed_registry_or_handler_rejects_original_binding(tmp_path, monkeypatch, binding):
    source = getattr(bridge, binding)
    target = tmp_path / source.name
    target.write_bytes(source.read_bytes())
    monkeypatch.setattr(bridge, binding, target)
    bundle, _ = bridge.prepare(INPUTS, rule_context_path=MAIN, reference_selection=SELECTION)
    request = write_json(tmp_path / 'request.json', bundle['request'])
    receipt_path = receipt(tmp_path, request)
    target.write_bytes(target.read_bytes() + b'\n ')
    with pytest.raises(ValueError, match='Changed input'):
        bridge.freeze(receipt_path)


def test_frozen_task_cannot_be_rehashed_to_bypass_bound_plan(tmp_path, prepared):
    frozen = bridge.freeze(receipt(tmp_path, prepared))
    frozen['request']['tasks'][0]['source_rows'][0]['cells'][1]['raw_value'] = '0'
    frozen['request_sha256'] = digest(frozen['request'])
    with pytest.raises(ValueError, match='differs from bound plan'):
        bridge.verify(frozen)


def test_changed_plan_and_reused_receipt_are_rejected(tmp_path, prepared):
    receipt_path = receipt(tmp_path, prepared)
    plan_path = tmp_path / 'plan.json'
    with pytest.raises(ValueError, match='already exists'):
        bridge.record_test_plan(plan_path, prepared, receipt_path)
    write_json(plan_path, {'changed': True})
    with pytest.raises(ValueError, match='Changed input'):
        bridge.freeze(receipt_path)


def mock_gateway(tmp_path, prepared):
    """Write a labeled MOCK evidence fixture; invoke no gateway or provider."""
    from research_pipeline import context_gateway, context_model_view
    slot = tmp_path / 'MOCK_TRANSPORT_ONLY'
    request = read_json(prepared)
    wire, _ = context_model_view.project(request)
    response = example.hand_authored_plan(INPUTS)
    response['version'] = 'MOCK_EP_RESPONSE_NOT_LIVE_MODEL_OUTPUT'
    write_json(slot / 'request.json', request)
    write_json(slot / 'response.json', response)
    write_json(slot / 'model_input.json', wire)
    write_json(slot / 'transport_schema.json', request['payload']['schema'])
    write_json(slot / 'status.json', {'status': 'RETURNED_PENDING_STAGE_VALIDATION',
                                     'request_sha256': request['request_sha256'],
                                     'task_identity': context_gateway.task_identity(request['payload']),
                                     'provider_started': True})
    write_json(slot / 'provider/call.json', {'status': 'RETURNED', 'exit_code': 0,
                                            'request_sha256': request['request_sha256'],
                                            'provider': 'MOCK_TRANSPORT', 'mock_transport': True})
    return slot


def test_saved_response_interface_accepts_explicit_mock_without_live_claim(tmp_path, prepared):
    slot = mock_gateway(tmp_path, prepared)
    target = tmp_path / 'model_receipt.json'
    recorded = bridge.record_model_plan(prepared, slot, target, evidence_kind='MOCK_TRANSPORT_RESPONSE')
    assert recorded['origin'] == 'MOCK_TRANSPORT_RESPONSE'
    assert not recorded['model_generated'] and not recorded['served_model_identity_verified']
    assert recorded['plan_ref'] == cb.file_ref(slot / 'response.json')
    frozen = bridge.freeze(target)
    assert len(frozen['request']['tasks']) == 3


def test_mock_cannot_be_relabeled_as_live_model_evidence(tmp_path, prepared):
    with pytest.raises(ValueError, match='mock transport cannot be labeled'):
        bridge.record_model_plan(prepared, mock_gateway(tmp_path, prepared), tmp_path / 'receipt.json')


@pytest.mark.parametrize('mutation', ['missing_call', 'wrong_request', 'wrong_task', 'bad_response', 'different_transport'])
def test_response_receipt_rejects_missing_or_mismatched_evidence(tmp_path, prepared, mutation):
    slot = mock_gateway(tmp_path, prepared)
    if mutation == 'missing_call':
        (slot / 'provider/call.json').unlink()
    elif mutation == 'wrong_request':
        call = read_json(slot / 'provider/call.json')
        call['request_sha256'] = 'stale'
        write_json(slot / 'provider/call.json', call)
    elif mutation == 'wrong_task':
        status = read_json(slot / 'status.json')
        status['task_identity']['stage'] = 'EI-findings'
        write_json(slot / 'status.json', status)
    elif mutation == 'bad_response':
        write_json(slot / 'response.json', {'version': 'MOCK_SCHEMA_FAILURE'})
    else:
        write_json(slot / 'model_input.json', {'different_transport': True})
    with pytest.raises((ValueError, ValidationError, OSError)):
        bridge.record_model_plan(prepared, slot, tmp_path / 'receipt.json', evidence_kind='MOCK_TRANSPORT_RESPONSE')


def test_changed_saved_response_after_receipt_is_rejected(tmp_path, prepared):
    slot = mock_gateway(tmp_path, prepared)
    target = tmp_path / 'receipt.json'
    bridge.record_model_plan(prepared, slot, target, evidence_kind='MOCK_TRANSPORT_RESPONSE')
    response = read_json(slot / 'response.json')
    response['analyses'][0]['reason'] = 'Changed after binding'
    write_json(slot / 'response.json', response)
    with pytest.raises(ValueError, match='Changed input'):
        bridge.freeze(target)


def test_saved_response_must_also_satisfy_exact_saved_transport_schema(tmp_path, prepared):
    from research_pipeline import eda_ep_transport
    from research_pipeline.context_linear import assemble
    slot = mock_gateway(tmp_path, prepared)
    host_schema = read_json(prepared)['payload']['schema']
    strict_schema = eda_ep_transport.schema(host_schema, read_json(bridge.REGISTRY),
                                           scope=bridge._semantic_scope(assemble(read_json(prepared)))[1])
    write_json(slot / 'transport_schema.json', strict_schema)
    # The old manual response is host-valid but has redundant root references
    # forbidden by this stricter saved transport. It must never gain a receipt.
    with pytest.raises(ValidationError):
        bridge.record_model_plan(prepared, slot, tmp_path / 'receipt.json', evidence_kind='MOCK_TRANSPORT_RESPONSE')
