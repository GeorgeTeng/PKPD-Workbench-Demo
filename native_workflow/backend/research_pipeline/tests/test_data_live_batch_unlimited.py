"""Explicit cumulative-time opt-out, synthetic calls only."""
import copy

import pytest
from research_pipeline import data_live_batch as bounded, data_live_batch_unlimited as unlimited
from research_pipeline.common import read_json, write_json, PipelineError
from research_pipeline.adequacy import file_ref
from test_data_live_batch import setup


def authorization(root):
    return write_json(root/'unlimited.json', {'user_instruction': '不用设置时间上限 跑通为止',
        'aggregate_provider_seconds_limit': None, 'aggregate_wall_seconds_limit': None,
        'preserve_elapsed_time_and_call_history': True, 'reuse_all_accepted_results': True,
        'requested_model': 'gpt-6-sol'})


def test_expired_batch_continues_without_changing_original_manifest_or_history(setup, monkeypatch):
    directory, out, _ = setup
    before = (directory/'manifest.json').read_bytes()
    policy = unlimited.UnlimitedBatch.enable(directory, authorization(directory.parent))
    with unlimited.UnlimitedBatch.open(directory) as batch:
        batch.bind_stage(out, 'coverage')
        write_json(directory/'calls/old.json', {'batch': batch.ref, 'timeout_seconds': 1600,
                                               'elapsed_seconds': 1600})
        state = read_json(directory/'state.json')
        state['started_epoch'] = 10
        write_json(directory/'state.json', state)
        monkeypatch.setattr(bounded.time, 'time', lambda: 4010)
        decision = batch.admission({'elapsed_seconds': 3100.407, 'samples': []}, 100)
        assert decision['allowed']
        assert batch.summary()['new_provider_seconds'] == 1600
        assert batch.summary()['historical_elapsed_seconds'] == 1500.407
        assert batch.summary()['aggregate_provider_seconds_limit'] is None
        assert batch.summary()['time_policy'] == policy
    assert (directory/'manifest.json').read_bytes() == before
    # Opt-out must not silently affect the original adapter/default.
    with bounded.Batch.open(directory) as old:
        assert not old.admission({'elapsed_seconds': 3100.407}, 1)['allowed']


def test_authorization_is_append_only_and_tamper_rejected(setup):
    directory, _, _ = setup
    auth = authorization(directory.parent)
    unlimited.UnlimitedBatch.enable(directory, auth)
    with pytest.raises(FileExistsError):
        unlimited.UnlimitedBatch.enable(directory, auth)
    write_json(auth, {'changed': True})
    with pytest.raises(ValueError):
        unlimited.UnlimitedBatch.open(directory)


def test_enable_rejects_active_batch(setup):
    directory, _, _ = setup
    with bounded.Batch.open(directory):
        with pytest.raises(ValueError, match='releases its lock'):
            unlimited.UnlimitedBatch.enable(directory, authorization(directory.parent))


def test_necessity_resumes_after_1500_with_timeout_validation_and_exact_replay(tmp_path, monkeypatch):
    from research_pipeline import data_necessity_v6 as n
    from test_data_necessity_v5 import inputs
    from test_data_necessity_v4 import rules
    from test_data_necessity_v6 import answer
    plan, cov, catalog = inputs()
    engine = n._engine()
    monkeypatch.setattr(engine, '_verified_inputs', lambda *args:
        (copy.deepcopy(plan), copy.deepcopy(cov), copy.deepcopy(catalog), rules()))
    monkeypatch.setattr(n, '_engine', lambda: engine)
    pp = write_json(tmp_path/'inputs/plan.json', plan)
    cp = write_json(tmp_path/'coverage/coverage.json', cov)
    source = write_json(tmp_path/'source.json', {})
    history = write_json(tmp_path/'history.json', {'elapsed_seconds': 1500.407, 'calls': 4, 'prior_calls': 4})
    scope = write_json(tmp_path/'auth.json', {'new_calls_model': bounded.MODEL,
        'new_batch_provider_seconds_limit': 1500, 'new_batch_wall_seconds_limit': 1800,
        'prior_history_is_not_reset': True, 'inputs': {'DR': file_ref(pp),
        'source_view': file_ref(source), 'historical_coverage_budget': file_ref(history)}})
    directory = tmp_path/'batch'
    bounded.Batch.create(scope, directory)
    policy = unlimited.UnlimitedBatch.enable(directory, authorization(tmp_path))
    out = tmp_path/'necessity'
    build = n.prepare(pp, cp, out, time_policy=policy)
    assert build['budget']['max_provider_seconds'] is None
    ticks = iter([10, 1611, 2000, 2001])
    monkeypatch.setattr(engine, '_monotonic', lambda: next(ticks))
    timeouts = []
    def generate(request, **options):
        timeouts.append(options['timeout'])
        raw = answer(read_json(out/'parts/NEC01/payload.json'))
        return {**raw, 'request_sha256': request['request_sha256']}
    generate.executor_id = 'SYNTHETIC_UNLIMITED_CONTINUATION'
    with unlimited.UnlimitedBatch.open(directory) as batch:
        write_json(cp.parent/'batch_binding.json', {'batch': batch.ref})
        with pytest.raises(PipelineError, match='remaining time allowance'):
            n.run_prepared(out, generator=generate, batch=batch)
        assert read_json(out/'provider_budget_ledger.json')['provider_elapsed_seconds'] == 1601
        result = n.run_prepared(out, generator=generate, batch=batch, retry_failed=True)
        assert result['complete'] and timeouts == [1500, 1500]
        assert n.verify_result(out/'necessity.json') == result
        assert read_json(out/'provider_budget_ledger.json')['provider_elapsed_seconds'] == 1602
        assert n.run_prepared(out, generator=generate, batch=batch) == result
        assert len(timeouts) == 2
    # Per-request ledger allowance stays checked even though cumulative time is unrestricted.
    ledger = read_json(out/'provider_budget_ledger.json')
    ledger['attempts'][1]['provider_timeout_seconds'] = 1499
    with pytest.raises(PipelineError, match='timeout differs'):
        engine._validate_ledger(out, ledger, engine.verify_prepared(out)[-1])
