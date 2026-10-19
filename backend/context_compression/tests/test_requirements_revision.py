"""Compression rules 1.26.0 (CC002 revision): after requirements_review asks for changes, the redo is one patch
of the reviewed inventory. Authored inventories and reviews exercise the host contract only, not extraction or
review quality."""
import copy
import pytest

from ctxcomp import engine, requirements_parts as parts, requirements_revision as revision
from ctxcomp.engine import accept, prepare, load_run, accepted_response
from ctxcomp.io import read_json, write_json
from ctxcomp.providers import run_model
from ctxcomp.rules import load_rules
from test_retention import demo
from test_supporting_scope import cited_run, QUOTE
from test_requirements_parts import generator as parts_generator
from rule_versions import rules_1_30, before_1_31

pytestmark = pytest.mark.usefixtures('rules_1_30')


def reviewed_run(tmp_path, flagged='SA01'):
    """An inventory written in parts (P01, SA01) and a review that asks to revise one item."""
    run, passage, units, proposal = cited_run(tmp_path)
    run_model(run, generator=parts_generator(units, proposal, passage, []), until='requirements', review_executor_id='test')
    inventory = accepted_response(run, load_run(run)[1], 'requirements')['requirements']
    request = prepare(run, 'requirements_review')
    review = demo.fixture_requirements_review(inventory, proposal)
    review['decision'] = 'REVISE'
    for record in review['items']:
        if record['requirement_id'] == flagged:
            record.update(verdict='ALTERED', reason='The statement drops the printed unit.')
    outcome = accept(run, 'requirements_review', {'request_sha256': request['request_sha256'], 'review': review})
    assert outcome['status'] == 'REVISE'
    return run, passage, units, proposal, inventory


def patcher(calls, replace=('SA01',), add=(), remove=(), binding=None):
    def generate(request, model=None):
        p = request['payload']
        if p['stage'] == 'binding_repair':
            calls.append('binding_repair'); task = p['tasks'][0]
            return {'request_sha256': request['request_sha256'], 'method_ref_repairs': [], 'repairs': [
                {'item_id': task['item_id'], 'binding_index': task['binding_index'], 'status': 'CORRECTED',
                 'replacements': [{'field': task['field'], 'component_ids': task['component_ids'], 'value': QUOTE}],
                 'reason': 'Authored exact excerpt.'}]}
        assert 'revision_patch' in p, 'only the patch call is expected'
        calls.append('patch')
        reviewed = {r['id']: r for r in p['reviewed_inventory']['items']}
        records = []
        for item_id in replace:
            record = copy.deepcopy(reviewed[item_id]); record['rationale'] = 'Revised after review.'
            if binding: record['science']['bindings'] = [{'field': 'experimental_unit', 'value': binding, 'component_ids': ['C1']}]
            records.append(record)
        for item_id in add:
            record = copy.deepcopy(reviewed['SA01']); record['id'] = item_id; record['science']['relations'] = []
            records.append(record)
        return {'request_sha256': request['request_sha256'], 'requirements': {'items': records, 'potential_questions': []},
                'remove_item_ids': list(remove), 'remove_question_ids': [],
                'changes': [{'id': i, 'action': 'REPLACE', 'finding': 'Review item verdict.'} for i in replace]}
    return generate


def test_a_revise_review_is_answered_with_one_patch_of_the_flagged_records(tmp_path):
    run, passage, units, proposal, reviewed = reviewed_run(tmp_path)
    assert read_json(run/'feedback'/revision.REVIEWED)['response']['requirements'] == reviewed
    engine.reopen_for_revision(run, guidance='Keep the printed unit.', submitted_by='test')
    base = prepare(run, 'requirements')
    assert revision.enabled(base['payload']) and base['payload']['reviewed_inventory'] == reviewed
    calls = []
    result = run_model(run, generator=patcher(calls), until='requirements', review_executor_id='test')
    assert result == {'status': 'STAGE_READY', 'stage': 'requirements'}
    assert calls == ['patch']
    inventory = accepted_response(run, load_run(run)[1], 'requirements')['requirements']
    assert [r['id'] for r in inventory['items']] == ['P01', 'SA01']
    assert inventory['items'][0] == reviewed['items'][0]
    assert inventory['items'][1]['rationale'] == 'Revised after review.'
    proof = read_json(run/revision.PROOF)
    assert proof['changed_ids'] == ['SA01'] and proof['review_sha256'] and proof['accepted_candidate'] is None
    patch = read_json(run/proof['request'])['payload']
    assert patch['revision_patch']['must_change'] == ['SA01'] and patch['revision_guidance']['guidance'] == 'Keep the printed unit.'
    assert 'reviewed_inventory' in patch and patch['schema']['properties']['requirements']['properties']['items']['minItems'] == 0
    # The patched inventory is reviewed again in full.
    assert [r['id'] for r in prepare(run, 'requirements_review')['payload']['requirements']['items']] == ['P01', 'SA01']


