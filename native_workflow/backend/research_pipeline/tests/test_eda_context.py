"""Offline EDA routing checks. Fixtures are not approved Data or real EDA results."""
import copy
import re
from pathlib import Path
import pytest
from ctxcomp import context_dispatch, providers
from ctxcomp.io import digest
from research_pipeline import context_builder as cb, context_model_view as cmv
from research_pipeline import context_routes, eda_context as eda
from research_pipeline.common import read_json
from research_pipeline.context_linear import LinearSession
from research_pipeline.eda_framework import check_framework
from research_pipeline.minimal_context_reducer import expand_payload


def fixtures(call):
    pack, _, agent, _, _, _ = eda._contract(call)
    # Deliberately retain source uncertainty and identifiers through projection.
    inputs = {name: {'status': 'OFFLINE_INTERFACE_FIXTURE_NOT_EXECUTED'}
              for name in agent['inputs'] if name not in {'human_confirmation', 'scientific_reference'}}
    inputs['task_context'] = {'objective': 'Offline interface test only.', 'implemented_r_operations': []}
    inputs['data_handoff'] = {'status': 'OFFLINE_FIXTURE_NOT_APPROVED',
        'records': [{'source_id': 'S1', 'record_id': 'ROW1', 'species': 'mouse',
                     'matrix': 'serum', 'unit': 'mg/L', 'experimental_unit': 'group mean',
                     'value': None, 'censoring': 'UNKNOWN', 'dose_basis': 'unresolved'}],
        'open_items': ['Do not infer plasma, individual animals or zero concentration.']}
    contract = pack['artifact_contracts'][eda.MODEL_OUTPUT[call]]
    # Structural fixture only; no claim that these permissive field schemas are
    # a scientific validator or a production runtime response contract.
    schema = {'type': 'object', 'required': contract['required_fields'],
              'properties': {key: {} for key in contract['required_fields']},
              'additionalProperties': False}
    return inputs, schema


@pytest.mark.parametrize('call', tuple(context_routes.EDA))
def test_stage_input_and_scoped_rules_survive_model_projection(call):
    inputs, schema = fixtures(call)
    bundle = eda.prepare(call, inputs, schema)
    cb.verify_bundle(bundle)
    visible, audit = cmv.project(bundle['request'])
    decoded = expand_payload(visible['payload'])
    for name, value in inputs.items():
        assert decoded[name] == value
    pack = read_json(eda.PACK)
    assert decoded['processing_rules'] == [r for r in pack['rules'] if ('EP-plan' if call == 'EP-finalize' else call) in r['calls']]
    assert [r['id'] for r in decoded['governance']['rules']] == [f'G{i:03}' for i in range(1, 9)]
    assert decoded['schema'] == schema
    assert 'eda_context_bindings' not in decoded
    assert audit['host_only_fields']['payload/eda_context_bindings']
    assert decoded['transport_scope']['rendered_images_supplied'] is False
    assert audit['minimal_context']['semantic_expansion_exact'] is True
    assert 'human_confirmation' not in decoded and 'eda_handoff' not in decoded
    instructions = decoded['instructions']
    assert sum(s in instructions for s in ('Act as EP,', 'Act as EP.', 'Act as EP after EC.', 'Act as EI,', 'Act independently as ER,')) == 1
    assert bundle['context_manifest']['execution_authorized'] is False


@pytest.mark.parametrize('call', tuple(context_routes.EDA))
def test_default_provider_uses_prepared_eda_once(call, tmp_path, monkeypatch):
    inputs, schema = fixtures(call)
    request = eda.prepare(call, inputs, schema)['request']
    seen = []
    def stub(req, **kwargs):
        assert context_dispatch.prepared(req)
        seen.append(context_dispatch.model_input(req))
        return {'request_sha256': req['request_sha256'], 'offline_stub': True}
    monkeypatch.setattr(providers, '_codex_generate_raw', stub)
    providers.codex_generate(request, context_scope=tmp_path)
    with pytest.raises(ValueError, match='repeat'):
        providers.codex_generate(request, context_scope=tmp_path)
    assert len(seen) == 1
    slot = next((tmp_path / 'contextbuilder').iterdir())
    assert read_json(slot / 'model_input.json') == seen[0]
    assert read_json(slot / 'budget.json')['status'] == 'WITHIN_APPLICATION_BUDGET'
    assert read_json(slot / 'context_manifest.json')['input_bindings']['eda_rules'] == cb.file_ref(eda.PACK)


