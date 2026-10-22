"""V5 coverage handoff preserves facts and action gates without rejudging summaries."""
import copy

import pytest
from ctxcomp.io import digest
from research_pipeline import data_necessity_v4 as legacy
from research_pipeline import data_necessity_v5 as n
from research_pipeline.common import PipelineError, read_json, write_json
from test_data_necessity_v4 import fixture, rules, answer, wire_answer


def inputs(*, pure=True, complete=True):
    plan, coverage, catalog = fixture(status='UNRESOLVED')
    coverage['version'] = 'COVERAGE_FACTS_5.0'
    coverage['complete'] = complete
    field = coverage['matches'][0]['criteria'][0]
    full = copy.deepcopy(field)
    full.update(id='FULL_REQUIREMENT', host_derivation={
        'version': 'CONSTITUENT_FACTS_1.0', 'pure_aggregate': pure,
        'constituent_ids': ['FIELD_001']})
    coverage['matches'][0]['criteria'].insert(0, full)
    return plan, coverage, catalog


def test_real_v5_digest_and_original_facts_are_preserved():
    plan, coverage, catalog = inputs()
    before = copy.deepcopy(coverage)
    payload = n.build_payload(plan, coverage, catalog, project_rules=rules())
    assert coverage == before
    assert payload['coverage_sha256'] == digest(coverage)
    assert payload['source_coverage_version'] == 'COVERAGE_FACTS_5.0'
    assert payload['operation'] == n.VERSION
    assert payload['units'][0]['criteria'] == coverage['matches'][0]['criteria']
    assert [g['criterion_id'] for g in payload['gaps']] == ['FIELD_001']


def test_pure_host_summary_not_repeated_as_a_model_gap_but_body_gap_retained():
    plan, coverage, catalog = inputs(pure=False)
    payload = n.build_payload(plan, coverage, catalog, project_rules=rules())
    assert {g['criterion_id'] for g in payload['gaps']} == {'FULL_REQUIREMENT', 'FIELD_001'}
    coverage['matches'][0]['criteria'][0]['host_derivation']['pure_aggregate'] = True
    payload = n.build_payload(plan, coverage, catalog, project_rules=rules())
    wire = n.transport_payload(payload)
    assert 'FULL_REQUIREMENT' not in wire['units'][0]['gap_criteria']
    assert wire['units'][0]['host_aggregates']['FULL_REQUIREMENT']['status'] == 'UNRESOLVED'


@pytest.mark.parametrize('change', ['incomplete', 'wrong_plan', 'unrecognized_derivation', 'missing_constituent', 'wrong_aggregate_status'])
def test_handoff_or_aggregate_proof_is_not_trusted_blindly(change):
    plan, coverage, catalog = inputs()
    if change == 'incomplete':
        coverage['complete'] = False
    elif change == 'wrong_plan':
        plan['requirements'][0]['required_by'] = 'BEFORE_PTA'
    elif change == 'unrecognized_derivation':
        coverage['matches'][0]['criteria'][0]['host_derivation']['version'] = 'FAKE'
    elif change == 'wrong_aggregate_status':
        coverage['matches'][0]['criteria'][0]['status'] = 'SUPPORTED'
    else:
        coverage['matches'][0]['criteria'][0]['host_derivation']['constituent_ids'] = ['UNKNOWN']
    with pytest.raises(PipelineError):
        n.build_payload(plan, coverage, catalog, project_rules=rules())


def test_action_disposition_keeps_full_coverage_and_original_safety_gates():
    plan, coverage, catalog = inputs()
    coverage['scoped_exclusions'] = [{'unit_id': 'EXCLUDED_UNIT',
        'reason': 'Verified upstream rule and scope exclusion', 'evidence': []}]
    payload = n.build_payload(plan, coverage, catalog, project_rules=rules())
    result = n.resolve(answer(payload), payload)
    assert result['version'] == n.VERSION
    assert result['coverage_facts'] == payload['units']
    assert result['scoped_exclusions'] == coverage['scoped_exclusions']
    assert len(result['decisions']) == 1
    assert not result['methods'][0]['actions'][1]['input_supported']
    assert not any(result[k] for k in ['scientific_approval', 'can_enter_qc', 'fit_ready'])