def test_the_patched_inventory_is_rechecked_at_acceptance(tmp_path):
    run, *_ = reviewed_run(tmp_path)
    engine.reopen_for_revision(run)
    base = prepare(run, 'requirements')
    run_model(run, generator=patcher([]), until='requirements')
    accepted = copy.deepcopy(accepted_response(run, load_run(run)[1], 'requirements'))
    assert revision.produced_by_patch(run, base, accepted) and revision.verify_proof(run, base, accepted)
    assert not parts.produced_by_parts(run, base, accepted)
    edited = copy.deepcopy(accepted); edited['requirements']['items'][0]['statement'] = 'Edited after the patch.'
    assert not revision.produced_by_patch(run, base, edited)
    with pytest.raises(ValueError, match='neither the patched inventory'):
        revision.verify_proof(run, base, edited)
    proof = read_json(run/revision.PROOF)
    changed = read_json(run/proof['response']); changed['requirements']['items'][0]['rationale'] = 'Changed on disk.'
    write_json(run/proof['response'], changed)
    state = load_run(run)[1]; state['accepted'].pop('requirements'); write_json(run/'state.json', state)
    with pytest.raises(ValueError, match='artifact changed'):
        accept(run, 'requirements', accepted)


def test_a_patch_that_leaves_a_flagged_item_unchanged_stops_and_is_asked_again(tmp_path):
    run, *_ = reviewed_run(tmp_path)
    engine.reopen_for_revision(run)
    calls = []
    with pytest.raises(revision.RevisionPatchError, match='SA01'):
        run_model(run, generator=patcher(calls, replace=('P01',)), until='requirements', review_executor_id='test')
    stopped = read_json(run/'stopped.json')
    assert stopped['stage'] == 'requirements' and stopped['error_code'] == 'MODEL_REQUIREMENTS_REVISION_INVALID'
    assert 'requirements--patch' in stopped['model_call']
    assert 'requirements' not in load_run(run)[1]['accepted']
    calls.clear()
    run_model(run, generator=patcher(calls), until='requirements', review_executor_id='test')
    assert calls == ['patch']


def test_a_patch_may_split_and_remove_records(tmp_path):
    run, *_ = reviewed_run(tmp_path)
    engine.reopen_for_revision(run)
    run_model(run, generator=patcher([], replace=(), add=('SA02', 'SA03'), remove=('SA01',)), until='requirements')
    inventory = accepted_response(run, load_run(run)[1], 'requirements')['requirements']
    assert [r['id'] for r in inventory['items']] == ['P01', 'SA02', 'SA03']


def test_patch_contract():
    reviewed = {'version': '1.1', 'potential_questions': [{'id': 'PQ01'}], 'items': [{'id': 'P01'}, {'id': 'SA01'}]}
    payload = {'reviewed_inventory': reviewed, 'previous_feedback': {'items': [
        {'requirement_id': 'SA01', 'verdict': 'ALTERED'}, {'requirement_id': 'P01', 'verdict': 'UNRESOLVED'},
        {'requirement_id': 'X9', 'verdict': 'MISSING'}]}}
    assert revision.must_change(payload) == ['SA01']
    base = {'request_sha256': 'b', 'payload': payload}
    request = {'request_sha256': 'r', 'payload': {'schema': {'type': 'object'}, 'revision_patch': {'must_change': ['SA01']}}}
    def patch(items=(), remove=(), questions=(), remove_questions=()):
        return {'request_sha256': 'r', 'requirements': {'items': list(items), 'potential_questions': list(questions)},
                'remove_item_ids': list(remove), 'remove_question_ids': list(remove_questions), 'changes': []}
    merged = revision.apply(base, request, patch(items=[{'id': 'SA01', 'x': 1}, {'id': 'N01'}], questions=[{'id': 'PQ02'}]))
    assert merged == {'request_sha256': 'b', 'requirements': {'version': '1.1', 'items': [{'id': 'P01'}, {'id': 'SA01', 'x': 1}, {'id': 'N01'}],
                                                            'potential_questions': [{'id': 'PQ01'}, {'id': 'PQ02'}]}}
    assert reviewed['items'][1] == {'id': 'SA01'}
    for bad, message in [(patch(), 'changes nothing'), (patch(items=[{'id': 'P01'}]), 'changes nothing'),
                         (patch(remove=['SA01', 'Q7']), 'does not have: Q7'),
                         (patch(items=[{'id': 'SA01'}], remove=['SA01']), 'both returns and removes'),
                         (patch(items=[{'id': 'SA01'}, {'id': 'P01', 'x': 2}]), 'unchanged: SA01'),
                         (patch(items=[{'id': 'SA01'}, {'id': 'SA01'}]), 'twice')]:
        with pytest.raises(revision.RevisionPatchError, match=message):
            revision.apply(base, request, bad)


