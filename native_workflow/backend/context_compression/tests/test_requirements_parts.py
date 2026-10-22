"""Compression rules 1.25.0 to 1.30.0 (CC002): the requirements inventory as a proposal part, then parallel supporting
parts; 1.31.0 starts every part at once (test_parallel_requirements_parts.py). Authored inventories exercise the host
contract only, not extraction quality."""
import copy
import pytest

from ctxcomp import engine, requirements_parts as parts
from ctxcomp.engine import accept, prepare, load_run, accepted_response
from ctxcomp.io import read_json, write_json
from ctxcomp.providers import run_model
from ctxcomp.rules import load_rules
from test_retention import demo
from test_supporting_scope import cited_run, QUOTE
from rule_versions import before_1_31, freeze


@pytest.fixture(autouse=True)
def sequential_parts(monkeypatch):
    freeze(monkeypatch, before_1_31())


def generator(units, proposal, passage, calls, target='P01', binding=None):
    def generate(request, model=None):
        p = request['payload']; part = p.get('inventory_part', {}).get('part', p['stage'])
        calls.append(part)
        if part == 'binding_repair':
            task = p['tasks'][0]
            return {'request_sha256': request['request_sha256'], 'method_ref_repairs': [], 'repairs': [
                {'item_id': task['item_id'], 'binding_index': task['binding_index'], 'status': 'CORRECTED',
                 'replacements': [{'field': task['field'], 'component_ids': task['component_ids'], 'value': QUOTE}],
                 'reason': 'Authored exact excerpt.'}]}
        if part == 'proposal':
            inventory = demo.fixture_requirements({'/objective': 'Study animal PK.'}, units, proposal[0]['source_id'])
            inventory['items'][0]['id'] = 'P01'
        else:
            assert part == 'supporting_A'
            inventory = demo.fixture_requirements({'/data/available/0': QUOTE}, units, passage['id'])
            item = inventory['items'][0]; item['id'] = 'SA01'
            item['science']['relations'] = [{'type': 'SUPPORTS', 'target_id': target, 'component_ids': ['C1']}]
            if binding: item['science']['bindings'] = [{'field': 'experimental_unit', 'value': binding, 'component_ids': ['C1']}]
        return {'request_sha256': request['request_sha256'], 'requirements': inventory}
    return generate


def test_inventory_runs_as_a_proposal_part_then_supporting_parts(tmp_path):
    run, passage, units, proposal = cited_run(tmp_path); calls = []
    base = prepare(run, 'requirements')
    assert parts.enabled(base['payload'])
    result = run_model(run, generator=generator(units, proposal, passage, calls), until='requirements', review_executor_id='test')
    assert result == {'status': 'STAGE_READY', 'stage': 'requirements'}
    assert calls == ['proposal', 'supporting_A']
    inventory = accepted_response(run, load_run(run)[1], 'requirements')['requirements']
    assert [r['id'] for r in inventory['items']] == ['P01', 'SA01']
    proof = read_json(run/parts.PROOF)
    assert set(proof['parts']) == {'proposal', 'supporting_A'} and proof['groups'][0]['passage_ids'] == [passage['id']]
    first = read_json(run/proof['parts']['proposal']['request'])['payload']
    assert parts.SPLIT_SENTENCE not in first['instructions'] and 'leave that supporting fact to the supporting parts' in first['instructions']
    item_id = first['schema']['properties']['requirements']['properties']['items']['items']['properties']['id']
    assert item_id['pattern'] == '^P[0-9]{2,3}$'
    second = read_json(run/proof['parts']['supporting_A']['request'])['payload']
    assert [r['id'] for r in second['proposal_inventory']['items']] == ['P01']
    assert second['inventory_part']['question_ids'] == ['MI001'] and second['inventory_part']['passage_ids'] == [passage['id']]
    # The merged inventory is reviewed like a single answer.
    review = prepare(run, 'requirements_review')['payload']
    assert [r['id'] for r in review['requirements']['items']] == ['P01', 'SA01']


def test_a_failed_part_is_the_only_one_called_again(tmp_path):
    run, passage, units, proposal = cited_run(tmp_path); calls = []
    with pytest.raises(parts.PartOutputError, match='supporting_A'):
        run_model(run, generator=generator(units, proposal, passage, calls, target='P99'), until='requirements', review_executor_id='test')
    stopped = read_json(run/'stopped.json')
    assert stopped['stage'] == 'requirements' and stopped['error_code'] == 'MODEL_REQUIREMENTS_PART_INVALID'
    assert 'requirements--supporting_A' in stopped['model_call']
    calls.clear()
    run_model(run, generator=generator(units, proposal, passage, calls), until='requirements', review_executor_id='test')
    assert calls == ['supporting_A']
    proof = read_json(run/parts.PROOF)
    assert proof['parts']['proposal']['execution'] == 'REUSED' and proof['parts']['supporting_A']['execution'] == 'GENERATED'


