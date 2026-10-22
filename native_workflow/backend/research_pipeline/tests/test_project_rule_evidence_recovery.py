"""Saved-response index repair tests; synthetic review is not semantic approval."""
import copy
import pytest
from research_pipeline import project_rule_agent as a
from research_pipeline.common import read_json, write_json
from test_project_rule_agent import bundle, extraction, reviewer


def saved(bundle):
    root, ref, value = bundle
    req = a.request(value, 'project_rules_extract'); raw = extraction(req)
    span = copy.deepcopy(raw['items'][0]['evidence'][0]); span['quote'] = 'after predictions are frozen'
    raw['items'][0]['field_evidence'][0]['spans'] = [span]
    return req, raw


def recover(bundle, req, raw):
    root, ref, _ = bundle
    return a.recover_evidence_index(ref, a.file_ref(write_json(root/'request.json', req)),
                                   a.file_ref(write_json(root/'raw.json', raw)), root/'recovered')


def test_exact_index_recovery_replays_through_full_review_and_publication(bundle):
    root, ref, value = bundle; req, raw = saved(bundle); original = copy.deepcopy(raw)
    with pytest.raises(ValueError, match='Field evidence'):
        a.validate_candidate(raw, req, value)
    candidate_ref = recover(bundle, req, raw)
    result = read_json(candidate_ref['path'])
    expected = copy.deepcopy(raw)
    expected['items'][0]['evidence'].append(raw['items'][0]['field_evidence'][0]['spans'][0])
    assert result == expected and raw == original and read_json(root/'raw.json') == original
    a.verify_candidate_recovery(ref, candidate_ref)
    a.review(ref, candidate_ref, root/'review', generator=reviewer)
    report = a.publish(ref, candidate_ref, a.file_ref(root/'review/review.json'), root/'published')
    assert a.verify_published(report['project_rules_ref'])['candidate_ref'] == candidate_ref
    # Even rehashing a changed raw file cannot hide a changed replay result.
    proof = read_json(candidate_ref['evidence_index_recovery_ref']['path'])
    proof['additions'] = []
    write_json(candidate_ref['evidence_index_recovery_ref']['path'], proof)
    candidate_ref['evidence_index_recovery_ref'] = a.file_ref(candidate_ref['evidence_index_recovery_ref']['path'])
    with pytest.raises(ValueError, match='replay'):
        a.verify_candidate_recovery(ref, candidate_ref)


@pytest.mark.parametrize('mode', ['invalid_quote', 'new_unit', 'missing_coverage', 'wrong_request', 'missing_authority'])
def test_recovery_cannot_supply_content_links_or_authority(bundle, mode):
    req, raw = saved(bundle); item = raw['items'][0]
    if mode == 'invalid_quote': item['field_evidence'][0]['spans'][0]['quote'] = 'invented'
    elif mode == 'new_unit': item['field_evidence'][0]['spans'] = copy.deepcopy(raw['items'][1]['evidence'])
    elif mode == 'missing_coverage': raw['source_coverage'][0]['item_ids'] = []
    elif mode == 'wrong_request': req['payload']['instructions'] += 'changed'
    else: item['authority_evidence'] = []
    with pytest.raises(ValueError): recover(bundle, req, raw)
    assert not (bundle[0]/'recovered/candidate.json').exists()


def test_new_exact_quote_must_already_have_item_unit_and_coverage(bundle):
    req, raw = saved(bundle); item = raw['items'][0]
    item['evidence'][0]['quote'] = 'Human PK is only for final validation'
    item['authority_evidence'] = copy.deepcopy(item['evidence'])
    # Both original field spans and new index quote remain exact source evidence.
    candidate_ref = recover(bundle, req, raw)
    a.verify_candidate_recovery(bundle[1], candidate_ref)


def test_semantic_revise_remains_unpublished_after_index_recovery(bundle):
    req, raw = saved(bundle); candidate_ref = recover(bundle, req, raw)
    def reject(req, **kwargs):
        result = reviewer(req); result['decision'] = 'REVISE'
        result['global_checks'][0]['verdict'] = 'REVISE'
        return result
    root, ref, _ = bundle
    a.review(ref, candidate_ref, root/'review', generator=reject)
    report = a.publish(ref, candidate_ref, a.file_ref(root/'review/review.json'), root/'published')
    assert report['status'] == 'RULES_REVISION_REQUIRED'
    assert not (root/'published/main.json').exists()
