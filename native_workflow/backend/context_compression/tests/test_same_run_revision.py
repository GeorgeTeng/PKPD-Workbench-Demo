"""Redoing a reviewed stage in the same run: other accepted stages are reused and a person's guidance reaches
only the redone stage while it answers the current review. Authored responses exercise contracts, not model accuracy."""
import threading
import pytest
from ctxcomp.engine import init_run, load_run, make_request, reopen_for_revision
from ctxcomp.io import read_json, write_json, digest
from ctxcomp.providers import run_model
from test_retention import reference_run, EXAMPLES
from rule_versions import before_1_29, freeze


@pytest.fixture(autouse=True)
def manual_revisions(monkeypatch):
    """These runs stop at a REVISE for a person to reopen: rules before 1.29.0, which revise once automatically."""
    freeze(monkeypatch, before_1_29())


def model_for(reference_run, calls, review=None):
    """review edits each requirements review once; a review in parts (1.31.0) is one call in calls, and each part
    answers with that review's records for its own IDs."""
    reviews = {}; lock = threading.Lock()
    def answer(request, model=None):
        stage = request['payload']['stage']; part = request['payload'].get('review_part')
        if part:
            key = request['payload']['parent_request_sha256']
            with lock:  # Parts run at the same time; the review is written once per round.
                if key not in reviews:
                    reviews[key] = answer({**request, 'payload': {k: v for k, v in request['payload'].items()
                                                                if k != 'review_part'}})['review']
            return review_part(request, reviews[key])
        calls.append((stage, request['payload']))
        response = read_json(reference_run / 'saved_responses' / (stage + '.json'))
        response['request_sha256'] = request['request_sha256']
        if 'revision_patch' in request['payload']:
            # Compression rules 1.26.0: the redo after a review is a patch of the reviewed inventory.
            first = {**request['payload']['reviewed_inventory']['items'][0], 'rationale': 'Revised after review.'}
            fields = request['payload']['schema']['properties']['requirements']['properties']
            response = {'request_sha256': request['request_sha256'], 'remove_item_ids': [],
                        'requirements': {'items': [first], **({'potential_questions': []} if 'potential_questions' in fields else {})},
                        **({'remove_question_ids': []} if 'potential_questions' in fields else {}),
                        'changes': [{'id': first['id'], 'action': 'REPLACE', 'finding': 'Authored test.'}]}
        if stage == 'requirements_review' and review:
            review(response['review'])
        return response
    return answer


def review_part(request, review):
    p = request['payload']; own = set(p['review_part']['item_ids']); units = set(p['review_source_unit_ids'])
    return {'request_sha256': request['request_sha256'], 'review': {**review,
            'items': [r for r in review['items'] if r['requirement_id'] in own],
            'source_units': [r for r in review['source_units'] if r['unit_id'] in units]}}


def stopped_run(tmp_path, reference_run, decision):
    run = tmp_path / 'run'
    init_run(run, EXAMPLES / 'current_research/proposal.md', context_review_mode='legacy')
    def stop(review):
        review['decision'] = decision; review['source_units'][0]['verdict'] = 'MISSING'
    assert run_model(run, generator=model_for(reference_run, [], stop))['status'] == decision
    return run


def test_revise_redoes_only_the_reviewed_stage_with_guidance(tmp_path, reference_run):
    run = stopped_run(tmp_path, reference_run, 'REVISE')
    review = read_json(run / 'feedback/requirements.json')
    record = reopen_for_revision(run, guidance='Restore the omitted first section.', submitted_by='Synthetic tester')
    assert record['stage'] == 'requirements' and record['decision'] == 'REVISE'
    assert record['candidate_acceptance_removed'] is False  # REVISE had already removed it.
    assert not record['scientific_approval'] and not record['guidance_is_scientific_evidence']
    assert list((run / 'audit/revisions').glob('*.json'))
    payload = make_request(run, 'requirements')['payload']
    assert payload['previous_feedback'] == review
    assert payload['revision_guidance'] == {'guidance': 'Restore the omitted first section.',
                                            'submitted_by': 'Synthetic tester', 'at': record['at']}
    assert 'not scientific evidence' in payload['instructions']
    calls = []
    assert run_model(run, generator=model_for(reference_run, calls))['status'] == 'CONTEXT_READY'
    # Attachment planning and evidence were accepted before the stop and are not called again.
    assert [stage for stage, _ in calls] == ['requirements', 'requirements_review', 'context', 'context_review']
    assert calls[0][1]['revision_guidance']['guidance'] == 'Restore the omitted first section.'
    assert all('revision_guidance' not in payload for _, payload in calls[1:])


