"""Explicit v5 coverage adapter over the frozen action-specific necessity rules.

The in-memory v4-shaped projection reuses the established decision contract. The
published input digest, bindings, facts and version always identify actual v5
coverage. No historical implementation or result is edited by this adapter.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
from uuid import uuid4

from ctxcomp.io import digest
from .adequacy import file_ref
from .common import PipelineError, read_json, write_json
from . import data_necessity_v4 as legacy, data_requirement_check as criteria

VERSION = 'DATA_NECESSITY_5.0'
MODEL = legacy.MODEL


def fail(message):
    raise PipelineError('DATA_NECESSITY_V5_INVALID', message)


def _pure_aggregates(payload):
    omitted = set()
    for unit in payload['units']:
        by_id = {c['id']: c for c in unit['criteria']}
        full = by_id.get('FULL_REQUIREMENT', {})
        proof = full.get('host_derivation')
        if not proof:
            continue  # Original imported model judgements still need normal handling.
        if proof.get('version') != 'CONSTITUENT_FACTS_1.0':
            fail('Unknown host aggregate derivation')
        expected = set(by_id) - {'FULL_REQUIREMENT'}
        members = proof.get('constituent_ids', [])
        if len(members) != len(set(members)) or set(members) != expected:
            fail('Host aggregate must identify every unchanged constituent criterion')
        if proof.get('pure_aggregate') is not True:
            continue  # Additional body qualification is a distinct gap, not duplication.
        if not members:
            fail('An empty checklist cannot justify suppressing the overall requirement')
        status = criteria.aggregate([by_id[key] for key in members])
        status = 'SUPPORTED' if status == 'AVAILABLE_CANDIDATE' else status
        if full['status'] != status:
            fail('Pure aggregate status differs from its constituent facts')
        omitted.add(unit['unit_id']+'/FULL_REQUIREMENT')
    return omitted


def _partition_units(engine, payload):
    """Pack complete scope/requirement units; only transport boundaries change."""
    units = {u['unit_id']: u for u in payload['units']}
    if len(units) != len(payload['units']):
        fail('Duplicate necessity unit in partition input')
    counts = {uid: 0 for uid in units}
    keys = set()
    for gap in payload['gaps']:
        if gap['unit_id'] not in units or gap['key'] in keys:
            fail('Unknown or duplicated necessity gap in partition input')
        keys.add(gap['key'])
        counts[gap['unit_id']] += 1
    groups, pending, count = [], [], 0
    for uid in units:
        size = counts[uid]
        if not size:
            continue
        if size > engine.PART_CRITERIA_LIMIT:
            fail('One complete necessity unit exceeds the fixed criterion budget')
        if pending and count + size > engine.PART_CRITERIA_LIMIT:
            groups.append(pending)
            pending, count = [], 0
        pending.append(uid)
        count += size
    if pending:
        groups.append(pending)
    parts = []

    def pack(ids):
        local = engine._part_payload(payload, ids)
        request = engine._request(local)
        chars = len(json.dumps(request, ensure_ascii=False))
        if chars > engine.PART_TARGET_CHARS and len(ids) > 1:
            # Serialize once per candidate packet; split only at complete unit boundaries.
            midpoint = len(ids) // 2
            pack(ids[:midpoint]); pack(ids[midpoint:])
            return
        if chars > engine.data.REQUEST_BUDGET:
            fail('One complete necessity unit exceeds the fixed request budget')
        parts.append({'payload': local, 'request': request, 'request_chars': chars,
            'gap_criteria': len(local['gaps']),
            'schema_chars': len(json.dumps(engine.wire_schema(local), ensure_ascii=False))})

    for ids in groups:
        pack(ids)
    if (len(parts) > min(engine.MAX_PARTS, engine.MAX_PROVIDER_CALLS)
            or sum(p['request_chars'] for p in parts) > engine.MAX_TOTAL_PROVIDER_CHARS):
        fail('Planned necessity calls exceed the fixed cumulative provider budget')
    actual = [g['key'] for part in parts for g in part['payload']['gaps']]
    if len(actual) != len(set(actual)) or set(actual) != keys:
        fail('Necessity partition duplicated or omitted a gap')
    for index, part in enumerate(parts, 1):
        part['part_id'] = 'NEC' + str(index).zfill(2)
    return parts


def _engine():
    """A private module instance prevents changes leaking into historical v4 callers."""
    spec = importlib.util.spec_from_file_location(
        'research_pipeline._necessity_v5_private', legacy.__file__)
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    original_build, original_transport = engine.build_payload, engine.transport_payload
    original_resolve = engine.resolve
    original_check = engine._check_bindings
    engine.VERSION = VERSION
    engine.PART_CRITERIA_LIMIT = 100
    engine.MAX_PARTS = 32
    engine.MAX_PROVIDER_CALLS = 32

    def review_module():
        from . import data_coverage_v5
        return data_coverage_v5

    def build(plan, coverage, catalog, **kwargs):
        if coverage.get('version') != 'COVERAGE_FACTS_5.0' or coverage.get('complete') is not True:
            fail('Necessity requires complete, independently verified v5 coverage')
        # Only the contract discriminator is adapted; facts and source bindings are untouched.
        projection = {**coverage, 'version': 'COVERAGE_FACTS_4.0'}
        payload = original_build(plan, projection, catalog, **kwargs)
        payload['coverage_sha256'] = digest(coverage)
        payload['source_coverage_version'] = coverage['version']
        payload['scoped_exclusions'] = copy.deepcopy(coverage.get('scoped_exclusions', []))
        omitted = _pure_aggregates(payload)
        payload['gaps'] = [g for g in payload['gaps'] if g['key'] not in omitted]
        payload['derived_aggregate_keys'] = sorted(omitted)
        payload['instructions'] += ('\nHost aggregates are immutable summaries of supplied constituent facts. '
            'Do not rejudge a suppressed pure aggregate. Distinct measurement qualification gaps '
            'remain explicit gap criteria. All original action and new-data rules still apply.')
        return payload

    def transport(payload):
        wire = original_transport(payload)
        omitted = set(payload.get('derived_aggregate_keys', []))
        for unit in wire['units']:
            if unit['unit_id']+'/FULL_REQUIREMENT' in omitted:
                full = unit['gap_criteria'].pop('FULL_REQUIREMENT', None)
                if full is not None:
                    unit['host_aggregates'] = {'FULL_REQUIREMENT': {
                        'status': full['status'], 'role': 'DERIVED_SUMMARY_NOT_ANOTHER_DECISION'}}
        return wire

    def check_bindings(bindings):
        if bindings.get('adapter_code') != file_ref(__file__):
            fail('Necessity v5 adapter binding changed or is missing')
        original_check(bindings)

    def resolve(raw, payload):
        result = original_resolve(raw, payload)
        result['source_coverage_version'] = payload['source_coverage_version']
        result['scoped_exclusions'] = copy.deepcopy(payload.get('scoped_exclusions', []))
        return result

    engine._review_module = review_module
    engine.build_payload = build
    engine.transport_payload = transport
    engine._check_bindings = check_bindings
    engine.resolve = resolve
    engine.partition = lambda payload: _partition_units(engine, payload)
    return engine


def build_payload(plan, coverage, catalog, **kwargs):
    return _engine().build_payload(plan, coverage, catalog, **kwargs)


def transport_payload(payload):
    return _engine().transport_payload(payload)


def resolve(raw, payload):
    return _engine().resolve(raw, payload)


def prepare(plan_path, coverage_path, out, **kwargs):
    engine = _engine()
    built = engine.prepare(plan_path, coverage_path, out, **kwargs)
    path = Path(out)/'bindings.json'
    bindings = read_json(path)
    bindings['adapter_code'] = file_ref(__file__)
    write_json(path, bindings)
    engine.verify_prepared(out)
    return built


def checkpoint(out):
    """Read-only status; partial decisions never become a completed assessment."""
    out = Path(out)
    engine = _engine()
    if (out / 'necessity.json').exists():
        return engine.verify_result(out / 'necessity.json')
    _, _, _, parts = engine.verify_prepared(out)
    ledger = read_json(out / 'provider_budget_ledger.json')
    engine._validate_ledger(out, ledger, parts)
    return {'version': VERSION, 'status': 'CHECKPOINTED', 'complete': False,
        'completed_parts': sum(engine._cache(p, out / 'parts' / p['part_id']) is not None for p in parts),
        'total_parts': len(parts), 'provider_elapsed_seconds': ledger['provider_elapsed_seconds'],
        'stop_reason': 'PAUSED' if (out / 'PAUSE').exists() else 'CALL_LIMIT',
        'scientific_approval': False, 'can_enter_qc': False, 'fit_ready': False}


def run_prepared(out, *, generator=None, max_new_calls=1, retry_failed=False, batch=None):
    from .data_coverage_v5 import _alive, admission
    if isinstance(max_new_calls, bool) or not isinstance(max_new_calls, int) or max_new_calls < 0:
        fail('max_new_calls must be a nonnegative integer')
    out = Path(out)
    from .data_live_batch import require_stage_batch
    require_stage_batch(out, batch)
    if batch is not None:
        batch.bind_stage(out, 'necessity')
        generator = batch.generator(out, generator)
    lock = out / 'runtime.lock'
    if lock.exists():
        if _alive(read_json(lock).get('pid')):
            fail('Necessity runtime already active')
        archive = out / 'stale_locks'
        archive.mkdir(exist_ok=True)
        lock.replace(archive / (uuid4().hex + '.json'))
    descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump({'pid': os.getpid()}, stream)
    try:
        engine = _engine()
        if (out / 'necessity.json').exists():
            return engine.verify_result(out / 'necessity.json')
        _, _, _, parts = engine.verify_prepared(out)
        ledger = read_json(out / 'provider_budget_ledger.json')
        engine._validate_ledger(out, ledger, parts)
        engine._recover_interrupted(out, ledger)
        result = checkpoint(out)
        for _ in range(max_new_calls):
            if (out / 'PAUSE').exists():
                return checkpoint(out)
            ledger = read_json(out / 'provider_budget_ledger.json')
            pending = [p for p in parts if engine._cache(p, out / 'parts' / p['part_id']) is None]
            if pending:
                decision = (batch.admission if batch is not None else admission)({'elapsed_seconds': ledger['provider_elapsed_seconds'], 'samples': []},
                                     pending[0]['gap_criteria'])
                if not decision['allowed']:
                    return {**checkpoint(out), 'stop_reason': 'BUDGET_BOUNDARY', 'admission': decision}
            result = engine.run_prepared(out, generator=generator, max_new_calls=1, retry_failed=retry_failed)
            if (out / 'necessity.json').exists():
                return result
        return checkpoint(out)
    finally:
        lock.unlink(missing_ok=True)


def run(plan_path, coverage_path, out, *, generator=None, max_new_calls=1, **kwargs):
    prepare(plan_path, coverage_path, out, **kwargs)
    return run_prepared(out, generator=generator, max_new_calls=max_new_calls)


def verify_result(path):
    return _engine().verify_result(path)
