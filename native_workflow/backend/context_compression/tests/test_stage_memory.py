"""Answers shared between runs, running up to one stage, and redoing a stage. Authored responses exercise the
contracts, not model accuracy."""
import pytest
from ctxcomp.engine import init_run, load_run, rerun_from, stage_status
from ctxcomp.io import read_json
from ctxcomp.providers import run_model
from test_retention import reference_run, EXAMPLES
from test_same_run_revision import model_for

EXECUTOR = {'provider': 'test_generator', 'requested_model': 'synthetic'}


def new_run(path):
    init_run(path, EXAMPLES / 'current_research/proposal.md', context_review_mode='legacy')
    return path


def stages(calls):
    return [stage for stage, _ in calls]


def test_a_new_run_reuses_answers_an_earlier_run_had_accepted(tmp_path, reference_run):
    memory = tmp_path / 'memory'
    first, calls = new_run(tmp_path / 'first'), []
    assert run_model(first, generator=model_for(reference_run, calls), review_executor_id=EXECUTOR,
                     shared_cache=memory)['status'] == 'CONTEXT_READY'
    assert 'requirements' in stages(calls)
    second, again = new_run(tmp_path / 'second'), []
    assert run_model(second, generator=model_for(reference_run, again), review_executor_id=EXECUTOR,
                     shared_cache=memory)['status'] == 'CONTEXT_READY'
    # Identical requests from the same executor need no model call; every check of accept still ran.
    assert 'requirements' not in stages(again) and 'context' not in stages(again)
    reused = read_json(second / 'audit/reused/requirements.json')
    assert reused['source_run'] == str(first.resolve()) and reused['model_called'] is False
    assert load_run(second)[1]['accepted']['requirements']['provider'] == 'stage_cache'
    assert {r['stage']: r['status'] for r in stage_status(second)}['requirements'] == 'REUSED'


def test_another_executor_or_a_fresh_stage_calls_the_model(tmp_path, reference_run):
    memory = tmp_path / 'memory'
    run_model(new_run(tmp_path / 'first'), generator=model_for(reference_run, []), review_executor_id=EXECUTOR,
              shared_cache=memory)
    other = []
    run_model(new_run(tmp_path / 'other'), generator=model_for(reference_run, other),
              review_executor_id={**EXECUTOR, 'requested_model': 'another'}, shared_cache=memory)
    assert 'requirements' in stages(other)
    fresh = []
    run_model(new_run(tmp_path / 'fresh'), generator=model_for(reference_run, fresh), review_executor_id=EXECUTOR,
              shared_cache=memory, fresh=('requirements',))
    # The fresh answer is identical here, so later requests are unchanged and still reused.
    assert stages(fresh) == ['requirements']


def test_a_rejected_review_is_not_remembered(tmp_path, reference_run):
    memory = tmp_path / 'memory'
    def stop(review):
        review['decision'] = 'REVISE'; review['source_units'][0]['verdict'] = 'MISSING'
    assert run_model(new_run(tmp_path / 'first'), generator=model_for(reference_run, [], stop),
                     review_executor_id=EXECUTOR, shared_cache=memory)['status'] == 'REVISE'
    assert not (memory / 'requirements_review').exists() and (memory / 'requirements').exists()


def test_run_until_a_stage_then_redo_it(tmp_path, reference_run):
    run, calls = new_run(tmp_path / 'run'), []
    assert run_model(run, generator=model_for(reference_run, calls), until='requirements') == {
        'status': 'STAGE_READY', 'stage': 'requirements'}
    assert stages(calls)[-1] == 'requirements'
    assert {r['stage']: r['status'] for r in stage_status(run)}['requirements_review'] == 'PENDING'
    run_model(run, generator=model_for(reference_run, []))
    record = rerun_from(run, 'requirements', requested_by='Synthetic tester')
    assert record['removed_acceptances'] == ['requirements', 'requirements_review', 'context', 'context_review']
    accepted = load_run(run)[1]['accepted']
    assert 'requirements' not in accepted and {'attachment_plan', 'attachment_evidence'} <= set(accepted)
    calls = []
    assert run_model(run, generator=model_for(reference_run, calls))['status'] == 'CONTEXT_READY'
    assert stages(calls) == ['requirements', 'requirements_review', 'context', 'context_review']
    with pytest.raises(ValueError, match='until must be one of'):
        run_model(run, generator=model_for(reference_run, []), until='pipeline')
