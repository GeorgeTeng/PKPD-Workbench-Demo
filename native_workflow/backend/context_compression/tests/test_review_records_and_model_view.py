"""Compression rules 1.30.0: unknown review records are set aside, and the model reads each source's text once."""
import copy
import pytest

from ctxcomp import model_view
from ctxcomp.engine import prepare, accept, load_run, accepted_response
from ctxcomp.io import read_json, digest
from test_retention import demo
from test_supporting_scope import cited_run, accept_requirements
from rule_versions import before_1_30, freeze, cc002


def review_request(tmp_path):
    run, passage, units, proposal = cited_run(tmp_path)
    requirements = accept_requirements(run, passage, units, proposal)
    return run, prepare(run, 'requirements_review'), demo.fixture_requirements_review(requirements, proposal)


def submit(run, request, review):
    return accept(run, 'requirements_review', {'request_sha256': request['request_sha256'], 'review': review})


def test_a_preserved_item_record_under_an_unknown_id_goes_to_limitations(tmp_path):
    run, request, review = review_request(tmp_path)
    assert 'exactly one record for each inventory item' in request['payload']['instructions']
    review['items'].append({**review['items'][0], 'requirement_id': 'SA34_DUP_NOTE', 'reason': 'R001 repeats R002.'})
    submit(run, request, review)
    accepted = accepted_response(run, load_run(run)[1], 'requirements_review')['review']
    assert [r['requirement_id'] for r in accepted['items']] == ['R001', 'R002']
    assert any('SA34_DUP_NOTE' in n and 'R001 repeats R002.' in n for n in accepted['limitations'])
    entry, = read_json(run/'audit/unconfirmed_evidence.json')['review_records']
    assert entry['action'] == 'MOVED_TO_LIMITATIONS' and entry['request_sha256'] == request['request_sha256']


def test_exact_repeats_merge_and_a_missing_id_still_stops(tmp_path):
    run, request, review = review_request(tmp_path)
    missing = copy.deepcopy(review); missing['items'] = missing['items'][:1]
    with pytest.raises(ValueError, match='Requirement review'):
        submit(run, request, missing)
    review['items'].append({**review['items'][0], 'reason': 'Seen twice.'})
    submit(run, request, review)
    accepted = accepted_response(run, load_run(run)[1], 'requirements_review')['review']
    assert [r['requirement_id'] for r in accepted['items']] == ['R001', 'R002']
    assert accepted['items'][0]['reason'].endswith('Seen twice.')
    assert read_json(run/'audit/unconfirmed_evidence.json')['review_records'][0]['action'] == 'MERGED_REPEAT'


def test_pass_with_a_defect_outside_the_request_still_stops(tmp_path):
    run, request, review = review_request(tmp_path)
    assert review['decision'] == 'PASS'
    review['items'].append({**review['items'][0], 'requirement_id': 'X1', 'verdict': 'MISSING'})
    with pytest.raises(ValueError, match='PASS contradicts a review record outside'):
        submit(run, request, review)


def test_runs_frozen_before_1_30_stop_on_an_unknown_item_and_see_the_full_request(tmp_path, monkeypatch):
    freeze(monkeypatch, before_1_30())
    run, request, review = review_request(tmp_path)
    assert 'exactly one record for each inventory item' not in request['payload']['instructions']
    assert model_view.view(request) == request
    review['items'].append({**review['items'][0], 'requirement_id': 'SA34_DUP_NOTE'})
    with pytest.raises(ValueError, match='Requirement review'):
        submit(run, request, review)


def test_the_model_reads_each_source_text_once_while_the_request_and_hash_stay_whole(tmp_path):
    run, request, _ = review_request(tmp_path)
    payload = request['payload']
    assert request['request_sha256'] == digest(payload)
    sent = model_view.view(request)
    compact = sent['payload']
    assert sent['request_sha256'] == request['request_sha256'] and request['payload'] is payload
    assert 'requirements_evidence_audit' not in compact and 'source_registry' not in compact
    assert all('text_sha256' not in u for u in compact['source_units'])
    assert [u['text'] for u in compact['source_units']] == [u['text'] for u in payload['source_units']]
    assert all('text' not in s and 'original_sha256' not in s for s in compact['sources'])
    assert 'given once, in source_units' in payload['instructions']


def test_a_source_whose_units_do_not_rebuild_it_keeps_its_text():
    payload = {'processing_rules': cc002(model_payload='COMPACT'),
               'sources': [{'id': 'S1', 'text': 'ab', 'original_sha256': 'x'}, {'id': 'S2', 'text': 'cd'}],
               'source_units': [{'id': 'S1_U0001', 'source_id': 'S1', 'start_char': 0, 'end_char': 2, 'text': 'ab',
                                 'text_sha256': 'y'},
                                {'id': 'S2_U0001', 'source_id': 'S2', 'start_char': 0, 'end_char': 1, 'text': 'c'}],
               'source_registry': [{'id': 'S1'}]}
    compact = model_view.view({'payload': payload})['payload']
    assert compact['sources'] == [{'id': 'S1'}, {'id': 'S2', 'text': 'cd'}]
    assert 'source_registry' not in compact and payload['source_registry']
