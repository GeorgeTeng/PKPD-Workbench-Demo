"""EP contract/provenance checks only; no model or EDA runtime execution."""
import copy
from pathlib import Path

import jsonschema
import pytest
from ctxcomp import providers
from research_pipeline import context_builder as cb, context_model_view as cmv, eda_context, eda_ep
from research_pipeline.common import read_json, write_json
from research_pipeline.minimal_context_reducer import expand_payload

ROOT = Path(__file__).resolve().parents[3]
INPUTS = ROOT / 'outputs/EDA_ContextBuilder_TEST_20261015/ep_inputs.json'
MAIN = ROOT / 'outputs/ContextBuilder_Minimal_Fixture_20261015/main.json'
CATALOG = (ROOT / 'backend/research_pipeline/research_pipeline/resources/context_builder/reference_catalogs'
           / read_json(eda_context.PACK)['source']['current_reference_catalog']['file'])
SELECTION = [{'path': ['scientific_reference', 'text'], 'catalog': cb.file_ref(CATALOG),
              'selected': ['01', '02', '03', '06', '08', '11', '15']}]


def changed(tmp_path, mutate):
    value = read_json(INPUTS)
    mutate(value)
    return write_json(tmp_path / 'inputs.json', value)


def test_all_assigned_cells_and_notes_round_trip_and_keep_limits():
    original = read_json(INPUTS)
    inputs, bindings, audit = eda_ep.intake(INPUTS)
    assert audit['source_cells'] == len(audit['source_ids']) == 148
    assert audit['full_project_rules'] == audit['model_project_rules'] == 56
    for before, after in zip(original['data_handoff']['source_items'], inputs['data_handoff']['source_items']):
        assert before['profile'] == after['profile']
        assert eda_ep.unpack_rows(after['source_rows']) == before['source_rows']
    assert original['data_handoff']['unresolved_and_limitations'] == inputs['data_handoff']['unresolved_and_limitations']
    assert original['task_context']['project_rules'] == inputs['task_context']['project_rules']
    assert 'scientific_context' not in inputs['task_context']
    assert 'study' not in inputs['task_context']
    assert inputs['task_context']['project_evaluation_setting'] == original['task_context']['study']['population']
    assert not any('conflict' in k for k in inputs['task_context']['planning_boundary'])
    cb.check_refs(bindings)


def test_published_routing_preserves_exact_operative_fields_and_exclusion_audit():
    original = read_json(INPUTS)
    inputs, refs, audit = eda_ep.intake(INPUTS, rule_context_path=MAIN)
    expected_ids = ['R034', 'R035', 'R036', 'R052', 'R054']
    assert audit['full_project_rules'] == 56 and audit['model_project_rules'] == 5
    assert audit['rule_routing']['included_ids'] == expected_ids
    assert len(audit['rule_routing']['excluded_ids']) == 51
    assert audit['rule_routing']['original_projection']['unresolved'] == []
    assert inputs['task_context']['project_rules'] == [r for r in original['task_context']['project_rules'] if r['id'] in expected_ids]
    assert refs['ep:published_rules'] == read_json(MAIN)['project_rules_ref']


def test_original_duties_governance_and_science_survive_shared_projection(monkeypatch):
    monkeypatch.setattr(providers, 'codex_generate', lambda *a, **k: pytest.fail('No model call'))
    bundle, audit = eda_ep.prepare(INPUTS, rule_context_path=MAIN, reference_selection=SELECTION)
    projected, projection = cmv.project(bundle['request'])
    visible = expand_payload(projected['payload'])
    original_pack = read_json(eda_context.PACK)
    assert visible['instructions'] == bundle['request']['payload']['instructions']
    assert visible['processing_rules'] == [r for r in original_pack['rules'] if 'EP-plan' in r['calls']]
    assert [r['id'] for r in visible['governance']['rules']] == [f'G{i:03}' for i in range(1, 9)]
    assert visible['output_contract'] == original_pack['artifact_contracts']['eda_plan']
    assert visible['eda_scope'] == original_pack['scope']
    assert visible['transport_scope']['rendered_images_supplied'] is False
    assert projection['reference_selection']['fields'][0]['selected'] == SELECTION[0]['selected']
    assert 'GLOBAL' in [x['id'] for x in projection['reference_selection']['fields'][0]['included']]
    assert 'SOURCE_KEY' in [x['id'] for x in projection['reference_selection']['fields'][0]['included']]
    assert 'REVIEW_BOUNDARY' in [x['id'] for x in projection['reference_selection']['fields'][0]['included']]
    assert projection['minimal_context']['semantic_expansion_exact'] is True
    assert visible['data_handoff'] == bundle['request']['payload']['data_handoff']
    assert visible['task_context']['project_evaluation_setting'] == read_json(INPUTS)['task_context']['study']['population']
    assert 'do not infer project-wide absence' in visible['task_context']['planning_boundary']['evidence_scope']
    assert 'eda_context_bindings' not in visible and 'context_task_bindings' not in visible
    assert bundle['context_manifest']['execution_authorized'] is False
    assert 'reviewed_method_background_v1' not in visible['task_context']
    assert audit['provider_calls'] == 0 and audit['scientific_approval'] is False


