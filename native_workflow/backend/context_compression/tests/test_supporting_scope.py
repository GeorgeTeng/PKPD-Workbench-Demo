"""CC002 (compression rules 1.20.0-1.22.0): per-unit verdicts cover the proposal; supporting passages are
checked where cited. Authored verdicts exercise the contracts only, not model accuracy."""
import copy
import pytest

from ctxcomp.engine import prepare, accept
from ctxcomp.io import read_json, leaves
from ctxcomp.rules import load_rules
from ctxcomp import split_review
from test_retention import demo
from test_runtime_rules import evidence_run

QUOTE = 'Repeated samples use the same animal ID.'


def cited_run(tmp_path):
    """A material question answered by one cited supporting passage; CONFLICT keeps it a warning."""
    run, q, req = evidence_run(tmp_path)
    passage = next(p for p in req['payload']['passages'] if QUOTE in p['text'])
    accept(run, 'attachment_evidence', {'request_sha256': req['request_sha256'], 'answers': [
        {'question_id': q['id'], 'status': 'CONFLICT', 'statement': 'The supporting file states the animal identity.',
         'reason': 'Authored test.', 'citations': [{'passage_id': passage['id'], 'quote': QUOTE}]}]})
    payload = prepare(run, 'requirements')['payload']
    scope = payload['compression_scope']['source_ids']
    proposal = [u for u in payload['source_units'] if u['source_id'] in scope]
    return run, passage, payload['source_units'], proposal


def accept_requirements(run, passage, units, proposal):
    """R001 cites the proposal; R002 cites only the supporting passage."""
    requirements = demo.fixture_requirements({'/objective': 'Study animal PK.'}, units, proposal[0]['source_id'])
    support = demo.fixture_requirements({'/data/available/0': QUOTE}, units, passage['id'])['items'][0]
    requirements['items'].append({**support, 'id': 'R002'})
    accept(run, 'requirements', {'request_sha256': prepare(run, 'requirements')['request_sha256'],
                                 'requirements': requirements})
    return requirements


def test_models_get_a_search_summary_while_the_audit_keeps_the_full_log(tmp_path):
    run, passage, units, proposal = cited_run(tmp_path)
    payload = prepare(run, 'requirements')['payload']
    assert payload['supporting_questions'] == [{'question_id': 'MI001', 'field': 'sampling identity',
        'question': 'Are repeated samples from one animal?', 'importance': 'MATERIAL', 'needed_at': 'pk',
        'status': 'CONFLICT', 'cited_passage_ids': [passage['id']], 'cited_proposal_ids': []}]
    warning = payload['missing_information_warnings'][0]
    full = read_json(run/'audit/missing_information_review.json')['warnings'][0]
    assert {k: v for k, v in warning.items() if k != 'search'} == {k: v for k, v in full.items() if k != 'search'}
    assert full['search']['files'][0]['locations'] and 'locations' not in warning['search']['files'][0]
    assert warning['search']['files'][0]['matched_locations'] == len(full['search']['files'][0]['locations'])
    assert warning['search']['matched_passages'] == len(full['search']['passage_ids'])
    assert warning['search']['supplied_passage_ids'] == [passage['id']]
    assert warning['search']['full_log'] == 'audit/missing_information_review.json'


def test_requirements_review_gives_unit_verdicts_for_the_proposal_only(tmp_path):
    run, passage, units, proposal = cited_run(tmp_path)
    assert len(proposal) < len(units)
    requirements = accept_requirements(run, passage, units, proposal)
    request = prepare(run, 'requirements_review')
    assert request['payload']['review_source_unit_ids'] == [u['id'] for u in proposal]
    review = demo.fixture_requirements_review(requirements, proposal)
    # R002 is still reviewed as an item; its supporting unit needs no record of its own.
    assert [r['requirement_id'] for r in review['items']] == ['R001', 'R002']
    assert all('R002' not in r['requirement_ids'] for r in review['source_units'])
    clash = copy.deepcopy(review); clash['source_units'].append({**review['source_units'][0], 'verdict': 'ALTERED'})
    with pytest.raises(ValueError, match='Source-unit review'):
        accept(run, 'requirements_review', {'request_sha256': request['request_sha256'], 'review': clash})
    # Records for units outside the proposal are set aside (1.30.0), not checked.
    every = demo.fixture_requirements_review(requirements, units)
    accept(run, 'requirements_review', {'request_sha256': request['request_sha256'], 'review': every})
    from ctxcomp.engine import load_run, accepted_response
    accepted = accepted_response(run, load_run(run)[1], 'requirements_review')['review']
    assert [r['unit_id'] for r in accepted['source_units']] == [u['id'] for u in proposal]
    extra = [u['id'] for u in units if u not in proposal]
    assert [e['id'] for e in read_json(run/'audit/unconfirmed_evidence.json')['review_records']] == extra
    assert all(any(i in note for note in accepted['limitations']) for i in extra)