def test_no_executor_identity_means_no_reuse(tmp_path):
    run, passage, units, proposal = cited_run(tmp_path); calls = []
    with pytest.raises(parts.PartOutputError):
        run_model(run, generator=generator(units, proposal, passage, calls, target='P99'), until='requirements')
    calls.clear()
    run_model(run, generator=generator(units, proposal, passage, calls), until='requirements')
    assert calls == ['proposal', 'supporting_A']


def test_merged_parts_are_rechecked_at_acceptance(tmp_path):
    run, passage, units, proposal = cited_run(tmp_path); calls = []
    base = prepare(run, 'requirements'); make = generator(units, proposal, passage, calls)
    run_model(run, generator=make, until='requirements')
    accepted = copy.deepcopy(accepted_response(run, load_run(run)[1], 'requirements'))
    assert parts.produced_by_parts(run, base, accepted) and parts.verify_proof(run, base, accepted)
    edited = copy.deepcopy(accepted); edited['requirements']['items'][1]['statement'] = 'Edited after merge.'
    assert not parts.produced_by_parts(run, base, edited)
    with pytest.raises(ValueError, match='neither the merged parts'):
        parts.verify_proof(run, base, edited)
    # A changed part artifact is caught when the merged answer is accepted again.
    proof = read_json(run/parts.PROOF)
    response_path = run/proof['parts']['supporting_A']['response']
    changed = read_json(response_path); changed['requirements']['items'][0]['rationale'] = 'Changed on disk.'
    write_json(response_path, changed)
    engine.rerun_from(run, 'requirements')
    with pytest.raises(ValueError, match='artifact changed'):
        accept(run, 'requirements', accepted)


def test_a_whole_inventory_submitted_by_hand_is_still_accepted_on_its_own_checks(tmp_path):
    run, passage, units, proposal = cited_run(tmp_path)
    from test_supporting_scope import accept_requirements
    accept_requirements(run, passage, units, proposal)
    assert [r['id'] for r in accepted_response(run, load_run(run)[1], 'requirements')['requirements']['items']] == ['R001', 'R002']
    assert not (run/parts.PROOF).exists()


def test_binding_repair_of_the_merged_parts_is_linked_in_the_proof(tmp_path):
    run, passage, units, proposal = cited_run(tmp_path); calls = []
    run_model(run, generator=generator(units, proposal, passage, calls, binding='same animal (paraphrase)'),
              until='requirements', review_executor_id='test')
    assert calls == ['proposal', 'supporting_A', 'binding_repair']
    proof = read_json(run/parts.PROOF)
    assert proof['accepted_candidate']['binding_repair_result'].startswith('audit/binding_repairs/')
    inventory = accepted_response(run, load_run(run)[1], 'requirements')['requirements']
    assert inventory['items'][1]['science']['bindings'][0]['value'] == QUOTE


def test_supporting_groups_balance_questions_and_give_each_passage_one_owner():
    payload = {'sources': [{'id': f'X{i}', 'role': 'SUPPORTING_EVIDENCE', 'text': 'x' * size}
                           for i, size in enumerate([100, 100, 100, 100, 400, 50])] + [{'id': 'PROP', 'role': 'PRIMARY_SOURCE', 'text': 'p'}],
               'supporting_questions': [
                   {'question_id': 'MI001', 'cited_passage_ids': ['X0', 'X1']},
                   {'question_id': 'MI002', 'cited_passage_ids': ['X1', 'X2']},
                   {'question_id': 'MI003', 'cited_passage_ids': []},
                   {'question_id': 'MI004', 'cited_passage_ids': ['X3']},
                   {'question_id': 'MI005', 'cited_passage_ids': ['X4']}]}
    groups = parts.supporting_groups(payload, 3)
    assert [g['letter'] for g in groups] == ['A', 'B', 'C']
    owned = [i for g in groups for i in g['passage_ids']]
    assert sorted(owned) == ['X0', 'X1', 'X2', 'X3', 'X4', 'X5'] and len(owned) == len(set(owned))
    assert all('MI003' not in g['question_ids'] for g in groups)
    assert parts.supporting_groups({'sources': [], 'supporting_questions': []}, 3) == []


def test_runs_frozen_before_1_25_write_the_inventory_in_one_call(tmp_path, monkeypatch):
    earlier = before_1_31()
    next(r for r in earlier['rules'] if r['id'] == 'CC002')['host_requirement'].pop('requirements_parts')
    monkeypatch.setattr(engine, 'load_rules', lambda: copy.deepcopy(earlier))
    run, passage, units, proposal = cited_run(tmp_path); calls = []
    def whole(request, model=None):
        calls.append(request['payload'].get('inventory_part'))
        inventory = demo.fixture_requirements({'/objective': 'Study animal PK.'}, units, proposal[0]['source_id'])
        return {'request_sha256': request['request_sha256'], 'requirements': inventory}
    run_model(run, generator=whole, until='requirements')
    assert calls == [None] and not (run/parts.PROOF).exists()