@pytest.mark.parametrize('stage,agent', [('EC-calculate','EC'), ('EV-plot','EV'),
    ('ER-handoff','ER'), ('EP-new', None), ('EC-calculate',None), ('EDA',None), ('DP','EP')])
def test_no_r_worker_handoff_or_unregistered_eda_model_bypass(stage, agent, tmp_path, monkeypatch):
    payload = {'stage': stage, 'instructions': 'No model call', 'schema': {'type':'object'}}
    if agent:
        payload['agent'] = agent
    request = {'payload': payload, 'request_sha256': digest(payload)}
    assert context_routes.managed(request)
    monkeypatch.setattr(providers, '_codex_generate_raw', lambda *a, **kw: pytest.fail('No transport'))
    with pytest.raises(ValueError):
        providers.codex_generate(request, context_scope=tmp_path)


@pytest.mark.parametrize('field', ['calculation_bundle', 'eda_findings', 'human_confirmation', 'raw_tables'])
def test_planner_cannot_receive_later_stage_inputs(field):
    inputs, schema = fixtures('EP-plan')
    inputs[field] = {'should_not_be_sent': True}
    with pytest.raises(ValueError, match='exactly'):
        eda.prepare('EP-plan', inputs, schema)


@pytest.mark.parametrize('field', ['processing_rules', 'instructions', 'transport_scope'])
def test_direct_gateway_cannot_replace_authoritative_context(field, tmp_path, monkeypatch):
    from research_pipeline.context_gateway import assemble
    inputs, schema = fixtures('ER-review')
    request = eda.prepare('ER-review', inputs, schema)['request']
    request['payload'][field] = [] if field == 'processing_rules' else 'changed'
    request['request_sha256'] = digest(request['payload'])
    with pytest.raises(ValueError, match='authoritative context mismatch'):
        assemble(request)


def test_changed_bound_input_stops_before_transport(tmp_path, monkeypatch):
    path = tmp_path / 'handoff.json'
    path.write_text('{}')
    inputs, schema = fixtures('EP-plan')
    request = eda.prepare('EP-plan', inputs, schema, input_bindings={'data_input':cb.file_ref(path)})['request']
    path.write_text('{"changed":true}')
    monkeypatch.setattr(providers, '_codex_generate_raw', lambda *a, **kw: pytest.fail('No transport'))
    with pytest.raises(ValueError, match='Changed input'):
        providers.codex_generate(request, context_scope=tmp_path / 'run')


