"""Targeted correction of contradictory returned facts; frozen v5 stays unchanged.

The provider returns only named corrections. A separately labelled host merge
retains every other original byte-level JSON value and records both model turns.
"""
import copy
import json
import os
import time
from pathlib import Path
from uuid import uuid4

from ctxcomp.io import digest
from . import data_coverage_v5 as v
from .adequacy import file_ref
from .common import read_json, write_json, utcnow


def diagnose(payload, raw):
    v.d.validate_schema(raw, v.facts().response_schema(payload))
    return {fid: 'SUPPORTED contradicts retained counterevidence; distinguish a documented rule '
                 'from whether this source scope satisfies it. Return a consistent status and concrete next action.'
            for fid, value in raw['facts'].items() if value['s'] == 'SUPPORTED' and value['x']}


def correction_payload(payload, original, findings):
    if not findings or not set(findings) <= set(payload['facts']):
        v.fail('Correction requires named original fact diagnostics')
    result = copy.deepcopy(payload)
    result['facts'] = {fid: copy.deepcopy(payload['facts'][fid]) for fid in findings}
    scopes = {f['scope_id'] for f in result['facts'].values()}
    units = {t['unit_id'] for f in result['facts'].values() for t in f['targets']}
    result['scopes'] = [s for s in result['scopes'] if s['id'] in scopes]
    result['units'] = [u for u in result['units'] if u['unit_id'] in units]
    allowed = {item for s in result['scopes'] for item in s['item_ids']}
    allowed |= set(result.get('extra_item_ids', []))
    allowed |= {item for sid in scopes for item in result.get('authorized_extra_items', {}).get(sid, [])}
    cited = {index for fid in findings for key in ('e', 'x') for index in original['facts'][fid][key]}
    result['source_rows'] = [row for row in result['source_rows']
        if (row[2] is None or row[2] in allowed) and
        (row[2] is None or row[4] in cited or row[1] in {'SOURCE_NOTE', 'SOURCE_HEADER', 'DESCRIPTOR'})]
    result['source_projection'] = 'ORIGINAL_AUTHORITIES_AND_TARGET_SCOPE_CONTEXT_PLUS_ALL_ORIGINAL_TARGET_CITATIONS; UNRELATED_MEASUREMENTS_NOT_REREAD'
    result['visible_item_ids'] = [item for item in result.get('visible_item_ids', []) if item in allowed]
    requirements = {u['requirement']['id'] for u in result['units']}
    result['requirements'] = {key: value for key, value in result.get('requirements', {}).items() if key in requirements}
    result['authorized_extra_items'] = {key: value for key, value in result.get('authorized_extra_items', {}).items() if key in scopes}
    for key in ('retained_source_links', 'counterevidence_targets'):
        result[key] = {uid: value for uid, value in result.get(key, {}).items() if uid in units}
    result['part_id'] += '_CORRECTION'
    result['correction_diagnostics'] = findings
    result['prior_target_answers_NON_EVIDENCE'] = {fid: original['facts'][fid] for fid in findings}
    result['fixed_unit_metadata'] = {uid: original['unit_metadata'][uid] for uid in units}
    result['preserved_other_facts_sha256'] = digest({fid: value for fid, value in original['facts'].items() if fid not in findings})
    result['instructions'] += ('\nTARGETED CORRECTION ONLY: return only the named facts. Do not seek PASS. '
        'Keep all original support and counterevidence selectors; their source text remains immutable. '
        'Reconsider status, factual reason, needed action and evidence kind together. A rule being documented '
        'does not establish that this scope satisfies it. Respect original applicability conditions; do not '
        'transfer another pathogen or experimental scope. PARTIAL, CONFLICT and UNRESOLVED remain valid. '
        'All other facts and unit metadata stay unchanged. Do not invent new measurements or approve experiments.')
    schema = v.facts().response_schema(result)
    del schema['properties']['unit_metadata']
    schema['required'].remove('unit_metadata')
    return v.facts().transport_payload(result), schema


def governed_request(payload, schema):
    class Capture(Exception):
        pass
    caller = v.planning.sf.private_module()
    def capture(p):
        exc = Capture()
        exc.request = v.d.governed_request(p)
        raise exc
    caller.governed_request = capture
    try:
        caller.invoke(Path('.'), 'DC-review', payload, schema, model=v.MODEL)
    except Capture as exc:
        request = exc.request
    if len(json.dumps(request, ensure_ascii=False)) > v.d.REQUEST_BUDGET:
        v.fail('Targeted correction request exceeds original transport budget')
    return request