def test_no_explicit_selection_safely_retains_full_reference():
    bundle, _ = eda_ep.prepare(INPUTS)
    visible, _ = cmv.project(bundle['request'])
    expanded = expand_payload(visible['payload'])
    assert expanded['scientific_reference']['text'] == bundle['request']['payload']['scientific_reference']['text']
    assert 'context_selection' not in bundle['request']['payload']


@pytest.mark.parametrize('mutate, message', [
    (lambda x: x['task_context'].update(extra_scientific_limit='unknown'), 'unknown task'),
    (lambda x: x['data_handoff'].update(quarantine=['unreviewed']), 'unknown handoff'),
    (lambda x: x['data_handoff']['source_items'][0]['source_rows'][0].update(condition='unknown'), 'unknown or missing row'),
    (lambda x: x['data_handoff']['source_items'][0]['source_rows'][0]['cells'][0].update(censoring='unknown'), 'unknown cell'),
    (lambda x: x['data_handoff']['source_items'][0]['source_rows'][1]['cells'][0].update(raw_value='changed'), 'source cells differ'),
    (lambda x: x['data_handoff']['source_items'][0]['profile'].update(record_level='individual animals'), 'profile differs'),
    (lambda x: x['data_handoff'].update(status='READY'), 'only the unapproved TEST'),
    (lambda x: x['task_context']['fixture_scope'].update(no_production_admission_or_release=False), 'explicit TEST'),
    (lambda x: x['task_context']['fixture_scope']['authorized_item_ids'].reverse(), 'scope/order'),
])
def test_unknown_limits_or_invalid_identity_stop_before_assembly(tmp_path, mutate, message):
    with pytest.raises(ValueError, match=message):
        eda_ep.prepare(changed(tmp_path, mutate))


def test_rules_changed_from_published_pack_cannot_use_original_routing(tmp_path):
    path = changed(tmp_path, lambda x: x['task_context']['project_rules'][0].update(text='changed'))
    with pytest.raises(ValueError, match='differ from the published'):
        eda_ep.prepare(path, rule_context_path=MAIN)


def test_changed_assigned_evidence_stops_bundle_verification(tmp_path):
    path = write_json(tmp_path / 'inputs.json', read_json(INPUTS))
    bundle, _ = eda_ep.prepare(path)
    write_json(path, {'changed': True})
    with pytest.raises(ValueError, match='Changed input'):
        cb.verify_bundle(bundle)


def test_output_schema_encodes_original_fields_without_workflow_or_new_duties():
    schema = eda_ep.response_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    artifact = read_json(eda_context.PACK)['artifact_contracts']['eda_plan']
    assert schema['required'] == artifact['required_fields']
    analysis = schema['properties']['analyses']['items']
    assert analysis['required'] == artifact['analysis_fields']
    assert set(analysis['properties']) == set(artifact['analysis_fields'])
    assert analysis['properties']['display_spec']['required'] == artifact['display_spec_fields']
    assert set(analysis['properties']['display_spec']['properties']) == set(artifact['display_spec_fields'])
    candidate = {'version': 'OFFLINE_SCHEMA_TEST_ONLY', 'input_refs': {'dataset_ids': ['F0004:S1:T28']},
                 'objective': 'Schema fixture, not a scientific plan.', 'analyses': [],
                 'not_planned': [], 'open_items': []}
    jsonschema.validate(candidate, schema)
    candidate['analyses'] = [{'analysis_id': 'MISSING_ORIGINAL_FIELDS'}]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(candidate, schema)
    candidate['analyses'] = []
    candidate['input_refs'] = {'path': 'Must not request a mechanical binding from the model'}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(candidate, schema)


def test_base_schema_has_no_shared_mutable_field_nodes():
    schema = eda_ep.response_schema()
    seen = {}
    def visit(value, path):
        if isinstance(value, (dict, list)):
            assert id(value) not in seen, ('schema aliases', seen.get(id(value)), path)
            seen[id(value)] = path
            children = value.items() if isinstance(value, dict) else enumerate(value)
            for key, child in children:
                visit(child, path + '/' + str(key))
    visit(schema, '')


def test_execution_schema_descriptions_stay_with_their_scientific_field():
    from research_pipeline import eda_ep_execution
    schema = eda_ep_execution.execution_schema()
    root = schema['properties']
    analysis = root['analyses']['items']['properties']
    display = analysis['display_spec']['properties']
    assert root['version'] is not root['objective']
    assert root['version']['description'].startswith('A concise plan-format identifier')
    assert root['objective']['description'].startswith('Copy task_context.objective exactly')
    assert 'description' not in analysis['analysis_id']
    assert 'description' not in analysis['question']
    assert analysis['experimental_unit']['description'].startswith('For typed execution, copy the exact permitted experimental_unit')
    assert analysis['status']['description'].startswith('Only PLANNED tasks')
    assert display['kind']['description'].startswith('Use an exact registered display kind')
    assert display['uncertainty_definition']['description'].startswith('Registered machine CODE ONLY')
    assert 'description' not in display['caption_limits']
    root['objective']['description'] = 'MUTATED_OBJECTIVE_DESCRIPTION'
    assert analysis['status']['description'].startswith('Only PLANNED tasks')
    assert root['version']['description'].startswith('A concise plan-format identifier')