def test_needs_review_releases_the_candidate_only_on_request(tmp_path, reference_run):
    run = stopped_run(tmp_path, reference_run, 'NEEDS_REVIEW')
    assert 'requirements' in load_run(run)[1]['accepted']
    record = reopen_for_revision(run, submitted_by='Synthetic tester')
    assert record['candidate_acceptance_removed'] is True
    accepted = load_run(run)[1]['accepted']
    assert 'requirements' not in accepted and {'attachment_plan', 'attachment_evidence'} <= set(accepted)
    assert 'revision_guidance' not in make_request(run, 'requirements')['payload']  # No guidance was given.


def test_guidance_does_not_outlive_the_review_it_answers(tmp_path, reference_run):
    run = stopped_run(tmp_path, reference_run, 'REVISE')
    reopen_for_revision(run, guidance='Restore the omitted first section.', submitted_by='Synthetic tester')
    def again(review):
        review['decision'] = 'REVISE'; review['source_units'][1]['verdict'] = 'MISSING'
    assert run_model(run, generator=model_for(reference_run, [], again))['status'] == 'REVISE'
    payload = make_request(run, 'requirements')['payload']
    assert payload['previous_feedback'] == read_json(run / 'feedback/requirements.json')
    assert 'revision_guidance' not in payload


def test_only_a_semantic_review_stop_can_be_reopened(tmp_path, reference_run):
    run = stopped_run(tmp_path, reference_run, 'REVISE')
    stopped = read_json(run / 'stopped.json')
    write_json(run / 'stopped.json', {**stopped, 'status': 'ERROR'})
    with pytest.raises(ValueError, match='REVISE or NEEDS_REVIEW'):
        reopen_for_revision(run)
    write_json(run / 'stopped.json', stopped)
    write_json(run / 'feedback/requirements.json', {'decision': 'REVISE', 'altered': True})
    with pytest.raises(ValueError, match='no longer matches'):
        reopen_for_revision(run)
    assert not (run / 'feedback/requirements.guidance.json').exists()
    assert digest(read_json(run / 'stopped.json')) == digest(stopped)


def automatic_run(tmp_path, reference_run, monkeypatch, decisions):
    """A run under the current rules whose requirements reviews answer decisions in turn, then PASS."""
    from ctxcomp.rules import load_rules
    freeze(monkeypatch, load_rules())
    run = tmp_path / 'run'
    init_run(run, EXAMPLES / 'current_research/proposal.md', context_review_mode='legacy')
    answers = iter(decisions); calls = []
    def review(r):
        decision = next(answers, 'PASS')
        if decision != 'PASS':
            r['decision'] = decision; r['source_units'][0]['verdict'] = 'MISSING'
    return run, calls, run_model(run, generator=model_for(reference_run, calls, review))


def test_from_1_29_a_revise_is_patched_and_reviewed_again_without_a_person(tmp_path, reference_run, monkeypatch):
    run, calls, result = automatic_run(tmp_path, reference_run, monkeypatch, ['REVISE'])
    assert result['status'] == 'CONTEXT_READY'
    stages = [stage for stage, _ in calls if stage != 'attachment_plan']
    assert stages == ['requirements', 'requirements_review', 'requirements', 'requirements_review', 'context', 'context_review']
    assert 'reviewed_inventory' in calls[3][1] and 'reviewed_inventory' not in calls[1][1]
    records = [read_json(p) for p in (run / 'audit/revisions').glob('*.json')]
    assert [(r['submitted_by'], r['guidance']) for r in records] == [('host:automatic_revision', '')]


def test_a_second_revise_stops_for_a_person(tmp_path, reference_run, monkeypatch):
    run, calls, result = automatic_run(tmp_path, reference_run, monkeypatch, ['REVISE', 'REVISE'])
    assert result['status'] == 'REVISE'
    assert [stage for stage, _ in calls].count('requirements_review') == 2
    assert len(list((run / 'audit/revisions').glob('*.json'))) == 1
    assert read_json(run / 'stopped.json')['status'] == 'REVISE'