def test_new_data_cannot_be_inferred_from_unresolved_source_qualification():
    plan, coverage, catalog = inputs()
    payload = n.build_payload(plan, coverage, catalog, project_rules=rules())
    raw = answer(payload)
    d = raw['decisions'][0]
    d['disposition'] = 'NEW_DATA'
    d['for_action'] = d['first_dependency_action']
    d['new_data'] = {'needed_for_current_action': True, 'applicability_resolved': True,
        'permitted_search_complete': True, 'existing_material_can_supply': False,
        'definition_pending': False, 'planned_output_pending': False}
    with pytest.raises(PipelineError, match='immutable'):
        n.resolve(raw, payload)


def test_legacy_module_and_contract_remain_unchanged():
    before = (legacy.VERSION, legacy.build_payload, legacy._review_module)
    plan, coverage, catalog = inputs()
    n.build_payload(plan, coverage, catalog, project_rules=rules())
    assert (legacy.VERSION, legacy.build_payload, legacy._review_module) == before
    old_plan, old_cov, old_catalog = fixture()
    assert legacy.build_payload(old_plan, old_cov, old_catalog)['operation'] == 'DATA_NECESSITY_4.0'


def test_adapter_prepare_pause_run_and_replay_bind_actual_code(tmp_path, monkeypatch):
    plan, coverage, catalog = inputs()
    engine = n._engine()
    monkeypatch.setattr(engine, '_verified_inputs', lambda *a:
        (copy.deepcopy(plan), copy.deepcopy(coverage), copy.deepcopy(catalog), rules()))
    monkeypatch.setattr(n, '_engine', lambda: engine)
    pp = write_json(tmp_path / 'inputs/plan.json', plan)
    cp = write_json(tmp_path / 'inputs/coverage.json', coverage)
    out = tmp_path / 'necessity'
    n.prepare(pp, cp, out)
    assert read_json(out / 'bindings.json')['adapter_code']['path'] == n.__file__
    calls = []
    def generate(request, **kwargs):
        calls.append(kwargs['model'])
        payload = read_json(out / 'parts/NEC01/payload.json')
        raw = wire_answer(payload)
        raw['request_sha256'] = request['request_sha256']
        return raw
    generate.executor_id = 'offline-v5-adapter-test'
    (out / 'PAUSE').write_text('pause', encoding='utf-8')
    assert n.run_prepared(out, generator=generate)['stop_reason'] == 'PAUSED'
    assert not calls
    (out / 'PAUSE').unlink()
    result = n.run_prepared(out, generator=generate)
    assert calls == ['gpt-6-sol']
    assert n.verify_result(out / 'necessity.json') == result
    assert n.run_prepared(out, generator=generate) == result and len(calls) == 1
    bindings = read_json(out / 'bindings.json')
    bindings.pop('adapter_code')
    write_json(out / 'bindings.json', bindings)
    with pytest.raises(PipelineError):
        n.verify_result(out / 'necessity.json')


def many_scope_payload():
    plan, coverage, catalog = inputs(pure=False)
    plan['requirements'].append(copy.deepcopy(plan['requirements'][0]))
    plan['requirements'][1]['id'] = 'RQ002'
    coverage['planning_sha256'] = digest(plan)
    match = copy.deepcopy(coverage['matches'][0])
    field = copy.deepcopy(match['criteria'][1])
    match['criteria'] = [{**copy.deepcopy(field), 'id': 'FIELD_' + str(i).zfill(3)} for i in range(30)]
    scope = copy.deepcopy(coverage['scopes'][0])
    coverage['scopes'], coverage['matches'] = [], []
    for i in range(34):
        sid = 'S' + str(i)
        coverage['scopes'].append({**copy.deepcopy(scope), 'id': sid})
        for requirement in ('RQ001', 'RQ002'):
            coverage['matches'].append({**copy.deepcopy(match), 'scope_id': sid,
                'requirement_id': requirement, 'unit_id': sid + '/' + requirement})
    return n.build_payload(plan, coverage, catalog, project_rules=rules())