def test_runs_frozen_before_1_30_stop_on_a_unit_record_outside_the_request(tmp_path, monkeypatch):
    from rule_versions import before_1_30, freeze
    freeze(monkeypatch, before_1_30())
    run, passage, units, proposal = cited_run(tmp_path)
    requirements = accept_requirements(run, passage, units, proposal)
    request = prepare(run, 'requirements_review')
    with pytest.raises(ValueError, match='Source-unit review'):
        accept(run, 'requirements_review', {'request_sha256': request['request_sha256'],
                                            'review': demo.fixture_requirements_review(requirements, units)})


def context_review_base(tmp_path):
    """cited_run accepted through context; returns the context_review request."""
    run, passage, units, proposal = cited_run(tmp_path)
    requirements = accept_requirements(run, passage, units, proposal)
    request = prepare(run, 'requirements_review')
    accept(run, 'requirements_review', {'request_sha256': request['request_sha256'],
                                        'review': demo.fixture_requirements_review(requirements, proposal)})
    context = {'version': '3.0', 'objective': 'Study animal PK.',
        'study': {k: 'NOT_FOUND' for k in ('drug', 'regimen', 'population', 'system', 'measurements', 'methods')},
        'data': {'available': [], 'required': []}, 'rules': [], 'checks': [],
        'uncertainties': ['PROPOSED [MI001] Confirm sampling identity before pk: random effects require experimental-unit identity.']}
    status = lambda p: 'EXPLICIT' if p == '/objective' else 'PROPOSED' if p.startswith('/uncertainties') else 'NOT_FOUND'
    evidence = [{'path': p, 'status': status(p), 'source_id': proposal[0]['source_id'] if p == '/objective' else '',
                 'quote': 'Study animal PK.' if p == '/objective' else '', 'reason': 'Authored test.'}
                for p, v in leaves(context) if p != '/version']
    accept(run, 'context', {'request_sha256': prepare(run, 'context')['request_sha256'],
                            'context': context, 'evidence': evidence})
    return units, proposal, requirements, prepare(run, 'context_review')


def test_completeness_branch_gives_unit_verdicts_for_the_proposal_only(tmp_path):
    units, proposal, requirements, base = context_review_base(tmp_path)
    assert base['payload']['review_source_unit_ids'] == [u['id'] for u in proposal]
    child = split_review.request_for(base, split_review.COMPLETE)
    assert child['payload']['review_source_unit_ids'] == [u['id'] for u in proposal]
    assert child['payload']['source_units'] == units  # Supporting passages stay available for cited checks.
    assert child['payload']['supporting_questions'] == base['payload']['supporting_questions']
    assert 'Cover every unit in review_source_unit_ids' in child['payload']['instructions']
    for branch in (split_review.FAITH, split_review.GLOBAL):
        assert 'review_source_unit_ids' not in split_review.request_for(base, branch, prior={})['payload']

    def response(unit_ids):
        review = {'decision': 'REVISE', 'reviewer': 'Authored test', 'review_type': 'ASSISTANT_INTERNAL_REVIEW',
            'critical_errors': [], 'limitations': ['Authored test labels only.'],
            'coverage': [{'requirement_id': r['id'], 'verdict': 'MISSING', 'reason': 'Authored test.',
                          'components': [{'component_id': c['id'], 'verdict': 'MISSING', 'targets': [],
                                          'reason': 'Authored test.'} for c in r['components']]}
                         for r in requirements['items']],
            'retention': [{'source_id': proposal[0]['source_id'], 'quote': 'Study animal PK.', 'verdict': 'PRESERVED',
                           'critical': True, 'reason': 'Authored test.'}],
            'source_units': [{'unit_id': i, 'verdict': 'PRESERVED', 'reason': 'Authored test.'} for i in unit_ids],
            'scientific_checks': [{'id': i, 'verdict': 'PRESERVED', 'reason': 'Authored test.'}
                                  for i in child['payload'].get('required_scientific_ids', [])]}
        return {'request_sha256': child['request_sha256'], 'review': review}

    with pytest.raises(ValueError, match='Source-unit completeness'):
        split_review.validate_branch(base, child, response([u['id'] for u in units]), split_review.COMPLETE)
    split_review.validate_branch(base, child, response([u['id'] for u in proposal]), split_review.COMPLETE)


