"""Bounded execution fixtures only; no actual provider is called."""
import pytest
from research_pipeline import data_live_batch as b, data_coverage_v5 as coverage
from research_pipeline.common import write_json, read_json
from research_pipeline.adequacy import file_ref


@pytest.fixture
def setup(tmp_path):
    plan = write_json(tmp_path/'plan.json', {})
    source = write_json(tmp_path/'source.json', {})
    history = write_json(tmp_path/'history.json', {'elapsed_seconds': 1500.407, 'calls': 4, 'prior_calls': 4})
    auth = write_json(tmp_path/'auth.json', {'new_calls_model': 'gpt-6-sol',
        'new_batch_provider_seconds_limit': 1500, 'new_batch_wall_seconds_limit': 1800,
        'prior_history_is_not_reset': True,
        'inputs': {'DR': file_ref(plan), 'source_view': file_ref(source), 'historical_coverage_budget': file_ref(history)}})
    out = tmp_path/'coverage'
    write_json(out/'build.json', {'bindings': {'plan': file_ref(plan), 'source_view': file_ref(source)},
        'historical_import': {'refs': {'budget': file_ref(history)}}})
    directory = tmp_path/'batch'
    b.Batch.create(auth, directory)
    return directory, out, auth


def test_explicit_additional_budget_preserves_exhausted_history(setup):
    directory, out, _ = setup
    old = {'elapsed_seconds': 1500.407, 'samples': []}
    assert not coverage.admission(old, 1)['allowed']
    with b.Batch.open(directory) as batch:
        batch.bind_stage(out, 'coverage')
        assert batch.admission(old, 1)['allowed']
        assert old['elapsed_seconds'] == 1500.407
        assert batch.summary()['historical_calls'] == 8
        assert batch.summary()['new_calls'] == 0
    with pytest.raises(ValueError, match='original explicit batch'):
        b.require_stage_batch(out, None)


def test_one_authorization_cannot_create_second_budget(setup):
    directory, _, auth = setup
    with pytest.raises(FileExistsError):
        b.Batch.create(auth, directory.parent/'another')


@pytest.mark.parametrize('exception', [RuntimeError('failure'), KeyboardInterrupt()])
def test_failure_and_interrupt_charge_shared_time(setup, monkeypatch, exception):
    directory, out, _ = setup
    ticks = iter([10.0, 22.0])
    monkeypatch.setattr(b.time, 'monotonic', lambda: next(ticks))
    def failed(*args, **kwargs):
        assert kwargs['timeout'] <= 1480
        raise exception
    with b.Batch.open(directory) as batch:
        batch.bind_stage(out, 'coverage')
        with pytest.raises(type(exception)):
            batch.generator(out, failed)({'request_sha256': 'test'}, model='gpt-6-sol', timeout=2000)
        assert batch.summary()['new_provider_seconds'] == 12
        assert batch.summary()['new_calls'] == 1
    with b.Batch.open(directory) as batch:
        assert batch.summary()['new_provider_seconds'] == 12


def test_unknown_crash_consumes_reservation_and_wall_limits_dispatch(setup, monkeypatch):
    directory, out, _ = setup
    with b.Batch.open(directory) as batch:
        batch.bind_stage(out, 'coverage')
        write_json(directory/'calls/crash.json', {'batch': batch.ref, 'timeout_seconds': 1400})
        assert batch.summary()['remaining_seconds'] == 100
        state = read_json(directory/'state.json')
        state['started_epoch'] = 100
        write_json(directory/'state.json', state)
        monkeypatch.setattr(b.time, 'time', lambda: 1890)
        assert batch.summary()['remaining_seconds'] == 10
        assert not batch.admission({'elapsed_seconds': 1600}, 1)['allowed']
        with pytest.raises(ValueError, match='exhausted'):
            batch.generator(out, lambda *a, **k: pytest.fail('dispatch'))(
                {'request_sha256': 'test'}, model='gpt-6-sol', timeout=1000)


