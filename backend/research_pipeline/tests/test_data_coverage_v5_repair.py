"""Local targeted correction and original v5 replay; no provider calls."""
import copy
from pathlib import Path

import pytest
from ctxcomp.io import digest
from research_pipeline import data_coverage_v5 as v, data_coverage_v5_repair as repair
from research_pipeline.data_live_batch import Batch
from research_pipeline.common import read_json, write_json
from research_pipeline.adequacy import file_ref
from test_data_coverage_facts_v5 import case, answer


@pytest.fixture
def failed(case, tmp_path, monkeypatch):
    built, payload = case
    payload['part_id'] = 'FACT001'
    plan = write_json(tmp_path/'plan.json', {})
    source = write_json(tmp_path/'source.json', {})
    history = write_json(tmp_path/'history.json', {'elapsed_seconds': 1500.407, 'calls': 4, 'prior_calls': 4})
    built.update(payloads=[payload], planning_sha256='fixture',
        bindings={'plan': file_ref(plan), 'source_view': file_ref(source)},
        historical_import={'refs': {'budget': file_ref(history)}}, prior_model_seconds=1500.407, prior_model_calls=8)
    out = tmp_path/'coverage'
    write_json(out/'build.json', built)
    request = v.governed_request(payload)
    write_json(out/'requests/FACT001.json', request)
    raw = answer(payload)
    raw['request_sha256'] = request['request_sha256']
    fid = next(iter(raw['facts']))
    raw['facts'][fid]['x'] = raw['facts'][fid]['e'][:]
    rawdir = out/'calls/failed/data_agents/audit/DC-review/raw'
    write_json(rawdir/'response.json', raw)
    write_json(rawdir/'request.json', request)
    write_json(out/'attempts/failed.json', {'id': 'failed', 'part_id': 'FACT001',
        'build_sha256': digest(built), 'status': 'FAILED', 'provider_started': True,
        'elapsed_seconds': 12.0, 'timeout_seconds': 1500, 'checks': len(raw['facts'])})
    monkeypatch.setattr(v, '_load', lambda path: built)
    auth = write_json(tmp_path/'auth.json', {'new_calls_model': 'gpt-6-sol',
        'new_batch_provider_seconds_limit': 1500, 'new_batch_wall_seconds_limit': 1800,
        'prior_history_is_not_reset': True,
        'inputs': {'DR': file_ref(plan), 'source_view': file_ref(source), 'historical_coverage_budget': file_ref(history)}})
    Batch.create(auth, tmp_path/'batch')
    return out, tmp_path/'repair', raw, fid


def corrected(folder):
    plan = read_json(folder/'plan.json')
    raw = read_json(plan['refs']['original_raw']['path'])
    return {'request_sha256': read_json(folder/'request.json')['request_sha256'],
        'facts': {fid: {**raw['facts'][fid], 's': 'CONFLICT',
                       'r': 'Synthetic correction retains the original contradiction.',
                       'n': 'Review the original scoped source and its experimental-unit condition.'}
                  for fid in plan['targets']}}


def test_correction_keeps_other_facts_metadata_and_original_v5_replays(failed):
    out, folder, original, fid = failed
    plan = repair.prepare(out, 'failed', folder)
    assert plan['targets'] == [fid]
    assert len(plan['payload']['facts']) == 1
    assert 'unit_metadata' not in plan['schema']['properties']
    before = Path(plan['refs']['original_raw']['path']).read_bytes()
    calls = []
    def provider(request, **options):
        calls.append(request)
        return corrected(folder)
    provider.executor_id = 'SYNTHETIC_TARGETED_CORRECTION'
    with Batch.open(out.parent/'batch') as batch:
        result = repair.run_prepared(folder, batch=batch, generator=provider)
        assert result['complete'] and len(calls) == 1
        assert result['model_budget']['prior_calls'] == 8
        assert result['model_budget']['calls'] == 2  # Original failed + one correction.
        assert batch.summary()['new_calls'] == 1
        assert repair.run_prepared(folder, batch=batch, generator=provider) == result
        assert len(calls) == 1
    merged = repair.verify_merge(folder)
    assert merged['unit_metadata'] == original['unit_metadata']
    assert all(merged['facts'][key] == value for key, value in original['facts'].items() if key != fid)
    assert merged['facts'][fid]['x'] == original['facts'][fid]['x']
    assert Path(plan['refs']['original_raw']['path']).read_bytes() == before
    assert read_json(out/'attempts/failed.json')['status'] == 'FAILED'
    receipt = read_json(out/'accepted/FACT001.json')
    assert receipt['response_origin'].startswith('HOST_DERIVED_TARGETED_CORRECTION')
    assert v.verify_result(out/'coverage.json') == result


@pytest.mark.parametrize('damage', ['discard_counter', 'foreign_fact', 'omit_fact', 'stale_hash'])
def test_rejects_unbounded_or_evidence_discarding_correction(failed, damage):
    out, folder, original, fid = failed
    plan = repair.prepare(out, 'failed', folder)
    raw = corrected(folder)
    if damage == 'discard_counter': raw['facts'][fid]['x'] = []
    elif damage == 'foreign_fact': raw['facts']['F9999'] = copy.deepcopy(raw['facts'][fid])
    elif damage == 'omit_fact': raw['facts'].pop(fid)
    else: raw['request_sha256'] = 'wrong'
    with pytest.raises(ValueError):
        repair.merge(original, raw, plan['targets'], read_json(folder/'request.json'), plan['schema'])


def test_still_conflicting_supported_is_rejected_and_charged(failed):
    out, folder, _, fid = failed
    repair.prepare(out, 'failed', folder)
    def bad(request, **options):
        raw = corrected(folder)
        raw['facts'][fid]['s'] = 'SUPPORTED'
        return raw
    with Batch.open(out.parent/'batch') as batch:
        with pytest.raises(ValueError, match='Counterevidence cannot'):
            repair.run_prepared(folder, batch=batch, generator=bad)
        assert batch.summary()['new_calls'] == 1
    assert not (out/'accepted/FACT001.json').exists()
    assert (folder/'response.json').exists()
    assert v._ledger(out, read_json(out/'build.json'))['calls'] == 2