def test_whole_unit_partition_avoids_half_empty_scope_packets_without_budget_increase():
    payload = many_scope_payload()
    engine = n._engine()
    parts = engine.partition(payload)
    assert len(parts) <= 32
    assert engine.PART_CRITERIA_LIMIT == 100
    assert engine.MAX_PARTS == engine.MAX_PROVIDER_CALLS == 32
    assert engine.MAX_TOTAL_PROVIDER_CHARS == 8_000_000 and engine.MODEL_BUDGET_SECONDS == 1500
    assert all(p['gap_criteria'] <= 100 and p['request_chars'] <= engine.data.REQUEST_BUDGET for p in parts)
    assert sum(p['request_chars'] for p in parts) <= 8_000_000
    units = [u for p in parts for u in p['payload']['units']]
    assert len(units) == len({u['unit_id'] for u in units}) == len(payload['units'])
    original = {u['unit_id']: u for u in payload['units']}
    assert all(u == original[u['unit_id']] for u in units)
    expected = {g['key'] for g in payload['gaps']}
    actual = [g['key'] for p in parts for g in p['payload']['gaps']]
    assert len(actual) == len(set(actual)) and set(actual) == expected
    full_raw = {'request_sha256': 'fixture', 'decisions': []}
    for part in parts:
        local = part['payload']
        canonical = engine.materialize_wire(wire_answer(local), local)
        full_raw['decisions'].extend(engine.rebase_decisions(canonical, local, payload))
    result = engine.resolve(full_raw, payload)
    assert len(result['methods']) == 34  # Two units in the same original scope still aggregate together.
    assert len(result['decisions']) == len(payload['gaps'])


@pytest.mark.parametrize('damage', ['duplicate', 'omit'])
def test_partition_rejects_overlapping_or_missing_gap_projection(monkeypatch, damage):
    plan, coverage, catalog = inputs()
    engine = n._engine()
    payload = engine.build_payload(plan, coverage, catalog, project_rules=rules())
    original = engine._part_payload
    def damaged(value, unit_ids):
        local = original(value, unit_ids)
        local['gaps'] = local['gaps'] * 2 if damage == 'duplicate' else []
        return local
    monkeypatch.setattr(engine, '_part_payload', damaged)
    with pytest.raises(PipelineError, match='duplicated or omitted'):
        engine.partition(payload)


def test_partition_preserves_local_evidence_enums_and_rejects_foreign_reference():
    plan, coverage, catalog = inputs()
    other = copy.deepcopy(coverage['matches'][0])
    other['scope_id'] = 'S2'
    for criterion in other['criteria']:
        for field in ('evidence', 'counterevidence'):
            for evidence in criterion.get(field, []):
                evidence['source'] = 'I2:note'
    coverage['matches'].append(other)
    scope = copy.deepcopy(coverage['scopes'][0])
    scope.update(id='S2', item_ids=['I2'])
    coverage['scopes'].append(scope)
    catalog['I2:note'] = {**copy.deepcopy(catalog['I1:note']), 'item_id': 'I2'}
    engine = n._engine()
    engine.PART_CRITERIA_LIMIT = 1  # Force two local packets, without loosening any bound.
    payload = engine.build_payload(plan, coverage, catalog, project_rules=rules())
    parts = engine.partition(payload)
    assert len(parts) == 2
    assert 'I2:note' not in parts[0]['payload']['evidence_catalog']
    assert 'I1:note' not in parts[1]['payload']['evidence_catalog']
    raw = wire_answer(parts[0]['payload'])
    next(iter(raw['units'].values()))['groups'][0]['evidence_refs'] = ['E99999']
    with pytest.raises(PipelineError):
        engine.materialize_wire(raw, parts[0]['payload'])


def test_partition_does_not_raise_budget_for_oversized_complete_unit():
    plan, coverage, catalog = inputs()
    engine = n._engine()
    payload = engine.build_payload(plan, coverage, catalog, project_rules=rules())
    base = payload['gaps'][0]
    payload['gaps'] = [{**base, 'key': base['key'] + '/' + str(i)} for i in range(101)]
    with pytest.raises(PipelineError, match='complete necessity unit'):
        engine.partition(payload)