def test_necessity_shares_remaining_and_requires_same_batch_coverage(setup, monkeypatch):
    directory, out, auth = setup
    nec = out.parent/'necessity'
    scope = read_json(auth)
    cov = write_json(out/'coverage.json', {'complete': True})
    write_json(nec/'build.json', {'version': 'fixture'})
    write_json(nec/'bindings.json', {'plan': scope['inputs']['DR'], 'coverage': file_ref(cov)})
    ticks = iter([10, 310, 400, 420])
    monkeypatch.setattr(b.time, 'monotonic', lambda: next(ticks))
    timeouts = []
    def fake(*args, **kwargs):
        timeouts.append(kwargs['timeout'])
        return {}
    with b.Batch.open(directory) as batch:
        with pytest.raises(ValueError, match='same batch'):
            batch.bind_stage(nec, 'necessity')
        batch.bind_stage(out, 'coverage')
        batch.generator(out, fake)({'request_sha256': 'cov'}, model='gpt-6-sol', timeout=9999)
        batch.bind_stage(nec, 'necessity')
        batch.generator(nec, fake)({'request_sha256': 'nec'}, model='gpt-6-sol', timeout=9999)
        assert timeouts == [1480, 1180]
        assert batch.summary()['new_provider_seconds'] == 320
        assert batch.summary()['historical_elapsed_seconds'] == 1500.407


def test_model_and_bound_hash_drift_fail_before_dispatch(setup):
    directory, out, _ = setup
    with b.Batch.open(directory) as batch:
        batch.bind_stage(out, 'coverage')
        generate = batch.generator(out, lambda *a, **k: pytest.fail('dispatch'))
        with pytest.raises(ValueError, match='exact gpt-6-sol'):
            generate({'request_sha256': 'x'}, model='gpt-6-luna', timeout=100)
        write_json(out/'build.json', {'changed': True})
        with pytest.raises(ValueError):
            generate({'request_sha256': 'x'}, model='gpt-6-sol', timeout=100)


def test_wrapper_has_stable_provider_routing_identity_without_served_claim(setup):
    from research_pipeline import data_agents as d
    directory, out, _ = setup
    with b.Batch.open(directory) as batch:
        wrapper = batch.generator(out)
        assert d.executor_id(b.MODEL, None) in wrapper.executor_id
        assert wrapper.executor_id == batch.generator(out).executor_id
        assert 'served_model' not in batch.manifest


def test_batch_through_actual_necessity_engine_and_replay(tmp_path, monkeypatch):
    import copy
    from research_pipeline import data_necessity_v6 as n
    from test_data_necessity_v6 import answer
    from test_data_necessity_v5 import inputs
    from test_data_necessity_v4 import rules
    plan, cov, catalog = inputs()
    engine = n._engine()
    monkeypatch.setattr(engine, '_verified_inputs', lambda *args:
        (copy.deepcopy(plan), copy.deepcopy(cov), copy.deepcopy(catalog), rules()))
    monkeypatch.setattr(n, '_engine', lambda: engine)
    pp = write_json(tmp_path/'inputs/plan.json', plan)
    cp = write_json(tmp_path/'coverage/coverage.json', cov)
    source = write_json(tmp_path/'source.json', {})
    history = write_json(tmp_path/'history.json', {'elapsed_seconds': 1500.407, 'calls': 4, 'prior_calls': 4})
    auth = write_json(tmp_path/'auth.json', {'new_calls_model': b.MODEL,
        'new_batch_provider_seconds_limit': 1500, 'new_batch_wall_seconds_limit': 1800,
        'prior_history_is_not_reset': True, 'inputs': {'DR': file_ref(pp),
        'source_view': file_ref(source), 'historical_coverage_budget': file_ref(history)}})
    b.Batch.create(auth, tmp_path/'batch')
    out = tmp_path/'necessity'
    n.prepare(pp, cp, out)
    calls = []
    def generate(request, **kwargs):
        calls.append(request)
        raw = answer(read_json(out/'parts/NEC01/payload.json'))
        return {**raw, 'request_sha256': request['request_sha256']}
    generate.executor_id = 'SYNTHETIC_BATCH_NECESSITY'
    with b.Batch.open(tmp_path/'batch') as batch:
        # Stub the completed Coverage marker; all Necessity runtime/replay is real.
        write_json(cp.parent/'batch_binding.json', {'batch': batch.ref})
        result = n.run_prepared(out, batch=batch, generator=generate)
        assert result['complete'] and len(calls) == 1
        assert n.verify_result(out/'necessity.json') == result
        assert n.run_prepared(out, batch=batch, generator=generate) == result
        assert batch.summary()['new_calls'] == 1
