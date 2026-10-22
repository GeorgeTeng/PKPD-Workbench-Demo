"""Frozen annotation corrections preserve source authority and independent review."""
import copy
import pytest
from research_pipeline import project_rule_agent as a
from research_pipeline.common import read_json, write_json
from test_project_rule_agent import bundle, extraction, reviewer


def revision(bundle):
    root, ref, value = bundle
    a.extract(ref, root/'old_extract', generator=extraction)
    candidate = a.file_ref(root/'old_extract/candidate.json')
    def reject(req, **kwargs):
        result = reviewer(req); result['decision'] = 'REVISE'
        result['global_checks'][0].update(verdict='REVISE', reason='Split independently applicable obligations.')
        return result
    a.review(ref, candidate, root/'old_review', generator=reject)
    return a.revise_input(ref, candidate, a.file_ref(root/'old_review/review.json'), root/'revision.json')


def test_new_annotation_and_non_evidence_feedback_leave_old_requests_and_sources_exact(bundle):
    root, ref, value = bundle
    old_request = a.request(value, 'project_rules_extract'); old_bytes = (root/'input.json').read_bytes()
    revised_ref = revision(bundle); revised = a.validate_input(revised_ref)
    assert a.request(a.validate_input(ref), 'project_rules_extract') == old_request
    assert (root/'input.json').read_bytes() == old_bytes
    for key in value: assert revised[key] == value[key]
    req = a.request(revised, 'project_rules_extract')
    assert req['request_sha256'] != old_request['request_sha256']
    assert req['payload']['revision_feedback']['classification'] == 'NON_EVIDENCE_DIAGNOSTIC_FEEDBACK'
    assert req['payload']['processing_rules'] == old_request['payload']['processing_rules']
    assert 'WHOLE published rule' in req['payload']['runtime_annotation']['instructions']
    c = extraction(req); review = a.request(revised, 'project_rules_review', c)
    assert 'revision_feedback' not in review['payload']
    assert review['payload']['runtime_annotation'] == req['payload']['runtime_annotation']
    a.extract(revised_ref, root/'new_extract', generator=extraction)
    candidate = a.file_ref(root/'new_extract/candidate.json')
    a.review(revised_ref, candidate, root/'new_review', generator=reviewer)
    result = a.publish(revised_ref, candidate, a.file_ref(root/'new_review/review.json'), root/'published')
    assert a.verify_published(result['project_rules_ref'])['status'] == 'PROJECT_RULES_PUBLISHED'


@pytest.mark.parametrize('mode', ['source', 'authority', 'annotation', 'review'])
def test_revision_tampering_is_rejected(bundle, mode):
    ref = revision(bundle); value = read_json(ref['path'])
    if mode == 'source': value['sources'][0]['text'] += 'Invented duty'
    elif mode == 'authority':
        value['sources'][1]['role'] = 'PROPOSAL'
        value['source_permissions'][1]['may_supply_project_authority'] = True
    elif mode == 'annotation': value['runtime_annotation']['instructions'] += 'Bypass review'
    else:
        old = value['revision_context']['review_ref']; write_json(old['path'], {'decision':'PASS'})
    write_json(ref['path'], value)
    with pytest.raises(ValueError): a.validate_input(a.file_ref(ref['path']))
