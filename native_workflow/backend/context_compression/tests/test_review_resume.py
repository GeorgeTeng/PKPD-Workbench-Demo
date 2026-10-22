"""Explicit retry call counts and stale-review rejection, using authored responses."""
import copy
import pytest
from ctxcomp import split_review as split
from ctxcomp.engine import prepare, verify_context
from ctxcomp.io import read_json, write_json, digest
from ctxcomp.providers import run_model
from test_split_review import split_run, authored_response
from test_retention import reference_run


def fail_global_once(run, original, *, identity='test-provider-v1'):
    calls = []
    def generate(request, model=None):
        stage = request['payload']['stage']; calls.append(stage)
        if stage == split.GLOBAL:
            raise RuntimeError('Synthetic disconnect')
        return authored_response(request, original)
    with pytest.raises(RuntimeError, match='disconnect'):
        run_model(run, generator=generate, review_executor_id=identity)
    return calls


def test_explicit_retry_only_calls_failed_global(split_run):
    run, original = split_run
    assert set(fail_global_once(run, original)) == set(split.BRANCHES)
    calls = []
    def generate(request, model=None):
        calls.append(request['payload']['stage'])
        return authored_response(request, original)
    assert run_model(run, generator=generate, review_executor_id='test-provider-v1')['status'] == 'CONTEXT_READY'
    assert calls == [split.GLOBAL]
    assert verify_context(run)['status'] == 'VALID'
    proof = read_json(run/'parallel_review_proof.json')
    assert proof['branches'][split.FAITH]['execution'] == 'REUSED'
    assert proof['branches'][split.COMPLETE]['execution'] == 'REUSED'
    assert proof['branches'][split.GLOBAL]['execution'] == 'GENERATED'


@pytest.mark.parametrize('change', ['candidate', 'rules', 'schema', 'executor'])
def test_changed_dependencies_prevent_review_reuse(split_run, change):
    run, original = split_run
    fail_global_once(run, original)
    base = copy.deepcopy(prepare(run, 'context_review'))
    identity = 'test-provider-v1'
    if change == 'candidate': base['payload']['context']['version'] = 'new-candidate'
    elif change == 'rules': base['payload']['processing_rules']['version'] = 'changed'
    elif change == 'schema': base['payload']['schema']['description'] = 'Changed schema'
    else: identity = 'different-provider'
    base['request_sha256'] = digest(base['payload'])
    calls = []
    def generate(request, branch, cancel):
        calls.append(branch)
        return authored_response(request, original)
    split.execute(run, base, 'changed-'+change, generate, executor_id=identity)
    assert set(calls) == set(split.BRANCHES)


def test_tampered_reusable_response_stops_without_new_model_call(split_run):
    run, original = split_run
    fail_global_once(run, original)
    artifact = next((run/'review_branches').glob('*/'+split.FAITH+'.response.json'))
    response = read_json(artifact); response['review']['limitations'].append('Altered audit')
    write_json(artifact, response)
    calls = []
    def generate(request, model=None):
        calls.append(request['payload']['stage'])
        return authored_response(request, original)
    with pytest.raises(ValueError, match='changed'):
        run_model(run, generator=generate, review_executor_id='test-provider-v1')
    assert not calls
    assert not (run/'handoff/main.json').exists()


def test_semantic_failure_is_reused_as_failure_not_shopped_for_pass(split_run):
    run, original = split_run; base = prepare(run, 'context_review')
    def failing(request, branch, cancel):
        response = authored_response(request, original)
        if branch == split.FAITH:
            response['review']['decision'] = 'REVISE'
            response['review']['critical_errors'] = ['Known omission']
        return response
    first = split.execute(run, base, 'semantic-first', failing, executor_id='test-provider-v1')
    assert first['review']['decision'] == 'REVISE'
    def forbidden(*args):
        pytest.fail('An unchanged failed review must not be repeatedly sampled for PASS')
    second = split.execute(run, base, 'semantic-second', forbidden, executor_id='test-provider-v1')
    assert second == first
    assert not (run/'handoff/main.json').exists()


def test_custom_generator_without_identity_does_not_reuse(split_run):
    run, original = split_run
    fail_global_once(run, original)
    calls = []
    def generate(request, model=None):
        calls.append(request['payload']['stage'])
        return authored_response(request, original)
    assert run_model(run, generator=generate)['status'] == 'CONTEXT_READY'
    assert set(calls) == set(split.BRANCHES)


def test_invalid_branch_is_retried_without_repeating_valid_sibling(split_run):
    run, original = split_run
    def invalid(request, model=None):
        response = authored_response(request, original)
        if request['payload']['stage'] == split.COMPLETE:
            response['review']['coverage'].pop()
        return response
    with pytest.raises(split.ReviewOutputError):
        run_model(run, generator=invalid, review_executor_id='test-provider-v1')
    calls = []
    def repaired(request, model=None):
        calls.append(request['payload']['stage'])
        return authored_response(request, original)
    assert run_model(run, generator=repaired, review_executor_id='test-provider-v1')['status'] == 'CONTEXT_READY'
    assert calls == [split.COMPLETE, split.GLOBAL]


def test_changed_validator_prevents_reuse(split_run, monkeypatch):
    run, original = split_run
    fail_global_once(run, original)
    monkeypatch.setattr(split, '_validator_fingerprint', lambda: 'new-validator-version')
    calls = []
    def generate(request, model=None):
        calls.append(request['payload']['stage'])
        return authored_response(request, original)
    assert run_model(run, generator=generate, review_executor_id='test-provider-v1')['status'] == 'CONTEXT_READY'
    assert set(calls) == set(split.BRANCHES)


def test_changed_branch_findings_require_new_global_review(split_run):
    run, original = split_run
    base = prepare(run, 'context_review')
    prior = {branch: authored_response(split.request_for(base, branch), original)
             for branch in [split.FAITH, split.COMPLETE]}
    old = split.request_for(base, split.GLOBAL, prior)
    prior[split.COMPLETE]['review']['limitations'].append('Additional reviewed limitation')
    new = split.request_for(base, split.GLOBAL, prior)
    assert old['request_sha256'] != new['request_sha256']
