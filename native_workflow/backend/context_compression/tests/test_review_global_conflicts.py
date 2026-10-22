"""CC012 global conflicts: complete checklist, traceable findings and no override."""
import pytest
from ctxcomp import split_review as split
from ctxcomp.engine import prepare
from ctxcomp.providers import run_model
from ctxcomp.io import read_json
from review_test_support import reference_run, split_run, branch_case, validate, authored_response


def test_global_review_receives_both_reviews_and_full_source_context(split_run):
    case = branch_case(split_run, split.GLOBAL)
    validate(case, split.GLOBAL)
    p = case[1]['payload']
    assert set(p['branch_reviews']) == {split.FAITH, split.COMPLETE}
    assert p['context'] == case[0]['payload']['context']
    assert p['source_units'] == case[0]['payload']['source_units']
    assert p['required_check_ids'] == list(split.GLOBAL_CHECKS)


@pytest.mark.parametrize('check_id', split.GLOBAL_CHECKS)
def test_every_global_check_is_required_once(split_run, check_id):
    case = branch_case(split_run, split.GLOBAL)
    record = next(x for x in case[2]['review']['checks'] if x['id'] == check_id)
    record['id'] = 'UNKNOWN_CHECK'
    with pytest.raises(ValueError, match='exactly once'): validate(case, split.GLOBAL)


@pytest.mark.parametrize('check_id', split.GLOBAL_CHECKS)
def test_each_unresolved_global_conflict_blocks_publication(split_run, check_id):
    run, original = split_run
    def generator(request, model=None):
        result = authored_response(request, original)
        if request['payload']['stage'] == split.GLOBAL:
            r = result['review']; r['decision'] = 'NEEDS_REVIEW'
            finding = next(x for x in r['checks'] if x['id'] == check_id)
            finding.update(verdict='UNRESOLVED', reason='Authored unresolved conflict: ' + check_id)
        return result
    assert run_model(run, generator=generator)['status'] == 'NEEDS_REVIEW'
    assert not (run/'handoff/main.json').exists()
    assert check_id in str(read_json(run/'feedback/context.json'))


@pytest.mark.parametrize('fault', ['false_pass', 'fabricated_source', 'fabricated_target', 'stale_response'])
def test_global_review_rejects_invalid_claims(split_run, fault):
    case = branch_case(split_run, split.GLOBAL)
    response = case[2]; finding = response['review']['checks'][0]
    if fault == 'false_pass': finding['verdict'] = 'ALTERED'
    elif fault == 'fabricated_source':
        u = case[0]['payload']['source_units'][0]
        finding['source_evidence'] = [{'source_id':u['source_id'],'unit_id':u['id'],'quote':'Invented source text.'}]
    elif fault == 'fabricated_target': finding['targets'] = [{'path':'/objective','quote':'Invented output text.'}]
    else: response['request_sha256'] = 'different_review'
    with pytest.raises(ValueError): validate(case, split.GLOBAL)


@pytest.mark.parametrize('branch', [split.FAITH, split.COMPLETE])
@pytest.mark.parametrize('decision', ['REVISE', 'NEEDS_REVIEW'])
def test_global_pass_cannot_override_either_required_review(split_run, branch, decision):
    run, original = split_run
    def generator(request, model=None):
        response = authored_response(request, original)
        if request['payload']['stage'] == branch:
            response['review']['decision'] = decision
            response['review']['critical_errors'] = ['Authored unresolved branch finding.']
        return response
    assert run_model(run, generator=generator)['status'] == decision
    assert not (run/'handoff/main.json').exists()


def test_global_duplicate_check_cannot_hide_another_check(split_run):
    case = branch_case(split_run, split.GLOBAL)
    checks = case[2]['review']['checks']; checks[-1] = dict(checks[0])
    with pytest.raises(ValueError, match='exactly once'): validate(case, split.GLOBAL)
