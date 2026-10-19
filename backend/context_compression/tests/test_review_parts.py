"""Compression rules 1.31.0 (CC002 review_parts): the requirements review in parts that run at the same time."""
import copy
import threading
import pytest

from ctxcomp import review_parts
from ctxcomp.engine import prepare, load_run, accepted_response
from ctxcomp.io import read_json
from ctxcomp.providers import run_model
from test_retention import reference_run, replay_until
from rule_versions import before_1_31, freeze


def saved_review(reference_run):
    return read_json(reference_run/'saved_responses/requirements_review.json')['review']


def answering(full, calls, barrier=None, edit=None):
    """Each part answers with the saved review's records for its own IDs."""
    def generate(request, model=None):
        p = request['payload']; part = p.get('review_part')
        assert part, 'the review should run in parts'
        calls.append(part['part'])
        if barrier: barrier.wait(timeout=10)
        own = set(part['item_ids']); units = set(p['review_source_unit_ids'])
        review = {**copy.deepcopy(full), 'reviewer': f'part {part["part"]}',
                  'items': [r for r in full['items'] if r['requirement_id'] in own],
                  'source_units': [r for r in full['source_units'] if r['unit_id'] in units]}
        if edit: edit(part['part'], review)
        return {'request_sha256': request['request_sha256'], 'review': review}
    return generate


def test_parts_split_units_and_ids_once_and_run_together(tmp_path, reference_run):
    run = tmp_path/'run'; replay_until(run, reference_run, 'requirements')
    base = prepare(run, 'requirements_review'); payload = base['payload']
    assert review_parts.enabled(payload)
    parts = review_parts.plan(payload)
    from ctxcomp.scientific import item_ids
    assert sorted(i for p in parts for i in p['item_ids']) == sorted(item_ids(payload['requirements']))
    assert [u for p in parts for u in p['unit_ids']] == payload['review_source_unit_ids']
    assert 1 < len(parts) <= 3 and all(p['item_ids'] and p['unit_ids'] for p in parts)
    first = review_parts.part_request(base, parts[0], parts)['payload']
    assert first['review_source_unit_ids'] == parts[0]['unit_ids'] and set(first['review_source_unit_links']) == set(parts[0]['unit_ids'])
    assert first['requirements'] == payload['requirements'] and 'You write part 1' in first['instructions']
    calls = []
    full = saved_review(reference_run)
    result = run_model(run, generator=answering(full, calls, threading.Barrier(len(parts))), until='requirements_review')
    assert result == {'status': 'STAGE_READY', 'stage': 'requirements_review'} and sorted(calls) == list(range(1, len(parts) + 1))
    accepted = accepted_response(run, load_run(run)[1], 'requirements_review')['review']
    assert accepted['decision'] == full['decision'] and accepted['reviewer'].startswith(f'Requirements review in {len(parts)} parts')
    assert [r['requirement_id'] for r in accepted['items']] == item_ids(payload['requirements'])
    assert [r['unit_id'] for r in accepted['source_units']] == payload['review_source_unit_ids']


def test_a_record_for_another_parts_id_goes_to_limitations_and_a_defect_there_means_revise(tmp_path, reference_run):
    run = tmp_path/'run'; replay_until(run, reference_run, 'requirements')
    base = prepare(run, 'requirements_review'); parts = review_parts.plan(base['payload'])
    full = saved_review(reference_run)
    other = parts[1]['item_ids'][0]
    def edit(part, review):
        if part == 1:
            review['items'].append({'requirement_id': other, 'verdict': 'ALTERED', 'reason': 'Seen from part 1.'})
    responses = [answering(full, [], edit=edit)(review_parts.part_request(base, p, parts)) for p in parts]
    merged = review_parts.merge(base, parts, responses)['review']
    assert [r['requirement_id'] for r in merged['items']].count(other) == 1
    assert any(other in n and 'Seen from part 1.' in n for n in merged['limitations'])
    assert merged['decision'] == ('REVISE' if full['decision'] == 'PASS' else full['decision'])


def test_a_small_review_stays_one_call(tmp_path, reference_run):
    from test_supporting_scope import cited_run, accept_requirements
    run, passage, units, proposal = cited_run(tmp_path)
    accept_requirements(run, passage, units, proposal)
    assert len(proposal) == 1 and not review_parts.enabled(prepare(run, 'requirements_review')['payload'])


def test_runs_frozen_before_1_31_review_in_one_call(tmp_path, reference_run, monkeypatch):
    freeze(monkeypatch, before_1_31())
    run = tmp_path/'run'; replay_until(run, reference_run, 'requirements')
    assert not review_parts.enabled(prepare(run, 'requirements_review')['payload'])