def test_a_requested_rerun_calls_every_part_again(tmp_path):
    run, passage, units, proposal = cited_run(tmp_path); calls = []
    make = generator(units, proposal, passage, calls)
    run_model(run, generator=make, until='requirements', review_executor_id='test')
    engine.rerun_from(run, 'requirements'); calls.clear()
    run_model(run, generator=make, until='requirements', review_executor_id='test')
    assert calls == []  # Same request and executor: both validated parts are reused.
    engine.rerun_from(run, 'requirements')
    run_model(run, generator=make, until='requirements', review_executor_id='test', fresh=('requirements',))
    assert calls == ['proposal', 'supporting_A']


def format_repairing(make, calls, keep_id=True):
    """The supporting part writes one binding with a field outside the allowed list; the repair call fixes it."""
    def generate(request, model=None):
        p = request['payload']
        if p['stage'] == 'schema_repair':
            calls.append('schema_repair')
            task = p['tasks'][0]; record = copy.deepcopy(task['record'])
            record['science']['bindings'][0]['field'] = 'experimental_unit'
            if not keep_id: record['id'] = 'SA99'
            return {'request_sha256': request['request_sha256'],
                    'repairs': [{'collection': task['collection'], 'index': task['index'], 'record': record}]}
        response = make(request)
        if p.get('inventory_part', {}).get('part') == 'supporting_A':
            response['requirements']['items'][0]['science']['bindings'] = [
                {'field': 'experimental unit', 'value': QUOTE, 'component_ids': ['C1']}]
        return response
    return generate


def test_a_malformed_record_is_repaired_without_rewriting_the_part(tmp_path):
    from ctxcomp.schema_repair import lenient
    run, passage, units, proposal = cited_run(tmp_path); calls = []
    base = prepare(run, 'requirements')
    strict = parts.supporting_request(base, parts.supporting_groups(base['payload'], 3)[0],
                                      parts.supporting_groups(base['payload'], 3), {'items': [], 'potential_questions': []})['payload']['schema']
    relaxed = lenient(strict)
    records = relaxed['properties']['requirements']['properties']
    assert 'enum' not in str(records) and "'additionalProperties': False" not in str(records) and 'enum' in str(strict)
    assert relaxed['additionalProperties'] is False  # Outside the records no repair applies, so the CLI stays strict.
    from ctxcomp import requirements_revision as revision
    patch = lenient(revision.patch_schema(base['payload']['schema']))
    assert patch['properties']['changes']['items']['properties']['action']['enum'] == ['REPLACE', 'ADD', 'REMOVE']
    run_model(run, generator=format_repairing(generator(units, proposal, passage, calls), calls), until='requirements')
    assert calls == ['proposal', 'supporting_A', 'schema_repair']
    inventory = accepted_response(run, load_run(run)[1], 'requirements')['requirements']
    assert inventory['items'][1]['science']['bindings'][0]['field'] == 'experimental_unit'
    proof = read_json(run/parts.PROOF)
    receipt = proof['parts']['supporting_A']
    assert read_json(run/receipt['schema_repair'])['status'] == 'FORMAT_REPAIRED_AWAITING_CHECKS'
    raw = read_json(run/receipt['response'].replace('.response.json', '.model_response.json'))
    assert raw['requirements']['items'][0]['science']['bindings'][0]['field'] == 'experimental unit'


def test_a_format_repair_that_changes_an_id_stops_the_run(tmp_path):
    run, passage, units, proposal = cited_run(tmp_path); calls = []
    with pytest.raises(ValueError, match='changed the ID'):
        run_model(run, generator=format_repairing(generator(units, proposal, passage, calls), calls, keep_id=False), until='requirements')
    stopped = read_json(run/'stopped.json')
    assert stopped['error_code'] == 'MODEL_SCHEMA_REPAIR_FAILED' and 'schema_repair' in stopped['model_call']


def test_runs_frozen_before_1_25_get_no_format_repair(tmp_path, monkeypatch):
    earlier = before_1_31()
    next(r for r in earlier['rules'] if r['id'] == 'CC002')['host_requirement'].pop('schema_repair')
    monkeypatch.setattr(engine, 'load_rules', lambda: copy.deepcopy(earlier))
    run, passage, units, proposal = cited_run(tmp_path); calls = []
    with pytest.raises(parts.PartOutputError, match='experimental unit'):
        run_model(run, generator=format_repairing(generator(units, proposal, passage, calls), calls), until='requirements')
    assert 'schema_repair' not in calls