def prepare(out, failed_attempt_id, repair_dir):
    out, repair_dir = Path(out).resolve(), Path(repair_dir).resolve()
    if repair_dir.exists() and any(repair_dir.iterdir()):
        v.fail('Correction requires a new empty artifact directory')
    built = v._load(out)
    attempt_path = out/'attempts'/(failed_attempt_id+'.json')
    attempt = read_json(attempt_path)
    if attempt['status'] != 'FAILED' or attempt['build_sha256'] != digest(built):
        v.fail('Correction must name a failed attempt of this unchanged build')
    v._check_duration(attempt)
    part = attempt['part_id']
    if (out/'accepted'/(part+'.json')).exists():
        v.fail('Do not repair an already accepted part')
    raw_paths = list((out/'calls'/failed_attempt_id/'data_agents/audit/DC-review').glob('*/response.json'))
    if len(raw_paths) != 1:
        v.fail('No unique original failed response')
    original = read_json(raw_paths[0])
    request_path = out/'requests'/(part+'.json')
    request = read_json(request_path)
    if read_json(raw_paths[0].with_name('request.json')) != request or original['request_sha256'] != request['request_sha256']:
        v.fail('Original failed response does not match its request')
    payload = next(p for p in built['payloads'] if p['part_id'] == part)
    findings = diagnose(payload, original)
    wire, schema = correction_payload(payload, original, findings)
    corrected_request = governed_request(wire, schema)
    plan = {'version': 'TARGETED_FACT_CORRECTION_1.0', 'out': str(out), 'part_id': part,
        'targets': list(findings), 'diagnostics': findings,
        'refs': {'build': file_ref(out/'build.json'), 'failed_attempt': file_ref(attempt_path),
            'original_raw': file_ref(raw_paths[0]), 'original_request': file_ref(request_path),
            'repair_code': file_ref(__file__)}, 'payload': wire, 'schema': schema,
        'preserved_other_facts': len(original['facts'])-len(findings)}
    write_json(repair_dir/'request.json', corrected_request)
    plan['refs']['correction_request'] = file_ref(repair_dir/'request.json')
    write_json(repair_dir/'plan.json', plan)
    return plan


def load(repair_dir):
    repair_dir = Path(repair_dir)
    plan = read_json(repair_dir/'plan.json')
    v.planning.check_refs(plan['refs'])
    if plan['refs']['repair_code'] != file_ref(__file__):
        v.fail('Correction implementation changed')
    built = v._load(plan['out'])
    original = read_json(plan['refs']['original_raw']['path'])
    payload = next(p for p in built['payloads'] if p['part_id'] == plan['part_id'])
    findings = diagnose(payload, original)
    wire, schema = correction_payload(payload, original, findings)
    if (list(findings) != plan['targets'] or findings != plan['diagnostics'] or wire != plan['payload'] or
            schema != plan['schema'] or governed_request(wire, schema) != read_json(repair_dir/'request.json')):
        v.fail('Correction request does not replay from its original response')
    return plan, built, payload, original


def merge(original, correction, targets, request, schema):
    v.d.validate_schema(correction, schema)
    if correction['request_sha256'] != request['request_sha256'] or set(correction['facts']) != set(targets):
        v.fail('Correction response does not match exact named targets/request')
    result = copy.deepcopy(original)
    for fid in targets:
        before, after = original['facts'][fid], correction['facts'][fid]
        if any(not set(before[key]) <= set(after[key]) for key in ('e', 'x')):
            v.fail('Correction cannot discard original support or counterevidence')
        result['facts'][fid] = copy.deepcopy(after)
    return result


def verify_merge(repair_dir):
    repair_dir = Path(repair_dir)
    plan, built, payload, original = load(repair_dir)
    lineage = read_json(repair_dir/'merge_lineage.json')
    v.planning.check_refs(lineage['refs'])
    merged = merge(original, read_json(repair_dir/'response.json'), plan['targets'],
                   read_json(repair_dir/'request.json'), plan['schema'])
    if read_json(repair_dir/'merged/response.json') != merged:
        v.fail('Derived correction differs from immutable original plus named changes')
    matches = v.facts().materialize(merged, payload, built['catalog'])
    if lineage['matches_sha256'] != digest(matches):
        v.fail('Derived correction materialization changed')
    return merged