def test_binding_repair_of_the_patched_inventory_is_linked_in_the_proof(tmp_path):
    run, *_ = reviewed_run(tmp_path)
    engine.reopen_for_revision(run)
    calls = []
    run_model(run, generator=patcher(calls, binding='same animal (paraphrase)'), until='requirements', review_executor_id='test')
    assert calls == ['patch', 'binding_repair']
    proof = read_json(run/revision.PROOF)
    assert proof['accepted_candidate']['binding_repair_result'].startswith('audit/binding_repairs/')
    inventory = accepted_response(run, load_run(run)[1], 'requirements')['requirements']
    assert inventory['items'][1]['science']['bindings'][0]['value'] == QUOTE


def test_a_whole_inventory_submitted_by_hand_after_a_review_is_accepted_on_its_own_checks(tmp_path):
    run, passage, units, proposal, reviewed = reviewed_run(tmp_path)
    engine.reopen_for_revision(run)
    base = prepare(run, 'requirements')
    assert accept(run, 'requirements', {'request_sha256': base['request_sha256'], 'requirements': reviewed})['status'] == 'ACCEPTED'
    assert not (run/revision.PROOF).exists()


def test_runs_frozen_before_1_26_redo_the_whole_inventory(tmp_path, monkeypatch):
    earlier = before_1_31()
    next(r for r in earlier['rules'] if r['id'] == 'CC002')['host_requirement'].pop('revision')
    monkeypatch.setattr(engine, 'load_rules', lambda: copy.deepcopy(earlier))
    run, passage, units, proposal, reviewed = reviewed_run(tmp_path)
    assert not (run/'feedback'/revision.REVIEWED).exists()
    engine.reopen_for_revision(run)
    base = prepare(run, 'requirements')
    assert 'reviewed_inventory' not in base['payload'] and 'previous_feedback' in base['payload']
    calls = []
    run_model(run, generator=parts_generator(units, proposal, passage, calls), until='requirements', review_executor_id='test')
    assert calls == ['proposal', 'supporting_A']


def test_a_stale_reviewed_inventory_is_not_patched(tmp_path):
    run, *_ = reviewed_run(tmp_path)
    engine.reopen_for_revision(run)
    record = read_json(run/'feedback'/revision.REVIEWED); record['review_sha256'] = 'other review'
    write_json(run/'feedback'/revision.REVIEWED, record)
    assert 'reviewed_inventory' not in prepare(run, 'requirements')['payload']


def test_a_rerun_after_a_passed_revision_starts_over_instead_of_patching_the_older_inventory(tmp_path):
    run, passage, units, proposal, reviewed = reviewed_run(tmp_path)
    engine.reopen_for_revision(run)
    run_model(run, generator=patcher([]), until='requirements')
    revised = accepted_response(run, load_run(run)[1], 'requirements')['requirements']
    request = prepare(run, 'requirements_review')
    review = demo.fixture_requirements_review(revised, proposal)
    assert accept(run, 'requirements_review', {'request_sha256': request['request_sha256'], 'review': review})['status'] == 'ACCEPTED'
    engine.rerun_from(run, 'context')  # Later stages leave the reviewed inventory alone.
    assert 'superseded_by' not in read_json(run/'feedback'/revision.REVIEWED)
    engine.rerun_from(run, 'requirements')
    assert read_json(run/'feedback'/revision.REVIEWED)['superseded_by']['rerun_from'] == 'requirements'
    payload = prepare(run, 'requirements')['payload']
    assert 'reviewed_inventory' not in payload and not revision.enabled(payload)
    calls = []
    run_model(run, generator=parts_generator(units, proposal, passage, calls), until='requirements', review_executor_id='test')
    assert calls == ['proposal', 'supporting_A']
    # A later review that asks for changes keeps a fresh record for the next patch.
    request = prepare(run, 'requirements_review')
    inventory = accepted_response(run, load_run(run)[1], 'requirements')['requirements']
    review = demo.fixture_requirements_review(inventory, proposal); review['decision'] = 'REVISE'
    review['items'][0].update(verdict='ALTERED', reason='Authored finding.')
    assert accept(run, 'requirements_review', {'request_sha256': request['request_sha256'], 'review': review})['status'] == 'REVISE'
    engine.reopen_for_revision(run)
    assert prepare(run, 'requirements')['payload']['reviewed_inventory'] == inventory