def test_linear_order_and_no_repeat(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(providers, '_codex_generate_raw', lambda req, **kw: seen.append(req['payload']['stage']) or {})
    with LinearSession(tmp_path / 'linear').activate():
        for call in context_routes.EDA:
            inputs, schema = fixtures(call)
            providers.codex_generate(eda.prepare(call, inputs, schema)['request'])
    assert seen == ['EP-plan', 'EP-finalize', 'EI-findings', 'ER-review']
    with pytest.raises(ValueError, match='Backward stage'):
        with LinearSession(tmp_path / 'backward').activate():
            for call in ('ER-review', 'EP-plan'):
                inputs, schema = fixtures(call)
                providers.codex_generate(eda.prepare(call, inputs, schema)['request'])


def test_scaffold_runtime_stays_disabled():
    checked = check_framework()
    assert checked['model_calls_run'] == 0
    assert checked['eda_enabled'] is False
    assert checked['runtime_implemented'] is False


def test_planner_registry_and_schema_required():
    inputs, schema = fixtures('EP-plan')
    del inputs['task_context']['implemented_r_operations']
    with pytest.raises(ValueError, match='registry'):
        eda.prepare('EP-plan', inputs, schema)
    inputs, _ = fixtures('EP-plan')
    with pytest.raises(ValueError, match='artifact contract fields'):
        eda.prepare('EP-plan', inputs, {'type':'object'})


def test_eda_nested_project_rules_move_only_enumerated_audit_fields():
    inputs, schema = fixtures('EP-plan')
    project_root = Path(__file__).resolve().parents[3]
    rules = read_json(project_root / 'outputs/ContextBuilder_Minimal_Fixture_20261015/main.json')['rules']
    # Preserve an unknown extension to prove the projection is allowlist-based.
    rules = copy.deepcopy(rules)
    rules[0]['scientific_extension'] = {'must_remain': 'test caveat'}
    inputs['task_context']['project_rules'] = rules
    inputs['task_context']['fixture_scope'] = {
        'status': 'TEST_ONLY_NOT_PRODUCTION_ASSESSMENT',
        'authorized_item_ids': ['F0004:S1:T28', 'F0004:S1:T13', 'F0004:S1:T10'],
        'out_of_scope': 'NOT_IN_TEST_SCOPE; absence is not project-level missingness.'}
    host_inputs = copy.deepcopy(inputs)
    bundle = eda.prepare('EP-plan', inputs, schema)
    visible, audit = cmv.project(bundle['request'])
    decoded = expand_payload(visible['payload'])
    assert bundle['request']['payload']['task_context'] == host_inputs['task_context']
    assert decoded['schema'] == schema
    assert len(decoded['task_context']['project_rules']) == 56
    assert {k: v for k, v in decoded['task_context'].items() if k != 'project_rules'} == {
        k: v for k, v in host_inputs['task_context'].items() if k != 'project_rules'}
    assert audit['minimal_context']['semantic_expansion_exact'] is True

    host_only = {'evidence', 'field_evidence', 'authority_evidence',
                 'candidate_ids', 'classification_reason', 'routing_reason'}
    operative = {'id', 'kind', 'text', 'conditions', 'exceptions', 'scope',
                 'requirement', 'usage'}
    ledger = {entry['path']: entry['value'] for entry in audit['minimal_context']['mechanical_field_ledger']}
    for index, (before, after) in enumerate(zip(host_inputs['task_context']['project_rules'],
                                                 decoded['task_context']['project_rules'])):
        assert set(after) == set(before) - host_only
        for key in operative:
            assert after[key] == before[key]
        for key in set(before) - host_only:
            assert after[key] == before[key]
        for key in host_only & set(before):
            assert '/payload/task_context/project_rules/{}/{}'.format(index, key) in ledger
            assert ledger['/payload/task_context/project_rules/{}/{}'.format(index, key)] == before[key]

    # The pinned Rule evidence excerpts contain no restrictive caveat absent
    # from the operative Rule fields; those clauses stay visible in full.
    restrictive = re.compile(r'\b(?:no|not|never|only|must|shall|without|unless|except|'
                             r'unavailable|unknown|unverified|do not|does not|rather than)\b', re.I)
    for rule in host_inputs['task_context']['project_rules']:
        operative_text = ' '.join(str(rule.get(k, '')) for k in operative)
        for field in ('evidence', 'authority_evidence', 'field_evidence'):
            for entry in rule.get(field, []) or []:
                if isinstance(entry, dict) and isinstance(entry.get('quote'), str):
                    quote = entry['quote']
                    if restrictive.search(quote):
                        assert restrictive.search(operative_text), (rule['id'], field, quote)


def test_hidden_repair_is_still_blocked(tmp_path):
    from research_pipeline.context_gateway import assemble
    inputs, schema = fixtures('EP-plan')
    request = eda.prepare('EP-plan', inputs, schema)['request']
    request['payload']['contract_correction'] = {'previous_result': 'repair'}
    request['request_sha256'] = digest(request['payload'])
    with pytest.raises(ValueError, match='disabled'):
        assemble(request)


def test_eda_raw_transport_cannot_bypass_builder():
    inputs, schema = fixtures('EP-plan')
    request = eda.prepare('EP-plan', inputs, schema)['request']
    with pytest.raises(ValueError, match='bypass'):
        providers._codex_generate_raw(request)


def test_eda_over_budget_stops_without_truncating_or_sending(tmp_path, monkeypatch):
    from research_pipeline import context_budget as budget
    from research_pipeline.common import write_json
    policy = read_json(budget.POLICY)
    policy.update(total_characters=2000, reserved_output_characters=0)
    monkeypatch.setattr(budget, 'POLICY', write_json(tmp_path / 'budget.json', policy))
    inputs, schema = fixtures('ER-review')
    request = eda.prepare('ER-review', inputs, schema)['request']
    monkeypatch.setattr(providers, '_codex_generate_raw', lambda *a, **kw: pytest.fail('No transport'))
    with pytest.raises(ValueError, match='Final model input'):
        providers.codex_generate(request, context_scope=tmp_path / 'run')
    slot = next((tmp_path / 'run/contextbuilder').iterdir())
    assert read_json(slot / 'request.json') == request
    assert read_json(slot / 'status.json')['provider_started'] is False