def finalize(repair_dir):
    repair_dir = Path(repair_dir)
    plan, built, payload, original = load(repair_dir)
    out = Path(plan['out'])
    attempt_path = Path(read_json(repair_dir/'execution.json')['attempt_path'])
    attempt = read_json(attempt_path)
    v._check_duration(attempt)
    merged = merge(original, read_json(repair_dir/'response.json'), plan['targets'],
                   read_json(repair_dir/'request.json'), plan['schema'])
    matches = v.facts().materialize(merged, payload, built['catalog'])
    write_json(repair_dir/'merged/response.json', merged)
    write_json(repair_dir/'merged/request.json', read_json(plan['refs']['original_request']['path']))
    lineage = {'origin': 'HOST_DERIVED_TARGETED_CORRECTION_NOT_A_NEW_FULL_MODEL_RESPONSE',
        'targets': plan['targets'], 'preserved_other_facts': plan['preserved_other_facts'],
        'unit_metadata': 'UNCHANGED_ORIGINAL', 'matches_sha256': digest(matches),
        'refs': {**plan['refs'], 'plan': file_ref(repair_dir/'plan.json'),
                 'correction_raw': file_ref(repair_dir/'response.json'),
                 'merged_raw': file_ref(repair_dir/'merged/response.json')}}
    write_json(repair_dir/'merge_lineage.json', lineage)
    verify_merge(repair_dir)
    receipt = v._accept_raw(out, built, payload, attempt, repair_dir/'merged/response.json')
    diagnostic = v._diagnostics(repair_dir/'model_call')
    receipt.update(response_origin=lineage['origin'], requested_model=v.MODEL,
                   served_model=diagnostic['served_model'], served_models=diagnostic['served_models'])
    receipt['refs'].update(lineage['refs'], merge_lineage=file_ref(repair_dir/'merge_lineage.json'))
    if (repair_dir/'model_call/call.json').exists():
        receipt['refs']['correction_model_call'] = file_ref(repair_dir/'model_call/call.json')
    write_json(out/'accepted'/(plan['part_id']+'.json'), receipt)
    attempt.update(status='ACCEPTED', model_record=diagnostic, response_origin=lineage['origin'],
                   merge_lineage_ref=file_ref(repair_dir/'merge_lineage.json'))
    write_json(attempt_path, attempt)
    v.emit(out, 'TARGETED_CORRECTION_ACCEPTED', part_id=plan['part_id'], targets=plan['targets'],
           original_failed_attempt=read_json(plan['refs']['failed_attempt']['path'])['id'])
    return v.rebuild_checkpoint(out)


def run_prepared(repair_dir, *, batch, generator=None):
    repair_dir = Path(repair_dir).resolve()
    plan, built, payload, _ = load(repair_dir)
    out = Path(plan['out'])
    lock = out/'runtime.lock'
    with lock.open('x', encoding='utf-8') as stream:
        json.dump({'pid': os.getpid(), 'at': utcnow(), 'operation': 'TARGETED_CORRECTION'}, stream)
    try:
        batch.bind_stage(out, 'coverage')
        if (repair_dir/'response.json').exists():
            return finalize(repair_dir)  # Recovery/replay never dispatches another call.
        if (repair_dir/'execution.json').exists():
            v.fail('A prior correction attempt exists; inspect it before an explicit new correction')
        if (out/'accepted'/(plan['part_id']+'.json')).exists():
            v.fail('Part already accepted; do not dispatch another correction')
        decision = batch.admission(v._ledger(out, built), len(plan['targets']))
        if not decision['allowed']:
            v.fail('Correction exceeds the explicitly authorized batch budget')
        call_id = uuid4().hex
        attempt_path = out/'attempts'/(call_id+'.json')
        attempt = {'id': call_id, 'part_id': plan['part_id'], 'build_sha256': digest(built),
            'status': 'RUNNING', 'owner_pid': os.getpid(), 'started_at': utcnow(),
            'checks': len(plan['targets']), 'requested_model': v.MODEL, 'served_model': None,
            'provider_started': True, 'timeout_seconds': decision['remaining_seconds']-v.RESERVE_SECONDS,
            'request_ref': file_ref(repair_dir/'request.json'), 'prediction': decision,
            'response_origin': 'TARGETED_CORRECTION_REQUEST', 'repair_plan_ref': file_ref(repair_dir/'plan.json')}
        write_json(repair_dir/'execution.json', {'attempt_path': str(attempt_path)})
        write_json(attempt_path, attempt)
        started = time.monotonic()
        try:
            try:
                raw = batch.generator(out, generator)(read_json(repair_dir/'request.json'), model=v.MODEL,
                    timeout=attempt['timeout_seconds'], diagnostics_dir=repair_dir/'model_call')
                write_json(repair_dir/'response.json', raw)
            finally:
                attempt.update(elapsed_seconds=time.monotonic()-started, ended_at=utcnow())
                write_json(attempt_path, attempt)
                v._ledger(out, built)
            return finalize(repair_dir)
        except BaseException as exc:
            attempt.update(status='INTERRUPTED' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'FAILED',
                           error=str(exc), model_record=v._diagnostics(repair_dir/'model_call'))
            write_json(attempt_path, attempt)
            raise
    finally:
        lock.unlink(missing_ok=True)