def test_runs_frozen_with_earlier_rules_keep_every_unit_and_the_full_log(tmp_path, monkeypatch):
    from ctxcomp import engine
    earlier = copy.deepcopy(load_rules())
    next(r for r in earlier['rules'] if r['id'] == 'CC002').pop('host_requirement')
    monkeypatch.setattr(engine, 'load_rules', lambda: copy.deepcopy(earlier))
    run, passage, units, proposal = cited_run(tmp_path)
    payload = prepare(run, 'requirements')['payload']
    assert 'supporting_questions' not in payload
    assert payload['missing_information_warnings'] == read_json(run/'audit/missing_information_review.json')['warnings']
    requirements = accept_requirements(run, passage, units, proposal)
    request = prepare(run, 'requirements_review')
    assert 'review_source_unit_ids' not in request['payload']
    with pytest.raises(ValueError, match='Source-unit review'):
        accept(run, 'requirements_review', {'request_sha256': request['request_sha256'],
                                            'review': demo.fixture_requirements_review(requirements, proposal)})
    accept(run, 'requirements_review', {'request_sha256': request['request_sha256'],
                                        'review': demo.fixture_requirements_review(requirements, units)})


def test_supporting_questions_list_cited_proposal_passages_apart(tmp_path):
    """Compression rules 1.22.0: cited_passage_ids holds supporting passages only."""
    run, q, req = evidence_run(tmp_path)
    passage = next(p for p in req['payload']['passages'] if QUOTE in p['text'])
    proposal = req['payload']['proposal_sources'][0]
    accept(run, 'attachment_evidence', {'request_sha256': req['request_sha256'], 'answers': [
        {'question_id': q['id'], 'status': 'CONFLICT', 'statement': 'The proposal omits what the supporting file states.',
         'reason': 'Authored test.', 'citations': [{'passage_id': proposal['id'], 'quote': 'animal identity is not stated'},
                                                   {'passage_id': passage['id'], 'quote': QUOTE}]}]})
    question = prepare(run, 'requirements')['payload']['supporting_questions'][0]
    assert question['cited_passage_ids'] == [passage['id']]
    assert question['cited_proposal_ids'] == [proposal['id']]


def test_every_reviewer_learns_why_each_supporting_passage_was_supplied(tmp_path):
    units, proposal, requirements, base = context_review_base(tmp_path)
    assert base['payload']['context_review_mode'] == split_review.MODE_V3
    parts = split_review.faithfulness_parts(base)
    faith = [split_review.part_request(base, part)['payload'] for part in parts]
    complete, conflicts = (split_review.request_for(base, b, prior={})['payload']
                           for b in (split_review.COMPLETE, split_review.GLOBAL))
    for payload in faith + [complete, conflicts]:
        assert payload['supporting_questions'] == base['payload']['supporting_questions']
        assert 'It only explains why a passage was supplied' in payload['instructions']
    assert 'as a MISSING verdict on the affected' in complete['instructions']
    # parallel_v3: the parts are told the conflict review runs at the same time, not after them.
    assert all('checks all fields at the same time' in p['instructions'] and 'then checks' not in p['instructions']
               for p in faith)


def test_runs_frozen_with_rules_1_21_keep_their_review_requests(tmp_path, monkeypatch):
    from ctxcomp import engine
    earlier = copy.deepcopy(load_rules())
    next(r for r in earlier['rules'] if r['id'] == 'CC002')['host_requirement']['question_links'] = 'CITED_PASSAGES'
    next(r for r in earlier['rules'] if r['id'] == 'CC012').pop('host_requirement')
    monkeypatch.setattr(engine, 'load_rules', lambda: copy.deepcopy(earlier))
    units, proposal, requirements, base = context_review_base(tmp_path)
    assert 'cited_proposal_ids' not in base['payload']['supporting_questions'][0]
    faith = [split_review.part_request(base, part)['payload'] for part in split_review.faithfulness_parts(base)]
    complete, conflicts = (split_review.request_for(base, b, prior={})['payload']
                           for b in (split_review.COMPLETE, split_review.GLOBAL))
    assert all('supporting_questions' not in p for p in faith + [conflicts])
    assert complete['supporting_questions'] == base['payload']['supporting_questions']
    assert all('It only explains why' not in p['instructions'] for p in faith + [complete, conflicts])
    assert all('the global conflict review then checks all fields together.' in p['instructions'] for p in faith)


