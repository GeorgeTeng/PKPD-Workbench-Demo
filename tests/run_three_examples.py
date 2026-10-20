"""Sequential, real HTTP acceptance of the three packaged examples through Data.

The existing single-example driver owns progression and authorized gates. This
wrapper independently checks persisted gates, downloaded artifact hashes, actual
Data outputs, model request identity, and that downstream nodes never started.
It never repairs Context or retries a failed example automatically.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import quote
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ('pmb', 'meropenem', 'voriconazole')
UPSTREAM = ('intake', 'context', 'adequacy', 'prepare')
GATES = ('context', 'adequacy', 'prepare')
PROFILE = 'SOURCE_PRESERVING_DEMO_1.0'
SCOPE = 'SOURCE_ORGANIZATION_AND_TECHNICAL_QC_ONLY'


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def stamp():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def fetch(base, path):
    with urlopen(base.rstrip('/') + path, timeout=120) as response:
        return response.read()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def expected_effort(value):
    """API receipts may intentionally omit the Codex-specific effort field."""
    return None if value.lower() == 'none' else value


def model_calls(state_root):
    """Only call receipts, never prompt contents or credentials."""
    outputs = state_root / 'workbench_outputs'
    return {str(p.resolve()): digest(p.read_bytes()) for p in outputs.rglob('call.json')}


def relevant_calls(state_root, session_id, baseline, expected_model, expected_effort):
    session = read_json(state_root / 'workbench_state/canvas_sessions' / session_id / 'session.json')
    jobs = set(session.get('job_history', []))
    if session.get('job_id'):
        jobs.add(session['job_id'])
    # Context artifacts may belong to an earlier job preserved by a retry.
    output_root = (state_root / 'workbench_outputs').resolve()
    run_dirs = set()
    for node in session['nodes'].values():
        for artifact in node.get('artifacts', []):
            path = Path(artifact['path']).resolve()
            if path.is_relative_to(output_root):
                relative = path.relative_to(output_root)
                if relative.parts:
                    run_dirs.add(output_root / relative.parts[0])
    for job in jobs:
        spec_path = state_root / 'workbench_state/workbench_jobs' / job / 'request.json'
        if spec_path.is_file():
            run_dirs.add(Path(read_json(spec_path)['out']).resolve())
    receipts = []
    seen = set()
    historical_hashes = set(baseline.values())
    for run in sorted(run_dirs):
        require(run.is_relative_to(output_root), 'Model receipt directory escapes demo outputs')
        for path in sorted(run.rglob('call.json')):
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            raw = path.read_bytes()
            call = json.loads(raw)
            fresh = baseline.get(key) != digest(raw) and digest(raw) not in historical_hashes
            entry = {k: call[k] for k in ('provider', 'requested_model', 'requested_reasoning_effort',
                'status', 'request_sha256', 'served_models', 'served_model_verified',
                'started_at', 'finished_at') if k in call}
            entry.update(path=key, sha256=digest(raw), new_or_changed=fresh)
            entry['served_identity_status'] = ('REPORTED' if call.get('served_models') else 'NOT_REPORTED')
            receipts.append(entry)
            if fresh and call.get('status') == 'RETURNED':
                require(call.get('requested_model') == expected_model,
                        f'Unexpected requested model in {path}: {call.get("requested_model")}')
                require(call.get('requested_reasoning_effort') == expected_effort,
                        f'Unexpected reasoning effort in {path}: {call.get("requested_reasoning_effort")}')
    require(receipts, 'No real model call receipts found for this session')
    return receipts


def validate(base, session_id, state_root, baseline, expected_model, expected_effort):
    prefix = '/ui-api/workflow/sessions/' + quote(session_id, safe='')
    state = json.loads(fetch(base, prefix))
    nodes = {n['id']: n['state'] for n in state['nodes']}
    local_session = read_json(state_root / 'workbench_state/canvas_sessions' / session_id / 'session.json')
    require(local_session['id'] == session_id, 'Local session does not match the HTTP session')
    output_root = (state_root / 'workbench_outputs').resolve()
    require(state.get('context_revision_child') is None, 'Unexpected Context revision child')
    for node in UPSTREAM:
        require(nodes[node]['execution'] == 'COMPLETED', f'{node} did not complete')
        require(nodes[node].get('approved') is True, f'{node} is not approved')
    gates = []
    for node in GATES:
        value = nodes[node]
        review = value.get('review') or {}
        require(review.get('decision') == 'APPROVE', f'{node} lacks its visible review record')
        require(review.get('output_signature') == value.get('output_signature'), f'{node} review signature mismatch')
        require((value.get('langgraph_review') or {}).get('status') == 'APPROVED', f'{node} checkpoint is not approved')
        gates.append({'node': node, 'output_signature': value['output_signature'], 'review': review,
                      'checkpoint': value['langgraph_review']})
    downstream = {key: value['execution'] for key, value in nodes.items() if key not in UPSTREAM}
    require(all(value == 'NOT_STARTED' for value in downstream.values()), f'Downstream execution detected: {downstream}')
    verified = []
    documents = {}
    # Verify every actual file locally, then verify public downloads of reports,
    # manifests and a complete representative dataset. Native download endpoints
    # recheck the whole node on every GET; fetching every file makes that O(N^2).
    local_bytes = {}
    http_verified = set()
    http_samples = []
    public_names = {'manifest.json', 'main.json', 'project_rules.json', 'adequacy.json', 'qc_context.json',
        'requirements.json', 'data_labels.json', 'data_report.json', 'source_tables.json',
        'normalized_manifest.json', 'data_dictionary.json', 'cleaning_log.json', 'partition_manifest.json',
        'program_qc.json', 'qc_findings.json', 'unresolved_ledger.json', 'handoff_review.json',
        'demo_context_review.json', 'independent_context_review.json',
        'eda_context.json', 'pk_context.json', 'index_context.json'}

    def verify_download(node, artifact):
        sha = artifact['sha256']
        if sha not in http_verified:
            endpoint = prefix + '/nodes/' + node + '/artifacts/' + quote(artifact['name'], safe='')
            transport_bytes = fetch(base, endpoint)
            require(digest(transport_bytes) == sha,
                    f'HTTP artifact hash mismatch: {node}/{artifact["name"]}')
            http_verified.add(sha)
            http_samples.append({'node': node, 'name': artifact['name'], 'sha256': sha,
                                 'bytes': len(transport_bytes), 'endpoint': endpoint,
                                 'verification': 'HTTP_RESPONSE_SHA256'})

    for node in UPSTREAM:
        local_node = local_session['nodes'][node]
        require(local_node.get('output_signature') == nodes[node].get('output_signature'),
                f'Local/HTTP output signature mismatch for {node}')
        local_refs = {(a['name'], a['sha256']): a for a in local_node['artifacts']}
        for artifact in nodes[node]['artifacts']:
            sha = artifact['sha256']
            local_ref = local_refs.get((artifact['name'], sha))
            require(local_ref is not None, f'HTTP artifact lacks matching local reference: {node}/{artifact["name"]}')
            local_path = Path(local_ref['path']).resolve()
            require(local_path.is_relative_to(output_root), 'Artifact file escapes the local outputs directory')
            if local_path not in local_bytes:
                local_bytes[local_path] = local_path.read_bytes()
            raw = local_bytes[local_path]
            require(digest(raw) == sha, f'Artifact hash mismatch: {node}/{artifact["name"]}')
            verified.append({'node': node, 'name': artifact['name'], 'sha256': sha, 'bytes': len(raw),
                             'local_path': str(local_path), 'verification': 'LOCAL_FILE_SHA256'})
            if artifact['name'].endswith('.json'):
                documents[(node, artifact['name'])] = json.loads(raw)
            if artifact['name'] in public_names:
                verify_download(node, artifact)
    required = {'context': {'main.json', 'project_rules.json'},
                'adequacy': {'adequacy.json', 'requirements.json', 'data_labels.json', 'qc_context.json'},
                'prepare': {'data_report.json', 'source_tables.json', 'normalized_manifest.json',
                            'data_dictionary.json', 'cleaning_log.json', 'partition_manifest.json'}}
    for node, names in required.items():
        actual = {a['name'] for a in nodes[node]['artifacts']}
        require(names <= actual, f'Missing actual artifacts in {node}: {sorted(names - actual)}')
    source = documents[('prepare', 'source_tables.json')]
    normalized = documents[('prepare', 'normalized_manifest.json')]
    require(source.get('tables'), 'No extracted source tables')
    require(normalized.get('datasets'), 'No actual normalized Data datasets')
    verified_hashes = {a['sha256'] for a in verified if a['node'] == 'prepare'}
    for dataset in normalized['datasets']:
        for key in ('data', 'csv', 'metadata_file', 'quarantine'):
            require((dataset.get(key) or {}).get('sha256') in verified_hashes,
                    f'Actual {key} bytes missing from verified Data artifacts for {dataset.get("id")}')
    for key in ('data', 'csv', 'metadata_file', 'quarantine'):
        sha = normalized['datasets'][0][key]['sha256']
        artifact = next(a for a in nodes['prepare']['artifacts'] if a['sha256'] == sha)
        verify_download('prepare', artifact)
    summary = documents[('prepare', 'data_report.json')]
    assessment = documents[('adequacy', 'adequacy.json')]
    requirements = documents[('adequacy', 'requirements.json')]
    labels = documents[('adequacy', 'data_labels.json')]
    require(summary.get('scientific_release') is False, 'Data report must explicitly prohibit scientific release')
    require(summary.get('demo_profile') == PROFILE and summary.get('execution_scope') == SCOPE,
            'Data report does not declare the selected technical demo profile')
    require(summary.get('status') == 'DEMO_TECHNICAL_DATA_READY', 'Data technical processing is not ready')
    require(summary.get('technical_processing_complete') is True and summary.get('cleaning_complete') is True,
            'Source-preserving preparation and technical QC did not complete')
    require(summary.get('fit_ready') is False and summary.get('handoff_review_complete') is False,
            'Demo must retain deferred scientific readiness/review')
    require(summary.get('requires_human_review') is True and assessment.get('requires_human_review') is True,
            'Demo must retain visible Human review gates')
    require(assessment.get('demo_profile') == PROFILE and assessment.get('scientific_release') is False,
            'Assessment does not retain technical-demo scientific release boundary')
    require((assessment.get('llm_review') or {}).get('decision') == 'NOT_RUN_IN_DEMO',
            'Assessment must explicitly defer full scientific DC review')
    require({r['id'] for r in assessment.get('requirements', [])} == {r['id'] for r in requirements['requirements']},
            'Technical assessment dropped or added scientific requirements')
    require(all(r.get('coverage_status') == 'NOT_ASSESSED_IN_DEMO' for r in assessment['requirements']),
            'Technical assessment implied scientific requirement coverage')
    fingerprints = lambda values: {json.dumps(v, sort_keys=True, ensure_ascii=False) for v in values}
    require(fingerprints(requirements.get('findings', []) + labels.get('findings', [])) <= fingerprints(assessment['findings']),
            'Upstream requirements/label findings were dropped')
    require(fingerprints(assessment['findings']) <= fingerprints(summary['findings']),
            'Data report dropped assessment findings')
    deferred_context = None
    deferral_ref = documents[('context', 'main.json')].get('demo_context_review_ref')
    if deferral_ref:
        deferred_context = documents.get(('context', 'demo_context_review.json'))
        independent = documents.get(('context', 'independent_context_review.json'))
        require(deferred_context is not None and independent is not None,
                'Deferred Context review lacks its actual receipt and independent review artifacts')
        for reference, name in ((deferral_ref, 'demo_context_review.json'),
                                (deferred_context['review_ref'], 'independent_context_review.json')):
            actual = next(a for a in verified if a['node'] == 'context' and a['name'] == name)
            require(reference['sha256'] == actual['sha256']
                    and Path(reference['path']).resolve() == Path(actual['local_path']).resolve(),
                    f'Deferred Context review reference does not bind exact bytes/location: {name}')
        require(deferred_context.get('original_review_decision') == 'REVISE'
                and deferred_context.get('candidate_changed') is False
                and deferred_context.get('independent_review_passed') is False
                and deferred_context.get('scientific_release') is False,
                'Deferred Context review changed the independent verdict, candidate or release boundary')
        review = independent['review']
        require(review['decision'] == 'REVISE' and review.get('critical_errors') == []
                and independent['candidate_sha256'] == deferred_context['candidate_sha256'],
                'Deferred Context receipt does not retain the exact independent review/candidate')
        require(review['records'] and review['source_units']
                and all(r[k] == 'PRESERVED' for r in review['records'] for k in ('faithfulness', 'completeness'))
                and all(u['verdict'] == 'PRESERVED' for u in review['source_units']),
                'Deferred Context includes a scientific preservation failure')
        known_records = {r['id'] for r in review['records']}
        require(review['fixes'] and all(f['target'] in known_records for f in review['fixes']),
                'Deferred Context includes an unsupported new repair target')
        defects = [c for c in review['checks'] if c['verdict'] != 'PRESERVED']
        require(len(defects) == 1 and defects[0]['id'] == 'canonical_placement_no_duplicate_gaps'
                and defects[0]['verdict'] == 'ALTERED',
                'Deferred Context extends beyond its sole canonical-placement defect')
        findings = deferred_context['findings']
        require(findings and all(f['severity'] == 'HUMAN_REVIEW' and f['required_by'] == 'BEFORE_EDA' for f in findings),
                'Deferred Context findings lost their visible review deadline')
        require(fingerprints(findings) <= fingerprints(assessment['findings'])
                and fingerprints(findings) <= fingerprints(summary['findings']),
                'Deferred Context findings were dropped before final Data')
        ledger = documents.get(('prepare', 'unresolved_ledger.json'))
        require(ledger is not None, 'Deferred Context findings lack the final unresolved ledger')

        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for child in value.values():
                    yield from strings(child)
            elif isinstance(value, list):
                for child in value:
                    yield from strings(child)

        ledger_text = list(strings(ledger))
        require(all(any(f['reason'] in text for text in ledger_text) for f in findings),
                'Deferred Context findings were dropped from the final unresolved ledger')
    for name in ('eda_context.json', 'pk_context.json', 'index_context.json'):
        handoff = documents.get(('prepare', name))
        require(handoff is not None, f'Missing actual downstream inspection handoff: {name}')
        require(handoff.get('execution_authorized') is False and handoff.get('scientific_release') is False
                and handoff.get('status') == 'PENDING_SCIENTIFIC_REVIEW',
                f'{name} does not preserve deferred scientific execution')
    calls = relevant_calls(state_root, session_id, baseline, expected_model, expected_effort)
    return {'status': 'PASSED_THROUGH_DATA', 'session_id': session_id, 'gates': gates,
            'downstream_executions': downstream, 'verified_artifacts': verified,
            'byte_verification': 'ALL_LOCAL_ARTIFACTS_PLUS_HTTP_REPORTS_MANIFESTS_AND_REPRESENTATIVE_DATASET',
            'http_verified_unique_hashes': len(http_verified),
            'http_transport_samples': http_samples,
            'artifact_counts': dict(Counter(a['node'] for a in verified)),
            'source_table_count': len(source['tables']), 'normalized_dataset_count': len(normalized['datasets']),
            'data_report': summary, 'adequacy_report': assessment,
            'requirement_count': len(requirements['requirements']), 'data_label_count': len(labels['labels']),
            'deferred_context_review': deferred_context,
            'model_calls': calls, 'scientific_release': False, 'independent_human_review': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:8772')
    parser.add_argument('--state-root', type=Path, default=ROOT / 'state')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--pmb-session', help='Explicit existing source-bound PMB flow to reuse')
    parser.add_argument('--approve-test-gates', action='store_true')
    parser.add_argument('--expected-model', default='gpt-6.1-sol')
    parser.add_argument('--expected-effort', default='high', type=expected_effort,
                        help='Expected requested_reasoning_effort; none requires an absent/null field (default: high)')
    parser.add_argument('--timeout-seconds', type=int, default=None,
                        help='Optional driver process deadline; no deadline by default')
    parser.add_argument('--stop-after-example', choices=EXAMPLES,
                        help='Save independently verified results and stop safely before importing the next example')
    args = parser.parse_args()
    if not args.approve_test_gates:
        parser.error('Explicit --approve-test-gates authorization is required')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.output_dir / 'three_examples_acceptance.json'
    initial_report = {'status': 'RUNNING', 'started_at': stamp(), 'scope': 'INTAKE_CONTEXT_DATA_ONLY',
        'execution': 'SEQUENTIAL_LIVE_HTTP', 'context_scientific_revision_loops': 0,
        'gate_reviewer': 'USER_AUTHORIZED_DEMO_ACCEPTANCE', 'independent_human_review': False,
        'scientific_release': False, 'eda_executed': False, 'pk_executed': False,
        'expected_requested_model': args.expected_model, 'expected_reasoning_effort': args.expected_effort,
        'examples': [], 'invocations': []}
    report = read_json(report_path) if report_path.exists() else initial_report
    require(report.get('scope') == initial_report['scope'], 'Existing report has a different execution scope')
    require(report.get('expected_requested_model') == args.expected_model,
            'Existing report has a different requested model; use a new output directory')
    require(report.get('expected_reasoning_effort') == args.expected_effort,
            'Existing report has a different reasoning effort; use a new output directory')
    report.setdefault('invocations', []).append({'started_at': stamp(), 'prior_status': report['status'],
                                                'prior_boundary_after': report.get('boundary_after')})
    report['status'] = 'RUNNING'
    report.pop('error', None)
    report.pop('finished_at', None)
    report.pop('boundary_after', None)
    report.pop('boundary_at', None)

    def save():
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')

    def hold_after(example):
        if args.stop_after_example != example:
            return False
        report.update(status='WAITING_AT_EXAMPLE_BOUNDARY', boundary_after=example, boundary_at=stamp())
        save()
        print(json.dumps({'event': 'HELD_AT_VERIFIED_EXAMPLE_BOUNDARY', 'example': example,
                          'report': str(report_path.resolve())}), flush=True)
        return True

    save()
    active_item = None
    try:
        available = json.loads(fetch(args.base, '/workspace-api/examples'))
        require(set(EXAMPLES) <= {e['id'] for e in available}, 'An expected example is missing from the catalog')
        report['packaged_examples'] = available
        save()
        for example in EXAMPLES:
            started = stamp()
            baseline = model_calls(args.state_root)
            item = next((i for i in report['examples'] if i['example'] == example), None)
            if item is None:
                item = {'example': example, 'status': 'NOT_STARTED', 'attempts': []}
                report['examples'].append(item)
            active_item = item
            session_id = item.get('session_id')
            # A previous wrapper may have stopped while its driver's durable
            # report already recorded the imported flow. Recover that flow.
            previous_output = Path(item['driver_report']) if item.get('driver_report') else None
            if previous_output and previous_output.is_file():
                previous_driver = read_json(previous_output)
                session_id = previous_driver.get('session_id') or session_id
            if example == 'pmb' and args.pmb_session:
                require(not session_id or session_id == args.pmb_session,
                        'Explicit PMB flow differs from the existing report; use its recorded flow or a new output directory')
                session_id = args.pmb_session
            if session_id and item['status'] == 'PASSED_THROUGH_DATA':
                item.update(validate(args.base, session_id, args.state_root, baseline,
                                     args.expected_model, args.expected_effort))
                item['last_reverified_at'] = stamp()
                save()
                print(json.dumps({'event': 'EXAMPLE_REVERIFIED_WITHOUT_EXECUTION', 'example': example,
                                  'session_id': session_id}), flush=True)
                if hold_after(example):
                    return 0
                continue
            attempts = item.setdefault('attempts', [])
            # Preserve previous single-example reports and logs on every retry.
            attempt = len(attempts) + 1
            output = args.output_dir / f'{example}_driver_attempt_{attempt:02d}.json'
            require(not output.exists(), 'Refusing to replace an existing driver attempt report')
            command = [sys.executable, str(ROOT / 'tests/run_data_acceptance.py'), '--base', args.base,
                       '--example', example, '--max-context-repairs', '0', '--approve-test-gates', '--output', str(output)]
            if session_id:
                command += ['--session', session_id]
            attempt_record = {'attempt': attempt, 'started_at': started, 'status': 'RUNNING',
                              'driver_report': str(output.resolve()), 'command': command,
                              'continued_session_id': session_id}
            attempts.append(attempt_record)
            item.update(status='RUNNING', started_at=started, driver_report=str(output.resolve()), command=command)
            item.pop('error', None)
            save()
            print(json.dumps({'event': 'EXAMPLE_STARTED', 'example': example, 'at': started}), flush=True)
            with output.with_suffix('.log').open('w', encoding='utf-8') as log:
                child_environment = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
                result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                        timeout=args.timeout_seconds, check=False, env=child_environment)
            item['driver_exit_code'] = result.returncode
            driver = read_json(output)
            item['session_id'] = driver.get('session_id')
            attempt_record.update(driver_exit_code=result.returncode, session_id=driver.get('session_id'),
                                  status=driver['status'], finished_at=stamp(), error=driver.get('error'))
            require(result.returncode == 0 and driver['status'] == 'PASSED_THROUGH_DATA',
                    f'{example} stopped: {driver.get("error", driver["status"])}')
            item.update(validate(args.base, driver['session_id'], args.state_root, baseline,
                                 args.expected_model, args.expected_effort))
            item['finished_at'] = stamp()
            save()
            print(json.dumps({'event': 'EXAMPLE_VERIFIED', 'example': example,
                              'session_id': item['session_id'], 'artifact_counts': item['artifact_counts']}), flush=True)
            if hold_after(example):
                return 0
        report['status'] = 'ALL_THREE_PASSED_THROUGH_DATA'
        report['finished_at'] = stamp()
        save()
        print(json.dumps({'status': report['status'], 'report': str(report_path.resolve())}), flush=True)
        return 0
    except Exception as exc:
        report.update(status='FAILED', error=str(exc), finished_at=stamp())
        if active_item is not None:
            was_running = active_item['status'] == 'RUNNING'
            active_item.update(status='FAILED', error=str(exc))
            if was_running and active_item.get('attempts'):
                active_item['attempts'][-1].update(status='FAILED', error=str(exc), finished_at=stamp())
        save()
        print(json.dumps({'status': 'FAILED', 'error': str(exc), 'report': str(report_path.resolve())}), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