def test_requirements_review_is_given_each_units_links_including_potential_questions(tmp_path):
    run, passage, units, proposal = cited_run(tmp_path)
    requirements = accept_requirements(run, passage, units, proposal)
    request = prepare(run, 'requirements_review')
    review = demo.fixture_requirements_review(requirements, proposal)
    # The links the host checks are the ones the reviewer is given, unit by unit.
    assert request['payload']['review_source_unit_links'] == {r['unit_id']: sorted(r['requirement_ids'])
                                                              for r in review['source_units']}
    assert 'review_source_unit_links' in request['payload']['instructions']
    fields = request['payload']['schema']['properties']['review']['properties']['source_units']['items']['properties']
    assert 'review_source_unit_links' in fields['requirement_ids']['description']
    assert 'description' not in fields['unit_id'] and 'description' not in fields['reason']
    # A potential question citing a unit is one of its links, as the 2026-10-09 run's reviewer missed.
    from ctxcomp.retention import source_unit_links
    inventory = {'items': requirements['items'], 'potential_questions': [
        {'id': 'PQ001', 'source_refs': [{'unit_id': proposal[0]['id']}]}]}
    links = source_unit_links(inventory, [proposal[0]['id']])
    assert links[proposal[0]['id']] == set(request['payload']['review_source_unit_links'][proposal[0]['id']]) | {'PQ001'}



def test_host_fills_each_units_links_so_a_dropped_link_no_longer_stops_the_run(tmp_path):
    """Compression rules 1.25.0: the 2026-10-09 02:11 run stopped because the reviewer left out links."""
    run, passage, units, proposal = cited_run(tmp_path)
    requirements = accept_requirements(run, passage, units, proposal)
    request = prepare(run, 'requirements_review')
    assert 'Return requirement_ids as []' in request['payload']['instructions']
    review = demo.fixture_requirements_review(requirements, proposal)
    expected = {r['unit_id']: r['requirement_ids'] for r in review['source_units']}
    for record in review['source_units']:
        record['requirement_ids'] = []
    assert accept(run, 'requirements_review', {'request_sha256': request['request_sha256'], 'review': review})['status'] == 'ACCEPTED'
    from ctxcomp.engine import load_run, accepted_response
    accepted = accepted_response(run, load_run(run)[1], 'requirements_review')['review']
    assert {r['unit_id']: sorted(r['requirement_ids']) for r in accepted['source_units']} == \
        {k: sorted(v) for k, v in expected.items()}
    audit = read_json(run/'audit/requirements_review_links.json')
    assert [c['unit_id'] for c in audit['changed_units']] == [r['unit_id'] for r in review['source_units'] if expected[r['unit_id']]]
    # Unit coverage itself stays strict; see test_requirements_review_gives_unit_verdicts_for_the_proposal_only.


def test_runs_frozen_before_1_25_still_check_the_models_links(tmp_path, monkeypatch):
    from ctxcomp import engine
    earlier = copy.deepcopy(load_rules())
    next(r for r in earlier['rules'] if r['id'] == 'CC002')['host_requirement'].pop('unit_links')
    monkeypatch.setattr(engine, 'load_rules', lambda: copy.deepcopy(earlier))
    run, passage, units, proposal = cited_run(tmp_path)
    requirements = accept_requirements(run, passage, units, proposal)
    request = prepare(run, 'requirements_review')
    assert 'Return requirement_ids as []' not in request['payload']['instructions']
    review = demo.fixture_requirements_review(requirements, proposal)
    for record in review['source_units']:
        record['requirement_ids'] = []
    if any(demo.fixture_requirements_review(requirements, proposal)['source_units'][i]['requirement_ids']
           for i in range(len(review['source_units']))):
        with pytest.raises(ValueError, match='Source-to-requirement links'):
            accept(run, 'requirements_review', {'request_sha256': request['request_sha256'], 'review': review})
    assert not (run/'audit/requirements_review_links.json').exists()


def test_a_revise_review_with_host_filled_links_can_be_revised_in_the_same_run(tmp_path):
    """The model returns requirement_ids as [] and the host fills them, so the stop record points at the filled
    review that became the feedback; reopen_for_revision compares the two."""
    from ctxcomp import engine
    run, passage, units, proposal = cited_run(tmp_path)
    requirements = accept_requirements(run, passage, units, proposal)
    request = prepare(run, 'requirements_review')
    review = demo.fixture_requirements_review(requirements, proposal)
    review['decision'] = 'REVISE'
    review['items'][0].update(verdict='ALTERED', reason='Authored finding.')
    for record in review['source_units']:
        record['requirement_ids'] = []
    outcome = accept(run, 'requirements_review', {'request_sha256': request['request_sha256'], 'review': review})
    assert outcome == {'status': 'REVISE', 'stage': 'requirements_review',
                       'reason': 'Semantic review requires attention; no handoff published'}
    stopped = read_json(run/'stopped.json')
    assert stopped['response'].startswith('reviews/requirements_review.') and stopped['submission'].startswith('submissions/')
    assert read_json(run/stopped['response'])['review'] == read_json(run/'feedback/requirements.json')
    assert read_json(run/stopped['submission'])['review'] == review
    assert engine.reopen_for_revision(run, guidance='Authored guidance.')['stage'] == 'requirements'
